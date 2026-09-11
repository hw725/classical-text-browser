/**
 * 편성 에디터 — LayoutBlock → 단위 변환
 *
 * 기능:
 *   1. 교정된 텍스트를 블록별로 표시 (교정 적용 후)
 *   2. 각 LayoutBlock을 1:1로 단위 자동 생성 ("자동 편성")
 *   3. 여러 LayoutBlock을 합쳐서 하나의 단위 생성 ("합치기")
 *   4. 이미 생성된 단위 목록 표시
 *   5. 크로스 페이지 합치기 (시작~끝 페이지 범위)
 *
 * 의존성:
 *   - sidebar-tree.js (viewerState)
 *   - interpretation.js (interpState)
 *
 * 왜 이렇게 하는가:
 *   교정은 LayoutBlock(물리적 단위) 기반이지만,
 *   표점·현토·번역은 단위(논리적 단위) 기반이다.
 *   이 편성 단계에서 연구자가 LayoutBlock을 단위으로
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
  currentBoundaries: [], // 지금 저장돼 있는 경계 — 편성 탭의 기본 화면
  // _page: 이 블록이 소속된 페이지 번호 (크로스 페이지 지원용)
  units: [], // 이미 생성된 단위 목록
  selectedTbId: null, // 쪼개기를 위해 선택된 단위 ID
  selectedTb: null, // 쪼개기를 위해 선택된 단위 객체
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
  _bindStepFolding();
  _bindCompEvents();
}

/**
 * 이벤트 바인딩.
 */
function _bindCompEvents() {
  const splitBtn = document.getElementById("comp-split-btn");
  const splitCancelBtn = document.getElementById("comp-split-cancel-btn");
  const splitTextarea = document.getElementById("comp-split-textarea");

  const splitExecBtn = document.getElementById("comp-split-exec-btn");
  const resetBtn = document.getElementById("comp-reset-btn");

  // 패널의 「쪼개기」는 고른 기사의 쪼개기 창을 연다 — 실행은 창 안의 단추가 한다(창이 닫혀 있으면 나눌 글이 없다)
  if (splitBtn)
    splitBtn.addEventListener("click", () => {
      if (compState.selectedTb) _selectUnit(compState.selectedTb);
      else showToast("사이드바 「내용」이나 아래 목록에서 기사를 먼저 고르세요.", "warning");
    });
  if (splitExecBtn) splitExecBtn.addEventListener("click", _executeSplit);
  if (splitCancelBtn) splitCancelBtn.addEventListener("click", _cancelSplit);
  const splitClose = document.getElementById("comp-split-close");
  if (splitClose) splitClose.addEventListener("click", _cancelSplit);
  const splitOverlay = document.getElementById("comp-split-overlay");
  if (splitOverlay)
    splitOverlay.addEventListener("click", (ev) => {
      if (ev.target === splitOverlay) _cancelSplit(); // 겉막을 누르면 닫는다
    });
  if (resetBtn) resetBtn.addEventListener("click", _resetComposition);
  // 편성 흐름 ①②③ (D-122) — 단추는 「말로 넣기」·「더 묻기」·「후보 보기」·「적용」 넷뿐이다
  const sayBtn = document.getElementById("comp-say-btn");
  if (sayBtn) sayBtn.addEventListener("click", _rulesFromWords);
  const sayBox = document.getElementById("comp-llm-say");
  if (sayBox)
    sayBox.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) _rulesFromWords();
    });
  const sigRefresh = document.getElementById("comp-signals-refresh");
  if (sigRefresh) sigRefresh.addEventListener("click", () => _startFlow(true));
  const sigPropose = document.getElementById("comp-signals-propose-btn");
  if (sigPropose) sigPropose.addEventListener("click", () => _proposeBoundaries());
  const proposeApply = document.getElementById("comp-propose-apply-btn");
  if (proposeApply) proposeApply.addEventListener("click", _applyProposals);
  // ②의 칸이 바뀌면 ③의 후보는 낡는다 — 「적용」을 막고 「후보 보기」를 가리킨다
  const sigBox = document.getElementById("comp-signals");
  if (sigBox) {
    sigBox.addEventListener("change", _refreshApplyState);
    sigBox.addEventListener("input", _refreshApplyState);
  }
  const checkAll = document.getElementById("comp-check-all");
  if (checkAll) checkAll.addEventListener("change", () => _checkVisible(checkAll.checked));
  for (const [id, fn] of [
    ["comp-batch-apply", _batchChange],
    ["comp-batch-check", () => _batchCheck(true)],
    ["comp-batch-uncheck", () => _batchCheck(false)],
    ["comp-batch-suppress", _batchSuppress],
  ]) {
    const el = document.getElementById(id);
    if (el) el.addEventListener("click", fn);
  }
  // LLM 진입점 — 「말로 넣기」와 「더 묻기」 창. 창에서 무엇을 물을지 고른다
  const llmBtn = document.getElementById("comp-llm-btn");
  if (llmBtn) llmBtn.addEventListener("click", _openLlmModal);
  const llmRun = document.getElementById("comp-llm-run");
  if (llmRun) llmRun.addEventListener("click", _runLlmModal);
  for (const id of ["comp-llm-close", "comp-llm-cancel"]) {
    const el = document.getElementById(id);
    if (el) el.addEventListener("click", _closeLlmModal);
  }
  const optStructInit = document.getElementById("comp-llm-opt-structure");
  if (optStructInit) optStructInit.addEventListener("change", _updateLlmStructureNote);
  const llmScope = document.getElementById("comp-llm-scope");
  if (llmScope) llmScope.addEventListener("change", _updateLlmScopeNote);
  const llmOverlay = document.getElementById("comp-llm-overlay");
  if (llmOverlay)
    llmOverlay.addEventListener("click", (ev) => {
      if (ev.target === llmOverlay) _closeLlmModal();
    });
  const addBtn = document.getElementById("comp-signals-add-btn");
  const addInput = document.getElementById("comp-signals-add-word");
  if (addBtn) addBtn.addEventListener("click", _addManualWord);
  if (addInput)
    addInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") _addManualWord();
    });
  const curRefresh = document.getElementById("comp-current-refresh");
  if (curRefresh) curRefresh.addEventListener("click", _renderCurrentBoundaries);
  // 사이드바에서 고른 것을 여기서도 표시한다 — 양쪽이 어긋나 보이면 안 된다
  document.addEventListener("unit-selected", (ev) => {
    const list = document.getElementById("comp-current-list");
    if (list)
      list.querySelectorAll(".comp-cur-row").forEach((el) => {
        el.classList.toggle("is-selected", el.dataset.unitId === ev.detail.id);
      });
    // 「단위 손보기」도 사이드바에서 고른 기사를 잡는다 — 그 «안»을 조각으로 나누는 도구다(사용자 지적 2026-09-11)
    _pickUnitForTweak(ev.detail.id);
  });
  // textarea 입력 시 쪼개기 미리보기 업데이트
  if (splitTextarea)
    splitTextarea.addEventListener("input", _updateSplitPreview);

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
  _loadCompositionData(); // 끝에서 _startFlow()를 부른다 — 「경계 제안」 단추는 없다(D-122)
}

/**
 * 편성 모드를 비활성화한다.
 */
// eslint-disable-next-line no-unused-vars
function deactivateCompositionMode() {
  compState.active = false;
}

/* ──────────────────────────
   페이지 범위 결정
   ────────────────────────── */

/* ──────────────────────────
   데이터 로드
   ────────────────────────── */

/**
 * 교정된 텍스트 + 기존 단위를 로드한다.
 *
 * 왜 이렇게 하는가:
 *   편성 화면은 두 영역으로 나뉜다:
 *   (1) 위: 교정된 LayoutBlock 텍스트 (소스)
 *   (2) 아래: 이미 생성된 단위 (결과)
 *
 *   페이지 범위 모드가 켜져 있으면 인접 페이지의 블록도 함께 로드하여
 *   페이지 경계를 넘는 합치기를 지원한다.
 */
async function _loadCompositionData() {
  // 편성이 바뀌면 사이드바 「내용」 트리도 따라간다 (D-085)
  if (typeof refreshContentsTree === "function") refreshContentsTree();
  const { docId, partId, pageNum } = viewerState;
  if (!docId || !partId || !pageNum) {
    _renderUnits();
    return;
  }

  // 단위는 **원본 저장소**의 것이다(D-097). 이 패널만 해석 저장소에 묻고 있어서, 해석 저장소를
  // 고르지 않으면 조회조차 하지 않았고 목록이 늘 비어 「쪼개기」가 영영 꺼져 있었다
  // (浩齋65 실측 2026-09-08: 원본에 단위 581개가 있는데 화면은 «아직 단위가 없습니다»).
  // 사이드바 「내용」 트리와 같은 곳을 본다.
  compState.units = [];
  try {
    const url =
      `/api/documents/${encodeURIComponent(docId)}/boundaries` +
      `?part_id=${encodeURIComponent(viewerState.partId || "")}&include_text=1`;
    const res = await fetch(url);
    const data = res.ok ? await res.json() : null;
    for (const row of (data && data.boundaries) || []) {
      if (row.unit_status === "deprecated" || row.unit_status === "archived") continue;
      // 경계 색인의 평평한 칸을 카드가 기대하는 모양으로 옮긴다
      compState.units.push({
        id: row.id,
        sequence_index: row.order != null ? row.order + 1 : row.sequence_index,
        original_text: row.original_text || "",
        source_refs: row.source_refs || [],
        status: row.unit_status || row.status || "draft",
        metadata: { level: row.level, role: row.role, title: row.title },
      });
    }
  } catch (e) {
    console.error("단위 목록을 읽지 못했습니다", e);
  }

  _renderUnits();
  _updateBlockCount();
  if (compState.pendingUnitId) _pickUnitForTweak(compState.pendingUnitId); // 탭을 늦게 열어도 사이드바의 선택을 잡는다
  _renderCurrentBoundaries();
  // 편성 흐름은 스스로 시작한다 — 다른 문헌·권으로 바뀌었으면 다시 센다(같으면 아무 일도 없다)
  if (compState.active) _startFlow();
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
 * 이미 생성된 단위 목록을 렌더링한다.
 */
function _renderUnits() {
  const container = document.getElementById("comp-textblock-list");
  if (!container) return;

  if (!viewerState.docId || !viewerState.partId) {
    container.innerHTML =
      '<div class="placeholder" style="padding:20px; text-align:center; color:var(--text-muted);">' +
      "사이드바에서 문헌과 권을 고르세요.<br>" +
      '<span style="font-size:11px;">(편성은 원본 저장소의 것이라 해석 저장소를 고르지 않아도 됩니다)</span></div>';
    return;
  }

  if (compState.units.length === 0) {
    container.innerHTML =
      '<div class="placeholder" style="padding:20px; text-align:center; color:var(--text-muted);">' +
      '아직 단위가 없습니다. 위 ①②③으로 후보를 골라 「적용」하거나, 사이드바 「내용」의 «경계 넣기»로 첫 경계를 놓으세요.</div>';
    return;
  }

  // 접기는 바깥 <details id="comp-manual">가 맡는다 — 여기서 또 접으면 두 겹이 된다.
  container.innerHTML = "";

  // sequence_index 순으로 정렬
  const sorted = [...compState.units].sort(
    (a, b) => (a.sequence_index || 0) - (b.sequence_index || 0),
  );
  // «기사인데 아래 단위를 품은» 것을 찾는다.
  // 단위의 끝은 «같은 깊이 이상의 다음 경계»다(D-092). 그래서 깊이가 이웃보다 얕은 기사는
  // 뒤따르는 기사들을 통째로 삼킨다 — 천진담초 실측에서 기사 하나가 30,906자(권 뒤쪽 전부)였다.
  // 논리로는 맞지만 사람이 알아채기 어려우므로 카드에 적어 준다.
  const swallows = new Map();
  sorted.forEach((u, i) => {
    const lv = Number(u.metadata?.level) || 2;
    let n = 0;
    for (let j = i + 1; j < sorted.length; j++) {
      if ((Number(sorted[j].metadata?.level) || 2) <= lv) break;
      n++;
    }
    if (n > 0 && (u.metadata?.role || "article") !== "container") swallows.set(u.id, n);
  });

  sorted.forEach((tb) => {
    const isSelectedTb = compState.selectedTbId === tb.id;
    const card = document.createElement("div");
    card.className = "comp-tb-card";
    card.dataset.unitId = tb.id;
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
      _selectUnit(tb);
    });

    // 헤더: seq# + source 요약 + 삭제 버튼
    const header = document.createElement("div");
    header.style.cssText =
      "display:flex; align-items:center; gap:6px; margin-bottom:4px;";

    const seqBadge = document.createElement("span");
    seqBadge.style.cssText =
      "font-size:10px; font-weight:700; color:var(--accent-green, #22c55e); background:rgba(34,197,94,0.1); padding:1px 5px; border-radius:2px;";
    seqBadge.textContent = `#${tb.sequence_index}`;

    // 역할·글자 수 — 무엇을 고르는지 카드에서 바로 보이게
    const roleName = { container: "묶음", article: "기사", fragment: "조각" };
    const kindBadge = document.createElement("span");
    kindBadge.style.cssText = "font-size:10px; color:var(--text-muted);";
    const chars = (tb.original_text || "").length;
    kindBadge.textContent = `${roleName[tb.metadata?.role || "article"] || "기사"} · ${chars.toLocaleString()}자`;

    // 출처는 «몇 쪽에 걸쳐 있는가»만 보인다. v1.3부터 단위는 LayoutBlock을 기억하지 않아
    // 그 id는 전부 «?»로 나왔다 — 카드의 절반을 뜻 없는 문자열이 차지하고 있었다(D-092).
    const sourceInfo = document.createElement("span");
    sourceInfo.style.cssText = "font-size:10px; color:var(--text-muted);";
    const refs = (tb.source_refs || []).length
      ? tb.source_refs
      : tb.source_ref
        ? [tb.source_ref]
        : [];
    const pageNums = [...new Set(refs.map((r) => r.page).filter((n) => n != null))].sort(
      (a, b) => a - b,
    );
    if (pageNums.length === 1) sourceInfo.textContent = `${pageNums[0]}쪽`;
    else if (pageNums.length > 1)
      sourceInfo.textContent = `${pageNums[0]}~${pageNums[pageNums.length - 1]}쪽`;

    const statusBadge = document.createElement("span");
    statusBadge.style.cssText =
      "font-size:10px; color:var(--text-muted); margin-left:auto;";
    statusBadge.textContent = tb.status || "draft";

    // 삭제 버튼 (× 표시, hover 시에만 표시됨)
    const deleteBtn = document.createElement("button");
    deleteBtn.className = "comp-tb-delete-btn";
    deleteBtn.title = "이 단위를 물리기 (경계를 deprecated로 — 되돌릴 수 있음)";
    deleteBtn.textContent = "\u00d7";
    deleteBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      _deleteUnit(tb);
    });

    header.appendChild(seqBadge);
    header.appendChild(sourceInfo);
    header.appendChild(statusBadge);

    // 「52페이지」 뱃지는 없앴다 — 바로 옆의 「11~62쪽」이 같은 것을 더 잘 말한다
    header.insertBefore(kindBadge, statusBadge);
    const swallowed = swallows.get(tb.id);
    if (swallowed) {
      const warn = document.createElement("span");
      warn.style.cssText =
        "font-size:10px; color:var(--accent-warning, #f59e0b); background:rgba(245,158,11,0.12); padding:1px 5px; border-radius:2px;";
      warn.textContent = `⚠ 아래 단위 ${swallowed}개를 품음`;
      warn.title =
        "이 단위의 깊이가 뒤따르는 단위들보다 얕아, 그것들을 통째로 삼키고 있습니다." +
        "\n" +
        "사이드바 「내용」에서 ⇥로 깊이를 한 단 내리거나, 역할을 «묶음»으로 바꾸세요.";
      header.insertBefore(warn, statusBadge);
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
  if (!el) return;
  const tb = compState.selectedTb;
  const role = { container: "묶음", article: "기사", fragment: "조각" }[tb?.metadata?.role || "article"];
  el.textContent =
    `단위 ${compState.units.length}개` +
    (tb
      ? ` · 고른 ${role} #${tb.sequence_index} 「${(tb.metadata?.title || "").slice(0, 14)}」 → 「쪼개기」로 그 안을 나눕니다`
      : " · 사이드바 「내용」에서 기사를 고르면 여기서 그 안을 나눕니다");
}

/**
 * 사이드바 「내용」에서 고른 단위를 「단위 손보기」의 대상으로 잡는다(창은 열지 않는다 — 「쪼개기」를 누르면 연다).
 * 입력: 단위 id. 출력: 없음. 단위 목록이 아직 없으면 기억해 두었다가 목록이 오면 잡는다.
 */
function _pickUnitForTweak(id) {
  const tb = (compState.units || []).find((u) => u.id === id);
  if (!tb) {
    compState.pendingUnitId = id;
    return;
  }
  compState.pendingUnitId = null;
  compState.selectedTbId = tb.id;
  compState.selectedTb = tb;
  const splitBtn = document.getElementById("comp-split-btn");
  if (splitBtn) splitBtn.disabled = false;
  _updateBlockCount();
  document.querySelectorAll("#comp-textblock-list .comp-tb-card").forEach((card) => {
    card.classList.toggle("is-selected", card.dataset.unitId === tb.id);
  });
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
 * 단위를 선택하고 쪼개기 편집기를 연다.
 *
 * 왜 이렇게 하는가:
 *   크로스 페이지 합치기로 만든 큰 단위를
 *   연구자가 수동으로 단락별로 나눌 수 있어야 한다.
 *   단위 카드를 클릭하면 쪼개기 편집기가 열리고,
 *   텍스트 중간에 === 구분선을 넣어 쪼갤 위치를 지정한다.
 *
 * 입력: tb — 단위 객체 ({id, original_text, source_refs, ...})
 */
function _selectUnit(tb) {
  compState.selectedTbId = tb.id;
  compState.selectedTb = tb;
  // 쪼개기는 가운데 모달로 뜬다 — 패널 맨 밑으로 내려가면 긴 본문을 다루기 어렵다(사용자 요청)
  const editor = document.getElementById("comp-split-overlay");
  const textarea = document.getElementById("comp-split-textarea");
  const splitBtn = document.getElementById("comp-split-btn");

  if (editor) editor.style.display = "flex";
  const info = document.getElementById("comp-split-info");
  if (info) {
    const role = { container: "묶음", article: "기사", fragment: "조각" }[tb.metadata?.role || "article"];
    const title = tb.metadata?.title || "";
    info.textContent = `#${tb.sequence_index} ${role}${title ? " · " + title : ""} · ${(tb.original_text || "").length.toLocaleString()}자`;
  }
  if (textarea) {
    textarea.value = tb.original_text || "";
    textarea.focus();
  }
  if (splitBtn) splitBtn.disabled = false;

  _updateSplitPreview();

  // 단위 목록에서 선택 표시 갱신
  _renderUnits();
}

/* ──────────────────────────
   편성 액션: 개별 단위 삭제
   ────────────────────────── */

/**
 * 개별 단위를 deprecated 상태로 전환하여 삭제한다.
 *
 * 왜 이렇게 하는가:
 *   잘못 편성된 단위 하나만 골라서 삭제하고 싶을 때,
 *   전체 리셋 없이 개별 단위로 deprecated 전환할 수 있게 한다.
 *   deprecated된 단위는 목록에서 숨겨지지만 이력은 보존된다.
 *
 * 입력: tb — 단위 객체 ({id, original_text, sequence_index, ...})
 */
async function _deleteUnit(tb) {
  if (!viewerState.docId || !viewerState.partId) {
    showToast("사이드바에서 문헌과 권을 먼저 고르세요.", "warning");
    return;
  }

  // 텍스트 미리보기 (확인 대화상자에 표시)
  const previewText = (tb.original_text || "").substring(0, 50);
  const displayText =
    previewText +
    (tb.original_text && tb.original_text.length > 50 ? "..." : "");

  if (
    !confirm(
      `단위 #${tb.sequence_index} 을(를) 삭제하시겠습니까?\n\n"${displayText}"\n\n(deprecated 전환 — 이력은 보존됩니다)`,
    )
  ) {
    return;
  }

  _updateCompStatus("삭제 중...", false);

  try {
    // 배치 리셋 엔드포인트를 1개 ID로 호출 (단일 git commit)
    const res = await fetch(
      `/api/documents/${encodeURIComponent(viewerState.docId)}/composition/reset`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ part_id: viewerState.partId, unit_ids: [tb.id] }),
      },
    );

    if (res.ok || res.status === 207) {
      _updateCompStatus(`단위 #${tb.sequence_index} 삭제 완료`, false);

      // 삭제한 단위가 현재 쪼개기 편집기에 열려 있으면 닫기
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
 * 현재 페이지의 단위를 모두 deprecated 상태로 전환한다.
 *
 * 왜 이렇게 하는가:
 *   편성을 처음부터 다시 하고 싶을 때, 기존 단위를 삭제하는 대신
 *   deprecated 상태로 전환하여 이력을 보존한다.
 *   deprecated된 단위는 목록에서 숨겨지므로 깨끗하게 재시작할 수 있다.
 */
async function _resetComposition() {
  if (!viewerState.docId || !viewerState.partId) {
    showToast("사이드바에서 문헌과 권을 먼저 고르세요.", "warning");
    return;
  }

  const targets = compState.units.filter(
    (tb) => tb.status !== "deprecated" && tb.status !== "archived",
  );

  if (targets.length === 0) {
    showToast("물릴 단위가 없습니다.", 'warning');
    return;
  }

  if (
    !confirm(
      `현재 표시된 단위 ${targets.length}개를 모두 리셋(deprecated)하시겠습니까?\n\n이력은 보존되며, 나중에 복원할 수 있습니다.`,
    )
  ) {
    return;
  }

  _updateCompStatus(`리셋 중... (${targets.length}개)`, false);

  try {
    // 배치 리셋 엔드포인트: 한 번의 API 호출 + 한 번의 git commit
    const res = await fetch(
      `/api/documents/${encodeURIComponent(viewerState.docId)}/composition/reset`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          part_id: viewerState.partId,
          unit_ids: targets.map((tb) => tb.id),
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

  const editor = document.getElementById("comp-split-overlay");
  const textarea = document.getElementById("comp-split-textarea");
  const splitBtn = document.getElementById("comp-split-btn");
  const preview = document.getElementById("comp-split-preview");

  if (editor) editor.style.display = "none";
  if (textarea) textarea.value = "";
  if (splitBtn) splitBtn.disabled = true;
  if (preview) preview.textContent = "";
  _updateBlockCount();

  _renderUnits();
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
    preview.textContent = "구분선(===)을 넣으면 여러 문단으로 나뉩니다.";
    preview.style.color = "var(--text-muted)";
  } else {
    // 첫 조각은 원래 기사의 자리에 남는다 — 새로 서는 경계는 둘째 조각부터다
    preview.textContent = `→ 이 기사 안이 문단 ${nonEmpty.length}개로 나뉩니다 (조각 경계 ${nonEmpty.length - 1}개가 들어갑니다).`;
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
 *   3. 각 조각마다 새 단위 생성 (source_refs는 원본 전체를 상속)
 *   4. 원본 단위를 deprecated 상태로 전환
 *   5. 데이터 새로고침
 *
 * 왜 source_refs를 전체 상속하는가:
 *   쪼개기는 이미 합쳐진 단위를 단락별로 나누는 작업이다.
 *   나눠진 각 조각이 어느 원본 LayoutBlock에서 왔는지
 *   정확한 char_range를 자동 계산하기 어렵다.
 *   전체 source_refs를 상속하되 char_range를 null로 두면
 *   "이 블록들에서 유래했다"는 추적성은 유지된다.
 */
async function _executeSplit() {
  if (!compState.selectedTb || !compState.selectedTbId) {
    showToast("나눌 단위를 먼저 선택하세요.", 'warning');
    return;
  }
  if (!viewerState.docId || !viewerState.partId) {
    showToast("사이드바에서 문헌과 권을 먼저 고르세요.", "warning");
    return;
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
      `/api/documents/${encodeURIComponent(viewerState.docId)}/composition/split`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          original_unit_id: compState.selectedTbId,
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
      `쪼개기 완료: ${nonEmpty.length}개 단위 생성`,
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


/* ──────────────────────────
   경계 제안 (D-088)
   권 전체 확정본에서 글 단위 경계 후보를 받아 보이고, 승인한 것만 단위으로.
   합치기·쪼개기를 블록 단위로 반복하는 대신 «어디서 글이 바뀌는가»만 정한다.
   ────────────────────────── */

/* ──────────────────────────
   이 책의 신호 (D-116) — 전문에서 센 규약 후보. 고른 것이 규칙이 된다
   ────────────────────────── */

const signalState = {
  data: null, // /segmentation/signals 응답
  docId: null, // 어느 문헌·권의 신호인가 — 다른 문헌으로 바꾼 뒤 옛 설정을 저장하면 안 된다
  partId: null,
  seq: 0, // 요청 세대. 늦게 끝난 옛 요청이 새 상태를 덮지 않게
  checked: new Set(), // 켜진 신호 id
  manual: [], // 사람이 더한 어휘 행 [{id, toggle, label}]
  // 초안 규칙 전체 — 화면 칸에 없는 값(min_confidence·furniture 등)의 바탕. 처음엔 저장본(없으면 권고),
  // 「말로 넣기」가 돌려준 규칙으로 바뀐다. 저장본을 바탕으로 쓰면 말로 바꾼 값이 사라진다(Codex 지적)
  draft: null,
  touched: false, // 권고에서 하나라도 바꿨는가 → origin "manual"
};

/** 신호 상태가 지금 고른 문헌·권의 것인가. */
function _signalsCurrent() {
  return !!signalState.data && signalState.docId === viewerState.docId && signalState.partId === viewerState.partId;
}

// 신호 id → 사람 말. 서버(core.rule_induction.SIGNAL_LABELS)와 같은 말을 쓴다
const _SIGNAL_LABELS = {
  date: "날짜가 행 첫머리에", mark: "○ 권점 + 날짜", volume: "卷頭 (卷之一 …)",
  indent_alone: "내려쓰기만으로 경계",
  short_line: "짧은 행", after_short: "행갈음 뒤의 행", indent: "내려쓰기",
};
function _signalLabel(id) {
  if (id === "toc") return "목차";
  if (_SIGNAL_LABELS[id]) return _SIGNAL_LABELS[id];
  const i = id.indexOf(":");
  if (i < 0) return id;
  const pos = id.slice(0, i);
  const v = id.slice(i + 1);
  if (pos === "tail") return `행 끝 「${v}」`;
  if (pos === "head") return `행 첫머리 「${v}」`;
  if (pos === "sym") return `기호 「${v}」`;
  if (pos === "after") return `기호 뒤 「${v}」`;
  return id;
}

// 규칙의 «목록 칸»들 — 행의 toggle이 이 중 하나면 value가 그 칸에 들어간다(D-119)
const _LIST_TOGGLES = ["title_words", "head_words", "symbols", "head_templates", "tail_templates"];

/**
 * 답 한 줄 (D-117) — 층계가 어디서 멈췄는지. 0단이면 LLM 단추를 내고 «자세히»를 펼친다.
 */
function _renderVerdict() {
  const box = document.getElementById("comp-verdict");
  const text = document.getElementById("comp-verdict-text");
  if (!box || !text) return;
  const d = signalState.data;
  const stage = d?.stage;
  box.classList.remove("is-none", "is-toc");
  if (!stage) {
    text.textContent = "전문을 세지 못했습니다.";
    return;
  }
  const saved = d.saved_rules;
  const hasSaved = !!saved && !!(saved.origin || saved.title_words?.length || saved.head_words?.length || saved.symbols?.length || Object.keys(saved.signals || {}).length);
  text.innerHTML = "";
  const lead = document.createElement("b");
  lead.textContent = "찾은 규약: ";
  text.appendChild(lead);
  text.appendChild(document.createTextNode(stage.summary));
  const tag = document.createElement("span");
  tag.className = "comp-verdict-stage";
  tag.textContent = ` — ${stage.level ? `${stage.level}단 ${stage.name}` : "0단"}` + (hasSaved ? (saved.origin === "manual" ? " · 저장된 설정(손봄)을 따릅니다" : " · 저장된 설정") : " · 권고(아직 저장 안 됨)");
  text.appendChild(tag);
  if (stage.level === 1) box.classList.add("is-toc");
  if (stage.level === 0) box.classList.add("is-none");
  // 규약은 OCR(L2)로도 세지만 후보는 확정본(L4)만 읽는다 — 없으면 ③이 비는 까닭을 여기서 말한다
  box.querySelectorAll(".comp-verdict-warn").forEach((el) => el.remove());
  if (!(d.source || {}).l4_pages) {
    const warn = document.createElement("span");
    warn.className = "comp-verdict-warn";
    warn.textContent = "확정본(L4)이 없어 후보를 만들 수 없습니다 — 교정 인덱스의 「권 전체 OCR」을 먼저 하세요";
    box.appendChild(warn);
  }
  // 저장된 설정이 이번 권고와 다르면(예: D-116 때 저장한 뒤 층계가 바뀜) 한 번에 권고로 돌아갈 길을 준다
  box.querySelectorAll(".comp-verdict-reset").forEach((el) => el.remove());
  const rec = d.recommended_rules;
  if (hasSaved && rec && (stage.by || []).some((id) => id !== "toc" && !signalState.checked.has(id))) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "text-btn text-btn-sm comp-verdict-reset";
    b.textContent = "권고대로";
    b.title = "저장된 설정을 버리고 이번에 찾은 규약(권고)대로 체크합니다. 「후보 보기」나 「전부 적용」을 눌러야 저장됩니다";
    b.addEventListener("click", () => {
      signalState.checked = new Set();
      signalState.manual = signalState.manual.filter((m) => m.llm);
      for (const r of d.signals) {
        if (r.toggle.startsWith("signals.")) {
          if (rec.signals?.[r.toggle.slice(8)] !== false) signalState.checked.add(r.id);
        } else if (_LIST_TOGGLES.includes(r.toggle) && (rec[r.toggle] || []).includes(r.value)) signalState.checked.add(r.id);
        else if (r.toggle === "indent_alone" && rec.indent_alone) signalState.checked.add(r.id);
      }
      signalState.touched = false;
      _renderSignals();
      tag.textContent = ` — ${stage.level}단 ${stage.name} · 권고대로 체크함(아직 저장 안 됨)`;
      b.remove();
    });
    text.appendChild(b);
  }
}

/**
 * 「더 묻기…」 창 — 편성 탭에서 「말로 넣기」와 함께 모델을 부르는 자리 (D-117·D-122).
 *
 * 왜 창 하나인가: LLM 단추가 셋(구조화 스위치·어휘 뽑기·표지 묻기)이면 «무엇이 모델을 부르는가»가
 * 헷갈린다(사용자 지시 2026-09-07). 창에서 셋 중 고르고 「묻기」 한 번으로 돈다.
 * 목차 항목 구조화는 누를 때 목차를 LLM으로 읽어 이번 후보에 쓰고, 문헌 설정 toc_llm에도 남긴다
 * (서버 auto 라우트가 읽는 값 — 사이드바 「자동 트리」는 규칙만 쓴다). 나머지 둘도 누를 때 한 번 돈다.
 */
function _openLlmModal() {
  if (!viewerState.docId || !viewerState.partId) {
    showToast("사이드바에서 문헌과 권을 먼저 고르세요.", "warning");
    return;
  }
  const overlay = document.getElementById("comp-llm-overlay");
  if (!overlay) return;
  const d = signalState.data;
  const toc = _signalsCurrent() ? d.toc : null;
  const optToc = document.getElementById("comp-llm-opt-toc");
  const note = document.getElementById("comp-llm-opt-toc-note");
  if (optToc) {
    optToc.checked = !!document.getElementById("comp-toc-llm")?.checked;
    optToc.disabled = !toc;
  }
  if (note) note.textContent = toc ? `(목차 ${toc.pages.join(",")}쪽 · ${toc.entries}항목)` : "(이 권에서 목차 쪽을 못 찾아 해당 없음)";
  const optPat = document.getElementById("comp-llm-opt-patterns");
  if (optPat) optPat.checked = !!(d && d.stage && d.stage.level === 0); // 못 찾은 책이면 표지 묻기가 기본
  const optWords = document.getElementById("comp-llm-opt-words");
  if (optWords) optWords.checked = false;
  const optStruct = document.getElementById("comp-llm-opt-structure");
  if (optStruct) optStruct.checked = false;
  const status = document.getElementById("comp-llm-status");
  if (status) status.textContent = "";
  _updateLlmRefNote();
  overlay.style.display = "";
  _updateLlmScopeNote();
  _updateLlmStructureNote();
}

/** ①의 글(해제·서지 설명 + 아는 것). 세 선택지와 「말로 넣기」가 다 이것을 보낸다. 저장은 「적용」(reference_text). */
function _llmReferenceText() {
  return (document.getElementById("comp-llm-say")?.value || "").trim();
}

/**
 * 모달의 참고 상태 줄 — ①의 글이 몇 자인지. 입력: 없음. 출력: 없음.
 * 해제는 ①의 칸에 있다(D-122 덧붙임 2026-09-11) — 따로 가던 「해제 칸으로」 단추는 없앴다.
 */
function _updateLlmRefNote() {
  const note = document.getElementById("comp-llm-ref-note");
  if (!note) return;
  const n = _llmReferenceText().length;
  note.textContent = n ? `①의 글 ${n.toLocaleString()}자를 함께 읽습니다` : "①이 비어 있습니다 — 해제·서지 설명을 붙여 넣으면 더 정확합니다";
  note.title = n
    ? "아래 선택지가 모두 함께 읽습니다. 긴 해제는 권별 서술이 있는 데를 골라 넘깁니다"
    : "한국고전종합DB 해제 같은 것을 ①에 통째로 붙여 넣으면 아래 선택지가 모두 더 정확해집니다";
}

/** 표본 범위의 크기(줄·글자)를 보내기 전에 보인다 — 실행 게이트는 도구 층에(전역 규칙 11). */
async function _updateLlmScopeNote() {
  const note = document.getElementById("comp-llm-scope-note");
  const sel = document.getElementById("comp-llm-scope");
  if (!note || !sel || !viewerState.docId || !viewerState.partId) return;
  note.textContent = "크기를 재는 중…";
  try {
    const res = await fetch(`/api/documents/${encodeURIComponent(viewerState.docId)}/segmentation/signals/llm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ part_id: viewerState.partId, scope: sel.value, dry_run: true }),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.error || `HTTP ${res.status}`);
    note.textContent = `${d.lines}줄 · ${Number(d.chars).toLocaleString()}자`;
  } catch (e) {
    note.textContent = `크기 못 잼: ${e.message}`;
  }
}

function _closeLlmModal() {
  const overlay = document.getElementById("comp-llm-overlay");
  if (overlay) overlay.style.display = "none";
}

async function _runLlmModal() {
  const wantToc = !!document.getElementById("comp-llm-opt-toc")?.checked;
  const wantWords = !!document.getElementById("comp-llm-opt-words")?.checked;
  const wantPat = !!document.getElementById("comp-llm-opt-patterns")?.checked;
  const wantStruct = !!document.getElementById("comp-llm-opt-structure")?.checked;
  const status = document.getElementById("comp-llm-status");
  const run = document.getElementById("comp-llm-run");
  const say = (t) => {
    if (status) status.textContent = t;
  };
  if (!_signalsCurrent()) {
    say("신호를 세는 중…");
    await _startFlow();
    if (!_signalsCurrent()) {
      say("신호를 세지 못했습니다.");
      return;
    }
  }
  // 목차 구조화는 설정이다 — 숨은 체크박스(문헌 설정 toc_llm)에 남긴다
  const tocState = document.getElementById("comp-toc-llm");
  const mark = document.getElementById("comp-toc-llm-mark");
  if (tocState && tocState.checked !== wantToc) {
    tocState.checked = wantToc;
    signalState.touched = true;
  }
  if (mark) mark.hidden = !wantToc;
  if (!wantToc && !wantWords && !wantPat && !wantStruct) {
    say("고른 것이 없습니다.");
    return;
  }
  if (run) run.disabled = true;
  try {
    const done = [];
    if (wantWords) {
      say("해제·본문 표본을 보내는 중…");
      await _suggestRules();
      done.push("표제 어휘");
    }
    if (wantPat) {
      say("시작 표지 표본을 보내는 중…");
      await _askLlmPatterns();
      done.push("시작 표지");
    }
    if (wantToc) {
      say("목차 쪽 텍스트를 보내는 중…");
      await _detectToc(true);
      done.push("목차 구조화");
    }
    if (wantStruct) {
      // 권 전문(텍스트)을 보낸다 — 이 선택지만 «조각»이 아니라 전문이다. 크기는 창에 미리 보였다
      say("권 전문을 보내는 중… (묶음마다 한 번씩 부릅니다)");
      await _askLlmStructure();
      done.push("구조");
    }
    _closeLlmModal();
    const out = document.getElementById("comp-llm-pattern-out");
    if (out && !wantPat && !wantStruct) out.textContent = `LLM: ${done.join(" · ")} — ②에서 확인하고 「후보 보기」`;
    if (wantToc || wantStruct) await _proposeBoundaries();
    else _refreshApplyState();
  } finally {
    if (run) run.disabled = false;
  }
}

/**
 * 4단 (D-117): 통계가 못 찾은 책 — LLM에 «시작 표지의 공통점»을 묻는다. 표본 행만 보내고,
 * 답은 정해진 종류로만 받으며, 전문에서 되풀이되는 것만 신호 목록에 들어온다(켤지는 사람이).
 */
async function _askLlmPatterns() {
  const out = document.getElementById("comp-llm-pattern-out");
  if (!_signalsCurrent()) {
    showToast("신호를 아직 세지 못했습니다.", "warning");
    return;
  }
  const llmSel = typeof getLlmModelSelection === "function" ? getLlmModelSelection("comp-llm-model-select") : {};
  if (out) out.textContent = "표본을 모델에 보내는 중…";
  try {
    const res = await fetch(`/api/documents/${encodeURIComponent(viewerState.docId)}/segmentation/signals/llm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        part_id: viewerState.partId,
        force_provider: llmSel.force_provider || null,
        force_model: llmSel.force_model || null,
        scope: document.getElementById("comp-llm-scope")?.value || "starts",
        reference_text: _llmReferenceText(),
      }),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.error || `HTTP ${res.status}`);
    signalState.llmAsked = true;
    const rows = d.signals || [];
    for (const r of rows) {
      const current = _signalRows();
      const existing = current.find((x) => x.toggle === r.toggle && x.value === r.value);
      // 발견된 접은 꼴과 LLM의 원문 어휘가 같은 ID여도 서로 덮어쓰지 않는다.
      const id = existing?.id || (current.some((x) => x.id === r.id) ? `manual:${r.toggle}:${r.value}` : r.id);
      if (!existing) signalState.manual.push({ ...r, id, manual: true });
      if (r.recommended) signalState.checked.add(id);
    }
    signalState.touched = signalState.touched || rows.length > 0;
    _renderSignals();
    if (out) {
      const said = (d.raw || []).map((p) => `${p.kind}:${p.value}`).filter((s) => !s.endsWith(":")).join(", ");
      const sent = d.sample_lines != null ? ` (보낸 표본 ${d.sample_lines}줄·${Number(d.sample_chars || 0).toLocaleString()}자)` : "";
      out.textContent = d.error
        ? `LLM 실패: ${d.error}`
        : rows.length
          ? `모델(${d.model || "?"})이 말한 ${said || "(없음)"} 중 전문에서 되풀이되는 ${rows.length}개를 목록에 넣었습니다${sent} — 「후보 보기」로 확인하세요`
          : `모델(${d.model || "?"})의 답 ${said || "(없음)"} 중 전문에서 넷 이상 되풀이되는 것이 없습니다${sent} — 표본을 넓혀 다시 묻거나 찍어 주세요`;
    }
  } catch (e) {
    if (out) out.textContent = `실패: ${e.message}`;
  }
}

/** «구조를 통째로 묻기»가 보낼 크기(행·글자·호출 수)를 미리 보인다 — 실행 게이트는 도구 층에(전역 규칙 11). */
async function _updateLlmStructureNote() {
  const note = document.getElementById("comp-llm-opt-structure-note");
  if (!note || !viewerState.docId || !viewerState.partId) return;
  note.textContent = "크기를 재는 중…";
  try {
    const res = await fetch(`/api/documents/${encodeURIComponent(viewerState.docId)}/segmentation/structure/llm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ part_id: viewerState.partId, dry_run: true }),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.error || `HTTP ${res.status}`);
    note.textContent = `권 전문 ${d.lines}행 · ${Number(d.chars).toLocaleString()}자 · 호출 ${d.calls}번`;
  } catch (e) {
    note.textContent = `크기 못 잼: ${e.message}`;
  }
}

/**
 * «구조를 통째로 묻기» (D-125): 권의 확정본 전문을 행 번호와 함께 보내 «새 글이 시작하는 행»을 받는다.
 * 모델은 위치를 만들지 않고 고르기만 한다 — 서버가 실제 행에 대조한 것만 온다. 답은 proposeState.llm에
 * 두고, _proposeBoundaries가 규칙 후보와 합쳐 ③에 세운다. 저장은 「적용」이 한다.
 */
async function _askLlmStructure() {
  const out = document.getElementById("comp-llm-pattern-out");
  const docId = viewerState.docId, partId = viewerState.partId;
  const llmSel = typeof getLlmModelSelection === "function" ? getLlmModelSelection("comp-llm-model-select") : {};
  if (out) out.textContent = "권 전문을 모델에 보내는 중…";
  try {
    const res = await fetch(`/api/documents/${encodeURIComponent(docId)}/segmentation/structure/llm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        part_id: partId,
        force_provider: llmSel.force_provider || null,
        force_model: llmSel.force_model || null,
        reference_text: _llmReferenceText(),
      }),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.error || `HTTP ${res.status}`);
    if (docId !== viewerState.docId || partId !== viewerState.partId) return; // 그 사이 다른 책으로 갔다
    const props = d.proposals || [];
    proposeState.llm = props.length ? { docId, partId, proposals: props, meta: d } : null;
    if (out) {
      const sent = `보낸 ${d.sent_lines}행·${Number(d.sent_chars || 0).toLocaleString()}자·${d.calls}번`;
      const fixed = d.title_fixed ? ` · 제목을 행 글자로 바꾼 것 ${d.title_fixed}` : "";
      const dropped = d.dropped ? ` · 실제 행이 아니라 버린 것 ${d.dropped}` : "";
      out.textContent = props.length
        ? `모델(${d.model || "?"})이 가리킨 ${d.said}자리 중 ${props.length}개가 실제 행과 맞아 ③에 «LLM 구조»로 섰습니다 (${sent}${fixed}${dropped})` +
          (d.error ? ` — 일부 실패: ${d.error}` : "")
        : d.error
          ? `LLM 실패: ${d.error} — 「모델」에서 다른 모델을 골라 다시 물으세요 (실측: 답 대신 영문 추론을 써 내려가는 모델이 있습니다)`
          : `모델(${d.model || "?"})이 가리킨 ${d.said}자리 중 실제 행과 맞는 것이 없습니다 (${sent})`;
    }
  } catch (e) {
    if (out) out.textContent = `실패: ${e.message}`;
  }
}

/** 이 후보를 모델이 «글의 시작»으로 가리켰는가 (D-125). */
function _isLlmProposal(p) {
  return (p.reasons || []).includes("llm:structure");
}

/**
 * 모델의 답을 규칙 후보와 합친다 (D-125). 입력: propose 응답·문헌·권. 출력: 없음(data를 고친다).
 * 같은 자리면 그 후보에 근거만 보태고(둘이 가리키면 확신도 0.8), 새 자리면 후보로 더한다.
 * 사람이 억제한 자리는 모델이 가리켜도 되살리지 않는다 — 억제는 사람의 결정이다.
 */
function _mergeLlmProposals(data, docId, partId) {
  const llm = proposeState.llm;
  if (!llm || llm.docId !== docId || llm.partId !== partId || !llm.proposals.length) return;
  const byKey = new Map(data.proposals.map((p) => [_propKey(p), p]));
  let added = 0, joined = 0;
  for (const p of llm.proposals) {
    const k = _propKey(p);
    const cur = byKey.get(k);
    if (cur) {
      if (!cur.reasons.includes("llm:structure")) cur.reasons.push("llm:structure");
      if (!cur.suppressed) {
        cur.accepted = true;
        cur.confidence = Math.max(cur.confidence || 0, 0.8);
      }
      joined++;
    } else {
      const copy = { ...p, reasons: [...p.reasons] };
      data.proposals.push(copy);
      byKey.set(k, copy);
      added++;
    }
  }
  data.proposals.sort((a, b) => a.page - b.page || a.line_index - b.line_index || (a.char_offset || 0) - (b.char_offset || 0));
  data.stats.llm = { added, joined };
}

/**
 * 목차에는 있으나 본문에서 대조 못 한 항목(D-122 덧붙임 2026-09-11). 입력: 상자·unmatched 목록. 출력: 없음.
 * 제목마다 «비슷한 행» 후보(서버 locate_title, 느슨한 유사도·순서 무시)를 접어 두고, 「여기서 시작」을 누르면
 * 그 자리가 ③의 후보로 선다(체크된 채, «목차·찾아 넣음»). 저장은 여전히 「적용」 — 자동으로 경계가 되지 않는다.
 */
function _renderUnmatchedToc(box, un) {
  box.style.display = un.length ? "" : "none";
  box.textContent = "";
  if (!un.length) return;
  const placed = new Set((proposeState.located?.proposals || []).map((p) => p.toc_index));
  const head = document.createElement("div");
  head.textContent = `목차에는 있으나 본문에서 못 찾음 (${un.length}) — 제목을 누르면 비슷한 행을 보입니다:`;
  box.appendChild(head);
  const chips = document.createElement("div");
  for (const u of un) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "comp-unmatched-chip" + (placed.has(u.index) ? " is-placed" : "") + (proposeState.unmatchedOpen === u.index ? " is-open" : "");
    b.textContent = u.title + (placed.has(u.index) ? " ✓" : "");
    b.title = placed.has(u.index) ? "③에 넣었습니다 — 다른 자리로 바꾸려면 다시 누르세요" : `비슷한 행 ${(u.near || []).length}개`;
    b.addEventListener("click", () => {
      proposeState.unmatchedOpen = proposeState.unmatchedOpen === u.index ? null : u.index;
      _renderUnmatchedToc(box, un);
    });
    chips.appendChild(b);
  }
  box.appendChild(chips);
  const open = un.find((u) => u.index === proposeState.unmatchedOpen);
  if (!open) return;
  const cands = document.createElement("div");
  cands.className = "comp-unmatched-cands";
  const near = open.near || [];
  if (!near.length) {
    const el = document.createElement("div");
    el.textContent = `「${open.title}」과 비슷한 행이 본문에 없습니다 — OCR이 제목을 다르게 읽었거나 이 권에 없는 글입니다. 사이드바 「경계 넣기」로 직접 넣을 수 있습니다.`;
    cands.appendChild(el);
  }
  for (const c of near) {
    const row = document.createElement("div");
    row.className = "comp-unmatched-cand";
    const where = document.createElement("span");
    where.className = "prop-goto";
    where.textContent = `${c.page}쪽 ${c.line_index + 1}행`;
    where.title = "누르면 그 쪽으로 이동";
    where.addEventListener("click", () => {
      if (typeof goToPage === "function") goToPage(c.page);
    });
    const txt = document.createElement("span");
    txt.textContent = `「${c.text}」 ${Math.round(c.score * 100)}%`;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "text-btn text-btn-sm";
    btn.textContent = "여기서 시작";
    btn.title = `이 행을 「${open.title}」의 시작으로 ③에 넣습니다(체크된 채). 저장은 「적용」`;
    btn.addEventListener("click", () => _addLocatedProposal(open, c));
    row.append(where, txt, btn);
    cands.appendChild(row);
  }
  box.appendChild(cands);
}

/** 못 찾은 목차 항목 하나를 고른 행에 놓는다. 입력: 항목·후보 행. 출력: 없음(③을 다시 그린다). */
function _addLocatedProposal(entry, cand) {
  const docId = viewerState.docId, partId = viewerState.partId;
  if (!proposeState.located || proposeState.located.docId !== docId || proposeState.located.partId !== partId)
    proposeState.located = { docId, partId, proposals: [] };
  const level = entry.level || 2;
  const mine = {
    page: cand.page, line_index: cand.line_index, char_offset: 0, title: entry.title, level,
    role: level <= 1 ? "container" : "article", kind: "", reasons: ["toc:located"], confidence: 0.6,
    accepted: true, suppressed: false, toc_index: entry.index,
  };
  // 같은 항목은 한 자리만 — 전에 넣은 자리는 표지를 떼고(규칙 후보이기도 하면 남긴다) 새 자리로
  proposeState.located.proposals = proposeState.located.proposals.filter((p) => p.toc_index !== entry.index).concat([mine]);
  proposeState.unmatchedOpen = null;
  const data = proposeState.data;
  if (data) {
    data.proposals = data.proposals.filter((p) => !(p.toc_index === entry.index && p.reasons.length === 1 && p.reasons[0] === "toc:located"));
    for (const p of data.proposals) {
      if (p.toc_index === entry.index) {
        p.reasons = p.reasons.filter((r) => r !== "toc:located");
        delete p.toc_index;
      }
    }
    _mergeLocatedProposals(data, docId, partId);
    proposeState.checked.add(_propKey(mine));
    _renderProposals();
    _refreshApplyState();
  }
  showToast(`「${entry.title}」을(를) ${cand.page}쪽 ${cand.line_index + 1}행에서 시작하는 후보로 넣었습니다 — 저장은 「적용」`, "success");
}

/** 사람이 찾아 넣은 목차 자리를 후보 목록에 합친다(다시 세어도 남는다). 입력: propose 응답·문헌·권. */
function _mergeLocatedProposals(data, docId, partId) {
  const loc = proposeState.located;
  if (!loc || loc.docId !== docId || loc.partId !== partId || !loc.proposals.length) return;
  const byKey = new Map(data.proposals.map((p) => [_propKey(p), p]));
  for (const p of loc.proposals) {
    const k = _propKey(p);
    const cur = byKey.get(k);
    if (cur) {
      if (!cur.reasons.includes("toc:located")) cur.reasons.push("toc:located");
      cur.toc_index = p.toc_index;
      if (!cur.suppressed) cur.accepted = true;
      if (!cur.title) cur.title = p.title;
    } else {
      const copy = { ...p, reasons: [...p.reasons] };
      data.proposals.push(copy);
      byKey.set(k, copy);
    }
  }
  data.proposals.sort((a, b) => a.page - b.page || a.line_index - b.line_index || (a.char_offset || 0) - (b.char_offset || 0));
}

/**
 * ①②③ 단계 접기(사용자 요청 2026-09-11). 머리를 누르면 접히고, 접힌 것은 이 브라우저가 기억한다(localStorage).
 * 머리 안의 단추(↻ 등)는 접지 않는다. 처음에는 다 펼쳐져 있다 — 흐름을 처음 보는 사람이 세 단계를 다 봐야 한다.
 */
function _bindStepFolding() {
  const KEY = "ctb.comp.collapsed";
  let saved = [];
  try {
    saved = JSON.parse(localStorage.getItem(KEY) || "[]");
  } catch (_) {
    saved = [];
  }
  for (const sec of document.querySelectorAll("#comp-propose-panel .comp-step")) {
    const head = sec.querySelector(".comp-step-head");
    if (!head) continue;
    if (saved.includes(sec.id)) sec.classList.add("is-collapsed");
    head.addEventListener("click", (ev) => {
      if (ev.target.closest("button, input, select, label, a")) return; // 머리 안의 단추는 제 일을 한다
      sec.classList.toggle("is-collapsed");
      const now = [...document.querySelectorAll("#comp-propose-panel .comp-step.is-collapsed")].map((s) => s.id);
      try {
        localStorage.setItem(KEY, JSON.stringify(now));
      } catch (_) {
        /* 저장 못 해도 접기는 된다 */
      }
    });
  }
}

/** 서버가 센 행 + 사람이 더한 행. 렌더·규칙 조립이 같은 목록을 본다. */
function _signalRows() {
  const rows = signalState.data ? signalState.data.signals.slice() : [];
  return rows.concat(signalState.manual);
}

/**
 * 전문에서 신호를 센다(규칙만, 저장 없음). 체크 상태는 저장된 규칙이 있으면 그것, 없으면 권고.
 *
 * 왜 저장된 규칙을 우선하는가: 사람이 한 번 고른 것을 다음에 열 때 권고로 되돌리면 안 된다.
 * 저장된 어휘가 이번 셈에 없으면(표본이 바뀌었거나 손으로 넣은 것) 「손으로 넣음」 행으로 남긴다.
 */
async function _loadSignals() {
  const list = document.getElementById("comp-signals-list");
  const summary = document.getElementById("comp-signals-summary");
  if (!list) return;
  list.innerHTML = '<div class="placeholder">전문을 세는 중…</div>';
  signalState.data = null;
  signalState.manual = [];
  signalState.draft = null;
  signalState.touched = false;
  const seq = ++signalState.seq;
  const docId = viewerState.docId;
  const partId = viewerState.partId;
  try {
    const res = await fetch(`/api/documents/${encodeURIComponent(docId)}/segmentation/signals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ part_id: partId, toc_pages: _tocPagesFromInput() }),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.error || `HTTP ${res.status}`);
    if (seq !== signalState.seq) return; // 그 사이 다른 문헌·권으로 다시 불렀다
    signalState.data = d;
    signalState.docId = docId;
    signalState.partId = partId;
    const saved = d.saved_rules;
    const ids = new Set(d.signals.map((s) => s.id));
    // «저장된 설정»은 origin이 있을 때만이 아니다 — D-116 전에 저장한 표제 어휘·스위치도 그렇다
    // (서버 rules_are_empty와 같은 판정). 없으면 서버가 권고에서 만든 recommended_rules를 따른다 —
    // 주 신호를 하나도 권고하지 못한 표본에서 서버는 주 신호를 기본값(켬)으로 두는데, 화면이
    // recommended 표시만 보고 다 끄면 「전부 적용」이 «적용할 구간이 없습니다»로 끝난다(Codex 지적).
    // 서버 rules_are_empty와 같은 판정 — indent_alone만 켠 저장본도 저장본이다(Codex 지적)
    const hasSaved = !!saved && !!(saved.origin || saved.indent_alone || _LIST_TOGGLES.some((t) => saved[t]?.length) || Object.keys(saved.signals || {}).length);
    const base = hasSaved ? saved : d.recommended_rules;
    if (base) _checkFromRules(base);
    else signalState.checked = new Set(d.signals.filter((s) => s.recommended).map((s) => s.id));
    signalState.touched = hasSaved && saved.origin === "manual";
    if (summary) {
      const src = d.source || {};
      const where = src.l2_pages
        ? `확정본 ${src.l4_pages}쪽 + OCR ${src.l2_pages}쪽`
        : `확정본 ${src.l4_pages}쪽`;
      summary.textContent = `${d.lines}행 (${where}) · ` + (hasSaved ? (saved.origin === "manual" || !saved.origin ? "저장된 설정(손봄)" : "저장된 설정(자동 도출)") : "아직 저장 안 됨 — 권고 상태");
    }
    signalState.llmAsked = false;
    _renderSignals();
    _renderVerdict();
    // 목차 줄 — 층계 1단의 결과를 그대로 적는다(목차 감지 라우트를 또 부르지 않는다)
    const tocSummary = document.getElementById("comp-toc-summary");
    if (tocSummary && d.toc) {
      tocSummary.textContent = `${d.toc.pages.join(",")}쪽 · ${d.toc.entries}항목 중 ${d.toc.matched} 대조` + (d.toc.decisive ? " (규약)" : " (약함)");
    }
  } catch (e) {
    list.innerHTML = `<div class="placeholder">신호를 세지 못했습니다: ${e.message}</div>`;
    const text = document.getElementById("comp-verdict-text");
    if (text) text.textContent = `전문을 세지 못했습니다: ${e.message}`;
  }
}

/**
 * 규칙(전체) → 화면의 체크 상태·손으로 넣은 행·참고 칸. 입력: 규칙. 출력: 없음.
 *
 * 처음 읽을 때(저장된 규칙 또는 권고)와 「말로 넣기」가 돌려준 규칙이 같은 길을 지난다(D-122).
 * 행은 «칸+값»으로 맞춘다 — 같은 글자라도 어휘(head_words)와 접은 꼴(head_templates)은 다른 규칙이다.
 */
function _checkFromRules(base) {
  const d = signalState.data;
  if (!d || !base) return;
  const ids = new Set(d.signals.map((s) => s.id));
  signalState.checked = new Set();
  const listed = new Map(); // toggle → 목록에 있는 value들
  const note = (toggle, value) => {
    if (!listed.has(toggle)) listed.set(toggle, new Set());
    listed.get(toggle).add(value);
  };
  for (const s of d.signals) {
    if (s.toggle.startsWith("signals.")) {
      if (base.signals?.[s.toggle.slice(8)] !== false) signalState.checked.add(s.id);
    } else if (_LIST_TOGGLES.includes(s.toggle)) {
      note(s.toggle, s.value);
      if ((base[s.toggle] || []).includes(s.value)) signalState.checked.add(s.id);
    } else if (s.toggle === "indent_alone") {
      if (base.indent_alone) signalState.checked.add(s.id);
    }
  }
  // 손으로 넣은 행: 규칙 목록에 든 것은 아래서 다시 만들고(켜진 채), 안 든 것(꺼 둔 후보)은 그대로 둔다.
  // 스위치 행은 규칙에서 다시 만든다
  signalState.manual = signalState.manual.filter(
    (m) => !m.toggle.startsWith("signals.") && !(_LIST_TOGGLES.includes(m.toggle) && (base[m.toggle] || []).includes(m.value)),
  );
  for (const m of signalState.manual) if (_LIST_TOGGLES.includes(m.toggle)) note(m.toggle, m.value);
  // 규칙에는 있는데 이번 셈에 없는 값 — 손으로 넣은 것이거나 표본이 바뀐 것. 행으로 남긴다
  const prefix = { title_words: "tail", head_words: "head", symbols: "sym", head_templates: "head", tail_templates: "tail" };
  for (const toggle of _LIST_TOGGLES) {
    for (const w of base[toggle] || []) {
      if (listed.get(toggle)?.has(w)) continue;
      const id = `manual:${toggle}:${w}`;
      signalState.manual.push({ id, toggle, value: w, label: `${_signalLabel(`${prefix[toggle]}:${w}`)} (손으로 넣음)`, manual: true, group: toggle === "symbols" ? "visual" : "primary" });
      note(toggle, w);
      signalState.checked.add(id);
    }
  }
  // 목록에 없는데 규칙에서 꺼 둔 스위치(예: bbox가 없어 세지 못한 내려쓰기) — 행으로 보여 켤 수 있게 한다.
  // 안 보이면 저장할 때 조용히 되살아난다(Codex 지적)
  for (const [k, on] of Object.entries(base.signals || {})) {
    if (on === false && !ids.has(k) && _SIGNAL_LABELS[k]) {
      signalState.manual.push({ id: k, toggle: `signals.${k}`, label: `${_SIGNAL_LABELS[k]} (이번 셈에는 없음 — 꺼 둠)`, manual: true, group: ["short_line", "after_short", "indent"].includes(k) ? "aux" : "primary" });
    }
  }
  signalState.draft = base;
  _rulesToForm(base);
}

/** 저장이 끝났다는 것을 요약 줄이 말하게 한다 — 「적용」 뒤에도 «아직 저장 안 됨»이 남으면 안 된다. */
function _markRulesSaved(saved) {
  if (signalState.data) signalState.data.saved_rules = saved;
  signalState.draft = saved;
  const summary = document.getElementById("comp-signals-summary");
  if (!summary || !signalState.data) return;
  const src = signalState.data.source || {};
  const where = src.l2_pages ? `확정본 ${src.l4_pages}쪽 + OCR ${src.l2_pages}쪽` : `확정본 ${src.l4_pages}쪽`;
  summary.textContent =
    `${signalState.data.lines}행 (${where}) · ` +
    (saved?.origin === "manual" ? "저장된 설정(손봄)" : "저장된 설정(자동 도출)");
}

function _renderSignals() {
  const list = document.getElementById("comp-signals-list");
  if (!list) return;
  list.innerHTML = "";
  // 주 신호(혼자 후보를 만드는 것)를 앞에, 보조를 뒤에 — 점수 순서대로 섞이면 «무엇이 규약인가»가 안 보인다
  const order = { visual: 0, primary: 1, aux: 2 };
  const rows = _signalRows().sort((a, b) => (order[a.group] ?? 1) - (order[b.group] ?? 1));
  if (!rows.length) {
    list.innerHTML = '<div class="placeholder">되풀이되는 표지를 찾지 못했습니다. 어휘를 직접 더하거나 목차를 쓰세요.</div>';
  }
  const maxScore = Math.max(0.01, ...rows.map((r) => r.score || 0));
  // 켠 것·손으로 넣은 것·권고된 것만 펼쳐 둔다. 나머지는 «센 근거»이지 규칙이 아니므로 접는다 —
  // 종류를 없앤 뒤(D-119) 발견기가 스무 줄 넘게 세는 책이 있어 답이 묻혔다(2026-09-08 지적).
  const open = rows.filter((r) => signalState.checked.has(r.id) || r.manual || r.recommended);
  const folded = rows.filter((r) => !open.includes(r));
  for (const r of open) list.appendChild(_signalRowEl(r, maxScore));
  if (folded.length) {
    const more = document.createElement("details");
    more.className = "comp-sig-more";
    more.open = !!signalState.showAll;
    more.addEventListener("toggle", () => { signalState.showAll = more.open; });
    const sum = document.createElement("summary");
    sum.textContent = `센 것 ${folded.length}줄 더 — 점수가 낮아 켜지 않았습니다`;
    sum.title = "이 책에서 되풀이되기는 하지만 규약으로 보기엔 약한 것들입니다. 켜면 규칙이 됩니다";
    more.appendChild(sum);
    for (const r of folded) more.appendChild(_signalRowEl(r, maxScore));
    list.appendChild(more);
  }
  const d = signalState.data;
  if (d && (d.dropped?.length || d.furniture?.length)) {
    const note = document.createElement("div");
    note.className = "comp-sig-dropped";
    const parts = [];
    // 화면은 좁다 — 수만 말하고 자세한 것은 툴팁으로 보인다(2026-09-09 사용자 지적)
    const byWhy = { page_furniture: [], date_tail: [] };
    for (const x of d.dropped || []) (byWhy[x.why] || (byWhy[x.why] = [])).push(`${x.label} ${x.count}회`);
    const detail = [];
    if (byWhy.page_furniture.length) {
      parts.push(`판심 문구 ${byWhy.page_furniture.length}가지`);
      detail.push("쪽마다 같은 자리라 뺀 것: " + byWhy.page_furniture.join(" · "));
    }
    if (byWhy.date_tail.length) {
      parts.push(`날짜뿐 ${byWhy.date_tail.length}가지`);
      detail.push("날짜뿐이라 뺀 것: " + byWhy.date_tail.join(" · "));
    }
    if (d.furniture?.length) detail.push("판심·엽수로 본 행: " + d.furniture.slice(0, 8).join(" · "));
    if (d.page_format?.summary) {
      parts.push(d.page_format.summary); // 「판심 24 · 두주 83 · 반엽 10행」
      const s = d.page_format.samples || {};
      if (s.pansim?.length) detail.push("판심 자리: " + s.pansim.join(" · "));
      if (s.margin?.length) detail.push("두주·난외: " + s.margin.join(" · "));
    }
    if (d.page_format?.catalog?.summary) parts.push(d.page_format.catalog.summary);
    note.textContent = parts.length ? "뺀 것 — " + parts.join(" · ") : "";
    note.title = detail.length
      ? detail.join(String.fromCharCode(10))
      : "종이의 규약(판심·엽수·인쇄소 도장)은 글의 시작이 아니므로 후보에서 뺍니다";
    list.appendChild(note);
  }
}

/** 신호 한 줄을 만든다. 입력: 신호 행·점수 최댓값. 출력: <div>. 목적: 펼친 줄과 접힌 줄이 같게. */
function _signalRowEl(r, maxScore) {
  const row = document.createElement("div");
  row.className = "comp-sig-row" + (r.group === "aux" ? " is-aux" : "") + (r.manual ? " is-manual" : "");
  const main = document.createElement("label");
  main.className = "comp-sig-main";
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.checked = signalState.checked.has(r.id);
  cb.addEventListener("change", () => {
    if (cb.checked) signalState.checked.add(r.id);
    else signalState.checked.delete(r.id);
    signalState.touched = true;
  });
  const label = document.createElement("span");
  label.className = "comp-sig-label";
  label.textContent = r.label || _signalLabel(r.id);
  const count = document.createElement("span");
  count.className = "comp-sig-count";
  count.textContent = r.count != null ? `${r.count}회` : "";
  main.appendChild(cb);
  main.appendChild(label);
  main.appendChild(count);
  if (r.marker) {
    const mk = document.createElement("span");
    mk.className = "comp-sig-aux";
    mk.textContent = "되풀이";
    mk.title = "행들이 대부분 같은 글이거나 앞 날짜를 되적습니다 — 판권·두주 같은 종이의 규약일 수 있어 권고하지 않습니다";
    main.appendChild(mk);
  }
  if (r.group === "aux") {
    const aux = document.createElement("span");
    aux.className = "comp-sig-aux";
    aux.textContent = "보조";
    aux.title = "혼자서는 후보를 만들지 않고, 날짜·어휘가 있는 행의 신뢰도만 올립니다";
    main.appendChild(aux);
  }
  row.appendChild(main);
  if (r.score != null) {
    const bar = document.createElement("span");
    bar.className = "comp-sig-bar";
    bar.title = `점수 ${r.score} — 횟수 × 간격의 고름` + (r.chain != null ? ` × 날짜 사슬 ${r.chain}` : "");
    const fill = document.createElement("span");
    fill.style.width = `${Math.round((r.score / maxScore) * 100)}%`;
    bar.appendChild(fill);
    row.appendChild(bar);
  }
  if (r.examples && r.examples.length) {
    const ex = document.createElement("span");
    ex.className = "comp-sig-ex";
    ex.textContent = r.examples[0];
    ex.title = r.examples.join("\n");
    row.appendChild(ex);
  }
  if (r.manual) {
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "comp-sig-remove";
    rm.textContent = "×";
    rm.title = "이 어휘 행을 지웁니다";
    rm.addEventListener("click", () => {
      signalState.manual = signalState.manual.filter((m) => m.id !== r.id);
      signalState.checked.delete(r.id);
      // 목록 밖 스위치 행을 지우면 «저장에서 꺼 둠»도 지운다 — 기본(켬)으로 돌아간다
      if (r.toggle.startsWith("signals.") && signalState.data?.saved_rules?.signals) delete signalState.data.saved_rules.signals[r.id];
      signalState.touched = true;
      _renderSignals();
      _refreshApplyState();
    });
    row.appendChild(rm);
  }
  return row;
}

/**
 * 입력: 후보 ID·규칙 칸·표시명·값. 출력: 없음(행과 체크 상태 갱신).
 * 목적: 같은 칸·값은 재사용하되 어휘와 접은 꼴의 ID 충돌로 저장값이 사라지지 않게 한다.
 */
function _addWordRow(id, toggle, label, value) {
  value = value ?? id.slice(id.indexOf(":") + 1);
  const rows = _signalRows();
  const existing = rows.find((r) => r.toggle === toggle && r.value === value);
  if (existing) id = existing.id;
  else {
    if (rows.some((r) => r.id === id)) id = `manual:${toggle}:${value}`;
    signalState.manual.push({ id, toggle, label, value, manual: true, group: toggle === "symbols" ? "visual" : "primary" });
  }
  signalState.checked.add(id);
  signalState.touched = true;
  _renderSignals();
  _refreshApplyState();
}

function _addManualWord() {
  const input = document.getElementById("comp-signals-add-word");
  if (!input) return;
  let w = input.value.trim();
  if (!w) return;
  if (!signalState.data) {
    showToast("신호를 아직 세지 못했습니다.", "warning");
    return;
  }
  if (w.startsWith("^")) {
    w = w.slice(1).trim();
    if (w) _addWordRow(`head:${w}`, "head_words", `행 첫머리 「${w}」 (손으로 넣음)`, w);
  } else if (w.length === 1 && !/[\p{L}\p{N}]/u.test(w)) {
    _addWordRow(`sym:${w}`, "symbols", `기호 「${w}」 (손으로 넣음)`, w);
  } else {
    _addWordRow(`tail:${w}`, "title_words", `행 끝 「${w}」 (손으로 넣음)`, w);
  }
  input.value = "";
}

// 후보의 자리 키 — 체크·깊이·역할·선택은 index가 아니라 이것으로 든다. 규칙을 고쳐 다시 세어도
// 같은 자리는 같은 후보라 손본 것이 남는다(D-122, Codex 지적)
const proposeState = {
  data: null, // /segmentation/propose 응답
  docId: null,
  partId: null,
  seq: 0, // 요청 세대 — 늦게 온 옛 응답·다른 문헌의 응답은 버린다(Codex 지적)
  rulesDigest: null, // 이 후보를 셀 때 **실제로 보낸** 입력(규칙 + 목차 쪽)의 JSON — 지금 ②와 다르면 낡은 것
  tocRaw: null, // 목차 쪽 칸의 값(목차를 찾을 때의 것) — 바뀌면 다시 찾는다
  baseline: null, // Map(자리 키 → 후보) — 저장된 규칙(없으면 권고)으로 센 채택 후보. «바뀐 것»의 기준
  checked: new Set(), // 경계가 될 후보(자리 키)
  selected: new Set(), // 한꺼번에 고칠 후보(자리 키) — 체크와 다른 상태다
  anchor: null, // Shift 범위의 시작(자리 키)
  visible: [], // 지금 그려진 자리 키(표시 순서) — Shift 범위는 이 순서를 따른다
  showRejected: false, // 문턱 아래 후보도 보이는가
  levels: new Map(), // 자리 키 → 사람이 바꾼 깊이
  roles: new Map(), // 자리 키 → 사람이 바꾼 역할
  toc: null, // {pages, entries} — 목차 감지로 확인한 것. null이면 서버가 규칙으로 자동
  llm: null, // {docId, partId, proposals, meta} — «구조를 통째로 묻기»의 답(D-125). 규칙 후보와 합쳐 ③에 선다
  located: null, // {docId, partId, proposals} — 목차에는 있으나 대조 못 한 항목을 사람이 찾아 넣은 자리(D-122 덧붙임)
  unmatchedOpen: null, // 펼쳐 둔 못 찾은 항목의 index
  lastClicked: null, // 마지막으로 누른 행(자리 키) — 도구가 이 행 아래에 뜬다(D-122 덧붙임 2)
  baselineKind: "rules", // «바뀐 것»의 기준 — "boundaries"(저장된 경계) 또는 "rules"(저장된 규칙으로 센 후보)
};
const flowState = { loading: false }; // ①이 세는 중인가 — 겹쳐 시작하지 않는다

function _tocPagesFromInput() {
  const raw = document.getElementById("comp-toc-pages")?.value || "";
  const pages = raw.split(/[,，\s]+/).map((x) => Number(x)).filter((n) => Number.isInteger(n) && n > 0);
  return pages.length ? pages : null;
}

/**
 * 목차 쪽을 판별하고 항목을 뽑는다 (D-089). 규칙 또는 LLM. 결과는 다음 제안에 신호로 들어간다.
 */
async function _detectToc(useLlm) {
  if (!viewerState.docId || !viewerState.partId) {
    showToast("사이드바에서 문헌과 권을 먼저 고르세요.", "warning");
    return null;
  }
  const summary = document.getElementById("comp-toc-summary");
  if (summary) summary.textContent = useLlm ? "목차: LLM이 읽는 중…" : "목차: 규칙으로 찾는 중…";
  proposeState.tocRaw = document.getElementById("comp-toc-pages")?.value || "";
  // 결과 요약에 «규칙»인지 «LLM»인지 남긴다 — 제안 목록의 「목차 …」 근거가 어디서 왔는지 보이도록
  proposeState.tocSource = useLlm ? "LLM" : "규칙";
  try {
    const llmSel =
      typeof getLlmModelSelection === "function"
        ? getLlmModelSelection("comp-llm-model-select")
        : { force_provider: null, force_model: null };
    const res = await fetch(`/api/documents/${encodeURIComponent(viewerState.docId)}/segmentation/toc`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        part_id: viewerState.partId,
        toc_pages: _tocPagesFromInput(),
        use_llm: !!useLlm,
        reference_text: useLlm ? _llmReferenceText() : null,
        force_provider: useLlm ? llmSel.force_provider : null,
        force_model: useLlm ? llmSel.force_model : null,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    if (!data.toc_pages.length) {
      proposeState.toc = null;
      if (summary) summary.textContent = "없음 (쪽 번호를 직접 넣어 보세요)";
      return null;
    }
    proposeState.toc = { pages: data.toc_pages, entries: data.entries };
    if (summary && (useLlm || !summary.textContent || summary.textContent === "찾는 중…"))
      summary.textContent = `${data.toc_pages.join(",")}쪽 · ${data.entries.length}항목 (${proposeState.tocSource})`;
    const input = document.getElementById("comp-toc-pages");
    if (input && !input.value) {
      input.value = data.toc_pages.join(",");
      proposeState.tocRaw = input.value;
    }
    if (data.meta?.error) showToast(`LLM 실패로 규칙 추출을 썼습니다: ${data.meta.error}`, "warning");
    return proposeState.toc;
  } catch (e) {
    if (summary) summary.textContent = `실패 — ${e.message}`;
    return null;
  }
}

/**
 * 신호 목록의 체크 상태 + 참고·억제 칸 → 이 문헌의 segmentation_rules (D-116).
 *
 * 스위치 신호(날짜·○권점·卷頭·짧은 행·행갈음·내려쓰기)는 signals.*로, 어휘 행은
 * title_words·head_words로 간다. 목록에 없는 스위치(예: bbox가 없어 세지 못한 내려쓰기)는
 * 적지 않는다 — 빠진 키는 켜진 것이라(normalize_rules) L2가 생기면 저절로 살아난다.
 * origin: 권고 그대로면 "induced", 사람이 하나라도 바꿨으면 "manual".
 */
function _rulesFromForm() {
  const suppress = (document.getElementById("comp-rules-suppress")?.value || "")
    .split("\n")
    .map((w) => w.trim())
    .filter(Boolean);
  const maxChars = Number(document.getElementById("comp-rules-maxchars")?.value || 14);
  const reference = _llmReferenceText(); // ①의 글 — 해제·아는 것이 함께 저장된다
  // 바탕은 초안 규칙(없으면 저장본) — 목록에 없는 스위치·min_confidence·옛 판심 목록을 잃지 않는다.
  // use_date·use_layout(옛 굵은 스위치)은 버린다: 이제 signals가 낱낱이 적히고, 남겨 두면
  // normalize_rules가 그것으로 하위 스위치를 다시 끈다.
  const saved = signalState.draft || signalState.data?.saved_rules || {};
  const signals = { ...(saved.signals || {}) };
  const lists = Object.fromEntries(_LIST_TOGGLES.map((t) => [t, []]));
  let indent_alone = false;
  let touched = signalState.touched;
  for (const row of _signalRows()) {
    const on = signalState.checked.has(row.id);
    if (row.toggle.startsWith("signals.")) signals[row.toggle.slice(8)] = on;
    else if (on && _LIST_TOGGLES.includes(row.toggle) && row.value && !lists[row.toggle].includes(row.value)) lists[row.toggle].push(row.value);
    else if (on && row.toggle === "indent_alone") indent_alone = true;
    if (row.manual || on !== !!row.recommended) touched = true;
  }
  signals.toc = document.getElementById("comp-toc-use")?.checked !== false; // 목차 줄 = signals.toc (D-122)
  const induced = signalState.data?.furniture || [];
  const furniture = [...new Set([...(saved.furniture || []), ...induced])];
  const { use_date, use_layout, origin, ...rest } = saved; // eslint-disable-line no-unused-vars
  return {
    ...rest,
    signals,
    ...lists,
    indent_alone,
    furniture,
    suppress,
    max_title_chars: maxChars,
    reference_text: reference,
    toc_llm: !!document.getElementById("comp-toc-llm")?.checked,
    origin: touched ? "manual" : "induced",
  };
}

function _rulesToForm(rules) {
  const s = document.getElementById("comp-rules-suppress");
  const m = document.getElementById("comp-rules-maxchars");
  if (s) s.value = (rules?.suppress || []).join("\n");
  const tocLlm = document.getElementById("comp-toc-llm");
  if (tocLlm && rules && typeof rules.toc_llm === "boolean") tocLlm.checked = rules.toc_llm;
  const mark = document.getElementById("comp-toc-llm-mark");
  if (mark) mark.hidden = !(tocLlm && tocLlm.checked);
  const tocUse = document.getElementById("comp-toc-use");
  if (tocUse && rules) tocUse.checked = rules.signals?.toc !== false; // 안 적힌 스위치는 켜진 것
  if (m) m.value = rules?.max_title_chars || 14;
  // ①의 글: 저장된 reference_text를 넣는다 — 단 이 문헌에서 사람이 이미 쓰고 있는 글은 덮지 않는다
  // (규칙을 다시 읽는 일은 「권고대로」·적용 뒤에도 일어난다). 다른 문헌으로 갔으면 그 문헌의 것으로.
  const r = document.getElementById("comp-llm-say");
  if (r) {
    const saved = rules?.reference_text || "";
    const tag = `${viewerState.docId}/${viewerState.partId}`;
    if (signalState.refTag !== tag || !r.value.trim() || r.value === signalState.lastReference) r.value = saved;
    signalState.refTag = tag;
    signalState.lastReference = saved;
    _updateReferenceCount();
    if (!r._countBound) {
      r.addEventListener("input", _updateReferenceCount);
      r._countBound = true;
    }
  }
}

/**
 * 해제 글자수를 알려 준다. 길면 «골라서 넘긴다»는 것도 함께.
 *
 * 왜 필요한가: 한국고전종합DB 해제는 2만 자가 넘는다(운양집 23,894자 실측). 통째로 붙여
 * 넣는 것이 맞는데, 그러면 «너무 길어서 잘리지 않나»가 걱정된다. 저장은 통째로 하고
 * 프롬프트에 넣을 때만 권별 서술을 골라 8,000자로 간추린다는 것을 여기서 알린다.
 */
function _updateReferenceCount() {
  const r = document.getElementById("comp-llm-say");
  const out = document.getElementById("comp-say-count");
  if (!r || !out) return;
  const n = r.value.length;
  if (!n) {
    out.textContent = "";
  } else if (n <= 8000) {
    out.textContent = `${n.toLocaleString()}자 · 저장은 「적용」`;
  } else {
    out.textContent = `${n.toLocaleString()}자 — 통째로 저장하고, 모델에는 권별 내용이 있는 데를 골라 넘깁니다 · 저장은 「적용」`;
  }
}

/**
 * «지금 경계» — 이미 저장된 경계를 편성 탭에도 띄운다.
 *
 * 왜 필요한가: 편성 탭을 열면 「경계 제안」을 누르기 전까지 화면이 비어 있었다. 저장된 것은
 * 사이드바 「내용」에만 있어서, 양쪽이 어긋나 보이고 «매번 새로 제안해서 적용해야 하나»로
 * 읽혔다(사용자 지적 2026-09-04). 제안은 «새로 훑어 보는 것»이고, 이미 한 일은 여기 있다.
 *
 * 사이드바와 같은 것을 가리킨다 — 행을 누르면 같은 단위가 골라지고(unit-selected) 그 쪽으로 간다.
 */
async function _renderCurrentBoundaries() {
  const list = document.getElementById("comp-current-list");
  const stats = document.getElementById("comp-current-stats");
  if (!list) return;
  if (!viewerState.docId || !viewerState.partId) {
    list.innerHTML = '<div class="placeholder">문헌과 권을 고르면 지금 경계가 보입니다.</div>';
    if (stats) stats.textContent = "";
    return;
  }
  try {
    const q = `part_id=${encodeURIComponent(viewerState.partId)}`;
    const res = await fetch(
      `/api/documents/${encodeURIComponent(viewerState.docId)}/boundaries?${q}`,
    );
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    const rows = (data.boundaries || []).filter((b) => b.status !== "deprecated");
    compState.currentBoundaries = rows;
    const roleName = { container: "묶음", article: "기사", fragment: "조각" };
    const byRole = rows.reduce((a, b) => {
      const r = b.role || "article";
      a[r] = (a[r] || 0) + 1;
      return a;
    }, {});
    if (stats) {
      stats.textContent = rows.length
        ? `${rows.length}개 — ` +
          ["container", "article", "fragment"]
            .filter((r) => byRole[r])
            .map((r) => `${roleName[r]} ${byRole[r]}`)
            .join(" · ")
        : "";
    }
    list.innerHTML = "";
    if (!rows.length) {
      list.innerHTML =
        '<div class="placeholder">아직 경계가 없습니다. 아래 ①②③으로 세우거나, 사이드바 「내용」의 «＋ 경계 넣기»로 첫 경계를 놓으세요.</div>';
      return;
    }
    const selected = typeof currentUnitId === "function" ? currentUnitId() : null;
    for (const b of rows) {
      const row = document.createElement("div");
      row.className = "comp-cur-row" + (b.id === selected ? " is-selected" : "");
      row.dataset.unitId = b.id;
      const role = b.role || "article";
      const title = document.createElement("span");
      title.className = "comp-cur-title";
      const mark = { container: "▣ ", article: "", fragment: "· " }[role] || "";
      const stale = b.anchor_status === "stale";
      title.textContent = `${stale ? "⚠ " : ""}${mark}${b.title || "(제목 없음)"}`;
      if (stale) title.classList.add("comp-cur-stale");
      const meta = document.createElement("span");
      meta.className = "comp-cur-meta";
      const p0 = b.start ? b.start.page : null;
      const p1 = b.end ? b.end.page : null;
      const pages = p0 == null ? "" : p1 && p1 !== p0 ? `${p0}~${p1}쪽` : `${p0}쪽`;
      meta.textContent = `${roleName[role]}${b.role_estimated ? "(추정)" : ""} · ${b.level}단 · ${pages}`;
      if (b.role_estimated) meta.classList.add("is-estimated");
      row.appendChild(title);
      row.appendChild(meta);
      row.title = stale
        ? "확정본이 바뀐 뒤 자리를 못 찾았습니다 — 사이드바 「내용」에서 ▲▼로 옮겨 주세요"
        : "누르면 그 기사로 갑니다 (사이드바 「내용」과 같은 선택)";
      row.addEventListener("click", () => {
        // 사이드바와 같은 것을 가리킨다 — 트리 행을 눌렀을 때와 똑같이 동작한다
        const tree = document.querySelector(
          `#contents-tree .contents-block[data-block-id="${CSS.escape(b.id)}"]`,
        );
        if (tree) tree.click();
        list.querySelectorAll(".comp-cur-row.is-selected").forEach((el) => {
          el.classList.remove("is-selected");
        });
        row.classList.add("is-selected");
      });
      list.appendChild(row);
    }
  } catch (e) {
    list.innerHTML = `<div class="placeholder">지금 경계를 읽지 못했습니다: ${e.message}</div>`;
  }
}

/**
 * 편성 흐름의 입구 (D-116·D-122) — 탭을 열면 스스로 돈다. 단추가 아니다.
 *
 * 순서: 전문에서 신호를 센다(규칙만) → 목차 쪽을 찾는다(규칙만) → 저장된 규칙(없으면 권고)으로
 * 후보를 보인다. 아무것도 저장하지 않는다 — 저장은 ③「적용」 한 곳이다.
 * 입력: force(같은 문헌·권이어도 다시 셀 것인가). 출력: 없음.
 */
async function _startFlow(force) {
  if (!viewerState.docId || !viewerState.partId) return;
  if (!force && (_signalsCurrent() || flowState.loading)) return;
  flowState.loading = true;
  try {
    // 다른 문헌·권이면 전 책의 목차 쪽 번호가 이어지면 안 된다
    const tocInput = document.getElementById("comp-toc-pages");
    if (tocInput && (proposeState.docId !== viewerState.docId || proposeState.partId !== viewerState.partId)) tocInput.value = "";
    if (proposeState.llm && (proposeState.llm.docId !== viewerState.docId || proposeState.llm.partId !== viewerState.partId)) proposeState.llm = null;
    proposeState.tocRaw = null;
    proposeState.data = null;
    proposeState.baseline = null;
    proposeState.toc = null;
    proposeState.selected = new Set();
    proposeState.anchor = null;
    const list = document.getElementById("comp-propose-list");
    if (list) list.innerHTML = '<div class="placeholder">전문을 세는 중…</div>';
    const summary = document.getElementById("comp-toc-summary");
    if (summary) summary.textContent = "찾는 중…";
    _renderTalk(null);
    // 목차는 신호 세기의 1단이다(D-117). 제안에 넘길 항목 목록은 _detectToc(규칙)가 만든다 —
    // 둘이 같은 규칙(detect_toc_pages·extract_toc_entries_rule)을 쓰므로 어긋나지 않는다.
    await Promise.all([_loadSignals(), _detectToc(false)]);
    if (!_signalsCurrent()) return;
    await _proposeBoundaries(true);
  } finally {
    flowState.loading = false;
  }
}

/**
 * ②의 입력 지문 — 규칙 전체 + 목차 쪽 칸. 입력: (있으면) 규칙. 출력: JSON 문자열.
 * 목적: 후보를 셀 때 보낸 것과 지금 화면을 같은 식으로 견준다. 목차 쪽도 후보를 바꾸므로 든다.
 */
function _formDigest(rules) {
  return JSON.stringify({
    rules: rules || _rulesFromForm(),
    toc: document.getElementById("comp-toc-pages")?.value || "",
  });
}

/** 후보의 자리 키. 입력: 후보. 출력: "쪽:행:글자". */
function _propKey(p) {
  return `${p.page}:${p.line_index}:${p.char_offset || 0}`;
}

/** 채택된 후보를 자리 키로. 입력: propose 응답. 출력: Map. 목적: «바뀐 것»을 자리로 견준다. */
function _acceptedMap(data) {
  const m = new Map();
  for (const p of data?.proposals || []) if (p.accepted) m.set(_propKey(p), p);
  return m;
}

/** 저장된 경계 행을 자리 키로 — «바뀐 것»의 기준(D-122 덧붙임 2). */
function _savedMap(data) {
  const m = new Map();
  for (const p of data?.proposals || []) if (p.boundary_id) m.set(_propKey(p), p);
  return m;
}

/** 체크된 행을 자리 키로 — 「적용」하면 이것이 경계다. */
function _checkedMap(data) {
  const m = new Map();
  for (const p of data?.proposals || []) {
    const k = _propKey(p);
    if (proposeState.checked.has(k)) m.set(k, p);
  }
  return m;
}

/** 저장된 경계 목록이 이 문헌·권의 것인지 확인하고 아니면 읽는다. */
async function _ensureCurrentBoundaries() {
  const tag = `${viewerState.docId}/${viewerState.partId}`;
  if (compState.currentBoundariesTag === tag && Array.isArray(compState.currentBoundaries)) return;
  await _renderCurrentBoundaries();
  compState.currentBoundariesTag = tag;
}

/** 저장된 경계인가(손으로 넣은 것과 구분) — 서버 _is_proposal_boundary와 같은 판정. */
function _isProposalBoundary(b) {
  if ((b.metadata || {}).source === "proposal") return true;
  return (b.kind || "manual") !== "manual";
}

/**
 * 저장된 경계를 ③의 행으로 합친다(D-122 덧붙임 2). 입력: propose 응답. 출력: 없음(data를 고친다).
 * 같은 자리의 후보가 있으면 그 행에 «지금 경계» 표지를 얹고 제목·역할·깊이는 저장된 것으로(사람이 확정한
 * 것이다). 없으면 행을 더한다. 행 목록(data.lines)에 없는 자리(목차 쪽 등)는 넣지 않는다 — 그런 경계는
 * 「적용」이 건드리지 않는다(replace="listed"는 지목한 id만 지운다).
 */
function _mergeCurrentBoundaries(data) {
  const rows = (compState.currentBoundaries || []).filter((b) => b.status !== "deprecated" && b.status !== "archived");
  if (!rows.length) return;
  const lineKeys = new Set((data.lines || []).map((l) => `${l.page}:${l.line_index}`));
  const byKey = new Map(data.proposals.map((p) => [_propKey(p), p]));
  let joined = 0, added = 0;
  for (const b of rows) {
    const st = b.start || {};
    const page = Number(st.page), line = Number(st.line), off = Number(st.offset || 0);
    if (!lineKeys.has(`${page}:${line}`)) continue;
    const k = `${page}:${line}:${off}`;
    const manual = !_isProposalBoundary(b);
    const cur = byKey.get(k);
    if (cur) {
      if (!cur.reasons.includes("current")) cur.reasons.push("current");
      if (manual && !cur.reasons.includes("manual")) cur.reasons.push("manual");
      cur.boundary_id = b.id;
      cur.manual = manual;
      cur.title = b.title || cur.title;
      cur.level = b.level || cur.level;
      cur.role = b.role || cur.role;
      cur.confidence = 1;
      cur.accepted = true;
      joined++;
    } else {
      const p = {
        page, line_index: line, char_offset: off, title: b.title || "", level: b.level || 2,
        role: b.role || "article", kind: b.kind === "volume" ? "volume" : "", reasons: manual ? ["current", "manual"] : ["current"],
        confidence: 1, accepted: true, suppressed: false, boundary_id: b.id, manual,
      };
      data.proposals.push(p);
      byKey.set(k, p);
      added++;
    }
  }
  data.proposals.sort((a, b) => a.page - b.page || a.line_index - b.line_index || (a.char_offset || 0) - (b.char_offset || 0));
  data.stats.current = { added, joined };
}

/**
 * ②의 규칙으로 후보를 센다 (D-088). **저장하지 않는다** — propose 라우트는 규칙을 받기만 한다.
 * 입력: asBaseline(이 결과를 «바뀐 것»의 기준으로 삼을 것인가 — 처음·적용 직후). 출력: 없음.
 */
async function _proposeBoundaries(asBaseline) {
  if (!viewerState.docId || !viewerState.partId) {
    showToast("사이드바에서 문헌과 권을 먼저 고르세요.", "warning");
    return;
  }
  const list = document.getElementById("comp-propose-list");
  if (!list) return;
  if (!_signalsCurrent()) {
    await _startFlow(); // 신호부터 센다 — 끝에서 다시 여기로 온다
    return;
  }
  list.innerHTML = '<div class="placeholder">권 전체 확정본을 읽어 경계를 찾는 중…</div>';
  const docId = viewerState.docId;
  const partId = viewerState.partId;
  const seq = ++proposeState.seq;
  const useToc = document.getElementById("comp-toc-use")?.checked !== false;
  // 목차 쪽 칸을 고쳤으면 캐시(proposeState.toc)가 아니라 그 쪽으로 다시 찾는다(Codex 지적)
  const tocRaw = document.getElementById("comp-toc-pages")?.value || "";
  if (useToc && tocRaw !== proposeState.tocRaw) {
    await _detectToc(false);
    if (seq !== proposeState.seq) return;
  }
  const rules = _rulesFromForm();
  const digest = _formDigest(rules); // «보낸 것»의 지문 — 응답 뒤의 폼이 아니라
  try {
    const res = await fetch(`/api/documents/${encodeURIComponent(docId)}/segmentation/propose`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        part_id: partId,
        rules,
        use_toc: useToc,
        toc: useToc ? proposeState.toc : null,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    // 그 사이 다시 눌렀거나 다른 문헌·권으로 갔으면 이 응답은 버린다
    if (seq !== proposeState.seq || docId !== viewerState.docId || partId !== viewerState.partId) return;
    _mergeLlmProposals(data, docId, partId); // 모델이 가리킨 자리(D-125)는 규칙 후보와 같은 목록에 선다
    _mergeLocatedProposals(data, docId, partId); // 사람이 찾아 넣은 목차 자리도(D-122 덧붙임)
    // 저장된 경계가 ③의 바탕이다(D-122 덧붙임 2) — 닫았다 열어도 사이드바 「내용」과 같은 것을 본다
    await _ensureCurrentBoundaries();
    if (seq !== proposeState.seq || docId !== viewerState.docId || partId !== viewerState.partId) return;
    _mergeCurrentBoundaries(data);
    const hasSaved = data.proposals.some((p) => p.boundary_id);
    const same = proposeState.docId === docId && proposeState.partId === partId;
    const prevKeys = same && proposeState.data ? new Set(proposeState.data.proposals.map(_propKey)) : null;
    const hasToc = !!(data.toc && data.toc.matches && data.toc.matches.length);
    // 체크: 전에 있던 자리는 그대로, 새 자리는 기본(목차가 있는 책은 목차 항목만 — 날짜·형식 후보는
    // 목차 없는 일기류를 위한 것이다. 「전체」로 언제든 넓힐 수 있다)
    const checked = new Set();
    for (const p of data.proposals) {
      const k = _propKey(p);
      if (p.suppressed) continue; // 억제한 자리는 체크에서 빠진다 — 남으면 적용은 되고 화면만 꺼진다(Codex 지적)
      if (prevKeys && prevKeys.has(k)) {
        if (proposeState.checked.has(k)) checked.add(k);
      } else if (p.boundary_id) checked.add(k); // 저장된 경계는 처음부터 체크 — 아무것도 안 건드리면 아무 일도 없다
      else if (!hasSaved && p.accepted && (!hasToc || _isTocProposal(p) || _isLlmProposal(p))) checked.add(k);
    }
    const keys = new Set(data.proposals.map(_propKey));
    const keep = (map) => new Map([...map].filter(([k]) => keys.has(k)));
    proposeState.data = data;
    proposeState.docId = docId;
    proposeState.partId = partId;
    proposeState.rulesDigest = digest;
    proposeState.checked = checked;
    proposeState.levels = same ? keep(proposeState.levels) : new Map();
    proposeState.roles = same ? keep(proposeState.roles) : new Map();
    proposeState.selected = new Set([...proposeState.selected].filter((k) => keys.has(k)));
    if (asBaseline || !proposeState.baseline || !same) {
      proposeState.baseline = hasSaved ? _savedMap(data) : _acceptedMap(data);
      proposeState.baselineKind = hasSaved ? "boundaries" : "rules";
    }
    _renderProposals();
    _renderDiff();
    _refreshApplyState();
  } catch (e) {
    list.innerHTML = `<div class="placeholder">${_treeEscHtml ? _treeEscHtml(e.message) : e.message}</div>`;
    _refreshApplyState();
  }
}

// 근거 토큰 → 사람 말 (양수 신호는 초록, 감점은 붉게)
const _REASON_LABELS = {
  date: ["날짜", "pos"], mark: ["○ 표지", "pos"], short_line: ["짧은 행", "pos"], indent: ["내려쓰기", "pos"],
  same_day: ["같은 날", "pos"], month_rolled: ["달 넘김", ""], long_line: ["긴 행", "neg"],
  no_title_word: ["어휘 없음", "neg"], same_day_repeat: ["같은 날짜 되풀이", "neg"],
  word_in_clause: ["문장 속 어휘", "neg"], date_jump: ["날짜 역행", "neg"], suppressed: ["억제", "neg"],
  volume_repeat: ["卷 되풀이(판심)", "neg"], furniture: ["판심·엽수", "neg"],
  date_wrap: ["행 넘긴 날짜", "pos"], after_short: ["행갈음 시작", "pos"],
  indent_shallow: ["얕은 들여쓰기 → 묶음", ""], indent_deep: ["깊은 들여쓰기 → 조각", ""],
  "llm:structure": ["LLM 구조", "pos"],
};
function _reasonChip(r) {
  let label = r, cls = "";
  if (r === "current") { label = "지금 경계"; cls = "current"; }
  else if (r === "manual") { label = "손으로 넣음"; cls = "current"; }
  else if (r === "toc:located") { label = "목차·찾아 넣음"; cls = "pos"; }
  else if (r.startsWith("toc:")) { label = `목차 ${r.slice(4)}`; cls = "pos"; }
  else if (r.startsWith("volume:")) { label = `卷 ${r.slice(7)}`; cls = "pos"; }
  else if (r.startsWith("title_word:")) { label = `어휘 ${r.slice(11)}`; cls = "pos"; }
  else if (r.startsWith("head_word:")) { label = `행머리 ${r.slice(10)}`; cls = "pos"; }
  else if (r.startsWith("head_template:")) { label = `행머리 꼴 ${r.slice(14)}`; cls = "pos"; }
  else if (r.startsWith("tail_template:")) { label = `행끝 꼴 ${r.slice(14)}`; cls = "pos"; }
  else if (_REASON_LABELS[r]) [label, cls] = _REASON_LABELS[r];
  const s = document.createElement("span");
  s.className = `prop-reason ${cls}`;
  s.textContent = label;
  return s;
}

/** 목차 대응이거나 卷 표제 — «목차 항목만» 기본 선택에서 살아남는 것들. */
function _isTocProposal(p) {
  if (p.kind === "volume") return true; // 卷이 빠지면 트리에 묶음이 없다
  return (p.reasons || []).some((r) => r.startsWith("toc:"));
}

const _ROLE_NAMES = { container: "묶음", article: "기사", fragment: "조각" };

/** 후보 하나의 (역할, 깊이) — 사람이 바꾼 것이 있으면 그것. */
function _propRoleLevel(p) {
  const k = _propKey(p);
  return {
    role: proposeState.roles.get(k) ?? p.role ?? "article",
    level: proposeState.levels.get(k) ?? p.level ?? 2,
  };
}

/** ③ 머리 줄: 행 수·후보·체크 + 문턱 아래 보기. */
function _updateStats() {
  const data = proposeState.data;
  const stats = document.getElementById("comp-propose-stats");
  if (!data || !stats) return;
  const nCur = data.proposals.filter((p) => p.boundary_id).length;
  stats.textContent = `${data.stats.lines}행 · ` + (nCur ? `지금 경계 ${nCur} · ` : "") + `후보 ${data.proposals.length} · 체크 ${proposeState.checked.size}` +
    (data.stats.suppressed ? ` · 억제 ${data.stats.suppressed}` : "") +
    (data.stats.llm ? ` · LLM ${data.stats.llm.added + data.stats.llm.joined}` : "");
  // 문턱 아래 후보는 기본으로 숨긴다 — 보이는 목록은 «승인 후보»여야 읽힌다
  const rejected = data.proposals.filter((p) => !p.accepted).length;
  if (rejected) {
    const tg = document.createElement("button");
    tg.type = "button";
    tg.className = "text-btn";
    tg.style.cssText = "font-size:11px; margin-left:6px;";
    tg.textContent = proposeState.showRejected ? `문턱 아래 ${rejected}개 숨기기` : `문턱 아래 ${rejected}개 보기`;
    tg.addEventListener("click", () => {
      proposeState.showRejected = !proposeState.showRejected;
      _renderProposals();
    });
    stats.appendChild(tg);
  }
}

/**
 * ③ 후보 목록. 체크 = 경계가 될 것, 행 선택(Shift 범위·Ctrl 하나씩) = 한꺼번에 고칠 것.
 * 행마다 있던 역할 select·깊이 input·「억제」 단추는 없앴다 — 몇백 개를 하나씩 만지지 않는다(D-122).
 */
function _renderProposals() {
  const data = proposeState.data;
  const list = document.getElementById("comp-propose-list");
  if (!data || !list) return;
  _updateStats();
  // 목차 신호 요약 (D-089)
  const tocSummary = document.getElementById("comp-toc-summary");
  const unmatchedBox = document.getElementById("comp-toc-unmatched");
  if (data.toc && data.toc.entries?.length) {
    const n = data.toc.entries.length;
    const m = data.toc.matches?.length || 0;
    if (tocSummary)
      tocSummary.textContent =
        `${data.toc.pages.join(",")}쪽 · ${n}항목 중 ${m} 대조` +
        (proposeState.tocSource ? ` (${proposeState.tocSource})` : "");
    if (unmatchedBox) _renderUnmatchedToc(unmatchedBox, data.toc.unmatched || []);
  } else {
    if (tocSummary && !proposeState.toc) tocSummary.textContent = "없음";
    if (unmatchedBox) unmatchedBox.style.display = "none";
  }
  _parkRowTools(); // 목록을 지우기 전에 도구를 거둔다
  list.innerHTML = "";
  proposeState.visible = [];
  if (!data.proposals.length) {
    list.innerHTML =
      '<div class="placeholder">경계 후보가 없습니다. ②에서 규칙을 더 켜거나 어휘를 더해 「후보 보기」를 누르세요.</div>';
    _renderBatchBar();
    _updateCheckAll();
    return;
  }
  for (const p of data.proposals) {
    const k = _propKey(p);
    if (!p.accepted && !proposeState.showRejected && !proposeState.checked.has(k)) continue;
    proposeState.visible.push(k);
    const row = document.createElement("div");
    row.className = "comp-propose-row" + (p.suppressed ? " suppressed" : "") + (proposeState.selected.has(k) ? " is-selected" : "") + (p.boundary_id ? " is-current" : "");
    row.dataset.key = k;
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = proposeState.checked.has(k);
    cb.disabled = !!p.suppressed;
    cb.addEventListener("click", (ev) => ev.stopPropagation());
    cb.addEventListener("change", () => {
      if (cb.checked) proposeState.checked.add(k);
      else proposeState.checked.delete(k);
      _updateStats();
      _updateCheckAll();
      _refreshApplyState();
    });
    if (p.boundary_id) cb.title = p.manual ? "저장된 경계(손으로 넣음) — 체크를 빼면 「적용」 때 지웁니다" : "저장된 경계 — 체크를 빼면 「적용」 때 지웁니다";
    const body = document.createElement("div");
    const title = document.createElement("div");
    title.className = "prop-title";
    title.textContent = p.title;
    if (p.reasons.some((r) => r.startsWith("toc:"))) {
      const badge = document.createElement("span");
      badge.className = "prop-badge-toc";
      badge.textContent = p.kind === "volume" ? "목차·권" : "목차";
      title.appendChild(badge);
    }
    const meta = document.createElement("div");
    meta.className = "prop-meta";
    const d = p.date || {};
    const dateTxt = d.month || d.day
      ? `${d.ganzhi ? d.ganzhi + " " : ""}${d.month ? d.month + "월" : "?월"} ${d.day ? d.day + "일" : ""}` +
        (d.month_inferred ? (d.month_rolled ? " (달 넘김 추정)" : " (달 물려받음)") : "")
      : "";
    // 행 중간 경계(D-090 2단계): 「○七日」처럼 열 중간에서 날이 바뀌는 판식은 몇째 글자인지도 보인다
    const goto = document.createElement("span");
    goto.className = "prop-goto";
    goto.textContent = `${p.page}쪽 ${p.line_index + 1}행` + (p.char_offset ? ` ${p.char_offset + 1}자째` : "");
    goto.title = "누르면 그 쪽으로 이동";
    goto.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (typeof goToPage === "function") goToPage(p.page);
    });
    meta.appendChild(goto);
    const rest = [dateTxt, p.place ? `장소·상대: ${p.place}` : ""].filter(Boolean).join("  |  ");
    meta.appendChild(document.createTextNode((rest ? "  |  " + rest : "") + "  "));
    for (const r of p.reasons) meta.appendChild(_reasonChip(r));
    body.appendChild(title);
    body.appendChild(meta);
    const right = document.createElement("div");
    right.className = "prop-actions";
    const conf = document.createElement("span");
    const cls = p.confidence >= 0.8 ? "high" : p.confidence >= 0.5 ? "mid" : "low";
    conf.className = `prop-conf ${cls}`;
    conf.textContent = `${Math.round(p.confidence * 100)}%`;
    right.appendChild(conf);
    // 역할(뜻)과 깊이(구조)는 따로(D-092). 글자로만 보이고, 바꾸는 것은 행을 골라 위 줄에서
    const lvl = document.createElement("span");
    lvl.className = "prop-lvl";
    const rl = _propRoleLevel(p);
    lvl.textContent = `${_ROLE_NAMES[rl.role] || rl.role} ${rl.level}단`;
    lvl.title = "역할 · 깊이 — 행을 골라 위 줄에서 바꿉니다";
    right.appendChild(lvl);
    row.appendChild(cb);
    row.appendChild(body);
    row.appendChild(right);
    row.addEventListener("click", (ev) => _selectRow(k, ev));
    list.appendChild(row);
  }
  _renderBatchBar();
  _updateCheckAll();
}

/**
 * 행 선택. 입력: 자리 키·마우스 이벤트. 출력: 없음.
 * 그냥 누르면 그것만, Shift는 앞서 누른 것부터 범위(보이는 순서), Ctrl은 하나씩 더하고 뺀다.
 */
function _selectRow(k, ev) {
  const vis = proposeState.visible;
  proposeState.lastClicked = k;
  if (ev.shiftKey && proposeState.anchor && vis.includes(proposeState.anchor)) {
    const a = vis.indexOf(proposeState.anchor);
    const b = vis.indexOf(k);
    const [lo, hi] = a < b ? [a, b] : [b, a];
    if (!(ev.ctrlKey || ev.metaKey)) proposeState.selected = new Set();
    for (let i = lo; i <= hi; i++) proposeState.selected.add(vis[i]);
  } else if (ev.ctrlKey || ev.metaKey) {
    if (proposeState.selected.has(k)) proposeState.selected.delete(k);
    else proposeState.selected.add(k);
    proposeState.anchor = k;
  } else {
    proposeState.selected = proposeState.selected.size === 1 && proposeState.selected.has(k) ? new Set() : new Set([k]);
    proposeState.anchor = k;
  }
  document.querySelectorAll("#comp-propose-list .comp-propose-row").forEach((el) => {
    el.classList.toggle("is-selected", proposeState.selected.has(el.dataset.key));
  });
  _renderBatchBar();
}

/** 위 줄의 안내 + 도구를 고른 행 옆에 놓는다. 고른 것이 없으면 도구를 거둔다. */
function _renderBatchBar() {
  const n = proposeState.selected.size;
  const count = document.getElementById("comp-sel-count");
  if (count) count.textContent = n ? `고른 행 ${n}개` : "행을 누르면 그 옆에 고치는 도구가 뜹니다(Shift 범위·Ctrl 하나씩)";
  _placeRowTools();
}

/** 도구를 목록 밖 보관함으로 되돌린다 — 목록을 다시 그리기 전에(innerHTML이 지우면 단추의 이벤트가 사라진다). */
function _parkRowTools() {
  const tools = document.getElementById("comp-batch-tools");
  const holder = document.getElementById("comp-batch-holder");
  if (tools && holder && tools.parentElement !== holder) holder.appendChild(tools);
  if (tools) tools.hidden = true;
}

/**
 * 도구를 마지막으로 누른 행 바로 아래에 놓는다(D-122 덧붙임 2). 여러 행을 잡았으면 «N행에:».
 * 왜: «선택»이라는 상태를 배우지 않아도, 누른 자리에서 바로 고칠 수 있어야 한다(사용자 지적 2026-09-11).
 */
function _placeRowTools() {
  const tools = document.getElementById("comp-batch-tools");
  if (!tools) return;
  const n = proposeState.selected.size;
  const cnt = document.getElementById("comp-batch-count");
  if (cnt) cnt.textContent = n > 1 ? `고른 ${n}행에:` : "이 행에:";
  if (!n) {
    _parkRowTools();
    return;
  }
  let key = proposeState.lastClicked;
  if (!proposeState.selected.has(key)) key = [...proposeState.selected].pop();
  const row = [...document.querySelectorAll("#comp-propose-list .comp-propose-row")].find((el) => el.dataset.key === key);
  if (!row) {
    _parkRowTools();
    return;
  }
  row.insertAdjacentElement("afterend", tools);
  tools.hidden = false;
  // 붙박이 발·머리 줄에 가리지 않게 굴려 보인다(scroll-margin이 그 높이를 안다)
  tools.scrollIntoView({ block: "nearest" });
}

/** 「전체」 체크박스를 보이는 행의 상태에 맞춘다(전부·일부·없음). */
function _updateCheckAll() {
  const el = document.getElementById("comp-check-all");
  if (!el) return;
  const vis = proposeState.visible;
  const n = vis.filter((k) => proposeState.checked.has(k)).length;
  el.checked = vis.length > 0 && n === vis.length;
  el.indeterminate = n > 0 && n < vis.length;
}

/** 보이는 후보 전부 체크·해제. */
function _checkVisible(on) {
  const data = proposeState.data;
  if (!data) return;
  const suppressed = new Set(data.proposals.filter((p) => p.suppressed).map(_propKey));
  for (const k of proposeState.visible) {
    if (suppressed.has(k)) continue;
    if (on) proposeState.checked.add(k);
    else proposeState.checked.delete(k);
  }
  _renderProposals();
  _refreshApplyState();
}

/** 고른 행의 체크를 한꺼번에. */
function _batchCheck(on) {
  const suppressed = new Set((proposeState.data?.proposals || []).filter((p) => p.suppressed).map(_propKey));
  for (const k of proposeState.selected) {
    if (on && !suppressed.has(k)) proposeState.checked.add(k);
    else if (!on) proposeState.checked.delete(k);
  }
  _renderProposals();
  _refreshApplyState();
}

/** 고른 행의 역할·깊이를 한꺼번에 바꾼다. 비운 칸은 그대로 둔다. */
function _batchChange() {
  const role = document.getElementById("comp-batch-role")?.value || "";
  const raw = document.getElementById("comp-batch-level")?.value || "";
  const level = raw ? Math.max(1, Number(raw) || 1) : null;
  if (!role && level == null) {
    showToast("바꿀 역할이나 깊이를 고르세요.", "warning");
    return;
  }
  for (const k of proposeState.selected) {
    if (role) proposeState.roles.set(k, role);
    if (level != null) proposeState.levels.set(k, level);
  }
  _renderProposals();
}

/** 고른 행을 억제 목록에 넣고 다시 센다 — 저장은 「적용」이 한다. */
async function _batchSuppress() {
  const data = proposeState.data;
  if (!data || !proposeState.selected.size) return;
  const byKey = new Map(data.proposals.map((p) => [_propKey(p), p]));
  const el = document.getElementById("comp-rules-suppress");
  if (!el) return;
  const cur = el.value.split(/\n/).map((x) => x.trim()).filter(Boolean);
  for (const k of proposeState.selected) {
    const p = byKey.get(k);
    if (!p) continue;
    const text = (data.lines.find((l) => l.page === p.page && l.line_index === p.line_index)?.text || p.title).trim();
    if (text && !cur.includes(text)) cur.push(text);
  }
  el.value = cur.join(String.fromCharCode(10));
  signalState.touched = true;
  proposeState.selected = new Set();
  await _proposeBoundaries();
}

/**
 * «바뀐 것» (D-121 관문): 저장된 규칙(없으면 권고)으로 센 채택 후보와 지금 후보를 자리로 견준다.
 * 수만 같고 자리가 바뀐 것도 잡힌다 — 「후보 615 → 608」만으로는 모자란다(Codex 지적).
 */
function _renderDiff() {
  const out = document.getElementById("comp-preview-out");
  const data = proposeState.data;
  if (!out) return;
  if (!data || !proposeState.baseline) {
    out.hidden = true;
    return;
  }
  // 저장된 경계가 있으면 «체크한 것 vs 저장된 것»(적용하면 정확히 이것이 일어난다), 없으면 옛 방식(채택 후보 vs 기준)
  const byBoundaries = proposeState.baselineKind === "boundaries";
  const now = byBoundaries ? _checkedMap(data) : _acceptedMap(data);
  const base = proposeState.baseline;
  const added = [...now.keys()].filter((k) => !base.has(k));
  const removed = [...base.keys()].filter((k) => !now.has(k));
  if (!added.length && !removed.length) {
    out.hidden = true;
    return;
  }
  out.hidden = false;
  out.textContent = "";
  const head = document.createElement("div");
  head.className = "comp-preview-head";
  head.textContent = byBoundaries
    ? `바뀐 것 — 새로 세울 자리 ${added.length} · 지울 자리 ${removed.length}`
    : `바뀐 것 — 새로 잡히는 자리 ${added.length} · 빠지는 자리 ${removed.length}`;
  head.title = byBoundaries
    ? "지금 저장된 경계와 견줍니다. 「적용」하면 정확히 이대로 됩니다"
    : "지금 저장된 규칙(없으면 권고)으로 센 채택 후보와 견줍니다. 「적용」하면 이것이 기준이 됩니다";
  out.appendChild(head);
  const where = (p) => `${p.page}쪽 ${p.line_index + 1}행`;
  const box = document.createElement("div");
  box.className = "comp-preview-list";
  const show = (keys, src, sign) => {
    const sorted = keys.sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    for (const k of sorted.slice(0, 12)) {
      const p = src.get(k);
      const line = document.createElement("div");
      line.className = "comp-preview-row";
      line.textContent = `${sign} ${where(p)}  ${(p.title || "").slice(0, 30)}`;
      box.appendChild(line);
    }
    if (sorted.length > 12) {
      const more = document.createElement("div");
      more.className = "comp-preview-note";
      more.textContent = `… ${sorted.length - 12}자리 더`;
      box.appendChild(more);
    }
  };
  show(added, now, "+");
  show(removed, base, "−");
  out.appendChild(box);
}

/**
 * 「적용」 단추의 상태. ②의 칸이 후보를 셀 때와 다르면 후보가 낡은 것이라 막는다 —
 * 사람이 규칙을 고쳐 놓고 옛 후보를 적용하면 «말한 것과 다른 일»이 된다(D-122).
 */
function _refreshApplyState() {
  const btn = document.getElementById("comp-propose-apply-btn");
  const note = document.getElementById("comp-apply-note");
  if (!btn) return;
  const data = proposeState.data;
  if (!data || !_signalsCurrent()) {
    btn.disabled = true;
    if (note) note.textContent = "";
    return;
  }
  const stale = _formDigest() !== proposeState.rulesDigest;
  btn.disabled = stale || !proposeState.checked.size;
  if (note) note.textContent = stale ? "규칙이 바뀌었습니다 — 「후보 보기」로 다시 세우세요" : proposeState.checked.size ? "" : "체크한 후보가 없습니다";
  if (proposeState.baselineKind === "boundaries") _renderDiff(); // 체크가 곧 «바뀐 것»이다
}

/**
 * 해제와 본문의 짧은 행에서 표제 어휘 후보를 뽑는다 (D-092 남은 것).
 *
 * 왜 바로 넣지 않는가: 규칙은 이 문헌의 편집 정책이고 판단은 사람의 것이다(D-080 계열).
 * 후보를 칩으로 보여 주고, 누른 것만 표제 어휘 칸에 붙는다.
 */
async function _suggestRules() {
  const out = document.getElementById("comp-rules-suggest-out");
  if (!out || !viewerState.docId || !viewerState.partId) {
    if (out) out.textContent = "문헌과 권을 먼저 고르세요.";
    return;
  }
  // 모델 이름에는 「kimi-k3:cloud」처럼 콜론이 든다 — 첫 콜론에서만 나누는 공용 함수를 쓴다.
  // 전에는 `split(":")`로 잘라 「kimi-k3」만 보내 Ollama 404가 났다(사용자 실측 2026-09-07).
  const llmSel =
    typeof getLlmModelSelection === "function"
      ? getLlmModelSelection("comp-llm-model-select")
      : { force_provider: null, force_model: null };
  const provider = llmSel.force_provider;
  const model = llmSel.force_model;
  out.textContent = "해제와 본문을 보는 중…";
  try {
    const res = await fetch(
      `/api/documents/${encodeURIComponent(viewerState.docId)}/segmentation-rules/suggest`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          part_id: viewerState.partId,
          reference_text: _llmReferenceText() || null,
          force_provider: provider || null,
          force_model: model || null,
        }),
      },
    );
    const d = await res.json();
    if (!res.ok) throw new Error(d.error || `HTTP ${res.status}`);
    _renderRuleCandidates(d);
  } catch (e) {
    out.textContent = `뽑기 실패: ${e.message}`;
  }
}

function _renderRuleCandidates(d) {
  const out = document.getElementById("comp-rules-suggest-out");
  out.textContent = "";
  const words = d.title_words || [];
  const sup = d.suppress || [];
  if (!words.length && !sup.length) {
    out.textContent = d.error
      ? `뽑지 못했습니다: ${d.error}`
      : `후보가 없습니다 (표본 ${d.sample_count || 0}행). 손으로 적으세요.`;
    return;
  }
  const line = document.createElement("div");
  line.textContent = `표본 ${d.sample_count || 0}행${d.model ? ` · ${d.model}` : ""} — 누르면 넣습니다`;
  out.appendChild(line);
  const add = (text, targetId, isList) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "comp-rules-cand";
    b.textContent = text;
    b.title = isList ? "억제 목록에 넣기" : "신호 목록에 표제 어휘로 넣기 (켜진 채로)";
    b.addEventListener("click", () => {
      if (isList) {
        const el = document.getElementById(targetId);
        if (!el) return;
        const cur = el.value.trim();
        const has = cur.split(/\n/).some((x) => x.trim() === text);
        if (!has) el.value = cur ? cur + "\n" + text : text;
      } else {
        _addWordRow(`tail:${text}`, "title_words", `행 끝 「${text}」 (LLM 후보)`, text);
      }
      b.disabled = true;
    });
    out.appendChild(b);
  };
  for (const w of words) add(w, null, false);
  for (const s of sup) add(s, "comp-rules-suppress", true);
  if (d.note) {
    const n = document.createElement("div");
    n.textContent = d.note;
    out.appendChild(n);
  }
}

/**
 * ① 「말로 넣기」 — 연구자가 쓴 문장을 규칙 변경으로 옮긴다 (D-121 두 번째 입구). 저장하지 않는다.
 *
 * 옮긴 것은 ②의 체크 상태·손으로 넣은 행·참고 칸에 바로 들어가고(_checkFromRules) ③이 다시 선다 —
 * «바뀐 것»이 거기서 보인다. 옮기지 못한 말은 반드시 보인다: 비슷한 칸으로 바꿔치기하면 사람은
 * 말했다고 여기는데 시스템은 다른 일을 한다.
 */
async function _rulesFromWords() {
  const box = document.getElementById("comp-llm-say");
  const said = (box?.value || "").trim();
  const btn = document.getElementById("comp-say-btn");
  if (!said) {
    showToast("이 책에 대해 아는 것을 한 줄 적어 주세요.", "warning");
    if (box) box.focus();
    return;
  }
  if (!_signalsCurrent()) {
    await _startFlow();
    if (!_signalsCurrent()) return;
  }
  const llmSel = typeof getLlmModelSelection === "function" ? getLlmModelSelection("comp-llm-model-select") : {};
  const useToc = document.getElementById("comp-toc-use")?.checked !== false;
  if (btn) btn.disabled = true;
  const docId = viewerState.docId;
  const partId = viewerState.partId;
  _renderTalk({ pending: true });
  try {
    const res = await fetch(
      `/api/documents/${encodeURIComponent(viewerState.docId)}/segmentation/rules-from-words`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          part_id: viewerState.partId,
          said,
          rules: _rulesFromForm(), // 화면의 초안 위에 얹는다 — 저장본이 아니라(Codex 지적)
          use_toc: useToc,
          toc_pages: useToc ? _tocPagesFromInput() : null,
          force_provider: llmSel.force_provider || null,
          force_model: llmSel.force_model || null,
        }),
      },
    );
    const d = await res.json();
    if (!res.ok) throw new Error(d.error || `HTTP ${res.status}`);
    if (docId !== viewerState.docId || partId !== viewerState.partId) return; // 다른 문헌으로 갔다
    const talk = d.talk || {};
    if (talk.error) {
      _renderTalk({ error: talk.error });
      return;
    }
    if (d.rules) {
      _checkFromRules(d.rules);
      signalState.touched = true;
      _renderSignals();
      _renderVerdict();
    }
    _renderTalk(talk);
    if (d.rules) await _proposeBoundaries();
    else _refreshApplyState();
  } catch (e) {
    _renderTalk({ error: e.message });
  } finally {
    if (btn) btn.disabled = false;
  }
}

// 규칙 칸 이름 → 사람 말 (말로 옮긴 결과를 보일 때)
const _FIELD_LABELS = {
  title_words: "행 끝 어휘", head_words: "행 첫머리 어휘", symbols: "기호", head_templates: "행 첫머리 꼴",
  tail_templates: "행 끝 꼴", suppress: "억제", furniture: "판심·엽수",
  "signals.toc": "목차", "signals.date": "날짜", "signals.mark": "○ 권점 + 날짜", "signals.volume": "卷頭",
  "signals.short_line": "짧은 행", "signals.after_short": "행갈음 뒤", "signals.indent": "내려쓰기",
  indent_alone: "내려쓰기만으로 경계", max_title_chars: "표제 최대 글자수", min_confidence: "최소 신뢰도",
};

/** 「말로 넣기」 결과. 입력: null(감춤) · {pending} · {error} · talk. 출력: 없음. */
function _renderTalk(talk) {
  const out = document.getElementById("comp-talk-out");
  if (!out) return;
  out.textContent = "";
  if (!talk) {
    out.hidden = true;
    return;
  }
  out.hidden = false;
  const line = (text, cls) => {
    const el = document.createElement("div");
    el.className = "comp-talk-row" + (cls ? ` ${cls}` : "");
    el.textContent = text;
    out.appendChild(el);
    return el;
  };
  if (talk.pending) {
    line("말을 규칙 칸으로 옮기는 중…");
    return;
  }
  if (talk.error) {
    line(`옮기지 못했습니다: ${talk.error}`, "is-unsupported");
    return;
  }
  const acc = talk.accepted || [];
  const un = talk.unsupported || [];
  if (!acc.length && !un.length) {
    line("규칙 칸으로 옮길 수 있는 말이 없었습니다.");
    return;
  }
  for (const a of acc) {
    const label = _FIELD_LABELS[a.field] || a.field;
    let text;
    if (a.op === "add") text = `옮김: ${label} 「${a.value}」 더함`;
    else if (a.op === "remove") text = `옮김: ${label} 「${a.value}」 뺌`;
    else text = `옮김: ${label} ${a.value === false ? "끔" : a.value === true ? "켬" : a.value}`;
    if (a.count != null) text += ` · 전문에 ${a.count}번`;
    const el = line(text + (a.count === 0 ? " — 이 책에 없는 말입니다" : ""), a.count === 0 ? "is-zero" : "");
    if (a.why) el.title = a.why;
  }
  if (un.length) {
    // 많으면(해제를 붙여 넣은 뒤) 접어 둔다 — 돌려주되 화면을 덮지 않는다
    const fold = un.length > 3;
    const holder = fold ? document.createElement("details") : out;
    if (fold) {
      const sm = document.createElement("summary");
      sm.className = "comp-talk-row is-unsupported";
      sm.textContent = `옮기지 못한 말 ${un.length} — 참고로만 읽었습니다(펼쳐 보기). 지금 규칙에는 범위·조건이 없습니다`;
      holder.appendChild(sm);
      out.appendChild(holder);
    } else {
      line(`옮기지 못한 말 ${un.length} — 지금 규칙에는 범위·조건이 없습니다`, "is-unsupported");
    }
    for (const u of un) {
      const el = document.createElement("div");
      el.className = "comp-talk-row is-unsupported";
      el.textContent = `「${u.said}」 — ${u.why}`;
      el.title = u.why || "";
      holder.appendChild(el);
    }
  }
  if (talk.note) line(talk.note, "");
  if (acc.length) line("→ ②에 반영했습니다. ③에서 «바뀐 것»을 보고 「적용」하세요.");
}

/**
 * ③ 「적용」 — ②의 규칙을 저장하고 체크한 후보로 경계를 세운다. 한 요청(D-122).
 * 구간은 화면에서 다시 계산한다 — 사용자가 체크를 바꾸면 서버의 spans와 달라지기 때문이다.
 * 지울 수(실제 대상)는 dry_run으로 먼저 세어 묻는다.
 */
async function _applyProposals() {
  const data = proposeState.data;
  if (!data || !_signalsCurrent()) return;
  if (_formDigest() !== proposeState.rulesDigest) {
    showToast("규칙이 바뀌었습니다 — 「후보 보기」로 후보를 다시 세운 뒤 적용하세요.", "warning");
    _refreshApplyState();
    return;
  }
  const byKey = new Map(data.proposals.map((p) => [_propKey(p), p]));
  const picked = [...proposeState.checked].map((k) => byKey.get(k)).filter(Boolean);
  if (!picked.length) {
    showToast("체크한 후보가 없습니다.", "warning");
    return;
  }
  const lines = data.lines;
  const keyOf = (l) => `${l.page}:${l.line_index}`;
  const pos = new Map(lines.map((l, i) => [keyOf(l), i]));
  // 경계 = (행, 행 안 글자 오프셋). 다음 경계가 행 중간이면 이 구간은 같은 행의 그 글자 앞에서 끝난다 (D-090 2단계)
  const starts = picked
    .map((p) => ({ li: pos.get(keyOf(p)), off: p.char_offset || 0, p }))
    .filter((s) => s.li != null)
    .sort((a, b) => a.li - b.li || a.off - b.off);
  const endBefore = (next) =>
    next.off > 0
      ? { page: lines[next.li].page, line_index: lines[next.li].line_index, char_end: next.off }
      : { page: lines[next.li - 1].page, line_index: lines[next.li - 1].line_index, char_end: null };
  const spans = [];
  if (starts[0].li > 0 || starts[0].off > 0) {
    spans.push({ title: lines[0].text.trim().slice(0, 20) || "(앞부분)", kind: "front", level: 2, role: "article",
      start: { page: lines[0].page, line_index: lines[0].line_index, char_offset: 0 },
      end: endBefore(starts[0]) });
  }
  starts.forEach((s, k) => {
    const end = k + 1 < starts.length
      ? endBefore(starts[k + 1])
      : { page: lines[lines.length - 1].page, line_index: lines[lines.length - 1].line_index, char_end: null };
    const rl = _propRoleLevel(s.p);
    spans.push({ title: s.p.title, kind: s.p.kind || "", level: rl.level, role: rl.role,
      start: { page: lines[s.li].page, line_index: lines[s.li].line_index, char_offset: s.off },
      end });
  });
  // ③이 «지금 경계 + 새 후보»이므로 지울 것은 «체크를 뺀 저장된 행»뿐이다(D-122 덧붙임 2). 목록에 없던
  // 경계(행 목록 밖)는 건드리지 않는다
  const replace = "listed";
  const drop = data.proposals.filter((p) => p.boundary_id && !proposeState.checked.has(_propKey(p))).map((p) => p.boundary_id);
  const rules = _rulesFromForm();
  const btn = document.getElementById("comp-propose-apply-btn");
  const url = `/api/documents/${encodeURIComponent(viewerState.docId)}/segmentation/apply`;
  const post = (extra) =>
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ part_id: viewerState.partId, spans, pages: data.pages || null, replace, drop, ...extra }),
    });
  if (btn) btn.disabled = true;
  try {
    // 무엇을 지우는지 실제 수로 묻는다 — «손으로 넣은 것도»가 아니라 «M개».
    // 세지 못했으면 멈춘다 — 확인 없이 지우는 길이 되면 안 된다(Codex 지적)
    const dryRes = await post({ dry_run: true });
    const dry = await dryRes.json().catch(() => ({}));
    if (!dryRes.ok || dry.dry_run !== true) throw new Error(dry.error || `지울 수를 세지 못했습니다 (HTTP ${dryRes.status})`);
    if (dry.removed) {
      const msg = `새로 ${dry.would_create ?? spans.length}개를 세우고, 지금 경계 중 ${dry.removed}개를 지웁니다.\nGit으로 되돌릴 수 있습니다. 계속할까요?`;
      if (!confirm(msg)) return;
    }
    const res = await post({ rules });
    const result = await res.json();
    if (!res.ok) throw new Error(result.error || `HTTP ${res.status}`);
    const nNew = result.new ?? result.created.length;
    showToast((nNew ? `경계 ${nNew}개 새로 세움` : "새로 세운 경계 없음") + (result.removed ? ` · ${result.removed}개 지움` : "") +
      (result.role_changed ? ` · 역할 ${result.role_changed}개 바꿈` : "") + (result.rules ? " · 규칙 저장" : ""), "success");
    if (result.rules_error) showToast(result.rules_error, "warning");
    else _markRulesSaved(result.rules || rules);
    // 적용한 것이 다음 «바뀐 것»의 기준이 된다 — 저장된 경계를 다시 읽어 ③을 그 위에 다시 세운다
    proposeState.rulesDigest = _formDigest();
    await _loadCompositionData();
    if (typeof refreshContentsTree === "function") refreshContentsTree();
    compState.currentBoundariesTag = null;
    await _proposeBoundaries(true);
  } catch (e) {
    showToast(`적용 실패: ${e.message}`, "error");
  } finally {
    if (btn) btn.disabled = false;
    _refreshApplyState();
  }
}
