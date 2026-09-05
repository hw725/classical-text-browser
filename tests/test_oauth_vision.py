"""OpenAI(OAuth) 비전은 Responses API로 간다.

프록시가 chat.completions의 data: URL을 거부한다(2026-09-06, D-110).
"""

import asyncio
from types import SimpleNamespace

import pytest

from llm.config import LlmConfig
from llm.providers.openai_oauth_provider import OpenAiOAuthProvider


class _FakeResponses:
    def __init__(self, log):
        self.log = log

    async def create(self, **req):
        self.log.append(req)
        return SimpleNamespace(
            output_text='{"text":"hi"}', status="completed", incomplete_details=None,
            usage=SimpleNamespace(input_tokens=5, output_tokens=3), model="gpt-5.4-mini", id="r1",
        )


class _FakeClient:
    def __init__(self, log):
        self.responses = _FakeResponses(log)


def test_vision_uses_responses_api_with_input_image(monkeypatch):
    log = []
    p = OpenAiOAuthProvider(LlmConfig())
    monkeypatch.setattr(p, "_create_client", lambda: _FakeClient(log))
    r = asyncio.run(
        p.call_with_image("read", b"PNGDATA", response_format="json", model="gpt-5.4-mini")
    )
    assert r.text == '{"text":"hi"}' and r.provider == "openai_oauth" and r.cost_usd == 0.0
    req = log[0]
    content = req["input"][0]["content"]
    assert content[0]["type"] == "input_image"
    assert content[0]["image_url"].startswith("data:image/png;base64,")
    assert content[1] == {"type": "input_text", "text": "read"}
    assert req["text"] == {"format": {"type": "json_object"}}


def test_truncated_json_is_an_error(monkeypatch):
    class _Trunc(_FakeResponses):
        async def create(self, **req):
            return SimpleNamespace(
                output_text="{",
                status="incomplete",
                incomplete_details=SimpleNamespace(reason="max_output_tokens"),
                usage=None,
                model="m",
                id="r2",
            )

    p = OpenAiOAuthProvider(LlmConfig())
    monkeypatch.setattr(p, "_create_client", lambda: SimpleNamespace(responses=_Trunc([])))
    with pytest.raises(Exception, match="truncated"):
        asyncio.run(p.call_with_image("read", b"x", response_format="json"))
