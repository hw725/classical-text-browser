/**
 * 이체자 사전 관리 — 별도 메인 탭
 *
 * 기능:
 *   1. 다중 사전 관리 (생성/복제/삭제/활성화)
 *   2. 이체자 쌍 CRUD (추가/삭제/검색)
 *   3. 대량 가져오기 (CSV/TSV/JSON/텍스트)
 *   4. 내보내기 (JSON/CSV 다운로드)
 *   5. 정렬 (유니코드순/이체자 수 순)
 *
 * 의존성:
 *   - 별도 의존 없음 (독립 모듈)
 *
 * 왜 별도 탭인가:
 *   - 이체자 사전은 문헌 전체에 걸쳐 공유하는 자원
 *   - 검색, 정렬, 내보내기 등 체계적 관리가 필요
 *   - 대조 뷰의 부속이 아닌 독립적 관리 도구
 */

/* ──────────────────────────
   전역 상태
   ────────────────────────── */

const variantManagerState = {
  dicts: [],           // 사전 목록 [{name, file, active}]
  activeName: null,    // 활성 사전 이름
  variants: {},        // 현재 표시 중인 사전 데이터
  sortBy: "unicode",   // 정렬: "unicode" | "count"
  filterQuery: "",     // 검색어
};

/* ──────────────────────────
   초기화
   ────────────────────────── */

/**
 * 이체자 관리 탭을 초기화한다.
 * workspace.js의 DOMContentLoaded에서 호출.
 */
// eslint-disable-next-line no-unused-vars
function initVariantManager() {
  // 사전 선택 드롭다운 변경
  const dictSelect = document.getElementById("vm-dict-select");
  if (dictSelect) {
    dictSelect.addEventListener("change", () => {
      _loadDictContent(dictSelect.value);
    });
  }

  // 버튼 이벤트
  _bindClick("vm-btn-create", _createDict);
  _bindClick("vm-btn-copy", _copyDict);
  _bindClick("vm-btn-delete", _deleteDict);
  _bindClick("vm-btn-add-pair", _addPairDialog);
  _bindClick("vm-btn-import", _showImportDialog);
  _bindClick("vm-btn-export-json", () => _exportDict("json"));
  _bindClick("vm-btn-export-csv", () => _exportDict("csv"));

  // 정렬 토글
  _bindClick("vm-btn-sort", _toggleSort);

  // 검색
  const searchInput = document.getElementById("vm-search");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      variantManagerState.filterQuery = searchInput.value.trim();
      _renderVariantTable();
    });
  }

  // 삭제 버튼 이벤트 위임 (테이블 내 × 버튼)
  const tableBody = document.getElementById("vm-table-body");
  if (tableBody) {
    tableBody.addEventListener("click", (e) => {
      const btn = e.target.closest(".vm-delete-btn");
      if (!btn) return;
      const charA = btn.dataset.a;
      const charB = btn.dataset.b;
      _deletePair(charA, charB);
    });
  }
}

/**
 * 이체자 탭 활성화 시 호출.
 */
// eslint-disable-next-line no-unused-vars
function activateVariantMode() {
  _loadDictList();
}

/**
 * 이체자 탭 비활성화 시 호출.
 */
// eslint-disable-next-line no-unused-vars
function deactivateVariantMode() {
  // 정리할 것 없음
}

/* ──────────────────────────
   사전 목록 관리
   ────────────────────────── */

async function _loadDictList() {
  try {
    const res = await fetch("/api/variant-dicts");
    if (!res.ok) throw new Error("사전 목록 조회 실패");
    const data = await res.json();

    variantManagerState.dicts = data.dicts || [];

    // 드롭다운 갱신
    const select = document.getElementById("vm-dict-select");
    if (!select) return;

    select.innerHTML = "";
    let activeName = null;
    for (const d of variantManagerState.dicts) {
      const opt = document.createElement("option");
      opt.value = d.name;
      opt.textContent = d.active ? `${d.name} (활성)` : d.name;
      if (d.active) {
        opt.selected = true;
        activeName = d.name;
      }
      select.appendChild(opt);
    }

    variantManagerState.activeName = activeName;

    // 활성 사전 내용 로드
    if (activeName) {
      await _loadDictContent(activeName);
    }
  } catch (err) {
    console.error("사전 목록 로드 오류:", err);
    showToast("이체자 사전 목록을 불러올 수 없습니다: " + err.message, 'error');
  }
}

async function _loadDictContent(name) {
  try {
    const res = await fetch(`/api/variant-dicts/${encodeURIComponent(name)}`);
    if (!res.ok) throw new Error("사전 조회 실패");
    const data = await res.json();

    variantManagerState.variants = data.variants || {};

    // 통계 표시
    const statsEl = document.getElementById("vm-stats");
    if (statsEl) {
      statsEl.textContent = `${data.size || 0}자 / ${data.pair_count || 0}쌍`;
    }

    _renderVariantTable();
  } catch (err) {
    console.error("사전 내용 로드 오류:", err);
    showToast("이체자 사전을 불러올 수 없습니다: " + err.message, 'error');
  }
}

/* ──────────────────────────
   사전 CRUD
   ────────────────────────── */

async function _createDict() {
  const name = prompt("새 사전 이름 (영문/숫자/밑줄):");
  if (!name) return;

  try {
    const res = await fetch("/api/variant-dicts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!res.ok) {
      const err = await res.json();
      showToast(err.error || "사전 생성 실패", 'error');
      return;
    }
    showToast(`사전 '${name}' 생성 완료`, 'success');
    await _loadDictList();
  } catch (err) {
    showToast("사전 생성 오류: " + err.message, 'error');
  }
}

async function _copyDict() {
  const select = document.getElementById("vm-dict-select");
  const srcName = select ? select.value : null;
  if (!srcName) return;

  const newName = prompt(`'${srcName}' 복제 — 새 이름:`);
  if (!newName) return;

  try {
    const res = await fetch(`/api/variant-dicts/${encodeURIComponent(srcName)}/copy`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_name: newName }),
    });
    if (!res.ok) {
      const err = await res.json();
      showToast(err.error || "복제 실패", 'error');
      return;
    }
    showToast(`사전 '${newName}' 복제 완료`, 'success');
    await _loadDictList();
  } catch (err) {
    showToast("복제 오류: " + err.message, 'error');
  }
}

async function _deleteDict() {
  const select = document.getElementById("vm-dict-select");
  const name = select ? select.value : null;
  if (!name) return;

  if (!confirm(`사전 '${name}'을(를) 삭제하시겠습니까?`)) return;

  try {
    const res = await fetch(`/api/variant-dicts/${encodeURIComponent(name)}`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const err = await res.json();
      showToast(err.error || "삭제 실패", 'error');
      return;
    }
    showToast(`사전 '${name}' 삭제 완료`, 'success');
    await _loadDictList();
  } catch (err) {
    showToast("삭제 오류: " + err.message, 'error');
  }
}

/* ──────────────────────────
   이체자 쌍 관리
   ────────────────────────── */

function _addPairDialog() {
  const charA = prompt("글자 A:");
  if (!charA) return;
  const charB = prompt("글자 B (이체자):");
  if (!charB) return;

  _addPair(charA.trim(), charB.trim());
}

async function _addPair(charA, charB) {
  const select = document.getElementById("vm-dict-select");
  const name = select ? select.value : variantManagerState.activeName;
  if (!name) return;

  try {
    const res = await fetch(`/api/variant-dicts/${encodeURIComponent(name)}/pair`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ char_a: charA, char_b: charB }),
    });
    if (!res.ok) {
      const err = await res.json();
      showToast(err.error || "추가 실패", 'error');
      return;
    }
    await _loadDictContent(name);
  } catch (err) {
    showToast("추가 오류: " + err.message, 'error');
  }
}

async function _deletePair(charA, charB) {
  if (!confirm(`이체자 쌍 "${charA}" ↔ "${charB}"를 삭제하시겠습니까?`)) return;

  const select = document.getElementById("vm-dict-select");
  const name = select ? select.value : variantManagerState.activeName;
  if (!name) return;

  try {
    const res = await fetch(`/api/variant-dicts/${encodeURIComponent(name)}/pair`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ char_a: charA, char_b: charB }),
    });
    if (!res.ok) {
      const err = await res.json();
      showToast(err.error || "삭제 실패", 'error');
      return;
    }
    await _loadDictContent(name);
  } catch (err) {
    showToast("삭제 오류: " + err.message, 'error');
  }
}

/* ──────────────────────────
   가져오기 / 내보내기
   ────────────────────────── */

function _showImportDialog() {
  const select = document.getElementById("vm-dict-select");
  const name = select ? select.value : variantManagerState.activeName;
  if (!name) return;

  // 오버레이 생성
  const overlay = document.createElement("div");
  overlay.className = "vm-overlay";

  const dialog = document.createElement("div");
  dialog.className = "vm-dialog";
  dialog.innerHTML = `
    <h3 style="margin:0 0 8px">이체자 가져오기 — ${_escHtml(name)}</h3>
    <div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px">
      지원 형식: CSV, TSV, 텍스트, JSON. 한 줄에 3개 이상이면 모든 조합 등록.
    </div>
    <div style="margin-bottom:6px">
      <label>형식:
        <select id="vm-import-format" style="background:var(--bg-secondary);color:var(--text-primary);border:1px solid var(--border);padding:2px 4px">
          <option value="auto">자동 감지</option>
          <option value="csv">CSV (쉼표)</option>
          <option value="tsv">TSV (탭)</option>
          <option value="text">텍스트 (공백/↔)</option>
          <option value="json">JSON</option>
        </select>
      </label>
    </div>
    <textarea id="vm-import-text" placeholder="여기에 이체자 데이터를 붙여넣으세요..."
      style="width:100%;height:160px;background:var(--bg-secondary);color:var(--text-primary);border:1px solid var(--border);border-radius:4px;padding:6px;font-size:13px;box-sizing:border-box;resize:vertical"></textarea>
    <div style="margin-top:6px">
      <label style="cursor:pointer;color:var(--accent-blue,#3b82f6)">
        파일에서 불러오기
        <input type="file" id="vm-import-file" accept=".csv,.tsv,.txt,.json" style="display:none">
      </label>
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:10px">
      <button class="text-btn" id="vm-import-cancel">취소</button>
      <button class="text-btn text-btn-primary" id="vm-import-submit">가져오기</button>
    </div>
  `;

  overlay.appendChild(dialog);
  document.body.appendChild(overlay);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.remove();
  });

  document.getElementById("vm-import-cancel").addEventListener("click", () => overlay.remove());

  // 파일 선택 → textarea 채우기
  document.getElementById("vm-import-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      document.getElementById("vm-import-text").value = reader.result;
      const ext = file.name.split(".").pop().toLowerCase();
      const fmtSelect = document.getElementById("vm-import-format");
      if (ext === "csv") fmtSelect.value = "csv";
      else if (ext === "tsv") fmtSelect.value = "tsv";
      else if (ext === "json") fmtSelect.value = "json";
      else fmtSelect.value = "auto";
    };
    reader.readAsText(file, "UTF-8");
  });

  // 제출
  document.getElementById("vm-import-submit").addEventListener("click", async () => {
    const text = document.getElementById("vm-import-text").value;
    const fmt = document.getElementById("vm-import-format").value;
    if (!text.trim()) {
      showToast("가져올 데이터를 입력하세요.", 'warning');
      return;
    }

    try {
      const res = await fetch(`/api/variant-dicts/${encodeURIComponent(name)}/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, format: fmt }),
      });
      if (!res.ok) {
        const err = await res.json();
        showToast(err.error || "가져오기 실패", 'error');
        return;
      }
      const data = await res.json();
      let msg = `가져오기 완료 — 추가: ${data.added}쌍, 건너뜀: ${data.skipped}쌍, 총: ${data.size}자`;
      if (data.errors && data.errors.length > 0) {
        msg += ` (오류 ${data.errors.length}건)`;
      }
      showToast(msg, 'success');
      overlay.remove();
      await _loadDictContent(name);
    } catch (err) {
      showToast("가져오기 오류: " + err.message, 'error');
    }
  });
}

function _exportDict(format) {
  const select = document.getElementById("vm-dict-select");
  const name = select ? select.value : variantManagerState.activeName;
  if (!name) return;

  // 다운로드 링크 생성
  const url = `/api/variant-dicts/${encodeURIComponent(name)}/export?format=${format}`;
  const a = document.createElement("a");
  a.href = url;
  a.download = `${name}.${format === "csv" ? "csv" : "json"}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

/* ──────────────────────────
   테이블 렌더링
   ────────────────────────── */

function _toggleSort() {
  const state = variantManagerState;
  state.sortBy = state.sortBy === "unicode" ? "count" : "unicode";
  const btn = document.getElementById("vm-btn-sort");
  if (btn) {
    btn.textContent = state.sortBy === "unicode" ? "유니코드순" : "이체자 수 순";
  }
  _renderVariantTable();
}

function _renderVariantTable() {
  const tableBody = document.getElementById("vm-table-body");
  if (!tableBody) return;

  const variants = variantManagerState.variants;
  const query = variantManagerState.filterQuery;

  // 양방향 중복 제거하여 쌍 목록 생성
  const seen = new Set();
  const pairs = [];
  for (const [char, alts] of Object.entries(variants)) {
    if (!Array.isArray(alts)) continue;
    for (const alt of alts) {
      const key = [char, alt].sort().join("\u2194");
      if (!seen.has(key)) {
        seen.add(key);
        pairs.push({ charA: char, charB: alt, altCount: alts.length });
      }
    }
  }

  // 검색 필터
  const filtered = query
    ? pairs.filter(
        (p) => p.charA.includes(query) || p.charB.includes(query)
      )
    : pairs;

  // 정렬
  if (variantManagerState.sortBy === "count") {
    filtered.sort((a, b) => b.altCount - a.altCount || a.charA.localeCompare(b.charA));
  } else {
    filtered.sort((a, b) => a.charA.localeCompare(b.charA) || a.charB.localeCompare(b.charB));
  }

  // 렌더링 (최대 500개까지 표시 — 성능)
  const maxDisplay = 500;
  const displayList = filtered.slice(0, maxDisplay);

  if (displayList.length === 0) {
    tableBody.innerHTML = `<tr><td colspan="3" style="text-align:center;color:var(--text-secondary);padding:20px">${
      query ? `"${_escHtml(query)}" 검색 결과 없음` : "등록된 이체자가 없습니다"
    }</td></tr>`;
    return;
  }

  let html = "";
  for (const p of displayList) {
    html += `<tr>
      <td style="font-size:18px;text-align:center;width:50px">${_escHtml(p.charA)}</td>
      <td style="font-size:18px;text-align:center;width:50px">${_escHtml(p.charB)}</td>
      <td style="text-align:center;width:40px">
        <button class="vm-delete-btn" data-a="${_escAttr(p.charA)}" data-b="${_escAttr(p.charB)}" title="삭제">&times;</button>
      </td>
    </tr>`;
  }

  if (filtered.length > maxDisplay) {
    html += `<tr><td colspan="3" style="text-align:center;color:var(--text-secondary);padding:8px">
      ... 외 ${filtered.length - maxDisplay}쌍 (검색으로 범위를 좁혀주세요)
    </td></tr>`;
  }

  tableBody.innerHTML = html;
}

/* ──────────────────────────
   유틸리티
   ────────────────────────── */

function _bindClick(id, handler) {
  const el = document.getElementById(id);
  if (el) el.addEventListener("click", handler);
}

function _escHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function _escAttr(str) {
  return str.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}
