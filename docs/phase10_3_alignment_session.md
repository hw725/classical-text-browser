# Phase 10-3: 정렬 엔진 — OCR ↔ 텍스트 대조

> Claude Code 세션 지시문
> 이 문서를 읽고 작업 순서대로 구현하라.

---

## 사전 준비

1. CLAUDE.md를 먼저 읽어라.
2. docs/DECISIONS.md를 읽어라.
3. docs/phase10_12_design.md의 Phase 10-3 섹션을 읽어라.
4. 이 문서 전체를 읽은 후 작업을 시작하라.
5. **이미 완료된 Phase 10-1(OCR), 10-2(LLM)의 코드 구조를 확인하라**:
   - `src/ocr/` — OCR 결과 데이터 모델 (OcrBlockResult, OcrLineResult)
   - `src/ocr/pipeline.py` — L2 JSON 저장 형식
   - `src/core/` — 기존 핵심 로직 파일들
   - `src/api/` — 기존 API 라우터 패턴
   - `static/js/` — 기존 GUI (특히 correction-editor.js)

---

## 설계 요약 — 반드시 이해한 후 구현

### 핵심 원칙

- **글자 단위 대조**: OCR 텍스트(L2)와 참조 텍스트(L4)를 한 글자씩 비교한다.
- **이체자 보정**: 불일치 중 이체자 관계인 쌍은 별도 분류한다 (說/説, 經/経 등).
- **블록 단위 매칭**: layout_block_id로 L2 블록과 L4 블록을 매칭한다.
- **비파괴**: 대조는 읽기 전용 — L2나 L4 데이터를 수정하지 않는다.

### 정렬 알고리즘 개요

```
입력:
  ocr_text  = "王戎簡要裵楷通"      (L2 OCR 결과)
  ref_text  = "王戎簡要裴楷清通"    (L4 확정 텍스트)

1단계 — difflib.SequenceMatcher:
  SequenceMatcher(None, ocr_text, ref_text)
  opcodes:
    ('equal',   0, 4, 0, 4)  →  王戎簡要 = 王戎簡要
    ('replace', 4, 5, 4, 5)  →  裵 → 裴          (불일치)
    ('equal',   5, 6, 5, 6)  →  楷 = 楷
    ('insert',  6, 6, 6, 7)  →  (없음) → 清       (OCR 누락)
    ('equal',   6, 7, 7, 8)  →  通 = 通

2단계 — 이체자 보정:
  裵/裴 → variant_chars.json에 있으면 → match_type를 "mismatch" → "variant"로 변경

최종 결과:
  王(exact) 戎(exact) 簡(exact) 要(exact) 裵/裴(variant) 楷(exact) ×/清(deletion) 通(exact)
```

### 대조 유형 (AlignedPair.match_type)

| 유형 | 의미 | 색상 | 예시 |
|------|------|------|------|
| `exact` | 완전 일치 | 초록 ✅ | 王 = 王 |
| `variant` | 이체자 (同字異形) | 노랑 🟡 | 裵 ≈ 裴 |
| `mismatch` | 불일치 (다른 글자) | 빨강 🔴 | 甲 ≠ 乙 |
| `insertion` | OCR에만 있음 (참조에 없음) | 회색 ➕ | OCR: 甲, 참조: — |
| `deletion` | 참조에만 있음 (OCR 누락) | 회색 ➖ | OCR: —, 참조: 清 |

---

## 작업 순서

아래 작업을 번호 순서대로 구현하라. 각 작업이 끝나면 테스트를 실행하고 통과 확인 후 다음으로 넘어가라.

---

### 작업 1: AlignedPair 데이터 모델

`src/core/alignment.py` 작성:

```python
"""정렬 엔진 — OCR 결과(L2)와 참조 텍스트(L4) 글자 단위 대조.

두 텍스트를 정렬하여 일치/이체자/불일치/삽입/삭제를 구분한다.
교정 GUI에서 불일치를 하이라이팅하는 데 사용.

사용법:
    from src.core.alignment import align_texts, AlignedPair

    pairs = align_texts("王戎簡要裵楷通", "王戎簡要裴楷清通")
    for pair in pairs:
        print(f"{pair.ocr_char} / {pair.ref_char} → {pair.match_type}")
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MatchType(str, Enum):
    """대조 결과 유형."""
    EXACT = "exact"          # 완전 일치
    VARIANT = "variant"      # 이체자 (同字異形)
    MISMATCH = "mismatch"    # 불일치 (다른 글자)
    INSERTION = "insertion"   # OCR에만 있음 (참조에 없는 글자)
    DELETION = "deletion"    # 참조에만 있음 (OCR이 놓친 글자)


@dataclass
class AlignedPair:
    """글자 하나의 대조 결과.

    ocr_char와 ref_char 중 하나가 None이면 insertion 또는 deletion.
    둘 다 있으면 exact, variant, 또는 mismatch.
    """

    ocr_char: Optional[str]     # OCR이 인식한 글자 (없으면 None)
    ref_char: Optional[str]     # 참조 텍스트의 글자 (없으면 None)
    match_type: MatchType       # 대조 결과 유형
    ocr_index: Optional[int] = None   # ocr_text에서의 위치 (0-indexed)
    ref_index: Optional[int] = None   # ref_text에서의 위치 (0-indexed)

    def to_dict(self) -> dict:
        """API 응답용 딕셔너리."""
        return {
            "ocr_char": self.ocr_char,
            "ref_char": self.ref_char,
            "match_type": self.match_type.value,
            "ocr_index": self.ocr_index,
            "ref_index": self.ref_index,
        }


@dataclass
class AlignmentStats:
    """대조 통계.

    전체 글자 수와 유형별 개수.
    GUI 통계 바에 표시.
    """

    total_chars: int = 0
    exact: int = 0
    variant: int = 0
    mismatch: int = 0
    insertion: int = 0
    deletion: int = 0

    @property
    def accuracy(self) -> float:
        """일치율 (exact + variant) / total. 0.0~1.0."""
        if self.total_chars == 0:
            return 0.0
        return (self.exact + self.variant) / self.total_chars

    def to_dict(self) -> dict:
        return {
            "total_chars": self.total_chars,
            "exact": self.exact,
            "variant": self.variant,
            "mismatch": self.mismatch,
            "insertion": self.insertion,
            "deletion": self.deletion,
            "accuracy": round(self.accuracy, 4),
        }

    @classmethod
    def from_pairs(cls, pairs: list[AlignedPair]) -> AlignmentStats:
        """AlignedPair 리스트에서 통계를 계산한다."""
        stats = cls(total_chars=len(pairs))
        for p in pairs:
            if p.match_type == MatchType.EXACT:
                stats.exact += 1
            elif p.match_type == MatchType.VARIANT:
                stats.variant += 1
            elif p.match_type == MatchType.MISMATCH:
                stats.mismatch += 1
            elif p.match_type == MatchType.INSERTION:
                stats.insertion += 1
            elif p.match_type == MatchType.DELETION:
                stats.deletion += 1
        return stats


@dataclass
class BlockAlignment:
    """블록 하나의 대조 결과.

    페이지 단위 대조 시 블록별 결과를 담는다.
    """

    layout_block_id: str
    pairs: list[AlignedPair] = field(default_factory=list)
    stats: Optional[AlignmentStats] = None
    ocr_text: str = ""
    ref_text: str = ""
    error: Optional[str] = None  # 대조 실패 시 에러 메시지

    def to_dict(self) -> dict:
        result = {
            "layout_block_id": self.layout_block_id,
            "ocr_text": self.ocr_text,
            "ref_text": self.ref_text,
            "pairs": [p.to_dict() for p in self.pairs],
        }
        if self.stats:
            result["stats"] = self.stats.to_dict()
        if self.error:
            result["error"] = self.error
        return result
```

테스트 `tests/test_alignment_models.py`:

```python
"""정렬 데이터 모델 테스트."""

from src.core.alignment import (
    AlignedPair, MatchType, AlignmentStats, BlockAlignment,
)


class TestAlignedPair:
    def test_exact_pair(self):
        p = AlignedPair(ocr_char="王", ref_char="王", match_type=MatchType.EXACT,
                        ocr_index=0, ref_index=0)
        d = p.to_dict()
        assert d["match_type"] == "exact"
        assert d["ocr_char"] == "王"

    def test_deletion_pair(self):
        p = AlignedPair(ocr_char=None, ref_char="清", match_type=MatchType.DELETION,
                        ref_index=6)
        assert p.ocr_char is None
        assert p.to_dict()["match_type"] == "deletion"


class TestAlignmentStats:
    def test_from_pairs(self):
        pairs = [
            AlignedPair("王", "王", MatchType.EXACT),
            AlignedPair("裵", "裴", MatchType.VARIANT),
            AlignedPair(None, "清", MatchType.DELETION),
        ]
        stats = AlignmentStats.from_pairs(pairs)
        assert stats.total_chars == 3
        assert stats.exact == 1
        assert stats.variant == 1
        assert stats.deletion == 1
        assert abs(stats.accuracy - 2/3) < 0.001

    def test_empty(self):
        stats = AlignmentStats.from_pairs([])
        assert stats.accuracy == 0.0


class TestBlockAlignment:
    def test_to_dict(self):
        ba = BlockAlignment(
            layout_block_id="p01_b01",
            ocr_text="王戎",
            ref_text="王戎",
            pairs=[AlignedPair("王", "王", MatchType.EXACT)],
            stats=AlignmentStats(total_chars=1, exact=1),
        )
        d = ba.to_dict()
        assert d["layout_block_id"] == "p01_b01"
        assert len(d["pairs"]) == 1
```

커밋: `feat(alignment): AlignedPair + AlignmentStats + BlockAlignment 데이터 모델`

---

### 작업 2: 이체자 사전

`resources/variant_chars.json` — **사용자가 직접 작성**하는 이체자 사전.

앱은 빈 템플릿만 제공하고, 사용자가 자신의 텍스트 작업에 맞춰 이체자 쌍을 추가한다.

#### 2-A: 템플릿 파일

```json
{
  "_format_guide": {
    "설명": "이체자(異體字) 사전. 같은 글자의 다른 형태를 등록한다.",
    "형식": "variants 객체에 글자(키) → 이체자 배열(값)을 양방향으로 등록한다.",
    "양방향 규칙": "A→B를 등록하면 B→A도 반드시 등록해야 한다.",
    "예시": "說과 説이 이체자이면: \"說\": [\"説\"], \"説\": [\"說\"] 두 항목 모두 필요.",
    "다대일": "齒의 이체자가 歯, 齿 둘 다이면: \"齒\": [\"歯\", \"齿\"]",
    "용도": "정렬 엔진(Phase 10-3)이 OCR↔참조 텍스트 대조 시 이체자를 별도 분류한다.",
    "확장": "작업하면서 새 이체자 쌍을 발견할 때마다 추가한다."
  },
  "_version": "0.1.0",
  "variants": {
    "裴": ["裵"],
    "裵": ["裴"]
  }
}
```

⚠️ 주의: 위 템플릿에는 예시로 裴/裵 한 쌍만 넣어둔다. 나머지는 사용자가 추가.

#### 2-B: GUI에서 이체자 관리 기능

정렬 대조 뷰에 이체자 사전 관리 UI를 추가한다:

```
[이체자 사전 관리]
  - 현재 등록: 1쌍
  - [+ 쌍 추가] 버튼 → 다이얼로그: 글자A [  ] ↔ 글자B [  ] [등록]
  - 대조 결과에서 mismatch 글자를 우클릭 → "이체자로 등록" 메뉴
  - 등록 시 양방향 자동 추가 (A→B, B→A 모두)
  - [내보내기] [가져오기] 버튼 — JSON 파일로 공유 가능
```

사용자가 대조 작업 중 발견한 이체자를 바로 등록할 수 있게 한다.
이렇게 하면 사전이 사용자의 실제 텍스트에 맞게 점진적으로 성장한다.

이체자 사전을 로드하고 검색하는 유틸리티를 `src/core/alignment.py`에 추가:

```python
# --- 작업 1에서 만든 파일에 이어서 추가 ---

import json
import os
import logging

logger = logging.getLogger(__name__)


class VariantCharDict:
    """이체자 사전.

    양방향 검색을 지원한다.
    is_variant("裵", "裴") → True
    is_variant("王", "裴") → False

    사전 파일: resources/variant_chars.json
    """

    def __init__(self, dict_path: Optional[str] = None):
        """사전을 로드한다.

        입력: dict_path (None이면 기본 경로 resources/variant_chars.json)
        """
        self._variants: dict[str, set[str]] = {}

        if dict_path is None:
            # 프로젝트 루트에서 resources/variant_chars.json 탐색
            # 실제 경로는 앱 설정에 따라 달라질 수 있음
            dict_path = self._find_default_path()

        if dict_path and os.path.exists(dict_path):
            self._load(dict_path)
        else:
            logger.warning(f"이체자 사전을 찾을 수 없습니다: {dict_path}")

    def _find_default_path(self) -> Optional[str]:
        """기본 사전 경로를 찾는다."""
        # 여러 후보 경로 시도
        candidates = [
            "resources/variant_chars.json",
            os.path.join(os.path.dirname(__file__), "..", "..", "resources", "variant_chars.json"),
        ]
        for path in candidates:
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path):
                return abs_path
        return None

    def _load(self, path: str) -> None:
        """JSON 파일에서 이체자 사전을 로드한다."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        variants_raw = data.get("variants", {})
        for char, alts in variants_raw.items():
            if char not in self._variants:
                self._variants[char] = set()
            for alt in alts:
                self._variants[char].add(alt)

        logger.info(f"이체자 사전 로드: {len(self._variants)}개 항목 ({path})")

    def is_variant(self, char_a: str, char_b: str) -> bool:
        """두 글자가 이체자 관계인지 확인한다.

        양방향: is_variant("説", "說") == is_variant("說", "説") == True
        같은 글자: is_variant("王", "王") → False (이체자가 아니라 동일 글자)
        """
        if char_a == char_b:
            return False

        # A→B 방향
        if char_a in self._variants and char_b in self._variants[char_a]:
            return True

        # B→A 방향 (양방향 보장)
        if char_b in self._variants and char_a in self._variants[char_b]:
            return True

        return False

    @property
    def size(self) -> int:
        """사전에 등록된 글자 수."""
        return len(self._variants)
```

테스트 `tests/test_alignment_variant.py`:

```python
"""이체자 사전 테스트."""

import json
import os
import pytest
from src.core.alignment import VariantCharDict


@pytest.fixture
def variant_dict(tmp_path):
    """테스트용 이체자 사전 (사용자가 직접 만드는 형식)."""
    data = {
        "_format_guide": {
            "설명": "이체자 사전 — 양방향 등록 필수"
        },
        "variants": {
            "說": ["説"],
            "説": ["說"],
            "裴": ["裵"],
            "裵": ["裴"],
            "經": ["経"],
            "経": ["經"],
        }
    }
    path = tmp_path / "variant_chars.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return VariantCharDict(str(path))


class TestVariantCharDict:
    def test_is_variant_true(self, variant_dict):
        assert variant_dict.is_variant("說", "説") is True
        assert variant_dict.is_variant("裴", "裵") is True

    def test_is_variant_bidirectional(self, variant_dict):
        assert variant_dict.is_variant("説", "說") is True
        assert variant_dict.is_variant("裵", "裴") is True

    def test_is_variant_false(self, variant_dict):
        assert variant_dict.is_variant("王", "裴") is False

    def test_same_char_not_variant(self, variant_dict):
        assert variant_dict.is_variant("王", "王") is False

    def test_unknown_char(self, variant_dict):
        assert variant_dict.is_variant("가", "나") is False

    def test_size(self, variant_dict):
        assert variant_dict.size == 6

    def test_missing_file(self):
        d = VariantCharDict("/nonexistent/path.json")
        assert d.size == 0
        assert d.is_variant("說", "説") is False
```

커밋: `feat(alignment): 이체자 사전 (variant_chars.json) + VariantCharDict`

---

### 작업 3: 핵심 정렬 알고리즘

`src/core/alignment.py`에 `align_texts()` 함수 추가:

```python
# --- 기존 코드에 이어서 추가 ---

import difflib


def align_texts(
    ocr_text: str,
    ref_text: str,
    variant_dict: Optional[VariantCharDict] = None,
) -> list[AlignedPair]:
    """OCR 텍스트와 참조 텍스트를 글자 단위로 정렬한다.

    입력:
      ocr_text: L2 OCR 인식 텍스트 (줄바꿈 제거된 상태)
      ref_text: L4 확정 텍스트 (줄바꿈 제거된 상태)
      variant_dict: 이체자 사전 (None이면 이체자 보정 안 함)

    출력: AlignedPair 리스트

    알고리즘:
      1단계: difflib.SequenceMatcher로 opcodes 추출
      2단계: opcodes를 AlignedPair로 변환
      3단계: mismatch 중 이체자 사전에 있는 쌍을 variant로 재분류
    """
    pairs: list[AlignedPair] = []

    # 1단계: difflib로 정렬
    matcher = difflib.SequenceMatcher(None, ocr_text, ref_text)
    opcodes = matcher.get_opcodes()

    # 2단계: opcodes → AlignedPair 변환
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            # 완전 일치
            for k in range(i2 - i1):
                pairs.append(AlignedPair(
                    ocr_char=ocr_text[i1 + k],
                    ref_char=ref_text[j1 + k],
                    match_type=MatchType.EXACT,
                    ocr_index=i1 + k,
                    ref_index=j1 + k,
                ))

        elif tag == "replace":
            # 1:1 대응이 가능한 부분은 mismatch
            # 길이가 다르면 짧은 쪽은 mismatch, 남는 쪽은 insertion/deletion
            ocr_len = i2 - i1
            ref_len = j2 - j1
            common_len = min(ocr_len, ref_len)

            for k in range(common_len):
                pairs.append(AlignedPair(
                    ocr_char=ocr_text[i1 + k],
                    ref_char=ref_text[j1 + k],
                    match_type=MatchType.MISMATCH,
                    ocr_index=i1 + k,
                    ref_index=j1 + k,
                ))

            # OCR이 더 길면 → 나머지는 insertion
            for k in range(common_len, ocr_len):
                pairs.append(AlignedPair(
                    ocr_char=ocr_text[i1 + k],
                    ref_char=None,
                    match_type=MatchType.INSERTION,
                    ocr_index=i1 + k,
                ))

            # 참조가 더 길면 → 나머지는 deletion
            for k in range(common_len, ref_len):
                pairs.append(AlignedPair(
                    ocr_char=None,
                    ref_char=ref_text[j1 + k],
                    match_type=MatchType.DELETION,
                    ref_index=j1 + k,
                ))

        elif tag == "insert":
            # 참조에만 있음 → OCR이 놓침
            for k in range(j2 - j1):
                pairs.append(AlignedPair(
                    ocr_char=None,
                    ref_char=ref_text[j1 + k],
                    match_type=MatchType.DELETION,
                    ref_index=j1 + k,
                ))

        elif tag == "delete":
            # OCR에만 있음 → 참조에 없음
            for k in range(i2 - i1):
                pairs.append(AlignedPair(
                    ocr_char=ocr_text[i1 + k],
                    ref_char=None,
                    match_type=MatchType.INSERTION,
                    ocr_index=i1 + k,
                ))

    # 3단계: 이체자 보정
    if variant_dict:
        for pair in pairs:
            if (pair.match_type == MatchType.MISMATCH
                    and pair.ocr_char and pair.ref_char
                    and variant_dict.is_variant(pair.ocr_char, pair.ref_char)):
                pair.match_type = MatchType.VARIANT

    return pairs


def compute_stats(pairs: list[AlignedPair]) -> AlignmentStats:
    """AlignedPair 리스트에서 통계를 계산한다. (편의 함수)"""
    return AlignmentStats.from_pairs(pairs)
```

테스트 `tests/test_alignment_core.py`:

```python
"""핵심 정렬 알고리즘 테스트."""

import json
import pytest
from src.core.alignment import (
    align_texts, compute_stats,
    AlignedPair, MatchType, VariantCharDict,
)


@pytest.fixture
def variant_dict(tmp_path):
    data = {
        "variants": {
            "裴": ["裵"], "裵": ["裴"],
            "說": ["説"], "説": ["說"],
        }
    }
    path = tmp_path / "variants.json"
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    return VariantCharDict(str(path))


class TestAlignTexts:
    def test_identical(self):
        pairs = align_texts("王戎簡要", "王戎簡要")
        assert len(pairs) == 4
        assert all(p.match_type == MatchType.EXACT for p in pairs)

    def test_mismatch(self):
        pairs = align_texts("甲乙", "甲丙")
        assert pairs[0].match_type == MatchType.EXACT
        assert pairs[1].match_type == MatchType.MISMATCH
        assert pairs[1].ocr_char == "乙"
        assert pairs[1].ref_char == "丙"

    def test_ocr_missing_char(self):
        """OCR이 글자를 놓친 경우 (deletion)."""
        pairs = align_texts("王戎簡要楷通", "王戎簡要裴楷清通")
        # "裴"와 "清"이 OCR에 없음
        deletions = [p for p in pairs if p.match_type == MatchType.DELETION]
        assert len(deletions) >= 1  # 최소 1개 deletion

    def test_ocr_extra_char(self):
        """OCR이 글자를 잘못 추가한 경우 (insertion)."""
        pairs = align_texts("王甲戎", "王戎")
        insertions = [p for p in pairs if p.match_type == MatchType.INSERTION]
        assert len(insertions) >= 1

    def test_empty_ocr(self):
        pairs = align_texts("", "王戎")
        assert len(pairs) == 2
        assert all(p.match_type == MatchType.DELETION for p in pairs)

    def test_empty_ref(self):
        pairs = align_texts("王戎", "")
        assert len(pairs) == 2
        assert all(p.match_type == MatchType.INSERTION for p in pairs)

    def test_both_empty(self):
        pairs = align_texts("", "")
        assert len(pairs) == 0

    def test_variant_correction(self, variant_dict):
        """이체자 보정: mismatch → variant."""
        pairs = align_texts("裵", "裴", variant_dict=variant_dict)
        assert len(pairs) == 1
        assert pairs[0].match_type == MatchType.VARIANT

    def test_variant_not_applied_without_dict(self):
        """이체자 사전 없으면 variant로 분류하지 않음."""
        pairs = align_texts("裵", "裴", variant_dict=None)
        assert pairs[0].match_type == MatchType.MISMATCH

    def test_full_example(self, variant_dict):
        """설계 문서의 예제: 王戎簡要裵楷通 vs 王戎簡要裴楷清通."""
        pairs = align_texts("王戎簡要裵楷通", "王戎簡要裴楷清通", variant_dict=variant_dict)

        # 유형별 분류
        types = {p.match_type for p in pairs}
        assert MatchType.EXACT in types
        assert MatchType.VARIANT in types  # 裵/裴

        # 통계
        stats = compute_stats(pairs)
        assert stats.exact >= 5   # 王戎簡要楷通 (최소)
        assert stats.variant >= 1  # 裵/裴

    def test_index_tracking(self):
        """ocr_index와 ref_index가 올바르게 추적되는지."""
        pairs = align_texts("AB", "AB")
        assert pairs[0].ocr_index == 0
        assert pairs[0].ref_index == 0
        assert pairs[1].ocr_index == 1
        assert pairs[1].ref_index == 1


class TestComputeStats:
    def test_basic(self, variant_dict):
        pairs = align_texts("王裵", "王裴", variant_dict=variant_dict)
        stats = compute_stats(pairs)
        assert stats.total_chars == 2
        assert stats.exact == 1
        assert stats.variant == 1
        assert stats.accuracy == 1.0  # exact + variant = total
```

커밋: `feat(alignment): 핵심 정렬 알고리즘 — difflib + 이체자 보정`

---

### 작업 4: 페이지 단위 대조

`src/core/alignment.py`에 `align_page()` 함수 추가:

```python
# --- 기존 코드에 이어서 추가 ---

def align_page(
    library_root: str,
    doc_id: str,
    part_id: str,
    page_number: int,
    variant_dict: Optional[VariantCharDict] = None,
) -> list[BlockAlignment]:
    """페이지의 모든 블록을 대조한다.

    입력:
      library_root: 서고 루트 경로
      doc_id, part_id, page_number: 페이지 식별
      variant_dict: 이체자 사전

    출력: BlockAlignment 리스트 (블록별 대조 결과)

    처리:
      1. L2 OCR 결과 로드 (L2_ocr/page_NNN.json)
      2. L4 확정 텍스트 로드 (L4_text/page_NNN.json)
      3. layout_block_id로 매칭
      4. 블록별 align_texts() 실행
    """
    results: list[BlockAlignment] = []

    # L2 OCR 결과 로드
    l2_path = os.path.join(
        library_root, "sources", doc_id, part_id,
        "L2_ocr", f"page_{page_number:03d}.json"
    )
    l2_data = _load_json(l2_path)
    if l2_data is None:
        return [BlockAlignment(
            layout_block_id="*",
            error=f"L2 OCR 결과를 찾을 수 없습니다: {l2_path}"
        )]

    # L4 확정 텍스트 로드
    l4_path = os.path.join(
        library_root, "sources", doc_id, part_id,
        "L4_text", f"page_{page_number:03d}.json"
    )
    l4_data = _load_json(l4_path)
    if l4_data is None:
        return [BlockAlignment(
            layout_block_id="*",
            error=f"L4 확정 텍스트를 찾을 수 없습니다: {l4_path}"
        )]

    # L2 블록 → dict (block_id → text)
    l2_blocks: dict[str, str] = {}
    for ocr_result in l2_data.get("ocr_results", []):
        block_id = ocr_result.get("layout_block_id", "")
        text = ocr_result.get("text", "")
        l2_blocks[block_id] = text

    # L4 블록 → dict (block_id → text)
    # L4의 정확한 형식은 기존 코드를 확인하라.
    # 여기서는 블록별 텍스트가 있다고 가정.
    l4_blocks: dict[str, str] = {}
    for text_block in l4_data.get("text_blocks", []):
        block_id = text_block.get("layout_block_id", "")
        text = text_block.get("text", "")
        l4_blocks[block_id] = text

    # 블록별 대조
    all_block_ids = set(l2_blocks.keys()) | set(l4_blocks.keys())
    for block_id in sorted(all_block_ids):
        ocr_text = l2_blocks.get(block_id, "")
        ref_text = l4_blocks.get(block_id, "")

        # 줄바꿈 제거 (글자 단위 비교이므로)
        ocr_clean = ocr_text.replace("\n", "")
        ref_clean = ref_text.replace("\n", "")

        if not ocr_clean and not ref_clean:
            continue  # 둘 다 빈 블록은 건너뜀

        pairs = align_texts(ocr_clean, ref_clean, variant_dict=variant_dict)
        stats = AlignmentStats.from_pairs(pairs)

        results.append(BlockAlignment(
            layout_block_id=block_id,
            pairs=pairs,
            stats=stats,
            ocr_text=ocr_clean,
            ref_text=ref_clean,
        ))

    return results


def _load_json(path: str) -> Optional[dict]:
    """JSON 파일을 로드한다. 없으면 None."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
```

테스트 `tests/test_alignment_page.py`:

```python
"""페이지 단위 대조 테스트."""

import json
import os
import pytest

from src.core.alignment import align_page, VariantCharDict, MatchType


@pytest.fixture
def test_library(tmp_path):
    """L2 + L4 데이터가 있는 테스트 서고."""
    doc_dir = tmp_path / "sources" / "doc001" / "vol1"

    # L2 OCR 결과
    l2_dir = doc_dir / "L2_ocr"
    l2_dir.mkdir(parents=True)
    l2_data = {
        "page_number": 1,
        "ocr_results": [
            {"layout_block_id": "p01_b01", "text": "王戎簡要裵楷通"},
            {"layout_block_id": "p01_b02", "text": "孔明臥龍呂望非熊"},
        ],
    }
    with open(l2_dir / "page_001.json", "w") as f:
        json.dump(l2_data, f, ensure_ascii=False)

    # L4 확정 텍스트
    l4_dir = doc_dir / "L4_text"
    l4_dir.mkdir(parents=True)
    l4_data = {
        "page_number": 1,
        "text_blocks": [
            {"layout_block_id": "p01_b01", "text": "王戎簡要裴楷清通"},
            {"layout_block_id": "p01_b02", "text": "孔明臥龍呂望非熊"},
        ],
    }
    with open(l4_dir / "page_001.json", "w") as f:
        json.dump(l4_data, f, ensure_ascii=False)

    return tmp_path


@pytest.fixture
def variant_dict(tmp_path):
    data = {"variants": {"裴": ["裵"], "裵": ["裴"]}}
    path = tmp_path / "variants.json"
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    return VariantCharDict(str(path))


class TestAlignPage:
    def test_basic(self, test_library, variant_dict):
        results = align_page(
            str(test_library), "doc001", "vol1", 1,
            variant_dict=variant_dict,
        )
        assert len(results) == 2

        # 블록 1: 裵/裴 이체자 + 清 누락
        b1 = results[0]
        assert b1.layout_block_id == "p01_b01"
        assert b1.stats.variant >= 1

        # 블록 2: 완전 일치
        b2 = results[1]
        assert b2.layout_block_id == "p01_b02"
        assert b2.stats.exact == 8
        assert b2.stats.accuracy == 1.0

    def test_missing_l2(self, test_library):
        results = align_page(str(test_library), "doc001", "vol1", 999)
        assert len(results) == 1
        assert results[0].error is not None
        assert "L2" in results[0].error

    def test_missing_l4(self, test_library):
        # L4 삭제
        l4_path = os.path.join(
            str(test_library), "sources", "doc001", "vol1", "L4_text", "page_001.json"
        )
        os.remove(l4_path)

        results = align_page(str(test_library), "doc001", "vol1", 1)
        assert results[0].error is not None
        assert "L4" in results[0].error
```

커밋: `feat(alignment): 페이지 단위 대조 — L2 ↔ L4 블록 매칭`

---

### 작업 5: API 엔드포인트

기존 API 라우터에 정렬 엔드포인트를 추가한다.

```python
# src/api/ 에 alignment_routes.py 추가 (또는 기존 라우터에 병합)

# ── 대조 실행 ──

# POST /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/alignment
# 입력: (없음 또는 옵션 지정)
# 전제 조건: L2(OCR 결과)와 L4(확정 텍스트)가 모두 있어야 함
# 응답: {
#   "blocks": [
#     {
#       "layout_block_id": "p01_b01",
#       "ocr_text": "王戎簡要裵楷通",
#       "ref_text": "王戎簡要裴楷清通",
#       "pairs": [...],
#       "stats": { "total_chars": 8, "exact": 5, "variant": 1, ... }
#     },
#     ...
#   ],
#   "page_stats": { "total_chars": 16, ... }
# }

# ── 대조 결과 조회 ──

# GET /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/alignment
# 마지막 대조 결과를 반환 (캐시 또는 재계산)
# 없으면 404
```

구현 시 주의:
1. align_page() 호출 시 VariantCharDict를 앱 레벨에서 한 번만 로드한다.
2. 대조 결과를 캐시할지 매번 재계산할지는 기존 패턴을 따른다.
3. L2 또는 L4가 없으면 명확한 에러 메시지 반환.

커밋: `feat(api): 정렬 엔드포인트 — 대조 실행 + 결과 조회`

---

### 작업 6: GUI — 대조 뷰

교정 모드(correction-editor.js)에 "대조" 서브탭을 추가한다.

#### 6-A: 대조 결과 테이블

```
┌──────────────────────────────────────────┐
│ 대조 결과 — page 1, 블록 p01_b01         │
│                                          │
│  ── 통계 바 ──                            │
│  전체 8자 — 일치 5 · 이체자 1 · 누락 1 · 불일치 0  │
│  정확도: 87.5%                            │
│  [████████████░░] 87.5%                  │
│                                          │
│  ── 글자별 대조 ──                         │
│  ┌─────┬─────┬──────────┐               │
│  │ OCR │ 참조 │   상태   │               │
│  ├─────┼─────┼──────────┤               │
│  │  王 │  王 │ ✅ 일치  │               │
│  │  戎 │  戎 │ ✅ 일치  │               │
│  │  簡 │  簡 │ ✅ 일치  │               │
│  │  要 │  要 │ ✅ 일치  │               │
│  │  裵 │  裴 │ 🟡 이체자│               │
│  │  楷 │  楷 │ ✅ 일치  │               │
│  │  ×  │  清 │ 🔴 누락  │  ← 클릭 → 교정│
│  │  通 │  通 │ ✅ 일치  │               │
│  └─────┴─────┴──────────┘               │
└──────────────────────────────────────────┘
```

#### 6-B: 색상 규칙

| match_type | 배경색 | 글자색 | 아이콘 |
|-----------|--------|--------|--------|
| exact | 없음 (기본) | 기본 | ✅ |
| variant | 연노랑 `#FFF9C4` | 기본 | 🟡 |
| mismatch | 연빨강 `#FFCDD2` | 기본 | 🔴 |
| insertion | 연회색 `#E0E0E0` | 회색 | ➕ |
| deletion | 연회색 `#E0E0E0` | 회색 | ➖ |

#### 6-C: 이미지 위 하이라이팅

- OCR 결과의 글자별 bbox를 이용해 이미지 위에 불일치 위치를 표시.
- variant: 노란 테두리
- mismatch: 빨간 테두리
- deletion: 빨간 점선 테두리 (해당 위치 추정)
- 토글: `[대조 오버레이 표시/숨기기]`

#### 6-D: 상호작용

- 불일치 글자(mismatch/deletion) 클릭 → 교정 다이얼로그 열림.
- 이체자(variant) 클릭 → 팝업: "裵 → 裴 (이체자)" + [참조로 교정] 버튼.
- 블록 탭: 여러 블록이 있으면 탭으로 전환.

커밋: `feat(gui): 대조 뷰 — 글자별 비교 테이블 + 통계 바 + 오버레이`

---

### 작업 7: 통합 테스트 + 최종 정리

```python
# tests/test_alignment_integration.py

class TestAlignmentIntegration:
    def test_full_flow(self, test_library, variant_dict):
        """전체 흐름: align_page → 결과 검증 → 통계."""
        pass

    def test_api_flow(self, test_client, test_library):
        """API: POST /alignment → GET /alignment."""
        pass

    def test_empty_l2_text(self, test_library):
        """OCR 결과가 빈 블록일 때."""
        pass
```

최종 정리:

1. `docs/DECISIONS.md`에 추가할 내용 확인 (정렬 알고리즘은 별도 Decision ID 불필요할 수 있음).
2. `docs/phase10_12_design.md`의 Phase 10-3 섹션에 "✅ 완료" 표시.
3. 이체자 사전 파일이 정상적으로 배포되는지 확인.

최종 커밋: `feat: Phase 10-3 완료 — 정렬 엔진 (OCR ↔ 텍스트 대조)`

---

## 체크리스트

작업 완료 후 아래를 모두 확인하라:

- [ ] `src/core/alignment.py` — AlignedPair, VariantCharDict, align_texts, align_page 모두 동작
- [ ] `resources/variant_chars.json` — 이체자 사전 파일 존재 + 로드 정상
- [ ] 모든 테스트 통과 (`uv run pytest tests/test_alignment_*.py -v`)
- [ ] 이체자 사전 없이도 기본 정렬 동작 (variant 분류만 안 됨)
- [ ] API 엔드포인트가 기존 앱에 등록됨
- [ ] GUI 교정 모드에 "대조" 서브탭 동작
- [ ] 불일치 글자 클릭 → 교정 다이얼로그 연결

---

## ⏭️ 다음 세션: Phase 10-4 — KORCIS 파서 고도화 (선택)

```
이 세션(10-3)이 완료되면 다음 작업 여부를 판단한다.

10-3에서 만든 것:
  ✅ 정렬 알고리즘 (difflib + 이체자 보정)
  ✅ 이체자 사전 (resources/variant_chars.json)
  ✅ 페이지 단위 대조 (L2 ↔ L4 블록 매칭)
  ✅ API 엔드포인트
  ✅ GUI — 대조 뷰 + 통계 바 + 이미지 오버레이

10-4 판단 기준:
  - 파서 수선 세션에서 KORCIS 기본 구현이 충분한가?
  - API 키 기반 고급 기능(구조화된 검색, KORMARC 008 해석, 판식정보 추출)이 지금 필요한가?
  - 필요하면 → phase10_4_korcis_session.md
  - 불필요하면 → Phase 11-1 현토 편집기로 건너뜀

⚠️ Phase 11-1은 혜원의 L5 데이터 모델 확인이 필요하다.
   10-4를 건너뛰더라도 11-1 시작 전에 확인 사항을 해결해야 한다.
```
