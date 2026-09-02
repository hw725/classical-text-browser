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
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

ENV_NAMES = (".venv", ".venv-gpu")

# 각 환경의 파이썬 안에서 돈다. 앱 코드를 import해 엔진 등록까지 실제로 해 본다.
PROBE_PACKAGES = r"""
import json, sys, platform, importlib
out = {"python": sys.version.split()[0], "executable": sys.executable,
       "platform": platform.system(), "packages": {}, "errors": {}}
for name in ("numpy", "cv2", "onnxruntime", "torch", "paddle", "paddleocr"):
    try:
        m = importlib.import_module(name)
        out["packages"][name] = getattr(m, "__version__", "?")
    except Exception as e:  # noqa: BLE001
        out["errors"][name] = f"{type(e).__name__}: {e}"[:400]
try:
    import paddle  # noqa: F401
    out["paddle_cuda"] = bool(paddle.device.is_compiled_with_cuda())
except Exception:  # noqa: BLE001
    out["paddle_cuda"] = None
print(json.dumps(out, ensure_ascii=False))
"""

# 한 패키지만 새 프로세스에서 import한다. torch와 paddle이 둘 다 있을 때 «함께 뜨지 않는»
# 것(cuDNN DLL 충돌)과 «혼자서도 안 뜨는» 것을 가르기 위해서다.
PROBE_ALONE = r"""
import json, sys, importlib
name = sys.argv[1] if len(sys.argv) > 1 else "paddle"
try:
    m = importlib.import_module(name)
    print(json.dumps({"ok": True, "version": getattr(m, "__version__", "?")}))
except Exception as e:  # noqa: BLE001
    print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"[:400]}))
"""

# 엔진 등록은 별도 프로세스에서 한다. 같은 프로세스에서 paddleocr을 두 번 import하면
# paddlex가 «PDX has already been initialized»를 던져 진짜 원인이 가려진다.
PROBE_ENGINES = r"""
import json, sys, os
out = {"engines": [], "errors": {}}
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


def _run_probe(py: Path, root: Path, source: str, timeout: int) -> dict:
    try:
        proc = subprocess.run(
            [str(py), "-c", source],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        line = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.startswith("{")), None)
        if line:
            return json.loads(line)
        return {"probe_error": (proc.stderr or proc.stdout)[-600:]}
    except subprocess.TimeoutExpired:
        return {"probe_error": f"{timeout}초 안에 끝나지 않았습니다 (paddle import가 멈춤?)"}
    except Exception as e:  # noqa: BLE001
        return {"probe_error": f"{type(e).__name__}: {e}"}


def _run_probe_alone(py: Path, root: Path, module: str, timeout: int) -> dict:
    try:
        proc = subprocess.run(
            [str(py), "-c", PROBE_ALONE, module],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        line = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.startswith("{")), None)
        return json.loads(line) if line else {"ok": False, "error": (proc.stderr or "")[-300:]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _run_worker_ping(py: Path, root: Path, timeout: int) -> dict:
    """PaddleOCR 워커(D-091)를 실제로 띄워 ping 한다 — «워커 순서»로 import되는지 본다.

    왜 엔진 조사와 별도인가: 엔진 조사(PROBE_ENGINES)는 registry 등록 순서대로 NDL古典籍
    Full(torch)을 먼저 import하고 paddle을 나중에 읽는다. 그 순서는 .venv에 GPU torch가
    잘못 들어 있어도 산다(torch → paddle 순서는 뜬다). 그런데 워커는 paddle을 먼저 읽고
    paddleocr(paddlex)이 torch를 끌어오는 순서라 같은 환경에서 죽는다(shm.dll WinError 127).
    2026-09-03 실측: doctor는 .venv paddleocr ✓라고 했지만 서버에서는 PaddleOCR 사용 불가였다.
    등록 순서로 검사하면 이 실패를 못 보므로 워커 자체를 띄워 본다.
    """
    src_dir = root / "src"
    env = dict(os.environ)
    env.pop("CTB_PADDLE_PYTHON", None)
    env.pop("CTB_PADDLE_FORCE_WORKER", None)
    env["PYTHONPATH"] = str(src_dir) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            [str(py), "-m", "ocr.paddle_worker"],
            input='{"op": "ping"}' + chr(10) + '{"op": "quit"}' + chr(10),
            cwd=str(src_dir),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("{")), None)
        if not line:
            tail = (proc.stderr or "")[-300:]
            return {"available": False, "reason": "워커가 응답하지 않음: " + tail}
        resp = json.loads(line)
        return {
            "available": bool(resp.get("ok") and resp.get("available")),
            "reason": resp.get("reason") or resp.get("error"),
            "paddle": resp.get("paddle"),
        }
    except subprocess.TimeoutExpired:
        return {"available": False, "reason": f"{timeout}초 안에 끝나지 않았습니다"}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": f"{type(e).__name__}: {e}"}


def cudnn_conflict(e: dict) -> bool:
    """torch와 paddle이 각각 혼자서는 뜨는데 한 프로세스에서는 둘 중 하나가 죽는가.

    Windows에서 둘은 cuDNN 9 DLL을 따로 들고 온다(torch/lib, nvidia/cudnn/bin). 판이 다르면
    먼저 뜬 쪽의 DLL이 이름으로 재사용되어 뒤에 뜨는 쪽이 WinError 127로 죽는다.
    앱은 엔진 등록 때 NDL古典籍 Full(torch) → PaddleOCR(paddle) 순으로 import하므로
    이 경우 화면에서는 PaddleOCR이 사용 불가로 보인다. 실측 2026-09-02.
    """
    alone = e.get("alone") or {}
    if not alone:
        return False
    return all(alone.get(n, {}).get("ok") for n in ("torch", "paddle"))


def probe_env(root: Path, name: str, timeout: int = 180) -> dict:
    """환경 하나를 조사한다. 패키지 조사와 엔진 조사를 각각 새 프로세스로 돌려 합친다."""
    py = env_python(root, name)
    result: dict = {
        "name": name,
        "exists": (root / name).exists(),
        "python_path": str(py) if py else None,
    }
    if py is None:
        return result
    pk = _run_probe(py, root, PROBE_PACKAGES, timeout)
    if "probe_error" in pk:
        result["probe_error"] = pk["probe_error"]
        return result
    result.update(pk)
    # torch·paddle이 둘 다 있는데 하나가 죽었다 → 각각 혼자서는 뜨는지 본다 (cuDNN 충돌 판정)
    both = {"torch", "paddle"} <= (set(pk.get("packages", {})) | set(pk.get("errors", {})))
    if both and ({"torch", "paddle"} & set(pk.get("errors", {}))):
        alone = {}
        for name in ("paddle", "torch"):
            alone[name] = _run_probe_alone(py, root, name, timeout)
        result["alone"] = alone
    # .venv는 GPU 환경에서 PaddleOCR 워커로 쓰인다(D-091). 워커는 paddle을 먼저 읽으므로
    # 등록 순서(torch 먼저)의 엔진 조사와 다르게 죽을 수 있다 — 워커를 직접 띄워 본다.
    # 주의: 위 루프가 `name`을 덮어쓴다 — result["name"]으로 판정한다.
    if result["name"] == ".venv" and "paddle" in pk.get("packages", {}):
        result["worker"] = _run_worker_ping(py, root, timeout)
    en = _run_probe(py, root, PROBE_ENGINES, timeout)
    result["engines"] = en.get("engines", [])
    if en.get("errors"):
        result.setdefault("errors", {}).update(en["errors"])
    if "probe_error" in en:
        result["engine_probe_error"] = en["probe_error"]
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
    chosen = ".venv-gpu" if gpu_env_usable(gpu_env, gpu) else ".venv"
    return {
        "root": str(root),
        "host_python": sys.version.split()[0],
        "platform": platform.system(),
        "nvidia_gpu": gpu,
        "requires_python": requires_python(root),
        "start_server_picks": chosen,
        "envs": envs,
    }


def gpu_env_usable(gpu_env: Optional[dict], gpu: bool) -> bool:
    """start_server.bat의 선택 규칙.

    GPU가 보이고 .venv-gpu에서 torch(TrOCR)나 paddle 중 하나라도 import되면 그것(D-091),
    아니면 .venv.
    """
    if not (gpu and gpu_env and gpu_env.get("python_path")) or gpu_env.get("probe_error"):
        return False
    pk, err = gpu_env.get("packages", {}), gpu_env.get("errors", {})
    return any(name in pk and name not in err for name in ("torch", "paddle"))


def _torch_breaks_paddleocr(e: dict) -> bool:
    """paddleocr import 실패 원인이 torch DLL인가.

    paddleocr 3.x(paddlex)는 torch가 **설치돼 있으면** import한다(paddlex/utils/env.py).
    그래서 깨진 torch가 있으면 paddleocr까지 못 뜬다 — 실측 2026-09-02: .venv에 torch가
    들어 있고 shm.dll이 WinError 127, .venv-gpu는 cudnn_cnn64_9.dll이 WinError 127.
    """
    err = e.get("errors", {})
    msg = (err.get("paddleocr") or "") + " " + (err.get("torch") or "")
    # torch import 자체가 실패했거나, paddleocr 오류 문구에 torch 경로가 보이면 torch가 원인
    return "paddleocr" in err and ("torch" in err or "torch" in msg.lower())


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
        if cudnn_conflict(e):
            recs.append(
                {
                    "level": "fix",
                    "text": f"{tag}: torch와 paddle이 각각 혼자서는 뜨지만 한 프로세스에서는 둘 중 "
                    "하나가 죽습니다(cuDNN DLL 판이 다름). start_server.bat이 이 환경을 고르면 "
                    "PaddleOCR은 .venv(CPU)의 파이썬을 자식 프로세스로 띄워 돌립니다(D-091) — "
                    ".venv가 정상이면 그대로 두면 됩니다. GPU로 PaddleOCR을 돌리려면 torch를 "
                    "빼야 합니다: `.venv-gpu\\Scripts\\python -m pip uninstall -y torch "
                    "torchvision`.",
                }
            )
            continue
        if _torch_breaks_paddleocr(e):
            cause = (err.get("torch") or err.get("paddleocr") or "")[:120]
            if e["name"] == ".venv":
                recs.append(
                    {
                        "level": "fix",
                        "text": f"{tag}: 깨진 torch 때문에 paddleocr이 못 뜹니다 ({cause}). "
                        "torch는 CPU 번들에 없는 패키지입니다 — 설치 폴더에서 `uv sync`를 한 번 "
                        "돌리면 torch가 빠지고 paddleocr이 살아납니다.",
                    }
                )
            else:
                recs.append(
                    {
                        "level": "fix",
                        "text": f"{tag}: 깨진 torch(cuDNN DLL) 때문에 paddleocr이 못 뜹니다. "
                        "PaddleOCR만 GPU로 쓸 거면 `.venv-gpu\\Scripts\\python -m pip uninstall -y "
                        "torch torchvision`. NDL古典籍 TrOCR도 쓸 거면 user-guide §7-A.6-2의 "
                        "torch 핀(<2.8, cu124)으로 다시 설치하세요.",
                    }
                )
            continue
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

    worker = (venv or {}).get("worker")
    worker_dead = bool(worker) and not worker.get("available")
    if worker_dead:
        why = (worker.get("reason") or "이유 없음")[:160]
        if "torch" in venv.get("packages", {}):
            recs.append(
                {
                    "level": "fix",
                    "text": ".venv: PaddleOCR 워커(paddle → paddleocr 순서)가 죽습니다 — "
                    f"{why}. .venv에 든 GPU torch가 원인입니다(paddleocr이 torch를 끌어옴). "
                    "엔진 목록 조사는 torch를 먼저 읽어 통과하지만 서버의 워커는 이 순서라 "
                    "PaddleOCR이 사용 불가로 뜹니다. 설치 폴더에서 `uv sync`를 돌려 torch를 "
                    "빼세요.",
                }
            )
        else:
            recs.append({"level": "fix", "text": f".venv: PaddleOCR 워커 ping 실패 — {why}"})
    if venv and venv.get("python_path") and "torch" in venv.get("packages", {}):
        recs.append(
            {
                "level": "warn",
                "text": ".venv에 torch가 들어 있습니다. CPU 번들에는 없는 패키지라 `uv sync`가 "
                "빼 버립니다. GPU 스택은 .venv-gpu에만 두세요(D-078).",
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
            bad = (not gpu_env_usable(gpu_env, True)) or _py_tuple(gpu_env.get("python")) >= (3, 13)
            if bad:
                recs.append(
                    {
                        "level": "fix",
                        "text": "GPU가 보이지만 .venv-gpu에서 paddle·paddleocr이 뜨지 않아 "
                        "start_server는 .venv(CPU)로 뜁니다. GPU로 OCR하려면 위 항목대로 "
                        ".venv-gpu를 고치세요. 안 쓸 거면 지워도 됩니다.",
                    }
                )
    if chosen == ".venv" and venv and venv.get("python_path") and not venv.get("probe_error"):
        pe = next((x for x in venv.get("engines", []) if x.get("engine_id") == "paddleocr"), None)
        if pe and pe.get("available") and not worker_dead:
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
        for name, res in (e.get("alone") or {}).items():
            state = (
                "혼자서는 뜸" if res.get("ok") else f"혼자서도 실패: {res.get('error', '')[:120]}"
            )
            lines.append(f"    ({name} 단독 import: {state})")
        for eng in e.get("engines", []):
            mark = "✓" if eng.get("available") else "✗"
            reason = (
                f" — {eng['reason']}" if (not eng.get("available") and eng.get("reason")) else ""
            )
            lines.append(f"    {mark} {eng['engine_id']}{reason}")
        w = e.get("worker")
        if w:
            if w.get("available"):
                lines.append(
                    f"    ✓ paddle 워커 ping (paddle→paddleocr 순서, paddle {w.get('paddle')})"
                )
            else:
                lines.append(f"    ✗ paddle 워커 ping — {(w.get('reason') or '')[:200]}")
        lines.append("")
    lines.append("── 권고 ──")
    if not recs:
        lines.append("문제를 찾지 못했습니다.")
    for r in recs:
        icon = {"fix": "▶ 고칠 것", "warn": "△ 참고", "ok": "✓"}[r["level"]]
        lines.append(f"{icon}: {r['text']}")
    return "\n".join(lines)
