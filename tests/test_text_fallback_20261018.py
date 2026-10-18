"""Ollama 글 기본(kimi-k3:cloud)이 없으면 받아 둔 클라우드 글 모델로 대신한다.

D-143 보충, 2026-10-18.

무엇을 지키는가(사용자 결정 《그 순서로 v1.4.4에》):
    1. 기본 kimi-k3:cloud가 설치 목록에 없으면 glm-5.2:cloud → glm-5.3:cloud 순으로
       받아 둔 것을 쓴다.
       대신 쓴 사실은 요청의 폴백 알림(llm.fallback_notice → 화면 토스트)과 서버 경고에 남는다.
    2. 로컬 모델은 자동으로 고르지 않는다 — 후보가 없으면 지금처럼 부르지 않고 다음 순위로 넘어간다.
       (로컬 소형 모델은 품질이 낮다는 사용자 판단, 긴 JSON 답을 깨뜨릴 위험)
    3. 사람이 .env·설정에서 고른 모델이 없으면 대신하지 않는다 — 고른 것을 말없이 바꾸지 않는다.
    4. 스트리밍 호출도 같은 규칙. 설정 카드는 《대신 무엇으로 가는가》를 보인다.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from llm import fallback_notice
from llm.config import LlmConfig
from llm.providers.base import LlmProviderError
from llm.providers.ollama import OllamaProvider


def _provider(monkeypatch, names, env=None):
    monkeypatch.delenv("OLLAMA_TEXT_MODEL", raising=False)
    cfg = LlmConfig()
    cfg._env_cache = {k.upper(): v for k, v in (env or {}).items()}
    p = OllamaProvider(cfg)

    async def models(**kw):
        return [{"name": n} for n in names]

    monkeypatch.setattr(p, "list_models", models)
    calls = []

    async def generate(payload):
        calls.append(payload)
        return {"response": "답"}

    monkeypatch.setattr(p, "_generate", generate)
    return p, calls


def _run_in_request(coro_fn):
    """요청 하나 안에서 돌린 것처럼 폴백 알림 목록을 깔고 돌린다."""
    bucket, token = fallback_notice.begin()
    try:
        result = asyncio.run(coro_fn())
    finally:
        fallback_notice.end(token)
    return result, bucket


def test_missing_default_uses_glm_52_first(monkeypatch):
    p, calls = _provider(monkeypatch, ["glm-5.3:cloud", "glm-5.2:cloud", "qwen3:8b"])
    r, notes = _run_in_request(lambda: p.call("안녕"))
    assert calls[0]["model"] == "glm-5.2:cloud" and r.model == "glm-5.2:cloud"
    assert len(notes) == 1 and "kimi-k3:cloud" in notes[0] and "glm-5.2:cloud" in notes[0]


def test_then_glm_53(monkeypatch):
    p, calls = _provider(monkeypatch, ["glm-5.3:cloud", "gemma4:e4b"])
    asyncio.run(p.call("안녕"))
    assert calls[0]["model"] == "glm-5.3:cloud"


def test_local_models_are_not_picked(monkeypatch):
    p, calls = _provider(monkeypatch, ["qwen3:8b", "gemma4:e4b", "gemma4:cloud"])
    with pytest.raises(LlmProviderError, match="목록에 없"):
        asyncio.run(p.call("안녕"))
    assert calls == []


def test_chosen_model_is_not_substituted(monkeypatch):
    env = {"ollama_text_model": "my-model:cloud"}
    p, calls = _provider(monkeypatch, ["glm-5.2:cloud"], env=env)
    with pytest.raises(LlmProviderError, match="my-model:cloud"):
        asyncio.run(p.call("안녕"))
    assert calls == []


def test_default_present_is_used_without_notice(monkeypatch):
    p, calls = _provider(monkeypatch, ["glm-5.2:cloud", "kimi-k3:cloud"])
    _, notes = _run_in_request(lambda: p.call("안녕"))
    assert calls[0]["model"] == "kimi-k3:cloud" and notes == []


def test_stream_uses_the_same_substitute(monkeypatch):
    p, _ = _provider(monkeypatch, ["glm-5.2:cloud"])
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        body = json.dumps({"response": "답", "done": True}) + "\n"
        return httpx.Response(200, content=body.encode())

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "llm.providers.ollama.httpx.AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )

    asyncio.run(p.call_stream("안녕"))
    assert sent and sent[0]["model"] == "glm-5.2:cloud"


def test_settings_card_shows_substitute(monkeypatch):
    from app.routers.llm_ocr import _default_model_info

    p, _ = _provider(monkeypatch, ["glm-5.3:cloud", "glm-5.2:cloud"])
    info = asyncio.run(_default_model_info(p))
    assert info["listed"] is False and info["substitute"] == "glm-5.2:cloud"
    p2, _ = _provider(monkeypatch, ["qwen3:8b"])
    assert asyncio.run(_default_model_info(p2))["substitute"] is None
