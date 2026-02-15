/**
 * 대조 뷰 — OCR 결과(L2)와 확정 텍스트(L4) 글자 단위 비교
 *
 * 기능:
 *   1. 페이지의 L2 ↔ L4를 글자 단위로 대조 (API 호출)
 *   2. 통계 바: 일치·이체자·불일치·삽입·삭제 비율
 *   3. 글자별 대조 테이블 (색상 코딩)
 *   4. 이체자 사전 관리 (조회/추가)
 *   5. 불일치 글자 클릭 → 이체자 등록 다이얼로그
 *
 * 의존성:
 *   - viewerState (sidebar-tree.js) — docId, partId, pageNum
 *   - correctionState (correction-editor.js) — active 상태
 *
 * 왜 이렇게 하는가:
 *   - 교정 작업 시 OCR이 어디서 틀렸는지 한눈에 보여줌
 *   - 이체자를 자동 분류하여 실제 오류만 집중 교정 가능
 *   - 정확도 통계로 OCR 품질을 객관적으로 측정
 */

/* ──────────────────────────
   전역 상태
   ────────────────────────── */

// eslint-disable-next-line no-unused-vars
const alignmentState = {
  lastResult: null,        // 마지막 대조 결과
  activeBlockId: "*",      // 현재 선택된 블록 탭 ("*" = 페이지 전체)
  variantDict: null,       // 이체자 사전 캐시
};


/* ──────────────────────────
   초기화
   ────────────────────────── */

/**
 * 대조 뷰를 초기화한다.
 * workspace.js의 DOMContentLoaded에서 호출.
 */
// eslint-disable-next-line no-unused-vars
function initAlignmentView() {
  _initSubtabEvents();
  _initVariantEvents();
}


/**
 * 서브탭(교정/대조) 전환 이벤트를 설정한다.
 */
function _initSubtabEvents() {
  const subtabs = document.querySelectorAll(".corr-subtab");
  subtabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const view = tab.dataset.view;

      // 탭 활성화
      subtabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");

      // 뷰 전환
      const corrTextArea = document.getElementById("corr-text-area");
      const corrListSection = document.getElementById("corr-list-section");
      const alignmentView = document.getElementById("alignment-view");

      if (view === "alignment") {
        if (corrTextArea) corrTextArea.style.display = "none";
        if (corrListSection) corrListSection.style.display = "none";
        if (alignmentView) alignmentView.style.display = "";
        _runAlignment();
      } else {
        if (corrTextArea) corrTextArea.style.display = "";
        if (corrListSection) corrListSection.style.display = "";
        if (alignmentView) alignmentView.style.display = "none";
      }
    });
  });
}


/**
 * 이체자 사전 관리 이벤트를 설정한다.
 */
function _initVariantEvents() {
  const addBtn = document.getElementById("alignment-add-variant");
  if (addBtn) {
    addBtn.addEventListener("click", () => {
      _showVariantAddDialog();
    });
  }
}


/* ──────────────────────────
   대조 실행
   ────────────────────────── */

/**
 * 현재 페이지의 대조를 실행한다.
 */
async function _runAlignment() {
  if (!viewerState.docId || !viewerState.partId || !viewerState.pageNum) {
    _showAlignmentPlaceholder("페이지를 선택하세요.");
    return;
  }

  const statsBar = document.getElementById("alignment-stats-bar");
  if (statsBar) statsBar.innerHTML = '<div class="placeholder">대조 실행 중...</div>';

  const table = document.getElementById("alignment-table");
  if (table) table.innerHTML = "";

  try {
    const url = `/api/documents/${viewerState.docId}/parts/${viewerState.partId}/pages/${viewerState.pageNum}/alignment`;
    const res = await fetch(url, { method: "POST" });

    if (!res.ok) {
      const err = await res.json();
      _showAlignmentPlaceholder(err.error || "대조 실행 실패");
      return;
    }

    const data = await res.json();
    alignmentState.lastResult = data;
    alignmentState.activeBlockId = "*";

    _renderBlockTabs(data.blocks);
    _renderAlignmentResult(data);
    _loadVariantDict();
  } catch (err) {
    console.error("대조 실행 오류:", err);
    _showAlignmentPlaceholder("대조 실행 중 오류가 발생했습니다.");
  }
}


/* ──────────────────────────
   렌더링: 블록 탭
   ────────────────────────── */

/**
 * 블록 탭을 렌더링한다.
 */
function _renderBlockTabs(blocks) {
  const container = document.getElementById("alignment-block-tabs");
  if (!container) return;
  container.innerHTML = "";

  blocks.forEach((block) => {
    const tab = document.createElement("button");
    tab.className = "alignment-block-tab";
    if (block.layout_block_id === alignmentState.activeBlockId) {
      tab.classList.add("active");
    }

    const label = block.layout_block_id === "*" ? "전체" : block.layout_block_id;
    const accuracy = block.stats ? `${Math.round(block.stats.accuracy * 100)}%` : "—";
    tab.textContent = `${label} (${accuracy})`;

    tab.addEventListener("click", () => {
      alignmentState.activeBlockId = block.layout_block_id;
      container.querySelectorAll(".alignment-block-tab").forEach((t) =>
        t.classList.remove("active")
      );
      tab.classList.add("active");
      _renderAlignmentResult(alignmentState.lastResult);
    });

    container.appendChild(tab);
  });
}


/* ──────────────────────────
   렌더링: 통계 + 테이블
   ────────────────────────── */

/**
 * 선택된 블록의 대조 결과를 렌더링한다.
 */
function _renderAlignmentResult(data) {
  if (!data || !data.blocks) return;

  const block = data.blocks.find(
    (b) => b.layout_block_id === alignmentState.activeBlockId
  );
  if (!block) return;

  _renderStatsBar(block.stats);
  _renderAlignmentTable(block.pairs);
}


/**
 * 통계 바를 렌더링한다.
 */
function _renderStatsBar(stats) {
  const container = document.getElementById("alignment-stats-bar");
  if (!container || !stats) return;

  const accuracy = Math.round(stats.accuracy * 100);
  const total = stats.total_chars;

  container.innerHTML = `
    <div class="alignment-stats-summary">
      전체 ${total}자 —
      <span class="align-exact">일치 ${stats.exact}</span> ·
      <span class="align-variant">이체자 ${stats.variant}</span> ·
      <span class="align-mismatch">불일치 ${stats.mismatch}</span> ·
      <span class="align-insertion">삽입 ${stats.insertion}</span> ·
      <span class="align-deletion">누락 ${stats.deletion}</span>
    </div>
    <div class="alignment-accuracy-bar">
      <div class="alignment-accuracy-fill" style="width: ${accuracy}%"></div>
      <span class="alignment-accuracy-label">${accuracy}%</span>
    </div>
  `;
}


/**
 * 글자별 대조 테이블을 렌더링한다.
 */
function _renderAlignmentTable(pairs) {
  const container = document.getElementById("alignment-table");
  if (!container) return;

  if (!pairs || pairs.length === 0) {
    container.innerHTML = '<div class="placeholder">대조할 데이터가 없습니다</div>';
    return;
  }

  let html = '<div class="alignment-grid">';
  html += '<div class="alignment-grid-header">';
  html += '  <span class="ag-col">OCR</span>';
  html += '  <span class="ag-col">참조</span>';
  html += '  <span class="ag-col ag-status">상태</span>';
  html += "</div>";

  pairs.forEach((pair, idx) => {
    const cls = `alignment-row align-${pair.match_type}`;
    const ocrChar = pair.ocr_char || "—";
    const refChar = pair.ref_char || "—";
    const icon = _matchTypeIcon(pair.match_type);
    const label = _matchTypeLabel(pair.match_type);

    html += `<div class="${cls}" data-pair-idx="${idx}">`;
    html += `  <span class="ag-col ag-char">${_escapeHtml(ocrChar)}</span>`;
    html += `  <span class="ag-col ag-char">${_escapeHtml(refChar)}</span>`;
    html += `  <span class="ag-col ag-status">${icon} ${label}</span>`;
    html += "</div>";
  });

  html += "</div>";
  container.innerHTML = html;

  // 불일치/이체자 클릭 이벤트
  container.querySelectorAll(".align-mismatch, .align-variant").forEach((row) => {
    row.style.cursor = "pointer";
    row.addEventListener("click", () => {
      const idx = parseInt(row.dataset.pairIdx, 10);
      const pair = pairs[idx];
      if (pair && pair.ocr_char && pair.ref_char) {
        _onAlignmentPairClick(pair);
      }
    });
  });
}


/* ──────────────────────────
   이체자 사전 관리
   ────────────────────────── */

/**
 * 이체자 사전을 로드하여 표시한다.
 */
async function _loadVariantDict() {
  try {
    const res = await fetch("/api/alignment/variant-dict");
    if (!res.ok) return;
    const data = await res.json();
    alignmentState.variantDict = data;
    _renderVariantList(data);
  } catch (err) {
    console.error("이체자 사전 로드 실패:", err);
  }
}


/**
 * 이체자 사전 목록을 렌더링한다.
 */
function _renderVariantList(data) {
  const container = document.getElementById("alignment-variant-list");
  if (!container) return;

  const variants = data.variants || {};
  const keys = Object.keys(variants);

  if (keys.length === 0) {
    container.innerHTML = '<div class="placeholder">등록된 이체자가 없습니다</div>';
    return;
  }

  // 양방향이므로 중복 제거 (A↔B 한 쌍만 표시)
  const shown = new Set();
  let html = "";

  keys.forEach((char) => {
    variants[char].forEach((alt) => {
      const pairKey = [char, alt].sort().join("↔");
      if (shown.has(pairKey)) return;
      shown.add(pairKey);
      html += `<span class="variant-pair">${_escapeHtml(char)} ↔ ${_escapeHtml(alt)}</span>`;
    });
  });

  container.innerHTML = html;
}


/**
 * 이체자 추가 다이얼로그를 표시한다.
 */
function _showVariantAddDialog(charA, charB) {
  const a = prompt("글자 A:", charA || "");
  if (!a) return;
  const b = prompt("글자 B (이체자):", charB || "");
  if (!b) return;

  _addVariantPair(a.trim(), b.trim());
}


/**
 * 이체자 쌍을 서버에 등록한다.
 */
async function _addVariantPair(charA, charB) {
  try {
    const res = await fetch("/api/alignment/variant-dict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ char_a: charA, char_b: charB }),
    });

    if (!res.ok) {
      const err = await res.json();
      alert(err.error || "이체자 등록 실패");
      return;
    }

    // 사전 새로고침 + 대조 재실행
    await _loadVariantDict();
    _runAlignment();
  } catch (err) {
    console.error("이체자 등록 오류:", err);
  }
}


/**
 * 대조 결과에서 불일치/이체자 쌍 클릭 시 처리.
 */
function _onAlignmentPairClick(pair) {
  if (pair.match_type === "mismatch") {
    // mismatch → 이체자로 등록할지 묻기
    const msg = `"${pair.ocr_char}" ↔ "${pair.ref_char}"\n이체자로 등록하시겠습니까?`;
    if (confirm(msg)) {
      _addVariantPair(pair.ocr_char, pair.ref_char);
    }
  } else if (pair.match_type === "variant") {
    // variant → 정보 표시
    alert(`"${pair.ocr_char}" ↔ "${pair.ref_char}" — 이체자(同字異形)로 등록되어 있습니다.`);
  }
}


/* ──────────────────────────
   유틸리티
   ────────────────────────── */

function _matchTypeIcon(type) {
  switch (type) {
    case "exact":     return "&#10003;";   // ✓
    case "variant":   return "&#9679;";    // ●
    case "mismatch":  return "&#10007;";   // ✗
    case "insertion":  return "+";
    case "deletion":   return "&minus;";
    default:           return "?";
  }
}

function _matchTypeLabel(type) {
  switch (type) {
    case "exact":     return "일치";
    case "variant":   return "이체자";
    case "mismatch":  return "불일치";
    case "insertion":  return "삽입";
    case "deletion":   return "누락";
    default:           return type;
  }
}

function _escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function _showAlignmentPlaceholder(msg) {
  const statsBar = document.getElementById("alignment-stats-bar");
  if (statsBar) statsBar.innerHTML = `<div class="placeholder">${msg}</div>`;
  const table = document.getElementById("alignment-table");
  if (table) table.innerHTML = "";
}
