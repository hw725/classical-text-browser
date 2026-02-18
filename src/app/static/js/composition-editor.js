/**
 * 편성 에디터 — LayoutBlock → TextBlock 변환
 *
 * 기능:
 *   1. 교정된 텍스트를 블록별로 표시 (교정 적용 후)
 *   2. 각 LayoutBlock을 1:1로 TextBlock 자동 생성 ("자동 편성")
 *   3. 여러 LayoutBlock을 합쳐서 하나의 TextBlock 생성 ("합치기")
 *   4. 이미 생성된 TextBlock 목록 표시
 *
 * 의존성:
 *   - sidebar-tree.js (viewerState)
 *   - interpretation.js (interpState)
 *
 * 왜 이렇게 하는가:
 *   교정은 LayoutBlock(물리적 단위) 기반이지만,
 *   표점·현토·번역은 TextBlock(논리적 단위) 기반이다.
 *   이 편성 단계에서 연구자가 LayoutBlock을 TextBlock으로
 *   재편성(합치기·쪼개기)하여 후속 작업의 기본 단위를 정한다.
 */


/* ──────────────────────────
   상태 객체
   ────────────────────────── */

const compState = {
  active: false,           // 편성 모드 활성화 여부
  sourceBlocks: [],        // 교정된 LayoutBlock 목록 [{block_id, block_type, original_text, corrected_text, ...}]
  textBlocks: [],          // 이미 생성된 TextBlock 목록
  selectedBlockIds: [],    // 합치기를 위해 선택된 LayoutBlock ID 목록
  workId: null,            // 현재 Work UUID (TextBlock 생성에 필요)
};


/* ──────────────────────────
   초기화
   ────────────────────────── */

/**
 * 편성 에디터를 초기화한다.
 * DOMContentLoaded에서 workspace.js가 호출한다.
 */
// eslint-disable-next-line no-unused-vars
function initCompositionEditor() {
  _bindCompEvents();
}


/**
 * 이벤트 바인딩.
 */
function _bindCompEvents() {
  const autoBtn = document.getElementById("comp-auto-btn");
  const mergeBtn = document.getElementById("comp-merge-btn");

  if (autoBtn) autoBtn.addEventListener("click", _autoCompose);
  if (mergeBtn) mergeBtn.addEventListener("click", _mergeSelectedBlocks);
}


/* ──────────────────────────
   모드 활성화 / 비활성화
   ────────────────────────── */

/**
 * 편성 모드를 활성화한다.
 */
// eslint-disable-next-line no-unused-vars
function activateCompositionMode() {
  compState.active = true;
  _loadCompositionData();
}


/**
 * 편성 모드를 비활성화한다.
 */
// eslint-disable-next-line no-unused-vars
function deactivateCompositionMode() {
  compState.active = false;
  compState.selectedBlockIds = [];
}


/* ──────────────────────────
   데이터 로드
   ────────────────────────── */

/**
 * 교정된 텍스트 + 기존 TextBlock을 로드한다.
 *
 * 왜 이렇게 하는가:
 *   편성 화면은 두 영역으로 나뉜다:
 *   (1) 위: 교정된 LayoutBlock 텍스트 (소스)
 *   (2) 아래: 이미 생성된 TextBlock (결과)
 */
async function _loadCompositionData() {
  const { docId, partId, pageNum } = viewerState;
  if (!docId || !partId || !pageNum) {
    _renderSourceBlocks();
    _renderTextBlocks();
    return;
  }

  // 교정된 텍스트 + TextBlock을 병렬 로드
  const promises = [
    fetch(`/api/documents/${docId}/pages/${pageNum}/corrected-text?part_id=${partId}`)
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null),
  ];

  // 해석 저장소가 선택되어 있으면 TextBlock도 로드
  if (interpState.interpId) {
    promises.push(
      fetch(`/api/interpretations/${interpState.interpId}/entities/text_block?page=${pageNum}&document_id=${docId}`)
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null)
    );
    // Work 자동 확보
    promises.push(_ensureWork());
  }

  const results = await Promise.all(promises);

  // 교정된 텍스트
  const correctedData = results[0];
  if (correctedData) {
    compState.sourceBlocks = correctedData.blocks || [];
  } else {
    compState.sourceBlocks = [];
  }

  // TextBlock 목록
  const tbData = results[1];
  if (tbData && tbData.entities) {
    // 현재 페이지에 해당하는 TextBlock만 필터
    compState.textBlocks = tbData.entities.filter((e) => {
      const refs = e.source_refs || [];
      const ref = e.source_ref;
      // source_refs가 있으면 그 중에 현재 페이지가 포함된 것
      if (refs.length > 0) {
        return refs.some((r) => r.page === pageNum && r.document_id === docId);
      }
      // 하위 호환: source_ref로 필터
      if (ref) {
        return ref.page === pageNum && ref.document_id === docId;
      }
      return false;
    });
  } else {
    compState.textBlocks = [];
  }

  compState.selectedBlockIds = [];
  _renderSourceBlocks();
  _renderTextBlocks();
  _updateBlockCount();
}


/**
 * Work를 자동 확보한다 (없으면 생성).
 *
 * 왜 이렇게 하는가:
 *   TextBlock을 만들려면 소속 Work가 필요하다.
 *   편성 탭을 열 때 자동으로 Work를 확보하여
 *   연구자가 별도 작업 없이 바로 편성할 수 있게 한다.
 */
async function _ensureWork() {
  if (compState.workId) return;

  try {
    // 기존 Work 목록 확인
    const listRes = await fetch(
      `/api/interpretations/${interpState.interpId}/entities/work`
    );
    if (listRes.ok) {
      const data = await listRes.json();
      const works = data.entities || [];
      // 현재 문헌에 해당하는 Work 찾기
      const match = works.find(
        (w) => w.metadata && w.metadata.document_id === viewerState.docId
      );
      if (match) {
        compState.workId = match.id;
        return;
      }
      // 아무 Work나 있으면 사용
      if (works.length > 0) {
        compState.workId = works[0].id;
        return;
      }
    }

    // Work 자동 생성
    const createRes = await fetch(
      `/api/interpretations/${interpState.interpId}/entities/work/auto-create`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_id: viewerState.docId }),
      }
    );
    if (createRes.ok) {
      const result = await createRes.json();
      compState.workId = result.work?.id || null;
    }
  } catch (e) {
    console.error("Work 확보 실패:", e);
  }
}


/* ──────────────────────────
   렌더링: 소스 블록 (교정된 LayoutBlock)
   ────────────────────────── */

/**
 * 교정된 LayoutBlock 목록을 렌더링한다.
 *
 * 왜 이렇게 하는가:
 *   연구자가 각 블록의 교정된 텍스트를 확인하고,
 *   체크박스로 합칠 블록을 선택할 수 있게 한다.
 */
function _renderSourceBlocks() {
  const container = document.getElementById("comp-source-blocks");
  if (!container) return;

  if (compState.sourceBlocks.length === 0) {
    container.innerHTML =
      '<div class="placeholder" style="padding:20px; text-align:center; color:var(--text-muted);">' +
      "이 페이지에 교정된 텍스트가 없습니다.</div>";
    return;
  }

  container.innerHTML = "";

  compState.sourceBlocks.forEach((block) => {
    const card = document.createElement("div");
    card.className = "comp-source-card";
    card.dataset.blockId = block.block_id;

    // 이미 TextBlock으로 편성된 블록인지 확인
    const alreadyComposed = compState.textBlocks.some((tb) => {
      const refs = tb.source_refs || [];
      return refs.some((r) => r.layout_block_id === block.block_id);
    });

    const isSelected = compState.selectedBlockIds.includes(block.block_id);

    card.style.cssText = `
      border: 1px solid ${alreadyComposed ? "var(--accent-green, #22c55e)" : isSelected ? "var(--accent-primary, #3b82f6)" : "var(--border)"};
      border-radius: 4px;
      padding: 8px;
      cursor: pointer;
      background: ${alreadyComposed ? "rgba(34,197,94,0.05)" : isSelected ? "rgba(59,130,246,0.08)" : "var(--bg-secondary)"};
      transition: border-color 0.15s;
    `;

    // 헤더: 체크박스 + 블록 ID + 상태 뱃지
    const header = document.createElement("div");
    header.style.cssText = "display:flex; align-items:center; gap:6px; margin-bottom:4px;";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = isSelected;
    checkbox.disabled = alreadyComposed;
    checkbox.style.cssText = "margin:0;";
    checkbox.addEventListener("change", () => {
      _toggleBlockSelection(block.block_id, checkbox.checked);
    });

    const label = document.createElement("span");
    label.style.cssText = "font-size:11px; font-weight:600; font-family:monospace;";
    label.textContent = block.block_id;

    const typeBadge = document.createElement("span");
    typeBadge.style.cssText = "font-size:10px; color:var(--text-muted); background:var(--bg-tertiary, #f0f0f0); padding:1px 4px; border-radius:2px;";
    typeBadge.textContent = block.block_type || "text";

    header.appendChild(checkbox);
    header.appendChild(label);
    header.appendChild(typeBadge);

    if (alreadyComposed) {
      const doneBadge = document.createElement("span");
      doneBadge.style.cssText = "font-size:10px; color:var(--accent-green, #22c55e); margin-left:auto;";
      doneBadge.textContent = "편성됨";
      header.appendChild(doneBadge);
    }

    if (block.corrections_applied > 0) {
      const corrBadge = document.createElement("span");
      corrBadge.style.cssText = "font-size:10px; color:var(--accent-warning, #f59e0b); margin-left:auto;";
      corrBadge.textContent = `교정 ${block.corrections_applied}건`;
      header.appendChild(corrBadge);
    }

    // 텍스트 미리보기
    const preview = document.createElement("div");
    preview.style.cssText = "font-size:12px; line-height:1.6; white-space:pre-wrap; max-height:80px; overflow:hidden; color:var(--text-primary);";
    const displayText = block.corrected_text || block.original_text || "";
    preview.textContent = displayText.length > 200 ? displayText.substring(0, 200) + "..." : displayText;

    card.appendChild(header);
    card.appendChild(preview);
    container.appendChild(card);

    // 카드 클릭으로도 선택 토글 (체크박스 외 영역)
    card.addEventListener("click", (e) => {
      if (e.target === checkbox || alreadyComposed) return;
      checkbox.checked = !checkbox.checked;
      _toggleBlockSelection(block.block_id, checkbox.checked);
    });
  });
}


/**
 * 블록 선택 토글.
 */
function _toggleBlockSelection(blockId, selected) {
  if (selected) {
    if (!compState.selectedBlockIds.includes(blockId)) {
      compState.selectedBlockIds.push(blockId);
    }
  } else {
    compState.selectedBlockIds = compState.selectedBlockIds.filter(
      (id) => id !== blockId
    );
  }
  _renderSourceBlocks();
}


/* ──────────────────────────
   렌더링: TextBlock 목록
   ────────────────────────── */

/**
 * 이미 생성된 TextBlock 목록을 렌더링한다.
 */
function _renderTextBlocks() {
  const container = document.getElementById("comp-textblock-list");
  if (!container) return;

  if (!interpState.interpId) {
    container.innerHTML =
      '<div class="placeholder" style="padding:20px; text-align:center; color:var(--text-muted);">' +
      "해석 저장소를 먼저 선택하세요 (해석 탭에서 생성/선택)</div>";
    return;
  }

  if (compState.textBlocks.length === 0) {
    container.innerHTML =
      '<div class="placeholder" style="padding:20px; text-align:center; color:var(--text-muted);">' +
      '아직 TextBlock이 없습니다. "자동 편성" 또는 "합치기"를 사용하세요.</div>';
    return;
  }

  container.innerHTML = "";

  // sequence_index 순으로 정렬
  const sorted = [...compState.textBlocks].sort(
    (a, b) => (a.sequence_index || 0) - (b.sequence_index || 0)
  );

  sorted.forEach((tb) => {
    const card = document.createElement("div");
    card.style.cssText = `
      border: 1px solid var(--accent-green, #22c55e);
      border-radius: 4px;
      padding: 8px;
      background: rgba(34,197,94,0.03);
    `;

    // 헤더: seq# + source 요약
    const header = document.createElement("div");
    header.style.cssText = "display:flex; align-items:center; gap:6px; margin-bottom:4px;";

    const seqBadge = document.createElement("span");
    seqBadge.style.cssText = "font-size:10px; font-weight:700; color:var(--accent-green, #22c55e); background:rgba(34,197,94,0.1); padding:1px 5px; border-radius:2px;";
    seqBadge.textContent = `#${tb.sequence_index}`;

    const sourceInfo = document.createElement("span");
    sourceInfo.style.cssText = "font-size:10px; color:var(--text-muted); font-family:monospace;";
    const refs = tb.source_refs || [];
    if (refs.length > 0) {
      sourceInfo.textContent = refs.map((r) => r.layout_block_id || "?").join(" + ");
    } else if (tb.source_ref) {
      sourceInfo.textContent = tb.source_ref.layout_block_id || "?";
    }

    const statusBadge = document.createElement("span");
    statusBadge.style.cssText = "font-size:10px; color:var(--text-muted); margin-left:auto;";
    statusBadge.textContent = tb.status || "draft";

    header.appendChild(seqBadge);
    header.appendChild(sourceInfo);
    header.appendChild(statusBadge);

    // 텍스트 미리보기
    const preview = document.createElement("div");
    preview.style.cssText = "font-size:12px; line-height:1.6; white-space:pre-wrap; max-height:60px; overflow:hidden; color:var(--text-primary);";
    const text = tb.original_text || "";
    preview.textContent = text.length > 150 ? text.substring(0, 150) + "..." : text;

    card.appendChild(header);
    card.appendChild(preview);
    container.appendChild(card);
  });
}


/**
 * 블록 카운트 표시 업데이트.
 */
function _updateBlockCount() {
  const el = document.getElementById("comp-block-count");
  if (el) {
    el.textContent = `소스 ${compState.sourceBlocks.length}개 / TextBlock ${compState.textBlocks.length}개`;
  }
}


/**
 * 저장 상태 표시.
 */
function _updateCompStatus(text, isError) {
  const el = document.getElementById("comp-save-status");
  if (el) {
    el.textContent = text;
    el.style.color = isError ? "var(--accent-error, #ef4444)" : "var(--accent-green, #22c55e)";
  }
}


/* ──────────────────────────
   편성 액션: 자동 편성
   ────────────────────────── */

/**
 * 모든 LayoutBlock을 1:1로 TextBlock으로 자동 생성한다.
 *
 * 왜 이렇게 하는가:
 *   대부분의 경우 LayoutBlock과 TextBlock이 1:1 대응한다.
 *   "자동 편성" 버튼 하나로 빠르게 편성을 완료할 수 있게 한다.
 *   이미 편성된 블록은 건너뛴다.
 */
async function _autoCompose() {
  if (!interpState.interpId) {
    alert("해석 저장소를 먼저 선택하세요 (해석 탭에서 생성/선택).");
    return;
  }
  if (!compState.workId) {
    alert("Work를 생성할 수 없습니다. 해석 탭을 먼저 확인하세요.");
    return;
  }
  if (compState.sourceBlocks.length === 0) {
    alert("편성할 소스 블록이 없습니다.");
    return;
  }

  // 이미 편성된 블록 ID 수집
  const composedBlockIds = new Set();
  compState.textBlocks.forEach((tb) => {
    const refs = tb.source_refs || [];
    refs.forEach((r) => {
      if (r.layout_block_id) composedBlockIds.add(r.layout_block_id);
    });
    if (tb.source_ref && tb.source_ref.layout_block_id) {
      composedBlockIds.add(tb.source_ref.layout_block_id);
    }
  });

  // 편성 안 된 블록만 처리
  const toCompose = compState.sourceBlocks.filter(
    (b) => !composedBlockIds.has(b.block_id)
  );

  if (toCompose.length === 0) {
    _updateCompStatus("모든 블록이 이미 편성됨", false);
    return;
  }

  _updateCompStatus(`편성 중... (${toCompose.length}개)`, false);

  let created = 0;
  const baseSeq = compState.textBlocks.length;

  for (let i = 0; i < toCompose.length; i++) {
    const block = toCompose[i];
    const text = block.corrected_text || block.original_text || "";
    if (!text.trim()) continue;

    try {
      const res = await fetch(
        `/api/interpretations/${interpState.interpId}/entities/text_block/compose`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            work_id: compState.workId,
            sequence_index: baseSeq + i,
            original_text: text,
            part_id: viewerState.partId,
            source_refs: [
              {
                document_id: viewerState.docId,
                page: viewerState.pageNum,
                layout_block_id: block.block_id,
                char_range: null,
              },
            ],
          }),
        }
      );

      if (res.ok) {
        created++;
      } else {
        const err = await res.json().catch(() => ({}));
        console.error(`TextBlock 생성 실패 (${block.block_id}):`, err);
      }
    } catch (e) {
      console.error(`TextBlock 생성 실패 (${block.block_id}):`, e);
    }
  }

  _updateCompStatus(`${created}개 TextBlock 생성 완료`, false);

  // 데이터 새로고침
  await _loadCompositionData();
}


/* ──────────────────────────
   편성 액션: 합치기
   ────────────────────────── */

/**
 * 선택한 LayoutBlock들을 합쳐서 하나의 TextBlock을 생성한다.
 *
 * 왜 이렇게 하는가:
 *   고전 텍스트에서 문장이 여러 블록에 걸쳐 있는 경우,
 *   연구자가 해당 블록들을 선택하고 "합치기"를 누르면
 *   하나의 TextBlock으로 만들어진다.
 */
async function _mergeSelectedBlocks() {
  if (!interpState.interpId) {
    alert("해석 저장소를 먼저 선택하세요.");
    return;
  }
  if (!compState.workId) {
    alert("Work를 생성할 수 없습니다.");
    return;
  }

  const selectedIds = compState.selectedBlockIds;
  if (selectedIds.length < 2) {
    alert("합치려면 2개 이상의 블록을 선택하세요.");
    return;
  }

  // 선택된 블록의 텍스트를 순서대로 이어붙이기
  // (소스 블록 목록의 순서를 유지)
  const orderedBlocks = compState.sourceBlocks.filter((b) =>
    selectedIds.includes(b.block_id)
  );

  const mergedText = orderedBlocks
    .map((b) => b.corrected_text || b.original_text || "")
    .join("\n");

  const sourceRefs = orderedBlocks.map((b) => ({
    document_id: viewerState.docId,
    page: viewerState.pageNum,
    layout_block_id: b.block_id,
    char_range: null,
  }));

  _updateCompStatus("합치는 중...", false);

  try {
    const res = await fetch(
      `/api/interpretations/${interpState.interpId}/entities/text_block/compose`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          work_id: compState.workId,
          sequence_index: compState.textBlocks.length,
          original_text: mergedText,
          part_id: viewerState.partId,
          source_refs: sourceRefs,
        }),
      }
    );

    if (res.ok) {
      const blockIds = orderedBlocks.map((b) => b.block_id).join(" + ");
      _updateCompStatus(`합치기 완료: ${blockIds}`, false);
    } else {
      const err = await res.json().catch(() => ({}));
      _updateCompStatus(`합치기 실패: ${err.error || "알 수 없는 오류"}`, true);
    }
  } catch (e) {
    _updateCompStatus(`합치기 실패: ${e.message}`, true);
  }

  // 데이터 새로고침
  await _loadCompositionData();
}
