/**
 * 내용 트리 — 사이드바에서 Work → TextBlock(순서)로 문헌을 훑고, 블록을 누르면
 * 그 내용이 있는 쪽(PDF)으로 간다 (D-085 1단계).
 *
 * 왜 필요한가:
 *   원본 층(L1~L4)은 쪽 단위일 수밖에 없다. 그런데 교감이 끝난 뒤에는 연구자가
 *   쪽을 넘기며 내용을 찾는 게 아니라 **내용에서 쪽으로** 가야 한다. TextBlock에는
 *   이미 source_refs(쪽·레이아웃 블록)가 있는데, 지금까지는 「이 쪽에 어떤 블록이
 *   있나」(하단 엔티티 탭)만 있고 그 반대 방향이 없었다. 이 파일이 그 반대 방향이다.
 *
 * 저장 형식은 건드리지 않는다. /api/interpretations/{id}/contents 가 blocks/·works/를
 * 읽어 묶어 준 것을 그리기만 한다. 해석 층을 내용 단위로 저장하는 것(2단계)은
 * 별도 결정이다 — D-085.
 *
 * 의존성:
 *   viewerState (sidebar-tree.js) · goToPage (sidebar-tree.js)
 *   interpState (interpretation.js) · layoutState/_selectBlock (layout-editor.js)
 *   _treeEscHtml (sidebar-tree.js)
 */

const contentsState = {
  interpId: null, // 마지막으로 그린 해석 저장소
  data: null, // /contents 응답
  collapsedWorks: new Set(), // 접어 둔 Work id
};

/**
 * 「내용」 섹션을 보이거나 숨긴다.
 *
 * 왜 따로 있는가: 사이드바 섹션은 모두 HTML에서 display:none으로 시작하고 JS가
 * 모드에 따라 켠다. 이 섹션은 처음 만들 때 켜는 코드가 없어 **어디서도 보이지
 * 않았다** (v1.2.3 첫 배포에서 발견). 해석 섹션(interp-section)을 켜고 끄는 네 자리가
 * 이 함수를 같이 부른다 — 내용 트리는 해석 저장소가 있어야 뜨는 것이므로 같은 조건이다.
 * 추출 프로필(data-profile="collation" → hidden)에서는 hidden 속성이 우선하므로
 * 여기서 display를 비워도 보이지 않는다.
 */
function setContentsSectionVisible(visible) {
  const section = document.getElementById("contents-section");
  if (!section) return;
  section.style.display = visible ? "" : "none";
}

/**
 * 내용 트리를 다시 불러 그린다. 해석 저장소를 고르거나 편성이 바뀔 때 부른다.
 * interpState.interpId가 없으면 안내문만 남긴다.
 */
async function refreshContentsTree() {
  const container = document.getElementById("contents-tree");
  if (!container) return;

  const interpId = typeof interpState !== "undefined" ? interpState.interpId : null;
  if (!interpId) {
    contentsState.interpId = null;
    contentsState.data = null;
    container.innerHTML =
      '<div class="placeholder">해석 저장소를 선택하면 편성된 내용이 표시됩니다</div>';
    return;
  }

  const docId = typeof viewerState !== "undefined" ? viewerState.docId : null;
  const qs = docId ? `?document_id=${encodeURIComponent(docId)}` : "";
  try {
    const res = await fetch(`/api/interpretations/${encodeURIComponent(interpId)}/contents${qs}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      container.innerHTML = `<div class="placeholder">${_treeEscHtml(err.error || "내용 트리를 불러오지 못했습니다")}</div>`;
      return;
    }
    contentsState.interpId = interpId;
    contentsState.data = await res.json();
    _renderContentsTree(container);
    highlightContentsForPage(viewerState.pageNum);
  } catch (e) {
    container.innerHTML = `<div class="placeholder">내용 트리 오류: ${_treeEscHtml(e.message)}</div>`;
  }
}

function _renderContentsTree(container) {
  const data = contentsState.data;
  container.innerHTML = "";
  if (!data || data.total_blocks === 0) {
    container.innerHTML =
      '<div class="placeholder">편성된 TextBlock이 없습니다. 편성 탭에서 블록을 만들면 여기 나타납니다.</div>';
    return;
  }

  const groups = data.works.map((w) => ({ key: w.id, title: w.title, blocks: w.blocks }));
  if (data.unassigned && data.unassigned.length) {
    groups.push({ key: "__unassigned__", title: "(Work 미배정)", blocks: data.unassigned });
  }

  for (const g of groups) {
    if (!g.blocks.length) continue;
    const node = document.createElement("div");
    node.className = "tree-node contents-work";

    const header = document.createElement("div");
    header.className = "tree-node-header";
    const collapsed = contentsState.collapsedWorks.has(g.key);
    header.innerHTML =
      `<span class="tree-toggle">${collapsed ? "▶" : "▼"}</span>` +
      `<span class="tree-label" title="${_treeEscHtml(g.title)}">${_treeEscHtml(g.title)}</span>` +
      `<span class="contents-count">${g.blocks.length}</span>`;
    header.addEventListener("click", () => {
      if (contentsState.collapsedWorks.has(g.key)) contentsState.collapsedWorks.delete(g.key);
      else contentsState.collapsedWorks.add(g.key);
      _renderContentsTree(container);
      highlightContentsForPage(viewerState.pageNum);
    });
    node.appendChild(header);

    const children = document.createElement("div");
    children.className = "tree-children";
    children.style.display = collapsed ? "none" : "";
    for (const b of g.blocks) children.appendChild(_createBlockRow(b));
    node.appendChild(children);
    container.appendChild(node);
  }
}

/**
 * 블록 한 줄: [순번] 미리보기 … 쪽 배지들.
 * 줄을 누르면 첫 쪽으로, 배지를 누르면 그 쪽으로 간다. 두 쪽에 걸친 블록은 배지가 둘이다.
 */
function _createBlockRow(block) {
  const row = document.createElement("div");
  row.className = "tree-page contents-block";
  row.dataset.blockId = block.id || "";
  row.dataset.pages = (block.pages || []).map((p) => p.page).join(",");
  const seq = block.sequence_index != null ? `${block.sequence_index}. ` : "";
  row.title = `${seq}${block.preview}  (${block.char_count}자${block.status ? ", " + block.status : ""})`;

  const label = document.createElement("span");
  label.className = "tree-label contents-preview";
  label.textContent = `${seq}${block.preview || "(비어있음)"}`;
  row.appendChild(label);

  const badges = document.createElement("span");
  badges.className = "contents-badges";
  for (const p of block.pages || []) {
    const badge = document.createElement("button");
    badge.type = "button";
    badge.className = "contents-page-badge";
    badge.textContent = `${p.page}쪽`;
    badge.title = p.layout_block_ids.length
      ? `${p.page}쪽 · 레이아웃 블록 ${p.layout_block_ids.join(", ")}`
      : `${p.page}쪽`;
    badge.addEventListener("click", (ev) => {
      ev.stopPropagation();
      _jumpToBlockPage(block, p);
    });
    badges.appendChild(badge);
  }
  row.appendChild(badges);

  row.addEventListener("click", () => {
    const first = (block.pages || [])[0];
    if (first) _jumpToBlockPage(block, first);
    else showToast("이 블록에는 출처 쪽 정보가 없습니다.", "warning");
  });
  return row;
}

/**
 * 블록이 있는 쪽으로 이동하고, 레이아웃이 뜨면 해당 LayoutBlock을 선택(강조)한다.
 *
 * 권(part)이 참조에 있고 지금 보는 권과 다르면 권 선택기로 먼저 바꾼다.
 * 예전 참조에는 part_id가 없으므로 그때는 현재 권으로 간다.
 */
async function _jumpToBlockPage(block, pageRef) {
  if (pageRef.part_id && pageRef.part_id !== viewerState.partId) {
    // 다른 권이다. 트리 노드 클릭 경로(goToPage)는 현재 권 안에서만 찾으므로
    // 권·쪽을 함께 바꾸는 _selectPage(sidebar-tree.js)를 직접 부른다.
    if (typeof _selectPage === "function") {
      _selectPage(viewerState.docId, pageRef.part_id, pageRef.page, viewerState.documentInfo, null);
      if (typeof updatePartSelector === "function" && viewerState.documentInfo?.parts) {
        updatePartSelector(viewerState.documentInfo.parts, pageRef.part_id);
      }
    } else {
      showToast(`이 블록은 다른 권(${pageRef.part_id})에 있습니다. 권을 먼저 바꾸세요.`, "warning");
      return;
    }
  } else if (Number(viewerState.pageNum) !== Number(pageRef.page)) {
    if (typeof goToPage !== "function" || !goToPage(pageRef.page)) {
      showToast(`${pageRef.page}쪽으로 이동할 수 없습니다.`, "error");
      return;
    }
  }
  _selectLayoutBlocksWhenLoaded(pageRef.layout_block_ids || []);
  _markActiveBlock(block.id);
}

/**
 * 레이아웃(L3)이 비동기로 로드되므로 블록이 나타날 때까지 잠깐 기다린 뒤 선택한다.
 * 3초 안에 안 뜨면 조용히 포기한다 — 쪽 이동 자체는 이미 끝났다.
 */
function _selectLayoutBlocksWhenLoaded(blockIds) {
  if (!blockIds.length || typeof layoutState === "undefined") return;
  const target = blockIds[0];
  const started = Date.now();
  const tick = () => {
    const found = (layoutState.blocks || []).some((b) => b.block_id === target);
    if (found) {
      if (typeof _selectBlock === "function") _selectBlock(target);
      return;
    }
    if (Date.now() - started < 3000) setTimeout(tick, 150);
  };
  setTimeout(tick, 150);
}

function _markActiveBlock(blockId) {
  document.querySelectorAll(".contents-block.active").forEach((el) => el.classList.remove("active"));
  const row = document.querySelector(`.contents-block[data-block-id="${blockId}"]`);
  if (row) {
    row.classList.add("active");
    row.scrollIntoView({ block: "nearest" });
  }
}

/**
 * 현재 쪽에 있는 블록들을 트리에서 표시한다 (쪽 → 내용 방향의 동기화).
 * workspace.js의 onPageChanged에서 부른다.
 */
function highlightContentsForPage(pageNum) {
  const page = Number(pageNum);
  document.querySelectorAll(".contents-block").forEach((el) => {
    const pages = (el.dataset.pages || "").split(",").filter(Boolean).map(Number);
    el.classList.toggle("on-page", pages.includes(page));
  });
}
