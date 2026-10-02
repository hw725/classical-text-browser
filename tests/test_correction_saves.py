"""교정 탭 «글자 교정» 보기 — 자유 편집이 만든 교정을 그대로 그리는가 (2026-10-02 사고).

왜 이 시험이 필요한가:
    자유 편집으로 고치고 저장하면 서버가 원문과 diff해 교정 목록을 만든다
    (`core.document._diff_to_corrections`). 그 교정은 넣기(원문 "")·지우기(교정 "")·
    여러 글자와 줄바꿈을 한꺼번에 바꾸기다. 그런데 「글자 교정」 보기는 «교정의
    첫 글자 자리에서 그 글자 하나만 바꿔 그리기»만 할 줄 알았다. 저장은 됐는데
    교정 탭을 다시 열면 기본 보기인 글자 교정이 원문을 거의 그대로 보여 줘서
    «교정 전으로 되돌아갔다»로 보였다.

    이 시험은 서버가 실제로 만드는 교정으로 화면 함수를 돌려, **보이는 글 = 교정본**인지
    잰다. 화면 쪽 글 만들기(`_applyCorrectionsLocally`, 모드 전환 때 쓴다)도 서버와 같은지 본다.
"""

from __future__ import annotations

import json

import pytest

from core.document import _apply_corrections_to_text, _diff_to_corrections
from tests.js_harness import run_js

# ruff: noqa: E501 — 스텁 JS를 그대로 넣은 문자열이라 줄 길이 규칙을 이 파일에서는 끈다

JS = "correction-editor.js"

# _renderCharsIntoElement 가 쓰는 만큼만 흉내 낸 DOM.
# 마지막에 «사람 눈에 보이는 글»을 꺼낸다 — br은 줄바꿈, 지운 표시(.corr-deleted)는 뺀다.
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
globalThis.document = {
  createElement: (t) => new El(t),
  createTextNode: (s) => ({ tag: "#text", text: s }),
};
globalThis.CORRECTION_TYPES = {};
function visible(n) {
  if (n.tag === "#text") return n.text;
  if (n.tag === "br") return "\n";
  if (n._cls && n._cls.has("corr-deleted")) return "";
  if (n._text != null) return n._text;
  return n.children.map(visible).join("");
}
"""

CASES = [
    # 실제 사고 쪽(舊注蒙求攷異提要 2쪽)의 첫머리 — 넣기·줄바꿈 지우기·여러 줄 바꾸기·□ 바꾸기
    (
        "春\n発\n免\n戌\n甲\n六月\n雁斎先生閲\n□□□\n勵風館蔵",
        "文化甲戌春発兌\n雁斎先生閲\n旧注蒙求\n勵風館蔵",
    ),
    ("一二三四五", "一二三四五六七"),  # 끝에 넣기
    ("一二三四五", "三四五"),  # 앞을 지우기
    ("甲乙\n丙丁", "甲乙丙丁"),  # 줄바꿈만 지우기
    ("甲乙丙丁", "甲乙\n丙丁"),  # 줄바꿈 넣기
    ("天地玄黃", "天地元黃"),  # 글자 하나 바꾸기(예전에도 되던 것)
]


@pytest.mark.parametrize("original,corrected", CASES)
def test_char_view_shows_the_freetext_result(tmp_path, original, corrected):
    corrs = _diff_to_corrections(original, corrected, 2)
    # 시험의 전제: 서버가 이 교정으로 같은 글을 만든다
    assert _apply_corrections_to_text(original, corrs) == corrected

    setup = FAKE_DOM + (
        f"globalThis.correctionState = {{ pageText: {json.dumps(original, ensure_ascii=False)}, "
        f"corrections: {json.dumps(corrs, ensure_ascii=False)} }};\n"
    )
    body = (
        "const root = new El('div');\n"
        "_renderCharsIntoElement(root, correctionState.pageText, 0, null);\n"
        "console.log(JSON.stringify({ shown: visible(root), "
        "local: _applyCorrectionsLocally(correctionState.pageText, correctionState.corrections) }));"
    )
    out = run_js(
        tmp_path, JS, ["_renderCharsIntoElement", "_flatCorrectionLayout", "_onCharClick", "_applyCorrectionsLocally"], setup, body
    )
    assert out["shown"] == corrected, "글자 교정 보기가 교정본과 다르다 — 저장한 교정이 «안 된 것처럼» 보인다"
    assert out["local"] == corrected, "모드 전환 때 화면이 만드는 글이 서버 교정본과 다르다"


# ── 확정본을 다시 써도 사람 교정이 남는가 ──
#
# 확정본(L4_text/pages)을 다시 쓰는 길(OCR 채우기·텍스트레이어 가져오기·LLM 교정 적용·
# 일괄 교정·열람 탭 저장)은 모두 save_page_text를 지난다. 예전에는 교정 파일을 그대로 두어
# 교정이 조용히 안 먹거나, 저장된 교정본이 새 확정본을 통째로 가렸다.


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
    """교정 탭 «자유 편집 → 저장»과 같은 일(라우트 api_save_page_corrections의 자유 편집 분기)."""
    from core.document import get_page_text, save_page_corrections

    base = get_page_text(doc, "vol1", 1)["text"]
    save_page_corrections(
        doc, "vol1", 1,
        {"part_id": "vol1", "corrected_text": corrected, "corrections": _diff_to_corrections(base, corrected, 1)},
    )


def test_machine_rewrite_keeps_freetext_correction(tmp_path):
    """OCR을 다시 채워 확정본이 바뀌어도 사람이 고친 자리는 사람 글이 남고, 기계가 고친 다른 자리는 들어온다."""
    from core.document import get_corrected_text, save_page_text

    doc = _doc(tmp_path, "天地玄黃\n宇宙洪荒\n日月盈昃")
    _freetext_save(doc, "天地玄黃\n宇宙洪荒之\n日月盈昃")  # 사람: 둘째 줄 끝에 之 넣기
    save_page_text(doc, "vol1", 1, "天地元黃\n宇宙洪荒\n日月盈仄")  # 기계: 玄→元, 昃→仄
    got = get_corrected_text(doc, "vol1", 1)["corrected_text"]
    assert got == "天地元黃\n宇宙洪荒之\n日月盈仄"


@pytest.mark.parametrize(
    "base,human,machine,want",
    [
        # 사람 고침이 기계가 넓게 바꾼 구간 안에 있으면 그 구간은 사람 판 — 사람이 둔 C가 남는다
        ("ABCDE", "AbCdE", "AXYZE", "AbCdE"),
        ("ABCDE", "AbcDE", "ABXYE", "AbcDE"),
        # 둘이 같은 글자를 같은 자리에 넣으면 한 번만
        ("AB", "AXB", "AXB", "AXB"),
        ("天地黃", "天地玄黃", "天地玄黃宇", "天地玄黃宇"),
        # 빈 쪽을 사람이 옮겨 적은 뒤 OCR이 채우면 사람 글이 남는다(겹쳐 붙지 않는다)
        ("", "HUMAN", "OCRTEXT", "HUMAN"),
        # 서로 다른 자리는 둘 다 산다
        ("一二三四五六", "壹二三四五六", "一二三四五陸", "壹二三四五陸"),
    ],
)
def test_three_way_merge(base, human, machine, want):
    from core.document import _three_way

    assert _three_way(base, human, machine) == want


def test_insert_at_same_spot_keeps_both_once(tmp_path):
    """사람과 기계가 같은 자리(맨 앞)에 서로 다른 글을 넣기만 했으면 둘 다 — 기계 앞, 사람 뒤."""
    from core.document import get_corrected_text, save_page_text

    doc = _doc(tmp_path, "春\n発")
    _freetext_save(doc, "文化甲戌春発")  # 사람: 앞에 넣고 줄바꿈 지우기
    save_page_text(doc, "vol1", 1, "序\n春\n発")  # 기계: 맨 앞에 序 줄
    assert get_corrected_text(doc, "vol1", 1)["corrected_text"] == "序\n文化甲戌春発"


def test_stale_records_become_history_not_deleted(tmp_path):
    """옛 글에 맞지 않는 항목(일괄 교정의 «이미 반영» 기록)은 지우지 않고 다시 적용되지 않게 남긴다."""
    from core.document import apply_batch_corrections, get_corrected_text, save_page_text

    doc = _doc(tmp_path, "玄黃玄")
    apply_batch_corrections(doc, "vol1", 1, 1, "玄", "元")
    save_page_text(doc, "vol1", 1, "元黃元\n宇宙")
    data = json.loads((doc / "L4_text/corrections/vol1_page_001_corrections.json").read_text(encoding="utf-8"))
    batch = [c for c in data["corrections"] if c["corrected_by"] == "human_batch"]
    assert len(batch) == 2 and all(c["char_index"] is None for c in batch)
    assert get_corrected_text(doc, "vol1", 1)["corrected_text"] == "元黃元\n宇宙"


def test_broken_corrections_file_does_not_block_text_write(tmp_path):
    from core.document import get_page_text, save_page_text

    doc = _doc(tmp_path, "甲")
    p = doc / "L4_text/corrections/vol1_page_001_corrections.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{깨진", encoding="utf-8")
    r = save_page_text(doc, "vol1", 1, "乙")
    assert get_page_text(doc, "vol1", 1)["text"] == "乙" and "corrections_rebase_error" in r


def test_human_wins_where_both_changed(tmp_path):
    from core.document import get_corrected_text, save_page_text

    doc = _doc(tmp_path, "□□三四五")
    _freetext_save(doc, "一二三四五")  # 사람: □□ → 一二
    save_page_text(doc, "vol1", 1, "壹貳三四五")  # 기계도 같은 자리를 다르게 읽음
    assert get_corrected_text(doc, "vol1", 1)["corrected_text"] == "一二三四五"


def test_char_corrections_follow_shifted_text(tmp_path):
    """글자 교정(교정본 저장 없음)도 앞에 글이 늘어 자리가 밀리면 따라간다."""
    from core.document import get_corrected_text, save_page_corrections, save_page_text

    doc = _doc(tmp_path, "甲乙丙丁")
    save_page_corrections(doc, "vol1", 1, {"part_id": "vol1", "corrections": [
        {"page": 1, "block_id": None, "line": None, "char_index": 2, "type": "variant_char",
         "original_ocr": "丙", "corrected": "昞", "corrected_by": "human", "confidence": 0.9, "note": "피휘"},
    ]})
    save_page_text(doc, "vol1", 1, "序\n甲乙丙丁")
    out = get_corrected_text(doc, "vol1", 1)
    assert out["corrected_text"] == "序\n甲乙昞丁"
    corrs = json.loads((doc / "L4_text/corrections/vol1_page_001_corrections.json").read_text(encoding="utf-8"))["corrections"]
    assert corrs[0]["type"] == "variant_char" and corrs[0]["note"] == "피휘", "유형·비고가 옮겨 오지 않았다"


def test_batch_correction_keeps_freetext_result(tmp_path):
    """일괄 교정이 자유 편집 교정본을 지우던 것."""
    from core.document import apply_batch_corrections, get_corrected_text

    doc = _doc(tmp_path, "玄玄\n□□")
    _freetext_save(doc, "玄玄\n天地")
    apply_batch_corrections(doc, "vol1", 1, 1, "玄", "元")
    assert get_corrected_text(doc, "vol1", 1)["corrected_text"] == "元元\n天地"
