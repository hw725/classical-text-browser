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
  lastResult: null, // 마지막 대조 결과
  activeBlockId: "*", // 현재 선택된 블록 탭 ("*" = 페이지 전체)
  variantDict: null, // 이체자 사전 캐시
};

let _variantEventDelegationBound = false;

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
 * 서브탭(교정/일괄/대조) 전환 이벤트를 설정한다.
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
      const batchView = document.getElementById("batch-correction-view");

      // 모든 뷰 숨기기
      if (corrTextArea) corrTextArea.style.display = "none";
      if (corrListSection) corrListSection.style.display = "none";
      if (alignmentView) alignmentView.style.display = "none";
      if (batchView) batchView.style.display = "none";

      if (view === "alignment") {
        if (alignmentView) alignmentView.style.display = "";
        _runAlignment();
      } else if (view === "batch") {
        if (batchView) batchView.style.display = "";
        // 일괄 교정 초기화 (현재 페이지 정보 반영)
        if (typeof activateBatchCorrection === "function") activateBatchCorrection();
      } else {
        // corrections (교정) 뷰
        if (corrTextArea) corrTextArea.style.display = "";
        if (corrListSection) corrListSection.style.display = "";
      }
    });
  });
}

/**
 * 이체자 사전 관리 이벤트를 설정한다.
 */
function _initVariantEvents() {
  if (_variantEventDelegationBound) return;
  _variantEventDelegationBound = true;

  document.addEventListener("click", (e) => {
    if (!(e.target instanceof Element)) return;

    const addBtn = e.target.closest("#alignment-add-variant");
    if (addBtn) {
      e.preventDefault();
      _showVariantAddDialog();
      return;
    }

    const importBtn = e.target.closest("#alignment-import-variant");
    if (importBtn) {
      e.preventDefault();
      _showVariantImportDialog();
    }
  });
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
  if (statsBar)
    statsBar.innerHTML = '<div class="placeholder">대조 실행 중...</div>';

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

    const label =
      block.layout_block_id === "*" ? "전체" : block.layout_block_id;
    const accuracy = block.stats
      ? `${Math.round(block.stats.accuracy * 100)}%`
      : "—";
    tab.textContent = `${label} (${accuracy})`;

    tab.addEventListener("click", () => {
      alignmentState.activeBlockId = block.layout_block_id;
      container
        .querySelectorAll(".alignment-block-tab")
        .forEach((t) => t.classList.remove("active"));
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
    (b) => b.layout_block_id === alignmentState.activeBlockId,
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
    container.innerHTML =
      '<div class="placeholder">대조할 데이터가 없습니다</div>';
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
  container
    .querySelectorAll(".align-mismatch, .align-variant")
    .forEach((row) => {
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
    container.innerHTML =
      '<div class="placeholder">등록된 이체자가 없습니다</div>';
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
 * 이체자 대량 가져오기 다이얼로그를 표시한다.
 *
 * 텍스트 붙여넣기 + 파일 업로드 두 가지 방법을 지원한다.
 * 형식: CSV, TSV, 텍스트(공백/↔ 구분), JSON 자동 감지.
 */
function _showVariantImportDialog() {
  // 기존 다이얼로그가 있으면 제거
  const existing = document.getElementById("variant-import-dialog");
  if (existing) existing.remove();

  const overlay = document.createElement("div");
  overlay.id = "variant-import-dialog";
  overlay.style.cssText =
    "position:fixed;top:0;left:0;width:100%;height:100%;" +
    "background:rgba(0,0,0,0.5);z-index:10000;display:flex;" +
    "align-items:center;justify-content:center;";

  const dialog = document.createElement("div");
  dialog.style.cssText =
    "background:var(--bg-primary,#1e1e1e);color:var(--text-primary,#e0e0e0);" +
    "border-radius:8px;padding:20px;width:520px;max-height:80vh;" +
    "overflow-y:auto;box-shadow:0 8px 32px rgba(0,0,0,0.5);";

  dialog.innerHTML = `
    <h3 style="margin:0 0 12px 0;font-size:15px;">이체자 사전 가져오기</h3>
    <div style="margin-bottom:8px;font-size:12px;color:var(--text-secondary,#aaa);">
      지원 형식: CSV (<code>A,B</code>), TSV (<code>A&#9;B</code>),
      텍스트 (<code>A B</code> 또는 <code>A↔B</code>),
      JSON (<code>{"A":["B"]}</code> 또는 <code>[["A","B"]]</code>)<br>
      한 줄에 3개 이상이면 모든 조합을 등록합니다. <code>#</code>으로 시작하는 줄은 무시됩니다.
    </div>
    <div style="margin-bottom:8px;">
      <label style="font-size:13px;">
        형식:
        <select id="variant-import-format" style="margin-left:4px;padding:2px 6px;
          background:var(--bg-secondary,#2d2d2d);color:var(--text-primary,#e0e0e0);
          border:1px solid var(--border-color,#555);border-radius:4px;">
          <option value="auto">자동 감지</option>
          <option value="csv">CSV (쉼표)</option>
          <option value="tsv">TSV (탭)</option>
          <option value="text">텍스트 (공백/↔)</option>
          <option value="json">JSON</option>
        </select>
      </label>
    </div>
    <textarea id="variant-import-text"
      placeholder="여기에 이체자 데이터를 붙여넣으세요.&#10;예시:&#10;說,説&#10;齒,歯,齿&#10;裴,裵"
      style="width:100%;height:180px;font-family:monospace;font-size:13px;
        background:var(--bg-secondary,#2d2d2d);color:var(--text-primary,#e0e0e0);
        border:1px solid var(--border-color,#555);border-radius:4px;
        padding:8px;resize:vertical;box-sizing:border-box;"></textarea>
    <div style="margin:8px 0;">
      <label style="font-size:13px;cursor:pointer;
        color:var(--accent-color,#4fc3f7);text-decoration:underline;">
        파일에서 불러오기
        <input type="file" id="variant-import-file"
          accept=".csv,.tsv,.txt,.json"
          style="display:none;">
      </label>
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">
      <button id="variant-import-cancel"
        style="padding:6px 16px;border:1px solid var(--border-color,#555);
          background:transparent;color:var(--text-primary,#e0e0e0);
          border-radius:4px;cursor:pointer;">취소</button>
      <button id="variant-import-submit"
        style="padding:6px 16px;border:none;
          background:var(--accent-color,#4fc3f7);color:#000;
          border-radius:4px;cursor:pointer;font-weight:bold;">가져오기</button>
    </div>
  `;

  overlay.appendChild(dialog);
  document.body.appendChild(overlay);

  // 파일 선택 시 textarea에 내용 채우기
  const fileInput = document.getElementById("variant-import-file");
  fileInput.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      document.getElementById("variant-import-text").value = reader.result;
      // 파일 확장자로 형식 자동 설정
      const ext = file.name.split(".").pop().toLowerCase();
      const fmtSelect = document.getElementById("variant-import-format");
      if (ext === "csv") fmtSelect.value = "csv";
      else if (ext === "tsv") fmtSelect.value = "tsv";
      else if (ext === "json") fmtSelect.value = "json";
      else fmtSelect.value = "auto";
    };
    reader.readAsText(file, "UTF-8");
  });

  // 취소
  document
    .getElementById("variant-import-cancel")
    .addEventListener("click", () => {
      overlay.remove();
    });

  // 오버레이 바깥 클릭 시 닫기
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.remove();
  });

  // 가져오기 실행
  document
    .getElementById("variant-import-submit")
    .addEventListener("click", async () => {
      const text = document.getElementById("variant-import-text").value;
      const fmt = document.getElementById("variant-import-format").value;

      if (!text.trim()) {
        alert("가져올 데이터를 입력하세요.");
        return;
      }

      await _importVariantData(text, fmt);
      overlay.remove();
    });
}

/**
 * 이체자 데이터를 서버로 전송하여 대량 등록한다.
 */
async function _importVariantData(text, format) {
  try {
    const res = await fetch("/api/alignment/variant-dict/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, format }),
    });

    if (!res.ok) {
      const err = await res.json();
      alert(err.error || "이체자 가져오기 실패");
      return;
    }

    const data = await res.json();

    // 결과 메시지 조립
    let msg = `이체자 가져오기 완료\n\n추가: ${data.added}쌍\n건너뜀 (중복): ${data.skipped}쌍\n총 사전 크기: ${data.size}자`;
    if (data.errors && data.errors.length > 0) {
      msg +=
        `\n\n오류 ${data.errors.length}건:\n` +
        data.errors.slice(0, 10).join("\n");
      if (data.errors.length > 10) {
        msg += `\n... 외 ${data.errors.length - 10}건`;
      }
    }
    alert(msg);

    // 사전 새로고침 + 대조 재실행
    await _loadVariantDict();
    if (data.added > 0) {
      _runAlignment();
    }
  } catch (err) {
    console.error("이체자 가져오기 오류:", err);
    alert("이체자 가져오기 중 오류가 발생했습니다: " + err.message);
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
    alert(
      `"${pair.ocr_char}" ↔ "${pair.ref_char}" — 이체자(同字異形)로 등록되어 있습니다.`,
    );
  }
}

/* ──────────────────────────
   유틸리티
   ────────────────────────── */

function _matchTypeIcon(type) {
  switch (type) {
    case "exact":
      return "&#10003;"; // ✓
    case "variant":
      return "&#9679;"; // ●
    case "mismatch":
      return "&#10007;"; // ✗
    case "insertion":
      return "+";
    case "deletion":
      return "&minus;";
    default:
      return "?";
  }
}

function _matchTypeLabel(type) {
  switch (type) {
    case "exact":
      return "일치";
    case "variant":
      return "이체자";
    case "mismatch":
      return "불일치";
    case "insertion":
      return "삽입";
    case "deletion":
      return "누락";
    default:
      return type;
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
