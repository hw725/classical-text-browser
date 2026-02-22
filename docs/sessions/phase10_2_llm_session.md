# Phase 10-2: LLM 4단 폴백 아키텍처 + 레이아웃 분석

> Claude Code 세션 지시문
> 이 문서를 읽고 작업 순서대로 구현하라.

---

## 사전 준비

1. CLAUDE.md를 먼저 읽어라.
2. docs/phase10_12_design.md의 Phase 10-2 섹션을 읽어라.
3. 이 문서 전체를 읽은 후 작업을 시작하라.
4. 기존 코드 구조를 먼저 파악하라: `src/` 디렉토리 전체, `src/core/`, `src/api/`, `static/js/`.

---

## 설계 요약 — 반드시 이해한 후 구현

### 핵심 원칙

- **모든 LLM 호출은 `src/llm/router.py`를 통해야 한다.** provider를 직접 호출하지 않는다.
- **4단 폴백**: Base44 HTTP → Base44 Bridge → Ollama → 직접 API. 순서대로 시도하여 첫 성공 반환.
- **force_provider, force_model**: 폴백을 우회하여 특정 모델을 지정할 수 있다. 품질 테스트용.
- **compare()**: 같은 입력을 여러 모델에 병렬 전송. 결과를 나란히 비교. 채택 후 Draft로 전환.
- **Draft → Review → Commit**: LLM 결과는 항상 Draft 상태로 생성. 사람이 검토 후 확정.

### 호출 우선순위

```
1순위: Base44 InvokeLLM via agent-chat HTTP
       - URL: http://127.0.0.1:8787/api/chat
       - 헬스체크: GET http://127.0.0.1:8787/api/meta
       - 요청 형식: POST {"text": "...", "connector": "sequential-thinking"}
       - 이미지: attachments 필드에 base64 인코딩
       - 비용: 무료

2순위: Base44 InvokeLLM via Node.js bridge
       - 실행: node src/llm/bridge/invoke.js  (stdin → stdout JSON)
       - 전제: Node.js 20+, backend-44 경로 설정, base44 login 완료
       - SDK: backend-44/src/client.js의 getBase44Client() 사용
       - 비전: node src/llm/bridge/invoke_vision.js (UploadFile → InvokeLLM)
       - 비용: 무료

3순위: Ollama (로컬 서버)
       - URL: http://localhost:11434
       - 텍스트: POST /api/generate {"model": "...", "prompt": "...", "stream": false}
       - 이미지: POST /api/generate {"model": "...", "prompt": "...", "images": ["base64..."], "stream": false}
       - 모델 목록: GET /api/tags
       - 용도별 기본 모델:
           text:        kimi-k2.5:cloud
           vision:      qwen3-vl:235b-cloud
           translation: glm-5:cloud
           json:        gemini-3-flash-preview:cloud
       - 비용: 무료 (클라우드 모델은 Ollama가 프록시)

4순위: 직접 API (Anthropic / OpenAI / Gemini)
       - Anthropic: anthropic Python SDK, 모델 claude-sonnet-4-20250514
       - OpenAI: openai Python SDK
       - Gemini: google-generativeai Python SDK
       - 비용: 유료
```

### 디렉토리 구조 (최종)

```
src/llm/
  __init__.py               ← from .router import LlmRouter 노출
  router.py                 ← 단일 진입점
  config.py                 ← 설정 관리
  usage_tracker.py          ← 비용/사용량 추적
  draft.py                  ← LlmDraft 모델
  providers/
    __init__.py
    base.py                 ← BaseLlmProvider, LlmResponse
    base44_http.py          ← 1순위
    base44_bridge.py        ← 2순위
    ollama.py               ← 3순위
    anthropic.py            ← 4순위
    openai_provider.py      ← 4순위 (openai.py는 패키지명과 충돌 가능)
    gemini.py               ← 4순위
  bridge/
    invoke.js               ← Node.js 텍스트 브릿지
    invoke_vision.js        ← Node.js 이미지 브릿지
  prompts/
    layout_analysis.yaml    ← 레이아웃 분석 프롬프트
```

---

## 작업 순서

아래 작업을 번호 순서대로 구현하라. 각 작업이 끝나면 테스트를 실행하고 통과 확인 후 다음으로 넘어가라.

---

### 작업 1: 의존성 설치 + 디렉토리 생성

```bash
uv add httpx pyyaml
# anthropic, openai, google-generativeai는 4순위 provider 구현 시 설치
```

디렉토리를 생성하라:

```
src/llm/__init__.py
src/llm/providers/__init__.py
src/llm/bridge/          (빈 디렉토리)
src/llm/prompts/         (빈 디렉토리)
```

`src/llm/__init__.py` 내용:

```python
"""LLM 호출 모듈.

모든 LLM 호출은 LlmRouter를 통해야 한다.
provider를 직접 import하지 마라.

사용법:
    from src.llm import LlmRouter
    router = LlmRouter(config)
    response = await router.call("프롬프트")
"""
```

아직 LlmRouter import는 넣지 마라. 작업 6에서 router.py를 만든 후 추가.

커밋: `feat(llm): Phase 10-2 시작 — 디렉토리 구조 + 의존성`

---

### 작업 2: BaseLlmProvider 추상 클래스 + LlmResponse

파일: `src/llm/providers/base.py`

구현할 것:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class LlmResponse:
    """모든 provider가 반환하는 통합 응답 모델."""
    text: str
    provider: str                     # "base44_http", "ollama", "anthropic" 등
    model: str                        # 실제 사용된 모델명
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    cost_usd: Optional[float] = None  # 무료면 0.0
    elapsed_sec: Optional[float] = None  # 응답 시간 (비교용)
    raw: Optional[dict] = None        # provider별 원본 응답 (디버깅)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class LlmProviderError(Exception):
    """개별 provider 호출 실패."""
    pass


class LlmUnavailableError(Exception):
    """모든 provider가 사용 불가."""
    pass


class BaseLlmProvider(ABC):
    """LLM provider 추상 클래스."""

    provider_id: str = ""
    display_name: str = ""
    supports_image: bool = False

    def __init__(self, config):
        self.config = config

    @abstractmethod
    async def is_available(self) -> bool: ...

    @abstractmethod
    async def call(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        response_format: str = "text",   # "text" | "json"
        model: Optional[str] = None,
        max_tokens: int = 4096,
        purpose: str = "text",
        **kwargs,
    ) -> LlmResponse: ...

    @abstractmethod
    async def call_with_image(
        self,
        prompt: str,
        image: bytes,
        *,
        image_mime: str = "image/png",
        system: Optional[str] = None,
        response_format: str = "text",
        model: Optional[str] = None,
        max_tokens: int = 4096,
        **kwargs,
    ) -> LlmResponse: ...
```

`src/llm/providers/__init__.py`:

```python
from .base import BaseLlmProvider, LlmResponse, LlmProviderError, LlmUnavailableError
```

테스트: `src/llm/providers/base.py`가 import 가능한지 확인.

```python
# tests/test_llm_base.py
from src.llm.providers.base import BaseLlmProvider, LlmResponse, LlmProviderError, LlmUnavailableError

def test_llm_response_creation():
    r = LlmResponse(text="hello", provider="test", model="test-model")
    assert r.text == "hello"
    assert r.cost_usd is None
    assert r.timestamp  # 자동 생성됨

def test_base_provider_is_abstract():
    import pytest
    with pytest.raises(TypeError):
        BaseLlmProvider(config={})  # 추상 클래스 직접 생성 불가
```

커밋: `feat(llm): BaseLlmProvider 추상 클래스 + LlmResponse 모델`

---

### 작업 3: Base44 HTTP Provider (1순위)

파일: `src/llm/providers/base44_http.py`

구현할 것:

```python
import httpx
import base64
import time
from .base import BaseLlmProvider, LlmResponse, LlmProviderError


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
        """agent-chat에 텍스트 요청."""
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
                raise LlmProviderError(f"agent-chat 응답 {resp.status_code}: {resp.text[:200]}")
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
        """agent-chat에 이미지 첨부 요청."""
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
                raise LlmProviderError(f"agent-chat 응답 {resp.status_code}")
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
```

테스트: is_available()이 서버가 꺼져있을 때 False를 반환하는지 확인.

```python
# tests/test_llm_base44_http.py
import pytest
from src.llm.providers.base44_http import Base44HttpProvider

@pytest.mark.asyncio
async def test_base44_http_unavailable_when_server_down():
    """agent-chat 서버가 안 떠있으면 is_available() → False."""
    provider = Base44HttpProvider(config={"agent_chat_url": "http://127.0.0.1:19999"})
    assert await provider.is_available() is False
```

커밋: `feat(llm): Base44 HTTP provider (1순위 — agent-chat 연동)`

---

### 작업 4: Base44 Bridge Provider (2순위)

#### 4-A: Node.js 브릿지 스크립트

파일: `src/llm/bridge/invoke.js`

```javascript
/**
 * Base44 InvokeLLM 브릿지 — 텍스트 전용.
 *
 * Python에서 subprocess로 실행. stdin JSON → stdout JSON.
 * 사용: echo '{"prompt":"..."}' | node invoke.js
 *
 * 전제:
 *   - 환경변수 BACKEND44_PATH에 backend-44 경로 설정
 *   - 또는 이 파일 기준 상대 경로로 backend-44 탐색
 *   - base44 login 완료 (~/.base44/auth/auth.json 존재)
 */

import { readFileSync, existsSync } from 'fs';
import { resolve, dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// backend-44 경로 탐색
function findBackend44Root() {
  // 1. 환경변수
  if (process.env.BACKEND44_PATH) {
    const p = resolve(process.env.BACKEND44_PATH);
    if (existsSync(join(p, 'src', 'client.js'))) return p;
  }
  // 2. 프로젝트 루트 기준 상대 경로 탐색 (여러 후보)
  const candidates = [
    resolve(__dirname, '..', '..', '..', '..', 'backend-44'),
    resolve(__dirname, '..', '..', '..', '..', 'head-repo', 'hw725', 'backend-44'),
  ];
  for (const c of candidates) {
    if (existsSync(join(c, 'src', 'client.js'))) return c;
  }
  return null;
}

async function main() {
  const backend44Root = findBackend44Root();
  if (!backend44Root) {
    throw new Error(
      'backend-44를 찾을 수 없습니다.\n' +
      'BACKEND44_PATH 환경변수를 설정하세요.'
    );
  }

  // 동적 import (경로가 런타임에 결정되므로)
  const clientPath = join(backend44Root, 'src', 'client.js');
  const { getBase44Client, ensureAuth } = await import(clientPath);

  // stdin 읽기
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  const { prompt, system, response_type } = input;

  ensureAuth();
  const base44 = getBase44Client();

  const fullPrompt = system
    ? `[시스템 지시]\n${system}\n\n[요청]\n${prompt}`
    : prompt;

  const result = await base44.integrations.Core.InvokeLLM({
    prompt: fullPrompt,
    response_type: response_type || 'text',
  });

  const text = typeof result === 'string'
    ? result
    : (result?.content || JSON.stringify(result));

  process.stdout.write(JSON.stringify({ text, provider: 'base44_bridge', raw: result }));
}

main().catch(e => {
  process.stderr.write(JSON.stringify({ error: e.message || String(e) }));
  process.exit(1);
});
```

파일: `src/llm/bridge/invoke_vision.js`

```javascript
/**
 * Base44 InvokeLLM 브릿지 — 이미지 분석용.
 *
 * stdin: {"prompt": "...", "image_path": "/tmp/xxx.png", "image_mime": "image/png"}
 * stdout: {"text": "...", "provider": "base44_bridge"}
 */

import { readFileSync, existsSync } from 'fs';
import { resolve, dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

function findBackend44Root() {
  if (process.env.BACKEND44_PATH) {
    const p = resolve(process.env.BACKEND44_PATH);
    if (existsSync(join(p, 'src', 'client.js'))) return p;
  }
  const candidates = [
    resolve(__dirname, '..', '..', '..', '..', 'backend-44'),
    resolve(__dirname, '..', '..', '..', '..', 'head-repo', 'hw725', 'backend-44'),
  ];
  for (const c of candidates) {
    if (existsSync(join(c, 'src', 'client.js'))) return c;
  }
  return null;
}

async function main() {
  const backend44Root = findBackend44Root();
  if (!backend44Root) {
    throw new Error('backend-44를 찾을 수 없습니다.');
  }

  const clientPath = join(backend44Root, 'src', 'client.js');
  const { getBase44Client, ensureAuth } = await import(clientPath);

  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  const { prompt, image_path, image_mime } = input;

  if (!existsSync(image_path)) {
    throw new Error(`이미지 파일 없음: ${image_path}`);
  }

  ensureAuth();
  const base44 = getBase44Client();

  // 이미지 업로드
  const imageBuffer = readFileSync(image_path);
  const fileName = image_path.split(/[\\/]/).pop();

  let fileObj;
  if (typeof globalThis.File === 'function') {
    fileObj = new globalThis.File([imageBuffer], fileName, {
      type: image_mime || 'image/png',
    });
  } else {
    fileObj = new globalThis.Blob([imageBuffer], {
      type: image_mime || 'image/png',
    });
    fileObj.name = fileName;
  }

  const uploadResult = await base44.integrations.Core.UploadFile({ file: fileObj });
  if (!uploadResult?.file_url) {
    throw new Error('파일 업로드 실패: file_url 없음');
  }

  const result = await base44.integrations.Core.InvokeLLM({
    prompt,
    file_urls: [uploadResult.file_url],
  });

  const text = typeof result === 'string'
    ? result
    : (result?.content || JSON.stringify(result));

  process.stdout.write(JSON.stringify({
    text,
    provider: 'base44_bridge',
    file_url: uploadResult.file_url,
    raw: result,
  }));
}

main().catch(e => {
  process.stderr.write(JSON.stringify({ error: e.message || String(e) }));
  process.exit(1);
});
```

#### 4-B: Python Provider

파일: `src/llm/providers/base44_bridge.py`

```python
import asyncio
import json
import tempfile
import time
from pathlib import Path
from .base import BaseLlmProvider, LlmResponse, LlmProviderError


class Base44BridgeProvider(BaseLlmProvider):
    """Node.js 브릿지를 subprocess로 실행하여 Base44 SDK 호출."""

    provider_id = "base44_bridge"
    display_name = "Base44 (bridge)"
    supports_image = True

    @property
    def _bridge_dir(self) -> Path:
        """bridge 스크립트가 있는 디렉토리."""
        return Path(__file__).parent.parent / "bridge"

    @property
    def _invoke_script(self) -> Path:
        return self._bridge_dir / "invoke.js"

    @property
    def _vision_script(self) -> Path:
        return self._bridge_dir / "invoke_vision.js"

    async def is_available(self) -> bool:
        """Node.js + bridge 스크립트 + Base44 인증 토큰 확인."""
        # 1. Node.js 설치 확인
        try:
            proc = await asyncio.create_subprocess_exec(
                "node", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.wait(), timeout=5.0)
            if proc.returncode != 0:
                return False
        except (FileNotFoundError, asyncio.TimeoutError):
            return False

        # 2. bridge 스크립트 존재
        if not self._invoke_script.exists():
            return False

        # 3. Base44 인증 토큰
        auth_path = Path.home() / ".base44" / "auth" / "auth.json"
        if not auth_path.exists():
            # .env의 BASE44_TOKEN도 확인
            if not self.config.get_api_key("base44"):
                return False

        return True

    async def _run_bridge(self, script: Path, input_data: dict,
                          timeout: float = 120.0) -> dict:
        """Node.js 스크립트를 실행하고 결과를 반환."""
        env_vars = {}
        backend_path = self.config.get("base44_backend_path")
        if backend_path:
            env_vars["BACKEND44_PATH"] = str(backend_path)

        import os
        full_env = {**os.environ, **env_vars}

        proc = await asyncio.create_subprocess_exec(
            "node", str(script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=full_env,
        )

        input_bytes = json.dumps(input_data).encode("utf-8")

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input_bytes),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise LlmProviderError(f"Base44 bridge 타임아웃 ({timeout}초)")

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace")
            try:
                err_data = json.loads(err_msg)
                err_msg = err_data.get("error", err_msg)
            except (json.JSONDecodeError, KeyError):
                pass
            raise LlmProviderError(f"Base44 bridge 실패: {err_msg}")

        return json.loads(stdout.decode("utf-8"))

    async def call(self, prompt, *, system=None, response_format="text",
                   model=None, max_tokens=4096, purpose="text",
                   **kwargs) -> LlmResponse:
        t0 = time.monotonic()
        data = await self._run_bridge(self._invoke_script, {
            "prompt": prompt,
            "system": system,
            "response_type": "json" if response_format == "json" else "text",
        })
        elapsed = time.monotonic() - t0

        return LlmResponse(
            text=data.get("text", ""),
            provider=self.provider_id,
            model="base44_invokellm",
            cost_usd=0.0,
            elapsed_sec=round(elapsed, 2),
            raw=data.get("raw"),
        )

    async def call_with_image(self, prompt, image, *, image_mime="image/png",
                              system=None, response_format="text", model=None,
                              max_tokens=4096, **kwargs) -> LlmResponse:
        # 이미지를 임시 파일로 저장
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(image)
            tmp_path = tmp.name

        try:
            t0 = time.monotonic()
            data = await self._run_bridge(self._vision_script, {
                "prompt": prompt if not system else f"[시스템 지시]\n{system}\n\n[요청]\n{prompt}",
                "image_path": tmp_path,
                "image_mime": image_mime,
            }, timeout=180.0)
            elapsed = time.monotonic() - t0

            return LlmResponse(
                text=data.get("text", ""),
                provider=self.provider_id,
                model="base44_invokellm_vision",
                cost_usd=0.0,
                elapsed_sec=round(elapsed, 2),
                raw=data.get("raw"),
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
```

테스트:

```python
# tests/test_llm_bridge.py
import pytest
from src.llm.providers.base44_bridge import Base44BridgeProvider

@pytest.mark.asyncio
async def test_bridge_unavailable_without_node(monkeypatch):
    """Node.js가 없으면 is_available() → False."""
    monkeypatch.setenv("PATH", "")  # node를 못 찾게
    provider = Base44BridgeProvider(config=type("C", (), {"get": lambda s, k, d=None: d, "get_api_key": lambda s, k: None})())
    # 이 테스트는 환경에 따라 다를 수 있으므로 skip 가능
```

커밋: `feat(llm): Base44 bridge provider (2순위 — Node.js subprocess)`

---

### 작업 5: Ollama Provider (3순위)

파일: `src/llm/providers/ollama.py`

```python
import httpx
import base64
import time
from typing import Optional
from .base import BaseLlmProvider, LlmResponse, LlmProviderError


class OllamaProvider(BaseLlmProvider):
    """Ollama 로컬 서버를 통한 LLM 호출. 클라우드 모델도 프록시."""

    provider_id = "ollama"
    display_name = "Ollama"
    supports_image = True

    DEFAULT_MODELS = {
        "text": "kimi-k2.5:cloud",
        "vision": "qwen3-vl:235b-cloud",
        "translation": "glm-5:cloud",
        "json": "gemini-3-flash-preview:cloud",
    }

    @property
    def _url(self) -> str:
        return self.config.get("ollama_url", "http://localhost:11434")

    async def is_available(self) -> bool:
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
                "vision": any(kw in name.lower() for kw in ["vl", "vision", "llava"]),
            })
        return models

    async def call(self, prompt, *, system=None, response_format="text",
                   model=None, max_tokens=4096, purpose="text",
                   **kwargs) -> LlmResponse:
        selected_model = model or self.DEFAULT_MODELS.get(purpose, self.DEFAULT_MODELS["text"])

        payload = {
            "model": selected_model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system
        if response_format == "json":
            payload["format"] = "json"

        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(f"{self._url}/api/generate", json=payload)
            if resp.status_code != 200:
                raise LlmProviderError(f"Ollama 응답 {resp.status_code}: {resp.text[:200]}")
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
            resp = await client.post(f"{self._url}/api/generate", json=payload)
            if resp.status_code != 200:
                raise LlmProviderError(f"Ollama vision 응답 {resp.status_code}")
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
```

테스트:

```python
# tests/test_llm_ollama.py
import pytest
from src.llm.providers.ollama import OllamaProvider

@pytest.mark.asyncio
async def test_ollama_unavailable():
    provider = OllamaProvider(config=type("C", (), {"get": lambda s, k, d=None: "http://127.0.0.1:19998"})())
    assert await provider.is_available() is False

def test_default_models():
    provider = OllamaProvider(config=type("C", (), {"get": lambda s, k, d=None: d})())
    assert provider.DEFAULT_MODELS["vision"] == "qwen3-vl:235b-cloud"
    assert provider.DEFAULT_MODELS["translation"] == "glm-5:cloud"
```

커밋: `feat(llm): Ollama provider (3순위 — 클라우드 모델 프록시)`

---

### 작업 6: Anthropic Provider (4순위)

```bash
uv add anthropic
```

파일: `src/llm/providers/anthropic_provider.py`

(파일명을 `anthropic_provider.py`로 한다. `anthropic.py`는 패키지명과 충돌할 수 있다.)

```python
import time
import base64
from typing import Optional
from .base import BaseLlmProvider, LlmResponse, LlmProviderError


class AnthropicProvider(BaseLlmProvider):
    """Anthropic Claude API 직접 호출. 최후 수단."""

    provider_id = "anthropic"
    display_name = "Claude (Anthropic)"
    supports_image = True
    DEFAULT_MODEL = "claude-sonnet-4-20250514"

    # 대략적 가격 (1K tokens 기준, USD)
    PRICING = {
        "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
    }

    async def is_available(self) -> bool:
        return bool(self.config.get_api_key("anthropic"))

    def _estimate_cost(self, model, tokens_in, tokens_out):
        pricing = self.PRICING.get(model, {"input": 0.003, "output": 0.015})
        cost = (tokens_in or 0) / 1000 * pricing["input"] + \
               (tokens_out or 0) / 1000 * pricing["output"]
        return round(cost, 6)

    async def call(self, prompt, *, system=None, response_format="text",
                   model=None, max_tokens=4096, purpose="text",
                   **kwargs) -> LlmResponse:
        import anthropic

        api_key = self.config.get_api_key("anthropic")
        if not api_key:
            raise LlmProviderError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")

        client = anthropic.AsyncAnthropic(api_key=api_key)
        selected_model = model or self.DEFAULT_MODEL

        messages = [{"role": "user", "content": prompt}]

        t0 = time.monotonic()
        response = await client.messages.create(
            model=selected_model,
            max_tokens=max_tokens,
            system=system or "",
            messages=messages,
        )
        elapsed = time.monotonic() - t0

        text = response.content[0].text if response.content else ""
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens

        return LlmResponse(
            text=text,
            provider=self.provider_id,
            model=response.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=self._estimate_cost(selected_model, tokens_in, tokens_out),
            elapsed_sec=round(elapsed, 2),
            raw={"id": response.id},
        )

    async def call_with_image(self, prompt, image, *, image_mime="image/png",
                              system=None, response_format="text", model=None,
                              max_tokens=4096, **kwargs) -> LlmResponse:
        import anthropic

        api_key = self.config.get_api_key("anthropic")
        if not api_key:
            raise LlmProviderError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")

        client = anthropic.AsyncAnthropic(api_key=api_key)
        selected_model = model or self.DEFAULT_MODEL

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image_mime,
                            "data": base64.b64encode(image).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        t0 = time.monotonic()
        response = await client.messages.create(
            model=selected_model,
            max_tokens=max_tokens,
            system=system or "",
            messages=messages,
        )
        elapsed = time.monotonic() - t0

        text = response.content[0].text if response.content else ""
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens

        return LlmResponse(
            text=text,
            provider=self.provider_id,
            model=response.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=self._estimate_cost(selected_model, tokens_in, tokens_out),
            elapsed_sec=round(elapsed, 2),
            raw={"id": response.id},
        )
```

테스트:

```python
# tests/test_llm_anthropic.py
import pytest
from src.llm.providers.anthropic_provider import AnthropicProvider

@pytest.mark.asyncio
async def test_anthropic_unavailable_without_key():
    config = type("C", (), {"get_api_key": lambda s, k: None, "get": lambda s, k, d=None: d})()
    provider = AnthropicProvider(config=config)
    assert await provider.is_available() is False
```

커밋: `feat(llm): Anthropic provider (4순위 — Claude API)`

---

### 작업 7: Config

파일: `src/llm/config.py`

```python
import os
from pathlib import Path
from typing import Optional


class LlmConfig:
    """LLM 설정 관리.

    설정 우선순위: 환경변수 → .env 파일 → 기본값.
    """

    DEFAULTS = {
        "agent_chat_url": "http://127.0.0.1:8787",
        "ollama_url": "http://localhost:11434",
        "base44_backend_path": None,
        "monthly_budget_usd": 10.0,
    }

    # 환경변수명 매핑
    API_KEY_ENV = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GOOGLE_API_KEY",
        "base44": "BASE44_TOKEN",
    }

    def __init__(self, library_root: Optional[Path] = None):
        self._library_root = library_root
        self._env_cache: dict = {}

        # .env 파일 로드 (있으면)
        if library_root:
            env_file = library_root / ".env"
            if env_file.exists():
                self._env_cache = self._load_dotenv(env_file)

    def _load_dotenv(self, path: Path) -> dict:
        """간단한 .env 파서. python-dotenv 없이 동작."""
        result = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            result[key] = value
        return result

    def get_api_key(self, provider: str) -> Optional[str]:
        """API 키 조회. 환경변수 → .env → None."""
        env_name = self.API_KEY_ENV.get(provider)
        if not env_name:
            return None
        return os.environ.get(env_name) or self._env_cache.get(env_name)

    def get(self, key: str, default=None):
        """설정값 조회. 환경변수(대문자) → .env → DEFAULTS → default."""
        env_key = key.upper()
        val = os.environ.get(env_key) or self._env_cache.get(env_key)
        if val is not None:
            return val
        return self.DEFAULTS.get(key, default)
```

테스트:

```python
# tests/test_llm_config.py
from src.llm.config import LlmConfig

def test_config_defaults():
    config = LlmConfig()
    assert config.get("agent_chat_url") == "http://127.0.0.1:8787"
    assert config.get("ollama_url") == "http://localhost:11434"

def test_config_api_key_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
    config = LlmConfig()
    assert config.get_api_key("anthropic") == "test-key-123"

def test_config_api_key_missing():
    config = LlmConfig()
    # 환경변수도 .env도 없으면 None
    # (이미 환경에 설정되어 있을 수 있으므로 삭제 후 테스트)
    assert config.get_api_key("nonexistent") is None
```

커밋: `feat(llm): LlmConfig — 설정 관리`

---

### 작업 8: Router

파일: `src/llm/router.py`

이것이 핵심이다. 아래 기능을 모두 구현하라:

1. **`call()`** — 자동 폴백 + force_provider/force_model 지원
2. **`call_with_image()`** — 이미지 분석 호출
3. **`compare()`** — 여러 모델 병렬 비교
4. **`get_available_models()`** — GUI 드롭다운용 모델 목록

```python
import asyncio
import time
from typing import Optional

from .config import LlmConfig
from .usage_tracker import UsageTracker
from .providers.base import (
    BaseLlmProvider, LlmResponse, LlmProviderError, LlmUnavailableError
)
from .providers.base44_http import Base44HttpProvider
from .providers.base44_bridge import Base44BridgeProvider
from .providers.ollama import OllamaProvider
from .providers.anthropic_provider import AnthropicProvider


class LlmRouter:
    """LLM 호출 단일 진입점.

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
        results = await router.compare("번역해줘", targets=["base44_http", ("ollama", "glm-5:cloud")])
    """

    def __init__(self, config: Optional[LlmConfig] = None):
        self.config = config or LlmConfig()
        self.usage_tracker = UsageTracker(self.config)

        # 우선순위 순서
        self.providers: list[BaseLlmProvider] = [
            Base44HttpProvider(self.config),
            Base44BridgeProvider(self.config),
            OllamaProvider(self.config),
            AnthropicProvider(self.config),
            # OpenAI, Gemini는 나중에 추가
        ]

    def _get_provider(self, provider_id: str) -> Optional[BaseLlmProvider]:
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
        """LLM 호출. 자동 폴백 또는 명시적 모델 선택."""

        # 명시적 선택 모드
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

        # 자동 폴백 모드
        errors = []
        for provider in self.providers:
            try:
                if not await provider.is_available():
                    continue

                response = await provider.call(
                    prompt, system=system, response_format=response_format,
                    max_tokens=max_tokens, purpose=purpose, **kwargs,
                )
                self.usage_tracker.log(response, purpose=purpose)
                return response

            except Exception as e:
                errors.append(f"{provider.provider_id}: {e}")
                continue

        raise LlmUnavailableError(
            "사용 가능한 LLM provider가 없습니다.\n"
            "확인 사항:\n"
            "  1. agent-chat: cd backend-44 && npm run agent:chat\n"
            "  2. Ollama: ollama serve\n"
            "  3. API 키: .env에 ANTHROPIC_API_KEY 등\n\n"
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
        """이미지 분석 호출. supports_image 인 provider만 시도."""

        if force_provider:
            provider = self._get_provider(force_provider)
            if not provider:
                raise LlmProviderError(f"provider '{force_provider}' 없음")
            if not provider.supports_image:
                raise LlmProviderError(f"'{force_provider}'은(는) 이미지 미지원")
            if not await provider.is_available():
                raise LlmProviderError(f"'{force_provider}' 사용 불가")

            response = await provider.call_with_image(
                prompt, image, image_mime=image_mime,
                model=force_model, **kwargs,
            )
            self.usage_tracker.log(response, purpose=purpose)
            return response

        errors = []
        for provider in self.providers:
            if not provider.supports_image:
                continue
            try:
                if not await provider.is_available():
                    continue
                response = await provider.call_with_image(
                    prompt, image, image_mime=image_mime, **kwargs,
                )
                self.usage_tracker.log(response, purpose=purpose)
                return response
            except Exception as e:
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

        targets: ["base44_http", ("ollama", "glm-5:cloud"), "anthropic"]
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
        """GUI 드롭다운용 모델 목록."""
        models = []

        for provider in self.providers:
            available = await provider.is_available()

            if provider.provider_id == "ollama" and available:
                try:
                    ollama_models = await provider.list_models()
                    for m in ollama_models:
                        models.append({
                            "provider": "ollama",
                            "model": m["name"],
                            "available": True,
                            "display": f"Ollama — {m['name']}",
                            "cost": "free",
                            "vision": m.get("vision", False),
                        })
                except Exception:
                    models.append({
                        "provider": "ollama",
                        "model": "(조회 실패)",
                        "available": False,
                        "display": "Ollama (모델 목록 조회 실패)",
                        "cost": "free",
                        "vision": False,
                    })
            else:
                models.append({
                    "provider": provider.provider_id,
                    "model": getattr(provider, "DEFAULT_MODEL", "auto"),
                    "available": available,
                    "display": provider.display_name,
                    "cost": "free" if "base44" in provider.provider_id or provider.provider_id == "ollama" else "paid",
                    "vision": provider.supports_image,
                })

        return models

    async def get_status(self) -> dict:
        """각 provider의 가용 상태. GET /api/llm/status에서 사용."""
        status = {}
        for provider in self.providers:
            try:
                avail = await provider.is_available()
                info = {"available": avail, "display_name": provider.display_name}

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
```

`src/llm/__init__.py`를 업데이트하라:

```python
"""LLM 호출 모듈. 모든 LLM 호출은 LlmRouter를 통해야 한다."""

from .router import LlmRouter
from .config import LlmConfig
from .providers.base import LlmResponse, LlmProviderError, LlmUnavailableError
```

테스트:

```python
# tests/test_llm_router.py
import pytest
from unittest.mock import AsyncMock, patch
from src.llm.router import LlmRouter
from src.llm.config import LlmConfig
from src.llm.providers.base import LlmResponse, LlmUnavailableError

@pytest.fixture
def router():
    return LlmRouter(LlmConfig())

@pytest.mark.asyncio
async def test_all_unavailable_raises(router):
    """모든 provider가 불가하면 LlmUnavailableError."""
    for p in router.providers:
        p.is_available = AsyncMock(return_value=False)
    with pytest.raises(LlmUnavailableError):
        await router.call("test")

@pytest.mark.asyncio
async def test_fallback_order(router):
    """1순위 실패 → 2순위 시도."""
    mock_response = LlmResponse(text="ok", provider="ollama", model="test")

    # 1순위, 2순위 불가
    router.providers[0].is_available = AsyncMock(return_value=False)
    router.providers[1].is_available = AsyncMock(return_value=False)
    # 3순위 (ollama) 가능
    router.providers[2].is_available = AsyncMock(return_value=True)
    router.providers[2].call = AsyncMock(return_value=mock_response)

    result = await router.call("test")
    assert result.provider == "ollama"

@pytest.mark.asyncio
async def test_force_provider(router):
    """force_provider로 특정 provider 직접 지정."""
    mock_response = LlmResponse(text="forced", provider="ollama", model="glm-5:cloud")
    router.providers[2].is_available = AsyncMock(return_value=True)
    router.providers[2].call = AsyncMock(return_value=mock_response)

    result = await router.call("test", force_provider="ollama", force_model="glm-5:cloud")
    assert result.text == "forced"
    assert result.model == "glm-5:cloud"

@pytest.mark.asyncio
async def test_get_status(router):
    """get_status가 모든 provider 상태를 반환."""
    for p in router.providers:
        p.is_available = AsyncMock(return_value=False)
    status = await router.get_status()
    assert "base44_http" in status
    assert "ollama" in status
    assert "anthropic" in status
```

커밋: `feat(llm): LlmRouter — 4단 폴백 + 모델 선택 + 비교`

---

### 작업 9: Usage Tracker

파일: `src/llm/usage_tracker.py`

```python
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class UsageTracker:
    """LLM 사용량 추적. 서고별 llm_usage_log.jsonl에 기록."""

    def __init__(self, config):
        self.config = config
        self._log_path: Optional[Path] = None

    def _get_log_path(self) -> Path:
        """로그 파일 경로. 서고 루트가 없으면 홈 디렉토리."""
        if self._log_path:
            return self._log_path

        library_root = getattr(self.config, '_library_root', None)
        if library_root:
            self._log_path = Path(library_root) / "llm_usage_log.jsonl"
        else:
            self._log_path = Path.home() / ".classical-text-browser" / "llm_usage_log.jsonl"

        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        return self._log_path

    def log(self, response, purpose: str = ""):
        """호출 기록 추가."""
        from .providers.base import LlmResponse
        if not isinstance(response, LlmResponse):
            return

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": "call",
            "provider": response.provider,
            "model": response.model,
            "tokens_in": response.tokens_in,
            "tokens_out": response.tokens_out,
            "cost_usd": response.cost_usd or 0.0,
            "elapsed_sec": response.elapsed_sec,
            "purpose": purpose,
        }
        self._append(entry)

    def log_comparison(self, purpose, targets, results):
        """비교 모드 호출 기록."""
        from .providers.base import LlmResponse

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": "comparison",
            "purpose": purpose,
            "targets": [{"provider": pid, "model": model} for pid, model in targets],
            "results": [
                {
                    "provider": r.provider if isinstance(r, LlmResponse) else None,
                    "model": r.model if isinstance(r, LlmResponse) else None,
                    "text_length": len(r.text) if isinstance(r, LlmResponse) else 0,
                    "elapsed_sec": r.elapsed_sec if isinstance(r, LlmResponse) else None,
                    "error": str(r) if isinstance(r, Exception) else None,
                }
                for r in results
            ],
        }
        self._append(entry)

    def _append(self, entry: dict):
        path = self._get_log_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_monthly_summary(self) -> dict:
        """이번 달 사용량 요약."""
        path = self._get_log_path()
        if not path.exists():
            return {"total_calls": 0, "total_cost_usd": 0.0, "by_provider": {}, "by_purpose": {}}

        now = datetime.now(timezone.utc)
        month_prefix = now.strftime("%Y-%m")

        total_calls = 0
        total_cost = 0.0
        by_provider = {}
        by_purpose = {}

        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") != "call":
                continue
            if not entry.get("ts", "").startswith(month_prefix):
                continue

            total_calls += 1
            cost = entry.get("cost_usd", 0.0) or 0.0
            total_cost += cost

            prov = entry.get("provider", "unknown")
            if prov not in by_provider:
                by_provider[prov] = {"calls": 0, "cost": 0.0}
            by_provider[prov]["calls"] += 1
            by_provider[prov]["cost"] += cost

            purp = entry.get("purpose", "unknown")
            by_purpose[purp] = by_purpose.get(purp, 0) + 1

        budget = float(self.config.get("monthly_budget_usd", 10.0) or 10.0)

        return {
            "total_calls": total_calls,
            "total_cost_usd": round(total_cost, 4),
            "by_provider": by_provider,
            "by_purpose": by_purpose,
            "budget_usd": budget,
            "budget_remaining_usd": round(budget - total_cost, 4),
        }
```

커밋: `feat(llm): UsageTracker — 비용 추적 + 비교 기록`

---

### 작업 10: LlmDraft 모델

파일: `src/llm/draft.py`

```python
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class LlmDraft:
    """LLM 결과의 Draft — 사람이 검토 후 확정하는 패턴.

    흐름: LLM 호출 → Draft(pending) → 사람 검토 → accepted/modified/rejected → Commit

    레이아웃 분석, 번역, 주석 등 모든 LLM 기능에서 사용.
    """

    draft_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    purpose: str = ""           # "layout_analysis", "translation", "annotation"
    status: str = "pending"     # pending → accepted | modified | rejected

    # LLM 결과
    provider: str = ""
    model: str = ""
    prompt_used: str = ""
    response_text: str = ""
    response_data: Optional[dict] = None  # 구조화된 결과 (JSON 파싱 후)

    # 비용
    cost_usd: float = 0.0
    elapsed_sec: float = 0.0

    # 검토 결과
    reviewed_by: str = "user"
    reviewed_at: Optional[str] = None
    modifications: Optional[str] = None  # modified일 때 변경 내용 설명

    # 품질 평가 (비교 테스트용)
    quality_rating: Optional[int] = None     # 1~5점
    quality_notes: Optional[str] = None      # "주석 영역 빠뜨림"
    compared_with: Optional[list] = None     # ["base44_http", "anthropic"]
    chosen_reason: Optional[str] = None      # "블록 구분 가장 정확"

    # 타임스탬프
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def accept(self, quality_rating: Optional[int] = None, notes: str = ""):
        self.status = "accepted"
        self.reviewed_at = datetime.now().isoformat()
        if quality_rating:
            self.quality_rating = quality_rating
        if notes:
            self.quality_notes = notes

    def modify(self, modifications: str, quality_rating: Optional[int] = None):
        self.status = "modified"
        self.reviewed_at = datetime.now().isoformat()
        self.modifications = modifications
        if quality_rating:
            self.quality_rating = quality_rating

    def reject(self, reason: str = ""):
        self.status = "rejected"
        self.reviewed_at = datetime.now().isoformat()
        self.quality_notes = reason

    def to_dict(self) -> dict:
        """JSON 직렬화용."""
        return {k: v for k, v in self.__dict__.items() if v is not None}
```

커밋: `feat(llm): LlmDraft — Draft→Review→Commit 패턴`

---

### 작업 11: 레이아웃 분석 프롬프트 + 핵심 로직

#### 11-A: 프롬프트

파일: `src/llm/prompts/layout_analysis.yaml`

```yaml
name: layout_analysis
version: "1.0"
description: "고전 텍스트 페이지 이미지에서 영역(LayoutBlock)을 식별"

system: |
  당신은 동아시아 고전 텍스트(한문, 한국 고서) 전문가입니다.
  주어진 페이지 이미지에서 텍스트 영역을 식별하고 각 영역의 종류와 위치를 JSON으로 반환합니다.

  영역 종류(block_type):
  - "본문"(main_text): 본문 텍스트 영역
  - "주석"(annotation): 주석, 협주, 두주 등
  - "판심제"(center_column): 판심(版心) 영역
  - "광곽"(border): 광곽(匡郭) 테두리
  - "장차"(page_number): 장차(張次) 표시
  - "어미"(fishtail): 어미(魚尾) 장식
  - "기타"(other): 도장, 장서인, 낙서 등

prompt_template: |
  이 고전 텍스트 페이지 이미지를 분석하세요.

  각 텍스트 영역을 식별하고, 아래 JSON 형식으로 반환하세요.
  좌표는 이미지 전체를 기준으로 한 비율(0.0~1.0)입니다.

  ```json
  {
    "blocks": [
      {
        "block_type": "main_text",
        "bbox_ratio": [x_min, y_min, x_max, y_max],
        "confidence": 0.95,
        "reading_order": 1,
        "notes": "우측 본문 영역, 10행"
      }
    ],
    "page_description": "2엽 양면 중 우측면, 사주단변, 10행 20자",
    "estimated_columns": 10
  }
  ```

  주의:
  - bbox_ratio는 [좌상단x, 좌상단y, 우하단x, 우하단y], 각 값 0.0~1.0
  - 한문은 우→좌, 위→아래로 읽으므로 reading_order를 우측부터 매기세요
  - 주석(협주)은 본문보다 작은 글자로 2행 병기된 부분입니다
  - 판심제는 접힌 부분(중앙)에 있는 제목·권차 정보입니다
  - JSON만 반환하세요. 설명 텍스트를 넣지 마세요.
```

#### 11-B: 핵심 로직

파일: `src/core/layout_analyzer.py`

```python
"""LLM 기반 레이아웃 분석.

이미지를 LLM에 보내서 LayoutBlock 제안을 받고, Draft로 반환.
"""

import json
import yaml
from pathlib import Path
from typing import Optional

from src.llm.router import LlmRouter
from src.llm.draft import LlmDraft
from src.llm.providers.base import LlmResponse


def _load_prompt() -> dict:
    prompt_path = Path(__file__).parent.parent / "llm" / "prompts" / "layout_analysis.yaml"
    with open(prompt_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


async def analyze_page_layout(
    router: LlmRouter,
    page_image: bytes,
    *,
    image_mime: str = "image/png",
    force_provider: Optional[str] = None,
    force_model: Optional[str] = None,
) -> LlmDraft:
    """페이지 이미지 → LLM 레이아웃 분석 → Draft 반환.

    반환된 Draft의 response_data에 blocks 배열이 들어있다.
    status는 "pending" — 사용자가 검토 후 accept/modify/reject.
    """
    prompt_config = _load_prompt()

    response: LlmResponse = await router.call_with_image(
        prompt_config["prompt_template"],
        page_image,
        image_mime=image_mime,
        system=prompt_config["system"],
        response_format="json",
        force_provider=force_provider,
        force_model=force_model,
        purpose="layout_analysis",
    )

    # JSON 파싱 시도
    response_data = None
    try:
        text = response.text.strip()
        # 코드블록 제거
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
        response_data = json.loads(text)
    except (json.JSONDecodeError, IndexError):
        response_data = {"raw_text": response.text, "parse_error": True}

    draft = LlmDraft(
        purpose="layout_analysis",
        provider=response.provider,
        model=response.model,
        prompt_used=prompt_config["prompt_template"][:200],
        response_text=response.text,
        response_data=response_data,
        cost_usd=response.cost_usd or 0.0,
        elapsed_sec=response.elapsed_sec or 0.0,
    )

    return draft


async def compare_layout_analysis(
    router: LlmRouter,
    page_image: bytes,
    *,
    targets: Optional[list] = None,
) -> list[LlmDraft]:
    """여러 모델로 레이아웃 분석 비교. Draft 목록 반환."""
    prompt_config = _load_prompt()

    results = await router.compare(
        prompt_config["prompt_template"],
        image=page_image,
        system=prompt_config["system"],
        targets=targets,
        purpose="layout_analysis",
    )

    drafts = []
    for r in results:
        if isinstance(r, Exception):
            drafts.append(LlmDraft(
                purpose="layout_analysis",
                status="rejected",
                quality_notes=f"호출 실패: {r}",
            ))
        else:
            response_data = None
            try:
                text = r.text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1]
                    if text.endswith("```"):
                        text = text[:-3]
                response_data = json.loads(text)
            except (json.JSONDecodeError, IndexError):
                response_data = {"raw_text": r.text, "parse_error": True}

            drafts.append(LlmDraft(
                purpose="layout_analysis",
                provider=r.provider,
                model=r.model,
                response_text=r.text,
                response_data=response_data,
                cost_usd=r.cost_usd or 0.0,
                elapsed_sec=r.elapsed_sec or 0.0,
            ))

    return drafts
```

커밋: `feat(llm): 레이아웃 분석 프롬프트 + Draft 패턴 적용`

---

### 작업 12: API 엔드포인트

기존 `src/api/` 패턴을 따라 LLM 관련 엔드포인트를 추가하라. 기존 라우터 구조를 먼저 확인하라.

파일: `src/api/llm_routes.py`

```python
"""LLM 관련 API 엔드포인트."""

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional
import json

# router, config는 앱 초기화 시 주입
# 아래는 엔드포인트 정의의 골격

router = APIRouter(prefix="/api/llm", tags=["llm"])


class LlmCallRequest(BaseModel):
    prompt: str
    system: Optional[str] = None
    response_format: str = "text"
    force_provider: Optional[str] = None
    force_model: Optional[str] = None
    purpose: str = "text"


class DraftReviewRequest(BaseModel):
    action: str  # "accept" | "modify" | "reject"
    quality_rating: Optional[int] = None
    quality_notes: Optional[str] = None
    modifications: Optional[str] = None


# ── Provider 상태 ──

@router.get("/status")
async def get_llm_status():
    """각 provider의 가용 상태."""
    # llm_router는 앱에서 주입
    from src.api.deps import get_llm_router
    llm_router = get_llm_router()
    return await llm_router.get_status()


@router.get("/models")
async def get_available_models():
    """GUI 드롭다운용 모델 목록."""
    from src.api.deps import get_llm_router
    llm_router = get_llm_router()
    return await llm_router.get_available_models()


@router.get("/usage")
async def get_usage_summary():
    """이번 달 사용량 요약."""
    from src.api.deps import get_llm_router
    llm_router = get_llm_router()
    return llm_router.usage_tracker.get_monthly_summary()


# ── 레이아웃 분석 ──

@router.post("/documents/{doc_id}/pages/{page}/layout/analyze")
async def analyze_layout(doc_id: str, page: int,
                         force_provider: Optional[str] = None,
                         force_model: Optional[str] = None):
    """페이지 이미지를 LLM으로 레이아웃 분석. Draft 반환."""
    from src.api.deps import get_llm_router, get_library
    from src.core.layout_analyzer import analyze_page_layout

    llm_router = get_llm_router()
    library = get_library()

    # 페이지 이미지 로드 (기존 library 메서드 사용)
    page_image = library.get_page_image(doc_id, page)
    if not page_image:
        raise HTTPException(404, f"페이지 이미지 없음: {doc_id} page {page}")

    draft = await analyze_page_layout(
        llm_router, page_image,
        force_provider=force_provider,
        force_model=force_model,
    )

    return draft.to_dict()


@router.post("/documents/{doc_id}/pages/{page}/layout/compare")
async def compare_layout(doc_id: str, page: int,
                         targets: Optional[list[str]] = None):
    """여러 모델로 레이아웃 분석 비교."""
    from src.api.deps import get_llm_router, get_library
    from src.core.layout_analyzer import compare_layout_analysis

    llm_router = get_llm_router()
    library = get_library()

    page_image = library.get_page_image(doc_id, page)
    if not page_image:
        raise HTTPException(404, f"페이지 이미지 없음")

    # targets 파싱: ["base44_http", "ollama:glm-5:cloud"]
    parsed_targets = None
    if targets:
        parsed_targets = []
        for t in targets:
            if ":" in t:
                parts = t.split(":", 1)
                parsed_targets.append((parts[0], parts[1]))
            else:
                parsed_targets.append(t)

    drafts = await compare_layout_analysis(
        llm_router, page_image, targets=parsed_targets,
    )

    return [d.to_dict() for d in drafts]


# ── Draft 관리 ──

# Draft 저장소는 메모리 (서버 재시작 시 소멸)
# 필요하면 나중에 파일 기반으로 변경
_drafts: dict = {}  # draft_id → LlmDraft


@router.post("/drafts/{draft_id}/review")
async def review_draft(draft_id: str, req: DraftReviewRequest):
    """Draft를 검토 (accept/modify/reject)."""
    draft = _drafts.get(draft_id)
    if not draft:
        raise HTTPException(404, f"Draft 없음: {draft_id}")

    if req.action == "accept":
        draft.accept(quality_rating=req.quality_rating, notes=req.quality_notes or "")
    elif req.action == "modify":
        draft.modify(modifications=req.modifications or "", quality_rating=req.quality_rating)
    elif req.action == "reject":
        draft.reject(reason=req.quality_notes or "")
    else:
        raise HTTPException(400, f"알 수 없는 action: {req.action}")

    return draft.to_dict()
```

**주의**: `src/api/deps.py`가 없으면 만들어라. 기존 앱 초기화 패턴에 맞춰 LlmRouter 인스턴스를 주입하는 방식을 구현. 기존 코드의 의존성 주입 패턴을 먼저 확인하라.

**주의**: 기존 `src/api/`의 라우터 등록 패턴을 확인하고, `llm_routes.router`를 앱에 포함시켜라.

커밋: `feat(llm): API 엔드포인트 — /status, /models, /usage, /analyze, /compare`

---

### 작업 13: GUI — 모델 선택 + AI 분석

기존 `static/js/layout-editor.js`를 수정하라. 없으면 새로 만들어라.

추가할 UI 요소:

1. **모델 선택 드롭다운** — "AI 분석" 버튼 옆에 배치
   - `GET /api/llm/models` 호출하여 목록 표시
   - "🔄 자동", 각 모델, "🔬 비교 모드" 옵션
   - 사용 불가 모델은 disabled + 사유 표시

2. **AI 분석 버튼** — 클릭 시:
   - 선택된 모델로 `POST /api/llm/documents/{doc_id}/pages/{page}/layout/analyze` 호출
   - force_provider, force_model 쿼리 파라미터 전달
   - 결과(Draft)를 점선 블록으로 표시

3. **비교 모드** — "🔬 비교 모드" 선택 시:
   - `POST .../layout/compare` 호출
   - 결과를 나란히 표시 (각 모델별 블록 + 시간 + 비용)
   - "이 결과 채택" 버튼으로 선택

4. **Draft 검토 UI** — 각 제안 블록에:
   - [✅ 승인] [✏️ 수정] [❌ 삭제] 버튼
   - 별점 (1~5) 입력 가능
   - "전체 확정" → 각 블록을 POST /drafts/{id}/review

5. **LLM 상태 표시** — 사이드바 또는 하단에:
   - `GET /api/llm/status` 호출
   - 🟢/⚫ 아이콘으로 각 provider 상태
   - 이번 달 비용: `GET /api/llm/usage`

구현 주의:
- 기존 layout-editor.js의 구조를 먼저 파악하고 기존 패턴에 맞춰 추가하라.
- 새 HTML 요소는 기존 레이아웃 편집기 영역에 자연스럽게 통합되어야 한다.
- API 호출은 기존 프로젝트의 fetch 패턴(에러 처리 포함)을 따라라.

커밋: `feat(llm): GUI — 모델 선택 + AI 분석 + 비교 모드 + 상태 표시`

---

### 작업 14: 통합 테스트

파일: `tests/test_llm_integration.py`

```python
"""LLM 시스템 통합 테스트.

실제 provider 연결은 하지 않는다 (mock).
Router → Provider → Draft → Review 전체 흐름을 검증.
"""

import pytest
from unittest.mock import AsyncMock, patch
from src.llm.router import LlmRouter
from src.llm.config import LlmConfig
from src.llm.draft import LlmDraft
from src.llm.providers.base import LlmResponse, LlmUnavailableError


@pytest.fixture
def config(tmp_path):
    return LlmConfig(library_root=tmp_path)


@pytest.fixture
def router(config):
    return LlmRouter(config)


class TestFallbackOrder:
    """폴백 순서 테스트."""

    @pytest.mark.asyncio
    async def test_first_available_wins(self, router):
        """첫 번째 사용 가능한 provider가 응답."""
        resp = LlmResponse(text="from_base44", provider="base44_http", model="auto")
        router.providers[0].is_available = AsyncMock(return_value=True)
        router.providers[0].call = AsyncMock(return_value=resp)

        result = await router.call("test")
        assert result.provider == "base44_http"
        # 2순위 이하는 시도하지 않아야 함
        for p in router.providers[1:]:
            p.is_available = AsyncMock(return_value=True)  # 설정만
        # 호출되지 않았는지는 call mock으로 확인 가능

    @pytest.mark.asyncio
    async def test_skip_to_third(self, router):
        """1·2순위 불가 → 3순위 시도."""
        router.providers[0].is_available = AsyncMock(return_value=False)
        router.providers[1].is_available = AsyncMock(return_value=False)

        resp = LlmResponse(text="from_ollama", provider="ollama", model="kimi")
        router.providers[2].is_available = AsyncMock(return_value=True)
        router.providers[2].call = AsyncMock(return_value=resp)

        result = await router.call("test")
        assert result.provider == "ollama"

    @pytest.mark.asyncio
    async def test_all_fail(self, router):
        """전부 실패 → LlmUnavailableError."""
        for p in router.providers:
            p.is_available = AsyncMock(return_value=False)
        with pytest.raises(LlmUnavailableError):
            await router.call("test")


class TestForceProvider:
    """명시적 모델 선택 테스트."""

    @pytest.mark.asyncio
    async def test_force_specific_model(self, router):
        resp = LlmResponse(text="forced", provider="ollama", model="glm-5:cloud")
        router.providers[2].is_available = AsyncMock(return_value=True)
        router.providers[2].call = AsyncMock(return_value=resp)

        result = await router.call("test", force_provider="ollama", force_model="glm-5:cloud")
        assert result.model == "glm-5:cloud"
        # call()에 model="glm-5:cloud"가 전달되었는지 확인
        router.providers[2].call.assert_called_once()
        call_kwargs = router.providers[2].call.call_args
        assert call_kwargs.kwargs.get("model") == "glm-5:cloud" or \
               (call_kwargs[1] and call_kwargs[1].get("model") == "glm-5:cloud")


class TestCompare:
    """비교 모드 테스트."""

    @pytest.mark.asyncio
    async def test_compare_returns_multiple(self, router):
        resp1 = LlmResponse(text="a", provider="base44_http", model="auto")
        resp2 = LlmResponse(text="b", provider="ollama", model="kimi")

        router.providers[0].is_available = AsyncMock(return_value=True)
        router.providers[0].call = AsyncMock(return_value=resp1)
        router.providers[2].is_available = AsyncMock(return_value=True)
        router.providers[2].call = AsyncMock(return_value=resp2)

        results = await router.compare(
            "test",
            targets=["base44_http", "ollama"],
        )
        assert len(results) == 2
        texts = {r.text for r in results if isinstance(r, LlmResponse)}
        assert "a" in texts
        assert "b" in texts


class TestDraftWorkflow:
    """Draft → Review → Commit 흐름."""

    def test_draft_accept(self):
        d = LlmDraft(purpose="layout_analysis", response_text="test")
        assert d.status == "pending"
        d.accept(quality_rating=4, notes="잘 됨")
        assert d.status == "accepted"
        assert d.quality_rating == 4

    def test_draft_modify(self):
        d = LlmDraft(purpose="layout_analysis")
        d.modify("주석 영역 좌표 수정", quality_rating=3)
        assert d.status == "modified"
        assert d.modifications == "주석 영역 좌표 수정"

    def test_draft_reject(self):
        d = LlmDraft(purpose="layout_analysis")
        d.reject("영역 구분 부정확")
        assert d.status == "rejected"


class TestUsageTracking:
    """비용 추적 테스트."""

    def test_log_and_summary(self, config):
        from src.llm.usage_tracker import UsageTracker
        tracker = UsageTracker(config)

        resp = LlmResponse(
            text="test", provider="ollama", model="kimi",
            tokens_in=100, tokens_out=50, cost_usd=0.0, elapsed_sec=1.5,
        )
        tracker.log(resp, purpose="layout_analysis")
        tracker.log(resp, purpose="translation")

        summary = tracker.get_monthly_summary()
        assert summary["total_calls"] == 2
        assert summary["by_provider"]["ollama"]["calls"] == 2
        assert summary["by_purpose"]["layout_analysis"] == 1
        assert summary["by_purpose"]["translation"] == 1
```

모든 테스트가 통과하는지 확인:

```bash
uv run pytest tests/test_llm_base.py tests/test_llm_config.py tests/test_llm_router.py tests/test_llm_integration.py -v
```

커밋: `test(llm): 통합 테스트 — 폴백, 모델 선택, 비교, Draft, 비용 추적`

---

### 작업 15: 최종 정리

1. `src/llm/providers/__init__.py`에 모든 provider를 export:

```python
from .base import BaseLlmProvider, LlmResponse, LlmProviderError, LlmUnavailableError
from .base44_http import Base44HttpProvider
from .base44_bridge import Base44BridgeProvider
from .ollama import OllamaProvider
from .anthropic_provider import AnthropicProvider
```

2. `docs/DECISIONS.md`에 추가:

```markdown
## D-010: LLM 호출 아키텍처 — 4단 폴백 + 모델 선택

- 결정일: 2026-02-15
- 상태: 확정
- 내용:
  - 모든 LLM 호출은 LlmRouter를 통한다
  - 우선순위: Base44 HTTP → Base44 Bridge → Ollama → 직접 API
  - force_provider/force_model로 특정 모델 지정 가능
  - compare()로 여러 모델 병렬 비교 가능
  - Draft → Review → Commit 패턴으로 LLM 결과를 사람이 검토
- 근거: Base44 무료 LLM 최대 활용 + 품질 비교를 통한 최적 모델 탐색
```

3. `docs/phase10_12_design.md`의 Phase 10-2 섹션에 "✅ 완료" 표시.

4. `.env.example`에 LLM 설정 항목 추가:

```env
# === LLM 설정 ===

# Base44 (1·2순위 — 무료)
# BASE44_TOKEN=your_token_here
# BASE44_BACKEND_PATH=C:\Users\junto\Downloads\head-repo\hw725\backend-44

# Ollama (3순위 — localhost:11434에서 자동 감지)

# 직접 API (4순위 — 유료)
# ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
# GOOGLE_API_KEY=AIza...

# 예산
# LLM_MONTHLY_BUDGET_USD=10.0
```

최종 커밋: `feat: Phase 10-2 완료 — LLM 4단 폴백 아키텍처 + 레이아웃 분석`

---

## 체크리스트

작업 완료 후 아래를 모두 확인하라:

- [ ] `src/llm/` 전체 구조가 위 디렉토리 구조와 일치
- [ ] `from src.llm import LlmRouter, LlmConfig, LlmResponse` 정상 동작
- [ ] 모든 테스트 통과 (`uv run pytest tests/test_llm_*.py -v`)
- [ ] agent-chat 안 띄운 상태에서 is_available() → False 확인
- [ ] .env.example에 LLM 설정 항목 추가됨
- [ ] DECISIONS.md에 D-010 추가됨
- [ ] bridge/invoke.js가 backend-44 경로를 올바르게 탐색
- [ ] API 엔드포인트가 기존 앱에 등록됨 (`/api/llm/status` 접근 가능)
- [ ] GUI에 모델 선택 드롭다운 + AI 분석 버튼 동작

---

## ⏭️ 다음 세션: Phase 10-1 — OCR 엔진 연동

```
이 세션(10-2)이 완료되면 다음 작업은 Phase 10-1 — OCR 엔진 연동이다.

10-2에서 만든 것:
  ✅ LlmRouter (4단 폴백)
  ✅ Base44HttpProvider, Base44BridgeProvider, OllamaProvider, AnthropicProvider
  ✅ Draft → Review → Commit 패턴
  ✅ UsageTracker (비용 추적)
  ✅ 레이아웃 분석 프롬프트 + 로직
  ✅ 모델 비교 모드 (compare)
  ✅ GUI — 모델 선택 + AI 분석

10-1에서 만들 것:
  - OCR 플러그인 아키텍처 (BaseOcrEngine + Registry)
  - PaddleOCR 엔진 (오프라인 퍼스트)
  - OCR 파이프라인 (L3 bbox → 이미지 크롭 → OCR → L2 저장)
  - API 엔드포인트
  - GUI — OCR 실행 + 결과 표시 + 이미지 오버레이

세션 문서: phase10_1_ocr_session.md
사전 준비:
  - PaddleOCR 설치 가능한지 확인 (paddlepaddle ~500MB)
  - GPU 없으면 CPU 버전으로 진행
  - L3 layout_page.json이 있는 테스트 데이터 확인
```
