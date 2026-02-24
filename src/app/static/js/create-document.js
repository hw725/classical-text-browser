/**
 * 새 문헌 생성 — URL에서 서지정보 + 이미지 자동 다운로드
 *
 * 기능:
 *   1. 사이드바 "+ 새 문헌" 버튼 → 다이얼로그 열기
 *   2. URL 입력 → "미리보기" → 서지정보 + 에셋(이미지) 목록 표시
 *   3. doc_id 입력 + 에셋 체크박스 선택 → "생성" → 문헌 자동 생성
 *   4. 생성 완료 시 사이드바 트리 갱신
 *
 * 2단계 워크플로우:
 *   [Step 1] URL → preview-from-url → 서지정보 + 에셋 확인
 *   [Step 2] 확인 후 → create-from-url → 실제 생성 (다운로드 포함)
 *
 * 의존성: sidebar-tree.js (initSidebarTree), workspace.js (loadLibraryInfo)
 *
 * 왜 이렇게 하는가:
 *   기존 워크플로우는 "이미지 준비 → 문서 생성 → 서지정보 추가"의 3단계였다.
 *   국립공문서관처럼 URL에서 이미지와 서지를 제공하는 경우,
 *   URL 하나로 한 번에 처리하는 것이 연구자에게 훨씬 편리하다.
 */


/* ──────────────────────────
   전역 상태
   ────────────────────────── */

/** 미리보기 결과 캐시 */
let _previewData = null;


/* ──────────────────────────
   초기화
   ────────────────────────── */

/**
 * 새 문헌 생성 모듈을 초기화한다.
 *
 * 목적: workspace.js의 DOMContentLoaded에서 호출되어 이벤트를 바인딩한다.
 */
// eslint-disable-next-line no-unused-vars
function initCreateDocument() {
  console.log("[create-document] initCreateDocument 호출됨");
  _bindCreateDocEvents();
}


/**
 * 이벤트를 바인딩한다.
 */
function _bindCreateDocEvents() {
  // "+ 새 문헌" 버튼
  const createBtn = document.getElementById("create-doc-btn");
  console.log("[create-document] create-doc-btn 요소:", createBtn);
  if (createBtn) {
    createBtn.addEventListener("click", _openCreateDocDialog);
    console.log("[create-document] click 이벤트 바인딩 완료");
  } else {
    console.error("[create-document] create-doc-btn을 찾을 수 없음!");
  }

  // 닫기 버튼
  const closeBtn = document.getElementById("create-doc-close");
  if (closeBtn) {
    closeBtn.addEventListener("click", _closeCreateDocDialog);
  }

  // 오버레이 클릭 닫기
  const overlay = document.getElementById("create-doc-overlay");
  if (overlay) {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) _closeCreateDocDialog();
    });
  }

  // 미리보기 버튼
  const previewBtn = document.getElementById("create-doc-preview-btn");
  if (previewBtn) {
    previewBtn.addEventListener("click", _previewFromUrl);
  }

  // URL 입력 Enter 키
  const urlInput = document.getElementById("create-doc-url");
  if (urlInput) {
    urlInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") _previewFromUrl();
    });
  }

  // 뒤로 버튼
  const backBtn = document.getElementById("create-doc-back-btn");
  if (backBtn) {
    backBtn.addEventListener("click", _backToStep1);
  }

  // 생성 버튼
  const createDocBtn = document.getElementById("create-doc-create-btn");
  if (createDocBtn) {
    createDocBtn.addEventListener("click", _createFromUrl);
  }
}


/* ──────────────────────────
   다이얼로그 열기/닫기
   ────────────────────────── */

function _openCreateDocDialog() {
  console.log("[create-document] _openCreateDocDialog 호출됨");
  const overlay = document.getElementById("create-doc-overlay");
  if (!overlay) {
    console.error("[create-document] create-doc-overlay 요소를 찾을 수 없음");
    return;
  }

  // 상태 초기화
  _previewData = null;
  _showStep1();

  // 입력값 초기화
  const urlInput = document.getElementById("create-doc-url");
  if (urlInput) urlInput.value = "";

  const statusEl = document.getElementById("create-doc-status");
  if (statusEl) statusEl.textContent = "";

  overlay.style.display = "flex";

  // URL 입력에 포커스
  if (urlInput) setTimeout(() => urlInput.focus(), 100);
}


function _closeCreateDocDialog() {
  const overlay = document.getElementById("create-doc-overlay");
  if (overlay) overlay.style.display = "none";
}


/* ──────────────────────────
   Step 1: URL 미리보기
   ────────────────────────── */

function _showStep1() {
  const step1 = document.getElementById("create-doc-step1");
  const step2 = document.getElementById("create-doc-step2");
  const progress = document.getElementById("create-doc-progress");

  if (step1) step1.style.display = "";
  if (step2) step2.style.display = "none";
  if (progress) progress.style.display = "none";
}


function _backToStep1() {
  _showStep1();
}


/**
 * URL에서 서지정보와 에셋 목록을 미리본다.
 *
 * 왜 미리보기를 먼저 하는가:
 *   - 연구자가 서지정보를 확인한 후 생성 여부를 결정할 수 있다.
 *   - 다운로드할 에셋을 선택할 수 있다 (전체 다운로드는 시간이 오래 걸린다).
 */
async function _previewFromUrl() {
  const urlInput = document.getElementById("create-doc-url");
  const statusEl = document.getElementById("create-doc-status");
  const previewBtn = document.getElementById("create-doc-preview-btn");
  if (!urlInput) return;

  const url = urlInput.value.trim();
  if (!url) {
    if (statusEl) statusEl.textContent = "URL을 입력하세요.";
    return;
  }

  // 로딩 표시
  if (statusEl) statusEl.textContent = "서지정보 조회 중...";
  if (previewBtn) previewBtn.disabled = true;

  try {
    const res = await fetch("/api/documents/preview-from-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });

    const data = await res.json();

    if (!res.ok) {
      let errorMsg = data.error || "미리보기 실패";
      if (data.supported_sources) {
        errorMsg += "\n지원: " + data.supported_sources
          .map((s) => s.description)
          .join(", ");
      }
      throw new Error(errorMsg);
    }

    // 미리보기 데이터 캐시
    _previewData = data;

    // Step 2 표시
    _showStep2(data);
  } catch (err) {
    if (statusEl) {
      statusEl.textContent = err.message;
      statusEl.style.color = "var(--error)";
    }
  } finally {
    if (previewBtn) previewBtn.disabled = false;
  }
}


/* ──────────────────────────
   Step 2: 미리보기 결과 + 생성
   ────────────────────────── */

/**
 * 미리보기 결과를 표시하고 Step 2로 전환한다.
 */
function _showStep2(data) {
  const step1 = document.getElementById("create-doc-step1");
  const step2 = document.getElementById("create-doc-step2");

  if (step1) step1.style.display = "none";
  if (step2) step2.style.display = "";

  // 서지 요약
  _renderBibSummary(data.bibliography);

  // 에셋 목록
  _renderAssets(data.assets || []);

  // doc_id 추천값
  const docIdInput = document.getElementById("create-doc-id");
  if (docIdInput) {
    docIdInput.value = data.suggested_doc_id || "";
  }

  // 제목
  const titleInput = document.getElementById("create-doc-title");
  if (titleInput) {
    titleInput.value = data.bibliography?.title || "";
  }

  // 상태 초기화
  const statusEl = document.getElementById("create-doc-create-status");
  if (statusEl) statusEl.textContent = "";
}


/**
 * 서지정보 요약을 렌더링한다.
 */
function _renderBibSummary(bib) {
  const container = document.getElementById("create-doc-bib-summary");
  if (!container || !bib) return;

  const fields = [
    { label: "제목", value: bib.title },
    { label: "저자", value: bib.creator?.name },
    { label: "성립/간행", value: bib.date_created },
    { label: "판종", value: bib.edition_type },
    { label: "형태사항", value: bib.physical_description },
    { label: "소장처", value: bib.repository?.name },
  ];

  let html = '<div class="create-doc-bib-table">';
  for (const f of fields) {
    if (!f.value) continue;
    html += `<div class="create-doc-bib-row">
      <span class="create-doc-bib-label">${_cdEscapeHtml(f.label)}</span>
      <span class="create-doc-bib-value">${_cdEscapeHtml(f.value)}</span>
    </div>`;
  }
  html += "</div>";

  container.innerHTML = html;
}


/**
 * 에셋(이미지) 목록을 체크박스로 렌더링한다.
 */
function _renderAssets(assets) {
  const section = document.getElementById("create-doc-assets-section");
  const container = document.getElementById("create-doc-assets");

  if (!section || !container) return;

  if (assets.length === 0) {
    section.style.display = "none";
    container.innerHTML = "";
    return;
  }

  section.style.display = "";

  let html = "";
  for (const asset of assets) {
    const id = asset.id || asset.asset_id || "";
    const label = asset.label || id;
    const pages = asset.page_count || "?";
    const sizeKb = asset.file_size ? Math.round(asset.file_size / 1024) : null;
    const sizeText = sizeKb ? ` (${sizeKb}KB)` : "";

    html += `<label class="create-doc-asset-item">
      <input type="checkbox" class="create-doc-asset-cb" value="${_cdEscapeHtml(id)}" checked />
      <span class="create-doc-asset-label">${_cdEscapeHtml(label)}</span>
      <span class="create-doc-asset-info">${pages}p${sizeText}</span>
    </label>`;
  }

  // 전체 선택/해제
  html = `<label class="create-doc-asset-item create-doc-asset-all">
    <input type="checkbox" id="create-doc-asset-all-cb" checked />
    <span class="create-doc-asset-label">전체 선택</span>
  </label>` + html;

  container.innerHTML = html;

  // 전체 선택 체크박스 이벤트
  const allCb = document.getElementById("create-doc-asset-all-cb");
  if (allCb) {
    allCb.addEventListener("change", () => {
      container.querySelectorAll(".create-doc-asset-cb").forEach((cb) => {
        cb.checked = allCb.checked;
      });
    });
  }
}


/**
 * URL에서 문헌을 생성한다.
 *
 * 왜 선택적 에셋 다운로드를 지원하는가:
 *   蒙求 같은 경우 3권 187페이지를 전부 받으면 시간이 오래 걸린다.
 *   연구자가 필요한 권만 선택할 수 있도록 체크박스를 제공한다.
 */
async function _createFromUrl() {
  if (!_previewData) return;

  const docIdInput = document.getElementById("create-doc-id");
  const titleInput = document.getElementById("create-doc-title");
  const statusEl = document.getElementById("create-doc-create-status");
  const createBtn = document.getElementById("create-doc-create-btn");

  const docId = docIdInput ? docIdInput.value.trim() : "";
  const title = titleInput ? titleInput.value.trim() : "";

  if (!docId) {
    if (statusEl) statusEl.textContent = "문헌 ID를 입력하세요.";
    return;
  }

  // doc_id 형식 검증 (영문 소문자로 시작, 소문자/숫자/밑줄)
  if (!/^[a-z][a-z0-9_]{0,63}$/.test(docId)) {
    if (statusEl) {
      statusEl.textContent = "문헌 ID: 영문 소문자로 시작, 소문자/숫자/밑줄만 가능 (최대 64자)";
    }
    return;
  }

  // 선택된 에셋 수집
  const checkboxes = document.querySelectorAll(".create-doc-asset-cb:checked");
  const selectedAssets = Array.from(checkboxes).map((cb) => cb.value).filter(Boolean);

  // 에셋이 있는데 하나도 선택 안 한 경우
  const allAssets = _previewData.assets || [];
  if (allAssets.length > 0 && selectedAssets.length === 0) {
    if (statusEl) statusEl.textContent = "최소 하나의 에셋을 선택하세요.";
    return;
  }

  // URL 가져오기
  const urlInput = document.getElementById("create-doc-url");
  const url = urlInput ? urlInput.value.trim() : _previewData.bibliography?.digital_source?.source_url;

  // 진행 상태 표시
  _showProgress("문헌 생성 중... (이미지 다운로드에 시간이 걸릴 수 있습니다)");
  if (createBtn) createBtn.disabled = true;

  try {
    const body = {
      url: url,
      doc_id: docId,
      title: title || null,
      selected_assets: allAssets.length > 0 ? selectedAssets : null,
    };

    const res = await fetch("/api/documents/create-from-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "문헌 생성 실패");
    }

    // 성공 — 경고가 있어도 생성은 완료된 상태
    let msg = `문헌 '${data.document_id}' 생성 완료! (${data.asset_count || 0}개 파일)`;
    if (data.warning) {
      msg += `\n⚠ ${data.warning}`;
    }
    _showProgress(msg);

    // 사이드바 갱신 + 완료 알림
    await _refreshSidebar();

    // 3초 후 다이얼로그 닫기 (연구자가 완료 메시지를 읽을 시간)
    setTimeout(() => {
      _closeCreateDocDialog();
    }, 3000);
  } catch (err) {
    _hideProgress();
    if (statusEl) {
      statusEl.textContent = err.message;
      statusEl.style.color = "var(--error)";
    }
    // 에러 시에도 사이드바 갱신 시도
    // 왜: 502가 와도 문헌 폴더가 이미 생성되었을 수 있다.
    //      갱신하면 목록에 바로 나타나므로 서버를 재시작할 필요가 없다.
    await _refreshSidebar();
  } finally {
    if (createBtn) createBtn.disabled = false;
  }
}


/* ──────────────────────────
   사이드바 갱신
   ────────────────────────── */

/**
 * 사이드바 문헌 목록을 갱신한다.
 *
 * 왜 별도 함수인가:
 *   성공/실패 양쪽에서 호출해야 하므로 중복 방지.
 *   502 에러가 와도 문헌 폴더가 이미 생성되었을 수 있으므로
 *   에러 시에도 갱신하면 서버 재시작 없이 목록에 나타난다.
 */
async function _refreshSidebar() {
  try {
    const docsRes = await fetch("/api/documents");
    if (docsRes.ok) {
      const docs = await docsRes.json();
      const statusEl = document.getElementById("status-documents");
      if (statusEl) statusEl.textContent = `문헌: ${docs.length}`;
      if (typeof initSidebarTree === "function") {
        initSidebarTree(docs);
      }
    }
  } catch {
    // 갱신 실패는 치명적이지 않다
  }
}


/* ──────────────────────────
   진행 상태 표시
   ────────────────────────── */

function _showProgress(text) {
  const step2 = document.getElementById("create-doc-step2");
  const progress = document.getElementById("create-doc-progress");
  const progressText = document.getElementById("create-doc-progress-text");

  if (step2) step2.style.display = "none";
  if (progress) progress.style.display = "";
  if (progressText) progressText.textContent = text;
}


function _hideProgress() {
  const step2 = document.getElementById("create-doc-step2");
  const progress = document.getElementById("create-doc-progress");

  if (step2) step2.style.display = "";
  if (progress) progress.style.display = "none";
}


/* ──────────────────────────
   유틸리티
   ────────────────────────── */

/**
 * HTML 이스케이프 (create-document 모듈 전용).
 *
 * 왜 별도 함수인가:
 *   bibliography.js의 _escapeHtml과 동일하지만,
 *   vanilla JS에서 모듈 스코프가 없으므로 이름 충돌 방지.
 */
function _cdEscapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str || "";
  return div.innerHTML;
}
