"""LLM 설정 관리.

설정 우선순위: 환경변수 → .env 파일 → 기본값.
"""

import logging
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
        # localhost가 아니라 127.0.0.1: Windows는 localhost를 IPv6(::1)부터 시도해 Ollama(IPv4)에
        # 닿기까지 2초를 버린다(2026-09-05 실측 2.11s vs 0.04s). 호출마다 그랬다.
        "ollama_url": "http://127.0.0.1:11434",
        "monthly_budget_usd": 10.0,
    }

    # 환경변수명 매핑
    API_KEY_ENV = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GOOGLE_API_KEY",
    }

    def __init__(self, library_root: Optional[Path] = None):
        self._library_root = library_root
        self._env_cache: dict = {}

        # .env 파일 로드 우선순위:
        #   1. 프로젝트 루트 (.env.example과 같은 위치)
        #   2. 서고(library) 루트
        # 서고 .env가 프로젝트 루트 .env의 값을 덮어쓴다.
        # → API 키는 프로젝트 루트에, 서고별 설정은 서고 .env에 넣을 수 있다.
        # src/llm/config.py → 프로젝트 루트
        project_root = Path(__file__).resolve().parent.parent.parent
        project_env = project_root / ".env"
        if project_env.exists():
            self._env_cache = self._load_dotenv(project_env)

        if library_root:
            lib_env = Path(library_root) / ".env"
            if lib_env.exists():
                # 서고 .env가 프로젝트 .env를 덮어쓴다 (merge)
                self._env_cache.update(self._load_dotenv(lib_env))

    def _load_dotenv(self, path: Path) -> dict:
        """간단한 .env 파서. python-dotenv 없이 동작.

        인코딩: UTF-8(BOM 허용). Windows 메모장이 남기는 BOM이나 cp949로 저장된
        파일에서 UnicodeDecodeError로 죽으면 LLM 라우터 초기화가 실패하고, 그
        라우터를 주입받는 OCR 엔진 목록까지 500이 된다. 못 읽는 글자는 치환하고
        경고만 남긴다 — API 키는 ASCII라 영향이 없다.
        """
        result = {}
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            logging.getLogger(__name__).warning(
                f".env가 UTF-8이 아닙니다: {path} — 못 읽는 글자는 치환합니다. "
                "UTF-8로 다시 저장하세요."
            )
            text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
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

    def is_set(self, key: str) -> bool:
        """사람이 정해 둔 값이 있는가 — 환경변수나 .env에. DEFAULTS는 «정한 것»이 아니다."""
        env_key = key.upper()
        return bool(os.environ.get(env_key) or self._env_cache.get(env_key))

    def get(self, key: str, default=None):
        """설정값 조회. 환경변수(대문자) → .env → DEFAULTS → default."""
        env_key = key.upper()
        val = os.environ.get(env_key) or self._env_cache.get(env_key)
        if val is not None:
            return val
        return self.DEFAULTS.get(key, default)
