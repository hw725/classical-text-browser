"""자동 스캔 → 작업 계획, PDF 판면 줄바꿈 지우기 (2026-10-02).

무엇을 고정하는가:
  - 자동 스캔(판독 계획 측정)의 결과는 **글이 아니라 계획 칸으로 바로** 들어간다
    (core.read_plan.plan_from_survey). 사람이 건너뜀으로 둔 쪽·측정하지 않은 쪽은 그대로이고,
    누운 쪽의 90/270은 «추정»으로 표시된다.
  - 텍스트 내보내기는 PDF 판면 때문에 생긴 줄바꿈만 지운다. 세로는 그대로 붙이고 가로는 빈칸,
    영어 하이픈 낱말은 붙인다. 쪽을 넘는 문단은 하나로 잇고 쪽 표시를 글 안에 넣는다.
    쪽마다 되풀이되는 머리글은 뺀다.
"""

from __future__ import annotations

import json

from src.core.read_plan import default_engine_for, plan_from_survey
from src.export.text_export import (
    Chapter,
    _body,
    build_chapters,
    join_columns,
    page_directions,
    running_line_keys,
)

# ── 자동 스캔 → 계획 ─────────────────────────────────────


def _row(page, current=0, target=0, guess=False, engine=None, content=None, mixed=False):
    return {
        "page": page,
        "current": current,
        "target": target,
        "guess": guess,
        "engine": engine,
        "content": content,
        "mixed": mixed,
    }


def test_scan_fills_plan_directly_and_keeps_human_choices():
    """입력: 사람이 2쪽을 건너뜀·6쪽을 paddleocr로 적은 계획 + 1~5쪽 스캔.
    출력: 2쪽은 그대로 건너뜀, 3~4쪽은 측정한 90°(추정), 5쪽은 백지라도 사람이 적은 쪽이
    아니므로 건너뜀, 6쪽(측정 안 함)은 사람이 적은 그대로."""
    base = {
        "title": "책",
        "guidance": "",
        "ranges": [
            {"pages": "2", "skip": True, "note": "표지 뒷면"},
            {"pages": "6", "rotation": 0, "engine": "paddleocr", "writing": "horizontal_ltr"},
        ],
        "chapters": [{"page": 1, "title": "서", "level": 1}],
    }
    per_page = [
        _row(1, engine="ndlocr", content="modern_print"),
        _row(2, engine="ndlocr", content="modern_print"),
        _row(3, target=90, guess=True, engine="ndlocr", content="modern_print"),
        _row(4, target=90, guess=True, engine="ndlocr", content="modern_print"),
        _row(5, content="blank"),
    ]
    for r in per_page:
        if r["content"] == "modern_print":
            r["label"] = "근현대 활자"
    plan, marks = plan_from_survey(per_page, 6, base_plan=base, fallback_engine="ndlocr")
    by = {r["pages"]: r for r in plan["ranges"]}
    assert by["2"] == {"pages": "2", "skip": True, "note": "표지 뒷면"}
    assert by["3-4"]["rotation"] == 90 and "추정 90°" in by["3-4"]["note"]
    assert by["5"]["skip"] is True and by["5"]["note"] == "스캔: 백지"
    assert by["6"]["engine"] == "paddleocr" and "note" not in by["6"]
    assert by["1"]["note"].startswith("스캔: 측정 0°") and "근현대 활자" in by["1"]["note"]
    assert plan["chapters"] == base["chapters"]  # 장 목록은 스캔이 건드리지 않는다
    assert marks["guess_pages"] == [3, 4] and marks["mixed_pages"] == []


def test_scan_orientation_only_uses_fallback_engine_and_writing():
    """방향만(CPU) 스캔은 엔진을 모른다 — 계획에 없던 쪽은 fallback 엔진과 고른 쓰기 방향."""
    plan, marks = plan_from_survey(
        [_row(1), _row(2, target=None)],
        2,
        writing="horizontal_ltr",
        fallback_engine="paddleocr",
    )
    assert [r["engine"] for r in plan["ranges"]] == ["paddleocr", "paddleocr"]
    assert all(r["writing"] == "horizontal_ltr" for r in plan["ranges"])
    # 못 잰 쪽(target None)은 기본값으로 채웠다는 메모가 붙어 잰 쪽과 구별된다
    assert plan["ranges"][1] == {
        "pages": "2",
        "rotation": 0,
        "engine": "paddleocr",
        "writing": "horizontal_ltr",
        "note": "스캔: 못 잼 — 기본값",
    }
    assert marks["measured_pages"] == [1]


def test_scan_mixed_page_is_flagged_and_left_out():
    """섞인 쪽은 엔진 하나로 못 읽는다 — 계획에서 뺀다(OCR 패널이 «계획에서 뺌»이라 알린다)."""
    plan, marks = plan_from_survey([_row(1, mixed=True, content="hangul")], 1)
    assert marks["mixed_pages"] == [1]
    assert plan["ranges"][0]["skip"] is True and "영역별 OCR" in plan["ranges"][0]["note"]


def test_scan_keeps_human_setting_on_blank_or_mixed_page():
    """사람이 엔진을 적은 쪽은 모델이 «백지»·«섞임»이라고 해도 건너뜀으로 뒤집지 않는다."""
    base = {
        "title": "",
        "guidance": "",
        "ranges": [
            {"pages": "1-2", "rotation": 0, "engine": "llm_vision", "writing": "vertical_rtl"}
        ],
        "chapters": [],
    }
    # 측정이 다른 회전·엔진을 함께 내놓아도 회전·엔진까지 그대로 지킨다(Codex 지적 2026-10-02)
    plan, _marks = plan_from_survey(
        [
            _row(1, target=90, engine="ndlocr", content="blank"),
            _row(2, target=180, engine="ndlocr", mixed=True, content="hangul"),
        ],
        2,
        base_plan=base,
    )
    assert all(
        not r.get("skip") and r["engine"] == "llm_vision" and r["rotation"] == 0
        for r in plan["ranges"]
    )


def test_scan_bad_rows_are_reported_and_good_rows_kept():
    """이상한 측정 행 하나가 정상 행까지 버리게 하지 않는다 — 이상한 행은 problems로."""
    rows = [
        None,
        {"page": True, "target": 0},
        {"page": 2, "target": "unknown"},
        _row(3, target=90),
    ]
    plan, marks = plan_from_survey(rows, 3)
    assert [r["pages"] for r in plan["ranges"]] == ["3"]
    assert plan["ranges"][0]["rotation"] == 90
    assert len(marks["problems"]) == 3


def test_default_engine_for_writing():
    assert default_engine_for("horizontal_ltr", {"paddleocr", "ndlocr"}) == "paddleocr"
    assert default_engine_for("vertical_rtl", {"paddleocr", "ndlocr"}) == "ndlocr"
    assert default_engine_for("vertical_rtl", {"honkoku"}) == "honkoku"
    assert default_engine_for("vertical_rtl", set()) == "ndlocr"


# ── 줄 잇기 ─────────────────────────────────────────────

PAPER = [
    "3). 準擬人法(物質的인 性質이 觀念에 配當된 것) (5)",
    "으로 나누고 있는데, 이는 擬人法 自體를 分類한 것이나 擬人體文學의 概念이라면",
    "적어도 「全篇이 擬人形式으로 쓰여진 모든 文學作品」 즉 Moulton 氏의 1) 의 境遇를",
    "擇해야 할 것이며 「擬人體」라는 用語는 그 文字가 表示하는 바와 같이 內容도 主題도",
    "모두 擬人으로 된 것을 이른다.",
]


def _paper_l2(ends, starts=None):
    """가로쓰기 한 블록. ends는 줄마다 오른쪽 끝 x(글자 높이 20 → 글자 1.5개 = 30)."""
    starts = starts or [100] * len(ends)
    return {
        "ocr_results": [
            {
                "writing_direction": "horizontal_ltr",
                "lines": [
                    {"text": f"줄{i}", "bbox": [s, 100 + 30 * i, e, 120 + 30 * i]}
                    for i, (s, e) in enumerate(zip(starts, ends))
                ],
            }
        ]
    }


def test_horizontal_lines_join_with_space():
    """가로쓰기 논문(사용자가 준 본보기): 양쪽 맞춤이라 첫 줄은 글자가 적어도 판면은 가득 찼다.
    줄 좌표가 있으면 한 문단으로 잇고, 판면 줄바꿈 자리에는 빈칸 하나. 「로 시작하는 줄도 잇는다."""
    from src.export.text_export import _join, line_geometry

    flags = line_geometry(_paper_l2([900, 905, 898, 902, 500]), len(PAPER))
    assert flags == [(True, False)] * 4 + [(False, False)]
    paras, still_open = _join(PAPER, True, flags)
    assert len(paras) == 1 and not still_open
    assert "(5) 으로 나누고" in paras[0] and "概念이라면 적어도 「全篇이" in paras[0]
    assert paras[0].endswith("主題도 모두 擬人으로 된 것을 이른다.")
    # 좌표가 없으면 글자 폭 어림 — 글자가 적은 첫 줄을 문단 끝으로 오판한다(그래서 좌표가 먼저다)
    assert len(join_columns(PAPER, horizontal=True)) == 2


def test_word_evidence_rejoins_broken_korean_words():
    """옛 국한문 조판은 줄이 어절 한가운데서 꺾인다. 같은 문헌의 줄 가운데를 근거로 가른다
    (doc_20260917 김일렬 논문에서 잰 유형들)."""
    from src.export.text_export import WordEvidence, _glue

    # 줄 가운데(첫·끝 어절이 아닌 자리)에 온전한 어절로 나오는 것들이 근거가 된다
    pages = {
        1: "\n".join(
            [
                "이 글은 알 수 있다 하고 또 그대로 둔다",
                "그 作品 自體 硏究는 對象에 두고 本論 그리고 끝",
                "가 作品의 範圍로 하나로 文學의 槪念을 본다",
                "나 學者는 擬人體를 對象으로 主題를 본다",
            ]
        )
    }
    ev = WordEvidence(pages)
    glue = lambda a, b: _glue(a, b, True, ev)  # noqa: E731
    assert glue("알 수 있", "다. 그런데") == "알 수 있다. 그런데"  # ① «있다»가 줄 가운데에 있다
    assert glue("用語를 그대", "로 쓴다") == "用語를 그대로 쓴다"
    assert glue("이것은 對象", "에다가 둔다") == "이것은 對象에다가 둔다"  # 한자 어근 + 한글 토씨
    assert glue("面에 置", "重했다는 것") == "面에 置重했다는 것"  # 한자 한 글자로 끝남
    assert glue("어떤 作品", "自體의 硏究") == "어떤 作品 自體의 硏究"  # 둘 다 홀로 선 낱말
    assert glue("이렇게", "慣用的인 意味") == "이렇게 慣用的인 意味"  # 한글 다음 한자는 경계
    assert glue("가 그리고", "끝이다") == "가 그리고 끝이다"  # «그리고»는 홀로 선 어절
    # 한글이 없는 가로쓰기는 근거 없이 한자끼리 붙인다
    assert _glue("本年六月勅令第三", "十九號", True) == "本年六月勅令第三十九號"


def test_indent_starts_paragraph_and_quote_only_once():
    from src.export.text_export import line_geometry

    # 둘째 줄 들여 씀(새 문단), 넷째·다섯째는 인용 단락처럼 줄 전체가 들어감 — 넷째만 새 문단
    flags = line_geometry(_paper_l2([900] * 5, [100, 140, 100, 160, 160]), 5)
    assert [f[1] for f in flags] == [False, True, False, True, False]
    # 줄 수가 L4와 다르면(사람이 줄을 더하거나 뺐으면) 좌표를 쓰지 않는다
    assert line_geometry(_paper_l2([900] * 5), 4) is None


def test_horizontal_numbered_line_starts_paragraph():
    full = "가나다라마바사아자차카타파하" * 3
    paras = join_columns([full, full, "2. 둘째 항목 " + full, full], horizontal=True)
    assert len(paras) == 2 and paras[1].startswith("2. 둘째 항목")


def test_latin_hyphen_word_is_rejoined():
    full = "This is a long line of English text in a paper that ends with con-"
    paras = join_columns([full, "cept and continues here with more words to fill.", "short."], True)
    assert "concept and" in paras[0]


def test_vertical_lines_join_without_space():
    full = "一二三四五六七八九十" * 2
    assert join_columns([full, full + "。", "短"]) == [full + full + "。短"]


def test_paragraph_continues_across_pages_with_inline_marker():
    """앞 쪽 마지막 줄이 가득 찼고 다음 쪽 첫 줄이 새 문단 머리가 아니면 한 문단이다."""
    full = "가나다라마바사아자차카타파하" * 3
    ch = Chapter("논문", 1, pages=[(1, [full, full]), (2, [full, "끝."])])
    md = _body(ch, "md", keep_lines=False, horizontal={1: True, 2: True})
    paras = md.split("\n\n")
    assert paras[0] == '<a id="p1"></a>**[PDF p.1]**'
    assert len(paras) == 2
    assert f'{full} <a id="p2"></a>[PDF p.2]{full} 끝.' in paras[1]


def test_no_join_across_missing_page_or_direction_change():
    """확정본이 없는 쪽을 건너뛰거나(1→3쪽) 쓰기 방향이 바뀌면 문단을 잇지 않는다."""
    full = "가나다라마바사아자차카타파하" * 3
    ch = Chapter("글", 1, pages=[(1, [full, full]), (3, [full, "끝."])])
    md = _body(ch, "md", keep_lines=False, horizontal={1: True, 3: True})
    assert "**[PDF p.3]**" in md and "[PDF p.3]" not in md.replace("**[PDF p.3]**", "")
    ch = Chapter("글", 1, pages=[(1, [full, full]), (2, [full, "끝."])])
    md = _body(ch, "md", keep_lines=False, horizontal={1: True, 2: False})
    assert "**[PDF p.2]**" in md


def test_join_decision_never_sees_page_marks():
    """쪽을 넘어 이을 때 빈칸·어절 판정은 쪽 표시가 섞이지 않은 글로 한다 — 표시가 섞이면 앞 줄 끝
    어절이 «p.2]作品»처럼 되어 문헌 안 근거를 못 찾는다(Codex 지적 2026-10-02)."""
    seen: list[str] = []

    class Spy:
        def joins(self, a, b):
            seen.append(a)
            return False

    full = "가나다라마바사아자차카타파하" * 3
    ch = Chapter(
        "글",
        1,
        pages=[(1, [full, full]), (2, [full + " 作品"]), (3, ["自體의 " + full, "끝."])],
        flags=[[(True, False)] * 2, [(True, False)], [(True, False), (False, False)]],
    )
    md = _body(ch, "md", keep_lines=False, horizontal={1: True, 2: True, 3: True}, evidence=Spy())
    assert seen and all("<a id" not in a and "PDF p." not in a for a in seen)
    assert "[PDF p.2]" in md and "[PDF p.3]" in md


def test_single_line_block_is_not_treated_as_full():
    from src.export.text_export import line_geometry

    l2 = {
        "ocr_results": [
            {
                "writing_direction": "horizontal_ltr",
                "lines": [{"text": "짧은 한 줄", "bbox": [100, 100, 300, 120]}],
            }
        ]
    }
    assert line_geometry(l2, 1) == [(False, False)]


def test_running_headers_are_dropped():
    pages = {
        n: f"國語國文學 第{40 + n}號\n"
        + "\n".join(f"{body}의 {k}번째 줄을 이어서 적는다" for k in ("첫", "둘", "셋", "넷"))
        + f"\n- {n} -"
        for n, body in enumerate(["가을", "겨울", "봄날", "여름", "장마"], 1)
    }
    assert "國語國文學第#號" in running_line_keys(pages)
    chapters, stats = build_chapters(pages, [], front_title="논문")
    assert stats["running_lines"] == 5
    assert all("國語國文學" not in ln for _p, lines in chapters[0].pages for ln in lines)


def test_running_headers_need_three_pages():
    assert running_line_keys({1: "머리\n본문", 2: "머리\n본문2"}) == set()


def test_short_pages_keep_number_only_differences():
    """줄이 몇 안 되는 쪽은 가장자리가 곧 본문이다 — 숫자만 다른 본문 줄을 머리글로 빼지 않는다."""
    pages = {n: f"측정값 {n}0\n결과를 적는다 {n}" for n in range(1, 4)}
    assert running_line_keys(pages) == set()


# ── 쓰기 방향 ───────────────────────────────────────────


def test_page_directions_plan_then_ocr_then_guess(tmp_path):
    doc = tmp_path / "d1"
    (doc / "L2_ocr").mkdir(parents=True)
    (doc / "L2_ocr" / "vol1_page_002.json").write_text(
        json.dumps(
            {"ocr_results": [{"writing_direction": "horizontal_ltr", "lines": [{"text": "漢文"}]}]}
        ),
        encoding="utf-8",
    )
    plan = {
        "ranges": [{"pages": "1", "rotation": 0, "engine": "ndlocr", "writing": "vertical_rtl"}]
    }
    texts = {1: "한글 세로쓰기", 2: "漢文", 3: "한글이 많은 쪽", 4: "漢文漢文漢文"}
    hz, used = page_directions(doc, "vol1", texts, plan)
    assert hz == {1: False, 2: True, 3: True, 4: False}
    assert used == {"plan": 1, "ocr": 1, "guess": 2}
