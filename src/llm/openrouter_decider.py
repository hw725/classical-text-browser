"""OpenRouter로 부르는 Perplexity decider — 편성 «글이 시작하는 행» 판정의 기본 (D-136).

왜 있는가:
    편성 「더 묻기…」의 판정 모델(D-129)은 TypeSafe Jev였다. 같은 저장 측정(천진담초·운양집 1책
    정답, 2026-10-03 —
    head-repo `docs/clef-vs-jev-20261003/scripts_or/{decider,jev}/ctb_*.json`)에서
    Perplexity decider가 F1 0.846 대 0.818(천진담초), 0.814 대 0.743(운양집 1책)으로 앞섰다.
    사용자 결정(2026-10-05)으로 본문 경계 판정의 기본을 이것으로 바꾼다.

왜 `llm/decider.py`(Perplexity 직결)를 쓰지 않는가:
    측정은 OpenRouter 경유였다. 주소·모델 id·키가 모두 다르다 — 직결은 `decider-27b`를
    `api.perplexity.ai`에 PERPLEXITY_API_KEY로, 이것은 `perplexity/pplx-decider-v1-27b`를
    OpenRouter에 OPENROUTER_API_KEY로 보낸다. 잰 길과 같은 길로 부른다.

무엇을 아는가:
    - `POST https://openrouter.ai/api/alpha/decisions`,
      본문은 System One과 같은 {model, state, questions}.
    - 응답은 {answers, usage{input_tokens, cost}} — Cloudflare처럼 한 겹 싸지 않는다(벗길 것 없음).
      cost는 게이트웨이가 준 값이라 JevClient가 그것을 정본으로 쓴다.
    - 텍스트만 보낸다. 이미지 싣는 법은 측정하지 않았다 — 이미지가 오면 보내기 전에 거부한다.

키 — **TypeSafe 키를 OpenRouter로 보내지 않는다:**
    JevClient의 KEY_NAMES는 TYPESAFE_API_KEY가 맨 앞이다. 그대로 물려받으면 TypeSafe 키가
    OpenRouter 주소로 나간다(2026-09-21 401 사고의 거울상). 그래서 이름을 OPENROUTER_API_KEY
    하나로 좁힌다. 찾는 순서는 Jev와 같다: 환경변수 → 서고 `.env`(설정 ▸ 판정 모델) → 프로젝트
    `.env` → 개인 키 파일(`~/.claude/data/triage/.env` — llm_pipeline이 OpenRouter 키를 두는 곳).
"""

from __future__ import annotations

from llm.jev import JevClient

OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
OPENROUTER_DECIDER_MODEL = "perplexity/pplx-decider-v1-27b"
# 게이트웨이가 usage.cost를 주면 그 값을 쓴다. 이것은 cost가 빠졌을 때의 어림뿐이다 —
# Perplexity 직결 단가($0.04/M, D-134)를 빌렸고 OpenRouter 단가로 잰 값이 아니다.
OPENROUTER_DECIDER_USD_PER_M = 0.04
OPENROUTER_KEY_NAMES = ("OPENROUTER_API_KEY",)


class OpenRouterDecisionClient(JevClient):
    """OpenRouter decisions — JevClient와 같은 ask·gate·usage, 주소·모델·키 이름만 다르다."""

    PROVIDER = "openrouter"
    DEFAULT_URL = OPENROUTER_DECISIONS_URL
    DEFAULT_MODEL = OPENROUTER_DECIDER_MODEL
    URL_ENV = "OPENROUTER_DECISIONS_URL"
    KEY_NAMES = OPENROUTER_KEY_NAMES  # TYPESAFE_API_KEY를 물려받지 않는다 — 위 «키» 참고
    KEY_FALLBACK_FILE = True  # 개인 키 파일에 OPENROUTER_API_KEY가 있다(Jev와 같은 마지막 출처)
    INPUT_USD_PER_M = OPENROUTER_DECIDER_USD_PER_M
    ACCEPTS_IMAGES = False  # 측정하지 않은 길 — 보내기 전에 거부한다


OPENROUTER_CLEF_MODEL = "cloudflare/clef"
OPENROUTER_CLEF_USD_PER_M = 0.24  # OpenRouter 모델 목록 실측(2026-10-05), Cloudflare 직접과 같다


class OpenRouterClefClient(OpenRouterDecisionClient):
    """OpenRouter로 부르는 clef — 이미지 판정의 2단계(Cloudflare 무료량이 바닥났거나 실패할 때).

    사용자 결정(2026-10-05): 이미지 판정은 Cloudflare clef(무료, 하루 ≈250쪽)
    → OpenRouter clef(유료 크레딧,
    쪽당 ≈$0.0004) → 기본 비전 모델. 같은 모델을 다른 길(게이트웨이)로 부른다.

    실측으로 정한 세 가지(head-repo `docs/clef-vs-jev-20261003/`):
    - 이미지는 `state` 배열의 `{"type": "image_url", "image_url": {"url": data URL}}`로만 받는다 —
      최상위 `images`는 조용히 무시된다(빨강·파랑 색 시험에서 둘 다 0.019).
    - 뒤는 Cloudflare라 문맥 사전 검사가 이미지를 바이트로 어림한다 — ClefClient와 같은 2MP·300KB로
      맞춘다. **보낸 뒤 다시 인코딩하지 않는다**: DeciderClient식 재인코딩은
      300KB를 ≈470KB로 되돌려 413을 냈다.
    - 같은 쪽 실제 청구는 ≈1,850토큰(300KB·200KB 모두 통과).
    """

    DEFAULT_MODEL = OPENROUTER_CLEF_MODEL
    INPUT_USD_PER_M = OPENROUTER_CLEF_USD_PER_M
    ACCEPTS_IMAGES = True

    def _body(self, state, questions, images):
        """{model, state, questions}. 이미지가 있으면 state를 [글, image_url…] 배열로 바꾼다."""
        import base64

        from llm.clef_cf import DEFAULT_IMAGE_BYTES, DEFAULT_IMAGE_PIXELS, fit_image_clef

        if not images:
            return {"model": self.model, "state": state, "questions": dict(questions)}
        parts: list = [state if isinstance(state, str) else str(state)]
        for raw, mime in images:
            data, m = fit_image_clef(
                raw,
                mime or "image/jpeg",
                max_bytes=DEFAULT_IMAGE_BYTES,
                max_pixels=DEFAULT_IMAGE_PIXELS,
            )
            url = f"data:{m};base64,{base64.b64encode(data).decode('ascii')}"
            parts.append({"type": "image_url", "image_url": {"url": url}})
        return {"model": self.model, "state": parts, "questions": dict(questions)}
