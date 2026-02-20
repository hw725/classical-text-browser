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

  // (LLM 모델 목록은 workspace.js의 _loadAllLlmModelSelects()가 일괄 로드)

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

  // 사전형 주석 UI 초기화
  initDictAnnotation();
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
        ${_renderDictBadge(ann)}
        <span class="ann-card-status ${statusClass}">${ann.status}</span>
      </div>
      <div class="ann-card-body">
        <div class="ann-card-label">${ann.content.label}</div>
        <div class="ann-card-desc">${ann.content.description}</div>
        ${_renderDictExpanded(ann)}
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

  // 사전 편집 필드 채우기
  if (typeof _populateDictEditFields === "function") {
    _populateDictEditFields(ann);
  }

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

async function _aiTagAll() {
  /* AI 자동 태깅: /api/llm/annotation 호출 → 결과를 개별 주석으로 저장.
   *
   * 흐름:
   *   1. 현재 블록 텍스트를 LLM에 전송
   *   2. LLM이 인명/지명/관직/전고/용어 태깅
   *   3. 각 태깅 결과를 서버 주석 API로 개별 POST (draft 상태)
   *   4. UI 갱신
   */
  const text = annState.originalText;
  if (!text) {
    alert("태깅할 텍스트가 없습니다. 먼저 블록을 선택하세요.");
    return;
  }

  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";
  const blockId = annState.blockId;
  if (!blockId) {
    alert("블록을 먼저 선택하세요.");
    return;
  }

  // 버튼 비활성화 + 진행 표시
  const aiBtn = document.getElementById("ann-ai-tag-btn");
  if (aiBtn) {
    aiBtn.disabled = true;
    aiBtn.textContent = "AI 태깅 중…";
  }

  try {
    // LLM 프로바이더/모델 선택 반영
    const llmSel = typeof getLlmModelSelection === "function"
      ? getLlmModelSelection("ann-llm-model-select")
      : { force_provider: null, force_model: null };

    const reqBody = { text };
    if (llmSel.force_provider) reqBody.force_provider = llmSel.force_provider;
    if (llmSel.force_model) reqBody.force_model = llmSel.force_model;

    // 1. LLM 호출
    const resp = await fetch("/api/llm/annotation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reqBody),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `서버 오류 ${resp.status}`);
    }

    const data = await resp.json();
    const aiAnnotations = data.annotations || [];

    if (aiAnnotations.length === 0) {
      _showSaveStatus("AI가 태깅할 항목을 찾지 못했습니다.");
      return;
    }

    // 2. 각 태깅을 서버 주석으로 저장 (draft 상태)
    let savedCount = 0;
    for (const ann of aiAnnotations) {
      // end 인덱스 보정: LLM이 exclusive end를 줄 수 있으므로 방어
      const start = ann.start;
      let end = ann.end;
      // end가 start보다 작거나 같으면 text 길이로 보정
      if (end <= start && ann.text) {
        end = start + ann.text.length - 1;
      } else if (end > start && end >= text.length) {
        end = text.length - 1;
      }
      // inclusive end 보정: end가 exclusive(start + len)이면 -1
      if (ann.text && (end - start + 1) > ann.text.length) {
        end = start + ann.text.length - 1;
      }

      try {
        const saveResp = await fetch(
          `/api/interpretations/${interpId}/pages/${vs.pageNum}/annotations/${blockId}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              target: { start, end },
              type: ann.type || "term",
              content: {
                label: ann.label || ann.text || "",
                description: ann.description || "",
                references: [],
              },
            }),
          }
        );
        if (saveResp.ok) savedCount++;
      } catch (e) {
        console.warn("주석 저장 실패:", ann, e);
      }
    }

    // 3. UI 갱신
    await _loadBlockAnnotations(blockId);
    _renderSourceText();
    _renderAnnList();
    _renderStatusSummary();
    _showSaveStatus(`AI 태깅 완료: ${savedCount}개 주석 (${data._provider || "LLM"})`);

  } catch (e) {
    console.error("AI 태깅 실패:", e);
    alert("AI 태깅 실패: " + e.message);
  } finally {
    // 버튼 복원
    if (aiBtn) {
      aiBtn.disabled = false;
      aiBtn.textContent = "AI 태깅";
    }
  }
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


/* ────────────────────────────────────
   사전형 주석 (Dictionary Annotation)
   ──────────────────────────────────── */

/**
 * 사전 보기 토글 상태.
 * true이면 주석 카드에 dictionary 필드를 확장 표시.
 */
let _dictViewExpanded = false;

function initDictAnnotation() {
  /* 사전형 주석 UI 초기화.
   * initAnnotationEditor() 이후에 호출한다.
   */

  // 사전 보기 토글
  const toggleBtn = document.getElementById("ann-dict-view-toggle");
  if (toggleBtn) toggleBtn.addEventListener("click", _toggleDictView);

  // 단계별 생성 버튼
  const s1Btn = document.getElementById("ann-dict-stage1-btn");
  if (s1Btn) s1Btn.addEventListener("click", () => _generateDictStage(1));

  const s2Btn = document.getElementById("ann-dict-stage2-btn");
  if (s2Btn) s2Btn.addEventListener("click", () => _generateDictStage(2));

  const s3Btn = document.getElementById("ann-dict-stage3-btn");
  if (s3Btn) s3Btn.addEventListener("click", () => _generateDictStage(3));

  // 일괄 사전 생성
  const batchBtn = document.getElementById("ann-dict-batch-btn");
  if (batchBtn) batchBtn.addEventListener("click", _generateDictBatch);

  // 내보내기/가져오기
  const exportBtn = document.getElementById("ann-dict-export-btn");
  if (exportBtn) exportBtn.addEventListener("click", _exportDictionary);

  const importBtn = document.getElementById("ann-dict-import-btn");
  if (importBtn) importBtn.addEventListener("click", _importDictionary);

  // 사전 편집 저장
  const dictSaveBtn = document.getElementById("ann-dict-save-btn");
  if (dictSaveBtn) dictSaveBtn.addEventListener("click", _saveDictFields);
}


function _toggleDictView() {
  _dictViewExpanded = !_dictViewExpanded;
  const btn = document.getElementById("ann-dict-view-toggle");
  if (btn) btn.textContent = _dictViewExpanded ? "사전 접기" : "사전 펼치기";
  _renderAnnList();
}


/* ── 주석 카드에 사전 정보 확장 표시 ── */

function _renderDictBadge(ann) {
  /* 주석 카드에 사전 단계 뱃지를 HTML 문자열로 반환한다. */
  const stage = ann.current_stage || "none";
  if (stage === "none") return "";

  const labels = {
    "from_original": "1단계",
    "from_translation": "2단계",
    "from_both": "3단계",
    "reviewed": "검토완료",
  };
  const label = labels[stage] || stage;
  return `<span class="ann-dict-badge ann-dict-badge-${stage}">${label}</span>`;
}


function _renderDictExpanded(ann) {
  /* 사전 보기가 확장되었을 때 dictionary 필드를 HTML로 렌더링. */
  if (!_dictViewExpanded) return "";
  const d = ann.dictionary;
  if (!d) return '<div class="ann-dict-empty">사전 항목 없음</div>';

  let html = '<div class="ann-dict-detail">';
  html += `<div class="ann-dict-hw">${d.headword || ""}`;
  if (d.headword_reading) html += ` (${d.headword_reading})`;
  html += "</div>";

  if (d.dictionary_meaning) {
    html += `<div class="ann-dict-meaning"><b>사전적 의미:</b> ${d.dictionary_meaning}</div>`;
  }
  if (d.contextual_meaning) {
    html += `<div class="ann-dict-ctx"><b>문맥적 의미:</b> ${d.contextual_meaning}</div>`;
  }

  if (d.source_references && d.source_references.length > 0) {
    const refs = d.source_references.map(r => r.title + (r.section ? ` ${r.section}` : "")).join(", ");
    html += `<div class="ann-dict-refs"><b>출전:</b> ${refs}</div>`;
  }

  if (d.related_terms && d.related_terms.length > 0) {
    html += `<div class="ann-dict-related"><b>관련어:</b> ${d.related_terms.join(", ")}</div>`;
  }

  html += "</div>";
  return html;
}


/* ── 단계별 사전 생성 ── */

async function _generateDictStage(stageNum) {
  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";
  const blockId = annState.blockId;
  if (!blockId) {
    alert("블록을 먼저 선택하세요.");
    return;
  }

  const btn = document.getElementById(`ann-dict-stage${stageNum}-btn`);
  if (btn) {
    btn.disabled = true;
    btn.textContent = `${stageNum}단계 생성 중…`;
  }

  try {
    const llmSel = typeof getLlmModelSelection === "function"
      ? getLlmModelSelection("ann-llm-model-select")
      : { force_provider: null, force_model: null };

    const reqBody = { block_id: blockId };
    if (llmSel.force_provider) reqBody.force_provider = llmSel.force_provider;
    if (llmSel.force_model) reqBody.force_model = llmSel.force_model;

    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${vs.pageNum}/annotations/generate-stage${stageNum}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqBody),
      }
    );

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `서버 오류 ${resp.status}`);
    }

    const result = await resp.json();
    const count = (result.annotations || []).length;
    _showSaveStatus(`${stageNum}단계 완료: ${count}개 항목`);

    await _loadBlockAnnotations(blockId);
    _renderSourceText();
    _renderAnnList();
    _renderStatusSummary();

  } catch (e) {
    console.error(`${stageNum}단계 사전 생성 실패:`, e);
    alert(`${stageNum}단계 사전 생성 실패: ${e.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = `${stageNum}단계`;
    }
  }
}


async function _generateDictBatch() {
  const is = typeof interpState !== "undefined" ? interpState : null;
  const interpId = (is && is.interpId) || "default";

  if (!confirm("전체 문서에 대해 일괄 사전 생성(3단계 직행)을 실행합니다.\n시간이 걸릴 수 있습니다. 진행하시겠습니까?")) return;

  const btn = document.getElementById("ann-dict-batch-btn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "일괄 생성 중…";
  }

  try {
    const llmSel = typeof getLlmModelSelection === "function"
      ? getLlmModelSelection("ann-llm-model-select")
      : { force_provider: null, force_model: null };

    const reqBody = {};
    if (llmSel.force_provider) reqBody.force_provider = llmSel.force_provider;
    if (llmSel.force_model) reqBody.force_model = llmSel.force_model;

    const resp = await fetch(`/api/interpretations/${interpId}/annotations/generate-batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reqBody),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `서버 오류 ${resp.status}`);
    }

    const result = await resp.json();
    _showSaveStatus(`일괄 생성 완료: ${result.pages_processed}페이지, ${result.total_annotations}개 항목`);

    // 현재 블록 갱신
    if (annState.blockId) {
      await _loadBlockAnnotations(annState.blockId);
      _renderSourceText();
      _renderAnnList();
      _renderStatusSummary();
    }

  } catch (e) {
    console.error("일괄 사전 생성 실패:", e);
    alert("일괄 사전 생성 실패: " + e.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "일괄 사전 생성";
    }
  }
}


/* ── 사전 내보내기/가져오기 ── */

async function _exportDictionary() {
  const is = typeof interpState !== "undefined" ? interpState : null;
  const interpId = (is && is.interpId) || "default";

  try {
    const resp = await fetch(`/api/interpretations/${interpId}/export/dictionary`);
    if (!resp.ok) throw new Error("내보내기 실패");

    const data = await resp.json();
    const count = data.entries ? data.entries.length : 0;

    // JSON 다운로드
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `dictionary_${interpId}.json`;
    a.click();
    URL.revokeObjectURL(url);

    _showSaveStatus(`사전 내보내기: ${count}개 항목`);
  } catch (e) {
    console.error("사전 내보내기 실패:", e);
    alert("사전 내보내기 실패: " + e.message);
  }
}


async function _importDictionary() {
  const is = typeof interpState !== "undefined" ? interpState : null;
  const interpId = (is && is.interpId) || "default";

  // 파일 선택
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".json";
  input.addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    try {
      const text = await file.text();
      const dictData = JSON.parse(text);

      const strategy = prompt(
        "가져오기 전략을 선택하세요:\n- merge: 기존 항목과 병합\n- skip_existing: 기존 항목 건너뛰기\n- overwrite: 기존 항목 덮어쓰기",
        "merge"
      );
      if (!strategy) return;

      const resp = await fetch(`/api/interpretations/${interpId}/import/dictionary`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dictionary_data: dictData,
          merge_strategy: strategy,
        }),
      });

      if (!resp.ok) throw new Error("가져오기 실패");

      const result = await resp.json();
      _showSaveStatus(`가져오기: 새로 ${result.imported}개, 병합 ${result.merged}개, 건너뜀 ${result.skipped}개`);

      // 갱신
      if (annState.blockId) {
        await _loadBlockAnnotations(annState.blockId);
        _renderSourceText();
        _renderAnnList();
      }
    } catch (err) {
      console.error("사전 가져오기 실패:", err);
      alert("사전 가져오기 실패: " + err.message);
    }
  });
  input.click();
}


/* ── 사전 편집 필드 (편집 패널 확장) ── */

function _populateDictEditFields(ann) {
  /* 편집 패널에 사전형 주석 필드를 채운다.
   * _selectAnnotation()에서 호출. */
  const panel = document.getElementById("ann-dict-edit-panel");
  if (!panel) return;

  const d = ann.dictionary || {};
  panel.style.display = "";

  const hw = document.getElementById("ann-dict-headword");
  if (hw) hw.value = d.headword || "";

  const reading = document.getElementById("ann-dict-reading");
  if (reading) reading.value = d.headword_reading || "";

  const dictMeaning = document.getElementById("ann-dict-meaning");
  if (dictMeaning) dictMeaning.value = d.dictionary_meaning || "";

  const ctxMeaning = document.getElementById("ann-dict-ctx-meaning");
  if (ctxMeaning) ctxMeaning.value = d.contextual_meaning || "";

  const refs = document.getElementById("ann-dict-src-refs");
  if (refs) refs.value = (d.source_references || []).map(r => r.title).join(", ");

  const related = document.getElementById("ann-dict-related");
  if (related) related.value = (d.related_terms || []).join(", ");

  const notes = document.getElementById("ann-dict-notes");
  if (notes) notes.value = d.notes || "";
}


async function _saveDictFields() {
  /* 사전 편집 필드를 서버에 저장한다. */
  if (!annState.selectedAnnId) return;

  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";
  const blockId = annState.blockId;
  const annId = annState.selectedAnnId;

  const hw = document.getElementById("ann-dict-headword");
  const reading = document.getElementById("ann-dict-reading");
  const dictMeaning = document.getElementById("ann-dict-meaning");
  const ctxMeaning = document.getElementById("ann-dict-ctx-meaning");
  const refs = document.getElementById("ann-dict-src-refs");
  const related = document.getElementById("ann-dict-related");
  const notes = document.getElementById("ann-dict-notes");

  const sourceRefs = refs && refs.value
    ? refs.value.split(",").map(s => ({ title: s.trim() })).filter(r => r.title)
    : [];

  const relatedTerms = related && related.value
    ? related.value.split(",").map(s => s.trim()).filter(Boolean)
    : [];

  const dictionary = {
    headword: hw ? hw.value : "",
    headword_reading: reading ? reading.value || null : null,
    dictionary_meaning: dictMeaning ? dictMeaning.value : "",
    contextual_meaning: ctxMeaning ? ctxMeaning.value || null : null,
    source_references: sourceRefs,
    related_terms: relatedTerms,
    notes: notes ? notes.value || null : null,
  };

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${vs.pageNum}/annotations/${blockId}/${annId}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dictionary }),
      }
    );

    if (resp.ok) {
      _showSaveStatus("사전 필드 저장 완료");
      await _loadBlockAnnotations(blockId);
      _renderAnnList();
    }
  } catch (e) {
    console.error("사전 필드 저장 실패:", e);
  }
}
