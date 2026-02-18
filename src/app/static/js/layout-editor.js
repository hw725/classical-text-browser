/**
 * 레이아웃 편집기 — PDF 위에 LayoutBlock 사각형을 그리고 속성을 편집한다.
 *
 * 기능:
 *   1. PDF 캔버스 위 투명 오버레이에서 마우스 드래그로 사각형 그리기
 *   2. 기존 사각형 선택 → 크기 조절 (모서리 핸들) / 이동 (드래그)
 *   3. 사각형 삭제 (Delete 키 또는 버튼)
 *   4. 블록 타입별 색상, reading_order 번호 표시
 *   5. 우측 패널에서 블록 속성 편집
 *   6. 저장 → L3_layout/page_NNN.json (layout_page.schema.json으로 검증)
 *
 * 의존성: sidebar-tree.js (viewerState), pdf-renderer.js (pdfState)
 *
 * 왜 이렇게 하는가:
 *   - D-002: LayoutBlock은 OCR이 읽는 순서를 지정하기 위한 영역 단위다.
 *   - 사람(연구자)이 이미지 위에 영역을 그리고 reading_order를 부여한다.
 *   - 이 데이터는 L3_layout/에 저장되어, 추후 OCR 파이프라인의 입력이 된다.
 */

/* ──────────────────────────
   레이아웃 편집기 상태
   ────────────────────────── */

const layoutState = {
  active: false,           // 레이아웃 모드 활성화 여부
  blocks: [],              // 현재 페이지의 LayoutBlock 배열
  selectedBlockId: null,   // 현재 선택된 블록 ID
  blockTypes: [],          // resources/block_types.json에서 로드한 블록 타입 목록
  isDirty: false,          // 수정 여부
  imageWidth: null,        // PDF 페이지의 원본 너비 (px)
  imageHeight: null,       // PDF 페이지의 원본 높이 (px)

  // 드래그 상태
  dragMode: null,          // null | "draw" | "move" | "resize"
  dragStartX: 0,
  dragStartY: 0,
  dragBlock: null,         // 드래그 대상 블록
  dragHandle: null,        // 리사이즈 핸들 위치 ("nw","ne","sw","se")
  dragOrigBbox: null,      // 드래그 시작 시의 원본 bbox

  // 핸들 크기 (px, 캔버스 좌표 기준)
  HANDLE_SIZE: 8,
};


/* ──────────────────────────
   초기화
   ────────────────────────── */

/**
 * 레이아웃 편집기를 초기화한다.
 * DOMContentLoaded 시 workspace.js에서 호출된다.
 */
// eslint-disable-next-line no-unused-vars
function initLayoutEditor() {
  _loadBlockTypes();
  _initOverlayEvents();
  _initPropsEvents();
}


/**
 * resources/block_types.json에서 블록 타입 목록을 로드한다.
 *
 * 왜 이렇게 하는가: 블록 타입별 색상과 라벨을 서버에서 가져와,
 *                    드롭다운과 캔버스 색상에 사용한다.
 */
async function _loadBlockTypes() {
  try {
    const res = await fetch("/api/resources/block_types");
    if (!res.ok) throw new Error("block_types API 응답 오류");
    const data = await res.json();
    layoutState.blockTypes = data.block_types || [];

    // block_type 드롭다운 채우기
    const select = document.getElementById("prop-block-type");
    if (select) {
      select.innerHTML = "";
      layoutState.blockTypes.forEach((bt) => {
        const opt = document.createElement("option");
        opt.value = bt.id;
        opt.textContent = `${bt.label} (${bt.id})`;
        select.appendChild(opt);
      });
    }
  } catch (err) {
    console.error("블록 타입 로드 실패:", err);
  }
}


/**
 * 블록 타입 ID로 색상을 반환한다.
 */
function _getBlockColor(blockType) {
  const bt = layoutState.blockTypes.find((t) => t.id === blockType);
  return bt ? bt.color : "#D1D5DB";
}


/* ──────────────────────────
   오버레이 캔버스: 크기 동기화
   ────────────────────────── */

/**
 * 오버레이 캔버스 크기를 PDF 캔버스에 맞춘다.
 *
 * 왜 이렇게 하는가: PDF 캔버스 위에 투명 오버레이를 정확히 겹치려면,
 *                    두 캔버스의 크기와 위치가 동일해야 한다.
 *                    CSS style.width/height는 표시 크기,
 *                    canvas.width/height는 렌더링 해상도.
 */
function _syncOverlaySize() {
  const pdfCanvas = document.getElementById("pdf-canvas");
  const overlay = document.getElementById("layout-overlay");
  if (!pdfCanvas || !overlay) return;

  // CSS 표시 크기를 동일하게 맞춤
  overlay.style.width = pdfCanvas.style.width;
  overlay.style.height = pdfCanvas.style.height;

  // 렌더링 해상도도 동일하게 (HiDPI 지원)
  overlay.width = pdfCanvas.width;
  overlay.height = pdfCanvas.height;
}


/**
 * PDF 캔버스의 좌표를 오버레이 내부 좌표로 변환한다.
 * (마우스 이벤트 → 캔버스 내부 좌표)
 */
function _canvasCoords(e) {
  const overlay = document.getElementById("layout-overlay");
  const rect = overlay.getBoundingClientRect();
  const scaleX = overlay.width / rect.width;
  const scaleY = overlay.height / rect.height;
  return {
    x: (e.clientX - rect.left) * scaleX,
    y: (e.clientY - rect.top) * scaleY,
  };
}


/**
 * 캔버스 내부 좌표를 이미지 좌표(bbox용)로 변환한다.
 *
 * 왜 이렇게 하는가: bbox는 원본 이미지 기준 좌표여야 한다.
 *                    캔버스 좌표 = 이미지 좌표 × scale × devicePixelRatio 이므로,
 *                    역변환이 필요하다.
 */
function _canvasToImage(cx, cy) {
  const outputScale = window.devicePixelRatio || 1;
  return {
    x: cx / outputScale / pdfState.scale,
    y: cy / outputScale / pdfState.scale,
  };
}

/**
 * 이미지 좌표를 캔버스 내부 좌표로 변환한다.
 */
function _imageToCanvas(ix, iy) {
  const outputScale = window.devicePixelRatio || 1;
  return {
    x: ix * pdfState.scale * outputScale,
    y: iy * pdfState.scale * outputScale,
  };
}


/* ──────────────────────────
   오버레이 렌더링: 모든 블록 그리기
   ────────────────────────── */

/**
 * 오버레이 캔버스에 모든 LayoutBlock을 다시 그린다.
 *
 * 왜 이렇게 하는가: 블록 추가/수정/삭제/선택 변경 때마다 전체를 다시 그린다.
 *                    Canvas는 "즉시 모드" 렌더링이므로, 변경 시 매번 clear & redraw한다.
 */
function _redrawOverlay() {
  const overlay = document.getElementById("layout-overlay");
  if (!overlay) return;

  _syncOverlaySize();
  const ctx = overlay.getContext("2d");
  ctx.clearRect(0, 0, overlay.width, overlay.height);

  layoutState.blocks.forEach((block) => {
    const [x1, y1, x2, y2] = block.bbox;
    const p1 = _imageToCanvas(x1, y1);
    const p2 = _imageToCanvas(x2, y2);
    const w = p2.x - p1.x;
    const h = p2.y - p1.y;

    const color = _getBlockColor(block.block_type);
    const isSelected = block.block_id === layoutState.selectedBlockId;

    // 반투명 채우기
    ctx.fillStyle = color + "33"; // 20% 투명도
    ctx.fillRect(p1.x, p1.y, w, h);

    // 테두리
    ctx.strokeStyle = color;
    ctx.lineWidth = isSelected ? 3 : 2;
    if (isSelected) {
      ctx.setLineDash([]);
    } else {
      ctx.setLineDash([]);
    }
    ctx.strokeRect(p1.x, p1.y, w, h);

    // reading_order 번호 표시 (좌상단)
    ctx.fillStyle = color;
    const fontSize = Math.max(14, 18 * (window.devicePixelRatio || 1));
    ctx.font = `bold ${fontSize}px sans-serif`;
    const label = `${block.reading_order}`;
    const tm = ctx.measureText(label);
    const pad = 4;
    // 배경 사각형
    ctx.fillStyle = color;
    ctx.fillRect(p1.x, p1.y, tm.width + pad * 2, fontSize + pad);
    // 텍스트
    ctx.fillStyle = "#FFFFFF";
    ctx.fillText(label, p1.x + pad, p1.y + fontSize);

    // 선택된 블록: 리사이즈 핸들 (4모서리)
    if (isSelected) {
      const hs = layoutState.HANDLE_SIZE;
      ctx.fillStyle = "#FFFFFF";
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      const corners = [
        { x: p1.x, y: p1.y },         // nw
        { x: p2.x, y: p1.y },         // ne
        { x: p1.x, y: p2.y },         // sw
        { x: p2.x, y: p2.y },         // se
      ];
      corners.forEach((c) => {
        ctx.fillRect(c.x - hs / 2, c.y - hs / 2, hs, hs);
        ctx.strokeRect(c.x - hs / 2, c.y - hs / 2, hs, hs);
      });
    }
  });
}


/* ──────────────────────────
   오버레이 이벤트: 마우스 드래그
   ────────────────────────── */

function _initOverlayEvents() {
  const overlay = document.getElementById("layout-overlay");
  if (!overlay) return;

  overlay.addEventListener("mousedown", _onMouseDown);
  overlay.addEventListener("mousemove", _onMouseMove);
  overlay.addEventListener("mouseup", _onMouseUp);
  overlay.addEventListener("mouseleave", _onMouseUp);

  // Delete 키로 블록 삭제
  document.addEventListener("keydown", (e) => {
    if (!layoutState.active) return;
    if (e.key === "Delete" && layoutState.selectedBlockId) {
      _deleteSelectedBlock();
    }
  });
}


/**
 * 마우스다운: 클릭 위치에 따라 draw/move/resize 모드를 결정한다.
 */
function _onMouseDown(e) {
  if (!layoutState.active) return;
  e.preventDefault();

  const pos = _canvasCoords(e);

  // 1. 선택된 블록의 리사이즈 핸들 확인
  if (layoutState.selectedBlockId) {
    const handle = _hitTestHandle(pos);
    if (handle) {
      const block = layoutState.blocks.find(
        (b) => b.block_id === layoutState.selectedBlockId
      );
      layoutState.dragMode = "resize";
      layoutState.dragHandle = handle;
      layoutState.dragBlock = block;
      layoutState.dragOrigBbox = [...block.bbox];
      layoutState.dragStartX = pos.x;
      layoutState.dragStartY = pos.y;
      return;
    }
  }

  // 2. 기존 블록 클릭 확인 (이동)
  const hitBlock = _hitTestBlock(pos);
  if (hitBlock) {
    _selectBlock(hitBlock.block_id);
    layoutState.dragMode = "move";
    layoutState.dragBlock = hitBlock;
    layoutState.dragOrigBbox = [...hitBlock.bbox];
    layoutState.dragStartX = pos.x;
    layoutState.dragStartY = pos.y;
    return;
  }

  // 3. 빈 영역 클릭 → 새 사각형 그리기
  _selectBlock(null);
  layoutState.dragMode = "draw";
  layoutState.dragStartX = pos.x;
  layoutState.dragStartY = pos.y;
}


/**
 * 마우스이동: 현재 dragMode에 따라 동작을 수행한다.
 */
function _onMouseMove(e) {
  if (!layoutState.active || !layoutState.dragMode) {
    // 커서 모양 변경
    _updateCursor(e);
    return;
  }
  e.preventDefault();

  const pos = _canvasCoords(e);
  const dx = pos.x - layoutState.dragStartX;
  const dy = pos.y - layoutState.dragStartY;

  if (layoutState.dragMode === "draw") {
    _handleDrawMove(pos);
  } else if (layoutState.dragMode === "move") {
    _handleMoveMove(dx, dy);
  } else if (layoutState.dragMode === "resize") {
    _handleResizeMove(pos, dx, dy);
  }
}


/**
 * 마우스업: 드래그 완료 처리.
 */
function _onMouseUp(e) {
  if (!layoutState.active || !layoutState.dragMode) return;

  if (layoutState.dragMode === "draw") {
    _handleDrawEnd(e);
  }

  layoutState.dragMode = null;
  layoutState.dragBlock = null;
  layoutState.dragHandle = null;
  layoutState.dragOrigBbox = null;
}


/**
 * 커서 모양을 현재 위치에 따라 변경한다.
 */
function _updateCursor(e) {
  const overlay = document.getElementById("layout-overlay");
  if (!overlay || !layoutState.active) return;

  const pos = _canvasCoords(e);

  // 리사이즈 핸들 위에 있으면 리사이즈 커서
  if (layoutState.selectedBlockId) {
    const handle = _hitTestHandle(pos);
    if (handle) {
      const cursorMap = { nw: "nwse-resize", se: "nwse-resize", ne: "nesw-resize", sw: "nesw-resize" };
      overlay.style.cursor = cursorMap[handle];
      return;
    }
  }

  // 블록 위에 있으면 이동 커서
  if (_hitTestBlock(pos)) {
    overlay.style.cursor = "move";
    return;
  }

  // 빈 영역 → 십자 커서 (그리기)
  overlay.style.cursor = "crosshair";
}


/* ──────────────────────────
   드래그 모드: draw (새 사각형 그리기)
   ────────────────────────── */

function _handleDrawMove(pos) {
  // 임시 사각형을 오버레이에 표시
  _redrawOverlay();
  const overlay = document.getElementById("layout-overlay");
  const ctx = overlay.getContext("2d");

  const x = Math.min(layoutState.dragStartX, pos.x);
  const y = Math.min(layoutState.dragStartY, pos.y);
  const w = Math.abs(pos.x - layoutState.dragStartX);
  const h = Math.abs(pos.y - layoutState.dragStartY);

  ctx.strokeStyle = "#3B82F6";
  ctx.lineWidth = 2;
  ctx.setLineDash([6, 3]);
  ctx.strokeRect(x, y, w, h);
  ctx.setLineDash([]);
}

function _handleDrawEnd(e) {
  const pos = _canvasCoords(e);
  const x1c = Math.min(layoutState.dragStartX, pos.x);
  const y1c = Math.min(layoutState.dragStartY, pos.y);
  const x2c = Math.max(layoutState.dragStartX, pos.x);
  const y2c = Math.max(layoutState.dragStartY, pos.y);

  // 너무 작은 사각형은 무시 (최소 10px)
  if (x2c - x1c < 10 || y2c - y1c < 10) {
    _redrawOverlay();
    return;
  }

  // 캔버스 좌표 → 이미지 좌표
  const p1 = _canvasToImage(x1c, y1c);
  const p2 = _canvasToImage(x2c, y2c);

  // 새 블록 생성
  const pageNum = viewerState.pageNum || 1;
  const blockNum = layoutState.blocks.length + 1;
  const blockId = `p${String(pageNum).padStart(2, "0")}_b${String(blockNum).padStart(2, "0")}`;

  const newBlock = {
    block_id: blockId,
    block_type: "main_text",
    bbox: [
      Math.round(p1.x),
      Math.round(p1.y),
      Math.round(p2.x),
      Math.round(p2.y),
    ],
    reading_order: layoutState.blocks.length,
    writing_direction: "vertical_rtl",
    line_style: null,
    font_size_class: null,
    ocr_config: null,
    refers_to_block: null,
    skip: false,
  };

  layoutState.blocks.push(newBlock);
  layoutState.isDirty = true;
  _selectBlock(blockId);
  _updateBlockList();
  _updateLayoutSaveStatus("modified");
}


/* ──────────────────────────
   드래그 모드: move (블록 이동)
   ────────────────────────── */

function _handleMoveMove(dx, dy) {
  const block = layoutState.dragBlock;
  if (!block) return;

  const orig = layoutState.dragOrigBbox;
  const dImg = _canvasToImage(
    layoutState.dragStartX + dx,
    layoutState.dragStartY + dy
  );
  const origImg = _canvasToImage(layoutState.dragStartX, layoutState.dragStartY);
  const imgDx = dImg.x - origImg.x;
  const imgDy = dImg.y - origImg.y;

  block.bbox = [
    Math.round(orig[0] + imgDx),
    Math.round(orig[1] + imgDy),
    Math.round(orig[2] + imgDx),
    Math.round(orig[3] + imgDy),
  ];

  layoutState.isDirty = true;
  _updateLayoutSaveStatus("modified");
  _redrawOverlay();
}


/* ──────────────────────────
   드래그 모드: resize (블록 크기 조절)
   ────────────────────────── */

function _handleResizeMove(pos, dx, dy) {
  const block = layoutState.dragBlock;
  if (!block) return;

  const orig = layoutState.dragOrigBbox;
  const handle = layoutState.dragHandle;

  // 원본 bbox를 캔버스 좌표로 변환
  const cp1 = _imageToCanvas(orig[0], orig[1]);
  const cp2 = _imageToCanvas(orig[2], orig[3]);

  let nx1 = cp1.x, ny1 = cp1.y, nx2 = cp2.x, ny2 = cp2.y;

  if (handle === "nw") { nx1 = cp1.x + dx; ny1 = cp1.y + dy; }
  if (handle === "ne") { nx2 = cp2.x + dx; ny1 = cp1.y + dy; }
  if (handle === "sw") { nx1 = cp1.x + dx; ny2 = cp2.y + dy; }
  if (handle === "se") { nx2 = cp2.x + dx; ny2 = cp2.y + dy; }

  // 최소 크기 보장
  if (Math.abs(nx2 - nx1) < 10 || Math.abs(ny2 - ny1) < 10) return;

  // 정규화 (x1 < x2, y1 < y2)
  const imgP1 = _canvasToImage(Math.min(nx1, nx2), Math.min(ny1, ny2));
  const imgP2 = _canvasToImage(Math.max(nx1, nx2), Math.max(ny1, ny2));

  block.bbox = [
    Math.round(imgP1.x),
    Math.round(imgP1.y),
    Math.round(imgP2.x),
    Math.round(imgP2.y),
  ];

  layoutState.isDirty = true;
  _updateLayoutSaveStatus("modified");
  _redrawOverlay();
}


/* ──────────────────────────
   히트 테스트: 블록/핸들 클릭 판정
   ────────────────────────── */

/**
 * 캔버스 좌표가 어떤 블록 위에 있는지 확인한다.
 * 여러 블록이 겹치면 가장 마지막 (위에 그려진) 블록을 반환한다.
 */
function _hitTestBlock(pos) {
  for (let i = layoutState.blocks.length - 1; i >= 0; i--) {
    const block = layoutState.blocks[i];
    const p1 = _imageToCanvas(block.bbox[0], block.bbox[1]);
    const p2 = _imageToCanvas(block.bbox[2], block.bbox[3]);
    if (pos.x >= p1.x && pos.x <= p2.x && pos.y >= p1.y && pos.y <= p2.y) {
      return block;
    }
  }
  return null;
}

/**
 * 선택된 블록의 리사이즈 핸들에 마우스가 있는지 확인한다.
 * 반환: "nw" | "ne" | "sw" | "se" | null
 */
function _hitTestHandle(pos) {
  if (!layoutState.selectedBlockId) return null;
  const block = layoutState.blocks.find(
    (b) => b.block_id === layoutState.selectedBlockId
  );
  if (!block) return null;

  const p1 = _imageToCanvas(block.bbox[0], block.bbox[1]);
  const p2 = _imageToCanvas(block.bbox[2], block.bbox[3]);
  const hs = layoutState.HANDLE_SIZE * 1.5; // 약간 넓은 히트 영역

  const corners = [
    { name: "nw", x: p1.x, y: p1.y },
    { name: "ne", x: p2.x, y: p1.y },
    { name: "sw", x: p1.x, y: p2.y },
    { name: "se", x: p2.x, y: p2.y },
  ];

  for (const c of corners) {
    if (Math.abs(pos.x - c.x) <= hs && Math.abs(pos.y - c.y) <= hs) {
      return c.name;
    }
  }
  return null;
}


/* ──────────────────────────
   블록 선택 / 삭제
   ────────────────────────── */

function _selectBlock(blockId) {
  layoutState.selectedBlockId = blockId;
  _redrawOverlay();
  _updatePropsForm();
  _updateBlockList();
}

function _deleteSelectedBlock() {
  if (!layoutState.selectedBlockId) return;
  layoutState.blocks = layoutState.blocks.filter(
    (b) => b.block_id !== layoutState.selectedBlockId
  );
  layoutState.selectedBlockId = null;
  layoutState.isDirty = true;
  _updateLayoutSaveStatus("modified");
  _redrawOverlay();
  _updatePropsForm();
  _updateBlockList();
}


/* ──────────────────────────
   우측 패널: 블록 속성 편집 폼
   ────────────────────────── */

function _initPropsEvents() {
  // 속성 변경 이벤트
  const fields = [
    "prop-block-type", "prop-reading-order", "prop-writing-dir",
    "prop-refers-to", "prop-line-style", "prop-font-size",
  ];
  fields.forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("change", _onPropChange);
    }
  });

  // 삭제 버튼
  const delBtn = document.getElementById("prop-delete");
  if (delBtn) {
    delBtn.addEventListener("click", _deleteSelectedBlock);
  }

  // 저장 버튼
  const saveBtn = document.getElementById("layout-save");
  if (saveBtn) {
    saveBtn.addEventListener("click", _saveLayout);
  }
}


/**
 * 속성 폼의 값이 변경될 때 블록 데이터를 업데이트한다.
 */
function _onPropChange() {
  const block = layoutState.blocks.find(
    (b) => b.block_id === layoutState.selectedBlockId
  );
  if (!block) return;

  block.block_type = document.getElementById("prop-block-type").value;
  block.reading_order = parseInt(
    document.getElementById("prop-reading-order").value, 10
  ) || 0;
  block.writing_direction = document.getElementById("prop-writing-dir").value;

  const refVal = document.getElementById("prop-refers-to").value;
  block.refers_to_block = refVal || null;

  const lsVal = document.getElementById("prop-line-style").value;
  block.line_style = lsVal || null;

  const fsVal = document.getElementById("prop-font-size").value;
  block.font_size_class = fsVal || null;

  layoutState.isDirty = true;
  _updateLayoutSaveStatus("modified");
  _redrawOverlay();
  _updateBlockList();
}


/**
 * 선택된 블록의 속성을 폼에 표시한다.
 */
function _updatePropsForm() {
  const form = document.getElementById("layout-props-form");
  if (!form) return;

  if (!layoutState.selectedBlockId) {
    form.style.display = "none";
    return;
  }

  const block = layoutState.blocks.find(
    (b) => b.block_id === layoutState.selectedBlockId
  );
  if (!block) {
    form.style.display = "none";
    return;
  }

  form.style.display = "";
  document.getElementById("prop-block-id").value = block.block_id;
  document.getElementById("prop-block-type").value = block.block_type;
  document.getElementById("prop-reading-order").value = block.reading_order;
  document.getElementById("prop-writing-dir").value =
    block.writing_direction || "vertical_rtl";
  document.getElementById("prop-line-style").value = block.line_style || "";
  document.getElementById("prop-font-size").value = block.font_size_class || "";

  // refers_to_block 드롭다운 채우기 (같은 페이지의 다른 블록)
  const refSelect = document.getElementById("prop-refers-to");
  refSelect.innerHTML = '<option value="">없음</option>';
  layoutState.blocks.forEach((b) => {
    if (b.block_id !== block.block_id) {
      const opt = document.createElement("option");
      opt.value = b.block_id;
      const bt = layoutState.blockTypes.find((t) => t.id === b.block_type);
      opt.textContent = `${b.block_id} (${bt ? bt.label : b.block_type})`;
      if (b.block_id === block.refers_to_block) opt.selected = true;
      refSelect.appendChild(opt);
    }
  });
}


/* ──────────────────────────
   우측 패널: 전체 블록 목록
   ────────────────────────── */

function _updateBlockList() {
  const listEl = document.getElementById("layout-block-list");
  const countEl = document.getElementById("layout-block-count");
  if (!listEl) return;

  if (countEl) countEl.textContent = `블록: ${layoutState.blocks.length}`;

  // reading_order 순으로 정렬된 사본
  const sorted = [...layoutState.blocks].sort(
    (a, b) => a.reading_order - b.reading_order
  );

  listEl.innerHTML = "";
  sorted.forEach((block) => {
    const item = document.createElement("div");
    const color = _getBlockColor(block.block_type);
    const bt = layoutState.blockTypes.find((t) => t.id === block.block_type);
    const label = bt ? bt.label : block.block_type;
    const isSelected = block.block_id === layoutState.selectedBlockId;

    item.className = "block-list-item" + (isSelected ? " selected" : "");
    item.innerHTML = `
      <span class="block-list-color" style="background:${color}"></span>
      <span class="block-list-order">${block.reading_order}</span>
      <span class="block-list-label">${label}</span>
      <span class="block-list-id">${block.block_id}</span>
    `;

    item.addEventListener("click", () => {
      _selectBlock(block.block_id);
    });

    listEl.appendChild(item);
  });
}


/* ──────────────────────────
   저장 상태 표시
   ────────────────────────── */

function _updateLayoutSaveStatus(status) {
  const el = document.getElementById("layout-save-status");
  if (!el) return;
  const map = {
    saved: { text: "저장됨", cls: "status-saved" },
    modified: { text: "수정됨", cls: "status-modified" },
    saving: { text: "저장 중...", cls: "status-saving" },
    error: { text: "저장 실패", cls: "status-error" },
    empty: { text: "", cls: "" },
  };
  const info = map[status] || map.empty;
  el.textContent = info.text;
  el.className = "text-save-status " + info.cls;
}


/* ──────────────────────────
   API: 레이아웃 로드 / 저장
   ────────────────────────── */

/**
 * 현재 페이지의 레이아웃을 API에서 로드한다.
 *
 * 호출: 레이아웃 모드 진입 시, 페이지 변경 시.
 */
// eslint-disable-next-line no-unused-vars
async function loadPageLayout(docId, partId, pageNum) {
  if (!docId || !partId || !pageNum) return;

  const url = `/api/documents/${docId}/pages/${pageNum}/layout?part_id=${partId}`;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error("레이아웃 API 응답 오류");
    const data = await res.json();

    layoutState.blocks = data.blocks || [];
    layoutState.imageWidth = data.image_width;
    layoutState.imageHeight = data.image_height;
    layoutState.selectedBlockId = null;
    layoutState.isDirty = false;

    _updateLayoutSaveStatus(data._meta?.exists ? "saved" : "empty");
    _redrawOverlay();
    _updatePropsForm();
    _updateBlockList();
  } catch (err) {
    console.error("레이아웃 로드 실패:", err);
    layoutState.blocks = [];
    _redrawOverlay();
    _updateBlockList();
  }
}


/**
 * 현재 레이아웃을 API에 저장한다.
 */
async function _saveLayout() {
  const { docId, partId, pageNum } = viewerState;
  if (!docId || !partId || !pageNum) return;

  _updateLayoutSaveStatus("saving");

  // 이미지 크기 정보: PDF 페이지의 원래 크기 사용
  let imgW = layoutState.imageWidth;
  let imgH = layoutState.imageHeight;
  if (!imgW && pdfState.pdfDoc) {
    try {
      const page = await pdfState.pdfDoc.getPage(pageNum);
      const vp = page.getViewport({ scale: 1.0 });
      imgW = Math.round(vp.width);
      imgH = Math.round(vp.height);
    } catch (_) { /* 무시 */ }
  }

  // 블록 중 draft 속성(_draft) 제거하고, 스키마에 없는 필드도 정리
  const cleanBlocks = layoutState.blocks.map(b => {
    const clean = { ...b };
    // 스키마에 없는 내부 전용 필드 제거
    delete clean._draft;
    delete clean._draft_id;
    delete clean._confidence;
    delete clean.notes;  // 스키마에 없으므로 제거
    return clean;
  });

  // analysis_method: draft 블록이 하나라도 있으면 llm, 아니면 manual
  const hasLlmBlocks = layoutState.blocks.some(b => b._draft);
  const method = hasLlmBlocks ? "llm" : "manual";

  const payload = {
    part_id: partId,
    page_number: pageNum,
    image_width: imgW,
    image_height: imgH,
    analysis_method: method,
    blocks: cleanBlocks,
  };

  const url = `/api/documents/${docId}/pages/${pageNum}/layout?part_id=${partId}`;
  try {
    const res = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || "저장 실패");
    }
    layoutState.isDirty = false;
    _updateLayoutSaveStatus("saved");
  } catch (err) {
    console.error("레이아웃 저장 실패:", err);
    _updateLayoutSaveStatus("error");
  }
}


/* ──────────────────────────
   모드 전환: 레이아웃 모드 활성화/비활성화
   ────────────────────────── */

/**
 * 레이아웃 모드를 활성화한다.
 */
// eslint-disable-next-line no-unused-vars
function activateLayoutMode() {
  layoutState.active = true;
  const overlay = document.getElementById("layout-overlay");
  if (overlay) {
    overlay.style.display = "block";
    _syncOverlaySize();
  }

  // 현재 페이지의 레이아웃 로드
  if (viewerState.docId && viewerState.partId && viewerState.pageNum) {
    loadPageLayout(viewerState.docId, viewerState.partId, viewerState.pageNum);
  }
}

/**
 * 레이아웃 모드를 비활성화한다.
 */
// eslint-disable-next-line no-unused-vars
function deactivateLayoutMode() {
  layoutState.active = false;
  layoutState.selectedBlockId = null;
  const overlay = document.getElementById("layout-overlay");
  if (overlay) {
    overlay.style.display = "none";
  }
}


/* ──────────────────────────
   Phase 10-2: LLM 레이아웃 분석
   ────────────────────────── */

/**
 * LLM 관련 UI를 초기화한다.
 *
 * 왜 layout-editor.js에 넣는가:
 *   AI 분석은 레이아웃 편집기의 확장 기능이다.
 *   분석 결과(Draft)를 기존 블록 편집 UI에 통합한다.
 */
function _initLlmLayoutUI() {
  // 모델 목록 로드
  _loadLlmModels();
  // LLM 상태 로드
  _loadLlmStatus();

  // AI 분석 버튼
  const analyzeBtn = document.getElementById("llm-analyze-btn");
  if (analyzeBtn) {
    analyzeBtn.addEventListener("click", _runLlmAnalysis);
  }

  // 비교 버튼
  const compareBtn = document.getElementById("llm-compare-btn");
  if (compareBtn) {
    compareBtn.addEventListener("click", _runLlmComparison);
  }
}


/**
 * GET /api/llm/models → 드롭다운에 모델 목록 표시.
 */
async function _loadLlmModels() {
  const select = document.getElementById("llm-model-select");
  if (!select) return;

  try {
    const res = await fetch("/api/llm/models");
    if (!res.ok) return;
    const models = await res.json();

    // 기존 옵션 초기화 (자동 유지)
    select.innerHTML = '<option value="auto">자동 (폴백순서)</option>';

    for (const m of models) {
      const opt = document.createElement("option");
      opt.value = `${m.provider}:${m.model}`;
      const icon = m.available ? "●" : "○";
      const costLabel = m.cost === "free" ? "" : " [유료]";
      opt.textContent = `${icon} ${m.display}${costLabel}`;
      opt.disabled = !m.available;
      select.appendChild(opt);
    }

    // 비교 모드 옵션
    const compareOpt = document.createElement("option");
    compareOpt.value = "compare";
    compareOpt.textContent = "비교 모드";
    select.appendChild(compareOpt);
  } catch {
    // 서버 미연결 시 무시
  }
}


/**
 * GET /api/llm/status → 상태 인디케이터 표시.
 */
async function _loadLlmStatus() {
  const indicators = document.getElementById("llm-status-indicators");
  const costDisplay = document.getElementById("llm-cost-display");
  if (!indicators) return;

  try {
    const [statusRes, usageRes] = await Promise.all([
      fetch("/api/llm/status"),
      fetch("/api/llm/usage"),
    ]);

    if (statusRes.ok) {
      const status = await statusRes.json();
      let html = "";
      for (const [id, info] of Object.entries(status)) {
        const icon = info.available ? "🟢" : "⚫";
        const name = info.display_name || id;
        html += `<span class="llm-provider-indicator" title="${name}">${icon}</span>`;
      }
      indicators.innerHTML = html;
    }

    if (usageRes.ok && costDisplay) {
      const usage = await usageRes.json();
      const cost = usage.total_cost_usd || 0;
      const budget = usage.budget_usd || 10;
      costDisplay.textContent = `$${cost.toFixed(2)} / $${budget.toFixed(2)}`;
    }
  } catch {
    // 무시
  }
}


/**
 * AI 분석 실행.
 */
async function _runLlmAnalysis() {
  if (!viewerState.docId || viewerState.pageNum == null) {
    _setLlmStatus("문헌/페이지를 먼저 선택하세요.");
    return;
  }

  const select = document.getElementById("llm-model-select");
  const selectedValue = select ? select.value : "auto";

  // 비교 모드 선택 시 비교 함수로 위임
  if (selectedValue === "compare") {
    return _runLlmComparison();
  }

  // force_provider, force_model 파싱
  let params = "";
  if (selectedValue !== "auto") {
    const parts = selectedValue.split(":", 2);
    params = `?force_provider=${encodeURIComponent(parts[0])}`;
    if (parts[1] && parts[1] !== "auto") {
      params += `&force_model=${encodeURIComponent(parts[1])}`;
    }
  }

  _setLlmStatus("AI 분석 중...");
  const analyzeBtn = document.getElementById("llm-analyze-btn");
  if (analyzeBtn) analyzeBtn.disabled = true;

  try {
    const url = `/api/llm/analyze-layout/${viewerState.docId}/${viewerState.pageNum}${params}`;
    const res = await fetch(url, { method: "POST" });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "분석 실패");
    }

    // Draft 결과를 블록으로 변환
    _applyDraftToBlocks(data);

    // 분석 결과를 L3에 자동 저장 (OCR 실행의 전제 조건)
    // 사용자가 저장 버튼을 따로 누를 필요 없이, 분석 완료 시 바로 저장한다.
    await _saveLayout();

    _setLlmStatus(
      `분석 완료·저장됨 (${data.provider || "?"}, ${(data.elapsed_sec || 0).toFixed(1)}s)`
    );
  } catch (err) {
    _setLlmStatus(`오류: ${err.message}`);
  } finally {
    if (analyzeBtn) analyzeBtn.disabled = false;
  }
}


/**
 * 비교 분석 실행.
 */
async function _runLlmComparison() {
  if (!viewerState.docId || viewerState.pageNum == null) {
    _setLlmStatus("문헌/페이지를 먼저 선택하세요.");
    return;
  }

  _setLlmStatus("여러 모델 비교 중...");

  try {
    const url = `/api/llm/compare-layout/${viewerState.docId}/${viewerState.pageNum}`;
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targets: null }),  // 사용 가능한 모든 모델
    });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "비교 실패");
    }

    // 비교 결과 다이얼로그 표시
    _showComparisonResults(data);
    _setLlmStatus(`비교 완료: ${data.length}개 모델`);
  } catch (err) {
    _setLlmStatus(`비교 오류: ${err.message}`);
  }
}


/**
 * Draft 결과를 레이아웃 블록으로 적용한다.
 *
 * Draft의 response_data.blocks를 기존 layoutState.blocks에 추가.
 * 점선 스타일로 표시하여 기존 블록과 구분.
 */
function _applyDraftToBlocks(draft) {
  const blocks = draft.response_data?.blocks;
  if (!blocks || !Array.isArray(blocks)) {
    _setLlmStatus("분석 결과에 블록이 없습니다.");
    return;
  }

  // 기존 블록과 합침 (draft 블록은 _draft 플래그)
  // 페이지 번호: 현재 viewerState.pageNum에서 추출 (없으면 01)
  const pNum = String(viewerState.pageNum || 1).padStart(2, "0");
  for (const b of blocks) {
    // block_id 형식: 스키마 패턴 ^p\d+_b\d+$ 준수
    const bIdx = String(layoutState.blocks.length + 1).padStart(2, "0");
    // block_type 검증: 스키마 enum에 없는 값은 "unknown"으로 대체
    const validBlockTypes = [
      "main_text", "annotation", "preface", "colophon", "memorial",
      "page_title", "page_number", "seal", "illustration",
      "marginal_note", "table_of_contents", "unknown"
    ];
    const rawType = b.block_type || "main_text";
    const safeType = validBlockTypes.includes(rawType) ? rawType : "unknown";
    const newBlock = {
      block_id: `p${pNum}_b${bIdx}`,
      block_type: safeType,
      bbox: _ratioToPixelBbox(b.bbox_ratio),
      reading_order: b.reading_order || layoutState.blocks.length + 1,
      writing_direction: "vertical_rtl",
      notes: b.notes || "",
      _draft: true,           // Draft 표시
      _draft_id: draft.draft_id,
      _confidence: b.confidence,
    };
    layoutState.blocks.push(newBlock);
  }

  layoutState.isDirty = true;
  _redrawOverlay();
  _updateBlockList();
}


/**
 * bbox_ratio (0~1 비율) → 픽셀 좌표로 변환.
 */
function _ratioToPixelBbox(ratioArr) {
  if (!ratioArr || ratioArr.length !== 4) return [0, 0, 100, 100];

  const w = layoutState.imageWidth || 1000;
  const h = layoutState.imageHeight || 1400;

  // [x_min, y_min, x_max, y_max] 비율 → 픽셀 변환
  let x1 = Math.round(ratioArr[0] * w);
  let y1 = Math.round(ratioArr[1] * h);
  let x2 = Math.round(ratioArr[2] * w);
  let y2 = Math.round(ratioArr[3] * h);

  // LLM이 좌표를 뒤집어 반환할 수 있으므로 정규화
  if (x1 > x2) [x1, x2] = [x2, x1];
  if (y1 > y2) [y1, y2] = [y2, y1];

  return [x1, y1, x2, y2];
}


/**
 * 비교 결과 다이얼로그를 표시한다.
 */
function _showComparisonResults(drafts) {
  // 간단한 alert로 표시 (추후 모달로 개선)
  let msg = "=== LLM 비교 결과 ===\n\n";
  for (const d of drafts) {
    const blocks = d.response_data?.blocks;
    const count = Array.isArray(blocks) ? blocks.length : "?";
    msg += `[${d.provider || "?"} / ${d.model || "?"}]\n`;
    msg += `  블록: ${count}개, 시간: ${(d.elapsed_sec || 0).toFixed(1)}s\n`;
    msg += `  비용: $${(d.cost_usd || 0).toFixed(4)}\n`;
    if (d.status === "rejected") {
      msg += `  오류: ${d.quality_notes || "호출 실패"}\n`;
    }
    msg += "\n";
  }

  // 첫 번째 성공 Draft를 자동 적용할지 물어봄
  const successful = drafts.filter(
    d => d.status !== "rejected" && d.response_data?.blocks
  );
  if (successful.length > 0) {
    msg += `가장 첫 번째 결과를 적용하시겠습니까?`;
    if (confirm(msg)) {
      _applyDraftToBlocks(successful[0]);
    }
  } else {
    alert(msg + "\n성공한 모델이 없습니다.");
  }
}


/**
 * LLM 상태 텍스트를 설정한다.
 */
function _setLlmStatus(text) {
  const el = document.getElementById("llm-analyze-status");
  if (el) el.textContent = text;
}


// 레이아웃 모드 활성화 시 LLM UI도 초기화
const _origActivateLayoutMode = typeof activateLayoutMode === "function"
  ? activateLayoutMode
  : null;

// DOMContentLoaded에서 LLM UI 초기화
document.addEventListener("DOMContentLoaded", () => {
  _initLlmLayoutUI();
});
