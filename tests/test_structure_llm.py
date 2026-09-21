"""D-125 — 구조를 통째로 묻기: 모델은 행 번호를 고르기만 하고, 코드가 실제 행에 대조한다."""

import asyncio
import json

from core.segmentation import Line
from core.structure_llm import (
    CONFIDENCE,
    REASON,
    ask_structure_llm,
    chunk_lines,
    parse_line_id,
    render_chunk,
    structure_size,
    validate_items,
)
from tests.test_segmentation import _FakeRouter, _setup, client  # noqa: F401 — fixture 재사용

_COL = "山川草木風雲雨雪日月星辰花鳥魚蟲春夏秋冬"


def _book(pages=4, rows=6):
    """쪽마다 rows행. 첫 행은 짧은 표제, 셋째 행은 빈 행(보내지 않아야 한다)."""
    lines = []
    for p in range(1, pages + 1):
        for i in range(rows):
            text = f"題{p}" if i == 0 else "" if i == 2 else _COL
            lines.append(Line(page=p, line_index=i, text=text))
    return lines


def test_line_id_round_trip_and_lenient_parse():
    assert parse_line_id("p8-L3") == (8, 3)
    assert parse_line_id(" 행 p12-L0 ") == (12, 0)
    assert parse_line_id("8-3") is None and parse_line_id(None) is None


def test_chunks_split_at_page_boundaries_and_skip_empty_lines():
    lines = _book(pages=4)
    chunks = chunk_lines(lines, max_chars=2 * (2 + 4 * len(_COL)) + 1)
    assert len(chunks) == 2 and [ln.page for ln in chunks[0]] == [1] * 5 + [2] * 5
    assert all(ln.text.strip() for c in chunks for ln in c)
    size = structure_size(lines, max_chars=10)  # 한 쪽이 묶음보다 커도 쪽은 자르지 않는다
    assert size["calls"] == 4 and size["lines"] == 20
    text = render_chunk(chunks[0])
    assert text.startswith("— 1쪽 —\np1-L0\t題1\n") and "p1-L2\t" not in text


def test_validate_keeps_real_lines_and_fixes_titles():
    lines = _book(pages=1)
    items = [
        {"line": "p1-L0", "title": "題1", "level": 1, "role": "container"},
        {"line": "p1-L3", "title": "없는 제목", "level": "2", "role": "poem"},  # 제목은 행 글자로
        {"line": "p1-L2", "title": "x"},  # 빈 행
        {"line": "p9-L1", "title": "x"},  # 없는 쪽
        {"line": "p1-L0", "title": "題1"},  # 되풀이
        "문자열",  # 객체가 아님
        {"title": "번호 없음"},
    ]
    out, stats = validate_items(lines, items, max_title_chars=6)
    assert [(p["page"], p["line_index"]) for p in out] == [(1, 0), (1, 3)]
    assert out[0]["role"] == "container" and out[0]["level"] == 1
    assert out[1]["title"] == _COL[:6] and out[1]["role"] == "article" and out[1]["level"] == 2
    assert all(p["reasons"] == [REASON] and p["confidence"] == CONFIDENCE for p in out)
    assert all(p["accepted"] and p["char_offset"] == 0 for p in out)
    assert stats["title_fixed"] == 1 and stats["dropped"] == 5
    assert stats["reasons"] == {"unknown_line": 2, "duplicate": 1, "not_object": 1, "no_line_id": 1}


def test_ask_sends_numbered_text_per_chunk_and_merges_answers():
    lines = _book(pages=4)
    router = _FakeRouter(
        json.dumps(
            {
                "starts": [{"line": "p1-L0", "title": "題1"}, {"line": "p3-L0", "title": "題3"}],
                "note": "표제는 짧은 행",
            }
        )
    )
    out, meta = asyncio.run(ask_structure_llm(lines, router, max_chars=2 * (2 + 4 * len(_COL)) + 1))
    assert meta["calls"] == 2 and len(router.calls) == 2
    assert router.calls[0]["response_format"] == "json" and router.calls[0]["think"] is False
    # 같은 답이 두 묶음에서 오면 되풀이는 하나만 남는다
    assert [(p["page"], p["line_index"]) for p in out] == [(1, 0), (3, 0)]
    assert meta["said"] == 4 and meta["dropped"] == 2 and meta["provider"] == "fake"
    assert meta["notes"] == ["표제는 짧은 행"] * 2 and meta["error"] is None


def test_ask_survives_a_bad_chunk_and_reports_it():
    lines = _book(pages=2)

    class Router:
        def __init__(self):
            self.n = 0

        async def call(self, prompt, **kwargs):
            self.n += 1
            if self.n == 1:
                raise RuntimeError("모델 없음")

            class R:
                text, provider, model = '{"starts": [{"line": "p2-L0", "title": "題2"}]}', "f", "m"

            return R()

    out, meta = asyncio.run(ask_structure_llm(lines, Router(), max_chars=100))
    assert [(p["page"], p["line_index"]) for p in out] == [(2, 0)]
    assert "1번째 묶음" in meta["error"] and "모델 없음" in meta["error"]


def test_route_dry_run_counts_without_calling_model(client, tmp_path):  # noqa: F811
    _lib, part_id = _setup(client, tmp_path)
    r = client.post(
        "/api/documents/d1/segmentation/structure/llm",
        json={"part_id": part_id, "dry_run": True},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["dry_run"] is True and d["lines"] > 0 and d["chars"] > 0 and d["calls"] == 1
    assert d["proposals"] == []


def test_route_returns_validated_proposals(client, tmp_path, monkeypatch):  # noqa: F811
    from app import _state

    _lib, part_id = _setup(client, tmp_path)
    fake = _FakeRouter(
        json.dumps(
            {
                "starts": [
                    {"line": "p1-L0", "title": "天津奉使緣起", "level": 1, "role": "container"},
                    {"line": "p3-L0", "title": "十二月初一日", "level": 2},
                    {"line": "p7-L0", "title": "없는 쪽"},
                ]
            }
        )
    )
    monkeypatch.setattr(_state, "_llm_router", fake)
    r = client.post(
        "/api/documents/d1/segmentation/structure/llm",
        json={"part_id": part_id, "reference_text": "해제 한 줄"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    got = [(p["page"], p["line_index"], p["level"]) for p in d["proposals"]]
    assert got == [(1, 0, 1), (3, 0, 2)]
    assert d["dropped"] == 1 and d["model"] == "fake-1" and d["calls"] == 1
    assert fake.calls[0]["system"] and fake.calls[0]["response_format"] == "json"
    # 자리는 ③가 그대로 쓰는 모양이다 — 적용 요청의 spans로 바로 들어간다
    for p in d["proposals"]:
        assert set(p) >= {"page", "line_index", "char_offset", "title", "level", "role", "reasons"}


# ── 같은 라우트의 판정 모델 길(engine="jev") ────────────────────────────────
def test_route_jev_dry_run_counts_questions_and_cost(client, tmp_path):  # noqa: F811
    """보내기 전에 «몇 행·몇 질문·몇 번·얼마»를 돌려준다 — 실행 게이트는 도구 층에(전역 규칙 11)."""
    _lib, part_id = _setup(client, tmp_path)
    r = client.post(
        "/api/documents/d1/segmentation/structure/llm",
        json={"part_id": part_id, "engine": "jev", "dry_run": True},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["engine"] == "jev" and d["dry_run"] is True
    assert d["questions"] == d["lines"] and d["calls"] >= 1 and d["cost_usd_est"] > 0
    assert d["proposals"] == []


def test_route_jev_returns_proposals_and_never_calls_the_generative_router(
    client, tmp_path, monkeypatch  # noqa: F811
):
    """판정 모델 길은 LlmRouter를 거치지 않는다 — 라우터의 계약은 «프롬프트 → 글»이다."""
    import llm.jev as jev
    from app import _state

    _lib, part_id = _setup(client, tmp_path)
    router = _FakeRouter('{"starts": []}')
    monkeypatch.setattr(_state, "_llm_router", router)

    class FakeClient:
        model = "fake-jev"
        has_key = True

        def __init__(self, **kwargs):
            self.calls = 0

        def gate(self, planned):
            return None

        def ask(self, state, questions):
            self.calls += 1
            # 첫 행만 «시작»이라고 답한다 — 나머지는 본문
            return {
                qid: {"type": "noul", "noul": 0.95 if qid.endswith("-L0") else 0.1}
                for qid in questions
            }

        def usage(self):
            return {"calls": self.calls, "cost_usd": 0.0}

    monkeypatch.setattr(jev, "JevClient", FakeClient)
    r = client.post(
        "/api/documents/d1/segmentation/structure/llm",
        json={"part_id": part_id, "engine": "jev"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["engine"] == "jev" and d["proposals"]
    assert {p["line_index"] for p in d["proposals"]} == {0}
    assert all(p["reasons"] == ["jev:structure"] for p in d["proposals"])
    assert router.calls == []  # 생성 모델은 한 번도 부르지 않았다


def test_route_jev_says_so_when_there_is_no_key(client, tmp_path, monkeypatch):  # noqa: F811
    """키가 없으면 한 건도 쏘지 않고 한국어로 원인과 해결책을 돌려준다."""
    import llm.jev as jev

    _lib, part_id = _setup(client, tmp_path)

    class NoKey:
        has_key = False

        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(jev, "JevClient", NoKey)
    r = client.post(
        "/api/documents/d1/segmentation/structure/llm",
        json={"part_id": part_id, "engine": "jev"},
    )
    assert r.status_code == 400
    assert "TYPESAFE_API_KEY" in r.json()["error"]
