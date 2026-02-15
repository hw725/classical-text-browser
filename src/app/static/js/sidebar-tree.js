/**
 * 사이드바 트리 뷰 — 문헌 > 권(Part) > 페이지 계층구조
 *
 * 기능:
 *   1. 문헌 목록을 트리 루트로 표시
 *   2. 문헌 클릭 시 API에서 상세 정보를 가져와 parts를 표시
 *   3. part 클릭 시 페이지 목록을 표시 (page_count는 PDF 로드 후 동적 결정)
 *   4. 페이지 클릭 시 좌측(PDF) + 우측(텍스트) 패널을 로드
 *
 * 의존성: 없음 (다른 모듈에서 viewerState를 참조한다)
 *
 * 왜 이렇게 하는가:
 *   - 비개발자 연구자가 문헌 구조를 한눈에 파악할 수 있도록 트리 형태로 표시한다.
 *   - 문헌 > 권 > 페이지의 3단 계층이 platform-v7.md의 다권본 구조와 일치한다.
 */

/* ──────────────────────────
   전역 상태: 현재 선택된 문헌/권/페이지
   다른 JS 모듈(pdf-renderer, text-editor)에서 참조한다.
   ────────────────────────── */

// eslint-disable-next-line no-unused-vars
const viewerState = {
  docId: null,         // 현재 선택된 문헌 ID
  partId: null,        // 현재 선택된 권 ID
  pageNum: null,       // 현재 선택된 페이지 번호 (1부터 시작)
  documentInfo: null,  // 캐시된 문헌 상세 정보 (manifest + pages)
};


/**
 * 사이드바 트리 뷰를 초기화한다.
 *
 * 목적: workspace.js의 loadLibraryInfo()에서 가져온 문헌 목록을
 *       3레벨 트리로 렌더링한다.
 * 입력: docs — 문헌 정보 배열 [{document_id, title, ...}, ...].
 */
// eslint-disable-next-line no-unused-vars
function initSidebarTree(docs) {
  const container = document.getElementById("document-list");

  if (!docs || docs.length === 0) {
    container.innerHTML = '<div class="placeholder">등록된 문헌이 없습니다</div>';
    return;
  }

  container.innerHTML = "";

  docs.forEach((doc) => {
    const docNode = _createDocumentNode(doc);
    container.appendChild(docNode);
  });
}


/**
 * 문헌 노드를 생성한다.
 *
 * 구조:
 *   <div class="tree-node tree-document">
 *     <div class="tree-node-header">
 *       <span class="tree-toggle">▶</span>
 *       <span class="tree-label">世說新語 (더미)</span>
 *       <span class="tree-badge">dummy_shishuo</span>
 *     </div>
 *     <div class="tree-children" style="display:none">
 *       <!-- part 노드들 (클릭 시 동적 생성) -->
 *     </div>
 *   </div>
 */
function _createDocumentNode(doc) {
  const node = document.createElement("div");
  node.className = "tree-node tree-document";
  node.dataset.docId = doc.document_id || "";

  const header = document.createElement("div");
  header.className = "tree-node-header";
  header.innerHTML = `
    <span class="tree-toggle">▶</span>
    <span class="tree-label">${doc.title || "제목 없음"}</span>
    <span class="tree-badge">${doc.document_id || ""}</span>
  `;

  const children = document.createElement("div");
  children.className = "tree-children";
  children.style.display = "none";

  // 문헌 헤더 클릭 → parts 확장/축소
  header.addEventListener("click", () => {
    _toggleDocument(doc.document_id, header, children);
  });

  node.appendChild(header);
  node.appendChild(children);
  return node;
}


/**
 * 문헌 노드를 클릭했을 때 parts를 확장/축소한다.
 *
 * 동작:
 *   - 닫힌 상태: API에서 문헌 상세를 가져와 parts 하위 트리를 생성한다.
 *   - 열린 상태: 하위 트리를 접는다.
 *
 * 왜 이렇게 하는가:
 *   - 문헌 목록은 GET /api/documents 로 가져오지만,
 *     parts 상세는 GET /api/documents/{doc_id} 로 별도 요청해야 한다.
 *   - 첫 클릭 시에만 API를 호출하고, 이후는 캐시된 데이터를 사용한다.
 */
async function _toggleDocument(docId, headerEl, childrenEl) {
  const toggle = headerEl.querySelector(".tree-toggle");
  const isOpen = childrenEl.style.display !== "none";

  if (isOpen) {
    // 접기
    childrenEl.style.display = "none";
    toggle.classList.remove("expanded");
    return;
  }

  // 펼치기
  childrenEl.style.display = "";
  toggle.classList.add("expanded");

  // 이미 로드된 경우 스킵
  if (childrenEl.children.length > 0) return;

  // API에서 문헌 상세 가져오기
  try {
    childrenEl.innerHTML = '<div class="placeholder">불러오는 중...</div>';
    const res = await fetch(`/api/documents/${docId}`);
    if (!res.ok) throw new Error("문헌 상세 API 응답 오류");
    const docInfo = await res.json();

    childrenEl.innerHTML = "";

    if (!docInfo.parts || docInfo.parts.length === 0) {
      childrenEl.innerHTML = '<div class="placeholder">등록된 권이 없습니다</div>';
      return;
    }

    // 각 part에 대한 노드 생성
    docInfo.parts.forEach((part) => {
      const partNode = _createPartNode(docId, part, docInfo);
      childrenEl.appendChild(partNode);
    });
  } catch (err) {
    console.error("문헌 상세 로드 실패:", err);
    childrenEl.innerHTML = '<div class="placeholder">문헌 정보를 불러올 수 없습니다</div>';
  }
}


/**
 * 권(Part) 노드를 생성한다.
 *
 * 구조:
 *   <div class="tree-node tree-part">
 *     <div class="tree-node-header">
 *       <span class="tree-toggle">▶</span>
 *       <span class="tree-label">vol1: dummy_shishuo</span>
 *       <span class="tree-badge">2p</span>
 *     </div>
 *     <div class="tree-children" style="display:none">
 *       <!-- page 노드들 -->
 *     </div>
 *   </div>
 */
function _createPartNode(docId, part, docInfo) {
  const node = document.createElement("div");
  node.className = "tree-node tree-part";
  node.dataset.partId = part.part_id;

  const pageCountLabel = part.page_count
    ? `${part.page_count}p`
    : "?p";

  const header = document.createElement("div");
  header.className = "tree-node-header";
  header.innerHTML = `
    <span class="tree-toggle">▶</span>
    <span class="tree-label">${part.label || part.part_id}</span>
    <span class="tree-badge">${pageCountLabel}</span>
  `;

  const children = document.createElement("div");
  children.className = "tree-children";
  children.style.display = "none";

  // part 헤더 클릭 → 페이지 목록 확장/축소
  header.addEventListener("click", (e) => {
    e.stopPropagation();
    _togglePart(docId, part, docInfo, header, children);
  });

  node.appendChild(header);
  node.appendChild(children);
  return node;
}


/**
 * 권 노드를 클릭했을 때 페이지 목록을 확장/축소한다.
 *
 * page_count 처리:
 *   - manifest에 page_count가 있으면 그대로 사용한다.
 *   - page_count가 null이면, PDF를 백그라운드로 로드하여 페이지 수를 파악한다.
 *     (PDF.js의 pdfDoc.numPages 활용)
 */
async function _togglePart(docId, part, docInfo, headerEl, childrenEl) {
  const toggle = headerEl.querySelector(".tree-toggle");
  const isOpen = childrenEl.style.display !== "none";

  if (isOpen) {
    childrenEl.style.display = "none";
    toggle.classList.remove("expanded");
    return;
  }

  childrenEl.style.display = "";
  toggle.classList.add("expanded");

  // 이미 로드된 경우 스킵
  if (childrenEl.children.length > 0) return;

  let pageCount = part.page_count;

  // page_count가 null이면 PDF에서 파악
  if (!pageCount) {
    try {
      childrenEl.innerHTML = '<div class="placeholder">페이지 수 확인 중...</div>';
      pageCount = await _getPageCountFromPdf(docId, part.part_id);
      // 뱃지 업데이트
      const badge = headerEl.querySelector(".tree-badge");
      if (badge) badge.textContent = `${pageCount}p`;
    } catch (err) {
      console.error("페이지 수 확인 실패:", err);
      childrenEl.innerHTML = '<div class="placeholder">페이지 수를 확인할 수 없습니다</div>';
      return;
    }
  }

  childrenEl.innerHTML = "";

  // 페이지 노드 생성
  for (let i = 1; i <= pageCount; i++) {
    const pageNode = _createPageNode(docId, part.part_id, i, docInfo);
    childrenEl.appendChild(pageNode);
  }
}


/**
 * PDF.js로 PDF의 페이지 수를 파악한다.
 *
 * 왜 이렇게 하는가: manifest의 page_count가 null인 경우 (아직 파악되지 않은 경우),
 *                    PDF 파일을 부분적으로 로드하여 총 페이지 수만 확인한다.
 */
async function _getPageCountFromPdf(docId, partId) {
  // PDF.js가 로드되어 있는지 확인
  if (typeof pdfjsLib === "undefined") {
    throw new Error("PDF.js가 로드되지 않았습니다");
  }

  const url = `/api/documents/${docId}/pdf/${partId}`;
  const loadingTask = pdfjsLib.getDocument(url);
  const pdfDoc = await loadingTask.promise;
  const numPages = pdfDoc.numPages;
  pdfDoc.destroy();
  return numPages;
}


/**
 * 페이지 노드를 생성한다.
 *
 * 구조:
 *   <div class="tree-node tree-page" data-page="1">
 *     <span class="tree-page-icon">📄</span>
 *     <span class="tree-label">1페이지</span>
 *   </div>
 */
function _createPageNode(docId, partId, pageNum, docInfo) {
  const node = document.createElement("div");
  node.className = "tree-node tree-page";
  node.dataset.page = pageNum;
  node.dataset.docId = docId;
  node.dataset.partId = partId;

  node.innerHTML = `
    <span class="tree-page-icon"></span>
    <span class="tree-label">${pageNum}페이지</span>
  `;

  // 페이지 클릭 → PDF + 텍스트 로드
  node.addEventListener("click", (e) => {
    e.stopPropagation();
    _selectPage(docId, partId, pageNum, docInfo, node);
  });

  return node;
}


/**
 * 페이지를 선택한다.
 *
 * 동작:
 *   1. viewerState를 업데이트한다.
 *   2. 사이드바에서 선택된 페이지를 하이라이트한다.
 *   3. 좌측 PDF 렌더러에 해당 페이지를 로드한다.
 *   4. 우측 텍스트 에디터에 해당 페이지의 텍스트를 로드한다.
 */
function _selectPage(docId, partId, pageNum, docInfo, pageNode) {
  // 비저장 변경 확인 (text-editor.js에서 정의)
  if (typeof checkUnsavedChanges === "function" && !checkUnsavedChanges()) {
    return;
  }

  // viewerState 업데이트
  viewerState.docId = docId;
  viewerState.partId = partId;
  viewerState.pageNum = pageNum;
  viewerState.documentInfo = docInfo;

  // 사이드바 하이라이트 업데이트
  _highlightPage(pageNode);

  // 좌측: PDF 로드 (pdf-renderer.js에서 정의)
  if (typeof loadPdfPage === "function") {
    loadPdfPage(docId, partId, pageNum);
  }

  // 우측: 텍스트 로드 (text-editor.js에서 정의)
  if (typeof loadPageText === "function") {
    loadPageText(docId, partId, pageNum);
  }

  // Phase 4: 레이아웃 모드일 때 레이아웃도 로드
  if (typeof loadPageLayout === "function" && typeof layoutState !== "undefined" && layoutState.active) {
    loadPageLayout(docId, partId, pageNum);
  }

  // 다권본: part 선택기 업데이트 (pdf-renderer.js에서 정의)
  if (typeof updatePartSelector === "function" && docInfo && docInfo.parts) {
    updatePartSelector(docInfo.parts, partId);
  }

  // Phase 6: 교정 모드일 때 교정 데이터도 로드
  if (typeof loadPageCorrections === "function" && typeof correctionState !== "undefined" && correctionState.active) {
    loadPageCorrections(docId, partId, pageNum);
  }

  // Phase 6: Git 이력 로드
  if (typeof _loadGitLog === "function") {
    _loadGitLog(docId);
  }

  // Phase 5: 서지정보 로드 (bibliography.js에서 정의)
  if (typeof loadBibliography === "function") {
    loadBibliography(docId);
  }

  // Phase 7: 해석 모드일 때 층 내용 로드
  if (typeof interpState !== "undefined" && interpState.active && interpState.interpId) {
    if (typeof _loadLayerContent === "function") {
      _loadLayerContent();
    }
  }

  // Phase 10-1: 레이아웃 모드일 때 기존 OCR 결과 로드
  if (typeof loadOcrResults === "function" && typeof layoutState !== "undefined" && layoutState.active) {
    loadOcrResults();
  }
}


/**
 * 사이드바에서 선택된 페이지를 하이라이트한다.
 */
function _highlightPage(pageNode) {
  // 기존 하이라이트 제거
  document.querySelectorAll(".tree-page.active").forEach((el) => {
    el.classList.remove("active");
  });
  // 새 하이라이트
  pageNode.classList.add("active");
}


/**
 * 외부에서 페이지 하이라이트를 업데이트할 때 사용한다.
 * (PDF 뷰어에서 이전/다음 페이지 이동 시 사이드바 동기화)
 */
// eslint-disable-next-line no-unused-vars
function highlightTreePage(pageNum) {
  document.querySelectorAll(".tree-page.active").forEach((el) => {
    el.classList.remove("active");
  });

  const target = document.querySelector(
    `.tree-page[data-page="${pageNum}"][data-doc-id="${viewerState.docId}"][data-part-id="${viewerState.partId}"]`
  );
  if (target) {
    target.classList.add("active");
    // 스크롤하여 보이도록
    target.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}
