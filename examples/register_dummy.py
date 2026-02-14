"""더미 문헌을 서고에 등록하는 스크립트.

목적: generate_dummy_pdf.py로 생성한 더미 PDF를 테스트 서고에 등록한다.
      기존 core.library, core.document 모듈을 활용한다.

사용법:
    uv run python examples/register_dummy.py

동작:
    1. examples/test_library/ 에 서고를 초기화한다 (이미 존재하면 스킵).
    2. dummy_shishuo.pdf를 문헌 "世說新語 (더미)"로 등록한다.

사전 조건:
    examples/dummy_shishuo.pdf 가 존재해야 한다.
    → uv run python examples/generate_dummy_pdf.py 를 먼저 실행하세요.
"""

import sys
from pathlib import Path

# src/ 디렉토리를 Python 경로에 추가
_src_dir = str(Path(__file__).resolve().parent.parent / "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from core.document import add_document
from core.library import init_library

LIBRARY_PATH = Path(__file__).parent / "test_library"
PDF_PATH = Path(__file__).parent / "dummy_shishuo.pdf"


def main() -> None:
    """테스트 서고를 초기화하고 더미 문헌을 등록한다."""
    # PDF 존재 확인
    if not PDF_PATH.exists():
        print(f"오류: 더미 PDF를 찾을 수 없습니다: {PDF_PATH}")
        print("→ 해결: 먼저 uv run python examples/generate_dummy_pdf.py 를 실행하세요.")
        sys.exit(1)

    # 1. 서고 초기화
    if not (LIBRARY_PATH / "library_manifest.json").exists():
        init_library(LIBRARY_PATH)
        print(f"서고 초기화 완료: {LIBRARY_PATH}")
    else:
        print(f"서고 이미 존재: {LIBRARY_PATH}")

    # 2. 문헌 등록
    doc_path = LIBRARY_PATH / "documents" / "dummy_shishuo"
    if doc_path.exists():
        print(f"문헌 이미 등록됨: dummy_shishuo")
        print("→ 재등록하려면 먼저 기존 문헌 디렉토리를 삭제하세요.")
        return

    add_document(
        library_path=LIBRARY_PATH,
        title="世說新語 (더미)",
        doc_id="dummy_shishuo",
        files=[PDF_PATH],
    )
    print(f"문헌 등록 완료: dummy_shishuo")
    print(f"  경로: {doc_path}")
    print(f"  서고: {LIBRARY_PATH}")
    print()
    print("서버 시작:")
    print(f"  uv run python -m app serve --library {LIBRARY_PATH}")


if __name__ == "__main__":
    main()
