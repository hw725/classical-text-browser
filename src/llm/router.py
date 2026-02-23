"""LLM Router — 다단 폴백 + 모델 선택 + 비교.

모든 LLM 호출의 단일 진입점.
provider를 직접 호출하지 말고, 항상 이 Router를 통해 호출한다.

사용법:
    from src.llm.config import LlmConfig
    from src.llm.router import LlmRouter

    config = LlmConfig(library_root=Path("./test_library"))
    router = LlmRouter(config)

    # 자동 폴백
    response = await router.call("이 문장을 번역해줘")

    # 특정 모델 지정
    response = await router.call(
        "번역해줘",
        force_provider="ollama",
        force_model="glm-5:cloud"
    )

    # 비교
    results = await router.compare(
        "번역해줘",
        targets=["base44_bridge", ("ollama", "glm-5:cloud")]
    )
"""

import asyncio
import logging
import time
from typing import Optional

from .config import LlmConfig
from .providers.anthropic_provider import AnthropicProvider
from .providers.base import (
    BaseLlmProvider,
    LlmProviderError,
    LlmResponse,
    LlmUnavailableError,
)
from .providers.base44_bridge import Base44BridgeProvider
from .providers.gemini_provider import GeminiProvider
from .providers.ollama import OllamaProvider
from .providers.openai_provider import OpenAiProvider
from .usage_tracker import UsageTracker

_logger = logging.getLogger(__name__)


class LlmRouter:
    """LLM 호출 단일 진입점."""

    # is_available() 캐시 TTL (초).
    # Base44(subprocess 5s), Ollama(HTTP 3s) 같은 느린 체크를
    # 매 호출마다 반복하지 않기 위해 캐시한다.
    _AVAIL_TTL_OK = 120    # 사용 가능 → 2분간 재확인 안 함
    _AVAIL_TTL_FAIL = 30   # 사용 불가 → 30초간 재확인 안 함

    def __init__(self, config: Optional[LlmConfig] = None):
        self.config = config or LlmConfig()
        self.usage_tracker = UsageTracker(self.config)

        # 우선순위 순서 (무료 → 저렴 → 중간 → 최후)
        self.providers: list[BaseLlmProvider] = [
            Base44BridgeProvider(self.config),    # 1순위: 무료 (비전 포함)
            OllamaProvider(self.config),          # 2순위: 무료 (로컬/프록시)
            GeminiProvider(self.config),           # 3순위: 저렴 (비전 포함)
            OpenAiProvider(self.config),           # 4순위: 중간 (비전 포함)
            AnthropicProvider(self.config),       # 5순위: 최후 폴백
        ]

        # is_available() 캐시: {provider_id: (결과, 타임스탬프)}
        self._avail_cache: dict[str, tuple[bool, float]] = {}

    async def is_available_cached(self, provider: BaseLlmProvider) -> bool:
        """is_available() 결과를 캐싱하여 반환.

        왜 캐싱하는가:
            Base44는 Node.js subprocess(5초), Ollama는 HTTP(3초) 체크가 필요하다.
            자동 폴백에서 매번 순차 호출하면 사용 불가 프로바이더마다 3~5초 낭비.
            짧은 TTL로 캐싱하면 첫 호출 후 거의 즉시 건너뛸 수 있다.
        """
        pid = provider.provider_id
        cached = self._avail_cache.get(pid)
        if cached:
            ok, ts = cached
            ttl = self._AVAIL_TTL_OK if ok else self._AVAIL_TTL_FAIL
            if time.monotonic() - ts < ttl:
                return ok

        try:
            ok = await provider.is_available()
        except Exception:
            ok = False
        self._avail_cache[pid] = (ok, time.monotonic())
        return ok

    def invalidate_cache(self, provider_id: Optional[str] = None):
        """가용성 캐시를 무효화한다. 설정 변경 시 호출."""
        if provider_id:
            self._avail_cache.pop(provider_id, None)
        else:
            self._avail_cache.clear()

    def _get_provider(self, provider_id: str) -> Optional[BaseLlmProvider]:
        """provider_id로 provider 객체를 찾는다."""
        for p in self.providers:
            if p.provider_id == provider_id:
                return p
        return None

    async def call(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        response_format: str = "text",
        force_provider: Optional[str] = None,
        force_model: Optional[str] = None,
        purpose: str = "text",
        max_tokens: int = 4096,
        **kwargs,
    ) -> LlmResponse:
        """LLM 호출. 자동 폴백 또는 명시적 모델 선택.

        기본 동작: 우선순위에 따라 provider를 순서대로 시도.

        모델 선택 옵션 (품질 테스트·비교용):
            force_provider: 특정 provider만 사용
            force_model: 특정 모델 지정 (force_provider와 함께 사용)
        """
        # ── 명시적 선택 모드 ──
        if force_provider:
            provider = self._get_provider(force_provider)
            if not provider:
                available = [p.provider_id for p in self.providers]
                raise LlmProviderError(
                    f"provider '{force_provider}'을(를) 찾을 수 없습니다. "
                    f"사용 가능: {available}"
                )
            if not await provider.is_available():
                raise LlmProviderError(
                    f"provider '{force_provider}'이(가) 현재 사용할 수 없습니다."
                )

            response = await provider.call(
                prompt, system=system, response_format=response_format,
                model=force_model, max_tokens=max_tokens, purpose=purpose,
                **kwargs,
            )
            self.usage_tracker.log(response, purpose=purpose)
            return response

        # ── 자동 폴백 모드 ──
        # 1단계: 모든 프로바이더의 가용성을 병렬로 사전 체크 (캐시 활용).
        #   Base44(5s) + Ollama(3s) 순차 체크 → 최대 8초 낭비
        #   병렬 체크 + 캐시 → 첫 호출 max(5,3)=5초, 이후 ~0초
        avail_results = await asyncio.gather(
            *[self.is_available_cached(p) for p in self.providers],
            return_exceptions=True,
        )

        # 2단계: 사용 가능한 프로바이더만 우선순위대로 호출
        errors = []
        for provider, ok in zip(self.providers, avail_results):
            if ok is not True:
                continue
            try:
                response = await provider.call(
                    prompt, system=system, response_format=response_format,
                    max_tokens=max_tokens, purpose=purpose, **kwargs,
                )
                self.usage_tracker.log(response, purpose=purpose)
                return response

            except Exception as e:
                # 호출 실패 시 캐시 무효화 (다음에 재체크)
                self._avail_cache.pop(provider.provider_id, None)
                errors.append(f"{provider.provider_id}: {e}")
                continue

        raise LlmUnavailableError(
            "사용 가능한 LLM provider가 없습니다.\n"
            "확인 사항:\n"
            "  1. Base44: base44 login 후 bridge 스크립트 확인\n"
            "  2. Ollama: ollama serve\n"
            "  3. API 키: .env에 OPENAI_API_KEY, GOOGLE_API_KEY 등\n\n"
            "시도 결과:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    async def call_with_image(
        self,
        prompt: str,
        image: bytes,
        *,
        image_mime: str = "image/png",
        force_provider: Optional[str] = None,
        force_model: Optional[str] = None,
        purpose: str = "vision",
        **kwargs,
    ) -> LlmResponse:
        """이미지 분석 호출. supports_image인 provider만 시도."""
        if force_provider:
            provider = self._get_provider(force_provider)
            if not provider:
                raise LlmProviderError(
                    f"provider '{force_provider}' 없음"
                )
            if not provider.supports_image:
                raise LlmProviderError(
                    f"'{force_provider}'은(는) 이미지 미지원"
                )
            if not await provider.is_available():
                raise LlmProviderError(
                    f"'{force_provider}' 사용 불가"
                )

            response = await provider.call_with_image(
                prompt, image, image_mime=image_mime,
                model=force_model, **kwargs,
            )
            self.usage_tracker.log(response, purpose=purpose)
            return response

        # 비전 지원 프로바이더의 가용성을 병렬 체크
        vision_providers = [p for p in self.providers if p.supports_image]
        avail_results = await asyncio.gather(
            *[self.is_available_cached(p) for p in vision_providers],
            return_exceptions=True,
        )

        errors = []
        for provider, ok in zip(vision_providers, avail_results):
            if ok is not True:
                continue
            try:
                response = await provider.call_with_image(
                    prompt, image, image_mime=image_mime, **kwargs,
                )
                self.usage_tracker.log(response, purpose=purpose)
                return response
            except Exception as e:
                self._avail_cache.pop(provider.provider_id, None)
                errors.append(f"{provider.provider_id}: {e}")
                continue

        raise LlmUnavailableError(
            "이미지 분석 가능한 provider가 없습니다.\n"
            "시도 결과:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    async def compare(
        self,
        prompt: str,
        *,
        targets: Optional[list] = None,
        image: Optional[bytes] = None,
        system: Optional[str] = None,
        purpose: str = "comparison",
        **kwargs,
    ) -> list:
        """여러 모델에 같은 입력을 보내서 결과를 비교.

        targets: ["base44_bridge", ("ollama", "glm-5:cloud"), "anthropic"]
                 None이면 사용 가능한 모든 provider.

        반환: list[LlmResponse | Exception]
        """
        # 대상 결정
        if targets is None:
            pairs = []
            for p in self.providers:
                if image and not p.supports_image:
                    continue
                if await p.is_available():
                    pairs.append((p.provider_id, None))
        else:
            pairs = []
            for t in targets:
                if isinstance(t, str):
                    pairs.append((t, None))
                elif isinstance(t, (list, tuple)) and len(t) == 2:
                    pairs.append((t[0], t[1]))

        # 병렬 호출
        async def _one(pid, model):
            try:
                if image:
                    return await self.call_with_image(
                        prompt, image, system=system,
                        force_provider=pid, force_model=model,
                        purpose=purpose, **kwargs,
                    )
                else:
                    return await self.call(
                        prompt, system=system,
                        force_provider=pid, force_model=model,
                        purpose=purpose, **kwargs,
                    )
            except Exception as e:
                return e

        results = await asyncio.gather(*[_one(pid, m) for pid, m in pairs])

        self.usage_tracker.log_comparison(purpose, pairs, results)
        return list(results)

    async def get_available_models(self) -> list[dict]:
        """GUI 드롭다운용 모델 목록.

        list_models() 메서드가 있는 프로바이더(Ollama, OpenAI, Gemini)는
        개별 모델을 각각 표시한다.
        """
        models = []

        # list_models()를 지원하는 프로바이더 ID
        EXPANDABLE = {"ollama", "openai", "gemini"}

        for provider in self.providers:
            available = await provider.is_available()

            if provider.provider_id in EXPANDABLE and available:
                try:
                    provider_models = await provider.list_models()
                    for m in provider_models:
                        is_free = provider.provider_id == "ollama"
                        models.append({
                            "provider": provider.provider_id,
                            "model": m["name"],
                            "available": True,
                            "display": f"{provider.display_name} — {m['name']}",
                            "cost": "free" if is_free else m.get("cost", "paid"),
                            "vision": m.get("vision", False),
                        })
                except Exception:
                    models.append({
                        "provider": provider.provider_id,
                        "model": "(조회 실패)",
                        "available": False,
                        "display": f"{provider.display_name} (모델 목록 조회 실패)",
                        "cost": "free" if provider.provider_id == "ollama" else "paid",
                        "vision": False,
                    })
            else:
                models.append({
                    "provider": provider.provider_id,
                    "model": getattr(provider, "DEFAULT_MODEL", "auto"),
                    "available": available,
                    "display": provider.display_name,
                    "cost": (
                        "free"
                        if "base44" in provider.provider_id
                        or provider.provider_id == "ollama"
                        else "paid"
                    ),
                    "vision": provider.supports_image,
                })

        return models

    async def get_status(self) -> dict:
        """각 provider의 가용 상태. GET /api/llm/status에서 사용."""
        status = {}
        for provider in self.providers:
            try:
                avail = await provider.is_available()
                info = {
                    "available": avail,
                    "display_name": provider.display_name,
                }

                if provider.provider_id == "ollama" and avail:
                    models = await provider.list_models()
                    info["models"] = [m["name"] for m in models]

                status[provider.provider_id] = info
            except Exception as e:
                status[provider.provider_id] = {
                    "available": False,
                    "error": str(e),
                }
        return status
