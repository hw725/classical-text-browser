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

from .base import TRUNCATED_MARK, LlmProviderError, LlmResponse, thinking_options
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

    # «없더라»를 기억해 두는 시각. 화면을 열 때마다 2.4초를 다시 내지 않기 위함.
    # 짧게 잡아 프록시를 나중에 띄웠을 때 오래 기다리지 않게 한다.
    _miss_until: float = 0.0
    MISS_TTL_SEC = 30.0

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
            # 0.7초: 프록시는 로컬이라 있으면 수십 ms 안에 답한다. 2초로 두면 다른 프로그램이
            # 잡고 답하지 않는 포트(AnySign4PC의 10531)마다 2초씩 설정 화면이 멈춘다
            # (2026-09-05 실측).
            async with httpx.AsyncClient(timeout=0.7, trust_env=False) as client:
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

        # 못 찾은 결과를 잠깐 기억한다.
        #
        # 왜: 프록시가 안 떠 있으면 10개 포트가 모두 타임아웃해 **2.4초**가
        # 걸린다(동시 실행으로 20초에서 줄인 값이다). 그런데 이 확인은
        # /api/llm/status·/api/llm/models가 부르고, 그 둘은 화면을 열 때마다
        # 불린다. 프록시가 그 사이에 뜨는 일은 드무니 짧게 기억한다.
        import time as _time

        now = _time.monotonic()
        if self._miss_until and now < self._miss_until:
            return False

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
        self._miss_until = now + self.MISS_TTL_SEC
        return False

    async def list_models(self) -> list[dict]:
        """프록시에서 제공하는 모델 목록 반환.

        is_available()에서 캐싱된 목록을 사용한다.
        캐시가 없으면 다시 프록시에 질의한다.
        """
        if not self._discovered_models:
            await self.is_available()  # 캐시 없으면 다시 확인
        # 이미지 생성 전용(gpt-image-*)은 대화·비전 호출이 안 되므로 뺀다.
        return [
            {
                "name": m.get("id", "unknown"),
                "vision": True,  # ChatGPT 모델은 대부분 비전 지원
                "cost": "free",
            }
            for m in (self._discovered_models or [])
            if "image" not in str(m.get("id", ""))
        ]

    async def call_with_image(
        self,
        prompt,
        image,
        *,
        image_mime="image/png",
        system=None,
        response_format="text",
        model=None,
        max_tokens=4096,
        **kwargs,
    ) -> LlmResponse:
        """ChatGPT 계정(프록시)으로 이미지 분석 — **Responses API**로 보낸다.

        왜 chat.completions가 아닌가: openai-oauth 프록시는 chat.completions의 data: URL 이미지를
        «URL scheme must be http or https, got data:»(500)로 거부한다. 같은 이미지를
        Responses API의 input_image로 보내면 받는다(2026-09-06 실측). 이 경로가 막혀 있어
        «gpt는 OAuth로» 쓰는 사용자는 LLM OCR이 전부 실패했다.
        """
        import base64 as _b64
        import time as _time

        client = self._create_client()
        selected_model = model or self.DEFAULT_MODEL
        data_uri = f"data:{image_mime};base64,{_b64.b64encode(image).decode('ascii')}"

        think, thinking_budget = thinking_options(kwargs)
        req = {
            "model": selected_model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_image", "image_url": data_uri},
                        {"type": "input_text", "text": prompt},
                    ],
                }
            ],
            "max_output_tokens": max_tokens + thinking_budget,
        }
        if system:
            req["instructions"] = system
        if response_format == "json":
            req["text"] = {"format": {"type": "json_object"}}
        if self._is_reasoning_model(selected_model):
            req["reasoning"] = {"effort": "medium" if think else "low"}

        t0 = _time.monotonic()
        try:
            response = await client.responses.create(**req)
        except Exception as e:
            msg = str(e)
            # 이 프록시 판이 모르는 인자는 빼고 한 번 더 — 형식 강제·추론 옵션은 없어도 돈다.
            # 단, «인자를 거부한» 오류(400)일 때만이다. 로그인 만료(401)·한도(429)·연결 실패에
            # 같은 요청을 되풀이하면 한도만 축나고 결과는 같다(Codex 지적 2026-09-06).
            if ("text" in req or "reasoning" in req) and self._is_param_rejection(e):
                req.pop("text", None)
                req.pop("reasoning", None)
                try:
                    response = await client.responses.create(**req)
                except Exception as e2:  # noqa: BLE001
                    raise LlmProviderError(
                        f"OpenAI(OAuth) vision 호출 실패: {str(e2)[:200]}"
                    ) from e2
            else:
                raise LlmProviderError(f"OpenAI(OAuth) vision 호출 실패: {msg[:200]}") from e
        elapsed = _time.monotonic() - t0

        text = (getattr(response, "output_text", None) or "").strip()
        status = str(getattr(response, "status", "") or "")
        incomplete = getattr(response, "incomplete_details", None)
        reason = str(getattr(incomplete, "reason", "") or "") if incomplete else ""
        if response_format == "json" and (status == "incomplete" or reason == "max_output_tokens"):
            raise LlmProviderError(
                f"OpenAI(OAuth) vision JSON output {TRUNCATED_MARK} (reason={reason or status}, "
                f"max_tokens={max_tokens}, thinking_budget={thinking_budget})"
            )
        if response_format == "json" and not text:
            raise LlmProviderError(f"OpenAI(OAuth) vision empty JSON output (status={status})")
        usage = getattr(response, "usage", None)
        tokens_in = getattr(usage, "input_tokens", None) if usage else None
        tokens_out = getattr(usage, "output_tokens", None) if usage else None
        return LlmResponse(
            text=text,
            provider=self.provider_id,
            model=getattr(response, "model", None) or selected_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=0.0,  # 구독 한도 — 금액은 0이지만 한도를 쓴다
            elapsed_sec=round(elapsed, 2),
            raw={"id": getattr(response, "id", None), "status": status},
        )

    @staticmethod
    def _is_param_rejection(exc: Exception) -> bool:
        """프록시가 «모르는 인자»라고 거부한 오류인가 — 그때만 인자를 빼고 다시 부른다.

        입력: 예외. 출력: 400 계열이거나 문구가 인자 거부를 말하면 True.
        401(로그인)·403·429(한도)·5xx·연결 오류는 False — 다시 보내도 같다.
        """
        status = getattr(exc, "status_code", None)
        if status in (401, 403, 429) or (isinstance(status, int) and status >= 500):
            return False
        if status == 400:
            return True
        msg = str(exc).lower()
        marks = (
            "unknown parameter", "unsupported", "unrecognized", "invalid_request", "not supported",
        )
        return any(k in msg for k in marks)

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
