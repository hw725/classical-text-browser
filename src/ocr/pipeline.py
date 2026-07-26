"""OCR 파이프라인.

L3 레이아웃 → 이미지 크롭 → OCR 엔진 → L2 결과 저장.
모든 OCR 실행은 이 파이프라인을 통해야 한다.

사용법:
    from src.ocr import OcrPipeline, OcrEngineRegistry

    registry = OcrEngineRegistry()
    registry.auto_register()

    pipeline = OcrPipeline(registry, library_root="/path/to/library")
    result = pipeline.run_page(doc_id="doc001", part_id="vol1", page_number=1)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .base import OcrBlockResult, OcrEngineError
from .image_utils import (
    crop_block,
    get_page_image_path,
    load_page_image,
    load_page_image_from_pdf,
    preprocess_for_ocr,
    resolve_part_pdf,
)
from .registry import OcrEngineRegistry

logger = logging.getLogger(__name__)


@dataclass
class OcrPageResult:
    """한 페이지의 OCR 결과.

    파이프라인의 최종 출력.
    ocr_page.schema.json 형식으로 저장된다.
    """

    doc_id: str
    part_id: str
    page_number: int
    ocr_results: list[dict] = field(default_factory=list)
    engine_id: str = ""
    total_blocks: int = 0
    processed_blocks: int = 0
    skipped_blocks: int = 0
    elapsed_sec: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """ocr_page.schema.json 호환 딕셔너리.

        스키마 필수 필드: part_id, page_number, ocr_results
        스키마 옵션 필드: ocr_engine, ocr_config
        """
        return {
            "part_id": self.part_id,
            "page_number": self.page_number,
            "ocr_engine": self.engine_id or None,
            "ocr_config": None,
            "ocr_results": self.ocr_results,
        }

    def to_summary(self) -> dict:
        """API 응답용 요약 (스키마 외 메타데이터 포함)."""
        return {
            "status": "completed" if not self.errors else "partial",
            "engine": self.engine_id,
            "total_blocks": self.total_blocks,
            "processed_blocks": self.processed_blocks,
            "skipped_blocks": self.skipped_blocks,
            "elapsed_sec": round(self.elapsed_sec, 2),
            "ocr_results": self.ocr_results,
            "errors": self.errors,
        }


class OcrPipeline:
    """OCR 파이프라인.

    주요 메서드:
      run_page(): 페이지의 모든 블록을 OCR
      run_block(): 단일 블록만 OCR (재실행용)
    """

    def __init__(
        self,
        registry: OcrEngineRegistry,
        library_root: str,
    ):
        """파이프라인 초기화.

        입력:
          registry: OCR 엔진 레지스트리 (auto_register() 호출 완료 상태)
          library_root: 서고 루트 경로
        """
        self.registry = registry
        self.library_root = library_root

    def run_page(
        self,
        doc_id: str,
        part_id: str,
        page_number: int,
        engine_id: Optional[str] = None,
        block_ids: Optional[list[str]] = None,
        progress_callback: Optional[Callable[[dict], None]] = None,
        **engine_kwargs,
    ) -> OcrPageResult:
        """페이지의 블록들을 OCR 실행한다.

        입력:
          doc_id: 문서 ID
          part_id: 파트 ID
          page_number: 페이지 번호 (1-indexed)
          engine_id: OCR 엔진 (None이면 기본 엔진)
          block_ids: OCR할 블록 ID 목록 (None이면 전체)
          progress_callback: 블록 처리 진행 시 호출되는 콜백 (SSE 스트리밍용).
              호출 형식:
              callback({"current": 2, "total": 5, "block_id": "p01_b02", ...})
          **engine_kwargs: 엔진에 전달할 추가 인자 (force_provider, force_model 등)

        출력: OcrPageResult

        처리 순서:
          1. L3 layout_page.json 로드 → 블록 목록
          2. L1 이미지 로드
          3. 각 블록: 크롭 → OCR → 결과 수집
          4. 결과를 L2 JSON으로 저장
        """
        start_time = time.time()
        result = OcrPageResult(doc_id=doc_id, part_id=part_id, page_number=page_number)

        # 1. 엔진 확인
        engine = self.registry.get_engine(engine_id)
        result.engine_id = engine.engine_id

        # 2. L3 레이아웃 로드
        layout = self._load_layout(doc_id, part_id, page_number)
        if layout is None:
            result.errors.append(f"L3 레이아웃을 찾을 수 없습니다: page {page_number}")
            return result

        blocks = layout.get("blocks", [])
        result.total_blocks = len(blocks)

        # block_ids 필터링
        if block_ids is not None:
            blocks = [b for b in blocks if b.get("block_id") in block_ids]

        # reading_order로 정렬
        blocks.sort(key=lambda b: b.get("reading_order", 999))

        # 3. 이미지 로드
        # 우선 개별 이미지 파일을 탐색하고, 없으면 PDF에서 추출한다.
        image_path = get_page_image_path(self.library_root, doc_id, part_id, page_number)
        if image_path is not None:
            page_image = load_page_image(image_path)
        else:
            # PDF에서 페이지 추출 시도
            # part_id를 반드시 넘긴다 — 없으면 다권본에서 첫 권을 읽는다.
            page_image = load_page_image_from_pdf(
                self.library_root, doc_id, page_number, part_id=part_id
            )
            if page_image is None:
                result.errors.append(
                    f"L1 이미지를 찾을 수 없습니다: page {page_number} "
                    f"(L1_source에 이미지 파일도 PDF도 없음)"
                )
                return result

        # 4-a. 좌표계 보정: L3 레이아웃의 image_width/height와 실제 이미지 크기가
        #       다를 수 있다. (예: GUI에서 PDF.js 1x 뷰포트 기준으로 저장했는데,
        #       OCR 파이프라인은 PyMuPDF 2x 스케일로 로드하는 경우)
        #       이 경우 bbox 좌표를 실제 이미지 크기에 맞게 스케일링한다.
        layout_w = layout.get("image_width", 0)
        layout_h = layout.get("image_height", 0)
        actual_w, actual_h = page_image.size

        # 방어 로직: image_width가 0이거나 누락된 경우,
        # PDF의 1x 뷰포트 크기로 추정한다.
        # 왜 필요한가: 프론트엔드는 PDF.js viewport(scale=1.0) 기준으로
        #   bbox를 저장하므로, image_width가 누락되면 스케일링이 건너뛰어져
        #   1x 좌표로 2x 이미지를 crop하게 되어 엉뚱한 영역이 잘린다.
        if (layout_w <= 0 or layout_h <= 0) and actual_w > 0:
            # PDF에서 1x 뷰포트 크기를 얻어 layout 크기로 사용
            pdf_vp_size = self._get_pdf_viewport_size(doc_id, page_number, part_id)
            if pdf_vp_size:
                layout_w, layout_h = pdf_vp_size
                logger.warning(
                    f"L3에 image_width 누락 — PDF 뷰포트로 추정: "
                    f"{layout_w}×{layout_h} (실제 이미지: {actual_w}×{actual_h})"
                )
            else:
                # PDF도 없으면 bbox 범위에서 추정 (최후 수단)
                max_x = max((b.get("bbox", [0, 0, 0, 0])[2] for b in blocks), default=0)
                max_y = max((b.get("bbox", [0, 0, 0, 0])[3] for b in blocks), default=0)
                if (max_x > 0 and max_x < actual_w * 0.8) or (max_y > 0 and max_y < actual_h * 0.8):
                    # bbox 최대값이 실제 이미지 크기의 80% 미만이면
                    # 스케일 불일치가 확실하므로 비율을 추정
                    # 가장 흔한 케이스: PDF 2x (viewport = actual / 2)
                    layout_w = actual_w // 2
                    layout_h = actual_h // 2
                    logger.warning(
                        f"L3에 image_width 누락, PDF 뷰포트도 없음 — "
                        f"bbox 범위에서 추정: {layout_w}×{layout_h}"
                    )

        if layout_w > 0 and layout_h > 0 and (layout_w != actual_w or layout_h != actual_h):
            scale_x = actual_w / layout_w
            scale_y = actual_h / layout_h
            logger.info(
                f"bbox 좌표 스케일링: L3 ({layout_w}×{layout_h}) → "
                f"실제 ({actual_w}×{actual_h}), scale=({scale_x:.2f}, {scale_y:.2f})"
            )
            for block in blocks:
                bbox = block.get("bbox")
                if bbox and len(bbox) == 4:
                    old_bbox = list(bbox)
                    block["bbox"] = [
                        round(bbox[0] * scale_x),
                        round(bbox[1] * scale_y),
                        round(bbox[2] * scale_x),
                        round(bbox[3] * scale_y),
                    ]
                    logger.debug(
                        f"  블록 {block.get('block_id', '?')}: {old_bbox} → {block['bbox']}"
                    )
        elif layout_w > 0 and layout_w == actual_w:
            logger.debug(f"bbox 스케일링 불필요: L3 = 실제 = {actual_w}×{actual_h}")

        # ── 페이지 단위 OCR 분기 (ndlocr 등) ────────────────────
        # supports_page_level=True인 엔진은 페이지 전체를 한 번에 처리한다.
        # 조건:
        #   - 엔진이 페이지 단위를 지원
        #   - 전체 블록 처리 (block_ids가 None)
        #   - 블록이 페이지의 70% 이상을 덮을 때만 사용
        #
        # 왜 커버리지 조건이 필요한가:
        #   페이지 단위 OCR은 전체 페이지에서 라인을 탐지한 뒤 블록에 매칭한다.
        #   블록이 페이지 일부만 덮으면 블록 밖의 텍스트가 가장 가까운 블록에
        #   할당되어, 사용자가 선택하지 않은 영역의 글자가 결과에 섞인다.
        #   블록 커버리지가 낮으면 블록별 crop 경로를 사용하여
        #   각 블록 영역만 정확하게 잘라서 OCR한다.
        use_page_level = (
            getattr(engine, "supports_page_level", False)
            and block_ids is None
            and self._blocks_cover_page(blocks, actual_w, actual_h, threshold=0.7)
        )
        if use_page_level:
            try:
                page_bytes = self._page_image_to_bytes(page_image)
                page_results = engine.recognize_page(
                    page_bytes,
                    blocks,
                    progress_callback=progress_callback,
                    **engine_kwargs,
                )
                result.ocr_results = page_results
                result.processed_blocks = len(page_results)
                result.elapsed_sec = time.time() - start_time

                self._save_ocr_result(
                    doc_id,
                    part_id,
                    page_number,
                    result,
                    merge_with_existing=False,
                )

                logger.info(
                    f"OCR 완료 (페이지 단위): {doc_id}/{part_id}/page_{page_number:03d} — "
                    f"{result.processed_blocks} 블록, {result.elapsed_sec:.1f}초"
                )
                return result
            except NotImplementedError:
                # recognize_page() 미구현 → 아래 블록별 경로로 폴백
                logger.info(f"{engine.engine_id}: 페이지 단위 미지원, 블록별로 전환")
            except Exception as e:
                # 페이지 단위 실패 → 블록별 경로로 폴백 (기존 기능 보호)
                logger.warning(f"페이지 단위 OCR 실패, 블록별로 전환: {e}")
        # ── 페이지 단위 분기 끝 ────────────────────────────────

        # 4. 블록별 OCR (기존 경로 — 수정하지 않음)
        # processable_blocks: skip이 아닌 실제 처리 대상 블록 수
        processable_blocks = [b for b in blocks if not b.get("skip", False)]
        total_processable = len(processable_blocks)

        for proc_idx, block in enumerate(blocks):
            block_id = block.get("block_id", "unknown")
            skip = block.get("skip", False)

            if skip:
                result.skipped_blocks += 1
                logger.debug(f"블록 건너뜀 (skip=true): {block_id}")
                continue

            # 진행률 콜백: 처리 시작 알림
            current_num = result.processed_blocks + len(result.errors) + 1
            if progress_callback:
                progress_callback(
                    {
                        "current": current_num,
                        "total": total_processable,
                        "block_id": block_id,
                        "status": "processing",
                    }
                )

            try:
                ocr_dict = self._process_block(engine, page_image, block, **engine_kwargs)
                ocr_dict["layout_block_id"] = block_id
                result.ocr_results.append(ocr_dict)
                result.processed_blocks += 1
            except OcrEngineError as e:
                error_msg = f"블록 {block_id} OCR 실패: {e}"
                result.errors.append(error_msg)
                logger.warning(error_msg)

        result.elapsed_sec = time.time() - start_time

        # 5. L2 JSON 저장
        self._save_ocr_result(
            doc_id,
            part_id,
            page_number,
            result,
            merge_with_existing=(block_ids is not None),
        )

        logger.info(
            f"OCR 완료: {doc_id}/{part_id}/page_{page_number:03d} — "
            f"{result.processed_blocks}/{result.total_blocks} 블록, "
            f"{result.elapsed_sec:.1f}초"
        )

        return result

    def run_block(
        self,
        doc_id: str,
        part_id: str,
        page_number: int,
        block_id: str,
        engine_id: Optional[str] = None,
        **engine_kwargs,
    ) -> OcrPageResult:
        """단일 블록만 OCR 실행 (재실행용).

        기존 L2 결과에서 해당 블록만 업데이트한다.
        engine_kwargs는 run_page()를 통해 엔진의 recognize()에 전달된다.
        """
        return self.run_page(
            doc_id,
            part_id,
            page_number,
            engine_id=engine_id,
            block_ids=[block_id],
            **engine_kwargs,
        )

    def _get_pdf_viewport_size(
        self,
        doc_id: str,
        page_number: int,
        part_id: Optional[str] = None,
    ) -> Optional[tuple[int, int]]:
        """PDF의 1x 뷰포트 크기를 반환한다.

        왜 필요한가:
            프론트엔드는 PDF.js viewport(scale=1.0) 기준으로 bbox를 저장한다.
            L3에 image_width가 누락된 경우, PDF의 1x 뷰포트 크기를 알면
            올바른 스케일 비율을 계산할 수 있다.
            PyMuPDF의 page.rect가 PDF.js viewport(scale=1.0)과 동일한 크기다.
            (PDF.js의 userUnit=1, PyMuPDF의 기본 단위 = 72 DPI = 1x)

        왜 part_id가 필요한가: 권마다 종이 크기가 다를 수 있다. 엉뚱한 권의
        크기로 배율을 잡으면 crop 영역이 통째로 어긋난다.

        반환: (width, height) 정수 튜플, PDF가 없으면 None
        """
        doc_path = Path(self.library_root) / "documents" / doc_id
        pdf_path = resolve_part_pdf(doc_path, part_id)
        if pdf_path is None or not pdf_path.exists():
            return None

        try:
            import fitz
        except ImportError:
            return None

        # with를 쓰는 이유: 예외 경로에서도 파일 핸들이 닫힌다(Windows 잠금 방지).
        try:
            with fitz.open(str(pdf_path)) as doc:
                page_idx = page_number - 1
                if page_idx < 0 or page_idx >= len(doc):
                    return None
                rect = doc[page_idx].rect
                return (round(rect.width), round(rect.height))
        except Exception:
            return None

    @staticmethod
    def _blocks_cover_page(
        blocks: list[dict],
        page_w: int,
        page_h: int,
        threshold: float = 0.7,
    ) -> bool:
        """블록들이 페이지의 일정 비율 이상을 덮는지 확인한다.

        왜 필요한가:
            페이지 단위 OCR(recognize_page)은 전체 페이지를 스캔하므로,
            블록이 일부만 덮으면 블록 밖 텍스트가 결과에 섞인다.
            커버리지가 threshold 미만이면 블록별 crop 경로가 더 정확하다.

        입력:
            blocks: L3 블록 목록 (bbox 포함)
            page_w, page_h: 페이지 이미지 크기 (실제 픽셀)
            threshold: 최소 커버리지 비율 (0.0~1.0)
        출력:
            True면 페이지 단위 OCR 사용 가능, False면 블록별 crop 사용
        """
        if page_w <= 0 or page_h <= 0:
            return False

        page_area = page_w * page_h
        block_area = 0
        for b in blocks:
            bbox = b.get("bbox")
            if not bbox or len(bbox) != 4 or b.get("skip", False):
                continue
            w = abs(bbox[2] - bbox[0])
            h = abs(bbox[3] - bbox[1])
            block_area += w * h

        coverage = block_area / page_area
        if coverage < threshold:
            logger.info(
                f"블록 커버리지 {coverage:.1%} < {threshold:.0%} → "
                f"페이지 단위 대신 블록별 crop OCR 사용"
            )
        return coverage >= threshold

    def _process_block(
        self,
        engine,
        page_image,
        block: dict,
        **engine_kwargs,
    ) -> dict:
        """단일 블록을 OCR 처리한다.

        입력: 엔진, 페이지 이미지, 블록 정보(L3)
        출력: OCR 결과 딕셔너리 (ocr_page.schema.json 형식)

        engine_kwargs는 엔진의 recognize()에 그대로 전달된다.
        LlmOcrEngine의 경우 force_provider, force_model 등을 받을 수 있다.
        """
        bbox = block.get("bbox")
        if not bbox or len(bbox) != 4:
            raise OcrEngineError(f"유효하지 않은 bbox: {bbox}")

        # 이미지 크롭 (디버그: 이미지 크기 대비 bbox 비율 확인)
        img_w, img_h = page_image.size
        logger.debug(
            f"crop 블록 {block.get('block_id', '?')}: "
            f"bbox={bbox}, image={img_w}×{img_h}, "
            f"비율=({bbox[2] / img_w:.2%}, {bbox[3] / img_h:.2%})"
        )
        cropped = crop_block(page_image, bbox)

        # 전처리
        writing_direction = block.get("writing_direction", "vertical_rtl")
        language = block.get("language", "classical_chinese")
        processed = preprocess_for_ocr(cropped, writing_direction=writing_direction)

        # OCR 실행
        ocr_result: OcrBlockResult = engine.recognize(
            processed,
            writing_direction=writing_direction,
            language=language,
            **engine_kwargs,
        )

        return ocr_result.to_dict()

    def _load_layout(
        self,
        doc_id: str,
        part_id: str,
        page_number: int,
    ) -> Optional[dict]:
        """L3 layout_page.json을 로드한다.

        실제 프로젝트 경로 규칙:
          {library_root}/documents/{doc_id}/L3_layout/{part_id}_page_{NNN}.json

        왜 이 경로인가:
          core/document.py의 _layout_file_path()와 동일한 컨벤션.
          다권본에서 part_id를 파일명에 포함해 고유하게 식별한다.
        """
        filename = f"{part_id}_page_{page_number:03d}.json"
        layout_path = Path(self.library_root) / "documents" / doc_id / "L3_layout" / filename

        if not layout_path.exists():
            return None

        with open(layout_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_ocr_result(
        self,
        doc_id: str,
        part_id: str,
        page_number: int,
        result: OcrPageResult,
        merge_with_existing: bool = False,
    ) -> str:
        """OCR 결과를 L2 JSON으로 저장한다.

        실제 프로젝트 경로 규칙:
          {library_root}/documents/{doc_id}/L2_ocr/{part_id}_page_{NNN}.json

        반환: 저장된 파일 경로
        """
        filename = f"{part_id}_page_{page_number:03d}.json"
        l2_dir = Path(self.library_root) / "documents" / doc_id / "L2_ocr"
        l2_dir.mkdir(parents=True, exist_ok=True)

        output_path = l2_dir / filename

        data = result.to_dict()

        if merge_with_existing and output_path.exists():
            with open(output_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)

            existing_results = existing_data.get("ocr_results", [])
            incoming_results = data.get("ocr_results", [])

            incoming_by_id = {
                item.get("layout_block_id"): item
                for item in incoming_results
                if item.get("layout_block_id")
            }

            merged_results = []
            for old_item in existing_results:
                block_id = old_item.get("layout_block_id")
                if block_id in incoming_by_id:
                    merged_results.append(incoming_by_id.pop(block_id))
                else:
                    merged_results.append(old_item)

            merged_ids = {
                m.get("layout_block_id") for m in merged_results if m.get("layout_block_id")
            }
            for new_item in incoming_results:
                block_id = new_item.get("layout_block_id")
                if block_id and block_id not in merged_ids:
                    merged_results.append(new_item)
                    merged_ids.add(block_id)

            data["ocr_results"] = merged_results

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"L2 OCR 결과 저장: {output_path}")
        return str(output_path)

    @staticmethod
    def _page_image_to_bytes(page_image) -> bytes:
        """PIL Image → PNG bytes 변환 (페이지 단위 OCR 엔진에 전달용).

        왜 별도 메서드인가:
          recognize_page()는 bytes를 입력으로 받는다 (PIL Image 직접 의존 방지).
          파이프라인 내부에서만 사용하는 변환 헬퍼.
        """
        import io as _io

        buf = _io.BytesIO()
        page_image.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()
