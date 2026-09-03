"""해석 저장소(interpretations) API 라우터.

Phase 7 + Phase 8 엔드포인트를 포함한다.
- Phase 7: 해석 저장소 CRUD, 의존 변경 확인, 층 내용 조회/저장, git 이력/커밋
- Phase 8: 코어 스키마 엔티티 CRUD, 단위 생성/편성/쪼개기/리셋, Work 자동 생성, Tag 승격

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
    create_unit_from_source,
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

    entity_type: str  # work, unit, tag, concept, agent, relation
    data: dict  # 스키마에 맞는 엔티티 데이터


class EntityUpdateRequest(BaseModel):
    """엔티티 수정 요청 본문."""

    updates: dict  # 갱신할 필드 딕셔너리


class UnitFromSourceRequest(BaseModel):
    """단위 생성 요청 (source_ref 자동 채움)."""

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


class ComposeUnitRequest(BaseModel):
    """편성 탭에서 단위를 생성하는 요청.

    여러 LayoutBlock을 합치거나 하나를 쪼개서 단위를 만든다.
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
    level: int | None = None  # 깊이 (D-092). 없으면 volume → 1, 그 밖 2
    role: str | None = None  # container·article·fragment. 없으면 깊이로 추정
    start: dict  # {"page": int, "line_index": int, "char_offset"?}
    end: dict


class SegmentationApplyRequest(BaseModel):
    """승인한 구간을 단위로 만든다."""

    document_id: str
    part_id: str
    work_id: str
    spans: list[SegmentationSpan]
    pages: list[int] | None = None  # 제안 때와 같은 범위여야 행 번호가 맞는다
    # 적용은 누적이 아니다 — «제안 패널의 체크 상태가 곧 트리»(사용자, 2026-09-03).
    # replace="proposal": 전에 제안으로 만든 경계 중 이번 선택에 없는 것은 지운다
    #   (손으로 넣은 것은 둔다).
    # replace="all": 이 권의 살아 있는 경계를 전부 지우고 새로 세운다(자동 트리).
    # replace="none": 예전처럼 더하기만.
    replace: str = "proposal"


class SplitUnitRequest(BaseModel):
    """단위 쪼개기 요청 본문.

    쪼개기는 언제나 «기사 **안**을 문단으로 나누는» 일이다 — 별도 기사를 만들지 않는다
    (사용자 명시 2026-09-03). 기사 단위는 경계 제안·«경계 넣기»가 정한다.
    """

    original_unit_id: str
    part_id: str
    pieces: list[str]  # === 구분선으로 나눈 텍스트 조각들


class ResetCompositionRequest(BaseModel):
    """편성 리셋 요청 본문."""

    unit_ids: list[str]  # deprecated로 전환할 단위 ID 목록


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

    목적: Work, 단위, Tag, Concept, Agent, Relation 엔티티를 해석 저장소에 추가한다.
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
    """내용 트리 — Work → 단위(sequence_index 순) + 각 블록이 있는 쪽 (D-085).

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
    block_id: str | None = Query(None, description="단위 ID 필터"),
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


@router.post("/api/interpretations/{interp_id}/entities/unit/from-source")
async def api_create_unit_from_source(
    interp_id: str,
    body: UnitFromSourceRequest,
):
    """L4 확정 텍스트에서 단위를 생성한다 (source_ref 자동 채움).

    목적: 연구자가 현재 보고 있는 페이지/블록에서 단위를 만들면,
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
        result = create_unit_from_source(
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
        return JSONResponse({"error": f"단위 생성 실패: {e}"}, status_code=400)

    # 자동 git commit
    block_info = body.layout_block_id or ""
    commit_msg = f"feat: 단위 생성 — page {body.page_num:03d} {block_info}"
    result["git"] = git_commit_interpretation(interp_path, commit_msg)

    return result


@router.post("/api/interpretations/{interp_id}/entities/unit/compose")
async def api_compose_unit(
    interp_id: str,
    body: ComposeUnitRequest,
    bg: BackgroundTasks,
    no_commit: bool = Query(False, description="True이면 git commit을 건너뛴다 (배치 작업용)"),
):
    """편성 탭에서 단위를 생성한다 (source_refs 배열 지원).

    목적: 여러 LayoutBlock을 합치거나, 하나의 LayoutBlock을 쪼개서
          단위를 만든다. source_refs로 출처를 정확히 추적한다.
    입력:
        work_id — 소속 Work UUID.
        sequence_index — 작품 내 순서.
        original_text — 편성된 텍스트 (교정 적용 후).
        part_id — 파트 ID.
        source_refs — 출처 참조 배열 (순서대로 이어붙인 것).
        no_commit — True이면 git commit을 건너뛴다 (쪼개기 등 배치 작업 시).
    출력: {"status": "created", "id": ..., "unit": {...}}
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

    unit_data = {
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
        result = create_entity(interp_path, "unit", unit_data)
    except Exception as e:
        return JSONResponse({"error": f"단위 생성 실패: {e}"}, status_code=400)

    # git commit — 백그라운드로 실행하여 API 즉시 응답
    if not no_commit:
        block_ids = [r.layout_block_id or "?" for r in body.source_refs]
        commit_msg = f"feat: 단위 편성 — {'+'.join(block_ids)}"
        bg.add_task(git_commit_interpretation, interp_path, commit_msg)
        result["git"] = "background"
    else:
        result["git"] = {"committed": False, "reason": "no_commit=true"}
    result["unit"] = unit_data

    return result


@router.post("/api/interpretations/{interp_id}/segmentation/propose")
async def api_segmentation_propose(interp_id: str, body: SegmentationProposeRequest):
    """L4 확정 텍스트에서 글 단위 경계 후보를 제안한다 (D-088). 아무것도 저장하지 않는다.

    목적: 일기·담초처럼 글마다 표제가 서는 문헌에서 «어디서 글이 바뀌는가»를 기계가
          먼저 찍고, 사용자가 승인한 것만 단위가 된다.
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
        # 사람이 붙여 넣은 해제·참고 텍스트(문헌 설정)를 LLM에 같이 준다
        try:
            from core.document import get_document_info
            from core.segmentation import normalize_rules

            _rules = normalize_rules(get_document_info(doc_path).get("segmentation_rules"))
            reference_text = _rules.get("reference_text") or ""
        except Exception:  # noqa: BLE001 — 참고는 없어도 된다
            reference_text = ""
        entries, meta = await extract_toc_entries_llm(
            page_lines,
            toc_pages,
            _get_llm_router(),
            body.force_provider,
            body.force_model,
            reference_text=reference_text,
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
    """승인한 구간들을 단위로 만든다 (D-088).

    각 구간은 쪽마다 char_range를 가진 source_refs로 출처를 남긴다 — «3쪽 12행부터
    4쪽 5행까지»가 그대로 기록된다. sequence_index는 이 Work의 기존 최대값 다음부터.
    한 번의 git commit으로 묶는다.
    """
    from core.segmentation import collect_document_lines

    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    interp_path = require_repo_path("interpretations", interp_id)
    doc_path = require_repo_path("documents", body.document_id)
    if not interp_path.exists() or not doc_path.exists():
        return JSONResponse({"error": "해석 저장소 또는 문헌을 찾을 수 없습니다."}, status_code=404)
    if not body.spans:
        return JSONResponse({"error": "적용할 구간이 없습니다."}, status_code=400)

    # D-092: 구간 하나 = 경계 하나. 행 목록은 한 번만 읽고, 경계 파일은 한 번만 쓰고, 커밋도 한 번.
    # 전에는 구간마다 create_entity → 권 전체 확정본을 다시 읽어(208쪽 0.6초) 43구간에 30초가
    # 걸렸고, 그 사이에 «내용 새로고침»을 누르면 아직 없는 것으로 보였다(실측 2026-09-03).
    from core.boundaries import (
        insert_boundary,
        load_boundaries,
        new_boundary,
        save_boundaries,
    )
    from core.segmentation import boundary_bbox

    lines, page_texts = collect_document_lines(doc_path, body.part_id, body.pages)
    keys = [(ln.page, ln.line_index) for ln in lines]
    l4_commit = _document_head(doc_path)
    data = load_boundaries(interp_path, body.document_id, body.part_id)
    removed = _replace_boundaries(data, body.spans, body.replace)
    created = []
    errors = []
    for span in body.spans:
        s = span.start or {}
        key = (int(s.get("page", 0)), int(s.get("line_index", 0)))
        if key not in keys:
            errors.append(f"구간을 찾을 수 없습니다: {span.title}")
            continue
        start = {"page": key[0], "line": key[1], "offset": int(s.get("char_offset") or 0)}
        level = int(span.level) if span.level else (1 if span.kind == "volume" else 2)
        item = new_boundary(
            start=start,
            level=level,
            role=span.role or None,
            title=span.title or None,
            kind=span.kind or "manual",
            work_id=body.work_id,
            status="draft",
            anchor_status="approved",
            page_texts=page_texts,
            l4_commit=l4_commit,
            bbox=boundary_bbox(
                doc_path,
                body.part_id,
                {"page": start["page"], "line": start["line"], "offset": start["offset"]},
                {"page": start["page"], "line": start["line"], "offset": None},
            ),
        )
        item["metadata"] = {"source": "proposal"}  # 제안에서 온 경계 — 다음 적용 때 바꿔치기 대상
        try:
            kept = insert_boundary(data, item)  # 같은 자리·층위가 있으면 그것(중복 없음)
            created.append(
                {"id": kept["id"], "title": kept.get("title"), "sequence_index": len(created)}
            )
        except Exception as e:  # noqa: BLE001 — 한 구간의 실패가 나머지를 막지 않는다
            errors.append(f"{span.title}: {e}")
    git = None
    if created or removed:
        save_boundaries(interp_path, data)
        git = git_commit_interpretation(
            interp_path,
            f"feat: 경계 제안 적용 — 경계 {len(created)}개, 바꿔치기로 {removed}개 제거 "
            "(D-088·D-092)",
        )
    return {"created": created, "removed": removed, "errors": errors, "git": git}


def _is_proposal_boundary(b: dict) -> bool:
    """제안(날짜·어휘·목차·front)에서 온 경계인가.

    손으로 넣은 것(kind manual, source 없음)과 구분한다.
    """
    if (b.get("metadata") or {}).get("source") == "proposal":
        return True
    return b.get("kind") not in (None, "", "manual")


def _replace_boundaries(data: dict, spans, mode: str) -> int:
    """적용 전에 바꿔치기 대상 경계를 지운다. 지운 수를 돌려준다.

    proposal — 제안에서 온 경계 중 이번 선택(같은 자리·층위)에 없는 것.
    all — 살아 있는 경계 전부(자동 트리가 다시 세운다).
    none — 지우지 않는다(예전 동작).
    """
    if mode == "none":
        return 0
    keep_keys = set()
    for s in spans:
        st = s.start or {}
        keep_keys.add(
            (
                int(st.get("page", 0)),
                int(st.get("line_index", 0)),
                int(st.get("char_offset") or 0),
                int(s.level) if s.level else (1 if s.kind == "volume" else 2),
            )
        )
    before = data.get("boundaries") or []
    kept = []
    removed = 0
    for b in before:
        st = b.get("start") or {}
        key = (
            int(st.get("page", 0)),
            int(st.get("line", 0)),
            int(st.get("offset", 0)),
            int(b.get("level", 2)),
        )
        live = b.get("status") not in ("deprecated", "archived")
        if not live or key in keep_keys:
            kept.append(b)
            continue
        if mode == "all" or (mode == "proposal" and _is_proposal_boundary(b)):
            removed += 1
            continue
        kept.append(b)
    data["boundaries"] = kept
    return removed


class SegmentationAutoRequest(BaseModel):
    """자동 트리 (D-092 후속): 목차·해제·들여쓰기·위치를 합쳐 한 번에 개요를 세운다."""

    document_id: str
    part_id: str
    work_id: str | None = None
    use_llm_toc: bool = False  # 목차 항목 구조화에 LLM(해제 참고)
    force_provider: str | None = None
    force_model: str | None = None
    toc_only: bool | None = None  # None이면 목차가 있을 때 목차 항목만
    replace: str = "all"  # 기본: 이 권의 경계를 새로 세운다


@router.post("/api/interpretations/{interp_id}/segmentation/auto")
async def api_segmentation_auto(interp_id: str, body: SegmentationAutoRequest):
    """자동 트리: 목차 감지 → (LLM 구조화) → 경계 제안(층위 추정) → 승인된 것을 적용(바꿔치기).

    사용자가 원한 것: Workflowy처럼 사이드바에 개요가 자동으로 서고, 그 안에서 고친다.
    편성 탭의 제안 패널은 검토용이고 이것이 기본 경로다.
    출력: {"toc_pages", "proposals", "accepted", "applied", "removed", "unmatched_toc", "git"}
    """
    from app._state import _get_llm_router
    from core.document import get_document_info
    from core.segmentation import collect_document_lines, normalize_rules, propose_boundaries
    from core.toc import (
        align_toc_to_body,
        detect_toc_pages,
        extract_toc_entries_llm,
        extract_toc_entries_rule,
    )

    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    interp_path = require_repo_path("interpretations", interp_id)
    doc_path = require_repo_path("documents", body.document_id)
    if not interp_path.exists() or not doc_path.exists():
        return JSONResponse({"error": "해석 저장소 또는 문헌을 찾을 수 없습니다."}, status_code=404)
    try:
        rules = normalize_rules(get_document_info(doc_path).get("segmentation_rules"))
    except FileNotFoundError:
        rules = normalize_rules(None)
    lines, page_texts = collect_document_lines(doc_path, body.part_id, None)
    if not lines:
        return JSONResponse(
            {"error": "확정 텍스트(L4)가 있는 쪽이 없습니다. OCR·교정을 먼저 하세요."},
            status_code=400,
        )
    page_lines = {p: t.split("\n") for p, t in page_texts.items()}
    toc_pages = detect_toc_pages(page_lines, rules["max_title_chars"])
    toc_matches = None
    unmatched = []
    toc_meta = None
    if toc_pages:
        if body.use_llm_toc:
            entries, toc_meta = await extract_toc_entries_llm(
                page_lines,
                toc_pages,
                _get_llm_router(),
                body.force_provider,
                body.force_model,
                reference_text=rules.get("reference_text") or "",
            )
        else:
            entries = extract_toc_entries_rule(page_lines, toc_pages)
        body_lines = [ln for ln in lines if ln.page not in set(toc_pages)]
        matches, un = align_toc_to_body(entries, body_lines)
        toc_matches = [m.to_dict() for m in matches]
        unmatched = [entries[i].to_dict() for i in un]
        lines = body_lines
    result = propose_boundaries(lines, rules, toc_matches=toc_matches)
    toc_only = body.toc_only if body.toc_only is not None else bool(toc_matches)
    # 목차만 고르는 기본값에서도 卷 표제(kind="volume")는 남긴다 — 빠지면 트리에 묶음이 없다
    chosen = [
        p
        for p in result["proposals"]
        if p["accepted"]
        and (
            not toc_only or p["kind"] == "volume" or any(r.startswith("toc:") for r in p["reasons"])
        )
    ]
    # 구간은 «다음 선택 경계 앞까지»가 아니라 경계 목록이 알아서 정하므로 시작만 넘기면 된다
    spans = [
        SegmentationSpan(
            title=p["title"],
            kind=p["kind"] or "",
            level=int(p.get("level") or 2),
            role=p.get("role"),
            start={
                "page": p["page"],
                "line_index": p["line_index"],
                "char_offset": p.get("char_offset") or 0,
            },
            end={"page": p["page"], "line_index": p["line_index"], "char_end": None},
        )
        for p in chosen
    ]
    work_id = body.work_id
    if not work_id:
        works = list_entities(interp_path, "work")
        work_id = works[0]["id"] if works else None
    if not work_id:
        return JSONResponse(
            {"error": "Work가 없습니다. 해석 저장소에 Work를 먼저 만드세요."}, status_code=400
        )
    applied = await api_segmentation_apply(
        interp_id,
        SegmentationApplyRequest(
            document_id=body.document_id,
            part_id=body.part_id,
            work_id=work_id,
            spans=spans,
            replace=body.replace,
        ),
    )
    if isinstance(applied, JSONResponse):
        return applied
    return {
        "toc_pages": toc_pages,
        "toc_meta": toc_meta,
        "proposals": len(result["proposals"]),
        "accepted": sum(1 for p in result["proposals"] if p["accepted"]),
        "toc_only": toc_only,
        "applied": len(applied.get("created", [])),
        "removed": applied.get("removed", 0),
        "errors": applied.get("errors", []),
        "unmatched_toc": unmatched,
        "git": applied.get("git"),
    }


def _document_head(doc_path) -> str | None:
    """원본 저장소의 현재 커밋. 앵커가 어느 확정본 기준인지 남긴다."""
    try:
        import git as _git

        return _git.Repo(doc_path).head.commit.hexsha
    except Exception:  # noqa: BLE001
        return None


def _boundary_rows(
    interp_path,
    document_id: str | None,
    part_id: str | None,
    page_cache: dict | None = None,
) -> list[dict]:
    """경계 색인 «보기» (D-090): 단위를 원본 위치 순서로 늘어놓고 행 앵커를 계산한다.

    경계는 별도 데이터가 아니다. 위치의 정본은 단위.source_refs(쪽·글자 범위)이고,
    행 번호·좌표는 여기서 계산한다. 그래서 합치기·쪼개기·옮기기 어느 경로로 바꿔도 색인이
    어긋나지 않는다.

    page_cache — {(document_id, part_id): {쪽: 텍스트}}. 부르는 쪽이 이미 권 텍스트를 읽었으면
    넘긴다. 208쪽짜리 권을 다시 읽는 데만 0.25초가 든다(운양집 실측).
    """
    from core.segmentation import anchor_from_refs

    _library_path = get_library_path()
    rows = []
    if page_cache is None:
        page_cache = {}
    for blk in list_entities(interp_path, "unit"):
        if blk.get("status") == "deprecated":
            continue
        refs = blk.get("source_refs") or ([blk["source_ref"]] if blk.get("source_ref") else [])
        refs = [r for r in refs if r and r.get("page")]
        if not refs:
            continue
        doc_id = refs[0].get("document_id")
        pid = refs[0].get("part_id") or (blk.get("metadata") or {}).get("part_id")
        if document_id and doc_id != document_id:
            continue
        if part_id and pid != part_id:
            continue
        key = (doc_id, pid or "")
        if key not in page_cache:
            texts: dict[int, str] = {}
            doc_path = _resolve_repo_path("documents", doc_id) if doc_id else None
            if doc_path is not None and doc_path.exists() and pid:
                from core.segmentation import collect_document_lines

                _ls, texts = collect_document_lines(doc_path, pid, None)
            page_cache[key] = texts
        anchor_pos = anchor_from_refs(refs, page_cache[key]) or {}
        meta = blk.get("metadata") or {}
        a = meta.get("anchor") or {}
        rows.append(
            {
                "id": blk["id"],
                "work_id": blk.get("work_id"),
                "document_id": doc_id,
                "part_id": pid,
                "sequence_index": blk.get("sequence_index"),
                "title": meta.get("title") or (blk.get("original_text") or "").strip()[:20],
                "kind": a.get("kind") or meta.get("kind") or "manual",
                "level": int(a.get("level", 2) or 2),
                "role": meta.get("role"),
                "status": a.get("status") or blk.get("status"),
                "anchor_status": a.get("status"),
                "unit_status": blk.get("status"),
                "confidence": a.get("confidence"),
                "reasons": a.get("reasons") or [],
                "start": anchor_pos.get("start"),
                "end": anchor_pos.get("end"),
                "bbox": a.get("bbox"),
                "l4_commit": a.get("l4_commit"),
            }
        )
    rows.sort(
        key=lambda r: (
            r["part_id"] or "",
            (r["start"] or {}).get("page", 0),
            (r["start"] or {}).get("line", 0),
            r["sequence_index"] or 0,
        )
    )
    for i, r in enumerate(rows):
        r["order"] = i
    return rows


class BoundaryUpdateRequest(BaseModel):
    """단위의 경계를 옮기거나 제목·상태를 바꾼다 (D-090).

    start·end는 {"page", "line", "offset"}. offset은 행 안의 글자(2단계 — 澹齋日錄류처럼
    행 중간에서 날이 바뀌는 판식). start.offset 생략 = 행 첫머리, end.offset 생략 = 행 끝.
    shift_start·shift_end는 행 단위이며 옮긴 뒤 오프셋은 행 첫머리·행 끝이 된다.
    """

    title: str | None = None
    status: str | None = None
    start: dict | None = None  # {"page", "line", "offset"?}
    end: dict | None = None
    level: int | None = None  # 깊이 바꾸기 (D-092)
    role: str | None = None  # 역할 바꾸기: container·article·fragment
    shift_start: int | None = None
    shift_end: int | None = None


@router.get("/api/interpretations/{interp_id}/boundaries")
async def api_list_boundaries(
    interp_id: str,
    document_id: str | None = Query(None),
    part_id: str | None = Query(None),
):
    """경계 색인 보기 (D-090): 단위를 원본 위치 순서로, 시작·끝 행과 좌표 캐시를 붙여."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    interp_path = require_repo_path("interpretations", interp_id)
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"}, status_code=404
        )
    rows = _boundary_rows(interp_path, document_id, part_id)
    return {"boundaries": rows, "total": len(rows)}


@router.put("/api/interpretations/{interp_id}/boundaries/{unit_id}")
async def api_update_boundary(interp_id: str, unit_id: str, body: BoundaryUpdateRequest):
    """단위의 경계를 옮긴다. 위치의 정본(source_refs)과 본문을 다시 잇는다.

    행 단위. 앞뒤 블록과 겹치거나 비지 않게 한다 — 시작을 뒤로 밀면 앞 블록의 끝이 그만큼
    늘고, 끝을 내리면 뒤 블록의 시작이 밀린다. 이웃은 같은 Work·권에서 원본 위치 순서로 잡는다.
    """
    from core.segmentation import (
        boundary_bbox,
        collect_document_lines,
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
        blk = get_entity(interp_path, "unit", unit_id)
    except FileNotFoundError:
        return JSONResponse({"error": f"단위를 찾을 수 없습니다: {unit_id}"}, status_code=404)
    refs = blk.get("source_refs") or []
    if not refs or not refs[0].get("page"):
        return JSONResponse(
            {"error": "출처(source_refs)가 없는 블록은 옮길 수 없습니다."}, status_code=400
        )
    from core.boundaries import (
        find_boundary,
        load_boundaries,
        move_boundary,
        save_boundaries,
        unit_end,
        update_boundary,
    )

    doc_id = refs[0]["document_id"]
    pid = refs[0].get("part_id") or (blk.get("metadata") or {}).get("part_id")
    doc_path = require_repo_path("documents", doc_id)
    lines, page_texts = collect_document_lines(doc_path, pid, None)
    keys = [(ln.page, ln.line_index) for ln in lines]
    if not keys:
        return JSONResponse({"error": "확정 텍스트(L4)가 없습니다."}, status_code=400)
    data = load_boundaries(interp_path, doc_id, pid)
    item = find_boundary(data, unit_id)
    if item is None:
        return JSONResponse({"error": "경계를 찾을 수 없습니다. 다시 제안하세요."}, status_code=409)

    def _norm(pos: dict | None, fallback: dict) -> dict:
        if not pos:
            return dict(fallback)
        return {
            "page": int(pos.get("page", fallback["page"])),
            "line": int(pos.get("line", 0)),
            "offset": int(pos.get("offset") or 0),
        }

    def _shift_lines(pos: dict, delta: int) -> dict:
        k = (int(pos["page"]), int(pos["line"]))
        i = keys.index(k) if k in keys else 0
        i = max(0, min(len(keys) - 1, i + int(delta)))
        return {"page": keys[i][0], "line": keys[i][1], "offset": 0}

    touched: list[str] = []
    start_moved = False
    start = _norm(body.start, item["start"])
    if body.shift_start:
        start = _shift_lines(start, body.shift_start)
    if (int(start["page"]), int(start["line"])) not in keys:
        return JSONResponse({"error": "시작 행이 현재 확정본에 없습니다."}, status_code=400)
    if start != item["start"]:
        move_boundary(data, unit_id, start, page_texts)
        item["l4_commit"] = _document_head(doc_path)
        touched.append(unit_id)
        start_moved = True
    # 끝은 저장하지 않는다 — «끝을 옮긴다»는 곧 «다음 경계(같은 층위 이상)를 옮긴다»이다.
    if body.end or body.shift_end:
        bounds = data["boundaries"]
        idx = next(i for i, b in enumerate(bounds) if b.get("id") == unit_id)
        nxt_start = unit_end(bounds, idx)
        _dead = ("deprecated", "archived")
        nxt = next(
            (
                b
                for b in bounds[idx + 1 :]
                if b.get("start") == nxt_start and b.get("status") not in _dead
            ),
            None,
        )
        if nxt is not None:
            # end는 «이 단위의 마지막 자리»이므로 다음 경계는 그 바로 뒤
            # (end.offset이 있으면 그 글자)
            if body.end:
                e = _norm(body.end, nxt["start"])
                new_next = e if e.get("offset") else _shift_lines(e, 1)
            else:
                new_next = _shift_lines(nxt["start"], body.shift_end)
            if new_next != nxt["start"]:
                move_boundary(data, nxt["id"], new_next, page_texts)
                nxt["l4_commit"] = _document_head(doc_path)
                touched.append(nxt["id"])
    fields: dict = {}
    if body.title is not None:
        fields["title"] = body.title
    if body.status is not None:
        fields["anchor_status"] = body.status
    if body.level is not None:
        fields["level"] = max(1, int(body.level))
    if body.role is not None:
        if body.role not in ("container", "article", "fragment"):
            return JSONResponse(
                {"error": "role은 container·article·fragment 중 하나입니다."}, status_code=400
            )
        fields["role"] = body.role
    if fields:
        update_boundary(data, unit_id, fields)
        if unit_id not in touched:
            touched.append(unit_id)
    # 시작 행의 L2 좌표 캐시(화면 표시용). 시작이 그대로면 다시 재지 않는다 —
    # 제목·역할·층위만 바꿔도 L2를 읽어 오던 군더더기였다.
    b = find_boundary(data, unit_id)
    if start_moved or b.get("bbox") is None:
        b["bbox"] = boundary_bbox(
            doc_path,
            pid,
            {
                "page": b["start"]["page"],
                "line": b["start"]["line"],
                "offset": b["start"]["offset"],
            },
            {"page": b["start"]["page"], "line": b["start"]["line"], "offset": None},
        )
    save_boundaries(interp_path, data)
    title = b.get("title") or unit_id[:8]
    git = git_commit_interpretation(interp_path, f"fix: 경계 수정 — {title} (D-092)")
    row = next(
        (
            r
            for r in _boundary_rows(interp_path, doc_id, pid, {(doc_id, pid or ""): page_texts})
            if r["id"] == unit_id
        ),
        None,
    )
    return {"boundary": row, "touched": touched, "git": git}


class BoundaryInsertRequest(BaseModel):
    """경계 넣기 (D-092) — 임의 행·행 중간에서 단위를 나눈다. 새 id는 뒤 단위(이 경계)에 붙는다."""

    document_id: str
    part_id: str
    start: dict  # {"page", "line", "offset"}
    level: int = 2
    role: str | None = None  # container·article·fragment (없으면 깊이로 추정)
    title: str | None = None
    kind: str = "manual"
    work_id: str | None = None  # 없으면 그 자리를 품는 단위의 Work, 그것도 없으면 첫 Work


@router.post("/api/interpretations/{interp_id}/boundaries")
async def api_insert_boundary(interp_id: str, body: BoundaryInsertRequest):
    """경계를 넣는다 = 그 자리에서 단위를 쪼갠다. 앞 단위의 id는 그대로, 새 id는 뒤 단위에."""
    from core.boundaries import (
        insert_boundary,
        load_boundaries,
        new_boundary,
        save_boundaries,
        sort_key,
    )
    from core.segmentation import boundary_bbox, collect_document_lines

    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    interp_path = require_repo_path("interpretations", interp_id)
    doc_path = require_repo_path("documents", body.document_id)
    if not interp_path.exists() or not doc_path.exists():
        return JSONResponse({"error": "해석 저장소 또는 문헌을 찾을 수 없습니다."}, status_code=404)
    lines, page_texts = collect_document_lines(doc_path, body.part_id, None)
    keys = [(ln.page, ln.line_index) for ln in lines]
    start = {
        "page": int(body.start.get("page", 0)),
        "line": int(body.start.get("line", 0)),
        "offset": int(body.start.get("offset") or 0),
    }
    if (start["page"], start["line"]) not in keys:
        return JSONResponse({"error": "그 쪽·행에 확정 텍스트(L4)가 없습니다."}, status_code=400)
    data = load_boundaries(interp_path, body.document_id, body.part_id)
    work_id = body.work_id
    if not work_id:
        # 그 자리를 품는(앞에 있는) 경계의 Work → 없으면 첫 Work
        before = [
            b
            for b in data["boundaries"]
            if sort_key(b) <= (start["page"], start["line"], start["offset"], 99)
        ]
        work_id = next((b.get("work_id") for b in reversed(before) if b.get("work_id")), None)
        if not work_id:
            works = list_entities(interp_path, "work")
            work_id = works[0]["id"] if works else None
    item = new_boundary(
        start=start,
        level=max(1, int(body.level)),
        role=body.role or None,
        title=body.title
        or (
            lines[keys.index((start["page"], start["line"]))].text[start["offset"] :].strip()[:20]
            or None
        ),
        kind=body.kind or "manual",
        work_id=work_id,
        status="draft",
        page_texts=page_texts,
        l4_commit=_document_head(doc_path),
    )
    item["bbox"] = boundary_bbox(
        doc_path,
        body.part_id,
        {"page": start["page"], "line": start["line"], "offset": start["offset"]},
        {"page": start["page"], "line": start["line"], "offset": None},
    )
    try:
        kept = insert_boundary(data, item)  # 같은 자리·층위가 이미 있으면 그것을 돌려준다
    except FileExistsError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    existing = kept is not item
    git = None
    if not existing:
        save_boundaries(interp_path, data)
        git = git_commit_interpretation(
            interp_path, f"feat: 경계 넣기 — {item.get('title') or item['id'][:8]} (D-092)"
        )
    row = next(
        (
            r
            for r in _boundary_rows(interp_path, body.document_id, body.part_id)
            if r["id"] == kept["id"]
        ),
        None,
    )
    return {"boundary": row, "existing": existing, "git": git}


@router.delete("/api/interpretations/{interp_id}/boundaries/{unit_id}")
async def api_delete_boundary(interp_id: str, unit_id: str):
    """경계를 지운다 = 그 단위를 앞 단위에 합친다. 앞 단위의 id가 남는다 (D-092).

    관계·태그가 지운 id를 가리키고 있으면 그대로 두고 응답에 알린다 — 사람이 옮긴다.
    """
    from core.boundaries import (
        delete_boundary,
        list_boundary_parts,
        load_boundaries,
        save_boundaries,
    )

    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    interp_path = require_repo_path("interpretations", interp_id)
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"}, status_code=404
        )
    for doc_id, pid in list_boundary_parts(interp_path):
        data = load_boundaries(interp_path, doc_id, pid)
        ids = [b["id"] for b in data["boundaries"]]
        if unit_id not in ids:
            continue
        idx = ids.index(unit_id)
        prev_id = next(
            (
                b["id"]
                for b in reversed(data["boundaries"][:idx])
                if b.get("status") not in ("deprecated", "archived")
            ),
            None,
        )
        removed = delete_boundary(data, unit_id)
        save_boundaries(interp_path, data)
        dangling = [
            tg["id"] for tg in list_entities(interp_path, "tag") if tg.get("block_id") == unit_id
        ]
        git = git_commit_interpretation(
            interp_path, f"fix: 경계 지우기 — {removed.get('title') or unit_id[:8]} (D-092)"
        )
        return {
            "deleted": unit_id,
            "merged_into": prev_id,
            "dangling_tags": dangling,
            "git": git,
        }
    return JSONResponse({"error": f"경계를 찾을 수 없습니다: {unit_id}"}, status_code=404)


@router.get("/api/interpretations/{interp_id}/boundaries/export.csv")
async def api_export_boundaries_csv(
    interp_id: str,
    document_id: str | None = Query(None),
    part_id: str | None = Query(None),
):
    """경계 색인을 CSV로 (D-090). 열 이름은 연구자 DB의 article_index 관례. UTF-8 BOM."""
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
    rows = _boundary_rows(interp_path, document_id, part_id)
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
            "l4_commit",
        ]
    )
    for r in rows:
        s_, e_ = r.get("start") or {}, r.get("end") or {}
        w.writerow(
            [
                r["id"],
                r.get("document_id"),
                r.get("part_id"),
                r["order"],
                r.get("kind"),
                r.get("level", 2),
                r.get("title"),
                s_.get("page", ""),
                s_.get("line", ""),
                e_.get("page", ""),
                e_.get("line", ""),
                r.get("status"),
                r.get("confidence") if r.get("confidence") is not None else "",
                " ".join(r.get("reasons") or []),
                (r.get("l4_commit") or "")[:12],
            ]
        )
    data = ("\ufeff" + buf.getvalue()).encode("utf-8")
    name = f"boundaries_{document_id or interp_id}{('_' + part_id) if part_id else ''}.csv"
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/api/interpretations/{interp_id}/entities/unit/split")
async def api_split_unit(interp_id: str, body: SplitUnitRequest, bg: BackgroundTasks):
    """단위를 여러 조각으로 쪼갠다 (백그라운드 git commit).

    목적: 한 단위를 단락 단위로 나누는 배치 작업.
          모든 조각 생성 + 원본 deprecated 를 한 번의 git commit으로 처리하여
          사용자 대기 시간을 최소화한다.

    처리 순서:
        1. 원본 단위에서 source_refs, work_id 상속
        2. 각 조각마다 새 단위 생성 (git commit 없이)
        3. 원본 단위를 deprecated 전환 (git commit 없이)
        4. 마지막에 한 번만 git commit
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

    # D-092: 쪼개기 = 원본 단위 **안에** 경계를 더 넣는 것. 원본 id는 첫 조각으로 그대로 남고,
    # 둘째 조각부터 새 경계(새 id)가 선다. 새 경계는 원본보다 한 단 깊은 «조각»이라 원본 기사가
    # 그것들을 품는다 — 기사 자체는 쪼개지지 않는다. 본문은 저장하지 않으므로 «조각 텍스트»는
    # 자리를 찾는 열쇠일 뿐이다 — 조각의 첫 글자들이 원본 본문에서 나오는 자리에 경계를 놓는다.
    from core.boundaries import (
        find_boundary,
        insert_boundary,
        load_boundaries,
        new_boundary,
        position_from_char,
        save_boundaries,
    )
    from core.segmentation import collect_document_lines

    try:
        original = get_entity(interp_path, "unit", body.original_unit_id)
    except FileNotFoundError:
        return JSONResponse(
            {"error": f"원본 단위를 찾을 수 없습니다: {body.original_unit_id}"},
            status_code=404,
        )
    pieces = [str(piece).strip() for piece in (body.pieces or []) if str(piece).strip()]
    if len(pieces) < 2:
        return JSONResponse({"error": "쪼개기 조각은 2개 이상이어야 합니다."}, status_code=400)
    refs = [r for r in (original.get("source_refs") or []) if r and r.get("page")]
    if not refs:
        return JSONResponse({"error": "원본 단위에 출처(쪽)가 없습니다."}, status_code=400)
    doc_id = refs[0].get("document_id")
    pid = refs[0].get("part_id") or body.part_id
    data = load_boundaries(interp_path, doc_id, pid)
    orig_b = find_boundary(data, body.original_unit_id)
    if orig_b is None:
        return JSONResponse({"error": "원본 경계를 찾을 수 없습니다."}, status_code=404)
    doc_path = _resolve_repo_path("documents", doc_id)
    lines, page_texts = collect_document_lines(doc_path, pid, None) if doc_path else ([], {})
    text = original.get("original_text") or ""

    def _to_page_abs(idx: int):
        """단위 본문 안의 오프셋 → (쪽, 쪽 텍스트 절대 오프셋). 본문은 쪽 조각을 개행으로 이었다."""
        consumed = 0
        for r in refs:
            cr = r.get("char_range")
            if not cr:
                continue
            seg = int(cr[1]) - int(cr[0])
            if idx <= consumed + seg:
                return int(r["page"]), int(cr[0]) + (idx - consumed)
            consumed += seg + 1
        return None

    created_ids: list[str] = []
    errors: list[str] = []
    cursor = 0
    for i, piece in enumerate(pieces[1:], start=2):
        key = piece[:6]
        at = text.find(key, cursor) if key else -1
        if at < 0:
            errors.append(f"조각 {i}: 첫 글자 «{key}»를 원본 본문에서 찾지 못했습니다")
            continue
        cursor = at + max(1, len(key))
        where = _to_page_abs(at)
        if where is None:
            errors.append(f"조각 {i}: 자리를 쪽으로 옮기지 못했습니다")
            continue
        page, abs_off = where
        # 조각은 원본보다 «한 단 안쪽»이다. 같은 층위로 넣으면 원본과 나란한 별도 기사가 되어
        # 기사가 쪼개져 버린다 — v1.3.0까지 그렇게 동작했다(사용자 지적).
        item = new_boundary(
            start=position_from_char(page_texts, page, abs_off),
            level=int(orig_b.get("level", 2)) + 1,
            role="fragment",
            title=piece[:20],
            kind="manual",
            work_id=orig_b.get("work_id"),
            status="draft",
            page_texts=page_texts or None,
            l4_commit=_document_head(doc_path) if doc_path else None,
        )
        try:
            insert_boundary(data, item)
            created_ids.append(item["id"])
        except Exception as e:  # noqa: BLE001
            errors.append(f"조각 {i}: {e}")
    if created_ids:
        save_boundaries(interp_path, data)
    commit_msg = f"feat: 단위 쪼개기 — 경계 {len(created_ids)}개 삽입 (D-092)"
    bg.add_task(git_commit_interpretation, interp_path, commit_msg)
    if errors:
        return JSONResponse(
            {
                "created_count": len(created_ids),
                "created_ids": created_ids,
                "errors": errors,
                "git": "background",
            },
            status_code=207,
        )
    return {
        "created_count": len(created_ids),
        "created_ids": created_ids,
        "deprecated_id": None,  # 원본은 첫 조각으로 남는다(D-092: 앞 id 유지)
        "git": "background",
    }


@router.post("/api/interpretations/{interp_id}/entities/unit/reset")
async def api_reset_composition(interp_id: str, body: ResetCompositionRequest, bg: BackgroundTasks):
    """여러 단위를 한꺼번에 deprecated 전환한다 (백그라운드 git commit).

    목적: 편성 리셋 시 모든 단위를 배치로 deprecated 전환.
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

    for tb_id in body.unit_ids:
        try:
            update_entity(interp_path, "unit", tb_id, {"status": "deprecated"})
            deprecated_count += 1
        except Exception as e:
            errors.append(f"{tb_id[:8]}: {e}")

    # 백그라운드 git commit — API는 즉시 응답
    commit_msg = f"fix: 단위 편성 리셋 — {deprecated_count}개 deprecated"
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

    목적: 단위 생성에 필요한 Work가 없을 때,
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
