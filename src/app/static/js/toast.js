/**
 * 토스트 알림 시스템 — alert() 대체
 *
 * 사용법:
 *   showToast('저장되었습니다', 'success');
 *   showToast('오류가 발생했습니다', 'error');
 *   showToast('주의: 데이터가 없습니다', 'warning');
 *   showToast('처리 중입니다...', 'info');
 *
 * 목적:
 *   alert()는 브라우저 이벤트 루프를 차단하여 연구 흐름을 끊는다.
 *   토스트는 화면 우상단에 잠시 표시되고 자동으로 사라져서
 *   작업을 멈추지 않고도 피드백을 받을 수 있다.
 */

/* global window, document */

(function () {
  "use strict";

  /** 토스트가 표시되는 시간 (밀리초) */
  const DURATION = {
    success: 3000,
    info: 3000,
    warning: 5000,
    error: 7000,
  };

  /** 타입별 아이콘 (SVG) */
  const ICONS = {
    success:
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>',
    error:
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    warning:
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    info: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
  };

  /**
   * 토스트 알림 표시
   *
   * @param {string} message - 표시할 메시지
   * @param {'success'|'error'|'warning'|'info'} type - 알림 유형
   * @param {number} [duration] - 표시 시간 (밀리초). 미지정 시 유형별 기본값
   */
  function showToast(message, type, duration) {
    type = type || "info";
    duration = duration || DURATION[type] || 3000;

    let container = document.getElementById("toast-container");
    if (!container) {
      /* 컨테이너가 없으면 자동 생성 */
      container = document.createElement("div");
      container.id = "toast-container";
      container.className = "toast-container";
      container.setAttribute("aria-live", "polite");
      container.setAttribute("aria-atomic", "false");
      document.body.appendChild(container);
    }

    /* 토스트 요소 생성 */
    const toast = document.createElement("div");
    toast.className = "toast toast-" + type;
    toast.setAttribute("role", "alert");

    const icon = ICONS[type] || ICONS.info;
    toast.innerHTML =
      '<span class="toast-icon">' +
      icon +
      "</span>" +
      '<span class="toast-message">' +
      escapeHtml(message) +
      "</span>" +
      '<button class="toast-close" aria-label="닫기">&times;</button>';

    /* 닫기 버튼 */
    const closeBtn = toast.querySelector(".toast-close");
    closeBtn.addEventListener("click", function () {
      removeToast(toast);
    });

    /* 컨테이너에 추가 (최신이 위로) */
    container.prepend(toast);

    /* 등장 애니메이션 — reflow 후 active 클래스 추가 */
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        toast.classList.add("toast-active");
      });
    });

    /* 자동 제거 타이머 */
    const timer = setTimeout(function () {
      removeToast(toast);
    }, duration);

    /* 마우스 올리면 타이머 일시정지 */
    toast.addEventListener("mouseenter", function () {
      clearTimeout(timer);
    });
    toast.addEventListener("mouseleave", function () {
      setTimeout(function () {
        removeToast(toast);
      }, 1500);
    });
  }

  /**
   * 토스트 제거 (퇴장 애니메이션 후 DOM에서 삭제)
   */
  function removeToast(toast) {
    if (toast.classList.contains("toast-removing")) return;
    toast.classList.add("toast-removing");
    toast.addEventListener(
      "animationend",
      function () {
        toast.remove();
      },
      { once: true }
    );
    /* animationend가 실행 안 될 경우 대비 */
    setTimeout(function () {
      if (toast.parentNode) toast.remove();
    }, 500);
  }

  /**
   * HTML 이스케이프 (XSS 방지)
   */
  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  /* 전역에 노출 */
  window.showToast = showToast;
})();
