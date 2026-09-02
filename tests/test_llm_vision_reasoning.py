"""비전 경로 추론 출력 보장 테스트 (D-083).

무엇을 고정하는가:
  - 사고 예산은 답변 예산에 **더해진다** (프로바이더 4종)
  - 비전 경로도 JSON 형식을 강제한다 (Ollama format / Gemini mime / OpenAI response_format)
  - 잘림(done_reason / finish_reason / stop_reason)은 예외로 드러난다
  - Anthropic은 thinking 블록이 아니라 text 블록만 본문으로 삼는다
  - LlmOcrEngine 사다리: 사고 켠 호출이 잘리면 사고를 끄고 재시도, thinking 폴백은 없다

왜 서버 없이 시험하는가:
  이 환경(그리고 CI)에는 Ollama도 API 키도 없다. 페이로드 조립과 응답 해석은
  순수 함수로 떼어 놓았으므로 네트워크 한 줄만 바꿔 끼우면 나머지를 전부 검사할
  수 있다. D-073의 교훈 — «분기가 존재만 하고 한 번도 실행되지 않는» 상태를
  남기지 않는다.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from llm.providers.anthropic_provider import AnthropicProvider  # noqa: E402
from llm.providers.base import (  # noqa: E402
    DEFAULT_THINKING_BUDGET,
    TRUNCATED_MARK,
    LlmProviderError,
    LlmResponse,
    thinking_options,
)
from llm.providers.gemini_provider import GeminiProvider  # noqa: E402
from llm.providers.ollama import OllamaProvider  # noqa: E402
from llm.providers.openai_provider import OpenAiProvider  # noqa: E402
from ocr.base import OcrEngineError  # noqa: E402
from ocr.llm_ocr_engine import OCR_LINES_SCHEMA, LlmOcrEngine  # noqa: E402

# ─── thinking_options ──────────────────────────────────────────────


class TestThinkingOptions:
    def test_unspecified(self):
        assert thinking_options({}) == (None, 0)

    def test_off_has_zero_budget(self):
        assert thinking_options({"think": False, "thinking_budget": 9999}) == (False, 0)

    def test_on_uses_default_budget(self):
        think, budget = thinking_options({"think": True})
        assert think is True and budget == DEFAULT_THINKING_BUDGET

    def test_on_with_budget(self):
        assert thinking_options({"think": True, "thinking_budget": 2048}) == (True, 2048)

    def test_effort_string_counts_as_on(self):
        think, budget = thinking_options({"think": "low"})
        assert think == "low" and budget == DEFAULT_THINKING_BUDGET

    def test_bad_budget_falls_back(self):
        assert (
            thinking_options({"think": True, "thinking_budget": "abc"})[1]
            == DEFAULT_THINKING_BUDGET
        )


# ─── Ollama ──────────────────────────────────────────────────────


class _FakeConfig:
    def get(self, key, default=None):
        return {"ollama_url": "http://fake:11434"}.get(key, default)

    def get_api_key(self, name):
        return None


def _ollama_with_reply(reply: dict, captured: list) -> OllamaProvider:
    prov = OllamaProvider(_FakeConfig())

    async def fake_post(payload, *, label="Ollama"):
        captured.append(payload)
        return reply

    prov._post_generate = fake_post  # type: ignore[method-assign]
    return prov


class TestOllamaVision:
    def test_budget_added_and_schema_sent(self):
        captured: list = []
        prov = _ollama_with_reply(
            {"response": '{"lines":[{"text":"王戎"}]}', "done_reason": "stop"}, captured
        )
        resp = asyncio.run(
            prov.call_with_image(
                "p",
                b"img",
                model="m",
                max_tokens=1000,
                response_format="json",
                json_schema=OCR_LINES_SCHEMA,
                think=True,
                thinking_budget=3000,
            )
        )
        payload = captured[0]
        assert payload["options"]["num_predict"] == 4000  # 1000 + 3000
        assert payload["think"] is True
        assert payload["format"] == OCR_LINES_SCHEMA  # "json" 문자열이 아니라 스키마 객체
        assert resp.text.startswith('{"lines"')

    def test_think_off_keeps_budget_zero(self):
        captured: list = []
        prov = _ollama_with_reply({"response": "{}", "done_reason": "stop"}, captured)
        asyncio.run(
            prov.call_with_image(
                "p",
                b"img",
                model="m",
                max_tokens=1000,
                think=False,
                thinking_budget=5000,
                response_format="json",
            )
        )
        assert captured[0]["options"]["num_predict"] == 1000
        assert captured[0]["think"] is False
        assert captured[0]["format"] == "json"  # 스키마를 안 주면 "json"

    def test_effort_string_passthrough(self):
        captured: list = []
        prov = _ollama_with_reply({"response": "x", "done_reason": "stop"}, captured)
        asyncio.run(prov.call_with_image("p", b"img", model="gpt-oss", think="low"))
        assert captured[0]["think"] == "low"

    def test_unspecified_think_not_in_payload(self):
        captured: list = []
        prov = _ollama_with_reply({"response": "x", "done_reason": "stop"}, captured)
        asyncio.run(prov.call_with_image("p", b"img", model="m"))
        assert "think" not in captured[0]
        assert "format" not in captured[0]

    def test_truncation_raises_with_mark(self):
        prov = _ollama_with_reply({"response": '{"lines":[{"te', "done_reason": "length"}, [])
        with pytest.raises(LlmProviderError) as ei:
            asyncio.run(prov.call_with_image("p", b"img", model="m", response_format="json"))
        assert TRUNCATED_MARK in str(ei.value)

    def test_empty_json_output_raises(self):
        """JSON을 요구했는데 비면 실패 — 다른 프로바이더와 같은 규칙."""
        prov = _ollama_with_reply({"response": "", "done_reason": "stop"}, [])
        with pytest.raises(LlmProviderError) as ei:
            asyncio.run(prov.call_with_image("p", b"img", model="m", response_format="json"))
        assert "empty" in str(ei.value)

    def test_thinking_fallback_disabled_returns_empty(self):
        """allow_thinking_fallback=False면 사고문을 본문으로 쓰지 않는다 (D-074 유지)."""
        prov = _ollama_with_reply(
            {"response": "", "thinking": "The user wants...", "done_reason": "stop"}, []
        )
        resp = asyncio.run(
            prov.call_with_image("p", b"img", model="m", allow_thinking_fallback=False)
        )
        assert resp.text == ""


# ─── Gemini ──────────────────────────────────────────────────────


class TestGeminiThinkingConfig:
    class _Types:
        class ThinkingConfig:
            def __init__(self, thinking_budget=None, include_thoughts=None):
                self.thinking_budget = thinking_budget
                self.include_thoughts = include_thoughts

    def test_unspecified_leaves_model_default(self):
        assert (
            GeminiProvider._build_thinking_config(self._Types, "gemini-2.5-flash", None, 0) is None
        )

    def test_off_sets_zero_budget_on_flash(self):
        cfg = GeminiProvider._build_thinking_config(self._Types, "gemini-2.5-flash", False, 0)
        assert cfg is not None and cfg.thinking_budget == 0

    def test_off_on_pro_is_left_alone(self):
        """Pro 계열은 예산 0을 거부한다 — 억지로 보내면 호출이 죽는다."""
        assert (
            GeminiProvider._build_thinking_config(self._Types, "gemini-2.5-pro", False, 0) is None
        )

    def test_on_sets_budget_and_hides_thoughts(self):
        cfg = GeminiProvider._build_thinking_config(self._Types, "gemini-2.5-flash", True, 2048)
        assert cfg.thinking_budget == 2048 and cfg.include_thoughts is False

    def test_missing_sdk_class(self):
        assert GeminiProvider._build_thinking_config(SimpleNamespace(), "m", True, 100) is None


# ─── OpenAI ──────────────────────────────────────────────────────


class TestOpenAiVisionKwargs:
    def test_json_and_budget(self):
        kw = OpenAiProvider._vision_create_kwargs("gpt-4o", [], 1000 + 3000, "json", None)
        assert kw["max_completion_tokens"] == 4000
        assert kw["response_format"] == {"type": "json_object"}
        assert "reasoning_effort" not in kw

    def test_non_reasoning_model_never_gets_effort(self):
        kw = OpenAiProvider._vision_create_kwargs("gpt-4o", [], 100, "text", True)
        assert "reasoning_effort" not in kw

    def test_reasoning_model_effort_mapping(self):
        def eff(model, think):
            return OpenAiProvider._vision_create_kwargs(model, [], 1, "text", think).get(
                "reasoning_effort"
            )

        assert eff("gpt-5", True) == "medium"
        assert eff("gpt-5", False) == "minimal"
        assert eff("gpt-5-mini-2025-08-07", False) == "minimal"
        # gpt-5.1·5.2는 minimal을 거부한다 — 최소치 low로
        assert eff("gpt-5.2", False) == "low"
        assert eff("o3", False) == "low"
        assert eff("o4-mini", "high") == "high"
        assert eff("gpt-4o", False) is None


# ─── Anthropic ───────────────────────────────────────────────────


class TestAnthropicVision:
    def test_text_blocks_only(self):
        content = [
            SimpleNamespace(type="thinking", thinking="let me think"),
            SimpleNamespace(type="text", text='{"lines":'),
            SimpleNamespace(type="text", text="[]}"),
        ]
        assert AnthropicProvider._text_from_content(content) == '{"lines":[]}'

    def test_thinking_only_is_empty_not_contaminated(self):
        content = [SimpleNamespace(type="thinking", thinking="The user wants me to...")]
        assert AnthropicProvider._text_from_content(content) == ""

    def test_kwargs_with_thinking(self):
        kw = AnthropicProvider._vision_create_kwargs("claude", [], "sys", 1000, True, 3000)
        assert kw["max_tokens"] == 4000 and kw["thinking"] == {
            "type": "enabled",
            "budget_tokens": 3000,
        }

    def test_kwargs_min_budget_1024(self):
        kw = AnthropicProvider._vision_create_kwargs("claude", [], None, 400, True, 100)
        assert kw["thinking"]["budget_tokens"] == 1024
        assert kw["max_tokens"] > kw["thinking"]["budget_tokens"]  # API 불변식

    def test_kwargs_without_thinking(self):
        kw = AnthropicProvider._vision_create_kwargs("claude", [], None, 1000, False, 0)
        assert kw["max_tokens"] == 1000 and "thinking" not in kw


# ─── LlmOcrEngine 사다리 ─────────────────────────────────────────


class _FakeVisionRouter:
    """호출 순서를 기록하고, 정해진 응답 대본을 차례로 돌려주는 가짜 라우터."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []
        self.providers = [SimpleNamespace(supports_image=True)]

    async def call_with_image(self, prompt, image, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return LlmResponse(text=item, provider="fake", model="m")


class TestEnginePlan:
    def test_default_is_think_off_single_then_double(self):
        plan = LlmOcrEngine._plan_attempts({})
        assert plan == [{"think": False, "max_tokens": 4096}, {"think": False, "max_tokens": 8192}]

    def test_think_on_adds_think_off_step(self):
        plan = LlmOcrEngine._plan_attempts(
            {"think": True, "thinking_budget": 2048, "max_tokens": 1000}
        )
        assert plan[0] == {"think": True, "max_tokens": 1000, "thinking_budget": 2048}
        assert plan[1] == {"think": False, "max_tokens": 1000}
        assert plan[2] == {"think": False, "max_tokens": 2000}


class TestEngineLadder:
    def test_truncated_with_think_falls_back_to_no_think(self):
        router = _FakeVisionRouter(
            [
                LlmProviderError(f"Ollama vision 출력이 잘렸습니다 ({TRUNCATED_MARK})"),
                '{"lines":[{"text":"王戎簡要"}]}',
            ]
        )
        engine = LlmOcrEngine(router)
        result = engine.recognize(b"img", think=True, thinking_budget=2048)
        assert [c["think"] for c in router.calls] == [True, False]
        assert router.calls[0]["thinking_budget"] == 2048
        assert "thinking_budget" not in router.calls[1]
        assert result.lines[0].text == "王戎簡要"
        # 모든 시도에서 형식 강제·폴백 금지는 변하지 않는다
        for c in router.calls:
            assert c["response_format"] == "json"
            assert c["json_schema"] is OCR_LINES_SCHEMA
            assert c["allow_thinking_fallback"] is False

    def test_non_truncation_error_is_not_retried(self):
        router = _FakeVisionRouter([LlmProviderError("rate limit 429"), "unused"])
        engine = LlmOcrEngine(router)
        with pytest.raises(OcrEngineError):
            engine.recognize(b"img", think=True)
        assert len(router.calls) == 1

    def test_all_truncated_fails_loudly(self):
        router = _FakeVisionRouter([LlmProviderError(TRUNCATED_MARK)] * 3)
        engine = LlmOcrEngine(router)
        with pytest.raises(OcrEngineError) as ei:
            engine.recognize(b"img", think=True)
        assert "잘렸" in str(ei.value)
        assert [c["max_tokens"] for c in router.calls] == [4096, 4096, 8192]

    def test_default_call_is_think_off(self):
        router = _FakeVisionRouter(['{"lines":[{"text":"甲"}]}'])
        engine = LlmOcrEngine(router)
        engine.recognize(b"img")
        assert router.calls[0]["think"] is False


# ─── 라우터: 잘림은 폴백 대상이 아니다 ──────────────────────────


class _TruncatingProvider:
    provider_id = "ollama"
    supports_image = True

    def __init__(self, log):
        self.log = log

    async def is_available(self):
        return True

    async def call_with_image(self, prompt, image, **kwargs):
        self.log.append(("ollama", kwargs.get("think")))
        raise LlmProviderError(f"Ollama vision 출력이 잘렸습니다 ({TRUNCATED_MARK})")


class _PaidProvider:
    provider_id = "gemini"
    supports_image = True

    def __init__(self, log):
        self.log = log

    async def is_available(self):
        return True

    async def call_with_image(self, prompt, image, **kwargs):
        self.log.append(("gemini", kwargs.get("think")))
        return LlmResponse(text='{"lines":[]}', provider="gemini", model="m")


class TestRouterTruncationFallback:
    def _router(self, log):
        from llm.config import LlmConfig
        from llm.router import LlmRouter

        router = LlmRouter(LlmConfig())
        router.providers = [_TruncatingProvider(log), _PaidProvider(log)]
        router._avail_cache = {}
        return router

    def test_default_falls_back_to_next_provider(self):
        log: list = []
        router = self._router(log)
        resp = asyncio.run(router.call_with_image("p", b"img", think=True))
        assert resp.provider == "gemini"

    def test_no_fallback_flag_raises_so_engine_can_retry_same_provider(self):
        log: list = []
        router = self._router(log)
        with pytest.raises(LlmProviderError):
            asyncio.run(
                router.call_with_image("p", b"img", think=True, fallback_on_truncation=False)
            )
        assert log == [("ollama", True)]  # 유료 프로바이더는 호출되지 않았다

    def test_engine_ladder_stays_on_same_provider(self):
        """엔진 사다리: 잘림 → 사고 끔 재시도가 같은(무료) 프로바이더에서 돈다."""
        log: list = []
        router = self._router(log)
        engine = LlmOcrEngine(router)
        with pytest.raises(OcrEngineError):
            engine.recognize(b"img", think=True)
        assert all(p == "ollama" for p, _ in log)
        assert [t for _, t in log] == [True, False, False]
