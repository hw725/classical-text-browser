"""서고 `.env`를 화면에서 읽고 쓴다 — API 키를 손으로 편집하지 않게 (D-102).

왜 필요한가: v1.3.0까지 API 키를 넣는 길은 **`.env`를 직접 여는 것**뿐이었다. 처음 쓰는
사람에게 「메모장으로 .env를 열어 ANTHROPIC_API_KEY=… 를 적으세요」는 넘기 어려운 문턱이고,
BOM·cp949로 저장해 라우터 초기화가 통째로 실패한 사고도 있었다(llm/config.py 주석).

어디에 쓰는가: **서고 루트의 `.env`**다. 프로젝트 루트가 아니다 —
  - 앱을 새 판으로 갈아도 키가 남는다(서고는 앱 폴더 밖에 있다).
  - 서고마다 다른 계정을 쓸 수 있다.
  - 프로젝트 루트 `.env`는 그대로 읽히고(우선순위는 llm/config.py), 이 모듈은 건드리지 않는다.

값을 돌려주지 않는다: 읽기는 **있는가와 끝 네 글자**만 알린다. 화면·로그·API 어디에도 키
전체가 나가지 않는다. 예외는 비밀이 아닌 기본 모델 셋(PLAIN_KEYS, D-143)뿐이다.
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
    # 판정 모델(D-134) — 글을 만들지 않고 확률 붙은 판정만 돌려주는 모델. LLM 라우터 밖에서 쓴다
    "perplexity": "PERPLEXITY_API_KEY",  # Perplexity Decisions(이미지 판정 — 자동 스캔의 종류)
    "typesafe": "TYPESAFE_API_KEY",  # TypeSafe Jev(텍스트 판정 — 편성 본문·목차 판정의 주, D-139)
    # OpenRouter — Perplexity decider v1.1(본문 판정에서 Jev가 실패한 호출만, D-139)·TypeSafe 키가
    # 없을 때의 OpenRouter 경유 Jev·이미지 판정 clef
    "openrouter": "OPENROUTER_API_KEY",
    # Cloudflare Workers AI clef(이미지 판정 — 자동 스캔의 종류, 키가 있으면 기본, D-135).
    # 주소에 계정 id가 들어가 값이 둘이다. 없으면 Windows 사용자 환경변수도 본다(llm/clef_cf.py)
    "cloudflare": "CLOUDFLARE_API_TOKEN",
    "cloudflare_account": "CLOUDFLARE_ACCOUNT_ID",
    # 자동(폴백 순서) 기본 모델(D-143) — 비밀이 아니라 그대로 보인다(PLAIN_KEYS).
    # 설정 「LLM 연결」의 Ollama·OpenAI(OAuth) 칸에서 고른다. 비우면 앱에 든 기본값
    "ollama_text_model": "OLLAMA_TEXT_MODEL",
    "openai_oauth_model": "OPENAI_OAUTH_MODEL",
    "openai_oauth_effort": "OPENAI_OAUTH_EFFORT",
}

# 값을 가리지 않고 돌려주는 키 — 모델 이름·추론 강도는 비밀이 아니고, 사람이 무엇을 골랐는지
# 보여야 고를 수 있다. API 키는 여기에 넣지 않는다.
PLAIN_KEYS = frozenset({"ollama_text_model", "openai_oauth_model", "openai_oauth_effort"})

# 추론 강도로 받는 값 — llm.providers.openai_oauth_provider.OpenAiOAuthProvider.EFFORTS와 같다.
# 다른 글이 들어가면 프로바이더가 무시하고 medium으로 돌므로, 저장할 때 막아 화면과 실제를 맞춘다.
_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
# 모델 이름 모양 — Ollama(`kimi-k3:cloud`)·OpenAI(`gpt-6.1-sol`) 둘 다. 공백·따옴표·= 은 받지 않는다
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$")

_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def env_path(library_root: str | Path) -> Path:
    return Path(library_root) / ".env"


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return _read_lines_for_write(path)  # UTF-8 → cp949 순으로 — 쓰기와 같은 판독
    except (OSError, ValueError) as e:
        logger.warning(".env를 읽지 못했습니다 (%s): %s", path, e)
        return []


def _looks_korean(text: str) -> bool:
    """ASCII 밖 글자가 모두 한글·한자·전각 문장부호인가. cp949 판독을 믿어도 되는지 가린다."""
    for ch in text:
        if ord(ch) < 128:
            continue
        o = ord(ch)
        if not (0xAC00 <= o <= 0xD7A3 or 0x3130 <= o <= 0x318F or 0x4E00 <= o <= 0x9FFF
                or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF or 0x2000 <= o <= 0x206F
                or 0x1100 <= o <= 0x11FF or 0xF900 <= o <= 0xFAFF):
            return False
    return True


def _read_lines_for_write(path: Path) -> list[str]:
    """고쳐 쓰기 전에 읽는다 — 못 읽으면 **쓰지 않는다**. 입력: .env 경로. 출력: 줄 목록.

    왜 _read_lines와 따로인가(2026-10-11 전수): 읽기용은 못 읽으면 빈 목록을 돌려준다. 쓰기가
    그것을 받으면 관리 키만 적은 파일로 갈아 끼워, 사람이 적어 둔 모델 고정·예산 같은 다른 줄이
    통째로 사라졌다. 한글 주석이 든 cp949 .env(메모장이 《ANSI》로 저장한 것)가 바로 그 경우라,
    cp949로 한 번 더 읽어 보고(다시 쓸 때는 UTF-8) 그것도 안 되면 ValueError로 멈춘다.
    cp949로 《읽히기만》 하는 다른 8비트 파일(라틴 문자 등)을 cp949로 오해해 다시 쓰면 글자가
    바뀐다 — 그래서 cp949 판독은 ASCII 밖 글자가 한글·한자일 때만 받는다(2026-10-11 재확인).
    """
    if not path.exists():
        return []
    raw = path.read_bytes()  # OSError는 그대로 올린다 — 라우트가 알린다
    try:
        return raw.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError:
        pass
    try:
        text = raw.decode("cp949")
    except UnicodeDecodeError:
        text = None
    if text is not None and _looks_korean(text):
        return text.splitlines()
    raise ValueError(
        f"{path}를 읽지 못해 고치지 않았습니다(UTF-8도 한글 cp949도 아님).\n"
        "→ 해결: 그 파일을 메모장에서 열어 《UTF-8》로 다시 저장한 뒤 다시 시도하세요."
    )


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
    """키를 사람이 《맞는 것 같다》고만 알아볼 수 있게. 끝 네 글자만 남긴다."""
    v = (value or "").strip()
    if not v:
        return ""
    return f"…{v[-4:]}" if len(v) > 4 else "…"


def read_status(library_root: str | Path) -> dict:
    """서고 .env에 무엇이 들어 있는가. **키 값은 돌려주지 않는다**(PLAIN_KEYS만 value).

    출력: {"path", "exists", "keys": {provider: {"set": bool, "hint": "…abcd", "value"?: str}}}
    """
    p = env_path(library_root)
    values = _parse(_read_lines(p))
    keys = {}
    for provider, env_name in MANAGED_KEYS.items():
        v = values.get(env_name, "")
        keys[provider] = {"set": bool(v), "hint": mask(v), "env_name": env_name}
        if provider in PLAIN_KEYS:
            keys[provider]["value"] = v  # 모델 이름·강도는 비밀이 아니다(D-143)
    return {"path": str(p), "exists": p.exists(), "keys": keys}


def write_values(library_root: str | Path, updates: dict[str, str | None]) -> dict:
    """서고 .env를 고친다. **다른 줄은 그대로 둔다.**

    입력: {provider: 값}. 값이 빈 문자열이나 None이면 그 줄을 지운다.
    출력: read_status()와 같은 모양.

    왜 통째로 다시 쓰지 않는가: 사람이 적어 둔 주석·다른 설정(모델 고정, 예산 등)이
    사라지면 안 된다. 아는 열쇠만 갈아 끼우고 나머지는 손대지 않는다.
    """
    p = env_path(library_root)
    lines = _read_lines_for_write(p)
    wanted = {MANAGED_KEYS[k]: (v or "").strip() for k, v in updates.items() if k in MANAGED_KEYS}
    # 값 속 개행은 다른 줄(=다른 키)이 된다 — 키 하나 저장으로 설정을 덮어쓰게 할 수 없다.
    for k, v in wanted.items():
        if "\n" in v or "\r" in v:
            raise ValueError(f"{k} 값에 줄바꿈이 들어 있습니다.")
    effort = wanted.get(MANAGED_KEYS["openai_oauth_effort"])
    if effort and effort not in _EFFORTS:
        raise ValueError(
            f"추론 강도는 {', '.join(_EFFORTS)} 중 하나여야 합니다(받은 값: {effort})."
        )
    for k in ("ollama_text_model", "openai_oauth_model"):
        v = wanted.get(MANAGED_KEYS[k])
        if v and not _MODEL_RE.match(v):
            raise ValueError(f"{MANAGED_KEYS[k]} 값이 모델 이름 모양이 아닙니다: {v[:60]}")
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
    tmp = p.with_name(p.name + ".tmp")  # with_suffix는 점 파일에서 《.env.env.tmp》가 됐다
    tmp.write_text(body, encoding="utf-8", newline="\n")
    tmp.replace(p)  # 원자적 교체 — 도중에 죽어도 반쪽 파일이 남지 않는다
    logger.info(".env 갱신: %s (%s)", p, ", ".join(sorted(wanted)))  # 값은 남기지 않는다
    return read_status(library_root)


OLLAMA_CANDIDATES = (
    "http://127.0.0.1:11434",
    "http://[::1]:11434",  # OLLAMA_HOST=localhost로 띄우면 Windows에서 IPv6에만 붙는 경우가 있다
)


def detect_ollama(base_url: str | None = None, timeout: float = 2.0) -> dict:
    """Ollama가 도는지, 어떤 모델이 있는지 본다.

    출력: {"reachable": bool, "base_url": str, "models": [이름…], "error": str|None,
           "tried": [주소…]}
    왜 여기 있는가: 마법사가 「Ollama를 켜 두셨나요」를 사람에게 묻는 대신 직접 확인한다.
    주소를 안 주면 후보(127.0.0.1 → [::1])를 차례로 본다 — 어느 쪽에 떠 있는지는 기기마다
    다르다(2026-09-05: 한 PC는 127.0.0.1만, 다른 PC는 그것으로 안 잡힘).
    """
    import json
    import urllib.request

    if base_url:
        candidates = [base_url.rstrip("/").replace("://localhost:", "://127.0.0.1:")]
    else:
        candidates = list(OLLAMA_CANDIDATES)
    # 시스템 프록시(HTTP_PROXY)가 잡힌 PC에서 127.0.0.1 요청이 프록시로 나가 실패한다 —
    # 로컬 호출은 프록시를 타지 않는다.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    errors = []
    for url in candidates:
        try:
            with opener.open(f"{url}/api/tags", timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            models = [m.get("name", "") for m in (data.get("models") or []) if m.get("name")]
            return {
                "reachable": True,
                "base_url": url,
                "models": models,
                "error": None,
                "tried": candidates,
            }
        except Exception as e:  # noqa: BLE001 — 안 떠 있는 것이 정상 상태의 하나다
            errors.append(f"{url}: {str(e)[:120]}")
    return {
        "reachable": False,
        "base_url": candidates[0],
        "models": [],
        "error": " | ".join(errors)[:400],
        "tried": candidates,
    }
