"""콘솔 출력을 UTF-8로 고정한다 — cp949 창에서 안내문이 죽지 않게.

## 왜 이 파일이 따로 있는가

한국어 Windows의 콘솔 기본 인코딩은 **cp949**다. 한글은 cp949에 들어 있지만
`—`(em dash, U+2014)·`«»`·`→`·`✓`는 **없다.** 그런 글자를 `print`하면
`UnicodeEncodeError`로 프로그램이 즉사한다 — 이 저장소의 안내문은 그런 글자를
일상적으로 쓴다.

이 PC는 사용자 환경변수 `PYTHONUTF8=1`이 박혀 있어 겪지 않는다. **받는 사람의
PC에는 없다.** 그래서 «내 PC에서 잘 돌았다»가 증거가 되지 못하는 자리다.

## 같은 교훈을 세 번 배웠다

1. 2026-07-26 — `ctb --help`가 cp949에서 죽었다. `src/cli/__main__.py`만 고쳤다.
2. 2026-09-06 — 창 없는 exe(`installer/ctb_setup.py`)에서 다시 겪었다. 거기만 고쳤다.
3. 2026-09-22 — 전수로 재니 `scripts/warmup_paddle.py`(설치 5단계)와
   `src/app/__main__.py`(`start_server.bat`이 `--reload`로 띄운다)가 **그대로**였다.
   고칠 때마다 그 파일만 고치고 형제 파일에 옮기지 않은 것이 원인이다.

그래서 정의를 **한 곳**에 두고, 배포되는 진입점이 이것을 부르는지
`tests/test_doc_drift.py`가 기계로 확인한다. `installer/ctb_setup.py`만 예외로
같은 처리를 직접 품는다 — 그 파일은 표준 라이브러리만으로 홀로 도는 exe라
이 저장소를 import할 수 없다(D-113).
"""

from __future__ import annotations

import sys

__all__ = ["force_utf8_console"]


def force_utf8_console() -> None:
    """`sys.stdout`·`sys.stderr`를 UTF-8로 다시 연다. 실패해도 조용히 지나간다.

    입력: 없음.
    출력: 없음(두 스트림의 인코딩을 바꾼다).
    목적: cp949 콘솔에서 안내문이 `UnicodeEncodeError`로 죽는 것을 막는다.

    `errors="replace"`를 함께 주는 이유:
        재설정이 통하지 않는 환경(파이프, 일부 터미널, 창 없는 exe)에서도
        «죽는» 대신 «몇 글자가 ?로 보이는» 쪽으로 끝나게 한다. 안내를 못 읽는
        것보다 조금 깨져 보이는 것이 낫다.

    `sys.stdout`이 `None`일 수 있다:
        창 없는(`pythonw`·`--noconsole`) 실행에서는 표준 출력이 아예 없다.
        그때 `getattr`가 `None`을 걸러 낸다.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue  # None 스트림이거나 재설정을 지원하지 않는 객체
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass  # 파이프·리다이렉트 등 재설정 불가 환경
