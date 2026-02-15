"""Anthropic Provider (4순위).

Anthropic Claude API 직접 호출. 최후 수단.
유료지만 가장 안정적. 고전 한문 분석에 Claude가 가장 정확할 수 있다.
"""

import base64
import time
from typing import Optional

from .base import BaseLlmProvider, LlmProviderError, LlmResponse


class AnthropicProvider(BaseLlmProvider):
    """Anthropic Claude API 직접 호출."""

    provider_id = "anthropic"
    display_name = "Claude (Anthropic)"
    supports_image = True
    DEFAULT_MODEL = "claude-sonnet-4-20250514"

    # 대략적 가격 (1K tokens 기준, USD)
    PRICING = {
        "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
    }

    async def is_available(self) -> bool:
        """ANTHROPIC_API_KEY가 설정되어 있는지 확인."""
        return bool(self.config.get_api_key("anthropic"))

    def _estimate_cost(self, model: str,
                       tokens_in: Optional[int],
                       tokens_out: Optional[int]) -> float:
        """토큰 수로 비용 추정."""
        pricing = self.PRICING.get(
            model, {"input": 0.003, "output": 0.015}
        )
        cost = (
            (tokens_in or 0) / 1000 * pricing["input"]
            + (tokens_out or 0) / 1000 * pricing["output"]
        )
        return round(cost, 6)

    async def call(self, prompt, *, system=None, response_format="text",
                   model=None, max_tokens=4096, purpose="text",
                   **kwargs) -> LlmResponse:
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

    async def call_with_image(self, prompt, image, *, image_mime="image/png",
                              system=None, response_format="text", model=None,
                              max_tokens=4096, **kwargs) -> LlmResponse:
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
