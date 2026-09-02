"""글 단위 경계 목록 — 단위(글)의 정본 (D-092).

왜 이것이 정본인가:
    v1.2.x까지 글 단위는 TextBlock(본문 복사본 + 쪽·글자 범위)이었고 경계는 그 위치의 보기였다
    (D-090). 임의 행·행 중간에 경계를 넣을 수 있게 되자(D-090 2단계) TextBlock이 따로 가진
    정보는 «단위의 id·제목·상태»뿐이었고, 본문 복사본은 교감이 반영되지 않는 짐이었다.
    그래서 뒤집었다 — **경계 목록이 정본**이고 TextBlock은 이 목록에서 만든 읽기 전용 보기다.

규칙 (D-092 결정):
    - 권마다 파일 하나: core_entities/boundaries/{document_id}__{part_id}.json
    - 항목 = «여기서 단위가 시작한다». 끝은 저장하지 않는다 — 같은 층위 이상의 다음 경계 앞까지.
    - 단위의 id는 시작 경계에 붙는다. 합치기 = 뒤 경계 삭제(앞 id가 남는다), 쪼개기 = 경계 삽입
      (새 id는 뒤 단위에), 옮기기 = start만 바꾼다.
    - 층위: 1 = 卷·편, 2 = 기사, 3 이상 = 기사 안 조각. 층위 n을 손대도 더 얕은 층위의 id는 그대로.
    - 본문은 저장하지 않고 L4에서 잘라 온다. L4 커밋이 바뀌면 오프셋이 아니라 anchor_text로
      자리를 다시 찾고, 못 찾으면 anchor_status="stale"로 표시한다
      (조용히 틀린 자리를 가리키지 않는다).

이 모듈은 파일과 순수 계산만 담당한다. git commit·HTTP 응답은 라우터의 일이다.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

BOUNDARIES_DIRNAME = "boundaries"
LEGACY_BLOCKS_DIRNAME = "blocks"
MIGRATED_BLOCKS_DIRNAME = "blocks_migrated_v1"
ANCHOR_TEXT_LEN = (
    8  # 자리를 다시 찾을 때 쓰는 글자 수 — 너무 짧으면 여러 곳에 맞고, 길면 교감에 깨진다
)

_SCHEMA_CACHE: dict | None = None


# ── 파일 ─────────────────────────────────────────────────────────────────


def boundaries_dir(interp_path: str | Path) -> Path:
    return Path(interp_path) / "core_entities" / BOUNDARIES_DIRNAME


def boundaries_file(interp_path: str | Path, document_id: str, part_id: str) -> Path:
    return boundaries_dir(interp_path) / f"{document_id}__{part_id}.json"


def list_boundary_parts(interp_path: str | Path) -> list[tuple[str, str]]:
    """경계 파일이 있는 (document_id, part_id) 목록."""
    d = boundaries_dir(interp_path)
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out.append((str(data["document_id"]), str(data["part_id"])))
        except (OSError, ValueError, KeyError):
            continue
    return out


def _schema() -> dict:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        p = (
            Path(__file__).resolve().parent.parent.parent
            / "schemas"
            / "core"
            / "boundaries.schema.json"
        )
        _SCHEMA_CACHE = json.loads(p.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE


def validate(data: dict) -> None:
    import jsonschema

    jsonschema.validate(data, _schema())


def sort_key(b: dict) -> tuple:
    s = b.get("start") or {}
    return (
        int(s.get("page", 0)),
        int(s.get("line", 0)),
        int(s.get("offset", 0)),
        int(b.get("level", 2)),
    )


def load_boundaries(interp_path: str | Path, document_id: str, part_id: str) -> dict:
    """권의 경계 목록. 파일이 없으면 빈 목록(파일은 만들지 않는다)."""
    p = boundaries_file(interp_path, document_id, part_id)
    if not p.exists():
        return {"document_id": document_id, "part_id": part_id, "boundaries": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    data["boundaries"] = sorted(data.get("boundaries") or [], key=sort_key)
    return data


def save_boundaries(interp_path: str | Path, data: dict) -> Path:
    """검증하고 원자적으로 쓴다(write_json_atomic — D-069). 순서는 위치순으로 고정한다."""
    from core.document import write_json_atomic

    data = dict(data)
    data["boundaries"] = sorted(data.get("boundaries") or [], key=sort_key)
    validate(data)
    p = boundaries_file(interp_path, data["document_id"], data["part_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(p, data)
    return p


# ── 위치 계산 ─────────────────────────────────────────────────────────────


def position_from_char(page_texts: dict[int, str], page: int, abs_offset: int) -> dict:
    """쪽 텍스트의 절대 글자 오프셋 → {page, line, offset}."""
    t = page_texts.get(int(page), "")
    at = max(0, min(int(abs_offset), len(t)))
    line_start = t.rfind("\n", 0, at) + 1
    return {"page": int(page), "line": t.count("\n", 0, at), "offset": at - line_start}


def char_from_position(page_texts: dict[int, str], pos: dict) -> Optional[int]:
    """{page, line, offset} → 쪽 텍스트의 절대 글자 오프셋. 행이 없으면 None."""
    t = page_texts.get(int(pos["page"]))
    if t is None:
        return None
    raw = t.split("\n")
    line = int(pos.get("line", 0))
    if line < 0 or line >= len(raw):
        return None
    base = sum(len(r) + 1 for r in raw[:line])
    return base + max(0, min(int(pos.get("offset", 0)), len(raw[line])))


def anchor_text_at(
    page_texts: dict[int, str], pos: dict, n: int = ANCHOR_TEXT_LEN
) -> Optional[str]:
    at = char_from_position(page_texts, pos)
    if at is None:
        return None
    t = page_texts[int(pos["page"])]
    return t[at : at + n].replace("\n", "")


# ── 단위(보기) 계산 ──────────────────────────────────────────────────────


def _live(b: dict) -> bool:
    return b.get("status") not in ("deprecated", "archived")


def unit_end(bounds: list[dict], i: int) -> Optional[dict]:
    """i번째 경계의 단위가 끝나는 자리.

    = 같은 층위 이상(level 값이 작거나 같은)의 다음 경계. 없으면 None(권 끝까지).
    """
    lv = int(bounds[i].get("level", 2))
    for j in range(i + 1, len(bounds)):
        if not _live(bounds[j]):
            continue
        if int(bounds[j].get("level", 2)) <= lv:
            return bounds[j]["start"]
    return None


def _span_for(
    lines, keys: list[tuple[int, int]], start: dict, end: Optional[dict]
) -> Optional[dict]:
    """경계 start/end(exclusive) → span_to_text_and_refs()가 받는 구간. 시작 행이 없으면 None."""
    s_key = (int(start["page"]), int(start["line"]))
    if s_key not in keys:
        return None
    s_i = keys.index(s_key)
    s_off = int(start.get("offset", 0))
    if end is None:
        e_i, e_end = len(lines) - 1, None
    else:
        e_key = (int(end["page"]), int(end["line"]))
        if e_key in keys:
            e_i = keys.index(e_key)
            e_off = int(end.get("offset", 0))
            if e_off > 0:
                e_end = e_off
            else:
                e_i, e_end = e_i - 1, None
        else:
            # 끝 경계의 행이 사라졌다(stale) — 그 쪽 앞까지로 본다
            e_i = max(
                s_i,
                max((k for k, key in enumerate(keys) if key[0] < int(end["page"])), default=s_i),
            )
            e_end = None
    if e_i < s_i or (e_i == s_i and e_end is not None and e_end <= s_off):
        # 빈 단위(같은 자리에 두 경계). 텍스트 없음.
        e_i, e_end = s_i, s_off
    return {
        "start": {"page": keys[s_i][0], "line_index": keys[s_i][1], "char_offset": s_off},
        "end": {"page": keys[e_i][0], "line_index": keys[e_i][1], "char_end": e_end},
    }


def compute_units(
    data: dict,
    lines: list,
    page_texts: dict[int, str],
) -> list[dict]:
    """경계 목록 → TextBlock 모양의 단위 목록(읽기 전용 보기).

    입력:
        data — load_boundaries() 결과.
        lines, page_texts — segmentation.collect_document_lines()의 결과(그 권).
    출력: TextBlock 스키마와 같은 모양의 dict 목록(위치 순서). 관계·태그·표점 편집기가
          `text_block` 엔티티로 읽던 것과 같은 필드를 준다 — id·work_id·sequence_index·
          original_text·source_ref·source_refs·status·notes·metadata(title·kind·level·anchor).
    """
    from core.segmentation import span_to_text_and_refs

    bounds = [b for b in sorted(data.get("boundaries") or [], key=sort_key)]
    keys = [(ln.page, ln.line_index) for ln in lines]
    doc_id, part_id = data["document_id"], data["part_id"]
    units: list[dict] = []
    seq_by_work: dict[Optional[str], int] = {}
    for i, b in enumerate(bounds):
        if not _live(b):
            continue
        span = _span_for(lines, keys, b["start"], unit_end(bounds, i))
        if span is None:
            text, refs = (
                "",
                [
                    {
                        "document_id": doc_id,
                        "part_id": part_id,
                        "page": int(b["start"]["page"]),
                        "layout_block_id": None,
                        "char_range": None,
                        "layer": "L4",
                    }
                ],
            )
        else:
            text, refs = span_to_text_and_refs(span, lines, page_texts, doc_id, part_id)
        wid = b.get("work_id")
        seq = seq_by_work.get(wid, 0)
        seq_by_work[wid] = seq + 1
        anchor = {
            "kind": b.get("kind") or "manual",
            "level": int(b.get("level", 2)),
            "status": b.get("anchor_status") or "approved",
            "confidence": b.get("confidence"),
            "reasons": list(b.get("reasons") or []),
            "l4_commit": b.get("l4_commit"),
            "bbox": b.get("bbox"),
        }
        meta = dict(b.get("metadata") or {})
        meta.update(
            {
                "part_id": part_id,
                "title": b.get("title"),
                "kind": b.get("kind"),
                "level": int(b.get("level", 2)),
                "segmentation": "boundary",
                "anchor": anchor,
            }
        )
        units.append(
            {
                "id": b["id"],
                "work_id": wid,
                "sequence_index": seq,
                "original_text": text,
                "normalized_text": None,
                "source_ref": {k: v for k, v in refs[0].items() if k != "char_range"},
                "source_refs": refs,
                "status": b.get("status", "draft"),
                "notes": b.get("notes"),
                "metadata": meta,
            }
        )
    return units


# ── 재대조 (L4가 바뀐 뒤) ─────────────────────────────────────────────────


def rematch(data: dict, page_texts: dict[int, str], l4_commit: Optional[str]) -> int:
    """L4 커밋이 달라진 경계를 anchor_text로 다시 찾는다. 바뀐 항목 수를 돌려준다.

    찾는 규칙: 같은 쪽에서 anchor_text가 나오는 자리 중 옛 오프셋에 가장 가까운 것. 없으면
    anchor_status="stale"로 두고 위치는 그대로(사람이 옮긴다). anchor_text가 없던 항목은
    지금 자리에서 만들어 둔다.
    """
    changed = 0
    for b in data.get("boundaries") or []:
        same = l4_commit is not None and b.get("l4_commit") == l4_commit
        at = char_from_position(page_texts, b["start"])
        if same:
            if at is not None and not b.get("anchor_text"):
                b["anchor_text"] = anchor_text_at(page_texts, b["start"])
                changed += 1
            continue
        t = page_texts.get(int(b["start"]["page"]), "")
        want = b.get("anchor_text")
        if not want:
            if at is not None:
                b["anchor_text"] = anchor_text_at(page_texts, b["start"])
            b["l4_commit"] = l4_commit
            changed += 1
            continue
        # 후보 자리들
        hits = []
        k = t.find(want)
        while k >= 0:
            hits.append(k)
            k = t.find(want, k + 1)
        if not hits and len(want) > 4:
            short = want[:4]
            k = t.find(short)
            while k >= 0:
                hits.append(k)
                k = t.find(short, k + 1)
        if not hits:
            if b.get("anchor_status") != "stale":
                b["anchor_status"] = "stale"
                changed += 1
            continue
        old_at = at if at is not None else 0
        best = min(hits, key=lambda h: abs(h - old_at))
        b["start"] = position_from_char(page_texts, b["start"]["page"], best)
        b["l4_commit"] = l4_commit
        if b.get("anchor_status") == "stale":
            b["anchor_status"] = "approved"
        changed += 1
    return changed


# ── CRUD (파일에 쓰지 않는다 — 호출자가 save_boundaries) ────────────────


def new_boundary(
    start: dict,
    level: int = 2,
    title: Optional[str] = None,
    kind: Optional[str] = None,
    work_id: Optional[str] = None,
    status: str = "draft",
    anchor_status: str = "approved",
    boundary_id: Optional[str] = None,
    page_texts: Optional[dict[int, str]] = None,
    l4_commit: Optional[str] = None,
    confidence: Optional[float] = None,
    reasons: Optional[list[str]] = None,
    bbox: Optional[dict] = None,
) -> dict:
    """경계 항목 하나. page_texts를 주면 anchor_text를 채운다."""
    pos = {
        "page": int(start["page"]),
        "line": int(start.get("line", 0)),
        "offset": int(start.get("offset", 0)),
    }
    return {
        "id": boundary_id or str(uuid.uuid4()),
        "level": int(level),
        "start": pos,
        "title": title,
        "kind": kind,
        "status": status,
        "anchor_status": anchor_status,
        "work_id": work_id,
        "anchor_text": anchor_text_at(page_texts, pos) if page_texts else None,
        "l4_commit": l4_commit,
        "confidence": confidence,
        "reasons": list(reasons or []),
        "bbox": bbox,
        "notes": None,
        "metadata": None,
    }


def find_boundary(data: dict, boundary_id: str) -> Optional[dict]:
    return next((b for b in data.get("boundaries") or [] if b.get("id") == boundary_id), None)


def find_at(data: dict, start: dict, level: int) -> Optional[dict]:
    """같은 자리(쪽·행·글자)·같은 층위의 살아 있는 경계."""
    key = (int(start["page"]), int(start.get("line", 0)), int(start.get("offset", 0)), int(level))
    for b in data.get("boundaries") or []:
        if _live(b) and sort_key(b) == key:
            return b
    return None


def insert_boundary(data: dict, item: dict) -> dict:
    """경계를 넣는다. 같은 자리·같은 층위에 이미 살아 있는 경계가 있으면 **그것을 돌려준다**.

    왜: 경계 제안을 두 번 «선택 적용»하면 같은 자리에 경계가 둘 생겨 빈 단위와 겹친 항목이
    트리에 두 번 떴다(운양집 실측 2026-09-03, 77 → 148). 같은 자리는 같은 단위이므로 두 번 넣는
    것은 아무 일도 아니어야 한다 — 먼저 있던 id가 남고, 관계·태그가 가리키는 id도 그것이다.
    """
    if find_boundary(data, item["id"]) is not None:
        raise FileExistsError(f"같은 id의 경계가 이미 있습니다: {item['id']}")
    existing = find_at(data, item["start"], int(item.get("level", 2)))
    if existing is not None:
        return existing
    data.setdefault("boundaries", []).append(item)
    data["boundaries"].sort(key=sort_key)
    return item


def delete_boundary(data: dict, boundary_id: str) -> dict:
    """경계를 지운다 = 그 단위를 앞 단위에 합친다. 지운 항목을 돌려준다."""
    b = find_boundary(data, boundary_id)
    if b is None:
        raise FileNotFoundError(f"경계를 찾을 수 없습니다: {boundary_id}")
    data["boundaries"] = [x for x in data["boundaries"] if x.get("id") != boundary_id]
    return b


def move_boundary(
    data: dict, boundary_id: str, start: dict, page_texts: Optional[dict[int, str]] = None
) -> dict:
    b = find_boundary(data, boundary_id)
    if b is None:
        raise FileNotFoundError(f"경계를 찾을 수 없습니다: {boundary_id}")
    b["start"] = {
        "page": int(start["page"]),
        "line": int(start.get("line", 0)),
        "offset": int(start.get("offset", 0)),
    }
    if page_texts:
        b["anchor_text"] = anchor_text_at(page_texts, b["start"])
    b["anchor_status"] = "approved"
    data["boundaries"].sort(key=sort_key)
    return b


_UPDATABLE = (
    "title",
    "kind",
    "status",
    "anchor_status",
    "level",
    "work_id",
    "notes",
    "metadata",
    "bbox",
    "confidence",
    "reasons",
)


def update_boundary(data: dict, boundary_id: str, fields: dict) -> dict:
    b = find_boundary(data, boundary_id)
    if b is None:
        raise FileNotFoundError(f"경계를 찾을 수 없습니다: {boundary_id}")
    for k, v in fields.items():
        if k in _UPDATABLE:
            b[k] = v
    data["boundaries"].sort(key=sort_key)
    return b


# ── 마이그레이션 (blocks/ → boundaries/) ─────────────────────────────────


def needs_migration(interp_path: str | Path) -> bool:
    """옛 TextBlock 파일은 있는데 경계 목록이 없는 저장소인가."""
    interp_path = Path(interp_path)
    blocks = interp_path / "core_entities" / LEGACY_BLOCKS_DIRNAME
    return (
        blocks.exists() and any(blocks.glob("*.json")) and not boundaries_dir(interp_path).exists()
    )


def migrate_from_blocks(interp_path: str | Path, library_root: str | Path) -> dict:
    """blocks/*.json → boundaries/*.json. 손실 없이, 옛 파일은 blocks_migrated_v1/로 옮겨 둔다.

    규칙(D-092 마이그레이션):
      - 첫 source_ref의 쪽·char_range[0]에서 시작 경계를 만든다.
        char_range가 없으면 쪽 첫 행 0.
      - id·제목·종류·상태·work_id·metadata.anchor(층위·신뢰도·근거·bbox)는 그대로.
      - 끝 위치는 버린다(다음 경계가 정한다). deprecated·archived 블록도 옮기되 단위를
        만들지 않는다.
    출력: {"parts": [(document_id, part_id, n)], "skipped": [...이유...]}
    """
    from core.segmentation import collect_document_lines

    interp_path = Path(interp_path)
    library_root = Path(library_root)
    blocks_dir = interp_path / "core_entities" / LEGACY_BLOCKS_DIRNAME
    grouped: dict[tuple[str, str], list[dict]] = {}
    skipped: list[str] = []
    for f in sorted(blocks_dir.glob("*.json")):
        try:
            blk = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            skipped.append(f"{f.name}: 읽기 실패 {e}")
            continue
        refs = blk.get("source_refs") or ([blk["source_ref"]] if blk.get("source_ref") else [])
        refs = [r for r in refs if r and r.get("page")]
        if not refs:
            skipped.append(f"{blk.get('id')}: 출처(쪽)가 없다")
            continue
        r0 = refs[0]
        doc_id = r0.get("document_id")
        part_id = r0.get("part_id") or (blk.get("metadata") or {}).get("part_id") or "vol1"
        if not doc_id:
            skipped.append(f"{blk.get('id')}: document_id가 없다")
            continue
        grouped.setdefault((doc_id, part_id), []).append(blk)

    out_parts = []
    for (doc_id, part_id), blks in grouped.items():
        doc_path = library_root / "documents" / doc_id
        page_texts: dict[int, str] = {}
        if doc_path.exists():
            try:
                _lines, page_texts = collect_document_lines(doc_path, part_id, None)
            except Exception as e:  # noqa: BLE001 — L4가 없어도 쪽 첫 행으로는 옮길 수 있다
                logger.warning("마이그레이션: %s/%s 확정본을 읽지 못함 (%s)", doc_id, part_id, e)
        data = load_boundaries(interp_path, doc_id, part_id)
        for blk in blks:
            refs = blk.get("source_refs") or [blk.get("source_ref")]
            r0 = next(r for r in refs if r and r.get("page"))
            cr = r0.get("char_range")
            page = int(r0["page"])
            if cr and page_texts.get(page) is not None:
                pos = position_from_char(page_texts, page, int(cr[0]))
            else:
                pos = {"page": page, "line": 0, "offset": 0}
            meta = blk.get("metadata") or {}
            anchor = meta.get("anchor") or {}
            item = new_boundary(
                start=pos,
                level=int(anchor.get("level") or 2),
                title=meta.get("title") or (blk.get("original_text") or "").strip()[:20] or None,
                kind=anchor.get("kind") or meta.get("kind") or "manual",
                work_id=blk.get("work_id"),
                status=blk.get("status", "draft"),
                anchor_status=anchor.get("status") or "approved",
                boundary_id=blk["id"],
                page_texts=page_texts or None,
                l4_commit=anchor.get("l4_commit") or r0.get("commit"),
                confidence=anchor.get("confidence"),
                reasons=anchor.get("reasons"),
                bbox=anchor.get("bbox"),
            )
            item["notes"] = blk.get("notes")
            rest = {
                k: v
                for k, v in meta.items()
                if k not in ("title", "kind", "anchor", "part_id", "segmentation", "level")
            }
            item["metadata"] = rest or None
            if find_boundary(data, item["id"]) is None:
                data["boundaries"].append(item)
        save_boundaries(interp_path, data)
        out_parts.append((doc_id, part_id, len(blks)))

    # 옛 파일은 지우지 않는다 — 이름만 바꿔 둔다(해석 저장소는 Git이라 어느 쪽이든 되돌릴 수 있다)
    target = interp_path / "core_entities" / MIGRATED_BLOCKS_DIRNAME
    if not target.exists():
        shutil.move(str(blocks_dir), str(target))
    boundaries_dir(interp_path).mkdir(parents=True, exist_ok=True)
    return {"parts": out_parts, "skipped": skipped}
