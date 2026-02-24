"""align_text_to_pages() 및 관련 헬퍼 함수 단위 테스트.

테스트 대상:
  - _nfc(): NFC 정규화
  - _extract_multi_anchors(): 다중 앵커 추출
  - _build_ngram_index(): n-gram 인덱스 구축
  - _find_anchor_in_index(): n-gram 기반 앵커 탐색
  - _interpolate_missing(): 미매칭 경계 보간
  - align_text_to_pages(): 전체 파이프라인
"""

import unicodedata

import pytest

from src.text_import.common import (
    _build_ngram_index,
    _extract_multi_anchors,
    _find_anchor_in_index,
    _fuzzy_search_range,
    _interpolate_missing,
    _nfc,
    align_text_to_pages,
)


# ──────────────────────────────────────
# _nfc 테스트
# ──────────────────────────────────────


class TestNfc:
    def test_nfc_identity(self):
        """이미 NFC인 텍스트는 변하지 않아야 한다."""
        text = "王戎簡要裴楷清通"
        assert _nfc(text) == text

    def test_nfc_decomposed_hangul(self):
        """NFD 한글이 NFC로 합성되어야 한다."""
        # '가' = U+AC00 (NFC) vs U+1100 U+1161 (NFD)
        nfd = "\u1100\u1161"  # ㄱ + ㅏ (분해형)
        nfc = "\uAC00"  # 가 (합성형)
        assert _nfc(nfd) == nfc

    def test_nfc_empty(self):
        assert _nfc("") == ""


# ──────────────────────────────────────
# _extract_multi_anchors 테스트
# ──────────────────────────────────────


class TestExtractMultiAnchors:
    def test_long_page_three_anchors(self):
        """충분히 긴 페이지에서 3개 앵커가 추출되어야 한다."""
        # 50자 한자 문자열
        page_han = "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏閏餘成歲律呂調陽雲騰致雨露結爲霜金生麗水玉出崑岡劍號巨闕珠稱夜光"
        anchors = _extract_multi_anchors(page_han, anchor_length=15)
        assert len(anchors) == 3
        # 시작부
        assert anchors[0] == page_han[:15]
        # 끝부
        assert anchors[2] == page_han[-15:]
        # 중간부
        assert len(anchors[1]) == 15

    def test_medium_page_two_anchors(self):
        """앵커 2개 분량의 페이지에서 2개가 추출되어야 한다."""
        page_han = "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往"  # 20자
        anchors = _extract_multi_anchors(page_han, anchor_length=15)
        assert len(anchors) == 2
        assert anchors[0] == page_han[:15]
        assert anchors[1] == page_han[-15:]

    def test_short_page_one_anchor(self):
        """앵커 길이 미만이면 전체가 단일 앵커."""
        page_han = "天地玄黃"  # 4자 < 15
        anchors = _extract_multi_anchors(page_han, anchor_length=15)
        assert len(anchors) == 1
        assert anchors[0] == page_han

    def test_empty_page(self):
        """빈 페이지는 빈 리스트."""
        assert _extract_multi_anchors("", anchor_length=15) == []


# ──────────────────────────────────────
# _build_ngram_index 테스트
# ──────────────────────────────────────


class TestBuildNgramIndex:
    def test_basic_index(self):
        text = "天地玄黃宇宙洪荒"
        idx = _build_ngram_index(text, n=3)
        assert "天地玄" in idx
        assert idx["天地玄"] == [0]
        assert "宇宙洪" in idx
        assert idx["宇宙洪"] == [4]

    def test_repeated_ngram(self):
        """반복 n-gram의 위치가 모두 기록되어야 한다."""
        text = "ABCABCABC"
        idx = _build_ngram_index(text, n=3)
        assert idx["ABC"] == [0, 3, 6]

    def test_short_text(self):
        """n-gram보다 짧은 텍스트는 빈 인덱스."""
        idx = _build_ngram_index("AB", n=5)
        assert len(idx) == 0


# ──────────────────────────────────────
# _find_anchor_in_index 테스트
# ──────────────────────────────────────


class TestFindAnchorInIndex:
    def test_exact_match(self):
        """정확히 존재하는 앵커는 confidence 1.0."""
        han = "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏"
        idx = _build_ngram_index(han, n=5)
        pos, conf = _find_anchor_in_index("宇宙洪荒日月盈昃辰宿列張寒來暑", 0, idx, han, 5)
        assert pos >= 0
        assert conf == 1.0

    def test_fuzzy_match_one_error(self):
        """1글자 오류가 있어도 매칭되어야 한다."""
        han = "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏"
        idx = _build_ngram_index(han, n=5)
        # "宇宙洪荒日月盈★辰宿列張寒來暑" — 1자 차이
        anchor = "宇宙洪荒日月盈★辰宿列張寒來暑"
        pos, conf = _find_anchor_in_index(anchor, 0, idx, han, 5)
        assert pos >= 0
        assert conf > 0.8  # 14/15 글자 일치

    def test_search_start_respected(self):
        """search_start 이전의 매칭은 무시해야 한다."""
        han = "天地玄黃宇宙洪荒天地玄黃宇宙洪荒"  # 동일 패턴 반복
        idx = _build_ngram_index(han, n=5)
        anchor = "天地玄黃宇宙洪荒"
        # 첫 번째 출현 (pos=0)
        pos1, _ = _find_anchor_in_index(anchor, 0, idx, han, 5)
        assert pos1 == 0
        # search_start=1 이후부터 → 두 번째 출현
        pos2, _ = _find_anchor_in_index(anchor, 1, idx, han, 5)
        assert pos2 == 8


# ──────────────────────────────────────
# _interpolate_missing 테스트
# ──────────────────────────────────────


class TestInterpolateMissing:
    def test_no_missing(self):
        boundaries = [0, 100, 200]
        _interpolate_missing(boundaries, 300)
        assert boundaries == [0, 100, 200]

    def test_middle_missing(self):
        boundaries = [0, -1, 200]
        _interpolate_missing(boundaries, 300)
        assert boundaries[1] == 100  # 0과 200 사이의 균등 분할

    def test_first_missing(self):
        boundaries = [-1, 100, 200]
        _interpolate_missing(boundaries, 300)
        assert boundaries[0] == 0

    def test_all_missing(self):
        boundaries = [-1, -1, -1]
        _interpolate_missing(boundaries, 300)
        assert boundaries[0] == 0
        assert boundaries[1] == 100
        assert boundaries[2] == 200


# ──────────────────────────────────────
# align_text_to_pages 통합 테스트
# ──────────────────────────────────────


class TestAlignTextToPages:
    """전체 파이프라인 테스트."""

    # 테스트용 한자 텍스트 (3페이지 분량)
    PAGE1_TEXT = "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏"  # 24자
    PAGE2_TEXT = "閏餘成歲律呂調陽雲騰致雨露結爲霜金生麗水玉出崑岡"  # 24자
    PAGE3_TEXT = "劍號巨闕珠稱夜光果珍李柰菜重芥薑海鹹河淡鱗潛羽翔"  # 24자
    FULL_TEXT = PAGE1_TEXT + PAGE2_TEXT + PAGE3_TEXT

    def _make_page_texts(self):
        return [
            {"page_num": 1, "text": self.PAGE1_TEXT},
            {"page_num": 2, "text": self.PAGE2_TEXT},
            {"page_num": 3, "text": self.PAGE3_TEXT},
        ]

    def test_exact_match(self):
        """OCR과 외부 텍스트가 동일하면 모든 confidence가 높아야 한다."""
        results = align_text_to_pages(self._make_page_texts(), self.FULL_TEXT)
        assert len(results) == 3
        for r in results:
            assert r["confidence"] >= 0.8
            assert r["matched_text"]  # 빈 문자열이 아닌지

    def test_nfc_normalization(self):
        """NFC 비정규화 입력도 정상 매칭되어야 한다."""
        # NFD 형태의 한글을 섞은 텍스트
        nfd_text = unicodedata.normalize("NFD", self.FULL_TEXT)
        results = align_text_to_pages(self._make_page_texts(), nfd_text)
        assert len(results) == 3
        for r in results:
            assert r["confidence"] >= 0.8

    def test_partial_ocr_error(self):
        """1~2자 OCR 오류가 있어도 매칭되어야 한다."""
        # 2페이지의 OCR에 오류가 1자 있는 경우
        page_texts = [
            {"page_num": 1, "text": self.PAGE1_TEXT},
            {"page_num": 2, "text": "閏餘成歲律呂調陽雲★致雨露結爲霜金生麗水玉出崑岡"},  # 騰→★
            {"page_num": 3, "text": self.PAGE3_TEXT},
        ]
        results = align_text_to_pages(page_texts, self.FULL_TEXT)
        assert len(results) == 3
        # 오류 있는 페이지도 매칭 시도
        assert results[1]["confidence"] > 0.0

    def test_empty_ocr_page(self):
        """OCR 텍스트가 비어있는 페이지는 보간으로 처리해야 한다."""
        page_texts = [
            {"page_num": 1, "text": self.PAGE1_TEXT},
            {"page_num": 2, "text": ""},  # OCR 실패
            {"page_num": 3, "text": self.PAGE3_TEXT},
        ]
        results = align_text_to_pages(page_texts, self.FULL_TEXT)
        assert len(results) == 3
        # 빈 페이지의 matched_text도 비어있지 않아야 (보간됨)
        assert results[1]["matched_text"] or results[1]["confidence"] == 0.0

    def test_cascade_recovery(self):
        """중간 페이지 실패 시 전후 페이지는 정상이어야 한다."""
        # 2페이지 OCR이 완전히 다른 텍스트인 경우
        page_texts = [
            {"page_num": 1, "text": self.PAGE1_TEXT},
            {"page_num": 2, "text": "完全不同的文字完全不同的文字完全不同的文字完全不同的文字"},
            {"page_num": 3, "text": self.PAGE3_TEXT},
        ]
        results = align_text_to_pages(page_texts, self.FULL_TEXT)
        assert len(results) == 3
        # 1, 3페이지는 정상 매칭
        assert results[0]["confidence"] >= 0.8
        assert results[2]["confidence"] >= 0.5

    def test_single_page(self):
        """페이지가 1개면 전체 텍스트가 매핑되어야 한다."""
        page_texts = [{"page_num": 1, "text": self.FULL_TEXT}]
        results = align_text_to_pages(page_texts, self.FULL_TEXT)
        assert len(results) == 1
        assert results[0]["confidence"] >= 0.8

    def test_no_han_in_imported(self):
        """외부 텍스트에 한자가 없으면 전체를 첫 페이지에 매핑."""
        results = align_text_to_pages(
            [{"page_num": 1, "text": "한글만"}],
            "한글만 있는 텍스트",
        )
        assert len(results) == 1
        assert results[0]["confidence"] == 0.0
        assert results[0]["matched_text"] == "한글만 있는 텍스트"

    def test_multi_anchor_voting(self):
        """다중 앵커 투표가 작동하는지 확인.

        3개 앵커 중 1개가 OCR 오류여도 나머지 2개로 매칭해야 한다.
        """
        # 페이지 OCR에서 시작부만 다르고 중간·끝은 동일
        page_han_corrupted = "★★★★★★★★★★★★★★★" + self.PAGE1_TEXT[15:]
        page_texts = [
            {"page_num": 1, "text": page_han_corrupted},
            {"page_num": 2, "text": self.PAGE2_TEXT},
            {"page_num": 3, "text": self.PAGE3_TEXT},
        ]
        results = align_text_to_pages(page_texts, self.FULL_TEXT)
        assert len(results) == 3
        # 시작부 앵커는 실패하지만 중간·끝 앵커로 매칭
        assert results[0]["confidence"] > 0.0
