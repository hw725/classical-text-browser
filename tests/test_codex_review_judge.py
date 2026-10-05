"""판정 모델 리뷰: 실제 키와 통신을 차단한 실패 재현만 보관한다."""

import io
import json
import os
import socket
import urllib.request

import pytest

from llm import clef_cf, jev
from llm.openrouter_decider import OpenRouterDecisionClient
from tests.js_harness import run_js


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """가짜 키만 허용하고 파일·레지스트리·소켓을 차단하여 요청을 기록한다."""
    path = os.environ.get("PATH", os.defpath)
    system_root = os.environ.get("SystemRoot", "C:\\Windows")
    for name in list(os.environ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATH", path)
    monkeypatch.setenv("SystemRoot", system_root)
    monkeypatch.setattr(jev, "KEY_ENV_FILE", tmp_path / "absent.env")
    monkeypatch.setattr(jev, "_key_from_app_env", lambda *a, **k: None)
    monkeypatch.setattr(jev, "resolve_key", lambda *a, **k: None)
    monkeypatch.setattr(clef_cf, "resolve_key", lambda *a, **k: None)
    monkeypatch.setattr(clef_cf, "_win_user_env", lambda *a: None)
    monkeypatch.setattr(jev.JevClient, "_log_usage", lambda *a, **k: None)
    monkeypatch.setattr(jev.time, "sleep", lambda *a: None)

    def blocked(*a, **k):
        raise AssertionError("Network access forbidden")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    seen = []

    def opener(req, **kw):
        seen.append(req)
        return io.BytesIO(json.dumps({"answers": {"q": {"noul": 0.9}}}).encode())

    original = jev.JevClient.__init__

    def init(self, **kw):
        kw.setdefault("opener", opener)
        original(self, **kw)

    monkeypatch.setattr(jev.JevClient, "__init__", init)
    return opener, seen


def test_vendor_url_override_must_not_receive_typesafe_key(monkeypatch, isolated):
    """TypeSafe 키가 환경변수로 바꾼 OpenRouter 주소로 전송되는지 재현한다."""
    opener, seen = isolated
    monkeypatch.setenv("JEV_BASE_URL", "https://openrouter.ai/api/alpha/decisions")
    client = jev.JevClient(api_key="fake-typesafe-only", opener=opener, retries=0)
    with pytest.raises(jev.JevCallFailed, match="url_points_to_other_vendor") as ei:
        client.ask("s", {"q": {"type": "noul", "instructions": "?"}})
    assert "JEV_BASE_URL" in ei.value.detail and "openrouter" in ei.value.detail
    leaked = [(r.full_url, r.get_header("Authorization")) for r in seen
              if "openrouter.ai" in r.full_url]
    assert not leaked, leaked
    assert client.asks_made == 0  # 보내지 않은 묻기는 상한을 쓰지 않는다


def _vendor_clients():
    from llm.decider import DeciderClient
    from llm.openrouter_decider import OpenRouterClefClient, OpenRouterJevClient

    def clef(**kw):
        return clef_cf.ClefClient(account_id="fake-account", **kw)

    return {
        "jev": jev.JevClient, "openrouter": OpenRouterDecisionClient,
        "openrouter_jev": OpenRouterJevClient, "openrouter_clef": OpenRouterClefClient,
        "decider": DeciderClient, "clef": clef,
    }


@pytest.mark.parametrize("name, foreign, own", [
    ("jev", "https://api.perplexity.ai/v1/decisions", "https://api.typesafe.ai/v1/systemone"),
    ("openrouter", "https://api.typesafe.ai/v1/systemone",
     "https://openrouter.ai/api/alpha/decisions"),
    ("openrouter_jev", "https://api.perplexity.ai/v1/decisions",
     "https://openrouter.ai/api/alpha/decisions"),
    ("openrouter_clef", "https://api.cloudflare.com/client/v4/accounts/a/ai/run/x",
     "https://openrouter.ai/api/alpha/decisions"),
    ("decider", "https://openrouter.ai/api/alpha/decisions",
     "https://api.perplexity.ai/v1/decisions"),
    ("clef", "https://openrouter.ai/api/alpha/decisions",
     "https://api.cloudflare.com/client/v4/accounts/a/ai/run/@cf/cloudflare/clef"),
])
def test_every_judge_url_env_refuses_other_vendor(monkeypatch, isolated, name, foreign, own):
    """하위 클래스마다 제 URL_ENV가 있다 — 같은 규칙이 모두에 적용된다.

    같은 업체 주소와 자체 게이트웨이(모르는 호스트)는 허용한다.
    """
    opener, seen = isolated
    make = _vendor_clients()[name]
    env = make(api_key="k", max_calls=0).URL_ENV
    q = {"q": {"type": "noul", "instructions": "?"}}
    monkeypatch.setenv(env, foreign)
    bad = make(api_key="fake", opener=opener, retries=0)
    with pytest.raises(jev.JevCallFailed, match="url_points_to_other_vendor"):
        bad.ask("s", q)
    assert not seen
    for ok_url in (own, "https://my-gateway.example.org/v1/decisions",
                   "https://gateway.ai.cloudflare.com/v1/a/g/openrouter"):
        monkeypatch.setenv(env, ok_url)
        make(api_key="fake", opener=opener, retries=0).ask("s", q)
        assert seen[-1].full_url == ok_url


def test_local_body_rejection_does_not_spend_ask_cap(isolated):
    """전송 전 크기 거절 후 남은 한 번으로 정상 요청을 보낼 수 있어야 한다."""
    opener, seen = isolated
    client = clef_cf.ClefClient(api_key="fake-cf", account_id="fake-account",
                                max_calls=1, opener=opener, retries=0)
    q = {"q": {"type": "noul", "instructions": "?"}}
    with pytest.raises(jev.JevCallFailed, match="clef_body_too_large"):
        client.ask("x" * clef_cf.MAX_BODY_BYTES, q)
    assert not seen
    client.ask("small", q)
    assert len(seen) == 1


def test_gate_checks_remaining_budget(isolated):
    """이미 한 번 사용한 상한 1회 클라이언트는 추가 묶음의 게이트를 거절해야 한다."""
    opener, _ = isolated
    client = jev.JevClient(api_key="fake-typesafe", max_calls=1, opener=opener)
    client.ask("s", {"q": {"type": "noul", "instructions": "?"}})
    with pytest.raises(jev.JevGateExceeded):
        client.gate(1)


def test_screen_distinguishes_missing_cost_from_zero(tmp_path, isolated):
    """usage가 없는 유료 응답의 비용 미상 정보가 화면에서 0달러로 바뀌지 않아야 한다."""
    opener, _ = isolated
    client = OpenRouterDecisionClient(api_key="fake-or", opener=opener)
    client.ask("s", {"q": {"type": "noul", "instructions": "?"}})
    usage = {**client.usage(), "provider": client.PROVIDER}
    assert usage["uncosted_calls"] == 1
    out = run_js(tmp_path, "work-order.js", ["_woUsageText", "_woUsd"],
                 "const U = " + json.dumps(usage) + ";",
                 "console.log(JSON.stringify({text: _woUsageText(U)}));")
    assert "유료 청구 $0" not in out["text"], out["text"]
    assert "비용 모름 1회" in out["text"], out["text"]


def test_scan_keeps_judge_probabilities_in_state(tmp_path, isolated):
    """쪽별 판정 확률은 상태(row.decider)에 그대로 남는다 — 화면 표시는 하지 않는 것이 설계다.

    Codex 리뷰(2026-10-06)는 «확률이 화면에 안 보인다»를 결함으로 냈으나 거절했다: 서버
    (`llm_ocr.py` «확률을 실어 둔다 — … 측정·검토용»)가 확률을 per_page[].decider에 싣는 것은
    측정·검토를 위해서이고, 화면은 문턱으로 접은 종류만 보인다(D-134). 이 시험은 그 보존을 고정한다.
    """
    names = ["workOrderState", "WO_UNSUPPORTED_HEADING", "_woScan", "_woTarget",
             "_woKey", "_woReady", "_woScanPages", "_woCurrentPlan", "_woScanModelSel",
             "_woScanProgress", "_woStatus", "_woScanUrl", "_woSetPlan", "_woRenderPlan",
             "_woConflicts", "_woPages", "_woEsc", "_woScanSummary", "_woFallbackText",
             "_woUsageText", "_woUsd"]
    setup = """
const els = {};
const document = {getElementById(id) {
  return els[id] || (els[id] = {value:'', textContent:'', innerHTML:'', dataset:{}});
}};
const viewerState = {docId:'d1', partId:'vol1'};
const ocrState = {gpuRuntime:true};
function showToast() { throw Error('unexpected toast'); }
function getLlmModelSelection() { return {force_provider:'clef', force_model:'clef'}; }
async function fetch() { throw Error('network forbidden'); }
let prob = 0.51;
async function _postSurveyStream() {
  return {checked:1, provider:'cloudflare', model:'clef', failures:[],
    per_page:[{page:1, target:0, contents:['classical_print'],
      decider:{has_classical_print:prob}}],
    plan:{ranges:[{pages:'1', rotation:0, engine:'ndlocr', writing:'vertical_rtl'}]},
    plan_marks:{}, rotation:[], engines:[]};
}
"""
    body = """
workOrderState.key = 'd1|vol1';
await _woScan();
const firstProb = workOrderState.scan.per_page[0].decider.has_classical_print;
prob = 0.99;
await _woScan();
console.log(JSON.stringify({firstProb,
  secondProb:workOrderState.scan.per_page[0].decider.has_classical_print}));
"""
    out = run_js(tmp_path, "work-order.js", names, setup, body)
    # 서버가 준 확률이 접히거나 반올림되지 않고 스캔마다 상태에 그대로 남는다
    assert (out["firstProb"], out["secondProb"]) == (0.51, 0.99)
