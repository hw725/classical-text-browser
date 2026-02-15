"""OCR 엔진 레지스트리 테스트."""

import pytest
from src.ocr.base import BaseOcrEngine, OcrBlockResult, OcrEngineUnavailableError
from src.ocr.registry import OcrEngineRegistry


class DummyEngine(BaseOcrEngine):
    """테스트용 더미 엔진."""
    engine_id = "dummy"
    display_name = "Dummy"
    requires_network = False

    def is_available(self):
        return True

    def recognize(self, image_bytes, **kwargs):
        return OcrBlockResult()


class UnavailableEngine(BaseOcrEngine):
    """사용 불가 상태인 더미 엔진."""
    engine_id = "unavailable"
    display_name = "Unavailable"
    requires_network = True

    def is_available(self):
        return False

    def recognize(self, image_bytes, **kwargs):
        return OcrBlockResult()


class TestOcrEngineRegistry:
    def test_register_and_get(self):
        registry = OcrEngineRegistry()
        engine = DummyEngine()
        registry.register(engine)

        result = registry.get_engine("dummy")
        assert result is engine

    def test_default_engine(self):
        """첫 번째로 사용 가능한 엔진이 기본값."""
        registry = OcrEngineRegistry()
        registry.register(DummyEngine())

        assert registry.default_engine_id == "dummy"
        engine = registry.get_engine()  # None → 기본 엔진
        assert engine.engine_id == "dummy"

    def test_unavailable_not_default(self):
        """사용 불가 엔진은 기본값이 되지 않는다."""
        registry = OcrEngineRegistry()
        registry.register(UnavailableEngine())

        assert registry.default_engine_id is None

    def test_get_nonexistent(self):
        """존재하지 않는 엔진 조회 시 에러."""
        registry = OcrEngineRegistry()
        registry.register(DummyEngine())

        with pytest.raises(OcrEngineUnavailableError, match="찾을 수 없습니다"):
            registry.get_engine("nonexistent")

    def test_get_unavailable(self):
        """사용 불가 엔진 조회 시 에러."""
        registry = OcrEngineRegistry()
        registry.register(UnavailableEngine())

        with pytest.raises(OcrEngineUnavailableError, match="사용할 수 없는"):
            registry.get_engine("unavailable")

    def test_get_no_engines(self):
        """엔진이 하나도 없을 때 기본 엔진 조회 시 에러."""
        registry = OcrEngineRegistry()

        with pytest.raises(OcrEngineUnavailableError, match="등록된 OCR 엔진이 없습니다"):
            registry.get_engine()

    def test_list_engines(self):
        registry = OcrEngineRegistry()
        registry.register(DummyEngine())
        registry.register(UnavailableEngine())

        engines = registry.list_engines()
        assert len(engines) == 2
        ids = {e["engine_id"] for e in engines}
        assert ids == {"dummy", "unavailable"}

    def test_set_default_engine(self):
        """기본 엔진을 수동으로 변경."""
        registry = OcrEngineRegistry()
        registry.register(DummyEngine())

        # 같은 ID로 다른 엔진 등록
        class AnotherEngine(BaseOcrEngine):
            engine_id = "another"
            display_name = "Another"
            requires_network = False
            def is_available(self): return True
            def recognize(self, image_bytes, **kwargs): return OcrBlockResult()

        registry.register(AnotherEngine())
        registry.default_engine_id = "another"
        assert registry.default_engine_id == "another"

    def test_set_default_nonexistent(self):
        """등록되지 않은 엔진을 기본으로 설정하면 에러."""
        registry = OcrEngineRegistry()
        with pytest.raises(ValueError, match="등록되지 않은 엔진"):
            registry.default_engine_id = "nonexistent"

    def test_auto_register(self):
        """auto_register()가 에러 없이 실행되는지 (PaddleOCR 미설치 환경에서도)."""
        registry = OcrEngineRegistry()
        registry.auto_register()
        # PaddleOCR 설치 여부에 따라 0개 또는 1개
        assert isinstance(registry.list_engines(), list)
