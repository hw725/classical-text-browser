"""PaddleOCR 엔진 래퍼.

오프라인 퍼스트 원칙에 따른 기본(1순위) OCR 엔진.
PP-OCRv4 모델 사용 — 중국어 고전 텍스트에 적합.

특징:
  - 로컬 실행, 무료
  - 세로쓰기 지원 (PP-OCR 자체 방향 감지)
  - 줄 단위 + 글자 단위 bbox 제공 (글자 단위는 줄 bbox 균등 분할)
  - 신뢰도(confidence) 제공
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

        주의: 초기화가 느릴 수 있다 (모델 로드).
             첫 호출 시 모델 자동 다운로드 (~100MB).
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
            logger.info("PaddleOCR 미설치 — uv add paddlepaddle paddleocr")

        return self._available

    def _get_ocr(self):
        """PaddleOCR 인스턴스를 lazy 초기화."""
        if self._ocr is None:
            if not self.is_available():
                raise OcrEngineUnavailableError("PaddleOCR이 설치되지 않았습니다.")

            from paddleocr import PaddleOCR as _PaddleOCR

            self._ocr = _PaddleOCR(
                lang=self._lang,
                use_angle_cls=True,   # 방향 감지 (세로쓰기 지원)
                use_gpu=self._use_gpu,
                show_log=False,       # 로그 최소화
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

        PaddleOCR 출력 형식:
          result = ocr.ocr(image)
          result[0] = [
            [bbox_points, (text, confidence)],
            ...
          ]
          bbox_points = [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]  (4꼭짓점)

        변환:
          4꼭짓점 → [x_min, y_min, x_max, y_max]
          (text, confidence) → OcrLineResult
        """
        import numpy as np
        from PIL import Image

        ocr = self._get_ocr()

        # bytes → numpy array (PaddleOCR 입력 형식)
        img = Image.open(io.BytesIO(image_bytes))
        img_array = np.array(img)

        try:
            raw_result = ocr.ocr(img_array, cls=True)
        except Exception as e:
            raise OcrEngineError(f"PaddleOCR 인식 실패: {e}")

        # PaddleOCR 결과 파싱
        lines = []

        if raw_result and raw_result[0]:
            for item in raw_result[0]:
                bbox_points = item[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                text = item[1][0]
                confidence = float(item[1][1])

                # 4꼭짓점 → [x_min, y_min, x_max, y_max]
                xs = [p[0] for p in bbox_points]
                ys = [p[1] for p in bbox_points]
                line_bbox = [min(xs), min(ys), max(xs), max(ys)]

                # 글자 단위 결과 생성 (PaddleOCR 기본은 줄 단위)
                # 글자 단위 bbox가 없으므로 줄 bbox를 균등 분할
                characters = self._split_line_to_chars(
                    text, line_bbox, confidence, writing_direction
                )

                lines.append(OcrLineResult(
                    text=text,
                    bbox=line_bbox,
                    characters=characters,
                ))

        # 세로쓰기일 때: 줄을 오른쪽→왼쪽 순서로 정렬
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

        PaddleOCR은 기본적으로 줄 단위 결과만 제공.
        글자 단위 bbox는 줄 bbox를 균등 분할하여 추정.

        세로쓰기: y축 방향으로 균등 분할
        가로쓰기: x축 방향으로 균등 분할
        """
        if not text:
            return []

        x_min, y_min, x_max, y_max = line_bbox
        n = len(text)
        chars = []

        for i, ch in enumerate(text):
            if writing_direction == "vertical_rtl":
                # 세로쓰기: y축 분할
                ch_y_min = y_min + (y_max - y_min) * i / n
                ch_y_max = y_min + (y_max - y_min) * (i + 1) / n
                char_bbox = [x_min, ch_y_min, x_max, ch_y_max]
            else:
                # 가로쓰기: x축 분할
                ch_x_min = x_min + (x_max - x_min) * i / n
                ch_x_max = x_min + (x_max - x_min) * (i + 1) / n
                char_bbox = [ch_x_min, y_min, ch_x_max, y_max]

            chars.append(OcrCharResult(
                char=ch,
                bbox=char_bbox,
                confidence=line_confidence,  # 줄 confidence를 글자에도 동일 적용
            ))

        return chars
