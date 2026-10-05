"""판정 모델 — Perplexity Decider(이미지) 도입과 화면에서 키 넣기 (D-134).

무엇을 고정하는가:
  - Decider는 문서의 계약대로 보낸다: 주소·Bearer·모델 id·이미지는 state 배열 안 data URL
  - 큰 이미지는 보내기 전에 상한(32×32 타일 2,048개) 안으로 줄인다 — 넘기면 1분 뒤 504
  - 키는 설정 화면이 쓰는 **서고 .env**에서 찾는다(Jev도).
    Decider는 Jev의 개인 키 파일을 보지 않는다
  - Jev에 이미지를 주면 보내기 전에 거부한다(Jev는 base64를 글자로 읽어 엉뚱한 답을 준다)
  - 429의 Retry-After를 따른다
  - 판정 모델 호출도 서고의 LLM 사용 기록에 남는다
  - 자동 스캔이 «판정 모델»을 고르면 생성 LLM 대신 Decider의 확률로 종류를 정한다
  - 설정 화면 «판정 모델»: 상태 라우트·키 저장(값은 돌려주지 않는다)
"""

from __future__ import annotations

import base64
import io
import json
import urllib.error

import pytest

from llm.decider import MAX_TILES, TILE, DeciderClient, fit_image
from llm.jev import JevCallFailed, JevClient


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(capture: list, answers: dict, usage=None):
    def op(req, timeout=None):
        capture.append(req)
        return _Resp(
            json.dumps({"answers": answers, "usage": usage or {"input_tokens": 1000}}).encode()
        )

    return op


def _png(w: int, h: int) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _no_ambient_keys(monkeypatch, tmp_path):
    """이 PC의 키를 시험에 섞지 않는다 — 환경변수·프로젝트 루트 .env·공용 키 파일을 모두 막는다.

    프로젝트 루트 .env에 PERPLEXITY_API_KEY를 두면 «키 없음» 시험이 깨지고, 자동 스캔 시험은 진짜로
    부를 뻔했다(2026-10-02 검토 지적). 서고 .env만 읽게 바꿔 둔다.
    """
    import llm.clef_cf as clef
    import llm.jev as jev

    for k in (
        "PERPLEXITY_API_KEY",
        "TYPESAFE_API_KEY",
        "JEV_API_KEY",
        "OPENROUTER_API_KEY",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_CLEF_URL",
    ):
        monkeypatch.delenv(k, raising=False)
    # 이 PC는 Cloudflare 키가 Windows 사용자 환경변수에 있다(D-135) — 레지스트리도 막는다
    monkeypatch.setattr(clef, "_win_user_env", lambda name: None)
    monkeypatch.setattr(jev, "KEY_ENV_FILE", tmp_path / "no-personal-key-file.env")

    def library_only(names, library_root):
        if not library_root:
            return None
        p = library_root / ".env"
        if not p.exists():
            return None
        vals = dict(
            ln.split("=", 1) for ln in p.read_text(encoding="utf-8").splitlines() if "=" in ln
        )
        return next((vals[n].strip() for n in names if vals.get(n, "").strip()), None)

    monkeypatch.setattr(jev, "_key_from_app_env", library_only)


def test_decider_request_matches_documented_contract(tmp_path):
    cap: list = []
    c = DeciderClient(
        api_key="pplx-test",
        opener=_opener(cap, {"q": {"type": "noul", "noul": 0.9}}),
        library_root=tmp_path,
    )
    c.ask(
        "한 쪽", {"q": {"type": "noul", "instructions": "?"}}, images=[(_png(40, 30), "image/png")]
    )
    req = cap[0]
    assert req.full_url == "https://api.perplexity.ai/v1/decisions"  # 끝에 / 붙이면 404
    assert req.get_header("Authorization") == "Bearer pplx-test"
    body = json.loads(req.data)
    assert body["model"] == "decider-27b"
    assert body["state"][0] == "한 쪽"
    img = body["state"][1]
    assert img["type"] == "image_url" and img["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    assert set(body) == {"model", "state", "questions"}  # 모르는 최상위 칸은 400
    assert c.usage()["cost_usd"] == pytest.approx(1000 * 0.04 / 1e6)


def test_big_image_is_shrunk_below_tile_limit():
    from PIL import Image

    data, mime = fit_image(_png(3000, 2200), "image/png")
    w, h = Image.open(io.BytesIO(data)).size
    assert -(-w // TILE) * -(-h // TILE) <= MAX_TILES and mime == "image/jpeg"
    small = _png(400, 300)
    assert fit_image(small, "image/png") == (small, "image/png")  # 작은 것은 다시 압축하지 않는다


def test_keys_come_from_library_env(tmp_path, monkeypatch):
    """설정 화면이 넣은 키(서고 .env)를 Decider와 Jev가 모두 읽는다. 환경변수가 이긴다."""
    import llm.jev as jev

    monkeypatch.setattr(jev, "KEY_ENV_FILE", tmp_path / "no-such.env")
    (tmp_path / ".env").write_text(
        "PERPLEXITY_API_KEY=pplx-lib\nTYPESAFE_API_KEY=ts-lib\n", encoding="utf-8"
    )
    assert DeciderClient(library_root=tmp_path).has_key
    assert JevClient(library_root=tmp_path).has_key
    monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-env")
    assert DeciderClient(library_root=tmp_path)._key == "pplx-env"


def test_key_name_order_beats_source_order(tmp_path, monkeypatch):
    """서고 .env의 OPENROUTER 키가 키 파일의 TYPESAFE 키를 이기면 안 된다 — 이름 순서가 먼저다."""
    import llm.jev as jev

    f = tmp_path / "triage.env"
    f.write_text("TYPESAFE_API_KEY=ts-from-file\n", encoding="utf-8")
    monkeypatch.setattr(jev, "KEY_ENV_FILE", f)
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / ".env").write_text("OPENROUTER_API_KEY=or-from-library\n", encoding="utf-8")
    assert JevClient(library_root=lib)._key == "ts-from-file"


def test_decider_does_not_read_jev_personal_key_file(tmp_path, monkeypatch):
    import llm.jev as jev

    f = tmp_path / "triage.env"
    f.write_text("PERPLEXITY_API_KEY=should-not-be-used\n", encoding="utf-8")
    monkeypatch.setattr(jev, "KEY_ENV_FILE", f)
    empty_lib = tmp_path / "lib"
    empty_lib.mkdir()
    assert not DeciderClient(library_root=empty_lib).has_key


def test_jev_refuses_images_before_sending():
    cap: list = []
    c = JevClient(api_key="k", opener=_opener(cap, {}))
    with pytest.raises(JevCallFailed, match="images_not_supported"):
        c.ask("s", {"q": {"type": "noul", "instructions": "?"}}, images=[(b"x", "image/png")])
    assert cap == [] and c.calls_made == 0


def test_retry_after_is_honoured(monkeypatch):
    import llm.jev as jev

    slept: list = []
    monkeypatch.setattr(jev.time, "sleep", lambda s: slept.append(s))
    calls = {"n": 0}

    def op(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(
                req.full_url, 429, "too many", {"Retry-After": "3"}, io.BytesIO(b"")
            )
        return _Resp(json.dumps({"answers": {}, "usage": {"input_tokens": 5}}).encode())

    DeciderClient(api_key="k", opener=op).ask("s", {"q": {"type": "noul", "instructions": "?"}})
    assert slept == [3.0] and calls["n"] == 2


def test_decision_calls_are_logged_to_library_usage(tmp_path):
    cap: list = []
    DeciderClient(api_key="k", opener=_opener(cap, {}), library_root=tmp_path).ask(
        "s", {"q": {"type": "noul", "instructions": "?"}}, purpose="page_survey"
    )
    log = (tmp_path / "llm_usage_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
    entry = json.loads(log[-1])
    assert entry["provider"] == "perplexity" and entry["model"] == "decider-27b"
    assert entry["purpose"] == "page_survey" and entry["tokens_in"] == 1000


def test_parse_decider_answers_threshold_and_blank():
    from core.page_survey import decider_questions, parse_decider_answers

    q = decider_questions()
    assert q["orientation"]["type"] == "choice" and set(q["orientation"]["criteria"]) == {
        "upright",
        "needs_cw",
        "needs_ccw",
        "upside_down",
    }
    assert all(q[k]["type"] == "noul" for k in q if k.startswith("has_"))
    ans = {
        "orientation": {"type": "choice", "choice": "needs_cw", "probabilities": {"needs_cw": 0.8}},
        "has_classical_print": {"noul": 0.9},
        "has_kunten": {"noul": 0.55},
        "has_hangul": {"noul": 0.2},
        "has_blank": {"noul": True},  # bool은 확률이 아니다 — 버린다
    }
    o, contents, probs = parse_decider_answers(ans)
    assert o == "needs_cw" and contents == ["classical_print", "kunten"]
    assert probs["contents"]["hangul"] == 0.2 and "blank" not in probs["contents"]
    o, contents, _ = parse_decider_answers(
        {
            "orientation": {"choice": "sideways"},
            "has_blank": {"noul": 0.9},
            "has_hangul": {"noul": 0.7},
        }
    )
    assert o is None and contents == [
        "blank"
    ]  # 정해진 선택지가 아니면 버리고, 백지면 나머지를 지운다


# ── 화면·라우트 ──

from tests.test_segmentation import _setup, client  # noqa: E402,F401 — fixture 재사용


def test_settings_route_lists_models_and_saves_keys(client, tmp_path):  # noqa: F811
    _setup(client, tmp_path)  # 서고를 하나 세운다 — 키는 그 서고 .env에 쓴다
    r = client.get("/api/settings/decision-models")
    assert r.status_code == 200
    models = {m["id"]: m for m in r.json()["models"]}
    assert set(models) == {"cloudflare", "perplexity", "openrouter", "typesafe"}
    assert r.json()["default_image_provider"] is None  # 키가 없으면 기본은 그대로(생성 비전 LLM)
    assert models["perplexity"]["signup_url"] == "https://console.perplexity.ai/project/keys"
    r = client.post("/api/settings/llm-keys", json={"perplexity": "pplx-abcdWXYZ"})
    assert r.status_code == 200, r.text
    assert "pplx-abcdWXYZ" not in r.text and r.json()["keys"]["perplexity"]["hint"] == "…WXYZ"
    models = {m["id"]: m for m in client.get("/api/settings/decision-models").json()["models"]}
    assert models["perplexity"]["has_key"] is True and models["perplexity"]["status"] == "unchecked"


def test_survey_with_decider_uses_probabilities(client, tmp_path, monkeypatch):  # noqa: F811
    import llm.decider as dec
    from core import env_doctor

    monkeypatch.setattr(env_doctor, "_GPU_RUNTIME", True)
    _lib, part_id = _setup(client, tmp_path)
    url = f"/api/documents/d1/parts/{part_id}/rotation/suggest"

    # 키가 없으면 보내기 전에 화면이 할 일을 알려 준다
    r = client.post(url, json={"force_provider": "decider", "force_model": "decider-27b"})
    assert r.status_code == 400 and r.json()["needs_key"] == "perplexity"

    r = client.post(url, json={"dry_run": True, "force_provider": "decider"})
    assert r.json()["engine"] == "decider" and r.json()["cost_usd_est"] > 0

    sent: list = []

    def fake_ask(self, state, questions, *, images=(), purpose=""):
        sent.append((len(images), purpose, sorted(questions)))
        return {
            "orientation": {"choice": "upright", "probabilities": {"upright": 0.9}},
            "has_modern_print": {"noul": 0.92},
            "has_hangul": {"noul": 0.1},
        }

    monkeypatch.setattr(dec.DeciderClient, "has_key", property(lambda self: True))
    monkeypatch.setattr(dec.DeciderClient, "ask", fake_ask)
    r = client.post(url, json={"force_provider": "decider", "force_model": "decider-27b"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["provider"] == "perplexity" and d["model"] == "decider-27b"
    assert len(sent) == 3 and all(n == 1 and p == "page_survey" for n, p, _ in sent)
    assert d["per_page"][0]["contents"] == ["modern_print"]
    assert d["per_page"][0]["decider"]["contents"]["modern_print"] == 0.92
    assert "decider_usage" in d


def test_scan_select_offers_decider_option():
    """화면: 자동 스캔의 «종류 판정 모델»에 판정 모델 선택지가 붙는다(생성 모델 목록 밖이다)."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src" / "app" / "static"
    html = (root / "index.html").read_text(encoding="utf-8")
    assert 'id="wo-scan-model-select"' in html and 'data-extra-options="vision-decider"' in html
    assert 'id="settings-decision-models"' in html
    ws = (root / "js" / "workspace.js").read_text(encoding="utf-8")
    assert '"decider:decider-27b"' in ws
    assert '"clef:clef"' in ws and "default_image_provider" in ws  # D-135 — 키가 있으면 기본
    sp = (root / "js" / "setup-panel.js").read_text(encoding="utf-8")
    assert "perplexity:" in sp and "/api/settings/decision-models" in sp


def test_decider_image_is_real_base64(tmp_path):
    cap: list = []
    png = _png(20, 20)
    DeciderClient(api_key="k", opener=_opener(cap, {})).ask("s", {}, images=[(png, "image/png")])
    url = json.loads(cap[0].data)["state"][1]["image_url"]["url"]
    assert base64.b64decode(url.split(",", 1)[1]) == png
