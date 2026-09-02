"""글 경계 제안 테스트 (D-088).

무엇을 고정하는가:
  - 날짜 문법: 干支·月·日·是月·是日·初·廿, 한자 수사
  - 사슬: 是月·일자만 적은 표제는 앞 회차의 달을 물려받고, 일자가 작아지면 달을 올린다
  - 본문 속 날짜(달 역행)는 신뢰도가 내려가 승인되지 않는다
  - 표제 어휘·억제 목록은 규칙(문헌 설정)에서 오고 코드에는 없다
  - 형식 신호: 짧은 행·내려쓰기(bbox)
  - API: 제안은 저장하지 않고, 적용은 쪽별 char_range 출처를 가진 TextBlock을 만든다
"""

from __future__ import annotations

import json

import pytest

from src.core.segmentation import (
    DEFAULT_RULES,
    Line,
    cjk_number,
    normalize_rules,
    parse_date_head,
    propose_boundaries,
    span_to_text_and_refs,
)

# 천진담초(1882) 실제 표제 — 운양 김윤식 텍스트 데이터베이스에서 확인한 원문
CHEONJIN_TITLES = [
    ("辛巳十一月二十八日保定督署談草", "辛巳", 11, 28),
    ("是月三十日替署談草", None, None, 30),
    ("十二月初一日替着遣飮時使通詞傳語口談", None, 12, 1),
    ("壬午正月初十日天津海關道署談草", "壬午", 1, 10),
    ("是月十八日周玉山談草", None, None, 18),
    ("壬午二月十一日與許涑文談草略", "壬午", 2, 11),
    ("二十一日海關署談草", None, None, 21),
    ("是日軍械所與劉薌林談草", None, None, None),
    ("十四日海關署口談節錄", None, None, 14),
    ("六月初七日許涑文談略", None, 6, 7),
]
BODY = "本文本文本文本文本文本文本文本文本文本文本"  # 21자 — 본문 열 길이


class TestDateGrammar:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("十", 10),
            ("二十八", 28),
            ("廿一", 21),
            ("初十", 10),
            ("三十", 30),
            ("正", 1),
            ("臘", 12),
            ("卄三", 23),
            ("三", 3),
        ],
    )
    def test_cjk_number(self, text, expected):
        assert cjk_number(text) == expected

    @pytest.mark.parametrize("title,ganzhi,month,day", CHEONJIN_TITLES)
    def test_real_titles_parse(self, title, ganzhi, month, day):
        h = parse_date_head(title)
        assert h.present
        assert (h.ganzhi, h.month, h.day) == (ganzhi, month, day)

    def test_ganzhi_alone_is_not_a_date(self):
        assert not parse_date_head("壬午年間事").present

    def test_body_sentence_without_date(self):
        assert not parse_date_head("李中堂以筆談問曰").present


def _doc(titles, rules=None, body_lines=3, body=BODY):
    """표제 + 본문 행으로 한 쪽짜리 문헌을 만든다."""
    lines, li = [], 0
    for t in titles:
        lines.append(Line(1, li, t))
        li += 1
        for _ in range(body_lines):
            lines.append(Line(1, li, body))
            li += 1
    return propose_boundaries(lines, rules)


class TestChain:
    def test_month_inherited_and_rolled(self):
        r = _doc(
            ["壬午三月二十二日海關署談草", "十二日海關署談草", "是月十八日周玉山談草"],
            {"title_words": ["談草"]},
        )
        months = [(p["date"]["month"], p["date"]["day"]) for p in r["proposals"]]
        assert months == [(3, 22), (4, 12), (4, 18)]
        assert r["proposals"][1]["date"]["month_rolled"] is True
        assert r["proposals"][2]["date"]["month_inferred"] is True
        assert all(p["accepted"] for p in r["proposals"])

    def test_same_day_marker(self):
        r = _doc(["二月十一日與許涑文談草略", "是日軍械所與劉薌林談草"], {"title_words": ["談草"]})
        assert r["proposals"][1]["date"]["day"] == 11 and "same_day" in r["proposals"][1]["reasons"]

    def test_date_inside_body_is_not_accepted(self):
        """12-19 회차 본문 속 「三月廿一日李中堂以筆談問曰」 — 달이 거꾸로, 행은 본문 길이."""
        lines = [Line(1, 0, "十二月十九日北洋衙門談草")]
        lines += [Line(1, i, BODY) for i in range(1, 4)]
        lines.append(Line(1, 4, "三月廿一日李中堂以筆談問曰" + "本文本文本文本文"))  # 21자 본문 열
        lines += [Line(1, i, BODY) for i in range(5, 8)]
        r = propose_boundaries(lines, {"title_words": ["談草", "筆談"]})
        body_prop = next(p for p in r["proposals"] if p["title"].startswith("三月"))
        assert "date_jump" in body_prop["reasons"]
        assert body_prop["accepted"] is False
        assert len(r["spans"]) == 1  # 경계는 12-19 하나뿐

    def test_suppress_list_from_rules(self):
        r = _doc(
            ["十二月十九日北洋衙門談草", "三月廿一日李中堂以筆談問曰"],
            {"title_words": ["談草", "筆談"], "suppress": ["三月廿一日李中堂以筆談問曰"]},
        )
        sup = r["proposals"][1]
        assert sup["suppressed"] is True and sup["accepted"] is False
        assert r["stats"]["suppressed"] == 1


class TestSignals:
    def test_no_title_words_in_code(self):
        assert DEFAULT_RULES["title_words"] == [] and DEFAULT_RULES["suppress"] == []

    def test_title_word_and_place(self):
        r = _doc(["壬午正月初十日天津海關道署談草"], {"title_words": ["談草"]})
        p = r["proposals"][0]
        assert p["kind"] == "談草" and p["place"] == "天津海關道署"
        assert "title_word:談草" in p["reasons"]
        # 15자라 기본 max_title_chars(14)를 넘는다 — 형식 신호 없이 날짜+어휘로 승인
        assert "short_line" not in p["reasons"] and p["accepted"] is True
        r2 = _doc(["二十一日海關署談草"], {"title_words": ["談草"]})
        assert "short_line" in r2["proposals"][0]["reasons"]

    def test_date_only_short_line_is_enough(self):
        """표제 어휘가 없는 일기: 날짜 + 짧은 별행이면 승인."""
        r = _doc(["初三日晴", "初四日雨"], None)
        assert [p["accepted"] for p in r["proposals"]] == [True, True]

    def test_date_only_long_line_is_weak(self):
        """날짜로 시작하지만 본문만큼 긴 행은 승인 문턱 아래."""
        r = _doc(["初三日" + BODY[:18]], None)
        p = r["proposals"][0]
        assert "long_line" in p["reasons"] and p["accepted"] is False

    def test_indent_from_bbox(self):
        """세로쓰기: 표제 열의 위(y1)가 본문 열보다 한 글자 넘게 낮으면 내려쓰기."""
        lines = []
        for i in range(6):
            lines.append(
                Line(1, i, BODY, bbox=[100 * (7 - i), 120, 100 * (7 - i) + 40, 120 + 21 * 26])
            )
        lines.append(Line(1, 6, "十四日海關署口談節錄", bbox=[50, 175, 90, 175 + 10 * 26]))
        r = propose_boundaries(lines, {"title_words": ["口談"]})
        p = r["proposals"][0]
        assert "indent" in p["reasons"] and p["confidence"] >= 0.8

    def test_front_matter_span(self):
        lines = [
            Line(1, 0, "天津奉使緣起"),
            Line(1, 1, BODY),
            Line(1, 2, "辛巳十一月二十八日保定督署談草"),
            Line(1, 3, BODY),
        ]
        r = propose_boundaries(lines, {"title_words": ["談草"]})
        assert [s["kind"] for s in r["spans"]] == ["front", "談草"]
        assert r["spans"][0]["start"] == {"page": 1, "line_index": 0}
        assert r["spans"][1]["end"] == {"page": 1, "line_index": 3}

    def test_rules_normalized(self):
        r = normalize_rules({"title_words": [" 談草 ", ""], "max_title_chars": "12"})
        assert r["title_words"] == ["談草"] and r["max_title_chars"] == 12 and r["use_date"] is True


class TestSpanRefs:
    def test_cross_page_span_makes_one_ref_per_page(self):
        lines = [
            Line(1, 0, "十四日海關署口談節錄", char_start=0),
            Line(1, 1, BODY, char_start=11),
            Line(2, 0, BODY, char_start=0),
            Line(2, 1, BODY, char_start=22),
        ]
        page_texts = {1: "十四日海關署口談節錄\n" + BODY, 2: BODY + "\n" + BODY}
        span = {"start": {"page": 1, "line_index": 0}, "end": {"page": 2, "line_index": 1}}
        text, refs = span_to_text_and_refs(span, lines, page_texts, "d1", "v1")
        assert text.startswith("十四日") and text.count("\n") == 3
        assert [r["page"] for r in refs] == [1, 2]
        assert refs[0]["char_range"] == [0, len(page_texts[1])]
        assert refs[1]["char_range"] == [0, len(page_texts[2])]
        assert refs[0]["part_id"] == "v1" and refs[0]["layer"] == "L4"


# ── API ──────────────────────────────────────────────────────────────────


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
    """서고 + 문헌(PDF 3쪽) + L4 확정본 + 해석 저장소 + Work."""
    import fitz

    r = client.post("/api/library/quick-start")
    assert r.status_code == 200
    lib = r.json()["library_path"]
    pdf = tmp_path / "t.pdf"
    d = fitz.open()
    for _ in range(3):
        d.new_page(width=400, height=600)
    d.save(str(pdf))
    with open(pdf, "rb") as f:
        r = client.post(
            "/api/documents/create-from-files",
            data={"doc_id": "d1", "title": "담초"},
            files=[("files", ("t.pdf", f.read(), "application/pdf"))],
        )
    assert r.status_code == 200, r.text
    part_id = r.json()["parts"][0]["part_id"]
    from pathlib import Path

    pages = Path(lib) / "documents" / "d1" / "L4_text" / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    (pages / f"{part_id}_page_001.txt").write_text(
        "天津奉使緣起\n" + BODY + "\n辛巳十一月二十八日保定督署談草\n" + BODY, encoding="utf-8"
    )
    (pages / f"{part_id}_page_002.txt").write_text(
        BODY + "\n是月三十日替署談草\n" + BODY, encoding="utf-8"
    )
    (pages / f"{part_id}_page_003.txt").write_text(
        "十二月初一日替着遣飮時使通詞傳語口談\n" + BODY, encoding="utf-8"
    )
    r = client.post(
        "/api/interpretations",
        json={
            "interp_id": "i1",
            "source_document_id": "d1",
            "interpreter_type": "human",
            "interpreter_name": "t",
            "title": "t",
        },
    )
    assert r.status_code == 200, r.text
    r = client.post("/api/interpretations/i1/entities/work/auto-create", json={"document_id": "d1"})
    assert r.status_code == 200, r.text
    return lib, part_id, r.json()["work"]["id"] if "work" in r.json() else r.json()["id"]


def test_propose_and_apply(client, tmp_path):
    lib, part_id, work_id = _setup(client, tmp_path)
    # 규칙 저장 (문헌 설정)
    r = client.put(
        "/api/documents/d1/segmentation-rules", json={"rules": {"title_words": ["談草", "口談"]}}
    )
    assert r.status_code == 200 and r.json()["segmentation_rules"]["title_words"] == [
        "談草",
        "口談",
    ]
    from pathlib import Path

    manifest = json.loads(
        (Path(lib) / "documents" / "d1" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["segmentation_rules"]["title_words"] == ["談草", "口談"]

    r = client.post(
        "/api/interpretations/i1/segmentation/propose",
        json={"document_id": "d1", "part_id": part_id},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    titles = [p["title"] for p in data["proposals"] if p["accepted"]]
    assert titles == [
        "辛巳十一月二十八日保定督署談草",
        "是月三十日替署談草",
        "十二月初一日替着遣飮時使通詞傳語口談",
    ]
    assert data["proposals"][1]["date"]["month"] == 11  # 是月 → 물려받음
    assert data["spans"][0]["kind"] == "front" and len(data["spans"]) == 4
    assert data["pages"] == [1, 2, 3]
    # 제안은 아무것도 저장하지 않는다
    assert client.get("/api/interpretations/i1/contents?document_id=d1").json()["total_blocks"] == 0

    r = client.post(
        "/api/interpretations/i1/segmentation/apply",
        json={
            "document_id": "d1",
            "part_id": part_id,
            "work_id": work_id,
            "spans": [
                {k: v for k, v in s.items() if k in ("title", "kind", "start", "end")}
                for s in data["spans"]
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["created"]) == 4 and r.json()["errors"] == []

    tree = client.get("/api/interpretations/i1/contents?document_id=d1").json()
    blocks = tree["works"][0]["blocks"]
    assert [b["sequence_index"] for b in blocks] == [0, 1, 2, 3]
    # 두 쪽에 걸친 회차(1쪽 3행 → 2쪽 1행)는 쪽 배지가 둘
    assert [p["page"] for p in blocks[1]["pages"]] == [1, 2]
    assert blocks[1]["preview"].startswith("辛巳十一月二十八日")
    # 출처에 char_range가 있고 part_id가 채워진다
    from src.core.entity import list_entities

    tb = next(
        b
        for b in list_entities(Path(lib) / "interpretations" / "i1", "text_block")
        if b["sequence_index"] == 1
    )
    assert tb["source_refs"][0]["part_id"] == part_id and tb["source_refs"][0]["char_range"][0] > 0
    assert tb["metadata"]["title"] == "辛巳十一月二十八日保定督署談草"


def test_propose_without_l4_is_400(client, tmp_path):
    lib, part_id, _ = _setup(client, tmp_path)
    import shutil
    from pathlib import Path

    shutil.rmtree(Path(lib) / "documents" / "d1" / "L4_text" / "pages")
    r = client.post(
        "/api/interpretations/i1/segmentation/propose",
        json={"document_id": "d1", "part_id": part_id},
    )
    assert r.status_code == 400 and "L4" in r.json()["error"]


# ── 목차 신호 (D-089) ─────────────────────────────────────────────────────

from src.core.toc import (  # noqa: E402
    TocEntry,
    align_toc_to_body,
    detect_toc_pages,
    extract_toc_entries_llm,
    extract_toc_entries_rule,
    title_similarity,
    toc_page_score,
)

TOC_PAGE = [
    "雲養集目錄",
    "卷之一",
    "詩",
    "感懷 一",
    "次韻贈李參判 二",
    "登北漢 三",
    "卷之二",
    "疏",
    "辭職疏 一",
    "論時務疏 五",
]
BODY_P5 = ["雲養集卷之一", "詩", "感懷", BODY, "次韻贈李參判幷序", BODY, "登北漢山", BODY]
BODY_P6 = ["雲養集卷之二", "疏", "辭職疏 壬午", BODY, "論時務疏", BODY]


class TestTocDetection:
    def test_toc_page_scores_high_body_low(self):
        assert toc_page_score(TOC_PAGE) >= 0.9
        assert toc_page_score(BODY_P5) < 0.7

    def test_detect_first_run_only(self):
        pages = {1: ["雲養集", "重刊本"], 2: TOC_PAGE, 3: TOC_PAGE[:6], 5: BODY_P5, 6: BODY_P6}
        assert detect_toc_pages(pages) == [2, 3]

    def test_rule_extraction_levels_and_leaf_hint(self):
        entries = extract_toc_entries_rule({2: TOC_PAGE}, [2])
        titles = [(e.level, e.title, e.page_hint) for e in entries]
        assert titles[0] == (1, "卷之一", None)  # 卷之一의 수사는 葉 번호가 아니다
        assert (2, "感懷", "一") in titles and (2, "論時務疏", "五") in titles
        assert all(e.title != "雲養集目錄" for e in entries)


class TestTocAlignment:
    def test_similarity_head_and_containment(self):
        assert title_similarity("感懷", "感懷") == 1.0
        assert title_similarity("次韻贈李參判", "次韻贈李參判幷序") >= 0.95
        assert title_similarity("卷之一", "雲養集卷之一") >= 0.9
        assert title_similarity("感懷", BODY) < 0.6

    def test_order_preserving_alignment_with_decoy(self):
        entries = extract_toc_entries_rule({2: TOC_PAGE}, [2])
        # 본문 앞에 미끼 행(뒤 항목과 같은 제목)을 두어도 순서 때문에 앞 항목이 먼저 온다
        body = [Line(5, i, t) for i, t in enumerate(["論時務疏"] + BODY_P5)]
        body += [Line(6, i, t) for i, t in enumerate(BODY_P6)]
        matches, unmatched = align_toc_to_body(entries, body)
        got = {m.title: (m.page, m.line_index) for m in matches}
        assert got["論時務疏"] == (6, 4)  # 미끼(5쪽 0행)가 아니라 순서상 맞는 자리
        assert got["卷之一"] == (5, 1) and got["感懷"] == (5, 3)
        assert unmatched == []

    def test_unmatched_entries_reported(self):
        entries = [TocEntry("感懷"), TocEntry("없는글"), TocEntry("登北漢")]
        body = [Line(5, i, t) for i, t in enumerate(BODY_P5)]
        matches, unmatched = align_toc_to_body(entries, body)
        assert [m.title for m in matches] == ["感懷", "登北漢"] and unmatched == [1]


class _FakeRouter:
    def __init__(self, text):
        self._text = text
        self.calls = []

    async def call(self, prompt, **kwargs):
        self.calls.append(kwargs)

        class R:
            pass

        r = R()
        r.text, r.provider, r.model = self._text, "fake", "fake-1"
        return r


class TestTocLlm:
    def test_llm_json_used_and_json_forced(self):
        import asyncio

        router = _FakeRouter(
            '{"is_toc": true, "entries": [{"title": "感懷", "level": 2, "page_hint": "一"}, '
            '{"title": "卷之二", "level": 1}]}'
        )
        entries, meta = asyncio.run(extract_toc_entries_llm({2: TOC_PAGE}, [2], router))
        assert meta["method"] == "llm" and meta["provider"] == "fake"
        assert [(e.title, e.level, e.page_hint) for e in entries] == [
            ("感懷", 2, "一"),
            ("卷之二", 1, None),
        ]
        assert router.calls[0]["response_format"] == "json" and "think" not in router.calls[0]

    def test_llm_garbage_falls_back_to_rule(self):
        import asyncio

        entries, meta = asyncio.run(
            extract_toc_entries_llm({2: TOC_PAGE}, [2], _FakeRouter("응답이 이상합니다"))
        )
        assert meta["method"] == "rule" and meta["error"]
        assert any(e.title == "感懷" for e in entries)


class TestTocSignalInProposer:
    def test_toc_match_creates_boundary_without_date(self):
        lines = [Line(5, i, t) for i, t in enumerate(BODY_P5)]
        entries = extract_toc_entries_rule({2: TOC_PAGE}, [2])
        matches, _ = align_toc_to_body(entries, lines)
        r = propose_boundaries(lines, None, toc_matches=[m.to_dict() for m in matches])
        titles = [(p["title"], p["kind"], p["accepted"]) for p in r["proposals"]]
        assert ("卷之一", "volume", True) in titles and ("感懷", "", True) in titles
        assert all(any(x.startswith("toc:") for x in p["reasons"]) for p in r["proposals"])
        assert r["proposals"][0]["confidence"] >= 0.6


def test_toc_api_and_propose_with_toc(client, tmp_path):
    lib, part_id, work_id = _setup(client, tmp_path)
    from pathlib import Path

    pages = Path(lib) / "documents" / "d1" / "L4_text" / "pages"
    (pages / f"{part_id}_page_001.txt").write_text("\n".join(TOC_PAGE), encoding="utf-8")
    (pages / f"{part_id}_page_002.txt").write_text("\n".join(BODY_P5), encoding="utf-8")
    (pages / f"{part_id}_page_003.txt").write_text("\n".join(BODY_P6), encoding="utf-8")

    r = client.post(
        "/api/interpretations/i1/segmentation/toc", json={"document_id": "d1", "part_id": part_id}
    )
    assert r.status_code == 200, r.text
    assert r.json()["toc_pages"] == [1] and r.json()["method"] == "rule"
    assert [e["title"] for e in r.json()["entries"]][:3] == ["卷之一", "詩", "感懷"]

    body = {"document_id": "d1", "part_id": part_id}
    r = client.post("/api/interpretations/i1/segmentation/propose", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["toc"]["pages"] == [1] and data["pages"] == [2, 3]  # 목차 쪽은 본문 후보에서 빠진다
    # 卷之一·卷之二(포함 관계)까지 9항목 전부 대조
    assert len(data["toc"]["matches"]) == 9 and data["toc"]["unmatched"] == []
    accepted = [p["title"] for p in data["proposals"] if p["accepted"]]
    assert accepted[:3] == ["卷之一", "詩", "感懷"] and "論時務疏" in accepted
    assert all(ln["page"] != 1 for ln in data["lines"])


# ── 경계 색인 (D-090) ─────────────────────────────────────────────────────


def test_boundary_index_created_listed_shifted_exported(client, tmp_path):
    lib, part_id, work_id = _setup(client, tmp_path)
    rules = {"rules": {"title_words": ["談草", "口談"]}}
    client.put("/api/documents/d1/segmentation-rules", json=rules)
    body = {"document_id": "d1", "part_id": part_id}
    data = client.post("/api/interpretations/i1/segmentation/propose", json=body).json()
    keep = ("title", "kind", "start", "end")
    r = client.post(
        "/api/interpretations/i1/segmentation/apply",
        json={
            "document_id": "d1",
            "part_id": part_id,
            "work_id": work_id,
            "spans": [{k: v for k, v in s.items() if k in keep} for s in data["spans"]],
        },
    )
    assert r.status_code == 200, r.text
    created = r.json()["created"]
    assert all(c["boundary_id"] for c in created)

    # 목록: 순서대로, TextBlock과 서로 가리킨다
    url = f"/api/interpretations/i1/boundaries?document_id=d1&part_id={part_id}"
    lst = client.get(url).json()
    assert lst["total"] == 4 and [b["order"] for b in lst["boundaries"]] == [0, 1, 2, 3]
    b1 = lst["boundaries"][1]
    assert b1["title"] == "辛巳十一月二十八日保定督署談草" and b1["status"] == "approved"
    assert b1["start"] == {"page": 1, "line": 2} and b1["end"] == {"page": 2, "line": 0}
    assert b1["text_block_id"] == created[1]["id"] and b1["l4_commit"]
    assert b1["bbox"] is None  # 이 픽스처에는 L2가 없다 — 틀린 좌표를 만들지 않는다

    # 내용 트리에 boundary_id·anchor가 붙는다
    tree = client.get("/api/interpretations/i1/contents?document_id=d1").json()
    blk = tree["works"][0]["blocks"][1]
    assert blk["boundary_id"] == b1["id"] and blk["anchor"]["start"] == {"page": 1, "line": 2}

    # 시작을 한 행 뒤로: 이 경계는 1쪽 3행부터, 앞(front) 경계는 1쪽 2행까지 늘어난다
    r = client.put(f"/api/interpretations/i1/boundaries/{b1['id']}", json={"shift_start": 1})
    assert r.status_code == 200, r.text
    assert r.json()["boundary"]["start"] == {"page": 1, "line": 3}
    lst = client.get("/api/interpretations/i1/boundaries?document_id=d1").json()["boundaries"]
    assert lst[0]["end"] == {"page": 1, "line": 2}
    # 파생 TextBlock의 본문이 다시 이어졌다 — 표제 행이 앞 블록으로 넘어갔다
    from pathlib import Path

    from src.core.entity import get_entity

    interp_dir = Path(lib) / "interpretations" / "i1"
    tb1 = get_entity(interp_dir, "text_block", b1["text_block_id"])
    tb0 = get_entity(interp_dir, "text_block", lst[0]["text_block_id"])
    assert not tb1["original_text"].startswith("辛巳")
    assert tb0["original_text"].rstrip().endswith("辛巳十一月二十八日保定督署談草")
    assert tb1["source_refs"][0]["char_range"][0] > 0

    # CSV: article_index 관례의 열, BOM, 4행
    r = client.get(f"{url.replace('boundaries?', 'boundaries/export.csv?')}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    text = r.content.decode("utf-8-sig")
    rows = [ln for ln in text.splitlines() if ln.strip()]
    assert rows[0].startswith("기사id,문헌,권,순서,유형,층위,제목,시작쪽,시작행,끝쪽,끝행,상태")
    assert len(rows) == 5 and ",1,3,2,0,approved," in rows[2]


def test_boundary_bbox_from_l2_when_line_counts_match(tmp_path):
    """L2 행 수가 L4 행 수와 맞을 때만 앵커 bbox를 만든다."""
    import json

    from src.core.segmentation import anchor_bbox

    doc = tmp_path / "documents" / "d"
    (doc / "L4_text" / "pages").mkdir(parents=True)
    (doc / "L2_ocr").mkdir()
    manifest = {"document_id": "d", "parts": [{"part_id": "v1"}]}
    (doc / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (doc / "L4_text" / "pages" / "v1_page_001.txt").write_text("甲\n\n乙\n丙", encoding="utf-8")
    lines = [
        {"text": "甲", "bbox": [900, 100, 940, 500]},
        {"text": "乙", "bbox": [800, 100, 840, 500]},
        {"text": "丙", "bbox": [700, 100, 740, 500]},
    ]
    l2 = {
        "part_id": "v1",
        "page_number": 1,
        "image_width": 1000,
        "image_height": 1500,
        "ocr_results": [{"layout_block_id": "b", "lines": lines}],
    }
    (doc / "L2_ocr" / "v1_page_001.json").write_text(json.dumps(l2), encoding="utf-8")
    # L4 행 2(빈 행 다음 乙)는 L2의 두 번째 행
    a = anchor_bbox(doc, "v1", 1, 2)
    assert a["bbox"] == [800, 100, 840, 500] and a["image_width"] == 1000
    assert anchor_bbox(doc, "v1", 1, 1) is None  # 빈 행에는 앵커가 없다
