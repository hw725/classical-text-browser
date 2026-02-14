/**
 * 텍스트 에디터 — 우측 패널 (L4 교정 텍스트)
 *
 * 기능:
 *   1. API에서 페이지별 텍스트를 로드
 *   2. textarea에 표시 및 편집
 *   3. [本文] / [注釈] 블록 섹션 삽입
 *   4. 저장 버튼 또는 Ctrl+S로 API에 PUT
 *   5. 저장 상태 표시 (저장됨 / 수정됨 / 저장 실패)
 *   6. 비저장 변경 시 페이지 전환 경고
 *
 * 의존성: sidebar-tree.js (viewerState)
 *
 * 왜 이렇게 하는가:
 *   - 연구자가 PDF 원본을 보면서 옆에서 직접 텍스트를 입력한다.
 *   - [本文]과 [注釈]으로 블록을 구분하여, 추후 block_type과 연결할 수 있다.
 *   - textarea를 사용하는 이유: plain text 기반이라 단순하고 안정적이며,
 *     향후 더 정교한 에디터로 교체할 수 있다.
 */

/* ──────────────────────────
   에디터 상태
   ────────────────────────── */

const editorState = {
  originalText: "",  // 로드 시의 텍스트 (변경 감지용)
  isDirty: false,    // 수정 여부
};


/**
 * 페이지 텍스트를 API에서 로드하여 에디터에 표시한다.
 *
 * 호출: sidebar-tree.js의 selectPage(), pdf-renderer.js의 syncPageChange()
 * 동작:
 *   1. placeholder를 숨기고 에디터를 표시
 *   2. GET /api/documents/{doc_id}/pages/{page_num}/text?part_id=xx
 *   3. 응답의 text를 textarea에 채움
 *   4. 파일 존재 여부에 따라 상태 표시
 */
// eslint-disable-next-line no-unused-vars
async function loadPageText(docId, partId, pageNum) {
  // placeholder 숨기기, 에디터 표시
  document.getElementById("text-placeholder").style.display = "none";
  document.getElementById("text-editor").style.display = "flex";

  const url = `/api/documents/${docId}/pages/${pageNum}/text?part_id=${partId}`;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error("텍스트 API 응답 오류");
    const data = await res.json();

    const textarea = document.getElementById("text-content");
    textarea.value = data.text;
    editorState.originalText = data.text;
    editorState.isDirty = false;

    // 파일 정보 표시 (파일명만)
    const fileName = data.file_path.split("/").pop();
    document.getElementById("text-file-info").textContent = fileName;

    _updateSaveStatus(data.exists ? "saved" : "new");
  } catch (err) {
    console.error("텍스트 로드 실패:", err);
    _updateSaveStatus("error");
  }
}


/**
 * 현재 텍스트를 API에 저장한다.
 *
 * 동작:
 *   1. viewerState에서 현재 문헌/권/페이지 정보를 가져온다
 *   2. PUT /api/documents/{doc_id}/pages/{page_num}/text?part_id=xx
 *   3. 성공 시 originalText를 갱신하고 isDirty를 false로
 */
async function _saveCurrentText() {
  const { docId, partId, pageNum } = viewerState;
  if (!docId || !partId || !pageNum) return;

  const textarea = document.getElementById("text-content");
  const text = textarea.value;

  _updateSaveStatus("saving");

  const url = `/api/documents/${docId}/pages/${pageNum}/text?part_id=${partId}`;
  try {
    const res = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });

    if (!res.ok) throw new Error("저장 실패");

    editorState.originalText = text;
    editorState.isDirty = false;
    _updateSaveStatus("saved");
  } catch (err) {
    console.error("텍스트 저장 실패:", err);
    _updateSaveStatus("error");
  }
}


/**
 * 저장 상태를 UI에 반영한다.
 *
 * 상태 종류:
 *   - saved: 저장 완료 (초록색)
 *   - new: 새 파일, 아직 저장된 적 없음 (회색)
 *   - modified: 수정됨, 저장 필요 (노란색)
 *   - saving: 저장 중 (파란색)
 *   - error: 저장 실패 (빨간색)
 */
function _updateSaveStatus(status) {
  const el = document.getElementById("text-save-status");
  const map = {
    saved: { text: "저장됨", cls: "status-saved" },
    new: { text: "새 파일", cls: "status-new" },
    modified: { text: "수정됨", cls: "status-modified" },
    saving: { text: "저장 중...", cls: "status-saving" },
    error: { text: "저장 실패", cls: "status-error" },
  };
  const info = map[status] || map.saved;
  el.textContent = info.text;
  el.className = "text-save-status " + info.cls;
}


/**
 * 비저장 변경이 있을 때 확인 대화상자를 표시한다.
 *
 * 반환: true면 이동 허용, false면 이동 취소.
 * 호출: sidebar-tree.js, pdf-renderer.js에서 페이지 전환 시 호출한다.
 *
 * 왜 이렇게 하는가: 연구자가 텍스트를 입력 중에 실수로 다른 페이지를
 *                    클릭하면 입력 내용이 사라지므로, 경고를 표시한다.
 */
// eslint-disable-next-line no-unused-vars
function checkUnsavedChanges() {
  if (!editorState.isDirty) return true;
  return confirm("수정된 내용이 저장되지 않았습니다.\n저장하지 않고 이동하시겠습니까?");
}


/**
 * textarea의 커서 위치에 텍스트를 삽입한다.
 *
 * 왜 이렇게 하는가: [本文], [注釈] 블록 마커를 편리하게 삽입하기 위해
 *                    버튼을 제공한다. 커서 위치에 삽입하면 자연스럽다.
 */
function _insertAtCursor(textarea, text) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const before = textarea.value.substring(0, start);
  const after = textarea.value.substring(end);
  textarea.value = before + text + after;
  textarea.selectionStart = textarea.selectionEnd = start + text.length;
  textarea.focus();

  // 변경 감지 트리거
  textarea.dispatchEvent(new Event("input"));
}


/**
 * 텍스트 에디터의 이벤트 리스너를 초기화한다.
 *
 * DOMContentLoaded 시 workspace.js에서 호출된다.
 */
// eslint-disable-next-line no-unused-vars
function initTextEditor() {
  const textarea = document.getElementById("text-content");
  if (!textarea) return;

  // 변경 감지 — 텍스트가 원본과 다르면 "수정됨" 상태로
  textarea.addEventListener("input", () => {
    editorState.isDirty = textarea.value !== editorState.originalText;
    if (editorState.isDirty) {
      _updateSaveStatus("modified");
    } else {
      _updateSaveStatus("saved");
    }
  });

  // 저장 버튼
  document.getElementById("text-save").addEventListener("click", _saveCurrentText);

  // Ctrl+S 단축키
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key === "s") {
      e.preventDefault();
      if (viewerState.docId) {
        _saveCurrentText();
      }
    }
  });

  // [本文] 삽입 버튼
  document.getElementById("text-insert-main").addEventListener("click", () => {
    _insertAtCursor(textarea, "[本文]\n");
  });

  // [注釈] 삽입 버튼
  document.getElementById("text-insert-anno").addEventListener("click", () => {
    _insertAtCursor(textarea, "\n[注釈]\n");
  });
}
