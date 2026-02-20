/**
 * citation-editor.js — 인용 마크 편집기
 *
 * 연구자가 원문이나 번역에서 텍스트를 드래그하여 인용 마크를 생성하고,
 * 마크된 구절의 원문+표점본+번역+주석을 통합 조회하며,
 * 학술 인용 형식으로 내보내는 편집기.
 *
 * 의존: workspace.js (viewerState), sidebar-tree.js (interpState)
 */

/* ────────────────────────────────────
   상태
   ──────────────────────────────────── */

const citeState = {
  active: false,
  blockId: "",
  originalText: "",       // 현재 블록의 L4 원문
  marks: [],              // 현재 페이지의 인용 마크 배열
  allMarks: [],           // 전체 인용 마크 (전체 보기 모드)
  selectedMarkId: null,
  viewMode: "page",       // "page" | "all"
  resolvedContext: null,   // 선택된 마크의 통합 컨텍스트
};


/* ────────────────────────────────────
   초기화 / 모드 전환
   ──────────────────────────────────── */

function initCitationEditor() {
  // 블록 선택
  const blockSel = document.getElementById("cite-block-select");
  if (blockSel) blockSel.addEventListener("change", _onCiteBlockChange);

  // 보기 모드 전환
  const viewToggle = document.getElementById("cite-view-toggle");
  if (viewToggle) viewToggle.addEventListener("click", _toggleCiteViewMode);

  // 인용 마크 추가 (텍스트 선택 후)
  const addBtn = document.getElementById("cite-add-btn");
  if (addBtn) addBtn.addEventListener("click", _onCiteTextSelection);

  // 내보내기
  const exportBtn = document.getElementById("cite-export-btn");
  if (exportBtn) exportBtn.addEventListener("click", _exportSelectedCitations);

  // 편집 패널 버튼
  const editSave = document.getElementById("cite-edit-save-btn");
  if (editSave) editSave.addEventListener("click", _saveCiteEdit);

  const editDelete = document.getElementById("cite-edit-delete-btn");
  if (editDelete) editDelete.addEventListener("click", _deleteCiteMark);

  const editClose = document.getElementById("cite-edit-close-btn");
  if (editClose) editClose.addEventListener("click", _closeCiteEditPanel);
}


function activateCitationMode() {
  citeState.active = true;
  _populateCiteBlockSelect();
}


function deactivateCitationMode() {
  citeState.active = false;
  citeState.selectedMarkId = null;
  citeState.resolvedContext = null;
  const editPanel = document.getElementById("cite-edit-panel");
  if (editPanel) editPanel.style.display = "none";
  const ctxPanel = document.getElementById("cite-context-panel");
  if (ctxPanel) ctxPanel.style.display = "none";
}


/* ────────────────────────────────────
   블록 선택 / 데이터 로드
   ──────────────────────────────────── */

async function _populateCiteBlockSelect() {
  const sel = document.getElementById("cite-block-select");
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
      _onCiteBlockChange();
    }
  } catch (e) {
    console.error("블록 목록 로드 실패:", e);
  }
}


async function _onCiteBlockChange() {
  const sel = document.getElementById("cite-block-select");
  const blockId = sel ? sel.value : "";
  if (!blockId) return;

  citeState.blockId = blockId;
  citeState.selectedMarkId = null;

  // 편집/컨텍스트 패널 닫기
  const editPanel = document.getElementById("cite-edit-panel");
  if (editPanel) editPanel.style.display = "none";
  const ctxPanel = document.getElementById("cite-context-panel");
  if (ctxPanel) ctxPanel.style.display = "none";

  // 데이터 병렬 로드
  await Promise.all([
    _loadCiteBlockText(blockId),
    _loadCiteMarks(),
  ]);

  _renderCiteSourceText();
  _renderCiteMarkList();
}


async function _loadCiteBlockText(blockId) {
  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  if (!vs || !vs.docId || !vs.pageNum) return;

  try {
    const resp = await fetch(`/api/documents/${vs.docId}/pages/${vs.pageNum}/text`);
    if (!resp.ok) return;
    const data = await resp.json();
    citeState.originalText = data.text || "";
  } catch (e) {
    console.error("텍스트 로드 실패:", e);
    citeState.originalText = "";
  }
}


async function _loadCiteMarks() {
  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${vs.pageNum}/citation-marks`
    );
    if (!resp.ok) return;
    const data = await resp.json();
    citeState.marks = data.marks || [];
  } catch (e) {
    console.error("인용 마크 로드 실패:", e);
    citeState.marks = [];
  }
}


/* ────────────────────────────────────
   원문 렌더링 (하이라이팅)
   ──────────────────────────────────── */

function _renderCiteSourceText() {
  const container = document.getElementById("cite-source-text");
  if (!container) return;

  const text = citeState.originalText;
  if (!text) {
    container.innerHTML = '<span class="placeholder">텍스트가 없습니다</span>';
    return;
  }

  // 인용 마크 하이라이팅: 현재 블록의 마크만
  const blockMarks = citeState.marks.filter(
    m => m.source && m.source.block_id === citeState.blockId
  );

  // 글자별 하이라이트 배열
  const charHighlight = new Array(text.length).fill(false);
  const charMarkId = new Array(text.length).fill(null);

  for (const m of blockMarks) {
    const s = m.source.start;
    const e = m.source.end;
    for (let i = s; i <= e && i < text.length; i++) {
      charHighlight[i] = true;
      charMarkId[i] = m.id;
    }
  }

  // HTML 생성
  let html = "";
  let inHighlight = false;
  let currentMarkId = null;

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    const isHL = charHighlight[i];
    const mid = charMarkId[i];

    if (isHL && (!inHighlight || mid !== currentMarkId)) {
      if (inHighlight) html += "</span>";
      html += `<span class="cite-highlight" data-cite-id="${mid}">`;
      inHighlight = true;
      currentMarkId = mid;
    } else if (!isHL && inHighlight) {
      html += "</span>";
      inHighlight = false;
      currentMarkId = null;
    }

    // 특수문자 이스케이프
    if (ch === "<") html += "&lt;";
    else if (ch === ">") html += "&gt;";
    else if (ch === "&") html += "&amp;";
    else html += ch;
  }
  if (inHighlight) html += "</span>";

  container.innerHTML = html;

  // 하이라이트 클릭 이벤트
  container.querySelectorAll(".cite-highlight").forEach(el => {
    el.addEventListener("click", () => {
      const cid = el.dataset.citeId;
      if (cid) _selectCiteMark(cid);
    });
  });
}


/* ────────────────────────────────────
   마크 목록 렌더링
   ──────────────────────────────────── */

function _renderCiteMarkList() {
  const listEl = document.getElementById("cite-mark-list");
  if (!listEl) return;

  const marks = citeState.viewMode === "all" ? citeState.allMarks : citeState.marks;

  // 마크 카운트 갱신
  const countEl = document.getElementById("cite-mark-count");
  if (countEl) countEl.textContent = (marks || []).length;

  if (!marks || marks.length === 0) {
    listEl.innerHTML = '<div class="placeholder">인용 마크가 없습니다. 원문을 드래그하여 마크하세요.</div>';
    return;
  }

  let html = "";
  for (const m of marks) {
    const selected = m.id === citeState.selectedMarkId ? " cite-card-selected" : "";
    const statusClass = `cite-status-${m.status || "active"}`;
    const snippet = (m.source_text_snapshot || "").slice(0, 20);
    const label = m.label || "";
    const tags = (m.tags || []).map(t => `<span class="cite-tag">${_esc(t)}</span>`).join(" ");
    const pageInfo = m.page_number ? `<span class="cite-page-badge">p.${m.page_number}</span>` : "";

    html += `<div class="cite-card${selected} ${statusClass}" data-cite-id="${m.id}">
      <div class="cite-card-header">
        <span class="cite-card-snippet">${_esc(snippet)}${snippet.length < (m.source_text_snapshot || "").length ? "…" : ""}</span>
        ${pageInfo}
        <input type="checkbox" class="cite-card-check" data-cite-id="${m.id}" title="내보내기 선택">
      </div>
      <div class="cite-card-body">
        ${label ? `<div class="cite-card-label">${_esc(label)}</div>` : ""}
        ${tags ? `<div class="cite-card-tags">${tags}</div>` : ""}
      </div>
    </div>`;
  }

  listEl.innerHTML = html;

  // 카드 클릭 이벤트
  listEl.querySelectorAll(".cite-card").forEach(card => {
    card.addEventListener("click", (e) => {
      // 체크박스 클릭은 무시
      if (e.target.classList.contains("cite-card-check")) return;
      const cid = card.dataset.citeId;
      if (cid) _selectCiteMark(cid);
    });
  });
}


/* ────────────────────────────────────
   마크 선택 → 통합 컨텍스트 resolve
   ──────────────────────────────────── */

async function _selectCiteMark(markId) {
  citeState.selectedMarkId = markId;
  _renderCiteMarkList();  // 선택 표시 갱신

  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";

  // 마크 찾기 (page/all 양쪽에서)
  const mark = citeState.marks.find(m => m.id === markId)
    || citeState.allMarks.find(m => m.id === markId);
  if (!mark) return;

  const pageNum = mark.page_number || vs.pageNum;

  // resolve API 호출
  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${pageNum}/citation-marks/${markId}/resolve`,
      { method: "POST" }
    );
    if (!resp.ok) {
      console.error("resolve 실패:", resp.statusText);
      return;
    }
    const ctx = await resp.json();
    citeState.resolvedContext = ctx;
    _renderCiteContext(ctx);
    _populateCiteEditPanel(mark);
  } catch (e) {
    console.error("인용 컨텍스트 조회 실패:", e);
  }
}


function _renderCiteContext(ctx) {
  const panel = document.getElementById("cite-context-panel");
  if (!panel) return;
  panel.style.display = "";

  // 원문
  const origEl = document.getElementById("cite-ctx-original");
  if (origEl) origEl.textContent = ctx.original_text || "(원문 없음)";

  // 표점본
  const punctEl = document.getElementById("cite-ctx-punctuated");
  if (punctEl) punctEl.textContent = ctx.punctuated_text || "(표점 미적용)";

  // 텍스트 변경 경고
  const warnEl = document.getElementById("cite-ctx-text-changed");
  if (warnEl) warnEl.style.display = ctx.text_changed ? "" : "none";

  // 번역
  const transEl = document.getElementById("cite-ctx-translations");
  if (transEl) {
    if (ctx.translations && ctx.translations.length > 0) {
      transEl.innerHTML = ctx.translations.map(t =>
        `<div class="cite-ctx-trans-item">
          <span class="cite-ctx-trans-status">[${t.status}]</span>
          ${_esc(t.translation)}
        </div>`
      ).join("");
    } else {
      transEl.innerHTML = '<span class="placeholder">번역 없음</span>';
    }
  }

  // 주석
  const annEl = document.getElementById("cite-ctx-annotations");
  if (annEl) {
    if (ctx.annotations && ctx.annotations.length > 0) {
      annEl.innerHTML = ctx.annotations.map(a => {
        const dict = a.dictionary;
        const dictInfo = dict
          ? ` — ${_esc(dict.headword || "")}(${_esc(dict.headword_reading || "")}): ${_esc(dict.dictionary_meaning || "")}`
          : "";
        return `<div class="cite-ctx-ann-item">
          <span class="cite-ctx-ann-type">[${_esc(a.type)}]</span>
          <strong>${_esc(a.label)}</strong>
          ${a.description ? `: ${_esc(a.description)}` : ""}
          ${dictInfo}
        </div>`;
      }).join("");
    } else {
      annEl.innerHTML = '<span class="placeholder">주석 없음</span>';
    }
  }
}


/* ────────────────────────────────────
   텍스트 선택 → 인용 마크 추가
   ──────────────────────────────────── */

function _onCiteTextSelection() {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed) {
    alert("원문에서 인용할 텍스트를 먼저 드래그하세요.");
    return;
  }

  const text = citeState.originalText;
  const selectedText = selection.toString();
  if (!selectedText || selectedText.length === 0) return;

  // 정확한 위치 계산: getSelection의 Range 사용
  const range = _getSelectionCharRange();
  if (!range) {
    alert("텍스트 범위를 결정할 수 없습니다. 원문 영역에서 드래그하세요.");
    return;
  }

  const label = prompt(
    `"${selectedText.slice(0, 30)}${selectedText.length > 30 ? "…" : ""}" 인용 메모:`,
    ""
  );
  if (label === null) return;  // 취소

  const tagsStr = prompt("태그 (쉼표 구분, 없으면 빈칸):", "");
  const tags = tagsStr ? tagsStr.split(",").map(t => t.trim()).filter(Boolean) : [];

  _addCitationMark(range.start, range.end, selectedText, label || null, tags);
  selection.removeAllRanges();
}


/**
 * 현재 Selection의 정확한 글자 인덱스를 계산한다.
 *
 * 왜 text.indexOf() 대신 이 방식을 쓰는가:
 *   동일한 글자열이 원문에 여러 번 나타날 때 indexOf()는
 *   항상 첫 번째 위치만 반환한다. Range API를 사용하면
 *   실제 선택 위치를 정확히 알 수 있다.
 */
function _getSelectionCharRange() {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return null;

  const container = document.getElementById("cite-source-text");
  if (!container) return null;

  const range = sel.getRangeAt(0);

  // container 기준 글자 인덱스 계산
  const preRange = document.createRange();
  preRange.selectNodeContents(container);
  preRange.setEnd(range.startContainer, range.startOffset);
  const startText = preRange.toString();

  const fullRange = document.createRange();
  fullRange.selectNodeContents(container);
  fullRange.setEnd(range.endContainer, range.endOffset);
  const endText = fullRange.toString();

  const start = startText.length;
  const end = endText.length - 1;  // inclusive

  if (start > end || end < 0) return null;
  return { start, end };
}


async function _addCitationMark(start, end, selectedText, label, tags) {
  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";
  const blockId = citeState.blockId;

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${vs.pageNum}/citation-marks`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          block_id: blockId,
          start: start,
          end: end,
          marked_from: "original",
          source_text_snapshot: selectedText,
          label: label,
          tags: tags,
        }),
      }
    );
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      alert(`인용 마크 추가 실패: ${err.error || resp.statusText}`);
      return;
    }

    // 갱신
    await _loadCiteMarks();
    _renderCiteSourceText();
    _renderCiteMarkList();
    _showCiteSaveStatus("마크 추가됨");
  } catch (e) {
    console.error("인용 마크 추가 실패:", e);
  }
}


/* ────────────────────────────────────
   편집 패널
   ──────────────────────────────────── */

function _populateCiteEditPanel(mark) {
  const panel = document.getElementById("cite-edit-panel");
  if (!panel) return;
  panel.style.display = "";

  const labelEl = document.getElementById("cite-edit-label");
  if (labelEl) labelEl.value = mark.label || "";

  const tagsEl = document.getElementById("cite-edit-tags");
  if (tagsEl) tagsEl.value = (mark.tags || []).join(", ");

  const statusEl = document.getElementById("cite-edit-status");
  if (statusEl) statusEl.value = mark.status || "active";

  // Citation override
  const override = mark.citation_override || {};
  const workTitleEl = document.getElementById("cite-edit-work-title");
  if (workTitleEl) workTitleEl.value = override.work_title || "";

  const pageRefEl = document.getElementById("cite-edit-page-ref");
  if (pageRefEl) pageRefEl.value = override.page_ref || "";

  const suppEl = document.getElementById("cite-edit-supplementary");
  if (suppEl) suppEl.value = override.supplementary || "";
}


async function _saveCiteEdit() {
  if (!citeState.selectedMarkId) return;

  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";
  const markId = citeState.selectedMarkId;

  // 마크 페이지 번호 결정
  const mark = citeState.marks.find(m => m.id === markId)
    || citeState.allMarks.find(m => m.id === markId);
  const pageNum = (mark && mark.page_number) || vs.pageNum;

  const label = document.getElementById("cite-edit-label");
  const tags = document.getElementById("cite-edit-tags");
  const status = document.getElementById("cite-edit-status");
  const workTitle = document.getElementById("cite-edit-work-title");
  const pageRef = document.getElementById("cite-edit-page-ref");
  const supp = document.getElementById("cite-edit-supplementary");

  const tagsArr = tags ? tags.value.split(",").map(t => t.trim()).filter(Boolean) : [];

  const override = {};
  if (workTitle && workTitle.value) override.work_title = workTitle.value;
  else override.work_title = null;
  if (pageRef && pageRef.value) override.page_ref = pageRef.value;
  else override.page_ref = null;
  if (supp && supp.value) override.supplementary = supp.value;
  else override.supplementary = null;

  const hasOverride = override.work_title || override.page_ref || override.supplementary;

  const body = {
    label: label ? label.value || null : null,
    tags: tagsArr,
    status: status ? status.value : "active",
    citation_override: hasOverride ? override : null,
  };

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${pageNum}/citation-marks/${markId}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    );
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      alert(`수정 실패: ${err.error || resp.statusText}`);
      return;
    }

    await _loadCiteMarks();
    _renderCiteMarkList();
    _showCiteSaveStatus("수정 저장됨");
  } catch (e) {
    console.error("인용 마크 수정 실패:", e);
  }
}


async function _deleteCiteMark() {
  if (!citeState.selectedMarkId) return;
  if (!confirm("이 인용 마크를 삭제하시겠습니까?")) return;

  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";
  const markId = citeState.selectedMarkId;

  const mark = citeState.marks.find(m => m.id === markId)
    || citeState.allMarks.find(m => m.id === markId);
  const pageNum = (mark && mark.page_number) || vs.pageNum;

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/pages/${pageNum}/citation-marks/${markId}`,
      { method: "DELETE" }
    );
    if (!resp.ok) {
      alert("삭제 실패");
      return;
    }

    citeState.selectedMarkId = null;
    const editPanel = document.getElementById("cite-edit-panel");
    if (editPanel) editPanel.style.display = "none";
    const ctxPanel = document.getElementById("cite-context-panel");
    if (ctxPanel) ctxPanel.style.display = "none";

    await _loadCiteMarks();
    _renderCiteSourceText();
    _renderCiteMarkList();
    _showCiteSaveStatus("마크 삭제됨");
  } catch (e) {
    console.error("인용 마크 삭제 실패:", e);
  }
}


function _closeCiteEditPanel() {
  citeState.selectedMarkId = null;
  const editPanel = document.getElementById("cite-edit-panel");
  if (editPanel) editPanel.style.display = "none";
  const ctxPanel = document.getElementById("cite-context-panel");
  if (ctxPanel) ctxPanel.style.display = "none";
  _renderCiteMarkList();
}


/* ────────────────────────────────────
   보기 모드 전환 (페이지 / 전체)
   ──────────────────────────────────── */

async function _toggleCiteViewMode() {
  const btn = document.getElementById("cite-view-toggle");

  if (citeState.viewMode === "page") {
    citeState.viewMode = "all";
    if (btn) btn.textContent = "페이지 보기";
    await _loadAllCiteMarks();
  } else {
    citeState.viewMode = "page";
    if (btn) btn.textContent = "전체 보기";
  }

  _renderCiteMarkList();
}


async function _loadAllCiteMarks() {
  const is = typeof interpState !== "undefined" ? interpState : null;
  const interpId = (is && is.interpId) || "default";

  try {
    const resp = await fetch(`/api/interpretations/${interpId}/citation-marks/all`);
    if (!resp.ok) return;
    citeState.allMarks = await resp.json();
  } catch (e) {
    console.error("전체 인용 마크 로드 실패:", e);
    citeState.allMarks = [];
  }
}


/* ────────────────────────────────────
   인용 내보내기
   ──────────────────────────────────── */

async function _exportSelectedCitations() {
  const is = typeof interpState !== "undefined" ? interpState : null;
  const interpId = (is && is.interpId) || "default";

  // 체크된 마크 수집
  const checks = document.querySelectorAll(".cite-card-check:checked");
  const markIds = [];
  checks.forEach(cb => markIds.push(cb.dataset.citeId));

  if (markIds.length === 0) {
    alert("내보낼 인용 마크를 선택하세요 (체크박스).");
    return;
  }

  const inclTrans = confirm("번역도 포함하시겠습니까?");

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/citation-marks/export`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mark_ids: markIds,
          include_translation: inclTrans,
        }),
      }
    );
    if (!resp.ok) {
      alert("내보내기 실패");
      return;
    }

    const result = await resp.json();
    const citationText = result.citations || "";

    if (!citationText) {
      alert("내보낼 내용이 없습니다.");
      return;
    }

    // 미리보기 + 클립보드 복사
    const preview = document.getElementById("cite-export-preview");
    if (preview) {
      preview.textContent = citationText;
      preview.style.display = "";
    }

    try {
      await navigator.clipboard.writeText(citationText);
      _showCiteSaveStatus(`${result.count}건 클립보드 복사됨`);
    } catch (clipErr) {
      // 클립보드 접근 실패 시 (보안 정책)
      prompt("아래 텍스트를 복사하세요:", citationText);
    }
  } catch (e) {
    console.error("인용 내보내기 실패:", e);
  }
}


/* ────────────────────────────────────
   유틸리티
   ──────────────────────────────────── */

function _esc(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}


function _showCiteSaveStatus(msg) {
  const el = document.getElementById("cite-save-status");
  if (!el) return;
  el.textContent = msg;
  setTimeout(() => { el.textContent = ""; }, 3000);
}
