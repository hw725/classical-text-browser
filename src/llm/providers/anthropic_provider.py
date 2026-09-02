"""Anthropic Provider (4순위).

Anthropic Claude API 직접 호출. 최후 수단.
유료지만 가장 안정적. 고전 한문 분석에 Claude가 가장 정확할 수 있다.
"""

import base64
import time
from typing import Optional

from .base import (
    TRUNCATED_MARK,
    BaseLlmProvider,
    LlmProviderError,
    LlmResponse,
    thinking_options,
)


class AnthropicProvider(BaseLlmProvider):
    """Anthropic Claude API 직접 호출."""

    provider_id = "anthropic"
    display_name = "Claude (Anthropic)"
    supports_image = True
    billing_model = "metered"  # 쓴 만큼 과금된다
    DEFAULT_MODEL = "claude-sonnet-4-20250514"

    # 배포판에서는 각자 자기 키를 .env에 넣는다.
    setup_kind = "env_key"
    setup_steps = (
        "https://console.anthropic.com/settings/keys 에서 키 발급",
        ".env에 ANTHROPIC_API_KEY=... 를 적고 서버 재시작",
    )

    # 대략적 가격 (1K tokens 기준, USD)
    PRICING = {
        "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
    }

    async def is_available(self) -> bool:
        """ANTHROPIC_API_KEY가 설정되어 있는지 확인."""
        return bool(self.config.get_api_key("anthropic"))

    def _estimate_cost(
        self, model: str, tokens_in: Optional[int], tokens_out: Optional[int]
    ) -> float:
        """토큰 수로 비용 추정."""
        pricing = self.PRICING.get(model, {"input": 0.003, "output": 0.015})
        cost = (tokens_in or 0) / 1000 * pricing["input"] + (tokens_out or 0) / 1000 * pricing[
            "output"
        ]
        return round(cost, 6)

    async def call(
        self,
        prompt,
        *,
        system=None,
        response_format="text",
        model=None,
        max_tokens=4096,
        purpose="text",
        **kwargs,
    ) -> LlmResponse:
        """Claude API로 텍스트 생성."""
        import anthropic

        api_key = self.config.get_api_key("anthropic")
        if not api_key:
            raise LlmProviderError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")

        client = anthropic.AsyncAnthropic(api_key=api_key)
        selected_model = model or self.DEFAULT_MODEL

        messages = [{"role": "user", "content": prompt}]

        t0 = time.monotonic()
        response = await client.messages.create(
            model=selected_model,
            max_tokens=max_tokens,
            system=system or "",
            messages=messages,
        )
        elapsed = time.monotonic() - t0

        text = response.content[0].text if response.content else ""
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens

        return LlmResponse(
            text=text,
            provider=self.provider_id,
            model=response.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=self._estimate_cost(selected_model, tokens_in, tokens_out),
            elapsed_sec=round(elapsed, 2),
            raw={"id": response.id},
        )

    async def call_with_image(
        self,
        prompt,
        image,
        *,
        image_mime="image/png",
        system=None,
        response_format="text",
        model=None,
        max_tokens=4096,
        **kwargs,
    ) -> LlmResponse:
        """Claude Vision으로 이미지 분석."""
        import anthropic

        api_key = self.config.get_api_key("anthropic")
        if not api_key:
            raise LlmProviderError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")

        client = anthropic.AsyncAnthropic(api_key=api_key)
        selected_model = model or self.DEFAULT_MODEL

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image_mime,
                            "data": base64.b64encode(image).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        # 사고 예산을 답변 예산에 더한다 (D-083). Anthropic은 max_tokens가
        # budget_tokens보다 커야 한다는 제약이 있는데, 더해서 잡으면 항상 성립한다.
        think, thinking_budget = thinking_options(kwargs)
        create_kwargs = self._vision_create_kwargs(
            selected_model, messages, system, max_tokens, think, thinking_budget
        )

        t0 = time.monotonic()
        response = await client.messages.create(**create_kwargs)
        elapsed = time.monotonic() - t0

        text = self._text_from_content(response.content)
        stop_reason = str(getattr(response, "stop_reason", "") or "")
        # 잘림·빈 응답은 실패로 드러낸다 (D-083 원칙 3).
        if response_format == "json" and stop_reason == "max_tokens":
            raise LlmProviderError(
                f"Anthropic vision JSON output {TRUNCATED_MARK} (stop_reason={stop_reason}, "
                f"max_tokens={max_tokens}, thinking_budget={thinking_budget})"
            )
        if response_format == "json" and not text.strip():
            raise LlmProviderError(
                f"Anthropic vision empty JSON output (stop_reason={stop_reason}, "
                f"max_tokens={max_tokens})"
            )
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens

        return LlmResponse(
            text=text,
            provider=self.provider_id,
            model=response.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=self._estimate_cost(selected_model, tokens_in, tokens_out),
            elapsed_sec=round(elapsed, 2),
            raw={"id": response.id, "stop_reason": stop_reason},
        )

    @staticmethod
    def _text_from_content(content) -> str:
        """응답 content 블록에서 **text 블록만** 모아 본문을 만든다.

        왜 content[0].text를 쓰지 않는가:
            사고를 켜면 첫 블록이 thinking 블록이다. content[0].text는 거기서
            AttributeError로 죽거나, SDK 버전에 따라 사고문을 본문으로 돌려준다.
            후자는 D-074가 막은 바로 그 오염이다. 블록 type을 보고 고른다.
        """
        parts = []
        for block in content or []:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", "") or "")
        return "".join(parts)

    @staticmethod
    def _vision_create_kwargs(
        model: str, messages: list, system, max_tokens: int, think, thinking_budget: int
    ) -> dict:
        """비전 호출 인자를 조립한다. 순수 함수라 테스트로 고정한다.

        think가 켜져 있으면 thinking={"type":"enabled","budget_tokens":N}을 넣고
        max_tokens를 N만큼 늘린다. Anthropic의 budget_tokens 최소치는 1024다.
        think=False/None이면 사고 설정을 보내지 않는다(모델 기본은 사고 없음).
        """
        kwargs = {
            "model": model,
            "max_tokens": max_tokens + (thinking_budget if think else 0),
            "system": system or "",
            "messages": messages,
        }
        if think:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": max(1024, thinking_budget)}
        return kwargs
