"""LLM provider 추상 클래스 + 통합 응답 모델.

모든 provider는 BaseLlmProvider를 구현한다.
router.py가 우선순위에 따라 순서대로 시도.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class LlmResponse:
    """모든 provider가 반환하는 통합 응답 모델.

    어떤 provider를 썼든 호출자는 동일한 형식을 받는다.
    """

    text: str                                # 응답 텍스트
    provider: str                            # "base44_http", "ollama", "anthropic" 등
    model: str                               # 실제 사용된 모델명
    tokens_in: Optional[int] = None          # 입력 토큰 (추정 가능할 때)
    tokens_out: Optional[int] = None         # 출력 토큰
    cost_usd: Optional[float] = None         # 추정 비용 (무료면 0.0)
    elapsed_sec: Optional[float] = None      # 응답 시간 (비교용)
    raw: Optional[dict] = None               # provider별 원본 응답 (디버깅)
    timestamp: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )


class LlmProviderError(Exception):
    """개별 provider 호출 실패."""
    pass


class LlmUnavailableError(Exception):
    """모든 provider가 사용 불가."""
    pass


class BaseLlmProvider(ABC):
    """LLM provider 추상 클래스.

    각 provider는 이것을 구현한다.
    router.py가 우선순위에 따라 순서대로 시도.
    """

    provider_id: str = ""
    display_name: str = ""
    supports_image: bool = False

    def __init__(self, config):
        self.config = config

    @abstractmethod
    async def is_available(self) -> bool:
        """이 provider가 현재 사용 가능한지 확인."""
        ...

    @abstractmethod
    async def call(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        response_format: str = "text",   # "text" | "json"
        model: Optional[str] = None,
        max_tokens: int = 4096,
        purpose: str = "text",
        **kwargs,
    ) -> LlmResponse:
        """텍스트 프롬프트로 LLM 호출."""
        ...

    async def call_stream(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        response_format: str = "text",
        model: Optional[str] = None,
        max_tokens: int = 4096,
        purpose: str = "text",
        progress_callback=None,
        **kwargs,
    ) -> "LlmResponse":
        """스트리밍 LLM 호출. 기본 구현은 call()을 감싸서 heartbeat를 생성한다.

        왜 이렇게 하는가:
            네이티브 스트리밍을 지원하지 않는 프로바이더(Base44, Anthropic 등)도
            heartbeat 이벤트를 통해 사용자에게 '처리 중'임을 알릴 수 있다.
            네이티브 스트리밍을 지원하는 프로바이더(Ollama, OpenAI, Gemini)는
            이 메서드를 오버라이드하여 토큰 단위 진행률을 제공한다.

        입력:
            progress_callback — 선택적 콜백.
                {"type":"progress","elapsed_sec":N,"provider":"..."} dict를 받는다.
                SSE 이벤트로 변환하여 프론트엔드에 전달된다.
        출력: LlmResponse (call()과 동일).
        """
        import asyncio
        import time

        t0 = time.monotonic()

        # call()을 태스크로 실행하면서 2초마다 heartbeat 전송
        call_task = asyncio.create_task(
            self.call(
                prompt, system=system, response_format=response_format,
                model=model, max_tokens=max_tokens, purpose=purpose,
                **kwargs,
            )
        )

        while not call_task.done():
            await asyncio.sleep(2.0)
            if progress_callback and not call_task.done():
                progress_callback({
                    "type": "progress",
                    "elapsed_sec": round(time.monotonic() - t0, 1),
                    "provider": self.provider_id,
                })

        return call_task.result()

    @abstractmethod
    async def call_with_image(
        self,
        prompt: str,
        image: bytes,
        *,
        image_mime: str = "image/png",
        system: Optional[str] = None,
        response_format: str = "text",
        model: Optional[str] = None,
        max_tokens: int = 4096,
        **kwargs,
    ) -> LlmResponse:
        """이미지 + 텍스트 프롬프트로 LLM 호출.

        supports_image=False인 provider에서 호출하면 NotImplementedError.
        """
        ...
