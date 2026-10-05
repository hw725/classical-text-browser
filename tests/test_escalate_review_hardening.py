"""D-137 후속 — 애매한 후보 2차 판정의 들이기 방어 (2026-10-05 리뷰 지적 6건 중 서버 쪽 5건).

네트워크 없음. 화면 쪽(«예 N»과 실제 체크 수)은 headless 검증으로 따로 본다.
새 이름은 모듈 속성으로 꺼낸다(`er.X`) — 옛 코드에서 이 파일을 돌리면 import 단계에서 통째로 죽지
않고 시험마다 따로 실패해, 무엇이 막혔는지 셀 수 있게.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import core.escalate_review as er
from core.segmentation import Line
from tests.test_segmentation import _setup, client  # noqa: F401 — fixture 재사용


def _lines(n_pages: int, rows: int) -> list[Line]:
    return [
        Line(page=p, line_index=i, text=f"行{p}-{i}")
        for p in range(1, n_pages + 1)
        for i in range(rows)
    ]


def _store(tmp_path, positions, n_pages=9, rows=10, doc="d1", part="v1"):
    lib = tmp_path / "lib"
    lib.mkdir(exist_ok=True)
    lines = _lines(n_pages, rows)
    er.save_candidates(lib, doc, part, lines, positions, source="screen")
    return lib, lines


# ── 1. 지시문 예시 id가 진짜 판정으로 들어가지 않는다 ────────────────────────────
def test_example_id_in_instructions_can_never_be_a_candidate():
    """예시 id는 쪽 0 — 쪽은 1부터 세므로 어떤 확정본 행도 그 id를 갖지 않는다."""
    text = er.render_chunk_text(
        [{"id": "p8-L3", "before": [], "text": "十二月初一日", "after": []}], 1, 1, None, "d1", "v1"
    )
    instr = text.split(er.CANDIDATES_MARKER)[0]
    ex_ids = re.findall(r'"id"\s*:\s*"(p\d+-L\d+)"', instr)
    assert ex_ids, "지시문에 답 예시가 있어야 한다"
    assert all(i.startswith("p0-") for i in ex_ids), ex_ids


def test_pasting_the_exported_chunk_back_is_refused(tmp_path):
    """클립보드가 없으면 화면이 내보낸 글을 답 칸에 띄운다 — 그대로 들이면 거부·안내."""
    lib, lines = _store(tmp_path, [(8, 3), (9, 1)])
    out = er.export_from_store(lib, "d1", "v1", lines)
    chunk = out["chunks"][0]["text"]
    with pytest.raises(ValueError, match="그대로 붙인"):
        er.import_answers(lib, "d1", "v1", chunk)
    assert er.load_store(lib, "d1", "v1")["verdicts"] == {}


def test_answer_that_echoes_instructions_is_refused(tmp_path):
    """채팅 LLM이 지시문을 되풀이한 뒤 답했다 — 예시 줄을 답으로 읽지 않게 통째로 거부한다."""
    lib, lines = _store(tmp_path, [(8, 3), (9, 1)])
    chunk = er.export_from_store(lib, "d1", "v1", lines)["chunks"][0]["text"]
    echoed = chunk + '\n\n{"answers":[{"id":"p9-L1","start":"no","conf":0.8}]}'
    with pytest.raises(ValueError, match="그대로 붙인"):
        er.import_answers(lib, "d1", "v1", echoed)


def test_route_refuses_self_paste_with_400(client, tmp_path):  # noqa: F811
    _lib, part_id = _setup(client, tmp_path)
    r = client.post(
        "/api/documents/d1/segmentation/escalate/export",
        json={"part_id": part_id, "candidates": [{"page": 1, "line_index": 2}]},
    )
    chunk = r.json()["chunks"][0]["text"]
    r = client.post(
        "/api/documents/d1/segmentation/escalate/import",
        json={"part_id": part_id, "answer_text": chunk},
    )
    assert r.status_code == 400 and "그대로 붙인" in r.json()["error"]


# ── 2. 다른 권·문헌의 답을 가려낸다 ─────────────────────────────────────────
def test_chunks_carry_a_short_batch_tag_and_the_doc_and_part():
    out = er.export_chunks(_lines(3, 100), [(p, i) for p in (1, 2, 3) for i in range(70)],
                           100, None, "d1", "v1")
    tags = [c["tag"] for c in out["chunks"]]
    assert tags == [er.batch_tag("d1", "v1", n) for n in (1, 2, 3)]
    assert all(re.fullmatch(r"esc-[0-9a-f]{6}-\d+", t) for t in tags)
    first = out["chunks"][0]["text"]
    head = first.splitlines()[0]
    assert "d1" in head and "v1" in head and tags[0] in head
    assert f'"batch":"{tags[0]}"' in first  # 답 예시가 표지를 되받는 모양을 보여 준다
    assert er.batch_tag("d1", "v1", 1) != er.batch_tag("d1", "v2", 1)


def test_answer_with_another_volumes_tag_is_refused(tmp_path):
    lib, _ = _store(tmp_path, [(1, 2), (2, 1)])
    other = er.batch_tag("d1", "v2", 1)
    ans = json.dumps({"batch": other, "answers": [{"id": "p1-L2", "start": "yes", "conf": 0.9}]})
    with pytest.raises(ValueError, match="다른 문헌·권"):
        er.import_answers(lib, "d1", "v1", ans)
    assert er.load_store(lib, "d1", "v1")["verdicts"] == {}
    # 제 표지면 받는다
    mine = ans.replace(other, er.batch_tag("d1", "v1", 1))
    res = er.import_answers(lib, "d1", "v1", mine)
    assert res["counts"]["yes"] == 1 and res["tag_status"] == "ok" and not res["warnings"]


def test_untagged_answer_is_accepted_but_warns_when_most_ids_are_rejected(tmp_path):
    lib, _ = _store(tmp_path, [(1, 2), (2, 1)])
    # 옛 답(표지 없음) — 대부분 후보 밖: 다른 권의 답일 공산이 크다
    ans = json.dumps({"answers": [
        {"id": "p1-L2", "start": "yes"},
        {"id": "p50-L1", "start": "no"},
        {"id": "p51-L1", "start": "no"},
    ]})
    res = er.import_answers(lib, "d1", "v1", ans)
    assert res["tag_status"] == "absent" and res["counts"]["yes"] == 1
    assert res["warnings"] and "절반" in res["warnings"][0]
    # 거부가 절반 이하면 경고 없음
    ok = json.dumps({"answers": [{"id": "p2-L1", "start": "no"}, {"id": "p1-L2", "start": "yes"}]})
    assert er.import_answers(lib, "d1", "v1", ok)["warnings"] == []


# ── 3. 깊은 중첩·너무 긴 붙여 넣기가 서버를 죽이지 않는다 ──────────────────────
def test_deeply_nested_paste_does_not_crash_the_parser():
    deep = '{"a":[' * 5000
    r = er.parse_answers(deep, ["p1-L0"])
    assert r["verdicts"] == {} and r["parse_status"] == "no_json"


def test_route_answers_400_not_500_for_deep_or_huge_paste(client, tmp_path):  # noqa: F811
    _lib, part_id = _setup(client, tmp_path)
    client.post(
        "/api/documents/d1/segmentation/escalate/export",
        json={"part_id": part_id, "candidates": [{"page": 1, "line_index": 2}]},
    )
    url = "/api/documents/d1/segmentation/escalate/import"
    r = client.post(url, json={"part_id": part_id, "answer_text": '{"a":[' * 5000})
    assert r.status_code == 200 and r.json()["parse_status"] == "no_json"
    huge = "x" * (er.MAX_ANSWER_CHARS + 1)
    r = client.post(url, json={"part_id": part_id, "answer_text": huge})
    assert r.status_code == 400 and "너무 깁니다" in r.json()["error"]


# ── 4. 문헌·권 id가 서고 밖으로 빠지지 않는다 ────────────────────────────────
@pytest.mark.parametrize(
    "doc,part",
    [("..", "v1"), ("d1", ".."), ("a/b", "v1"), ("d1", "x\\y"), ("C:\\x", "v1"), ("", "v1")],
)
def test_store_path_refuses_ids_that_leave_the_library(doc, part):
    with pytest.raises(ValueError):
        er.store_path("LIB", doc, part)


def test_cli_refuses_parent_doc_and_writes_nothing_outside(client, tmp_path, capsys):  # noqa: F811
    import importlib.util

    lib, part_id = _setup(client, tmp_path)
    spec = importlib.util.spec_from_file_location(
        "escalate_review_cli_h",
        Path(__file__).resolve().parents[1] / "scripts" / "escalate_review.py",
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    ans = tmp_path / "a.json"
    ans.write_text('{"answers": []}', encoding="utf-8")
    before = sorted(p.name for p in Path(lib).iterdir())
    # «documents/..»는 서고 자체라 «있는 폴더»로 통과했다 — 이제는 id 검사에서 멈춘다
    rc = cli.main(["import", "--library", lib, "--doc", "..", "--part", part_id, "--in", str(ans)])
    assert rc == 1 and "폴더 이름 하나" in capsys.readouterr().err
    rc = cli.main(["export", "--library", lib, "--doc", "d1", "--part", "..",
                   "--out", str(tmp_path / "o.txt")])
    assert rc == 1 and "폴더 이름 하나" in capsys.readouterr().err
    assert sorted(p.name for p in Path(lib).iterdir()) == before
    assert not (Path(lib) / ".escalate_review" / f"{part_id}.json").exists()


def test_routes_refuse_parent_part_id(client, tmp_path):  # noqa: F811
    _setup(client, tmp_path)
    r = client.post(
        "/api/documents/d1/segmentation/escalate/export",
        json={"part_id": "..", "candidates": [{"page": 1, "line_index": 2}]},
    )
    assert r.status_code == 400
    r = client.get("/api/documents/d1/segmentation/escalate?part_id=..")
    assert r.status_code == 400


# ── 5. 목록이 바뀌어도 들인 판정은 남고, 다시 판정은 결과에 드러난다 ────────────
def test_export_with_a_narrower_list_keeps_verdicts_outside_it(tmp_path):
    lib, lines = _store(tmp_path, [(1, 2), (2, 1), (3, 0)])
    er.import_answers(lib, "d1", "v1", json.dumps({"answers": [
        {"id": "p1-L2", "start": "yes"}, {"id": "p3-L0", "start": "no"},
    ]}))
    # 화면이 「상위 N」 등으로 좁힌 목록으로 다시 내보낸다 — p3-L0은 목록 밖
    er.save_candidates(lib, "d1", "v1", lines, [(1, 2), (2, 1)], source="screen")
    store = er.load_store(lib, "d1", "v1")
    assert set(store["verdicts"]) == {"p1-L2", "p3-L0"}  # 기록은 남는다
    assert set(er.current_verdicts(store)) == {"p1-L2"}  # 쓰이는 것은 지금 목록의 것
    # 다시 넓히면 옛 판정이 되살아난다(다시 묻지 않아도 된다)
    er.save_candidates(lib, "d1", "v1", lines, [(1, 2), (2, 1), (3, 0)], source="screen")
    assert er.current_verdicts(er.load_store(lib, "d1", "v1"))["p3-L0"]["start"] == "no"
    # 확정본 글이 바뀐 자리의 옛 판정은 버린다 — 다른 글에 대한 답이다
    changed = [Line(page=ln.page, line_index=ln.line_index,
                    text="新" if (ln.page, ln.line_index) == (3, 0) else ln.text) for ln in lines]
    er.save_candidates(lib, "d1", "v1", changed, [(1, 2)], source="screen")
    assert set(er.load_store(lib, "d1", "v1")["verdicts"]) == {"p1-L2"}


def test_reanswering_the_same_id_is_reported_as_rejudged(tmp_path):
    lib, _ = _store(tmp_path, [(1, 2), (2, 1)])
    er.import_answers(lib, "d1", "v1", json.dumps({"answers": [
        {"id": "p1-L2", "start": "yes"}, {"id": "p2-L1", "start": "no"},
    ]}))
    res = er.import_answers(lib, "d1", "v1", json.dumps({"answers": [
        {"id": "p1-L2", "start": "no"}, {"id": "p2-L1", "start": "no"},
    ]}))
    assert res["rejudged"] == 2 and res["flipped"] == 1
    assert er.load_store(lib, "d1", "v1")["verdicts"]["p1-L2"]["start"] == "no"  # 덮는다


def test_get_route_returns_only_current_candidates_verdicts(client, tmp_path):  # noqa: F811
    lib, part_id = _setup(client, tmp_path)
    url = "/api/documents/d1/segmentation/escalate"
    client.post(f"{url}/export", json={"part_id": part_id, "candidates": [
        {"page": 1, "line_index": 2}, {"page": 2, "line_index": 1}]})
    r = client.post(f"{url}/import", json={"part_id": part_id, "answer_text": json.dumps(
        {"answers": [{"id": "p1-L2", "start": "yes"}, {"id": "p2-L1", "start": "no"}]})})
    assert r.status_code == 200, r.text
    client.post(f"{url}/export", json={"part_id": part_id, "candidates": [
        {"page": 1, "line_index": 2}]})
    assert set(client.get(f"{url}?part_id={part_id}").json()["verdicts"]) == {"p1-L2"}
    assert set(er.load_store(lib, "d1", part_id)["verdicts"]) == {"p1-L2", "p2-L1"}
