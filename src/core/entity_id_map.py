"""구 ID → 신 ID 매핑 장부 (D-128 2항).

무엇을 막는가:
    Concept을 승격하거나 둘을 하나로 합치면 새 id가 생긴다. 그 순간 옛 id를
    인용한 과거 참조 — 논문 각주, 다른 해석 저장소, 내보낸 사전 — 가 조용히
    끊긴다. 커넥톰 데이터베이스는 뉴런이 병합·분할될 때마다 구 bodyId → 신 bodyId
    매핑을 릴리스 노트에 남겨 이것을 막는다. 같은 일을 여기서 한다.

왜 `Relation`의 `supersedes` 서술어가 아니라 별도 테이블인가 — 코드를 읽고 내린 판단:

    ① **Relation은 «해석 내용»이고 이것은 «장부»다.** 라우터의
       `GET /api/interpretations/{id}/entities/relation`
       (src/app/routers/interpretations.py:501)이 relations/ 아래를 그대로 목록으로
       돌려준다. 장부를 거기 섞으면 연구자가 보는 관계 목록이 내부 기록으로
       오염된다. D-128 2항은 «사용자에게 보이지 않는 내부 장부»라고 못 박았다.

    ② **Tag → Concept 승격을 담을 수 없다.** relation.schema.json의
       `subject_type` enum은 `agent | concept` 둘뿐이다(schemas/core/relation.schema.json).
       승격 기록을 Relation에 넣으려면 해석 축의 스키마를 장부 때문에 넓혀야 하는데,
       그것은 코어 스키마의 «구조만 담는다»는 전제를 거스른다.

    ③ **조회가 O(1)이어야 한다.** 옛 id로 물어볼 때마다 relations/*.json을 전부
       열어 훑을 수는 없다. 장부는 파일 하나다.

파일: `{해석 저장소}/core_entities/id_map.json`

    {
      "schema_version": "1.0",
      "entries": [
        {"entity_type": "concept", "old_id": "...", "new_id": "...",
         "relation": "superseded_by", "recorded_at": "...", "note": null}
      ]
    }

`relation` 값 둘:
    - `superseded_by` — 같은 종류 안에서 옛것이 새것으로 대체됐다(병합). 조회는
      이 고리만 따라간다.
    - `promoted_to` — Tag가 Concept이 됐다. **고리로 따라가지 않는다** — Tag는
      승격 뒤에도 그대로 남아 제 id로 조회되므로(entity.py의 promote_tag_to_concept은
      Tag를 건드리지 않는다), 이것은 «무엇이 됐는가»를 알려주는 기록이지 대체가 아니다.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ID_MAP_FILENAME = "id_map.json"
ID_MAP_SCHEMA_VERSION = "1.0"

# 조회 시 따라가는 고리. promoted_to는 대체가 아니므로 여기 없다.
FOLLOWED_RELATIONS = ("superseded_by",)


def id_map_path(interp_path: str | Path) -> Path:
    """장부 파일의 경로. 입력: 해석 저장소 경로. 출력: Path."""
    return Path(interp_path).resolve() / "core_entities" / ID_MAP_FILENAME


def load_id_map(interp_path: str | Path) -> dict:
    """장부를 읽는다. 없으면 빈 장부를 돌려준다(파일을 만들지는 않는다).

    입력: interp_path — 해석 저장소 경로.
    출력: {"schema_version": "1.0", "entries": [...]}
    """
    path = id_map_path(interp_path)
    if not path.exists():
        return {"schema_version": ID_MAP_SCHEMA_VERSION, "entries": []}
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        # 장부가 깨졌다고 해서 서고를 못 열게 하면 안 된다. 빈 장부로 계속 가되
        # 로그를 남긴다 — 조용히 덮어쓰면 매핑이 영영 사라진다.
        logger.warning("id_map.json을 읽지 못했습니다(%s). 빈 장부로 진행합니다: %s", path, e)
        return {"schema_version": ID_MAP_SCHEMA_VERSION, "entries": []}
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        logger.warning("id_map.json의 모양이 예상과 다릅니다(%s). 빈 장부로 진행합니다.", path)
        return {"schema_version": ID_MAP_SCHEMA_VERSION, "entries": []}
    return data


def record_mapping(
    interp_path: str | Path,
    *,
    entity_type: str,
    old_id: str,
    new_id: str,
    relation: str = "superseded_by",
    note: str | None = None,
) -> dict:
    """매핑 한 줄을 장부에 적는다.

    입력:
        entity_type — 옛 엔티티의 종류 (concept, tag, agent …).
        old_id — 옛 id. new_id — 새 id.
        relation — "superseded_by"(대체) 또는 "promoted_to"(승격).
        note — 사람이 읽을 사유.
    출력: 적힌 항목 dict.

    왜 덮어쓰지 않고 쌓는가: 병합은 여러 번 일어나고 A→B→C 같은 고리가 생긴다.
    중간 단계를 지우면 A를 인용한 참조가 다시 끊긴다 — 이 모듈의 존재 이유가 그것이다.
    같은 (종류, 옛 id, 고리)가 이미 있으면 새 대상으로 갱신한다(재병합).
    """
    if old_id == new_id:
        raise ValueError(
            "구 ID와 신 ID가 같습니다 — 매핑할 것이 없습니다.\n"
            "→ 해결: 병합 대상과 목표가 다른 엔티티인지 확인하세요."
        )
    data = load_id_map(interp_path)
    entry = {
        "entity_type": entity_type,
        "old_id": old_id,
        "new_id": new_id,
        "relation": relation,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }
    entries = [
        e
        for e in data["entries"]
        if not (
            e.get("entity_type") == entity_type
            and e.get("old_id") == old_id
            and e.get("relation") == relation
        )
    ]
    entries.append(entry)
    data["entries"] = entries
    data["schema_version"] = ID_MAP_SCHEMA_VERSION

    from .document import write_json_atomic

    write_json_atomic(id_map_path(interp_path), data)
    return entry


def resolve_id(
    interp_path: str | Path,
    entity_type: str,
    entity_id: str,
) -> dict:
    """옛 id가 지금 무엇이 됐는지 되짚는다.

    입력: entity_type — 엔티티 종류. entity_id — 물어보는 id(옛것일 수 있다).
    출력:
        {"id": 최종 id, "chain": [거쳐온 id...], "superseded": bool}
        매핑이 없으면 {"id": 그대로, "chain": [그 id], "superseded": False}.

    왜 고리(chain)를 돌려주는가: A→B→C로 두 번 병합된 뒤 A를 물으면 C가 나오는데,
    「왜 C인가」를 설명하려면 거쳐온 자리가 필요하다.

    고리가 한 바퀴 도는 경우(잘못 적힌 장부)에는 멈추고 거기까지를 돌려준다 —
    무한 반복으로 서버가 멎는 것보다 낫다.
    """
    lookup: dict[str, str] = {}
    for e in load_id_map(interp_path)["entries"]:
        if e.get("entity_type") != entity_type:
            continue
        if e.get("relation") not in FOLLOWED_RELATIONS:
            continue
        old, new = e.get("old_id"), e.get("new_id")
        if old and new:
            lookup[old] = new

    chain = [entity_id]
    seen = {entity_id}
    current = entity_id
    while current in lookup:
        nxt = lookup[current]
        if nxt in seen:
            logger.warning(
                "id_map에 순환이 있습니다: %s (종류 %s). 거기서 멈춥니다.", chain, entity_type
            )
            break
        chain.append(nxt)
        seen.add(nxt)
        current = nxt

    return {"id": current, "chain": chain, "superseded": current != entity_id}


def successors(interp_path: str | Path, entity_type: str, entity_id: str) -> list[dict]:
    """이 id에서 **나간** 기록을 모은다(대체·승격 둘 다).

    입력: entity_type, entity_id.
    출력: 장부 항목 목록. Tag가 무엇으로 승격됐는지 물을 때 쓴다.
    """
    return [
        e
        for e in load_id_map(interp_path)["entries"]
        if e.get("entity_type") == entity_type and e.get("old_id") == entity_id
    ]


def predecessors(interp_path: str | Path, entity_type: str, entity_id: str) -> list[dict]:
    """이 id로 **들어온** 기록을 모은다.

    입력: entity_type, entity_id.
    출력: 장부 항목 목록. 「이 Concept은 무엇들이 합쳐진 것인가」에 답한다.
    """
    return [
        e
        for e in load_id_map(interp_path)["entries"]
        if e.get("entity_type") == entity_type and e.get("new_id") == entity_id
    ]
