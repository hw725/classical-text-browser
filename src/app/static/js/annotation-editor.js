/**
 * annotation-editor.js — L7 주석 편집기
 *
 * Phase 11-3: 원문에 인물·지명·용어·전거·메모 주석을 붙이는 편집기.
 * 주석은 블록 단위로 관리하며, 유형별 색상 하이라이팅 + 편집 패널 제공.
 *
 * 의존: workspace.js (viewerState), sidebar-tree.js (viewerState)
 */

/* ────────────────────────────────────
   상태
   ──────────────────────────────────── */

const annState = {
  active: false,
  originalText: "",
  blockId: "",
  annotations: [],     // 현재 블록의 주석 배열
  annotationTypes: [],  // 전체 유형 목록 (types + custom)
  selectedAnnId: null,  // 편집 중인 주석 ID
};


/* ────────────────────────────────────
   초기화 / 모드 전환
   ──────────────────────────────────── */

function initAnnotationEditor() {
  // 블록 선택
  const blockSel = document.getElementById("ann-block-select");
  if (blockSel) blockSel.addEventListener("change", _onAnnBlockChange);

  // 유형 필터
  const typeFilter = document.getElementById("ann-type-filter");
  if (typeFilter) typeFilter.addEventListener("change", _renderAnnList);

  // 버튼
  const aiBtn = document.getElementById("ann-ai-tag-btn");
  if (aiBtn) aiBtn.addEventListener("click", _aiTagAll);

  const commitAllBtn = document.getElementById("ann-commit-all-btn");
  if (commitAllBtn) commitAllBtn.addEventListener("click", _commitAllDrafts);

  const typeMgmtBtn = document.getElementById("ann-type-mgmt-btn");
  if (typeMgmtBtn) typeMgmtBtn.addEventListener("click", _showTypeMgmtDialog);

  // 편집 패널 버튼
  const editSave = document.getElementById("ann-edit-save-btn");
  if (editSave) editSave.addEventListener("click", _saveEditedAnnotation);

  const editAccept = document.getElementById("ann-edit-accept-btn");
  if (editAccept) editAccept.addEventListener("click", _acceptAnnotation);

  const editDelete = document.getElementById("ann-edit-delete-btn");
  if (editDelete) editDelete.addEventListener("click", _deleteAnnotation);

  const editCancel = document.getElementById("ann-edit-cancel-btn");
  if (editCancel) editCancel.addEventListener("click", _closeEditPanel);
}


function activateAnnotationMode() {
  annState.active = true;
  _loadAnnotationTypes();
  _populateAnnBlockSelect();
}

function deactivateAnnotationMode() {
  annState.active = false;
  annState.selectedAnnId = null;
  const editPanel = document.getElementById("ann-edit-panel");
  if (editPanel) editPanel.style.display = "none";
}


/* ────────────────────────────────────
   유형 로드
   ──────────────────────────────────── */

async function _loadAnnotationTypes() {
  try {
    const resp = await fetch("/api/annotation-types");
    if (resp.ok) {
      const data = await resp.json();
      annState.annotationTypes = data.all || [];
      _populateTypeFilter();
      _populateEditTypeSelect();
    }
  } catch (e) {
    console.error("주석 유형 로드 실패:", e);
  }
}

function _populateTypeFilter() {
  const sel = document.getElementById("ann-type-filter");
  if (!sel) return;
  sel.innerHTML = '<option value="">전체 유형</option>';
  for (const t of annState.annotationTypes) {
    const opt = document.createElement("option");
    opt.value = t.id;
    opt.textContent = `${t.icon || ""} ${t.label}`;
    sel.appendChild(opt);
  }
}

function _populateEditTypeSelect() {
  const sel = document.getElementById("ann-edit-type");
  if (!sel) return;
  sel.innerHTML = "";
  for (const t of annState.annotationTypes) {
    const opt = document.createElement("option");
    opt.value = t.id;
    opt.textContent = `${t.icon || ""} ${t.label}`;
    sel.appendChild(opt);
  }
}

function _getTypeInfo(typeId) {
  return annState.annotationTypes.find(t => t.id === typeId) || { label: typeId, color: "#999", icon: "🏷️" };
}


/* ────────────────────────────────────
   블록 선택
   ──────────────────────────────────── */

async function _populateAnnBlockSelect() {
  const sel = document.getElementById("ann-block-select");
  if (!sel) return;
  sel.innerHTML = '<option value="">블록 선택</option>';

  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  if (!vs || !vs.docId || !vs.pageNum) return;

  try {
    const resp = await fetch(`/api/documents/${vs.docId}/pages/${vs.pageNum}/layout`);
    if (!resp.ok) return;
    const layout = await resp.json();
    const blocks = layout.blocks || [];

    for (const b of blocks) {
      const opt = document.createElement("option");
      opt.value = b.block_id;
      opt.textContent = `${b.block_id} (${b.block_type || "?"})`;
      sel.appendChild(opt);
    }

    if (blocks.length > 0) {
      sel.value = blocks[0].block_id;
      _onAnnBlockChange();
    }
  } catch (e) {
    console.error("블록 목록 로드 실패:", e);
  }
}

async function _onAnnBlockChange() {
  const sel = document.getElementById("ann-block-select");
  const blockId = sel ? sel.value : "";
  if (!blockId) return;

  annState.blockId = blockId;
  annState.selectedAnnId = null;
  const editPanel = document.getElementById("ann-edit-panel");
  if (editPanel) editPanel.style.display = "none";

  await Promise.all([
    _loadBlockText(blockId),
    _loadBlockAnnotations(blockId),
  ]);

  _renderSourceText();
  _renderAnnList();
  _renderStatusSummary();
}


/* ────────────────────────────────────
   데이터 로드
   ──────────────────────────────────── */

async function _loadBlockText(blockId) {
  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  if (!vs || !vs.docId || !vs.pageNum) return;

  try {
    const resp = await fetch(`/api/documents/${vs.docId}/pages/${vs.pageNum}/text`);
    if (!resp.ok) return;
    const data = await resp.json();
    // L4 텍스트에서 블록 찾기
    const blocks = data.blocks || [];
    const block = blocks.find(b => b.block_id === blockId);
    annState.originalText = block ? block.text : (data.text || "");
  } catch (e) {
    console.error("텍스트 로드 실패:", e);
    annState.originalText = "";
  }
}

async function _loadBlockAnnotations(blockId) {
  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";

  try {
    const resp = await fetch(`/api/interpretations/${interpId}/pages/${vs.pageNum}/annotations`);
    if (!resp.ok) {
      annState.annotations = [];
      return;
    }
    const data = await resp.json();
    const blocks = data.blocks || [];
    const block = blocks.find(b => b.block_id === blockId);
    annState.annotations = block ? block.annotations : [];
  } catch (e) {
    console.error("주석 로드 실패:", e);
    annState.annotations = [];
  }
}


/* ────────────────────────────────────
   원문 렌더링 (하이라이팅)
   ──────────────────────────────────── */

function _renderSourceText() {
  const container = document.getElementById("ann-source-text");
  if (!container) return;

  const text = annState.originalText;
  if (!text) {
    container.textContent = "(텍스트 없음)";
    return;
  }

  // 글자별 하이라이트 색상 매핑
  const charColors = new Array(text.length).fill(null);
  const charAnnIds = new Array(text.length).fill(null);

  for (const ann of annState.annotations) {
    const start = ann.target.start;
    const end = ann.target.end;
    const typeInfo = _getTypeInfo(ann.type);

    for (let i = start; i <= end && i < text.length; i++) {
      charColors[i] = typeInfo.color;
      charAnnIds[i] = ann.id;
    }
  }

  // HTML 생성
  container.innerHTML = "";
  let i = 0;
  while (i < text.length) {
    if (charColors[i]) {
      const color = charColors[i];
      const annId = charAnnIds[i];
      const span = document.createElement("span");
      span.className = "ann-highlight";
      span.style.backgroundColor = color + "30"; // 반투명
      span.style.borderBottom = `2px solid ${color}`;
      span.dataset.annId = annId;
      span.title = _getAnnotationTooltip(annId);

      // 같은 색상+annId가 연속되는 글자를 모음
      let j = i;
      while (j < text.length && charAnnIds[j] === annId) j++;
      span.textContent = text.slice(i, j);
      span.addEventListener("click", () => _selectAnnotation(annId));
      container.appendChild(span);
      i = j;
    } else {
      // 하이라이트 없는 글자
      const span = document.createElement("span");
      span.className = "ann-plain-char";
      // 같은 null 연속 모음
      let j = i;
      while (j < text.length && !charColors[j]) j++;
      span.textContent = text.slice(i, j);
      // 텍스트 범위 선택으로 수동 주석 추가 지원
      span.addEventListener("mouseup", _onTextSelection);
      container.appendChild(span);
      i = j;
    }
  }
}

function _getAnnotationTooltip(annId) {
  const ann = annState.annotations.find(a => a.id === annId);
  if (!ann) return "";
  const typeInfo = _getTypeInfo(ann.type);
  return `${typeInfo.icon} ${ann.content.label} [${ann.status}]`;
}


/* ────────────────────────────────────
   텍스트 범위 선택 → 수동 주석 추가
   ──────────────────────────────────── */

function _onTextSelection() {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed) return;

  const text = annState.originalText;
  const selectedText = selection.toString();
  if (!selectedText || selectedText.length === 0) return;

  // 원문에서 선택된 텍스트의 위치 찾기
  const startIdx = text.indexOf(selectedText);
  if (startIdx === -1) return;

  const endIdx = startIdx + selectedText.length - 1;

  const typeId = prompt(
    `"${selectedText}"에 주석을 추가합니다.\n유형을 입력하세요 (person/place/term/allusion/note):`,
    "note"
  );
  if (!typeId) return;

  const label = prompt("표제어:", selectedText);
  if (label === null) return;

  const desc = prompt("설명:", "");
  if (desc === null) return;

  _addManualAnnotation(startIdx, endIdx, typeId, label, desc || "");
  selection.removeAllRanges();
}

async function _addManualAnnotation(start, end, typeId, label, description) {
  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";
  const blockId = annState.blockId;

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${vs.pageNum}/annotations/${blockId}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target: { start, end },
          type: typeId,
          content: { label, description, references: [] },
        }),
      }
    );

    if (resp.ok) {
      await _loadBlockAnnotations(blockId);
      _renderSourceText();
      _renderAnnList();
      _renderStatusSummary();
    }
  } catch (e) {
    console.error("주석 추가 실패:", e);
  }
}


/* ────────────────────────────────────
   주석 목록 렌더링
   ──────────────────────────────────── */

function _renderAnnList() {
  const container = document.getElementById("ann-list");
  if (!container) return;

  const typeFilter = document.getElementById("ann-type-filter");
  const filterType = typeFilter ? typeFilter.value : "";

  let anns = annState.annotations;
  if (filterType) {
    anns = anns.filter(a => a.type === filterType);
  }

  if (anns.length === 0) {
    container.innerHTML = '<div class="placeholder">주석이 없습니다. 텍스트를 선택하거나 AI 태깅을 실행하세요.</div>';
    return;
  }

  // start 순으로 정렬
  anns.sort((a, b) => a.target.start - b.target.start);

  container.innerHTML = "";
  for (const ann of anns) {
    const typeInfo = _getTypeInfo(ann.type);
    const card = document.createElement("div");
    card.className = "ann-card";
    if (ann.id === annState.selectedAnnId) card.classList.add("ann-card-selected");

    const sourceText = annState.originalText.slice(ann.target.start, ann.target.end + 1);

    const statusClass = ann.status === "accepted" ? "ann-status-accepted"
                      : ann.status === "draft" ? "ann-status-draft"
                      : "ann-status-reviewed";

    card.innerHTML = `
      <div class="ann-card-header">
        <span class="ann-card-type" style="color:${typeInfo.color}">${typeInfo.icon} ${typeInfo.label}</span>
        <span class="ann-card-range">"${sourceText}" [${ann.target.start}–${ann.target.end}]</span>
        <span class="ann-card-status ${statusClass}">${ann.status}</span>
      </div>
      <div class="ann-card-body">
        <div class="ann-card-label">${ann.content.label}</div>
        <div class="ann-card-desc">${ann.content.description}</div>
      </div>
    `;

    card.addEventListener("click", () => _selectAnnotation(ann.id));
    container.appendChild(card);
  }
}

function _renderStatusSummary() {
  const el = document.getElementById("ann-status-summary");
  if (!el) return;

  const total = annState.annotations.length;
  const accepted = annState.annotations.filter(a => a.status === "accepted").length;
  const draft = annState.annotations.filter(a => a.status === "draft").length;

  el.textContent = `전체 ${total} / 확정 ${accepted} / 초안 ${draft}`;
}


/* ────────────────────────────────────
   주석 선택 → 편집 패널
   ──────────────────────────────────── */

function _selectAnnotation(annId) {
  annState.selectedAnnId = annId;
  const ann = annState.annotations.find(a => a.id === annId);
  if (!ann) return;

  const editPanel = document.getElementById("ann-edit-panel");
  if (editPanel) editPanel.style.display = "";

  // 폼 채우기
  const typeSelect = document.getElementById("ann-edit-type");
  if (typeSelect) typeSelect.value = ann.type;

  const labelInput = document.getElementById("ann-edit-label");
  if (labelInput) labelInput.value = ann.content.label || "";

  const descInput = document.getElementById("ann-edit-desc");
  if (descInput) descInput.value = ann.content.description || "";

  const refsInput = document.getElementById("ann-edit-refs");
  if (refsInput) refsInput.value = (ann.content.references || []).join(", ");

  // 목록 하이라이트 갱신
  _renderAnnList();
}

function _closeEditPanel() {
  annState.selectedAnnId = null;
  const editPanel = document.getElementById("ann-edit-panel");
  if (editPanel) editPanel.style.display = "none";
  _renderAnnList();
}


/* ────────────────────────────────────
   편집 패널 액션
   ──────────────────────────────────── */

async function _saveEditedAnnotation() {
  if (!annState.selectedAnnId) return;

  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";
  const blockId = annState.blockId;
  const annId = annState.selectedAnnId;

  const typeSelect = document.getElementById("ann-edit-type");
  const labelInput = document.getElementById("ann-edit-label");
  const descInput = document.getElementById("ann-edit-desc");
  const refsInput = document.getElementById("ann-edit-refs");

  const refs = (refsInput && refsInput.value)
    ? refsInput.value.split(",").map(s => s.trim()).filter(Boolean)
    : [];

  const updates = {
    type: typeSelect ? typeSelect.value : undefined,
    content: {
      label: labelInput ? labelInput.value : "",
      description: descInput ? descInput.value : "",
      references: refs,
    },
  };

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${vs.pageNum}/annotations/${blockId}/${annId}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      }
    );

    if (resp.ok) {
      _showSaveStatus("수정 완료");
      await _loadBlockAnnotations(blockId);
      _renderSourceText();
      _renderAnnList();
      _renderStatusSummary();
    }
  } catch (e) {
    console.error("주석 수정 실패:", e);
  }
}

async function _acceptAnnotation() {
  if (!annState.selectedAnnId) return;

  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";
  const blockId = annState.blockId;
  const annId = annState.selectedAnnId;

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${vs.pageNum}/annotations/${blockId}/${annId}/commit`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      }
    );

    if (resp.ok) {
      _showSaveStatus("승인 완료");
      await _loadBlockAnnotations(blockId);
      _renderSourceText();
      _renderAnnList();
      _renderStatusSummary();
    }
  } catch (e) {
    console.error("주석 승인 실패:", e);
  }
}

async function _deleteAnnotation() {
  if (!annState.selectedAnnId) return;
  if (!confirm("이 주석을 삭제하시겠습니까?")) return;

  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";
  const blockId = annState.blockId;
  const annId = annState.selectedAnnId;

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${vs.pageNum}/annotations/${blockId}/${annId}`,
      { method: "DELETE" }
    );

    if (resp.ok || resp.status === 204) {
      annState.selectedAnnId = null;
      _closeEditPanel();
      _showSaveStatus("삭제 완료");
      await _loadBlockAnnotations(blockId);
      _renderSourceText();
      _renderAnnList();
      _renderStatusSummary();
    }
  } catch (e) {
    console.error("주석 삭제 실패:", e);
  }
}


/* ────────────────────────────────────
   AI 태깅 / 일괄 확정
   ──────────────────────────────────── */

function _aiTagAll() {
  alert("AI 자동 태깅은 LLM 연동이 필요합니다.\n현재는 수동 주석만 지원합니다.");
}

async function _commitAllDrafts() {
  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${vs.pageNum}/annotations/commit-all`,
      { method: "POST" }
    );

    if (resp.ok) {
      const result = await resp.json();
      _showSaveStatus(`${result.committed}개 확정`);
      await _loadBlockAnnotations(annState.blockId);
      _renderSourceText();
      _renderAnnList();
      _renderStatusSummary();
    }
  } catch (e) {
    console.error("일괄 확정 실패:", e);
  }
}


/* ────────────────────────────────────
   유형 관리 다이얼로그
   ──────────────────────────────────── */

async function _showTypeMgmtDialog() {
  const id = prompt("새 유형 ID (영문, 예: sutra_ref):");
  if (!id) return;

  const label = prompt("유형 이름 (한글):");
  if (!label) return;

  const color = prompt("색상 (예: #FF6600):", "#888888");
  if (!color) return;

  const icon = prompt("아이콘 (이모지):", "🏷️");

  try {
    const resp = await fetch("/api/annotation-types", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, label, color, icon: icon || "🏷️" }),
    });

    if (resp.ok) {
      _showSaveStatus("유형 추가 완료");
      await _loadAnnotationTypes();
    } else {
      const err = await resp.json();
      alert("유형 추가 실패: " + (err.error || "알 수 없는 오류"));
    }
  } catch (e) {
    console.error("유형 추가 실패:", e);
  }
}


/* ────────────────────────────────────
   유틸리티
   ──────────────────────────────────── */

function _showSaveStatus(msg) {
  const el = document.getElementById("ann-save-status");
  if (!el) return;
  el.textContent = msg;
  setTimeout(() => { el.textContent = ""; }, 2000);
}
