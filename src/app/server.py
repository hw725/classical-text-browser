"""웹 앱 서버.

FastAPI 기반. 서고 데이터를 API로 제공하고 정적 파일(HTML/CSS/JS)을 서빙한다.
D-001: 이 플랫폼의 주 인터페이스는 GUI이며, CLI는 보조 도구다.

API 엔드포인트:
    GET /            → index.html (워크스페이스)
    GET /api/library → 서고 정보
    GET /api/documents → 문헌 목록
    GET /api/documents/{doc_id} → 특정 문헌 정보
    GET /api/documents/{doc_id}/pdf/{part_id} → PDF 파일 서빙
    GET /api/documents/{doc_id}/pages/{page_num}/text → 페이지 텍스트 조회
    PUT /api/documents/{doc_id}/pages/{page_num}/text → 페이지 텍스트 저장
"""

import sys
from pathlib import Path

# src/ 디렉토리를 Python 경로에 추가
_src_dir = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.library import get_library_info, list_documents
from core.document import (
    get_document_info,
    get_page_layout,
    get_page_text,
    get_pdf_path,
    list_pages,
    save_page_layout,
    save_page_text,
)


app = FastAPI(
    title="고전 텍스트 디지털 서고 플랫폼",
    description="사람과 LLM이 함께 고전 텍스트를 읽고 번역하고 연구하는 통합 작업 환경",
    version="0.2.0",
)


class TextSaveRequest(BaseModel):
    """텍스트 저장 요청 본문. PUT /api/documents/{doc_id}/pages/{page_num}/text 에서 사용."""
    text: str


class LayoutSaveRequest(BaseModel):
    """레이아웃 저장 요청 본문. PUT /api/documents/{doc_id}/pages/{page_num}/layout 에서 사용.

    layout_page.schema.json 형식의 JSON을 그대로 전달받는다.
    """
    part_id: str
    page_number: int
    image_width: int | None = None
    image_height: int | None = None
    analysis_method: str | None = None
    blocks: list = []

# 서고 경로 — serve 명령에서 설정된다
_library_path: Path | None = None

# 정적 파일 디렉토리
_static_dir = Path(__file__).parent / "static"


def configure(library_path: str | Path) -> FastAPI:
    """서고 경로를 설정하고 정적 파일 마운트를 수행한다.

    목적: 서버 시작 전에 서고 경로를 지정한다.
    입력: library_path — 서고 디렉토리 경로.
    출력: 설정된 FastAPI 앱 인스턴스.
    """
    global _library_path
    _library_path = Path(library_path).resolve()

    # 정적 파일 서빙 (CSS, JS 등)
    # mount는 한 번만 — 이미 마운트된 경우 스킵
    routes_paths = [r.path for r in app.routes]
    if "/static" not in routes_paths:
        app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

    return app


# --- 페이지 라우트 ---

@app.get("/")
async def index():
    """메인 워크스페이스 페이지를 반환한다."""
    return FileResponse(str(_static_dir / "index.html"))


# --- API 라우트 ---

@app.get("/api/library")
async def api_library():
    """서고 정보를 반환한다."""
    if _library_path is None:
        return JSONResponse(
            {"error": "서고가 설정되지 않았습니다."},
            status_code=500,
        )
    try:
        return get_library_info(_library_path)
    except FileNotFoundError:
        return JSONResponse(
            {"error": f"서고를 찾을 수 없습니다: {_library_path}"},
            status_code=404,
        )


@app.get("/api/documents")
async def api_documents():
    """서고의 문헌 목록을 반환한다."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    return list_documents(_library_path)


@app.get("/api/documents/{doc_id}")
async def api_document(doc_id: str):
    """특정 문헌의 정보를 반환한다 (manifest + pages)."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    try:
        info = get_document_info(doc_path)
        info["pages"] = list_pages(doc_path)
        return info
    except FileNotFoundError:
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )


@app.get("/api/documents/{doc_id}/pdf/{part_id}")
async def api_document_pdf(doc_id: str, part_id: str):
    """문헌의 특정 권(part) PDF 파일을 반환한다.

    목적: 좌측 PDF 뷰어에서 원본 PDF를 렌더링하기 위해 파일을 서빙한다.
    입력:
        doc_id — 문헌 ID.
        part_id — 권 식별자 (예: "vol1").
    출력: PDF 파일 (application/pdf).
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    try:
        pdf_path = get_pdf_path(doc_path, part_id)
        return FileResponse(
            str(pdf_path),
            media_type="application/pdf",
            filename=pdf_path.name,
        )
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.get("/api/documents/{doc_id}/pages/{page_num}/text")
async def api_page_text(
    doc_id: str,
    page_num: int,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """특정 페이지의 텍스트를 반환한다.

    목적: 우측 텍스트 에디터에 페이지 텍스트를 로드하기 위해 사용한다.
    입력:
        doc_id — 문헌 ID.
        page_num — 페이지 번호 (1부터 시작).
        part_id — 쿼리 파라미터, 권 식별자.
    출력: {document_id, part_id, page, text, file_path, exists}.
          파일이 없으면 text=""과 exists=false를 반환한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    try:
        return get_page_text(doc_path, part_id, page_num)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.put("/api/documents/{doc_id}/pages/{page_num}/text")
async def api_save_page_text(
    doc_id: str,
    page_num: int,
    body: TextSaveRequest,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """특정 페이지의 텍스트를 저장한다.

    목적: 우측 텍스트 에디터에서 입력한 텍스트를 L4_text/pages/에 기록한다.
    입력:
        doc_id — 문헌 ID.
        page_num — 페이지 번호.
        part_id — 쿼리 파라미터, 권 식별자.
        body — {text: "저장할 텍스트"}.
    출력: {status: "saved", file_path, size}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    try:
        return save_page_text(doc_path, part_id, page_num, body.text)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


# --- 레이아웃 API (Phase 4) ---


@app.get("/api/documents/{doc_id}/pages/{page_num}/layout")
async def api_page_layout(
    doc_id: str,
    page_num: int,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """특정 페이지의 레이아웃(LayoutBlock 목록)을 반환한다.

    목적: 레이아웃 편집기에서 기존 LayoutBlock을 로드하기 위해 사용한다.
    입력:
        doc_id — 문헌 ID.
        page_num — 페이지 번호 (1부터 시작).
        part_id — 쿼리 파라미터, 권 식별자.
    출력: layout_page.schema.json 형식 + _meta (document_id, file_path, exists).
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    try:
        return get_page_layout(doc_path, part_id, page_num)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.put("/api/documents/{doc_id}/pages/{page_num}/layout")
async def api_save_page_layout(
    doc_id: str,
    page_num: int,
    body: LayoutSaveRequest,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """특정 페이지의 레이아웃을 저장한다.

    목적: 레이아웃 편집기에서 작성한 LayoutBlock 데이터를 L3_layout/에 기록한다.
    입력:
        doc_id — 문헌 ID.
        page_num — 페이지 번호.
        part_id — 쿼리 파라미터, 권 식별자.
        body — layout_page.schema.json 형식의 레이아웃 데이터.
    출력: {status: "saved", file_path, block_count}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    layout_data = body.model_dump()
    try:
        return save_page_layout(doc_path, part_id, page_num, layout_data)
    except Exception as e:
        # jsonschema.ValidationError 등
        return JSONResponse(
            {"error": f"레이아웃 저장 실패: {e}"},
            status_code=400,
        )


@app.get("/api/resources/block_types")
async def api_block_types():
    """블록 타입 어휘 목록을 반환한다.

    목적: 레이아웃 편집기에서 block_type 드롭다운을 채우기 위해 사용한다.
    출력: resources/block_types.json의 내용.
    """
    block_types_path = (
        Path(__file__).resolve().parent.parent.parent
        / "resources" / "block_types.json"
    )
    if not block_types_path.exists():
        return JSONResponse(
            {"error": "block_types.json을 찾을 수 없습니다."},
            status_code=404,
        )
    import json
    data = json.loads(block_types_path.read_text(encoding="utf-8"))
    return data
