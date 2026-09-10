"""권 전문을 LLM에 보여 «글이 시작하는 행»을 통째로 묻는다 (D-125).

왜 있는가:
    규칙(D-116~D-119)은 되풀이되는 표지가 있는 책에서 잘 듣는다. 문집·잡록처럼 표제가 제각각인
    책은 표지가 없어 규칙이 못 잡는데, 사람은 전문을 읽으면 어디서 글이 바뀌는지 안다. 그 판단을
    모델에 맡기되, **모델이 위치를 만들지 않고 고르기만** 하게 해서 이미지-글자 대응을 지킨다.

어떻게 위치를 지키는가:
    행마다 ``p8-L3`` 같은 번호를 붙여 텍스트만 보낸다(좌표·이미지는 보내지 않는다). 답은 그 번호를
    가리키는 목록이고, 코드가 «실제로 있는 행인가 · 제목이 그 행의 글자인가»를 확인해 후보(Proposal
    과 같은 모양)로 바꾼다. 후보는 지금 ③에 서는 것과 같은 (쪽·행·글자) 자리이므로, 「적용」이
    만드는 경계·앵커 글자·점선·재대조가 전부 그대로 된다.

무엇을 하지 않는가:
    저장하지 않는다(적용은 ③ 한 곳). 글을 고쳐 쓰지 않는다. 행 중간 경계는 만들지 않는다
    (행 첫머리만).
    모델의 «자신감»은 쓰지 않는다 — 확신도는 고정 0.6(중간)이고, 규칙 후보와 같은 자리면 그 후보에
    근거만 보탠다.
"""

from __future__ import annotations

import re
from typing import Optional

from core.segmentation import Line
from core.toc import lenient_json, reference_excerpt

STRUCTURE_SYSTEM_PROMPT = (
    "당신은 한문 고서의 편집자입니다. 행 번호가 붙은 전문을 읽고, "
    "새 글(기사·편·시·서간·일기의 날 등)이 "
    "시작하는 행을 고르십시오. 글을 고쳐 쓰거나 옮기지 말고 행 번호만 가리키십시오. "
    "제목은 그 행에 실제로 있는 글자에서만 따오고, 없으면 빈 문자열로 두십시오. "
    "깊이(level)는 1 = 권·부처럼 여러 글을 묶는 큰 단위, 2 = 낱글, 3 이상 = 글 안의 절입니다. "
    "역할(role)은 container(묶음)·article(기사)·fragment(조각) 중 하나입니다. "
    "판심·엽수·두주처럼 쪽마다 되풀이되는 것은 글의 시작이 아닙니다. "
    "JSON으로만 답하십시오."
)

REASON = "llm:structure"
CONFIDENCE = 0.6  # 화면의 «중간»(≥0.5) — 모델의 자신감은 믿지 않는다(D-117과 같은 태도)
ROLES = ("container", "article", "fragment")
DEFAULT_MAX_CHARS = 7000  # 묶음 하나의 글자 수 — 로컬 모델의 문맥(8k 토큰)에도 들어가는 크기
_LINE_ID = re.compile(r"p(\d+)-L(\d+)")


def line_id(ln: Line) -> str:
    """행 번호 — 모델이 가리키고 코드가 되찾는 열쇠. 입력: Line. 출력: «p8-L3»."""
    return f"p{ln.page}-L{ln.line_index}"


def parse_line_id(s: str) -> Optional[tuple[int, int]]:
    """«p8-L3» → (8, 3). 모델이 앞뒤에 다른 글자를 붙여도 번호만 찾는다. 없으면 None."""
    m = _LINE_ID.search(str(s or ""))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def chunk_lines(lines: list[Line], max_chars: int = DEFAULT_MAX_CHARS) -> list[list[Line]]:
    """전문을 쪽 경계에서 잘라 묶음으로 나눈다. 빈 행은 보내지 않는다.

    입력: 행 목록(쪽·행 순), 묶음 최대 글자 수. 출력: 묶음 목록(각각 Line 목록).
    왜 쪽 경계인가: 한 쪽이 두 묶음에 걸치면 같은 쪽의 행이 두 답에 나뉘어 나온다. 한 쪽이
    max_chars보다 크면 그 쪽만으로 한 묶음이 된다(자르지 않는다).
    """
    pages: dict[int, list[Line]] = {}
    for ln in lines:
        if not ln.text.strip():
            continue
        pages.setdefault(ln.page, []).append(ln)
    chunks: list[list[Line]] = []
    cur: list[Line] = []
    cur_chars = 0
    for page in sorted(pages):
        rows = pages[page]
        chars = sum(len(r.text) for r in rows)
        if cur and cur_chars + chars > max_chars:
            chunks.append(cur)
            cur, cur_chars = [], 0
        cur.extend(rows)
        cur_chars += chars
    if cur:
        chunks.append(cur)
    return chunks


def structure_size(lines: list[Line], max_chars: int = DEFAULT_MAX_CHARS) -> dict:
    """보내기 전에 «몇 행·몇 자·몇 번 부르는가»를 센다 — 실행 게이트를 도구 층에(전역 규칙 11)."""
    chunks = chunk_lines(lines, max_chars)
    return {
        "lines": sum(len(c) for c in chunks),
        "chars": sum(len(ln.text) for c in chunks for ln in c),
        "calls": len(chunks),
    }


def render_chunk(chunk: list[Line]) -> str:
    """묶음을 «번호<TAB>글»로 편다. 쪽이 바뀌면 «— n쪽 —» 머리를 둔다."""
    out: list[str] = []
    last_page = None
    for ln in chunk:
        if ln.page != last_page:
            out.append(f"— {ln.page}쪽 —")
            last_page = ln.page
        out.append(f"{line_id(ln)}\t{ln.text}")
    return "\n".join(out)


def _fold(s: str) -> str:
    return re.sub(r"[\s　○●◎□■◇◆・．。、，,.:：;；「」『』()\[\]（）]", "", str(s or ""))


def validate_items(
    lines: list[Line], items: list, max_title_chars: int = 20
) -> tuple[list[dict], dict]:
    """모델의 답을 실제 행에 대조해 후보로 바꾼다.

    입력: 행 목록, 모델의 starts 목록([{line, title, level, role, why}]), 제목 최대 글자.
    출력: (후보 목록 — Proposal.to_dict와 같은 모양,
          {"dropped": n, "title_fixed": n, "reasons": {...}}).
    버리는 것: 번호가 없거나 실제 행이 아닌 것, 빈 행, 같은 행의 되풀이.
    제목이 그 행의 글자가 아니면 버리지 않고 **행의 글자로 바꾼다** — 자리가 정본이고 제목은
    사람이 고친다.
    """
    by_id: dict[tuple[int, int], Line] = {(ln.page, ln.line_index): ln for ln in lines}
    out: list[dict] = []
    seen: set[tuple[int, int]] = set()
    stats = {"dropped": 0, "title_fixed": 0, "reasons": {}}

    def drop(why: str) -> None:
        stats["dropped"] += 1
        stats["reasons"][why] = stats["reasons"].get(why, 0) + 1

    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            drop("not_object")
            continue
        key = parse_line_id(it.get("line"))
        if key is None:
            drop("no_line_id")
            continue
        ln = by_id.get(key)
        if ln is None or not ln.text.strip():
            drop("unknown_line")
            continue
        if key in seen:
            drop("duplicate")
            continue
        seen.add(key)
        title = str(it.get("title") or "").strip()
        if not title or _fold(title) not in _fold(ln.text) or len(title) > max_title_chars + 8:
            if title:
                stats["title_fixed"] += 1
            title = ln.text.strip()[:max_title_chars]
        try:
            level = max(1, min(9, int(it.get("level") or 2)))
        except (TypeError, ValueError):
            level = 2
        role = str(it.get("role") or "").strip()
        if role not in ROLES:
            role = "container" if level == 1 else "article"
        out.append(
            {
                "page": ln.page,
                "line_index": ln.line_index,
                "char_offset": 0,
                "title": title,
                "level": level,
                "role": role,
                "date": {},
                "kind": "",
                "place": "",
                "confidence": CONFIDENCE,
                "reasons": [REASON],
                "suppressed": False,
                "accepted": True,
                "why": str(it.get("why") or "")[:200],
            }
        )
    out.sort(key=lambda p: (p["page"], p["line_index"]))
    return out, stats


async def ask_structure_llm(
    lines: list[Line],
    router,
    force_provider: Optional[str] = None,
    force_model: Optional[str] = None,
    reference_text: str = "",
    max_chars: int = DEFAULT_MAX_CHARS,
    max_title_chars: int = 20,
) -> tuple[list[dict], dict]:
    """전문을 묶음으로 나눠 묻고, 답을 실제 행에 대조해 후보로 돌려준다.

    출력: (후보 목록, meta) — meta: provider·model·error·calls·sent_lines·sent_chars·
    said(모델이 말한 수)·dropped·title_fixed·reasons·notes. 묶음 하나가 실패하면 그 묶음만 비고
    error에 남긴다 — 다른 묶음의 답은 살린다(권 전체를 다시 묻게 하지 않는다).
    """
    meta: dict = {
        "provider": None,
        "model": None,
        "error": None,
        "calls": 0,
        "sent_lines": 0,
        "sent_chars": 0,
        "said": 0,
        "dropped": 0,
        "title_fixed": 0,
        "reasons": {},
        "notes": [],
    }
    chunks = chunk_lines(lines, max_chars)
    if not chunks:
        meta["error"] = "확정본(L4)에 글이 있는 행이 없습니다."
        return [], meta
    ref = ""
    if reference_text and reference_text.strip():
        ref = "해제(판단에만 쓸 것):\n" + reference_excerpt(reference_text, 4000) + "\n\n"
    kwargs = {
        "system": STRUCTURE_SYSTEM_PROMPT,
        "response_format": "json",
        "max_tokens": 4096,
        "purpose": "segmentation_rules",
        "think": False,  # 자리를 고르는 일이다 — 사고 예산을 쓸 일이 아니다(D-083)
    }
    if force_provider:
        kwargs["force_provider"] = force_provider
    if force_model:
        kwargs["force_model"] = force_model
    items: list = []
    errors: list[str] = []
    for i, chunk in enumerate(chunks):
        pages = sorted({ln.page for ln in chunk})
        intro = (
            f"이 권의 전문 중 {i + 1}/{len(chunks)}번째 묶음입니다({pages[0]}~{pages[-1]}쪽). "
            "앞뒤 묶음에서 글이 이어질 수 있으니, 이 묶음 첫 행이 글의 첫머리라고 "
            "단정하지 마십시오.\n"
            "한 줄은 «행 번호<TAB>글»입니다. 새 글이 시작하는 행을 모두 고르고, 형식은\n"
            '{"starts": [{"line": "p8-L3", "title": "...", "level": 2, "role": "article", '
            '"why": "..."}], "note": "..."}\n\n'
        )
        prompt = ref + intro + render_chunk(chunk)
        meta["calls"] += 1
        meta["sent_lines"] += len(chunk)
        meta["sent_chars"] += sum(len(ln.text) for ln in chunk)
        try:
            response = await router.call(prompt, **kwargs)
        except Exception as e:  # noqa: BLE001 — 모델이 없어도 규칙 길은 남아 있다
            errors.append(f"{i + 1}번째 묶음: {type(e).__name__}: {e}")
            continue
        meta["provider"] = getattr(response, "provider", None) or meta["provider"]
        meta["model"] = getattr(response, "model", None) or meta["model"]
        text = getattr(response, "text", "") or ""
        data = lenient_json(text)
        if not isinstance(data, dict) or not isinstance(data.get("starts"), list):
            # 무엇이 왔는지 앞부분을 남긴다 — «형식이 아니다»만으로는 모델을 바꿀지 프롬프트를
            # 고칠지 모른다
            errors.append(f"{i + 1}번째 묶음: starts 목록이 아닌 답")
            meta.setdefault("raw_failed", []).append(text[:600])
            continue
        items.extend(data["starts"])
        note = str(data.get("note") or "").strip()
        if note:
            meta["notes"].append(note[:300])
    meta["said"] = len(items)
    out, stats = validate_items(lines, items, max_title_chars=max_title_chars)
    meta.update(stats)
    if errors:
        meta["error"] = " / ".join(errors)[:600]
    return out, meta
