"""앱 전역 설정 관리.

서고 경로와 무관한 앱 수준 설정을 관리한다.
설정 파일: ~/.classical-text-platform/config.json

왜 서고 안이 아닌 홈 디렉토리인가:
    서고가 여러 개일 수 있고, 서고 경로 자체를 기억해야 하므로
    서고 외부의 고정된 위치에 저장해야 한다.

저장 항목:
    - recent_libraries: 최근 사용한 서고 목록 (최대 10개)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 설정 경로 ──────────────────────────────────

CONFIG_DIR = Path.home() / ".classical-text-platform"
CONFIG_FILE = CONFIG_DIR / "config.json"

# 최근 서고 목록 최대 개수
_MAX_RECENT = 10


# ── 설정 파일 읽기/쓰기 ─────────────────────────

def load_app_config() -> dict:
    """앱 설정을 로드한다.

    출력: 설정 dict. 파일이 없으면 빈 dict.
    """
    if not CONFIG_FILE.exists():
        return {}

    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"앱 설정 읽기 실패 (기본값 사용): {e}")
        return {}


def save_app_config(config: dict) -> None:
    """앱 설정을 저장한다.

    입력: config — 전체 설정 dict.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# ── 최근 서고 관리 ──────────────────────────────

def get_recent_libraries() -> list[dict]:
    """최근 사용한 서고 목록을 반환한다.

    출력:
        [{
            "path": "/abs/path/to/library",
            "name": "monggu_library",
            "last_used": "2026-02-20T12:34:56+00:00"
        }, ...]
        최신 순 정렬, 최대 10개.
    """
    config = load_app_config()
    recent = config.get("recent_libraries", [])

    # 존재하지 않는 서고 제거 (경로가 사라진 경우)
    valid = []
    for entry in recent:
        path = entry.get("path", "")
        if path and Path(path).exists():
            valid.append(entry)

    return valid[:_MAX_RECENT]


def add_recent_library(path: str | Path, name: str | None = None) -> None:
    """서고를 최근 목록에 추가하거나 업데이트한다.

    입력:
        path — 서고의 절대 경로.
        name — 서고 이름 (None이면 디렉토리명 사용).

    동작:
        - 이미 목록에 있으면 last_used만 갱신하고 맨 앞으로 이동.
        - 없으면 맨 앞에 추가.
        - 10개 초과 시 오래된 항목 제거.
    """
    abs_path = str(Path(path).resolve())
    effective_name = name or Path(abs_path).name
    now = datetime.now(timezone.utc).isoformat()

    config = load_app_config()
    recent: list[dict] = config.get("recent_libraries", [])

    # 기존 항목 제거 (경로 기준)
    recent = [r for r in recent if r.get("path") != abs_path]

    # 맨 앞에 추가
    recent.insert(0, {
        "path": abs_path,
        "name": effective_name,
        "last_used": now,
    })

    # 최대 개수 제한
    config["recent_libraries"] = recent[:_MAX_RECENT]
    save_app_config(config)


def get_last_library() -> str | None:
    """마지막으로 사용한 서고 경로를 반환한다.

    출력: 절대 경로 문자열, 또는 None (기록 없음).

    주의: 경로가 존재하는지 확인한다.
          삭제된 서고는 건너뛰고 그다음 서고를 반환한다.
    """
    recent = get_recent_libraries()
    for entry in recent:
        path = entry.get("path", "")
        if path and (Path(path) / "library_manifest.json").exists():
            return path
    return None
