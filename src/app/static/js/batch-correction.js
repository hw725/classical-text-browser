/**
 * 일괄 교정 — 같은 글자를 여러 페이지에 걸쳐 한 번에 교정
 *
 * 기능:
 *   1. 페이지 범위 + 대상 글자 → 미리보기 (매칭 건수·위치)
 *   2. 확인 후 일괄 실행 → corrections.json 업데이트
 *
 * 의존성:
 *   - viewerState (workspace.js) — 현재 문헌/권/페이지 정보
 */

/* ──────────────────────────
   초기화
   ────────────────────────── */

// eslint-disable-next-line no-unused-vars
function initBatchCorrection() {
  const previewBtn = document.getElementById("batch-preview-btn");
  const executeBtn = document.getElementById("batch-execute-btn");

  if (previewBtn) {
    previewBtn.addEventListener("click", _batchPreview);
  }
  if (executeBtn) {
    executeBtn.addEventListener("click", _batchExecute);
  }
}

/**
 * 일괄 교정 탭 활성화 시 호출.
 * 현재 문헌의 페이지 범위를 자동으로 채운다.
 */
// eslint-disable-next-line no-unused-vars
function activateBatchCorrection() {
  // viewerState에서 현재 페이지 정보를 가져와 기본값 설정
  if (typeof viewerState === "undefined") return;

  const startInput = document.getElementById("batch-page-start");
  const endInput = document.getElementById("batch-page-end");

  if (startInput && viewerState.pageNum) {
    startInput.value = 1;
  }
  if (endInput && viewerState.totalPages) {
    endInput.value = viewerState.totalPages;
  } else if (endInput && viewerState.pageNum) {
    endInput.value = viewerState.pageNum;
  }
}

/* ──────────────────────────
   미리보기
   ────────────────────────── */

let _lastPreviewData = null; // 실행 시 재사용

async function _batchPreview() {
  if (typeof viewerState === "undefined" || !viewerState.docId) {
    showToast("문헌을 먼저 선택하세요.", 'warning');
    return;
  }

  const partId = viewerState.partId;
  const pageStart = parseInt(document.getElementById("batch-page-start").value, 10);
  const pageEnd = parseInt(document.getElementById("batch-page-end").value, 10);
  const originalChar = document.getElementById("batch-original-char").value.trim();
  const correctedChar = document.getElementById("batch-corrected-char").value.trim();

  if (!originalChar) {
    showToast("찾을 글자를 입력하세요.", 'warning');
    return;
  }
  if (!correctedChar) {
    showToast("교정 글자를 입력하세요.", 'warning');
    return;
  }
  if (originalChar === correctedChar) {
    showToast("찾을 글자와 교정 글자가 동일합니다.", 'warning');
    return;
  }
  if (pageStart > pageEnd) {
    showToast("페이지 범위가 올바르지 않습니다.", 'warning');
    return;
  }

  const resultDiv = document.getElementById("batch-result");
  const executeBtn = document.getElementById("batch-execute-btn");
  if (resultDiv) resultDiv.innerHTML = '<div class="placeholder">검색 중...</div>';
  if (executeBtn) executeBtn.disabled = true;

  try {
    const res = await fetch(
      `/api/documents/${viewerState.docId}/batch-corrections/preview`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          part_id: partId,
          page_start: pageStart,
          page_end: pageEnd,
          original_char: originalChar,
          corrected_char: correctedChar,
        }),
      }
    );
    if (!res.ok) {
      const err = await res.json();
      showToast(err.detail || err.error || "미리보기 실패", 'error');
      return;
    }

    const data = await res.json();
    _lastPreviewData = data;
    _renderPreviewResult(data);

    if (data.total_matches > 0 && executeBtn) {
      executeBtn.disabled = false;
    }
  } catch (err) {
    console.error("일괄 교정 미리보기 오류:", err);
    showToast("미리보기 중 오류가 발생했습니다: " + err.message, 'error');
  }
}

function _renderPreviewResult(data) {
  const resultDiv = document.getElementById("batch-result");
  if (!resultDiv) return;

  if (data.total_matches === 0) {
    resultDiv.innerHTML = `<div class="placeholder">
      "${_escHtml(data.original_char)}" → 매칭 결과 없음 (이미 교정되었거나 해당 글자가 없습니다)
    </div>`;
    return;
  }

  let html = `<div class="batch-summary">
    <strong>"${_escHtml(data.original_char)}" → "${_escHtml(data.corrected_char)}"</strong>
    — ${data.total_matches}건 (${data.pages.length}페이지)
  </div>`;

  html += '<div class="batch-page-list">';
  for (const page of data.pages) {
    html += `<div class="batch-page-item">
      <span class="batch-page-num">p.${page.page}</span>
      <span class="batch-page-count">${page.count}건</span>
      <span class="batch-page-contexts">`;

    // 컨텍스트 미리보기 (최대 3개)
    const previewPositions = page.positions.slice(0, 3);
    for (const pos of previewPositions) {
      const ctx = pos.context;
      // 대상 글자를 하이라이트
      const highlighted = _escHtml(ctx).replace(
        _escHtml(data.original_char),
        `<mark>${_escHtml(data.original_char)}</mark>`
      );
      html += `<span class="batch-context">…${highlighted}…</span> `;
    }
    if (page.positions.length > 3) {
      html += `<span class="batch-context-more">외 ${page.positions.length - 3}건</span>`;
    }

    html += "</span></div>";
  }
  html += "</div>";

  resultDiv.innerHTML = html;
}

/* ──────────────────────────
   실행
   ────────────────────────── */

async function _batchExecute() {
  if (!_lastPreviewData || _lastPreviewData.total_matches === 0) {
    showToast("먼저 미리보기를 실행하세요.", 'warning');
    return;
  }

  const total = _lastPreviewData.total_matches;
  const orig = _lastPreviewData.original_char;
  const corr = _lastPreviewData.corrected_char;

  if (!confirm(`"${orig}" → "${corr}" 총 ${total}건을 일괄 교정하시겠습니까?`)) {
    return;
  }

  const partId = viewerState.partId;
  const pageStart = parseInt(document.getElementById("batch-page-start").value, 10);
  const pageEnd = parseInt(document.getElementById("batch-page-end").value, 10);
  const correctionType = document.getElementById("batch-correction-type").value;
  const note = document.getElementById("batch-note").value.trim() || null;

  const executeBtn = document.getElementById("batch-execute-btn");
  if (executeBtn) executeBtn.disabled = true;

  try {
    const res = await fetch(
      `/api/documents/${viewerState.docId}/batch-corrections/execute`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          part_id: partId,
          page_start: pageStart,
          page_end: pageEnd,
          original_char: orig,
          corrected_char: corr,
          correction_type: correctionType,
          note: note,
        }),
      }
    );
    if (!res.ok) {
      const err = await res.json();
      showToast(err.detail || err.error || "일괄 교정 실행 실패", 'error');
      return;
    }

    const data = await res.json();
    showToast(
      `일괄 교정 완료 — 교정: ${data.total_corrected}건, 대상 페이지: ${data.pages_affected}개`,
      'success');

    // 결과 초기화
    _lastPreviewData = null;
    const resultDiv = document.getElementById("batch-result");
    if (resultDiv) {
      resultDiv.innerHTML =
        '<div class="placeholder">교정 완료. 다음 교정을 진행하세요.</div>';
    }
  } catch (err) {
    console.error("일괄 교정 실행 오류:", err);
    showToast("일괄 교정 중 오류가 발생했습니다: " + err.message, 'error');
  }
}

/* ──────────────────────────
   유틸리티
   ────────────────────────── */

function _escHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
