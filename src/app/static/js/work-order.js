/**
 * 말로 작업 지시 (D-131) — 복잡한 스캔본을 «말 → 계획 → 확인 → 적용 → OCR → 결과 되들이기 → 내려받기»로.
 *
 * 왜 이 창인가:
 *   돌아간 2쪽 펼침·세로쓰기·필사본·한글 번역이 섞인 사진본이 한 권에 들어 있으면, 쪽마다 회전·엔진·쓰기
 *   방향을 단추로 고르는 일이 끝나지 않는다. 연구자는 자기 책을 이미 안다 — 그것을 말로 적게 하고
 *   (「5~69쪽은 시계 방향으로 누운 펼침이고 활자」), LLM이 정해진 칸으로 옮긴 «작업 계획»을 사람이 보고
 *   적용한다. 옮기지 못한 말은 반드시 그대로 보여 준다(rule_talk와 같은 규약).
 *
 * 한 흐름(①②③):
 *   ① 말로 적기 → 「계획으로 옮기기」 (LLM 한 번, 저장하지 않음)
 *   ② 계획 확인 → 「적용」 (회전·판독 지침·장 목록 저장) → «권 전체 OCR»에 계획이 걸린다
 *   ③ 결과 — LLM(Claude Code 세션 등)이 돌려준 강독 JSON을 「들이기」(교정은 L4로), 장별 「내려받기」.
 *      원하는 노트 모양이 따로 있으면 예시를 붙여 «틀»로 바꾸고 그 틀로 내려받는다(모양만 LLM, 내용은 층)
 *
 * OCR 실행 자체는 기존 «권 전체 OCR»이 한다(진행 표시·중단·백업·L4 보호가 거기 있다).
 */

/* global viewerState, showToast, getLlmModelSelection, setOcrEnginePlan, syncSavedRotation */

// 계획은 **문헌·권에 묶는다** — 다른 문헌으로 옮긴 뒤 불러오기가 실패해도 앞 문헌의 계획이
// 남아 새 문헌에 적용되지 않게(Codex 지적 2026-09-30). key가 지금 대상과 다르면 계획을 쓰지 않는다.
const workOrderState = { key: null, plan: null, pageCount: 0, engines: [], loading: false };

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

/** ② 계획을 표로 보인다 — 무엇이 어느 엔진·회전으로 돌지 «적용» 전에 보여야 한다. */
function _woRenderPlan(plan, unsupported = [], heading = "옮기지 못한 말 — 계획에 들어가지 않았습니다. 말을 고쳐 다시 옮기거나, 아래 JSON을 직접 고치세요.") {
  const box = document.getElementById("wo-plan");
  const json = document.getElementById("wo-plan-json");
  if (!box) return;
  if (!plan) {
    box.innerHTML = '<div class="comp-split-note">아직 계획이 없습니다. ①에 책에 대해 아는 것을 적으세요.</div>';
    if (json) json.value = "";
    return;
  }
  const rows = (plan.ranges || [])
    .map((r) =>
      r.skip
        ? `<tr><td>${_woEsc(r.pages)}</td><td colspan="3">건너뜀</td><td>${_woEsc(r.note)}</td></tr>`
        : `<tr><td>${_woEsc(r.pages)}</td><td>${_woEsc(r.rotation)}°</td><td>${_woEsc(r.engine)}</td>` +
          `<td>${r.writing === "horizontal_ltr" ? "가로" : "세로"}</td><td>${_woEsc(r.note)}</td></tr>`,
    )
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
  box.innerHTML =
    miss +
    `<table class="wo-table"><thead><tr><th>쪽</th><th>회전</th><th>엔진</th><th>쓰기</th><th>메모</th></tr></thead>` +
    `<tbody>${rows || '<tr><td colspan="5">구간 없음</td></tr>'}</tbody></table>` +
    (chapters ? `<div class="wo-dim">장</div><ul class="wo-chapters">${chapters}</ul>` : "") +
    (plan.guidance ? `<div class="wo-dim">판독 지침: ${_woEsc(plan.guidance)}</div>` : "");
  if (json) json.value = JSON.stringify(plan, null, 2);
}

async function _woLoad() {
  const t = _woTarget();
  if (!t) return;
  // 불러오는 동안·실패하면 계획을 비운다 — 앞 문헌의 계획으로 적용하지 않게
  const key = _woKey(t);
  Object.assign(workOrderState, { key, plan: null, loading: true });
  _woRenderPlan(null);
  try {
    const res = await fetch(`/api/documents/${encodeURIComponent(t.docId)}/read-plan?part_id=${encodeURIComponent(t.partId)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    if (workOrderState.key !== key) return; // 그 사이 다른 문헌을 열었다
    workOrderState.plan = data.plan;
    workOrderState.pageCount = data.page_count;
    workOrderState.engines = data.engines || [];
    _woRenderPlan(
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

/** ① 말 → 계획 초안. 저장하지 않는다. */
async function _woFromWords() {
  const t = _woTarget();
  if (!t || !_woReady(t)) return;
  const said = (document.getElementById("wo-said")?.value || "").trim();
  if (!said) {
    _woStatus("책에 대해 아는 것을 한 줄 이상 적으세요. 예: «5~69쪽은 시계 방향으로 누운 2쪽 펼침이고 근대 활자 세로쓰기»", "warning");
    return;
  }
  const llmSel = typeof getLlmModelSelection === "function" ? getLlmModelSelection("wo-model-select") : {};
  const btn = document.getElementById("wo-from-words");
  if (btn) btn.disabled = true;
  _woStatus("LLM이 말을 계획으로 옮기는 중…");
  try {
    const res = await fetch(`/api/documents/${encodeURIComponent(t.docId)}/read-plan/from-words`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ said, part_id: t.partId, base_plan: workOrderState.plan, ...llmSel }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    if (workOrderState.key !== _woKey(t)) return;
    workOrderState.plan = data.plan;
    _woRenderPlan(data.plan, data.unsupported || []);
    _woStatus(
      `계획 초안(${data.provider || "?"}:${data.model || "?"}) — ②에서 확인하고 「적용」을 누르세요.` +
        (data.note ? ` 모델 메모: ${data.note}` : ""),
    );
  } catch (e) {
    _woStatus(`옮기지 못했습니다: ${e.message}`, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

/** ② 적용 — 회전·지침·장 저장 후 «권 전체 OCR»에 계획을 건다. */
async function _woApply() {
  const t = _woTarget();
  if (!t || !_woReady(t)) return;
  let plan = workOrderState.plan;
  const jsonEl = document.getElementById("wo-plan-json");
  if (jsonEl && jsonEl.value.trim()) {
    try {
      plan = JSON.parse(jsonEl.value);
    } catch (e) {
      _woStatus(`계획 JSON을 읽을 수 없습니다: ${e.message}`, "error");
      return;
    }
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
    workOrderState.plan = data.plan;
    _woRenderPlan(
      data.plan,
      (data.problems || []).map((p) => ({ said: p.where, why: p.why })),
      "적용하며 알릴 것 — 계획은 저장됐습니다. 아래 구간은 뜻대로 돌지 않을 수 있습니다.",
    );
    if (typeof setOcrEnginePlan === "function") {
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
        mixed: [],
      });
    }
    _woStatus(
      `적용했습니다 — 돌릴 쪽 ${data.pages.length} · 회전 구간 ${data.rotation_ranges.length}. ` +
        "OCR 패널의 「권 전체 OCR」을 누르면 이 계획대로 돕니다(«판독 계획대로»가 켜져 있습니다).",
      "success",
    );
    // 뷰어가 새 회전으로 다시 그리게 한다 — 권의 회전은 그대로이고 쪽 범위만 바뀐다
    const part = viewerState?.documentInfo?.parts?.find((p) => p.part_id === t.partId);
    await syncSavedRotation(t.docId, t.partId, Number(part?.rotation) || 0, data.rotation_ranges || []);
  } catch (e) {
    _woStatus(`적용하지 못했습니다: ${e.message}`, "error");
  }
}

/** ③ LLM이 돌려준 강독 JSON 들이기 — 교정은 L4로, 국역·어휘는 노트로. */
async function _woImportNote(file) {
  const t = _woTarget();
  if (!t || !file) return;
  let note;
  try {
    note = JSON.parse(await file.text());
  } catch (e) {
    _woStatus(`JSON을 읽을 수 없습니다: ${e.message}`, "error");
    return;
  }
  try {
    const res = await fetch(`/api/documents/${encodeURIComponent(t.docId)}/reading-notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note, part_id: t.partId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    // 새 저장 형식 없이 기존 층에 나눠 담았다(D-131): L4·편성 경계·L6 번역·L7 주석
    const missed = (data.unplaced_sections || []).length + (data.unplaced_segments || []).length;
    _woStatus(
      `들였습니다: ${note.chapter} — 교정 ${data.corrected.length}쪽 · 항목 경계 +${data.boundaries_added} · ` +
        `번역 ${data.translations} · 주석 ${data.annotations} (해석 저장소 ${data.interp_id})` +
        (data.kept.length ? ` · 사람이 고친 쪽 ${data.kept.join(",")}은 두었습니다(교정 탭에서 비교하세요)` : "") +
        (missed ? ` · 자리를 못 찾은 항목·구획 ${missed}개 — 확정본과 답의 원문이 다릅니다` : ""),
      data.kept.length || missed ? "warning" : "success",
    );
  } catch (e) {
    _woStatus(`들이지 못했습니다: ${e.message}`, "error");
  }
}

function _woDownload(format) {
  const t = _woTarget();
  if (!t) return;
  const keep = document.getElementById("wo-keep-lines")?.checked ? "true" : "false";
  window.location.href =
    `/api/documents/${encodeURIComponent(t.docId)}/export/text?part_id=${encodeURIComponent(t.partId)}&format=${format}&keep_lines=${keep}`;
}

/**
 * ③ 틀 — 노트 모양은 수업·스터디마다 달라진다. 코드에 모양을 박지 않고, 연구자가 붙여 넣은 예시를
 * LLM이 틀로 바꾸면(모양만), 내려받을 때 서버가 층(L4·경계·L6·L7)으로 채운다(export/note_template.py).
 * 틀은 저장하지 않는다 — 파일로 받아 두었다가 다시 불러온다.
 */
function _woSetTemplate(template, preview, problems) {
  workOrderState.template = template || null;
  const pre = document.getElementById("wo-template-preview");
  const box = document.getElementById("wo-template-problems");
  if (pre) {
    // textContent — 예시·미리보기에 든 글자를 HTML로 해석하지 않는다
    pre.textContent = preview || "";
    pre.style.display = preview ? "" : "none";
  }
  if (box) {
    box.innerHTML = problems && problems.length
      ? `<b>틀 점검</b><ul>${problems.map((p) => `<li>${_woEsc(p)}</li>`).join("")}</ul>`
      : "";
    box.style.display = problems && problems.length ? "" : "none";
  }
  for (const id of ["wo-template-save", "wo-dl-template"]) {
    const b = document.getElementById(id);
    if (b) b.disabled = !workOrderState.template;
  }
}

async function _woMakeTemplate() {
  const t = _woTarget();
  if (!t) return;
  const example = (document.getElementById("wo-example")?.value || "").trim();
  if (!example) {
    _woStatus("원하는 노트 예시를 먼저 붙여 넣으세요.", "warning");
    return;
  }
  const llmSel = typeof getLlmModelSelection === "function" ? getLlmModelSelection("wo-model-select") : {};
  const btn = document.getElementById("wo-make-template");
  if (btn) btn.disabled = true;
  _woStatus("예시를 틀로 바꾸는 중…");
  try {
    const res = await fetch(`/api/documents/${encodeURIComponent(t.docId)}/note-template/from-example`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ example, force_provider: llmSel.force_provider, force_model: llmSel.force_model }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    _woSetTemplate(data.template, data.preview, data.problems);
    _woStatus(
      data.problems && data.problems.length
        ? "틀을 만들었지만 점검에 걸린 것이 있습니다 — 아래를 보고 예시를 고쳐 다시 만드세요."
        : `틀을 만들었습니다(${data.provider || "?"} ${data.model || ""}). 아래는 본보기 항목을 이 틀로 채운 모습입니다.`,
      data.problems && data.problems.length ? "warning" : "success",
    );
  } catch (e) {
    _woStatus(`틀을 만들지 못했습니다: ${e.message}`, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

function _woSaveTemplate() {
  if (!workOrderState.template) return;
  const blob = new Blob([workOrderState.template], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "강독노트_틀.j2";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

async function _woDownloadWithTemplate() {
  const t = _woTarget();
  if (!t || !workOrderState.template) return;
  const ext = document.getElementById("wo-template-ext")?.value || "txt";
  try {
    const res = await fetch(`/api/documents/${encodeURIComponent(t.docId)}/export/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template: workOrderState.template, part_id: t.partId, ext }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${t.docId}_${t.partId}_notes.zip`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    _woStatus("틀로 만든 강독 노트를 내려받았습니다.", "success");
  } catch (e) {
    _woStatus(`내려받지 못했습니다: ${e.message}`, "error");
  }
}

function openWorkOrder() {
  const overlay = document.getElementById("work-order-overlay");
  if (!overlay || !_woTarget()) return;
  overlay.style.display = "";
  _woLoad();
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
  document.getElementById("wo-from-words")?.addEventListener("click", _woFromWords);
  document.getElementById("wo-apply")?.addEventListener("click", _woApply);
  document.getElementById("wo-note-file")?.addEventListener("change", (ev) => {
    const f = ev.target.files && ev.target.files[0];
    _woImportNote(f);
    ev.target.value = "";
  });
  document.getElementById("wo-dl-wiki")?.addEventListener("click", () => _woDownload("wiki"));
  document.getElementById("wo-dl-md")?.addEventListener("click", () => _woDownload("md"));
  document.getElementById("wo-make-template")?.addEventListener("click", _woMakeTemplate);
  document.getElementById("wo-template-save")?.addEventListener("click", _woSaveTemplate);
  document.getElementById("wo-dl-template")?.addEventListener("click", _woDownloadWithTemplate);
  document.getElementById("wo-template-file")?.addEventListener("change", async (ev) => {
    const f = ev.target.files && ev.target.files[0];
    ev.target.value = "";
    if (!f) return;
    // 불러온 틀은 서버가 내려받을 때 점검한다(문법 오류면 그때 한국어로 알린다)
    _woSetTemplate(await f.text(), "", []);
    _woStatus(`틀을 불러왔습니다: ${f.name}`, "success");
  });
}
