"""PaddleOCR 모델을 설치 단계에서 미리 받는다 — 첫 OCR이 몇 분씩 멈춰 보이지 않게.

왜: PaddleOCR은 처음 쓰일 때 검출·인식 모델(약 240MB)을 Baidu 서버에서 받는다. 한국에서는
느리고, 앱 화면에는 진행이 보이지 않아 «멈췄다»로 보인다(2026-09-06, 다른 PC 보고).
설치 스크립트가 이 스크립트를 한 번 돌려 두면 첫 실행이 바로 된다.

쓰는 법: uv run python scripts/warmup_paddle.py [언어…]   (기본: korean ch)
종료 코드: 0 성공, 1 실패(설치는 계속 — OCR 첫 실행 때 다시 받는다).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> int:
    langs = sys.argv[1:] or ["korean", "ch"]
    os.environ.setdefault("CTB_PADDLE_DEVICE", "cpu")
    try:
        from ocr.paddleocr_engine import PaddleOcrEngine
    except Exception as e:  # noqa: BLE001
        print(f"  PaddleOCR 모듈을 읽지 못했습니다: {e}")
        return 1
    rc = 0
    for lang in langs:
        t = time.time()
        print(f"  {lang} 모델 확인·받기 (처음이면 최대 200MB, 인터넷 필요)…", flush=True)
        try:
            engine = PaddleOcrEngine(lang=lang, use_gpu=False)
            if not engine.is_available():
                why = getattr(engine, "_unavailable_reason", "") or "PaddleOCR 사용 불가"
                print(f"  건너뜀: {why}")
                continue
            engine._get_ocr(lang)  # 여기서 모델을 받는다(이미 있으면 바로 끝난다)
            print(f"  {lang} 준비됨 ({time.time() - t:.0f}초)")
        except Exception as e:  # noqa: BLE001 — 실패해도 설치는 계속, 첫 OCR 때 다시 시도한다
            print(
                f"  {lang} 모델을 받지 못했습니다 ({type(e).__name__}: {str(e)[:120]})"
                " — 첫 OCR 때 다시 받습니다."
            )
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
