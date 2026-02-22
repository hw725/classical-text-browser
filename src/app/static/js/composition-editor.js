/**
 * 편성 에디터 — LayoutBlock → TextBlock 변환
 *
 * 기능:
 *   1. 교정된 텍스트를 블록별로 표시 (교정 적용 후)
 *   2. 각 LayoutBlock을 1:1로 TextBlock 자동 생성 ("자동 편성")
 *   3. 여러 LayoutBlock을 합쳐서 하나의 TextBlock 생성 ("합치기")
 *   4. 이미 생성된 TextBlock 목록 표시
 *   5. 크로스 페이지 합치기 (시작~끝 페이지 범위)
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
 *
 *   고전 텍스트에서 문장이 페이지 경계를 넘는 경우가 흔하므로,
 *   페이지 범위(예: 2~5)를 함께 보고 합칠 수 있어야 한다.
 */

/* ──────────────────────────
   상태 객체
   ────────────────────────── */

const compState = {
  active: false, // 편성 모드 활성화 여부
  sourceBlocks: [], // 교정된 LayoutBlock 목록 [{block_id, block_type, original_text, corrected_text, _page, ...}]
  // _page: 이 블록이 소속된 페이지 번호 (크로스 페이지 지원용)
  textBlocks: [], // 이미 생성된 TextBlock 목록
  selectedBlockKeys: [], // 합치기를 위해 선택된 LayoutBlock 키 목록 ("{page}::{block_id}")
  workId: null, // 현재 Work UUID (TextBlock 생성에 필요)
  rangeStart: null, // 시작 페이지 (null이면 현재 페이지)
  rangeEnd: null, // 끝 페이지 (null이면 현재 페이지)
  selectedTbId: null, // 쪼개기를 위해 선택된 TextBlock ID
  selectedTb: null, // 쪼개기를 위해 선택된 TextBlock 객체
};

function _toBlockKey(page, blockId) {
  return `${Number(page || 0)}::${String(blockId || "")}`;
}

function _blockToKey(block, fallbackPage) {
  const page = block?._page ?? fallbackPage ?? viewerState.pageNum ?? 0;
  return _toBlockKey(page, block?.block_id);
}

function _sourceRefToKey(ref, fallbackPage) {
  if (!ref || !ref.layout_block_id) return null;
  const page = ref.page ?? fallbackPage ?? viewerState.pageNum ?? 0;
  return _toBlockKey(page, ref.layout_block_id);
}

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
  _bindCompInterpSelect();
}

/**
 * 이벤트 바인딩.
 */
function _bindCompEvents() {
  const autoBtn = document.getElementById("comp-auto-btn");
  const mergeBtn = document.getElementById("comp-merge-btn");
  const splitBtn = document.getElementById("comp-split-btn");
  const splitCancelBtn = document.getElementById("comp-split-cancel-btn");
  const splitTextarea = document.getElementById("comp-split-textarea");

  const splitExecBtn = document.getElementById("comp-split-exec-btn");
  const resetBtn = document.getElementById("comp-reset-btn");

  if (autoBtn) autoBtn.addEventListener("click", _autoCompose);
  if (mergeBtn) mergeBtn.addEventListener("click", _mergeSelectedBlocks);
  if (splitBtn) splitBtn.addEventListener("click", _executeSplit);
  if (splitExecBtn) splitExecBtn.addEventListener("click", _executeSplit);
  if (splitCancelBtn) splitCancelBtn.addEventListener("click", _cancelSplit);
  if (resetBtn) resetBtn.addEventListener("click", _resetComposition);
  // textarea 입력 시 쪼개기 미리보기 업데이트
  if (splitTextarea)
    splitTextarea.addEventListener("input", _updateSplitPreview);

  // 페이지 범위 입력 (시작~끝)
  const startInput = document.getElementById("comp-page-start");
  const endInput = document.getElementById("comp-page-end");
  const applyBtn = document.getElementById("comp-page-range-apply");

  const applyRange = () => {
    const currentPage = Number(viewerState.pageNum || 1);
    const start = Number(startInput?.value || currentPage);
    const end = Number(endInput?.value || currentPage);

    if (
      !Number.isFinite(start) ||
      !Number.isFinite(end) ||
      start < 1 ||
      end < 1
    ) {
      showToast("페이지 범위는 1 이상의 숫자로 입력해주세요.", 'warning');
      return;
    }

    compState.rangeStart = Math.floor(start);
    compState.rangeEnd = Math.floor(end);
    _loadCompositionData();
  };

  if (applyBtn) applyBtn.addEventListener("click", applyRange);
  if (startInput) {
    startInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") applyRange();
    });
  }
  if (endInput) {
    endInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") applyRange();
    });
  }
}

/* ──────────────────────────
   편성 패널 내 해석 저장소 선택 드롭다운
   ────────────────────────── */

/**
 * 편성 패널 상단의 해석 저장소 드롭다운 이벤트를 바인딩한다.
 *
 * 왜 이렇게 하는가:
 *   편성 탭에서 TextBlock을 생성하려면 해석 저장소가 필수인데,
 *   기존에는 "교차 뷰어" 모드에서만 선택할 수 있었다.
 *   편성 패널에 직접 드롭다운을 두면 모드 전환 없이 선택 가능하다.
 */
function _bindCompInterpSelect() {
  const select = document.getElementById("comp-interp-select");
  if (!select) return;

  select.addEventListener("change", () => {
    const interpId = select.value;
    if (interpId) {
      // interpretation.js의 _selectInterpretation을 직접 호출
      if (typeof _selectInterpretation === "function") {
        _selectInterpretation(interpId);
      } else {
        // fallback: 상태만 직접 설정
        interpState.interpId = interpId;
      }
    } else {
      interpState.interpId = null;
      interpState.interpInfo = null;
    }
    // 편성 데이터 다시 로드
    _loadCompositionData();
  });
}

/**
 * 편성 패널의 해석 저장소 드롭다운 옵션을 갱신한다.
 * activateCompositionMode()에서 호출된다.
 */
async function _refreshCompInterpSelect() {
  const select = document.getElementById("comp-interp-select");
  if (!select) return;

  try {
    const res = await fetch("/api/interpretations");
    if (!res.ok) return;
    const list = await res.json();

    // 기존 옵션 초기화
    select.innerHTML = '<option value="">-- 선택하세요 --</option>';

    list.forEach((item) => {
      const opt = document.createElement("option");
      opt.value = item.interpretation_id;
      const label = item.title || item.interpretation_id;
      const type = item.interpreter?.type || "human";
      opt.textContent = `[${type}] ${label}`;
      select.appendChild(opt);
    });

    // 현재 선택된 해석 저장소가 있으면 드롭다운에 반영
    if (interpState.interpId) {
      select.value = interpState.interpId;
    }
  } catch (err) {
    console.error("편성 패널 해석 저장소 목록 로드 실패:", err);
  }
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
  _refreshCompInterpSelect(); // 해석 저장소 드롭다운 갱신
  _loadCompositionData();
}

/**
 * 편성 모드를 비활성화한다.
 */
// eslint-disable-next-line no-unused-vars
function deactivateCompositionMode() {
  compState.active = false;
  compState.selectedBlockKeys = [];
}

/* ──────────────────────────
   페이지 범위 결정
   ────────────────────────── */

/**
 * 로드할 페이지 번호 목록을 반환한다.
 *
 * 왜 이렇게 하는가:
 *   고전 텍스트에서 문장이 페이지 경계를 넘는 경우가 흔하다.
 *   "이전 페이지" / "다음 페이지" 체크박스를 켜면
 *   인접 페이지의 블록도 함께 보고 합칠 수 있다.
 *
 * 출력: [start..end] 형태의 페이지 번호 배열.
 */
function _getPageRange(currentPage) {
  const rawStart = Number(compState.rangeStart ?? currentPage);
  const rawEnd = Number(compState.rangeEnd ?? currentPage);
  const start = Math.max(1, Math.floor(Math.min(rawStart, rawEnd)));
  const end = Math.max(1, Math.floor(Math.max(rawStart, rawEnd)));

  const pages = [];
  for (let page = start; page <= end; page += 1) {
    pages.push(page);
  }
  return pages;
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
 *
 *   페이지 범위 모드가 켜져 있으면 인접 페이지의 블록도 함께 로드하여
 *   페이지 경계를 넘는 합치기를 지원한다.
 */
async function _loadCompositionData() {
  const { docId, partId, pageNum } = viewerState;
  if (!docId || !partId || !pageNum) {
    _renderSourceBlocks();
    _renderTextBlocks();
    return;
  }

  // 초기 진입 시 범위 기본값 = 현재 페이지
  if (compState.rangeStart == null || compState.rangeEnd == null) {
    compState.rangeStart = pageNum;
    compState.rangeEnd = pageNum;
  }

  _syncPageRangeInputs();

  // 페이지 표시기 업데이트
  _updatePageIndicator(pageNum);

  const pages = _getPageRange(pageNum);

  // 각 페이지의 교정된 텍스트를 병렬 로드
  const correctedPromises = pages.map((p) =>
    fetch(`/api/documents/${docId}/pages/${p}/corrected-text?part_id=${partId}`)
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null),
  );

  const promises = [...correctedPromises];

  // 해석 저장소가 선택되어 있으면 TextBlock도 로드
  if (interpState.interpId) {
    // 범위 내 모든 페이지의 TextBlock을 로드하기 위해 각 페이지별 요청
    for (const p of pages) {
      promises.push(
        fetch(
          `/api/interpretations/${interpState.interpId}/entities/text_block?page=${p}&document_id=${docId}`,
        )
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null),
      );
    }
    // Work 자동 확보
    promises.push(_ensureWork());
  }

  const results = await Promise.all(promises);

  // 교정된 텍스트: 여러 페이지를 합쳐서 _page 태깅
  compState.sourceBlocks = [];
  for (let i = 0; i < pages.length; i++) {
    const correctedData = results[i];
    if (correctedData && correctedData.blocks) {
      // 각 블록에 소속 페이지 번호를 태깅
      const tagged = correctedData.blocks.map((b) => ({
        ...b,
        _page: pages[i],
      }));
      compState.sourceBlocks.push(...tagged);
    }
  }

  // TextBlock 목록: 범위 내 모든 페이지의 결과를 합침 (중복 제거)
  const tbStart = correctedPromises.length; // TextBlock 결과 시작 인덱스
  const seenTbIds = new Set();
  compState.textBlocks = [];

  if (interpState.interpId) {
    for (let i = 0; i < pages.length; i++) {
      const tbData = results[tbStart + i];
      if (tbData && tbData.entities) {
        for (const entity of tbData.entities) {
          // deprecated / archived는 목록에서 숨김
          if (entity.status === "deprecated" || entity.status === "archived")
            continue;
          if (!seenTbIds.has(entity.id)) {
            seenTbIds.add(entity.id);
            compState.textBlocks.push(entity);
          }
        }
      }
    }
  }

  compState.selectedBlockKeys = [];
  _renderSourceBlocks();
  _renderTextBlocks();
  _updateBlockCount();
}

/**
 * 페이지 표시기를 업데이트한다.
 */
function _updatePageIndicator(pageNum) {
  const el = document.getElementById("comp-page-indicator");
  if (el) {
    const pages = _getPageRange(pageNum);
    if (pages.length === 1) {
      el.textContent = `p.${pageNum}`;
    } else {
      el.textContent = `p.${pages[0]}–${pages[pages.length - 1]}`;
    }
  }
}

/**
 * 범위 입력 UI를 상태값과 동기화한다.
 */
function _syncPageRangeInputs() {
  const startInput = document.getElementById("comp-page-start");
  const endInput = document.getElementById("comp-page-end");
  if (startInput && compState.rangeStart != null) {
    startInput.value = String(compState.rangeStart);
  }
  if (endInput && compState.rangeEnd != null) {
    endInput.value = String(compState.rangeEnd);
  }
}

/**
 * 해석 저장소에 수동 git commit을 보낸다 (배치 작업 완료 후).
 *
 * 왜 이렇게 하는가:
 *   쪼개기·리셋 등 여러 API 호출이 필요한 배치 작업에서,
 *   개별 호출마다 git commit하면 10~60초씩 걸린다.
 *   no_commit=true로 변경을 모은 뒤 마지막에 한 번만 commit하면
 *   전체 작업이 1~2초에 끝난다.
 */
async function _commitBatch(message) {
  if (!interpState.interpId) return;
  try {
    await fetch(`/api/interpretations/${interpState.interpId}/git/commit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
  } catch (e) {
    console.error("배치 커밋 실패:", e);
  }
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
      `/api/interpretations/${interpState.interpId}/entities/work`,
    );
    if (listRes.ok) {
      const data = await listRes.json();
      const works = data.entities || [];
      // 현재 문헌에 해당하는 Work 찾기
      const match = works.find(
        (w) => w.metadata && w.metadata.document_id === viewerState.docId,
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
      },
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
 *
 * 페이지 범위 모드:
 *   블록이 여러 페이지에서 왔을 때 페이지별 구분선을 넣고,
 *   현재 페이지가 아닌 블록은 연한 배경으로 표시한다.
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
  const currentPage = viewerState.pageNum;

  // 페이지별 그룹핑
  let lastPage = null;

  compState.sourceBlocks.forEach((block) => {
    const blockPage = block._page || currentPage;

    // 페이지 구분선 (다른 페이지 블록이 시작될 때)
    if (blockPage !== lastPage) {
      lastPage = blockPage;
      const divider = document.createElement("div");
      const isCurrent = blockPage === currentPage;
      divider.style.cssText = `
        font-size: 10px;
        font-weight: 600;
        color: ${isCurrent ? "var(--text-primary)" : "var(--text-muted)"};
        padding: 4px 6px;
        margin-top: ${blockPage === compState.sourceBlocks[0]._page ? "0" : "8px"};
        border-bottom: 1px solid var(--border);
        display: flex;
        align-items: center;
        gap: 4px;
      `;
      divider.innerHTML = isCurrent
        ? `<span>p.${blockPage}</span> <span style="color:var(--accent-primary,#3b82f6);font-size:9px;">(현재)</span>`
        : `<span style="opacity:0.7;">p.${blockPage}</span>`;
      container.appendChild(divider);
    }

    const isForeignPage = blockPage !== currentPage;

    const card = document.createElement("div");
    card.className = "comp-source-card";
    card.dataset.blockId = block.block_id;
    card.dataset.blockPage = String(blockPage);

    // 이미 TextBlock으로 편성된 블록인지 확인
    const blockKey = _blockToKey(block, currentPage);
    const alreadyComposed = compState.textBlocks.some((tb) => {
      const refs = tb.source_refs || [];
      const inRefs = refs.some(
        (r) => _sourceRefToKey(r, blockPage) === blockKey,
      );
      if (inRefs) return true;
      return _sourceRefToKey(tb.source_ref, blockPage) === blockKey;
    });

    const isSelected = compState.selectedBlockKeys.includes(blockKey);

    // 현재 페이지가 아닌 블록은 왼쪽에 색깔 줄을 넣어 시각적으로 구분
    const borderLeft = isForeignPage
      ? "3px solid var(--accent-warning, #f59e0b)"
      : "none";
    card.style.cssText = `
      border: 1px solid ${alreadyComposed ? "var(--accent-green, #22c55e)" : isSelected ? "var(--accent-primary, #3b82f6)" : "var(--border)"};
      border-left: ${alreadyComposed ? "1px solid var(--accent-green, #22c55e)" : isSelected ? "1px solid var(--accent-primary, #3b82f6)" : borderLeft};
      border-radius: 4px;
      padding: 8px;
      cursor: pointer;
      background: ${alreadyComposed ? "rgba(34,197,94,0.05)" : isSelected ? "rgba(59,130,246,0.08)" : isForeignPage ? "rgba(245,158,11,0.03)" : "var(--bg-secondary)"};
      transition: border-color 0.15s;
    `;

    // 헤더: 체크박스 + 블록 ID + 페이지 뱃지 + 상태 뱃지
    const header = document.createElement("div");
    header.style.cssText =
      "display:flex; align-items:center; gap:6px; margin-bottom:4px;";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = isSelected;
    checkbox.disabled = alreadyComposed;
    checkbox.style.cssText = "margin:0;";
    checkbox.addEventListener("change", () => {
      _toggleBlockSelection(blockKey, checkbox.checked);
    });

    const label = document.createElement("span");
    label.style.cssText =
      "font-size:11px; font-weight:600; font-family:var(--font-mono);";
    label.textContent = block.block_id;

    const typeBadge = document.createElement("span");
    typeBadge.style.cssText =
      "font-size:10px; color:var(--text-muted); background:var(--bg-tertiary, #f0f0f0); padding:1px 4px; border-radius:2px;";
    typeBadge.textContent = block.block_type || "text";

    header.appendChild(checkbox);
    header.appendChild(label);
    header.appendChild(typeBadge);

    // 다른 페이지 블록이면 페이지 뱃지 표시
    if (isForeignPage) {
      const pageBadge = document.createElement("span");
      pageBadge.style.cssText =
        "font-size:9px; color:var(--accent-warning, #f59e0b); background:rgba(245,158,11,0.1); padding:1px 4px; border-radius:2px;";
      pageBadge.textContent = `p.${blockPage}`;
      header.appendChild(pageBadge);
    }

    if (alreadyComposed) {
      const doneBadge = document.createElement("span");
      doneBadge.style.cssText =
        "font-size:10px; color:var(--accent-green, #22c55e); margin-left:auto;";
      doneBadge.textContent = "편성됨";
      header.appendChild(doneBadge);
    }

    if (block.corrections_applied > 0) {
      const corrBadge = document.createElement("span");
      corrBadge.style.cssText =
        "font-size:10px; color:var(--accent-warning, #f59e0b); margin-left:auto;";
      corrBadge.textContent = `교정 ${block.corrections_applied}건`;
      header.appendChild(corrBadge);
    }

    // 텍스트 미리보기
    const preview = document.createElement("div");
    preview.style.cssText =
      "font-size:12px; line-height:1.6; white-space:pre-wrap; max-height:80px; overflow:hidden; color:var(--text-primary);";
    const displayText = block.corrected_text || block.original_text || "";
    preview.textContent =
      displayText.length > 200
        ? displayText.substring(0, 200) + "..."
        : displayText;

    card.appendChild(header);
    card.appendChild(preview);
    container.appendChild(card);

    // 카드 클릭으로도 선택 토글 (체크박스 외 영역)
    card.addEventListener("click", (e) => {
      if (e.target === checkbox || alreadyComposed) return;
      checkbox.checked = !checkbox.checked;
      _toggleBlockSelection(blockKey, checkbox.checked);
    });
  });
}

/**
 * 블록 선택 토글.
 */
function _toggleBlockSelection(blockKey, selected) {
  if (selected) {
    if (!compState.selectedBlockKeys.includes(blockKey)) {
      compState.selectedBlockKeys.push(blockKey);
    }
  } else {
    compState.selectedBlockKeys = compState.selectedBlockKeys.filter(
      (key) => key !== blockKey,
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
      "위의 해석 저장소 드롭다운에서 선택하세요.<br>" +
      '<span style="font-size:11px;">(없으면 사이드바 해석 저장소 섹션에서 새로 만들기)</span></div>';
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
    (a, b) => (a.sequence_index || 0) - (b.sequence_index || 0),
  );

  sorted.forEach((tb) => {
    const isSelectedTb = compState.selectedTbId === tb.id;
    const card = document.createElement("div");
    card.className = "comp-tb-card";
    card.style.cssText = `
      border: 1px solid ${isSelectedTb ? "var(--accent-primary, #3b82f6)" : "var(--accent-green, #22c55e)"};
      border-radius: 4px;
      padding: 8px;
      cursor: pointer;
      background: ${isSelectedTb ? "rgba(59,130,246,0.08)" : "rgba(34,197,94,0.03)"};
    `;
    card.addEventListener("click", (e) => {
      // 삭제 버튼 클릭 시에는 쪼개기 편집기를 열지 않음
      if (e.target.classList.contains("comp-tb-delete-btn")) return;
      _selectTextBlock(tb);
    });

    // 헤더: seq# + source 요약 + 삭제 버튼
    const header = document.createElement("div");
    header.style.cssText =
      "display:flex; align-items:center; gap:6px; margin-bottom:4px;";

    const seqBadge = document.createElement("span");
    seqBadge.style.cssText =
      "font-size:10px; font-weight:700; color:var(--accent-green, #22c55e); background:rgba(34,197,94,0.1); padding:1px 5px; border-radius:2px;";
    seqBadge.textContent = `#${tb.sequence_index}`;

    const sourceInfo = document.createElement("span");
    sourceInfo.style.cssText =
      "font-size:10px; color:var(--text-muted); font-family:var(--font-mono);";
    const refs = tb.source_refs || [];
    if (refs.length > 0) {
      // 크로스 페이지 source_refs이면 페이지도 표시
      const pages = new Set(refs.map((r) => r.page));
      if (pages.size > 1) {
        // 여러 페이지에 걸친 TextBlock
        sourceInfo.textContent = refs
          .map((r) => `p${r.page}:${r.layout_block_id || "?"}`)
          .join(" + ");
      } else {
        sourceInfo.textContent = refs
          .map((r) => r.layout_block_id || "?")
          .join(" + ");
      }
    } else if (tb.source_ref) {
      sourceInfo.textContent = tb.source_ref.layout_block_id || "?";
    }

    const statusBadge = document.createElement("span");
    statusBadge.style.cssText =
      "font-size:10px; color:var(--text-muted); margin-left:auto;";
    statusBadge.textContent = tb.status || "draft";

    // 삭제 버튼 (× 표시, hover 시에만 표시됨)
    const deleteBtn = document.createElement("button");
    deleteBtn.className = "comp-tb-delete-btn";
    deleteBtn.title = "이 TextBlock 삭제 (deprecated 전환)";
    deleteBtn.textContent = "\u00d7";
    deleteBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      _deleteTextBlock(tb);
    });

    header.appendChild(seqBadge);
    header.appendChild(sourceInfo);
    header.appendChild(statusBadge);

    // 크로스 페이지 TextBlock이면 뱃지 추가
    if (refs.length > 0) {
      const pages = new Set(refs.map((r) => r.page));
      if (pages.size > 1) {
        const crossBadge = document.createElement("span");
        crossBadge.style.cssText =
          "font-size:9px; color:var(--accent-warning, #f59e0b); background:rgba(245,158,11,0.1); padding:1px 4px; border-radius:2px;";
        crossBadge.textContent = `${pages.size}페이지`;
        header.insertBefore(crossBadge, statusBadge);
      }
    }

    // 삭제 버튼은 항상 맨 오른쪽에 위치
    header.appendChild(deleteBtn);

    // 텍스트 미리보기
    const preview = document.createElement("div");
    preview.style.cssText =
      "font-size:12px; line-height:1.6; white-space:pre-wrap; max-height:60px; overflow:hidden; color:var(--text-primary);";
    const text = tb.original_text || "";
    preview.textContent =
      text.length > 150 ? text.substring(0, 150) + "..." : text;

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
    el.style.color = isError
      ? "var(--accent-error, #ef4444)"
      : "var(--accent-green, #22c55e)";
  }
}

/* ──────────────────────────
   편성 액션: 자동 편성
   ────────────────────────── */

/**
 * 현재 페이지의 LayoutBlock을 1:1로 TextBlock으로 자동 생성한다.
 *
 * 왜 이렇게 하는가:
 *   대부분의 경우 LayoutBlock과 TextBlock이 1:1 대응한다.
 *   "자동 편성" 버튼 하나로 빠르게 편성을 완료할 수 있게 한다.
 *   이미 편성된 블록은 건너뛴다.
 *
 * 자동 편성은 현재 페이지 블록만 대상으로 한다.
 * 왜: 인접 페이지 블록은 합치기 전용이다. 자동 편성은 그 페이지에서 직접 해야 한다.
 */
async function _autoCompose() {
  if (!interpState.interpId) {
    showToast("편성 패널 상단의 해석 저장소 드롭다운에서 먼저 선택하세요.", 'warning');
    return;
  }
  if (!compState.workId) {
    await _ensureWork();
    if (!compState.workId) {
      showToast("Work를 확보할 수 없습니다. 해석 저장소를 다시 선택해주세요.", 'warning');
      return;
    }
  }

  const currentPage = viewerState.pageNum;

  // 현재 페이지 블록만 필터
  const currentPageBlocks = compState.sourceBlocks.filter(
    (b) => (b._page || currentPage) === currentPage,
  );

  if (currentPageBlocks.length === 0) {
    showToast("편성할 소스 블록이 없습니다.", 'warning');
    return;
  }

  // 이미 편성된 블록 ID 수집
  const composedKeys = new Set();
  compState.textBlocks.forEach((tb) => {
    const refs = tb.source_refs || [];
    refs.forEach((r) => {
      const key = _sourceRefToKey(r, currentPage);
      if (key) composedKeys.add(key);
    });
    const singleKey = _sourceRefToKey(tb.source_ref, currentPage);
    if (singleKey) {
      composedKeys.add(singleKey);
    }
  });

  // 편성 안 된 블록만 처리
  const toCompose = currentPageBlocks.filter(
    (b) => !composedKeys.has(_blockToKey(b, currentPage)),
  );

  if (toCompose.length === 0) {
    _updateCompStatus("모든 블록이 이미 편성됨", false);
    return;
  }

  _updateCompStatus(`편성 중... (${toCompose.length}개)`, false);

  let created = 0;
  const errors = [];
  const baseSeq = compState.textBlocks.length;

  for (let i = 0; i < toCompose.length; i++) {
    const block = toCompose[i];
    const text = block.corrected_text || block.original_text || "";
    if (!text.trim()) continue;

    // 여러 블록 생성 시 no_commit=true로 git commit을 건너뛴다
    const useNoCommit = toCompose.length > 1;
    const url =
      `/api/interpretations/${interpState.interpId}/entities/text_block/compose` +
      (useNoCommit ? "?no_commit=true" : "");

    try {
      const res = await fetch(url, {
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
              page: block._page || currentPage,
              layout_block_id: block.block_id,
              char_range: null,
            },
          ],
        }),
      });

      if (res.ok) {
        created++;
      } else {
        const err = await res.json().catch(() => ({}));
        errors.push(
          `${block.block_id}: ${err.error || err.detail || "HTTP " + res.status}`,
        );
        console.error(`TextBlock 생성 실패 (${block.block_id}):`, err);
      }
    } catch (e) {
      errors.push(`${block.block_id}: ${e.message}`);
      console.error(`TextBlock 생성 실패 (${block.block_id}):`, e);
    }
  }

  // no_commit 모드였으면 마지막에 한 번만 커밋
  if (created > 0 && toCompose.length > 1) {
    await _commitBatch(`feat: 자동 편성 — ${created}개 TextBlock 생성`);
  }

  if (errors.length > 0 && created === 0) {
    showToast(`자동 편성 실패:\n\n${errors.join("\n")}`, 'error');
    _updateCompStatus("자동 편성 실패", false);
    return;
  }
  if (errors.length > 0) {
    showToast(
      `${created}개 생성, ${errors.length}개 실패:\n\n${errors.join("\n")}`,
      'error',
    );
  }

  _updateCompStatus(`${created}개 TextBlock 생성 완료`, false);

  // 데이터 새로고침
  await _loadCompositionData();
}

/* ──────────────────────────
   편성 액션: 합치기 (크로스 페이지 지원)
   ────────────────────────── */

/**
 * 선택한 LayoutBlock들을 합쳐서 하나의 TextBlock을 생성한다.
 *
 * 왜 이렇게 하는가:
 *   고전 텍스트에서 문장이 여러 블록 또는 여러 페이지에 걸쳐 있는 경우,
 *   연구자가 해당 블록들을 선택하고 "합치기"를 누르면
 *   하나의 TextBlock으로 만들어진다.
 *
 * 크로스 페이지 지원:
 *   각 블록의 _page를 참조하여 source_refs에 정확한 page를 기록한다.
 *   이전 페이지의 마지막 블록 + 현재 페이지의 첫 블록처럼
 *   페이지 경계를 넘는 합치기가 가능하다.
 */
async function _mergeSelectedBlocks() {
  if (!interpState.interpId) {
    showToast("편성 패널 상단의 해석 저장소 드롭다운에서 먼저 선택하세요.", 'warning');
    return;
  }
  if (!compState.workId) {
    await _ensureWork();
    if (!compState.workId) {
      showToast("Work를 확보할 수 없습니다. 해석 저장소를 다시 선택해주세요.", 'warning');
      return;
    }
  }

  const selectedKeys = compState.selectedBlockKeys;
  if (selectedKeys.length < 2) {
    showToast("합치려면 2개 이상의 블록을 선택하세요.", 'warning');
    return;
  }

  const currentPage = viewerState.pageNum;

  // 선택된 블록의 텍스트를 순서대로 이어붙이기
  // (소스 블록 목록의 순서를 유지 — 이미 페이지 순 + reading_order 순)
  const selectedSet = new Set(selectedKeys);
  const orderedBlocks = compState.sourceBlocks.filter((b) =>
    selectedSet.has(_blockToKey(b, currentPage)),
  );

  if (orderedBlocks.length !== selectedKeys.length) {
    showToast(
      "선택한 블록을 모두 찾지 못했습니다. 범위를 다시 불러온 뒤 시도해주세요.",
      'warning',
    );
    return;
  }

  // 선택 블록은 순서가 섞이지 않는 연속 구간이어야 한다.
  const selectedIndices = compState.sourceBlocks
    .map((block, index) => ({ block, index }))
    .filter(({ block }) => selectedSet.has(_blockToKey(block, currentPage)))
    .map(({ index }) => index)
    .sort((a, b) => a - b);
  const minIndex = selectedIndices[0];
  const maxIndex = selectedIndices[selectedIndices.length - 1];
  const expectedCount = maxIndex - minIndex + 1;
  if (expectedCount !== selectedIndices.length) {
    showToast(
      "합치기는 순서가 섞이지 않는 연속 구간만 지원합니다.\n" +
        "중간 블록을 포함해서 다시 선택해주세요.",
      'warning',
    );
    return;
  }

  const mergedText = orderedBlocks
    .map((b) => b.corrected_text || b.original_text || "")
    .join("\n");

  // 각 블록의 실제 페이지를 source_refs에 기록 (크로스 페이지 핵심)
  const sourceRefs = orderedBlocks.map((b) => ({
    document_id: viewerState.docId,
    page: b._page || currentPage,
    layout_block_id: b.block_id,
    char_range: null,
  }));

  // 크로스 페이지 합치기인지 확인 (사용자에게 알림)
  const pages = new Set(sourceRefs.map((r) => r.page));
  const isCrossPage = pages.size > 1;

  _updateCompStatus(
    isCrossPage ? `${pages.size}개 페이지에서 합치는 중...` : "합치는 중...",
    false,
  );

  try {
    const res = await fetch(
      `/api/interpretations/${interpState.interpId}/entities/text_block/compose?no_commit=true`,
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
      },
    );

    if (res.ok) {
      // 합치기 성공 → 배치 커밋 (git commit 1회만)
      const blockIds = orderedBlocks.map((b) => b.block_id).join(" + ");
      const suffix = isCrossPage
        ? ` (p.${[...pages].join("+")} 크로스 페이지)`
        : "";
      await _commitBatch(`feat: TextBlock 합치기 — ${blockIds}${suffix}`);
      _updateCompStatus(`합치기 완료: ${blockIds}${suffix}`, false);
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

/* ──────────────────────────
   편성 액션: 쪼개기 (split)
   ────────────────────────── */

/**
 * TextBlock을 선택하고 쪼개기 편집기를 연다.
 *
 * 왜 이렇게 하는가:
 *   크로스 페이지 합치기로 만든 큰 TextBlock을
 *   연구자가 수동으로 단락별로 나눌 수 있어야 한다.
 *   TextBlock 카드를 클릭하면 쪼개기 편집기가 열리고,
 *   텍스트 중간에 === 구분선을 넣어 쪼갤 위치를 지정한다.
 *
 * 입력: tb — TextBlock 객체 ({id, original_text, source_refs, ...})
 */
function _selectTextBlock(tb) {
  compState.selectedTbId = tb.id;
  compState.selectedTb = tb;

  // 쪼개기 편집기 표시
  const editor = document.getElementById("comp-split-editor");
  const textarea = document.getElementById("comp-split-textarea");
  const splitBtn = document.getElementById("comp-split-btn");

  if (editor) editor.style.display = "block";
  if (textarea) {
    textarea.value = tb.original_text || "";
    textarea.focus();
  }
  if (splitBtn) splitBtn.disabled = false;

  _updateSplitPreview();

  // TextBlock 목록에서 선택 표시 갱신
  _renderTextBlocks();
}

/* ──────────────────────────
   편성 액션: 개별 TextBlock 삭제
   ────────────────────────── */

/**
 * 개별 TextBlock을 deprecated 상태로 전환하여 삭제한다.
 *
 * 왜 이렇게 하는가:
 *   잘못 편성된 TextBlock 하나만 골라서 삭제하고 싶을 때,
 *   전체 리셋 없이 개별 단위로 deprecated 전환할 수 있게 한다.
 *   deprecated된 TextBlock은 목록에서 숨겨지지만 이력은 보존된다.
 *
 * 입력: tb — TextBlock 객체 ({id, original_text, sequence_index, ...})
 */
async function _deleteTextBlock(tb) {
  if (!interpState.interpId) {
    showToast("해석 저장소가 선택되지 않았습니다.", 'warning');
    return;
  }

  // 텍스트 미리보기 (확인 대화상자에 표시)
  const previewText = (tb.original_text || "").substring(0, 50);
  const displayText =
    previewText +
    (tb.original_text && tb.original_text.length > 50 ? "..." : "");

  if (
    !confirm(
      `TextBlock #${tb.sequence_index} 을(를) 삭제하시겠습니까?\n\n"${displayText}"\n\n(deprecated 전환 — 이력은 보존됩니다)`,
    )
  ) {
    return;
  }

  _updateCompStatus("삭제 중...", false);

  try {
    // 배치 리셋 엔드포인트를 1개 ID로 호출 (단일 git commit)
    const res = await fetch(
      `/api/interpretations/${interpState.interpId}/entities/text_block/reset`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text_block_ids: [tb.id] }),
      },
    );

    if (res.ok || res.status === 207) {
      _updateCompStatus(`TextBlock #${tb.sequence_index} 삭제 완료`, false);

      // 삭제한 TextBlock이 현재 쪼개기 편집기에 열려 있으면 닫기
      if (compState.selectedTbId === tb.id) {
        _cancelSplit();
      }
    } else {
      const err = await res.json().catch(() => ({}));
      const msg = err.error || err.detail || `HTTP ${res.status}`;
      showToast(`삭제 실패: ${msg}`, 'error');
      return;
    }
  } catch (e) {
    showToast(`삭제 실패: ${e.message}`, 'error');
    return;
  }

  // 데이터 새로고침
  await _loadCompositionData();
}

/* ──────────────────────────
   편성 리셋
   ────────────────────────── */

/**
 * 현재 페이지의 TextBlock을 모두 deprecated 상태로 전환한다.
 *
 * 왜 이렇게 하는가:
 *   편성을 처음부터 다시 하고 싶을 때, 기존 TextBlock을 삭제하는 대신
 *   deprecated 상태로 전환하여 이력을 보존한다.
 *   deprecated된 TextBlock은 목록에서 숨겨지므로 깨끗하게 재시작할 수 있다.
 */
async function _resetComposition() {
  if (!interpState.interpId) {
    showToast("편성 패널 상단의 해석 저장소 드롭다운에서 먼저 선택하세요.", 'warning');
    return;
  }

  const targets = compState.textBlocks.filter(
    (tb) => tb.status !== "deprecated" && tb.status !== "archived",
  );

  if (targets.length === 0) {
    showToast("리셋할 TextBlock이 없습니다.", 'warning');
    return;
  }

  if (
    !confirm(
      `현재 표시된 TextBlock ${targets.length}개를 모두 리셋(deprecated)하시겠습니까?\n\n이력은 보존되며, 나중에 복원할 수 있습니다.`,
    )
  ) {
    return;
  }

  _updateCompStatus(`리셋 중... (${targets.length}개)`, false);

  try {
    // 배치 리셋 엔드포인트: 한 번의 API 호출 + 한 번의 git commit
    const res = await fetch(
      `/api/interpretations/${interpState.interpId}/entities/text_block/reset`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text_block_ids: targets.map((tb) => tb.id),
        }),
      },
    );

    if (!res.ok && res.status !== 207) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || err.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();
    const done = data.deprecated_count || 0;
    const errors = data.errors || [];

    if (errors.length > 0) {
      showToast(
        `${done}개 리셋 완료, ${errors.length}개 실패:\n${errors.join("\n")}`,
        'error',
      );
    }

    _updateCompStatus(`리셋 완료: ${done}개 deprecated`, false);
  } catch (e) {
    showToast(`리셋 실패: ${e.message}`, 'error');
    _updateCompStatus("리셋 실패", true);
    return;
  }

  // 쪼개기 편집기 닫기
  _cancelSplit();

  // 데이터 새로고침
  await _loadCompositionData();
}

/**
 * 쪼개기 편집기를 닫고 선택을 해제한다.
 */
function _cancelSplit() {
  compState.selectedTbId = null;
  compState.selectedTb = null;

  const editor = document.getElementById("comp-split-editor");
  const textarea = document.getElementById("comp-split-textarea");
  const splitBtn = document.getElementById("comp-split-btn");
  const preview = document.getElementById("comp-split-preview");

  if (editor) editor.style.display = "none";
  if (textarea) textarea.value = "";
  if (splitBtn) splitBtn.disabled = true;
  if (preview) preview.textContent = "";

  _renderTextBlocks();
}

/**
 * 쪼개기 미리보기를 업데이트한다.
 *
 * 왜 이렇게 하는가:
 *   === 구분선으로 텍스트를 나눴을 때 몇 조각이 되는지
 *   실시간으로 보여주어 연구자가 확인할 수 있게 한다.
 */
function _updateSplitPreview() {
  const textarea = document.getElementById("comp-split-textarea");
  const preview = document.getElementById("comp-split-preview");
  if (!textarea || !preview) return;

  const pieces = _parseSplitPieces(textarea.value);
  const nonEmpty = pieces.filter((p) => p.trim().length > 0);

  if (nonEmpty.length <= 1) {
    preview.textContent =
      "구분선(===)을 넣으면 여러 TextBlock으로 쪼갤 수 있습니다.";
    preview.style.color = "var(--text-muted)";
  } else {
    preview.textContent = `→ ${nonEmpty.length}개의 TextBlock으로 쪼개집니다.`;
    preview.style.color = "var(--accent-primary, #3b82f6)";
  }
}

/**
 * 텍스트를 === 구분선으로 나눈다.
 *
 * 파싱 규칙:
 *   - ===만 있는 줄을 기준으로 split
 *   - 각 조각의 앞뒤 공백은 trim
 *
 * 입력: text — 전체 텍스트
 * 출력: 문자열 배열 (쪼개진 조각들)
 */
function _parseSplitPieces(text) {
  return text
    .split(/\n\s*===\s*\n|^===\s*\n|\n\s*===$/gm)
    .map((piece) => piece.trim());
}

/**
 * 쪼개기를 실행한다.
 *
 * 처리 순서:
 *   1. 텍스트를 === 구분선으로 파싱
 *   2. 비어 있는 조각 제거
 *   3. 각 조각마다 새 TextBlock 생성 (source_refs는 원본 전체를 상속)
 *   4. 원본 TextBlock을 deprecated 상태로 전환
 *   5. 데이터 새로고침
 *
 * 왜 source_refs를 전체 상속하는가:
 *   쪼개기는 이미 합쳐진 TextBlock을 단락별로 나누는 작업이다.
 *   나눠진 각 조각이 어느 원본 LayoutBlock에서 왔는지
 *   정확한 char_range를 자동 계산하기 어렵다.
 *   전체 source_refs를 상속하되 char_range를 null로 두면
 *   "이 블록들에서 유래했다"는 추적성은 유지된다.
 */
async function _executeSplit() {
  if (!compState.selectedTb || !compState.selectedTbId) {
    showToast("쪼갤 TextBlock을 먼저 선택하세요.", 'warning');
    return;
  }
  if (!interpState.interpId) {
    showToast("편성 패널 상단의 해석 저장소 드롭다운에서 먼저 선택하세요.", 'warning');
    return;
  }

  // Work가 없으면 확보 시도
  if (!compState.workId) {
    await _ensureWork();
    if (!compState.workId) {
      showToast("Work를 확보할 수 없습니다. 해석 저장소를 다시 선택해주세요.", 'warning');
      return;
    }
  }

  const textarea = document.getElementById("comp-split-textarea");
  if (!textarea) return;

  const pieces = _parseSplitPieces(textarea.value);
  const nonEmpty = pieces.filter((p) => p.trim().length > 0);

  if (nonEmpty.length <= 1) {
    showToast(
      "=== 구분선을 넣어 2개 이상으로 나눠야 합니다.\n\n예시:\n첫 번째 텍스트\n===\n두 번째 텍스트",
      'warning',
    );
    return;
  }

  _updateCompStatus(`쪼개는 중... (${nonEmpty.length}개)`, false);

  try {
    const res = await fetch(
      `/api/interpretations/${interpState.interpId}/entities/text_block/split`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          original_text_block_id: compState.selectedTbId,
          pieces: nonEmpty,
          part_id: viewerState.partId,
        }),
      },
    );

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(
        err.error || err.detail || `쪼개기 실패: HTTP ${res.status}`,
      );
    }

    _updateCompStatus(
      `쪼개기 완료: ${nonEmpty.length}개 TextBlock 생성`,
      false,
    );
  } catch (e) {
    showToast(`쪼개기 실패:\n${e.message}`, 'error');
    _updateCompStatus("쪼개기 실패", true);
    return;
  }

  // 쪼개기 편집기 닫기
  _cancelSplit();

  // 데이터 새로고침
  await _loadCompositionData();
}
