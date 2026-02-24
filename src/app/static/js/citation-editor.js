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
  blockId: "",            // "tb:<id>" (TextBlock) 또는 LayoutBlock ID
  originalText: "",       // 현재 블록의 L4 원문
  punctMarks: [],         // 표점 marks (원문 미리보기에 적용)
  marks: [],              // 현재 페이지의 인용 마크 배열
  allMarks: [],           // 전체 인용 마크 (전체 보기 모드)
  selectedMarkId: null,
  viewMode: "page",       // "page" | "all"
  resolvedContext: null,   // 선택된 마크의 통합 컨텍스트
};

/* ────────────────────────────────────
   내보내기 프리셋 / 설정
   ──────────────────────────────────── */

/** 인용 내보내기 필드 정의 (드래그 목록에 표시) */
const CITE_FIELD_DEFS = [
  { id: "author",          label: "저자" },
  { id: "book_volume",     label: "서명 + 권수" },
  { id: "work_page",       label: "작품명 + 페이지" },
  { id: "punctuated_text", label: "표점 원문" },
  { id: "translation",     label: "번역" },
];

/**
 * CITE_PRESETS는 이제 cite-format-manager.js의 getCiteFormatLibrary()를 통해
 * 동적으로 관리된다. 이 파일에서는 양식 라이브러리를 조회하여 사용한다.
 */

const CITE_EXPORT_SETTINGS_KEY = "cite_export_settings";

/** localStorage에서 내보내기 설정 로드. 없으면 한국 학술 형식 기본값. */
function _loadCiteExportSettings() {
  try {
    const raw = localStorage.getItem(CITE_EXPORT_SETTINGS_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* 파싱 실패 시 기본값 */ }
  // 기본값: 양식 라이브러리의 첫 번째 양식 (한국 학술 형식)
  const lib = typeof getCiteFormatLibrary === "function" ? getCiteFormatLibrary() : [];
  const first = lib[0] || {};
  return {
    preset: first.id || "korean_academic",
    field_order: first.field_order || ["author", "book_volume", "work_page", "punctuated_text", "translation"],
    bracket_replace_single: _normalizeBracketMode(first.bracket_replace_single),
    bracket_replace_double: _normalizeBracketMode(first.bracket_replace_double),
    wrap_double_quotes: first.wrap_double_quotes || false,
    include_translation: first.include_translation !== false,
  };
}

/** 현재 설정을 localStorage에 저장 */
function _saveCiteExportSettings(settings) {
  localStorage.setItem(CITE_EXPORT_SETTINGS_KEY, JSON.stringify(settings));
}

/**
 * 인용 탭의 프리셋 드롭다운을 양식 라이브러리에서 동적 생성한다.
 * cite-format-manager.js에서 양식 저장/삭제 시 호출됨.
 */
function _refreshCitePresetSelect() {
  const sel = document.getElementById("cite-preset-select");
  if (!sel) return;

  // 현재 선택값 보존
  const currentVal = sel.value;

  // 기존 option 제거 (마지막 "사용자 정의"만 남기기)
  sel.innerHTML = "";

  // 양식 라이브러리에서 option 추가
  const library = typeof getCiteFormatLibrary === "function" ? getCiteFormatLibrary() : [];
  library.forEach(fmt => {
    const opt = document.createElement("option");
    opt.value = fmt.id;
    opt.textContent = fmt.name;
    sel.appendChild(opt);
  });

  // "사용자 정의" option 추가
  const customOpt = document.createElement("option");
  customOpt.value = "custom";
  customOpt.textContent = "사용자 정의";
  sel.appendChild(customOpt);

  // 이전 선택값 복원 (존재하면)
  const hasOption = Array.from(sel.options).some(o => o.value === currentVal);
  sel.value = hasOption ? currentVal : (library[0]?.id || "custom");
}

/**
 * API용 block_id 반환 — "tb:" 접두사 제거.
 * 표점·번역·주석·인용 모두 서버에는 접두사 없이 저장해야
 * block_id 매칭이 일치한다.
 */
function _citeApiBlockId() {
  return citeState.blockId.startsWith("tb:")
    ? citeState.blockId.slice(3)
    : citeState.blockId;
}


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

  // 리셋 버튼: 현재 페이지의 모든 인용 마크 삭제
  const resetBtn = document.getElementById("cite-reset-btn");
  if (resetBtn) resetBtn.addEventListener("click", _resetAllCiteMarks);

  // 내보내기 설정 패널 초기화
  _initCiteExportSettings();
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

  // TextBlock이 있으면 우선 사용 (번역·주석 편집기와 동일한 block_id 체계).
  // 왜: 표점·번역·주석이 TextBlock ID로 저장되므로, 인용에서도 같은 ID를
  //     사용해야 resolve 시 올바른 데이터를 매칭할 수 있다.
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (is && is.interpId) {
    try {
      const tbRes = await fetch(
        `/api/interpretations/${is.interpId}/entities/text_block?page=${vs.pageNum}&document_id=${vs.docId}`
      );
      if (tbRes.ok) {
        const tbData = await tbRes.json();
        const textBlocks = (tbData.entities || []).filter((e) => {
          const refs = e.source_refs || [];
          const ref = e.source_ref;
          if (refs.length > 0) return refs.some((r) => r.page === vs.pageNum);
          if (ref) return ref.page === vs.pageNum;
          return false;
        }).sort((a, b) => (a.sequence_index || 0) - (b.sequence_index || 0));

        if (textBlocks.length > 0) {
          textBlocks.forEach((tb) => {
            const opt = document.createElement("option");
            opt.value = `tb:${tb.id}`;
            const refs = tb.source_refs || [];
            const srcLabel = refs.map((r) => r.layout_block_id || "?").join("+");
            opt.textContent = `#${tb.sequence_index} TextBlock (${srcLabel})`;
            opt.dataset.text = tb.original_text || "";
            sel.appendChild(opt);
          });

          // 이전 선택값 복원 또는 첫 번째 블록 자동 선택
          if (citeState.blockId && sel.querySelector(`option[value="${citeState.blockId}"]`)) {
            sel.value = citeState.blockId;
          } else if (sel.options.length > 1) {
            sel.selectedIndex = 1;
            citeState.blockId = sel.value;
          }
          _onCiteBlockChange();
          return;
        }
      }
    } catch {
      // TextBlock 조회 실패 시 LayoutBlock 폴백
    }
  }

  // 폴백: LayoutBlock 기반 (편성 미완료 시)
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
    _loadCitePunctuation(blockId),
  ]);

  _renderCiteSourceText();
  _renderCiteMarkList();
}


async function _loadCiteBlockText(blockId) {
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
    if (!is || !is.interpId) { citeState.originalText = ""; return; }
    const apiBlockId = blockId.slice(3);
    let tbData = null;

    // TextBlock 정보 조회 (source_refs 필요)
    try {
      const tbRes = await fetch(
        `/api/interpretations/${is.interpId}/entities/text_block/${apiBlockId}`
      );
      if (tbRes.ok) tbData = await tbRes.json();
    } catch { /* 폴백 처리 아래 */ }

    // source_refs에서 원본 문서의 교정 텍스트를 가져온다
    let correctedText = "";
    if (tbData && tbData.source_refs && tbData.source_refs.length > 0) {
      const refPages = [...new Set(tbData.source_refs.map((r) => r.page))];
      const texts = [];
      for (const refPage of refPages) {
        try {
          const ctRes = await fetch(
            `/api/documents/${vs.docId}/pages/${refPage}/corrected-text?part_id=${vs.partId}`
          );
          if (ctRes.ok) {
            const ctData = await ctRes.json();
            const pageRefs = tbData.source_refs.filter((r) => r.page === refPage);
            for (const ref of pageRefs) {
              if (ref.layout_block_id && ctData.blocks) {
                const match = ctData.blocks.find((b) => b.block_id === ref.layout_block_id);
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
        } catch { /* skip */ }
      }
      correctedText = texts.join("\n");
    }

    // 교정 텍스트가 있으면 사용, 없으면 TextBlock 원본 폴백
    if (correctedText.trim()) {
      citeState.originalText = correctedText;
    } else {
      const sel = document.getElementById("cite-block-select");
      const selectedOpt = sel ? sel.querySelector(`option[value="${blockId}"]`) : null;
      citeState.originalText = (selectedOpt && selectedOpt.dataset.text)
        ? selectedOpt.dataset.text
        : (tbData ? tbData.original_text || "" : "");
    }
  } else {
    // ── LayoutBlock 모드 (하위 호환) ──
    // 교정 텍스트 API를 사용하여 해당 블록의 교정된 텍스트를 가져온다.
    try {
      const resp = await fetch(
        `/api/documents/${vs.docId}/pages/${vs.pageNum}/corrected-text?part_id=${vs.partId}`
      );
      if (!resp.ok) return;
      const data = await resp.json();
      const blocks = data.blocks || [];
      const match = blocks.find(b => b.block_id === blockId);
      if (match) {
        citeState.originalText = match.corrected_text || match.original_text || "";
      } else {
        citeState.originalText = data.corrected_text || "";
      }
    } catch (e) {
      console.error("텍스트 로드 실패:", e);
      citeState.originalText = "";
    }
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

async function _loadCitePunctuation(blockId) {
  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum || !is || !is.interpId) {
    citeState.punctMarks = [];
    return;
  }

  const apiBlockId = blockId.startsWith("tb:") ? blockId.slice(3) : blockId;

  try {
    const resp = await fetch(
      `/api/interpretations/${is.interpId}/pages/${vs.pageNum}/punctuation?block_id=${apiBlockId}`
    );
    if (resp.ok) {
      const data = await resp.json();
      citeState.punctMarks = data.marks || [];
    } else {
      citeState.punctMarks = [];
    }
  } catch (e) {
    console.error("표점 로드 실패:", e);
    citeState.punctMarks = [];
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

  const n = text.length;

  // ── 표점 before/after 버퍼 구성 ──
  const beforeBuf = new Array(n).fill("");
  const afterBuf = new Array(n).fill("");

  for (const mark of citeState.punctMarks) {
    const start = mark.target?.start ?? 0;
    const end = mark.target?.end ?? start;
    if (start < 0 || end >= n || start > end) continue;
    if (mark.before) beforeBuf[start] += mark.before;
    if (mark.after) afterBuf[end] += mark.after;
  }

  // 인용 마크 하이라이팅: 현재 블록의 마크만
  // 서버에 저장된 block_id는 접두사 없으므로 _citeApiBlockId()로 비교
  const apiBlockId = _citeApiBlockId();
  const blockMarks = citeState.marks.filter(
    m => m.source && m.source.block_id === apiBlockId
  );

  // 글자별 하이라이트 배열
  const charHighlight = new Array(n).fill(false);
  const charMarkId = new Array(n).fill(null);

  for (const m of blockMarks) {
    const s = m.source.start;
    const e = m.source.end;
    for (let i = s; i <= e && i < n; i++) {
      charHighlight[i] = true;
      charMarkId[i] = m.id;
    }
  }

  // HTML 생성: 글자별로 표점 + 하이라이트를 함께 렌더링
  let html = "";
  let inHighlight = false;
  let currentMarkId = null;

  for (let i = 0; i < n; i++) {
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

    // 표점 before + 원문 글자 + 표점 after (이스케이프 포함)
    html += _esc(beforeBuf[i]) + _esc(text[i]) + _esc(afterBuf[i]);
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
    showToast("원문에서 인용할 텍스트를 먼저 드래그하세요.", 'warning');
    return;
  }

  const selectedText = selection.toString();
  if (!selectedText || selectedText.length === 0) return;

  // 정확한 위치 계산: getSelection의 Range 사용
  const range = _getSelectionCharRange();
  if (!range) {
    showToast("텍스트 범위를 결정할 수 없습니다. 원문 영역에서 드래그하세요.", 'warning');
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
 * 표시 오프셋(표점 포함)을 원문 오프셋(표점 제외)으로 변환한다.
 *
 * 왜: 렌더링된 DOM에는 표점 기호(。？！ 등)가 삽입되어 있으므로,
 *   Range API가 반환하는 위치는 표점을 포함한 "표시 위치"이다.
 *   서버는 순수 원문(original_text)의 오프셋을 사용하므로 변환이 필요하다.
 *
 * @param {number} displayOffset - 표점 포함 표시 위치
 * @param {string} originalText - 순수 원문 텍스트
 * @param {Array} punctMarks - 표점 marks 배열
 * @returns {number} 원문 기준 글자 인덱스
 */
function _citeDisplayOffsetToOriginal(displayOffset, originalText, punctMarks) {
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

    displayPos += 1;  // 원문 글자 1자
    if (displayPos > displayOffset) return i;

    displayPos += afterBuf[i].length;
    if (displayPos > displayOffset) return i;
  }

  return n - 1;
}

/**
 * 현재 Selection의 정확한 원문 글자 인덱스를 계산한다.
 *
 * 왜 text.indexOf() 대신 이 방식을 쓰는가:
 *   동일한 글자열이 원문에 여러 번 나타날 때 indexOf()는
 *   항상 첫 번째 위치만 반환한다. Range API를 사용하면
 *   실제 선택 위치를 정확히 알 수 있다.
 *
 * 왜 표시 오프셋 → 원문 오프셋 변환이 필요한가:
 *   렌더링된 DOM에 표점 기호가 삽입되어 있으므로,
 *   Range API의 toString().length는 표점을 포함한 길이를 반환한다.
 *   서버는 표점을 제외한 순수 원문 기준 오프셋을 사용하므로
 *   _citeDisplayOffsetToOriginal()로 변환해야 한다.
 */
function _getSelectionCharRange() {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return null;

  const container = document.getElementById("cite-source-text");
  if (!container) return null;

  const range = sel.getRangeAt(0);

  // 선택이 원문 컨테이너 내부인지 확인
  if (!container.contains(range.startContainer) || !container.contains(range.endContainer)) return null;

  // container 기준 표시 오프셋 계산 (표점 포함)
  const preRange = document.createRange();
  preRange.selectNodeContents(container);
  preRange.setEnd(range.startContainer, range.startOffset);
  const displayStart = preRange.toString().length;

  const fullRange = document.createRange();
  fullRange.selectNodeContents(container);
  fullRange.setEnd(range.endContainer, range.endOffset);
  const displayEnd = fullRange.toString().length - 1;  // inclusive

  if (displayStart > displayEnd || displayEnd < 0) return null;

  // 표시 오프셋 → 원문 오프셋 변환 (표점 기호를 제외한 위치)
  const text = citeState.originalText;
  const start = _citeDisplayOffsetToOriginal(displayStart, text, citeState.punctMarks);
  const end = _citeDisplayOffsetToOriginal(displayEnd, text, citeState.punctMarks);

  if (start > end || end < 0) return null;
  return { start, end };
}


async function _addCitationMark(start, end, selectedText, label, tags) {
  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) return;

  const interpId = (is && is.interpId) || "default";
  const blockId = _citeApiBlockId();

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
      showToast(`인용 마크 추가 실패: ${err.error || resp.statusText}`, 'error');
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
      showToast(`수정 실패: ${err.error || resp.statusText}`, 'error');
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
      showToast("삭제 실패", 'error');
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
   내보내기 설정 패널 초기화 / 드래그앤드롭
   ──────────────────────────────────── */

/** 체크박스 값 설정 헬퍼 */
function _setCiteChecked(id, value) {
  const el = document.getElementById(id);
  if (el) el.checked = !!value;
}

/** select 요소 값 설정 헬퍼 */
function _setCiteSelectValue(id, value) {
  const el = document.getElementById(id);
  if (el) el.value = value || "none";
}

/** 설정 패널의 체크박스·프리셋·필드 순서를 초기화한다. */
function _initCiteExportSettings() {
  const settings = _loadCiteExportSettings();

  // 드롭다운을 양식 라이브러리에서 동적 생성
  _refreshCitePresetSelect();

  // 제목 기호 변환 select 초기화
  _setCiteSelectValue("cite-opt-bracket-single", _normalizeBracketMode(settings.bracket_replace_single));
  _setCiteSelectValue("cite-opt-bracket-double", _normalizeBracketMode(settings.bracket_replace_double));
  _setCiteChecked("cite-opt-wrap-quotes", settings.wrap_double_quotes);
  _setCiteChecked("cite-opt-include-trans", settings.include_translation);

  // 프리셋 선택 복원
  const presetSel = document.getElementById("cite-preset-select");
  if (presetSel) {
    presetSel.value = settings.preset || "custom";
    presetSel.addEventListener("change", _onCitePresetChange);
  }

  // 체크박스 변경 시 → 설정 저장 + 프리셋을 "사용자 정의"로 전환
  ["cite-opt-bracket-single", "cite-opt-bracket-double",
   "cite-opt-wrap-quotes", "cite-opt-include-trans"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", _onCiteSettingChange);
  });

  // 필드 순서 목록 렌더
  const defaultOrder = ["author", "book_volume", "work_page", "punctuated_text", "translation"];
  const order = settings.field_order || defaultOrder;
  _renderCiteFieldOrderList(order);
}

/** 프리셋 select 변경 핸들러 — 양식 라이브러리에서 설정 로드 */
function _onCitePresetChange(e) {
  const presetId = e.target.value;
  if (presetId === "custom") return;

  // 양식 라이브러리에서 해당 양식 찾기
  const library = typeof getCiteFormatLibrary === "function" ? getCiteFormatLibrary() : [];
  const preset = library.find(f => f.id === presetId);
  if (!preset) return;

  _setCiteSelectValue("cite-opt-bracket-single", _normalizeBracketMode(preset.bracket_replace_single));
  _setCiteSelectValue("cite-opt-bracket-double", _normalizeBracketMode(preset.bracket_replace_double));
  _setCiteChecked("cite-opt-wrap-quotes", preset.wrap_double_quotes);
  _setCiteChecked("cite-opt-include-trans", preset.include_translation);
  _renderCiteFieldOrderList(preset.field_order);

  _saveCiteExportSettings({ ...preset, preset: presetId });
}

/** 체크박스 변경 시 프리셋을 "사용자 정의"로 전환하고 설정 저장 */
function _onCiteSettingChange() {
  const presetSel = document.getElementById("cite-preset-select");
  if (presetSel) presetSel.value = "custom";
  _saveCiteExportSettings(_collectCiteExportSettings());
}

/** 설정 패널의 현재 상태를 객체로 수집 */
function _collectCiteExportSettings() {
  return {
    preset: document.getElementById("cite-preset-select")?.value || "custom",
    bracket_replace_single: document.getElementById("cite-opt-bracket-single")?.value || "none",
    bracket_replace_double: document.getElementById("cite-opt-bracket-double")?.value || "none",
    wrap_double_quotes: document.getElementById("cite-opt-wrap-quotes")?.checked || false,
    include_translation: document.getElementById("cite-opt-include-trans")?.checked || false,
    field_order: _getCiteFieldOrder(),
  };
}

/* ── 필드 순서 드래그앤드롭 (HTML5 DnD API) ── */

let _citeFieldDragId = null;

/** 필드 순서 목록을 렌더링한다. 각 아이템은 드래그 가능. */
function _renderCiteFieldOrderList(fieldOrder) {
  const container = document.getElementById("cite-field-order-list");
  if (!container) return;
  container.innerHTML = "";

  fieldOrder.forEach(fieldId => {
    const def = CITE_FIELD_DEFS.find(f => f.id === fieldId);
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

    item.addEventListener("dragstart", _onCiteFieldDragStart);
    item.addEventListener("dragover", _onCiteFieldDragOver);
    item.addEventListener("dragleave", _onCiteFieldDragLeave);
    item.addEventListener("drop", _onCiteFieldDrop);
    item.addEventListener("dragend", _onCiteFieldDragEnd);

    container.appendChild(item);
  });
}

function _onCiteFieldDragStart(e) {
  _citeFieldDragId = e.currentTarget.dataset.fieldId;
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", _citeFieldDragId);
  requestAnimationFrame(() => e.currentTarget.classList.add("dragging"));
}

function _onCiteFieldDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = "move";
  const item = e.currentTarget;
  if (item.dataset.fieldId === _citeFieldDragId) return;

  const rect = item.getBoundingClientRect();
  const midY = rect.top + rect.height / 2;
  item.classList.remove("drag-over-above", "drag-over-below");
  item.classList.add(e.clientY < midY ? "drag-over-above" : "drag-over-below");
}

function _onCiteFieldDragLeave(e) {
  e.currentTarget.classList.remove("drag-over-above", "drag-over-below");
}

function _onCiteFieldDrop(e) {
  e.preventDefault();
  const target = e.currentTarget;
  target.classList.remove("drag-over-above", "drag-over-below");

  const targetFieldId = target.dataset.fieldId;
  if (!_citeFieldDragId || _citeFieldDragId === targetFieldId) return;

  // 현재 순서에서 재배열
  const order = _getCiteFieldOrder();
  const fromIdx = order.indexOf(_citeFieldDragId);
  const toIdx = order.indexOf(targetFieldId);
  if (fromIdx < 0 || toIdx < 0) return;

  order.splice(fromIdx, 1);
  const rect = target.getBoundingClientRect();
  const midY = rect.top + rect.height / 2;
  const insertIdx = e.clientY < midY
    ? order.indexOf(targetFieldId)
    : order.indexOf(targetFieldId) + 1;
  order.splice(insertIdx, 0, _citeFieldDragId);

  _renderCiteFieldOrderList(order);

  // 프리셋을 "사용자 정의"로 전환 + 설정 저장
  const presetSel = document.getElementById("cite-preset-select");
  if (presetSel) presetSel.value = "custom";
  _saveCiteExportSettings(_collectCiteExportSettings());
}

function _onCiteFieldDragEnd(e) {
  _citeFieldDragId = null;
  e.currentTarget.classList.remove("dragging");
}

/** DOM에서 현재 필드 순서를 읽어 반환 */
function _getCiteFieldOrder() {
  const container = document.getElementById("cite-field-order-list");
  if (!container) return CITE_PRESETS.korean_academic.field_order.slice();
  return Array.from(container.querySelectorAll(".cite-field-order-item"))
    .map(el => el.dataset.fieldId);
}


/* ────────────────────────────────────
   인용 내보내기
   ──────────────────────────────────── */

async function _exportSelectedCitations() {
  const is = typeof interpState !== "undefined" ? interpState : null;
  const interpId = is && is.interpId;

  // 해석 저장소가 선택되지 않으면 내보내기 불가
  if (!interpId) {
    showToast("해석 저장소를 먼저 선택하세요.", 'warning');
    return;
  }

  // 체크된 마크 수집
  const checks = document.querySelectorAll(".cite-card-check:checked");
  const markIds = [];
  checks.forEach(cb => markIds.push(cb.dataset.citeId));

  if (markIds.length === 0) {
    showToast("내보낼 인용 마크를 선택하세요 (체크박스).", 'warning');
    return;
  }

  // 설정 패널에서 옵션 읽기 (기존 confirm 대체)
  const settings = _collectCiteExportSettings();
  const inclTrans = settings.include_translation;
  const exportOptions = {
    bracket_replace_single: settings.bracket_replace_single,
    bracket_replace_double: settings.bracket_replace_double,
    wrap_double_quotes: settings.wrap_double_quotes,
    field_order: settings.field_order,
  };

  try {
    const resp = await fetch(
      `/api/interpretations/${interpId}/citation-marks/export`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mark_ids: markIds,
          include_translation: inclTrans,
          export_options: exportOptions,
        }),
      }
    );
    if (!resp.ok) {
      // 서버 에러 메시지를 구체적으로 표시
      const errBody = await resp.json().catch(() => ({}));
      const detail = errBody.error || errBody.detail || resp.statusText;
      showToast(`내보내기 실패: ${detail}`, 'error');
      return;
    }

    const result = await resp.json();
    const citationText = result.citations || "";

    if (!citationText) {
      const reason = result.skipped
        ? `${result.skipped}건 해석 실패 (원문 없음 등)`
        : "내보낼 내용이 없습니다.";
      showToast(reason, 'warning');
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
      const skipInfo = result.skipped ? ` (${result.skipped}건 건너뜀)` : "";
      _showCiteSaveStatus(`${result.count}건 클립보드 복사됨${skipInfo}`);
    } catch (clipErr) {
      // 클립보드 접근 실패 시 (보안 정책)
      prompt("아래 텍스트를 복사하세요:", citationText);
    }
  } catch (e) {
    console.error("인용 내보내기 실패:", e);
    showToast("내보내기 실패: 네트워크 오류", 'error');
  }
}


/* ────────────────────────────────────
   전체 리셋: 현재 페이지의 모든 인용 마크 삭제
   ──────────────────────────────────── */

/**
 * 현재 페이지의 모든 인용 마크를 삭제한다.
 *
 * 왜 이렇게 하는가: 인용 마크를 처음부터 다시 지정하고 싶을 때,
 *   개별 삭제를 반복하는 대신 한 번에 모두 삭제할 수 있다.
 *   삭제 전 confirm()으로 사용자 확인을 받아 실수를 방지한다.
 */
async function _resetAllCiteMarks() {
  const vs = typeof viewerState !== "undefined" ? viewerState : null;
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!vs || !vs.pageNum) {
    showToast("페이지가 선택되어야 합니다.", 'warning');
    return;
  }

  const interpId = (is && is.interpId) || "default";

  if (citeState.marks.length === 0) {
    showToast("삭제할 인용 마크가 없습니다.", 'warning');
    return;
  }

  if (!confirm(
    `현재 페이지의 인용 마크 ${citeState.marks.length}건을 모두 삭제합니다.\n이 작업은 되돌릴 수 없습니다. 계속하시겠습니까?`
  )) return;

  let success = 0;
  let fail = 0;

  // 마크 ID 목록을 미리 복사 (삭제 중 배열 변경 방지)
  const ids = citeState.marks.map(m => m.id);

  for (const markId of ids) {
    try {
      const resp = await fetch(
        `/api/interpretations/${interpId}/pages/${vs.pageNum}/citation-marks/${markId}`,
        { method: "DELETE" }
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
  citeState.selectedMarkId = null;
  citeState.resolvedContext = null;
  const editPanel = document.getElementById("cite-edit-panel");
  if (editPanel) editPanel.style.display = "none";
  const ctxPanel = document.getElementById("cite-context-panel");
  if (ctxPanel) ctxPanel.style.display = "none";

  await _loadCiteMarks();
  _renderCiteSourceText();
  _renderCiteMarkList();

  if (fail > 0) {
    showToast(`인용 마크 리셋 완료: 성공 ${success}건, 실패 ${fail}건`, 'error');
  } else {
    _showCiteSaveStatus(`인용 마크 ${success}건 삭제 완료`);
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
