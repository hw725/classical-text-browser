/**
 * OCR 패널 — 레이아웃 모드에서 OCR 실행 + 결과 표시.
 *
 * Phase 10-1: OCR 엔진 연동.
 *
 * 의존 전역:
 *   viewerState  (sidebar-tree.js)  — docId, partId, pageNum
 *   layoutState  (layout-editor.js) — selectedBlockId, blocks
 *
 * 이 모듈이 제공하는 전역 함수:
 *   initOcrPanel()       — 앱 초기화 시 호출 (workspace.js)
 *   refreshOcrEngines()  — 엔진 목록 갱신
 *   loadOcrResults()     — 현재 페이지의 OCR 결과 로드
 */

/* ─── 상태 ─────────────────────────────────────── */

const ocrState = {
  engines: [], // [{engine_id, display_name, available}, ...]
  defaultEngine: null, // 기본 엔진 ID
  running: false, // OCR 실행 중 여부
  lastResults: null, // 마지막 OCR 결과 (to_summary 형식)
  verticalView: false, // OCR 결과 세로쓰기 표시 모드
  selectedResultIndex: -1, // OCR 목록에서 선택된 항목 index
};

/* ─── 초기화 ───────────────────────────────────── */

function initOcrPanel() {
  // 엔진 목록 로드
  refreshOcrEngines();

  // LLM 모델 행: llm_vision 엔진일 때만 표시
  // (모델 목록은 workspace.js의 _loadAllLlmModelSelects()가 일괄 로드)
  const engineSelect = document.getElementById("ocr-engine-select");
  if (engineSelect) {
    engineSelect.addEventListener("change", _toggleLlmModelRow);
  }

  // 버튼 이벤트
  const runAllBtn = document.getElementById("ocr-run-all");
  const runSelectedBtn = document.getElementById("ocr-run-selected");
  const deleteOcrBtn = document.getElementById("ocr-delete-page");
  const fillOcrBtn = document.getElementById("corr-fill-ocr");

  if (runAllBtn) {
    runAllBtn.addEventListener("click", () => _runOcr(null));
  }
  if (runSelectedBtn) {
    runSelectedBtn.addEventListener("click", () => {
      if (typeof layoutState !== "undefined" && layoutState.selectedBlockId) {
        _runOcr([layoutState.selectedBlockId]);
      }
    });
  }
  if (deleteOcrBtn) {
    deleteOcrBtn.addEventListener("click", _deleteCurrentPageOcr);
    deleteOcrBtn.textContent = "선택 OCR 삭제";
    deleteOcrBtn.title = "선택한 OCR 1건 삭제 (block_id 강제 매칭)";
  }
  if (fillOcrBtn) {
    fillOcrBtn.addEventListener("click", _fillFromOcr);
  }

  // OCR 결과 세로쓰기 토글
  const ocrVertBtn = document.getElementById("ocr-vertical-btn");
  if (ocrVertBtn) ocrVertBtn.addEventListener("click", _toggleOcrVerticalView);

  // 선택 블록 변경 시 "선택 블록 OCR" 버튼 상태 업데이트
  // layout-editor.js에서 블록 선택 시 이벤트를 발생시키지 않으므로
  // MutationObserver나 주기적 체크 대신, 블록 선택 함수를 감싸는 방식 사용
  setInterval(() => {
    _updateSelectedBlockButton();
    _syncOcrSelectionWithLayout();
  }, 300);
}

/* ─── 엔진 목록 ────────────────────────────────── */

async function refreshOcrEngines() {
  try {
    const resp = await fetch("/api/ocr/engines");
    if (!resp.ok) return;
    const data = await resp.json();

    ocrState.engines = data.engines || [];
    ocrState.defaultEngine = data.default_engine;

    _populateEngineSelect();
  } catch (e) {
    console.warn("OCR 엔진 목록 로드 실패:", e);
  }
}

function _populateEngineSelect() {
  const select = document.getElementById("ocr-engine-select");
  if (!select) return;

  select.innerHTML = "";

  if (ocrState.engines.length === 0) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "사용 가능한 엔진 없음";
    select.appendChild(opt);
    select.disabled = true;
    return;
  }

  select.disabled = false;

  for (const eng of ocrState.engines) {
    const opt = document.createElement("option");
    opt.value = eng.engine_id;
    opt.textContent = eng.display_name + (eng.available ? "" : " (사용 불가)");
    opt.disabled = !eng.available;
    if (eng.engine_id === ocrState.defaultEngine) {
      opt.selected = true;
    }
    select.appendChild(opt);
  }

  // 등록된 엔진이 2개 이상이면 엔진 선택 행을 표시한다.
  // available 여부와 무관하게 표시 — "사용 불가" 엔진도 보여줘야
  // 사용자가 설치 가능한 엔진이 있다는 것을 알 수 있다.
  const engineRow = document.getElementById("ocr-engine-row");
  if (engineRow) {
    engineRow.style.display = ocrState.engines.length <= 1 ? "none" : "";
  }

  // LLM 모델 행 표시/숨김 갱신
  _toggleLlmModelRow();
}

/* ─── OCR 실행 ─────────────────────────────────── */

async function _runOcr(blockIds) {
  if (ocrState.running) return;
  if (typeof viewerState === "undefined") return;

  const docId = viewerState.docId;
  const partId = viewerState.partId;
  const pageNum = viewerState.pageNum;

  if (!docId || !partId || !pageNum) {
    alert("문헌과 페이지를 먼저 선택하세요.");
    return;
  }

  const engineSelect = document.getElementById("ocr-engine-select");
  const engineId = engineSelect ? engineSelect.value || null : null;

  ocrState.running = true;
  _showProgress(true, "레이아웃 저장 확인 중...");
  _disableButtons(true);

  try {
    // OCR 전에 현재 레이아웃을 L3에 저장 (저장되지 않은 블록이 있을 수 있음)
    // layout-editor.js의 _saveLayout()이 전역이 아니므로 직접 호출
    if (
      typeof layoutState !== "undefined" &&
      layoutState.blocks &&
      layoutState.blocks.length > 0
    ) {
      await _ensureLayoutSaved(docId, partId, pageNum);
    }

    _showProgress(true, "OCR 실행 중...");

    // LLM 프로바이더/모델 선택 (llm_vision 엔진 전용)
    const llmSel =
      typeof getLlmModelSelection === "function"
        ? getLlmModelSelection("ocr-llm-model-select")
        : { force_provider: null, force_model: null };

    const reqBody = {
      engine_id: engineId,
      block_ids: blockIds,
    };
    if (llmSel.force_provider) reqBody.force_provider = llmSel.force_provider;
    if (llmSel.force_model) reqBody.force_model = llmSel.force_model;

    // PaddleOCR 엔진: 언어 선택
    const paddleLangSel = document.getElementById("ocr-paddle-lang-select");
    if (paddleLangSel && engineId === "paddleocr") {
      reqBody.paddle_lang = paddleLangSel.value;
    }

    const resp = await fetch(
      `/api/documents/${docId}/parts/${partId}/pages/${pageNum}/ocr`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqBody),
      },
    );

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.error || `HTTP ${resp.status}`);
    }

    const result = await resp.json();

    // 선택 블록 OCR의 응답은 부분 결과일 수 있다.
    // 저장된 L2 전체 결과를 다시 읽어와 화면에 반영해야
    // 기존 블록이 덮어써진 것처럼 보이지 않는다.
    let latest = result;
    try {
      const fullResp = await fetch(
        `/api/documents/${docId}/parts/${partId}/pages/${pageNum}/ocr`,
        { cache: "no-store" },
      );
      if (fullResp.ok) latest = await fullResp.json();
    } catch (_) {
      // 전체 재조회 실패 시에도 방금 결과는 유지
    }

    ocrState.lastResults = latest;

    _showProgress(false);
    _displayResults(latest);
  } catch (e) {
    _showProgress(false);
    alert(`OCR 실패: ${e.message}`);
  } finally {
    ocrState.running = false;
    _disableButtons(false);
  }
}

/* ─── OCR 결과 표시 ────────────────────────────── */

function _displayResults(result) {
  const preview = document.getElementById("ocr-results-preview");
  const list = document.getElementById("ocr-results-list");
  const summary = document.getElementById("ocr-results-summary");

  if (!preview || !list) return;

  preview.style.display = "";
  list.innerHTML = "";
  ocrState.selectedResultIndex = -1;

  const ocrResults = result.ocr_results || [];

  if (ocrResults.length === 0) {
    list.innerHTML = '<div class="ocr-result-empty">OCR 결과가 없습니다</div>';
    if (summary) summary.textContent = "";
    return;
  }

  for (let idx = 0; idx < ocrResults.length; idx++) {
    const block = ocrResults[idx];
    const blockId = String(block.layout_block_id || "").trim();
    const blockEl = document.createElement("div");
    blockEl.className = "ocr-result-item";
    blockEl.dataset.blockId = blockId;
    blockEl.dataset.ocrIndex = String(idx);
    blockEl.title = blockId
      ? `OCR #${idx + 1} · ${blockId}`
      : `OCR #${idx + 1} · block_id 없음`;
    blockEl.addEventListener("click", () => _selectOcrResultItem(blockId, idx));

    // 블록 ID
    const blockIdEl = document.createElement("span");
    blockIdEl.className = "ocr-result-block-id";
    blockIdEl.textContent = `#${idx + 1} ${blockId || "(block_id 없음)"}`;

    // 텍스트 (줄별)
    const textEl = document.createElement("span");
    textEl.className = "ocr-result-text";
    const lines = block.lines || [];
    const fullText = lines.map((l) => l.text).join("");
    textEl.textContent = fullText || "(비어있음)";

    // Confidence (평균)
    const avgConf = _calcAvgConfidence(lines);
    const confEl = document.createElement("span");
    confEl.className = "ocr-result-confidence " + _confidenceClass(avgConf);
    confEl.textContent = avgConf > 0 ? Math.round(avgConf * 100) + "%" : "—";
    confEl.title = `평균 신뢰도: ${(avgConf * 100).toFixed(1)}%`;

    blockEl.appendChild(blockIdEl);
    blockEl.appendChild(textEl);
    blockEl.appendChild(confEl);
    list.appendChild(blockEl);
  }

  _syncOcrSelectionWithLayout();
  _updateDeleteButtonState();

  // 요약
  if (summary) {
    const status = result.status || "completed";
    const elapsed = result.elapsed_sec || 0;
    const processed = result.processed_blocks || 0;
    const total = result.total_blocks || 0;
    const skipped = result.skipped_blocks || 0;
    const errors = result.errors || [];

    let text = `${processed}/${total} 블록 처리`;
    if (skipped > 0) text += `, ${skipped} 건너뜀`;
    text += ` (${elapsed}초)`;
    if (errors.length > 0) text += ` | 오류 ${errors.length}건`;

    summary.textContent = text;
    summary.className = errors.length > 0 ? "ocr-summary-partial" : "";
  }
}

function _calcAvgConfidence(lines) {
  let total = 0;
  let count = 0;
  for (const line of lines) {
    for (const ch of line.characters || []) {
      if (ch.confidence > 0) {
        total += ch.confidence;
        count++;
      }
    }
  }
  return count > 0 ? total / count : 0;
}

function _confidenceClass(conf) {
  if (conf >= 0.8) return "conf-high";
  if (conf >= 0.5) return "conf-mid";
  return "conf-low";
}

/* ─── OCR 결과 로드 (기존 L2) ──────────────────── */

async function loadOcrResults() {
  if (typeof viewerState === "undefined") return;

  const docId = viewerState.docId;
  const partId = viewerState.partId;
  const pageNum = viewerState.pageNum;

  if (!docId || !partId || !pageNum) return;

  try {
    const resp = await fetch(
      `/api/documents/${docId}/parts/${partId}/pages/${pageNum}/ocr`,
    );
    if (!resp.ok) {
      // 404 = OCR 결과 없음 (정상)
      ocrState.lastResults = null;
      const preview = document.getElementById("ocr-results-preview");
      if (preview) preview.style.display = "none";
      return;
    }

    const data = await resp.json();
    // L2 데이터를 to_summary 형식에 맞게 변환
    ocrState.lastResults = {
      status: "loaded",
      ocr_results: data.ocr_results || [],
      engine: data.ocr_engine || "",
      total_blocks: (data.ocr_results || []).length,
      processed_blocks: (data.ocr_results || []).length,
      skipped_blocks: 0,
      elapsed_sec: 0,
      errors: [],
    };
    _displayResults(ocrState.lastResults);
  } catch (e) {
    console.warn("OCR 결과 로드 실패:", e);
  }
}

/* ─── 교정 모드: OCR 결과로 채우기 ─────────────── */

async function _fillFromOcr() {
  if (typeof viewerState === "undefined") return;

  const docId = viewerState.docId;
  const partId = viewerState.partId;
  const pageNum = viewerState.pageNum;

  if (!docId || !partId || !pageNum) {
    alert("문헌과 페이지를 먼저 선택하세요.");
    return;
  }

  // OCR 결과는 항상 현재 페이지 기준으로 다시 로드한다.
  // 왜: 이전 페이지의 ocrState.lastResults가 남아있으면 다른 페이지 텍스트가 저장될 수 있다.
  let ocrData;
  try {
    const resp = await fetch(
      `/api/documents/${docId}/parts/${partId}/pages/${pageNum}/ocr`,
      { cache: "no-store" },
    );
    if (!resp.ok) {
      alert(
        "이 페이지에 OCR 결과가 없습니다. 레이아웃 모드에서 OCR을 먼저 실행하세요.",
      );
      return;
    }
    ocrData = await resp.json();
  } catch (e) {
    alert(`OCR 결과 로드 실패: ${e.message}`);
    return;
  }

  // OCR 결과에서 전체 텍스트 추출
  const ocrResults = ocrData.ocr_results || [];
  if (ocrResults.length === 0) {
    alert("OCR 결과가 비어있습니다.");
    return;
  }

  // 블록별로 줄 텍스트를 합쳐서 전체 텍스트 생성
  const fullText = ocrResults
    .map((block) => {
      const lines = block.lines || [];
      return lines.map((l) => l.text).join("\n");
    })
    .join("\n\n");

  // 1. 텍스트 API에 저장 (교정 모드에서도 접근 가능하도록)
  try {
    const saveUrl = `/api/documents/${docId}/pages/${pageNum}/text?part_id=${partId}`;
    const saveResp = await fetch(saveUrl, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ text: fullText }),
    });
    if (!saveResp.ok) {
      const errBody = await saveResp.text();
      throw new Error(errBody || `HTTP ${saveResp.status}`);
    }
  } catch (e) {
    alert(`OCR 텍스트 저장 실패: ${e.message}`);
    return;
  }

  // 2. 열람 모드의 textarea에도 채우기 (열람 모드일 때)
  const textarea = document.getElementById("text-content");
  if (textarea) {
    textarea.value = fullText;

    // OCR 채우기는 이미 서버 저장이 완료된 상태이므로,
    // 텍스트 에디터 상태도 "저장됨"으로 동기화한다.
    // 왜: input 이벤트를 발생시키면 editorState.isDirty가 true가 되어
    //      페이지 이동 시 "저장되지 않았습니다" 경고가 잘못 뜰 수 있다.
    if (typeof editorState !== "undefined") {
      editorState.originalText = fullText;
      editorState.isDirty = false;
    }
    if (typeof _updateSaveStatus === "function") {
      _updateSaveStatus("saved");
    }
  }

  // 3. 교정 모드가 활성화되어 있으면 교정 뷰 리프레시
  if (typeof correctionState !== "undefined" && correctionState.active) {
    if (typeof loadPageCorrections === "function") {
      await loadPageCorrections(docId, partId, pageNum);
    }
  }

  alert(`OCR 결과가 텍스트로 저장되었습니다. (${ocrResults.length}개 블록)`);
}

/* ─── OCR 결과 세로쓰기 토글 ─────────────────────── */

/**
 * OCR 결과 목록의 가로/세로 표시를 전환한다.
 *
 * 왜 이렇게 하는가: 고전 한문 텍스트는 세로로 읽으므로,
 *   OCR 결과도 세로로 표시하면 원본과 비교하기 쉽다.
 */
function _toggleOcrVerticalView() {
  ocrState.verticalView = !ocrState.verticalView;
  const list = document.getElementById("ocr-results-list");
  if (list) {
    list.classList.toggle("vertical-text-mode", ocrState.verticalView);
  }
  const btn = document.getElementById("ocr-vertical-btn");
  if (btn) {
    btn.classList.toggle("active", ocrState.verticalView);
    btn.title = ocrState.verticalView ? "가로쓰기로 전환" : "세로쓰기로 전환";
  }
}

/* ─── UI 헬퍼 ──────────────────────────────────── */

function _showProgress(show, text) {
  const el = document.getElementById("ocr-progress");
  const textEl = document.getElementById("ocr-progress-text");
  if (el) el.style.display = show ? "" : "none";
  if (textEl && text) textEl.textContent = text;
}

function _disableButtons(disabled) {
  const runAll = document.getElementById("ocr-run-all");
  const runSelected = document.getElementById("ocr-run-selected");
  const deleteBtn = document.getElementById("ocr-delete-page");
  if (runAll) runAll.disabled = disabled;
  if (runSelected) runSelected.disabled = disabled || !_hasSelectedBlock();
  if (deleteBtn)
    deleteBtn.disabled = disabled || !_canDeleteSelectedOcrResult();
}

function _hasSelectedBlock() {
  return typeof layoutState !== "undefined" && !!layoutState.selectedBlockId;
}

function _updateSelectedBlockButton() {
  const btn = document.getElementById("ocr-run-selected");
  if (!btn) return;
  btn.disabled = ocrState.running || !_hasSelectedBlock();
  _updateDeleteButtonState();
}

/**
 * OCR 실행 전에 현재 레이아웃(블록)을 L3에 저장한다.
 *
 * 왜 필요한가:
 *   OCR 파이프라인은 L3_layout/{part_id}_page_{NNN}.json에서 블록 목록을 읽는다.
 *   사용자가 레이아웃 분석/수동 편집 후 저장 버튼을 누르지 않으면 L3 파일이 없다.
 *   그래서 OCR 실행 직전에 현재 블록 상태를 자동 저장한다.
 */
async function _ensureLayoutSaved(docId, partId, pageNum) {
  // layoutState.blocks가 없거나 비어있으면 저장할 것이 없음
  if (
    typeof layoutState === "undefined" ||
    !layoutState.blocks ||
    layoutState.blocks.length === 0
  ) {
    return;
  }

  // 이미지 크기 정보
  let imgW = layoutState.imageWidth || 0;
  let imgH = layoutState.imageHeight || 0;
  if (!imgW && typeof pdfState !== "undefined" && pdfState.pdfDoc) {
    try {
      const page = await pdfState.pdfDoc.getPage(pageNum);
      const vp = page.getViewport({ scale: 1.0 });
      imgW = Math.round(vp.width);
      imgH = Math.round(vp.height);
    } catch (_) {
      /* 무시 */
    }
  }

  // 블록에서 스키마에 없는 내부 전용 필드 제거
  const cleanBlocks = layoutState.blocks.map((b) => {
    const clean = { ...b };
    delete clean._draft;
    delete clean._draft_id;
    delete clean._confidence;
    delete clean.notes;
    return clean;
  });

  const hasLlmBlocks = layoutState.blocks.some((b) => b._draft);

  const payload = {
    part_id: partId,
    page_number: pageNum,
    image_width: imgW,
    image_height: imgH,
    analysis_method: hasLlmBlocks ? "llm" : "manual",
    blocks: cleanBlocks,
  };

  const url = `/api/documents/${docId}/pages/${pageNum}/layout?part_id=${partId}`;
  try {
    const res = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      console.warn(
        "OCR 전 레이아웃 자동 저장 실패:",
        errData.error || "unknown",
      );
    }
  } catch (e) {
    console.warn("OCR 전 레이아웃 자동 저장 실패:", e);
  }
}

/**
 * OCR 엔진에 따라 LLM 모델 행과 PaddleOCR 언어 행을 표시/숨김한다.
 *
 * - llm_vision 엔진: LLM 모델 선택 행 표시, PaddleOCR 언어 행 숨김
 * - paddleocr 엔진: PaddleOCR 언어 행 표시, LLM 모델 행 숨김
 * - 기타 엔진: 둘 다 숨김
 */
function _toggleLlmModelRow() {
  const engineSelect = document.getElementById("ocr-engine-select");
  const engineId = engineSelect ? engineSelect.value : "";

  const modelRow = document.getElementById("ocr-llm-model-row");
  const paddleLangRow = document.getElementById("ocr-paddle-lang-row");

  if (modelRow) {
    modelRow.style.display = engineId === "llm_vision" ? "" : "none";
  }
  if (paddleLangRow) {
    paddleLangRow.style.display = engineId === "paddleocr" ? "" : "none";
  }
}

function _selectLayoutBlockFromOcr(blockId, ocrIndex = -1) {
  if (typeof layoutState === "undefined") return;

  const normalizedId = String(blockId || "").trim();
  const hasExact =
    normalizedId &&
    normalizedId !== "?" &&
    Array.isArray(layoutState.blocks) &&
    layoutState.blocks.some(
      (b) => String(b.block_id || "").trim() === normalizedId,
    );

  if (hasExact) {
    if (typeof _selectBlock === "function") {
      _selectBlock(normalizedId);
      return;
    }
    layoutState.selectedBlockId = normalizedId;
  } else {
    return;
  }
  if (typeof _redrawOverlay === "function") _redrawOverlay();
  if (typeof _updatePropsForm === "function") _updatePropsForm();
  if (typeof _updateBlockList === "function") _updateBlockList();
}

function _syncOcrSelectionWithLayout() {
  const list = document.getElementById("ocr-results-list");
  if (!list) return;

  list.querySelectorAll(".ocr-result-item").forEach((el) => {
    const index = Number(el.dataset.ocrIndex);
    const isSelected = index === ocrState.selectedResultIndex;
    el.classList.toggle("ocr-result-item-selected", isSelected);
  });
}

function _selectOcrResultItem(blockId, ocrIndex) {
  ocrState.selectedResultIndex = ocrIndex;
  _syncOcrSelectionWithLayout();
  _updateDeleteButtonState();
  _selectLayoutBlockFromOcr(blockId, ocrIndex);
}

function _canDeleteSelectedOcrResult() {
  const idx = ocrState.selectedResultIndex;
  if (!ocrState.lastResults || idx < 0) return false;
  const rows = ocrState.lastResults.ocr_results || [];
  if (idx >= rows.length) return false;
  const blockId = String(rows[idx].layout_block_id || "").trim();
  return !!blockId && blockId !== "?";
}

function _updateDeleteButtonState() {
  const deleteBtn = document.getElementById("ocr-delete-page");
  if (!deleteBtn) return;
  deleteBtn.disabled = ocrState.running || !_canDeleteSelectedOcrResult();
}

async function _deleteCurrentPageOcr() {
  if (ocrState.running) return;
  if (typeof viewerState === "undefined") return;

  const docId = viewerState.docId;
  const partId = viewerState.partId;
  const pageNum = viewerState.pageNum;

  if (!docId || !partId || !pageNum) {
    alert("문헌과 페이지를 먼저 선택하세요.");
    return;
  }

  if (!_canDeleteSelectedOcrResult()) {
    alert(
      "삭제할 OCR 항목을 먼저 선택하세요. (block_id가 있는 항목만 삭제 가능)",
    );
    return;
  }

  const idx = ocrState.selectedResultIndex;
  const row = (ocrState.lastResults.ocr_results || [])[idx];
  const blockId = String(row.layout_block_id || "").trim();
  const previewText = String(
    (row.lines || []).map((line) => line.text || "").join(""),
  );
  const shortText =
    previewText.length > 30 ? `${previewText.slice(0, 30)}…` : previewText;

  const ok = confirm(
    `선택한 OCR 1건을 삭제할까요?\n- OCR 항목: #${idx + 1}\n- block_id: ${blockId}\n- 내용: ${shortText || "(비어있음)"}`,
  );
  if (!ok) return;

  _disableButtons(true);
  _showProgress(true, "선택 OCR 삭제 중...");

  try {
    const resp = await fetch(
      `/api/documents/${docId}/parts/${partId}/pages/${pageNum}/ocr/${encodeURIComponent(blockId)}?index=${idx}`,
      { method: "DELETE" },
    );

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${resp.status}`);
    }

    const refreshResp = await fetch(
      `/api/documents/${docId}/parts/${partId}/pages/${pageNum}/ocr`,
      { cache: "no-store" },
    );

    if (refreshResp.ok) {
      const latest = await refreshResp.json();
      ocrState.lastResults = {
        status: "loaded",
        ocr_results: latest.ocr_results || [],
        engine: latest.ocr_engine || "",
        total_blocks: (latest.ocr_results || []).length,
        processed_blocks: (latest.ocr_results || []).length,
        skipped_blocks: 0,
        elapsed_sec: 0,
        errors: [],
      };
      _displayResults(ocrState.lastResults);
    } else {
      ocrState.lastResults = null;
      const preview = document.getElementById("ocr-results-preview");
      const list = document.getElementById("ocr-results-list");
      const summary = document.getElementById("ocr-results-summary");
      if (preview) preview.style.display = "none";
      if (list) list.innerHTML = "";
      if (summary) summary.textContent = "";
    }

    alert(`선택한 OCR 1건을 삭제했습니다. (block_id: ${blockId}, #${idx + 1})`);
  } catch (e) {
    alert(`OCR 결과 삭제 실패: ${e.message}`);
  } finally {
    _showProgress(false);
    _disableButtons(false);
  }
}
