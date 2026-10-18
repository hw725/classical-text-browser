"""자동(폴백 순서) 기본 모델과 《조용한 폴백》 (D-143, 2026-10-18).

무엇을 지키는가:
    1. Ollama 텍스트 기본은 `kimi-k3:cloud`, ChatGPT 계정(OAuth) 기본은 `gpt-6.1-sol`이다.
       4월에 넣은 `gemma4:e4b`·`gpt-5.4-mini`가 반년 동안 남아 이 PC에서는 앞 두 순위가 늘 실패했다
       (Ollama 404 `model 'gemma4:e4b' not found`, OAuth 500) — 답은 3순위 Gemini에서 왔다.
    2. 기본 모델은 .env(OLLAMA_TEXT_MODEL·OPENAI_OAUTH_MODEL·OPENAI_OAUTH_EFFORT)로 바꾼다.
       설정 화면도 같은 서고 .env를 쓴다(core.env_settings).
    3. OAuth 추론 강도는 호출자가 정하지 않으면 medium(사용자 결정). think=False·명시값은 그대로.
    4. 기본 모델이 설치 목록·프록시 목록에 없으면 **부르지 않고** 《목록에 없다》로 실패한다.
    5. 앞 순위가 실패하면 조용히 넘어가지 않는다 — 응답의 fallback, 서버 경고 기록,
       API 응답 머리(X-CTB-LLM-Fallback), 화면 토스트.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

from llm.config import LlmConfig
from llm.providers.base import BaseLlmProvider, LlmProviderError, LlmResponse
from llm.providers.ollama import OllamaProvider
from llm.providers.openai_oauth_provider import OpenAiOAuthProvider


@pytest.fixture
def clean_env(monkeypatch):
    """이 PC의 .env·환경변수가 기본값 시험을 흔들지 않게."""
    for k in ("OLLAMA_TEXT_MODEL", "OPENAI_OAUTH_MODEL", "OPENAI_OAUTH_EFFORT"):
        monkeypatch.delenv(k, raising=False)

    def _cfg(**env):
        c = LlmConfig()
        c._env_cache = {k.upper(): v for k, v in env.items()}
        return c

    return _cfg


# ── 1·2. 기본값과 .env ────────────────────────────────────────────────


def test_ollama_text_default_is_kimi_k3_for_every_text_purpose(clean_env):
    p = OllamaProvider(clean_env())
    for purpose in (
        "text",
        "translation",
        "json",
        "punctuation",
        "annotation",
        "segmentation_rules",
    ):
        assert p.default_text_model(purpose) == "kimi-k3:cloud", purpose
    # 비전 기본은 이 결정의 범위 밖 — 그대로 gemma4:cloud(D-114)
    assert OllamaProvider.DEFAULT_MODELS["vision"] == "gemma4:cloud"


def test_ollama_text_default_follows_env(clean_env):
    p = OllamaProvider(clean_env(OLLAMA_TEXT_MODEL="glm-5.2:cloud"))
    assert p.default_text_model("text") == "glm-5.2:cloud"
    assert p.default_text_model("translation") == "glm-5.2:cloud"


def test_oauth_default_is_gpt_6_1_sol_and_follows_env(clean_env):
    assert OpenAiOAuthProvider(clean_env()).default_model() == "gpt-6.1-sol"
    assert (
        OpenAiOAuthProvider(clean_env(OPENAI_OAUTH_MODEL="gpt-6-luna")).default_model()
        == "gpt-6-luna"
    )


def test_gpt6_is_a_reasoning_model():
    """gpt-6 계열에 추론 강도를 보내려면 이 판정이 참이어야 한다 — 전에는 gpt-5까지만 봤다."""
    assert OpenAiOAuthProvider._is_reasoning_model("gpt-6.1-sol")
    assert OpenAiOAuthProvider._is_reasoning_model("gpt-6-astra")


# ── 3. 추론 강도 ──────────────────────────────────────────────────────


def test_oauth_effort_defaults_to_medium_when_caller_is_silent(clean_env):
    p = OpenAiOAuthProvider(clean_env())
    assert p.reasoning_effort(None) == "medium"
    assert p.reasoning_effort(True) == "medium"
    assert p.reasoning_effort(False) == "low"  # 사고 끔(D-074)은 그대로
    assert p.reasoning_effort("high") == "high"  # 명시값은 그대로
    assert (
        OpenAiOAuthProvider(clean_env(OPENAI_OAUTH_EFFORT="high")).reasoning_effort(None) == "high"
    )


class _FakeChat:
    def __init__(self, log):
        self.log = log

    async def create(self, **kw):
        self.log.append(kw)
        msg = SimpleNamespace(content="답")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=1),
            model=kw["model"],
            id="c1",
        )


class _FakeResponses:
    def __init__(self, log):
        self.log = log

    async def create(self, **req):
        self.log.append(req)
        return SimpleNamespace(
            output_text="답",
            status="completed",
            incomplete_details=None,
            usage=SimpleNamespace(input_tokens=5, output_tokens=3),
            model=req["model"],
            id="r1",
        )


class _FakeClient:
    def __init__(self, log):
        self.chat = SimpleNamespace(completions=_FakeChat(log))
        self.responses = _FakeResponses(log)


def _oauth_with_fake(cfg, log, listed=("gpt-6.1-sol", "gpt-6-luna")):
    p = OpenAiOAuthProvider(cfg)
    p._create_client = lambda: _FakeClient(log)
    p._discovered_url = "http://127.0.0.1:10532/v1"
    p._discovered_models = [{"id": m} for m in listed]
    return p


def test_oauth_text_call_sends_default_model_with_medium_effort(clean_env):
    log = []
    p = _oauth_with_fake(clean_env(), log)
    r = asyncio.run(p.call("안녕"))
    assert r.model == "gpt-6.1-sol"
    assert log[0]["model"] == "gpt-6.1-sol"
    assert log[0]["reasoning_effort"] == "medium"


def test_oauth_vision_call_sends_medium_effort_when_silent(clean_env):
    log = []
    p = _oauth_with_fake(clean_env(), log)
    asyncio.run(p.call_with_image("read", b"PNG"))
    assert log[0]["model"] == "gpt-6.1-sol"
    assert log[0]["reasoning"] == {"effort": "medium"}


# ── 4. 목록에 없는 기본 모델은 부르지 않는다 ──────────────────────────


def test_oauth_default_missing_from_proxy_list_fails_without_calling(clean_env):
    log = []
    p = _oauth_with_fake(clean_env(), log, listed=("gpt-5.6-sol",))
    with pytest.raises(LlmProviderError, match="목록에 없"):
        asyncio.run(p.call("안녕"))
    with pytest.raises(LlmProviderError, match="목록에 없"):
        asyncio.run(p.call_with_image("read", b"PNG"))
    assert log == []  # 한도를 쓰는 호출이 나가지 않았다


def test_oauth_explicit_model_is_not_blocked_by_list(clean_env):
    """사람이 고른 모델은 막지 않는다 — 목록보다 새 모델일 수 있다."""
    log = []
    p = _oauth_with_fake(clean_env(), log, listed=("gpt-5.6-sol",))
    asyncio.run(p.call("안녕", model="gpt-6.1-sol"))
    assert log and log[0]["model"] == "gpt-6.1-sol"


def test_ollama_default_missing_from_installed_list_fails_without_calling(clean_env, monkeypatch):
    p = OllamaProvider(clean_env())
    calls = []

    async def _models(*a, **k):
        return [{"name": "glm-5.3:cloud"}, {"name": "gemma4:cloud"}]

    async def _gen(payload):
        calls.append(payload)
        return {"response": "답"}

    monkeypatch.setattr(p, "list_models", _models)
    monkeypatch.setattr(p, "_generate", _gen)
    with pytest.raises(LlmProviderError, match="목록에 없"):
        asyncio.run(p.call("안녕"))
    assert calls == []


def test_ollama_default_installed_is_called(clean_env, monkeypatch):
    p = OllamaProvider(clean_env())
    calls = []

    async def _models(*a, **k):
        return [{"name": "kimi-k3:cloud"}]

    async def _gen(payload):
        calls.append(payload)
        return {"response": "답"}

    monkeypatch.setattr(p, "list_models", _models)
    monkeypatch.setattr(p, "_generate", _gen)
    r = asyncio.run(p.call("안녕"))
    assert r.model == "kimi-k3:cloud" and calls[0]["model"] == "kimi-k3:cloud"


# ── 5. 앞 순위 실패를 드러낸다 ────────────────────────────────────────


class _Fail(BaseLlmProvider):
    supports_image = True

    def __init__(self, pid, msg):
        self.provider_id = pid
        self.display_name = pid
        self._msg = msg

    async def is_available(self):
        return True

    async def list_models(self):
        return []

    async def call(self, prompt, **kw):
        raise LlmProviderError(self._msg)

    async def call_stream(self, prompt, **kw):
        raise LlmProviderError(self._msg)

    async def call_with_image(self, prompt, image, **kw):
        raise LlmProviderError(self._msg)


class _Ok(_Fail):
    def __init__(self, pid):
        super().__init__(pid, "")

    def _resp(self):
        return LlmResponse(text="답", provider=self.provider_id, model="m-ok", cost_usd=0.0)

    async def call(self, prompt, **kw):
        return self._resp()

    async def call_stream(self, prompt, **kw):
        return self._resp()

    async def call_with_image(self, prompt, image, **kw):
        return self._resp()


def _router(tmp_path, monkeypatch):
    monkeypatch.setenv("CTB_CONFIG_DIR", str(tmp_path))
    from llm.router import LlmRouter

    r = LlmRouter(LlmConfig(library_root=tmp_path))
    r.providers = [
        _Fail("ollama", "Ollama 응답 404: model 'gemma4:e4b' not found"),
        _Fail("openai_oauth", "Error code: 500 server_error"),
        _Ok("gemini"),
    ]
    return r


@pytest.mark.parametrize("method", ["call", "call_stream", "call_with_image"])
def test_router_fallback_is_on_the_response_and_in_the_log(tmp_path, monkeypatch, caplog, method):
    r = _router(tmp_path, monkeypatch)
    args = ("묻기", b"PNG") if method == "call_with_image" else ("묻기",)
    with caplog.at_level(logging.WARNING, logger="llm.router"):
        resp = asyncio.run(getattr(r, method)(*args))
    assert resp.provider == "gemini"
    assert [f["provider"] for f in resp.fallback] == ["ollama", "openai_oauth"]
    assert "404" in resp.fallback[0]["error"] and "500" in resp.fallback[1]["error"]
    warned = " ".join(rec.getMessage() for rec in caplog.records if rec.levelno >= logging.WARNING)
    assert "ollama" in warned and "openai_oauth" in warned and "gemini" in warned


def test_router_without_fallback_has_empty_trail(tmp_path, monkeypatch):
    r = _router(tmp_path, monkeypatch)
    r.providers = [_Ok("ollama")]
    assert asyncio.run(r.call("묻기")).fallback == []


def test_unavailable_message_names_the_current_default_not_gemma(tmp_path, monkeypatch):
    from llm.providers.base import LlmUnavailableError

    r = _router(tmp_path, monkeypatch)
    r.providers = r.providers[:2]
    with pytest.raises(LlmUnavailableError) as ei:
        asyncio.run(r.call("묻기"))
    assert "gemma4:e4b 모델 필요" not in str(ei.value)
    assert "kimi-k3:cloud" in str(ei.value)


def test_api_response_carries_fallback_header(tmp_path, monkeypatch):
    """화면이 알 수 있게 — 라우트가 따로 손대지 않아도 미들웨어가 머리에 싣는다."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.server import _llm_fallback_header

    r = _router(tmp_path, monkeypatch)
    mini = FastAPI()
    mini.middleware("http")(_llm_fallback_header)

    @mini.get("/api/ask")
    async def ask():
        resp = await r.call("묻기")
        return {"text": resp.text}

    @mini.get("/api/quiet")
    async def quiet():
        return {}

    c = TestClient(mini)
    got = c.get("/api/ask")
    head = unquote(got.headers.get("X-CTB-LLM-Fallback", ""))
    assert "ollama" in head and "openai_oauth" in head and "gemini" in head
    assert "X-CTB-LLM-Fallback" not in c.get("/api/quiet").headers


def test_screen_turns_fallback_header_into_a_notice(tmp_path):
    from urllib.parse import quote

    from tests.js_harness import run_js

    raw = quote(
        "ollama/kimi-k3:cloud: 모델 없음 → openai_oauth/gpt-6.1-sol: 500 → gemini/gemini-2.5-flash"
    )
    out = run_js(
        tmp_path,
        "toast.js",
        ["_llmFallbackNotice"],
        "",
        f"console.log(JSON.stringify({{ msg: _llmFallbackNotice({raw!r}),"
        " none: _llmFallbackNotice(null) }));",
    )
    assert "앞 순위" in out["msg"] and "gemini" in out["msg"] and "모델 없음" in out["msg"]
    assert out["none"] is None


# ── 2. 설정 화면이 같은 .env를 쓴다 ───────────────────────────────────


def test_account_card_shows_default_model_and_whether_it_is_listed(clean_env, monkeypatch):
    from app.routers.llm_ocr import _default_model_info

    o = OllamaProvider(clean_env())

    async def _models(*a, **k):
        return [
            {"name": "glm-5.3:cloud"},
            {"name": "kimi-k3:cloud"},
            {"name": "kimi-k2:cloud", "retired": True},
        ]

    monkeypatch.setattr(o, "list_models", _models)
    info = asyncio.run(_default_model_info(o))
    assert info["model"] == "kimi-k3:cloud" and info["listed"] and info["source"] == "builtin"
    assert info["env_key"] == "ollama_text_model"
    assert "kimi-k2:cloud" not in info["choices"]  # 은퇴 모델은 고를 수 없다

    q = _oauth_with_fake(clean_env(OPENAI_OAUTH_MODEL="gpt-5.4-mini"), [], listed=("gpt-6.1-sol",))
    info = asyncio.run(_default_model_info(q))
    assert info["model"] == "gpt-5.4-mini" and info["source"] == "env" and not info["listed"]
    assert info["effort"] == "medium" and info["effort_key"] == "openai_oauth_effort"


def test_settings_manage_default_model_keys_in_plain_text(tmp_path):
    from core.env_settings import MANAGED_KEYS, read_status, write_values

    assert MANAGED_KEYS["ollama_text_model"] == "OLLAMA_TEXT_MODEL"
    assert MANAGED_KEYS["openai_oauth_model"] == "OPENAI_OAUTH_MODEL"
    assert MANAGED_KEYS["openai_oauth_effort"] == "OPENAI_OAUTH_EFFORT"
    st = write_values(
        tmp_path, {"ollama_text_model": "glm-5.2:cloud", "anthropic": "sk-secret-1234"}
    )
    # 모델 이름은 비밀이 아니라 그대로 보인다. 키는 여전히 끝 네 글자만
    assert st["keys"]["ollama_text_model"]["value"] == "glm-5.2:cloud"
    assert "value" not in st["keys"]["anthropic"]
    assert read_status(tmp_path)["keys"]["anthropic"]["hint"] == "…1234"


def test_settings_reject_unknown_effort(tmp_path):
    from core.env_settings import write_values

    with pytest.raises(ValueError):
        write_values(tmp_path, {"openai_oauth_effort": "max\nOPENAI_API_KEY=x"})
    with pytest.raises(ValueError):
        write_values(tmp_path, {"openai_oauth_effort": "turbo"})


# ── 릴리스 리뷰 회귀(2026-10-18 Codex·검토 에이전트 지적, 고치기 전 실패 확인) ──────────


def _bare_config(monkeypatch):
    for key in ("OLLAMA_TEXT_MODEL", "OPENAI_OAUTH_MODEL", "OPENAI_OAUTH_EFFORT"):
        monkeypatch.delenv(key, raising=False)
    config = LlmConfig()
    config._env_cache = {}
    return config


def _chat_client(calls):
    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="answer"), finish_reason="stop")
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            model=kwargs["model"],
            id="fake-response",
        )

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_tags_http_failure_does_not_block_default(monkeypatch):
    """/api/tags가 503이면 《모델 0개》가 아니라 《목록 확인 실패》 — 기본 모델을 막지 않는다."""
    import httpx

    provider = OllamaProvider(_bare_config(monkeypatch))
    monkeypatch.setattr(provider, "_shared_get", lambda key: None)
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(503, json={"error": "temporary tags failure"})
    )
    monkeypatch.setattr(
        "llm.providers.ollama.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    calls = []

    async def generate(payload):
        calls.append(payload)
        return {"response": "answer"}

    monkeypatch.setattr(provider, "_generate", generate)
    response = asyncio.run(provider.call("prompt"))
    assert response.text == "answer"
    assert len(calls) == 1


def test_retired_default_counts_as_missing(monkeypatch):
    """설정 카드가 은퇴 모델을 목록에서 빼듯, 라우터도 은퇴한 기본 모델을 부르지 않는다(410)."""
    provider = OllamaProvider(_bare_config(monkeypatch))

    async def models(**kw):
        return [{"name": "kimi-k3:cloud", "retired": True}]

    monkeypatch.setattr(provider, "list_models", models)
    with pytest.raises(LlmProviderError, match="목록에 없습니다"):
        asyncio.run(provider._require_installed("kimi-k3:cloud"))


def test_successfully_empty_oauth_list_blocks_default(monkeypatch):
    provider = OpenAiOAuthProvider(_bare_config(monkeypatch))
    provider._discovered_models = []  # /v1/models가 {data: []}로 답했다
    calls = []
    monkeypatch.setattr(provider, "_create_client", lambda: _chat_client(calls))
    with pytest.raises(LlmProviderError):
        asyncio.run(provider.call("prompt"))
    assert calls == []


def test_silent_think_keeps_explicit_reasoning_budget(monkeypatch):
    provider = OpenAiOAuthProvider(_bare_config(monkeypatch))
    calls = []
    monkeypatch.setattr(provider, "_create_client", lambda: _chat_client(calls))
    asyncio.run(provider.call("prompt", model="gpt-6.1-sol", max_tokens=256, thinking_budget=128))
    assert calls[0]["reasoning_effort"] == "medium"
    assert calls[0]["max_completion_tokens"] == 256 + 128


def test_fallback_header_lists_each_line_once():
    from llm import fallback_notice

    value = unquote(fallback_notice.header_value(["a → b", "a → b", "c → d", "a → b"]))
    assert value == "a → b | c → d"


def test_nonstream_correction_preserves_fallback_header(monkeypatch, tmp_path, caplog):
    """작업 스레드(run_in_executor)에서 난 폴백도 응답 머리에 실린다."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers import llm_ocr
    from app.server import _llm_fallback_header
    from llm.router import LlmRouter

    monkeypatch.setattr(llm_ocr, "require_repo_path", lambda *args: tmp_path)
    monkeypatch.setattr(llm_ocr, "_get_ocr_pipeline", lambda: (None, None))
    router = LlmRouter.__new__(LlmRouter)

    def correction(*args, **kwargs):
        router._finish(
            LlmResponse(text="answer", provider="gemini", model="fake"),
            [{"provider": "ollama", "model": "fake", "error": "unavailable"}],
            "ocr_correction",
        )
        return {"blocks": []}

    monkeypatch.setattr(llm_ocr, "_run_page_correction", correction)
    app = FastAPI()
    app.middleware("http")(_llm_fallback_header)
    app.include_router(llm_ocr.router)
    with caplog.at_level("WARNING", logger="llm.router"):
        response = TestClient(app).post(
            "/api/documents/doc/parts/main/pages/1/ocr/correct", json={"mode": "fast"}
        )
    assert response.status_code == 200, response.text
    assert any("ollama" in record.getMessage() for record in caplog.records)
    assert "X-CTB-LLM-Fallback" in response.headers


def test_llm_ocr_thread_keeps_request_context(monkeypatch):
    """LLM 비전 OCR은 별도 스레드에서 asyncio.run을 돈다 — 그 안의 폴백도 요청 목록에 적힌다."""
    from llm import fallback_notice
    from ocr.llm_ocr_engine import LlmOcrEngine

    engine = LlmOcrEngine()

    async def recognize(*args, **kwargs):
        fallback_notice.record("ollama/x: 목록에 없음 → gemini/y")
        return "done"

    monkeypatch.setattr(engine, "_recognize_async", recognize)
    monkeypatch.setattr(engine, "_join_timeout", lambda kwargs: 10)
    monkeypatch.setattr(engine, "is_available", lambda: True)
    bucket, token = fallback_notice.begin()
    try:
        engine.recognize(b"img")
    except Exception:  # noqa: BLE001 — 결과 변환 실패는 이 시험의 관심이 아니다
        pass
    finally:
        fallback_notice.end(token)
    assert bucket == ["ollama/x: 목록에 없음 → gemini/y"]


def test_saved_defaults_reach_ocr_engine_and_clear_cache(monkeypatch, tmp_path):
    """설정 저장 뒤 이미 만든 LLM OCR 엔진도 새 기본 모델을 쓰고, 《자동》 결과 캐시는 비워진다."""
    from app import _state
    from app.routers.library import LlmKeysRequest, api_set_llm_keys
    from ocr.llm_ocr_engine import LlmOcrEngine
    from ocr.registry import OcrEngineRegistry

    _bare_config(monkeypatch)
    monkeypatch.setattr(_state, "_library_path", tmp_path)
    monkeypatch.setattr(_state, "_llm_router", None)
    monkeypatch.setattr(_state, "_ocr_registry", None)
    monkeypatch.setattr(_state, "_ocr_pipeline", None)
    monkeypatch.setattr(_state, "_llm_result_cache", {"punctuation:auto:x": (0.0, {})})

    def register_llm_only(registry):
        registry.register(LlmOcrEngine())

    monkeypatch.setattr(OcrEngineRegistry, "auto_register", register_llm_only)
    _state._get_ocr_pipeline()
    status = asyncio.run(
        api_set_llm_keys(
            LlmKeysRequest(openai_oauth_model="gpt-6-luna", openai_oauth_effort="high")
        )
    )
    assert status["keys"]["openai_oauth_model"]["value"] == "gpt-6-luna"
    _, registry = _state._get_ocr_pipeline()
    oauth = registry.get_engine("llm_vision")._router._get_provider("openai_oauth")
    assert oauth.default_model() == "gpt-6-luna"
    assert oauth.reasoning_effort(None) == "high"
    assert _state._llm_result_cache == {}


def test_save_error_shows_validation_reason():
    """422(형식 검사)의 까닭은 detail 목록에 있다 — 토스트에 《HTTP 422》만 남지 않게."""
    from pathlib import Path

    js = Path(__file__).resolve().parents[1] / "src/app/static/js/setup-panel.js"
    text = js.read_text(encoding="utf-8")
    assert "data.error || `HTTP ${res.status}`" not in text
    assert text.count("data.detail.map((d) => d.msg)") >= 1
