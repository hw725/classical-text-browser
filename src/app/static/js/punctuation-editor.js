/**
 * 표점 편집기 (L5 句讀) — Phase 11-1
 *
 * 기능:
 *   - 원문 글자를 나열하고, 글자 사이를 클릭하여 표점 삽입 위치 선택
 *   - 표점 부호 팔레트에서 부호를 클릭하여 삽입
 *   - 감싸기 부호(《》 등)는 범위 선택 후 삽입
 *   - AI 표점 버튼 → LLM Draft 생성
 *   - 실시간 미리보기 갱신
 *
 * 의존성:
 *   - sidebar-tree.js (viewerState)
 *   - interpretation.js (interpState)
 */


/* ──────────────────────────
   상태 객체
   ────────────────────────── */

const punctState = {
  active: false,           // 모드 활성화 여부
  originalText: "",        // L4 원문 (블록 텍스트)
  blockId: "",             // 현재 블록 ID
  marks: [],               // 현재 표점 목록
  presets: [],             // 표점 부호 프리셋
  selectedSlot: null,      // 선택된 삽입 위치 (글자 인덱스, "after" 기준)
  selectionRange: null,    // 범위 선택 {start, end} (감싸기 부호용)
  isDirty: false,          // 변경 여부
  activePaletteTab: "fullwidth",  // 현재 선택된 팔레트 카테고리
};


/* ──────────────────────────
   초기화
   ────────────────────────── */

/**
 * 표점 편집기를 초기화한다.
 * DOMContentLoaded에서 workspace.js가 호출한다.
 */
// eslint-disable-next-line no-unused-vars
function initPunctuationEditor() {
  _loadPresets();
  _bindPunctEvents();
}


/**
 * 표점 프리셋을 로드한다.
 * 정적 JSON 파일에서 프리셋 목록을 읽어온다.
 */
async function _loadPresets() {
  try {
    const res = await fetch("/api/punctuation-presets");
    if (!res.ok) {
      // API 불가 시 하드코딩 폴백
      punctState.presets = _defaultPresets();
      _renderPalette();
      return;
    }
    const data = await res.json();
    punctState.presets = data.presets || [];
    _renderPalette();
  } catch {
    punctState.presets = _defaultPresets();
    _renderPalette();
  }
}


/**
 * 프리셋 폴백 (네트워크 불가 시).
 *
 * category 분류:
 *   fullwidth  — 전각 문장부호 (중국/일본식)
 *   halfwidth  — 반각 문장부호 (한국식, 공백 없이 삽입)
 *   paired     — 감싸기 부호 (범위 선택 후 한 쌍으로 삽입)
 *   individual — 개별 삽입 (열기/닫기 부호를 단독으로 삽입)
 */
function _defaultPresets() {
  return [
    // 전각
    { id: "period", label: "마침표", category: "fullwidth", before: null, after: "。" },
    { id: "comma", label: "쉼표", category: "fullwidth", before: null, after: "，" },
    { id: "enumeration", label: "나열점", category: "fullwidth", before: null, after: "、" },
    { id: "semicolon", label: "쌍점", category: "fullwidth", before: null, after: "；" },
    { id: "colon", label: "고리점", category: "fullwidth", before: null, after: "：" },
    { id: "question", label: "물음표", category: "fullwidth", before: null, after: "？" },
    { id: "exclamation", label: "느낌표", category: "fullwidth", before: null, after: "！" },
    // 반각
    { id: "period_hw", label: "마침표(반각)", category: "halfwidth", before: null, after: "." },
    { id: "comma_hw", label: "쉼표(반각)", category: "halfwidth", before: null, after: "," },
    { id: "semicolon_hw", label: "쌍점(반각)", category: "halfwidth", before: null, after: ";" },
    { id: "colon_hw", label: "고리점(반각)", category: "halfwidth", before: null, after: ":" },
    { id: "question_hw", label: "물음표(반각)", category: "halfwidth", before: null, after: "?" },
    { id: "exclamation_hw", label: "느낌표(반각)", category: "halfwidth", before: null, after: "!" },
    // 감싸기
    { id: "book_title", label: "서명호", category: "paired", before: "《", after: "》" },
    { id: "chapter_title", label: "편명호", category: "paired", before: "〈", after: "〉" },
    { id: "quote_single", label: "인용부호", category: "paired", before: "「", after: "」" },
    { id: "quote_double", label: "겹인용부호", category: "paired", before: "『", after: "』" },
    // 개별 삽입 (감싸기 부호의 열기/닫기를 각각 단독 삽입)
    { id: "paren_open", label: "소괄호 열기", category: "individual", before: null, after: "（" },
    { id: "paren_close", label: "소괄호 닫기", category: "individual", before: null, after: "）" },
    { id: "guillemet_open", label: "서명호 열기", category: "individual", before: null, after: "《" },
    { id: "guillemet_close", label: "서명호 닫기", category: "individual", before: null, after: "》" },
    { id: "angle_open", label: "편명호 열기", category: "individual", before: null, after: "〈" },
    { id: "angle_close", label: "편명호 닫기", category: "individual", before: null, after: "〉" },
    { id: "corner_open", label: "인용부호 열기", category: "individual", before: null, after: "「" },
    { id: "corner_close", label: "인용부호 닫기", category: "individual", before: null, after: "」" },
    { id: "dcorner_open", label: "겹인용부호 열기", category: "individual", before: null, after: "『" },
    { id: "dcorner_close", label: "겹인용부호 닫기", category: "individual", before: null, after: "』" },
  ];
}


/* ──────────────────────────
   이벤트 바인딩
   ────────────────────────── */

function _bindPunctEvents() {
  // 블록 선택
  const blockSelect = document.getElementById("punct-block-select");
  if (blockSelect) {
    blockSelect.addEventListener("change", () => {
      const blockId = blockSelect.value;
      if (blockId) {
        punctState.blockId = blockId;
        _loadPunctuationData();
      }
    });
  }

  // 저장 버튼
  const saveBtn = document.getElementById("punct-save-btn");
  if (saveBtn) saveBtn.addEventListener("click", _savePunctuation);

  // 초기화 버튼
  const clearBtn = document.getElementById("punct-clear-btn");
  if (clearBtn) clearBtn.addEventListener("click", _clearPunctuation);

  // AI 표점 버튼
  const aiBtn = document.getElementById("punct-ai-btn");
  if (aiBtn) aiBtn.addEventListener("click", _requestAiPunctuation);
  // (LLM 모델 목록은 workspace.js의 _loadAllLlmModelSelects()가 일괄 로드)
}


/* ──────────────────────────
   모드 활성화/비활성화
   ────────────────────────── */

/**
 * 표점 모드를 활성화한다.
 * 현재 페이지의 원문과 표점 데이터를 로드한다.
 */
// eslint-disable-next-line no-unused-vars
function activatePunctuationMode() {
  punctState.active = true;
  _populateBlockSelect();
  if (punctState.blockId) {
    _loadPunctuationData();
  }
}

/**
 * 표점 모드를 비활성화한다.
 */
// eslint-disable-next-line no-unused-vars
function deactivatePunctuationMode() {
  punctState.active = false;
  punctState.selectedSlot = null;
  punctState.selectionRange = null;
}


/* ──────────────────────────
   블록 선택 드롭다운
   ────────────────────────── */

/**
 * 블록 선택 드롭다운을 채운다.
 *
 * 왜 이렇게 하는가:
 *   편성 단계를 거쳤으면 TextBlock이 존재한다.
 *   TextBlock이 있으면 TextBlock 목록을 드롭다운에 표시하고,
 *   없으면 기존처럼 LayoutBlock 목록을 표시한다 (하위 호환).
 */
async function _populateBlockSelect() {
  const select = document.getElementById("punct-block-select");
  if (!select) return;

  // 기본 옵션만 남기기
  select.innerHTML = '<option value="">블록 선택</option>';

  if (!viewerState.docId || !viewerState.partId || !viewerState.pageNum) return;

  // TextBlock이 있으면 우선 사용
  if (interpState.interpId) {
    try {
      const tbRes = await fetch(
        `/api/interpretations/${interpState.interpId}/entities/text_block?page=${viewerState.pageNum}&document_id=${viewerState.docId}`
      );
      if (tbRes.ok) {
        const tbData = await tbRes.json();
        const textBlocks = (tbData.entities || []).filter((e) => {
          const refs = e.source_refs || [];
          const ref = e.source_ref;
          if (refs.length > 0) return refs.some((r) => r.page === viewerState.pageNum);
          if (ref) return ref.page === viewerState.pageNum;
          return false;
        }).sort((a, b) => (a.sequence_index || 0) - (b.sequence_index || 0));

        if (textBlocks.length > 0) {
          // TextBlock 기반 드롭다운
          textBlocks.forEach((tb) => {
            const opt = document.createElement("option");
            // TextBlock ID를 value로 사용 (UUID)
            opt.value = `tb:${tb.id}`;
            const refs = tb.source_refs || [];
            const srcLabel = refs.map((r) => r.layout_block_id || "?").join("+");
            opt.textContent = `#${tb.sequence_index} TextBlock (${srcLabel})`;
            // TextBlock 텍스트를 data 속성에 저장
            opt.dataset.text = tb.original_text || "";
            select.appendChild(opt);
          });

          // 이전 선택 복원 또는 첫 번째 자동 선택
          if (punctState.blockId && select.querySelector(`option[value="${punctState.blockId}"]`)) {
            select.value = punctState.blockId;
          } else if (select.options.length > 1) {
            select.selectedIndex = 1;
            punctState.blockId = select.value;
            _loadPunctuationData();
          }
          return;
        }
      }
    } catch {
      // TextBlock 조회 실패 시 LayoutBlock 폴백
    }
  }

  // 폴백: LayoutBlock 기반 드롭다운 (편성 미완료 시)
  try {
    const res = await fetch(
      `/api/documents/${viewerState.docId}/pages/${viewerState.pageNum}/layout?part_id=${viewerState.partId}`
    );
    if (!res.ok) {
      const opt = document.createElement("option");
      opt.value = `p${String(viewerState.pageNum).padStart(2, "0")}_b01`;
      opt.textContent = `p${String(viewerState.pageNum).padStart(2, "0")}_b01 (기본)`;
      select.appendChild(opt);
      return;
    }
    const data = await res.json();
    const blocks = data.blocks || [];

    if (blocks.length === 0) {
      const opt = document.createElement("option");
      opt.value = `p${String(viewerState.pageNum).padStart(2, "0")}_b01`;
      opt.textContent = `p${String(viewerState.pageNum).padStart(2, "0")}_b01 (기본)`;
      select.appendChild(opt);
    } else {
      blocks.forEach((block) => {
        const opt = document.createElement("option");
        opt.value = block.block_id;
        opt.textContent = `${block.block_id} (${block.block_type || "text"})`;
        select.appendChild(opt);
      });
    }

    // 이전에 선택했던 블록이 있으면 복원
    if (punctState.blockId) {
      select.value = punctState.blockId;
    } else if (select.options.length > 1) {
      select.selectedIndex = 1;
      punctState.blockId = select.value;
      _loadPunctuationData();
    }
  } catch {
    const opt = document.createElement("option");
    opt.value = `p${String(viewerState.pageNum).padStart(2, "0")}_b01`;
    opt.textContent = `p${String(viewerState.pageNum).padStart(2, "0")}_b01 (기본)`;
    select.appendChild(opt);
  }
}


/* ──────────────────────────
   데이터 로드
   ────────────────────────── */

/**
 * 현재 블록의 원문 + 표점 데이터를 로드한다.
 *
 * 왜 이렇게 하는가:
 *   blockId가 "tb:UUID" 형식이면 TextBlock에서 텍스트를 가져오고,
 *   그렇지 않으면 기존처럼 L4 텍스트에서 가져온다 (하위 호환).
 *   TextBlock을 사용하면 교정이 적용된 텍스트를 자동으로 받을 수 있다.
 */
async function _loadPunctuationData() {
  if (!interpState.interpId || !viewerState.pageNum || !punctState.blockId) {
    _renderCharArea();
    return;
  }

  const isTextBlock = punctState.blockId.startsWith("tb:");

  try {
    if (isTextBlock) {
      // TextBlock 기반: 원본 문서의 최신 교정 텍스트를 우선 사용
      //
      // 왜 이렇게 하는가:
      //   TextBlock의 original_text는 편성(composition) 시점의 스냅샷이다.
      //   편성 이후에 교감/교정을 수정하면 TextBlock에는 반영되지 않는다.
      //   따라서 source_refs를 통해 원본 문서의 최신 교정 텍스트를 가져온다.
      //   교정 텍스트를 못 가져오면 TextBlock 원본을 폴백으로 사용한다.
      const tbId = punctState.blockId.replace("tb:", "");
      let tbData = null;

      // TextBlock 정보 조회 (source_refs 필요)
      try {
        const tbRes = await fetch(
          `/api/interpretations/${interpState.interpId}/entities/text_block/${tbId}`
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
              `/api/documents/${viewerState.docId}/pages/${refPage}/corrected-text?part_id=${viewerState.partId}`
            );
            if (ctRes.ok) {
              const ctData = await ctRes.json();
              // source_refs에 layout_block_id가 있으면 해당 블록만 추출
              const pageRefs = tbData.source_refs.filter((r) => r.page === refPage);
              for (const ref of pageRefs) {
                if (ref.layout_block_id && ctData.blocks) {
                  const match = ctData.blocks.find((b) => b.block_id === ref.layout_block_id);
                  if (match) {
                    texts.push(match.corrected_text || match.original_text || "");
                    continue;
                  }
                }
                // 블록 매칭 실패 시 전체 교정 텍스트
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
        punctState.originalText = correctedText;
      } else {
        // 폴백: TextBlock의 원본 텍스트 (편성 시점 스냅샷)
        const select = document.getElementById("punct-block-select");
        const selectedOpt = select ? select.querySelector(`option[value="${punctState.blockId}"]`) : null;
        punctState.originalText = (selectedOpt && selectedOpt.dataset.text)
          ? selectedOpt.dataset.text
          : (tbData ? tbData.original_text || "" : "");
      }

      // 표점 로드 (block_id는 TextBlock ID)
      const punctBlockId = tbId;
      const punctRes = await fetch(
        `/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/punctuation?block_id=${punctBlockId}`
      );
      if (punctRes.ok) {
        const punctData = await punctRes.json();
        punctState.marks = punctData.marks || [];
      } else {
        punctState.marks = [];
      }

    } else {
      // 기존 LayoutBlock 기반 (하위 호환)
      const [textRes, punctRes] = await Promise.all([
        fetch(`/api/documents/${viewerState.docId}/pages/${viewerState.pageNum}/corrected-text?part_id=${viewerState.partId}`),
        fetch(`/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/punctuation?block_id=${punctState.blockId}`),
      ]);

      // 교정된 텍스트에서 해당 블록의 텍스트를 추출
      if (textRes.ok) {
        const data = await textRes.json();
        const blocks = data.blocks || [];
        const match = blocks.find((b) => b.block_id === punctState.blockId);
        if (match) {
          punctState.originalText = match.corrected_text || match.original_text || "";
        } else {
          // 블록 매칭 실패 시 전체 교정 텍스트 사용
          punctState.originalText = data.corrected_text || "";
        }
      } else {
        punctState.originalText = "";
      }

      // 표점 로드
      if (punctRes.ok) {
        const punctData = await punctRes.json();
        punctState.marks = punctData.marks || [];
      } else {
        punctState.marks = [];
      }
    }

    punctState.isDirty = false;
    _renderCharArea();
    _renderMarksList();
    _renderPreview();
    // 마크가 있으면 목록/미리보기 자동 펼침
    _openDetailsIfHasMarks();
  } catch (e) {
    console.error("표점 데이터 로드 실패:", e);
  }
}


/* ──────────────────────────
   렌더링 — 글자 영역
   ────────────────────────── */

/**
 * 원문 글자를 글자 단위로 렌더링한다.
 *
 * 왜 이렇게 하는가:
 *   각 글자를 span으로 감싸고, 글자 사이에 클릭 가능한 슬롯(빈칸)을 배치.
 *   슬롯을 클릭하면 그 위치에 표점을 삽입할 수 있다.
 *   이미 표점이 있는 위치에는 표점 부호가 표시된다.
 */
function _renderCharArea() {
  const area = document.getElementById("punct-char-area");
  if (!area) return;

  if (!punctState.originalText) {
    area.innerHTML = '<div class="placeholder">표점 모드: 문헌을 선택하면 원문이 표시됩니다</div>';
    return;
  }

  const text = punctState.originalText;
  const n = text.length;

  // 각 위치의 before/after 표점을 미리 계산
  const beforeMarks = new Array(n).fill(null);
  const afterMarks = new Array(n).fill(null);

  for (const mark of punctState.marks) {
    const start = mark.target?.start ?? 0;
    const end = mark.target?.end ?? start;
    if (mark.before && start >= 0 && start < n) {
      beforeMarks[start] = { text: mark.before, markId: mark.id };
    }
    if (mark.after && end >= 0 && end < n) {
      afterMarks[end] = { text: mark.after, markId: mark.id };
    }
  }

  let html = '<div class="punct-chars">';

  for (let i = 0; i < n; i++) {
    const ch = text[i];

    // before 표점 표시
    if (beforeMarks[i]) {
      html += `<span class="punct-mark punct-mark-before" data-mark-id="${beforeMarks[i].markId}" title="클릭하여 삭제">${beforeMarks[i].text}</span>`;
    }

    // 글자 span (선택 가능)
    const selectedClass = _isCharInSelection(i) ? " punct-char-selected" : "";
    html += `<span class="punct-char${selectedClass}" data-idx="${i}">${ch}</span>`;

    // after 표점 표시
    if (afterMarks[i]) {
      html += `<span class="punct-mark punct-mark-after" data-mark-id="${afterMarks[i].markId}" title="클릭하여 삭제">${afterMarks[i].text}</span>`;
    }

    // 삽입 슬롯 (글자 사이, 마지막 글자 뒤에도)
    const slotClass = punctState.selectedSlot === i ? " punct-slot-active" : "";
    html += `<span class="punct-slot${slotClass}" data-slot="${i}" title="여기에 표점 삽입">┊</span>`;
  }

  html += "</div>";
  area.innerHTML = html;

  // 이벤트 위임: 글자 클릭, 슬롯 클릭, 표점 클릭
  area.addEventListener("click", _handleCharAreaClick);
}


/**
 * 글자/슬롯/표점 클릭 이벤트 처리.
 */
function _handleCharAreaClick(e) {
  const target = e.target;

  // 표점 부호 클릭 → 삭제
  if (target.classList.contains("punct-mark")) {
    const markId = target.dataset.markId;
    if (markId) {
      _removeMark(markId);
    }
    return;
  }

  // 삽입 슬롯 클릭 → 선택
  if (target.classList.contains("punct-slot")) {
    const slot = parseInt(target.dataset.slot, 10);
    if (!isNaN(slot)) {
      punctState.selectedSlot = slot;
      punctState.selectionRange = null;
      _renderCharArea();
    }
    return;
  }

  // 글자 클릭 → 범위 선택 (shift 키로 범위 확장)
  if (target.classList.contains("punct-char")) {
    const idx = parseInt(target.dataset.idx, 10);
    if (!isNaN(idx)) {
      if (e.shiftKey && punctState.selectionRange) {
        // 범위 확장
        punctState.selectionRange.end = idx;
      } else {
        // 새 선택
        punctState.selectionRange = { start: idx, end: idx };
        punctState.selectedSlot = idx;
      }
      _renderCharArea();
    }
    return;
  }
}

/**
 * 글자가 선택 범위 안에 있는지 확인.
 */
function _isCharInSelection(idx) {
  if (!punctState.selectionRange) return false;
  const { start, end } = punctState.selectionRange;
  const lo = Math.min(start, end);
  const hi = Math.max(start, end);
  return idx >= lo && idx <= hi;
}


/* ──────────────────────────
   표점 부호 팔레트
   ────────────────────────── */

/**
 * 팔레트 카테고리 정의.
 * 탭 버튼으로 전환하며, 한 번에 1개 카테고리만 표시한다.
 */
const PALETTE_CATEGORIES = {
  fullwidth:  { label: "전각" },
  halfwidth:  { label: "반각" },
  paired:     { label: "감싸기" },
  individual: { label: "개별" },
};


/**
 * 팔레트를 카테고리 탭 방식으로 렌더링한다.
 *
 * 왜 이렇게 하는가:
 *   기존에 4개 카테고리를 모두 동시에 보여주면 ~150px를 차지하여
 *   글자 영역의 공간이 부족했다. 탭 방식으로 한 카테고리만 표시하면
 *   ~50px로 축소되어 글자 영역에 더 많은 공간을 확보할 수 있다.
 */
function _renderPalette() {
  const tabContainer = document.getElementById("punct-palette-tabs");
  const btnContainer = document.getElementById("punct-palette-row");
  if (!tabContainer || !btnContainer) return;

  // 카테고리별로 프리셋을 분류
  const grouped = {};
  for (const [catId] of Object.entries(PALETTE_CATEGORIES)) {
    grouped[catId] = [];
  }
  for (const preset of punctState.presets) {
    const cat = preset.category || "fullwidth";
    if (grouped[cat]) {
      grouped[cat].push(preset);
    } else {
      grouped.fullwidth.push(preset);
    }
  }

  // 탭 버튼 렌더링 (한 번만 — 이후 탭 전환 시에는 버튼만 갱신)
  tabContainer.innerHTML = "";
  for (const [catId, catMeta] of Object.entries(PALETTE_CATEGORIES)) {
    if (grouped[catId].length === 0) continue;
    const tab = document.createElement("button");
    tab.className = "punct-palette-tab" + (catId === punctState.activePaletteTab ? " active" : "");
    tab.textContent = catMeta.label;
    tab.dataset.cat = catId;
    tab.addEventListener("click", () => {
      punctState.activePaletteTab = catId;
      _renderPaletteButtons(grouped);
      // 탭 active 상태 갱신
      tabContainer.querySelectorAll(".punct-palette-tab").forEach((t) => {
        t.classList.toggle("active", t.dataset.cat === catId);
      });
    });
    tabContainer.appendChild(tab);
  }

  // 현재 탭의 버튼 렌더링
  // grouped를 클로저로 기억하기 위해 저장
  tabContainer._grouped = grouped;
  _renderPaletteButtons(grouped);
}


/**
 * 선택된 카테고리의 프리셋 버튼만 렌더링한다.
 */
function _renderPaletteButtons(grouped) {
  const container = document.getElementById("punct-palette-row");
  if (!container) return;
  container.innerHTML = "";

  const catId = punctState.activePaletteTab;
  const presets = grouped[catId] || [];

  for (const preset of presets) {
    const btn = document.createElement("button");
    btn.className = "punct-preset-btn";
    btn.title = preset.label;
    btn.dataset.presetId = preset.id;

    // 표시할 부호 결정
    if (catId === "paired") {
      btn.textContent = `${preset.before}…${preset.after}`;
      btn.classList.add("punct-preset-paired");
    } else {
      btn.textContent = preset.after || preset.before || "?";
    }

    btn.addEventListener("click", () => _insertPreset(preset));
    container.appendChild(btn);
  }
}


/**
 * 선택된 위치에 프리셋 부호를 삽입한다.
 *
 * 삽입 방식:
 *   - 감싸기(paired) 부호: 반드시 범위 선택 필요 (첫 글자 클릭 → Shift+마지막 글자)
 *     범위가 없으면 안내 메시지를 표시한다.
 *   - 단일/개별 부호: 슬롯(글자 사이 ┊) 클릭 후 삽입
 */
function _insertPreset(preset) {
  // 감싸기 부호 (before + after 모두 있는 경우): 범위 선택 필수
  const isPaired = preset.before && preset.after;

  if (isPaired) {
    if (!punctState.selectionRange) {
      showToast(
        `${preset.before}${preset.after} 감싸기 부호는 범위 선택이 필요합니다.\n\n` +
        "사용법:\n" +
        "  1. 첫 번째 글자를 클릭하세요\n" +
        "  2. Shift 키를 누른 채 마지막 글자를 클릭하세요\n" +
        "  3. 선택된 범위가 주황색으로 표시됩니다\n" +
        "  4. 감싸기 부호 버튼을 클릭하세요\n\n" +
        "개별 삽입이 필요하면 아래 '개별 삽입' 행의 버튼을 사용하세요.",
        'warning',
      );
      return;
    }
    const lo = Math.min(punctState.selectionRange.start, punctState.selectionRange.end);
    const hi = Math.max(punctState.selectionRange.start, punctState.selectionRange.end);
    const mark = {
      id: _genTempId(),
      target: { start: lo, end: hi },
      before: preset.before,
      after: preset.after,
    };
    punctState.marks.push(mark);
  } else {
    // 단일/개별 부호: 슬롯 또는 범위 끝 위치에 삽입
    if (punctState.selectedSlot === null && !punctState.selectionRange) {
      showToast("표점을 삽입할 위치를 먼저 선택하세요.\n글자 사이의 ┊ 를 클릭하세요.", 'warning');
      return;
    }
    const idx = punctState.selectedSlot ?? punctState.selectionRange?.end ?? 0;
    const mark = {
      id: _genTempId(),
      target: { start: idx, end: idx },
      before: preset.before || null,
      after: preset.after || null,
    };
    punctState.marks.push(mark);
  }

  punctState.isDirty = true;
  punctState.selectedSlot = null;
  punctState.selectionRange = null;
  _renderCharArea();
  _renderMarksList();
  _renderPreview();
}


/* ──────────────────────────
   표점 CRUD
   ────────────────────────── */

function _removeMark(markId) {
  punctState.marks = punctState.marks.filter((m) => m.id !== markId);
  punctState.isDirty = true;
  _renderCharArea();
  _renderMarksList();
  _renderPreview();
}

function _clearPunctuation() {
  if (punctState.marks.length > 0 && !confirm("모든 표점을 삭제하시겠습니까?")) return;
  punctState.marks = [];
  punctState.isDirty = true;
  _renderCharArea();
  _renderMarksList();
  _renderPreview();
}


/* ──────────────────────────
   마크 목록 렌더링
   ────────────────────────── */

function _renderMarksList() {
  const list = document.getElementById("punct-marks-list");
  const count = document.getElementById("punct-mark-count");
  if (!list) return;

  if (count) count.textContent = punctState.marks.length;

  if (punctState.marks.length === 0) {
    list.innerHTML = '<div class="placeholder" style="font-size:12px;padding:8px;">표점이 없습니다</div>';
    return;
  }

  let html = "";
  for (const mark of punctState.marks) {
    const s = mark.target?.start ?? "?";
    const e = mark.target?.end ?? s;
    const charRange = s === e
      ? punctState.originalText[s] || `[${s}]`
      : `${punctState.originalText[s] || ""}…${punctState.originalText[e] || ""} [${s}-${e}]`;

    const display = [];
    if (mark.before) display.push(`앞:${mark.before}`);
    if (mark.after) display.push(`뒤:${mark.after}`);

    html += `<div class="punct-mark-item">
      <span class="punct-mark-char">${charRange}</span>
      <span class="punct-mark-info">${display.join(" ")}</span>
      <button class="punct-mark-del" data-mark-id="${mark.id}" title="삭제">&times;</button>
    </div>`;
  }
  list.innerHTML = html;

  // 삭제 버튼 이벤트
  list.querySelectorAll(".punct-mark-del").forEach((btn) => {
    btn.addEventListener("click", () => _removeMark(btn.dataset.markId));
  });
}


/* ──────────────────────────
   미리보기 렌더링
   ────────────────────────── */

/**
 * 클라이언트 사이드에서 미리보기를 생성한다.
 * 서버의 render_punctuated_text와 동일한 알고리즘.
 */
function _renderPreview() {
  const previewEl = document.getElementById("punct-preview");
  if (!previewEl) return;

  const text = punctState.originalText;
  if (!text) {
    previewEl.textContent = "";
    return;
  }

  const n = text.length;
  const beforeBuf = new Array(n).fill("");
  const afterBuf = new Array(n).fill("");

  for (const mark of punctState.marks) {
    const start = mark.target?.start ?? 0;
    const end = mark.target?.end ?? start;
    if (start < 0 || end >= n || start > end) continue;
    if (mark.before) beforeBuf[start] += mark.before;
    if (mark.after) afterBuf[end] += mark.after;
  }

  let result = "";
  for (let i = 0; i < n; i++) {
    result += beforeBuf[i] + text[i] + afterBuf[i];
  }

  previewEl.textContent = result;
}


/* ──────────────────────────
   저장
   ────────────────────────── */

async function _savePunctuation() {
  if (!interpState.interpId || !viewerState.pageNum || !punctState.blockId) {
    showToast("해석 저장소와 블록이 선택되어야 합니다.", 'warning');
    return;
  }

  const statusEl = document.getElementById("punct-save-status");
  if (statusEl) statusEl.textContent = "저장 중...";

  try {
    // TextBlock 경로("tb:xxx")의 접두사를 제거하여 저장.
    // 로드(_loadPunctuationData)에서도 "tb:"를 제거해 API 호출하므로,
    // 저장 시에도 동일하게 제거해야 block_id가 일치한다.
    const saveBlockId = punctState.blockId.startsWith("tb:")
      ? punctState.blockId.slice(3)
      : punctState.blockId;

    const res = await fetch(
      `/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/punctuation`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          block_id: saveBlockId,
          marks: punctState.marks,
        }),
      }
    );

    if (res.ok) {
      punctState.isDirty = false;
      if (statusEl) {
        statusEl.textContent = "저장 완료";
        setTimeout(() => { statusEl.textContent = ""; }, 2000);
      }
    } else {
      const err = await res.json();
      showToast(`저장 실패: ${err.error || "알 수 없는 오류"}`, 'error');
      if (statusEl) statusEl.textContent = "저장 실패";
    }
  } catch (e) {
    showToast(`저장 실패: ${e.message}`, 'error');
    if (statusEl) statusEl.textContent = "저장 실패";
  }
}


/* ──────────────────────────
   AI 표점 요청
   ────────────────────────── */

async function _requestAiPunctuation() {
  if (!punctState.originalText) {
    showToast("원문이 없습니다. 블록을 선택하세요.", 'warning');
    return;
  }

  // ── 선택 영역 판별 ──
  // 드래그로 범위를 선택한 경우: 해당 영역만 AI 표점 (기존 marks 유지).
  // 선택 없으면: 전체 텍스트에 AI 표점 (기존 marks 전체 교체).
  const sel = punctState.selectionRange;
  const hasSelection = sel && sel.start !== sel.end;
  const selLo = hasSelection ? Math.min(sel.start, sel.end) : 0;
  const selHi = hasSelection ? Math.max(sel.start, sel.end) : punctState.originalText.length - 1;

  const scopeLabel = hasSelection
    ? `선택 영역(${selLo}~${selHi})만`
    : "전체 텍스트에";
  if (!confirm(`AI가 ${scopeLabel} 표점을 생성합니다.\n해당 범위의 기존 표점은 덮어씁니다. 계속하시겠습니까?`)) return;

  const aiBtn = document.getElementById("punct-ai-btn");
  const statusEl = document.getElementById("punct-save-status");
  if (aiBtn) {
    aiBtn.disabled = true;
    aiBtn.textContent = "생성 중...";
  }

  // 경과 시간 표시: 1초마다 갱신하여 사용자에게 대기 중임을 알린다.
  const startTime = Date.now();
  const elapsedTimer = setInterval(() => {
    const sec = Math.floor((Date.now() - startTime) / 1000);
    if (aiBtn) aiBtn.textContent = `생성 중... (${sec}초)`;
    if (statusEl) statusEl.textContent = `AI 표점 처리 중... ${sec}초 경과`;
  }, 1000);

  try {
    // LLM 프로바이더/모델 선택 반영
    const llmSel = typeof getLlmModelSelection === "function"
      ? getLlmModelSelection("punct-llm-model-select")
      : { force_provider: null, force_model: null };

    // 대상 영역 추출 (선택 범위 또는 전체)
    const rawText = punctState.originalText;
    const targetText = hasSelection
      ? rawText.substring(selLo, selHi + 1)
      : rawText;

    // 대상 영역에서 공백을 제거하여 LLM에 전달.
    // cleanToTarget: 공백 제거 인덱스 → targetText 내 인덱스 매핑.
    let cleanText = "";
    const cleanToTarget = [];
    for (let i = 0; i < targetText.length; i++) {
      if (!/\s/.test(targetText[i])) {
        cleanToTarget.push(i);
        cleanText += targetText[i];
      }
    }

    if (!cleanText) {
      showToast("선택 영역에 표점할 글자가 없습니다.", 'warning');
      return;
    }

    const reqBody = { text: cleanText };
    if (llmSel.force_provider) reqBody.force_provider = llmSel.force_provider;
    if (llmSel.force_model) reqBody.force_model = llmSel.force_model;

    // LLM에게 표점 생성 요청
    const resp = await fetch("/api/llm/punctuation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reqBody),
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.error || `HTTP ${resp.status}`);
    }

    const data = await resp.json();

    // AI가 반환한 marks를 적용
    // LLM 인덱스(공백 제거 기준) → targetText 인덱스 → 원문 인덱스로 복원.
    if (data.marks && Array.isArray(data.marks)) {
      const cn = cleanText.length;
      const totalReceived = data.marks.length;
      let skipped = 0;
      const newMarks = [];
      for (const m of data.marks) {
        let cs = m.start ?? m.target?.start ?? 0;
        let ce = m.end ?? m.target?.end ?? cs;

        // 부호가 없는 mark는 건너뛴다
        if (!m.before && !m.after) { skipped++; continue; }

        // clean 인덱스 clamp
        if (cs < 0) cs = 0;
        if (ce >= cn) ce = cn - 1;
        if (cs > ce) { skipped++; continue; }

        // clean → targetText → 원문 인덱스
        const tStart = cleanToTarget[cs] ?? 0;
        const tEnd = cleanToTarget[ce] ?? tStart;
        const start = selLo + tStart;
        const end = selLo + tEnd;

        newMarks.push({
          id: m.id || _genTempId(),
          target: { start, end },
          before: m.before || null,
          after: m.after || null,
        });
      }

      if (skipped > 0) {
        console.warn(`[표점] AI 반환 ${totalReceived}개 중 ${skipped}개 무효 mark 제외`);
      }

      // 선택 영역이면: 해당 범위의 기존 marks만 교체, 나머지 유지
      // 전체이면: 전부 교체
      if (hasSelection) {
        punctState.marks = punctState.marks.filter(mk => {
          const ms = mk.target?.start ?? 0;
          const me = mk.target?.end ?? ms;
          // 선택 범위와 겹치는 mark 제거
          return me < selLo || ms > selHi;
        });
        punctState.marks.push(...newMarks);
        // 인덱스 순으로 정렬
        punctState.marks.sort((a, b) => (a.target?.start ?? 0) - (b.target?.start ?? 0));
      } else {
        punctState.marks = newMarks;
      }

      punctState.isDirty = true;
      _renderCharArea();
      _renderMarksList();
      _renderPreview();
      _openDetailsIfHasMarks();
      const statusEl = document.getElementById("punct-save-status");
      if (statusEl) {
        const scope = hasSelection ? `선택 영역에 ` : "";
        const msg = newMarks.length > 0
          ? `${scope}AI 표점 ${newMarks.length}개 생성 완료 — [저장]을 누르세요`
          : "AI가 mark를 생성하지 못했습니다.";
        statusEl.textContent = msg;
        setTimeout(() => { statusEl.textContent = ""; }, 5000);
      }
      if (newMarks.length === 0 && totalReceived > 0) {
        showToast(`AI가 ${totalReceived}개 mark를 반환했으나 모두 무효합니다.`, 'warning');
      }
    } else {
      showToast("AI 응답에 marks가 없습니다. 수동으로 표점을 삽입하세요.", 'warning');
    }
  } catch (e) {
    showToast(`AI 표점 실패: ${e.message}`, 'error');
  } finally {
    clearInterval(elapsedTimer);
    if (aiBtn) {
      aiBtn.disabled = false;
      aiBtn.textContent = "AI 표점";
    }
  }
}


/* ──────────────────────────
   유틸리티
   ────────────────────────── */

/**
 * 임시 ID 생성 (클라이언트 사이드).
 * 서버 저장 시 서버가 재발급할 수도 있지만,
 * 클라이언트에서도 고유 ID가 필요하다.
 */
function _genTempId() {
  return "mk_" + Math.random().toString(36).substring(2, 8);
}


/**
 * 마크가 있으면 마크 목록과 미리보기 details를 자동으로 펼친다.
 * 마크가 없으면 접힌 상태를 유지한다.
 */
function _openDetailsIfHasMarks() {
  const hasMarks = punctState.marks.length > 0;
  const marksDetails = document.getElementById("punct-marks-details");
  const previewDetails = document.getElementById("punct-preview-details");
  if (hasMarks) {
    if (previewDetails) previewDetails.open = true;
  }
  // 마크 목록은 건수가 적을 때만 자동 펼침 (너무 많으면 공간 차지)
  if (hasMarks && punctState.marks.length <= 20) {
    if (marksDetails) marksDetails.open = true;
  }
}
