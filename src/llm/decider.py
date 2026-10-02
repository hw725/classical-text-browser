"""Perplexity Decisions API — 이미지를 받는 판정 모델 (D-134).

왜 있는가:
    판정 모델(«state + 형이 정해진 질문 → 확률 붙은 답», 글을 만들지 않는다)은 지금까지 TypeSafe Jev
    하나였고 Jev는 **텍스트 전용**이다. 그래서 쪽 이미지를 봐야 하는 일 — 자동 스캔의 «무슨 글인가»
    (활자·판본·손글씨·훈점·한글·백지) — 은 생성형 비전 LLM에 자유 JSON을 받아 왔고 느렸다.
    Perplexity의 decider-27b는 같은 계약에 이미지를 받는다. 답은 정해진 선택지의 확률뿐이라
    «정해진 값이 아니면 버린다»를 파서가 아니라 형식이 지킨다.

무엇을 아는가 (공식 문서 2026-10-02 확인 — docs.perplexity.ai/docs/decisions):
    - `POST https://api.perplexity.ai/v1/decisions`, `Authorization: Bearer <키>`(x-api-key는 401).
      끝에 `/`를 붙이거나 다른 경로면 404.
    - 본문 `{model, state, questions}` → `{model, answers, usage:{input_tokens, output_tokens}}`.
      모델 id는 `decider-27b`(HF 이름 pplx-decider-v1-27b는 API에서 안 받는다).
    - 이미지는 **state 배열 안에**
      `{"type":"image_url","image_url":{"url":"data:image/png;base64,…"}}`.
      PNG·JPEG·WebP data URL만 — http(s) 주소는 400(«API는 주소를 가져오지 않는다»).
      한 장에 32×32 타일 2,048개까지(1440×1440은 되고 1600×1310은 안 된다). 넘기면 1분쯤 기다리다
      504가 온다 — 그래서 보내기 전에 줄인다(`fit_image`). 메가픽셀당 약 1,000 입력 토큰.
    - 입력 100만 토큰당 $0.04, 출력 무료, 요청당 요금 없음. 초당 10요청(모든 요금제), 넘으면 429 +
      Retry-After. 질문 1~128개, 입력 262,144토큰 미만, 본문 32MiB.
    - **언어별 정확도는 문서에 없다.** 기반은 Qwen3.8-27B. 한문·고서 이미지에서 얼마나 맞는지는
      우리 자료로 재야 한다(`scripts/eval_decider_survey.py`) — 재기 전에는 답을 «제안»으로만 쓴다.

키: PERPLEXITY_API_KEY — 환경변수 → 서고 `.env`(설정 화면 «판정 모델»에서 넣는다) → 프로젝트 `.env`.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from io import BytesIO
from typing import Any

from llm.jev import JevClient

DECIDER_URL = "https://api.perplexity.ai/v1/decisions"
DECIDER_MODEL = "decider-27b"
DECIDER_INPUT_USD_PER_M = 0.04
DECIDER_KEY_NAMES = ("PERPLEXITY_API_KEY",)

# 한 장의 상한 — 32×32 타일 2,048개. 여유를 두고 1,900타일(≈ 1.95MP)에 맞춘다
MAX_TILES = 1900
TILE = 32
_MIME_OK = {"image/png", "image/jpeg", "image/webp"}


def fit_image(data: bytes, mime: str = "image/jpeg") -> tuple[bytes, str]:
    """이미지를 상한 안으로 줄인다. 입력: 바이트, mime. 출력: (바이트, mime).

    왜: 상한을 넘으면 오류가 바로 오지 않고 1분 뒤 504가 온다(문서) — 쪽마다 1분을 버리지 않게
    보내기 전에 줄인다. 이미 작으면 그대로 둔다(다시 압축하면 화질만 잃는다).
    PIL이 없거나 못 읽는 바이트면 그대로 돌려준다 — 서버가 판단하게 한다.
    """
    try:
        from PIL import Image

        img = Image.open(BytesIO(data))
        w, h = img.size
        tiles = -(-w // TILE) * -(-h // TILE)
        if tiles <= MAX_TILES and mime in _MIME_OK:
            return data, mime
        img = img.convert("RGB")
        if tiles > MAX_TILES:  # 상한 안이면 키우지 않는다 — 형식만 JPEG로 바꾼다
            # 타일 수는 올림이라 면적 비율대로 줄여도 조금 넘칠 수 있다 — 넘으면 더 줄인다
            scale = (MAX_TILES / tiles) ** 0.5
            while True:
                nw, nh = max(TILE, int(w * scale)), max(TILE, int(h * scale))
                if -(-nw // TILE) * -(-nh // TILE) <= MAX_TILES:
                    break
                scale *= 0.97
            img = img.resize((nw, nh))
        out = BytesIO()
        img.save(out, format="JPEG", quality=88)
        return out.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001
        return data, mime


class DeciderClient(JevClient):
    """Perplexity Decisions — JevClient와 같은 ask·gate·usage, 이미지는 state 배열에 싣는다."""

    PROVIDER = "perplexity"
    DEFAULT_URL = DECIDER_URL
    DEFAULT_MODEL = DECIDER_MODEL
    URL_ENV = "PERPLEXITY_DECISIONS_URL"
    KEY_NAMES = DECIDER_KEY_NAMES
    KEY_FALLBACK_FILE = False  # 공용 키 파일은 Jev(llm_pipeline)의 것 — 여기서는 보지 않는다
    INPUT_USD_PER_M = DECIDER_INPUT_USD_PER_M
    ACCEPTS_IMAGES = True

    def _body(
        self, state: Any, questions: Mapping[str, Any], images: Sequence[tuple[bytes, str]]
    ) -> dict:
        """이미지가 있으면 state를 [글, 이미지…] 배열로 바꾼다(문서의 모양 그대로)."""
        if images:
            parts: list[Any] = []
            if isinstance(state, list):
                parts.extend(state)
            elif state not in (None, ""):
                # 글 조각은 문자열 그대로 — 객체 state는 JSON 글로 바꿔 배열에 넣는다
                parts.append(
                    state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)
                )
            for raw, mime in images:
                data, m = fit_image(raw, mime or "image/jpeg")
                url = f"data:{m};base64,{base64.b64encode(data).decode('ascii')}"
                parts.append({"type": "image_url", "image_url": {"url": url}})
            state = parts
        return {"model": self.model, "state": state, "questions": dict(questions)}


def decider_status(library_root=None) -> dict:
    """키가 있는가만 — 네트워크를 쓰지 않는다. 출력: {provider, has_key, model}."""
    c = DeciderClient(library_root=library_root, max_calls=0)
    return {"provider": c.PROVIDER, "has_key": c.has_key, "model": c.model}
