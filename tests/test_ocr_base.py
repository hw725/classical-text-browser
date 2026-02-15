"""OCR 기본 데이터 모델 테스트.

OcrCharResult, OcrLineResult, OcrBlockResult의 to_dict()가
ocr_page.schema.json과 호환되는 출력을 생성하는지 검증한다.
"""

import pytest
from src.ocr.base import (
    BaseOcrEngine,
    OcrBlockResult,
    OcrCharResult,
    OcrEngineError,
    OcrEngineUnavailableError,
    OcrLineResult,
)


class TestOcrCharResult:
    def test_to_dict_basic(self):
        char = OcrCharResult(char="王", bbox=[0, 0, 50, 50], confidence=0.95)
        d = char.to_dict()
        assert d["char"] == "王"
        assert d["bbox"] == [0, 0, 50, 50]
        assert d["confidence"] == 0.95

    def test_to_dict_no_bbox(self):
        char = OcrCharResult(char="戎")
        d = char.to_dict()
        assert d["char"] == "戎"
        assert "bbox" not in d
        assert "confidence" not in d

    def test_to_dict_rounding(self):
        char = OcrCharResult(char="A", bbox=[1.12345, 2.6789, 3.111, 4.999], confidence=0.87654)
        d = char.to_dict()
        assert d["bbox"] == [1.12, 2.68, 3.11, 5.0]
        assert d["confidence"] == 0.8765


class TestOcrLineResult:
    def test_to_dict_with_characters(self):
        line = OcrLineResult(
            text="王戎",
            bbox=[0, 0, 50, 100],
            characters=[
                OcrCharResult(char="王", confidence=0.95),
                OcrCharResult(char="戎", confidence=0.90),
            ],
        )
        d = line.to_dict()
        assert d["text"] == "王戎"
        assert d["bbox"] == [0, 0, 50, 100]
        assert len(d["characters"]) == 2
        assert d["characters"][0]["char"] == "王"

    def test_to_dict_no_characters(self):
        line = OcrLineResult(text="텍스트")
        d = line.to_dict()
        assert d["text"] == "텍스트"
        assert "characters" not in d

    def test_to_dict_no_bbox(self):
        line = OcrLineResult(text="줄")
        d = line.to_dict()
        assert "bbox" not in d


class TestOcrBlockResult:
    def test_to_dict_schema_compliant(self):
        """to_dict()가 ocr_page.schema.json의 OcrResult 형식만 출력하는지.

        스키마에 additionalProperties: false이므로
        lines와 layout_block_id만 허용된다.
        layout_block_id는 파이프라인에서 추가하므로 여기선 lines만.
        """
        block = OcrBlockResult(
            lines=[OcrLineResult(text="王戎簡要", bbox=[0, 0, 50, 200])],
            engine_id="paddleocr",
            language="classical_chinese",
            writing_direction="vertical_rtl",
            raw_engine_output={"debug": "data"},
        )
        d = block.to_dict()
        # lines만 있어야 한다 (engine_id, language 등은 포함 안 됨)
        assert "lines" in d
        assert len(d["lines"]) == 1
        assert "engine_id" not in d
        assert "language" not in d
        assert "raw_engine_output" not in d

    def test_full_text(self):
        block = OcrBlockResult(
            lines=[
                OcrLineResult(text="王戎簡要"),
                OcrLineResult(text="裴楷清通"),
            ]
        )
        assert block.full_text == "王戎簡要\n裴楷清通"

    def test_avg_confidence(self):
        block = OcrBlockResult(
            lines=[
                OcrLineResult(
                    text="AB",
                    characters=[
                        OcrCharResult(char="A", confidence=0.8),
                        OcrCharResult(char="B", confidence=0.6),
                    ],
                ),
            ]
        )
        assert block.avg_confidence == pytest.approx(0.7)

    def test_avg_confidence_empty(self):
        block = OcrBlockResult()
        assert block.avg_confidence == 0.0

    def test_char_count(self):
        block = OcrBlockResult(
            lines=[
                OcrLineResult(text="王戎"),
                OcrLineResult(text="簡要裴楷"),
            ]
        )
        assert block.char_count == 6


class TestExceptions:
    def test_ocr_engine_error(self):
        with pytest.raises(OcrEngineError):
            raise OcrEngineError("테스트 에러")

    def test_unavailable_is_subclass(self):
        assert issubclass(OcrEngineUnavailableError, OcrEngineError)


class TestBaseOcrEngine:
    def test_abstract_methods(self):
        """BaseOcrEngine은 직접 인스턴스를 만들 수 없다."""
        with pytest.raises(TypeError):
            BaseOcrEngine()

    def test_get_info(self):
        """구현체의 get_info()가 올바른 형식을 반환하는지."""
        class DummyEngine(BaseOcrEngine):
            engine_id = "dummy"
            display_name = "Dummy"
            requires_network = False

            def is_available(self):
                return True

            def recognize(self, image_bytes, **kwargs):
                return OcrBlockResult()

        engine = DummyEngine()
        info = engine.get_info()
        assert info["engine_id"] == "dummy"
        assert info["display_name"] == "Dummy"
        assert info["requires_network"] is False
        assert info["available"] is True
