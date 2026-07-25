"""LLM 4단 폴백 + OCR 엔진 연동 라우터.

server.py의 Phase 10-2 (LLM) / Phase 10-1 (OCR) 엔드포인트를 분리한 파일.

포함 라우트:
    GET  /api/llm/status
    GET  /api/llm/models
    GET  /api/llm/usage
    POST /api/llm/analyze-layout/{doc_id}/{page}
    POST /api/llm/compare-layout/{doc_id}/{page}
    POST /api/llm/drafts/{draft_id}/review
    POST /api/ocr/detect-layout/{doc_id}/{page}
    GET  /api/ocr/engines
    POST /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr
    POST /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr/stream
    GET  /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr
    DELETE /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr
    DELETE /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr/{block_id}
    POST /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr/{block_id}
    POST /api/documents/{doc_id}/parts/{part_id}/ocr/batch
"""

import shutil
from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app._state import _get_llm_router, _get_ocr_pipeline, get_library_path, get_llm_drafts

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

    engine_id: str | None = None  # None이면 기본 엔진
    block_ids: list[str] | None = None  # None이면 전체 블록
    force_provider: str | None = None  # LLM 프로바이더 지정 (llm_vision 엔진 전용)
    force_model: str | None = None  # LLM 모델 지정 (llm_vision 엔진 전용)
    # PaddleOCR 언어 코드 (paddleocr 엔진 전용: ch, chinese_cht, korean, japan, en)
    paddle_lang: str | None = None


class OcrBatchRequest(BaseModel):
    """권(part) 단위 일괄 OCR 요청 본문."""

    engine_id: str | None = None  # None이면 기본 엔진
    pages: list[int] | None = None  # None이면 전체 쪽
    # 이미 L2 결과가 있는 쪽을 건너뛴다. 중단 후 이어서 돌리는 기본 동작이다.
    skip_existing: bool = True
    # 레이아웃이 없는 쪽에 페이지 전면 블록을 자동 생성한다.
    # 근현대 단일 컬럼 문헌용. 고서에서는 꺼야 한다.
    auto_full_page_block: bool = True
    writing_direction: str = "horizontal_ltr"
    # OCR이 끝나면 텍스트 레이어 PDF까지 만든다.
    #
    # 왜 기본값이 True인가: OCR 결과는 L2 JSON에만 들어가므로, 입히기를 따로
    # 실행하지 않으면 PDF는 여전히 스캔본이다. "OCR을 돌렸는데 왜 검색이
    # 안 되나"라는 기대 어긋남을 없앤다. 입히기는 LLM을 부르지 않고
    # 쪽당 1KB 미만이며 원본을 건드리지 않으므로 이어붙여도 안전하다.
    embed_after: bool = True
    force_provider: str | None = None
    force_model: str | None = None
    paddle_lang: str | None = None


# 학습 데이터에 한글이 없어 한글을 인식하지 못하는 엔진들.
# 근거는 각 엔진 파일의 docstring이다 (ndlocr_engine.py, ndlkotenocr_engine.py,
# ndlkotenocr_full_engine.py). 추측이 아니라 문서화된 제약이다.
HANGUL_INCAPABLE_ENGINES = ("ndlocr", "ndlkotenocr", "ndlkotenocr-full")


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
            router_inst,
            page_image,
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

    # targets 파싱: ["ollama", "gemini:gemini-2.5-flash"]
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
            router_inst,
            page_image,
            targets=parsed_targets,
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


@router.post("/api/ocr/detect-layout/{doc_id}/{page}")
async def api_detect_layout(
    doc_id: str,
    page: int,
    part_id: str = Query(..., description="파트 ID"),
    engine_id: str = Query(
        None,
        description="레이아웃 감지 엔진 ID (ndlocr 또는 ndlkotenocr). "
        "None이면 레이아웃 감지를 지원하는 첫 번째 엔진 사용.",
    ),
    conf_threshold: float = Query(0.3, description="감지 신뢰도 임계값 (0.0~1.0)"),
):
    """서버사이드 레이아웃 감지 (엔진 선택 가능).

    왜 필요한가:
        KotenLayout(브라우저 ONNX)은 5클래스(본문/삽화/인장)만 탐지한다.
        서버 엔진은 16~17클래스(본문/주석/두주/판심제/장차/도판 등)를 탐지하여
        고전적 레이아웃을 더 세밀하게 분석할 수 있다.

    지원 엔진:
        - ndlkotenocr: RTMDet 16클래스 (고전적 전용)
        - ndlocr: DEIM 17클래스 (근현대 범용)

    입력:
        doc_id: 문서 ID
        page: 페이지 번호 (1-indexed)
        part_id: 파트 ID (이미지 탐색에 사용)
        engine_id: 레이아웃 감지 엔진 ID (None이면 자동 선택)
        conf_threshold: 감지 신뢰도 임계값

    출력:
        { "blocks": [...], "image_width": int, "image_height": int,
          "analysis_method": "auto_detect", "engine": "<engine_id>" }
    """
    library_path = get_library_path()
    if library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    # 1. 레이아웃 감지 엔진 가져오기
    _pipeline, registry = _get_ocr_pipeline()

    if engine_id is not None:
        # 명시적으로 지정된 엔진 사용
        try:
            engine = registry.get_engine(engine_id)
        except Exception as e:
            return JSONResponse(
                {"error": f"'{engine_id}' 엔진을 사용할 수 없습니다: {e}"},
                status_code=400,
            )
        if not getattr(engine, "supports_layout_detection", False):
            return JSONResponse(
                {"error": f"'{engine_id}' 엔진은 레이아웃 감지를 지원하지 않습니다."},
                status_code=400,
            )
    else:
        # engine_id 미지정 → 레이아웃 감지를 지원하는 첫 번째 사용 가능 엔진 자동 선택
        engine = None
        for info in registry.list_engines():
            if info.get("supports_layout_detection") and info.get("available"):
                try:
                    engine = registry.get_engine(info["engine_id"])
                    break
                except Exception:
                    continue
        if engine is None:
            return JSONResponse(
                {"error": "레이아웃 감지를 지원하는 사용 가능한 엔진이 없습니다."},
                status_code=400,
            )

    # 2. 페이지 이미지 로드 (원본 해상도)
    import io as _io

    from ocr.image_utils import get_page_image_path, load_page_image, load_page_image_from_pdf

    image_path = get_page_image_path(str(library_path), doc_id, part_id, page)
    if image_path is not None:
        pil_image = load_page_image(image_path)
    else:
        pil_image = load_page_image_from_pdf(str(library_path), doc_id, page)

    if pil_image is None:
        return JSONResponse(
            {"error": f"페이지 이미지를 찾을 수 없습니다: {doc_id} page {page}"},
            status_code=404,
        )

    # PIL Image → PNG bytes
    buf = _io.BytesIO()
    pil_image.convert("RGB").save(buf, format="PNG")
    image_bytes = buf.getvalue()

    img_w, img_h = pil_image.size

    # 3. 레이아웃 감지
    try:
        blocks = engine.detect_layout(
            image_bytes,
            page_number=page,
            conf_threshold=conf_threshold,
        )
    except Exception as e:
        return JSONResponse(
            {"error": f"레이아웃 감지 실패: {e}"},
            status_code=500,
        )

    return {
        "blocks": blocks,
        "image_width": img_w,
        "image_height": img_h,
        "analysis_method": "auto_detect",
        "engine": engine.engine_id,
        "block_count": len(blocks),
    }


@router.get("/api/ocr/engines")
async def api_ocr_engines():
    """등록된 OCR 엔진 목록과 사용 가능 여부를 반환한다.

    목적: GUI의 OCR 실행 패널에서 엔진 드롭다운을 채우기 위해 사용한다.
    출력: {
        "engines": [
            {"engine_id": "paddleocr", "display_name": "PaddleOCR", "available": true, ...}
        ],
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

    # PaddleOCR 엔진: 요청별 언어 지정 (공유 인스턴스 mutation 없음)
    # 왜 engine_kwargs로 전달하는가:
    #   이전에는 paddle_engine.lang을 직접 변경했는데, 동시 요청 시
    #   언어가 뒤바뀌는 레이스 컨디션이 발생했다 (공유 싱글톤 mutation).
    #   engine_kwargs로 전달하면 PaddleOcrEngine.recognize()에서
    #   언어별 캐시 인스턴스를 사용하여 안전하게 처리된다.
    if body.paddle_lang and body.engine_id == "paddleocr":
        engine_kwargs["paddle_lang"] = body.paddle_lang

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
    # PaddleOCR 요청별 언어 지정 (공유 인스턴스 mutation 없음)
    if body.paddle_lang and body.engine_id == "paddleocr":
        engine_kwargs["paddle_lang"] = body.paddle_lang

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
    legacy_filename = f"page_{page_number:03d}.json"
    ocr_path = library_path / "documents" / doc_id / "L2_ocr" / filename

    # 레거시 파일명 폴백 (part_id 없는 구형 파일 호환)
    if not ocr_path.exists():
        legacy_path = library_path / "documents" / doc_id / "L2_ocr" / legacy_filename
        if legacy_path.exists():
            ocr_path = legacy_path
            filename = legacy_filename
        else:
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

    # 엔진별 추가 인자
    engine_kwargs = {}
    if body.force_provider:
        engine_kwargs["force_provider"] = body.force_provider
    if body.force_model:
        engine_kwargs["force_model"] = body.force_model
    # PaddleOCR 요청별 언어 지정 (공유 인스턴스 mutation 없음)
    if body.paddle_lang and body.engine_id == "paddleocr":
        engine_kwargs["paddle_lang"] = body.paddle_lang

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


# ===========================================================================
#  권(part) 단위 일괄 OCR
# ===========================================================================
#
# 왜 필요한가:
#   기존 OCR 라우트는 전부 페이지 단위다. 300쪽 문헌이면 사용자가
#   "페이지 선택 → 레이아웃 자동감지 → OCR 실행"을 300번 반복해야 한다.
#   근현대 논문처럼 페이지마다 판형이 같은 문헌에서는 이 반복에 의미가 없다.
#
# 왜 파이프라인을 고치지 않는가:
#   D-009의 계약(L3 → crop → 엔진 → L2, 파이프라인 경유)을 그대로 지킨다.
#   이 라우트는 쪽마다 기존 run_page()를 부르는 루프일 뿐이다.


@router.post("/api/documents/{doc_id}/parts/{part_id}/ocr/batch")
async def api_run_ocr_batch(doc_id: str, part_id: str, body: OcrBatchRequest):
    """권 전체를 쪽 단위로 이어서 OCR 하고 SSE로 진행률을 보낸다.

    목적: 페이지마다 반복하던 "레이아웃 → OCR"을 한 번의 요청으로 끝낸다.
    입력: doc_id, part_id, body(OcrBatchRequest).
    출력: text/event-stream
        - start    : {"type":"start","total":N,"engine_id":...,"warnings":[...]}
        - page     : {"type":"page","page":3,"index":2,"total":10,"status":"ok",
                      "lines":12,"block_created":true}
        - skip     : {"type":"skip","page":3,...,"reason":"이미 OCR 결과가 있습니다."}
        - complete : {"type":"complete","processed":8,"skipped":2,"failed":0,...}
        - error    : {"type":"error","error":"..."}

    중단과 재개:
        클라이언트가 연결을 끊으면 **쪽 경계에서** 멈춘다. 이미 끝난 쪽의
        결과는 L2에 남아 있으므로, 같은 요청을 다시 보내면
        skip_existing=True에 의해 남은 쪽부터 이어서 돈다.
        (별도 상태 파일이 필요 없다 — L2 자체가 체크포인트다.)
    """
    import asyncio
    import json as _json
    from pathlib import Path as _Path

    library_path = get_library_path()
    if library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = library_path / "documents" / doc_id
    if not (doc_path / "manifest.json").exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"}, status_code=404
        )

    # 대상 쪽 목록을 정한다.
    from core.document import get_document_info

    manifest = get_document_info(doc_path)
    part = next(
        (p for p in manifest.get("parts", []) if p.get("part_id") == part_id), None
    )
    if part is None:
        available = [p.get("part_id") for p in manifest.get("parts", [])]
        return JSONResponse(
            {
                "error": f"권을 찾을 수 없습니다: part_id='{part_id}'\n"
                f"→ 사용 가능한 part_id: {available}"
            },
            status_code=404,
        )

    page_count = int(part.get("page_count") or 0)
    if body.pages is None:
        targets = list(range(1, page_count + 1))
    elif page_count:
        # 쪽 수를 아는 경우에만 범위를 거른다.
        targets = [p for p in body.pages if 1 <= p <= page_count]
    else:
        targets = list(body.pages)

    if not targets:
        return JSONResponse(
            {
                "error": "OCR 할 쪽이 없습니다.\n"
                f"→ 이 권의 쪽 수는 {page_count}입니다. pages 값을 확인하세요."
            },
            status_code=400,
        )

    pipeline, registry = _get_ocr_pipeline()

    engine_kwargs = {}
    if body.force_provider:
        engine_kwargs["force_provider"] = body.force_provider
    if body.force_model:
        engine_kwargs["force_model"] = body.force_model
    if body.paddle_lang and body.engine_id == "paddleocr":
        engine_kwargs["paddle_lang"] = body.paddle_lang

    # 엔진 선택에 대한 사전 경고. 사용자가 300쪽을 다 돌린 뒤에
    # "한글이 하나도 안 나왔다"는 것을 알게 되면 안 된다.
    #
    # 기본 엔진은 "설치된 것 중 첫 번째"라(registry.py) 근현대 논문에도
    # 고전적 전용 엔진이 잡힌다. 그래서 이 경고가 특히 중요하다.
    warnings: list[str] = []
    effective_engine = body.engine_id or registry.default_engine_id
    if effective_engine in HANGUL_INCAPABLE_ENGINES:
        warnings.append(
            f"'{effective_engine}' 엔진은 한글을 인식하지 못합니다 "
            "(학습 데이터에 한글이 없습니다). "
            "→ 한글이 포함된 문헌이면 llm_vision 엔진을 사용하세요."
        )

    progress_queue: asyncio.Queue = asyncio.Queue()

    def _l2_exists(page_number: int) -> bool:
        """이 쪽에 이미 OCR 결과가 있는지 확인한다 (재개 판단)."""
        l2 = doc_path / "L2_ocr" / f"{part_id}_page_{page_number:03d}.json"
        if not l2.exists():
            return False
        try:
            data = _json.loads(_Path(l2).read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError):
            return False
        # 파일만 있고 내용이 비어 있으면 다시 돌린다.
        return bool(data.get("ocr_results"))

    async def _run_batch():
        """쪽을 하나씩 돌며 결과를 큐에 넣는다."""
        loop = asyncio.get_event_loop()
        processed = skipped = failed = 0
        total_lines = 0

        await progress_queue.put(
            {
                "type": "start",
                "total": len(targets),
                "engine_id": effective_engine,
                "warnings": warnings,
            }
        )

        try:
            for index, page_number in enumerate(targets):
                if body.skip_existing and _l2_exists(page_number):
                    skipped += 1
                    await progress_queue.put(
                        {
                            "type": "skip",
                            "page": page_number,
                            "index": index,
                            "total": len(targets),
                            "reason": "이미 OCR 결과가 있습니다.",
                        }
                    )
                    continue

                block_created = False
                try:
                    # 1) 레이아웃이 없으면 페이지 전면 블록을 만든다.
                    if body.auto_full_page_block:
                        from ocr.full_page_block import ensure_full_page_block

                        info = await loop.run_in_executor(
                            None,
                            lambda p=page_number: ensure_full_page_block(
                                doc_path,
                                part_id,
                                p,
                                writing_direction=body.writing_direction,
                            ),
                        )
                        block_created = bool(info.get("created"))

                    # 2) 기존 파이프라인으로 OCR (D-009 계약 그대로)
                    result = await loop.run_in_executor(
                        None,
                        lambda p=page_number: pipeline.run_page(
                            doc_id=doc_id,
                            part_id=part_id,
                            page_number=p,
                            engine_id=body.engine_id,
                            **engine_kwargs,
                        ),
                    )
                    summary = result.to_summary()
                    lines = sum(
                        len(r.get("lines") or [])
                        for r in (summary.get("ocr_results") or [])
                    )
                    total_lines += lines
                    processed += 1
                    await progress_queue.put(
                        {
                            "type": "page",
                            "page": page_number,
                            "index": index,
                            "total": len(targets),
                            "status": summary.get("status"),
                            "lines": lines,
                            "block_created": block_created,
                            "errors": summary.get("errors") or [],
                        }
                    )
                except Exception as e:  # noqa: BLE001 — 한 쪽 실패로 전체를 멈추지 않는다
                    failed += 1
                    await progress_queue.put(
                        {
                            "type": "page",
                            "page": page_number,
                            "index": index,
                            "total": len(targets),
                            "status": "error",
                            "lines": 0,
                            "block_created": block_created,
                            "errors": [str(e)],
                        }
                    )

            # OCR이 끝났으면 텍스트 레이어 PDF까지 만든다.
            # 실패해도 OCR 결과는 유효하므로 배치 전체를 실패로 보지 않는다.
            embed_summary = None
            if body.embed_after and (processed or skipped):
                await progress_queue.put({"type": "baking", "total": len(targets)})
                try:
                    from export.text_layer_pdf import embed_text_layer

                    embed_result = await loop.run_in_executor(
                        None, lambda: embed_text_layer(doc_path, part_id)
                    )
                    embed_summary = embed_result.to_dict()
                except Exception as e:  # noqa: BLE001
                    warnings.append(
                        f"OCR은 끝났지만 텍스트 레이어 PDF를 입히지 못했습니다: {e}\n"
                        "→ 해결: 내보내기를 따로 실행해 보세요."
                    )

            await progress_queue.put(
                {
                    "type": "complete",
                    "processed": processed,
                    "skipped": skipped,
                    "failed": failed,
                    "total": len(targets),
                    "total_lines": total_lines,
                    "engine_id": effective_engine,
                    "warnings": warnings,
                    "embedded": embed_summary,
                }
            )
        except asyncio.CancelledError:
            # 클라이언트가 끊었다. 여기까지의 결과는 L2에 남아 있으므로
            # 같은 요청을 다시 보내면 이어서 돈다.
            raise
        except Exception as e:  # noqa: BLE001
            await progress_queue.put({"type": "error", "error": str(e)})

    async def _event_generator():
        task = asyncio.create_task(_run_batch())
        try:
            while True:
                data = await progress_queue.get()
                yield f"data: {_json.dumps(data, ensure_ascii=False)}\n\n"
                if data.get("type") in ("complete", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
