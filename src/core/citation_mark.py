"""인용 마크(Citation Mark) 코어 로직.

연구자가 원문이나 번역에서 논문 인용을 위해 마크한 텍스트 구절을 관리한다.
마크된 구절에 대해 L4(원문)+L5(표점)+L6(번역)+L7(주석)을 횡단하여
통합 조회하고, 학술 인용 형식으로 내보낸다.

핵심 워크플로우:
  읽기 중 텍스트 드래그 → 인용 마크 생성 → 나중에 통합 조회 → 인용 형식 내보내기

저장 위치: {interp_id}/citation_marks/{part_id}_page_{NNN}_citation_marks.json

왜 별도 디렉토리인가:
  인용 마크는 L5~L8 해석 레이어가 아니라 연구 도구다.
  해석 데이터와 섞이지 않도록 citation_marks/ 에 분리 저장한다.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import validate


# ──────────────────────────────────────
# 스키마 로드 (모듈 레벨 캐시)
# ──────────────────────────────────────

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent / "schemas" / "interp" / "citation_mark_page.schema.json"
)

_schema_cache: dict | None = None


def _get_schema() -> dict:
    """인용 마크 JSON 스키마를 로드한다 (최초 1회만 읽음)."""
    global _schema_cache
    if _schema_cache is None:
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            _schema_cache = json.load(f)
    return _schema_cache


# ──────────────────────────────────────
# 파일 I/O
# ──────────────────────────────────────


def _citation_mark_file_path(interp_path: Path, part_id: str, page_num: int) -> Path:
    """인용 마크 파일 경로 조립.

    컨벤션: citation_marks/{part_id}_page_{NNN}_citation_marks.json
    왜 이렇게 하는가:
        기존 L5/L6/L7 파일 네이밍 패턴과 동일하게 맞추되,
        L-레이어 디렉토리가 아닌 citation_marks/ 에 저장한다.
    """
    return (
        interp_path
        / "citation_marks"
        / f"{part_id}_page_{page_num:03d}_citation_marks.json"
    )


def load_citation_marks(
    interp_path: str | Path, part_id: str, page_num: int
) -> dict:
    """인용 마크 파일을 로드한다.

    목적: 해석 저장소의 citation_marks/에서 인용 마크 JSON을 읽는다.
    입력:
        interp_path — 해석 저장소 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호.
    출력: {"part_id": ..., "page_number": ..., "marks": [...]}.
          파일 없으면 빈 marks 반환.
    """
    interp_path = Path(interp_path).resolve()
    file_path = _citation_mark_file_path(interp_path, part_id, page_num)

    if not file_path.exists():
        return {
            "part_id": part_id,
            "page_number": page_num,
            "marks": [],
        }

    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


def save_citation_marks(
    interp_path: str | Path,
    part_id: str,
    page_num: int,
    data: dict,
) -> Path:
    """인용 마크를 스키마 검증 후 저장한다.

    목적: 인용 마크 데이터를 JSON으로 기록한다.
    입력:
        interp_path — 해석 저장소 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호.
        data — {"part_id": ..., "page_number": ..., "marks": [...]}.
    출력: 저장된 파일 경로.
    Raises: jsonschema.ValidationError — 스키마 불일치 시.
    """
    validate(instance=data, schema=_get_schema())

    interp_path = Path(interp_path).resolve()
    file_path = _citation_mark_file_path(interp_path, part_id, page_num)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    file_path.write_text(text, encoding="utf-8")

    return file_path


# ──────────────────────────────────────
# CRUD — marks 배열 조작
# ──────────────────────────────────────


def _gen_cite_id() -> str:
    """인용 마크 ID 자동 생성. 예: cite_a1b2c3"""
    return f"cite_{uuid.uuid4().hex[:6]}"


def add_citation_mark(data: dict, mark: dict) -> dict:
    """인용 마크를 추가한다.

    목적: marks 배열에 새 인용 마크를 추가한다.
    입력:
        data — {"part_id": ..., "page_number": ..., "marks": [...]}.
        mark — {"source": {block_id, start, end}, "marked_from": "original"|"translation",
                "source_text_snapshot": "...", ...}.
    출력: id, created_at 등이 채워진 mark dict.
    """
    if "id" not in mark or not mark["id"]:
        mark["id"] = _gen_cite_id()

    if "created_at" not in mark or not mark["created_at"]:
        mark["created_at"] = datetime.now(timezone.utc).isoformat()

    if "status" not in mark or not mark["status"]:
        mark["status"] = "active"

    # 옵션 필드 기본값
    mark.setdefault("label", None)
    mark.setdefault("tags", [])
    mark.setdefault("citation_override", None)

    data["marks"].append(mark)
    return mark


def update_citation_mark(data: dict, mark_id: str, updates: dict) -> dict | None:
    """인용 마크를 수정한다.

    입력:
        updates — 수정할 필드. 예: {"label": "핵심 논거", "tags": ["서론"]}.
    출력: 수정된 mark. 없으면 None.
    """
    for mark in data["marks"]:
        if mark["id"] == mark_id:
            for key, value in updates.items():
                # id, source, created_at는 수정 불가
                if key in ("id", "source", "created_at"):
                    continue
                mark[key] = value
            return mark
    return None


def remove_citation_mark(data: dict, mark_id: str) -> bool:
    """인용 마크를 삭제한다.

    출력: 삭제 성공 여부.
    """
    original_len = len(data["marks"])
    data["marks"] = [m for m in data["marks"] if m["id"] != mark_id]
    return len(data["marks"]) < original_len


# ──────────────────────────────────────
# 전체 인용 마크 수집
# ──────────────────────────────────────


def list_all_citation_marks(
    interp_path: str | Path, part_id: str = "main"
) -> list[dict]:
    """전체 페이지에서 인용 마크를 수집하여 반환한다.

    목적: 인용 패널에서 "전체 보기" 모드로 모든 인용 마크를 표시.
    입력:
        interp_path — 해석 저장소 경로.
        part_id — 권 식별자.
    출력: [{page_number, ...mark_fields}, ...] — 페이지 번호 포함.

    왜 이렇게 하는가:
        연구자는 문서 전체에서 마크한 구절을 한눈에 보고 싶다.
        페이지별 파일을 순회하여 통합 목록을 만든다.
    """
    interp_path = Path(interp_path).resolve()
    cite_dir = interp_path / "citation_marks"

    if not cite_dir.exists():
        return []

    all_marks = []
    for f in sorted(cite_dir.glob(f"{part_id}_page_*_citation_marks.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            page_num = data.get("page_number", 0)
            for mark in data.get("marks", []):
                mark_with_page = dict(mark)
                mark_with_page["page_number"] = page_num
                all_marks.append(mark_with_page)
        except (json.JSONDecodeError, OSError):
            continue

    return all_marks


# ──────────────────────────────────────
# 인용 컨텍스트 해석 (cross-layer resolve)
# ──────────────────────────────────────


def resolve_citation_context(
    library_path: str | Path,
    doc_id: str,
    interp_path: str | Path,
    part_id: str,
    page_num: int,
    mark: dict,
) -> dict:
    """인용 마크 1개에 대해 L4+L5+L6+L7 통합 컨텍스트를 조회한다.

    목적: 연구자가 인용 마크를 클릭했을 때, 원문/표점본/번역/주석을
          한눈에 볼 수 있도록 레이어 횡단 데이터를 수집한다.
    입력:
        library_path — 서고 경로.
        doc_id — 문헌 ID.
        interp_path — 해석 저장소 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호.
        mark — 인용 마크 dict.
    출력:
        {
            "mark": {...},              — 인용 마크 원본
            "original_text": "...",     — L4 원문 (마크 범위)
            "punctuated_text": "...",   — L5 표점 적용본 (마크 범위)
            "full_block_text": "...",   — L4 블록 전체 텍스트
            "translations": [...],     — L6 번역 (범위 겹치는 것)
            "annotations": [...],      — L7 주석 (범위 겹치는 것)
            "bibliography": {...},     — 서지정보
            "text_changed": bool,      — L4 텍스트 변경 여부
        }

    왜 이렇게 하는가:
        인용은 원문만이 아니라 표점본·번역·주석이 함께 필요하다.
        하나의 마크에서 모든 레이어를 횡단 조회하여 통합 뷰를 제공한다.
    """
    # 지연 임포트 — 순환 참조 방지
    from core.document import get_bibliography, get_page_text
    from core.entity import get_entity
    from core.punctuation import load_punctuation, render_punctuated_text
    from core.translation import load_translations
    from core.annotation import load_annotations

    library_path = Path(library_path).resolve()
    interp_path = Path(interp_path).resolve()
    doc_path = library_path / "documents" / doc_id

    source = mark.get("source", {})
    block_id = source.get("block_id", "")
    start = source.get("start", 0)
    end = source.get("end", 0)

    # ─── L4: 원문 텍스트 ───
    # TextBlock 기반 마크인지 확인:
    #   TextBlock ID (UUID)로 저장된 경우, start/end는 TextBlock.original_text 기준이다.
    #   L4 전체 페이지 텍스트에서 슬라이스하면 오프셋이 불일치한다.
    #   따라서 TextBlock entity를 먼저 조회하여 블록 텍스트를 사용한다.
    full_block_text = ""
    original_text = ""
    _used_textblock = False

    try:
        tb = get_entity(interp_path, "text_block", block_id)
        full_block_text = tb.get("original_text", "")
        _used_textblock = True
    except (FileNotFoundError, Exception):
        # TextBlock이 아닌 경우 (LayoutBlock ID 등) → L4 페이지 텍스트 폴백
        page_data = get_page_text(doc_path, part_id, page_num)
        full_block_text = page_data.get("text", "")

    if full_block_text and start <= end < len(full_block_text):
        original_text = full_block_text[start:end + 1]
    elif full_block_text and start < len(full_block_text):
        original_text = full_block_text[start:]

    # ─── L5: 표점 적용본 ───
    punctuated_text = original_text  # 기본값: 표점 없으면 원문 그대로
    try:
        punct_data = load_punctuation(interp_path, part_id, page_num, block_id)
        marks_list = punct_data.get("marks", [])
        if marks_list and full_block_text:
            # 마크 범위에 해당하는 표점만 필터하여 부분 텍스트에 적용한다.
            range_marks = _filter_marks_for_range(marks_list, start, end)
            # 범위 시작을 0으로 맞추기 위해 오프셋 조정
            adjusted_marks = _adjust_mark_offsets(range_marks, start)
            punctuated_text = render_punctuated_text(original_text, adjusted_marks)
    except Exception:
        # 표점 로드 실패 시 원문 그대로
        pass

    # ─── L6: 번역 (범위 겹치는 것) ───
    translations = []
    try:
        trans_data = load_translations(interp_path, part_id, page_num)
        for tr in trans_data.get("translations", []):
            tr_source = tr.get("source", {})
            if tr_source.get("block_id") == block_id:
                tr_start = tr_source.get("start", 0)
                tr_end = tr_source.get("end", 0)
                # 범위 겹침 검사: 두 구간이 겹치는지
                if tr_start <= end and tr_end >= start:
                    translations.append({
                        "id": tr.get("id"),
                        "source_text": tr.get("source_text", ""),
                        "translation": tr.get("translation", ""),
                        "target_language": tr.get("target_language", "ko"),
                        "status": tr.get("status", "draft"),
                    })
    except Exception:
        pass

    # ─── L7: 주석 (범위 겹치는 것) ───
    annotations = []
    try:
        ann_data = load_annotations(interp_path, part_id, page_num)
        for block in ann_data.get("blocks", []):
            if block.get("block_id") != block_id:
                continue
            for ann in block.get("annotations", []):
                ann_target = ann.get("target", {})
                ann_start = ann_target.get("start", 0)
                ann_end = ann_target.get("end", 0)
                if ann_start <= end and ann_end >= start:
                    annotations.append({
                        "id": ann.get("id"),
                        "type": ann.get("type", ""),
                        "label": ann.get("content", {}).get("label", ""),
                        "description": ann.get("content", {}).get("description", ""),
                        "dictionary": ann.get("dictionary"),
                    })
    except Exception:
        pass

    # ─── 서지정보 ───
    bibliography = {}
    try:
        bibliography = get_bibliography(doc_path)
    except Exception:
        pass

    # ─── 텍스트 변경 감지 ───
    snapshot = mark.get("source_text_snapshot", "")
    text_changed = (snapshot != original_text) if snapshot and original_text else False

    return {
        "mark": mark,
        "original_text": original_text,
        "punctuated_text": punctuated_text,
        "full_block_text": full_block_text,
        "translations": translations,
        "annotations": annotations,
        "bibliography": bibliography,
        "text_changed": text_changed,
    }


def _filter_marks_for_range(
    marks: list[dict], start: int, end: int
) -> list[dict]:
    """표점 marks에서 지정 범위(start~end)에 걸치는 것만 필터한다.

    왜 이렇게 하는가:
        전체 블록의 표점 중 인용 범위에 해당하는 것만 추출하여
        부분 텍스트에 표점을 적용해야 한다.
    """
    filtered = []
    for m in marks:
        target = m.get("target", {})
        m_start = target.get("start", 0)
        m_end = target.get("end", 0)
        # 표점이 인용 범위 안에 있으면 포함
        if m_start >= start and m_end <= end:
            filtered.append(m)
    return filtered


def _adjust_mark_offsets(marks: list[dict], offset: int) -> list[dict]:
    """표점 marks의 target 인덱스를 offset만큼 이동한다.

    왜 이렇게 하는가:
        원문의 일부만 추출하면 인덱스가 0부터 시작해야 한다.
        예: 원문 인덱스 5~10의 표점 → 0~5로 조정.
    """
    adjusted = []
    for m in marks:
        new_mark = dict(m)
        target = dict(m.get("target", {}))
        target["start"] = target.get("start", 0) - offset
        target["end"] = target.get("end", 0) - offset
        new_mark["target"] = target
        adjusted.append(new_mark)
    return adjusted


# ──────────────────────────────────────
# 인용 형식 변환
# ──────────────────────────────────────


# 인용 내보내기 기본 필드 순서
# 왜 이렇게 하는가: 한국 학술 논문의 전형적 인용 형식(저자, 서명, 작품 페이지 : 원문)을
# 기본값으로 유지하되, 사용자가 순서를 바꿀 수 있게 한다.
DEFAULT_FIELD_ORDER = [
    "author",           # 저자
    "book_volume",      # 서명 + 권수
    "work_page",        # 작품명 + 페이지(부가정보)
    "punctuated_text",  # 표점 원문
    "translation",      # 번역
]


def format_citation(
    context: dict,
    include_translation: bool = False,
    export_options: dict | None = None,
) -> str:
    """통합 컨텍스트를 학술 인용 형식 문자열로 변환한다.

    목적: 연구자가 논문에 붙여넣을 수 있는 인용 문자열 생성.
    형식: {著者}, {書名}{卷數}, {작품제목} {페이지}({부가정보}) : {표점 원문}

    입력:
        context — resolve_citation_context()의 결과.
        include_translation — True면 번역도 포함.
        export_options — 내보내기 서식 옵션 (None이면 기본값 사용).
            bracket_replace_single: "none"|"corner_to_angle"|"angle_to_corner" (「」↔〈〉).
            bracket_replace_double: "none"|"corner_to_angle"|"angle_to_corner" (『』↔《》).
            wrap_double_quotes: 원문을 \u201c\u201d로 감쌀지 여부.
            field_order: 필드 순서 배열 (DEFAULT_FIELD_ORDER 참조).
    출력: 인용 형식 문자열.

    왜 이렇게 하는가:
        사용자의 학술 논문 인용 형식:
        朴趾源, 燕岩集卷2, 答巡使書 25면(韓國文集叢刊252집, 48면) : 若吾所樂者善...
    """
    opts = export_options or {}
    field_order = opts.get("field_order") or DEFAULT_FIELD_ORDER

    bib = context.get("bibliography", {})
    mark = context.get("mark", {})
    override = mark.get("citation_override") or {}

    # ── 각 필드 추출 (citation_override 우선) ──
    # creator는 스키마상 object({name, role, period, ...}) 또는 null
    creator = bib.get("creator")
    if isinstance(creator, dict):
        author = creator.get("name", "") or ""
    elif isinstance(creator, str):
        author = creator
    else:
        author = ""
    book_title = bib.get("title", "") or ""

    # volume: bibliography에서 또는 part_id에서
    volume = ""
    physical = bib.get("physical_description", {})
    if isinstance(physical, dict):
        volume = physical.get("volumes", "")

    work_title = override.get("work_title") or ""
    page_ref = override.get("page_ref") or ""
    supplementary = override.get("supplementary") or ""

    # 페이지 번호 자동 (override 없을 때)
    if not page_ref:
        page_num = mark.get("page_number") or context.get("mark", {}).get("source", {})
        if isinstance(page_num, int):
            page_ref = f"{page_num}면"

    punctuated_text = context.get("punctuated_text", "")

    # ── 제목 기호 치환 (표점본 원문에 적용, 양방향) ──
    # 값은 "none" | "corner_to_angle" | "angle_to_corner" (하위 호환: True→corner_to_angle)
    brs = opts.get("bracket_replace_single")
    if brs is True:
        brs = "corner_to_angle"
    if brs == "corner_to_angle":
        punctuated_text = punctuated_text.replace("「", "〈").replace("」", "〉")
    elif brs == "angle_to_corner":
        punctuated_text = punctuated_text.replace("〈", "「").replace("〉", "」")

    brd = opts.get("bracket_replace_double")
    if brd is True:
        brd = "corner_to_angle"
    if brd == "corner_to_angle":
        punctuated_text = punctuated_text.replace("『", "《").replace("』", "》")
    elif brd == "angle_to_corner":
        punctuated_text = punctuated_text.replace("《", "『").replace("》", "』")

    # ── 각 필드를 개별 조립하여 dict에 담기 ──
    field_values: dict[str, str] = {}

    if author:
        field_values["author"] = author

    title_part = book_title
    if volume:
        title_part += str(volume)
    if title_part:
        field_values["book_volume"] = title_part

    if work_title:
        page_info = work_title
        if page_ref:
            page_info += f" {page_ref}"
        if supplementary:
            page_info += f"({supplementary})"
        field_values["work_page"] = page_info
    elif page_ref:
        page_info = page_ref
        if supplementary:
            page_info += f"({supplementary})"
        field_values["work_page"] = page_info

    if punctuated_text:
        display_text = punctuated_text
        if opts.get("wrap_double_quotes"):
            display_text = f"\u201c{display_text}\u201d"
        field_values["punctuated_text"] = display_text

    if include_translation and context.get("translations"):
        trans_texts = [
            t["translation"] for t in context["translations"]
            if t.get("translation")
        ]
        if trans_texts:
            field_values["translation"] = " ".join(trans_texts)

    # ── field_order 순서대로 조합 ──
    # 구분자 규칙:
    #   연속된 서지정보 필드(author, book_volume, work_page) → 콤마(, )로 연결
    #   서지정보 ↔ 원문(punctuated_text) → 콜론( : )으로 구분
    #   번역(translation) → 개행(\n)으로 구분
    # 왜 이렇게 하는가: 사용자가 원문을 앞에 배치해도
    # "若吾所樂者善也 : 朴趾源, 燕岩集" 처럼 자연스럽게 연결되도록.
    segments: list[tuple[str, str]] = []  # (type, value) — "bib" / "text" / "trans"

    for fid in field_order:
        val = field_values.get(fid)
        if not val:
            continue
        if fid == "punctuated_text":
            segments.append(("text", val))
        elif fid == "translation":
            segments.append(("trans", val))
        else:
            # 연속된 bib 필드는 하나로 병합 (콤마 연결)
            if segments and segments[-1][0] == "bib":
                segments[-1] = ("bib", segments[-1][1] + ", " + val)
            else:
                segments.append(("bib", val))

    # 세그먼트를 적절한 구분자로 연결
    parts: list[str] = []
    for i, (seg_type, seg_val) in enumerate(segments):
        if i == 0:
            parts.append(seg_val)
        elif seg_type == "trans" or segments[i - 1][0] == "trans":
            parts.append("\n" + seg_val)
        elif seg_type != segments[i - 1][0]:
            # bib↔text 전환 → 콜론
            parts.append(" : " + seg_val)
        else:
            parts.append(", " + seg_val)

    return "".join(parts)


def export_citations(
    contexts: list[dict],
    include_translation: bool = True,
    export_options: dict | None = None,
) -> str:
    """여러 인용 컨텍스트를 일괄 변환한다.

    목적: 선택한 인용 마크들을 한 번에 내보내기.
    입력:
        contexts — resolve_citation_context() 결과 리스트.
        include_translation — 번역 포함 여부.
        export_options — 내보내기 서식 옵션 (format_citation 참조).
    출력: 줄바꿈으로 구분된 인용 문자열.
    """
    citations = []
    for ctx in contexts:
        citation = format_citation(
            ctx,
            include_translation=include_translation,
            export_options=export_options,
        )
        if citation:
            citations.append(citation)

    return "\n\n".join(citations)
