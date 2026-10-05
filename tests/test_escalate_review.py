"""D-137 — 애매한 후보 2차 판정: 내보내기·들이기는 모델을 부르지 않고, 모델은 행을 더할 수 없다.

네트워크 없음. 화면 라우트·CLI·core가 같은 함수를 쓰는지, 결과가 «체크 제안»에 그치는지를 본다.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.escalate_review import (
    AFTER_LINES,
    BEFORE_LINES,
    INSTRUCTIONS,
    candidate_items,
    export_chunks,
    load_store,
    parse_answers,
    store_path,
)
from core.segmentation import Line
from tests.test_segmentation import _setup, client  # noqa: F401 — fixture 재사용


def _lines(n_pages: int = 3, rows: int = 100) -> list[Line]:
    out = []
    for p in range(1, n_pages + 1):
        for i in range(rows):
            out.append(Line(page=p, line_index=i, text="" if i == 5 else f"行{p}-{i}"))
    return out


# ── 내보내기 ──────────────────────────────────────────────────────────────
def test_items_carry_context_but_never_probabilities():
    lines = _lines(n_pages=2, rows=10)
    items, skipped = candidate_items(
        lines, [{"page": 2, "line_index": 0, "prob": 0.77}, (1, 7), (9, 9)]
    )
    assert skipped == ["p9-L9"]  # 지금 확정본에 없는 자리는 빼고 알린다
    first = items[0]
    assert first["id"] == "p1-L7" and first["text"] == "行1-7"
    # 빈 행(5)은 건너뛰고 앞 4행을 잇는다
    assert first["before"] == ["行1-2", "行1-3", "行1-4", "行1-6"] and BEFORE_LINES == 4
    assert first["after"] == ["行1-8", "行1-9"] and len(first["after"]) <= AFTER_LINES
    # 쪽 첫 행의 문맥은 앞 쪽 끝이다
    assert items[1]["id"] == "p2-L0" and items[1]["before"][-1] == "行1-9"
    assert set(first) == {"id", "before", "text", "after"}


def test_export_splits_into_chunks_of_at_most_100_and_states_the_contract():
    lines = _lines(n_pages=3, rows=100)
    positions = [(p, i) for p in (1, 2, 3) for i in range(0, 100, 1) if i != 5][:250]
    out = export_chunks(lines, positions, book_type="diary")
    assert out["count"] == 250 and [c["label"] for c in out["chunks"]] == ["1/3", "2/3", "3/3"]
    assert [len(c["ids"]) for c in out["chunks"]] == [100, 100, 50]
    text = out["chunks"][0]["text"]
    assert "묶음 1/3" in text and "날짜로 시작하는 표제 행" in text
    assert '"answers"' in text and '"start"' in text and '"conf"' in text and '"yes"' in text
    assert INSTRUCTIONS.splitlines()[0] in text
    # 후보 줄은 JSON이고 확률 칸이 없다
    rows = [json.loads(ln) for ln in text.splitlines() if ln.startswith('{"id"')]
    assert len(rows) == 100 and all(set(r) == {"id", "before", "text", "after"} for r in rows)
    assert "prob" not in text and "noul" not in text


# ── 들이기 ────────────────────────────────────────────────────────────────
IDS = [f"p1-L{i}" for i in range(6)]


def test_import_reads_fenced_json_with_prose_and_validates_ids():
    answer = (
        "판정 결과입니다.\n```json\n"
        + json.dumps(
            {
                "answers": [
                    {"id": "p1-L0", "start": "yes", "conf": 0.9},
                    {"id": "p1-L1", "start": "no", "conf": 0.8},
                    {
                        "id": "p7-L7",
                        "start": "yes",
                        "conf": 1.0,
                    },  # 후보 밖 — 모델이 행을 못 더함
                    {"id": "p1-L2", "start": "maybe"},  # 모양 틀림
                    "문자열",  # 모양 틀림
                    {"start": "yes"},  # id 없음
                    {"id": "p1-L0", "start": "no"},  # 되풀이 — 먼저 온 답을 쓴다
                    {"id": "p1-L3", "start": "NO", "conf": 7},  # conf 범위 밖은 None, 판정은 산다
                ]
            },
            ensure_ascii=False,
        )
        + "\n```\n이상입니다."
    )
    r = parse_answers(answer, IDS, chunk_size=100)
    assert r["verdicts"] == {
        "p1-L0": {"start": "yes", "conf": 0.9},
        "p1-L1": {"start": "no", "conf": 0.8},
        "p1-L3": {"start": "no", "conf": None},
    }
    assert r["unknown_ids"] == ["p7-L7"] and r["counts"]["rejected"] == 1
    assert r["counts"]["malformed"] == 3 and r["duplicates"] == 1
    assert r["missing_ids"] == ["p1-L2", "p1-L4", "p1-L5"]
    assert r["counts"] == {"yes": 1, "no": 2, "missing": 3, "rejected": 1, "malformed": 3}


def test_missing_counts_only_the_chunks_the_answer_touched():
    ids = [f"p1-L{i}" for i in range(250)]
    ans = json.dumps({"answers": [{"id": i, "start": "no"} for i in ids[:99]]})
    r = parse_answers(ans, ids, chunk_size=100)
    assert r["missing_ids"] == ["p1-L99"]  # 2/3·3/3은 아직 붙이지 않았을 뿐이다
    # 덩어리 둘의 답을 이어 붙여도 읽는다
    two = ans + "\n\n" + json.dumps({"answers": [{"id": "p1-L150", "start": "yes"}]})
    r2 = parse_answers(two, ids, chunk_size=100)
    assert r2["counts"]["yes"] == 1 and r2["counts"]["missing"] == 1 + 99
    assert parse_answers("모르겠습니다", ids)["parse_status"] == "no_json"


# ── 라우트: 체크 제안만, 경계는 저장하지 않는다 ─────────────────────────────
def _boundaries_files(lib, part_id):
    d = Path(lib) / "documents" / "d1" / "boundaries"
    return {p.name: p.read_bytes() for p in d.glob("*.json")} if d.exists() else {}


def test_route_round_trip_suggests_only_and_saves_no_boundary(client, tmp_path):  # noqa: F811
    lib, part_id = _setup(client, tmp_path)
    before = _boundaries_files(lib, part_id)
    cands = [
        {"page": 1, "line_index": 2},
        {"page": 2, "line_index": 1},
        {"page": 3, "line_index": 0},
    ]
    r = client.post(
        "/api/documents/d1/segmentation/escalate/export",
        json={"part_id": part_id, "candidates": cands, "chunk_size": 2},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["count"] == 3 and [c["label"] for c in d["chunks"]] == ["1/2", "2/2"]
    assert "辛巳十一月二十八日保定督署談草" in d["chunks"][0]["text"]
    answer = {
        "answers": [
            {"id": "p1-L2", "start": "yes", "conf": 0.9},
            {"id": "p2-L1", "start": "no", "conf": 0.6},
            {"id": "p99-L0", "start": "yes"},
        ]
    }
    r = client.post(
        "/api/documents/d1/segmentation/escalate/import",
        json={"part_id": part_id, "answer_text": "```json\n" + json.dumps(answer) + "\n```"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["counts"] == {"yes": 1, "no": 1, "missing": 0, "rejected": 1, "malformed": 0}
    assert d["remaining"] == 1  # 2/2 덩어리(p3-L0)는 아직
    # 경계는 그대로다 — 저장은 「적용」만 한다
    assert _boundaries_files(lib, part_id) == before
    # 메모는 문헌 저장소(git) 밖, 서고 루트에 있다
    sp = store_path(lib, "d1", part_id)
    assert sp.exists() and "documents" not in sp.relative_to(Path(lib)).parts
    r = client.get(f"/api/documents/d1/segmentation/escalate?part_id={part_id}")
    assert r.json()["verdicts"] == {
        "p1-L2": {"start": "yes", "conf": 0.9},
        "p2-L1": {"start": "no", "conf": 0.6},
    }


def test_import_without_candidates_explains_what_to_do(client, tmp_path):  # noqa: F811
    _lib, part_id = _setup(client, tmp_path)
    r = client.post(
        "/api/documents/d1/segmentation/escalate/import",
        json={"part_id": part_id, "answer_text": '{"answers": []}'},
    )
    assert r.status_code == 400 and "판정 모델로 고르기" in r.json()["error"]


def test_judge_run_remembers_escalate_candidates(client, tmp_path, monkeypatch):  # noqa: F811
    """판정 실행이 애매한 후보를 메모에 적어야 서버 없는 CLI가 그 목록으로 내보낼 수 있다."""
    from app.routers import composition
    from core.segmentation import collect_document_lines

    lib, part_id = _setup(client, tmp_path)
    doc_path = Path(lib) / "documents" / "d1"
    lines, _ = collect_document_lines(doc_path, part_id, None)
    props = [
        {"page": 1, "line_index": 2, "band": "escalate", "prob": 0.6},
        {"page": 1, "line_index": 0, "band": "accept", "prob": 0.99},
    ]
    composition._remember_escalate(doc_path, part_id, lines, props)
    store = load_store(lib, "d1", part_id)
    assert [c["id"] for c in store["candidates"]] == ["p1-L2"] and store["source"] == "judge"


# ── CLI: 서버 없이 같은 core 함수로 ─────────────────────────────────────────
def test_cli_round_trip(client, tmp_path):  # noqa: F811
    import importlib.util

    lib, part_id = _setup(client, tmp_path)
    client.post(
        "/api/documents/d1/segmentation/escalate/export",
        json={
            "part_id": part_id,
            "candidates": [{"page": 2, "line_index": 1}, {"page": 3, "line_index": 0}],
        },
    )
    spec = importlib.util.spec_from_file_location(
        "escalate_review_cli",
        Path(__file__).resolve().parents[1] / "scripts" / "escalate_review.py",
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    out = tmp_path / "esc.txt"
    assert (
        cli.main(["export", "--library", lib, "--doc", "d1", "--part", part_id, "--out", str(out)])
        == 0
    )
    text = out.read_text(encoding="utf-8")
    assert '"id": "p2-L1"' in text and '"id": "p3-L0"' in text and "묶음 1/1" in text
    ans = tmp_path / "answers.json"
    ans.write_text(
        "답:\n"
        + json.dumps(
            {
                "answers": [
                    {"id": "p2-L1", "start": "no", "conf": 0.7},
                    {"id": "p3-L0", "start": "yes", "conf": 0.95},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert (
        cli.main(["import", "--library", lib, "--doc", "d1", "--part", part_id, "--in", str(ans)])
        == 0
    )
    v = load_store(lib, "d1", part_id)["verdicts"]
    assert v["p3-L0"]["start"] == "yes" and v["p2-L1"]["start"] == "no"
    # 화면이 같은 메모를 불러온다
    r = client.get(f"/api/documents/d1/segmentation/escalate?part_id={part_id}")
    assert set(r.json()["verdicts"]) == {"p2-L1", "p3-L0"}
