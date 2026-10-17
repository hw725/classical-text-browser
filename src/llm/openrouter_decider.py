"""OpenRouter로 부르는 판정 모델 — 지금은 설정에서 고른 모델(`OpenRouterModelClient`, D-142).

2026-10-17(D-142): 편성·자동 스캔은 이제 설정에서 고른 OpenRouter 모델(아래
`OpenRouterModelClient`)로만 부른다. 이 파일의 다른 셋(decider v1.1 고정·Jev 경유·clef 경유)은
옛 경로·평가 스크립트가 쓰는 것으로 남아 있다. 아래는 D-136·D-139 당시의 기록이다.

2026-10-11(D-139): v1(`pplx-decider-v1-27b`)이 OpenRouter에서 폐기(404 《No endpoints found》)되어
v1.1(`pplx-decider-v1.1-27b`)로 바꾸고, 주 판정자는 Jev로 되돌렸다 —
이것은 Jev가 실패한 호출만 대신 답한다.
아래 《왜 있는가》는 D-136 당시(v1을 주로 쓰던 때)의 근거다.

왜 있는가:
    편성 「더 묻기…」의 판정 모델(D-129)은 TypeSafe Jev였다. 같은 저장 측정(천진담초·운양집 1책
    정답, 2026-10-03 —
    head-repo `docs/clef-vs-jev-20261003/scripts_or/{decider,jev}/ctb_*.json`)에서
    Perplexity decider가 F1 0.846 대 0.818(천진담초), 0.814 대 0.743(운양집 1책)으로 앞섰다.
    사용자 결정(2026-10-05)으로 본문 경계 판정의 기본을 이것으로 바꾼다.

왜 `llm/decider.py`(Perplexity 직결)를 쓰지 않는가:
    측정은 OpenRouter 경유였다. 주소·모델 id·키가 모두 다르다 — 직결은 `decider-27b`를
    `api.perplexity.ai`에 PERPLEXITY_API_KEY로, 이것은 `perplexity/pplx-decider-v1.1-27b`를
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

from llm.jev import INPUT_USD_PER_M as JEV_INPUT_USD_PER_M
from llm.jev import JevClient

OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
OPENROUTER_DECIDER_MODEL = "perplexity/pplx-decider-v1.1-27b"
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
    KEY_NAMES = OPENROUTER_KEY_NAMES  # TYPESAFE_API_KEY를 물려받지 않는다 — 위 《키》 참고
    KEY_FALLBACK_FILE = True  # 개인 키 파일에 OPENROUTER_API_KEY가 있다(Jev와 같은 마지막 출처)
    INPUT_USD_PER_M = OPENROUTER_DECIDER_USD_PER_M
    ACCEPTS_IMAGES = False  # 측정하지 않은 길 — 보내기 전에 거부한다


OPENROUTER_JEV_MODEL = "~typesafe/jev-latest"


class OpenRouterJevClient(OpenRouterDecisionClient):
    """OpenRouter로 부르는 TypeSafe Jev — TypeSafe 키 없이 OpenRouter 키만 있을 때 (D-136 후속).

    사용자 결정(2026-10-05): OpenRouter 키만 있으면 Jev를 OpenRouter 경유로 부른다. 전에는
    JevClient가 OPENROUTER_API_KEY를 이름 목록 끝에 두어, 그 키를 **TypeSafe 주소로** 보내 401을
    받았다(목차 대조·decider 실패 시 폴백·설정 《연결 확인》 셋 다).

    계약은 llm_pipeline 정본(`llm_runtime/jev_decisions.py` PROVIDERS["openrouter"])과 같다 —
    주소 `/api/alpha/decisions`, 모델 `~typesafe/jev-latest`, 본문·응답은 직결과 같은
    {model, state, questions} → {answers, usage}, 키는 OPENROUTER_API_KEY 하나. 비용은
    usage.cost가 정본이고, 없으면 직결과 같은 Jev 입력 단가($0.042/M)로 어림한다(모델이 같다).

    **문턱은 Jev의 것이다**(0.85/0.5) — PROVIDER가 《openrouter》라 decider 문턱(0.997/0.69)을 받지
    않게 `JUDGE_FAMILY = "jev"`를 단다(`structure_llm.judge_thresholds`가 이것을 먼저 본다).
    텍스트 전용 — 이미지는 보내기 전에 거부한다(Jev는 base64를 글자로 읽는다, 2026-10-02 실측).
    """

    DEFAULT_MODEL = OPENROUTER_JEV_MODEL
    INPUT_USD_PER_M = JEV_INPUT_USD_PER_M  # $0.042/M — usage.cost가 없을 때만 쓴다
    ACCEPTS_IMAGES = False
    JUDGE_FAMILY = "jev"


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


# 고른 모델의 이미지 상한 — clef 길의 2MP·300KB(위 클래스 머리말의 실측)와 decider의 타일 상한
# (32×32 타일 2,048개, `decider.MAX_TILES` 1,900으로 여유) 중 작은 쪽. 어느 모델이 고르든 넘지 않게
_MODEL_IMAGE_PIXELS = min(2_000_000, 1900 * 32 * 32)
# 단가를 목록에서 못 찾을 때의 어림(입력 100만 토큰당 $) — 실제 비용은 응답의 usage.cost다
_MODEL_USD_PER_M_FALLBACK = 0.04


def judge_family(model: str) -> str:
    """모델 id → 문턱 계통. 입력: OpenRouter 모델 id. 출력: "jev" | "decider" | "unmeasured".

    문턱은 모델마다 저장 측정으로 골랐다(structure_llm.JUDGE_THRESHOLDS 머리말). 같은 계통의
    새 판(Jev 1.14·decider v1.2)은 **그 계통의 값을 빌린다 — 잰 값이 아니다.** 잰 적 없는 다른
    업체 모델은 "unmeasured"이고 Jev 값을 쓴다(structure_llm.judge_thresholds)."""
    m = (model or "").lower()
    if m.lstrip("~").startswith("typesafe/"):
        return "jev"
    if "pplx-decider" in m:
        return "decider"
    return "unmeasured"


class OpenRouterModelClient(OpenRouterDecisionClient):
    """설정에서 고른 OpenRouter 판정 모델 (D-142, 사용자 결정 2026-10-17).

    편성(텍스트)과 자동 스캔(이미지)이 모두 이 클라이언트로 부른다 — 모델 id만 다르다.
    주소·키·본문은 OpenRouter decisions 그대로(`/api/alpha/decisions`, OPENROUTER_API_KEY 하나).
    인스턴스마다 정하는 것:
      - INPUT_USD_PER_M: 모델 목록의 단가(미리 세기 어림용 — 실제 비용은 usage.cost)
      - ACCEPTS_IMAGES: 목록이 《텍스트만》이라 하면 이미지를 보내기 전에 거부한다(모르면 받는다)
      - JUDGE_FAMILY: 편성 문턱 계통(`judge_family`)
    이미지는 `state` 배열의 image_url이다 — OpenRouter decisions의 이미지 형식(위 clef 실측).
    """

    def __init__(self, *, model: str, **kwargs) -> None:
        from llm.decision_models import accepts_images, model_info

        super().__init__(model=model, **kwargs)
        info = model_info(model) or {}
        usd = info.get("usd_per_m")
        self.INPUT_USD_PER_M = float(usd) if usd is not None else _MODEL_USD_PER_M_FALLBACK
        self.ACCEPTS_IMAGES = accepts_images(model) is not False
        self.JUDGE_FAMILY = judge_family(model)

    def _body(self, state, questions, images):
        """{model, state, questions}. 이미지가 있으면 state를 [글, image_url…] 배열로 바꾼다."""
        import base64

        from llm.clef_cf import DEFAULT_IMAGE_BYTES, fit_image_clef

        if not images:
            return {"model": self.model, "state": state, "questions": dict(questions)}
        parts: list = [state if isinstance(state, str) else str(state)]
        for raw, mime in images:
            data, m = fit_image_clef(
                raw,
                mime or "image/jpeg",
                max_bytes=DEFAULT_IMAGE_BYTES,
                max_pixels=_MODEL_IMAGE_PIXELS,
            )
            url = f"data:{m};base64,{base64.b64encode(data).decode('ascii')}"
            parts.append({"type": "image_url", "image_url": {"url": url}})
        return {"model": self.model, "state": parts, "questions": dict(questions)}
