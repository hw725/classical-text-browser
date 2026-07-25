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

    if (!ocrSection.hidden) {
      await _loadExtractEngines();
      await _refreshExtractPending();
    }
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

/**
 * LLM Vision용 모델 목록을 채운다.
 *
 * 왜 모델을 보여 주는가:
 *   LLM Vision은 5단 폴백이라 어느 프로바이더가 잡힐지 화면에 드러나지 않는다.
 *   실제로 «무료 로컬로 돌 것»이라 여겼는데 유료 API가 처리하고 있던 일이 있었다.
 *   무엇으로 도는지 보이고, 원하면 고를 수 있어야 한다.
 */
async function _loadExtractModels() {
  const select = document.getElementById("extract-model-select");
  if (!select || select.dataset.loaded === "1") return;

  try {
    const res = await fetch("/api/llm/models");
    const models = await res.json();
    select.innerHTML = "";

    const auto = document.createElement("option");
    auto.value = "";
    auto.textContent = "자동 (폴백 순서대로)";
    select.appendChild(auto);

    for (const m of Array.isArray(models) ? models : []) {
      // 비전이 되는 모델만 — OCR은 이미지를 봐야 한다.
      if (!m.vision || !m.available) continue;
      const opt = document.createElement("option");
      opt.value = `${m.provider}:${m.model}`;
      // 과금 방식을 이름에 함께 적는다. «free»만 보고 공짜로 오해하면 안 된다.
      const billing =
        m.provider === "ollama"
          ? (m.model || "").includes("cloud") ? "구독 한도" : "로컬 무료"
          : m.provider === "openai_oauth" ? "구독 한도" : "종량 과금";
      opt.textContent = `${m.display || m.model} — ${billing}`;
      select.appendChild(opt);
    }
    select.dataset.loaded = "1";
  } catch (e) {
    console.warn("[ExtractPanel] 모델 목록을 불러오지 못했습니다:", e);
  }
}

/** 선택한 엔진이 한글을 못 읽으면 경고를 보여 준다. */
function _updateEngineWarning() {
  const select = document.getElementById("extract-engine-select");
  const warn = document.getElementById("extract-engine-warn");
  if (!select || !warn) return;
  // LLM Vision일 때만 모델을 고르게 한다 (다른 엔진은 모델 개념이 없다).
  const modelRow = document.getElementById("extract-model-row");
  if (modelRow) {
    const isLlm = select.value === "llm_vision";
    modelRow.hidden = !isLlm;
    if (isLlm) _loadExtractModels();
  }

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

/**
 * 이번 실행에서 어느 모델로 얼마를 썼는지 보여 준다.
 *
 * 왜 금액만으로 부족한가:
 *   구독형(Ollama 클라우드·OpenAI OAuth)은 비용이 0으로 기록된다.
 *   «$0.00»만 띄우면 공짜로 오해하지만 실제로는 계정 한도를 쓰고 있다.
 *   게다가 두 서비스 모두 남은 한도를 API로 알려 주지 않는다
 *   (실측: 응답 헤더에 rate limit 정보 없음). 그래서 과금 방식에 따라
 *   문구를 달리하고, 한도는 제공자 대시보드에서 보라고 안내한다.
 */
function _showUsage(usage) {
  const box = document.getElementById("extract-usage");
  if (!box) return;
  if (!usage || !usage.calls) {
    box.hidden = true;
    return;
  }

  const cls = {
    metered: "extract-usage-metered",
    subscription: "extract-usage-subscription",
    free: "extract-usage-free",
  }[usage.billing] || "";
  box.className = `extract-usage ${cls}`;

  const models = (usage.models || []).join(", ") || "(알 수 없음)";
  const tokens =
    usage.tokens_in || usage.tokens_out
      ? ` · 토큰 ${(usage.tokens_in || 0).toLocaleString()}/${(usage.tokens_out || 0).toLocaleString()}`
      : "";

  box.textContent = `${models} · ${usage.calls}회 호출${tokens}
${usage.note || ""}`;
  box.hidden = false;
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

/**
 * 실행하기 전에 «몇 쪽이 실제로 도는가»를 보여 준다.
 *
 * 왜 필요한가:
 *   OCR 한 쪽마다 LLM 호출이 나간다. 특히 레이아웃을 몇 쪽만 고친 뒤
 *   다시 실행할 때, 전체 300쪽이 다시 도는 것인지 고친 1쪽만 도는 것인지가
 *   버튼을 누르기 전에 보여야 한다.
 */
async function _refreshExtractPending() {
  const box = document.getElementById("extract-pending");
  const target = _extractTarget();
  if (!box || !target) return;

  // 「이미 처리한 쪽도 다시」를 켰으면 재개 판정이 통째로 꺼지므로
  // 예상 규모가 달라진다. 남은 쪽 수를 그대로 보여 주면 거짓말이 된다.
  const force = document.getElementById("extract-force-redo");
  if (force && force.checked) {
    const total = _extractPageCount();
    box.textContent = total
      ? `«이미 처리한 쪽도 다시»가 켜져 있어 ${total}쪽 전체가 다시 돕니다.`
      : "«이미 처리한 쪽도 다시»가 켜져 있어 전체가 다시 돕니다.";
    box.className = "extract-pending extract-diag-scan";
    box.hidden = false;
    return;
  }

  try {
    const res = await fetch(
      `/api/documents/${target.docId}/parts/${target.partId}/ocr/pending`
    );
    const data = await res.json();
    if (!res.ok) {
      box.hidden = true;
      return;
    }

    if (data.will_run === 0) {
      box.textContent = `${data.page_count}쪽 모두 처리됐습니다. 실행해도 도는 쪽이 없습니다.`;
      box.className = "extract-pending extract-diag-ok";
      box.hidden = false;
      return;
    }

    const parts = [];
    if (data.todo) parts.push(`${data.todo}쪽 미처리`);
    if (data.stale) {
      // 어느 쪽이 다시 도는지 번호까지 보여 준다. 사용자가 방금 고친 쪽과
      // 일치하는지 눈으로 확인할 수 있어야 한다.
      const shown = data.stale_pages.slice(0, 8).join(", ");
      const more = data.stale_pages.length > 8 ? " 외" : "";
      parts.push(`${data.stale}쪽은 레이아웃을 고쳐 다시 (${shown}쪽${more})`);
    }
    box.textContent = `실행하면 ${data.will_run}쪽이 돕니다 — ${parts.join(" · ")}`;
    box.className = "extract-pending extract-diag-warn";
    box.hidden = false;
  } catch (e) {
    // 예상 규모를 못 보여 줘도 실행 자체는 막지 않는다.
    box.hidden = true;
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

  // 「이미 처리한 쪽도 다시」를 켜면 재개 판정을 통째로 끈다.
  // 끄면(기본) 아직 안 한 쪽 + 레이아웃을 고친 쪽만 돈다.
  const force = document.getElementById("extract-force-redo");
  if (force && force.checked) body.skip_existing = false;

  // 모델을 골랐으면 그것으로 고정한다 (비우면 폴백 순서를 따른다).
  const modelSelect = document.getElementById("extract-model-select");
  if (modelSelect && modelSelect.value) {
    const [provider, ...rest] = modelSelect.value.split(":");
    body.force_provider = provider;
    body.force_model = rest.join(":");
  }

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
        } else if (evt.type === "redo") {
          // 레이아웃이 바뀌어 다시 도는 쪽이다. 왜 다시 도는지 그 자리에서
          // 보이지 않으면 «건너뛴다더니 왜 도나»가 된다.
          text.textContent = `${evt.page}쪽 다시 — ${evt.reason}`;
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
      // redone은 processed 안에 포함된 값이다. 따로 더하지 않고 괄호로 덧붙인다.
      if (done.redone) parts.push(`그중 ${done.redone}쪽은 레이아웃 수정분`);
      if (done.skipped) parts.push(`${done.skipped}쪽 건너뜀`);
      if (done.failed) parts.push(`${done.failed}쪽 실패`);
      if (done.embedded) {
        parts.push(`PDF ${done.embedded.embedded_pages}쪽에 텍스트 입힘`);
      }
      text.textContent = parts.join(" · ");
      showToast(parts.join(" · "), "success");
      _showUsage(done.usage);
      (done.warnings || []).forEach((w) => showToast(w, "info"));
      await _refreshExtractExport();
      await _refreshExtractPending();
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
    if (data.embedded_pages > 0) {
      const detected = data.detected_lines
        ? `, 줄 위치 검출 ${data.detected_lines}줄`
        : "";
      showToast(
        `${data.embedded_pages}쪽에 텍스트를 입혔습니다 ` +
          `(${Math.round(data.size_bytes / 1024)}KB${detected}).`,
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

  // 강제 재실행을 켜고 끄면 «몇 쪽이 도는가»가 달라진다. 그 자리에서 바꾼다.
  const force = document.getElementById("extract-force-redo");
  if (force) force.addEventListener("change", _refreshExtractPending);
}
