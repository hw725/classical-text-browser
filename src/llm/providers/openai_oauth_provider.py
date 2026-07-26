"""OpenAI OAuth Provider.

openai-oauth (https://github.com/EvanZhouDev/openai-oauth) 프록시를 통해
ChatGPT 계정 인증으로 OpenAI API를 무료로 사용.

사전 준비:
    1. npx @openai/codex login   ← ChatGPT 계정으로 OAuth 인증
    2. npx openai-oauth           ← 로컬 프록시 시작

프록시가 실행 중이면 자동으로 감지하여 OpenAI API 키 없이 사용할 수 있다.
OPENAI_API_KEY가 설정된 경우에도, 프록시가 살아있으면 이 프로바이더가
일반 OpenAI보다 우선 사용된다 (비용 절감).

포트 탐색:
    openai-oauth의 기본 포트는 10531이지만, 다른 프로그램이 점유하면
    자동으로 인접 포트(10532~10540)로 올려서 시작한다.
    이 프로바이더도 동일 범위를 스캔해서 프록시를 자동 발견한다.
    OPENAI_OAUTH_BASE_URL 환경변수를 설정하면 스캔 없이 고정 URL을 사용한다.
"""

import logging
from typing import Optional

from .openai_provider import OpenAiProvider

_logger = logging.getLogger(__name__)

# openai-oauth 기본 포트 및 스캔 범위
_DEFAULT_PORT = 10531
_PORT_SCAN_RANGE = range(10531, 10541)  # 10531~10540


class OpenAiOAuthProvider(OpenAiProvider):
    """openai-oauth 프록시를 통한 OpenAI API 호출.

    OpenAiProvider를 상속하여 클라이언트 생성과 가용성 체크만 오버라이드.
    호출 로직(call, call_stream, call_with_image)은 부모 클래스 것을 그대로 사용.
    """

    provider_id = "openai_oauth"
    display_name = "OpenAI (OAuth)"
    supports_image = True
    # ChatGPT 구독 한도를 쓴다. 종량 과금이 아니므로 금액은 0으로 기록되지만
    # 한도는 소모된다 — 남은 한도는 OpenAI 쪽에서 확인해야 한다.
    billing_model = "subscription"
    DEFAULT_MODEL = "gpt-5.4-mini"  # OAuth 프록시 기본 모델 (비용 효율적)

    # API 키가 아니라 ChatGPT 계정으로 로그인한다. 프록시가 브라우저를 열어
    # 인증을 받으므로 앱이 대신할 수 없다.
    setup_kind = "cli_signin"
    setup_steps = (
        "npx -y openai-oauth   (Windows에서는 start_server.bat가 자동 기동)",
        "브라우저가 열리면 ChatGPT 계정으로 로그인",
    )

    # is_available()에서 발견한 프록시 URL을 캐싱.
    # 매 호출마다 포트 스캔을 반복하지 않기 위함.
    _discovered_url: Optional[str] = None

    # 프록시에서 발견된 모델 목록을 캐싱 (list_models 용)
    _discovered_models: Optional[list[dict]] = None

    def _get_base_url(self) -> str:
        """프록시 URL 조회.

        우선순위:
            1. 환경변수 OPENAI_OAUTH_BASE_URL (고정)
            2. is_available()에서 자동 발견한 URL (캐시)
            3. 기본 포트 10531
        """
        explicit = self.config.get("OPENAI_OAUTH_BASE_URL")
        if explicit:
            return explicit
        if self._discovered_url:
            return self._discovered_url
        return f"http://127.0.0.1:{_DEFAULT_PORT}/v1"

    async def _probe_port(self, port: int) -> Optional[list[dict]]:
        """특정 포트에 openai-oauth 프록시가 있는지 HTTP로 확인.

        반환: 성공 시 모델 리스트 [{id, ...}, ...], 실패 시 None.
        """
        try:
            import httpx

            url = f"http://127.0.0.1:{port}/v1/models"
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(
                    url,
                    headers={"Authorization": "Bearer oauth-proxy"},
                )
                if resp.status_code != 200:
                    return None
                # OpenAI 호환 프록시는 {"object": "list", "data": [...]} 형태
                data = resp.json()
                if isinstance(data, dict) and "data" in data:
                    return data["data"]
                return None
        except Exception:
            return None

    async def is_available(self) -> bool:
        """openai-oauth 프록시가 실행 중인지 확인.

        OPENAI_OAUTH_BASE_URL이 설정되어 있으면 해당 URL만 확인.
        아니면 10531~10540 범위를 스캔하여 프록시를 자동 발견한다.
        openai-oauth는 기본 포트가 점유되어 있으면 다음 포트로 올리므로
        이 범위를 확인해야 안정적으로 연결할 수 있다.
        """
        explicit = self.config.get("OPENAI_OAUTH_BASE_URL")
        if explicit:
            # 고정 URL이면 해당 URL만 확인
            try:
                from urllib.parse import urlparse

                port = urlparse(explicit).port or _DEFAULT_PORT
                models = await self._probe_port(port)
                if models is not None:
                    self._discovered_url = explicit
                    self._discovered_models = models
                    return True
            except Exception:
                pass
            self._discovered_url = None
            self._discovered_models = None
            return False

        # 포트 스캔: 캐시된 포트 먼저 시도 후, 나머지 스캔
        if self._discovered_url:
            try:
                from urllib.parse import urlparse

                cached_port = urlparse(self._discovered_url).port
                if cached_port:
                    models = await self._probe_port(cached_port)
                    if models is not None:
                        self._discovered_models = models
                        return True
            except Exception:
                pass

        # 전체 범위 스캔 — 10개 포트를 **동시에** 훑는다.
        #
        # 왜 직렬로 하면 안 되는가: 프록시가 안 떠 있으면 포트마다 2초씩
        # 기다려 총 20초가 걸린다. 그동안 설정 화면은 «로딩 중»에 멈춰 있고,
        # 이 프로바이더 하나 때문에 나머지 넷의 상태도 못 본다.
        # 실측(2026-07-26): 직렬 20.2초 → 동시 2초 남짓.
        import asyncio

        ports = list(_PORT_SCAN_RANGE)
        results = await asyncio.gather(
            *(self._probe_port(p) for p in ports), return_exceptions=True
        )
        for port, models in zip(ports, results):
            # 낮은 포트를 우선한다 — openai-oauth가 기본 포트부터 올리므로
            # 여러 개가 떠 있으면 먼저 뜬 것이 정본일 가능성이 높다.
            if isinstance(models, list):
                self._discovered_url = f"http://127.0.0.1:{port}/v1"
                self._discovered_models = models
                _logger.info(f"openai-oauth 프록시 발견: port {port}")
                return True

        self._discovered_url = None
        self._discovered_models = None
        return False

    async def list_models(self) -> list[dict]:
        """프록시에서 제공하는 모델 목록 반환.

        is_available()에서 캐싱된 목록을 사용한다.
        캐시가 없으면 다시 프록시에 질의한다.
        """
        if self._discovered_models:
            return [
                {
                    "name": m.get("id", "unknown"),
                    "vision": True,  # ChatGPT 모델은 대부분 비전 지원
                    "cost": "free",
                }
                for m in self._discovered_models
            ]
        # 캐시 없으면 다시 확인
        await self.is_available()
        if self._discovered_models:
            return [
                {
                    "name": m.get("id", "unknown"),
                    "vision": True,
                    "cost": "free",
                }
                for m in self._discovered_models
            ]
        return []

    def _create_client(self):
        """openai-oauth 프록시를 가리키는 AsyncOpenAI 클라이언트 생성.

        프록시는 인증을 자체 처리하므로 API 키가 불필요하다.
        OpenAI SDK가 api_key 필수이므로 더미 값을 넣는다.
        """
        import openai

        return openai.AsyncOpenAI(
            api_key="oauth-proxy",  # 프록시가 인증 처리, 더미 값
            base_url=self._get_base_url(),
        )

    def _estimate_cost(
        self, model: str, tokens_in: Optional[int], tokens_out: Optional[int]
    ) -> float:
        """OAuth 프록시는 ChatGPT 계정 크레딧을 사용하므로 API 비용은 0."""
        return 0.0
