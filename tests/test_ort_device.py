"""onnxruntime 장치 판정(ort_device) — GPU판이면 cuda + DLL 미리 올림, 아니면 cpu, 스위치로 강제."""

import sys
import types

import pytest

from src.ocr import ort_device as od


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    od.reset_for_tests()
    monkeypatch.delenv("CTB_ORT_DEVICE", raising=False)
    yield
    od.reset_for_tests()


def _fake_ort(providers, with_preload=True):
    m = types.ModuleType("onnxruntime")
    m.get_available_providers = lambda: providers
    m.calls = []
    if with_preload:
        m.preload_dlls = lambda: m.calls.append("preload")
    return m


def test_cuda_provider_means_cuda_and_preloads(monkeypatch):
    fake = _fake_ort(["CUDAExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setitem(sys.modules, "onnxruntime", fake)
    assert od.ort_device() == "cuda" and fake.calls == ["preload"]
    assert od.ort_device() == "cuda" and fake.calls == ["preload"]  # 두 번 부르지 않는다


def test_cpu_build_means_cpu(monkeypatch):
    fake = _fake_ort(["CPUExecutionProvider"])
    monkeypatch.setitem(sys.modules, "onnxruntime", fake)
    assert od.ort_device() == "cpu" and fake.calls == []


def test_env_switch_wins(monkeypatch):
    fake = _fake_ort(["CUDAExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setitem(sys.modules, "onnxruntime", fake)
    monkeypatch.setenv("CTB_ORT_DEVICE", "cpu")
    assert od.ort_device() == "cpu"


def test_missing_onnxruntime_is_cpu(monkeypatch):
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    assert od.ort_device() == "cpu"
