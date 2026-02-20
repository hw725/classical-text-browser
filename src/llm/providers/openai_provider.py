"""OpenAI Provider.

OpenAI Chat Completions API 호출.
비전(이미지 분석) 지원.

환경변수: OPENAI_API_KEY
"""

import base64
import time
from typing import Optional

from .base import BaseLlmProvider, LlmProviderError, LlmResponse


class OpenAiProvider(BaseLlmProvider):
    """OpenAI API 호출. 비전 포함."""

    provider_id = "openai"
    display_name = "OpenAI"
    supports_image = True
    DEFAULT_MODEL = "gpt-5-mini"  # 비용 효율적 기본 모델

    # 주요 모델 목록 (하드코딩 — API로 모델 목록을 가져올 수 있지만
    # 불필요한 모델이 너무 많아서 수동 관리가 실용적)
    MODELS = [
        {"name": "gpt-5-nano", "vision": True, "cost": "lowest",
         "input": 0.0001, "output": 0.0004},
        {"name": "gpt-5-mini", "vision": True, "cost": "low",
         "input": 0.0004, "output": 0.0016},
        {"name": "gpt-5", "vision": True, "cost": "medium",
         "input": 0.002, "output": 0.008},
        {"name": "o3-mini", "vision": False, "cost": "medium",
         "input": 0.0011, "output": 0.0044},
        {"name": "gpt-5-pro", "vision": True, "cost": "high",
         "input": 0.015, "output": 0.06},
    ]

    # 가격표 (1K tokens 기준, USD)
    PRICING = {m["name"]: {"input": m["input"], "output": m["output"]} for m in MODELS}

    async def is_available(self) -> bool:
        """OPENAI_API_KEY가 설정되어 있는지 확인."""
        return bool(self.config.get_api_key("openai"))

    async def list_models(self) -> list[dict]:
        """주요 모델 목록 반환. GUI 드롭다운용."""
        return [
            {
                "name": m["name"],
                "vision": m["vision"],
                "cost": m["cost"],
            }
            for m in self.MODELS
        ]

    def _estimate_cost(self, model: str,
                       tokens_in: Optional[int],
                       tokens_out: Optional[int]) -> float:
        """토큰 수로 비용 추정."""
        pricing = self.PRICING.get(
            model, {"input": 0.0004, "output": 0.0016}
        )
        cost = (
            (tokens_in or 0) / 1000 * pricing["input"]
            + (tokens_out or 0) / 1000 * pricing["output"]
        )
        return round(cost, 6)

    async def call(self, prompt, *, system=None, response_format="text",
                   model=None, max_tokens=4096, purpose="text",
                   **kwargs) -> LlmResponse:
        """OpenAI Chat Completions API로 텍스트 생성."""
        import openai

        api_key = self.config.get_api_key("openai")
        if not api_key:
            raise LlmProviderError("OPENAI_API_KEY가 설정되지 않았습니다.")

        client = openai.AsyncOpenAI(api_key=api_key)
        selected_model = model or self.DEFAULT_MODEL

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        create_kwargs = {
            "model": selected_model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if response_format == "json":
            create_kwargs["response_format"] = {"type": "json_object"}

        t0 = time.monotonic()
        response = await client.chat.completions.create(**create_kwargs)
        elapsed = time.monotonic() - t0

        text = response.choices[0].message.content if response.choices else ""
        tokens_in = response.usage.prompt_tokens if response.usage else None
        tokens_out = response.usage.completion_tokens if response.usage else None

        return LlmResponse(
            text=text or "",
            provider=self.provider_id,
            model=response.model or selected_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=self._estimate_cost(selected_model, tokens_in, tokens_out),
            elapsed_sec=round(elapsed, 2),
            raw={"id": response.id},
        )

    async def call_with_image(self, prompt, image, *, image_mime="image/png",
                              system=None, response_format="text", model=None,
                              max_tokens=4096, **kwargs) -> LlmResponse:
        """OpenAI Vision으로 이미지 분석.

        이미지는 base64 data URI로 전달한다.
        """
        import openai

        api_key = self.config.get_api_key("openai")
        if not api_key:
            raise LlmProviderError("OPENAI_API_KEY가 설정되지 않았습니다.")

        client = openai.AsyncOpenAI(api_key=api_key)
        selected_model = model or self.DEFAULT_MODEL

        b64_data = base64.b64encode(image).decode("ascii")
        data_uri = f"data:{image_mime};base64,{b64_data}"

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": data_uri},
                },
                {"type": "text", "text": prompt},
            ],
        })

        t0 = time.monotonic()
        response = await client.chat.completions.create(
            model=selected_model,
            messages=messages,
            max_tokens=max_tokens,
        )
        elapsed = time.monotonic() - t0

        text = response.choices[0].message.content if response.choices else ""
        tokens_in = response.usage.prompt_tokens if response.usage else None
        tokens_out = response.usage.completion_tokens if response.usage else None

        return LlmResponse(
            text=text or "",
            provider=self.provider_id,
            model=response.model or selected_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=self._estimate_cost(selected_model, tokens_in, tokens_out),
            elapsed_sec=round(elapsed, 2),
            raw={"id": response.id},
        )
