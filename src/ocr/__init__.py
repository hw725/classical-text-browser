"""OCR 엔진 연동 모듈.

플러그인 아키텍처로 다양한 OCR 엔진을 지원한다.
기본 엔진: PaddleOCR (오프라인).

사용법:
    from src.ocr import OcrPipeline, OcrEngineRegistry

    registry = OcrEngineRegistry()
    registry.auto_register()
    pipeline = OcrPipeline(registry, library_root="./test_library")
    result = pipeline.run_page(doc_id, part_id, page_number)
"""

from .pipeline import OcrPipeline
from .registry import OcrEngineRegistry
from .base import BaseOcrEngine, OcrBlockResult, OcrLineResult, OcrCharResult
from .base import OcrEngineError, OcrEngineUnavailableError
from .image_utils import crop_block, preprocess_for_ocr, load_page_image, load_page_image_from_pdf

__all__ = [
    "OcrPipeline",
    "OcrEngineRegistry",
    "BaseOcrEngine",
    "OcrBlockResult",
    "OcrLineResult",
    "OcrCharResult",
    "OcrEngineError",
    "OcrEngineUnavailableError",
    "crop_block",
    "preprocess_for_ocr",
    "load_page_image",
]
