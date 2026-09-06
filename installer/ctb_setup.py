"""CTB-Setup.exe — 고전서지 통합 브라우저 설치 프로그램 (B-004 → D-113).

무엇을 하는가: 창 하나에서 ① 설치 폴더를 고르고 ② 글자 인식 엔진을 고르면
③ 앱을 내려받아 풀고 ④ `install.ps1`(Python·Git·uv·의존·모델)을 돌리고 ⑤ 바탕화면에
「고전서지 브라우저」 아이콘을 만든 뒤 ⑥ 바로 켜 준다. 터미널을 열 일이 없다.

왜 «부트스트래퍼»인가: OCR 스택(약 830MB)을 exe에 통째로 넣으면 판마다 그 크기를 다시
받아야 하고, 앱의 자동 업데이트(D-112 — git 사본 + `uv sync`)와 어긋난다. 작은 exe가
설치만 맡고, 그 뒤는 앱이 스스로 갱신하는 편이 사용자에게 가장 적게 시킨다.

표준 라이브러리만 쓴다(tkinter·urllib·zipfile·subprocess) — PyInstaller로 한 파일이 된다.
`--auto --dir <폴더> --pick 1`로 창 없이도 돈다(자동 검증용). **`--auto`는 바탕화면 바로 가기를
만들지 않는다**(`--shortcut`으로 켠다) — 격리 HOME에서 돌린 검증이 실제 바탕화면에 임시 폴더를
가리키는 「고전서지 브라우저」 아이콘을 남겼다(2026-09-06). 바탕화면 경로는 HOME이 아니라
Windows에 묻기 때문이다.

빌드: scripts/build_installer.ps1  (uvx pyinstaller)
"""

from __future__ import annotations

import argparse
import io
import os
import queue
import re
import subprocess
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path

REPO = "hw725/classical-text-browser"
# 설치 파일이 받는 판. 릴리스 태그의 소스 zip — main.zip이면 «릴리스 안 된 커밋»도 받게 된다.
ZIP_URL = os.environ.get("CTB_SETUP_ZIP") or (
    f"https://github.com/{REPO}/archive/refs/tags/v1.3.0.zip"
)
DEFAULT_DIR = Path.home() / "ClassicalTextBrowser"
SHORTCUT_NAME = "고전서지 브라우저.lnk"
# uv·PaddleX·ollama가 찍는 색·커서 제어열 — 터미널이 아니면 글자 그대로 창에 남는다([32m …).
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][A-Za-z0-9]|[\x00-\x08\x0b-\x1f]")


# ── 실제 작업 (창이 있든 없든 같은 코드) ─────────────────────────────────


def download(url: str, say) -> bytes:
    """소스 zip을 받는다. 진행률을 say로 알린다."""
    say(f"내려받는 중: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "ctb-setup"})
    with urllib.request.urlopen(req, timeout=120) as r:
        total = int(r.headers.get("Content-Length") or 0)
        buf = io.BytesIO()
        got = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            buf.write(chunk)
            got += len(chunk)
            if total:
                say(f"  {got * 100 // total}% ({got // 1024}KB)", replace=True)
    say(f"  받음: {got // 1024}KB")
    return buf.getvalue()


def extract_into(data: bytes, target: Path, say) -> None:
    """zip의 맨 위 폴더(classical-text-browser-<판>/)를 벗겨 target에 푼다. 기존 파일은 덮어쓴다."""
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        top = names[0].split("/")[0] if names and "/" in names[0] else ""
        n = 0
        for info in z.infolist():
            rel = info.filename
            if top and rel.startswith(top + "/"):
                rel = rel[len(top) + 1 :]
            if not rel:
                continue
            dest = target / rel
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                out.write(src.read())
            n += 1
    say(f"  풀었음: {n}개 파일 → {target}")


def run_install_ps1(target: Path, pick: str, say) -> int:
    """install.ps1을 돌리며 출력을 그대로 창에 흘린다. 엔진 선택은 환경 변수로 넘긴다."""
    env = dict(os.environ)
    env["CTB_INSTALL_PICK"] = pick
    # 출력은 UTF-8로 받는다 — 콘솔 코드 페이지(cp949) 그대로면 한글이 깨진다.
    ps1 = str(target / "install.ps1").replace("'", "''")
    cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        f"[Console]::OutputEncoding = [Text.Encoding]::UTF8; & '{ps1}'; exit $LASTEXITCODE",
    ]
    say("설치 스크립트 실행 (Python·Git·uv·의존·글자 인식 모델) — 처음이면 5~10분")
    p = subprocess.Popen(
        cmd, cwd=str(target), env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert p.stdout is not None
    for raw in iter(p.stdout.readline, b""):
        try:
            line = raw.decode("utf-8").rstrip()
        except UnicodeDecodeError:
            line = raw.decode("cp949", "replace").rstrip()
        line = _ANSI.sub("", line)
        if line.strip():
            say("  " + line)
    return p.wait()


def make_shortcut(target: Path, say) -> Path | None:
    """바탕화면에 start_server.bat 바로 가기. 실패해도 설치는 성공이다."""
    # 바탕화면은 OneDrive 등으로 옮겨져 있을 수 있다 — Windows에 실제 경로를 묻는다.
    desktop = None
    try:
        raw = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
            capture_output=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        # 콘솔 출력은 코드 페이지(cp949) — 「바탕 화면」 같은 한글 경로가 온다
        try:
            out = raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            out = raw.decode("cp949", "replace").strip()
        if out:
            desktop = Path(out)
    except Exception:  # noqa: BLE001
        desktop = None
    if not desktop:
        desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    lnk = desktop / SHORTCUT_NAME
    q = lambda v: str(v).replace("'", "''")  # noqa: E731 — PowerShell 작은따옴표 이스케이프
    ps = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}'); "
        f"$s.TargetPath = '{q(target / 'start_server.bat')}'; "
        f"$s.WorkingDirectory = '{q(target)}'; "
        "$s.Description = 'Classical Text Browser'; $s.Save()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=60,
        )
        say(f"바탕화면 아이콘: {lnk.name}")
        return lnk
    except Exception as e:  # noqa: BLE001
        say(
            f"바탕화면 아이콘을 만들지 못했습니다({type(e).__name__}) — "
            "설치 폴더의 start_server.bat을 쓰세요."
        )
        return None


def install(target: Path, pick: str, say) -> bool:
    """전체 순서. 출력: 성공 여부."""
    try:
        data = download(ZIP_URL, say)
        extract_into(data, target, say)
        rc = run_install_ps1(target, pick, say)
        if rc != 0:
            say(f"설치 스크립트가 오류로 끝났습니다(코드 {rc}). 위 기록의 [막힘] 줄을 보세요.")
            return False
        make_shortcut(target, say)
        say("설치가 끝났습니다.")
        return True
    except Exception as e:  # noqa: BLE001 — 창에 까닭을 남긴다
        say(f"설치 실패: {type(e).__name__}: {e}")
        return False


def launch(target: Path) -> None:
    """start_server.bat을 새 창에서 켠다(자동 업데이트 → 서버 → 브라우저)."""
    subprocess.Popen(
        ["cmd", "/c", "start", "", str(target / "start_server.bat")], cwd=str(target)
    )


# ── 창 ────────────────────────────────────────────────────────────────


def gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, ttk

    root = tk.Tk()
    root.title("고전서지 통합 브라우저 설치")
    root.geometry("640x520")
    root.minsize(560, 440)

    frm = ttk.Frame(root, padding=12)
    frm.pack(fill="both", expand=True)

    title = ttk.Label(frm, text="고전서지 통합 브라우저를 설치합니다.", font=("", 12, "bold"))
    title.pack(anchor="w")
    ttk.Label(
        frm, text="설치 폴더를 고르고 「설치」를 누르면 끝까지 알아서 합니다. 인터넷이 필요합니다."
    ).pack(anchor="w", pady=(2, 10))

    row = ttk.Frame(frm)
    row.pack(fill="x")
    ttk.Label(row, text="설치 폴더").pack(side="left")
    dir_var = tk.StringVar(value=str(DEFAULT_DIR))
    ent = ttk.Entry(row, textvariable=dir_var)
    ent.pack(side="left", fill="x", expand=True, padx=6)

    def browse():
        d = filedialog.askdirectory(initialdir=str(DEFAULT_DIR.parent), title="설치 폴더")
        if d:
            dir_var.set(str(Path(d) / DEFAULT_DIR.name) if Path(d).name != DEFAULT_DIR.name else d)

    ttk.Button(row, text="폴더 선택", command=browse).pack(side="left")

    ttk.Label(frm, text="글자 인식 엔진").pack(anchor="w", pady=(10, 2))
    pick_var = tk.StringVar(value="1")
    for v, t in (
        ("1", "본체만 — 한글 논문·글자가 든 PDF는 이것으로 다 됩니다 (약 830MB)"),
        ("2", "+ 고서 엔진 — 한문 고서 스캔 (+170MB)"),
        ("3", "+ 고서·일본어 엔진 — 근현대 일본어 자료까지 (+340MB)"),
    ):
        ttk.Radiobutton(frm, text=t, value=v, variable=pick_var).pack(anchor="w")
    ttk.Label(frm, text="나중에 앱 안 설정에서 단추로 더할 수 있습니다.", foreground="gray").pack(
        anchor="w"
    )

    log = tk.Text(frm, height=14, wrap="word", state="disabled")
    log.pack(fill="both", expand=True, pady=(10, 6))

    btns = ttk.Frame(frm)
    btns.pack(fill="x")
    go = ttk.Button(btns, text="설치")
    go.pack(side="left")
    run_btn = ttk.Button(btns, text="지금 실행", state="disabled")
    run_btn.pack(side="left", padx=6)
    ttk.Button(btns, text="닫기", command=root.destroy).pack(side="right")

    q: queue.Queue = queue.Queue()

    def say(text: str, replace: bool = False) -> None:
        q.put((text, replace))

    def pump():
        try:
            while True:
                text, replace = q.get_nowait()
                log.configure(state="normal")
                if replace:
                    log.delete("end-2l", "end-1l")
                log.insert("end", text + "\n")
                log.see("end")
                log.configure(state="disabled")
        except queue.Empty:
            pass
        root.after(100, pump)

    state = {"target": None}

    def worker():
        target = Path(dir_var.get()).expanduser()
        ok = install(target, pick_var.get(), say)
        state["target"] = target if ok else None
        root.after(0, lambda: finish(ok))

    def finish(ok: bool):
        go.configure(state="normal")
        if ok:
            run_btn.configure(state="normal")
            say("「지금 실행」을 누르면 앱이 켜지고 브라우저가 열립니다.")
            say("다음부터는 바탕화면의 「고전서지 브라우저」 아이콘으로 켭니다.")

    def start():
        go.configure(state="disabled")
        run_btn.configure(state="disabled")
        threading.Thread(target=worker, daemon=True).start()

    def run_now():
        if state["target"]:
            launch(state["target"])
            root.destroy()

    go.configure(command=start)
    run_btn.configure(command=run_now)
    pump()
    root.mainloop()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="고전서지 통합 브라우저 설치")
    ap.add_argument("--auto", action="store_true", help="창 없이 설치(검증용)")
    ap.add_argument("--dir", default=None, help="설치 폴더")
    ap.add_argument("--pick", default="1", choices=["1", "2", "3"], help="글자 인식 엔진")
    ap.add_argument("--no-shortcut", action="store_true", help="(옛 이름) --auto의 기본 동작")
    ap.add_argument("--shortcut", action="store_true", help="--auto에서도 바탕화면 바로 가기를 만든다")
    a = ap.parse_args(argv)
    if not a.auto:
        return gui()

    # 콘솔은 cp949일 수 있다 — «—» 같은 글자에서 죽지 않게 UTF-8로 고정(창 없는 exe는 stdout이 없다)
    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    last = {"pct": -1}

    def say(text, replace=False):
        if sys.stdout is None:
            return
        if replace:  # 진행률은 10%마다만
            pct = text.strip().split("%")[0]
            if pct.isdigit() and int(pct) // 10 == last["pct"]:
                return
            last["pct"] = int(pct) // 10 if pct.isdigit() else last["pct"]
        print(text, flush=True)

    target = Path(a.dir).expanduser() if a.dir else DEFAULT_DIR
    if not a.shortcut:
        # 검증용 실행이 실제 바탕화면을 건드리지 않게 — 창으로 설치할 때만 아이콘을 만든다.
        global make_shortcut
        make_shortcut = lambda t, s: None  # noqa: E731
    return 0 if install(target, a.pick, say) else 1


if __name__ == "__main__":
    sys.exit(main())
