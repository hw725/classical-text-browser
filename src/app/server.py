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
    GET /api/documents/{doc_id}/bibliography → 서지정보 조회
    PUT /api/documents/{doc_id}/bibliography → 서지정보 저장
    GET /api/documents/{doc_id}/pages/{page_num}/corrections → 교정 기록 조회
    PUT /api/documents/{doc_id}/pages/{page_num}/corrections → 교정 기록 저장 (자동 git commit)
    GET /api/documents/{doc_id}/git/log → git 커밋 이력
    GET /api/documents/{doc_id}/git/diff/{commit_hash} → 커밋 diff
    GET /api/parsers → 등록된 파서 목록
    POST /api/parsers/{parser_id}/search → 외부 소스 검색
    POST /api/parsers/{parser_id}/map → 검색 결과를 bibliography 형식으로 매핑

    --- Phase 7: 해석 저장소 API ---
    POST /api/interpretations → 해석 저장소 생성
    GET  /api/interpretations → 해석 저장소 목록
    GET  /api/interpretations/{interp_id} → 해석 저장소 상세
    GET  /api/interpretations/{interp_id}/dependency → 의존 변경 확인
    POST /api/interpretations/{interp_id}/dependency/acknowledge → 변경 인지
    POST /api/interpretations/{interp_id}/dependency/update-base → 기반 업데이트
    GET  /api/interpretations/{interp_id}/layers/{layer}/{sub_type}/pages/{page_num} → 층 내용 조회
    PUT  /api/interpretations/{interp_id}/layers/{layer}/{sub_type}/pages/{page_num} → 층 내용 저장
    GET  /api/interpretations/{interp_id}/git/log → git 이력

    --- Phase 10: URL → 문헌 자동 생성 API ---
    POST /api/documents/preview-from-url → URL에서 서지정보 + 에셋 미리보기
    POST /api/documents/create-from-url → URL에서 문헌 자동 생성

    --- Phase 10-2: LLM 4단 폴백 아키텍처 API ---
    GET  /api/llm/status → 각 provider 가용 상태
    GET  /api/llm/models → GUI 드롭다운용 모델 목록
    GET  /api/llm/usage  → 이번 달 사용량 요약
    POST /api/llm/analyze-layout/{doc_id}/{page} → 레이아웃 분석 (Draft 반환)
    POST /api/llm/compare-layout/{doc_id}/{page} → 레이아웃 분석 비교
    POST /api/llm/drafts/{draft_id}/review → Draft 검토 (accept/modify/reject)

    --- Phase 10-1: OCR 엔진 연동 API ---
    GET  /api/ocr/engines → 등록된 OCR 엔진 목록 + 사용 가능 여부
    POST /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr → OCR 실행
    GET  /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr → OCR 결과 조회
    POST /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr/{block_id} → 단일 블록 재실행

    --- Phase 10-3: 정렬 엔진 API ---
    POST /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/alignment → 대조 실행
    GET  /api/alignment/variant-dict → 이체자 사전 조회
    POST /api/alignment/variant-dict → 이체자 쌍 추가

    --- Phase 11-1: L5 표점/현토 API ---
    GET  /api/interpretations/{interp_id}/pages/{page}/punctuation → 표점 조회
    PUT  /api/interpretations/{interp_id}/pages/{page}/punctuation → 표점 저장
    POST /api/interpretations/{interp_id}/pages/{page}/punctuation/{block_id}/marks → 표점 추가
    DELETE /api/interpretations/{interp_id}/pages/{page}/punctuation/{block_id}/marks/{id} → 표점 삭제
    GET  /api/interpretations/{interp_id}/pages/{page}/punctuation/{block_id}/preview → 표점 미리보기
    GET  /api/interpretations/{interp_id}/pages/{page}/hyeonto → 현토 조회
    PUT  /api/interpretations/{interp_id}/pages/{page}/hyeonto → 현토 저장
    POST /api/interpretations/{interp_id}/pages/{page}/hyeonto/{block_id}/annotations → 현토 추가
    DELETE /api/interpretations/{interp_id}/pages/{page}/hyeonto/{block_id}/annotations/{id} → 현토 삭제
    GET  /api/interpretations/{interp_id}/pages/{page}/hyeonto/{block_id}/preview → 현토 미리보기

    --- Phase 8: 코어 스키마 엔티티 API ---
    POST /api/interpretations/{interp_id}/entities → 엔티티 생성
    GET  /api/interpretations/{interp_id}/entities/{entity_type} → 유형별 목록
    GET  /api/interpretations/{interp_id}/entities/{entity_type}/{entity_id} → 단일 조회
    PUT  /api/interpretations/{interp_id}/entities/{entity_type}/{entity_id} → 엔티티 수정
    GET  /api/interpretations/{interp_id}/entities/page/{page_num} → 페이지별 엔티티
    POST /api/interpretations/{interp_id}/entities/text_block/from-source → TextBlock 생성
    POST /api/interpretations/{interp_id}/entities/work/auto-create → Work 자동 생성
    POST /api/interpretations/{interp_id}/entities/tags/{tag_id}/promote → Tag→Concept 승격
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

from core.library import get_library_info, list_documents, list_interpretations
from core.document import (
    create_document_from_url,
    get_bibliography,
    get_document_info,
    get_git_diff,
    get_git_log,
    get_page_corrections,
    get_page_layout,
    get_page_text,
    get_pdf_path,
    git_commit_document,
    list_pages,
    save_bibliography,
    save_page_corrections,
    save_page_layout,
    save_page_text,
)
from core.interpretation import (
    acknowledge_changes,
    check_dependency,
    create_interpretation,
    get_interp_git_log,
    get_interpretation_info,
    get_layer_content,
    git_commit_interpretation,
    save_layer_content,
    update_base,
)
from core.entity import (
    auto_create_work,
    create_entity,
    create_textblock_from_source,
    get_entity,
    list_entities,
    list_entities_for_page,
    promote_tag_to_concept,
    update_entity,
)
from core.punctuation import (
    add_mark,
    load_punctuation,
    remove_mark,
    render_punctuated_text,
    save_punctuation,
    split_sentences,
)
from core.hyeonto import (
    add_annotation,
    load_hyeonto,
    remove_annotation,
    render_hyeonto_text,
    save_hyeonto,
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


# =========================================
#   Phase 10: URL → 문헌 자동 생성 API
# =========================================


def _suggest_doc_id(title: str) -> str:
    """서지 제목에서 문헌 ID 후보를 자동 생성한다.

    목적: 사용자가 doc_id를 직접 입력하지 않아도 되도록 서지 제목에서
          영문 소문자/숫자/밑줄로 구성된 ID를 자동으로 만든다.
    입력: title — 서지 제목 (한자/가나/한글 포함 가능).
    출력: doc_id 후보 문자열 (최대 64자, ^[a-z][a-z0-9_]*$ 형식).

    왜 ASCII만 사용하는가:
        doc_id는 파일시스템 디렉토리명으로 사용되므로,
        manifest.schema.json 규칙에 따라 영문 소문자+숫자+밑줄만 허용한다.
        한자 제목인 경우 사용자가 직접 입력하도록 빈 제안값을 반환한다.
    """
    # ASCII 영문숫자와 공백/밑줄/하이픈만 추출
    cleaned = []
    for ch in title:
        if ch.isascii() and ch.isalnum():
            cleaned.append(ch.lower())
        elif ch in " _-":
            cleaned.append("_")
        # 비 ASCII 문자(한자, 가나, 한글 등)는 건너뜀
    result = "".join(cleaned).strip("_")
    # 연속 밑줄 제거
    while "__" in result:
        result = result.replace("__", "_")
    # 영문 소문자로 시작하지 않으면 접두어 추가
    if result and not result[0].isalpha():
        result = "doc_" + result
    # 64자 제한
    return result[:64] if result else ""


class PreviewFromUrlRequest(BaseModel):
    """URL에서 서지정보 + 에셋 목록 미리보기 요청."""
    url: str


@app.post("/api/documents/preview-from-url")
async def api_preview_from_url(body: PreviewFromUrlRequest):
    """URL에서 서지정보와 다운로드 가능한 에셋 목록을 미리보기한다.

    목적: 문헌 생성 전에 서지정보와 이미지 목록을 확인한다 (2단계 워크플로우의 1단계).
    입력: { "url": "https://www.digital.archives.go.jp/file/1078619.html" }
    출력: {
        "parser_id": "japan_national_archives",
        "bibliography": {...},
        "assets": [{"id": "...", "label": "...", "page_count": 77}, ...],
        "suggested_doc_id": "蒙求"
    }
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    import parsers as _parsers_mod  # noqa: F401
    from parsers.base import detect_parser_from_url, get_parser, get_supported_sources

    url = body.url.strip()
    if not url:
        return JSONResponse({"error": "URL이 비어있습니다."}, status_code=400)

    # 1. 파서 판별
    parser_id = detect_parser_from_url(url)
    if parser_id is None:
        sources = get_supported_sources()
        return JSONResponse(
            {
                "error": "이 URL은 자동 인식할 수 없습니다.",
                "supported_sources": sources,
            },
            status_code=400,
        )

    # 2. fetch + 매핑
    try:
        fetcher, mapper = get_parser(parser_id)
        raw_data = await fetcher.fetch_by_url(url)
        bibliography = mapper.map_to_bibliography(raw_data)
    except Exception as e:
        return JSONResponse(
            {"error": f"서지정보 가져오기 실패: {e}"},
            status_code=502,
        )

    # 3. 에셋 목록 조회 (지원하는 파서만)
    assets = []
    if fetcher.supports_asset_download:
        try:
            assets = await fetcher.list_assets(raw_data)
        except Exception as e:
            # 에셋 목록 실패는 치명적이지 않음 — 경고만
            assets = []
            bibliography.setdefault("_warnings", []).append(
                f"에셋 목록 조회 실패: {e}"
            )

    # 4. doc_id 후보 생성
    title = bibliography.get("title", "")
    suggested_doc_id = _suggest_doc_id(title) if title else "untitled"

    return {
        "parser_id": parser_id,
        "bibliography": bibliography,
        "assets": assets,
        "suggested_doc_id": suggested_doc_id,
    }


class CreateFromUrlRequest(BaseModel):
    """URL에서 문헌 자동 생성 요청."""
    url: str
    doc_id: str
    title: str | None = None
    selected_assets: list[str] | None = None


@app.post("/api/documents/create-from-url")
async def api_create_from_url(body: CreateFromUrlRequest):
    """URL에서 서지정보와 이미지를 가져와 문헌을 자동 생성한다.

    목적: URL 하나로 서지정보 추출 + 이미지 다운로드 + 문서 폴더 생성을 한 번에 수행.
          2단계 워크플로우의 2단계 (미리보기 후 실행).
    입력: {
        "url": "https://...",
        "doc_id": "monggu",
        "title": "蒙求",
        "selected_assets": ["M2023...156"]  // null이면 전체 다운로드
    }
    출력: create_document_from_url()의 결과.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    url = body.url.strip()
    doc_id = body.doc_id.strip()
    if not url:
        return JSONResponse({"error": "URL이 비어있습니다."}, status_code=400)
    if not doc_id:
        return JSONResponse({"error": "doc_id가 비어있습니다."}, status_code=400)

    try:
        result = await create_document_from_url(
            library_path=_library_path,
            url=url,
            doc_id=doc_id,
            title=body.title,
            selected_assets=body.selected_assets,
        )
        return result
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except FileExistsError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except Exception as e:
        return JSONResponse(
            {"error": f"문헌 생성 실패: {e}"},
            status_code=502,
        )


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


# --- 교정 API (Phase 6) ---


class CorrectionItem(BaseModel):
    """개별 교정 항목. corrections.schema.json의 Correction 정의와 대응."""
    page: int | None = None
    block_id: str | None = None
    line: int | None = None
    char_index: int | None = None
    type: str
    original_ocr: str
    corrected: str
    common_reading: str | None = None
    corrected_by: str | None = None
    confidence: float | None = None
    note: str | None = None


class CorrectionsSaveRequest(BaseModel):
    """교정 저장 요청 본문. corrections.schema.json 형식."""
    part_id: str | None = None
    corrections: list[CorrectionItem] = []


@app.get("/api/documents/{doc_id}/pages/{page_num}/corrections")
async def api_page_corrections(
    doc_id: str,
    page_num: int,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """특정 페이지의 교정 기록을 반환한다.

    목적: 교정 편집기에서 기존 교정 기록을 로드하기 위해 사용한다.
    입력:
        doc_id — 문헌 ID.
        page_num — 페이지 번호 (1부터 시작).
        part_id — 쿼리 파라미터, 권 식별자.
    출력: corrections.schema.json 형식 + _meta.
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
        return get_page_corrections(doc_path, part_id, page_num)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.put("/api/documents/{doc_id}/pages/{page_num}/corrections")
async def api_save_page_corrections(
    doc_id: str,
    page_num: int,
    body: CorrectionsSaveRequest,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """특정 페이지의 교정 기록을 저장하고 자동으로 git commit한다.

    목적: 교정 편집기에서 작성한 교정 데이터를 L4_text/corrections/에 기록하고,
          교정 내역을 요약한 커밋 메시지로 자동 commit한다.
    입력:
        doc_id — 문헌 ID.
        page_num — 페이지 번호.
        part_id — 쿼리 파라미터, 권 식별자.
        body — corrections.schema.json 형식의 교정 데이터.
    출력: {status, file_path, correction_count, git}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    corrections_data = body.model_dump()
    try:
        save_result = save_page_corrections(doc_path, part_id, page_num, corrections_data)
    except Exception as e:
        return JSONResponse(
            {"error": f"교정 저장 실패: {e}"},
            status_code=400,
        )

    # 교정 유형별 건수 집계 → git commit 메시지 생성
    from collections import Counter
    type_counts = Counter(c["type"] for c in corrections_data.get("corrections", []))
    summary_parts = [f"{t} {n}건" for t, n in type_counts.items()]
    summary = ", ".join(summary_parts) if summary_parts else "없음"
    commit_msg = f"L4: page {page_num:03d} 교정 — {summary}"

    git_result = git_commit_document(doc_path, commit_msg)
    save_result["git"] = git_result

    return save_result


# --- Git API (Phase 6) ---


@app.get("/api/documents/{doc_id}/git/log")
async def api_git_log(
    doc_id: str,
    max_count: int = Query(50, description="최대 커밋 수"),
):
    """문헌 저장소의 git 커밋 이력을 반환한다.

    목적: 하단 패널의 Git 이력 탭에 커밋 목록을 표시하기 위해 사용한다.
    입력:
        doc_id — 문헌 ID.
        max_count — 최대 커밋 수 (기본 50).
    출력: [{hash, short_hash, message, author, date}, ...].
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    return {"commits": get_git_log(doc_path, max_count=max_count)}


@app.get("/api/documents/{doc_id}/git/diff/{commit_hash}")
async def api_git_diff(doc_id: str, commit_hash: str):
    """특정 커밋과 그 부모 사이의 diff를 반환한다.

    목적: Git 이력에서 커밋을 선택했을 때 변경 내용을 표시하기 위해 사용한다.
    입력:
        doc_id — 문헌 ID.
        commit_hash — 대상 커밋 해시.
    출력: {commit_hash, message, diffs: [{file, change_type, diff_text}, ...]}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    result = get_git_diff(doc_path, commit_hash)
    if "error" in result:
        return JSONResponse({"error": result["error"]}, status_code=404)

    return result


# --- 서지정보 API (Phase 5) ---


@app.get("/api/documents/{doc_id}/bibliography")
async def api_bibliography(doc_id: str):
    """문헌의 서지정보를 반환한다.

    목적: 서지정보 패널에 bibliography.json 내용을 표시하기 위해 사용한다.
    입력: doc_id — 문헌 ID.
    출력: bibliography.json의 내용.
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
        return get_bibliography(doc_path)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


class DocumentBibFromUrlRequest(BaseModel):
    """문서에 URL로 서지정보를 가져와 바로 저장하는 요청 본문."""
    url: str


@app.post("/api/documents/{doc_id}/bibliography/from-url")
async def api_document_bib_from_url(doc_id: str, body: DocumentBibFromUrlRequest):
    """URL에서 서지정보를 가져와 해당 문서에 바로 저장한다.

    목적: 연구자의 워크플로우를 1단계로 줄인다.
          문서 선택 → URL 붙여넣기 → 가져오기 → 끝.
    입력: { "url": "https://..." }
    처리:
        1. URL에서 bibliography 생성
        2. 해당 문서의 bibliography.json에 저장
        3. git commit
    출력: { "status": "saved", "parser_id": "ndl", "bibliography": {...} }
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    import parsers as _parsers_mod  # noqa: F401
    from parsers.base import detect_parser_from_url, get_parser, get_supported_sources

    url = body.url.strip()
    if not url:
        return JSONResponse({"error": "URL이 비어있습니다."}, status_code=400)

    # URL 판별
    parser_id = detect_parser_from_url(url)
    if parser_id is None:
        sources = get_supported_sources()
        return JSONResponse(
            {
                "error": "이 URL은 자동 인식할 수 없습니다.",
                "supported_sources": sources,
            },
            status_code=400,
        )

    # 파서 가져오기 + fetch + 매핑
    try:
        fetcher, mapper = get_parser(parser_id)
        raw_data = await fetcher.fetch_by_url(url)
        bibliography = mapper.map_to_bibliography(raw_data)
    except Exception as e:
        return JSONResponse(
            {"error": f"서지정보 가져오기 실패: {e}"},
            status_code=502,
        )

    # 저장
    try:
        save_bibliography(doc_path, bibliography)
    except Exception as e:
        return JSONResponse(
            {"error": f"서지정보 저장 실패: {e}"},
            status_code=400,
        )

    # git commit
    git_result = git_commit_document(doc_path, f"L0: 서지정보 URL 가져오기 ({parser_id})")

    return {
        "status": "saved",
        "parser_id": parser_id,
        "bibliography": bibliography,
        "git": git_result,
    }


class BibliographySaveRequest(BaseModel):
    """서지정보 저장 요청 본문. bibliography.schema.json 형식."""
    title: str | None = None
    title_reading: str | None = None
    alternative_titles: list[str] | None = None
    creator: dict | None = None
    contributors: list[dict] | None = None
    date_created: str | None = None
    edition_type: str | None = None
    language: str | None = None
    script: str | None = None
    physical_description: str | None = None
    subject: list[str] | None = None
    classification: dict | None = None
    series_title: str | None = None
    material_type: str | None = None
    repository: dict | None = None
    digital_source: dict | None = None
    raw_metadata: dict | None = None
    _mapping_info: dict | None = None
    notes: str | None = None


@app.put("/api/documents/{doc_id}/bibliography")
async def api_save_bibliography(doc_id: str, body: BibliographySaveRequest):
    """문헌의 서지정보를 저장한다.

    목적: 파서가 가져온 서지정보 또는 사용자가 수동 편집한 내용을 저장한다.
    입력:
        doc_id — 문헌 ID.
        body — bibliography.schema.json 형식의 데이터.
    출력: {status: "saved", file_path}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    bib_data = body.model_dump(exclude_none=False)
    try:
        return save_bibliography(doc_path, bib_data)
    except Exception as e:
        return JSONResponse(
            {"error": f"서지정보 저장 실패: {e}"},
            status_code=400,
        )


# --- 파서 API (Phase 5) ---


@app.get("/api/parsers")
async def api_parsers():
    """등록된 파서 목록을 반환한다.

    목적: GUI에서 파서 선택 드롭다운을 채우기 위해 사용한다.
    출력: [{id, name, api_variant}, ...]
    """
    # 파서 모듈을 지연 import (parsers 패키지가 register_parser를 호출)
    import parsers  # noqa: F401
    from parsers.base import list_parsers, get_registry_json

    return {
        "parsers": list_parsers(),
        "registry": get_registry_json(),
    }


class BibliographyFromUrlRequest(BaseModel):
    """URL에서 서지정보를 가져오는 요청 본문."""
    url: str


@app.post("/api/bibliography/from-url")
async def api_bibliography_from_url(body: BibliographyFromUrlRequest):
    """URL을 자동 판별하여 서지정보를 가져온다.

    목적: 연구자가 URL을 붙여넣기만 하면 서지정보를 자동으로 가져온다.
          파서 선택·검색·결과 선택 과정이 필요 없다.
    입력: { "url": "https://..." }
    처리:
        1. detect_parser_from_url(url) → parser_id
        2. fetcher.fetch_by_url(url) → raw_data
        3. mapper.map_to_bibliography(raw_data) → bibliography
    출력: { "parser_id": "ndl", "bibliography": {...} }
    에러: URL을 인식할 수 없으면 → 지원하는 소스 목록 안내
    """
    import parsers  # noqa: F401
    from parsers.base import detect_parser_from_url, get_parser, get_supported_sources

    url = body.url.strip()
    if not url:
        return JSONResponse(
            {"error": "URL이 비어있습니다."},
            status_code=400,
        )

    # 1. URL 패턴으로 파서 자동 판별
    parser_id = detect_parser_from_url(url)
    if parser_id is None:
        sources = get_supported_sources()
        return JSONResponse(
            {
                "error": "이 URL은 자동 인식할 수 없습니다.",
                "supported_sources": sources,
                "hint": "지원하는 소스의 URL을 붙여넣거나, '직접 검색' 기능을 사용하세요.",
            },
            status_code=400,
        )

    # 2. 파서 가져오기
    try:
        fetcher, mapper = get_parser(parser_id)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)

    # 3. URL에서 메타데이터 추출
    try:
        raw_data = await fetcher.fetch_by_url(url)
    except (ValueError, FileNotFoundError) as e:
        return JSONResponse(
            {"error": f"URL에서 데이터를 가져올 수 없습니다: {e}"},
            status_code=400,
        )
    except Exception as e:
        return JSONResponse(
            {
                "error": f"외부 소스 접속 실패: {e}",
                "hint": "네트워크 연결을 확인하고 다시 시도하세요.",
            },
            status_code=502,
        )

    # 4. 매핑
    try:
        bibliography = mapper.map_to_bibliography(raw_data)
    except Exception as e:
        return JSONResponse(
            {"error": f"서지정보 매핑 실패: {e}"},
            status_code=400,
        )

    return {"parser_id": parser_id, "bibliography": bibliography}


class ParserSearchRequest(BaseModel):
    """파서 검색 요청 본문."""
    query: str
    cnt: int = 10
    mediatype: int | None = None


@app.post("/api/parsers/{parser_id}/search")
async def api_parser_search(parser_id: str, body: ParserSearchRequest):
    """외부 소스에서 서지정보를 검색한다.

    목적: GUI의 "서지정보 가져오기" 다이얼로그에서 사용.
    입력:
        parser_id — 파서 ID (예: "ndl", "japan_national_archives").
        body — {query: "검색어", cnt: 10}.
    출력: {results: [{title, creator, item_id, summary, raw}, ...]}.
    """
    import parsers  # noqa: F401
    from parsers.base import get_parser

    try:
        fetcher, _mapper = get_parser(parser_id)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)

    try:
        results = await fetcher.search(
            body.query,
            cnt=body.cnt,
            mediatype=body.mediatype,
        )
        return {"results": results}
    except Exception as e:
        return JSONResponse(
            {"error": f"검색 실패: {e}\n→ 해결: 네트워크 연결과 검색어를 확인하세요."},
            status_code=502,
        )


class ParserMapRequest(BaseModel):
    """파서 매핑 요청 본문. 검색 결과의 raw 데이터를 전달한다."""
    raw_data: dict


@app.post("/api/parsers/{parser_id}/map")
async def api_parser_map(parser_id: str, body: ParserMapRequest):
    """검색 결과를 bibliography.json 형식으로 매핑한다.

    목적: 사용자가 검색 결과에서 항목을 선택하면,
          해당 항목의 raw 데이터를 공통 스키마로 변환한다.
    입력:
        parser_id — 파서 ID.
        body — {raw_data: {...}} (Fetcher가 반환한 raw dict).
    출력: bibliography.schema.json 형식의 dict.
    """
    import parsers  # noqa: F401
    from parsers.base import get_parser

    try:
        _fetcher, mapper = get_parser(parser_id)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)

    try:
        bibliography = mapper.map_to_bibliography(body.raw_data)
        return {"bibliography": bibliography}
    except Exception as e:
        return JSONResponse(
            {"error": f"매핑 실패: {e}"},
            status_code=400,
        )


class ParserFetchAndMapRequest(BaseModel):
    """상세 조회 + 매핑 결합 요청 본문."""
    item_id: str


@app.post("/api/parsers/{parser_id}/fetch-and-map")
async def api_parser_fetch_and_map(parser_id: str, body: ParserFetchAndMapRequest):
    """항목의 상세 정보를 가져와서 bibliography로 매핑한다.

    목적: 검색 결과에서 항목을 선택했을 때,
          KORCIS처럼 검색 결과에 전체 메타데이터가 없는 소스에서
          fetch_detail + map_to_bibliography를 한 번에 수행한다.
    입력:
        parser_id — 파서 ID.
        body — {item_id: "..."} (검색 결과의 item_id).
    출력: bibliography.schema.json 형식의 dict.
    """
    import parsers  # noqa: F401
    from parsers.base import get_parser

    try:
        fetcher, mapper = get_parser(parser_id)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)

    try:
        raw_data = await fetcher.fetch_detail(body.item_id)
        bibliography = mapper.map_to_bibliography(raw_data)
        return {"bibliography": bibliography}
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse(
            {"error": f"상세 조회/매핑 실패: {e}"},
            status_code=502,
        )


# =========================================
#   Phase 7: 해석 저장소 API
# =========================================


class CreateInterpretationRequest(BaseModel):
    """해석 저장소 생성 요청 본문."""
    interp_id: str
    source_document_id: str
    interpreter_type: str
    interpreter_name: str | None = None
    title: str | None = None


class LayerContentSaveRequest(BaseModel):
    """층 내용 저장 요청 본문."""
    content: str | dict
    part_id: str


class AcknowledgeRequest(BaseModel):
    """변경 인지 요청 본문."""
    file_paths: list[str] | None = None


@app.post("/api/interpretations")
async def api_create_interpretation(body: CreateInterpretationRequest):
    """해석 저장소를 생성한다.

    목적: 원본 문헌을 기반으로 새 해석 저장소를 만든다.
    입력:
        body — {interp_id, source_document_id, interpreter_type, interpreter_name, title}.
    출력: 생성된 해석 저장소의 manifest 정보.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    try:
        interp_path = create_interpretation(
            _library_path,
            interp_id=body.interp_id,
            source_document_id=body.source_document_id,
            interpreter_type=body.interpreter_type,
            interpreter_name=body.interpreter_name,
            title=body.title,
        )
        info = get_interpretation_info(interp_path)
        return {"status": "created", "interpretation": info}
    except (ValueError, FileExistsError, FileNotFoundError) as e:
        status = 400 if isinstance(e, (ValueError, FileExistsError)) else 404
        return JSONResponse({"error": str(e)}, status_code=status)


@app.get("/api/interpretations")
async def api_interpretations():
    """해석 저장소 목록을 반환한다."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    return list_interpretations(_library_path)


@app.get("/api/interpretations/{interp_id}")
async def api_interpretation(interp_id: str):
    """특정 해석 저장소의 상세 정보를 반환한다."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    try:
        return get_interpretation_info(interp_path)
    except FileNotFoundError:
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )


@app.get("/api/interpretations/{interp_id}/dependency")
async def api_check_dependency(interp_id: str):
    """해석 저장소의 의존 변경을 확인한다.

    목적: 원본 저장소가 변경되었는지 확인하여 경고 배너를 표시하기 위해 사용한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    try:
        return check_dependency(_library_path, interp_id)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.post("/api/interpretations/{interp_id}/dependency/acknowledge")
async def api_acknowledge_changes(interp_id: str, body: AcknowledgeRequest):
    """변경된 파일을 '인지함' 상태로 전환한다.

    목적: 연구자가 원본 변경을 확인했지만 해석은 유효하다고 판단할 때 사용한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    try:
        return acknowledge_changes(_library_path, interp_id, body.file_paths)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.post("/api/interpretations/{interp_id}/dependency/update-base")
async def api_update_base(interp_id: str):
    """기반 커밋을 현재 원본 HEAD로 갱신한다.

    목적: 원본 변경을 모두 반영하고 새 기반에서 작업을 계속한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    try:
        return update_base(_library_path, interp_id)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.get("/api/interpretations/{interp_id}/layers/{layer}/{sub_type}/pages/{page_num}")
async def api_layer_content(
    interp_id: str,
    layer: str,
    sub_type: str,
    page_num: int,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """해석 층의 내용을 반환한다.

    목적: 해석 뷰어에서 특정 층/서브타입/페이지의 내용을 로드하기 위해 사용한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        return get_layer_content(interp_path, layer, sub_type, part_id, page_num)
    except FileNotFoundError:
        return JSONResponse(
            {"error": f"레이어 내용을 찾을 수 없습니다: {layer}/{sub_type} page {page_num}"},
            status_code=404,
        )
    except Exception as e:
        return JSONResponse(
            {"error": f"레이어 조회 중 오류: {e}"},
            status_code=500,
        )


@app.put("/api/interpretations/{interp_id}/layers/{layer}/{sub_type}/pages/{page_num}")
async def api_save_layer_content(
    interp_id: str,
    layer: str,
    sub_type: str,
    page_num: int,
    body: LayerContentSaveRequest,
):
    """해석 층의 내용을 저장하고 자동 git commit한다.

    목적: 해석 뷰어에서 편집한 내용을 저장하고 버전 이력을 남긴다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        save_result = save_layer_content(
            interp_path, layer, sub_type, body.part_id, page_num, body.content,
        )
    except Exception as e:
        return JSONResponse({"error": f"저장 실패: {e}"}, status_code=400)

    # 자동 git commit
    layer_label = {"L5_reading": "구두점", "L6_translation": "번역", "L7_annotation": "주석"}.get(layer, layer)
    commit_msg = f"{layer}: page {page_num:03d} {layer_label} 편집 ({sub_type})"
    git_result = git_commit_interpretation(interp_path, commit_msg)
    save_result["git"] = git_result

    return save_result


@app.get("/api/interpretations/{interp_id}/git/log")
async def api_interp_git_log(
    interp_id: str,
    max_count: int = Query(50, description="최대 커밋 수"),
):
    """해석 저장소의 git 커밋 이력을 반환한다."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    return {"commits": get_interp_git_log(interp_path, max_count=max_count)}


# =========================================
#   Phase 8: 코어 스키마 엔티티 API
# =========================================


class EntityCreateRequest(BaseModel):
    """엔티티 생성 요청 본문."""
    entity_type: str   # work, text_block, tag, concept, agent, relation
    data: dict         # 스키마에 맞는 엔티티 데이터


class EntityUpdateRequest(BaseModel):
    """엔티티 수정 요청 본문."""
    updates: dict      # 갱신할 필드 딕셔너리


class TextBlockFromSourceRequest(BaseModel):
    """TextBlock 생성 요청 (source_ref 자동 채움)."""
    document_id: str
    part_id: str
    page_num: int
    layout_block_id: str | None = None
    original_text: str
    work_id: str
    sequence_index: int


class PromoteTagRequest(BaseModel):
    """Tag → Concept 승격 요청."""
    label: str | None = None
    scope_work: str | None = None
    description: str | None = None


class AutoCreateWorkRequest(BaseModel):
    """Work 자동 생성 요청."""
    document_id: str


@app.post("/api/interpretations/{interp_id}/entities")
async def api_create_entity(interp_id: str, body: EntityCreateRequest):
    """코어 스키마 엔티티를 생성한다.

    목적: Work, TextBlock, Tag, Concept, Agent, Relation 엔티티를 해석 저장소에 추가한다.
    입력: entity_type + data (JSON 스키마 형식).
    출력: {"status": "created", "entity_type": ..., "id": ..., "file_path": ...}
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        result = create_entity(interp_path, body.entity_type, body.data)
    except (ValueError, FileExistsError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"엔티티 생성 실패: {e}"}, status_code=400)

    # 자동 git commit
    commit_msg = f"feat: {body.entity_type} 엔티티 생성 — {result['id'][:8]}"
    result["git"] = git_commit_interpretation(interp_path, commit_msg)

    return result


@app.get("/api/interpretations/{interp_id}/entities/page/{page_num}")
async def api_entities_for_page(
    interp_id: str,
    page_num: int,
    document_id: str = Query(..., description="원본 문헌 ID"),
):
    """현재 페이지와 관련된 엔티티를 모두 반환한다.

    목적: 하단 패널 "엔티티" 탭에서 현재 페이지에 연결된 엔티티를 표시한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        return list_entities_for_page(interp_path, document_id, page_num)
    except Exception as e:
        return JSONResponse({"error": f"엔티티 조회 실패: {e}"}, status_code=400)


@app.get("/api/interpretations/{interp_id}/entities/{entity_type}")
async def api_list_entities(
    interp_id: str,
    entity_type: str,
    status: str | None = Query(None, description="상태 필터"),
    block_id: str | None = Query(None, description="TextBlock ID 필터"),
):
    """특정 유형의 엔티티 목록을 반환한다."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    filters = {}
    if status:
        filters["status"] = status
    if block_id:
        filters["block_id"] = block_id

    try:
        entities = list_entities(interp_path, entity_type, filters or None)
        return {"entity_type": entity_type, "count": len(entities), "entities": entities}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/interpretations/{interp_id}/entities/{entity_type}/{entity_id}")
async def api_get_entity(interp_id: str, entity_type: str, entity_id: str):
    """단일 엔티티를 조회한다."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        return get_entity(interp_path, entity_type, entity_id)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.put("/api/interpretations/{interp_id}/entities/{entity_type}/{entity_id}")
async def api_update_entity(
    interp_id: str,
    entity_type: str,
    entity_id: str,
    body: EntityUpdateRequest,
):
    """엔티티를 수정한다 (상태 전이 포함).

    목적: 엔티티 필드를 갱신한다. 삭제는 불가능하며 상태 전이만 허용된다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        result = update_entity(interp_path, entity_type, entity_id, body.updates)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"엔티티 수정 중 오류: {e}"}, status_code=500)

    # 자동 git commit
    commit_msg = f"fix: {entity_type} 엔티티 수정 — {entity_id[:8]}"
    result["git"] = git_commit_interpretation(interp_path, commit_msg)

    return result


@app.post("/api/interpretations/{interp_id}/entities/text_block/from-source")
async def api_create_textblock_from_source(
    interp_id: str,
    body: TextBlockFromSourceRequest,
):
    """L4 확정 텍스트에서 TextBlock을 생성한다 (source_ref 자동 채움).

    목적: 연구자가 현재 보고 있는 페이지/블록에서 TextBlock을 만들면,
          source_ref가 자동으로 채워진다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        result = create_textblock_from_source(
            interp_path,
            _library_path,
            body.document_id,
            body.part_id,
            body.page_num,
            body.layout_block_id,
            body.original_text,
            body.work_id,
            body.sequence_index,
        )
    except Exception as e:
        return JSONResponse({"error": f"TextBlock 생성 실패: {e}"}, status_code=400)

    # 자동 git commit
    block_info = body.layout_block_id or ""
    commit_msg = f"feat: TextBlock 생성 — page {body.page_num:03d} {block_info}"
    result["git"] = git_commit_interpretation(interp_path, commit_msg)

    return result


@app.post("/api/interpretations/{interp_id}/entities/work/auto-create")
async def api_auto_create_work(interp_id: str, body: AutoCreateWorkRequest):
    """문헌 메타데이터로부터 Work 엔티티를 자동 생성한다.

    목적: TextBlock 생성에 필요한 Work가 없을 때,
          문헌의 서지정보/매니페스트에서 자동으로 Work를 만든다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        result = auto_create_work(interp_path, _library_path, body.document_id)
    except Exception as e:
        return JSONResponse({"error": f"Work 자동 생성 실패: {e}"}, status_code=400)

    # 기존 Work 반환인 경우 커밋 불필요
    if result["status"] == "created":
        work_title = result["work"].get("title", "")
        commit_msg = f"feat: Work 자동 생성 — {work_title}"
        result["git"] = git_commit_interpretation(interp_path, commit_msg)

    return result


@app.post("/api/interpretations/{interp_id}/entities/tags/{tag_id}/promote")
async def api_promote_tag(
    interp_id: str,
    tag_id: str,
    body: PromoteTagRequest,
):
    """Tag를 Concept으로 승격한다.

    목적: 연구자가 확인한 Tag를 의미 엔티티(Concept)로 격상한다.
          core-schema-v1.3.md 섹션 7: Promotion Flow.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        result = promote_tag_to_concept(
            interp_path,
            tag_id,
            label=body.label,
            scope_work=body.scope_work,
            description=body.description,
        )
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": f"Tag 승격 실패: {e}"}, status_code=400)

    # 자동 git commit
    label = result.get("concept", {}).get("label", "")
    commit_msg = f"feat: Tag → Concept 승격 — {label}"
    result["git"] = git_commit_interpretation(interp_path, commit_msg)

    return result


# ===========================================================================
#  Phase 10-2: LLM 4단 폴백 아키텍처 API
# ===========================================================================

# LLM Router 인스턴스 (serve 시 초기화)
_llm_router = None


def _get_llm_router():
    """LLM Router를 lazy-init한다.

    왜 lazy-init인가:
        _library_path는 serve 명령에서 설정된다.
        LlmConfig가 서고의 .env를 읽으려면 경로가 필요하다.
    """
    global _llm_router
    if _llm_router is None:
        from llm.config import LlmConfig
        from llm.router import LlmRouter
        config = LlmConfig(library_root=_library_path)
        _llm_router = LlmRouter(config)
    return _llm_router


class DraftReviewRequest(BaseModel):
    """Draft 검토 요청 본문."""
    action: str  # "accept" | "modify" | "reject"
    quality_rating: int | None = None
    quality_notes: str | None = None
    modifications: str | None = None


class CompareLayoutRequest(BaseModel):
    """레이아웃 비교 요청 본문."""
    targets: list[str] | None = None


# Draft 저장소 (메모리 — 서버 재시작 시 소멸)
_llm_drafts: dict = {}


@app.get("/api/llm/status")
async def api_llm_status():
    """각 provider의 가용 상태."""
    router = _get_llm_router()
    return await router.get_status()


@app.get("/api/llm/models")
async def api_llm_models():
    """GUI 드롭다운용 모델 목록."""
    router = _get_llm_router()
    return await router.get_available_models()


@app.get("/api/llm/usage")
async def api_llm_usage():
    """이번 달 사용량 요약."""
    router = _get_llm_router()
    return router.usage_tracker.get_monthly_summary()


@app.post("/api/llm/analyze-layout/{doc_id}/{page}")
async def api_analyze_layout(
    doc_id: str,
    page: int,
    force_provider: str | None = Query(None),
    force_model: str | None = Query(None),
):
    """페이지 이미지를 LLM으로 레이아웃 분석. Draft 반환.

    왜 별도 엔드포인트인가:
        기존 layout-editor의 수동 블록 편집과 독립적으로,
        LLM이 제안하는 블록을 Draft로 관리한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    from core.layout_analyzer import analyze_page_layout

    router = _get_llm_router()

    # 페이지 이미지 로드
    page_image = _load_page_image(doc_id, page)
    if not page_image:
        return JSONResponse(
            {"error": f"페이지 이미지 없음: {doc_id} page {page}"},
            status_code=404,
        )

    try:
        draft = await analyze_page_layout(
            router, page_image,
            force_provider=force_provider,
            force_model=force_model,
        )
    except Exception as e:
        return JSONResponse({"error": f"레이아웃 분석 실패: {e}"}, status_code=500)

    # Draft 저장
    _llm_drafts[draft.draft_id] = draft
    return draft.to_dict()


@app.post("/api/llm/compare-layout/{doc_id}/{page}")
async def api_compare_layout(doc_id: str, page: int, body: CompareLayoutRequest):
    """여러 모델로 레이아웃 분석 비교."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    from core.layout_analyzer import compare_layout_analysis

    router = _get_llm_router()

    page_image = _load_page_image(doc_id, page)
    if not page_image:
        return JSONResponse(
            {"error": f"페이지 이미지 없음: {doc_id} page {page}"},
            status_code=404,
        )

    # targets 파싱: ["base44_http", "ollama:glm-5:cloud"]
    parsed_targets = None
    if body.targets:
        parsed_targets = []
        for t in body.targets:
            if ":" in t:
                parts = t.split(":", 1)
                parsed_targets.append((parts[0], parts[1]))
            else:
                parsed_targets.append(t)

    try:
        drafts = await compare_layout_analysis(
            router, page_image, targets=parsed_targets,
        )
    except Exception as e:
        return JSONResponse({"error": f"레이아웃 비교 실패: {e}"}, status_code=500)

    # Draft들 저장
    for d in drafts:
        _llm_drafts[d.draft_id] = d

    return [d.to_dict() for d in drafts]


@app.post("/api/llm/drafts/{draft_id}/review")
async def api_review_draft(draft_id: str, body: DraftReviewRequest):
    """Draft를 검토 (accept/modify/reject)."""
    draft = _llm_drafts.get(draft_id)
    if not draft:
        return JSONResponse({"error": f"Draft 없음: {draft_id}"}, status_code=404)

    if body.action == "accept":
        draft.accept(
            quality_rating=body.quality_rating,
            notes=body.quality_notes or "",
        )
    elif body.action == "modify":
        draft.modify(
            modifications=body.modifications or "",
            quality_rating=body.quality_rating,
        )
    elif body.action == "reject":
        draft.reject(reason=body.quality_notes or "")
    else:
        return JSONResponse(
            {"error": f"알 수 없는 action: {body.action}"},
            status_code=400,
        )

    return draft.to_dict()


def _load_page_image(doc_id: str, page: int) -> bytes | None:
    """페이지 이미지를 바이트로 로드한다.

    L1_source에서 PDF를 찾아 해당 페이지를 이미지로 변환.
    또는 이미 이미지 파일이면 직접 읽는다.

    왜 이렇게 하는가:
        기존 PDF 뷰어는 클라이언트에서 PDF.js로 렌더링하지만,
        LLM 분석에는 서버에서 이미지를 추출해야 한다.
    """
    if _library_path is None:
        return None

    doc_dir = _library_path / "documents" / doc_id

    # 1. L1_source에서 이미지 파일 직접 찾기 (JPEG)
    source_dir = doc_dir / "L1_source"
    if source_dir.exists():
        # 페이지 번호에 해당하는 이미지 찾기
        for pattern in [
            f"*_p{page:03d}.*",
            f"*_p{page:04d}.*",
            f"*_{page:03d}.*",
            f"*_{page:04d}.*",
            f"page_{page}.*",
            f"p{page}.*",
        ]:
            matches = list(source_dir.glob(pattern))
            for m in matches:
                if m.suffix.lower() in (".jpg", ".jpeg", ".png", ".tiff", ".tif"):
                    return m.read_bytes()

    # 2. PDF에서 페이지 추출 (pypdfium2 사용 시도)
    pdf_files = list(source_dir.glob("*.pdf")) if source_dir.exists() else []
    if pdf_files:
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(str(pdf_files[0]))
            if page < len(pdf):
                pdf_page = pdf[page]
                bitmap = pdf_page.render(scale=2.0)
                pil_image = bitmap.to_pil()
                import io
                buf = io.BytesIO()
                pil_image.save(buf, format="PNG")
                return buf.getvalue()
        except ImportError:
            pass  # pypdfium2가 없으면 건너뜀

    return None


# ===========================================================================
#  Phase 10-1: OCR 엔진 연동 API
# ===========================================================================

# OCR Pipeline + Registry 인스턴스 (서버 시작 시 lazy init)
_ocr_registry = None
_ocr_pipeline = None


def _get_ocr_pipeline():
    """OCR Pipeline과 Registry를 lazy-init한다.

    왜 lazy-init인가:
        _library_path는 serve 명령에서 설정된다.
        OcrPipeline은 library_root가 필요하므로 앱 초기화 후에 생성해야 한다.
    """
    global _ocr_registry, _ocr_pipeline
    if _ocr_registry is None:
        from ocr.registry import OcrEngineRegistry
        from ocr.pipeline import OcrPipeline

        _ocr_registry = OcrEngineRegistry()
        _ocr_registry.auto_register()
        _ocr_pipeline = OcrPipeline(_ocr_registry, library_root=str(_library_path))

    return _ocr_pipeline, _ocr_registry


class OcrRunRequest(BaseModel):
    """OCR 실행 요청 본문."""
    engine_id: str | None = None      # None이면 기본 엔진
    block_ids: list[str] | None = None  # None이면 전체 블록


@app.get("/api/ocr/engines")
async def api_ocr_engines():
    """등록된 OCR 엔진 목록과 사용 가능 여부를 반환한다.

    목적: GUI의 OCR 실행 패널에서 엔진 드롭다운을 채우기 위해 사용한다.
    출력: {
        "engines": [{"engine_id": "paddleocr", "display_name": "PaddleOCR", "available": true, ...}],
        "default_engine": "paddleocr"
    }
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    _pipeline, registry = _get_ocr_pipeline()
    return {
        "engines": registry.list_engines(),
        "default_engine": registry.default_engine_id,
    }


@app.post("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr")
async def api_run_ocr(
    doc_id: str,
    part_id: str,
    page_number: int,
    body: OcrRunRequest,
):
    """페이지의 블록들을 OCR 실행한다.

    목적: 레이아웃 모드에서 OCR을 실행하고 결과를 L2_ocr/에 저장한다.
    입력:
        doc_id — 문헌 ID.
        part_id — 권 식별자.
        page_number — 페이지 번호 (1-indexed).
        body — {"engine_id": null, "block_ids": null}.
    출력: OcrPageResult.to_summary() 형식.
          일부 블록 실패 시에도 성공한 블록 결과를 반환한다 (부분 성공).

    처리 순서:
        1. L3 layout_page.json에서 블록 목록 로드
        2. L1_source에서 이미지 로드 (개별 파일 또는 PDF 페이지 추출)
        3. 각 블록: bbox 크롭 → 전처리 → OCR 엔진 인식
        4. 결과를 L2_ocr/{part_id}_page_{NNN}.json에 저장
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    pipeline, _registry = _get_ocr_pipeline()

    try:
        result = pipeline.run_page(
            doc_id=doc_id,
            part_id=part_id,
            page_number=page_number,
            engine_id=body.engine_id,
            block_ids=body.block_ids,
        )
        return result.to_summary()
    except Exception as e:
        return JSONResponse(
            {"error": f"OCR 실행 실패: {e}"},
            status_code=500,
        )


@app.get("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr")
async def api_get_ocr_result(
    doc_id: str,
    part_id: str,
    page_number: int,
):
    """특정 페이지의 OCR 결과(L2)를 반환한다.

    목적: 교정 모드에서 기존 OCR 결과를 로드하기 위해 사용한다.
    입력:
        doc_id — 문헌 ID.
        part_id — 권 식별자.
        page_number — 페이지 번호 (1-indexed).
    출력: L2_ocr/{part_id}_page_{NNN}.json의 내용.
          파일이 없으면 404.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    import json as _json

    filename = f"{part_id}_page_{page_number:03d}.json"
    ocr_path = _library_path / "documents" / doc_id / "L2_ocr" / filename

    if not ocr_path.exists():
        return JSONResponse(
            {"error": f"OCR 결과가 없습니다: {doc_id}/{part_id}/page_{page_number:03d}"},
            status_code=404,
        )

    data = _json.loads(ocr_path.read_text(encoding="utf-8"))
    data["_meta"] = {
        "document_id": doc_id,
        "part_id": part_id,
        "page_number": page_number,
        "file_path": str(ocr_path.relative_to(_library_path)),
    }
    return data


@app.post("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr/{block_id}")
async def api_rerun_ocr_block(
    doc_id: str,
    part_id: str,
    page_number: int,
    block_id: str,
    body: OcrRunRequest,
):
    """특정 블록만 OCR을 재실행한다.

    목적: 하나의 블록만 다시 OCR 처리하고 기존 L2 결과에 반영한다.
          인식 결과가 좋지 않은 블록을 개별적으로 재시도할 때 사용한다.
    입력:
        doc_id — 문헌 ID.
        part_id — 권 식별자.
        page_number — 페이지 번호 (1-indexed).
        block_id — 재실행할 블록 ID (L3 layout의 block_id).
        body — {"engine_id": null} (다른 엔진으로 시도 가능).
    출력: OcrPageResult.to_summary() 형식 (해당 블록만 포함).
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    pipeline, _registry = _get_ocr_pipeline()

    try:
        result = pipeline.run_block(
            doc_id=doc_id,
            part_id=part_id,
            page_number=page_number,
            block_id=block_id,
            engine_id=body.engine_id,
        )
        return result.to_summary()
    except Exception as e:
        return JSONResponse(
            {"error": f"OCR 블록 재실행 실패: {e}"},
            status_code=500,
        )


# ===========================================================================
#  Phase 10-3: 정렬 엔진 — OCR ↔ 텍스트 대조 API
# ===========================================================================

# 이체자 사전 인스턴스 (서버 시작 시 lazy init)
_variant_dict = None


def _get_variant_dict():
    """이체자 사전을 lazy-init한다.

    왜 lazy-init인가:
        _library_path가 설정된 후에야 서고 내부 사전 경로를 알 수 있다.
        기본 경로(resources/variant_chars.json)를 먼저 시도하고,
        없으면 VariantCharDict가 빈 사전으로 동작한다.
    """
    global _variant_dict
    if _variant_dict is None:
        from core.alignment import VariantCharDict

        _variant_dict = VariantCharDict()  # 기본 경로 자동 탐색

    return _variant_dict


@app.post("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/alignment")
async def api_run_alignment(
    doc_id: str,
    part_id: str,
    page_number: int,
):
    """페이지의 OCR 결과(L2)와 확정 텍스트(L4)를 글자 단위로 대조한다.

    목적: 교정 모드에서 OCR 인식 결과와 사람이 확정한 텍스트의 차이를 시각적으로 보여준다.
    입력:
        doc_id — 문헌 ID.
        part_id — 권 식별자.
        page_number — 페이지 번호 (1-indexed).
    전제 조건:
        L2(OCR 결과)와 L4(확정 텍스트)가 모두 있어야 한다.
    출력: {
        "blocks": [BlockAlignment.to_dict(), ...],  # 블록별 대조 결과
        "page_stats": AlignmentStats.to_dict()       # 페이지 전체 통계 (* 블록)
    }
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    from core.alignment import align_page

    variant_dict = _get_variant_dict()

    try:
        block_results = align_page(
            library_root=str(_library_path),
            doc_id=doc_id,
            part_id=part_id,
            page_number=page_number,
            variant_dict=variant_dict,
        )
    except Exception as e:
        return JSONResponse(
            {"error": f"대조 실행 실패: {e}"},
            status_code=500,
        )

    # 에러만 있는 경우
    if len(block_results) == 1 and block_results[0].error:
        return JSONResponse(
            {"error": block_results[0].error},
            status_code=404,
        )

    # 페이지 전체 통계 (* 블록)
    page_stats = None
    blocks_output = []
    for br in block_results:
        blocks_output.append(br.to_dict())
        if br.layout_block_id == "*" and br.stats:
            page_stats = br.stats.to_dict()

    return {
        "blocks": blocks_output,
        "page_stats": page_stats,
    }


@app.get("/api/alignment/variant-dict")
async def api_get_variant_dict():
    """이체자 사전 내용을 반환한다.

    목적: GUI의 이체자 사전 관리 패널에서 현재 등록된 이체자 목록을 표시한다.
    출력: { "variants": { "裴": ["裵"], "裵": ["裴"], ... }, "size": 2 }
    """
    variant_dict = _get_variant_dict()
    return {
        "variants": variant_dict.to_dict(),
        "size": variant_dict.size,
    }


class VariantPairRequest(BaseModel):
    """이체자 쌍 추가 요청."""
    char_a: str
    char_b: str


@app.post("/api/alignment/variant-dict")
async def api_add_variant_pair(body: VariantPairRequest):
    """이체자 쌍을 사전에 추가한다.

    목적: 대조 결과에서 사용자가 발견한 이체자를 바로 등록할 수 있게 한다.
    입력: { "char_a": "裴", "char_b": "裵" }
    처리:
        1. 양방향 등록 (A→B, B→A)
        2. resources/variant_chars.json에 저장
    출력: { "status": "ok", "size": <새 사전 크기> }
    """
    variant_dict = _get_variant_dict()

    if not body.char_a or not body.char_b:
        return JSONResponse({"error": "두 글자 모두 입력해야 합니다."}, status_code=400)
    if body.char_a == body.char_b:
        return JSONResponse({"error": "같은 글자는 이체자로 등록할 수 없습니다."}, status_code=400)

    variant_dict.add_pair(body.char_a, body.char_b)

    # 사전 파일에 저장
    save_path = variant_dict._find_default_path()
    if save_path:
        variant_dict.save(save_path)
    else:
        # 기본 경로에 새로 생성
        import os
        resources_dir = os.path.join(os.path.dirname(__file__), "..", "..", "resources")
        os.makedirs(resources_dir, exist_ok=True)
        save_path = os.path.join(resources_dir, "variant_chars.json")
        variant_dict.save(save_path)

    return {"status": "ok", "size": variant_dict.size}


# ───────────────────────────────────────────────────
# Phase 11-1: 표점 프리셋 조회
# ───────────────────────────────────────────────────

@app.get("/api/punctuation-presets")
async def api_punctuation_presets():
    """표점 부호 프리셋 목록을 반환한다."""
    presets_path = Path(__file__).parent.parent.parent / "resources" / "punctuation_presets.json"
    if not presets_path.exists():
        return {"presets": [], "custom": []}
    import json as _json
    with open(presets_path, encoding="utf-8") as f:
        return _json.load(f)


# ───────────────────────────────────────────────────
# Phase 11-1: L5 표점(句讀) API
# ───────────────────────────────────────────────────


class PunctuationSaveRequest(BaseModel):
    """표점 저장 요청."""
    block_id: str
    marks: list


class MarkAddRequest(BaseModel):
    """개별 표점 추가 요청."""
    target: dict
    before: str | None = None
    after: str | None = None


@app.get("/api/interpretations/{interp_id}/pages/{page_num}/punctuation")
async def api_get_punctuation(interp_id: str, page_num: int, block_id: str = Query(...)):
    """표점 조회.

    목적: 특정 블록의 L5 표점 데이터를 반환한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 저장소 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    # part_id는 문헌에서 자동 추론 (현재는 "main" 기본값)
    part_id = "main"
    data = load_punctuation(interp_path, part_id, page_num, block_id)
    return data


@app.put("/api/interpretations/{interp_id}/pages/{page_num}/punctuation")
async def api_save_punctuation(interp_id: str, page_num: int, body: PunctuationSaveRequest):
    """표점 저장 (전체 덮어쓰기).

    목적: 블록의 표점 데이터를 저장한다. 스키마 검증 후 파일 기록.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 저장소 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    part_id = "main"
    data = {"block_id": body.block_id, "marks": body.marks}

    try:
        file_path = save_punctuation(interp_path, part_id, page_num, data)
        # git commit
        try:
            git_commit_interpretation(interp_path, f"feat: L5 표점 저장 — page {page_num}")
        except Exception:
            pass  # git 실패는 저장 성공에 영향 없음
        return {"success": True, "file_path": str(file_path.relative_to(_library_path))}
    except Exception as e:
        return JSONResponse({"error": f"표점 저장 실패: {e}"}, status_code=400)


@app.post("/api/interpretations/{interp_id}/pages/{page_num}/punctuation/{block_id}/marks")
async def api_add_mark(interp_id: str, page_num: int, block_id: str, body: MarkAddRequest):
    """개별 표점 추가."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_punctuation(interp_path, part_id, page_num, block_id)
    mark = {"target": body.target, "before": body.before, "after": body.after}
    result = add_mark(data, mark)

    try:
        save_punctuation(interp_path, part_id, page_num, data)
        return JSONResponse(result, status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.delete("/api/interpretations/{interp_id}/pages/{page_num}/punctuation/{block_id}/marks/{mark_id}")
async def api_delete_mark(interp_id: str, page_num: int, block_id: str, mark_id: str):
    """개별 표점 삭제."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_punctuation(interp_path, part_id, page_num, block_id)
    removed = remove_mark(data, mark_id)

    if not removed:
        return JSONResponse({"error": f"표점 '{mark_id}'를 찾을 수 없습니다."}, status_code=404)

    save_punctuation(interp_path, part_id, page_num, data)
    return JSONResponse(status_code=204, content=None)


@app.get("/api/interpretations/{interp_id}/pages/{page_num}/punctuation/{block_id}/preview")
async def api_punctuation_preview(interp_id: str, page_num: int, block_id: str):
    """합성 텍스트 미리보기.

    L4 원문에 표점을 적용한 결과 + 문장 분리를 반환.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    # 표점 로드
    punct_data = load_punctuation(interp_path, part_id, page_num, block_id)

    # L4 원문 로드 (해석 저장소의 L5_reading에서)
    layer_result = get_layer_content(interp_path, "L5_reading", "main_text", part_id, page_num)
    original_text = ""
    if layer_result.get("exists") and isinstance(layer_result.get("content"), str):
        original_text = layer_result["content"]

    rendered = render_punctuated_text(original_text, punct_data.get("marks", []))
    sentences = split_sentences(original_text, punct_data.get("marks", []))

    return {
        "original_text": original_text,
        "rendered": rendered,
        "sentences": sentences,
    }


# ───────────────────────────────────────────────────
# Phase 11-1: L5 현토(懸吐) API
# ───────────────────────────────────────────────────


class HyeontoSaveRequest(BaseModel):
    """현토 저장 요청."""
    block_id: str
    annotations: list


class AnnotationAddRequest(BaseModel):
    """개별 현토 추가 요청."""
    target: dict
    position: str = "after"
    text: str
    category: str | None = None


@app.get("/api/interpretations/{interp_id}/pages/{page_num}/hyeonto")
async def api_get_hyeonto(interp_id: str, page_num: int, block_id: str = Query(...)):
    """현토 조회."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 저장소 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    part_id = "main"
    data = load_hyeonto(interp_path, part_id, page_num, block_id)
    return data


@app.put("/api/interpretations/{interp_id}/pages/{page_num}/hyeonto")
async def api_save_hyeonto(interp_id: str, page_num: int, body: HyeontoSaveRequest):
    """현토 저장 (전체 덮어쓰기)."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 저장소 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    part_id = "main"
    data = {"block_id": body.block_id, "annotations": body.annotations}

    try:
        file_path = save_hyeonto(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(interp_path, f"feat: L5 현토 저장 — page {page_num}")
        except Exception:
            pass
        return {"success": True, "file_path": str(file_path.relative_to(_library_path))}
    except Exception as e:
        return JSONResponse({"error": f"현토 저장 실패: {e}"}, status_code=400)


@app.post("/api/interpretations/{interp_id}/pages/{page_num}/hyeonto/{block_id}/annotations")
async def api_add_annotation(interp_id: str, page_num: int, block_id: str, body: AnnotationAddRequest):
    """개별 현토 추가."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_hyeonto(interp_path, part_id, page_num, block_id)
    annotation = {
        "target": body.target,
        "position": body.position,
        "text": body.text,
        "category": body.category,
    }
    result = add_annotation(data, annotation)

    try:
        save_hyeonto(interp_path, part_id, page_num, data)
        return JSONResponse(result, status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.delete("/api/interpretations/{interp_id}/pages/{page_num}/hyeonto/{block_id}/annotations/{ann_id}")
async def api_delete_annotation(interp_id: str, page_num: int, block_id: str, ann_id: str):
    """개별 현토 삭제."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_hyeonto(interp_path, part_id, page_num, block_id)
    removed = remove_annotation(data, ann_id)

    if not removed:
        return JSONResponse({"error": f"현토 '{ann_id}'를 찾을 수 없습니다."}, status_code=404)

    save_hyeonto(interp_path, part_id, page_num, data)
    return JSONResponse(status_code=204, content=None)


@app.get("/api/interpretations/{interp_id}/pages/{page_num}/hyeonto/{block_id}/preview")
async def api_hyeonto_preview(interp_id: str, page_num: int, block_id: str):
    """현토 합성 텍스트 미리보기.

    표점이 있으면 함께 적용한 결과를 반환.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    # L4 원문 로드
    layer_result = get_layer_content(interp_path, "L5_reading", "main_text", part_id, page_num)
    original_text = ""
    if layer_result.get("exists") and isinstance(layer_result.get("content"), str):
        original_text = layer_result["content"]

    # 현토 로드
    ht_data = load_hyeonto(interp_path, part_id, page_num, block_id)
    rendered = render_hyeonto_text(original_text, ht_data.get("annotations", []))

    # 표점도 함께 적용한 결과
    punct_data = load_punctuation(interp_path, part_id, page_num, block_id)
    # 표점 + 현토 합성: 먼저 현토 적용 후 표점 적용
    combined = render_punctuated_text(rendered, punct_data.get("marks", []))

    return {
        "original_text": original_text,
        "rendered_hyeonto": rendered,
        "rendered_combined": combined,
    }
