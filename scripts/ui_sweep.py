"""릴리스 전 화면 전체 훑기 — 읽기만 한다 (maintenance §5 4-1).

쓰는 법:  (사용자가 실제로 켜는 환경으로 서버를 띄운 뒤)
    .venv-gpu\\Scripts\\python.exe -m app serve --port 8179      # GPU PC — 아이콘이 고르는 환경
    uv run --with playwright python scripts/ui_sweep.py 8179

무엇을 보는가: 버전 표시, 사이드 패널 전부 열림, 콘솔·페이지 오류, 4xx/5xx 응답, 처음 설정 마법사.
저장·받기·설치·삭제류 단추는 누르지 않는다. 결과 그림은 logs/ui_sweep_*.png.
오류가 하나라도 있으면 종료 코드 1.

왜 있는가: 2026-09-06 v1.3.0 — diff 리뷰·pytest 1017건을 다 통과한 뒤 화면 아래 «v1.2.1»이 남아
있었다. 검증 서버는 uv run(.venv)으로 띄웠는데 아이콘은 .venv-gpu로 뜬다. 바뀐 부분만 보는 리뷰는
환경 상태와 diff 밖 화면을 못 본다 — 태그 전에 이 훑기를 사용자 실행 경로에서 돈다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8179"
OUT = Path(__file__).resolve().parents[1] / "logs"
OUT.mkdir(exist_ok=True)
# 이런 말이 든 단추는 상태를 바꾸므로 누르지 않는다.
DANGER = re.compile(
    r"저장|지우기|받기|설치|업데이트|삭제|초기화|리셋|시작|로그인|실행|만들기|가져오기|내보내기|보내기|적용|"
    r"되돌리기|커밋|추가|넣기|옮기기|쪼개기|백업|복원|휴지통|비우기"
)
# 설정 패널 안에서 «탭»으로 볼 요소 — 단추 일반은 아니다.
TAB_SEL = (
    "#settings-section [role=tab], #settings-section .tab, #settings-section .settings-tab, "
    "#settings-section .tabs button, #settings-section details > summary"
)
JS_BADGE = "() => (document.getElementById('app-version')||{}).textContent"
JS_WIZ_SHOWN = (
    "() => { const o = document.getElementById('setup-wizard-overlay'); "
    "return o && o.style.display !== 'none' ? 'shown' : 'hidden'; }"
)
JS_PANELS = (
    "() => [...document.querySelectorAll('[data-panel]')].map(e => e.getAttribute('data-panel'))"
)
JS_SETTINGS_ON = "() => !!document.querySelector('.activity-btn.active[data-panel=settings]')"
JS_TABS = (
    "(s) => [...document.querySelectorAll(s)]"
    ".map((e,i) => ({i, text: (e.innerText||'').trim().slice(0,30)}))"
)
JS_SCROLL_WIZ = "() => document.getElementById('btn-open-wizard').scrollIntoView({block: 'center'})"
JS_WIZ_BUTTONS = (
    "() => { const o = document.getElementById('setup-wizard-overlay'); "
    "if (!o) return 'no overlay'; "
    "return [...o.querySelectorAll('button')].map(b => b.innerText.trim()).filter(Boolean)"
    ".slice(0,40).join(' | '); }"
)


def main() -> int:
    """훑기를 돌리고 오류·실패 요청이 하나라도 있으면 1을 돌려준다."""
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True)
        pg = b.new_page(viewport={"width": 1400, "height": 950})
        errors: list[str] = []
        failed: list[str] = []

        def on_console(m) -> None:
            if m.type == "error":
                errors.append(f"console: {m.text[:160]}")

        def on_response(r) -> None:
            if r.status >= 400:
                failed.append(f"{r.status} {r.request.method} {r.url.split('?')[0][-90:]}")

        pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        pg.on("console", on_console)
        pg.on("response", on_response)

        pg.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
        pg.wait_for_timeout(4000)
        print("title:", pg.title())
        badge = pg.evaluate(JS_BADGE)
        print("version badge:", badge)
        if not badge or badge == "vunknown":
            errors.append("version badge empty/unknown")
        print("wizard on load:", pg.evaluate(JS_WIZ_SHOWN))

        panels = pg.evaluate(JS_PANELS)
        print("panels:", panels)
        for name in panels:
            try:
                pg.click(f"[data-panel='{name}']", timeout=3000)
                pg.wait_for_timeout(1200)
                print(f"  panel {name}: ok")
            except Exception as e:  # noqa: BLE001 — 실패도 기록이 목적
                print(f"  panel {name}: CLICK FAIL {type(e).__name__}")
                errors.append(f"panel {name} click failed")

        # 설정 패널 — 탭류만 누른다(위험 단추 제외). 켜진 패널을 다시 누르면 접히므로(인덱스 규칙)
        # 이미 켜져 있으면 누르지 않는다.
        if not pg.evaluate(JS_SETTINGS_ON):
            pg.click("[data-panel='settings']", timeout=3000)
        pg.wait_for_timeout(800)
        tabs = pg.evaluate(JS_TABS, TAB_SEL)
        print("settings tabs found:", len(tabs))
        for t in tabs:
            if DANGER.search(t["text"]):
                continue
            try:
                pg.locator(TAB_SEL).nth(t["i"]).click(timeout=2000)
                pg.wait_for_timeout(700)
                print(f"  tab ok: {t['text']}")
            except Exception as e:  # noqa: BLE001
                print(f"  tab FAIL: {t['text']} {type(e).__name__}")
        pg.screenshot(path=str(OUT / "ui_sweep_settings.png"))

        # 처음 설정 마법사 — 열어서 단추 이름만 읽는다(설정 패널 아래쪽에 있어 먼저 스크롤)
        try:
            pg.evaluate(JS_SCROLL_WIZ)
            pg.click("#btn-open-wizard", timeout=3000)
            pg.wait_for_timeout(2500)
            print("wizard buttons:", pg.evaluate(JS_WIZ_BUTTONS))
            pg.screenshot(path=str(OUT / "ui_sweep_wizard.png"))
        except Exception as e:  # noqa: BLE001
            print("wizard open FAIL:", type(e).__name__)
            errors.append("wizard open failed")

        print("\n== console/page errors:", len(errors))
        for e in errors[:30]:
            print("  ", e)
        print("== failed requests (>=400):", len(failed))
        for f in sorted(set(failed))[:30]:
            print("  ", f)
        b.close()
        return 1 if errors or failed else 0


if __name__ == "__main__":
    sys.exit(main())
