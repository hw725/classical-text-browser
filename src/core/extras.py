"""엔진 추가 설치 — «uv sync --extra»를 서버가 대신 돌린다 (D-106).

왜 있는가:
    이 앱의 사용자는 터미널을 쓰지 않는다. 고서 엔진을 넣으려고 `uv sync --extra classical`을
    치게 하면 거기서 끝난다(2026-09-05 지적). 업데이트(D-103)가 이미 uv sync를 돌리므로
    같은 길로 extras도 넣는다 — 화면의 「설치」 단추 하나.

함정 — uv sync는 환경을 lock과 «정확히» 맞춘다:
    `--extra`로 적지 않은 extras는 **지운다.** 고서 엔진을 넣으려고 `uv sync --extra classical`만
    돌리면 전에 넣은 일본어 엔진이 사라진다. 그래서 고른 extras를 `.ctb-extras.json`(앱 루트,
    gitignore)에 기록하고, 업데이트와 추가 설치가 언제나 **기록 전부**를 넘긴다. 기록이 없으면
    지금 깔린 것을 import로 짚어 처음 기록을 만든다.

GPU판(classical-gpu)은 여기서 다루지 않는다 — .venv가 아니라 별도 환경 .venv-gpu에 깐다(D-078).
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from core.document import write_json_atomic

# 화면에 보여 주는 extras. 이름은 pyproject.toml [project.optional-dependencies]와 같아야 한다.
# probe: 이 모듈이 import되면 «깔려 있다»고 본다. japanese·classical은 의존이 같아서
# 하나를 깔면 둘 다 import된다 — 모델 파일은 엔진이 처음 돌 때 따로 받는다.
KNOWN_EXTRAS: dict[str, dict] = {
    "classical": {
        "label": "고서 엔진 (NDL古典籍OCR-Lite)",
        "for": "한문 고서(古典籍) 스캔을 읽습니다. CPU로 돕니다.",
        "size": "약 170MB",
        "probe": "onnxruntime",
    },
    "japanese": {
        "label": "일본어 엔진 (NDLOCR-Lite)",
        "for": "근현대 일본어 자료를 읽습니다. 한글은 읽지 못합니다.",
        "size": "약 170MB",
        "probe": "onnxruntime",
    },
}

# 이 환경(.venv)에 절대 넣지 않는 것 — torch 계열은 .venv-gpu에(D-078).
BLOCKED_EXTRAS = {"classical-gpu", "ndlkotenocr-full"}

_RECORD_NAME = ".ctb-extras.json"


def app_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _record_path() -> Path:
    return app_root() / _RECORD_NAME


def defined_extras() -> set[str]:
    """pyproject.toml이 정의한 extras 이름 전부."""
    import tomllib

    try:
        with open(app_root() / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    return set(data.get("project", {}).get("optional-dependencies", {}).keys())


def _venv_python() -> str:
    """uv sync가 갱신하는 환경(.venv)의 파이썬. GPU PC는 서버가 .venv-gpu로 뜨므로 sys.executable로
    짚으면 «깔림» 판정과 설치 대상이 어긋난다(리뷰 지적)."""

    for rel in ("Scripts/python.exe", "bin/python"):
        cand = app_root() / ".venv" / rel
        if cand.exists():
            return str(cand)
    return sys.executable


def _probe(module: str) -> bool:
    """이 프로세스가 아니라 **.venv의 파이썬**으로 import해 본다.

    왜: 서버가 도는 동안 새로 깔린 꾸러미는 자식 프로세스가 가장 확실하게 본다. 또 여기서
    무거운 모듈을 import하면 서버 프로세스에 그 DLL이 붙어 버린다(cuDNN 충돌, D-091).
    """
    try:
        p = subprocess.run(
            [_venv_python(), "-c", f"import {module}"],
            capture_output=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return p.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


_probe_cache: dict[str, tuple[float, bool]] = {}
_PROBE_TTL = 30.0


def installed_extras(force: bool = False) -> dict[str, bool]:
    """KNOWN_EXTRAS마다 지금 깔려 있는가. probe가 같으면 한 번만 본다.

    자식 프로세스를 띄우는 일이라 30초 동안 기억한다 — 화면이 2초마다 묻는다.
    설치가 끝난 직후에는 force=True로 다시 본다.
    """
    now = time.time()
    seen: dict[str, bool] = {}
    result: dict[str, bool] = {}
    for name, meta in KNOWN_EXTRAS.items():
        mod = meta["probe"]
        if mod not in seen:
            hit = _probe_cache.get(mod)
            if force or hit is None or now - hit[0] > _PROBE_TTL:
                hit = (now, _probe(mod))
                _probe_cache[mod] = hit
            seen[mod] = hit[1]
        result[name] = seen[mod]
    return result


def recorded_extras() -> list[str]:
    """기록된 extras. 기록이 없으면 지금 깔린 것으로 처음 기록을 만든다."""
    path = _record_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [e for e in data.get("extras", []) if isinstance(e, str)]
        except (OSError, ValueError):
            pass
    found = [name for name, ok in installed_extras().items() if ok]
    _save_record(found)
    return found


def _save_record(extras: list[str]) -> None:
    write_json_atomic(_record_path(), {"extras": sorted(set(extras))})


def sync_args(extra_extras: list[str] | None = None) -> list[str]:
    """`uv sync`에 넘길 인자 — 기록된 extras 전부 + 이번에 더할 것."""
    # 기록에 남은 «지금 pyproject에 없는 이름»은 넘기지 않는다 — uv sync --extra bogus는 rc=2로
    # 죽고, 그 뒤로 업데이트·설치가 화면에서 복구할 길 없이 전부 실패한다(리뷰 실측).
    defined = defined_extras()
    wanted = sorted((set(recorded_extras()) | set(extra_extras or [])) & defined)
    args = ["uv", "sync"]
    for e in wanted:
        args += ["--extra", e]
    return args


# ── 설치 작업(한 번에 하나) ─────────────────────────────────────────────
_job: dict = {
    "running": False,
    "extra": None,
    "ok": None,
    "log": [],
    "started": None,
    "finished": None,
}
_lock = threading.Lock()
# 업데이트(uv sync)와 추가 설치(uv sync --extra)가 같은 환경을 서로 다른 extras 집합으로
# 동기화하지 않게 — 둘 중 하나가 도는 동안 다른 쪽은 거절한다. updater가 같은 잠금을 쓴다.
JOB_LOCK = threading.Lock()


def status() -> dict:
    """화면이 2초마다 묻는 것: 무엇이 깔렸고, 지금 도는 작업이 있는가."""
    with _lock:
        job = dict(_job)
        job["log"] = job["log"][-40:]
    return {
        "extras": [
            {"name": name, **meta, "installed": ok, "recorded": name in recorded_extras()}
            for (name, meta), ok in zip(KNOWN_EXTRAS.items(), installed_extras().values())
        ],
        "job": job,
    }


def _kill_tree(p) -> None:
    """자식과 그 손자까지 끝낸다.

    Windows에서 uv만 죽이면 uv가 띄운 pip/빌드 프로세스가 stdout을 물고 살아 있어 읽기가
    끝나지 않는다 — 감시가 있어도 running·JOB_LOCK이 안 풀린다(리뷰 실측).
    """
    import sys

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(p.pid)],
                capture_output=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            p.kill()
    except Exception:  # noqa: BLE001
        try:
            p.kill()
        except Exception:  # noqa: BLE001
            pass


def start_install(extra: str, on_done=None) -> dict:
    """`uv sync --extra <기록 전부> --extra <extra>`를 뒤에서 돌린다.

    입력: extra — pyproject가 정의한 extras 이름(BLOCKED_EXTRAS 제외). on_done — 성공하면
          부르는 함수(엔진 등록 캐시를 비우는 데 쓴다).
    출력: {"ok": bool, "error"?: str}. 이미 도는 작업이 있으면 거절한다.
    """
    if extra in BLOCKED_EXTRAS:
        return {
            "ok": False,
            "error": (
                f"{extra}는 이 환경에 넣지 않습니다 — GPU판은 별도 환경(.venv-gpu)에 깝니다"
                "(사용자 가이드 7-A.6-2)."
            ),
        }
    if extra not in defined_extras():
        return {"ok": False, "error": f"모르는 엔진 묶음입니다: {extra}"}
    if not JOB_LOCK.acquire(blocking=False):
        return {
            "ok": False,
            "error": "앱 업데이트나 다른 설치가 도는 중입니다. 끝나면 다시 누르세요.",
        }
    with _lock:
        if _job["running"]:
            JOB_LOCK.release()
            return {
                "ok": False,
                "error": f"{_job['extra']} 설치가 아직 돌고 있습니다. 끝나면 다시 누르세요.",
            }
        _job.update(
            {
                "running": True,
                "extra": extra,
                "ok": None,
                "log": [],
                "started": time.time(),
                "finished": None,
            }
        )

    # 준비(기록 읽기·probe)에서 죽어도 «도는 중»이 영원히 남지 않게 — 예외 경계 안에서.
    try:
        args = sync_args([extra])
    except Exception as e:  # noqa: BLE001
        with _lock:
            _job.update({"running": False, "ok": False, "finished": time.time()})
            _job["log"].append(f"준비 실패: {e}")
        JOB_LOCK.release()
        return {"ok": False, "error": f"설치를 준비하지 못했습니다: {e}"}

    def _run():
        code = -1
        p = None
        # **본문 전체**가 한 try 안이다 — OSError가 아닌 예외(Timer.start의 RuntimeError 등)가
        # 새면 running=True와 JOB_LOCK이 영원히 남아 이후 설치·업데이트가 전부 거절된다(리뷰 지적).
        try:
            p = subprocess.Popen(
                args,
                cwd=app_root(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            # 마감은 시작 시점부터 — 출력을 다 읽을 때까지 기다린 뒤 재면 제한이 없는 것과 같다.
            timed_out = {"hit": False}

            def _kill():
                if p.poll() is None:
                    timed_out["hit"] = True
                    _kill_tree(p)

            watchdog = threading.Timer(1800, _kill)
            watchdog.daemon = True
            watchdog.start()
            try:
                assert p.stdout is not None
                for line in p.stdout:
                    with _lock:
                        _job["log"].append(line.rstrip())
                        del _job["log"][:-500]  # 무한히 자라지 않게
                code = p.wait()
            finally:
                watchdog.cancel()
            if timed_out["hit"]:
                code = -1
                with _lock:
                    _job["log"].append("30분을 넘겨 중단했습니다.")
        except Exception as e:  # noqa: BLE001 — 어떤 예외든 «도는 중»을 남기지 않는다
            code = -1
            with _lock:
                _job["log"].append(f"실패: {type(e).__name__}: {e}")
        ok = code == 0
        try:
            if ok:
                try:
                    _save_record(recorded_extras() + [extra])
                except Exception as e:  # noqa: BLE001 — 설치는 됐는데 기록만 실패
                    with _lock:
                        _job["log"].append(f"설치는 됐지만 기록에 실패했습니다: {e}")
                installed_extras(force=True)  # 방금 깔린 것을 바로 짚는다
                if on_done is not None:
                    try:
                        on_done()
                    except Exception as e:  # noqa: BLE001 — 뒷정리 실패가 설치 성공을 가리면 안 된다
                        with _lock:
                            _job["log"].append(f"엔진 목록 새로 고침 실패: {e}")
        finally:
            with _lock:
                _job.update({"running": False, "ok": ok, "finished": time.time()})
            JOB_LOCK.release()

    threading.Thread(target=_run, name=f"extras-install-{extra}", daemon=True).start()
    return {"ok": True, "args": args}
