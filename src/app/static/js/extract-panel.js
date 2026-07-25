/**
 * 텍스트 추출 패널 — 「논문」 프로필 전용 (D-055).
 *
 * 왜 별도 패널인가:
 *   고서 흐름은 «레이아웃 → OCR → 교정»을 페이지마다 반복하는 것을 전제로 한다.
 *   근현대 논문은 판형이 페이지마다 같아 그 반복에 의미가 없다.
 *   진단 → 엔진 → 권 전체 OCR → 산출물을 한자리에 모아 한 번에 끝낸다.
 *
 * 왜 열람 탭 안에 두는가:
 *   새 모드 탭을 만들면 «탭을 줄이려고 시작한 일»이 탭을 늘리는 것으로 끝난다.
 *   열람은 문헌을 열면 처음 보게 되는 화면이므로 여기가 자연스럽다.
 *
 * 교감 모드에서는 hidden이므로 기존 열람 화면은 아무것도 바뀌지 않는다.
 */

/** 마지막으로 진단한 문헌/권 — 같은 대상을 중복 조회하지 않기 위해. */
let _extractLast = { docId: null, partId: null };
/** 진행 중인 OCR 요청의 중단 신호. 쪽 경계에서 멈춘다. */
let _extractAbort = null;

/**
 * "1-10, 15" 같은 쪽 범위 문자열을 쪽 번호 배열로 바꾼다.
 *
 * 입력: raw — 사용자가 입력한 문자열. 비어 있으면 null(= 전체).
 *       maxPage — 이 권의 마지막 쪽.
 * 출력: 정렬된 중복 없는 쪽 번호 배열, 또는 null.
 */
function parsePageRange(raw, maxPage) {
  const text = (raw || "").trim();
  if (!text) return null;

  const pages = new Set();
  for (const chunk of text.split(",")) {
    const part = chunk.trim();
    if (!part) continue;
    const range = part.match(/^(\d+)\s*-\s*(\d+)$/);
    if (range) {
      const from = parseInt(range[1], 10);
      const to = parseInt(range[2], 10);
      for (let p = Math.min(from, to); p <= Math.max(from, to); p++) {
        if (p >= 1 && (!maxPage || p <= maxPage)) pages.add(p);
      }
      continue;
    }
    const single = parseInt(part, 10);
    if (!Number.isNaN(single) && single >= 1 && (!maxPage || single <= maxPage)) {
      pages.add(single);
    }
  }
  return pages.size ? [...pages].sort((a, b) => a - b) : null;
}

/** 현재 열린 문헌/권을 돌려준다. 없으면 null. */
function _extractTarget() {
  if (typeof viewerState === "undefined" || !viewerState) return null;
  if (!viewerState.docId || !viewerState.partId) return null;
  return { docId: viewerState.docId, partId: viewerState.partId };
}

/** 이 권의 쪽 수를 manifest에서 찾는다. 모르면 0. */
function _extractPageCount() {
  const info = viewerState && viewerState.documentInfo;
  if (!info || !Array.isArray(info.parts)) return 0;
  const part = info.parts.find((p) => p.part_id === viewerState.partId);
  return part ? Number(part.page_count) || 0 : 0;
}

/**
 * 패널 전체를 현재 문헌 상태에 맞춰 다시 그린다.
 *
 * 추출 모드이 아니거나 문헌이 없으면 아무것도 하지 않는다.
 */
async function refreshExtractPanel(force) {
  const panel = document.getElementById("extract-panel");
  if (!panel || panel.hidden) return;

  const target = _extractTarget();
  const diagnosis = document.getElementById("extract-diagnosis");
  const ocrSection = document.getElementById("extract-ocr-section");
  const importSection = document.getElementById("extract-import-section");

  if (!target) {
    diagnosis.textContent = "문헌의 페이지를 열면 진단합니다.";
    diagnosis.className = "extract-diagnosis";
    ocrSection.hidden = true;
    importSection.hidden = true;
    return;
  }

  const same =
    _extractLast.docId === target.docId && _extractLast.partId === target.partId;
  if (same && !force) return;
  _extractLast = { ...target };

  diagnosis.textContent = "진단 중…";
  diagnosis.className = "extract-diagnosis";

  try {
    const res = await fetch(
      `/api/documents/${target.docId}/parts/${target.partId}/text-layer`
    );
    const data = await res.json();
    if (!res.ok) {
      diagnosis.textContent = data.error || "진단하지 못했습니다.";
      diagnosis.className = "extract-diagnosis extract-diag-warn";
      ocrSection.hidden = true;
      importSection.hidden = true;
      return;
    }

    const labels = {
      born_digital: "텍스트 있음",
      partial: "일부만 텍스트",
      scanned: "스캔본",
    };
    const cls = {
      born_digital: "extract-diag-ok",
      partial: "extract-diag-warn",
      scanned: "extract-diag-scan",
    };
    diagnosis.className = `extract-diagnosis ${cls[data.verdict] || ""}`;
    diagnosis.textContent =
      `${labels[data.verdict] || data.verdict} — ${data.total_pages}쪽 ` +
      `(표본 ${data.sampled}쪽 중 ${data.pages_with_text}쪽에 활자)\n` +
      data.recommendation;

    // 스캔본·부분본이면 OCR을, 텍스트가 있으면 바로 가져오기를 권한다.
    ocrSection.hidden = data.verdict === "born_digital";
    importSection.hidden = data.verdict === "scanned";

    if (!ocrSection.hidden) await _loadExtractEngines();
    _updateExtractCost();
  } catch (e) {
    diagnosis.textContent = `진단 중 오류: ${e.message}`;
    diagnosis.className = "extract-diagnosis extract-diag-warn";
  }

  await _refreshExtractExport();
}

/**
 * OCR 엔진 목록을 채운다.
 *
 * 한글을 인식하지 못하는 엔진은 이름에 표시하고, 고르면 경고를 띄운다.
 * 기본 엔진은 "설치된 것 중 첫 번째"라 논문에 고전적 전용 엔진이 잡히기 때문이다.
 */
async function _loadExtractEngines() {
  const select = document.getElementById("extract-engine-select");
  if (!select || select.dataset.loaded === "1") return;

  try {
    const res = await fetch("/api/ocr/engines");
    const data = await res.json();
    const HANGUL_INCAPABLE = ["ndlocr", "ndlkotenocr", "ndlkotenocr-full"];

    select.innerHTML = "";
    let preferred = null;
    for (const engine of data.engines || []) {
      if (!engine.available) continue;
      const opt = document.createElement("option");
      opt.value = engine.engine_id;
      const noHangul = HANGUL_INCAPABLE.includes(engine.engine_id);
      opt.textContent = engine.display_name + (noHangul ? " — 한글 불가" : "");
      opt.dataset.noHangul = noHangul ? "1" : "";
      select.appendChild(opt);
      // 한글 논문이 대상이므로 한글 되는 엔진을 먼저 고른다.
      if (!preferred && !noHangul) preferred = engine.engine_id;
    }
    if (preferred) select.value = preferred;
    select.dataset.loaded = "1";
    _updateEngineWarning();
    select.addEventListener("change", _updateEngineWarning);
  } catch (e) {
    console.warn("[PaperPanel] 엔진 목록을 불러오지 못했습니다:", e);
  }
}

/** 선택한 엔진이 한글을 못 읽으면 경고를 보여 준다. */
function _updateEngineWarning() {
  const select = document.getElementById("extract-engine-select");
  const warn = document.getElementById("extract-engine-warn");
  if (!select || !warn) return;
  const opt = select.selectedOptions[0];
  if (opt && opt.dataset.noHangul) {
    warn.hidden = false;
    warn.textContent =
      "이 엔진은 한글을 인식하지 못합니다 (학습 데이터에 한글이 없습니다). " +
      "한글이 섞인 논문이면 LLM Vision을 고르세요.";
  } else {
    warn.hidden = true;
  }
}

/**
 * 몇 쪽을 돌리게 되는지, LLM 호출이 몇 번인지 미리 알린다.
 *
 * 왜 필요한가: 300쪽이면 LLM 호출도 300번이다. 실행 전에 규모를 알아야 한다.
 */
function _updateExtractCost() {
  const costEl = document.getElementById("extract-cost");
  const input = document.getElementById("extract-pages-input");
  const select = document.getElementById("extract-engine-select");
  if (!costEl) return;

  const maxPage = _extractPageCount();
  const pages = parsePageRange(input ? input.value : "", maxPage);
  const count = pages ? pages.length : maxPage;
  if (!count) {
    costEl.textContent = "";
    return;
  }
  const engineId = select && select.value;
  const usesLlm = engineId === "llm_vision";
  costEl.textContent = usesLlm
    ? `${count}쪽 → LLM 호출 ${count}회`
    : `${count}쪽 (오프라인 엔진 — LLM 호출 없음)`;
}

/** 구운 PDF가 있는지 확인해 내려받기 링크를 갱신한다. */
async function _refreshExtractExport() {
  const status = document.getElementById("extract-export-status");
  const link = document.getElementById("extract-download-link");
  const target = _extractTarget();
  if (!status || !link || !target) return;

  const url = `/api/documents/${target.docId}/parts/${target.partId}/export/text-layer-pdf`;
  try {
    const res = await fetch(`${url}/status`);
    const data = await res.json();
    if (res.ok && data.exists) {
      const kb = Math.round(data.size_bytes / 1024);
      const when = data.modified_at
        ? new Date(data.modified_at).toLocaleString("ko-KR")
        : "";
      status.textContent = `텍스트 레이어 PDF 준비됨 — ${kb}KB${when ? ", " + when : ""}`;
      status.className = "extract-export-status extract-diag-ok";
      link.hidden = false;
      link.href = url;
    } else {
      status.textContent = "아직 텍스트 레이어 PDF가 없습니다.";
      status.className = "extract-export-status";
      link.hidden = true;
    }
  } catch (e) {
    status.textContent = "";
    link.hidden = true;
  }
}

/** 권 전체 OCR을 실행하고 진행률을 표시한다. */
async function _runExtractOcr() {
  const target = _extractTarget();
  if (!target) {
    showToast("먼저 문헌의 페이지를 여세요.", "info");
    return;
  }

  const btn = document.getElementById("extract-run-ocr");
  const select = document.getElementById("extract-engine-select");
  const input = document.getElementById("extract-pages-input");
  const progress = document.getElementById("extract-progress");
  const fill = document.getElementById("extract-progress-fill");
  const text = document.getElementById("extract-progress-text");

  // 이미 돌고 있으면 중단 요청으로 동작한다 (쪽 경계에서 멈춘다).
  if (_extractAbort) {
    _extractAbort.abort();
    return;
  }

  const pages = parsePageRange(input.value, _extractPageCount());
  const body = { engine_id: select.value || null };
  if (pages) body.pages = pages;

  _extractAbort = new AbortController();
  btn.textContent = "중단";
  btn.classList.add("extract-running");
  progress.hidden = false;
  fill.style.width = "0%";
  text.textContent = "시작하는 중…";

  try {
    const res = await fetch(
      `/api/documents/${target.docId}/parts/${target.partId}/ocr/batch`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: _extractAbort.signal,
      }
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast(err.error || "OCR을 시작하지 못했습니다.", "error");
      return;
    }

    // SSE를 직접 읽는다 (EventSource는 POST를 지원하지 않는다).
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let done = null;

    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });

      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const line = part.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        let evt;
        try {
          evt = JSON.parse(line.slice(6));
        } catch (e) {
          continue;
        }

        if (evt.type === "start") {
          text.textContent = `${evt.total}쪽 처리 예정`;
          (evt.warnings || []).forEach((w) => showToast(w, "info"));
        } else if (evt.type === "page" || evt.type === "skip") {
          const pct = Math.round(((evt.index + 1) / evt.total) * 100);
          fill.style.width = `${pct}%`;
          const label = evt.type === "skip" ? "건너뜀" : `${evt.lines || 0}줄`;
          text.textContent = `${evt.index + 1}/${evt.total}쪽 — ${evt.page}쪽 ${label}`;
        } else if (evt.type === "baking") {
          fill.style.width = "100%";
          text.textContent = "텍스트 레이어 PDF를 굽는 중…";
        } else if (evt.type === "complete") {
          done = evt;
        } else if (evt.type === "error") {
          showToast(evt.error || "OCR 중 오류가 발생했습니다.", "error");
        }
      }
    }

    if (done) {
      const parts = [`${done.processed}쪽 처리`];
      if (done.skipped) parts.push(`${done.skipped}쪽 건너뜀`);
      if (done.failed) parts.push(`${done.failed}쪽 실패`);
      if (done.baked) parts.push(`PDF ${done.baked.baked_pages}쪽 구움`);
      text.textContent = parts.join(" · ");
      showToast(parts.join(" · "), "success");
      (done.warnings || []).forEach((w) => showToast(w, "info"));
      await _refreshExtractExport();
      // 지금 보고 있는 쪽의 텍스트를 다시 읽어 화면에 반영한다.
      if (typeof loadPageText === "function") {
        loadPageText(target.docId, target.partId, viewerState.pageNum);
      }
    }
  } catch (e) {
    if (e.name === "AbortError") {
      text.textContent = "중단했습니다. 다시 실행하면 이어서 돕니다.";
      showToast("중단했습니다. 이미 끝난 쪽은 저장돼 있습니다.", "info");
      await _refreshExtractExport();
    } else {
      showToast(`OCR 중 오류: ${e.message}`, "error");
    }
  } finally {
    _extractAbort = null;
    btn.textContent = "전체 OCR 실행";
    btn.classList.remove("extract-running");
  }
}

/** born-digital PDF의 텍스트를 L4로 가져온다. */
async function _importExtractText() {
  const target = _extractTarget();
  if (!target) return;
  try {
    const res = await fetch(
      `/api/documents/${target.docId}/parts/${target.partId}/text-import/from-text-layer`,
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
      showToast(`${data.imported}쪽을 가져왔습니다 (원본 활자 그대로).`, "success");
      if (typeof loadPageText === "function") {
        loadPageText(target.docId, target.partId, viewerState.pageNum);
      }
    }
    (data.warnings || []).forEach((w) => showToast(w, "info"));
  } catch (e) {
    showToast(`가져오기 중 오류: ${e.message}`, "error");
  }
}

/** 텍스트 레이어 PDF를 다시 굽는다 (교정 후 갱신용). */
async function _embedExtractPdf() {
  const target = _extractTarget();
  if (!target) {
    showToast("먼저 문헌의 페이지를 여세요.", "info");
    return;
  }
  const btn = document.getElementById("extract-embed-btn");
  btn.disabled = true;
  try {
    const res = await fetch(
      `/api/documents/${target.docId}/parts/${target.partId}/export/text-layer-pdf`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      }
    );
    const data = await res.json();
    if (!res.ok) {
      showToast(data.error || "굽기에 실패했습니다.", "error");
      return;
    }
    if (data.baked_pages > 0) {
      showToast(
        `${data.baked_pages}쪽을 구웠습니다 ` +
          `(${Math.round(data.size_bytes / 1024)}KB).`,
        "success"
      );
    }
    (data.warnings || []).forEach((w) => showToast(w, "info"));
    await _refreshExtractExport();
  } catch (e) {
    showToast(`굽기 중 오류: ${e.message}`, "error");
  } finally {
    btn.disabled = false;
  }
}

/** 추출 패널의 버튼·입력을 초기화한다. */
function initExtractPanel() {
  const run = document.getElementById("extract-run-ocr");
  if (run) run.addEventListener("click", _runExtractOcr);

  const imp = document.getElementById("extract-import-text");
  if (imp) imp.addEventListener("click", _importExtractText);

  const bake = document.getElementById("extract-embed-btn");
  if (bake) bake.addEventListener("click", _embedExtractPdf);

  const refresh = document.getElementById("extract-refresh-btn");
  if (refresh) refresh.addEventListener("click", () => refreshExtractPanel(true));

  const pages = document.getElementById("extract-pages-input");
  if (pages) pages.addEventListener("input", _updateExtractCost);
}
