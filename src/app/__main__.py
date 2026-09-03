"""웹 앱 진입점.

사용법:
    python -m app serve --library <서고 경로> [--port 8000] [--host 127.0.0.1]
    python -m app serve --port 8000   # --library 생략 시 마지막 서고 자동 사용
"""

import argparse
import sys
from pathlib import Path

# src/ 디렉토리를 Python 경로에 추가
_src_dir = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)


def main():
    parser = argparse.ArgumentParser(
        prog="classical-text-browser",
        description="고전 텍스트 서고 웹 서버",
    )
    subparsers = parser.add_subparsers(dest="command")

    p_serve = subparsers.add_parser("serve", help="웹 서버를 실행한다")
    p_serve.add_argument(
        "--library",
        required=False,
        default=None,
        help="서고 경로 (생략 시 마지막 사용 서고 자동 선택)",
    )
    p_serve.add_argument("--port", type=int, default=8000, help="포트 (기본: 8000)")
    p_serve.add_argument("--host", default="127.0.0.1", help="호스트 (기본: 127.0.0.1)")
    p_serve.add_argument(
        "--reload",
        action="store_true",
        help="src/ 안의 파이썬 파일이 바뀌면 서버를 스스로 다시 띄운다 (개발·수정 반영용)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "serve":
        import uvicorn

        from app.server import configure

        # 서고 경로 결정: CLI 인자 → 마지막 사용 서고 → 미지정
        library_path = None

        if args.library:
            library_path = Path(args.library).resolve()
            if not (library_path / "library_manifest.json").exists():
                print(
                    f"오류: 서고를 찾을 수 없습니다: {library_path}\n"
                    "→ 해결: 'python -m cli init-library <경로>'로 서고를 먼저 생성하세요.",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            # 마지막 사용 서고 자동 선택
            try:
                from core.app_config import get_last_library

                last = get_last_library()
                if last:
                    library_path = Path(last).resolve()
                    print(f"마지막 서고 자동 선택: {library_path}")
            except Exception:
                pass

        if library_path:
            configure(library_path)
            print(f"서고: {library_path}")
        else:
            print("서고 미지정. 브라우저에서 서고를 선택하거나 생성하세요.")

        print(f"서버: http://{args.host}:{args.port}")
        if args.reload:
            # 사용자가 «고칠 때마다 서버를 껐다 켜기 싫다»고 해서 넣었다(2026-09-03).
            # uvicorn 자체 reload(멀티프로세싱으로 __main__을 다시 import)는 `python -m app`과
            # 얽혀 재기동 뒤 멈추는 것이 실측됐다. 대신 이 프로세스가 감시자가 되어 src/를 지켜보고,
            # .py가 바뀌면 «평범한 serve» 자식을 끄고 다시 띄운다. 자식은 reload를 모른다.
            _supervise(args, library_path)
            return
        uvicorn.run(
            "app.server:app",
            host=args.host,
            port=args.port,
            reload=False,
        )


def _supervise(args, library_path) -> None:
    """감시자: src/의 .py가 바뀌면 서버 자식을 다시 띄운다. Ctrl+C면 자식을 끄고 나간다.

    왜 자식에 --library를 넘기는가: 자식은 평범한 serve라 자기 인자로 서고를 잡는다.
    왜 watchfiles인가: uvicorn이 이미 의존하므로 새 패키지가 없다. 없으면 폴링(1초 mtime)으로 간다.
    """
    import signal
    import subprocess
    import time

    src_dir = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "-m", "app", "serve", "--host", args.host, "--port", str(args.port)]
    if library_path:
        cmd += ["--library", str(library_path)]
    child: subprocess.Popen | None = None

    def start():
        nonlocal child
        child = subprocess.Popen(cmd)

    def stop():
        nonlocal child
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
        child = None

    print(f"자동 재적재: {src_dir} 안의 .py가 바뀌면 서버가 다시 뜹니다 (엔진은 다시 읽습니다)")
    start()
    try:
        try:
            from watchfiles import watch

            for changes in watch(str(src_dir), watch_filter=lambda _c, path: path.endswith(".py")):
                names = sorted({Path(c[1]).name for c in changes})
                print(f"[자동 재적재] 변경 감지 {', '.join(names)[:120]} — 서버를 다시 띄웁니다")
                stop()
                start()
        except ImportError:
            # 폴링 폴백: 1초마다 .py mtime 최대값 비교
            def stamp():
                return max((p.stat().st_mtime for p in src_dir.rglob("*.py")), default=0.0)

            last = stamp()
            while True:
                time.sleep(1.0)
                now = stamp()
                if now != last:
                    last = now
                    print("[자동 재적재] 변경 감지 — 서버를 다시 띄웁니다")
                    stop()
                    start()
                if child is not None and child.poll() is not None:
                    print("[자동 재적재] 서버가 내려갔습니다. 다시 띄웁니다")
                    start()
    except KeyboardInterrupt:
        pass
    finally:
        stop()
    signal.signal(signal.SIGINT, signal.SIG_DFL)


if __name__ == "__main__":
    main()
