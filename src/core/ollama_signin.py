"""Ollama 로그인을 앱이 대신 시작한다 — «로그인 필요»라고만 말하고 끝내지 않는다 (D-107 연장).

`ollama signin`은 로그인 주소(https://ollama.com/connect?…)를 찍고 브라우저를 열어 준다.
이 모듈은 그 명령을 뒤에서 돌리고 주소를 건져 화면에 준다. 로그인이 끝났는지는 설정 화면이
/api/llm/accounts(= /api/me)로 다시 확인한다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time

_URL = re.compile(r"(https://[^\s\"'<>]+)")
_state: dict = {"proc": None, "url": None, "log": [], "started": None}
_lock = threading.Lock()


def find_ollama() -> str | None:
    return shutil.which("ollama") or shutil.which("ollama.exe")


def start(wait: float = 4.0) -> dict:
    """`ollama signin`을 띄우고 로그인 주소가 찍힐 때까지(최대 wait초) 기다린다.

    출력: {"ok", "url", "running", "log", "error"?}. ollama 명령이 없으면 error.
    """
    exe = find_ollama()
    if exe is None:
        return {"ok": False, "url": None, "running": False, "log": [],
                "error": "ollama 명령을 찾지 못했습니다. Ollama가 깔려 있고 PATH에 있어야 합니다."}
    with _lock:
        proc = _state["proc"]
        if proc is not None and proc.poll() is None and _state["url"]:
            return {"ok": True, "url": _state["url"], "running": True, "log": _state["log"][-10:]}
    try:
        proc = subprocess.Popen(
            [exe, "signin"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as e:
        return {"ok": False, "url": None, "running": False, "log": [], "error": f"실행 실패: {e}"}
    with _lock:
        _state.update({"proc": proc, "url": None, "log": [], "started": time.time()})

    def _pump():
        assert proc.stdout is not None
        for line in proc.stdout:
            text = line.strip()
            with _lock:
                _state["log"].append(text)
                m = _URL.search(text)
                if m and not _state["url"]:
                    _state["url"] = m.group(1)

    threading.Thread(target=_pump, name="ollama-signin", daemon=True).start()
    deadline = time.time() + wait
    while time.time() < deadline:
        with _lock:
            if _state["url"]:
                break
        time.sleep(0.2)
    with _lock:
        url = _state["url"]
        log = _state["log"][-10:]
        running = proc.poll() is None
    if not url and not running:
        return {"ok": False, "url": None, "running": False, "log": log,
                "error": "ollama signin이 주소를 주지 않고 끝났습니다: " + " / ".join(log)[:300]}
    return {"ok": True, "url": url, "running": running, "log": log}


# ── 모델 받기(ollama pull) — «터미널에서 ollama pull 하세요»로 끝내지 않는다 ──
_pull: dict = {"proc": None, "model": None, "log": [], "ok": None}


def pull_status() -> dict:
    with _lock:
        proc = _pull["proc"]
        running = proc is not None and proc.poll() is None
        return {
            "running": running,
            "model": _pull["model"],
            "ok": _pull["ok"],
            "log": _pull["log"][-8:],
        }


def pull(model: str) -> dict:
    """`ollama pull <model>`을 뒤에서 돌린다. 출력: pull_status()와 같은 꼴(+error)."""
    exe = find_ollama()
    if exe is None:
        return {**pull_status(), "error": "ollama 명령을 찾지 못했습니다."}
    if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,100}", model or ""):
        return {**pull_status(), "error": f"모델 이름이 이상합니다: {model!r}"}
    with _lock:
        proc = _pull["proc"]
        if proc is not None and proc.poll() is None:
            return {**pull_status(), "error": f"{_pull['model']} 받기가 아직 돌고 있습니다."}
    try:
        proc = subprocess.Popen(
            [exe, "pull", model],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as e:
        return {**pull_status(), "error": f"실행 실패: {e}"}
    with _lock:
        _pull.update({"proc": proc, "model": model, "log": [], "ok": None})

    def _pump():
        assert proc.stdout is not None
        for line in proc.stdout:
            with _lock:
                _pull["log"].append(line.strip()[:160])
        code = proc.wait()
        with _lock:
            _pull["ok"] = code == 0

    threading.Thread(target=_pump, name=f"ollama-pull-{model}", daemon=True).start()
    return pull_status()
