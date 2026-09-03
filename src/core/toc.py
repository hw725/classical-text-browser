"""목차(目錄) 판별·추출·본문 대조 — 글 경계 제안의 세 번째 신호 (D-089).

왜 목차인가:
    목차는 «글이 어디서 시작하는가»를 저자·편자가 이미 적어 둔 것이다. 날짜·형식으로
    추정하는 것보다 신뢰도가 한 단계 위다. 한국문집총간류 문집은 권 앞에 표준 목차가 있다.

역할 분담 — LLM은 두 곳에만:
    1. 어느 쪽이 목차인가 판별 — 규칙(짧은 행 비율·目錄/卷之 표지)이 먼저, LLM은 보조.
    2. 목차 쪽 텍스트에서 항목(제목·층위·葉 번호)을 구조화 — 텍스트만 넘긴다(비전 불필요,
       로컬 소형 모델로 충분). JSON 스키마 강제, 사고 끔(D-083).
    본문과의 대조는 LLM에 묻지 않는다. 목차 순서와 본문 순서는 같으므로 «순서를 지키는
    정렬»(동적 계획법)로 한 번에 맞춘다 — 결정적이고 근거가 남고 비용이 없다.

한계(설계에 반영):
    - 고서 목차의 제목은 본문 표제와 자주 다르다(줄여 쓰기, 卷만 적기). 대조는 «같음»이 아니라
      «가장 비슷하고 순서가 맞음»이다.
    - 목차의 葉 번호는 PDF 쪽 번호와 다르다. 힌트로만 둔다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

# ── 목차 판별 ─────────────────────────────────────────────────────────────

TOC_MARKERS = ("目錄", "目次", "總目", "卷之", "第一卷", "卷第")
# 목차 «시작» 표지 — 이 줄부터 목차다. 序 끝에 이어 쪽 중간에서 시작하는 총목이 있다(운양집 중간본).
TOC_START_MARKERS = ("目錄", "目次", "總目")
_VOLUME_RE = re.compile(
    r"^(?:卷之[一二三四五六七八九十廿卅]+|第[一二三四五六七八九十廿卅]+卷|卷[一二三四五六七八九十廿卅]+|附錄|續集|別集|補遺)"
)
# NDL 계열 엔진은 일본 신자체로 읽는다(卷→巻, 總→総, 錄→録). 표지어·卷 정규식·유사도는
# 정자로 맞춘 뒤 본다. 실측 2026-09-03: 운양집 총목의 「雲養集総目」「第一巻」이 통째로 빠졌다.
_SHINJITAI = str.maketrans(
    {
        "巻": "卷",
        "総": "總",
        "録": "錄",
        "説": "說",
        "傳": "傳",
        "伝": "傳",
        "叙": "敍",
        "雑": "雜",
        "拝": "拜",
        "帰": "歸",
        "満": "滿",
        "稿": "稿",
        "続": "續",
        "祐": "祐",
        "礼": "禮",
        "国": "國",
        "会": "會",
        "気": "氣",
        "対": "對",
        "画": "畫",
        "経": "經",
        "辞": "辭",
        "斉": "齊",
        "処": "處",
    }
)


def _kanji_norm(t: str) -> str:
    """신자체를 정자로. 문자 대 문자 치환만 한다(뜻이 갈리는 글자는 넣지 않는다)."""
    return (t or "").translate(_SHINJITAI)


# 葉 번호는 제목과 띄어 적힌다(OCR에서 공백·점으로 남는다). 붙어 있으면 제목의 일부로 본다.
_LEAF_TAIL_RE = re.compile(r"[\s·]+([一二三四五六七八九十百廿卅〇○0-9]+)$")
# 제목에 붙은 편수 꼬리: 「賦五」「序四十五」「詩一百九十八首」.
# 卷 수사(第一卷)는 층위 1이라 떼지 않는다.
_COUNT_TAIL_RE = re.compile(r"([一二三四五六七八九十百千廿卅]+)(?:首|篇|則|通|章)?$")


@dataclass
class TocEntry:
    title: str
    level: int = 2  # 1 = 卷·篇 같은 상위, 2 = 글
    page_hint: Optional[str] = None  # 목차에 적힌 葉 번호(문자열 그대로)
    source_page: Optional[int] = None
    source_line: Optional[int] = None
    count: Optional[str] = None  # 제목에 붙어 있던 편수(「賦五」의 五) — 제목이 아니라 정보

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "level": self.level,
            "page_hint": self.page_hint,
            "source_page": self.source_page,
            "source_line": self.source_line,
            "count": self.count,
        }


def toc_page_score(lines: list[str], max_title_chars: int = 14) -> float:
    """쪽이 목차일 가능성(0~1). 짧은 행 비율 + 표지어 + 葉 번호 꼬리 비율.

    본문 쪽은 행이 길고 고르며, 목차 쪽은 대부분이 표제 길이의 짧은 행이다.
    """
    texts = [_kanji_norm(t.strip()) for t in lines if t.strip()]
    # 목차 시작 표지(目錄·總目)가 쪽 중간에 있으면 그 줄부터가 목차다 — 앞의 序 꼬리는 빼고 잰다.
    start = next((i for i, t in enumerate(texts) if any(m in t for m in TOC_START_MARKERS)), None)
    if start:
        texts = texts[start:]
    if len(texts) < 4:
        return 0.0
    short = sum(1 for t in texts if len(t) <= max_title_chars) / len(texts)
    marker = any(m in t for t in texts[:6] for m in TOC_MARKERS)
    leaf = sum(1 for t in texts if _LEAF_TAIL_RE.search(t) and len(t) > 1) / len(texts)
    volume = sum(1 for t in texts if _VOLUME_RE.match(t)) / len(texts)
    score = (
        0.6 * short
        + (0.25 if marker else 0.0)
        + 0.15 * min(1.0, leaf * 2)
        + 0.1 * min(1.0, volume * 4)
    )
    return min(1.0, score)


def detect_toc_pages(
    pages: dict[int, list[str]],
    max_title_chars: int = 14,
    search_first: int = 20,
    threshold: float = 0.7,
    continue_short_ratio: float = 0.9,
) -> list[int]:
    """앞쪽 몇 쪽 중 목차로 보이는 쪽을 고른다. 연속된 목차 쪽을 함께 돌려준다.

    입력: {쪽: 행 목록}. 출력: 오름차순 쪽 번호 목록(없으면 빈 목록).
    왜 앞쪽만 보는가: 목차는 권 앞에 선다. 뒤쪽의 짧은 행 뭉치(시구·주석)를 목차로 오인하지 않는다.
    """
    ordered = sorted(pages)[:search_first]
    first = next(
        (p for p in ordered if toc_page_score(pages[p], max_title_chars) >= threshold), None
    )
    if first is None:
        return []
    # 첫 쪽만 문턱(threshold)으로 고르고, 이어지는 쪽은 «짧은 행 비율»로 잇는다.
    # 왜: 목차의 둘째 쪽부터는 표지어(目錄)가 없고 葉 번호도 없을 수 있어 점수가 0.6 언저리에
    # 머문다(운양집 총목 실측 0.63·0.65). 본문 첫 쪽(卷之一 + 著·校正 + 본문 열)은 짧은 행
    # 비율이 0.8 남짓이라 0.9 문턱에서 갈린다. 중간에 끊기면 그 뒤는 본문이다.
    run = [first]
    for p in ordered:
        if p <= first:
            continue
        if p != run[-1] + 1:
            break
        texts = [t.strip() for t in pages[p] if t.strip()]
        if len(texts) < 4:
            break
        short = sum(1 for t in texts if len(t) <= max_title_chars) / len(texts)
        if short >= continue_short_ratio:
            run.append(p)
        else:
            break
    return run


# ── 항목 추출 (규칙) ──────────────────────────────────────────────────────


def extract_toc_entries_rule(pages: dict[int, list[str]], toc_pages: list[int]) -> list[TocEntry]:
    """목차 쪽의 행을 항목으로. 卷之X 등은 층위 1, 나머지 층위 2. 꼬리의 葉 번호는 떼어 힌트로."""
    entries: list[TocEntry] = []
    for page in toc_pages:
        raws = pages.get(page, [])
        # 첫 쪽에서 목차 시작 표지(目錄·總目) 앞의 행은 序 꼬리다 — 항목이 아니다.
        start = next(
            (
                i
                for i, raw in enumerate(raws)
                if any(m in _kanji_norm(raw) for m in TOC_START_MARKERS)
            ),
            None,
        )
        for i, raw in enumerate(raws):
            if start is not None and i <= start:
                continue
            t = _kanji_norm(raw.strip())
            if not t or any(t == m or t.endswith(m) for m in ("目錄", "目次", "總目")):
                continue
            level = 1 if _VOLUME_RE.match(t) else 2
            hint = None
            count = None
            m = _LEAF_TAIL_RE.search(t)
            # 卷之一 같은 상위 표제의 수사는 葉 번호가 아니다
            if m and level == 2 and len(t) - len(m.group(0)) >= 2:
                hint = m.group(1)
                t = t[: -len(m.group(0))].strip()
            elif level == 2:
                # 붙은 편수(「賦五」「序四十五」「擊磬集七十二」) — 문집 총목은 葉 번호 대신
                # 편수를 적는다. 제목이 아니므로 떼어 count에 둔다.
                # 卷之一의 수사는 층위 1이라 떼지 않는다.
                c = _COUNT_TAIL_RE.search(t)
                if c and len(t) - len(c.group(0)) >= 1:
                    count = c.group(1)
                    t = t[: -len(c.group(0))].strip()
            # 편수만 남은 행(「三十」「五十一」) — 총목의 편수 줄 조각이다. 항목이 아니다.
            if not t or _COUNT_TAIL_RE.fullmatch(t):
                continue
            entries.append(
                TocEntry(
                    title=t,
                    level=level,
                    page_hint=hint,
                    source_page=page,
                    source_line=i,
                    count=count,
                )
            )
    return entries


# ── 항목 추출 (LLM 보조) ──────────────────────────────────────────────────

TOC_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "is_toc": {"type": "boolean"},
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "level": {"type": "integer"},
                    "page_hint": {"type": ["string", "null"]},
                },
                "required": ["title", "level"],
            },
        },
    },
    "required": ["is_toc", "entries"],
}

TOC_SYSTEM_PROMPT = (
    "당신은 한문 고서의 목차(目錄)를 구조화하는 도구입니다. 주어진 OCR 텍스트가 목차인지 판단하고, "
    "목차라면 항목을 순서대로 뽑습니다. 규칙: (1) 제목은 보이는 대로, 정규화·번역하지 않는다. "
    "(2) level은 卷·篇·附錄 같은 상위 단위가 1, 개별 글이 2. "
    "(3) 제목 뒤의 葉·쪽 번호는 page_hint로 "
    "떼어 문자열 그대로 둔다. (4) 목차가 아니면 is_toc=false, entries=[]. "
    "(5) OCR 잡음 행(빈 행·기호만 있는 행)은 버린다. 반드시 JSON만 출력한다."
)


def _lenient_json(text: str) -> Optional[dict]:
    text = (text or "").strip()
    for candidate in (text, text[text.find("{") : text.rfind("}") + 1] if "{" in text else ""):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None


def _is_toc_header(title: str) -> bool:
    """「雲養集總目」「目錄」처럼 목차 자체의 머리인가 — 항목이 아니다.

    LLM이 곧잘 항목으로 넣는다(운양집 실측). 규칙 추출과 같은 기준으로 거른다.
    """
    t = _kanji_norm(title.strip())
    return any(t == m or t.endswith(m) for m in TOC_START_MARKERS)


async def _llm_toc_page(
    router, page: int, texts: list[str], kwargs: dict, reference_text: str = ""
) -> tuple[list[TocEntry], dict]:
    """목차 쪽 하나를 LLM에 넘겨 항목을 구조화한다. 실패는 예외로 올린다.

    reference_text — 사람이 붙여 넣은 해제·서지 설명(manifest.segmentation_rules.reference_text).
    권차·편차·수록 작품 같은 배경을 알면 OCR이 깨진 항목의 층위·제목을 더 잘 세운다.
    """
    body = f"[{page}쪽]\n" + "\n".join(t for t in texts if t.strip())
    ref = ""
    if reference_text and reference_text.strip():
        ref = (
            "참고 — 이 문헌의 해제·서지 설명(사람이 적음, 그대로 옮기지 말고 판단에만 쓸 것):\n"
            + reference_text.strip()[:4000]
            + "\n\n"
        )
    prompt = (
        ref + "다음은 고서 앞부분 한 쪽의 OCR 텍스트입니다. "
        "목차인지 판단하고 항목을 JSON으로 뽑으세요.\n"
        '형식: {"is_toc": true, "entries": '
        '[{"title": "...", "level": 1|2, "page_hint": "..."|null}, ...]}\n\n' + body
    )
    response = await router.call(prompt, **kwargs)
    data = _lenient_json(getattr(response, "text", "") or "")
    if not data or "entries" not in data:
        raise ValueError("JSON 응답을 해석할 수 없습니다")
    entries = [
        TocEntry(
            title=str(e.get("title", "")).strip(),
            level=1 if int(e.get("level", 2)) <= 1 else 2,
            page_hint=(str(e["page_hint"]) if e.get("page_hint") not in (None, "") else None),
            source_page=page,
        )
        for e in data.get("entries", [])
        if str(e.get("title", "")).strip() and not _is_toc_header(str(e.get("title", "")))
    ]
    info = {
        "provider": getattr(response, "provider", None),
        "model": getattr(response, "model", None),
        "is_toc": bool(data.get("is_toc", True)),
    }
    return entries, info


async def extract_toc_entries_llm(
    pages: dict[int, list[str]],
    toc_pages: list[int],
    router,
    force_provider: Optional[str] = None,
    force_model: Optional[str] = None,
    reference_text: str = "",
) -> tuple[list[TocEntry], dict]:
    """LLM에 목차 쪽 텍스트를 넘겨 항목을 구조화한다. 실패한 쪽은 규칙 추출로 물러난다.

    왜 쪽마다 따로 부르는가: 운양집 총목(5쪽·항목 100여 개)을 한 번에 넘기자 Gemini의 JSON이
    max_tokens 4096에서 잘려 통째로 실패했다(실측 2026-09-03). 쪽 하나는 30행 안쪽이라
    답이 짧고, 한 쪽이 실패해도 나머지 쪽의 결과는 살아남는다. 순서는 쪽 순서 그대로다.

    출력: (항목, {"method": "llm"|"llm+rule"|"rule", "provider", "model", "is_toc",
                  "error", "pages_llm", "pages_rule"})
    """
    meta: dict = {
        "method": "rule",
        "provider": None,
        "model": None,
        "is_toc": None,
        "error": None,
        "pages_llm": [],
        "pages_rule": [],
    }
    kwargs = {
        "system": TOC_SYSTEM_PROMPT,
        "response_format": "json",
        "max_tokens": 4096,
        "purpose": "toc",
        "think": False,  # 사고 끔(D-083) — 텍스트 입력의 구조화라 사고가 필요 없다
    }
    if force_provider:
        kwargs["force_provider"] = force_provider
    if force_model:
        kwargs["force_model"] = force_model
    entries: list[TocEntry] = []
    errors: list[str] = []
    for page in toc_pages:
        try:
            got, info = await _llm_toc_page(
                router, page, pages.get(page, []), kwargs, reference_text
            )
        except Exception as e:  # noqa: BLE001 — 이 쪽만 규칙으로
            msg = f"{type(e).__name__}: {e}"
            if "사용할 수 없습니다" in str(e) or "찾을 수 없습니다" in str(e):
                # 프로바이더 자체가 없거나 죽은 것 — 쪽마다 같은 실패를 되풀이할 이유가 없다.
                # 남은 쪽은 전부 규칙으로 가고, 오류는 한 번만 적는다.
                rest = toc_pages[toc_pages.index(page) :]
                errors.append(f"{msg} (남은 {len(rest)}쪽 모두 규칙으로)")
                meta["pages_rule"].extend(rest)
                entries.extend(extract_toc_entries_rule(pages, rest))
                break
            errors.append(f"{page}쪽: {msg}")
            meta["pages_rule"].append(page)
            entries.extend(extract_toc_entries_rule(pages, [page]))
            continue
        meta["pages_llm"].append(page)
        meta["provider"] = meta["provider"] or info["provider"]
        meta["model"] = meta["model"] or info["model"]
        if meta["is_toc"] is None or info["is_toc"]:
            meta["is_toc"] = info["is_toc"]
        entries.extend(got)
    if meta["pages_llm"]:
        meta["method"] = "llm" if not meta["pages_rule"] else "llm+rule"
    if errors:
        meta["error"] = "; ".join(errors)[:1500]
    return entries, meta


# ── 본문 대조 (순서를 지키는 정렬) ────────────────────────────────────────


def _norm(t: str) -> str:
    return _kanji_norm(re.sub(r"[\s·。、，,．.:：;；○〇□]+", "", t or ""))


def title_similarity(title: str, line: str) -> float:
    """목차 제목과 본문 행 첫머리의 유사도(0~1). 본문 행은 제목 길이+2자까지만 본다.

    왜 첫머리인가: 표제 행 뒤에 참석자 부기·OCR 중복 꼬리가 붙는다. 제목이 행의 앞에서
    시작하는 것이 핵심 신호다.
    """
    a, b = _norm(title), _norm(line)
    if not a or not b:
        return 0.0
    # 짧은 제목은 우연히 닮는다(「月」「同六」이 본문 아무 행에나 붙었다 — 운양집 실측).
    # 1자는 행이 그 글자 하나일 때만, 2자는 행 첫머리가 정확히 같을 때만 대응한다.
    if len(a) == 1:
        return 0.95 if b == a else 0.0
    if len(a) == 2:
        if b == a:
            return 1.0
        return 0.95 if b.startswith(a) and len(b) <= 6 else 0.0
    head = b[: len(a) + 2]
    ratio = SequenceMatcher(None, a, head).ratio()
    if head.startswith(a):
        ratio = max(ratio, 0.95)
    elif len(a) >= 3 and a in b[: len(a) + 6]:
        # 「卷之一」이 「雲養集卷之一」 안에 들어 있는 경우 — 책 이름을 앞에 붙인 상위 표제
        ratio = max(ratio, 0.9)
    return ratio


@dataclass
class TocMatch:
    entry_index: int
    page: int
    line_index: int
    score: float
    title: str = ""
    level: int = 2

    def to_dict(self) -> dict:
        return {
            "entry_index": self.entry_index,
            "page": self.page,
            "line_index": self.line_index,
            "score": round(self.score, 3),
            "title": self.title,
            "level": self.level,
        }


def align_toc_to_body(
    entries: list[TocEntry],
    body_lines: list,  # segmentation.Line 목록 (page, line_index, text)
    min_score: float = 0.6,
    skip_penalty: float = 0.35,
) -> tuple[list[TocMatch], list[int]]:
    """목차 항목을 본문 행에 순서를 지키며 대응시킨다.

    동적 계획법: 항목 i를 본문 행 j에 놓거나(점수 s_ij) 항목 i를 건너뛴다(감점).
    본문 행은 앞으로만 간다. 출력: (대응 목록, 대응 못 한 항목 index 목록).
    항목 수 E, 후보 행 수 L이면 O(E·L). 후보 행은 유사도 min_score 이상인 것만 두어 L을 줄인다.
    """
    E = len(entries)
    if E == 0 or not body_lines:
        return [], list(range(E))
    # 후보: (entry_i, line_j, score)
    cand: list[list[tuple[int, float]]] = []
    for e in entries:
        row = []
        for j, ln in enumerate(body_lines):
            if not ln.text.strip():
                continue
            s = title_similarity(e.title, ln.text)
            if s >= min_score:
                row.append((j, s))
        cand.append(row)
    # DP over entries; state = last used line index (-1 = none). 후보만 다루므로 상태 수가 작다.
    # best[i] : dict last_j -> (score, backpointer)
    float("-inf")
    best: list[dict[int, tuple[float, Optional[tuple[int, int]]]]] = [{} for _ in range(E + 1)]
    best[0][-1] = (0.0, None)
    for i in range(E):
        for last_j, (sc, _) in best[i].items():
            # skip entry i
            cur = best[i + 1].get(last_j)
            if cur is None or sc - skip_penalty > cur[0]:
                best[i + 1][last_j] = (sc - skip_penalty, (last_j, -1))
            # place entry i on candidate j > last_j
            for j, s in cand[i]:
                if j <= last_j:
                    continue
                cur = best[i + 1].get(j)
                if cur is None or sc + s > cur[0]:
                    best[i + 1][j] = (sc + s, (last_j, j))
    # 최선 종점
    end_j, (end_score, _) = max(best[E].items(), key=lambda kv: kv[1][0])
    # 역추적
    placed: dict[int, int] = {}
    j = end_j
    for i in range(E, 0, -1):
        prev_j, chosen = best[i][j][1]
        if chosen >= 0:
            placed[i - 1] = chosen
        j = prev_j
    matches = []
    unmatched = []
    for i, e in enumerate(entries):
        if i in placed:
            ln = body_lines[placed[i]]
            matches.append(
                TocMatch(
                    entry_index=i,
                    page=ln.page,
                    line_index=ln.line_index,
                    score=title_similarity(e.title, ln.text),
                    title=e.title,
                    level=e.level,
                )
            )
        else:
            unmatched.append(i)
    return matches, unmatched
