/**
 * 연결·업데이트를 화면에서 끝낸다 (D-102 · D-103).
 *
 * 왜 필요한가:
 *   v1.3.0까지 API 키를 넣는 길은 «메모장으로 .env를 여는 것»뿐이었고, 새 판이 나온 줄
 *   알려면 GitHub 저장소를 직접 봐야 했다. 처음 쓰는 사람에게 둘 다 넘기 어려운 문턱이다.
 *
 * 무엇을 하는가:
 *   - 프로바이더 카드마다 키 입력칸 (저장하면 **서고 .env**에 쓴다 — 앱을 갈아도 남는다)
 *   - Ollama가 도는지 눌러서 확인
 *   - 새 판 확인과 내려받기 (고친 파일이 남아 있으면 받지 않는다)
 *
 * 키를 화면에 되돌려 주지 않는다: 서버는 «있는가»와 끝 네 글자만 준다.
 *
 * 의존성: showToast (workspace.js) · _loadLlmAccounts (workspace.js)
 */

const PROVIDER_KEY_HELP = {
  anthropic: { label: "Anthropic API 키", placeholder: "sk-ant-…" },
  openai: { label: "OpenAI API 키", placeholder: "sk-…" },
  gemini: { label: "Google(Gemini) API 키", placeholder: "AIza…" },
};

/**
 * 프로바이더 카드에 붙는 키 입력 줄.
 * @param {string} providerId — anthropic | openai | gemini
 * @param {object} keyState — /api/settings/llm-keys 의 keys
 * @returns {HTMLElement}
 */
function _llmKeyRow(providerId, keyState) {
  const help = PROVIDER_KEY_HELP[providerId] || { label: "API 키", placeholder: "" };
  const known = (keyState || {})[providerId] || {};
  const wrap = document.createElement("div");
  wrap.className = "settings-key-row";

  const input = document.createElement("input");
  input.type = "password";
  input.className = "bib-input settings-key-input";
  input.placeholder = known.set ? `저장됨 (${known.hint}) — 바꾸려면 새 키 입력` : help.placeholder;
  input.setAttribute("aria-label", help.label);
  input.autocomplete = "off";

  const save = document.createElement("button");
  save.className = "text-btn text-btn-sm";
  save.textContent = "저장";
  save.addEventListener("click", async () => {
    const value = input.value.trim();
    if (!value) {
      showToast("키를 입력하세요.", "warning");
      return;
    }
    await _saveLlmKeys({ [providerId]: value }, save, "저장했습니다.");
    input.value = "";
  });

  const clear = document.createElement("button");
  clear.className = "text-btn text-btn-sm";
  clear.textContent = "지우기";
  clear.disabled = !known.set;
  clear.title = "이 프로바이더의 키를 서고 .env에서 지웁니다";
  clear.addEventListener("click", async () => {
    if (!confirm(`${help.label}를 지울까요? 이 프로바이더는 쓸 수 없게 됩니다.`)) return;
    await _saveLlmKeys({ [providerId]: "" }, clear, "지웠습니다.");
  });

  wrap.append(input, save, clear);
  return wrap;
}

async function _saveLlmKeys(payload, btn, okMessage) {
  const before = btn.textContent;
  btn.disabled = true;
  btn.textContent = "…";
  try {
    const res = await fetch("/api/settings/llm-keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    showToast(okMessage, "success");
    if (typeof _loadLlmAccounts === "function") await _loadLlmAccounts();
  } catch (e) {
    showToast(`저장 실패: ${e.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = before;
  }
}

/** Ollama 카드에 붙는 «지금 도는지 확인» 줄. */
function _ollamaRow() {
  const wrap = document.createElement("div");
  wrap.className = "settings-key-row";

  const out = document.createElement("span");
  out.className = "settings-llm-note";

  const btn = document.createElement("button");
  btn.className = "text-btn text-btn-sm";
  btn.textContent = "지금 확인";
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    out.textContent = "확인 중…";
    try {
      const res = await fetch("/api/settings/ollama");
      const d = await res.json();
      out.textContent = d.reachable
        ? `연결됨 — 모델 ${d.models.length}개 (${d.models.slice(0, 3).join(", ")}${d.models.length > 3 ? " …" : ""})`
        : `닿지 않습니다 — Ollama를 켜 두셨는지 확인하세요 (${d.base_url})`;
    } catch (e) {
      out.textContent = `확인 실패: ${e.message}`;
    } finally {
      btn.disabled = false;
    }
  });

  wrap.append(btn, out);
  return wrap;
}

/* ── 앱 업데이트 (D-103) ─────────────────────────────────────────── */

async function _checkUpdate() {
  const box = document.getElementById("settings-update");
  const btn = document.getElementById("btn-check-update");
  if (!box) return;
  if (btn) btn.disabled = true;
  box.innerHTML = '<div class="placeholder">확인 중…</div>';
  try {
    const res = await fetch("/api/app/update-check");
    const d = await res.json();
    box.innerHTML = "";

    const line = document.createElement("div");
    line.className = "settings-llm-note";
    if (d.error) {
      line.textContent = `${d.error} (지금 판 ${d.current})`;
    } else if (d.update_available) {
      line.textContent = `새 판이 있습니다 — ${d.latest} (지금 ${d.current})`;
    } else {
      line.textContent = `최신입니다 — ${d.current}`;
    }
    box.appendChild(line);

    if (d.title) {
      const title = document.createElement("div");
      title.className = "settings-llm-note";
      title.textContent = d.title;
      box.appendChild(title);
    }

    if (d.update_available && d.breaking) {
      const warn = document.createElement("div");
      warn.className = "settings-update-warn";
      warn.textContent =
        "이 판은 서고 형식을 바꿉니다(되돌릴 수 없는 변화). 릴리스 노트를 먼저 읽으세요.";
      box.appendChild(warn);
    }

    const row = document.createElement("div");
    row.className = "settings-key-row";
    const link = document.createElement("a");
    link.href = d.html_url;
    link.target = "_blank";
    link.rel = "noopener";
    link.className = "text-btn text-btn-sm";
    link.textContent = "릴리스 노트";
    row.appendChild(link);

    if (d.update_available) {
      if (d.can_self_update) {
        const go = document.createElement("button");
        go.className = "text-btn text-btn-primary text-btn-sm";
        go.textContent = "지금 받기";
        go.addEventListener("click", () => _applyUpdate(d, box, go));
        row.appendChild(go);
      } else {
        const note = document.createElement("span");
        note.className = "settings-llm-note";
        note.textContent = "이 설치는 Git 사본이 아니라 앱 안에서 받을 수 없습니다.";
        row.appendChild(note);
      }
    }
    box.appendChild(row);
  } catch (e) {
    box.innerHTML = `<div class="placeholder">확인 실패: ${e.message}</div>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function _applyUpdate(info, box, btn) {
  const warn = info.breaking
    ? "\n\n이 판은 서고 형식을 바꿉니다 — 되돌릴 수 없습니다."
    : "";
  if (!confirm(`${info.current} → ${info.latest} 로 올립니다.${warn}\n\n계속할까요?`)) return;
  btn.disabled = true;
  btn.textContent = "받는 중…";
  try {
    const res = await fetch("/api/app/update", { method: "POST" });
    const d = await res.json();
    const log = document.createElement("div");
    log.className = "settings-update-log";
    log.textContent = (d.steps || [])
      .map((s) => `[${s.ok ? "OK" : "실패"}] ${s.name}\n${s.output}`)
      .join("\n\n");
    box.appendChild(log);
    const hint = document.createElement("div");
    hint.className = d.ok ? "settings-update-ok" : "settings-update-warn";
    hint.textContent = d.hint || (d.ok ? "받았습니다." : "받지 못했습니다.");
    box.appendChild(hint);
    showToast(d.ok ? "새 판을 받았습니다. 서버를 껐다 켜세요." : "받지 못했습니다.", d.ok ? "success" : "error");
  } catch (e) {
    showToast(`업데이트 실패: ${e.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "지금 받기";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("btn-check-update");
  if (btn && !btn.dataset.bound) {
    btn.dataset.bound = "1";
    btn.addEventListener("click", _checkUpdate);
  }
});


/* ── 첫 실행 마법사 (D-102) ────────────────────────────────────────
 *
 * 왜 필요한가: 지금까지 처음 켠 사람이 마주하는 것은 빈 화면이었다. 서고를 만들고, 글자
 * 인식 엔진이 무엇이 깔렸는지 알아내고, .env를 메모장으로 열어 키를 넣어야 비로소 쓸 수
 * 있었다. 세 가지를 한 자리에서 끝낸다.
 *
 * 언제 뜨는가: 서고가 아직 없을 때. 한 번 끝내면(또는 「나중에」를 누르면) 다시 뜨지 않는다
 * — 브라우저에 기억한다. 설정에서 언제든 다시 열 수 있다.
 */

const WIZARD_SEEN_KEY = "ctb.setupWizardDone";

async function openSetupWizard(force = false) {
  if (!force) {
    try {
      if (localStorage.getItem(WIZARD_SEEN_KEY) === "1") return;
    } catch (_) {
      /* 막혀 있으면 그냥 띄운다 */
    }
  }
  let overlay = document.getElementById("setup-wizard-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "setup-wizard-overlay";
    overlay.className = "wizard-overlay";
    overlay.innerHTML = `
      <div class="wizard-box" role="dialog" aria-labelledby="wizard-title">
        <div class="wizard-head">
          <span id="wizard-title">처음 설정</span>
          <span class="wizard-step-dots" id="wizard-dots"></span>
        </div>
        <div class="wizard-body" id="wizard-body"></div>
        <div class="wizard-foot">
          <button class="text-btn" id="wizard-later">나중에</button>
          <div class="text-toolbar-spacer"></div>
          <button class="text-btn" id="wizard-prev">이전</button>
          <button class="text-btn text-btn-primary" id="wizard-next">다음</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    document.getElementById("wizard-later").addEventListener("click", () => _closeWizard(true));
    document.getElementById("wizard-prev").addEventListener("click", () => _wizardGo(-1));
    document.getElementById("wizard-next").addEventListener("click", () => _wizardGo(+1));
  }
  overlay.style.display = "flex";
  _wizardState.step = 0;
  await _renderWizard();
}

const _wizardState = { step: 0, steps: ["서고", "글자 인식", "AI 연결"] };

function _closeWizard(remember) {
  const o = document.getElementById("setup-wizard-overlay");
  if (o) o.style.display = "none";
  if (remember) {
    try {
      localStorage.setItem(WIZARD_SEEN_KEY, "1");
    } catch (_) {
      /* 기억하지 못해도 이번 판은 닫힌다 */
    }
  }
}

async function _wizardGo(delta) {
  const last = _wizardState.steps.length - 1;
  const next = _wizardState.step + delta;
  if (next > last) {
    _closeWizard(true);
    if (typeof showToast === "function") showToast("설정을 마쳤습니다.", "success");
    return;
  }
  _wizardState.step = Math.max(0, next);
  await _renderWizard();
}

async function _renderWizard() {
  const body = document.getElementById("wizard-body");
  const dots = document.getElementById("wizard-dots");
  const next = document.getElementById("wizard-next");
  const prev = document.getElementById("wizard-prev");
  if (!body) return;
  dots.textContent = _wizardState.steps
    .map((s, i) => (i === _wizardState.step ? `● ${s}` : "○"))
    .join("  ");
  prev.disabled = _wizardState.step === 0;
  next.textContent = _wizardState.step === _wizardState.steps.length - 1 ? "마침" : "다음";
  body.innerHTML = '<div class="placeholder">불러오는 중…</div>';

  if (_wizardState.step === 0) await _wizardLibrary(body);
  else if (_wizardState.step === 1) await _wizardOcr(body);
  else await _wizardLlm(body);
}

/** 1단계 — 서고. 없으면 한 번 눌러 만든다. */
async function _wizardLibrary(body) {
  let info = {};
  try {
    // /api/library에는 경로가 없다 — 서고 자리는 /api/settings의 library_path다
    info = await (await fetch("/api/settings")).json();
  } catch (_) {
    info = {};
  }
  const has = !!(info && info.library_path);
  body.innerHTML = `
    <p class="wizard-lead">작업물이 쌓이는 폴더입니다. 문헌·해석·설정이 모두 여기에 들어가고,
      <b>앱 폴더 밖</b>에 있어 앱을 새 판으로 갈아도 그대로 남습니다.</p>
    <div class="wizard-status ${has ? "ok" : "todo"}">
      ${has ? `쓰는 중: ${_wizEsc(info.library_path)}` : "아직 서고가 없습니다."}
    </div>
    <div class="settings-key-row">
      <button class="text-btn text-btn-primary" id="wiz-make-lib">
        ${has ? "다른 자리에 새로 만들기" : "기본 자리에 만들기"}
      </button>
      <span class="settings-llm-note">기본 자리: 내 문서 ▸ 고전서지서고</span>
    </div>`;
  const btn = document.getElementById("wiz-make-lib");
  if (btn) {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "만드는 중…";
      try {
        const r = await fetch("/api/library/quick-start", { method: "POST" });
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
        await _wizardLibrary(body);
        if (typeof loadLibraryInfo === "function") loadLibraryInfo();
      } catch (e) {
        if (typeof showToast === "function") showToast(`만들지 못했습니다: ${e.message}`, "error");
        btn.disabled = false;
      }
    });
  }
}

/** 2단계 — 글자 인식 엔진. 무엇이 되고 무엇이 왜 안 되는지 보여 준다. */
async function _wizardOcr(body) {
  let engines = [];
  try {
    const d = await (await fetch("/api/ocr/engines")).json();
    engines = d.engines || d || [];
  } catch (_) {
    engines = [];
  }
  const rows = (Array.isArray(engines) ? engines : [])
    .map((e) => {
      const ok = e.available !== false;
      const why = e.reason || e.unavailable_reason || "";
      return `<div class="wizard-row ${ok ? "ok" : "todo"}">
        <b>${_wizEsc(e.display_name || e.name || e.id || "엔진")}</b>
        <span>${ok ? "쓸 수 있음" : _wizEsc(why || "설치되지 않음")}</span>
      </div>`;
    })
    .join("");
  body.innerHTML = `
    <p class="wizard-lead">스캔 이미지에서 글자를 읽는 엔진입니다. <b>하나만 있어도 됩니다.</b>
      없어도 텍스트가 들어 있는 PDF는 그대로 쓸 수 있습니다.</p>
    ${rows || '<div class="placeholder">엔진 목록을 읽지 못했습니다.</div>'}
    <p class="wizard-lead">더 넣으려면 앱 폴더에서 아래를 실행하세요. 시간이 걸립니다.</p>
    <div class="settings-update-log">uv sync --extra ocr        # 가벼운 엔진(ONNX)
uv sync --extra ocr-full   # 무거운 엔진(torch 계열)</div>`;
}

/** 3단계 — AI 연결. 설정 패널과 같은 카드를 그대로 쓴다. */
async function _wizardLlm(body) {
  body.innerHTML = `
    <p class="wizard-lead">번역·주석 초안, 목차 읽기에 씁니다. <b>하나만 연결돼 있어도</b> 됩니다.
      키는 서고 폴더의 <code>.env</code>에 저장되므로 앱을 갈아도 남습니다.</p>
    <div id="wizard-llm-list" class="settings-llm-list"><div class="placeholder">불러오는 중…</div></div>`;
  const box = document.getElementById("wizard-llm-list");
  // 설정 패널의 목록을 그대로 옮겨 담는다 — 두 벌로 만들지 않는다.
  const src = document.getElementById("settings-llm-accounts");
  if (typeof _loadLlmAccounts === "function" && src) {
    await _loadLlmAccounts();
    box.innerHTML = src.innerHTML;
    // innerHTML 복사는 이벤트를 잃는다. 입력·단추는 설정 패널에서 쓰라고 안내한다.
    box.querySelectorAll("input, button").forEach((el) => {
      el.disabled = true;
    });
    const note = document.createElement("div");
    note.className = "settings-info-note";
    note.textContent =
      "키를 넣으려면 마침 뒤 왼쪽 아이콘 줄의 ⚙ 설정 ▸ LLM 연결에서 입력하세요.";
    box.appendChild(note);
  }
}

function _wizEsc(s) {
  const d = document.createElement("div");
  d.textContent = String(s == null ? "" : s);
  return d.innerHTML;
}

document.addEventListener("DOMContentLoaded", () => {
  const open = document.getElementById("btn-open-wizard");
  if (open && !open.dataset.bound) {
    open.dataset.bound = "1";
    open.addEventListener("click", () => openSetupWizard(true));
  }
  // 서고가 아직 없으면 처음 설정을 띄운다.
  setTimeout(async () => {
    try {
      const info = await (await fetch("/api/settings")).json();
      if (!info || !info.library_path) openSetupWizard(false);
    } catch (_) {
      /* 서버가 아직이면 다음 실행에 뜬다 */
    }
  }, 1200);
});
