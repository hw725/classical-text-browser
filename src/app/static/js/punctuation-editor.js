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
 */
function _defaultPresets() {
  return [
    { id: "period", label: "마침표", before: null, after: "。" },
    { id: "comma", label: "쉼표", before: null, after: "，" },
    { id: "semicolon", label: "쌍점", before: null, after: "；" },
    { id: "colon", label: "고리점", before: null, after: "：" },
    { id: "question", label: "물음표", before: null, after: "？" },
    { id: "exclamation", label: "느낌표", before: null, after: "！" },
    { id: "book_title", label: "서명호", before: "《", after: "》" },
    { id: "chapter_title", label: "편명호", before: "〈", after: "〉" },
    { id: "quote_single", label: "인용부호", before: "「", after: "」" },
    { id: "quote_double", label: "겹인용부호", before: "『", after: "』" },
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
 * 교정 모드의 블록 필터와 같은 방식으로, 레이아웃 블록 목록을 가져온다.
 */
async function _populateBlockSelect() {
  const select = document.getElementById("punct-block-select");
  if (!select) return;

  // 기본 옵션만 남기기
  select.innerHTML = '<option value="">블록 선택</option>';

  if (!viewerState.docId || !viewerState.partId || !viewerState.pageNum) return;

  try {
    const res = await fetch(
      `/api/documents/${viewerState.docId}/pages/${viewerState.pageNum}/layout?part_id=${viewerState.partId}`
    );
    if (!res.ok) {
      // 레이아웃이 없으면 기본 블록 하나 제공
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
      // 첫 번째 블록 자동 선택
      select.selectedIndex = 1;
      punctState.blockId = select.value;
      _loadPunctuationData();
    }
  } catch {
    // 네트워크 오류 시 기본 블록
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
 */
async function _loadPunctuationData() {
  if (!interpState.interpId || !viewerState.pageNum || !punctState.blockId) {
    _renderCharArea();
    return;
  }

  try {
    // 원문 + 표점을 병렬 로드
    const [textRes, punctRes] = await Promise.all([
      fetch(`/api/documents/${viewerState.docId}/pages/${viewerState.pageNum}/text?part_id=${viewerState.partId}`),
      fetch(`/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/punctuation?block_id=${punctState.blockId}`),
    ]);

    // 원문 로드
    if (textRes.ok) {
      const textData = await textRes.json();
      // 텍스트에서 블록에 해당하는 부분을 추출
      // 현재는 전체 텍스트를 사용 (향후 블록별 분리 가능)
      punctState.originalText = textData.text || "";
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

    punctState.isDirty = false;
    _renderCharArea();
    _renderMarksList();
    _renderPreview();
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

function _renderPalette() {
  const row = document.getElementById("punct-palette-row");
  if (!row) return;

  row.innerHTML = "";
  for (const preset of punctState.presets) {
    const btn = document.createElement("button");
    btn.className = "punct-preset-btn";
    btn.title = preset.label;
    btn.dataset.presetId = preset.id;

    // 표시할 부호 결정
    const display = preset.before && preset.after
      ? `${preset.before}…${preset.after}`  // 감싸기 부호
      : preset.after || preset.before || "?";

    btn.textContent = display;
    btn.addEventListener("click", () => _insertPreset(preset));
    row.appendChild(btn);
  }
}


/**
 * 선택된 위치에 프리셋 부호를 삽입한다.
 */
function _insertPreset(preset) {
  if (punctState.selectedSlot === null && !punctState.selectionRange) {
    alert("표점을 삽입할 위치를 먼저 선택하세요.\n글자 사이의 ┊ 를 클릭하세요.");
    return;
  }

  // 감싸기 부호 (before + after 모두 있는 경우): 범위 선택 필요
  if (preset.before && preset.after) {
    if (punctState.selectionRange) {
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
      // 범위 없이 슬롯만 선택 → 해당 글자 하나에 적용
      const idx = punctState.selectedSlot;
      const mark = {
        id: _genTempId(),
        target: { start: idx, end: idx },
        before: preset.before,
        after: preset.after,
      };
      punctState.marks.push(mark);
    }
  } else {
    // 단일 부호 (after만 또는 before만)
    const idx = punctState.selectedSlot ?? 0;
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
    alert("해석 저장소와 블록이 선택되어야 합니다.");
    return;
  }

  const statusEl = document.getElementById("punct-save-status");
  if (statusEl) statusEl.textContent = "저장 중...";

  try {
    const res = await fetch(
      `/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/punctuation`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          block_id: punctState.blockId,
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
      alert(`저장 실패: ${err.error || "알 수 없는 오류"}`);
      if (statusEl) statusEl.textContent = "저장 실패";
    }
  } catch (e) {
    alert(`저장 실패: ${e.message}`);
    if (statusEl) statusEl.textContent = "저장 실패";
  }
}


/* ──────────────────────────
   AI 표점 요청
   ────────────────────────── */

async function _requestAiPunctuation() {
  if (!punctState.originalText) {
    alert("원문이 없습니다. 블록을 선택하세요.");
    return;
  }

  if (!confirm("AI가 표점을 자동 생성합니다.\n기존 표점이 있으면 덮어씁니다. 계속하시겠습니까?")) return;

  const aiBtn = document.getElementById("punct-ai-btn");
  if (aiBtn) {
    aiBtn.disabled = true;
    aiBtn.textContent = "생성 중...";
  }

  try {
    // preview API를 통해 AI 표점을 시뮬레이션
    // (실제 LLM 호출은 서버 사이드, 여기서는 미구현 — 향후 연결)
    alert("AI 표점 기능은 LLM 연결 후 사용 가능합니다.\n수동으로 표점을 삽입하세요.");
  } finally {
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
