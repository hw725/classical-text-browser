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
    // 서버는 라우터 캐시를 비웠다. 화면의 모델 드롭다운·추출 패널·마법사도 다시 채워야
    // 방금 넣은 연결이 «바로» 보인다(2026-09-05 지적 — 전에는 새로고침해야 했다).
    document.dispatchEvent(new CustomEvent("llm-accounts-changed"));
  } catch (e) {
    showToast(`저장 실패: ${e.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = before;
  }
}

/**
 * OpenAI(ChatGPT 계정) 카드 — 프록시 상태와 «시작·로그인» 단추 (D-107).
 *
 * 왜: 이 길은 키가 없고 프록시(Node)가 로그인을 대신한다. 전에는 프록시가 창 없이 떠서
 * 로그인이 필요해도 로그 파일을 열어야 주소를 알 수 있었다. 단추를 누르면 앱이 프록시를
 * 띄우고, 프록시가 브라우저를 열며, 주소가 찍히면 링크로도 보여 준다.
 */
function _oauthRow() {
  const wrap = document.createElement("div");
  wrap.className = "settings-key-row settings-oauth-row";

  const note = document.createElement("span");
  note.className = "settings-llm-note";
  note.textContent = "확인 중…";

  const btn = document.createElement("button");
  btn.className = "text-btn text-btn-sm";
  btn.textContent = "시작·로그인";

  const link = document.createElement("a");
  link.className = "text-btn text-btn-sm";
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = "브라우저에서 로그인 열기";
  link.hidden = true;

  wrap.append(note, btn, link);

  let timer = null;
  let ticks = 0; // 프록시는 떴는데 로그인을 안 하면 영원히 묻게 된다 — 5분(150틱) 상한
  // 마지막으로 본 상태. «안 됨 → 됨» 전이에서만 이벤트를 쏜다. 처음 물었을 때부터 «됨»이면
  // 쏘지 않는다 — 쏘면 마법사가 자기를 다시 그리며 새 줄을 만들고, 그 줄이 또 «됨»을 보고
  // 쏘는 무한 루프가 된다(2026-09-05 실측: /api/llm/models가 ERR_INSUFFICIENT_RESOURCES).
  let lastReady = null;
  const stop = () => {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
  };
  const render = (s) => {
    if (!s.npx) {
      note.textContent = "Node.js(npx)가 없어 이 길은 쓸 수 없습니다 — nodejs.org에서 LTS를 깔면 됩니다.";
      btn.disabled = true;
      stop();
      return;
    }
    if (s.ready) {
      note.textContent = `연결됨 — ${s.base_url}`;
      btn.textContent = "연결됨";
      btn.disabled = true;
      link.hidden = true;
      stop();
      if (lastReady === false) {
        // 방금 연결됐다 — 드롭다운이 구독 모델을 보게 한다
        document.dispatchEvent(new CustomEvent("llm-accounts-changed"));
      }
      lastReady = true;
      return;
    }
    lastReady = false;
    if (s.running) {
      note.textContent = "프록시가 뜨는 중… 로그인 창이 열리면 ChatGPT 계정으로 들어가세요.";
      btn.disabled = true;
    } else {
      note.textContent = "ChatGPT 구독으로 씁니다(키 없음). 누르면 프록시가 뜨고, 필요하면 로그인 창이 열립니다.";
      btn.textContent = "시작·로그인";
      btn.disabled = false;
    }
    if (s.login_url) {
      link.href = s.login_url;
      link.hidden = false;
    }
    if (!wrap.isConnected) stop();
  };
  const poll = async (initial = false) => {
    // 처음 한 번은 아직 DOM에 붙기 전에 불린다 — isConnected로 끊으면 상태를 영영 묻지 않는다
    // («확인 중…»이 단추를 누를 때까지 남았다, Codex 지적 2026-09-06).
    if (!initial && (++ticks > 150 || !wrap.isConnected)) {
      stop();
      return;
    }
    try {
      render(await (await fetch("/api/settings/oauth")).json());
    } catch (_) {
      /* 다음 틱에 다시 */
    }
  };
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    ticks = 0;
    try {
      const r = await fetch("/api/settings/oauth/start", { method: "POST" });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
      render(d);
      if (!timer && !d.ready) timer = setInterval(poll, 2000);
    } catch (e) {
      if (typeof showToast === "function") showToast(`프록시를 띄우지 못했습니다: ${e.message}`, "error");
      btn.disabled = false;
    }
  });
  poll(true);
  return wrap;
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
        : `닿지 않습니다 — Ollama를 켜 두셨는지 확인하세요. 시도한 주소: ${(d.tried || [d.base_url]).join(", ")}`
          + (d.error ? `
오류: ${d.error}` : "");
      out.style.whiteSpace = "pre-line";
    } catch (e) {
      out.textContent = `확인 실패: ${e.message}`;
    } finally {
      btn.disabled = false;
    }
  });

  // «로그인 필요»에서 끝내지 않는다 — 앱이 ollama signin을 띄우고 주소를 연다.
  const login = document.createElement("button");
  login.className = "text-btn text-btn-sm";
  login.textContent = "로그인";
  login.title = "ollama.com 계정으로 로그인(클라우드 모델용). 로컬 모델만 쓰면 필요 없습니다";
  const link = document.createElement("a");
  link.className = "text-btn text-btn-sm";
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = "로그인 창 열기";
  link.hidden = true;
  login.addEventListener("click", async () => {
    login.disabled = true;
    out.textContent = "로그인 주소를 받는 중…";
    try {
      const r = await fetch("/api/settings/ollama/signin", { method: "POST" });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
      if (d.url) {
        link.href = d.url;
        link.hidden = false;
        window.open(d.url, "_blank", "noopener");
        out.textContent = "브라우저에서 로그인한 뒤 「지금 확인」을 누르세요.";
      } else {
        out.textContent = "로그인 창이 열렸으면 그 안에서 진행하세요. 안 열렸으면 다시 누르세요.";
      }
      // 여기서 llm-accounts-changed를 쏘지 않는다 — 로그인이 끝난 게 아니고, 마법사가 이 줄을
      // 다시 그려 방금 띄운 「로그인 창 열기」 링크를 지워 버린다(리뷰 지적).
    } catch (e) {
      out.textContent = `로그인을 시작하지 못했습니다: ${e.message}`;
    } finally {
      login.disabled = false;
    }
  });

  wrap.append(btn, login, link, out);
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
    } else if (d.update_available && d.same_version) {
      line.textContent = d.from_zip
        ? `${d.current} 그대로지만 최신 판과 파일이 다릅니다(zip 설치) — 받으세요`
        : `${d.current} 그대로지만 고친 것이 ${d.commits_behind}건 있습니다 — 받으세요`;
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
        go.textContent = "받기";
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
  const what = info.same_version
    ? info.from_zip
      ? `${info.current} 안에서 고친 것을 받습니다(zip 설치를 git 사본으로 바꿉니다).`
      : `${info.current} 안에서 고친 것 ${info.commits_behind}건을 받습니다.`
    : `${info.current} → ${info.latest} 로 올립니다.`;
  if (!confirm(`${what}${warn}\n\n계속할까요?`)) return;
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
    btn.textContent = "받기";
  }
}

/**
 * 앱을 열면 새 판을 저절로 확인해 알린다(D-112). 받는 것은 사람이 누를 때만 — 도는 서버의
 * 코드를 뒤에서 바꾸지 않는다. 세션마다 한 번, 첫 화면이 다 뜬 뒤(8초).
 */
function _autoCheckUpdateOnce() {
  try {
    if (sessionStorage.getItem("ctb-update-checked")) return;
    sessionStorage.setItem("ctb-update-checked", "1");
  } catch (_) {
    /* 저장이 막힌 브라우저 — 매번 확인해도 해가 없다 */
  }
  setTimeout(async () => {
    try {
      const d = await (await fetch("/api/app/update-check")).json();
      if (!d || d.error || !d.update_available) return;
      const what = d.same_version ? `${d.current} 안에서 고친 것` : `새 판 ${d.latest}`;
      if (typeof showToast === "function") {
        showToast(`${what}이 있습니다 — 설정 ▸ 앱 업데이트 ▸ 「받기」`, "info");
      }
    } catch (_) {
      /* 오프라인이 정상이다 */
    }
  }, 8000);
}

document.addEventListener("DOMContentLoaded", () => {
  _autoCheckUpdateOnce();
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
  // 설치 진행 묻기는 마법사가 닫히면 그만둔다 — 설치 자체는 서버에서 계속 돈다.
  if (_extrasPollTimer) {
    clearInterval(_extrasPollTimer);
    _extrasPollTimer = null;
  }
  // 3단계의 «다시 그리기» 리스너도 뗀다 — 닫힌 뒤에도 키 저장마다 숨은 화면을 다시 그리지 않게.
  if (_wizardState.llmListener) {
    document.removeEventListener("llm-accounts-changed", _wizardState.llmListener);
    _wizardState.llmListener = null;
  }
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
  body.innerHTML =
    _wizardState.step === 1
      ? '<div class="placeholder">엔진을 확인하는 중… 처음이면 수십 초 걸릴 수 있습니다.</div>'
      : '<div class="placeholder">불러오는 중…</div>';

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
  // 더 넣을 수 있는 엔진 묶음과 지금 도는 설치(D-106). 사용자는 터미널을 쓰지 않는다 —
  // 단추를 누르면 서버가 uv sync를 대신 돌린다.
  let extras = { extras: [], job: { running: false } };
  try {
    extras = await (await fetch("/api/app/extras")).json();
  } catch (_) {
    /* 목록을 못 읽어도 엔진 상태는 보여 준다 */
  }
  const job = extras.job || { running: false };
  const extraRows = (extras.extras || []).map((x) => _extrasRowHtml(x, job)).join("");
  body.innerHTML = `
    <p class="wizard-lead">스캔 이미지에서 글자를 읽는 엔진입니다. <b>하나만 있어도 됩니다.</b>
      없어도 텍스트가 들어 있는 PDF는 그대로 쓸 수 있습니다.</p>
    ${rows || '<div class="placeholder">엔진 목록을 읽지 못했습니다.</div>'}
    <p class="wizard-lead">더 넣기 — 단추를 누르면 앱이 받아서 깝니다. 인터넷이 필요하고 몇 분 걸립니다.</p>
    <div id="wizard-extras">${extraRows || '<div class="placeholder">추가할 수 있는 엔진 목록을 읽지 못했습니다.</div>'}</div>
    <div id="wizard-extras-log" class="settings-update-log" ${job.running ? "" : "hidden"}></div>
    <p class="wizard-lead">한글 논문과 글자가 든 PDF는 본체만으로 다 됩니다. GPU판은 별도 환경 —
      사용자 가이드 7-A.6-2.</p>`;
  body.querySelectorAll("[data-install-extra]").forEach((btn) => {
    btn.addEventListener("click", () => _installExtra(btn.dataset.installExtra, body));
  });
  if (job.running) _pollExtras(body);
}

/** 엔진 묶음 한 줄 — 깔려 있음 / 설치 중 / [설치] 단추. */
function _extrasRowHtml(x, job) {
  const running = job.running && job.extra === x.name;
  let state;
  if (x.installed) state = '<span class="wizard-extra-state">깔려 있음</span>';
  else if (running) state = '<span class="wizard-extra-state">설치 중…</span>';
  else
    state = `<button class="text-btn text-btn-sm" data-install-extra="${_wizEsc(x.name)}"
      ${job.running ? "disabled" : ""}>설치 (${_wizEsc(x.size)})</button>`;
  return `<div class="wizard-row ${x.installed ? "ok" : "todo"}">
    <b>${_wizEsc(x.label)}</b>
    <span>${_wizEsc(x.for)}</span>
    ${state}
  </div>`;
}

async function _installExtra(name, body) {
  try {
    const r = await fetch(`/api/app/extras/${encodeURIComponent(name)}/install`, { method: "POST" });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
    if (typeof showToast === "function") showToast("받기 시작했습니다. 끝나면 알려 드립니다.", "info");
    await _wizardOcr(body); // «설치 중…»을 바로 보여 준다
  } catch (e) {
    if (typeof showToast === "function") showToast(`설치를 시작하지 못했습니다: ${e.message}`, "error");
  }
}

let _extrasPollTimer = null;

/** 설치가 끝날 때까지 2초마다 묻는다. 끝나면 로그를 남기고 엔진 목록을 다시 그린다. */
function _pollExtras(body) {
  if (_extrasPollTimer) return;
  const tick = async () => {
    let s;
    try {
      s = await (await fetch("/api/app/extras")).json();
    } catch (_) {
      return; // 잠깐 못 닿아도 다음 틱에 다시 본다
    }
    if (!s || !s.job) return; // 5xx가 JSON({detail})로 와도 타이머가 예외로 굳지 않게
    const log = document.getElementById("wizard-extras-log");
    const tail = (s.job.log || []).slice(-12).join("\n");
    if (log) {
      log.hidden = false;
      log.textContent = tail || "받는 중…";
    }
    if (!s.job.running) {
      clearInterval(_extrasPollTimer);
      _extrasPollTimer = null;
      if (typeof showToast === "function") {
        showToast(
          s.job.ok ? "엔진을 깔았습니다." : "설치가 실패했습니다. 기록을 보세요.",
          s.job.ok ? "success" : "error",
        );
      }
      // 실패해도 다시 그린다 — 안 그리면 «설치 중…»과 비활성 단추로 굳는다. 실패 기록은 남긴다.
      if (body.isConnected && _wizardState.step === 1) {
        await _wizardOcr(body);
        const again = document.getElementById("wizard-extras-log");
        if (again && !s.job.ok && tail) {
          again.hidden = false;
          again.textContent = tail;
        }
      }
    }
  };
  _extrasPollTimer = setInterval(tick, 2000);
  tick();
}

/** 3단계 — AI 연결. 키를 **여기서 바로** 넣는다 — 설정 패널과 같은 입력 줄을 쓴다. */
async function _wizardLlm(body) {
  let keyState = {};
  try {
    keyState = (await (await fetch("/api/settings/llm-keys")).json()).keys || {};
  } catch (_) {
    /* 상태를 못 읽어도 입력 줄은 보여 준다 */
  }
  body.innerHTML = `
    <p class="wizard-lead">번역·주석 초안, 목차 읽기에 씁니다. <b>하나만 연결돼 있어도</b> 됩니다.
      키는 서고 폴더에 저장되므로 앱을 갈아도 남고, 화면 어디에도 키 전체는 나오지 않습니다.
      지금 없으면 그냥 「마침」 — 설정 ▸ LLM 연결에서 언제든 넣습니다.</p>
    <div id="wizard-llm-list" class="settings-llm-list"></div>`;
  const box = document.getElementById("wizard-llm-list");

  const card = (title) => {
    const row = document.createElement("div");
    row.className = "settings-llm-row";
    const head = document.createElement("div");
    head.className = "settings-llm-head";
    const name = document.createElement("span");
    name.className = "settings-llm-name";
    name.textContent = title;
    head.appendChild(name);
    row.appendChild(head);
    box.appendChild(row);
    return row;
  };
  for (const pid of Object.keys(PROVIDER_KEY_HELP)) {
    card(PROVIDER_KEY_HELP[pid].label.replace(" API 키", "")).appendChild(_llmKeyRow(pid, keyState));
  }
  card("Ollama (내 컴퓨터, 무료)").appendChild(_ollamaRow());
  card("OpenAI — ChatGPT 계정으로 (구독 한도)").appendChild(_oauthRow());

  // 저장·지우기 뒤에는 «저장됨 (…)» 표시가 바뀌어야 한다 — 이 단계가 떠 있을 때만 다시 그린다.
  if (_wizardState.llmListener) {
    document.removeEventListener("llm-accounts-changed", _wizardState.llmListener);
  }
  _wizardState.llmListener = () => {
    const overlay = document.getElementById("setup-wizard-overlay");
    const shown = overlay && overlay.style.display !== "none";
    if (!shown || !body.isConnected || _wizardState.step !== 2) return;
    // 다른 칸에 치던 키를 잃지 않게 — 입력값을 챙겼다가 다시 그린 뒤 되돌려 넣는다.
    const typed = {};
    body.querySelectorAll("input[aria-label]").forEach((el) => {
      if (el.value) typed[el.getAttribute("aria-label")] = el.value;
    });
    _wizardLlm(body).then(() => {
      body.querySelectorAll("input[aria-label]").forEach((el) => {
        const v = typed[el.getAttribute("aria-label")];
        if (v) el.value = v;
      });
    });
  };
  document.addEventListener("llm-accounts-changed", _wizardState.llmListener);
}

function _wizEsc(s) {
  // 속성값에도 쓰므로 따옴표까지 — textContent→innerHTML은 & < >만 바꾼다.
  const d = document.createElement("div");
  d.textContent = String(s == null ? "" : s);
  return d.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
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
