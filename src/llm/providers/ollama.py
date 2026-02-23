"""Ollama Provider (3순위).

Ollama 로컬 서버(localhost:11434)를 통한 LLM 호출.
클라우드 모델도 Ollama가 프록시:
    - qwen3-vl:235b-cloud    ← 이미지 분석 가능 (비전 모델)
    - kimi-k2.5:cloud
    - minimax-m2.5:cloud
    - glm-5:cloud
    - gemini-3-flash-preview:cloud

호출 흐름:
    Python → HTTP POST localhost:11434/api/generate
          → Ollama → 클라우드 모델 프록시
          → 결과 반환
"""

import base64
import time

import httpx

from .base import BaseLlmProvider, LlmProviderError, LlmResponse


class OllamaProvider(BaseLlmProvider):
    """Ollama 로컬 서버를 통한 LLM 호출. 클라우드 모델도 프록시."""

    provider_id = "ollama"
    display_name = "Ollama"
    supports_image = True

    # 용도별 기본 모델
    # 주의: kimi-k2.5는 thinking 모델이라 사고 토큰이 num_predict 예산을
    # 소진하여 빈 응답을 반환할 수 있다.
    # JSON 구조화 출력이 필요한 용도(표점, 주석)는 non-thinking 모델을 사용한다.
    DEFAULT_MODELS = {
        "text": "kimi-k2.5:cloud",
        "vision": "qwen3-vl:235b-cloud",
        "translation": "glm-5:cloud",
        "json": "gemini-3-flash-preview:cloud",
        "punctuation": "gemini-3-flash-preview:cloud",   # JSON 출력 — non-thinking 모델
        "annotation": "gemini-3-flash-preview:cloud",     # JSON 출력 — non-thinking 모델
    }

    @property
    def _url(self) -> str:
        return self.config.get("ollama_url", "http://localhost:11434")

    async def is_available(self) -> bool:
        """Ollama 서버가 실행 중인지 확인."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self._url}/api/tags")
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            return False

    async def list_models(self) -> list[dict]:
        """설치된 모델 목록 조회. GUI 드롭다운에서 사용."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{self._url}/api/tags")
            data = resp.json()

        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            models.append({
                "name": name,
                "size": m.get("size", "N/A"),
                "vision": any(
                    kw in name.lower() for kw in ["vl", "vision", "llava"]
                ),
            })
        return models

    async def call(self, prompt, *, system=None, response_format="text",
                   model=None, max_tokens=4096, purpose="text",
                   **kwargs) -> LlmResponse:
        """Ollama API로 텍스트 생성.

        purpose: 용도 힌트 ("text", "translation", "json")
                 → 용도별 기본 모델 자동 선택
        """
        selected_model = (
            model
            or self.DEFAULT_MODELS.get(purpose, self.DEFAULT_MODELS["text"])
        )

        payload = {
            "model": selected_model,
            "prompt": prompt,
            "stream": False,
            # num_predict: Ollama의 최대 출력 토큰 설정.
            # 이 값이 없으면 모델 기본값(128~256)이 적용되어
            # 표점·주석 등 긴 JSON 응답이 중간에 잘린다.
            "options": {"num_predict": max_tokens},
        }
        if system:
            payload["system"] = system
        if response_format == "json":
            payload["format"] = "json"

        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{self._url}/api/generate", json=payload
            )
            if resp.status_code != 200:
                raise LlmProviderError(
                    f"Ollama 응답 {resp.status_code}: {resp.text[:200]}"
                )
            data = resp.json()
        elapsed = time.monotonic() - t0

        if data.get("error"):
            raise LlmProviderError(f"Ollama 에러: {data['error']}")

        return LlmResponse(
            text=data.get("response", ""),
            provider=self.provider_id,
            model=selected_model,
            tokens_in=data.get("prompt_eval_count"),
            tokens_out=data.get("eval_count"),
            cost_usd=0.0,
            elapsed_sec=round(elapsed, 2),
            raw=data,
        )

    async def call_with_image(self, prompt, image, *, image_mime="image/png",
                              system=None, response_format="text", model=None,
                              max_tokens=4096, **kwargs) -> LlmResponse:
        """Ollama 비전 모델로 이미지 분석.

        qwen3-vl:235b-cloud가 기본 비전 모델.
        Ollama API는 images 필드에 base64 배열을 받는다.
        """
        selected_model = model or self.DEFAULT_MODELS["vision"]

        payload = {
            "model": selected_model,
            "prompt": prompt,
            "images": [base64.b64encode(image).decode("ascii")],
            "stream": False,
        }
        if system:
            payload["system"] = system

        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{self._url}/api/generate", json=payload
            )
            if resp.status_code != 200:
                raise LlmProviderError(
                    f"Ollama vision 응답 {resp.status_code}"
                )
            data = resp.json()
        elapsed = time.monotonic() - t0

        return LlmResponse(
            text=data.get("response", ""),
            provider=self.provider_id,
            model=selected_model,
            tokens_in=data.get("prompt_eval_count"),
            tokens_out=data.get("eval_count"),
            cost_usd=0.0,
            elapsed_sec=round(elapsed, 2),
            raw=data,
        )
