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
  // 각 모듈 초기화를 try-catch로 감싸서, 한 모듈이 실패해도
  // 나머지 모듈이 정상 초기화되도록 보호한다.
  // 왜: 모듈 하나가 에러를 던지면 그 이후의 모든 init이 실행되지 않아
  //      버튼 클릭 등 이벤트가 전혀 동작하지 않는 문제가 발생한다.
  function _safeInit(name, fn) {
    try {
      fn();
    } catch (err) {
      console.error(`[workspace] ${name} 초기화 실패:`, err);
    }
  }

  _safeInit("ResizeHandlers", initResizeHandlers);
  _safeInit("PanelToggle", initPanelToggle);
  _safeInit("ActivityBar", initActivityBar);
  _safeInit("ModeBar", initModeBar);
  _safeInit("LibraryInfo", loadLibraryInfo);
  // Phase 3: 병렬 뷰어 모듈 초기화
  if (typeof initPdfRenderer === "function") _safeInit("PdfRenderer", initPdfRenderer);
  if (typeof initTextEditor === "function") _safeInit("TextEditor", initTextEditor);
  // Phase 4: 레이아웃 편집기 초기화
  if (typeof initLayoutEditor === "function") _safeInit("LayoutEditor", initLayoutEditor);
  // Phase 6: 교정 편집기 초기화
  if (typeof initCorrectionEditor === "function") _safeInit("CorrectionEditor", initCorrectionEditor);
  // Phase 5: 서지정보 패널 초기화
  if (typeof initBibliography === "function") _safeInit("Bibliography", initBibliography);
  // Phase 7: 해석 저장소 모듈 초기화
  if (typeof initInterpretation === "function") _safeInit("Interpretation", initInterpretation);
  // Phase 8: 엔티티 관리 모듈 초기화
  if (typeof initEntityManager === "function") _safeInit("EntityManager", initEntityManager);
  // Phase 10: 새 문헌 생성 모듈 초기화
  if (typeof initCreateDocument === "function") _safeInit("CreateDocument", initCreateDocument);
  // Phase 10-1: OCR 패널 초기화
  if (typeof initOcrPanel === "function") _safeInit("OcrPanel", initOcrPanel);
  // Phase 10-3: 대조 뷰 초기화
  if (typeof initAlignmentView === "function") _safeInit("AlignmentView", initAlignmentView);
  // 편성 에디터 초기화 (LayoutBlock → TextBlock)
  if (typeof initCompositionEditor === "function") _safeInit("CompositionEditor", initCompositionEditor);
  // Phase 11-1: 표점 편집기 초기화
  if (typeof initPunctuationEditor === "function") _safeInit("PunctuationEditor", initPunctuationEditor);
  // Phase 11-1: 현토 편집기 초기화
  if (typeof initHyeontoEditor === "function") _safeInit("HyeontoEditor", initHyeontoEditor);
  // Phase 11-2: 번역 편집기 초기화
  if (typeof initTranslationEditor === "function") _safeInit("TranslationEditor", initTranslationEditor);
  // Phase 11-3: 주석 편집기 초기화
  if (typeof initAnnotationEditor === "function") _safeInit("AnnotationEditor", initAnnotationEditor);
  // 인용 마크 편집기 초기화
  if (typeof initCitationEditor === "function") _safeInit("CitationEditor", initCitationEditor);
  // 인용 양식 관리 초기화
  if (typeof initCiteFormatManager === "function") _safeInit("CiteFormatManager", initCiteFormatManager);
  // 이체자 사전 관리 초기화
  if (typeof initVariantManager === "function") _safeInit("VariantManager", initVariantManager);
  // 일괄 교정 초기화
  if (typeof initBatchCorrection === "function") _safeInit("BatchCorrection", initBatchCorrection);
  // Phase 12-1: Git 그래프 초기화
  if (typeof initGitGraph === "function") _safeInit("GitGraph", initGitGraph);
  // Phase 12-3: JSON 스냅샷 Export/Import 버튼
  _safeInit("SnapshotButtons", initSnapshotButtons);
  // 읽기 보조선 초기화
  if (typeof initReaderLine === "function") _safeInit("ReaderLine", initReaderLine);
  // 비고/메모 패널 초기화
  if (typeof initNotesPanel === "function") _safeInit("NotesPanel", initNotesPanel);
  // 하단 패널 제거됨: 모든 탭이 액티비티 바 사이드바로 이동

  // 전 모드 LLM 모델 드롭다운 채우기 (모든 init 완료 후 한 번만)
  _safeInit("LlmModelSelects", _loadAllLlmModelSelects);
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

  // 하단 패널 제거됨: 리사이즈 핸들 불필요
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

  // 패널별 사이드바 섹션 매핑
  // explorer: 문헌목록 + 서지정보 + 해석저장소
  // settings: 설정 패널
  // git~notes: 구 하단 패널 탭들 → 사이드바로 이동
  const panelSections = {
    explorer: ["document-list", "bib-section", "interp-section"],
    settings: ["settings-section"],
    git: ["git-sidebar-section"],
    validation: ["validation-sidebar-section"],
    dependency: ["dep-sidebar-section"],
    entity: ["entity-sidebar-section"],
    notes: ["notes-sidebar-section"],
    "cite-formats": ["cite-formats-sidebar-section"],
  };

  // 패널별 사이드바 타이틀
  const panelTitles = {
    explorer: "서고 브라우저",
    settings: "설정",
    git: "Git 이력",
    validation: "검증 결과",
    dependency: "의존 추적",
    entity: "엔티티",
    notes: "비고",
    "cite-formats": "인용 양식",
  };

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const panel = btn.getAttribute("data-panel");
      const sidebar = document.getElementById("sidebar");
      const resizeHandle = document.getElementById("resize-sidebar");
      const workspace = document.querySelector(".workspace");

      // VSCode 스타일: 이미 활성인 버튼을 다시 클릭하면 사이드바 접기/펼치기
      if (btn.classList.contains("active")) {
        const isCollapsed = sidebar.classList.toggle("collapsed");
        if (resizeHandle)
          resizeHandle.style.display = isCollapsed ? "none" : "";
        // 그리드 컬럼 조정: 사이드바+리사이즈 영역을 0으로
        if (workspace) {
          workspace.style.gridTemplateColumns = isCollapsed
            ? "48px 0px 0px 1fr"
            : `48px var(--sidebar-width) 4px 1fr`;
        }
        // 세로맞춤 시 PDF가 새 너비에 맞게 재조정
        if (typeof _autoFit === "function") {
          setTimeout(() => _autoFit(), 50);
        }
        return;
      }

      // 다른 버튼을 클릭하면 사이드바 펼치기 + 패널 전환
      buttons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      // 접혀 있으면 펼치기
      if (sidebar.classList.contains("collapsed")) {
        sidebar.classList.remove("collapsed");
        if (resizeHandle) resizeHandle.style.display = "";
        if (workspace) {
          workspace.style.gridTemplateColumns = `48px var(--sidebar-width) 4px 1fr`;
        }
        if (typeof _autoFit === "function") {
          setTimeout(() => _autoFit(), 50);
        }
      }

      // 모든 sidebar-section 숨김
      document
        .querySelectorAll("#sidebar-content .sidebar-section")
        .forEach((s) => {
          s.style.display = "none";
        });

      // 사이드바 타이틀 업데이트
      const titleEl = document.querySelector(".sidebar-title");
      if (titleEl) titleEl.textContent = panelTitles[panel] || panel;

      if (panel === "settings") {
        // 설정 패널 표시
        const settingsEl = document.getElementById("settings-section");
        if (settingsEl) {
          settingsEl.style.display = "";
          _loadSettings();
        }
      } else if (panel === "explorer") {
        // explorer: 기존 섹션 복원
        const docList = document.querySelector(
          "#sidebar-content > .sidebar-section:first-child",
        );
        if (docList) docList.style.display = "";
        // 문헌 선택 상태에 따라 서지/해석 섹션 복원
        const bibSec = document.getElementById("bib-section");
        const interpSec = document.getElementById("interp-section");
        if (bibSec && typeof viewerState !== "undefined" && viewerState.docId) {
          bibSec.style.display = "";
        }
        if (
          interpSec &&
          typeof viewerState !== "undefined" &&
          viewerState.docId
        ) {
          interpSec.style.display = "";
        }
      } else {
        // git, validation, dependency, entity, notes — 해당 섹션 표시
        const sectionIds = panelSections[panel];
        if (sectionIds) {
          sectionIds.forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.style.display = "";
          });
        }

        // 패널별 데이터 로드 트리거
        if (
          panel === "git" &&
          typeof _loadGitLog === "function" &&
          typeof viewerState !== "undefined" &&
          viewerState.docId
        ) {
          _loadGitLog(viewerState.docId);
        }
        if (
          panel === "entity" &&
          typeof _loadEntitiesForCurrentPage === "function"
        ) {
          _loadEntitiesForCurrentPage();
        }
        if (panel === "notes" && typeof loadPageNotes === "function") {
          loadPageNotes();
        }
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

    // 서고 경로 표시 (input 필드에)
    const inputEl = document.getElementById("settings-library-input");
    if (inputEl) {
      inputEl.value = data.library_path || "";
      inputEl.title = data.library_path || "";
    }

    // 서고 편집/전환 버튼 이벤트 바인딩 (1회만)
    _initLibraryControls();

    // 최근 서고 목록 로드
    _loadRecentLibraries();

    // 원본 저장소 목록
    _renderRepoList("settings-doc-repos", data.documents || [], "documents");

    // 해석 저장소 목록
    _renderRepoList(
      "settings-interp-repos",
      data.interpretations || [],
      "interpretations",
    );

    // 백업 경로 및 백업 정보 표시
    _loadBackupInfo(data);
  } catch (e) {
    console.warn("설정 로드 실패:", e);
  }
}

/* ─── 서고 경로 관리 ───────────────────────────── */

let _libraryControlsInitialized = false;

function _initLibraryControls() {
  if (_libraryControlsInitialized) return;
  _libraryControlsInitialized = true;

  const browseBtn = document.getElementById("btn-browse-library");
  const newBtn = document.getElementById("btn-new-library");

  // "폴더 선택" 버튼 → 네이티브 폴더 대화상자 열기
  if (browseBtn) {
    browseBtn.addEventListener("click", _browseAndSwitchLibrary);
  }

  // "새 서고" 버튼 → 폴더 선택 후 서고 초기화
  if (newBtn) {
    newBtn.addEventListener("click", _createNewLibrary);
  }

  // 백업 관련 버튼 이벤트
  const browseBackupBtn = document.getElementById("btn-browse-backup");
  if (browseBackupBtn) {
    browseBackupBtn.addEventListener("click", _browseBackupFolder);
  }

  const saveBackupBtn = document.getElementById("btn-save-backup-path");
  if (saveBackupBtn) {
    saveBackupBtn.addEventListener("click", _saveBackupPath);
  }

  const execBackupBtn = document.getElementById("btn-execute-backup");
  if (execBackupBtn) {
    execBackupBtn.addEventListener("click", _executeBackup);
  }
}

/**
 * 네이티브 폴더 선택 대화상자를 열고, 선택된 폴더로 서고를 전환한다.
 *
 * 왜 이렇게 하는가:
 *   비개발자 연구자가 경로를 직접 타이핑하지 않고
 *   Windows 탐색기 스타일의 폴더 선택으로 서고를 지정할 수 있게 한다.
 *   선택된 폴더에 library_manifest.json이 없으면
 *   새 서고를 만들지 확인한다.
 */
async function _browseAndSwitchLibrary() {
  try {
    const res = await fetch("/api/library/browse", { method: "POST" });
    const data = await res.json();
    if (data.cancelled) return;

    const path = data.path;
    const inputEl = document.getElementById("settings-library-input");
    if (inputEl) inputEl.value = path;

    // 기존 서고인지 확인 (switch 시도)
    const switchRes = await fetch("/api/library/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });

    if (switchRes.ok) {
      location.reload();
      return;
    }

    // switch 실패 = 유효한 서고가 아님 → 새 서고 생성 제안
    if (confirm("이 폴더에 새 서고를 만들까요?\n\n" + path)) {
      const initRes = await fetch("/api/library/init", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const initData = await initRes.json();

      if (!initRes.ok) {
        showToast("서고 생성 실패: " + (initData.error || "알 수 없는 오류"), "error");
        return;
      }
      location.reload();
    }
  } catch (e) {
    showToast("폴더 선택 실패: " + e.message, "error");
  }
}

async function _switchLibrary(path) {
  try {
    const res = await fetch("/api/library/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    const data = await res.json();

    if (!res.ok) {
      showToast("서고 전환 실패: " + (data.error || "알 수 없는 오류"), 'error');
      return;
    }

    // 전체 페이지 리로드 (상태 초기화)
    location.reload();
  } catch (e) {
    showToast("서고 전환 실패: " + e.message, 'error');
  }
}

async function _createNewLibrary() {
  try {
    // 폴더 선택 대화상자
    const browseRes = await fetch("/api/library/browse", { method: "POST" });
    const browseData = await browseRes.json();
    if (browseData.cancelled) return;

    const path = browseData.path;

    const res = await fetch("/api/library/init", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    const data = await res.json();

    if (!res.ok) {
      showToast("서고 생성 실패: " + (data.error || "알 수 없는 오류"), "error");
      return;
    }

    location.reload();
  } catch (e) {
    showToast("서고 생성 실패: " + e.message, "error");
  }
}

/* ─── 서고 백업 관리 ───────────────────────────── */

/**
 * 백업 정보를 UI에 표시한다.
 * _loadSettings()에서 호출된다.
 */
function _loadBackupInfo(settingsData) {
  const inputEl = document.getElementById("settings-backup-input");
  if (inputEl && settingsData.backup_path) {
    inputEl.value = settingsData.backup_path;
    inputEl.title = settingsData.backup_path;
  }

  const infoEl = document.getElementById("backup-info");
  if (!infoEl) return;

  const bi = settingsData.backup_info;
  if (bi) {
    infoEl.style.display = "";
    const timeEl = document.getElementById("backup-last-time");
    const countEl = document.getElementById("backup-file-count");
    if (timeEl) {
      const d = new Date(bi.timestamp);
      timeEl.textContent = "마지막 백업: " + d.toLocaleString("ko-KR");
    }
    if (countEl) {
      const sizeMB = (bi.total_size / (1024 * 1024)).toFixed(1);
      countEl.textContent = `${bi.file_count}개 파일, ${sizeMB} MB`;
    }
  } else {
    infoEl.style.display = "none";
  }
}

/**
 * 백업 폴더 선택 대화상자를 열어 경로를 표시한다.
 */
async function _browseBackupFolder() {
  try {
    const res = await fetch("/api/library/browse", { method: "POST" });
    const data = await res.json();
    if (data.cancelled) return;

    const inputEl = document.getElementById("settings-backup-input");
    if (inputEl) {
      inputEl.value = data.path;
      inputEl.title = data.path;
    }
  } catch (e) {
    showToast("폴더 선택 실패: " + e.message, "error");
  }
}

/**
 * 백업 경로를 서버에 저장한다.
 */
async function _saveBackupPath() {
  const inputEl = document.getElementById("settings-backup-input");
  if (!inputEl || !inputEl.value) {
    showToast("백업 폴더를 먼저 선택하세요.", "warning");
    return;
  }

  try {
    const res = await fetch("/api/settings/backup-path", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: inputEl.value }),
    });
    const data = await res.json();

    if (!res.ok) {
      showToast("저장 실패: " + (data.error || "알 수 없는 오류"), "error");
      return;
    }

    showToast("백업 경로가 저장되었습니다.");
  } catch (e) {
    showToast("저장 실패: " + e.message, "error");
  }
}

/**
 * 서고를 백업 폴더에 복사한다.
 * 확인 대화상자를 거친 후 실행한다.
 */
async function _executeBackup() {
  if (!confirm("서고를 백업 폴더에 복사합니다.\n기존 백업이 있으면 교체됩니다.\n계속하시겠습니까?")) {
    return;
  }

  const btn = document.getElementById("btn-execute-backup");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "백업 중...";
  }

  try {
    const res = await fetch("/api/library/backup", { method: "POST" });
    const data = await res.json();

    if (!res.ok) {
      showToast("백업 실패: " + (data.error || "알 수 없는 오류"), "error");
      return;
    }

    const sizeMB = (data.total_size / (1024 * 1024)).toFixed(1);
    showToast(
      `백업 완료: ${data.file_count}개 파일, ${sizeMB} MB (${data.duration_sec}초)`
    );

    // 백업 정보 새로고침
    _loadSettings();
  } catch (e) {
    showToast("백업 실패: " + e.message, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "서고 백업";
    }
  }
}

async function _loadRecentLibraries() {
  const container = document.getElementById("recent-libraries");
  if (!container) return;

  try {
    const res = await fetch("/api/library/recent");
    if (!res.ok) return;
    const data = await res.json();
    const libraries = data.libraries || [];
    const current = data.current || "";

    if (libraries.length <= 1) {
      container.innerHTML = "";
      return;
    }

    container.innerHTML = "";
    for (const lib of libraries) {
      const item = document.createElement("div");
      item.className =
        "recent-library-item" + (lib.path === current ? " current" : "");

      const nameSpan = document.createElement("span");
      nameSpan.className = "recent-library-name";
      nameSpan.textContent = lib.name || "이름 없음";

      const pathSpan = document.createElement("span");
      pathSpan.className = "recent-library-path";
      pathSpan.textContent = lib.path;

      item.appendChild(nameSpan);
      item.appendChild(pathSpan);

      if (lib.path !== current) {
        item.addEventListener("click", () => _switchLibrary(lib.path));
        item.title = "클릭하여 이 서고로 전환";
      } else {
        item.title = "현재 서고";
      }

      container.appendChild(item);
    }
  } catch (e) {
    console.debug("최근 서고 목록 로드 실패:", e);
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

    item.innerHTML = `
      <div class="settings-repo-header">
        <strong>${repo.id}</strong>
        <button class="text-btn settings-remote-toggle" title="원격 동기화 설정">
          ${hasRemote ? "● 원격 연결됨" : "원격 설정 ▸"}
        </button>
      </div>
      <div class="settings-repo-remote" style="display: ${hasRemote ? "flex" : "none"};">
        <input type="text" class="settings-remote-input"
               placeholder="원격 URL (예: https://github.com/...)"
               value="${repo.remote_url || ""}"
               data-repo-type="${repoType}" data-repo-id="${repo.id}">
        <button class="text-btn settings-remote-save" title="원격 URL 저장">저장</button>
      </div>
      <div class="settings-repo-actions" style="display: ${hasRemote ? "flex" : "none"};">
        <button class="text-btn settings-push-btn"
                data-repo-type="${repoType}" data-repo-id="${repo.id}"
                ${hasRemote ? "" : "disabled"}>Push</button>
        <button class="text-btn settings-pull-btn"
                data-repo-type="${repoType}" data-repo-id="${repo.id}"
                ${hasRemote ? "" : "disabled"}>Pull</button>
      </div>
    `;

    // 원격 설정 토글 버튼
    item.querySelector(".settings-remote-toggle").addEventListener("click", () => {
      const remoteDiv = item.querySelector(".settings-repo-remote");
      const actionsDiv = item.querySelector(".settings-repo-actions");
      const hidden = remoteDiv.style.display === "none";
      remoteDiv.style.display = hidden ? "flex" : "none";
      actionsDiv.style.display = hidden ? "flex" : "none";
    });

    // 원격 URL 저장 버튼
    item
      .querySelector(".settings-remote-save")
      .addEventListener("click", async () => {
        const input = item.querySelector(".settings-remote-input");
        const url = input.value.trim();
        if (!url) {
          showToast("원격 URL을 입력하세요.", 'warning');
          return;
        }

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
          showToast(`원격 URL 설정 완료: ${url}`, 'success');
          _loadSettings(); // 새로고침
        } catch (e) {
          showToast(`원격 설정 실패: ${e.message}`, 'error');
        }
      });

    // Push/Pull 버튼
    const pushBtn = item.querySelector(".settings-push-btn");
    const pullBtn = item.querySelector(".settings-pull-btn");

    if (pushBtn) {
      pushBtn.addEventListener("click", () =>
        _gitSync(repoType, repo.id, "push"),
      );
    }
    if (pullBtn) {
      pullBtn.addEventListener("click", () =>
        _gitSync(repoType, repo.id, "pull"),
      );
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
    if (!res.ok) {
      const lines = [result.error || "알 수 없는 오류"];
      if (result.detail) lines.push(result.detail);
      if (result.hint) lines.push(`안내: ${result.hint}`);
      if (result.retried) lines.push("(서버에서 자동 재시도 1회 수행됨)");
      throw new Error(lines.join("\n"));
    }
    showToast(`${label} 완료: ${result.output || "성공"}`, 'success');
  } catch (e) {
    showToast(`${label} 실패: ${e.message}`, 'error');
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
      modeTabs.forEach((t) => {
        t.classList.remove("active");
        t.setAttribute("aria-selected", "false");
      });
      tab.classList.add("active");
      tab.setAttribute("aria-selected", "true");

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
  // Interpretation mode tab is removed from UI. Fallback to view if called externally.
  if (mode === "interpretation") {
    mode = "view";
  }

  const editorRight = document.getElementById("editor-right");
  const layoutPanel = document.getElementById("layout-props-panel");
  const correctionPanel = document.getElementById("correction-panel");
  const compositionPanel = document.getElementById("composition-panel");
  const interpPanel = document.getElementById("interp-panel");
  const punctPanel = document.getElementById("punct-panel");
  const hyeontoPanel = document.getElementById("hyeonto-panel");
  const transPanel = document.getElementById("trans-panel");
  const annPanel = document.getElementById("ann-panel");
  const citePanel = document.getElementById("cite-panel");
  const variantPanel = document.getElementById("variant-panel");

  // 이전 모드 정리
  if (currentMode === "layout") {
    if (typeof deactivateLayoutMode === "function") deactivateLayoutMode();
    if (layoutPanel) layoutPanel.style.display = "none";
  }
  if (currentMode === "correction") {
    if (typeof deactivateCorrectionMode === "function")
      deactivateCorrectionMode();
    if (correctionPanel) correctionPanel.style.display = "none";
  }
  if (currentMode === "composition") {
    if (typeof deactivateCompositionMode === "function")
      deactivateCompositionMode();
    if (compositionPanel) compositionPanel.style.display = "none";
  }
  if (currentMode === "interpretation") {
    if (typeof deactivateInterpretationMode === "function")
      deactivateInterpretationMode();
    if (interpPanel) interpPanel.style.display = "none";
  }
  if (currentMode === "punctuation") {
    if (typeof deactivatePunctuationMode === "function")
      deactivatePunctuationMode();
    if (punctPanel) punctPanel.style.display = "none";
  }
  if (currentMode === "hyeonto") {
    if (typeof deactivateHyeontoMode === "function") deactivateHyeontoMode();
    if (hyeontoPanel) hyeontoPanel.style.display = "none";
  }
  if (currentMode === "translation") {
    if (typeof deactivateTranslationMode === "function")
      deactivateTranslationMode();
    if (transPanel) transPanel.style.display = "none";
  }
  if (currentMode === "annotation") {
    if (typeof deactivateAnnotationMode === "function")
      deactivateAnnotationMode();
    if (annPanel) annPanel.style.display = "none";
  }
  if (currentMode === "citation") {
    if (typeof deactivateCitationMode === "function") deactivateCitationMode();
    if (citePanel) citePanel.style.display = "none";
  }
  if (currentMode === "variant") {
    if (typeof deactivateVariantMode === "function") deactivateVariantMode();
    if (variantPanel) variantPanel.style.display = "none";
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
  if (citePanel) citePanel.style.display = "none";
  if (variantPanel) variantPanel.style.display = "none";

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
    if (typeof activateCompositionMode === "function")
      activateCompositionMode();
  } else if (mode === "interpretation") {
    // 우측: 해석 뷰어 패널 표시
    if (interpPanel) interpPanel.style.display = "";
    if (typeof activateInterpretationMode === "function")
      activateInterpretationMode();
  } else if (mode === "punctuation") {
    // 우측: 표점 편집기 패널 표시
    if (punctPanel) punctPanel.style.display = "";
    if (typeof activatePunctuationMode === "function")
      activatePunctuationMode();
  } else if (mode === "hyeonto") {
    // 우측: 현토 편집기 패널 표시
    if (hyeontoPanel) hyeontoPanel.style.display = "";
    if (typeof activateHyeontoMode === "function") activateHyeontoMode();
  } else if (mode === "translation") {
    // 우측: 번역 편집기 패널 표시
    if (transPanel) transPanel.style.display = "";
    if (typeof activateTranslationMode === "function")
      activateTranslationMode();
  } else if (mode === "annotation") {
    // 우측: 주석 편집기 패널 표시
    if (annPanel) annPanel.style.display = "";
    if (typeof activateAnnotationMode === "function") activateAnnotationMode();
  } else if (mode === "citation") {
    // 우측: 인용 마크 패널 표시
    if (citePanel) citePanel.style.display = "";
    if (typeof activateCitationMode === "function") activateCitationMode();
  } else if (mode === "variant") {
    // 우측: 이체자 사전 관리 패널 표시
    if (variantPanel) variantPanel.style.display = "";
    if (typeof activateVariantMode === "function") activateVariantMode();
  } else {
    // view 모드: 텍스트 에디터 표시
    if (editorRight) editorRight.style.display = "";
  }
}

/* ──────────────────────────
   5. 서고 정보 로드
   ────────────────────────── */

/**
 * hwp-import.js 등 외부 모듈에서 가져오기 완료 후 사이드바를 갱신할 때 호출한다.
 * loadLibraryInfo()의 별칭으로, 문헌 목록을 다시 불러와 트리를 다시 그린다.
 */
// eslint-disable-next-line no-unused-vars
function _loadDocumentList() {
  loadLibraryInfo();
}

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
    // 서고 미설정 또는 API 연결 실패 — 서고 선택 안내를 표시
    const docList = document.getElementById("document-list");
    docList.innerHTML =
      '<div class="placeholder no-library-guide">' +
      '  <p>서고가 연결되지 않았습니다.</p>' +
      '  <button class="btn-sm btn-primary" id="btn-goto-settings">서고 설정 열기</button>' +
      '</div>';
    const goBtn = document.getElementById("btn-goto-settings");
    if (goBtn) {
      goBtn.addEventListener("click", () => {
        // 설정 패널의 activity-bar 버튼 클릭을 시뮬레이션
        const settingsBtn = document.querySelector('.activity-btn[data-panel="settings"]');
        if (settingsBtn) settingsBtn.click();
      });
    }
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
        showToast("내보낼 해석 저장소를 먼저 선택해주세요.", 'warning');
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
        showToast(`내보내기 실패: ${e.message}`, 'error');
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
        importBtn.textContent = "JSON 가져오는 중…";

        try {
          // 파일 내용 읽기
          const text = await file.text();
          let data;
          try {
            data = JSON.parse(text);
          } catch {
            throw new Error(
              "올바른 JSON 파일이 아닙니다.\n" +
                "- JSON 스냅샷 파일(.json)은 'JSON 가져오기'\n" +
                "- 해석 저장소 폴더는 '폴더 가져오기'를 사용하세요.",
            );
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
          let msg =
            `JSON 가져오기 완료!\n\n` +
            `문헌: ${result.title}\n` +
            `문헌 ID: ${result.doc_id}\n` +
            `해석 ID: ${result.interp_id}\n` +
            `레이어: ${(result.layers_imported || []).join(", ")}`;

          if (result.warnings && result.warnings.length > 0) {
            msg += `\n\n주의:\n${result.warnings.join("\n")}`;
          }

          showToast(msg, 'success');

          // 사이드바 문헌 목록 갱신
          if (typeof loadLibraryInfo === "function") {
            loadLibraryInfo();
          }
        } catch (e) {
          showToast(`JSON 가져오기 실패:\n${e.message}`, 'error');
        } finally {
          importBtn.disabled = false;
          importBtn.textContent = "JSON 가져오기";
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
  if (
    typeof loadPageLayout === "function" &&
    typeof layoutState !== "undefined" &&
    layoutState.active
  ) {
    loadPageLayout(docId, partId, pageNum);
  }

  // 4. 교정 동기화 (활성 시)
  if (
    typeof loadPageCorrections === "function" &&
    typeof correctionState !== "undefined" &&
    correctionState.active
  ) {
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

  // 6-1. 해석 저장소 목록 (문서가 선택되면 항상 사이드바 목록 로드)
  if (typeof _loadInterpretationList === "function") {
    _loadInterpretationList();
  }

  // 7. 해석 층 내용 (활성 시)
  if (
    typeof interpState !== "undefined" &&
    interpState.active &&
    interpState.interpId
  ) {
    if (typeof _loadLayerContent === "function") {
      _loadLayerContent();
    }
  }

  // 8. OCR 결과 (레이아웃 모드 활성 시)
  if (
    typeof loadOcrResults === "function" &&
    typeof layoutState !== "undefined" &&
    layoutState.active
  ) {
    loadOcrResults();
  }

  // 9. 비고/메모 (사이드바에서 비고 패널 활성 시)
  if (typeof loadPageNotes === "function") {
    const notesSection = document.getElementById("notes-sidebar-section");
    if (notesSection && notesSection.style.display !== "none") {
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

/* initBottomPanelTabs() 제거됨: 모든 탭이 액티비티 바 사이드바로 이동 */

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
    console.log(
      `LLM 모델 ${models.length}개 로드 → ${selects.length}개 드롭다운에 적용`,
    );

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
    if (visionOnly && !m.vision) continue; // 비전 미지원 모델 제외
    const opt = document.createElement("option");
    opt.value = `${m.provider}:${m.model}`;
    const icon = m.available ? "●" : "○";
    const costLabel = m.cost === "free" ? "" : " [유료]";
    const visionLabel = m.vision ? " 👁" : "";
    opt.textContent = `${icon} ${m.display}${costLabel}${visionLabel}`;
    opt.disabled = !m.available;
    select.appendChild(opt);
  }

  // ── 추가 옵션 (data-extra-options 속성으로 활성화) ──
  // 표점 화면 등 LLM이 아닌 외부 서비스를 선택지로 노출하고 싶을 때 사용한다.
  // 값은 `provider:model` 규약을 따라 backend의 force_provider 분기와 맞물린다.
  const extra = select.getAttribute("data-extra-options");
  if (extra && extra.includes("punct-external")) {
    const opt = document.createElement("option");
    opt.value = "external:default";
    opt.textContent = "● 외부 표점 서비스 (SikuRoBERTa, 양정현 2025)";
    opt.title = "출처: yachagye/korean-classical-chinese-punctuation · CC BY-NC-SA 4.0 · DOI 10.37924/JSSW.100.9";
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
  if (
    viewerState.docId === target.docId &&
    viewerState.partId === target.partId &&
    viewerState.pageNum === target.pageNum
  )
    return;

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
    container.innerHTML =
      '<div class="placeholder">등록된 문헌이 없습니다</div>';
    return;
  }

  container.innerHTML = docs
    .map(
      (doc) => `
      <div class="tree-item" data-doc-id="${doc.document_id || ""}">
        ${doc.title || "제목 없음"}
        <span class="doc-id">${doc.document_id || ""}</span>
      </div>
    `,
    )
    .join("");

  // 클릭 이벤트
  container.querySelectorAll(".tree-item").forEach((item) => {
    item.addEventListener("click", () => {
      container
        .querySelectorAll(".tree-item")
        .forEach((i) => i.classList.remove("active"));
      item.classList.add("active");
      // 향후: 문헌 선택 시 에디터 영역에 내용 표시
    });
  });
}


// ===================================================================
//  공용 SSE 스트리밍 헬퍼 (LLM 호출 + 진행 바)
// ===================================================================
//
// 왜 여기에 두는가:
//   표점·번역·주석 에디터 모두 동일한 SSE 패턴을 사용한다.
//   OCR 패널은 독자적 구현이지만, LLM 기능은 공용으로 통일한다.
//
// 사용법:
//   const result = await fetchWithSSE(
//     "/api/llm/punctuation/stream",
//     { text: "子曰..." },
//     (progress) => showEditorProgress("punct", true, `AI 처리 중... ${progress.elapsed_sec}초`),
//     "/api/llm/punctuation"   // 폴백 URL
//   );
// ===================================================================


/**
 * SSE 스트리밍 fetch. progress 이벤트를 실시간으로 전달하고,
 * complete 이벤트의 result를 반환한다.
 *
 * @param {string} url        스트리밍 엔드포인트 URL
 * @param {object} body       POST 요청 body (JSON)
 * @param {function} onProgress  progress 이벤트 콜백 ({type, elapsed_sec, tokens, provider})
 * @param {string} fallbackUrl  스트리밍 실패 시 폴백할 기존 엔드포인트 URL
 * @returns {Promise<object>} complete 이벤트의 result 객체
 */
async function fetchWithSSE(url, body, onProgress, fallbackUrl) {
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    // 스트리밍이 아닌 에러 응답이면 폴백
    if (!resp.ok || !resp.headers.get("content-type")?.includes("text/event-stream")) {
      throw new Error(`SSE 응답 아님: ${resp.status}`);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let result = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE 형식: "data: {...}\n\n" 단위로 파싱
      const lines = buffer.split("\n\n");
      buffer = lines.pop(); // 아직 완성되지 않은 마지막 부분

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data: ")) continue;
        try {
          const data = JSON.parse(trimmed.slice(6));
          if (data.type === "progress" && onProgress) {
            onProgress(data);
          } else if (data.type === "complete") {
            result = data.result;
          } else if (data.type === "error") {
            throw new Error(data.error || "SSE 에러");
          }
        } catch (parseErr) {
          // JSON 파싱 실패면 에러 이벤트가 아닌 한 무시
          if (parseErr.message && !parseErr.message.includes("SSE")) {
            console.warn("[fetchWithSSE] 파싱 무시:", trimmed);
          } else {
            throw parseErr;
          }
        }
      }
    }

    if (result !== null) return result;
    throw new Error("SSE complete 이벤트 없이 스트림 종료");

  } catch (err) {
    console.warn(`[fetchWithSSE] 스트리밍 실패, 폴백 시도: ${err.message}`);
    if (!fallbackUrl) throw err;

    // 폴백: 기존 비스트리밍 엔드포인트 호출
    const resp = await fetch(fallbackUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${resp.status}`);
    }
    return await resp.json();
  }
}


/**
 * 잘린 LLM 응답 경고 표시.
 *
 * 왜 필요한가:
 *   LLM 응답이 토큰 한도 등으로 중간에 끊기면, 백엔드
 *   (_state.py의 _salvage_truncated_array_payload)가 완성된 항목만 복구하고
 *   결과에 _truncated:true·_recovered_count를 실어 보낸다. 이 플래그를 소비해
 *   연구자에게 알리지 않으면, 불완전한 표점·주석을 완전한 것으로 오인할 수 있다.
 *   따라서 여기서 토스트로 "잘려서 일부만 복구됨 — 재실행 권장"을 노출한다.
 *
 * @param {object} data  파싱된 LLM 결과 (result dict). _truncated 여부를 본다.
 * @param {string} label 작업 이름 (예: "표점", "주석")
 * @returns {boolean} 잘림 감지 여부 (호출부에서 추가 처리 판단용)
 */
function notifyLlmTruncation(data, label) {
  if (!data || data._truncated !== true) return false;
  const n = data._recovered_count;
  const countText =
    typeof n === "number" ? `완성된 ${n}개 항목만` : "완성된 항목만";
  if (typeof showToast === "function") {
    showToast(
      `LLM ${label} 응답이 중간에 잘려 ${countText} 복구했습니다 — ` +
        `누락 가능성이 있으니 재실행을 권장합니다.`,
      "warning",
      9000,
    );
  }
  return true;
}
window.notifyLlmTruncation = notifyLlmTruncation;


/**
 * 에디터 진행 바 표시/숨김.
 * OCR의 _showProgress()와 동일한 패턴이지만 prefix로 DOM ID를 구분한다.
 *
 * HTML 요소 규칙:
 *   #{prefix}-progress       — 전체 컨테이너
 *   #{prefix}-progress-text  — 텍스트 표시
 *   #{prefix}-progress-fill  — 채움 바
 *
 * @param {string} prefix   DOM ID 접두사 ("punct", "trans", "ann")
 * @param {boolean} show    표시/숨김
 * @param {string} text     진행 상태 텍스트
 * @param {number} current  현재 진행 (선택)
 * @param {number} total    전체 수 (선택, 0이면 불확정)
 */
function showEditorProgress(prefix, show, text, current, total) {
  const el = document.getElementById(`${prefix}-progress`);
  const textEl = document.getElementById(`${prefix}-progress-text`);
  const fillEl = document.getElementById(`${prefix}-progress-fill`);

  if (el) el.style.display = show ? "" : "none";
  if (textEl) textEl.textContent = text || "";
  if (fillEl) {
    if (total && total > 0) {
      const pct = Math.min(100, Math.round((current / total) * 100));
      fillEl.style.width = pct + "%";
      fillEl.classList.add("ocr-progress-determinate");
      fillEl.classList.remove("ocr-progress-indeterminate");
    } else {
      // 불확정 진행률: 펄스 애니메이션 (OCR과 동일한 CSS 클래스 재사용)
      fillEl.style.width = "100%";
      fillEl.classList.remove("ocr-progress-determinate");
      fillEl.classList.add("ocr-progress-indeterminate");
    }
  }
}
