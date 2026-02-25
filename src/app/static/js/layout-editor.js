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
  let x = (e.clientX - rect.left) * scaleX;
  let y = (e.clientY - rect.top) * scaleY;

  // CSS 회전 보정: getBoundingClientRect()는 회전 후 AABB(축 정렬 바운딩 박스)를
  // 반환하므로, 90°/180°/270°에서 좌표를 역회전해야 캔버스 내부 좌표가 된다.
  if (typeof pdfState !== "undefined" && pdfState.rotation) {
    const deg = pdfState.rotation;
    const cw = overlay.width;
    const ch = overlay.height;
    if (deg === 90) {
      [x, y] = [y, cw - x];
    } else if (deg === 180) {
      [x, y] = [cw - x, ch - y];
    } else if (deg === 270) {
      [x, y] = [ch - y, x];
    }
  }

  return { x, y };
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

  // 리셋 버튼: 현재 페이지의 모든 레이아웃 블록 삭제
  const resetBtn = document.getElementById("layout-reset-btn");
  if (resetBtn) {
    resetBtn.addEventListener("click", _resetAllBlocks);
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
    item.draggable = true;
    item.dataset.blockId = block.block_id;
    item.innerHTML = `
      <span class="block-list-drag-handle" title="드래그하여 순서 변경">⠿</span>
      <span class="block-list-color" style="background:${color}"></span>
      <span class="block-list-order">${block.reading_order}</span>
      <span class="block-list-label">${label}</span>
      <span class="block-list-id">${block.block_id}</span>
    `;

    item.addEventListener("click", () => {
      _selectBlock(block.block_id);
    });
    item.addEventListener("dragstart", _onBlockDragStart);
    item.addEventListener("dragover", _onBlockDragOver);
    item.addEventListener("dragleave", _onBlockDragLeave);
    item.addEventListener("drop", _onBlockDrop);
    item.addEventListener("dragend", _onBlockDragEnd);

    listEl.appendChild(item);
  });
}


/* ──────────────────────────
   블록 목록 드래그 앤 드롭 순서 변경
   ────────────────────────── */

/** 드래그 중인 블록의 block_id를 임시 저장 */
let _draggedBlockId = null;

/**
 * 드래그 시작: dataTransfer에 block_id를 저장하고 시각적 피드백을 준다.
 */
function _onBlockDragStart(e) {
  const blockId = e.currentTarget.dataset.blockId;
  _draggedBlockId = blockId;
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", blockId);
  // 약간의 지연으로 dragging 클래스 추가 (드래그 고스트 이미지 생성 후)
  requestAnimationFrame(() => {
    e.currentTarget.classList.add("dragging");
  });
}

/**
 * 드래그가 블록 위를 지나갈 때: 드롭 위치를 위/아래 인디케이터로 표시한다.
 *
 * 왜 이렇게 하는가: 마우스 Y 좌표가 항목의 중앙보다 위인지 아래인지에 따라
 *   드롭될 위치를 사용자에게 직관적으로 보여준다.
 */
function _onBlockDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = "move";

  const item = e.currentTarget;
  // 자기 자신 위에서는 인디케이터 표시 안 함
  if (item.dataset.blockId === _draggedBlockId) return;

  const rect = item.getBoundingClientRect();
  const midY = rect.top + rect.height / 2;

  // 이전 인디케이터 제거 후 새로 설정
  item.classList.remove("drag-over-above", "drag-over-below");
  if (e.clientY < midY) {
    item.classList.add("drag-over-above");
  } else {
    item.classList.add("drag-over-below");
  }
}

/**
 * 드래그가 항목을 벗어날 때: 인디케이터를 제거한다.
 */
function _onBlockDragLeave(e) {
  e.currentTarget.classList.remove("drag-over-above", "drag-over-below");
}

/**
 * 드롭: 드래그한 블록을 드롭 위치에 맞게 reading_order를 재할당한다.
 *
 * 왜 이렇게 하는가: DOM 조작 대신 데이터(reading_order)를 직접 변경한 뒤
 *   _updateBlockList()로 목록을 다시 그린다. 이렇게 하면 데이터와 UI가
 *   항상 일치하고, 저장 시 올바른 순서가 서버에 전달된다.
 */
function _onBlockDrop(e) {
  e.preventDefault();
  const targetItem = e.currentTarget;
  targetItem.classList.remove("drag-over-above", "drag-over-below");

  const draggedId = _draggedBlockId;
  const targetId = targetItem.dataset.blockId;
  if (!draggedId || draggedId === targetId) return;

  // 현재 reading_order 순으로 블록 ID 배열을 만든다
  const ordered = [...layoutState.blocks]
    .sort((a, b) => a.reading_order - b.reading_order)
    .map((b) => b.block_id);

  // 드래그한 블록을 원래 위치에서 제거
  const fromIdx = ordered.indexOf(draggedId);
  if (fromIdx === -1) return;
  ordered.splice(fromIdx, 1);

  // 드롭 대상의 위치를 찾고, 마우스 위치에 따라 위/아래에 삽입
  const targetIdx = ordered.indexOf(targetId);
  const rect = targetItem.getBoundingClientRect();
  const midY = rect.top + rect.height / 2;
  const insertIdx = e.clientY < midY ? targetIdx : targetIdx + 1;
  ordered.splice(insertIdx, 0, draggedId);

  // reading_order를 0부터 순서대로 재할당
  ordered.forEach((blockId, idx) => {
    const block = layoutState.blocks.find((b) => b.block_id === blockId);
    if (block) block.reading_order = idx;
  });

  // UI 갱신 및 dirty 플래그 설정
  layoutState.isDirty = true;
  _updateLayoutSaveStatus("modified");
  _redrawOverlay();
  _updatePropsForm();
  _updateBlockList();
}

/**
 * 드래그 종료: 시각적 상태를 정리한다.
 */
function _onBlockDragEnd(e) {
  e.currentTarget.classList.remove("dragging");
  _draggedBlockId = null;
  // 혹시 남아있을 수 있는 인디케이터 모두 제거
  document.querySelectorAll(".block-list-item").forEach((el) => {
    el.classList.remove("drag-over-above", "drag-over-below");
  });
}


/* ──────────────────────────
   전체 리셋: 현재 페이지의 모든 레이아웃 블록 삭제
   ────────────────────────── */

/**
 * 현재 페이지의 모든 레이아웃 블록을 삭제하고 빈 레이아웃으로 저장한다.
 *
 * 왜 이렇게 하는가: 레이아웃을 처음부터 다시 그리고 싶을 때,
 *   개별 블록 삭제를 반복하는 대신 한 번에 모두 삭제할 수 있다.
 *   블록 배열을 비우고 PUT API로 빈 레이아웃을 서버에 저장한다.
 *   삭제 전 confirm()으로 사용자 확인을 받아 실수를 방지한다.
 */
async function _resetAllBlocks() {
  const { docId, partId, pageNum } = viewerState;
  if (!docId || !partId || !pageNum) {
    showToast("문헌과 페이지가 선택되어야 합니다.", 'warning');
    return;
  }

  if (layoutState.blocks.length === 0) {
    showToast("삭제할 레이아웃 블록이 없습니다.", 'warning');
    return;
  }

  if (!confirm(
    `현재 페이지의 레이아웃 블록 ${layoutState.blocks.length}개를 모두 삭제합니다.\n이 작업은 되돌릴 수 없습니다. 계속하시겠습니까?`
  )) return;

  // 블록 배열을 비우고 서버에 빈 레이아웃 저장
  layoutState.blocks = [];
  layoutState.selectedBlockId = null;
  layoutState.isDirty = true;

  try {
    await _saveLayout();
    _redrawOverlay();
    _updatePropsForm();
    _updateBlockList();
  } catch (e) {
    showToast(`레이아웃 리셋 실패: ${e.message}`, 'error');
  }
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

    // PDF 뷰포트(scale=1.0) 크기를 기준값으로 가져옴
    // 왜 필요한가:
    //   1. imageWidth가 없으면 LLM bbox_ratio 변환에 필요
    //   2. 기존 L3의 imageWidth가 뷰포트와 다르면 블록 좌표 보정 필요
    let vpWidth = 0, vpHeight = 0;
    if (typeof pdfState !== "undefined" && pdfState.pdfDoc) {
      try {
        const pdfPage = await pdfState.pdfDoc.getPage(pageNum);
        const vp = pdfPage.getViewport({ scale: 1.0 });
        vpWidth = Math.round(vp.width);
        vpHeight = Math.round(vp.height);
      } catch (_) { /* 무시 */ }
    }

    if (!layoutState.imageWidth && vpWidth > 0) {
      // 레이아웃이 아직 작성되지 않은 페이지 → PDF 뷰포트에서 설정
      layoutState.imageWidth = vpWidth;
      layoutState.imageHeight = vpHeight;
    } else if (layoutState.imageWidth && vpWidth > 0 && layoutState.imageWidth !== vpWidth) {
      // 기존 L3의 image_width가 PDF 뷰포트와 다른 경우
      // (예: 이전 버그로 3120이 저장되었지만, 실제 뷰포트는 1560)
      // → 블록 bbox를 뷰포트 좌표계로 리스케일
      const scaleX = vpWidth / layoutState.imageWidth;
      const scaleY = vpHeight / layoutState.imageHeight;
      console.info(
        `L3 imageWidth(${layoutState.imageWidth})가 PDF 뷰포트(${vpWidth})와 다릅니다.`,
        `블록 좌표를 리스케일합니다 (×${scaleX.toFixed(2)}, ×${scaleY.toFixed(2)})`
      );
      for (const block of layoutState.blocks) {
        if (block.bbox && block.bbox.length === 4) {
          block.bbox = [
            Math.round(block.bbox[0] * scaleX),
            Math.round(block.bbox[1] * scaleY),
            Math.round(block.bbox[2] * scaleX),
            Math.round(block.bbox[3] * scaleY),
          ];
        }
      }
      layoutState.imageWidth = vpWidth;
      layoutState.imageHeight = vpHeight;
      layoutState.isDirty = true;  // 리스케일했으므로 저장 필요
    }

    _updateLayoutSaveStatus(
      layoutState.isDirty ? "modified" : (data._meta?.exists ? "saved" : "empty")
    );
    _redrawOverlay();
    _updatePropsForm();
    _updateBlockList();
  } catch (err) {
    console.error("레이아웃 로드 실패:", err);
    layoutState.blocks = [];

    // 에러 시에도 imageWidth는 PDF 뷰포트에서 설정
    if (typeof pdfState !== "undefined" && pdfState.pdfDoc) {
      try {
        const pdfPage = await pdfState.pdfDoc.getPage(pageNum);
        const vp = pdfPage.getViewport({ scale: 1.0 });
        layoutState.imageWidth = Math.round(vp.width);
        layoutState.imageHeight = Math.round(vp.height);
      } catch (_) { /* 무시 */ }
    }

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

  // 자동감지 엔진 드롭다운 채우기 (서버 사용 가능 엔진 확인)
  _populateAutodetectEngines();

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
   자동감지: koten-layout-detector (ONNX)
   ────────────────────────── */

/**
 * ONNX 세션 캐시 — 모델을 한 번만 로드하고 재사용한다.
 *
 * 왜 이렇게 하는가:
 *   ONNX 모델(~36MB)은 처음 한 번만 로드하면 된다.
 *   이후 페이지 변경 시에는 캐시된 세션으로 즉시 추론한다.
 */
let _kotenSession = null;
let _kotenModelLoading = false;

/**
 * koten-layout-detector 클래스 → 우리 block_type 매핑.
 *
 * classId 0 (全体/overall): 판면 전체 영역이므로 건너뜀 (OCR 단위 아님)
 * classId 1 (手書き/handwritten): 필사본 본문 → main_text
 * classId 2 (活字/typography): 활자본 본문 → main_text
 * classId 3 (図版/illustration): 삽화 → illustration
 * classId 4 (印判/stamp): 인장 → seal
 */
const KOTEN_TO_BLOCK_TYPE = {
  0: null,           // overall — 건너뜀
  1: "main_text",    // handwritten
  2: "main_text",    // typography
  3: "illustration", // illustration
  4: "seal",         // stamp
};


/**
 * ONNX 모델을 로드한다.
 * 로컬 서버 경로 우선, 실패 시 GitHub Releases URL 폴백.
 *
 * @returns {Promise<ort.InferenceSession>}
 */
async function _loadKotenModel() {
  if (_kotenSession) return _kotenSession;
  if (_kotenModelLoading) {
    // 이미 로딩 중이면 완료될 때까지 대기
    while (_kotenModelLoading) {
      await new Promise(r => setTimeout(r, 100));
    }
    return _kotenSession;
  }

  _kotenModelLoading = true;
  _setAutodetectStatus("모델 로딩 중...");

  const LOCAL_URL = "/static/models/koten-layout-best.onnx";
  const GITHUB_URL = "https://github.com/yuta1984/koten-layout-detector/releases/download/v1.1.0/best.onnx";

  try {
    // 로컬 우선 시도
    try {
      const checkRes = await fetch(LOCAL_URL, { method: "HEAD" });
      if (checkRes.ok) {
        _kotenSession = await KotenLayout.loadModel(LOCAL_URL);
        _setAutodetectStatus("모델 로드 완료 (로컬)");
        return _kotenSession;
      }
    } catch (_) { /* 로컬 없으면 GitHub 폴백 */ }

    // GitHub Releases 폴백
    _setAutodetectStatus("모델 다운로드 중 (GitHub)...");
    _kotenSession = await KotenLayout.loadModel(GITHUB_URL);
    _setAutodetectStatus("모델 로드 완료 (GitHub)");
    return _kotenSession;
  } catch (err) {
    _setAutodetectStatus(`모델 로드 실패: ${err.message}`);
    throw err;
  } finally {
    _kotenModelLoading = false;
  }
}


/**
 * 지정된 PDF 페이지에서 이미지를 추출한다.
 *
 * 왜 이렇게 하는가:
 *   koten-layout-detector는 HTMLImageElement 또는 Canvas를 입력으로 받는다.
 *   PDF.js가 렌더링한 캔버스에서 직접 이미지를 만들어 전달한다.
 *   scale=1.0으로 렌더링하여, 좌표가 레이아웃 저장 좌표와 일치하도록 한다.
 *
 * @param {number} [pageNum] - 페이지 번호 (생략 시 현재 페이지)
 * @returns {Promise<HTMLImageElement>}
 */
async function _getPageImage(pageNum) {
  if (!pdfState.pdfDoc) throw new Error("PDF가 로드되지 않았습니다.");
  const pn = pageNum || viewerState.pageNum;

  const page = await pdfState.pdfDoc.getPage(pn);
  const vp = page.getViewport({ scale: 1.0 });

  // 오프스크린 캔버스에 scale=1.0으로 렌더링
  const offCanvas = document.createElement("canvas");
  offCanvas.width = Math.round(vp.width);
  offCanvas.height = Math.round(vp.height);
  const ctx = offCanvas.getContext("2d");

  await page.render({ canvasContext: ctx, viewport: vp }).promise;

  // Canvas → Image
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = offCanvas.toDataURL("image/png");
  });
}


/**
 * 자동감지 실행: 현재 PDF 페이지에서 레이아웃 영역을 감지한다.
 *
 * 엔진 선택에 따라 분기:
 *   - koten: 브라우저 ONNX (KotenLayout)
 *   - ndlocr: 서버 API (NDLOCR DEIM, 17클래스)
 */
async function _runAutoDetect() {
  const engineSelect = document.getElementById("autodetect-engine");
  const engine = engineSelect ? engineSelect.value : "koten";

  if (engine === "ndlocr") {
    return _runAutoDetectNdlocr();
  }

  // ── 이하 기존 KotenLayout 코드 (수정 없음) ──
  return _runAutoDetectKoten();
}

/**
 * KotenLayout 브라우저 자동감지 (기존 코드).
 *
 * 흐름:
 *   1. ONNX 모델 로드 (캐시)
 *   2. PDF 페이지 이미지 추출
 *   3. 전처리 → 추론 → 후처리
 *   4. Detection[] → LayoutBlock[] 변환
 *   5. 기존 블록에 추가 + 자동 저장
 */
async function _runAutoDetectKoten() {
  if (!viewerState.docId || viewerState.pageNum == null) {
    showToast("문헌과 페이지를 먼저 선택하세요.", 'warning');
    return;
  }

  const btn = document.getElementById("autodetect-btn");
  if (btn) btn.disabled = true;
  _setAutodetectStatus("감지 중...");
  const startTime = performance.now();

  try {
    // 1. 모델 로드
    const session = await _loadKotenModel();

    // 2. 페이지 이미지 추출
    const img = await _getPageImage();

    // imageWidth/Height 설정 (저장 시 필요)
    layoutState.imageWidth = img.naturalWidth || img.width;
    layoutState.imageHeight = img.naturalHeight || img.height;

    // 3. 전처리 → 추론 → 후처리
    const { tensor, meta } = KotenLayout.preprocess(img);
    const outputTensor = await KotenLayout.runInference(session, tensor);

    const confSlider = document.getElementById("autodetect-conf");
    const confThreshold = confSlider ? parseFloat(confSlider.value) : 0.5;
    const detections = KotenLayout.postprocess(outputTensor, meta, confThreshold, 0.45);

    // 4. Detection → LayoutBlock 변환 (행 자동 그룹핑 포함)
    const { blocks: newBlocks, lineCount } = _detectionsToBlocks(detections);

    if (newBlocks.length === 0) {
      _setAutodetectStatus("감지된 영역 없음 (임계값을 낮춰보세요)");
      return;
    }

    // 5. 기존 블록을 지우고 새 블록으로 교체
    layoutState.blocks = newBlocks;
    layoutState.isDirty = true;

    _redrawOverlay();
    _updateBlockList();

    // 자동 저장
    await _saveLayout();

    const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);
    const groupInfo = lineCount !== newBlocks.length
      ? `${lineCount}행 → ${newBlocks.length}블록`
      : `${newBlocks.length}블록`;
    _setAutodetectStatus(`${groupInfo} 감지·저장됨 (${elapsed}s)`);
  } catch (err) {
    console.error("자동감지 오류:", err);
    _setAutodetectStatus(`오류: ${err.message}`);
    showToast(`자동감지 실패: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}


/**
 * 전체 페이지 배치 자동감지.
 *
 * 전체 페이지 배치 자동감지.
 * 엔진 선택에 따라 분기한다.
 */
async function _runAutoDetectAll() {
  const engineSelect = document.getElementById("autodetect-engine");
  const engine = engineSelect ? engineSelect.value : "koten";

  if (engine === "ndlocr") {
    return _runAutoDetectAllNdlocr();
  }

  return _runAutoDetectAllKoten();
}

/**
 * KotenLayout 전체 페이지 배치 자동감지 (기존 코드).
 *
 * 왜 이렇게 하는가:
 *   고전적 PDF는 수십~수백 페이지이다.
 *   1페이지씩 수동 클릭하는 것은 비효율적이므로,
 *   전체 페이지를 순회하면서 자동감지 + 저장을 한번에 수행한다.
 *   ONNX 모델이 브라우저에서 돌아가므로 API 호출 없이 빠르게 처리된다.
 *
 * 흐름:
 *   1. ONNX 모델 로드 (캐시)
 *   2. 전체 페이지 순회
 *      a. 페이지 이미지 추출 (scale=1.0)
 *      b. 전처리 → 추론 → 후처리
 *      c. Detection → LayoutBlock 변환
 *      d. PUT /api/.../layout 으로 저장
 *   3. 현재 페이지의 결과를 화면에 반영
 */
async function _runAutoDetectAllKoten() {
  if (!viewerState.docId || !viewerState.partId) {
    showToast("문헌을 먼저 선택하세요.", 'warning');
    return;
  }

  if (!pdfState.pdfDoc) {
    showToast("PDF가 로드되지 않았습니다.", 'warning');
    return;
  }

  const totalPages = pdfState.pdfDoc.numPages;
  if (!confirm(`전체 ${totalPages}페이지에 대해 레이아웃 자동감지를 실행합니다.\n계속하시겠습니까?`)) {
    return;
  }

  const btn = document.getElementById("autodetect-btn");
  const batchBtn = document.getElementById("autodetect-all-btn");
  if (btn) btn.disabled = true;
  if (batchBtn) batchBtn.disabled = true;

  const confSlider = document.getElementById("autodetect-conf");
  const confThreshold = confSlider ? parseFloat(confSlider.value) : 0.5;

  const startTime = performance.now();
  let successCount = 0;
  let totalBlocks = 0;
  // 실패 추적: 어떤 페이지가 왜 실패했는지 기록
  const failures = [];

  try {
    // 1. 모델 로드
    const session = await _loadKotenModel();

    // 2. 전체 페이지 순회
    for (let pageNum = 1; pageNum <= totalPages; pageNum++) {
      _setAutodetectStatus(
        `감지 중... ${pageNum}/${totalPages} (성공 ${successCount}, 실패 ${failures.length})`
      );

      try {
        // a. 페이지 이미지 추출
        const img = await _getPageImage(pageNum);
        const imgW = img.naturalWidth || img.width;
        const imgH = img.naturalHeight || img.height;

        // b. 전처리 → 추론 → 후처리
        const { tensor, meta } = KotenLayout.preprocess(img);
        const outputTensor = await KotenLayout.runInference(session, tensor);
        const detections = KotenLayout.postprocess(outputTensor, meta, confThreshold, 0.45);

        // c. Detection → LayoutBlock 변환 (행 자동 그룹핑 포함)
        const { blocks } = _detectionsToBlocks(detections, pageNum, { width: imgW, height: imgH });

        // d. API로 저장
        const payload = {
          part_id: viewerState.partId,
          page_number: pageNum,
          image_width: imgW,
          image_height: imgH,
          analysis_method: "auto_detect",
          blocks: blocks,
        };

        const url = `/api/documents/${viewerState.docId}/pages/${pageNum}/layout?part_id=${viewerState.partId}`;
        const res = await fetch(url, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        if (res.ok) {
          successCount++;
          totalBlocks += blocks.length;
        } else {
          const errText = await res.text();
          console.error(`[전체감지] 페이지 ${pageNum} 저장 실패 (HTTP ${res.status}):`, errText);
          failures.push({ page: pageNum, reason: `HTTP ${res.status}: ${errText}` });
        }
      } catch (pageErr) {
        console.error(`[전체감지] 페이지 ${pageNum} 감지 오류:`, pageErr);
        failures.push({ page: pageNum, reason: pageErr.message });
      }
    }

    // 3. 현재 페이지의 결과를 화면에 반영
    if (viewerState.pageNum) {
      await loadPageLayout(viewerState.docId, viewerState.partId, viewerState.pageNum);
    }

    // 4. 결과 보고 — 성공/실패를 명확히 구분하여 표시
    const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);
    if (failures.length === 0) {
      _setAutodetectStatus(
        `완료: ${successCount}/${totalPages}페이지, ${totalBlocks}블록 (${elapsed}s)`
      );
    } else {
      _setAutodetectStatus(
        `완료: 성공 ${successCount}/${totalPages}, 실패 ${failures.length}건 (${elapsed}s)`
      );
      // 실패 원인을 사용자에게 표시 (첫 번째 실패의 원인만 토스트로)
      const firstFail = failures[0];
      const failPages = failures.map(f => f.page).join(", ");
      showToast(
        `저장 실패 ${failures.length}건 (페이지: ${failPages})\n원인: ${firstFail.reason}`,
        'error'
      );
    }
  } catch (err) {
    console.error("배치 자동감지 오류:", err);
    _setAutodetectStatus(`오류: ${err.message}`);
    showToast(`배치 자동감지 실패: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
    if (batchBtn) batchBtn.disabled = false;
  }
}


/**
 * 배열의 중앙값을 구한다. (그룹핑 통계용)
 * @param {number[]} arr
 * @returns {number}
 */
function _median(arr) {
  if (arr.length === 0) return 0;
  const sorted = arr.slice().sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid];
}


/**
 * 행(열) 단위 감지 결과를 들여쓰기·공간 인접성 기준으로 그룹핑한다.
 *
 * 왜 이렇게 하는가:
 *   koten-layout-detector는 세로 열 하나하나를 개별 감지한다.
 *   그대로 쓰면 한 페이지에 블록 10~20개가 생겨 OCR·교정·편성이 번거롭다.
 *   인접한 열들을 하나의 큰 영역 블록으로 합치되,
 *   들여쓰기(y1 위치 차이)나 큰 간격은 별도 블록으로 분리한다.
 *
 * 알고리즘:
 *   1. 텍스트(main_text)만 추출, 비텍스트(illustration, seal)는 개별 유지
 *   2. 텍스트를 x-center 내림차순 정렬 (RTL 읽기순)
 *   3. 인접 열 간 x-center 간격 중앙값, 열 높이 중앙값 계산
 *   4. 순차 비교: 인접(x-gap < medianGap×2) AND 같은 레벨(|Δy1| < medianHeight×0.15) → 같은 그룹
 *   5. 그룹 bbox 병합 (union)
 *
 * @param {Array<{ x1, y1, x2, y2, blockType, cx, cy }>} filtered - overall 제외, 매핑 완료된 감지 결과
 * @returns {Array<{ bbox: [number,number,number,number], blockType: string, cx: number, cy: number, memberCount: number }>}
 */
function _groupLineDetections(filtered) {
  // 1. 텍스트 / 비텍스트 분리
  const textDets = filtered.filter(d => d.blockType === "main_text");
  const otherDets = filtered.filter(d => d.blockType !== "main_text");

  // 비텍스트는 개별 블록으로 유지
  const otherGroups = otherDets.map(d => ({
    bbox: [d.x1, d.y1, d.x2, d.y2],
    blockType: d.blockType,
    cx: d.cx,
    cy: d.cy,
    memberCount: 1,
  }));

  // 텍스트 0~1개면 그룹핑 불필요
  if (textDets.length <= 1) {
    const singleGroups = textDets.map(d => ({
      bbox: [d.x1, d.y1, d.x2, d.y2],
      blockType: d.blockType,
      cx: d.cx,
      cy: d.cy,
      memberCount: 1,
    }));
    return singleGroups.concat(otherGroups);
  }

  // 2. x-center 내림차순 정렬 (오른쪽→왼쪽, RTL 읽기순)
  textDets.sort((a, b) => b.cx - a.cx);

  // 3. 통계 계산
  const heights = textDets.map(d => d.y2 - d.y1);
  const medianHeight = _median(heights);

  // 인접 열 간 x-center 간격 (정렬된 순서대로)
  const xGaps = [];
  for (let i = 1; i < textDets.length; i++) {
    xGaps.push(Math.abs(textDets[i - 1].cx - textDets[i].cx));
  }
  const medianGap = _median(xGaps);

  // 들여쓰기 임계값: 열 높이의 15% (약간의 y1 차이는 허용)
  const indentThreshold = medianHeight * 0.15;
  // 인접성 임계값: 중앙 간격의 2배 (열 사이에 빈 공간이 있으면 다른 영역)
  const adjacencyThreshold = medianGap * 2.0;

  // 4. 순차 그룹핑
  const groups = [];
  let currentGroup = { members: [textDets[0]] };

  for (let i = 1; i < textDets.length; i++) {
    const prev = textDets[i - 1];
    const curr = textDets[i];

    const xCenterGap = Math.abs(prev.cx - curr.cx);
    const y1Diff = Math.abs(prev.y1 - curr.y1);

    const isAdjacent = xCenterGap < adjacencyThreshold;
    const isSameLevel = y1Diff < indentThreshold;

    if (isAdjacent && isSameLevel) {
      // 같은 그룹에 추가
      currentGroup.members.push(curr);
    } else {
      // 현재 그룹 마감, 새 그룹 시작
      groups.push(currentGroup);
      currentGroup = { members: [curr] };
    }
  }
  groups.push(currentGroup); // 마지막 그룹

  // 5. 각 그룹의 bbox 병합 (union)
  const textGroups = groups.map(g => {
    let minX1 = Infinity, minY1 = Infinity, maxX2 = -Infinity, maxY2 = -Infinity;
    let sumCx = 0, sumCy = 0;
    for (const m of g.members) {
      if (m.x1 < minX1) minX1 = m.x1;
      if (m.y1 < minY1) minY1 = m.y1;
      if (m.x2 > maxX2) maxX2 = m.x2;
      if (m.y2 > maxY2) maxY2 = m.y2;
      sumCx += m.cx;
      sumCy += m.cy;
    }
    return {
      bbox: [minX1, minY1, maxX2, maxY2],
      blockType: "main_text",
      cx: sumCx / g.members.length,    // 그룹 중심 (reading_order 정렬용)
      cy: sumCy / g.members.length,
      memberCount: g.members.length,
    };
  });

  return textGroups.concat(otherGroups);
}


/**
 * Detection 배열을 LayoutBlock 배열로 변환한다.
 *
 * 흐름:
 *   1. overall(classId=0) 제외, block_type 매핑
 *   2. 인접 행(열)을 자동 그룹핑 (들여쓰기·간격 기준)
 *   3. 그룹별 LayoutBlock 생성 + reading_order 배정
 *
 * @param {Array<{ x1, y1, x2, y2, conf, classId, label, color }>} detections
 * @param {number} [pageNum] - 페이지 번호 (생략 시 현재 페이지)
 * @param {{ width: number, height: number }} [imgSize] - 이미지 크기 (생략 시 layoutState)
 * @returns {{ blocks: Array, lineCount: number }} LayoutBlock 배열 + 원래 행 수
 */
function _detectionsToBlocks(detections, pageNum, imgSize) {
  const pn = pageNum || viewerState.pageNum || 1;
  const pNum = String(pn).padStart(2, "0");
  const imgW = imgSize ? imgSize.width : (layoutState.imageWidth || 9999);
  const imgH = imgSize ? imgSize.height : (layoutState.imageHeight || 9999);

  // 1. overall(classId=0) 제외, block_type 매핑
  const filtered = detections
    .filter(d => KOTEN_TO_BLOCK_TYPE[d.classId] !== null && KOTEN_TO_BLOCK_TYPE[d.classId] !== undefined)
    .map(d => ({
      ...d,
      blockType: KOTEN_TO_BLOCK_TYPE[d.classId],
      cx: (d.x1 + d.x2) / 2,
      cy: (d.y1 + d.y2) / 2,
    }));

  const lineCount = filtered.length;

  // 2. 인접 행을 자동 그룹핑
  const groups = _groupLineDetections(filtered);

  // 3. reading_order 정렬: 그룹 cx 내림차순(오른쪽→왼쪽), 동일 위치면 cy 오름차순(위→아래)
  groups.sort((a, b) => {
    const xDiff = Math.abs(a.cx - b.cx);
    // 가까운 x 위치면 y로 비교
    if (xDiff < 50) return a.cy - b.cy;
    return b.cx - a.cx;
  });

  const blocks = groups.map((g, idx) => {
    const bIdx = String(idx + 1).padStart(2, "0");
    return {
      block_id: `p${pNum}_b${bIdx}`,
      block_type: g.blockType,
      bbox: [
        Math.round(Math.max(0, g.bbox[0])),
        Math.round(Math.max(0, g.bbox[1])),
        Math.round(Math.min(imgW, g.bbox[2])),
        Math.round(Math.min(imgH, g.bbox[3])),
      ],
      reading_order: idx,
      writing_direction: "vertical_rtl",
      line_style: null,
      font_size_class: null,
      ocr_config: null,
      refers_to_block: null,
      skip: g.blockType === "seal", // 인장은 OCR 건너뜀
    };
  });

  return { blocks, lineCount };
}


/**
 * 자동감지 상태 텍스트를 설정한다.
 */
function _setAutodetectStatus(text) {
  const el = document.getElementById("autodetect-status");
  if (el) el.textContent = text;
}


/**
 * 자동감지 UI를 초기화한다.
 *
 * 왜 layout-editor.js에 넣는가:
 *   자동감지는 레이아웃 편집기의 확장 기능이다.
 *   감지 결과를 기존 블록 편집 UI에 통합한다.
 */
function _initAutodetectUI() {
  // 현재 페이지 자동감지 버튼
  const btn = document.getElementById("autodetect-btn");
  if (btn) {
    btn.addEventListener("click", _runAutoDetect);
  }

  // 전체 페이지 배치 자동감지 버튼
  const batchBtn = document.getElementById("autodetect-all-btn");
  if (batchBtn) {
    batchBtn.addEventListener("click", _runAutoDetectAll);
  }

  // confidence 슬라이더 값 표시
  const slider = document.getElementById("autodetect-conf");
  const valueLabel = document.getElementById("autodetect-conf-value");
  if (slider && valueLabel) {
    slider.addEventListener("input", () => {
      valueLabel.textContent = parseFloat(slider.value).toFixed(2);
    });
  }
}


// DOMContentLoaded에서 자동감지 UI 초기화
document.addEventListener("DOMContentLoaded", () => {
  _initAutodetectUI();
});


/* ──────────────────────────
   자동감지: NDLOCR DEIM (서버사이드)
   ────────────────────────── */

/**
 * 자동감지 엔진 드롭다운의 NDLOCR 옵션 상태를 갱신한다.
 *
 * HTML에 정적으로 포함된 ndlocr 옵션(disabled 상태)을
 * /api/ocr/engines 응답에 따라 활성화 또는 사용 불가 표시로 전환.
 *
 * 왜 정적 포함인가:
 *   동적 추가 방식은 네트워크 지연·에러 시 옵션 자체가 안 보여서
 *   사용자가 NDLOCR 레이아웃 감지 기능의 존재를 알 수 없었다.
 *   정적으로 두고 상태만 갱신하면 항상 보인다.
 */
async function _populateAutodetectEngines() {
  const select = document.getElementById("autodetect-engine");
  if (!select) return;

  const ndlocrOpt = select.querySelector('option[value="ndlocr"]');
  if (!ndlocrOpt) return;

  try {
    const res = await fetch("/api/ocr/engines");
    if (!res.ok) {
      ndlocrOpt.textContent = "NDLOCR-DEIM (서버 연결 실패)";
      ndlocrOpt.disabled = true;
      console.warn("[layout] /api/ocr/engines 응답 오류:", res.status);
      return;
    }
    const data = await res.json();
    const ndlocr = (data.engines || []).find(
      e => e.engine_id === "ndlocr"
    );
    if (ndlocr && ndlocr.available) {
      // 사용 가능 → 활성화
      ndlocrOpt.textContent = "NDLOCR-DEIM (서버·17클래스)";
      ndlocrOpt.disabled = false;
    } else {
      // 엔진 미설치 또는 사용 불가
      ndlocrOpt.textContent = "NDLOCR-DEIM (미설치)";
      ndlocrOpt.disabled = true;
    }
  } catch (err) {
    ndlocrOpt.textContent = "NDLOCR-DEIM (서버 연결 실패)";
    ndlocrOpt.disabled = true;
    console.warn("[layout] 엔진 목록 조회 실패:", err.message);
  }
}


/**
 * NDLOCR DEIM 자동감지: 현재 페이지.
 *
 * 서버 API를 호출하여 DEIM으로 레이아웃을 감지한다.
 * KotenLayout(5클래스)과 달리 17개 클래스를 탐지하여
 * 본문/주석/두주/판심제/장차/도판 등을 세밀하게 구분한다.
 */
async function _runAutoDetectNdlocr() {
  if (!viewerState.docId || !viewerState.partId || viewerState.pageNum == null) {
    showToast("문헌과 페이지를 먼저 선택하세요.", "warning");
    return;
  }

  const btn = document.getElementById("autodetect-btn");
  if (btn) btn.disabled = true;
  _setAutodetectStatus("NDLOCR 감지 중...");
  const startTime = performance.now();

  try {
    // 1. 신뢰도 임계값
    const confSlider = document.getElementById("autodetect-conf");
    const conf = confSlider ? parseFloat(confSlider.value) : 0.3;

    // 2. 서버 API 호출
    const url =
      `/api/ocr/detect-layout/${viewerState.docId}/${viewerState.pageNum}` +
      `?part_id=${encodeURIComponent(viewerState.partId)}&conf_threshold=${conf}`;
    const res = await fetch(url, { method: "POST" });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${res.status}`);
    }

    const data = await res.json();

    // 3. 응답의 blocks를 layoutState에 반영
    layoutState.imageWidth = data.image_width;
    layoutState.imageHeight = data.image_height;
    layoutState.blocks = data.blocks || [];
    layoutState.isDirty = true;

    if (layoutState.blocks.length === 0) {
      _setAutodetectStatus("감지된 영역 없음 (임계값을 낮춰보세요)");
      return;
    }

    // 4. 렌더링 + 저장
    _redrawOverlay();
    _updateBlockList();
    await _saveLayout();

    const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);
    _setAutodetectStatus(
      `${data.block_count}블록 감지·저장됨 — NDLOCR (${elapsed}s)`
    );
  } catch (err) {
    console.error("NDLOCR 자동감지 오류:", err);
    _setAutodetectStatus(`오류: ${err.message}`);
    showToast(`NDLOCR 자동감지 실패: ${err.message}`, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}


/**
 * NDLOCR DEIM 전체 페이지 배치 자동감지.
 *
 * 전체 페이지를 순회하면서 서버 API를 호출한다.
 * 각 페이지 결과를 PUT /api/.../layout으로 직접 저장한다.
 */
async function _runAutoDetectAllNdlocr() {
  if (!viewerState.docId || !viewerState.partId) {
    showToast("문헌을 먼저 선택하세요.", "warning");
    return;
  }

  if (!pdfState.pdfDoc) {
    showToast("PDF가 로드되지 않았습니다.", "warning");
    return;
  }

  const totalPages = pdfState.pdfDoc.numPages;
  if (!confirm(
    `NDLOCR-DEIM으로 전체 ${totalPages}페이지 레이아웃을 서버에서 감지합니다.\n계속하시겠습니까?`
  )) {
    return;
  }

  const btn = document.getElementById("autodetect-btn");
  const batchBtn = document.getElementById("autodetect-all-btn");
  if (btn) btn.disabled = true;
  if (batchBtn) batchBtn.disabled = true;

  const confSlider = document.getElementById("autodetect-conf");
  const conf = confSlider ? parseFloat(confSlider.value) : 0.3;

  const startTime = performance.now();
  let successCount = 0;
  let totalBlocks = 0;
  const failures = [];

  try {
    for (let pageNum = 1; pageNum <= totalPages; pageNum++) {
      _setAutodetectStatus(
        `NDLOCR 감지 중... ${pageNum}/${totalPages} (성공 ${successCount}, 실패 ${failures.length})`
      );

      try {
        // 서버 API로 레이아웃 감지
        const detectUrl =
          `/api/ocr/detect-layout/${viewerState.docId}/${pageNum}` +
          `?part_id=${encodeURIComponent(viewerState.partId)}&conf_threshold=${conf}`;
        const detectRes = await fetch(detectUrl, { method: "POST" });

        if (!detectRes.ok) {
          const errData = await detectRes.json().catch(() => ({}));
          throw new Error(errData.error || `HTTP ${detectRes.status}`);
        }

        const data = await detectRes.json();
        const blocks = data.blocks || [];

        // PUT /api/.../layout으로 저장
        const saveUrl =
          `/api/documents/${viewerState.docId}/pages/${pageNum}/layout` +
          `?part_id=${encodeURIComponent(viewerState.partId)}`;
        const saveRes = await fetch(saveUrl, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            part_id: viewerState.partId,
            page_number: pageNum,
            image_width: data.image_width,
            image_height: data.image_height,
            analysis_method: "auto_detect",
            blocks: blocks,
          }),
        });

        if (saveRes.ok) {
          successCount++;
          totalBlocks += blocks.length;
        } else {
          const errText = await saveRes.text();
          failures.push({ page: pageNum, reason: `저장 실패 HTTP ${saveRes.status}: ${errText}` });
        }
      } catch (pageErr) {
        failures.push({ page: pageNum, reason: pageErr.message });
      }
    }

    // 현재 페이지의 결과를 화면에 반영
    if (viewerState.pageNum) {
      await loadPageLayout(viewerState.docId, viewerState.partId, viewerState.pageNum);
    }

    // 결과 보고
    const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);
    if (failures.length === 0) {
      _setAutodetectStatus(
        `완료: ${successCount}/${totalPages}페이지, ${totalBlocks}블록 — NDLOCR (${elapsed}s)`
      );
    } else {
      _setAutodetectStatus(
        `완료: 성공 ${successCount}/${totalPages}, 실패 ${failures.length}건 — NDLOCR (${elapsed}s)`
      );
      const failPages = failures.map(f => f.page).join(", ");
      showToast(
        `감지 실패 ${failures.length}건 (페이지: ${failPages})\n원인: ${failures[0].reason}`,
        "error"
      );
    }
  } catch (err) {
    console.error("NDLOCR 배치 자동감지 오류:", err);
    _setAutodetectStatus(`오류: ${err.message}`);
    showToast(`NDLOCR 배치 자동감지 실패: ${err.message}`, "error");
  } finally {
    if (btn) btn.disabled = false;
    if (batchBtn) batchBtn.disabled = false;
  }
}
