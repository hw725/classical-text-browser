/**
 * PDF 렌더러 — PDF.js 기반 좌측 패널
 *
 * 기능:
 *   1. PDF 파일을 API에서 로드 (/api/documents/{doc_id}/pdf/{part_id})
 *   2. 특정 페이지를 Canvas에 렌더링
 *   3. 페이지 이동 (이전/다음, 직접 입력)
 *   4. 줌 (확대/축소, Ctrl+스크롤, 창에 맞추기)
 *   5. 다권본: part 선택 시 PDF를 교체 로드
 *
 * 의존성: PDF.js (CDN), sidebar-tree.js (viewerState)
 *
 * 왜 이렇게 하는가:
 *   - 연구자가 원본 PDF를 페이지별로 열람하면서 우측 패널에 텍스트를 입력한다.
 *   - PDF.js는 브라우저에서 직접 PDF를 렌더링하므로 서버사이드 변환이 불필요하다.
 */

/* ──────────────────────────
   PDF.js 글로벌 설정
   ────────────────────────── */

// PDF.js worker 경로 — CDN에서 로드
if (typeof pdfjsLib !== "undefined") {
  pdfjsLib.GlobalWorkerOptions.workerSrc =
    "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
}


/* ──────────────────────────
   렌더러 상태
   ────────────────────────── */

const pdfState = {
  pdfDoc: null,        // 로드된 PDF 문서 객체 (pdfjsLib.PDFDocumentProxy)
  currentPage: 1,      // 현재 렌더링 중인 페이지 번호
  totalPages: 0,       // 전체 페이지 수
  scale: 1.0,          // 현재 줌 배율
  rendering: false,    // 렌더링 중 여부 (중복 렌더링 방지)
  pendingPage: null,   // 렌더링 대기 중인 페이지 번호
  currentDocId: null,  // 현재 로드된 문헌 ID
  currentPartId: null, // 현재 로드된 권 ID
  filterMode: 0,       // 이미지 필터: 0=원본, 1=흑백, 2=고대비, 3=반전
  rotation: 0,         // 회전 각도: 0, 90, 180, 270
  fitMode: "width",    // 자동 맞춤: "width" | "height" | "none"
};


/* ──────────────────────────
   이미지 필터 (Feature 1)
   ──────────────────────────
   바래진 고서 이미지를 흑백/반전으로 보면 글자가 더 잘 보인다.
   CSS filter를 #pdf-canvas에만 적용하여 오버레이 블록 색상은 유지한다.
*/

const FILTER_MODES = [
  { name: "원본",  filter: "none" },
  { name: "흑백",  filter: "grayscale(100%)" },
  { name: "고대비", filter: "grayscale(100%) contrast(2.0)" },
  { name: "반전",  filter: "invert(100%)" },
];

/**
 * 이미지 필터를 순환 전환한다.
 * 원본 → 흑백 → 고대비 → 반전 → 원본
 */
function _cycleFilter() {
  pdfState.filterMode = (pdfState.filterMode + 1) % FILTER_MODES.length;
  _applyFilter();
}

/**
 * 현재 filterMode에 따라 CSS filter를 적용한다.
 * canvas.style.filter 사용 — GPU 가속, 비파괴적, 좌표계에 영향 없음.
 */
function _applyFilter() {
  const canvas = document.getElementById("pdf-canvas");
  if (!canvas) return;
  const mode = FILTER_MODES[pdfState.filterMode];
  canvas.style.filter = mode.filter;
  const label = document.getElementById("pdf-filter-label");
  if (label) label.textContent = mode.name !== "원본" ? mode.name : "";
}


/* ──────────────────────────
   이미지 회전 (Feature 2)
   ──────────────────────────
   원본 서적이 옆으로 놓인 경우(족자, 가로형 문서) 회전이 필요하다.
   .pdf-canvas-wrapper에 CSS transform을 적용하여 #pdf-canvas와
   #layout-overlay가 함께 회전한다.
*/

/**
 * 시계 방향 90° 회전.
 */
function _rotateCW() {
  pdfState.rotation = (pdfState.rotation + 90) % 360;
  _applyRotation();
}

/**
 * 반시계 방향 90° 회전.
 */
function _rotateCCW() {
  pdfState.rotation = (pdfState.rotation + 270) % 360;
  _applyRotation();
}

/**
 * 현재 rotation 값에 따라 CSS transform을 적용한다.
 * 90°/270°에서는 wrapper의 margin으로 너비↔높이 교환 효과를 보정한다.
 */
function _applyRotation() {
  const wrapper = document.getElementById("pdf-canvas-wrapper");
  if (!wrapper) return;

  const deg = pdfState.rotation;
  wrapper.style.transform = deg === 0 ? "" : `rotate(${deg}deg)`;

  // 90°/270°에서 너비↔높이가 뒤바뀌므로 마진으로 보정
  if (deg === 90 || deg === 270) {
    const canvas = document.getElementById("pdf-canvas");
    if (canvas && canvas.style.width) {
      const w = parseInt(canvas.style.width, 10);
      const h = parseInt(canvas.style.height, 10);
      if (w && h) {
        const diff = (h - w) / 2;
        wrapper.style.margin = `${diff}px ${-diff}px`;
      }
    }
  } else {
    wrapper.style.margin = "";
  }

  // 회전 각도 라벨 표시
  const label = document.getElementById("pdf-rotation-label");
  if (label) label.textContent = deg === 0 ? "" : `${deg}°`;
}


/**
 * PDF를 로드하고 특정 페이지를 렌더링한다.
 *
 * 호출: sidebar-tree.js의 selectPage()에서 호출된다.
 * 동작:
 *   1. 같은 doc_id + part_id면 PDF 재로드 없이 페이지만 이동
 *   2. 다른 doc_id/part_id면 새 PDF를 로드
 *   3. placeholder를 숨기고 뷰어를 표시
 *
 * 왜 이렇게 하는가: PDF 로드는 네트워크 비용이 크므로,
 *                    같은 문서면 페이지 이동만 수행한다.
 */
// eslint-disable-next-line no-unused-vars
async function loadPdfPage(docId, partId, pageNum) {
  // placeholder 숨기기, 뷰어 표시
  document.getElementById("pdf-placeholder").style.display = "none";
  document.getElementById("pdf-viewer").style.display = "flex";

  // 같은 PDF면 페이지 이동만
  if (
    pdfState.currentDocId === docId &&
    pdfState.currentPartId === partId &&
    pdfState.pdfDoc
  ) {
    await _renderPage(pageNum);
    return;
  }

  // 새 PDF 로드
  const url = `/api/documents/${docId}/pdf/${partId}`;
  try {
    const loadingTask = pdfjsLib.getDocument(url);
    pdfState.pdfDoc = await loadingTask.promise;
    pdfState.totalPages = pdfState.pdfDoc.numPages;
    pdfState.currentDocId = docId;
    pdfState.currentPartId = partId;

    // UI 업데이트
    document.getElementById("pdf-page-total").textContent =
      `/ ${pdfState.totalPages}`;
    const pageInput = document.getElementById("pdf-page-input");
    pageInput.max = pdfState.totalPages;

    // 첫 로드 시 사용자가 선택한 맞춤 모드로 자동 맞춤
    await _autoFit();
    await _renderPage(pageNum);
    _updateFitLabel();
  } catch (err) {
    console.error("PDF 로드 실패:", err);
    const container = document.getElementById("pdf-canvas-container");
    // PDF가 없는 문헌 (HWP 전용 등)이면 친절한 메시지 표시
    container.innerHTML =
      '<div class="placeholder" style="text-align:center;padding:40px 20px;color:#888;">' +
      '<div style="font-size:24px;margin-bottom:8px;">📄</div>' +
      '<div>PDF를 불러올 수 없습니다.</div>' +
      '<div style="font-size:11px;margin-top:4px;color:#aaa;">HWP 전용 문헌이면 우측 텍스트 패널을 확인하세요.</div>' +
      '</div>';
    pdfState.pdfDoc = null;
    pdfState.currentDocId = null;
    pdfState.currentPartId = null;
  }
}


/**
 * 특정 페이지를 Canvas에 렌더링한다.
 *
 * 왜 이렇게 하는가: PDF.js의 render()는 비동기이므로,
 *                    렌더링 중에 새 요청이 들어오면 대기열에 넣는다.
 */
async function _renderPage(pageNum) {
  if (!pdfState.pdfDoc) return;
  if (pageNum < 1 || pageNum > pdfState.totalPages) return;

  // 렌더링 중이면 대기열에 등록
  if (pdfState.rendering) {
    pdfState.pendingPage = pageNum;
    return;
  }

  pdfState.rendering = true;
  pdfState.currentPage = pageNum;

  // 로딩 인디케이터 표시
  const loadingEl = document.getElementById("pdf-loading-indicator");
  if (loadingEl) loadingEl.style.display = "";

  try {
    const page = await pdfState.pdfDoc.getPage(pageNum);
    const viewport = page.getViewport({ scale: pdfState.scale });

    const canvas = document.getElementById("pdf-canvas");
    const ctx = canvas.getContext("2d");

    // 고해상도 디스플레이 지원 (HiDPI/Retina)
    const outputScale = window.devicePixelRatio || 1;
    canvas.width = Math.floor(viewport.width * outputScale);
    canvas.height = Math.floor(viewport.height * outputScale);
    canvas.style.width = Math.floor(viewport.width) + "px";
    canvas.style.height = Math.floor(viewport.height) + "px";

    const transform =
      outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : null;

    await page.render({
      canvasContext: ctx,
      viewport: viewport,
      transform: transform,
    }).promise;
  } catch (err) {
    console.error("페이지 렌더링 실패:", err);
  }

  pdfState.rendering = false;

  // 로딩 인디케이터 숨김
  if (loadingEl) loadingEl.style.display = "none";

  // UI 업데이트
  document.getElementById("pdf-page-input").value = pageNum;

  // Phase 4: PDF 렌더링 완료 후 레이아웃 오버레이 크기 동기화
  if (typeof _syncOverlaySize === "function") {
    _syncOverlaySize();
  }
  if (typeof _redrawOverlay === "function" && typeof layoutState !== "undefined" && layoutState.active) {
    _redrawOverlay();
  }

  // 렌더링 완료 후 회전/필터 상태 재적용
  if (pdfState.rotation !== 0) _applyRotation();
  if (pdfState.filterMode !== 0) _applyFilter();

  // 이전/다음 버튼 상태 갱신
  _updateNavButtonStates();

  // 대기 중인 페이지가 있으면 렌더링
  if (pdfState.pendingPage !== null) {
    const pending = pdfState.pendingPage;
    pdfState.pendingPage = null;
    await _renderPage(pending);
  }

  // 인접 페이지 프리로드 (렌더링 없이 PDF.js 내부 캐시 워밍)
  _preloadAdjacentPages(pageNum);
}


/**
 * 인접 페이지를 프리로드한다 (렌더링 없이 PDF.js 내부 캐시만 워밍).
 *
 * 왜 이렇게 하는가: PDF.js의 getPage()는 내부적으로 페이지 데이터를 파싱/캐시한다.
 *   미리 호출해두면 다음 페이지 이동 시 파싱 시간이 줄어 체감 속도가 빨라진다.
 */
function _preloadAdjacentPages(currentPage) {
  if (!pdfState.pdfDoc) return;
  const pages = [currentPage - 1, currentPage + 1];
  for (const p of pages) {
    if (p >= 1 && p <= pdfState.totalPages) {
      // 비동기 호출, 결과는 무시 (캐시 워밍 목적)
      pdfState.pdfDoc.getPage(p).catch(() => {});
    }
  }
}


/**
 * 줌 레벨을 변경하고 현재 페이지를 다시 렌더링한다.
 */
function _setZoom(newScale) {
  pdfState.scale = Math.max(0.25, Math.min(5.0, newScale));
  document.getElementById("pdf-zoom-level").textContent =
    Math.round(pdfState.scale * 100) + "%";
  _renderPage(pdfState.currentPage);
}


/**
 * 캔버스 컨테이너 너비에 맞춰 줌을 조정한다.
 *
 * 왜 이렇게 하는가: PDF를 처음 로드할 때 컨테이너 너비에 맞추면
 *                    가로 스크롤 없이 편하게 볼 수 있다.
 */
async function _fitToWidth() {
  if (!pdfState.pdfDoc) return;
  const page = await pdfState.pdfDoc.getPage(pdfState.currentPage || 1);
  const viewport = page.getViewport({ scale: 1.0 });
  const container = document.getElementById("pdf-canvas-container");
  // 패딩과 스크롤바 여유분 20px
  const newScale = (container.clientWidth - 20) / viewport.width;
  _setZoom(newScale);
}


/**
 * 캔버스 컨테이너 높이에 맞춰 줌을 조정한다.
 *
 * 왜 이렇게 하는가: 세로로 긴 고전 텍스트 페이지를 한 화면에 넣으면
 *   전체 페이지를 한눈에 볼 수 있어 읽기 편하다.
 */
async function _fitToHeight() {
  if (!pdfState.pdfDoc) return;
  const page = await pdfState.pdfDoc.getPage(pdfState.currentPage || 1);
  const viewport = page.getViewport({ scale: 1.0 });
  const container = document.getElementById("pdf-canvas-container");
  // 패딩 여유분 20px
  const newScale = (container.clientHeight - 20) / viewport.height;
  _setZoom(newScale);
}


/**
 * 현재 fitMode에 따라 자동 맞춤을 적용한다.
 *
 * 왜 이렇게 하는가: 페이지를 전환할 때마다 사용자가 선택한 맞춤 모드를
 *   자동으로 재적용하여 일관된 보기 경험을 제공한다.
 *   수동 줌 시에는 fitMode="none"으로 전환되어 자동 맞춤이 중단된다.
 */
async function _autoFit() {
  if (pdfState.fitMode === "width") {
    await _fitToWidth();
  } else if (pdfState.fitMode === "height") {
    await _fitToHeight();
  }
  // "none"이면 아무것도 하지 않음
}


/**
 * 맞춤 모드를 순환한다: 가로맞춤 → 세로맞춤 → 해제 → 가로맞춤.
 */
function _cycleFitMode() {
  if (pdfState.fitMode === "width") {
    pdfState.fitMode = "height";
    _fitToHeight();
  } else if (pdfState.fitMode === "height") {
    pdfState.fitMode = "none";
  } else {
    pdfState.fitMode = "width";
    _fitToWidth();
  }
  _updateFitLabel();
}


/**
 * 맞춤 모드 라벨을 업데이트한다.
 */
function _updateFitLabel() {
  const label = document.getElementById("pdf-fit-label");
  if (!label) return;
  if (pdfState.fitMode === "width") {
    label.textContent = "가로맞춤";
  } else if (pdfState.fitMode === "height") {
    label.textContent = "세로맞춤";
  } else {
    label.textContent = "";
  }
}


/**
 * PDF 뷰어에서 페이지가 변경될 때, 모든 패널을 동기화한다.
 *
 * 왜 이렇게 하는가: PDF 뷰어의 이전/다음 버튼, 키보드 단축키 등으로
 *   페이지를 이동할 때 교정·해석·비고 등 모든 패널이 갱신되어야 한다.
 *   실제 동기화 로직은 workspace.js의 onPageChanged()에 집약.
 */
function _syncPageChange(pageNum) {
  // 비저장 변경 확인
  if (typeof checkUnsavedChanges === "function" && !checkUnsavedChanges()) {
    // 이전 페이지로 되돌리기
    _renderPage(viewerState.pageNum);
    return;
  }

  viewerState.pageNum = pageNum;

  // 공통 동기화 함수 호출 (workspace.js에서 정의)
  if (typeof onPageChanged === "function") {
    onPageChanged();
  }
}


/**
 * 이전/다음 페이지 버튼의 활성/비활성 상태를 업데이트한다.
 *
 * 왜 이렇게 하는가:
 *   첫 페이지에서 "이전" 버튼, 마지막 페이지에서 "다음" 버튼을 비활성화하여
 *   연구자에게 경계임을 시각적으로 알려준다.
 */
function _updateNavButtonStates() {
  const prevBtn = document.getElementById("pdf-prev");
  const nextBtn = document.getElementById("pdf-next");
  if (!prevBtn || !nextBtn) return;

  prevBtn.disabled = (pdfState.currentPage <= 1);
  nextBtn.disabled = (pdfState.currentPage >= pdfState.totalPages);
}


/**
 * 다권본 선택기를 업데이트한다.
 *
 * 목적: 다권본 문헌에서 권을 전환할 때 사용하는 <select> 드롭다운을 채운다.
 * 입력:
 *   parts — manifest의 parts 배열.
 *   selectedPartId — 현재 선택된 part_id.
 */
// eslint-disable-next-line no-unused-vars
function updatePartSelector(parts, selectedPartId) {
  const select = document.getElementById("pdf-part-select");
  select.innerHTML = "";

  parts.forEach((part) => {
    const option = document.createElement("option");
    option.value = part.part_id;
    option.textContent = `${part.label || part.part_id}`;
    if (part.part_id === selectedPartId) {
      option.selected = true;
    }
    select.appendChild(option);
  });

  // 단권본이면 select 숨김
  select.style.display = parts.length <= 1 ? "none" : "";
}


/**
 * PDF 뷰어의 이벤트 리스너를 초기화한다.
 *
 * DOMContentLoaded 시 workspace.js에서 호출된다.
 */
// eslint-disable-next-line no-unused-vars
function initPdfRenderer() {
  // PDF.js가 로드되었는지 확인
  if (typeof pdfjsLib === "undefined") {
    console.warn("PDF.js가 로드되지 않았습니다. PDF 뷰어를 사용할 수 없습니다.");
    return;
  }

  // 이전 페이지 버튼
  document.getElementById("pdf-prev").addEventListener("click", () => {
    if (pdfState.currentPage > 1) {
      const newPage = pdfState.currentPage - 1;
      _renderPage(newPage);
      _syncPageChange(newPage);
    }
  });

  // 다음 페이지 버튼
  document.getElementById("pdf-next").addEventListener("click", () => {
    if (pdfState.currentPage < pdfState.totalPages) {
      const newPage = pdfState.currentPage + 1;
      _renderPage(newPage);
      _syncPageChange(newPage);
    }
  });

  // 페이지 번호 직접 입력
  document.getElementById("pdf-page-input").addEventListener("change", (e) => {
    const page = parseInt(e.target.value, 10);
    if (page >= 1 && page <= pdfState.totalPages) {
      _renderPage(page);
      _syncPageChange(page);
    } else {
      // 범위 외 값은 현재 페이지로 되돌림
      e.target.value = pdfState.currentPage;
    }
  });

  // 줌 확대 버튼 — 수동 줌이므로 자동 맞춤 해제
  document.getElementById("pdf-zoom-in").addEventListener("click", () => {
    pdfState.fitMode = "none";
    _updateFitLabel();
    _setZoom(pdfState.scale + 0.25);
  });

  // 줌 축소 버튼 — 수동 줌이므로 자동 맞춤 해제
  document.getElementById("pdf-zoom-out").addEventListener("click", () => {
    pdfState.fitMode = "none";
    _updateFitLabel();
    _setZoom(pdfState.scale - 0.25);
  });

  // 맞춤 모드 순환 버튼: 가로맞춤 → 세로맞춤 → 해제 → 가로맞춤
  document.getElementById("pdf-zoom-fit").addEventListener("click", () => {
    _cycleFitMode();
  });

  // Ctrl+스크롤로 줌 — 수동 줌이므로 자동 맞춤 해제
  document
    .getElementById("pdf-canvas-container")
    .addEventListener(
      "wheel",
      (e) => {
        if (e.ctrlKey) {
          e.preventDefault();
          pdfState.fitMode = "none";
          _updateFitLabel();
          const delta = e.deltaY > 0 ? -0.1 : 0.1;
          _setZoom(pdfState.scale + delta);
        }
      },
      { passive: false }
    );

  // 이미지 필터 전환 버튼 (Feature 1)
  const filterBtn = document.getElementById("pdf-filter-btn");
  if (filterBtn) filterBtn.addEventListener("click", _cycleFilter);

  // 회전 버튼 (Feature 2)
  const rotateCwBtn = document.getElementById("pdf-rotate-cw");
  if (rotateCwBtn) rotateCwBtn.addEventListener("click", _rotateCW);
  const rotateCcwBtn = document.getElementById("pdf-rotate-ccw");
  if (rotateCcwBtn) rotateCcwBtn.addEventListener("click", _rotateCCW);

  // 다권본 권 변경 이벤트
  document.getElementById("pdf-part-select").addEventListener("change", (e) => {
    const newPartId = e.target.value;

    // 비저장 변경 확인
    if (typeof checkUnsavedChanges === "function" && !checkUnsavedChanges()) {
      e.target.value = viewerState.partId;
      return;
    }

    viewerState.partId = newPartId;
    viewerState.pageNum = 1;

    loadPdfPage(viewerState.docId, newPartId, 1);

    if (typeof loadPageText === "function") {
      loadPageText(viewerState.docId, newPartId, 1);
    }
  });


  /* ──────────────────────────
     키보드 단축키 (Plan 2)
     ──────────────────────────
     ↑/↓: 페이지 이전/다음 (PDF가 뷰포트 안에 다 보일 때만 — 줌인 상태에서는 스크롤 우선)
     PageUp/PageDown: 페이지 이전/다음 (항상)
     Home/End: 첫/마지막 페이지 (항상)

     왜 ←/→가 아닌 ↑/↓인가:
       고전 한문은 우→좌로 읽는 책이 많아서 ←/→의 "이전/다음" 의미가 모호하다.
       ↑/↓는 방향 중립적이라 혼동이 없다.
  */
  document.addEventListener("keydown", (e) => {
    // PDF가 로드되지 않았으면 무시
    if (!pdfState.pdfDoc) return;

    // 입력 필드 포커스 시 무시 (reader-line.js R키 패턴 준용)
    const tag = document.activeElement?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (document.activeElement?.isContentEditable) return;

    // 다이얼로그 오버레이가 열려 있으면 무시
    const overlays = document.querySelectorAll(".bib-dialog-overlay, .corr-dialog-overlay");
    for (const ov of overlays) {
      if (ov.style.display !== "none" && ov.style.display !== "") return;
    }

    let targetPage = null;

    switch (e.key) {
      case "ArrowUp":
      case "ArrowDown": {
        // 줌인 상태(스크롤 가능)에서는 스크롤 우선, 페이지 전환하지 않음
        const container = document.getElementById("pdf-canvas-container");
        if (container && container.scrollHeight > container.clientHeight + 2) return;
        targetPage = e.key === "ArrowUp"
          ? pdfState.currentPage - 1
          : pdfState.currentPage + 1;
        break;
      }
      case "PageUp":
        targetPage = pdfState.currentPage - 1;
        break;
      case "PageDown":
        targetPage = pdfState.currentPage + 1;
        break;
      case "Home":
        targetPage = 1;
        break;
      case "End":
        targetPage = pdfState.totalPages;
        break;
      default:
        return; // 처리하지 않는 키는 기본 동작 유지
    }

    // 범위 확인 후 페이지 이동
    if (targetPage !== null && targetPage >= 1 && targetPage <= pdfState.totalPages && targetPage !== pdfState.currentPage) {
      e.preventDefault();
      _renderPage(targetPage);
      _syncPageChange(targetPage);
    } else if (targetPage !== null) {
      // 경계에서 기본 동작 방지 (PageUp/Down의 스크롤 등)
      e.preventDefault();
    }
  });
}
