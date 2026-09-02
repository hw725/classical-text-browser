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

            def is_available(self):
                return True

            def recognize(self, image_bytes, **kwargs):
                return OcrBlockResult()

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


class BrokenEngine(BaseOcrEngine):
    """상태 확인이 예외로 죽는 엔진 — DLL 로드 실패·cv2 배포판 충돌을 흉내 낸다."""

    engine_id = "broken"
    display_name = "Broken"
    requires_network = False

    def is_available(self):
        # 기본 엔진이 이미 정해진 뒤 등록되면 register()는 이걸 부르지 않는다.
        # 목록 조회(get_info)에서 처음 불리며 죽는다.
        raise AttributeError("module 'cv2' has no attribute 'IMREAD_COLOR'")

    def recognize(self, image_bytes, **kwargs):
        return OcrBlockResult()


class TestEngineListRobustness:
    """엔진 하나가 깨져도 목록 API는 살아야 한다 (D-044·D-056 — 실패는 available=False)."""

    def test_list_survives_broken_engine(self):
        registry = OcrEngineRegistry()
        registry.register(DummyEngine())
        registry.register(BrokenEngine())

        infos = {i["engine_id"]: i for i in registry.list_engines()}
        assert infos["dummy"]["available"] is True
        assert infos["broken"]["available"] is False
        assert "AttributeError" in infos["broken"]["unavailable_reason"]
        assert "IMREAD_COLOR" in infos["broken"]["unavailable_reason"]

    def test_get_info_exposes_unavailable_reason(self):
        engine = UnavailableEngine()
        engine._unavailable_reason = "onnxruntime이 설치되지 않았습니다."
        info = engine.get_info()
        assert info["available"] is False
        assert info["unavailable_reason"] == "onnxruntime이 설치되지 않았습니다."
        # 사용 가능한 엔진에는 이유 필드가 없다
        assert "unavailable_reason" not in DummyEngine().get_info()


class TestEnginesApi:
    """/api/ocr/engines — 초기화 예외를 원인과 함께 500으로 내보낸다.

    왜: 예전에는 예외가 그대로 새어 나가 화면이 «서고를 선택하면 엔진 목록이
    표시됩니다»로 잘못 안내했다. 서고가 있는 사용자는 무엇을 고쳐야 하는지 알 수 없었다.
    """

    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("USERPROFILE", str(fake_home))
        monkeypatch.setenv("HOME", str(fake_home))
        from fastapi.testclient import TestClient

        from app.server import app

        with TestClient(app) as c:
            yield c

    def test_no_library_message(self, client, monkeypatch):
        import app.routers.llm_ocr as mod

        monkeypatch.setattr(mod, "get_library_path", lambda: None)
        r = client.get("/api/ocr/engines")
        assert r.status_code == 500
        assert r.json()["error"] == "서고가 설정되지 않았습니다."

    def test_init_failure_reports_cause(self, client, monkeypatch, tmp_path):
        import app.routers.llm_ocr as mod

        monkeypatch.setattr(mod, "get_library_path", lambda: tmp_path)

        def _boom():
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

        monkeypatch.setattr(mod, "_get_ocr_pipeline", _boom)
        r = client.get("/api/ocr/engines")
        assert r.status_code == 500
        body = r.json()
        assert body["error_type"] == "UnicodeDecodeError"
        assert body["error"].startswith("OCR 엔진 목록을 만들지 못했습니다")
        assert "서고가 설정되지" not in body["error"]

    def test_success_shape(self, client, monkeypatch, tmp_path):
        import app.routers.llm_ocr as mod

        registry = OcrEngineRegistry()
        registry.register(DummyEngine())
        monkeypatch.setattr(mod, "get_library_path", lambda: tmp_path)
        monkeypatch.setattr(mod, "_get_ocr_pipeline", lambda: (None, registry))
        r = client.get("/api/ocr/engines")
        assert r.status_code == 200
        assert r.json()["default_engine"] == "dummy"
        assert [e["engine_id"] for e in r.json()["engines"]] == ["dummy"]
