"""주석 편집기 화면 JS — 확장 한자 좌표·사전 펼침 이스케이프·저장 실패 알림 (Codex 교차검증 2026-09-16 ③·⑤·⑩).

왜 이 시험이 필요한가:
    ③ 서버(Python)는 글자를 코드포인트로 세고 화면(JS)은 `.length`·`[i]`·`.slice`로 UTF-16 단위를
       셌다. 확장 한자(𠀀 같은 CJK 확장 B, 서로게이트 쌍)가 앞에 하나만 있어도 그 뒤 주석이 한 칸
       어긋나고, 한자가 반으로 갈린 서로게이트가 화면에 찍힌다.
    ⑤ 사전 펼침 카드가 표제어·뜻·해설을 이스케이프 없이 innerHTML에 넣었다 — LLM·가져오기 문자열이다.
    ⑩ 사전 편집 저장이 4xx/5xx·네트워크 실패를 콘솔에만 남겨 사용자는 저장된 줄 알았다.
"""

from __future__ import annotations

import pytest

from tests.js_harness import run_js

# ruff: noqa: E501 — 스텁·본문 JS를 그대로 넣은 문자열이라 줄 길이 규칙을 이 파일에서는 끈다

JS = "annotation-editor.js"

# ── 최소 DOM 스텁: 만든 요소와 텍스트만 기억한다 ──
FAKE_DOM = r"""
function _el() {
  const e = { children: [], style: {}, dataset: {}, _text: "", listeners: {}, className: "", title: "" };
  e.addEventListener = (n, f) => { e.listeners[n] = f; };
  e.appendChild = (c) => { e.children.push(c); };
  Object.defineProperty(e, "textContent", { get() { return e._text; }, set(v) { e._text = String(v); } });
  Object.defineProperty(e, "innerHTML", { get() { return e._html || ""; }, set(v) { e._html = String(v); e.children = []; } });
  return e;
}
const container = _el();
globalThis.document = {
  getElementById: (id) => (id === "ann-source-text" ? container : null),
  createElement: () => _el(),
};
function _getTypeInfo() { return { color: "#ff0000", icon: "★", label: "인물" }; }
function _selectAnnotation() {}
function _onTextSelection() {}
"""

ASTRAL = "𠀀甲乙"  # 𠀀 = U+20000, JS에서는 서로게이트 두 단위


@pytest.fixture
def render_state():
    return (
        FAKE_DOM
        + """
globalThis.annState = {
  originalText: %r,
  punctMarks: [{ target: { start: 0, end: 0 }, before: null, after: "。" }],
  annotations: [{ id: "a1", type: "person", target: { start: 1, end: 1 },
                  content: { label: "甲", description: "" }, status: "draft" }],
};
"""
        % ASTRAL
    )


def test_highlight_covers_the_code_point_not_a_surrogate_half(tmp_path, render_state):
    """서버 좌표 [1,1]은 «甲»이다. 화면도 甲을 칠해야 한다."""
    out = run_js(
        tmp_path,
        JS,
        ["_renderSourceText", "_getAnnotationTooltip"],
        render_state,
        """
_renderSourceText();
const spans = container.children.map((c) => ({ text: c._text, ann: c.dataset.annId || null }));
console.log(JSON.stringify({ spans }));
""",
    )
    spans = out["spans"]
    highlighted = [s for s in spans if s["ann"] == "a1"]
    assert highlighted == [{"text": "甲", "ann": "a1"}], spans
    assert "".join(s["text"] for s in spans) == "𠀀。甲乙"


def test_punctuate_slice_uses_code_points(tmp_path, render_state):
    out = run_js(
        tmp_path,
        JS,
        ["_punctuateSlice"],
        render_state,
        """
console.log(JSON.stringify({ one: _punctuateSlice(1, 1), zero: _punctuateSlice(0, 0), all: _punctuateSlice(0, 2) }));
""",
    )
    assert out == {"one": "甲", "zero": "𠀀。", "all": "𠀀。甲乙"}


def test_selection_display_offsets_map_to_code_point_indices(tmp_path, render_state):
    """DOM Range가 준 «선택 앞 표시 문자열»·«선택 끝까지 표시 문자열» → 원문 코드포인트 범위."""
    out = run_js(
        tmp_path,
        JS,
        ["_annDisplayRangeToOriginal", "_annDisplayOffsetToOriginal"],
        render_state,
        """
const r1 = _annDisplayRangeToOriginal("𠀀。", "𠀀。甲", annState.originalText, annState.punctMarks);
const r2 = _annDisplayRangeToOriginal("", "𠀀。甲乙", annState.originalText, annState.punctMarks);
const r3 = _annDisplayRangeToOriginal("𠀀。甲", "𠀀。甲乙", annState.originalText, annState.punctMarks);
console.log(JSON.stringify({ r1, r2, r3 }));
""",
    )
    assert out["r1"] == {"startIdx": 1, "endIdx": 1, "actualText": "甲"}
    assert out["r2"] == {"startIdx": 0, "endIdx": 2, "actualText": "𠀀甲乙"}
    assert out["r3"] == {"startIdx": 2, "endIdx": 2, "actualText": "乙"}


def test_ai_range_helpers_count_code_points(tmp_path):
    """AI 태깅 좌표 보정도 같은 자(코드포인트)를 써야 서버 좌표와 맞는다."""
    out = run_js(
        tmp_path,
        JS,
        [
            "_buildAiRangeIndexMap",
            "_AI_RANGE_IGNORABLE_CHAR_RE",
            "_splitIntoSentences",
            "_composePunctuatedTextForAi",
        ],
        "",
        """
const m = _buildAiRangeIndexMap("𠀀甲乙");
const s = _splitIntoSentences("𠀀甲乙丙", [{ target: { start: 1, end: 1 }, after: "。" }]);
console.log(JSON.stringify({ stripped: Array.from(m.strippedText), toOriginal: m.strippedToOriginal,
  sentences: s.map((x) => [x.origStart, x.origEnd, x.text]) }));
""",
    )
    assert out["stripped"] == ["𠀀", "甲", "乙"]
    assert out["toOriginal"] == [0, 1, 2]
    assert out["sentences"] == [[0, 1, "𠀀甲"], [2, 3, "乙丙"]]


# ── ⑤ 사전 펼침 이스케이프 ──


def test_dict_expanded_escapes_every_string_field(tmp_path):
    out = run_js(
        tmp_path,
        JS,
        ["_DICT_CATEGORY_LABELS", "_escHtml", "_renderDictExpanded"],
        "globalThis._dictViewExpanded = true;",
        """
const html = _renderDictExpanded({ dictionary: {
  headword: "<img src=x onerror=alert(1)>", headword_reading: "<b>r</b>",
  dictionary_meaning: "<i>m</i>", contextual_meaning: "<u>c</u>",
  sense_note: "<img src=y onerror=alert(2)>",
  source_references: [{ title: "<s>t</s>", section: "<em>s</em>" }],
  related_terms: ["<strong>x</strong>"], category: "<script>", scope: "this_text_unit",
}});
console.log(JSON.stringify({ html }));
""",
    )
    html = out["html"]
    # 카드 골격의 <b>사전적 의미:</b>는 코드가 쓴 것 — 들어온 문자열의 태그만 본다
    injected = (
        "<img",
        "<b>r</b>",
        "<i>m</i>",
        "<u>c</u>",
        "<s>t</s>",
        "<em>s</em>",
        "<strong>x</strong>",
        "<script>",
    )
    for raw in injected:
        assert raw not in html, f"{raw!r}가 그대로 들어갔다: {html}"
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "이 글에서만" in html


# ── ⑩ 저장 실패 알림 ──

SAVE_STUBS = r"""
globalThis.annState = { selectedAnnId: "a1", blockId: "b1" };
globalThis.viewerState = { pageNum: 1 };
globalThis.interpState = { interpId: "i1" };
globalThis.document = { getElementById: () => ({ value: "王戎" }) };
globalThis.toasts = []; globalThis.statuses = [];
globalThis.showToast = (m, k) => toasts.push([m, k]);
globalThis._showSaveStatus = (m) => statuses.push(m);
globalThis._loadBlockAnnotations = async () => {};
globalThis._renderAnnList = () => {};
globalThis._annPartQuery = () => "";
console.error = () => {};
"""


def test_dict_save_http_error_is_shown_to_user(tmp_path):
    out = run_js(
        tmp_path,
        JS,
        ["_annApiBlockId", "_saveDictFields"],
        SAVE_STUBS
        + """
globalThis.fetch = async () => ({ ok: false, status: 500, json: async () => ({ error: "디스크 오류" }) });
""",
        """
await _saveDictFields();
console.log(JSON.stringify({ toasts, statuses }));
""",
    )
    errors = [t for t in out["toasts"] if t[1] == "error"]
    assert errors and "디스크 오류" in errors[0][0], out
    assert not any("완료" in s for s in out["statuses"]), out


def test_dict_save_network_failure_is_shown_to_user(tmp_path):
    out = run_js(
        tmp_path,
        JS,
        ["_annApiBlockId", "_saveDictFields"],
        SAVE_STUBS
        + """
globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
""",
        """
await _saveDictFields();
console.log(JSON.stringify({ toasts, statuses }));
""",
    )
    errors = [t for t in out["toasts"] if t[1] == "error"]
    assert errors and "Failed to fetch" in errors[0][0], out
