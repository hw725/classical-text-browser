"""환경 진단 권고 규칙 (core.env_doctor.recommend) 테스트.

실제 가상환경을 띄우지 않고 조사 결과 dict만 넣어 권고를 고정한다.
사용자가 겪은 상황(2026-09-02): .venv를 3.12로 다시 만들었는데 PaddleOCR이 사용 불가.
doctor로 보니 .venv에 torch가 들어 있고 shm.dll이 WinError 127 → paddleocr(paddlex)이
torch를 import하다 죽었다. .venv-gpu는 cudnn_cnn64_9.dll이 같은 오류.
"""

from __future__ import annotations

from src.core.env_doctor import format_report, gpu_env_usable, recommend


def _env(name, python=None, errors=None, engines=None, probe_error=None, exists=True):
    e = {
        "name": name,
        "exists": exists,
        "python_path": f"{name}/Scripts/python.exe" if python else None,
    }
    if python:
        e.update(
            python=python,
            platform="Windows",
            packages={"paddle": "3.3.1", "paddleocr": "3.3.3"},
            errors=errors or {},
            engines=engines or [],
        )
    if probe_error:
        e["probe_error"] = probe_error
    return e


def _report(envs, gpu=True, platform="Windows"):
    gpu_env = next((e for e in envs if e["name"] == ".venv-gpu"), None)
    return {
        "root": "C:/ctb",
        "host_python": "3.12.4",
        "platform": platform,
        "nvidia_gpu": gpu,
        "requires_python": ">=3.10,<3.13",
        "start_server_picks": ".venv-gpu" if gpu_env_usable(gpu_env, gpu) else ".venv",
        "envs": envs,
    }


PADDLE_OK = [{"engine_id": "paddleocr", "available": True, "reason": None}]
PADDLE_BAD = [
    {
        "engine_id": "paddleocr",
        "available": False,
        "reason": "Windows + Python 3.13 + PaddlePaddle 3.x(CPU) …",
    }
]


def test_stale_gpu_env_with_py313_is_flagged():
    envs = [
        _env(".venv", "3.12.4", engines=PADDLE_OK),
        _env(".venv-gpu", "3.13.1", engines=PADDLE_BAD),
    ]
    recs = recommend(_report(envs, gpu=True))
    texts = " ".join(r["text"] for r in recs if r["level"] == "fix")
    assert "3.12로 다시 만드세요" in texts
    assert "PaddleOCR 사용 불가 — Windows + Python 3.13" in texts


def test_gpu_env_without_gpu_is_unused():
    envs = [
        _env(".venv", "3.12.4", engines=PADDLE_OK),
        _env(".venv-gpu", "3.12.4", engines=PADDLE_OK),
    ]
    recs = recommend(_report(envs, gpu=False))
    assert any("쓰이지 않으니 지워도" in r["text"] for r in recs)
    assert any(r["level"] == "ok" and "PaddleOCR 사용 가능" in r["text"] for r in recs)


def test_missing_venv_and_paddle_import_error():
    envs = [
        _env(".venv"),
        _env(".venv-gpu", "3.12.4", errors={"paddle": "OSError: [WinError 126]"}),
    ]
    report = _report(envs, gpu=True)
    assert report["start_server_picks"] == ".venv"  # paddle이 안 뜨는 .venv-gpu는 고르지 않는다
    texts = [r["text"] for r in recommend(report)]
    assert any("install.bat" in t for t in texts)
    assert any("paddle import 실패 — OSError" in t for t in texts)
    assert any("start_server는 .venv(CPU)로 뜁니다" in t for t in texts)


def test_probe_failure_is_reported_not_crashed():
    envs = [_env(".venv", "3.12.4", probe_error="180초 안에 끝나지 않았습니다")]
    recs = recommend(_report(envs, gpu=False))
    assert any("조사 실패" in r["text"] for r in recs)
    out = format_report(_report(envs, gpu=False), recs)
    assert "조사 실패" in out and "── 권고 ──" in out


def test_broken_torch_in_cpu_env_points_to_uv_sync():
    """.venv에 torch가 들어가 있고 shm.dll이 WinError 127 → paddleocr까지 실패."""
    e = _env(
        ".venv",
        "3.12.13",
        errors={
            "torch": "OSError: [WinError 127] … torch\\lib\\shm.dll",
            "paddleocr": "OSError: [WinError 127] … torch\\lib\\shm.dll",
        },
    )
    e["packages"]["torch"] = "2.7.1"
    recs = recommend(_report([e], gpu=False))
    fixes = [r["text"] for r in recs if r["level"] == "fix"]
    assert any("깨진 torch 때문에 paddleocr이 못 뜹니다" in t and "uv sync" in t for t in fixes)
    assert not any("paddle import 실패" in t for t in fixes)
    assert any(".venv에 torch가 들어 있습니다" in r["text"] for r in recs)


def test_broken_torch_in_gpu_env_offers_uninstall():
    venv = _env(".venv", "3.12.13", engines=PADDLE_OK)
    gpu = _env(
        ".venv-gpu",
        "3.12.13",
        errors={
            "torch": "OSError: [WinError 127] … cudnn_cnn64_9.dll",
            "paddleocr": "OSError: [WinError 127] … cudnn_cnn64_9.dll",
        },
    )
    gpu["paddle_cuda"] = True
    report = _report([venv, gpu], gpu=True)
    # paddle은 뜨므로 start_server는 .venv-gpu를 고른다(paddle GPU in-process)
    assert report["start_server_picks"] == ".venv-gpu"
    texts = [r["text"] for r in recommend(report)]
    assert any("pip uninstall -y torch torchvision" in t for t in texts)


def test_cudnn_conflict_between_torch_and_paddle():
    """실측: .venv-gpu에서 torch 2.6+cu124가 먼저 뜨면 paddle의 cudnn_cnn64_9.dll이 WinError 127.
    각각 혼자서는 뜬다 → 충돌 판정, 하나만 고르라는 권고."""
    gpu = _env(
        ".venv-gpu",
        "3.12.13",
        errors={"paddle": "OSError: [WinError 127] … nvidia\\cudnn\\bin\\cudnn_cnn64_9.dll"},
    )
    gpu["packages"]["torch"] = "2.6.0+cu124"
    gpu["alone"] = {
        "paddle": {"ok": True, "version": "3.3.1"},
        "torch": {"ok": True, "version": "2.6.0+cu124"},
    }
    venv = _env(".venv", "3.12.13", engines=PADDLE_OK)
    texts = [r["text"] for r in recommend(_report([venv, gpu], gpu=True))]
    assert any("cuDNN DLL 판이 다름" in t and "자식 프로세스" in t for t in texts)
    assert not any("paddle import 실패" in t for t in texts)


def test_worker_ping_failure_is_fix_even_if_engine_probe_passes():
    """실측 2026-09-03: .venv에 GPU torch가 들어 있어도 엔진 조사(torch 먼저)는 paddleocr ✓.
    그러나 서버의 워커(paddle 먼저)는 shm.dll WinError 127로 죽어 PaddleOCR이 사용 불가였다.
    워커 ping이 실패하면 «고칠 것»으로, uv sync를 가리켜야 한다."""
    venv = _env(".venv", "3.12.13", engines=PADDLE_OK)
    venv["packages"]["torch"] = "2.6.0+cu124"
    venv["worker"] = {
        "available": False,
        "reason": r"PaddleOCR을 불러오는 중 오류가 났습니다 "
        r"(OSError: [WinError 127] … torch\lib\shm.dll)",
    }
    gpu = _env(
        ".venv-gpu", "3.12.13", errors={"paddle": "OSError: [WinError 127] … cudnn_cnn64_9.dll"}
    )
    gpu["packages"]["torch"] = "2.6.0+cu124"
    gpu["alone"] = {"paddle": {"ok": True}, "torch": {"ok": True}}
    report = _report([venv, gpu], gpu=True)
    recs = recommend(report)
    fixes = [r["text"] for r in recs if r["level"] == "fix"]
    assert any("워커(paddle → paddleocr 순서)가 죽습니다" in t and "uv sync" in t for t in fixes)
    assert not any(r["level"] == "ok" for r in recs)
    out = format_report(report, recs)
    assert "✗ paddle 워커 ping" in out


def test_worker_ping_ok_is_reported():
    venv = _env(".venv", "3.12.13", engines=PADDLE_OK)
    venv["worker"] = {"available": True, "reason": None, "paddle": "3.3.1"}
    report = _report([venv], gpu=False)
    recs = recommend(report)
    assert any(r["level"] == "ok" for r in recs)
    assert "✓ paddle 워커 ping" in format_report(report, recs)
