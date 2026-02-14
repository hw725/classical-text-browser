"""웹 앱 진입점.

사용법:
    python -m app serve --library <서고 경로> [--port 8000] [--host 127.0.0.1]
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
        prog="classical-text-platform-server",
        description="고전 텍스트 서고 웹 서버",
    )
    subparsers = parser.add_subparsers(dest="command")

    p_serve = subparsers.add_parser("serve", help="웹 서버를 실행한다")
    p_serve.add_argument("--library", required=True, help="서고 경로")
    p_serve.add_argument("--port", type=int, default=8000, help="포트 (기본: 8000)")
    p_serve.add_argument("--host", default="127.0.0.1", help="호스트 (기본: 127.0.0.1)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "serve":
        import uvicorn
        from app.server import configure

        library_path = Path(args.library).resolve()
        if not (library_path / "library_manifest.json").exists():
            print(
                f"오류: 서고를 찾을 수 없습니다: {library_path}\n"
                "→ 해결: 'python -m cli init-library <경로>'로 서고를 먼저 생성하세요.",
                file=sys.stderr,
            )
            sys.exit(1)

        configure(library_path)
        print(f"서고: {library_path}")
        print(f"서버: http://{args.host}:{args.port}")
        uvicorn.run(
            "app.server:app",
            host=args.host,
            port=args.port,
            reload=False,
        )


if __name__ == "__main__":
    main()
