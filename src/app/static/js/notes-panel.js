/**
 * 비고/메모 패널 — 페이지별 자유 텍스트 메모.
 *
 * 목적: 연구자가 아직 어디로 편입될지 미확정인 내용(임시 메모, 질문,
 *       참고 사항 등)을 페이지 단위로 기록하고 관리한다.
 *
 * 저장 위치: {interp_path}/_notes/{part_id}/page_NNN.json
 * 자동저장: 2초 디바운스로 타이핑 중단 후 자동 저장.
 *
 * 의존 전역:
 *   viewerState  (sidebar-tree.js) — docId, partId, pageNum, interpId
 */

/* ─── 상태 ─────────────────────────────────────── */

const notesState = {
  entries: [],         // [{text, created_at, updated_at}, ...]
  loaded: false,       // 현재 페이지의 메모 로드 여부
  saveTimer: null,     // 자동저장 디바운스 타이머
  saving: false,       // 저장 중 여부
};


/* ─── 초기화 ───────────────────────────────────── */

/**
 * 비고 패널을 초기화한다.
 * DOMContentLoaded 후 workspace.js에서 호출한다.
 */
function initNotesPanel() {
  const addBtn = document.getElementById("notes-add-btn");
  if (addBtn) addBtn.addEventListener("click", _addNoteEntry);
}


/* ─── 메모 로드 ────────────────────────────────── */

/**
 * 현재 페이지의 비고를 서버에서 로드하여 표시한다.
 *
 * 왜 이렇게 하는가: 페이지 이동 시마다 호출하여 해당 페이지의 메모를 보여준다.
 *   해석 저장소가 선택되지 않은 경우 비활성 메시지를 표시한다.
 */
async function loadPageNotes() {
  const container = document.getElementById("notes-panel-content");
  if (!container) return;

  const list = document.getElementById("notes-list");
  const status = document.getElementById("notes-save-status");

  // 해석 저장소가 선택되지 않으면 비활성 표시
  if (typeof viewerState === "undefined" || !viewerState.interpId) {
    if (list) list.innerHTML = '<div class="placeholder">해석 저장소를 선택하면 비고를 작성할 수 있습니다</div>';
    notesState.entries = [];
    notesState.loaded = false;
    return;
  }

  const interpId = viewerState.interpId;
  const partId = viewerState.partId || "main";
  const pageNum = viewerState.pageNum;

  if (!pageNum) {
    if (list) list.innerHTML = '<div class="placeholder">페이지를 선택하세요</div>';
    return;
  }

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${pageNum}/notes?part_id=${partId}`
    );
    if (!resp.ok) {
      notesState.entries = [];
      notesState.loaded = true;
      _renderNotes();
      return;
    }

    const data = await resp.json();
    notesState.entries = data.entries || [];
    notesState.loaded = true;
    _renderNotes();
  } catch (e) {
    console.warn("비고 로드 실패:", e);
    notesState.entries = [];
    notesState.loaded = true;
    _renderNotes();
  }
}


/* ─── 메모 저장 (자동저장 2초 디바운스) ───────── */

/**
 * 비고를 서버에 저장한다.
 *
 * 왜 자동저장인가: 연구자가 메모 저장을 잊는 것을 방지.
 *   타이핑이 멈추면 2초 후 자동으로 서버에 전송한다.
 */
async function _saveNotes() {
  if (typeof viewerState === "undefined" || !viewerState.interpId) return;
  if (notesState.saving) return;

  const interpId = viewerState.interpId;
  const partId = viewerState.partId || "main";
  const pageNum = viewerState.pageNum;
  if (!pageNum) return;

  notesState.saving = true;
  const status = document.getElementById("notes-save-status");
  if (status) status.textContent = "저장 중...";

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${pageNum}/notes?part_id=${partId}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entries: notesState.entries }),
      }
    );

    if (resp.ok) {
      if (status) {
        status.textContent = "저장됨";
        setTimeout(() => { status.textContent = ""; }, 2000);
      }
    } else {
      if (status) status.textContent = "저장 실패";
    }
  } catch (e) {
    console.warn("비고 저장 실패:", e);
    if (status) status.textContent = "저장 실패";
  } finally {
    notesState.saving = false;
  }
}


/**
 * 자동저장 디바운스를 트리거한다.
 * textarea의 input 이벤트에서 호출된다.
 */
function _scheduleSave() {
  if (notesState.saveTimer) clearTimeout(notesState.saveTimer);
  notesState.saveTimer = setTimeout(_saveNotes, 2000);

  const status = document.getElementById("notes-save-status");
  if (status) status.textContent = "수정됨";
}


/* ─── 메모 항목 관리 ──────────────────────────── */

/**
 * 새 메모 항목을 추가한다.
 */
function _addNoteEntry() {
  const now = new Date().toISOString();
  notesState.entries.push({
    text: "",
    created_at: now,
    updated_at: now,
  });
  _renderNotes();

  // 마지막 항목에 포커스
  requestAnimationFrame(() => {
    const textareas = document.querySelectorAll("#notes-list .notes-textarea");
    if (textareas.length > 0) {
      textareas[textareas.length - 1].focus();
    }
  });
}


/**
 * 메모 항목을 삭제한다.
 */
function _removeNoteEntry(index) {
  notesState.entries.splice(index, 1);
  _renderNotes();
  _scheduleSave();
}


/* ─── 렌더링 ──────────────────────────────────── */

/**
 * 비고 목록을 DOM에 렌더링한다.
 */
function _renderNotes() {
  const list = document.getElementById("notes-list");
  if (!list) return;

  list.innerHTML = "";

  if (notesState.entries.length === 0) {
    list.innerHTML = '<div class="placeholder">메모가 없습니다. "+ 추가" 버튼으로 추가하세요.</div>';
    return;
  }

  notesState.entries.forEach((entry, idx) => {
    const entryEl = document.createElement("div");
    entryEl.className = "notes-entry";

    // 메타 정보 (생성일시 + 삭제 버튼)
    const meta = document.createElement("div");
    meta.className = "notes-meta";

    const dateSpan = document.createElement("span");
    const created = entry.created_at ? new Date(entry.created_at) : new Date();
    dateSpan.textContent = _notesFormatDate(created);
    dateSpan.className = "notes-date";

    const removeBtn = document.createElement("button");
    removeBtn.className = "text-btn notes-remove-btn";
    removeBtn.textContent = "삭제";
    removeBtn.title = "이 메모 삭제";
    removeBtn.addEventListener("click", () => _removeNoteEntry(idx));

    meta.appendChild(dateSpan);
    meta.appendChild(removeBtn);

    // 텍스트 입력
    const textarea = document.createElement("textarea");
    textarea.className = "notes-textarea";
    textarea.value = entry.text || "";
    textarea.placeholder = "메모를 입력하세요...";
    textarea.rows = 3;

    // 입력 시 자동저장 + 상태 갱신
    textarea.addEventListener("input", () => {
      notesState.entries[idx].text = textarea.value;
      notesState.entries[idx].updated_at = new Date().toISOString();
      _scheduleSave();
    });

    entryEl.appendChild(meta);
    entryEl.appendChild(textarea);
    list.appendChild(entryEl);
  });
}


/**
 * 날짜를 간략한 형식으로 포맷한다.
 */
function _notesFormatDate(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  const h = String(date.getHours()).padStart(2, "0");
  const min = String(date.getMinutes()).padStart(2, "0");
  return `${y}-${m}-${d} ${h}:${min}`;
}
