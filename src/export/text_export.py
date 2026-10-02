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
    ② 줄 잇기 — PDF 판면 때문에 생긴 줄바꿈만 지운다. 세로쓰기의 한 열·가로쓰기의 한 줄은
       문장 단위가 아니다. 줄이 쪽의 보통 길이보다 짧게 끝나면 문단이 끝난 것으로 보고,
       ○·【·〔 같은 머리로 시작하는 줄은 새 문단으로 본다.
       - 세로쓰기는 열을 그대로 붙인다(한문에는 띄어쓰기가 없다).
       - 가로쓰기는 줄 사이에 빈칸 하나를 둔다. 영어 낱말이 «con-»처럼 하이픈으로 끊겼으면
         하이픈을 떼고 붙인다. 한글이 없는 줄끼리(한문·일본어)는 한자·가나끼리 만나면 붙인다.
         한글 문헌은 줄이 **어절 한가운데서** 꺾였는지(옛 국한문 조판) 같은 문헌 안의 근거로
         가린다(WordEvidence) — 사전 없이 판정하므로 틀리는 자리가 남는다.
       - 문단이 쪽을 넘어 이어지면(쪽의 마지막 줄이 가득 찼으면) 다음 쪽 첫 줄과 잇고, 그 자리에
         쪽 표시를 글 안에 넣는다.
       잇는 규칙이 틀리면 원문 줄바꿈이 필요할 수 있어 keep_lines=True로 끌 수 있다.
    ③ 쪽마다 되풀이되는 머리글·바닥글 빼기 — 학술지 이름·논문 제목·쪽수처럼 여러 쪽의 첫머리
       (또는 끝) 두 줄 안에 같은 글(숫자는 무시)이 되풀이되는 줄. 뺀 줄 수는 돌려준다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

import regex

_NOISE_CHARS = set("〇○、。・，,.·□-—_|/\\1234567890 ")
_PARA_STARTERS = ("○", "◎", "●", "【", "〔", "(", "（", "「", "第")
# 가로쓰기에서는 「·(로 시작하는 줄이 문장 중간에서 흔히 꺾인다(«「擬人體」라는», «(1990)») —
# 새 문단으로 보면 문단이 잘게 쪼개진다. 기호 머리와 번호 매김만 새 문단으로 본다
_PARA_STARTERS_H = ("○", "◎", "●", "■", "□", "▶", "【", "〔", "第")
_NUMBERED_H = re.compile(r"^(?:\(?\d{1,2}\)[.\s]|\d{1,2}\.\s|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.)")
_LATIN_HYPHEN = re.compile(r"[A-Za-z]-$")
# 한자(확장 포함)·가나·전각 구두점(、。「」 등) — 이 글자끼리 만나는 줄 경계에는 빈칸을 넣지 않는다
_NO_SPACE = regex.compile(
    r"[\p{Han}\p{Hiragana}\p{Katakana}\p{Block=CJK_Symbols_and_Punctuation}"
    r"\p{Block=Halfwidth_and_Fullwidth_Forms}]"
)


def _width(s: str) -> int:
    """화면 폭으로 센 길이 — 한자·한글은 2, 로마자·숫자는 1.

    가로쓰기 국한문 논문은 한 줄에 로마자가 섞이면 글자 수가 들쭉날쭉해, 글자 수로 «가득 찬
    줄»을 재면 꽉 찬 줄을 짧은 줄로 오판한다.
    """
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F", "A") else 1 for c in s)


def _starts_para(line: str, horizontal: bool) -> bool:
    if horizontal:
        return line.startswith(_PARA_STARTERS_H) or bool(_NUMBERED_H.match(line))
    return line.startswith(_PARA_STARTERS)


_HANGUL_HEAD = regex.compile(r"^\p{Hangul}+")
_HAN_HEAD = regex.compile(r"^\p{Han}+")
_WORD_EDGE = regex.compile(r"[\p{Hangul}\p{Han}]$")
# 어절 양끝에서 떼어 내는 문장 부호 — «있다.»의 «있다», «(物質的인»의 «物質的인»
_TOKEN_STRIP = "()（）「」『』[]〔〕<>《》〈〉,.;:!?·、。'\"‘’“”"


class WordEvidence:
    """이 문헌 안에서 «어절 한가운데서 꺾인 줄»을 가려낼 근거 (2026-10-02).

    왜 필요한가: 옛 국한문 논문은 글자 단위로 양쪽을 맞춰, 줄이 어절 한가운데서 꺾인다
    («그대|로», «있|다», «나타|나며»). 그 자리에 빈칸을 넣으면 «그대 로»가 되고, 붙이면 어절
    경계에서 꺾인 줄(«概念이라면|적어도»)이 «概念이라면적어도»가 된다. 사전을 들이지 않고
    **같은 문헌의 줄 가운데**를 근거로 고른다 — 줄 가운데의 어절은 판면에 꺾이지 않은 온전한
    어절이기 때문이다(줄 첫·끝 어절은 꺾인 조각일 수 있어 근거에서 뺀다).

    판정은 이 차례로 하고, 먼저 걸린 것이 이긴다(evidence):
      0. 앞 줄이 한글·한자로 끝나지 않거나(문장 부호·로마자) 다음 줄이 한글·한자로 시작하지
         않으면 빈칸.
      1. 붙임 — 앞 줄 끝 글자 + 다음 줄 첫 조각이 줄 가운데 어절 안에 이어서 나온다
         («있»+«다» → «있다», «對»+«象» → «對象»). 조각은 한글이면 첫 한글 덩어리, 한자면
         첫 한자 두 자까지(한자는 첫 한 자로도 본다).
      2. 빈칸 — 앞 줄이 한글로 끝나고 다음 줄이 한자로 시작한다(국한문 어절은 «한자 어근 +
         한글 토씨» 차례라 한글 다음 한자는 경계다: «갖는|特性을»).
      3. 붙임 — 앞 줄이 한자로 끝나고 다음 줄이 한글로 시작한다(한자 어근 + 한글 토씨:
         «對象|에다가», «依存|하려는»).
      4. 붙임 — 앞 줄 끝 어절이 한자 한 글자이고 그 글자가 줄 가운데에서 홀로 선 적이 없다
         (꺾인 한자어: «置|重», «麗|朝»).
      5. 붙임 — 다음 줄 첫 한글 조각이 두 자 이하이고, 줄 가운데에서 **다른 어절의 일부로** 쓰인
         횟수가 홀로 어절이 된 횟수의 세 배 이상이다(«로»·«의»·«나며» — 조사·어미는 홀로 서지
         않는다. «대개»·«좀» 같은 부사는 다른 어절 안에 들지 않아 걸리지 않는다).
      6. 빈칸 — 앞 줄 끝 어절이나 다음 줄 첫 어절 **가운데 하나라도** 줄 가운데에서 온전한
         어절로 나온 적이 있다(«作品|自體의» — «作品»이 홀로 선 낱말이다).
      7. 근거 없음 — 아래 조판 습관.

    근거가 없는 자리는 **이 문헌의 조판 습관**을 따른다(default). 근거가 분명한 경계에서 «붙임»이
    «빈칸»보다 많으면 글자 단위로 양쪽을 맞춘 옛 조판(줄이 아무 자리에서나 꺾인다 — 이때는 근거
    없는 자리도 꺾인 어절일 가능성이 높다)이고, 아니면 어절 경계에서 줄을 바꾸는 요즘 조판이다.
    한계: 근거 없는 자리는 습관을 따를 뿐이라 틀릴 수 있다(옛 조판에서 «그리고|좀» → «그리고좀»,
    요즘 조판에서 «論究|하려는» → «論究 하려는»). 「그것은|다 같이」처럼 홀로 선 한 글자 낱말이
    줄 머리에 오면 붙을 수 있다.
    """

    def __init__(self, page_texts: dict[int, str]):
        from collections import Counter

        interior: list[str] = []
        alone: Counter = Counter()
        for text in page_texts.values():
            for line in text.splitlines():
                tokens = [t.strip(_TOKEN_STRIP) for t in line.split()]
                for t in tokens[1:-1]:
                    if t:
                        interior.append(t)
                        alone[t] += 1
        self._interior = "\n".join(interior)
        self._alone = alone
        # 이 문헌의 조판 습관 — 근거가 분명한 경계에서 «붙임»이 많은가. 문장 부호로 끝나거나
        # 한글·한자로 시작하지 않는 경계(문장 끝·표 행·로마자)는 습관과 무관하므로 세지 않는다
        votes = {True: 0, False: 0}
        for text in page_texts.values():
            # 빈 줄로 나뉜 두 줄은 판면 꺾임이 아니라 문단 경계다 — 이웃한 두 줄만 센다
            lines = [ln.strip() for ln in text.splitlines()]
            for a, b in zip(lines, lines[1:]):
                if not a or not b:
                    continue
                if not (_WORD_EDGE.search(a) and (_HANGUL_HEAD.match(b) or _HAN_HEAD.match(b))):
                    continue
                v = self.evidence(a, b)
                if v is not None:
                    votes[v] += 1
        self.votes = votes
        self.default = votes[True] > votes[False]

    def evidence(self, a: str, b: str) -> Optional[bool]:
        """a(앞 줄) 끝과 b(다음 줄) 머리가 한 어절인가 — True·False, 근거가 없으면 None."""
        if not a or not b or not _WORD_EDGE.search(a):
            return False
        m = _HANGUL_HEAD.match(b)
        if m:
            head = m.group(0)
        else:
            mh = _HAN_HEAD.match(b)
            if not mh:
                return False
            head = mh.group(0)[:2]
        if a[-1] + head in self._interior or (not m and a[-1] + head[0] in self._interior):
            return True
        # 한글 다음에 한자가 오는 어절은 드물다 — 국한문 어절은 «한자 어근 + 한글 토씨» 차례다
        # («갖는|特性을», «이렇게|慣用的인»은 어절 경계). «스토리|性»처럼 드문 예외는 ①이 잡는다
        if not m and _HANGUL_HEAD.match(a[-1]):
            return False
        last = a.split()[-1].strip(_TOKEN_STRIP)
        a_han = bool(_HAN_HEAD.match(a[-1]))
        # 한자 다음 줄이 한글로 시작하면 한자 어근 + 한글 토씨다(«對象|에다가», «依存|하려는»)
        if m and a_han:
            return True
        # 앞 줄 끝이 한자 한 글자뿐이면 꺾인 한자어다(«置|重», «麗|朝») — 줄 가운데에서
        # 그 한 글자가 홀로 선 적이 없을 때만(«그 時»·«約 一»처럼 홀로 쓰는 글자는 빼려고)
        if not m and a_han and len(last) == 1 and not self._alone[last]:
            return True
        if m and len(head) <= 2:
            inside = self._interior.count(head) - self._alone[head]
            if inside > 0 and inside >= 3 * self._alone[head]:
                return True
        # 앞 줄 끝 어절이나 다음 줄 첫 어절이 줄 가운데에서 온전한 어절로 나온 적이 있으면 경계
        first = b.split()[0].strip(_TOKEN_STRIP)
        if self._alone[last] or self._alone[first]:
            return False
        return None

    def joins(self, a: str, b: str) -> bool:
        """a(앞 줄) 끝과 b(다음 줄) 머리가 한 어절인가. 근거가 없으면 이 문헌의 조판 습관."""
        v = self.evidence(a, b)
        return self.default if v is None else v


def _glue(a: str, b: str, horizontal: bool, evidence: Optional[WordEvidence] = None) -> str:
    """판면 줄바꿈 하나를 지운다. 세로는 그대로 붙이고, 가로는 빈칸(하이픈 낱말은 붙임).

    evidence가 있으면 한글 어절 한가운데서 꺾인 줄은 빈칸 없이 붙인다(WordEvidence).
    """
    if not a:
        return b
    if not b:
        return a
    if not horizontal:
        return a + b
    if _LATIN_HYPHEN.search(a) and b[:1].islower():
        return a[:-1] + b
    # 한글 문헌(evidence 있음)은 한자끼리 만나는 경계도 근거로 가린다 — 국한문에서는
    # «作品|自體»처럼 두 낱말일 수 있다
    # 두 줄 다 한글이 없으면(한글 문헌 속 한문·일본어 인용) 아래의 한자 규칙을 따른다
    if evidence is not None and (_HANGUL.search(a) or _HANGUL.search(b)):
        return a + b if evidence.joins(a, b) else a + " " + b
    # 한글이 없는 가로쓰기(한문·일본어)는 띄어쓰기가 없다 — 양쪽이 한자·가나·전각 구두점이면 붙인다
    if _NO_SPACE.match(a[-1]) and _NO_SPACE.match(b[0]):
        return a + b
    return a + " " + b


def _join(
    lines: list[str],
    horizontal: bool = False,
    flags: Optional[list[tuple[bool, bool]]] = None,
    evidence: Optional[WordEvidence] = None,
) -> tuple[list[str], bool]:
    """줄을 문단으로 잇는다. 출력: (문단 목록, 마지막 문단이 열려 있는가).

    입력 flags는 줄마다 (가득 참, 들여 써서 시작함) — OCR 결과(L2)의 줄 좌표에서 잰 것
    (line_geometry). 있으면 그것으로 문단 끝·시작을 가른다. 없으면 글자 폭으로 어림한다:
    «보통 길이»는 그 쪽 줄 폭의 상위 20% 값이고, 그 0.8배보다 짧은 줄이 문단 끝이다.
    양쪽 맞춤 조판은 줄마다 글자 수가 달라(한자·띄어쓰기가 많은 줄은 글자가 적다) 어림이
    틀리기 쉽다 — 좌표가 있으면 언제나 좌표가 이긴다.
    «열려 있다» = 마지막 줄이 가득 차 끝났다 — 다음 쪽에서 이어질 수 있다.
    """
    pairs = [
        (ln.strip(), flags[i] if flags and i < len(flags) else None)
        for i, ln in enumerate(lines)
        if ln.strip()
    ]
    if not pairs:
        return [], False
    if flags is None or any(f is None for _ln, f in pairs):
        widths = sorted(_width(ln) for ln, _f in pairs)
        full = widths[int(len(widths) * 0.8)] if len(widths) > 1 else widths[0]
        pairs = [(ln, (_width(ln) >= full * 0.8, False)) for ln, _f in pairs]
        if len(pairs) == 1:
            # 한 줄뿐인 쪽은 «가득 찼는지» 잴 기준이 없다 — 열린 것으로 보지 않는다
            pairs = [(pairs[0][0], (False, False))]
    paras: list[str] = []
    buf = ""
    for ln, (is_full, indented) in pairs:
        if buf and (indented or _starts_para(ln, horizontal)):
            paras.append(buf)
            buf = ""
        buf = _glue(buf, ln, horizontal, evidence)
        if not is_full:
            paras.append(buf)
            buf = ""
    if buf:
        paras.append(buf)
        return paras, True
    return paras, False


def line_geometry(l2: dict, n_lines: int) -> Optional[list[tuple[bool, bool]]]:
    """OCR 결과(L2)의 줄 좌표로 줄마다 (가득 참, 들여 써서 시작함)을 잰다.

    입력: L2 JSON, 확정본(L4)의 비어 있지 않은 줄 수. 출력: 줄마다 한 쌍, 또는 None(못 잼).
    L4는 L2를 줄 그대로 옮긴 것이다(권 전체 OCR의 fill_text_layer). 사람이 글자를 고쳐도 줄 수가
    같으면 줄의 자리는 그대로이므로 **줄 수가 같을 때만** 좌표를 쓴다 — 다르면 None(글자 폭 어림).
    블록마다: 줄 끝이 블록에서 가장 먼 줄 끝의 «글자 1.5개» 안이면 가득 참. 줄 머리가 블록의
    가장 앞 머리보다 «글자 0.6개» 이상 들어가 있고 바로 앞 줄은 들어가 있지 않으면 들여 써서
    시작함(인용 단락처럼 줄 전체가 들어간 곳은 첫 줄만 새 문단). 글자 크기는 줄 굵기의 중앙값.
    가로쓰기는 x, 세로쓰기는 y를 잰다.
    """
    out: list[tuple[bool, bool]] = []
    for res in l2.get("ocr_results") or []:
        vertical = str(res.get("writing_direction") or "vertical_rtl").startswith("vertical")
        rows = [ln for ln in res.get("lines") or [] if (ln.get("text") or "").strip()]
        if not rows:
            continue
        spans = []
        for ln in rows:
            b = ln.get("bbox")
            if not (isinstance(b, list) and len(b) == 4):
                return None
            x1, y1, x2, y2 = (float(v) for v in b)
            spans.append((y1, y2, x2 - x1) if vertical else (x1, x2, y2 - y1))
        thick = sorted(s[2] for s in spans)[len(spans) // 2] or 1.0
        far = max(s[1] for s in spans)
        near = min(s[0] for s in spans)
        if len(spans) == 1:
            # 한 줄뿐인 블록은 견줄 줄이 없어 «가득 찼는지» 모른다 — 그 줄 자신이 «가장 먼 끝»이라
            # 언제나 가득 참이 되어 다음 쪽 문단과 붙었다(Codex 지적 2026-10-02). 문단 끝으로 본다
            out.append((False, False))
            continue
        prev_in = False
        for a, z, _t in spans:
            is_in = a > near + 0.6 * thick
            # 첫 줄이 들어가 있으면 이 쪽은 새 문단으로 시작한다 — 앞 쪽 문단과 잇지 않는다
            out.append((z >= far - 1.5 * thick, is_in and not prev_in))
            prev_in = is_in
    return out if len(out) == n_lines else None


MIN_LINES_FOR_RUNNING = 6


def running_line_keys(page_texts: dict[int, str], edge: int = 2) -> set[str]:
    """쪽마다 되풀이되는 머리글·바닥글의 대조 글자. 입력: {쪽: 텍스트}. 출력: 키 집합.

    각 쪽의 첫 edge줄·끝 edge줄만 본다. 숫자(아라비아)는 #로 바꾸고 빈칸을 뺀 글이 세 쪽 이상,
    그리고 쪽 수의 30% 이상에서 그 자리에 나오면 머리글이다 — 홀짝 쪽이 서로 다른 머리글
    (학술지 이름 / 논문 제목)을 달아도 각각 절반쯤이라 걸린다.
    줄이 몇 안 되는 쪽(MIN_LINES 미만)은 세지 않는다 — 그런 쪽은 «가장자리 두 줄»이 곧 본문이라,
    숫자만 다른 본문 줄(«측정값 10»·«측정값 20»)이 머리글로 잡혀 내보내기에서 빠졌다(Codex 지적
    2026-10-02). 빼는 것은 내보내기뿐이고 확정본은 그대로이며, 뺀 줄 수는 통계로 돌려준다.
    """
    from collections import Counter

    if len(page_texts) < 3:
        return set()
    seen: Counter = Counter()
    for text in page_texts.values():
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if len(lines) < MIN_LINES_FOR_RUNNING:
            continue
        keys = {_running_key(ln) for ln in lines[:edge] + lines[-edge:]}
        seen.update(k for k in keys if len(k) >= 2)
    need = max(3, int(len(page_texts) * 0.3 + 0.999))
    return {k for k, n in seen.items() if n >= need}


def _running_key(line: str) -> str:
    return re.sub(r"\s", "", re.sub(r"[0-9]+", "#", line))


def join_columns(lines: list[str], horizontal: bool = False) -> list[str]:
    """세로 열(또는 가로 줄)을 문단으로 잇는다. 입력: 한 쪽의 줄, 가로쓰기 여부. 출력: 문단 목록."""
    return _join(lines, horizontal)[0]


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


@dataclass
class Chapter:
    """내보낼 장 하나 — 제목·층위와 쪽별 줄."""

    title: str
    level: int
    pages: list[tuple[int, list[str]]] = field(default_factory=list)
    # pages와 나란한 줄 좌표 판정 — 항목마다 줄별 (가득 참, 들여 씀) 또는 None(못 잼)
    flags: list = field(default_factory=list)


def _compact(s: str) -> str:
    return re.sub(r"[\s・.·、。,()（）]", "", s)


def _title_anchor(title: str) -> str:
    """제목 대조 글자 — 정본은 core.read_plan.title_anchor(강독 들이기와 같은 규칙을 쓰려고)."""
    from core.read_plan import title_anchor

    return title_anchor(title)


def build_chapters(
    page_texts: dict[int, str],
    chapters: list[dict],
    front_title: str = "앞붙이",
    geometry: Optional[dict[int, list[tuple[bool, bool]]]] = None,
) -> tuple[list[Chapter], dict]:
    """쪽 텍스트를 장으로 나눈다.

    입력: {PDF 쪽: L4 텍스트}, 계획의 chapters([{page, title, level}]), 첫 장 앞 부분의 이름,
          {쪽: 줄 좌표 판정}(line_geometry — 비어 있지 않은 L4 줄과 나란하다, 없어도 된다).
    출력: (장 목록, {"noise_lines": 뺀 줄 수, "running_lines": 뺀 머리글·바닥글 줄 수,
          "anchored": 제목 글자로 쪽 안 자리를 찾은 장 수}).
    장의 시작 쪽에서 제목 글자(번호 머리를 뗀 앞 6자)를 찾으면 그 줄부터 새 장이다 — 펼침 쪽은
    앞 장의 끝과 새 장의 시작이 한 쪽에 같이 있다. 못 찾으면 그 쪽 첫 줄부터.
    """
    starts = sorted(chapters, key=lambda c: (c["page"], c.get("level", 1)))
    out: list[Chapter] = [Chapter(front_title, 1)]
    stats = {"noise_lines": 0, "running_lines": 0, "anchored": 0}
    running = running_line_keys(page_texts)
    by_page: dict[int, list[dict]] = {}
    for c in starts:
        by_page.setdefault(int(c["page"]), []).append(c)
    for page in sorted(page_texts):
        raw = [ln.strip() for ln in page_texts[page].splitlines() if ln.strip()]
        geo = (geometry or {}).get(page)
        if geo is not None and len(geo) != len(raw):
            geo = None
        lines = []
        kept_flags: list = []
        for i, ln in enumerate(raw):
            if is_noise_line(ln):
                stats["noise_lines"] += 1
            elif running and (i < 2 or i >= len(raw) - 2) and _running_key(ln) in running:
                stats["running_lines"] += 1
            else:
                lines.append(ln)
                kept_flags.append(geo[i] if geo else None)

        def _add(ch: Chapter, a: int, b: int, page=page, lines=lines, kept=kept_flags) -> None:
            ch.pages.append((page, lines[a:b]))
            ch.flags.append(kept[a:b] if kept and kept[0] is not None else None)

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
                _add(out[-1], cursor, cut)
            cursor = cut
            out.append(Chapter(c["title"], int(c.get("level") or 1)))
        if cursor < len(lines):
            _add(out[-1], cursor, len(lines))
    if not out[0].pages:
        out.pop(0)
    return out, stats


def page_marker(page: int, labels: Optional[list[tuple[str, str]]] = None) -> str:
    """쪽 표시 글자. 예: «PDF p.46 · 교재 42면» — PDF 쪽과 다른 체계(손글씨 면 등)를 나란히 둔다."""
    parts = [f"PDF p.{page}"] + [f"{name} {value}면" for name, value in labels or []]
    return " · ".join(parts)


def _mark(page: int, fmt: str, labels: Optional[dict], inline: bool = False) -> str:
    """쪽 표시. inline이면 문단 안에 넣는 꼴(굵게 하지 않는다 — 문장 가운데라 눈에 덜 걸리게)."""
    mark = page_marker(page, (labels or {}).get(page))
    if fmt == "md":
        return f'<a id="p{page}"></a>[{mark}]' if inline else f'<a id="p{page}"></a>**[{mark}]**'
    if inline:
        return f'<span id="p{page}">[{mark}]</span>'
    return f"<span id=\"p{page}\">'''[{mark}]'''</span>"


def _body(
    ch: Chapter,
    fmt: str,
    keep_lines: bool,
    labels: Optional[dict] = None,
    horizontal: Optional[dict] = None,
    evidence: Optional[WordEvidence] = None,
) -> str:
    """장 하나의 본문. horizontal은 {쪽: 가로쓰기인가} — 없는 쪽은 세로쓰기로 본다.
    evidence는 어절 한가운데서 꺾인 줄을 가리는 근거(WordEvidence, 없으면 언제나 빈칸).

    줄을 이을 때는 쪽을 넘는 문단을 하나로 잇는다: 앞 쪽의 마지막 문단이 열려 있고(마지막 줄이
    가득 참) 이 쪽 첫 줄이 새 문단 머리가 아니면, 이 쪽 첫 문단을 앞 문단 뒤에 붙이고 그 사이에
    쪽 표시를 글 안에 넣는다. 그렇지 않으면 쪽 표시를 제 줄에 둔다.
    잇는 것은 **바로 앞 쪽**(PDF 쪽 번호가 1 차이)이고 **쓰기 방향이 같을 때**뿐이다 — 사이 쪽의
    확정본이 없거나(2쪽이 빠진 1→3쪽) 세로 본문 다음 가로 부록이면 이어 붙이지 않는다.
    """
    parts: list[str] = []
    # parts[-1]과 같은 문단의 **표시 없는** 글 — 잇기 판정(빈칸·어절 근거)은 이것으로 한다.
    # 쪽 표시가 섞인 글로 판정하면 앞 줄 끝 어절이 «p.2]作品»처럼 되어 근거를 못 찾는다
    clean_last = ""
    still_open = False
    prev_page: Optional[int] = None
    prev_hz: Optional[bool] = None
    for idx, (page, lines) in enumerate(ch.pages):
        hz = bool((horizontal or {}).get(page))
        if keep_lines:
            parts.append(_mark(page, fmt, labels))
            parts.append(("  \n" if fmt == "md" else "<br />\n").join(lines))
            continue
        flags = ch.flags[idx] if idx < len(ch.flags) else None
        paras, open_tail = _join(lines, hz, flags, evidence)
        first = next((ln.strip() for ln in lines if ln.strip()), "")
        first_indented = bool(flags and flags[0][1])
        continues = (
            still_open
            and paras
            and parts
            and prev_page == page - 1
            and prev_hz == hz
            and not first_indented
            and not _starts_para(first, hz)
        )
        if continues:
            # 잇는 방식(빈칸 여부)은 쪽 표시 없이 글끼리 정하고, 그 이음매에 표시를 넣는다 —
            # 표시를 먼저 붙이면 «그대|로»의 «로»가 표시 뒤에 숨어 판정이 늘 빈칸이 된다
            joined = _glue(clean_last, paras[0], hz, evidence)  # 언제나 paras[0]으로 끝난다
            head = joined[: len(joined) - len(paras[0])]
            # head는 clean_last 그대로 + 빈칸이거나, 하이픈 낱말이면 clean_last에서 끝 «-»를 뗀 것
            if head.startswith(clean_last):
                parts[-1] = parts[-1] + head[len(clean_last) :]
            else:
                parts[-1] = parts[-1][: len(head) - len(clean_last)]
            parts[-1] += _mark(page, fmt, labels, inline=True) + paras[0]
            clean_last = joined
            paras = paras[1:]
        else:
            parts.append(_mark(page, fmt, labels))
        parts.extend(paras)
        if paras:
            clean_last = paras[-1]
        still_open = open_tail
        prev_page, prev_hz = page, hz
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
    horizontal: Optional[dict] = None,
    evidence: Optional[WordEvidence] = None,
) -> dict[str, str]:
    """장 목록을 파일들로. 입력: 책 제목, 장, 형식("md" | "wiki"), 줄 유지 여부, 출처 한 줄,
    쪽 이름표({PDF 쪽: [(이름, 값)]} — read_plan.page_label_map), {쪽: 가로쓰기인가},
    어절 근거(WordEvidence — 가로쓰기 한글의 꺾인 어절을 붙인다).

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
            texts.append(_body(ch, fmt, keep_lines, labels, horizontal, evidence))
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


_HANGUL = regex.compile(r"\p{Hangul}")


def page_directions(
    doc_path, part_id: str, page_texts: dict[int, str], plan: Optional[dict] = None
) -> tuple[dict[int, bool], dict]:
    """쪽마다 가로쓰기인가. 출력: ({쪽: 가로쓰기인가}, {"plan": n, "ocr": n, "guess": n}).

    알아내는 차례 — 사람이 정한 것이 먼저다:
      1. 작업 계획(read_plan)의 쓰기 방향 — 사람이 말했거나 화면에서 적용한 것.
      2. 그 쪽 OCR 결과(L2)의 블록 쓰기 방향 — OCR을 돌릴 때 정한 것(글자 수가 많은 쪽으로).
      3. 둘 다 없으면 글자에서 어림: 한글이 글자의 20% 이상이면 가로쓰기. 한글 세로쓰기
         책은 여기서 틀린다 — 그런 책은 계획에 쓰기 방향을 적으면 1번이 이긴다.
    """
    import json
    from pathlib import Path

    from core.read_plan import page_settings

    doc_path = Path(doc_path)
    settings: dict[int, dict] = {}
    if plan:
        try:
            # 저장된 계획의 범위는 닫혀 있다(validate_plan) — 쪽 수 없이 읽는다
            settings = page_settings(plan, None)
        except (ValueError, KeyError):
            settings = {}
    out: dict[int, bool] = {}
    used = {"plan": 0, "ocr": 0, "guess": 0}
    for page, text in page_texts.items():
        s = settings.get(page) or {}
        if s.get("writing"):
            out[page] = s["writing"].startswith("horizontal")
            used["plan"] += 1
            continue
        votes = {True: 0, False: 0}
        f = doc_path / "L2_ocr" / f"{part_id}_page_{page:03d}.json"
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            for res in data.get("ocr_results") or []:
                wd = str(res.get("writing_direction") or "")
                if not wd:
                    continue
                n = sum(len(ln.get("text") or "") for ln in res.get("lines") or []) or 1
                votes[wd.startswith("horizontal")] += n
        if votes[True] or votes[False]:
            out[page] = votes[True] > votes[False]
            used["ocr"] += 1
            continue
        letters = [c for c in text if not c.isspace()]
        out[page] = bool(letters) and len(_HANGUL.findall(text)) / len(letters) >= 0.2
        used["guess"] += 1
    return out, used


def export_document(
    doc_path, part_id: str, fmt: str = "md", keep_lines: bool = False
) -> tuple[dict[str, str], dict]:
    """문헌의 L4를 장별 파일로. 입력: 문헌 경로, 권, 형식, 줄 유지. 출력: (파일들, 통계).

    장은 문헌의 read_plan.json(작업 계획)에서 읽는다. 계획이 없으면 한 장(책 전체)이다.
    줄 잇기의 쓰기 방향은 page_directions가 쪽마다 정한다.
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
    # 줄 좌표(L2) — 문단 끝·시작을 글자 폭 어림보다 정확히 가른다(line_geometry)
    import json

    geometry: dict[int, list] = {}
    for n, text in page_texts.items():
        f = doc_path / "L2_ocr" / f"{part_id}_page_{n:03d}.json"
        if not f.exists():
            continue
        try:
            l2 = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        geo = line_geometry(l2, sum(1 for ln in text.splitlines() if ln.strip()))
        if geo is not None:
            geometry[n] = geo
    chapters, stats = build_chapters(
        page_texts, plan.get("chapters") or [], front_title=title, geometry=geometry
    )
    stats["geometry_pages"] = len(geometry)
    # 데이터 판 각인(D-128 1항) — 교정 후 다시 내보낸 파일과 구별된다
    try:
        from core.corpus_version import corpus_snapshot

        cv = corpus_snapshot(doc_path.parent.parent, document_ids=[doc_path.name])["corpus_hash"]
    except Exception:  # noqa: BLE001 — 각인을 못 해도 내보내기는 된다
        cv = None
    note = f"확정본(L4) {len(page_texts)}쪽에서 만듦" + (f" · {cv}" if cv else "")
    from core.read_plan import page_label_map

    labels = page_label_map(plan) if plan else {}
    horizontal, direction_from = page_directions(doc_path, part_id, page_texts, plan)
    # 꺾인 어절의 근거는 이 문헌 전문에서 — 가로쓰기 쪽이 있고 한글 문헌일 때만 만든다.
    # 한글이 없는 가로쓰기(한문·일본어)는 띄어쓰기가 없으니 근거 없이 한자끼리 붙인다
    all_text = "".join(page_texts.values())
    korean = len(_HANGUL.findall(all_text)) >= 0.05 * max(1, len(all_text))
    evidence = WordEvidence(page_texts) if any(horizontal.values()) and korean else None
    files = render(
        title,
        chapters,
        fmt,
        keep_lines,
        source_note=note,
        labels=labels,
        horizontal=horizontal,
        evidence=evidence,
    )
    stats.update(
        {
            "pages": len(page_texts),
            "chapters": len(chapters),
            "files": len(files),
            "horizontal_pages": sum(horizontal.values()),
            "direction_from": direction_from,
        }
    )
    return files, stats
