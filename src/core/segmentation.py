"""글 단위 경계 제안 — 쪽 단위 텍스트에서 «어디서 글이 바뀌는가»를 제안한다 (D-088).

왜 필요한가:
    원본 층(L1~L4)은 쪽 단위이고 해석은 글(내용) 단위다. 둘을 잇는 편성 작업은
    지금까지 손으로 블록을 합치고 쪼개는 일이었다. 일기·사행록·담초처럼 글마다
    표제가 서는 문헌은 경계 신호가 뚜렷해서 기계가 **제안**할 수 있다.

무엇을 하지 않는가:
    확정하지 않는다. 결과는 신뢰도 붙은 후보 목록이고, 사용자가 승인한 것만
    TextBlock이 된다(D-085 결정 2 — 단위는 잠정적).

신호를 두 층으로 나눈다 — 하드코딩 금지 원칙(D-080·D-081과 같은 태도):
    1. 문헌 무관 신호 (코드):
       - 날짜 문법: 干支·月·日·是月·是日·朔·晦. 그리고 날짜의 단조 증가(사슬).
         「是月」·일자만 적은 표제는 앞 회차에서 달을 물려받고, 일자가 앞보다 작아지면
         달을 올린다. 앞뒤가 맞지 않으면 신뢰도를 내린다 — 본문 문장 속의 날짜가
         표제처럼 보이는 경우(예: 三月廿一日李中堂以筆談問曰)가 여기서 걸린다.
       - 형식: 별행이면서 본문보다 눈에 띄게 짧은 행, L2 bbox가 있으면 내려쓰기.
    2. 문헌 설정 (manifest.segmentation_rules, 화면에서 편집):
       - title_words: 표제를 끝맺는 어휘 (예: 談草·筆談). 문헌마다 다르므로 데이터.
       - suppress: 표제로 보지 않을 행(원문 그대로). 규칙이 놓친 예외를 사람이 적는다.
       - max_title_chars: 별행 표제로 볼 최대 글자수.

입력은 「쪽·행 번호·텍스트(·bbox)」의 평평한 목록이라 L4가 어떻게 저장되든 상관없다.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── 날짜 문법 (문헌 무관) ────────────────────────────────────────────────

_GANZHI = "[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]"
_NUM = "[一二三四五六七八九十廿卄卅]+"
_MONTH = rf"(?:是月|閏?(?:正|臘|{_NUM})月)"
_DAY = rf"(?:是日|翌日|同日|朔日?|晦日?|初{_NUM}日|{_NUM}日)"
# 「○七日」처럼 날짜 앞에 오는 조목 표지 — 澹齋日錄류는 개행 없이 이 표지로 날을 나눈다
# (D-090 2단계).
_MARK = "[○◯〇●]"
_MARK_RE = re.compile(_MARK)
DATE_HEAD_RE = re.compile(
    rf"^(?P<mark>{_MARK})?(?P<ganzhi>{_GANZHI})?年?(?P<month>{_MONTH})?(?P<day>{_DAY})?"
)

_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cjk_number(text: str) -> Optional[int]:
    """한자 수사를 정수로. 十→10, 廿三→23, 二十一→21, 初三→3, 正→1, 臘→12. 못 읽으면 None."""
    if not text:
        return None
    t = text.replace("初", "")
    if t == "正":
        return 1
    if t == "臘":
        return 12
    t = t.replace("卄", "廿")
    total = 0
    if "卅" in t:
        total += 30
        t = t.replace("卅", "")
    if "廿" in t:
        total += 20
        t = t.replace("廿", "")
    if "十" in t:
        before, _, after = t.partition("十")
        total += (_DIGITS.get(before, 1) if before else 1) * 10
        if after:
            if after not in _DIGITS:
                return None
            total += _DIGITS[after]
        return total
    if t == "":
        return total or None
    if t in _DIGITS:
        return total + _DIGITS[t]
    return None


@dataclass
class DateHead:
    """행 첫머리에서 읽은 날짜."""

    ganzhi: Optional[str] = None
    month: Optional[int] = None  # None = 안 적음(是月 포함)
    day: Optional[int] = None
    is_month_rel: bool = False  # 是月
    is_day_rel: bool = False  # 是日·翌日
    mark: bool = False  # 날짜 앞의 ○ 표지가 있었나
    matched: str = ""  # 날짜로 읽은 원문 조각

    @property
    def present(self) -> bool:
        return bool(self.matched)


def parse_date_head(text: str) -> DateHead:
    """행 첫머리의 날짜 조각을 읽는다. 干支만 있는 것은 날짜로 치지 않는다."""
    m = DATE_HEAD_RE.match(text)
    if not m or not (m.group("month") or m.group("day")):
        return DateHead()
    head = DateHead(ganzhi=m.group("ganzhi"), matched=m.group(0), mark=bool(m.group("mark")))
    mon = m.group("month")
    if mon:
        if mon == "是月":
            head.is_month_rel = True
        else:
            head.month = cjk_number(mon.replace("閏", "").rstrip("月"))
    day = m.group("day")
    if day:
        if day in ("是日", "翌日", "同日"):
            head.is_day_rel = True
        elif day.startswith("朔"):
            head.day = 1
        elif day.startswith("晦"):
            head.day = 30
        else:
            head.day = cjk_number(day.rstrip("日"))
    return head


# ── 규칙 (문헌 설정) ─────────────────────────────────────────────────────

DEFAULT_RULES: dict = {
    "use_date": True,
    "use_layout": True,
    "title_words": [],
    "suppress": [],
    "max_title_chars": 14,
    "min_confidence": 0.5,
    # 해제·서지 설명 등 사람이 붙여 넣은 참고 텍스트. 목차 감지(LLM)가 프롬프트에 넣어 참고한다.
    # 규칙(코드)은 이것을 읽지 않는다 — 지식은 데이터, 판단은 사람·LLM의 것(D-080·D-081 태도).
    "reference_text": "",
}


def normalize_rules(rules: Optional[dict]) -> dict:
    """빠진 항목은 기본값으로, 문자열 목록은 공백을 걷어 낸다."""
    out = dict(DEFAULT_RULES)
    for k, v in (rules or {}).items():
        if k in out and v is not None:
            out[k] = v
    out["title_words"] = [str(w).strip() for w in out["title_words"] if str(w).strip()]
    out["suppress"] = [str(w).strip() for w in out["suppress"] if str(w).strip()]
    out["max_title_chars"] = int(out["max_title_chars"])
    out["min_confidence"] = float(out["min_confidence"])
    out["reference_text"] = str(out.get("reference_text") or "").strip()[:8000]
    return out


# ── 제안 ─────────────────────────────────────────────────────────────────


@dataclass
class Line:
    """입력 행. bbox는 쪽 픽셀 [x1,y1,x2,y2] (없으면 None)."""

    page: int
    line_index: int
    text: str
    bbox: Optional[list] = None
    char_start: int = 0  # 그 쪽 텍스트 안의 시작 오프셋
    block_id: Optional[str] = None
    writing_direction: str = "vertical_rtl"


@dataclass
class Proposal:
    page: int
    line_index: int
    char_offset: int  # 행 안의 시작 글자(0 = 행 첫머리). 행 중간 경계는 D-090 2단계
    title: str
    date: dict
    kind: str  # 맞은 title_word, 없으면 ""
    place: str  # 날짜 뒤·어휘 앞 조각
    confidence: float
    reasons: list = field(default_factory=list)
    suppressed: bool = False
    accepted: bool = False  # min_confidence 이상 & 억제 아님 → 스팬 경계
    level: int = 2  # 추정 층위(D-092): 1 = 卷·편, 2 = 기사, 3 = 조각. 사람이 바꿀 수 있다

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "line_index": self.line_index,
            "char_offset": self.char_offset,
            "title": self.title,
            "level": self.level,
            "date": self.date,
            "kind": self.kind,
            "place": self.place,
            "confidence": round(self.confidence, 2),
            "reasons": list(self.reasons),
            "suppressed": self.suppressed,
            "accepted": self.accepted,
        }


_INDENT_CHARS: dict[tuple[int, int], float] = {}


def _layout_signals(lines: list[Line], rules: dict) -> dict[tuple[int, int], list[str]]:
    """형식 신호: 짧은 행·내려쓰기. 쪽 안의 본문 행 분포와 비교한다.

    왜 쪽 단위 비교인가: 글자 크기·행 길이는 판식(板式)마다 다르니 절대값을 쓸 수 없다.
    같은 쪽의 중앙값보다 눈에 띄게 짧거나 위가 낮으면 표제로 본다.

    부수 산출: 행마다 내려쓰기 «글자 수»(본문 중앙값 대비, 반올림)를 `_INDENT_CHARS`에 남긴다.
    층위 추정(`_assign_levels`)이 이것을 쓴다 — 판식마다 표제의 들여쓰기가 다르므로 절대값이
    아니라 «이 문헌에서 가장 흔한 표제 들여쓰기»를 기준으로 얕고 깊음을 가른다.
    """
    out: dict[tuple[int, int], list[str]] = {}
    _INDENT_CHARS.clear()
    if not rules["use_layout"]:
        return out
    by_page: dict[int, list[Line]] = {}
    for ln in lines:
        by_page.setdefault(ln.page, []).append(ln)
    for page, page_lines in by_page.items():
        lens = [len(ln.text) for ln in page_lines if ln.text.strip()]
        if len(lens) < 3:
            continue
        median_len = statistics.median(lens)
        # 내려쓰기: 세로쓰기는 y1(위), 가로쓰기는 x1(왼쪽)의 중앙값과 비교
        tops = []
        for ln in page_lines:
            if ln.bbox and len(ln.bbox) == 4 and ln.text.strip():
                tops.append(
                    ln.bbox[1] if ln.writing_direction.startswith("vertical") else ln.bbox[0]
                )
        median_top = statistics.median(tops) if len(tops) >= 3 else None
        # 글자 한 자의 크기 ≈ 행 길이(px) / 글자수 의 중앙값
        char_px = None
        sizes = []
        for ln in page_lines:
            if ln.bbox and len(ln.bbox) == 4 and len(ln.text.strip()) >= 4:
                extent = (
                    (ln.bbox[3] - ln.bbox[1])
                    if ln.writing_direction.startswith("vertical")
                    else (ln.bbox[2] - ln.bbox[0])
                )
                sizes.append(extent / len(ln.text.strip()))
        if len(sizes) >= 3:
            char_px = statistics.median(sizes)
        for ln in page_lines:
            n = len(ln.text.strip())
            if not n:
                continue
            reasons = []
            if n <= rules["max_title_chars"] and median_len >= rules["max_title_chars"] + 4:
                reasons.append("short_line")
            if median_top is not None and char_px and ln.bbox and len(ln.bbox) == 4:
                top = ln.bbox[1] if ln.writing_direction.startswith("vertical") else ln.bbox[0]
                _INDENT_CHARS[(ln.page, ln.line_index)] = round((top - median_top) / char_px, 1)
                if top - median_top >= char_px * 0.8:
                    reasons.append("indent")
            if reasons:
                out[(ln.page, ln.line_index)] = reasons
    return out


# 표제 어휘 바로 앞의 문장 표지. 「以筆談問曰」「故談草無一見存者」「以上口談」처럼 어휘가
# 서술어·목적어로 쓰인 자리다 — 표제라면 어휘 앞에는 날짜·장소·상대가 온다.
# 문헌 무관 문법이므로 코드에 둔다(천진담초 실측 2026-09-03, D-088 «남은 것»).
_CLAUSE_MARKERS = ("以上", "以", "故", "而", "則", "乃", "遂", "因", "其")


def _find_title_word(text: str, words: list[str], limit: int) -> tuple[str, int]:
    """표제 어휘가 앞부분(limit 글자 안)에 있으면 (어휘, 위치). 없으면 ("", -1)."""
    best = ("", -1)
    head = text[:limit]
    for w in words:
        pos = head.find(w)
        if pos >= 0 and (best[1] < 0 or pos < best[1]):
            best = (w, pos)
    return best


def _line_candidates(raw: str) -> list[tuple[int, str]]:
    """행 하나에서 경계 후보가 설 자리 — 행 첫머리(0)와 행 안의 ○+날짜 자리. 오프셋은 raw 기준.

    왜: 澹齋日錄류 일기는 개행 없이 「…○七日晴…○八日雨…」처럼 열 중간에서 날이 바뀐다.
    행 단위 앵커로는 이런 판식을 자를 수 없다(D-090 «남은 것»). ○ 뒤에 날짜 문법이 있을 때만
    후보로 삼는다 — ○만으로는 구두점·표기 부호와 구별할 수 없다.
    """
    lead = len(raw) - len(raw.lstrip())
    out = [(0, raw.strip())]
    for m in _MARK_RE.finditer(raw):
        if m.start() <= lead:
            continue  # 첫머리의 ○는 오프셋 0 후보가 다룬다
        sub = raw[m.start() :].strip()
        if parse_date_head(sub).present:
            out.append((m.start(), sub))
    return out


def propose_boundaries(
    lines: list[Line],
    rules: Optional[dict] = None,
    toc_matches: Optional[list[dict]] = None,
) -> dict:
    """행 목록에서 글 경계 후보를 만든다.

    toc_matches — core.toc.align_toc_to_body()의 결과(dict 목록). 대응된 행은 날짜·형식이
    없어도 후보가 되고 신뢰도가 크게 오른다(D-089). level 1(卷·篇)은 kind="volume".

    출력: {"proposals": [...], "spans": [...], "stats": {...}, "rules": 적용된 규칙}
      proposals — 날짜나 표제 어휘가 있는 모든 행 (억제된 것도 표시용으로 포함)
      spans — accepted 제안 사이의 구간. 첫 제안 앞에 행이 있으면 kind="front" 구간.
        {"title", "kind", "start": {"page","line_index"}, "end": {"page","line_index"}(포함),
         "line_count", "proposal_index"}
    """
    rules = normalize_rules(rules)
    layout = _layout_signals(lines, rules)
    limit = rules["max_title_chars"] + 8
    toc_by_line: dict[tuple[int, int], dict] = {
        (int(m["page"]), int(m["line_index"])): m for m in (toc_matches or [])
    }

    proposals: list[Proposal] = []
    prev_month: Optional[int] = None
    prev_day: Optional[int] = None
    for ln in lines:
        if not ln.text.strip():
            continue
        for char_offset, text in _line_candidates(ln.text):
            head = parse_date_head(text) if rules["use_date"] else DateHead()
            word, wpos = _find_title_word(text, rules["title_words"], limit)
            # 형식·목차 신호는 행 첫머리에만 있다 — 행 중간 후보는 ○ 표지와 날짜가 신호다
            sig = layout.get((ln.page, ln.line_index), []) if char_offset == 0 else []
            toc = toc_by_line.get((ln.page, ln.line_index)) if char_offset == 0 else None
            if not head.present and not word and toc is None:
                continue

            reasons: list[str] = []
            conf = 0.0
            if toc is not None:
                # 목차가 «여기서 글이 시작한다»고 적어 둔 행 — 가장 강한 신호
                conf += 0.5 + 0.2 * float(toc.get("score", 0))
                reasons.append(f"toc:{toc.get('title', '')}")
            if head.present:
                conf += 0.5
                reasons.append("date")
            if head.mark:
                # ○+날짜는 그 자체가 조목 표지다. 긴 행·어휘 없음 감점은 이 판식에 맞지 않는다.
                conf += 0.25
                reasons.append("mark")
            if word:
                conf += 0.3
                reasons.append(f"title_word:{word}")
            if "short_line" in sig:
                conf += 0.2
                reasons.append("short_line")
            if "indent" in sig:
                conf += 0.25
                reasons.append("indent")
            # 표제 어휘 없이 날짜만 있고 행이 본문만큼 길면 본문 속 날짜일 가능성
            if (
                head.present
                and not word
                and not sig
                and toc is None
                and not head.mark
                and len(text) > rules["max_title_chars"]
            ):
                conf -= 0.25
                reasons.append("long_line")
            # 어휘는 있는데 날짜가 없고 본문만큼 긴 행 — 어휘가 문장 속에 쓰인 것
            # (「…并闕日記故談草無一見存者」). 짧은 행 신호가 있으면 표제일 수 있으니 뺀다.
            if (
                word
                and not head.present
                and toc is None
                and "short_line" not in sig
                and len(text) > rules["max_title_chars"]
            ):
                conf -= 0.25
                reasons.append("long_line")
            # 어휘 바로 앞이 문장 표지(以·故·而…)면 표제가 아니라 서술이다
            if word and wpos > 0 and text[:wpos].endswith(_CLAUSE_MARKERS):
                conf -= 0.3
                reasons.append("word_in_clause")
            # 문헌이 표제 어휘를 정해 두었는데 날짜만 있는 행 — 두주(頭註)·간행 정보·본문 속
            # 날짜 조각이 대부분이다. 어휘 없는 일기류(title_words 비어 있음)에는 적용하지 않는다.
            if head.present and rules["title_words"] and not word and toc is None and not head.mark:
                conf -= 0.25
                reasons.append("no_title_word")

            # 날짜 사슬
            month, day = head.month, head.day
            month_inferred = False
            month_rolled = False
            if head.present:
                if month is None:
                    month = prev_month
                    month_inferred = True
                    if (
                        day is not None
                        and prev_day is not None
                        and day < prev_day
                        and month is not None
                    ):
                        month = month % 12 + 1
                        month_rolled = True
                        reasons.append("month_rolled")
                elif prev_month is not None:
                    forward = (month - prev_month) % 12
                    if forward > 2 or (
                        forward == 0 and day is not None and prev_day is not None and day < prev_day
                    ):
                        # 본문 속 날짜(예: 三月廿一日李中堂以筆談問曰)가 표제처럼 보일 때
                        # 걸리는 자리.
                        # 짧은 행·내려쓰기 신호가 없으면 min_confidence(0.5) 아래로 내려간다.
                        conf -= 0.35
                        reasons.append("date_jump")
                if head.is_day_rel:
                    day = prev_day
                    reasons.append("same_day")
                elif (
                    not word
                    and toc is None
                    and day is not None
                    and day == prev_day
                    and (month is None or month == prev_month)
                ):
                    # 앞 회차와 같은 날짜를 어휘 없이 되적은 행
                    # (「初四日…談草」 다음 쪽의 「四日」) —
                    # 두주나 되풀이 표기다. 是日·同日처럼 «같은 날» 표지를 쓴 것은 위에서 걸렀다.
                    conf -= 0.35
                    reasons.append("same_day_repeat")

            suppressed = any(text == s or text.startswith(s) for s in rules["suppress"])
            if suppressed:
                reasons.append("suppressed")

            # 장소·상대: 날짜 뒤부터 표제 어휘 앞까지
            tail_start = len(head.matched)
            place = text[tail_start:wpos] if word and wpos >= tail_start else text[tail_start:limit]
            place = place.strip()
            title = text[: (wpos + len(word)) if word else min(len(text), limit)]
            kind = word
            if toc is not None:
                title = toc.get("title") or title
                if int(toc.get("level", 2)) == 1:
                    kind = "volume"

            conf = max(0.0, min(1.0, conf))
            accepted = (not suppressed) and conf >= rules["min_confidence"]
            proposals.append(
                Proposal(
                    page=ln.page,
                    line_index=ln.line_index,
                    char_offset=char_offset,
                    title=title,
                    date={
                        "ganzhi": head.ganzhi,
                        "month": month,
                        "day": day,
                        "month_inferred": month_inferred,
                        "month_rolled": month_rolled,
                        "text": head.matched,
                    },
                    kind=kind,
                    place=place,
                    confidence=conf,
                    reasons=reasons,
                    suppressed=suppressed,
                    accepted=accepted,
                )
            )
            if accepted and head.present:
                if month is not None:
                    prev_month = month
                if day is not None:
                    prev_day = day

    _assign_levels(proposals)
    spans = _build_spans(lines, proposals)
    return {
        "proposals": [p.to_dict() for p in proposals],
        "spans": spans,
        "stats": {
            "lines": len(lines),
            "proposals": len(proposals),
            "accepted": sum(1 for p in proposals if p.accepted),
            "suppressed": sum(1 for p in proposals if p.suppressed),
        },
        "rules": rules,
    }


def _assign_levels(proposals: list[Proposal]) -> None:
    """제안마다 층위를 추정한다 (D-092 — 사용자 요청 «들여쓰기로 레이어를 미리 구분»).

    규칙:
      - 목차 대응은 목차의 층위를 따른다(kind="volume" → 1, 그 밖은 2).
      - 나머지는 들여쓰기 글자 수로: 승인된 제안들의 **가장 흔한 들여쓰기**가 기사(2)이고,
        그보다 한 글자 넘게 얕으면 卷·편(1), 한 글자 넘게 깊으면 조각(3).
        bbox가 없어 들여쓰기를 모르면 2.
    왜 최빈값 기준인가: 표제의 들여쓰기는 판식마다 다르다(천진담초는 2자 내려쓰기, 문집은 시제
    頂格에 부기가 내려쓰기). 절대값 문턱은 한 문헌에만 맞는다.
    """
    import statistics

    for p in proposals:
        if any(r.startswith("toc:") for r in p.reasons):
            p.level = 1 if p.kind == "volume" else 2
    base_vals = [
        _INDENT_CHARS.get((p.page, p.line_index))
        for p in proposals
        if p.accepted and p.char_offset == 0 and not any(r.startswith("toc:") for r in p.reasons)
    ]
    base_vals = [v for v in base_vals if v is not None]
    if not base_vals:
        return
    try:
        mode = statistics.mode([round(v) for v in base_vals])
    except statistics.StatisticsError:
        mode = round(statistics.median(base_vals))
    for p in proposals:
        if any(r.startswith("toc:") for r in p.reasons) or p.char_offset != 0:
            continue
        v = _INDENT_CHARS.get((p.page, p.line_index))
        if v is None:
            continue
        if v <= mode - 1.5:
            p.level = 1
            p.reasons.append("indent_shallow")
        elif v >= mode + 1.5:
            p.level = 3
            p.reasons.append("indent_deep")
        else:
            p.level = 2


def _build_spans(lines: list[Line], proposals: list[Proposal]) -> list[dict]:
    """accepted 제안을 경계로 행 목록을 구간으로 나눈다. 경계는 (행, 글자 오프셋)이다.

    start.char_offset — 시작 행 안의 시작 글자. end.char_end — 끝 행 안의 끝 글자(exclusive),
    None이면 행 끝까지. 다음 경계가 행 중간이면 이 구간은 같은 행의 그 글자 앞에서 끝난다.
    """
    if not lines:
        return []
    accepted = [p for p in proposals if p.accepted]
    keys = [(ln.page, ln.line_index) for ln in lines]
    idx_of = {k: i for i, k in enumerate(keys)}
    prop_at = {}
    for p in accepted:
        if (p.page, p.line_index) in idx_of:
            prop_at.setdefault((idx_of[(p.page, p.line_index)], p.char_offset), p)
    bounds = sorted(prop_at)
    if not bounds:
        return []
    starts = ([(0, 0)] if bounds[0] != (0, 0) else []) + bounds
    spans = []
    for si, (s_i, s_off) in enumerate(starts):
        if si + 1 < len(starts):
            n_i, n_off = starts[si + 1]
            e_i, e_end = (n_i, n_off) if n_off > 0 else (n_i - 1, None)
        else:
            e_i, e_end = len(lines) - 1, None
        if e_i < s_i or (e_i == s_i and e_end is not None and e_end <= s_off):
            continue
        prop = prop_at.get((s_i, s_off))
        spans.append(
            {
                "title": prop.title if prop else lines[s_i].text.strip()[:20],
                "kind": prop.kind if prop else "front",
                "level": prop.level if prop else 2,
                "start": {"page": keys[s_i][0], "line_index": keys[s_i][1], "char_offset": s_off},
                "end": {"page": keys[e_i][0], "line_index": keys[e_i][1], "char_end": e_end},
                "line_count": e_i - s_i + 1,
                "proposal_index": (proposals.index(prop) if prop else None),
            }
        )
    return spans


# ── 문헌에서 행 모으기 ────────────────────────────────────────────────────


def collect_document_lines(
    doc_path: str | Path,
    part_id: str,
    pages: Optional[list[int]] = None,
) -> tuple[list[Line], dict[int, str]]:
    """문헌의 L4 확정 텍스트를 쪽·행으로 펼친다. L2 행 bbox가 맞아떨어지면 붙인다.

    출력: (행 목록, {쪽: 그 쪽의 전체 텍스트}) — 뒤의 것은 적용 때 char_range를 만들 때 쓴다.
    쪽 목록이 None이면 manifest의 page_count(없으면 L4_text/pages 파일)로 전체를 돈다.
    """
    from core.document import get_corrected_text, get_document_info

    doc_path = Path(doc_path)
    if pages is None:
        pages = _list_part_pages(doc_path, part_id, get_document_info)
    lines: list[Line] = []
    page_texts: dict[int, str] = {}
    for page in pages:
        try:
            corrected = get_corrected_text(doc_path, part_id, page)
        except Exception:  # noqa: BLE001 — 텍스트 없는 쪽은 건너뛴다
            continue
        text = corrected.get("corrected_text") or ""
        if not text.strip():
            continue
        page_texts[page] = text
        l2_lines = _l2_line_boxes(doc_path, part_id, page)
        raw_lines = text.split("\n")
        use_bbox = len(l2_lines) == len([t for t in raw_lines if t.strip()])
        offset = 0
        nonempty_i = 0
        for i, raw in enumerate(raw_lines):
            bbox = None
            direction = "vertical_rtl"
            if raw.strip() and use_bbox:
                bbox, direction = l2_lines[nonempty_i]
            if raw.strip():
                nonempty_i += 1
            lines.append(
                Line(
                    page=page,
                    line_index=i,
                    text=raw,
                    bbox=bbox,
                    char_start=offset,
                    writing_direction=direction,
                )
            )
            offset += len(raw) + 1
    return lines, page_texts


def _list_part_pages(doc_path: Path, part_id: str, get_document_info) -> list[int]:
    try:
        manifest = get_document_info(doc_path)
        for part in manifest.get("parts") or []:
            if part.get("part_id") == part_id and part.get("page_count"):
                return list(range(1, int(part["page_count"]) + 1))
    except Exception:  # noqa: BLE001
        pass
    pages_dir = doc_path / "L4_text" / "pages"
    found = []
    for f in pages_dir.glob(f"{part_id}_page_*.txt") if pages_dir.exists() else []:
        try:
            found.append(int(f.stem.rsplit("_", 1)[1]))
        except ValueError:
            continue
    return sorted(found)


def _l2_line_boxes(doc_path: Path, part_id: str, page: int) -> list[tuple[list, str]]:
    """L2의 행 bbox를 블록 순서대로. 없으면 빈 목록."""
    import json

    p = doc_path / "L2_ocr" / f"{part_id}_page_{page:03d}.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for res in data.get("ocr_results") or []:
        direction = res.get("writing_direction") or "vertical_rtl"
        for line in res.get("lines") or []:
            if (line.get("text") or "").strip():
                out.append((line.get("bbox"), direction))
    return out


def span_to_text_and_refs(
    span: dict,
    lines: list[Line],
    page_texts: dict[int, str],
    document_id: str,
    part_id: str,
) -> tuple[str, list[dict]]:
    """구간 하나를 TextBlock의 original_text와 source_refs(쪽별 char_range)로 바꾼다."""
    s, e = span["start"], span["end"]
    s_off = int(s.get("char_offset") or 0)
    e_end = e.get("char_end")
    e_end = int(e_end) if e_end is not None else None
    keys = [(ln.page, ln.line_index) for ln in lines]
    i0 = keys.index((s["page"], s["line_index"]))
    i1 = keys.index((e["page"], e["line_index"]))
    chunk = lines[i0 : i1 + 1]
    texts = [ln.text for ln in chunk]
    # 끝을 먼저 자르고 시작을 자른다 — 같은 행 안의 구간(시작·끝이 한 행)도 맞는다
    if e_end is not None:
        texts[-1] = texts[-1][:e_end]
    if s_off:
        texts[0] = texts[0][s_off:]
    text = "\n".join(texts).strip()
    refs = []
    by_page: dict[int, list[Line]] = {}
    for ln in chunk:
        by_page.setdefault(ln.page, []).append(ln)
    for page, pls in by_page.items():
        start = pls[0].char_start + (s_off if pls[0] is chunk[0] else 0)
        if pls[-1] is chunk[-1] and e_end is not None:
            end = pls[-1].char_start + e_end
        else:
            end = pls[-1].char_start + len(pls[-1].text)
        refs.append(
            {
                "document_id": document_id,
                "part_id": part_id,
                "page": page,
                "layout_block_id": None,
                "char_range": [start, min(end, len(page_texts.get(page, "")))],
                "layer": "L4",
            }
        )
    return text, refs


# ── 경계 색인 (D-090) 보조 ────────────────────────────────────────────────


def line_bbox_index(doc_path: str | Path, part_id: str, page: int) -> dict:
    """쪽의 L2 행 bbox를 «비어 있지 않은 행 번호» 기준으로. 없으면 빈 dict.

    출력: {"boxes": [bbox,...] (블록 순서), "image_width", "image_height"}
    """
    import json

    p = Path(doc_path) / "L2_ocr" / f"{part_id}_page_{page:03d}.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    pairs = _l2_line_boxes(Path(doc_path), part_id, page)
    return {
        "boxes": [b for b, _d in pairs],
        "directions": [d for _b, d in pairs],
        "image_width": data.get("image_width"),
        "image_height": data.get("image_height"),
    }


def anchor_bbox(
    doc_path: str | Path,
    part_id: str,
    page: int,
    line_index: int,
    offset: int = 0,
    offset_end: Optional[int] = None,
) -> Optional[dict]:
    """경계 앵커(쪽·행·글자)를 L2 행 bbox로. L4 행과 L2 행 수가 맞아야 신뢰할 수 있다.

    offset·offset_end(글자, exclusive)가 행 중간이면 행 bbox를 글자 비율로 잘라 돌려준다
    (D-090 2단계). 글자마다 좌표가 없으므로 «행 길이 × 글자 비율»의 추정이다 — 세로쓰기는
    위아래, 가로쓰기는 좌우로 자른다.

    L4의 line_index는 빈 행을 포함한 번호다. L2 행은 비어 있지 않은 행만 있으므로,
    같은 쪽의 L4 텍스트에서 앞선 빈 행 수를 빼서 대응시킨다. 수가 어긋나면 None —
    틀린 좌표를 보여 주는 것보다 안 보여 주는 게 낫다.
    """
    from core.document import get_corrected_text

    idx = line_bbox_index(doc_path, part_id, page)
    if not idx or not idx["boxes"]:
        return None
    try:
        text = get_corrected_text(Path(doc_path), part_id, page).get("corrected_text") or ""
    except Exception:  # noqa: BLE001
        return None
    raw = text.split("\n")
    nonempty = [i for i, t in enumerate(raw) if t.strip()]
    if len(nonempty) != len(idx["boxes"]) or line_index not in nonempty:
        return None
    k = nonempty.index(line_index)
    box = list(idx["boxes"][k])
    n = max(1, len(raw[line_index]))
    cut_start = bool(offset and offset > 0)
    cut_end = offset_end is not None and offset_end < n
    if box and len(box) == 4 and (cut_start or cut_end):
        f0 = min(1.0, max(0.0, (offset or 0) / n))
        f1 = min(1.0, max(f0, (offset_end if offset_end is not None else n) / n))
        dirs = idx.get("directions") or ["vertical_rtl"] * len(idx["boxes"])
        x1, y1, x2, y2 = box
        if str(dirs[k]).startswith("vertical"):
            box = [x1, y1 + (y2 - y1) * f0, x2, y1 + (y2 - y1) * f1]
        else:
            box = [x1 + (x2 - x1) * f0, y1, x1 + (x2 - x1) * f1, y2]
    return {
        "bbox": box,
        "image_width": idx["image_width"],
        "image_height": idx["image_height"],
    }


def boundary_bbox(doc_path: str | Path, part_id: str, start: dict, end: dict) -> Optional[dict]:
    """경계의 시작·끝 행 bbox 캐시(boundary.schema의 bbox)."""
    s = anchor_bbox(
        doc_path, part_id, int(start["page"]), int(start["line"]), int(start.get("offset") or 0)
    )
    e_off = end.get("offset")
    e = anchor_bbox(
        doc_path,
        part_id,
        int(end["page"]),
        int(end["line"]),
        0,
        int(e_off) if e_off is not None else None,
    )
    if not s and not e:
        return None
    ref = s or e
    return {
        "start_line": (s or {}).get("bbox"),
        "end_line": (e or {}).get("bbox"),
        "image_width": ref.get("image_width"),
        "image_height": ref.get("image_height"),
    }


def boundary_span(boundary: dict) -> dict:
    """경계 항목을 span_to_text_and_refs()가 받는 구간 형식으로."""
    return {
        "title": boundary.get("title", ""),
        "kind": boundary.get("kind", ""),
        "start": {"page": boundary["start"]["page"], "line_index": boundary["start"]["line"]},
        "end": {"page": boundary["end"]["page"], "line_index": boundary["end"]["line"]},
    }


def line_of_offset(page_text: str, offset: int) -> int:
    """쪽 텍스트 안의 글자 오프셋이 몇 번째 행(0-based, 빈 행 포함)인지."""
    if offset <= 0:
        return 0
    return page_text.count("\n", 0, min(offset, len(page_text)))


def anchor_from_refs(refs: list[dict], page_texts: dict[int, str]) -> Optional[dict]:
    """TextBlock의 source_refs(쪽·char_range)에서 시작·끝 행 앵커를 계산한다 (D-090).

    위치의 정본은 source_refs 하나다. 행 번호는 저장하지 않고 읽을 때 계산한다 — 그래야
    합치기·쪼개기·경계 옮기기 어느 경로로 바꿔도 색인이 어긋나지 않는다.
    char_range가 없는 참조(옛 편성)는 그 쪽 전체로 본다.
    """
    refs = [r for r in (refs or []) if r.get("page")]
    if not refs:
        return None
    first, last = refs[0], refs[-1]
    t0 = page_texts.get(int(first["page"]), "")
    t1 = page_texts.get(int(last["page"]), "")
    cr0 = first.get("char_range") or [0, len(t0)]
    cr1 = last.get("char_range") or [0, len(t1)]
    s_at = int(cr0[0])
    e_at = max(0, int(cr1[1]) - 1)  # 마지막 글자
    s_line_start = t0.rfind("\n", 0, min(s_at, len(t0))) + 1
    e_line_start = t1.rfind("\n", 0, min(e_at, len(t1))) + 1
    e_line_end = t1.find("\n", e_line_start)
    e_line_end = len(t1) if e_line_end < 0 else e_line_end
    e_off: Optional[int] = max(0, int(cr1[1]) - e_line_start)
    if e_off >= e_line_end - e_line_start:
        e_off = None  # 행 끝까지 — 행 단위 경계와 같은 뜻
    return {
        # offset — 행 안의 시작 글자(0 = 행 첫머리). end.offset은 exclusive 끝 글자(행 길이면 행 끝)
        "start": {
            "page": int(first["page"]),
            "line": line_of_offset(t0, s_at),
            "offset": max(0, s_at - s_line_start),
        },
        "end": {
            "page": int(last["page"]),
            "line": line_of_offset(t1, e_at),
            "offset": e_off,
        },
    }
