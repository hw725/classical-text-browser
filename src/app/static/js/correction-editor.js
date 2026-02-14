/**
 * 교정 편집기 — 글자 단위 교정 + 블록별 섹션 + Git 연동
 *
 * 기능:
 *   1. 페이지 텍스트를 글자 단위 <span>으로 렌더링
 *   2. 글자 클릭 → 교정 다이얼로그 (유형, 원문, 교정문, 메모)
 *   3. 교정된 글자 하이라이팅 (유형별 색상)
 *   4. L3 레이아웃이 있으면 블록별 섹션으로 구분
 *   5. 저장 시 corrections.json + 자동 git commit
 *   6. 하단 패널에 git log + diff 표시
 *
 * 의존성: sidebar-tree.js (viewerState), layout-editor.js (layoutState.blockTypes)
 *
 * 왜 이렇게 하는가:
 *   - 연구자가 PDF 원본을 보면서, 옆 패널에서 글자를 하나씩 선택하여 교정한다.
 *   - textarea 대신 div+span을 사용하는 이유: 글자 단위 클릭과 하이라이팅이 필요하다.
 *   - 교정 유형(OCR 오류, 이체자, 판본 이문 등)을 구분하여 기록하면,
 *     나중에 통계 분석이나 자동 교정 모델 학습에 활용할 수 있다.
 */

/* ──────────────────────────
   교정 편집기 상태
   ────────────────────────── */

const correctionState = {
  active: false,           // 교정 모드 활성화 여부
  corrections: [],         // 현재 페이지의 교정 목록
  blocks: [],              // L3 레이아웃 블록 (있으면)
  hasLayout: false,        // L3 데이터 존재 여부
  selectedCharInfo: null,  // 선택된 글자 정보 {blockId, charIdx, char}
  editingCorrIdx: -1,      // 편집 중인 교정 인덱스 (-1이면 새 교정)
  pageText: "",            // 현재 페이지 텍스트 원본
  isDirty: false,          // 수정 여부
};


/* ──────────────────────────
   교정 유형 정의
   ────────────────────────── */

/**
 * 교정 유형별 메타데이터.
 * corrections.schema.json의 type enum과 일치해야 한다.
 *
 * 왜 이렇게 하는가: UI 표시용 라벨과 색상을 한곳에서 관리한다.
 */
const CORRECTION_TYPES = {
  ocr_error:        { label: "OCR 오류",       color: "#ef4444", cssClass: "corr-ocr-error" },
  variant_reading:  { label: "판본 이문",       color: "#3b82f6", cssClass: "corr-variant-reading" },
  variant_char:     { label: "이체자",          color: "#a855f7", cssClass: "corr-variant-char" },
  decoding_error:   { label: "판독 불가→가능",  color: "#f59e0b", cssClass: "corr-decoding-error" },
  uncertain:        { label: "불확실",          color: "#6b7280", cssClass: "corr-uncertain" },
};


/* ──────────────────────────
   초기화
   ────────────────────────── */

/**
 * 교정 편집기를 초기화한다.
 * DOMContentLoaded 시 workspace.js에서 호출된다.
 */
// eslint-disable-next-line no-unused-vars
function initCorrectionEditor() {
  _initCorrDialogEvents();
  _initCorrToolbarEvents();
  _initGitPanelEvents();
}


/**
 * 교정 다이얼로그의 이벤트 리스너를 등록한다.
 */
function _initCorrDialogEvents() {
  // 닫기 버튼
  const closeBtn = document.getElementById("corr-dialog-close");
  if (closeBtn) closeBtn.addEventListener("click", _closeCorrDialog);

  // 취소 버튼
  const cancelBtn = document.getElementById("corr-dialog-cancel");
  if (cancelBtn) cancelBtn.addEventListener("click", _closeCorrDialog);

  // 저장 버튼
  const saveBtn = document.getElementById("corr-dialog-save");
  if (saveBtn) saveBtn.addEventListener("click", _saveCorrFromDialog);

  // 삭제 버튼
  const deleteBtn = document.getElementById("corr-dialog-delete");
  if (deleteBtn) deleteBtn.addEventListener("click", _deleteCorrFromDialog);

  // 교정 유형 변경 시 통행 텍스트 필드 표시/숨김
  const typeSelect = document.getElementById("corr-type");
  if (typeSelect) {
    typeSelect.addEventListener("change", () => {
      _toggleCommonReadingField(typeSelect.value);
    });
  }

  // 확신도 슬라이더 값 표시
  const slider = document.getElementById("corr-confidence");
  const valDisplay = document.getElementById("corr-confidence-val");
  if (slider && valDisplay) {
    slider.addEventListener("input", () => {
      valDisplay.textContent = slider.value;
    });
  }

  // 오버레이 클릭으로 닫기
  const overlay = document.getElementById("corr-dialog-overlay");
  if (overlay) {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) _closeCorrDialog();
    });
  }
}


/**
 * 교정 툴바의 이벤트 리스너를 등록한다.
 */
function _initCorrToolbarEvents() {
  // 저장 버튼
  const saveBtn = document.getElementById("corr-save");
  if (saveBtn) saveBtn.addEventListener("click", _saveCorrections);

  // Ctrl+S 단축키는 workspace.js 또는 text-editor.js에서 이미 등록되어 있으므로,
  // 교정 모드에서도 동일 단축키로 저장하기 위해 이벤트를 추가한다.
  document.addEventListener("keydown", (e) => {
    if (!correctionState.active) return;
    if (e.ctrlKey && e.key === "s") {
      e.preventDefault();
      _saveCorrections();
    }
  });

  // 블록 필터 변경
  const filter = document.getElementById("corr-block-filter");
  if (filter) {
    filter.addEventListener("change", () => {
      _applyBlockFilter(filter.value);
    });
  }
}


/* ──────────────────────────
   모드 전환: 교정 모드 활성화/비활성화
   ────────────────────────── */

/**
 * 교정 모드를 활성화한다.
 * workspace.js의 _switchMode("correction")에서 호출된다.
 *
 * 왜 이렇게 하는가: 교정 모드 진입 시 현재 페이지의 텍스트, 레이아웃, 교정 데이터를
 *                    모두 로드하여 글자 단위 렌더링을 수행한다.
 */
// eslint-disable-next-line no-unused-vars
function activateCorrectionMode() {
  correctionState.active = true;

  // 현재 페이지의 교정 데이터 로드
  if (viewerState.docId && viewerState.partId && viewerState.pageNum) {
    loadPageCorrections(viewerState.docId, viewerState.partId, viewerState.pageNum);
  }
}


/**
 * 교정 모드를 비활성화한다.
 */
// eslint-disable-next-line no-unused-vars
function deactivateCorrectionMode() {
  correctionState.active = false;
  correctionState.selectedCharInfo = null;
}


/* ──────────────────────────
   데이터 로드
   ────────────────────────── */

/**
 * 현재 페이지의 텍스트 + 레이아웃 + 교정 데이터를 로드한다.
 *
 * 왜 이렇게 하는가: 교정 뷰를 구성하려면 세 가지 데이터가 모두 필요하다.
 *   1. 텍스트: 글자 단위 렌더링의 기반
 *   2. 레이아웃: 블록별 섹션 구분 (있으면)
 *   3. 교정: 기존 교정 하이라이트 표시
 *
 * 세 API를 병렬로 호출하여 로딩 시간을 줄인다.
 */
// eslint-disable-next-line no-unused-vars
async function loadPageCorrections(docId, partId, pageNum) {
  if (!docId || !partId || !pageNum) return;

  try {
    // 세 API 병렬 호출
    const [textRes, layoutRes, corrRes] = await Promise.all([
      fetch(`/api/documents/${docId}/pages/${pageNum}/text?part_id=${partId}`),
      fetch(`/api/documents/${docId}/pages/${pageNum}/layout?part_id=${partId}`),
      fetch(`/api/documents/${docId}/pages/${pageNum}/corrections?part_id=${partId}`),
    ]);

    if (!textRes.ok) throw new Error("텍스트 API 응답 오류");
    const textData = await textRes.json();
    correctionState.pageText = textData.text || "";

    if (layoutRes.ok) {
      const layoutData = await layoutRes.json();
      correctionState.blocks = layoutData.blocks || [];
      correctionState.hasLayout = correctionState.blocks.length > 0;
    } else {
      correctionState.blocks = [];
      correctionState.hasLayout = false;
    }

    if (corrRes.ok) {
      const corrData = await corrRes.json();
      correctionState.corrections = corrData.corrections || [];
    } else {
      correctionState.corrections = [];
    }

    correctionState.isDirty = false;
    correctionState.selectedCharInfo = null;
    correctionState.editingCorrIdx = -1;

    _renderCorrectionView();
    _renderCorrList();
    _updateCorrCount();
    _updateCorrSaveStatus(correctionState.corrections.length > 0 ? "saved" : "empty");

    // Git 이력도 로드
    _loadGitLog(docId);

  } catch (err) {
    console.error("교정 데이터 로드 실패:", err);
    _updateCorrSaveStatus("error");
  }
}


/* ──────────────────────────
   텍스트 렌더링: 글자 단위 + 블록별 섹션
   ────────────────────────── */

/**
 * 텍스트를 글자 단위 <span>으로 렌더링한다.
 *
 * 왜 이렇게 하는가:
 *   - textarea는 개별 글자에 클릭 이벤트나 스타일을 부여할 수 없다.
 *   - div + span 구조를 사용하면 글자 단위 선택, 하이라이팅, 툴팁이 가능하다.
 *   - [本文], [注釈] 마커가 있으면 블록별 섹션으로 나눈다.
 */
function _renderCorrectionView() {
  const container = document.getElementById("corr-text-area");
  if (!container) return;

  const text = correctionState.pageText;
  if (!text) {
    container.innerHTML = '<div class="placeholder">이 페이지에 텍스트가 없습니다. 열람 모드에서 먼저 텍스트를 입력하세요.</div>';
    return;
  }

  // [本文] / [注釈] 마커로 텍스트를 블록 세그먼트로 분할
  const segments = _splitTextIntoSegments(text);

  // 블록 필터 드롭다운 업데이트
  _updateBlockFilterOptions(segments);

  container.innerHTML = "";

  if (segments.length > 1 || correctionState.hasLayout) {
    // 블록별 섹션으로 렌더링
    segments.forEach((seg, segIdx) => {
      const section = _createBlockSection(seg, segIdx);
      container.appendChild(section);
    });
  } else {
    // 단일 섹션 (마커 없음)
    const charContainer = document.createElement("div");
    charContainer.className = "corr-block-body";
    _renderCharsIntoElement(charContainer, text, 0, null);
    container.appendChild(charContainer);
  }
}


/**
 * 텍스트를 [本文] / [注釈] 마커로 분할한다.
 *
 * 반환: [{type: "main_text"|"annotation"|"unknown", label, text, startIdx}, ...]
 *
 * 왜 이렇게 하는가: Phase 3에서 텍스트를 [本文], [注釈] 마커로 구분하도록 설계했다.
 *                    이 마커를 기준으로 블록별 섹션을 나눈다.
 */
function _splitTextIntoSegments(text) {
  const markerPattern = /\[(本文|注釈)\]/g;
  const segments = [];
  let lastIdx = 0;
  let lastType = "unknown";
  let lastLabel = "전체";
  let match;

  while ((match = markerPattern.exec(text)) !== null) {
    // 마커 이전 텍스트가 있으면 이전 세그먼트에 추가
    if (match.index > lastIdx) {
      const segText = text.substring(lastIdx, match.index);
      if (segText.trim()) {
        segments.push({
          type: lastType,
          label: lastLabel,
          text: segText,
          startIdx: lastIdx,
        });
      }
    }

    // 마커 유형 결정
    if (match[1] === "本文") {
      lastType = "main_text";
      lastLabel = "本文 (본문)";
    } else {
      lastType = "annotation";
      lastLabel = "注釈 (주석)";
    }

    // 마커 자체는 건너뜀 (텍스트에 포함하지 않음)
    lastIdx = match.index + match[0].length;
  }

  // 마지막 세그먼트
  if (lastIdx < text.length) {
    const segText = text.substring(lastIdx);
    if (segText.trim()) {
      segments.push({
        type: lastType,
        label: lastLabel,
        text: segText,
        startIdx: lastIdx,
      });
    }
  }

  // 세그먼트가 하나도 없으면 전체를 하나로
  if (segments.length === 0) {
    segments.push({
      type: "unknown",
      label: "전체",
      text: text,
      startIdx: 0,
    });
  }

  return segments;
}


/**
 * 블록 섹션 DOM 요소를 생성한다.
 */
function _createBlockSection(segment, segIdx) {
  const section = document.createElement("div");
  section.className = "corr-block-section";
  section.dataset.blockType = segment.type;

  // 블록 타입에 맞는 색상 찾기
  let color = "#D1D5DB";
  if (typeof layoutState !== "undefined" && layoutState.blockTypes) {
    const bt = layoutState.blockTypes.find((t) => t.id === segment.type);
    if (bt) color = bt.color;
  }

  // 헤더
  const header = document.createElement("div");
  header.className = "corr-block-header";
  header.innerHTML = `
    <span class="corr-block-toggle">▶</span>
    <span class="corr-block-color" style="background:${color}"></span>
    <span class="corr-block-label">${segment.label}</span>
    <span class="corr-block-id">seg_${segIdx}</span>
  `;

  // 접기/펴기
  const toggle = header.querySelector(".corr-block-toggle");
  header.addEventListener("click", () => {
    const body = section.querySelector(".corr-block-body");
    if (body.classList.contains("collapsed")) {
      body.classList.remove("collapsed");
      toggle.classList.remove("collapsed");
    } else {
      body.classList.add("collapsed");
      toggle.classList.add("collapsed");
    }
  });

  // 본문
  const body = document.createElement("div");
  body.className = "corr-block-body";
  _renderCharsIntoElement(body, segment.text, segment.startIdx, segment.type);

  section.appendChild(header);
  section.appendChild(body);

  return section;
}


/**
 * 텍스트의 글자들을 span 요소로 렌더링하여 부모 요소에 추가한다.
 *
 * 입력:
 *   parent — 부모 DOM 요소.
 *   text — 렌더링할 텍스트.
 *   globalStartIdx — 전체 텍스트 내에서의 시작 인덱스 (교정 위치 매칭용).
 *   blockType — 블록 유형 (null이면 단일 섹션).
 *
 * 왜 이렇게 하는가: 각 글자를 <span>으로 감싸면 개별 클릭 이벤트와 교정 하이라이팅이 가능하다.
 *                    줄바꿈은 <br>로, 마커 텍스트([本文] 등)는 건너뛴다.
 */
function _renderCharsIntoElement(parent, text, globalStartIdx, blockType) {
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    const globalIdx = globalStartIdx + i;

    if (ch === "\n") {
      parent.appendChild(document.createElement("br"));
      continue;
    }
    if (ch === "\r") continue; // CRLF의 CR은 무시

    const span = document.createElement("span");
    span.className = "corr-char";
    span.textContent = ch;
    span.dataset.idx = globalIdx;
    if (blockType) span.dataset.blockType = blockType;

    // 이 위치에 교정이 있는지 확인
    const corrIdx = _findCorrectionAtIndex(globalIdx);
    if (corrIdx >= 0) {
      const corr = correctionState.corrections[corrIdx];
      const typeInfo = CORRECTION_TYPES[corr.type] || {};
      span.classList.add("corrected", typeInfo.cssClass || "");
      span.dataset.corrIdx = corrIdx;
      // 교정된 글자를 표시 (corrected 값이 있으면 그것으로)
      if (corr.corrected && corr.corrected !== corr.original_ocr) {
        span.textContent = corr.corrected;
      }
      // 툴팁: 원래 글자 → 교정 글자 (유형)
      const typeLabel = typeInfo.label || corr.type;
      span.title = `${corr.original_ocr} → ${corr.corrected} (${typeLabel})`;
      if (corr.note) span.title += `\n${corr.note}`;
    }

    // 클릭 이벤트: 교정 다이얼로그 열기
    span.addEventListener("click", () => {
      _onCharClick(span, globalIdx, ch, blockType, corrIdx);
    });

    parent.appendChild(span);
  }
}


/**
 * 전체 텍스트 인덱스에 해당하는 교정 항목을 찾는다.
 * 반환: corrections 배열 내의 인덱스. 없으면 -1.
 *
 * 왜 이렇게 하는가: char_index 필드가 전체 텍스트 내의 위치를 나타내므로,
 *                    현재 글자 위치와 대조하여 교정 여부를 판단한다.
 */
function _findCorrectionAtIndex(globalIdx) {
  return correctionState.corrections.findIndex(
    (c) => c.char_index === globalIdx
  );
}


/* ──────────────────────────
   글자 클릭 → 교정 다이얼로그
   ────────────────────────── */

/**
 * 글자 span 클릭 시 호출된다.
 * 기존 교정이 있으면 편집, 없으면 새 교정 다이얼로그를 연다.
 */
function _onCharClick(span, globalIdx, originalChar, blockType, existingCorrIdx) {
  // 이전 선택 해제
  document.querySelectorAll(".corr-char.selected").forEach((el) => {
    el.classList.remove("selected");
  });
  span.classList.add("selected");

  correctionState.selectedCharInfo = {
    globalIdx,
    originalChar,
    blockType,
    element: span,
  };

  if (existingCorrIdx >= 0) {
    // 기존 교정 편집
    correctionState.editingCorrIdx = existingCorrIdx;
    _openCorrDialog(correctionState.corrections[existingCorrIdx]);
  } else {
    // 새 교정
    correctionState.editingCorrIdx = -1;
    _openCorrDialog(null);
  }
}


/**
 * 교정 다이얼로그를 연다.
 *
 * 입력: existingCorr — 기존 교정 객체 (null이면 새 교정).
 */
function _openCorrDialog(existingCorr) {
  const overlay = document.getElementById("corr-dialog-overlay");
  if (!overlay) return;

  const titleEl = document.getElementById("corr-dialog-title");
  const typeEl = document.getElementById("corr-type");
  const origEl = document.getElementById("corr-original");
  const correctedEl = document.getElementById("corr-corrected");
  const commonEl = document.getElementById("corr-common-reading");
  const noteEl = document.getElementById("corr-note");
  const confEl = document.getElementById("corr-confidence");
  const confVal = document.getElementById("corr-confidence-val");
  const deleteBtn = document.getElementById("corr-dialog-delete");

  if (existingCorr) {
    // 기존 교정 편집 모드
    titleEl.textContent = "교정 편집";
    typeEl.value = existingCorr.type;
    origEl.value = existingCorr.original_ocr;
    correctedEl.value = existingCorr.corrected;
    commonEl.value = existingCorr.common_reading || "";
    noteEl.value = existingCorr.note || "";
    confEl.value = existingCorr.confidence ?? 0.9;
    confVal.textContent = existingCorr.confidence ?? 0.9;
    deleteBtn.style.display = "";
  } else {
    // 새 교정 모드
    titleEl.textContent = "교정 입력";
    typeEl.value = "ocr_error";
    origEl.value = correctionState.selectedCharInfo?.originalChar || "";
    correctedEl.value = "";
    commonEl.value = "";
    noteEl.value = "";
    confEl.value = 0.9;
    confVal.textContent = "0.9";
    deleteBtn.style.display = "none";
  }

  _toggleCommonReadingField(typeEl.value);
  overlay.style.display = "";

  // 교정 글자 입력에 포커스
  setTimeout(() => correctedEl.focus(), 100);
}


/**
 * variant_reading 유형일 때만 통행 텍스트 필드를 표시한다.
 *
 * 왜 이렇게 하는가: common_reading은 판본 이문(variant_reading) 전용 필드다.
 *                    다른 유형에서는 불필요하므로 숨겨서 UI를 단순화한다.
 */
function _toggleCommonReadingField(type) {
  const group = document.getElementById("corr-common-reading-group");
  if (group) {
    group.style.display = type === "variant_reading" ? "" : "none";
  }
}


/**
 * 교정 다이얼로그를 닫는다.
 */
function _closeCorrDialog() {
  const overlay = document.getElementById("corr-dialog-overlay");
  if (overlay) overlay.style.display = "none";

  // 선택 해제
  document.querySelectorAll(".corr-char.selected").forEach((el) => {
    el.classList.remove("selected");
  });
  correctionState.selectedCharInfo = null;
  correctionState.editingCorrIdx = -1;
}


/**
 * 다이얼로그의 저장 버튼 클릭 시: 교정 항목을 추가/수정한다.
 */
function _saveCorrFromDialog() {
  const info = correctionState.selectedCharInfo;
  if (!info) return;

  const type = document.getElementById("corr-type").value;
  const original = document.getElementById("corr-original").value;
  const corrected = document.getElementById("corr-corrected").value;
  const common = document.getElementById("corr-common-reading").value;
  const note = document.getElementById("corr-note").value;
  const confidence = parseFloat(document.getElementById("corr-confidence").value);

  if (!corrected) {
    alert("교정 글자를 입력하세요.");
    return;
  }

  const corrItem = {
    page: viewerState.pageNum || null,
    block_id: null, // 향후 L3와 더 정교하게 연결 가능
    line: null,
    char_index: info.globalIdx,
    type: type,
    original_ocr: original,
    corrected: corrected,
    common_reading: type === "variant_reading" ? (common || null) : null,
    corrected_by: "human",
    confidence: confidence,
    note: note || null,
  };

  if (correctionState.editingCorrIdx >= 0) {
    // 기존 교정 수정
    correctionState.corrections[correctionState.editingCorrIdx] = corrItem;
  } else {
    // 새 교정 추가
    correctionState.corrections.push(corrItem);
  }

  correctionState.isDirty = true;
  _updateCorrSaveStatus("modified");
  _updateCorrCount();

  _closeCorrDialog();
  _renderCorrectionView();
  _renderCorrList();
}


/**
 * 다이얼로그의 삭제 버튼 클릭 시: 교정 항목을 제거한다.
 */
function _deleteCorrFromDialog() {
  if (correctionState.editingCorrIdx < 0) return;

  if (!confirm("이 교정을 삭제하시겠습니까?")) return;

  correctionState.corrections.splice(correctionState.editingCorrIdx, 1);
  correctionState.isDirty = true;
  _updateCorrSaveStatus("modified");
  _updateCorrCount();

  _closeCorrDialog();
  _renderCorrectionView();
  _renderCorrList();
}


/* ──────────────────────────
   교정 목록 (우측 패널 하단)
   ────────────────────────── */

/**
 * 교정 목록을 렌더링한다.
 */
function _renderCorrList() {
  const listEl = document.getElementById("corr-list");
  if (!listEl) return;

  if (correctionState.corrections.length === 0) {
    listEl.innerHTML = '<div class="placeholder">교정 기록이 없습니다</div>';
    return;
  }

  listEl.innerHTML = "";
  correctionState.corrections.forEach((corr, idx) => {
    const typeInfo = CORRECTION_TYPES[corr.type] || {};
    const typeCls = "type-" + corr.type.replace(/_/g, "-");

    const item = document.createElement("div");
    item.className = "corr-list-item";
    item.innerHTML = `
      <span class="corr-list-type ${typeCls}">${typeInfo.label || corr.type}</span>
      <span class="corr-list-text">${corr.original_ocr}</span>
      <span class="corr-list-arrow">→</span>
      <span class="corr-list-text">${corr.corrected}</span>
      <span class="corr-list-note">${corr.note || ""}</span>
    `;

    // 클릭 시 해당 글자로 스크롤 + 하이라이트
    item.addEventListener("click", () => {
      const charEl = document.querySelector(`.corr-char[data-idx="${corr.char_index}"]`);
      if (charEl) {
        charEl.scrollIntoView({ behavior: "smooth", block: "center" });
        // 잠시 강조 효과
        charEl.classList.add("selected");
        setTimeout(() => charEl.classList.remove("selected"), 1500);
      }
    });

    listEl.appendChild(item);
  });
}


/* ──────────────────────────
   블록 필터
   ────────────────────────── */

/**
 * 블록 필터 드롭다운 옵션을 업데이트한다.
 */
function _updateBlockFilterOptions(segments) {
  const filter = document.getElementById("corr-block-filter");
  if (!filter) return;

  filter.innerHTML = '<option value="all">전체</option>';
  segments.forEach((seg, idx) => {
    const opt = document.createElement("option");
    opt.value = idx;
    opt.textContent = seg.label;
    filter.appendChild(opt);
  });
}

/**
 * 블록 필터를 적용한다.
 */
function _applyBlockFilter(value) {
  const sections = document.querySelectorAll(".corr-block-section");
  if (value === "all") {
    sections.forEach((s) => s.style.display = "");
  } else {
    const idx = parseInt(value, 10);
    sections.forEach((s, i) => {
      s.style.display = i === idx ? "" : "none";
    });
  }
}


/* ──────────────────────────
   교정 저장 (API)
   ────────────────────────── */

/**
 * 현재 페이지의 교정을 API에 저장한다.
 * API가 자동으로 git commit도 수행한다.
 */
async function _saveCorrections() {
  const { docId, partId, pageNum } = viewerState;
  if (!docId || !partId || !pageNum) return;

  _updateCorrSaveStatus("saving");

  const payload = {
    part_id: partId,
    corrections: correctionState.corrections,
  };

  const url = `/api/documents/${docId}/pages/${pageNum}/corrections?part_id=${partId}`;
  try {
    const res = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || "저장 실패");
    }

    const result = await res.json();
    correctionState.isDirty = false;
    _updateCorrSaveStatus("saved");

    // Git 이력 새로고침
    if (result.git && result.git.committed) {
      _loadGitLog(docId);
    }

  } catch (err) {
    console.error("교정 저장 실패:", err);
    _updateCorrSaveStatus("error");
  }
}


/* ──────────────────────────
   상태 표시
   ────────────────────────── */

function _updateCorrSaveStatus(status) {
  const el = document.getElementById("corr-save-status");
  if (!el) return;
  const map = {
    saved: { text: "저장됨", cls: "status-saved" },
    modified: { text: "수정됨", cls: "status-modified" },
    saving: { text: "저장 중...", cls: "status-saving" },
    error: { text: "저장 실패", cls: "status-error" },
    empty: { text: "", cls: "" },
  };
  const info = map[status] || map.empty;
  el.textContent = info.text;
  el.className = "text-save-status " + info.cls;
}

function _updateCorrCount() {
  const el = document.getElementById("corr-count");
  if (el) {
    el.textContent = `교정: ${correctionState.corrections.length}건`;
  }
}


/* ──────────────────────────
   Git 이력 패널 (하단)
   ────────────────────────── */

function _initGitPanelEvents() {
  const backBtn = document.getElementById("git-diff-back");
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      document.getElementById("git-log-list").style.display = "";
      document.getElementById("git-diff-view").style.display = "none";
    });
  }
}

/**
 * 문헌의 git 커밋 이력을 로드하여 하단 패널에 표시한다.
 */
// eslint-disable-next-line no-unused-vars
async function _loadGitLog(docId) {
  if (!docId) return;

  const listEl = document.getElementById("git-log-list");
  if (!listEl) return;

  try {
    const res = await fetch(`/api/documents/${docId}/git/log`);
    if (!res.ok) throw new Error("Git log API 응답 오류");
    const data = await res.json();
    const commits = data.commits || [];

    if (commits.length === 0) {
      listEl.innerHTML = '<div class="placeholder">커밋 이력이 없습니다</div>';
      return;
    }

    listEl.innerHTML = "";
    commits.forEach((c) => {
      const item = document.createElement("div");
      item.className = "git-commit-item";

      // 날짜 포맷: YYYY-MM-DD HH:mm
      const dateStr = _formatDate(c.date);

      item.innerHTML = `
        <span class="git-commit-hash">${c.short_hash}</span>
        <span class="git-commit-msg">${_escapeHtml(c.message)}</span>
        <span class="git-commit-date">${dateStr}</span>
      `;

      // 클릭 시 diff 보기
      item.addEventListener("click", () => {
        _loadGitDiff(docId, c.hash, c.message);
      });

      listEl.appendChild(item);
    });

  } catch (err) {
    console.error("Git log 로드 실패:", err);
    listEl.innerHTML = '<div class="placeholder">Git 이력을 불러올 수 없습니다</div>';
  }
}


/**
 * 특정 커밋의 diff를 로드하여 표시한다.
 */
async function _loadGitDiff(docId, commitHash, message) {
  const logList = document.getElementById("git-log-list");
  const diffView = document.getElementById("git-diff-view");
  const diffTitle = document.getElementById("git-diff-title");
  const diffContent = document.getElementById("git-diff-content");

  if (!diffView || !diffContent) return;

  // 목록 숨기고 diff 표시
  if (logList) logList.style.display = "none";
  diffView.style.display = "";
  if (diffTitle) diffTitle.textContent = `${commitHash.substring(0, 7)} — ${message}`;
  diffContent.innerHTML = '<div class="placeholder">diff를 불러오는 중...</div>';

  try {
    const res = await fetch(`/api/documents/${docId}/git/diff/${commitHash}`);
    if (!res.ok) throw new Error("Git diff API 응답 오류");
    const data = await res.json();
    const diffs = data.diffs || [];

    if (diffs.length === 0) {
      diffContent.innerHTML = '<div class="placeholder">변경 사항이 없습니다</div>';
      return;
    }

    diffContent.innerHTML = "";
    diffs.forEach((d) => {
      const fileDiv = document.createElement("div");
      fileDiv.className = "git-diff-file";

      const filename = document.createElement("div");
      filename.className = "git-diff-filename";
      filename.textContent = `${d.change_type}: ${d.file}`;
      fileDiv.appendChild(filename);

      const diffText = document.createElement("div");
      diffText.className = "git-diff-text";
      // diff 텍스트에 색상 적용
      diffText.innerHTML = _colorizeDiff(d.diff_text || "");
      fileDiv.appendChild(diffText);

      diffContent.appendChild(fileDiv);
    });

  } catch (err) {
    console.error("Git diff 로드 실패:", err);
    diffContent.innerHTML = '<div class="placeholder">diff를 불러올 수 없습니다</div>';
  }
}


/**
 * diff 텍스트에 추가/삭제 행 색상을 적용한다.
 */
function _colorizeDiff(text) {
  if (!text) return "";
  return _escapeHtml(text)
    .split("\n")
    .map((line) => {
      if (line.startsWith("+")) {
        return `<span class="diff-add">${line}</span>`;
      } else if (line.startsWith("-")) {
        return `<span class="diff-del">${line}</span>`;
      } else if (line.startsWith("@@")) {
        return `<span class="diff-hunk">${line}</span>`;
      }
      return line;
    })
    .join("\n");
}


/* ──────────────────────────
   유틸리티
   ────────────────────────── */

function _escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function _formatDate(isoStr) {
  try {
    const d = new Date(isoStr);
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    const hh = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
  } catch (_) {
    return isoStr;
  }
}
