"""LLM 기반 OCR 엔진.

기존 LLM 라우터(src/llm/)의 비전 기능을 사용하여
이미지에서 텍스트를 인식한다.

별도의 OCR 라이브러리(PaddleOCR, Tesseract 등)를 설치할 필요 없이,
이미 구성된 LLM 프로바이더(base44_http, base44_bridge, ollama, anthropic)의
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

logger = logging.getLogger(__name__)


# ─── 프롬프트 템플릿 ──────────────────────────────────────

_OCR_SYSTEM_PROMPT = """\
당신은 고전 텍스트 OCR 전문가입니다.
이미지에서 텍스트를 정확하게 읽어 JSON으로 반환하세요.

규칙:
1. 이미지에 보이는 텍스트를 한 줄씩 읽습니다.
2. 세로쓰기(vertical_rtl)이면 오른쪽 열부터 왼쪽으로, 각 열은 위에서 아래로 읽습니다.
3. 가로쓰기(horizontal_ltr)이면 위에서 아래로, 각 행은 왼쪽에서 오른쪽으로 읽습니다.
4. 이체자, 약자는 원문 그대로 옮기되, 판독 불가 글자는 □로 표기합니다.
5. 반드시 순수 JSON만 출력하세요. 설명이나 markdown은 절대 포함하지 마세요.

출력 형식 (JSON):
{"lines": [{"text": "첫째 줄 텍스트"}, {"text": "둘째 줄 텍스트"}, ...]}
"""


def _build_ocr_prompt(writing_direction: str, language: str) -> str:
    """OCR 요청 프롬프트를 생성한다."""
    dir_desc = {
        "vertical_rtl": "세로쓰기 (오른쪽→왼쪽)",
        "vertical_ltr": "세로쓰기 (왼쪽→오른쪽)",
        "horizontal_ltr": "가로쓰기 (왼쪽→오른쪽)",
        "horizontal_rtl": "가로쓰기 (오른쪽→왼쪽)",
    }
    lang_desc = {
        "classical_chinese": "고전 한문(漢文)",
        "korean": "한국어",
        "japanese": "일본어",
    }

    direction = dir_desc.get(writing_direction, writing_direction)
    lang = lang_desc.get(language, language)

    return (
        f"이 이미지의 텍스트를 읽어주세요.\n"
        f"서사 방향: {direction}\n"
        f"언어: {lang}\n"
        f"JSON으로만 응답하세요."
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
                    self._recognize_async(
                        image_bytes, writing_direction, language, **kwargs
                    )
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
        prompt = _build_ocr_prompt(writing_direction, language)

        # kwargs에서 force_provider/force_model 추출 (UI 프로바이더 선택 지원)
        force_provider = kwargs.get("force_provider")
        force_model = kwargs.get("force_model")

        call_kwargs = dict(
            image_mime="image/png",
            purpose="ocr",
            system=_OCR_SYSTEM_PROMPT,
        )
        if force_provider:
            call_kwargs["force_provider"] = force_provider
        if force_model:
            call_kwargs["force_model"] = force_model

        response = await self._router.call_with_image(
            prompt,
            image_bytes,
            **call_kwargs,
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

            # 글자별 OcrCharResult 생성 (bbox 없음, 신뢰도 LLM 기본값)
            characters = [
                OcrCharResult(char=ch, confidence=0.9)
                for ch in text
                if ch.strip()  # 공백 제외
            ]

            ocr_lines.append(OcrLineResult(
                text=text,
                characters=characters,
            ))

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
                        f"LLM OCR 응답 JSON 파싱 실패, 줄바꿈 분리로 대체: "
                        f"{text[:100]}..."
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
