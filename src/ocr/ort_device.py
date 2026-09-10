"""onnxruntime 엔진(みんなで翻刻·NDL古典籍 Lite·NDLOCR)이 쓸 장치를 한 곳에서 정한다.

왜 있는가:
    GPU 환경(.venv-gpu)에 onnxruntime **GPU판**을 두면 이 셋도 GPU로 돈다(2026-09-10 실측 —
    みんなで翻刻 한 쪽 22초 → 6초). 그런데 두 가지가 있어야 한다.
    1. CUDAExecutionProvider가 실제로 보이는가(CPU판이면 없다).
    2. torch보다 onnxruntime을 **먼저** 쓰는 프로세스에서는 CUDA DLL을 미리 올려야 한다
       (`preload_dlls`). 안 그러면 첫 세션이 조용히 CPU로 떨어진다(실측: RTMDet providers가
       CPU만). torch가 먼저 떴으면 그 DLL을 같이 쓰므로 괜찮다.
    엔진마다 이 판단을 흩어 두면 하나만 CPU로 남아도 모른다 — 그래서 한 함수다.

끄는 스위치: CTB_ORT_DEVICE=cpu (강제 CPU) / cuda (강제). 없으면 «되면 cuda».
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_DEVICE: str | None = None
_PRELOADED = False


def ort_device() -> str:
    """이 프로세스의 onnxruntime 장치 — "cuda" 또는 "cpu". 한 번 정하고 기억한다."""
    global _DEVICE, _PRELOADED
    if _DEVICE is not None:
        return _DEVICE
    forced = (os.environ.get("CTB_ORT_DEVICE") or "").strip().lower()
    if forced in ("cpu", "cuda"):
        _DEVICE = forced
        if forced == "cuda":
            _preload()
        return _DEVICE
    try:
        import onnxruntime

        if "CUDAExecutionProvider" in onnxruntime.get_available_providers():
            _preload()
            _DEVICE = "cuda"
        else:
            _DEVICE = "cpu"
    except Exception as e:  # noqa: BLE001 — onnxruntime이 없으면 엔진 쪽이 따로 알린다
        logger.debug("onnxruntime 장치 판정 실패 → cpu: %s", e)
        _DEVICE = "cpu"
    return _DEVICE


def _preload() -> None:
    """CUDA·cuDNN DLL을 미리 올린다(onnxruntime 1.21+). 실패해도 엔진은 CPU로 돈다."""
    global _PRELOADED
    if _PRELOADED:
        return
    _PRELOADED = True
    try:
        import onnxruntime

        if hasattr(onnxruntime, "preload_dlls"):
            onnxruntime.preload_dlls()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "onnxruntime preload_dlls 실패 — 이 프로세스의 ONNX 엔진은 CPU로 돌 수 있다: %s", e
        )


def reset_for_tests() -> None:
    """시험용 — 기억한 판정을 지운다."""
    global _DEVICE, _PRELOADED
    _DEVICE = None
    _PRELOADED = False
