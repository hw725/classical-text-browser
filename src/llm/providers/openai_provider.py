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

    # 주요 모델 목록 (2026-02 기준, 수동 관리)
    # API로 모델 목록을 가져올 수 있지만 불필요한 모델이 너무 많아서 수동 관리가 실용적.
    # 가격: 1K 토큰당 USD. 출처: https://platform.openai.com/docs/pricing
    MODELS = [
        {"name": "gpt-5-nano", "vision": True, "cost": "lowest",
         "input": 0.00005, "output": 0.0004},
        {"name": "gpt-5-mini", "vision": True, "cost": "low",
         "input": 0.00025, "output": 0.002},
        {"name": "gpt-5", "vision": True, "cost": "medium",
         "input": 0.00125, "output": 0.01},
        {"name": "gpt-5.2", "vision": True, "cost": "high",
         "input": 0.00175, "output": 0.014},
        {"name": "o4-mini", "vision": False, "cost": "medium",
         "input": 0.0011, "output": 0.0044},
        {"name": "gpt-4.1", "vision": True, "cost": "high",
         "input": 0.002, "output": 0.008},
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
        }
        # OpenAI 최신 모델(gpt-5, o3 등)은 max_tokens 대신
        # max_completion_tokens를 사용한다.
        # 구형 모델 호환을 위해 먼저 max_completion_tokens를 시도하고,
        # 실패하면 max_tokens로 폴백한다.
        create_kwargs["max_completion_tokens"] = max_tokens
        if response_format == "json":
            create_kwargs["response_format"] = {"type": "json_object"}

        t0 = time.monotonic()
        try:
            response = await client.chat.completions.create(**create_kwargs)
        except openai.BadRequestError as e:
            if "max_completion_tokens" in str(e):
                # 구형 모델: max_tokens로 폴백
                del create_kwargs["max_completion_tokens"]
                create_kwargs["max_tokens"] = max_tokens
                response = await client.chat.completions.create(**create_kwargs)
            else:
                raise
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

    async def call_stream(
        self, prompt, *, system=None, response_format="text",
        model=None, max_tokens=4096, purpose="text",
        progress_callback=None, **kwargs,
    ) -> LlmResponse:
        """OpenAI 네이티브 스트리밍. stream=True로 청크 단위 수신.

        왜 네이티브 스트리밍을 사용하는가:
            OpenAI SDK는 stream=True를 지원하며, 토큰이 생성될 때마다
            delta.content로 부분 응답을 받을 수 있다.
            이를 통해 실시간 진행률 표시가 가능하다.
        """
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
            "stream": True,
            "max_completion_tokens": max_tokens,
        }
        if response_format == "json":
            create_kwargs["response_format"] = {"type": "json_object"}

        t0 = time.monotonic()
        full_text = ""
        tokens_out = 0
        last_report = t0

        try:
            stream = await client.chat.completions.create(**create_kwargs)
        except openai.BadRequestError as e:
            if "max_completion_tokens" in str(e):
                del create_kwargs["max_completion_tokens"]
                create_kwargs["max_tokens"] = max_tokens
                stream = await client.chat.completions.create(**create_kwargs)
            else:
                raise

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                full_text += delta.content
                tokens_out += 1

                now = time.monotonic()
                if progress_callback and (now - last_report) >= 1.0:
                    last_report = now
                    progress_callback({
                        "type": "progress",
                        "elapsed_sec": round(now - t0, 1),
                        "tokens": tokens_out,
                        "provider": self.provider_id,
                    })

        elapsed = time.monotonic() - t0

        return LlmResponse(
            text=full_text,
            provider=self.provider_id,
            model=selected_model,
            tokens_in=None,
            tokens_out=tokens_out,
            cost_usd=self._estimate_cost(selected_model, None, tokens_out),
            elapsed_sec=round(elapsed, 2),
            raw={"stream": True},
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
        try:
            response = await client.chat.completions.create(
                model=selected_model,
                messages=messages,
                max_completion_tokens=max_tokens,
            )
        except openai.BadRequestError as e:
            if "max_completion_tokens" in str(e):
                response = await client.chat.completions.create(
                    model=selected_model,
                    messages=messages,
                    max_tokens=max_tokens,
                )
            else:
                raise
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
