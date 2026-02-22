/**
 * 번역 편집기 (L6 Translation) — Phase 11-2
 *
 * 기능:
 *   - 문장별 번역 카드 표시 (표점으로 분리된 문장 단위)
 *   - 각 카드에 상태 표시: 미번역 / draft / accepted
 *   - [AI 번역] → 해당 문장 LLM Draft 생성 (향후 연결)
 *   - [수동 입력] → 텍스트 영역 활성화, translator.type = "human"
 *   - 원문 + 표점 + 현토 합성 텍스트 미리보기 (읽기 전용)
 *
 * 의존성:
 *   - sidebar-tree.js (viewerState)
 *   - interpretation.js (interpState)
 */


/* ──────────────────────────
   상태 객체
   ────────────────────────── */

const transState = {
  active: false,
  originalText: "",      // L4 원문
  blockId: "",
  sentences: [],         // split_sentences 결과
  translations: [],      // 서버에서 로드한 번역 데이터
  punctMarks: [],        // 표점
  htAnnotations: [],     // 현토
  isDirty: false,
};


/* ──────────────────────────
   초기화
   ────────────────────────── */

// eslint-disable-next-line no-unused-vars
function initTranslationEditor() {
  _bindTransEvents();
  // (LLM 모델 목록은 workspace.js의 _loadAllLlmModelSelects()가 일괄 로드)
  initRefDictUI();
}

function _bindTransEvents() {
  const blockSelect = document.getElementById("trans-block-select");
  if (blockSelect) {
    blockSelect.addEventListener("change", () => {
      const blockId = blockSelect.value;
      if (blockId) {
        transState.blockId = blockId;
        _loadTranslationData();
      }
    });
  }

  const saveBtn = document.getElementById("trans-save-btn");
  if (saveBtn) saveBtn.addEventListener("click", _saveAllTranslations);

  const aiAllBtn = document.getElementById("trans-ai-all-btn");
  if (aiAllBtn) aiAllBtn.addEventListener("click", _aiTranslateAll);

  // 리셋 버튼: 현재 페이지의 모든 번역 삭제
  const resetBtn = document.getElementById("trans-reset-btn");
  if (resetBtn) resetBtn.addEventListener("click", _resetAllTranslations);
}


/* ──────────────────────────
   모드 활성화/비활성화
   ────────────────────────── */

// eslint-disable-next-line no-unused-vars
function activateTranslationMode() {
  transState.active = true;
  _populateTransBlockSelect();
  if (transState.blockId) {
    _loadTranslationData();
  }
}

// eslint-disable-next-line no-unused-vars
function deactivateTranslationMode() {
  transState.active = false;
}


/* ──────────────────────────
   블록 선택 드롭다운
   ────────────────────────── */

async function _populateTransBlockSelect() {
  const select = document.getElementById("trans-block-select");
  if (!select) return;

  select.innerHTML = '<option value="">블록 선택</option>';

  if (!viewerState.docId || !viewerState.partId || !viewerState.pageNum) return;

  try {
    const res = await fetch(
      `/api/documents/${viewerState.docId}/pages/${viewerState.pageNum}/layout?part_id=${viewerState.partId}`
    );
    if (!res.ok) {
      _addTransDefaultBlock(select);
      return;
    }
    const data = await res.json();
    const blocks = data.blocks || [];

    if (blocks.length === 0) {
      _addTransDefaultBlock(select);
    } else {
      blocks.forEach((block) => {
        const opt = document.createElement("option");
        opt.value = block.block_id;
        opt.textContent = `${block.block_id} (${block.block_type || "text"})`;
        select.appendChild(opt);
      });
    }

    if (transState.blockId) {
      select.value = transState.blockId;
    } else if (select.options.length > 1) {
      select.selectedIndex = 1;
      transState.blockId = select.value;
      _loadTranslationData();
    }
  } catch {
    _addTransDefaultBlock(select);
  }
}

function _addTransDefaultBlock(select) {
  const opt = document.createElement("option");
  opt.value = `p${String(viewerState.pageNum).padStart(2, "0")}_b01`;
  opt.textContent = `p${String(viewerState.pageNum).padStart(2, "0")}_b01 (기본)`;
  select.appendChild(opt);
}


/* ──────────────────────────
   데이터 로드
   ────────────────────────── */

async function _loadTranslationData() {
  if (!interpState.interpId || !viewerState.pageNum || !transState.blockId) {
    _renderTransCards();
    return;
  }

  try {
    // 원문 + 표점 + 현토 + 번역을 병렬 로드
    const [textRes, punctRes, htRes, transRes] = await Promise.all([
      fetch(`/api/documents/${viewerState.docId}/pages/${viewerState.pageNum}/text?part_id=${viewerState.partId}`),
      fetch(`/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/punctuation?block_id=${transState.blockId}`),
      fetch(`/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/hyeonto?block_id=${transState.blockId}`),
      fetch(`/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/translation`),
    ]);

    if (textRes.ok) {
      const textData = await textRes.json();
      transState.originalText = textData.text || "";
    } else {
      transState.originalText = "";
    }

    if (punctRes.ok) {
      const punctData = await punctRes.json();
      transState.punctMarks = punctData.marks || [];
    } else {
      transState.punctMarks = [];
    }

    if (htRes.ok) {
      const htData = await htRes.json();
      transState.htAnnotations = htData.annotations || [];
    } else {
      transState.htAnnotations = [];
    }

    if (transRes.ok) {
      const transData = await transRes.json();
      transState.translations = transData.translations || [];
    } else {
      transState.translations = [];
    }

    // 문장 분리 (클라이언트 사이드)
    transState.sentences = _splitSentencesClient(
      transState.originalText, transState.punctMarks
    );

    transState.isDirty = false;
    _renderSourceText();
    _renderTransCards();
    _renderStatusSummary();
  } catch (e) {
    console.error("번역 데이터 로드 실패:", e);
  }
}


/* ──────────────────────────
   문장 분리 (클라이언트 사이드)
   ────────────────────────── */

/**
 * 서버의 split_sentences와 동일한 알고리즘.
 * 표점의 after에 。？！이 있으면 그 위치에서 문장을 나눈다.
 */
function _splitSentencesClient(text, marks) {
  if (!text) return [];

  const enders = new Set(["。", "？", "！"]);
  const enderPositions = new Set();

  for (const mark of marks) {
    const after = mark.after || "";
    for (const ch of after) {
      if (enders.has(ch)) {
        const end = mark.target?.end ?? -1;
        if (end >= 0 && end < text.length) {
          enderPositions.add(end);
        }
        break;
      }
    }
  }

  const sentences = [];
  let start = 0;

  for (let i = 0; i < text.length; i++) {
    if (enderPositions.has(i)) {
      sentences.push({ start, end: i, text: text.substring(start, i + 1) });
      start = i + 1;
    }
  }

  if (start < text.length) {
    sentences.push({ start, end: text.length - 1, text: text.substring(start) });
  }

  return sentences;
}


/* ──────────────────────────
   원문 미리보기
   ────────────────────────── */

function _renderSourceText() {
  const el = document.getElementById("trans-source-text");
  if (!el) return;

  const text = transState.originalText;
  if (!text) {
    el.textContent = "";
    return;
  }

  const n = text.length;
  const beforeBuf = new Array(n).fill("");
  const afterBuf = new Array(n).fill("");

  // 표점 적용
  for (const mark of transState.punctMarks) {
    const start = mark.target?.start ?? 0;
    const end = mark.target?.end ?? start;
    if (start < 0 || end >= n || start > end) continue;
    if (mark.before) beforeBuf[start] += mark.before;
    if (mark.after) afterBuf[end] += mark.after;
  }

  // 현토 적용
  for (const ann of transState.htAnnotations) {
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

  el.textContent = result;
}


/* ──────────────────────────
   번역 카드 렌더링
   ────────────────────────── */

function _renderTransCards() {
  const container = document.getElementById("trans-cards");
  if (!container) return;

  if (!transState.originalText || transState.sentences.length === 0) {
    container.innerHTML = '<div class="placeholder">번역 모드: 블록을 선택하면 문장별 번역이 표시됩니다</div>';
    return;
  }

  let html = "";
  for (let i = 0; i < transState.sentences.length; i++) {
    const sent = transState.sentences[i];
    // 이 문장에 대응하는 번역 찾기
    const tr = _findTranslation(sent);

    const statusClass = tr ? `trans-status-${tr.status}` : "trans-status-none";
    const statusLabel = tr
      ? (tr.status === "draft" ? "초안" : tr.status === "accepted" ? "확정" : tr.status)
      : "미번역";
    const translatorLabel = tr && tr.translator
      ? (tr.translator.type === "llm" ? `AI (${tr.translator.model || "?"})` : "수동")
      : "";

    html += `<div class="trans-card ${statusClass}" data-sent-idx="${i}">
      <div class="trans-card-header">
        <span class="trans-card-source">${sent.text}</span>
        <span class="trans-card-status-badge">${statusLabel}</span>
      </div>`;

    if (tr) {
      html += `<div class="trans-card-body">
        <textarea class="trans-card-textarea" data-tr-id="${tr.id}" rows="2">${tr.translation}</textarea>
        <div class="trans-card-actions">
          <span class="trans-card-translator">${translatorLabel}</span>
          <div class="trans-card-btns">`;

      if (tr.status === "draft") {
        html += `<button class="text-btn text-btn-small trans-accept-btn" data-tr-id="${tr.id}">확정</button>`;
      }

      html += `<button class="text-btn text-btn-small trans-del-btn" data-tr-id="${tr.id}">삭제</button>
          </div>
        </div>
      </div>`;
    } else {
      html += `<div class="trans-card-body trans-card-empty">
        <button class="text-btn text-btn-small trans-manual-btn" data-sent-idx="${i}">수동 입력</button>
        <button class="text-btn text-btn-small trans-ai-btn" data-sent-idx="${i}">AI 번역</button>
      </div>`;
    }

    html += `</div>`;
  }

  container.innerHTML = html;

  // 이벤트 바인딩
  container.querySelectorAll(".trans-accept-btn").forEach((btn) => {
    btn.addEventListener("click", () => _acceptTranslation(btn.dataset.trId));
  });
  container.querySelectorAll(".trans-del-btn").forEach((btn) => {
    btn.addEventListener("click", () => _deleteTranslation(btn.dataset.trId));
  });
  container.querySelectorAll(".trans-manual-btn").forEach((btn) => {
    btn.addEventListener("click", () => _manualInput(parseInt(btn.dataset.sentIdx, 10)));
  });
  container.querySelectorAll(".trans-ai-btn").forEach((btn) => {
    btn.addEventListener("click", () => _aiTranslateSingle(parseInt(btn.dataset.sentIdx, 10)));
  });
  container.querySelectorAll(".trans-card-textarea").forEach((ta) => {
    ta.addEventListener("input", () => { transState.isDirty = true; });
  });
}


/**
 * 문장에 대응하는 번역을 찾는다.
 * source.block_id + start/end로 매칭.
 */
function _findTranslation(sent) {
  return transState.translations.find((tr) => {
    const src = tr.source || {};
    return src.block_id === transState.blockId &&
      src.start === sent.start &&
      src.end === sent.end;
  }) || null;
}


/* ──────────────────────────
   상태 요약
   ────────────────────────── */

function _renderStatusSummary() {
  const el = document.getElementById("trans-status-summary");
  if (!el) return;

  const total = transState.sentences.length;
  let draft = 0, accepted = 0, none = 0;

  for (const sent of transState.sentences) {
    const tr = _findTranslation(sent);
    if (!tr) none++;
    else if (tr.status === "draft") draft++;
    else if (tr.status === "accepted") accepted++;
  }

  el.textContent = `전체 ${total} / 확정 ${accepted} / 초안 ${draft} / 미번역 ${none}`;
}


/* ──────────────────────────
   수동 입력
   ────────────────────────── */

function _manualInput(sentIdx) {
  const sent = transState.sentences[sentIdx];
  if (!sent) return;

  const text = prompt(`"${sent.text}" 번역을 입력하세요:`);
  if (!text || !text.trim()) return;

  // API 호출: 수동 번역 추가
  _addManualTranslation(sent, text.trim());
}

async function _addManualTranslation(sent, translationText) {
  if (!interpState.interpId || !viewerState.pageNum) return;

  try {
    const res = await fetch(
      `/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/translation`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: {
            block_id: transState.blockId,
            start: sent.start,
            end: sent.end,
          },
          source_text: sent.text,
          translation: translationText,
          target_language: "ko",
        }),
      }
    );

    if (res.ok) {
      const result = await res.json();
      transState.translations.push(result);
      _renderTransCards();
      _renderStatusSummary();
    } else {
      const err = await res.json();
      showToast(`번역 추가 실패: ${err.error || "알 수 없는 오류"}`, 'error');
    }
  } catch (e) {
    showToast(`번역 추가 실패: ${e.message}`, 'error');
  }
}


/* ──────────────────────────
   확정 / 삭제
   ────────────────────────── */

async function _acceptTranslation(trId) {
  if (!interpState.interpId || !viewerState.pageNum) return;

  // 텍스트 영역에서 수정된 값 가져오기
  const ta = document.querySelector(`.trans-card-textarea[data-tr-id="${trId}"]`);
  const modifications = ta ? { translation: ta.value.trim() } : null;

  try {
    const res = await fetch(
      `/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/translation/${trId}/commit`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ modifications }),
      }
    );

    if (res.ok) {
      const result = await res.json();
      // 로컬 상태 업데이트
      const idx = transState.translations.findIndex((t) => t.id === trId);
      if (idx >= 0) transState.translations[idx] = result;
      _renderTransCards();
      _renderStatusSummary();
    }
  } catch (e) {
    showToast(`확정 실패: ${e.message}`, 'error');
  }
}

async function _deleteTranslation(trId) {
  if (!confirm("이 번역을 삭제하시겠습니까?")) return;
  if (!interpState.interpId || !viewerState.pageNum) return;

  try {
    const res = await fetch(
      `/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/translation/${trId}`,
      { method: "DELETE" }
    );

    if (res.ok || res.status === 204) {
      transState.translations = transState.translations.filter((t) => t.id !== trId);
      _renderTransCards();
      _renderStatusSummary();
    }
  } catch (e) {
    showToast(`삭제 실패: ${e.message}`, 'error');
  }
}


/* ──────────────────────────
   AI 번역 (단일 / 전체)
   ────────────────────────── */

async function _aiTranslateSingle(sentIdx) {
  const sent = transState.sentences[sentIdx];
  if (!sent) return;

  // 이미 번역이 있으면 덮어쓸지 확인
  const existing = _findTranslation(sent);
  if (existing && !confirm("기존 번역이 있습니다. AI 번역으로 덮어쓰시겠습니까?")) return;

  // 버튼 비활성화
  const btns = document.querySelectorAll(".trans-ai-btn");
  btns.forEach((b) => { b.disabled = true; b.textContent = "번역 중..."; });

  try {
    // LLM 프로바이더/모델 선택 반영
    const llmSel = typeof getLlmModelSelection === "function"
      ? getLlmModelSelection("trans-llm-model-select")
      : { force_provider: null, force_model: null };

    const reqBody = { text: sent.text };
    if (llmSel.force_provider) reqBody.force_provider = llmSel.force_provider;
    if (llmSel.force_model) reqBody.force_model = llmSel.force_model;

    const resp = await fetch("/api/llm/translation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reqBody),
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.error || `HTTP ${resp.status}`);
    }

    const data = await resp.json();
    const translationText = data.translation || "";
    if (!translationText) throw new Error("AI 응답에 번역이 없습니다.");

    // 기존 번역 업데이트 또는 새로 추가
    if (existing) {
      const res = await fetch(
        `/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/translation/${existing.id}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ translation: translationText }),
        }
      );
      if (res.ok) {
        const updated = await res.json();
        Object.assign(existing, updated);
      }
    } else {
      await _addManualTranslation(sent, translationText);
    }

    _renderTransCards();
    _renderStatusSummary();
  } catch (e) {
    showToast(`AI 번역 실패: ${e.message}`, 'error');
  } finally {
    btns.forEach((b) => { b.disabled = false; b.textContent = "AI"; });
  }
}

async function _aiTranslateAll() {
  if (!transState.sentences || transState.sentences.length === 0) {
    showToast("번역할 문장이 없습니다.", 'warning');
    return;
  }

  // 미번역 문장만 대상
  const targets = [];
  for (let i = 0; i < transState.sentences.length; i++) {
    if (!_findTranslation(transState.sentences[i])) {
      targets.push(i);
    }
  }

  if (targets.length === 0) {
    showToast("모든 문장이 이미 번역되어 있습니다.", 'info');
    return;
  }

  if (!confirm(`미번역 ${targets.length}개 문장을 AI로 번역합니다. 계속하시겠습니까?`)) return;

  const allBtn = document.getElementById("trans-ai-all-btn");
  if (allBtn) { allBtn.disabled = true; allBtn.textContent = "번역 중..."; }

  let success = 0;
  let fail = 0;

  for (const idx of targets) {
    try {
      await _aiTranslateSingle(idx);
      success++;
    } catch {
      fail++;
    }
  }

  if (allBtn) { allBtn.disabled = false; allBtn.textContent = "전체 AI 번역"; }
  showToast(`AI 번역 완료: 성공 ${success}건, 실패 ${fail}건`, 'success');
}


/* ──────────────────────────
   전체 저장
   ────────────────────────── */

async function _saveAllTranslations() {
  if (!interpState.interpId || !viewerState.pageNum) {
    showToast("해석 저장소가 선택되어야 합니다.", 'warning');
    return;
  }

  const statusEl = document.getElementById("trans-save-status");
  if (statusEl) statusEl.textContent = "저장 중...";

  // 텍스트 영역에서 수정된 값 반영
  document.querySelectorAll(".trans-card-textarea").forEach((ta) => {
    const trId = ta.dataset.trId;
    const tr = transState.translations.find((t) => t.id === trId);
    if (tr) tr.translation = ta.value.trim();
  });

  // 각 번역을 개별 PUT으로 업데이트
  let success = 0;
  for (const tr of transState.translations) {
    try {
      const res = await fetch(
        `/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/translation/${tr.id}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            translation: tr.translation,
            status: tr.status,
          }),
        }
      );
      if (res.ok) success++;
    } catch {
      // 개별 실패는 무시
    }
  }

  transState.isDirty = false;
  if (statusEl) {
    statusEl.textContent = `${success}건 저장 완료`;
    setTimeout(() => { statusEl.textContent = ""; }, 2000);
  }
}


/* ──────────────────────────────────
   전체 리셋: 현재 페이지의 모든 번역 삭제
   ────────────────────────────────── */

/**
 * 현재 페이지의 모든 번역을 삭제한다.
 *
 * 왜 이렇게 하는가: 페이지 단위로 번역을 처음부터 다시 하고 싶을 때,
 *   개별 삭제를 반복하는 대신 한 번에 모두 삭제할 수 있다.
 *   삭제 전 confirm()으로 사용자 확인을 받아 실수를 방지한다.
 */
async function _resetAllTranslations() {
  if (!interpState.interpId || !viewerState.pageNum) {
    showToast("해석 저장소와 페이지가 선택되어야 합니다.", 'warning');
    return;
  }

  if (transState.translations.length === 0) {
    showToast("삭제할 번역이 없습니다.", 'warning');
    return;
  }

  if (!confirm(
    `현재 페이지의 번역 ${transState.translations.length}건을 모두 삭제합니다.\n이 작업은 되돌릴 수 없습니다. 계속하시겠습니까?`
  )) return;

  let success = 0;
  let fail = 0;

  // 번역 ID 목록을 미리 복사 (삭제 중 배열 변경 방지)
  const ids = transState.translations.map(t => t.id);

  for (const trId of ids) {
    try {
      const res = await fetch(
        `/api/interpretations/${interpState.interpId}/pages/${viewerState.pageNum}/translation/${trId}`,
        { method: "DELETE" }
      );
      if (res.ok || res.status === 204) {
        success++;
      } else {
        fail++;
      }
    } catch {
      fail++;
    }
  }

  // 로컬 상태 초기화
  transState.translations = [];
  transState.isDirty = false;
  _renderTransCards();
  _renderStatusSummary();

  if (fail > 0) {
    showToast(`번역 리셋 완료: 성공 ${success}건, 실패 ${fail}건`, 'error');
  }
}


/* ────────────────────────────────────
   참조 사전 매칭 (Reference Dictionary)
   ──────────────────────────────────── */

/**
 * 참조 사전 상태.
 */
const refDictState = {
  enabled: false,       // 참조 사전 사용 토글
  matches: [],          // 매칭 결과
  selectedHeadwords: new Set(), // 사용자가 선택한 headword
};


function initRefDictUI() {
  /* 참조 사전 UI 초기화. initTranslationEditor() 이후 호출. */
  const toggleBtn = document.getElementById("trans-refdict-toggle");
  if (toggleBtn) toggleBtn.addEventListener("click", _toggleRefDict);

  const applyBtn = document.getElementById("trans-refdict-apply-btn");
  if (applyBtn) applyBtn.addEventListener("click", _applyRefDictSelection);

  const selectAllBtn = document.getElementById("trans-refdict-select-all-btn");
  if (selectAllBtn) selectAllBtn.addEventListener("click", _selectAllRefDict);

  const manageDictsBtn = document.getElementById("trans-refdict-manage-btn");
  if (manageDictsBtn) manageDictsBtn.addEventListener("click", _showRefDictManager);
}


function _toggleRefDict() {
  refDictState.enabled = !refDictState.enabled;
  const btn = document.getElementById("trans-refdict-toggle");
  if (btn) {
    btn.textContent = refDictState.enabled ? "참조 사전 OFF" : "참조 사전 ON";
    btn.classList.toggle("active", refDictState.enabled);
  }

  const panel = document.getElementById("trans-refdict-panel");
  if (panel) panel.style.display = refDictState.enabled ? "" : "none";

  if (refDictState.enabled && transState.blockId) {
    _loadRefDictMatches();
  }
}


async function _loadRefDictMatches() {
  /* 현재 블록의 원문에서 참조 사전 매칭을 수행한다. */
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!is || !is.interpId) return;

  const blocks = [{ block_id: transState.blockId, text: transState.originalText }];
  if (!blocks[0].text) return;

  try {
    const resp = await fetch(`/api/interpretations/${is.interpId}/reference-dicts/match`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ blocks }),
    });

    if (!resp.ok) return;

    const data = await resp.json();
    refDictState.matches = data.matches || [];
    // 기본적으로 전체 선택
    refDictState.selectedHeadwords = new Set(
      refDictState.matches.map(m => `${m.headword}|${m.source_dict}`)
    );
    _renderRefDictMatches();
  } catch (e) {
    console.error("참조 사전 매칭 실패:", e);
  }
}


function _renderRefDictMatches() {
  /* 매칭 결과를 리스트로 표시한다. */
  const container = document.getElementById("trans-refdict-list");
  if (!container) return;

  if (refDictState.matches.length === 0) {
    container.innerHTML = '<div class="placeholder">매칭된 항목이 없습니다.</div>';
    return;
  }

  container.innerHTML = "";
  for (const m of refDictState.matches) {
    const key = `${m.headword}|${m.source_dict}`;
    const checked = refDictState.selectedHeadwords.has(key) ? "checked" : "";
    const reading = m.headword_reading ? ` (${m.headword_reading})` : "";
    const meaning = m.dictionary_meaning || "";
    const source = m.source_document || m.source_dict || "";

    const item = document.createElement("label");
    item.className = "trans-refdict-item";
    item.innerHTML = `
      <input type="checkbox" data-key="${key}" ${checked}>
      <span class="trans-refdict-hw">${m.headword}${reading}</span>
      <span class="trans-refdict-type">[${m.type || ""}]</span>
      <span class="trans-refdict-meaning">${meaning.slice(0, 60)}${meaning.length > 60 ? "…" : ""}</span>
      <span class="trans-refdict-source">${source}</span>
    `;

    const checkbox = item.querySelector("input");
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        refDictState.selectedHeadwords.add(key);
      } else {
        refDictState.selectedHeadwords.delete(key);
      }
    });

    container.appendChild(item);
  }
}


function _selectAllRefDict() {
  const allSelected = refDictState.selectedHeadwords.size === refDictState.matches.length;
  if (allSelected) {
    refDictState.selectedHeadwords.clear();
  } else {
    for (const m of refDictState.matches) {
      refDictState.selectedHeadwords.add(`${m.headword}|${m.source_dict}`);
    }
  }
  _renderRefDictMatches();
}


function _applyRefDictSelection() {
  /* 선택된 매칭 항목을 번역 참고 텍스트로 생성하여 다음 AI 번역에 반영. */
  const selected = refDictState.matches.filter(m =>
    refDictState.selectedHeadwords.has(`${m.headword}|${m.source_dict}`)
  );

  if (selected.length === 0) {
    showToast("선택된 항목이 없습니다.", 'warning');
    return;
  }

  // 참고 텍스트 생성 (서버의 format_for_translation_context와 동일한 형식)
  let lines = ["[참고 사전]"];
  for (const m of selected) {
    let line = `- ${m.headword}`;
    if (m.headword_reading) line += `(${m.headword_reading})`;
    if (m.type) line += ` [${m.type}]`;
    line += `: ${m.dictionary_meaning || ""}`;
    if (m.contextual_meaning) line += ` / 문맥: ${m.contextual_meaning}`;
    lines.push(line);
  }

  // transState에 참조 사전 컨텍스트 저장 (AI 번역 시 사용)
  transState._refDictContext = lines.join("\n");

  const statusEl = document.getElementById("trans-save-status");
  if (statusEl) {
    statusEl.textContent = `참조 사전 ${selected.length}개 항목 적용`;
    setTimeout(() => { statusEl.textContent = ""; }, 2000);
  }
}


async function _showRefDictManager() {
  /* 참조 사전 관리 다이얼로그: 목록 조회 + 등록 + 삭제. */
  const is = typeof interpState !== "undefined" ? interpState : null;
  if (!is || !is.interpId) return;

  try {
    const resp = await fetch(`/api/interpretations/${is.interpId}/reference-dicts`);
    if (!resp.ok) return;
    const data = await resp.json();
    const dicts = data.reference_dicts || [];

    let msg = "등록된 참조 사전:\n";
    if (dicts.length === 0) {
      msg += "(없음)\n";
    } else {
      for (const d of dicts) {
        msg += `  - ${d.filename} (${d.source_document_title}, ${d.total_entries}개 항목)\n`;
      }
    }
    msg += "\n새 사전을 등록하려면 '등록'을, 기존 사전을 삭제하려면 '삭제'를 입력하세요.\n(취소하려면 빈칸)";

    const action = prompt(msg);
    if (!action) return;

    if (action === "등록") {
      // 파일 선택으로 등록
      const input = document.createElement("input");
      input.type = "file";
      input.accept = ".json";
      input.addEventListener("change", async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const text = await file.text();
        const dictData = JSON.parse(text);

        const regResp = await fetch(`/api/interpretations/${is.interpId}/reference-dicts`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dictionary_data: dictData }),
        });
        if (regResp.ok) {
          const result = await regResp.json();
          showToast(`참조 사전 등록 완료: ${result.filename}`, 'success');
        }
      });
      input.click();
    } else if (action === "삭제") {
      const filename = prompt("삭제할 파일명:");
      if (!filename) return;

      const delResp = await fetch(`/api/interpretations/${is.interpId}/reference-dicts/${filename}`, {
        method: "DELETE",
      });
      if (delResp.ok || delResp.status === 204) {
        showToast("참조 사전 삭제 완료", 'success');
      }
    }
  } catch (e) {
    console.error("참조 사전 관리 실패:", e);
  }
}
