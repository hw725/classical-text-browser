"""주석(Annotation) 라우터.

L7 주석 CRUD, 사전형 주석 생성/내보내기/가져오기, 참조 사전 관리,
인용 마크(Citation Mark) CRUD/내보내기, AI 주석 태깅 API를 모아둔다.

왜 분리하는가:
    server.py가 너무 길어져 유지보수가 어렵다.
    주석 관련 기능은 독립적이므로 별도 라우터로 분리한다.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app._state import get_library_path, _get_llm_router, _call_llm_text, _call_llm_text_stream

from core.annotation import (
    add_annotation as add_ann,
    check_translation_changed,
    get_annotation_summary,
    get_annotations_by_type,
    get_annotations_by_stage,
    load_annotations,
    remove_annotation as remove_ann,
    save_annotations,
    update_annotation as update_ann,
)
from core.annotation_llm import commit_annotation_draft, commit_all_drafts
from core.annotation_dict_llm import (
    generate_stage1_from_original,
    generate_stage2_from_translation,
    generate_stage3_from_both,
)
from core.annotation_dict_io import (
    export_dictionary,
    import_dictionary,
    save_export,
)
from core.annotation_dict_match import (
    format_for_translation_context,
    list_reference_dicts,
    load_reference_dict,
    match_page_blocks,
    register_reference_dict,
    remove_reference_dict,
)
from core.annotation_types import (
    add_custom_type,
    load_annotation_types,
    remove_custom_type,
)
from core.citation_mark import (
    add_citation_mark,
    export_citations,
    format_citation,
    list_all_citation_marks,
    load_citation_marks,
    remove_citation_mark,
    resolve_citation_context,
    save_citation_marks,
    update_citation_mark,
)
from core.interpretation import git_commit_interpretation

logger = logging.getLogger(__name__)

router = APIRouter(tags=["annotation"])


# ── Pydantic 모델 ─────────────────────────────────


class AnnotationAddRequest(BaseModel):
    """수동 주석 추가 요청."""
    target: dict
    type: str
    content: dict


class AnnotationUpdateRequest(BaseModel):
    """주석 수정 요청."""
    target: dict | None = None
    type: str | None = None
    content: dict | None = None
    status: str | None = None


class AnnotationCommitRequest(BaseModel):
    """주석 Draft 확정 요청."""
    modifications: dict | None = None


class CustomTypeRequest(BaseModel):
    """사용자 정의 주석 유형 추가 요청."""
    id: str
    label: str
    color: str
    icon: str = "🏷️"


class DictStageRequest(BaseModel):
    """사전형 주석 단계별 생성 요청."""
    block_id: str
    force_provider: str | None = None
    force_model: str | None = None


class DictBatchRequest(BaseModel):
    """사전형 주석 일괄 생성 요청 (Stage 3 직행)."""
    pages: list[int] | None = None  # None이면 전체 페이지
    force_provider: str | None = None
    force_model: str | None = None


class DictImportRequest(BaseModel):
    """사전 가져오기 요청."""
    dictionary_data: dict
    merge_strategy: str = "merge"
    target_page: int = 1


class RefDictRegisterRequest(BaseModel):
    """참조 사전 등록 요청."""
    dictionary_data: dict
    filename: str | None = None


class RefDictMatchRequest(BaseModel):
    """참조 사전 매칭 요청."""
    blocks: list[dict]
    ref_filenames: list[str] | None = None


class CitationMarkAddRequest(BaseModel):
    """인용 마크 추가 요청."""
    block_id: str
    start: int
    end: int
    marked_from: str  # "original" | "translation"
    source_text_snapshot: str
    label: str | None = None
    tags: list[str] = []


class CitationMarkUpdateRequest(BaseModel):
    """인용 마크 수정 요청."""
    label: str | None = None
    tags: list[str] | None = None
    citation_override: dict | None = None
    status: str | None = None
    marked_from: str | None = None


class CitationExportRequest(BaseModel):
    """인용 내보내기 요청.

    export_options:
        bracket_replace_single — 「」 → 〈〉 치환 여부.
        bracket_replace_double — 『』 → 《》 치환 여부.
        wrap_double_quotes — 원문을 \u201c\u201d로 감쌀지 여부.
        field_order — 인용 필드 순서 배열.
    """
    mark_ids: list[str]
    include_translation: bool = True
    export_options: dict | None = None


class AiAnnotationRequest(BaseModel):
    """AI 주석 태깅 요청."""
    text: str                         # 태깅할 원문 텍스트
    force_provider: str | None = None
    force_model: str | None = None


# ──────────────────────────────────────────────────────────
# L7 주석 CRUD API
# ──────────────────────────────────────────────────────────


@router.get("/api/interpretations/{interp_id}/pages/{page_num}/annotations")
async def api_get_annotations(interp_id: str, page_num: int, type: str | None = None):
    """주석 조회.

    목적: 특정 페이지의 L7 주석 데이터를 반환한다.
    쿼리 파라미터: type — 특정 유형만 필터링 (선택).
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 저장소 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    part_id = "main"
    data = load_annotations(interp_path, part_id, page_num)

    if type:
        filtered = get_annotations_by_type(data, type)
        return {"part_id": part_id, "page_number": page_num, "filtered_type": type, "results": filtered}

    return data


@router.get("/api/interpretations/{interp_id}/pages/{page_num}/annotations/summary")
async def api_annotation_summary(interp_id: str, page_num: int):
    """주석 상태 요약.

    목적: 페이지의 주석 현황을 한눈에 파악.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"
    data = load_annotations(interp_path, part_id, page_num)
    return get_annotation_summary(data)


@router.post("/api/interpretations/{interp_id}/pages/{page_num}/annotations/{block_id}")
async def api_add_annotation(
    interp_id: str, page_num: int, block_id: str, body: AnnotationAddRequest
):
    """수동 주석 추가.

    목적: 사용자가 직접 주석을 입력한다. annotator.type = "human", status = "accepted".
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_annotations(interp_path, part_id, page_num)

    annotation = {
        "target": body.target,
        "type": body.type,
        "content": body.content,
        "annotator": {"type": "human", "model": None, "draft_id": None},
        "status": "accepted",
        "reviewed_by": None,
        "reviewed_at": None,
    }
    result = add_ann(data, block_id, annotation)

    try:
        save_annotations(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(interp_path, f"feat: L7 주석 추가 — page {page_num}")
        except Exception:
            pass
        return JSONResponse(result, status_code=201)
    except Exception as e:
        return JSONResponse({"error": f"주석 저장 실패: {e}"}, status_code=400)


@router.put("/api/interpretations/{interp_id}/pages/{page_num}/annotations/{block_id}/{ann_id}")
async def api_update_annotation(
    interp_id: str, page_num: int, block_id: str, ann_id: str,
    body: AnnotationUpdateRequest,
):
    """주석 수정."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_annotations(interp_path, part_id, page_num)
    updates = {}
    if body.target is not None:
        updates["target"] = body.target
    if body.type is not None:
        updates["type"] = body.type
    if body.content is not None:
        updates["content"] = body.content
    if body.status is not None:
        updates["status"] = body.status

    result = update_ann(data, block_id, ann_id, updates)
    if result is None:
        return JSONResponse({"error": f"주석 '{ann_id}'를 찾을 수 없습니다."}, status_code=404)

    try:
        save_annotations(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(interp_path, f"feat: L7 주석 수정 — page {page_num}")
        except Exception:
            pass
        return result
    except Exception as e:
        return JSONResponse({"error": f"주석 저장 실패: {e}"}, status_code=400)


@router.delete("/api/interpretations/{interp_id}/pages/{page_num}/annotations/{block_id}/{ann_id}")
async def api_delete_annotation(
    interp_id: str, page_num: int, block_id: str, ann_id: str
):
    """주석 삭제."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_annotations(interp_path, part_id, page_num)
    removed = remove_ann(data, block_id, ann_id)

    if not removed:
        return JSONResponse({"error": f"주석 '{ann_id}'를 찾을 수 없습니다."}, status_code=404)

    save_annotations(interp_path, part_id, page_num, data)
    return JSONResponse(status_code=204, content=None)


@router.post("/api/interpretations/{interp_id}/pages/{page_num}/annotations/{block_id}/{ann_id}/commit")
async def api_commit_annotation(
    interp_id: str, page_num: int, block_id: str, ann_id: str,
    body: AnnotationCommitRequest,
):
    """주석 Draft 개별 확정.

    목적: 연구자가 Draft를 검토 후 확정. status → "accepted".
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_annotations(interp_path, part_id, page_num)
    result = commit_annotation_draft(data, block_id, ann_id, body.modifications)

    if result is None:
        return JSONResponse({"error": f"주석 '{ann_id}'를 찾을 수 없습니다."}, status_code=404)

    try:
        save_annotations(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(interp_path, f"feat: L7 주석 확정 — page {page_num}")
        except Exception:
            pass
        return result
    except Exception as e:
        return JSONResponse({"error": f"주석 저장 실패: {e}"}, status_code=400)


@router.post("/api/interpretations/{interp_id}/pages/{page_num}/annotations/commit-all")
async def api_commit_all_annotations(interp_id: str, page_num: int):
    """주석 Draft 일괄 확정.

    목적: 페이지의 모든 draft 주석을 한번에 accepted로 변경.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_annotations(interp_path, part_id, page_num)
    count = commit_all_drafts(data)

    if count == 0:
        return {"message": "확정할 draft 주석이 없습니다.", "committed": 0}

    try:
        save_annotations(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(interp_path, f"feat: L7 주석 일괄 확정 — page {page_num}")
        except Exception:
            pass
        return {"message": f"{count}개 주석을 확정했습니다.", "committed": count}
    except Exception as e:
        return JSONResponse({"error": f"주석 저장 실패: {e}"}, status_code=400)


# --- 주석 유형 관리 API ---

@router.get("/api/annotation-types")
async def api_get_annotation_types():
    """주석 유형 목록.

    목적: 기본 프리셋 + 사용자 정의 유형을 반환한다.
    """
    _library_path = get_library_path()
    work_path = _library_path if _library_path else None
    data = load_annotation_types(work_path)
    return data


@router.post("/api/annotation-types")
async def api_add_annotation_type(body: CustomTypeRequest):
    """사용자 정의 주석 유형 추가."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    try:
        type_def = {"id": body.id, "label": body.label, "color": body.color, "icon": body.icon}
        result = add_custom_type(_library_path, type_def)
        return JSONResponse(result, status_code=201)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.delete("/api/annotation-types/{type_id}")
async def api_delete_annotation_type(type_id: str):
    """사용자 정의 주석 유형 삭제.

    주의: 기본 프리셋(person, place, term, allusion, note)은 삭제할 수 없다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    removed = remove_custom_type(_library_path, type_id)
    if not removed:
        return JSONResponse({"error": f"유형 '{type_id}'를 찾을 수 없거나 기본 프리셋입니다."}, status_code=404)

    return JSONResponse(status_code=204, content=None)


# ──────────────────────────────────────────────────────────
# 사전형 주석 API (L7 Dictionary Annotation)
# ──────────────────────────────────────────────────────────


# ── 단계별 사전 생성 ──


@router.post("/api/interpretations/{interp_id}/pages/{page_num}/annotations/generate-stage1")
async def api_dict_generate_stage1(interp_id: str, page_num: int, body: DictStageRequest):
    """1단계 사전 생성: 원문에서 사전 항목 추출.

    목적: L4 원문을 분석하여 표제어, 독음, 사전적 의미, 출전을 생성한다.
    전제 조건: L4 원문이 존재해야 한다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    try:
        llm_router = _get_llm_router()
        if body.force_provider:
            llm_router.force_provider = body.force_provider
        if body.force_model:
            llm_router.force_model = body.force_model

        result = await generate_stage1_from_original(
            interp_path=interp_path,
            part_id="main",
            page_num=page_num,
            block_id=body.block_id,
            router=llm_router,
        )
        return result
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": f"1단계 사전 생성 실패: {e}"}, status_code=500)


@router.post("/api/interpretations/{interp_id}/pages/{page_num}/annotations/generate-stage2")
async def api_dict_generate_stage2(interp_id: str, page_num: int, body: DictStageRequest):
    """2단계 사전 생성: 번역으로 보강.

    목적: 1단계 결과에 L6 번역의 문맥적 의미를 보강한다.
    전제 조건: 1단계 완료 + L6 번역이 존재해야 한다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    try:
        llm_router = _get_llm_router()
        if body.force_provider:
            llm_router.force_provider = body.force_provider
        if body.force_model:
            llm_router.force_model = body.force_model

        result = await generate_stage2_from_translation(
            interp_path=interp_path,
            part_id="main",
            page_num=page_num,
            block_id=body.block_id,
            router=llm_router,
        )
        return result
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": f"2단계 사전 생성 실패: {e}"}, status_code=500)


@router.post("/api/interpretations/{interp_id}/pages/{page_num}/annotations/generate-stage3")
async def api_dict_generate_stage3(interp_id: str, page_num: int, body: DictStageRequest):
    """3단계 사전 생성: 원문+번역 최종 통합.

    목적: 원문과 번역을 종합하여 사전 항목을 최종 정리한다.
    전제 조건: 원문 + 번역이 모두 존재. 1→2단계 완료 또는 일괄 생성 모드.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    try:
        llm_router = _get_llm_router()
        if body.force_provider:
            llm_router.force_provider = body.force_provider
        if body.force_model:
            llm_router.force_model = body.force_model

        result = await generate_stage3_from_both(
            interp_path=interp_path,
            part_id="main",
            page_num=page_num,
            block_id=body.block_id,
            router=llm_router,
        )
        return result
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": f"3단계 사전 생성 실패: {e}"}, status_code=500)


@router.post("/api/interpretations/{interp_id}/annotations/generate-batch")
async def api_dict_generate_batch(interp_id: str, body: DictBatchRequest):
    """일괄 사전 생성 (Stage 3 직행).

    목적: 완성된 원문+번역 쌍에서 모든 페이지의 사전을 한번에 생성한다.
    용도: 이미 완성된 작업에서 사전을 추출하여 다른 문헌 참조 사전으로 활용.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    try:
        llm_router = _get_llm_router()
        if body.force_provider:
            llm_router.force_provider = body.force_provider
        if body.force_model:
            llm_router.force_model = body.force_model

        # 대상 페이지 결정
        if body.pages:
            pages = body.pages
        else:
            # L4 텍스트 파일이 있는 모든 페이지를 스캔
            text_dir = interp_path / "L4_text" / "main_text"
            if not text_dir.exists():
                return JSONResponse({"error": "L4 텍스트가 없습니다."}, status_code=404)
            pages = sorted(
                int(f.stem.split("_page_")[1].split("_")[0])
                for f in text_dir.glob("main_page_*_text.json")
            )

        # 각 페이지별 블록에 대해 Stage 3 실행
        total_results = {"pages_processed": 0, "total_annotations": 0, "errors": []}

        for page_num in pages:
            try:
                # 페이지의 모든 블록 찾기
                ann_data = load_annotations(interp_path, "main", page_num)
                block_ids = [b["block_id"] for b in ann_data.get("blocks", [])]

                # 블록이 없으면 L4 텍스트에서 블록 ID 추출
                if not block_ids:
                    text_file = text_dir / f"main_page_{page_num:03d}_text.json"
                    if text_file.exists():
                        import json as _json
                        with open(text_file, encoding="utf-8") as f:
                            text_data = _json.load(f)
                        block_ids = [b["block_id"] for b in text_data.get("blocks", [])]

                for block_id in block_ids:
                    result = await generate_stage3_from_both(
                        interp_path=interp_path,
                        part_id="main",
                        page_num=page_num,
                        block_id=block_id,
                        router=llm_router,
                    )
                    total_results["total_annotations"] += len(result.get("annotations", []))

                total_results["pages_processed"] += 1
            except Exception as e:
                total_results["errors"].append({"page": page_num, "error": str(e)})

        return total_results
    except Exception as e:
        return JSONResponse({"error": f"일괄 사전 생성 실패: {e}"}, status_code=500)


# ── 사전 내보내기/가져오기 ──


@router.get("/api/interpretations/{interp_id}/export/dictionary")
async def api_export_dictionary(interp_id: str, page_start: int | None = None, page_end: int | None = None):
    """사전 내보내기.

    목적: 해석의 L7 사전형 주석을 독립 사전 JSON으로 추출한다.
    쿼리 파라미터: page_start, page_end — 페이지 범위 (선택).
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    # 문서 정보 가져오기
    meta_file = interp_path / "interpretation.json"
    doc_id = interp_id
    doc_title = interp_id
    if meta_file.exists():
        import json as _json
        with open(meta_file, encoding="utf-8") as f:
            meta = _json.load(f)
        doc_id = meta.get("document_id", interp_id)
        doc_title = meta.get("document_title", interp_id)

    page_range = None
    if page_start is not None and page_end is not None:
        page_range = (page_start, page_end)

    result = export_dictionary(
        interp_path=interp_path,
        doc_id=doc_id,
        doc_title=doc_title,
        interp_id=interp_id,
        page_range=page_range,
    )

    return result


@router.post("/api/interpretations/{interp_id}/export/dictionary/save")
async def api_save_export(interp_id: str):
    """사전 내보내기 파일 저장.

    목적: 내보내기 결과를 해석 저장소의 exports/ 디렉토리에 저장한다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    # 먼저 전체 내보내기 생성
    meta_file = interp_path / "interpretation.json"
    doc_id = interp_id
    doc_title = interp_id
    if meta_file.exists():
        import json as _json
        with open(meta_file, encoding="utf-8") as f:
            meta = _json.load(f)
        doc_id = meta.get("document_id", interp_id)
        doc_title = meta.get("document_title", interp_id)

    dictionary_data = export_dictionary(interp_path, doc_id, doc_title, interp_id)
    saved_path = save_export(interp_path, dictionary_data)

    return {
        "saved_path": str(saved_path),
        "total_entries": dictionary_data["statistics"]["total_entries"],
    }


@router.post("/api/interpretations/{interp_id}/import/dictionary")
async def api_import_dictionary(interp_id: str, body: DictImportRequest):
    """사전 가져오기.

    목적: 다른 문헌에서 내보낸 사전을 현재 해석에 병합한다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    result = import_dictionary(
        interp_path=interp_path,
        dictionary_data=body.dictionary_data,
        target_page=body.target_page,
        merge_strategy=body.merge_strategy,
    )

    return result


# ── 참조 사전 관리 ──


@router.get("/api/interpretations/{interp_id}/reference-dicts")
async def api_list_reference_dicts(interp_id: str):
    """참조 사전 목록 조회.

    목적: 등록된 참조 사전 파일 목록을 반환한다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    dicts = list_reference_dicts(interp_path)
    return {"reference_dicts": dicts}


@router.post("/api/interpretations/{interp_id}/reference-dicts")
async def api_register_reference_dict(interp_id: str, body: RefDictRegisterRequest):
    """참조 사전 등록.

    목적: 내보내기된 사전 파일을 참조 사전으로 등록한다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    saved_path = register_reference_dict(interp_path, body.dictionary_data, body.filename)
    return {"saved_path": str(saved_path), "filename": saved_path.name}


@router.delete("/api/interpretations/{interp_id}/reference-dicts/{filename}")
async def api_remove_reference_dict(interp_id: str, filename: str):
    """참조 사전 삭제."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    removed = remove_reference_dict(interp_path, filename)
    if not removed:
        return JSONResponse({"error": f"참조 사전 '{filename}'을 찾을 수 없습니다."}, status_code=404)

    return JSONResponse(status_code=204, content=None)


@router.post("/api/interpretations/{interp_id}/reference-dicts/match")
async def api_match_reference_dicts(interp_id: str, body: RefDictMatchRequest):
    """참조 사전 매칭.

    목적: 원문 블록에서 참조 사전의 표제어를 자동 매칭한다.
    입력: blocks — [{block_id, text}, ...], ref_filenames — 사용할 참조 사전 (선택).
    출력: 매칭 결과 리스트.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    matches = match_page_blocks(interp_path, body.blocks, body.ref_filenames)

    return {"matches": matches}


# ── 번역↔주석 연동 ──


@router.get("/api/interpretations/{interp_id}/pages/{page_num}/annotations/translation-changed")
async def api_check_translation_changed(interp_id: str, page_num: int):
    """번역 변경 감지.

    목적: 주석의 translation_snapshot과 현재 번역을 비교하여 변경 여부를 반환한다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    part_id = "main"
    ann_data = load_annotations(interp_path, part_id, page_num)

    from core.translation import load_translations
    tr_data = load_translations(interp_path, part_id, page_num)

    changed = check_translation_changed(ann_data, tr_data)
    return {"translation_changed": len(changed) > 0, "changed_annotations": changed}


# ──────────────────────────────────────
# 인용 마크 (Citation Mark) API
# ──────────────────────────────────────


@router.get("/api/interpretations/{interp_id}/pages/{page_num}/citation-marks")
async def api_get_citation_marks(
    interp_id: str,
    page_num: int,
    part_id: str = Query("main", description="권 식별자"),
):
    """페이지의 인용 마크 목록을 반환한다.

    목적: 인용 편집기에서 해당 페이지의 마크 목록을 표시.
    입력:
        interp_id — 해석 저장소 ID.
        page_num — 페이지 번호.
        part_id — 권 식별자.
    출력: {part_id, page_number, marks: [...]}.
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

    return load_citation_marks(interp_path, part_id, page_num)


@router.post("/api/interpretations/{interp_id}/pages/{page_num}/citation-marks")
async def api_add_citation_mark(
    interp_id: str,
    page_num: int,
    body: CitationMarkAddRequest,
    part_id: str = Query("main", description="권 식별자"),
):
    """인용 마크를 추가한다.

    목적: 연구자가 원문 또는 번역에서 텍스트를 드래그하여 인용 마크를 생성.
    입력:
        body — {block_id, start, end, marked_from, source_text_snapshot, label?, tags?}.
    출력: 추가된 인용 마크.
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

    data = load_citation_marks(interp_path, part_id, page_num)
    mark = {
        "source": {
            "block_id": body.block_id,
            "start": body.start,
            "end": body.end,
        },
        "marked_from": body.marked_from,
        "source_text_snapshot": body.source_text_snapshot,
        "label": body.label,
        "tags": body.tags,
    }

    try:
        added = add_citation_mark(data, mark)
        save_citation_marks(interp_path, part_id, page_num, data)
        # git commit을 별도 스레드에서 실행하여 이벤트 루프 블로킹 방지
        asyncio.get_event_loop().create_task(
            asyncio.to_thread(
                git_commit_interpretation, interp_path,
                f"feat: 인용 마크 추가 — page {page_num}, {body.block_id}",
            )
        )
        return added
    except Exception as e:
        return JSONResponse({"error": f"인용 마크 추가 실패: {e}"}, status_code=400)


@router.put("/api/interpretations/{interp_id}/pages/{page_num}/citation-marks/{mark_id}")
async def api_update_citation_mark(
    interp_id: str,
    page_num: int,
    mark_id: str,
    body: CitationMarkUpdateRequest,
    part_id: str = Query("main", description="권 식별자"),
):
    """인용 마크를 수정한다.

    목적: 라벨, 태그, citation_override, 상태 등을 수정.
    입력:
        mark_id — 인용 마크 ID.
        body — 수정할 필드.
    출력: 수정된 인용 마크.
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

    data = load_citation_marks(interp_path, part_id, page_num)

    # body에서 None이 아닌 필드만 업데이트
    updates = {}
    if body.label is not None:
        updates["label"] = body.label
    if body.tags is not None:
        updates["tags"] = body.tags
    if body.citation_override is not None:
        updates["citation_override"] = body.citation_override
    if body.status is not None:
        updates["status"] = body.status
    if body.marked_from is not None:
        updates["marked_from"] = body.marked_from

    updated = update_citation_mark(data, mark_id, updates)
    if updated is None:
        return JSONResponse(
            {"error": f"인용 마크를 찾을 수 없습니다: {mark_id}"},
            status_code=404,
        )

    try:
        save_citation_marks(interp_path, part_id, page_num, data)
        asyncio.get_event_loop().create_task(
            asyncio.to_thread(
                git_commit_interpretation, interp_path,
                f"fix: 인용 마크 수정 — {mark_id}",
            )
        )
        return updated
    except Exception as e:
        return JSONResponse({"error": f"인용 마크 수정 실패: {e}"}, status_code=400)


@router.delete("/api/interpretations/{interp_id}/pages/{page_num}/citation-marks/{mark_id}")
async def api_delete_citation_mark(
    interp_id: str,
    page_num: int,
    mark_id: str,
    part_id: str = Query("main", description="권 식별자"),
):
    """인용 마크를 삭제한다.

    목적: 더 이상 인용하지 않을 마크를 삭제.
    입력: mark_id — 인용 마크 ID.
    출력: {status: "deleted"}.
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

    data = load_citation_marks(interp_path, part_id, page_num)
    removed = remove_citation_mark(data, mark_id)

    if not removed:
        return JSONResponse(
            {"error": f"인용 마크를 찾을 수 없습니다: {mark_id}"},
            status_code=404,
        )

    try:
        save_citation_marks(interp_path, part_id, page_num, data)
        asyncio.get_event_loop().create_task(
            asyncio.to_thread(
                git_commit_interpretation, interp_path,
                f"fix: 인용 마크 삭제 — {mark_id}",
            )
        )
        return {"status": "deleted", "mark_id": mark_id}
    except Exception as e:
        return JSONResponse({"error": f"인용 마크 삭제 실패: {e}"}, status_code=400)


@router.get("/api/interpretations/{interp_id}/citation-marks/all")
async def api_list_all_citation_marks(
    interp_id: str,
    part_id: str = Query("main", description="권 식별자"),
):
    """전체 페이지의 인용 마크를 통합 수집하여 반환한다.

    목적: 인용 패널의 "전체 보기" 모드.
    입력: interp_id, part_id.
    출력: [{page_number, id, source, ...}, ...].
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

    return list_all_citation_marks(interp_path, part_id)


@router.post("/api/interpretations/{interp_id}/pages/{page_num}/citation-marks/{mark_id}/resolve")
async def api_resolve_citation_mark(
    interp_id: str,
    page_num: int,
    mark_id: str,
    part_id: str = Query("main", description="권 식별자"),
):
    """인용 마크 1개의 통합 컨텍스트(L4+L5+L6+L7+서지정보)를 조회한다.

    목적: 연구자가 인용 마크를 클릭했을 때 원문+표점본+번역+주석을 통합 표시.
    입력: interp_id, page_num, mark_id.
    출력: {mark, original_text, punctuated_text, translations, annotations, bibliography, text_changed}.
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

    # 인용 마크 찾기
    data = load_citation_marks(interp_path, part_id, page_num)
    mark = None
    for m in data.get("marks", []):
        if m["id"] == mark_id:
            mark = m
            break

    if mark is None:
        return JSONResponse(
            {"error": f"인용 마크를 찾을 수 없습니다: {mark_id}"},
            status_code=404,
        )

    # 문서 ID 조회 (해석 매니페스트에서)
    manifest_path = interp_path / "manifest.json"
    if not manifest_path.exists():
        return JSONResponse(
            {"error": "해석 매니페스트를 찾을 수 없습니다."},
            status_code=404,
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    doc_id = manifest.get("source_document_id", "")

    try:
        context = resolve_citation_context(
            library_path=_library_path,
            doc_id=doc_id,
            interp_path=interp_path,
            part_id=part_id,
            page_num=page_num,
            mark=mark,
        )
        return context
    except Exception as e:
        return JSONResponse({"error": f"인용 컨텍스트 조회 실패: {e}"}, status_code=500)


@router.post("/api/interpretations/{interp_id}/citation-marks/export")
async def api_export_citations(
    interp_id: str,
    body: CitationExportRequest,
    part_id: str = Query("main", description="권 식별자"),
):
    """선택한 인용 마크들을 학술 인용 형식으로 변환한다.

    목적: 연구자가 선택한 마크들을 논문에 붙여넣을 수 있는 형식으로 내보내기.
    입력:
        body — {mark_ids: [...], include_translation: bool}.
    출력: {citations: "formatted text", count: N}.
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

    # 문서 ID 조회
    manifest_path = interp_path / "manifest.json"
    if not manifest_path.exists():
        return JSONResponse(
            {"error": "해석 매니페스트를 찾을 수 없습니다."},
            status_code=404,
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    doc_id = manifest.get("source_document_id", "")

    # 전체 마크에서 선택된 것 찾기
    all_marks = list_all_citation_marks(interp_path, part_id)
    mark_map = {m["id"]: m for m in all_marks}

    contexts = []
    skipped = 0
    for mid in body.mark_ids:
        if mid not in mark_map:
            logger.warning("인용 내보내기: mark_id '%s'를 찾을 수 없음 (skip)", mid)
            skipped += 1
            continue
        mark = mark_map[mid]
        page_num = mark.get("page_number", 1)
        try:
            ctx = resolve_citation_context(
                library_path=_library_path,
                doc_id=doc_id,
                interp_path=interp_path,
                part_id=part_id,
                page_num=page_num,
                mark=mark,
            )
            contexts.append(ctx)
        except Exception as e:
            logger.warning(
                "인용 내보내기: mark '%s' (page %s) resolve 실패: %s",
                mid, page_num, e,
            )
            skipped += 1
            continue

    citations_text = export_citations(
        contexts,
        include_translation=body.include_translation,
        export_options=body.export_options,
    )
    return {
        "citations": citations_text,
        "count": len(contexts),
        "skipped": skipped,
    }


# ──────────────────────────────────────────────────────────
# AI 주석 태깅 (LLM Annotation)
# ──────────────────────────────────────────────────────────


@router.post("/api/llm/annotation")
async def api_llm_annotation(body: AiAnnotationRequest):
    """AI 주석 태깅.

    입력: 원문 텍스트
    출력: 태깅된 주석 배열 (인명, 지명, 관직, 전고 등)
    """
    try:
        result = await _call_llm_text(
            "annotation", body.text,
            force_provider=body.force_provider,
            force_model=body.force_model,
        )
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ──────────────────────────────────────────────────────────
# SSE 스트리밍 AI 주석 + 일괄 저장
# ──────────────────────────────────────────────────────────
#
# 기존 /api/llm/annotation을 수정하지 않고 /stream 엔드포인트를 추가.
# 주석 일괄 저장도 N건 순차 POST → 1건 batch POST로 최적화.


@router.post("/api/llm/annotation/stream")
async def api_llm_annotation_stream(body: AiAnnotationRequest):
    """AI 주석 태깅 SSE 스트리밍.

    기존 api_llm_annotation과 동일한 결과를 반환하되,
    LLM 응답 대기 중 progress 이벤트를 실시간으로 전달한다.
    """
    import asyncio
    import json as _json

    queue: asyncio.Queue = asyncio.Queue()

    async def _run_llm():
        await _call_llm_text_stream(
            "annotation", body.text, queue,
            force_provider=body.force_provider,
            force_model=body.force_model,
        )

    async def _event_generator():
        task = asyncio.create_task(_run_llm())
        try:
            while True:
                data = await queue.get()
                event_type = data.get("type", "progress")
                yield f"data: {_json.dumps(data, ensure_ascii=False)}\n\n"
                if event_type in ("complete", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


class AnnotationBatchSaveRequest(BaseModel):
    """주석 일괄 저장 요청.

    왜 필요한가:
        AI 태깅 후 N개 주석을 개별 POST로 저장하면 N번의 왕복이 필요하다.
        이 엔드포인트는 1회 POST로 N개를 저장한다.
    """
    annotations: list[dict]


@router.post(
    "/api/interpretations/{interp_id}/pages/{page_num}/annotations/{block_id}/batch"
)
async def api_batch_save_annotations(
    interp_id: str, page_num: int, block_id: str,
    body: AnnotationBatchSaveRequest,
):
    """주석 일괄 저장. N건을 1 POST로 처리.

    입력: annotations — [{target, type, content}, ...] 배열.
    출력: {saved: N, errors: [...]}
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소 '{interp_id}'를 찾을 수 없습니다."},
            status_code=404,
        )

    part_id = "main"
    data = load_annotations(interp_path, part_id, page_num)

    saved = 0
    errors = []
    for i, ann in enumerate(body.annotations):
        try:
            annotation = {
                "target": ann.get("target", {}),
                "type": ann.get("type", "term"),
                "content": ann.get("content", {}),
                "annotator": ann.get("annotator", {
                    "type": "llm", "model": None, "draft_id": None,
                }),
                "status": ann.get("status", "draft"),
                "reviewed_by": None,
                "reviewed_at": None,
            }
            add_ann(data, block_id, annotation)
            saved += 1
        except Exception as e:
            errors.append({"index": i, "error": str(e)})

    try:
        save_annotations(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(
                interp_path, f"feat: L7 주석 일괄 저장 — page {page_num} ({saved}건)"
            )
        except Exception:
            pass
        return {"saved": saved, "errors": errors}
    except Exception as e:
        return JSONResponse({"error": f"주석 저장 실패: {e}"}, status_code=400)
