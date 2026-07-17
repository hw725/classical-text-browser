"""문헌(document) 관련 API 라우터.

server.py에서 분리된 문헌 CRUD, 텍스트/레이아웃/교정/서지정보/Git 이력,
외부 파서 연동, PDF/HWP 텍스트 가져오기 엔드포인트를 모아 둔다.

라우터 태그: documents
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app._state import _get_llm_router, get_library_path, require_repo_path
from core.document import (
    add_document,
    create_document_from_hwp,
    create_document_from_url,
    get_bibliography,
    get_corrected_text,
    get_document_info,
    get_git_diff,
    get_git_log,
    get_page_corrections,
    get_page_layout,
    get_page_text,
    get_pdf_path,
    git_commit_document,
    import_hwp_text_to_document,
    list_pages,
    match_hwp_text_to_layout_blocks,
    save_bibliography,
    save_page_corrections,
    save_page_layout,
    save_page_text,
)
from core.library import (
    list_documents,
    trash_document,
)
from core.repo_id import REPO_ID_RULE_TEXT, is_valid_repo_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])


# ── Pydantic 모델 ─────────────────────────────────


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


class PreviewFromUrlRequest(BaseModel):
    """URL에서 서지정보 + 에셋 목록 미리보기 요청."""

    url: str


class CreateFromUrlRequest(BaseModel):
    """URL에서 문헌 자동 생성 요청."""

    url: str
    doc_id: str
    title: str | None = None
    selected_assets: list[str] | None = None


class MatchHwpToBlocksRequest(BaseModel):
    """HWP 텍스트를 LayoutBlock에 매칭하는 요청."""

    part_id: str
    page_num: int
    block_text_mapping: list[dict]


class PdfSeparateRequest(BaseModel):
    """PDF 텍스트 분리 요청."""

    structure: dict  # DocumentStructure 딕셔너리
    pages: list[dict] | None = None  # [{page_num, text}] — None이면 전체
    custom_instructions: str = ""
    force_provider: str | None = None
    force_model: str | None = None


class AlignPreviewRequest(BaseModel):
    """외부 텍스트를 기존 문헌의 페이지에 자동 매핑하는 요청."""

    doc_id: str
    part_id: str | None = None  # None이면 첫 번째 part 사용
    original_text: str  # 분리된 원문 텍스트 (연속)


class PdfApplyRequest(BaseModel):
    """PDF 분리 결과를 문서에 적용하는 요청."""

    doc_id: str
    part_id: str | None = None  # None이면 첫 번째 part 사용
    results: list[dict]  # [{page_num, original_text, ...}]
    page_mapping: list[dict] | None = None  # [{source_page, target_page, part_id}]
    save_translation_to_l6: bool = False
    strip_punctuation: bool = True
    strip_hyeonto: bool = True


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
    """교정 저장 요청 본문. corrections.schema.json 형식.

    자유편집 모드에서는 corrected_text를 보내고,
    서버가 원본과 diff하여 corrections를 자동 생성한다.
    글자교정 모드에서는 기존처럼 corrections만 보낸다.
    """

    part_id: str | None = None
    corrected_text: str | None = None  # 자유편집 모드에서 편집된 전문
    corrections: list[CorrectionItem] = []


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


class DocumentBibFromUrlRequest(BaseModel):
    """문서에 URL로 서지정보를 가져와 바로 저장하는 요청 본문."""

    url: str


class BibliographyFromUrlRequest(BaseModel):
    """URL에서 서지정보를 가져오는 요청 본문."""

    url: str


class ParserSearchRequest(BaseModel):
    """파서 검색 요청 본문."""

    query: str
    cnt: int = 10
    mediatype: int | None = None


class ParserMapRequest(BaseModel):
    """파서 매핑 요청 본문. 검색 결과의 raw 데이터를 전달한다."""

    raw_data: dict


class ParserFetchAndMapRequest(BaseModel):
    """상세 조회 + 매핑 결합 요청 본문."""

    item_id: str


# ── 헬퍼 함수 ─────────────────────────────────


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


# ── 문헌 CRUD API ──────────────────────────────


@router.get("/api/documents")
async def api_documents():
    """서고의 문헌 목록을 반환한다."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    return list_documents(_library_path)


@router.delete("/api/documents/{doc_id}")
async def api_delete_document(doc_id: str):
    """문헌을 휴지통(.trash/documents/)으로 이동한다.

    목적: 문헌 폴더를 영구 삭제하지 않고 서고 내 .trash/로 옮긴다.
    응답에 related_interpretations가 포함되므로
    프론트엔드에서 연관 해석 저장소 경고를 표시할 수 있다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    try:
        result = trash_document(_library_path, doc_id)
        return result
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except PermissionError as e:
        return JSONResponse(
            {
                "error": (
                    f"파일이 사용 중이라 삭제할 수 없습니다.\n원인: {e}\n"
                    "→ 해결: 해당 폴더를 사용 중인 프로그램을 닫고 다시 시도하세요."
                )
            },
            status_code=500,
        )
    except Exception as e:
        return JSONResponse(
            {"error": f"삭제 중 오류가 발생했습니다: {e}"},
            status_code=500,
        )


# =========================================
#   Phase 10: URL → 문헌 자동 생성 API
# =========================================


@router.post("/api/documents/preview-from-url")
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
    _library_path = get_library_path()
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

    # 3. 에셋 목록 조회
    # - 전용 에셋 다운로더가 있는 파서 → list_assets() 사용
    # - 없는 파서(NDL, KORCIS 등) → URL 자체가 PDF/이미지인지 폴백 감지
    assets = []
    if fetcher.supports_asset_download:
        try:
            assets = await fetcher.list_assets(raw_data)
        except Exception as e:
            # 에셋 목록 실패는 치명적이지 않음 — 경고만
            assets = []
            bibliography.setdefault("_warnings", []).append(f"에셋 목록 조회 실패: {e}")
    else:
        # 폴백: URL 자체가 다운로드 가능한 파일(PDF/이미지)인지 확인
        try:
            from parsers.asset_detector import detect_direct_download

            direct = await detect_direct_download(url)
            if direct:
                assets = [direct]
        except Exception as e:
            logger.debug(f"폴백 에셋 감지 실패 (무시): {e}")

    # 4. doc_id 후보 생성
    title = bibliography.get("title", "")
    suggested_doc_id = _suggest_doc_id(title) if title else "untitled"

    return {
        "parser_id": parser_id,
        "bibliography": bibliography,
        "assets": assets,
        "suggested_doc_id": suggested_doc_id,
    }


@router.post("/api/documents/create-from-url")
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
    _library_path = get_library_path()
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


# --- 진단 ---


@router.get("/api/documents/{doc_id}/_diag")
async def api_diagnose_document(doc_id: str):
    """문헌 디스크 상태를 한 번에 진단해 반환한다.

    목적: 사용자 환경에서 PDF가 깨진 원인(LFS pointer 변환, PDF 헤더 손상, hook 미작동 등)을
          서버 측에서 검사해 한 번에 보고한다. 사용자에게 메모장으로 파일 열어보라고
          시키지 않고도 진단할 수 있게 한다.

    출력:
        {
            "document_id": str,
            "doc_path": str,
            "manifest_parts": [...],
            "gitattributes": "...",
            "hooks_path": "...",
            "hooks_dir_files": [...],
            "files": [
                {
                    "name": "...",
                    "size": int,
                    "head_hex": "25504446...",
                    "head_text": "%PDF-1.7\\n...",
                    "is_pdf": bool,
                    "is_lfs_pointer": bool,
                    "fitz_page_count": int | None,
                    "fitz_error": str | None
                },
                ...
            ]
        }
    """
    import json as _json

    import fitz
    import git

    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    # require_repo_path가 doc_id 형식(경로 트래버설)까지 검증한다
    doc_path = require_repo_path("documents", doc_id)
    if not doc_path.exists():
        return JSONResponse({"error": f"문헌 없음: {doc_id}"}, status_code=404)

    # 절대 경로는 노출하지 않는다 — 사용자가 진단 결과를 외부(이슈 트래커 등)에
    # 공유할 때 사용자명/홈 디렉터리 경로가 함께 새지 않도록 상대 경로로 표시한다.
    # 로컬 머신에서는 이미 디스크 접근 권한이 있어 정보 가치가 없다.
    out: dict = {
        "document_id": doc_id,
        "doc_path": f"documents/{doc_id}",
    }

    # manifest
    mp = doc_path / "manifest.json"
    if mp.exists():
        try:
            out["manifest_parts"] = _json.loads(mp.read_text(encoding="utf-8")).get("parts")
        except Exception as e:  # noqa: BLE001
            out["manifest_error"] = str(e)

    # .gitattributes
    gatt = doc_path / ".gitattributes"
    if gatt.exists():
        out["gitattributes"] = gatt.read_text(encoding="utf-8")

    # .gitignore
    gign = doc_path / ".gitignore"
    if gign.exists():
        out["gitignore"] = gign.read_text(encoding="utf-8")

    # git config: core.hooksPath — 활성/비활성 여부만 표시 (절대 경로 숨김)
    try:
        repo = git.Repo(doc_path)
        cr = repo.config_reader()
        try:
            hooks_path_raw = cr.get_value("core", "hooksPath")
            # 우리 라우터가 설정한 비활성 디렉터리(.git/no-hooks)인지만 판별해 노출
            out["hooks_path"] = (
                "<disabled: .git/no-hooks>"
                if hooks_path_raw and "no-hooks" in str(hooks_path_raw)
                else "<custom>"
            )
        except Exception:
            out["hooks_path"] = None
    except Exception as e:  # noqa: BLE001
        out["git_error"] = str(e)

    # 실제 .git/hooks 또는 hooksPath 디렉터리 안 파일 (LFS hook이 살아있는지 확인)
    hooks_dir = doc_path / ".git" / "hooks"
    if hooks_dir.exists():
        out["hooks_dir_files"] = [p.name for p in sorted(hooks_dir.iterdir()) if p.is_file()]

    # L1_source 파일 진단
    l1 = doc_path / "L1_source"
    files_info = []
    if l1.exists():
        for f in sorted(l1.iterdir()):
            if not f.is_file():
                continue
            try:
                head = f.read_bytes()[:48]
            except Exception as e:  # noqa: BLE001
                files_info.append({"name": f.name, "read_error": str(e)})
                continue
            info = {
                "name": f.name,
                "size": f.stat().st_size,
                "head_hex": head.hex(),
                "head_text": head.decode("ascii", errors="replace"),
                "is_pdf": head.startswith(b"%PDF"),
                "is_lfs_pointer": head.startswith(b"version https://git-lfs"),
            }
            if info["is_pdf"]:
                try:
                    with fitz.open(f) as d:
                        info["fitz_page_count"] = d.page_count
                except Exception as e:  # noqa: BLE001
                    info["fitz_error"] = str(e)
            files_info.append(info)
    out["files"] = files_info

    return out


# --- 로컬 파일에서 새 문헌 생성 ---


@router.post("/api/documents/create-from-files")
async def api_create_from_files(
    doc_id: str | None = Form(None),
    title: str | None = Form(None),
    files: list[UploadFile] = File(...),
):
    """로컬 이미지/PDF로 새 문헌을 생성한다.

    doc_id를 비워 보내면 서버가 자동 생성한다 (드래그 앤 드롭 온보딩용):
        첫 파일 이름에서 ASCII 후보를 만들고, 한자/한글뿐이라 후보가 비면
        doc_YYYYMMDD를 쓰며, 기존 문헌과 겹치면 _2, _3...을 붙인다.
        연구자가 영문 ID를 억지로 지어내지 않아도 되게 하기 위함이다.

    동작 (클라이언트가 보낸 순서를 그대로 보존):
        - 이미지(.jpg/.jpeg/.png/.tif/.tiff)들은 한 묶음으로 PIL이
          PDF로 합쳐 L1_source/<doc_id>.pdf로 저장. manifest에 part 1개,
          page_count = 이미지 개수.
        - PDF(.pdf)들은 각각 별도 part. PyMuPDF(fitz)로 page_count 산출.
        - 혼합 시: 이미지 묶음 PDF 1개(part 1) + 각 PDF 1개씩 추가 part.

    왜 이미지를 PDF로 묶는가:
        사이드바 트리는 part 클릭 시 PDF.js로 part.file을 로드해 페이지를
        펼친다. 이미지를 그대로 두면 PDF.js가 못 열어 페이지가 안 나온다.
        Pillow는 이미 의존성에 있어 추가 라이브러리 없이 해결된다.

    왜 add_document로 빈 문헌부터 만드는가:
        디렉터리 골격 + .gitignore/.gitattributes(LFS) + 첫 git commit +
        bibliography 골격을 그대로 재사용하기 위해서다. 그 위에 우리가
        L1_source/만 채우고 manifest.parts를 다시 쓴 뒤 두 번째 commit한다.
    """
    import json
    import shutil
    import tempfile

    import fitz  # PyMuPDF — PDF 생성/페이지 수 파악
    import git

    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    if not files:
        return JSONResponse(
            {"error": "최소 한 개 이상의 파일을 업로드하세요."},
            status_code=400,
        )

    doc_id = (doc_id or "").strip()
    if not doc_id:
        # 자동 생성 — 첫 파일 이름에서 후보를 만든다.
        # basename만 취해 경로 트래버설을 차단한 뒤 stem을 소독한다.
        first_name = Path(files[0].filename or "").name
        base = _suggest_doc_id(Path(first_name).stem) if first_name else ""
        if not base:
            # 파일명이 한자/한글뿐이면 후보가 비므로 날짜 기반으로 대체
            from datetime import datetime as _dt

            base = "doc_" + _dt.now().strftime("%Y%m%d")
        base = base[:60]  # 충돌 접미사(_2 등)를 붙일 여유를 남긴다
        docs_dir = Path(_library_path) / "documents"
        doc_id = base
        n = 1
        while (docs_dir / doc_id).exists():
            n += 1
            doc_id = f"{base}_{n}"
    # doc_id 형식 검증을 라우터 진입점에서 즉시 — temp 파일/디렉터리 이름에 사용되기
    # 전에 차단해야 ../ 등 경로 트래버설 위험을 막을 수 있다.
    # add_document에도 같은 검증이 있지만 그건 디렉터리 생성 시점이라 늦다.
    # 자동 생성된 doc_id도 같은 검증을 통과시킨다 (구성상 항상 통과하지만,
    # _suggest_doc_id 변경 시 여기가 최후 방어선이 된다). 규칙 정본: core/repo_id.py.
    if not is_valid_repo_id(doc_id):
        return JSONResponse(
            {
                "error": (
                    f"문헌 ID 형식이 올바르지 않습니다: {doc_id!r}\n→ {REPO_ID_RULE_TEXT}"
                )
            },
            status_code=400,
        )

    image_suffixes = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    allowed_suffixes = image_suffixes | {".pdf"}

    # 흐름:
    #   1) 모든 업로드를 임시 디렉터리에 풀고
    #   2) 이미지 → PyMuPDF로 한 권의 PDF로 묶고 (임시 폴더 안에서)
    #   3) PDF는 그대로 임시 폴더에 두고
    #   4) **검증 모두 통과한 뒤** add_document(files=[모두]) 한 번 호출
    #      → L1_source 채움 + git init/commit
    #   5) manifest.parts를 우리 의도(이미지묶음=vol1, 각 PDF=별도 vol)로 교체
    # 왜 add_document 호출을 마지막으로 미루는가:
    #   변환 실패 시 doc_path가 아직 만들어지지 않아 부분 생성 상태가 남지 않는다.
    #   Windows에서는 git이 .git/ 내부 핸들을 잡고 있어 rmtree가 부분적으로 실패할 수 있는데,
    #   애초에 doc_path를 만들지 않으면 그 위험이 사라진다.
    tmp_dir = Path(tempfile.mkdtemp(prefix="ctb_create_from_files_"))
    try:
        img_dir = tmp_dir / "images"
        pdf_dir = tmp_dir / "pdfs"
        img_dir.mkdir()
        pdf_dir.mkdir()

        # 1. 입력 분류 — 클라이언트가 보낸 순서가 페이지 순서가 된다
        image_paths: list[Path] = []
        # (저장명, 원본 라벨, tmp 경로) — 저장명은 ASCII로 안전하게, 라벨은 원본 stem
        pdf_inputs: list[tuple[str, str, Path]] = []
        # 이미지 묶음 PDF는 항상 <doc_id>.pdf로 저장될 예정이라 미리 예약.
        # 사용자가 같은 이름의 PDF를 첨부하면 충돌로 거절된다.
        seen_pdf_storage_names: set[str] = {f"{doc_id}.pdf"}
        pdf_idx = 0  # PDF별 영문 인덱스 (한국어 등 비ASCII 파일명 회피용)

        for idx, upload in enumerate(files):
            raw_name = upload.filename or "file"
            safe_name = Path(raw_name).name  # basename만 (경로 트래버설 방지)
            if not safe_name:
                continue
            suffix = Path(safe_name).suffix.lower()
            if suffix not in allowed_suffixes:
                return JSONResponse(
                    {
                        "error": (
                            f"지원하지 않는 파일 형식입니다: {safe_name}\n"
                            "→ 해결: PDF, JPG, JPEG, PNG, TIF, TIFF만 가능합니다."
                        )
                    },
                    status_code=400,
                )
            # 1) 임시 디스크에 스트리밍 저장 (메모리 폭주 회피)
            #    upload.file은 SpooledTemporaryFile — shutil.copyfileobj가 큰 파일도
            #    청크 단위로 복사한다. 한 번에 전부 메모리에 올리지 않는다.
            if suffix in image_suffixes:
                tmp_path = img_dir / f"{idx:04d}_{safe_name}"
            else:
                # PDF 저장 파일명을 ASCII로 강제. 왜:
                #   Windows + Git 환경에서 비ASCII 파일명이 git filter를 거치며
                #   working tree에 영향을 줄 위험 + 다양한 파일시스템 호환성.
                #   파일 시스템에 저장하는 이름은 ASCII로 통일하고, 원본 이름은
                #   manifest.label로 보존해 사용자에게는 원래 이름이 보이게 한다.
                pdf_idx += 1
                ext = Path(safe_name).suffix or ".pdf"
                try:
                    safe_name.encode("ascii")
                    storage_name = safe_name
                except UnicodeEncodeError:
                    storage_name = f"{doc_id}_pdf{pdf_idx}{ext}"

                if storage_name in seen_pdf_storage_names:
                    return JSONResponse(
                        {
                            "error": (
                                f"같은 이름의 PDF가 두 번 포함되었습니다: {safe_name}\n"
                                "→ 해결: 파일 이름을 다르게 하거나 한 번만 선택하세요."
                            )
                        },
                        status_code=400,
                    )
                seen_pdf_storage_names.add(storage_name)
                tmp_path = pdf_dir / storage_name

            # 스트림 복사
            try:
                upload.file.seek(0)
            except Exception:
                pass
            with open(tmp_path, "wb") as out_fp:
                shutil.copyfileobj(upload.file, out_fp, length=1024 * 1024)

            # 2) 저장 후 헤더만 다시 읽어 검증 (메모리 부담 거의 없음)
            with open(tmp_path, "rb") as in_fp:
                head = in_fp.read(8)
            file_size = tmp_path.stat().st_size

            if file_size == 0:
                return JSONResponse(
                    {
                        "error": (
                            f"업로드 콘텐츠가 비어 있습니다: {safe_name}\n"
                            "→ 가능한 원인: 브라우저가 파일을 못 읽음, 또는 안티바이러스 차단."
                        )
                    },
                    status_code=400,
                )
            if suffix == ".pdf" and not head.startswith(b"%PDF"):
                return JSONResponse(
                    {
                        "error": (
                            f"업로드된 PDF가 정상 PDF 형식이 아닙니다: {safe_name}\n"
                            f"파일 크기: {file_size:,} bytes, 첫 8바이트: {head.hex()}\n"
                            "→ 가능한 원인:\n"
                            "  1) 안티바이러스(Windows Defender 등)가 PDF를 검역해 NULL로 변환\n"
                            "  2) 브라우저 확장(보안/번역/광고차단)이 업로드를 가로채 변조\n"
                            "  3) 원본 PDF 파일 자체가 손상\n"
                            "→ 해결: 같은 PDF를 메모장으로 열어 첫 줄이 '%PDF-'로 시작하는지 "
                            "먼저 확인하세요. NULL로 보이면 (1)/(2)가 원인입니다."
                        )
                    },
                    status_code=400,
                )

            if suffix in image_suffixes:
                image_paths.append(tmp_path)
            else:
                original_stem = Path(safe_name).stem
                pdf_inputs.append((storage_name, original_stem, tmp_path))

        if not image_paths and not pdf_inputs:
            return JSONResponse({"error": "유효한 파일이 없습니다."}, status_code=400)

        # 제목이 비면 첫 파일의 원본 이름(stem)을 쓴다 — 한자/한글 제목이 그대로
        # 보존되므로, ASCII로 소독된 doc_id보다 연구자에게 훨씬 유용하다.
        first_stem = Path(Path(files[0].filename or "").name).stem
        effective_title = (title or "").strip() or first_stem or doc_id

        # 2. 이미지 → PyMuPDF로 PDF 묶기 (임시 폴더 안에서)
        # 왜 PIL 대신 PyMuPDF인가:
        #   PIL의 multi-page PDF 출력은 PDF.js 일부 버전에서 "Invalid PDF structure"로
        #   거절될 수 있다. PyMuPDF는 PDF 1.7 사양을 생성하므로 PDF.js 호환성이 가장 좋다.
        prepared_files: list[Path] = []
        part_meta: list[dict] = []  # [{label, file_basename, page_count}]

        if image_paths:
            images_pdf = tmp_dir / f"{doc_id}.pdf"
            try:
                pdf_doc = fitz.open()
                try:
                    for p in image_paths:
                        pix = fitz.Pixmap(str(p))
                        try:
                            # CMYK 등 4채널은 RGB로 변환 (PDF.insert_image 안정성)
                            if pix.colorspace and pix.colorspace.n >= 4:
                                pix = fitz.Pixmap(fitz.csRGB, pix)
                            page = pdf_doc.new_page(width=pix.width, height=pix.height)
                            page.insert_image(page.rect, pixmap=pix)
                        finally:
                            pix = None  # noqa: F841 — 명시적 해제
                    # 가장 보수적인 옵션 — 일부 PDF.js 버전(3.11)이 garbage 컬렉션이나
                    # deflate 스트림에 까다로울 수 있어 디폴트 평이한 PDF로 저장한다.
                    pdf_doc.save(str(images_pdf))
                finally:
                    pdf_doc.close()
            except Exception as e:  # noqa: BLE001
                logger.exception("이미지 → PDF 변환 실패")
                return JSONResponse(
                    {
                        "error": (
                            f"이미지를 PDF로 묶는 중 오류: {e}\n"
                            "→ 해결: 이미지 파일이 손상되지 않았는지 확인하세요. "
                            "이미지 형식이 표준 JPG/PNG/TIFF인지도 확인하세요."
                        )
                    },
                    status_code=400,
                )
            prepared_files.append(images_pdf)
            part_meta.append(
                {
                    "label": effective_title,
                    "file_basename": images_pdf.name,
                    "page_count": len(image_paths),
                }
            )

        # 3. 각 PDF → 페이지 수 산출 + prepared_files에 추가
        for storage_name, original_label, src in pdf_inputs:
            try:
                with fitz.open(src) as pdf:
                    pc = pdf.page_count
            except Exception:
                # 손상된 PDF여도 일단 등록 — 사이드바가 PDF.js로 재시도한다.
                pc = None
            prepared_files.append(src)
            part_meta.append(
                {
                    "label": original_label,  # 사용자에게 보이는 이름은 원본 그대로
                    "file_basename": storage_name,  # 디스크 저장명은 ASCII 안전
                    "page_count": pc,
                }
            )

        # 4. add_document로 디렉터리 생성 + 파일 복사 + git init + 첫 commit (atomic)
        # add_document는 자체적으로 hooksPath를 비활성화하고 LFS filter를 끄므로
        # git hook 실패로 인한 예외는 발생하지 않는다. 따라서 일반적인 예외 처리만.
        try:
            doc_path = add_document(
                library_path=_library_path,
                title=effective_title,
                doc_id=doc_id,
                files=prepared_files,
            )
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except FileExistsError as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        except Exception as e:  # noqa: BLE001
            logger.exception("add_document 실패 — 디스크 정리")
            shutil.rmtree(
                Path(_library_path) / "documents" / doc_id,
                ignore_errors=True,
            )
            return JSONResponse(
                {"error": f"문헌 생성 실패: {e}"},
                status_code=502,
            )

        # 5. working tree의 PDF가 진짜 PDF 바이트인지 확인 (LFS pointer 방어)
        # 왜 검사하는가:
        #   git-lfs가 .gitattributes 룰에 따라 working tree를 LFS pointer로
        #   덮어씌우는 경우(특히 일부 git/lfs 조합에서 first commit 후), PDF.js가
        #   "Invalid PDF structure"로 거절한다. 디스크 파일이 %PDF로 시작 안 하면
        #   임시 폴더에 보관해둔 원본을 다시 복사해 working tree를 복원한다.
        l1 = doc_path / "L1_source"
        for meta, src in zip(part_meta, prepared_files):
            wt_path = l1 / meta["file_basename"]
            try:
                head = wt_path.read_bytes()[:8]
            except Exception:
                head = b""
            if not head.startswith(b"%PDF"):
                logger.warning(
                    f"working tree {wt_path.name} not PDF (head={head!r}) — 임시본으로 복원"
                )
                try:
                    shutil.copy2(src, wt_path)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"복원 실패 (계속 진행): {e}")

        # 6. manifest.parts 교체 (add_document가 파일별 vol1, vol2... 로 채운 것을
        #    우리 의도: 이미지묶음=vol1, 각 PDF=vol2,vol3...로 정리)
        parts = []
        for i, meta in enumerate(part_meta, start=1):
            parts.append(
                {
                    "part_id": f"vol{i}",
                    "label": meta["label"],
                    "file": f"L1_source/{meta['file_basename']}",
                    "page_count": meta["page_count"],
                }
            )

        manifest_path = doc_path / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["parts"] = parts
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 7. manifest 변경분 commit (LFS 후크 부재 등은 비치명적)
        try:
            repo = git.Repo(doc_path)
            repo.git.add("-A")
            if repo.git.diff("--cached", "--name-only"):
                n_imgs = len(image_paths)
                n_pdfs = len(pdf_inputs)
                repo.index.commit(f"feat: 로컬 파일 추가 — 이미지 {n_imgs}장, PDF {n_pdfs}개")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"git commit 경고 (무시): {e}")

        return {
            "document_id": doc_id,
            "doc_path": str(doc_path),
            "title": effective_title,
            "asset_count": len(image_paths) + len(pdf_inputs),
            "image_count": len(image_paths),
            "pdf_count": len(pdf_inputs),
            "parts": parts,
            "mode": "create_from_files",
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# --- HWP 가져오기 ---


@router.post("/api/documents/preview-hwp")
async def api_preview_hwp(file: UploadFile = File(...)):
    """HWP/HWPX 파일을 미리보기한다.

    목적: 가져오기 전에 파일 내용과 표점·현토 감지 결과를 확인한다.
    입력: multipart/form-data로 HWP/HWPX 파일 업로드.
    출력:
        {
            "metadata": {title, author, format, ...},
            "text_preview": str (앞부분 500자),
            "sections_count": int,
            "detected_punctuation": bool,
            "detected_hyeonto": bool,
            "sample_clean_text": str (첫 섹션의 정리 결과),
        }
    """
    import tempfile

    from hwp.reader import detect_format, get_reader
    from hwp.text_cleaner import clean_hwp_text

    # 업로드된 파일을 임시 파일로 저장
    suffix = Path(file.filename or "").suffix or ".hwpx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # 형식 감지
        fmt = detect_format(tmp_path)
        if fmt is None:
            return JSONResponse(
                {"error": f"지원하지 않는 파일 형식입니다: {suffix}"},
                status_code=400,
            )

        # 텍스트 추출
        reader = get_reader(tmp_path)
        metadata = reader.extract_metadata()

        if hasattr(reader, "extract_sections"):
            sections = reader.extract_sections()
            full_text = "\n\n".join(s["text"] for s in sections)
            sections_count = len(sections)
        else:
            full_text = reader.extract_text()
            sections_count = len([t for t in full_text.split("\n\n") if t.strip()])

        # 표점·현토 감지 (샘플)
        sample_text = full_text[:2000]
        sample_result = clean_hwp_text(sample_text)

        return {
            "metadata": metadata,
            "text_preview": full_text[:500],
            "full_text_length": len(full_text),
            "sections_count": sections_count,
            "detected_punctuation": sample_result.had_punctuation,
            "detected_hyeonto": sample_result.had_hyeonto,
            "detected_taidu": sample_result.had_taidu,
            "sample_clean_text": sample_result.clean_text[:500],
            "punct_count": len(sample_result.punctuation_marks),
            "hyeonto_count": len(sample_result.hyeonto_annotations),
        }
    except Exception as e:
        return JSONResponse(
            {"error": f"HWP 파일 읽기 실패: {e}"},
            status_code=400,
        )
    finally:
        # 임시 파일 정리
        try:
            tmp_path.unlink()
        except OSError:
            pass


@router.post("/api/documents/import-hwp")
async def api_import_hwp(
    file: UploadFile = File(...),
    doc_id: str = Form(...),
    title: str = Form(None),
    page_mapping: str = Form(None),
    strip_punctuation: bool = Form(True),
    strip_hyeonto: bool = Form(True),
):
    """HWP/HWPX 파일에서 텍스트를 가져온다.

    목적: HWP 텍스트를 기존 문서의 L4에 가져오거나, 새 문헌을 생성한다.
    입력: multipart/form-data
        file — HWP/HWPX 파일
        doc_id — 문헌 ID
        title — 제목 (선택, 새 문헌 생성 시)
        page_mapping — JSON 문자열 (선택, 시나리오 1의 섹션↔페이지 매핑)
        strip_punctuation — 표점 제거 여부 (기본 true)
        strip_hyeonto — 현토 제거 여부 (기본 true)
    모드 자동 판별:
        - doc_id가 이미 존재하면 → 시나리오 1 (기존 문서에 텍스트 가져오기)
        - doc_id가 없으면 → 시나리오 2 (새 문헌 생성)
    출력: {document_id, title, mode, pages_saved, text_pages, cleaned_stats}
    """
    import tempfile

    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    if not doc_id or not doc_id.strip():
        return JSONResponse({"error": "doc_id가 비어있습니다."}, status_code=400)
    doc_id = doc_id.strip()

    # page_mapping JSON 파싱
    parsed_mapping = None
    if page_mapping:
        try:
            parsed_mapping = json.loads(page_mapping)
        except json.JSONDecodeError:
            return JSONResponse(
                {"error": "page_mapping이 올바른 JSON이 아닙니다."},
                status_code=400,
            )

    # 업로드된 파일을 임시 파일로 저장
    suffix = Path(file.filename or "").suffix or ".hwpx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        doc_path = require_repo_path("documents", doc_id)
        manifest_path = doc_path / "manifest.json"

        if doc_path.exists() and manifest_path.exists():
            # 시나리오 1: 기존 문서에 텍스트 가져오기
            # manifest.json이 있는 정상 문헌에만 적용한다.
            result = import_hwp_text_to_document(
                library_path=_library_path,
                doc_id=doc_id,
                hwp_file=tmp_path,
                page_mapping=parsed_mapping,
                strip_punctuation=strip_punctuation,
                strip_hyeonto=strip_hyeonto,
            )
        else:
            # 시나리오 2: 새 문헌 생성
            # 디렉토리만 있고 manifest가 없으면 (이전 가져오기 실패 잔재)
            # 기존 디렉토리를 백업 이름으로 변경 후 새로 생성한다.
            if doc_path.exists() and not manifest_path.exists():
                import time as _time

                backup_name = f"{doc_id}_incomplete_{int(_time.time())}"
                backup_path = doc_path.parent / backup_name
                doc_path.rename(backup_path)
                logging.getLogger(__name__).warning(
                    "manifest 없는 불완전 문헌 디렉토리 발견: %s → %s 로 백업",
                    doc_path,
                    backup_path,
                )
            result = create_document_from_hwp(
                library_path=_library_path,
                hwp_file=tmp_path,
                doc_id=doc_id,
                title=title,
                strip_punctuation=strip_punctuation,
                strip_hyeonto=strip_hyeonto,
            )

        return result
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except FileExistsError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse(
            {"error": f"HWP 가져오기 실패: {e}"},
            status_code=500,
        )
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


@router.post("/api/documents/{doc_id}/match-hwp-to-blocks")
async def api_match_hwp_to_blocks(doc_id: str, body: MatchHwpToBlocksRequest):
    """페이지 텍스트를 LayoutBlock 단위로 매칭한다 (2단계).

    목적: 1단계(페이지 매핑) 완료 후, 레이아웃 분석(L3)이 있으면
          HWP 텍스트를 LayoutBlock 단위로 분할·매칭한다.
    전제: 레이아웃 분석(L3) 완료.
    입력: {
        "part_id": "vol1",
        "page_num": 1,
        "block_text_mapping": [
            {"layout_block_id": "p01_b01", "text": "天地之道..."},
            ...
        ]
    }
    출력: {matched_blocks, ocr_result_saved}
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    try:
        result = match_hwp_text_to_layout_blocks(
            library_path=_library_path,
            doc_id=doc_id,
            part_id=body.part_id,
            page_num=body.page_num,
            block_text_mapping=body.block_text_mapping,
        )
        return result
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse(
            {"error": f"블록 매칭 실패: {e}"},
            status_code=500,
        )


# --- PDF 참조 텍스트 추출 (Part D) ---


@router.post("/api/text-import/pdf/analyze")
async def api_pdf_analyze(file: UploadFile = File(...)):
    """PDF 텍스트 레이어를 분석한다.

    목적: PDF에 텍스트 레이어가 있는지 확인하고,
          첫 몇 페이지의 텍스트를 추출하여 구조 분석(LLM)을 수행한다.
    입력: multipart/form-data로 PDF 파일 업로드.
    출력:
        {
            "page_count": int,
            "has_text_layer": bool,
            "sample_pages": [{page_num, text, char_count}, ...],
            "detected_structure": {pattern_type, original_markers, ...} | null,
        }
    """
    import tempfile

    from text_import.pdf_extractor import PdfTextExtractor

    suffix = Path(file.filename or "").suffix or ".pdf"
    if suffix.lower() != ".pdf":
        return JSONResponse(
            {"error": f"PDF 파일만 지원합니다 (받은 형식: {suffix})"},
            status_code=400,
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        extractor = PdfTextExtractor(tmp_path)
        has_text = extractor.has_text_layer()
        page_count = extractor.page_count
        sample_pages = extractor.get_sample_text(max_pages=3)

        # 텍스트 레이어가 있으면 LLM으로 구조 분석 시도
        detected_structure = None
        llm_router = _get_llm_router()
        if has_text and llm_router is not None:
            try:
                from text_import.text_separator import TextSeparator

                separator = TextSeparator(llm_router)
                structure = await separator.analyze_structure(sample_pages)
                detected_structure = structure.to_dict()
            except Exception as e:
                logging.getLogger(__name__).warning("구조 분석 실패 (비치명적): %s", e)

        extractor.close()

        return {
            "page_count": page_count,
            "has_text_layer": has_text,
            "sample_pages": sample_pages,
            "detected_structure": detected_structure,
        }
    except Exception as e:
        return JSONResponse(
            {"error": f"PDF 분석 실패: {e}"},
            status_code=400,
        )
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


@router.post("/api/text-import/hwp/separate")
async def api_hwp_separate(
    file: UploadFile = File(...),
):
    """HWP 텍스트를 유니코드 문자 유형(한자/한글) 기반으로 원문/번역 분리한다.

    목적: HWP에서 추출한 혼합 텍스트(한문 원문 + 한국어 번역이 뒤섞인 경우)를
          regex \\p{Han}/\\p{Hangul} 유니코드 카테고리로 줄 단위 분류하여 분리한다.
    입력: multipart/form-data로 HWP/HWPX 파일 업로드
    출력:
        {
            "method": "unicode_script",
            "stats": {total_lines, original_lines, translation_lines, ...},
            "results": [{page_num, original_text, translation_text}]
        }

    왜 규칙 기반인가:
      한문(漢字)과 한글(Hangul)은 유니코드 블록이 완전히 다르다.
      LLM 없이 각 줄의 \\p{Han} vs \\p{Hangul} 비율만으로 정확하게 분류할 수 있다.
      LLM은 느리고, 비용이 들고, 500자 제한 등 문제가 있었다.
    """
    import tempfile

    from hwp.reader import get_reader
    from text_import.common import separate_by_script

    suffix = Path(file.filename or "").suffix or ".hwpx"
    if suffix.lower() not in (".hwp", ".hwpx"):
        return JSONResponse(
            {"error": f"HWP/HWPX 파일만 지원합니다 (받은 형식: {suffix})"},
            status_code=400,
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # HWP에서 전체 텍스트 추출
        reader = get_reader(tmp_path)
        if hasattr(reader, "extract_sections"):
            sections = reader.extract_sections()
            full_text = "\n\n".join(s["text"] for s in sections)
        else:
            full_text = reader.extract_text()

        if not full_text.strip():
            return JSONResponse({"error": "텍스트가 비어 있습니다."}, status_code=400)

        # 유니코드 문자 유형 기반 분리
        sep_result = separate_by_script(full_text)

        return {
            "method": "unicode_script",
            "stats": sep_result["stats"],
            "results": [
                {
                    "page_num": 1,
                    "original_text": sep_result["original_text"],
                    "translation_text": sep_result["translation_text"],
                }
            ],
        }
    except Exception as e:
        logging.getLogger(__name__).exception("HWP 텍스트 분리 실패")
        return JSONResponse(
            {"error": f"텍스트 분리 실패: {e}"},
            status_code=500,
        )
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


@router.post("/api/text-import/pdf/separate")
async def api_pdf_separate(
    file: UploadFile = File(...),
    body: str = Form("{}"),
):
    """PDF 텍스트를 유니코드 문자 유형(한자/한글) 기반으로 원문/번역 분리한다.

    목적: PDF 각 페이지의 텍스트를 regex \\p{Han}/\\p{Hangul}로 줄 단위 분류하여
          원문과 번역을 분리한다. LLM 불필요.
    입력:
        file — PDF 파일 (multipart)
        body — JSON 문자열 (호환용, 무시해도 됨)
    출력:
        {
            "method": "unicode_script",
            "page_count": int,
            "stats": {total_lines, original_lines, translation_lines, ...},
            "results": [{page_num, original_text, translation_text}, ...]
        }

    왜 규칙 기반인가:
      한문(漢字)과 한글(Hangul)은 유니코드 블록이 완전히 다르다.
      LLM 없이 각 줄의 \\p{Han} vs \\p{Hangul} 비율만으로 정확하게 분류할 수 있다.
      LLM은 느리고, 비용이 들고, API 키 미설정 시 사용 불가했다.
    """
    import tempfile

    from text_import.common import separate_by_script

    suffix = Path(file.filename or "").suffix or ".pdf"
    if suffix.lower() != ".pdf":
        return JSONResponse(
            {"error": f"PDF 파일만 지원합니다 (받은 형식: {suffix})"},
            status_code=400,
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        from text_import.pdf_extractor import PdfTextExtractor

        extractor = PdfTextExtractor(tmp_path)
        pages = extractor.extract_all_pages()
        page_count = extractor.page_count
        extractor.close()

        # 페이지별 유니코드 문자 유형 기반 분리
        results = []
        total_stats = {
            "total_lines": 0,
            "original_lines": 0,
            "translation_lines": 0,
            "skipped_lines": 0,
        }

        for page in pages:
            text = page.get("text", "").strip()
            if not text:
                results.append(
                    {
                        "page_num": page["page_num"],
                        "original_text": "",
                        "translation_text": "",
                    }
                )
                continue

            sep = separate_by_script(text)
            results.append(
                {
                    "page_num": page["page_num"],
                    "original_text": sep["original_text"],
                    "translation_text": sep["translation_text"],
                }
            )

            # 통계 누적
            for key in total_stats:
                total_stats[key] += sep["stats"].get(key, 0)

        return {
            "method": "unicode_script",
            "page_count": page_count,
            "stats": total_stats,
            "results": results,
        }
    except Exception as e:
        logging.getLogger(__name__).exception("PDF 텍스트 분리 실패")
        return JSONResponse(
            {"error": f"텍스트 분리 실패: {e}"},
            status_code=500,
        )
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


@router.post("/api/text-import/align-preview")
async def api_align_preview(body: AlignPreviewRequest):
    """외부 텍스트를 기존 문헌의 OCR/L4 텍스트와 한자 앵커로 대조하여 페이지 매핑을 미리 보여준다.

    목적: 기존 문헌(PDF/이미지)에 외부 HWP/PDF 텍스트를 붙일 때,
          어느 텍스트가 어느 페이지에 해당하는지 자동으로 알아낸다.
    입력: AlignPreviewRequest {doc_id, part_id, original_text}
    출력:
        {
            "page_count": int,
            "alignments": [{page_num, matched_text, ocr_preview, confidence, anchor}, ...]
        }

    왜 이렇게 하는가:
      기존 문헌에 이미 OCR 텍스트가 있으면, 외부 텍스트의 어느 부분이
      어느 페이지인지 한자 시퀀스 매칭으로 자동 대조할 수 있다.
      OCR 텍스트가 없으면 균등 분할로 폴백한다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", body.doc_id)
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌이 존재하지 않습니다: {body.doc_id}"},
            status_code=404,
        )

    try:
        from text_import.common import align_text_to_pages

        manifest = get_document_info(doc_path)
        parts = manifest.get("parts", [])
        if not parts:
            return JSONResponse({"error": "문헌에 part 정보가 없습니다."}, status_code=400)

        # part_id 결정
        part_id = body.part_id or parts[0]["part_id"]
        page_count = 0
        for p in parts:
            if p["part_id"] == part_id:
                page_count = p.get("page_count") or 0
                break

        if page_count == 0:
            return JSONResponse(
                {"error": f"part '{part_id}'의 페이지 수가 0이거나 part를 찾을 수 없습니다."},
                status_code=400,
            )

        # 각 페이지의 기존 L4 텍스트 조회
        page_texts: list[dict] = []
        for pg in range(1, page_count + 1):
            page_info = get_page_text(doc_path, part_id, pg)
            page_texts.append(
                {
                    "page_num": pg,
                    "text": page_info.get("text", ""),
                }
            )

        # 자동 매핑 실행
        alignments = align_text_to_pages(page_texts, body.original_text)

        return {
            "page_count": page_count,
            "part_id": part_id,
            "alignments": alignments,
        }
    except Exception as e:
        logging.getLogger(__name__).exception("텍스트 매핑 실패")
        return JSONResponse(
            {"error": f"텍스트 매핑 실패: {e}"},
            status_code=500,
        )


@router.post("/api/text-import/pdf/apply")
async def api_pdf_apply(body: PdfApplyRequest, background_tasks: BackgroundTasks):
    """PDF 분리 결과를 문서의 L4에 적용한다.

    목적: 사용자가 확인/수정한 분리 결과를 실제 문서에 저장한다.
    입력: PdfApplyRequest
    출력: {pages_saved, l4_files}
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", body.doc_id)
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌이 존재하지 않습니다: {body.doc_id}"},
            status_code=404,
        )

    try:
        from hwp.text_cleaner import clean_hwp_text
        from text_import.common import (
            save_formatting_sidecar,
            save_punctuation_sidecar,
            save_text_to_l4,
            save_translation_sidecar,
        )

        # 매니페스트에서 기본 part_id (body.part_id가 있으면 우선 사용)
        manifest = get_document_info(doc_path)
        parts = manifest.get("parts", [])
        default_part_id = body.part_id or (parts[0]["part_id"] if parts else "vol1")

        l4_files = []
        pages_saved = 0
        translations_saved = 0

        for item in body.results:
            page_num = item.get("page_num", 0)
            original_text = item.get("original_text", "")
            translation_text = item.get("translation_text", "")
            if not original_text.strip():
                continue

            # page_mapping이 있으면 대상 페이지/part 변환
            target_page = page_num
            target_part = default_part_id
            if body.page_mapping:
                for m in body.page_mapping:
                    if m.get("source_page") == page_num:
                        target_page = m.get("target_page", page_num)
                        target_part = m.get("part_id", default_part_id)
                        break

            # 표점·현토 분리 (옵션)
            if body.strip_punctuation or body.strip_hyeonto:
                result = clean_hwp_text(
                    original_text,
                    strip_punct=body.strip_punctuation,
                    strip_hyeonto=body.strip_hyeonto,
                )
                text_to_save = result.clean_text

                # 사이드카 데이터 저장
                save_punctuation_sidecar(
                    doc_path,
                    target_part,
                    target_page,
                    result.punctuation_marks,
                    result.hyeonto_annotations,
                    raw_text_length=len(original_text),
                    clean_text_length=len(result.clean_text),
                    source="pdf_import",
                )

                if result.taidu_marks:
                    save_formatting_sidecar(
                        doc_path,
                        target_part,
                        target_page,
                        result.taidu_marks,
                    )
            else:
                text_to_save = original_text

            # L4 텍스트 저장 (원문)
            file_path = save_text_to_l4(doc_path, target_part, target_page, text_to_save)
            l4_files.append(file_path.relative_to(doc_path).as_posix())
            pages_saved += 1

            # 번역 사이드카 저장 (분리된 번역이 있으면)
            if translation_text and translation_text.strip():
                tr_path = save_translation_sidecar(
                    doc_path,
                    target_part,
                    target_page,
                    translation_text,
                    source="text_import",
                )
                if tr_path:
                    l4_files.append(tr_path.relative_to(doc_path).as_posix())
                    translations_saved += 1

        # completeness_status 업데이트
        manifest["completeness_status"] = "text_imported"
        (doc_path / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # page_count 업데이트 — 사이드바에 페이지 목록이 뜨도록
        max_page = 0
        for item in body.results:
            pn = item.get("page_num", 0)
            if pn > max_page:
                max_page = pn
        if max_page > 0:
            for part in manifest.get("parts", []):
                if part["part_id"] == default_part_id:
                    existing = part.get("page_count") or 0
                    part["page_count"] = max(existing, max_page)
            (doc_path / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        # git commit (백그라운드)
        commit_msg = f"feat: 텍스트 가져오기 — {pages_saved}페이지"
        if translations_saved:
            commit_msg += f", 번역 {translations_saved}페이지"
        background_tasks.add_task(
            git_commit_document,
            doc_path,
            commit_msg,
        )

        return {
            "pages_saved": pages_saved,
            "translations_saved": translations_saved,
            "l4_files": l4_files,
        }
    except Exception as e:
        return JSONResponse(
            {"error": f"텍스트 적용 실패: {e}"},
            status_code=500,
        )


# ── 문헌 상세 / PDF / 텍스트 API ──────────────────


@router.get("/api/documents/{doc_id}")
async def api_document(doc_id: str):
    """특정 문헌의 정보를 반환한다 (manifest + pages)."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", doc_id)
    try:
        info = get_document_info(doc_path)
        info["pages"] = list_pages(doc_path)
        return info
    except FileNotFoundError:
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )


@router.get("/api/documents/{doc_id}/pdf/{part_id}")
async def api_document_pdf(doc_id: str, part_id: str):
    """문헌의 특정 권(part) PDF 파일을 반환한다.

    목적: 좌측 PDF 뷰어에서 원본 PDF를 렌더링하기 위해 파일을 서빙한다.
    입력:
        doc_id — 문헌 ID.
        part_id — 권 식별자 (예: "vol1").
    출력: PDF 파일 (application/pdf).
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", doc_id)
    try:
        pdf_path = get_pdf_path(doc_path, part_id)
        return FileResponse(
            str(pdf_path),
            media_type="application/pdf",
            filename=pdf_path.name,
        )
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.get("/api/documents/{doc_id}/pages/{page_num}/text")
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
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", doc_id)
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    try:
        return get_page_text(doc_path, part_id, page_num)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.put("/api/documents/{doc_id}/pages/{page_num}/text")
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
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", doc_id)
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


@router.get("/api/documents/{doc_id}/pages/{page_num}/layout")
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
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", doc_id)
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    try:
        return get_page_layout(doc_path, part_id, page_num)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.put("/api/documents/{doc_id}/pages/{page_num}/layout")
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
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", doc_id)
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


@router.get("/api/resources/block_types")
async def api_block_types():
    """블록 타입 어휘 목록을 반환한다.

    목적: 레이아웃 편집기에서 block_type 드롭다운을 채우기 위해 사용한다.
    출력: resources/block_types.json의 내용.
    """
    # src/app/routers/documents.py → parent.parent.parent.parent = 프로젝트 루트
    block_types_path = (
        Path(__file__).resolve().parent.parent.parent.parent / "resources" / "block_types.json"
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


@router.get("/api/documents/{doc_id}/pages/{page_num}/corrections")
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
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", doc_id)
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    try:
        return get_page_corrections(doc_path, part_id, page_num)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.put("/api/documents/{doc_id}/pages/{page_num}/corrections")
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
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", doc_id)
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    corrections_data = body.model_dump()

    # 자유편집 모드: corrected_text에서 diff로 corrections 자동 생성
    # 왜 서버에서 diff하는가:
    #   원본 텍스트(L4_text/pages/)는 서버에만 있다.
    #   프론트엔드가 원본을 가지고 있더라도, 서버가 직접 diff하면
    #   원본 기준이 확실하고, 프론트엔드 구현 오류로 인한 불일치를 방지한다.
    if body.corrected_text is not None:
        from core.document import (
            _diff_to_corrections,
            _merge_corrections,
            get_page_text,
        )
        from core.document import (
            get_page_corrections as _get_corrs,
        )

        try:
            text_result = get_page_text(doc_path, part_id, page_num)
            original_text = text_result["text"]
        except Exception:
            return JSONResponse(
                {"error": "원본 텍스트를 읽을 수 없습니다 (L4_text/pages/ 확인)."},
                status_code=400,
            )

        # CRLF → LF 정규화
        corrected_text = body.corrected_text.replace("\r\n", "\n")

        # diff → corrections 자동 생성
        auto_corrs = _diff_to_corrections(original_text, corrected_text, page_num)

        # 기존 corrections의 메타데이터(유형, 비고 등) 보존하며 병합
        existing = _get_corrs(doc_path, part_id, page_num)
        existing_corrs = existing.get("corrections", [])
        merged = _merge_corrections(auto_corrs, existing_corrs)

        corrections_data["corrections"] = merged
        corrections_data["corrected_text"] = corrected_text

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

    try:
        git_result = git_commit_document(
            doc_path,
            commit_msg,
            add_paths=[save_result.get("file_path", "")],
        )
    except Exception as e:
        git_result = {
            "committed": False,
            "message": f"git commit 실패: {e}",
        }

    save_result["git"] = git_result

    return save_result


# --- 교정 적용 텍스트 API (편성 탭용) ---


@router.get("/api/documents/{doc_id}/pages/{page_num}/corrected-text")
async def api_corrected_text(
    doc_id: str,
    page_num: int,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """교정이 적용된 텍스트를 반환한다.

    목적: 편성(composition) 탭에서 교정된 텍스트를 블록별로 표시하기 위해 사용한다.
          L4_text/pages/ 원본에 L4_text/corrections/ 교정 기록을 적용한 결과.
    입력:
        doc_id — 문헌 ID.
        page_num — 페이지 번호 (1부터 시작).
        part_id — 쿼리 파라미터, 권 식별자.
    출력: {document_id, part_id, page, original_text, corrected_text, correction_count, blocks}.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", doc_id)
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    try:
        return get_corrected_text(doc_path, part_id, page_num)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


# --- Git API (Phase 6) ---


@router.get("/api/documents/{doc_id}/git/log")
async def api_git_log(
    doc_id: str,
    max_count: int = Query(50, description="최대 커밋 수"),
    pushed_only: bool = Query(False, description="push된 커밋만 반환"),
):
    """문헌 저장소의 git 커밋 이력을 반환한다.

    목적: Git 이력 사이드바에 커밋 목록을 표시하기 위해 사용한다.
    입력:
        doc_id — 문헌 ID.
        max_count — 최대 커밋 수 (기본 50).
        pushed_only — True이면 원격에 push된 커밋만 반환.
    출력: [{hash, short_hash, message, author, date}, ...].
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", doc_id)
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    result = get_git_log(doc_path, max_count=max_count, pushed_only=pushed_only)
    # result = {"mode": "full"|"milestones", "commits": [...]}
    return result


@router.get("/api/documents/{doc_id}/git/diff/{commit_hash}")
async def api_git_diff(doc_id: str, commit_hash: str):
    """특정 커밋과 그 부모 사이의 diff를 반환한다.

    목적: Git 이력에서 커밋을 선택했을 때 변경 내용을 표시하기 위해 사용한다.
    입력:
        doc_id — 문헌 ID.
        commit_hash — 대상 커밋 해시.
    출력: {commit_hash, message, diffs: [{file, change_type, diff_text}, ...]}.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", doc_id)
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


@router.get("/api/documents/{doc_id}/bibliography")
async def api_bibliography(doc_id: str):
    """문헌의 서지정보를 반환한다.

    목적: 서지정보 패널에 bibliography.json 내용을 표시하기 위해 사용한다.
    입력: doc_id — 문헌 ID.
    출력: bibliography.json의 내용.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", doc_id)
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    try:
        return get_bibliography(doc_path)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.post("/api/documents/{doc_id}/bibliography/from-url")
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
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", doc_id)
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


@router.put("/api/documents/{doc_id}/bibliography")
async def api_save_bibliography(doc_id: str, body: BibliographySaveRequest):
    """문헌의 서지정보를 저장한다.

    목적: 파서가 가져온 서지정보 또는 사용자가 수동 편집한 내용을 저장한다.
    입력:
        doc_id — 문헌 ID.
        body — bibliography.schema.json 형식의 데이터.
    출력: {status: "saved", file_path}.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", doc_id)
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


@router.get("/api/parsers")
async def api_parsers():
    """등록된 파서 목록을 반환한다.

    목적: GUI에서 파서 선택 드롭다운을 채우기 위해 사용한다.
    출력: [{id, name, api_variant}, ...]
    """
    # 파서 모듈을 지연 import (parsers 패키지가 register_parser를 호출)
    import parsers  # noqa: F401
    from parsers.base import get_registry_json, list_parsers

    return {
        "parsers": list_parsers(),
        "registry": get_registry_json(),
    }


@router.post("/api/bibliography/from-url")
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


@router.post("/api/parsers/{parser_id}/search")
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


@router.post("/api/parsers/{parser_id}/map")
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


@router.post("/api/parsers/{parser_id}/fetch-and-map")
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
