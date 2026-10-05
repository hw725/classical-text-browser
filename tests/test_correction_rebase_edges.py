"""확정본을 다시 쓸 때 사람 교정을 옮겨 붙이는 병합(D-133)의 가장자리 — 2026-10-05 검토 지적.

왜 이 시험이 필요한가:
    D-133은 «겹친 자리는 사람이 이긴다»로 사람 교정을 지켰다. 검토 탐침이 그 규칙의 가장자리 넷을 잡았다.

    1. OCR을 다시 돌려 쪽 글이 통째로 바뀌었는데(옛 `ABCDEFGH` → 새 `PQRSTUVW`) 사람이 한 글자를
       고쳐 두었으면, 겹친 묶음이 쪽 전체라 «사람 판»이 옛 글 전체를 되살렸다. 열람 탭(새 글)과
       교정 탭·내보내기(옛 글)가 서로 다른 글을 보였고, 새 OCR은 아무 말 없이 버려졌다.
       실제 서고의 재OCR 쌍(배치가 바뀐 쪽)에서는 한 글자 고침이 옛 글 수백 자를 되살렸다.
    2. 기계가 지운 범위의 끝에 사람이 넣은 글이 엉뚱한 줄 뒤에 붙었다(`…IJKL`+`M` → `ABCDM`).
    3. 같은 자리에 사람 `之`, 기계 `之也`를 넣으면 `之也之`가 됐다.
    4. 같은 자리의 «넣기»와 «바꾸기»를 [넣기, 바꾸기] 순서로 두면 서버는 바꾸기를 건너뛰고,
       화면(글자 교정 보기)은 둘 다 그렸다 — 보이는 글과 내보내는 글이 달랐다.

    그리고 사람이 모르면 고친 것이 닿지 않는다 — 확정본을 다시 쓰는 화면 경로가 «옮겼다/못 옮겼다»를
    알리는지도 본다.
"""

from __future__ import annotations

import json

import pytest

from core.document import _apply_corrections_to_text, _diff_to_corrections
from tests.js_harness import run_js

# ruff: noqa: E501 — 스텁 JS 문자열


def _doc(tmp_path, base: str):
    from core.document import save_page_text

    doc = tmp_path / "doc"
    doc.mkdir()
    (doc / "manifest.json").write_text(
        json.dumps({"document_id": "doc", "parts": [{"part_id": "vol1"}]}), encoding="utf-8"
    )
    save_page_text(doc, "vol1", 1, base)
    return doc


def _freetext_save(doc, corrected: str):
    """교정 탭 «자유 편집 → 저장»과 같은 일."""
    from core.document import get_page_text, save_page_corrections

    base = get_page_text(doc, "vol1", 1)["text"]
    save_page_corrections(
        doc,
        "vol1",
        1,
        {
            "part_id": "vol1",
            "corrected_text": corrected,
            "corrections": _diff_to_corrections(base, corrected, 1),
        },
    )


def _corr_file(doc):
    return json.loads(
        (doc / "L4_text/corrections/vol1_page_001_corrections.json").read_text(encoding="utf-8")
    )


# ── 1. 새 글이 옛 글과 맞춰 볼 수 없으면 병합하지 않고 기록으로 옮긴다 ──


def test_whole_page_reocr_does_not_resurrect_old_text():
    from core.document import _three_way

    assert _three_way("ABCDEFGH", "ABXDEFGH", "PQRSTUVW") == "PQRSTUVW"


def test_whole_page_reocr_moves_freetext_correction_to_history(tmp_path):
    from core.document import get_corrected_text, save_page_text

    doc = _doc(tmp_path, "ABCDEFGH")
    _freetext_save(doc, "ABXDEFGH")
    r = save_page_text(doc, "vol1", 1, "PQRSTUVW")
    # 교정 탭·내보내기가 보는 글 = 새 확정본 (옛 글을 되살리지 않는다)
    assert get_corrected_text(doc, "vol1", 1)["corrected_text"] == "PQRSTUVW"
    # 사람 교정은 지우지 않고 기록으로 남는다 — 다시 적용되지 않게 char_index 없음
    hist = [c for c in _corr_file(doc)["corrections"] if c["char_index"] is None]
    assert [(c["original_ocr"], c["corrected"]) for c in hist] == [("C", "X")]
    assert "옛 확정본" in (hist[0]["note"] or "")
    # 그 사실을 응답이 알린다
    assert r["corrections_unmerged"]["count"] == 1


def test_unmerged_char_correction_keeps_type_and_note(tmp_path):
    from core.document import save_page_corrections, save_page_text

    doc = _doc(tmp_path, "甲乙丙丁戊己")
    save_page_corrections(
        doc,
        "vol1",
        1,
        {
            "part_id": "vol1",
            "corrections": [
                {
                    "page": 1,
                    "block_id": None,
                    "line": None,
                    "char_index": 2,
                    "type": "variant_char",
                    "original_ocr": "丙",
                    "corrected": "昞",
                    "corrected_by": "human",
                    "confidence": 0.9,
                    "note": "피휘",
                },
            ],
        },
    )
    r = save_page_text(doc, "vol1", 1, "子丑寅卯辰巳午")
    hist = [c for c in _corr_file(doc)["corrections"] if c["char_index"] is None]
    assert len(hist) == 1 and hist[0]["type"] == "variant_char" and hist[0]["corrected"] == "昞"
    assert "피휘" in hist[0]["note"], "옛 비고가 사라졌다"
    assert r["corrections_unmerged"]["count"] == 1


def test_moved_line_does_not_duplicate_old_line(tmp_path):
    """새 OCR이 줄 순서를 바꿨는데 사람이 옮겨진 줄을 고쳐 두었다 — 옛 줄을 되살려 같은 줄이 두 번 나오면 안 된다."""
    from core.document import get_corrected_text, save_page_text

    a, b = "天地玄黃宇宙洪荒", "日月盈昃辰宿列張"
    doc = _doc(tmp_path, f"{a}\n{b}")
    _freetext_save(doc, f"{a.replace('玄', '元')}\n{b}")  # 사람: 첫 줄 玄→元
    new = f"{b}\n{a}"  # 기계: 두 줄 순서를 바꿔 읽음
    r = save_page_text(doc, "vol1", 1, new)
    got = get_corrected_text(doc, "vol1", 1)["corrected_text"]
    assert len(got) == len(new), f"옛 줄이 되살아나 글이 늘었다: {got!r}"
    assert r.get("corrections_unmerged", {}).get("count", 0) >= 1 or "元" in got


def test_small_reocr_still_merges(tmp_path):
    """새 글이 옛 글과 대부분 같으면(보통의 재OCR) 지금처럼 옮겨 붙인다 — 알림도 «옮겼다»."""
    from core.document import get_corrected_text, save_page_text

    doc = _doc(tmp_path, "天地玄黃宇宙洪荒日月盈昃")
    _freetext_save(doc, "天地玄黄宇宙洪荒日月盈昃")
    r = save_page_text(doc, "vol1", 1, "天也玄黃字宙洪荒曰月盈仄")
    assert get_corrected_text(doc, "vol1", 1)["corrected_text"] == "天也玄黄字宙洪荒曰月盈仄"
    assert "corrections_unmerged" not in r and r["corrections_rebased"]["kept"] == 1


# ── 2. 지운 범위 경계에 붙은 넣기는 겹친 것이다 ──


def test_insert_after_deleted_tail_is_not_glued_to_wrong_line(tmp_path):
    from core.document import _three_way, get_corrected_text, save_page_text

    got = _three_way("ABCDEFGH\nIJKL", "ABCDEFGH\nIJKLM", "ABCD")
    assert got != "ABCDM", "사람이 IJKL 뒤에 넣은 M이 ABCD 뒤에 붙었다"

    doc = _doc(tmp_path, "ABCDEFGH\nIJKL")
    _freetext_save(doc, "ABCDEFGH\nIJKLM")
    r = save_page_text(doc, "vol1", 1, "ABCD")
    assert get_corrected_text(doc, "vol1", 1)["corrected_text"] == got
    hist = [c for c in _corr_file(doc)["corrections"] if c["char_index"] is None]
    assert any(c["corrected"] == "M" for c in hist) and r["corrections_unmerged"]["count"] == 1


@pytest.mark.parametrize(
    "base,human,machine,want",
    [
        # 지운 한 글자의 바로 뒤(끝 경계)에 넣음 — 겹친 것 → 사람 판
        ("ABCDE", "ABCXDE", "ABDE", "ABCXDE"),
        # 지운 한 글자의 바로 앞(시작 경계)에 넣음 — 겹친 것 → 사람 판
        ("ABCDE", "ABXCDE", "ABDE", "ABXCDE"),
        # 바꾸기 경계의 넣기는 여전히 둘 다 산다(이웃한 고침)
        ("ABCDE", "ABCXDE", "ABYDE", "ABYXDE"),
    ],
)
def test_insert_at_deletion_boundary_conflicts(base, human, machine, want):
    from core.document import _three_way

    assert _three_way(base, human, machine) == want


# ── 3. 같은 자리 넣기 — 한쪽이 다른 쪽의 앞·뒤 조각이면 긴 쪽 하나 ──


@pytest.mark.parametrize(
    "human,machine,want",
    [
        ("AB之CD", "AB之也CD", "AB之也CD"),  # 사람 것이 기계 것의 앞 조각
        ("AB之也CD", "AB之CD", "AB之也CD"),  # 기계 것이 사람 것의 앞 조각
        ("AB之CD", "AB也之CD", "AB也之CD"),  # 뒤 조각
        ("AB之CD", "AB也CD", "AB也之CD"),  # 서로 다르면 지금처럼 둘 다(기계 앞)
    ],
)
def test_same_spot_insert_prefix_not_duplicated(human, machine, want):
    from core.document import _three_way

    assert _three_way("ABCD", human, machine) == want


# ── 4. 같은 자리 «넣기»+«바꾸기» — 서버·화면 글 만들기·글자 교정 보기가 같아야 한다 ──

INS = {
    "page": 1,
    "block_id": None,
    "line": None,
    "char_index": 2,
    "type": "ocr_error",
    "original_ocr": "",
    "corrected": "X",
}
REP = {
    "page": 1,
    "block_id": None,
    "line": None,
    "char_index": 2,
    "type": "ocr_error",
    "original_ocr": "C",
    "corrected": "Y",
}
INS2 = {**INS, "corrected": "Q"}

ORDER_CASES = [
    ([INS, REP], "ABXYDEF"),
    ([REP, INS], "ABXYDEF"),
    ([INS, INS2], "ABXQCDEF"),  # 같은 자리 넣기 둘은 목록 순서대로
]

FAKE_DOM = r"""
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.title = "";
    this._cls = new Set(); this._text = null;
    const self = this;
    this.classList = { add: (...c) => c.forEach((x) => x && self._cls.add(x)), contains: (c) => self._cls.has(c) };
  }
  set className(v) { this._cls = new Set(String(v).split(/\s+/).filter(Boolean)); }
  set textContent(v) { this._text = v; this.children = []; }
  appendChild(c) { this.children.push(c); return c; }
  addEventListener() {}
}
globalThis.document = { createElement: (t) => new El(t), createTextNode: (s) => ({ tag: "#text", text: s }) };
globalThis.CORRECTION_TYPES = {};
function visible(n) {
  if (n.tag === "#text") return n.text;
  if (n.tag === "br") return "\n";
  if (n._cls && n._cls.has("corr-deleted")) return "";
  if (n._text != null) return n._text;
  return n.children.map(visible).join("");
}
"""


@pytest.mark.parametrize("corrs,want", ORDER_CASES)
def test_server_apply_order_matches_screen(tmp_path, corrs, want):
    assert _apply_corrections_to_text("ABCDEF", corrs) == want
    setup = FAKE_DOM + (
        f"globalThis.correctionState = {{ pageText: 'ABCDEF', corrections: {json.dumps(corrs)} }};\n"
    )
    body = (
        "const root = new El('div');\n"
        "_renderCharsIntoElement(root, 'ABCDEF', 0, null);\n"
        "console.log(JSON.stringify({ shown: visible(root), local: _applyCorrectionsLocally('ABCDEF', correctionState.corrections) }));"
    )
    out = run_js(
        tmp_path,
        "correction-editor.js",
        [
            "_renderCharsIntoElement",
            "_flatCorrectionLayout",
            "_onCharClick",
            "_applyCorrectionsLocally",
        ],
        setup,
        body,
    )
    assert out["shown"] == want, "글자 교정 보기"
    assert out["local"] == want, "모드 전환 때 화면이 만드는 글"


# ── 5. 알림 — 응답에 실리고, 화면 도우미가 읽어 사람에게 보인다 ──


def test_batch_correction_reports_rebase_per_page(tmp_path):
    from core.document import apply_batch_corrections

    doc = _doc(tmp_path, "玄玄\n□□")
    _freetext_save(doc, "玄玄\n天地")
    r = apply_batch_corrections(doc, "vol1", 1, 1, "玄", "元")
    notes = r.get("corrections_notices") or []
    assert notes and notes[0]["page"] == 1 and notes[0]["rebased"]["kept"] == 1


def test_notify_helper_shows_toasts(tmp_path):
    setup = "globalThis.toasts = [];\nglobalThis.showToast = (m, t) => toasts.push({m, t});\n"
    body = (
        "notifyCorrectionsRebase({corrections_rebased: {kept: 2, history: 0}});\n"
        "notifyCorrectionsRebase({corrections_rebased: {kept: 0, history: 1}, corrections_unmerged: {count: 1, similarity: 0.0}});\n"
        "notifyCorrectionsRebase({corrections_rebase_error: 'JSONDecodeError: x'});\n"
        "notifyCorrectionsRebase({corrections_notices: [{page: 3, unmerged: {count: 2}}, {page: 5, rebased: {kept: 1, history: 0}}]});\n"
        "notifyCorrectionsRebase({status: 'saved'});\n"
        "console.log(JSON.stringify({toasts}));"
    )
    out = run_js(tmp_path, "workspace.js", ["notifyCorrectionsRebase"], setup, body)
    ts = out["toasts"]
    assert len(ts) == 5, ts  # 마지막 «저장됨»만 있는 응답은 아무것도 띄우지 않는다
    assert ts[0]["t"] == "info" and "2건" in ts[0]["m"]
    assert ts[1]["t"] == "warning" and "기록" in ts[1]["m"]
    assert ts[2]["t"] == "error"
    assert ts[3]["t"] == "warning" and ts[3]["m"].startswith("3쪽") and "2건" in ts[3]["m"]
    assert ts[4]["t"] == "info" and ts[4]["m"].startswith("5쪽")


# ── 6. 알림이 없던 경로(2026-10-06) ──
#
# 6206fc0은 열람 탭 저장·OCR 패널 저장·LLM 교정 적용·일괄 교정·텍스트레이어 가져오기에 알림을 달았다.
# 그런데 확정본 채우기(fill-text)·권 전체 OCR(일괄·작업 계획)·CLI 작업 계획 OCR·강독 결과 들이기·
# HWP 가져오기는 save_page_text의 쪽별 응답을 버려, 교정이 «기록»으로 옮겨져도 사람이 몰랐다.
# 앞의 셋은 실제 병합으로, 들이기·일괄 OCR은 «못 옮김»을 돌려주는 저장으로 바꿔 끼워 응답까지 본다.

from tests.test_lite_mode_api import _sse_events, batch_ready, isolated_app  # noqa: E402, F401
from tests.test_read_plan import NOTE, PLAN, _setup, client  # noqa: E402, F401


def _lib_doc(tmp_path, base: str):
    """서고 아래 문헌 하나(1쪽, 확정본 base) — 서고 경로를 받는 함수·라우트용."""
    from core.document import save_page_text

    lib = tmp_path / "lib"
    doc = lib / "documents" / "doc"
    doc.mkdir(parents=True)
    (doc / "manifest.json").write_text(
        json.dumps({"document_id": "doc", "parts": [{"part_id": "vol1", "page_count": 1}]}),
        encoding="utf-8",
    )
    save_page_text(doc, "vol1", 1, base)
    return lib, doc


def _write_l2(doc, text: str):
    p = doc / "L2_ocr" / "vol1_page_001.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"ocr_results": [{"layout_block_id": "b1", "lines": [{"text": text}]}]}),
        encoding="utf-8",
    )


def _saver_reporting_unmerged(monkeypatch):
    """진짜로 저장하되 «교정 2건을 못 옮겼다»를 덧붙여 돌려주는 save_page_text.

    경로마다 그 소식을 응답까지 싣는지만 본다(병합 자체는 위 시험들이 본다).
    호출부가 함수 안에서 `from core.document import save_page_text`로 부르므로 모듈 속성을 바꾼다.
    """
    import core.document as cd

    real = cd.save_page_text

    def fake(doc_path, part_id, page_num, text):
        out = real(doc_path, part_id, page_num, text)
        return {**out, "corrections_unmerged": {"count": 2, "similarity": 0.1}}

    monkeypatch.setattr(cd, "save_page_text", fake)


def test_fill_text_route_reports_rebase(tmp_path, monkeypatch):
    """확정본 채우기(OCR 결과 → L4)가 쪽마다 «교정 옮김» 소식을 돌려준다."""
    import asyncio

    from app.routers import llm_ocr

    lib, doc = _lib_doc(tmp_path, "ABCDEFGH")
    _freetext_save(doc, "ABXDEFGH")
    _write_l2(doc, "PQRSTUVW")
    monkeypatch.setattr(llm_ocr, "get_library_path", lambda: lib)
    r = asyncio.run(llm_ocr.api_fill_text_from_ocr("doc", "vol1", overwrite=True, pages="1"))
    assert r["filled"] == 1
    notes = r.get("corrections_notices") or []
    assert [n["page"] for n in notes] == [1] and notes[0]["unmerged"]["count"] == 1


def test_batch_ocr_complete_event_carries_notices(batch_ready, monkeypatch):  # noqa: F811
    """권 전체 OCR(작업 계획 OCR도 이 길)의 마지막 이벤트에 쪽별 소식이 실린다."""
    client_, doc_id, part_id = batch_ready
    _saver_reporting_unmerged(monkeypatch)
    events = _sse_events(
        client_.post(
            f"/api/documents/{doc_id}/parts/{part_id}/ocr/batch",
            json={"engine_id": "dummy", "pages": [1, 2]},
        )
    )
    done = events[-1]
    assert done["type"] == "complete", events
    notes = done.get("corrections_notices") or []
    assert [n["page"] for n in notes] == [1, 2]
    assert all(n["unmerged"]["count"] == 2 for n in notes)


def test_read_pages_cli_reports_rebase(tmp_path, monkeypatch):
    """CLI 작업 계획 OCR(`ctb read`)은 화면이 없으니 반환값에 싣는다."""
    import ocr.full_page_block as fpb
    from ocr import read_book

    doc = _doc(tmp_path, "ABCDEFGH")
    _freetext_save(doc, "ABXDEFGH")
    monkeypatch.setattr(fpb, "ensure_full_page_block", lambda *a, **k: None)
    monkeypatch.setattr(read_book, "l4_is_hand_edited", lambda *a: False)

    class _Result:
        def to_summary(self):
            return {"ocr_results": [{"layout_block_id": "b1", "lines": [{"text": "PQRSTUVW"}]}]}

    class _Pipeline:
        def run_page(self, **kw):
            return _Result()

    plan = [{"from": 1, "to": 1, "engine_id": "x", "writing_direction": "vertical_rtl"}]
    stats = read_book.read_pages(_Pipeline(), "doc", doc, "vol1", [1], plan, redo=True)
    assert stats["done"] == 1
    notes = stats.get("corrections_notices") or []
    assert [n["page"] for n in notes] == [1] and notes[0]["unmerged"]["count"] == 1


def test_reading_notes_route_reports_rebase(client, tmp_path, monkeypatch):  # noqa: F811
    """강독 결과 들이기가 L4 교정을 쓸 때 쪽별 소식을 응답에 싣는다."""
    _lib, part = _setup(client, tmp_path)
    r = client.put("/api/documents/d1/read-plan", json={"plan": PLAN, "part_id": part})
    assert r.status_code == 200, r.text
    _saver_reporting_unmerged(monkeypatch)
    answer = dict(
        NOTE, chapter="壹. 民事慣習回答彙集", corrections=[{"page": 3, "text": "民事慣習"}]
    )
    answer["sections"][0]["page"] = 3
    r = client.post("/api/documents/d1/reading-notes", json={"note": answer, "part_id": part})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["corrected"] == [3]
    notes = res.get("corrections_notices") or []
    assert [n["page"] for n in notes] == [3] and notes[0]["unmerged"]["count"] == 2


def test_hwp_import_reports_rebase(tmp_path, monkeypatch):
    """기존 문헌에 HWP 텍스트를 넣을 때 쪽별 소식을 돌려준다."""
    import hwp.reader as hr
    from core.document import import_hwp_text_to_document

    lib, doc = _lib_doc(tmp_path, "ABCDEFGH")
    _freetext_save(doc, "ABXDEFGH")

    class _Reader:
        def extract_sections(self):
            return [{"text": "PQRSTUVW"}]

    monkeypatch.setattr(hr, "get_reader", lambda f: _Reader())
    hwp_file = tmp_path / "x.hwpx"
    hwp_file.write_bytes(b"PK")
    r = import_hwp_text_to_document(lib, "doc", hwp_file)
    assert r["pages_saved"] == 1
    notes = r.get("corrections_notices") or []
    assert [n["page"] for n in notes] == [1] and notes[0]["unmerged"]["count"] == 1


def test_fill_empty_page_text_notifies(tmp_path):
    """교정 탭이 빈 확정본을 채울 때(fillEmptyPageText) 응답의 소식을 띄운다."""
    setup = (
        "globalThis._fillInFlight = new Map();\n"
        "globalThis.toasts = [];\nglobalThis.showToast = (m, t) => toasts.push({m, t});\n"
        "globalThis.seen = [];\nglobalThis.notifyCorrectionsRebase = (d) => seen.push(d);\n"
        "globalThis.fetch = async () => ({ok: true, json: async () => "
        "({filled: 1, corrections_notices: [{page: 4, unmerged: {count: 1}}]})});\n"
    )
    body = (
        "const filled = await fillEmptyPageText('d', 'vol1', 4);\n"
        "console.log(JSON.stringify({filled, seen, toasts}));"
    )
    out = run_js(tmp_path, "text-editor.js", ["fillEmptyPageText"], setup, body)
    assert out["filled"] is True
    assert out["seen"] and out["seen"][0]["corrections_notices"][0]["page"] == 4


@pytest.mark.parametrize(
    "js_file,func",
    [
        ("extract-panel.js", "refreshCorrectionReviewBar"),  # 「다음 미확인 쪽」 전에 채우기
        ("extract-panel.js", "_openPageInTab"),  # 「대조」 전에 채우기
        ("extract-panel.js", "_runExtractOcr"),  # 추출 모드 권 전체 OCR
        ("ocr-panel.js", "_runPartOcr"),  # 권 전체 OCR — 작업 계획(work-order.js)도 이 길
        ("export-view.js", "_cxImportNote"),  # 강독 결과 들이기
        ("hwp-import.js", "_executeHwpImport"),  # HWP 가져오기
    ],
)
def test_screen_callers_pass_response_to_notify(js_file, func):
    """확정본을 다시 쓰는 화면 호출부마다 응답을 notifyCorrectionsRebase에 넘긴다."""
    from tests.js_harness import STATIC_JS, extract_js

    src = extract_js((STATIC_JS / js_file).read_text(encoding="utf-8"), [func])
    assert "notifyCorrectionsRebase(" in src, f"{js_file}::{func}가 교정 옮김 소식을 버린다"
