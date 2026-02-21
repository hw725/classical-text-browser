"""OCR 엔진 연동 모듈.

플러그인 아키텍처로 다양한 OCR 엔진을 지원한다.

기본 엔진:
  - LLM Vision OCR: 기존 LLM 라우터의 비전 기능을 사용.
    별도 설치 없이 base44_bridge, ollama 등으로 OCR 수행.

추가 엔진 (별도 설치 필요):
  - PaddleOCR: uv add paddlepaddle paddleocr (CJK에 적합, Linux/macOS 권장)
  - Tesseract: pip install pytesseract + 시스템 설치
  - 기타: BaseOcrEngine을 상속하여 커스텀 엔진 추가 가능

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
from .llm_ocr_engine import LlmOcrEngine
from .image_utils import crop_block, preprocess_for_ocr, load_page_image, load_page_image_from_pdf

__all__ = [
    "OcrPipeline",
    "OcrEngineRegistry",
    "BaseOcrEngine",
    "LlmOcrEngine",
    "OcrBlockResult",
    "OcrLineResult",
    "OcrCharResult",
    "OcrEngineError",
    "OcrEngineUnavailableError",
    "crop_block",
    "preprocess_for_ocr",
    "load_page_image",
]
