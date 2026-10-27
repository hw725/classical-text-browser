"""Claude Code CLI Provider — OpenAI OAuth 넘침분을 마무리한다 (2026-10-27).

왜 있는가:
    사용자 지시(2026-10-27): 「남은 사용량이 감당 못할 거 같으면 자동으로 네가 마저
    처리하도록 하란 말이야」. 「네가」는 Claude 다. OAuth(ChatGPT 구독)의 남은 사용량이
    예비분 이하이거나 조회에 실패하거나 한도 오류(401·402·403·429·quota)가 나면,
    그 몫을 Ollama·Gemini 가 아니라 Claude 가 맡는다. API 키(AnthropicProvider)가 없어도
    이 PC 에 로그인된 Claude Code(`claude`)가 있으면 그것을 쓴다.

평소 순서에는 끼지 않는다(OVERFLOW_ONLY):
    라우터는 이 공급자를 OAuth 가 사용량 때문에 막혔을 때만 부른다. 배포판을 받은
    다른 사용자의 PC 에 `claude` 가 깔려 있다고 해서 Gemini·OpenAI 앞에서 그 구독을
    쓰게 되면 안 되기 때문이다.
    사람이 모델 칸에서 고르면(force_provider="claude_cli") 언제든 쓴다.

호출:
    claude -p --output-format text --tools "" --no-session-persistence
           [--system-prompt-file <임시 파일>] [--model <모델>]
    본문은 표준 입력으로 보낸다. 도구를 다 끄므로 파일·명령에 손대지 않는다.
    이미지는 보내지 않는다(supports_image=False) — 비전 넘침분은 라우터가
    Anthropic(API 키)으로 보낸다.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from .base import BaseLlmProvider, LlmProviderError, LlmResponse

# 한 번 호출 상한. 소량 실측 약 11초(BRIEF 2026-10-27). 긴 JSON 답(주석·표점)은
# 몇 분 걸릴 수 있어 넉넉히 둔다.
_TIMEOUT_SEC = 600


def find_claude() -> Optional[str]:
    """`claude` 실행 파일. npm 판의 claude.cmd 는 옆의 claude.exe 를 직접 쓴다.

    왜: .cmd 를 거치면 cmd.exe 가 인자를 다시 해석해 지시문의 줄바꿈·따옴표가 깨진다.
    """
    exe = shutil.which("claude")
    if not exe:
        return None
    if exe.lower().endswith((".cmd", ".bat")):
        pkg = Path(exe).parent / "node_modules" / "@anthropic-ai" / "claude-code"
        native = pkg / "bin" / "claude.exe"
        if native.is_file():
            return str(native)
    return exe


class ClaudeCliProvider(BaseLlmProvider):
    """이 PC 에 로그인된 Claude Code(`claude -p`)로 텍스트 호출."""

    provider_id = "claude_cli"
    display_name = "Claude (Claude Code CLI)"
    supports_image = False
    # Claude 구독(Claude Code 로그인) 한도를 쓴다 — 금액은 0으로 적지만 공짜가 아니다(D-056).
    billing_model = "subscription"
    setup_kind = "cli_signin"
    setup_steps = (
        "Claude Code 설치(npm i -g @anthropic-ai/claude-code)",
        "터미널에서 claude 를 한 번 실행해 로그인",
    )
    # 자동 순서에서는 OAuth 넘침분에만 쓴다(라우터가 본다).
    OVERFLOW_ONLY = True
    DEFAULT_MODEL = "claude (CLI 기본)"

    def default_model(self) -> str:
        return (self.config.get("claude_cli_model") or "").strip() or self.DEFAULT_MODEL

    async def is_available(self) -> bool:
        return find_claude() is not None

    async def list_models(self) -> list[dict]:
        return [{"name": self.default_model(), "vision": False, "cost": "subscription"}]

    def _argv(self, exe: str, system_file: Optional[str], model: Optional[str]) -> list[str]:
        # 빈 인자 "" 는 claude.exe 를 직접 부를 때 그대로 간다. .CMD 를 거쳐도 %* 가 `""` 를 그대로
        # 넘겨 node 가 빈 문자열로 받는다.
        argv = [exe, "-p", "--output-format", "text", "--tools", "", "--no-session-persistence"]
        if system_file:
            argv += ["--system-prompt-file", system_file]
        chosen = model or (self.config.get("claude_cli_model") or "").strip()
        if chosen:
            argv += ["--model", chosen]
        return argv

    async def call(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        response_format: str = "text",
        model: Optional[str] = None,
        max_tokens: int = 4096,
        purpose: str = "text",
        **kwargs,
    ) -> LlmResponse:
        exe = find_claude()
        if not exe:
            raise LlmProviderError(
                "Claude Code(claude) 실행 파일을 찾지 못했습니다 — OAuth 넘침분을 맡을 수 없습니다"
            )
        body = prompt
        if response_format == "json":
            body += "\n\n(JSON 객체 하나만 출력하라. 앞뒤 설명·코드 울타리 없이.)"
        env = dict(os.environ)
        env.pop("CLAUDECODE", None)  # Claude Code 안에서 띄운 서버여도 중첩 실행 거부를 피한다

        # 지시문은 인자가 아니라 파일로 넘긴다(--system-prompt-file). npm 판 claude.CMD 를 거치면
        # cmd.exe 가 줄바꿈 든 인자를 첫 줄에서 자르고, 명령줄 길이(32,767자)도 넘을 수 있다.
        sys_path: Optional[str] = None
        if system:
            fd, sys_path = tempfile.mkstemp(prefix="ctb_claude_sys_", suffix=".txt")
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(system)
        argv = self._argv(exe, sys_path, model)

        t0 = time.monotonic()
        try:
            proc = await asyncio.to_thread(
                subprocess.run, argv, input=body, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=_TIMEOUT_SEC, env=env,
            )
        except subprocess.TimeoutExpired as e:
            raise LlmProviderError(f"claude -p 가 {_TIMEOUT_SEC}초 안에 끝나지 않았습니다") from e
        finally:
            if sys_path:
                try:
                    os.unlink(sys_path)  # 이 함수가 만든 임시 지시문 파일만 지운다
                except OSError:
                    pass
        elapsed = time.monotonic() - t0
        text = (proc.stdout or "").strip()
        if proc.returncode != 0 or not text:
            err = " ".join((proc.stderr or proc.stdout or "").split())[:200]
            raise LlmProviderError(f"claude -p 실패(코드 {proc.returncode}): {err or '빈 출력'}")
        if response_format == "json" and text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        return LlmResponse(
            text=text,
            provider=self.provider_id,
            model=model or self.default_model(),
            cost_usd=0.0,  # 구독 한도 — 금액은 0이지만 한도를 쓴다
            elapsed_sec=round(elapsed, 2),
        )

    async def call_with_image(self, prompt, image, **kwargs) -> LlmResponse:
        raise LlmProviderError("Claude Code CLI 공급자는 이미지를 받지 않습니다")
