"""Jev를 어느 길로 부르는가 — 키마다 제 주소로만 (D-136 후속, 2026-10-05).

결함: `llm/jev.py`의 KEY_NAMES 끝에 OPENROUTER_API_KEY가 있어, OpenRouter 키만 있는 사람의
`JevClient.has_key`가 참이 되고 편성 목차 대조·decider 실패 시 폴백·설정 「연결 확인」이 그 키를
**TypeSafe 주소로** 보냈다(401).

사용자 결정: OpenRouter 키만 있으면 Jev를 OpenRouter 경유(`~typesafe/jev-latest`)로 부른다.

지키는 것:
  ① 키 조합 넷(없음 / TypeSafe만 / OpenRouter만 / 둘 다)마다 편성 라우트의 목차 대조 Jev·본문 판정·
    폴백이 어느 클래스·주소·키로 가는가. **가짜 opener가 실제로 나간 요청의 URL과 Authorization을
    잡아** «OpenRouter 키가 typesafe 주소로 가지 않는다»·«TypeSafe 키가 openrouter 주소로 가지
    않는다»를 직접 단언한다.
  ② OpenRouter 경유 Jev의 답은 Jev 문턱(0.85/0.5)으로 판정된다 — decider 문턱(0.95/0.35)이 아니다.
  ③ 설정 «판정 모델»: TypeSafe 칸의 has_key는 TypeSafe 키만 보고, `jev_via`가 길을 알린다.
    「연결 확인」이 OpenRouter 키를 TypeSafe 주소로 보내지 않는다.

**이 PC에는 진짜 키가 있다** — 환경변수·Windows 사용자 환경변수(Cloudflare)·개인 키 파일
(`~/.claude/data/triage/.env`)·프로젝트 .env. 아래 fixture가 넷을 모두 막고 서고 .env만 읽게 하며,
네트워크 대신 가짜 opener를 모든 판정 클라이언트의 기본값으로 끼운다(빠져나간 요청이 있어도 밖으로
나가지 않는다). 첫 시험이 막혔는지부터 확인한다.
"""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

import llm.jev as jev_mod
import llm.openrouter_decider as or_mod
from core.segmentation import Line
from llm.jev import TYPESAFE_URL, JevCallFailed, JevClient, make_jev_client
from llm.openrouter_decider import (
    OPENROUTER_DECIDER_MODEL,
    OPENROUTER_DECISIONS_URL,
    OPENROUTER_JEV_MODEL,
    OpenRouterDecisionClient,
    OpenRouterJevClient,
)
from tests.test_segmentation import client  # noqa: F401 — fixture 재사용

TS_KEY = "ts-FAKE-typesafe-0001"
OR_KEY = "sk-or-FAKE-openrouter-0002"

_ALL_KEY_ENVS = (
    "PERPLEXITY_API_KEY",
    "TYPESAFE_API_KEY",
    "JEV_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_DECISIONS_URL",
    "JEV_BASE_URL",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_CLEF_URL",
)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Wire:
    """가짜 urlopen — 나간 요청을 (주소, Bearer 키, 모델)로 적고 System One 모양 답을 돌려준다.

    noul은 `noul`(기본 0.9), choice는 첫 선택지(목차 대조의 후보는 유사도 순이라 첫째가 제목 행)를
    0.95로 고른다. `fail_models`에 든 모델은 402로 떨어뜨린다(decider 실패 → 폴백을 재려고).
    """

    def __init__(self) -> None:
        self.seen: list[dict] = []
        self.noul = 0.9
        self.fail_models: set[str] = set()

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        auth = req.get_header("Authorization") or ""
        self.seen.append(
            {"url": req.full_url, "key": auth.removeprefix("Bearer "), "model": body.get("model"),
             "kind": next(iter(body["questions"].values())).get("type")}
        )
        if body.get("model") in self.fail_models:
            raise urllib.error.HTTPError(
                req.full_url, 402, "Payment Required", {}, io.BytesIO(b"{}")
            )
        answers = {}
        for qid, q in body["questions"].items():
            if q.get("type") == "choice":
                first = next(iter(q["criteria"]))
                answers[qid] = {"type": "choice", "choice": first, "probabilities": {first: 0.95}}
            else:
                answers[qid] = {"type": "noul", "noul": self.noul}
        usage = {"input_tokens": 50}
        if req.full_url.startswith("https://openrouter.ai/"):
            usage["cost"] = 0.000017  # 게이트웨이는 cost를 준다 — TypeSafe 직결은 주지 않는다
        return _Resp(json.dumps({"answers": answers, "usage": usage}).encode("utf-8"))

    def assert_keys_stay_home(self) -> None:
        """«어떤 키도 남의 주소로 나가지 않는다» — 이 파일이 지키려는 한 줄."""
        for s in self.seen:
            if s["url"].startswith(TYPESAFE_URL):
                assert s["key"] == TS_KEY, f"TypeSafe 주소로 남의 키가 나갔다: {s['model']}"
            elif s["url"].startswith("https://openrouter.ai/"):
                assert s["key"] == OR_KEY, f"OpenRouter 주소로 남의 키가 나갔다: {s['model']}"
            else:
                raise AssertionError(f"모르는 주소: {s['url']}")


@pytest.fixture(autouse=True)
def wire(monkeypatch, tmp_path) -> Wire:
    """실제 키 차단 + 모든 판정 클라이언트의 기본 opener를 가짜로."""
    import llm.clef_cf as clef

    for k in _ALL_KEY_ENVS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(clef, "_win_user_env", lambda name: None)  # Windows 사용자 환경변수
    monkeypatch.setattr(jev_mod, "KEY_ENV_FILE", tmp_path / "no-personal-key-file.env")

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

    monkeypatch.setattr(jev_mod, "_key_from_app_env", library_only)
    w = Wire()
    # opener는 키워드 전용 인자라 기본값이 __kwdefaults__에 있다 — 물려받은 클래스(decider·
    # OpenRouter·clef)도 같은 __init__을 쓰므로 여기 한 곳으로 전부 막힌다
    monkeypatch.setitem(JevClient.__init__.__kwdefaults__, "opener", w)
    return w


def _lib(tmp_path: Path, keys: dict[str, str]) -> Path:
    lib = tmp_path / "lib"
    lib.mkdir(exist_ok=True)
    (lib / ".env").write_text("".join(f"{k}={v}\n" for k, v in keys.items()), encoding="utf-8")
    return lib


_COMBOS = {
    "none": {},
    "typesafe_only": {"TYPESAFE_API_KEY": TS_KEY},
    "openrouter_only": {"OPENROUTER_API_KEY": OR_KEY},
    "both": {"TYPESAFE_API_KEY": TS_KEY, "OPENROUTER_API_KEY": OR_KEY},
}


def test_ambient_keys_are_blocked(tmp_path, wire):
    """시험 전제 — 이 PC의 진짜 키가 하나도 보이지 않아야 아래가 의미가 있다."""
    from llm.clef_cf import ClefClient
    from llm.openrouter_decider import OpenRouterClefClient

    for cls in (JevClient, OpenRouterJevClient, OpenRouterDecisionClient, ClefClient,
                OpenRouterClefClient):
        assert cls(library_root=tmp_path).has_key is False, cls.__name__
        assert cls(library_root=None).has_key is False, cls.__name__
    assert make_jev_client(library_root=None).has_key is False
    assert JevClient(library_root=None)._opener is wire


# ── 직결 Jev는 OpenRouter 키를 보지 않는다 ─────────────────────────────────────
def test_direct_jev_ignores_openrouter_key(tmp_path, monkeypatch):
    """OpenRouter 키만 있으면 TypeSafe 직결은 «키 없음» — 환경변수·서고·개인 파일 셋 다."""
    assert "OPENROUTER_API_KEY" not in JevClient.KEY_NAMES
    assert not JevClient(library_root=_lib(tmp_path, {"OPENROUTER_API_KEY": OR_KEY})).has_key
    monkeypatch.setenv("OPENROUTER_API_KEY", OR_KEY)
    assert not JevClient(library_root=None).has_key
    monkeypatch.delenv("OPENROUTER_API_KEY")
    f = tmp_path / "personal.env"
    f.write_text(f"OPENROUTER_API_KEY={OR_KEY}\n", encoding="utf-8")
    monkeypatch.setattr(jev_mod, "KEY_ENV_FILE", f)
    assert not JevClient(library_root=None).has_key
    # 개인 파일의 OpenRouter 키로는 OpenRouter 경유 Jev가 선다
    assert type(make_jev_client(library_root=None)) is OpenRouterJevClient


# ── ① make_jev_client: 키 조합 넷 ────────────────────────────────────────────
@pytest.mark.parametrize(
    "combo,cls,url,key",
    [
        ("none", JevClient, TYPESAFE_URL, None),
        ("typesafe_only", JevClient, TYPESAFE_URL, TS_KEY),
        ("openrouter_only", OpenRouterJevClient, OPENROUTER_DECISIONS_URL, OR_KEY),
        ("both", JevClient, TYPESAFE_URL, TS_KEY),  # 둘 다면 측정한 기본 길(직결)
    ],
)
def test_make_jev_client_picks_by_key(tmp_path, wire, combo, cls, url, key):
    c = make_jev_client(library_root=_lib(tmp_path, _COMBOS[combo]), max_calls=3)
    assert type(c) is cls
    assert c.has_key is (key is not None)
    if key is None:
        with pytest.raises(JevCallFailed):
            c.ask("s", {"q": {"type": "noul", "instructions": "?"}})
        assert wire.seen == []
        return
    c.ask("s", {"q": {"type": "noul", "instructions": "?"}})
    assert wire.seen[0]["url"] == url and wire.seen[0]["key"] == key
    expected_model = OPENROUTER_JEV_MODEL if cls is OpenRouterJevClient else "jev-latest"
    assert wire.seen[0]["model"] == expected_model
    wire.assert_keys_stay_home()


def test_openrouter_jev_contract(tmp_path, wire):
    """llm_pipeline 정본(jev_decisions.PROVIDERS["openrouter"])과 같은 계약."""
    assert OPENROUTER_JEV_MODEL == "~typesafe/jev-latest"
    assert OpenRouterJevClient.KEY_NAMES == ("OPENROUTER_API_KEY",)
    assert OpenRouterJevClient.INPUT_USD_PER_M == 0.042
    c = OpenRouterJevClient(api_key=OR_KEY, library_root=tmp_path)
    c.ask("state", {"q": {"type": "noul", "instructions": "?"}})
    assert wire.seen[0]["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert c.usage()["cost_usd"] == pytest.approx(0.000017)  # usage.cost가 정본
    with pytest.raises(JevCallFailed):  # 텍스트 전용 — 이미지는 보내기 전에 거부
        c.ask("s", {"q": {"type": "noul", "instructions": "?"}}, images=[(b"x", "image/png")])
    assert len(wire.seen) == 1


def test_openrouter_jev_cost_falls_back_to_jev_rate(tmp_path):
    """cost가 빠진 답이면 Jev 입력 단가 $0.042/M으로 어림한다."""

    def op(req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        ans = {q: {"type": "noul", "noul": 0.5} for q in body["questions"]}
        return _Resp(json.dumps({"answers": ans, "usage": {"input_tokens": 1_000_000}}).encode())

    c = OpenRouterJevClient(api_key=OR_KEY, opener=op, library_root=tmp_path)
    c.ask("s", {"q": {"type": "noul", "instructions": "?"}})
    assert c.usage()["cost_usd"] == pytest.approx(0.042)


# ── ② 문턱 ────────────────────────────────────────────────────────────────────
def test_openrouter_jev_gets_jev_thresholds(tmp_path, wire):
    from core.structure_llm import ask_structure_jev, judge_thresholds

    assert judge_thresholds(OpenRouterJevClient(api_key="x")) == (0.85, 0.5)
    assert judge_thresholds(OpenRouterDecisionClient(api_key="x")) == (0.95, 0.35)
    lines = [Line(page=1, line_index=i, text=f"글자{i}" * 3) for i in range(2)]
    wire.noul = 0.9  # Jev 문턱이면 accept, decider 문턱이었다면 escalate
    props, meta = ask_structure_jev(
        lines, OpenRouterJevClient(api_key=OR_KEY, library_root=tmp_path), max_chars=10_000
    )
    assert {p["band"] for p in props} == {"accept"}
    assert (meta["accept_at"], meta["reject_at"]) == (0.85, 0.5)
    assert all(p["judge"] == f"openrouter:{OPENROUTER_JEV_MODEL}" for p in props)


# ── ① 편성 라우트: 키 조합 넷, 실제로 나간 요청으로 ─────────────────────────────
class _Entry:
    def __init__(self, title: str, level: int = 1) -> None:
        self.title = title
        self.level = level


def _run_route(monkeypatch, lib: Path):
    import app.routers.composition as comp
    import core.toc as toc_mod
    from app.routers.composition import SegmentationStructureLlmRequest, _structure_jev
    from core.segmentation import normalize_rules

    monkeypatch.setattr(comp, "get_library_path", lambda: lib)
    monkeypatch.setattr(toc_mod, "detect_toc_pages", lambda pages, *a, **k: [1])
    monkeypatch.setattr(
        toc_mod, "extract_toc_entries_rule", lambda pages, tp: [_Entry("甲集"), _Entry("乙集")]
    )
    toc_page = [Line(page=1, line_index=i, text=t) for i, t in enumerate(["目錄", "甲集", "乙集"])]
    body = [
        Line(page=2, line_index=0, text="甲集序 天地玄黃"),
        Line(page=2, line_index=1, text="宇宙洪荒日月盈昃"),
        Line(page=2, line_index=2, text="乙集記 辰宿列張"),
    ]
    req = SegmentationStructureLlmRequest(part_id="vol1", engine="jev")
    return _structure_jev(None, req, toc_page + body, normalize_rules(None), 10_000)


DECIDER_LABEL = f"openrouter:{OPENROUTER_DECIDER_MODEL}"
OR_JEV_LABEL = f"openrouter:{OPENROUTER_JEV_MODEL}"
TS_JEV_LABEL = "typesafe:jev-latest"


@pytest.mark.parametrize(
    "combo,body_label,fallback,toc_label",
    [
        ("typesafe_only", TS_JEV_LABEL, None, TS_JEV_LABEL),
        ("openrouter_only", DECIDER_LABEL, OR_JEV_LABEL, OR_JEV_LABEL),
        ("both", DECIDER_LABEL, TS_JEV_LABEL, TS_JEV_LABEL),
    ],
)
def test_route_sends_each_key_only_to_its_own_address(
    tmp_path, monkeypatch, wire, combo, body_label, fallback, toc_label
):
    out = _run_route(monkeypatch, _lib(tmp_path, _COMBOS[combo]))
    assert isinstance(out, dict), out
    assert out["answered_by"] == {body_label: 1}
    assert out["fallback"] == fallback
    assert out["toc"]["judge"] == toc_label and out["toc"]["picked"] == 2
    assert all(
        p["judge"] == toc_label for p in out["proposals"] if p["reasons"] == ["toc:jev"]
    )
    wire.assert_keys_stay_home()
    toc_reqs = [s for s in wire.seen if s["kind"] == "choice"]  # 목차 대조는 choice
    assert len(toc_reqs) == 2  # 목차 항목 둘 — 전부 Jev
    if combo == "openrouter_only":
        # 이 결함의 핵심: OpenRouter 키만 있을 때 TypeSafe 주소로는 한 건도 나가지 않는다
        assert not any(s["url"].startswith(TYPESAFE_URL) for s in wire.seen)
        assert {s["model"] for s in toc_reqs} == {OPENROUTER_JEV_MODEL}
    else:
        assert {s["url"] for s in toc_reqs} == {TYPESAFE_URL}
    if combo == "typesafe_only":
        assert not any(s["url"].startswith("https://openrouter.ai/") for s in wire.seen)


def test_route_without_any_key_sends_nothing(tmp_path, monkeypatch, wire):
    out = _run_route(monkeypatch, _lib(tmp_path, {}))
    assert out.status_code == 400
    msg = json.loads(out.body)["error"]
    assert "OPENROUTER_API_KEY" in msg and "TYPESAFE_API_KEY" in msg
    assert wire.seen == []


def test_route_dry_run_names_the_toc_judge(tmp_path, monkeypatch, wire):
    import app.routers.composition as comp
    from app.routers.composition import SegmentationStructureLlmRequest, _structure_jev
    from core.segmentation import normalize_rules

    lib = _lib(tmp_path, _COMBOS["openrouter_only"])
    monkeypatch.setattr(comp, "get_library_path", lambda: lib)
    req = SegmentationStructureLlmRequest(part_id="vol1", engine="jev", dry_run=True)
    out = _structure_jev(None, req, [Line(page=2, line_index=0, text="본문" * 3)],
                         normalize_rules(None), 10_000)
    assert out["judge"] == DECIDER_LABEL and out["toc_judge"] == OR_JEV_LABEL
    assert wire.seen == []


def test_decider_failure_falls_back_to_openrouter_jev_with_jev_thresholds(
    tmp_path, monkeypatch, wire
):
    """OpenRouter 키만 — decider가 402면 같은 키로 OpenRouter 경유 Jev가 대신 답하고, 그 답은
    Jev 문턱으로 판정된다(0.9 → accept. decider 문턱이었다면 escalate)."""
    wire.fail_models = {OPENROUTER_DECIDER_MODEL}
    wire.noul = 0.9
    out = _run_route(monkeypatch, _lib(tmp_path, _COMBOS["openrouter_only"]))
    assert out["fallback_calls"] == 1 and out["answered_by"] == {OR_JEV_LABEL: 1}
    assert out["thresholds"][OR_JEV_LABEL] == [0.85, 0.5]
    body_props = [p for p in out["proposals"] if p["reasons"] == ["jev:structure"]]
    assert body_props and {p["band"] for p in body_props} == {"accept"}
    assert all(p["judge"] == OR_JEV_LABEL for p in body_props)
    wire.assert_keys_stay_home()
    assert not any(s["url"].startswith(TYPESAFE_URL) for s in wire.seen)


# ── ③ 설정 «판정 모델» ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "combo,jev_via",
    [("none", None), ("typesafe_only", "typesafe"), ("openrouter_only", "openrouter"),
     ("both", "typesafe")],
)
def test_settings_typesafe_row_sees_only_typesafe_key(client, wire, combo, jev_via):  # noqa: F811
    r = client.post("/api/library/quick-start")
    assert r.status_code == 200, r.text
    keys = {"TYPESAFE_API_KEY": "typesafe", "OPENROUTER_API_KEY": "openrouter"}
    payload = {keys[k]: v for k, v in _COMBOS[combo].items()}
    if payload:
        r = client.post("/api/settings/llm-keys", json=payload)
        assert r.status_code == 200, r.text

    d = client.get("/api/settings/decision-models").json()
    models = {m["id"]: m for m in d["models"]}
    assert models["typesafe"]["has_key"] is ("TYPESAFE_API_KEY" in _COMBOS[combo])
    assert models["openrouter"]["has_key"] is ("OPENROUTER_API_KEY" in _COMBOS[combo])
    assert d["jev_via"] == jev_via
    assert ("OpenRouter 키로 Jev를 부릅니다" in models["typesafe"]["role"]) is (
        jev_via == "openrouter"
    )
    assert wire.seen == []  # check=false는 부르지 않는다

    # 「연결 확인」 — 실제로 나간 요청의 주소·키로 본다
    d = client.get("/api/settings/decision-models?check=true").json()
    models = {m["id"]: m for m in d["models"]}
    wire.assert_keys_stay_home()
    if combo == "openrouter_only":
        assert models["typesafe"]["status"] == "needs_key"
        assert not any(s["url"].startswith(TYPESAFE_URL) for s in wire.seen)
    if combo in ("typesafe_only", "both"):
        assert models["typesafe"]["status"] == "ready"
        assert any(s["url"].startswith(TYPESAFE_URL) for s in wire.seen)


def test_screen_names_openrouter_jev():
    """화면의 «누가 답했나»가 OpenRouter 경유 Jev를 decider로 읽지 않는다 — 경유 가지가 먼저다."""
    js = (
        Path(__file__).resolve().parent.parent
        / "src" / "app" / "static" / "js" / "composition-editor.js"
    ).read_text(encoding="utf-8")
    start = js.index("function _judgeName")
    block = js[start : js.index("}", start)]
    via = block.index('"openrouter:~typesafe/"')
    generic = block.index('"openrouter:")')
    assert via < generic and "OpenRouter 경유" in block
    # 결과 줄·크기 안내가 목차 대조를 맡은 Jev를 밝힌다
    assert "d.toc.judge" in js and "d.toc_judge" in js


def test_or_module_exports_used_by_route():
    """라우트·시험이 가짜로 바꿔 끼우는 이름이 모듈에 있다(make_jev_client가 부를 때 찾는다)."""
    assert or_mod.OpenRouterJevClient is OpenRouterJevClient
    assert jev_mod.JevClient is JevClient


# ── ④ 직결이 거절되면 OpenRouter로 넘어간다 (2026-10-06 TypeSafe 402 크레딧 소진) ──────────
_Q = {"q": {"type": "noul", "instructions": "?"}}


def test_direct_refusal_moves_to_openrouter_and_stays(tmp_path, wire):
    """두 키가 다 있을 때 직결 402 → 같은 묻기를 OpenRouter 경유로, 그 뒤로는 바로 OpenRouter."""
    wire.fail_models = {"jev-latest"}  # 직결 모델 이름만 402 — OpenRouter 이름(~typesafe/…)은 통과
    c = make_jev_client(library_root=_lib(tmp_path, _COMBOS["both"]), max_calls=3)
    assert type(c) is JevClient, "고르는 규칙(①)은 그대로 — 넘어가는 것은 묻는 도중이다"
    assert c.ask("s", _Q)["q"]["noul"] == 0.9
    c.ask("s", _Q)
    assert [(s["url"], s["model"]) for s in wire.seen] == [
        (TYPESAFE_URL, "jev-latest"),
        (OPENROUTER_DECISIONS_URL, OPENROUTER_JEV_MODEL),
        (OPENROUTER_DECISIONS_URL, OPENROUTER_JEV_MODEL),
    ]
    wire.assert_keys_stay_home()
    assert c.fell_back == "openrouter(typesafe 402)"
    assert (c.PROVIDER, c.model) == ("openrouter", OPENROUTER_JEV_MODEL), "«누가 답했나»가 실제 길"
    u = c.usage()
    assert u["asks"] == 2, "거절된 묻기를 상한에 두 번 세지 않는다"
    assert u["via_openrouter"] == 1 and u["cost_usd"] > 0


def test_fallback_keeps_one_budget(tmp_path, wire):
    """넘어간 뒤에도 상한은 하나다 — OpenRouter 쪽이 새 예산을 갖지 않는다."""
    wire.fail_models = {"jev-latest"}
    c = make_jev_client(library_root=_lib(tmp_path, _COMBOS["both"]), max_calls=2)
    c.ask("s", _Q)
    c.ask("s", _Q)
    with pytest.raises(jev_mod.JevGateExceeded):
        c.ask("s", _Q)


def test_no_fallback_without_openrouter_key_or_when_disabled(tmp_path, wire):
    wire.fail_models = {"jev-latest"}
    c = make_jev_client(library_root=_lib(tmp_path, _COMBOS["typesafe_only"]), max_calls=3)
    with pytest.raises(JevCallFailed) as ei:
        c.ask("s", _Q)
    assert ei.value.status == 402 and len(wire.seen) == 1 and c.fell_back is None
    off = JevClient(library_root=_lib(tmp_path, _COMBOS["both"]), max_calls=3, fallback=False)
    with pytest.raises(JevCallFailed):
        off.ask("s", _Q)
    assert len(wire.seen) == 2


def test_openrouter_clients_do_not_chain_further(tmp_path, wire):
    """OpenRouter decider·Jev 자신이 거절되면 그대로 실패 — 폴백은 TypeSafe 직결에만 있다."""
    wire.fail_models = {OPENROUTER_DECIDER_MODEL, OPENROUTER_JEV_MODEL}
    for cls in (OpenRouterDecisionClient, OpenRouterJevClient):
        c = cls(library_root=_lib(tmp_path, _COMBOS["both"]), max_calls=3)
        with pytest.raises(JevCallFailed):
            c.ask("s", _Q)
    assert len(wire.seen) == 2
