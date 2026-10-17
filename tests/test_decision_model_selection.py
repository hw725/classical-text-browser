"""판정 모델을 OpenRouter 목록에서 고른다 (D-142, 사용자 결정 2026-10-17).

무엇을 고정하는가:
  - 기본값: 텍스트 `typesafe/jev-1.14` · 텍스트 폴백 `perplexity/pplx-decider-v1.2` ·
    이미지 `perplexity/pplx-decider-v1.2`(사용자 지시).
    저장은 앱 설정 config.json의 `decision_models`.
  - 모양이 틀린 id는 저장하지 않는다(400) — 화면에서 온 값이 본문·로그에 그대로 들어간다.
    폴백만 빈 값(《폴백 없음》)을 받는다.
  - 목록: OpenRouter `/models?output_modalities=decisions`를 한 시간 캐시하고, 닿지 않으면 앱에 든
    목록(27개)으로 물러선다 — 예외를 내지 않는다.
  - 고른 모델의 클라이언트(`OpenRouterModelClient`): 주소는 OpenRouter decisions, 키는
    OPENROUTER_API_KEY만, 본문 모델은 고른 id, 이미지는 state 배열의 image_url, 단가는 목록의 것,
    목록이 《텍스트만》이라 하면 이미지를 보내기 전에 거부한다.
  - 문턱 계통: Jev 계열은 Jev 값(0.85/0.5), decider 계열은 decider 값(0.997/0.69), 잰 적 없는 다른
    업체 모델은 Jev 값 — 업체가 openrouter라는 이유로 decider 값을 받지 않는다.

외부 호출 없음 — opener를 가짜로 끼우고, 이 PC의 실제 키는 막는다.
"""

from __future__ import annotations

import base64
import io
import json
import time

import pytest

import llm.decision_models as dm
import llm.jev as jev_mod
from llm.decision_models import (
    BUILTIN_CATALOG,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_TEXT_FALLBACK_MODEL,
    DEFAULT_TEXT_MODEL,
)
from llm.jev import JevCallFailed
from llm.openrouter_decider import OPENROUTER_DECISIONS_URL, OpenRouterModelClient, judge_family
from tests.test_segmentation import _setup, client  # noqa: F401 — fixture 재사용


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """앱 설정 파일·목록 캐시·실제 키를 시험마다 새로 — 저장한 고름이 다른 시험으로 새지 않게."""
    import core.app_config as app_config

    cfg_dir = tmp_path / "cfg"
    monkeypatch.setattr(app_config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(app_config, "CONFIG_FILE", cfg_dir / "config.json")
    monkeypatch.setattr(dm, "_cache", {"at": 0.0, "models": None})
    for k in ("OPENROUTER_API_KEY", "TYPESAFE_API_KEY", "JEV_API_KEY", "OPENROUTER_DECISIONS_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(jev_mod, "KEY_ENV_FILE", tmp_path / "no-personal-key-file.env")

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

    monkeypatch.setattr(jev_mod, "_key_from_app_env", library_only)


# ── 고름: 기본값·저장·검증 ────────────────────────────────────────────────────


def test_defaults_are_the_user_choice():
    assert DEFAULT_TEXT_MODEL == "typesafe/jev-1.14"
    assert DEFAULT_TEXT_FALLBACK_MODEL == "perplexity/pplx-decider-v1.2"
    assert DEFAULT_IMAGE_MODEL == "perplexity/pplx-decider-v1.2"
    assert dm.load_selection() == {
        "text": DEFAULT_TEXT_MODEL,
        "text_fallback": DEFAULT_TEXT_FALLBACK_MODEL,
        "image": DEFAULT_IMAGE_MODEL,
    }
    # 기본 모델은 모두 앱에 든 목록에 있고, 이미지 기본은 이미지를 받는 모델이다
    ids = {m["id"] for m in BUILTIN_CATALOG}
    assert {DEFAULT_TEXT_MODEL, DEFAULT_TEXT_FALLBACK_MODEL, DEFAULT_IMAGE_MODEL} <= ids
    assert dm.accepts_images(DEFAULT_IMAGE_MODEL) is True


def test_save_keeps_other_slots_and_other_config():
    from core.app_config import load_app_config, save_app_config

    save_app_config({"backup_path": "D:/b"})
    out = dm.save_selection({"image": "cloudflare/clef", "text": None})
    assert out["image"] == "cloudflare/clef" and out["text"] == DEFAULT_TEXT_MODEL
    cfg = load_app_config()
    assert cfg["backup_path"] == "D:/b"  # 다른 설정을 지우지 않는다
    assert cfg["decision_models"]["image"] == "cloudflare/clef"
    assert dm.load_selection()["image"] == "cloudflare/clef"


def test_fallback_can_be_none_but_others_cannot():
    assert dm.save_selection({"text_fallback": ""})["text_fallback"] == ""
    assert dm.load_selection()["text_fallback"] == ""
    with pytest.raises(ValueError):
        dm.save_selection({"text": ""})


@pytest.mark.parametrize(
    "bad", ["jev-1.14", "https://evil/x", "a/b c", "../../x", "typesafe/jev\n1", "A/B"]
)
def test_malformed_ids_are_refused(bad):
    with pytest.raises(ValueError):
        dm.save_selection({"text": bad})
    assert dm.load_selection()["text"] == DEFAULT_TEXT_MODEL


def test_broken_saved_value_falls_back_to_default():
    from core.app_config import save_app_config

    save_app_config({"decision_models": {"text": 12, "image": "not an id", "text_fallback": None}})
    assert dm.load_selection() == dm.DEFAULTS


def test_valid_ids_include_aliases_and_free_variants():
    for ok in ("~typesafe/jev-latest", "inception/mercury-decide:free", "nace-ai/drex-v2.0"):
        assert dm.valid_model_id(ok), ok


# ── 목록 ─────────────────────────────────────────────────────────────────────

_LIVE = {
    "data": [
        {"id": "typesafe/jev-1.15", "name": "TypeSafe: Jev 1.15",
         "architecture": {"input_modalities": ["text"], "output_modalities": ["decisions"]},
         "pricing": {"prompt": "0.000000042"}},
        {"id": "some/chat-model", "name": "chat",
         "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
         "pricing": {"prompt": "0.000001"}},
        {"id": "BAD ID", "name": "x", "architecture": {}, "pricing": {}},
    ]
}


def test_catalog_parses_live_list_and_caches_it():
    calls = {"n": 0}

    def op(req, timeout=None):
        calls["n"] += 1
        assert req.full_url == dm.CATALOG_URL and req.get_header("Authorization") is None
        return _Resp(json.dumps(_LIVE).encode())

    out = dm.fetch_catalog(opener=op, now=1000.0)
    assert out["source"] == "live"
    # 판정을 내지 않는 모델·모양이 틀린 id는 버린다
    assert out["models"] == [
        {"id": "typesafe/jev-1.15", "name": "TypeSafe: Jev 1.15", "inputs": ["text"],
         "usd_per_m": 0.042}
    ]
    assert dm.fetch_catalog(opener=op, now=1000.0 + 60)["source"] == "live" and calls["n"] == 1
    dm.fetch_catalog(opener=op, now=1000.0 + dm.CATALOG_TTL + 1)
    assert calls["n"] == 2  # 한 시간이 지나면 다시 받는다
    assert dm.model_info("typesafe/jev-1.15")["usd_per_m"] == 0.042


def test_catalog_falls_back_to_builtin_without_raising():
    def down(req, timeout=None):
        raise OSError("offline")

    out = dm.fetch_catalog(opener=down, now=1.0)
    assert out["source"] == "builtin" and out["models"] == BUILTIN_CATALOG
    empty = dm.fetch_catalog(opener=lambda r, timeout=None: _Resp(b'{"data": []}'), now=2.0)
    assert empty["source"] == "builtin"


def test_builtin_catalog_is_well_formed():
    ids = [m["id"] for m in BUILTIN_CATALOG]
    assert len(ids) == 27 and len(set(ids)) == 27
    assert all(dm.valid_model_id(i) for i in ids)
    assert all(m["usd_per_m"] >= 0 and m["inputs"] for m in BUILTIN_CATALOG)


# ── 고른 모델의 클라이언트 ─────────────────────────────────────────────────────


def _cap_opener(seen: list, answers=None, usage=None):
    def op(req, timeout=None):
        seen.append(req)
        body = json.loads(req.data.decode("utf-8"))
        ans = answers or {q: {"type": "noul", "noul": 0.7} for q in body["questions"]}
        payload = {"answers": ans, "usage": usage or {"input_tokens": 1000}}
        return _Resp(json.dumps(payload).encode())

    return op


def test_model_client_contract(tmp_path):
    (tmp_path / ".env").write_text(
        "TYPESAFE_API_KEY=ts-must-not-leave\nOPENROUTER_API_KEY=sk-or-ok\n", encoding="utf-8"
    )
    seen: list = []
    c = OpenRouterModelClient(model=DEFAULT_TEXT_MODEL, library_root=tmp_path,
                              opener=_cap_opener(seen))
    c.ask("글", {"q": {"type": "noul", "instructions": "?"}})
    req = seen[0]
    assert req.full_url == OPENROUTER_DECISIONS_URL
    assert req.get_header("Authorization") == "Bearer sk-or-ok"  # TypeSafe 키는 나가지 않는다
    body = json.loads(req.data)
    assert body["model"] == DEFAULT_TEXT_MODEL and set(body) == {"model", "state", "questions"}
    # usage.cost가 없으면 목록의 단가(Jev 1.14 $0.042/M)로 어림한다
    assert c.usage()["cost_usd"] == pytest.approx(1000 * 0.042 / 1e6)


def test_model_client_sends_images_in_state_array(tmp_path):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (3000, 2200), "white").save(buf, format="PNG")
    seen: list = []
    c = OpenRouterModelClient(
        model=DEFAULT_IMAGE_MODEL, api_key="sk-or-x", opener=_cap_opener(seen)
    )
    q = {"q": {"type": "noul", "instructions": "?"}}
    c.ask("쪽", q, images=[(buf.getvalue(), "image/png")])
    body = json.loads(seen[0].data)
    text, part = body["state"]
    assert text == "쪽" and part["type"] == "image_url" and "images" not in body
    raw = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
    img = Image.open(io.BytesIO(raw))
    w, h = img.size
    # decider 타일 상한(32×32 2,048개) 안이고 300KB 안이다 — 어느 모델을 골라도 넘지 않게
    assert -(-w // 32) * -(-h // 32) <= 2048 and len(raw) <= 300 * 1024


def test_text_only_model_refuses_images_before_sending():
    seen: list = []
    c = OpenRouterModelClient(model="nace-ai/drex-v2.0", api_key="k", opener=_cap_opener(seen))
    with pytest.raises(JevCallFailed):
        c.ask("s", {"q": {"type": "noul", "instructions": "?"}}, images=[(b"x", "image/png")])
    assert seen == []
    # 목록에 없는 모델은 모른다 — 막지 않는다(목록보다 새 모델일 수 있다)
    assert OpenRouterModelClient(model="new/vendor-model", api_key="k").ACCEPTS_IMAGES is True


def test_unknown_model_price_falls_back():
    c = OpenRouterModelClient(model="new/vendor-model", api_key="k")
    assert c.INPUT_USD_PER_M == 0.04


@pytest.mark.parametrize(
    "model,family,thresholds",
    [
        ("typesafe/jev-1.14", "jev", (0.85, 0.5)),
        ("~typesafe/jev-latest", "jev", (0.85, 0.5)),
        ("perplexity/pplx-decider-v1.2", "decider", (0.997, 0.69)),
        ("~perplexity/pplx-decider-flash-latest", "decider", (0.997, 0.69)),
        ("liquid/d1", "unmeasured", (0.85, 0.5)),
        ("cloudflare/clef", "unmeasured", (0.85, 0.5)),
    ],
)
def test_thresholds_follow_model_family(model, family, thresholds):
    from core.structure_llm import judge_thresholds

    assert judge_family(model) == family
    assert judge_thresholds(OpenRouterModelClient(model=model, api_key="k")) == thresholds


# ── 설정 라우트 ───────────────────────────────────────────────────────────────


def test_post_route_saves_and_get_reflects(client, tmp_path):  # noqa: F811
    _setup(client, tmp_path)
    r = client.post(
        "/api/settings/decision-models",
        json={"text": "typesafe/jev-1.13", "text_fallback": "", "image": "liquid/d1"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["selection"] == {
        "text": "typesafe/jev-1.13", "text_fallback": "", "image": "liquid/d1"
    }
    d = client.get("/api/settings/decision-models?catalog=false").json()
    assert d["selection"]["image"] == "liquid/d1" and d["image_model"] == "liquid/d1"
    r = client.post("/api/settings/decision-models", json={"image": "nope"})
    assert r.status_code == 400 and "모델 id" in r.json()["error"]
    assert client.get("/api/settings/decision-models?catalog=false").json()["image_model"] == (
        "liquid/d1"
    )


def test_route_uses_saved_text_model(client, tmp_path, monkeypatch):  # noqa: F811
    """편성 판정이 저장된 텍스트 모델을 부르고, 폴백을 비우면 폴백 클라이언트를 만들지 않는다."""
    import llm.openrouter_decider as or_mod
    from app.routers.composition import SegmentationStructureLlmRequest, _structure_jev
    from core.segmentation import Line, normalize_rules

    dm.save_selection({"text": "typesafe/jev-1.13", "text_fallback": ""})
    made: list = []

    class C:
        PROVIDER = "openrouter"
        INPUT_USD_PER_M = 0.042
        has_key = True

        def __init__(self, *, model, **k):
            self.model = model
            self.JUDGE_FAMILY = judge_family(model)
            made.append(model)

        def gate(self, n):
            return None

        def ask(self, state, questions):
            return {q: {"type": "noul", "noul": 0.9} for q in questions}

        def usage(self):
            return {"calls": 1, "cost_usd": 0.0}

    monkeypatch.setattr(or_mod, "OpenRouterModelClient", C)
    body = [Line(page=2, line_index=i, text=f"본문{i}" * 3) for i in range(2)]
    req = SegmentationStructureLlmRequest(part_id="vol1", engine="jev")
    out = _structure_jev(None, req, body, normalize_rules(None), 10_000)
    assert made == ["typesafe/jev-1.13"]
    assert out["answered_by"] == {"openrouter:typesafe/jev-1.13": 1} and out["fallback"] is None


def test_survey_uses_saved_image_model(client, tmp_path, monkeypatch):  # noqa: F811
    from app.routers import llm_ocr

    dm.save_selection({"image": "~perplexity/pplx-decider-flash-latest"})
    c = llm_ocr._decision_client("decision", tmp_path, 0)
    assert c.model == "~perplexity/pplx-decider-flash-latest"
    chain = llm_ocr._decision_chain(tmp_path)
    assert chain[0]["model"] == "~perplexity/pplx-decider-flash-latest"
    assert chain[0]["usd_per_page_est"] == pytest.approx(2400 * 0.01 / 1e6)



# ── 2026-10-18 릴리스 리뷰 지적 ──
def test_catalog_price_negative_or_nonfinite_is_unknown():
    """OpenRouter는 가변 단가를 "-1"로 적는다 — 《무료》나 음수 어림·JSON 500이 되지 않게 None."""
    payload = {
        "data": [
            {"id": "a/neg", "pricing": {"prompt": "-1"}, "architecture": {}},
            {"id": "a/nan", "pricing": {"prompt": "nan"}, "architecture": {}},
            {"id": "a/inf", "pricing": {"prompt": "1e400"}, "architecture": {}},
            {"id": "a/ok", "pricing": {"prompt": "0.00000002"}, "architecture": {}},
        ]
    }
    got = {m["id"]: m["usd_per_m"] for m in dm._parse_catalog(payload)}
    assert got == {"a/neg": None, "a/nan": None, "a/inf": None, "a/ok": 0.02}


def test_judge_family_jev_only_for_typesafe():
    """다른 업체의 `x/jev…`가 Jev 문턱을 받지 않는다 — 계통은 업체 이름으로 판정한다."""
    from llm.openrouter_decider import judge_family

    assert judge_family("typesafe/jev-1.14") == "jev"
    assert judge_family("~typesafe/jev-latest") == "jev"
    assert judge_family("someone/jev-clone") == "unmeasured"


def test_retired_model_not_in_builtin_catalog():
    """2026-10-18 OpenRouter 목록에서 빠진 decider v1.1은 오프라인 목록에도 없다.

    골라도 실패한다.
    """
    assert "perplexity/pplx-decider-v1.1-27b" not in {m["id"] for m in dm.BUILTIN_CATALOG}


def test_gate_exceeded_is_not_handed_to_the_fallback():
    """호출 상한(JevGateExceeded)은 비용 게이트다 — 폴백(유료)에 다시 묻지 않고 멈춘다."""
    from core.segmentation import Line
    from core.structure_llm import ask_structure_jev
    from llm.jev import JevGateExceeded

    class Capped:
        PROVIDER, model = "openrouter", "typesafe/jev-1.14"
        calls = 0

        def ask(self, state, questions):
            self.calls += 1
            raise JevGateExceeded("상한")

        def usage(self):
            return {"calls": self.calls}

    class Fallback(Capped):
        model = "perplexity/pplx-decider-v1.2"

        def ask(self, state, questions):
            self.calls += 1
            return {q: {"type": "noul", "noul": 0.9} for q in questions}

    lines = [Line(page=1, line_index=i, text=f"글자{i}" * 3) for i in range(6)]
    primary, fb = Capped(), Fallback()
    _props, meta = ask_structure_jev(
        lines, primary, max_chars=10_000, questions_per_call=2, fallback=fb
    )
    assert fb.calls == 0
    assert primary.calls == 1  # 남은 묶음도 보내지 않는다
    assert meta["error"] and "상한" in meta["error"]


def test_screen_reverts_select_when_save_fails():
    """저장에 실패하면 드롭다운을 서버 값으로 되돌린다 — 화면이 쓰지 않는 모델을 보이지 않게."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    js = (root / "src/app/static/js/setup-panel.js").read_text(encoding="utf-8")
    body = js.split("async function _saveDecisionModel", 1)[1].split("\n}\n", 1)[0]
    catch = body.split("} catch (e) {", 1)[1]
    assert "select.value = select.dataset.saved" in catch
    assert "select.dataset.saved = current" in js



# ── 2026-10-18 Codex 최종 리뷰 지적 ──
def test_one_malformed_catalog_item_does_not_drop_the_list():
    """항목 하나의 모양이 틀려도(architecture가 글자 등) 그 항목만 버린다.

    새 모델이 사라지지 않게.
    """
    payload = {
        "data": [
            {"id": "a/odd", "architecture": "text", "pricing": "free"},
            {"id": "a/ok", "architecture": {}, "pricing": {"prompt": "0.00000002"}},
        ]
    }
    assert [m["id"] for m in dm._parse_catalog(payload)] == ["a/ok"]


def test_catalog_failure_is_remembered_briefly():
    """오프라인이면 설정을 열 때마다 5초씩 기다리지 않는다 — 실패도 잠깐 기억한다.

    새로 고침(force)은 다시 받는다.
    """
    calls = {"n": 0}

    def down(req, timeout=None):
        calls["n"] += 1
        raise OSError("offline")

    assert dm.fetch_catalog(opener=down, now=1000.0)["source"] == "builtin"
    assert dm.fetch_catalog(opener=down, now=1060.0)["source"] == "builtin"
    assert calls["n"] == 1
    dm.fetch_catalog(opener=down, now=1060.0, force=True)
    assert calls["n"] == 2
    dm.fetch_catalog(opener=down, now=1060.0 + dm.CATALOG_RETRY_AFTER + 1)
    assert calls["n"] == 3


def test_text_only_model_refused_for_image_slot():
    """목록이 텍스트만 받는다고 적은 모델은 이미지 칸에 저장하지 않는다(API로 와도)."""
    dm._cache.update(at=time.time(), models=[
        {"id": "a/text-only", "name": "t", "inputs": ["text"], "usd_per_m": 0.01},
    ])
    with pytest.raises(ValueError, match="이미지"):
        dm.save_selection({"image": "a/text-only"})
    # 텍스트 칸은 그대로 받는다, 목록에 없는 새 id도 이미지 칸에 받는다(모름은 막지 않는다)
    assert dm.save_selection({"text": "a/text-only"})["text"] == "a/text-only"
    assert dm.save_selection({"image": "brand/new-model"})["image"] == "brand/new-model"



def test_missing_price_is_unknown_not_free():
    """단가가 없거나 비었으면 《모름》(None)이다.

    《무료》로 보이고 어림이 0이 되지 않게(Codex 재검토).
    """
    payload = {"data": [
        {"id": "a/none", "architecture": {}, "pricing": {}},
        {"id": "a/null", "architecture": {}, "pricing": {"prompt": None}},
        {"id": "a/empty", "architecture": {}, "pricing": {"prompt": ""}},
        {"id": "a/zero", "architecture": {}, "pricing": {"prompt": "0"}},
    ]}
    got = {m["id"]: m["usd_per_m"] for m in dm._parse_catalog(payload)}
    assert got == {"a/none": None, "a/null": None, "a/empty": None, "a/zero": 0.0}


def test_bad_modalities_drop_only_that_item():
    """입출력 형식이 목록이 아니면 그 항목만 버린다.

    글자 "image"를 낱자로 쪼개 오판하지도 않는다.
    """
    payload = {"data": [
        {"id": "a/num", "architecture": {"output_modalities": 1}},
        {"id": "a/str", "architecture": {"input_modalities": "image"}},
        {"id": "a/zero", "architecture": {"output_modalities": 0}},
        {"id": "a/emptystr", "architecture": {"input_modalities": ""}},
        {"id": "a/big", "architecture": {}, "pricing": {"prompt": 10**400}},
        {"id": "a/ok", "architecture": {"input_modalities": ["text", "image"]}},
    ]}
    got = dm._parse_catalog(payload)
    assert [(m["id"], m["inputs"]) for m in got] == [
        ("a/big", ["text"]), ("a/ok", ["text", "image"])
    ]
    assert got[0]["usd_per_m"] is None  # 너무 큰 정수 단가는 《모름》
