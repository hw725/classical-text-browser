/**
 * 워크스페이스 레이아웃 인터랙션 — vanilla JS
 *
 * 기능:
 *   1. 사이드바 너비 드래그 조절
 *   2. 에디터 좌우 분할 비율 드래그 조절
 *   3. 하단 패널 높이 드래그 조절 + 접기/펴기
 *   4. 액티비티 바 탭 전환
 *   5. API에서 서고 정보 로드
 */

document.addEventListener("DOMContentLoaded", () => {
  initResizeHandlers();
  initPanelToggle();
  initActivityBar();
  initTabs();
  loadLibraryInfo();
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
   4. 탭 전환 (층별 탭 + 하단 패널 탭)
   ────────────────────────── */

function initTabs() {
  // 층별 탭 (원문, 교정, 현토, 번역, 주석)
  initTabGroup(".tab-bar .tab");
  // 하단 패널 탭 (Git 이력, 검증 결과, 의존 추적)
  initTabGroup(".panel-tabs .panel-tab");
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
   5. 서고 정보 로드
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

    renderDocumentList(docs);
  } catch (err) {
    // API 연결 실패는 정상 — 정적 파일만 볼 수도 있다
    document.getElementById("document-list").innerHTML =
      '<div class="placeholder">서고에 연결할 수 없습니다</div>';
  }
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
