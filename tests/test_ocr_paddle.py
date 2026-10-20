"""PaddleOCR 엔진 테스트.

PaddleOCR이 설치되지 않은 환경에서도 기본 테스트가 통과해야 한다.
실제 인식 시험은 PaddleOCR이 설치돼 있으면 자동으로 돈다(아래 skipif).
"""

import pytest

from src.ocr.paddleocr_engine import PaddleOcrEngine


class TestPaddleOcrEngine:
    def test_engine_info(self):
        engine = PaddleOcrEngine()
        assert engine.engine_id == "paddleocr"
        assert engine.requires_network is False

    def test_split_line_to_chars_vertical(self):
        engine = PaddleOcrEngine()
        # 설치 여부와 무관하게 정확히 bool을 돌려준다(1·None 아님)
        # — test_is_available_check(2026-10-12 정리)에서 옮김
        assert isinstance(engine.is_available(), bool)
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
        missing = _paddle_models_missing(engine._lang)
        if missing:
            # 빠른 계층은 바깥 네트워크를 막으므로(conftest) 모델을 받을 수 없다.
            # 이 PC는 캐시가 있어 돌았지만 빈 CI 서버에서는 《모델을 받을 곳이 없다》로
            # 실패했다(D-144 첫 실행, 2026-10-20).
            pytest.skip(
                f"PaddleOCR 모델이 캐시에 없음({', '.join(missing)}) — "
                "한 번 OCR을 돌려 받아 두면 이 시험이 돈다"
            )
        result = engine.recognize(buf.getvalue())
        assert result.engine_id == "paddleocr"


def _paddle_models_missing(lang: str) -> list[str]:
    """실제 인식에 필요한 PaddleX 모델 가운데 로컬 캐시에 없는 것의 이름 목록.

    입력: lang — 엔진의 PaddleOCR 언어 코드(기본 "ch").
    출력: 캐시(`PADDLE_PDX_CACHE_HOME`, 기본 ~/.paddlex)의 official_models에 없는 모델 이름.
    비면 다 있다.
    목적: 모델 이름을 시험에 박지 않고 PaddleOCR이 지금 판에서 고르는 이름을 그대로 묻는다 —
    PaddleOCR을 올려 기본 모델이 바뀌어도 이 검사가 따라간다.
    `_get_ocr_model_names`는 self를 쓰지 않는다.
    """
    from pathlib import Path

    from paddleocr._pipelines.ocr import PaddleOCR
    from paddlex.utils.cache import CACHE_DIR

    names = [n for n in PaddleOCR._get_ocr_model_names(None, lang, None) if n]
    root = Path(CACHE_DIR) / "official_models"
    return [n for n in names if not (root / n).is_dir()]


class TestPaddleImportFailure:
    """패키지 찾기(find_spec)가 ImportError가 아닌 예외로 죽어도 《사용 불가》로 끝나야 한다.

    is_available()은 paddle을 import하지 않고 메타데이터·find_spec만 본다(warmup_paddle 참고) —
    첫 OCR 때 _get_ocr()의 실제 import 실패는 이 시험이 재지 않는다.

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
