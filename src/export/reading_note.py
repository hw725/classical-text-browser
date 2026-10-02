"""강독 노트 — 기존 층에서 다시 조립해 미디어위키·마크다운으로 낸다 (D-131).

노트는 저장하지 않는다. 언제나 지금의 층에서 새로 만든다:
    장·문서 항목 = 편성 경계(단위), 원문 = 지금 L4(교정 탭에서 고친 것이 그대로 반영),
    국역 = L6 번역 항목, 어휘·문법 = L7 사전형 주석, 해제·서지·요점·문서 정보·검토 = L7 비고 주석.
render_wiki·render_markdown은 기본 모양이다. 수업·스터디마다 모양이 다르면 코드를 고치지 않고
«틀»을 준다(export/note_template.py — 예시 노트를 LLM이 틀로 바꾸고, 코드가 층으로 채운다).
assemble_notes가 만드는 dict는 **그리기 위한 보기**이지 저장 형식이 아니다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from core.reading_ingest import CHAPTER_NOTES as _CHAPTER_NOTES  # 저장과 조립이 같은 표를 쓴다

_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _circled(n: int) -> str:
    return _CIRCLED[n - 1] if 1 <= n <= len(_CIRCLED) else f"({n})"


def _notes_of(ann_blocks: list, block_id: str, label: str) -> list[dict]:
    return [
        a
        for b in ann_blocks
        if b.get("block_id") == block_id
        for a in b.get("annotations") or []
        if a.get("type") == "note" and (a.get("content") or {}).get("label") == label
    ]


def _lines_of(ann_blocks: list, block_id: str, label: str) -> list[str]:
    return [
        ln
        for a in _notes_of(ann_blocks, block_id, label)
        for ln in a["content"]["description"].split("\n")
        if ln.strip()
    ]


def assemble_notes(library: str | Path, doc_id: str, part_id: str, interp_id: str) -> list[dict]:
    """층에서 장별 노트 보기를 만든다. 번역·주석이 하나라도 있는 장만.

    출력: [{"title", "chapter", "bibliography", "intro", "notes", "points",
            "sections": [{"heading", "level", "page", "meta",
                          "segments": [{"label", "text", "ko", "terms", "check", "changed"}]}]}].
    원문은 **지금 L4**에서 자른다. 번역 당시 원문(source_text)과 다르면 changed=True — 교정한 뒤
    국역을 다시 봐야 하는 자리다.
    """
    from core.annotation import load_annotations
    from core.boundaries import compute_units, load_doc_boundaries
    from core.reading_ingest import check_interp_id
    from core.segmentation import collect_document_lines
    from core.translation import load_translations
    from ocr.read_book import check_part_id

    library = Path(library)
    doc_path = library / "documents" / doc_id
    check_part_id(part_id)
    interp_path = check_interp_id(library, doc_id, interp_id)  # 경로 이탈·다른 문헌 막기
    if not interp_path.exists():
        return []
    lines, page_texts = collect_document_lines(doc_path, part_id, None)
    units = compute_units(load_doc_boundaries(doc_path, doc_id, part_id), lines, page_texts)
    cache: dict[int, tuple[list, list]] = {}

    def layers(page: int) -> tuple[list, list]:
        if page not in cache:
            tr = load_translations(interp_path, part_id, page).get("translations") or []
            ann = load_annotations(interp_path, part_id, page).get("blocks") or []
            cache[page] = (tr, ann)
        return cache[page]

    notes: list[dict] = []
    current: Optional[dict] = None
    for u in units:
        md = u.get("metadata") or {}
        level = int(md.get("level") or 2)
        tr, ann = layers(int(u["source_ref"]["page"]))
        if level <= 1:
            title = md.get("title") or ""
            current = {"title": f"{title} 강독 노트".strip(), "chapter": title, "sections": []}
            for label, key in _CHAPTER_NOTES:
                current[key] = _lines_of(ann, u["id"], label)
            notes.append(current)
            continue
        if current is None:
            continue
        text = u.get("original_text") or ""
        mine = sorted(
            (t for t in tr if (t.get("source") or {}).get("block_id") == u["id"]),
            key=lambda t: t["source"]["start"],
        )
        terms = [
            a
            for b in ann
            if b.get("block_id") == u["id"]
            for a in b.get("annotations") or []
            if a.get("dictionary")
        ]
        checks = _notes_of(ann, u["id"], "검토")
        segments = []
        for n, t in enumerate(mine, 1):
            s, e = t["source"]["start"], t["source"]["end"]
            now = text[s : e + 1]
            seg_terms = sorted(
                (a for a in terms if s <= a["target"]["start"] <= e),
                key=lambda a: a["target"]["start"],
            )
            then = "".join((t.get("source_text") or "").split())
            segments.append(
                {
                    "label": f"○{_circled(n)}",
                    "text": now.replace("\n", ""),
                    "ko": t.get("translation") or "",
                    "terms": [
                        {
                            "term": a["dictionary"]["headword"],
                            "reading": a["dictionary"].get("headword_reading") or "",
                            "gloss": a["dictionary"].get("dictionary_meaning") or "",
                        }
                        for a in seg_terms
                    ],
                    "check": "; ".join(
                        c["content"]["description"]
                        for c in checks
                        if s <= c["target"]["start"] <= e
                    ),
                    "changed": "".join(now.split()) != then,
                }
            )
        meta = _lines_of(ann, u["id"], "문서 정보")
        if segments or meta:
            current["sections"].append(
                {
                    "heading": md.get("title") or "",
                    "level": min(5, level + 1),
                    "page": int(u["source_ref"]["page"]),  # 틀이 쪽을 따로 쓰고 싶을 때
                    "meta": meta,
                    "segments": segments,
                }
            )
    # 구획이 없어도 해제·서지·요점이 있는 장은 남긴다
    return [n for n in notes if n["sections"] or any(n.get(k) for _l, k in _CHAPTER_NOTES)]


# ── 미디어위키 ─────────────────────────────────────────────


def _wiki_box(label: str, body: str) -> str:
    """접히는 표 한 칸 — 강독 노트의 «국역 (펼치기)» 모양."""
    return (
        '{| class="wikitable mw-collapsible mw-collapsed" style="width:100%"\n'
        f"! {label} (펼치기)\n|-\n|\n{body}\n|}}"
    )


def _wiki_term(t: dict) -> str:
    reading = f"({t['reading']})" if t.get("reading") else ""
    return f"* '''{t['term']}'''{reading} — {t['gloss']}"


def render_wiki(note: dict, author: Optional[str] = None) -> str:
    """노트 보기 하나를 미디어위키 문서로.

    구조: 해제 → 원문 강독(항목 → 구획 → 원문 → 접히는 국역 → 어휘·문법) → 독해 요점.
    """
    out: list[str] = [f"= {note.get('title') or note['chapter']} ="]
    if author:
        out.append(f": 작성: [[{author}]]")
    out.extend(f": {b}" for b in note.get("bibliography") or [])
    if note.get("intro") or note.get("notes"):
        out.append("\n== 해제 ==")
        out.extend(note.get("intro") or [])
        out.extend(f": {n}" for n in note.get("notes") or [])
    out.append("\n== 원문 강독 ==")
    for s in note.get("sections") or []:
        bar = "=" * int(s.get("level") or 3)
        out.append(f"\n{bar} {s['heading']} {bar}")
        out.extend(f": {m}" for m in s.get("meta") or [])
        for seg in s.get("segments") or []:
            out.append("")
            if seg.get("label"):
                out.append(f"'''{seg['label']}'''")
            out.append(f": {seg['text']}")
            if seg.get("changed"):
                out.append(": ※ 번역 뒤 확정본이 고쳐졌다 — 국역을 다시 볼 것")
            if seg.get("ko"):
                out.append("")
                out.append(_wiki_box("국역", seg["ko"]))
            if seg.get("terms"):
                out.append("")
                out.append("'''어휘·문법'''")
                out.extend(_wiki_term(t) for t in seg["terms"])
            if seg.get("check"):
                out.append(f": ※ 검토 — {seg['check']}")
    if note.get("points"):
        out.append("\n== 독해 요점 ==")
        out.extend(f"# {p}" for p in note["points"])
    out.append(
        "\n: 출처 — 원문은 확정본(L4), 국역은 번역(L6), 어휘·문법·비고는 주석(L7)에서 조립했다. "
        "작성자·검토 상태는 각 층에 기록된다 — "
        "LLM이 넣고 사람이 아직 손대지 않은 것은 검토 전 초안이다."
    )
    return "\n".join(out) + "\n"


def render_markdown(note: dict) -> str:
    """노트 보기 하나를 마크다운으로 — 같은 구조, 국역은 <details>로 접는다."""
    out: list[str] = [f"# {note.get('title') or note['chapter']}"]
    out.extend(f"> {b}  " for b in note.get("bibliography") or [])
    if note.get("intro") or note.get("notes"):
        out.append("\n## 해제\n")
        out.extend(p + "\n" for p in note.get("intro") or [])
        out.extend(f"- {n}" for n in note.get("notes") or [])
    out.append("\n## 원문 강독")
    for s in note.get("sections") or []:
        out.append("\n" + "#" * int(s.get("level") or 3) + " " + s["heading"] + "\n")
        out.extend(f"- {m}" for m in s.get("meta") or [])
        for seg in s.get("segments") or []:
            out.append("")
            if seg.get("label"):
                out.append(f"**{seg['label']}**\n")
            out.append(f"> {seg['text']}\n")
            if seg.get("changed"):
                out.append("※ 번역 뒤 확정본이 고쳐졌다 — 국역을 다시 볼 것\n")
            if seg.get("ko"):
                out.append(f"<details><summary>국역</summary>\n\n{seg['ko']}\n\n</details>\n")
            if seg.get("terms"):
                out.append("**어휘·문법**\n")
                for t in seg["terms"]:
                    reading = f"({t['reading']})" if t.get("reading") else ""
                    out.append(f"- **{t['term']}**{reading} — {t['gloss']}")
            if seg.get("check"):
                out.append(f"\n※ 검토 — {seg['check']}")
    if note.get("points"):
        out.append("\n## 독해 요점\n")
        out.extend(f"{i}. {p}" for i, p in enumerate(note["points"], 1))
    return "\n".join(out) + "\n"


def note_slug(chapter: str) -> str:
    """파일 이름 — 장 제목의 글자·숫자만 남긴다."""
    s = re.sub(r"[^\w]+", "_", chapter, flags=re.UNICODE).strip("_")
    return s[:60] or "note"


def note_filename(order: int, chapter: str, ext: str) -> str:
    """노트 파일 이름 — 장 순번을 앞에 붙인다. 제목만 쓰면 «A-B»와 «A B»가 같은 이름이 되어
    한 장이 다른 장을 덮는다(Codex 지적 2026-09-30)."""
    return f"노트_{order:02d}_{note_slug(chapter)}.{ext}"
