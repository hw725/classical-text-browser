"""OCR 엔진 연동 모듈.

플러그인 아키텍처로 다양한 OCR 엔진을 지원한다.

기본 엔진:
  - LLM Vision OCR: 기존 LLM 라우터의 비전 기능을 사용(Ollama 기본은 gemma4:cloud, D-114).
  - PaddleOCR: 기본 의존성(CPU판). GPU판은 별도 환경 .venv-gpu(D-078).

추가 엔진 (설치 프로그램의 선택지 = pyproject extras):
  - NDLOCR-Lite·古典籍 Lite/Full·みんなで翻刻: extras japanese·classical·honkoku 등
    (onnxruntime·torch 기반, 한문·일본어 전용 — 한글은 못 읽는다)
  - 기타: BaseOcrEngine을 상속하여 커스텀 엔진 추가 가능
  어느 엔진이 왜 안 뜨는지는 doctor.bat(scripts/doctor.py)이 알려 준다.

사용법(이 저장소는 src를 경로에 넣고 «ocr»로 가져온다):
    from ocr import OcrPipeline, OcrEngineRegistry

    registry = OcrEngineRegistry()
    registry.auto_register()
    pipeline = OcrPipeline(registry, library_root="./test_library")
    result = pipeline.run_page(doc_id, part_id, page_number)
"""

from .base import (
    BaseOcrEngine,
    OcrBlockResult,
    OcrCharResult,
    OcrEngineError,
    OcrEngineUnavailableError,
    OcrLineResult,
)
from .image_utils import crop_block, load_page_image, load_page_image_from_pdf, preprocess_for_ocr
from .llm_ocr_engine import LlmOcrEngine
from .pipeline import OcrPipeline
from .registry import OcrEngineRegistry

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
    "load_page_image_from_pdf",
]
