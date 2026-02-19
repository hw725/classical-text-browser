/**
 * HWP/HWPX 파일 가져오기 UI.
 *
 * 워크플로우:
 *   1. 파일 선택(.hwp/.hwpx) → 미리보기 (메타데이터 + 텍스트 + 표점·현토 감지)
 *   2. 문헌 ID 입력 + 옵션 설정 → 가져오기 실행
 *   3. doc_id가 이미 존재하면 시나리오 1 (기존 문서에 텍스트 투입)
 *      doc_id가 없으면 시나리오 2 (새 문헌 생성)
 *
 * 의존: index.html의 #hwp-import-overlay 다이얼로그.
 */

/* global _loadDocumentList */  // workspace.js에서 제공

// ── 다이얼로그 열기/닫기 ──────────────────────

/** 다이얼로그를 열고 초기 상태로 리셋한다. */
function _openHwpImportDialog() {
  const overlay = document.getElementById("hwp-import-overlay");
  if (!overlay) return;

  // 상태 초기화
  document.getElementById("hwp-import-file").value = "";
  document.getElementById("hwp-import-status").textContent = "";
  document.getElementById("hwp-import-preview").style.display = "none";
  document.getElementById("hwp-import-step2").style.display = "none";
  document.getElementById("hwp-import-exec-status").textContent = "";

  overlay.style.display = "flex";
}

/** 다이얼로그를 닫는다. */
function _closeHwpImportDialog() {
  const overlay = document.getElementById("hwp-import-overlay");
  if (overlay) overlay.style.display = "none";
}


// ── 미리보기 ──────────────────────────────────

/** 선택한 HWP 파일의 미리보기를 서버에서 가져온다. */
async function _previewHwpFile() {
  const fileInput = document.getElementById("hwp-import-file");
  const statusEl = document.getElementById("hwp-import-status");
  const previewDiv = document.getElementById("hwp-import-preview");

  if (!fileInput.files || fileInput.files.length === 0) {
    statusEl.textContent = "파일을 선택하세요.";
    return;
  }

  const file = fileInput.files[0];
  statusEl.textContent = "미리보기 중...";

  try {
    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch("/api/documents/preview-hwp", {
      method: "POST",
      body: formData,
    });

    const data = await res.json();

    if (!res.ok) {
      statusEl.textContent = data.error || "미리보기 실패";
      return;
    }

    // 메타데이터 표시
    const metaEl = document.getElementById("hwp-import-meta");
    const meta = data.metadata || {};
    metaEl.innerHTML = [
      `<b>제목:</b> ${meta.title || "(없음)"}`,
      `<b>형식:</b> ${meta.format || "?"}`,
      `<b>섹션 수:</b> ${data.sections_count || 0}`,
      `<b>전체 길이:</b> ${(data.full_text_length || 0).toLocaleString()}자`,
    ].join(" &nbsp;|&nbsp; ");

    // 감지 뱃지
    const punctEl = document.getElementById("hwp-preview-punct");
    const hyeontoEl = document.getElementById("hwp-preview-hyeonto");
    const taiduEl = document.getElementById("hwp-preview-taidu");

    punctEl.textContent = data.detected_punctuation
      ? `표점 감지 (${data.punct_count}개)` : "표점 없음";
    punctEl.style.color = data.detected_punctuation ? "#e0a000" : "#666";

    hyeontoEl.textContent = data.detected_hyeonto
      ? `현토 감지 (${data.hyeonto_count}개)` : "현토 없음";
    hyeontoEl.style.color = data.detected_hyeonto ? "#e0a000" : "#666";

    taiduEl.textContent = data.detected_taidu ? "대두 감지" : "";

    // 텍스트 미리보기
    document.getElementById("hwp-import-text-preview").value =
      data.text_preview || "(텍스트 없음)";
    document.getElementById("hwp-import-clean-preview").value =
      data.sample_clean_text || "";

    previewDiv.style.display = "block";

    // Step 2 표시
    const step2 = document.getElementById("hwp-import-step2");
    step2.style.display = "block";

    // 제목 자동 채우기
    const titleInput = document.getElementById("hwp-import-title");
    if (!titleInput.value && meta.title) {
      titleInput.value = meta.title;
    }

    statusEl.textContent = "";
  } catch (err) {
    statusEl.textContent = `오류: ${err.message}`;
  }
}


// ── 가져오기 실행 ─────────────────────────────

/** HWP 텍스트를 문헌으로 가져온다. */
async function _executeHwpImport() {
  const fileInput = document.getElementById("hwp-import-file");
  const docIdInput = document.getElementById("hwp-import-doc-id");
  const titleInput = document.getElementById("hwp-import-title");
  const stripPunct = document.getElementById("hwp-import-strip-punct").checked;
  const stripHyeonto = document.getElementById("hwp-import-strip-hyeonto").checked;
  const statusEl = document.getElementById("hwp-import-exec-status");
  const execBtn = document.getElementById("hwp-import-exec-btn");

  const docId = docIdInput.value.trim();
  if (!docId) {
    statusEl.textContent = "문헌 ID를 입력하세요.";
    return;
  }

  if (!fileInput.files || fileInput.files.length === 0) {
    statusEl.textContent = "파일을 선택하세요.";
    return;
  }

  // 실행 중 버튼 비활성화
  execBtn.disabled = true;
  statusEl.textContent = "가져오는 중...";

  try {
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    formData.append("doc_id", docId);
    if (titleInput.value.trim()) {
      formData.append("title", titleInput.value.trim());
    }
    formData.append("strip_punctuation", stripPunct.toString());
    formData.append("strip_hyeonto", stripHyeonto.toString());

    const res = await fetch("/api/documents/import-hwp", {
      method: "POST",
      body: formData,
    });

    const data = await res.json();

    if (!res.ok) {
      statusEl.textContent = data.error || "가져오기 실패";
      return;
    }

    // 성공
    const stats = data.cleaned_stats || {};
    const mode = data.mode === "create_from_hwp" ? "새 문헌 생성" : "기존 문헌에 투입";
    statusEl.textContent =
      `완료: ${mode} — ${data.pages_saved}페이지` +
      (stats.punct_count ? `, 표점 ${stats.punct_count}개 분리` : "") +
      (stats.hyeonto_count ? `, 현토 ${stats.hyeonto_count}개 분리` : "");

    // 문헌 목록 새로고침
    if (typeof _loadDocumentList === "function") {
      _loadDocumentList();
    }
  } catch (err) {
    statusEl.textContent = `오류: ${err.message}`;
  } finally {
    execBtn.disabled = false;
  }
}


// ── 이벤트 바인딩 ─────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  // 닫기 버튼
  const closeBtn = document.getElementById("hwp-import-close");
  if (closeBtn) closeBtn.addEventListener("click", _closeHwpImportDialog);

  // 오버레이 클릭으로 닫기
  const overlay = document.getElementById("hwp-import-overlay");
  if (overlay) {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) _closeHwpImportDialog();
    });
  }

  // 미리보기 버튼
  const previewBtn = document.getElementById("hwp-import-preview-btn");
  if (previewBtn) previewBtn.addEventListener("click", _previewHwpFile);

  // 가져오기 실행 버튼
  const execBtn = document.getElementById("hwp-import-exec-btn");
  if (execBtn) execBtn.addEventListener("click", _executeHwpImport);
});
