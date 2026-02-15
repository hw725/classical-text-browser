"""L5 표점(句讀) 코어 로직.

원문 문자열은 절대 변형하지 않는다.
표점 부호는 글자 인덱스(0-based, inclusive)에 삽입할 before/after 정보만 기록.
"""

import json
import uuid
from pathlib import Path

from jsonschema import validate

# ──────────────────────────────────────
# 스키마 로드 (모듈 레벨 캐시)
# ──────────────────────────────────────

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent / "schemas" / "interp" / "punctuation_page.schema.json"
)

_schema_cache: dict | None = None


def _get_schema() -> dict:
    """표점 JSON 스키마를 로드한다 (최초 1회만 읽음)."""
    global _schema_cache
    if _schema_cache is None:
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            _schema_cache = json.load(f)
    return _schema_cache


# ──────────────────────────────────────
# 파일 I/O
# ──────────────────────────────────────


def load_punctuation(interp_path: str | Path, part_id: str, page_num: int, block_id: str) -> dict:
    """L5 표점 파일에서 특정 블록의 표점을 로드한다.

    목적: 해석 저장소의 L5_reading/main_text에서 표점 JSON을 읽는다.
    입력:
        interp_path — 해석 저장소 경로 (예: library/interpretations/monggu_interp_001).
        part_id — 권 식별자.
        page_num — 페이지 번호.
        block_id — 블록 ID.
    출력: {"block_id": ..., "marks": [...]}.
          파일 없거나 해당 블록 없으면 빈 marks 반환.
    """
    interp_path = Path(interp_path).resolve()
    file_path = _punctuation_file_path(interp_path, part_id, page_num)

    if not file_path.exists():
        return {"block_id": block_id, "marks": []}

    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    # 파일에 저장된 block_id가 요청과 일치하면 반환
    if data.get("block_id") == block_id:
        return data

    return {"block_id": block_id, "marks": []}


def save_punctuation(
    interp_path: str | Path,
    part_id: str,
    page_num: int,
    data: dict,
) -> Path:
    """L5 표점을 스키마 검증 후 저장한다.

    목적: 표점 데이터를 JSON으로 기록한다.
    입력:
        interp_path — 해석 저장소 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호.
        data — {"block_id": ..., "marks": [...]}.
    출력: 저장된 파일 경로.
    Raises: jsonschema.ValidationError — 스키마 불일치 시.
    """
    validate(instance=data, schema=_get_schema())

    interp_path = Path(interp_path).resolve()
    file_path = _punctuation_file_path(interp_path, part_id, page_num)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    file_path.write_text(text, encoding="utf-8")

    return file_path


def _punctuation_file_path(interp_path: Path, part_id: str, page_num: int) -> Path:
    """표점 파일 경로 조립.

    컨벤션: L5_reading/main_text/{part_id}_page_{NNN}_punctuation.json
    기존 L5 경로({part_id}_page_{NNN}.json)와 충돌 방지를 위해 _punctuation 접미사 사용.
    """
    return (
        interp_path
        / "L5_reading"
        / "main_text"
        / f"{part_id}_page_{page_num:03d}_punctuation.json"
    )


# ──────────────────────────────────────
# CRUD — marks 배열 조작
# ──────────────────────────────────────


def _gen_mark_id() -> str:
    """표점 ID 자동 생성. 예: pm_a1b2c3"""
    return f"pm_{uuid.uuid4().hex[:6]}"


def add_mark(data: dict, mark: dict) -> dict:
    """표점 부호를 추가한다.

    목적: marks 배열에 새 표점을 추가한다. id가 없으면 자동 생성.
    입력:
        data — {"block_id": ..., "marks": [...]}.
        mark — {"target": {"start": N, "end": N}, "before": ..., "after": ...}.
    출력: id가 추가된 mark dict.
    """
    if "id" not in mark or not mark["id"]:
        mark["id"] = _gen_mark_id()

    data["marks"].append(mark)
    return mark


def remove_mark(data: dict, mark_id: str) -> bool:
    """표점 부호를 삭제한다.

    출력: 삭제 성공 여부.
    """
    original_len = len(data["marks"])
    data["marks"] = [m for m in data["marks"] if m["id"] != mark_id]
    return len(data["marks"]) < original_len


def update_mark(data: dict, mark_id: str, updates: dict) -> dict | None:
    """표점 부호를 수정한다.

    입력:
        updates — 수정할 필드. 예: {"after": "。"} 또는 {"target": {"start": 5, "end": 5}}.
    출력: 수정된 mark. 없으면 None.
    """
    for mark in data["marks"]:
        if mark["id"] == mark_id:
            for key, value in updates.items():
                mark[key] = value
            return mark
    return None


# ──────────────────────────────────────
# 렌더링 — 원문 + 표점 합성
# ──────────────────────────────────────


def render_punctuated_text(original_text: str, marks: list[dict]) -> str:
    """원문에 표점 부호를 삽입한 합성 텍스트를 생성한다.

    목적: GUI 미리보기용. 원문 문자열 자체는 변형하지 않고,
          marks에 지정된 위치에 부호를 삽입한 새 문자열을 반환.

    알고리즘:
        1. 각 글자 위치에 대해 before/after 버퍼를 준비
        2. marks를 순회하며 target 범위에 before/after를 기록
        3. 글자별로 before + 글자 + after를 연결

    입력:
        original_text — L4 원문 문자열. 예: "王戎簡要裴楷清通"
        marks — marks 배열.
    출력: 합성 텍스트. 예: "王戎簡要，裴楷清通。"
    """
    if not original_text:
        return ""

    n = len(original_text)
    # 각 글자 위치별 before/after 문자열 버퍼
    before_buf = [""] * n
    after_buf = [""] * n

    for mark in marks:
        target = mark.get("target", {})
        start = target.get("start", 0)
        end = target.get("end", start)

        # 범위 검증
        if start < 0 or end >= n or start > end:
            continue

        before_str = mark.get("before") or ""
        after_str = mark.get("after") or ""

        # before는 범위 시작 글자 앞에, after는 범위 끝 글자 뒤에
        before_buf[start] += before_str
        after_buf[end] += after_str

    # 합성
    parts = []
    for i, ch in enumerate(original_text):
        parts.append(before_buf[i])
        parts.append(ch)
        parts.append(after_buf[i])

    return "".join(parts)


def split_sentences(original_text: str, marks: list[dict]) -> list[dict]:
    """표점 기반으로 문장을 분리한다.

    목적: 번역(L6) 단위 생성용. 마침표(。)를 기준으로 문장 경계를 결정.
          쉼표(，)는 절 구분이므로 문장 분리에 포함하지 않는다.

    입력:
        original_text — L4 원문 문자열.
        marks — marks 배열.
    출력: [{"start": 0, "end": 3, "text": "王戎簡要"}, ...] 형태.
          start/end는 원문 글자 인덱스 (inclusive).
    """
    if not original_text:
        return []

    # 문장 종결 부호들 (after에 이 부호가 있으면 문장 끝)
    sentence_enders = {"。", "？", "！"}

    # end 인덱스 → 문장 종결 여부 매핑
    ender_positions = set()
    for mark in marks:
        after_str = mark.get("after") or ""
        if any(ch in sentence_enders for ch in after_str):
            end_pos = mark.get("target", {}).get("end", -1)
            if 0 <= end_pos < len(original_text):
                ender_positions.add(end_pos)

    # 문장 분리
    sentences = []
    sentence_start = 0

    for i in range(len(original_text)):
        if i in ender_positions:
            sentences.append({
                "start": sentence_start,
                "end": i,
                "text": original_text[sentence_start:i + 1],
            })
            sentence_start = i + 1

    # 마지막 문장 (종결 부호 없는 나머지)
    if sentence_start < len(original_text):
        sentences.append({
            "start": sentence_start,
            "end": len(original_text) - 1,
            "text": original_text[sentence_start:],
        })

    return sentences
