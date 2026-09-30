"""말로 작업 지시·강독 노트·장별 내보내기 시험 (D-131).

무엇을 고정하는가:
  - 작업 계획: 쪽 범위 문법, 틀린 칸은 버리고 **이유를 돌려준다**(조용히 바꿔치기하지 않는다),
    겹친 구간은 알린다, 회전은 manifest의 쪽 범위 회전(D-126)으로 저장된다
  - 말 → 계획: 모델이 모르는 엔진을 적으면 코드가 되돌려 unsupported에 적는다. 저장하지 않는다
  - 내보내기: 잡음 줄(손글씨 쪽 번호·접힌 자리 선)을 빼고 센다, 장 제목 글자로 쪽 안 자리를 찾는다
  - 강독 노트: 교정은 L4에 들어가되 **사람이 고친 L4는 덮지 않는다**, 위키는 접히는 국역 표를 쓴다
  - API: GET/PUT read-plan, from-words(가짜 모델), reading-notes, export zip
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.read_plan import (
    page_settings,
    parse_pages,
    plan_from_words,
    rotation_runs,
    validate_plan,
)
from src.core.reading_ingest import check_answer, locate
from src.export.reading_note import render_markdown, render_wiki
from src.export.text_export import build_chapters, is_noise_line, join_columns, render

PLAN = {
    "title": "강의교재",
    "guidance": "가타카나 문어문",
    "ranges": [
        {"pages": "1", "rotation": 90, "engine": "ndlocr", "writing": "vertical_rtl"},
        {"pages": "2", "skip": True, "note": "백지"},
        {"pages": "3-4", "rotation": 0, "engine": "ndlocr", "writing": "horizontal_ltr"},
    ],
    "chapters": [{"page": 3, "title": "壹. 民事慣習回答彙集", "level": 1}],
}


class FakeRouter:
    """LlmRouter 대역 — 정해 둔 JSON 답을 돌려준다."""

    def __init__(self, answer: dict):
        self.answer = answer
        self.prompts: list[str] = []

    async def call(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return SimpleNamespace(
            text=json.dumps(self.answer, ensure_ascii=False), provider="fake", model="m"
        )


# ── 계획 ─────────────────────────────────────────────────


class TestPlan:
    def test_parse_pages(self):
        assert parse_pages("1-3,7, 9-10") == [1, 2, 3, 7, 9, 10]
        assert parse_pages("5-", 7) == [5, 6, 7]

    @pytest.mark.parametrize("bad", ["0-3", "5-2", "3-99"])
    def test_parse_pages_rejects(self, bad):
        with pytest.raises(ValueError):
            parse_pages(bad, 10)

    def test_bad_items_are_dropped_with_reasons(self):
        """입력: 모르는 엔진·틀린 회전·범위 밖. 출력: 그 구간은 빠지고 problems에 이유가 남는다."""
        plan = {
            "ranges": [
                {"pages": "1-2", "rotation": 90, "engine": "ndlocr"},
                {"pages": "3", "rotation": 45, "engine": "ndlocr"},
                {"pages": "4", "rotation": 0, "engine": "magic"},
                {"pages": "9-12", "rotation": 0, "engine": "ndlocr"},
            ],
            "chapters": [{"page": 99, "title": "x"}],
        }
        clean, problems = validate_plan(plan, 10)
        assert [r["pages"] for r in clean["ranges"]] == ["1-2"]
        whys = " ".join(p["why"] for p in problems)
        assert "0·90·180·270" in whys and "magic" in whys and "벗어납니다" in whys
        assert clean["chapters"] == []

    def test_overlap_is_reported(self):
        plan = {
            "ranges": [{"pages": "1-3", "engine": "ndlocr"}, {"pages": "3-4", "engine": "ndlocr"}]
        }
        _clean, problems = validate_plan(plan, 5)
        assert any("겹칩니다" in p["why"] for p in problems)

    def test_settings_and_runs(self):
        clean, _ = validate_plan(PLAN, 4)
        s = page_settings(clean, 4)
        assert s[2] == {"skip": True}
        assert s[3]["writing"] == "horizontal_ltr"
        assert rotation_runs(s) == [(1, 1, 90), (3, 4, 0)]

    def test_words_unknown_engine_goes_to_unsupported(self):
        """모델이 없는 엔진을 적으면 코드가 되돌려 «옮기지 못한 말»로 보인다."""
        import asyncio

        answer = {
            "plan": {
                "title": "t",
                "ranges": [
                    {"pages": "1-2", "rotation": 90, "engine": "ndlocr"},
                    {"pages": "3", "rotation": 0, "engine": "super_ocr"},
                ],
                "chapters": [],
            },
            "unsupported": [{"said": "표는 따로", "why": "표를 나누는 칸이 없다"}],
        }
        router = FakeRouter(answer)
        plan, meta = asyncio.run(plan_from_words("1~2쪽은 누웠다", 5, ["ndlocr"], router))
        assert [r["pages"] for r in plan["ranges"]] == ["1-2"]
        saids = [u["said"] for u in meta["unsupported"]]
        assert "표는 따로" in saids and any("ranges[1]" in s for s in saids)
        assert "PDF로 5쪽" in router.prompts[0]

    def test_words_empty_is_error(self):
        import asyncio

        plan, meta = asyncio.run(plan_from_words("  ", 5, [], FakeRouter({})))
        assert plan is None and meta["error"]


# ── 내보내기 ──────────────────────────────────────────────


class TestExport:
    @pytest.mark.parametrize("line", ["1/1", "198", "1,0", "〇〇、〇〇〇〇、〇〇〇〇、〇〇"])
    def test_noise(self, line):
        assert is_noise_line(line)

    @pytest.mark.parametrize("line", ["四四", "○要旨", "本年六月勅令第三十九號ヲ以テ"])
    def test_not_noise(self, line):
        assert not is_noise_line(line)

    def test_join_columns(self):
        full = "一二三四五六七八九十" * 2
        paras = join_columns([full, full, "끝.", "○照會", full, "짧다", full, "○要旨" + full])
        # 짧은 열은 문단 끝(소제목 ○照會도 제 줄로 선다), ○로 시작하는 열은 가득 차도 새 문단
        assert paras == [full + full + "끝.", "○照會", full + "짧다", full, "○要旨" + full]

    def test_chapter_anchored_inside_spread(self):
        """입력: 한 쪽에 앞 장 끝 + 새 장 제목. 출력: 제목 줄부터 새 장이다."""
        pages = {1: "앞글\n1/1\n", 2: "앞 장 끝\n一臨時財産整理局事務要綱\n본문"}
        chapters, stats = build_chapters(
            pages, [{"page": 2, "title": "貳. 臨時財産整理局事務要綱", "level": 1}]
        )
        assert [c.title for c in chapters] == ["앞붙이", "貳. 臨時財産整理局事務要綱"]
        assert chapters[0].pages[-1] == (2, ["앞 장 끝"])
        assert stats == {"noise_lines": 1, "anchored": 1}

    def test_render_formats(self):
        chapters, _ = build_chapters({1: "가\n나"}, [{"page": 1, "title": "壹", "level": 1}])
        md = render("책", chapters, "md")
        wiki = render("책", chapters, "wiki")
        assert set(md) == {"01.md", "index.md", "all.md"}
        assert "## 壹" in md["01.md"] and '<a id="p1"></a>' in md["01.md"]
        assert "== 壹 ==" in wiki["01.wiki"] and "= 책 =" in wiki["index.wiki"]


# ── 강독 노트 ─────────────────────────────────────────────

NOTE = {
    "title": "노트",
    "chapter": "貳. 臨時財産整理局事務要綱",
    "intro": ["해제 문단."],
    "corrections": [{"page": 1, "text": "本年六月勅令"}],
    "sections": [
        {
            "heading": "一、證明方ノ件 (증명 방식의 건)",
            "level": 3,
            "page": 1,
            "meta": ["교재 42면"],
            "segments": [
                {
                    "label": "○①",
                    "text": "本年六月勅令第三十九號ヲ以テ",
                    "ko": "올해 6월 칙령 제39호로",
                    "terms": [
                        {"term": "以テ", "reading": "もって", "gloss": "~로써", "type": "Grammar"}
                    ],
                }
            ],
        }
    ],
    "points": ["候는 경어 표지이다."],
}


class TestNote:
    def test_answer_shape(self):
        """답 형식(저장 형식 아님)의 최소 조건 — 장 제목·항목·구획 원문."""
        assert check_answer(NOTE) == []
        bad = {"chapter": "x", "sections": [{"heading": "h", "segments": [{"ko": "원문 없음"}]}]}
        assert any("원문" in p for p in check_answer(bad))
        assert check_answer({"sections": []})

    def test_locate_ignores_column_breaks(self):
        """세로 열이 줄바꿈으로 끊긴 확정본에서도 구획 원문을 찾는다(끝 포함 인덱스)."""
        text = "○要旨\n本年六月勅令第三\n十九號ヲ以テ宮內府"
        a, b = locate(text, "本年六月勅令第三十九號ヲ以テ")
        assert text[a] == "本" and text[b] == "テ"
        assert locate(text, "없는 글") is None

    def test_locate_tolerates_variant_glyphs(self):
        """字體만 다른 글자(稅/税·說/説)가 섞여도 같은 구획을 찾는다. 엉뚱한 곳엔 안 붙인다."""
        text = "前文\n二結稅ヲ給スル場合ニハ土地ヲ折給\nスルコトナク說明ス\n後文"
        hit = locate(text, "二結税ヲ給スル場合ニハ土地ヲ折給スルコトナク説明ス")
        assert hit and text[hit[0]] == "二" and text[hit[1]] == "ス"
        assert locate(text, "全然関係ノナイ文章デアリマス") is None

    def test_wiki_matches_reading_note_shape(self):
        w = render_wiki(NOTE, author="작성자")
        assert w.startswith("= 노트 =") and ": 작성: [[작성자]]" in w
        assert "=== 一、證明方ノ件 (증명 방식의 건) ===" in w
        assert "mw-collapsible mw-collapsed" in w and "! 국역 (펼치기)" in w
        assert "* '''以テ'''(もって) — ~로써" in w
        assert "== 독해 요점 ==" in w and "# 候는 경어 표지이다." in w

    def test_markdown(self):
        m = render_markdown(NOTE)
        assert "<details><summary>국역</summary>" in m and "- **以テ**(もって) — ~로써" in m


# ── API ─────────────────────────────────────────────────


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
    """서고 + 4쪽 문헌."""
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
            data={"doc_id": "d1", "title": "교재"},
            files=[("files", ("t.pdf", f.read(), "application/pdf"))],
        )
    assert r.status_code == 200, r.text
    return lib, r.json()["parts"][0]["part_id"]


def test_apply_plan_saves_rotation_guidance_and_plan(client, tmp_path):
    lib, part = _setup(client, tmp_path)
    r = client.get(f"/api/documents/d1/read-plan?part_id={part}")
    assert r.status_code == 200 and r.json()["plan"] is None and r.json()["page_count"] == 4
    r = client.put("/api/documents/d1/read-plan", json={"plan": PLAN, "part_id": part})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["pages"] == [1, 3, 4] and data["skipped"] == [2]
    # 권의 회전(0)과 같은 3~4쪽은 범위에 남지 않는다(D-126 병합 규칙)
    assert data["rotation_ranges"] == [{"from": 1, "to": 1, "rotation": 90}]
    assert {(e["from"], e["to"], e["writing_direction"]) for e in data["engine_plan"]} == {
        (1, 1, "vertical_rtl"),
        (3, 4, "horizontal_ltr"),
    }
    doc = lib / "documents" / "d1"
    manifest = json.loads((doc / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ocr_guidance"] == "가타카나 문어문"
    assert (
        json.loads((doc / "read_plan" / f"{part}.json").read_text("utf-8"))["chapters"][0]["page"]
        == 3
    )
    assert (
        client.get(f"/api/documents/d1/read-plan?part_id={part}").json()["plan"]["title"]
        == "강의교재"
    )


def test_from_words_does_not_save(client, tmp_path, monkeypatch):
    lib, part = _setup(client, tmp_path)
    import app.routers.llm_ocr as mod

    fake = FakeRouter(
        {"plan": {"title": "t", "ranges": [{"pages": "1-4", "rotation": 90, "engine": "ndlocr"}]}}
    )
    monkeypatch.setattr(mod, "_get_llm_router", lambda: fake)
    doc = lib / "documents" / "d1"
    before = (doc / "manifest.json").read_bytes()
    r = client.post(
        "/api/documents/d1/read-plan/from-words", json={"said": "다 누웠다", "part_id": part}
    )
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["ranges"][0]["rotation"] == 90 and r.json()["provider"] == "fake"
    assert (doc / "manifest.json").read_bytes() == before
    assert not (doc / "read_plan").exists() and not (doc / "read_plan.json").exists()


def test_answer_goes_into_existing_layers_and_note_is_reassembled(client, tmp_path):
    """강독 결과 한 벌 → L4·경계·L6·L7. 새 저장 파일은 생기지 않고, 노트는 층에서 다시 조립된다."""
    lib, part = _setup(client, tmp_path)
    doc = lib / "documents" / "d1"
    pages = doc / "L4_text" / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    # 2쪽은 L2 없이 L4만 있다 — 사람이 넣은 것으로 본다(덮지 않는다)
    (pages / f"{part}_page_002.txt").write_text("사람이 고친 글", encoding="utf-8")
    r = client.put("/api/documents/d1/read-plan", json={"plan": PLAN, "part_id": part})
    assert r.status_code == 200, r.text
    answer = dict(
        NOTE,
        chapter="壹. 民事慣習回答彙集",
        corrections=[
            {
                "page": 3,
                "text": "民事慣習回答彙集\n一、證明方ノ件\n本年六月勅令第三\n十九號ヲ以テ",
                "hand_page": "7",
            },
            {"page": 2, "text": "LLM 교정"},
        ],
    )
    answer["sections"][0]["page"] = 3
    r = client.post("/api/documents/d1/reading-notes", json={"note": answer, "part_id": part})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["corrected"] == [3] and res["kept"] == [2]
    assert res["translations"] == 1 and res["annotations"] >= 3  # 어휘 1 + 문서 정보 + 해제·요점
    assert res["unplaced_sections"] == [] and res["unplaced_segments"] == []
    assert (pages / f"{part}_page_002.txt").read_text(encoding="utf-8") == "사람이 고친 글"
    # 새 저장 형식이 없다 — 강독 노트 파일·폴더를 만들지 않는다
    assert not (doc / "reading_notes").exists()
    interp = lib / "interpretations" / res["interp_id"]
    assert list((interp / "L6_translation" / "main_text").glob("*_translation.json"))
    assert list((interp / "L7_annotation" / "main_text").glob("*_annotation.json"))
    # 손글씨 쪽 번호가 계획의 이름표와 다르면(이 계획엔 규칙이 없다) 그 쪽만 낱쪽 이름표로 남는다
    assert res["relabeled_pages"] == [3]
    # 다시 들여도 이 들이기가 넣은 항목만 바뀐다(번역·경계 개수가 늘지 않는다)
    bfile = doc / "boundaries" / f"{part}.json"
    n_bounds = len(json.loads(bfile.read_text("utf-8"))["boundaries"])
    r = client.post("/api/documents/d1/reading-notes", json={"note": answer, "part_id": part})
    assert r.status_code == 200 and r.json()["translations"] == 1
    assert r.json()["boundaries_added"] == 0
    assert len(json.loads(bfile.read_text("utf-8"))["boundaries"]) == n_bounds
    tr = json.loads(
        next((interp / "L6_translation" / "main_text").glob("*.json")).read_text("utf-8")
    )
    assert len(tr["translations"]) == 1
    # 앱의 AI 번역은 그 단위의 확정 용어 풀이(L7)를 프롬프트에 싣는다(사용자 번역 지침, D-131)
    from app.routers.reading import AiTranslationRequest, _translation_input

    bid = tr["translations"][0]["source"]["block_id"]
    sent = "本年六月勅令第三十九號ヲ以テ"
    body = AiTranslationRequest(
        text=sent, interp_id=res["interp_id"], part_id=part, page=3, block_id=bid
    )
    composed = _translation_input(body)
    # 들이기 직후의 어휘는 검토 전 초안 — «확정»이 아니라 «참고»로 실린다(사용자 지침: 검토된 사전)
    assert composed.startswith("[검토 전 용어 풀이")
    assert "- 以テ(もって) [Grammar]: ~로써" in composed and composed.endswith(sent)
    # 사람이 검토(reviewed)로 올리면 «확정 용어 풀이»가 된다
    ann_file = next((interp / "L7_annotation" / "main_text").glob("*.json"))
    ann = json.loads(ann_file.read_text("utf-8"))
    term = next(a for b in ann["blocks"] for a in b["annotations"] if a.get("dictionary"))
    r = client.put(
        f"/api/interpretations/{res['interp_id']}/pages/3/annotations/{bid}/{term['id']}"
        f"?part_id={part}",
        json={"status": "reviewed"},
    )
    assert r.status_code == 200, r.text
    assert _translation_input(body).startswith("[확정 용어 풀이")
    assert _translation_input(AiTranslationRequest(text=sent)) == sent  # 자리가 없으면 원문만

    r = client.post(
        "/api/documents/d1/reading-notes", json={"note": {"chapter": "x"}, "part_id": part}
    )
    assert r.status_code == 400 and "모양" in r.json()["error"]

    r = client.get(f"/api/documents/d1/export/text?part_id={part}&format=wiki")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"index.wiki", "all.wiki"} <= names
    note = z.read(next(n for n in names if n.startswith("강독_"))).decode("utf-8")
    assert "! 국역 (펼치기)" in note and "올해 6월 칙령 제39호로" in note
    assert "* '''以テ'''(もって) — ~로써" in note and "== 해제 ==" in note
    assert "本年六月勅令第三十九號ヲ以テ" in note  # 원문은 지금 L4에서, 열 끊김 없이
    assert client.get(f"/api/documents/d1/export/text?part_id={part}&format=pdf").status_code == 400


# ── 리뷰 반영(Codex·문서 교차 확인 2026-09-30) ─────────────────


class TestPlanStrict:
    def test_no_silent_coercion(self):
        """skip "false"·회전 90.9·층위 0을 비슷한 값으로 바꾸지 않고 문제로 알린다."""
        plan = {
            "ranges": [
                {"pages": "1", "skip": "false"},
                {"pages": "2", "rotation": 90.9, "engine": "ndlocr"},
            ],
            "chapters": [{"page": 1, "title": "x", "level": 0}],
        }
        clean, problems = validate_plan(plan, 5)
        assert clean["ranges"] == [] and clean["chapters"] == []
        whys = " ".join(p["why"] for p in problems)
        assert "skip" in whys and "90.9" in whys and "층위" in whys

    def test_open_range_is_closed_and_bad_shapes_are_problems(self):
        plan = {
            "ranges": [{"pages": "4-", "rotation": 0, "engine": "ndlocr"}],
            "page_labels": [
                {"name": "교재", "offset": -1},
                {"pages": "+1", "name": "a", "label": "1"},
            ],
        }
        clean, problems = validate_plan(plan, 6)
        assert clean["ranges"][0]["pages"] == "4-6"  # 닫힌 범위로 저장 — 쪽 수 없이 읽어도 된다
        assert len(problems) == 2 and "page_labels" not in clean
        with pytest.raises(ValueError):
            validate_plan({"ranges": 1}, 5) if False else parse_pages("5-")  # 쪽 수 없이 열린 범위

    def test_later_invalid_offset_removes_label(self):
        from src.core.read_plan import page_label_map

        plan = {
            "page_labels": [
                {"pages": "1-3", "name": "교재", "label": "9"},
                {"pages": "1-3", "name": "교재", "offset": -2},
            ]
        }
        # 1·2쪽은 뒤 규칙으로 0 이하 → 앞 이름표도 지워진다. 3쪽은 1
        assert page_label_map(plan) == {3: [("교재", "1")]}


class TestLocateStrict:
    def test_head_tail_needs_similar_middle(self):
        text = "ABCDEFGHxxxxxxxxIJKLMNOP"
        assert locate(text, "ABCDEFGH12345678IJKLMNOP") is None

    def test_fuzzy_rejects_large_trim(self):
        text = "前前前前前前本年六月勅令第三十九號ヲ以テ後"
        # 앞 여섯 글자가 전혀 다른 원문 — 가운데만 물어 전체 구획으로 삼지 않는다
        assert locate(text, "明治十年本年六月勅令第三十九號ヲ以テ") is None


def test_answer_shape_checked_before_any_write(client, tmp_path):
    """terms가 글이 아닌 답은 L4를 쓰기 **전에** 거절된다(반쯤 들어간 상태를 남기지 않는다)."""
    lib, part = _setup(client, tmp_path)
    doc = lib / "documents" / "d1"
    bad = dict(NOTE, corrections=[{"page": 1, "text": "새 글"}])
    bad["sections"] = [dict(NOTE["sections"][0], segments=[{"text": "本年", "terms": [1]}])]
    r = client.post("/api/documents/d1/reading-notes", json={"note": bad, "part_id": part})
    assert r.status_code == 400
    assert not (doc / "L4_text" / "pages" / f"{part}_page_001.txt").exists()
    r = client.post(
        "/api/documents/d1/reading-notes",
        json={"note": NOTE, "part_id": part, "interp_id": "../escape"},
    )
    assert r.status_code == 400 and "규칙" in r.json()["error"]


def test_human_work_survives_reimport(client, tmp_path):
    """들이기 뒤 사람이 고친 L4(커밋 안 됨)·번역은 다시 들여도 그대로다."""
    lib, part = _setup(client, tmp_path)
    doc = lib / "documents" / "d1"
    assert (
        client.put("/api/documents/d1/read-plan", json={"plan": PLAN, "part_id": part}).status_code
        == 200
    )
    answer = dict(
        NOTE,
        chapter="壹. 民事慣習回答彙集",
        corrections=[{"page": 3, "text": "民事慣習回答彙集\n本年六月勅令第三十九號ヲ以テ"}],
    )
    answer["sections"] = [dict(NOTE["sections"][0], page=3)]
    r = client.post("/api/documents/d1/reading-notes", json={"note": answer, "part_id": part})
    assert r.status_code == 200, r.text
    res = r.json()
    page_file = doc / "L4_text" / "pages" / f"{part}_page_003.txt"
    # ① 편집기 저장(커밋하지 않음)으로 사람이 L4를 고친다
    page_file.write_text(
        "民事慣習回答彙集\n本年六月勅令第三十九號ヲ以テ 사람 교정", encoding="utf-8"
    )
    # ② 번역 탭에서 사람이 국역을 고친다
    interp = lib / "interpretations" / res["interp_id"]
    tr_file = next((interp / "L6_translation" / "main_text").glob("*.json"))
    tr = json.loads(tr_file.read_text("utf-8"))["translations"][0]
    r = client.put(
        f"/api/interpretations/{res['interp_id']}/pages/3/translation/{tr['id']}?part_id={part}",
        json={"translation": "사람이 고친 국역"},
    )
    assert r.status_code == 200, r.text
    # 다시 들인다
    r = client.post("/api/documents/d1/reading-notes", json={"note": answer, "part_id": part})
    assert r.status_code == 200, r.text
    assert r.json()["kept"] == [3]
    assert "사람 교정" in page_file.read_text(encoding="utf-8")
    texts = [t["translation"] for t in json.loads(tr_file.read_text("utf-8"))["translations"]]
    assert "사람이 고친 국역" in texts


def test_note_filenames_keep_chapters_apart():
    from src.export.reading_note import note_filename

    assert note_filename(1, "A-B", "wiki") != note_filename(2, "A B", "wiki")


# ── 노트 틀(D-131 보완, 2026-09-30) — 모양은 틀이, 내용은 층이 ─────────────────

TPL = (
    "# {{ note.title }}\n"
    "{% for s in note.sections %}## {{ s.heading }} (PDF {{ s.page }})\n"
    "{% for g in s.segments %}{{ loop.index }}. {{ g.text }}\n   → {{ g.ko }}\n"
    "{% for t in g.terms %}   - {{ t.term }}({{ t.reading }}): {{ t.gloss }}\n{% endfor %}"
    "{% endfor %}{% endfor %}"
)


class TestNoteTemplate:
    def test_fields_match_sample(self):
        """틀 도움말(FIELDS)의 이름이 실제 노트 보기에 있다 — 없는 이름을 모델에 가르치지 않게."""
        import re as _re

        from src.export.note_template import FIELDS, SAMPLE_NOTE

        seg = SAMPLE_NOTE["sections"][0]["segments"][0]
        scopes = {
            "note": SAMPLE_NOTE,
            "s": SAMPLE_NOTE["sections"][0],
            "g": seg,
            "t": seg["terms"][0],
        }
        for scope, key in _re.findall(r"\b(note|s|g|t)\.(\w+)", FIELDS):
            assert key in scopes[scope], f"{scope}.{key}"

    def test_render_and_sandbox(self):
        from src.export.note_template import SAMPLE_NOTE, check_template, render_with_template

        out = render_with_template(SAMPLE_NOTE, TPL)
        assert "## 一、證明方ノ件 (증명 방식의 건) (PDF 46)" in out
        assert "1. 本年六月勅令第三十九號ヲ以テ\n   → 올해 6월 칙령 제39호로써" in out
        assert "   - 以テ(もって): ~로써" in out
        assert check_template(TPL) == []
        # 틀은 사용자가 준 글이다 — 파이썬 내부로 나가는 길은 막힌다
        with pytest.raises(ValueError):
            render_with_template(SAMPLE_NOTE, "{{ ''.__class__.__mro__[1].__subclasses__() }}")
        with pytest.raises(ValueError):
            render_with_template(SAMPLE_NOTE, "{% for s in note.sections %}")  # 짝 없는 for
        # 예시 글을 그대로 베낀 «틀»은 층의 내용을 쓰지 않는다 — 걸러 알린다
        assert check_template("= 제목 =\n원문 그대로 베낌\n")

    def test_template_from_example_strips_fence_and_previews(self):
        import asyncio

        from src.export.note_template import template_from_example

        class TextRouter:
            async def call(self, prompt, **kwargs):
                self.prompt = prompt
                return SimpleNamespace(text="```jinja\n" + TPL + "```", provider="fake", model="m")

        router = TextRouter()
        res = asyncio.run(template_from_example("= 예시 =\n○① 원문\n국역", router))
        assert res["template"].startswith("# {{ note.title }}") and "```" not in res["template"]
        assert res["problems"] == [] and "本年六月勅令" in res["preview"]
        assert "g.ko" in router.prompt  # 쓸 수 있는 이름을 모델에 준다
        assert asyncio.run(template_from_example("  ", router))["error"]


def test_export_notes_with_template(client, tmp_path, monkeypatch):
    """예시 → 틀(저장하지 않음) → 그 틀로 zip. 내용은 층에서 온다."""
    lib, part = _setup(client, tmp_path)
    doc = lib / "documents" / "d1"
    (doc / "L4_text" / "pages").mkdir(parents=True, exist_ok=True)
    r = client.put("/api/documents/d1/read-plan", json={"plan": PLAN, "part_id": part})
    assert r.status_code == 200, r.text
    answer = dict(
        NOTE,
        chapter="壹. 民事慣習回答彙集",
        corrections=[
            {"page": 3, "text": "民事慣習回答彙集\n一、證明方ノ件\n本年六月勅令第三\n十九號ヲ以テ"}
        ],
    )
    answer["sections"][0]["page"] = 3
    r = client.post("/api/documents/d1/reading-notes", json={"note": answer, "part_id": part})
    assert r.status_code == 200, r.text

    # 틀 도움말의 본보기(SAMPLE_NOTE)는 실제로 조립되는 보기와 같은 칸을 가진다
    from export.note_template import SAMPLE_NOTE
    from export.reading_note import assemble_notes

    (real,) = assemble_notes(lib, "d1", part, "d1_reading")
    assert set(real) >= set(SAMPLE_NOTE) - {"notes", "bibliography", "intro", "points"}
    assert set(real["sections"][0]) == set(SAMPLE_NOTE["sections"][0])
    assert set(real["sections"][0]["segments"][0]) == set(SAMPLE_NOTE["sections"][0]["segments"][0])

    import app.routers.llm_ocr as mod

    class TextRouter:
        async def call(self, prompt, **kwargs):
            return SimpleNamespace(text=TPL, provider="fake", model="m")

    monkeypatch.setattr(mod, "_get_llm_router", lambda: TextRouter())
    before = sorted(p.name for p in doc.iterdir())
    r = client.post("/api/documents/d1/note-template/from-example", json={"example": "= 예시 ="})
    assert r.status_code == 200, r.text
    tpl = r.json()["template"]
    assert sorted(p.name for p in doc.iterdir()) == before  # 틀은 저장하지 않는다

    r = client.post(
        "/api/documents/d1/export/notes", json={"template": tpl, "part_id": part, "ext": "md"}
    )
    assert r.status_code == 200, r.text
    z = zipfile.ZipFile(io.BytesIO(r.content))
    (name,) = z.namelist()
    assert name.startswith("강독_01_") and name.endswith(".md")
    body = z.read(name).decode("utf-8")
    assert "   → 올해 6월 칙령 제39호로" in body and "本年六月勅令第三十九號ヲ以テ" in body
    bad = client.post(
        "/api/documents/d1/export/notes", json={"template": "{% for %}", "part_id": part}
    )
    assert bad.status_code == 400 and "틀" in bad.json()["error"]
    assert client.post(
        "/api/documents/d1/export/notes", json={"template": tpl, "part_id": part, "ext": "../x"}
    ).status_code == 400
