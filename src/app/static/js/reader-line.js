/**
 * 읽기 보조선 — PDF 뷰어 위에 가로/세로 안내선을 표시한다.
 *
 * 목적: 고서의 세로 열이나 가로 줄을 읽을 때,
 *       현재 읽는 위치를 시각적으로 표시하여 눈의 이동을 돕는다.
 *
 * 구현: .pdf-canvas-container 안에 pointer-events:none div를 삽입,
 *       마우스 위치를 따라 이동한다.
 *
 * 토글 3단: 끔 → 가로선(Y 추적) → 세로선(X 추적) → 끔
 * 단축키: R 키 (input/textarea 포커스 시 무시)
 *
 * z-index: 5 — pdf-canvas(z: auto) 위, layout-overlay(z: 10) 아래.
 *              pointer-events: none이므로 오버레이 조작을 방해하지 않는다.
 */

const readerLineState = {
  enabled: false,
  mode: "horizontal",  // "horizontal" = 가로선(Y추적), "vertical" = 세로선(X추적)
};


/**
 * 읽기 보조선을 초기화한다.
 * DOMContentLoaded 후 workspace.js에서 호출한다.
 */
function initReaderLine() {
  const container = document.getElementById("pdf-canvas-container");
  if (!container) return;

  // 보조선 div 생성
  const line = document.createElement("div");
  line.id = "reader-line";
  line.className = "reader-line";
  line.style.display = "none";
  container.appendChild(line);

  // 마우스 추적
  container.addEventListener("mousemove", _onReaderMouseMove);
  container.addEventListener("mouseleave", () => {
    if (line) line.style.display = "none";
  });
  container.addEventListener("mouseenter", () => {
    if (readerLineState.enabled && line) line.style.display = "block";
  });

  // 툴바 토글 버튼
  const toggleBtn = document.getElementById("pdf-reader-line-btn");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", _toggleReaderLine);
  }

  // 키보드 단축키: R키로 토글
  document.addEventListener("keydown", (e) => {
    if (e.key === "r" && !e.ctrlKey && !e.altKey && !e.metaKey) {
      // 포커스가 입력 필드이면 무시
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      // contentEditable 요소도 무시
      if (document.activeElement?.isContentEditable) return;
      _toggleReaderLine();
    }
  });
}


/**
 * 보조선 모드를 순환 전환한다.
 * 끔 → 가로선 → 세로선 → 끔
 */
function _toggleReaderLine() {
  if (!readerLineState.enabled) {
    readerLineState.enabled = true;
    readerLineState.mode = "horizontal";
  } else if (readerLineState.mode === "horizontal") {
    readerLineState.mode = "vertical";
  } else {
    readerLineState.enabled = false;
  }

  const line = document.getElementById("reader-line");
  const btn = document.getElementById("pdf-reader-line-btn");

  if (!readerLineState.enabled) {
    if (line) line.style.display = "none";
    if (btn) btn.classList.remove("active");
    if (btn) btn.title = "읽기 보조선 (R)";
  } else {
    if (line) {
      line.className = `reader-line reader-line-${readerLineState.mode}`;
    }
    if (btn) btn.classList.add("active");
    if (btn) {
      btn.title = readerLineState.mode === "horizontal"
        ? "읽기 보조선: 가로 → 세로 (R)"
        : "읽기 보조선: 세로 → 끄기 (R)";
    }
  }
}


/**
 * 마우스 이동 시 보조선 위치를 업데이트한다.
 *
 * 왜 container 기준인가: pdf-canvas-container는 스크롤 가능한 영역이므로,
 *   scrollTop/scrollLeft를 더해야 실제 위치에 정확히 맞는다.
 */
function _onReaderMouseMove(e) {
  if (!readerLineState.enabled) return;
  const line = document.getElementById("reader-line");
  if (!line) return;

  const container = document.getElementById("pdf-canvas-container");
  const rect = container.getBoundingClientRect();

  line.style.display = "block";

  if (readerLineState.mode === "horizontal") {
    const y = e.clientY - rect.top + container.scrollTop;
    line.style.top = y + "px";
    line.style.left = "0";
    line.style.width = "100%";
    line.style.height = "2px";
    line.className = "reader-line reader-line-horizontal";
  } else {
    const x = e.clientX - rect.left + container.scrollLeft;
    line.style.left = x + "px";
    line.style.top = "0";
    line.style.height = "100%";
    line.style.width = "2px";
    line.className = "reader-line reader-line-vertical";
  }
}
