/**
 * 교정 탭 「들이기·내보내기」 (2026-10-02 — 옛 「말로 작업 지시」 ③을 옮김)
 *
 * 왜 여기인가:
 *   계획 창(말로 작업 지시)은 «OCR 전에 무엇을 어떻게 읽을지»를 정하는 곳이다. 텍스트를 내려받거나
 *   LLM 결과를 들이는 일은 OCR·교정이 끝난 뒤 확정본(L4)을 다루는 일이라 교정 탭이 맞다.
 *   «강독»이라는 말도 뺐다 — 강독 노트는 한 예시였을 뿐이고, 논문 한 편을 OCR한 뒤 판면 줄바꿈만
 *   지워 마크다운으로 받는 것이 더 흔한 쓰임이다.
 *
 * 하는 일:
 *   - 텍스트로 내려받기 — 한 파일(GET export/text?single=true) 또는 장별 zip(GET export/text)
 *   - LLM 결과 JSON 들이기 — POST reading-notes(새 저장 형식 없이 L4·경계·L6·L7에 나눠 담는다, D-131)
 *   - 노트 틀 — 예시를 LLM이 틀로 바꾸고(POST note-template/from-example), 그 틀로 내려받는다
 *     (POST export/notes). 틀은 저장하지 않는다 — 파일로 받아 두었다가 다시 불러온다.
 */

/* global viewerState, showToast, getLlmModelSelection */

const exportViewState = { template: null };

function _cxEsc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

function _cxTarget() {
  const docId = viewerState?.docId;
  const partId = viewerState?.partId || "vol1";
  if (!docId) {
    showToast("문헌을 먼저 여세요.", "warning");
    return null;
  }
  return { docId, partId };
}

function _cxStatus(text, kind = "") {
  const el = document.getElementById("cx-status");
  if (!el) return;
  el.textContent = text;
  el.dataset.kind = kind;
}

/** 내려받기 — 실패하면 서버의 한국어 사유를 보여 준다(링크로 바로 가면 오류 JSON 화면이 뜬다). */
async function _cxFetchDownload(url, options, fallbackName) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  const blob = await res.blob();
  // 서버가 정한 파일 이름(RFC 5987) — 없으면 대체 이름
  const cd = res.headers.get("Content-Disposition") || "";
  const m = cd.match(/filename\*=UTF-8''([^;]+)/i);
  let name = fallbackName;
  try {
    if (m) name = decodeURIComponent(m[1]);
  } catch (_) {
    name = fallbackName; // 깨진 퍼센트 인코딩이어도 내려받기는 한다
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  return { name, removed: _cxRemovedNote(res) };
}

/** 한 파일 내려받기에서 뺀 줄 수(서버 머리 X-CTB-*). 없으면 빈 글. */
function _cxRemovedNote(res) {
  const run = Number(res.headers.get("X-CTB-Running-Lines") || 0);
  const noise = Number(res.headers.get("X-CTB-Noise-Lines") || 0);
  if (!run && !noise) return "";
  const bits = [];
  if (run) bits.push(`쪽마다 되풀이된 머리글 ${run}줄`);
  if (noise) bits.push(`쪽 번호·잡음 ${noise}줄`);
  return ` — ${bits.join(", ")}을 뺐습니다(확정본은 그대로)`;
}

/** 텍스트로 내려받기. single이면 전문 한 파일, 아니면 장별 zip. */
async function _cxDownloadText(single) {
  const t = _cxTarget();
  if (!t) return;
  const fmt = document.getElementById("cx-format")?.value || "md";
  const keep = document.getElementById("cx-keep-lines")?.checked ? "true" : "false";
  const url =
    `/api/documents/${encodeURIComponent(t.docId)}/export/text?part_id=${encodeURIComponent(t.partId)}` +
    `&format=${fmt}&keep_lines=${keep}${single ? "&single=true" : ""}`;
  _cxStatus("만드는 중…");
  try {
    const { name, removed } = await _cxFetchDownload(url, {}, `${t.docId}_${t.partId}.${single ? fmt : "zip"}`);
    _cxStatus(`내려받았습니다: ${name}${removed}`, "success");
  } catch (e) {
    _cxStatus(`내려받지 못했습니다: ${e.message}`, "error");
  }
}

/** LLM이 돌려준 결과 JSON 들이기 — 교정은 L4로, 번역·어휘는 L6·L7로. */
async function _cxImportNote(file) {
  const t = _cxTarget();
  if (!t || !file) return;
  let note;
  try {
    note = JSON.parse(await file.text());
  } catch (e) {
    _cxStatus(`JSON을 읽을 수 없습니다: ${e.message}`, "error");
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
    _cxStatus(
      `들였습니다: ${note.chapter} — 교정 ${data.corrected.length}쪽 · 항목 경계 +${data.boundaries_added} · ` +
        `번역 ${data.translations} · 주석 ${data.annotations} (해석 저장소 ${data.interp_id})` +
        (data.kept.length ? ` · 사람이 고친 쪽 ${data.kept.join(",")}은 두었습니다(교정 서브탭에서 비교하세요)` : "") +
        (missed ? ` · 자리를 못 찾은 항목·구획 ${missed}개 — 확정본과 답의 원문이 다릅니다` : ""),
      data.kept.length || missed ? "warning" : "success",
    );
    // L4 교정을 쓴 쪽의 사람 교정 소식(D-133) — 옮기지 못한 교정은 «기록»으로 갔다
    if (typeof notifyCorrectionsRebase === "function") notifyCorrectionsRebase(data);
  } catch (e) {
    _cxStatus(`들이지 못했습니다: ${e.message}`, "error");
  }
}

function _cxSetTemplate(template, preview, problems) {
  exportViewState.template = template || null;
  const pre = document.getElementById("cx-template-preview");
  const box = document.getElementById("cx-template-problems");
  if (pre) {
    // textContent — 예시·미리보기에 든 글자를 HTML로 해석하지 않는다
    pre.textContent = preview || "";
    pre.style.display = preview ? "" : "none";
  }
  if (box) {
    box.innerHTML = problems && problems.length
      ? `<b>틀 점검</b><ul>${problems.map((p) => `<li>${_cxEsc(p)}</li>`).join("")}</ul>`
      : "";
    box.style.display = problems && problems.length ? "" : "none";
  }
  for (const id of ["cx-template-save", "cx-dl-template"]) {
    const b = document.getElementById(id);
    if (b) b.disabled = !exportViewState.template;
  }
}

async function _cxMakeTemplate() {
  const t = _cxTarget();
  if (!t) return;
  const example = (document.getElementById("cx-example")?.value || "").trim();
  if (!example) {
    _cxStatus("원하는 노트 예시를 먼저 붙여 넣으세요.", "warning");
    return;
  }
  const llmSel = typeof getLlmModelSelection === "function" ? getLlmModelSelection("cx-model-select") : {};
  const btn = document.getElementById("cx-make-template");
  if (btn) btn.disabled = true;
  _cxStatus("예시를 틀로 바꾸는 중…");
  try {
    const res = await fetch(`/api/documents/${encodeURIComponent(t.docId)}/note-template/from-example`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ example, force_provider: llmSel.force_provider, force_model: llmSel.force_model }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    _cxSetTemplate(data.template, data.preview, data.problems);
    _cxStatus(
      data.problems && data.problems.length
        ? "틀을 만들었지만 점검에 걸린 것이 있습니다 — 아래를 보고 예시를 고쳐 다시 만드세요."
        : `틀을 만들었습니다(${data.provider || "?"} ${data.model || ""}). 아래는 본보기 항목을 이 틀로 채운 모습입니다.`,
      data.problems && data.problems.length ? "warning" : "success",
    );
  } catch (e) {
    _cxStatus(`틀을 만들지 못했습니다: ${e.message}`, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

function _cxSaveTemplate() {
  if (!exportViewState.template) return;
  const blob = new Blob([exportViewState.template], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "노트_틀.j2";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

async function _cxDownloadWithTemplate() {
  const t = _cxTarget();
  if (!t || !exportViewState.template) return;
  const ext = document.getElementById("cx-template-ext")?.value || "txt";
  try {
    await _cxFetchDownload(
      `/api/documents/${encodeURIComponent(t.docId)}/export/notes`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ template: exportViewState.template, part_id: t.partId, ext }),
      },
      `${t.docId}_${t.partId}_notes.zip`,
    );
    _cxStatus("틀로 만든 노트를 내려받았습니다.", "success");
  } catch (e) {
    _cxStatus(`내려받지 못했습니다: ${e.message}`, "error");
  }
}

// eslint-disable-next-line no-unused-vars
function initExportView() {
  document.getElementById("extract-text-md-btn")?.addEventListener("click", downloadPlainText);
  document.getElementById("cx-dl-one")?.addEventListener("click", () => _cxDownloadText(true));
  document.getElementById("cx-dl-zip")?.addEventListener("click", () => _cxDownloadText(false));
  document.getElementById("cx-note-file")?.addEventListener("change", (ev) => {
    const f = ev.target.files && ev.target.files[0];
    _cxImportNote(f);
    ev.target.value = "";
  });
  document.getElementById("cx-make-template")?.addEventListener("click", _cxMakeTemplate);
  document.getElementById("cx-template-save")?.addEventListener("click", _cxSaveTemplate);
  document.getElementById("cx-dl-template")?.addEventListener("click", _cxDownloadWithTemplate);
  document.getElementById("cx-template-file")?.addEventListener("change", async (ev) => {
    const f = ev.target.files && ev.target.files[0];
    ev.target.value = "";
    if (!f) return;
    // 불러온 틀은 서버가 내려받을 때 점검한다(문법 오류면 그때 한국어로 알린다)
    _cxSetTemplate(await f.text(), "", []);
    _cxStatus(`틀을 불러왔습니다: ${f.name}`, "success");
  });
}

/**
 * 「논문」 추출 패널의 «3. 텍스트로 내려받기» — 전문 한 파일(마크다운). 교정 탭과 같은 라우트다.
 * 입력: 없음(viewerState). 출력: 없음. 결과는 토스트로 알린다.
 */
// eslint-disable-next-line no-unused-vars
async function downloadPlainText() {
  const t = _cxTarget();
  if (!t) return;
  const url =
    `/api/documents/${encodeURIComponent(t.docId)}/export/text?part_id=${encodeURIComponent(t.partId)}` +
    "&format=md&single=true";
  try {
    const { name, removed } = await _cxFetchDownload(url, {}, `${t.docId}_${t.partId}.md`);
    showToast(`내려받았습니다: ${name}${removed}`, "success");
  } catch (e) {
    showToast(`내려받지 못했습니다: ${e.message}`, "error");
  }
}
