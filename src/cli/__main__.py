"""CLI 도구 — 고전서지 통합 브라우저.

사용법:
    python -m cli init-library <path>
    python -m cli add-document <library_path> --title <제목> --doc-id <id> [--files ...]
    python -m cli list-documents <library_path>

pip install -e . 후 실행하거나, src/ 디렉토리에서 실행한다.
"""

import argparse
import sys
from pathlib import Path

# src/ 디렉토리를 Python 경로에 추가하여 pip install 없이도 실행 가능하게 한다.
# (pip install -e . 후에는 이 조작이 불필요하지만, 해가 되지 않는다.)
_src_dir = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from core.library import init_library, get_library_info, list_documents  # noqa: E402
from core.document import add_document  # noqa: E402


def cmd_init_library(args):
    """서고를 초기화한다."""
    try:
        path = init_library(args.path)
        print(f"✓ 서고를 생성했습니다: {path}")
    except FileExistsError as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_add_document(args):
    """문헌을 서고에 등록한다."""
    try:
        doc_path = add_document(
            library_path=args.library_path,
            title=args.title,
            doc_id=args.doc_id,
            files=args.files,
        )
        print(f"✓ 문헌을 등록했습니다: {doc_path}")
    except (FileExistsError, FileNotFoundError, ValueError) as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_list_documents(args):
    """서고의 문헌 목록을 출력한다."""
    try:
        info = get_library_info(args.library_path)
        docs = list_documents(args.library_path)

        print(f"서고: {info.get('name', '?')}")
        print(f"문헌 수: {len(docs)}")
        print()

        if not docs:
            print("  (등록된 문헌이 없습니다)")
            return

        for doc in docs:
            doc_id = doc.get("document_id", "?")
            title = doc.get("title", "?")
            status = doc.get("completeness_status", "?")
            parts_count = len(doc.get("parts", []))
            print(f"  [{doc_id}] {title}  — {status}, {parts_count}개 파일")

    except FileNotFoundError as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="classical-text-browser",
        description="고전서지 통합 브라우저 — CLI 도구",
    )
    subparsers = parser.add_subparsers(dest="command")

    # init-library
    p_init = subparsers.add_parser(
        "init-library",
        help="서고 디렉토리 구조를 생성한다",
    )
    p_init.add_argument("path", help="서고를 생성할 경로")
    p_init.set_defaults(func=cmd_init_library)

    # add-document
    p_add = subparsers.add_parser(
        "add-document",
        help="문헌을 서고에 등록한다",
    )
    p_add.add_argument("library_path", help="서고 경로")
    p_add.add_argument("--title", required=True, help="문헌 제목 (예: 蒙求)")
    p_add.add_argument("--doc-id", required=True, help="문헌 ID (예: monggu)")
    p_add.add_argument("--files", nargs="*", help="L1_source에 복사할 파일 경로")
    p_add.set_defaults(func=cmd_add_document)

    # list-documents
    p_list = subparsers.add_parser(
        "list-documents",
        help="서고의 문헌 목록을 출력한다",
    )
    p_list.add_argument("library_path", help="서고 경로")
    p_list.set_defaults(func=cmd_list_documents)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
