"""L5 현토(懸吐) 코어 로직.

원문 문자열은 절대 변형하지 않는다.
현토는 글자 인덱스(0-based, inclusive)에 붙일 토(한글)만 기록.
"""

import json
import uuid
from pathlib import Path

from jsonschema import validate

# ──────────────────────────────────────
# 스키마 로드 (모듈 레벨 캐시)
# ──────────────────────────────────────

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent / "schemas" / "interp" / "hyeonto_page.schema.json"
)

_schema_cache: dict | None = None


def _get_schema() -> dict:
    """현토 JSON 스키마를 로드한다 (최초 1회만 읽음)."""
    global _schema_cache
    if _schema_cache is None:
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            _schema_cache = json.load(f)
    return _schema_cache


# ──────────────────────────────────────
# 파일 I/O
# ──────────────────────────────────────


def load_hyeonto(interp_path: str | Path, part_id: str, page_num: int, block_id: str) -> dict:
    """L5 현토 파일에서 특정 블록의 현토를 로드한다.

    목적: 해석 저장소의 L5_reading/main_text에서 현토 JSON을 읽는다.
    입력:
        interp_path — 해석 저장소 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호.
        block_id — 블록 ID.
    출력: {"block_id": ..., "annotations": [...]}.
          파일 없거나 해당 블록 없으면 빈 annotations 반환.
    """
    interp_path = Path(interp_path).resolve()
    file_path = _hyeonto_file_path(interp_path, part_id, page_num)

    if not file_path.exists():
        return {"block_id": block_id, "annotations": []}

    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    if data.get("block_id") == block_id:
        return data

    return {"block_id": block_id, "annotations": []}


def save_hyeonto(
    interp_path: str | Path,
    part_id: str,
    page_num: int,
    data: dict,
) -> Path:
    """L5 현토를 스키마 검증 후 저장한다.

    목적: 현토 데이터를 JSON으로 기록한다.
    입력:
        interp_path — 해석 저장소 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호.
        data — {"block_id": ..., "annotations": [...]}.
    출력: 저장된 파일 경로.
    Raises: jsonschema.ValidationError — 스키마 불일치 시.
    """
    validate(instance=data, schema=_get_schema())

    interp_path = Path(interp_path).resolve()
    file_path = _hyeonto_file_path(interp_path, part_id, page_num)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    file_path.write_text(text, encoding="utf-8")

    return file_path


def _hyeonto_file_path(interp_path: Path, part_id: str, page_num: int) -> Path:
    """현토 파일 경로 조립.

    컨벤션: L5_reading/main_text/{part_id}_page_{NNN}_hyeonto.json
    """
    return (
        interp_path
        / "L5_reading"
        / "main_text"
        / f"{part_id}_page_{page_num:03d}_hyeonto.json"
    )


# ──────────────────────────────────────
# CRUD — annotations 배열 조작
# ──────────────────────────────────────


def _gen_annotation_id() -> str:
    """현토 ID 자동 생성. 예: ht_a1b2c3"""
    return f"ht_{uuid.uuid4().hex[:6]}"


def add_annotation(data: dict, annotation: dict) -> dict:
    """현토를 추가한다.

    목적: annotations 배열에 새 현토를 추가한다. id가 없으면 자동 생성.
    입력:
        data — {"block_id": ..., "annotations": [...]}.
        annotation — {"target": {"start": N, "end": N}, "position": "after", "text": "은"}.
    출력: id가 추가된 annotation dict.
    """
    if "id" not in annotation or not annotation["id"]:
        annotation["id"] = _gen_annotation_id()
    if "category" not in annotation:
        annotation["category"] = None

    data["annotations"].append(annotation)
    return annotation


def remove_annotation(data: dict, annotation_id: str) -> bool:
    """현토를 삭제한다.

    출력: 삭제 성공 여부.
    """
    original_len = len(data["annotations"])
    data["annotations"] = [a for a in data["annotations"] if a["id"] != annotation_id]
    return len(data["annotations"]) < original_len


def update_annotation(data: dict, annotation_id: str, updates: dict) -> dict | None:
    """현토를 수정한다.

    입력:
        updates — 수정할 필드. 예: {"text": "하고"} 또는 {"position": "before"}.
    출력: 수정된 annotation. 없으면 None.
    """
    for ann in data["annotations"]:
        if ann["id"] == annotation_id:
            for key, value in updates.items():
                ann[key] = value
            return ann
    return None


# ──────────────────────────────────────
# 렌더링 — 원문 + 현토 합성
# ──────────────────────────────────────


def render_hyeonto_text(original_text: str, annotations: list[dict]) -> str:
    """원문에 현토를 삽입한 합성 텍스트를 생성한다.

    목적: GUI 미리보기용. 원문 문자열 자체는 변형하지 않고,
          annotations에 지정된 위치에 토를 삽입한 새 문자열을 반환.

    알고리즘:
        1. 각 글자 위치에 대해 before/after 토 버퍼를 준비
        2. annotations를 순회하며 position에 따라 적절한 버퍼에 기록
        3. 글자별로 before + 글자 + after를 연결

    입력:
        original_text — L4 원문 문자열. 예: "王戎簡要裴楷清通"
        annotations — annotations 배열.
    출력: 합성 텍스트. 예: "王戎은簡要하고裴楷ᅵ清通하니"
    """
    if not original_text:
        return ""

    n = len(original_text)
    before_buf = [""] * n
    after_buf = [""] * n

    for ann in annotations:
        target = ann.get("target", {})
        start = target.get("start", 0)
        end = target.get("end", start)
        position = ann.get("position", "after")
        text = ann.get("text", "")

        # 범위 검증
        if start < 0 or end >= n or start > end:
            continue

        if position == "before":
            before_buf[start] += text
        else:
            # "after" (기본), "over", "under" → 일단 end 뒤에 삽입
            after_buf[end] += text

    # 합성
    parts = []
    for i, ch in enumerate(original_text):
        parts.append(before_buf[i])
        parts.append(ch)
        parts.append(after_buf[i])

    return "".join(parts)
