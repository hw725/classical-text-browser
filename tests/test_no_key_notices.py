"""키도 비전 모델도 없는 PC에서 «보내기 전 안내»가 사실을 말한다 (2026-10-06 설치 검증 후속).

설치 검증(새 PC 흉내 — 키 없음, Ollama 닿지 않음)에서 나온 빈틈 셋:
  a. 편성 «판정 모델로 고르기» 미리 보기가 키가 하나도 없는데 «13행 · 질문 13개 · 호출 1번 ·
     약 $0.000069 · TypeSafe Jev»로만 말했다 — 누르면 400. 미리 보기(dry_run) 응답이
     `has_key`·`needs_key`를 싣고 화면이 «키 없음 — 설정 → «판정 모델»»을 보인다.
  b. 자동 스캔의 «자동»·비전 모델 항목이 쓸 수 있는 비전 모델이 하나도 없어도 «비전 모델 3번 …
     쪽마다 몇 초»만 말했다. 서버가 라우터의 가용성 확인(`is_available_cached`, 시간 제한)으로
     «닿는 비전 프로바이더»를 세어 `vision_ready`·`no_vision`을 싣고, 화면이 그것을 말한다.
     시간 안에 못 재면 `vision_checked: False`(모름) — «없다»고 하지 않는다.
  c. clef 사슬의 마지막 단계(기본 비전 모델, Ollama)를 Ollama가 닿지 않아도 has_key=true로
     안내했다. Ollama에는 키라는 것이 없다 — `has_key`는 None, 닿는지는 `reachable`
     (True/False, 못 재면 None)로 따로 말하고 화면은 «지금 닿지 않음»을 붙인다.

외부 호출 없음 — 키는 지우고, 라우터는 가짜로 바꾼다.
"""

from __future__ import annotations

import json

import pytest

import llm.clef_cf as clef
import llm.jev as jev
from tests.js_harness import run_js
from tests.test_segmentation import _setup, client  # noqa: F401 — fixture 재사용

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


class _Prov:
    def __init__(self, pid: str, ok: bool, image: bool = True):
        self.provider_id = pid
        self.supports_image = image
        self._ok = ok

    async def is_available(self):
        return self._ok


class _Router:
    """비전 프로바이더의 가용성만 답하는 가짜 라우터 — 네트워크 없음."""

    def __init__(self, ready: set[str]):
        ids = ["ollama", "openai_oauth", "gemini", "openai", "anthropic"]
        self.providers = [_Prov(i, i in ready) for i in ids]
        self.asked: list[str] = []

    async def is_available_cached(self, p):
        self.asked.append(p.provider_id)
        return await p.is_available()


def _router(monkeypatch, ready: set[str]) -> _Router:
    import app._state as app_state

    r = _Router(ready)
    monkeypatch.setattr(app_state, "_get_llm_router", lambda: r)
    return r


def _gpu(monkeypatch):
    from core import env_doctor

    monkeypatch.setattr(env_doctor, "_GPU_RUNTIME", True)


# ── a. 편성 «판정 모델로 고르기» 미리 보기 ─────────────────────────────


def _judge_dry(client, part_id):  # noqa: F811
    r = client.post(
        "/api/documents/d1/segmentation/structure/llm",
        json={"part_id": part_id, "engine": "jev", "dry_run": True},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_a_judge_dry_run_says_no_key(client, tmp_path):  # noqa: F811
    _lib, part_id = _setup(client, tmp_path)
    d = _judge_dry(client, part_id)
    assert d["dry_run"] is True
    assert d["has_key"] is False
    assert d["needs_key"] == "openrouter"  # 실제 실행의 400과 같은 칸 id


def test_a_judge_dry_run_with_key_has_no_needs_key(client, tmp_path, monkeypatch):  # noqa: F811
    _lib, part_id = _setup(client, tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake-key")
    d = _judge_dry(client, part_id)
    assert d["has_key"] is True and "needs_key" not in d


def _judge_note(tmp_path, dry: dict) -> str:
    setup = (
        "const els = {};\n"
        "const document = { getElementById: (id) =>"
        " els[id] || (els[id] = { id, textContent: '' }) };\n"
        "const viewerState = { docId: 'd1', partId: 'vol1' };\n"
        f"const DRY = {json.dumps(dry, ensure_ascii=False)};\n"
        "async function fetch() { return { ok: true, json: async () => DRY }; }\n"
    )
    out = run_js(
        tmp_path,
        "composition-editor.js",
        ["_updateLlmJudgeNote", "_judgeName"],
        setup,
        "await _updateLlmJudgeNote();"
        " console.log(JSON.stringify({ note: els['comp-llm-opt-judge-note'].textContent }));",
    )
    return out["note"]


_JUDGE_DRY = {
    "proposals": [],
    "dry_run": True,
    "engine": "jev",
    "lines": 13,
    "chars": 400,
    "calls": 1,
    "questions": 13,
    "toc_entries": 0,
    "cost_usd_est": 0.000069,
    "judge": "typesafe:jev-latest",
    "toc_judge": None,
}


def test_a_judge_note_says_no_key(tmp_path):
    note = _judge_note(tmp_path, dict(_JUDGE_DRY, has_key=False, needs_key="openrouter"))
    assert "키 없음" in note and "판정 모델" in note
    assert "13행" in note  # 크기는 그대로 보인다


def test_a_judge_note_with_key_has_no_warning(tmp_path):
    note = _judge_note(tmp_path, dict(_JUDGE_DRY, has_key=True))
    assert "키 없음" not in note and "13행" in note


# ── b. 자동 스캔 미리 세기 — 쓸 수 있는 비전 모델 ─────────────────────────


def _scan_dry(client, part_id, **extra):  # noqa: F811
    url = f"/api/documents/d1/parts/{part_id}/rotation/suggest"
    r = client.post(url, json={"pages": [1, 3], "dry_run": True, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_b_auto_with_no_vision_provider_says_so(client, tmp_path, monkeypatch):  # noqa: F811
    _gpu(monkeypatch)
    _lib, part_id = _setup(client, tmp_path)
    _router(monkeypatch, ready=set())
    d = _scan_dry(client, part_id)
    assert d["vision_checked"] is True
    assert d["vision_ready"] == []
    assert d["no_vision"] is True


def test_b_forced_provider_checks_only_that_one(client, tmp_path, monkeypatch):  # noqa: F811
    _gpu(monkeypatch)
    _lib, part_id = _setup(client, tmp_path)
    r = _router(monkeypatch, ready={"gemini"})
    d = _scan_dry(client, part_id, force_provider="ollama", force_model="auto")
    assert d["no_vision"] is True and r.asked == ["ollama"]
    d = _scan_dry(client, part_id)  # 자동이면 gemini 하나로 된다
    assert d["vision_ready"] == ["gemini"] and "no_vision" not in d


def test_b_orientation_only_does_not_probe(client, tmp_path, monkeypatch):  # noqa: F811
    _lib, part_id = _setup(client, tmp_path)
    r = _router(monkeypatch, ready=set())
    d = _scan_dry(client, part_id, orientation_only=True)
    assert r.asked == [] and "no_vision" not in d


_WO_NAMES = ["_woDryNote", "_woKeyHint", "_woUsd"]


def _wo_note(tmp_path, dry: dict, sel: dict | None = None) -> str:
    setup = f"const D = {json.dumps(dry, ensure_ascii=False)}; const SEL = {json.dumps(sel or {})};"
    return run_js(
        tmp_path,
        "work-order.js",
        _WO_NAMES,
        setup,
        "console.log(JSON.stringify({ note: _woDryNote(D, SEL) }));",
    )["note"]


_SCAN_DRY = {"dry_run": True, "pages": 3, "calls": 3, "ocr_calls": 6}


def test_b_scan_note_says_no_vision_model(tmp_path):
    note = _wo_note(
        tmp_path, dict(_SCAN_DRY, vision_checked=True, vision_ready=[], no_vision=True)
    )
    assert "비전 모델" in note and "없" in note
    assert "쪽마다 몇 초" not in note


def test_b_scan_note_unchanged_when_vision_ready(tmp_path):
    note = _wo_note(tmp_path, dict(_SCAN_DRY, vision_checked=True, vision_ready=["ollama"]))
    assert "쪽마다 몇 초" in note


# ── c. clef 사슬의 마지막 단계 — Ollama가 닿는가 ──────────────────────────


def test_c_clef_chain_vision_step_is_not_claimed_as_keyed(client, tmp_path, monkeypatch):  # noqa: F811
    _gpu(monkeypatch)
    _lib, part_id = _setup(client, tmp_path)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-fake-token")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "cf-fake-account")
    _router(monkeypatch, ready=set())  # Ollama 닿지 않음
    d = _scan_dry(client, part_id, force_provider="clef", force_model="clef")
    vis = next(s for s in d["chain"] if s["step"] == "vision")
    assert vis["has_key"] is not True  # Ollama에는 키가 없다 — «키 있음»이라고 하지 않는다
    assert vis["reachable"] is False


def test_c_clef_chain_vision_step_reachable(client, tmp_path, monkeypatch):  # noqa: F811
    _gpu(monkeypatch)
    _lib, part_id = _setup(client, tmp_path)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-fake-token")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "cf-fake-account")
    _router(monkeypatch, ready={"ollama"})
    d = _scan_dry(client, part_id, force_provider="clef", force_model="clef")
    vis = next(s for s in d["chain"] if s["step"] == "vision")
    assert vis["reachable"] is True


def _chain(reachable):
    return [
        {"step": "cloudflare", "label": "Cloudflare clef", "has_key": True, "paid": False,
         "free_pages_per_day": 250},
        {"step": "openrouter", "label": "OpenRouter clef", "has_key": False, "paid": True,
         "usd_per_page_est": 0.000576},
        {"step": "vision", "label": "기본 비전 모델", "has_key": None, "reachable": reachable,
         "paid": False, "model": "ollama:kimi-k3:cloud"},
    ]


def test_c_scan_note_says_last_step_unreachable(tmp_path):
    dry = dict(_SCAN_DRY, engine="clef", cost_usd_est=0.0017, cost_usd_max=0.0, chain=_chain(False))
    note = _wo_note(tmp_path, dry)
    assert "kimi-k3" in note and "닿지 않" in note


def test_c_scan_note_reachable_has_no_warning(tmp_path):
    dry = dict(_SCAN_DRY, engine="clef", cost_usd_est=0.0017, cost_usd_max=0.0, chain=_chain(True))
    assert "닿지 않" not in _wo_note(tmp_path, dry)
