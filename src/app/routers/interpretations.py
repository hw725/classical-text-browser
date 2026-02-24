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

from app._state import get_library_path
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

    interp_path = _library_path / "interpretations" / interp_id
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


@router.get("/api/interpretations/{interp_id}/git/log")
async def api_interp_git_log(
    interp_id: str,
    max_count: int = Query(50, description="최대 커밋 수"),
):
    """해석 저장소의 git 커밋 이력을 반환한다."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
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

    interp_path = _library_path / "interpretations" / interp_id
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

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    # source_refs에 commit 해시 자동 채움
    import git as _git
    refs_with_commit = []
    for ref in body.source_refs:
        doc_path = _library_path / "documents" / ref.document_id
        commit_hash = None
        try:
            repo = _git.Repo(doc_path)
            commit_hash = repo.head.commit.hexsha
        except Exception:
            pass
        refs_with_commit.append({
            "document_id": ref.document_id,
            "page": ref.page,
            "layout_block_id": ref.layout_block_id,
            "char_range": ref.char_range,
            "layer": "L4",
            "commit": commit_hash,
        })

    # 하위 호환: 첫 번째 ref를 source_ref로도 저장
    first_ref = refs_with_commit[0] if refs_with_commit else None
    source_ref_compat = None
    if first_ref:
        source_ref_compat = {
            k: v for k, v in first_ref.items() if k != "char_range"
        }

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

    interp_path = _library_path / "interpretations" / interp_id
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
            doc_path = _library_path / "documents" / ref.get("document_id", "")
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
            tb for tb in list_entities(interp_path, "text_block")
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
            "source_refs": [
                {**r, "char_range": None} for r in inherited_refs
            ],
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
                interp_path, "text_block",
                body.original_text_block_id,
                {"status": "deprecated"},
            )
        except Exception as e:
            errors.append(f"원본 deprecated 실패: {e}")

    # 백그라운드 git commit — API는 즉시 응답
    commit_msg = f"feat: TextBlock 쪼개기 — {len(created_ids)}개 생성"
    bg.add_task(git_commit_interpretation, interp_path, commit_msg)

    if errors:
        return JSONResponse({
            "created_count": len(created_ids),
            "errors": errors,
            "git": "background",
        }, status_code=207)

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

    interp_path = _library_path / "interpretations" / interp_id
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
        return JSONResponse({
            "deprecated_count": deprecated_count,
            "errors": errors,
            "git": "background",
        }, status_code=207)

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
