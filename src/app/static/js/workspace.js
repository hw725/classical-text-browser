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
  // 편성 에디터 초기화 (LayoutBlock → TextBlock)
  if (typeof initCompositionEditor === "function") initCompositionEditor();
  // Phase 11-1: 표점 편집기 초기화
  if (typeof initPunctuationEditor === "function") initPunctuationEditor();
  // Phase 11-1: 현토 편집기 초기화
  if (typeof initHyeontoEditor === "function") initHyeontoEditor();
  // Phase 11-2: 번역 편집기 초기화
  if (typeof initTranslationEditor === "function") initTranslationEditor();
  // Phase 11-3: 주석 편집기 초기화
  if (typeof initAnnotationEditor === "function") initAnnotationEditor();
  // Phase 12-1: Git 그래프 초기화
  if (typeof initGitGraph === "function") initGitGraph();
  // Phase 12-3: JSON 스냅샷 Export/Import 버튼
  initSnapshotButtons();
  // 읽기 보조선 초기화
  if (typeof initReaderLine === "function") initReaderLine();
  // 비고/메모 패널 초기화
  if (typeof initNotesPanel === "function") initNotesPanel();
  // Phase 7+8: 하단 패널 탭 전환 (Git 이력 ↔ 의존 추적 ↔ 엔티티 ↔ 비고)
  initBottomPanelTabs();

  // 전 모드 LLM 모델 드롭다운 채우기 (모든 init 완료 후 한 번만)
  _loadAllLlmModelSelects();
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

  // 패널별 표시/숨김 매핑
  // explorer: 문헌목록 + 서지정보 + 해석저장소 (기존)
  // settings: 설정 패널만
  const panelSections = {
    explorer: ["document-list", "bib-section", "interp-section"],
    settings: ["settings-section"],
  };

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      const panel = btn.getAttribute("data-panel");

      // 모든 sidebar-section 숨김
      document.querySelectorAll("#sidebar-content .sidebar-section").forEach((s) => {
        s.style.display = "none";
      });

      if (panel === "settings") {
        // 설정 패널 표시
        const settingsEl = document.getElementById("settings-section");
        if (settingsEl) {
          settingsEl.style.display = "";
          _loadSettings();
        }
        // 사이드바 타이틀 변경
        const title = document.querySelector(".sidebar-title");
        if (title) title.textContent = "설정";
      } else {
        // explorer: 기존 섹션 복원
        const docList = document.querySelector("#sidebar-content > .sidebar-section:first-child");
        if (docList) docList.style.display = "";
        // 문헌 선택 상태에 따라 서지/해석 섹션 복원
        const bibSec = document.getElementById("bib-section");
        const interpSec = document.getElementById("interp-section");
        if (bibSec && typeof viewerState !== "undefined" && viewerState.docId) {
          bibSec.style.display = "";
        }
        if (interpSec && typeof viewerState !== "undefined" && viewerState.docId) {
          interpSec.style.display = "";
        }
        // 사이드바 타이틀 복원
        const title = document.querySelector(".sidebar-title");
        if (title) title.textContent = "서고 브라우저";
      }
    });
  });
}


/* ──────────────────────────
   3-1. 설정 패널 로드
   ────────────────────────── */

async function _loadSettings() {
  try {
    const res = await fetch("/api/settings");
    if (!res.ok) return;
    const data = await res.json();

    // 서고 경로 표시
    const pathEl = document.getElementById("settings-library-path");
    if (pathEl) {
      pathEl.textContent = data.library_path || "(설정 안 됨)";
    }

    // 원본 저장소 목록
    _renderRepoList("settings-doc-repos", data.documents || [], "documents");

    // 해석 저장소 목록
    _renderRepoList("settings-interp-repos", data.interpretations || [], "interpretations");
  } catch (e) {
    console.warn("설정 로드 실패:", e);
  }
}


function _renderRepoList(containerId, repos, repoType) {
  const container = document.getElementById(containerId);
  if (!container) return;

  if (repos.length === 0) {
    container.innerHTML = '<div class="placeholder">저장소 없음</div>';
    return;
  }

  container.innerHTML = "";
  for (const repo of repos) {
    const item = document.createElement("div");
    item.className = "settings-repo-item";

    const hasRemote = !!repo.remote_url;
    const statusIcon = hasRemote ? "●" : "○";
    const statusClass = hasRemote ? "remote-connected" : "remote-disconnected";

    item.innerHTML = `
      <div class="settings-repo-header">
        <span class="${statusClass}">${statusIcon}</span>
        <strong>${repo.id}</strong>
      </div>
      <div class="settings-repo-remote">
        <input type="text" class="settings-remote-input"
               placeholder="원격 URL (예: https://github.com/...)"
               value="${repo.remote_url || ""}"
               data-repo-type="${repoType}" data-repo-id="${repo.id}">
        <button class="text-btn settings-remote-save" title="원격 URL 저장">저장</button>
      </div>
      <div class="settings-repo-actions">
        <button class="text-btn settings-push-btn"
                data-repo-type="${repoType}" data-repo-id="${repo.id}"
                ${hasRemote ? "" : "disabled"}>Push</button>
        <button class="text-btn settings-pull-btn"
                data-repo-type="${repoType}" data-repo-id="${repo.id}"
                ${hasRemote ? "" : "disabled"}>Pull</button>
      </div>
    `;

    // 원격 URL 저장 버튼
    item.querySelector(".settings-remote-save").addEventListener("click", async () => {
      const input = item.querySelector(".settings-remote-input");
      const url = input.value.trim();
      if (!url) { alert("원격 URL을 입력하세요."); return; }

      try {
        const res = await fetch("/api/settings/remote", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            repo_type: repoType,
            repo_id: repo.id,
            remote_url: url,
          }),
        });
        const result = await res.json();
        if (!res.ok) throw new Error(result.error);
        alert(`원격 URL 설정 완료: ${url}`);
        _loadSettings();  // 새로고침
      } catch (e) {
        alert(`원격 설정 실패: ${e.message}`);
      }
    });

    // Push/Pull 버튼
    const pushBtn = item.querySelector(".settings-push-btn");
    const pullBtn = item.querySelector(".settings-pull-btn");

    if (pushBtn) {
      pushBtn.addEventListener("click", () => _gitSync(repoType, repo.id, "push"));
    }
    if (pullBtn) {
      pullBtn.addEventListener("click", () => _gitSync(repoType, repo.id, "pull"));
    }

    container.appendChild(item);
  }
}


async function _gitSync(repoType, repoId, action) {
  const label = action === "push" ? "Push" : "Pull";
  if (!confirm(`${repoId} 저장소를 ${label} 하시겠습니까?`)) return;

  try {
    const res = await fetch("/api/settings/git-sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        repo_type: repoType,
        repo_id: repoId,
        action: action,
      }),
    });
    const result = await res.json();
    if (!res.ok) throw new Error(result.error);
    alert(`${label} 완료: ${result.output || "성공"}`);
  } catch (e) {
    alert(`${label} 실패: ${e.message}`);
  }
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
  const compositionPanel = document.getElementById("composition-panel");
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
  if (currentMode === "composition") {
    if (typeof deactivateCompositionMode === "function") deactivateCompositionMode();
    if (compositionPanel) compositionPanel.style.display = "none";
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
  if (compositionPanel) compositionPanel.style.display = "none";
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
  } else if (mode === "composition") {
    // 우측: 편성 에디터 패널 표시
    if (compositionPanel) compositionPanel.style.display = "";
    if (typeof activateCompositionMode === "function") activateCompositionMode();
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

    // Phase 3: 트리 뷰 사용 (sidebar-tree.js)
    if (typeof initSidebarTree === "function") {
      initSidebarTree(docs);
    } else {
      renderDocumentList(docs);
    }

    // URL 해시에서 열람 위치 복원 (Plan 4)
    _restoreFromHash();
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
 * JSON 스냅샷 Export/Import 버튼을 설정한다.
 *
 * 왜 이렇게 하는가:
 *   Phase 12-3에서 현재 해석 작업(Work)을 단일 JSON 파일로
 *   내보내거나, 다른 환경에서 가져온 JSON을 불러올 수 있다.
 *   - Export: 현재 해석 저장소를 JSON 파일로 다운로드
 *   - Import: JSON 파일을 선택하여 새 Work로 생성
 */
function initSnapshotButtons() {
  // ─── Export 버튼 ───
  const exportBtn = document.getElementById("snapshot-export-btn");
  if (exportBtn) {
    exportBtn.addEventListener("click", async () => {
      // 현재 선택된 해석 저장소 ID 확인
      if (typeof interpState === "undefined" || !interpState.interpId) {
        alert("내보낼 해석 저장소를 먼저 선택해주세요.");
        return;
      }

      const interpId = interpState.interpId;
      exportBtn.disabled = true;
      exportBtn.textContent = "내보내는 중…";

      try {
        const res = await fetch(`/api/interpretations/${interpId}/export/json`);
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.error || `서버 오류: ${res.status}`);
        }

        // 서버가 보낸 파일명 추출 (Content-Disposition 헤더)
        const disposition = res.headers.get("Content-Disposition") || "";
        let filename = `${interpId}.json`;
        const match = disposition.match(/filename="?([^"]+)"?/);
        if (match) filename = match[1];

        // Blob → 다운로드 트리거
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (e) {
        alert(`내보내기 실패: ${e.message}`);
      } finally {
        exportBtn.disabled = false;
        exportBtn.textContent = "내보내기";
      }
    });
  }

  // ─── Import 버튼 ───
  const importBtn = document.getElementById("snapshot-import-btn");
  if (importBtn) {
    importBtn.addEventListener("click", () => {
      // 숨겨진 file input 생성 → JSON 파일 선택
      const input = document.createElement("input");
      input.type = "file";
      input.accept = ".json,application/json";
      input.style.display = "none";

      input.addEventListener("change", async () => {
        const file = input.files[0];
        if (!file) return;

        importBtn.disabled = true;
        importBtn.textContent = "가져오는 중…";

        try {
          // 파일 내용 읽기
          const text = await file.text();
          let data;
          try {
            data = JSON.parse(text);
          } catch {
            throw new Error("올바른 JSON 파일이 아닙니다.");
          }

          // 서버에 전송
          const res = await fetch("/api/import/json", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
          });

          const result = await res.json();

          if (!res.ok) {
            // 검증 오류 표시
            const errMsg = result.errors
              ? result.errors.join("\n")
              : result.error || "알 수 없는 오류";
            throw new Error(errMsg);
          }

          // 성공: 결과 안내
          let msg = `가져오기 완료!\n\n` +
            `문헌: ${result.title}\n` +
            `문헌 ID: ${result.doc_id}\n` +
            `해석 ID: ${result.interp_id}\n` +
            `레이어: ${(result.layers_imported || []).join(", ")}`;

          if (result.warnings && result.warnings.length > 0) {
            msg += `\n\n주의:\n${result.warnings.join("\n")}`;
          }

          alert(msg);

          // 사이드바 문헌 목록 갱신
          if (typeof loadLibraryInfo === "function") {
            loadLibraryInfo();
          }
        } catch (e) {
          alert(`가져오기 실패:\n${e.message}`);
        } finally {
          importBtn.disabled = false;
          importBtn.textContent = "가져오기";
          input.remove();
        }
      });

      document.body.appendChild(input);
      input.click();
    });
  }
}


/* ──────────────────────────
   페이지 변경 공통 동기화
   ──────────────────────────
   사이드바 트리 클릭(_selectPage)과 PDF 툴바 ◀▶ 버튼(_syncPageChange),
   키보드 단축키, URL 해시 복원 등 어떤 경로로 페이지가 바뀌더라도
   모든 패널을 동일하게 갱신하기 위한 단일 진입점.

   왜 이렇게 하는가:
     이전에는 _selectPage(9가지 동기화)와 _syncPageChange(3가지만)가
     불일치하여 툴바로 페이지를 넘기면 교정·해석·비고 등이 갱신되지 않았다.
*/

/**
 * 페이지 변경 후 모든 패널을 동기화한다.
 *
 * 입력:
 *   opts.skipText — true이면 텍스트 로드 생략 (이미 로드한 경우)
 *   opts.skipHighlight — true이면 사이드바 하이라이트 생략 (직접 처리한 경우)
 */
// eslint-disable-next-line no-unused-vars
function onPageChanged(opts) {
  opts = opts || {};
  const docId = viewerState.docId;
  const partId = viewerState.partId;
  const pageNum = viewerState.pageNum;
  if (!docId || !partId || !pageNum) return;

  // 1. 텍스트 에디터
  if (!opts.skipText && typeof loadPageText === "function") {
    loadPageText(docId, partId, pageNum);
  }

  // 2. 사이드바 하이라이트
  if (!opts.skipHighlight && typeof highlightTreePage === "function") {
    highlightTreePage(pageNum);
  }

  // 3. 레이아웃 동기화 (활성 시)
  if (typeof loadPageLayout === "function" &&
      typeof layoutState !== "undefined" && layoutState.active) {
    loadPageLayout(docId, partId, pageNum);
  }

  // 4. 교정 동기화 (활성 시)
  if (typeof loadPageCorrections === "function" &&
      typeof correctionState !== "undefined" && correctionState.active) {
    loadPageCorrections(docId, partId, pageNum);
  }

  // 5. Git 이력
  if (typeof _loadGitLog === "function") {
    _loadGitLog(docId);
  }

  // 6. 서지정보
  if (typeof loadBibliography === "function") {
    loadBibliography(docId);
  }

  // 7. 해석 층 내용 (활성 시)
  if (typeof interpState !== "undefined" && interpState.active && interpState.interpId) {
    if (typeof _loadLayerContent === "function") {
      _loadLayerContent();
    }
  }

  // 8. OCR 결과 (레이아웃 모드 활성 시)
  if (typeof loadOcrResults === "function" &&
      typeof layoutState !== "undefined" && layoutState.active) {
    loadOcrResults();
  }

  // 9. 비고/메모 (탭 표시 중일 때)
  if (typeof loadPageNotes === "function") {
    const notesPanel = document.getElementById("notes-panel-content");
    if (notesPanel && notesPanel.style.display !== "none") {
      loadPageNotes();
    }
  }

  // 10. 이전/다음 버튼 상태 (Plan 3에서 추가)
  if (typeof _updateNavButtonStates === "function") {
    _updateNavButtonStates();
  }

  // 11. URL 해시 업데이트 (Plan 4에서 추가)
  if (typeof _updateHash === "function") {
    _updateHash();
  }
}


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
  const notesContent = document.getElementById("notes-panel-content");

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");

      // 탭 내용 전환: 0=Git, 1=검증결과, 2=의존추적, 3=엔티티, 4=비고
      if (gitContent) gitContent.style.display = (index === 0) ? "" : "none";
      if (validationContent) validationContent.style.display = (index === 1) ? "" : "none";
      if (depContent) depContent.style.display = (index === 2) ? "" : "none";
      if (entityContent) entityContent.style.display = (index === 3) ? "" : "none";
      if (notesContent) notesContent.style.display = (index === 4) ? "" : "none";

      // Phase 8: 엔티티 탭 활성화 시 엔티티 로드
      if (index === 3 && typeof _loadEntitiesForCurrentPage === "function") {
        _loadEntitiesForCurrentPage();
      }

      // 비고 탭 활성화 시 메모 로드
      if (index === 4 && typeof loadPageNotes === "function") {
        loadPageNotes();
      }
    });
  });
}


/* ──────────────────────────
   공통 LLM 모델 선택 로더
   ──────────────────────────
   OCR, 표점, 번역, 주석 등 모든 모드에서 동일한
   LLM 프로바이더/모델 드롭다운을 공유한다.
   /api/llm/models를 한 번만 fetch하여 모든 셀렉트를 채운다.
*/

/**
 * 모든 LLM 모델 드롭다운을 한 번에 채운다.
 *
 * DOMContentLoaded 끝에서 호출한다.
 * /api/llm/models를 한 번만 fetch하고,
 * class="llm-model-select"인 모든 <select>에 옵션을 채운다.
 *
 * 왜 이 방식인가:
 *   개별 init 함수에서 각각 호출하면 타이밍 문제가 생길 수 있다.
 *   한 곳에서 한 번에 처리하면 확실하다.
 */
async function _loadAllLlmModelSelects() {
  // class="llm-model-select"인 모든 <select> 찾기
  const selects = document.querySelectorAll("select.llm-model-select");
  if (selects.length === 0) return;

  try {
    const res = await fetch("/api/llm/models");
    if (!res.ok) {
      console.warn("LLM 모델 목록 로드 실패:", res.status);
      return;
    }
    const models = await res.json();
    console.log(`LLM 모델 ${models.length}개 로드 → ${selects.length}개 드롭다운에 적용`);

    // 모든 셀렉트에 동일한 옵션 채우기
    for (const select of selects) {
      _fillLlmSelect(select, models);
    }
  } catch (e) {
    console.warn("LLM 모델 목록 로드 실패:", e);
  }
}

function _fillLlmSelect(select, models) {
  // data-vision-only 속성이 있으면 비전 지원 모델만 표시 (OCR, 레이아웃 분석용)
  const visionOnly = select.hasAttribute("data-vision-only");

  select.innerHTML = '<option value="auto">자동 (폴백순서)</option>';
  for (const m of models) {
    if (visionOnly && !m.vision) continue;  // 비전 미지원 모델 제외
    const opt = document.createElement("option");
    opt.value = `${m.provider}:${m.model}`;
    const icon = m.available ? "●" : "○";
    const costLabel = m.cost === "free" ? "" : " [유료]";
    const visionLabel = m.vision ? " 👁" : "";
    opt.textContent = `${icon} ${m.display}${costLabel}${visionLabel}`;
    opt.disabled = !m.available;
    select.appendChild(opt);
  }
}

/**
 * selectId의 <select>에서 force_provider, force_model을 파싱한다.
 *
 * 반환: { force_provider: string|null, force_model: string|null }
 */
function getLlmModelSelection(selectId) {
  const select = document.getElementById(selectId);
  const value = select ? select.value : "auto";

  if (value === "auto") {
    return { force_provider: null, force_model: null };
  }

  // 모델명에 콜론이 포함될 수 있으므로 (예: "qwen3-vl:235b-cloud")
  // 첫 번째 콜론에서만 분리한다.
  const colonIdx = value.indexOf(":");
  const provider = value.substring(0, colonIdx);
  const model = value.substring(colonIdx + 1);
  return {
    force_provider: provider || null,
    force_model: model && model !== "auto" ? model : null,
  };
}


/* ──────────────────────────
   URL 해시 라우팅 (Plan 4)
   ──────────────────────────
   형식: #doc_id/part_id/page_num  (예: #monggu/vol1/3)

   왜 이렇게 하는가:
     1. 새로고침해도 열람 위치가 복원된다.
     2. 브라우저 뒤로/앞으로 버튼으로 이전 페이지로 돌아갈 수 있다.
     3. URL을 공유하면 같은 페이지를 바로 열 수 있다 (딥링크).
*/

/** 해시 업데이트 억제 플래그 (복원 중 해시 재생성 방지) */
let _suppressHashUpdate = false;

/**
 * 현재 viewerState를 URL 해시에 반영한다.
 * onPageChanged()에서 호출된다.
 */
function _updateHash() {
  if (_suppressHashUpdate) return;
  const { docId, partId, pageNum } = viewerState;
  if (!docId || !partId || !pageNum) return;

  const newHash = `#${docId}/${partId}/${pageNum}`;
  // 같은 해시면 중복 pushState 방지
  if (window.location.hash === newHash) return;
  history.pushState(null, "", newHash);
}

/**
 * URL 해시를 파싱한다.
 * 반환: { docId, partId, pageNum } 또는 null
 */
function _parseHash() {
  const hash = window.location.hash.replace(/^#/, "");
  if (!hash) return null;

  const parts = hash.split("/");
  if (parts.length < 3) return null;

  const docId = parts[0];
  const partId = parts[1];
  const pageNum = parseInt(parts[2], 10);
  if (!docId || !partId || isNaN(pageNum) || pageNum < 1) return null;

  return { docId, partId, pageNum };
}

/**
 * URL 해시에서 열람 위치를 복원한다.
 * loadLibraryInfo() 완료 후 호출된다.
 */
async function _restoreFromHash() {
  const target = _parseHash();
  if (!target) return;

  try {
    // 문헌 상세 가져오기 (parts 정보 필요)
    const res = await fetch(`/api/documents/${target.docId}`);
    if (!res.ok) return;
    const docInfo = await res.json();

    // viewerState 설정
    viewerState.docId = target.docId;
    viewerState.partId = target.partId;
    viewerState.pageNum = target.pageNum;
    viewerState.documentInfo = docInfo;

    // 해시 재생성 억제 (이미 해시에서 복원 중)
    _suppressHashUpdate = true;

    // PDF 로드
    if (typeof loadPdfPage === "function") {
      loadPdfPage(target.docId, target.partId, target.pageNum);
    }

    // 다권본 선택기 업데이트
    if (typeof updatePartSelector === "function" && docInfo.parts) {
      updatePartSelector(docInfo.parts, target.partId);
    }

    // 모든 패널 동기화
    if (typeof onPageChanged === "function") {
      onPageChanged();
    }

    // 서지정보·해석 섹션 표시
    const bibSec = document.getElementById("bib-section");
    const interpSec = document.getElementById("interp-section");
    if (bibSec) bibSec.style.display = "";
    if (interpSec) interpSec.style.display = "";

    _suppressHashUpdate = false;
  } catch (e) {
    _suppressHashUpdate = false;
    console.warn("해시 복원 실패:", e);
  }
}

// 브라우저 뒤로/앞으로 버튼 → 해시 파싱 → 페이지 복원
window.addEventListener("popstate", () => {
  const target = _parseHash();
  if (!target) return;

  // 같은 위치면 무시
  if (viewerState.docId === target.docId &&
      viewerState.partId === target.partId &&
      viewerState.pageNum === target.pageNum) return;

  viewerState.docId = target.docId;
  viewerState.partId = target.partId;
  viewerState.pageNum = target.pageNum;

  _suppressHashUpdate = true;

  if (typeof loadPdfPage === "function") {
    loadPdfPage(target.docId, target.partId, target.pageNum);
  }

  if (typeof onPageChanged === "function") {
    onPageChanged();
  }

  _suppressHashUpdate = false;
});


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
