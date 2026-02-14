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
};


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

    // 첫 로드 시 너비에 맞추기
    await _fitToWidth();
    await _renderPage(pageNum);
  } catch (err) {
    console.error("PDF 로드 실패:", err);
    const container = document.getElementById("pdf-canvas-container");
    container.innerHTML =
      '<div class="placeholder">PDF를 불러올 수 없습니다</div>';
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

  // UI 업데이트
  document.getElementById("pdf-page-input").value = pageNum;

  // 대기 중인 페이지가 있으면 렌더링
  if (pdfState.pendingPage !== null) {
    const pending = pdfState.pendingPage;
    pdfState.pendingPage = null;
    await _renderPage(pending);
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
 * PDF 뷰어에서 페이지가 변경될 때, 텍스트 에디터와 사이드바를 동기화한다.
 *
 * 왜 이렇게 하는가: PDF 뷰어의 이전/다음 버튼으로 페이지를 이동할 때,
 *                    우측 텍스트 에디터도 같은 페이지를 표시해야 한다.
 */
function _syncPageChange(pageNum) {
  // 비저장 변경 확인
  if (typeof checkUnsavedChanges === "function" && !checkUnsavedChanges()) {
    // 이전 페이지로 되돌리기
    _renderPage(viewerState.pageNum);
    return;
  }

  viewerState.pageNum = pageNum;

  // 우측 텍스트 에디터 동기화
  if (typeof loadPageText === "function") {
    loadPageText(viewerState.docId, viewerState.partId, pageNum);
  }

  // 사이드바 하이라이트 동기화
  if (typeof highlightTreePage === "function") {
    highlightTreePage(pageNum);
  }
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

  // 줌 확대 버튼
  document.getElementById("pdf-zoom-in").addEventListener("click", () => {
    _setZoom(pdfState.scale + 0.25);
  });

  // 줌 축소 버튼
  document.getElementById("pdf-zoom-out").addEventListener("click", () => {
    _setZoom(pdfState.scale - 0.25);
  });

  // 너비에 맞추기 버튼
  document.getElementById("pdf-zoom-fit").addEventListener("click", () => {
    _fitToWidth();
  });

  // Ctrl+스크롤로 줌
  document
    .getElementById("pdf-canvas-container")
    .addEventListener(
      "wheel",
      (e) => {
        if (e.ctrlKey) {
          e.preventDefault();
          const delta = e.deltaY > 0 ? -0.1 : 0.1;
          _setZoom(pdfState.scale + delta);
        }
      },
      { passive: false }
    );

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
}
