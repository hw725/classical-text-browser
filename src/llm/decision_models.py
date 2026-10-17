"""판정 모델 고르기 — OpenRouter decisions 목록에서 모델을 고른다 (D-142).

왜 있는가:
    판정 모델(《state + 형이 정해진 질문 → 확률 붙은 답》)은 지금까지 모델 id가
    클래스 상수였다(`jev-latest`·`pplx-decider-v1.1-27b`·`clef`·`decider-27b`).
    새 판(Jev 1.14·decider v1.2)이 나와도 코드를 고치지 않으면 바꿀 길이 없었고,
    업체마다 키·주소·사슬이 따로라 《지금 무엇이 답하는가》를 화면에서 알기 어려웠다.

    사용자 결정(2026-10-17): **판정은 OpenRouter 하나로 부르고, 모델은 OpenRouter
    decisions 목록(openrouter.ai/models?output_modalities=decisions)에서 설정 화면으로
    고른다.** 다른 플랫폼(TypeSafe·Perplexity·Cloudflare 직결)은 《추가 예정》으로만
    적고 쓰지 않는다 — 서고 .env에 그 키가 있어도 판정은 OpenRouter로 간다.
    그 클라이언트 코드(`jev.py`·`decider.py`·`clef_cf.py`)는 다시 붙일 자리라 남긴다.

무엇을 고르는가 (기본값은 사용자 지시 2026-10-17):
    - text           편성 「판정 모델로 고르기」의 본문 판정과 목차 대조
                     — 기본 `typesafe/jev-1.14`
    - text_fallback  text 모델이 실패한 호출만 대신 답한다
                     — 기본 `perplexity/pplx-decider-v1.2`, 빈 값이면 폴백 없음
    - image          「말로 지시」 ① 자동 스캔의 《무슨 글인가》
                     — 기본 `perplexity/pplx-decider-v1.2`. 실패한 쪽은 기본 비전
                     모델(kimi-k3)로 넘어간다(사슬 끝은 그대로)

어디에 저장하는가:
    앱 설정 `~/.classical-text-browser/config.json`의 `decision_models`. 비밀이 아니라
    서고 `.env`(키 자리)에 두지 않는다. 키(`OPENROUTER_API_KEY`)는 그대로 서고 `.env`.

목록은 어디서 오는가:
    `GET https://openrouter.ai/api/v1/models?output_modalities=decisions`(키 없이 열린다).
    한 시간 캐시하고, 닿지 않으면 `BUILTIN_CATALOG`(2026-10-17 그 주소에서 받은 것, 27개)를
    쓴다 — 오프라인 PC에서도 설정 화면이 고를 거리를 보이게.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

CATALOG_URL = "https://openrouter.ai/api/v1/models?output_modalities=decisions"
CATALOG_TTL = 3600.0  # 초 — 목록은 하루에 몇 번 바뀌지 않는다
CATALOG_TIMEOUT = 5.0

DEFAULT_TEXT_MODEL = "typesafe/jev-1.14"
DEFAULT_TEXT_FALLBACK_MODEL = "perplexity/pplx-decider-v1.2"
DEFAULT_IMAGE_MODEL = "perplexity/pplx-decider-v1.2"
DEFAULTS: dict[str, str] = {
    "text": DEFAULT_TEXT_MODEL,
    "text_fallback": DEFAULT_TEXT_FALLBACK_MODEL,
    "image": DEFAULT_IMAGE_MODEL,
}
SLOTS = tuple(DEFAULTS)

# OpenRouter 모델 id 모양 — 《업체/이름》(별칭은 앞에 ~, 무료판은 뒤에 :free).
# 화면에서 온 값을 본문에 넣기 전에 거른다
_MODEL_ID_RE = re.compile(r"^~?[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._:-]*$")

# 판정 플랫폼 — 지금은 OpenRouter만 쓴다(사용자 결정 2026-10-17).
# 나머지는 화면에 《추가 예정》으로만 보인다
PLATFORMS: list[dict[str, str]] = [
    {"id": "openrouter", "label": "OpenRouter", "status": "active"},
    {"id": "typesafe", "label": "TypeSafe 직결 (Jev)", "status": "planned"},
    {"id": "perplexity", "label": "Perplexity 직결 (Decider)", "status": "planned"},
    {"id": "cloudflare", "label": "Cloudflare Workers AI 직결 (clef)", "status": "planned"},
]

# 2026-10-17 CATALOG_URL에서 받은 목록 — (id, 이름, 입력 형식, 입력 100만 토큰당 $). 그날 28개였고
# 이튿날 목록에서 빠진 `perplexity/pplx-decider-v1.1-27b`를 뺐다(27개) —
# 오프라인에서 은퇴 모델을 고르지 않게.
# 목록이 닿지 않을 때만 쓴다. 단가는 미리 세기의 어림에만 들어가고,
# 실제 비용은 응답의 usage.cost다
_TI = ("text", "image")
_T = ("text",)
_BUILTIN_ROWS: list[tuple[str, str, tuple[str, ...], float]] = [
    ("perplexity/pplx-decider-flash-v1.2", "Perplexity: Decider Flash V1.2", _TI, 0.01),
    ("perplexity/pplx-decider-v1.2", "Perplexity: Decider V1.2", _TI, 0.02),
    ("~perplexity/pplx-decider-flash-latest", "Perplexity: Decider Flash Latest", _TI, 0.01),
    ("respan/span-02", "Respan: Span-02", _TI, 0.01),
    ("liquid/d1-ultra", "LiquidAI: d1-ultra", _TI, 0.042),
    ("typesafe/jev-1.14", "TypeSafe: Jev 1.14", _TI, 0.042),
    ("~perplexity/pplx-decider-latest", "Perplexity: Decider Latest", _TI, 0.02),
    ("scaledown/classify-1", "ScaleDown: Classify-1", ("text", "image", "file"), 0.04),
    ("nace-ai/drex-v2.0", "Nace.AI: Drex v2.0", _T, 0.06),
    ("microsoft/microsoft-decision-1", "Microsoft: Microsoft-Decision-1", _T, 0.042),
    ("nace-ai/drex-v1.5", "Nace.AI: Drex v1.5", _T, 0.04),
    ("cloudflare/clef-omni", "Cloudflare: Clef Omni", ("text", "image", "audio", "video"), 0.15),
    ("upstage/solar-decide-flash", "Upstage: Solar Decide Flash", _T, 0.05),
    ("openai/gpt-6-luna-decisions", "OpenAI: GPT-6 Luna Decisions", _TI, 0.1),
    ("liquid/d1", "LiquidAI: d1", _TI, 0.02),
    ("cloudflare/clef-flash", "Cloudflare: Clef Flash", _TI, 0.021),
    ("cloudflare/clef", "Cloudflare: Clef", _TI, 0.042),
    ("togethercomputer/tev1-4b-experimental", "Together: Tev1 4B Experimental", _T, 0.042),
    ("inception/mercury-decide", "Inception: Mercury Decide", _TI, 0.02),
    ("inception/mercury-decide:free", "Inception: Mercury Decide (free)", _TI, 0.0),
    ("upstage/solar-decide", "Upstage: Solar Decide", _T, 0.05),
    ("respan/span-01", "Respan: Span-01", _T, 0.02),
    ("respan/span-01-lite", "Respan: Span-01 Lite", _T, 0.0),
    ("respan/span-01-lite:free", "Respan: Span-01 Lite (free)", _T, 0.0),
    ("jaredpalmer/kev-4b", "Jared Palmer: Kev 4B", _T, 0.042),
    ("~typesafe/jev-latest", "TypeSafe: Jev Latest", _TI, 0.042),
    ("typesafe/jev-1.13", "TypeSafe: Jev 1.13", _TI, 0.042),
]
BUILTIN_CATALOG: list[dict[str, Any]] = [
    {"id": i, "name": n, "inputs": list(ins), "usd_per_m": p} for i, n, ins, p in _BUILTIN_ROWS
]
CATALOG_FETCHED_AT = "2026-10-17"

_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "models": None, "fail_at": 0.0}
# 받기에 실패하면 이만큼은 다시 받지 않는다 — 오프라인 PC가 설정을 열 때마다 5초씩 기다리지 않게.
# 「연결 확인」(force)은 이 유예를 건너뛴다.
CATALOG_RETRY_AFTER = 300.0


def valid_model_id(value: Any) -> bool:
    """OpenRouter 모델 id 모양인가. 입력: 아무 값. 출력: bool."""
    return isinstance(value, str) and bool(_MODEL_ID_RE.match(value.strip()))


def _parse_catalog(payload: dict) -> list[dict[str, Any]]:
    """OpenRouter /models 응답 → [{id, name, inputs, usd_per_m}].

    모양이 틀린 항목·판정(decisions)을 내지 않는 항목은 버린다."""
    out: list[dict[str, Any]] = []
    for m in (payload or {}).get("data") or []:
        mid = m.get("id") if isinstance(m, dict) else None
        if not valid_model_id(mid):
            continue
        arch = m.get("architecture") or {}
        pricing = m.get("pricing") or {}
        if not isinstance(arch, dict) or not isinstance(pricing, dict):
            # 항목 하나의 모양이 틀렸다고 목록 전체를 내장 목록으로 바꾸지 않는다 — 그 항목만 버린다
            continue
        # 없을 때(None)만 기본값 — 0·""·{} 같은 틀린 값은 아래 형식 검사에서 버린다
        outs = arch.get("output_modalities")
        outs = ["decisions"] if outs is None else outs
        ins = arch.get("input_modalities")
        ins = ["text"] if ins is None else ins
        if not isinstance(outs, list) or not isinstance(ins, list):
            # 글자 "image"를 낱자로 쪼개거나 숫자에서 TypeError가 나 목록 전체를 버리지 않게
            continue
        if "decisions" not in outs:
            continue
        raw = pricing.get("prompt")
        try:
            # 단가가 없거나 빈 값이면 《모름》 — 0으로 읽으면 화면이 《무료》라 하고 어림이 0이 된다
            usd: Optional[float] = None if raw in (None, "") else float(raw) * 1e6
        except (TypeError, ValueError, OverflowError):
            usd = None
        # OpenRouter는 가변 단가를 "-1"로 적는다 — 음수·무한·NaN은 《모름》
        # (화면이 《무료》로 보이거나 JSON 응답이 500이 되지 않게)
        if usd is not None and not (math.isfinite(usd) and usd >= 0):
            usd = None
        out.append(
            {
                "id": mid,
                "name": str(m.get("name") or mid),
                "inputs": [str(x) for x in ins],
                "usd_per_m": round(usd, 6) if usd is not None else None,
            }
        )
    return out


def fetch_catalog(
    *, opener=urllib.request.urlopen, now: Optional[float] = None, force: bool = False
) -> dict[str, Any]:
    """OpenRouter decisions 모델 목록.

    출력: {"models": [...], "source": "live"|"builtin", "fetched_at"}.
    한 시간 캐시한다. 닿지 않거나 모양이 틀리면 내장 목록을 돌려준다 — 예외를 내지
    않는다(설정 화면이 목록 없이 비지 않게). 키는 보내지 않는다(키 없이 열리는 주소다).
    """
    t = time.time() if now is None else now
    with _cache_lock:
        fresh = _cache["models"] is not None and t - _cache["at"] < CATALOG_TTL
        if fresh and not force:
            return {"models": _cache["models"], "source": "live", "fetched_at": _cache["at"]}
        failed_recently = t - _cache.get("fail_at", 0.0) < CATALOG_RETRY_AFTER
    if failed_recently and not force:
        return {
            "models": list(BUILTIN_CATALOG),
            "source": "builtin",
            "fetched_at": CATALOG_FETCHED_AT,
        }
    try:
        req = urllib.request.Request(CATALOG_URL, headers={"Accept": "application/json"})
        with opener(req, timeout=CATALOG_TIMEOUT) as resp:
            models = _parse_catalog(json.loads(resp.read().decode("utf-8")))
        if not models:
            raise ValueError("목록이 비었습니다")
    except Exception as e:  # noqa: BLE001 — 오프라인·차단·모양 틀림 모두 내장 목록으로
        logger.info("OpenRouter 판정 모델 목록을 받지 못해 내장 목록을 씁니다: %s", e)
        with _cache_lock:
            _cache["fail_at"] = t
        return {
            "models": list(BUILTIN_CATALOG),
            "source": "builtin",
            "fetched_at": CATALOG_FETCHED_AT,
        }
    with _cache_lock:
        _cache.update(at=t, models=models)
    return {"models": models, "source": "live", "fetched_at": t}


def cached_catalog() -> list[dict[str, Any]]:
    """네트워크 없이 아는 목록 — 캐시가 있으면 그것, 없으면 내장. 단가 어림·입력 형식용.

    캐시가 만료된 뒤 받기에 실패해도 옛 live 목록을 그대로 쓴다(설정 화면은 내장 목록을 보일 수
    있다 — 둘 다 그날 받은 목록이라 단가 어림의 차이는 작다)."""
    with _cache_lock:
        return list(_cache["models"] or BUILTIN_CATALOG)


def model_info(model: str) -> Optional[dict[str, Any]]:
    """아는 목록에서 모델 하나. 없으면 None.

    목록에 없는 id도 고를 수는 있다 — 목록보다 새 모델일 수 있다."""
    return next((m for m in cached_catalog() if m["id"] == model), None)


def accepts_images(model: str) -> Optional[bool]:
    """이미지를 받는 모델인가. 목록에 없으면 None(모름)."""
    info = model_info(model)
    return None if info is None else "image" in (info.get("inputs") or [])


def load_selection() -> dict[str, str]:
    """지금 고른 모델 셋. 출력: {"text", "text_fallback", "image"}.

    저장값이 없거나 모양이 틀린 칸은 기본값. text_fallback만 빈 문자열(《폴백 없음》)을
    저장값으로 받는다."""
    from core.app_config import load_app_config

    saved = load_app_config().get("decision_models") or {}
    out: dict[str, str] = {}
    for slot, default in DEFAULTS.items():
        v = saved.get(slot) if isinstance(saved, dict) else None
        if slot == "text_fallback" and v == "":
            out[slot] = ""
        elif valid_model_id(v):
            out[slot] = v.strip()
        else:
            out[slot] = default
    return out


def save_selection(updates: dict[str, Optional[str]]) -> dict[str, str]:
    """고른 모델을 저장한다. 출력: 저장 뒤의 고름.

    입력: 칸별 값 — None이면 그 칸은 그대로, text_fallback의 ""는 《폴백 없음》.
    모양이 틀린 id는 ValueError — 화면이 그 문구를 보인다."""
    from core.app_config import load_app_config, save_app_config

    current = load_selection()
    for slot, v in updates.items():
        if slot not in DEFAULTS or v is None:
            continue
        v = v.strip()
        if slot == "text_fallback" and v == "":
            current[slot] = ""
            continue
        if not valid_model_id(v):
            raise ValueError(
                f"모델 id 모양이 아닙니다: {v!r} — OpenRouter 목록의 id"
                f"(예: {DEFAULTS[slot]})를 고르세요."
            )
        if slot == "image" and accepts_images(v) is False:
            # 목록이 텍스트만 받는다고 적은 모델 — 이미지를 보내기 전에 거부되어
            # 쪽마다 비전으로 넘어간다.
            # 목록에 없는 모델(모름)은 막지 않는다 — 목록보다 새 모델일 수 있다
            raise ValueError(
                f"{v}는 OpenRouter 목록에서 이미지를 받지 않는 모델입니다 — 이미지 칸에는 "
                "이미지를 받는 모델을 고르세요."
            )
        current[slot] = v
    cfg = load_app_config()
    cfg["decision_models"] = current
    save_app_config(cfg)
    return current


def make_decision_client(model: str, **kwargs):
    """고른 모델로 OpenRouter 판정 클라이언트를 만든다.

    입력: 모델 id, JevClient 생성자 인자(library_root·max_calls 등).
    출력: `OpenRouterModelClient`."""
    from llm.openrouter_decider import OpenRouterModelClient

    return OpenRouterModelClient(model=model, **kwargs)
