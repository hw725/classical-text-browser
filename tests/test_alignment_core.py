"""핵심 정렬 알고리즘 테스트."""

import json

import pytest

from src.core.alignment import (
    AlignedPair,
    MatchType,
    VariantCharDict,
    align_texts,
    compute_stats,
)


@pytest.fixture
def variant_dict(tmp_path):
    data = {
        "variants": {
            "裴": ["裵"],
            "裵": ["裴"],
            "說": ["説"],
            "説": ["說"],
        },
    }
    path = tmp_path / "variants.json"
    with open(path, "w", encoding="utf-8") as f:
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
        deletions = [p for p in pairs if p.match_type == MatchType.DELETION]
        assert len(deletions) >= 1

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
        pairs = align_texts(
            "王戎簡要裵楷通", "王戎簡要裴楷清通", variant_dict=variant_dict,
        )

        types = {p.match_type for p in pairs}
        assert MatchType.EXACT in types
        assert MatchType.VARIANT in types  # 裵/裴

        stats = compute_stats(pairs)
        assert stats.exact >= 5  # 王戎簡要楷通 (최소)
        assert stats.variant >= 1  # 裵/裴

    def test_index_tracking(self):
        """ocr_index와 ref_index가 올바르게 추적되는지."""
        pairs = align_texts("AB", "AB")
        assert pairs[0].ocr_index == 0
        assert pairs[0].ref_index == 0
        assert pairs[1].ocr_index == 1
        assert pairs[1].ref_index == 1

    def test_single_char_mismatch(self):
        pairs = align_texts("A", "B")
        assert len(pairs) == 1
        assert pairs[0].match_type == MatchType.MISMATCH

    def test_replace_longer_ocr(self):
        """replace에서 OCR이 더 긴 경우: 공통부분 mismatch + 나머지 insertion."""
        pairs = align_texts("ABC", "X")
        # A→X (mismatch), B (insertion), C (insertion) 또는 유사한 분류
        insertions = [p for p in pairs if p.match_type == MatchType.INSERTION]
        mismatches = [p for p in pairs if p.match_type == MatchType.MISMATCH]
        assert len(insertions) + len(mismatches) == 3

    def test_replace_longer_ref(self):
        """replace에서 ref가 더 긴 경우: 공통부분 mismatch + 나머지 deletion."""
        pairs = align_texts("X", "ABC")
        deletions = [p for p in pairs if p.match_type == MatchType.DELETION]
        mismatches = [p for p in pairs if p.match_type == MatchType.MISMATCH]
        assert len(deletions) + len(mismatches) == 3


class TestComputeStats:
    def test_basic(self, variant_dict):
        pairs = align_texts("王裵", "王裴", variant_dict=variant_dict)
        stats = compute_stats(pairs)
        assert stats.total_chars == 2
        assert stats.exact == 1
        assert stats.variant == 1
        assert stats.accuracy == 1.0  # exact + variant = total

    def test_with_all_types(self, variant_dict):
        """다양한 유형이 혼합된 경우."""
        pairs = [
            AlignedPair("王", "王", MatchType.EXACT),
            AlignedPair("裵", "裴", MatchType.VARIANT),
            AlignedPair("甲", "乙", MatchType.MISMATCH),
            AlignedPair("丙", None, MatchType.INSERTION),
            AlignedPair(None, "丁", MatchType.DELETION),
        ]
        stats = compute_stats(pairs)
        assert stats.total_chars == 5
        assert stats.exact == 1
        assert stats.variant == 1
        assert stats.mismatch == 1
        assert stats.insertion == 1
        assert stats.deletion == 1
        assert stats.accuracy == 0.4  # 2/5
