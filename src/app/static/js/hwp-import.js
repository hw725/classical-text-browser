/**
 * 텍스트 파일 가져오기 UI (HWP + PDF 통합).
 *
 * 워크플로우:
 *   1. 파일 선택(.hwp/.hwpx/.pdf) → 자동 형식 판별
 *   2-HWP: 미리보기(메타데이터 + 텍스트 + 표점·현토 감지)
 *   2-HWP(선택): 원문/번역 분리(LLM) → 분리 결과 미리보기 + 편집
 *   2-PDF: 텍스트 레이어 확인 + 구조 분석(LLM)
 *   3-PDF: 원문/번역 분리(LLM) → 분리 결과 미리보기 + 편집
 *   4: 문헌 ID 입력 + 옵션 → 가져오기 실행
 *
 * 의존: index.html의 #hwp-import-overlay 다이얼로그.
 */

/* global _loadDocumentList */  // workspace.js에서 제공

/** 현재 파일 형식 추적 — "hwp" | "pdf" | null */
let _importFileType = null;

/** PDF 분리 결과 캐시 (분리 실행 후 저장 → apply에서 사용) */
let _pdfSeparationResults = null;

/** PDF 구조 분석 결과 캐시 */
let _pdfStructure = null;

/** HWP 분리 결과 캐시 (분리 실행 후 저장 → 가져오기에서 사용) */
let _hwpSeparationResults = null;

// ── 다이얼로그 열기/닫기 ──────────────────────

/** 다이얼로그를 열고 초기 상태로 리셋한다. */
function _openHwpImportDialog() {
  const overlay = document.getElementById("hwp-import-overlay");
  if (!overlay) return;

  // 상태 초기화
  _importFileType = null;
  _pdfSeparationResults = null;
  _pdfStructure = null;
  _hwpSeparationResults = null;

  document.getElementById("hwp-import-file").value = "";
  document.getElementById("hwp-import-status").textContent = "";
  document.getElementById("hwp-import-preview").style.display = "none";
  document.getElementById("pdf-import-preview").style.display = "none";
  document.getElementById("hwp-import-step2").style.display = "none";
  document.getElementById("hwp-import-exec-status").textContent = "";
  // HWP 분리 관련 초기화
  const hwpSepResults = document.getElementById("hwp-separation-results");
  if (hwpSepResults) hwpSepResults.style.display = "none";
  const hwpSepStatus = document.getElementById("hwp-import-separate-status");
  if (hwpSepStatus) hwpSepStatus.textContent = "";

  overlay.style.display = "flex";
}

/** 다이얼로그를 닫는다. */
function _closeHwpImportDialog() {
  const overlay = document.getElementById("hwp-import-overlay");
  if (overlay) overlay.style.display = "none";
}


// ── 파일 형식 판별 ──────────────────────────

/** 파일 확장자로 형식을 판별한다. */
function _detectFileType(filename) {
  const ext = (filename || "").split(".").pop().toLowerCase();
  if (ext === "hwp" || ext === "hwpx") return "hwp";
  if (ext === "pdf") return "pdf";
  return null;
}


// ── 미리보기 (형식에 따라 분기) ──────────────

/** 선택한 파일의 미리보기를 수행한다. */
async function _previewImportFile() {
  const fileInput = document.getElementById("hwp-import-file");
  const statusEl = document.getElementById("hwp-import-status");

  if (!fileInput.files || fileInput.files.length === 0) {
    statusEl.textContent = "파일을 선택하세요.";
    return;
  }

  const file = fileInput.files[0];
  _importFileType = _detectFileType(file.name);

  // 결과 영역 초기화
  document.getElementById("hwp-import-preview").style.display = "none";
  document.getElementById("pdf-import-preview").style.display = "none";
  document.getElementById("hwp-import-step2").style.display = "none";

  if (_importFileType === "hwp") {
    await _previewHwpFile(file, statusEl);
  } else if (_importFileType === "pdf") {
    await _previewPdfFile(file, statusEl);
  } else {
    statusEl.textContent = "지원하지 않는 형식입니다. (.hwp, .hwpx, .pdf만 가능)";
  }
}


// ── HWP 미리보기 ────────────────────────────

async function _previewHwpFile(file, statusEl) {
  statusEl.textContent = "HWP 미리보기 중...";

  try {
    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch("/api/documents/preview-hwp", {
      method: "POST",
      body: formData,
    });

    const data = await res.json();
    if (!res.ok) {
      statusEl.textContent = data.error || "미리보기 실패";
      return;
    }

    // 메타데이터 표시
    const metaEl = document.getElementById("hwp-import-meta");
    const meta = data.metadata || {};
    metaEl.innerHTML = [
      `<b>제목:</b> ${meta.title || "(없음)"}`,
      `<b>형식:</b> ${meta.format || "?"}`,
      `<b>섹션 수:</b> ${data.sections_count || 0}`,
      `<b>전체 길이:</b> ${(data.full_text_length || 0).toLocaleString()}자`,
    ].join(" &nbsp;|&nbsp; ");

    // 감지 뱃지
    const punctEl = document.getElementById("hwp-preview-punct");
    const hyeontoEl = document.getElementById("hwp-preview-hyeonto");
    const taiduEl = document.getElementById("hwp-preview-taidu");

    punctEl.textContent = data.detected_punctuation
      ? `표점 감지 (${data.punct_count}개)` : "표점 없음";
    punctEl.style.color = data.detected_punctuation ? "#e0a000" : "#666";

    hyeontoEl.textContent = data.detected_hyeonto
      ? `현토 감지 (${data.hyeonto_count}개)` : "현토 없음";
    hyeontoEl.style.color = data.detected_hyeonto ? "#e0a000" : "#666";

    taiduEl.textContent = data.detected_taidu ? "대두 감지" : "";

    // 텍스트 미리보기
    document.getElementById("hwp-import-text-preview").value =
      data.text_preview || "(텍스트 없음)";
    document.getElementById("hwp-import-clean-preview").value =
      data.sample_clean_text || "";

    document.getElementById("hwp-import-preview").style.display = "block";

    // Step 2 표시
    document.getElementById("hwp-import-step2").style.display = "block";

    // 제목 자동 채우기
    const titleInput = document.getElementById("hwp-import-title");
    if (!titleInput.value && meta.title) {
      titleInput.value = meta.title;
    }

    statusEl.textContent = "";
  } catch (err) {
    statusEl.textContent = `오류: ${err.message}`;
  }
}


// ── PDF 미리보기 ────────────────────────────

async function _previewPdfFile(file, statusEl) {
  statusEl.textContent = "PDF 분석 중...";

  try {
    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch("/api/text-import/pdf/analyze", {
      method: "POST",
      body: formData,
    });

    const data = await res.json();
    if (!res.ok) {
      statusEl.textContent = data.error || "PDF 분석 실패";
      return;
    }

    // 메타 정보
    const metaEl = document.getElementById("pdf-import-meta");
    metaEl.innerHTML = [
      `<b>페이지 수:</b> ${data.page_count}`,
      `<b>텍스트 레이어:</b> ${data.has_text_layer ? "있음" : "없음"}`,
    ].join(" &nbsp;|&nbsp; ");

    // 텍스트 레이어 상태
    const textLayerEl = document.getElementById("pdf-preview-text-layer");
    textLayerEl.textContent = data.has_text_layer
      ? "텍스트 추출 가능" : "텍스트 레이어 없음 — OCR이 필요합니다";
    textLayerEl.style.color = data.has_text_layer ? "#4caf50" : "#f44336";

    // 구조 분석 결과
    const structureEl = document.getElementById("pdf-preview-structure");
    const structureInfo = document.getElementById("pdf-structure-info");

    if (data.detected_structure) {
      _pdfStructure = data.detected_structure;
      structureEl.textContent = `구조 분석 완료 (${data.detected_structure.pattern_type})`;
      structureEl.style.color = "#4caf50";

      // 구조 상세 표시
      document.getElementById("pdf-structure-type").textContent =
        _translatePatternType(data.detected_structure.pattern_type);
      document.getElementById("pdf-structure-original").textContent =
        data.detected_structure.original_markers || "(없음)";
      document.getElementById("pdf-structure-translation").textContent =
        data.detected_structure.translation_markers || "(없음)";
      document.getElementById("pdf-structure-confidence").textContent =
        `${(data.detected_structure.confidence * 100).toFixed(0)}%`;
      structureInfo.style.display = "block";
    } else {
      structureEl.textContent = data.has_text_layer
        ? "구조 분석 건너뜀" : "";
      structureEl.style.color = "#666";
      structureInfo.style.display = "none";
    }

    // 샘플 텍스트
    const sampleText = (data.sample_pages || [])
      .map(p => `--- 페이지 ${p.page_num} (${p.char_count}자) ---\n${p.text}`)
      .join("\n\n");
    document.getElementById("pdf-import-sample-text").value = sampleText || "(텍스트 없음)";

    // 분리 결과 초기화
    document.getElementById("pdf-separation-results").style.display = "none";
    _pdfSeparationResults = null;

    document.getElementById("pdf-import-preview").style.display = "block";

    // 텍스트 레이어가 있으면 Step 2 표시
    if (data.has_text_layer) {
      document.getElementById("hwp-import-step2").style.display = "block";
    }

    statusEl.textContent = "";
  } catch (err) {
    statusEl.textContent = `오류: ${err.message}`;
  }
}

/** 패턴 타입을 한국어로 변환. */
function _translatePatternType(type) {
  const map = {
    alternating: "원문→번역 교차",
    block: "블록 분리 (앞 원문/뒤 번역)",
    interlinear: "줄 단위 교차",
    mixed: "혼합 구조",
    original_only: "원문만 있음",
    unknown: "분석 실패",
  };
  return map[type] || type;
}


// ── PDF 원문/번역 분리 ──────────────────────

async function _executePdfSeparation() {
  const fileInput = document.getElementById("hwp-import-file");
  const statusEl = document.getElementById("pdf-import-separate-status");
  const btn = document.getElementById("pdf-import-separate-btn");

  if (!fileInput.files || fileInput.files.length === 0) {
    statusEl.textContent = "파일을 다시 선택하세요.";
    return;
  }

  if (!_pdfStructure) {
    statusEl.textContent = "구조 분석 결과가 없습니다. 미리보기를 다시 실행하세요.";
    return;
  }

  btn.disabled = true;
  statusEl.textContent = "LLM으로 원문/번역 분리 중... (시간이 걸릴 수 있습니다)";

  try {
    const customInstructions =
      document.getElementById("pdf-import-custom-instructions").value.trim();

    const bodyObj = {
      structure: _pdfStructure,
      custom_instructions: customInstructions,
    };

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    formData.append("body", JSON.stringify(bodyObj));

    const res = await fetch("/api/text-import/pdf/separate", {
      method: "POST",
      body: formData,
    });

    const data = await res.json();
    if (!res.ok) {
      statusEl.textContent = data.error || "분리 실패";
      showToast(`텍스트 분리 실패: ${data.error || "알 수 없는 오류"}`, 'error');
      return;
    }

    _pdfSeparationResults = data.results || [];

    // 분리 결과 미리보기
    const allOriginal = _pdfSeparationResults
      .map(r => r.original_text || "")
      .filter(t => t.trim())
      .join("\n\n");
    const allTranslation = _pdfSeparationResults
      .map(r => r.translation_text || "")
      .filter(t => t.trim())
      .join("\n\n");

    document.getElementById("pdf-import-original-preview").value = allOriginal;
    document.getElementById("pdf-import-translation-preview").value = allTranslation;
    document.getElementById("pdf-separation-results").style.display = "block";

    // Step 2 표시
    document.getElementById("hwp-import-step2").style.display = "block";

    const pagesWithText = _pdfSeparationResults.filter(r => r.original_text).length;
    statusEl.textContent = `분리 완료: ${pagesWithText}페이지에서 원문 추출`;
  } catch (err) {
    statusEl.textContent = `오류: ${err.message}`;
    showToast(`텍스트 분리 중 오류: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
  }
}


// ── 가져오기 실행 (HWP / PDF 공통) ──────────

async function _executeImport() {
  if (_importFileType === "pdf") {
    await _executePdfApply();
  } else {
    await _executeHwpImport();
  }
}


// ── HWP 원문/번역 분리 (LLM) ────────────────

/**
 * HWP 텍스트를 LLM으로 원문/번역/주석으로 분리한다.
 *
 * 동작:
 *   1. 미리보기에서 추출된 텍스트를 서버로 전송
 *   2. 서버가 TextSeparator로 구조 분석 + 분리
 *   3. 분리 결과(원문, 번역)를 편집 가능한 textarea에 표시
 *   4. 사용자가 확인/수정 후 "가져오기"를 클릭하면 분리된 원문이 L4에 저장됨
 */
async function _executeHwpSeparation() {
  const statusEl = document.getElementById("hwp-import-separate-status");
  const btn = document.getElementById("hwp-import-separate-btn");
  const textPreview = document.getElementById("hwp-import-text-preview");

  const text = textPreview ? textPreview.value : "";
  if (!text.trim()) {
    statusEl.textContent = "분리할 텍스트가 없습니다. 먼저 미리보기를 실행하세요.";
    return;
  }

  btn.disabled = true;
  statusEl.textContent = "LLM으로 원문/번역 분리 중... (시간이 걸릴 수 있습니다)";

  try {
    const customInstructions =
      (document.getElementById("hwp-import-custom-instructions") || {}).value || "";

    let res;
    try {
      res = await fetch("/api/text-import/hwp/separate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: text,
          custom_instructions: customInstructions.trim(),
        }),
      });
    } catch (networkErr) {
      statusEl.textContent = "서버 연결 실패 — 서버가 실행 중인지 확인하세요.";
      alert("서버 연결 실패: " + networkErr.message);
      return;
    }

    const data = await res.json();
    if (!res.ok) {
      const errMsg = data.error || "분리 실패";
      statusEl.textContent = errMsg;
      // LLM 미설정 등 중요 에러는 alert로 확실히 표시
      alert(`텍스트 분리 실패:\n${errMsg}`);
      return;
    }

    _hwpSeparationResults = data.results || [];

    // 분리 결과 미리보기 표시
    const allOriginal = _hwpSeparationResults
      .map((r) => r.original_text || "")
      .filter((t) => t.trim())
      .join("\n\n");
    const allTranslation = _hwpSeparationResults
      .map((r) => r.translation_text || "")
      .filter((t) => t.trim())
      .join("\n\n");

    document.getElementById("hwp-import-original-preview").value = allOriginal;
    document.getElementById("hwp-import-translation-preview").value = allTranslation;
    document.getElementById("hwp-separation-results").style.display = "block";

    // 정리된 원문 미리보기도 분리 결과로 교체
    document.getElementById("hwp-import-clean-preview").value = allOriginal;

    // 구조 정보 표시
    const structure = data.structure || {};
    const patternLabel = _translatePatternType(structure.pattern_type || "unknown");
    statusEl.textContent =
      `분리 완료: ${patternLabel}` +
      (structure.confidence ? ` (확신도 ${(structure.confidence * 100).toFixed(0)}%)` : "");

    // Step 2 표시
    document.getElementById("hwp-import-step2").style.display = "block";
  } catch (err) {
    statusEl.textContent = `오류: ${err.message}`;
    showToast(`텍스트 분리 중 오류: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
  }
}


// ── HWP 가져오기 실행 ───────────────────────

async function _executeHwpImport() {
  const fileInput = document.getElementById("hwp-import-file");
  const docIdInput = document.getElementById("hwp-import-doc-id");
  const titleInput = document.getElementById("hwp-import-title");
  const stripPunct = document.getElementById("hwp-import-strip-punct").checked;
  const stripHyeonto = document.getElementById("hwp-import-strip-hyeonto").checked;
  const statusEl = document.getElementById("hwp-import-exec-status");
  const execBtn = document.getElementById("hwp-import-exec-btn");

  const docId = docIdInput.value.trim();
  if (!docId) {
    statusEl.textContent = "문헌 ID를 입력하세요.";
    return;
  }

  if (!fileInput.files || fileInput.files.length === 0) {
    statusEl.textContent = "파일을 선택하세요.";
    return;
  }

  execBtn.disabled = true;

  // ─── 분리 결과가 있으면: apply API로 분리된 원문/번역 저장 ───
  if (_hwpSeparationResults && _hwpSeparationResults.length > 0) {
    statusEl.textContent = "분리된 텍스트 저장 중...";

    try {
      // 먼저 HWP 파일 업로드로 문헌 생성 (아직 없으면)
      const formData = new FormData();
      formData.append("file", fileInput.files[0]);
      formData.append("doc_id", docId);
      if (titleInput.value.trim()) {
        formData.append("title", titleInput.value.trim());
      }
      // 분리 모드에서는 원본 텍스트를 먼저 올리지 않고 apply로 대체
      formData.append("strip_punctuation", "false");
      formData.append("strip_hyeonto", "false");

      const createRes = await fetch("/api/documents/import-hwp", {
        method: "POST",
        body: formData,
      });

      if (!createRes.ok) {
        const errData = await createRes.json();
        // "이미 존재합니다" 에러는 무시 (기존 문헌에 투입하는 경우)
        if (!errData.error || !errData.error.includes("이미 존재")) {
          statusEl.textContent = errData.error || "문헌 생성 실패";
          showToast(`문헌 생성 실패: ${errData.error || "알 수 없는 오류"}`, "error");
          execBtn.disabled = false;
          return;
        }
      }

      // 사용자가 편집한 원문/번역 반영
      const editedOriginal =
        document.getElementById("hwp-import-original-preview").value;
      const editedTranslation =
        document.getElementById("hwp-import-translation-preview").value;

      const results = [{
        page_num: 1,
        original_text: editedOriginal,
        translation_text: editedTranslation,
      }];

      // apply API로 분리된 원문을 L4에, 번역을 사이드카에 저장
      const applyRes = await fetch("/api/text-import/pdf/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          doc_id: docId,
          results: results,
          strip_punctuation: stripPunct,
          strip_hyeonto: stripHyeonto,
        }),
      });

      const applyData = await applyRes.json();
      if (!applyRes.ok) {
        statusEl.textContent = applyData.error || "저장 실패";
        showToast(`텍스트 저장 실패: ${applyData.error || "알 수 없는 오류"}`, "error");
        execBtn.disabled = false;
        return;
      }

      let msg = `완료: 원문 ${applyData.pages_saved}페이지 L4 저장`;
      if (applyData.translations_saved) {
        msg += `, 번역 ${applyData.translations_saved}페이지 저장`;
      }
      statusEl.textContent = msg;

      if (typeof _loadDocumentList === "function") {
        _loadDocumentList();
      }
    } catch (err) {
      statusEl.textContent = `오류: ${err.message}`;
      showToast(`가져오기 중 오류: ${err.message}`, "error");
    } finally {
      execBtn.disabled = false;
    }
    return;
  }

  // ─── 분리 안 한 경우: 기존 HWP 가져오기 (전체 텍스트를 L4에 저장) ───
  statusEl.textContent = "가져오는 중...";

  try {
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    formData.append("doc_id", docId);
    if (titleInput.value.trim()) {
      formData.append("title", titleInput.value.trim());
    }
    formData.append("strip_punctuation", stripPunct.toString());
    formData.append("strip_hyeonto", stripHyeonto.toString());

    const res = await fetch("/api/documents/import-hwp", {
      method: "POST",
      body: formData,
    });

    const data = await res.json();

    if (!res.ok) {
      const errMsg = data.error || "가져오기 실패";
      statusEl.textContent = errMsg;
      alert(`HWP 가져오기 실패:\n${errMsg}`);
      return;
    }

    const stats = data.cleaned_stats || {};
    const mode = data.mode === "create_from_hwp" ? "새 문헌 생성" : "기존 문헌에 투입";
    statusEl.textContent =
      `완료: ${mode} — ${data.pages_saved}페이지` +
      (stats.punct_count ? `, 표점 ${stats.punct_count}개 분리` : "") +
      (stats.hyeonto_count ? `, 현토 ${stats.hyeonto_count}개 분리` : "");

    if (typeof _loadDocumentList === "function") {
      _loadDocumentList();
    }
  } catch (err) {
    statusEl.textContent = `오류: ${err.message}`;
    showToast(`HWP 가져오기 중 오류: ${err.message}`, 'error');
  } finally {
    execBtn.disabled = false;
  }
}


// ── PDF 가져오기 적용 ───────────────────────

async function _executePdfApply() {
  const docIdInput = document.getElementById("hwp-import-doc-id");
  const stripPunct = document.getElementById("hwp-import-strip-punct").checked;
  const stripHyeonto = document.getElementById("hwp-import-strip-hyeonto").checked;
  const statusEl = document.getElementById("hwp-import-exec-status");
  const execBtn = document.getElementById("hwp-import-exec-btn");

  const docId = docIdInput.value.trim();
  if (!docId) {
    statusEl.textContent = "문헌 ID를 입력하세요.";
    return;
  }

  // 분리 결과가 있으면 사용, 없으면 직접 텍스트 사용
  let results;
  if (_pdfSeparationResults && _pdfSeparationResults.length > 0) {
    // 사용자가 편집한 원문 반영
    const editedOriginal = document.getElementById("pdf-import-original-preview").value;
    // 편집된 텍스트를 단일 결과로 전송 (전체를 page 1로)
    results = [{
      page_num: 1,
      original_text: editedOriginal,
      translation_text: document.getElementById("pdf-import-translation-preview").value,
    }];
  } else {
    statusEl.textContent = "먼저 '원문/번역 분리 실행'을 해주세요.";
    return;
  }

  execBtn.disabled = true;
  statusEl.textContent = "L4에 저장 중...";

  try {
    const res = await fetch("/api/text-import/pdf/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        doc_id: docId,
        results: results,
        strip_punctuation: stripPunct,
        strip_hyeonto: stripHyeonto,
      }),
    });

    const data = await res.json();

    if (!res.ok) {
      statusEl.textContent = data.error || "저장 실패";
      showToast(`PDF 텍스트 저장 실패: ${data.error || "알 수 없는 오류"}`, 'error');
      return;
    }

    statusEl.textContent = `완료: ${data.pages_saved}페이지 L4에 저장`;

    if (typeof _loadDocumentList === "function") {
      _loadDocumentList();
    }
  } catch (err) {
    statusEl.textContent = `오류: ${err.message}`;
    showToast(`PDF 텍스트 저장 중 오류: ${err.message}`, 'error');
  } finally {
    execBtn.disabled = false;
  }
}


// ── 이벤트 바인딩 ─────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  // 닫기 버튼
  const closeBtn = document.getElementById("hwp-import-close");
  if (closeBtn) closeBtn.addEventListener("click", _closeHwpImportDialog);

  // 오버레이 클릭으로 닫기
  const overlay = document.getElementById("hwp-import-overlay");
  if (overlay) {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) _closeHwpImportDialog();
    });
  }

  // 미리보기 버튼 — 형식에 따라 분기
  const previewBtn = document.getElementById("hwp-import-preview-btn");
  if (previewBtn) previewBtn.addEventListener("click", _previewImportFile);

  // 가져오기 실행 버튼 — 형식에 따라 분기
  const execBtn = document.getElementById("hwp-import-exec-btn");
  if (execBtn) execBtn.addEventListener("click", _executeImport);

  // PDF 분리 실행 버튼
  const separateBtn = document.getElementById("pdf-import-separate-btn");
  if (separateBtn) separateBtn.addEventListener("click", _executePdfSeparation);

  // HWP 분리 실행 버튼
  const hwpSeparateBtn = document.getElementById("hwp-import-separate-btn");
  if (hwpSeparateBtn) hwpSeparateBtn.addEventListener("click", _executeHwpSeparation);
});
