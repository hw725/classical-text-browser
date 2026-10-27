"""OpenAI OAuth는 남은 사용량을 먼저 보고, 넘친 몫은 Claude가 마무리한다 (2026-10-27 사용자 지시).

사용자 원문:
    「앞으로 모든 openai oauth 쓸 때마다 codex /status 로 남은 사용량을 확인하고
     적절하게 작업을 들어가란 말이야」
    「무조건 그렇게 넘기고 남은 사용량이 감당 못할 거 같으면 자동으로 네가 마저
     처리하도록 하란 말이야」
    (「네가」 = Claude. ollama 가 아니라 Claude 로 넘긴다.)

검사하는 것:
    1. 문지기(OAuthQuotaGuard)가 첫 호출 전·20회마다·일정 시간마다 남은 양을 다시 읽고,
       예비분 이하·조회 실패·사용 불가면 막는다. 막힌 뒤에도 일정 시간 뒤 다시 읽어 풀린다.
    2. 막혔을 때 OAuth 공급자는 프록시를 부르지 않는다. 한도 오류(429 등)를 받으면 문지기를 막는다.
    3. 라우터는 Ollama 1순위를 그대로 두고, OAuth 가 사용량 때문에 막히면 Gemini 가 아니라
       Claude(claude -p 공급자, 비전은 Anthropic)로 넘긴다. 사유(남은 사용량)가 폴백 알림에 실린다.
    4. Claude CLI 공급자는 OAuth 넘침분에만 쓰인다(평소 순서에는 끼지 않는다).

외부 호출 없음 — 사용량 조회·프록시·claude 실행은 모두 가짜다.
pytest 로도, 단독(`python tests/test_oauth_quota_first_20261027.py`, 실패는 `FAIL:` 줄)으로도 돈다.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / "src"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── 공통 가짜 ──────────────────────────────────────────────────────────


def _quota(used5h=30, used7d=20, allowed=True, reached=None):
    return {
        "rateLimits": {
            "planType": "team",
            "rateLimitReachedType": reached,
            "primary": {"usedPercent": used5h, "windowDurationMins": 300, "resetsAt": None},
            "secondary": {"usedPercent": used7d, "windowDurationMins": 10080, "resetsAt": None},
        },
        "ordinaryUsageAllowed": allowed,
    }


class _Reader:
    def __init__(self, value):
        self.value = value
        self.reads = 0

    def __call__(self):
        self.reads += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _guard(reader, clock=None):
    from llm.providers.openai_oauth_provider import OAuthQuotaGuard

    return OAuthQuotaGuard(reader=reader, clock=clock or _Clock())


def _cfg():
    from llm.config import LlmConfig

    c = LlmConfig()
    c._env_cache = {}
    return c


class _FakeChat:
    def __init__(self, log, exc=None):
        self.log, self.exc = log, exc

    async def create(self, **kw):
        if self.exc:
            raise self.exc
        self.log.append(kw)
        msg = SimpleNamespace(content="답")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=1),
            model=kw["model"],
            id="c1",
        )


class _FakeResponses:
    def __init__(self, log, exc=None):
        self.log, self.exc = log, exc

    async def create(self, **req):
        if self.exc:
            raise self.exc
        self.log.append(req)
        return SimpleNamespace(
            output_text="답", status="completed", incomplete_details=None,
            usage=SimpleNamespace(input_tokens=5, output_tokens=3), model=req["model"], id="r1",
        )


def _oauth(log, guard, exc=None):
    from llm.providers.openai_oauth_provider import OpenAiOAuthProvider

    p = OpenAiOAuthProvider(_cfg())
    p._create_client = lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=_FakeChat(log, exc)), responses=_FakeResponses(log, exc)
    )
    p._discovered_url = "http://127.0.0.1:10532/v1"
    p._discovered_models = [{"id": "gpt-6.1-sol"}]
    p.quota_guard = guard
    return p


def _fake_provider_classes():
    from llm.providers.base import BaseLlmProvider, LlmProviderError, LlmResponse
    from llm.providers.openai_oauth_provider import OAuthQuotaError

    class Fake(BaseLlmProvider):
        supports_image = True

        def __init__(self, pid, mode="ok", msg="", image=True, overflow_only=False):
            self.provider_id = pid
            self.display_name = pid
            self.mode, self.msg = mode, msg
            self.supports_image = image
            self.OVERFLOW_ONLY = overflow_only
            self.calls = 0

        async def is_available(self):
            return True

        async def list_models(self):
            return []

        def _go(self):
            self.calls += 1
            if self.mode == "quota":
                raise OAuthQuotaError(self.msg)
            if self.mode == "fail":
                raise LlmProviderError(self.msg)
            return LlmResponse(text='{"ok": 1}', provider=self.provider_id, model="m", cost_usd=0.0)

        async def call(self, prompt, **kw):
            return self._go()

        async def call_stream(self, prompt, **kw):
            return self._go()

        async def call_with_image(self, prompt, image, **kw):
            return self._go()

    return Fake


def _router(providers):
    os.environ["CTB_CONFIG_DIR"] = tempfile.mkdtemp(prefix="ctb_oauthq_")
    from llm.config import LlmConfig
    from llm.router import LlmRouter

    r = LlmRouter(LlmConfig(library_root=Path(tempfile.mkdtemp(prefix="ctb_oauthq_lib_"))))
    r.providers = providers
    return r


QUOTA_MSG = "OAuth 남은 사용량 8% ≤ 예비 10% — Claude 로 넘김"


# ── 1. 문지기 ──────────────────────────────────────────────────────────


def test_guard_reads_before_first_call_and_every_20_calls():
    rd = _Reader(_quota())
    g = _guard(rd)
    assert g.check() is None and rd.reads == 1
    for _ in range(19):
        g.note_call()
        assert g.check() is None
    assert rd.reads == 1, rd.reads
    g.note_call()
    assert g.check() is None
    assert rd.reads == 2, rd.reads


def test_guard_rereads_after_time_ttl():
    rd, clk = _Reader(_quota()), _Clock()
    g = _guard(rd, clk)
    g.check()
    clk.t += g.OK_TTL_SEC + 1
    g.check()
    assert rd.reads == 2


def test_guard_blocks_at_reserve_on_smaller_window():
    g = _guard(_Reader(_quota(used5h=30, used7d=92)))
    reason = g.check()
    assert reason and "남은" in reason and "예비" in reason, reason


def test_guard_blocks_when_read_fails():
    g = _guard(_Reader(RuntimeError("codex 없음")))
    reason = g.check()
    assert reason and "모름" in reason, reason


def test_guard_blocks_when_usage_not_allowed():
    g = _guard(_Reader(_quota(allowed=False, reached="primary")))
    assert g.check()


def test_guard_does_not_reread_while_blocked_then_recovers_after_ttl():
    rd, clk = _Reader(_quota(used5h=95)), _Clock()
    g = _guard(rd, clk)
    assert g.check()
    assert g.check() and rd.reads == 1  # 막힌 동안은 매번 app-server 를 띄우지 않는다
    rd.value = _quota(used5h=40)
    clk.t += g.BLOCK_TTL_SEC + 1
    assert g.check() is None
    assert rd.reads == 2


# ── 2. 공급자 ──────────────────────────────────────────────────────────


def test_provider_does_not_call_proxy_when_blocked():
    from llm.providers.openai_oauth_provider import OAuthQuotaError

    log = []
    p = _oauth(log, _guard(_Reader(_quota(used5h=95))))
    for coro in (lambda: p.call("안녕"), lambda: p.call_stream("안녕"),
                 lambda: p.call_with_image("read", b"PNG")):
        try:
            asyncio.run(coro())
        except OAuthQuotaError as e:
            assert "남은" in str(e), e
        else:
            raise AssertionError("막혔는데 호출이 나갔다")
    assert log == []


def test_provider_counts_calls_when_allowed():
    log = []
    g = _guard(_Reader(_quota()))
    p = _oauth(log, g)
    asyncio.run(p.call("안녕"))
    assert log and g.calls == 1


def test_provider_limit_error_blocks_guard():
    from llm.providers.openai_oauth_provider import OAuthQuotaError

    class _E(Exception):
        status_code = 429

    rd = _Reader(_quota())
    g = _guard(rd)
    p = _oauth([], g, exc=_E("Error code: 429 - usage limit reached"))
    try:
        asyncio.run(p.call("안녕"))
    except OAuthQuotaError:
        pass
    else:
        raise AssertionError("429 가 OAuthQuotaError 로 바뀌지 않았다")
    assert g.check(), "429 뒤에도 문지기가 열려 있다"
    assert rd.reads == 1


# ── 3. 라우터 ──────────────────────────────────────────────────────────


def test_router_default_order_keeps_ollama_first_and_claude_after_oauth():
    r = _router(None)
    from llm.router import LlmRouter

    r.providers = LlmRouter(r.config).providers
    ids = [p.provider_id for p in r.providers]
    assert ids[:3] == ["ollama", "openai_oauth", "claude_cli"], ids
    assert ids[-1] == "anthropic", ids


def _overflow_router():
    Fake = _fake_provider_classes()
    providers = [
        Fake("ollama", "fail", "Ollama 응답 404"),
        Fake("openai_oauth", "quota", QUOTA_MSG),
        Fake("gemini"),  # 순서상 Claude 보다 앞이어도 넘침분은 Claude 가 먼저
        Fake("claude_cli", image=False, overflow_only=True),
        Fake("anthropic"),
    ]
    return _router(providers), providers


def test_router_sends_oauth_overflow_to_claude_not_gemini():
    from llm import fallback_notice

    for method in ("call", "call_stream"):
        r, ps = _overflow_router()
        bucket, tok = fallback_notice.begin()
        try:
            resp = asyncio.run(getattr(r, method)("묻기"))
        finally:
            fallback_notice.end(tok)
        assert resp.provider == "claude_cli", (method, resp.provider)
        assert ps[2].calls == 0, "gemini 가 불렸다"
        assert [f["provider"] for f in resp.fallback] == ["ollama", "openai_oauth"]
        assert "남은" in resp.fallback[1]["error"]
        assert any("OAuth 남은 사용량" in line for line in bucket), bucket


def test_router_vision_overflow_goes_to_anthropic_before_gemini():
    r, ps = _overflow_router()
    resp = asyncio.run(r.call_with_image("읽기", b"PNG"))
    assert resp.provider == "anthropic", resp.provider
    assert ps[2].calls == 0


def test_router_claude_cli_is_overflow_only():
    Fake = _fake_provider_classes()
    ps = [Fake("ollama", "fail", "x"), Fake("openai_oauth", "fail", "Error code: 500"),
          Fake("claude_cli", image=False, overflow_only=True), Fake("gemini")]
    r = _router(ps)
    resp = asyncio.run(r.call("묻기"))
    assert resp.provider == "gemini" and ps[2].calls == 0
    ps2 = [Fake("ollama"), Fake("openai_oauth"),
           Fake("claude_cli", image=False, overflow_only=True)]
    resp = asyncio.run(_router(ps2).call("묻기"))
    assert resp.provider == "ollama" and ps2[1].calls == 0 and ps2[2].calls == 0


def test_router_forced_oauth_overflow_goes_to_claude():
    Fake = _fake_provider_classes()
    ps = [Fake("ollama"), Fake("openai_oauth", "quota", QUOTA_MSG),
          Fake("claude_cli", image=False, overflow_only=True), Fake("gemini")]
    r = _router(ps)
    resp = asyncio.run(r.call("묻기", force_provider="openai_oauth"))
    assert resp.provider == "claude_cli", resp.provider
    assert resp.fallback and "남은" in resp.fallback[0]["error"]
    resp = asyncio.run(r.call_stream("묻기", force_provider="openai_oauth"))
    assert resp.provider == "claude_cli", resp.provider


def test_state_auto_loop_sends_oauth_overflow_to_claude():
    """앱의 JSON 갈래(_call_llm_text)도 라우터와 같은 순서를 쓴다 — 자기 반복문을 따로 돈다."""
    import app._state as st

    r, ps = _overflow_router()
    old = st._get_llm_router
    st._get_llm_router = lambda: r
    try:
        out = asyncio.run(st._call_llm_text("punctuation", "學而時習之 oauth-quota-check-1027"))
    finally:
        st._get_llm_router = old
    assert out is not None
    assert ps[3].calls == 1 and ps[2].calls == 0, [p.calls for p in ps]


# ── 4. Claude CLI 공급자 ───────────────────────────────────────────────


def test_claude_cli_command_line():
    import llm.providers.claude_cli_provider as cc

    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        sp = argv[argv.index("--system-prompt-file") + 1]
        seen["system"] = Path(sp).read_text(encoding="utf-8")
        seen["sys_path"] = sp
        return SimpleNamespace(returncode=0, stdout="답\n", stderr="")

    old_run, old_exe = cc.subprocess.run, cc.find_claude
    cc.subprocess.run = fake_run
    cc.find_claude = lambda: "claude.exe"
    try:
        p = cc.ClaudeCliProvider(_cfg())
        assert asyncio.run(p.is_available())
        resp = asyncio.run(p.call("본문", system="지시문 첫 줄\n둘째 줄"))
    finally:
        cc.subprocess.run, cc.find_claude = old_run, old_exe
    argv = seen["argv"]
    assert argv[0] == "claude.exe" and "-p" in argv
    for a, b in (("--output-format", "text"), ("--tools", "")):
        assert argv[argv.index(a) + 1] == b, argv
    # 여러 줄 지시문은 인자가 아니라 파일로 — claude.CMD 가 줄바꿈 인자를 자른다
    assert "--system-prompt" not in argv
    assert seen["system"] == "지시문 첫 줄\n둘째 줄"
    assert not Path(seen["sys_path"]).exists(), "임시 지시문 파일이 남았다"
    assert "--no-session-persistence" in argv
    assert seen["kw"].get("input") == "본문"
    assert resp.text == "답" and resp.provider == "claude_cli"
    assert p.OVERFLOW_ONLY is True and p.supports_image is False


# ── 단독 실행 ──────────────────────────────────────────────────────────


def _main() -> int:
    fails = 0
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn()
            print(f"PASS: {name}")
        except BaseException as e:  # noqa: BLE001 — 가져오기 실패도 FAIL 로 센다
            fails += 1
            msg = " ".join(f"{type(e).__name__}: {e}".split())[:300]
            print(f"FAIL: {name} — {msg}")
    print(f"{len(tests) - fails}/{len(tests)} 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(_main())
