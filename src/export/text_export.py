"""확정본(L4)을 장별 마크다운·미디어위키 문서로 내보낸다 (D-131).

왜 필요한가:
    OCR 결과를 앱 밖에서 읽고 나누려면(강의 자료·위키·노트) 쪽 단위 텍스트가 아니라 «장» 단위
    문서가 필요하다. 장의 시작은 작업 계획(read_plan.json)의 chapters가 정한다. 사람이 교정 탭에서
    L4를 고치면 다시 내보낼 때 그대로 반영된다 — 내보내기는 언제나 L4에서 새로 만든다.

무엇을 고치고 무엇을 고치지 않는가:
    글자는 고치지 않는다. 다음 둘만 한다.
    ① 잡음 줄 빼기 — 쪽 여백의 손글씨 쪽 번호(「1/1」「198」)처럼 **아스키만으로 된 짧은 줄**과,
       접힌 자리의 선을 글자로 읽은 줄(「〇、〇〇、…」처럼 동그라미·쉼표가 대부분인 줄). 뺀 줄 수는
       돌려준다(조용히 버리지 않는다).
    ② 세로 열 잇기 — 세로쓰기의 한 열은 문장 단위가 아니다. 열이 쪽의 보통 길이보다 짧게 끝나면
       문단이 끝난 것으로 보고, ○·【·〔·( 로 시작하는 열은 새 문단으로 본다.
       잇는 규칙이 틀리면 원문 줄바꿈이 필요할 수 있어 keep_lines=True로 끌 수 있다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

_NOISE_CHARS = set("〇○、。・，,.·□-—_|/\\1234567890 ")
_PARA_STARTERS = ("○", "◎", "●", "【", "〔", "(", "（", "「", "第")


def is_noise_line(line: str) -> bool:
    """본문이 아닌 줄인가. 입력: 한 줄. 출력: True면 뺀다.

    - 아스키만으로 된 5자 이하(손글씨 쪽 번호·기호).
      한자 숫자(「四四」)는 인쇄된 쪽수일 수 있어 둔다.
    - 8자 이상인데 동그라미·쉼표·숫자가 70% 이상(접힌 자리 선·밑줄을 글자로 읽은 것).
    """
    s = line.strip()
    if not s:
        return False
    if len(s) <= 5 and all(ord(c) < 128 for c in s):
        return True
    if len(s) >= 8 and sum(c in _NOISE_CHARS for c in s) / len(s) >= 0.7:
        return True
    return False


def join_columns(lines: list[str]) -> list[str]:
    """세로 열(또는 가로 줄)을 문단으로 잇는다. 입력: 한 쪽의 줄. 출력: 문단 목록.

    «보통 길이»는 그 쪽 줄 길이의 상위 20% 값이다 — 가득 찬 열의 길이에 가깝다.
    """
    lines = [ln.strip() for ln in lines if ln.strip()]
    if not lines:
        return []
    lengths = sorted(len(ln) for ln in lines)
    full = lengths[int(len(lengths) * 0.8)] if len(lengths) > 1 else lengths[0]
    paras: list[str] = []
    buf = ""
    for ln in lines:
        if buf and ln.startswith(_PARA_STARTERS):
            paras.append(buf)
            buf = ""
        buf += ln
        if len(ln) < full * 0.8:
            paras.append(buf)
            buf = ""
    if buf:
        paras.append(buf)
    return paras


@dataclass
class Chapter:
    """내보낼 장 하나 — 제목·층위와 쪽별 줄."""

    title: str
    level: int
    pages: list[tuple[int, list[str]]] = field(default_factory=list)


def _compact(s: str) -> str:
    return re.sub(r"[\s・.·、。,()（）]", "", s)


def _title_anchor(title: str) -> str:
    """제목 대조 글자 — 정본은 core.read_plan.title_anchor(강독 들이기와 같은 규칙을 쓰려고)."""
    from core.read_plan import title_anchor

    return title_anchor(title)


def build_chapters(
    page_texts: dict[int, str], chapters: list[dict], front_title: str = "앞붙이"
) -> tuple[list[Chapter], dict]:
    """쪽 텍스트를 장으로 나눈다.

    입력: {PDF 쪽: L4 텍스트}, 계획의 chapters([{page, title, level}]), 첫 장 앞 부분의 이름.
    출력: (장 목록, {"noise_lines": 뺀 줄 수, "anchored": 제목 글자로 쪽 안 자리를 찾은 장 수}).
    장의 시작 쪽에서 제목 글자(번호 머리를 뗀 앞 6자)를 찾으면 그 줄부터 새 장이다 — 펼침 쪽은
    앞 장의 끝과 새 장의 시작이 한 쪽에 같이 있다. 못 찾으면 그 쪽 첫 줄부터.
    """
    starts = sorted(chapters, key=lambda c: (c["page"], c.get("level", 1)))
    out: list[Chapter] = [Chapter(front_title, 1)]
    stats = {"noise_lines": 0, "anchored": 0}
    by_page: dict[int, list[dict]] = {}
    for c in starts:
        by_page.setdefault(int(c["page"]), []).append(c)
    for page in sorted(page_texts):
        raw = page_texts[page].splitlines()
        lines = []
        for ln in raw:
            if is_noise_line(ln):
                stats["noise_lines"] += 1
            elif ln.strip():
                lines.append(ln.strip())
        cursor = 0
        for c in by_page.get(page, []):
            anchor = _title_anchor(c["title"])
            cut = None
            if anchor:
                for i in range(cursor, len(lines)):
                    if anchor in _compact(lines[i]):
                        cut = i
                        stats["anchored"] += 1
                        break
            if cut is None:
                cut = cursor
            if cut > cursor:
                out[-1].pages.append((page, lines[cursor:cut]))
            cursor = cut
            out.append(Chapter(c["title"], int(c.get("level") or 1)))
        if cursor < len(lines):
            out[-1].pages.append((page, lines[cursor:]))
    if not out[0].pages:
        out.pop(0)
    return out, stats


def page_marker(page: int, labels: Optional[list[tuple[str, str]]] = None) -> str:
    """쪽 표시 글자. 예: «PDF p.46 · 교재 42면» — PDF 쪽과 다른 체계(손글씨 면 등)를 나란히 둔다."""
    parts = [f"PDF p.{page}"] + [f"{name} {value}면" for name, value in labels or []]
    return " · ".join(parts)


def _body(ch: Chapter, fmt: str, keep_lines: bool, labels: Optional[dict] = None) -> str:
    parts: list[str] = []
    for page, lines in ch.pages:
        mark = page_marker(page, (labels or {}).get(page))
        if fmt == "md":
            parts.append(f'<a id="p{page}"></a>**[{mark}]**')
        else:
            parts.append(f"<span id=\"p{page}\">'''[{mark}]'''</span>")
        if keep_lines:
            parts.append(("  \n" if fmt == "md" else "<br />\n").join(lines))
        else:
            parts.extend(join_columns(lines))
    return "\n\n".join(parts)


def _heading(title: str, level: int, fmt: str) -> str:
    level = max(1, min(level, 5))
    if fmt == "md":
        return "#" * (level + 1) + " " + title
    bar = "=" * (level + 1)
    return f"{bar} {title} {bar}"


def render(
    book_title: str,
    chapters: list[Chapter],
    fmt: str = "md",
    keep_lines: bool = False,
    source_note: Optional[str] = None,
    labels: Optional[dict] = None,
) -> dict[str, str]:
    """장 목록을 파일들로. 입력: 책 제목, 장, 형식("md" | "wiki"), 줄 유지 여부, 출처 한 줄,
    쪽 이름표({PDF 쪽: [(이름, 값)]} — read_plan.page_label_map).

    출력: {파일명: 내용} — 층위 1 장마다 한 파일(그 아래 층위는 같은 파일의 소제목)과
    목차 파일(index), 모두 이은 한 파일(all). 파일명은 번호만 쓴다(한자 제목은 파일 시스템마다
    다르게 깨진다).
    """
    if fmt not in ("md", "wiki"):
        raise ValueError(f"형식은 md 또는 wiki: {fmt}")
    ext = "md" if fmt == "md" else "wiki"
    groups: list[list[Chapter]] = []
    for ch in chapters:
        if ch.level <= 1 or not groups:
            groups.append([ch])
        else:
            groups[-1].append(ch)
    files: dict[str, str] = {}
    toc_lines: list[str] = []
    all_parts: list[str] = []
    note = f"\n\n{source_note}" if source_note else ""
    for n, group in enumerate(groups, 1):
        name = f"{n:02d}.{ext}"
        head = group[0]
        first_page = next((p for c in group for p, _ in c.pages), None)
        texts = []
        for ch in group:
            texts.append(_heading(ch.title, ch.level, fmt))
            texts.append(_body(ch, fmt, keep_lines, labels))
        doc = "\n\n".join(texts) + "\n"
        files[name] = doc
        all_parts.append(doc)
        where = (
            f" ({page_marker(first_page, (labels or {}).get(first_page))}~)" if first_page else ""
        )
        if fmt == "md":
            toc_lines.append(f"{n}. [{head.title}]({name}){where}")
        else:
            toc_lines.append(f"# {head.title}{where} — {name}")
    title_line = f"# {book_title}" if fmt == "md" else f"= {book_title} ="
    files[f"index.{ext}"] = title_line + note + "\n\n" + "\n".join(toc_lines) + "\n"
    files[f"all.{ext}"] = title_line + note + "\n\n" + "\n".join(all_parts)
    return files


def export_document(
    doc_path, part_id: str, fmt: str = "md", keep_lines: bool = False
) -> tuple[dict[str, str], dict]:
    """문헌의 L4를 장별 파일로. 입력: 문헌 경로, 권, 형식, 줄 유지. 출력: (파일들, 통계).

    장은 문헌의 read_plan.json(작업 계획)에서 읽는다. 계획이 없으면 한 장(책 전체)이다.
    """
    from pathlib import Path

    from core.document import get_document_info
    from ocr.read_book import load_plan

    doc_path = Path(doc_path)
    pages_dir = doc_path / "L4_text" / "pages"
    page_texts: dict[int, str] = {}
    for f in sorted(pages_dir.glob(f"{part_id}_page_*.txt")):
        try:
            n = int(f.stem.rsplit("_", 1)[1])
        except ValueError:
            continue
        page_texts[n] = f.read_text(encoding="utf-8")
    plan = load_plan(doc_path, part_id) or {}
    title = plan.get("title") or get_document_info(doc_path).get("title") or doc_path.name
    chapters, stats = build_chapters(page_texts, plan.get("chapters") or [], front_title=title)
    # 데이터 판 각인(D-128 1항) — 교정 후 다시 내보낸 파일과 구별된다
    try:
        from core.corpus_version import corpus_snapshot

        cv = corpus_snapshot(doc_path.parent.parent, document_ids=[doc_path.name])["corpus_hash"]
    except Exception:  # noqa: BLE001 — 각인을 못 해도 내보내기는 된다
        cv = None
    note = f"확정본(L4) {len(page_texts)}쪽에서 만듦" + (f" · {cv}" if cv else "")
    from core.read_plan import page_label_map

    labels = page_label_map(plan) if plan else {}
    files = render(title, chapters, fmt, keep_lines, source_note=note, labels=labels)
    stats.update({"pages": len(page_texts), "chapters": len(chapters), "files": len(files)})
    return files, stats
