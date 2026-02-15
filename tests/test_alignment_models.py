"""정렬 데이터 모델 테스트."""

from src.core.alignment import (
    AlignedPair,
    AlignmentStats,
    BlockAlignment,
    MatchType,
)


class TestAlignedPair:
    def test_exact_pair(self):
        p = AlignedPair(
            ocr_char="王", ref_char="王", match_type=MatchType.EXACT,
            ocr_index=0, ref_index=0,
        )
        d = p.to_dict()
        assert d["match_type"] == "exact"
        assert d["ocr_char"] == "王"
        assert d["ocr_index"] == 0

    def test_deletion_pair(self):
        p = AlignedPair(
            ocr_char=None, ref_char="清", match_type=MatchType.DELETION,
            ref_index=6,
        )
        assert p.ocr_char is None
        assert p.to_dict()["match_type"] == "deletion"

    def test_insertion_pair(self):
        p = AlignedPair(
            ocr_char="甲", ref_char=None, match_type=MatchType.INSERTION,
            ocr_index=3,
        )
        assert p.ref_char is None
        assert p.to_dict()["match_type"] == "insertion"

    def test_variant_pair(self):
        p = AlignedPair(
            ocr_char="裵", ref_char="裴", match_type=MatchType.VARIANT,
            ocr_index=4, ref_index=4,
        )
        d = p.to_dict()
        assert d["match_type"] == "variant"
        assert d["ocr_char"] == "裵"
        assert d["ref_char"] == "裴"

    def test_mismatch_pair(self):
        p = AlignedPair(
            ocr_char="甲", ref_char="乙", match_type=MatchType.MISMATCH,
        )
        assert p.to_dict()["match_type"] == "mismatch"


class TestMatchType:
    def test_enum_values(self):
        assert MatchType.EXACT.value == "exact"
        assert MatchType.VARIANT.value == "variant"
        assert MatchType.MISMATCH.value == "mismatch"
        assert MatchType.INSERTION.value == "insertion"
        assert MatchType.DELETION.value == "deletion"

    def test_str_enum(self):
        """MatchType은 str Enum이므로 문자열 비교 가능."""
        assert MatchType.EXACT == "exact"


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
        assert abs(stats.accuracy - 2 / 3) < 0.001

    def test_empty(self):
        stats = AlignmentStats.from_pairs([])
        assert stats.accuracy == 0.0
        assert stats.total_chars == 0

    def test_perfect_accuracy(self):
        pairs = [
            AlignedPair("王", "王", MatchType.EXACT),
            AlignedPair("裵", "裴", MatchType.VARIANT),
        ]
        stats = AlignmentStats.from_pairs(pairs)
        assert stats.accuracy == 1.0

    def test_to_dict(self):
        stats = AlignmentStats(total_chars=10, exact=7, variant=1, mismatch=2)
        d = stats.to_dict()
        assert d["total_chars"] == 10
        assert d["accuracy"] == 0.8


class TestBlockAlignment:
    def test_to_dict_basic(self):
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
        assert "stats" in d

    def test_to_dict_with_error(self):
        ba = BlockAlignment(
            layout_block_id="*",
            error="L2 OCR 결과를 찾을 수 없습니다",
        )
        d = ba.to_dict()
        assert d["error"] is not None
        assert "L2" in d["error"]

    def test_to_dict_no_stats(self):
        ba = BlockAlignment(layout_block_id="b01")
        d = ba.to_dict()
        assert "stats" not in d
