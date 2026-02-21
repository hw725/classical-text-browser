"""text_cleaner 단위 테스트.

다양한 표점/현토/공백/대두 조합으로 clean_hwp_text()의 정확성을 검증한다.
"""

import pytest

from hwp.text_cleaner import (
    CleanResult,
    clean_hwp_text,
    detect_hyeonto,
    detect_taidu,
    normalize_punctuation,
    reclean_after_edit,
)


class TestNormalizePunctuation:
    """반각→전각 정규화 테스트."""

    def test_halfwidth_period(self):
        assert normalize_punctuation(".") == "。"

    def test_halfwidth_comma(self):
        assert normalize_punctuation(",") == "，"

    def test_halfwidth_semicolon(self):
        assert normalize_punctuation(";") == "；"

    def test_halfwidth_colon(self):
        assert normalize_punctuation(":") == "："

    def test_halfwidth_question(self):
        assert normalize_punctuation("?") == "？"

    def test_halfwidth_exclamation(self):
        assert normalize_punctuation("!") == "！"

    def test_fullwidth_passthrough(self):
        """전각 표점은 그대로 반환."""
        assert normalize_punctuation("。") == "。"
        assert normalize_punctuation("，") == "，"

    def test_non_punctuation_passthrough(self):
        """표점이 아닌 문자는 그대로 반환."""
        assert normalize_punctuation("天") == "天"


class TestCleanHwpTextPunctuation:
    """표점 분리 테스트."""

    def test_fullwidth_punctuation(self):
        """전각 표점 포함 텍스트 → 표점 분리 + 순수 원문."""
        result = clean_hwp_text("天地之道。忠恕而已矣，")
        assert result.clean_text == "天地之道忠恕而已矣"
        assert result.had_punctuation is True
        assert len(result.punctuation_marks) == 2
        # 첫 번째: 道 뒤의 。
        assert result.punctuation_marks[0]["mark"] == "。"
        assert result.punctuation_marks[0]["pos"] == 3  # 道 = index 3
        # 두 번째: 矣 뒤의 ，
        assert result.punctuation_marks[1]["mark"] == "，"
        assert result.punctuation_marks[1]["pos"] == 8  # 矣 = index 8

    def test_halfwidth_punctuation(self):
        """반각 표점 → 전각으로 정규화 + 분리."""
        result = clean_hwp_text("天地之道.忠恕而已矣,")
        assert result.clean_text == "天地之道忠恕而已矣"
        assert result.punctuation_marks[0]["mark"] == "。"  # . → 。
        assert result.punctuation_marks[0]["original_mark"] == "."
        assert result.punctuation_marks[1]["mark"] == "，"  # , → ，

    def test_halfwidth_with_spaces(self):
        """반각 표점 + 공백 세트 → 공백까지 함께 제거."""
        result = clean_hwp_text("天地之道. 忠恕而已矣, ")
        assert result.clean_text == "天地之道忠恕而已矣"
        assert len(result.punctuation_marks) == 2

    def test_no_punctuation(self):
        """순수 한문 → 변경 없이 통과."""
        result = clean_hwp_text("天地之道忠恕而已矣")
        assert result.clean_text == "天地之道忠恕而已矣"
        assert result.had_punctuation is False
        assert len(result.punctuation_marks) == 0

    def test_strip_punct_false(self):
        """strip_punct=False → 표점 유지."""
        result = clean_hwp_text("天地之道。忠恕", strip_punct=False)
        assert "。" in result.clean_text
        assert result.had_punctuation is False  # 제거 안 했으므로

    def test_empty_text(self):
        """빈 텍스트 → 빈 결과."""
        result = clean_hwp_text("")
        assert result.clean_text == ""
        assert result.had_punctuation is False

    def test_whitespace_only(self):
        """공백만 → 빈 결과."""
        result = clean_hwp_text("   \n\n  ")
        assert result.clean_text == ""


class TestCleanHwpTextHyeonto:
    """현토 분리 테스트."""

    def test_hyeonto_detection(self):
        """현토 포함 텍스트 → 현토 감지 + 분리."""
        result = clean_hwp_text("天地之道는忠恕而已矣니")
        assert result.clean_text == "天地之道忠恕而已矣"
        assert result.had_hyeonto is True
        assert len(result.hyeonto_annotations) == 2
        # 道 뒤의 "는"
        assert result.hyeonto_annotations[0]["text"] == "는"
        assert result.hyeonto_annotations[0]["pos"] == 3
        # 矣 뒤의 "니"
        assert result.hyeonto_annotations[1]["text"] == "니"
        assert result.hyeonto_annotations[1]["pos"] == 8

    def test_hyeonto_with_punctuation(self):
        """현토 + 표점 혼합 → 둘 다 분리."""
        result = clean_hwp_text("天地之道는。忠恕而已矣니，")
        assert result.clean_text == "天地之道忠恕而已矣"
        assert result.had_hyeonto is True
        assert result.had_punctuation is True

    def test_hyeonto_with_punct_and_space(self):
        """현토 + 표점 + 공백 세트."""
        result = clean_hwp_text("天地之道는. 忠恕")
        assert result.clean_text == "天地之道忠恕"
        assert result.had_hyeonto is True
        assert result.had_punctuation is True

    def test_strip_hyeonto_false(self):
        """strip_hyeonto=False → 현토 유지."""
        result = clean_hwp_text("天地之道는忠恕", strip_hyeonto=False)
        assert "는" in result.clean_text
        assert result.had_hyeonto is False

    def test_multi_char_hyeonto(self):
        """여러 글자 현토 (2~4자)."""
        result = clean_hwp_text("夫子之道하니忠恕而已矣니라")
        assert result.clean_text == "夫子之道忠恕而已矣"
        hyeonto_texts = [h["text"] for h in result.hyeonto_annotations]
        assert "하니" in hyeonto_texts
        assert "니라" in hyeonto_texts


class TestCleanHwpTextTaidu:
    """대두 감지 테스트."""

    def test_taidu_detection(self):
        """줄머리 공백 → 대두 후보 감지."""
        text = "天地之道\n 臣聞天地\n忠恕而已"
        result = clean_hwp_text(text)
        assert result.had_taidu is True
        assert len(result.taidu_marks) >= 1
        # 臣 앞의 공백 1자
        assert any(t["raise_chars"] == 1 for t in result.taidu_marks)

    def test_taidu_two_spaces(self):
        """2자 공백 대두."""
        text = "天地之道\n  臣聞天地"
        candidates = detect_taidu(text)
        assert len(candidates) >= 1
        assert candidates[0]["raise_chars"] == 2


class TestDetectHyeonto:
    """detect_hyeonto() 단독 테스트."""

    def test_basic_pattern(self):
        """[한자][한글][한자] 패턴."""
        results = detect_hyeonto("天地는道也")
        assert len(results) == 1
        assert results[0]["text"] == "는"

    def test_no_hyeonto(self):
        """현토 없는 순수 한문."""
        results = detect_hyeonto("天地之道忠恕而已矣")
        assert len(results) == 0


class TestRecleanAfterEdit:
    """편집 후 재계산 테스트."""

    def test_replace_char(self):
        """글자 교체 → pos 불변."""
        result = reclean_after_edit(
            clean_text="天地之道忠恕",
            edits=[{"type": "replace", "pos": 2, "new_char": "的"}],
            punctuation_marks=[{"pos": 3, "mark": "。", "original_mark": "。"}],
            hyeonto_annotations=[],
        )
        assert result.clean_text == "天地的道忠恕"
        assert result.punctuation_marks[0]["pos"] == 3  # 불변

    def test_insert_char(self):
        """글자 삽입 → pos +1 시프트."""
        result = reclean_after_edit(
            clean_text="天地道忠恕",
            edits=[{"type": "insert", "pos": 2, "new_char": "之"}],
            punctuation_marks=[{"pos": 2, "mark": "。", "original_mark": "。"}],
            hyeonto_annotations=[{"pos": 4, "text": "니", "position": "after"}],
        )
        assert result.clean_text == "天地之道忠恕"
        assert result.punctuation_marks[0]["pos"] == 3  # 2→3
        assert result.hyeonto_annotations[0]["pos"] == 5  # 4→5

    def test_delete_char(self):
        """글자 삭제 → pos -1 시프트."""
        result = reclean_after_edit(
            clean_text="天地之道忠恕",
            edits=[{"type": "delete", "pos": 2}],
            punctuation_marks=[{"pos": 3, "mark": "。", "original_mark": "。"}],
            hyeonto_annotations=[],
        )
        assert result.clean_text == "天地道忠恕"
        assert result.punctuation_marks[0]["pos"] == 2  # 3→2


class TestPdfExtractor:
    """PdfTextExtractor 기본 테스트 (파일 없이)."""

    def test_file_not_found(self):
        """존재하지 않는 파일 → FileNotFoundError."""
        from text_import.pdf_extractor import PdfTextExtractor

        with pytest.raises(FileNotFoundError):
            PdfTextExtractor("nonexistent.pdf")
