"""OpenAI OAuth 프록시를 앱이 띄우고 로그인 길을 연다 (D-107).

왜 있는가:
    「OpenAI (OAuth)」는 ChatGPT 구독으로 쓰는 길이라 키가 없다. 프록시(openai-oauth, Node)가
    로그인을 대신하는데, start_server.bat이 창 없이 띄우므로 로그인이 필요할 때 사람이 보는 것은
    `logs/openai-oauth.log`뿐이었다 — 사용자 가이드 8.3이 «로그를 보세요»라고 적어 두었다.
    사용자는 로그를 열지 않는다(2026-09-05 지적).

무엇을 하는가:
    설정·마법사의 단추 하나로 프록시를 띄우고, 출력에서 «준비됨» 줄과 로그인 주소를 건져
    화면에 낸다. 프록시는 로그인이 필요하면 스스로 브라우저를 열기도 한다 — 그래도 주소를
    같이 보여 준다(브라우저가 안 열린 경우를 위해).

start_server.bat이 이미 띄운 프록시가 있으면 그것을 쓴다 — 포트를 짚어 보고 살아 있으면
새로 띄우지 않는다. 프록시가 쓰는 포트 범위는 provider와 같다(10531~10540).
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

PORT_RANGE = range(10531, 10541)

_READY = re.compile(r"ready at (http://[^\s]+)")
# 로그인 주소 — 프록시·OpenAI가 찍는 https 주소 가운데 내 컴퓨터가 아닌 것.
_LOGIN_URL = re.compile(r"(https://[^\s\"'<>]+)")

_state: dict = {
    "proc": None,  # Popen — 이 앱이 띄운 경우에만
    "port": None,
    "base_url": None,
    "login_url": None,
    "log": [],
    "started": None,
}
_lock = threading.Lock()


def app_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def find_npx() -> str | None:
    """npx 실행 파일. Windows는 npx.cmd다 — Node.js가 없으면 None."""
    return shutil.which("npx.cmd") or shutil.which("npx")


def _probe(port: int, timeout: float = 0.7) -> bool:
    """그 포트에 OpenAI 호환 프록시가 살아 있는가 (/v1/models가 200)."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/models",
            headers={"Authorization": "Bearer oauth-proxy"},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 로컬은 프록시 없이
        with opener.open(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read())
            return isinstance(data, dict) and "data" in data
    except Exception:
        return False


_last_found_port: int | None = None


def find_running() -> str | None:
    """이미 떠 있는 프록시의 base URL. 없으면 None.

    지난번에 찾은 포트를 먼저 보고, 없으면 열 포트를 **동시에** 찔러 본다 — 차례로 하면
    답하지 않는 포트마다 시간 제한만큼 설정 화면이 멈춘다.
    """
    global _last_found_port
    if _last_found_port and _probe(_last_found_port):
        return f"http://127.0.0.1:{_last_found_port}/v1"
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(PORT_RANGE)) as ex:
        hits = list(ex.map(_probe, PORT_RANGE))
    for port, ok in zip(PORT_RANGE, hits):
        if ok:
            _last_found_port = port
            return f"http://127.0.0.1:{port}/v1"
    _last_found_port = None
    return None


def _free_port() -> int | None:
    for port in PORT_RANGE:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return None


def status() -> dict:
    """화면이 묻는 것 — npx가 있는가, 떠 있는가, 준비됐는가, 로그인 주소, 로그 꼬리."""
    with _lock:
        proc = _state["proc"]
        running = proc is not None and proc.poll() is None
        base_url = _state["base_url"]
        login_url = _state["login_url"]
        log = list(_state["log"][-30:])
    ready = bool(base_url) and _probe(int(base_url.rsplit(":", 1)[1].split("/")[0]))
    if not ready:
        found = find_running()  # start_server.bat이 띄운 것일 수 있다
        if found:
            base_url, ready = found, True
            with _lock:
                _state["base_url"] = found
    return {
        "npx": find_npx() is not None,
        "running": running or ready,
        "ready": ready,
        "base_url": base_url if ready else None,
        "login_url": None if ready else login_url,
        "log": log,
    }


def start() -> dict:
    """프록시를 띄운다. 이미 살아 있으면 그대로 status()를 준다.

    출력: status()와 같은 꼴. npx가 없거나 빈 포트가 없으면 {"error": ...}.
    """
    if find_running():
        return status()
    npx = find_npx()
    if npx is None:
        return {
            "error": "Node.js(npx)가 없습니다. https://nodejs.org 에서 LTS를 깐 뒤 다시 누르세요.",
            **status(),
        }
    with _lock:
        proc = _state["proc"]
        if proc is not None and proc.poll() is None:
            return status()
    port = _free_port()
    if port is None:
        return {"error": "10531~10540 포트가 모두 차 있습니다.", **status()}

    logs = app_root() / "logs"
    logs.mkdir(exist_ok=True)
    try:
        proc = subprocess.Popen(
            [npx, "-y", "openai-oauth", "--port", str(port)],
            cwd=app_root(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as e:
        return {"error": f"프록시를 띄우지 못했습니다: {e}", **status()}

    with _lock:
        _state.update(
            {
                "proc": proc,
                "port": port,
                "base_url": None,
                "login_url": None,
                "log": [],
                "started": time.time(),
            }
        )

    def _pump():
        # 프록시 출력을 한 줄씩 받아 «준비됨»과 로그인 주소를 건진다. 파일에도 덧붙인다 —
        # start_server.bat이 쓰던 그 로그라 사람이 보던 자리가 바뀌지 않는다.
        assert proc.stdout is not None
        with open(logs / "openai-oauth.log", "a", encoding="utf-8") as f:
            for line in proc.stdout:
                f.write(line)
                text = line.strip()
                with _lock:
                    _state["log"].append(text)
                    m = _READY.search(text)
                    if m:
                        _state["base_url"] = m.group(1)
                    for url in _LOGIN_URL.findall(text):
                        if "127.0.0.1" not in url and "localhost" not in url:
                            _state["login_url"] = url

    threading.Thread(target=_pump, name="openai-oauth-proxy", daemon=True).start()
    return status()
