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
_DAY = rf"(?:是日|翌日|朔日?|晦日?|初{_NUM}日|{_NUM}日)"
DATE_HEAD_RE = re.compile(rf"^(?P<ganzhi>{_GANZHI})?年?(?P<month>{_MONTH})?(?P<day>{_DAY})?")

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
    matched: str = ""  # 날짜로 읽은 원문 조각

    @property
    def present(self) -> bool:
        return bool(self.matched)


def parse_date_head(text: str) -> DateHead:
    """행 첫머리의 날짜 조각을 읽는다. 干支만 있는 것은 날짜로 치지 않는다."""
    m = DATE_HEAD_RE.match(text)
    if not m or not (m.group("month") or m.group("day")):
        return DateHead()
    head = DateHead(ganzhi=m.group("ganzhi"), matched=m.group(0))
    mon = m.group("month")
    if mon:
        if mon == "是月":
            head.is_month_rel = True
        else:
            head.month = cjk_number(mon.replace("閏", "").rstrip("月"))
    day = m.group("day")
    if day:
        if day in ("是日", "翌日"):
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
    title: str
    date: dict
    kind: str  # 맞은 title_word, 없으면 ""
    place: str  # 날짜 뒤·어휘 앞 조각
    confidence: float
    reasons: list = field(default_factory=list)
    suppressed: bool = False
    accepted: bool = False  # min_confidence 이상 & 억제 아님 → 스팬 경계

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "line_index": self.line_index,
            "title": self.title,
            "date": self.date,
            "kind": self.kind,
            "place": self.place,
            "confidence": round(self.confidence, 2),
            "reasons": list(self.reasons),
            "suppressed": self.suppressed,
            "accepted": self.accepted,
        }


def _layout_signals(lines: list[Line], rules: dict) -> dict[tuple[int, int], list[str]]:
    """형식 신호: 짧은 행·내려쓰기. 쪽 안의 본문 행 분포와 비교한다.

    왜 쪽 단위 비교인가: 글자 크기·행 길이는 판식(板式)마다 다르니 절대값을 쓸 수 없다.
    같은 쪽의 중앙값보다 눈에 띄게 짧거나 위가 낮으면 표제로 본다.
    """
    out: dict[tuple[int, int], list[str]] = {}
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
                if top - median_top >= char_px * 0.8:
                    reasons.append("indent")
            if reasons:
                out[(ln.page, ln.line_index)] = reasons
    return out


def _find_title_word(text: str, words: list[str], limit: int) -> tuple[str, int]:
    """표제 어휘가 앞부분(limit 글자 안)에 있으면 (어휘, 위치). 없으면 ("", -1)."""
    best = ("", -1)
    head = text[:limit]
    for w in words:
        pos = head.find(w)
        if pos >= 0 and (best[1] < 0 or pos < best[1]):
            best = (w, pos)
    return best


def propose_boundaries(lines: list[Line], rules: Optional[dict] = None) -> dict:
    """행 목록에서 글 경계 후보를 만든다.

    출력: {"proposals": [...], "spans": [...], "stats": {...}, "rules": 적용된 규칙}
      proposals — 날짜나 표제 어휘가 있는 모든 행 (억제된 것도 표시용으로 포함)
      spans — accepted 제안 사이의 구간. 첫 제안 앞에 행이 있으면 kind="front" 구간.
        {"title", "kind", "start": {"page","line_index"}, "end": {"page","line_index"}(포함),
         "line_count", "proposal_index"}
    """
    rules = normalize_rules(rules)
    layout = _layout_signals(lines, rules)
    limit = rules["max_title_chars"] + 8

    proposals: list[Proposal] = []
    prev_month: Optional[int] = None
    prev_day: Optional[int] = None
    for ln in lines:
        text = ln.text.strip()
        if not text:
            continue
        head = parse_date_head(text) if rules["use_date"] else DateHead()
        word, wpos = _find_title_word(text, rules["title_words"], limit)
        sig = layout.get((ln.page, ln.line_index), [])
        if not head.present and not word:
            continue

        reasons: list[str] = []
        conf = 0.0
        if head.present:
            conf += 0.5
            reasons.append("date")
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
        if head.present and not word and not sig and len(text) > rules["max_title_chars"]:
            conf -= 0.25
            reasons.append("long_line")

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
                    # 본문 속 날짜(예: 三月廿一日李中堂以筆談問曰)가 표제처럼 보일 때 걸리는 자리.
                    # 짧은 행·내려쓰기 신호가 없으면 min_confidence(0.5) 아래로 내려간다.
                    conf -= 0.35
                    reasons.append("date_jump")
            if head.is_day_rel:
                day = prev_day
                reasons.append("same_day")

        suppressed = any(text == s or text.startswith(s) for s in rules["suppress"])
        if suppressed:
            reasons.append("suppressed")

        # 장소·상대: 날짜 뒤부터 표제 어휘 앞까지
        tail_start = len(head.matched)
        place = text[tail_start:wpos] if word and wpos >= tail_start else text[tail_start:limit]
        place = place.strip()
        title = text[: (wpos + len(word)) if word else min(len(text), limit)]

        conf = max(0.0, min(1.0, conf))
        accepted = (not suppressed) and conf >= rules["min_confidence"]
        proposals.append(
            Proposal(
                page=ln.page,
                line_index=ln.line_index,
                title=title,
                date={
                    "ganzhi": head.ganzhi,
                    "month": month,
                    "day": day,
                    "month_inferred": month_inferred,
                    "month_rolled": month_rolled,
                    "text": head.matched,
                },
                kind=word,
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


def _build_spans(lines: list[Line], proposals: list[Proposal]) -> list[dict]:
    """accepted 제안을 경계로 행 목록을 구간으로 나눈다."""
    if not lines:
        return []
    accepted = [p for p in proposals if p.accepted]
    keys = [(ln.page, ln.line_index) for ln in lines]
    bounds = sorted({(p.page, p.line_index) for p in accepted})
    idx_of = {k: i for i, k in enumerate(keys)}
    cut_indices = [idx_of[b] for b in bounds if b in idx_of]
    spans = []
    starts = ([0] if (cut_indices and cut_indices[0] > 0) else []) + cut_indices
    for si, start in enumerate(starts):
        end = (starts[si + 1] - 1) if si + 1 < len(starts) else len(lines) - 1
        if end < start:
            continue
        is_front = start not in cut_indices
        prop = None
        if not is_front:
            prop = next(p for p in accepted if (p.page, p.line_index) == keys[start])
        spans.append(
            {
                "title": prop.title if prop else lines[start].text.strip()[:20],
                "kind": prop.kind if prop else "front",
                "start": {"page": keys[start][0], "line_index": keys[start][1]},
                "end": {"page": keys[end][0], "line_index": keys[end][1]},
                "line_count": end - start + 1,
                "proposal_index": (proposals.index(prop) if prop else None),
            }
        )
    if not cut_indices:
        return []
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
    keys = [(ln.page, ln.line_index) for ln in lines]
    i0 = keys.index((s["page"], s["line_index"]))
    i1 = keys.index((e["page"], e["line_index"]))
    chunk = lines[i0 : i1 + 1]
    text = "\n".join(ln.text for ln in chunk).strip()
    refs = []
    by_page: dict[int, list[Line]] = {}
    for ln in chunk:
        by_page.setdefault(ln.page, []).append(ln)
    for page, pls in by_page.items():
        start = pls[0].char_start
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
