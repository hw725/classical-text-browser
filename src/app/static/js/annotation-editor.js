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
  blockId: "", // "tb:<id>" (TextBlock) 또는 LayoutBlock ID
  annotations: [], // 현재 블록의 주석 배열
  punctMarks: [], // 표점 marks (원문 미리보기에 적용)
  annotationTypes: [], // 전체 유형 목록 (types + custom)
  selectedAnnId: null, // 편집 중인 주석 ID
};

/**
 * API용 block_id 반환 — "tb:" 접두사 제거.
 * 표점·번역·주석 모두 서버에는 접두사 없이 저장해야
 * block_id 매칭이 일치한다.
 */
function _annApiBlockId() {
  return annState.blockId.startsWith("tb:")
    ? annState.blockId.slice(3)
    : annState.blockId;
}

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

  // 리셋 버튼: 현재 페이지의 모든 주석 삭제
  const resetBtn = document.getElementById("ann-reset-btn");
  if (resetBtn) resetBtn.addEventListener("click", _resetAllAnnotations);

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
  return (
    annState.annotationTypes.find((t) => t.id === typeId) || {
      label: typeId,
      color: "#999",
      icon: "註",
    }
  );
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
  const previousBlockId =
    annState.blockId ||
    (typeof transState !== "undefined" ? transState.blockId : "") ||
    (typeof hyeontoState !== "undefined" ? hyeontoState.blockId : "") ||
    (typeof punctState !== "undefined" ? punctState.blockId : "");

  // TextBlock이 있으면 우선 사용 (번역 편집기와 동일한 block_id 체계).
  // 왜: 표점·번역이 TextBlock ID로 저장되므로, 주석에서도 같은 ID를
  //     사용해야 블록 간 데이터 연결이 일관된다.
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (is && is.interpId) {
    try {
      const tbRes = await fetch(
        `/api/interpretations/${is.interpId}/entities/text_block?page=${vs.pageNum}&document_id=${vs.docId}`,
      );
      if (tbRes.ok) {
        const tbData = await tbRes.json();
        const textBlocks = (tbData.entities || [])
          .filter((e) => {
            const refs = e.source_refs || [];
            const ref = e.source_ref;
            if (refs.length > 0) return refs.some((r) => r.page === vs.pageNum);
            if (ref) return ref.page === vs.pageNum;
            return false;
          })
          .sort((a, b) => (a.sequence_index || 0) - (b.sequence_index || 0));

        if (textBlocks.length > 0) {
          textBlocks.forEach((tb) => {
            const opt = document.createElement("option");
            opt.value = `tb:${tb.id}`;
            const refs = tb.source_refs || [];
            const srcLabel = refs
              .map((r) => r.layout_block_id || "?")
              .join("+");
            opt.textContent = `#${tb.sequence_index} TextBlock (${srcLabel})`;
            opt.dataset.text = tb.original_text || "";
            sel.appendChild(opt);
          });

          // 이전 선택값 복원 또는 첫 번째 블록 자동 선택
          if (
            previousBlockId &&
            sel.querySelector(`option[value="${previousBlockId}"]`)
          ) {
            sel.value = previousBlockId;
            annState.blockId = sel.value;
          } else if (sel.options.length > 1) {
            sel.selectedIndex = 1;
            annState.blockId = sel.value;
          }
          _onAnnBlockChange();
          return;
        }
      }
    } catch {
      // TextBlock 조회 실패 시 LayoutBlock 폴백
    }
  }

  // 폴백: LayoutBlock 기반 (편성 미완료 시)
  try {
    const partParam = vs.partId
      ? `?part_id=${encodeURIComponent(vs.partId)}`
      : "";
    const resp = await fetch(
      `/api/documents/${vs.docId}/pages/${vs.pageNum}/layout${partParam}`,
    );
    if (!resp.ok) {
      _addAnnDefaultBlock(sel, vs);
      annState.blockId = sel.value;
      _onAnnBlockChange();
      return;
    }
    const layout = await resp.json();
    const blocks = layout.blocks || [];

    if (blocks.length === 0) {
      _addAnnDefaultBlock(sel, vs);
    } else {
      for (const b of blocks) {
        const opt = document.createElement("option");
        opt.value = b.block_id;
        opt.textContent = `${b.block_id} (${b.block_type || "text"})`;
        sel.appendChild(opt);
      }
    }

    if (previousBlockId && sel.querySelector(`option[value="${previousBlockId}"]`)) {
      sel.value = previousBlockId;
    } else if (sel.options.length > 1) {
      sel.selectedIndex = 1;
    }
    if (sel.value) {
      annState.blockId = sel.value;
      _onAnnBlockChange();
    }
  } catch (e) {
    console.error("블록 목록 로드 실패:", e);
    _addAnnDefaultBlock(sel, vs);
    annState.blockId = sel.value;
    _onAnnBlockChange();
  }
}

function _addAnnDefaultBlock(select, vs) {
  const pageNum = (vs && vs.pageNum) || 1;
  const fallbackId = `p${String(pageNum).padStart(2, "0")}_b01`;
  if (select.querySelector(`option[value="${fallbackId}"]`)) return;
  const opt = document.createElement("option");
  opt.value = fallbackId;
  opt.textContent = `${fallbackId} (기본)`;
  select.appendChild(opt);
  select.value = fallbackId;
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
    _loadBlockPunctuation(blockId),
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

  const isTextBlock = blockId.startsWith("tb:");
  const is = typeof interpState !== "undefined" ? interpState : null;

  if (isTextBlock) {
    // ── TextBlock 모드: 최신 교정 텍스트를 우선 사용 ──
    //
    // 왜 이렇게 하는가:
    //   TextBlock의 original_text는 편성(composition) 시점의 스냅샷이다.
    //   편성 이후에 교감/교정을 수정하면 TextBlock에는 반영되지 않는다.
    //   따라서 source_refs를 통해 원본 문서의 최신 교정 텍스트를 가져온다.
    //   교정 텍스트를 못 가져오면 TextBlock 원본을 폴백으로 사용한다.
    if (!is || !is.interpId) {
      annState.originalText = "";
      return;
    }
    const apiBlockId = blockId.slice(3);
    let tbData = null;

    // TextBlock 정보 조회 (source_refs 필요)
    try {
      const tbRes = await fetch(
        `/api/interpretations/${is.interpId}/entities/text_block/${apiBlockId}`,
      );
      if (tbRes.ok) tbData = await tbRes.json();
    } catch {
      /* 폴백 처리 아래 */
    }

    // source_refs에서 원본 문서의 교정 텍스트를 가져온다
    let correctedText = "";
    if (tbData && tbData.source_refs && tbData.source_refs.length > 0) {
      const refPages = [...new Set(tbData.source_refs.map((r) => r.page))];
      const texts = [];
      for (const refPage of refPages) {
        try {
          const ctRes = await fetch(
            `/api/documents/${vs.docId}/pages/${refPage}/corrected-text?part_id=${vs.partId}`,
          );
          if (ctRes.ok) {
            const ctData = await ctRes.json();
            const pageRefs = tbData.source_refs.filter(
              (r) => r.page === refPage,
            );
            for (const ref of pageRefs) {
              if (ref.layout_block_id && ctData.blocks) {
                const match = ctData.blocks.find(
                  (b) => b.block_id === ref.layout_block_id,
                );
                if (match) {
                  texts.push(match.corrected_text || match.original_text || "");
                  continue;
                }
              }
              if (texts.length === 0) {
                texts.push(ctData.corrected_text || "");
              }
            }
          }
        } catch {
          /* skip */
        }
      }
      correctedText = texts.join("\n");
    }

    // 교정 텍스트가 있으면 사용, 없으면 TextBlock 원본 폴백
    if (correctedText.trim()) {
      annState.originalText = correctedText;
    } else {
      const sel = document.getElementById("ann-block-select");
      const selectedOpt = sel
        ? sel.querySelector(`option[value="${blockId}"]`)
        : null;
      annState.originalText =
        selectedOpt && selectedOpt.dataset.text
          ? selectedOpt.dataset.text
          : tbData
            ? tbData.original_text || ""
            : "";
    }
  } else {
    // ── LayoutBlock 모드 (하위 호환) ──
    // 교정 텍스트 API를 사용하여 해당 블록의 교정된 텍스트를 가져온다.
    try {
      const resp = await fetch(
        `/api/documents/${vs.docId}/pages/${vs.pageNum}/corrected-text?part_id=${vs.partId}`,
      );
      if (!resp.ok) return;
      const data = await resp.json();
      const blocks = data.blocks || [];
      const match = blocks.find((b) => b.block_id === blockId);
      if (match) {
        annState.originalText =
          match.corrected_text || match.original_text || "";
      } else {
        annState.originalText = data.corrected_text || "";
      }
    } catch (e) {
      console.error("텍스트 로드 실패:", e);
      annState.originalText = "";
    }
  }
}

async function _loadBlockAnnotations(blockId) {
  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";
  // API에 전달할 block_id: "tb:" 접두사 제거
  const apiBlockId = blockId.startsWith("tb:") ? blockId.slice(3) : blockId;

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${vs.pageNum}/annotations`,
    );
    if (!resp.ok) {
      annState.annotations = [];
      return;
    }
    const data = await resp.json();
    const blocks = data.blocks || [];
    const block = blocks.find((b) => b.block_id === apiBlockId);
    annState.annotations = block ? block.annotations : [];
  } catch (e) {
    console.error("주석 로드 실패:", e);
    annState.annotations = [];
  }
}

async function _loadBlockPunctuation(blockId) {
  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum || !is || !is.interpId) {
    annState.punctMarks = [];
    return;
  }

  const apiBlockId = blockId.startsWith("tb:") ? blockId.slice(3) : blockId;

  try {
    const resp = await fetch(
      `/api/interpretations/${is.interpId}/pages/${vs.pageNum}/punctuation?block_id=${apiBlockId}`,
    );
    if (resp.ok) {
      const data = await resp.json();
      annState.punctMarks = data.marks || [];
    } else {
      annState.punctMarks = [];
    }
  } catch (e) {
    console.error("표점 로드 실패:", e);
    annState.punctMarks = [];
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
  const n = text.length;

  // ── 표점 before/after 버퍼 구성 ──
  // 왜: 원문 글자 사이에 표점 기호(。？！ 등)를 삽입하여
  //     연구자가 문장 구조를 파악할 수 있게 한다.
  const beforeBuf = new Array(n).fill("");
  const afterBuf = new Array(n).fill("");

  for (const mark of annState.punctMarks) {
    const start = mark.target?.start ?? 0;
    const end = mark.target?.end ?? start;
    if (start < 0 || end >= n || start > end) continue;
    if (mark.before) beforeBuf[start] += mark.before;
    if (mark.after) afterBuf[end] += mark.after;
  }

  // ── 글자별 하이라이트 색상 매핑 ──
  const charColors = new Array(n).fill(null);
  const charAnnIds = new Array(n).fill(null);

  for (const ann of annState.annotations) {
    const start = ann.target.start;
    const end = ann.target.end;
    const typeInfo = _getTypeInfo(ann.type);

    for (let i = start; i <= end && i < n; i++) {
      charColors[i] = typeInfo.color;
      charAnnIds[i] = ann.id;
    }
  }

  // ── HTML 생성: 글자별로 표점 + 하이라이트를 함께 렌더링 ──
  container.innerHTML = "";
  let i = 0;
  while (i < n) {
    if (charColors[i]) {
      const color = charColors[i];
      const annId = charAnnIds[i];
      const span = document.createElement("span");
      span.className = "ann-highlight";
      span.style.backgroundColor = color + "30"; // 반투명
      span.style.borderBottom = `2px solid ${color}`;
      span.dataset.annId = annId;
      span.title = _getAnnotationTooltip(annId);

      // 같은 annId가 연속되는 글자를 모아서 표점 포함 텍스트 생성
      let j = i;
      let buf = "";
      while (j < n && charAnnIds[j] === annId) {
        buf += beforeBuf[j] + text[j] + afterBuf[j];
        j++;
      }
      span.textContent = buf;
      span.addEventListener("click", () => _selectAnnotation(annId));
      container.appendChild(span);
      i = j;
    } else {
      // 하이라이트 없는 글자: 연속 null을 모아서 표점 포함 텍스트 생성
      const span = document.createElement("span");
      span.className = "ann-plain-char";
      let j = i;
      let buf = "";
      while (j < n && !charColors[j]) {
        buf += beforeBuf[j] + text[j] + afterBuf[j];
        j++;
      }
      span.textContent = buf;
      // 텍스트 범위 선택으로 수동 주석 추가 지원
      span.addEventListener("mouseup", _onTextSelection);
      container.appendChild(span);
      i = j;
    }
  }
}

function _getAnnotationTooltip(annId) {
  const ann = annState.annotations.find((a) => a.id === annId);
  if (!ann) return "";
  const typeInfo = _getTypeInfo(ann.type);
  return `${typeInfo.icon} ${ann.content.label} [${ann.status}]`;
}

/* ────────────────────────────────────
   텍스트 범위 선택 → 수동 주석 추가
   ──────────────────────────────────── */

/**
 * 표시 오프셋(표점 포함)을 원문 오프셋(표점 제외)으로 변환한다.
 *
 * 왜: 렌더링된 DOM에는 표점 기호(。？！ 등)가 삽입되어 있으므로,
 *   사용자가 텍스트를 드래그하여 선택하면 Range API가 반환하는 위치는
 *   표점을 포함한 "표시 위치"이다.
 *   서버는 순수 원문(original_text)의 오프셋을 사용하므로 변환이 필요하다.
 *
 * @param {number} displayOffset - 표점 포함 표시 위치
 * @param {string} originalText - 순수 원문 텍스트
 * @param {Array} punctMarks - 표점 marks 배열
 * @returns {number} 원문 기준 글자 인덱스
 */
function _annDisplayOffsetToOriginal(displayOffset, originalText, punctMarks) {
  const n = originalText.length;
  if (n === 0) return 0;

  // 표점 before/after 버퍼 구성 (렌더링과 동일한 로직)
  const beforeBuf = new Array(n).fill("");
  const afterBuf = new Array(n).fill("");

  for (const mark of punctMarks) {
    const start = mark.target?.start ?? 0;
    const end = mark.target?.end ?? start;
    if (start < 0 || end >= n || start > end) continue;
    if (mark.before) beforeBuf[start] += mark.before;
    if (mark.after) afterBuf[end] += mark.after;
  }

  // 표시 문자열을 순차 스캔하며 원문 인덱스 매핑
  let displayPos = 0;
  for (let i = 0; i < n; i++) {
    displayPos += beforeBuf[i].length;
    if (displayPos > displayOffset) return i;

    displayPos += 1; // 원문 글자 1자
    if (displayPos > displayOffset) return i;

    displayPos += afterBuf[i].length;
    if (displayPos > displayOffset) return i;
  }

  return n - 1;
}

function _onTextSelection() {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed) return;

  const text = annState.originalText;
  if (!text) return;

  const selectedText = selection.toString();
  if (!selectedText || selectedText.length === 0) return;

  // Range API로 표시 위치를 정확하게 계산한다.
  // 왜 indexOf() 대신 이 방식을 쓰는가:
  //   1) 동일한 글자열이 원문에 여러 번 나타날 때 indexOf()는
  //      항상 첫 번째 위치만 반환한다.
  //   2) selection.toString()에는 표점 기호가 포함되어 있어
  //      순수 원문에서 indexOf()가 실패(-1)할 수 있다.
  const container = document.getElementById("ann-source-text");
  if (!container) return;

  const range = selection.getRangeAt(0);

  // 선택이 원문 컨테이너 내부인지 확인
  if (
    !container.contains(range.startContainer) ||
    !container.contains(range.endContainer)
  )
    return;

  // container 기준 표시 오프셋 계산 (표점 포함)
  const preRange = document.createRange();
  preRange.selectNodeContents(container);
  preRange.setEnd(range.startContainer, range.startOffset);
  const displayStart = preRange.toString().length;

  const fullRange = document.createRange();
  fullRange.selectNodeContents(container);
  fullRange.setEnd(range.endContainer, range.endOffset);
  const displayEnd = fullRange.toString().length - 1;

  if (displayStart > displayEnd || displayEnd < 0) return;

  // 표시 오프셋 → 원문 오프셋 변환 (표점 기호를 제외한 위치)
  const startIdx = _annDisplayOffsetToOriginal(
    displayStart,
    text,
    annState.punctMarks,
  );
  const endIdx = _annDisplayOffsetToOriginal(
    displayEnd,
    text,
    annState.punctMarks,
  );

  if (startIdx < 0 || endIdx < 0 || startIdx > endIdx) return;

  // 실제 원문 텍스트 추출 (prompt에 표시용)
  const actualText = text.slice(startIdx, endIdx + 1);

  const typeId = prompt(
    `"${actualText}"에 주석을 추가합니다.\n유형을 입력하세요 (person/place/term/allusion/official_title/book_title/grammar/note):`,
    "note",
  );
  if (!typeId) return;

  const label = prompt("표제어:", actualText);
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
  const blockId = _annApiBlockId();

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
      },
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

/**
 * 원문의 [start, end] 범위에 표점 부호를 적용한 텍스트 반환.
 * 주석 카드의 인용 텍스트 등에서 사용.
 */
function _punctuateSlice(start, end) {
  const text = annState.originalText;
  if (!text) return "";
  const slice = text.slice(start, end + 1);
  const len = slice.length;
  const beforeBuf = new Array(len).fill("");
  const afterBuf = new Array(len).fill("");

  for (const mark of annState.punctMarks) {
    const mS = mark.target?.start ?? 0;
    const mE = mark.target?.end ?? mS;
    if (mE < start || mS > end) continue;
    const lS = mS - start;
    const lE = mE - start;
    if (lS >= 0 && lS < len && mark.before) beforeBuf[lS] += mark.before;
    if (lE >= 0 && lE < len && mark.after) afterBuf[lE] += mark.after;
  }

  let result = "";
  for (let i = 0; i < len; i++) {
    result += beforeBuf[i] + slice[i] + afterBuf[i];
  }
  return result;
}

function _composePunctuatedTextForAi(originalText, punctMarks) {
  if (!originalText) return "";
  const n = originalText.length;
  if (n === 0) return "";

  const beforeBuf = new Array(n).fill("");
  const afterBuf = new Array(n).fill("");

  for (const mark of punctMarks || []) {
    const start = mark.target?.start ?? 0;
    const end = mark.target?.end ?? start;
    if (start < 0 || end >= n || start > end) continue;
    if (mark.before) beforeBuf[start] += mark.before;
    if (mark.after) afterBuf[end] += mark.after;
  }

  let out = "";
  for (let i = 0; i < n; i++) {
    out += beforeBuf[i] + originalText[i] + afterBuf[i];
  }
  return out;
}

/**
 * 표점 마크 기반 문장 분리 — AI 태깅 병렬 처리용.
 *
 * 표점된 텍스트에서 문장 끝(。！？ 등)을 찾아
 * 원문을 문장 단위로 분할한다.
 * 각 문장에 해당하는 punctMarks를 로컬 인덱스로 변환하여 포함하므로,
 * 기존 _resolveAiAnnotationRangeWithPunctuation 을 문장 단위로 재사용할 수 있다.
 *
 * @param {string} originalText - 원문 (표점 없는 순수 텍스트)
 * @param {Array} punctMarks - 표점 마크 배열
 * @returns {Array<{origStart, origEnd, text, punctMarks, punctuatedText}>}
 */
function _splitIntoSentences(originalText, punctMarks) {
  if (!originalText || originalText.length === 0) return [];
  if (!Array.isArray(punctMarks) || punctMarks.length === 0) {
    // 표점이 없으면 분할 불가 → 전체를 하나의 "문장"으로
    return [
      {
        origStart: 0,
        origEnd: originalText.length - 1,
        text: originalText,
        punctMarks: [],
        punctuatedText: originalText,
      },
    ];
  }

  // 문장 종결 부호 집합
  const sentenceEndChars = new Set(["。", "！", "？", ".", "!", "?"]);

  // punctMarks의 after 필드에서 문장 끝 위치를 수집
  const endPositions = [];
  for (const mark of punctMarks) {
    if (!mark.after) continue;
    for (const ch of mark.after) {
      if (sentenceEndChars.has(ch)) {
        const end = mark.target?.end ?? mark.target?.start ?? 0;
        if (end >= 0 && end < originalText.length) {
          endPositions.push(end);
        }
        break;
      }
    }
  }

  if (endPositions.length === 0) {
    // 문장 종결 부호가 없으면 전체를 하나로
    return [
      {
        origStart: 0,
        origEnd: originalText.length - 1,
        text: originalText,
        punctMarks: punctMarks,
        punctuatedText: _composePunctuatedTextForAi(originalText, punctMarks),
      },
    ];
  }

  endPositions.sort((a, b) => a - b);
  // 같은 위치에 여러 종결 부호가 있으면 중복 제거
  const uniqueEnds = [...new Set(endPositions)];

  const sentences = [];
  let start = 0;

  for (const endPos of uniqueEnds) {
    if (endPos < start) continue;
    const sentText = originalText.slice(start, endPos + 1);
    if (sentText.length === 0) continue;

    // 이 문장 범위에 해당하는 punctMarks → 로컬 인덱스로 변환
    const localMarks = [];
    for (const mark of punctMarks) {
      const mStart = mark.target?.start ?? 0;
      const mEnd = mark.target?.end ?? mStart;
      if (mStart >= start && mEnd <= endPos) {
        localMarks.push({
          ...mark,
          target: { start: mStart - start, end: mEnd - start },
        });
      }
    }

    sentences.push({
      origStart: start,
      origEnd: endPos,
      text: sentText,
      punctMarks: localMarks,
      punctuatedText: _composePunctuatedTextForAi(sentText, localMarks),
    });
    start = endPos + 1;
  }

  // 마지막 문장 끝 이후 남은 텍스트 (종결 부호 없이 끝나는 경우)
  if (start < originalText.length) {
    const sentText = originalText.slice(start);
    const lastEnd = originalText.length - 1;
    const localMarks = [];
    for (const mark of punctMarks) {
      const mStart = mark.target?.start ?? 0;
      const mEnd = mark.target?.end ?? mStart;
      if (mStart >= start && mEnd <= lastEnd) {
        localMarks.push({
          ...mark,
          target: { start: mStart - start, end: mEnd - start },
        });
      }
    }
    sentences.push({
      origStart: start,
      origEnd: originalText.length - 1,
      text: sentText,
      punctMarks: localMarks,
      punctuatedText: _composePunctuatedTextForAi(sentText, localMarks),
    });
  }

  return sentences;
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
    anns = anns.filter((a) => a.type === filterType);
  }

  if (anns.length === 0) {
    container.innerHTML =
      '<div class="placeholder">주석이 없습니다. 텍스트를 선택하거나 AI 태깅을 실행하세요.</div>';
    return;
  }

  // start 순으로 정렬
  anns.sort((a, b) => a.target.start - b.target.start);

  container.innerHTML = "";
  for (const ann of anns) {
    const typeInfo = _getTypeInfo(ann.type);
    const card = document.createElement("div");
    card.className = "ann-card";
    if (ann.id === annState.selectedAnnId)
      card.classList.add("ann-card-selected");

    const sourceText = _punctuateSlice(ann.target.start, ann.target.end);

    const statusClass =
      ann.status === "accepted"
        ? "ann-status-accepted"
        : ann.status === "draft"
          ? "ann-status-draft"
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
  const accepted = annState.annotations.filter(
    (a) => a.status === "accepted",
  ).length;
  const draft = annState.annotations.filter((a) => a.status === "draft").length;

  el.textContent = `전체 ${total} / 확정 ${accepted} / 초안 ${draft}`;
}

/* ────────────────────────────────────
   주석 선택 → 편집 패널
   ──────────────────────────────────── */

function _selectAnnotation(annId) {
  annState.selectedAnnId = annId;
  const ann = annState.annotations.find((a) => a.id === annId);
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
  const blockId = _annApiBlockId();
  const annId = annState.selectedAnnId;

  const typeSelect = document.getElementById("ann-edit-type");
  const labelInput = document.getElementById("ann-edit-label");
  const descInput = document.getElementById("ann-edit-desc");
  const refsInput = document.getElementById("ann-edit-refs");

  const refs =
    refsInput && refsInput.value
      ? refsInput.value
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
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
      },
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
  const blockId = _annApiBlockId();
  const annId = annState.selectedAnnId;

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${vs.pageNum}/annotations/${blockId}/${annId}/commit`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
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
  const blockId = _annApiBlockId();
  const annId = annState.selectedAnnId;

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${vs.pageNum}/annotations/${blockId}/${annId}`,
      { method: "DELETE" },
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
   * 흐름 (문장 병렬 처리):
   *   1. 표점 기준으로 문장 분리 (2문장 이상 & 60자 이상이면 병렬)
   *   2. 문장별로 LLM 병렬 호출 (동시 3개씩)
   *   3. 문장 로컬 인덱스 → 원문 글로벌 인덱스 변환
   *   4. 완료된 문장부터 UI에 진행률 표시
   *   5. 전체 결과를 batch POST로 저장
   *
   * 짧은 텍스트(60자 미만 또는 1문장)는 기존 단일 호출 방식 사용.
   */
  const text = annState.originalText;
  if (!text) {
    showToast("태깅할 텍스트가 없습니다. 먼저 블록을 선택하세요.", "warning");
    return;
  }

  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";
  const blockId = _annApiBlockId();
  if (!blockId) {
    showToast("블록을 먼저 선택하세요.", "warning");
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
    const llmSel =
      typeof getLlmModelSelection === "function"
        ? getLlmModelSelection("ann-llm-model-select")
        : { force_provider: null, force_model: null };

    if (typeof showEditorProgress === "function") {
      showEditorProgress("ann", true, "AI 태깅 처리 중...");
    }

    // 문장 분리: 표점 기준으로 문장 경계를 찾는다
    const sentences = _splitIntoSentences(text, annState.punctMarks);
    const useSentenceMode = sentences.length >= 2 && text.length >= 60;

    // ── 태깅 결과를 모을 배열 (인덱스 보정 완료 상태) ──
    const allResolved = [];
    let providerInfo = "LLM";

    if (useSentenceMode) {
      /* ── 문장 단위 병렬 처리 ──
       * 왜 이렇게 하는가:
       *   텍스트가 길면 LLM 응답 시간이 급격히 느려진다.
       *   문장 단위로 쪼개면 개별 호출이 빠르고,
       *   동시 3개씩 병렬 처리하여 총 시간을 단축한다.
       *   완료된 문장부터 진행률을 표시하여 체감 속도도 개선.
       */
      const CONCURRENCY = 3;
      let completed = 0;
      const total = sentences.length;
      // 잘린 응답을 문장별로 집계 — 개별 토스트 남발 대신 끝에 1회 경고.
      let truncatedSentences = 0;
      let truncatedRecovered = 0;

      for (let i = 0; i < sentences.length; i += CONCURRENCY) {
        const batch = sentences.slice(i, i + CONCURRENCY);
        const promises = batch.map(async (sent) => {
          const reqBody = { text: sent.punctuatedText };
          if (llmSel.force_provider)
            reqBody.force_provider = llmSel.force_provider;
          if (llmSel.force_model) reqBody.force_model = llmSel.force_model;

          const data = await fetchWithSSE(
            "/api/llm/annotation/stream",
            reqBody,
            () => {},
            "/api/llm/annotation",
          );
          return {
            sentence: sent,
            annotations: data.annotations || [],
            provider: data._provider || "",
            truncated: data._truncated === true,
            recovered:
              typeof data._recovered_count === "number"
                ? data._recovered_count
                : 0,
          };
        });

        const results = await Promise.allSettled(promises);
        for (const result of results) {
          if (result.status !== "fulfilled") {
            console.warn("문장 태깅 실패:", result.reason);
            continue;
          }
          const { sentence, annotations, provider, truncated, recovered } =
            result.value;
          if (provider) providerInfo = provider;
          if (truncated) {
            truncatedSentences += 1;
            truncatedRecovered += recovered;
          }

          for (const ann of annotations) {
            // 문장 로컬 인덱스 → 원문 글로벌 인덱스 변환
            const resolved = _resolveAiAnnotationRangeWithPunctuation(
              ann,
              sentence.text,
              sentence.punctMarks,
            );
            if (!resolved) continue;

            const globalStart = resolved.start + sentence.origStart;
            const globalEnd = resolved.end + sentence.origStart;
            if (globalStart < 0 || globalEnd >= text.length) continue;

            allResolved.push({
              start: globalStart,
              end: globalEnd,
              type: ann.type,
              label: ann.label,
              text: ann.text,
              description: ann.description,
            });
          }
        }

        completed += batch.length;
        if (aiBtn)
          aiBtn.textContent = `AI 태깅 중… (${completed}/${total}문장)`;
        if (typeof showEditorProgress === "function") {
          showEditorProgress(
            "ann",
            true,
            `AI 태깅: ${completed}/${total}문장 완료`,
          );
        }
      }
      // 문장 단위 병렬 호출 중 하나라도 잘렸으면 1회 경고 (누락 가능성 알림)
      if (truncatedSentences > 0 && typeof showToast === "function") {
        showToast(
          `LLM 주석 응답이 ${truncatedSentences}개 문장에서 잘려 ` +
            `완성된 ${truncatedRecovered}개 항목만 복구했습니다 — ` +
            `누락 가능성이 있으니 해당 문장을 재실행하세요.`,
          "warning",
          9000,
        );
      }
    } else {
      /* ── 기존 단일 호출 방식 (짧은 텍스트 / 1문장) ── */
      const aiInputText = _composePunctuatedTextForAi(
        text,
        annState.punctMarks,
      );
      const reqBody = { text: aiInputText || text };
      if (llmSel.force_provider)
        reqBody.force_provider = llmSel.force_provider;
      if (llmSel.force_model) reqBody.force_model = llmSel.force_model;

      const data = await fetchWithSSE(
        "/api/llm/annotation/stream",
        reqBody,
        (progress) => {
          const sec = progress.elapsed_sec || 0;
          if (aiBtn) aiBtn.textContent = `AI 태깅 중… (${sec}초)`;
          if (typeof showEditorProgress === "function") {
            showEditorProgress(
              "ann",
              true,
              `AI 태깅 처리 중... ${sec}초 경과`,
            );
          }
        },
        "/api/llm/annotation",
      );
      providerInfo = data._provider || "LLM";

      // 잘린 응답 복구 시 경고 (누락 가능성 알림)
      if (typeof notifyLlmTruncation === "function") {
        notifyLlmTruncation(data, "주석");
      }

      for (const ann of data.annotations || []) {
        const resolved = _resolveAiAnnotationRangeWithPunctuation(
          ann,
          text,
          annState.punctMarks,
        );
        if (!resolved) continue;
        if (resolved.start < 0 || resolved.end >= text.length) continue;
        allResolved.push({
          start: resolved.start,
          end: resolved.end,
          type: ann.type,
          label: ann.label,
          text: ann.text,
          description: ann.description,
        });
      }
    }

    if (allResolved.length === 0) {
      _showSaveStatus("AI가 태깅할 항목을 찾지 못했습니다.");
      return;
    }

    // ── 중복 제거: 동일 범위(start,end)의 주석은 첫 번째만 유지 ──
    // 문장 경계에서 같은 대상이 중복 태깅될 수 있으므로 필터링.
    const seenRanges = new Set();
    const deduped = allResolved.filter((r) => {
      const key = `${r.start}:${r.end}`;
      if (seenRanges.has(key)) return false;
      seenRanges.add(key);
      return true;
    });

    // ── 인덱스 보정 완료된 결과 → batch payload 구성 ──
    const batchPayload = [];
    for (const r of deduped) {
      if (r.start < 0 || r.end < r.start || r.end >= text.length) continue;

      const labelText =
        _normalizeAiTagText(r.label || r.text || "") ||
        text.slice(r.start, r.end + 1);

      batchPayload.push({
        target: { start: r.start, end: r.end },
        type: r.type || "term",
        content: {
          label: labelText,
          description: r.description || "",
          references: [],
        },
        status: "draft",
      });
    }

    // batch 엔드포인트로 1회 POST 시도. 실패 시 기존 순차 방식 폴백.
    let savedCount = 0;
    try {
      const batchResp = await fetch(
        `/api/interpretations/${interpId}/pages/${vs.pageNum}/annotations/${blockId}/batch`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ annotations: batchPayload }),
        },
      );
      if (batchResp.ok) {
        const batchResult = await batchResp.json();
        savedCount = batchResult.saved || 0;
      } else {
        throw new Error("batch 엔드포인트 실패");
      }
    } catch (batchErr) {
      // 폴백: 개별 순차 POST
      console.warn("batch 저장 실패, 순차 폴백:", batchErr.message);
      for (const payload of batchPayload) {
        try {
          const saveResp = await fetch(
            `/api/interpretations/${interpId}/pages/${vs.pageNum}/annotations/${blockId}`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            },
          );
          if (saveResp.ok) savedCount++;
        } catch (e) {
          console.warn("주석 저장 실패:", e);
        }
      }
    }

    // ── UI 갱신 ──
    await _loadBlockAnnotations(blockId);
    _renderSourceText();
    _renderAnnList();
    _renderStatusSummary();
    const modeLabel = useSentenceMode
      ? `${sentences.length}문장 병렬`
      : providerInfo;
    _showSaveStatus(`AI 태깅 완료: ${savedCount}개 주석 (${modeLabel})`);
  } catch (e) {
    console.error("AI 태깅 실패:", e);
    showToast("AI 태깅 실패: " + e.message, "error");
  } finally {
    // 진행 바 숨김 + 버튼 복원
    if (typeof showEditorProgress === "function") {
      showEditorProgress("ann", false);
    }
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
      { method: "POST" },
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
   유형 관리 다이얼로그 (모달)

   왜 이렇게 하는가:
     기존 prompt() 4연타 방식은 기존 유형 확인·삭제가 불가능하고,
     색상을 hex로 직접 입력해야 해서 연구자에게 불편하다.
     bib-dialog 패턴의 모달로 교체하여
     목록 조회 + 추가 + 삭제를 한 화면에서 처리한다.
   ──────────────────────────────────── */

/**
 * 유형 관리 모달을 연다.
 *
 * 목적: 기본 프리셋 + 사용자 정의 유형 목록을 보여주고,
 *       새 유형 추가 / 기존 커스텀 유형 삭제를 가능하게 한다.
 */
async function _showTypeMgmtDialog() {
  const overlay = document.getElementById("atm-dialog-overlay");
  if (!overlay) return;

  overlay.style.display = "";
  await _renderTypeList();

  // 이벤트 바인딩 (중복 방지를 위해 매번 재바인딩)
  const closeBtn = document.getElementById("atm-dialog-close");
  const doneBtn = document.getElementById("atm-dialog-done");
  if (closeBtn) closeBtn.onclick = _closeTypeMgmtDialog;
  if (doneBtn) doneBtn.onclick = _closeTypeMgmtDialog;

  // 오버레이 클릭으로 닫기
  overlay.onclick = (e) => {
    if (e.target === overlay) _closeTypeMgmtDialog();
  };
}

/**
 * 유형 관리 모달을 닫고, 유형 필터·편집 셀렉트를 갱신한다.
 */
function _closeTypeMgmtDialog() {
  const overlay = document.getElementById("atm-dialog-overlay");
  if (overlay) overlay.style.display = "none";
  // 모달에서 추가/삭제했을 수 있으므로 셀렉트 박스 갱신
  _populateTypeFilter();
  _populateEditTypeSelect();
}

/**
 * 모달 본문에 유형 목록 + 추가 폼을 렌더링한다.
 *
 * 출력 구조:
 *   ── 기본 프리셋 ── (읽기 전용 카드)
 *   ── 사용자 정의 ── (삭제 버튼 포함 카드)
 *   ── 새 유형 추가 ── (입력 폼)
 */
async function _renderTypeList() {
  const body = document.getElementById("atm-dialog-body");
  if (!body) return;

  // API에서 최신 유형 목록 가져오기
  let data;
  try {
    const resp = await fetch("/api/annotation-types");
    if (!resp.ok) throw new Error("API 오류");
    data = await resp.json();
  } catch (e) {
    body.innerHTML = '<p style="color:var(--error-color)">유형 목록을 불러올 수 없습니다.</p>';
    return;
  }

  const presets = data.types || [];
  const custom = data.custom || [];
  const hidden = data.hidden || [];
  // 보호 유형: 삭제 불가 (인물, 지명, 서명)
  const protectedIds = new Set(["person", "place", "book_title"]);

  let html = "";

  // ── 기본 프리셋 ──
  html += '<div class="atm-section-title">기본 프리셋</div>';
  for (const t of presets) {
    const isProtected = protectedIds.has(t.id);
    html += `
      <div class="atm-type-card">
        <span class="atm-type-color" style="background:${_escAttr(t.color)}"></span>
        <span class="atm-type-icon">${_escHtml(t.icon || "註")}</span>
        <span class="atm-type-label">${_escHtml(t.label)}</span>
        <span class="atm-type-id">${_escHtml(t.id)}</span>
        ${isProtected ? "" : `<button class="text-btn atm-delete-btn" data-type-id="${_escAttr(t.id)}" title="삭제">삭제</button>`}
      </div>`;
  }

  // ── 숨긴 프리셋 복원 ──
  if (hidden.length > 0) {
    html += '<div class="atm-section-title" style="margin-top:12px">숨긴 프리셋</div>';
    for (const id of hidden) {
      html += `
        <div class="atm-type-card" style="opacity:0.6">
          <span class="atm-type-label">${_escHtml(id)}</span>
          <button class="text-btn atm-restore-btn" data-type-id="${_escAttr(id)}" title="복원">복원</button>
        </div>`;
    }
  }

  // ── 사용자 정의 ──
  html += '<div class="atm-section-title" style="margin-top:12px">사용자 정의</div>';
  if (custom.length === 0) {
    html += '<div class="atm-empty">아직 추가된 유형이 없습니다.</div>';
  } else {
    for (const t of custom) {
      html += `
        <div class="atm-type-card">
          <span class="atm-type-color" style="background:${_escAttr(t.color)}"></span>
          <span class="atm-type-icon">${_escHtml(t.icon || "註")}</span>
          <span class="atm-type-label">${_escHtml(t.label)}</span>
          <span class="atm-type-id">${_escHtml(t.id)}</span>
          <button class="text-btn atm-delete-btn" data-type-id="${_escAttr(t.id)}" title="삭제">삭제</button>
        </div>`;
    }
  }

  // ── 새 유형 추가 폼 ──
  html += `
    <div class="atm-section-title" style="margin-top:12px">새 유형 추가</div>
    <div class="atm-add-form">
      <div class="atm-form-row">
        <label class="atm-form-label">ID (영문)</label>
        <input id="atm-new-id" type="text" class="bib-input" placeholder="예: sutra_ref" />
      </div>
      <div class="atm-form-row">
        <label class="atm-form-label">이름</label>
        <input id="atm-new-label" type="text" class="bib-input" placeholder="예: 경전 참조" />
      </div>
      <div class="atm-form-row">
        <label class="atm-form-label">아이콘</label>
        <input id="atm-new-icon" type="text" class="bib-input" placeholder="註" value="註" style="width:60px" />
      </div>
      <div class="atm-form-row">
        <label class="atm-form-label">색상</label>
        <input id="atm-new-color" type="color" class="atm-color-input" value="#888888" />
      </div>
      <div class="atm-form-actions">
        <button id="atm-add-btn" class="bib-btn bib-btn-primary">추가</button>
      </div>
    </div>`;

  body.innerHTML = html;

  // 추가 버튼 바인딩
  const addBtn = document.getElementById("atm-add-btn");
  if (addBtn) addBtn.addEventListener("click", _addCustomType);

  // 삭제 버튼 바인딩 (프리셋 + 커스텀 공용)
  for (const btn of body.querySelectorAll(".atm-delete-btn")) {
    btn.addEventListener("click", () => _deleteCustomType(btn.dataset.typeId));
  }

  // 복원 버튼 바인딩
  for (const btn of body.querySelectorAll(".atm-restore-btn")) {
    btn.addEventListener("click", () => _restorePresetType(btn.dataset.typeId));
  }
}

/**
 * 폼 입력값을 읽어 사용자 정의 유형을 추가한다.
 *
 * 입력 검증 → POST /api/annotation-types → 목록 갱신.
 */
async function _addCustomType() {
  const id = (document.getElementById("atm-new-id")?.value || "").trim();
  const label = (document.getElementById("atm-new-label")?.value || "").trim();
  const icon = (document.getElementById("atm-new-icon")?.value || "").trim() || "註";
  const color = document.getElementById("atm-new-color")?.value || "#888888";
  const status = document.getElementById("atm-dialog-status");

  if (!id) { showToast("ID를 입력하세요.", "warning"); return; }
  if (!label) { showToast("이름을 입력하세요.", "warning"); return; }
  // ID는 영문+숫자+밑줄만 허용
  if (!/^[a-zA-Z][a-zA-Z0-9_]*$/.test(id)) {
    showToast("ID는 영문으로 시작하고, 영문·숫자·밑줄만 사용할 수 있습니다.", "warning");
    return;
  }

  try {
    const resp = await fetch("/api/annotation-types", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, label, color, icon }),
    });

    if (resp.ok) {
      if (status) status.textContent = "추가 완료";
      await _loadAnnotationTypes();
      await _renderTypeList();
    } else {
      const err = await resp.json();
      showToast("유형 추가 실패: " + (err.error || "알 수 없는 오류"), "error");
    }
  } catch (e) {
    console.error("유형 추가 실패:", e);
    showToast("유형 추가 중 오류가 발생했습니다.", "error");
  }
}

/**
 * 사용자 정의 유형을 삭제한다.
 *
 * 입력: typeId — 삭제할 유형 ID.
 * confirm() 후 DELETE /api/annotation-types/{typeId} → 목록 갱신.
 */
async function _deleteCustomType(typeId) {
  if (!confirm(`유형 '${typeId}'를 삭제하시겠습니까?`)) return;
  const status = document.getElementById("atm-dialog-status");

  try {
    const resp = await fetch(`/api/annotation-types/${encodeURIComponent(typeId)}`, {
      method: "DELETE",
    });

    if (resp.ok || resp.status === 204) {
      if (status) status.textContent = "삭제 완료";
      await _loadAnnotationTypes();
      await _renderTypeList();
    } else {
      const err = await resp.json().catch(() => ({}));
      showToast("유형 삭제 실패: " + (err.error || "알 수 없는 오류"), "error");
    }
  } catch (e) {
    console.error("유형 삭제 실패:", e);
    showToast("유형 삭제 중 오류가 발생했습니다.", "error");
  }
}

/**
 * 숨긴 프리셋 유형을 복원한다.
 *
 * 입력: typeId — 복원할 유형 ID.
 * POST /api/annotation-types/{typeId}/restore → 목록 갱신.
 */
async function _restorePresetType(typeId) {
  const status = document.getElementById("atm-dialog-status");
  try {
    const resp = await fetch(
      `/api/annotation-types/${encodeURIComponent(typeId)}/restore`,
      { method: "POST" },
    );
    if (resp.ok) {
      if (status) status.textContent = "복원 완료";
      await _loadAnnotationTypes();
      await _renderTypeList();
    } else {
      const err = await resp.json().catch(() => ({}));
      showToast("복원 실패: " + (err.error || "알 수 없는 오류"), "error");
    }
  } catch (e) {
    console.error("유형 복원 실패:", e);
    showToast("유형 복원 중 오류가 발생했습니다.", "error");
  }
}

/** HTML 이스케이프 (속성용) */
function _escAttr(s) {
  return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** HTML 이스케이프 (텍스트 콘텐츠용) */
function _escHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* ────────────────────────────────────
   전체 리셋: 현재 페이지의 모든 주석 삭제
   ──────────────────────────────────── */

/**
 * 현재 블록의 모든 주석을 삭제한다.
 *
 * 왜 이렇게 하는가: AI 태깅이나 수동 주석 작업을 처음부터 다시 하고 싶을 때,
 *   개별 삭제를 반복하는 대신 한 번에 모두 삭제할 수 있다.
 *   삭제 전 confirm()으로 사용자 확인을 받아 실수를 방지한다.
 */
async function _resetAllAnnotations() {
  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) {
    showToast("페이지가 선택되어야 합니다.", "warning");
    return;
  }

  const interpId = (is && is.interpId) || "default";
  const blockId = _annApiBlockId();

  if (!blockId) {
    showToast("블록을 먼저 선택하세요.", "warning");
    return;
  }

  if (annState.annotations.length === 0) {
    showToast("삭제할 주석이 없습니다.", "warning");
    return;
  }

  if (
    !confirm(
      `현재 블록(${blockId})의 주석 ${annState.annotations.length}건을 모두 삭제합니다.\n이 작업은 되돌릴 수 없습니다. 계속하시겠습니까?`,
    )
  )
    return;

  let success = 0;
  let fail = 0;

  // 주석 ID 목록을 미리 복사 (삭제 중 배열 변경 방지)
  const ids = annState.annotations.map((a) => a.id);

  for (const annId of ids) {
    try {
      const resp = await fetch(
        `/api/interpretations/${interpId}/pages/${vs.pageNum}/annotations/${blockId}/${annId}`,
        { method: "DELETE" },
      );
      if (resp.ok || resp.status === 204) {
        success++;
      } else {
        fail++;
      }
    } catch {
      fail++;
    }
  }

  // 로컬 상태 초기화 및 UI 갱신
  annState.selectedAnnId = null;
  _closeEditPanel();
  await _loadBlockAnnotations(blockId);
  _renderSourceText();
  _renderAnnList();
  _renderStatusSummary();

  if (fail > 0) {
    showToast(`주석 리셋 완료: 성공 ${success}건, 실패 ${fail}건`, "error");
  } else {
    _showSaveStatus(`주석 ${success}건 삭제 완료`);
  }
}

/* ────────────────────────────────────
   유틸리티
   ──────────────────────────────────── */

function _showSaveStatus(msg) {
  const el = document.getElementById("ann-save-status");
  if (!el) return;
  el.textContent = msg;
  setTimeout(() => {
    el.textContent = "";
  }, 2000);
}

function _normalizeAiTagText(rawText) {
  if (!rawText || typeof rawText !== "string") return "";
  let text = rawText.trim();
  if (!text) return "";

  const leading = /^[\s"'“”‘’「『《〈【〔（\(\[]+/u;
  const trailing = /[\s"'“”‘’」』》〉】〕）\)\]]+$/u;

  while (leading.test(text)) {
    text = text.replace(leading, "").trim();
  }
  while (trailing.test(text)) {
    text = text.replace(trailing, "").trim();
  }

  return text;
}

const _AI_RANGE_IGNORABLE_CHAR_RE =
  /[\s,.;:!?'"`~\-_=+\/\\|()[\]{}<>«»“”‘’‹›《》〈〉「」『』【】〔〕［］｛｝（）﹙﹚﹛﹜、。；：？！…·・，．]/u;

function _toAiIndex(value, fallback) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.trunc(n);
}

function _buildAiRangeIndexMap(text) {
  const strippedChars = [];
  const strippedToOriginal = [];
  const originalToStripped = new Array(text.length).fill(-1);

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (_AI_RANGE_IGNORABLE_CHAR_RE.test(ch)) continue;
    originalToStripped[i] = strippedChars.length;
    strippedToOriginal.push(i);
    strippedChars.push(ch);
  }

  return {
    strippedText: strippedChars.join(""),
    strippedToOriginal,
    originalToStripped,
  };
}

function _findNearestOccurrence(haystack, needle, hintIndex) {
  if (!haystack || !needle) return -1;
  let pos = haystack.indexOf(needle);
  if (pos === -1) return -1;

  let bestPos = pos;
  let bestDist = Math.abs(pos - hintIndex);

  while (pos !== -1) {
    const dist = Math.abs(pos - hintIndex);
    if (dist < bestDist) {
      bestPos = pos;
      bestDist = dist;
      if (bestDist === 0) break;
    }
    pos = haystack.indexOf(needle, pos + 1);
  }

  return bestPos;
}

function _resolveAiAnnotationRange(ann, originalText) {
  const n = originalText.length;
  if (n === 0) return null;

  const target = ann && typeof ann === "object" ? ann.target || {} : {};
  let start = _toAiIndex(ann?.start, _toAiIndex(target.start, 0));
  let end = _toAiIndex(ann?.end, _toAiIndex(target.end, start));
  if (end < start) {
    const tmp = start;
    start = end;
    end = tmp;
  }

  start = Math.max(0, Math.min(start, n - 1));
  end = Math.max(start, Math.min(end, n - 1));

  const normalizedText = _normalizeAiTagText(ann?.text || "");
  if (!normalizedText) {
    return { start, end };
  }

  const currentSlice = originalText.slice(start, end + 1);
  const localIndex = currentSlice.indexOf(normalizedText);
  if (localIndex !== -1) {
    const fixedStart = start + localIndex;
    return {
      start: fixedStart,
      end: Math.min(n - 1, fixedStart + normalizedText.length - 1),
    };
  }

  const foundStart = _findNearestOccurrence(originalText, normalizedText, start);
  if (foundStart !== -1) {
    return {
      start: foundStart,
      end: Math.min(n - 1, foundStart + normalizedText.length - 1),
    };
  }

  // AI가 표점을 포함한 텍스트를 반환해도 원문 인덱스로 되돌릴 수 있게 보정한다.
  const sourceMap = _buildAiRangeIndexMap(originalText);
  const queryMap = _buildAiRangeIndexMap(normalizedText);
  const strippedNeedle = queryMap.strippedText;
  if (strippedNeedle) {
    const strippedHint = sourceMap.originalToStripped[start];
    const hintIndex = strippedHint >= 0 ? strippedHint : 0;
    const strippedMatchStart = _findNearestOccurrence(
      sourceMap.strippedText,
      strippedNeedle,
      hintIndex,
    );
    if (strippedMatchStart !== -1) {
      const mappedStart = sourceMap.strippedToOriginal[strippedMatchStart];
      const mappedEnd =
        sourceMap.strippedToOriginal[
          strippedMatchStart + strippedNeedle.length - 1
        ];
      if (Number.isInteger(mappedStart) && Number.isInteger(mappedEnd)) {
        return { start: mappedStart, end: mappedEnd };
      }
    }
  }

  if (start <= end) {
    return {
      start,
      end,
    };
  }

  return null;
}

function _stripAiIgnorableChars(text) {
  if (!text) return "";
  let out = "";
  for (const ch of text) {
    if (_AI_RANGE_IGNORABLE_CHAR_RE.test(ch)) continue;
    out += ch;
  }
  return out;
}

function _clampAiRange(range, n) {
  if (!range || n <= 0) return null;
  let start = Math.max(0, Math.min(range.start, n - 1));
  let end = Math.max(0, Math.min(range.end, n - 1));
  if (end < start) {
    const tmp = start;
    start = end;
    end = tmp;
  }
  return { start, end };
}

function _scoreAiRangeCandidate(range, queryText, originalText) {
  if (!range || !queryText || !originalText) return 0;
  const slice = originalText.slice(range.start, range.end + 1);
  const left = _stripAiIgnorableChars(slice);
  const right = _stripAiIgnorableChars(queryText);
  if (!left || !right) return 0;
  if (left === right) return 3;
  if (left.includes(right) || right.includes(left)) return 2;
  if (left[0] === right[0]) return 1;
  return 0;
}

function _extractLabelHanjaForAi(label) {
  const normalizedLabel = _normalizeAiTagText(label || "");
  if (!normalizedLabel) return "";

  const parenMatches = normalizedLabel.matchAll(/[\(\uff08]([^\)\uff09]+)[\)\uff09]/gu);
  for (const m of parenMatches) {
    const inner = _normalizeAiTagText(m[1] || "");
    if (!inner) continue;
    if (/[\u3400-\u9fff\uf900-\ufaff]/u.test(inner)) {
      return inner;
    }
  }
  return "";
}

function _resolveAiRangeByQuery(queryText, candidateRanges, originalText) {
  const n = originalText.length;
  const normalizedText = _normalizeAiTagText(queryText || "");
  if (!normalizedText) return null;

  for (const range of candidateRanges) {
    const currentSlice = originalText.slice(range.start, range.end + 1);
    const localIndex = currentSlice.indexOf(normalizedText);
    if (localIndex !== -1) {
      const fixedStart = range.start + localIndex;
      return {
        start: fixedStart,
        end: Math.min(n - 1, fixedStart + normalizedText.length - 1),
      };
    }
  }

  let bestDirect = null;
  for (const range of candidateRanges) {
    const foundStart = _findNearestOccurrence(
      originalText,
      normalizedText,
      range.start,
    );
    if (foundStart === -1) continue;
    const dist = Math.abs(foundStart - range.start);
    if (!bestDirect || dist < bestDirect.dist) {
      bestDirect = { start: foundStart, dist };
    }
  }
  if (bestDirect) {
    return {
      start: bestDirect.start,
      end: Math.min(n - 1, bestDirect.start + normalizedText.length - 1),
    };
  }

  const sourceMap = _buildAiRangeIndexMap(originalText);
  const queryMap = _buildAiRangeIndexMap(normalizedText);
  const strippedNeedle = queryMap.strippedText;
  if (strippedNeedle) {
    let bestStripped = null;
    for (const range of candidateRanges) {
      const strippedHintRaw = sourceMap.originalToStripped[range.start];
      const hintIndex = strippedHintRaw >= 0 ? strippedHintRaw : 0;
      const strippedMatchStart = _findNearestOccurrence(
        sourceMap.strippedText,
        strippedNeedle,
        hintIndex,
      );
      if (strippedMatchStart === -1) continue;
      const dist = Math.abs(strippedMatchStart - hintIndex);
      if (!bestStripped || dist < bestStripped.dist) {
        bestStripped = { start: strippedMatchStart, dist };
      }
    }

    if (bestStripped) {
      const mappedStart = sourceMap.strippedToOriginal[bestStripped.start];
      const mappedEnd =
        sourceMap.strippedToOriginal[
          bestStripped.start + strippedNeedle.length - 1
        ];
      if (Number.isInteger(mappedStart) && Number.isInteger(mappedEnd)) {
        return { start: mappedStart, end: mappedEnd };
      }
    }
  }

  return null;
}

function _resolveAiAnnotationRangeWithPunctuation(
  ann,
  originalText,
  punctMarks = [],
) {
  const n = originalText.length;
  if (n === 0) return null;

  const target = ann && typeof ann === "object" ? ann.target || {} : {};
  let start = _toAiIndex(ann?.start, _toAiIndex(target.start, 0));
  let end = _toAiIndex(ann?.end, _toAiIndex(target.end, start));
  if (end < start) {
    const tmp = start;
    start = end;
    end = tmp;
  }

  const rawRange = _clampAiRange({ start, end }, n);
  if (!rawRange) return null;
  const candidateRanges = [rawRange];

  if (Array.isArray(punctMarks) && punctMarks.length > 0) {
    const displayStart = _annDisplayOffsetToOriginal(
      start,
      originalText,
      punctMarks,
    );
    const displayEnd = _annDisplayOffsetToOriginal(end, originalText, punctMarks);
    const converted = _clampAiRange(
      {
        start: Math.min(displayStart, displayEnd),
        end: Math.max(displayStart, displayEnd),
      },
      n,
    );
    if (
      converted &&
      (converted.start !== rawRange.start || converted.end !== rawRange.end)
    ) {
      candidateRanges.push(converted);
    }
  }

  const labelHanja = _extractLabelHanjaForAi(ann?.label || "");
  if (labelHanja) {
    const byLabelHanja = _resolveAiRangeByQuery(
      labelHanja,
      candidateRanges,
      originalText,
    );
    if (byLabelHanja) return byLabelHanja;
    // 라벨 괄호 내 한자가 있으면 그 값으로 맞지 않는 항목은 버린다.
    return null;
  }

  const normalizedText = _normalizeAiTagText(ann?.text || "");
  if (!normalizedText) {
    return rawRange;
  }

  const resolvedByText = _resolveAiRangeByQuery(
    normalizedText,
    candidateRanges,
    originalText,
  );
  if (resolvedByText) return resolvedByText;

  let bestRange = rawRange;
  let bestScore = _scoreAiRangeCandidate(bestRange, normalizedText, originalText);
  for (let i = 1; i < candidateRanges.length; i++) {
    const score = _scoreAiRangeCandidate(
      candidateRanges[i],
      normalizedText,
      originalText,
    );
    if (score > bestScore) {
      bestRange = candidateRanges[i];
      bestScore = score;
    }
  }
  return bestRange;
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
    from_original: "1단계",
    from_translation: "2단계",
    from_both: "3단계",
    reviewed: "검토완료",
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
    const refs = d.source_references
      .map((r) => r.title + (r.section ? ` ${r.section}` : ""))
      .join(", ");
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
  const blockId = _annApiBlockId();
  if (!blockId) {
    showToast("블록을 먼저 선택하세요.", "warning");
    return;
  }

  const btn = document.getElementById(`ann-dict-stage${stageNum}-btn`);
  if (btn) {
    btn.disabled = true;
    btn.textContent = `${stageNum}단계 생성 중…`;
  }

  try {
    const llmSel =
      typeof getLlmModelSelection === "function"
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
      },
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
    showToast(`${stageNum}단계 사전 생성 실패: ${e.message}`, "error");
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

  if (
    !confirm(
      "전체 문서에 대해 일괄 사전 생성(3단계 직행)을 실행합니다.\n시간이 걸릴 수 있습니다. 진행하시겠습니까?",
    )
  )
    return;

  const btn = document.getElementById("ann-dict-batch-btn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "일괄 생성 중…";
  }

  try {
    const llmSel =
      typeof getLlmModelSelection === "function"
        ? getLlmModelSelection("ann-llm-model-select")
        : { force_provider: null, force_model: null };

    const reqBody = {};
    if (llmSel.force_provider) reqBody.force_provider = llmSel.force_provider;
    if (llmSel.force_model) reqBody.force_model = llmSel.force_model;

    const resp = await fetch(
      `/api/interpretations/${interpId}/annotations/generate-batch`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqBody),
      },
    );

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `서버 오류 ${resp.status}`);
    }

    const result = await resp.json();
    _showSaveStatus(
      `일괄 생성 완료: ${result.pages_processed}페이지, ${result.total_annotations}개 항목`,
    );

    // 현재 블록 갱신
    if (annState.blockId) {
      await _loadBlockAnnotations(annState.blockId);
      _renderSourceText();
      _renderAnnList();
      _renderStatusSummary();
    }
  } catch (e) {
    console.error("일괄 사전 생성 실패:", e);
    showToast("일괄 사전 생성 실패: " + e.message, "error");
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
    const resp = await fetch(
      `/api/interpretations/${interpId}/export/dictionary`,
    );
    if (!resp.ok) throw new Error("내보내기 실패");

    const data = await resp.json();
    const count = data.entries ? data.entries.length : 0;

    // JSON 다운로드
    const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `dictionary_${interpId}.json`;
    a.click();
    URL.revokeObjectURL(url);

    _showSaveStatus(`사전 내보내기: ${count}개 항목`);
  } catch (e) {
    console.error("사전 내보내기 실패:", e);
    showToast("사전 내보내기 실패: " + e.message, "error");
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
        "merge",
      );
      if (!strategy) return;

      const resp = await fetch(
        `/api/interpretations/${interpId}/import/dictionary`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            dictionary_data: dictData,
            merge_strategy: strategy,
          }),
        },
      );

      if (!resp.ok) throw new Error("가져오기 실패");

      const result = await resp.json();
      _showSaveStatus(
        `가져오기: 새로 ${result.imported}개, 병합 ${result.merged}개, 건너뜀 ${result.skipped}개`,
      );

      // 갱신
      if (annState.blockId) {
        await _loadBlockAnnotations(annState.blockId);
        _renderSourceText();
        _renderAnnList();
      }
    } catch (err) {
      console.error("사전 가져오기 실패:", err);
      showToast("사전 가져오기 실패: " + err.message, "error");
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
  if (refs)
    refs.value = (d.source_references || []).map((r) => r.title).join(", ");

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
  const blockId = _annApiBlockId();
  const annId = annState.selectedAnnId;

  const hw = document.getElementById("ann-dict-headword");
  const reading = document.getElementById("ann-dict-reading");
  const dictMeaning = document.getElementById("ann-dict-meaning");
  const ctxMeaning = document.getElementById("ann-dict-ctx-meaning");
  const refs = document.getElementById("ann-dict-src-refs");
  const related = document.getElementById("ann-dict-related");
  const notes = document.getElementById("ann-dict-notes");

  const sourceRefs =
    refs && refs.value
      ? refs.value
          .split(",")
          .map((s) => ({ title: s.trim() }))
          .filter((r) => r.title)
      : [];

  const relatedTerms =
    related && related.value
      ? related.value
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
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
      },
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
