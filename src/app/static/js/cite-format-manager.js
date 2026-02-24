/**
 * cite-format-manager.js — 인용 양식 관리 (액티비티 바 → 사이드바 패널)
 *
 * 학술지마다 다른 원전 인용 양식을 이름 붙여 저장·편집·삭제한다.
 * 저장된 양식은 인용 탭(citation-editor.js)의 드롭다운에서 선택 가능.
 *
 * 저장소: localStorage 키 "cite_format_library"
 * 첫 실행 시 기본 양식 3종을 시드하며, 이후에는 모든 양식이 동등하게
 * 편집·삭제 가능하다.
 *
 * 의존: citation-editor.js (CITE_FIELD_DEFS 상수 참조)
 */

/* ────────────────────────────────────
   상수: 첫 실행 시 시드되는 기본 양식
   ──────────────────────────────────── */

const DEFAULT_FORMATS = [
  {
    id: "korean_academic",
    name: "한국 학술 형식",
    field_order: ["author", "book_volume", "work_page", "punctuated_text", "translation"],
    bracket_replace_single: "none",
    bracket_replace_double: "none",
    wrap_double_quotes: false,
    include_translation: true,
  },
  {
    id: "brief",
    name: "간략 형식",
    field_order: ["author", "work_page", "punctuated_text"],
    bracket_replace_single: "none",
    bracket_replace_double: "none",
    wrap_double_quotes: true,
    include_translation: false,
  },
  {
    id: "text_only",
    name: "원문 중심",
    field_order: ["punctuated_text", "author", "book_volume", "work_page", "translation"],
    bracket_replace_single: "corner_to_angle",
    bracket_replace_double: "corner_to_angle",
    wrap_double_quotes: true,
    include_translation: true,
  },
];

/**
 * 기존 boolean 값 → mode 문자열 변환 (하위 호환).
 * localStorage에 저장된 옛 양식이 true/false를 갖고 있을 수 있다.
 */
function _normalizeBracketMode(val) {
  if (val === true) return "corner_to_angle";
  if (val === false || val == null) return "none";
  return val; // 이미 문자열이면 그대로
}

const CFM_STORAGE_KEY = "cite_format_library";

/* ────────────────────────────────────
   localStorage CRUD
   ──────────────────────────────────── */

/**
 * 양식 라이브러리 전체를 반환한다.
 * 첫 실행 시(localStorage 비어있음) 기본 양식을 시드한다.
 * citation-editor.js에서도 호출하므로 전역 함수로 노출.
 */
function getCiteFormatLibrary() {
  return _loadFormats();
}

/** localStorage에서 양식 배열을 로드. 비어있으면 기본값 시드. */
function _loadFormats() {
  try {
    const raw = localStorage.getItem(CFM_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    }
  } catch { /* 파싱 실패 시 기본값으로 시드 */ }

  // 첫 실행: 기본 양식 시드
  const seed = DEFAULT_FORMATS.map(f => ({ ...f }));
  _saveFormats(seed);
  return seed;
}

/** 양식 배열을 localStorage에 저장 */
function _saveFormats(formats) {
  localStorage.setItem(CFM_STORAGE_KEY, JSON.stringify(formats));
}


/* ────────────────────────────────────
   상태
   ──────────────────────────────────── */

const cfmState = {
  editingId: null,  // 편집 중인 양식 ID (null이면 새 양식)
};


/* ────────────────────────────────────
   초기화
   ──────────────────────────────────── */

function initCiteFormatManager() {
  // + 새 양식 버튼
  const addBtn = document.getElementById("cfm-add-btn");
  if (addBtn) addBtn.addEventListener("click", () => _openFormatEditor(null));

  // 편집 폼 버튼
  const saveBtn = document.getElementById("cfm-save-btn");
  if (saveBtn) saveBtn.addEventListener("click", _saveFormat);

  const cancelBtn = document.getElementById("cfm-cancel-btn");
  if (cancelBtn) cancelBtn.addEventListener("click", _closeFormatEditor);

  const deleteBtn = document.getElementById("cfm-delete-btn");
  if (deleteBtn) deleteBtn.addEventListener("click", _deleteFormat);

  // 초기 렌더
  _renderFormatList();
}


/* ────────────────────────────────────
   양식 목록 렌더링
   ──────────────────────────────────── */

function _renderFormatList() {
  const container = document.getElementById("cfm-format-list");
  if (!container) return;

  const library = getCiteFormatLibrary();
  if (library.length === 0) {
    container.innerHTML = '<div class="placeholder">양식이 없습니다</div>';
    return;
  }

  container.innerHTML = "";
  library.forEach(fmt => {
    const card = document.createElement("div");
    card.className = "cfm-format-card";
    card.dataset.formatId = fmt.id;

    const nameSpan = document.createElement("span");
    nameSpan.className = "cfm-format-name";
    nameSpan.textContent = fmt.name;

    // 편집 + 삭제 버튼
    const btnGroup = document.createElement("span");
    btnGroup.className = "cfm-card-btn-group";

    const editBtn = document.createElement("button");
    editBtn.className = "cfm-card-btn";
    editBtn.title = "편집";
    editBtn.textContent = "편집";
    editBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      _openFormatEditor(fmt.id);
    });

    const delBtn = document.createElement("button");
    delBtn.className = "cfm-card-btn cfm-card-btn-danger";
    delBtn.title = "삭제";
    delBtn.textContent = "삭제";
    delBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      _deleteFormatById(fmt.id, fmt.name);
    });

    btnGroup.appendChild(editBtn);
    btnGroup.appendChild(delBtn);

    card.appendChild(nameSpan);
    card.appendChild(btnGroup);
    container.appendChild(card);
  });
}


/* ────────────────────────────────────
   양식 편집 폼
   ──────────────────────────────────── */

/**
 * 편집 폼을 연다.
 * @param {string|null} formatId — 기존 양식 ID (null이면 새 양식)
 */
function _openFormatEditor(formatId) {
  const panel = document.getElementById("cfm-edit-panel");
  if (!panel) return;

  cfmState.editingId = formatId;

  let data;
  if (formatId) {
    const library = getCiteFormatLibrary();
    data = library.find(f => f.id === formatId);
    if (!data) return;
  } else {
    // 새 양식 기본값
    data = {
      name: "",
      field_order: ["author", "book_volume", "work_page", "punctuated_text", "translation"],
      bracket_replace_single: "none",
      bracket_replace_double: "none",
      wrap_double_quotes: false,
      include_translation: true,
    };
  }

  // 폼 필드 채우기
  const nameInput = document.getElementById("cfm-edit-name");
  if (nameInput) nameInput.value = data.name || "";

  _setCfmSelectValue("cfm-opt-bracket-single", _normalizeBracketMode(data.bracket_replace_single));
  _setCfmSelectValue("cfm-opt-bracket-double", _normalizeBracketMode(data.bracket_replace_double));
  _setCfmChecked("cfm-opt-wrap-quotes", data.wrap_double_quotes);
  _setCfmChecked("cfm-opt-include-trans", data.include_translation);

  // 필드 순서 드래그 목록
  _renderCfmFieldOrderList(data.field_order);

  // 삭제 버튼: 기존 양식이면 표시, 새 양식이면 숨김
  const deleteBtn = document.getElementById("cfm-delete-btn");
  if (deleteBtn) {
    deleteBtn.style.display = formatId ? "" : "none";
  }

  // 편집 패널 제목
  const titleEl = panel.querySelector(".cfm-edit-title");
  if (titleEl) {
    titleEl.textContent = formatId ? "양식 편집" : "새 양식";
  }

  panel.style.display = "";
}

function _closeFormatEditor() {
  const panel = document.getElementById("cfm-edit-panel");
  if (panel) panel.style.display = "none";
  cfmState.editingId = null;
}

function _setCfmChecked(id, value) {
  const el = document.getElementById(id);
  if (el) el.checked = !!value;
}

/** select 요소의 값을 설정하는 헬퍼 */
function _setCfmSelectValue(id, value) {
  const el = document.getElementById(id);
  if (el) el.value = value || "none";
}


/* ────────────────────────────────────
   저장 / 삭제
   ──────────────────────────────────── */

function _saveFormat() {
  const nameInput = document.getElementById("cfm-edit-name");
  const name = (nameInput?.value || "").trim();
  if (!name) {
    if (typeof showToast === "function") showToast("양식 이름을 입력하세요.", "warning");
    return;
  }

  const formatData = {
    id: cfmState.editingId || _generateId(),
    name: name,
    field_order: _getCfmFieldOrder(),
    bracket_replace_single: document.getElementById("cfm-opt-bracket-single")?.value || "none",
    bracket_replace_double: document.getElementById("cfm-opt-bracket-double")?.value || "none",
    wrap_double_quotes: document.getElementById("cfm-opt-wrap-quotes")?.checked || false,
    include_translation: document.getElementById("cfm-opt-include-trans")?.checked || false,
  };

  const formats = _loadFormats();

  if (cfmState.editingId) {
    const idx = formats.findIndex(f => f.id === cfmState.editingId);
    if (idx >= 0) {
      formats[idx] = formatData;
    } else {
      formats.push(formatData);
    }
  } else {
    formats.push(formatData);
  }

  _saveFormats(formats);
  _renderFormatList();
  _closeFormatEditor();

  // 인용 탭의 드롭다운도 갱신
  if (typeof _refreshCitePresetSelect === "function") {
    _refreshCitePresetSelect();
  }

  const statusEl = document.getElementById("cfm-save-status");
  if (statusEl) {
    statusEl.textContent = "저장됨";
    setTimeout(() => { statusEl.textContent = ""; }, 2000);
  }
}

function _deleteFormat() {
  if (!cfmState.editingId) return;
  _deleteFormatById(cfmState.editingId);
}

/**
 * ID로 양식을 삭제한다. 목록 카드와 편집 폼 양쪽에서 호출.
 * @param {string} formatId — 삭제할 양식 ID
 * @param {string} [displayName] — 확인 대화상자에 표시할 이름 (없으면 조회)
 */
function _deleteFormatById(formatId, displayName) {
  const formats = _loadFormats();
  const fmt = formats.find(f => f.id === formatId);
  if (!fmt) return;

  const name = displayName || fmt.name;
  if (!confirm(`"${name}" 양식을 삭제하시겠습니까?`)) return;

  const filtered = formats.filter(f => f.id !== formatId);
  _saveFormats(filtered);
  _renderFormatList();

  // 편집 폼이 해당 양식을 열고 있었으면 닫기
  if (cfmState.editingId === formatId) {
    _closeFormatEditor();
  }

  // 인용 탭 드롭다운 갱신
  if (typeof _refreshCitePresetSelect === "function") {
    _refreshCitePresetSelect();
  }
}

/** 간단한 UUID 생성 (crypto.randomUUID 사용, 폴백 포함) */
function _generateId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  // 폴백: 타임스탬프 + 랜덤
  return "fmt_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 8);
}


/* ────────────────────────────────────
   필드 순서 드래그앤드롭 (사이드바 편집 폼용)
   citation-editor.js의 패턴을 재사용하되
   컨테이너 ID만 다르다 (cfm-field-order-list).
   ──────────────────────────────────── */

let _cfmDragFieldId = null;

function _renderCfmFieldOrderList(fieldOrder) {
  // CITE_FIELD_DEFS는 citation-editor.js에서 정의됨
  const defs = typeof CITE_FIELD_DEFS !== "undefined" ? CITE_FIELD_DEFS : [];
  const container = document.getElementById("cfm-field-order-list");
  if (!container) return;
  container.innerHTML = "";

  fieldOrder.forEach(fieldId => {
    const def = defs.find(f => f.id === fieldId);
    if (!def) return;

    const item = document.createElement("div");
    item.className = "cite-field-order-item";
    item.draggable = true;
    item.dataset.fieldId = fieldId;

    const handle = document.createElement("span");
    handle.className = "cite-field-drag-handle";
    handle.title = "드래그하여 순서 변경";
    handle.textContent = "\u2847";

    const label = document.createElement("span");
    label.className = "cite-field-label";
    label.textContent = def.label;

    item.appendChild(handle);
    item.appendChild(label);

    item.addEventListener("dragstart", _onCfmFieldDragStart);
    item.addEventListener("dragover", _onCfmFieldDragOver);
    item.addEventListener("dragleave", _onCfmFieldDragLeave);
    item.addEventListener("drop", _onCfmFieldDrop);
    item.addEventListener("dragend", _onCfmFieldDragEnd);

    container.appendChild(item);
  });
}

function _onCfmFieldDragStart(e) {
  _cfmDragFieldId = e.currentTarget.dataset.fieldId;
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", _cfmDragFieldId);
  requestAnimationFrame(() => e.currentTarget.classList.add("dragging"));
}

function _onCfmFieldDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = "move";
  const item = e.currentTarget;
  if (item.dataset.fieldId === _cfmDragFieldId) return;
  const rect = item.getBoundingClientRect();
  const midY = rect.top + rect.height / 2;
  item.classList.remove("drag-over-above", "drag-over-below");
  item.classList.add(e.clientY < midY ? "drag-over-above" : "drag-over-below");
}

function _onCfmFieldDragLeave(e) {
  e.currentTarget.classList.remove("drag-over-above", "drag-over-below");
}

function _onCfmFieldDrop(e) {
  e.preventDefault();
  const target = e.currentTarget;
  target.classList.remove("drag-over-above", "drag-over-below");

  const targetFieldId = target.dataset.fieldId;
  if (!_cfmDragFieldId || _cfmDragFieldId === targetFieldId) return;

  const order = _getCfmFieldOrder();
  const fromIdx = order.indexOf(_cfmDragFieldId);
  const toIdx = order.indexOf(targetFieldId);
  if (fromIdx < 0 || toIdx < 0) return;

  order.splice(fromIdx, 1);
  const rect = target.getBoundingClientRect();
  const midY = rect.top + rect.height / 2;
  const insertIdx = e.clientY < midY
    ? order.indexOf(targetFieldId)
    : order.indexOf(targetFieldId) + 1;
  order.splice(insertIdx, 0, _cfmDragFieldId);

  _renderCfmFieldOrderList(order);
}

function _onCfmFieldDragEnd(e) {
  _cfmDragFieldId = null;
  e.currentTarget.classList.remove("dragging");
}

/** 편집 폼의 현재 필드 순서를 반환 */
function _getCfmFieldOrder() {
  const container = document.getElementById("cfm-field-order-list");
  if (!container) return ["author", "book_volume", "work_page", "punctuated_text", "translation"];
  return Array.from(container.querySelectorAll(".cite-field-order-item"))
    .map(el => el.dataset.fieldId);
}
