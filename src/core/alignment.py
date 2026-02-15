"""정렬 엔진 — OCR 결과(L2)와 참조 텍스트(L4) 글자 단위 대조.

두 텍스트를 정렬하여 일치/이체자/불일치/삽입/삭제를 구분한다.
교정 GUI에서 불일치를 하이라이팅하는 데 사용.

핵심 원칙:
  - 비파괴: L2나 L4 데이터를 수정하지 않는다 (읽기 전용 비교)
  - 글자 단위: difflib.SequenceMatcher로 한 글자씩 비교
  - 이체자 보정: 이체자 사전으로 동자이형(同字異形) 분류

사용법:
    from src.core.alignment import align_texts, AlignedPair

    pairs = align_texts("王戎簡要裵楷通", "王戎簡要裴楷清通")
    for pair in pairs:
        print(f"{pair.ocr_char} / {pair.ref_char} → {pair.match_type}")

페이지 단위 대조:
    from src.core.alignment import align_page

    result = align_page(library_root, doc_id, part_id, page_number)
"""

from __future__ import annotations

import difflib
import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────
# 데이터 모델 (작업 1)
# ──────────────────────────────────────


class MatchType(str, Enum):
    """대조 결과 유형.

    | 유형 | 의미 | GUI 색상 |
    |------|------|----------|
    | exact | 완전 일치 | 초록 |
    | variant | 이체자 (同字異形) | 노랑 |
    | mismatch | 불일치 (다른 글자) | 빨강 |
    | insertion | OCR에만 있음 | 회색 |
    | deletion | 참조에만 있음 (OCR 누락) | 회색 |
    """

    EXACT = "exact"
    VARIANT = "variant"
    MISMATCH = "mismatch"
    INSERTION = "insertion"
    DELETION = "deletion"


@dataclass
class AlignedPair:
    """글자 하나의 대조 결과.

    ocr_char와 ref_char 중 하나가 None이면 insertion 또는 deletion.
    둘 다 있으면 exact, variant, 또는 mismatch.
    """

    ocr_char: Optional[str]
    ref_char: Optional[str]
    match_type: MatchType
    ocr_index: Optional[int] = None
    ref_index: Optional[int] = None

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

    전체 글자 수와 유형별 개수. GUI 통계 바에 표시.
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
    layout_block_id가 "*"이면 페이지 전체 대조 결과.
    """

    layout_block_id: str
    pairs: list[AlignedPair] = field(default_factory=list)
    stats: Optional[AlignmentStats] = None
    ocr_text: str = ""
    ref_text: str = ""
    error: Optional[str] = None

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


# ──────────────────────────────────────
# 이체자 사전 (작업 2)
# ──────────────────────────────────────


class VariantCharDict:
    """이체자(異體字) 사전.

    양방향 검색을 지원한다.
    is_variant("裵", "裴") → True
    is_variant("王", "裴") → False

    사전 파일: resources/variant_chars.json
    사용자가 직접 이체자 쌍을 추가하며 사전을 성장시킨다.
    """

    def __init__(self, dict_path: Optional[str] = None):
        """사전을 로드한다.

        입력: dict_path — 사전 파일 경로. None이면 기본 경로를 탐색.
        """
        self._variants: dict[str, set[str]] = {}

        if dict_path is None:
            dict_path = self._find_default_path()

        if dict_path and os.path.exists(dict_path):
            self._load(dict_path)
        else:
            logger.warning("이체자 사전을 찾을 수 없습니다: %s", dict_path)

    def _find_default_path(self) -> Optional[str]:
        """기본 사전 경로를 찾는다.

        여러 후보 경로를 시도:
          1. 현재 작업 디렉토리 기준 resources/variant_chars.json
          2. 이 파일 기준 상대 경로
        """
        candidates = [
            "resources/variant_chars.json",
            os.path.join(
                os.path.dirname(__file__), "..", "..", "resources", "variant_chars.json"
            ),
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

        logger.info("이체자 사전 로드: %d개 항목 (%s)", len(self._variants), path)

    def is_variant(self, char_a: str, char_b: str) -> bool:
        """두 글자가 이체자 관계인지 확인한다.

        양방향: is_variant("説", "說") == is_variant("說", "説") == True
        같은 글자: is_variant("王", "王") → False (이체자가 아니라 동일 글자)
        """
        if char_a == char_b:
            return False

        if char_a in self._variants and char_b in self._variants[char_a]:
            return True

        if char_b in self._variants and char_a in self._variants[char_b]:
            return True

        return False

    def add_pair(self, char_a: str, char_b: str) -> None:
        """이체자 쌍을 양방향으로 추가한다.

        GUI에서 사용자가 새 이체자를 등록할 때 호출.
        """
        if char_a == char_b:
            return
        self._variants.setdefault(char_a, set()).add(char_b)
        self._variants.setdefault(char_b, set()).add(char_a)

    def save(self, path: str) -> None:
        """사전을 JSON 파일로 저장한다."""
        serializable = {
            char: sorted(alts) for char, alts in sorted(self._variants.items())
        }
        data = {
            "_format_guide": {
                "설명": "이체자(異體字) 사전. 같은 글자의 다른 형태를 등록한다.",
                "양방향 규칙": "A→B를 등록하면 B→A도 자동 등록된다.",
                "용도": "정렬 엔진이 OCR↔참조 텍스트 대조 시 이체자를 별도 분류한다.",
            },
            "_version": "0.1.0",
            "variants": serializable,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @property
    def size(self) -> int:
        """사전에 등록된 글자 수."""
        return len(self._variants)

    def to_dict(self) -> dict:
        """API 응답용 딕셔너리."""
        return {
            char: sorted(alts) for char, alts in sorted(self._variants.items())
        }


# ──────────────────────────────────────
# 핵심 정렬 알고리즘 (작업 3)
# ──────────────────────────────────────


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

            # OCR이 더 길면 → 나머지는 insertion (참조에 없는 글자)
            for k in range(common_len, ocr_len):
                pairs.append(AlignedPair(
                    ocr_char=ocr_text[i1 + k],
                    ref_char=None,
                    match_type=MatchType.INSERTION,
                    ocr_index=i1 + k,
                ))

            # 참조가 더 길면 → 나머지는 deletion (OCR이 놓친 글자)
            for k in range(common_len, ref_len):
                pairs.append(AlignedPair(
                    ocr_char=None,
                    ref_char=ref_text[j1 + k],
                    match_type=MatchType.DELETION,
                    ref_index=j1 + k,
                ))

        elif tag == "insert":
            # difflib "insert": ref에만 있음 → OCR이 놓침 → deletion
            for k in range(j2 - j1):
                pairs.append(AlignedPair(
                    ocr_char=None,
                    ref_char=ref_text[j1 + k],
                    match_type=MatchType.DELETION,
                    ref_index=j1 + k,
                ))

        elif tag == "delete":
            # difflib "delete": ocr에만 있음 → 참조에 없음 → insertion
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
            if (
                pair.match_type == MatchType.MISMATCH
                and pair.ocr_char
                and pair.ref_char
                and variant_dict.is_variant(pair.ocr_char, pair.ref_char)
            ):
                pair.match_type = MatchType.VARIANT

    return pairs


def compute_stats(pairs: list[AlignedPair]) -> AlignmentStats:
    """AlignedPair 리스트에서 통계를 계산한다. (편의 함수)"""
    return AlignmentStats.from_pairs(pairs)


# ──────────────────────────────────────
# 페이지 단위 대조 (작업 4)
# ──────────────────────────────────────


def _extract_ocr_text(ocr_result: dict) -> str:
    """L2 OcrResult 하나에서 전체 텍스트를 추출한다.

    L2 형식: { "lines": [ { "text": "王戎簡要", ... }, ... ] }
    lines의 text를 이어붙여 반환한다.
    """
    lines = ocr_result.get("lines", [])
    return "".join(line.get("text", "") for line in lines)


def align_page(
    library_root: str,
    doc_id: str,
    part_id: str,
    page_number: int,
    variant_dict: Optional[VariantCharDict] = None,
) -> list[BlockAlignment]:
    """페이지의 OCR 결과(L2)와 확정 텍스트(L4)를 대조한다.

    입력:
      library_root: 서고 루트 경로
      doc_id, part_id, page_number: 페이지 식별
      variant_dict: 이체자 사전

    출력: BlockAlignment 리스트
      - 블록별 대조 결과 (L2 블록 기준)
      - 마지막에 페이지 전체 대조 결과 (layout_block_id="*")

    처리:
      1. L2 OCR 결과 로드 (JSON)
      2. L4 확정 텍스트 로드 (plain text)
      3. 페이지 전체 텍스트 대조 (L2 concat vs L4)
      4. 블록별 대조 (L2 블록 → L4에서 해당 부분 매칭)

    왜 이렇게 하는가:
      L4는 plain text (.txt) 파일이고, L2는 블록별 JSON이다.
      블록↔L4 직접 매핑이 불가능하므로, 페이지 전체를 먼저 대조한 뒤
      L2 블록 텍스트를 개별적으로도 검색하여 위치를 추정한다.
    """
    results: list[BlockAlignment] = []
    doc_path = Path(library_root) / "documents" / doc_id

    # ── L2 OCR 결과 로드 ──
    l2_filename = f"{part_id}_page_{page_number:03d}.json"
    l2_path = doc_path / "L2_ocr" / l2_filename
    l2_data = _load_json(str(l2_path))

    if l2_data is None:
        return [BlockAlignment(
            layout_block_id="*",
            error=f"L2 OCR 결과를 찾을 수 없습니다: {l2_path}",
        )]

    # ── L4 확정 텍스트 로드 ──
    l4_filename = f"{part_id}_page_{page_number:03d}.txt"
    l4_path = doc_path / "L4_text" / "pages" / l4_filename
    ref_text = _load_text(str(l4_path))

    if ref_text is None:
        return [BlockAlignment(
            layout_block_id="*",
            error=f"L4 확정 텍스트를 찾을 수 없습니다: {l4_path}",
        )]

    # 참조 텍스트에서 줄바꿈 제거 (글자 단위 비교)
    ref_clean = ref_text.replace("\n", "").replace("\r", "")

    # ── L2 블록별 텍스트 추출 ──
    ocr_results = l2_data.get("ocr_results", [])
    block_texts: list[tuple[str, str]] = []  # (block_id, text)

    for ocr_result in ocr_results:
        block_id = ocr_result.get("layout_block_id", "")
        block_text = _extract_ocr_text(ocr_result)
        if block_text:
            block_texts.append((block_id, block_text))

    # ── 블록별 대조 ──
    # 각 블록의 OCR 텍스트를 L4 전체에서 찾아서 대조한다.
    # L4에서의 위치를 추정하기 위해 부분 문자열 검색 + difflib 사용.
    for block_id, ocr_text in block_texts:
        # L4 텍스트에서 이 블록에 해당하는 부분을 찾는다.
        # 완벽한 매칭은 불가능하므로, 블록 텍스트 자체를 ref로도 사용.
        # 가장 실용적: OCR 블록 텍스트 vs L4 전체에서 가장 유사한 부분.
        block_ref = _find_best_match_in_ref(ocr_text, ref_clean)

        pairs = align_texts(ocr_text, block_ref, variant_dict=variant_dict)
        stats = AlignmentStats.from_pairs(pairs)

        results.append(BlockAlignment(
            layout_block_id=block_id,
            pairs=pairs,
            stats=stats,
            ocr_text=ocr_text,
            ref_text=block_ref,
        ))

    # ── 페이지 전체 대조 ──
    full_ocr = "".join(text for _, text in block_texts)
    if full_ocr or ref_clean:
        full_pairs = align_texts(full_ocr, ref_clean, variant_dict=variant_dict)
        full_stats = AlignmentStats.from_pairs(full_pairs)
        results.append(BlockAlignment(
            layout_block_id="*",
            pairs=full_pairs,
            stats=full_stats,
            ocr_text=full_ocr,
            ref_text=ref_clean,
        ))

    return results


def _find_best_match_in_ref(ocr_text: str, ref_text: str) -> str:
    """L4 참조 텍스트에서 OCR 블록 텍스트에 가장 유사한 부분을 찾는다.

    왜 이렇게 하는가:
      L4는 페이지 전체 plain text이고, L2는 블록별로 나뉘어 있다.
      블록의 OCR 텍스트가 L4 어디에 해당하는지 찾아야 블록 단위 대조가 가능하다.

    알고리즘:
      1. OCR 텍스트 길이와 같은 윈도우를 L4 위에서 슬라이딩
      2. SequenceMatcher.ratio()가 가장 높은 위치를 선택
      3. 선택된 위치에서 앞뒤로 약간 확장하여 OCR 누락 글자를 포함
      4. 유사도가 너무 낮으면 (< 0.3) 전체 참조 텍스트를 반환 (매칭 실패)
    """
    if not ocr_text or not ref_text:
        return ref_text

    ocr_len = len(ocr_text)
    ref_len = len(ref_text)

    # 참조가 OCR보다 짧으면 그냥 전체 비교
    if ref_len <= ocr_len:
        return ref_text

    # 1단계: 정확한 길이 윈도우로 최적 위치 찾기
    best_ratio = 0.0
    best_start = 0

    for start in range(ref_len - ocr_len + 1):
        candidate = ref_text[start:start + ocr_len]
        ratio = difflib.SequenceMatcher(None, ocr_text, candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = start

    if best_ratio < 0.3:
        return ref_text

    # 2단계: 최적 위치에서 약간 확장하여 누락 글자 포함
    # OCR이 놓친 글자가 있을 수 있으므로 앞뒤 2글자 여유
    margin = 2
    expand_start = max(0, best_start - margin)
    expand_end = min(ref_len, best_start + ocr_len + margin)

    # 확장된 범위와 정확한 범위 중 더 좋은 ratio를 선택
    exact_text = ref_text[best_start:best_start + ocr_len]
    expanded_text = ref_text[expand_start:expand_end]

    exact_ratio = difflib.SequenceMatcher(None, ocr_text, exact_text).ratio()
    expanded_ratio = difflib.SequenceMatcher(None, ocr_text, expanded_text).ratio()

    if expanded_ratio > exact_ratio:
        return expanded_text
    return exact_text


def _load_json(path: str) -> Optional[dict]:
    """JSON 파일을 로드한다. 없으면 None."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_text(path: str) -> Optional[str]:
    """텍스트 파일을 로드한다. 없으면 None."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
