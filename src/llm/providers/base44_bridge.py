"""Base44 Bridge Provider (2순위).

Node.js 브릿지 스크립트를 subprocess로 실행하여 Base44 SDK 호출.
agent-chat 서버가 안 떠있을 때의 대안.

호출 흐름:
    Python → subprocess.run(["node", "invoke.js", ...])
          → invoke.js → Base44 SDK InvokeLLM
          → stdout JSON → Python 파싱

전제:
    - Node.js 20+ 설치됨
    - backend-44 디렉토리가 설정에 지정됨
    - base44 login 완료 (토큰이 ~/.base44/auth/auth.json에 있음)
"""

import asyncio
import functools
import json
import subprocess
import tempfile
import time
from pathlib import Path

from .base import BaseLlmProvider, LlmProviderError, LlmResponse


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
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                functools.partial(
                    subprocess.run,
                    ["node", "--version"],
                    capture_output=True,
                    timeout=5.0,
                ),
            )
            if result.returncode != 0:
                return False
        except (FileNotFoundError, subprocess.TimeoutExpired):
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
        """Node.js 스크립트를 실행하고 결과를 반환.

        왜 이렇게 하는가:
            Windows의 asyncio ProactorEventLoop에서
            create_subprocess_exec + pipe 조합이 Node.js와 호환되지 않는다.
            subprocess.run을 스레드 풀(run_in_executor)에서 실행하면
            표준 OS 파이프를 사용하므로 Windows에서도 안정적으로 동작한다.
        """
        import os

        env_vars = {}
        backend_path = self.config.get("base44_backend_path")
        if backend_path:
            env_vars["BACKEND44_PATH"] = str(backend_path)

        full_env = {**os.environ, **env_vars}

        # 입력 데이터를 임시 파일로 작성 → 환경변수로 경로 전달
        # (stdin pipe 대신 파일을 사용하면 EOF 문제 완전 회피)
        input_file = Path(tempfile.mktemp(suffix=".json"))
        input_file.write_text(json.dumps(input_data), encoding="utf-8")
        full_env["BRIDGE_INPUT_FILE"] = str(input_file)

        try:
            # subprocess.run을 스레드 풀에서 실행 (asyncio 이벤트 루프 블로킹 방지)
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    functools.partial(
                        subprocess.run,
                        ["node", str(script)],
                        capture_output=True,
                        env=full_env,
                        timeout=timeout,
                    ),
                ),
                timeout=timeout + 5,  # executor 자체 타임아웃 여유
            )
        except (asyncio.TimeoutError, subprocess.TimeoutExpired):
            raise LlmProviderError(f"Base44 bridge 타임아웃 ({timeout}초)")
        finally:
            input_file.unlink(missing_ok=True)

        if result.returncode != 0:
            err_msg = result.stderr.decode("utf-8", errors="replace")
            try:
                err_data = json.loads(err_msg)
                err_msg = err_data.get("error", err_msg)
            except (json.JSONDecodeError, KeyError):
                pass
            raise LlmProviderError(f"Base44 bridge 실패: {err_msg}")

        # stdout에 client.js의 로그가 섞여 있을 수 있으므로
        # JSON 객체 부분만 추출한다. (마지막 '{' ~ 마지막 '}')
        raw_out = result.stdout.decode("utf-8", errors="replace")
        json_start = raw_out.rfind('{"')
        if json_start < 0:
            raise LlmProviderError(f"Base44 bridge: JSON 응답 없음. stdout={raw_out[:200]}")
        return json.loads(raw_out[json_start:])

    async def call(self, prompt, *, system=None, response_format="text",
                   model=None, max_tokens=4096, purpose="text",
                   **kwargs) -> LlmResponse:
        """Node.js 브릿지로 InvokeLLM 호출."""
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
        """이미지를 임시 파일로 저장 → bridge에 경로 전달."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(image)
            tmp_path = tmp.name

        try:
            t0 = time.monotonic()
            full_prompt = prompt
            if system:
                full_prompt = f"[시스템 지시]\n{system}\n\n[요청]\n{prompt}"

            data = await self._run_bridge(self._vision_script, {
                "prompt": full_prompt,
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
