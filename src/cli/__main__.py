"""CLI 도구 — 고전서지 통합 브라우저.

사용법:
    python -m cli init-library <path>
    python -m cli add-document <library_path> --title <제목> --doc-id <id> [--files ...]
    python -m cli list-documents <library_path>

pip install -e . 후 실행하거나, src/ 디렉토리에서 실행한다.
"""

import argparse
import os
import sys
from pathlib import Path

# src/ 디렉토리를 Python 경로에 추가하여 pip install 없이도 실행 가능하게 한다.
# (pip install -e . 후에는 이 조작이 불필요하지만, 해가 되지 않는다.)
_src_dir = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from core.document import add_document  # noqa: E402
from core.library import get_library_info, init_library, list_documents  # noqa: E402


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


def _default_workspace() -> Path:
    """CLI가 쓸 기본 작업 서고 경로.

    왜 홈 아래인가: 논문 파일 옆에 서고를 만들면 논문 폴더가 지저분해지고,
    서지 관리 도구가 그 폴더를 훑을 때 걸린다. 한 곳에 모아 두면 나중에
    GUI로 열 때도 «어디였더라»를 묻지 않아도 된다.
    """
    return Path.home() / "Documents" / "고전서지서고_추출"


def cmd_ocr(args):
    """파일 하나(또는 폴더 하나)를 OCR 해서 텍스트 레이어 PDF로 만든다.

    embed-folder와 같은 일을 하지만 **묻는 것을 최소로 줄인 진입점**이다.
    서고를 미리 만들 필요도, 폴더 구조를 맞출 필요도 없다.

        uv run python -m cli ocr 논문.pdf

    왜 따로 두는가:
        embed-folder는 «주제 폴더로 정리된 수백 편»을 전제로 한다. 폴더 경로와
        --library를 모두 요구하고 기본이 미리보기다. 한 편만 처리하려는
        사람에게는 그 전제가 전부 장벽이다. «논문 하나 넣고 텍스트 레이어
        PDF 받기»가 한 줄로 끝나야 한다.
    """
    import shutil
    import tempfile

    from cli.embed_folder import embed_folder

    source = Path(args.target).expanduser().resolve()
    if not source.exists():
        print(f"오류: 찾을 수 없습니다 — {source}", file=sys.stderr)
        sys.exit(1)

    library = Path(args.library).expanduser() if args.library else _default_workspace()
    library.mkdir(parents=True, exist_ok=True)

    # embed_folder는 «주제 폴더/파일» 구조를 훑는다. 파일 하나를 받은 경우
    # 임시로 그 구조를 만들어 준다 — 원본은 복사하지 않고 그대로 쓰기 위해
    # 원본이 이미 «폴더 안의 파일»이면 그 부모를 쓴다.
    staging = None
    if source.is_dir():
        root = source
    else:
        staging = Path(tempfile.mkdtemp(prefix="ctb_ocr_"))
        (staging / "기타").mkdir()
        # 복사가 아니라 링크를 걸면 원본을 아카이브로 «옮기는» 단계에서
        # 원본이 사라진다. 여기서는 복사본을 쓰고, 산출물만 원본 옆에 놓는다.
        shutil.copy2(source, staging / "기타" / source.name)
        root = staging

    # 엔진은 registry.auto_register()가 인자 없이 만든다. 생성 전에 환경변수로
    # 의사를 남겨 두면 PaddleOcrEngine.__init__이 읽어 간다.
    if args.paddle_lang:
        os.environ["CTB_PADDLE_LANG"] = args.paddle_lang
    if args.paddle_device:
        os.environ["CTB_PADDLE_DEVICE"] = args.paddle_device

    try:
        report = embed_folder(
            root,
            library,
            engine_id=args.engine,
            dry_run=not args.execute,
            replace_original=True,
            keep_workspace=True,  # 나중에 GUI로 검수할 수 있어야 한다
            use_line_detection=not args.no_line_detection,
            page_sleep=args.sleep,
        )

        if not args.execute:
            # 미리보기 안내는 embed_folder가 이미 출력했다. 두 번 찍지 않는다.
            return

        # 파일 하나를 받은 경우, 산출물을 원본 옆에 놓는다.
        if staging is not None and report.processed:
            made = staging / "기타" / source.name
            if made.exists():
                out = args.output and Path(args.output).expanduser()
                if not out:
                    out = source.with_name(f"{source.stem}_text{source.suffix}")
                shutil.copy2(made, out)
                print(f"\n산출물: {out}")

        print(
            f"\n처리 {report.processed}편 / 실패 {report.failed}편"
            f"\n작업 서고: {library}"
            "\n  결과가 이상하면 GUI를 켜서 이 서고를 열고 쪽별 검수를 하세요."
        )
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def cmd_embed_folder(args):
    """논문 폴더의 스캔본에 텍스트 레이어를 입힌다."""
    from cli.embed_folder import embed_folder

    report = embed_folder(
        Path(args.folder),
        Path(args.library),
        engine_id=args.engine,
        dry_run=not args.execute,
        limit=args.limit,
        max_pages=args.max_pages,
        only=args.only,
        replace_original=not args.keep_original_in_place,
        archive_root=Path(args.archive_dir) if args.archive_dir else None,
        keep_workspace=not args.drop_workspace,
        page_sleep=args.sleep,
        paper_sleep=args.sleep_between,
        use_line_detection=not args.no_line_detection,
    )

    if args.execute:
        print(
            f"\n=== 결과 ===\n"
            f"  처리 완료 {report.processed}편 / 실패 {report.failed}편 "
            f"/ 이미 끝남 {report.skipped_done}편\n"
            f"  걸린 시간 {report.elapsed_sec / 60:.1f}분"
        )
        if report.failures:
            print("\n  실패 목록:")
            for f in report.failures[:10]:
                print(f"    {Path(f['source']).name[:60]} — {f.get('error', '')[:70]}")


def _force_utf8_output() -> None:
    """표준 출력을 UTF-8로 맞춘다.

    왜 필요한가:
        한국어 Windows의 콘솔 기본 인코딩은 cp949다. 이 CLI의 안내문에는
        «—»(em dash)와 «»» 같은 글자가 들어 있는데 cp949로는 인코딩되지 않아
        **`--help`가 UnicodeEncodeError로 죽는다**(실측 2026-07-26).
        도움말조차 볼 수 없으면 CLI를 쓸 수 없다.

        errors="replace"를 함께 주는 이유: 재설정이 통하지 않는 환경(파이프,
        일부 터미널)에서도 안내가 «죽는» 대신 «일부 글자가 ?로 보이는» 쪽으로
        끝나게 하기 위함이다. 안내문을 못 읽는 것보다 낫다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # 재설정을 지원하지 않는 스트림이면 그대로 둔다.
            pass


def main():
    _force_utf8_output()

    parser = argparse.ArgumentParser(
        # 설치하면 `ctb`로 부를 수 있다([project.scripts]).
        # `python -m cli`로도 도므로 도움말에는 짧은 쪽을 적는다.
        prog="ctb",
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

    # embed-folder
    p_embed = subparsers.add_parser(
        "embed-folder",
        help="논문 폴더의 스캔본만 골라 텍스트 레이어를 입힌다",
        description=(
            "폴더를 훑어 텍스트 레이어가 없는 PDF만 골라 OCR한 뒤, "
            "원본은 아카이브로 옮기고 텍스트 레이어 PDF를 원래 자리에 원래 이름으로 놓는다. "
            "기본은 미리보기(dry-run)이며 --execute를 붙여야 실제로 바꾼다."
        ),
    )
    p_embed.add_argument("folder", help="논문 폴더 경로")
    p_embed.add_argument(
        "--library",
        required=True,
        help="작업 서고 경로 (없으면 새로 만든다). OCR 이력이 여기 남는다.",
    )
    p_embed.add_argument(
        "--engine",
        default="llm_vision",
        help="OCR 엔진 (기본: llm_vision — 한글이 되는 유일한 기본 선택). "
        "ndlocr/ndlkotenocr 계열은 한글을 인식하지 못한다.",
    )
    p_embed.add_argument(
        "--execute",
        action="store_true",
        help="실제로 실행한다 (없으면 계획만 보여 준다)",
    )
    p_embed.add_argument("--limit", type=int, default=None, help="처리할 최대 편수 (시범 실행용)")
    p_embed.add_argument(
        "--only",
        default=None,
        help="파일명에 이 문자열이 든 논문만 처리한다 (특정 편 시범 실행용)",
    )
    p_embed.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="이 쪽수를 넘는 문헌은 건너뛴다 (큰 것을 나중으로 미룰 때)",
    )
    p_embed.add_argument(
        "--keep-original-in-place",
        action="store_true",
        help="원본을 그 자리에 두고 입히기만 한다 (자리바꿈·아카이브 없음)",
    )
    p_embed.add_argument(
        "--archive-dir",
        default=None,
        help="원본 아카이브 위치 (기본: <논문폴더>/_scan_originals)",
    )
    p_embed.add_argument(
        "--drop-workspace",
        action="store_true",
        help="처리가 끝나면 작업 서고의 복사본을 지운다. "
        "**지우면 나중에 GUI로 검수할 수 없다** — OCR을 처음부터 다시 돌려야 하고 "
        "비용을 두 번 낸다. 디스크를 아껴야 할 때만 쓴다.",
    )
    # 예전 이름. 기본값이 뒤집혔으므로 이제 아무 일도 하지 않지만,
    # 이 옵션을 쓰던 스크립트가 오류로 멈추지 않게 받아만 둔다.
    p_embed.add_argument(
        "--keep-workspace",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    p_embed.add_argument(
        "--no-line-detection",
        action="store_true",
        help="줄 위치 검출을 끈다. 켜져 있으면 텍스트가 원본 글자 자리에 놓이지만 "
        "쪽당 약 8초가 더 든다. 끄면 빨라지는 대신 검색 형광이 제자리에 뜨지 않는다. "
        "(PaddleOCR가 없으면 어차피 꺼진 것과 같다)",
    )
    p_embed.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="쪽 사이 대기 시간(초). LLM 사용량 한도를 아낄 때 쓴다.",
    )
    p_embed.add_argument(
        "--sleep-between",
        type=float,
        default=0.0,
        help="논문 사이 대기 시간(초)",
    )
    p_embed.set_defaults(func=cmd_embed_folder)

    # ocr — 한 줄 진입점 (파일 하나 또는 폴더 하나)
    p_ocr = subparsers.add_parser(
        "ocr",
        help="논문 PDF에 텍스트 레이어를 입힌다 (파일 하나도 가능)",
        description="스캔본 PDF를 OCR 해서 검색 가능한 PDF로 만든다. 서고를 미리 만들 필요가 없다.",
    )
    p_ocr.add_argument("target", help="PDF 파일 또는 폴더 경로")
    p_ocr.add_argument(
        "--execute",
        action="store_true",
        help="실제로 실행한다. 없으면 무엇을 할지 보여 주기만 한다.",
    )
    p_ocr.add_argument(
        "-o",
        "--output",
        default=None,
        help="산출물 경로 (기본: 원본 옆에 <이름>_text.pdf)",
    )
    p_ocr.add_argument(
        "--library",
        default=None,
        help=f"작업 서고 경로 (기본: {_default_workspace()}). "
        "OCR 결과가 여기 남아 나중에 GUI로 검수할 수 있다.",
    )
    p_ocr.add_argument(
        "--engine",
        default="llm_vision",
        help="OCR 엔진 (기본: llm_vision — 한글 문헌은 바꾸지 마세요)",
    )
    # PaddleOCR 세부 설정. 엔진이 registry에서 인자 없이 생성되므로 환경변수로 넘긴다.
    p_ocr.add_argument(
        "--paddle-lang",
        default=None,
        help="PaddleOCR 언어 모델 (korean/chinese_cht/ch/japan/en). "
        "국한문 혼용 한국 논문은 korean. 기본값 ch는 한글을 읽지 못한다.",
    )
    p_ocr.add_argument(
        "--paddle-device",
        default=None,
        choices=["auto", "cpu", "gpu"],
        help="PaddleOCR 연산 장치 (기본: auto — CUDA 빌드이고 GPU가 보일 때만 GPU). "
        "GPU가 없으면 auto가 알아서 cpu로 간다.",
    )
    p_ocr.add_argument(
        "--no-line-detection",
        action="store_true",
        help="줄 위치 검출을 끈다. 쪽당 약 8초를 아끼는 대신 검색 형광이 제자리에 뜨지 않는다.",
    )
    p_ocr.add_argument("--sleep", type=float, default=0.0, help="쪽 사이 대기 시간(초)")
    p_ocr.set_defaults(func=cmd_ocr)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
