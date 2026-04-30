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

/** 미리보기 결과 캐시 (URL 모드) */
let _previewData = null;

/**
 * 현재 활성 모드 — "url" | "local".
 *
 * 왜 모드 추적이 필요한가:
 *   Step2의 "문헌 생성" 버튼은 두 모드에서 호출 대상이 다르다
 *   (URL은 /api/documents/create-from-url, 로컬은 /api/documents/create-from-files).
 *   생성 직전에 어느 흐름이었는지 알아야 한다.
 */
let _activeMode = "url";

/** 로컬 모드에서 사용자가 선택한 File 객체 목록 */
let _localFiles = [];


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

  // 모드 탭
  const tabUrl = document.getElementById("create-doc-tab-url");
  const tabLocal = document.getElementById("create-doc-tab-local");
  if (tabUrl) {
    tabUrl.addEventListener("click", () => _switchCreateDocMode("url"));
  }
  if (tabLocal) {
    tabLocal.addEventListener("click", () => _switchCreateDocMode("local"));
  }

  // 미리보기 버튼 (URL 모드)
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

  // 로컬 파일 입력 변경 (누적)
  const localFileInput = document.getElementById("create-doc-local-files");
  if (localFileInput) {
    localFileInput.addEventListener("change", _onLocalFilesChanged);
  }

  // "파일 추가" 버튼 — 숨겨진 input을 열어 다중 선택을 받는다
  const localAddBtn = document.getElementById("create-doc-local-add-btn");
  if (localAddBtn) {
    localAddBtn.addEventListener("click", () => {
      if (localFileInput) localFileInput.click();
    });
  }

  // "전체 비우기" 버튼
  const localClearBtn = document.getElementById("create-doc-local-clear-btn");
  if (localClearBtn) {
    localClearBtn.addEventListener("click", _clearLocalFiles);
  }

  // 로컬 모드 "다음" 버튼
  const localNextBtn = document.getElementById("create-doc-local-next-btn");
  if (localNextBtn) {
    localNextBtn.addEventListener("click", _proceedFromLocal);
  }

  // 뒤로 버튼
  const backBtn = document.getElementById("create-doc-back-btn");
  if (backBtn) {
    backBtn.addEventListener("click", _backToStep1);
  }

  // 생성 버튼 — 모드에 따라 분기
  const createDocBtn = document.getElementById("create-doc-create-btn");
  if (createDocBtn) {
    createDocBtn.addEventListener("click", () => {
      if (_activeMode === "local") {
        _createFromFiles();
      } else {
        _createFromUrl();
      }
    });
  }
}


/* ──────────────────────────
   모드 전환
   ────────────────────────── */

/**
 * URL 모드와 로컬 파일 모드 사이를 전환한다.
 *
 * 왜 두 모드를 한 다이얼로그에 두는가:
 *   사용자에게 "어디에서 가져오는가"는 단일 시작점에서 선택하는 것이
 *   가장 직관적이다. 별도 버튼/메뉴를 만들면 사이드바가 복잡해진다.
 */
function _switchCreateDocMode(mode) {
  _activeMode = mode === "local" ? "local" : "url";

  const tabUrl = document.getElementById("create-doc-tab-url");
  const tabLocal = document.getElementById("create-doc-tab-local");
  const paneUrl = document.getElementById("create-doc-pane-url");
  const paneLocal = document.getElementById("create-doc-pane-local");

  const isUrl = _activeMode === "url";
  if (tabUrl) {
    tabUrl.classList.toggle("create-doc-tab-active", isUrl);
    tabUrl.setAttribute("aria-selected", isUrl ? "true" : "false");
  }
  if (tabLocal) {
    tabLocal.classList.toggle("create-doc-tab-active", !isUrl);
    tabLocal.setAttribute("aria-selected", !isUrl ? "true" : "false");
  }
  if (paneUrl) paneUrl.style.display = isUrl ? "" : "none";
  if (paneLocal) paneLocal.style.display = isUrl ? "none" : "";

  // 모드 전환 시 양쪽 상태 메시지를 비운다.
  const urlStatusEl = document.getElementById("create-doc-status");
  if (urlStatusEl) urlStatusEl.textContent = "";
  const localStatusEl = document.getElementById("create-doc-local-status");
  if (localStatusEl) localStatusEl.textContent = "";
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
  _localFiles = [];
  _switchCreateDocMode("url"); // 기본 탭은 URL
  _showStep1();

  // URL 모드 입력값 초기화
  const urlInput = document.getElementById("create-doc-url");
  if (urlInput) urlInput.value = "";

  const statusEl = document.getElementById("create-doc-status");
  if (statusEl) statusEl.textContent = "";

  // 로컬 모드 입력값 초기화
  const localFileInput = document.getElementById("create-doc-local-files");
  if (localFileInput) localFileInput.value = "";
  const localStatusEl = document.getElementById("create-doc-local-status");
  if (localStatusEl) localStatusEl.textContent = "";
  _renderLocalFilesEditor();

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
 * 미리보기 결과를 표시하고 Step 2로 전환한다 (URL 모드).
 */
function _showStep2(data) {
  const step1 = document.getElementById("create-doc-step1");
  const step2 = document.getElementById("create-doc-step2");

  if (step1) step1.style.display = "none";
  if (step2) step2.style.display = "";

  // URL 모드 전용 섹션 표시 / 로컬 섹션 숨김
  _toggleStep2Sections("url");

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
 * Step2 섹션을 모드에 맞춰 보이거나 숨긴다.
 *
 * URL 모드: 서지 요약 + 에셋 체크박스
 * 로컬 모드: 선택된 파일 목록만
 */
function _toggleStep2Sections(mode) {
  const isLocal = mode === "local";

  const bibSummary = document.getElementById("create-doc-bib-summary");
  const assetsSection = document.getElementById("create-doc-assets-section");
  const localFilesSection = document.getElementById(
    "create-doc-local-files-section"
  );

  if (bibSummary) bibSummary.style.display = isLocal ? "none" : "";
  if (assetsSection) {
    // URL 모드일 때만 표시 — 단, 에셋이 비어 있으면 _renderAssets가 다시 숨긴다.
    assetsSection.style.display = isLocal ? "none" : "";
  }
  if (localFilesSection) {
    localFilesSection.style.display = isLocal ? "" : "none";
  }
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


/* ──────────────────────────
   로컬 파일 모드
   ────────────────────────── */

/** 허용 확장자 — 백엔드 add_document와 일치해야 한다. */
const _LOCAL_ALLOWED_EXT = ["pdf", "jpg", "jpeg", "png", "tif", "tiff"];


/**
 * 파일 input에서 새 파일이 들어오면 _localFiles에 누적한다.
 *
 * 왜 누적인가:
 *   여러 폴더에 흩어진 페이지 이미지를 사용자가 여러 번 나눠서 추가할 수 있어야 한다.
 *   매번 덮어쓰면 한 번에 모두 선택해야 하는 부담이 생긴다.
 *
 * 검증/중복 처리:
 *   - 허용 확장자가 아닌 파일은 거른 뒤 상태바에 알린다.
 *   - 같은 이름이 이미 있으면 건너뛴다 (백엔드에서 PDF 이름 충돌이 거절되므로
 *     사전 거절이 친절하다). 이미지는 PDF로 묶이므로 이름 충돌이 무해하지만,
 *     사용자 의도는 "한 번 더 누른 실수"일 가능성이 높다.
 */
function _onLocalFilesChanged(e) {
  const statusEl = document.getElementById("create-doc-local-status");
  if (statusEl) {
    statusEl.textContent = "";
    statusEl.style.color = "";
  }

  const fileList = e?.target?.files || [];
  if (fileList.length === 0) {
    _refreshLocalFilesUI();
    return;
  }

  const incoming = Array.from(fileList);
  const invalid = [];
  const duplicates = [];
  const accepted = [];
  const existingKeys = new Set(_localFiles.map((f) => f.name));

  for (const f of incoming) {
    const ext = (f.name.split(".").pop() || "").toLowerCase();
    if (!_LOCAL_ALLOWED_EXT.includes(ext)) {
      invalid.push(f.name);
      continue;
    }
    if (existingKeys.has(f.name)) {
      duplicates.push(f.name);
      continue;
    }
    accepted.push(f);
    existingKeys.add(f.name);
  }

  _localFiles = _localFiles.concat(accepted);

  if (statusEl) {
    const msgs = [];
    if (invalid.length > 0) msgs.push(`지원 안 함: ${invalid.join(", ")}`);
    if (duplicates.length > 0) msgs.push(`중복 무시: ${duplicates.join(", ")}`);
    if (msgs.length > 0) {
      statusEl.textContent = msgs.join(" · ");
      statusEl.style.color = "var(--error)";
    }
  }

  // input은 비워서 같은 파일을 다시 선택할 수 있게 한다.
  if (e?.target) e.target.value = "";

  _refreshLocalFilesUI();
}


/**
 * 전체 비우기.
 */
function _clearLocalFiles() {
  _localFiles = [];
  const statusEl = document.getElementById("create-doc-local-status");
  if (statusEl) {
    statusEl.textContent = "";
    statusEl.style.color = "";
  }
  _refreshLocalFilesUI();
}


/**
 * 한 항목을 위/아래로 이동한다.
 *
 * delta: -1(위), +1(아래). 첫/마지막 위치에서는 호출 안 됨(버튼 disabled).
 */
function _moveLocalFile(index, delta) {
  const target = index + delta;
  if (target < 0 || target >= _localFiles.length) return;
  const tmp = _localFiles[index];
  _localFiles[index] = _localFiles[target];
  _localFiles[target] = tmp;
  _refreshLocalFilesUI();
}


/**
 * 한 항목을 목록에서 제거한다.
 */
function _removeLocalFile(index) {
  if (index < 0 || index >= _localFiles.length) return;
  _localFiles.splice(index, 1);
  _refreshLocalFilesUI();
}


/**
 * 요약 텍스트와 편집 가능한 파일 목록을 다시 그린다.
 */
function _refreshLocalFilesUI() {
  // 요약
  const summaryEl = document.getElementById("create-doc-local-summary");
  if (summaryEl) {
    if (_localFiles.length === 0) {
      summaryEl.textContent = "파일을 선택하지 않았습니다.";
    } else {
      const totalBytes = _localFiles.reduce((s, f) => s + (f.size || 0), 0);
      const totalKb = Math.round(totalBytes / 1024);
      const totalText =
        totalKb >= 1024
          ? (totalKb / 1024).toFixed(1) + " MB"
          : totalKb + " KB";
      summaryEl.textContent = `${_localFiles.length}개 파일 / ${totalText}`;
    }
  }

  _renderLocalFilesEditor();
}


/**
 * Step1의 편집 가능한 파일 목록을 렌더링한다.
 *
 * 각 행에 인덱스, 파일명, 종류(이미지/PDF), 크기, ↑/↓/× 버튼.
 */
function _renderLocalFilesEditor() {
  const container = document.getElementById("create-doc-local-editor");
  if (!container) return;

  if (_localFiles.length === 0) {
    container.innerHTML = "";
    return;
  }

  const last = _localFiles.length - 1;
  let html = "";
  for (let i = 0; i < _localFiles.length; i++) {
    const f = _localFiles[i];
    const ext = (f.name.split(".").pop() || "").toLowerCase();
    const kind = ext === "pdf" ? "PDF" : "이미지";
    const sizeKb = Math.round((f.size || 0) / 1024);
    const sizeText =
      sizeKb >= 1024 ? (sizeKb / 1024).toFixed(1) + " MB" : sizeKb + " KB";

    html += `<div class="create-doc-local-row" data-idx="${i}">
      <span class="create-doc-local-index">${i + 1}</span>
      <span class="create-doc-local-name" title="${_cdEscapeHtml(f.name)}">${_cdEscapeHtml(f.name)}</span>
      <span class="create-doc-local-kind">${kind}</span>
      <span class="create-doc-local-size">${sizeText}</span>
      <span class="create-doc-local-row-btns">
        <button type="button" class="create-doc-local-row-btn" data-action="up"
          title="위로" ${i === 0 ? "disabled" : ""}>▲</button>
        <button type="button" class="create-doc-local-row-btn" data-action="down"
          title="아래로" ${i === last ? "disabled" : ""}>▼</button>
        <button type="button" class="create-doc-local-row-btn create-doc-local-row-remove"
          data-action="remove" title="제거">×</button>
      </span>
    </div>`;
  }
  container.innerHTML = html;

  // 위임 핸들러: 버튼 클릭을 컨테이너에서 잡아 인덱스를 찾는다.
  // 왜 위임인가: 매 렌더마다 buttons에 개별 listener를 붙이는 것보다 가볍다.
  container.onclick = (e) => {
    const btn = e.target.closest(".create-doc-local-row-btn");
    if (!btn) return;
    const row = btn.closest(".create-doc-local-row");
    const idx = parseInt(row?.dataset?.idx ?? "-1", 10);
    if (Number.isNaN(idx) || idx < 0) return;
    const action = btn.dataset.action;
    if (action === "up") _moveLocalFile(idx, -1);
    else if (action === "down") _moveLocalFile(idx, +1);
    else if (action === "remove") _removeLocalFile(idx);
  };
}


/**
 * 로컬 파일 모드에서 Step2로 넘어간다.
 *
 * 왜 미리보기 단계가 없는가:
 *   사용자 PC에 이미 있는 파일이므로 서지정보를 가져올 외부 소스가 없다.
 *   대신 파일 목록을 그대로 Step2에서 보여주고, doc_id/제목을 입력받는다.
 */
function _proceedFromLocal() {
  const statusEl = document.getElementById("create-doc-local-status");
  if (statusEl) {
    statusEl.textContent = "";
    statusEl.style.color = "";
  }

  if (_localFiles.length === 0) {
    if (statusEl) {
      statusEl.textContent = "최소 한 개 파일을 추가하세요.";
      statusEl.style.color = "var(--error)";
    }
    return;
  }

  // 확장자/중복은 _onLocalFilesChanged에서 이미 거른 상태다.
  // Step2로 전환
  const step1 = document.getElementById("create-doc-step1");
  const step2 = document.getElementById("create-doc-step2");
  if (step1) step1.style.display = "none";
  if (step2) step2.style.display = "";

  _toggleStep2Sections("local");
  _renderLocalFilesList(_localFiles);

  // doc_id 후보: 첫 파일 이름의 stem을 소독하여 추천
  const docIdInput = document.getElementById("create-doc-id");
  if (docIdInput && !docIdInput.value) {
    docIdInput.value = _suggestDocIdFromFile(_localFiles[0]?.name || "");
  }
  // 제목은 비워두고 사용자가 채우게 함 (로컬 파일은 자동 추출 불가)
  const titleInput = document.getElementById("create-doc-title");
  if (titleInput) titleInput.value = titleInput.value || "";

  // 상태 초기화
  const createStatusEl = document.getElementById("create-doc-create-status");
  if (createStatusEl) createStatusEl.textContent = "";
}


/**
 * 선택된 파일 목록을 Step2에 렌더링한다.
 */
function _renderLocalFilesList(files) {
  const container = document.getElementById("create-doc-local-files-list");
  if (!container) return;

  let html = "";
  for (let i = 0; i < files.length; i++) {
    const f = files[i];
    const ext = (f.name.split(".").pop() || "").toLowerCase();
    const kind = ext === "pdf" ? "PDF" : "이미지";
    const sizeKb = Math.round((f.size || 0) / 1024);
    const sizeText =
      sizeKb >= 1024 ? (sizeKb / 1024).toFixed(1) + " MB" : sizeKb + " KB";
    html += `<div class="create-doc-asset-item">
      <span class="create-doc-local-index">${i + 1}</span>
      <span class="create-doc-asset-label">${_cdEscapeHtml(f.name)}</span>
      <span class="create-doc-local-kind">${kind}</span>
      <span class="create-doc-asset-info">${sizeText}</span>
    </div>`;
  }
  container.innerHTML = html;
}


/**
 * 파일 이름에서 doc_id 후보를 만든다.
 *
 * 규칙: 영문 소문자로 시작, 소문자+숫자+밑줄, 최대 64자.
 * 한글/한자 등 비-ASCII 문자는 모두 제거되므로 이름이 한자뿐이면 빈 문자열이 된다.
 * 그 경우 사용자가 직접 입력하도록 빈 값을 반환한다.
 */
function _suggestDocIdFromFile(filename) {
  const stem = (filename || "").replace(/\.[^.]+$/, "");
  // 소문자화 + 영숫자/밑줄 외 모두 밑줄로 변환
  let candidate = stem.toLowerCase().replace(/[^a-z0-9_]+/g, "_");
  // 앞 비-알파벳 제거
  candidate = candidate.replace(/^[^a-z]+/, "");
  // 연속 밑줄 정리, 양 끝 밑줄 제거
  candidate = candidate.replace(/_+/g, "_").replace(/^_+|_+$/g, "");
  if (candidate.length > 64) candidate = candidate.slice(0, 64);
  return candidate;
}


/**
 * 로컬 파일 모드에서 문헌을 생성한다.
 */
async function _createFromFiles() {
  const docIdInput = document.getElementById("create-doc-id");
  const titleInput = document.getElementById("create-doc-title");
  const statusEl = document.getElementById("create-doc-create-status");
  const createBtn = document.getElementById("create-doc-create-btn");

  const docId = docIdInput ? docIdInput.value.trim() : "";
  const title = titleInput ? titleInput.value.trim() : "";

  if (!docId) {
    if (statusEl) {
      statusEl.textContent = "문헌 ID를 입력하세요.";
      statusEl.style.color = "var(--error)";
    }
    return;
  }
  if (!/^[a-z][a-z0-9_]{0,63}$/.test(docId)) {
    if (statusEl) {
      statusEl.textContent =
        "문헌 ID: 영문 소문자로 시작, 소문자/숫자/밑줄만 가능 (최대 64자)";
      statusEl.style.color = "var(--error)";
    }
    return;
  }

  if (_localFiles.length === 0) {
    if (statusEl) {
      statusEl.textContent = "선택된 파일이 없습니다. 뒤로 가서 파일을 선택하세요.";
      statusEl.style.color = "var(--error)";
    }
    return;
  }

  // FormData로 multipart 업로드
  const formData = new FormData();
  formData.append("doc_id", docId);
  if (title) formData.append("title", title);
  for (const f of _localFiles) {
    formData.append("files", f, f.name);
  }

  // 왜 fetch 대신 XMLHttpRequest를 쓰는가:
  //   fetch API는 업로드 진행률(upload.onprogress)을 노출하지 않는다.
  //   큰 이미지 묶음 업로드 시 진행 상황을 사용자에게 보여 주기 위해 XHR을 사용한다.
  // 첫 표시는 indeterminate(펄스) — 매우 빠른 업로드여도 막대가 보인다.
  _showProgress("업로드 준비 중...", null);
  if (createBtn) createBtn.disabled = true;

  try {
    const result = await _xhrPostFormData(
      "/api/documents/create-from-files",
      formData,
      // onUploadProgress: 0~50% 구간에 매핑 (서버 처리가 50~100%)
      (loaded, total) => {
        if (total > 0) {
          const pct = Math.min(50, Math.round((loaded / total) * 50));
          const mb = (loaded / 1024 / 1024).toFixed(1);
          const totalMb = (total / 1024 / 1024).toFixed(1);
          _showProgress(
            `업로드 중... ${mb} / ${totalMb} MB`,
            pct,
          );
        } else {
          _showProgress("업로드 중...", null);
        }
      },
      // onUploadDone: 업로드 끝, 서버 처리 시작
      () => {
        _showProgress(
          "서버에서 PDF로 묶고 저장 중... (페이지가 많으면 1-2분 걸립니다)",
          null, // null = indeterminate (펄스 애니메이션)
        );
      },
    );

    if (!result.ok) {
      const msg = result.data?.error || `문헌 생성 실패 (status ${result.status})`;
      throw new Error(msg);
    }

    const data = result.data;
    _showProgress(
      `문헌 '${data.document_id}' 생성 완료! (${data.asset_count || 0}개 파일)`,
      100,
    );

    await _refreshSidebar();

    setTimeout(() => {
      _closeCreateDocDialog();
    }, 2500);
  } catch (err) {
    _hideProgress();
    if (statusEl) {
      statusEl.textContent = err.message;
      statusEl.style.color = "var(--error)";
    }
    // 사이드바 갱신 시도 — 부분 성공일 수 있다.
    await _refreshSidebar();
  } finally {
    if (createBtn) createBtn.disabled = false;
  }
}


/**
 * XMLHttpRequest로 multipart POST를 보내고 진행률 콜백을 받는다.
 *
 * 반환: Promise<{ok, status, data}>
 *   ok: 2xx 여부
 *   status: HTTP 상태 코드
 *   data: 응답 본문(JSON 파싱). 파싱 실패 시 null.
 */
function _xhrPostFormData(url, formData, onProgress, onUploadDone) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url, true);
    // 큰 PDF/이미지 다수 업로드를 고려해 10분 timeout (서버 처리 포함)
    xhr.timeout = 10 * 60 * 1000;

    if (xhr.upload && onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded, e.total);
      };
      xhr.upload.onload = () => {
        if (typeof onUploadDone === "function") onUploadDone();
      };
    }

    xhr.onload = () => {
      let data = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        // 파싱 실패는 ok=false로 전달
      }
      resolve({
        ok: xhr.status >= 200 && xhr.status < 300,
        status: xhr.status,
        data,
      });
    };
    xhr.onerror = () => reject(new Error("네트워크 오류 — 서버에 연결할 수 없습니다."));
    xhr.ontimeout = () => reject(new Error("요청 시간이 초과되었습니다."));

    xhr.send(formData);
  });
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

/**
 * 진행 상태를 표시한다.
 *
 * @param {string} text — 사용자에게 보여줄 진행 메시지
 * @param {number|null} pct — 0~100 정수면 막대를 그 만큼 채움.
 *                            null이면 indeterminate(펄스) 모드 — 서버 처리 등
 *                            진행률을 알 수 없는 단계에 사용.
 */
function _showProgress(text, pct) {
  const step2 = document.getElementById("create-doc-step2");
  const progress = document.getElementById("create-doc-progress");
  const progressText = document.getElementById("create-doc-progress-text");
  const progressFill = document.getElementById("create-doc-progress-fill");

  if (step2) step2.style.display = "none";
  if (progress) progress.style.display = "";
  if (progressText) progressText.textContent = text;

  if (progressFill) {
    if (pct === null || pct === undefined) {
      // indeterminate — 막대를 100%로 채우고 펄스 애니메이션을 켠다
      progressFill.style.width = "100%";
      progressFill.classList.add("create-doc-progress-pulse");
    } else {
      progressFill.classList.remove("create-doc-progress-pulse");
      const clamped = Math.max(0, Math.min(100, Math.round(pct)));
      progressFill.style.width = `${clamped}%`;
    }
  }
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
