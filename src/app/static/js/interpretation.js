/**
 * 해석 저장소 뷰어/편집기 — vanilla JS
 *
 * 기능:
 *   1. 해석 저장소 목록 로드 (사이드바)
 *   2. 해석 저장소 생성 다이얼로그
 *   3. 의존 변경 확인 + 경고 배너
 *   4. 층별(L5/L6/L7) 내용 조회/편집/저장
 *   5. 하단 패널 의존 추적 렌더링
 *
 * 의존성: viewerState (sidebar-tree.js), _loadGitLog (correction-editor.js)
 *
 * 왜 이렇게 하는가:
 *   correction-editor.js 패턴을 따라 독립 모듈로 구성한다.
 *   해석 모드에서만 활성화되며, 모드 전환 시 activate/deactivate로 제어한다.
 */

/* ──────────────────────────
   상태 객체
   ────────────────────────── */

// eslint-disable-next-line no-unused-vars
const interpState = {
  active: false, // 해석 모드 활성화 여부
  interpId: null, // 선택된 해석 저장소 ID
  interpInfo: null, // manifest 캐시
  depStatus: null, // 의존 변경 확인 결과
  currentLayer: "L5_reading", // 현재 층
  currentSubType: "main_text", // main_text | annotation
  isDirty: false, // 편집 변경 여부
  interpretations: [], // 전체 목록 캐시
};

// eslint-disable-next-line no-unused-vars
const compareState = {
  active: false, // 비교 모드 활성 여부
  repoIdA: null, // 좌측 해석 저장소 ID
  repoIdB: null, // 우측 해석 저장소 ID
  contentA: "", // 좌측 텍스트 내용
  contentB: "", // 우측 텍스트 내용
};

/* ──────────────────────────
   초기화
   ────────────────────────── */

/**
 * 해석 모듈을 초기화한다.
 * DOMContentLoaded에서 workspace.js가 호출한다.
 */
// eslint-disable-next-line no-unused-vars
function initInterpretation() {
  // 생성 다이얼로그
  const createBtn = document.getElementById("interp-create-btn");
  if (createBtn) createBtn.addEventListener("click", _openCreateDialog);

  const importFolderBtn = document.getElementById("interp-import-folder-btn");
  if (importFolderBtn) {
    importFolderBtn.addEventListener("click", _importInterpretationFolder);
  }

  const dialogClose = document.getElementById("interp-dialog-close");
  if (dialogClose) dialogClose.addEventListener("click", _closeCreateDialog);

  const dialogOverlay = document.getElementById("interp-dialog-overlay");
  if (dialogOverlay)
    dialogOverlay.addEventListener("click", (e) => {
      if (e.target === dialogOverlay) _closeCreateDialog();
    });

  const createSaveBtn = document.getElementById("interp-create-save-btn");
  if (createSaveBtn)
    createSaveBtn.addEventListener("click", _createInterpretation);

  // 층별 서브탭
  document.querySelectorAll(".interp-subtab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const layer = tab.dataset.layer;
      if (layer === interpState.currentLayer) return;

      document
        .querySelectorAll(".interp-subtab")
        .forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      interpState.currentLayer = layer;

      // L7_annotation은 sub_type 토글 숨김
      const subtypeBar = document.getElementById("interp-subtype-bar");
      if (subtypeBar) {
        subtypeBar.style.display = layer === "L7_annotation" ? "none" : "";
      }

      _loadLayerContent();
      if (compareState.active) _loadCompareContent();
    });
  });

  // main_text / annotation 라디오
  document.querySelectorAll('input[name="interp-subtype"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      interpState.currentSubType = radio.value;
      _loadLayerContent();
      if (compareState.active) _loadCompareContent();
    });
  });

  // 저장 버튼
  const saveBtn = document.getElementById("interp-save");
  if (saveBtn) saveBtn.addEventListener("click", _saveLayerContent);

  // Ctrl+S 단축키 (해석 패널 안에서만)
  const content = document.getElementById("interp-content");
  if (content) {
    content.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        _saveLayerContent();
      }
    });
    content.addEventListener("input", () => {
      interpState.isDirty = true;
      _updateSaveStatus("modified");
    });
  }

  // 의존 배너 버튼
  const depDiff = document.getElementById("interp-dep-diff");
  if (depDiff) depDiff.addEventListener("click", _showDepInPanel);

  const depAck = document.getElementById("interp-dep-ack");
  if (depAck) depAck.addEventListener("click", _acknowledgeChanges);

  const depUpdate = document.getElementById("interp-dep-update");
  if (depUpdate) depUpdate.addEventListener("click", _updateBase);

  // 비교 모드 토글
  const compareCheckbox = document.getElementById("compare-mode-checkbox");
  if (compareCheckbox) {
    compareCheckbox.addEventListener("change", () => {
      _toggleCompareMode(compareCheckbox.checked);
    });
  }

  // 비교 저장소 선택 드롭다운
  const compareRepoA = document.getElementById("compare-repo-a");
  const compareRepoB = document.getElementById("compare-repo-b");
  if (compareRepoA) {
    compareRepoA.addEventListener("change", () => {
      compareState.repoIdA = compareRepoA.value || null;
      _loadCompareContent();
    });
  }
  if (compareRepoB) {
    compareRepoB.addEventListener("change", () => {
      compareState.repoIdB = compareRepoB.value || null;
      _loadCompareContent();
    });
  }
}

/**
 * 기존 해석 저장소 폴더를 가져온다.
 *
 * 왜 이렇게 하는가:
 *   JSON 스냅샷 export/import 없이, 이미 존재하는 해석 저장소 디렉토리를
 *   그대로 현재 서고의 interpretations/ 하위로 복사 등록하기 위함이다.
 *
 * 동작:
 *   1) 폴더 선택(디렉토리 업로드)
 *   2) multipart/form-data로 파일 전송
 *   3) 서버가 manifest 검사 후 새 해석 저장소로 생성
 */
async function _importInterpretationFolder() {
  const input = document.createElement("input");
  input.type = "file";
  input.multiple = true;
  input.setAttribute("webkitdirectory", "");
  input.setAttribute("directory", "");
  input.style.display = "none";

  input.addEventListener("change", async () => {
    const files = Array.from(input.files || []);
    if (files.length === 0) {
      input.remove();
      return;
    }

    const btn = document.getElementById("interp-import-folder-btn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "가져오는 중…";
    }

    try {
      const form = new FormData();
      files.forEach((file) => {
        const relativePath = file.webkitRelativePath || file.name;
        form.append("files", file, relativePath);
      });

      const res = await fetch("/api/import/interpretation-folder", {
        method: "POST",
        body: form,
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data.error || `서버 오류: ${res.status}`);
      }

      showToast(
        `가져오기 완료! 해석 ID: ${data.interp_id}, ` +
          `문헌 ID: ${data.source_document_id}, ` +
          `파일 수: ${data.file_count}` +
          (data.skipped_count ? `, 제외 파일 수: ${data.skipped_count}` : ""),
        'success');

      await _loadInterpretationList();
      if (typeof loadLibraryInfo === "function") {
        loadLibraryInfo();
      }
    } catch (err) {
      showToast(`폴더 가져오기 실패: ${err.message}`, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "폴더 가져오기";
      }
      input.remove();
    }
  });

  document.body.appendChild(input);
  input.click();
}

/* ──────────────────────────
   모드 활성화 / 비활성화
   ────────────────────────── */

/**
 * 해석 모드를 활성화한다.
 * workspace.js의 _switchMode()에서 호출된다.
 */
// eslint-disable-next-line no-unused-vars
function activateInterpretationMode() {
  interpState.active = true;

  // 사이드바 해석 섹션 표시
  const section = document.getElementById("interp-section");
  if (section) section.style.display = "";

  // 해석 저장소 목록 로드
  _loadInterpretationList();
}

/**
 * 해석 모드를 비활성화한다.
 */
// eslint-disable-next-line no-unused-vars
function deactivateInterpretationMode() {
  interpState.active = false;

  // 비교 모드 해제
  const checkbox = document.getElementById("compare-mode-checkbox");
  if (checkbox && checkbox.checked) {
    checkbox.checked = false;
    _toggleCompareMode(false);
  }

  // 사이드바 해석 섹션 숨김
  const section = document.getElementById("interp-section");
  if (section) section.style.display = "none";

  // 의존 배너 숨김
  _hideDepBanner();
}

/* ──────────────────────────
   해석 저장소 목록
   ────────────────────────── */

async function _loadInterpretationList() {
  const container = document.getElementById("interp-list");
  if (!container) return;

  try {
    const res = await fetch("/api/interpretations");
    if (!res.ok) throw new Error("해석 저장소 목록 API 오류");
    const list = await res.json();
    interpState.interpretations = list;

    if (list.length === 0) {
      container.innerHTML =
        '<div class="placeholder">등록된 해석 저장소가 없습니다</div>';
      return;
    }

    container.innerHTML = list
      .map((item) => {
        const typeClass = `type-${item.interpreter?.type || "human"}`;
        const typeLabel = item.interpreter?.type || "human";
        return `
        <div class="interp-list-item" data-interp-id="${item.interpretation_id}">
          <span class="interp-type-badge ${typeClass}">${typeLabel}</span>
          <span class="interp-list-title">${item.title || item.interpretation_id}</span>
          <span class="interp-list-source">${item.source_document_id}</span>
          <button class="interp-delete-btn" title="해석 저장소 삭제 (휴지통 이동)">×</button>
        </div>
      `;
      })
      .join("");

    // 클릭 이벤트
    container.querySelectorAll(".interp-list-item").forEach((el) => {
      el.addEventListener("click", (e) => {
        // 삭제 버튼 클릭은 무시 (삭제 버튼에 자체 핸들러가 있음)
        if (e.target.classList.contains("interp-delete-btn")) return;
        _selectInterpretation(el.dataset.interpId);
        // 하이라이트
        container
          .querySelectorAll(".interp-list-item")
          .forEach((i) => i.classList.remove("active"));
        el.classList.add("active");
      });

      // 삭제 버튼 이벤트
      const delBtn = el.querySelector(".interp-delete-btn");
      if (delBtn) {
        delBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          const interpId = el.dataset.interpId;
          const title =
            el.querySelector(".interp-list-title")?.textContent || interpId;
          _trashInterpretation(interpId, title);
        });
      }
    });
  } catch (err) {
    console.error("해석 저장소 목록 로드 실패:", err);
    container.innerHTML =
      '<div class="placeholder">목록을 불러올 수 없습니다</div>';
  }
}

/**
 * 해석 저장소를 휴지통으로 이동한다.
 *
 * 왜 이렇게 하는가:
 *   - 영구 삭제 대신 서고 내 .trash/ 폴더로 이동하여 복원 가능하게 한다.
 */
async function _trashInterpretation(interpId, interpTitle) {
  if (!confirm(`"${interpTitle}" 해석 저장소를 삭제(휴지통 이동)하시겠습니까?`))
    return;

  try {
    const res = await fetch(`/api/interpretations/${interpId}`, {
      method: "DELETE",
    });
    const data = await res.json();

    if (!res.ok) {
      showToast(`삭제 실패: ${data.error || "알 수 없는 오류"}`, 'error');
      return;
    }

    // 현재 선택된 해석 저장소가 삭제된 경우 상태 초기화
    if (interpState.interpId === interpId) {
      interpState.interpId = null;
      interpState.interpInfo = null;
    }

    // 목록 + 서고 설정 패널 새로고침
    _loadInterpretationList();
    if (typeof _loadSettings === "function") {
      _loadSettings();
    }
  } catch (err) {
    showToast(`삭제 중 오류: ${err.message}`, 'error');
  }
}

/* ──────────────────────────
   해석 저장소 선택
   ────────────────────────── */

async function _selectInterpretation(interpId) {
  interpState.interpId = interpId;

  // manifest 로드
  try {
    const res = await fetch(`/api/interpretations/${interpId}`);
    if (!res.ok) throw new Error("해석 저장소 상세 API 오류");
    interpState.interpInfo = await res.json();
  } catch (err) {
    console.error("해석 저장소 상세 로드 실패:", err);
    return;
  }

  // 의존 변경 확인
  await _checkDependency();

  // Phase 12-1: Git 그래프에 현재 해석 저장소 ID 전달
  if (typeof setGitGraphInterpId === "function") setGitGraphInterpId(interpId);

  // 내용 로드 (viewerState에 페이지가 있으면)
  _loadLayerContent();
}

/* ──────────────────────────
   의존 변경 확인
   ────────────────────────── */

async function _checkDependency() {
  if (!interpState.interpId) return;

  try {
    const res = await fetch(
      `/api/interpretations/${interpState.interpId}/dependency`,
    );
    if (!res.ok) throw new Error("의존 확인 API 오류");
    const dep = await res.json();
    interpState.depStatus = dep;

    if (dep.dependency_status === "current") {
      _hideDepBanner();
    } else {
      _showDepBanner(dep);
    }

    // 하단 패널 의존 추적 렌더링
    _renderDepPanel(dep);
  } catch (err) {
    console.error("의존 변경 확인 실패:", err);
  }
}

function _showDepBanner(dep) {
  const banner = document.getElementById("interp-dep-banner");
  const msg = document.getElementById("interp-dep-msg");
  if (!banner || !msg) return;

  const statusLabels = {
    outdated: "원본이 변경되었습니다",
    partially_acknowledged: "일부 변경을 인지했습니다",
    acknowledged: "모든 변경을 인지했습니다",
  };

  msg.textContent = `${statusLabels[dep.dependency_status] || dep.dependency_status} (변경 ${dep.changed_count}건)`;
  banner.style.display = "";
}

function _hideDepBanner() {
  const banner = document.getElementById("interp-dep-banner");
  if (banner) banner.style.display = "none";
}

/* ──────────────────────────
   의존 배너 액션
   ────────────────────────── */

function _showDepInPanel() {
  // 액티비티 바의 "의존 추적" 버튼을 클릭하여 사이드바 패널을 전환
  const depBtn = document.querySelector('.activity-btn[data-panel="dependency"]');
  if (depBtn) depBtn.click();
}

async function _acknowledgeChanges() {
  if (!interpState.interpId) return;

  try {
    const res = await fetch(
      `/api/interpretations/${interpState.interpId}/dependency/acknowledge`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_paths: null }),
      },
    );
    if (!res.ok) throw new Error("인지 API 오류");
    const result = await res.json();
    console.log("변경 인지 완료:", result);

    // 재확인
    await _checkDependency();
  } catch (err) {
    console.error("변경 인지 실패:", err);
  }
}

async function _updateBase() {
  if (!interpState.interpId) return;

  try {
    const res = await fetch(
      `/api/interpretations/${interpState.interpId}/dependency/update-base`,
      {
        method: "POST",
      },
    );
    if (!res.ok) throw new Error("기반 업데이트 API 오류");
    const result = await res.json();
    console.log("기반 업데이트 완료:", result);

    // 재확인
    await _checkDependency();
  } catch (err) {
    console.error("기반 업데이트 실패:", err);
  }
}

/* ──────────────────────────
   하단 패널 의존 추적 렌더링
   ────────────────────────── */

function _renderDepPanel(dep) {
  const summary = document.getElementById("dep-status-summary");
  const fileList = document.getElementById("dep-file-list");
  if (!summary || !fileList) return;

  // 상태 뱃지
  const badgeClass =
    {
      current: "status-current",
      outdated: "status-outdated",
      acknowledged: "status-acknowledged",
      partially_acknowledged: "status-partially",
    }[dep.dependency_status] || "status-outdated";

  summary.innerHTML = `
    <span class="dep-status-badge ${badgeClass}">${dep.dependency_status}</span>
    &nbsp; base: <code>${(dep.base_commit || "").substring(0, 7)}</code>
    &nbsp; source HEAD: <code>${(dep.source_head_commit || "").substring(0, 7)}</code>
    &nbsp; tracked: ${(dep.tracked_files || []).length}
    &nbsp; changed: ${dep.changed_count || 0}
  `;

  // 파일 목록
  const files = dep.tracked_files || [];
  if (files.length === 0) {
    fileList.innerHTML = '<div class="placeholder">추적 파일 없음</div>';
    return;
  }

  fileList.innerHTML = files
    .map((tf) => {
      const stClass = `st-${tf.status}`;
      return `
      <div class="dep-file-item">
        <span class="dep-file-status ${stClass}">${tf.status}</span>
        <span class="dep-file-path">${tf.path}</span>
      </div>
    `;
    })
    .join("");
}

/* ──────────────────────────
   층 내용 로드 / 저장
   ────────────────────────── */

async function _loadLayerContent() {
  if (!interpState.interpId || !viewerState.partId || !viewerState.pageNum) {
    _updateFileInfo("");
    return;
  }

  const { interpId, currentLayer, currentSubType } = interpState;
  const { partId, pageNum } = viewerState;

  const url = `/api/interpretations/${interpId}/layers/${currentLayer}/${currentSubType}/pages/${pageNum}?part_id=${partId}`;

  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error("층 내용 API 오류");
    const data = await res.json();

    const content = document.getElementById("interp-content");
    if (content) {
      // L6은 텍스트, L5/L7은 JSON → 텍스트로 표시
      if (typeof data.content === "string") {
        content.value = data.content;
      } else if (
        typeof data.content === "object" &&
        data.content !== null &&
        Object.keys(data.content).length > 0
      ) {
        content.value = JSON.stringify(data.content, null, 2);
      } else {
        content.value = "";
      }
    }

    interpState.isDirty = false;
    _updateSaveStatus(data.exists ? "saved" : "new");
    _updateFileInfo(data.file_path || "");
  } catch (err) {
    console.error("층 내용 로드 실패:", err);
    _updateSaveStatus("error");
  }
}

async function _saveLayerContent() {
  if (!interpState.interpId || !viewerState.partId || !viewerState.pageNum)
    return;

  const { interpId, currentLayer, currentSubType } = interpState;
  const { partId, pageNum } = viewerState;

  const content = document.getElementById("interp-content");
  if (!content) return;

  _updateSaveStatus("saving");

  const url = `/api/interpretations/${interpId}/layers/${currentLayer}/${currentSubType}/pages/${pageNum}`;

  try {
    const res = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content: content.value,
        part_id: partId,
      }),
    });
    if (!res.ok) throw new Error("저장 API 오류");
    const result = await res.json();
    console.log("저장 완료:", result);

    interpState.isDirty = false;
    _updateSaveStatus("saved");
    _updateFileInfo(result.file_path || "");
  } catch (err) {
    console.error("층 내용 저장 실패:", err);
    _updateSaveStatus("error");
  }
}

/* ──────────────────────────
   UI 유틸리티
   ────────────────────────── */

function _updateSaveStatus(status) {
  const el = document.getElementById("interp-save-status");
  if (!el) return;

  const map = {
    saved: { text: "저장됨", cls: "status-saved" },
    new: { text: "새 파일", cls: "status-new" },
    modified: { text: "수정됨", cls: "status-modified" },
    saving: { text: "저장 중...", cls: "status-saving" },
    error: { text: "오류", cls: "status-error" },
    empty: { text: "", cls: "" },
  };

  const info = map[status] || map["empty"];
  el.textContent = info.text;
  el.className = `text-save-status ${info.cls}`;
}

function _updateFileInfo(filePath) {
  const el = document.getElementById("interp-file-info");
  if (el) el.textContent = filePath;
}

/* ──────────────────────────
   생성 다이얼로그
   ────────────────────────── */

async function _openCreateDialog() {
  const overlay = document.getElementById("interp-dialog-overlay");
  if (!overlay) return;

  // 문헌 목록으로 select 채우기
  const select = document.getElementById("interp-new-source");
  if (select) {
    try {
      const res = await fetch("/api/documents");
      if (res.ok) {
        const docs = await res.json();
        select.innerHTML = '<option value="">문헌을 선택하세요</option>';
        docs.forEach((doc) => {
          const opt = document.createElement("option");
          opt.value = doc.document_id;
          opt.textContent = `${doc.title || doc.document_id} (${doc.document_id})`;
          select.appendChild(opt);
        });
      }
    } catch (err) {
      console.error("문헌 목록 로드 실패:", err);
    }
  }

  // 필드 초기화
  const fields = ["interp-new-id", "interp-new-name", "interp-new-title"];
  fields.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });

  const statusEl = document.getElementById("interp-create-status");
  if (statusEl) statusEl.textContent = "";

  overlay.style.display = "";
}

function _closeCreateDialog() {
  const overlay = document.getElementById("interp-dialog-overlay");
  if (overlay) overlay.style.display = "none";
}

async function _createInterpretation() {
  const interpId = document.getElementById("interp-new-id")?.value?.trim();
  const sourceDocId = document.getElementById("interp-new-source")?.value;
  const interpType = document.getElementById("interp-new-type")?.value;
  const interpName =
    document.getElementById("interp-new-name")?.value?.trim() || null;
  const title =
    document.getElementById("interp-new-title")?.value?.trim() || null;
  const statusEl = document.getElementById("interp-create-status");

  if (!interpId) {
    if (statusEl) statusEl.textContent = "ID를 입력하세요";
    return;
  }
  if (!sourceDocId) {
    if (statusEl) statusEl.textContent = "원본 문헌을 선택하세요";
    return;
  }

  if (statusEl) statusEl.textContent = "생성 중...";

  try {
    const res = await fetch("/api/interpretations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        interp_id: interpId,
        source_document_id: sourceDocId,
        interpreter_type: interpType,
        interpreter_name: interpName,
        title: title,
      }),
    });

    const data = await res.json();
    if (!res.ok) {
      if (statusEl) statusEl.textContent = data.error || "생성 실패";
      return;
    }

    if (statusEl) statusEl.textContent = "생성 완료!";
    setTimeout(() => {
      _closeCreateDialog();
      _loadInterpretationList();
    }, 500);
  } catch (err) {
    console.error("해석 저장소 생성 실패:", err);
    if (statusEl) statusEl.textContent = "네트워크 오류";
  }
}

/* ──────────────────────────
   비교 모드
   ────────────────────────── */

/**
 * 비교 모드를 켜거나 끈다.
 *
 * 왜 이렇게 하는가:
 *   일반 모드의 편집 textarea와 비교 모드의 읽기 전용 diff 뷰를
 *   display:none/block으로 교체하여, 기존 편집 흐름을 전혀 건드리지 않는다.
 *
 * 입력: enabled — true면 비교 모드, false면 일반 모드.
 */
function _toggleCompareMode(enabled) {
  compareState.active = enabled;

  const textarea = document.getElementById("interp-content");
  const container = document.getElementById("compare-container");
  const interpPanel = document.getElementById("interp-panel");

  if (!textarea || !container) return;

  if (enabled) {
    // 일반 모드 → 비교 모드
    textarea.style.display = "none";
    container.style.display = "";

    // 비교 모드 표시 클래스 (도구 바 요소 숨김용)
    if (interpPanel) interpPanel.classList.add("compare-mode-active");

    // 드롭다운에 저장소 목록 채우기
    _populateCompareSelects();

    // 현재 선택된 저장소를 A에 자동 선택
    if (interpState.interpId) {
      const selectA = document.getElementById("compare-repo-a");
      if (selectA) {
        selectA.value = interpState.interpId;
        compareState.repoIdA = interpState.interpId;
      }
    }

    _loadCompareContent();
  } else {
    // 비교 모드 → 일반 모드
    textarea.style.display = "";
    container.style.display = "none";

    if (interpPanel) interpPanel.classList.remove("compare-mode-active");

    // 상태 초기화
    compareState.repoIdA = null;
    compareState.repoIdB = null;
    compareState.contentA = "";
    compareState.contentB = "";
  }
}

/**
 * 비교 모드의 좌/우 저장소 선택 드롭다운을 채운다.
 *
 * 왜 이렇게 하는가:
 *   interpState.interpretations에 이미 캐시된 목록을 사용하여
 *   추가 API 호출 없이 드롭다운을 구성한다.
 */
function _populateCompareSelects() {
  const selects = [
    document.getElementById("compare-repo-a"),
    document.getElementById("compare-repo-b"),
  ];

  selects.forEach((sel) => {
    if (!sel) return;
    const currentVal = sel.value;
    sel.innerHTML = '<option value="">저장소 선택</option>';
    (interpState.interpretations || []).forEach((item) => {
      const opt = document.createElement("option");
      opt.value = item.interpretation_id;
      // 제목과 해석자 유형을 함께 표시
      const typeLabel =
        item.interpreter_type === "llm" ? " [LLM]" :
        item.interpreter_type === "hybrid" ? " [혼합]" : "";
      opt.textContent = (item.title || item.interpretation_id) + typeLabel;
      sel.appendChild(opt);
    });
    // 이전 선택값 복원
    if (currentVal) sel.value = currentVal;
  });
}

/**
 * 비교 모드에서 좌/우 패널의 내용을 로드하고 diff를 표시한다.
 *
 * 왜 이렇게 하는가:
 *   동일한 층(layer), 서브타입(subType), 페이지(pageNum)에 대해
 *   두 해석 저장소의 내용을 나란히 가져와 줄 단위 비교를 수행한다.
 *   기존 API 엔드포인트를 그대로 재사용한다.
 */
// eslint-disable-next-line no-unused-vars
async function _loadCompareContent() {
  if (!compareState.active) return;
  if (!viewerState.partId || !viewerState.pageNum) return;

  const { currentLayer, currentSubType } = interpState;
  const { partId, pageNum } = viewerState;

  // 좌측(A)과 우측(B)를 병렬로 로드
  const [contentA, contentB] = await Promise.all([
    _fetchComparePane(compareState.repoIdA, currentLayer, currentSubType, partId, pageNum),
    _fetchComparePane(compareState.repoIdB, currentLayer, currentSubType, partId, pageNum),
  ]);

  compareState.contentA = contentA;
  compareState.contentB = contentB;

  // diff 계산 및 렌더링
  _renderCompareDiff();
}

/**
 * 비교 패널 한쪽의 내용을 API에서 가져온다.
 *
 * 입력: repoId — 해석 저장소 ID (null이면 빈 문자열 반환)
 * 출력: 텍스트 문자열
 */
async function _fetchComparePane(repoId, layer, subType, partId, pageNum) {
  if (!repoId) return "";
  try {
    const url = `/api/interpretations/${repoId}/layers/${layer}/${subType}/pages/${pageNum}?part_id=${partId}`;
    const res = await fetch(url);
    if (!res.ok) return "";
    const data = await res.json();
    return _extractTextContent(data.content);
  } catch (err) {
    console.error(`비교 패널 로드 실패 (${repoId}):`, err);
    return "";
  }
}

/**
 * API 응답의 content를 문자열로 변환한다.
 *
 * 왜 이렇게 하는가:
 *   L6_translation은 문자열, L5_reading/L7_annotation은 JSON 객체를 반환한다.
 *   비교를 위해 모든 경우를 문자열로 통일한다.
 */
function _extractTextContent(content) {
  if (typeof content === "string") return content;
  if (
    typeof content === "object" &&
    content !== null &&
    Object.keys(content).length > 0
  ) {
    return JSON.stringify(content, null, 2);
  }
  return "";
}

/**
 * 비교 모드의 좌/우 패널에 diff 하이라이트를 렌더링한다.
 *
 * 왜 이렇게 하는가:
 *   줄 단위로 두 텍스트를 비교하여, 추가/삭제/동일 줄을
 *   시각적으로 구분한다. 고전 텍스트 비교에서는 줄 단위가 충분하다.
 */
function _renderCompareDiff() {
  const containerA = document.getElementById("compare-content-a");
  const containerB = document.getElementById("compare-content-b");
  if (!containerA || !containerB) return;

  // 저장소가 하나도 선택되지 않은 경우
  if (!compareState.repoIdA && !compareState.repoIdB) {
    containerA.innerHTML =
      '<div class="compare-placeholder">좌측 저장소를 선택하세요</div>';
    containerB.innerHTML =
      '<div class="compare-placeholder">우측 저장소를 선택하세요</div>';
    return;
  }

  const linesA = (compareState.contentA || "").split("\n");
  const linesB = (compareState.contentB || "").split("\n");

  // 양쪽 모두 내용이 없는 경우
  if (
    linesA.length <= 1 && linesA[0] === "" &&
    linesB.length <= 1 && linesB[0] === ""
  ) {
    containerA.innerHTML =
      '<div class="compare-placeholder">내용 없음</div>';
    containerB.innerHTML =
      '<div class="compare-placeholder">내용 없음</div>';
    return;
  }

  // diff 계산
  const diffResult = _computeLineDiff(linesA, linesB);

  // 렌더링
  containerA.innerHTML = "";
  containerB.innerHTML = "";

  diffResult.forEach((entry) => {
    if (entry.type === "unchanged") {
      containerA.appendChild(_makeDiffLine(entry.lineA, "diff-line-unchanged"));
      containerB.appendChild(_makeDiffLine(entry.lineB, "diff-line-unchanged"));
    } else if (entry.type === "removed") {
      // A에만 있는 줄: A에 빨간, B에 빈 줄
      containerA.appendChild(_makeDiffLine(entry.lineA, "diff-line-removed"));
      containerB.appendChild(_makeDiffLine("", "diff-line-removed"));
    } else if (entry.type === "added") {
      // B에만 있는 줄: A에 빈 줄, B에 초록
      containerA.appendChild(_makeDiffLine("", "diff-line-added"));
      containerB.appendChild(_makeDiffLine(entry.lineB, "diff-line-added"));
    }
  });
}

/**
 * diff 줄 DOM 요소를 생성한다.
 */
function _makeDiffLine(text, className) {
  const div = document.createElement("div");
  div.className = className;
  // textContent로 XSS 방지
  if (text) {
    div.textContent = text;
  } else {
    // 빈 줄도 높이를 유지하기 위해 공백 삽입
    div.innerHTML = "&nbsp;";
  }
  return div;
}

/**
 * 줄 단위 diff를 계산한다. (LCS 기반)
 *
 * 왜 이렇게 하는가:
 *   외부 라이브러리 없이 간단한 줄 단위 비교를 수행한다.
 *   고전 텍스트 페이지의 줄 수는 보통 수십 줄이므로 O(n*m) LCS로 충분하다.
 *
 * 입력: linesA — 좌측 줄 배열, linesB — 우측 줄 배열.
 * 출력: [{type: "unchanged"|"added"|"removed", lineA, lineB}] 배열.
 */
function _computeLineDiff(linesA, linesB) {
  const m = linesA.length;
  const n = linesB.length;

  // LCS 테이블 (DP)
  const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (linesA[i - 1] === linesB[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  // 역추적으로 diff 생성
  const result = [];
  let i = m;
  let j = n;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && linesA[i - 1] === linesB[j - 1]) {
      result.unshift({
        type: "unchanged",
        lineA: linesA[i - 1],
        lineB: linesB[j - 1],
      });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      result.unshift({ type: "added", lineA: null, lineB: linesB[j - 1] });
      j--;
    } else {
      result.unshift({ type: "removed", lineA: linesA[i - 1], lineB: null });
      i--;
    }
  }

  return result;
}
