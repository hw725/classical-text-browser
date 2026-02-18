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
  active: false,               // 해석 모드 활성화 여부
  interpId: null,              // 선택된 해석 저장소 ID
  interpInfo: null,            // manifest 캐시
  depStatus: null,             // 의존 변경 확인 결과
  currentLayer: "L5_reading",  // 현재 층
  currentSubType: "main_text", // main_text | annotation
  isDirty: false,              // 편집 변경 여부
  interpretations: [],         // 전체 목록 캐시
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

  const dialogClose = document.getElementById("interp-dialog-close");
  if (dialogClose) dialogClose.addEventListener("click", _closeCreateDialog);

  const dialogOverlay = document.getElementById("interp-dialog-overlay");
  if (dialogOverlay) dialogOverlay.addEventListener("click", (e) => {
    if (e.target === dialogOverlay) _closeCreateDialog();
  });

  const createSaveBtn = document.getElementById("interp-create-save-btn");
  if (createSaveBtn) createSaveBtn.addEventListener("click", _createInterpretation);

  // 층별 서브탭
  document.querySelectorAll(".interp-subtab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const layer = tab.dataset.layer;
      if (layer === interpState.currentLayer) return;

      document.querySelectorAll(".interp-subtab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      interpState.currentLayer = layer;

      // L7_annotation은 sub_type 토글 숨김
      const subtypeBar = document.getElementById("interp-subtype-bar");
      if (subtypeBar) {
        subtypeBar.style.display = (layer === "L7_annotation") ? "none" : "";
      }

      _loadLayerContent();
    });
  });

  // main_text / annotation 라디오
  document.querySelectorAll('input[name="interp-subtype"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      interpState.currentSubType = radio.value;
      _loadLayerContent();
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
      container.innerHTML = '<div class="placeholder">등록된 해석 저장소가 없습니다</div>';
      return;
    }

    container.innerHTML = list.map((item) => {
      const typeClass = `type-${item.interpreter?.type || "human"}`;
      const typeLabel = item.interpreter?.type || "human";
      return `
        <div class="interp-list-item" data-interp-id="${item.interpretation_id}">
          <span class="interp-type-badge ${typeClass}">${typeLabel}</span>
          <span class="interp-list-title">${item.title || item.interpretation_id}</span>
          <span class="interp-list-source">${item.source_document_id}</span>
        </div>
      `;
    }).join("");

    // 클릭 이벤트
    container.querySelectorAll(".interp-list-item").forEach((el) => {
      el.addEventListener("click", () => {
        _selectInterpretation(el.dataset.interpId);
        // 하이라이트
        container.querySelectorAll(".interp-list-item").forEach((i) => i.classList.remove("active"));
        el.classList.add("active");
      });
    });
  } catch (err) {
    console.error("해석 저장소 목록 로드 실패:", err);
    container.innerHTML = '<div class="placeholder">목록을 불러올 수 없습니다</div>';
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
    const res = await fetch(`/api/interpretations/${interpState.interpId}/dependency`);
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
    "outdated": "원본이 변경되었습니다",
    "partially_acknowledged": "일부 변경을 인지했습니다",
    "acknowledged": "모든 변경을 인지했습니다",
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
  // 하단 패널 "의존 추적" 탭을 활성화
  const tabs = document.querySelectorAll(".panel-tabs .panel-tab");
  tabs.forEach((t) => t.classList.remove("active"));
  // "의존 추적"은 3번째 탭 (인덱스 2)
  if (tabs[2]) tabs[2].classList.add("active");

  // 탭 내용 전환
  const gitContent = document.getElementById("git-panel-content");
  const depContent = document.getElementById("dep-panel-content");
  if (gitContent) gitContent.style.display = "none";
  if (depContent) depContent.style.display = "";
}

async function _acknowledgeChanges() {
  if (!interpState.interpId) return;

  try {
    const res = await fetch(`/api/interpretations/${interpState.interpId}/dependency/acknowledge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_paths: null }),
    });
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
    const res = await fetch(`/api/interpretations/${interpState.interpId}/dependency/update-base`, {
      method: "POST",
    });
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
  const badgeClass = {
    "current": "status-current",
    "outdated": "status-outdated",
    "acknowledged": "status-acknowledged",
    "partially_acknowledged": "status-partially",
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

  fileList.innerHTML = files.map((tf) => {
    const stClass = `st-${tf.status}`;
    return `
      <div class="dep-file-item">
        <span class="dep-file-status ${stClass}">${tf.status}</span>
        <span class="dep-file-path">${tf.path}</span>
      </div>
    `;
  }).join("");
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
      } else if (typeof data.content === "object" && data.content !== null && Object.keys(data.content).length > 0) {
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
  if (!interpState.interpId || !viewerState.partId || !viewerState.pageNum) return;

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
    "saved": { text: "저장됨", cls: "status-saved" },
    "new": { text: "새 파일", cls: "status-new" },
    "modified": { text: "수정됨", cls: "status-modified" },
    "saving": { text: "저장 중...", cls: "status-saving" },
    "error": { text: "오류", cls: "status-error" },
    "empty": { text: "", cls: "" },
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
  const interpName = document.getElementById("interp-new-name")?.value?.trim() || null;
  const title = document.getElementById("interp-new-title")?.value?.trim() || null;
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
