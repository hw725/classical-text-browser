"""OpenAI Provider.

OpenAI Chat Completions API 호출.
비전(이미지 분석) 지원.

환경변수: OPENAI_API_KEY
"""

import base64
import logging
import re
import time
from typing import Optional

from .base import (
    TRUNCATED_MARK,
    BaseLlmProvider,
    LlmProviderError,
    LlmResponse,
    thinking_options,
)


class OpenAiProvider(BaseLlmProvider):
    """OpenAI API 호출. 비전 포함."""

    provider_id = "openai"
    display_name = "OpenAI"
    supports_image = True
    billing_model = "metered"  # 쓴 만큼 과금된다
    DEFAULT_MODEL = "gpt-5.4-mini"  # 비용 효율적 기본 모델 (2026-09 기준 mini 최신)

    # 키는 화면(설정 ▸ LLM 연결)에서 넣는다 — 서고 .env에 저장된다(D-102).
    setup_kind = "env_key"
    setup_steps = (
        "https://platform.openai.com/api-keys 에서 키 발급",
        "설정 ▸ LLM 연결의 입력 칸에 붙여 넣고 「저장」",
    )

    def _create_client(self):
        """AsyncOpenAI 클라이언트 생성.

        서브클래스(예: OpenAiOAuthProvider)에서 오버라이드하여
        base_url이나 인증 방식을 변경할 수 있다.
        """
        import openai

        api_key = self.config.get_api_key("openai")
        if not api_key:
            raise LlmProviderError("OPENAI_API_KEY가 설정되지 않았습니다.")
        return openai.AsyncOpenAI(api_key=api_key)

    # 모델 목록은 API(/v1/models)에서 받는다 — 손으로 적은 목록은 반년이면 낡는다(2026-09-05:
    # gpt-5.6까지 나왔는데 목록은 gpt-5.2까지였다). 아래는 API를 못 부를 때의 폴백이자
    # 가격·비전 힌트다. 가격(1K 토큰당 USD)은 공식 표에서 확인한 것만 적는다 —
    # 없는 모델은 _estimate_cost의 기본값으로 추정한다. 출처: https://platform.openai.com/docs/pricing
    MODELS = [
        {
            "name": "gpt-5-nano",
            "vision": True,
            "cost": "lowest",
            "input": 0.00005,
            "output": 0.0004,
        },
        {"name": "gpt-5-mini", "vision": True, "cost": "low", "input": 0.00025, "output": 0.002},
        {"name": "gpt-5.4-mini", "vision": True, "cost": "low"},
        {"name": "gpt-5", "vision": True, "cost": "medium", "input": 0.00125, "output": 0.01},
        {"name": "gpt-5.4", "vision": True, "cost": "medium"},
        {"name": "gpt-5.2", "vision": True, "cost": "high", "input": 0.00175, "output": 0.014},
        {"name": "gpt-5.5", "vision": True, "cost": "high"},
        {"name": "gpt-5.6", "vision": True, "cost": "high"},
        {"name": "gpt-4.1", "vision": True, "cost": "high", "input": 0.002, "output": 0.008},
    ]

    # 가격표 (1K tokens 기준, USD) — 가격이 확인된 것만
    PRICING = {
        m["name"]: {"input": m["input"], "output": m["output"]} for m in MODELS if "input" in m
    }

    # API 목록에서 남길 것: 대화 모델. 실시간·음성·이미지 생성·임베딩·검색 전용은 뺀다.
    _MODEL_KEEP = re.compile(r"^(gpt-5|gpt-4\.1|o[1-9])")
    _MODEL_DROP = re.compile(
        r"realtime|audio|tts|transcribe|image|embedding|moderation|search|codex|instruct"
    )
    _DATED = re.compile(r"-20\d\d-\d\d-\d\d$")
    _models_cache: Optional[tuple[float, list[dict]]] = None
    _MODELS_TTL = 600.0

    async def is_available(self) -> bool:
        """OPENAI_API_KEY가 설정되어 있는지 확인."""
        return bool(self.config.get_api_key("openai"))

    async def list_models(self) -> list[dict]:
        """드롭다운용 모델 목록 — API에서 받고, 못 받으면 MODELS. 10분 동안 기억한다.

        날짜 접미 판(gpt-5-mini-2025-08-07)은 별칭이 따로 있으므로 뺀다.
        """
        now = time.time()
        if self._models_cache and now - self._models_cache[0] < self._MODELS_TTL:
            return self._models_cache[1]
        known = {m["name"]: m for m in self.MODELS}
        result: Optional[list[dict]] = None
        try:
            client = self._create_client()
            page = await client.models.list()
            ids = sorted(
                {
                    m.id
                    for m in page.data
                    if self._MODEL_KEEP.match(m.id)
                    and not self._MODEL_DROP.search(m.id)
                    and not self._DATED.search(m.id)
                },
                reverse=True,
            )
            if ids:
                result = [
                    {
                        "name": i,
                        "vision": known.get(i, {}).get("vision", not i.startswith("o")),
                        "cost": known.get(i, {}).get("cost", "unknown"),
                    }
                    for i in ids
                ]
        except Exception as e:  # noqa: BLE001 — 목록을 못 받아도 폴백으로 화면은 뜬다
            logging.getLogger(__name__).debug("OpenAI 모델 목록 조회 실패: %s", e)
        if result is None:
            result = [
                {"name": m["name"], "vision": m["vision"], "cost": m["cost"]} for m in self.MODELS
            ]
        self._models_cache = (now, result)
        return result

    def _estimate_cost(
        self, model: str, tokens_in: Optional[int], tokens_out: Optional[int]
    ) -> float:
        """토큰 수로 비용 추정."""
        pricing = self.PRICING.get(model, {"input": 0.0004, "output": 0.0016})
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
        """OpenAI Chat Completions API로 텍스트 생성."""
        import openai

        client = self._create_client()
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

        choice = response.choices[0] if response.choices else None
        message = choice.message if choice else None
        text = (message.content if message else "") or ""
        finish_reason = getattr(choice, "finish_reason", None) if choice else None
        finish_reason_s = str(finish_reason or "").lower()

        if response_format == "json" and finish_reason_s in ("length", "max_tokens"):
            raise LlmProviderError(
                f"OpenAI JSON output truncated (finish_reason={finish_reason_s}, "
                f"max_tokens={max_tokens})"
            )
        if response_format == "json" and not text.strip():
            raise LlmProviderError(
                f"OpenAI empty JSON output (finish_reason={finish_reason_s}, "
                f"max_tokens={max_tokens})"
            )

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
            raw={"id": response.id, "finish_reason": finish_reason_s},
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
        """OpenAI 네이티브 스트리밍. stream=True로 청크 단위 수신.

        왜 네이티브 스트리밍을 사용하는가:
            OpenAI SDK는 stream=True를 지원하며, 토큰이 생성될 때마다
            delta.content로 부분 응답을 받을 수 있다.
            이를 통해 실시간 진행률 표시가 가능하다.
        """
        import openai

        client = self._create_client()
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
        finish_reason = ""

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
            choice = chunk.choices[0] if chunk.choices else None
            if choice and getattr(choice, "finish_reason", None):
                finish_reason = str(choice.finish_reason).lower()
            delta = choice.delta if choice else None
            if delta and delta.content:
                full_text += delta.content
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

        if response_format == "json" and finish_reason in ("length", "max_tokens"):
            raise LlmProviderError(
                f"OpenAI stream JSON output truncated (finish_reason={finish_reason}, "
                f"max_tokens={max_tokens})"
            )
        if response_format == "json" and not full_text.strip():
            raise LlmProviderError(
                f"OpenAI stream empty JSON output (finish_reason={finish_reason}, "
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
            raw={"stream": True, "finish_reason": finish_reason},
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
        """OpenAI Vision으로 이미지 분석.

        이미지는 base64 data URI로 전달한다.
        """
        import openai

        client = self._create_client()
        selected_model = model or self.DEFAULT_MODEL

        b64_data = base64.b64encode(image).decode("ascii")
        data_uri = f"data:{image_mime};base64,{b64_data}"

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": data_uri},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        )

        # 사고 예산을 답변 예산에 더한다 (D-083). OpenAI 추론 모델은 추론 토큰이
        # max_completion_tokens 안에서 소모된다. 사고 강도는 reasoning_effort로
        # 조절하는데, 추론 모델이 아닌 곳에 보내면 400이 나므로 모델을 가려 보낸다.
        think, thinking_budget = thinking_options(kwargs)
        create_kwargs = self._vision_create_kwargs(
            selected_model, messages, max_tokens + thinking_budget, response_format, think
        )

        t0 = time.monotonic()
        try:
            response = await client.chat.completions.create(**create_kwargs)
        except openai.BadRequestError as e:
            if "max_completion_tokens" in str(e):
                create_kwargs["max_tokens"] = create_kwargs.pop("max_completion_tokens")
                response = await client.chat.completions.create(**create_kwargs)
            else:
                raise
        elapsed = time.monotonic() - t0

        choice = response.choices[0] if response.choices else None
        text = (choice.message.content if choice else "") or ""
        finish_reason = str(getattr(choice, "finish_reason", "") or "").lower()
        # 잘림·빈 응답은 실패로 드러낸다 (D-083 원칙 3). 텍스트 경로와 동일.
        if response_format == "json" and finish_reason in ("length", "max_tokens"):
            raise LlmProviderError(
                f"OpenAI vision JSON output {TRUNCATED_MARK} (finish_reason={finish_reason}, "
                f"max_tokens={max_tokens}, thinking_budget={thinking_budget})"
            )
        if response_format == "json" and not text.strip():
            raise LlmProviderError(
                f"OpenAI vision empty JSON output (finish_reason={finish_reason}, "
                f"max_tokens={max_tokens})"
            )
        tokens_in = response.usage.prompt_tokens if response.usage else None
        tokens_out = response.usage.completion_tokens if response.usage else None

        return LlmResponse(
            text=text,
            provider=self.provider_id,
            model=response.model or selected_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=self._estimate_cost(selected_model, tokens_in, tokens_out),
            elapsed_sec=round(elapsed, 2),
            raw={"id": response.id, "finish_reason": finish_reason},
        )

    @staticmethod
    def _is_reasoning_model(model: str) -> bool:
        """reasoning_effort를 받는 모델인가. o-계열과 gpt-5 계열만 받는다."""
        name = (model or "").lower()
        return name.startswith(("o1", "o3", "o4", "gpt-5"))

    @classmethod
    def _vision_create_kwargs(
        cls, model: str, messages: list, max_completion_tokens: int, response_format: str, think
    ) -> dict:
        """비전 호출 인자를 조립한다. 순수 함수라 테스트로 고정한다.

        입력: 모델, 메시지, 상한(답변+사고), 응답 형식, think(None|bool|str)
        출력: client.chat.completions.create(**kwargs)에 넘길 dict

        reasoning_effort 대응:
          - think=None        → 보내지 않는다 (모델 기본)
          - think=False       → gpt-5/-mini/-nano는 "minimal", 그 외 추론 모델은 "low"(최소치)
          - think=True        → "medium"
          - think="low" 등    → 그대로
          추론 모델이 아니면 어떤 경우에도 보내지 않는다 — 400으로 호출이 죽는다.
        """
        kwargs = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": max_completion_tokens,
        }
        if response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}
        if think is not None and cls._is_reasoning_model(model):
            if isinstance(think, str):
                kwargs["reasoning_effort"] = think
            elif think:
                kwargs["reasoning_effort"] = "medium"
            else:
                kwargs["reasoning_effort"] = "minimal" if cls._accepts_minimal(model) else "low"
        return kwargs

    @staticmethod
    def _accepts_minimal(model: str) -> bool:
        """reasoning_effort="minimal"을 받는 모델인가.

        gpt-5·gpt-5-mini·gpt-5-nano(및 날짜 접미 판)만 받는다. gpt-5.1·5.2는
        none|low|medium|high 계열이라 "minimal"을 거부한다(400). 사고 끔이 OCR의
        기본값이라 이 판정이 틀리면 기본 경로가 통째로 죽는다.
        """
        name = (model or "").lower()
        base = name.split("-20", 1)[0]  # 날짜 접미 제거: gpt-5-mini-2025-08-07 → gpt-5-mini
        return base in ("gpt-5", "gpt-5-mini", "gpt-5-nano")
