"""OCR 엔진 레지스트리.

사용 가능한 OCR 엔진을 등록하고 조회한다.
파서의 ParserRegistry와 동일한 패턴.

엔진은 코드에 하드코딩하지 않고 register()로 등록한다.
앱 초기화 시 사용 가능한 엔진을 자동 등록.
"""

from __future__ import annotations
import logging
from typing import Optional

from .base import BaseOcrEngine, OcrEngineUnavailableError

logger = logging.getLogger(__name__)


class OcrEngineRegistry:
    """OCR 엔진 레지스트리.

    사용법:
        registry = OcrEngineRegistry()
        registry.auto_register()  # 사용 가능한 엔진 자동 등록
        engine = registry.get_engine("paddleocr")
    """

    def __init__(self):
        self._engines: dict[str, BaseOcrEngine] = {}
        self._default_engine_id: Optional[str] = None

    def register(self, engine: BaseOcrEngine) -> None:
        """엔진을 등록한다.

        이미 같은 engine_id가 등록되어 있으면 덮어쓴다.
        """
        self._engines[engine.engine_id] = engine
        logger.info(f"OCR 엔진 등록: {engine.engine_id} ({engine.display_name})")

        # 첫 번째로 사용 가능한 엔진을 기본값으로
        if self._default_engine_id is None and engine.is_available():
            self._default_engine_id = engine.engine_id

    def get_engine(self, engine_id: Optional[str] = None) -> BaseOcrEngine:
        """엔진을 조회한다.

        입력: engine_id (None이면 기본 엔진)
        출력: BaseOcrEngine 인스턴스

        에러: OcrEngineUnavailableError — 엔진이 없거나 사용 불가
        """
        if engine_id is None:
            engine_id = self._default_engine_id

        if engine_id is None:
            raise OcrEngineUnavailableError("등록된 OCR 엔진이 없습니다.")

        engine = self._engines.get(engine_id)
        if engine is None:
            available = list(self._engines.keys())
            raise OcrEngineUnavailableError(
                f"엔진 '{engine_id}'를 찾을 수 없습니다. 사용 가능: {available}"
            )

        if not engine.is_available():
            raise OcrEngineUnavailableError(
                f"엔진 '{engine_id}'이(가) 사용할 수 없는 상태입니다."
            )

        return engine

    def list_engines(self) -> list[dict]:
        """등록된 모든 엔진의 정보를 반환한다. API 응답용."""
        return [engine.get_info() for engine in self._engines.values()]

    @property
    def default_engine_id(self) -> Optional[str]:
        return self._default_engine_id

    @default_engine_id.setter
    def default_engine_id(self, engine_id: str) -> None:
        if engine_id not in self._engines:
            raise ValueError(f"등록되지 않은 엔진: {engine_id}")
        self._default_engine_id = engine_id

    def auto_register(self) -> None:
        """사용 가능한 엔진을 자동으로 등록한다.

        각 엔진 모듈을 import 시도하고, 성공하면 등록.
        import 실패 = 해당 엔진의 의존성이 설치되지 않음 → 건너뜀.

        등록 순서 (= 드롭다운 표시 순서, 첫 available이 기본 엔진):
          1. NDL古典籍OCR-Lite — 고전적(古典籍) 전용, 변체가나/고서체/한문 특화
          2. NDLOCR-Lite — 근현대 인쇄 자료 범용
          3. LLM Vision OCR — LLM 비전 기반 (느릴 수 있음)
          4. PaddleOCR — Python 3.13에서 미지원, 맨 뒤 배치

        새 엔진을 추가하려면:
          1. BaseOcrEngine을 상속하는 클래스를 만든다.
          2. 여기에 try/except 블록을 추가한다.
          paddleocr_engine.py를 참고하라.
        """
        # ── 1. NDL古典籍OCR-Lite (고전적 전용 — 최우선 등록) ──
        # 에도 이전 와고서, 청대 이전 한적 등 고전적 자료에 특화.
        # RTMDet(레이아웃) + 단일 PARSeq(문자 인식). ONNX 기반 오프라인.
        # 원본: https://github.com/ndl-lab/ndlkotenocr-lite (CC BY 4.0)
        try:
            from .ndlkotenocr_engine import NdlkotenOcrEngine
            engine = NdlkotenOcrEngine()
            self.register(engine)
            if not engine.is_available():
                logger.info(
                    "NDL古典籍OCR-Lite 등록됨 (onnxruntime 미설치 또는 모델 없음 — 사용 불가). "
                    "설치: uv sync --extra ndlkotenocr"
                )
        except Exception as e:
            logger.warning(f"NDL古典籍OCR-Lite 등록 실패: {e}")

        # ── 2. NDLOCR-Lite (근현대 자료 범용) ──
        # DEIM(레이아웃) + 3단계 PARSeq 캐스케이드(문자 인식). ONNX 기반 오프라인.
        # PaddleOCR이 동작하지 않는 Python 3.13 환경의 대안.
        # 원본: https://github.com/ndl-lab/ndlocr-lite (CC BY 4.0)
        try:
            from .ndlocr_engine import NdlocrEngine
            engine = NdlocrEngine()
            self.register(engine)
            if not engine.is_available():
                logger.info(
                    "NDLOCR-Lite 등록됨 (onnxruntime 미설치 또는 모델 없음 — 사용 불가). "
                    "설치: uv sync --extra ndlocr"
                )
        except Exception as e:
            logger.warning(f"NDLOCR-Lite 등록 실패: {e}")

        # ── 3. LLM Vision OCR (느릴 수 있음) ──
        # LLM 라우터의 비전 기능 사용, 별도 설치 불필요.
        # 라우터는 나중에 서버에서 set_router()로 주입한다.
        try:
            from .llm_ocr_engine import LlmOcrEngine
            engine = LlmOcrEngine(router=None)  # 라우터는 lazy-init
            # is_available()은 라우터가 설정되면 True가 된다.
            # 여기서는 등록만 하고, 라우터 주입은 서버 초기화 시 수행.
            self.register(engine)
            logger.info("LLM Vision OCR 엔진 등록 (라우터 주입 대기)")
        except Exception as e:
            logger.warning(f"LLM Vision OCR 초기화 실패: {e}")

        # ── 4. PaddleOCR (맨 뒤 — Python 3.13 미지원) ──
        # 별도 설치 필요: uv sync --extra paddleocr
        # 미설치 시에도 등록 → list_engines()에서 available=false로 표시.
        # 왜: 프론트엔드에서 "PaddleOCR (사용 불가)" 옵션을 보여주어
        #      사용자에게 설치 가능한 엔진이 있다는 것을 알려주기 위함.
        try:
            from .paddleocr_engine import PaddleOcrEngine
            engine = PaddleOcrEngine()
            self.register(engine)
            if not engine.is_available():
                logger.info("PaddleOCR 등록됨 (패키지 미설치 — 사용 불가)")
        except Exception as e:
            logger.warning(f"PaddleOCR 등록 실패: {e}")

        if not self._engines:
            logger.info(
                "사용 가능한 OCR 엔진이 없습니다. "
                "OCR을 사용하려면 엔진을 설치하세요. "
                "예: uv sync --extra ndlocr 또는 uv sync --extra ndlkotenocr"
            )
