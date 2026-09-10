"""PaddleOCR 워커 모드 (D-091) 테스트.

무엇을 고정하는가:
  - from_dict가 to_dict의 역이다
  - 워커 프로토콜: ping·recognize·quit·알 수 없는 op, 예외는 {"ok": false}
  - 엔진이 워커 모드일 때 실제 자식 프로세스(같은 파이썬, 강제 플래그)로 ping이 오간다
  - CTB_PADDLE_PYTHON이 같은 파이썬을 가리키면 in-process
"""

from __future__ import annotations

import base64
import sys

import pytest

from src.ocr.base import OcrBlockResult, OcrCharResult, OcrLineResult
from src.ocr.paddle_worker import handle_request


def test_from_dict_roundtrip():
    chars = [OcrCharResult("王", [0, 0, 10, 10], 0.9), OcrCharResult("戎", [0, 10, 10, 20], 0.8)]
    r = OcrBlockResult(lines=[OcrLineResult(text="王戎", bbox=[0, 0, 10, 20], characters=chars)])
    back = OcrBlockResult.from_dict(
        r.to_dict(), engine_id="paddleocr", language="classical_chinese"
    )
    assert back.to_dict() == r.to_dict()
    assert back.engine_id == "paddleocr" and abs(back.avg_confidence - 0.85) < 1e-9


class _FakeEngine:
    _unavailable_reason = "가짜 이유"

    def __init__(self, available=True, raise_on_recognize=False):
        self._available = available
        self._raise = raise_on_recognize
        self.calls = []

    def is_available(self):
        return self._available

    def recognize(
        self, image_bytes, writing_direction="vertical_rtl", language="classical_chinese", **kw
    ):
        self.calls.append((len(image_bytes), writing_direction, language, kw))
        if self._raise:
            raise RuntimeError("모델 없음")
        line = OcrLineResult(text="甲", characters=[OcrCharResult("甲", None, 0.5)])
        return OcrBlockResult(lines=[line])


def test_protocol_ping_recognize_quit_unknown():
    eng = _FakeEngine()
    ping = handle_request(eng, {"op": "ping"})
    assert ping["ok"] and ping["available"] is True and ping["reason"] is None
    req = {
        "op": "recognize",
        "image_b64": base64.b64encode(b"PNGDATA").decode(),
        "writing_direction": "horizontal_ltr",
        "language": "korean",
        "kwargs": {"paddle_lang": "korean"},
    }
    resp = handle_request(eng, req)
    assert resp["ok"] and resp["result"]["lines"][0]["text"] == "甲"
    assert eng.calls == [(7, "horizontal_ltr", "korean", {"paddle_lang": "korean"})]
    assert handle_request(eng, {"op": "quit"})["bye"] is True
    assert handle_request(eng, {"op": "nope"})["ok"] is False


def test_protocol_errors_are_json_not_exceptions():
    req = {"op": "recognize", "image_b64": "QUJD"}
    resp = handle_request(_FakeEngine(raise_on_recognize=True), req)
    assert resp["ok"] is False and "RuntimeError: 모델 없음" in resp["error"] and "trace" in resp
    ping = handle_request(_FakeEngine(available=False), {"op": "ping"})
    assert ping["available"] is False and ping["reason"] == "가짜 이유"


def test_engine_worker_mode_spawns_child(monkeypatch):
    """같은 파이썬을 워커로 강제해 실제 프로세스 왕복을 확인한다."""
    pytest.importorskip("paddle")
    monkeypatch.setenv("CTB_PADDLE_PYTHON", sys.executable)
    monkeypatch.setenv("CTB_PADDLE_FORCE_WORKER", "1")
    from src.ocr.paddleocr_engine import PaddleOcrEngine

    eng = PaddleOcrEngine()
    assert eng._worker_python == sys.executable
    try:
        ok = eng.is_available()
        info = eng.get_info()
        assert info["worker_python"] == sys.executable
        assert ok is True and "별도 프로세스" in info["model_source"]
        assert eng._worker_info["executable"]
    finally:
        if eng._worker is not None:
            eng._worker.kill()


def test_gpu_worker_is_preferred_and_falls_back_to_cpu(monkeypatch):
    """GPU판 paddle이 있으면 워커를 지금 파이썬 + torch 차단으로 먼저 띄우고, 안 뜨면 CPU 워커로.

    D-091 덧붙임.
    """
    from src.ocr import paddleocr_engine as pe

    monkeypatch.setenv("CTB_PADDLE_PYTHON", "C:/other/.venv/Scripts/python.exe")
    monkeypatch.delenv("CTB_PADDLE_FORCE_WORKER", raising=False)
    monkeypatch.delenv("CTB_PADDLE_GPU_WORKER", raising=False)
    monkeypatch.setattr(pe, "_gpu_paddle_installed", lambda: True)
    eng = pe.PaddleOcrEngine()
    assert eng._worker_python == sys.executable and eng._worker_block_torch is True
    assert eng._worker_fallback == "C:/other/.venv/Scripts/python.exe"

    pings = iter(
        [
            {"ok": False, "available": False, "reason": "cudnn 충돌"},
            {"ok": True, "available": True, "gpu": False, "python": "3.12"},
        ]
    )
    monkeypatch.setattr(eng, "_ping_once", lambda: next(pings))
    info = eng._worker_ping()
    assert info["available"] is True and info["gpu_fallback_reason"] == "cudnn 충돌"
    assert eng._worker_python == "C:/other/.venv/Scripts/python.exe" and not eng._worker_block_torch
    assert "GPU 워커 실패로 CPU" in eng.get_info()["model_source"]

    # 끄는 스위치와 GPU판이 없는 환경은 예전 그대로(CPU 워커)
    monkeypatch.setenv("CTB_PADDLE_GPU_WORKER", "0")
    assert pe.PaddleOcrEngine()._worker_python == "C:/other/.venv/Scripts/python.exe"
    monkeypatch.delenv("CTB_PADDLE_GPU_WORKER")
    monkeypatch.setattr(pe, "_gpu_paddle_installed", lambda: False)
    assert pe.PaddleOcrEngine()._worker_block_torch is False


def test_worker_blocks_torch_when_asked(monkeypatch):
    """CTB_PADDLE_BLOCK_TORCH=1이면 워커 모듈이 뜨는 순간 torch import가 막힌다."""
    import subprocess
    from pathlib import Path

    code = (
        "import sys, os; os.environ['CTB_PADDLE_BLOCK_TORCH']='1';"
        "import ocr.paddle_worker;"
        "\ntry:\n import torch\n print('LOADED')\nexcept ImportError:\n print('BLOCKED')"
    )
    src = str(Path(__file__).resolve().parents[1] / "src")
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=src, capture_output=True, text=True, timeout=120
    )
    assert "BLOCKED" in out.stdout, out.stderr[-500:]


def test_engine_without_env_is_in_process(monkeypatch):
    monkeypatch.delenv("CTB_PADDLE_PYTHON", raising=False)
    monkeypatch.delenv("CTB_PADDLE_FORCE_WORKER", raising=False)
    from src.ocr.paddleocr_engine import PaddleOcrEngine

    assert PaddleOcrEngine()._worker_python is None
    monkeypatch.setenv("CTB_PADDLE_PYTHON", sys.executable)  # 같은 파이썬 → in-process
    assert PaddleOcrEngine()._worker_python is None
