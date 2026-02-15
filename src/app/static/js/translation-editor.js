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
      alert(`번역 추가 실패: ${err.error || "알 수 없는 오류"}`);
    }
  } catch (e) {
    alert(`번역 추가 실패: ${e.message}`);
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
    alert(`확정 실패: ${e.message}`);
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
    alert(`삭제 실패: ${e.message}`);
  }
}


/* ──────────────────────────
   AI 번역 (단일 / 전체)
   ────────────────────────── */

function _aiTranslateSingle(sentIdx) {
  alert("AI 번역 기능은 LLM 연결 후 사용 가능합니다.\n[수동 입력]을 이용하세요.");
}

function _aiTranslateAll() {
  alert("전체 AI 번역 기능은 LLM 연결 후 사용 가능합니다.\n[수동 입력]을 이용하세요.");
}


/* ──────────────────────────
   전체 저장
   ────────────────────────── */

async function _saveAllTranslations() {
  if (!interpState.interpId || !viewerState.pageNum) {
    alert("해석 저장소가 선택되어야 합니다.");
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
