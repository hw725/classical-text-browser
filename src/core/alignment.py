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
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from core.document import get_corrected_text

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

    def remove_pair(self, char_a: str, char_b: str) -> bool:
        """이체자 쌍을 양방향으로 삭제한다.

        입력: char_a, char_b — 삭제할 이체자 쌍.
        출력: 실제로 삭제되었으면 True, 존재하지 않았으면 False.

        왜 이렇게 하는가:
            이체자는 양방향으로 등록되므로 삭제도 양방향으로 처리한다.
            A→B를 삭제하면 B→A도 삭제한다.
            삭제 후 빈 set이면 키 자체를 삭제한다.
        """
        removed = False

        if char_a in self._variants and char_b in self._variants[char_a]:
            self._variants[char_a].discard(char_b)
            if not self._variants[char_a]:
                del self._variants[char_a]
            removed = True

        if char_b in self._variants and char_a in self._variants[char_b]:
            self._variants[char_b].discard(char_a)
            if not self._variants[char_b]:
                del self._variants[char_b]
            removed = True

        return removed

    def export_csv(self) -> str:
        """이체자 사전을 CSV 문자열로 내보낸다.

        출력: "글자A,글자B\\n" 형식의 CSV 문자열.
              양방향 중복을 제거하여 한 쌍당 한 줄만 출력한다.

        왜 이렇게 하는가:
            다른 도구에서 사용하거나 백업하기 위해 범용 형식으로 내보낸다.
        """
        seen = set()
        lines = []
        for char, alts in sorted(self._variants.items()):
            for alt in sorted(alts):
                pair_key = tuple(sorted([char, alt]))
                if pair_key not in seen:
                    seen.add(pair_key)
                    lines.append(f"{char},{alt}")
        return "\n".join(lines)

    @property
    def pair_count(self) -> int:
        """양방향 중복을 제거한 실제 이체자 쌍 수."""
        seen = set()
        for char, alts in self._variants.items():
            for alt in alts:
                pair_key = tuple(sorted([char, alt]))
                seen.add(pair_key)
        return len(seen)

    def import_bulk(self, text: str, fmt: str = "auto") -> dict:
        """외부 이체자 데이터를 대량으로 가져온다.

        목적: CSV, TSV, 텍스트, JSON 등 다양한 형식의 이체자 데이터를
              파싱하여 사전에 일괄 등록한다.
        입력:
            text — 가져올 텍스트 데이터.
            fmt — 형식 지정. "auto"이면 자동 감지.
                   "csv", "tsv", "text", "json" 중 하나.
        출력: { "added": 추가된 쌍 수, "skipped": 건너뛴 수, "errors": [에러 목록] }
        """
        if fmt == "auto":
            fmt = self._detect_format(text)

        if fmt == "json":
            return self._import_json(text)
        else:
            return self._import_delimited(text, fmt)

    def _detect_format(self, text: str) -> str:
        """텍스트 형식을 자동 감지한다.

        판별 기준:
          - { 로 시작하면 JSON
          - 탭 문자가 포함되면 TSV
          - 쉼표가 포함되면 CSV
          - 그 외는 공백 구분 텍스트
        """
        stripped = text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            return "json"
        # 첫 몇 줄로 판별
        first_lines = stripped.split("\n", 5)[:5]
        tab_count = sum(1 for line in first_lines if "\t" in line)
        comma_count = sum(1 for line in first_lines if "," in line)
        if tab_count >= 2:
            return "tsv"
        if comma_count >= 2:
            return "csv"
        return "text"

    def _import_delimited(self, text: str, fmt: str) -> dict:
        """구분자 기반 텍스트에서 이체자 쌍을 파싱한다.

        지원 형식:
          - csv: A,B 또는 A,B,C (한 행에 여러 이체자)
          - tsv: A\\tB 또는 A\\tB\\tC
          - text: A B 또는 A↔B (공백/화살표 구분)

        한 행에 3개 이상이면 모든 조합을 양방향 등록한다.
        예: 齒,歯,齿 → 齒↔歯, 齒↔齿, 歯↔齿
        """
        added = 0
        skipped = 0
        errors = []

        for line_num, line in enumerate(text.strip().split("\n"), 1):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue

            # 구분자로 분리
            if fmt == "csv":
                chars = [c.strip() for c in line.split(",")]
            elif fmt == "tsv":
                chars = [c.strip() for c in line.split("\t")]
            else:
                # text: 공백, ↔, =, → 등 다양한 구분자
                import re
                chars = [c.strip() for c in re.split(r"[\s↔=→⇔]+", line)]

            # 빈 항목 제거, 한 글자씩만 허용
            chars = [c for c in chars if c]

            if len(chars) < 2:
                errors.append(f"{line_num}행: 이체자 쌍이 부족합니다 — '{line}'")
                continue

            # 모든 조합을 양방향 등록
            for i in range(len(chars)):
                for j in range(i + 1, len(chars)):
                    a, b = chars[i], chars[j]
                    if a == b:
                        skipped += 1
                        continue
                    # 이미 등록된 쌍은 건너뛰기
                    if self.is_variant(a, b):
                        skipped += 1
                        continue
                    self.add_pair(a, b)
                    added += 1

        return {"added": added, "skipped": skipped, "errors": errors}

    def _import_json(self, text: str) -> dict:
        """JSON 형식에서 이체자 쌍을 파싱한다.

        지원 형식:
          1. 플랫폼 표준: {"variants": {"A": ["B", "C"], "B": ["A"], ...}}
          2. 간단 매핑: {"A": "B", "C": "D", ...}
          3. 간단 배열: {"A": ["B", "C"], ...}
          4. 쌍 배열: [["A", "B"], ["C", "D"], ...]
        """
        added = 0
        skipped = 0
        errors = []

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            return {"added": 0, "skipped": 0, "errors": [f"JSON 파싱 오류: {e}"]}

        # 형식 1: 플랫폼 표준 형식
        if isinstance(data, dict) and "variants" in data:
            data = data["variants"]

        if isinstance(data, dict):
            for char, alts in data.items():
                # _format_guide 같은 메타데이터 건너뛰기
                if char.startswith("_"):
                    continue
                if isinstance(alts, str):
                    # 형식 2: 단순 매핑 {"A": "B"}
                    alts = [alts]
                if isinstance(alts, list):
                    for alt in alts:
                        if not isinstance(alt, str):
                            continue
                        if char == alt:
                            skipped += 1
                            continue
                        if self.is_variant(char, alt):
                            skipped += 1
                            continue
                        self.add_pair(char, alt)
                        added += 1
        elif isinstance(data, list):
            # 형식 4: 쌍 배열 [["A", "B"], ...]
            for idx, pair in enumerate(data):
                if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                    errors.append(f"항목 {idx}: 올바른 쌍이 아닙니다 — {pair}")
                    continue
                # 배열 내 모든 조합 등록
                chars = [c for c in pair if isinstance(c, str)]
                for i in range(len(chars)):
                    for j in range(i + 1, len(chars)):
                        a, b = chars[i], chars[j]
                        if a == b:
                            skipped += 1
                            continue
                        if self.is_variant(a, b):
                            skipped += 1
                            continue
                        self.add_pair(a, b)
                        added += 1

        return {"added": added, "skipped": skipped, "errors": errors}


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

    # ── L4 확정 텍스트 로드 (교정 적용) ──
    # 교정이 있으면 교정 적용된 텍스트를, 없으면 원본을 사용한다.
    # 왜: L4 원본이 OCR에서 그대로 가져온 경우, 교정 없이 대조하면
    #      항상 100% 일치가 나와서 대조가 무의미하다.
    try:
        corrected = get_corrected_text(doc_path, part_id, page_number)
        ref_text = corrected.get("corrected_text", "")
    except Exception:
        ref_text = None

    if not ref_text:
        # 교정 결과도 없고 원본도 없는 경우
        l4_filename = f"{part_id}_page_{page_number:03d}.txt"
        l4_path = doc_path / "L4_text" / "pages" / l4_filename
        ref_text = _load_text(str(l4_path))

    if ref_text is None:
        return [BlockAlignment(
            layout_block_id="*",
            error=f"L4 확정 텍스트를 찾을 수 없습니다: {doc_path / 'L4_text' / 'pages'}",
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

    알고리즘 (후보 필터링 + 검증):
      0. NFC 정규화로 인코딩 차이를 제거
      1. OCR 텍스트의 처음 5자를 ref에서 find → 후보 위치 수집
      2. 후보가 없으면 3-gram으로 재시도
      3. 후보 주변에서만 SequenceMatcher 실행 (O(k*m), k=후보 수)
      4. 최적 위치에서 앞뒤 확장하여 OCR 누락 글자 포함
      5. 유사도가 너무 낮으면 (< 0.3) 전체 참조 텍스트를 반환

    왜 기존 전수 탐색에서 변경했나:
      기존은 ref 전체를 슬라이딩 윈도우로 탐색하여 O(n*m)이었다.
      고전 텍스트 한 페이지가 수백 자일 때 매 블록마다 이를 반복하면 느리고,
      비슷한 구절이 반복되는 고전 텍스트에서 오매칭 위험도 높았다.
      후보 필터링으로 검증 범위를 90% 이상 줄여 속도와 정확도를 모두 개선.
    """
    if not ocr_text or not ref_text:
        return ref_text

    # NFC 정규화
    ocr_text = unicodedata.normalize("NFC", ocr_text)
    ref_text = unicodedata.normalize("NFC", ref_text)

    ocr_len = len(ocr_text)
    ref_len = len(ref_text)

    # 참조가 OCR보다 짧으면 그냥 전체 비교
    if ref_len <= ocr_len:
        return ref_text

    # ── 1단계: 부분 문자열 검색으로 후보 위치 수집 ──
    candidates = _collect_probe_candidates(ocr_text, ref_text, probe_len=5)

    # 5-gram 후보가 없으면 3-gram으로 재시도
    if not candidates:
        candidates = _collect_probe_candidates(ocr_text, ref_text, probe_len=3)

    # ── 2단계: 후보가 있으면 후보 주변에서만 검증 ──
    if candidates:
        best_ratio = 0.0
        best_start = 0

        for cand in candidates:
            # 정확한 OCR 길이 윈도우로 먼저 검증 (정밀도 우선)
            if cand + ocr_len <= ref_len:
                exact_window = ref_text[cand:cand + ocr_len]
                ratio = difflib.SequenceMatcher(None, ocr_text, exact_window).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_start = cand
            # 후보 위치에서 약간 앞당겨 시작하는 윈도우도 시도
            # (probe가 OCR 텍스트 중간에 있을 수 있으므로)
            shifted_start = max(0, cand - ocr_len + 5)
            for s in range(shifted_start, min(cand + 1, ref_len - ocr_len + 1)):
                window = ref_text[s:s + ocr_len]
                ratio = difflib.SequenceMatcher(None, ocr_text, window).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_start = s
    else:
        # 후보가 전혀 없으면 전수 탐색 폴백 (드문 경우)
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

    # ── 3단계: 최적 위치에서 확장하여 누락 글자 포함 ──
    margin = 2
    expand_start = max(0, best_start - margin)
    expand_end = min(ref_len, best_start + ocr_len + margin)

    exact_text = ref_text[best_start:best_start + ocr_len]
    expanded_text = ref_text[expand_start:expand_end]

    exact_ratio = difflib.SequenceMatcher(None, ocr_text, exact_text).ratio()
    expanded_ratio = difflib.SequenceMatcher(None, ocr_text, expanded_text).ratio()

    if expanded_ratio > exact_ratio:
        return expanded_text
    return exact_text


def _collect_probe_candidates(
    ocr_text: str,
    ref_text: str,
    probe_len: int = 5,
) -> list[int]:
    """OCR 텍스트의 여러 위치에서 probe를 추출하여 ref에서 후보 위치를 수집한다.

    왜 여러 위치에서 probe를 추출하나:
      OCR 첫 글자부터 오류일 수 있다. 시작부·중간부·끝부에서 probe를 추출하여
      하나라도 ref에서 발견되면 후보로 채택한다.

    입력:
        ocr_text — OCR 블록 텍스트
        ref_text — L4 참조 텍스트
        probe_len — probe 길이
    출력: 후보 위치 리스트 (중복 제거, 정렬됨)
    """
    if len(ocr_text) < probe_len:
        return []

    # 시작부·중간부·끝부에서 probe 추출
    probes = []
    probes.append(ocr_text[:probe_len])
    if len(ocr_text) >= probe_len * 2:
        mid = len(ocr_text) // 2
        probes.append(ocr_text[mid:mid + probe_len])
    if len(ocr_text) >= probe_len * 3:
        probes.append(ocr_text[-(probe_len):])

    candidates = set()
    for probe in probes:
        start = 0
        while True:
            pos = ref_text.find(probe, start)
            if pos < 0:
                break
            candidates.add(pos)
            start = pos + 1

    return sorted(candidates)


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
