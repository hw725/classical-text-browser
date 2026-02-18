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
  engines: [],           // [{engine_id, display_name, available}, ...]
  defaultEngine: null,   // 기본 엔진 ID
  running: false,        // OCR 실행 중 여부
  lastResults: null,     // 마지막 OCR 결과 (to_summary 형식)
};


/* ─── 초기화 ───────────────────────────────────── */

function initOcrPanel() {
  // 엔진 목록 로드
  refreshOcrEngines();

  // LLM 모델 드롭다운 로드
  if (typeof populateLlmModelSelect === "function") {
    populateLlmModelSelect("ocr-llm-model-select");
  }

  // LLM 모델 행: llm_vision 엔진일 때만 표시
  const engineSelect = document.getElementById("ocr-engine-select");
  if (engineSelect) {
    engineSelect.addEventListener("change", _toggleLlmModelRow);
  }

  // 버튼 이벤트
  const runAllBtn = document.getElementById("ocr-run-all");
  const runSelectedBtn = document.getElementById("ocr-run-selected");
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
  if (fillOcrBtn) {
    fillOcrBtn.addEventListener("click", _fillFromOcr);
  }

  // 선택 블록 변경 시 "선택 블록 OCR" 버튼 상태 업데이트
  // layout-editor.js에서 블록 선택 시 이벤트를 발생시키지 않으므로
  // MutationObserver나 주기적 체크 대신, 블록 선택 함수를 감싸는 방식 사용
  setInterval(_updateSelectedBlockButton, 300);
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
  _showProgress(true, "OCR 실행 중...");
  _disableButtons(true);

  try {
    // LLM 프로바이더/모델 선택 (llm_vision 엔진 전용)
    const llmSel = typeof getLlmModelSelection === "function"
      ? getLlmModelSelection("ocr-llm-model-select")
      : { force_provider: null, force_model: null };

    const reqBody = {
      engine_id: engineId,
      block_ids: blockIds,
    };
    if (llmSel.force_provider) reqBody.force_provider = llmSel.force_provider;
    if (llmSel.force_model) reqBody.force_model = llmSel.force_model;

    const resp = await fetch(
      `/api/documents/${docId}/parts/${partId}/pages/${pageNum}/ocr`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqBody),
      }
    );

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.error || `HTTP ${resp.status}`);
    }

    const result = await resp.json();
    ocrState.lastResults = result;

    _showProgress(false);
    _displayResults(result);

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

  const ocrResults = result.ocr_results || [];

  if (ocrResults.length === 0) {
    list.innerHTML = '<div class="ocr-result-empty">OCR 결과가 없습니다</div>';
    if (summary) summary.textContent = "";
    return;
  }

  for (const block of ocrResults) {
    const blockEl = document.createElement("div");
    blockEl.className = "ocr-result-item";

    // 블록 ID
    const blockIdEl = document.createElement("span");
    blockIdEl.className = "ocr-result-block-id";
    blockIdEl.textContent = block.layout_block_id || "?";

    // 텍스트 (줄별)
    const textEl = document.createElement("span");
    textEl.className = "ocr-result-text";
    const lines = block.lines || [];
    const fullText = lines.map(l => l.text).join("");
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
    for (const ch of (line.characters || [])) {
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
      `/api/documents/${docId}/parts/${partId}/pages/${pageNum}/ocr`
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

  // OCR 결과 로드 (아직 없으면)
  let ocrData = ocrState.lastResults;
  if (!ocrData) {
    try {
      const resp = await fetch(
        `/api/documents/${docId}/parts/${partId}/pages/${pageNum}/ocr`
      );
      if (!resp.ok) {
        alert("이 페이지에 OCR 결과가 없습니다. 레이아웃 모드에서 OCR을 먼저 실행하세요.");
        return;
      }
      ocrData = await resp.json();
    } catch (e) {
      alert(`OCR 결과 로드 실패: ${e.message}`);
      return;
    }
  }

  // OCR 결과에서 전체 텍스트 추출
  const ocrResults = ocrData.ocr_results || [];
  if (ocrResults.length === 0) {
    alert("OCR 결과가 비어있습니다.");
    return;
  }

  // 블록별로 줄 텍스트를 합쳐서 전체 텍스트 생성
  const fullText = ocrResults
    .map(block => {
      const lines = block.lines || [];
      return lines.map(l => l.text).join("\n");
    })
    .join("\n\n");

  // 텍스트 에디터에 채우기 (text-editor.js의 전역 함수)
  if (typeof setEditorText === "function") {
    setEditorText(fullText);
  } else {
    // 직접 textarea에 설정
    const textarea = document.getElementById("text-content");
    if (textarea) {
      textarea.value = fullText;
      textarea.dispatchEvent(new Event("input"));
    }
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
  if (runAll) runAll.disabled = disabled;
  if (runSelected) runSelected.disabled = disabled || !_hasSelectedBlock();
}


function _hasSelectedBlock() {
  return typeof layoutState !== "undefined" && !!layoutState.selectedBlockId;
}


function _updateSelectedBlockButton() {
  const btn = document.getElementById("ocr-run-selected");
  if (!btn) return;
  btn.disabled = ocrState.running || !_hasSelectedBlock();
}


/**
 * LLM 모델 선택 행을 엔진 유형에 따라 표시/숨김.
 *
 * llm_vision 엔진일 때만 "LLM 모델" 드롭다운을 보여준다.
 * 다른 엔진(PaddleOCR, Tesseract 등)은 LLM 모델이 무관하므로 숨긴다.
 */
function _toggleLlmModelRow() {
  const engineSelect = document.getElementById("ocr-engine-select");
  const modelRow = document.getElementById("ocr-llm-model-row");
  if (!modelRow) return;

  const engineId = engineSelect ? engineSelect.value : "";
  modelRow.style.display = (engineId === "llm_vision" || engineId === "") ? "" : "none";
}
