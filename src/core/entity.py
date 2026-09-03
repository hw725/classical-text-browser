"""코어 스키마 엔티티 관리 모듈.

해석 저장소(Interpretation) 내부에서 코어 스키마 엔티티
(Work, TextBlock, Tag, Concept, Agent, Relation)를 생성·조회·수정한다.
core-schema-v1.3.md 및 operation-rules-v1.0.md에 따른다.

    {interp_id}/
    └── core_entities/
        ├── works/{uuid}.json
        ├── blocks/{uuid}.json
        ├── tags/{uuid}.json
        ├── concepts/{uuid}.json
        ├── agents/{uuid}.json
        └── relations/{uuid}.json

왜 이렇게 하는가:
    - 코어 스키마 엔티티는 해석 작업의 산물이므로 해석 저장소 안에 둔다.
    - 엔티티는 절대 삭제하지 않고 상태(status) 전이만 허용한다 (operation-rules 2.4).
    - 모든 엔티티는 jsonschema로 검증한 후 저장한다.
    - 파일명은 엔티티의 id 필드와 반드시 일치해야 한다 (operation-rules 2.1).
"""

import json
import logging
import uuid
from pathlib import Path

import git
import jsonschema

logger = logging.getLogger(__name__)

# ──────────────────────────
# 상수 정의
# ──────────────────────────

# 엔티티 유형 → 서브디렉터리 이름 매핑
ENTITY_TYPES: dict[str, str] = {
    "work": "works",
    "text_block": "blocks",
    "tag": "tags",
    "concept": "concepts",
    "agent": "agents",
    "relation": "relations",
}

# 상태 전이 규칙 (operation-rules 2.4: 삭제 금지, 전이만 허용)
VALID_STATUS_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["active", "deprecated", "archived"],
    "active": ["deprecated", "archived"],
    "deprecated": ["archived"],
    "archived": [],  # 최종 상태 — 더 이상 전이 불가
}

# 엔티티 유형 → JSON 스키마 파일명
SCHEMA_FILES: dict[str, str] = {
    "work": "work.schema.json",
    "text_block": "text_block.schema.json",
    "tag": "tag.schema.json",
    "concept": "concept.schema.json",
    "agent": "agent.schema.json",
    "relation": "relation.schema.json",
}


# ──────────────────────────
# 내부 유틸리티
# ──────────────────────────


def _entity_dir_path(interp_path: Path, entity_type: str) -> Path:
    """엔티티 유형의 저장 디렉터리 경로를 반환한다. 디렉터리가 없으면 생성한다.

    목적: core_entities/{subdir}/ 경로를 일관되게 관리한다.
    입력:
        interp_path — 해석 저장소 루트 경로.
        entity_type — ENTITY_TYPES의 키 (work, text_block 등).
    출력: Path 객체.
    왜 이렇게 하는가:
        기존 해석 저장소에 core_entities가 없을 수 있으므로 lazy 생성한다.
    """
    if entity_type not in ENTITY_TYPES:
        raise ValueError(
            f"지원하지 않는 엔티티 유형입니다: '{entity_type}'\n"
            f"→ 해결: 다음 중 하나를 사용하세요: {', '.join(ENTITY_TYPES.keys())}"
        )
    subdir = ENTITY_TYPES[entity_type]
    dir_path = interp_path / "core_entities" / subdir
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def _validate_entity(entity_type: str, data: dict) -> None:
    """엔티티 데이터를 JSON 스키마로 검증한다.

    목적: 잘못된 데이터가 저장되지 않도록 사전 검증한다.
    입력:
        entity_type — 엔티티 유형 (ENTITY_TYPES 키).
        data — 검증할 엔티티 딕셔너리.
    왜 이렇게 하는가:
        document.py의 save_page_layout() 378~396행과 동일한 패턴으로,
        schemas/core/ 디렉터리의 JSON 스키마를 사용하여 저장 전 검증한다.

    Raises:
        jsonschema.ValidationError: 스키마 검증 실패 시.
    """
    schema_file = SCHEMA_FILES.get(entity_type)
    if not schema_file:
        return

    schema_path = Path(__file__).resolve().parent.parent.parent / "schemas" / "core" / schema_file
    if schema_path.exists():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        # _meta 등 내부 필드는 검증에서 제외
        validate_data = {k: v for k, v in data.items() if not k.startswith("_")}
        jsonschema.validate(instance=validate_data, schema=schema)
    else:
        logger.warning(
            "스키마 파일이 없어 '%s' 엔티티 검증을 건너뜁니다: %s",
            entity_type,
            schema_path,
        )


def _write_json(path: Path, data: dict) -> None:
    """JSON을 원자적으로 저장한다. 정본은 core.document.write_json_atomic이다.

    왜 위임하는가: 같은 함수가 다섯 모듈에 복제돼 있었다. 한 곳만 안전하게
    고치면 나머지 넷은 그대로 위험한 채 남는다.
    """
    from .document import write_json_atomic

    write_json_atomic(path, data)


def _get_source_head_commit(doc_path: Path) -> str:
    """원본 저장소의 HEAD 커밋 해시를 반환한다.

    왜 이렇게 하는가:
        TextBlock의 source_ref.commit에 사용된다.
        원본에 git이 없으면 'no_git'을 반환하여 방어한다.
    """
    try:
        repo = git.Repo(doc_path)
        return repo.head.commit.hexsha
    except (git.InvalidGitRepositoryError, ValueError):
        return "no_git"


# ──────────────────────────
# 공개 API 함수
# ──────────────────────────


# ──────────────────────────
# text_block = 경계 목록의 보기 (D-092)
# ──────────────────────────
#
# v1.3부터 글 단위의 정본은 core_entities/boundaries/{doc}__{part}.json이다. 이 모듈의
# text_block 조회·생성·갱신은 그 목록을 읽고 쓰는 얇은 층이며, blocks/*.json은 만들지
# 않는다.
# 옛 저장소(blocks/만 있는)는 처음 읽을 때 한 번 옮긴다(migrate_from_blocks —
# 옛 파일은 이름만 바꿈).


def _library_root(interp_path: str | Path) -> Path:
    """해석 저장소 경로에서 서고 루트(…/interpretations/{id} → …)."""
    return Path(interp_path).resolve().parent.parent


def _ensure_boundaries(interp_path: Path) -> None:
    from core.boundaries import migrate_from_blocks, needs_migration

    if needs_migration(interp_path):
        result = migrate_from_blocks(interp_path, _library_root(interp_path))
        logger.info("TextBlock → 경계 목록 마이그레이션: %s", result)
        # 해석 저장소는 Git이다 — 옮긴 상태를 한 커밋으로 남겨야 되돌릴 수 있다.
        try:
            from core.interpretation import git_commit_interpretation

            git_commit_interpretation(
                interp_path,
                f"chore: TextBlock → 경계 목록 마이그레이션 (D-092) — {len(result['parts'])}권",
            )
        except Exception as e:  # noqa: BLE001 — 커밋 실패가 읽기를 막으면 안 된다
            logger.warning("마이그레이션 커밋 실패: %s", e)


_PART_LINES_CACHE: dict[tuple, tuple[float, tuple]] = {}
_PART_LINES_TTL = 3.0  # 초. 화면 한 번 그릴 때 쪽마다 오는 요청들이 같은 208쪽을 되풀이해 읽지 않게


def _part_lines(interp_path: Path, document_id: str, part_id: str):
    """그 권의 L4 행 목록과 쪽 텍스트. 문헌이 없거나 L4가 없으면 빈 것.

    짧은 캐시(3초): 편성 탭이 쪽마다 `entities/text_block?page=` 요청을 보내고 그때마다 권 전체
    확정본(208쪽 0.6초)을 읽었다. 교정 저장은 3초 뒤에 반영된다 — 같은 화면 안의 되풀이만 막는다.
    """
    import time

    from core.segmentation import collect_document_lines

    key = (str(Path(interp_path).resolve()), document_id, part_id)
    hit = _PART_LINES_CACHE.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < _PART_LINES_TTL:
        return hit[1]
    doc_path = _library_root(interp_path) / "documents" / document_id
    if not doc_path.exists():
        return [], {}
    try:
        result = collect_document_lines(doc_path, part_id, None)
    except Exception as ex:  # noqa: BLE001 — L4가 없으면 본문 없는 단위로 보인다
        logger.warning("확정본을 읽지 못했습니다 (%s/%s): %s", document_id, part_id, ex)
        result = ([], {})
    _PART_LINES_CACHE[key] = (now, result)
    return result


def _text_block_view(interp_path: str | Path) -> list[dict]:
    """모든 권의 경계 목록에서 TextBlock 모양의 단위 목록을 만든다(읽기 전용)."""
    from core.boundaries import compute_units, list_boundary_parts, load_boundaries

    interp_path = Path(interp_path).resolve()
    _ensure_boundaries(interp_path)
    from core.boundaries import rematch, save_boundaries

    units: list[dict] = []
    for doc_id, part_id in list_boundary_parts(interp_path):
        lines, page_texts = _part_lines(interp_path, doc_id, part_id)
        data = load_boundaries(interp_path, doc_id, part_id)
        # L4가 바뀐 뒤(교감) 오프셋 대신 anchor_text로 자리를 다시 찾는다(D-092 결정 4).
        head = _document_head(_library_root(interp_path) / "documents" / doc_id)
        if page_texts and head and any(b.get("l4_commit") != head for b in data["boundaries"]):
            if rematch(data, page_texts, head):
                save_boundaries(interp_path, data)
        units.extend(compute_units(data, lines, page_texts))
    return units


def _document_head(doc_path: Path) -> str | None:
    """원본 저장소의 현재 커밋(없으면 None)."""
    try:
        import git as _git

        return _git.Repo(doc_path).head.commit.hexsha
    except Exception:  # noqa: BLE001
        return None


def _find_boundary_home(interp_path: Path, boundary_id: str):
    """id가 든 경계 파일의 (data, item). 없으면 (None, None)."""
    from core.boundaries import find_boundary, list_boundary_parts, load_boundaries

    for doc_id, part_id in list_boundary_parts(interp_path):
        data = load_boundaries(interp_path, doc_id, part_id)
        item = find_boundary(data, boundary_id)
        if item is not None:
            return data, item
    return None, None


def _create_boundary_from_textblock(interp_path: Path, data: dict) -> dict:
    """TextBlock 모양의 입력(apply·from-source·split이 만들던 것)을 경계 하나로 저장한다."""
    from core.boundaries import (
        boundaries_file,
        insert_boundary,
        load_boundaries,
        new_boundary,
        position_from_char,
        save_boundaries,
    )

    refs = data.get("source_refs") or ([data["source_ref"]] if data.get("source_ref") else [])
    refs = [r for r in refs if r and r.get("page")]
    if not refs:
        raise ValueError("TextBlock을 경계로 만들려면 출처(source_refs의 쪽)가 필요합니다.")
    r0 = refs[0]
    doc_id = r0.get("document_id")
    part_id = r0.get("part_id") or (data.get("metadata") or {}).get("part_id") or "vol1"
    if not doc_id:
        raise ValueError("source_refs에 document_id가 없습니다.")
    _lines, page_texts = _part_lines(interp_path, doc_id, part_id)
    page = int(r0["page"])
    cr = r0.get("char_range")
    if cr and page_texts.get(page) is not None:
        pos = position_from_char(page_texts, page, int(cr[0]))
    else:
        pos = {"page": page, "line": 0, "offset": 0}
    meta = data.get("metadata") or {}
    anchor = meta.get("anchor") or {}
    item = new_boundary(
        start=pos,
        level=int(anchor.get("level") or meta.get("level") or 2),
        title=meta.get("title") or (data.get("original_text") or "").strip()[:20] or None,
        kind=anchor.get("kind") or meta.get("kind") or "manual",
        work_id=data.get("work_id"),
        status=data.get("status", "draft"),
        anchor_status=anchor.get("status") or "approved",
        boundary_id=data.get("id"),
        page_texts=page_texts or None,
        l4_commit=anchor.get("l4_commit") or r0.get("commit"),
        confidence=anchor.get("confidence"),
        reasons=anchor.get("reasons"),
        bbox=anchor.get("bbox"),
    )
    item["notes"] = data.get("notes")
    rest = {
        k: v
        for k, v in meta.items()
        if k not in ("title", "kind", "anchor", "part_id", "segmentation", "level")
    }
    item["metadata"] = rest or None
    bdata = load_boundaries(interp_path, doc_id, part_id)
    kept = insert_boundary(bdata, item)  # 같은 자리·층위가 이미 있으면 그것(중복 없음)
    save_boundaries(interp_path, bdata)
    rel = boundaries_file(interp_path, doc_id, part_id).relative_to(interp_path).as_posix()
    return {
        "status": "created" if kept is item else "exists",
        "entity_type": "text_block",
        "id": kept["id"],
        "file_path": rel,
    }


def _update_boundary_from_textblock(interp_path: Path, entity_id: str, updates: dict) -> dict:
    """TextBlock 갱신 요청(status·notes·metadata·work_id)을 경계 항목에 적용한다."""
    from core.boundaries import save_boundaries, update_boundary

    data, item = _find_boundary_home(interp_path, entity_id)
    if item is None:
        raise FileNotFoundError(
            f"text_block 엔티티를 찾을 수 없습니다: {entity_id}\n"
            "→ 해결: 엔티티 ID와 유형을 확인하세요."
        )
    if "id" in updates and updates["id"] != entity_id:
        raise ValueError(
            "엔티티 ID는 변경할 수 없습니다.\n→ 해결: id 필드를 updates에서 제거하세요."
        )
    if "status" in updates and updates["status"] != item.get("status"):
        old_status = item.get("status", "draft")
        allowed = VALID_STATUS_TRANSITIONS.get(old_status, [])
        if updates["status"] not in allowed:
            raise ValueError(
                f"상태 전이가 허용되지 않습니다: '{old_status}' → '{updates['status']}'\n"
                f"→ 해결: '{old_status}'에서 가능한 전이: {allowed or '없음 (최종 상태)'}"
            )
    fields: dict = {}
    for k in ("status", "notes", "work_id"):
        if k in updates:
            fields[k] = updates[k]
    # 옛 계약: source_refs를 바꾸면 «위치를 옮긴다». 첫 참조의 쪽·char_range[0]이 새 시작이다.
    # (끝은 저장하지 않으므로 char_range[1]은 무시한다 — 다음 경계가 정한다.)
    refs = [r for r in (updates.get("source_refs") or []) if r and r.get("page")]
    if refs:
        from core.boundaries import move_boundary, position_from_char

        r0 = refs[0]
        _lines, page_texts = _part_lines(interp_path, data["document_id"], data["part_id"])
        cr = r0.get("char_range")
        page = int(r0["page"])
        if cr and page_texts.get(page) is not None:
            pos = position_from_char(page_texts, page, int(cr[0]))
        else:
            pos = {"page": page, "line": 0, "offset": 0}
        move_boundary(data, entity_id, pos, page_texts or None)
    meta = updates.get("metadata")
    if isinstance(meta, dict):
        if "title" in meta:
            fields["title"] = meta["title"]
        if "kind" in meta:
            fields["kind"] = meta["kind"]
        if "level" in meta:
            fields["level"] = int(meta["level"])
        anchor = meta.get("anchor") or {}
        if "status" in anchor:
            fields["anchor_status"] = anchor["status"]
        rest = {
            k: v
            for k, v in meta.items()
            if k not in ("title", "kind", "anchor", "part_id", "segmentation", "level")
        }
        if rest:
            fields["metadata"] = {**(item.get("metadata") or {}), **rest}
    update_boundary(data, entity_id, fields)
    save_boundaries(interp_path, data)
    return {"status": "updated", "entity_type": "text_block", "id": entity_id}


def create_entity(
    interp_path: str | Path,
    entity_type: str,
    data: dict,
) -> dict:
    """새 엔티티를 생성하여 JSON 파일로 저장한다.

    목적: 코어 스키마 엔티티를 해석 저장소에 추가한다.
    입력:
        interp_path — 해석 저장소 경로.
        entity_type — 엔티티 유형 (work, text_block, tag, concept, agent, relation).
        data — 엔티티 딕셔너리. id가 없으면 UUID를 자동 생성한다.
    출력: {"status": "created", "entity_type": ..., "id": ..., "file_path": ...}

    왜 이렇게 하는가:
        - UUID 자동 생성으로 연구자가 ID를 신경 쓰지 않아도 된다.
        - 스키마 검증 후 저장하여 데이터 무결성을 보장한다.
        - 동일 ID의 엔티티가 이미 있으면 오류를 발생시킨다 (operation-rules 2.1).
    """
    interp_path = Path(interp_path).resolve()
    if entity_type == "text_block":
        _ensure_boundaries(interp_path)
        return _create_boundary_from_textblock(interp_path, data)

    # id 자동 생성
    if "id" not in data or not data["id"]:
        data["id"] = str(uuid.uuid4())

    # 스키마 검증
    _validate_entity(entity_type, data)

    # 파일 경로 결정
    dir_path = _entity_dir_path(interp_path, entity_type)
    file_path = dir_path / f"{data['id']}.json"

    if file_path.exists():
        raise FileExistsError(
            f"동일한 ID의 엔티티가 이미 존재합니다: {data['id']}\n"
            "→ 해결: 다른 ID를 사용하거나 기존 엔티티를 수정하세요."
        )

    _write_json(file_path, data)

    relative_path = file_path.relative_to(interp_path).as_posix()
    return {
        "status": "created",
        "entity_type": entity_type,
        "id": data["id"],
        "file_path": relative_path,
    }


def get_entity(
    interp_path: str | Path,
    entity_type: str,
    entity_id: str,
) -> dict:
    """단일 엔티티를 ID로 조회한다.

    목적: 엔티티 상세 조회.
    입력:
        interp_path — 해석 저장소 경로.
        entity_type — 엔티티 유형.
        entity_id — UUID 문자열.
    출력: 엔티티 딕셔너리.

    Raises:
        FileNotFoundError: 엔티티를 찾을 수 없을 때.
    """
    interp_path = Path(interp_path).resolve()
    if entity_type == "text_block":
        hit = next((u for u in _text_block_view(interp_path) if u.get("id") == entity_id), None)
        if hit is None:
            raise FileNotFoundError(
                f"text_block 엔티티를 찾을 수 없습니다: {entity_id}\n"
                "→ 해결: 엔티티 ID와 유형을 확인하세요."
            )
        return hit
    dir_path = _entity_dir_path(interp_path, entity_type)
    file_path = dir_path / f"{entity_id}.json"

    if not file_path.exists():
        raise FileNotFoundError(
            f"{entity_type} 엔티티를 찾을 수 없습니다: {entity_id}\n"
            "→ 해결: 엔티티 ID와 유형을 확인하세요."
        )

    return json.loads(file_path.read_text(encoding="utf-8"))


def update_entity(
    interp_path: str | Path,
    entity_type: str,
    entity_id: str,
    updates: dict,
) -> dict:
    """기존 엔티티를 수정한다 (얕은 병합).

    목적: 엔티티 필드를 갱신한다. 삭제는 절대 하지 않는다.
    입력:
        interp_path — 해석 저장소 경로.
        entity_type — 엔티티 유형.
        entity_id — UUID 문자열.
        updates — 갱신할 필드 딕셔너리. 기존 값에 덮어쓴다.
    출력: {"status": "updated", "entity_type": ..., "id": ...}

    왜 이렇게 하는가:
        - 상태 전이 규칙(VALID_STATUS_TRANSITIONS)을 검증하여
          잘못된 전이를 방지한다 (operation-rules 2.4).
        - 병합 후 스키마 검증을 한 번 더 수행한다.
        - id 필드는 변경할 수 없다.
    """
    interp_path = Path(interp_path).resolve()
    if entity_type == "text_block":
        _ensure_boundaries(interp_path)
        return _update_boundary_from_textblock(interp_path, entity_id, updates)
    dir_path = _entity_dir_path(interp_path, entity_type)
    file_path = dir_path / f"{entity_id}.json"

    if not file_path.exists():
        raise FileNotFoundError(
            f"{entity_type} 엔티티를 찾을 수 없습니다: {entity_id}\n"
            "→ 해결: 엔티티 ID와 유형을 확인하세요."
        )

    existing = json.loads(file_path.read_text(encoding="utf-8"))

    # id 변경 금지
    if "id" in updates and updates["id"] != entity_id:
        raise ValueError(
            "엔티티 ID는 변경할 수 없습니다.\n→ 해결: id 필드를 updates에서 제거하세요."
        )

    # 상태 전이 검증
    if "status" in updates and updates["status"] != existing.get("status"):
        old_status = existing.get("status", "draft")
        new_status = updates["status"]
        allowed = VALID_STATUS_TRANSITIONS.get(old_status, [])
        if new_status not in allowed:
            raise ValueError(
                f"상태 전이가 허용되지 않습니다: '{old_status}' → '{new_status}'\n"
                f"→ 해결: '{old_status}'에서 가능한 전이: {allowed or '없음 (최종 상태)'}"
            )

    # 얕은 병합
    merged = {**existing, **updates}
    merged["id"] = entity_id  # id 보존

    # 병합 후 스키마 재검증
    _validate_entity(entity_type, merged)

    _write_json(file_path, merged)

    return {
        "status": "updated",
        "entity_type": entity_type,
        "id": entity_id,
    }


def list_entities(
    interp_path: str | Path,
    entity_type: str,
    filters: dict | None = None,
) -> list[dict]:
    """특정 유형의 엔티티 목록을 반환한다.

    목적: 엔티티 목록 조회 (선택적 필터링).
    입력:
        interp_path — 해석 저장소 경로.
        entity_type — 엔티티 유형.
        filters — 선택적 필터. 예: {"status": "draft"}, {"block_id": "uuid"}.
    출력: 엔티티 딕셔너리의 리스트.

    왜 이렇게 하는가:
        하단 패널에서 유형별 엔티티 목록을 표시할 때 사용한다.
        필터가 있으면 해당 필드가 일치하는 엔티티만 반환한다.
    """
    interp_path = Path(interp_path).resolve()
    if entity_type == "text_block":
        entities = _text_block_view(interp_path)
        if filters:
            entities = [e for e in entities if all(e.get(k) == v for k, v in filters.items())]
        return entities
    dir_path = _entity_dir_path(interp_path, entity_type)

    entities = []
    for f in dir_path.glob("*.json"):
        try:
            entity = json.loads(f.read_text(encoding="utf-8"))
            entities.append(entity)
        except (json.JSONDecodeError, OSError):
            continue

    # 필터 적용
    if filters:
        filtered = []
        for entity in entities:
            match = True
            for key, value in filters.items():
                if entity.get(key) != value:
                    match = False
                    break
            if match:
                filtered.append(entity)
        entities = filtered

    return entities


def list_entities_for_page(
    interp_path: str | Path,
    document_id: str,
    page_num: int,
) -> dict:
    """현재 페이지와 관련된 모든 엔티티를 조회한다.

    목적: 하단 패널 "엔티티" 탭에서 현재 페이지에 관련된 엔티티를 표시한다.
    입력:
        interp_path — 해석 저장소 경로.
        document_id — 원본 문헌 ID.
        page_num — 페이지 번호 (1-based).
    출력: {
        "blocks": [...], "tags": [...], "concepts": [...],
        "agents": [...], "relations": [...], "works": [...]
    }

    왜 이렇게 하는가:
        - 먼저 source_ref.page가 일치하는 TextBlock을 찾고,
        - 그 TextBlock의 block_id를 가진 Tag를 찾고,
        - 관련된 Relation, Agent, Concept을 찾아 함께 반환한다.
        - 연구자가 현재 보고 있는 페이지의 맥락에서 엔티티를 파악할 수 있게 한다.
    """
    interp_path = Path(interp_path).resolve()

    # 1) TextBlock: source_ref.document_id == document_id and source_ref.page == page_num
    all_blocks = list_entities(interp_path, "text_block")
    page_blocks = []
    for blk in all_blocks:
        ref = blk.get("source_ref")
        if ref and ref.get("document_id") == document_id and ref.get("page") == page_num:
            page_blocks.append(blk)

    block_ids = {blk["id"] for blk in page_blocks}

    # 2) Tag: block_id가 page_blocks에 해당
    all_tags = list_entities(interp_path, "tag")
    page_tags = [t for t in all_tags if t.get("block_id") in block_ids]

    # 3) Relation: subject_id 또는 object_id가 관련 엔티티 ID에 해당
    all_relations = list_entities(interp_path, "relation")
    # 관련 ID 집합: blocks + tags에서 연결된 것들
    related_ids = block_ids.copy()
    related_ids.update(t["id"] for t in page_tags)

    page_relations = []
    agent_ids = set()
    concept_ids = set()
    for rel in all_relations:
        # evidence_blocks가 page_blocks를 포함하거나, subject/object가 관련 ID
        evidence = set(rel.get("evidence_blocks") or [])
        if (
            evidence & block_ids
            or rel.get("subject_id") in related_ids
            or rel.get("object_id") in related_ids
        ):
            page_relations.append(rel)
            # 관련된 Agent/Concept/Block ID 수집 (.get()으로 KeyError 방지)
            subj_id = rel.get("subject_id")
            obj_id = rel.get("object_id")
            if rel.get("subject_type") == "agent" and subj_id:
                agent_ids.add(subj_id)
            elif rel.get("subject_type") == "concept" and subj_id:
                concept_ids.add(subj_id)
            if rel.get("object_type") == "agent" and obj_id:
                agent_ids.add(obj_id)
            elif rel.get("object_type") == "concept" and obj_id:
                concept_ids.add(obj_id)
            elif rel.get("object_type") == "block" and obj_id:
                block_ids.add(obj_id)

    # 4) Agent / Concept: 관련 ID로 필터
    all_agents = list_entities(interp_path, "agent")
    all_concepts = list_entities(interp_path, "concept")

    # Tag에서 참조된 concept도 포함 (promote된 경우)
    for tag in page_tags:
        meta = tag.get("metadata") or {}
        if meta.get("promoted_to_concept_id"):
            concept_ids.add(meta["promoted_to_concept_id"])

    page_agents = [a for a in all_agents if a["id"] in agent_ids]
    page_concepts = [c for c in all_concepts if c["id"] in concept_ids]

    # agent_ids/concept_ids에 없더라도 scope_work가 일치하는 것은 포함하지 않음
    # (너무 많아질 수 있으므로, 페이지 필터는 관계로 연결된 것만)

    # 5) Work: blocks의 work_id
    work_ids = {blk.get("work_id") for blk in page_blocks if blk.get("work_id")}
    all_works = list_entities(interp_path, "work")
    page_works = [w for w in all_works if w["id"] in work_ids]

    return {
        "works": page_works,
        "blocks": page_blocks,
        "tags": page_tags,
        "concepts": page_concepts,
        "agents": page_agents,
        "relations": page_relations,
    }


def promote_tag_to_concept(
    interp_path: str | Path,
    tag_id: str,
    label: str | None = None,
    scope_work: str | None = None,
    description: str | None = None,
) -> dict:
    """Tag를 Concept으로 승격한다 (Promotion Flow).

    목적: 연구자가 확인한 Tag를 의미 엔티티(Concept)로 격상한다.
    입력:
        interp_path — 해석 저장소 경로.
        tag_id — 승격할 Tag의 UUID.
        label — Concept의 라벨. 미지정 시 Tag의 surface를 사용.
        scope_work — Concept이 유효한 Work의 ID. null이면 전역.
        description — 학술적 설명.
    출력: 생성된 Concept 딕셔너리.

    왜 이렇게 하는가:
        core-schema-v1.3.md 섹션 7: Tag → Concept 승격은
        연구자의 명시적 판단으로만 이루어진다.
        Tag 자체는 변경하지 않는다 (연구자가 별도로 상태를 결정).
        Concept의 metadata에 promoted_from_tag_id를 기록하여 출처를 추적한다.
    """
    interp_path = Path(interp_path).resolve()

    # Tag 읽기
    tag = get_entity(interp_path, "tag", tag_id)

    # Concept 라벨: 비어있으면 승격 불가
    effective_label = label or tag.get("surface", "")
    if not effective_label:
        raise ValueError(
            f"Concept 라벨을 결정할 수 없습니다. "
            f"Tag(id={tag_id})에 surface가 없고, label 인수도 지정되지 않았습니다."
        )

    # Concept 생성
    concept_data = {
        "id": str(uuid.uuid4()),
        "label": effective_label,
        "scope_work": scope_work,
        "description": description,
        "concept_features": None,
        "status": "draft",
        "metadata": {
            "promoted_from_tag_id": tag_id,
        },
    }

    result = create_entity(interp_path, "concept", concept_data)
    return {**result, "concept": concept_data}


def create_textblock_from_source(
    interp_path: str | Path,
    library_path: str | Path,
    document_id: str,
    part_id: str,
    page_num: int,
    layout_block_id: str | None,
    original_text: str,
    work_id: str,
    sequence_index: int,
) -> dict:
    """L4 확정 텍스트에서 TextBlock을 생성한다 (source_ref 자동 채움).

    목적: 연구자가 "TextBlock 만들기" 버튼을 클릭하면,
          현재 문서·페이지·블록 정보에서 source_ref를 자동으로 채워
          TextBlock을 생성한다.
    입력:
        interp_path — 해석 저장소 경로.
        library_path — 서고 루트 경로.
        document_id — 원본 문헌 ID.
        part_id — 파트 ID (예: vol1).
        page_num — 페이지 번호 (1-based).
        layout_block_id — L3 LayoutBlock ID (없으면 null).
        original_text — L4 확정 텍스트.
        work_id — 소속 Work의 UUID.
        sequence_index — 작품 내 순서 (0-based).
    출력: 생성된 TextBlock 딕셔너리.

    왜 이렇게 하는가:
        D-005: source_ref로 TextBlock이 원본 저장소의 어디에서 왔는지를
        항상 추적해야 한다. commit 해시를 기록하여 정확한 시점을 고정한다.
    """
    interp_path = Path(interp_path).resolve()
    library_path = Path(library_path).resolve()
    doc_path = library_path / "documents" / document_id

    # 원본 저장소의 현재 HEAD 커밋 해시
    commit_hash = _get_source_head_commit(doc_path)

    single_ref = {
        "document_id": document_id,
        "page": page_num,
        "layout_block_id": layout_block_id,
        "layer": "L4",
        "commit": commit_hash,
    }

    text_block_data = {
        "id": str(uuid.uuid4()),
        "work_id": work_id,
        "sequence_index": sequence_index,
        "original_text": original_text,
        "normalized_text": None,
        "source_ref": single_ref,
        "source_refs": [{**single_ref, "char_range": None}],
        "status": "draft",
        "notes": None,
        "metadata": {
            "part_id": part_id,
        },
    }

    result = create_entity(interp_path, "text_block", text_block_data)
    return {**result, "text_block": text_block_data}


def auto_create_work(
    interp_path: str | Path,
    library_path: str | Path,
    document_id: str,
) -> dict:
    """문헌의 메타데이터로부터 Work 엔티티를 자동 생성한다.

    목적: TextBlock을 만들기 전에 소속 Work가 필요한데,
          연구자가 직접 만들지 않아도 문헌 정보에서 자동 생성할 수 있다.
    입력:
        interp_path — 해석 저장소 경로.
        library_path — 서고 루트 경로.
        document_id — 원본 문헌 ID.
    출력: {"status": "created"/"existing", "work": {...}}

    왜 이렇게 하는가:
        - 이미 같은 document_id로 생성된 Work가 있으면 중복 생성하지 않는다.
        - bibliography.json → title, creator.name, period를 채운다.
        - 없으면 manifest.json의 title을 사용한다.
    """
    interp_path = Path(interp_path).resolve()
    library_path = Path(library_path).resolve()

    # 이미 같은 document_id로 생성된 Work가 있는지 확인
    existing_works = list_entities(interp_path, "work")
    for work in existing_works:
        meta = work.get("metadata") or {}
        if meta.get("source_document_id") == document_id:
            return {"status": "existing", "work": work}

    # 문헌 메타데이터 읽기
    doc_path = library_path / "documents" / document_id
    title = document_id  # 기본값
    author = None
    period = None

    # bibliography.json 시도
    bib_path = doc_path / "bibliography.json"
    if bib_path.exists():
        try:
            bib = json.loads(bib_path.read_text(encoding="utf-8"))
            if bib.get("title"):
                title = bib["title"]
            creator = bib.get("creator")
            if isinstance(creator, dict) and creator.get("name"):
                author = creator["name"]
            if bib.get("date_created"):
                period = bib["date_created"]
        except (json.JSONDecodeError, OSError):
            pass

    # manifest.json 폴백
    if title == document_id:
        manifest_path = doc_path / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("title"):
                    title = manifest["title"]
            except (json.JSONDecodeError, OSError):
                pass

    work_data = {
        "id": str(uuid.uuid4()),
        "title": title,
        "author": author,
        "period": period,
        "status": "draft",
        "metadata": {
            "source_document_id": document_id,
        },
    }

    result = create_entity(interp_path, "work", work_data)
    return {**result, "work": work_data}


def auto_create_textblocks_from_text(
    interp_path: str | Path,
    library_path: str | Path,
    document_id: str,
    pages: list[dict],
) -> list[dict]:
    """텍스트에서 TextBlock을 직접 생성한다 (시나리오 2: HWP만).

    목적: HWP 파일로 새 문헌을 만든 후, 레이아웃 분석(L3) 없이
          바로 TextBlock을 생성하여 표점·현토·번역 작업을 시작할 수 있게 한다.
    입력:
        interp_path — 해석 저장소 경로.
        library_path — 서고 루트 경로.
        document_id — 원본 문헌 ID.
        pages — [{page_num, text, part_id(선택)}].
            각 항목은 한 페이지의 텍스트.
            part_id가 없으면 "vol1" 사용.
    출력: 생성된 TextBlock 딕셔너리 리스트.

    왜 이렇게 하는가:
        시나리오 2에서는 PDF/이미지가 없으므로 LayoutBlock도 없다.
        source_ref.layout_block_id=null로 설정하고,
        source_ref.page만으로 원본을 추적한다.
        Work가 아직 없으면 자동으로 생성한다 (auto_create_work).
    """
    interp_path = Path(interp_path).resolve()
    library_path = Path(library_path).resolve()

    # Work 자동 생성 (없으면 생성, 있으면 기존 것 사용)
    work_result = auto_create_work(interp_path, library_path, document_id)
    work_id = work_result["work"]["id"]

    created_blocks = []

    for seq_idx, page_info in enumerate(pages):
        page_num = page_info["page_num"]
        text = page_info.get("text", "")
        part_id = page_info.get("part_id", "vol1")

        if not text.strip():
            continue

        # TextBlock 생성 — layout_block_id=null (HWP 직접 가져오기)
        block_result = create_textblock_from_source(
            interp_path=interp_path,
            library_path=library_path,
            document_id=document_id,
            part_id=part_id,
            page_num=page_num,
            layout_block_id=None,
            original_text=text,
            work_id=work_id,
            sequence_index=seq_idx,
        )

        created_blocks.append(block_result)

    return created_blocks


# ──────────────────────────────────────
# 내용 트리 — Work → TextBlock 순서 (D-085)
# ──────────────────────────────────────


def _block_preview(text: str | None, length: int = 14) -> str:
    """미리보기용 첫 글자들. 공백·줄바꿈을 걷어 낸 뒤 length 글자."""
    compact = "".join((text or "").split())
    return compact[:length] + ("…" if len(compact) > length else "")


def list_contents(interp_path: str | Path, document_id: str | None = None) -> dict:
    """해석 저장소의 내용 트리 — Work마다 TextBlock을 sequence_index 순으로.

    목적: 교감 뒤에는 쪽이 아니라 **내용**으로 찾아가야 한다(D-085). 사이드바의
          「내용」 트리가 이 결과로 그려지고, 블록을 누르면 source_refs의 쪽으로
          이동한다. 저장 형식은 건드리지 않는다 — blocks/·works/를 읽어 묶기만 한다.
    입력:
        interp_path — 해석 저장소 경로.
        document_id — 주면 그 문헌을 가리키는 블록만. None이면 전부.
    출력: {
        "works": [{"id", "title", "author", "block_count", "blocks": [...]}, ...],
        "unassigned": [...블록...],          # work_id가 없거나 Work가 사라진 블록
        "total_blocks": N
    }
      블록 하나: {"id", "sequence_index", "preview", "char_count", "status",
                  "pages": [{"page", "part_id", "layout_block_ids": [...]}, ...]}
      pages는 source_refs를 쪽 번호로 묶은 것(등장 순서). 두 쪽에 걸친 블록은 둘이다.
      part_id는 참조에 있을 때만 — 예전 참조에는 없어 null일 수 있다.
    """
    interp_path = Path(interp_path).resolve()
    works = {w["id"]: w for w in list_entities(interp_path, "work") if w.get("id")}
    grouped: dict[str, list[dict]] = {wid: [] for wid in works}
    unassigned: list[dict] = []

    for blk in list_entities(interp_path, "text_block"):
        refs = blk.get("source_refs") or ([blk["source_ref"]] if blk.get("source_ref") else [])
        if document_id and refs and not any(r.get("document_id") == document_id for r in refs):
            continue
        pages: list[dict] = []
        for r in refs:
            page = r.get("page")
            if page is None:
                continue
            slot = next((p for p in pages if p["page"] == page), None)
            if slot is None:
                slot = {"page": page, "part_id": r.get("part_id"), "layout_block_ids": []}
                pages.append(slot)
            if r.get("layout_block_id") and r["layout_block_id"] not in slot["layout_block_ids"]:
                slot["layout_block_ids"].append(r["layout_block_id"])
            if slot["part_id"] is None and r.get("part_id"):
                slot["part_id"] = r["part_id"]
        item = {
            "id": blk.get("id"),
            "sequence_index": blk.get("sequence_index"),
            # 경계 앵커(D-090): 위치의 정본은 source_refs. 종류·신뢰도·좌표 캐시는 metadata.anchor
            "anchor": (blk.get("metadata") or {}).get("anchor"),
            "level": int(((blk.get("metadata") or {}).get("level")) or 2),
            "role": (blk.get("metadata") or {}).get("role"),
            "title": (blk.get("metadata") or {}).get("title"),
            "source_refs": refs,
            "preview": _block_preview(blk.get("original_text")),
            "char_count": len("".join((blk.get("original_text") or "").split())),
            "status": blk.get("status"),
            "pages": pages,
        }
        wid = blk.get("work_id")
        if wid in grouped:
            grouped[wid].append(item)
        else:
            unassigned.append(item)

    def _order(items: list[dict]) -> list[dict]:
        # sequence_index가 없는 블록은 뒤로, 그 안에서는 첫 쪽 번호로.
        return sorted(
            items,
            key=lambda b: (
                b["sequence_index"] is None,
                b["sequence_index"] if b["sequence_index"] is not None else 0,
                b["pages"][0]["page"] if b["pages"] else 0,
            ),
        )

    out_works = []
    for wid, w in works.items():
        blocks = _order(grouped[wid])
        out_works.append(
            {
                "id": wid,
                "title": w.get("title") or "(제목 없음)",
                "author": w.get("author"),
                "block_count": len(blocks),
                "blocks": blocks,
            }
        )
    out_works.sort(key=lambda w: (w["block_count"] == 0, w["title"]))
    unassigned = _order(unassigned)
    return {
        "works": out_works,
        "unassigned": unassigned,
        "total_blocks": sum(w["block_count"] for w in out_works) + len(unassigned),
    }
