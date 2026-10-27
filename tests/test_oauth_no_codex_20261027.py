"""Codex CLI 가 없는 PC 에서는 OAuth 를 부르지 않고 Claude 로 넘긴다 (2026-10-27 사용자 결정).

사용자 원문: 「코덱스 없으면 클로드로 넘기도록 해」

배포판을 받은 PC 에는 `codex` 가 없을 수 있다. 그러면 남은 사용량 조회(oauth_quota.read_quota)가
「codex CLI 를 찾지 못했습니다」로 실패하고, 문지기는 「모름」으로 막는다 — OAuth 프록시는
한 번도 부르지 않고, 넘친 몫은 Gemini 가 아니라 claude_cli(없으면 anthropic)가 맡는다.

tests/test_oauth_quota_first_20261027.py 는 가짜 조회기(reader)를 넣어 문지기를 시험한다.
여기서는 조회기를 넣지 않고 진짜 read_quota 를 타게 한 뒤 shutil.which 가 codex 를 못 찾게만
만든다 — 실제 배포판 PC 와 같은 갈래다. 외부 호출 없음(codex·claude·프록시 모두 가짜).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / "src"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FAKE_CLAUDE = r"C:\fake\claude.exe"


@pytest.fixture
def no_codex(monkeypatch):
    """codex 는 PATH 에 없고 claude 는 있는 PC. 조회 프로세스·claude 실행 횟수를 센다."""
    import llm.oauth_quota as oq
    import llm.providers.claude_cli_provider as cc

    real_which = shutil.which
    seen = {"popen": 0, "claude_runs": []}

    def fake_which(name, *a, **kw):
        if str(name).lower().startswith("codex"):
            return None
        if str(name).lower() == "claude":
            return FAKE_CLAUDE
        return real_which(name, *a, **kw)

    def fake_popen(*a, **kw):  # codex app-server 를 띄우려 하면 안 된다
        seen["popen"] += 1
        raise AssertionError("codex 가 없는데 app-server 를 띄우려 했다")

    def fake_run(argv, **kw):
        seen["claude_runs"].append(argv)
        return SimpleNamespace(returncode=0, stdout="클로드 답\n", stderr="")

    monkeypatch.setattr(shutil, "which", fake_which)
    monkeypatch.setattr(oq.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cc.subprocess, "run", fake_run)
    return seen


class _ProxyLog:
    def __init__(self):
        self.calls = 0


def _real_oauth(proxy: _ProxyLog):
    """진짜 OpenAiOAuthProvider + 진짜 문지기(조회기 없음 → read_quota). 프록시만 가짜."""
    from llm.config import LlmConfig
    from llm.providers.openai_oauth_provider import OAuthQuotaGuard, OpenAiOAuthProvider

    cfg = LlmConfig()
    cfg._env_cache = {}
    p = OpenAiOAuthProvider(cfg)

    class _Create:
        async def create(self, **kw):
            proxy.calls += 1
            raise AssertionError("문지기가 막았어야 할 OAuth 프록시 호출이 나갔다")

    p._create_client = lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=_Create()), responses=_Create()
    )
    p._discovered_url = "http://127.0.0.1:10532/v1"
    p._discovered_models = [{"id": "gpt-6.1-sol"}]

    async def _up():  # 프록시는 떠 있다(로그인은 다른 경로로 해 두었다)
        return True

    p.is_available = _up
    p.quota_guard = OAuthQuotaGuard()  # reader=None → 진짜 read_quota 를 탄다
    return p


def _fake(pid, available=True, image=True):
    from llm.providers.base import BaseLlmProvider, LlmProviderError, LlmResponse

    class Fake(BaseLlmProvider):
        def __init__(self):
            self.provider_id = pid
            self.display_name = pid
            self.supports_image = image
            self.calls = 0

        async def is_available(self):
            return available

        async def list_models(self):
            return []

        def _go(self):
            self.calls += 1
            if pid == "ollama":
                raise LlmProviderError("Ollama 응답 404")
            return LlmResponse(text="답", provider=pid, model="m", cost_usd=0.0)

        async def call(self, prompt, **kw):
            return self._go()

        async def call_stream(self, prompt, **kw):
            return self._go()

        async def call_with_image(self, prompt, image, **kw):
            return self._go()

    return Fake()


def _claude_cli():
    from llm.config import LlmConfig
    from llm.providers.claude_cli_provider import ClaudeCliProvider

    cfg = LlmConfig()
    cfg._env_cache = {}
    return ClaudeCliProvider(cfg)


def _router(providers):
    os.environ["CTB_CONFIG_DIR"] = tempfile.mkdtemp(prefix="ctb_nocodex_")
    from llm.config import LlmConfig
    from llm.router import LlmRouter

    r = LlmRouter(LlmConfig(library_root=Path(tempfile.mkdtemp(prefix="ctb_nocodex_lib_"))))
    r.providers = providers
    return r


def _setup():
    proxy = _ProxyLog()
    oauth = _real_oauth(proxy)
    gemini = _fake("gemini")
    anthropic = _fake("anthropic")
    # 기본 순서와 같게: ollama → openai_oauth → claude_cli → gemini → openai → anthropic
    ps = [_fake("ollama"), oauth, _claude_cli(), gemini, _fake("openai"), anthropic]
    return proxy, ps, gemini, anthropic


def test_read_quota_fails_without_codex(no_codex):
    import llm.oauth_quota as oq

    with pytest.raises(RuntimeError, match="codex"):
        oq.read_quota()
    assert no_codex["popen"] == 0


def test_no_codex_auto_call_goes_to_claude_cli_not_oauth_or_gemini(no_codex):
    for method in ("call", "call_stream"):
        proxy, ps, gemini, anthropic = _setup()
        resp = asyncio.run(getattr(_router(ps), method)("묻기", purpose="text"))
        assert resp.provider == "claude_cli", (method, resp.provider)
        assert resp.text == "클로드 답"
        assert proxy.calls == 0, "codex 가 없는데 OAuth 프록시를 불렀다"
        assert gemini.calls == 0 and anthropic.calls == 0
        assert no_codex["popen"] == 0
        oauth_err = [f for f in resp.fallback if f["provider"] == "openai_oauth"]
        assert oauth_err and "모름" in oauth_err[0]["error"], resp.fallback
    assert len(no_codex["claude_runs"]) == 2
    assert no_codex["claude_runs"][0][0] == FAKE_CLAUDE


def test_no_codex_forced_oauth_goes_to_claude_cli(no_codex):
    proxy, ps, gemini, _ = _setup()
    resp = asyncio.run(_router(ps).call("묻기", force_provider="openai_oauth"))
    assert resp.provider == "claude_cli", resp.provider
    assert proxy.calls == 0 and gemini.calls == 0


def test_no_codex_no_claude_cli_goes_to_anthropic_before_gemini(no_codex, monkeypatch):
    import llm.providers.claude_cli_provider as cc

    monkeypatch.setattr(cc, "find_claude", lambda: None)  # claude 도 없는 PC
    proxy, ps, gemini, anthropic = _setup()
    resp = asyncio.run(_router(ps).call("묻기"))
    assert resp.provider == "anthropic", resp.provider
    assert proxy.calls == 0 and gemini.calls == 0
    assert no_codex["claude_runs"] == []


def _setup_no_proxy():
    """OAuth 프록시도 안 뜬 PC — openai_oauth.is_available() 가 False."""
    proxy, ps, gemini, anthropic = _setup()

    async def _down():
        return False

    ps[1].is_available = _down
    return proxy, ps, gemini, anthropic


def test_no_codex_no_proxy_goes_to_claude_cli_before_gemini(no_codex):
    for method in ("call", "call_stream"):
        proxy, ps, gemini, anthropic = _setup_no_proxy()
        resp = asyncio.run(getattr(_router(ps), method)("묻기"))
        assert resp.provider == "claude_cli", (method, resp.provider)
        assert proxy.calls == 0 and gemini.calls == 0 and anthropic.calls == 0
    assert no_codex["popen"] == 0


def test_no_codex_no_proxy_no_claude_goes_to_anthropic_before_gemini(no_codex, monkeypatch):
    import llm.providers.claude_cli_provider as cc

    monkeypatch.setattr(cc, "find_claude", lambda: None)
    proxy, ps, gemini, anthropic = _setup_no_proxy()
    resp = asyncio.run(_router(ps).call("묻기"))
    assert resp.provider == "anthropic", resp.provider
    assert gemini.calls == 0
    proxy, ps, gemini, anthropic = _setup_no_proxy()
    resp = asyncio.run(_router(ps).call_with_image("읽기", b"PNG"))
    assert resp.provider == "anthropic", resp.provider
    assert gemini.calls == 0


def test_codex_present_but_no_proxy_keeps_normal_order(monkeypatch):
    """Codex 는 있고 프록시만 안 뜬 PC 는 OAuth 를 쓸 수 있는 PC — 평소 순서(Gemini)를 둔다."""
    real_which = shutil.which
    monkeypatch.setattr(
        shutil, "which",
        lambda n, *a, **k: r"C:\fake\codex.cmd" if str(n).lower().startswith("codex")
        else (FAKE_CLAUDE if str(n).lower() == "claude" else real_which(n, *a, **k)),
    )
    proxy, ps, gemini, anthropic = _setup_no_proxy()
    resp = asyncio.run(_router(ps).call("묻기"))
    assert resp.provider == "gemini", resp.provider
    assert proxy.calls == 0 and anthropic.calls == 0


def test_no_codex_vision_goes_to_anthropic_before_gemini(no_codex):
    proxy, ps, gemini, anthropic = _setup()
    resp = asyncio.run(_router(ps).call_with_image("읽기", b"PNG"))
    assert resp.provider == "anthropic", resp.provider  # claude_cli 는 이미지를 받지 않는다
    assert proxy.calls == 0 and gemini.calls == 0
