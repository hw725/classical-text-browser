"""서고 `.env`를 화면에서 읽고 쓴다 — API 키를 손으로 편집하지 않게 (D-102).

왜 필요한가: v1.3.0까지 API 키를 넣는 길은 **`.env`를 직접 여는 것**뿐이었다. 처음 쓰는
사람에게 「메모장으로 .env를 열어 ANTHROPIC_API_KEY=… 를 적으세요」는 넘기 어려운 문턱이고,
BOM·cp949로 저장해 라우터 초기화가 통째로 실패한 사고도 있었다(llm/config.py 주석).

어디에 쓰는가: **서고 루트의 `.env`**다. 프로젝트 루트가 아니다 —
  - 앱을 새 판으로 갈아도 키가 남는다(서고는 앱 폴더 밖에 있다).
  - 서고마다 다른 계정을 쓸 수 있다.
  - 프로젝트 루트 `.env`는 그대로 읽히고(우선순위는 llm/config.py), 이 모듈은 건드리지 않는다.

값을 돌려주지 않는다: 읽기는 **있는가와 끝 네 글자**만 알린다. 화면·로그·API 어디에도 키
전체가 나가지 않는다.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# 화면에서 다룰 수 있는 값. 여기 없는 키는 이 모듈이 손대지 않는다 —
# .env에 사람이 적어 둔 다른 설정을 지우지 않기 위해서다.
MANAGED_KEYS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "ollama_url": "OLLAMA_URL",
}

_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def env_path(library_root: str | Path) -> Path:
    return Path(library_root) / ".env"


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        logger.warning(".env를 읽지 못했습니다 (%s): %s", path, e)
        return []


def _parse(lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in lines:
        if ln.lstrip().startswith("#"):
            continue
        m = _LINE_RE.match(ln)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def mask(value: str) -> str:
    """키를 사람이 «맞는 것 같다»고만 알아볼 수 있게. 끝 네 글자만 남긴다."""
    v = (value or "").strip()
    if not v:
        return ""
    return f"…{v[-4:]}" if len(v) > 4 else "…"


def read_status(library_root: str | Path) -> dict:
    """서고 .env에 무엇이 들어 있는가. **값은 돌려주지 않는다.**

    출력: {"path", "exists", "keys": {provider: {"set": bool, "hint": "…abcd"}}}
    """
    p = env_path(library_root)
    values = _parse(_read_lines(p))
    keys = {}
    for provider, env_name in MANAGED_KEYS.items():
        v = values.get(env_name, "")
        keys[provider] = {"set": bool(v), "hint": mask(v), "env_name": env_name}
    return {"path": str(p), "exists": p.exists(), "keys": keys}


def write_values(library_root: str | Path, updates: dict[str, str | None]) -> dict:
    """서고 .env를 고친다. **다른 줄은 그대로 둔다.**

    입력: {provider: 값}. 값이 빈 문자열이나 None이면 그 줄을 지운다.
    출력: read_status()와 같은 모양.

    왜 통째로 다시 쓰지 않는가: 사람이 적어 둔 주석·다른 설정(모델 고정, 예산 등)이
    사라지면 안 된다. 아는 열쇠만 갈아 끼우고 나머지는 손대지 않는다.
    """
    p = env_path(library_root)
    lines = _read_lines(p)
    wanted = {MANAGED_KEYS[k]: (v or "").strip() for k, v in updates.items() if k in MANAGED_KEYS}
    if not wanted:
        return read_status(library_root)

    out: list[str] = []
    seen: set[str] = set()
    for ln in lines:
        m = _LINE_RE.match(ln) if not ln.lstrip().startswith("#") else None
        name = m.group(1) if m else None
        if name in wanted:
            seen.add(name)
            val = wanted[name]
            if val:  # 값이 있으면 갈아 끼우고, 비었으면 그 줄을 지운다
                out.append(f"{name}={val}")
            continue
        out.append(ln)
    for name, val in wanted.items():
        if name not in seen and val:
            out.append(f"{name}={val}")

    body = "\n".join(out).rstrip("\n") + "\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".env.tmp")
    tmp.write_text(body, encoding="utf-8", newline="\n")
    tmp.replace(p)  # 원자적 교체 — 도중에 죽어도 반쪽 파일이 남지 않는다
    logger.info(".env 갱신: %s (%s)", p, ", ".join(sorted(wanted)))  # 값은 남기지 않는다
    return read_status(library_root)


def detect_ollama(base_url: str | None = None, timeout: float = 2.0) -> dict:
    """Ollama가 도는지, 어떤 모델이 있는지 본다.

    출력: {"reachable": bool, "base_url": str, "models": [이름…], "error": str|None}
    왜 여기 있는가: 마법사가 「Ollama를 켜 두셨나요」를 사람에게 묻는 대신 직접 확인한다.
    """
    import json
    import urllib.error
    import urllib.request

    url = (base_url or "http://127.0.0.1:11434").rstrip("/")
    # localhost → 127.0.0.1: Windows가 IPv6를 먼저 시도해 2초를 버리고, 그 사이 제한 시간(2초)을
    # 넘기면 떠 있는 Ollama를 «없음»으로 판정한다(2026-09-05 실측·보고).
    url = url.replace("://localhost:", "://127.0.0.1:")
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        models = [m.get("name", "") for m in (data.get("models") or []) if m.get("name")]
        return {"reachable": True, "base_url": url, "models": models, "error": None}
    except Exception as e:  # noqa: BLE001 — 안 떠 있는 것이 정상 상태의 하나다
        return {"reachable": False, "base_url": url, "models": [], "error": str(e)[:200]}
