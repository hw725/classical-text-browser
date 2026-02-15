"""L7 주석(Annotation) 코어 로직.

블록 내 원문 범위에 대한 주석 CRUD + 필터링 + 상태 관리.
주석 유형은 annotation_types.json으로 관리하며, 고정 enum이 아니다.
"""

import json
import uuid
from pathlib import Path

from jsonschema import validate

# ──────────────────────────────────────
# 스키마 로드 (모듈 레벨 캐시)
# ──────────────────────────────────────

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent / "schemas" / "interp" / "annotation_page.schema.json"
)

_schema_cache: dict | None = None


def _get_schema() -> dict:
    """주석 JSON 스키마를 로드한다 (최초 1회만 읽음)."""
    global _schema_cache
    if _schema_cache is None:
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            _schema_cache = json.load(f)
    return _schema_cache


# ──────────────────────────────────────
# 파일 I/O
# ──────────────────────────────────────


def _annotation_file_path(interp_path: Path, part_id: str, page_num: int) -> Path:
    """주석 파일 경로 조립.

    컨벤션: L7_annotation/main_text/{part_id}_page_{NNN}_annotation.json

    왜 이렇게 하는가:
        L5(_punctuation/_hyeonto), L6(_translation)와 동일한 패턴.
        _annotation 접미사로 다른 파일과 구분한다.
    """
    return (
        interp_path
        / "L7_annotation"
        / "main_text"
        / f"{part_id}_page_{page_num:03d}_annotation.json"
    )


def load_annotations(
    interp_path: str | Path, part_id: str, page_num: int
) -> dict:
    """L7 주석 파일을 로드한다.

    목적: 해석 저장소의 L7_annotation에서 주석 JSON을 읽는다.
    입력:
        interp_path — 해석 저장소 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호.
    출력: {"part_id": ..., "page_number": ..., "blocks": [...]}.
          파일 없으면 빈 blocks 반환.
    """
    interp_path = Path(interp_path).resolve()
    file_path = _annotation_file_path(interp_path, part_id, page_num)

    if not file_path.exists():
        return {
            "part_id": part_id,
            "page_number": page_num,
            "blocks": [],
        }

    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


def save_annotations(
    interp_path: str | Path,
    part_id: str,
    page_num: int,
    data: dict,
) -> Path:
    """L7 주석을 스키마 검증 후 저장한다.

    목적: 주석 데이터를 JSON으로 기록한다.
    입력:
        interp_path — 해석 저장소 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호.
        data — {"part_id": ..., "page_number": ..., "blocks": [...]}.
    출력: 저장된 파일 경로.
    Raises: jsonschema.ValidationError — 스키마 불일치 시.
    """
    validate(instance=data, schema=_get_schema())

    interp_path = Path(interp_path).resolve()
    file_path = _annotation_file_path(interp_path, part_id, page_num)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    file_path.write_text(text, encoding="utf-8")

    return file_path


# ──────────────────────────────────────
# 블록 탐색 헬퍼
# ──────────────────────────────────────


def _find_block(data: dict, block_id: str) -> dict | None:
    """blocks 배열에서 block_id에 해당하는 블록을 찾는다."""
    for block in data.get("blocks", []):
        if block["block_id"] == block_id:
            return block
    return None


def _ensure_block(data: dict, block_id: str) -> dict:
    """블록이 없으면 생성하여 반환한다."""
    block = _find_block(data, block_id)
    if block is None:
        block = {"block_id": block_id, "annotations": []}
        data["blocks"].append(block)
    return block


# ──────────────────────────────────────
# CRUD — annotations 배열 조작
# ──────────────────────────────────────


def _gen_annotation_id() -> str:
    """주석 ID 자동 생성. 예: ann_a1b2c3"""
    return f"ann_{uuid.uuid4().hex[:6]}"


def add_annotation(data: dict, block_id: str, annotation: dict) -> dict:
    """주석을 추가한다.

    목적: 지정된 블록의 annotations 배열에 새 주석을 추가한다.
    입력:
        data — {"part_id": ..., "page_number": ..., "blocks": [...]}.
        block_id — 대상 블록 ID.
        annotation — 주석 항목. target, type, content 등 포함.
    출력: id가 추가된 annotation dict.
    """
    if "id" not in annotation or not annotation["id"]:
        annotation["id"] = _gen_annotation_id()

    # 필수 필드 기본값 채우기
    annotation.setdefault("status", "draft")
    annotation.setdefault("reviewed_by", None)
    annotation.setdefault("reviewed_at", None)
    annotation.setdefault("annotator", {"type": "human", "model": None, "draft_id": None})

    block = _ensure_block(data, block_id)
    block["annotations"].append(annotation)
    return annotation


def update_annotation(
    data: dict, block_id: str, annotation_id: str, updates: dict
) -> dict | None:
    """주석을 수정한다.

    입력:
        updates — 수정할 필드. 예: {"content": {...}, "status": "accepted"}.
    출력: 수정된 annotation. 없으면 None.
    """
    block = _find_block(data, block_id)
    if block is None:
        return None

    for ann in block["annotations"]:
        if ann["id"] == annotation_id:
            for key, value in updates.items():
                ann[key] = value
            return ann
    return None


def remove_annotation(data: dict, block_id: str, annotation_id: str) -> bool:
    """주석을 삭제한다.

    출력: 삭제 성공 여부.
    """
    block = _find_block(data, block_id)
    if block is None:
        return False

    original_len = len(block["annotations"])
    block["annotations"] = [
        ann for ann in block["annotations"] if ann["id"] != annotation_id
    ]
    return len(block["annotations"]) < original_len


# ──────────────────────────────────────
# 필터링 + 요약
# ──────────────────────────────────────


def get_annotations_by_type(data: dict, type_id: str) -> list:
    """특정 유형의 주석만 필터링한다.

    목적: 인물만, 지명만 등 유형별 조회.
    출력: [{"block_id": ..., "annotation": {...}}, ...] — 블록 ID 포함.
    """
    results = []
    for block in data.get("blocks", []):
        for ann in block.get("annotations", []):
            if ann.get("type") == type_id:
                results.append({
                    "block_id": block["block_id"],
                    "annotation": ann,
                })
    return results


def get_annotation_summary(data: dict) -> dict:
    """주석 상태 요약을 반환한다.

    목적: 페이지 전체의 주석 현황을 한눈에 파악.
    출력: {
        "total": N,
        "by_type": {"person": N, "place": N, ...},
        "by_status": {"draft": N, "reviewed": N, "accepted": N}
    }.
    """
    by_type: dict[str, int] = {}
    by_status = {"draft": 0, "reviewed": 0, "accepted": 0}
    total = 0

    for block in data.get("blocks", []):
        for ann in block.get("annotations", []):
            total += 1
            # 유형별
            t = ann.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
            # 상태별
            s = ann.get("status", "draft")
            if s in by_status:
                by_status[s] += 1

    return {
        "total": total,
        "by_type": by_type,
        "by_status": by_status,
    }
