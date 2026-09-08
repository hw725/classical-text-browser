"""규칙 도출 테스트 (D-116).

무엇을 고정하는가:
  - ○+날짜가 되풀이되는 일기에서는 mark가, 「談草」로 끝나는 짧은 행이 되풀이되면
    title_word가 권고된다
  - 쪽마다 한 번 같은 자리에 오는 것(판심·엽수)은 신호에서 빠지고 furniture로 간다
  - 도출 결과 → segmentation_rules 변환(rules_from_signals)과 «규칙이 비어 있는가» 판정
  - propose_boundaries가 signals 스위치·head_words·furniture를 따른다
  - API: /segmentation/signals는 저장하지 않고, 규칙이 빈 문헌의 /segmentation/auto는
    먼저 도출해 저장한다
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core import page_format
from src.core import rule_induction as induction
from src.core.rule_induction import (
    extract_start_patterns_llm,
    induce_signals,
    is_symbol_char,
    rules_are_empty,
    rules_from_signals,
    sample_size,
    sample_start_lines,
    toc_signal,
    verify_pattern,
)
from src.core.segmentation import Line, normalize_rules, propose_boundaries
from tests.test_segmentation import BODY, _FakeRouter, _setup, client  # noqa: F401 — fixture 재사용

_COL = "本文本文本文本文本文本文本文本文本文本文"  # 20자 — 열 용량
_DAYS = [
    "初一日",
    "初二日",
    "初三日",
    "初四日",
    "初五日",
    "初六日",
    "初七日",
    "初八日",
    "初九日",
    "初十日",
    "十一日",
    "十二日",
    "十三日",
    "十四日",
    "十五日",
    "十六日",
    "十七日",
    "十八日",
    "十九日",
    "二十日",
]


def _pages(rows_per_page: list[list[str]]) -> list[Line]:
    out = []
    for p, rows in enumerate(rows_per_page, start=1):
        out += [Line(p, i, t) for i, t in enumerate(rows)]
    return out


def _diary_pages(n_pages=6, per_page=8, furniture="書"):
    """○+날짜가 두 행마다 오는 일기. 쪽 끝에는 판심 글자 하나."""
    pages, k = [], 0
    for _ in range(n_pages):
        rows = []
        for i in range(per_page - 1):
            if i % 2 == 0:
                rows.append(f"{_COL[:8]}○{_DAYS[k % 20]}晴{_COL[:6]}")
                k += 1
            else:
                rows.append(_COL)
        rows.append(furniture)
        pages.append(rows)
    return _pages(pages)


class TestInduce:
    def test_furniture_uses_nonempty_page_position_without_changing_source_indices(self):
        """입력: 빈 행 수가 다른 L4·L2 자리. 출력: 판심 제외. 목적: 층 혼합을 견딘다."""
        pages = []
        for blanks in (1, 2, 3, 4, 0, 0):
            pages.append([_COL, _COL] + [""] * blanks + ["刊記", _COL])
        lines = _pages(pages)
        indices = [(ln.page, ln.line_index) for ln in lines]
        result = induce_signals(lines)
        assert "刊記" in result["furniture"]
        assert [(ln.page, ln.line_index) for ln in lines] == indices

    def test_mark_date_diary_is_recognised(self):
        r = induce_signals(_diary_pages())
        # 층계(D-117): 눈에 띄는 기호 ○가 2단에서 규약으로 결정되고,
        # 날짜 사슬이 또렷한 mark도 함께 켜진다
        assert r["stage"]["level"] == 2 and "sym:○" in r["stage"]["by"]
        rows = {s["id"]: s for s in r["signals"]}
        assert rows["sym:○"]["recommended"] is True
        mark = rows["mark"]
        assert mark["recommended"] is True
        assert mark["count"] >= 20 and mark["chain"] is not None and mark["chain"] >= 0.9
        # 쪽마다 한 번 같은 자리의 「書」는 글의 규약이 아니다
        assert "書" in r["furniture"]
        assert all(s["id"] != "head:書" for s in r["signals"])

    def test_title_word_family_from_short_line_tails(self):
        pages = []
        places = "天津保定海關署周玉山李中堂軍械所"
        for p in range(5):
            pages.append(
                [
                    f"{_DAYS[p]}海關署談草",
                    _COL,
                    _COL,
                    f"{places[p * 2 : p * 2 + 3]}談草",
                    _COL,
                    _COL,
                ]
            )
        r = induce_signals(_pages(pages))
        ids = {s["id"]: s for s in r["signals"]}
        assert ids["tail:談草"]["recommended"] is True
        assert ids["tail:談草"]["count"] == 10 and ids["tail:談草"]["value"] == "談草"
        rules = rules_from_signals(r)
        assert rules["title_words"] == ["談草"] and rules["origin"] == "induced"

    def test_page_furniture_family_is_dropped(self):
        # 「京城…」이 쪽마다 첫 행에 한 번 — 인쇄소 도장. head_word:京이 신호가 되면 안 된다
        pages = [[f"京城鍾路{p}", _COL, f"{_DAYS[p]}談草", _COL, _COL, _COL] for p in range(8)]
        r = induce_signals(_pages(pages))
        assert any(d["id"].startswith("head:京") for d in r["dropped"])
        assert all(not s["id"].startswith("head:京") for s in r["signals"])

    def test_head_word_needs_short_lines(self):
        # 「天」이 본문 긴 행 첫머리에만 편중되면 표제 규약이 아니다 — 권고하지 않는다
        pages = [
            ["天" + _COL[1:], _COL, f"{_DAYS[p]}談草", "天" + _COL[1:], _COL, _COL]
            for p in range(8)
        ]
        r = induce_signals(_pages(pages))
        tian = [s for s in r["signals"] if s["id"].startswith("head:天")]
        assert tian and tian[0]["recommended"] is False

    def test_unknown_glyph_is_never_a_word(self):
        pages = [[f"{_DAYS[p]}□□", _COL, _COL, "□談", _COL, _COL] for p in range(8)]
        r = induce_signals(_pages(pages))
        assert r["signals"], "판식 신호는 세어져야 한다 — 빈 목록이면 아래 단언이 공허하다"
        assert all("□" not in s["id"] for s in r["signals"])

    def test_wrapped_date_is_counted_like_the_proposer_sees_it(self):
        # 「…○三十|日雨…」 — 제안기는 date_wrap 후보를 만든다. 도출기도 같은 자리를 mark로 세야 한다
        pages = []
        for p in range(6):
            pages.append(
                [
                    _COL,
                    f"{_COL[:16]}○二十",
                    f"日雨{_COL[:18]}",
                    _COL,
                    f"{_COL[:8]}○{_DAYS[p]}晴{_COL[:6]}",
                    _COL,
                ]
            )
        r = induce_signals(_pages(pages))
        mark = [s for s in r["signals"] if s["id"] == "mark"]
        assert mark and mark[0]["count"] == 12

    def test_too_few_lines(self):
        r = induce_signals(_pages([["○初一日", "本"]]))
        assert r["signals"] == [] and r["lines"] == 2


class TestRulesFromSignals:
    def test_unchecked_signal_is_off_and_missing_aux_stays_on(self):
        r = induce_signals(_diary_pages())
        # 사람이 mark를 뺐다 — 날짜는 그대로 켜 둔다
        chosen = [s["id"] for s in r["signals"] if s["recommended"] and s["id"] != "mark"]
        rules = rules_from_signals(r, None, chosen)
        assert rules["signals"]["mark"] is False
        # bbox가 없어 목록에 없던 내려쓰기는 끄지 않는다(나중에 L2가 생기면 살아난다)
        assert rules["signals"]["indent"] is True

    def test_rules_are_empty(self):
        assert (
            rules_are_empty(None) and rules_are_empty({}) and rules_are_empty({"suppress": ["x"]})
        )
        assert not rules_are_empty({"title_words": ["談草"]})
        assert not rules_are_empty({"origin": "manual"})
        assert not rules_are_empty(normalize_rules({"signals": {"mark": False}}))


class TestProposerHonoursRules:
    def test_mark_switch_off_removes_the_mark_family(self):
        # mark는 «가족» 스위치다 —
        # 끄면 행 중간 ○+날짜 후보가 «날짜»라는 다른 이름으로 살아남지 않는다
        lines = _diary_pages(n_pages=2, furniture=_COL)
        on = propose_boundaries(lines, None)
        off = propose_boundaries(lines, {"signals": {"mark": False}})
        assert any("mark" in p["reasons"] for p in on["proposals"])
        assert off["stats"]["proposals"] == 0
        # 행 첫머리에 ○ 없이 온 날짜는 date 가족 — mark를 꺼도 남는다
        plain = _pages([[_COL, "初三日晴" + _COL[:10], _COL, _COL]])
        r = propose_boundaries(plain, {"signals": {"mark": False}})
        assert r["stats"]["proposals"] == 1 and "mark" not in r["proposals"][0]["reasons"]

    def test_date_and_mark_off_means_no_date_candidates(self):
        lines = _diary_pages(n_pages=2, furniture=_COL)
        r = propose_boundaries(lines, {"signals": {"mark": False, "date": False}})
        assert r["stats"]["proposals"] == 0

    def test_head_word_from_rules(self):
        lines = _pages([[_COL, _COL, "有詩", _COL, _COL, _COL, "有詩", _COL]])
        none = propose_boundaries(lines, None)
        assert none["stats"]["proposals"] == 0
        r = propose_boundaries(lines, {"head_words": ["有"]})
        acc = [p for p in r["proposals"] if p["accepted"]]
        assert len(acc) == 2 and "head_word:有" in acc[0]["reasons"]
        # 긴 본문 행이 有로 시작하면 어휘 점수만으로는 문턱을 못 넘는다
        r2 = propose_boundaries(
            _pages([[_COL, "有" + _COL[1:], _COL, _COL]]), {"head_words": ["有"]}
        )
        assert r2["stats"]["accepted"] == 0

    def test_furniture_text_is_not_a_boundary(self):
        lines = _pages([["天津談草", _COL, "初一日談草", _COL, _COL]])
        r = propose_boundaries(lines, {"title_words": ["談草"], "furniture": ["天津談草"]})
        by_title = {p["title"]: p for p in r["proposals"]}
        assert by_title["天津談草"]["accepted"] is False
        assert "furniture" in by_title["天津談草"]["reasons"]
        assert by_title["初一日談草"]["accepted"] is True

    def test_normalize_keeps_old_coarse_switches(self):
        rules = normalize_rules({"use_layout": False})
        assert rules["signals"]["short_line"] is False and rules["signals"].get("date", True)


def test_signals_api_counts_without_saving(client, tmp_path):  # noqa: F811
    lib, part_id = _setup(client, tmp_path)
    r = client.post("/api/documents/d1/segmentation/signals", json={"part_id": part_id})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["source"]["l4_pages"] == 3 and d["saved_rules"] is None
    assert (
        isinstance(d["signals"], list) and "stage" in d
    )  # 세 쪽 표본은 넷 미만이라 날짜 가족이 없다
    assert d["recommended_rules"]["origin"] == "induced"
    manifest = json.loads(
        (Path(lib) / "documents" / "d1" / "manifest.json").read_text(encoding="utf-8")
    )
    assert not manifest.get("segmentation_rules")


def test_auto_tree_saves_induced_rules_when_a_primary_signal_is_found(client, tmp_path):  # noqa: F811
    """주 신호가 권고될 만큼 되풀이되는 문헌: 자동 트리가 규칙을 찾아 manifest에 저장한다."""
    lib, part_id = _setup(client, tmp_path)
    pages = Path(lib) / "documents" / "d1" / "L4_text" / "pages"
    rows = []
    for k in range(12):
        rows.append(f"{_COL[:8]}○{_DAYS[k]}晴{_COL[:6]}")
        rows.append(_COL)
    for i in range(1, 4):
        (pages / f"{part_id}_page_{i:03d}.txt").write_text(
            "\n".join(rows[(i - 1) * 8 : i * 8]), encoding="utf-8"
        )
    r = client.post("/api/documents/d1/segmentation/auto", json={"part_id": part_id})
    assert r.status_code == 200, r.text
    d = r.json()
    assert "mark" in (d["induced"] or []) and d["rules_origin"] == "induced"
    manifest = json.loads(
        (Path(lib) / "documents" / "d1" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["segmentation_rules"]["origin"] == "induced"
    assert manifest["segmentation_rules"]["signals"]["mark"] is True
    # 저장된 뒤에는 다시 세지 않는다
    r2 = client.post("/api/documents/d1/segmentation/auto", json={"part_id": part_id})
    assert r2.json()["induced"] is None and r2.json()["rules_origin"] == "induced"


def test_auto_tree_uses_defaults_without_saving_when_nothing_repeats(client, tmp_path):  # noqa: F811
    """되풀이되는 표지가 없는 작은 표본: 기본 신호로 세우되 규칙은 저장하지 않는다."""
    lib, part_id = _setup(client, tmp_path)
    r = client.post("/api/documents/d1/segmentation/auto", json={"part_id": part_id})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["induced"] is not None and d["rules_origin"] == "induced"
    manifest = json.loads(
        (Path(lib) / "documents" / "d1" / "manifest.json").read_text(encoding="utf-8")
    )
    # 세 쪽짜리에서는 권고할 만큼 되풀이되는 것이 없다 — 기본값으로 세우되 저장하지 않는다
    assert not manifest.get("segmentation_rules")
    assert d["applied"] >= 1
    # 사람이 규칙을 저장해 두면 다시 세지 않는다
    client.put("/api/documents/d1/segmentation-rules", json={"rules": {"title_words": ["談草"]}})
    r2 = client.post("/api/documents/d1/segmentation/auto", json={"part_id": part_id})
    assert r2.json()["induced"] is None and r2.json()["rules_origin"] == ""


def test_put_rules_with_new_fields_passes_schema(client, tmp_path):  # noqa: F811
    _setup(client, tmp_path)
    rules = {
        "signals": {"mark": False},
        "head_words": ["有"],
        "furniture": ["書"],
        "toc_llm": True,
        "origin": "manual",
    }
    r = client.put("/api/documents/d1/segmentation-rules", json={"rules": rules})
    assert r.status_code == 200, r.text
    saved = r.json()["segmentation_rules"]
    assert saved["signals"] == {"mark": False} and saved["toc_llm"] is True
    # 모르는 스위치 이름은 normalize_rules가 걷어 내고 저장은 된다 —
    # 오타가 «꺼짐»으로 저장되지 않는다
    r = client.put(
        "/api/documents/d1/segmentation-rules", json={"rules": {"signals": {"marc": False}}}
    )
    assert r.status_code == 200
    assert r.json()["segmentation_rules"]["signals"] == {}


def test_auto_tree_skips_toc_when_switched_off(client, tmp_path):  # noqa: F811
    """편성 탭 목차 줄을 끄면 /auto도 목차를 찾지 않는다 (Codex 지적 2026-09-07)."""
    lib, part_id = _setup(client, tmp_path)
    r = client.post(
        "/api/documents/d1/segmentation/auto",
        json={"part_id": part_id, "use_toc": False, "toc_pages": [1]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["toc_pages"] == []


# ── 층계 (D-117) ─────────────────────────────────────────────────────────


class TestCascade:
    def test_toc_pages_are_not_counted_and_toc_decides(self):
        """목차가 본문과 대조되면 1단에서 멈추고, 목차 쪽의 짧은 행은 규약으로 배우지 않는다."""
        titles = [f"第{_DAYS[i]}篇" for i in range(8)]
        toc_page = ["目錄"] + [f"{t} {i + 1}" for i, t in enumerate(titles)]
        body_pages = [[titles[i], _COL, _COL, _COL] for i in range(8)]
        lines = _pages([toc_page] + body_pages)
        toc = toc_signal(lines)
        assert toc and toc["pages"] == [1] and toc["decisive"], toc
        r = induce_signals(lines, None, toc=toc)
        assert r["stage"]["level"] == 1 and r["stage"]["by"] == ["toc"]
        # 목차 쪽의 「第…篇」 행은 세지 않았다 — 본문에서만 8회
        first = [s for s in r["signals"] if s["id"].startswith("head:第")]
        assert not first or first[0]["count"] == 8
        # 텍스트 신호는 권고하지 않는다(1단에서 멈춤) — 보조만 켠다
        assert all(not s["recommended"] for s in r["signals"] if s["group"] != "aux")
        assert r["stage"]["summary"].startswith("목차 ")

    def test_symbol_family_decides_stage_two(self):
        # 「●」가 두 행마다 한 번 — 날짜가 없어도 시각 신호(2단)가 규약이다
        pages = [
            [f"{_COL[:9]}●{_COL[:10]}" if i % 2 == 0 else _COL for i in range(8)] for _ in range(5)
        ]
        r = induce_signals(_pages(pages))
        assert r["stage"]["level"] == 2
        rules = rules_from_signals(r)
        assert rules["symbols"] == ["●"] and rules["indent_alone"] is False
        assert "sym:●" in r["stage"]["by"]

    def test_punctuation_is_not_a_symbol(self):
        assert is_symbol_char("●") and is_symbol_char("○") and is_symbol_char("△")
        assert not is_symbol_char("、") and not is_symbol_char("。") and not is_symbol_char("「")
        assert not is_symbol_char("□") and not is_symbol_char("本") and not is_symbol_char("1")

    def test_indent_runs_are_not_a_boundary_convention(self):
        # 내려쓴 행이 줄지어 오면(협주·시 본문) 덩어리다 — 내려쓰기 단독은 규약이 아니다
        rows = []
        for i in range(24):
            # 여덟 행마다 셋이 붙어서 내려쓴다 —
            # 절반이 내려쓰면 «본문 위치»의 중앙값이 흔들려 시험이 안 된다
            indented = (i % 8) in (2, 3, 4)
            top = 40 if indented else 10
            rows.append(Line(1, i, _COL, bbox=[10, top, 30, top + 400]))
        r = induce_signals(rows)
        ind = [s for s in r["signals"] if s["id"] == "indent_alone"]
        assert ind and ind[0]["adjacent"] > 0.5 and not ind[0]["recommended"]
        assert r["stage"]["level"] != 2 or "indent_alone" not in r["stage"]["by"]

    def test_weak_toc_falls_through_and_says_so(self):
        # 목차 쪽은 잡혔지만 본문과 거의 대조되지 않는다 — 3단으로 내려가되 요약에 «약함»을 적는다
        toc_page = ["目錄"] + [f"甲{i}篇 {i + 1}" for i in range(8)]
        body = [[f"{_DAYS[i]}談草", _COL, _COL, _COL] for i in range(8)]
        lines = _pages([toc_page] + body)
        toc = toc_signal(lines)
        if toc is None:  # 판별 규칙이 이 합성 목차를 못 잡을 수도 있다 — 그러면 시험 대상이 아니다
            return
        assert not toc["decisive"]
        r = induce_signals(lines, None, toc=toc)
        assert r["stage"]["level"] == 3 and "약함" in r["stage"]["summary"]


class TestProposerVisualRules:
    def test_symbol_alone_makes_candidates(self):
        lines = _pages([[_COL, f"{_COL[:9]}●{_COL[:10]}", _COL, f"●{_COL[:12]}", _COL]])
        none = propose_boundaries(lines, None)
        assert none["stats"]["proposals"] == 0
        r = propose_boundaries(lines, {"symbols": ["●"]})
        acc = [p for p in r["proposals"] if p["accepted"]]
        assert len(acc) == 2
        assert all("symbol:●" in p["reasons"] for p in acc)
        mid = next(p for p in acc if p["char_offset"] > 0)
        assert mid["char_offset"] == 9 and not mid["title"].startswith("●")

    def test_symbol_with_date_keeps_mark_reason(self):
        lines = _diary_pages(n_pages=2, furniture=_COL)
        r = propose_boundaries(lines, {"symbols": ["○"]})
        acc = [p for p in r["proposals"] if p["accepted"]]
        assert acc and all("mark" in p["reasons"] and "symbol:○" in p["reasons"] for p in acc)

    def test_indent_alone_rule(self):
        rows = [Line(1, i, _COL, bbox=[10, 40 if i in (2, 6) else 10, 30, 400]) for i in range(9)]
        assert propose_boundaries(rows, None)["stats"]["proposals"] == 0
        r = propose_boundaries(rows, {"indent_alone": True})
        acc = [p for p in r["proposals"] if p["accepted"]]
        assert [p["line_index"] for p in acc] == [2, 6]
        assert "indent_alone" in acc[0]["reasons"]


class TestLlmPatterns:
    def test_verify_pattern_counts_in_text(self):
        pages = [["又" + _COL[1:], _COL, _COL, "又" + _COL[1:], _COL, _COL] for _ in range(4)]
        lines = _pages(pages)
        row = verify_pattern(lines, "head_word", "又")
        assert row and row["count"] == 8 and row["toggle"] == "head_words" and row["llm"] is True
        assert row["id"] == "head:又" and row["value"] == "又"
        assert verify_pattern(lines, "head_word", "無") is None  # 전문에 없다
        assert verify_pattern(lines, "symbol", "又") is None  # 기호가 아니다

    def test_llm_answer_is_verified_not_trusted(self):
        pages = [["又" + _COL[1:], _COL, _COL, "答" + _COL[1:], _COL, _COL] for _ in range(4)]
        lines = _pages(pages)
        router = _FakeRouter(
            '{"patterns": [{"kind": "head_word", "value": "又", "why": "x"},'
            ' {"kind": "head_word", "value": "無", "why": "지어냄"},'
            ' {"kind": "none"}], "note": "n"}'
        )
        import asyncio

        rows, meta = asyncio.run(extract_start_patterns_llm(lines, normalize_rules(None), router))
        assert [r["id"] for r in rows] == ["head:又"]
        assert meta["model"] == "fake-1" and len(meta["raw"]) == 3
        assert router.calls[0]["response_format"] == "json" and router.calls[0]["think"] is False


def test_explicit_toc_page_is_excluded_even_without_entries(client, tmp_path, monkeypatch):  # noqa: F811
    """입력: 항목을 못 읽은 목차 쪽. 출력: 그 쪽을 본문에서 제외.

    목적: 목차를 규약으로 배우지 않는다.

    사람이 «여기가 목차»라고 적었으면 항목을 못 읽어도 그 쪽의 짧은 행을 본문 규약으로 세면 안 된다
    (D-117 1단). 전에는 항목 추출이 실패하면 목차 자체가 없던 일이 됐다(Codex 지적 2026-09-08).
    """
    from core import toc

    _lib, part_id = _setup(client, tmp_path)
    monkeypatch.setattr(toc, "extract_toc_entries_rule", lambda *_args: [])
    r = client.post(
        "/api/documents/d1/segmentation/signals",
        json={"part_id": part_id, "toc_pages": [1]},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["toc"] == {
        "pages": [1],
        "entries": 0,
        "matched": 0,
        "ratio": 0.0,
        "decisive": False,
    }
    assert d["lines"] == 5  # 1쪽의 네 행을 뺀 나머지


def test_auto_invalid_manifest_returns_repairable_error(client, tmp_path):  # noqa: F811
    """입력: 권 목록이 깨진 문헌. 출력: 400과 고칠 곳. 목적: 저장 실패를 500으로 숨기지 않는다."""
    from core.document import write_json_atomic

    lib, part_id = _setup(client, tmp_path)
    doc = Path(lib) / "documents" / "d1"
    manifest_path = doc / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["parts"] = []
    write_json_atomic(manifest_path, manifest)
    before = manifest_path.read_bytes()
    rows = [text for i in range(8) for text in (f"●제목{i}", "본문" * 20)]
    (doc / "L4_text" / "pages" / f"{part_id}_page_001.txt").write_text(
        chr(10).join(rows), encoding="utf-8", newline=""
    )
    r = client.post(
        "/api/documents/d1/segmentation/auto", json={"part_id": part_id, "use_toc": False}
    )
    assert r.status_code == 400, r.text
    assert "문헌 정보" in r.json()["error"]
    assert manifest_path.read_bytes() == before  # 실패했으면 원본을 건드리지 않는다


def test_signals_api_reports_stage(client, tmp_path):  # noqa: F811
    _lib, part_id = _setup(client, tmp_path)
    r = client.post("/api/documents/d1/segmentation/signals", json={"part_id": part_id})
    assert r.status_code == 200, r.text
    d = r.json()
    assert "stage" in d and d["stage"]["level"] in (0, 1, 2, 3)
    assert d["toc"] is None


class TestSampleScopes:
    @pytest.mark.parametrize("patterns", [1, True, {"kind": "none"}, "none"])
    def test_malformed_pattern_collection_returns_error(self, patterns):
        """입력: 목록 아닌 응답. 출력: 오류 메타. 목적: 모델 오답의 예외 전파를 막는다."""
        import asyncio

        router = _FakeRouter(json.dumps({"patterns": patterns}))
        rows, meta = asyncio.run(
            extract_start_patterns_llm(self._book(), normalize_rules(None), router)
        )
        assert rows == []
        assert meta["error"]

    def _book(self):
        pages = []
        for p in range(10):
            pages.append([f"{_DAYS[p]}談草", _COL, _COL, "又" + _COL[1:], _COL, _COL])
        return _pages(pages)

    def test_starts_is_default_and_truncates(self):
        lines = self._book()
        rules = normalize_rules(None)
        s = sample_start_lines(lines, rules)
        assert 0 < len(s) <= 80 and all(len(x) <= 24 for x in s)
        assert sample_start_lines(lines, rules, scope="starts") == s

    def test_context_wraps_candidate_with_neighbours(self):
        lines = self._book()
        s = sample_start_lines(lines, normalize_rules(None), scope="context")
        assert s and all(set(json.loads(x)) == {"before", "candidate", "after"} for x in s)

    def test_context_preserves_separator_inside_source_lines(self):
        """입력: 구분자가 든 원문. 출력: 복원 가능한 세 행. 목적: 후보 오인을 막는다."""
        lines = _pages([["앞 ／ ▶원문", '후보 "인용"', "뒤 \\ 원문"]])
        sample = sample_start_lines(lines, normalize_rules(None), scope="context")
        records = [json.loads(row) for row in sample]
        assert records[1] == {
            "before": lines[0].text,
            "candidate": lines[1].text,
            "after": lines[2].text,
        }

    def test_pages_and_all_send_whole_pages(self):
        lines = self._book()
        rules = normalize_rules(None)
        pages = sample_start_lines(lines, rules, scope="pages")
        heads = [x for x in pages if x.startswith("— ") and x.endswith("쪽 —")]
        assert len(heads) == 6 and len(pages) == 6 * 7
        whole = sample_start_lines(lines, rules, scope="all")
        assert len(whole) == 10 * 7  # 쪽 머리 + 6행
        size = sample_size(lines, rules, "all")
        assert size["lines"] == 70 and size["chars"] == sum(len(x) for x in whole)

    def test_llm_gets_scope_and_reports_size(self):
        lines = self._book()
        router = _FakeRouter('{"patterns": [{"kind": "head_word", "value": "又"}]}')
        import asyncio

        rows, meta = asyncio.run(
            extract_start_patterns_llm(lines, normalize_rules(None), router, scope="pages")
        )
        assert [r["id"] for r in rows] == ["head:又"]
        assert meta["scope"] == "pages" and meta["sample_lines"] == 42 and meta["sample_chars"] > 0
        assert router.calls[0]["response_format"] == "json"


def test_signals_llm_dry_run_reports_size_without_calling_model(client, tmp_path):  # noqa: F811
    _lib, part_id = _setup(client, tmp_path)
    r = client.post(
        "/api/documents/d1/segmentation/signals/llm",
        json={"part_id": part_id, "scope": "all", "dry_run": True},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["dry_run"] is True and d["scope"] == "all" and d["lines"] > 0 and d["chars"] > 0
    # 모르는 범위는 기본으로
    r = client.post(
        "/api/documents/d1/segmentation/signals/llm",
        json={"part_id": part_id, "scope": "everything", "dry_run": True},
    )
    assert r.json()["scope"] == "starts"


class TestDiscoveryIsGeneric:
    """D-119 — 코드에 종류가 없다: 有·談草·N日·○ 전부 «자리 × 되풀이 문자열»로 찾는다."""

    def test_finds_head_word_and_template_without_naming_them(self):
        # 행마다 달라야 «같은 글 되풀이»로 걸리지 않는다
        body = "山川草木風雲雨雪日月星辰花鳥魚蟲春夏秋冬"
        pages = []
        for p in range(8):
            # 쪽마다 자리를 바꾼다 — 같은 자리에 한 번씩 오면 판심(쪽 규약)으로 걸러진다
            rows = [_COL] * 7
            rows[p % 3] = "又" + body[p:] + body[:p]
            rows[3 + p % 3] = f"{'一二三四五六七八'[p]}、" + body[p + 2 :] + body[: p + 2]
            pages.append(rows)
        r = induce_signals(_pages(pages))
        again = [s for s in r["signals"] if s["id"].startswith("head:又")]
        assert again and again[0]["toggle"] == "head_words" and again[0]["value"].startswith("又")
        # 「一、」「二、」… 는 접으면 «N、» — 템플릿 칸으로
        tpl = [s for s in r["signals"] if s["toggle"] == "head_templates"]
        assert tpl and tpl[0]["value"].startswith("N")
        rules = rules_from_signals(r, None, [s["id"] for s in r["signals"] if s["group"] != "aux"])
        assert any(w.startswith("又") for w in rules["head_words"])
        assert any(t.startswith("N") for t in rules["head_templates"])

    def test_repeated_identical_lines_are_not_a_title_convention(self):
        # 판권 문구 「同十一日」이 쪽마다 되풀이 — 표제는 행마다 달라야 한다
        pages = [["同十一日", _COL, f"{_DAYS[p]}談草", _COL, _COL, "同十一日"] for p in range(8)]
        r = induce_signals(_pages(pages))
        same = [s for s in r["signals"] if s["id"].startswith("head:同")]
        assert all(s.get("marker") == "repeat_text" and not s["recommended"] for s in same)

    def test_template_rule_makes_candidates(self):
        lines = _pages([[_COL, "一、" + _COL[2:], _COL, "二、" + _COL[2:], _COL]])
        assert propose_boundaries(lines, None)["stats"]["proposals"] == 0
        r = propose_boundaries(lines, {"head_templates": ["N、"]})
        acc = [p for p in r["proposals"] if p["accepted"]]
        assert [p["line_index"] for p in acc] == [1, 3]
        assert any(x.startswith("head_template:") for x in acc[0]["reasons"])


class TestPageFormat:
    """판식(版式)을 좌표에서 읽는다 (D-120). 자신 없으면 아무것도 빼지 않는 것이 계약이다."""

    def test_irregular_format_has_no_geometric_labels(self):
        """입력: 한 쪽과 좌표 없는 행. 출력: unknown만. 목적: 유보 계약 보존."""
        lines = self._spread(pages=1)
        lines.append(Line(1, 99, "좌표없음"))
        result = page_format.analyze(lines)
        assert result["regular"] is False
        assert result["labels"] == {(1, 99): "unknown"}
        assert page_format.body_lines(lines, result) == lines

    @pytest.mark.parametrize(
        "bbox",
        [
            [520, 1400, 400, 1480],
            [400, 1480, 520, 1400],
            [400, 1400, 400, 1480],
            [400, 1400, 520, 1400],
        ],
    )
    def test_invalid_rectangles_are_unknown(self, bbox):
        """입력: 역전·면적 없는 좌표. 출력: 보존. 목적: 손상 좌표로 제외하지 않는다."""
        lines = self._spread()
        bad = Line(1, 99, "손상좌표", bbox=bbox)
        lines.append(bad)
        result = page_format.analyze(lines)
        assert result["labels"][(1, 99)] == "unknown"
        assert page_format.line_length(bad) is None
        assert page_format.line_axis(bad) is None
        assert bad in page_format.body_lines(lines, result)

    def test_horizontal_transpose_preserves_classification(self):
        """입력: 같은 판식의 축 교환. 출력: 같은 라벨. 목적: 가로쓰기 기준점 검증."""
        lines = self._spread()
        lines.extend(
            [
                Line(1, 90, "두주", bbox=[400, 1400, 520, 1480]),
                Line(1, 91, "짧은표제", bbox=[600, 800, 720, 880]),
            ]
        )
        horizontal = [
            Line(
                ln.page,
                ln.line_index,
                ln.text,
                bbox=[ln.bbox[1], ln.bbox[0], ln.bbox[3], ln.bbox[2]],
                writing_direction="horizontal_ltr",
            )
            for ln in lines
        ]
        assert page_format.analyze(horizontal) == page_format.analyze(lines)

    def test_many_notes_do_not_define_body_reference(self):
        """입력: 본문보다 많은 두주. 출력: 두주 분리. 목적: 기준의 자기 오염 방지."""
        lines = self._spread()
        for page in range(1, 9):
            lines.extend(Line(page, 90 + i, "두주", bbox=[400, 1400, 520, 1480]) for i in range(25))
        result = page_format.analyze(lines)
        assert result["regular"] is True
        assert result["counts"]["margin"] == 200
        assert result["counts"]["body"] == 160

    def test_two_fold_candidates_abstain(self):
        """입력: 같은 크기의 틈 둘. 출력: 유보. 목적: 첫 틈을 임의로 확정하지 않는다."""
        axes = [0, 10, 20, 60, 70, 80, 120, 130, 140]
        assert page_format._page_fold(axes) is None

    def test_duplicate_axes_do_not_change_columns_or_fold(self):
        """입력: 같은 축의 OCR 중복. 출력: 같은 판식. 목적: 행을 열로 중복 세지 않는다."""
        axes = [0, 10, 20, 60, 70, 80]
        expected = (20, 60, 3, 3)
        assert page_format._page_fold(axes) == expected
        assert page_format._page_fold(axes + axes) == expected
        assert page_format._page_fold([0, 0, 10, 60, 70, 70]) is None

    def test_fold_agreement_does_not_depend_on_coordinate_origin(self):
        """입력: 원점만 이동한 불규칙 판식. 출력: 같은 유보. 목적: 절대 좌표 편향 방지."""
        lines = self._spread(pages=4)
        for ln in lines:
            shift = 3000 if ln.page > 2 else 0
            ln.bbox = [ln.bbox[0] + shift, ln.bbox[1], ln.bbox[2] + shift, ln.bbox[3]]
        assert page_format.analyze(lines)["regular"] is False
        for ln in lines:
            ln.bbox = [ln.bbox[0] + 100000, ln.bbox[1], ln.bbox[2] + 100000, ln.bbox[3]]
        assert page_format.analyze(lines)["regular"] is False

    @pytest.mark.parametrize("pages", range(3, 7))
    @pytest.mark.parametrize("fold_pages", range(7))
    def test_regular_page_count_boundary(self, pages, fold_pages):
        """입력: 3~6쪽의 판심 비율. 출력: 기존 문턱. 목적: 반올림 경계 검산."""
        lines = self._spread(pages=pages)
        flat = self._spread(pages=pages, gap=0)
        lines = [ln for ln in lines if ln.page <= fold_pages]
        lines += [ln for ln in flat if ln.page > fold_pages]
        result = page_format.analyze(lines)
        assert result["regular"] == (min(pages, fold_pages) >= max(3, pages * 0.5))
        if not result["regular"]:
            assert result["labels"] == {}
            assert page_format.body_lines(lines, result) == lines

    @pytest.mark.parametrize("height", [0.001, 80, 1700])
    def test_equal_lengths_have_no_absolute_size_cutoff(self, height):
        """입력: 모두 같은 길이. 출력: 비례 문턱. 목적: 작다는 이유로 지우지 않는다."""
        assert page_format._body_cut([height] * 20) == pytest.approx(height * 0.6)
        lines = self._spread(height=height)
        result = page_format.analyze(lines)
        assert result["counts"]["body"] == len(lines)
        assert page_format.body_lines(lines, result) == lines

    def test_fold_minimum_and_equal_pitch(self):
        """입력: 등간격·최소 열 수. 출력: 유보 또는 판심. 목적: 열 수 경계 검산."""
        assert page_format._page_fold(list(range(6))) is None
        assert page_format._page_fold([0, 10, 50, 60, 70]) is None
        assert page_format._page_fold([0, 10, 20, 60, 70, 80]) == (20, 60, 3, 3)

    @pytest.mark.parametrize("left,right", [(1, 19), (19, 1), (10, 10)])
    def test_fold_has_no_assumed_center(self, left, right):
        """입력: 한쪽으로 치우친 틈. 출력: 측정 행자. 목적: 중앙 판심을 가정하지 않는다."""
        result = page_format.analyze(self._spread(left=left, right=right))
        assert result["regular"] is True
        assert result["haengja"] == (left, right)
        assert result["fold"]["center"] == 200 + (left - 0.5) * 140 + 500 + 60

    def test_variable_column_counts_abstain_without_dominant_pair(self):
        """입력: 매쪽 다른 열 수. 출력: 유보. 목적: 반복 없는 판식의 본문 보존."""
        lines = []
        for page in range(1, 9):
            spread = self._spread(pages=1, left=page + 3, right=page + 3)
            for ln in spread:
                ln.page = page
            lines.extend(spread)
        result = page_format.analyze(lines)
        assert result["regular"] is False
        assert page_format.body_lines(lines, result) == lines

    def test_middle_length_title_and_merged_columns_are_kept(self):
        """입력: 중간 길이 표제·합쳐진 열. 출력: 보존. 목적: 두 길이 문턱의 역할 검증."""
        lines = self._spread()
        lines.append(Line(1, 90, "표제", bbox=[400, 1400, 520, 2080]))
        # OCR이 두 열을 합쳐도 길이는 본문이며, 판심 안쪽이라는 근거도 없다.
        lines[0].bbox[2] = lines[1].bbox[2]
        lines.pop(1)
        result = page_format.analyze(lines)
        assert result["regular"] is True
        assert page_format.body_lines(lines, result) == lines

    def test_analysis_is_repeatable_and_does_not_mutate_input(self):
        """입력: 판심 조각·좌표 없는 행. 출력: 같은 결과. 목적: 재호출과 필터 합치 검증."""
        import copy

        lines = self._spread()
        lines.extend(
            [
                Line(1, 90, "판심", bbox=[2000, 1400, 2100, 1480]),
                Line(1, 91, "좌표없음"),
            ]
        )
        before = copy.deepcopy(lines)
        result = page_format.analyze(lines)
        assert result == page_format.analyze(lines)
        assert lines == before
        assert result["labels"][(1, 90)] == "pansim"
        assert page_format.body_lines(lines) == page_format.body_lines(lines, result)
        assert page_format.body_lines(lines, result) == [ln for ln in lines if ln.line_index != 90]

    def test_catalog_and_coordinates_check_each_other(self):
        """입력: 목록의 행자수와 좌표에서 잰 값. 출력: 일치·불일치·유보. 목적: 서로의 검산.

        좌표만으로 «접은 자리»를 확정할 수 없다는 것이 D-120의 알려진 한계다. 목록(KORMARC
        300▼b)의 행자수는 그와 독립이므로 확인도 반증도 된다.
        """
        catalog = {"haengja": "반엽 10행 20자"}
        same = page_format.compare_with_catalog({"haengja": (10, 10)}, catalog)
        assert same["agree"] is True and same["catalog"] == 10

        differ = page_format.compare_with_catalog({"haengja": (7, 8)}, catalog)
        assert differ["agree"] is False
        assert "7·8행" in differ["summary"]

        # 한쪽 반엽만 열을 놓친 쪽은 «맞음»으로 본다 — 목록의 값이 어느 한쪽에 있으면 된다
        partial = page_format.compare_with_catalog({"haengja": (9, 10)}, catalog)
        assert partial["agree"] is True

    def test_comparison_is_silent_when_there_is_nothing_to_compare(self):
        """입력: 목록만·좌표만·둘 다 없음. 출력: 유보 또는 None. 목적: 없는 것을 지어내지 않는다."""
        only_measured = page_format.compare_with_catalog({"haengja": (10, 10)}, None)
        assert only_measured["agree"] is None and only_measured["catalog"] is None
        only_catalog = page_format.compare_with_catalog({"haengja": None}, {"haengja": "10행"})
        assert only_catalog["agree"] is None and only_catalog["measured"] is None
        assert page_format.compare_with_catalog({"haengja": None}, None) is None

    def test_catalog_reads_the_raw_line_when_fields_are_not_split(self):
        """입력: 갈라 담지 않은 원문. 출력: 행 수. 목적: 붙여 넣기만 해도 견줄 수 있다."""
        raw = {"summary": "四周雙邊 半郭 19.1 x 14.6 cm, 10行20字 註雙行, 上2葉花紋魚尾"}
        assert page_format.catalog_columns(raw) == 10
        assert page_format.catalog_columns({"summary": "판식 미상"}) is None
        assert page_format.catalog_columns({"summary": "1935行"}) is None  # 행 수가 아닌 숫자

    def _spread(self, pages=8, left=10, right=10, gap=1000, pitch=140, height=1700, top=800):
        """접어 찍은 장(반엽 둘) 흉내 — 왼쪽 열들, 넓은 판심, 오른쪽 열들."""
        lines = []
        for p in range(1, pages + 1):
            idx = 0
            x = 200
            for i in range(left + right):
                if i == left:
                    x += gap  # 판심(접은 자리)
                lines.append(
                    Line(
                        p,
                        idx,
                        f"本文{p}_{i}" + "文" * 12,
                        bbox=[x, top, x + 120, top + height],
                        writing_direction="vertical_rtl",
                    )
                )
                idx += 1
                x += pitch
        return lines

    def test_fold_and_haengja_are_measured_not_assumed(self):
        """입력: 반엽 10열씩 접은 장. 출력: 일정한 판식·행자 (10, 10). 목적: 좌표로 잰다."""
        lines = self._spread()
        r = page_format.analyze(lines)
        assert r["regular"] is True
        assert r["haengja"] == (10, 10)
        assert r["fold"]["pages"] == 8

    def test_single_leaf_scan_has_no_fold_and_changes_nothing(self):
        """입력: 접은 자리 없는 쪽. 출력: 전부 본문. 목적: 자신 없으면 잠자코 있는다."""
        lines = self._spread(gap=140)  # 판심 없이 고른 간격
        r = page_format.analyze(lines)
        assert r["regular"] is False
        assert r["counts"]["margin"] == 0 and r["counts"]["pansim"] == 0
        assert len(page_format.body_lines(lines, r)) == len(lines)

    def test_marginal_note_is_dropped_but_indented_title_is_kept(self):
        """입력: 아주 작은 두주와 내려쓴 별행 표제. 출력: 두주만 뺀다.

        목적: D-117의 indent_alone 판식(시집은 제목만 내려쓴다)을 지운다면 정작 찾아야 할
        표제를 잃는다. 두주는 본문 열의 몇십 분의 일이고 표제는 그렇게까지 작지 않다.
        """
        lines = self._spread()
        page, idx = 1, 90
        lines.append(  # 두주 — 아주 작고 아래에서 시작
            Line(page, idx, "同日", bbox=[400, 1400, 520, 1480], writing_direction="vertical_rtl")
        )
        lines.append(  # 내려쓴 별행 표제 — 짧지만 두주만큼 작지는 않다
            Line(
                page,
                idx + 1,
                "詩三首",
                bbox=[600, 1000, 720, 1750],
                writing_direction="vertical_rtl",
            )
        )
        r = page_format.analyze(lines)
        assert r["labels"][(page, idx)] == "margin"
        assert r["labels"][(page, idx + 1)] == "body"
        kept = {(ln.page, ln.line_index) for ln in page_format.body_lines(lines, r)}
        assert (page, idx) not in kept and (page, idx + 1) in kept

    def test_lines_without_coordinates_are_kept(self):
        """입력: 좌표 없는 행. 출력: 남는다. 목적: 텍스트로 가져온 문헌을 망치지 않는다."""
        lines = self._spread()
        lines.append(Line(1, 99, "좌표없음"))
        r = page_format.analyze(lines)
        assert r["labels"][(1, 99)] == "unknown"
        assert any(ln.line_index == 99 for ln in page_format.body_lines(lines, r))

    def test_induction_only_drops_when_the_format_is_regular(self):
        """입력: 판심 있는 책과 없는 책. 출력: 전자만 행이 준다. 목적: 발견기와의 계약."""
        with_fold = self._spread()
        noise = Line(1, 90, "同日", bbox=[400, 1400, 520, 1480], writing_direction="vertical_rtl")
        with_fold.append(noise)
        r1 = induce_signals(with_fold)
        assert r1["page_format"]["regular"] is True
        assert r1["lines"] == len(with_fold) - 1  # 두주 한 행이 빠졌다

        flat = self._spread(gap=140)
        flat.append(
            Line(1, 90, "同日", bbox=[400, 1400, 520, 1480], writing_direction="vertical_rtl")
        )
        r2 = induce_signals(flat)
        assert r2["page_format"]["regular"] is False
        assert r2["lines"] == len(flat)  # 하나도 빼지 않았다


class TestDiscoveryRegressions:
    """입력 경계와 발견→판정 계약을 고정해 문법별 예외의 재발을 막는다."""

    def test_short_and_symbol_only_lines(self):
        """입력: 짧은 행. 출력: 실제 길이의 꼴만. 목적: 빈 꼴·중복 계수 방지."""
        fams = induction._discover(["", "●", "本●", "●又●又"] * 4)
        assert fams[("sym", "●")] == [k for k in range(16) if k % 4 != 0]
        assert fams[("after", "●又")] == [3, 7, 11, 15]
        assert all(form for _, form in fams)
        assert ("head", "本●") in fams
        assert ("after", "●") not in fams

    def test_after_uses_folded_length_not_raw_length(self):
        """입력: 긴 수사 뒤 표지. 출력: 접은 네 글자. 목적: 원문 절단 누락 방지."""
        fams = induction._discover(["●" + "一" * 12 + "、本文"] * 4)
        assert fams[("after", "●N、本文")] == [0, 1, 2, 3]

    def test_nested_equal_count_keeps_longer(self):
        """입력: 같은 횟수의 포함 꼴. 출력: 긴 꼴. 목적: 정상 가지치기를 고정한다."""
        fams = {("head", "又"): [0, 3, 6, 9], ("head", "又詩"): [0, 3, 6, 9]}
        assert induction._prune_nested(fams) == {("head", "又詩"): [0, 3, 6, 9]}

    def test_lift_without_occurrences_is_not_evidence(self):
        """입력: 전문에 없는 꼴. 출력: 편중 0. 목적: 기대값 0의 무한 점수 방지."""
        assert induction._lift(["本文"], ("head", "無"), 4) == 0

    def test_tail_drop_requires_actual_date_only_lines(self):
        """입력: 날짜 글자를 포함한 일반 어휘. 출력: 어휘. 목적: 글자 목록 편향 제거."""
        texts = ["萬物皆同", "天下大同", "和而不同", "殊途而同"]
        assert induction._classify("tail", "同", texts, list(range(4)))[0] == "title_words"
        mixed = ["十一日", "十二日", "十三日", "山中度日"]
        assert induction._classify("tail", "N日", mixed, list(range(4)))[0] != "drop"
        dates = ["十一日", "十二日", "十三日", "十四日"]
        assert induction._classify("tail", "N日", dates, list(range(4)))[0] == "drop"

    def test_after_classifies_only_the_matching_occurrence(self):
        """입력: 한 행의 서로 다른 기호 뒤 꼴. 출력: 각 꼴의 문법. 목적: 날짜 오염 방지."""
        texts = ["●又本文●初一日晴"] * 4
        assert induction._classify("after", "●又", texts, list(range(4)))[0] == "symbols"
        assert induction._classify("after", "●初N", texts, list(range(4)))[0] == "signals.mark"

    def test_classification_does_not_sample_only_the_first_40(self):
        """입력: 앞 40행만 날짜. 출력: 혼합 어휘. 목적: 문헌 뒤쪽 표본 누락 방지."""
        texts = ["同十一日"] * 40 + ["同遊山水"] * 20
        assert induction._classify("head", "同", texts, list(range(60)))[0] == "head_words"

    def test_month_only_and_relative_dates_are_not_repeated_dates(self):
        """입력: 월만 있는 날짜와 상대 날짜. 출력: 날짜 0. 목적: 같은 달의 시제(「三月春」)를
        판권의 «같은 날짜 되풀이»로 오판하지 않는다 — Codex는 월만으로도 세자고 했으나 거절."""
        texts = ["三月春", "三月雨", "三月晴", "三月風", "翌日", "同日"]
        assert induction._repeat_fraction(texts, list(range(6))) == (0, 1.0)

    def test_grammar_families_are_shown_but_not_recommended_when_dense(self):
        """입력: 매 행이 날짜. 출력: 날짜 가족은 보이되 권고 아님. 목적: 문법 가족도 밀도 문턱
        (_solid)을 따른다. 판심 필터는 문법 가족에 적용하지 않는다 — «쪽마다 한 번 같은 자리»는
        판심의 꼴이지만 날짜는 행마다 다른 글이라 한 쪽 한 기사 일기를 판심으로 버리면 안 된다
        (Codex 제안 거절, 2026-09-08)."""
        dense = induce_signals(_pages([["一日"] * 8]))
        date = [s for s in dense["signals"] if s["id"] == "date"]
        assert date and not date[0]["recommended"] and date[0]["per100"] == 100.0
        pages = [[_DAYS[p] + "記", _COL, _COL, _COL] for p in range(8)]
        fixed = induce_signals(_pages(pages))
        assert any(s["id"] == "date" and s["recommended"] for s in fixed["signals"])
        # 같은 행들의 어휘 꼴(「初N日記」)은 판심으로 떨어져도 된다 — 날짜 가족만 살면 된다
        assert not any(d["id"] == "date" for d in fixed["dropped"])

    def test_overlap_deduplication_has_a_stable_tie_break(self, monkeypatch):
        """입력: 동일 점수·중첩 가족의 역순. 출력: 같은 선택. 목적: 사전 삽입 순서 의존 제거."""
        texts = ["●AX●BY", _COL, _COL] * 4
        fams = {("after", "●AX"): [0, 3, 6, 9], ("after", "●BY"): [0, 3, 6, 9]}
        lines = _pages([texts])
        monkeypatch.setattr(induction, "_discover", lambda _: fams)
        forward = induction.induce_signals(lines)
        monkeypatch.setattr(induction, "_discover", lambda _: dict(reversed(list(fams.items()))))
        reverse = induction.induce_signals(lines)
        assert forward == reverse

    @pytest.mark.parametrize("toggle", ["head_templates", "tail_templates"])
    def test_templates_count_as_saved_rules(self, toggle):
        """입력: 템플릿만 저장. 출력: 비어 있지 않음. 목적: 자동 도출의 덮어쓰기 방지."""
        assert not rules_are_empty({toggle: ["N、"]})

    def test_rules_preserve_unlisted_values_but_remove_unchecked_ones(self):
        """입력: 저장값·미선택·중복 선택. 출력: 보존된 고유 값. 목적: 재도출 데이터 유실 방지."""
        rows = [
            {"id": "head:又", "toggle": "head_words", "value": "又", "group": "primary"},
            {"id": "head:答", "toggle": "head_words", "value": "答", "group": "primary"},
            {"id": "other", "toggle": "head_words", "value": "答", "group": "primary"},
        ]
        base = {"head_words": ["存", "存", "又"], "tail_templates": ["N篇"]}
        rules = rules_from_signals({"signals": rows}, base, ["head:答", "other"])
        assert rules["head_words"] == ["存", "答"]
        assert rules["tail_templates"] == ["N篇"]
        assert base["head_words"] == ["存", "存", "又"]

    def test_verified_pattern_obeys_adjacency_and_unknown_filter(self):
        """입력: 덩어리 표지·OCR 잡음. 출력: 비권고·제외. 목적: LLM 문턱 우회 방지."""
        lines = _pages([["又山", "又川", "又林", "又海"] + [_COL] * 8])
        row = verify_pattern(lines, "head_word", "又")
        assert row and row["adjacent"] == 0.75 and not row["recommended"]
        unknown = _pages([["□山", _COL] * 4])
        assert verify_pattern(unknown, "head_word", "□") is None

    def test_decisive_toc_survives_a_small_body(self):
        """입력: 충분히 대조된 목차·짧은 본문. 출력: 1단. 목적: 빈 본문 조기 반환 우회 방지."""
        toc = {"pages": [1], "entries": 3, "matched": 3, "decisive": True}
        result = induce_signals(_pages([["目錄"], ["本文"]]), toc=toc)
        assert result["stage"]["level"] == 1 and result["stage"]["by"] == ["toc"]
