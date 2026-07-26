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
  // 다른 문헌으로 옮겼다. 이전 문헌의 쪽 정보를 검수 바가 쓰면 안 된다.
  resetReviewCache();
  // 쪽 범위도 비운다 — 앞 문헌에서 지정한 쪽이 남아 있으면 엉뚱한 쪽이
  // 대상이 되고, «지정한 5쪽은 이미 처리됐습니다» 같은 안내가 이유 없이 뜬다.
  const pagesInput = document.getElementById("extract-pages-input");
  if (pagesInput) pagesInput.value = "";

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
      await _refreshExtractOverview();
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

/** 만들어 둔 PDF가 있는지 확인해 내려받기 링크를 갱신한다. */
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
/**
 * 지정한 쪽으로 이동한다.
 *
 * 왜 함수로 감싸는가:
 *   예전에는 호출부마다 `typeof goToPage === "function"`으로 감쌌는데,
 *   **그 함수가 실제로 없었다.** 가드가 오류를 삼켜 버려서 버튼을 눌러도
 *   아무 일이 일어나지 않았고 콘솔에도 아무것도 남지 않았다.
 *   없으면 조용히 넘어가는 대신 **화면에 알린다.**
 */
function _navigateToPage(pageNumber) {
  if (typeof goToPage !== "function") {
    showToast(
      "쪽 이동 기능을 찾지 못했습니다. 페이지를 새로 고쳐 보세요.",
      "error"
    );
    return false;
  }
  return goToPage(pageNumber);
}


function _formatPageList(pages, limit = 8) {
  /** 쪽 번호 목록을 «1, 2, 3쪽 외»처럼 줄여 적는다. */
  const shown = pages.slice(0, limit).join(", ");
  return `${shown}쪽${pages.length > limit ? " 외" : ""}`;
}

async function _refreshExtractPending() {
  const box = document.getElementById("extract-pending");
  const target = _extractTarget();
  if (!box || !target) return;

  // 쪽 범위는 두 갈래 모두에 적용된다. 이것을 빼먹으면 «12쪽만 다시»라고
  // 지정해 놓고 «15쪽 전체가 돕니다»라는 안내를 보게 된다 — 비용이 걸린
  // 자리에서 부풀린 숫자를 보여 주는 셈이다.
  const input = document.getElementById("extract-pages-input");
  const range = parsePageRange(input ? input.value : "", _extractPageCount());
  const rangeNote = range ? ` (지정한 범위 ${_formatPageList(range)})` : "";

  // 「이미 처리한 쪽도 다시」를 켰으면 재개 판정이 통째로 꺼지므로
  // 서버에 물어볼 것 없이 대상이 곧 실행 대상이다.
  const force = document.getElementById("extract-force-redo");
  if (force && force.checked) {
    const count = range ? range.length : _extractPageCount();
    box.textContent = count
      ? `«이미 처리한 쪽도 다시»가 켜져 있어 쪽 ${count}개가 다시 돕니다${rangeNote}.`
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

    // 서버는 권 전체를 기준으로 답한다. 쪽 범위를 지정했으면 그 안으로 좁힌다.
    const inRange = (p) => !range || range.includes(p);
    const todo = (data.todo_pages || []).filter(inRange);
    const stale = (data.stale_pages || []).filter(inRange);
    const willRun = todo.length + stale.length;

    if (willRun === 0) {
      box.textContent = range
        ? `지정한 ${_formatPageList(range)}은 이미 처리됐습니다. ` +
          "다시 돌리려면 «이미 처리한 쪽도 다시»를 켜세요."
        : `쪽 ${data.page_count}개를 모두 처리했습니다. 실행해도 도는 쪽이 없습니다.`;
      box.className = "extract-pending extract-diag-ok";
      box.hidden = false;
      return;
    }

    // 내역은 «개수»가 아니라 **쪽 번호**로 적는다.
    //
    // 왜: 한국어에서 «쪽»이 개수 단위이자 번호 단위라 «3쪽 미처리»가
    // «세 쪽이 미처리»로도 «3쪽이 미처리»로도 읽힌다. 쪽 범위를 비워 둔
    // 상태에서 «실행하면 3쪽이 돕니다 — 3쪽 미처리»가 뜨면 어느 쪽이
    // 도는지 오히려 헷갈린다. 번호를 그대로 보여 주면 그 애매함이 없다.
    const parts = [];
    // 라벨은 «쪽»을 겹쳐 쓰지 않는다 — _formatPageList가 이미 «쪽»으로 끝난다.
    if (todo.length) parts.push(`아직 안 함: ${_formatPageList(todo)}`);
    if (stale.length) {
      parts.push(`레이아웃 수정: ${_formatPageList(stale)}`);
    }
    box.textContent = `실행하면 쪽 ${willRun}개가 돕니다${rangeNote} — ${parts.join(" · ")}`;
    box.className = "extract-pending extract-diag-warn";
    box.hidden = false;
  } catch (e) {
    // 예상 규모를 못 보여 줘도 실행 자체는 막지 않는다.
    box.hidden = true;
  }
}

/* ─── 쪽별 결과 훑어보기 ─────────────────────────
 *
 * 왜 필요한가:
 *   부분 재-OCR은 «어느 쪽이 나쁜지»를 이미 알고 있다는 전제 위에 서 있다.
 *   그런데 텍스트를 보는 경로가 쪽 단위뿐이라, 15쪽이면 15번 눌러 봐야
 *   알 수 있고 300쪽이면 사실상 불가능하다. 여기서 한눈에 훑는다.
 *
 * 판정을 어디까지 믿을 것인가:
 *   «글자 적음»은 틀렸다는 뜻이 아니다. 표지·간지·참고문헌 쪽은 원래
 *   글자가 적다. 그래서 실제 글자 수와 본문 앞머리를 함께 보여 주고
 *   **판단은 사람이 한다.** 표시는 «봐 두라»는 뜻이다.
 */

const _EXTRACT_FLAG_LABEL = {
  not_run: "안 돌림",
  empty: "결과 없음",
  few_chars: "글자 적음",
  no_position: "좌표 없음",
};

/** 이 쪽을 눈여겨봐야 하는가 (좌표 없음은 정상일 수 있어 뺀다). */
function _isSuspectPage(page) {
  return (page.flags || []).some((f) => f !== "no_position");
}

/* ─── 쪽별 검수 기록 ─────────────────────────────
 *
 * 왜 필요한가:
 *   결과에 확신이 있으면 추출 화면에서 바로 텍스트 레이어 PDF를 만드는 것이
 *   가장 편하다. 그런데 그 «확신»은 쪽마다 원본과 대조해 봐야 생긴다.
 *   어디까지 봤는지 기억에 의존하면 300쪽에서는 반드시 빠뜨린다.
 *
 * 왜 localStorage인가:
 *   확인 여부는 **사람의 작업 상태**이지 문헌의 데이터가 아니다. 저장소에
 *   넣으려면 스키마를 고쳐야 하고(둘 다 additionalProperties: false)
 *   교환 형식(D-018)에 영향이 간다. 작업 프로필도 같은 이유로
 *   localStorage에 둔다(D-055).
 *
 * 왜 글자 수를 함께 저장하는가:
 *   확인한 뒤 그 쪽을 다시 OCR 하면 내용이 달라진다. 확인 표시가 그대로
 *   남으면 **보지 않은 결과를 봤다고 기록한 셈**이 된다. 확인 당시의
 *   글자 수를 적어 두고 달라지면 자동으로 풀리게 한다.
 */

function _reviewKey(target) {
  return `ctb.reviewed.${target.docId}.${target.partId}`;
}

function _loadReviewed(target) {
  try {
    return JSON.parse(localStorage.getItem(_reviewKey(target)) || "{}");
  } catch (e) {
    return {};
  }
}

function _saveReviewed(target, map) {
  try {
    localStorage.setItem(_reviewKey(target), JSON.stringify(map));
  } catch (e) {
    // 저장에 실패해도 화면은 계속 동작해야 한다 (사생활 모드 등).
  }
}

/** 이 쪽이 «확인됨»인가 — 확인 당시와 글자 수가 같을 때만. */
function _isReviewed(map, page) {
  const at = map[String(page.page)];
  return at !== undefined && at === page.chars;
}

/* ─── 교정 탭의 검수 바 ───────────────────────────
 *
 * 왜 교정 탭에 두는가:
 *   검수는 «원본 이미지와 전체 텍스트를 나란히 놓고 보는» 일이고, 그 화면은
 *   교정 탭뿐이다. 그런데 확인 표시가 추출 패널(열람 탭)에만 있으면
 *   쪽마다 «교정 탭에서 보고 → 열람 탭에서 체크 → 다시 교정 탭»이 되어
 *   15쪽에 탭 전환이 30번 일어난다. 그러면 아무도 검수하지 않는다.
 *
 *   그래서 확인 표시를 검수하는 자리로 가져온다. 추출 패널의 목록은
 *   시작점과 진행률을 보여 주는 대시보드로 남는다.
 *
 * 왜 «다음 쪽»이 아니라 «다음 미확인 쪽»인가:
 *   이미 본 쪽을 다시 지나가면 흐름이 끊긴다. 남은 것만 이어서 보게 한다.
 */

/** 검수 바가 쓰는 쪽별 정보. 글자 수 기준을 훑어보기와 하나로 유지한다. */
let _reviewPages = null;

async function _loadReviewPages(target, { force = false } = {}) {
  if (_reviewPages && !force) return _reviewPages;
  try {
    const res = await fetch(
      `/api/documents/${target.docId}/parts/${target.partId}/ocr/overview`
    );
    if (!res.ok) return null;
    _reviewPages = (await res.json()).pages || [];
    return _reviewPages;
  } catch (e) {
    return null;
  }
}

/** 다른 문헌으로 옮기면 이전 문헌의 쪽 정보를 쓰지 않도록 버린다. */
function resetReviewCache() {
  _reviewPages = null;
}

/**
 * 교정 탭의 검수 바를 현재 쪽에 맞춰 갱신한다.
 *
 * 입력: pageNum — 지금 교정 탭이 보고 있는 쪽.
 * 교정 탭이 쪽을 열 때마다 부른다 (correction-editor.js).
 * 추출 모드가 아니면 아무것도 하지 않는다 — 고서 흐름에는 이 개념이 없다.
 */
async function refreshCorrectionReviewBar(pageNum) {
  const bar = document.getElementById("corr-review-bar");
  if (!bar) return;

  const isExtract =
    typeof currentProfile !== "undefined" && currentProfile === "extract";
  const target = _extractTarget();
  if (!isExtract || !target || !pageNum) {
    bar.hidden = true;
    return;
  }

  const pages = await _loadReviewPages(target);
  if (!pages || !pages.length) {
    bar.hidden = true;
    return;
  }

  const page = pages.find((p) => p.page === pageNum);
  if (!page) {
    bar.hidden = true;
    return;
  }

  const reviewed = _loadReviewed(target);
  const doneCount = pages.filter((p) => _isReviewed(reviewed, p)).length;
  const remaining = pages.filter((p) => !_isReviewed(reviewed, p));

  const progress = document.getElementById("corr-review-progress");
  progress.textContent = `검수 ${doneCount}/${pages.length}쪽`;
  bar.classList.toggle("corr-review-complete", remaining.length === 0);

  const check = document.getElementById("corr-review-checkbox");
  check.checked = _isReviewed(reviewed, page);
  check.onchange = () => {
    const map = _loadReviewed(target);
    if (check.checked) {
      // 훑어보기와 같은 값을 넣는다. 다르면 표시가 서로 어긋난다.
      map[String(page.page)] = page.chars;
    } else {
      delete map[String(page.page)];
    }
    _saveReviewed(target, map);
    refreshCorrectionReviewBar(pageNum);
    // 열람 탭으로 돌아갔을 때 목록이 이미 맞아 있게 해 둔다.
    _refreshExtractOverview();
  };

  const next = document.getElementById("corr-review-next");
  // 지금 쪽 다음부터 찾고, 없으면 앞쪽에서 다시 찾는다(한 바퀴).
  const after = remaining.find((p) => p.page > pageNum);
  const target_ = after || remaining.find((p) => p.page !== pageNum);
  if (!target_) {
    next.textContent = "모두 확인했습니다";
    next.disabled = true;
    next.onclick = null;
  } else {
    next.textContent = `다음 미확인 ${target_.page}쪽 →`;
    next.disabled = false;
    next.onclick = async () => {
      // 다음 쪽도 L4가 비어 있을 수 있다. 이동 전에 채운다.
      try {
        await fetch(
          `/api/documents/${target.docId}/parts/${target.partId}` +
            `/ocr/fill-text?pages=${target_.page}`,
          { method: "POST" }
        );
      } catch (e) {
        // 채우지 못해도 이동은 막지 않는다.
      }
      _navigateToPage(target_.page);
    };
  }

  bar.hidden = false;
}

async function _refreshExtractOverview() {
  const box = document.getElementById("extract-overview");
  const list = document.getElementById("extract-overview-list");
  const hint = document.getElementById("extract-overview-hint");
  const summary = document.getElementById("extract-overview-summary");
  const target = _extractTarget();
  if (!box || !list || !target) return;

  try {
    const res = await fetch(
      `/api/documents/${target.docId}/parts/${target.partId}/ocr/overview`
    );
    const data = await res.json();
    if (!res.ok || !(data.pages || []).length) {
      box.hidden = true;
      return;
    }

    const reviewed = _loadReviewed(target);
    const doneCount = data.pages.filter((p) => _isReviewed(reviewed, p)).length;

    const suspect = data.pages.filter(_isSuspectPage);
    summary.textContent =
      `쪽별 검수 — ${doneCount}/${data.pages.length}쪽 확인` +
      (suspect.length ? ` · 살펴볼 쪽 ${suspect.length}개` : "");
    // 살펴볼 쪽이 있거나 아직 다 못 봤으면 접힌 채로 두지 않는다.
    if (
      (suspect.length || doneCount < data.pages.length) &&
      !box.dataset.userToggled
    ) {
      box.open = true;
    }

    // 좌표 없음이 «글자가 나온 모든 쪽»에 해당하면 그것은 이 쪽의 문제가
    // 아니라 엔진 특성이다(LLM Vision은 bbox를 주지 않는다). 쪽마다 붙이면
    // 똑같은 표시가 열댓 개 떠서 정작 봐야 할 표시가 묻힌다. 한 번만 말한다.
    //
    // 빈 쪽은 애초에 좌표를 가질 줄이 없으므로 판정에서 뺀다. 넣으면
    // 빈 쪽이 하나만 있어도 이 축약이 꺼진다.
    const scored = data.pages.filter((p) => p.lines > 0);
    const allNoPosition =
      scored.length > 0 &&
      scored.every((p) => (p.flags || []).includes("no_position"));

    // 여기 표시는 «통계로 잡히는 것»뿐이다. 몇 글자 오독처럼 글자 수가
    // 정상인 잘못은 원본과 대조해야만 보인다. 그 사실을 숨기면 사용자는
    // «표시 없는 쪽 = 문제 없는 쪽»으로 오해한다.
    const hints = [
      `글자 수 중앙값 ${data.median_chars}자.`,
      "표시가 없어도 틀렸을 수 있습니다 — 「대조」로 원본과 나란히 보세요.",
    ];
    if (suspect.length) {
      hints.push("표지·참고문헌 쪽은 원래 글자가 적으니 본문을 보고 판단하세요.");
    }
    if (allNoPosition) {
      hints.push(
        "이 엔진은 글자 위치를 주지 않아 모든 쪽이 «좌표 없음»입니다 " +
          "(PaddleOCR를 설치하면 위치를 찾아 줍니다)."
      );
    }
    hint.textContent = hints.join(" ");

    list.innerHTML = "";
    for (const page of data.pages) {
      list.appendChild(_buildOverviewRow(page, { target, reviewed, allNoPosition }));
    }
    box.hidden = false;
    _refreshReviewStatus(data.pages, reviewed);
  } catch (e) {
    box.hidden = true;
  }
}

/**
 * 훑어보기 한 행을 만든다.
 *
 * 행 하나에서 세 갈래로 갈 수 있어야 한다. 발견하고도 갈 곳이 없으면
 * 결국 «다시 OCR»만 반복하게 되는데, 같은 엔진·같은 레이아웃이면
 * 결과도 대체로 같다.
 *
 *   대조   → 교정 탭. 원본 이미지 옆에서 글자를 직접 고친다.
 *            몇 글자 오독은 이쪽이 빠르고 확실하다.
 *   영역   → 레이아웃 탭. 2단·표처럼 영역이 잘못 잡힌 경우.
 *   행 클릭 → 쪽 범위에 넣는다. 엔진·모델을 바꿔 다시 돌릴 때.
 */
function _buildOverviewRow(page, { target, reviewed, allNoPosition }) {
  const row = document.createElement("div");
  row.className = "extract-overview-row";
  if (_isSuspectPage(page)) row.classList.add("extract-overview-suspect");
  if (_isReviewed(reviewed, page)) row.classList.add("extract-overview-done");

  const head = document.createElement("div");
  head.className = "extract-overview-head";

  // 확인 표시. 라벨로 감싸 체크박스 옆 글자를 눌러도 켜지게 한다.
  const checkLabel = document.createElement("label");
  checkLabel.className = "extract-overview-check";
  checkLabel.title = "이 쪽을 확인했다고 표시합니다";
  const check = document.createElement("input");
  check.type = "checkbox";
  check.checked = _isReviewed(reviewed, page);
  check.addEventListener("click", (e) => e.stopPropagation());
  check.addEventListener("change", () => {
    const map = _loadReviewed(target);
    if (check.checked) {
      // 확인 당시의 글자 수를 함께 적는다. 다시 OCR 해서 내용이 바뀌면
      // 이 값이 어긋나 확인이 저절로 풀린다.
      map[String(page.page)] = page.chars;
      row.classList.add("extract-overview-done");
    } else {
      delete map[String(page.page)];
      row.classList.remove("extract-overview-done");
    }
    _saveReviewed(target, map);
    _refreshExtractOverview();
  });
  checkLabel.appendChild(check);
  head.appendChild(checkLabel);

  const num = document.createElement("span");
  num.className = "extract-overview-page";
  num.textContent = `${page.page}쪽`;
  head.appendChild(num);

  const stat = document.createElement("span");
  stat.className = "extract-overview-stat";
  stat.textContent = `${page.lines}줄 · ${page.chars}자`;
  head.appendChild(stat);

  for (const flag of page.flags || []) {
    // 위에서 한 번에 안내했으므로 쪽마다 반복하지 않는다.
    if (flag === "no_position" && allNoPosition) continue;
    const tag = document.createElement("span");
    tag.className = `extract-overview-flag flag-${flag}`;
    tag.textContent = _EXTRACT_FLAG_LABEL[flag] || flag;
    head.appendChild(tag);
  }

  const actions = document.createElement("span");
  actions.className = "extract-overview-actions";

  // 되돌릴 수 있는 쪽에만 버튼을 둔다. 다시 돌린 적 없는 쪽에는 뜨지 않는다.
  if (page.has_backup) {
    const undo = document.createElement("button");
    undo.type = "button";
    undo.className = "extract-overview-action extract-overview-undo";
    undo.textContent = "OCR 되돌리기";
    undo.title =
      "새로 돌린 결과가 이전만 못할 때 쓰세요. " +
      "다시 돌리기 직전으로 되돌립니다 (교정도 함께). " +
      "교정만 되돌리려면 교정 탭의 교정 목록을 쓰세요.";
    undo.addEventListener("click", async (e) => {
      e.stopPropagation();
      await _restoreExtractPage(target, page.page);
    });
    actions.appendChild(undo);
  }

  for (const [label, mode, title] of [
    ["대조", "correction", "교정 탭에서 원본과 나란히 보고 고칩니다"],
    ["영역", "layout", "레이아웃 탭에서 읽을 영역을 확인·수정합니다"],
  ]) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "extract-overview-action";
    btn.textContent = label;
    btn.title = title;
    btn.addEventListener("click", (e) => {
      e.stopPropagation(); // 행 클릭(쪽 범위 편입)과 겹치지 않게 한다
      _openPageInTab(page.page, mode);
    });
    actions.appendChild(btn);
  }
  head.appendChild(actions);
  row.appendChild(head);

  const preview = document.createElement("div");
  preview.className = "extract-overview-preview";
  // 미리보기가 비면 사용자는 «안 나온 건지 화면이 깨진 건지» 알 수 없다.
  preview.textContent = page.preview || "— 텍스트가 없습니다 —";
  row.appendChild(preview);

  row.addEventListener("click", () => _focusExtractPage(page.page));
  return row;
}

/**
 * 한 쪽을 **OCR 다시 돌리기 직전** 상태로 되돌린다.
 *
 * 무엇에 쓰는 것인가 — **새로 돌린 결과가 이전만 못할 때 하나뿐이다.**
 * 다시 돌리면 그 쪽의 교정 텍스트가 새 OCR 결과로 덮이므로, 새 결과가
 * 나쁘면 이전 것(교정 포함)으로 물러설 길이 필요하다.
 *
 * 교정만 취소하려는 것이라면 이 버튼이 아니다 — 교정 탭의 교정 목록에서
 * 항목별 삭제나 «모두 삭제»를 쓰면 된다. 그쪽이 더 세밀하고 차수 제한도 없다.
 *
 * OCR 결과(L2)와 교정 텍스트(L4)를 함께 되돌린다 — 배치가 둘 다 덮어쓰므로
 * 하나만 되돌리면 «OCR은 예전 것인데 교정은 사라진» 어긋난 상태가 된다.
 */
async function _restoreExtractPage(target, pageNumber) {
  try {
    const res = await fetch(
      `/api/documents/${target.docId}/parts/${target.partId}` +
        `/ocr/restore?pages=${pageNumber}`,
      { method: "POST" }
    );
    const data = await res.json();
    if (!res.ok) {
      showToast(data.error || "되돌리지 못했습니다.", "error");
      return;
    }
    if (!(data.restored || []).length) {
      showToast(`${pageNumber}쪽에는 되돌릴 OCR 실행이 없습니다.`, "info");
      return;
    }
    showToast(
      `${pageNumber}쪽을 다시 돌리기 직전으로 되돌렸습니다. 다시 누르면 원래대로.`,
      "success"
    );
    await _refreshExtractOverview();
    await _refreshExtractPending();
    // 지금 그 쪽을 보고 있으면 화면도 다시 읽는다.
    if (viewerState && viewerState.pageNum === pageNumber) {
      if (typeof loadPageText === "function") {
        loadPageText(target.docId, target.partId, pageNumber);
      }
      if (typeof loadPageCorrections === "function") {
        loadPageCorrections(target.docId, target.partId, pageNumber);
      }
    }
  } catch (err) {
    showToast(`되돌리기 중 오류: ${err.message}`, "error");
  }
}


/**
 * 그 쪽으로 이동한 뒤 지정한 탭을 연다.
 *
 * 왜 탭 버튼을 클릭하는가:
 *   _switchMode()를 직접 부르면 탭 하이라이트가 따라오지 않는다. 그 처리는
 *   initModeBar()의 클릭 핸들러 안에 있다. 버튼을 실제로 누르면 기존 경로를
 *   그대로 타므로 두 곳이 어긋날 일이 없다.
 */
async function _openPageInTab(pageNumber, mode) {
  const tab = document.querySelector(`.mode-tab[data-mode="${mode}"]`);
  if (!tab || tab.hidden) {
    showToast(`«${mode}» 탭을 찾을 수 없습니다.`, "error");
    return;
  }

  // 교정 탭은 L4를 읽는데, 배치 OCR 이전에 만든 문헌은 L4가 비어 있다.
  // 그대로 보내면 «대조»를 눌렀는데 빈 화면이 나온다. 그 쪽만 미리 채운다.
  // (이미 있으면 건드리지 않으므로 손으로 고친 교정은 안전하다.)
  if (mode === "correction") {
    const target = _extractTarget();
    if (target) {
      try {
        await fetch(
          `/api/documents/${target.docId}/parts/${target.partId}` +
            `/ocr/fill-text?pages=${pageNumber}`,
          { method: "POST" }
        );
      } catch (e) {
        // 채우지 못해도 탭 이동 자체는 막지 않는다.
      }
    }
  }

  _navigateToPage(pageNumber);
  tab.click();
}

/**
 * PDF를 만들기 전에 «쪽마다 확인이 끝났는가»를 알린다.
 *
 * 산출물은 서지 관리 도구로 넘어가 원본을 대체한다. 확신 없이 내보내면
 * 잘못된 텍스트가 그대로 굳는다. 막지는 않되 사실은 알린다.
 */
function _refreshReviewStatus(pages, reviewed) {
  const box = document.getElementById("extract-review-status");
  if (!box) return;
  if (!pages || !pages.length) {
    box.hidden = true;
    return;
  }

  const notDone = pages.filter((p) => !_isReviewed(reviewed, p));
  if (!notDone.length) {
    box.textContent = `${pages.length}쪽을 모두 확인했습니다.`;
    box.className = "extract-review-status extract-diag-ok";
  } else {
    box.textContent =
      `아직 확인하지 않은 쪽이 ${notDone.length}개 있습니다 ` +
      `(${_formatPageList(notDone.map((p) => p.page), 6)}). ` +
      "위 «쪽별 검수»에서 확인한 뒤 만드는 것을 권합니다.";
    box.className = "extract-review-status extract-diag-warn";
  }
  box.hidden = false;
}

/**
 * 그 쪽으로 이동하고 쪽 범위에 넣는다.
 *
 * 훑어보다 «이 쪽이 이상하다»를 발견한 순간 바로 다시 돌릴 수 있어야 한다.
 * 쪽 번호를 외웠다가 아래 칸에 옮겨 적게 만들면 그 사이에 틀린다.
 */
function _focusExtractPage(pageNumber) {
  _navigateToPage(pageNumber);

  const input = document.getElementById("extract-pages-input");
  if (input) {
    const current = parsePageRange(input.value, _extractPageCount()) || [];
    // 이미 들어 있으면 빼서, 누를 때마다 켜고 끌 수 있게 한다.
    const next = current.includes(pageNumber)
      ? current.filter((p) => p !== pageNumber)
      : [...current, pageNumber].sort((a, b) => a - b);
    input.value = next.join(", ");
    _updateExtractCost();
    _refreshExtractPending();
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
          // OCR이 끝나고 **다른 단계**가 시작된 것이다. 그 사실이 보여야 한다 —
          // 진행 막대만 100%로 두면 «끝났는데 멈춘 것»처럼 보인다.
          // 검출이 쪽당 8초쯤 걸려 15쪽이면 2분 가까이 이 화면에 머문다.
          fill.style.width = "100%";
          text.textContent =
            `OCR 완료. 이제 검색되는 PDF를 만듭니다 — ${evt.total || ""}쪽에서 ` +
            "글자 위치를 찾는 중이라 1~2분 걸립니다.";
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
      await _refreshExtractOverview();
      // 지금 보고 있는 쪽의 텍스트를 다시 읽어 화면에 반영한다.
      if (typeof loadPageText === "function") {
        loadPageText(target.docId, target.partId, viewerState.pageNum);
      }
      // 레이아웃도 함께 다시 읽는다.
      //
      // 왜: 배치는 쪽마다 **L3 전면 블록을 새로 만든다**(D-055).
      // 그런데 onPageChanged는 레이아웃 탭이 활성일 때만 다시 읽고,
      // 배치는 열람 탭에서 도니 그 경로를 타지 않는다. 그래서 배치 뒤
      // 레이아웃 탭으로 가면 **블록이 없던 시절의 화면**이 남아 있었다.
      if (typeof loadPageLayout === "function") {
        loadPageLayout(target.docId, target.partId, viewerState.pageNum);
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

/** 검색되는 PDF를 다시 만든다 (교정 후 갱신용). */
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
      showToast(data.error || "PDF를 만들지 못했습니다.", "error");
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
    showToast(`PDF 만들기 중 오류: ${e.message}`, "error");
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
  if (pages) {
    pages.addEventListener("input", () => {
      _updateExtractCost();
      // 쪽 범위도 «몇 쪽이 도는가»를 바꾼다. 이것을 빼면 범위를 좁혀 놓고도
      // 예상 규모는 권 전체 기준으로 남아 실제보다 부풀려 보인다.
      _refreshExtractPending();
    });
  }

  // 강제 재실행을 켜고 끄면 «몇 쪽이 도는가»가 달라진다. 그 자리에서 바꾼다.
  const force = document.getElementById("extract-force-redo");
  if (force) force.addEventListener("change", _refreshExtractPending);

  // 사용자가 직접 접었으면 다음부터 자동으로 펼치지 않는다.
  const overview = document.getElementById("extract-overview");
  if (overview) {
    overview.addEventListener("toggle", () => {
      overview.dataset.userToggled = "1";
    });
  }
}
