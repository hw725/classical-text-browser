/**
 * 워크스페이스 레이아웃 인터랙션 — vanilla JS
 *
 * 기능:
 *   1. 사이드바 너비 드래그 조절
 *   2. 에디터 좌우 분할 비율 드래그 조절
 *   3. 액티비티 바 탭 전환
 *   4. API에서 서고 정보 로드
 *   5. PDF 렌더러 초기화 (pdf-renderer.js)
 *   6. 텍스트 에디터 초기화 (text-editor.js)
 *   7. 교정 편집기 초기화 (correction-editor.js)
 *
 * 참고: 예전의 «하단 패널»(높이 드래그 + 접기/펴기)은 사이드바로 옮겨졌다.
 *   관련 DOM(panel-toggle, bottom-panel)이 index.html에서 사라졌으므로
 *   그 코드도 함께 제거했다.
 */

document.addEventListener("DOMContentLoaded", () => {
  _initCollapsibleSidebarSections();
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

  _safeInit("AppVersion", _loadAppVersion);
  _safeInit("ResizeHandlers", initResizeHandlers);
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
  // 드래그 앤 드롭 온보딩 (PDF/이미지 드롭 → 새 문헌)
  if (typeof initDragDrop === "function") _safeInit("DragDrop", initDragDrop);
  // 텍스트 레이어 가져오기 버튼 (프로필에 따라 동작이 갈린다)
  _safeInit("TextLayerImport", initTextLayerImport);
  // 텍스트 추출 패널 (진단 → OCR → 산출물)
  if (typeof initExtractPanel === "function") _safeInit("PaperPanel", initExtractPanel);
  // 작업 프로필 (고서 / 논문) — 고서 전용 탭 표시 여부
  // 프로필 적용이 위 버튼 상태를 갱신하므로 반드시 뒤에 둔다.
  _safeInit("WorkspaceProfile", initWorkspaceProfile);
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

/* ──────────────────────────
   2. 액티비티 바 탭 전환
   ────────────────────────── */

function initActivityBar() {
  const buttons = document.querySelectorAll(".activity-btn");

  // 패널별 사이드바 섹션 매핑
  // explorer: 문헌목록 + 서지정보 + 해석저장소
  // settings: 설정 패널
  // git~notes: 구 하단 패널 탭들 → 사이드바로 이동
  const panelSections = {
    explorer: ["document-list", "bib-section", "interp-section", "contents-section"],
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
            ? "var(--activity-width) 0px 0px 1fr"
            : `var(--activity-width) var(--sidebar-width) 4px 1fr`;
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
          workspace.style.gridTemplateColumns = `var(--activity-width) var(--sidebar-width) 4px 1fr`;
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
        // 해석 저장소는 추출 모드에서 숨긴다(L5~L7을 쓰지 않는다).
        // hidden 속성만으로도 CSS가 막지만, 여기서 style.display를 비우는
        // 코드가 «보이게 하는 의도»로 읽히므로 조건을 명시해 둔다.
        if (
          interpSec &&
          !interpSec.hidden &&
          typeof viewerState !== "undefined" &&
          viewerState.docId
        ) {
          interpSec.style.display = "";
          // 내용 트리(D-085)는 해석 섹션과 같은 조건으로 보인다.
          if (typeof setContentsSectionVisible === "function") setContentsSectionVisible(true);
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

    // LLM 연결 상태 (프로바이더마다 도달·인증을 따로 본다)
    _loadLlmAccounts();
  } catch (e) {
    console.warn("설정 로드 실패:", e);
  }
}

/* ─── LLM 연결 상태 ─────────────────────────────
 *
 * 왜 별도 절인가:
 *   API 키 방식(.env)은 키만 넣으면 되지만, 구독형(Ollama 클라우드·
 *   OpenAI OAuth)은 터미널 로그인이 필요하고 앱이 대신할 수 없다.
 *   더 나쁜 것은 «서버는 떴는데 로그인은 안 된» 상태다 — 가용해 보이지만
 *   클라우드 모델 호출이 실패하고 라우터가 조용히 유료 API로 넘어간다.
 *   그 사실이 화면에 보여야 한다(D-056).
 */

const _LLM_STATUS_LABEL = {
  ready: "연결됨",
  needs_signin: "로그인 필요",
  needs_key: "키 필요",
  offline: "실행 안 됨",
};

async function _loadLlmAccounts() {
  const box = document.getElementById("settings-llm-accounts");
  if (!box) return;

  try {
    const res = await fetch("/api/llm/accounts");
    if (!res.ok) {
      box.innerHTML = '<div class="placeholder">연결 상태를 확인하지 못했습니다.</div>';
      return;
    }
    const data = await res.json();
    const providers = data.providers || [];
    if (!providers.length) {
      box.innerHTML = '<div class="placeholder">등록된 프로바이더가 없습니다.</div>';
      return;
    }

    box.innerHTML = "";
    for (const p of providers) {
      const row = document.createElement("div");
      row.className = `settings-llm-row llm-${p.status}`;

      const head = document.createElement("div");
      head.className = "settings-llm-head";

      const name = document.createElement("span");
      name.className = "settings-llm-name";
      name.textContent = p.display_name;
      head.appendChild(name);

      const badge = document.createElement("span");
      badge.className = `settings-llm-badge llm-badge-${p.status}`;
      badge.textContent = _LLM_STATUS_LABEL[p.status] || p.status;
      head.appendChild(badge);

      // 과금 방식은 늘 보인다. 구독형이 «무료»로 오해되지 않도록.
      const billing = document.createElement("span");
      billing.className = "settings-llm-billing";
      billing.textContent =
        { metered: "종량 과금", subscription: "구독 한도", free: "로컬 무료" }[
          p.billing_model
        ] || p.billing_model;
      head.appendChild(billing);

      row.appendChild(head);

      const note = document.createElement("div");
      note.className = "settings-llm-note";
      // 백엔드가 **강조**를 마크다운처럼 보내므로 그대로 두지 않고 벗긴다.
      note.textContent = (p.note || "").replace(/\*\*/g, "");
      row.appendChild(note);

      // 아직 못 쓰는 프로바이더만 «무엇을 해야 하는가»를 펼쳐 보여 준다.
      if (p.status !== "ready" && (p.setup_steps || []).length) {
        const steps = document.createElement("ol");
        steps.className = "settings-llm-steps";
        for (const s of p.setup_steps) {
          const li = document.createElement("li");
          li.textContent = s;
          steps.appendChild(li);
        }
        row.appendChild(steps);
      }

      box.appendChild(row);
    }
  } catch (e) {
    box.innerHTML = '<div class="placeholder">연결 상태를 확인하지 못했습니다.</div>';
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

  // 터미널에서 로그인한 뒤 앱을 다시 켜지 않아도 되도록 다시 확인을 둔다.
  const refreshLlmBtn = document.getElementById("btn-refresh-llm-accounts");
  if (refreshLlmBtn) {
    refreshLlmBtn.addEventListener("click", () => {
      const box = document.getElementById("settings-llm-accounts");
      if (box) box.innerHTML = '<div class="placeholder">확인 중...</div>';
      _loadLlmAccounts();
    });
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

/* ──────────────────────────
   아이콘 줄 접기/펴기
   ──────────────────────────

   왜 필요한가:
     사이드바는 접을 수 있지만 **왼쪽 아이콘 줄은 접어도 남는다.**
     추출 모드에서는 아이콘이 둘뿐이라(서고 브라우저·설정) 그 줄이
     화면만 차지한다.

   왜 모드 바에 두는가:
     줄을 접으면 그 안의 버튼으로는 되돌릴 수 없다. 되돌릴 수단은
     **줄 밖에, 항상 보이는 자리에** 있어야 한다. 모드 바가 그 자리다.
*/

const RAIL_STORAGE_KEY = "ctb.railHidden";

function _applyRailState(hidden) {
  document.body.dataset.rail = hidden ? "hidden" : "shown";
  const btn = document.getElementById("rail-toggle");
  if (btn) {
    btn.setAttribute("aria-pressed", hidden ? "true" : "false");
    btn.title = hidden ? "왼쪽 아이콘 줄 펴기" : "왼쪽 아이콘 줄 접기";
  }
  // 그리드 폭은 CSS 변수를 따라가지만, 사이드바 접기 코드가 인라인으로
  // 덮어쓴 상태일 수 있다. 그 값을 다시 계산해 준다.
  const workspace = document.querySelector(".workspace");
  const sidebar = document.getElementById("sidebar");
  if (workspace && sidebar) {
    workspace.style.gridTemplateColumns = sidebar.classList.contains("collapsed")
      ? "var(--activity-width) 0px 0px 1fr"
      : "var(--activity-width) var(--sidebar-width) 4px 1fr";
  }
}

function initRailToggle() {
  const btn = document.getElementById("rail-toggle");
  if (!btn) return;

  let hidden = false;
  try {
    hidden = localStorage.getItem(RAIL_STORAGE_KEY) === "1";
  } catch (e) {
    hidden = false;
  }
  _applyRailState(hidden);

  btn.addEventListener("click", () => {
    const next = document.body.dataset.rail !== "hidden";
    _applyRailState(next);
    try {
      localStorage.setItem(RAIL_STORAGE_KEY, next ? "1" : "0");
    } catch (e) {
      // 저장 실패해도 이번 세션에서는 동작한다.
    }

    // 펼 때는 서고 브라우저로 맞춘다.
    //
    // 왜: 줄을 펴는 행동은 대개 «문헌을 보러 간다»는 뜻이다. 설정은
    // 어쩌다 한 번 쓴다. 접기 직전에 설정을 보고 있었다는 이유로 다시
    // 설정이 열리면 한 번 더 눌러야 한다.
    if (!next) {
      const explorer = document.querySelector('.activity-btn[data-panel="explorer"]');
      if (explorer && !explorer.classList.contains("active")) explorer.click();
    }

    if (typeof _autoFit === "function") setTimeout(() => _autoFit(), 50);
  });
}

function initModeBar() {
  initRailToggle();

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

/* ──────────────────────────
   1-b. 작업 프로필 (고서 / 논문)
   ──────────────────────────

   왜 필요한가:
     이 앱은 고서(古書)를 읽기 위해 만들어졌고, 상단 탭 10개가 그 작업
     순서를 그대로 드러낸다. 그런데 근현대 논문 스캔본에서 텍스트만
     뽑으려는 경우 표점·현토·이체자·편성은 쓸 일이 없다.
     (한문 독법 표기·이체자 판별은 근현대 활자본에 해당하지 않는다.)

   무엇을 바꾸지 않는가:
     숨기는 것은 **탭의 표시뿐**이다. 모드 전환 함수(_switchMode)도,
     각 패널도, 저장되는 데이터도 건드리지 않는다. 프로필을 되돌리면
     그대로 돌아온다. 문헌 파일에는 아무것도 기록하지 않는다
     (manifest 스키마는 additionalProperties:false라 손대면 파급이 크다).

   왜 localStorage인가:
     문헌마다 기억해야 쓸모가 있는데(한 서고에 고서와 논문이 섞인다),
     서버 설정에는 UI 토글을 담는 키가 없고 새로 만들면 스키마·스냅샷에
     파급이 생긴다. 테마 스위처(index.html)가 이미 쓰는 방식이기도 하다. */

const WORKSPACE_PROFILES = { collation: "교감", extract: "추출" };
const PROFILE_STORAGE_PREFIX = "ctb.profile.";
let currentProfile = "collation";

/**
 * 문헌에 저장된 작업 프로필을 읽는다.
 *
 * 입력: docId — 문헌 ID (없으면 전역 기본값을 본다)
 * 출력: "collation" 또는 "extract"
 */
function getWorkspaceProfile(docId) {
  try {
    const key = PROFILE_STORAGE_PREFIX + (docId || "_default");
    const saved = localStorage.getItem(key);
    if (saved && WORKSPACE_PROFILES[saved]) return saved;
  } catch (e) {
    // localStorage가 막힌 환경(사생활 보호 모드 등)에서도 앱은 동작해야 한다.
    console.warn("[Profile] 저장된 프로필을 읽지 못했습니다:", e);
  }
  return "collation";
}

/**
 * 문헌의 작업 프로필을 저장한다.
 *
 * 입력: docId — 문헌 ID (없으면 전역 기본값으로 저장)
 *       profile — "collation" 또는 "extract"
 */
function saveWorkspaceProfile(docId, profile) {
  try {
    localStorage.setItem(PROFILE_STORAGE_PREFIX + (docId || "_default"), profile);
  } catch (e) {
    console.warn("[Profile] 프로필을 저장하지 못했습니다:", e);
  }
}

/**
 * 작업 프로필을 화면에 적용한다.
 *
 * 입력: profile — "collation"(고서, 전체 탭) 또는 "extract"(논문, 고서 전용 탭 숨김)
 * 출력: 없음.
 *
 * 왜 hidden 속성인가: CSS 클래스를 새로 만들지 않아도 되고,
 * 스크린 리더도 숨겨진 탭을 읽지 않는다.
 */
function applyWorkspaceProfile(profile) {
  if (!WORKSPACE_PROFILES[profile]) profile = "collation";
  currentProfile = profile;
  const isExtractMode = profile === "extract";

  document.querySelectorAll('[data-profile="collation"]').forEach((el) => {
    el.hidden = isExtractMode;
  });

  // 지금 보고 있는 탭이 숨겨졌다면 열람으로 되돌린다.
  // (제거된 interpretation 모드를 view로 폴백시키는 기존 방식과 같다.)
  const activeTab = document.querySelector(".mode-tab.active");
  if (activeTab && activeTab.hidden) {
    document.querySelectorAll(".mode-tab").forEach((t) => {
      t.classList.remove("active");
      t.setAttribute("aria-selected", "false");
    });
    const viewTab = document.querySelector('.mode-tab[data-mode="view"]');
    if (viewTab) {
      viewTab.classList.add("active");
      viewTab.setAttribute("aria-selected", "true");
    }
    _switchMode("view");
  }

  // 사이드바도 마찬가지다. 해석 저장소 전용 패널(검증·의존·엔티티·비고·
  // 인용 양식)을 보고 있는데 그 버튼이 숨겨지면, **볼 수는 있는데 돌아올
  // 방법이 없는** 화면에 갇힌다. 서고 브라우저로 되돌린다.
  const activeActivity = document.querySelector(".activity-btn.active");
  if (activeActivity && activeActivity.hidden) {
    const explorer = document.querySelector('.activity-btn[data-panel="explorer"]');
    if (explorer) explorer.click();
  }

  // 지금 어느 모드인지가 한눈에 보여야 한다.
  // 탭 몇 개가 사라지는 것만으로는 신호가 약하다.
  //
  // 세 곳에 동시에 표시한다:
  //   1) body 속성 — 화면 전체의 색조를 바꿀 수 있게 (CSS가 받는다)
  //   2) 배지 — 현재 상태를 글자로
  //   3) 버튼 — 누르면 어디로 가는지
  document.body.dataset.workspaceProfile = profile;

  const badge = document.getElementById("profile-badge");
  if (badge) {
    badge.textContent = `${WORKSPACE_PROFILES[profile]} 모드`;
    badge.classList.toggle("profile-badge-extract", isExtractMode);
  }

  const toggle = document.getElementById("profile-toggle");
  if (toggle) {
    const next = isExtractMode ? "collation" : "extract";
    toggle.textContent = `${WORKSPACE_PROFILES[next]} 모드로 →`;
    toggle.setAttribute("aria-pressed", isExtractMode ? "true" : "false");
    toggle.classList.toggle("profile-extract", isExtractMode);
  }

  _updateTextLayerImportButton(isExtractMode);

  // 텍스트 추출 패널은 「논문」 프로필에서만 보인다.
  const extractPanel = document.getElementById("extract-panel");
  if (extractPanel) {
    extractPanel.hidden = !isExtractMode;
    if (isExtractMode && typeof refreshExtractPanel === "function") {
      refreshExtractPanel(true);
    }
  }
}

/**
 * 사이드바 "가져오기" 버튼의 상태를 프로필에 맞춘다.
 *
 * 입력: enabled — 추출 모드이면 true.
 *
 * 왜 프로필로 가르는가: 이 버튼은 D-037로 봉인돼 있다
 * (HWP/PDF 가져오기가 아직 안정적이지 않다는 판단). 그 판단을 뒤집지 않고,
 * 추출 모드에서만 **다른 동작** — PDF 텍스트 레이어를 그대로 L4로
 * 옮기는 단순 경로 — 에 연결한다. hwp-import 다이얼로그는 여전히 봉인이다.
 */
function _updateTextLayerImportButton(enabled) {
  const btn = document.getElementById("import-hwp-btn");
  if (!btn) return;
  if (enabled) {
    btn.title = "PDF 텍스트 레이어에서 본문 가져오기 (OCR 없음)";
    btn.style.opacity = "";
    btn.style.cursor = "pointer";
  } else {
    btn.title = "HWP/HWPX/PDF 가져오기 (준비중)";
    btn.style.opacity = "0.5";
    btn.style.cursor = "default";
  }
}

/**
 * "가져오기" 버튼 동작을 등록한다.
 *
 * 교감 모드: 기존과 같이 "준비중" 안내 (D-037).
 * 추출 모드: 열린 문헌의 PDF 텍스트 레이어를 L4 텍스트로 가져온다.
 */
function initTextLayerImport() {
  const btn = document.getElementById("import-hwp-btn");
  if (!btn) return;

  btn.addEventListener("click", async () => {
    if (currentProfile !== "extract") {
      showToast("HWP/HWPX/PDF 가져오기 기능은 현재 준비중입니다.", "info");
      return;
    }
    const docId = viewerState && viewerState.docId;
    const partId = viewerState && viewerState.partId;
    if (!docId || !partId) {
      showToast("먼저 문헌의 페이지를 여세요.", "info");
      return;
    }

    btn.disabled = true;
    try {
      const res = await fetch(
        `/api/documents/${docId}/parts/${partId}/text-import/from-text-layer`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        }
      );
      const data = await res.json();
      if (!res.ok) {
        showToast(data.error || "가져오기에 실패했습니다.", "error");
        return;
      }
      if (data.imported > 0) {
        showToast(
          `${data.imported}쪽을 가져왔습니다 (OCR 없이 원본 활자 그대로).`,
          "success"
        );
        // 지금 보고 있는 쪽의 텍스트를 다시 읽어 화면에 반영한다.
        if (typeof loadPageText === "function") {
          loadPageText(docId, partId, viewerState.pageNum);
        }
      } else {
        showToast(
          (data.warnings && data.warnings[0]) || "가져올 텍스트가 없습니다.",
          "info"
        );
      }
    } catch (e) {
      showToast(`가져오기 중 오류가 발생했습니다: ${e.message}`, "error");
    } finally {
      btn.disabled = false;
    }
  });
}

/**
 * 현재 열린 문헌에 맞는 프로필을 적용한다.
 *
 * 입력: docId — 문헌 ID.
 * 왜 필요한가: 한 서고에 고서와 논문이 섞여 있으므로,
 * 문헌을 바꿀 때마다 그 문헌에 맞는 프로필로 따라가야 한다.
 */
function applyProfileForDocument(docId) {
  applyWorkspaceProfile(getWorkspaceProfile(docId));
}

/**
 * 프로필 전환 버튼을 초기화한다.
 */
function initWorkspaceProfile() {
  const toggle = document.getElementById("profile-toggle");
  if (toggle) {
    toggle.addEventListener("click", async () => {
      const next = currentProfile === "collation" ? "extract" : "collation";
      const docId =
        typeof viewerState !== "undefined" && viewerState ? viewerState.docId : null;
      saveWorkspaceProfile(docId, next);
      applyWorkspaceProfile(next);
      if (typeof showToast === "function") {
        showToast(
          next === "extract"
            ? "추출 모드 — 열람·레이아웃·교정만 남겼습니다."
            : "교감 모드 — 모든 작업 탭을 표시합니다.",
          "info"
        );
      }
      // 추출 모드에서는 L5-L7을 쓰지 않는다. 이 문헌에 딸린 해석 저장소가
      // 비어 있으면 정리해 목록이 잡동사니로 차지 않게 한다.
      if (next === "extract" && docId) {
        await _discardEmptyInterpretations(docId);
      }
    });
  }
  // 첫 진입에는 아직 문헌이 없으므로 전역 기본값을 쓴다.
  applyWorkspaceProfile(getWorkspaceProfile(null));
}

/**
 * 이 문헌의 비어 있는 해석 저장소를 휴지통으로 옮긴다.
 *
 * 입력: docId — 문헌 ID.
 *
 * 왜 «비어 있는» 것만인가: 모드 전환은 표시를 바꾸는 일이지 데이터를
 * 지우는 일이 아니다. 번역이나 주석이 하나라도 있으면 서버가 지키고
 * 그 사실을 돌려준다. 옮긴 것도 삭제가 아니라 휴지통이라 되돌릴 수 있다.
 */
async function _discardEmptyInterpretations(docId) {
  try {
    const res = await fetch(
      `/api/documents/${docId}/interpretations/discard-empty`,
      { method: "POST", headers: { "Content-Type": "application/json" } }
    );
    if (!res.ok) return;
    const data = await res.json();
    if (data.discarded && data.discarded.length && typeof showToast === "function") {
      showToast(
        `쓰지 않는 해석 저장소 ${data.discarded.length}개를 휴지통으로 옮겼습니다. ` +
          "(설정 → 휴지통에서 복원할 수 있습니다)",
        "info"
      );
      if (typeof loadLibraryInfo === "function") loadLibraryInfo();
    } else if (data.kept && data.kept.length && typeof showToast === "function") {
      showToast(
        `해석 저장소에 작업 내용이 있어 그대로 두었습니다 ` +
          `(${data.kept.length}개).`,
        "info"
      );
    }
  } catch (e) {
    // 정리는 편의 기능이다. 실패해도 모드 전환은 이미 끝났다.
    console.warn("[Profile] 빈 해석 저장소 정리 실패:", e);
  }
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

async function loadLibraryInfo(options) {
  // restoreHash: false면 URL 해시 기반 열람 위치 복원을 건너뛴다.
  // 문헌 생성 직후의 사이드바 갱신(create-document.js)처럼 "목록만 새로
  // 그리고 싶은" 호출자가 쓴다 — 복원까지 하면 보던 화면이 다시 로드된다.
  const restoreHash = options?.restoreHash !== false;
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
      // 서고가 정해졌으니 OCR 엔진 목록을 (다시) 불러온다. 화면이 서고보다 먼저
      // 열리면 첫 호출이 500으로 끝나 드롭다운이 «로딩 중»에 멈춰 있었다.
      if (typeof refreshOcrEngines === "function") refreshOcrEngines();
      // 내용 트리 새로고침 단추 (D-085). 한 번만 바인딩한다.
      const contentsBtn = document.getElementById("contents-refresh-btn");
      if (contentsBtn && !contentsBtn.dataset.bound) {
        contentsBtn.dataset.bound = "1";
        contentsBtn.addEventListener("click", () => {
          if (typeof refreshContentsTree === "function") refreshContentsTree();
        });
      }
    } else {
      renderDocumentList(docs);
    }

    // 서고는 있지만 문헌이 하나도 없을 때 — 드래그 앤 드롭 시작 안내.
    // 왜: 첫 사용자가 "+ 새 문헌"을 찾기 전에 가장 빠른 길을 먼저 보여준다.
    if (docs.length === 0) {
      const docList = document.getElementById("document-list");
      if (docList) {
        docList.insertAdjacentHTML(
          "beforeend",
          '<div class="drop-hint">PDF나 이미지 파일(폴더)을<br />' +
            "이 창 안 어디에든 끌어다 놓으면<br />바로 문헌으로 등록됩니다.</div>",
        );
      }
    }

    // URL 해시에서 열람 위치 복원 (Plan 4)
    if (restoreHash) _restoreFromHash();
  } catch (err) {
    // 서고 미설정 또는 API 연결 실패 — 서고 선택 안내를 표시
    const docList = document.getElementById("document-list");
    docList.innerHTML =
      '<div class="placeholder no-library-guide">' +
      '  <p>서고가 연결되지 않았습니다.</p>' +
      '  <button class="btn-sm btn-primary" id="btn-goto-settings">서고 설정 열기</button>' +
      '  <div class="drop-hint">또는 PDF·이미지를 이 창에 끌어다 놓으세요.<br />' +
      "기본 서고를 자동으로 만들어 바로 시작합니다.</div>" +
      "</div>";
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
  // 내용 트리: 이 쪽에 있는 블록 표시 (D-085)
  if (typeof highlightContentsForPage === "function") highlightContentsForPage(pageNum);

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
    // <option> 안에는 SVG를 넣을 수 없다 — 이모지(👁)는 OS 폰트에 따라
    // 렌더링이 크게 달라 텍스트 라벨로 표기한다.
    const visionLabel = m.vision ? " [비전]" : "";
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
    // 컨테이너가 떴는지 **누르기 전에** 알려 준다.
    //
    // 왜: 표점 서비스는 Docker 컨테이너라 앱보다 늦게 올라온다.
    // 준비되기 전에 누르면 오류만 보이고 왜 그런지 알 수 없다. 누르기 전에
    // 알려 주는 것이 `/api/llm/punctuation/external/health`의 목적이다.
    _annotateExternalPunctStatus(opt);
  }
}

/**
 * 외부 표점 서비스 상태를 선택지 라벨에 붙인다.
 *
 * 입력: 그 서비스의 `<option>` 요소.
 *
 * 컨테이너가 아직 올라오는 중이면 몇 초 간격으로 다시 확인한다 —
 * 앱을 열어 둔 채 기다리면 라벨이 스스로 「준비됨」으로 바뀐다.
 */
function _annotateExternalPunctStatus(opt) {
  const BASE = "● 외부 표점 서비스 (SikuRoBERTa, 양정현 2025)";
  let tries = 0;

  const check = async () => {
    tries += 1;
    let h = null;
    try {
      const res = await fetch("/api/llm/punctuation/external/health");
      h = await res.json();
    } catch {
      // 상태 확인 자체가 실패하면 라벨을 건드리지 않는다.
      return;
    }
    if (!opt.isConnected) return; // 드롭다운이 다시 그려졌다

    if (!h.configured) {
      opt.textContent = `${BASE} — 설정 안 됨`;
      opt.disabled = true;
      opt.title = "punctuation-service/.env에 PUNCT_MODEL_HOST_PATH를 적어야 합니다.";
      return;
    }
    if (h.reachable) {
      opt.textContent = `${BASE} — 준비됨`;
      opt.disabled = false;
      return;
    }

    opt.textContent = `${BASE} — 시작 중…`;
    // 컨테이너 기동은 보통 10~30초다. 2초 간격으로 30번(약 1분)까지 지켜본다.
    if (tries < 30) setTimeout(check, 2000);
    else opt.textContent = `${BASE} — 응답 없음`;
  };

  check();
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
    if (typeof setContentsSectionVisible === "function") setContentsSectionVisible(true);

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
/**
 * 화면 아래 상태바의 버전을 서버에서 읽어 채운다.
 *
 * 왜 하드코딩하지 않는가: 버전을 여러 곳에 적으면 릴리스 때 일부만 고쳐져
 * 화면이 옛 버전을 말하게 된다. 정본은 `pyproject.toml` 하나이고,
 * 화면은 서버(`/api/app/version`)에서 받는다.
 */
async function _loadAppVersion() {
  const el = document.getElementById("app-version");
  if (!el) return;
  try {
    const res = await fetch("/api/app/version");
    const data = await res.json();
    el.textContent = data.version ? `v${data.version}` : "";
  } catch {
    // 버전을 못 읽어도 화면은 정상 동작해야 한다 — 비워 둔다.
    el.textContent = "";
  }
}

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


/**
 * 사이드바 섹션 머리를 누르면 접고 펼친다. 접힘 상태는 localStorage에 남는다.
 * 서지사항은 기본으로 접는다(사용자 요청 2026-09-03 — 늘 펼쳐져 있어 화면을 차지했다).
 * 머리 안의 단추·링크(section-header-actions)는 눌러도 접히지 않는다.
 */
function _initCollapsibleSidebarSections() {
  const DEFAULT_COLLAPSED = new Set(["bib-section"]);
  document.querySelectorAll(".sidebar-section").forEach((section) => {
    const header = section.querySelector(":scope > .section-header");
    if (!header || !section.id) return;
    const key = `sidebar.collapsed.${section.id}`;
    let collapsed;
    try {
      const saved = localStorage.getItem(key);
      collapsed = saved === null ? DEFAULT_COLLAPSED.has(section.id) : saved === "1";
    } catch {
      collapsed = DEFAULT_COLLAPSED.has(section.id);
    }
    section.classList.toggle("collapsed", collapsed);
    header.classList.add("collapsible");
    header.title = "누르면 접기/펼치기";
    header.addEventListener("click", (ev) => {
      if (ev.target.closest(".section-header-actions, button, a, select, input")) return;
      const now = !section.classList.contains("collapsed");
      section.classList.toggle("collapsed", now);
      try {
        localStorage.setItem(key, now ? "1" : "0");
      } catch {
        /* 저장 못 해도 동작에는 지장 없음 */
      }
    });
  });
}
