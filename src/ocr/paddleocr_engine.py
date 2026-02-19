"""PaddleOCR 엔진 래퍼.

이 파일은 BaseOcrEngine을 구현한다.
PaddleOCR 외에도 Tesseract, Google Vision, Claude Vision 등
어떤 OCR 엔진이든 같은 패턴으로 추가할 수 있다.

설치 방법:
  uv add --optional paddleocr paddlepaddle paddleocr

주의:
  - PaddlePaddle 3.x는 Windows에서 OneDNN 관련 호환성 문제가 있을 수 있다.
  - Python 3.12 이하에서는 PaddlePaddle 2.6.x를 사용하면 안정적이다.
  - Python 3.13+에서는 PaddlePaddle 3.x만 지원되는데,
    Windows에서 fused_conv2d OneDNN 에러가 발생할 수 있다.
  - Linux/macOS에서는 문제없이 동작한다.

PaddleOCR v3 호환:
  - v2: ocr.ocr() → [[[bbox_4pts, (text, conf)], ...]]
  - v3: ocr.ocr() → result 객체 (predict 스타일)
  - 이 엔진은 두 형식을 모두 처리한다.
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

# PaddleOCR 지원 언어 코드 → 표시 이름
PADDLE_LANGUAGES = {
    "ch": "중국어 간체 (Chinese Simplified)",
    "chinese_cht": "중국어 번체 (Chinese Traditional)",
    "korean": "한국어 (Korean)",
    "japan": "일본어 (Japanese)",
    "en": "영어 (English)",
}


class PaddleOcrEngine(BaseOcrEngine):
    """PaddleOCR 엔진.

    초기화 시 PaddleOCR 모델을 lazy 로드한다 (첫 호출 시 모델 다운로드 발생).
    언어를 변경하면 모델을 다시 로드한다.

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
          lang: PaddleOCR 언어 코드 ("ch" = 중국어/한자, "chinese_cht" = 번체 등)
          use_gpu: GPU 사용 여부

        주의: 첫 호출 시 모델 자동 다운로드 (~100MB).
        """
        self._lang = lang
        self._use_gpu = use_gpu
        self._ocr = None  # lazy init
        self._ocr_lang = None  # 현재 로드된 모델의 언어
        self._available: Optional[bool] = None

    @property
    def lang(self) -> str:
        return self._lang

    @lang.setter
    def lang(self, value: str) -> None:
        """언어를 변경한다. 다음 recognize() 호출 시 모델을 다시 로드한다."""
        if value != self._lang:
            self._lang = value
            # 이미 로드된 모델과 언어가 다르면 재초기화 필요
            if self._ocr is not None and self._ocr_lang != value:
                self._ocr = None
                logger.info(f"PaddleOCR 언어 변경: {self._ocr_lang} → {value} (재초기화 예정)")

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
        """PaddleOCR 인스턴스를 lazy 초기화.

        언어가 변경되었으면 모델을 다시 로드한다.
        초기화 실패 시 한국어 에러 메시지를 제공한다.
        """
        # 언어가 변경되었으면 기존 인스턴스 해제
        if self._ocr is not None and self._ocr_lang != self._lang:
            self._ocr = None

        if self._ocr is None:
            if not self.is_available():
                raise OcrEngineUnavailableError(
                    "PaddleOCR이 설치되지 않았습니다.\n"
                    "설치: uv add --optional paddleocr paddlepaddle paddleocr\n"
                    "참고: paddlepaddle 용량 ~500MB, 첫 실행 시 OCR 모델 ~100MB 추가 다운로드"
                )

            try:
                from paddleocr import PaddleOCR as _PaddleOCR

                self._ocr = _PaddleOCR(
                    lang=self._lang,
                    use_angle_cls=True,
                    use_gpu=self._use_gpu,
                    show_log=False,
                )
                self._ocr_lang = self._lang
                logger.info(f"PaddleOCR 모델 로드 완료 (lang={self._lang}, gpu={self._use_gpu})")

            except Exception as e:
                # 모델 초기화 실패 시 구체적인 안내 제공
                err_msg = str(e)
                if "OneDNN" in err_msg or "onednn" in err_msg.lower():
                    raise OcrEngineError(
                        f"PaddleOCR 모델 초기화 실패 (OneDNN 호환성 문제).\n"
                        f"Windows + Python 3.13에서 발생할 수 있습니다.\n"
                        f"해결: Linux/macOS 환경에서 사용하거나, "
                        f"Python 3.12 이하 + PaddlePaddle 2.6.x를 사용하세요.\n"
                        f"원본 에러: {e}"
                    )
                raise OcrEngineError(
                    f"PaddleOCR 모델 초기화 실패.\n"
                    f"언어: {self._lang}, GPU: {self._use_gpu}\n"
                    f"원본 에러: {e}"
                )

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

        버그 수정:
          - RGBA/L/P 모드 이미지를 RGB로 변환 (PaddleOCR은 RGB만 지원)
          - 빈 결과·잘못된 item 구조 안전 처리
          - 세로쓰기에서는 cls=False (각도 분류기가 세로쓰기를 잘못 회전시킴)
        """
        import numpy as np
        from PIL import Image

        ocr = self._get_ocr()

        # 이미지 열기 + RGB 변환 (RGBA/L/P 등 → RGB)
        # 왜: PaddleOCR은 3채널 RGB numpy 배열만 받는다.
        #      RGBA(투명 포함), L(흑백), P(팔레트)는 에러를 발생시킨다.
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        img_array = np.array(img)

        # 세로쓰기에서는 각도 분류(cls)를 끈다.
        # 왜: use_angle_cls=True로 초기화해도, 세로쓰기 이미지에서
        #      각도 분류기가 텍스트를 180° 회전시키는 오인식이 발생한다.
        use_cls = writing_direction != "vertical_rtl"

        try:
            raw_result = ocr.ocr(img_array, cls=use_cls)
        except Exception as e:
            raise OcrEngineError(f"PaddleOCR 인식 실패: {e}")

        lines = self._parse_result(raw_result, writing_direction)

        # 세로쓰기: 오른쪽→왼쪽 정렬 (x좌표 내림차순)
        if writing_direction == "vertical_rtl" and lines:
            lines.sort(key=lambda ln: -(ln.bbox[0] if ln.bbox else 0))

        return OcrBlockResult(
            lines=lines,
            engine_id=self.engine_id,
            language=language,
            writing_direction=writing_direction,
            raw_engine_output={"paddle_result": str(raw_result)[:500]},
        )

    def _parse_result(
        self, raw_result, writing_direction: str
    ) -> list[OcrLineResult]:
        """PaddleOCR 반환 결과를 파싱한다.

        v2 형식: [[[4점bbox, (text, conf)], ...]]
        v3 형식: result 객체 (predict 스타일, 속성 접근)

        두 형식을 자동 감지하여 처리한다.
        잘못된 item 구조는 건너뛴다 (경고 로그만 남김).
        """
        lines: list[OcrLineResult] = []

        if not raw_result:
            return lines

        # v3 result 객체 감지: list가 아니면 v3 형식일 수 있음
        # v3에서는 result에 .boxes, .texts, .scores 등 속성이 있음
        if not isinstance(raw_result, list) and hasattr(raw_result, "rec_texts"):
            return self._parse_v3_result(raw_result, writing_direction)

        # v2 형식: raw_result는 이미지별 리스트 (보통 1개 이미지)
        page_result = raw_result[0] if raw_result else None
        if not page_result:
            return lines

        for idx, item in enumerate(page_result):
            try:
                # item 구조 검증: [bbox_4pts, (text, confidence)]
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    logger.warning(f"PaddleOCR item[{idx}] 구조 이상 — 건너뜀: {type(item)}")
                    continue

                bbox_points = item[0]
                text_info = item[1]

                # bbox 검증: 4개의 좌표점 [[x,y], [x,y], [x,y], [x,y]]
                if not isinstance(bbox_points, (list, tuple)) or len(bbox_points) < 4:
                    logger.warning(f"PaddleOCR item[{idx}] bbox 구조 이상 — 건너뜀")
                    continue

                # 텍스트+신뢰도 검증: (text, confidence)
                if not isinstance(text_info, (list, tuple)) or len(text_info) < 2:
                    logger.warning(f"PaddleOCR item[{idx}] text_info 구조 이상 — 건너뜀")
                    continue

                text = str(text_info[0])
                confidence = float(text_info[1])

                if not text.strip():
                    continue

                # bbox 4점 → [x_min, y_min, x_max, y_max]
                xs = [float(p[0]) for p in bbox_points]
                ys = [float(p[1]) for p in bbox_points]
                line_bbox = [min(xs), min(ys), max(xs), max(ys)]

                characters = self._split_line_to_chars(
                    text, line_bbox, confidence, writing_direction
                )

                lines.append(OcrLineResult(
                    text=text,
                    bbox=line_bbox,
                    characters=characters,
                ))

            except (TypeError, ValueError, IndexError) as e:
                logger.warning(f"PaddleOCR item[{idx}] 파싱 실패 — 건너뜀: {e}")
                continue

        return lines

    def _parse_v3_result(
        self, result, writing_direction: str
    ) -> list[OcrLineResult]:
        """PaddleOCR v3 result 객체를 파싱한다.

        v3에서는 result.rec_texts, result.rec_scores, result.dt_polys 등
        속성으로 결과에 접근한다.
        """
        lines: list[OcrLineResult] = []

        try:
            texts = getattr(result, "rec_texts", None) or []
            scores = getattr(result, "rec_scores", None) or []
            polys = getattr(result, "dt_polys", None) or []

            for idx, text in enumerate(texts):
                if not text or not str(text).strip():
                    continue

                text = str(text)
                confidence = float(scores[idx]) if idx < len(scores) else 0.0

                # dt_polys: N×2 배열 (다각형 좌표)
                if idx < len(polys) and polys[idx] is not None:
                    poly = polys[idx]
                    xs = [float(p[0]) for p in poly]
                    ys = [float(p[1]) for p in poly]
                    line_bbox = [min(xs), min(ys), max(xs), max(ys)]
                else:
                    line_bbox = [0, 0, 0, 0]

                characters = self._split_line_to_chars(
                    text, line_bbox, confidence, writing_direction
                )

                lines.append(OcrLineResult(
                    text=text,
                    bbox=line_bbox,
                    characters=characters,
                ))

        except Exception as e:
            logger.warning(f"PaddleOCR v3 결과 파싱 실패: {e}")

        return lines

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

    def get_info(self) -> dict:
        """엔진 정보를 딕셔너리로 반환. API 응답용.

        BaseOcrEngine.get_info()에 PaddleOCR 전용 정보를 추가한다:
          - lang: 현재 설정된 언어 코드
          - use_gpu: GPU 사용 여부
          - supported_languages: 지원 언어 목록
        """
        info = super().get_info()
        info["lang"] = self._lang
        info["use_gpu"] = self._use_gpu
        info["supported_languages"] = PADDLE_LANGUAGES
        return info
