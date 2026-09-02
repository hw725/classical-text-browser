"""LLM 기반 OCR 엔진.

기존 LLM 라우터(src/llm/)의 비전 기능을 사용하여
이미지에서 텍스트를 인식한다.

별도의 OCR 라이브러리(PaddleOCR, Tesseract 등)를 설치할 필요 없이,
이미 구성된 LLM 프로바이더(ollama, gemini, openai, anthropic)의
비전 기능으로 고전 텍스트를 인식한다.

왜 LLM을 OCR에 쓰는가:
  - 고전 한문은 세로쓰기, 이체자, 약자 등으로 전통 OCR의 정확도가 낮다.
  - 비전 LLM은 문맥을 이해하므로 글자 인식 정확도가 높다.
  - 추가 의존성 설치 없이 기존 LLM 인프라를 재사용한다.

사용법:
    from src.llm.router import LlmRouter
    from src.llm.config import LlmConfig
    from src.ocr.llm_ocr_engine import LlmOcrEngine

    config = LlmConfig()
    router = LlmRouter(config)
    engine = LlmOcrEngine(router)
    result = engine.recognize(image_bytes)
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Optional

from .base import (
    BaseOcrEngine,
    OcrBlockResult,
    OcrCharResult,
    OcrEngineError,
    OcrEngineUnavailableError,
    OcrLineResult,
)
from .ocr_prompt import build_system_prompt, build_user_prompt, parse_uncertainty

try:  # 프로바이더가 잘림을 알리는 표식. 경로 문제로 못 읽으면 문자열로 대체.
    from llm.providers.base import TRUNCATED_MARK
except ImportError:  # pragma: no cover — src 경로 설정이 다른 실행 환경
    TRUNCATED_MARK = "truncated"

logger = logging.getLogger(__name__)


# ─── 프롬프트 템플릿 ──────────────────────────────────────

# 시스템 프롬프트는 ocr_prompt.build_system_prompt()가 만든다 (D-081).
# 예전에는 여기 문자열 상수로 있었다 — 페르소나 한 줄·규칙 5개가 전부였고,
# 문헌·블록·자형·앵커 정보는 어디에도 들어가지 않았다.
_OCR_SYSTEM_PROMPT = build_system_prompt()


# 답변 JSON 스키마. Ollama는 format에 이 객체를 그대로 받고, 다른 프로바이더는
# JSON 모드만 켠다(스키마 미지원이거나 형식이 달라서). 스키마와 시스템 프롬프트의
# 출력 형식 설명은 같은 모양이어야 한다 — 어긋나면 모델이 둘 중 하나를 따른다.
OCR_LINES_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        }
    },
    "required": ["lines"],
}


def _build_ocr_prompt(writing_direction: str, language: str, **context) -> str:
    """OCR 요청 프롬프트를 조립한다 (D-081).

    입력: 서사 방향·언어, 그리고 recognize() kwargs에서 넘어온 문맥:
          block_type / doc_guidance / variant_hints / anchor_text /
          context_before / context_after. 없는 조각은 자리 자체가 빠진다.
    출력: 사용자 프롬프트 문자열.
    """
    return build_user_prompt(
        writing_direction,
        language,
        block_type=context.get("block_type"),
        doc_guidance=context.get("doc_guidance"),
        variant_hints=context.get("variant_hints"),
        anchor_text=context.get("anchor_text"),
        context_before=context.get("context_before"),
        context_after=context.get("context_after"),
    )


class LlmOcrEngine(BaseOcrEngine):
    """LLM 비전 기반 OCR 엔진.

    기존 LLM 라우터의 call_with_image()를 사용하여
    이미지에서 텍스트를 인식한다.

    왜 BaseOcrEngine을 상속하는가:
        기존 OCR 파이프라인(registry → pipeline → run_page)에
        플러그인으로 끼워넣기 위해서다.
        사용자는 OCR 엔진 드롭다운에서 "LLM Vision"을 선택하면 된다.
    """

    engine_id = "llm_vision"
    display_name = "LLM Vision OCR"
    requires_network = True  # LLM 호출에 네트워크 필요

    def __init__(self, router=None):
        """초기화.

        입력:
          router: LlmRouter 인스턴스. None이면 나중에 set_router()로 설정.
                  서버 시작 시 lazy-init 패턴에 맞추기 위해 None 허용.
        """
        self._router = router
        # 가용성 캐시 (매번 async 호출 방지)
        self._available_cache: Optional[bool] = None

    def set_router(self, router) -> None:
        """LLM 라우터를 설정한다. 서버의 lazy-init에서 사용."""
        self._router = router
        self._available_cache = None

    def is_available(self) -> bool:
        """LLM 라우터가 설정되어 있고, 비전 지원 프로바이더가 있는지 확인.

        왜 캐시를 쓰는가:
            is_available()은 sync인데 LLM 상태 확인은 async다.
            서버 시작 시 한 번만 확인하고 캐시한다.
            라우터가 설정되면 캐시를 초기화한다.
        """
        if self._router is None:
            return False

        if self._available_cache is not None:
            return self._available_cache

        # 비전 지원 프로바이더가 하나라도 있으면 사용 가능
        for provider in self._router.providers:
            if provider.supports_image:
                self._available_cache = True
                return True

        self._available_cache = False
        return False

    def recognize(
        self,
        image_bytes: bytes,
        writing_direction: str = "vertical_rtl",
        language: str = "classical_chinese",
        **kwargs,
    ) -> OcrBlockResult:
        """이미지에서 텍스트를 인식한다.

        LLM 라우터는 async이므로, 별도 스레드에서 이벤트 루프를 생성하여
        async→sync 브릿지를 수행한다.

        왜 스레드를 쓰는가:
            FastAPI의 async 핸들러 안에서 호출되므로
            이미 돌고 있는 이벤트 루프에서 asyncio.run()을 쓸 수 없다.
            별도 스레드의 새 이벤트 루프에서 LLM 호출을 실행한다.
        """
        if not self.is_available():
            raise OcrEngineUnavailableError(
                "LLM Vision OCR을 사용할 수 없습니다. "
                "LLM 라우터가 설정되지 않았거나 비전 지원 프로바이더가 없습니다."
            )

        # async 결과를 담을 컨테이너
        result_holder: dict = {}

        def _run_in_thread():
            """별도 스레드에서 async LLM 호출을 실행한다."""
            try:
                result_holder["value"] = asyncio.run(
                    self._recognize_async(image_bytes, writing_direction, language, **kwargs)
                )
            except Exception as e:
                result_holder["error"] = e

        thread = threading.Thread(target=_run_in_thread, daemon=True)
        thread.start()
        thread.join(timeout=120)

        if "error" in result_holder:
            raise OcrEngineError(f"LLM OCR 실패: {result_holder['error']}")
        if "value" not in result_holder:
            raise OcrEngineError("LLM OCR 타임아웃 (120초)")

        return result_holder["value"]

    async def _recognize_async(
        self,
        image_bytes: bytes,
        writing_direction: str,
        language: str,
        **kwargs,
    ) -> OcrBlockResult:
        """async로 LLM 비전 호출 → OcrBlockResult 변환.

        처리 순서:
          1. 프롬프트 생성
          2. LLM 라우터에 이미지 전송
          3. JSON 응답 파싱
          4. OcrBlockResult로 변환
        """
        prompt = _build_ocr_prompt(writing_direction, language, **kwargs)

        # kwargs에서 force_provider/force_model 추출 (UI 프로바이더 선택 지원)
        force_provider = kwargs.get("force_provider")
        force_model = kwargs.get("force_model")

        base_kwargs = dict(
            image_mime="image/png",
            purpose="ocr",
            system=_OCR_SYSTEM_PROMPT,
            # 답변을 스키마로 묶는다 (D-083 원칙 2). 사고를 켠 모델이 추론 문장을
            # 답변 자리에 흘리는 것을 막는 가장 확실한 방법이다. 프로바이더마다
            # 형식 강제 수단이 다르므로(Ollama format / Gemini mime / OpenAI
            # response_format) 여기서는 의도만 말하고 수단은 프로바이더가 고른다.
            response_format="json",
            json_schema=OCR_LINES_SCHEMA,
            # 빈 응답이 오면 thinking을 대신 쓰지 않는다 (D-074). 사고문이
            # PDF 텍스트 레이어로 구워지면 문서는 멀쩡해 보이는데 검색이
            # 안 되고 복사하면 사고문이 나온다. 빈 결과는 «실패»로 드러나기라도
            # 하지만 이 오염은 드러나지 않는다. 어떤 시도에서도 이 값은 바뀌지 않는다.
            allow_thinking_fallback=False,
        )
        if force_provider:
            base_kwargs["force_provider"] = force_provider
        if force_model:
            base_kwargs["force_model"] = force_model

        response = None
        last_error: Optional[Exception] = None
        for attempt in self._plan_attempts(kwargs):
            call_kwargs = dict(base_kwargs, **attempt)
            try:
                response = await self._router.call_with_image(prompt, image_bytes, **call_kwargs)
                break
            except Exception as e:  # noqa: BLE001 — 잘림만 사다리를 타고 나머지는 그대로 올린다
                last_error = e
                if TRUNCATED_MARK in str(e).lower() or "잘렸" in str(e):
                    logger.warning(
                        f"LLM OCR 출력 잘림 (think={attempt.get('think')!r}, "
                        f"max_tokens={attempt.get('max_tokens')}) → 다음 단계로: {e}"
                    )
                    continue
                raise
        if response is None:
            raise OcrEngineError(
                f"LLM OCR 출력이 모든 시도에서 잘렸습니다: {last_error}\n"
                "→ 블록을 더 작게 나누거나, 추론을 끄고 다시 시도하세요."
            )

        # 응답 텍스트에서 JSON 추출
        raw_text = response.text.strip()
        lines_data = self._parse_response(raw_text)

        # OcrBlockResult로 변환
        ocr_lines = []
        for line_info in lines_data:
            text = line_info.get("text", "")
            if not text:
                continue

            # [?]·□ 마커를 글자별 신뢰도로 바꾼다 (D-081). 예전에는 모든 글자에
            # 0.9를 박았다 — 하류(선별·형광)가 신뢰도로 오해할 가짜 값이었다.
            # 마커는 텍스트에서 걷어 낸다. 남으면 PDF 텍스트 레이어에 구워진다.
            clean_text, confidences = parse_uncertainty(text)
            if not clean_text:
                continue
            characters = [
                OcrCharResult(char=ch, confidence=conf) for ch, conf in zip(clean_text, confidences)
            ]

            ocr_lines.append(
                OcrLineResult(
                    text=clean_text,
                    characters=characters,
                )
            )

        result = OcrBlockResult(
            lines=ocr_lines,
            engine_id=self.engine_id,
            language=language,
            writing_direction=writing_direction,
        )

        logger.info(
            f"LLM OCR 완료: {len(ocr_lines)}줄, "
            f"{result.char_count}자 인식 "
            f"(provider: {response.provider})"
        )

        return result

    @staticmethod
    def _plan_attempts(kwargs: dict) -> list[dict]:
        """호출 시도 사다리를 짠다 (D-083 원칙 3).

        입력: recognize()가 받은 kwargs. 보는 키:
            think            — None/False(기본: 사고 끔, D-074) | True | "low" 등
            thinking_budget  — 사고 예산(토큰). 없으면 프로바이더 기본값
            max_tokens       — 답변 예산. 없으면 4096
        출력: 시도마다 router.call_with_image에 덧붙일 kwargs 목록. 앞에서부터
              시도하고, 출력이 **잘렸을 때만** 다음으로 넘어간다.

        사다리:
          1) 요청대로 (사고를 켰으면 켠 채로, 예산 분리)
          2) 사고를 켰다면 → 사고를 끄고 같은 답변 예산으로
          3) 답변 예산을 두 배로 (사고 끔)
        빈 응답은 여기서 다루지 않는다 — 그것은 «실패»로 그대로 드러나야 한다.
        thinking 필드를 본문으로 쓰는 폴백은 어떤 단계에도 없다.
        """
        think = kwargs.get("think", False)
        if think is None:
            think = False
        budget = kwargs.get("thinking_budget")
        max_tokens = int(kwargs.get("max_tokens") or 4096)

        attempts: list[dict] = []
        first = {"think": think, "max_tokens": max_tokens}
        if think and budget:
            first["thinking_budget"] = int(budget)
        attempts.append(first)
        if think:
            attempts.append({"think": False, "max_tokens": max_tokens})
        attempts.append({"think": False, "max_tokens": max_tokens * 2})
        return attempts

    def _parse_response(self, raw_text: str) -> list[dict]:
        """LLM 응답에서 lines 배열을 추출한다.

        LLM이 markdown 코드 블록으로 감싸거나,
        부가 설명을 포함할 수 있으므로 방어적으로 파싱한다.

        입력: LLM 응답 텍스트
        출력: [{"text": "줄1"}, {"text": "줄2"}, ...]
        """
        text = raw_text

        # markdown 코드 블록 제거: ```json ... ```
        if "```" in text:
            # 첫 번째 ``` 이후 ~ 마지막 ``` 이전 추출
            parts = text.split("```")
            # parts[1]이 코드 블록 내용 (json 접두사 포함 가능)
            if len(parts) >= 3:
                text = parts[1]
                # "json\n" 접두사 제거
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

        # JSON 파싱 시도
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # JSON 객체 부분만 추출 시도
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    data = json.loads(text[start:end])
                except json.JSONDecodeError:
                    # 최후 수단: 줄바꿈으로 분리
                    logger.warning(
                        f"LLM OCR 응답 JSON 파싱 실패, 줄바꿈 분리로 대체: {text[:100]}..."
                    )
                    return [{"text": line} for line in text.split("\n") if line.strip()]
            else:
                return [{"text": line} for line in text.split("\n") if line.strip()]

        # data가 {"lines": [...]} 형태인지 확인
        if isinstance(data, dict) and "lines" in data:
            return data["lines"]
        elif isinstance(data, list):
            return data
        else:
            # 예상치 못한 형태: 텍스트 필드 찾기
            logger.warning(f"LLM OCR 예상치 못한 응답 형태: {type(data)}")
            return [{"text": str(data)}]
