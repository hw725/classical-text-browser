"""자동 폴백에서 앞 순위가 실패한 사실을 요청 단위로 모은다 (D-143).

왜 필요한가:
    라우터는 앞 순위 실패를 모아 두기만 하고, 모두 실패했을 때만 알렸다. 그래서 4월 기본 모델이
    반년 동안 404·500을 내는 사이에도 화면·서버 기록에는 아무것도 남지 않았다(2026-10-18, 답은
    3순위 Gemini에서 왔다). LLM을 부르는 라우트는 200개가 넘는다 — 라우트마다 응답에 꼬리표를
    붙이게 하면 새 라우트에서 또 빠진다. 미들웨어가 요청마다 빈 목록을 깔아 두고, 라우터가 거기에
    적고, 미들웨어가 응답 머리 `X-CTB-LLM-Fallback`에 싣는다. 화면(toast.js)은 fetch 한 곳에서
    그 머리를 보고 알린다.

한계:
    스트리밍 응답(SSE)과 응답 뒤에 도는 작업(배치 OCR)은 머리가 먼저 나가므로 실리지 않는다.
    그 경우에도 서버 경고 기록(llm.router)에는 남는다.
"""

from __future__ import annotations

import contextvars
from urllib.parse import quote

HEADER = "X-CTB-LLM-Fallback"

# 요청마다 미들웨어가 새 목록을 넣는다. 라우트는 다른 태스크에서 돌 수 있지만(BaseHTTPMiddleware)
# 컨텍스트 복사본이 **같은 목록 객체**를 가리키므로 append가 미들웨어에서 보인다.
_trails: contextvars.ContextVar[list | None] = contextvars.ContextVar(
    "ctb_llm_fallback", default=None
)


def begin() -> tuple[list, contextvars.Token]:
    """요청 하나를 시작한다. 출력: (모을 목록, 되돌릴 토큰)."""
    bucket: list = []
    return bucket, _trails.set(bucket)


def end(token: contextvars.Token) -> None:
    _trails.reset(token)


def record(text: str) -> None:
    """폴백 한 건을 적는다. 요청 밖(스크립트·백그라운드)이면 아무것도 하지 않는다."""
    bucket = _trails.get()
    if bucket is not None and text:
        bucket.append(text)


def describe(trail: list[dict], winner: str) -> str:
    """사람이 읽는 한 줄. 예: `ollama/kimi-k3:cloud: 모델 없음 → openai_oauth/…: 500 → gemini/…`."""
    parts = []
    for f in trail:
        who = f["provider"] + (f"/{f['model']}" if f.get("model") else "")
        parts.append(f"{who}: {f['error']}")
    parts.append(winner)
    return " → ".join(parts)


def header_value(bucket: list) -> str:
    """응답 머리에 실을 값. 머리는 latin-1만 받으므로 UTF-8을 퍼센트 인코딩한다. 길면 자른다."""
    # 단위마다 라우터를 부르는 라우트는 같은 줄을 N번 적는다 — 한 번씩만 싣는다(순서 유지)
    return quote(" | ".join(dict.fromkeys(bucket))[:1500], safe=" /:|()")
