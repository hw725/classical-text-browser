"""LLM 설정 관리.

설정 우선순위: 환경변수 → .env 파일 → 기본값.
"""

import os
from pathlib import Path
from typing import Optional


class LlmConfig:
    """LLM 설정 관리.

    설정 우선순위: 환경변수 → .env 파일 → 기본값.

    사용법:
        config = LlmConfig(library_root=Path("./test_library"))
        api_key = config.get_api_key("anthropic")
        ollama_url = config.get("ollama_url")
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
            env_file = Path(library_root) / ".env"
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
