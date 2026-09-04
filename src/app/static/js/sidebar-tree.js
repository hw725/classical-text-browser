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

/**
 * HTML 특수문자를 이스케이프한다.
 *
 * 왜 이렇게 하는가:
 *   문헌 제목은 «드롭한 파일 이름»에서 그대로 만들어진다(backend documents.py).
 *   즉 사용자가 파일명을 지어 붙이는 순간 그 문자열이 트리 라벨의 innerHTML로
 *   들어간다 — `<img onerror=...>.pdf` 같은 이름이면 그대로 실행된다.
 *   브라우저의 textContent 경로를 빌려 «태그가 될 수 있는 글자»를 전부 무해한
 *   엔티티로 바꾼 뒤 innerHTML에 넣는다.
 *
 * 이름에 tree를 붙인 까닭:
 *   이 프로젝트의 JS 파일들은 모듈이 아니라 <script>로 나란히 읽히므로
 *   함수 이름이 «전부 하나의 전역 공간»을 공유한다. 다른 파일에도 _escHtml이
 *   여럿 있어서, 같은 이름을 쓰면 나중에 읽힌 파일의 것이 이겨 버린다.
 *
 * 입력: str — 임의의 문자열(null/undefined 허용)
 * 출력: HTML에 그대로 끼워 넣어도 안전한 문자열
 */
function _treeEscHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}


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
    <span class="tree-label">${_treeEscHtml(doc.title || "제목 없음")}</span>
    <span class="tree-badge">${_treeEscHtml(doc.document_id || "")}</span>
    <button class="tree-addpart-btn" title="이 문헌에 권 추가 (PDF)">＋</button>
    <button class="tree-delete-btn" title="문헌 삭제 (휴지통 이동)">×</button>
  `;

  const children = document.createElement("div");
  children.className = "tree-children";
  children.style.display = "none";

  // 권 추가 버튼 클릭 → PDF 고르기
  const addBtn = header.querySelector(".tree-addpart-btn");
  addBtn.addEventListener("click", (e) => {
    e.stopPropagation(); // 문헌 펼침 방지
    _addPartToDocument(doc.document_id, node, children);
  });

  // 삭제 버튼 클릭 → 휴지통 이동
  const deleteBtn = header.querySelector(".tree-delete-btn");
  deleteBtn.addEventListener("click", (e) => {
    e.stopPropagation(); // 문헌 펼침 방지
    _trashDocument(doc.document_id, doc.title || doc.document_id);
  });

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

    // 권이 하나뿐이면 그 단계를 건너뛰고 쪽을 문헌 바로 아래에 붙인다.
    //
    // 왜: 문헌 → 권 → 쪽은 여러 권으로 나뉜 고서(蒙求 등) 때문에 필요한
    // 구조다. 그러나 논문이나 단권 문헌은 권이 언제나 하나여서, 그 단계가
    // 아무 정보도 주지 않으면서 클릭만 한 번 더 요구한다.
    //
    // **데이터는 그대로 두고 표시만 접는다** — manifest의 parts는 손대지
    // 않으므로 여러 권 문헌은 예전과 똑같이 보인다. (D-055가 작업 모드에서
    // 쓴 것과 같은 방식이다.)
    if (docInfo.parts.length === 1) {
      await _renderPageNodes(docId, docInfo.parts[0], docInfo, headerEl, childrenEl);
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
    <span class="tree-label">${_treeEscHtml(part.label || part.part_id)}</span>
    <span class="tree-badge">${_treeEscHtml(pageCountLabel)}</span>
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

  await _renderPageNodes(docId, part, docInfo, headerEl, childrenEl);
}


/**
 * 쪽 노드를 채운다 (펼침/접힘 판단은 하지 않는다).
 *
 * 왜 따로 떼는가:
 *   권이 하나뿐인 문헌은 권 단계를 건너뛰고 문헌 아래에 쪽을 바로 붙인다.
 *   그때 _togglePart를 그대로 부르면 «이미 펼쳐져 있다»고 보고 곧바로 접어
 *   버린다(문헌 노드를 펼치면서 display를 이미 비워 뒀기 때문이다).
 *   채우는 일만 하는 함수가 따로 있어야 두 경로가 같은 코드를 쓴다.
 */
async function _renderPageNodes(docId, part, docInfo, headerEl, childrenEl) {
  // 이미 로드된 경우 스킵
  if (childrenEl.children.length > 0) return;

  let pageCount = part.page_count;

  // page_count가 null이면 PDF에서 파악, PDF 없으면 API에서 L4 텍스트 페이지 수 파악
  if (!pageCount) {
    try {
      childrenEl.innerHTML = '<div class="placeholder">페이지 수 확인 중...</div>';
      pageCount = await _getPageCountFromPdf(docId, part.part_id);
    } catch {
      // PDF 없음 (HWP 전용 문헌 등) → API에서 페이지 수 파악
      try {
        pageCount = await _getPageCountFromApi(docId);
      } catch (err2) {
        console.error("페이지 수 확인 실패:", err2);
        childrenEl.innerHTML = '<div class="placeholder">페이지 수를 확인할 수 없습니다</div>';
        return;
      }
    }
    // 뱃지 업데이트 — **권 노드일 때만.**
    //
    // 권이 하나뿐이라 이 함수를 문헌 노드에서 부른 경우 headerEl은 문헌
    // 헤더이고, 그 뱃지에는 문헌 ID가 들어 있다. 덮어쓰면 문헌 ID가 사라진다.
    if (pageCount && headerEl.closest(".tree-part")) {
      const badge = headerEl.querySelector(".tree-badge");
      if (badge) badge.textContent = `${pageCount}p`;
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
 * API에서 문헌의 페이지 수를 파악한다 (PDF 없을 때 폴백).
 *
 * 왜 이렇게 하는가: HWP 전용 문헌은 PDF가 없어 PDF.js로 페이지 수를 알 수 없다.
 *                    대신 GET /api/documents/{doc_id} 응답의 pages 배열 길이를 사용한다.
 *                    (서버에서 L4_text/pages/의 .txt 파일을 폴백으로 열거한다)
 */
async function _getPageCountFromApi(docId) {
  const res = await fetch(`/api/documents/${docId}`);
  if (!res.ok) throw new Error("문헌 상세 API 응답 오류");
  const docInfo = await res.json();
  const pages = docInfo.pages || [];
  if (pages.length === 0) throw new Error("페이지 없음");
  return pages.length;
}


/**
 * 페이지 노드를 생성한다.
 *
 * 구조:
 *   <div class="tree-node tree-page" data-page="1">
 *     <span class="tree-page-icon"></span>  ← 아이콘은 CSS ::before(▪)로 그린다
 *     <span class="tree-label">1페이지</span>
 *   </div>
 */
function _createPageNode(docId, partId, pageNum, docInfo) {
  const node = document.createElement("div");
  node.className = "tree-node tree-page";
  node.dataset.page = pageNum;
  node.dataset.docId = docId;
  node.dataset.partId = partId;

  // 쪽은 번호만 격자로(208쪽을 한 줄씩 세우면 아래 섹션이 화면 밖으로 밀린다 — 2026-09-03 실측)
  node.title = `${pageNum}쪽`;
  node.innerHTML = `<span class="tree-label">${pageNum}</span>`;

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
  const previousDocId = viewerState.docId;
  viewerState.docId = docId;
  viewerState.partId = partId;
  viewerState.pageNum = pageNum;
  viewerState.documentInfo = docInfo;
  if (typeof updateModeBarContext === "function") updateModeBarContext();

  // 문헌이 바뀌면 그 문헌의 작업 프로필(고서/논문)을 따라간다.
  // 한 서고에 고서와 논문이 섞여 있으므로 문헌마다 기억해야 쓸모가 있다.
  if (previousDocId !== docId && typeof applyProfileForDocument === "function") {
    applyProfileForDocument(docId);
  }
  // 문헌이 바뀌면 저장소 목록을 다시 읽어 그 문헌 것으로 잇는다.
  // 목록을 다시 읽지 않으면 앞 문헌의 저장소가 그대로 붙어 있었다(실측 2026-09-04).
  if (previousDocId !== docId && typeof _loadInterpretationList === "function") {
    _loadInterpretationList();
  }
  // 추출 패널은 열린 권(part)을 대상으로 진단하므로 권이 바뀌어도 갱신한다.
  if (typeof refreshExtractPanel === "function") {
    refreshExtractPanel(false);
  }

  // 사이드바 하이라이트 업데이트 (직접 노드 참조가 있으므로 여기서 처리)
  _highlightPage(pageNode);

  // 좌측: PDF 로드 (pdf-renderer.js에서 정의)
  if (typeof loadPdfPage === "function") {
    loadPdfPage(docId, partId, pageNum);
  }

  // 다권본: part 선택기 업데이트 (pdf-renderer.js에서 정의)
  if (typeof updatePartSelector === "function" && docInfo && docInfo.parts) {
    updatePartSelector(docInfo.parts, partId);
  }

  // 공통 동기화: 텍스트, 레이아웃, 교정, Git, 서지, 해석, OCR, 비고 등
  // (workspace.js의 onPageChanged에서 일괄 처리)
  if (typeof onPageChanged === "function") {
    onPageChanged({ skipHighlight: true });  // 하이라이트는 위에서 이미 처리
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
  // 새 하이라이트. 트리를 거치지 않고 이동한 경우 노드가 없을 수 있다.
  if (pageNode) pageNode.classList.add("active");
}


/**
 * 현재 문헌·권에서 지정한 쪽으로 이동한다 (트리 밖에서 부르는 진입점).
 *
 * 입력: pageNum — 1-based 쪽 번호. 출력: 이동했으면 true.
 *
 * 왜 필요한가:
 *   쪽 이동은 지금까지 **트리 노드를 클릭하는 것**으로만 됐다
 *   (`_selectPage`는 docInfo와 노드를 인자로 받는 비공개 함수다).
 *   그래서 추출 패널의 «대조»·«다음 미확인 쪽» 같은 버튼이 이동을
 *   시킬 방법이 없었다. 실제로 그 버튼들이 **조용히 아무 일도 하지
 *   않았다** — `typeof goToPage === "function"` 가드에 걸려 넘어갔기 때문에
 *   오류조차 나지 않았다.
 *
 * 왜 노드를 먼저 찾아 클릭하는가:
 *   그 경로에 저장 확인·프로필 전환·하이라이트가 다 걸려 있다. 직접
 *   `_selectPage`를 부르면 그중 하나를 빠뜨리기 쉽다. 트리가 접혀 있어
 *   노드가 없을 때만 직접 부른다.
 */
// eslint-disable-next-line no-unused-vars
function goToPage(pageNum) {
  if (!viewerState.docId || !viewerState.partId || !pageNum) return false;

  const node = document.querySelector(
    `.tree-page[data-doc-id="${viewerState.docId}"]` +
      `[data-part-id="${viewerState.partId}"][data-page="${pageNum}"]`
  );
  if (node) {
    node.click();
    return true;
  }

  // 트리가 접혀 있어 노드가 없다. 화면은 옮기되 하이라이트는 생략된다.
  _selectPage(
    viewerState.docId,
    viewerState.partId,
    pageNum,
    viewerState.documentInfo,
    null
  );
  return true;
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


/**
 * 이미 있는 문헌에 권(PDF)을 더한다.
 *
 * 왜 필요한가:
 *   `parts`는 지금까지 문헌을 만들 때 한 번 정해지면 끝이었다. 그래서
 *   卷下를 뒤늦게 구하면 문헌을 지우고 처음부터 다시 만들어야 했고,
 *   그러면 이미 한 OCR·교정이 전부 사라졌다.
 *
 *   단권 문헌은 트리에서 권 단계를 접어 두므로(D-060) «권을 더한다»는
 *   자리가 화면에 없다. 그래서 문헌 노드에 버튼을 둔다.
 */
async function _addPartToDocument(docId, nodeEl, childrenEl) {
  // 파일 선택 창을 그때그때 만든다. 숨은 <input>을 마크업에 두면 어느
  // 문헌에 대한 것인지 상태로 들고 있어야 해서 오히려 헷갈린다.
  const picker = document.createElement("input");
  picker.type = "file";
  picker.accept = ".pdf,application/pdf";
  picker.multiple = true;

  picker.addEventListener("change", async () => {
    if (!picker.files || !picker.files.length) return;

    const form = new FormData();
    for (const file of picker.files) form.append("files", file);
    // 파일이 하나일 때만 이름을 물어본다. 여럿이면 각자 자기 파일 이름을 쓴다.
    if (picker.files.length === 1) {
      const stem = picker.files[0].name.replace(/\.pdf$/i, "");
      const label = window.prompt("권 이름을 정하세요 (예: 卷下)", stem);
      if (label === null) return; // 취소
      if (label.trim()) form.append("label", label.trim());
    }

    try {
      const res = await fetch(`/api/documents/${docId}/parts`, {
        method: "POST",
        body: form,
      });
      const data = await res.json();
      if (!res.ok) {
        showToast(data.error || "권을 더하지 못했습니다.", "error");
        return;
      }

      const names = (data.added || []).map((p) => p.label).join(", ");
      showToast(`권 ${data.added.length}개를 더했습니다 — ${names}`, "success");

      // 트리를 다시 그린다. 권이 2개가 되면 접혀 있던 단계가 저절로 펼쳐진다.
      childrenEl.innerHTML = "";
      childrenEl.style.display = "none";
      const toggle = nodeEl.querySelector(".tree-toggle");
      if (toggle) toggle.classList.remove("expanded");
      const header = nodeEl.querySelector(".tree-node-header");
      if (header) _toggleDocument(docId, header, childrenEl);
    } catch (err) {
      showToast(`권 추가 중 오류: ${err.message}`, "error");
    }
  });

  picker.click();
}


/**
 * 문헌을 휴지통으로 이동한다.
 *
 * 왜 이렇게 하는가:
 *   - 영구 삭제 대신 서고 내 .trash/ 폴더로 이동하여 복원 가능하게 한다.
 *   - 연관 해석 저장소가 있으면 추가 경고를 표시한다.
 */
async function _trashDocument(docId, docTitle) {
  // 1단계: 연관 해석 저장소 확인을 위해 먼저 삭제 시도 전 사전 확인
  let msg = `"${docTitle}" 문헌을 삭제(휴지통 이동)하시겠습니까?`;
  if (!confirm(msg)) return;

  try {
    const res = await fetch(`/api/documents/${docId}`, { method: "DELETE" });
    let data;
    try {
      data = await res.json();
    } catch (_) {
      showToast("삭제 실패: 서버 내부 오류", "error");
      return;
    }

    if (!res.ok) {
      showToast(`삭제 실패: ${data.error || "알 수 없는 오류"}`, 'error');
      return;
    }

    // 연관 해석 저장소 경고
    if (data.related_interpretations && data.related_interpretations.length > 0) {
      showToast(
        `문헌이 휴지통으로 이동되었습니다.\n\n` +
        `주의: 다음 해석 저장소가 이 문헌을 참조합니다:\n` +
        data.related_interpretations.map((id) => `  - ${id}`).join("\n"),
        'warning'
      );
    }

    // 현재 선택된 문헌이 삭제된 경우 상태 초기화
    if (viewerState.docId === docId) {
      viewerState.docId = null;
      viewerState.partId = null;
      viewerState.pageNum = null;
      viewerState.documentInfo = null;
    }

    // 사이드바 + 서고 설정 패널 새로고침
    if (typeof loadLibraryInfo === "function") {
      loadLibraryInfo();
    }
    if (typeof _loadSettings === "function") {
      _loadSettings();
    }
  } catch (err) {
    showToast(`삭제 중 오류: ${err.message}`, 'error');
  }
}
