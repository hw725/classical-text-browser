/**
 * 검증 결과 패널 — 지금 서고의 파일이 제 스키마를 지키는가 (D-101).
 *
 * 왜 필요한가:
 *   스키마는 v1.2까지 «적어 두기만 한 것»이었다. 저장하는 쪽 몇 군데만 검증을 불렀고
 *   나머지는 아무도 보지 않았다 — 교환 형식 스키마가 구현과 다른 것도, 시험 픽스처가
 *   스키마를 어기고 있던 것도 그래서 몰랐다(D-100). 사람이 언제든 눌러 볼 수 있어야
 *   그런 어긋남이 조용히 쌓이지 않는다.
 *
 * 무엇을 보여 주는가: 검사한 파일 수 · 어긋난 곳 수 · 종류별 요약 · 어긋난 곳 목록
 * (파일 · 위치 · 무엇이 틀렸나). 파일을 고치지는 않는다 — 읽고 알리기만 한다.
 *
 * 의존성: viewerState (sidebar-tree.js) · interpState (interpretation.js) · _treeEscHtml
 */

const validationState = {
  loading: false,
  data: null,
  key: null, // 마지막으로 검사한 «문헌+해석» — 같은 것이면 다시 부르지 않는다
};

/**
 * 패널을 그린다. 활성화될 때와 「다시 검사」를 누를 때 부른다.
 * @param {boolean} force — 캐시를 무시하고 다시 검사한다
 */
async function loadValidation(force = false) {
  const box = document.getElementById("validation-panel-content");
  if (!box) return;

  const docId = typeof viewerState !== "undefined" ? viewerState.docId : null;
  const interpId = typeof interpState !== "undefined" ? interpState.interpId : null;
  if (!docId) {
    box.innerHTML = '<div class="placeholder">문헌을 고르면 검사합니다.</div>';
    validationState.data = null;
    validationState.key = null;
    return;
  }

  const key = `${docId}|${interpId || ""}`;
  if (!force && validationState.key === key && validationState.data) {
    _renderValidation(box);
    return;
  }
  if (validationState.loading) return;

  validationState.loading = true;
  box.innerHTML = '<div class="placeholder">검사하는 중…</div>';
  try {
    const qs = interpId ? `?interpretation_id=${encodeURIComponent(interpId)}` : "";
    const res = await fetch(`/api/documents/${encodeURIComponent(docId)}/validation${qs}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    validationState.data = data;
    validationState.key = key;
    _renderValidation(box);
  } catch (e) {
    box.innerHTML = `<div class="placeholder">검사하지 못했습니다: ${_treeEscHtml(e.message)}</div>`;
  } finally {
    validationState.loading = false;
  }
}

function _renderValidation(box) {
  const d = validationState.data;
  if (!d) return;
  const ok = d.issue_count === 0;
  const head =
    `<div class="val-head ${ok ? "val-ok" : "val-bad"}">` +
    `<span class="val-badge">${ok ? "이상 없음" : `어긋남 ${d.issue_count}`}</span>` +
    `<span class="val-sub">파일 ${d.checked}개 검사</span>` +
    `<button id="val-recheck" class="text-btn text-btn-sm" title="다시 검사">↻</button>` +
    "</div>";

  const groups = (d.groups || [])
    .map((g) => `<div class="val-group">${_treeEscHtml(g.label)} <b>${g.issues}</b></div>`)
    .join("");

  const items = (d.issues || [])
    .map(
      (it) =>
        '<div class="val-item">' +
        `<div class="val-item-file">[${_treeEscHtml(it.scope)}] ${_treeEscHtml(it.file)}</div>` +
        `<div class="val-item-where">${_treeEscHtml(it.where)}</div>` +
        `<div class="val-item-msg">${_treeEscHtml(it.message)}</div>` +
        "</div>",
    )
    .join("");

  const more = d.truncated
    ? '<div class="val-more">너무 많아 앞 200건만 보여 줍니다.</div>'
    : "";
  const body = ok
    ? '<div class="placeholder">검사한 파일이 모두 스키마를 지킵니다.</div>'
    : `<div class="val-groups">${groups}</div><div class="val-items">${items}</div>${more}`;

  box.innerHTML = head + body;
  const btn = document.getElementById("val-recheck");
  if (btn) btn.addEventListener("click", () => loadValidation(true));
}
