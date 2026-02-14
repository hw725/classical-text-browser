"""웹 앱 서버.

FastAPI 기반. 서고 데이터를 API로 제공하고 정적 파일(HTML/CSS/JS)을 서빙한다.
D-001: 이 플랫폼의 주 인터페이스는 GUI이며, CLI는 보조 도구다.

API 엔드포인트:
    GET /            → index.html (워크스페이스)
    GET /api/library → 서고 정보
    GET /api/documents → 문헌 목록
    GET /api/documents/{doc_id} → 특정 문헌 정보
"""

import sys
from pathlib import Path

# src/ 디렉토리를 Python 경로에 추가
_src_dir = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.library import get_library_info, list_documents
from core.document import get_document_info, list_pages


app = FastAPI(
    title="고전 텍스트 디지털 서고 플랫폼",
    description="사람과 LLM이 함께 고전 텍스트를 읽고 번역하고 연구하는 통합 작업 환경",
    version="0.1.0",
)

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
