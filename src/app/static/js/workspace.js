/**
 * 워크스페이스 레이아웃 인터랙션 — vanilla JS
 *
 * 기능:
 *   1. 사이드바 너비 드래그 조절
 *   2. 에디터 좌우 분할 비율 드래그 조절
 *   3. 하단 패널 높이 드래그 조절 + 접기/펴기
 *   4. 액티비티 바 탭 전환
 *   5. API에서 서고 정보 로드
 *   6. PDF 렌더러 초기화 (pdf-renderer.js)
 *   7. 텍스트 에디터 초기화 (text-editor.js)
 *   8. 교정 편집기 초기화 (correction-editor.js)
 */

document.addEventListener("DOMContentLoaded", () => {
  initResizeHandlers();
  initPanelToggle();
  initActivityBar();
  initTabs();
  initModeBar();
  loadLibraryInfo();
  // Phase 3: 병렬 뷰어 모듈 초기화
  if (typeof initPdfRenderer === "function") initPdfRenderer();
  if (typeof initTextEditor === "function") initTextEditor();
  // Phase 4: 레이아웃 편집기 초기화
  if (typeof initLayoutEditor === "function") initLayoutEditor();
  // Phase 6: 교정 편집기 초기화
  if (typeof initCorrectionEditor === "function") initCorrectionEditor();
  // Phase 5: 서지정보 패널 초기화
  if (typeof initBibliography === "function") initBibliography();
  // Phase 7: 해석 저장소 모듈 초기화
  if (typeof initInterpretation === "function") initInterpretation();
  // Phase 8: 엔티티 관리 모듈 초기화
  if (typeof initEntityManager === "function") initEntityManager();
  // Phase 10: 새 문헌 생성 모듈 초기화
  if (typeof initCreateDocument === "function") initCreateDocument();
  // Phase 10-1: OCR 패널 초기화
  if (typeof initOcrPanel === "function") initOcrPanel();
  // Phase 10-3: 대조 뷰 초기화
  if (typeof initAlignmentView === "function") initAlignmentView();
  // Phase 11-1: 표점 편집기 초기화
  if (typeof initPunctuationEditor === "function") initPunctuationEditor();
  // Phase 11-1: 현토 편집기 초기화
  if (typeof initHyeontoEditor === "function") initHyeontoEditor();
  // Phase 11-2: 번역 편집기 초기화
  if (typeof initTranslationEditor === "function") initTranslationEditor();
  // Phase 11-3: 주석 편집기 초기화
  if (typeof initAnnotationEditor === "function") initAnnotationEditor();
  // Phase 7+8: 하단 패널 탭 전환 (Git 이력 ↔ 의존 추적 ↔ 엔티티)
  initBottomPanelTabs();
});


/* ──────────────────────────
   1. 리사이즈 핸들러
   ────────────────────────── */

function initResizeHandlers() {
  // 사이드바 리사이즈
  setupColResize({
    handle: document.getElementById("resize-sidebar"),
    getTarget: () => document.getElementById("sidebar"),
    cssVar: "--sidebar-width",
    minSize: 170,
    maxSize: 600,
  });

  // 에디터 좌우 분할 리사이즈
  setupColResize({
    handle: document.getElementById("resize-editor"),
    getTarget: () => document.getElementById("editor-left"),
    cssVar: null, // flex 기반으로 직접 제어
    minSize: 200,
    maxSize: null, // 동적으로 계산
  });

  // 하단 패널 높이 리사이즈
  setupRowResize({
    handle: document.getElementById("resize-panel"),
    getTarget: () => document.getElementById("bottom-panel"),
    cssVar: "--panel-height",
    minSize: 100,
    maxSize: 500,
  });
}

/**
 * 수평(열) 리사이즈를 설정한다.
 * handle을 드래그하면 target의 너비가 바뀐다.
 */
function setupColResize({ handle, getTarget, cssVar, minSize, maxSize }) {
  if (!handle) return;

  let startX, startWidth;

  handle.addEventListener("mousedown", (e) => {
    e.preventDefault();
    const target = getTarget();
    startX = e.clientX;
    startWidth = target.getBoundingClientRect().width;

    handle.classList.add("active");
    document.body.classList.add("resizing");

    const onMouseMove = (e) => {
      const delta = e.clientX - startX;
      let newWidth = startWidth + delta;

      // 최소/최대 제한
      if (minSize) newWidth = Math.max(newWidth, minSize);
      const effectiveMax = maxSize || window.innerWidth * 0.6;
      newWidth = Math.min(newWidth, effectiveMax);

      if (cssVar) {
        document.documentElement.style.setProperty(cssVar, newWidth + "px");
      } else {
        // flex 기반 직접 제어 (에디터 분할)
        target.style.flex = "none";
        target.style.width = newWidth + "px";
      }
    };

    const onMouseUp = () => {
      handle.classList.remove("active");
      document.body.classList.remove("resizing");
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  });
}

/**
 * 수직(행) 리사이즈를 설정한다.
 * handle을 드래그하면 target의 높이가 바뀐다.
 * (위로 드래그 = 높이 증가)
 */
function setupRowResize({ handle, getTarget, cssVar, minSize, maxSize }) {
  if (!handle) return;

  let startY, startHeight;

  handle.addEventListener("mousedown", (e) => {
    e.preventDefault();
    const target = getTarget();

    // 접힌 상태면 리사이즈 무시
    if (target.classList.contains("collapsed")) return;

    startY = e.clientY;
    startHeight = target.getBoundingClientRect().height;

    handle.classList.add("active");
    document.body.classList.add("resizing-row");

    const onMouseMove = (e) => {
      // 위로 드래그 = delta 음수 = 높이 증가
      const delta = startY - e.clientY;
      let newHeight = startHeight + delta;

      if (minSize) newHeight = Math.max(newHeight, minSize);
      if (maxSize) newHeight = Math.min(newHeight, maxSize);

      if (cssVar) {
        document.documentElement.style.setProperty(cssVar, newHeight + "px");
      }
    };

    const onMouseUp = () => {
      handle.classList.remove("active");
      document.body.classList.remove("resizing-row");
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  });
}


/* ──────────────────────────
   2. 하단 패널 접기/펴기
   ────────────────────────── */

function initPanelToggle() {
  const toggle = document.getElementById("panel-toggle");
  const panel = document.getElementById("bottom-panel");
  if (!toggle || !panel) return;

  toggle.addEventListener("click", () => {
    panel.classList.toggle("collapsed");
  });
}


/* ──────────────────────────
   3. 액티비티 바 탭 전환
   ────────────────────────── */

function initActivityBar() {
  const buttons = document.querySelectorAll(".activity-btn");

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      // 향후: data-panel 값에 따라 사이드바 내용 전환
    });
  });
}


/* ──────────────────────────
   4. 모드 전환 (Phase 4: 열람 / 레이아웃 / 교정)
   ────────────────────────── */

/**
 * 현재 활성 모드를 추적한다.
 * "view" — 열람 모드 (기본. PDF + 텍스트 병렬 뷰어)
 * "layout" — 레이아웃 모드 (PDF 위에 LayoutBlock 편집)
 * "correction" — 교정 모드 (Phase 6: 글자 단위 교정 + 블록별 섹션 + Git 연동)
 * "interpretation" — 해석 모드 (Phase 7: 현토/번역/주석 + 의존 추적)
 * "punctuation" — 표점 모드 (Phase 11-1: L5 표점 편집기)
 * "hyeonto" — 현토 모드 (Phase 11-1: L5 현토 편집기)
 * "translation" — 번역 모드 (Phase 11-2: L6 번역 편집기)
 */
let currentMode = "view";

function initModeBar() {
  const modeTabs = document.querySelectorAll(".mode-tab");
  modeTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const newMode = tab.dataset.mode;
      if (newMode === currentMode) return;

      // 모드 탭 하이라이트 전환
      modeTabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");

      _switchMode(newMode);
    });
  });
}

/**
 * 모드를 전환한다.
 *
 * 왜 이렇게 하는가:
 *   - 열람 모드: 좌측 PDF, 우측 텍스트 에디터 (기존 Phase 3 동작)
 *   - 레이아웃 모드: 좌측 PDF + 오버레이, 우측 블록 속성 패널
 *   - 교정 모드: 좌측 PDF, 우측 교정 편집기 (글자 단위 하이라이팅)
 *
 *   모드 전환 시 좌측 PDF 뷰어는 유지하고,
 *   우측 패널과 오버레이만 교체한다.
 */
function _switchMode(mode) {
  const editorRight = document.getElementById("editor-right");
  const layoutPanel = document.getElementById("layout-props-panel");
  const correctionPanel = document.getElementById("correction-panel");
  const interpPanel = document.getElementById("interp-panel");
  const punctPanel = document.getElementById("punct-panel");
  const hyeontoPanel = document.getElementById("hyeonto-panel");
  const transPanel = document.getElementById("trans-panel");
  const annPanel = document.getElementById("ann-panel");

  // 이전 모드 정리
  if (currentMode === "layout") {
    if (typeof deactivateLayoutMode === "function") deactivateLayoutMode();
    if (layoutPanel) layoutPanel.style.display = "none";
  }
  if (currentMode === "correction") {
    if (typeof deactivateCorrectionMode === "function") deactivateCorrectionMode();
    if (correctionPanel) correctionPanel.style.display = "none";
  }
  if (currentMode === "interpretation") {
    if (typeof deactivateInterpretationMode === "function") deactivateInterpretationMode();
    if (interpPanel) interpPanel.style.display = "none";
  }
  if (currentMode === "punctuation") {
    if (typeof deactivatePunctuationMode === "function") deactivatePunctuationMode();
    if (punctPanel) punctPanel.style.display = "none";
  }
  if (currentMode === "hyeonto") {
    if (typeof deactivateHyeontoMode === "function") deactivateHyeontoMode();
    if (hyeontoPanel) hyeontoPanel.style.display = "none";
  }
  if (currentMode === "translation") {
    if (typeof deactivateTranslationMode === "function") deactivateTranslationMode();
    if (transPanel) transPanel.style.display = "none";
  }
  if (currentMode === "annotation") {
    if (typeof deactivateAnnotationMode === "function") deactivateAnnotationMode();
    if (annPanel) annPanel.style.display = "none";
  }

  // 모든 우측 패널 숨김 (초기화)
  if (editorRight) editorRight.style.display = "none";
  if (layoutPanel) layoutPanel.style.display = "none";
  if (correctionPanel) correctionPanel.style.display = "none";
  if (interpPanel) interpPanel.style.display = "none";
  if (punctPanel) punctPanel.style.display = "none";
  if (hyeontoPanel) hyeontoPanel.style.display = "none";
  if (transPanel) transPanel.style.display = "none";
  if (annPanel) annPanel.style.display = "none";

  // 새 모드 활성화
  currentMode = mode;

  if (mode === "layout") {
    // 우측: 레이아웃 속성 패널 표시
    if (layoutPanel) layoutPanel.style.display = "";
    if (typeof activateLayoutMode === "function") activateLayoutMode();
  } else if (mode === "correction") {
    // 우측: 교정 편집기 패널 표시
    if (correctionPanel) correctionPanel.style.display = "";
    if (typeof activateCorrectionMode === "function") activateCorrectionMode();
  } else if (mode === "interpretation") {
    // 우측: 해석 뷰어 패널 표시
    if (interpPanel) interpPanel.style.display = "";
    if (typeof activateInterpretationMode === "function") activateInterpretationMode();
  } else if (mode === "punctuation") {
    // 우측: 표점 편집기 패널 표시
    if (punctPanel) punctPanel.style.display = "";
    if (typeof activatePunctuationMode === "function") activatePunctuationMode();
  } else if (mode === "hyeonto") {
    // 우측: 현토 편집기 패널 표시
    if (hyeontoPanel) hyeontoPanel.style.display = "";
    if (typeof activateHyeontoMode === "function") activateHyeontoMode();
  } else if (mode === "translation") {
    // 우측: 번역 편집기 패널 표시
    if (transPanel) transPanel.style.display = "";
    if (typeof activateTranslationMode === "function") activateTranslationMode();
  } else if (mode === "annotation") {
    // 우측: 주석 편집기 패널 표시
    if (annPanel) annPanel.style.display = "";
    if (typeof activateAnnotationMode === "function") activateAnnotationMode();
  } else {
    // view 모드: 텍스트 에디터 표시
    if (editorRight) editorRight.style.display = "";
  }
}


/* ──────────────────────────
   5. 탭 전환 (층별 탭 + 하단 패널 탭)
   ────────────────────────── */

function initTabs() {
  // 층별 탭 (원문, 교정, 현토, 번역, 주석)
  initTabGroup(".tab-bar .tab");
}

function initTabGroup(selector) {
  const tabs = document.querySelectorAll(selector);
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
    });
  });
}


/* ──────────────────────────
   6. 서고 정보 로드
   ────────────────────────── */

async function loadLibraryInfo() {
  try {
    // 서고 정보
    const libRes = await fetch("/api/library");
    if (!libRes.ok) throw new Error("서고 API 응답 오류");
    const lib = await libRes.json();

    document.getElementById("status-library").textContent =
      `서고: ${lib.name || "이름 없음"}`;

    // 문헌 목록
    const docsRes = await fetch("/api/documents");
    if (!docsRes.ok) throw new Error("문헌 목록 API 응답 오류");
    const docs = await docsRes.json();

    document.getElementById("status-documents").textContent =
      `문헌: ${docs.length}`;

    // Phase 3: 트리 뷰 사용 (sidebar-tree.js)
    if (typeof initSidebarTree === "function") {
      initSidebarTree(docs);
    } else {
      renderDocumentList(docs);
    }
  } catch (err) {
    // API 연결 실패는 정상 — 정적 파일만 볼 수도 있다
    document.getElementById("document-list").innerHTML =
      '<div class="placeholder">서고에 연결할 수 없습니다</div>';
  }
}

/* ──────────────────────────
   7. 하단 패널 탭 전환 (Phase 7: Git 이력 ↔ 의존 추적)
   ────────────────────────── */

/**
 * 하단 패널 탭 전환을 설정한다.
 *
 * 왜 이렇게 하는가:
 *   기존 initTabGroup은 탭 하이라이트만 처리했다.
 *   Phase 7에서 "의존 추적" 탭을 추가하면서,
 *   탭에 따라 다른 내용 영역을 표시해야 한다.
 *   - "Git 이력" → #git-panel-content 표시
 *   - "의존 추적" → #dep-panel-content 표시
 *   - "엔티티" → #entity-panel-content 표시
 *   - 기타 탭은 기존 동작 유지
 */
function initBottomPanelTabs() {
  const tabs = document.querySelectorAll(".panel-tabs .panel-tab");
  const gitContent = document.getElementById("git-panel-content");
  const validationContent = document.getElementById("validation-panel-content");
  const depContent = document.getElementById("dep-panel-content");
  const entityContent = document.getElementById("entity-panel-content");

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");

      // 탭 내용 전환: 0=Git, 1=검증결과, 2=의존추적, 3=엔티티
      if (gitContent) gitContent.style.display = (index === 0) ? "" : "none";
      if (validationContent) validationContent.style.display = (index === 1) ? "" : "none";
      if (depContent) depContent.style.display = (index === 2) ? "" : "none";
      if (entityContent) entityContent.style.display = (index === 3) ? "" : "none";

      // Phase 8: 엔티티 탭 활성화 시 엔티티 로드
      if (index === 3 && typeof _loadEntitiesForCurrentPage === "function") {
        _loadEntitiesForCurrentPage();
      }
    });
  });
}


/**
 * 사이드바에 문헌 목록을 렌더링한다.
 */
function renderDocumentList(docs) {
  const container = document.getElementById("document-list");

  if (!docs || docs.length === 0) {
    container.innerHTML = '<div class="placeholder">등록된 문헌이 없습니다</div>';
    return;
  }

  container.innerHTML = docs
    .map(
      (doc) => `
      <div class="tree-item" data-doc-id="${doc.document_id || ""}">
        ${doc.title || "제목 없음"}
        <span class="doc-id">${doc.document_id || ""}</span>
      </div>
    `
    )
    .join("");

  // 클릭 이벤트
  container.querySelectorAll(".tree-item").forEach((item) => {
    item.addEventListener("click", () => {
      container.querySelectorAll(".tree-item").forEach((i) => i.classList.remove("active"));
      item.classList.add("active");
      // 향후: 문헌 선택 시 에디터 영역에 내용 표시
    });
  });
}
