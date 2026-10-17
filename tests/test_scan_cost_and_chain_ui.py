"""자동 스캔의 《보내기 전 비용》과 《사슬이 넘어간 것》을 화면까지 잇는다.

2026-10-05 리뷰 143 후속.

무엇을 고정하는가:
  1. 미리 세기(dry_run)도 실제 스캔과 **같은 모델 선택**(force_provider·force_model)을
     보낸다. 전에는 `{pages, dry_run}`뿐이라 서버가 engine·cost_usd_est를 내지 않았고,
     OpenRouter 키만 있어 유료 clef가 기본인 사람이 1,000쪽을 스캔해도 비용 어림을 못 봤다
     (전역 규칙 11 — 게이트는 도구 층에). 서버는 clef 사슬(Cloudflare 무료 → OpenRouter
     유료 → 기본 비전 모델)의 단계별 키 유무와 《최대 유료 어림》(`cost_usd_max`)을 준다.
  2. 결과: 사슬이 넘어간 쪽은 **실패가 아니다** — `fallback_steps`(넘어감)와
     `failures`(실패)를 나누고, 옛 `error` 문자열은 그대로 둔다(기존 소비처). 화면은
     넘어감을 《3쪽부터 OpenRouter clef로》로, 실제 쓴 비용(decider_usage)을 짧게,
     needs_key면 설정 《판정 모델》로 가는 안내를 보인다.
  3. 호출 상한은 **논리 호출(ask 한 번)**을 센다 — 429 백오프·clef 413 축소 재전송이
     상한을 갉아 남은 쪽을 유료 OpenRouter로 밀어내지 않는다. 상한에 닿으면
     (JevGateExceeded) 폴백 업체로 넘기지 않고 모델 호출을 멈춘다(상한은 《더 쏘지 말라》).
  4. 측정 스크립트가 업체 클라이언트에 남의 주소를 넘기지 않는다 — eval_clef_survey의
     OpenRouter 길은 `OpenRouterClefClient`이고, OpenRouter 키가 없으면 바로 끝난다
     (PERPLEXITY 키를 openrouter.ai로 보내던 결함).

2026-10-17(D-142) 덧붙임: 사슬은 《설정에서 고른 OpenRouter 이미지 모델(기본 decider v1.2) →
기본 비전 모델》로 바뀌었다(Cloudflare 무료 몫 단계는 직결이라 《추가 예정》). 1·2의 서버 시험은
그 뜻으로 고쳤고, 화면 JS의 옛 clef 안내 시험은 옛 응답을 읽는 갈래가 남아 있어 그대로 둔다.

외부 호출 없음 — 키는 가짜이고 ask는 모두 바꿔 끼운다.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

import llm.clef_cf as clef
import llm.jev as jev
from llm.jev import JevCallFailed, JevClient, JevGateExceeded
from tests.js_harness import run_js
from tests.test_segmentation import _setup, client  # noqa: F401 — fixture 재사용

ROOT = Path(__file__).resolve().parent.parent

_KEY_ENVS = (
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_CLEF_URL",
    "OPENROUTER_API_KEY",
    "OPENROUTER_DECISIONS_URL",
    "PERPLEXITY_API_KEY",
    "TYPESAFE_API_KEY",
    "JEV_API_KEY",
)


@pytest.fixture(autouse=True)
def _no_ambient_keys(monkeypatch, tmp_path):
    """이 PC의 진짜 키(환경변수·Windows 사용자 환경변수·개인 키 파일·프로젝트 .env)를
    섞지 않는다."""
    for k in _KEY_ENVS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(clef, "_win_user_env", lambda name: None)
    monkeypatch.setattr(jev, "KEY_ENV_FILE", tmp_path / "no-personal-key-file.env")
    monkeypatch.setattr(jev, "_key_from_app_env", lambda names, root: None)
    monkeypatch.setattr(jev.time, "sleep", lambda s: None)  # 백오프를 기다리지 않는다
    # 미리 세기의 비전 가용성 확인이 이 PC의 진짜 Ollama에 닿지 않게
    # (그 안내는 tests/test_no_key_notices.py가 잰다)
    import app.routers.llm_ocr as llm_ocr

    async def _no_probe(force_provider):
        return {"checked": False, "ready": []}

    monkeypatch.setattr(llm_ocr, "_vision_readiness", _no_probe)


def _keys(monkeypatch, *, cf: bool, orr: bool):
    if cf:
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-fake-token")
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "cf-fake-account")
    if orr:
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake-key")


def _gpu(monkeypatch):
    from core import env_doctor

    monkeypatch.setattr(env_doctor, "_GPU_RUNTIME", True)


# ── 1. 서버 dry_run: 사슬과 최대 유료 어림 ─────────────────────────────


def _dry(client, part_id, **extra):  # noqa: F811
    url = f"/api/documents/d1/parts/{part_id}/rotation/suggest"
    r = client.post(url, json={"pages": [1, 3], "dry_run": True, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_dry_run_clef_chain_both_keys(client, tmp_path, monkeypatch):  # noqa: F811
    """D-142: 사슬은 《설정의 OpenRouter 이미지 모델(유료) → 기본 비전 모델》 둘이다."""
    from llm.decision_models import DEFAULT_IMAGE_MODEL

    _gpu(monkeypatch)
    _lib, part_id = _setup(client, tmp_path)
    _keys(monkeypatch, cf=True, orr=True)
    d = _dry(client, part_id, force_provider="decision", force_model="decision")
    assert d["engine"] == "decision" and d["model"] == DEFAULT_IMAGE_MODEL
    steps = [(s["step"], s["has_key"]) for s in d["chain"]]
    # 사슬 끝(Ollama)에는 키가 없다 — None, 닿는지는 reachable(여기서는 못 잼 → None)
    assert steps == [("openrouter", True), ("vision", None)]
    assert d["chain"][1]["reachable"] is None
    assert d["chain"][0]["paid"] is True and d["chain"][0]["model"] == DEFAULT_IMAGE_MODEL
    # 쪽당 어림 = 2,400토큰 × 목록 단가(decider v1.2 $0.02/M) — 실측 아님
    assert d["chain"][0]["usd_per_page_est"] == pytest.approx(2400 * 0.02 / 1e6)
    assert d["cost_usd_max"] == pytest.approx(3 * d["chain"][0]["usd_per_page_est"], rel=1e-6)
    assert d["cost_usd_est"] == d["cost_usd_max"] > 0
    assert "needs_key" not in d


def test_dry_run_clef_openrouter_only_is_paid_from_first_page(client, tmp_path, monkeypatch):  # noqa: F811
    """옛 화면 값 "clef"·"decider"도 같은 길(설정의 이미지 모델)로 받는다.

    열어 둔 창이 400이 안 되게.
    """
    _gpu(monkeypatch)
    _lib, part_id = _setup(client, tmp_path)
    _keys(monkeypatch, cf=False, orr=True)
    for old in ("clef", "decider"):
        d = _dry(client, part_id, force_provider=old, force_model=old)
        assert d["engine"] == "decision"
        assert [(s["step"], s["has_key"]) for s in d["chain"]][:1] == [("openrouter", True)]
        assert d["cost_usd_max"] > 0


def test_dry_run_clef_cloudflare_only_has_no_paid_step(client, tmp_path, monkeypatch):  # noqa: F811
    """Cloudflare 키만 있으면 판정 모델은 키 없음이다.

    직결은 《추가 예정》이라 쓰지 않는다(D-142).
    """
    _gpu(monkeypatch)
    _lib, part_id = _setup(client, tmp_path)
    _keys(monkeypatch, cf=True, orr=False)
    d = _dry(client, part_id, force_provider="decision", force_model="decision")
    assert [(s["step"], s["has_key"]) for s in d["chain"]][:1] == [("openrouter", False)]
    assert d["needs_key"] == "openrouter"


def test_dry_run_clef_without_keys_says_needs_key(client, tmp_path, monkeypatch):  # noqa: F811
    _gpu(monkeypatch)
    _lib, part_id = _setup(client, tmp_path)
    d = _dry(client, part_id, force_provider="decision", force_model="decision")
    assert d["needs_key"] == "openrouter"


# ── 2. 서버 결과: 넘어감 ≠ 실패, 실제 비용 ────────────────────────────


def _chain_route(client, tmp_path, monkeypatch, ask):  # noqa: F811
    import app._state as app_state
    from llm.openrouter_decider import OpenRouterModelClient

    _gpu(monkeypatch)
    _lib, part_id = _setup(client, tmp_path)
    _keys(monkeypatch, cf=True, orr=True)
    monkeypatch.setattr(OpenRouterModelClient, "ask", ask)
    # 직결 clef는 이 길에서 쓰이지 않는다(D-142) — 불리면 시험이 깨지게 한다
    monkeypatch.setattr(clef.ClefClient, "ask", lambda *a, **k: pytest.fail("직결 clef를 불렀다"))
    seen: dict = {"router": 0}

    class FakeRouter:
        async def call_with_image(self, prompt, image, **kw):
            seen["router"] += 1
            seen["router_kw"] = kw
            from types import SimpleNamespace

            return SimpleNamespace(
                text='{"orientation": "upright", "contents": []}', provider="ollama", model="kimi"
            )

    monkeypatch.setattr(app_state, "_get_llm_router", lambda: FakeRouter())
    url = f"/api/documents/d1/parts/{part_id}/rotation/suggest"
    r = client.post(
        url, json={"pages": [1, 3], "force_provider": "decision", "force_model": "decision"}
    )
    assert r.status_code == 200, r.text
    return r.json(), seen


_OK = {
    "orientation": {"choice": "upright", "probabilities": {"upright": 0.9}},
    "has_classical_print": {"noul": 0.8},
}


def test_result_separates_fallback_from_failures(client, tmp_path, monkeypatch):  # noqa: F811
    """고른 모델이 2쪽에서 실패하면 2쪽부터 기본 비전 모델이 답한다 — 넘어감이지 실패가 아니다."""
    from llm.decision_models import DEFAULT_IMAGE_MODEL

    state = {"n": 0}

    def ask(self, *a, **k):
        state["n"] += 1
        if state["n"] >= 2:  # 2쪽부터 크레딧 바닥
            raise JevCallFailed("jev_http_error", status=402, detail="insufficient credits")
        self.calls_made += 1
        self.cost_total += 0.0004
        return _OK

    d, seen = _chain_route(client, tmp_path, monkeypatch, ask)
    assert d["fallback"] == "decision→vision"
    assert d["failures"] == []
    steps = d["fallback_steps"]
    assert len(steps) == 1 and steps[0]["page"] == 2
    assert (steps[0]["from"], steps[0]["to"]) == ("openrouter", "vision")
    assert steps[0]["from_model"] == DEFAULT_IMAGE_MODEL and "402" in steps[0]["why"]
    # 옛 소비처: error 문자열에는 그대로 남는다
    assert "기본 비전 모델로" in (d["error"] or "")
    # 2·3쪽은 비전 모델이 답했다 — 고른 모델로 다시 묻지 않는다(1번 실패 후 그 뒤는 비전 모델)
    assert seen["router"] == 2 and state["n"] == 2
    assert (seen["router_kw"]["force_provider"], seen["router_kw"]["force_model"]) == (
        "ollama", "kimi-k3:cloud",
    )
    # 실제 쓴 비용 — 업체별로
    by = {u["provider"]: u for u in d["decider_usage"]["by_provider"]}
    assert set(by) == {"openrouter"}
    assert by["openrouter"]["cost_usd"] == pytest.approx(0.0004)


def test_gate_exceeded_stops_instead_of_paid_fallback(client, tmp_path, monkeypatch):  # noqa: F811
    # 상한은 《더 쏘지 말라》 — 비전 모델로 계속 쏘면 상한의 뜻이 무너진다
    def ask(self, *a, **k):
        raise JevGateExceeded("상한 8회에 이미 도달했습니다.")

    d, seen = _chain_route(client, tmp_path, monkeypatch, ask)
    assert seen["router"] == 0
    assert "fallback" not in d
    assert d["failures"] and "상한" in d["failures"][0]
    assert d["capped_at_page"] == 1


def test_js_dry_note_decision_chain(tmp_path):
    """D-142 미리 세기 안내: 고른 모델 이름·유료·어림·실패하면 기본 비전 모델."""
    dry = {
        "dry_run": True,
        "pages": 1000,
        "calls": 1000,
        "ocr_calls": 2000,
        "engine": "decision",
        "model": "perplexity/pplx-decider-v1.2",
        "cost_usd_est": 0.048,
        "cost_usd_max": 0.048,
        "chain": [
            {"step": "openrouter", "label": "OpenRouter perplexity/pplx-decider-v1.2",
             "model": "perplexity/pplx-decider-v1.2", "has_key": True, "paid": True,
             "usd_per_page_est": 0.000048},
            {"step": "vision", "label": "기본 비전 모델", "has_key": None, "reachable": False,
             "paid": False, "model": "ollama:kimi-k3:cloud"},
        ],
    }
    note = _note(tmp_path, dry)["note"]
    assert "perplexity/pplx-decider-v1.2" in note and "OpenRouter 유료" in note
    assert "$0.048" in note and "kimi-k3" in note and "지금 닿지 않음" in note
    assert "Cloudflare" not in note


# ── 3. 화면 JS: 미리 세기 본문·안내 글, 결과 줄 ─────────────────────────

_NOTE_NAMES = [
    "_woRefreshScanNote",
    "_woScanModelSel",
    "_woScanPages",
    "_woScanUrl",
    "_woTarget",
    "_woDryNote",
    "_woKeyHint",
    "_woUsd",
]

_NOTE_SETUP = """
const els = {};
function el(id) {
  return els[id] || (els[id] = { id, hidden: false, textContent: "", value: "", dataset: {} });
}
const document = { getElementById: (id) => el(id), querySelector: () => null };
els["wo-scan-pages"] = { value: "1-1000" };
els["wo-scan-model-select"] = { value: "clef:clef" };
const ocrState = { gpuRuntime: true };
const viewerState = { docId: "d1", partId: "vol1" };
function showToast() {}
function getLlmModelSelection(id) {
  const v = document.getElementById(id).value;
  const i = v.indexOf(":");
  return { force_provider: v.slice(0, i), force_model: v.slice(i + 1) };
}
const sent = [];
const DRY = __DRY__;
async function fetch(url, opts) {
  sent.push(JSON.parse(opts.body));
  return { ok: true, json: async () => DRY };
}
"""


def _note(tmp_path, dry: dict) -> dict:
    setup = "let _woScanSeq = 0;\n" + _NOTE_SETUP.replace("__DRY__", json.dumps(dry))
    return run_js(
        tmp_path,
        "work-order.js",
        _NOTE_NAMES,
        setup,
        "await _woRefreshScanNote();"
        " console.log(JSON.stringify({sent, note: els['wo-scan-note'].textContent}));",
    )


_CHAIN = [
    {
        "step": "cloudflare",
        "label": "Cloudflare clef",
        "has_key": True,
        "paid": False,
        "free_pages_per_day": 250,
    },
    {
        "step": "openrouter",
        "label": "OpenRouter clef",
        "has_key": True,
        "paid": True,
        "usd_per_page_est": 0.000576,
    },
    {
        "step": "vision",
        "label": "기본 비전 모델",
        "has_key": True,
        "paid": False,
        "model": "ollama:kimi-k3:cloud",
    },
]


def test_js_dry_run_sends_model_selection_and_shows_chain_cost(tmp_path):
    dry = {
        "dry_run": True,
        "pages": 1000,
        "calls": 1000,
        "ocr_calls": 2000,
        "engine": "clef",
        "cost_usd_est": 0.576,
        "cost_usd_max": 0.576,
        "chain": _CHAIN,
    }
    out = _note(tmp_path, dry)
    body = out["sent"][0]
    assert body["dry_run"] is True and body["pages"] == [1, 1000]
    assert (body["force_provider"], body["force_model"]) == ("clef", "clef")
    note = out["note"]
    assert "Cloudflare 무료" in note and "OpenRouter 유료" in note
    assert "$0.58" in note  # 최대 어림
    assert "kimi-k3" in note  # 사슬 끝


def test_js_dry_note_openrouter_only_and_no_key(tmp_path):
    chain = [dict(_CHAIN[0], has_key=False), _CHAIN[1], _CHAIN[2]]
    out = _note(
        tmp_path,
        {
            "dry_run": True,
            "pages": 10,
            "calls": 10,
            "ocr_calls": 20,
            "engine": "clef",
            "cost_usd_est": 0.00576,
            "cost_usd_max": 0.00576,
            "chain": chain,
        },
    )
    # Cloudflare 키가 없으면 첫 쪽부터 유료다 — 《무료 몫 먼저》라고 말하면 안 된다
    assert "Cloudflare 무료" not in out["note"]
    assert "OpenRouter" in out["note"] and "유료" in out["note"] and "$0.0058" in out["note"]
    out = _note(
        tmp_path,
        {
            "dry_run": True,
            "pages": 10,
            "calls": 10,
            "ocr_calls": 20,
            "engine": "clef",
            "cost_usd_est": 0.00576,
            "cost_usd_max": 0,
            "needs_key": "cloudflare",
            "chain": [dict(s, has_key=s["step"] == "vision") for s in _CHAIN],
        },
    )
    assert "판정 모델" in out["note"] and "키" in out["note"]


_SUM_NAMES = ["_woScanSummary", "_woUsd", "_woFallbackText", "_woUsageText"]


def _summary(tmp_path, d: dict) -> dict:
    setup = f"const D = {json.dumps(d, ensure_ascii=False)};"
    return run_js(
        tmp_path,
        "work-order.js",
        _SUM_NAMES,
        setup,
        "console.log(JSON.stringify(_woScanSummary(D, true, {})));",
    )


def test_js_summary_shows_fallback_not_as_failure(tmp_path):
    d = {
        "checked": 3,
        "rotation": [],
        "engines": [],
        "unknown": 0,
        "provider": "openrouter",
        "model": "cloudflare/clef",
        "fallback": "cloudflare→openrouter",
        "failures": [],
        "fallback_steps": [
            {
                "page": 3,
                "from": "cloudflare",
                "to": "openrouter",
                "why": "429: daily free allocation",
            }
        ],
        "error": "3쪽: Cloudflare clef 429: daily — 이 쪽부터 OpenRouter clef로",
        "decider_usage": {
            "calls": 3,
            "cost_usd": 0.0012,
            "by_provider": [
                {"provider": "cloudflare", "calls": 2, "cost_usd": 0.0008},
                {"provider": "openrouter", "calls": 1, "cost_usd": 0.0004},
            ],
        },
    }
    s = _summary(tmp_path, d)
    assert s["kind"] == "success"
    assert "일부 실패" not in s["text"]
    assert "3쪽부터 OpenRouter clef로" in s["text"]
    assert "$0.0004" in s["text"]  # 실제 청구된 유료 몫


def test_js_summary_failures_still_warn(tmp_path):
    d = {
        "checked": 3,
        "rotation": [],
        "engines": [],
        "unknown": 1,
        "failures": ["2쪽 이미지 없음"],
        "error": "2쪽 이미지 없음",
    }
    s = _summary(tmp_path, d)
    assert s["kind"] == "warning" and "일부 실패: 2쪽 이미지 없음" in s["text"]


def test_js_summary_old_server_error_only_still_warns(tmp_path):
    # failures 칸이 없는 옛 응답 — error로 경고한다
    s = _summary(tmp_path, {"checked": 1, "error": "1쪽: 무엇"})
    assert s["kind"] == "warning"


def test_post_survey_stream_keeps_needs_key(tmp_path):
    out = run_js(
        tmp_path,
        "pdf-renderer.js",
        ["_postSurveyStream"],
        "async function fetch() { return { ok: false, status: 400, body: null,"
        " json: async () => ({ error: '키가 없습니다', needs_key: 'cloudflare' }) }; }",
        "try { await _postSurveyStream('/x', {}, () => {}); console.log('{}'); }"
        " catch (e) { console.log(JSON.stringify({ msg: e.message, nk: e.needsKey })); }",
    )
    assert out == {"msg": "키가 없습니다", "nk": "cloudflare"}


# ── 4. 호출 상한은 논리 호출을 센다 ────────────────────────────────────


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(req, code: int, body: bytes = b"{}"):
    import urllib.error

    return urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(body))


def test_429_retry_does_not_eat_the_cap():
    n = {"i": 0}

    def op(req, timeout=None):
        n["i"] += 1
        if n["i"] == 1:
            raise _http_error(req, 429)
        return _Resp(json.dumps({"answers": {"q": {"noul": 0.5}}, "usage": {}}).encode())

    c = JevClient(api_key="k", max_calls=2, opener=op)
    q = {"q": {"type": "noul", "instructions": "?"}}
    c.ask("s", q)  # 429 → 다시 보냄: HTTP 2번, 묻기 1번
    c.ask("s", q)  # 상한 2 — 묻기 두 번째라 통과해야 한다
    assert c.calls_made == 3 and c.usage()["asks"] == 2
    with pytest.raises(JevGateExceeded):
        c.ask("s", q)


def test_clef_413_shrink_resend_is_one_ask(tmp_path):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (3000, 3000), "white").save(buf, format="PNG")
    msg = b'{"errors":[{"message":"(208453) exceeded this model context window limit (65536)"}]}'
    n = {"i": 0}

    def op(req, timeout=None):
        n["i"] += 1
        if n["i"] == 1:
            raise _http_error(req, 413, msg)
        payload = {"result": {"answers": {"q": {"noul": 0.7}}, "usage": {}}, "success": True}
        return _Resp(json.dumps(payload).encode())

    c = clef.ClefClient(api_key="t", account_id="a", max_calls=1, opener=op, library_root=tmp_path)
    ans = c.ask(
        "s", {"q": {"type": "noul", "instructions": "?"}}, images=[(buf.getvalue(), "image/png")]
    )
    assert ans["q"]["noul"] == 0.7 and n["i"] == 2


# ── 5. 측정 스크립트: 남의 주소로 키를 보내지 않는다 ────────────────────


def _load_eval():
    spec = importlib.util.spec_from_file_location(
        "eval_clef_survey_t", ROOT / "scripts" / "eval_clef_survey.py"
    )
    m = importlib.util.module_from_spec(spec)
    argv = sys.argv
    sys.argv = ["x"]
    try:
        spec.loader.exec_module(m)
    finally:
        sys.argv = argv
    return m


def test_eval_openrouter_client_never_uses_perplexity_key(tmp_path, monkeypatch):
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-FAKE")
    m = _load_eval()
    with pytest.raises(SystemExit):
        m._openrouter_client("or-clef", tmp_path, 1)


def test_eval_openrouter_client_is_openrouter_clef(tmp_path, monkeypatch):
    from llm.openrouter_decider import OpenRouterClefClient

    monkeypatch.setenv("OPENROUTER_API_KEY", "or-FAKE")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-FAKE")
    m = _load_eval()
    for engine, model in m.OPENROUTER_ENGINES.items():
        c = m._openrouter_client(engine, tmp_path, 1)
        assert isinstance(c, OpenRouterClefClient)
        assert c.PROVIDER == "openrouter" and c.model == model
        assert c._url.startswith("https://openrouter.ai/") and c._key == "or-FAKE"


def test_scripts_do_not_hand_foreign_urls_to_vendor_clients():
    """scripts/ 아래 어디서도 업체 클라이언트(…Client)에 url=을 넘기지 않는다 — 주소는
    클래스가 정한다.

    클라이언트는 KEY_NAMES로 제 업체 키를 찾는데 url만 남의 것으로 바꾸면, 제 키가 남의
    주소로 나간다.
    """
    bad = []
    for p in sorted((ROOT / "scripts").glob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Name):
                name = f.id
            elif isinstance(f, ast.Attribute):
                name = f.attr
            else:
                name = ""
            if name.endswith("Client") and any(k.arg == "url" for k in node.keywords):
                bad.append(f"{p.name}:{node.lineno} {name}(url=…)")
    assert bad == []
