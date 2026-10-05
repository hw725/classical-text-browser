"""애매한 후보 2차 판정 (D-137).

판정 모델이 확신하지 못한 자리를 «사람이 고른 채팅 LLM»에 붙여 넣어 묻는다.

왜 있는가:
    편성의 본문 판정(D-129·D-136)은 후보를 세 대역으로 나눈다. 가운데(escalate)는 체크 해제로 서서
    사람이 하나씩 고르는데, 운양집 1책에서 그 수가 수백이다(decider 문턱 424행). 측정해 보니
    Claude에게 문맥 몇 줄과 함께 다시 물으면 참 시작 50 중 48을 지키며 사람이 볼 목록을
    555 → 74(87% 감소)로 줄였다. 같은 재현에서 decider 확률만으로 자르면 133이 남는다.

무엇을 하지 않는가 — **앱은 여기서 외부 모델을 부르지 않는다**:
    내보내기는 «지시문 + 후보 JSON 줄»인 글 한 덩어리를 만들 뿐이다. 사람이 그것을 아무 채팅
    LLM(Claude·ChatGPT·Gemini…)에 붙여 넣고, 답을 다시 붙여 넣는다. 이 PC에서는 Claude Code/Desktop
    세션이 `scripts/escalate_review.py`로 같은 일을 한다. 앱이 키·모델·비용을 하나 더 떠안지 않고,
    다른 사용자는 자기가 쓰는 채팅 LLM을 그대로 쓴다.

모델이 할 수 없는 것:
    - **행을 더할 수 없다.** 답의 id는 내보낸 후보 목록에 있는 것만 받는다(없는 id는 «거부»).
    - **경계를 저장할 수 없다.** 결과는 체크 제안뿐이다 — «예»는 체크, «아니오»는 체크 해제 + 표시.
      저장은 지금과 같이 사람이 「적용」을 누를 때만 일어난다.
    - 확률을 보지 않는다. 판정 모델의 확률을 보여 주면 그 숫자에 기대어 답한다(닻 효과) — 글만 준다.

어디에 남기는가:
    `<서고>/.escalate_review/<문헌>/<권>.json` — 후보 목록과 들인 2차 판정.
    **문헌 저장소(git) 밖**이다: 문헌 폴더에 두면 다음 교정 커밋의 `git add -A`가 이 임시 기록을
    끌고 들어간다. 경계가 아니라 «제안의 메모»라 서고 루트(git 아님 — `llm_usage_log.jsonl`과
    같은 자리)에 둔다. CLI(서버 없이 도는
    Claude 세션)가 화면이 세운 후보를 알아야 하므로 남기는 것이다.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from core.llm_json_items import parse_llm_items
from core.segmentation import Line
from core.structure_llm import line_id, parse_line_id

CHUNK_SIZE = 100  # 한 덩어리의 후보 수 — 채팅 창 한 번에 붙이고 답이 잘리지 않는 크기(측정은 50개)
BEFORE_LINES = 4  # 앞 문맥 — 표제 앞의 글 끝을 보여 주려면 2~3행이 모자랐다(측정 지시문 그대로)
AFTER_LINES = 2  # 뒤 문맥 — 표제 다음 행이 본문 첫머리인지 보면 충분하다
STORE_DIRNAME = ".escalate_review"

# 지시문의 답 예시에 쓰는 id. **후보가 될 수 없는 자리**여야 한다 — 쪽은 1부터 센다
# (`segmentation._list_part_pages`). 한때 실제로 있을 법한 «p8-L3»을 써서, 내보낸 글을 그대로
# 들이거나 채팅 LLM이 지시문을 되풀이하면 예시가 진짜 «예» 판정으로 들어가 체크됐다
# (2026-10-05 실측).
EXAMPLE_ID = "p0-L0"

# 내보낸 글의 머리. 들이기 입력에 이것이 있으면 «답»이 아니라 «내보낸 글»을 붙인 것이다
# (클립보드를 못 쓰면 화면이 내보낸 글을 답 칸에 띄운다 — 그대로 「들이기」를 누르는 길이 있다).
HEAD_PREFIX = "[애매한 후보 2차 판정 —"
CANDIDATES_MARKER = "후보(한 줄에 하나):"

# 답 글 길이 상한 — 묶음 100개 × 후보 100개 × 항목 200자. 이보다 긴 붙여 넣기는 답이 아니다.
# 상한이 없으면 깊게 중첩된 글 하나가 JSON 해석을 붙들거나(RecursionError) 서버 메모리를 쓴다.
MAX_ANSWER_CHARS = 2_000_000

# 묶음 표지 — «esc-<문헌·권 지문 6자>-<묶음 번호>». 답이 이것을 되받게 해서 다른 권·문헌의 답을
# 가려낸다. 문헌 id를 그대로 쓰지 않는 까닭: 한글·기호가 든 id는 채팅 LLM이 옮겨 적다 바꾸기 쉽다
# (짧은 ASCII가 안전).
_TAG_RE = re.compile(r"esc-([0-9a-f]{6})-(\d+)")

BOOK_HINTS = {
    "diary": "일기 — 날짜로 시작하는 표제 행(예: 「十二月初一日」)에서 새 날의 글이 시작합니다.",
    "collection": "문집 — 시·글의 제목 행에서 새 글이 시작합니다.",
}

# 측정(2026-10-05, Claude 50후보)에서 쓴 지시문을 사람에게 보이는 부분만 한국어로 옮겼다.
# JSON 계약의 키(answers·id·start·conf)와 값(yes·no)은 영어 그대로 둔다 — 어느 채팅 LLM이 답해도
# 같은 파서로 읽어야 하고, 키를 번역하면 모델마다 다른 말로 돌려준다.
INSTRUCTIONS = (
    "당신은 한문 고서의 편집자입니다. 아래 후보마다, text 행에서 **새 글**"
    "(기사·시·일기의 한 날·산문 한 편)이 시작하는지 판정하십시오.\n"
    "\n"
    '- "yes": text 행이 새 글의 첫 행(표제·제목)일 때만.\n'
    '- "no": 앞 글이 이어지는 본문, 글 안의 행, 쪽마다 되풀이되는 머리글(판심·권 이름 등), '
    "글 안의 주석.\n"
    "- before(바로 앞 행, 최대 4행)와 after(바로 뒤 행, 최대 2행)를 문맥으로 쓰십시오. "
    "판정하는 것은 text 행 하나입니다.\n"
    "- 책 종류 힌트: {hint}\n"
    "\n"
    "답은 JSON만 쓰십시오(설명 문장 없이). 아래의 모든 id에 빠짐없이 답하십시오"
    "{tag_rule}:\n"
    "{example}\n"
    'start는 "yes" 또는 "no", conf는 0.0~1.0의 확신도입니다. 예시의 id(' + EXAMPLE_ID + ")는 "
    "자리 표시일 뿐이니 답에 넣지 마십시오."
)

_YES = {"yes", "y", "true", "예", "네", "시작"}
_NO = {"no", "n", "false", "아니오", "아니요", "아님"}


def book_hint(book_type: Optional[str]) -> str:
    """책 종류 힌트 한 줄. 입력: "diary"·"collection"·None. None이면 둘 다 적는다(모르는 책)."""
    if book_type in BOOK_HINTS:
        return BOOK_HINTS[book_type]
    return "일기라면 날짜로 시작하는 표제 행, 문집이라면 시·글의 제목 행이 새 글의 시작입니다."


def candidate_items(
    lines: list[Line], positions: Iterable
) -> tuple[list[dict], list[str]]:
    """후보 자리를 «id·앞 문맥·행·뒤 문맥»으로 편다. **확률은 넣지 않는다.**

    입력: 확정본 행 목록(쪽·행 순), 자리 목록([(쪽, 행)] 또는 {page, line_index}).
    출력: (항목 목록 [{id, before, text, after}], 건너뛴 id — 지금 확정본에 없거나 빈 행).
    문맥은 **빈 행을 건너뛴 읽는 순서**로 쪽을 넘어 잇는다 — 쪽 첫 행의 표제는 앞 쪽 끝이 문맥이다.
    """
    seq = [ln for ln in lines if ln.text.strip()]
    seq.sort(key=lambda ln: (ln.page, ln.line_index))
    at = {(ln.page, ln.line_index): i for i, ln in enumerate(seq)}
    items: list[dict] = []
    skipped: list[str] = []
    seen: set[tuple[int, int]] = set()
    for pos in positions:
        key = _pos_key(pos)
        if key is None or key in seen:
            continue
        seen.add(key)
        i = at.get(key)
        if i is None:
            skipped.append(f"p{key[0]}-L{key[1]}")
            continue
        items.append(
            {
                "id": line_id(seq[i]),
                "before": [ln.text.strip() for ln in seq[max(0, i - BEFORE_LINES) : i]],
                "text": seq[i].text.strip(),
                "after": [ln.text.strip() for ln in seq[i + 1 : i + 1 + AFTER_LINES]],
            }
        )
    items.sort(key=lambda it: parse_line_id(it["id"]))
    return items, skipped


def _pos_key(pos) -> Optional[tuple[int, int]]:
    """자리 하나 → (쪽, 행). dict·튜플·«p8-L3» 셋을 받는다."""
    try:
        if isinstance(pos, dict):
            return int(pos["page"]), int(pos["line_index"])
        if isinstance(pos, str):
            return parse_line_id(pos)
        return int(pos[0]), int(pos[1])
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def tag_key(doc_id: str, part_id: str) -> str:
    """문헌·권 지문 6자(16진). 입력: 문헌·권 id. 출력: 예 «3fa9c1». 같은 문헌·권이면 늘 같다."""
    return hashlib.sha1(f"{doc_id}\x00{part_id}".encode("utf-8")).hexdigest()[:6]


def batch_tag(doc_id: str, part_id: str, index: int) -> str:
    """묶음 표지 «esc-3fa9c1-2». 답이 이것을 «batch»로 되받는다."""
    return f"esc-{tag_key(doc_id, part_id)}-{index}"


def render_chunk_text(
    items: list[dict],
    index: int,
    total: int,
    book_type: Optional[str],
    doc_id: Optional[str] = None,
    part_id: Optional[str] = None,
) -> str:
    """붙여 넣을 글 한 덩어리 — 지시문 + 후보 JSON 줄.

    입력: 항목·몇째(1부터)·전체·책 종류·문헌·권. 문헌·권을 주면 머리에 표지(`batch_tag`)를 싣고
    답이 그것을 되받게 한다 — 다른 권의 답을 붙여 넣으면 들이기가 거부한다. 주지 않으면 표지 없이
    (옛 모양) 만든다.
    """
    tag = batch_tag(doc_id, part_id, index) if doc_id is not None and part_id is not None else None
    where = f"문헌 {doc_id} · 권 {part_id} · " if tag else ""
    head = (
        f"{HEAD_PREFIX} {where}묶음 {index}/{total} · 후보 {len(items)}개"
        + (f" · 표지 {tag}]" if tag else "]")
    )
    body = "\n".join(json.dumps(it, ensure_ascii=False) for it in items)
    if tag:
        tag_rule = f'. "batch"에는 이 묶음의 표지 «{tag}»를 그대로 적으십시오'
        example = (
            f'{{"batch":"{tag}","answers":[{{"id":"{EXAMPLE_ID}","start":"yes","conf":0.9}}, ...]}}'
        )
    else:
        tag_rule = ""
        example = f'{{"answers":[{{"id":"{EXAMPLE_ID}","start":"yes","conf":0.9}}, ...]}}'
    instructions = INSTRUCTIONS.format(
        hint=book_hint(book_type), tag_rule=tag_rule, example=example
    )
    return f"{head}\n\n{instructions}\n\n{CANDIDATES_MARKER}\n{body}\n"


def export_chunks(
    lines: list[Line],
    positions: Iterable,
    chunk_size: int = CHUNK_SIZE,
    book_type: Optional[str] = None,
    doc_id: Optional[str] = None,
    part_id: Optional[str] = None,
) -> dict:
    """후보를 ≤chunk_size개씩 나눠 붙여 넣을 글로 만든다. 모델은 부르지 않는다.

    출력: {"chunks": [{"label": "1/3", "ids": [...], "text": "...", "tag": "esc-…-1"|None}],
           "count": n, "skipped": [...]}.
    덩어리를 나누는 까닭: 한 번에 수백 개를 붙이면 채팅 LLM의 답이 잘리거나 뒤쪽을 건너뛴다.
    문헌·권을 주면 묶음마다 표지를 싣는다(화면 라우트·CLI는 늘 준다).
    """
    size = max(1, int(chunk_size or CHUNK_SIZE))
    items, skipped = candidate_items(lines, positions)
    parts = [items[i : i + size] for i in range(0, len(items), size)]
    total = len(parts)
    tagged = doc_id is not None and part_id is not None
    chunks = [
        {
            "label": f"{n}/{total}",
            "ids": [it["id"] for it in part],
            "text": render_chunk_text(part, n, total, book_type, doc_id, part_id),
            "tag": batch_tag(doc_id, part_id, n) if tagged else None,
        }
        for n, part in enumerate(parts, start=1)
    ]
    return {"chunks": chunks, "count": len(items), "skipped": skipped, "chunk_size": size}


# ── 답 읽기 ────────────────────────────────────────────────────────────────


def _answer_objects(text: str) -> tuple[list, str]:
    """답 글에서 {"answers": [...]} 객체를 **모두** 찾는다. 출력: (항목 목록, 상태).

    덩어리 셋의 답을 한 칸에 이어 붙여도 읽히게 하려고 객체를 여러 개 찾는다(울타리·설명 문장은
    건너뛴다). 하나도 없으면 공통 파서(`parse_llm_items`)로 넘겨 잘린 답에서 완성된 항목만 건진다
    — 기능마다 복구 파서를 따로 두지 않는다(CLAUDE.md «파일 다루기»).
    """
    dec = json.JSONDecoder()
    found: list = []
    pos = 0
    text = text or ""
    while True:
        i = text.find("{", pos)
        if i < 0:
            break
        try:
            obj, end = dec.raw_decode(text, i)
        except (json.JSONDecodeError, RecursionError):
            # RecursionError: «{"a":[{"a":[…» 같은 깊은 중첩 붙여 넣기에서 파이썬 JSON 해석기가
            # 재귀 한도를 넘는다. 잡지 않으면 들이기 라우트가 500으로 죽었다(2026-10-05 실측).
            pos = i + 1
            continue
        if isinstance(obj, dict) and isinstance(obj.get("answers"), list):
            found.extend(obj["answers"])
            pos = end
        else:
            pos = i + 1
    if found:
        return found, "ok"
    # 맨 목록([{"id":…}, …])만 준 답도 받는다
    m = re.search(r"\[\s*\{", text)
    if m:
        try:
            arr, _ = dec.raw_decode(text, m.start())
            if isinstance(arr, list):
                return arr, "ok"
        except (json.JSONDecodeError, RecursionError):
            pass
    try:
        parsed = parse_llm_items(text, key="answers")
    except RecursionError:
        return [], "no_json"
    return list(parsed.items), parsed.status


def _start_value(v) -> Optional[str]:
    """start 값 → "yes"·"no"·None(알 수 없음). 불·한국어 답도 너그럽게 받는다."""
    if isinstance(v, bool):
        return "yes" if v else "no"
    s = str(v or "").strip().lower()
    if s in _YES:
        return "yes"
    if s in _NO:
        return "no"
    return None


def _conf_value(v) -> Optional[float]:
    """conf → 0~1 수 또는 None. 범위를 벗어나거나 수가 아니면 None(판정 자체는 살린다)."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 3) if 0.0 <= f <= 1.0 else None


def looks_like_export(text: str) -> bool:
    """붙여 넣은 글이 «답»이 아니라 «내보낸 글»(지시문 + 후보)인가.

    왜: 클립보드를 못 쓰면 화면이 내보낸 글을 답 칸에 띄운다. 그대로 「들이기」를 누르거나
    채팅 LLM이 지시문을 되풀이한 답을 붙이면, 복구 파서가 지시문의 예시 줄을 «답»으로 읽었다
    (2026-10-05 실측 — 예시 id가 실제로 있을 법한 자리라 그대로 체크됐다).
    머리·후보 표지가 보이면 들이지 않는다.
    """
    t = text or ""
    return HEAD_PREFIX in t or CANDIDATES_MARKER in t


def check_batch_tags(text: str, doc_id: Optional[str], part_id: Optional[str]) -> dict:
    """답에 적힌 묶음 표지를 이 문헌·권과 견준다.

    출력: {"status": "ok"|"absent"|"mismatch", "tags": [본 표지], "foreign": [다른 권 표지]}.
    «absent»는 옛 답이거나 LLM이 표지를 빠뜨린 것 — 받되 거부 비율로 경고한다(import_answers).
    """
    found = [f"esc-{k}-{n}" for k, n in _TAG_RE.findall(text or "")]
    if not found or doc_id is None or part_id is None:
        return {"status": "absent" if not found else "ok", "tags": found, "foreign": []}
    mine = tag_key(doc_id, part_id)
    foreign = sorted({t for t in found if t.split("-")[1] != mine})
    return {"status": "mismatch" if foreign else "ok", "tags": found, "foreign": foreign}


def parse_answers(text: str, candidate_ids: list[str], chunk_size: int = CHUNK_SIZE) -> dict:
    """붙여 넣은 답을 읽어 후보 목록에 대조한다. **모델이 행을 더할 수 없다.**

    입력: 답 글(울타리·설명 문장 섞여도 됨), 내보낸 후보 id(순서 그대로), 덩어리 크기.
    표지·«내보낸 글을 붙였나»는 여기서 보지 않는다 — 문헌·권을 아는 `import_answers`가 본다.
    출력: {
        "verdicts": {id: {"start": "yes"|"no", "conf": 수|None}},
        "counts": {"yes", "no", "missing", "rejected", "malformed"},
        "unknown_ids": [...]   — 후보에 없는 id(거부),
        "missing_ids": [...]   — 답이 닿은 덩어리 안에서 답이 없는 id(누락),
        "malformed": n, "duplicates": n, "parse_status": "ok"|"recovered"|"no_json",
    }
    «누락»은 **답이 닿은 덩어리 안에서만** 센다 — 1/3의 답을 붙였는데 2/3·3/3을 누락으로 세면
    사람이 «모델이 200개를 빠뜨렸다»로 읽는다. 하나도 못 읽었으면 전체를 누락으로 센다.
    """
    entries, status = _answer_objects(text)
    known = set(candidate_ids)
    verdicts: dict[str, dict] = {}
    unknown: list[str] = []
    malformed = 0
    duplicates = 0
    for e in entries:
        if not isinstance(e, dict):
            malformed += 1
            continue
        raw_id = e.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            malformed += 1
            continue
        key = parse_line_id(raw_id)
        cid = f"p{key[0]}-L{key[1]}" if key else raw_id.strip()
        if cid not in known:
            unknown.append(raw_id.strip()[:40])
            continue
        start = _start_value(e.get("start"))
        if start is None:
            malformed += 1
            continue
        if cid in verdicts:
            duplicates += 1  # 먼저 온 답을 쓴다 — 나중 답으로 조용히 뒤집지 않는다
            continue
        verdicts[cid] = {"start": start, "conf": _conf_value(e.get("conf"))}
    size = max(1, int(chunk_size or CHUNK_SIZE))
    if verdicts:
        order = {cid: n for n, cid in enumerate(candidate_ids)}
        touched = {order[i] // size for i in verdicts}
        scope = [cid for n, cid in enumerate(candidate_ids) if n // size in touched]
    else:
        scope = list(candidate_ids)
    missing = [cid for cid in scope if cid not in verdicts]
    yes = sum(1 for v in verdicts.values() if v["start"] == "yes")
    return {
        "verdicts": verdicts,
        "counts": {
            "yes": yes,
            "no": len(verdicts) - yes,
            "missing": len(missing),
            "rejected": len(unknown),
            "malformed": malformed,
        },
        "unknown_ids": unknown,
        "missing_ids": missing,
        "malformed": malformed,
        "duplicates": duplicates,
        "parse_status": status,
    }


# ── 서고에 남기는 메모(문헌 저장소 밖) ─────────────────────────────────────


def check_path_id(value, what: str) -> str:
    """문헌·권 id가 폴더 이름 하나인지 본다. 아니면 ValueError(한국어 — 원인과 할 일).

    왜: CLI `--doc ..`이 `<서고>/documents/..`(= 서고 자체)를 «있는 폴더»로 통과시키고, 메모 자리가
    `.escalate_review/../<권>.json`으로 서고 밖·위로 빠졌다(2026-10-05 실측). 또 예전에는 «a/b»를
    «a_b»로 바꿔 두 문헌이 한 메모를 나눠 쓸 수 있었다 — 바꾸지 않고 거부한다.
    """
    s = str(value or "")
    bad = (
        not s.strip()
        or s in (".", "..")
        or any(ch in s for ch in ("/", "\\", ":", "\x00"))
        or Path(s).is_absolute()
    )
    if bad:
        raise ValueError(
            f"{what} id «{s[:40]}»를 쓸 수 없습니다 — 폴더 이름 하나여야 합니다"
            "(빈 값·«..»·경로 구분자·드라이브 문자 금지). 편성 화면이나 서고의 documents 폴더에 "
            "보이는 이름을 그대로 적으세요."
        )
    return s


def store_path(library_root, doc_id: str, part_id: str) -> Path:
    """메모 파일 자리. 입력: 서고 루트·문헌·권. 출력: `<서고>/.escalate_review/<문헌>/<권>.json`.

    문헌·권 id가 폴더 이름 하나가 아니면 ValueError(`check_path_id`) — 서고 밖으로 빠지지 않게."""
    check_path_id(doc_id, "문헌")
    check_path_id(part_id, "권")
    safe = lambda s: re.sub(r"[^\w.\-]", "_", str(s))  # noqa: E731 — 파일 이름에 못 쓰는 글자를 막는다
    return Path(library_root) / STORE_DIRNAME / safe(doc_id) / f"{safe(part_id)}.json"


def load_store(library_root, doc_id: str, part_id: str) -> dict:
    """메모를 읽는다. 없거나 깨졌으면 빈 메모.

    출력: {"candidates": [...], "verdicts": {...}, ...}."""
    p = store_path(library_root, doc_id, part_id)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("candidates", [])
            data.setdefault("verdicts", {})
            return data
    except (OSError, ValueError):
        pass
    return {"doc_id": doc_id, "part_id": part_id, "candidates": [], "verdicts": {}}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_candidates(
    library_root,
    doc_id: str,
    part_id: str,
    lines: list[Line],
    positions: Iterable,
    source: str,
    probs: Optional[dict] = None,
    chunk_size: Optional[int] = None,
) -> dict:
    """애매한 후보 목록을 메모에 적는다. 이미 들인 2차 판정은 **그 자리의 글이 그대로면** 남긴다.

    입력: 서고·문헌·권, 확정본 행, 자리 목록, 출처("judge" — 판정 모델 실행 직후 / "screen" — 화면이
          내보내기 때 보낸 목록), probs({id: 확률} — 기록용, 내보내기에는 싣지 않는다).
    출력: 저장한 메모. 확정본이 바뀌어 글이 달라진(또는 사라진) 자리의 옛 판정은 버린다 — 다른 글에
          대한 답이다.
    **지금 후보 목록에 없는 자리의 판정도 버리지 않는다**: 화면이 「상위 N」·다시 판정으로 목록을
    바꿔 내보내면 예전에는 목록 밖의 들인 판정이 통째로 지워졌다(사람·LLM이 이미 답한 것을 다시
    묻게 된다). 판정 기록은 남기고, 화면에 쓰이는 것은 지금 후보에 있는 것뿐이다
    (`current_verdicts`).
    """
    from core.document import write_json_atomic

    items, skipped = candidate_items(lines, positions)
    old = load_store(library_root, doc_id, part_id)
    line_text = {line_id(ln): ln.text.strip() for ln in lines if ln.text.strip()}
    kept = {
        cid: v
        for cid, v in (old.get("verdicts") or {}).items()
        if isinstance(v, dict) and cid in line_text and v.get("text") == line_text[cid]
    }
    data = {
        "doc_id": doc_id,
        "part_id": part_id,
        "source": source,
        "updated": _now(),
        "candidates": [
            {"id": it["id"], "text": it["text"], "prob": (probs or {}).get(it["id"])}
            for it in items
        ],
        "skipped": skipped,
        "verdicts": kept,
        # 들이기가 «누락»을 내보낸 덩어리와 같은 경계로 세도록 덩어리 크기를 함께 둔다
        "chunk_size": max(1, int(chunk_size or old.get("chunk_size") or CHUNK_SIZE)),
    }
    write_json_atomic(store_path(library_root, doc_id, part_id), data)
    return data


def current_verdicts(store: dict) -> dict:
    """메모의 판정 가운데 **지금 후보 목록에 있는 자리**의 것만. 출력: {id: {start, conf}}.

    메모는 목록 밖의 옛 판정도 품는다(`save_candidates`) — 화면·CLI에 쓰이는 것은 지금 목록의
    것뿐이다."""
    ids = {c.get("id") for c in store.get("candidates") or []}
    return {
        cid: {"start": v.get("start"), "conf": v.get("conf")}
        for cid, v in (store.get("verdicts") or {}).items()
        if cid in ids and isinstance(v, dict)
    }


def import_answers(library_root, doc_id: str, part_id: str, text: str) -> dict:
    """답을 읽어 메모의 후보에 대조하고, 받아들인 판정을 메모에 더한다(체크 제안 — 경계 아님).

    출력: parse_answers의 결과 + {"all_verdicts": 지금 후보의 들인 판정 전부,
          "remaining": 아직 답 없는 수, "rejudged": 이미 판정이 있던 자리를 다시 답한 수,
          "flipped": 그 가운데 예↔아니오가 바뀐 수, "tag_status": "ok"|"absent",
          "warnings": [한국어 경고]}.
    ValueError(사람이 할 일을 적은 한국어 문구)로 거부하는 경우:
      - 후보가 없을 때, 글이 너무 길 때(`MAX_ANSWER_CHARS`),
      - 내보낸 글(지시문·후보)을 그대로 붙였을 때(`looks_like_export`),
      - 답의 묶음 표지가 다른 문헌·권의 것일 때(`check_batch_tags`).
    """
    from core.document import write_json_atomic

    text = text or ""
    if len(text) > MAX_ANSWER_CHARS:
        raise ValueError(
            f"붙여 넣은 글이 너무 깁니다({len(text):,}자 — 상한 {MAX_ANSWER_CHARS:,}자). "
            "채팅 LLM의 답(JSON)만 묶음 몇 개씩 나눠 붙이세요."
        )
    store = load_store(library_root, doc_id, part_id)
    cands = store.get("candidates") or []
    if not cands:
        raise ValueError(
            "이 권의 애매한 후보 목록이 없습니다. 편성 화면에서 「판정 모델로 고르기」를 돌리거나 "
            "「애매한 후보 내보내기」를 먼저 누르세요."
        )
    if looks_like_export(text):
        raise ValueError(
            "내보낸 글(지시문·후보)을 그대로 붙인 것 같습니다 — 들이지 않았습니다. 그 글은 채팅 "
            "LLM에 붙여 넣는 것이고, 이 칸에는 LLM의 답 "
            '{"batch":…,"answers":[…]} 부분만 붙이세요. '
            "LLM이 지시문을 되풀이했다면 답의 JSON만 골라 붙이세요."
        )
    tags = check_batch_tags(text, doc_id, part_id)
    if tags["status"] == "mismatch":
        raise ValueError(
            f"다른 문헌·권의 답입니다(표지 {', '.join(tags['foreign'][:5])} — 이 권의 표지는 "
            f"esc-{tag_key(doc_id, part_id)}-N). 들이지 않았습니다. 지금 연 권에서 내보낸 묶음의 "
            "답을 붙이세요."
        )
    ids = [c["id"] for c in cands]
    text_of = {c["id"]: c.get("text") for c in cands}
    res = parse_answers(text, ids, store.get("chunk_size") or CHUNK_SIZE)
    stamp = _now()
    verdicts = dict(store.get("verdicts") or {})
    rejudged = flipped = 0
    for cid, v in res["verdicts"].items():
        prev = verdicts.get(cid)
        if isinstance(prev, dict) and prev.get("start") in ("yes", "no"):
            rejudged += 1  # 같은 id를 다시 답하면 덮는다 — 덮었다는 사실은 숨기지 않는다
            if prev.get("start") != v["start"]:
                flipped += 1
        verdicts[cid] = {**v, "text": text_of.get(cid), "at": stamp}
    store["verdicts"] = verdicts
    store["updated"] = stamp
    write_json_atomic(store_path(library_root, doc_id, part_id), store)
    res["all_verdicts"] = current_verdicts(store)
    res["remaining"] = sum(1 for cid in ids if cid not in verdicts)
    res["rejudged"] = rejudged
    res["flipped"] = flipped
    res["tag_status"] = tags["status"]
    warnings: list[str] = []
    answered = len(res["verdicts"]) + res["counts"]["rejected"]
    if tags["status"] == "absent" and answered and res["counts"]["rejected"] * 2 > answered:
        # 표지가 없는 답(옛 답·LLM이 빠뜨림)은 받는다. 그러나 거부가 절반을 넘으면 다른 권의 답일
        # 공산이 크다 — 권마다 쪽·행 번호가 겹쳐 일부 id가 «우연히 맞아» 엉뚱한 자리에 체크될 수
        # 있다.
        warnings.append(
            f"거부한 id가 절반을 넘습니다({res['counts']['rejected']}/{answered}) — 다른 권·문헌의 "
            "답이 아닌지 확인하세요. 답에 묶음 표지(batch)가 없어 가려내지 못했습니다."
        )
    res["warnings"] = warnings
    return res


def export_from_store(
    library_root,
    doc_id: str,
    part_id: str,
    lines: list[Line],
    chunk_size: int = CHUNK_SIZE,
    book_type: Optional[str] = None,
) -> dict:
    """메모의 후보로 내보낸다(서버 없이 도는 CLI가 쓴다). 덩어리 크기를 메모에 남겨 들이기가 같은
    경계로 «누락»을 센다. 후보가 없으면 ValueError.

    한계: 메모를 적은 뒤 확정본이 바뀌어 사라진 행은 내보내기에서 빠지고(`skipped`), 그만큼
    덩어리 경계가 메모의 순서와 어긋나 «누락» 범위가 한 덩어리 넘어갈 수 있다. 판정 자체는 id로
    맞추므로 틀어지지 않는다."""
    from core.document import write_json_atomic

    store = load_store(library_root, doc_id, part_id)
    ids = [c["id"] for c in store.get("candidates") or []]
    if not ids:
        raise ValueError(
            "이 권의 애매한 후보 목록이 없습니다. "
            "편성 화면에서 「판정 모델로 고르기」를 먼저 돌리세요."
        )
    out = export_chunks(lines, ids, chunk_size, book_type, doc_id, part_id)
    if store.get("chunk_size") != out["chunk_size"]:
        store["chunk_size"] = out["chunk_size"]
        write_json_atomic(store_path(library_root, doc_id, part_id), store)
    return out
