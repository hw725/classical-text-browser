/**
 * 대조 뷰 — OCR 결과(L2)와 확정 텍스트(L4) 글자 단위 비교
 *
 * 기능:
 *   1. 페이지의 L2 ↔ L4를 글자 단위로 대조 (API 호출)
 *   2. 통계 바: 일치·이체자·불일치·삽입·삭제 비율
 *   3. 글자별 대조 테이블 (색상 코딩)
 *   4. 불일치 글자 클릭 → 이 문헌에서만 승인(D-080 결정 3) 또는 전역 사전 등록
 *   (사전 관리 — 목록·추가·가져오기 — 는 「이체자」 탭(variant-manager.js)이 한다. 이 파일에
 *    있던 추가·가져오기 대화창은 그 단추가 화면에 없어 닿지 않는 길이라 2026-10-11에 지웠다.)
 *
 * 의존성:
 *   - viewerState (sidebar-tree.js) — docId, partId, pageNum
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
}

/**
 * 서브탭(교정/일괄/대조/내보내기) 전환 이벤트를 설정한다.
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
      const exportView = document.getElementById("corr-export-view");

      // 모든 뷰 숨기기
      if (corrTextArea) corrTextArea.style.display = "none";
      if (corrListSection) corrListSection.style.display = "none";
      if (alignmentView) alignmentView.style.display = "none";
      if (batchView) batchView.style.display = "none";
      if (exportView) exportView.style.display = "none";

      if (view === "export") {
        // 들이기·내보내기(export-view.js) — 권 전체가 대상이라 쪽을 다시 그리지 않는다
        if (exportView) exportView.style.display = "";
      } else if (view === "alignment") {
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
    // 불일치인데 넓은 사전·문자 체계 사전에 관계가 있으면 힌트를 덧붙인다 (D-080).
    // 분류는 그대로 불일치다 — 《이 문헌에서 승인할지 보라》는 신호일 뿐이다.
    const label = _matchTypeLabel(pair.match_type) + _variantHintSuffix(pair.variant_hint);

    html += `<div class="${cls}" data-pair-idx="${idx}">`;
    html += `  <span class="ag-col ag-char">${_escapeHtmlAlignment(ocrChar)}</span>`;
    html += `  <span class="ag-col ag-char">${_escapeHtmlAlignment(refChar)}</span>`;
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
  } catch (err) {
    console.error("이체자 사전 로드 실패:", err);
  }
}

/* 여기 있던 `_renderVariantList()`를 뺐다 (D-069).
   대조 뷰 안에 이체자 목록을 그리던 함수인데, 그 자리(`alignment-variant-list`)가
   사라진 지 오래다 — 이체자 사전 관리는 전용 「이체자」 탭(`variant-panel`,
   `vm-*`)으로 옮겨 갔다. 컨테이너가 없으니 첫 줄의 null 가드에서 늘 되돌아갔고,
   그래서 《아무 일도 안 일어난다》는 것이 눈에 띄지 않았다.
   사전 자체는 여전히 `_loadVariantDict()`가 읽어 정렬에 쓴다. */

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
      showToast(err.error || "이체자 등록 실패", 'error');
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
    // mismatch → 이 문헌에서만 승인할지, 전역 사전에 등록할지 묻기 (D-080)
    //
    // 기본은 《이 문헌에서만》이다. 어느 관계까지 같은 글자로 볼지는 문헌마다 다르고,
    // A 문헌의 판단이 B 문헌의 판정을 바꾸면 안 된다. 전역 등록은 두 번째 물음이다.
    const hint = pair.variant_hint ? `\n(사전 힌트: ${_variantHintLabel(pair.variant_hint)})` : "";
    const msg =
      `"${pair.ocr_char}" ↔ "${pair.ref_char}"${hint}\n` +
      "이 문헌에서 같은 글자(이체자)로 승인하시겠습니까?\n" +
      "(취소를 누르면 전역 사전 등록을 따로 묻습니다)";
    if (confirm(msg)) {
      _approveVariantForDocument(pair.ocr_char, pair.ref_char);
    } else if (confirm(`"${pair.ocr_char}" ↔ "${pair.ref_char}"\n전역 이체자 사전에 등록하시겠습니까?`)) {
      _addVariantPair(pair.ocr_char, pair.ref_char);
    }
  } else if (pair.match_type === "variant") {
    // variant → 정보 표시
    showToast(
      `"${pair.ocr_char}" ↔ "${pair.ref_char}" — 이체자(同字異形)로 등록되어 있습니다.`,
      'info');
  }
}

/**
 * 이 문헌에서만 두 글자를 같은 글자로 승인한다 (D-080 결정 3).
 * 저장 위치: documents/{doc_id}/variant_approvals.json — 전역 사전으로 올라가지 않는다.
 */
async function _approveVariantForDocument(charA, charB) {
  const docId = typeof viewerState !== "undefined" ? viewerState.docId : null;
  if (!docId) {
    showToast("문헌을 먼저 여세요.", "warning");
    return;
  }
  try {
    const res = await fetch(`/api/documents/${encodeURIComponent(docId)}/variant-approvals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ char_a: charA, char_b: charB }),
    });
    const data = await res.json();
    if (!res.ok) {
      showToast(data.error || "승인에 실패했습니다.", "error");
      return;
    }
    showToast(`"${charA}" ↔ "${charB}" — 이 문헌에서 이체자로 승인했습니다 (${data.pair_count}쌍).`, "success");
    // 다시 대조하면 승인한 쌍이 《이체자》로 바뀐다.
    _runAlignment();
  } catch (e) {
    showToast(`승인 요청 실패: ${e.message}`, "error");
  }
}

function _variantHintLabel(hint) {
  switch (hint) {
    case "loose":
      return "넓은 이체 사전에 관계 있음";
    case "script":
      return "간체·신자체 등 문자 체계 차이";
    default:
      return hint || "";
  }
}

function _variantHintSuffix(hint) {
  if (!hint) return "";
  return ` <span class="align-hint" title="${_escapeHtmlAlignment(_variantHintLabel(hint))}">· 사전 힌트</span>`;
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

function _escapeHtmlAlignment(str) {
  // 브라우저가 텍스트로 넣고 다시 읽어 escape 한다(&, <, >). 그 뒤 큰·작은따옴표도 바꿔 속성 자리에도 안전하다.
  // 옛 이름 `_escapeHtml` 은 다섯 파일이 같은 이름으로 선언했고 구현이 모두 같았다(B-009 실측) — 파일마다
  // 제 이름을 붙였다.
  const div = document.createElement("div");
  div.textContent = str === null || str === undefined ? "" : str;
  // 속성 자리(title="…")에 쓰여도 안전하게 따옴표까지 바꾼다 — textContent 는 &, <, > 만 바꾼다
  // (2026-10-11 2차 전수: 문헌·권 제목·에셋 id·외부 source_url 이 속성을 벗어날 수 있었다)
  return div.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function _showAlignmentPlaceholder(msg) {
  const statsBar = document.getElementById("alignment-stats-bar");
  // msg에는 서버 오류 메시지가 그대로 실려 오기도 한다 — <가 섞이면
  // 태그로 읽혀 안내문이 사라지므로 넣기 직전에 이스케이프한다.
  if (statsBar) statsBar.innerHTML = `<div class="placeholder">${_escapeHtmlAlignment(msg)}</div>`;
  const table = document.getElementById("alignment-table");
  if (table) table.innerHTML = "";
}
