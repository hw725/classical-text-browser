/**
 * 드래그 앤 드롭 온보딩 — PDF/이미지를 창 어디에나 끌어다 놓으면 새 문헌 생성.
 *
 * 목적:
 *   첫 사용자가 경로 설정 없이 파일 하나로 작업을 시작할 수 있게 한다.
 *   서고가 아직 없으면 기본 서고(~/Documents/고전서지서고)를 자동으로
 *   만들어 연결한 뒤(POST /api/library/quick-start), 새 문헌 다이얼로그를
 *   드롭된 파일이 채워진 상태(Step2)로 연다.
 *
 * 왜 원본 경로를 쓰지 않고 파일 바이트를 업로드하는가:
 *   브라우저 보안상 드롭된 파일의 절대 경로는 읽을 수 없다. 그리고 이
 *   프로젝트는 설계상 원본을 L1_source/로 복사해 불변층으로 격리한다
 *   (platform-v7) — 원본 경로 참조 방식은 원본 이동 시 링크가 끊기는
 *   문제가 있어 의도적으로 피한 구조다. 따라서 업로드-복사가 정답이다.
 *
 * 의존성: create-document.js (openCreateDocDialogWithFiles),
 *         toast.js (showToast), workspace.js (loadLibraryInfo)
 */

/** dragenter/dragleave 짝을 세는 카운터.
 *  왜: 자식 요소로 드래그가 들어갔다 나올 때마다 leave가 발생하므로,
 *  단순 boolean으로는 오버레이가 깜빡인다. */
let _ddDepth = 0;

/** 드롭 처리 중 재진입 방지 플래그 (연속 드롭으로 다이얼로그가 엉키지 않게). */
let _ddBusy = false;

/** 폴더 드롭 시 순회 상한 — 실수로 거대한 폴더를 떨어뜨렸을 때의 보호막. */
const _DD_MAX_FILES = 2000;
const _DD_MAX_DEPTH = 4;

/** 허용 확장자 — create-document.js의 _LOCAL_ALLOWED_EXT와 같은 규칙.
 *  폴더 순회 중 Thumbs.db 등 잡파일을 걸러내는 용도로만 쓰고,
 *  최상위 드롭 파일은 그대로 넘겨 create-document 쪽에서 "지원 안 함"
 *  메시지를 보여주게 한다 (조용히 사라지면 사용자가 원인을 모른다). */
const _DD_ALLOWED_EXT = ["pdf", "jpg", "jpeg", "png", "tif", "tiff"];


/**
 * 전역 드래그 앤 드롭을 초기화한다. workspace.js의 DOMContentLoaded에서 호출.
 */
// eslint-disable-next-line no-unused-vars
function initDragDrop() {
  _ensureDropOverlay();

  // 파일을 끌고 있는 드래그인지 판별 — 텍스트 선택 드래그나
  // 레이아웃 블록 재정렬(layout-editor.js) 드래그에는 반응하면 안 된다.
  const isFileDrag = (e) =>
    e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");

  window.addEventListener("dragenter", (e) => {
    if (!isFileDrag(e)) return;
    e.preventDefault();
    _ddDepth += 1;
    _setDropOverlayVisible(true);
  });

  window.addEventListener("dragover", (e) => {
    if (!isFileDrag(e)) return;
    // preventDefault 없이는 브라우저가 드롭 자체를 거부하거나
    // 파일을 새 탭으로 열어 버린다.
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  });

  window.addEventListener("dragleave", (e) => {
    if (!isFileDrag(e)) return;
    _ddDepth = Math.max(0, _ddDepth - 1);
    if (_ddDepth === 0) _setDropOverlayVisible(false);
  });

  window.addEventListener("drop", (e) => {
    // 파일 드래그가 아니어도 preventDefault — 브라우저 기본 동작
    // (파일을 현재 탭에서 열어 앱을 떠나는 것)을 항상 막는다.
    e.preventDefault();
    _ddDepth = 0;
    _setDropOverlayVisible(false);
    if (!isFileDrag(e)) return;
    _handleFileDrop(e.dataTransfer);
  });
}


/**
 * 드롭된 파일들을 수집하고 서고를 확보한 뒤 새 문헌 다이얼로그를 연다.
 */
async function _handleFileDrop(dataTransfer) {
  if (_ddBusy) return;
  _ddBusy = true;
  try {
    const files = await _collectDroppedFiles(dataTransfer);
    if (files.length === 0) {
      if (typeof showToast === "function") {
        showToast(
          "지원하는 파일이 없습니다. PDF, JPG, PNG, TIF만 가능합니다.",
          "warning",
        );
      }
      return;
    }

    // 서고가 없으면 기본 서고를 자동으로 만들어 연결한다.
    const ok = await _ensureLibraryReady();
    if (!ok) return;

    if (typeof openCreateDocDialogWithFiles === "function") {
      openCreateDocDialogWithFiles(files);
    }
  } finally {
    _ddBusy = false;
  }
}


/**
 * DataTransfer에서 File 배열을 수집한다. 폴더 드롭도 지원한다.
 *
 * 왜 webkitGetAsEntry인가:
 *   dataTransfer.files는 폴더를 크기 0의 파일로 주거나 무시한다.
 *   페이지 이미지 수백 장이 든 폴더를 통째로 끌어놓는 것이 연구자의
 *   실제 사용 패턴이므로 디렉터리 순회가 필요하다.
 *
 * 정렬:
 *   readEntries의 반환 순서는 브라우저마다 보장되지 않는다. 이미지
 *   순서가 곧 페이지 순서가 되므로, 폴더 내 항목은 파일명 숫자
 *   인식(numeric) 정렬로 고정한다 (img2.jpg < img10.jpg).
 */
async function _collectDroppedFiles(dataTransfer) {
  const out = [];
  const items = dataTransfer.items;

  const supportsEntries =
    items &&
    items.length > 0 &&
    typeof items[0].webkitGetAsEntry === "function";

  if (!supportsEntries) {
    for (const f of Array.from(dataTransfer.files || [])) out.push(f);
    return out;
  }

  // items는 라이브 컬렉션이라 await 후 무효화될 수 있다 — entry를 먼저 전부 뽑는다.
  const entries = [];
  const looseFiles = [];
  for (const item of Array.from(items)) {
    if (item.kind !== "file") continue;
    const entry = item.webkitGetAsEntry();
    if (entry) entries.push(entry);
    else {
      const f = item.getAsFile();
      if (f) looseFiles.push(f);
    }
  }

  for (const entry of entries) {
    await _walkEntry(entry, out, 0, /* insideFolder= */ false);
    if (out.length >= _DD_MAX_FILES) break;
  }
  out.push(...looseFiles);

  if (out.length >= _DD_MAX_FILES && typeof showToast === "function") {
    showToast(
      `파일이 너무 많아 처음 ${_DD_MAX_FILES}개까지만 추가했습니다.`,
      "warning",
    );
  }
  return out.slice(0, _DD_MAX_FILES);
}


/**
 * FileSystemEntry를 재귀 순회하며 File을 수집한다.
 *
 * insideFolder=true(폴더 안 파일)일 때만 확장자를 필터링한다.
 * 최상위에 직접 드롭한 파일은 걸러내지 않고 넘겨서, create-document의
 * "지원 안 함: ..." 안내가 사용자에게 보이게 한다.
 */
async function _walkEntry(entry, out, depth, insideFolder) {
  if (out.length >= _DD_MAX_FILES) return;

  if (entry.isFile) {
    const file = await new Promise((resolve) =>
      entry.file(resolve, () => resolve(null)),
    );
    if (!file) return;
    if (insideFolder) {
      const ext = (file.name.split(".").pop() || "").toLowerCase();
      if (!_DD_ALLOWED_EXT.includes(ext)) return; // 폴더 안 잡파일은 조용히 제외
    }
    out.push(file);
    return;
  }

  if (entry.isDirectory) {
    if (depth >= _DD_MAX_DEPTH) return;
    const reader = entry.createReader();
    const children = [];
    // readEntries는 한 번에 최대 100개만 반환 — 빈 배열이 올 때까지 반복.
    for (;;) {
      const batch = await new Promise((resolve) =>
        reader.readEntries(resolve, () => resolve([])),
      );
      if (!batch || batch.length === 0) break;
      children.push(...batch);
    }
    children.sort((a, b) =>
      a.name.localeCompare(b.name, undefined, { numeric: true }),
    );
    for (const child of children) {
      await _walkEntry(child, out, depth + 1, true);
      if (out.length >= _DD_MAX_FILES) return;
    }
  }
}


/**
 * 서고가 연결되어 있는지 확인하고, 없으면 기본 서고를 자동 생성한다.
 *
 * 반환: 서고가 준비되면 true. 실패 시 사용자에게 토스트로 알리고 false.
 */
async function _ensureLibraryReady() {
  try {
    const res = await fetch("/api/library");
    if (res.ok) return true;
  } catch {
    // 서버 연결 실패 — 아래 quick-start도 실패할 것이므로 그쪽 에러로 안내된다.
  }

  let data = null;
  try {
    const qs = await fetch("/api/library/quick-start", { method: "POST" });
    data = await qs.json().catch(() => null);
    if (!qs.ok) throw new Error(data?.error || "기본 서고 생성 실패");
  } catch (err) {
    if (typeof showToast === "function") {
      showToast(
        `서고를 준비하지 못했습니다: ${err.message}\n설정에서 서고 폴더를 직접 선택해 주세요.`,
        "error",
      );
    }
    return false;
  }

  if (typeof showToast === "function") {
    const where = data?.library_path || "";
    showToast(
      data?.created
        ? `기본 서고를 만들어 연결했습니다: ${where}\n(위치는 설정에서 언제든 바꿀 수 있습니다)`
        : `기존 기본 서고에 연결했습니다: ${where}`,
      "success",
    );
  }
  // 상태바·사이드바를 새 서고 기준으로 갱신
  if (typeof loadLibraryInfo === "function") loadLibraryInfo();
  return true;
}


/* ──────────────────────────
   드롭 오버레이 (전체 화면 안내)
   ────────────────────────── */

function _ensureDropOverlay() {
  if (document.getElementById("drop-overlay")) return;
  const el = document.createElement("div");
  el.id = "drop-overlay";
  el.className = "drop-overlay";
  // 마크업은 정적이고 사용자 입력이 섞이지 않으므로 innerHTML이 안전하다.
  el.innerHTML =
    '<div class="drop-overlay-box">' +
    '  <svg width="40" height="40" viewBox="0 0 24 24" fill="none"' +
    '       stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
    '    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>' +
    '    <polyline points="7 8 12 3 17 8"/>' +
    '    <line x1="12" y1="3" x2="12" y2="15"/>' +
    "  </svg>" +
    "  <div class=\"drop-overlay-title\">여기에 놓으면 새 문헌으로 등록됩니다</div>" +
    "  <div class=\"drop-overlay-sub\">PDF · JPG · PNG · TIF — 이미지 폴더도 통째로 가능합니다</div>" +
    "</div>";
  document.body.appendChild(el);
}

function _setDropOverlayVisible(visible) {
  const el = document.getElementById("drop-overlay");
  if (el) el.classList.toggle("drop-overlay-visible", visible);
}
