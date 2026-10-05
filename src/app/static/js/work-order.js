/**
 * 말로 작업 지시 (D-131) + 자동 스캔 (D-126, 2026-10-02 합침) — 복잡한 스캔본을
 * «스캔 → 말로 덧붙이기 → 계획 확인 → 적용 → 권 전체 OCR»로.
 *
 * 왜 이 창인가:
 *   돌아간 2쪽 펼침·세로쓰기·필사본·한글 번역이 섞인 사진본이 한 권에 들어 있으면, 쪽마다 회전·엔진·쓰기
 *   방향을 단추로 고르는 일이 끝나지 않는다. 코드가 잴 수 있는 것(회전·글의 종류)은 스캔이 재고,
 *   연구자만 아는 것(장 목록·쪽 이름표·판독 지침·스캔이 틀린 구간)은 말로 적게 한다.
 *
 * 왜 「판독 계획」 단추를 없애고 여기로 합쳤는가 (2026-10-02):
 *   두 입구가 같은 계획 칸(「권 전체 OCR」의 엔진 계획)을 덮어써, 나중에 누른 쪽이 앞의 것을 조용히
 *   지웠다. 이제 계획은 하나이고, 스캔은 그 계획에 **값으로 바로** 들어간다(서버의 plan_from_survey).
 *   스캔 결과를 글로 풀어 «말» 칸에 넣지 않는 이유: 코드가 잰 숫자를 LLM이 다시 칸으로 옮기면 쪽
 *   번호가 밀릴 수 있다 — 지어낼 수 없던 값이 지어낼 수 있는 값이 된다. 말은 그 계획을 base_plan으로
 *   받아 고칠 데만 고친다. 말이 측정과 다르게 바꾼 쪽은 표 위에 짚어 준다.
 *
 * 한 흐름(①②③):
 *   ① 자동 스캔(선택) → 계획 표에 바로(저장하지 않음)
 *   ② 말로 덧붙이기 → 「계획에 덧붙이기」(LLM 한 번, 저장하지 않음)
 *   ③ 계획 확인(누운 쪽은 「보기」로 확인, 아니면 「반대로」) → 「적용」(회전·지침·장 저장)
 *      → «권 전체 OCR»에 계획이 걸린다
 *   OCR이 끝난 뒤의 들이기·내려받기는 교정 탭 「들이기·내보내기」(export-view.js)에 있다.
 *
 * OCR 실행 자체는 기존 «권 전체 OCR»이 한다(진행 표시·중단·백업·L4 보호가 거기 있다).
 */

/* global viewerState, showToast, getLlmModelSelection, setOcrEnginePlan, syncSavedRotation, ocrState,
   renderPageThumb, _postSurveyStream */

// 계획은 **문헌·권에 묶는다** — 다른 문헌으로 옮긴 뒤 불러오기가 실패해도 앞 문헌의 계획이
// 남아 새 문헌에 적용되지 않게(Codex 지적 2026-09-30). key가 지금 대상과 다르면 계획을 쓰지 않는다.
// scan: 마지막 스캔의 쪽별 측정(per_page)과 표시(guess_pages·mixed_pages) — 말이 측정과 다르게
// 바꾼 쪽을 짚는 데 쓴다. 저장하지 않는다(창을 다시 열면 사라진다).
// gen: 계획이 바뀔 때마다 1씩 오르는 세대 번호 — 스캔·말 요청은 보낼 때의 세대를 기억했다가, 응답이
// 왔을 때 세대가 달라졌으면(그 사이 「반대로」·JSON 고침·다시 열기) 결과를 반영하지 않는다. 문헌 키만
// 견주면 같은 문헌 안에서 고친 계획을 늦게 온 응답이 덮는다(Codex 지적 2026-10-02).
// warn: 표 위의 경고(옮기지 못한 말·뺀 칸) — 상태로 들고 있어야 「반대로」로 표를 다시 그려도 남는다.
const workOrderState = {
  key: null,
  plan: null,
  pageCount: 0,
  engines: [],
  loading: false,
  scan: null,
  gen: 0,
  warn: { list: [], heading: "" },
};

/** 계획을 바꾼다 — 세대를 올리고 표를 다시 그린다. warn을 주면 경고를 바꾸고, 안 주면 지금 경고를 둔다. */
function _woSetPlan(plan, warnList, heading) {
  workOrderState.plan = plan;
  workOrderState.gen += 1;
  if (warnList !== undefined) workOrderState.warn = { list: warnList, heading: heading || "" };
  _woRenderPlan(plan);
}

// 종류 판정 기본 모델 — 벤치마크(2026-09-11, 표본 10쪽): 종류 정답 kimi-k3 7/10·gemma4 5/10·minimax-m3 5/10,
// 쪽당 1.5초로 gemma4(1.3초)와 같다. 앱 전체 기본(gemma4:cloud, D-114)과는 별개다.
const WO_SCAN_DEFAULT_MODEL = "ollama:kimi-k3:cloud";

function _woKey(t) {
  return t ? `${t.docId}|${t.partId}` : null;
}

function _woEsc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

function _woTarget() {
  const docId = viewerState?.docId;
  const partId = viewerState?.partId || "vol1";
  if (!docId) {
    showToast("문헌을 먼저 여세요.", "warning");
    return null;
  }
  return { docId, partId };
}

function _woStatus(text, kind = "") {
  const el = document.getElementById("wo-status");
  if (!el) return;
  el.textContent = text;
  el.dataset.kind = kind;
}

/** «1-3,7» → [1,2,3,7]. 계획의 pages는 서버가 닫힌 범위로 정리해 둔다(read_plan.pages_spec). */
function _woPages(spec) {
  const out = [];
  for (const piece of String(spec || "").split(",")) {
    const m = piece.trim().match(/^(\d+)(?:-(\d+))?$/);
    if (!m) continue;
    const a = Number(m[1]);
    const b = Number(m[2] ?? m[1]);
    for (let p = a; p <= b; p++) out.push(p);
  }
  return out;
}

/**
 * 말이 측정과 다르게 바꾼 쪽 — 스캔이 «확실히» 잰 회전(추정 아님)과 지금 계획의 회전이 다른 쪽.
 * 추정(누운 쪽의 90/270)은 180° 차이까지 같은 것으로 본다(코드가 그 둘을 못 가린다).
 * 출력: [{pages: "5-12", measured, planned}] — 연속 쪽을 묶는다.
 */
function _woConflicts(plan) {
  const scan = workOrderState.scan;
  if (!scan || !plan) return [];
  const planned = {};
  for (const r of plan.ranges || []) {
    if (r.skip) continue;
    for (const p of _woPages(r.pages)) planned[p] = r.rotation;
  }
  const rows = [];
  for (const row of scan.per_page || []) {
    if (row.target == null || planned[row.page] == null) continue;
    const diff = (planned[row.page] - row.target + 360) % 360;
    if (diff === 0 || (row.guess && diff === 180)) continue;
    const last = rows[rows.length - 1];
    if (last && last.to === row.page - 1 && last.measured === row.target && last.planned === planned[row.page]) {
      last.to = row.page;
    } else {
      rows.push({ from: row.page, to: row.page, measured: row.target, planned: planned[row.page] });
    }
  }
  return rows.map((r) => ({ ...r, pages: r.from === r.to ? `${r.from}` : `${r.from}-${r.to}` }));
}

/** ③ 계획을 표로 보인다 — 무엇이 어느 엔진·회전으로 돌지 «적용» 전에 보여야 한다. */
const WO_UNSUPPORTED_HEADING =
  "옮기지 못한 말 — 계획에 들어가지 않았습니다. 말을 고쳐 다시 옮기거나, 아래 JSON을 직접 고치세요.";

function _woRenderPlan(plan) {
  const unsupported = workOrderState.warn.list || [];
  const heading = workOrderState.warn.heading || WO_UNSUPPORTED_HEADING;
  const box = document.getElementById("wo-plan");
  const json = document.getElementById("wo-plan-json");
  if (!box) return;
  if (!plan) {
    box.innerHTML = '<div class="comp-split-note">아직 계획이 없습니다. ①에서 스캔하거나 ②에 책에 대해 아는 것을 적으세요.</div>';
    if (json) json.value = "";
    return;
  }
  const guess = new Set(workOrderState.scan?.guess_pages || []);
  const rows = (plan.ranges || [])
    .map((r, i) => {
      if (r.skip) return `<tr><td>${_woEsc(r.pages)}</td><td colspan="4">건너뜀</td><td>${_woEsc(r.note)}</td></tr>`;
      const isGuess = _woPages(r.pages).some((p) => guess.has(p));
      // 「보기」는 구간 첫 쪽을 이 회전으로 그린다. 「반대로」는 회전에 180°를 더한다 —
      // 누운 쪽의 90/270은 코드가 못 가리므로(추정) 사람이 그림을 보고 고른다
      const tools =
        `<button class="text-btn text-btn-sm" type="button" data-wo-thumb="${i}" title="이 구간의 첫 쪽을 이 회전으로 그려 봅니다">보기</button>` +
        `<button class="text-btn text-btn-sm" type="button" data-wo-flip="${i}" title="회전을 반대로(+180°) 바꿉니다">반대로</button>`;
      return (
        `<tr${isGuess ? ' class="wo-guess"' : ""}><td>${_woEsc(r.pages)}</td>` +
        `<td>${_woEsc(r.rotation)}°${isGuess ? ' <span class="wo-badge" title="누운 쪽의 90°·270°를 코드가 가리지 못했습니다 — 「보기」로 확인하세요">추정</span>' : ""}</td>` +
        `<td>${_woEsc(r.engine)}</td><td>${r.writing === "horizontal_ltr" ? "가로" : "세로"}</td>` +
        `<td class="wo-tools">${tools}</td><td>${_woEsc(r.note)}</td></tr>` +
        `<tr class="wo-thumb-row" data-wo-thumb-row="${i}" hidden><td colspan="6"><canvas class="wo-thumb"></canvas></td></tr>`
      );
    })
    .join("");
  const chapters = (plan.chapters || [])
    .map((c) => {
      const depth = Math.max(0, Math.min(5, (Number(c.level) || 1) - 1));
      return `<li>${"　".repeat(depth)}${_woEsc(c.title)} <span class="wo-dim">(${_woEsc(c.page)}쪽)</span></li>`;
    })
    .join("");
  const miss = unsupported.length
    ? `<div class="wo-unsupported"><b>${_woEsc(heading.split(" — ")[0])}</b> — ${_woEsc(heading.split(" — ").slice(1).join(" — "))}<ul>` +
      unsupported.map((u) => `<li>${_woEsc(u.said)} — ${_woEsc(u.why)}</li>`).join("") +
      "</ul></div>"
    : "";
  const conflicts = _woConflicts(plan);
  const conflictBox = conflicts.length
    ? '<div class="wo-unsupported"><b>말과 스캔이 다른 쪽</b> — 스캔이 잰 회전과 지금 계획의 회전이 다릅니다. 말한 것이 맞으면 그대로 두고, 아니면 「보기」로 확인하세요.<ul>' +
      conflicts.map((c) => `<li>${_woEsc(c.pages)}쪽 — 스캔 ${c.measured}°, 계획 ${c.planned}°</li>`).join("") +
      "</ul></div>"
    : "";
  const mixed = workOrderState.scan?.mixed_pages || [];
  const mixedBox = mixed.length
    ? `<div class="wo-unsupported"><b>종류가 섞인 쪽 ${mixed.length}개</b> — ${_woEsc(mixed.join(","))}쪽은 엔진 하나로 읽을 수 없습니다(예: 한글+훈점). 레이아웃 탭에서 영역을 나눈 뒤 영역마다 엔진을 골라 「선택 블록 OCR」로 읽으세요.</div>`
    : "";
  box.innerHTML =
    miss +
    conflictBox +
    mixedBox +
    `<table class="wo-table"><thead><tr><th>쪽</th><th>회전</th><th>엔진</th><th>쓰기</th><th></th><th>메모</th></tr></thead>` +
    `<tbody>${rows || '<tr><td colspan="6">구간 없음</td></tr>'}</tbody></table>` +
    (chapters ? `<div class="wo-dim">장</div><ul class="wo-chapters">${chapters}</ul>` : "") +
    (plan.guidance ? `<div class="wo-dim">판독 지침: ${_woEsc(plan.guidance)}</div>` : "");
  if (json) json.value = JSON.stringify(plan, null, 2);
}

/**
 * JSON 칸을 손으로 고쳤는데 표가 아직 옛 계획이면, 표를 먼저 JSON에 맞춘다. 출력: 표가 이미 맞았으면 true.
 * 표의 단추는 «표의 몇 번째 줄»을 가리키므로, 고친 JSON에서 구간 순서가 바뀌었으면 엉뚱한 구간을
 * 돌리거나 그린다(Codex 지적 2026-10-02). 맞춘 뒤에는 사람이 표를 보고 다시 누르게 false를 돌려준다.
 */
function _woSyncFromJson() {
  const jsonEl = document.getElementById("wo-plan-json");
  if (!jsonEl || !jsonEl.value.trim() || !workOrderState.plan) return true;
  if (jsonEl.value === JSON.stringify(workOrderState.plan, null, 2)) return true;
  let plan;
  try {
    plan = JSON.parse(jsonEl.value);
  } catch (e) {
    _woStatus(`계획 JSON을 읽을 수 없습니다: ${e.message}`, "error");
    return false;
  }
  _woSetPlan(plan);
  _woStatus("JSON에서 고친 것을 표에 먼저 반영했습니다 — 표를 보고 다시 누르세요.", "warning");
  return false;
}

/** 계획 표의 「보기」 — 구간 첫 쪽을 그 회전으로 작게 그린다. 다시 누르면 접는다. */
async function _woToggleThumb(i) {
  const t = _woTarget();
  if (!_woSyncFromJson()) return;
  const r = workOrderState.plan?.ranges?.[i];
  const row = document.querySelector(`[data-wo-thumb-row="${i}"]`);
  if (!t || !r || !row) return;
  if (!row.hidden) {
    row.hidden = true;
    return;
  }
  const first = _woPages(r.pages)[0];
  const ok = await renderPageThumb(row.querySelector("canvas"), t.docId, t.partId, first, r.rotation).catch(() => false);
  if (!ok) {
    _woStatus("이 권의 PDF가 화면에 열려 있어야 그림을 보입니다 — 창을 닫고 이 권을 연 뒤 다시 여세요.", "warning");
    return;
  }
  row.hidden = false;
}

/** 계획 표의 「반대로」 — 그 구간의 회전에 180°를 더한다(저장하지 않는다 — 「적용」이 저장한다). */
function _woFlip(i) {
  // JSON 칸을 손으로 고쳤으면 표부터 맞춘다 — 표의 줄 번호가 고친 JSON의 구간을 가리키지 않을 수 있다
  if (!_woSyncFromJson()) return;
  const plan = workOrderState.plan;
  const r = plan?.ranges?.[i];
  if (!r || r.skip) return;
  r.rotation = (Number(r.rotation) + 180) % 360;
  const open = !document.querySelector(`[data-wo-thumb-row="${i}"]`)?.hidden;
  _woSetPlan(plan); // 경고는 그대로 둔다 — 회전 하나를 바꿨다고 뺀 칸이 해결된 것은 아니다
  if (open) _woToggleThumb(i);
}

async function _woLoad() {
  const t = _woTarget();
  if (!t) return;
  // 불러오는 동안·실패하면 계획을 비운다 — 앞 문헌의 계획으로 적용하지 않게
  const key = _woKey(t);
  Object.assign(workOrderState, { key, loading: true, scan: null });
  _woSetPlan(null, []); // 세대가 올라 이 창을 열기 전에 보낸 스캔·말 요청의 응답은 버려진다
  const gen = workOrderState.gen;
  try {
    const res = await fetch(`/api/documents/${encodeURIComponent(t.docId)}/read-plan?part_id=${encodeURIComponent(t.partId)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    if (workOrderState.key !== key || workOrderState.gen !== gen) return; // 그 사이 다른 문헌을 열었다
    workOrderState.pageCount = data.page_count;
    workOrderState.engines = data.engines || [];
    _woSetPlan(
      data.plan,
      (data.problems || []).map((p) => ({ said: p.where, why: p.why })),
      "저장된 계획에서 뺀 칸 — 확인에 걸린 칸은 쓰지 않습니다. 고쳐서 다시 적용하세요.",
    );
    _woStatus(
      `이 권은 ${data.page_count}쪽입니다. 쓸 수 있는 엔진: ${workOrderState.engines.join(", ") || "알 수 없음"}` +
        (data.plan ? " · 저장된 계획을 불러왔습니다." : ""),
    );
  } catch (e) {
    _woStatus(`계획을 불러오지 못했습니다: ${e.message}`, "error");
  } finally {
    if (workOrderState.key === key) workOrderState.loading = false;
  }
}

/** 지금 대상이 불러온 계획의 대상과 같은가 — 아니면 적용·옮기기를 막는다. */
function _woReady(t) {
  if (workOrderState.loading || workOrderState.key !== _woKey(t)) {
    _woStatus("이 문헌의 계획을 아직 불러오지 못했습니다 — 창을 닫고 다시 여세요.", "warning");
    return false;
  }
  return true;
}

/** 지금 계획 — JSON 칸을 손으로 고쳤으면 그것. 읽을 수 없으면 throw. */
function _woCurrentPlan() {
  const jsonEl = document.getElementById("wo-plan-json");
  if (jsonEl && jsonEl.value.trim()) {
    try {
      return JSON.parse(jsonEl.value);
    } catch (e) {
      throw new Error(`계획 JSON을 읽을 수 없습니다: ${e.message}`);
    }
  }
  return workOrderState.plan;
}

/** 스캔 쪽 범위 칸. 출력: [from, to] 또는 null(권 전체). 잘못 적었으면 throw. */
function _woScanPages() {
  const raw = (document.getElementById("wo-scan-pages")?.value || "").trim();
  if (!raw) return null;
  const m = raw.match(/^(\d+)\s*[-~–]\s*(\d+)$/) || raw.match(/^(\d+)$/);
  if (!m) throw new Error(`쪽 범위를 «37-60»처럼 적으세요: ${raw}`);
  return [Number(m[1]), Number(m[2] ?? m[1])];
}

function _woScanProgress(on, done = 0, total = 1, text = "") {
  const prog = document.getElementById("wo-scan-progress");
  if (prog) prog.hidden = !on;
  const bar = document.getElementById("wo-scan-progress-bar");
  if (bar) {
    bar.max = total || 1;
    bar.value = done;
  }
  const txt = document.getElementById("wo-scan-progress-text");
  if (txt) txt.textContent = text;
}

/**
 * 스캔 칸의 안내 — 이 환경에서 무엇을 재는가를 누르기 전에 밝힌다. GPU면 «방향 + 종류(엔진)»,
 * CPU면 «방향만»(종류 판정은 쪽마다 비전 모델 + PaddleOCR이라 CPU에서 한 시간, 사용자 지시 2026-09-10).
 * GPU면 dry_run으로 «몇 쪽·호출 몇 번»도 센다(실행 게이트는 도구 층에 — 전역 규칙 11).
 */
let _woScanSeq = 0;
async function _woRefreshScanNote() {
  const note = document.getElementById("wo-scan-note");
  const modelRow = document.getElementById("wo-scan-model-row");
  const gpu = typeof ocrState !== "undefined" && !!ocrState.gpuRuntime;
  if (modelRow) modelRow.hidden = !gpu;
  if (!note) return;
  if (!gpu) {
    note.textContent =
      "이 서버는 CPU 환경이라 방향만 잽니다(누운 쪽 찾기, 모델 호출 없음). 글의 종류로 엔진까지 고르려면 바탕화면 아이콘(GPU 환경)으로 켠 서버에서 스캔하세요.";
    return;
  }
  const t = _woTarget();
  if (!t) return;
  const my = ++_woScanSeq;
  let pages;
  try {
    pages = _woScanPages();
  } catch (e) {
    note.textContent = e.message;
    return;
  }
  note.textContent = "세는 중…";
  try {
    const res = await fetch(_woScanUrl(t), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pages, dry_run: true }),
    });
    const dry = await res.json();
    if (my !== _woScanSeq) return; // 그 사이 범위를 또 고쳤다
    if (dry.error) throw new Error(dry.error);
    note.textContent = `${dry.pages}쪽 — 비전 모델 ${dry.calls}번(글의 종류) + PaddleOCR 최대 ${dry.ocr_calls || 0}번(방향 판정, GPU). 쪽마다 몇 초.`;
  } catch (e) {
    if (my === _woScanSeq) note.textContent = `셀 수 없습니다: ${e.message}`;
  }
}

function _woScanUrl(t) {
  return `/api/documents/${encodeURIComponent(t.docId)}/parts/${encodeURIComponent(t.partId)}/rotation/suggest`;
}

/** ① 자동 스캔 → 계획에 바로(저장하지 않는다). 지금 계획이 있으면 그 위에 얹는다. */
async function _woScan() {
  const t = _woTarget();
  if (!t || !_woReady(t)) return;
  let pages;
  let base;
  try {
    pages = _woScanPages();
    base = _woCurrentPlan();
  } catch (e) {
    _woStatus(e.message, "error");
    return;
  }
  const gen = workOrderState.gen; // 이 계획을 바탕으로 스캔한다 — 그 사이 계획이 바뀌면 응답을 버린다
  const gpu = typeof ocrState !== "undefined" && !!ocrState.gpuRuntime;
  const llmSel = gpu && typeof getLlmModelSelection === "function" ? getLlmModelSelection("wo-scan-model-select") : {};
  const btn = document.getElementById("wo-scan");
  if (btn) btn.disabled = true;
  _woScanProgress(true, 0, 1, "시작하는 중…");
  _woStatus(gpu ? "쪽을 훑는 중 — 방향과 글의 종류…" : "쪽을 훑는 중 — 방향만…");
  try {
    const d = await _postSurveyStream(
      _woScanUrl(t),
      {
        pages,
        writing_direction: document.getElementById("wo-scan-writing")?.value || "vertical_rtl",
        orientation_only: !gpu,
        as_plan: true,
        base_plan: base || null,
        force_provider: llmSel.force_provider || null,
        force_model: llmSel.force_model || null,
      },
      (evt) => {
        if (evt.type === "start") _woScanProgress(true, 0, evt.total, `${evt.total}쪽 — 첫 쪽을 보는 중…`);
        else if (evt.type === "page")
          _woScanProgress(true, evt.index + 1, evt.total, `${evt.index + 1}/${evt.total}쪽 — ${evt.page}쪽 ${evt.label || ""}${evt.engine ? ` → ${evt.engine}` : ""}`);
      },
    );
    if (workOrderState.key !== _woKey(t)) return; // 그 사이 다른 문헌을 열었다
    if (workOrderState.gen !== gen) {
      _woStatus("스캔하는 사이 계획이 바뀌어(반대로·JSON 고침·말로 덧붙이기) 이 스캔 결과는 넣지 않았습니다 — 다시 스캔하세요.", "warning");
      return;
    }
    if (!d.plan) throw new Error(d.plan_error || d.error || "계획을 만들지 못했습니다");
    const marks = d.plan_marks || {};
    workOrderState.scan = { per_page: d.per_page || [], guess_pages: marks.guess_pages || [], mixed_pages: marks.mixed_pages || [] };
    _woSetPlan(
      d.plan,
      (marks.problems || []).map((p) => ({ said: p.where, why: p.why })),
      "앞 계획에서 뺀 칸 — 확인에 걸린 칸은 쓰지 않습니다.",
    );
    const who = d.model ? ` (${d.provider ? d.provider + ":" : ""}${d.model})` : "";
    _woStatus(
      `${d.checked}쪽을 봤습니다${who} — 회전이 다른 구간 ${(d.rotation || []).length}개` +
        (gpu ? `, 엔진 구간 ${(d.engines || []).length}개` : " (방향만)") +
        ((marks.guess_pages || []).length ? ` · «추정» ${marks.guess_pages.length}쪽은 「보기」로 확인하세요` : "") +
        (d.unknown ? ` · 판단 못 한 쪽 ${d.unknown}` : "") +
        (d.error ? ` · 일부 실패: ${d.error}` : "") +
        ". 계획에 들어갔습니다 — 아직 저장하지 않았습니다.",
      d.error ? "warning" : "success",
    );
  } catch (e) {
    _woStatus(`스캔하지 못했습니다: ${e.message}`, "error");
  } finally {
    _woScanProgress(false);
    if (btn) btn.disabled = false;
  }
}

/** ② 말 → 계획에 덧붙이기. 저장하지 않는다. 지금 계획(스캔 결과 포함)을 base_plan으로 넘긴다. */
async function _woFromWords() {
  const t = _woTarget();
  if (!t || !_woReady(t)) return;
  const said = (document.getElementById("wo-said")?.value || "").trim();
  if (!said) {
    _woStatus("책에 대해 아는 것을 한 줄 이상 적으세요. 예: «5~69쪽은 시계 방향으로 누운 2쪽 펼침이고 근대 활자 세로쓰기»", "warning");
    return;
  }
  let base;
  try {
    base = _woCurrentPlan();
  } catch (e) {
    _woStatus(e.message, "error");
    return;
  }
  const gen = workOrderState.gen;
  const llmSel = typeof getLlmModelSelection === "function" ? getLlmModelSelection("wo-model-select") : {};
  const btn = document.getElementById("wo-from-words");
  if (btn) btn.disabled = true;
  _woStatus("LLM이 말을 계획으로 옮기는 중…");
  try {
    const res = await fetch(`/api/documents/${encodeURIComponent(t.docId)}/read-plan/from-words`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ said, part_id: t.partId, base_plan: base, ...llmSel }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    if (workOrderState.key !== _woKey(t)) return;
    if (workOrderState.gen !== gen) {
      _woStatus("옮기는 사이 계획이 바뀌어(스캔·반대로·JSON 고침) 이 결과는 넣지 않았습니다 — 다시 누르세요.", "warning");
      return;
    }
    _woSetPlan(data.plan, data.unsupported || [], WO_UNSUPPORTED_HEADING);
    _woStatus(
      `계획 초안(${data.provider || "?"}:${data.model || "?"}) — ③에서 확인하고 「적용」을 누르세요.` +
        (data.note ? ` 모델 메모: ${data.note}` : ""),
    );
  } catch (e) {
    _woStatus(`옮기지 못했습니다: ${e.message}`, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

/** ③ 적용 — 회전·지침·장 저장 후 «권 전체 OCR»에 계획을 건다. */
async function _woApply() {
  const t = _woTarget();
  if (!t || !_woReady(t)) return;
  let plan;
  try {
    plan = _woCurrentPlan();
  } catch (e) {
    _woStatus(e.message, "error");
    return;
  }
  if (!plan) {
    _woStatus("적용할 계획이 없습니다.", "warning");
    return;
  }
  _woStatus("적용하는 중…");
  try {
    const res = await fetch(`/api/documents/${encodeURIComponent(t.docId)}/read-plan`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan, part_id: t.partId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    _woSetPlan(
      data.plan,
      (data.problems || []).map((p) => ({ said: p.where, why: p.why })),
      "적용하며 알릴 것 — 계획은 저장됐습니다. 아래 구간은 뜻대로 돌지 않을 수 있습니다.",
    );
    if (typeof setOcrEnginePlan === "function") {
      const mixed = (workOrderState.scan?.mixed_pages || []).map((p) => ({ page: p, label: "종류 섞임" }));
      setOcrEnginePlan({
        docId: t.docId,
        partId: t.partId,
        ranges: (data.engine_plan || []).map((r) => ({
          from: r.from,
          to: r.to,
          engine: r.engine_id,
          writing: r.writing_direction,
          label: r.writing_direction === "horizontal_ltr" ? "가로" : "세로",
        })),
        mixed,
      });
    }
    _woStatus(
      `적용했습니다 — 돌릴 쪽 ${data.pages.length} · 회전 구간 ${data.rotation_ranges.length}. ` +
        "OCR 패널의 「권 전체 OCR」을 누르면 이 계획대로 돕니다(«작업 계획대로»가 켜져 있습니다).",
      "success",
    );
    // 뷰어가 새 회전으로 다시 그리게 한다 — 권의 회전은 그대로이고 쪽 범위만 바뀐다
    const part = viewerState?.documentInfo?.parts?.find((p) => p.part_id === t.partId);
    await syncSavedRotation(t.docId, t.partId, Number(part?.rotation) || 0, data.rotation_ranges || []);
  } catch (e) {
    _woStatus(`적용하지 못했습니다: ${e.message}`, "error");
  }
}

function openWorkOrder() {
  const overlay = document.getElementById("work-order-overlay");
  if (!overlay || !_woTarget()) return;
  overlay.style.display = "";
  // 종류 판정 기본 모델은 kimi-k3:cloud. 목록에 없거나 은퇴(disabled)면 «자동». 한 번 고른 뒤에는 그것을 지킨다
  // 단 clef 키(Cloudflare 또는 OpenRouter)가 있어 목록이 clef를 미리 골랐으면(D-135, workspace.js의
  // `clefDefaulted`) 그것을 지킨다 — 한때 창을 열 때마다 kimi로 덮어 «키가 있으면 clef»가 화면에서
  // 한 번도 살아남지 못했다(2026-10-05 headless 실측: 네 경우 모두 창을 열면 kimi).
  const sel = document.getElementById("wo-scan-model-select");
  if (sel && !sel.dataset.picked) {
    const keepClef = sel.dataset.clefDefaulted && sel.value === "clef:clef";
    if (!keepClef && [...sel.options].some((o) => o.value === WO_SCAN_DEFAULT_MODEL && !o.disabled)) sel.value = WO_SCAN_DEFAULT_MODEL;
    sel.addEventListener("change", () => { sel.dataset.picked = "1"; }, { once: true });
  }
  _woLoad();
  _woRefreshScanNote();
  document.getElementById("wo-said")?.focus();
}

function initWorkOrder() {
  const overlay = document.getElementById("work-order-overlay");
  if (!overlay) return;
  const close = () => {
    overlay.style.display = "none";
  };
  document.getElementById("work-order-btn")?.addEventListener("click", openWorkOrder);
  document.getElementById("wo-close")?.addEventListener("click", close);
  document.getElementById("wo-cancel")?.addEventListener("click", close);
  overlay.addEventListener("click", (ev) => {
    if (ev.target === overlay) close();
  });
  document.getElementById("wo-scan")?.addEventListener("click", _woScan);
  document.getElementById("wo-scan-pages")?.addEventListener("input", _woRefreshScanNote);
  document.getElementById("wo-from-words")?.addEventListener("click", _woFromWords);
  document.getElementById("wo-apply")?.addEventListener("click", _woApply);
  // JSON 칸을 손으로 고치면 계획이 바뀐 것이다 — 도는 중인 스캔·말 응답이 그것을 덮지 않게 세대를 올린다
  document.getElementById("wo-plan-json")?.addEventListener("input", () => {
    workOrderState.gen += 1;
  });
  // 계획 표의 「보기」·「반대로」 — 표는 다시 그려지므로 위임으로 받는다
  document.getElementById("wo-plan")?.addEventListener("click", (ev) => {
    const b = ev.target instanceof Element ? ev.target.closest("[data-wo-thumb],[data-wo-flip]") : null;
    if (!b) return;
    if (b.dataset.woThumb != null) _woToggleThumb(Number(b.dataset.woThumb));
    else _woFlip(Number(b.dataset.woFlip));
  });
}
