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
# 판정 모델이 고른 자리 — 생성 모델의 것과 구분해야 근거가 섞이지 않는다
JEV_REASON = "jev:structure"
TOC_JEV_REASON = "toc:jev"  # 목차 항목을 판정 모델이 본문 행에 붙인 자리(층위 1~2)
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
    lines: list[Line], items: list, max_title_chars: int = 20, reason: str = REASON
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
                "reasons": [reason],
                "suppressed": False,
                "accepted": True,
                "why": str(it.get("why") or "")[:200],
            }
        )
    out.sort(key=lambda p: (p["page"], p["line_index"]))
    return out, stats


# ── Jev(판정 모델) 길 ────────────────────────────────────────────────────────
# 생성 모델에게는 «행 번호만 가리키라»고 부탁해야 하고, 부탁은 지켜지지 않을 수 있어
# validate_items가 뒤에서 거른다(없는 행·중복·지어낸 제목). Jev에게는 부탁할 것이 없다 —
# 질문이 «이 행에서 새 글이 시작하는가»(noul)이므로 답은 0~1 확률 하나뿐이고, 행은 코드가
# 정해서 묻는다. 지어낼 자리가 형식에 없다(D-117·D-125의 태도를 형식으로 옮긴 것).
#
# 한계: Jev는 제목·깊이를 만들지 않는다. 제목은 validate_items가 그 행의 글자로 채우고
# 깊이는 2(낱글) 고정이다. 층위가 필요하면 별도 질문(choice)으로 물어야 한다.
JEV_START_INSTRUCTIONS = (
    "한문 고서의 한 권 전문입니다. 아래 행의 첫머리에서 **새로운 글**"
    "(기사·편·시·서간, 또는 일기의 새 날)이 시작합니까?"
)
JEV_CRITERIA = {
    "true": (
        "이 행에서 새 글이 시작한다 — 날짜·표제·제목으로 시작하거나, 앞 글이 끝나고 "
        "다른 글이 열린다"
    ),
    "false": (
        "앞 행에서 이어지는 본문이다. 또는 판심·엽수·두주·판권처럼 쪽마다 되풀이되어 "
        "글의 시작이 아닌 것이다"
    ),
}
JEV_QUESTIONS_PER_CALL = 100  # 한 요청의 예산은 64k 토큰(state + 모든 질문) — 여유를 두고 자른다


def jev_question(ln: Line) -> dict:
    """행 하나에 대한 noul 질문. 입력: Line. 출력: TypeSafe questions의 값 하나.

    **질문 id는 모델에 가지 않는다**(TypeSafe 문서) — 그래서 어느 행을 묻는지 instructions가
    스스로 담아야 한다. 번호와 그 행의 글자를 함께 적는 까닭이다.
    """
    return {
        "type": "noul",
        "instructions": (
            f"{JEV_START_INSTRUCTIONS}\n행 «{line_id(ln)}»: 「{ln.text.strip()}」"
        ),
        "criteria": dict(JEV_CRITERIA),
    }


def jev_structure_size(
    lines: list[Line],
    max_chars: int = DEFAULT_MAX_CHARS,
    questions_per_call: int = JEV_QUESTIONS_PER_CALL,
) -> dict:
    """보내기 전에 «몇 행·몇 자·몇 번 부르는가»를 센다 — 게이트는 도구 층에(전역 규칙 11).

    출력: lines·chars·calls·questions. 한 묶음의 행이 questions_per_call보다 많으면 그 묶음은
    **같은 state로 여러 번** 부른다(state가 그만큼 되풀이되어 입력 토큰도 함께 는다).
    """
    chunks = chunk_lines(lines, max_chars)
    calls = 0
    for c in chunks:
        calls += max(1, -(-len(c) // max(1, questions_per_call)))
    return {
        "lines": sum(len(c) for c in chunks),
        "chars": sum(len(ln.text) for c in chunks for ln in c),
        "calls": calls,
        "questions": sum(len(c) for c in chunks),
    }


def ask_structure_jev(
    lines: list[Line],
    client,
    max_chars: int = DEFAULT_MAX_CHARS,
    questions_per_call: int = JEV_QUESTIONS_PER_CALL,
    threshold: float = 0.5,
    max_title_chars: int = 20,
) -> tuple[list[dict], dict]:
    """전문을 묶음으로 나눠 **행마다** «새 글이 시작하는가»를 Jev에 묻는다.

    입력: 행 목록, JevClient, 묶음 글자 수, 한 번에 보낼 질문 수, 채택 문턱(noul ≥ threshold),
          제목 최대 글자.
    출력: (후보 목록 — ask_structure_llm과 같은 모양, meta). meta에는 provider·model·calls·
          questions·sent_lines·sent_chars·said·dropped·error와 함께 **nouls**(행마다의 확률,
          [page, line_index, noul])를 담는다 — 문턱을 바꿔 다시 재려면 이 목록만 있으면 된다.

    확신도는 고정 0.6이다(D-125와 같다). Jev의 확률은 후보의 `why`에 적어 사람이 보게만 한다 —
    화면의 «확신도»는 규칙 후보와 견주는 값이라 다른 척도를 섞으면 안 된다.
    """
    meta: dict = {
        "provider": "typesafe",
        "model": getattr(client, "model", None),
        "error": None,
        "calls": 0,
        "questions": 0,
        "sent_lines": 0,
        "sent_chars": 0,
        "said": 0,
        "dropped": 0,
        "title_fixed": 0,
        "reasons": {},
        "notes": [],
        "nouls": [],
        "threshold": threshold,
    }
    chunks = chunk_lines(lines, max_chars)
    if not chunks:
        meta["error"] = "확정본(L4)에 글이 있는 행이 없습니다."
        return [], meta

    errors: list[str] = []
    items: list[dict] = []
    for i, chunk in enumerate(chunks):
        state = render_chunk(chunk)
        meta["sent_lines"] += len(chunk)
        meta["sent_chars"] += sum(len(ln.text) for ln in chunk)
        for start in range(0, len(chunk), questions_per_call):
            batch = chunk[start : start + questions_per_call]
            questions = {line_id(ln): jev_question(ln) for ln in batch}
            meta["calls"] += 1
            meta["questions"] += len(questions)
            try:
                answers = client.ask(state, questions)
            except Exception as e:  # noqa: BLE001 — 한 묶음이 죽어도 나머지는 살린다
                errors.append(f"{i + 1}번째 묶음: {type(e).__name__}: {e}")
                continue
            for ln in batch:
                p = _jev_noul(answers.get(line_id(ln)))
                if p is None:
                    continue
                meta["nouls"].append([ln.page, ln.line_index, round(p, 4)])
                if p >= threshold:
                    items.append(
                        {
                            "line": line_id(ln),
                            "title": "",  # Jev는 제목을 만들지 않는다 — 코드가 행 글자로 채운다
                            "level": 2,
                            "role": "article",
                            "why": f"jev noul {p:.2f}",
                        }
                    )
    meta["said"] = len(items)
    out, stats = validate_items(lines, items, max_title_chars=max_title_chars, reason=JEV_REASON)
    # 확률을 후보에 실어 보낸다 — 화면이 «상위 몇 개»로 자르려면 숫자가 후보에 있어야 한다.
    # 확신도(confidence)와는 다른 칸이다: 확신도는 규칙 후보와 견주는 값이고 이것은 모델의 확률이다.
    by_pos = {(int(pg), int(li)): v for pg, li, v in meta["nouls"]}
    for prop in out:
        prop["prob"] = by_pos.get((prop["page"], prop["line_index"]))
    meta.update(stats)
    if hasattr(client, "usage"):
        meta["usage"] = client.usage()
    if errors:
        meta["error"] = " / ".join(errors)[:600]
    return out, meta


def _jev_noul(answer) -> Optional[float]:
    """llm.jev.noul을 core에서 쓰기 위한 얇은 감싸기 — core가 llm을 import하지 않게 한다."""
    if not isinstance(answer, dict):
        return None
    v = answer.get("noul")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


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


# 고른 행에서 제목이 실제로 시작하는가 — 코드가 공짜로 확인하는 관문(모델의 자기 신고가 아니다).
# 운양집 1책 실측에서 이 값을 넘긴 고름은 전부 제목이 그 행의 첫머리였다.
SELF_CHECK_MIN = 0.85


def derive_toc_threshold(
    picks: list, tolerance: int = 0, min_picks: int = 5, fallback: float = 0.8
) -> tuple[float, dict]:
    """문턱을 **이 책의 답에서** 뽑는다 — 상수로 박지 않는다. 출력: (문턱, 어떻게 정했는지).

    입력: match_toc_entries_jev의 picks(각각 prob과 sim을 갖는다), 허용할 오답 수,
          문턱을 뽑기에 충분한 최소 답 수, 그만큼 없을 때 쓸 값.

    **정답표 없이 잴 수 있는 신호를 쓴다**: 고른 행에서 제목이 실제로 시작하는가(`sim`).
    코드가 공짜로 확인할 수 있고, 모델의 자기 신고가 아니다. 확률 높은 것부터 내려가다
    자기 검증이 tolerance번을 넘겨 깨지는 자리 **직전**에서 자른다.

    왜 분위수가 아닌가: 백분위는 분포와 무관하게 늘 같은 비율을 자르므로 대부분이 맞는 책에서는
    맞는 자리까지 잘라 낸다(D-128 11항 구현자와 합의, 2026-09-21).
    왜 상수가 아닌가: 운양집 1책에서 0.8이 들었던 것은 0.8이 특별해서가 아니라 0.94와 0.77 사이가
    비어 있었고 0.8이 그 빈 구간에 떨어졌기 때문이다. 절벽의 자리는 책마다 다르다.

    답이 min_picks보다 적으면 절벽을 말할 근거가 없으므로 fallback을 쓴다.
    """
    rows = sorted(
        ((float(p.get("prob") or 0), float(p.get("sim") or 0)) for p in picks), reverse=True
    )
    if len(rows) < min_picks:
        return fallback, {"how": "fallback", "picks": len(rows), "value": fallback}
    bad = 0
    for i, (prob, sim) in enumerate(rows):
        if sim < SELF_CHECK_MIN:  # 제목이 그 행에서 시작하지 않는다 — 자기 검증 실패
            bad += 1
            if bad > tolerance:
                value = rows[i - 1][0] if i else 1.0
                return value, {"how": "cliff", "picks": len(rows), "cut_at": i, "value": value}
    return rows[-1][0], {"how": "all_pass", "picks": len(rows), "value": rows[-1][0]}


def toc_picks_to_proposals(picks: list, entries: list, min_prob: float = 0.8) -> list[dict]:
    """목차 대조(고르기)의 답을 ③의 후보로. 입력: match_toc_entries_jev의 picks, 항목 목록, 문턱.

    출력: 후보 목록(Proposal.to_dict와 같은 모양). 층위는 **목차 항목의 층위**를 그대로 쓴다 —
    총목이 말하는 것은 권·集(층위 1~2)이고, 그 아래 낱글은 본문 판정이 맡는다.

    문턱을 두는 까닭: 운양집 1책 실측(2026-09-21)에서 높은 확률로 고른 14건은 제목이 그 행에서
    실제로 시작했고(불일치 0), 그 아래 11건 중 8건이 엉뚱한 행이었다. 문턱 아래를 **버리는 것이
    아니라** 후보로 세우지 않을 뿐이고, 화면이 «상위 몇 개»로 더 보일 수 있다.
    **min_prob은 상수가 아니라 `derive_toc_threshold()`가 이 책의 답에서 뽑은 값이 기본**이다.
    """
    out: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for p in picks:
        # 자기 검증은 확률과 **다른 관문**이다. 확률은 «얼마나 확신하는가»이고 이것은
        # «애초에 그 행이 맞는가»인데, 코드가 공짜로 확인할 수 있다(제목이 그 행에서 시작하는가).
        # 확률 문턱만 두면 답이 적어 문턱이 상수로 물러설 때 **자기 검증에 실패한 답이 그대로
        # 들어온다**(2026-09-21 반대 배치 실측: 답 4개에서 오답 하나가 통과했다).
        # 한계: 「續昇平館集」이 「昇平館集」 행을 고른 것처럼 접두 관계는 여기서 떨어진다 —
        # 그런 자리는 규칙·본문 판정 후보로 사람에게 남는다.
        if float(p.get("sim") or 0) < SELF_CHECK_MIN:
            continue
        if float(p.get("prob") or 0) < min_prob:
            continue
        key = (int(p["page"]), int(p["line_index"]))
        if key in seen:
            continue  # 총목이 같은 集을 권1·권2 양쪽에 적는다 — 자리는 하나다
        seen.add(key)
        i = int(p.get("entry", -1))
        level = 2
        if 0 <= i < len(entries):
            try:
                level = max(1, min(9, int(getattr(entries[i], "level", 2) or 2)))
            except (TypeError, ValueError):
                level = 2
        out.append(
            {
                "page": key[0],
                "line_index": key[1],
                "char_offset": 0,
                "title": str(p.get("title") or "")[:40],
                "level": level,
                "role": "container",
                "date": {},
                "kind": "",
                "place": "",
                "confidence": round(float(p.get("prob") or 0), 3),
                "prob": round(float(p.get("prob") or 0), 3),
                "reasons": [TOC_JEV_REASON],
                "suppressed": False,
                "accepted": True,
                "why": f"목차 항목을 본문에서 고름(확률 {p.get('prob')})",
            }
        )
    out.sort(key=lambda p: (p["page"], p["line_index"]))
    return out


def nest_under_toc(toc_props: list[dict], body_props: list[dict]) -> list[dict]:
    """본문 판정의 층위를 목차가 세운 층 **아래**로 내린다. 입력·출력: 후보 목록(body를 고친 사본).

    왜: 목차가 답하는 것은 권·集이고 본문 판정이 답하는 것은 그 안의 낱글이다. 둘을 같은 층에
    두면 트리가 «集과 작품이 형제»인 꼴이 된다. 그래서 각 본문 후보 앞에 선 가장 가까운 목차
    후보의 층위 + 1을 준다(최대 9). 목차 후보가 하나도 없으면(일기류) 아무것도 바꾸지 않는다 —
    그 책에서는 본문 판정이 곧 낱글의 층이다.
    """
    if not toc_props:
        return [dict(p) for p in body_props]
    marks = sorted(
        ((int(t["page"]), int(t["line_index"]), int(t.get("level") or 2)) for t in toc_props)
    )
    out: list[dict] = []
    for p in body_props:
        here = (int(p["page"]), int(p["line_index"]))
        level = None
        for page, line, lv in marks:
            if (page, line) <= here:
                level = lv
            else:
                break
        q = dict(p)
        if level is not None:
            q["level"] = max(1, min(9, level + 1))
            q["role"] = "article" if q["level"] >= 2 else "container"
        out.append(q)
    return out
