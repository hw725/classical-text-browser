"""본문 경계 판정의 폴백 — OpenRouter 경유 Perplexity decider v1.1 (D-136·D-139). 가짜로만 잰다.

실제 호출은 하지 않는다. 이 PC에는 개인 키 파일(~/.claude/data/triage/.env)에 실제 키가 있으므로
네트워크에 닿을 수 있는 자리는 전부 가짜 opener·가짜 클라이언트로 막는다. 지키는 것은 넷이다.
① TypeSafe 키가 OpenRouter 주소로 나가지 않는다(키 이름 격리).
② 기본 주소·모델이 측정한 그 길이다.
③ 주 모델(Jev) 호출이 실패하면 《그 호출만》 decider가 대신 답하고, 누가 답했는지 meta에 남는다.
④ 문턱은 답한 모델의 것을 쓴다 — decider v1.1 0.997/0.69, Jev 0.85/0.5.

2026-10-17(D-142): 편성 라우트는 설정에서 고른 OpenRouter 모델(텍스트 typesafe/jev-1.14·폴백
decider v1.2)로 부른다. 아래 《라우트》 시험은 그 뜻으로 고쳤고, 클라이언트 단의 시험(①②)은
`OpenRouterDecisionClient`가 남아 있어 그대로 둔다.
"""

from __future__ import annotations

import io
import json

import pytest

import llm.jev as jev_mod
from core.segmentation import Line
from core.structure_llm import (
    DECIDER_ACCEPT_AT,
    DECIDER_REJECT_AT,
    ask_structure_jev,
    judge_thresholds,
    line_id,
)
from llm.decision_models import DEFAULT_TEXT_FALLBACK_MODEL, DEFAULT_TEXT_MODEL
from llm.jev import JevCallFailed, JevClient
from llm.openrouter_decider import (
    OPENROUTER_DECIDER_MODEL,
    OPENROUTER_DECISIONS_URL,
    OpenRouterDecisionClient,
)


@pytest.fixture
def isolated_keys(monkeypatch, tmp_path):
    """키 출처 셋을 전부 시험이 정한 것으로 바꾼다 — 환경변수·서고/프로젝트 .env·개인 키 파일."""
    names = ("OPENROUTER_API_KEY", "TYPESAFE_API_KEY", "JEV_API_KEY", "OPENROUTER_DECISIONS_URL")
    for name in names:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(jev_mod, "_key_from_app_env", lambda names, root: None)
    key_file = tmp_path / "triage.env"
    key_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(jev_mod, "KEY_ENV_FILE", key_file)
    return key_file


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(seen: list):
    """요청을 기록하고 System One 모양 답을 돌려주는 가짜 urlopen."""

    def op(req, timeout=None):
        seen.append(req)
        body = json.loads(req.data.decode("utf-8"))
        answers = {q: {"type": "noul", "noul": 0.97} for q in body["questions"]}
        payload = {"answers": answers, "usage": {"input_tokens": 100, "cost": 0.000004}}
        return _Resp(json.dumps(payload).encode("utf-8"))

    return op


# ── ① 키 격리 ──────────────────────────────────────────────────────────────
def test_typesafe_key_is_never_sent_to_openrouter(isolated_keys, monkeypatch):
    """TypeSafe 키만 있으면 OpenRouter 클라이언트는 《키 없음》이다 — 남의 키를 빌리지 않는다."""
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-secret")
    isolated_keys.write_text("TYPESAFE_API_KEY=ts-file\nJEV_API_KEY=jev-file\n", encoding="utf-8")
    c = OpenRouterDecisionClient()
    assert not c.has_key
    with pytest.raises(JevCallFailed):
        c.ask("s", {"q": {"type": "noul", "instructions": "?"}})


def test_openrouter_key_comes_from_the_personal_file_and_only_it_is_sent(
    isolated_keys, monkeypatch
):
    """두 키가 다 있어도 OpenRouter로 가는 헤더에는 OpenRouter 키만 실린다."""
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-secret")
    # 줄 순서가 TypeSafe 먼저여도 이름이 정한다
    isolated_keys.write_text(
        "TYPESAFE_API_KEY=ts-file\nOPENROUTER_API_KEY=sk-or-file\n", encoding="utf-8"
    )
    seen: list = []
    c = OpenRouterDecisionClient(opener=_opener(seen))
    assert c.has_key
    c.ask("state", {"q": {"type": "noul", "instructions": "?"}})
    auth = seen[0].get_header("Authorization")
    assert auth == "Bearer sk-or-file"
    assert "ts-" not in auth


# ── ② 기본 주소·모델 ───────────────────────────────────────────────────────
def test_default_endpoint_and_model_are_the_measured_ones(isolated_keys):
    seen: list = []
    c = OpenRouterDecisionClient(api_key="sk-or-x", opener=_opener(seen))
    answers = c.ask("state", {"q": {"type": "noul", "instructions": "?"}})
    req = seen[0]
    assert req.full_url == OPENROUTER_DECISIONS_URL == "https://openrouter.ai/api/alpha/decisions"
    body = json.loads(req.data.decode("utf-8"))
    assert body["model"] == OPENROUTER_DECIDER_MODEL == "perplexity/pplx-decider-v1.1-27b"
    assert set(body) == {"model", "state", "questions"}  # System One과 같은 본문, 감싸기 없음
    assert answers["q"]["noul"] == 0.97
    # 게이트웨이가 준 cost가 정본이다
    assert c.usage()["cost_usd"] == pytest.approx(0.000004)


def test_images_are_refused_before_sending(isolated_keys):
    seen: list = []
    c = OpenRouterDecisionClient(api_key="sk-or-x", opener=_opener(seen))
    with pytest.raises(JevCallFailed):
        c.ask("s", {"q": {"type": "noul", "instructions": "?"}}, images=[(b"x", "image/png")])
    assert seen == []


# ── ③ 폴백 ─────────────────────────────────────────────────────────────────
class _Fake:
    def __init__(self, provider: str, model: str, scores: dict, fail: bool = False) -> None:
        self.PROVIDER = provider
        self.model = model
        self.scores = scores
        self.fail = fail
        self.calls = 0

    def ask(self, state, questions):
        self.calls += 1
        if self.fail:
            raise JevCallFailed("jev_http_error", status=402)
        return {q: {"type": "noul", "noul": self.scores.get(q, 0.0)} for q in questions}

    def usage(self):
        return {"calls": self.calls}


def _lines(n: int = 4) -> list[Line]:
    return [Line(page=1, line_index=i, text=f"글자{i}" * 3) for i in range(n)]


DECIDER_LABEL = f"openrouter:{OPENROUTER_DECIDER_MODEL}"


def test_failed_call_falls_back_to_the_decider_and_records_who_answered():
    lines = _lines(4)
    scores = {line_id(lines[0]): 0.998, line_id(lines[1]): 0.9, line_id(lines[2]): 0.6}
    primary = _Fake("typesafe", "jev-latest", scores, fail=True)
    decider = _Fake("openrouter", OPENROUTER_DECIDER_MODEL, scores)
    props, meta = ask_structure_jev(lines, primary, max_chars=10_000, fallback=decider)

    assert primary.calls == 1 and decider.calls == 1
    assert meta["error"] is None  # 폴백이 답했으면 실패가 아니다 — 메모에만 남는다
    assert meta["fallback_calls"] == 1
    assert meta["answered_by"] == {DECIDER_LABEL: 1}
    assert meta["fallback_lines"] == [[1, 0], [1, 1], [1, 2], [1, 3]]
    assert any(DECIDER_LABEL in n for n in meta["notes"])
    # decider가 답했으니 decider 문턱: 0.9 → escalate(Jev 문턱이었다면 accept),
    # 0.6 → reject(Jev 문턱이었다면 escalate)
    band = {p["line_index"]: p["band"] for p in props}
    assert band == {0: "accept", 1: "escalate"}
    assert all(p["judge"] == DECIDER_LABEL for p in props)
    assert meta["thresholds"][DECIDER_LABEL] == [DECIDER_ACCEPT_AT, DECIDER_REJECT_AT]


def test_without_fallback_a_failed_call_stays_an_error():
    lines = _lines(2)
    primary = _Fake("typesafe", "jev-latest", {}, fail=True)
    props, meta = ask_structure_jev(lines, primary, max_chars=10_000)
    assert props == [] and meta["error"] and meta["answered_by"] == {}


def test_fallback_is_per_call_not_sticky():
    """주 모델이 한 번 실패해도 다음 호출은 다시 주 모델부터 묻는다."""
    lines = _lines(4)

    class Flaky(_Fake):
        def ask(self, state, questions):
            self.calls += 1
            if self.calls == 1:
                raise JevCallFailed("jev_http_error", status=500)
            return super().ask(state, questions)

    primary = Flaky("typesafe", "jev-latest", {})
    decider = _Fake("openrouter", OPENROUTER_DECIDER_MODEL, {})
    _props, meta = ask_structure_jev(
        lines, primary, max_chars=10_000, questions_per_call=2, fallback=decider
    )
    assert meta["answered_by"] == {"typesafe:jev-latest": 1, DECIDER_LABEL: 1}
    assert meta["fallback_lines"] == [[1, 0], [1, 1]]


# ── ④ 모델별 문턱 ──────────────────────────────────────────────────────────
def test_thresholds_follow_the_model_that_answered():
    assert judge_thresholds(OpenRouterDecisionClient(api_key="x")) == (0.997, 0.69)
    assert judge_thresholds(JevClient(api_key="x")) == (0.85, 0.5)
    assert (DECIDER_ACCEPT_AT, DECIDER_REJECT_AT) == (0.997, 0.69)

    lines = _lines(5)
    ps = [0.998, 0.997, 0.9, 0.7, 0.69]
    scores = {line_id(ln): p for ln, p in zip(lines, ps)}
    props, meta = ask_structure_jev(
        lines, _Fake("openrouter", OPENROUTER_DECIDER_MODEL, scores), max_chars=10_000
    )
    band = {p["line_index"]: p["band"] for p in props}
    # 0.9는 Jev였다면 accept이지만 decider에서는 escalate, 0.69는 Jev였다면 escalate
    assert band == {0: "accept", 1: "accept", 2: "escalate", 3: "escalate"}
    assert meta["bands"] == {"accept": 2, "escalate": 2, "reject": 1}
    assert meta["accept_at"] == 0.997 and meta["reject_at"] == 0.69


# ── 라우트: 주는 텍스트 모델, 폴백 모델은 실패한 호출만, 목차는 텍스트 모델 (D-139·D-142) ─────
# D-142: 둘 다 설정에서 고른 OpenRouter 모델이고 같은 클래스(`OpenRouterModelClient`)로 만든다 —
# 가짜도 그 이름 하나에 끼우고 모델 id로 가른다. 기본은 텍스트 typesafe/jev-1.14 · 폴백 decider v1.2
TEXT_LABEL = f"openrouter:{DEFAULT_TEXT_MODEL}"
FALLBACK_LABEL = f"openrouter:{DEFAULT_TEXT_FALLBACK_MODEL}"


def _route_fakes(
    monkeypatch, *, key: bool = True, jev_fails: bool = False, fallback_model=None
):
    import core.toc as toc_mod
    import llm.decision_models as dm
    import llm.openrouter_decider as or_mod
    from llm.openrouter_decider import judge_family

    made: dict = {}
    calls: dict = {}

    class C:
        PROVIDER = "openrouter"
        INPUT_USD_PER_M = 0.04

        def __init__(self, *, model, **k):
            self.model = model
            self.has_key = key
            self.JUDGE_FAMILY = judge_family(model)
            made[model] = self

        def gate(self, n):
            return None

        def ask(self, state, questions):
            calls[self.model] = calls.get(self.model, 0) + 1
            if jev_fails and self.model == DEFAULT_TEXT_MODEL:
                raise JevCallFailed("jev_http_error", status=402)
            return {q: {"type": "noul", "noul": 0.9} for q in questions}

        def usage(self):
            return {"calls": calls.get(self.model, 0), "cost_usd": 0.0}

    monkeypatch.setattr(or_mod, "OpenRouterModelClient", C)
    if fallback_model is not None:
        sel = {**dm.DEFAULTS, "text_fallback": fallback_model}
        monkeypatch.setattr(dm, "load_selection", lambda: dict(sel))
    monkeypatch.setattr(toc_mod, "detect_toc_pages", lambda pages, *a, **k: [])
    # 직결 Jev는 이 길에서 만들어지면 안 된다 — 만들면 시험이 깨지게 한다
    monkeypatch.setattr(jev_mod, "JevClient", None)
    return made


def _call_route():
    from app.routers.composition import SegmentationStructureLlmRequest, _structure_jev
    from core.segmentation import normalize_rules

    body = [Line(page=2, line_index=i, text=f"본문{i}" * 3) for i in range(3)]
    req = SegmentationStructureLlmRequest(part_id="vol1", engine="jev")
    return _structure_jev(None, req, body, normalize_rules(None), 10_000)


def test_route_defaults_to_jev_even_with_an_openrouter_key(monkeypatch):
    """기본 텍스트 모델은 OpenRouter의 typesafe/jev-1.14 — Jev 문턱으로 판정한다."""
    _route_fakes(monkeypatch)
    out = _call_route()
    assert out["provider"] == "openrouter" and out["model"] == DEFAULT_TEXT_MODEL
    assert out["answered_by"] == {TEXT_LABEL: 1}
    assert {p["band"] for p in out["proposals"]} == {"accept"}  # Jev 문턱으로 0.9는 accept
    # 폴백도 사용량에 잡힌다 — 안 불렸어도 자리는 있다
    assert set(out["usage_by"]) == {TEXT_LABEL, FALLBACK_LABEL}


def test_route_falls_back_to_the_decider_when_jev_fails(monkeypatch):
    _route_fakes(monkeypatch, jev_fails=True)
    out = _call_route()
    assert out["fallback_calls"] == 1 and out["answered_by"] == {FALLBACK_LABEL: 1}
    # decider 문턱(0.997/0.69)으로 0.9는 escalate — 체크 해제로 선다
    assert {p["band"] for p in out["proposals"]} == {"escalate"}
    assert out["usage_by"][FALLBACK_LABEL]["calls"] == 1


def test_route_uses_jev_when_there_is_no_openrouter_key(monkeypatch):
    """폴백 칸을 비우면(《폴백 없음》) 폴백 클라이언트를 만들지 않는다 — 실패한 호출은 실패로."""
    made = _route_fakes(monkeypatch, fallback_model="")
    out = _call_route()
    assert out["provider"] == "openrouter" and out["fallback"] is None
    assert out["answered_by"] == {TEXT_LABEL: 1}
    assert set(made) == {DEFAULT_TEXT_MODEL}


def test_dry_run_names_the_judge(monkeypatch):
    from app.routers.composition import SegmentationStructureLlmRequest, _structure_jev
    from core.segmentation import normalize_rules

    _route_fakes(monkeypatch)
    req = SegmentationStructureLlmRequest(part_id="vol1", engine="jev", dry_run=True)
    body = [Line(page=2, line_index=0, text="본문" * 3)]
    out = _structure_jev(None, req, body, normalize_rules(None), 10_000)
    assert out["dry_run"] and out["judge"] == TEXT_LABEL
    # 폴백이 본문을 모두 떠맡을 때의 최대를 따로 알린다 — decider는 질문마다 글을 다시 세어 과금한다
    assert out["fallback_judge"] == FALLBACK_LABEL
    fb_max = out["fallback_cost_usd_max"]
    assert fb_max is not None and fb_max >= out["cost_usd_est"]
