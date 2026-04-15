"""Ollama Provider (1순위).

Ollama 로컬 서버(localhost:11434)를 통한 LLM 호출.
기본 로컬 모델: gemma4:e4b (Google Gemma 4, 멀티모달)

호출 흐름:
    Python → HTTP POST localhost:11434/api/generate
          → Ollama → 로컬 모델 실행
          → 결과 반환
"""

import base64
import time

import httpx

from .base import BaseLlmProvider, LlmProviderError, LlmResponse


class OllamaProvider(BaseLlmProvider):
    """Ollama 로컬 서버를 통한 LLM 호출. 기본 모델: gemma4:e4b."""

    provider_id = "ollama"
    display_name = "Ollama"
    supports_image = True

    # 용도별 기본 모델
    # 일반 텍스트/비전: gemma4:e4b (로컬, 멀티모달)
    # JSON 구조화 출력(표점/주석): 소형 로컬 모델은 품질이 떨어지므로
    #   클라우드 프록시 모델을 우선 사용한다.
    #   클라우드 프록시가 없으면 gemma4:e4b로 폴백.
    #
    # 왜 표점/주석은 별도 모델인가:
    #   표점(구두점)은 고전 한문의 문맥을 이해해야 정확하고,
    #   JSON 배열 형식으로 출력해야 한다. gemma4:e4b(소형)로는
    #   구두점 위치 정확도와 JSON 구조 준수율이 크게 떨어진다.
    DEFAULT_MODELS = {
        "text": "gemma4:e4b",
        "vision": "gemma4:e4b",
        "translation": "gemma4:e4b",
        "json": "gemma4:e4b",
        "punctuation": "gemma4:e4b",
        "annotation": "gemma4:e4b",
    }

    # JSON 구조화 출력에 소형 모델이 부적합한 용도 목록.
    # 이 용도들은 LLM Router의 자동 폴백에서 Ollama를 건너뛰고
    # 다음 프로바이더(Gemini 등)로 넘어가도록 한다.
    SKIP_FOR_PURPOSES = {"punctuation", "annotation"}

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
        """설치된 모델 목록 조회. GUI 드롭다운에서 사용.

        비전 지원 판별:
            Ollama /api/show 의 capabilities 배열에 "vision"이 있으면 비전 모델.
            이전에는 모델 이름의 키워드("vl", "vision", "llava")로 판별했으나,
            gemma4 등 이름에 키워드가 없는 멀티모달 모델을 놓치는 문제가 있었다.
            /api/show는 GGUF 메타데이터에서 vision.block_count를 확인하므로
            모델 이름과 무관하게 정확히 판별한다.
        """
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{self._url}/api/tags")
            data = resp.json()

        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            has_vision = await self._check_vision_capability(name)
            models.append({
                "name": name,
                "size": m.get("size", "N/A"),
                "vision": has_vision,
            })
        return models

    async def _check_vision_capability(self, model_name: str) -> bool:
        """개별 모델의 비전 지원 여부를 /api/show로 확인한다.

        왜 /api/show를 쓰는가:
            /api/tags는 모델 목록만 반환하고 capability 정보가 없다.
            /api/show는 capabilities 배열(["completion","vision"] 등)을 반환하며,
            이 배열에 "vision"이 있으면 비전 프로젝터가 로드된 모델이다.
            capabilities가 없는 구버전 Ollama에서는 모델 이름 키워드로 폴백한다.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self._url}/api/show",
                    json={"name": model_name},
                )
                if resp.status_code != 200:
                    # 실패 시 이름 기반 폴백
                    return self._name_based_vision_check(model_name)
                info = resp.json()

            # 1순위: capabilities 배열 (Ollama PR #10066 이후)
            caps = info.get("capabilities", [])
            if caps:
                return "vision" in caps

            # 2순위: details.families에 clip 계열이 있으면 비전
            families = info.get("details", {}).get("families", [])
            if any(f in ("clip", "mllama") for f in families):
                return True

            # 3순위: model_info에 vision.* 키가 있으면 비전
            model_info = info.get("model_info", {})
            if any(k.startswith("vision.") for k in model_info):
                return True

            # 최후 폴백: 이름 키워드 (구버전 Ollama 호환)
            return self._name_based_vision_check(model_name)

        except (httpx.ConnectError, httpx.TimeoutException, Exception):
            return self._name_based_vision_check(model_name)

    @staticmethod
    def _name_based_vision_check(model_name: str) -> bool:
        """모델 이름으로 비전 지원을 추정한다 (폴백용).

        /api/show를 사용할 수 없을 때만 호출된다.
        gemma4 등 이름에 키워드가 없는 모델은 놓칠 수 있으므로,
        가능한 한 /api/show 경로를 우선 사용해야 한다.
        """
        name_lower = model_name.lower()
        return any(
            kw in name_lower
            for kw in ["vl", "vision", "llava", "gemma4", "pixtral"]
        )

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
        # 클라우드 프록시 모델(gemini-3-flash-preview:cloud 등)은
        # 네트워크 지연이 추가되므로 타임아웃을 넉넉히 300초로 설정.
        async with httpx.AsyncClient(timeout=300.0) as client:
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

    async def call_stream(
        self, prompt, *, system=None, response_format="text",
        model=None, max_tokens=4096, purpose="text",
        progress_callback=None, **kwargs,
    ) -> LlmResponse:
        """Ollama 네이티브 스트리밍. NDJSON 청크를 읽으며 progress_callback 호출.

        왜 네이티브 스트리밍을 사용하는가:
            기본 heartbeat(2초 간격)보다 훨씬 세밀한 진행 표시가 가능하다.
            토큰이 생성될 때마다 경과 시간과 토큰 수를 실시간으로 전달한다.
            Ollama의 stream 모드는 NDJSON(줄 구분 JSON)으로 응답하며,
            각 줄은 {"response":"토큰","done":false} 형식이다.
        """
        import json as _json

        selected_model = (
            model
            or self.DEFAULT_MODELS.get(purpose, self.DEFAULT_MODELS["text"])
        )

        payload = {
            "model": selected_model,
            "prompt": prompt,
            "stream": True,
            "options": {"num_predict": max_tokens},
        }
        if system:
            payload["system"] = system
        if response_format == "json":
            payload["format"] = "json"

        t0 = time.monotonic()
        full_text = ""
        tokens_out = 0
        tokens_in = None
        last_report = t0

        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST", f"{self._url}/api/generate", json=payload
            ) as resp:
                if resp.status_code != 200:
                    raise LlmProviderError(
                        f"Ollama 스트리밍 응답 {resp.status_code}"
                    )

                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = _json.loads(line)
                    except _json.JSONDecodeError:
                        continue

                    if chunk.get("error"):
                        raise LlmProviderError(f"Ollama 에러: {chunk['error']}")

                    token = chunk.get("response", "")
                    full_text += token
                    tokens_out += 1

                    # 1초마다 progress 콜백
                    now = time.monotonic()
                    if progress_callback and (now - last_report) >= 1.0:
                        last_report = now
                        progress_callback({
                            "type": "progress",
                            "elapsed_sec": round(now - t0, 1),
                            "tokens": tokens_out,
                            "provider": self.provider_id,
                        })

                    if chunk.get("done"):
                        tokens_in = chunk.get("prompt_eval_count")
                        tokens_out = chunk.get("eval_count", tokens_out)
                        break

        elapsed = time.monotonic() - t0

        return LlmResponse(
            text=full_text,
            provider=self.provider_id,
            model=selected_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=0.0,
            elapsed_sec=round(elapsed, 2),
            raw={"stream": True},
        )

    async def call_with_image(self, prompt, image, *, image_mime="image/png",
                              system=None, response_format="text", model=None,
                              max_tokens=4096, **kwargs) -> LlmResponse:
        """Ollama 비전 모델로 이미지 분석.

        gemma4:e4b가 기본 비전 모델 (멀티모달).
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
