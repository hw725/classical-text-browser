"""독서(reading) 관련 API 라우터.

Phase 11-1 / 11-2 엔드포인트를 포함한다.
- L5 표점(句讀) CRUD + 프리셋
- L5 현토(懸吐) CRUD
- L5 비교 모드 (l5_compare)
- L6 번역(Translation) CRUD
- 페이지 비고(Notes) 조회/저장
- LLM 표점·번역 생성

모든 경로에서 서고 경로는 get_library_path()로 참조한다.
"""

import json
import logging

from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app._state import get_library_path, _call_llm_text
from core.interpretation import (
    get_layer_content,
    get_page_notes,
    git_commit_interpretation,
    save_page_notes,
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
from core.translation import (
    add_translation,
    get_translation_status,
    load_translations,
    remove_translation,
    save_translations,
    update_translation,
)
from core.translation_llm import commit_translation_draft

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reading"])


# ───────────────────────────────────────────────────
# Pydantic 요청 모델
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


class TranslationAddRequest(BaseModel):
    """수동 번역 입력 요청."""
    source: dict
    source_text: str
    translation: str
    target_language: str = "ko"
    hyeonto_text: str | None = None


class TranslationUpdateRequest(BaseModel):
    """번역 수정 요청."""
    translation: str | None = None
    status: str | None = None


class TranslationCommitRequest(BaseModel):
    """Draft 확정 요청."""
    modifications: dict | None = None


class NotesSaveRequest(BaseModel):
    """비고 저장 요청 모델."""
    entries: list[dict]


class AiPunctuationRequest(BaseModel):
    """AI 표점 요청."""
    text: str                         # 표점할 원문 텍스트
    force_provider: str | None = None
    force_model: str | None = None


class AiTranslationRequest(BaseModel):
    """AI 번역 요청."""
    text: str                         # 번역할 원문 텍스트
    force_provider: str | None = None
    force_model: str | None = None


# ───────────────────────────────────────────────────
# 표점 프리셋
# ───────────────────────────────────────────────────


@router.get("/api/punctuation-presets")
async def api_punctuation_presets():
    """표점 부호 프리셋 목록을 반환한다."""
    # __file__ = src/app/routers/reading.py → 4단계 올라가야 프로젝트 루트
    # 왜 .parent가 4개인가: routers/ → app/ → src/ → 프로젝트루트
    presets_path = Path(__file__).resolve().parent.parent.parent.parent / "resources" / "punctuation_presets.json"
    if not presets_path.exists():
        return {"presets": [], "custom": []}
    import json as _json
    with open(presets_path, encoding="utf-8") as f:
        return _json.load(f)


# ───────────────────────────────────────────────────
# Phase 11-1: L5 표점(句讀) API
# ───────────────────────────────────────────────────


@router.get("/api/interpretations/{interp_id}/pages/{page_num}/l5_compare")
async def api_l5_compare(
    interp_id: str,
    page_num: int,
    kind: str = Query("punctuation", description="L5 종류: punctuation | hyeonto"),
    part_id: str = Query("main", description="권 식별자"),
):
    """비교 모드용 L5 페이지 전체 데이터 조회.

    목적: 한 페이지에 속한 모든 블록의 표점 또는 현토 데이터를 수집하여
          텍스트 비교에 적합한 형태로 반환한다.

    왜 이렇게 하는가:
        기존 /punctuation, /hyeonto API는 block_id를 필수로 받아
        단일 블록만 반환한다. 비교 탭은 페이지 단위로 두 저장소를
        비교하므로, 페이지의 모든 블록을 한 번에 가져와야 한다.

    입력:
        kind — "punctuation" (표점, 기본) 또는 "hyeonto" (현토).
        part_id — 권 식별자 (기본 "main").
    출력: {"blocks": [...], "text_summary": "줄 단위 비교용 텍스트"}.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    if kind not in ("punctuation", "hyeonto"):
        return JSONResponse(
            {"error": f"kind는 'punctuation' 또는 'hyeonto'여야 합니다. 받은 값: {kind}"},
            status_code=400,
        )

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소 '{interp_id}'를 찾을 수 없습니다."},
            status_code=404,
        )

    # L5_reading/main_text/ 디렉토리에서 해당 페이지·종류의 파일을 모두 수집
    l5_dir = interp_path / "L5_reading" / "main_text"
    if not l5_dir.exists():
        return {"blocks": [], "text_summary": ""}

    page_prefix = f"{part_id}_page_{page_num:03d}"
    suffix = f"_{kind}.json"
    blocks = []

    import glob as glob_mod

    # 블록별 파일 + 레거시 페이지 파일 모두 수집
    pattern = str(l5_dir / f"{page_prefix}*{suffix}")
    for fpath in sorted(glob_mod.glob(pattern)):
        try:
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
            blocks.append(data)
        except (json.JSONDecodeError, OSError):
            continue

    # 비교용 텍스트 요약 생성
    lines = []
    for blk in blocks:
        bid = blk.get("block_id", "unknown")
        if kind == "punctuation":
            items = blk.get("marks", [])
            lines.append(f"[블록: {bid}]")
            for m in items:
                t = m.get("target", {})
                s, e = t.get("start", "?"), t.get("end", "?")
                before = m.get("before") or ""
                after = m.get("after") or ""
                # before와 after를 모두 보여주어 비교 시 차이를 명확히 함
                parts = []
                if before:
                    parts.append(f"앞:{before}")
                if after:
                    parts.append(f"뒤:{after}")
                desc = " ".join(parts) if parts else "(빈 표점)"
                lines.append(f"  [{s}-{e}] {desc}")
        else:
            items = blk.get("annotations", [])
            lines.append(f"[블록: {bid}]")
            for a in items:
                t = a.get("target", {})
                s, e = t.get("start", "?"), t.get("end", "?")
                text = a.get("text", "")
                pos = a.get("position", "after")
                lines.append(f"  [{s}-{e}] \"{text}\" ({pos})")

    return {"blocks": blocks, "text_summary": "\n".join(lines)}


@router.get("/api/interpretations/{interp_id}/pages/{page_num}/punctuation")
async def api_get_punctuation(interp_id: str, page_num: int, block_id: str = Query(...)):
    """표점 조회.

    목적: 특정 블록의 L5 표점 데이터를 반환한다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 저장소 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    # part_id는 문헌에서 자동 추론 (현재는 "main" 기본값)
    part_id = "main"
    data = load_punctuation(interp_path, part_id, page_num, block_id)
    return data


@router.put("/api/interpretations/{interp_id}/pages/{page_num}/punctuation")
async def api_save_punctuation(interp_id: str, page_num: int, body: PunctuationSaveRequest):
    """표점 저장 (전체 덮어쓰기).

    목적: 블록의 표점 데이터를 저장한다. 스키마 검증 후 파일 기록.
    """
    _library_path = get_library_path()
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


@router.post("/api/interpretations/{interp_id}/pages/{page_num}/punctuation/{block_id}/marks")
async def api_add_mark(interp_id: str, page_num: int, block_id: str, body: MarkAddRequest):
    """개별 표점 추가."""
    _library_path = get_library_path()
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


@router.delete("/api/interpretations/{interp_id}/pages/{page_num}/punctuation/{block_id}/marks/{mark_id}")
async def api_delete_mark(interp_id: str, page_num: int, block_id: str, mark_id: str):
    """개별 표점 삭제."""
    _library_path = get_library_path()
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


@router.get("/api/interpretations/{interp_id}/pages/{page_num}/punctuation/{block_id}/preview")
async def api_punctuation_preview(interp_id: str, page_num: int, block_id: str):
    """합성 텍스트 미리보기.

    L4 원문에 표점을 적용한 결과 + 문장 분리를 반환.
    """
    _library_path = get_library_path()
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


@router.get("/api/interpretations/{interp_id}/pages/{page_num}/hyeonto")
async def api_get_hyeonto(interp_id: str, page_num: int, block_id: str = Query(...)):
    """현토 조회."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 저장소 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    part_id = "main"
    data = load_hyeonto(interp_path, part_id, page_num, block_id)
    return data


@router.put("/api/interpretations/{interp_id}/pages/{page_num}/hyeonto")
async def api_save_hyeonto(interp_id: str, page_num: int, body: HyeontoSaveRequest):
    """현토 저장 (전체 덮어쓰기)."""
    _library_path = get_library_path()
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


@router.post("/api/interpretations/{interp_id}/pages/{page_num}/hyeonto/{block_id}/annotations")
async def api_add_annotation(interp_id: str, page_num: int, block_id: str, body: AnnotationAddRequest):
    """개별 현토 추가."""
    _library_path = get_library_path()
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


@router.delete("/api/interpretations/{interp_id}/pages/{page_num}/hyeonto/{block_id}/annotations/{ann_id}")
async def api_delete_annotation(interp_id: str, page_num: int, block_id: str, ann_id: str):
    """개별 현토 삭제."""
    _library_path = get_library_path()
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


@router.get("/api/interpretations/{interp_id}/pages/{page_num}/hyeonto/{block_id}/preview")
async def api_hyeonto_preview(interp_id: str, page_num: int, block_id: str):
    """현토 합성 텍스트 미리보기.

    표점이 있으면 함께 적용한 결과를 반환.
    """
    _library_path = get_library_path()
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


# ───────────────────────────────────────────────────
# Phase 11-2: L6 번역(Translation) API
# ───────────────────────────────────────────────────


@router.get("/api/interpretations/{interp_id}/pages/{page_num}/translation")
async def api_get_translations(interp_id: str, page_num: int):
    """번역 조회.

    목적: 특정 페이지의 L6 번역 데이터를 반환한다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 저장소 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    part_id = "main"
    data = load_translations(interp_path, part_id, page_num)
    return data


@router.get("/api/interpretations/{interp_id}/pages/{page_num}/translation/status")
async def api_translation_status(interp_id: str, page_num: int):
    """번역 상태 요약.

    목적: 페이지의 번역 진행 상황을 한눈에 파악.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"
    data = load_translations(interp_path, part_id, page_num)
    return get_translation_status(data)


@router.post("/api/interpretations/{interp_id}/pages/{page_num}/translation")
async def api_add_translation(interp_id: str, page_num: int, body: TranslationAddRequest):
    """수동 번역 입력.

    목적: 사용자가 직접 번역을 입력한다. translator.type = "human", status = "accepted".
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_translations(interp_path, part_id, page_num)

    entry = {
        "source": body.source,
        "source_text": body.source_text,
        "hyeonto_text": body.hyeonto_text,
        "target_language": body.target_language,
        "translation": body.translation,
        "translator": {"type": "human", "model": None, "draft_id": None},
        "status": "accepted",
        "reviewed_by": None,
        "reviewed_at": None,
    }
    result = add_translation(data, entry)

    try:
        save_translations(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(interp_path, f"feat: L6 번역 추가 — page {page_num}")
        except Exception:
            pass
        return JSONResponse(result, status_code=201)
    except Exception as e:
        return JSONResponse({"error": f"번역 저장 실패: {e}"}, status_code=400)


@router.put("/api/interpretations/{interp_id}/pages/{page_num}/translation/{translation_id}")
async def api_update_translation(
    interp_id: str, page_num: int, translation_id: str, body: TranslationUpdateRequest
):
    """번역 수정."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_translations(interp_path, part_id, page_num)
    updates = {}
    if body.translation is not None:
        updates["translation"] = body.translation
    if body.status is not None:
        updates["status"] = body.status

    result = update_translation(data, translation_id, updates)
    if result is None:
        return JSONResponse({"error": f"번역 '{translation_id}'를 찾을 수 없습니다."}, status_code=404)

    try:
        save_translations(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(interp_path, f"feat: L6 번역 수정 — page {page_num}")
        except Exception:
            pass
        return result
    except Exception as e:
        return JSONResponse({"error": f"번역 저장 실패: {e}"}, status_code=400)


@router.post("/api/interpretations/{interp_id}/pages/{page_num}/translation/{translation_id}/commit")
async def api_commit_translation(
    interp_id: str, page_num: int, translation_id: str, body: TranslationCommitRequest
):
    """Draft 확정.

    목적: 연구자가 Draft를 검토 후 확정. status → "accepted".
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_translations(interp_path, part_id, page_num)
    result = commit_translation_draft(data, translation_id, body.modifications)

    if result is None:
        return JSONResponse({"error": f"번역 '{translation_id}'를 찾을 수 없습니다."}, status_code=404)

    try:
        save_translations(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(interp_path, f"feat: L6 번역 확정 — page {page_num}")
        except Exception:
            pass
        return result
    except Exception as e:
        return JSONResponse({"error": f"번역 저장 실패: {e}"}, status_code=400)


@router.delete("/api/interpretations/{interp_id}/pages/{page_num}/translation/{translation_id}")
async def api_delete_translation(interp_id: str, page_num: int, translation_id: str):
    """번역 삭제."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_translations(interp_path, part_id, page_num)
    removed = remove_translation(data, translation_id)

    if not removed:
        return JSONResponse({"error": f"번역 '{translation_id}'를 찾을 수 없습니다."}, status_code=404)

    save_translations(interp_path, part_id, page_num, data)
    return JSONResponse(status_code=204, content=None)


# ───────────────────────────────────────────────────
# 페이지 비고(Notes) API
# ───────────────────────────────────────────────────


@router.get("/api/interpretations/{interp_id}/pages/{page_num}/notes")
async def api_get_notes(
    interp_id: str,
    page_num: int,
    part_id: str = Query("main", description="권 식별자"),
):
    """페이지 비고(메모)를 조회한다.

    목적: 연구자가 작성한 자유 메모를 불러온다.
          아직 어디로 편입될지 미확정인 내용(임시 메모, 질문 등)을 보관한다.
    입력:
        interp_id — 해석 저장소 ID.
        page_num — 페이지 번호.
        part_id — 권 식별자 (기본 "main").
    출력: {part_id, page, entries, exists}.
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

    return get_page_notes(interp_path, part_id, page_num)


@router.put("/api/interpretations/{interp_id}/pages/{page_num}/notes")
async def api_save_notes(
    interp_id: str,
    page_num: int,
    body: NotesSaveRequest,
    part_id: str = Query("main", description="권 식별자"),
):
    """페이지 비고(메모)를 저장한다.

    목적: 연구자가 작성한 자유 메모를 _notes/ 디렉토리에 저장하고 자동 커밋한다.
    입력:
        interp_id — 해석 저장소 ID.
        page_num — 페이지 번호.
        body — {entries: [{text, created_at, updated_at}, ...]}.
        part_id — 권 식별자 (기본 "main").
    출력: {status, file_path, count}.
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
        result = save_page_notes(interp_path, part_id, page_num, body.entries)
        # 자동 git commit
        try:
            git_commit_interpretation(
                interp_path,
                f"docs: 비고 저장 — page {page_num}",
            )
        except Exception:
            pass
        return result
    except Exception as e:
        return JSONResponse({"error": f"비고 저장 실패: {e}"}, status_code=400)


# ───────────────────────────────────────────────────
# LLM 표점/번역 헬퍼 함수
# ───────────────────────────────────────────────────


def _normalize_punct_marks(raw_marks: list) -> list:
    """LLM이 반환한 marks를 {start, end, before, after} 형식으로 정규화.

    왜 이렇게 하는가:
        LLM은 프롬프트와 다른 형식으로 응답할 수 있다.
        구형식 {after_char_index, mark}이든 신형식 {start, end, before, after}이든
        클라이언트가 일관되게 처리할 수 있도록 표준화한다.

    방어 처리:
        LLM이 marks 배열에 dict가 아닌 항목(문자열, 정수 등)을
        포함할 수 있으므로, dict가 아닌 항목은 무시한다.
    """
    import logging as _log
    _logger = _log.getLogger(__name__)
    normalized = []
    for m in raw_marks:
        # dict가 아닌 항목 방어 (LLM이 ["。","，"] 등 반환 시)
        if not isinstance(m, dict):
            _logger.warning(f"_normalize_punct_marks: dict가 아닌 mark 항목 무시: {m!r}")
            continue
        if "after_char_index" in m:
            # 구형식: {after_char_index: int, mark: str}
            # → after_char_index번째 글자 뒤에 mark를 삽입
            idx = m["after_char_index"]
            if not isinstance(idx, int):
                try:
                    idx = int(idx)
                except (ValueError, TypeError):
                    continue
            normalized.append({
                "start": idx, "end": idx,
                "before": None, "after": m.get("mark"),
            })
        else:
            # 신형식: 이미 {start, end, before, after}
            start = m.get("start", 0)
            end = m.get("end", start)
            # 인덱스가 문자열로 올 수 있다 ("3" → 3)
            try:
                start = int(start) if start is not None else 0
                end = int(end) if end is not None else start
            except (ValueError, TypeError):
                continue
            normalized.append({
                "start": start,
                "end": end,
                "before": m.get("before"),
                "after": m.get("after"),
            })
    return normalized


def _extract_marks_from_punctuated(original: str, punctuated: str) -> list:
    """표점이 삽입된 텍스트에서 marks를 역추출한다.

    왜 이렇게 하는가:
        LLM이 {"marks": [...]} 형식 대신 표점문(예: "표점문", "result")을
        반환하는 경우가 빈번하다. 원문과 표점문을 비교하여 삽입된 부호의
        위치를 자동 추출하면 어떤 형식이든 처리할 수 있다.

    알고리즘:
        원문 글자를 기준으로 표점문을 순서대로 대조한다.
        원문에 없는 글자가 나오면 표점 부호로 간주하고,
        직전 원문 글자의 after에 축적한다.
    """
    import re as _re
    # 원문·표점문 모두 공백 제거
    orig = _re.sub(r'\s+', '', original)
    punct = _re.sub(r'\s+', '', punctuated)

    marks = []
    oi = 0  # 원문 인덱스
    pending_after = ""  # 직전 글자 뒤에 붙일 부호 축적

    for ch in punct:
        if oi < len(orig) and ch == orig[oi]:
            # 원문 글자 — 축적된 부호가 있으면 직전 글자의 after로 기록
            if pending_after and oi > 0:
                marks.append({
                    "start": oi - 1, "end": oi - 1,
                    "before": None, "after": pending_after,
                })
                pending_after = ""
            oi += 1
        else:
            # 원문에 없는 글자 → 표점 부호
            pending_after += ch

    # 마지막 글자 뒤에 남은 부호 처리
    if pending_after and oi > 0:
        marks.append({
            "start": oi - 1, "end": oi - 1,
            "before": None, "after": pending_after,
        })

    return marks


# ───────────────────────────────────────────────────
# LLM 표점·번역 API
# ───────────────────────────────────────────────────


@router.post("/api/llm/punctuation")
async def api_llm_punctuation(body: AiPunctuationRequest):
    """AI 표점 생성.

    입력: 원문 텍스트
    출력: 표점이 삽입된 텍스트 + marks 배열

    LLM 응답 형식 대응:
        1. {"marks": [...]} → 그대로 사용 (정규화)
        2. {"표점문": "..."} 또는 {"result": "..."} 등 → 원문 대조로 marks 역추출
    """
    import logging as _logging
    import re as _re
    _logger = _logging.getLogger(__name__)

    # 공백/줄바꿈 제거 — Ollama·OpenAI가 줄바꿈 포함 텍스트에서 빈 응답을 반환하는 문제 방지
    clean_text = _re.sub(r'\s+', '', body.text)
    if not clean_text:
        return JSONResponse(
            {"error": "표점할 텍스트가 비어 있습니다 (공백만 포함)."},
            status_code=400,
        )

    _logger.info(f"AI 표점 요청: {len(clean_text)}자, provider={body.force_provider or 'auto'}")

    try:
        result = await _call_llm_text(
            "punctuation", clean_text,
            force_provider=body.force_provider,
            force_model=body.force_model,
        )
        # ── marks 형식 정규화 ──
        if "marks" in result and isinstance(result["marks"], list):
            result["marks"] = _normalize_punct_marks(result["marks"])
            _logger.info(f"AI 표점 완료: marks {len(result['marks'])}개 (직접 반환)")
        else:
            # marks가 없으면 표점문에서 역추출 시도
            # LLM이 {"표점문": "..."}, {"result": "..."}, {"punctuated": "..."} 등
            # 다양한 키로 표점문을 반환할 수 있다.
            punct_text = None
            for key in ("표점문", "punctuated", "result", "text", "output"):
                val = result.get(key)
                # 표점문은 원문보다 길어야 함 (부호가 삽입되었으므로).
                # 같은 길이일 수도 있으므로 >= 조건 사용.
                if isinstance(val, str) and len(val) >= len(clean_text):
                    punct_text = val
                    _logger.info(f"AI 표점: marks 없음, '{key}' 키에서 표점문 역추출 시도")
                    break
            if punct_text:
                result["marks"] = _extract_marks_from_punctuated(clean_text, punct_text)
                _logger.info(f"AI 표점 완료: marks {len(result['marks'])}개 (표점문 역추출)")
            else:
                _logger.warning(
                    f"AI 표점: marks도 표점문도 없음. 응답 키: {list(result.keys())}"
                )
                result["marks"] = []
        return result
    except Exception as e:
        _logger.error(f"AI 표점 실패: {e}", exc_info=True)
        # 타임아웃 에러는 사용자에게 더 친절한 메시지 제공
        import httpx as _httpx
        if isinstance(e, (_httpx.ReadTimeout, _httpx.ConnectTimeout, _httpx.TimeoutException)):
            error_msg = (
                f"LLM 응답 시간 초과 ({body.force_provider or 'auto'}). "
                f"텍스트가 길면 다른 프로바이더를 시도하거나, Ollama 서버 상태를 확인하세요."
            )
        else:
            error_msg = str(e)
        return JSONResponse({"error": error_msg}, status_code=500)


@router.post("/api/llm/translation")
async def api_llm_translation(body: AiTranslationRequest):
    """AI 번역.

    입력: 원문 텍스트
    출력: 한국어 번역 + 참고사항
    """
    try:
        result = await _call_llm_text(
            "translation", body.text,
            force_provider=body.force_provider,
            force_model=body.force_model,
        )
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
