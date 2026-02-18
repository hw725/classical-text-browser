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
from typing import Optional

from .base import OcrBlockResult, OcrEngineError
from .registry import OcrEngineRegistry
from .image_utils import (
    load_page_image, load_page_image_from_pdf,
    crop_block, preprocess_for_ocr, get_page_image_path,
)

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
        **engine_kwargs,
    ) -> OcrPageResult:
        """페이지의 블록들을 OCR 실행한다.

        입력:
          doc_id: 문서 ID
          part_id: 파트 ID
          page_number: 페이지 번호 (1-indexed)
          engine_id: OCR 엔진 (None이면 기본 엔진)
          block_ids: OCR할 블록 ID 목록 (None이면 전체)
          **engine_kwargs: 엔진에 전달할 추가 인자 (force_provider, force_model 등)

        출력: OcrPageResult

        처리 순서:
          1. L3 layout_page.json 로드 → 블록 목록
          2. L1 이미지 로드
          3. 각 블록: 크롭 → OCR → 결과 수집
          4. 결과를 L2 JSON으로 저장
        """
        start_time = time.time()
        result = OcrPageResult(
            doc_id=doc_id, part_id=part_id, page_number=page_number
        )

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
        image_path = get_page_image_path(
            self.library_root, doc_id, part_id, page_number
        )
        if image_path is not None:
            page_image = load_page_image(image_path)
        else:
            # PDF에서 페이지 추출 시도
            page_image = load_page_image_from_pdf(
                self.library_root, doc_id, page_number
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
                    block["bbox"] = [
                        round(bbox[0] * scale_x),
                        round(bbox[1] * scale_y),
                        round(bbox[2] * scale_x),
                        round(bbox[3] * scale_y),
                    ]

        # 4. 블록별 OCR
        for block in blocks:
            block_id = block.get("block_id", "unknown")
            skip = block.get("skip", False)

            if skip:
                result.skipped_blocks += 1
                logger.debug(f"블록 건너뜀 (skip=true): {block_id}")
                continue

            try:
                ocr_dict = self._process_block(
                    engine, page_image, block, **engine_kwargs
                )
                ocr_dict["layout_block_id"] = block_id
                result.ocr_results.append(ocr_dict)
                result.processed_blocks += 1
            except OcrEngineError as e:
                error_msg = f"블록 {block_id} OCR 실패: {e}"
                result.errors.append(error_msg)
                logger.warning(error_msg)

        result.elapsed_sec = time.time() - start_time

        # 5. L2 JSON 저장
        self._save_ocr_result(doc_id, part_id, page_number, result)

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
    ) -> OcrPageResult:
        """단일 블록만 OCR 실행 (재실행용).

        기존 L2 결과에서 해당 블록만 업데이트한다.
        """
        return self.run_page(
            doc_id, part_id, page_number,
            engine_id=engine_id,
            block_ids=[block_id],
        )

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

        # 이미지 크롭
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
        self, doc_id: str, part_id: str, page_number: int,
    ) -> Optional[dict]:
        """L3 layout_page.json을 로드한다.

        실제 프로젝트 경로 규칙:
          {library_root}/documents/{doc_id}/L3_layout/{part_id}_page_{NNN}.json

        왜 이 경로인가:
          core/document.py의 _layout_file_path()와 동일한 컨벤션.
          다권본에서 part_id를 파일명에 포함해 고유하게 식별한다.
        """
        filename = f"{part_id}_page_{page_number:03d}.json"
        layout_path = (
            Path(self.library_root) / "documents" / doc_id
            / "L3_layout" / filename
        )

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
    ) -> str:
        """OCR 결과를 L2 JSON으로 저장한다.

        실제 프로젝트 경로 규칙:
          {library_root}/documents/{doc_id}/L2_ocr/{part_id}_page_{NNN}.json

        반환: 저장된 파일 경로
        """
        filename = f"{part_id}_page_{page_number:03d}.json"
        l2_dir = (
            Path(self.library_root) / "documents" / doc_id / "L2_ocr"
        )
        l2_dir.mkdir(parents=True, exist_ok=True)

        output_path = l2_dir / filename

        data = result.to_dict()

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"L2 OCR 결과 저장: {output_path}")
        return str(output_path)
