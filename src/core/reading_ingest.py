"""LLM이 돌려준 «강독 결과»를 기존 층에 나눠 담는다 (D-131).

왜 새 저장 형식을 만들지 않는가 (2026-09-30 사용자 지시):
    강독할 때마다 노트 형식은 달라질 수 있다. 형식마다 저장 스키마를 만들면 형식이 바뀔 때마다
    데이터를 옮겨야 한다. 그래서 **저장은 이미 있는 층에** 하고, 노트는 그 층들에서 그때그때
    다시 조립한다(export/reading_note.py). 층의 대응:

        OCR 교정            → L4 확정본(원본 저장소)
        장(章)·문서 항목     → 편성 경계(원본 저장소, D-092·D-097) — 장은 층위 1, 항목은 2~
        원문 구획(○①…)의 국역 → L6 번역 항목(해석 저장소) — 단위 안 글자 범위
        어휘·문법            → L7 사전형 주석(headword·headword_reading·category·dictionary_meaning)
        해제·서지·요점·문서 정보·검토 메모 → L7 «비고(note)» 주석

    LLM의 답 모양(아래 check_answer)은 저장 형식이 아니라 **프롬프트의 답 형식**이다 — 다른 LLM
    기능이 JSON 답을 받아 층에 옮기는 것과 같다(D-127 parse_llm_items의 자리).

사람의 작업을 지키는 규칙 (Codex·문서 교차 확인 반영, 2026-09-30):
    - L4: «들이기가 쓴 L4»여야만 덮는다 — 마지막 커밋이 들이기이고, 작업 파일이 그 커밋과 같고
      (편집기 저장은 커밋하지 않으므로 커밋 안 된 수정이 곧 사람의 수정이다), 그 쪽의 교정 기록
      (corrections, 교정 탭)이 비어 있을 때. 하나라도 아니면 사람의 것으로 보고 두고 알린다.
    - L6·L7: 이 들이기가 넣었고(draft_id = IMPORT_TAG) 아직 초안(status draft)인 항목만 바꾼다.
      사람이 고치면 번역·주석 수정이 draft_id를 떼므로(core.translation·core.annotation)
      재들이기가 건드리지 않는다.
    - 경계: 사람이 세운 경계는 옮기지도 고치지도 않는다. 들이기 경계는 이 답이 다룬 쪽에서만
      다시 쓰거나 지우고, 사람의 번역·주석이 가리키는 경계는 지우지 않는다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

IMPORT_TAG = "reading-import"  # L6 translator.draft_id · L7 annotator.draft_id · 경계 reasons 표식
COMMIT_PREFIX = "강독 결과 반영"
# 장 단위 비고: (L7 note 주석의 label, 답의 칸). export/reading_note.py도 이것을 쓴다.
CHAPTER_NOTES = (
    ("서지", "bibliography"),
    ("해제", "intro"),
    ("해제 덧붙임", "notes"),
    ("독해 요점", "points"),
)
_CATEGORIES = {
    "Person", "Place", "Event", "Timespan", "Object", "Record",
    "ArtWork", "Food", "Clothing", "Concept", "Grammar",
}  # fmt: skip
_REPO_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


# ── 답 모양 확인 ─────────────────────────────────────────


def _is_str(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _str_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _check_segment(g, where: str, p: list[str]) -> None:
    if not isinstance(g, dict) or not _is_str(g.get("text")):
        p.append(f"{where}: 원문(text)이 없습니다")
        return
    for k in ("ko", "check", "label"):
        if g.get(k) is not None and not isinstance(g[k], str):
            p.append(f"{where}.{k}는 글이어야 합니다")
    terms = g.get("terms", [])
    if not isinstance(terms, list):
        p.append(f"{where}.terms는 목록이어야 합니다")
        return
    for t_i, t in enumerate(terms):
        if not isinstance(t, dict) or not _is_str(t.get("term")):
            p.append(f"{where}.terms[{t_i}]: term(글)이 없습니다")
        elif any(
            t.get(k) is not None and not isinstance(t[k], str) for k in ("reading", "gloss", "type")
        ):
            p.append(f"{where}.terms[{t_i}]: reading·gloss·type은 글이어야 합니다")


def check_answer(ans: dict) -> list[str]:
    """LLM 답의 모양을 **쓰기 전에** 끝까지 확인한다. 출력: 문제 목록(비면 통과).

    저장 스키마가 아니라 답 형식이다. 필수: chapter(글), sections[{heading, segments[{text}]}].
    선택 칸도 있으면 모양을 본다 — 모양이 틀린 칸이 L4·경계를 쓴 뒤에 터지면 반쯤 들어간
    상태가 남는다(Codex 지적 2026-09-30).
    """
    p: list[str] = []
    if not isinstance(ans, dict):
        return ["답은 {…} 모양이어야 합니다"]
    if not _is_str(ans.get("chapter")):
        p.append("chapter(장 제목)가 없습니다")
    for key in ("bibliography", "intro", "notes", "points"):
        if ans.get(key) is not None and not _str_list(ans[key]):
            p.append(f"{key}는 글의 목록이어야 합니다")
    secs = ans.get("sections")
    if not isinstance(secs, list):
        p.append("sections(문서 항목 목록)가 없습니다")
        secs = []
    for i, s in enumerate(secs):
        if not isinstance(s, dict) or not _is_str(s.get("heading")):
            p.append(f"sections[{i}]: heading이 없습니다")
            continue
        pg = s.get("page")
        if pg is not None and (isinstance(pg, bool) or not isinstance(pg, int) or pg < 1):
            p.append(f"sections[{i}].page는 1 이상의 정수여야 합니다")
        lv = s.get("level", 3)
        if isinstance(lv, bool) or not isinstance(lv, int) or not 2 <= lv <= 6:
            p.append(f"sections[{i}].level은 2~6의 정수여야 합니다")
        if s.get("meta") is not None and not _str_list(s["meta"]):
            p.append(f"sections[{i}].meta는 글의 목록이어야 합니다")
        segs = s.get("segments", [])
        if not isinstance(segs, list):
            p.append(f"sections[{i}].segments는 목록이어야 합니다")
            continue
        for j, g in enumerate(segs):
            _check_segment(g, f"sections[{i}].segments[{j}]", p)
    corr = ans.get("corrections", [])
    if not isinstance(corr, list):
        p.append("corrections는 목록이어야 합니다")
        corr = []
    for i, c in enumerate(corr):
        pg = c.get("page") if isinstance(c, dict) else None
        if (
            not isinstance(c, dict)
            or isinstance(pg, bool)
            or not isinstance(pg, int)
            or pg < 1
            or not isinstance(c.get("text"), str)
        ):
            p.append(f"corrections[{i}]: page(1 이상 정수)와 text(글)가 있어야 합니다")
    return p


# ── 글자 대조 ────────────────────────────────────────────


def _compact_map(text: str) -> tuple[str, list[int]]:
    """공백·줄바꿈을 뺀 글자열과, 그 글자마다 원래 위치. 세로 열 끊김과 무관하게 찾으려고."""
    out, idx = [], []
    for i, ch in enumerate(text):
        if not ch.isspace():
            out.append(ch)
            idx.append(i)
    return "".join(out), idx


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _ratio(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def locate(text: str, needle: str, start_at: int = 0) -> Optional[tuple[int, int]]:
    """needle이 text의 어디인가 — 공백·줄바꿈을 무시하고 찾는다. 출력: (시작, 끝 포함) 또는 None.

    순서: ① 통째로 ② 답이 줄 구분으로 넣은 « / »를 빼고 ③ 앞 8자·뒤 8자로 양 끝을 잡되 **그 사이
    전체가 needle과 0.85 이상 같을 때만**(가운데가 전부 다른 글을 물지 않게) ④ 근사(_locate_fuzzy).
    start_at은 원래 text의 위치 — 구획은 순서대로 오므로 앞 구획 뒤에서부터 찾는다.
    """
    comp, idx = _compact_map(text)
    if " / " in needle:
        hit = locate(text, needle.replace(" / ", ""), start_at)
        if hit:
            return hit
    n = _norm(needle)
    if not n or not comp:
        return None
    ci = next((k for k, i in enumerate(idx) if i >= start_at), len(idx))
    pos = comp.find(n, ci)
    if pos >= 0:
        return idx[pos], idx[pos + len(n) - 1]
    if len(n) >= 16:
        head, tail = n[:8], n[-8:]
        a = comp.find(head, ci)
        if a >= 0:
            b = comp.find(tail, a + 8)
            if b >= 0 and b - a <= len(n) * 2 and _ratio(comp[a : b + 8], n) >= 0.85:
                return idx[a], idx[b + 7]
    return _locate_fuzzy(comp, idx, n, ci)


def _locate_fuzzy(comp: str, idx: list[int], n: str, ci: int) -> Optional[tuple[int, int]]:
    """마지막 수단 — 字體만 다른 글자(稅/税·說/説)가 여럿 섞여 정확히 못 찾을 때.

    needle과 가장 길게 겹치는 부분(6자 이상)을 닻으로, 닻 둘레에서 일치 구간의 처음~끝을 창으로
    잡는다(길이를 고정하면 교정에서 빠진 글자만큼 창이 밀려 남의 글자를 문다). 받는 조건 둘:
    창과 needle의 일치율 0.8 이상, 그리고 needle의 **앞뒤에서 맞지 않고 잘려 나간 글자**가 각각
    max(2, 길이의 10%) 이하 — 앞뒤가 크게 다른 글의 가운데만 물어 전체 구획으로 삼지 않게.
    """
    from difflib import SequenceMatcher

    if len(n) < 8 or ci >= len(comp):
        return None
    hay = comp[ci : ci + max(len(n) * 4, 400)]
    m = SequenceMatcher(None, hay, n, autojunk=False).find_longest_match(0, len(hay), 0, len(n))
    if m.size < 6:
        return None
    lo = max(0, m.a - m.b - 4)
    region = hay[lo : m.a - m.b + len(n) + 4]
    blocks = [
        b for b in SequenceMatcher(None, region, n, autojunk=False).get_matching_blocks() if b.size
    ]
    if not blocks:
        return None
    slack = max(2, len(n) // 10)
    if blocks[0].b > slack or len(n) - (blocks[-1].b + blocks[-1].size) > slack:
        return None
    s, e = blocks[0].a, blocks[-1].a + blocks[-1].size - 1
    if _ratio(region[s : e + 1], n) < 0.8:
        return None
    return idx[ci + lo + s], idx[ci + lo + e]


def _heading_original(heading: str) -> str:
    """「原題 (국역 제목)」에서 원제만. 한국어 괄호는 **어디에 있든** 떼고, 〔…〕 편자 표시도 뺀다.

    예: 「一二　日清戦争 (청일전쟁) — 朝鮮問題…」 → 「一二　日清戦争 — 朝鮮問題…」
    """
    # CJK 문자 클래스는 regex 모듈의 유니코드 속성으로(CJK 텍스트 계약 R1 — 범위 표기는 빠뜨린다)
    import regex

    h = regex.sub(r"\s*\([^()]*\p{Hangul}[^()]*\)", "", heading).strip()
    h = re.sub(r"^〔[^〕]*〕\s*", "", h)
    return h


def _needle_pieces(text: str) -> list[str]:
    """찾을 글의 후보 — 통째로, 그리고 « — »·« / »·« | »로 나눈 조각(4자 이상).

    답은 제목의 여러 줄을 « — »나 « / »로 이어 적곤 한다. 확정본에는 그 기호가 없다.
    """
    out = [text]
    out += [p for p in re.split(r"\s+—\s+|\s/\s|\s\|\s", text) if len(_norm(p)) >= 4]
    return list(dict.fromkeys(out))


# ── L4 ──────────────────────────────────────────────────


def _written_by_import(doc_path: Path, part_id: str, page: int) -> bool:
    """이 쪽 L4가 «들이기가 쓴 그대로»인가 — 그래야 새 답으로 덮어도 사람의 수정을 잃지 않는다.

    셋이 모두 맞아야 참: ① 쪽 파일의 마지막 커밋이 들이기 ② 작업 파일이 그 커밋과 같다(편집기
    저장은 커밋하지 않는다 — 커밋 안 된 수정은 사람의 것) ③ 교정 탭의 교정 기록이 비어 있다
    (교정 탭은 corrections 파일만 커밋하고 쪽 파일은 그대로다).
    """
    try:
        import git

        rel = f"L4_text/pages/{part_id}_page_{page:03d}.txt"
        repo = git.Repo(doc_path)
        last = next(repo.iter_commits(paths=rel, max_count=1), None)
        if not (last and str(last.summary).startswith(COMMIT_PREFIX)):
            return False
        if repo.git.status("--porcelain", "--", rel).strip():
            return False
    except Exception:  # noqa: BLE001 — 이력을 못 읽으면 지키는 쪽으로
        return False
    corr = doc_path / "L4_text" / "corrections" / f"{part_id}_page_{page:03d}_corrections.json"
    if corr.exists():
        try:
            if json.loads(corr.read_text(encoding="utf-8")).get("corrections"):
                return False
        except (OSError, ValueError):
            return False
    return True


def apply_corrections(doc_path: Path, part_id: str, corrections: list[dict]) -> tuple[list, list]:
    """교정문을 L4에 쓴다. 출력: (쓴 쪽, 사람이 고친 L4라 둔 쪽)."""
    from core.document import save_page_text
    from ocr.read_book import l4_is_hand_edited

    written, kept = [], []
    for c in corrections or []:
        page = int(c["page"])
        if l4_is_hand_edited(doc_path, part_id, page) and not _written_by_import(
            doc_path, part_id, page
        ):
            kept.append(page)
            continue
        save_page_text(doc_path, part_id, page, str(c["text"]).rstrip() + "\n")
        written.append(page)
    return written, kept


# ── 경계 ────────────────────────────────────────────────


def _find_in_pages(page_texts: dict, pages: list[int], needle: str, after: Optional[tuple] = None):
    """쪽들에서 needle(공백 무시)을 찾는다. after=(쪽, 오프셋)이면 그 뒤에서. 출력: (쪽, 오프셋)."""
    for p in pages:
        t = page_texts.get(p)
        if not t:
            continue
        start = after[1] + 1 if after and after[0] == p else 0
        if after and p < after[0]:
            continue
        hit = locate(t, needle, start)
        if hit:
            return p, hit[0]
    return None


def answer_pages(ans: dict) -> set[int]:
    """이 답이 다룬 쪽 — 항목의 시작 쪽과 교정한 쪽.

    경계를 다시 쓰고 지우는 범위다. 최소~최대로 넓히지 않는다 — 10·20쪽만 다룬 답이 15쪽의 다른
    답 경계를 지우면 안 된다(Codex 지적 2026-09-30).
    """
    return {int(s["page"]) for s in ans.get("sections") or [] if s.get("page")} | {
        int(c["page"]) for c in ans.get("corrections") or []
    }


def place_boundaries(
    doc_path: Path, doc_id: str, part_id: str, ans: dict, chapter_page: Optional[int]
) -> dict:
    """장(층위 1)과 문서 항목(층위 2~)의 경계를 넣는다. 지우지는 않는다 — 지울 후보만 돌려준다.

    출력: {"chapter_id", "section_ids": [id|None …], "added", "unplaced": [heading …],
           "stale_ids": [이 답이 다룬 쪽에 있으나 이번 답에 안 나온 옛 들이기 경계]}.
    자리: 첫 구획 원문(24자)과 항목 원제를 그 항목의 시작 쪽부터 세 쪽 안에서 공백 무시로 찾는다.
    먼저 앞 항목 자리 뒤에서(순서를 지켜), 못 찾으면 창 안에서 순서 없이 찾는다 — 답의 항목 순서가
    확정본의 읽기 순서와 다를 때가 있다(펼침 쪽의 좌우, 머리가 떨어져 나간 문서).
    다시 들일 때: 이 들이기가 만든 경계(reasons에 IMPORT_TAG) 가운데 **이 답이 다룬 쪽 가까이에서**
    제목·층위가 같은 것을 **가장 가까운 것부터** 다시 쓴다(id 유지). 같은 제목이 되풀이되는 장
    (「同返事」)에서 먼 쪽의 경계를 끌어오지 않게. 사람이 세운 경계는 고치지 않는다.
    """
    from core.boundaries import (
        anchor_text_at,
        insert_boundary,
        load_doc_boundaries,
        new_boundary,
        position_from_char,
        save_doc_boundaries,
    )
    from core.read_plan import title_anchor
    from core.segmentation import collect_document_lines

    _lines, page_texts = collect_document_lines(doc_path, part_id, None)
    data = load_doc_boundaries(doc_path, doc_id, part_id)
    before = len(data.get("boundaries") or [])
    pages = sorted(page_texts)
    chapter = str(ans["chapter"]).strip()
    covered = answer_pages(ans)
    near = {p + d for p in covered for d in (-1, 0, 1)}
    mine = [b for b in data.get("boundaries") or [] if IMPORT_TAG in (b.get("reasons") or [])]
    claimed: set[str] = set()

    def put(pos: dict, level: int, title: str, role: str, anywhere: bool = False) -> dict:
        """같은 제목·층위의 옛 들이기 경계(가까운 것부터)를 옮기거나, 없으면 새로 넣는다."""
        cands = [
            b
            for b in mine
            if b["id"] not in claimed
            and b.get("title") == title
            and b.get("level") == level
            and (anywhere or int(b["start"]["page"]) in near)
        ]
        cands.sort(
            key=lambda b: (
                abs(int(b["start"]["page"]) - pos["page"]),
                abs(int(b["start"].get("line", 0)) - pos["line"]),
            )
        )
        if cands:
            old = cands[0]
            old["start"] = {"page": pos["page"], "line": pos["line"], "offset": pos["offset"]}
            old["anchor_text"] = anchor_text_at(page_texts, old["start"])
            claimed.add(old["id"])
            return old
        b = new_boundary(pos, level=level, title=title, role=role, page_texts=page_texts)
        b["reasons"] = [IMPORT_TAG]
        placed = insert_boundary(data, b)
        claimed.add(placed["id"])
        return placed

    # 장 — 제목 글자(번호 머리를 뗀 앞 6자)가 있는 **줄의 첫머리**. 손글씨 번호(「二、」)가 제목
    # 앞에 붙은 줄에서 글자 자리에 세우면 그 앞의 두 글자가 앞 장으로 떨어진다(2026-09-30 실측).
    # 장 경계는 한 장에 하나라 권 어디에 있든 다시 쓴다(anywhere).
    chapter_id = None
    if chapter_page:
        found = _find_in_pages(page_texts, [chapter_page], title_anchor(chapter))
        pos = position_from_char(page_texts, chapter_page, found[1] if found else 0)
        pos["offset"] = 0
        chapter_id = put(pos, 1, chapter, "container", anywhere=True)["id"]
    section_ids: list[Optional[str]] = []
    unplaced: list[str] = []
    after = (chapter_page, -1) if chapter_page else None
    for s in ans.get("sections") or []:
        start_page = int(s.get("page") or (after[0] if after else pages[0] if pages else 1))
        window = [p for p in pages if start_page <= p <= start_page + 2]
        segs = s.get("segments") or []
        # 첫 구획 원문(24자)을 제목보다 먼저 — 짧은 제목(「豫審終結決定」)은 다른 문서 안의 같은
        # 글자에 붙는다. 머리가 떨어져 나간 문서는 제목이 제자리에 아예 없다(2026-09-30 실측).
        needles = [p[:24] for p in _needle_pieces(segs[0]["text"])] if segs else []
        needles += _needle_pieces(_heading_original(s["heading"]))
        hit = None
        for constraint in (after, None):
            for nd in needles:
                if len(_norm(nd)) >= 4:
                    hit = _find_in_pages(page_texts, window, nd, constraint)
                    if hit:
                        break
            if hit:
                break
        if not hit:
            section_ids.append(None)
            unplaced.append(s["heading"])
            continue
        level = max(2, int(s.get("level") or 3) - 1)
        pos = position_from_char(page_texts, hit[0], hit[1])
        placed = put(pos, level, s["heading"], "article")
        if IMPORT_TAG in (placed.get("reasons") or []):
            placed["title"] = s["heading"]
        # 같은 자리·층위의 **사람 경계**가 돌아왔으면 그 경계를 쓰되 제목은 고치지 않는다
        section_ids.append(placed["id"])
        after = hit
    # 지울 후보: 이 답이 다룬 쪽에 있는 옛 들이기 경계 가운데 이번에 쓰이지 않은 것.
    # 못 찾은 항목(unplaced)과 같은 제목의 경계는 후보에서 뺀다 — «답에서 빠짐»이 아니라 «대조
    # 실패»일 수 있다(Codex 지적 2026-09-30).
    keep_titles = set(unplaced)
    stale = [
        b["id"]
        for b in mine
        if b["id"] not in claimed
        and b.get("level") != 1
        and int(b["start"]["page"]) in covered
        and b.get("title") not in keep_titles
    ]
    save_doc_boundaries(doc_path, data)
    return {
        "chapter_id": chapter_id,
        "section_ids": section_ids,
        "added": len(data.get("boundaries") or []) - before,
        "unplaced": unplaced,
        "stale_ids": stale,
    }


def remove_boundaries(doc_path: Path, doc_id: str, part_id: str, ids: list[str]) -> None:
    """경계 id들을 지운다(지울지는 호출자가 사람 참조를 보고 정했다)."""
    from core.boundaries import load_doc_boundaries, save_doc_boundaries

    if not ids:
        return
    drop = set(ids)
    data = load_doc_boundaries(doc_path, doc_id, part_id)
    data["boundaries"] = [b for b in data["boundaries"] if b["id"] not in drop]
    save_doc_boundaries(doc_path, data)


# ── 해석 저장소 L6·L7 ────────────────────────────────────


def default_interp_id(doc_id: str) -> str:
    """강독 결과를 담을 해석 저장소 id — 문헌 id + _reading (id 규칙: 영문 소문자로 시작, 64자)."""
    return f"{doc_id}_reading"[:64]


def check_interp_id(library: Path, doc_id: str, interp_id: str) -> Path:
    """해석 저장소 id가 규칙에 맞고, 이미 있으면 **이 문헌의** 저장소인가. 출력: 저장소 경로.

    경로 이탈(«../»)과 다른 문헌의 해석 저장소에 쓰는 일을 막는다. 틀리면 ValueError.
    """
    if not _REPO_ID.match(str(interp_id or "")):
        raise ValueError(
            f"해석 저장소 id가 규칙에 맞지 않습니다: {interp_id!r} (영문 소문자로 시작, 64자)"
        )
    path = Path(library) / "interpretations" / interp_id
    mf = path / "manifest.json"
    if mf.exists():
        try:
            src = json.loads(mf.read_text(encoding="utf-8")).get("source_document_id")
        except (OSError, ValueError):
            src = None
        if src and src != doc_id:
            raise ValueError(f"해석 저장소 {interp_id}은(는) 다른 문헌({src})의 것입니다")
    return path


def ensure_interpretation(library: Path, doc_id: str, interp_id: str, title: str) -> Path:
    """해석 저장소가 없으면 만들고, 있으면 기반 커밋을 지금 원본으로 올린다(L4를 고쳤으므로)."""
    from core.interpretation import create_interpretation, update_base

    path = check_interp_id(library, doc_id, interp_id)
    if not (path / "manifest.json").exists():
        return create_interpretation(
            library, interp_id, doc_id, "hybrid", "LLM 강독(사람 검토 전)", title=title
        )
    try:
        update_base(library, interp_id)
    except Exception:  # noqa: BLE001 — 기반 갱신 실패는 들이기를 막지 않는다(화면이 «낡음»으로 알린다)
        pass
    return path


def _note_annotation(start: int, end: int, label: str, text: str, model: str) -> dict:
    return {
        "target": {"start": start, "end": max(start, end)},
        "type": "note",
        "content": {"label": label, "description": text, "references": []},
        "dictionary": None,
        "annotator": {"type": "llm", "model": model, "draft_id": IMPORT_TAG},
        "status": "draft",
    }


def _term_annotation(t: dict, start: int, end: int, seg_text: str, ko: str, model: str) -> dict:
    from core.annotation_dict_llm import type_for

    cat = t.get("type") if t.get("type") in _CATEGORIES else None
    gloss = (t.get("gloss") or "").strip()
    return {
        "target": {"start": start, "end": max(start, end)},
        "type": type_for(None, cat),
        "content": {"label": t["term"], "description": gloss, "references": []},
        "dictionary": {
            "headword": t["term"],
            "headword_reading": t.get("reading") or None,
            "dictionary_meaning": gloss,
            "contextual_meaning": None,
            "source_references": [],
            "related_terms": [],
            "notes": None,
            "category": cat,
            "scope": None,
            "sense_note": None,
        },
        "current_stage": "from_both",
        "generation_history": [],
        "source_text_snapshot": seg_text,
        "translation_snapshot": ko or None,
        "annotator": {"type": "llm", "model": model, "draft_id": IMPORT_TAG},
        "status": "draft",
    }


def _ours(entry: dict, who: str) -> bool:
    """이 들이기가 넣었고 아직 아무도 손대지 않은 초안인가(재들이기가 바꿔도 되는가)."""
    return (entry.get(who) or {}).get("draft_id") == IMPORT_TAG and entry.get(
        "status", "draft"
    ) == "draft"


def _layer_pages(interp_path: Path, part_id: str) -> list[int]:
    pages: set[int] = set()
    for sub in ("L6_translation/main_text", "L7_annotation/main_text"):
        for f in (interp_path / sub).glob(f"{part_id}_page_*.json"):
            m = re.search(r"_page_(\d+)", f.name)
            if m:
                pages.add(int(m.group(1)))
    return sorted(pages)


def human_refs(interp_path: Path, part_id: str, block_ids: set[str]) -> set[str]:
    """이 block_id들 가운데 **사람의** 번역·주석이 가리키는 것 — 그런 경계는 지우지 않는다."""
    from core.annotation import load_annotations
    from core.translation import load_translations

    found: set[str] = set()
    if not interp_path.exists():
        return found
    for page in _layer_pages(interp_path, part_id):
        for t in load_translations(interp_path, part_id, page).get("translations") or []:
            bid = (t.get("source") or {}).get("block_id")
            if bid in block_ids and not _ours(t, "translator"):
                found.add(bid)
        for b in load_annotations(interp_path, part_id, page).get("blocks") or []:
            if b.get("block_id") in block_ids and any(
                not _ours(a, "annotator") for a in b.get("annotations") or []
            ):
                found.add(b["block_id"])
    return found


def _purge(tr_data: dict, ann_data: dict, block_id: str, labels: Optional[set] = None) -> bool:
    """이 들이기가 넣은 초안만 지운다. labels가 있으면 그 라벨의 비고(note)만. 출력: 바뀌었나."""
    changed = False
    if labels is None:
        keep = [
            t
            for t in tr_data.get("translations") or []
            if not ((t.get("source") or {}).get("block_id") == block_id and _ours(t, "translator"))
        ]
        if len(keep) != len(tr_data.get("translations") or []):
            tr_data["translations"] = keep
            changed = True
    for b in ann_data.get("blocks") or []:
        if b.get("block_id") != block_id:
            continue
        keep_a = [
            a
            for a in b.get("annotations") or []
            if not (
                _ours(a, "annotator")
                and (labels is None or (a.get("content") or {}).get("label") in labels)
            )
        ]
        if len(keep_a) != len(b.get("annotations") or []):
            b["annotations"] = keep_a
            changed = True
    return changed


def _purge_everywhere(interp_path: Path, part_id: str, targets: dict[str, Optional[set]]) -> None:
    """모든 쪽 파일에서 이 들이기의 초안을 치운다. targets: {block_id: None(전부) | {비고 라벨}}.

    왜 모든 쪽인가: 경계가 다른 쪽으로 옮겨지면 단위의 첫 쪽(L6·L7 파일)이 바뀐다. 첫 쪽만
    치우면 옛 쪽에 옛 초안이 남아 두 벌이 된다(Codex 지적 2026-09-30). 바뀐 파일만 쓴다.
    """
    from core.annotation import load_annotations, save_annotations
    from core.translation import load_translations, save_translations

    for page in _layer_pages(interp_path, part_id):
        tr = load_translations(interp_path, part_id, page)
        ann = load_annotations(interp_path, part_id, page)
        changed = False
        for bid, labels in targets.items():
            changed = _purge(tr, ann, bid, labels) or changed
        if changed:
            save_translations(interp_path, part_id, page, tr)
            save_annotations(interp_path, part_id, page, ann)


def ingest_answer(
    library: str | Path,
    doc_id: str,
    part_id: str,
    ans: dict,
    interp_id: Optional[str] = None,
    model: str = "LLM",
) -> dict:
    """강독 결과 한 벌을 층에 나눠 담는다. 입력: 서고, 문헌, 권, LLM 답, 해석 저장소 id, 모델 이름.

    출력: {"corrected", "kept", "boundaries_added", "boundaries_removed", "boundaries_kept",
           "unplaced_sections", "unplaced_segments", "approx_segments", "translations",
           "annotations", "relabeled_pages", "interp_id"}.
    순서: 모양·id 확인(쓰기 전) → L4 교정 → 경계 → 사람 참조 없는 옛 경계 지우기 → 커밋 →
    해석 저장소(기반을 지금 원본으로) → 옛 초안 치우기(모든 쪽) → L6·L7 → 커밋.
    L4·경계를 먼저 끝내야 해석 저장소가 곧바로 «원본이 바뀜»이 되지 않는다.
    """
    from core.annotation import add_annotation, load_annotations, save_annotations
    from core.boundaries import compute_units, load_doc_boundaries
    from core.document import get_document_info, git_commit_document
    from core.interpretation import git_commit_interpretation
    from core.segmentation import collect_document_lines
    from core.translation import add_translation, load_translations, save_translations
    from ocr.read_book import check_part_id, load_plan

    problems = check_answer(ans)
    if problems:
        raise ValueError("강독 결과의 모양이 맞지 않습니다: " + "; ".join(problems[:8]))
    library = Path(library)
    check_part_id(part_id)
    interp_id = interp_id or default_interp_id(doc_id)
    interp_path = check_interp_id(
        library, doc_id, interp_id
    )  # 쓰기 전에 — 틀린 id로 L4를 바꾸지 않게
    doc_path = library / "documents" / doc_id
    chapter = ans["chapter"].strip()

    # 1) L4 교정
    written, kept = apply_corrections(doc_path, part_id, ans.get("corrections") or [])
    if written:
        git_commit_document(doc_path, f"{COMMIT_PREFIX}: {chapter} — 교정 {len(written)}쪽")

    # 1-1) 손글씨 쪽 번호 — 계획의 쪽 이름표 규칙과 다르면 그 쪽만 낱쪽 이름표로 덧붙인다
    plan = load_plan(doc_path, part_id) or {}
    relabeled = _reconcile_hand_pages(doc_path, part_id, plan, ans.get("corrections") or [])

    # 2) 경계 — 장 시작 쪽은 작업 계획의 chapters에서(제목이 같을 때), 없으면 답의 가장 앞 쪽
    chapter_page = next(
        (c["page"] for c in plan.get("chapters") or [] if c["title"].strip() == chapter), None
    )
    if chapter_page is None:
        pages = [s.get("page") for s in ans["sections"] if s.get("page")]
        chapter_page = min(pages) if pages else None
    placed = place_boundaries(doc_path, doc_id, part_id, ans, chapter_page)

    # 3) 지울 후보 가운데 사람의 번역·주석이 가리키는 경계는 남긴다
    stale = set(placed["stale_ids"])
    held = human_refs(interp_path, part_id, stale) if stale else set()
    removed = sorted(stale - held)
    remove_boundaries(doc_path, doc_id, part_id, removed)
    git_commit_document(
        doc_path, f"편성: {chapter} — 강독 항목 경계 +{placed['added']} −{len(removed)}"
    )
    title = get_document_info(doc_path).get("title") or doc_id
    interp_path = ensure_interpretation(library, doc_id, interp_id, f"{title} 강독")

    # 4) 옛 초안 치우기 — 이번에 다시 쓰는 단위와 지운 단위 모두, **모든 쪽 파일에서**
    targets: dict[str, Optional[set]] = {bid: None for bid in placed["section_ids"] if bid}
    targets.update({bid: None for bid in removed})
    if placed["chapter_id"]:
        given = {label for label, key in CHAPTER_NOTES if ans.get(key)}
        if given:  # 장 단위 비고는 이 답이 준 칸만 바꾼다(한 장을 여러 답으로 나눠 들이므로)
            targets[placed["chapter_id"]] = given
    _purge_everywhere(interp_path, part_id, targets)

    # 5) 단위(경계에서 새로 만든 읽기 보기)와 L6·L7
    lines, page_texts = collect_document_lines(doc_path, part_id, None)
    units = {
        u["id"]: u
        for u in compute_units(load_doc_boundaries(doc_path, doc_id, part_id), lines, page_texts)
    }
    files: dict[int, tuple[dict, dict]] = {}

    def page_files(page: int) -> tuple[dict, dict]:
        if page not in files:
            files[page] = (
                load_translations(interp_path, part_id, page),
                load_annotations(interp_path, part_id, page),
            )
        return files[page]

    n_tr = n_ann = 0
    unplaced_segments: list[str] = []
    approx_segments: list[str] = []
    chap = units.get(placed["chapter_id"]) if placed["chapter_id"] else None
    if chap:
        _tr, ann = page_files(int(chap["source_ref"]["page"]))
        end = max(0, len(chap["original_text"]) - 1)
        for label, key in CHAPTER_NOTES:
            items = [x for x in ans.get(key) or [] if x.strip()]
            if items:
                note = _note_annotation(0, end, label, "\n".join(items), model)
                add_annotation(ann, chap["id"], note)
                n_ann += 1
    for s, uid in zip(ans["sections"], placed["section_ids"]):
        unit = units.get(uid) if uid else None
        if not unit:
            continue
        text = unit["original_text"]
        tr, ann = page_files(int(unit["source_ref"]["page"]))
        end_all = max(0, len(text) - 1)
        if s.get("meta"):
            note = _note_annotation(0, end_all, "문서 정보", "\n".join(s["meta"]), model)
            add_annotation(ann, uid, note)
            n_ann += 1
        cursor = 0
        used: list[tuple[int, int]] = []
        for g in s.get("segments") or []:
            # 순서대로(앞 구획 뒤에서), 못 찾으면 단위 처음부터 — 답의 구획 순서가 읽기 순서와
            # 어긋난 경우. 이미 다른 구획에 준 자리와 겹치면 받지 않는다
            # (같은 원문에 두 번 붙지 않게)
            hit = locate(text, g["text"], cursor)
            if not hit:
                back = locate(text, g["text"], 0)
                if back and not any(back[0] <= ue and us <= back[1] for us, ue in used):
                    hit = back
            if not hit:
                unplaced_segments.append(f"{s['heading'][:30]} — {g['text'][:20]}")
                continue
            a, b = hit
            used.append((a, b))
            cursor = max(cursor, b + 1)
            seg_text = text[a : b + 1]
            if _norm(seg_text) != _norm(g["text"]):
                # 글자가 똑같지는 않은 자리 — 확정본과 답의 원문이 字體·한두 글자 다르다. 알린다
                approx_segments.append(
                    f"{s['heading'][:30]} — {g['text'][:20]} ≈ {_norm(seg_text)[:20]}"
                )
            ko = (g.get("ko") or "").strip()
            if ko:
                add_translation(
                    tr,
                    {
                        "source": {"block_id": uid, "start": a, "end": b},
                        "source_text": seg_text,
                        "target_language": "ko",
                        "translation": ko,
                        "translator": {"type": "llm", "model": model, "draft_id": IMPORT_TAG},
                        "status": "draft",
                        "annotation_context": None,
                    },
                )
                n_tr += 1
            for t in g.get("terms") or []:
                th = locate(seg_text, t["term"])
                ta, tb = (a + th[0], a + th[1]) if th else (a, b)
                add_annotation(ann, uid, _term_annotation(t, ta, tb, seg_text, ko, model))
                n_ann += 1
            if g.get("check"):
                add_annotation(ann, uid, _note_annotation(a, b, "검토", g["check"], model))
                n_ann += 1
    for page, (tr, ann) in files.items():
        save_translations(interp_path, part_id, page, tr)
        save_annotations(interp_path, part_id, page, ann)
    git_commit_interpretation(
        interp_path, f"{COMMIT_PREFIX}: {chapter} — 번역 {n_tr} · 주석 {n_ann}"
    )
    return {
        "corrected": written,
        "kept": kept,
        "boundaries_added": placed["added"],
        "boundaries_removed": len(removed),
        "boundaries_kept": sorted(held),
        "unplaced_sections": placed["unplaced"],
        "unplaced_segments": unplaced_segments,
        "approx_segments": approx_segments,
        "translations": n_tr,
        "annotations": n_ann,
        "relabeled_pages": relabeled,
        "interp_id": interp_id,
    }


def _reconcile_hand_pages(
    doc_path: Path, part_id: str, plan: dict, corrections: list[dict]
) -> list[int]:
    """답이 읽어 온 손글씨 쪽 번호(hand_page)를 계획의 이름표와 견준다. 다르면 낱쪽 이름표를 더한다.

    이름표 이름은 계획의 첫 이름표 이름(없으면 «교재»). 출력: 새로 붙인 쪽 목록.
    규칙에 맞추지 않고 **읽은 대로** 둔다 — 쪽 번호가 건너뛰거나 겹친 책이 실제로 있다.
    """
    from core.document import write_json_atomic
    from core.read_plan import page_label_map
    from ocr.read_book import plan_path

    if not plan:
        return []
    labels = plan.get("page_labels") or []
    name = labels[0]["name"] if labels else "교재"
    current = page_label_map(plan)  # 저장된 계획의 범위는 닫혀 있다(validate_plan)
    added = []
    for c in corrections:
        hp = str(c.get("hand_page") or "").strip()
        page = int(c["page"])
        if not hp:
            continue
        if dict(current.get(page, [])).get(name) != hp:
            labels.append({"pages": str(page), "name": name, "label": hp[:20]})
            added.append(page)
    if added:
        plan["page_labels"] = labels
        target = plan_path(doc_path, part_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(target, plan)
    return added


def load_answer(path: str | Path) -> dict:
    """답 파일 하나를 읽는다(UTF-8 JSON)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
