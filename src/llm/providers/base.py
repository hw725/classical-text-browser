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
