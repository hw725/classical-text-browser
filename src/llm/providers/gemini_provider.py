"""Gemini Provider.

Google Gemini API 호출 (google-genai SDK).
비전(이미지 분석) 지원.

환경변수: GOOGLE_API_KEY
"""

import inspect
import time
from typing import Optional

from .base import (
    TRUNCATED_MARK,
    BaseLlmProvider,
    LlmProviderError,
    LlmResponse,
    thinking_options,
)


class GeminiProvider(BaseLlmProvider):
    """Google Gemini API 호출. 비전 포함."""

    provider_id = "gemini"
    display_name = "Google Gemini"
    supports_image = True
    billing_model = "metered"  # 쓴 만큼 과금된다
    DEFAULT_MODEL = "gemini-2.5-flash"  # 비용 효율적 기본 모델

    # 배포판에서는 각자 자기 키를 .env에 넣는다.
    setup_kind = "env_key"
    setup_steps = (
        "https://aistudio.google.com/apikey 에서 키 발급",
        ".env에 GOOGLE_API_KEY=... 를 적고 서버 재시작",
    )

    # 주요 모델 목록 (2026-02 기준)
    # Gemini 3 시리즈는 preview 상태. 안정성이 필요하면 2.5 사용.
    MODELS = [
        {
            "name": "gemini-2.5-flash",
            "vision": True,
            "cost": "lowest",
            "input": 0.00015,
            "output": 0.0006,
        },
        {"name": "gemini-2.5-pro", "vision": True, "cost": "low", "input": 0.00125, "output": 0.01},
        {
            "name": "gemini-3-flash-preview",
            "vision": True,
            "cost": "low",
            "input": 0.00015,
            "output": 0.0006,
        },
        {
            "name": "gemini-3-pro-preview",
            "vision": True,
            "cost": "medium",
            "input": 0.00125,
            "output": 0.01,
        },
        {
            "name": "gemini-3.1-pro-preview",
            "vision": True,
            "cost": "high",
            "input": 0.00125,
            "output": 0.01,
        },
    ]

    PRICING = {m["name"]: {"input": m["input"], "output": m["output"]} for m in MODELS}

    @staticmethod
    def _normalize_finish_reason(reason) -> str:
        if reason is None:
            return ""
        if hasattr(reason, "name"):
            reason = reason.name
        return str(reason).strip().lower()

    @classmethod
    def _extract_finish_reason(cls, response_obj) -> str:
        candidates = getattr(response_obj, "candidates", None) or []
        if not candidates:
            return ""
        reason = getattr(candidates[0], "finish_reason", None)
        return cls._normalize_finish_reason(reason)

    @staticmethod
    def _is_truncated_finish_reason(reason: str) -> bool:
        if not reason:
            return False
        return any(token in reason for token in ("max_tokens", "length", "token_limit"))

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

    def _estimate_cost(
        self, model: str, tokens_in: Optional[int], tokens_out: Optional[int]
    ) -> float:
        """토큰 수로 비용 추정."""
        pricing = self.PRICING.get(model, {"input": 0.00015, "output": 0.0006})
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
        # 사고 예산을 답변 예산에 더한다 (D-083) — 비전 경로와 같은 회계.
        # 텍스트 경로가 이것을 빠뜨려서, 목차 구조화(D-089)에서 2.5 flash가 기본 사고로
        # max_output_tokens 4096을 삼키고 한 쪽(30행)의 JSON도 잘렸다(실측 2026-09-03).
        # JSON을 요구하는 호출은 think를 지정하지 않았으면 «끔»으로 본다 — 기본 사고 끔(D-074).
        think, thinking_budget = thinking_options(kwargs)
        if think is None and response_format == "json":
            think, thinking_budget = False, 0
        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens + thinking_budget,
        )
        if system:
            config.system_instruction = system
        if response_format == "json":
            config.response_mime_type = "application/json"
        thinking_config = self._build_thinking_config(types, selected_model, think, thinking_budget)
        if thinking_config is not None:
            config.thinking_config = thinking_config

        t0 = time.monotonic()
        response = await client.aio.models.generate_content(
            model=selected_model,
            contents=prompt,
            config=config,
        )
        elapsed = time.monotonic() - t0

        text = response.text or ""
        finish_reason = self._extract_finish_reason(response)
        if response_format == "json" and self._is_truncated_finish_reason(finish_reason):
            raise LlmProviderError(
                f"Gemini JSON output truncated (finish_reason={finish_reason}, "
                f"max_tokens={max_tokens})"
            )
        if response_format == "json" and not text.strip():
            raise LlmProviderError(
                f"Gemini empty JSON output (finish_reason={finish_reason}, max_tokens={max_tokens})"
            )
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
            raw={"model": selected_model, "finish_reason": finish_reason},
        )

    async def call_stream(
        self,
        prompt,
        *,
        system=None,
        response_format="text",
        model=None,
        max_tokens=4096,
        purpose="text",
        progress_callback=None,
        **kwargs,
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
                prompt,
                system=system,
                response_format=response_format,
                model=model,
                max_tokens=max_tokens,
                purpose=purpose,
                progress_callback=progress_callback,
                **kwargs,
            )

        # 사고 예산을 답변 예산에 더한다 (D-083) — 비전 경로와 같은 회계.
        # 텍스트 경로가 이것을 빠뜨려서, 목차 구조화(D-089)에서 2.5 flash가 기본 사고로
        # max_output_tokens 4096을 삼키고 한 쪽(30행)의 JSON도 잘렸다(실측 2026-09-03).
        # JSON을 요구하는 호출은 think를 지정하지 않았으면 «끔»으로 본다 — 기본 사고 끔(D-074).
        think, thinking_budget = thinking_options(kwargs)
        if think is None and response_format == "json":
            think, thinking_budget = False, 0
        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens + thinking_budget,
        )
        if system:
            config.system_instruction = system
        if response_format == "json":
            config.response_mime_type = "application/json"
        thinking_config = self._build_thinking_config(types, selected_model, think, thinking_budget)
        if thinking_config is not None:
            config.thinking_config = thinking_config

        t0 = time.monotonic()
        full_text = ""
        tokens_out = 0
        last_report = t0
        finish_reason = ""

        stream_or_coro = client.aio.models.generate_content_stream(
            model=selected_model,
            contents=prompt,
            config=config,
        )

        # SDK 버전에 따라 반환 타입이 다를 수 있다.
        # - async iterator를 바로 반환하는 버전
        # - coroutine을 반환하고 await하면 async iterator가 되는 버전
        if inspect.isawaitable(stream_or_coro):
            stream = await stream_or_coro
        else:
            stream = stream_or_coro

        async for chunk in stream:
            chunk_finish_reason = self._extract_finish_reason(chunk)
            if chunk_finish_reason:
                finish_reason = chunk_finish_reason
            part_text = chunk.text or ""
            full_text += part_text
            tokens_out += 1

            now = time.monotonic()
            if progress_callback and (now - last_report) >= 1.0:
                last_report = now
                progress_callback(
                    {
                        "type": "progress",
                        "elapsed_sec": round(now - t0, 1),
                        "tokens": tokens_out,
                        "provider": self.provider_id,
                    }
                )

        elapsed = time.monotonic() - t0

        if response_format == "json" and self._is_truncated_finish_reason(finish_reason):
            raise LlmProviderError(
                f"Gemini stream JSON output truncated (finish_reason={finish_reason}, "
                f"max_tokens={max_tokens})"
            )
        if response_format == "json" and not full_text.strip():
            raise LlmProviderError(
                f"Gemini stream empty JSON output (finish_reason={finish_reason}, "
                f"max_tokens={max_tokens})"
            )

        return LlmResponse(
            text=full_text,
            provider=self.provider_id,
            model=selected_model,
            tokens_in=None,
            tokens_out=tokens_out,
            cost_usd=self._estimate_cost(selected_model, None, tokens_out),
            elapsed_sec=round(elapsed, 2),
            raw={"stream": True, "model": selected_model, "finish_reason": finish_reason},
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

        # 사고 예산을 답변 예산에 더한다 (D-083).
        # Gemini 2.5 계열은 기본으로 사고하고, 사고 토큰이 max_output_tokens에
        # 포함된다. 그래서 상한을 답변 크기로만 잡으면 사고가 상한을 삼키고
        # 답변이 빈다 — Ollama와 같은 함정이다.
        think, thinking_budget = thinking_options(kwargs)
        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens + thinking_budget,
        )
        if system:
            config.system_instruction = system
        # 답변 형식 강제 — 텍스트 경로와 같은 규칙 (D-033·D-083).
        if response_format == "json":
            config.response_mime_type = "application/json"
        thinking_config = self._build_thinking_config(types, selected_model, think, thinking_budget)
        if thinking_config is not None:
            config.thinking_config = thinking_config

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
        finish_reason = self._extract_finish_reason(response)
        # 잘림·빈 응답은 실패로 드러낸다 (D-083 원칙 3). 텍스트 경로와 동일.
        if response_format == "json" and self._is_truncated_finish_reason(finish_reason):
            raise LlmProviderError(
                f"Gemini vision JSON output {TRUNCATED_MARK} (finish_reason={finish_reason}, "
                f"max_tokens={max_tokens}, thinking_budget={thinking_budget})"
            )
        if response_format == "json" and not text.strip():
            raise LlmProviderError(
                f"Gemini vision empty JSON output (finish_reason={finish_reason}, "
                f"max_tokens={max_tokens})"
            )
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
            raw={"model": selected_model, "finish_reason": finish_reason},
        )

    @staticmethod
    def _build_thinking_config(types_mod, model: str, think, thinking_budget: int):
        """think 요청을 Gemini ThinkingConfig로 옮긴다. 만들 수 없으면 None.

        입력:
          types_mod        — google.genai.types (테스트에서 대체 가능하도록 인자로 받는다)
          model            — 선택된 모델 이름
          think            — thinking_options()가 돌려준 값
          thinking_budget  — 사고 예산(토큰). think가 꺼져 있으면 0
        출력: ThinkingConfig 또는 None

        규칙:
          - think가 None(지정 안 함)이면 모델 기본 동작을 건드리지 않는다.
          - think=False → thinking_budget=0. 단 Pro 계열은 0을 거부하므로(최소치가
            있다) 그 경우는 건드리지 않는다. 억지로 0을 보내면 호출 자체가 실패한다.
          - think 켬 → 예산을 주고 사고문은 응답에 포함하지 않는다
            (include_thoughts=False). 사고문이 본문에 섞이는 것이 D-074의 사고였다.
        """
        thinking_cls = getattr(types_mod, "ThinkingConfig", None)
        if thinking_cls is None or think is None:
            return None
        if think is False:
            if "pro" in (model or "").lower():
                return None
            return thinking_cls(thinking_budget=0)
        return thinking_cls(thinking_budget=thinking_budget, include_thoughts=False)
