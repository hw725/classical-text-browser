"""작업 화면 「모델」 칸이 새로고침 뒤에도 고른 모델을 기억한다 (D-143 보충, 2026-10-18).

무엇을 지키는가:
    설정에서 《자동》 기본 모델을 고르게 하면서(D-143), 작업 화면마다 있는 「모델」 칸(OCR·편성·
    표점·번역·주석·말로 지시·노트 틀)은 새로고침하면 늘 《자동》으로 돌아갔다. 그래서 《번역은 늘
    glm-5.2》처럼 작업마다 다른 모델을 쓰려면 매번 다시 골라야 했다(사용자 지적).
    1. 칸에서 고르면 그 칸의 선택을 브라우저에 적는다(칸마다 따로).
    2. 다시 채울 때(새로고침) 적어 둔 모델을 되살린다.
    3. 적어 둔 모델이 지금 목록에 없거나 쓸 수 없으면 《자동》으로 두되 **조용히 두지 않고** 알린다.
    4. 브라우저 저장소가 막혀도(사생활 보호 창) 칸은 정상으로 채워진다.

화면 JS의 실제 함수를 잘라 node로 돌린다(tests/js_harness.py) — 베끼면 화면과 시험이 갈라진다.
"""

from __future__ import annotations

from tests.js_harness import run_js

NAMES = ["_fillLlmSelect", "_restoreLlmChoice", "_llmChoiceLoad", "_llmChoiceSave"]

# 칸 하나와 브라우저 저장소·토스트만 흉내 낸다.
SETUP = r"""
const store = {};
let storageBroken = false;
globalThis.localStorage = {
  getItem: (k) => {
    if (storageBroken) throw new Error("blocked");
    return k in store ? store[k] : null;
  },
  setItem: (k, v) => { if (storageBroken) throw new Error("blocked"); store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
};
const toasts = [];
globalThis.window = { showToast: (m, t) => toasts.push([m, t]) };
globalThis.showToast = window.showToast;
globalThis.document = {
  createElement: () => ({ value: "", textContent: "", disabled: false, title: "" }),
};
function makeSelect(id) {
  const listeners = {};
  const s = {
    id, dataset: {}, options: [], _value: "",
    get value() { return this._value; },
    set value(v) { if (this.options.some((o) => o.value === v)) this._value = v; },
    hasAttribute: () => false, getAttribute: () => null,
    set innerHTML(html) {
      this.options = [{ value: "auto", textContent: "자동 (폴백순서)", disabled: false }];
      this._value = "auto";
    },
    appendChild(o) { this.options.push(o); if (!this._value) this._value = o.value; },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    pick(v) { this.value = v; (listeners.change || []).forEach((f) => f()); },
    listenerCount: (ev) => (listeners[ev] || []).length,
  };
  return s;
}
const m = (provider, model, available) =>
  ({ provider, model, display: model, available, cost: "subscription", vision: false });
const MODELS = [
  m("ollama", "kimi-k3:cloud", true),
  m("ollama", "glm-5.2:cloud", true),
  m("gemini", "gemini-2.5-flash", false),  // 쓸 수 없음(키 없음)
];
"""


def test_choice_survives_reload(tmp_path):
    """고른 모델이 새로고침(새 칸을 다시 채움) 뒤에도 남는다 — 칸마다 따로."""
    r = run_js(
        tmp_path,
        "workspace.js",
        NAMES,
        SETUP,
        """
        const trans = makeSelect("trans-llm-model-select");
        _fillLlmSelect(trans, MODELS);
        trans.pick("ollama:glm-5.2:cloud");
        const punct = makeSelect("punct-llm-model-select");
        _fillLlmSelect(punct, MODELS);
        // 새로고침: 같은 id의 새 칸
        const trans2 = makeSelect("trans-llm-model-select");
        _fillLlmSelect(trans2, MODELS);
        const punct2 = makeSelect("punct-llm-model-select");
        _fillLlmSelect(punct2, MODELS);
        console.log(JSON.stringify({trans: trans2.value, punct: punct2.value, toasts}));
        """,
    )
    assert r["trans"] == "ollama:glm-5.2:cloud"
    assert r["punct"] == "auto"
    assert r["toasts"] == []


def test_refill_keeps_one_listener_and_current_pick(tmp_path):
    """같은 페이지에서 목록을 다시 채워도(키 저장·창 포커스) 지금 고른 것이 남는다.

    듣는 함수(change)는 하나만 붙는다.
    """
    r = run_js(
        tmp_path,
        "workspace.js",
        NAMES,
        SETUP,
        """
        const s = makeSelect("ann-llm-model-select");
        _fillLlmSelect(s, MODELS);
        s.pick("ollama:kimi-k3:cloud");
        _fillLlmSelect(s, MODELS);
        _fillLlmSelect(s, MODELS);
        console.log(JSON.stringify({v: s.value, n: s.listenerCount("change")}));
        """,
    )
    assert r == {"v": "ollama:kimi-k3:cloud", "n": 1}


def test_missing_or_unavailable_choice_falls_back_with_notice(tmp_path):
    """기억한 모델이 목록에 없거나(지웠음) 쓸 수 없으면(로그인 풀림) 《자동》 — 알림과 함께."""
    r = run_js(
        tmp_path,
        "workspace.js",
        NAMES,
        SETUP,
        """
        store["ctb.llmModel.trans-llm-model-select"] = "ollama:qwen-old:cloud";
        store["ctb.llmModel.ocr-llm-model-select"] = "gemini:gemini-2.5-flash";
        const a = makeSelect("trans-llm-model-select");
        _fillLlmSelect(a, MODELS);
        const b = makeSelect("ocr-llm-model-select");
        _fillLlmSelect(b, MODELS);
        console.log(JSON.stringify({a: a.value, b: b.value, toasts}));
        """,
    )
    assert r["a"] == "auto" and r["b"] == "auto"
    assert len(r["toasts"]) == 2
    assert "qwen-old" in r["toasts"][0][0] and "자동" in r["toasts"][0][0]
    assert r["toasts"][0][1] == "warning"


def test_work_order_keeps_remembered_scan_model(tmp_path):
    """「말로 지시」 창을 열 때 종류 판정 칸을 기본 모델로 덮지 않는다.

    되살린 선택도 사람이 고른 것이다.

    workspace.js가 되살리며 붙이는 표지를 work-order.js의 실제 openWorkOrder가 지키는지 본다.
    """
    restored = run_js(
        tmp_path,
        "workspace.js",
        NAMES,
        SETUP,
        """
        store["ctb.llmModel.wo-scan-model-select"] = "ollama:glm-5.2:cloud";
        const s = makeSelect("wo-scan-model-select");
        _fillLlmSelect(s, MODELS);
        console.log(JSON.stringify({v: s.value, dataset: s.dataset}));
        """,
    )
    assert restored["v"] == "ollama:glm-5.2:cloud"
    r = run_js(
        tmp_path,
        "work-order.js",
        ["openWorkOrder", "WO_SCAN_DEFAULT_MODEL"],
        r"""
        const sel = {
          value: "ollama:glm-5.2:cloud",
          dataset: %s,
          options: [
            {value: "auto"}, {value: "ollama:kimi-k3:cloud"}, {value: "ollama:glm-5.2:cloud"},
          ],
          addEventListener: () => {},
        };
        const overlay = {style: {}};
        globalThis.document = {getElementById: (id) =>
          id === "work-order-overlay" ? overlay : id === "wo-scan-model-select" ? sel : null};
        function _woTarget() { return true; }
        function _woLoad() {}
        function _woRefreshScanNote() {}
        """
        % __import__("json").dumps(restored["dataset"]),
        """
        openWorkOrder();
        console.log(JSON.stringify({v: sel.value}));
        """,
    )
    assert r["v"] == "ollama:glm-5.2:cloud"


def test_blocked_storage_does_not_break_select(tmp_path):
    r = run_js(
        tmp_path,
        "workspace.js",
        NAMES,
        SETUP,
        """
        storageBroken = true;
        const s = makeSelect("comp-llm-model-select");
        _fillLlmSelect(s, MODELS);
        s.pick("ollama:glm-5.2:cloud");
        console.log(JSON.stringify({v: s.value, n: s.options.length, toasts}));
        """,
    )
    assert r == {"v": "ollama:glm-5.2:cloud", "n": 4, "toasts": []}
