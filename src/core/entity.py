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
import uuid
from pathlib import Path

import git
import jsonschema

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

    schema_path = (
        Path(__file__).resolve().parent.parent.parent
        / "schemas" / "core" / schema_file
    )
    if schema_path.exists():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        # _meta 등 내부 필드는 검증에서 제외
        validate_data = {k: v for k, v in data.items() if not k.startswith("_")}
        jsonschema.validate(instance=validate_data, schema=schema)


def _write_json(path: Path, data: dict) -> None:
    """JSON 파일을 UTF-8로 저장한다. (interpretation.py 641~646행 패턴)"""
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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
            "엔티티 ID는 변경할 수 없습니다.\n"
            "→ 해결: id 필드를 updates에서 제거하세요."
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
        if (evidence & block_ids
                or rel.get("subject_id") in related_ids
                or rel.get("object_id") in related_ids):
            page_relations.append(rel)
            # 관련된 Agent/Concept ID 수집
            if rel.get("subject_type") == "agent":
                agent_ids.add(rel["subject_id"])
            elif rel.get("subject_type") == "concept":
                concept_ids.add(rel["subject_id"])
            if rel.get("object_type") == "agent":
                agent_ids.add(rel["object_id"])
            elif rel.get("object_type") == "concept":
                concept_ids.add(rel["object_id"])

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

    # Concept 생성
    concept_data = {
        "id": str(uuid.uuid4()),
        "label": label or tag.get("surface", ""),
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

    text_block_data = {
        "id": str(uuid.uuid4()),
        "work_id": work_id,
        "sequence_index": sequence_index,
        "original_text": original_text,
        "normalized_text": None,
        "source_ref": {
            "document_id": document_id,
            "page": page_num,
            "layout_block_id": layout_block_id,
            "layer": "L4",
            "commit": commit_hash,
        },
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
