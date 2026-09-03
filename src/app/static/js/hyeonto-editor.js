/**
 * 현토 편집기 (L5 懸吐) — Phase 11-1
 *
 * 기능:
 *   - 원문 글자를 나열하고, 글자(범위) 클릭 → 현토 입력 팝업
 *   - 위치(after/before) 선택 + 토 텍스트 입력 → 삽입
 *   - 삽입된 현토는 원문 옆에 시각적으로 표시
 *   - 표점이 있으면 함께 반영된 미리보기
 *
 * 텍스트 로드 우선순위:
 *   1. 단위 모드 → source_refs를 통해 원본 문서의 최신 교정 텍스트
 *   2. 단위 모드 → 폴백: 단위.original_text (편성 시점 스냅샷)
 *   3. LayoutBlock 모드 → /api/documents/.../corrected-text 교정 텍스트
 *
 * 의존성:
 *   - sidebar-tree.js (viewerState)
 *   - interpretation.js (interpState)
 */


/* ──────────────────────────
   상태 객체
   ────────────────────────── */

const hyeontoState = {
  active: false,           // 모드 활성화 여부
  originalText: "",        // 교정된 텍스트 (또는 원문 폴백)
  blockId: "",             // 현재 블록 ID ("unit:UUID" 또는 LayoutBlock ID)
  annotations: [],         // 현재 현토 목록
  punctMarks: [],          // 현재 표점 목록 (미리보기용)
  selectedChar: null,      // 선택된 글자 인덱스
  selectionRange: null,    // 범위 선택 {start, end}
  isDirty: false,          // 변경 여부
};

/**
 * API용 block_id 반환 — "unit:" 접두사 제거.
 * 표점·번역·현토 모두 서버에는 접두사 없이 저장해야
 * block_id 매칭이 일치한다.
 */
function _htApiBlockId() {
  return hyeontoState.blockId.startsWith("unit:")
    ? hyeontoState.blockId.slice(5)
    : hyeontoState.blockId;
}


/* ──────────────────────────
   초기화
   ────────────────────────── */

/**
 * 현토 편집기를 초기화한다.
 * DOMContentLoaded에서 workspace.js가 호출한다.
 */
// eslint-disable-next-line no-unused-vars
function initHyeontoEditor() {
  _bindHyeontoEvents();
}


/* ──────────────────────────
   이벤트 바인딩
   ────────────────────────── */

function _bindHyeontoEvents() {
  // 블록 선택
  const blockSelect = document.getElementById("hyeonto-block-select");
  if (blockSelect) {
    blockSelect.addEventListener("change", () => {
      const blockId = blockSelect.value;
      if (blockId) {
        hyeontoState.blockId = blockId;
        _loadHyeontoData();
      }
    });
  }

  // 저장 버튼
  const saveBtn = document.getElementById("hyeonto-save-btn");
  if (saveBtn) saveBtn.addEventListener("click", _saveHyeonto);

  // 초기화 버튼
  const clearBtn = document.getElementById("hyeonto-clear-btn");
  if (clearBtn) clearBtn.addEventListener("click", _clearHyeonto);

  // 팝업 닫기
  const closeBtn = document.getElementById("hyeonto-popup-close");
  if (closeBtn) closeBtn.addEventListener("click", _hidePopup);

  // 삽입 버튼
  const insertBtn = document.getElementById("hyeonto-insert-btn");
  if (insertBtn) insertBtn.addEventListener("click", _insertAnnotation);

  // Enter 키로 삽입
  const textInput = document.getElementById("hyeonto-text-input");
  if (textInput) {
    textInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        _insertAnnotation();
      }
    });
  }
}


/* ──────────────────────────
   모드 활성화/비활성화
   ────────────────────────── */

// eslint-disable-next-line no-unused-vars
async function activateHyeontoMode() {
  hyeontoState.active = true;
  // await가 «반드시» 필요하다: _populateHyeontoBlockSelect는 서버 응답을 받은
  // 뒤에야 hyeontoState.blockId를 새 페이지 것으로 바꾼다. 기다리지 않으면
  // 아래 if가 «이전 페이지의» blockId를 읽어 엉뚱한 현토를 불러온다.
  await _populateHyeontoBlockSelect();
  if (hyeontoState.blockId) {
    _loadHyeontoData();
  }
}

// eslint-disable-next-line no-unused-vars
function deactivateHyeontoMode() {
  hyeontoState.active = false;
  hyeontoState.selectedChar = null;
  hyeontoState.selectionRange = null;
  _hidePopup();
}


/* ──────────────────────────
   블록 선택 드롭다운
   ────────────────────────── */

/**
 * 단위가 있으면 우선 사용, 없으면 LayoutBlock 폴백.
 * 표점·번역 편집기와 동일한 block_id 체계를 사용한다.
 *
 * 왜 이렇게 하는가:
 *   표점이 단위 ID로 저장되므로, 현토에서도 같은 ID를 써야
 *   표점 데이터를 찾을 수 있다.
 */
async function _populateHyeontoBlockSelect() {
  const select = document.getElementById("hyeonto-block-select");
  if (!select) return;

  select.innerHTML = '<option value="">블록 선택</option>';

  if (!viewerState.docId || !viewerState.partId || !viewerState.pageNum) return;

  // 단위가 있으면 우선 사용
  if (interpState.interpId) {
    try {
      const tbRes = await fetch(
        `/api/interpretations/${interpState.interpId}/entities/unit?document_id=${viewerState.docId}`
      );
      if (tbRes.ok) {
        const tbData = await tbRes.json();
        const units = (tbData.entities || []).sort((a, b) => (a.sequence_index || 0) - (b.sequence_index || 0));

        if (units.length > 0) {
          units.forEach((tb) => {
            const opt = document.createElement("option");
            opt.value = `unit:${tb.id}`;
            // 이름은 깊이가 아니라 역할이 정한다(D-092) — 3단에 오는 기사도 있다
            const _lv = Number(tb.metadata?.level) || 2;
            const _role =
              tb.metadata?.role || (_lv <= 1 ? "container" : _lv === 2 ? "article" : "fragment");
            const _kind = { container: "묶음", article: "기사", fragment: "조각" }[_role];
            const _title = tb.metadata?.title ? ` · ${tb.metadata.title}` : "";
            opt.textContent = `#${tb.sequence_index} ${_kind}${_title}`;
            opt.dataset.text = tb.original_text || "";
            select.appendChild(opt);
          });

          if (hyeontoState.blockId && select.querySelector(`option[value="${hyeontoState.blockId}"]`)) {
            select.value = hyeontoState.blockId;
          } else if (select.options.length > 1) {
            // 첫 번째를 저절로 고르지 않는다 — 어느 대목인지 모른 채 표점이 찍힌다.
            // 「내용」 트리에서 고른 단위를 따라간다(사용자 요청 2026-09-04).
            const _sel = typeof currentUnitId === "function" ? currentUnitId() : null;
            const _opt = _sel && select.querySelector(`option[value="unit:${_sel}"]`);
            if (_opt) select.value = _opt.value;
            else select.selectedIndex = 0;
            hyeontoState.blockId = select.value;
            _loadHyeontoData();
          }
          return;
        }
      }
    } catch {
      // 단위 조회 실패 시 LayoutBlock 폴백
    }
  }

  // 폴백: LayoutBlock 기반 (편성 미완료 시)
  try {
    const res = await fetch(
      `/api/documents/${viewerState.docId}/pages/${viewerState.pageNum}/layout?part_id=${viewerState.partId}`
    );
    if (!res.ok) {
      _addDefaultBlockOption(select);
      return;
    }
    const data = await res.json();
    const blocks = data.blocks || [];

    if (blocks.length === 0) {
      _addDefaultBlockOption(select);
    } else {
      blocks.forEach((block) => {
        const opt = document.createElement("option");
        opt.value = block.block_id;
        opt.textContent = `${block.block_id} (${block.block_type || "text"})`;
        select.appendChild(opt);
      });
    }

    if (hyeontoState.blockId) {
      select.value = hyeontoState.blockId;
    } else if (select.options.length > 1) {
      select.selectedIndex = 1;
      hyeontoState.blockId = select.value;
      _loadHyeontoData();
    }
  } catch {
    _addDefaultBlockOption(select);
  }
}

function _addDefaultBlockOption(select) {
  const opt = document.createElement("option");
  opt.value = `p${String(viewerState.pageNum).padStart(2, "0")}_b01`;
  opt.textContent = `p${String(viewerState.pageNum).padStart(2, "0")}_b01 (기본)`;
  select.appendChild(opt);
}


/* ──────────────────────────
   데이터 로드
   ────────────────────────── */

/**
 * 현재 블록의 교정 텍스트 + 현토 + 표점을 로드한다.
 *
 * 왜 이렇게 하는가:
 *   blockId가 "unit:UUID" 형식이면 단위에서 교정 텍스트를 가져오고,
 *   그렇지 않으면 기존처럼 L4 교정 텍스트에서 가져온다 (하위 호환).
 *   표점 편집기(punctuation-editor.js)와 동일한 패턴.
 */
async function _loadHyeontoData() {
  if (!interpState.interpId || !viewerState.pageNum || !hyeontoState.blockId) {
    _renderHyeontoCharArea();
    return;
  }

  const isUnit = hyeontoState.blockId.startsWith("unit:");

  try {
    if (isUnit) {
      // ── 단위 모드: 최신 교정 텍스트를 우선 사용 ──
      //
      // 왜 이렇게 하는가:
      //   서버가 L4에서 잘라 주므로 교감·교정이 곧바로 반영된다(D-092).
      const unitId = hyeontoState.blockId.replace("unit:", "");
      let tbData = null;

      // 단위 정보 조회 (source_refs 필요)
      try {
        const tbRes = await fetch(
          `/api/interpretations/${interpState.interpId}/entities/unit/${unitId}`
        );
        if (tbRes.ok) tbData = await tbRes.json();
      } catch { /* 폴백 처리 아래 */ }

      // 본문은 서버가 준 것을 그대로 쓴다.
      //
      // 왜 여기서 쪽을 다시 이어 붙이지 않는가: v1.3부터 단위는 본문을 저장하지 않고
      // **읽을 때 L4에서 잘라 온다**(D-092). 즉 서버의 original_text가 이미 «지금 교정본»이고,
      // 쪽 중간에서 시작·끝나는 경계도 글자 단위로 반영돼 있다.
      // 화면이 쪽 전체를 다시 받아 이으면 두 가지가 어긋났다(사용자 지적 2026-09-04):
      //   ① 둘째 쪽부터 빠졌다 — «texts.length === 0»일 때만 담아 첫 쪽만 들어갔다
      //      (layout_block_id는 v1.3부터 늘 null이라 블록 매칭이 언제나 실패한다)
      //   ② 쪽 중간 경계가 무시됐다 — char_range를 보지 않고 쪽 전체를 담았다
      const correctedText = (tbData && tbData.original_text) || "";

      hyeontoState.originalText = correctedText;

      // 현토 + 표점 로드 (block_id는 단위 ID, 접두사 없이)
      const apiBlockId = unitId;
      const [htRes, punctRes] = await Promise.all([
        fetch(`/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/hyeonto?block_id=${apiBlockId}`),
        fetch(`/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/punctuation?block_id=${apiBlockId}`),
      ]);

      hyeontoState.annotations = htRes.ok ? (await htRes.json()).annotations || [] : [];
      hyeontoState.punctMarks = punctRes.ok ? (await punctRes.json()).marks || [] : [];

    } else {
      // ── LayoutBlock 모드 (하위 호환) ──
      // 교정 텍스트 API를 사용하여 해당 블록의 교정된 텍스트를 가져온다.
      const [textRes, htRes, punctRes] = await Promise.all([
        fetch(`/api/documents/${viewerState.docId}/pages/${viewerState.pageNum}/corrected-text?part_id=${viewerState.partId}`),
        fetch(`/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/hyeonto?block_id=${hyeontoState.blockId}`),
        fetch(`/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/punctuation?block_id=${hyeontoState.blockId}`),
      ]);

      // 교정된 텍스트에서 해당 블록의 텍스트를 추출
      if (textRes.ok) {
        const data = await textRes.json();
        const blocks = data.blocks || [];
        const match = blocks.find((b) => b.block_id === hyeontoState.blockId);
        if (match) {
          hyeontoState.originalText = match.corrected_text || match.original_text || "";
        } else {
          // 블록 매칭 실패 시 전체 교정 텍스트 사용
          hyeontoState.originalText = data.corrected_text || "";
        }
      } else {
        hyeontoState.originalText = "";
      }

      hyeontoState.annotations = htRes.ok ? (await htRes.json()).annotations || [] : [];
      hyeontoState.punctMarks = punctRes.ok ? (await punctRes.json()).marks || [] : [];
    }

    hyeontoState.isDirty = false;
    _renderHyeontoCharArea();
    _renderAnnList();
    _renderHyeontoPreview();
  } catch (e) {
    console.error("현토 데이터 로드 실패:", e);
  }
}


/* ──────────────────────────
   렌더링 — 글자 영역
   ────────────────────────── */

/**
 * 원문 글자를 글자 단위로 렌더링한다.
 *
 * 왜 이렇게 하는가:
 *   각 글자를 span으로 감싸고, 위에 현토를 작은 루비 텍스트로 표시.
 *   글자 클릭 시 현토 입력 팝업을 표시한다.
 */
function _renderHyeontoCharArea() {
  const area = document.getElementById("hyeonto-char-area");
  if (!area) return;

  if (!hyeontoState.originalText) {
    area.innerHTML = '<div class="placeholder">현토 모드: 문헌을 선택하면 원문이 표시됩니다</div>';
    return;
  }

  const text = hyeontoState.originalText;
  const n = text.length;

  // 각 위치별 현토 텍스트를 미리 계산
  const annBefore = new Array(n).fill("");
  const annAfter = new Array(n).fill("");

  for (const ann of hyeontoState.annotations) {
    const start = ann.target?.start ?? 0;
    const end = ann.target?.end ?? start;
    const position = ann.position || "after";
    const annText = ann.text || "";

    if (start < 0 || end >= n || start > end) continue;

    if (position === "before") {
      annBefore[start] += annText;
    } else {
      annAfter[end] += annText;
    }
  }

  let html = '<div class="hyeonto-chars">';

  for (let i = 0; i < n; i++) {
    const ch = text[i];
    const hasAnn = annBefore[i] || annAfter[i];
    const selectedClass = _isHtCharInSelection(i) ? " hyeonto-char-selected" : "";
    const annClass = hasAnn ? " hyeonto-char-annotated" : "";

    html += `<span class="hyeonto-char-wrapper${selectedClass}${annClass}" data-idx="${i}">`;

    // 현토 표시 (루비 스타일)
    if (annBefore[i]) {
      html += `<span class="hyeonto-ruby hyeonto-ruby-before">${annBefore[i]}</span>`;
    }
    if (annAfter[i]) {
      html += `<span class="hyeonto-ruby hyeonto-ruby-after">${annAfter[i]}</span>`;
    }

    html += `<span class="hyeonto-char">${ch}</span>`;
    html += `</span>`;
  }

  html += "</div>";
  area.innerHTML = html;

  // 이벤트 위임: 글자 클릭
  area.addEventListener("click", _handleHtCharAreaClick);
}


function _handleHtCharAreaClick(e) {
  let wrapper = e.target.closest(".hyeonto-char-wrapper");
  if (!wrapper) return;

  const idx = parseInt(wrapper.dataset.idx, 10);
  if (isNaN(idx)) return;

  if (e.shiftKey && hyeontoState.selectionRange) {
    hyeontoState.selectionRange.end = idx;
  } else {
    hyeontoState.selectionRange = { start: idx, end: idx };
    hyeontoState.selectedChar = idx;
  }

  _renderHyeontoCharArea();
  _showPopup(idx);
}

function _isHtCharInSelection(idx) {
  if (!hyeontoState.selectionRange) return false;
  const { start, end } = hyeontoState.selectionRange;
  const lo = Math.min(start, end);
  const hi = Math.max(start, end);
  return idx >= lo && idx <= hi;
}


/* ──────────────────────────
   현토 입력 팝업
   ────────────────────────── */

function _showPopup(charIdx) {
  const popup = document.getElementById("hyeonto-input-popup");
  const targetLabel = document.getElementById("hyeonto-popup-target");
  const textInput = document.getElementById("hyeonto-text-input");

  if (!popup) return;

  // 선택된 글자 표시
  const text = hyeontoState.originalText;
  if (hyeontoState.selectionRange) {
    const lo = Math.min(hyeontoState.selectionRange.start, hyeontoState.selectionRange.end);
    const hi = Math.max(hyeontoState.selectionRange.start, hyeontoState.selectionRange.end);
    const chars = text.substring(lo, hi + 1);
    if (targetLabel) targetLabel.textContent = chars;
  } else {
    if (targetLabel) targetLabel.textContent = text[charIdx] || "";
  }

  popup.style.display = "";
  if (textInput) {
    textInput.value = "";
    textInput.focus();
  }
}

function _hidePopup() {
  const popup = document.getElementById("hyeonto-input-popup");
  if (popup) popup.style.display = "none";
}


/* ──────────────────────────
   현토 삽입
   ────────────────────────── */

function _insertAnnotation() {
  const posSelect = document.getElementById("hyeonto-position-select");
  const textInput = document.getElementById("hyeonto-text-input");

  if (!textInput || !textInput.value.trim()) {
    showToast("토 텍스트를 입력하세요.", 'warning');
    return;
  }

  const position = posSelect ? posSelect.value : "after";
  const annText = textInput.value.trim();

  let start, end;
  if (hyeontoState.selectionRange) {
    start = Math.min(hyeontoState.selectionRange.start, hyeontoState.selectionRange.end);
    end = Math.max(hyeontoState.selectionRange.start, hyeontoState.selectionRange.end);
  } else if (hyeontoState.selectedChar !== null) {
    start = hyeontoState.selectedChar;
    end = start;
  } else {
    showToast("글자를 먼저 선택하세요.", 'warning');
    return;
  }

  const ann = {
    id: "ht_" + Math.random().toString(36).substring(2, 8),
    target: { start, end },
    position,
    text: annText,
    category: null,
  };

  hyeontoState.annotations.push(ann);
  hyeontoState.isDirty = true;

  // 팝업 닫기 + 선택 해제
  _hidePopup();
  hyeontoState.selectedChar = null;
  hyeontoState.selectionRange = null;

  _renderHyeontoCharArea();
  _renderAnnList();
  _renderHyeontoPreview();
}


/* ──────────────────────────
   현토 삭제 / 초기화
   ────────────────────────── */

function _removeAnnotation(annId) {
  hyeontoState.annotations = hyeontoState.annotations.filter((a) => a.id !== annId);
  hyeontoState.isDirty = true;
  _renderHyeontoCharArea();
  _renderAnnList();
  _renderHyeontoPreview();
}

function _clearHyeonto() {
  if (hyeontoState.annotations.length > 0 && !confirm("모든 현토를 삭제하시겠습니까?")) return;
  hyeontoState.annotations = [];
  hyeontoState.isDirty = true;
  _renderHyeontoCharArea();
  _renderAnnList();
  _renderHyeontoPreview();
}


/* ──────────────────────────
   현토 목록 렌더링
   ────────────────────────── */

function _renderAnnList() {
  const list = document.getElementById("hyeonto-ann-list");
  const count = document.getElementById("hyeonto-ann-count");
  if (!list) return;

  if (count) count.textContent = hyeontoState.annotations.length;

  if (hyeontoState.annotations.length === 0) {
    list.innerHTML = '<div class="placeholder" style="font-size:12px;padding:8px;">현토가 없습니다</div>';
    return;
  }

  const text = hyeontoState.originalText;
  let html = "";

  for (const ann of hyeontoState.annotations) {
    const s = ann.target?.start ?? 0;
    const e = ann.target?.end ?? s;
    const chars = s === e ? (text[s] || `[${s}]`) : `${text[s] || ""}…${text[e] || ""} [${s}-${e}]`;
    const posLabel = ann.position === "before" ? "앞" : "뒤";

    html += `<div class="hyeonto-ann-item">
      <span class="hyeonto-ann-char">${chars}</span>
      <span class="hyeonto-ann-info">${posLabel}: ${ann.text}</span>
      <button class="hyeonto-ann-del" data-ann-id="${ann.id}" title="삭제">&times;</button>
    </div>`;
  }
  list.innerHTML = html;

  list.querySelectorAll(".hyeonto-ann-del").forEach((btn) => {
    btn.addEventListener("click", () => _removeAnnotation(btn.dataset.annId));
  });
}


/* ──────────────────────────
   미리보기 렌더링
   ────────────────────────── */

/**
 * 클라이언트 사이드에서 미리보기를 생성한다.
 * 표점 + 현토를 모두 반영한다.
 */
function _renderHyeontoPreview() {
  const previewEl = document.getElementById("hyeonto-preview");
  if (!previewEl) return;

  const text = hyeontoState.originalText;
  if (!text) {
    previewEl.textContent = "";
    return;
  }

  const n = text.length;
  const beforeBuf = new Array(n).fill("");
  const afterBuf = new Array(n).fill("");

  // 표점 적용
  for (const mark of hyeontoState.punctMarks) {
    const start = mark.target?.start ?? 0;
    const end = mark.target?.end ?? start;
    if (start < 0 || end >= n || start > end) continue;
    if (mark.before) beforeBuf[start] += mark.before;
    if (mark.after) afterBuf[end] += mark.after;
  }

  // 현토 적용
  for (const ann of hyeontoState.annotations) {
    const start = ann.target?.start ?? 0;
    const end = ann.target?.end ?? start;
    if (start < 0 || end >= n || start > end) continue;
    if (ann.position === "before") {
      beforeBuf[start] += ann.text || "";
    } else {
      afterBuf[end] += ann.text || "";
    }
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

async function _saveHyeonto() {
  if (!interpState.interpId || !viewerState.pageNum || !hyeontoState.blockId) {
    showToast("해석 저장소와 블록이 선택되어야 합니다.", 'warning');
    return;
  }

  // API에 전달할 block_id: "unit:" 접두사 제거
  const apiBlockId = _htApiBlockId();

  const statusEl = document.getElementById("hyeonto-save-status");
  if (statusEl) statusEl.textContent = "저장 중...";

  try {
    const res = await fetch(
      `/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/hyeonto`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          block_id: apiBlockId,
          annotations: hyeontoState.annotations,
        }),
      }
    );

    if (res.ok) {
      hyeontoState.isDirty = false;
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
