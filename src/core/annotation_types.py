"""주석 유형(Annotation Types) 관리.

기본 프리셋 8종(person, place, term, allusion, official_title,
book_title, grammar, note)을 제공하고,
사용자가 커스텀 유형을 추가/삭제할 수 있다.
프리셋 중 보호 유형(person, place, book_title)을 제외한 나머지는 서고별로 숨길 수 있다.

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

# 절대 삭제할 수 없는 보호 유형.
# 왜: 인명·지명·서명은 고전 텍스트 주석의 핵심이며,
#     이 세 유형 없이는 주석 작업이 성립하지 않는다.
PROTECTED_TYPE_IDS = frozenset({"person", "place", "book_title"})


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


def _load_work_data(work_path: str | Path) -> dict:
    """서고별 설정 파일을 로드한다. 없으면 빈 구조를 반환."""
    custom_path = _work_types_path(work_path)
    if custom_path.exists():
        with open(custom_path, encoding="utf-8") as f:
            return json.load(f)
    return {"custom": [], "hidden": []}


def _save_work_data(work_path: str | Path, work_data: dict):
    """서고별 설정 파일을 저장한다."""
    custom_path = _work_types_path(work_path)
    custom_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(work_data, ensure_ascii=False, indent=2) + "\n"
    custom_path.write_text(text, encoding="utf-8")


# ──────────────────────────────────────
# 공개 API
# ──────────────────────────────────────


def load_annotation_types(work_path: str | Path | None = None) -> dict:
    """기본 프리셋 + 사용자 정의 유형을 병합하여 반환한다.

    목적: 모든 주석 유형의 통합 목록을 제공.
    입력:
        work_path — 서고 경로. None이면 기본 프리셋만.
    출력: {"types": [...], "custom": [...], "hidden": [...], "all": [...]}
          types — 숨기지 않은 프리셋 목록.
          all = types + custom (검색용 통합 배열).
          hidden — 숨겨진 프리셋 ID 목록.
    """
    data = _load_default_types()
    hidden_ids = set()

    # 서고별 커스텀 유형 + 숨김 목록 병합
    if work_path is not None:
        work_data = _load_work_data(work_path)
        data["custom"] = work_data.get("custom", [])
        hidden_ids = set(work_data.get("hidden", []))

    # 숨겨진 프리셋은 types에서 제외
    if hidden_ids:
        data["types"] = [t for t in data["types"] if t["id"] not in hidden_ids]

    data["hidden"] = sorted(hidden_ids)

    # 통합 배열
    data["all"] = data["types"] + data.get("custom", [])
    return data


def add_custom_type(work_path: str | Path, type_def: dict) -> dict:
    """사용자 정의 주석 유형을 추가한다.

    목적: 기본 8종 외에 연구자가 필요한 유형을 추가.
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

    # 숨겨진 프리셋과도 중복 확인
    defaults = _load_default_types()
    default_ids = {t["id"] for t in defaults["types"]}
    if type_def["id"] in default_ids:
        raise ValueError(
            f"기본 프리셋과 동일한 ID입니다: {type_def['id']}. "
            "숨긴 프리셋을 복원하려면 restore_preset_type()을 사용하세요."
        )

    work_data = _load_work_data(work_path)
    work_data["custom"].append(type_def)
    _save_work_data(work_path, work_data)

    return type_def


def remove_type(work_path: str | Path, type_id: str) -> bool:
    """주석 유형을 삭제(숨김)한다.

    목적: 사용하지 않는 유형을 목록에서 제거.
    입력:
        work_path — 서고 경로.
        type_id — 삭제할 유형 ID.
    출력: 삭제 성공 여부.

    동작 방식:
        - 보호 유형(person, place, book_title)은 삭제할 수 없다.
        - 커스텀 유형이면 custom 배열에서 완전 삭제.
        - 프리셋 유형이면 hidden 배열에 추가하여 숨김 처리.
          (resources/annotation_types.json 원본은 수정하지 않는다.)
    """
    if type_id in PROTECTED_TYPE_IDS:
        return False

    work_data = _load_work_data(work_path)

    # 1) 커스텀 유형에서 찾기
    custom_list = work_data.get("custom", [])
    original_len = len(custom_list)
    work_data["custom"] = [t for t in custom_list if t["id"] != type_id]
    if len(work_data["custom"]) < original_len:
        _save_work_data(work_path, work_data)
        return True

    # 2) 프리셋 유형이면 숨김 처리
    defaults = _load_default_types()
    default_ids = {t["id"] for t in defaults["types"]}
    if type_id in default_ids:
        hidden = set(work_data.get("hidden", []))
        if type_id in hidden:
            return False  # 이미 숨김 상태
        hidden.add(type_id)
        work_data["hidden"] = sorted(hidden)
        _save_work_data(work_path, work_data)
        return True

    return False


def restore_preset_type(work_path: str | Path, type_id: str) -> bool:
    """숨긴 프리셋 유형을 복원한다.

    목적: 실수로 삭제한 프리셋을 다시 활성화.
    입력:
        work_path — 서고 경로.
        type_id — 복원할 유형 ID.
    출력: 복원 성공 여부.
    """
    work_data = _load_work_data(work_path)
    hidden = set(work_data.get("hidden", []))
    if type_id not in hidden:
        return False

    hidden.discard(type_id)
    work_data["hidden"] = sorted(hidden)
    _save_work_data(work_path, work_data)
    return True


# 하위 호환: 기존 코드가 remove_custom_type을 호출할 수 있으므로 별칭 유지.
remove_custom_type = remove_type


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
