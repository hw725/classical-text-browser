"""Gemini Provider.

Google Gemini API 호출 (google-genai SDK).
비전(이미지 분석) 지원.

환경변수: GOOGLE_API_KEY
"""

import time
from typing import Optional

from .base import BaseLlmProvider, LlmProviderError, LlmResponse


class GeminiProvider(BaseLlmProvider):
    """Google Gemini API 호출. 비전 포함."""

    provider_id = "gemini"
    display_name = "Google Gemini"
    supports_image = True
    DEFAULT_MODEL = "gemini-2.5-flash"  # 비용 효율적 기본 모델

    # 주요 모델 목록 (2026-02 기준)
    # Gemini 3 시리즈는 preview 상태. 안정성이 필요하면 2.5 사용.
    MODELS = [
        {"name": "gemini-2.5-flash", "vision": True, "cost": "lowest",
         "input": 0.00015, "output": 0.0006},
        {"name": "gemini-2.5-pro", "vision": True, "cost": "low",
         "input": 0.00125, "output": 0.01},
        {"name": "gemini-3-flash-preview", "vision": True, "cost": "low",
         "input": 0.00015, "output": 0.0006},
        {"name": "gemini-3-pro-preview", "vision": True, "cost": "medium",
         "input": 0.00125, "output": 0.01},
        {"name": "gemini-3.1-pro-preview", "vision": True, "cost": "high",
         "input": 0.00125, "output": 0.01},
    ]

    PRICING = {m["name"]: {"input": m["input"], "output": m["output"]} for m in MODELS}

    async def is_available(self) -> bool:
        """GOOGLE_API_KEY가 설정되어 있는지 확인."""
        return bool(self.config.get_api_key("gemini"))

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
            model, {"input": 0.00015, "output": 0.0006}
        )
        cost = (
            (tokens_in or 0) / 1000 * pricing["input"]
            + (tokens_out or 0) / 1000 * pricing["output"]
        )
        return round(cost, 6)

    async def call(self, prompt, *, system=None, response_format="text",
                   model=None, max_tokens=4096, purpose="text",
                   **kwargs) -> LlmResponse:
        """Gemini API로 텍스트 생성.

        google-genai SDK의 비동기 인터페이스 사용:
          client.aio.models.generate_content()
        """
        from google import genai
        from google.genai import types

        api_key = self.config.get_api_key("gemini")
        if not api_key:
            raise LlmProviderError("GOOGLE_API_KEY가 설정되지 않았습니다.")

        client = genai.Client(api_key=api_key)
        selected_model = model or self.DEFAULT_MODEL

        # Gemini는 system_instruction을 별도 파라미터로 받음
        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
        )
        if system:
            config.system_instruction = system
        if response_format == "json":
            config.response_mime_type = "application/json"

        t0 = time.monotonic()
        response = await client.aio.models.generate_content(
            model=selected_model,
            contents=prompt,
            config=config,
        )
        elapsed = time.monotonic() - t0

        text = response.text or ""
        tokens_in = getattr(response.usage_metadata, "prompt_token_count", None)
        tokens_out = getattr(response.usage_metadata, "candidates_token_count", None)

        return LlmResponse(
            text=text,
            provider=self.provider_id,
            model=selected_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=self._estimate_cost(selected_model, tokens_in, tokens_out),
            elapsed_sec=round(elapsed, 2),
            raw={"model": selected_model},
        )

    async def call_stream(
        self, prompt, *, system=None, response_format="text",
        model=None, max_tokens=4096, purpose="text",
        progress_callback=None, **kwargs,
    ) -> LlmResponse:
        """Gemini 네이티브 스트리밍. generate_content_stream() 사용.

        왜 네이티브 스트리밍을 사용하는가:
            google-genai SDK >=1.0.0은 generate_content_stream()을 지원한다.
            청크가 도착할 때마다 진행률을 전달하여 실시간 피드백이 가능하다.
            SDK 버전이 낮아 메서드가 없으면 기본 heartbeat 폴백으로 자동 전환한다.
        """
        from google import genai
        from google.genai import types

        api_key = self.config.get_api_key("gemini")
        if not api_key:
            raise LlmProviderError("GOOGLE_API_KEY가 설정되지 않았습니다.")

        client = genai.Client(api_key=api_key)
        selected_model = model or self.DEFAULT_MODEL

        # generate_content_stream 메서드 확인 — 없으면 heartbeat 폴백
        if not hasattr(client.aio.models, "generate_content_stream"):
            return await super().call_stream(
                prompt, system=system, response_format=response_format,
                model=model, max_tokens=max_tokens, purpose=purpose,
                progress_callback=progress_callback, **kwargs,
            )

        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
        )
        if system:
            config.system_instruction = system
        if response_format == "json":
            config.response_mime_type = "application/json"

        t0 = time.monotonic()
        full_text = ""
        tokens_out = 0
        last_report = t0

        async for chunk in client.aio.models.generate_content_stream(
            model=selected_model,
            contents=prompt,
            config=config,
        ):
            part_text = chunk.text or ""
            full_text += part_text
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
            raw={"stream": True, "model": selected_model},
        )

    async def call_with_image(self, prompt, image, *, image_mime="image/png",
                              system=None, response_format="text", model=None,
                              max_tokens=4096, **kwargs) -> LlmResponse:
        """Gemini Vision으로 이미지 분석.

        google-genai SDK는 Part(inline_data=...) 형식으로 이미지를 전달한다.
        """
        from google import genai
        from google.genai import types

        api_key = self.config.get_api_key("gemini")
        if not api_key:
            raise LlmProviderError("GOOGLE_API_KEY가 설정되지 않았습니다.")

        client = genai.Client(api_key=api_key)
        selected_model = model or self.DEFAULT_MODEL

        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
        )
        if system:
            config.system_instruction = system

        # 이미지 + 텍스트를 contents로 전달
        contents = [
            types.Part.from_bytes(data=image, mime_type=image_mime),
            prompt,
        ]

        t0 = time.monotonic()
        response = await client.aio.models.generate_content(
            model=selected_model,
            contents=contents,
            config=config,
        )
        elapsed = time.monotonic() - t0

        text = response.text or ""
        tokens_in = getattr(response.usage_metadata, "prompt_token_count", None)
        tokens_out = getattr(response.usage_metadata, "candidates_token_count", None)

        return LlmResponse(
            text=text,
            provider=self.provider_id,
            model=selected_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=self._estimate_cost(selected_model, tokens_in, tokens_out),
            elapsed_sec=round(elapsed, 2),
            raw={"model": selected_model},
        )
