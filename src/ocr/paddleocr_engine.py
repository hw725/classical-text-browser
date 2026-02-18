"""PaddleOCR 엔진 래퍼 (예시 구현).

이 파일은 BaseOcrEngine을 구현하는 예시다.
PaddleOCR 외에도 Tesseract, Google Vision, Claude Vision 등
어떤 OCR 엔진이든 같은 패턴으로 추가할 수 있다.

설치 방법:
  uv add paddlepaddle paddleocr

주의:
  - PaddlePaddle 3.x는 Windows에서 OneDNN 관련 호환성 문제가 있을 수 있다.
  - Python 3.12 이하에서는 PaddlePaddle 2.6.x를 사용하면 안정적이다.
  - Python 3.13+에서는 PaddlePaddle 3.x만 지원되는데,
    Windows에서 fused_conv2d OneDNN 에러가 발생할 수 있다.
  - Linux/macOS에서는 문제없이 동작한다.

커스텀 엔진을 만들려면:
  1. BaseOcrEngine을 상속하는 클래스를 만든다.
  2. engine_id, display_name, requires_network 클래스 속성을 정의한다.
  3. is_available()과 recognize()를 구현한다.
  4. registry.py의 auto_register()에 등록 코드를 추가한다.

예시: Tesseract OCR 엔진 추가
  class TesseractEngine(BaseOcrEngine):
      engine_id = "tesseract"
      display_name = "Tesseract OCR"
      requires_network = False

      def is_available(self) -> bool:
          try:
              import pytesseract
              return True
          except ImportError:
              return False

      def recognize(self, image_bytes, ...) -> OcrBlockResult:
          import pytesseract
          from PIL import Image
          img = Image.open(io.BytesIO(image_bytes))
          data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
          # ... data를 OcrBlockResult로 변환 ...
"""

from __future__ import annotations
import io
import logging
from typing import Optional

from .base import (
    BaseOcrEngine, OcrBlockResult, OcrLineResult, OcrCharResult,
    OcrEngineError, OcrEngineUnavailableError,
)

logger = logging.getLogger(__name__)


class PaddleOcrEngine(BaseOcrEngine):
    """PaddleOCR 엔진.

    초기화 시 PaddleOCR 모델을 lazy 로드한다 (첫 호출 시 모델 다운로드 발생).

    사용법:
        engine = PaddleOcrEngine()
        if engine.is_available():
            result = engine.recognize(image_bytes, writing_direction="vertical_rtl")
    """

    engine_id = "paddleocr"
    display_name = "PaddleOCR (오프라인)"
    requires_network = False

    def __init__(self, lang: str = "ch", use_gpu: bool = False):
        """PaddleOCR 엔진 초기화.

        입력:
          lang: PaddleOCR 언어 코드 ("ch" = 중국어/한자)
          use_gpu: GPU 사용 여부

        주의: 첫 호출 시 모델 자동 다운로드 (~100MB).
        """
        self._lang = lang
        self._use_gpu = use_gpu
        self._ocr = None  # lazy init
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """PaddleOCR 패키지가 설치되어 있는지 확인."""
        if self._available is not None:
            return self._available

        try:
            import paddleocr  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False

        return self._available

    def _get_ocr(self):
        """PaddleOCR 인스턴스를 lazy 초기화."""
        if self._ocr is None:
            if not self.is_available():
                raise OcrEngineUnavailableError(
                    "PaddleOCR이 설치되지 않았습니다.\n"
                    "설치: uv add paddlepaddle paddleocr"
                )

            from paddleocr import PaddleOCR as _PaddleOCR

            self._ocr = _PaddleOCR(
                lang=self._lang,
                use_angle_cls=True,
                use_gpu=self._use_gpu,
                show_log=False,
            )
            logger.info("PaddleOCR 모델 로드 완료")

        return self._ocr

    def recognize(
        self,
        image_bytes: bytes,
        writing_direction: str = "vertical_rtl",
        language: str = "classical_chinese",
        **kwargs,
    ) -> OcrBlockResult:
        """PaddleOCR로 텍스트를 인식한다.

        입력: 크롭된 블록 이미지 (PNG/JPEG 바이트)
        출력: OcrBlockResult
        """
        import numpy as np
        from PIL import Image

        ocr = self._get_ocr()

        img = Image.open(io.BytesIO(image_bytes))
        img_array = np.array(img)

        try:
            raw_result = ocr.ocr(img_array, cls=True)
        except Exception as e:
            raise OcrEngineError(f"PaddleOCR 인식 실패: {e}")

        lines = []
        if raw_result and raw_result[0]:
            for item in raw_result[0]:
                bbox_points = item[0]
                text = item[1][0]
                confidence = float(item[1][1])

                xs = [p[0] for p in bbox_points]
                ys = [p[1] for p in bbox_points]
                line_bbox = [min(xs), min(ys), max(xs), max(ys)]

                characters = self._split_line_to_chars(
                    text, line_bbox, confidence, writing_direction
                )

                lines.append(OcrLineResult(
                    text=text,
                    bbox=line_bbox,
                    characters=characters,
                ))

        if writing_direction == "vertical_rtl" and lines:
            lines.sort(key=lambda ln: -(ln.bbox[0] if ln.bbox else 0))

        return OcrBlockResult(
            lines=lines,
            engine_id=self.engine_id,
            language=language,
            writing_direction=writing_direction,
            raw_engine_output={"paddle_result": str(raw_result)[:500]},
        )

    def _split_line_to_chars(
        self,
        text: str,
        line_bbox: list[float],
        line_confidence: float,
        writing_direction: str,
    ) -> list[OcrCharResult]:
        """줄의 텍스트를 글자별로 분할하고 bbox를 추정한다.

        PaddleOCR은 줄 단위 결과만 제공.
        글자 단위 bbox는 줄 bbox를 균등 분할하여 추정.
        """
        if not text:
            return []

        x_min, y_min, x_max, y_max = line_bbox
        n = len(text)
        chars = []

        for i, ch in enumerate(text):
            if writing_direction == "vertical_rtl":
                ch_y_min = y_min + (y_max - y_min) * i / n
                ch_y_max = y_min + (y_max - y_min) * (i + 1) / n
                char_bbox = [x_min, ch_y_min, x_max, ch_y_max]
            else:
                ch_x_min = x_min + (x_max - x_min) * i / n
                ch_x_max = x_min + (x_max - x_min) * (i + 1) / n
                char_bbox = [ch_x_min, y_min, ch_x_max, y_max]

            chars.append(OcrCharResult(
                char=ch,
                bbox=char_bbox,
                confidence=line_confidence,
            ))

        return chars
