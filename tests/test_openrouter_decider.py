"""본문 경계 판정의 기본 — OpenRouter 경유 Perplexity decider (D-136). 가짜로만 잰다.

실제 호출은 하지 않는다. 이 PC에는 개인 키 파일(~/.claude/data/triage/.env)에 실제 키가 있으므로
네트워크에 닿을 수 있는 자리는 전부 가짜 opener·가짜 클라이언트로 막는다. 지키는 것은 넷이다.
① TypeSafe 키가 OpenRouter 주소로 나가지 않는다(키 이름 격리).
② 기본 주소·모델이 측정한 그 길이다.
③ 주 모델 호출이 실패하면 «그 호출만» Jev가 대신 답하고, 누가 답했는지 meta에 남는다.
④ 문턱은 답한 모델의 것을 쓴다 — decider 0.95/0.35, Jev 0.85/0.5.
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
    JEV_ACCEPT_AT,
    JEV_REJECT_AT,
    ask_structure_jev,
    judge_thresholds,
    line_id,
)
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
    """TypeSafe 키만 있으면 OpenRouter 클라이언트는 «키 없음»이다 — 남의 키를 빌리지 않는다."""
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
    assert body["model"] == OPENROUTER_DECIDER_MODEL == "perplexity/pplx-decider-v1-27b"
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


def test_failed_call_falls_back_to_jev_and_records_who_answered():
    lines = _lines(4)
    scores = {line_id(lines[0]): 0.9, line_id(lines[1]): 0.6, line_id(lines[2]): 0.3}
    primary = _Fake("openrouter", OPENROUTER_DECIDER_MODEL, scores, fail=True)
    jev = _Fake("typesafe", "jev-latest", scores)
    props, meta = ask_structure_jev(lines, primary, max_chars=10_000, fallback=jev)

    assert primary.calls == 1 and jev.calls == 1
    assert meta["error"] is None  # 폴백이 답했으면 실패가 아니다 — 메모에만 남는다
    assert meta["fallback_calls"] == 1
    assert meta["answered_by"] == {"typesafe:jev-latest": 1}
    assert meta["fallback_lines"] == [[1, 0], [1, 1], [1, 2], [1, 3]]
    assert any("typesafe:jev-latest" in n for n in meta["notes"])
    # Jev가 답했으니 Jev 문턱: 0.9 → accept(decider 문턱이었다면 escalate)
    band = {p["line_index"]: p["band"] for p in props}
    assert band == {0: "accept", 1: "escalate"}
    assert all(p["judge"] == "typesafe:jev-latest" for p in props)
    assert meta["thresholds"]["typesafe:jev-latest"] == [JEV_ACCEPT_AT, JEV_REJECT_AT]


def test_without_fallback_a_failed_call_stays_an_error():
    lines = _lines(2)
    primary = _Fake("openrouter", OPENROUTER_DECIDER_MODEL, {}, fail=True)
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

    primary = Flaky("openrouter", OPENROUTER_DECIDER_MODEL, {})
    jev = _Fake("typesafe", "jev-latest", {})
    _props, meta = ask_structure_jev(
        lines, primary, max_chars=10_000, questions_per_call=2, fallback=jev
    )
    assert meta["answered_by"] == {
        "typesafe:jev-latest": 1,
        f"openrouter:{OPENROUTER_DECIDER_MODEL}": 1,
    }
    assert meta["fallback_lines"] == [[1, 0], [1, 1]]


# ── ④ 모델별 문턱 ──────────────────────────────────────────────────────────
def test_thresholds_follow_the_model_that_answered():
    assert judge_thresholds(OpenRouterDecisionClient(api_key="x")) == (0.95, 0.35)
    assert judge_thresholds(JevClient(api_key="x")) == (0.85, 0.5)
    assert (DECIDER_ACCEPT_AT, DECIDER_REJECT_AT) == (0.95, 0.35)

    lines = _lines(5)
    ps = [0.96, 0.95, 0.9, 0.36, 0.35]
    scores = {line_id(ln): p for ln, p in zip(lines, ps)}
    props, meta = ask_structure_jev(
        lines, _Fake("openrouter", OPENROUTER_DECIDER_MODEL, scores), max_chars=10_000
    )
    band = {p["line_index"]: p["band"] for p in props}
    # 0.9는 Jev였다면 accept이지만 decider에서는 escalate, 0.36은 Jev였다면 reject
    assert band == {0: "accept", 1: "accept", 2: "escalate", 3: "escalate"}
    assert meta["bands"] == {"accept": 2, "escalate": 2, "reject": 1}
    assert meta["accept_at"] == 0.95 and meta["reject_at"] == 0.35


# ── 라우트: 기본은 decider, 키가 없으면 Jev, 목차는 Jev ─────────────────────
def _route_fakes(monkeypatch, *, decider_key: bool, decider_fails: bool = False):
    import core.toc as toc_mod
    import llm.openrouter_decider as or_mod

    made: dict = {}

    def factory(provider, model, has_key, fail):
        class C:
            PROVIDER = provider
            INPUT_USD_PER_M = 0.04
            calls = 0

            def __init__(self, *a, **k):
                self.model = model
                self.has_key = has_key
                made[provider] = self

            def gate(self, n):
                return None

            def ask(self, state, questions):
                C.calls += 1
                if fail:
                    raise JevCallFailed("jev_http_error", status=402)
                return {q: {"type": "noul", "noul": 0.9} for q in questions}

            def usage(self):
                return {"calls": C.calls, "cost_usd": 0.0}

        return C

    monkeypatch.setattr(
        or_mod,
        "OpenRouterDecisionClient",
        factory("openrouter", OPENROUTER_DECIDER_MODEL, decider_key, decider_fails),
    )
    monkeypatch.setattr(jev_mod, "JevClient", factory("typesafe", "jev-latest", True, False))
    monkeypatch.setattr(toc_mod, "detect_toc_pages", lambda pages, *a, **k: [])
    return made


def _call_route():
    from app.routers.composition import SegmentationStructureLlmRequest, _structure_jev
    from core.segmentation import normalize_rules

    body = [Line(page=2, line_index=i, text=f"본문{i}" * 3) for i in range(3)]
    req = SegmentationStructureLlmRequest(part_id="vol1", engine="jev")
    return _structure_jev(None, req, body, normalize_rules(None), 10_000)


def test_route_defaults_to_the_decider(monkeypatch):
    _route_fakes(monkeypatch, decider_key=True)
    out = _call_route()
    assert out["provider"] == "openrouter" and out["model"] == OPENROUTER_DECIDER_MODEL
    assert out["answered_by"] == {f"openrouter:{OPENROUTER_DECIDER_MODEL}": 1}
    # 0.9는 decider 문턱에서 escalate — 체크 해제로 선다
    assert {p["band"] for p in out["proposals"]} == {"escalate"}
    assert set(out["usage_by"]) == {f"openrouter:{OPENROUTER_DECIDER_MODEL}", "typesafe:jev-latest"}


def test_route_falls_back_to_jev_when_the_decider_fails(monkeypatch):
    _route_fakes(monkeypatch, decider_key=True, decider_fails=True)
    out = _call_route()
    assert out["fallback_calls"] == 1 and out["answered_by"] == {"typesafe:jev-latest": 1}
    assert {p["band"] for p in out["proposals"]} == {"accept"}  # Jev 문턱으로 0.9는 accept


def test_route_uses_jev_when_there_is_no_openrouter_key(monkeypatch):
    _route_fakes(monkeypatch, decider_key=False)
    out = _call_route()
    assert out["provider"] == "typesafe" and out["fallback"] is None
    assert out["answered_by"] == {"typesafe:jev-latest": 1}


def test_dry_run_names_the_judge(monkeypatch):
    from app.routers.composition import SegmentationStructureLlmRequest, _structure_jev
    from core.segmentation import normalize_rules

    _route_fakes(monkeypatch, decider_key=True)
    req = SegmentationStructureLlmRequest(part_id="vol1", engine="jev", dry_run=True)
    body = [Line(page=2, line_index=0, text="본문" * 3)]
    out = _structure_jev(None, req, body, normalize_rules(None), 10_000)
    assert out["dry_run"] and out["judge"] == f"openrouter:{OPENROUTER_DECIDER_MODEL}"
