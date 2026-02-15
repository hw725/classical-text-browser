/**
 * 현토 편집기 (L5 懸吐) — Phase 11-1
 *
 * 기능:
 *   - 원문 글자를 나열하고, 글자(범위) 클릭 → 현토 입력 팝업
 *   - 위치(after/before) 선택 + 토 텍스트 입력 → 삽입
 *   - 삽입된 현토는 원문 옆에 시각적으로 표시
 *   - 표점이 있으면 함께 반영된 미리보기
 *
 * 의존성:
 *   - sidebar-tree.js (viewerState)
 *   - interpretation.js (interpState)
 */


/* ──────────────────────────
   상태 객체
   ────────────────────────── */

const hyeontoState = {
  active: false,           // 모드 활성화 여부
  originalText: "",        // L4 원문
  blockId: "",             // 현재 블록 ID
  annotations: [],         // 현재 현토 목록
  punctMarks: [],          // 현재 표점 목록 (미리보기용)
  selectedChar: null,      // 선택된 글자 인덱스
  selectionRange: null,    // 범위 선택 {start, end}
  isDirty: false,          // 변경 여부
};


/* ──────────────────────────
   초기화
   ────────────────────────── */

/**
 * 현토 편집기를 초기화한다.
 * DOMContentLoaded에서 workspace.js가 호출한다.
 */
// eslint-disable-next-line no-unused-vars
function initHyeontoEditor() {
  _bindHyeontoEvents();
}


/* ──────────────────────────
   이벤트 바인딩
   ────────────────────────── */

function _bindHyeontoEvents() {
  // 블록 선택
  const blockSelect = document.getElementById("hyeonto-block-select");
  if (blockSelect) {
    blockSelect.addEventListener("change", () => {
      const blockId = blockSelect.value;
      if (blockId) {
        hyeontoState.blockId = blockId;
        _loadHyeontoData();
      }
    });
  }

  // 저장 버튼
  const saveBtn = document.getElementById("hyeonto-save-btn");
  if (saveBtn) saveBtn.addEventListener("click", _saveHyeonto);

  // 초기화 버튼
  const clearBtn = document.getElementById("hyeonto-clear-btn");
  if (clearBtn) clearBtn.addEventListener("click", _clearHyeonto);

  // 팝업 닫기
  const closeBtn = document.getElementById("hyeonto-popup-close");
  if (closeBtn) closeBtn.addEventListener("click", _hidePopup);

  // 삽입 버튼
  const insertBtn = document.getElementById("hyeonto-insert-btn");
  if (insertBtn) insertBtn.addEventListener("click", _insertAnnotation);

  // Enter 키로 삽입
  const textInput = document.getElementById("hyeonto-text-input");
  if (textInput) {
    textInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        _insertAnnotation();
      }
    });
  }
}


/* ──────────────────────────
   모드 활성화/비활성화
   ────────────────────────── */

// eslint-disable-next-line no-unused-vars
function activateHyeontoMode() {
  hyeontoState.active = true;
  _populateHyeontoBlockSelect();
  if (hyeontoState.blockId) {
    _loadHyeontoData();
  }
}

// eslint-disable-next-line no-unused-vars
function deactivateHyeontoMode() {
  hyeontoState.active = false;
  hyeontoState.selectedChar = null;
  hyeontoState.selectionRange = null;
  _hidePopup();
}


/* ──────────────────────────
   블록 선택 드롭다운
   ────────────────────────── */

async function _populateHyeontoBlockSelect() {
  const select = document.getElementById("hyeonto-block-select");
  if (!select) return;

  select.innerHTML = '<option value="">블록 선택</option>';

  if (!viewerState.docId || !viewerState.partId || !viewerState.pageNum) return;

  try {
    const res = await fetch(
      `/api/documents/${viewerState.docId}/pages/${viewerState.pageNum}/layout?part_id=${viewerState.partId}`
    );
    if (!res.ok) {
      _addDefaultBlockOption(select);
      return;
    }
    const data = await res.json();
    const blocks = data.blocks || [];

    if (blocks.length === 0) {
      _addDefaultBlockOption(select);
    } else {
      blocks.forEach((block) => {
        const opt = document.createElement("option");
        opt.value = block.block_id;
        opt.textContent = `${block.block_id} (${block.block_type || "text"})`;
        select.appendChild(opt);
      });
    }

    if (hyeontoState.blockId) {
      select.value = hyeontoState.blockId;
    } else if (select.options.length > 1) {
      select.selectedIndex = 1;
      hyeontoState.blockId = select.value;
      _loadHyeontoData();
    }
  } catch {
    _addDefaultBlockOption(select);
  }
}

function _addDefaultBlockOption(select) {
  const opt = document.createElement("option");
  opt.value = `p${String(viewerState.pageNum).padStart(2, "0")}_b01`;
  opt.textContent = `p${String(viewerState.pageNum).padStart(2, "0")}_b01 (기본)`;
  select.appendChild(opt);
}


/* ──────────────────────────
   데이터 로드
   ────────────────────────── */

async function _loadHyeontoData() {
  if (!interpState.interpId || !viewerState.pageNum || !hyeontoState.blockId) {
    _renderHyeontoCharArea();
    return;
  }

  try {
    // 원문 + 현토 + 표점을 병렬 로드
    const [textRes, htRes, punctRes] = await Promise.all([
      fetch(`/api/documents/${viewerState.docId}/pages/${viewerState.pageNum}/text?part_id=${viewerState.partId}`),
      fetch(`/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/hyeonto?block_id=${hyeontoState.blockId}`),
      fetch(`/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/punctuation?block_id=${hyeontoState.blockId}`),
    ]);

    if (textRes.ok) {
      const textData = await textRes.json();
      hyeontoState.originalText = textData.text || "";
    } else {
      hyeontoState.originalText = "";
    }

    if (htRes.ok) {
      const htData = await htRes.json();
      hyeontoState.annotations = htData.annotations || [];
    } else {
      hyeontoState.annotations = [];
    }

    if (punctRes.ok) {
      const punctData = await punctRes.json();
      hyeontoState.punctMarks = punctData.marks || [];
    } else {
      hyeontoState.punctMarks = [];
    }

    hyeontoState.isDirty = false;
    _renderHyeontoCharArea();
    _renderAnnList();
    _renderHyeontoPreview();
  } catch (e) {
    console.error("현토 데이터 로드 실패:", e);
  }
}


/* ──────────────────────────
   렌더링 — 글자 영역
   ────────────────────────── */

/**
 * 원문 글자를 글자 단위로 렌더링한다.
 *
 * 왜 이렇게 하는가:
 *   각 글자를 span으로 감싸고, 위에 현토를 작은 루비 텍스트로 표시.
 *   글자 클릭 시 현토 입력 팝업을 표시한다.
 */
function _renderHyeontoCharArea() {
  const area = document.getElementById("hyeonto-char-area");
  if (!area) return;

  if (!hyeontoState.originalText) {
    area.innerHTML = '<div class="placeholder">현토 모드: 문헌을 선택하면 원문이 표시됩니다</div>';
    return;
  }

  const text = hyeontoState.originalText;
  const n = text.length;

  // 각 위치별 현토 텍스트를 미리 계산
  const annBefore = new Array(n).fill("");
  const annAfter = new Array(n).fill("");

  for (const ann of hyeontoState.annotations) {
    const start = ann.target?.start ?? 0;
    const end = ann.target?.end ?? start;
    const position = ann.position || "after";
    const annText = ann.text || "";

    if (start < 0 || end >= n || start > end) continue;

    if (position === "before") {
      annBefore[start] += annText;
    } else {
      annAfter[end] += annText;
    }
  }

  let html = '<div class="hyeonto-chars">';

  for (let i = 0; i < n; i++) {
    const ch = text[i];
    const hasAnn = annBefore[i] || annAfter[i];
    const selectedClass = _isHtCharInSelection(i) ? " hyeonto-char-selected" : "";
    const annClass = hasAnn ? " hyeonto-char-annotated" : "";

    html += `<span class="hyeonto-char-wrapper${selectedClass}${annClass}" data-idx="${i}">`;

    // 현토 표시 (루비 스타일)
    if (annBefore[i]) {
      html += `<span class="hyeonto-ruby hyeonto-ruby-before">${annBefore[i]}</span>`;
    }
    if (annAfter[i]) {
      html += `<span class="hyeonto-ruby hyeonto-ruby-after">${annAfter[i]}</span>`;
    }

    html += `<span class="hyeonto-char">${ch}</span>`;
    html += `</span>`;
  }

  html += "</div>";
  area.innerHTML = html;

  // 이벤트 위임: 글자 클릭
  area.addEventListener("click", _handleHtCharAreaClick);
}


function _handleHtCharAreaClick(e) {
  let wrapper = e.target.closest(".hyeonto-char-wrapper");
  if (!wrapper) return;

  const idx = parseInt(wrapper.dataset.idx, 10);
  if (isNaN(idx)) return;

  if (e.shiftKey && hyeontoState.selectionRange) {
    hyeontoState.selectionRange.end = idx;
  } else {
    hyeontoState.selectionRange = { start: idx, end: idx };
    hyeontoState.selectedChar = idx;
  }

  _renderHyeontoCharArea();
  _showPopup(idx);
}

function _isHtCharInSelection(idx) {
  if (!hyeontoState.selectionRange) return false;
  const { start, end } = hyeontoState.selectionRange;
  const lo = Math.min(start, end);
  const hi = Math.max(start, end);
  return idx >= lo && idx <= hi;
}


/* ──────────────────────────
   현토 입력 팝업
   ────────────────────────── */

function _showPopup(charIdx) {
  const popup = document.getElementById("hyeonto-input-popup");
  const targetLabel = document.getElementById("hyeonto-popup-target");
  const textInput = document.getElementById("hyeonto-text-input");

  if (!popup) return;

  // 선택된 글자 표시
  const text = hyeontoState.originalText;
  if (hyeontoState.selectionRange) {
    const lo = Math.min(hyeontoState.selectionRange.start, hyeontoState.selectionRange.end);
    const hi = Math.max(hyeontoState.selectionRange.start, hyeontoState.selectionRange.end);
    const chars = text.substring(lo, hi + 1);
    if (targetLabel) targetLabel.textContent = chars;
  } else {
    if (targetLabel) targetLabel.textContent = text[charIdx] || "";
  }

  popup.style.display = "";
  if (textInput) {
    textInput.value = "";
    textInput.focus();
  }
}

function _hidePopup() {
  const popup = document.getElementById("hyeonto-input-popup");
  if (popup) popup.style.display = "none";
}


/* ──────────────────────────
   현토 삽입
   ────────────────────────── */

function _insertAnnotation() {
  const posSelect = document.getElementById("hyeonto-position-select");
  const textInput = document.getElementById("hyeonto-text-input");

  if (!textInput || !textInput.value.trim()) {
    alert("토 텍스트를 입력하세요.");
    return;
  }

  const position = posSelect ? posSelect.value : "after";
  const annText = textInput.value.trim();

  let start, end;
  if (hyeontoState.selectionRange) {
    start = Math.min(hyeontoState.selectionRange.start, hyeontoState.selectionRange.end);
    end = Math.max(hyeontoState.selectionRange.start, hyeontoState.selectionRange.end);
  } else if (hyeontoState.selectedChar !== null) {
    start = hyeontoState.selectedChar;
    end = start;
  } else {
    alert("글자를 먼저 선택하세요.");
    return;
  }

  const ann = {
    id: "ht_" + Math.random().toString(36).substring(2, 8),
    target: { start, end },
    position,
    text: annText,
    category: null,
  };

  hyeontoState.annotations.push(ann);
  hyeontoState.isDirty = true;

  // 팝업 닫기 + 선택 해제
  _hidePopup();
  hyeontoState.selectedChar = null;
  hyeontoState.selectionRange = null;

  _renderHyeontoCharArea();
  _renderAnnList();
  _renderHyeontoPreview();
}


/* ──────────────────────────
   현토 삭제 / 초기화
   ────────────────────────── */

function _removeAnnotation(annId) {
  hyeontoState.annotations = hyeontoState.annotations.filter((a) => a.id !== annId);
  hyeontoState.isDirty = true;
  _renderHyeontoCharArea();
  _renderAnnList();
  _renderHyeontoPreview();
}

function _clearHyeonto() {
  if (hyeontoState.annotations.length > 0 && !confirm("모든 현토를 삭제하시겠습니까?")) return;
  hyeontoState.annotations = [];
  hyeontoState.isDirty = true;
  _renderHyeontoCharArea();
  _renderAnnList();
  _renderHyeontoPreview();
}


/* ──────────────────────────
   현토 목록 렌더링
   ────────────────────────── */

function _renderAnnList() {
  const list = document.getElementById("hyeonto-ann-list");
  const count = document.getElementById("hyeonto-ann-count");
  if (!list) return;

  if (count) count.textContent = hyeontoState.annotations.length;

  if (hyeontoState.annotations.length === 0) {
    list.innerHTML = '<div class="placeholder" style="font-size:12px;padding:8px;">현토가 없습니다</div>';
    return;
  }

  const text = hyeontoState.originalText;
  let html = "";

  for (const ann of hyeontoState.annotations) {
    const s = ann.target?.start ?? 0;
    const e = ann.target?.end ?? s;
    const chars = s === e ? (text[s] || `[${s}]`) : `${text[s] || ""}…${text[e] || ""} [${s}-${e}]`;
    const posLabel = ann.position === "before" ? "앞" : "뒤";

    html += `<div class="hyeonto-ann-item">
      <span class="hyeonto-ann-char">${chars}</span>
      <span class="hyeonto-ann-info">${posLabel}: ${ann.text}</span>
      <button class="hyeonto-ann-del" data-ann-id="${ann.id}" title="삭제">&times;</button>
    </div>`;
  }
  list.innerHTML = html;

  list.querySelectorAll(".hyeonto-ann-del").forEach((btn) => {
    btn.addEventListener("click", () => _removeAnnotation(btn.dataset.annId));
  });
}


/* ──────────────────────────
   미리보기 렌더링
   ────────────────────────── */

/**
 * 클라이언트 사이드에서 미리보기를 생성한다.
 * 표점 + 현토를 모두 반영한다.
 */
function _renderHyeontoPreview() {
  const previewEl = document.getElementById("hyeonto-preview");
  if (!previewEl) return;

  const text = hyeontoState.originalText;
  if (!text) {
    previewEl.textContent = "";
    return;
  }

  const n = text.length;
  const beforeBuf = new Array(n).fill("");
  const afterBuf = new Array(n).fill("");

  // 표점 적용
  for (const mark of hyeontoState.punctMarks) {
    const start = mark.target?.start ?? 0;
    const end = mark.target?.end ?? start;
    if (start < 0 || end >= n || start > end) continue;
    if (mark.before) beforeBuf[start] += mark.before;
    if (mark.after) afterBuf[end] += mark.after;
  }

  // 현토 적용
  for (const ann of hyeontoState.annotations) {
    const start = ann.target?.start ?? 0;
    const end = ann.target?.end ?? start;
    if (start < 0 || end >= n || start > end) continue;
    if (ann.position === "before") {
      beforeBuf[start] += ann.text || "";
    } else {
      afterBuf[end] += ann.text || "";
    }
  }

  let result = "";
  for (let i = 0; i < n; i++) {
    result += beforeBuf[i] + text[i] + afterBuf[i];
  }

  previewEl.textContent = result;
}


/* ──────────────────────────
   저장
   ────────────────────────── */

async function _saveHyeonto() {
  if (!interpState.interpId || !viewerState.pageNum || !hyeontoState.blockId) {
    alert("해석 저장소와 블록이 선택되어야 합니다.");
    return;
  }

  const statusEl = document.getElementById("hyeonto-save-status");
  if (statusEl) statusEl.textContent = "저장 중...";

  try {
    const res = await fetch(
      `/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/hyeonto`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          block_id: hyeontoState.blockId,
          annotations: hyeontoState.annotations,
        }),
      }
    );

    if (res.ok) {
      hyeontoState.isDirty = false;
      if (statusEl) {
        statusEl.textContent = "저장 완료";
        setTimeout(() => { statusEl.textContent = ""; }, 2000);
      }
    } else {
      const err = await res.json();
      alert(`저장 실패: ${err.error || "알 수 없는 오류"}`);
      if (statusEl) statusEl.textContent = "저장 실패";
    }
  } catch (e) {
    alert(`저장 실패: ${e.message}`);
    if (statusEl) statusEl.textContent = "저장 실패";
  }
}
