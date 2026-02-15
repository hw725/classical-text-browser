"""L6 번역(Translation) 코어 로직.

문장 단위 번역 CRUD + 상태 관리.
표점(L5)으로 분리된 문장이 기본 번역 단위이며,
표점이 없으면 블록 전체를 하나의 문장으로 취급한다.
"""

import json
import uuid
from pathlib import Path

from jsonschema import validate

# ──────────────────────────────────────
# 스키마 로드 (모듈 레벨 캐시)
# ──────────────────────────────────────

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent / "schemas" / "interp" / "translation_page.schema.json"
)

_schema_cache: dict | None = None


def _get_schema() -> dict:
    """번역 JSON 스키마를 로드한다 (최초 1회만 읽음)."""
    global _schema_cache
    if _schema_cache is None:
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            _schema_cache = json.load(f)
    return _schema_cache


# ──────────────────────────────────────
# 파일 I/O
# ──────────────────────────────────────


def load_translations(
    interp_path: str | Path, part_id: str, page_num: int
) -> dict:
    """L6 번역 파일을 로드한다.

    목적: 해석 저장소의 L6_translation에서 번역 JSON을 읽는다.
    입력:
        interp_path — 해석 저장소 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호.
    출력: {"part_id": ..., "page_number": ..., "translations": [...]}.
          파일 없으면 빈 translations 반환.
    """
    interp_path = Path(interp_path).resolve()
    file_path = _translation_file_path(interp_path, part_id, page_num)

    if not file_path.exists():
        return {
            "part_id": part_id,
            "page_number": page_num,
            "translations": [],
        }

    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


def save_translations(
    interp_path: str | Path,
    part_id: str,
    page_num: int,
    data: dict,
) -> Path:
    """L6 번역을 스키마 검증 후 저장한다.

    목적: 번역 데이터를 JSON으로 기록한다.
    입력:
        interp_path — 해석 저장소 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호.
        data — {"part_id": ..., "page_number": ..., "translations": [...]}.
    출력: 저장된 파일 경로.
    Raises: jsonschema.ValidationError — 스키마 불일치 시.
    """
    validate(instance=data, schema=_get_schema())

    interp_path = Path(interp_path).resolve()
    file_path = _translation_file_path(interp_path, part_id, page_num)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    file_path.write_text(text, encoding="utf-8")

    return file_path


def _translation_file_path(interp_path: Path, part_id: str, page_num: int) -> Path:
    """번역 파일 경로 조립.

    컨벤션: L6_translation/main_text/{part_id}_page_{NNN}_translation.json

    왜 이렇게 하는가:
        기존 L6_translation/main_text/에 .txt 파일이 있을 수 있으므로,
        구조화된 번역 JSON은 _translation 접미사로 구분한다.
    """
    return (
        interp_path
        / "L6_translation"
        / "main_text"
        / f"{part_id}_page_{page_num:03d}_translation.json"
    )


# ──────────────────────────────────────
# CRUD — translations 배열 조작
# ──────────────────────────────────────


def _gen_translation_id() -> str:
    """번역 ID 자동 생성. 예: tr_a1b2c3"""
    return f"tr_{uuid.uuid4().hex[:6]}"


def add_translation(data: dict, entry: dict) -> dict:
    """번역을 추가한다.

    목적: translations 배열에 새 번역을 추가한다. id가 없으면 자동 생성.
    입력:
        data — {"part_id": ..., "page_number": ..., "translations": [...]}.
        entry — 번역 항목. source, source_text, translation 등 포함.
    출력: id가 추가된 entry dict.
    """
    if "id" not in entry or not entry["id"]:
        entry["id"] = _gen_translation_id()

    # 필수 필드 기본값 채우기
    entry.setdefault("hyeonto_text", None)
    entry.setdefault("target_language", "ko")
    entry.setdefault("status", "draft")
    entry.setdefault("reviewed_by", None)
    entry.setdefault("reviewed_at", None)
    entry.setdefault("translator", {"type": "human", "model": None, "draft_id": None})

    data["translations"].append(entry)
    return entry


def update_translation(data: dict, translation_id: str, updates: dict) -> dict | None:
    """번역을 수정한다.

    입력:
        updates — 수정할 필드. 예: {"translation": "수정된 번역", "status": "accepted"}.
    출력: 수정된 translation. 없으면 None.
    """
    for tr in data["translations"]:
        if tr["id"] == translation_id:
            for key, value in updates.items():
                tr[key] = value
            return tr
    return None


def remove_translation(data: dict, translation_id: str) -> bool:
    """번역을 삭제한다.

    출력: 삭제 성공 여부.
    """
    original_len = len(data["translations"])
    data["translations"] = [
        tr for tr in data["translations"] if tr["id"] != translation_id
    ]
    return len(data["translations"]) < original_len


# ──────────────────────────────────────
# 상태 요약
# ──────────────────────────────────────


def get_translation_status(data: dict) -> dict:
    """번역 상태 요약을 반환한다.

    목적: 페이지 전체의 번역 진행 상황을 한눈에 파악.
    출력: {"total": N, "draft": N, "reviewed": N, "accepted": N}.
    """
    translations = data.get("translations", [])
    status_counts = {"total": len(translations), "draft": 0, "reviewed": 0, "accepted": 0}

    for tr in translations:
        s = tr.get("status", "draft")
        if s in status_counts:
            status_counts[s] += 1

    return status_counts
