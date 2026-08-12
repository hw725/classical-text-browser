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
import os
import platform
import sys
from typing import Optional

from .base import (
    BaseOcrEngine,
    OcrBlockResult,
    OcrCharResult,
    OcrEngineError,
    OcrEngineUnavailableError,
    OcrLineResult,
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

    def __init__(self, lang: str | None = None, use_gpu: bool | None = None):
        """PaddleOCR 엔진 초기화.

        입력:
          lang: PaddleOCR 언어 코드 ("ch" = 중국어/한자, "chinese_cht" = 번체 등)
                None이면 환경변수 CTB_PADDLE_LANG, 그것도 없으면 "ch".
          use_gpu: GPU 사용 여부. None이면 환경변수 CTB_PADDLE_DEVICE를 본다
                   (auto | cpu | gpu, 기본 auto).

        환경변수를 두는 이유 (2026-08-12):
          registry.auto_register()가 `PaddleOcrEngine()`을 인자 없이 만든다.
          그래서 CLI로 들어오면 언어와 장치를 **바꿀 방법이 없었다** — 국한문 혼용
          한국 논문에 중국어 간체("ch") 모델이 걸려 한글이 통째로 빠진다.
          호출부를 고치지 않고 바깥에서 지정할 수 있도록 환경변수를 연다.
          CLI에서는 `ctb ocr --paddle-lang korean --paddle-device gpu`로 쓴다.

        기본을 auto로 두는 이유:
          GPU가 없는 환경이 다수다. auto는 **설치된 paddle이 CUDA 빌드이고 실제로
          장치가 보일 때만** gpu를 고르고, 그 외에는 전부 cpu로 간다. 그래서
          GPU 없는 사람은 아무것도 지정하지 않아도 예전과 똑같이 동작한다.
          GPU가 있는데도 CPU로 재보고 싶으면 `--paddle-device cpu`로 못 박는다.

        주의: 첫 호출 시 모델 자동 다운로드 (~100MB).
        """
        if lang is None:
            lang = os.environ.get("CTB_PADDLE_LANG") or "ch"
        if use_gpu is None:
            use_gpu = self._resolve_use_gpu(os.environ.get("CTB_PADDLE_DEVICE"))
        self._lang = lang
        self._use_gpu = use_gpu
        self._ocr = None  # lazy init
        self._ocr_lang = None  # 현재 로드된 모델의 언어
        self._lang_cache: dict = {}  # 언어별 PaddleOCR 인스턴스 캐시 (동시 요청 안전)
        self._available: Optional[bool] = None
        self._unavailable_reason: Optional[str] = None

    @staticmethod
    def _resolve_use_gpu(setting: str | None) -> bool:
        """"auto" | "cpu" | "gpu" 를 실제 사용 여부로 바꾼다.

        auto는 paddle이 CUDA 빌드이고 장치가 실제로 보일 때만 True다.
        paddle import 자체가 실패해도 조용히 False로 떨어져 CPU 경로를 탄다 —
        장치 판정 때문에 엔진이 죽는 일은 없어야 한다.
        """
        value = (setting or "auto").strip().lower()
        if value in ("gpu", "cuda", "1", "true", "yes", "on"):
            return True
        if value in ("cpu", "0", "false", "no", "off"):
            return False
        try:  # auto
            import paddle

            return bool(
                paddle.device.is_compiled_with_cuda()
                and paddle.device.cuda.device_count() > 0
            )
        except Exception:
            return False

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
        """PaddleOCR 패키지 + 현재 런타임 호환성을 확인."""
        if self._available is not None:
            return self._available

        try:
            import paddle  # noqa: F401
            import paddleocr  # noqa: F401

            # Windows + Python 3.13 + PaddlePaddle 3.x 조합에서
            # OneDNN fused_conv2d 런타임 에러가 빈번히 발생한다.
            # 이 조합은 설치되어 있어도 실사용이 불안정하므로 사용 불가로 간주한다.
            paddle_version = getattr(paddle, "__version__", "")
            is_windows = platform.system() == "Windows"
            is_py313_or_newer = sys.version_info >= (3, 13)
            major_version = paddle_version.split(".")[0]
            is_paddle3_or_newer = major_version.isdigit() and int(major_version) >= 3

            if is_windows and is_py313_or_newer and is_paddle3_or_newer and not self._use_gpu:
                self._available = False
                self._unavailable_reason = (
                    "Windows + Python 3.13 + PaddlePaddle 3.x(CPU) 조합은 "
                    "OneDNN 런타임 오류로 OCR이 실패할 수 있습니다."
                )
                logger.warning(f"PaddleOCR 사용 불가 처리: {self._unavailable_reason}")
                return self._available

            self._available = True
        except ImportError:
            self._available = False
            self._unavailable_reason = "PaddleOCR 또는 PaddlePaddle 패키지가 설치되지 않았습니다."

        return self._available

    def _get_ocr(self, lang: str | None = None):
        """PaddleOCR 인스턴스를 lazy 초기화.

        입력:
          lang: 사용할 언어 코드. None이면 기본 언어(self._lang)를 사용.
                다른 언어가 지정되면 별도 인스턴스를 캐시에서 반환한다.
                공유 인스턴스(self._ocr)를 변경하지 않으므로 동시 요청 시 안전하다.

        출력: PaddleOCR 인스턴스

        초기화 실패 시 한국어 에러 메시지를 제공한다.

        왜 언어별 캐시인가:
            이전에는 요청마다 self._lang을 변경(mutation)했는데,
            동시 요청이 오면 언어가 뒤바뀌는 레이스 컨디션이 발생했다.
            언어별 인스턴스를 캐시하면 공유 상태 변경 없이 안전하게 처리된다.
            PADDLE_LANGUAGES가 5개뿐이므로 메모리 부담도 경미하다.
        """
        target_lang = lang or self._lang

        # 1. 캐시에서 조회
        cached = self._lang_cache.get(target_lang)
        if cached is not None:
            return cached

        # 2. 기존 기본 인스턴스가 같은 언어이면 캐시에 등록
        if self._ocr is not None and self._ocr_lang == target_lang:
            self._lang_cache[target_lang] = self._ocr
            return self._ocr

        # 3. 새 인스턴스 생성
        if not self.is_available():
            reason = self._unavailable_reason
            raise OcrEngineUnavailableError(
                f"PaddleOCR을 현재 환경에서 사용할 수 없습니다.\n"
                f"사유: {reason or '확인되지 않은 환경 문제'}\n"
                "설치: uv add --optional paddleocr paddlepaddle paddleocr\n"
                "참고: paddlepaddle 용량 ~500MB, 첫 실행 시 OCR 모델 ~100MB 추가 다운로드"
            )

        try:
            from paddleocr import PaddleOCR as _PaddleOCR

            # Windows + CPU 환경에서는 OneDNN(MKLDNN) 경로가 런타임 오류를 낸다.
            #
            # paddlepaddle 3.x에서는 증상이 더 분명하다 — OneDNN이 PIR 속성 변환을
            # 지원하지 않아 `ConvertPirAttribute2RuntimeAttribute not support`로
            # 추론 자체가 실패한다(실측 2026-07-25, paddlepaddle 3.3.1 + Windows).
            # 생성자 인자만으로는 늦는 경우가 있어 환경 변수로도 못 박는다.
            windows_cpu = not self._use_gpu and platform.system() == "Windows"
            if windows_cpu:
                os.environ.setdefault("FLAGS_use_mkldnn", "0")
                os.environ.setdefault("FLAGS_enable_pir_api", "0")

            # PaddleOCR 3.x는 생성자 인자가 크게 바뀌었다.
            #   2.x: use_angle_cls / use_gpu / show_log
            #   3.x: use_textline_orientation / device (앞의 것들은 제거되어 오류가 난다)
            # 어느 쪽이 설치돼 있을지 모르므로 3.x 인자를 먼저 시도하고
            # TypeError·ValueError가 나면 2.x 인자로 물러난다.
            kwargs_v3 = {
                "lang": target_lang,
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_textline_orientation": False,
            }
            # 3.x는 use_gpu 대신 device를 받는다. 이걸 넘기지 않으면 use_gpu 설정이
            # 3.x 경로에서 조용히 무시된다(2.x kwargs에만 쓰이고 있었다).
            # paddlepaddle-gpu 설치 시 paddle이 알아서 gpu를 고르기도 하지만,
            # 의도를 코드에 남기고 CPU 강제도 가능하게 명시한다.
            # 실측 2026-08-12 (RTX 3070 Ti Laptop, 200DPI): CPU 52.1초/쪽 → GPU 1.0초/쪽.
            kwargs_v3["device"] = "gpu" if self._use_gpu else "cpu"
            kwargs_v2 = {
                "lang": target_lang,
                "use_angle_cls": True,
                "use_gpu": self._use_gpu,
                "show_log": False,
            }
            if windows_cpu:
                kwargs_v3["enable_mkldnn"] = False
                kwargs_v2["enable_mkldnn"] = False

            # device를 안 받는 3.x 판본이 있을 수 있다. 그때 곧바로 2.x 인자로
            # 물러나면 3.x가 use_gpu·show_log를 거부해 생성 자체가 실패한다.
            # device만 뺀 3.x 인자를 사이에 한 단계 둔다.
            kwargs_v3_nodevice = {k: v for k, v in kwargs_v3.items() if k != "device"}

            instance = None
            last_error: Exception | None = None
            for kwargs in (kwargs_v3, kwargs_v3_nodevice, kwargs_v2):
                try:
                    instance = _PaddleOCR(**kwargs)
                    break
                except (TypeError, ValueError) as e:
                    # "Unknown argument: show_log" 처럼 버전이 안 맞는 경우다.
                    last_error = e
            if instance is None:
                raise last_error or RuntimeError("PaddleOCR 생성 실패")

            self._lang_cache[target_lang] = instance

            # 기본 언어이면 기존 필드도 갱신 (하위 호환)
            if target_lang == self._lang:
                self._ocr = instance
                self._ocr_lang = target_lang

            logger.info(f"PaddleOCR 모델 로드 완료 (lang={target_lang}, gpu={self._use_gpu})")
            return instance

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
                f"언어: {target_lang}, GPU: {self._use_gpu}\n"
                f"원본 에러: {e}"
            )

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

        kwargs:
          paddle_lang: PaddleOCR 언어 코드 오버라이드 (공유 인스턴스 mutation 없음).
                       지정하면 해당 언어의 캐시된 인스턴스를 사용한다.
        """
        import numpy as np
        from PIL import Image

        # per-request 언어 오버라이드 (공유 인스턴스를 변경하지 않음)
        paddle_lang = kwargs.pop("paddle_lang", None)
        ocr = self._get_ocr(lang=paddle_lang)

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

        # 호출 방식도 버전마다 다르다.
        #   2.x: ocr.ocr(img, cls=bool)
        #   3.x: ocr.predict(img)  — cls 인자가 없어지고, 각도 분류는 생성 시 정한다
        # 3.x에 2.x 방식으로 부르면 "unexpected keyword argument 'cls'"가 난다.
        try:
            if hasattr(ocr, "predict"):
                try:
                    raw_result = ocr.predict(img_array)
                except TypeError:
                    # predict가 있어도 시그니처가 다를 수 있어 한 번 더 물러난다.
                    raw_result = ocr.ocr(img_array, cls=use_cls)
            else:
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

    def _parse_result(self, raw_result, writing_direction: str) -> list[OcrLineResult]:
        """PaddleOCR 반환 결과를 파싱한다.

        v2 형식: [[[4점bbox, (text, conf)], ...]]
        v3 형식: result 객체 (predict 스타일, 속성 접근)

        두 형식을 자동 감지하여 처리한다.
        잘못된 item 구조는 건너뛴다 (경고 로그만 남김).
        """
        lines: list[OcrLineResult] = []

        if not raw_result:
            return lines

        # v3 result 감지.
        #
        # 예전 조건은 `not isinstance(raw_result, list)`였는데, PaddleOCR 3.x의
        # predict()는 **이미지별 결과의 리스트**를 돌려준다. 그래서 v3인데도 이
        # 조건이 거짓이 되어 v2 경로로 흘렀고, v2 파서가 dict를 순회하며 키(str)를
        # item으로 받아 «구조 이상 — 건너뜀»을 줄마다 찍고 결과가 0줄이 되었다
        # (실측 2026-08-12, paddleocr 3.7.0: 한 쪽에서 15줄 전부 유실).
        #
        # 리스트면 첫 이미지 결과를 꺼내 보고, rec_texts를 속성이든 키로든
        # 가지고 있으면 v3로 본다.
        v3_payload = self._as_v3_payload(raw_result)
        if v3_payload is not None:
            return self._parse_v3_result(v3_payload, writing_direction)

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

                lines.append(
                    OcrLineResult(
                        text=text,
                        bbox=line_bbox,
                        characters=characters,
                    )
                )

            except (TypeError, ValueError, IndexError) as e:
                logger.warning(f"PaddleOCR item[{idx}] 파싱 실패 — 건너뜀: {e}")
                continue

        return lines

    @staticmethod
    def _v3_field(payload, name):
        """v3 결과에서 필드 하나를 꺼낸다. 속성·매핑 어느 쪽이든 받는다.

        3.7.0의 결과 객체는 dict처럼 키로 접근되고, 판본에 따라 속성으로도
        열린다. 한쪽만 가정하면 조용히 빈 결과가 된다.
        """
        value = getattr(payload, name, None)
        if value is None:
            try:
                value = payload[name]
            except Exception:
                value = None
        return value if value is not None else []

    def _as_v3_payload(self, raw_result):
        """raw_result가 v3 형식이면 파싱할 알맹이를, 아니면 None을 돌려준다."""
        candidate = raw_result
        if isinstance(raw_result, list):
            if not raw_result:
                return None
            candidate = raw_result[0]
        # 일부 판본은 실제 필드를 .res 아래에 둔다.
        for obj in (candidate, getattr(candidate, "res", None)):
            if obj is None:
                continue
            if hasattr(obj, "rec_texts"):
                return obj
            try:
                if "rec_texts" in obj:
                    return obj
            except TypeError:
                pass
        return None

    def _parse_v3_result(self, result, writing_direction: str) -> list[OcrLineResult]:
        """PaddleOCR v3 result 객체를 파싱한다.

        v3에서는 result.rec_texts, result.rec_scores, result.dt_polys 등으로
        결과에 접근한다(속성 또는 키).
        """
        lines: list[OcrLineResult] = []

        try:
            texts = self._v3_field(result, "rec_texts")
            scores = self._v3_field(result, "rec_scores")
            # rec_polys가 인식된 줄과 1:1로 맞는다. dt_polys는 검출만 된 것도
            # 포함할 수 있어 인덱스가 어긋날 수 있으므로 rec_polys를 먼저 쓴다.
            polys = self._v3_field(result, "rec_polys")
            if len(polys) == 0:
                polys = self._v3_field(result, "dt_polys")

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

                lines.append(
                    OcrLineResult(
                        text=text,
                        bbox=line_bbox,
                        characters=characters,
                    )
                )

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

            chars.append(
                OcrCharResult(
                    char=ch,
                    bbox=char_bbox,
                    confidence=line_confidence,
                )
            )

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
