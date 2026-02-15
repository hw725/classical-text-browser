"""주석 유형(Annotation Types) 관리.

기본 프리셋 5종(person, place, term, allusion, note)을 제공하고,
사용자가 커스텀 유형을 추가/삭제할 수 있다.

유형 정보는 resources/annotation_types.json에 기본값이 있고,
서고별로 덮어쓰기한 파일이 있으면 그것을 우선한다.
"""

import json
from pathlib import Path

# ──────────────────────────────────────
# 기본 프리셋 경로
# ──────────────────────────────────────

_DEFAULT_TYPES_PATH = (
    Path(__file__).parent.parent.parent / "resources" / "annotation_types.json"
)


def _load_default_types() -> dict:
    """resources/annotation_types.json에서 기본 프리셋을 로드한다."""
    with open(_DEFAULT_TYPES_PATH, encoding="utf-8") as f:
        return json.load(f)


def _work_types_path(work_path: str | Path) -> Path:
    """서고별 커스텀 유형 파일 경로.

    왜 이렇게 하는가:
        기본 프리셋은 resources/에 있지만,
        사용자 정의 유형은 서고(work) 안에 저장하여
        서고를 공유하면 유형도 함께 이동하도록 한다.
    """
    return Path(work_path).resolve() / "annotation_types.json"


# ──────────────────────────────────────
# 공개 API
# ──────────────────────────────────────


def load_annotation_types(work_path: str | Path | None = None) -> dict:
    """기본 프리셋 + 사용자 정의 유형을 병합하여 반환한다.

    목적: 모든 주석 유형의 통합 목록을 제공.
    입력:
        work_path — 서고 경로. None이면 기본 프리셋만.
    출력: {"types": [...], "custom": [...], "all": [...]}
          all = types + custom (검색용 통합 배열).
    """
    data = _load_default_types()

    # 서고별 커스텀 유형이 있으면 병합
    if work_path is not None:
        custom_path = _work_types_path(work_path)
        if custom_path.exists():
            with open(custom_path, encoding="utf-8") as f:
                work_data = json.load(f)
            data["custom"] = work_data.get("custom", [])

    # 통합 배열
    data["all"] = data["types"] + data.get("custom", [])
    return data


def add_custom_type(work_path: str | Path, type_def: dict) -> dict:
    """사용자 정의 주석 유형을 추가한다.

    목적: 기본 5종 외에 연구자가 필요한 유형을 추가.
    입력:
        work_path — 서고 경로.
        type_def — {"id": "sutra_ref", "label": "경전 참조", "color": "#...", "icon": "🙏"}.
    출력: 추가된 type_def.
    Raises: ValueError — id가 중복되거나 필수 필드 누락 시.
    """
    # 필수 필드 검증
    for field in ("id", "label", "color"):
        if field not in type_def:
            raise ValueError(f"주석 유형에 필수 필드가 없습니다: {field}")

    type_def.setdefault("icon", "🏷️")

    # 기존 유형과 중복 확인
    all_types = load_annotation_types(work_path)
    existing_ids = {t["id"] for t in all_types["all"]}
    if type_def["id"] in existing_ids:
        raise ValueError(f"이미 존재하는 유형 ID입니다: {type_def['id']}")

    # 서고별 파일 로드 또는 생성
    custom_path = _work_types_path(work_path)
    if custom_path.exists():
        with open(custom_path, encoding="utf-8") as f:
            work_data = json.load(f)
    else:
        work_data = {"custom": []}

    work_data["custom"].append(type_def)

    # 저장
    custom_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(work_data, ensure_ascii=False, indent=2) + "\n"
    custom_path.write_text(text, encoding="utf-8")

    return type_def


def remove_custom_type(work_path: str | Path, type_id: str) -> bool:
    """사용자 정의 주석 유형을 삭제한다.

    목적: 더 이상 사용하지 않는 커스텀 유형 제거.
    입력:
        work_path — 서고 경로.
        type_id — 삭제할 유형 ID.
    출력: 삭제 성공 여부.

    주의: 기본 프리셋(types)은 삭제할 수 없다. custom만 삭제 가능.
    """
    custom_path = _work_types_path(work_path)
    if not custom_path.exists():
        return False

    with open(custom_path, encoding="utf-8") as f:
        work_data = json.load(f)

    original_len = len(work_data.get("custom", []))
    work_data["custom"] = [
        t for t in work_data.get("custom", []) if t["id"] != type_id
    ]

    if len(work_data["custom"]) == original_len:
        return False

    text = json.dumps(work_data, ensure_ascii=False, indent=2) + "\n"
    custom_path.write_text(text, encoding="utf-8")
    return True


def validate_type(work_path: str | Path | None, type_id: str) -> bool:
    """주석 유형 ID가 유효한지 확인한다.

    목적: 주석 생성/수정 시 유형 검증.
    입력:
        work_path — 서고 경로. None이면 기본 프리셋만 확인.
        type_id — 확인할 유형 ID.
    출력: True이면 유효.
    """
    all_types = load_annotation_types(work_path)
    return any(t["id"] == type_id for t in all_types["all"])
