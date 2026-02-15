"""Base44 HTTP Provider (1순위).

agent-chat 서버(localhost:8787)를 통한 Base44 InvokeLLM 호출.

장점: 무료, MCP 도구 연동, 세션 관리.

호출 흐름:
    Python → HTTP POST localhost:8787/api/chat
          → agent-chat → Base44 InvokeLLM
          → 결과 JSON 반환
"""

import base64
import time

import httpx

from .base import BaseLlmProvider, LlmProviderError, LlmResponse


class Base44HttpProvider(BaseLlmProvider):
    """agent-chat 서버(localhost:8787)를 통한 Base44 InvokeLLM 호출."""

    provider_id = "base44_http"
    display_name = "Base44 (agent-chat)"
    supports_image = True

    @property
    def _url(self) -> str:
        return self.config.get("agent_chat_url", "http://127.0.0.1:8787")

    async def is_available(self) -> bool:
        """GET /api/meta로 헬스체크. timeout 2초."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self._url}/api/meta")
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            return False

    async def call(self, prompt, *, system=None, response_format="text",
                   model=None, max_tokens=4096, purpose="text",
                   connector="sequential-thinking", **kwargs) -> LlmResponse:
        """agent-chat에 텍스트 요청.

        connector: 사용할 커넥터 (기본: sequential-thinking)
        """
        full_prompt = prompt
        if system:
            full_prompt = f"[시스템 지시]\n{system}\n\n[요청]\n{prompt}"
        if response_format == "json":
            full_prompt += "\n\n반드시 JSON으로만 응답하라. 마크다운 코드블록 없이 순수 JSON만."

        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._url}/api/chat",
                json={"text": full_prompt, "connector": connector},
            )
            if resp.status_code != 200:
                raise LlmProviderError(
                    f"agent-chat 응답 {resp.status_code}: {resp.text[:200]}"
                )
            data = resp.json()
        elapsed = time.monotonic() - t0

        content = data.get("content", "")
        if not content and data.get("error"):
            raise LlmProviderError(f"agent-chat 에러: {data['error']}")

        return LlmResponse(
            text=content,
            provider=self.provider_id,
            model="base44_invokellm",
            cost_usd=0.0,
            elapsed_sec=round(elapsed, 2),
            raw=data,
        )

    async def call_with_image(self, prompt, image, *, image_mime="image/png",
                              system=None, response_format="text", model=None,
                              max_tokens=4096, **kwargs) -> LlmResponse:
        """agent-chat에 이미지 첨부 요청.

        attachments에 base64 인코딩한 이미지를 전송.
        """
        full_prompt = prompt
        if system:
            full_prompt = f"[시스템 지시]\n{system}\n\n[요청]\n{prompt}"

        attachment = {
            "name": "page_image.png",
            "type": image_mime,
            "data": base64.b64encode(image).decode("ascii"),
        }

        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{self._url}/api/chat",
                json={
                    "text": full_prompt,
                    "connector": "sequential-thinking",
                    "attachments": [attachment],
                },
            )
            if resp.status_code != 200:
                raise LlmProviderError(
                    f"agent-chat 응답 {resp.status_code}"
                )
            data = resp.json()
        elapsed = time.monotonic() - t0

        content = data.get("content", "")
        if not content and data.get("error"):
            raise LlmProviderError(f"agent-chat vision 에러: {data['error']}")

        return LlmResponse(
            text=content,
            provider=self.provider_id,
            model="base44_invokellm_vision",
            cost_usd=0.0,
            elapsed_sec=round(elapsed, 2),
            raw=data,
        )
