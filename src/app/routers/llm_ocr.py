"""LLM 4단 폴백 + OCR 엔진 연동 라우터.

server.py의 Phase 10-2 (LLM) / Phase 10-1 (OCR) 엔드포인트를 분리한 파일.

포함 라우트:
    GET  /api/llm/status
    GET  /api/llm/models
    GET  /api/llm/usage
    POST /api/llm/analyze-layout/{doc_id}/{page}
    POST /api/llm/compare-layout/{doc_id}/{page}
    POST /api/llm/drafts/{draft_id}/review
    GET  /api/ocr/engines
    POST /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr
    POST /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr/stream
    GET  /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr
    DELETE /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr
    DELETE /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr/{block_id}
    POST /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr/{block_id}
"""

import shutil
from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app._state import get_library_path, _get_llm_router, _get_ocr_pipeline, get_llm_drafts

router = APIRouter(tags=["llm_ocr"])


# ===========================================================================
#  Pydantic 요청 모델
# ===========================================================================

class DraftReviewRequest(BaseModel):
    """Draft 검토 요청 본문."""
    action: str  # "accept" | "modify" | "reject"
    quality_rating: int | None = None
    quality_notes: str | None = None
    modifications: str | None = None


class CompareLayoutRequest(BaseModel):
    """레이아웃 비교 요청 본문."""
    targets: list[str] | None = None


class OcrRunRequest(BaseModel):
    """OCR 실행 요청 본문."""
    engine_id: str | None = None        # None이면 기본 엔진
    block_ids: list[str] | None = None  # None이면 전체 블록
    force_provider: str | None = None   # LLM 프로바이더 지정 (llm_vision 엔진 전용)
    force_model: str | None = None      # LLM 모델 지정 (llm_vision 엔진 전용)
    paddle_lang: str | None = None      # PaddleOCR 언어 코드 (paddleocr 엔진 전용: ch, chinese_cht, korean, japan, en)


# ===========================================================================
#  헬퍼 함수
# ===========================================================================

def _load_page_image(doc_id: str, page: int) -> bytes | None:
    """페이지 이미지를 바이트로 로드한다 (LLM 전송용 리사이즈 포함).

    L1_source에서 PDF를 찾아 해당 페이지를 이미지로 변환.
    또는 이미 이미지 파일이면 직접 읽는다.
    LLM 비전 모델에 보내기 위해 최대 2000px, JPEG 압축을 적용한다.

    왜 리사이즈하는가:
        PDF에서 144 DPI로 추출하면 10MB+ PNG가 된다.
        base64 인코딩 시 14MB+ → Ollama 클라우드 프록시가 타임아웃/거부.
        LLM 비전 모델은 내부적으로 리사이즈하므로 2000px이면 충분하다.
    """
    from ocr.image_utils import resize_for_llm

    library_path = get_library_path()
    if library_path is None:
        return None

    doc_dir = library_path / "documents" / doc_id

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
                    raw = m.read_bytes()
                    return resize_for_llm(raw, max_long_side=2000)

    # 2. PDF에서 페이지 추출 (pymupdf/fitz 사용)
    pdf_files = list(source_dir.glob("*.pdf")) if source_dir.exists() else []
    if pdf_files:
        try:
            import fitz  # pymupdf

            doc = fitz.open(str(pdf_files[0]))
            # page는 1-indexed (API 경로), fitz는 0-indexed
            page_idx = page - 1
            if 0 <= page_idx < len(doc):
                pdf_page = doc[page_idx]
                # scale=2.0 → 144 DPI (기본 72 DPI × 2)
                pix = pdf_page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                raw = pix.tobytes("png")
                doc.close()
                return resize_for_llm(raw, max_long_side=2000)
            doc.close()
        except ImportError:
            pass  # pymupdf가 없으면 건너뜀

    return None


# ===========================================================================
#  Phase 10-2: LLM 4단 폴백 아키텍처 API
# ===========================================================================

@router.get("/api/llm/status")
async def api_llm_status():
    """각 provider의 가용 상태."""
    router_inst = _get_llm_router()
    return await router_inst.get_status()


@router.get("/api/llm/models")
async def api_llm_models():
    """GUI 드롭다운용 모델 목록."""
    router_inst = _get_llm_router()
    return await router_inst.get_available_models()


@router.get("/api/llm/usage")
async def api_llm_usage():
    """이번 달 사용량 요약."""
    router_inst = _get_llm_router()
    return router_inst.usage_tracker.get_monthly_summary()


@router.post("/api/llm/analyze-layout/{doc_id}/{page}")
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
    library_path = get_library_path()
    if library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    from core.layout_analyzer import analyze_page_layout

    router_inst = _get_llm_router()

    # 페이지 이미지 로드
    page_image = _load_page_image(doc_id, page)
    if not page_image:
        return JSONResponse(
            {"error": f"페이지 이미지 없음: {doc_id} page {page}"},
            status_code=404,
        )

    try:
        draft = await analyze_page_layout(
            router_inst, page_image,
            force_provider=force_provider,
            force_model=force_model,
        )
    except Exception as e:
        return JSONResponse({"error": f"레이아웃 분석 실패: {e}"}, status_code=500)

    # Draft 저장
    drafts = get_llm_drafts()
    drafts[draft.draft_id] = draft
    return draft.to_dict()


@router.post("/api/llm/compare-layout/{doc_id}/{page}")
async def api_compare_layout(doc_id: str, page: int, body: CompareLayoutRequest):
    """여러 모델로 레이아웃 분석 비교."""
    library_path = get_library_path()
    if library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    from core.layout_analyzer import compare_layout_analysis

    router_inst = _get_llm_router()

    page_image = _load_page_image(doc_id, page)
    if not page_image:
        return JSONResponse(
            {"error": f"페이지 이미지 없음: {doc_id} page {page}"},
            status_code=404,
        )

    # targets 파싱: ["base44_bridge", "ollama:glm-5:cloud"]
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
        draft_list = await compare_layout_analysis(
            router_inst, page_image, targets=parsed_targets,
        )
    except Exception as e:
        return JSONResponse({"error": f"레이아웃 비교 실패: {e}"}, status_code=500)

    # Draft들 저장
    drafts = get_llm_drafts()
    for d in draft_list:
        drafts[d.draft_id] = d

    return [d.to_dict() for d in draft_list]


@router.post("/api/llm/drafts/{draft_id}/review")
async def api_review_draft(draft_id: str, body: DraftReviewRequest):
    """Draft를 검토 (accept/modify/reject)."""
    drafts = get_llm_drafts()
    draft = drafts.get(draft_id)
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


# ===========================================================================
#  Phase 10-1: OCR 엔진 연동 API
# ===========================================================================

@router.get("/api/ocr/engines")
async def api_ocr_engines():
    """등록된 OCR 엔진 목록과 사용 가능 여부를 반환한다.

    목적: GUI의 OCR 실행 패널에서 엔진 드롭다운을 채우기 위해 사용한다.
    출력: {
        "engines": [{"engine_id": "paddleocr", "display_name": "PaddleOCR", "available": true, ...}],
        "default_engine": "paddleocr"
    }
    """
    library_path = get_library_path()
    if library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    _pipeline, registry = _get_ocr_pipeline()
    return {
        "engines": registry.list_engines(),
        "default_engine": registry.default_engine_id,
    }


@router.post("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr")
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
    library_path = get_library_path()
    if library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    pipeline, _registry = _get_ocr_pipeline()

    # LLM 엔진용 추가 인자 (force_provider, force_model)
    engine_kwargs = {}
    if body.force_provider:
        engine_kwargs["force_provider"] = body.force_provider
    if body.force_model:
        engine_kwargs["force_model"] = body.force_model

    # PaddleOCR 엔진: 언어 런타임 변경
    if body.paddle_lang and body.engine_id == "paddleocr":
        try:
            paddle_engine = _registry.get_engine("paddleocr")
            paddle_engine.lang = body.paddle_lang
        except Exception:
            pass  # 엔진이 없거나 사용 불가 — 무시 (아래 run_page에서 에러 처리)

    try:
        result = pipeline.run_page(
            doc_id=doc_id,
            part_id=part_id,
            page_number=page_number,
            engine_id=body.engine_id,
            block_ids=body.block_ids,
            **engine_kwargs,
        )
        return result.to_summary()
    except Exception as e:
        return JSONResponse(
            {"error": f"OCR 실행 실패: {e}"},
            status_code=500,
        )


@router.post("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr/stream")
async def api_run_ocr_stream(
    doc_id: str,
    part_id: str,
    page_number: int,
    body: OcrRunRequest,
):
    """OCR 실행 + SSE 스트리밍 진행률.

    목적: 블록별 진행률을 실시간으로 프론트엔드에 전달한다.
    출력: text/event-stream 형식.
        - progress 이벤트: {"type":"progress","current":2,"total":5,"block_id":"p01_b02"}
        - complete 이벤트: {"type":"complete", ...to_summary()}
        - error 이벤트: {"type":"error","error":"메시지"}
    """
    import asyncio
    import json as _json

    library_path = get_library_path()
    if library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    pipeline, _registry = _get_ocr_pipeline()

    # 엔진 설정 (기존 api_run_ocr와 동일)
    engine_kwargs = {}
    if body.force_provider:
        engine_kwargs["force_provider"] = body.force_provider
    if body.force_model:
        engine_kwargs["force_model"] = body.force_model
    if body.paddle_lang and body.engine_id == "paddleocr":
        try:
            paddle_engine = _registry.get_engine("paddleocr")
            paddle_engine.lang = body.paddle_lang
        except Exception:
            pass

    # asyncio.Queue를 사용해 동기 콜백 → 비동기 제너레이터로 연결
    progress_queue: asyncio.Queue = asyncio.Queue()

    def _on_progress(data: dict):
        """OCR 파이프라인(동기)에서 호출되는 콜백.
        asyncio 이벤트 루프에 안전하게 큐에 넣는다."""
        progress_queue.put_nowait(data)

    async def _run_ocr_in_thread():
        """OCR를 별도 스레드에서 실행하고 결과를 큐에 넣는다."""
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: pipeline.run_page(
                    doc_id=doc_id,
                    part_id=part_id,
                    page_number=page_number,
                    engine_id=body.engine_id,
                    block_ids=body.block_ids,
                    progress_callback=_on_progress,
                    **engine_kwargs,
                ),
            )
            await progress_queue.put({"type": "complete", **result.to_summary()})
        except Exception as e:
            await progress_queue.put({"type": "error", "error": str(e)})

    async def _event_generator():
        """SSE 이벤트를 생성하는 비동기 제너레이터."""
        # OCR를 백그라운드 태스크로 시작
        task = asyncio.create_task(_run_ocr_in_thread())
        try:
            while True:
                data = await progress_queue.get()
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


@router.get("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr")
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
    library_path = get_library_path()
    if library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    import json as _json

    filename = f"{part_id}_page_{page_number:03d}.json"
    ocr_path = library_path / "documents" / doc_id / "L2_ocr" / filename

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
        "file_path": str(ocr_path.relative_to(library_path)),
    }
    return data


@router.delete("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr")
async def api_delete_ocr_result(
    doc_id: str,
    part_id: str,
    page_number: int,
):
    """특정 페이지의 OCR 결과(L2)를 휴지통으로 이동한다."""
    library_path = get_library_path()
    if library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    filename = f"{part_id}_page_{page_number:03d}.json"
    legacy_filename = f"page_{page_number:03d}.json"
    ocr_path = doc_path / "L2_ocr" / filename

    if not ocr_path.exists():
        legacy_path = doc_path / "L2_ocr" / legacy_filename
        if legacy_path.exists():
            ocr_path = legacy_path
            filename = legacy_filename
        else:
            return JSONResponse(
                {"error": f"삭제할 OCR 결과가 없습니다: {doc_id}/{part_id}/page_{page_number:03d}"},
                status_code=404,
            )

    trash_dir = library_path / ".trash" / "ocr"
    trash_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    trash_name = f"{timestamp}_{doc_id}_{filename}"
    trash_path = trash_dir / trash_name

    try:
        shutil.move(str(ocr_path), str(trash_path))
    except Exception as e:
        return JSONResponse({"error": f"OCR 결과 삭제 실패: {e}"}, status_code=500)

    return {
        "status": "trashed",
        "document_id": doc_id,
        "part_id": part_id,
        "page_number": page_number,
        "trash_path": str(trash_path.relative_to(library_path)).replace("\\", "/"),
    }


@router.delete("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr/{block_id}")
async def api_delete_ocr_block_result(
    doc_id: str,
    part_id: str,
    page_number: int,
    block_id: str,
    index: int = Query(-1),
):
    """특정 OCR 결과 1건을 block_id + index로 강제 매칭하여 삭제한다.

    왜 이렇게 하는가:
      같은 페이지에서 layout_block_id가 겹치거나 중복 OCR 항목이 생길 수 있다.
      block_id만으로 삭제하면 여러 항목이 함께 지워질 위험이 있으므로,
      프론트가 보낸 index와 block_id를 동시에 검증해 단건만 삭제한다.
    """
    library_path = get_library_path()
    if library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    import json as _json

    filename = f"{part_id}_page_{page_number:03d}.json"
    legacy_filename = f"page_{page_number:03d}.json"
    ocr_path = doc_path / "L2_ocr" / filename

    if not ocr_path.exists():
        legacy_path = doc_path / "L2_ocr" / legacy_filename
        if legacy_path.exists():
            ocr_path = legacy_path
        else:
            return JSONResponse(
                {"error": f"OCR 결과가 없습니다: {doc_id}/{part_id}/page_{page_number:03d}"},
                status_code=404,
            )

    try:
        data = _json.loads(ocr_path.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"error": f"OCR 파일 읽기 실패: {e}"}, status_code=500)

    ocr_results = data.get("ocr_results")
    if not isinstance(ocr_results, list):
        return JSONResponse({"error": "OCR 결과 형식이 올바르지 않습니다."}, status_code=500)

    if index < 0 or index >= len(ocr_results):
        return JSONResponse(
            {
                "error": "삭제할 OCR 항목 index가 유효하지 않습니다.",
                "index": index,
                "total": len(ocr_results),
            },
            status_code=400,
        )

    normalized_block_id = str(block_id or "").strip()
    target = ocr_results[index]
    target_block_id = str(target.get("layout_block_id") or "").strip()

    if target_block_id != normalized_block_id:
        return JSONResponse(
            {
                "error": "block_id와 OCR 항목 index가 일치하지 않습니다.",
                "expected_block_id": normalized_block_id,
                "actual_block_id": target_block_id,
                "index": index,
            },
            status_code=409,
        )

    deleted_item = ocr_results.pop(index)
    data["ocr_results"] = ocr_results

    try:
        ocr_path.write_text(
            _json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        return JSONResponse({"error": f"OCR 파일 저장 실패: {e}"}, status_code=500)

    return {
        "status": "deleted",
        "document_id": doc_id,
        "part_id": part_id,
        "page_number": page_number,
        "block_id": normalized_block_id,
        "index": index,
        "remaining": len(ocr_results),
        "deleted_text": "".join(
            [(line.get("text") or "") for line in (deleted_item.get("lines") or [])]
        ),
    }


@router.post("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr/{block_id}")
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
    library_path = get_library_path()
    if library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    pipeline, _registry = _get_ocr_pipeline()

    # PaddleOCR 엔진: 언어 런타임 변경
    if body.paddle_lang and body.engine_id == "paddleocr":
        try:
            paddle_engine = _registry.get_engine("paddleocr")
            paddle_engine.lang = body.paddle_lang
        except Exception:
            pass

    # LLM 엔진용 추가 인자
    engine_kwargs = {}
    if body.force_provider:
        engine_kwargs["force_provider"] = body.force_provider
    if body.force_model:
        engine_kwargs["force_model"] = body.force_model

    try:
        result = pipeline.run_block(
            doc_id=doc_id,
            part_id=part_id,
            page_number=page_number,
            block_id=block_id,
            engine_id=body.engine_id,
            **engine_kwargs,
        )
        return result.to_summary()
    except Exception as e:
        return JSONResponse(
            {"error": f"OCR 블록 재실행 실패: {e}"},
            status_code=500,
        )
