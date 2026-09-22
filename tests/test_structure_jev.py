"""Jev(판정 모델)로 «글이 시작하는 행»을 고르는 길 — 가짜 클라이언트로 잰다.

실제 호출은 하지 않는다(돈이 들고, 답이 바뀌면 테스트가 흔들린다). 여기서 지키는 것은 셋이다.
① 코드가 행을 정해서 묻는다 — 모델이 행을 지어낼 자리가 형식에 없다.
② 문턱 아래 답은 후보가 되지 않는다.
③ 한 묶음이 죽어도 나머지 묶음의 답은 살아남는다.
"""

from __future__ import annotations

import pytest

from core.segmentation import Line
from core.structure_llm import (
    JEV_QUESTIONS_PER_CALL,
    ask_structure_jev,
    jev_question,
    jev_structure_size,
    line_id,
)
from llm.jev import JevCallFailed, JevClient, JevGateExceeded, noul


def _lines(n: int = 6, page: int = 1) -> list[Line]:
    return [Line(page=page, line_index=i, text=f"글자{i}" * 3) for i in range(n)]


class FakeJev:
    """묻는 질문마다 정해 둔 확률을 돌려준다. 무엇을 물었는지 기록한다."""

    model = "fake-jev"

    def __init__(self, scores: dict[str, float], fail_on: int = -1) -> None:
        self.scores = scores
        self.fail_on = fail_on
        self.seen: list[tuple[str, list[str]]] = []

    def ask(self, state: str, questions: dict) -> dict:
        self.seen.append((state, list(questions)))
        if len(self.seen) - 1 == self.fail_on:
            raise JevCallFailed("jev_http_error", status=500)
        return {
            qid: {"type": "noul", "noul": self.scores.get(qid, 0.0)} for qid in questions
        }

    def usage(self) -> dict:
        return {"calls": len(self.seen)}


def test_asks_about_every_line_and_keeps_the_ids():
    """행마다 질문 하나. 질문 id는 행 번호이고, 지시문에는 그 행의 글자가 들어간다."""
    lines = _lines(4)
    client = FakeJev({line_id(lines[2]): 0.9})
    props, meta = ask_structure_jev(lines, client, max_chars=10_000)

    assert meta["questions"] == 4
    _state, asked = client.seen[0]
    assert asked == [line_id(ln) for ln in lines]
    q = jev_question(lines[2])
    assert q["type"] == "noul"
    assert lines[2].text in q["instructions"]  # id는 모델에 가지 않는다 — 글자가 가야 한다
    assert len(props) == 1
    assert (props[0]["page"], props[0]["line_index"]) == (1, 2)
    # 제목은 모델이 만들지 않는다 — 코드가 그 행의 글자로 채운다
    assert props[0]["title"] == lines[2].text
    assert "jev" in props[0]["why"]


def test_threshold_decides_and_scores_are_kept_for_rescoring():
    """문턱 아래는 후보가 아니지만 확률은 meta에 남는다 — 다시 부르지 않고 문턱만 바꿔 재려고."""
    lines = _lines(3)
    scores = {line_id(lines[0]): 0.9, line_id(lines[1]): 0.55, line_id(lines[2]): 0.1}
    props, meta = ask_structure_jev(lines, FakeJev(scores), max_chars=10_000, threshold=0.8)
    assert [p["line_index"] for p in props] == [0]
    assert meta["nouls"] == [[1, 0, 0.9], [1, 1, 0.55], [1, 2, 0.1]]
    assert meta["threshold"] == 0.8


def test_one_failed_call_does_not_lose_the_others():
    """묶음 하나가 실패해도 다른 묶음의 답은 살린다 — 권 전체를 다시 묻게 하지 않는다."""
    lines = _lines(4, page=1) + _lines(4, page=2)
    scores = {line_id(ln): 0.95 for ln in lines}
    client = FakeJev(scores, fail_on=0)  # 첫 묶음만 실패
    props, meta = ask_structure_jev(lines, client, max_chars=60)  # 쪽마다 묶음 하나

    assert meta["calls"] == 2
    assert meta["error"] and "1번째 묶음" in meta["error"]
    assert {p["page"] for p in props} == {2}


def test_size_counts_calls_before_sending():
    """게이트는 도구 층에(전역 규칙 11) — 한 묶음의 행이 많으면 같은 state로 여러 번 부른다."""
    lines = _lines(JEV_QUESTIONS_PER_CALL * 2 + 5)
    size = jev_structure_size(lines, max_chars=10_000_000)
    assert size["questions"] == len(lines)
    assert size["calls"] == 3


def test_gate_refuses_before_the_network():
    client = JevClient(api_key="x", max_calls=2)
    client.gate(2)
    with pytest.raises(JevGateExceeded):
        client.gate(3)


def test_noul_reads_only_numbers():
    """True는 파이썬에서 int다 — 확률로 세면 «예»가 1.0이 되어 조용히 통과한다."""
    assert noul({"noul": 0.42}) == 0.42
    assert noul({"noul": True}) is None
    assert noul({"noul": "0.9"}) is None
    assert noul(None) is None


def test_client_without_key_fails_loudly():
    with pytest.raises(JevCallFailed):
        JevClient(api_key="").ask("state", {"q": {"type": "noul", "instructions": "?"}})


def test_key_file_order_beats_line_order(tmp_path):
    """파일에 적힌 줄 순서가 우선순위를 뒤집으면 안 된다 — 다른 서비스 키로 401이 난 자리."""
    from llm.jev import resolve_key

    env = tmp_path / ".env"
    env.write_text(
        'OPENROUTER_API_KEY=sk-or-first\nTYPESAFE_API_KEY="ts-second" # 메모\n',
        encoding="utf-8",
    )
    assert resolve_key(env) == "ts-second"


def test_key_file_ignores_blank_and_commented(tmp_path):
    from llm.jev import resolve_key

    env = tmp_path / ".env"
    env.write_text('# TYPESAFE_API_KEY=old\nJEV_API_KEY=" "\n', encoding="utf-8")
    assert resolve_key(env) is None


# ── 목차(층위 1~2)와 본문 판정(그 아래 층)을 겹치는 자리 ─────────────────────
class _Entry:
    """core.toc.TocEntry의 자리에 쓰는 최소 대역 — level만 본다."""

    def __init__(self, title: str, level: int = 2) -> None:
        self.title = title
        self.level = level


def test_toc_picks_become_proposals_above_the_threshold_only():
    """확률 문턱 아래는 후보로 세우지 않는다(버리는 것이 아니라 세우지 않는 것).

    운양집 실측(2026-09-21): 0.8 이상 14건은 제목이 그 행에서 실제로 시작했고 불일치가 0,
    0.8 미만 11건 중 8건이 엉뚱한 행이었다.
    """
    from core.structure_llm import TOC_JEV_REASON, toc_picks_to_proposals

    entries = [_Entry("擊磬集", level=2), _Entry("第一卷", level=1)]
    # sim은 «고른 행에서 제목이 시작하는가»(match_toc_entries_jev가 늘 싣는다). 픽스처가
    # 이것을 빠뜨리면 실제 답과 다른 모양이 되어, 시험은 초록인데 코드는 다른 일을 한다.
    picks = [
        {"entry": 0, "title": "擊磬集", "page": 14, "line_index": 7, "prob": 0.97, "sim": 1.0},
        {"entry": 1, "title": "第一卷", "page": 14, "line_index": 2, "prob": 0.55, "sim": 1.0},
    ]
    out = toc_picks_to_proposals(picks, entries, min_prob=0.8)
    assert [(p["page"], p["line_index"], p["level"]) for p in out] == [(14, 7, 2)]
    assert out[0]["reasons"] == [TOC_JEV_REASON] and out[0]["confidence"] == 0.97

    both = toc_picks_to_proposals(picks, entries, min_prob=0.5)
    assert [p["level"] for both_p in [both] for p in both_p] == [1, 2]  # 목차 항목의 층위 그대로


def test_toc_picks_keep_one_place_when_the_same_title_is_listed_twice():
    """총목이 같은 集을 권1·권2 양쪽에 적는다(운양집 102항목 중 12개) — 자리는 하나다."""
    from core.structure_llm import toc_picks_to_proposals

    entries = [_Entry("松屋雜詠"), _Entry("松屋雜詠")]
    picks = [
        {"entry": 0, "title": "松屋雜詠", "page": 41, "line_index": 35, "prob": 0.92, "sim": 1.0},
        {"entry": 1, "title": "松屋雜詠", "page": 41, "line_index": 35, "prob": 0.9, "sim": 1.0},
    ]
    assert len(toc_picks_to_proposals(picks, entries, 0.8)) == 1


def test_body_proposals_nest_under_the_nearest_toc_boundary():
    """목차가 세운 층(권·集) 아래로 본문 판정을 내린다 — 트리에서 형제가 되면 안 된다."""
    from core.structure_llm import nest_under_toc

    toc = [
        {"page": 14, "line_index": 2, "level": 1},  # 권
        {"page": 14, "line_index": 7, "level": 2},  # 集
    ]
    body = [
        {"page": 14, "line_index": 4, "level": 2, "role": "article"},  # 권 아래, 集 앞
        {"page": 20, "line_index": 3, "level": 2, "role": "article"},  # 集 아래
    ]
    out = nest_under_toc(toc, body)
    assert [p["level"] for p in out] == [2, 3]
    assert body[1]["level"] == 2  # 원본은 건드리지 않는다


def test_without_a_toc_the_levels_stay_as_they_are():
    """일기류에는 총목이 없다 — 그 책에서는 본문 판정이 곧 낱글의 층이다."""
    from core.structure_llm import nest_under_toc

    body = [{"page": 1, "line_index": 0, "level": 2, "role": "article"}]
    assert nest_under_toc([], body)[0]["level"] == 2


def test_toc_matching_refuses_when_nothing_fits():
    """본문에 없는 항목에 «없음»을 고를 수 있어야 한다 — 없는 것을 고르게 하면 지어내기다.

    운양집 실측: 본문에 글자가 없는 75항목 중 71개(95%)가 «없음»이었고, 잘못 고른 4건은
    전부 확률 0.73 이하라 문턱 0.8에서 사라졌다.
    """
    from core.segmentation import Line
    from core.toc import TOC_NONE, match_toc_entries_jev, toc_match_question

    body = [Line(page=1, line_index=i, text=f"본문{i}" * 4) for i in range(6)]
    q = toc_match_question("擊磬集", [(body[0], 0.1)])
    assert q["type"] == "choice" and TOC_NONE in q["criteria"]
    assert "p1-L0" in q["criteria"]  # 후보는 행 번호로 준다 — 모델이 자리를 만들 수 없다

    class Fake:
        model = "fake-jev"

        def ask(self, state, questions):
            return {
                "where": {
                    "type": "choice",
                    "choice": TOC_NONE,
                    "probabilities": {TOC_NONE: 0.9},
                }
            }

    out = match_toc_entries_jev([_Entry("擊磬集")], body, Fake())
    assert out["picks"] == [] and len(out["none"]) == 1


def test_toc_matching_ignores_an_answer_that_is_not_one_of_the_choices():
    """모델이 정해 둔 선택지가 아닌 것을 말하면 코드가 «없음»으로 되돌린다."""
    from core.segmentation import Line
    from core.toc import match_toc_entries_jev

    body = [Line(page=3, line_index=1, text="擊磬集")]

    class Fake:
        model = "fake-jev"

        def ask(self, state, questions):
            return {"where": {"type": "choice", "choice": "p9-L9", "probabilities": {}}}

    out = match_toc_entries_jev([_Entry("擊磬集")], body, Fake())
    assert out["picks"] == [] and out["none"][0]["title"] == "擊磬集"


# ── 화면 쪽 배선 (node로 함수만 잘라 돌린다) ────────────────────────────────
def test_screen_asks_the_judge_engine_and_keeps_the_answer(tmp_path):
    """「판정 모델로 고르기」가 engine="jev"로 부르고, 답을 규칙 후보와 합칠 자리에 둔다.

    화면 JS는 빌드가 없어 import할 수 없다 — js_harness가 함수만 잘라 node로 돌린다.
    """
    from tests.js_harness import run_js

    setup = """
      const out = { textContent: "" };
      const viewerState = { docId: "d1", partId: "vol1" };
      const proposeState = { llm: null };
      const sent = [];
      const document = { getElementById: () => out };
      const fetch = async (url, opts) => {
        sent.push({ url, body: JSON.parse(opts.body) });
        return {
          ok: true,
          json: async () => ({
            proposals: [{ page: 1, line_index: 0, reasons: ["jev:structure"], level: 2 }],
            questions: 12, calls: 1, toc: { entries: 3, above_threshold: 2 },
            usage: { cost_usd: 0.001 },
          }),
        };
      };
    """
    body = """
      await _askJudgeStructure();
      console.log(JSON.stringify({
        url: sent[0].url, body: sent[0].body,
        kept: proposeState.llm ? proposeState.llm.proposals.length : 0,
        said: out.textContent,
      }));
    """
    got = run_js(tmp_path, "composition-editor.js", ["_askJudgeStructure"], setup, body)
    assert got["body"]["engine"] == "jev" and got["body"]["part_id"] == "vol1"
    assert "structure/llm" in got["url"]  # 라우트를 늘리지 않았다 — 같은 자리에 engine만 더했다
    assert got["kept"] == 1
    assert "목차 3항목 중 2개" in got["said"] and "$0.001" in got["said"]


def test_screen_treats_judge_places_as_model_places(tmp_path):
    """③의 «모델이 가리킨 자리»에 판정 모델·목차 대조도 들어간다(배지·정렬이 그 판정을 쓴다)."""
    from tests.js_harness import run_js

    body = """
      console.log(JSON.stringify({
        llm: _isLlmProposal({ reasons: ["llm:structure"] }),
        jev: _isLlmProposal({ reasons: ["jev:structure"] }),
        toc: _isLlmProposal({ reasons: ["toc:jev"] }),
        rule: _isLlmProposal({ reasons: ["date"] }),
      }));
    """
    got = run_js(tmp_path, "composition-editor.js", ["_isLlmProposal"], "", body)
    assert got == {"llm": True, "jev": True, "toc": True, "rule": False}


def test_screen_ranks_model_candidates_by_probability(tmp_path):
    """«상위 몇 개»는 확률 내림차순으로 자른다. 확률이 없는 규칙 후보는 순위에 들어가지 않는다."""
    from tests.js_harness import run_js

    body = """
      const props = [
        { page: 1, line_index: 0, prob: 0.4 },
        { page: 1, line_index: 1 },              // 규칙 후보 — 확률 없음
        { page: 2, line_index: 0, prob: 0.95 },
        { page: 3, line_index: 0, prob: 0.7 },
      ];
      console.log(JSON.stringify({ ranked: _modelRanked(props) }));
    """
    got = run_js(tmp_path, "composition-editor.js", ["_modelRanked", "_propKey"], "", body)
    assert got["ranked"] == ["2:0:0", "3:0:0", "1:0:0"]


def test_screen_tells_when_the_two_paths_disagree(tmp_path):
    """어긋남 줄은 «모름»의 표시다 — 많이 다를 때만 표본을 보라고 하고, 아무것도 바꾸지 않는다."""
    from tests.js_harness import run_js

    setup = """
      const cls = { toggle: (c, on) => { box.far = on; } };
      const box = { hidden: true, textContent: "", classList: cls };
      const document = { getElementById: () => box };
    """
    body = """
      const far = [
        { page: 1, line_index: 0, accepted: true, reasons: ["date"] },
        ...Array.from({ length: 9 }, (_, i) => ({ page: 2, line_index: i, prob: 0.9,
                                                  reasons: ["jev:structure"] })),
      ];
      _renderDivergence(far);
      const farText = box.textContent, farFlag = box.far;
      const close = [
        { page: 1, line_index: 0, accepted: true, reasons: ["date"] },
        { page: 1, line_index: 0, prob: 0.9, reasons: ["jev:structure"] },
      ];
      _renderDivergence(close);
      const closeText = box.textContent, closeFlag = box.far;
      _renderDivergence([{ page: 1, line_index: 0, accepted: true, reasons: ["date"] }]);
      console.log(JSON.stringify({ farText, farFlag, closeText, closeFlag,
                                   hiddenWithoutModel: box.hidden }));
    """
    names = ["_renderDivergence", "_isLlmProposal", "_propKey"]
    got = run_js(tmp_path, "composition-editor.js", names, setup, body)
    assert "많이 다릅니다" in got["farText"] and got["farFlag"] is True
    assert "대체로 같습니다" in got["closeText"] and got["closeFlag"] is False
    assert got["hiddenWithoutModel"] is True  # 모델을 돌리지 않았으면 줄 자체가 없다


def test_threshold_is_derived_from_this_book_not_a_constant():
    """문턱은 이 책의 답에서 뽑는다 — 자기 검증이 깨지는 직전에서 자른다.

    자기 검증은 «고른 행에서 제목이 실제로 시작하는가»이고 코드가 공짜로 확인한다.

    운양집 1책 실측(2026-09-21)을 줄여 옮긴 모양이다: 0.94 위는 전부 맞고 0.77부터 틀리기
    시작했다. 상수 0.8이 들었던 것은 그 사이가 비어 있었기 때문이지 0.8이 특별해서가 아니다.
    """
    from core.structure_llm import derive_toc_threshold

    picks = [
        {"prob": 0.99, "sim": 1.0},
        {"prob": 0.97, "sim": 1.0},
        {"prob": 0.96, "sim": 1.0},
        {"prob": 0.94, "sim": 1.0},
        {"prob": 0.77, "sim": 0.2},  # 여기서 자기 검증이 깨진다
        {"prob": 0.70, "sim": 0.1},
    ]
    value, how = derive_toc_threshold(picks)
    assert value == 0.94 and how["how"] == "cliff" and how["cut_at"] == 4
    # 오답을 하나 허용하면 그 아래까지 내려간다
    assert derive_toc_threshold(picks, tolerance=1)[0] == 0.77


def test_threshold_falls_back_when_there_is_too_little_to_go_on():
    """답이 적으면 절벽을 말할 근거가 없다 — 그럴 때만 상수를 쓴다."""
    from core.structure_llm import derive_toc_threshold

    value, how = derive_toc_threshold([{"prob": 0.9, "sim": 1.0}], fallback=0.8)
    assert value == 0.8 and how["how"] == "fallback"


def test_threshold_keeps_everything_when_nothing_fails_the_self_check():
    from core.structure_llm import derive_toc_threshold

    picks = [{"prob": 0.9 - i / 100, "sim": 1.0} for i in range(6)]
    value, how = derive_toc_threshold(picks)
    assert how["how"] == "all_pass" and value == picks[-1]["prob"]


# ── 반대 배치 — «그 성질이 성립하는 유일한 배치»를 고른 것은 아닌가 ────────────
# 2026-09-21 D-128 구현 세션의 지적: 픽스처가 우연히 성질이 성립하는 배치만 고르고
# 독스트링이 그것을 코드의 성질이라고 적으면, 시험은 초록인데 주장은 거짓이다.
# 그래서 «도출이 상수보다 나은 이유»가 실제로 걸리는 배치들을 함께 잰다.
def test_threshold_finds_a_low_cliff_where_the_constant_keeps_nothing():
    """절벽이 0.55에 있는 책 — 고정 0.8은 **하나도 못 건진다**. 도출이 필요한 진짜 이유다."""
    from core.structure_llm import derive_toc_threshold, toc_picks_to_proposals

    picks = [
        {"prob": p, "sim": s, "page": i, "line_index": 0, "title": "가", "entry": 0}
        for i, (p, s) in enumerate(
            [(0.72, 1.0), (0.68, 1.0), (0.61, 1.0), (0.58, 1.0), (0.55, 1.0), (0.41, 0.1)]
        )
    ]

    class _E:
        level = 2

    value, how = derive_toc_threshold(picks)
    assert value == 0.55 and how["how"] == "cliff"
    assert len(toc_picks_to_proposals(picks, [_E()] * 6, value)) == 5
    assert len(toc_picks_to_proposals(picks, [_E()] * 6, 0.8)) == 0  # 상수였으면 전멸


def test_nothing_is_kept_when_even_the_best_answer_fails_its_own_check():
    """가장 확신한 답부터 엉뚱한 행이면 아무것도 세우지 않는다 — 확률이 높다고 믿지 않는다."""
    from core.structure_llm import derive_toc_threshold

    picks = [{"prob": 0.99, "sim": 0.1}] + [{"prob": 0.9 - i / 100, "sim": 1.0} for i in range(6)]
    value, _how = derive_toc_threshold(picks)
    assert value == 1.0  # 1.0 이상인 확률은 없으므로 채택 0


def test_self_check_gate_holds_even_when_the_threshold_falls_back():
    """답이 적어 문턱이 상수로 물러서도 **자기 검증에 실패한 답은 들이지 않는다**.

    이 구멍이 실제로 있었다(2026-09-21): 답 4개 배치에서 fallback 0.8이 엉뚱한 행 하나를
    그대로 통과시켰다. 확률과 자기 검증은 다른 관문이다.
    """
    from core.structure_llm import derive_toc_threshold, toc_picks_to_proposals

    picks = [
        {"prob": 0.95, "sim": 1.0, "page": 1, "line_index": 0, "title": "가", "entry": 0},
        {"prob": 0.90, "sim": 0.1, "page": 2, "line_index": 0, "title": "나", "entry": 0},  # 엉뚱
        {"prob": 0.88, "sim": 1.0, "page": 3, "line_index": 0, "title": "다", "entry": 0},
        {"prob": 0.80, "sim": 1.0, "page": 4, "line_index": 0, "title": "라", "entry": 0},
    ]

    class _E:
        level = 2

    value, how = derive_toc_threshold(picks)
    assert how["how"] == "fallback"  # 넷뿐이라 절벽을 말할 근거가 없다
    got = toc_picks_to_proposals(picks, [_E()] * 4, value)
    assert [p["page"] for p in got] == [1, 3, 4]  # 엉뚱한 2쪽은 문턱을 넘어도 빠진다


def test_a_pick_without_a_self_check_value_is_not_stood_up():
    """`sim`이 없는 답은 «검증할 수 없는 답»이므로 세우지 않는다.

    실제 경로(`match_toc_entries_jev`)는 늘 `sim`을 싣는다. 다른 생산자가 빠뜨리면 조용히
    통과시키는 대신 조용히 빠지는데, **둘 중에는 뒤가 낫다** — 검증 못 한 자리를 경계 후보로
    세우면 사람이 «코드가 확인한 것»으로 읽는다. 이 시험은 그 선택을 못 박아 둔다.
    """
    from core.structure_llm import toc_picks_to_proposals

    class _E:
        level = 2

    picks = [{"entry": 0, "title": "가", "page": 1, "line_index": 0, "prob": 0.99}]
    assert toc_picks_to_proposals(picks, [_E()], 0.5) == []


def test_screen_keeps_rule_places_when_the_model_answers(tmp_path):
    """**모델의 답은 규칙 후보를 거르지 않는다 — 합집합이다.**

    이 설계의 핵심 결정(D-129 1항)이고, 측정이 강제한 것이다: 천진담초에서는 «규칙 ∩ 모델»이
    가장 좋았지만 운양집에서 같은 구성은 규칙의 재현을 그대로 물려받아 0.880 → 0.176으로
    무너졌다. 규칙 후보로 거르면 **규칙이 못 보는 책에서는 모델도 함께 눈이 먼다.**

    **깨뜨려 본 기록(2026-09-22).** 합쳐지는 자리는 `_mergeLlmProposals` 하나인데 그때까지
    시험이 없었다 — D-129를 적으며 「이 주장을 무엇이 지키는가」를 묻다가 드러났다. 지금
    이 시험은 이렇게 갈린다:

    - 합치기를 «교집합»으로 바꾸면(모델이 가리키지 않은 규칙 후보를 버림) → **빨간불**
    - 합치기를 «모델 답으로 갈아 끼우기»로 바꾸면 → **빨간불**
    - 억제한 자리를 되살리게 하면 → **빨간불**
    """
    from tests.js_harness import run_js

    setup = """
      const proposeState = { llm: { docId: "d1", partId: "vol1", proposals: [
        { page: 1, line_index: 0, char_offset: 0, reasons: ["jev:structure"], confidence: 0.6 },
        { page: 2, line_index: 0, char_offset: 0, reasons: ["jev:structure"], confidence: 0.6 },
        { page: 3, line_index: 0, char_offset: 0, reasons: ["jev:structure"], confidence: 0.6 },
      ] } };
    """
    body = """
      const data = { stats: {}, proposals: [
        { page: 1, line_index: 0, char_offset: 0, reasons: ["date"], confidence: 0.5, accepted: true },
        { page: 1, line_index: 5, char_offset: 0, reasons: ["date"], confidence: 0.5, accepted: true },
        { page: 3, line_index: 0, char_offset: 0, reasons: ["date"], confidence: 0.5, suppressed: true },
      ] };
      _mergeLlmProposals(data, "d1", "vol1");
      const at = (k) => data.proposals.find((p) => _propKey(p) === k);
      console.log(JSON.stringify({
        keys: data.proposals.map(_propKey),
        ruleOnly: at("1:5:0") ? at("1:5:0").reasons : null,
        both: at("1:0:0") ? at("1:0:0").reasons : null,
        suppressedAccepted: at("3:0:0") ? !!at("3:0:0").accepted : null,
        stats: data.stats.llm,
      }));
    """
    got = run_js(tmp_path, "composition-editor.js", ["_mergeLlmProposals", "_propKey"], setup, body)
    # 규칙만 가리킨 자리(1:5)가 살아 있다 — 모델이 거르지 않는다
    assert got["keys"] == ["1:0:0", "1:5:0", "2:0:0", "3:0:0"]
    assert got["ruleOnly"] == ["date"]
    # 둘이 가리킨 자리는 근거만 보탠다(규칙 근거를 지우지 않는다)
    assert got["both"] == ["date", "llm:structure"]
    # 사람이 억제한 자리는 모델이 가리켜도 되살아나지 않는다
    assert got["suppressedAccepted"] is False
    assert got["stats"] == {"added": 1, "joined": 2}
