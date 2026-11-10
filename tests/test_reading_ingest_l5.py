"""강독 결과의 표점본·현토본 → L5 (D-148).

답 형식의 구획에 punct(원문에 표점 부호를 끼운 글)·hyeonto(원문에 한글 토를 끼운 글)가 있으면
끼운 글자만 떼어 해석 저장소의 L5 표점·현토로 담는다. 새 저장 형식은 없다.

지키는 것:
    - 원문 글자가 다르거나 받지 않는 글자가 끼어 있으면 넣지 않고 알린다(자리를 짐작하지 않는다).
    - 사람이 저장한 표점·현토는 다시 들여도 그대로다.
    - 다시 들이면 들이기의 것만 갈아 끼운다(두 벌이 되지 않는다).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.core.hyeonto import render_hyeonto_text
from src.core.punctuation import render_punctuated_text
from src.core.reading_ingest import check_answer, hyeonto_items, punct_marks, split_inserted

ORIGINAL = "王戎簡要裴楷清通"
PUNCT = "王戎簡要，裴楷清通。"
HYEONTO = "王戎은簡要하고裴楷는清通하니"

PLAN = {
    "title": "몽구",
    "guidance": "",
    "ranges": [{"pages": "1-4", "rotation": 0, "engine": "ndlocr", "writing": "vertical_rtl"}],
    "chapters": [{"page": 3, "title": "王戎簡要", "level": 1}],
}
ANSWER = {
    "chapter": "王戎簡要",
    "corrections": [{"page": 3, "text": "王戎簡要\n標題\n王戎簡要裴楷\n清通"}],
    "sections": [
        {
            "heading": "標題",
            "level": 3,
            "page": 3,
            "segments": [
                {"text": ORIGINAL, "ko": "왕융은 간요하고", "punct": PUNCT, "hyeonto": HYEONTO}
            ],
        }
    ],
}


# ── 끼운 글자 떼어 내기 ──────────────────────────────────


class TestSplit:
    def test_punct_roundtrips_through_the_renderer(self):
        marks = punct_marks(ORIGINAL, PUNCT)
        assert [(m["target"]["start"], m["before"], m["after"]) for m in marks] == [
            (3, None, "，"),
            (7, None, "。"),
        ]
        assert render_punctuated_text(ORIGINAL, marks) == PUNCT

    def test_opening_marks_go_before_the_next_character(self):
        marked = "子曰：「學而時習之，不亦說乎？」"
        original = "子曰學而時習之不亦說乎"
        marks = punct_marks(original, marked)
        assert render_punctuated_text(original, marks) == marked
        by_start = {m["target"]["start"]: m for m in marks}
        assert by_start[1]["after"] == "：" and by_start[2]["before"] == "「"
        assert by_start[10]["after"] == "？」"

    def test_leading_mark_and_offset(self):
        marks = punct_marks("詩云", "《詩》云", offset=5)
        assert marks[0]["target"] == {"start": 5, "end": 5} and marks[0]["before"] == "《"
        assert marks[0]["after"] == "》"

    def test_column_breaks_and_spaces_are_ignored(self):
        """확정본의 열 끊김(줄바꿈)과 답의 띄어쓰기는 자리를 흔들지 않는다."""
        original = "王戎簡要裴楷\n清通"
        marks = punct_marks(original, "王戎簡要， 裴楷清通。")
        assert render_punctuated_text(original, marks) == "王戎簡要，裴楷\n清通。"

    def test_hyeonto_roundtrips_through_the_renderer(self):
        items = hyeonto_items(ORIGINAL, HYEONTO)
        assert [(h["target"]["start"], h["position"], h["text"]) for h in items] == [
            (1, "after", "은"),
            (3, "after", "하고"),
            (5, "after", "는"),
            (7, "after", "하니"),
        ]
        assert all(h["category"] is None for h in items)
        assert render_hyeonto_text(ORIGINAL, items) == HYEONTO

    @pytest.mark.parametrize(
        "marked",
        [
            "王戎簡要，裴楷淸通。",  # 원문 글자가 다르다(清 → 淸)
            "王戎簡要，裴楷。",  # 원문이 모자란다
            "王戎簡要，裴楷清通也。",  # 원문에 없는 한자가 끼었다
            "王戎簡要1裴楷清通",  # 부호가 아닌 글자
        ],
    )
    def test_mismatch_is_refused_not_guessed(self, marked):
        assert punct_marks(ORIGINAL, marked) is None

    def test_each_field_takes_only_its_own_kind(self):
        assert hyeonto_items(ORIGINAL, PUNCT) is None  # 현토 칸에 표점
        assert punct_marks(ORIGINAL, HYEONTO) is None  # 표점 칸에 한글
        assert split_inserted("王", "王", lambda ch: False) == ["", ""]

    def test_shape(self):
        bad = copy.deepcopy(ANSWER)
        bad["sections"][0]["segments"][0]["punct"] = ["，"]
        assert any("punct" in p for p in check_answer(bad))
        assert check_answer(ANSWER) == []


# ── 층에 담기 ────────────────────────────────────────────


@pytest.fixture()
def client(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    from fastapi.testclient import TestClient

    from app.server import app

    with TestClient(app) as c:
        yield c


def _setup(client, tmp_path):
    """서고 + 4쪽 문헌 + 작업 계획."""
    import fitz

    r = client.post("/api/library/quick-start")
    assert r.status_code == 200
    lib = Path(r.json()["library_path"])
    pdf = tmp_path / "t.pdf"
    d = fitz.open()
    for _ in range(4):
        d.new_page(width=400, height=600)
    d.save(str(pdf))
    with open(pdf, "rb") as f:
        r = client.post(
            "/api/documents/create-from-files",
            data={"doc_id": "d1", "title": "몽구"},
            files=[("files", ("t.pdf", f.read(), "application/pdf"))],
        )
    assert r.status_code == 200, r.text
    part = r.json()["parts"][0]["part_id"]
    r = client.put("/api/documents/d1/read-plan", json={"plan": PLAN, "part_id": part})
    assert r.status_code == 200, r.text
    return lib, part


def _ingest(client, part, answer=ANSWER):
    r = client.post("/api/documents/d1/reading-notes", json={"note": answer, "part_id": part})
    assert r.status_code == 200, r.text
    return r.json()


def _l5(lib, res, kind):
    folder = lib / "interpretations" / res["interp_id"] / "L5_reading" / "main_text"
    return sorted(folder.glob(f"*_{kind}.json"))


def test_punct_and_hyeonto_go_into_l5_and_render_back(client, tmp_path):
    lib, part = _setup(client, tmp_path)
    res = _ingest(client, part)
    assert res["unplaced_segments"] == [] and res["l5_unplaced"] == [] and res["l5_kept"] == []
    assert res["punctuation"] == 2 and res["hyeonto"] == 4
    (pfile,) = _l5(lib, res, "punctuation")
    (hfile,) = _l5(lib, res, "hyeonto")
    pdata = json.loads(pfile.read_text("utf-8"))
    hdata = json.loads(hfile.read_text("utf-8"))
    assert pdata["block_id"] == hdata["block_id"]
    # 단위 원문 위에 다시 그리면 답의 표점본·현토본이 나온다(글자 좌표가 단위 기준으로 맞다)
    from core.boundaries import compute_units, load_doc_boundaries
    from core.segmentation import collect_document_lines

    doc = lib / "documents" / "d1"
    lines, page_texts = collect_document_lines(doc, part, None)
    units = compute_units(load_doc_boundaries(doc, "d1", part), lines, page_texts)
    text = next(u for u in units if u["id"] == pdata["block_id"])["original_text"]
    flat = "".join
    assert flat(render_punctuated_text(text, pdata["marks"]).split()).endswith(PUNCT)
    assert flat(render_hyeonto_text(text, hdata["annotations"]).split()).endswith(HYEONTO)

    # 다시 들여도 들이기의 것만 갈아 끼운다 — 파일도 항목도 늘지 않는다
    again = _ingest(client, part)
    assert again["punctuation"] == 2 and again["hyeonto"] == 4 and again["l5_kept"] == []
    assert len(_l5(lib, again, "punctuation")) == 1 and len(_l5(lib, again, "hyeonto")) == 1
    assert len(json.loads(pfile.read_text("utf-8"))["marks"]) == 2


def test_human_punctuation_survives_reimport(client, tmp_path):
    lib, part = _setup(client, tmp_path)
    res = _ingest(client, part)
    (pfile,) = _l5(lib, res, "punctuation")
    data = json.loads(pfile.read_text("utf-8"))
    mine = [{"id": "pm_human1", "target": {"start": 0, "end": 0}, "before": None, "after": "、"}]
    r = client.put(
        f"/api/interpretations/{res['interp_id']}/pages/3/punctuation?part_id={part}",
        json={"block_id": data["block_id"], "marks": mine},
    )
    assert r.status_code == 200, r.text
    again = _ingest(client, part)
    assert again["punctuation"] == 0 and len(again["l5_kept"]) == 1
    assert again["l5_kept"][0].startswith("표점")
    assert json.loads(pfile.read_text("utf-8"))["marks"] == mine
    assert again["hyeonto"] == 4  # 현토는 사람이 건드리지 않았다 — 그대로 갈아 끼운다


def test_uncommitted_human_edit_survives_reimport(client, tmp_path):
    """커밋하지 않은 수정도 사람의 것이다(작업 파일이 들이기 커밋과 다르다)."""
    lib, part = _setup(client, tmp_path)
    res = _ingest(client, part)
    (hfile,) = _l5(lib, res, "hyeonto")
    data = json.loads(hfile.read_text("utf-8"))
    data["annotations"][0]["text"] = "이"
    hfile.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    again = _ingest(client, part)
    assert again["hyeonto"] == 0 and any(k.startswith("현토") for k in again["l5_kept"])
    assert json.loads(hfile.read_text("utf-8"))["annotations"][0]["text"] == "이"


def test_mismatch_is_reported_and_nothing_is_written(client, tmp_path):
    lib, part = _setup(client, tmp_path)
    answer = copy.deepcopy(ANSWER)
    answer["sections"][0]["segments"][0]["punct"] = "王戎簡要，裴楷淸通。"
    del answer["sections"][0]["segments"][0]["hyeonto"]
    res = _ingest(client, part, answer)
    assert res["punctuation"] == 0 and res["hyeonto"] == 0
    assert len(res["l5_unplaced"]) == 1 and res["l5_unplaced"][0].startswith("표점")
    assert res["translations"] == 1  # 국역은 그대로 들어간다
    assert _l5(lib, res, "punctuation") == [] and _l5(lib, res, "hyeonto") == []


def test_answer_without_the_fields_writes_no_l5(client, tmp_path):
    lib, part = _setup(client, tmp_path)
    answer = copy.deepcopy(ANSWER)
    for key in ("punct", "hyeonto"):
        del answer["sections"][0]["segments"][0][key]
    res = _ingest(client, part, answer)
    assert res["punctuation"] == 0 and res["hyeonto"] == 0 and res["l5_unplaced"] == []
    assert _l5(lib, res, "punctuation") == [] and _l5(lib, res, "hyeonto") == []
