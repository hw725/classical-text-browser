"""해석 저장소(interpretations) API 라우터.

Phase 7 + Phase 8 엔드포인트를 포함한다.
- Phase 7: 해석 저장소 CRUD, 의존 변경 확인, 층 내용 조회/저장, git 이력/커밋
- Phase 8: 코어 스키마 엔티티 CRUD, TextBlock 생성/편성/쪼개기/리셋, Work 자동 생성, Tag 승격

모든 경로에서 서고 경로는 get_library_path()로 참조한다.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app._state import _resolve_repo_path, get_library_path, require_repo_path
from core.entity import (
    auto_create_work,
    create_entity,
    create_textblock_from_source,
    get_entity,
    list_contents,
    list_entities,
    list_entities_for_page,
    promote_tag_to_concept,
    update_entity,
)
from core.interpretation import (
    acknowledge_changes,
    check_dependency,
    create_interpretation,
    get_interp_git_log,
    get_interpretation_info,
    get_layer_content,
    get_layer_content_at_commit,
    git_commit_interpretation,
    save_layer_content,
    update_base,
)
from core.library import (
    list_interpretations,
    trash_interpretation,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["interpretations"])


# =========================================
#   Pydantic 모델 (요청 본문)
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


class ManualCommitRequest(BaseModel):
    """수동 커밋 요청 본문."""

    message: str = "batch: 배치 작업 커밋"


class EntityCreateRequest(BaseModel):
    """엔티티 생성 요청 본문."""

    entity_type: str  # work, text_block, tag, concept, agent, relation
    data: dict  # 스키마에 맞는 엔티티 데이터


class EntityUpdateRequest(BaseModel):
    """엔티티 수정 요청 본문."""

    updates: dict  # 갱신할 필드 딕셔너리


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
    """Tag -> Concept 승격 요청."""

    label: str | None = None
    scope_work: str | None = None
    description: str | None = None


class AutoCreateWorkRequest(BaseModel):
    """Work 자동 생성 요청."""

    document_id: str


class CompositionSourceRef(BaseModel):
    """편성용 소스 참조 하나."""

    document_id: str
    page: int
    layout_block_id: str | None = None
    char_range: list[int] | None = None  # [start, end) or null
    # 권(part). 없으면 요청 본문의 part_id로 채운다 (D-085 — 내용 트리에서 쪽으로 이동할 때 필요).
    part_id: str | None = None


class ComposeTextBlockRequest(BaseModel):
    """편성 탭에서 TextBlock을 생성하는 요청.

    여러 LayoutBlock을 합치거나 하나를 쪼개서 TextBlock을 만든다.
    source_refs 배열 순서대로 텍스트를 이어붙인다.
    """

    work_id: str
    sequence_index: int
    original_text: str
    part_id: str
    source_refs: list[CompositionSourceRef]


class SegmentationProposeRequest(BaseModel):
    """글 경계 제안 요청 (D-088)."""

    document_id: str
    part_id: str
    pages: list[int] | None = None  # None이면 권 전체
    rules: dict | None = None  # None이면 manifest.segmentation_rules → 기본값
    # 목차 신호 (D-089). use_toc=True면 toc가 없을 때 규칙으로 자동 판별·추출한다.
    use_toc: bool = True
    toc: dict | None = None  # {"pages": [...], "entries": [{"title","level","page_hint"}]}


class SegmentationTocRequest(BaseModel):
    """목차 판별·추출 요청 (D-089). 아무것도 저장하지 않는다."""

    document_id: str
    part_id: str
    toc_pages: list[int] | None = None  # None이면 앞쪽 쪽에서 자동 판별
    use_llm: bool = False  # True면 LLM으로 항목 구조화(실패 시 규칙으로)
    force_provider: str | None = None
    force_model: str | None = None


class SegmentationSpan(BaseModel):
    title: str
    kind: str = ""
    start: dict  # {"page": int, "line_index": int}
    end: dict


class SegmentationApplyRequest(BaseModel):
    """승인한 구간을 TextBlock으로 만든다."""

    document_id: str
    part_id: str
    work_id: str
    spans: list[SegmentationSpan]
    pages: list[int] | None = None  # 제안 때와 같은 범위여야 행 번호가 맞는다


class SplitTextBlockRequest(BaseModel):
    """TextBlock 쪼개기 요청 본문."""

    original_text_block_id: str
    part_id: str
    pieces: list[str]  # === 구분선으로 나눈 텍스트 조각들


class ResetCompositionRequest(BaseModel):
    """편성 리셋 요청 본문."""

    text_block_ids: list[str]  # deprecated로 전환할 TextBlock ID 목록


# =========================================
#   Phase 7: 해석 저장소 API
# =========================================


@router.post("/api/interpretations")
async def api_create_interpretation(body: CreateInterpretationRequest):
    """해석 저장소를 생성한다.

    목적: 원본 문헌을 기반으로 새 해석 저장소를 만든다.
    입력:
        body — {interp_id, source_document_id, interpreter_type, interpreter_name, title}.
    출력: 생성된 해석 저장소의 manifest 정보.
    """
    _library_path = get_library_path()
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


@router.get("/api/interpretations")
async def api_interpretations():
    """해석 저장소 목록을 반환한다."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    return list_interpretations(_library_path)


@router.delete("/api/interpretations/{interp_id}")
async def api_delete_interpretation(interp_id: str):
    """해석 저장소를 휴지통(.trash/interpretations/)으로 이동한다.

    목적: 해석 저장소 폴더를 영구 삭제하지 않고 서고 내 .trash/로 옮긴다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    try:
        result = trash_interpretation(_library_path, interp_id)
        return result
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.get("/api/interpretations/{interp_id}")
async def api_interpretation(interp_id: str):
    """특정 해석 저장소의 상세 정보를 반환한다."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
    try:
        return get_interpretation_info(interp_path)
    except FileNotFoundError:
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )


@router.get("/api/interpretations/{interp_id}/dependency")
async def api_check_dependency(interp_id: str):
    """해석 저장소의 의존 변경을 확인한다.

    목적: 원본 저장소가 변경되었는지 확인하여 경고 배너를 표시하기 위해 사용한다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    try:
        return check_dependency(_library_path, interp_id)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.post("/api/interpretations/{interp_id}/dependency/acknowledge")
async def api_acknowledge_changes(interp_id: str, body: AcknowledgeRequest):
    """변경된 파일을 '인지함' 상태로 전환한다.

    목적: 연구자가 원본 변경을 확인했지만 해석은 유효하다고 판단할 때 사용한다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    try:
        return acknowledge_changes(_library_path, interp_id, body.file_paths)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.post("/api/interpretations/{interp_id}/dependency/update-base")
async def api_update_base(interp_id: str):
    """기반 커밋을 현재 원본 HEAD로 갱신한다.

    목적: 원본 변경을 모두 반영하고 새 기반에서 작업을 계속한다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    try:
        return update_base(_library_path, interp_id)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.get("/api/interpretations/{interp_id}/layers/{layer}/{sub_type}/pages/{page_num}")
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
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
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


@router.get(
    "/api/interpretations/{interp_id}/commits/{commit_hash}"
    "/layers/{layer}/{sub_type}/pages/{page_num}"
)
async def api_layer_content_at_commit(
    interp_id: str,
    commit_hash: str,
    layer: str,
    sub_type: str,
    page_num: int,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """특정 커밋 시점의 해석 층 내용을 반환한다.

    목적: 버전 간 비교에서 과거 커밋의 층 내용을 로드한다.
    왜 기존 api_layer_content()를 수정하지 않는가:
        기존 엔드포인트는 항상 HEAD(현재 파일)를 읽는다.
        커밋 해시를 받는 별도 URL로 분리하여 기존 동작에 영향을 주지 않는다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        return get_layer_content_at_commit(
            interp_path, commit_hash, layer, sub_type, part_id, page_num
        )
    except Exception as e:
        return JSONResponse(
            {"error": f"커밋 시점 레이어 조회 중 오류: {e}"},
            status_code=500,
        )


@router.put("/api/interpretations/{interp_id}/layers/{layer}/{sub_type}/pages/{page_num}")
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
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        save_result = save_layer_content(
            interp_path,
            layer,
            sub_type,
            body.part_id,
            page_num,
            body.content,
        )
    except Exception as e:
        return JSONResponse({"error": f"저장 실패: {e}"}, status_code=400)

    # 자동 git commit
    layer_label = {
        "L5_reading": "구두점",
        "L6_translation": "번역",
        "L7_annotation": "주석",
    }.get(layer, layer)
    commit_msg = f"{layer}: page {page_num:03d} {layer_label} 편집 ({sub_type})"
    git_result = git_commit_interpretation(interp_path, commit_msg)
    save_result["git"] = git_result

    return save_result


@router.get("/api/interpretations/{interp_id}/git/log")
async def api_interp_git_log(
    interp_id: str,
    max_count: int = Query(50, description="최대 커밋 수"),
):
    """해석 저장소의 git 커밋 이력을 반환한다."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    return {"commits": get_interp_git_log(interp_path, max_count=max_count)}


@router.post("/api/interpretations/{interp_id}/git/commit")
async def api_interp_manual_commit(interp_id: str, body: ManualCommitRequest, bg: BackgroundTasks):
    """해석 저장소에 수동으로 git commit을 생성한다 (백그라운드).

    목적: 배치 작업(쪼개기, 리셋 등)에서 no_commit=true로 여러 변경을
          모은 뒤, 마지막에 한 번만 커밋한다. 커밋은 백그라운드에서 실행되어
          API가 즉시 응답한다.
    입력: message — 커밋 메시지 (기본값: "batch: 배치 작업 커밋")
    출력: {committed: "background", message}
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    bg.add_task(git_commit_interpretation, interp_path, body.message)
    return {"committed": "background", "message": body.message}


# =========================================
#   Phase 8: 코어 스키마 엔티티 API
# =========================================


@router.post("/api/interpretations/{interp_id}/entities")
async def api_create_entity(interp_id: str, body: EntityCreateRequest):
    """코어 스키마 엔티티를 생성한다.

    목적: Work, TextBlock, Tag, Concept, Agent, Relation 엔티티를 해석 저장소에 추가한다.
    입력: entity_type + data (JSON 스키마 형식).
    출력: {"status": "created", "entity_type": ..., "id": ..., "file_path": ...}
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
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


@router.get("/api/interpretations/{interp_id}/entities/page/{page_num}")
async def api_entities_for_page(
    interp_id: str,
    page_num: int,
    document_id: str = Query(..., description="원본 문헌 ID"),
):
    """현재 페이지와 관련된 엔티티를 모두 반환한다.

    목적: 하단 패널 "엔티티" 탭에서 현재 페이지에 연결된 엔티티를 표시한다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        return list_entities_for_page(interp_path, document_id, page_num)
    except Exception as e:
        return JSONResponse({"error": f"엔티티 조회 실패: {e}"}, status_code=400)


@router.get("/api/interpretations/{interp_id}/contents")
async def api_contents_tree(
    interp_id: str,
    document_id: str | None = Query(None, description="이 문헌을 가리키는 블록만"),
):
    """내용 트리 — Work → TextBlock(sequence_index 순) + 각 블록이 있는 쪽 (D-085).

    목적: 교감 뒤에는 쪽이 아니라 내용으로 찾아가야 한다. 사이드바 「내용」 트리가
          이 응답으로 그려지고, 블록을 누르면 pages[].page 로 이동해 layout_block_ids 를
          강조한다. 저장 형식은 바꾸지 않는다 — blocks/·works/ 를 읽어 묶기만 한다.
    출력: core.entity.list_contents() 참조.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )
    try:
        return list_contents(interp_path, document_id)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"내용 트리 조회 실패: {e}"}, status_code=400)


@router.get("/api/interpretations/{interp_id}/entities/{entity_type}")
async def api_list_entities(
    interp_id: str,
    entity_type: str,
    status: str | None = Query(None, description="상태 필터"),
    block_id: str | None = Query(None, description="TextBlock ID 필터"),
    page: int | None = Query(None, description="페이지 번호 필터 (source_ref.page)"),
    document_id: str | None = Query(None, description="문헌 ID 필터 (source_ref.document_id)"),
):
    """특정 유형의 엔티티 목록을 반환한다."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
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

        # page/document_id 필터 (source_ref, source_refs 기반)
        if page is not None or document_id is not None:
            filtered = []
            for ent in entities:
                refs = ent.get("source_refs") or []
                ref = ent.get("source_ref")
                match = False
                # source_refs 배열 검사
                for r in refs:
                    page_ok = page is None or r.get("page") == page
                    doc_ok = document_id is None or r.get("document_id") == document_id
                    if page_ok and doc_ok:
                        match = True
                        break
                # source_ref 단일 검사 (하위 호환)
                if not match and ref:
                    page_ok = page is None or ref.get("page") == page
                    doc_ok = document_id is None or ref.get("document_id") == document_id
                    if page_ok and doc_ok:
                        match = True
                if match:
                    filtered.append(ent)
            entities = filtered

        return {"entity_type": entity_type, "count": len(entities), "entities": entities}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.get("/api/interpretations/{interp_id}/entities/{entity_type}/{entity_id}")
async def api_get_entity(interp_id: str, entity_type: str, entity_id: str):
    """단일 엔티티를 조회한다."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
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


@router.put("/api/interpretations/{interp_id}/entities/{entity_type}/{entity_id}")
async def api_update_entity(
    interp_id: str,
    entity_type: str,
    entity_id: str,
    body: EntityUpdateRequest,
    bg: BackgroundTasks,
    no_commit: bool = Query(False, description="True이면 git commit을 건너뛴다 (배치 작업용)"),
):
    """엔티티를 수정한다 (상태 전이 포함).

    목적: 엔티티 필드를 갱신한다. 삭제는 불가능하며 상태 전이만 허용된다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
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

    # git commit — 백그라운드로 실행하여 API 즉시 응답
    if not no_commit:
        commit_msg = f"fix: {entity_type} 엔티티 수정 — {entity_id[:8]}"
        bg.add_task(git_commit_interpretation, interp_path, commit_msg)
        result["git"] = "background"
    else:
        result["git"] = {"committed": False, "reason": "no_commit=true"}

    return result


@router.post("/api/interpretations/{interp_id}/entities/text_block/from-source")
async def api_create_textblock_from_source(
    interp_id: str,
    body: TextBlockFromSourceRequest,
):
    """L4 확정 텍스트에서 TextBlock을 생성한다 (source_ref 자동 채움).

    목적: 연구자가 현재 보고 있는 페이지/블록에서 TextBlock을 만들면,
          source_ref가 자동으로 채워진다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
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


@router.post("/api/interpretations/{interp_id}/entities/text_block/compose")
async def api_compose_textblock(
    interp_id: str,
    body: ComposeTextBlockRequest,
    bg: BackgroundTasks,
    no_commit: bool = Query(False, description="True이면 git commit을 건너뛴다 (배치 작업용)"),
):
    """편성 탭에서 TextBlock을 생성한다 (source_refs 배열 지원).

    목적: 여러 LayoutBlock을 합치거나, 하나의 LayoutBlock을 쪼개서
          TextBlock을 만든다. source_refs로 출처를 정확히 추적한다.
    입력:
        work_id — 소속 Work UUID.
        sequence_index — 작품 내 순서.
        original_text — 편성된 텍스트 (교정 적용 후).
        part_id — 파트 ID.
        source_refs — 출처 참조 배열 (순서대로 이어붙인 것).
        no_commit — True이면 git commit을 건너뛴다 (쪼개기 등 배치 작업 시).
    출력: {"status": "created", "id": ..., "text_block": {...}}
    """
    import uuid as _uuid

    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    # source_refs에 commit 해시 자동 채움
    import git as _git

    refs_with_commit = []
    for ref in body.source_refs:
        # ID 형식이 안 맞는 ref는 커밋 해시만 비운 채 계속 진행한다
        # (이 루프는 best-effort 보강이므로 요청 전체를 거절하지 않는다).
        doc_path = _resolve_repo_path("documents", ref.document_id)
        commit_hash = None
        if doc_path is not None:
            try:
                repo = _git.Repo(doc_path)
                commit_hash = repo.head.commit.hexsha
            except Exception:
                pass
        refs_with_commit.append(
            {
                "document_id": ref.document_id,
                "page": ref.page,
                "layout_block_id": ref.layout_block_id,
                "part_id": ref.part_id or body.part_id,
                "char_range": ref.char_range,
                "layer": "L4",
                "commit": commit_hash,
            }
        )

    # 하위 호환: 첫 번째 ref를 source_ref로도 저장
    first_ref = refs_with_commit[0] if refs_with_commit else None
    source_ref_compat = None
    if first_ref:
        source_ref_compat = {k: v for k, v in first_ref.items() if k != "char_range"}

    text_block_data = {
        "id": str(_uuid.uuid4()),
        "work_id": body.work_id,
        "sequence_index": body.sequence_index,
        "original_text": body.original_text,
        "normalized_text": None,
        "source_ref": source_ref_compat,
        "source_refs": refs_with_commit,
        "status": "draft",
        "notes": None,
        "metadata": {"part_id": body.part_id},
    }

    try:
        result = create_entity(interp_path, "text_block", text_block_data)
    except Exception as e:
        return JSONResponse({"error": f"TextBlock 생성 실패: {e}"}, status_code=400)

    # git commit — 백그라운드로 실행하여 API 즉시 응답
    if not no_commit:
        block_ids = [r.layout_block_id or "?" for r in body.source_refs]
        commit_msg = f"feat: TextBlock 편성 — {'+'.join(block_ids)}"
        bg.add_task(git_commit_interpretation, interp_path, commit_msg)
        result["git"] = "background"
    else:
        result["git"] = {"committed": False, "reason": "no_commit=true"}
    result["text_block"] = text_block_data

    return result


@router.post("/api/interpretations/{interp_id}/segmentation/propose")
async def api_segmentation_propose(interp_id: str, body: SegmentationProposeRequest):
    """L4 확정 텍스트에서 글 단위 경계 후보를 제안한다 (D-088). 아무것도 저장하지 않는다.

    목적: 일기·담초처럼 글마다 표제가 서는 문헌에서 «어디서 글이 바뀌는가»를 기계가
          먼저 찍고, 사용자가 승인한 것만 TextBlock이 된다.
    입력: document_id, part_id, pages(None=전체), rules(None=문헌 설정 → 기본값).
    출력: core.segmentation.propose_boundaries() 결과 + "lines"(화면 표시용 행 목록).
    """
    from core.document import get_document_info
    from core.segmentation import collect_document_lines, normalize_rules, propose_boundaries

    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    interp_path = require_repo_path("interpretations", interp_id)
    doc_path = require_repo_path("documents", body.document_id)
    if not interp_path.exists() or not doc_path.exists():
        return JSONResponse({"error": "해석 저장소 또는 문헌을 찾을 수 없습니다."}, status_code=404)

    rules = body.rules
    if rules is None:
        try:
            rules = get_document_info(doc_path).get("segmentation_rules")
        except FileNotFoundError:
            rules = None
    rules = normalize_rules(rules)

    lines, page_texts = collect_document_lines(doc_path, body.part_id, body.pages)
    if not lines:
        return JSONResponse(
            {"error": "확정 텍스트(L4)가 있는 쪽이 없습니다. OCR·교정을 먼저 하세요."},
            status_code=400,
        )

    # 목차 신호 (D-089): 목차 쪽은 본문 후보에서 빼고, 항목을 본문 행에 순서대로 대응시킨다
    toc_info = None
    toc_matches = None
    if body.use_toc:
        from core.toc import (
            TocEntry,
            align_toc_to_body,
            detect_toc_pages,
            extract_toc_entries_rule,
        )

        page_lines = {p: t.split("\n") for p, t in page_texts.items()}
        if body.toc and body.toc.get("entries"):
            toc_pages = [int(p) for p in (body.toc.get("pages") or [])]
            entries = [
                TocEntry(
                    title=str(e.get("title", "")).strip(),
                    level=int(e.get("level", 2)),
                    page_hint=e.get("page_hint"),
                )
                for e in body.toc["entries"]
                if str(e.get("title", "")).strip()
            ]
        else:
            toc_pages = detect_toc_pages(page_lines, rules["max_title_chars"])
            entries = extract_toc_entries_rule(page_lines, toc_pages) if toc_pages else []
        if entries:
            body_lines = [ln for ln in lines if ln.page not in set(toc_pages)]
            matches, unmatched = align_toc_to_body(entries, body_lines)
            toc_matches = [m.to_dict() for m in matches]
            toc_info = {
                "pages": toc_pages,
                "entries": [e.to_dict() for e in entries],
                "matches": toc_matches,
                "unmatched": [entries[i].to_dict() | {"index": i} for i in unmatched],
            }
            lines = body_lines
            for p in toc_pages:
                page_texts.pop(p, None)

    result = propose_boundaries(lines, rules, toc_matches=toc_matches)
    result["lines"] = [
        {"page": ln.page, "line_index": ln.line_index, "text": ln.text} for ln in lines
    ]
    result["pages"] = sorted(page_texts)
    result["toc"] = toc_info
    return result


@router.post("/api/interpretations/{interp_id}/segmentation/toc")
async def api_segmentation_toc(interp_id: str, body: SegmentationTocRequest):
    """목차 쪽을 판별하고 항목을 뽑는다 (D-089). 저장하지 않는다.

    규칙(짧은 행 비율·目錄/卷之 표지·葉 번호 꼬리)으로 앞쪽 쪽을 고르고, use_llm이면 LLM이
    항목을 구조화한다(텍스트만 넘긴다 — 비전 불필요, JSON 강제, 사고 끔). 실패하면 규칙 추출.
    출력: {"toc_pages", "entries", "method", "meta"}
    """
    from app._state import _get_llm_router
    from core.segmentation import collect_document_lines
    from core.toc import detect_toc_pages, extract_toc_entries_llm, extract_toc_entries_rule

    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    doc_path = require_repo_path("documents", body.document_id)
    if not doc_path.exists():
        return JSONResponse({"error": "문헌을 찾을 수 없습니다."}, status_code=404)

    _lines, page_texts = collect_document_lines(doc_path, body.part_id, None)
    if not page_texts:
        return JSONResponse({"error": "확정 텍스트(L4)가 있는 쪽이 없습니다."}, status_code=400)
    page_lines = {p: t.split("\n") for p, t in page_texts.items()}
    toc_pages = body.toc_pages or detect_toc_pages(page_lines)
    if not toc_pages:
        return {
            "toc_pages": [],
            "entries": [],
            "method": "rule",
            "meta": {"reason": "목차로 보이는 쪽이 없습니다"},
        }
    if body.use_llm:
        entries, meta = await extract_toc_entries_llm(
            page_lines, toc_pages, _get_llm_router(), body.force_provider, body.force_model
        )
    else:
        entries, meta = extract_toc_entries_rule(page_lines, toc_pages), {"method": "rule"}
    return {
        "toc_pages": toc_pages,
        "entries": [e.to_dict() for e in entries],
        "method": meta.get("method", "rule"),
        "meta": meta,
    }


@router.post("/api/interpretations/{interp_id}/segmentation/apply")
async def api_segmentation_apply(interp_id: str, body: SegmentationApplyRequest):
    """승인한 구간들을 TextBlock으로 만든다 (D-088).

    각 구간은 쪽마다 char_range를 가진 source_refs로 출처를 남긴다 — «3쪽 12행부터
    4쪽 5행까지»가 그대로 기록된다. sequence_index는 이 Work의 기존 최대값 다음부터.
    한 번의 git commit으로 묶는다.
    """
    from core.segmentation import collect_document_lines, span_to_text_and_refs

    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    interp_path = require_repo_path("interpretations", interp_id)
    doc_path = require_repo_path("documents", body.document_id)
    if not interp_path.exists() or not doc_path.exists():
        return JSONResponse({"error": "해석 저장소 또는 문헌을 찾을 수 없습니다."}, status_code=404)
    if not body.spans:
        return JSONResponse({"error": "적용할 구간이 없습니다."}, status_code=400)

    lines, page_texts = collect_document_lines(doc_path, body.part_id, body.pages)
    existing = [
        b for b in list_entities(interp_path, "text_block") if b.get("work_id") == body.work_id
    ]
    seq = max((b.get("sequence_index") or 0) for b in existing) + 1 if existing else 0

    import uuid as _uuid

    from core.segmentation import boundary_bbox

    l4_commit = _document_head(doc_path)
    existing_b = [
        b
        for b in list_entities(interp_path, "boundary")
        if b.get("work_id") == body.work_id and b.get("part_id") == body.part_id
    ]
    order = max((b.get("order") or 0) for b in existing_b) + 1 if existing_b else 0

    created = []
    errors = []
    for span in body.spans:
        try:
            text, refs = span_to_text_and_refs(
                span.model_dump(), lines, page_texts, body.document_id, body.part_id
            )
        except ValueError:
            errors.append(f"구간을 찾을 수 없습니다: {span.title}")
            continue
        if not text:
            continue
        # 1) 경계 색인 항목 — 경계의 정본 (D-090)
        boundary = {
            "id": str(_uuid.uuid4()),
            "work_id": body.work_id,
            "document_id": body.document_id,
            "part_id": body.part_id,
            "order": order,
            "title": span.title,
            "kind": span.kind or "manual",
            "level": 1 if span.kind == "volume" else 2,
            "status": "approved",
            "confidence": None,
            "reasons": [],
            "start": {"page": int(span.start["page"]), "line": int(span.start["line_index"])},
            "end": {"page": int(span.end["page"]), "line": int(span.end["line_index"])},
            "bbox": boundary_bbox(
                doc_path,
                body.part_id,
                span.start | {"line": span.start["line_index"]},
                span.end | {"line": span.end["line_index"]},
            ),
            "text_block_id": None,
            "l4_commit": l4_commit,
            "metadata": None,
        }
        # 2) TextBlock — 경계에서 파생
        data = {
            "id": str(_uuid.uuid4()),
            "work_id": body.work_id,
            "sequence_index": seq,
            "original_text": text,
            "normalized_text": None,
            "source_ref": {k: v for k, v in refs[0].items() if k != "char_range"},
            "source_refs": refs,
            "status": "draft",
            "notes": None,
            "metadata": {
                "part_id": body.part_id,
                "title": span.title,
                "kind": span.kind or None,
                "segmentation": "proposed",
                "boundary_id": boundary["id"],
            },
        }
        boundary["text_block_id"] = data["id"]
        try:
            create_entity(interp_path, "boundary", boundary)
            create_entity(interp_path, "text_block", data)
            created.append(
                {
                    "id": data["id"],
                    "boundary_id": boundary["id"],
                    "title": span.title,
                    "sequence_index": seq,
                }
            )
            seq += 1
            order += 1
        except Exception as e:  # noqa: BLE001 — 한 구간의 실패가 나머지를 막지 않는다
            errors.append(f"{span.title}: {e}")

    git = None
    if created:
        git = git_commit_interpretation(
            interp_path, f"feat: 경계 제안 적용 — TextBlock {len(created)}개 (D-088)"
        )
    return {"created": created, "errors": errors, "git": git}


def _document_head(doc_path) -> str | None:
    """원본 저장소의 현재 커밋. 경계 앵커가 어느 확정본 기준인지 남긴다."""
    try:
        import git as _git

        return _git.Repo(doc_path).head.commit.hexsha
    except Exception:  # noqa: BLE001
        return None


class BoundaryUpdateRequest(BaseModel):
    """경계 한 항목 수정 (D-090). 행 단위로 옮기거나 제목·상태를 바꾼다."""

    title: str | None = None
    status: str | None = None  # proposed | approved | manual | deprecated
    start: dict | None = None  # {"page", "line"}
    end: dict | None = None
    shift_start: int | None = None  # 시작 행을 ±n 행 (같은 쪽 안에서)
    shift_end: int | None = None


@router.get("/api/interpretations/{interp_id}/boundaries")
async def api_list_boundaries(
    interp_id: str,
    document_id: str | None = Query(None),
    part_id: str | None = Query(None),
):
    """경계 색인 목록 (D-090) — 권 안 순서대로."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    interp_path = require_repo_path("interpretations", interp_id)
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"}, status_code=404
        )
    items = [
        b
        for b in list_entities(interp_path, "boundary")
        if (document_id is None or b.get("document_id") == document_id)
        and (part_id is None or b.get("part_id") == part_id)
    ]
    items.sort(key=lambda b: (b.get("part_id") or "", b.get("order") or 0))
    return {"boundaries": items, "total": len(items)}


@router.put("/api/interpretations/{interp_id}/boundaries/{boundary_id}")
async def api_update_boundary(interp_id: str, boundary_id: str, body: BoundaryUpdateRequest):
    """경계를 옮기거나 고친다. 경계가 정본이므로 파생 TextBlock의 본문·출처를 다시 잇는다.

    행 단위(shift_start/shift_end 또는 start/end). 앞뒤 경계와 겹치지 않게 한다 — 이 경계의
    시작을 올리면 앞 경계의 끝도 그만큼 당겨지고, 끝을 내리면 뒤 경계의 시작이 밀린다.
    """
    from core.segmentation import (
        boundary_bbox,
        boundary_span,
        collect_document_lines,
        span_to_text_and_refs,
    )

    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    interp_path = require_repo_path("interpretations", interp_id)
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"}, status_code=404
        )
    try:
        b = get_entity(interp_path, "boundary", boundary_id)
    except FileNotFoundError:
        return JSONResponse({"error": f"경계를 찾을 수 없습니다: {boundary_id}"}, status_code=404)
    doc_path = require_repo_path("documents", b["document_id"])
    lines, page_texts = collect_document_lines(doc_path, b["part_id"], None)
    keys = [(ln.page, ln.line_index) for ln in lines]
    if not keys:
        return JSONResponse({"error": "확정 텍스트(L4)가 없습니다."}, status_code=400)

    def _pos(anchor):
        try:
            return keys.index((int(anchor["page"]), int(anchor["line"])))
        except ValueError:
            return None

    start_i, end_i = _pos(b["start"]), _pos(b["end"])
    if start_i is None or end_i is None:
        return JSONResponse(
            {"error": "경계의 앵커가 현재 확정본에 없습니다. 다시 제안하세요."}, status_code=409
        )
    if body.start:
        start_i = _pos(body.start) if _pos(body.start) is not None else start_i
    if body.end:
        end_i = _pos(body.end) if _pos(body.end) is not None else end_i
    if body.shift_start:
        start_i = max(0, min(len(keys) - 1, start_i + int(body.shift_start)))
    if body.shift_end:
        end_i = max(0, min(len(keys) - 1, end_i + int(body.shift_end)))
    if end_i < start_i:
        return JSONResponse({"error": "끝이 시작보다 앞에 올 수 없습니다."}, status_code=400)

    # 이웃 경계와의 정합: 같은 Work·권에서 order 앞뒤
    siblings = sorted(
        (
            x
            for x in list_entities(interp_path, "boundary")
            if x.get("work_id") == b["work_id"]
            and x.get("part_id") == b["part_id"]
            and x.get("status") != "deprecated"
            and x["id"] != b["id"]
        ),
        key=lambda x: x.get("order") or 0,
    )
    prev_b = max(
        (x for x in siblings if (x.get("order") or 0) < (b.get("order") or 0)),
        key=lambda x: x["order"],
        default=None,
    )
    next_b = min(
        (x for x in siblings if (x.get("order") or 0) > (b.get("order") or 0)),
        key=lambda x: x["order"],
        default=None,
    )
    touched = []

    def _apply(bnd, s_i, e_i):
        bnd["start"] = {"page": keys[s_i][0], "line": keys[s_i][1]}
        bnd["end"] = {"page": keys[e_i][0], "line": keys[e_i][1]}
        bnd["bbox"] = boundary_bbox(doc_path, bnd["part_id"], bnd["start"], bnd["end"])
        text, refs = span_to_text_and_refs(
            boundary_span(bnd), lines, page_texts, bnd["document_id"], bnd["part_id"]
        )
        update_entity(
            interp_path,
            "boundary",
            bnd["id"],
            {k: bnd[k] for k in ("start", "end", "bbox", "title", "status")},
        )
        if bnd.get("text_block_id"):
            update_entity(
                interp_path,
                "text_block",
                bnd["text_block_id"],
                {
                    "original_text": text,
                    "source_refs": refs,
                    "source_ref": {k: v for k, v in refs[0].items() if k != "char_range"}
                    if refs
                    else None,
                },
            )
        touched.append(bnd["id"])

    if body.title is not None:
        b["title"] = body.title
    if body.status is not None:
        b["status"] = body.status
    _apply(b, start_i, end_i)
    if prev_b is not None:
        p_start = _pos(prev_b["start"])
        if p_start is not None and p_start <= start_i - 1:
            _apply(prev_b, p_start, start_i - 1)
    if next_b is not None:
        n_end = _pos(next_b["end"])
        if n_end is not None and end_i + 1 <= n_end:
            _apply(next_b, end_i + 1, n_end)
    git = git_commit_interpretation(interp_path, f"fix: 경계 수정 — {b['title']} (D-090)")
    return {
        "boundary": get_entity(interp_path, "boundary", b["id"]),
        "touched": touched,
        "git": git,
    }


@router.get("/api/interpretations/{interp_id}/boundaries/export.csv")
async def api_export_boundaries_csv(
    interp_id: str,
    document_id: str | None = Query(None),
    part_id: str | None = Query(None),
):
    """경계 색인을 CSV로 (D-090). 열 이름은 연구자 DB의 article_index 관례에 맞춘다.

    UTF-8 BOM — Excel이 바로 읽는다. 행 번호는 0-based(확정 텍스트의 행), 끝 행은 포함.
    """
    import csv
    import io as _io

    from fastapi.responses import Response

    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    interp_path = require_repo_path("interpretations", interp_id)
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"}, status_code=404
        )
    items = [
        b
        for b in list_entities(interp_path, "boundary")
        if (document_id is None or b.get("document_id") == document_id)
        and (part_id is None or b.get("part_id") == part_id)
    ]
    items.sort(key=lambda b: (b.get("part_id") or "", b.get("order") or 0))
    buf = _io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "기사id",
            "문헌",
            "권",
            "순서",
            "유형",
            "층위",
            "제목",
            "시작쪽",
            "시작행",
            "끝쪽",
            "끝행",
            "상태",
            "신뢰도",
            "근거",
            "text_block_id",
            "l4_commit",
        ]
    )
    for b in items:
        w.writerow(
            [
                b["id"],
                b.get("document_id"),
                b.get("part_id"),
                b.get("order"),
                b.get("kind"),
                b.get("level", 2),
                b.get("title"),
                b["start"]["page"],
                b["start"]["line"],
                b["end"]["page"],
                b["end"]["line"],
                b.get("status"),
                b.get("confidence") if b.get("confidence") is not None else "",
                " ".join(b.get("reasons") or []),
                b.get("text_block_id") or "",
                (b.get("l4_commit") or "")[:12],
            ]
        )
    data = ("\ufeff" + buf.getvalue()).encode("utf-8")
    name = f"boundaries_{document_id or interp_id}{('_' + part_id) if part_id else ''}.csv"
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/api/interpretations/{interp_id}/entities/text_block/split")
async def api_split_textblock(interp_id: str, body: SplitTextBlockRequest, bg: BackgroundTasks):
    """TextBlock을 여러 조각으로 쪼갠다 (백그라운드 git commit).

    목적: 한 TextBlock을 단락 단위로 나누는 배치 작업.
          모든 조각 생성 + 원본 deprecated 를 한 번의 git commit으로 처리하여
          사용자 대기 시간을 최소화한다.

    처리 순서:
        1. 원본 TextBlock에서 source_refs, work_id 상속
        2. 각 조각마다 새 TextBlock 생성 (git commit 없이)
        3. 원본 TextBlock을 deprecated 전환 (git commit 없이)
        4. 마지막에 한 번만 git commit
    """
    import uuid as _uuid

    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    # 원본 TextBlock 로드
    try:
        original = get_entity(interp_path, "text_block", body.original_text_block_id)
    except FileNotFoundError:
        return JSONResponse(
            {"error": f"원본 TextBlock을 찾을 수 없습니다: {body.original_text_block_id}"},
            status_code=404,
        )

    base_seq = int(original.get("sequence_index", 0))
    work_id = original.get("work_id")
    if not work_id:
        return JSONResponse({"error": "원본 TextBlock의 work_id가 없습니다."}, status_code=400)

    pieces = [str(piece).strip() for piece in (body.pieces or []) if str(piece).strip()]
    if len(pieces) < 2:
        return JSONResponse({"error": "쪼개기 조각은 2개 이상이어야 합니다."}, status_code=400)

    inherited_refs = original.get("source_refs") or []
    # source_ref(단수) 하위호환
    if not inherited_refs and original.get("source_ref"):
        inherited_refs = [original["source_ref"]]

    # source_refs에 현재 원본 commit 해시 채우기
    import git as _git

    for ref in inherited_refs:
        if not ref.get("commit"):
            # ID 형식이 안 맞는 ref는 건너뛴다 (best-effort 보강 — 기존 관용 동작 유지)
            doc_path = _resolve_repo_path("documents", ref.get("document_id", ""))
            if doc_path is None:
                continue
            try:
                repo = _git.Repo(doc_path)
                ref["commit"] = repo.head.commit.hexsha
            except Exception:
                pass

    # 하위 호환: 첫 번째 ref를 source_ref로도 저장
    first_ref = inherited_refs[0] if inherited_refs else None
    source_ref_compat = None
    if first_ref:
        source_ref_compat = {k: v for k, v in first_ref.items() if k != "char_range"}

    created_ids = []
    errors = []

    # 순서 보존: 원본 뒤에 있는 활성 TextBlock의 sequence를 뒤로 민다.
    try:
        active_blocks = [
            tb
            for tb in list_entities(interp_path, "text_block")
            if tb.get("id") != body.original_text_block_id
            and tb.get("status") not in ("deprecated", "archived")
            and int(tb.get("sequence_index", 0)) > base_seq
        ]
        active_blocks.sort(key=lambda tb: int(tb.get("sequence_index", 0)))

        shift = len(pieces) - 1
        for tb in active_blocks:
            seq = int(tb.get("sequence_index", 0))
            update_entity(interp_path, "text_block", tb["id"], {"sequence_index": seq + shift})
    except Exception as e:
        return JSONResponse({"error": f"sequence 재배치 실패: {e}"}, status_code=400)

    # 각 조각마다 새 TextBlock 생성 (원래 위치에 연속 삽입)
    for i, piece_text in enumerate(pieces):
        text_block_data = {
            "id": str(_uuid.uuid4()),
            "work_id": work_id,
            "sequence_index": base_seq + i,
            "original_text": piece_text,
            "normalized_text": None,
            "source_ref": source_ref_compat,
            "source_refs": [{**r, "char_range": None} for r in inherited_refs],
            "status": "draft",
            "notes": None,
            "metadata": {"part_id": body.part_id},
        }

        try:
            create_entity(interp_path, "text_block", text_block_data)
            created_ids.append(text_block_data["id"])
        except Exception as e:
            errors.append(f"조각 {i + 1}: {e}")

    # 원본 TextBlock을 deprecated 전환
    if created_ids:
        try:
            update_entity(
                interp_path,
                "text_block",
                body.original_text_block_id,
                {"status": "deprecated"},
            )
        except Exception as e:
            errors.append(f"원본 deprecated 실패: {e}")

    # 백그라운드 git commit — API는 즉시 응답
    commit_msg = f"feat: TextBlock 쪼개기 — {len(created_ids)}개 생성"
    bg.add_task(git_commit_interpretation, interp_path, commit_msg)

    if errors:
        return JSONResponse(
            {
                "created_count": len(created_ids),
                "errors": errors,
                "git": "background",
            },
            status_code=207,
        )

    return {
        "created_count": len(created_ids),
        "created_ids": created_ids,
        "deprecated_id": body.original_text_block_id,
        "git": "background",
    }


@router.post("/api/interpretations/{interp_id}/entities/text_block/reset")
async def api_reset_composition(interp_id: str, body: ResetCompositionRequest, bg: BackgroundTasks):
    """여러 TextBlock을 한꺼번에 deprecated 전환한다 (백그라운드 git commit).

    목적: 편성 리셋 시 모든 TextBlock을 배치로 deprecated 전환.
          개별 PUT 호출 대신 단일 엔드포인트로 처리하여 속도를 높인다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    deprecated_count = 0
    errors = []

    for tb_id in body.text_block_ids:
        try:
            update_entity(interp_path, "text_block", tb_id, {"status": "deprecated"})
            deprecated_count += 1
        except Exception as e:
            errors.append(f"{tb_id[:8]}: {e}")

    # 백그라운드 git commit — API는 즉시 응답
    commit_msg = f"fix: TextBlock 편성 리셋 — {deprecated_count}개 deprecated"
    bg.add_task(git_commit_interpretation, interp_path, commit_msg)

    if errors:
        return JSONResponse(
            {
                "deprecated_count": deprecated_count,
                "errors": errors,
                "git": "background",
            },
            status_code=207,
        )

    return {
        "deprecated_count": deprecated_count,
        "git": "background",
    }


@router.post("/api/interpretations/{interp_id}/entities/work/auto-create")
async def api_auto_create_work(interp_id: str, body: AutoCreateWorkRequest):
    """문헌 메타데이터로부터 Work 엔티티를 자동 생성한다.

    목적: TextBlock 생성에 필요한 Work가 없을 때,
          문헌의 서지정보/매니페스트에서 자동으로 Work를 만든다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
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


@router.post("/api/interpretations/{interp_id}/entities/tags/{tag_id}/promote")
async def api_promote_tag(
    interp_id: str,
    tag_id: str,
    body: PromoteTagRequest,
):
    """Tag를 Concept으로 승격한다.

    목적: 연구자가 확인한 Tag를 의미 엔티티(Concept)로 격상한다.
          core-schema-v1.3.md 섹션 7: Promotion Flow.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = require_repo_path("interpretations", interp_id)
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


# ── 빈 해석 저장소 정리 ────────────────────────────────
#
# 왜 필요한가:
#   문헌을 만들면 기본 해석 저장소가 함께 생긴다(D-054). 표점·번역·주석의
#   전제 조건이기 때문이다. 그런데 텍스트만 뽑는 작업(추출 모드)에서는
#   L5-L7을 아예 쓰지 않으므로 그 저장소가 빈 채로 목록에 쌓인다.
#
# 왜 «비었을 때만»인가:
#   모드 전환은 표시를 바꾸는 일이지 데이터를 지우는 일이 아니다.
#   실수로 눌렀다고 번역·주석이 사라지면 안 된다. 내용이 하나라도 있으면
#   건드리지 않고 그 사실을 알린다.
#
# 왜 삭제가 아니라 휴지통인가:
#   판단이 틀렸을 때 되돌릴 수 있어야 한다. 기존 휴지통 기능
#   (trash_interpretation + /api/trash/.../restore)을 그대로 쓴다.


def _interpretation_content_files(interp_path) -> list[str]:
    """해석 저장소에 실제 작업 내용이 있는지 훑어 파일 목록을 돌려준다.

    입력: interp_path — 해석 저장소 경로.
    출력: 내용 파일의 상대 경로 목록 (비어 있으면 빈 리스트).

    무엇을 «내용»으로 보는가: L5~L8 층 아래의 파일이다.
    manifest.json·dependency.json·.git·.gitignore는 생성 시 만들어지는
    골격이므로 «작업이 있다»는 근거가 되지 못한다.
    """
    from pathlib import Path as _Path

    interp_path = _Path(interp_path)
    found: list[str] = []
    for layer in ("L5_reading", "L6_translation", "L7_annotation", "L8_external"):
        layer_dir = interp_path / layer
        if not layer_dir.exists():
            continue
        for f in layer_dir.rglob("*"):
            if f.is_file() and f.name != ".gitkeep":
                found.append(str(f.relative_to(interp_path).as_posix()))
    return found


@router.get("/api/interpretations/{interp_id}/emptiness")
def api_interpretation_emptiness(interp_id: str):
    """해석 저장소가 비어 있는지 확인한다.

    목적: 정리해도 되는지 판단할 근거를 준다.
    출력: {interp_id, is_empty, content_files, content_count}
    """
    interp_path = require_repo_path("interpretations", interp_id)
    if not (interp_path / "manifest.json").exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"}, status_code=404
        )
    files = _interpretation_content_files(interp_path)
    return {
        "interp_id": interp_id,
        "is_empty": not files,
        "content_files": files[:20],
        "content_count": len(files),
    }


@router.post("/api/documents/{doc_id}/interpretations/discard-empty")
def api_discard_empty_interpretations(doc_id: str):
    """이 문헌에 딸린 **비어 있는** 해석 저장소를 휴지통으로 옮긴다.

    목적: 텍스트 추출만 할 문헌에서 쓰지 않는 저장소를 치운다.
    출력: {discarded: [...], kept: [{interp_id, content_count}], ...}

    내용이 있는 저장소는 절대 건드리지 않고 kept에 담아 이유와 함께 돌려준다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    from core.library import trash_interpretation

    discarded: list[str] = []
    kept: list[dict] = []
    errors: list[str] = []

    for interp in list_interpretations(_library_path):
        interp_id = interp.get("interpretation_id")
        # 이 문헌을 원본으로 삼는 해석 저장소만 대상으로 한다.
        if interp.get("source_document_id") != doc_id:
            continue

        interp_path = _library_path / "interpretations" / interp_id
        files = _interpretation_content_files(interp_path)
        if files:
            kept.append({"interp_id": interp_id, "content_count": len(files)})
            continue
        try:
            trash_interpretation(_library_path, interp_id)
            discarded.append(interp_id)
        except Exception as e:  # noqa: BLE001 — 하나 실패해도 나머지는 진행
            errors.append(f"{interp_id}: {e}")

    return {
        "document_id": doc_id,
        "discarded": discarded,
        "kept": kept,
        "errors": errors,
        "note": (
            "휴지통으로 옮겼습니다. 되돌리려면 설정 → 휴지통에서 복원하세요."
            if discarded
            else "정리할 빈 해석 저장소가 없습니다."
        ),
    }
