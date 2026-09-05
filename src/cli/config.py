"""CLI 기본값 — 자주 쓰는 옵션을 기억한다.

왜: `ctb ocr 논문.pdf --model openai_oauth:gpt-6-astra --paddle-lang korean`을 매번 치면
CLI가 편하지 않다(2026-09-05 지적). 한 번 저장해 두면 다음부터는 `ctb ocr 논문.pdf`만
친다. 우선순위는 **명령줄 > 저장한 기본값 > 내장 기본값**이다 — 저장해 둔 것은 언제나
명령줄 한 번으로 덮어쓸 수 있다.

어디에: 사용자 홈의 `.classical-text-browser/cli.json`. 서고가 아니라 **사람**의 것이다 —
같은 사람이 여러 서고를 써도 자주 쓰는 모델은 같다.

쓰는 법:
    ctb config                      저장된 기본값 보기
    ctb config set model openai_oauth:gpt-6-astra
    ctb config set paddle_lang korean
    ctb config unset model
    ctb ocr 논문.pdf --engine paddleocr --remember   이번에 준 옵션을 기본값으로 저장
"""

from __future__ import annotations

import json
from pathlib import Path

# 저장할 수 있는 키와 설명. 여기 없는 키는 거절한다 — 오타가 조용히 무시되지 않게.
ENGINES = ("llm_vision", "paddleocr", "ndlocr", "ndlkotenocr", "ndlkotenocr-full")
PROVIDERS = ("ollama", "openai_oauth", "gemini", "openai", "anthropic")

KEYS: dict[str, str] = {
    "engine": "OCR 엔진 (llm_vision·paddleocr·ndlocr·ndlkotenocr)",
    "model": "llm_vision이 쓸 LLM «프로바이더:모델» (예: openai_oauth:gpt-6-astra)",
    "paddle_lang": "PaddleOCR 언어 모델 (korean·chinese_cht·ch·japan·en)",
    "paddle_device": "PaddleOCR 연산 장치 (auto·cpu·gpu)",
    "line_detection": "줄 위치 검출 (true·false)",
    "sleep": "쪽 사이 대기 초",
    "library": "작업 서고 경로",
}


def config_path() -> Path:
    return Path.home() / ".classical-text-browser" / "cli.json"


def load() -> dict:
    """저장된 기본값. 파일이 없거나 깨졌으면 빈 dict — CLI가 멈추면 안 된다."""
    p = config_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    # 손으로 고친 파일("sleep": "1")도 형을 맞춰 읽는다 — time.sleep에 문자열이 가면 죽는다.
    out = {}
    for k, v in data.items():
        if k not in KEYS:
            continue
        try:
            out[k] = coerce(k, str(v)) if not isinstance(v, (bool, float)) else v
        except ValueError:
            continue  # 잘못된 값은 없는 것으로 — 저장값 때문에 CLI가 멈추면 안 된다
    return out


def save(data: dict) -> Path:
    from core.document import write_json_atomic

    p = config_path()
    write_json_atomic(p, {k: v for k, v in data.items() if k in KEYS})
    return p


def coerce(key: str, value: str):
    """문자열로 들어온 값을 키에 맞는 형으로. 잘못된 값은 ValueError."""
    if key not in KEYS:
        raise ValueError(f"모르는 키입니다: {key}. 쓸 수 있는 키: {', '.join(KEYS)}")
    if key == "line_detection":
        v = value.strip().lower()
        if v in ("true", "1", "yes", "on", "켬"):
            return True
        if v in ("false", "0", "no", "off", "끔"):
            return False
        raise ValueError("line_detection은 true 또는 false")
    if key == "sleep":
        try:
            return float(value)
        except ValueError as e:
            raise ValueError("sleep은 초(숫자)") from e
    if key == "paddle_device" and value not in ("auto", "cpu", "gpu"):
        raise ValueError("paddle_device는 auto·cpu·gpu 중 하나")
    if key == "engine" and value.strip() not in ENGINES:
        raise ValueError(f"engine은 {', '.join(ENGINES)} 중 하나")
    if key == "model":
        v = value.strip()
        head = v.split(":", 1)[0]
        if not v or head not in PROVIDERS:
            raise ValueError(
                "model은 «프로바이더:모델» 꼴 (프로바이더: " + ", ".join(PROVIDERS) + ")"
            )
    if key == "library":
        from pathlib import Path

        # 상대 경로를 저장하면 다른 폴더에서 치는 순간 새 서고가 생긴다 — 절대 경로로.
        return str(Path(value.strip()).expanduser().resolve())
    return value.strip()


def describe(data: dict) -> str:
    """사람이 읽을 목록. 비어 있으면 그렇다고 말한다."""
    if not data:
        return (
            f"저장된 기본값이 없습니다. ({config_path()})\n"
            "  예: ctb config set model 9   (번호는 ctb models)"
        )
    lines = [f"저장된 기본값 ({config_path()}):"]
    for k, v in data.items():
        lines.append(f"  {k} = {v}    — {KEYS[k]}")
    return "\n".join(lines)
