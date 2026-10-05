"""설치 5-1단계(Ollama 기본 비전 모델)가 Ollama가 꺼져 있어도 멈추지 않는다 (2026-10-06 설치 검증).

무엇을 고정하는가:
  1. install.ps1·install.sh에 `ollama list`가 다시 생기지 않는다. Ollama가 깔려 있으나 꺼져
     있으면 `ollama list`가 Ollama 앱(`ollama app.exe --hide`)을 스스로 띄우고, 그 앱이 출력
     파이프를 물려받아 닫지 않아 `(& ollama list | Out-String)`이 EOF를 영원히 기다렸다 —
     install.ps1과 CTB-Setup이 28분 동안 멈췄다. 목록은 HTTP API(`/api/tags`, 3초 제한)로 읽는다.
  2. install.ps1은 `ollama`를 직접 부르지 않고 `scripts/install_ollama_step.ps1`에 맡긴다. 그
     파일의 `ollama pull`은 시간 제한이 있고 **핸들을 물려주지 않는** 시작(UseShellExecute)이다 —
     출력을 파일로 돌리는 Start-Process도 상속 가능한 핸들 전부를 물려줘 손자가 파이프를 붙잡았다
     (재현: 남는 자식 30초 → 31초 대기).
  3. (Windows) 실제로 돌려 본다 — 가짜 `ollama.cmd`가 남는 자식을 띄워 파이프를 붙잡는 상황에서
     꺼짐·켜짐 둘 다 그 자식의 수명보다 훨씬 빨리 끝난다. 진짜 Ollama에는 닿지 않는다(닫힌 포트·
     가짜 HTTP 서버).
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALL_PS1 = ROOT / "install.ps1"
INSTALL_SH = ROOT / "install.sh"
STEP_PS1 = ROOT / "scripts" / "install_ollama_step.ps1"


def _code_lines(path: Path) -> list[str]:
    """주석 줄을 뺀 코드 줄(ps1·sh 모두 #가 주석)."""
    text = path.read_text(encoding="utf-8-sig")
    return [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]


# ── 1·2. 정적 ───────────────────────────────────────────────────────


@pytest.mark.parametrize("path", [INSTALL_PS1, INSTALL_SH, STEP_PS1], ids=lambda p: p.name)
def test_no_ollama_list_in_installers(path):
    bad = [ln for ln in _code_lines(path) if re.search(r"\bollama(\.exe)?\s+list\b", ln)]
    assert bad == [], f"{path.name}: `ollama list`는 꺼진 Ollama의 앱을 띄워 설치를 멈춘다 — {bad}"


def test_install_ps1_does_not_call_ollama_directly():
    # `& ollama …`·줄 머리의 `ollama …` — 이 단계의 명령 호출은 step 파일 한 곳에만 둔다
    bad = [
        ln
        for ln in _code_lines(INSTALL_PS1)
        if re.search(r"&\s*ollama\b", ln) or re.match(r"\s*ollama(\.exe)?\s", ln)
    ]
    assert bad == []
    assert "install_ollama_step.ps1" in INSTALL_PS1.read_text(encoding="utf-8-sig")


def test_step_reads_tags_over_http_with_timeout():
    code = "\n".join(_code_lines(STEP_PS1))
    assert "/api/tags" in code and re.search(r"Invoke-RestMethod[^\n]*-TimeoutSec\s+\d", code)
    # 명령 호출은 Invoke-OllamaTimed 한 곳 — 핸들을 물려주지 않는 시작, 시간 제한
    assert "UseShellExecute = $true" in code
    assert "WaitForExit(" in code
    assert "-RedirectStandardOutput" not in code
    assert not re.search(r"&\s*ollama\b", code)


def test_install_sh_reads_tags_with_timeout():
    code = "\n".join(_code_lines(INSTALL_SH))
    assert re.search(r"curl[^\n]*--max-time\s+\d[^\n]*/api/tags", code)


@pytest.mark.parametrize("path", [INSTALL_PS1, STEP_PS1], ids=lambda p: p.name)
def test_ps1_is_utf8_with_bom(path):
    # BOM이 없으면 Windows PowerShell 5.1이 ANSI 코드페이지로 읽어 한글이 깨진다
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")


# ── 3. Windows에서 실제로 돌려 보기 ───────────────────────────────────

_LINGER_SEC = 40  # 가짜 ollama가 남기는 자식의 수명 — 단계가 이것을 기다리면 실패
_FAKE_CMD = (
    "@echo off\r\n"
    'echo %* >> "%~dp0calls.log"\r\n'
    # Ollama 앱처럼 남는 자식 — 이 창의 출력 핸들을 물려받는다
    f'start "" /b powershell -NoProfile -Command "Start-Sleep {_LINGER_SEC}"\r\n'
    "echo NAME    ID    SIZE    MODIFIED\r\n"
    "exit /b 0\r\n"
)

windows_only = pytest.mark.skipif(
    sys.platform != "win32" or shutil.which("powershell") is None, reason="Windows PowerShell 전용"
)


def _closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _run_step(tmp_path: Path, ollama_host: str) -> tuple[str, float, list[str]]:
    import os

    fake = tmp_path / "fakebin"
    fake.mkdir(exist_ok=True)
    (fake / "ollama.cmd").write_text(_FAKE_CMD, encoding="ascii")
    env = dict(os.environ)
    env["PATH"] = f"{fake};{env.get('PATH', '')}"
    env["OLLAMA_HOST"] = ollama_host
    env["CTB_OLLAMA_PULL_TIMEOUT"] = "10"
    t0 = time.monotonic()
    # CTB-Setup(installer/ctb_setup.py::run_install_ps1)과 같은 꼴로 띄우고 출력을 파이프로
    # 읽는다 — EOF가 와야 끝난다
    ps1 = str(STEP_PS1).replace("'", "''")
    p = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f"[Console]::OutputEncoding = [Text.Encoding]::UTF8; & '{ps1}'; exit $LASTEXITCODE",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        timeout=_LINGER_SEC + 20,
    )
    elapsed = time.monotonic() - t0
    log = fake / "calls.log"
    calls = log.read_text(encoding="ascii", errors="replace").split() if log.exists() else []
    return p.stdout.decode("utf-8", errors="replace"), elapsed, calls


@windows_only
def test_step_skips_quickly_when_ollama_is_off(tmp_path):
    out, elapsed, calls = _run_step(tmp_path, f"127.0.0.1:{_closed_port()}")
    assert elapsed < 20, f"꺼진 Ollama에서 {elapsed:.1f}초"
    assert calls == []  # ollama 명령을 부르지 않았다
    assert "꺼져" in out


@windows_only
def test_step_pull_does_not_wait_for_lingering_children(tmp_path):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"models": [{"name": "llava:7b"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        out, elapsed, calls = _run_step(tmp_path, f"127.0.0.1:{srv.server_address[1]}")
    finally:
        srv.shutdown()
    # 가짜 ollama가 남긴 자식(40초)이 출력 파이프를 붙잡지 못했다
    assert elapsed < 20, f"남는 자식을 {elapsed:.1f}초 기다렸다"
    assert calls == ["pull", "gemma4:cloud", "pull", "kimi-k3:cloud"]
    assert "등록합니다" in out
