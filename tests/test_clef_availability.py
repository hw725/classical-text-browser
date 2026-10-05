"""clef를 고를 수 있는가 — 화면과 서버가 같은 조건을 쓰는가 (D-135 후속, 2026-10-05).

결함: 자동 스캔 라우트(`llm_ocr._decision_client`)는 Cloudflare 키가 없고 OpenRouter 키만 있으면
OpenRouter clef부터 시작하는데, 설정 라우트(`/api/settings/decision-models`)의
`default_image_provider`와 화면의 clef 옵션 활성은 Cloudflare 키만 보았다. 그래서 OpenRouter 키만
있는 사람은 clef를 고를 수 없고 kimi-k3로만 판정됐다.

지키는 것:
  - 키 조합 넷(없음 / OpenRouter만 / Cloudflare만 / 둘 다)에서 `clef_available`·`clef_via`·
    `default_image_provider`가 맞다.
  - 그 값이 자동 스캔 라우트의 판정(`_decision_client("clef", …).has_key`)과 **같다** — 조건이
    두 곳에서 갈라지면 이 시험이 깨진다.
  - 화면(workspace.js)은 clef 옵션의 활성을 `clef_available`로 정한다
    (Cloudflare 칸의 has_key가 아니라).

**이 PC에는 진짜 키가 있다** — 환경변수·Windows 사용자 환경변수(Cloudflare)·개인 키 파일
(`~/.claude/data/triage/.env`, OpenRouter)·프로젝트 .env. 막지 않으면 «키 없음» 경우가 거짓 초록이
되거나 거짓 빨강이 된다. 아래 fixture가 넷을 모두 막고, 첫 시험이 막혔는지부터 확인한다.
네트워크는 쓰지 않는다(check=false — 키가 «있는가»만 본다).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_segmentation import _setup, client  # noqa: F401 — fixture 재사용

_ALL_KEY_ENVS = (
    "PERPLEXITY_API_KEY",
    "TYPESAFE_API_KEY",
    "JEV_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_DECISIONS_URL",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_CLEF_URL",
)


@pytest.fixture(autouse=True)
def _no_ambient_keys(monkeypatch, tmp_path):
    """환경변수·Windows 사용자 환경변수·개인 키 파일·프로젝트 .env를 막고 서고 .env만 읽게 한다."""
    import llm.clef_cf as clef
    import llm.jev as jev

    for k in _ALL_KEY_ENVS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(clef, "_win_user_env", lambda name: None)  # 레지스트리(HKCU\Environment)
    monkeypatch.setattr(jev, "KEY_ENV_FILE", tmp_path / "no-personal-key-file.env")  # 개인 키 파일

    def library_only(names, library_root):
        # 프로젝트 루트 .env를 빼고 서고 .env만 — LlmConfig._env_cache는 둘을 합친다
        if not library_root:
            return None
        p = Path(library_root) / ".env"
        if not p.exists():
            return None
        vals = dict(
            ln.split("=", 1) for ln in p.read_text(encoding="utf-8").splitlines() if "=" in ln
        )
        return next((vals[n].strip() for n in names if vals.get(n, "").strip()), None)

    monkeypatch.setattr(jev, "_key_from_app_env", library_only)


def test_ambient_keys_are_blocked(tmp_path):
    """시험 전제 — 이 PC의 진짜 키가 하나도 보이지 않아야 아래 넷이 의미가 있다."""
    from llm.clef_cf import ClefClient
    from llm.openrouter_decider import OpenRouterClefClient, OpenRouterDecisionClient

    for cls in (ClefClient, OpenRouterClefClient, OpenRouterDecisionClient):
        assert cls(library_root=tmp_path).has_key is False, cls.__name__
        assert cls(library_root=None).has_key is False, cls.__name__


# (서고 .env에 넣을 키, 기대 clef_via)
_CASES = {
    "none": ({}, None),
    "openrouter_only": ({"openrouter": "sk-or-fakeOR12"}, "openrouter"),
    "cloudflare_only": (
        {"cloudflare": "cf-fakeTOKEN", "cloudflare_account": "acc-fake1234"},
        "cloudflare",
    ),
    "both": (
        {
            "openrouter": "sk-or-fakeOR12",
            "cloudflare": "cf-fakeTOKEN",
            "cloudflare_account": "acc-fake1234",
        },
        "cloudflare",  # 둘 다 있으면 Cloudflare(무료 몫)가 사슬의 1단계
    ),
}


@pytest.mark.parametrize("case", list(_CASES))
def test_clef_availability_matches_survey_route(client, case):  # noqa: F811
    keys, via = _CASES[case]
    r = client.post("/api/library/quick-start")
    assert r.status_code == 200, r.text
    lib = Path(r.json()["library_path"])
    if keys:
        r = client.post("/api/settings/llm-keys", json=keys)
        assert r.status_code == 200, r.text
        for v in keys.values():
            assert v not in r.text  # 값은 돌려주지 않는다

    d = client.get("/api/settings/decision-models").json()
    models = {m["id"]: m for m in d["models"]}
    assert models["cloudflare"]["has_key"] is (via == "cloudflare")
    assert models["openrouter"]["has_key"] is ("openrouter" in keys)
    assert d["clef_available"] is (via is not None)
    assert d["clef_via"] == via
    assert d["default_image_provider"] == ("clef" if via else None)

    # 자동 스캔 라우트가 실제로 고르는 클라이언트와 같은 답이어야 한다(조건이 갈라지면 깨진다)
    from app.routers import llm_ocr
    from llm.clef_cf import ClefClient
    from llm.openrouter_decider import OpenRouterClefClient

    c = llm_ocr._decision_client("clef", lib, 0)
    assert c.has_key is d["clef_available"]
    if via == "openrouter":
        assert type(c) is OpenRouterClefClient
    elif via == "cloudflare":
        assert type(c) is ClefClient


def test_survey_without_any_clef_key_says_both_keys(client, tmp_path, monkeypatch):  # noqa: F811
    """키가 둘 다 없으면 자동 스캔은 400이고, 안내는 Cloudflare만이 아니라 OpenRouter도 말한다."""
    from core import env_doctor

    monkeypatch.setattr(env_doctor, "_GPU_RUNTIME", True)
    _lib, part_id = _setup(client, tmp_path)
    r = client.post(
        f"/api/documents/d1/parts/{part_id}/rotation/suggest", json={"force_provider": "clef"}
    )
    assert r.status_code == 400, r.text
    j = r.json()
    assert j["needs_key"] == "cloudflare"
    assert "OpenRouter" in j["error"] and "Cloudflare" in j["error"]


def test_screen_uses_server_clef_available():
    """화면은 clef 옵션의 활성을 서버의 `clef_available`로 정한다(Cloudflare 칸 has_key 아님)."""
    ws = (
        Path(__file__).resolve().parent.parent / "src" / "app" / "static" / "js" / "workspace.js"
    ).read_text(encoding="utf-8")
    start = ws.index('extra.includes("vision-decider")')
    block = ws[start : ws.index("_loadAllLlmModelSelects", start)]
    assert "clef_available" in block
    assert "OpenRouter" in block  # 키 없을 때 안내가 OpenRouter 키로도 된다고 말한다
    # 옛 조건(id cloudflare 모델의 has_key로 clef를 막던 것)이 돌아오지 않게
    assert "x.id === s.id" not in block
    # 「말로 지시」를 열 때 kimi 기본이 미리 고른 clef를 덮지 않는다
    # (2026-10-05 headless 실측으로 드러남)
    js_dir = Path(__file__).resolve().parent.parent / "src" / "app" / "static" / "js"
    wo_js = (js_dir / "work-order.js").read_text(encoding="utf-8")
    start = wo_js.index("function openWorkOrder")
    body = wo_js[start : wo_js.index("function initWorkOrder", start)]
    assert "clefDefaulted" in body and "keepClef" in body
