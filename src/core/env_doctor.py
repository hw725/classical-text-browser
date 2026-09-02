"""환경 진단 — 어느 가상환경이 쓰이고, 그 안에서 OCR 엔진이 왜 안 되는지 한 번에 본다.

왜 필요한가:
    이 앱은 `.venv`(CPU 정본)와 `.venv-gpu`(GPU, 별도 생성)를 둘 다 가질 수 있고
    start_server가 GPU가 보이면 `.venv-gpu`를 고른다(D-078). 사용자가 `.venv`를 새로
    만들어도 옛 `.venv-gpu`가 남아 있으면 서버는 그쪽에서 뜬다. 그때 화면에는
    「PaddleOCR (사용 불가)」만 보이고, 원인(파이썬 3.13, DLL 실패, 미설치)은 콘솔 어딘가에
    있다. 이 모듈은 환경마다 파이썬을 직접 띄워 사실을 모으고, 무엇을 지우고 무엇을 남길지
    권고한다. 파일을 지우지는 않는다 — 되돌릴 수 없는 일은 사람이 한다.

구성:
    PROBE_SOURCE — 각 환경의 파이썬 안에서 실행되는 조사 스크립트(JSON 출력)
    probe_env()  — 환경 하나를 조사
    diagnose()   — 프로젝트 전체를 조사해 보고서 dict
    recommend()  — 보고서에서 권고 목록(순수 함수, 테스트 대상)
    format_report() — 사람이 읽는 텍스트
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

ENV_NAMES = (".venv", ".venv-gpu")

# 각 환경의 파이썬 안에서 돈다. 앱 코드를 import해 엔진 등록까지 실제로 해 본다.
PROBE_SOURCE = r"""
import json, sys, platform, importlib, os
out = {"python": sys.version.split()[0], "executable": sys.executable,
       "platform": platform.system(), "packages": {}, "errors": {}, "engines": []}
for name in ("paddle", "paddleocr", "onnxruntime", "torch", "cv2", "numpy"):
    try:
        m = importlib.import_module(name)
        out["packages"][name] = getattr(m, "__version__", "?")
    except Exception as e:  # noqa: BLE001
        out["errors"][name] = f"{type(e).__name__}: {e}"[:300]
try:
    import paddle  # noqa: F401
    out["paddle_cuda"] = bool(paddle.device.is_compiled_with_cuda())
except Exception:  # noqa: BLE001
    out["paddle_cuda"] = None
try:
    sys.path.insert(0, os.path.join(os.getcwd(), "src"))
    import logging; logging.disable(logging.CRITICAL)
    from ocr.registry import OcrEngineRegistry
    reg = OcrEngineRegistry(); reg.auto_register()
    for info in reg.list_engines():
        out["engines"].append({"engine_id": info.get("engine_id"),
                               "available": info.get("available"),
                               "reason": info.get("unavailable_reason")})
except Exception as e:  # noqa: BLE001
    out["errors"]["engines"] = f"{type(e).__name__}: {e}"[:300]
print(json.dumps(out, ensure_ascii=False))
"""


def env_python(root: Path, name: str) -> Optional[Path]:
    """가상환경의 파이썬 실행 파일. 없으면 None."""
    for rel in ("Scripts/python.exe", "bin/python", "bin/python3"):
        p = root / name / rel
        if p.exists():
            return p
    return None


def probe_env(root: Path, name: str, timeout: int = 180) -> dict:
    """환경 하나를 조사한다. 그 환경의 파이썬으로 PROBE_SOURCE를 실행해 JSON을 받는다."""
    py = env_python(root, name)
    result: dict = {
        "name": name,
        "exists": (root / name).exists(),
        "python_path": str(py) if py else None,
    }
    if py is None:
        return result
    try:
        proc = subprocess.run(
            [str(py), "-c", PROBE_SOURCE],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        line = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.startswith("{")), None)
        if line:
            result.update(json.loads(line))
        else:
            result["probe_error"] = (proc.stderr or proc.stdout)[-600:]
    except subprocess.TimeoutExpired:
        result["probe_error"] = f"{timeout}초 안에 끝나지 않았습니다 (paddle import가 멈춤?)"
    except Exception as e:  # noqa: BLE001
        result["probe_error"] = f"{type(e).__name__}: {e}"
    return result


def has_nvidia_gpu() -> bool:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return False
    try:
        return subprocess.run([exe, "-L"], capture_output=True, timeout=15).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def requires_python(root: Path) -> Optional[str]:
    try:
        for ln in (root / "pyproject.toml").read_text(encoding="utf-8").splitlines():
            if ln.strip().startswith("requires-python"):
                return ln.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return None


def diagnose(root: Path) -> dict:
    """프로젝트 전체 진단 보고서."""
    envs = [probe_env(root, n) for n in ENV_NAMES]
    gpu = has_nvidia_gpu()
    # start_server가 고를 환경 (D-078): GPU가 보이고 .venv-gpu가 있으면 그것, 아니면 .venv
    gpu_env = next((e for e in envs if e["name"] == ".venv-gpu"), None)
    chosen = ".venv-gpu" if (gpu and gpu_env and gpu_env.get("python_path")) else ".venv"
    return {
        "root": str(root),
        "host_python": sys.version.split()[0],
        "platform": platform.system(),
        "nvidia_gpu": gpu,
        "requires_python": requires_python(root),
        "start_server_picks": chosen,
        "envs": envs,
    }


def _py_tuple(v: Optional[str]) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in (v or "").split(".")[:2])
    except ValueError:
        return ()


def recommend(report: dict) -> list[dict]:
    """보고서에서 권고를 만든다. 각 항목: {"level": "fix"|"warn"|"ok", "text": str}.

    규칙(모두 사용자가 실제로 겪은 것):
      - start_server가 고른 환경에서 paddle import가 실패하거나 PaddleOCR이 사용 불가면 그 이유
      - .venv-gpu가 있는데 파이썬이 3.13 이상이거나 paddle이 죽으면: 지우거나 이름을 바꿔라
      - .venv-gpu가 있는데 GPU가 없으면: 쓰이지 않는다(정리 대상)
      - .venv가 없으면 install 스크립트
      - Windows + 3.13 + paddle 3.x(CPU)는 코드가 의도적으로 막는다 → 3.12로
    """
    recs: list[dict] = []
    envs = {e["name"]: e for e in report["envs"]}
    chosen = report["start_server_picks"]
    is_windows = report.get("platform") == "Windows"
    venv, gpu_env = envs.get(".venv"), envs.get(".venv-gpu")

    if not venv or not venv.get("python_path"):
        recs.append(
            {
                "level": "fix",
                "text": ".venv가 없습니다. install.bat(또는 install.sh)을 먼저 실행하세요.",
            }
        )

    for e in (venv, gpu_env):
        if not e or not e.get("python_path"):
            continue
        tag = f"{e['name']} (Python {e.get('python', '?')})"
        if e.get("probe_error"):
            recs.append({"level": "fix", "text": f"{tag}: 조사 실패 — {e['probe_error'][:200]}"})
            continue
        pyv = _py_tuple(e.get("python"))
        if pyv and pyv >= (3, 13):
            recs.append(
                {
                    "level": "fix",
                    "text": f"{tag}: paddlepaddle 휠은 3.12까지입니다"
                    f"(requires-python {report.get('requires_python')}). "
                    "이 환경은 PaddleOCR을 쓸 수 없습니다. 3.12로 다시 만드세요.",
                }
            )
        err = e.get("errors", {})
        if "paddle" in err:
            recs.append({"level": "fix", "text": f"{tag}: paddle import 실패 — {err['paddle']}"})
        elif "paddleocr" in err:
            recs.append(
                {"level": "fix", "text": f"{tag}: paddleocr import 실패 — {err['paddleocr']}"}
            )
        if "cv2" in err:
            recs.append(
                {
                    "level": "fix",
                    "text": f"{tag}: cv2 import 실패 — {err['cv2']} "
                    "(opencv 배포판 충돌: contrib판 하나만 남기세요)",
                }
            )
        for eng in e.get("engines", []):
            if eng.get("engine_id") == "paddleocr" and not eng.get("available"):
                recs.append(
                    {
                        "level": "fix",
                        "text": f"{tag}: PaddleOCR 사용 불가 — {eng.get('reason') or '이유 없음'}",
                    }
                )

    if gpu_env and gpu_env.get("python_path"):
        if not report.get("nvidia_gpu"):
            recs.append(
                {
                    "level": "warn",
                    "text": ".venv-gpu가 있지만 NVIDIA GPU가 보이지 않아 start_server는 "
                    ".venv를 씁니다. .venv-gpu는 쓰이지 않으니 지워도 됩니다(디스크 수 GB).",
                }
            )
        else:
            bad = (
                gpu_env.get("probe_error")
                or "paddle" in gpu_env.get("errors", {})
                or _py_tuple(gpu_env.get("python")) >= (3, 13)
            )
            if bad:
                recs.append(
                    {
                        "level": "fix",
                        "text": "start_server는 GPU를 보고 .venv-gpu를 고르는데 그 환경이 깨져 "
                        "있습니다. .venv-gpu 폴더를 지우거나 이름을 바꾸면 .venv(CPU)로 뜹니다. "
                        "GPU를 쓰려면 user-guide §7-A.6-2대로 3.12로 다시 만드세요.",
                    }
                )
    if chosen == ".venv" and venv and venv.get("python_path") and not venv.get("probe_error"):
        pe = next((x for x in venv.get("engines", []) if x.get("engine_id") == "paddleocr"), None)
        if pe and pe.get("available"):
            recs.append(
                {
                    "level": "ok",
                    "text": f".venv (Python {venv.get('python')}): PaddleOCR 사용 가능. "
                    "start_server가 이 환경을 씁니다.",
                }
            )
    if is_windows and any(
        _py_tuple(e.get("python")) >= (3, 13) for e in report["envs"] if e.get("python")
    ):
        recs.append(
            {
                "level": "warn",
                "text": "Windows + Python 3.13 + PaddlePaddle 3.x(CPU) 조합은 OneDNN 오류로 "
                "코드가 막습니다(D-059). 3.12를 쓰세요.",
            }
        )
    return recs


def format_report(report: dict, recs: list[dict]) -> str:
    lines = [
        "── 환경 진단 ──",
        f"폴더: {report['root']}",
        f"OS: {report['platform']} · NVIDIA GPU: {'있음' if report['nvidia_gpu'] else '없음'} · "
        f"requires-python: {report.get('requires_python')}",
        f"start_server가 고를 환경: {report['start_server_picks']}",
        "",
    ]
    for e in report["envs"]:
        if not e.get("python_path"):
            lines.append(f"[{e['name']}] 없음")
            continue
        lines.append(f"[{e['name']}] Python {e.get('python', '?')}  ({e['python_path']})")
        if e.get("probe_error"):
            lines.append(f"    조사 실패: {e['probe_error'][:300]}")
            continue
        pk = e.get("packages", {})
        lines.append(
            "    paddle "
            + pk.get("paddle", "—")
            + (" (CUDA)" if e.get("paddle_cuda") else "")
            + " · paddleocr "
            + pk.get("paddleocr", "—")
            + " · onnxruntime "
            + pk.get("onnxruntime", "—")
            + " · torch "
            + pk.get("torch", "—")
            + " · cv2 "
            + pk.get("cv2", "—")
        )
        for name, err in e.get("errors", {}).items():
            lines.append(f"    ✗ {name}: {err}")
        for eng in e.get("engines", []):
            mark = "✓" if eng.get("available") else "✗"
            reason = (
                f" — {eng['reason']}" if (not eng.get("available") and eng.get("reason")) else ""
            )
            lines.append(f"    {mark} {eng['engine_id']}{reason}")
        lines.append("")
    lines.append("── 권고 ──")
    if not recs:
        lines.append("문제를 찾지 못했습니다.")
    for r in recs:
        icon = {"fix": "▶ 고칠 것", "warn": "△ 참고", "ok": "✓"}[r["level"]]
        lines.append(f"{icon}: {r['text']}")
    return "\n".join(lines)
