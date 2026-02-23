/**
 * Phase 12-1: 사다리형 이분 Git 그래프.
 *
 * 왜 이렇게 하는가:
 *   원본 저장소(L1~L4)와 해석 저장소(L5~L7)의 커밋 이력을
 *   좌우 2개 레인으로 나란히 보여주면, 해석 작업이 어떤 원본
 *   시점을 기반했는지 직관적으로 파악할 수 있다.
 *   Based-On-Original trailer로 명시적 연결을, 타임스탬프로 추정 연결을 만든다.
 *
 * 모듈 구성:
 *   1. LAYER_COLORS / LINK_STYLES — 레이어별 색상·링크 스타일 상수
 *   2. calculateLayout() — 커밋의 X/Y 좌표 계산
 *   3. renderLadderGraph() — d3.js SVG 렌더링 + 인터랙션
 *   4. initGitGraph() — 탭 전환·API 호출·초기화
 */

/* ──────────────────────────────────────
   1. 색상 / 스타일 상수
   ────────────────────────────────────── */

const LAYER_COLORS = {
  // 원본 저장소
  L1: "#94a3b8", // slate
  L2: "#60a5fa", // blue
  L3: "#818cf8", // indigo
  L4: "#2563eb", // blue-dark
  // 해석 저장소
  L5: "#34d399", // emerald
  L5_punctuation: "#34d399",
  L5_hyeonto: "#10b981", // green
  L6: "#f59e0b", // amber
  L7: "#f97316", // orange
  unknown: "#6b7280", // gray
};

const LINK_STYLES = {
  explicit: { stroke: "#64748b", dasharray: "none", width: 1.5 },
  estimated: { stroke: "#94a3b8", dasharray: "6,3", width: 1 },
};

/* ──────────────────────────────────────
   2. 레이아웃 계산
   ────────────────────────────────────── */

/**
 * 두 저장소 커밋을 시간순 통합 정렬하여 X좌표를 계산한다.
 *
 * 입력: API 응답 데이터 { original, interpretation }
 * 출력: Map<hash, { x, y, lane }>
 */
function calculateLayout(data) {
  const NODE_GAP = 56; // 커밋 간 X 간격 (px)
  const LEFT_MARGIN = 70; // 좌측 여백
  const RIGHT_MARGIN = 40; // 우측 여백
  const LANE_LABEL_Y = 18; // 레인 라벨 Y
  const LANE_ORIGINAL_Y = 68; // 원본 레인 Y
  const LANE_INTERP_Y = 148; // 해석 레인 Y

  // 모든 커밋을 timestamp 오름차순 통합 정렬 (과거 → 최신)
  const allCommits = [
    ...data.original.commits.map((c) => ({ ...c, lane: "original" })),
    ...data.interpretation.commits.map((c) => ({
      ...c,
      lane: "interpretation",
    })),
  ].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

  const positions = new Map();
  allCommits.forEach((commit, index) => {
    positions.set(commit.hash, {
      x: index * NODE_GAP + LEFT_MARGIN,
      y: commit.lane === "original" ? LANE_ORIGINAL_Y : LANE_INTERP_Y,
      lane: commit.lane,
    });
  });

  const totalWidth = Math.max(
    580,
    allCommits.length * NODE_GAP + LEFT_MARGIN + RIGHT_MARGIN,
  );
  const totalHeight = 196;

  return {
    positions,
    allCommits,
    NODE_GAP,
    LEFT_MARGIN,
    RIGHT_MARGIN,
    LANE_LABEL_Y,
    LANE_ORIGINAL_Y,
    LANE_INTERP_Y,
    totalWidth,
    totalHeight,
  };
}

/* ──────────────────────────────────────
   3. d3.js SVG 렌더링
   ────────────────────────────────────── */

/**
 * 사다리형 이분 그래프를 SVG로 렌더링한다.
 *
 * container: DOM 요소 (div#git-graph-container)
 * data: API 응답 데이터
 */
function renderLadderGraph(container, data) {
  // 기존 SVG 제거
  container.innerHTML = "";

  if (!data.original.commits.length && !data.interpretation.commits.length) {
    container.innerHTML = '<div class="placeholder">커밋이 없습니다</div>';
    return;
  }

  const layout = calculateLayout(data);
  const {
    positions,
    allCommits,
    LEFT_MARGIN,
    RIGHT_MARGIN,
    LANE_LABEL_Y,
    LANE_ORIGINAL_Y,
    LANE_INTERP_Y,
    totalWidth,
    totalHeight,
  } = layout;

  const svg = d3
    .select(container)
    .append("svg")
    .attr("width", totalWidth)
    .attr("height", totalHeight)
    .attr("class", "git-graph-svg");

  // 화살표 마커 정의
  svg
    .append("defs")
    .append("marker")
    .attr("id", "arrowhead")
    .attr("viewBox", "0 0 10 10")
    .attr("refX", 8)
    .attr("refY", 5)
    .attr("markerWidth", 6)
    .attr("markerHeight", 6)
    .attr("orient", "auto")
    .append("path")
    .attr("d", "M 0 0 L 10 5 L 0 10 z")
    .attr("fill", "#64748b");

  // ── 레인 라벨 ──
  svg
    .append("text")
    .attr("x", LEFT_MARGIN)
    .attr("y", LANE_LABEL_Y)
    .attr("text-anchor", "start")
    .attr("class", "git-graph-lane-label")
    .text("원본 (L1~L4)");

  svg
    .append("text")
    .attr("x", LEFT_MARGIN)
    .attr("y", LANE_INTERP_Y - 24)
    .attr("text-anchor", "start")
    .attr("class", "git-graph-lane-label")
    .text("해석 (L5~L7)");

  // ── 레인 가로선 (배경) ──
  svg
    .append("line")
    .attr("x1", LEFT_MARGIN - 12)
    .attr("y1", LANE_ORIGINAL_Y)
    .attr("x2", totalWidth - RIGHT_MARGIN + 8)
    .attr("y2", LANE_ORIGINAL_Y)
    .attr("class", "git-graph-lane-line");

  svg
    .append("line")
    .attr("x1", LEFT_MARGIN - 12)
    .attr("y1", LANE_INTERP_Y)
    .attr("x2", totalWidth - RIGHT_MARGIN + 8)
    .attr("y2", LANE_INTERP_Y)
    .attr("class", "git-graph-lane-line");

  // ── 가로 연결선 (같은 레인 내 인접 커밋) ──
  const origCommits = allCommits.filter((c) => c.lane === "original");
  const interpCommits = allCommits.filter((c) => c.lane === "interpretation");

  _renderLaneLinks(svg, origCommits, positions);
  _renderLaneLinks(svg, interpCommits, positions);

  // ── 레인 간 연결선 (의존 관계) ──
  const linkSelection = svg
    .selectAll(".git-graph-link")
    .data(data.links)
    .enter()
    .append("path")
    .attr("class", "git-graph-link")
    .each(function (d) {
      const origPos = positions.get(d.original_hash);
      const interpPos = positions.get(d.interp_hash);
      if (!origPos || !interpPos) return;

      const style = LINK_STYLES[d.match_type] || LINK_STYLES.estimated;
      const startX = origPos.x;
      const startY = origPos.y + 8;
      const endX = interpPos.x;
      const endY = interpPos.y - 8;
      const elbowY = startY + (endY - startY) / 2;
      const path = `M ${startX} ${startY} L ${startX} ${elbowY} L ${endX} ${elbowY} L ${endX} ${endY}`;

      d3.select(this)
        .attr("d", path)
        .attr("fill", "none")
        .attr("stroke", style.stroke)
        .attr("stroke-width", style.width)
        .attr("stroke-dasharray", style.dasharray)
        .attr("marker-end", "url(#arrowhead)");
    });

  // ── 커밋 노드 ──
  const nodeData = allCommits.map((c) => {
    const pos = positions.get(c.hash);
    return { ...c, cx: pos.x, cy: pos.y };
  });

  const nodeGroup = svg
    .selectAll(".git-graph-node")
    .data(nodeData)
    .enter()
    .append("g")
    .attr("class", "git-graph-node")
    .attr("transform", (d) => `translate(${d.cx}, ${d.cy})`);

  // 원 (색상은 layers_affected 첫 번째 기준)
  nodeGroup
    .append("circle")
    .attr("r", 7)
    .attr("fill", (d) => {
      const layer = (d.layers_affected && d.layers_affected[0]) || "unknown";
      return LAYER_COLORS[layer] || LAYER_COLORS.unknown;
    })
    .attr("stroke", "#fff")
    .attr("stroke-width", 1.5);

  // 짧은 해시 텍스트
  nodeGroup
    .append("text")
    .attr("x", 0)
    .attr("y", (d) => (d.lane === "original" ? -12 : 18))
    .attr("text-anchor", "middle")
    .attr("class", "git-graph-hash")
    .text((d) => d.short_hash);

  // ── Phase 12-2: HEAD(현재 작업) 마커 ──
  const origHead = data.original.head_hash;
  const interpHead = data.interpretation.head_hash;

  nodeGroup.each(function (d) {
    const isHead = d.hash === origHead || d.hash === interpHead;
    if (!isHead) return;

    const g = d3.select(this);

    // 금색 테두리 링
    g.insert("circle", "circle")
      .attr("r", 12)
      .attr("fill", "none")
      .attr("stroke", "#ffd700")
      .attr("stroke-width", 2.5)
      .attr("class", "git-graph-head-ring");

    // "현재 작업" 라벨
    g.append("text")
      .attr("x", 0)
      .attr("y", d.lane === "original" ? -26 : 32)
      .attr("text-anchor", "middle")
      .attr("class", "git-graph-head-label")
      .text("현재 작업");
  });

  // ── 인터랙션 ──
  _addTooltip(nodeGroup);
  _addNodeClick(nodeGroup);
  _addLinkHighlight(linkSelection, nodeGroup);
}

/**
 * 같은 레인 내 인접 커밋 간 가로 연결선을 그린다.
 */
function _renderLaneLinks(svg, commits, positions) {
  for (let i = 0; i < commits.length - 1; i++) {
    const from = positions.get(commits[i].hash);
    const to = positions.get(commits[i + 1].hash);
    if (!from || !to) continue;

    svg
      .append("line")
      .attr("x1", from.x + 7)
      .attr("y1", from.y)
      .attr("x2", to.x - 7)
      .attr("y2", to.y)
      .attr("class", "git-graph-vertical");
  }
}

/* ──────────────────────────────────────
   4. 인터랙션
   ────────────────────────────────────── */

/**
 * 커밋 노드 호버 → 툴팁 표시.
 */
function _addTooltip(nodeSelection) {
  // 툴팁 요소가 없으면 생성
  let tooltip = document.getElementById("git-graph-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = "git-graph-tooltip";
    tooltip.className = "git-graph-tooltip";
    document.body.appendChild(tooltip);
  }

  nodeSelection
    .on("mouseenter", function (event, d) {
      const matchLabel =
        d.base_match_type === "explicit"
          ? "명시적"
          : d.base_match_type === "estimated"
            ? "추정"
            : "";
      const baseInfo = d.base_original_hash
        ? `<br><small>기반 원본: ${d.base_original_hash.substring(0, 7)} (${matchLabel})</small>`
        : "";
      const layers = (d.layers_affected || []).join(", ");

      tooltip.innerHTML =
        `<strong>${d.short_hash}</strong><br>` +
        `${_escapeHtml(d.message.split("\n")[0])}<br>` +
        `<small>${_escapeHtml(d.author)} · ${_formatDate(d.timestamp)}</small><br>` +
        `<small>레이어: ${layers}</small>` +
        baseInfo;
      tooltip.style.display = "block";
      tooltip.style.left = event.pageX + 12 + "px";
      tooltip.style.top = event.pageY - 10 + "px";
    })
    .on("mousemove", function (event) {
      tooltip.style.left = event.pageX + 12 + "px";
      tooltip.style.top = event.pageY - 10 + "px";
    })
    .on("mouseleave", function () {
      tooltip.style.display = "none";
    });
}

/**
 * 커밋 노드 클릭 → 상세 패널 표시 + 파일 목록 + 되돌리기 버튼.
 *
 * Phase 12-2: 기존 커밋 상세에 파일 미리보기와 되돌리기 기능을 추가한다.
 */
function _addNodeClick(nodeSelection) {
  nodeSelection.on("click", function (event, d) {
    const detail = document.getElementById("git-graph-detail");
    const title = document.getElementById("git-graph-detail-title");
    const body = document.getElementById("git-graph-detail-body");
    if (!detail || !title || !body) return;

    const layers = (d.layers_affected || []).join(", ");
    const matchLabel =
      d.base_match_type === "explicit"
        ? "명시적 매칭"
        : d.base_match_type === "estimated"
          ? "타임스탬프 추정"
          : "";
    const baseInfo = d.base_original_hash
      ? `<div class="git-detail-row"><span class="git-detail-label">기반 원본</span><code>${d.base_original_hash.substring(0, 7)}</code> <span class="git-detail-match">${matchLabel}</span></div>`
      : "";

    title.textContent = `${d.short_hash} — ${d.message.split("\n")[0]}`;
    body.innerHTML =
      `<div class="git-detail-row"><span class="git-detail-label">식별번호</span><code>${d.hash}</code></div>` +
      `<div class="git-detail-row"><span class="git-detail-label">작성자</span>${_escapeHtml(d.author)}</div>` +
      `<div class="git-detail-row"><span class="git-detail-label">시간</span>${_formatDate(d.timestamp)}</div>` +
      `<div class="git-detail-row"><span class="git-detail-label">레이어</span>${layers}</div>` +
      baseInfo +
      `<div class="git-detail-message"><pre>${_escapeHtml(d.message)}</pre></div>` +
      // Phase 12-2: 파일 목록 영역
      `<div class="git-detail-section-title">저장된 파일 목록</div>` +
      `<div id="git-detail-file-list" class="git-detail-file-list">` +
      `<span class="placeholder">불러오는 중...</span></div>` +
      // Phase 12-2: 되돌리기 버튼
      `<div class="git-detail-actions">` +
      `<button id="git-revert-btn" class="revert-btn" ` +
      `data-hash="${d.hash}" data-lane="${d.lane}">` +
      `이 버전으로 되돌리기</button></div>`;

    detail.style.display = "block";

    // 파일 목록 비동기 로드
    _loadCommitFiles(d);
    // 되돌리기 버튼 이벤트 연결
    _bindRevertButton();
  });
}

/**
 * 가로선 호버 → 연결된 노드만 하이라이트.
 */
function _addLinkHighlight(linkSelection, nodeSelection) {
  linkSelection
    .on("mouseenter", function (event, d) {
      nodeSelection.style("opacity", function (n) {
        return n.hash === d.original_hash || n.hash === d.interp_hash ? 1 : 0.2;
      });
      linkSelection.style("opacity", function (l) {
        return l === d ? 1 : 0.1;
      });
    })
    .on("mouseleave", function () {
      nodeSelection.style("opacity", 1);
      linkSelection.style("opacity", 1);
    });
}

/* ──────────────────────────────────────
   4-B. Phase 12-2: 파일 미리보기 + 되돌리기
   ────────────────────────────────────── */

/**
 * 커밋 시점의 파일 목록을 API에서 가져와 상세 패널에 표시한다.
 *
 * 왜 이렇게 하는가:
 *   연구자가 "이 시점에 무엇이 저장되어 있었는지" 확인할 수 있다.
 *   각 파일을 클릭하면 읽기 전용으로 내용을 미리볼 수 있다.
 */
async function _loadCommitFiles(commitData) {
  const fileListEl = document.getElementById("git-detail-file-list");
  if (!fileListEl) return;

  const repoType =
    commitData.lane === "original" ? "documents" : "interpretations";
  const repoId =
    commitData.lane === "original" ? _gitGraphDocId : _gitGraphInterpId;

  if (!repoId) {
    fileListEl.innerHTML =
      '<span class="placeholder">저장소 정보가 없습니다</span>';
    return;
  }

  try {
    const resp = await fetch(
      `/api/repos/${repoType}/${repoId}/commits/${commitData.hash}/files`,
    );
    if (!resp.ok) throw new Error("파일 목록 조회 실패");
    const data = await resp.json();

    if (data.error) {
      fileListEl.innerHTML = `<span class="placeholder">${_escapeHtml(data.error)}</span>`;
      return;
    }

    if (!data.files || data.files.length === 0) {
      fileListEl.innerHTML =
        '<span class="placeholder">파일이 없습니다</span>';
      return;
    }

    fileListEl.innerHTML = "";
    data.files.forEach((f) => {
      const item = document.createElement("div");
      item.className = "git-detail-file-item";
      item.textContent = f.path;
      item.title = `${f.path} (${_formatFileSize(f.size)})`;
      item.addEventListener("click", () => {
        _loadCommitFileContent(
          repoType,
          repoId,
          commitData.hash,
          f.path,
        );
      });
      fileListEl.appendChild(item);
    });
  } catch (err) {
    fileListEl.innerHTML =
      '<span class="placeholder">파일 목록을 불러올 수 없습니다</span>';
  }
}

/**
 * 커밋 시점의 특정 파일 내용을 읽기 전용으로 표시한다.
 *
 * 왜 이렇게 하는가:
 *   연구자가 과거 시점의 파일 내용을 안전하게 미리볼 수 있다.
 *   수정 불가(읽기 전용)로 표시하여 실수를 방지한다.
 */
async function _loadCommitFileContent(repoType, repoId, commitHash, filePath) {
  const body = document.getElementById("git-graph-detail-body");
  if (!body) return;

  // 기존 파일 뷰어가 있으면 제거 후 재생성
  let viewer = document.getElementById("git-detail-file-viewer");
  if (viewer) viewer.remove();

  viewer = document.createElement("div");
  viewer.id = "git-detail-file-viewer";
  viewer.className = "git-detail-file-viewer";
  body.appendChild(viewer);

  viewer.innerHTML =
    `<div class="git-detail-section-title">` +
    `${_escapeHtml(filePath)} <small>(읽기 전용)</small></div>` +
    '<div class="placeholder">불러오는 중...</div>';

  try {
    const resp = await fetch(
      `/api/repos/${repoType}/${repoId}/commits/${commitHash}/files/${filePath.split("/").map(encodeURIComponent).join("/")}`,
    );
    if (!resp.ok) throw new Error("파일 내용 조회 실패");
    const data = await resp.json();

    if (data.error && data.content == null) {
      viewer.innerHTML =
        `<div class="git-detail-section-title">${_escapeHtml(filePath)}</div>` +
        `<div class="placeholder">${_escapeHtml(data.error)}</div>`;
      return;
    }

    if (data.is_binary) {
      viewer.innerHTML =
        `<div class="git-detail-section-title">${_escapeHtml(filePath)}</div>` +
        '<div class="placeholder">(바이너리 파일 — 미리보기 불가)</div>';
      return;
    }

    // JSON 파일이면 정렬해서 표시
    let displayContent = data.content;
    if (filePath.endsWith(".json")) {
      try {
        displayContent = JSON.stringify(JSON.parse(data.content), null, 2);
      } catch {
        /* JSON 파싱 실패 시 원본 그대로 */
      }
    }

    viewer.innerHTML =
      `<div class="git-detail-section-title">` +
      `${_escapeHtml(filePath)} <small>(읽기 전용)</small></div>` +
      `<pre class="git-file-preview">${_escapeHtml(displayContent)}</pre>`;
  } catch (err) {
    viewer.innerHTML =
      `<div class="git-detail-section-title">${_escapeHtml(filePath)}</div>` +
      '<div class="placeholder">파일 내용을 불러올 수 없습니다</div>';
  }
}

/**
 * "이 버전으로 되돌리기" 버튼에 이벤트를 연결한다.
 *
 * 왜 이렇게 하는가:
 *   confirm() 다이얼로그로 한 번 더 확인하여 실수 방지.
 *   되돌리기는 새 커밋을 생성하므로 이력이 보존된다는 점을 안내한다.
 */
function _bindRevertButton() {
  const btn = document.getElementById("git-revert-btn");
  if (!btn) return;

  btn.addEventListener("click", () => {
    const hash = btn.dataset.hash;
    const lane = btn.dataset.lane;
    const shortHash = hash.substring(0, 7);

    const confirmed = confirm(
      `"${shortHash}" 시점으로 되돌리시겠습니까?\n\n` +
        `현재 작업 내용은 그대로 이력에 보존됩니다.\n` +
        `되돌리기 자체도 새로운 저장 시점으로 기록됩니다.`,
    );

    if (!confirmed) return;
    _executeRevert(hash, lane);
  });
}

/**
 * 되돌리기 API를 호출하고 결과를 표시한다.
 *
 * 왜 이렇게 하는가:
 *   POST /api/repos/{type}/{id}/revert 를 호출하여
 *   새 커밋을 생성하는 방식으로 안전하게 되돌린다.
 *   성공 시 그래프를 새로고침하여 변경 사항을 반영한다.
 */
async function _executeRevert(targetHash, lane) {
  const repoType = lane === "original" ? "documents" : "interpretations";
  const repoId = lane === "original" ? _gitGraphDocId : _gitGraphInterpId;

  if (!repoId) {
    if (typeof showToast === "function")
      showToast("저장소 정보가 없습니다.", "error");
    return;
  }

  const btn = document.getElementById("git-revert-btn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "되돌리는 중...";
  }

  try {
    const resp = await fetch(`/api/repos/${repoType}/${repoId}/revert`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_hash: targetHash }),
    });

    const result = await resp.json();

    if (!resp.ok || result.error) {
      if (typeof showToast === "function")
        showToast(result.error || "되돌리기 실패", "error");
      return;
    }

    if (!result.reverted) {
      if (typeof showToast === "function")
        showToast(
          result.message || "현재 상태가 이미 해당 시점과 동일합니다.",
          "info",
        );
      return;
    }

    if (typeof showToast === "function")
      showToast(
        `${targetHash.substring(0, 7)} 시점으로 되돌렸습니다. 새 저장 시점: ${result.new_short_hash}`,
        "success",
      );

    // 그래프 새로고침
    if (_gitGraphInterpId) {
      loadGitGraph(_gitGraphInterpId);
    }
  } catch (err) {
    if (typeof showToast === "function")
      showToast("되돌리기 중 오류가 발생했습니다: " + err.message, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "이 버전으로 되돌리기";
    }
  }
}

/* ──────────────────────────────────────
   5. 유틸리티
   ────────────────────────────────────── */

function _escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text || "";
  return div.innerHTML;
}

function _formatFileSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function _formatDate(isoString) {
  try {
    const d = new Date(isoString);
    return d.toLocaleString("ko-KR", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return isoString;
  }
}

/* ──────────────────────────────────────
   6. 초기화 + 탭 전환
   ────────────────────────────────────── */

/** 현재 선택된 해석 저장소 ID (workspace.js에서 설정) */
let _gitGraphInterpId = null;
/** 원본 문헌 ID (git-graph API 응답에서 자동 설정) */
let _gitGraphDocId = null;

/**
 * Git 그래프 모듈 초기화.
 * workspace.js의 DOMContentLoaded에서 호출된다.
 */
function initGitGraph() {
  // 뷰 탭 전환
  const tabs = document.querySelectorAll(".git-view-tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");

      const view = tab.dataset.view;
      const simpleView = document.getElementById("git-simple-view");
      const graphView = document.getElementById("git-graph-view");
      const controls = document.getElementById("git-graph-controls");

      if (view === "simple") {
        if (simpleView) simpleView.style.display = "";
        if (graphView) graphView.style.display = "none";
        if (controls) controls.style.display = "none";
      } else {
        if (simpleView) simpleView.style.display = "none";
        if (graphView) graphView.style.display = "";
        if (controls) controls.style.display = "";
        // 그래프 데이터 로드
        if (_gitGraphInterpId) {
          loadGitGraph(_gitGraphInterpId);
        }
      }
    });
  });

  // 상세 패널 닫기 버튼
  const closeBtn = document.getElementById("git-graph-detail-close");
  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      const detail = document.getElementById("git-graph-detail");
      if (detail) detail.style.display = "none";
    });
  }

  // 브랜치 드롭다운 변경 시 그래프 갱신
  const origBranch = document.getElementById("git-graph-orig-branch");
  const interpBranch = document.getElementById("git-graph-interp-branch");
  if (origBranch)
    origBranch.addEventListener("change", () => {
      if (_gitGraphInterpId) loadGitGraph(_gitGraphInterpId);
    });
  if (interpBranch)
    interpBranch.addEventListener("change", () => {
      if (_gitGraphInterpId) loadGitGraph(_gitGraphInterpId);
    });
}

/**
 * 해석 저장소 ID를 설정한다.
 * workspace.js에서 해석 저장소 선택 시 호출.
 */
function setGitGraphInterpId(interpId) {
  _gitGraphInterpId = interpId;
}

/**
 * 그래프 데이터를 API에서 가져와 렌더링한다.
 */
async function loadGitGraph(interpId) {
  const container = document.getElementById("git-graph-container");
  if (!container) return;

  container.innerHTML =
    '<div class="placeholder">그래프 데이터 로딩 중...</div>';

  const origBranch =
    document.getElementById("git-graph-orig-branch")?.value || "auto";
  const interpBranch =
    document.getElementById("git-graph-interp-branch")?.value || "auto";

  try {
    const params = new URLSearchParams({
      original_branch: origBranch,
      interp_branch: interpBranch,
      limit: "50",
      offset: "0",
    });

    const resp = await fetch(
      `/api/interpretations/${interpId}/git-graph?${params}`,
    );
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      container.innerHTML = `<div class="placeholder">오류: ${err.error || resp.statusText}</div>`;
      return;
    }

    const data = await resp.json();

    // Phase 12-2: 원본 문헌 ID 저장 (파일 조회/되돌리기 API에 필요)
    _gitGraphDocId = data.doc_id || null;

    // 브랜치 드롭다운 업데이트
    _updateBranchSelect(
      "git-graph-orig-branch",
      data.original.branches_available,
      data.original.branch,
    );
    _updateBranchSelect(
      "git-graph-interp-branch",
      data.interpretation.branches_available,
      data.interpretation.branch,
    );

    // d3.js 렌더링
    renderLadderGraph(container, data);
  } catch (err) {
    container.innerHTML = `<div class="placeholder">그래프 로딩 실패: ${err.message}</div>`;
  }
}

/**
 * 브랜치 드롭다운을 업데이트한다.
 */
function _updateBranchSelect(selectId, branches, current) {
  const sel = document.getElementById(selectId);
  if (!sel || !branches || !branches.length) return;

  // 현재 옵션과 동일하면 스킵
  const existing = Array.from(sel.options).map((o) => o.value);
  if (
    existing.length === branches.length &&
    existing.every((v, i) => v === branches[i])
  ) {
    sel.value = branches.includes(current) ? current : branches[0];
    return;
  }

  sel.innerHTML = "";
  branches.forEach((b) => {
    const opt = document.createElement("option");
    opt.value = b;
    opt.textContent = b;
    if (b === current) opt.selected = true;
    sel.appendChild(opt);
  });
}
