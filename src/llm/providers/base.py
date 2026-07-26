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

    text: str  # 응답 텍스트
    provider: str  # "ollama", "gemini", "openai", "anthropic" 등
    model: str  # 실제 사용된 모델명
    tokens_in: Optional[int] = None  # 입력 토큰 (추정 가능할 때)
    tokens_out: Optional[int] = None  # 출력 토큰
    cost_usd: Optional[float] = None  # 추정 비용 (무료면 0.0)
    elapsed_sec: Optional[float] = None  # 응답 시간 (비교용)
    raw: Optional[dict] = None  # provider별 원본 응답 (디버깅)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


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

    # 과금 방식. 사용량을 사용자에게 어떻게 보여줄지가 이 값에 따라 달라진다.
    #
    #   "metered"      — 쓴 만큼 돈이 나간다(Gemini·OpenAI·Anthropic).
    #                    실제 금액을 보여 줘야 한다.
    #   "subscription" — 구독 한도를 소모한다(Ollama 클라우드, OpenAI OAuth).
    #                    금액은 0이지만 **공짜가 아니다.** $0.00이라고 띄우면
    #                    한도를 쓰고 있다는 사실이 가려지므로, 호출 횟수와
    #                    토큰을 보여 주고 한도는 제공자 대시보드로 안내한다.
    #   "free"         — 로컬 실행이라 소모하는 것이 없다(Ollama 로컬 모델).
    #
    # 왜 이 구분이 필요한가: 폴백 순서만 보고 «무료로 돌 것»이라 여겼는데
    # 실제로는 유료 API가 처리하고 있던 일이 있었다. 어느 방식으로 얼마를
    # 쓰는지 사용자가 그 자리에서 알 수 있어야 한다.
    billing_model: str = "metered"

    def billing_for_model(self, model: str | None = None) -> str:
        """이 호출의 과금 방식을 돌려준다.

        입력: model — 실제로 쓴 모델 이름(같은 프로바이더도 모델에 따라 다를 수 있다).
        출력: "metered" | "subscription" | "free"

        기본은 클래스 값을 그대로 쓴다. Ollama처럼 로컬·클라우드가 섞인
        프로바이더는 이 메서드를 재정의한다.
        """
        return self.billing_model

    # 이 프로바이더를 쓰려면 사용자가 무엇을 해야 하는가.
    #
    #   "env_key"    — .env에 API 키를 넣는다. 배포판에서는 각자 자기 키를 쓴다.
    #   "cli_signin" — 터미널에서 로그인한다(구독형). 앱이 대신 해 줄 수 없다.
    #   "local"      — 설치하고 띄우기만 하면 된다. 계정이 필요 없다.
    #
    # 왜 필요한가: API 키 방식은 «.env에 키를 넣으세요»로 끝나지만, 구독형은
    # 터미널 로그인이 필요하고 그 사실이 어디에도 적혀 있지 않으면 사용자는
    # «왜 안 되는지» 알 수 없다. 폴백이 조용히 다음 프로바이더로 넘어가므로
    # 화면에는 아무 표시도 남지 않는다(D-056).
    setup_kind: str = "env_key"

    # 로그인·설정에 필요한 명령. setup_kind에 맞춰 화면에 그대로 보여 준다.
    setup_steps: tuple[str, ...] = ()

    def __init__(self, config):
        self.config = config

    async def account_info(self) -> dict | None:
        """로그인한 계정 정보를 돌려준다. 알 수 없으면 None.

        출력 예: {"account": "user@example.com", "plan": "pro"}

        왜 이 메서드가 있는가:
            구독형 프로바이더는 «서비스가 떠 있다»와 «로그인돼 있다»가 다르다.
            Ollama 서버는 로그인 없이도 뜨지만 클라우드 모델을 부르면 실패한다.
            is_available()만 보면 «사용 가능»으로 보이므로, 실행하고 나서야
            안 되는 것을 알게 된다.

        기본은 None이다 — 조회할 방법이 확인되지 않은 프로바이더는
        **있는 것처럼 만들지 않는다.** 남은 한도는 어느 프로바이더도
        제공하지 않으므로 이 메서드로 돌려주지 않는다(D-056).
        """
        return None

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
        response_format: str = "text",  # "text" | "json"
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
            네이티브 스트리밍을 지원하지 않는 프로바이더(Anthropic 등)도
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
                prompt,
                system=system,
                response_format=response_format,
                model=model,
                max_tokens=max_tokens,
                purpose=purpose,
                **kwargs,
            )
        )

        while not call_task.done():
            await asyncio.sleep(2.0)
            if progress_callback and not call_task.done():
                progress_callback(
                    {
                        "type": "progress",
                        "elapsed_sec": round(time.monotonic() - t0, 1),
                        "provider": self.provider_id,
                    }
                )

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
