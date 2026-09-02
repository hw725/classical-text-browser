"""PaddleOCR 엔진 테스트.

PaddleOCR이 설치되지 않은 환경에서도 기본 테스트가 통과해야 한다.
실제 인식 테스트는 PaddleOCR 설치 후 수동으로 실행.
"""

import pytest

from src.ocr.paddleocr_engine import PaddleOcrEngine


class TestPaddleOcrEngine:
    def test_engine_info(self):
        engine = PaddleOcrEngine()
        assert engine.engine_id == "paddleocr"
        assert engine.requires_network is False

    def test_is_available_check(self):
        engine = PaddleOcrEngine()
        # 설치 여부에 따라 True/False — 에러 없이 반환만 확인
        result = engine.is_available()
        assert isinstance(result, bool)

    def test_split_line_to_chars_vertical(self):
        engine = PaddleOcrEngine()
        chars = engine._split_line_to_chars(
            text="王戎",
            line_bbox=[10.0, 0.0, 30.0, 100.0],
            line_confidence=0.95,
            writing_direction="vertical_rtl",
        )
        assert len(chars) == 2
        assert chars[0].char == "王"
        assert chars[1].char == "戎"
        # 세로쓰기: y축 분할
        assert chars[0].bbox[1] == 0.0  # 王은 위쪽
        assert chars[1].bbox[1] == 50.0  # 戎은 아래쪽

    def test_split_line_to_chars_horizontal(self):
        engine = PaddleOcrEngine()
        chars = engine._split_line_to_chars(
            text="AB",
            line_bbox=[0.0, 10.0, 100.0, 30.0],
            line_confidence=0.9,
            writing_direction="horizontal_ltr",
        )
        assert len(chars) == 2
        assert chars[0].char == "A"
        # 가로쓰기: x축 분할
        assert chars[0].bbox[0] == 0.0
        assert chars[1].bbox[0] == 50.0

    def test_split_empty_text(self):
        engine = PaddleOcrEngine()
        chars = engine._split_line_to_chars(
            text="",
            line_bbox=[0.0, 0.0, 100.0, 100.0],
            line_confidence=0.9,
            writing_direction="vertical_rtl",
        )
        assert chars == []

    def test_split_single_char(self):
        engine = PaddleOcrEngine()
        chars = engine._split_line_to_chars(
            text="王",
            line_bbox=[10.0, 20.0, 50.0, 80.0],
            line_confidence=0.88,
            writing_direction="vertical_rtl",
        )
        assert len(chars) == 1
        assert chars[0].char == "王"
        assert chars[0].confidence == 0.88
        # 1글자이면 bbox가 줄 전체
        assert chars[0].bbox == [10.0, 20.0, 50.0, 80.0]

    @pytest.mark.skipif(not PaddleOcrEngine().is_available(), reason="PaddleOCR 미설치")
    def test_recognize_real(self):
        """실제 PaddleOCR 인식 테스트 (PaddleOCR 설치 시에만 실행)."""
        import io

        from PIL import Image, ImageDraw

        # 간단한 한자 이미지 생성
        img = Image.new("RGB", (200, 200), "white")
        draw = ImageDraw.Draw(img)
        draw.text((50, 50), "王", fill="black")

        buf = io.BytesIO()
        img.save(buf, format="PNG")

        engine = PaddleOcrEngine()
        result = engine.recognize(buf.getvalue())
        assert result.engine_id == "paddleocr"


class TestPaddleImportFailure:
    """import paddle이 ImportError가 아닌 예외로 죽어도 «사용 불가»로 끝나야 한다.

    Windows에서 DLL 로드 실패(OSError)가 실제 사례다. 예외가 새어 나가면 엔진 목록
    API 전체가 500이 된다.
    """

    def test_non_import_error_becomes_unavailable(self, monkeypatch):
        import importlib.abc
        import sys

        class _Exploding(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path, target=None):
                if fullname == "paddle":
                    raise OSError("[WinError 126] 지정된 모듈을 찾을 수 없습니다")
                return None

        for name in [m for m in sys.modules if m == "paddle" or m.startswith("paddle.")]:
            monkeypatch.delitem(sys.modules, name)
        monkeypatch.setattr(sys, "meta_path", [_Exploding()] + sys.meta_path)

        engine = PaddleOcrEngine()
        assert engine.is_available() is False
        assert "OSError" in engine._unavailable_reason
        assert "WinError 126" in engine._unavailable_reason
        # get_info()도 예외 없이 이유를 내보낸다
        info = engine.get_info()
        assert info["available"] is False and "OSError" in info["unavailable_reason"]
