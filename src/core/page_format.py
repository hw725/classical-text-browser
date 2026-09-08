"""판식(版式)을 좌표에서 읽는다 — 판심·본문 열·난외를 가른다 (D-120).

왜 필요한가:
    글의 규약을 «되풀이되는 글자»로만 찾으면 종이의 규약에 걸린다. 판심제는 쪽마다 장차가
    붙어 「浩齋辰巳日錄二」「…三」으로 달라지니 되풀이로 안 잡히고, 두주(欄外의 작은 주)는
    본문 행처럼 세어져 없는 규약을 만든다. 실측 2026-09-08: 浩齋辰巳日錄의 「同日」 두주가
    행 첫머리 어휘 후보로 올라왔고, 판심제는 «판심 목록»에 하나도 안 잡혔다.

    그런데 그 둘은 **자리와 크기로 한눈에 다르다**. 세로쓰기 고서의 본문은 키가 같은 열이
    고른 간격으로 서고, 판심은 그 열들 사이가 유난히 벌어진 자리이며, 두주는 본문 열의
    몇십 분의 일 크기다. 글자를 세지 말고 자리를 보면 된다.

무엇을 코드에 두는가:
    책마다 다른 값은 하나도 두지 않는다(D-119와 같은 원칙). 판심이 어디인지, 열이 몇인지,
    본문 열의 키가 얼마인지는 **그 책의 좌표에서 잰다**. 코드에 있는 것은 «본문 열은 키가
    고르고, 판심은 열 사이가 벌어지며, 난외는 훨씬 작다»는 판식 물리뿐이다.

무엇을 하지 않는가:
    행을 지우지 않는다. 라벨만 붙인다 — 규약을 찾을 때 빼고, 화면이 «판심제·두주 몇 행을
    뺐습니다»라고 말할 수 있게. 본문으로 쓸지는 부르는 쪽이 정한다.
"""

from __future__ import annotations

import re
import statistics
from typing import Optional

from core.segmentation import Line

# ── 문턱. 전부 «그 책에서 잰 값에 대한 비율»이고 절대 크기가 아니다 ──────────────
#
# 浩齋65·浩齋93·天津談草·雲養集 실측(2026-09-08): 행 길이 분포가 뚜렷하게 둘로 갈린다.
# 본문 열은 중앙값의 0.98~1.01배에 몰리고 조각은 0.25배 이하이며, 그 사이(0.3~0.95)가
# 비어 있다. 그래서 0.6은 «빈 골짜기 한가운데»다 — 조금 움직여도 결과가 같다.
_BODY_RATIO = 0.6  # 본문 열의 대표 길이에 견줘 이 비율 이상이면 본문 열
_BODY_QUANTILE = 0.75  # 대표 길이는 75분위 — 조각이 아무리 많아도 본문 쪽을 가리킨다
_FOLD_GAP = 2.5  # 열 사이 간격이 중앙값의 이 배를 넘으면 판심(접은 자리)
_MIN_COLUMNS = 6  # 이보다 열이 적은 쪽은 판식을 논하지 않는다(표지·백지)
_FOLD_AGREE = 0.15  # 쪽마다 잰 판심 자리가 책 전체 중앙값에서 이만큼(쪽 너비 비율) 안이어야
_FOLD_PAGES = 0.5  # 판심이 이 비율 이상의 쪽에서 잡혀야 «접어 찍은 책»이다
_COLUMNS_DOMINANT = 0.25  # 으뜸 열 수(예: 10·10)가 판심을 찾은 쪽의 이만큼은 되어야 «일정한 판식»
_TOP_ALIGN = 0.08  # 윗변이 본문 윗변에서 본문 높이의 이만큼 넘게 떨어지면 «본문 열이 아니다»
# 두주로 보려면 «본문 열이 아닌» 정도가 아니라 훨씬 작아야 한다. 내려쓴 별행 표제(D-117의
# indent_alone 판식 — 시집에서 제목만 내려쓴다)가 이 규칙에 걸리면 정작 찾아야 할 표제를 지운다.
# 浩齋 실측 2026-09-08: 두주는 본문 열의 0.03~0.05배였다. 표제는 그보다 훨씬 길다.
_MARGIN_RATIO = 0.25


def _is_vertical(ln: Line) -> bool:
    """입력: 행. 출력: 세로쓰기 여부. 목적: 길이와 배열 축을 일관되게 고른다."""
    return (ln.writing_direction or "vertical_rtl").startswith("vertical")


def _valid_bbox(ln: Line) -> bool:
    """입력: 행. 출력: 유효한 사각형 여부. 목적: 손상 좌표로 본문을 빼지 않는다."""
    b = ln.bbox
    return bool(b and len(b) == 4 and b[2] > b[0] and b[3] > b[1])


def line_length(ln: Line) -> Optional[float]:
    """행의 «글이 흐르는 방향» 길이. 세로쓰기면 높이, 가로쓰기면 너비. bbox가 없으면 None.

    입력: 행. 출력: 픽셀 길이 또는 None. 목적: 본문 열과 난외 조각을 크기로 가른다.
    """
    b = ln.bbox
    if not _valid_bbox(ln):
        return None
    return float(b[3] - b[1]) if _is_vertical(ln) else float(b[2] - b[0])


def line_axis(ln: Line) -> Optional[float]:
    """행이 «늘어서는 방향»의 중심. 세로쓰기면 x, 가로쓰기면 y. bbox가 없으면 None.

    입력: 행. 출력: 픽셀 좌표 또는 None. 목적: 열의 차례와 판심 자리를 본다.
    """
    b = ln.bbox
    if not _valid_bbox(ln):
        return None
    return (float(b[0]) + float(b[2])) / 2 if _is_vertical(ln) else (float(b[1]) + float(b[3])) / 2


def _body_cut(lengths: list[float]) -> float:
    """본문 열로 볼 최소 길이. 입력: 길이 목록. 출력: 문턱. 목적: 난외 조각을 가른다."""
    ordered = sorted(lengths)
    rep = ordered[min(len(ordered) - 1, int(_BODY_QUANTILE * (len(ordered) - 1)))]
    return rep * _BODY_RATIO


def _line_start(ln: Line) -> float:
    """입력: 유효 좌표 행. 출력: 시작 변. 목적: 가로쓰기의 왼쪽 변도 비교한다."""
    return float(ln.bbox[1] if _is_vertical(ln) else ln.bbox[0])


def _page_fold(axes: list[float]) -> Optional[tuple[float, float, int, int]]:
    """한 쪽의 판심 — (왼쪽 끝, 오른쪽 끝, 왼쪽 열 수, 오른쪽 열 수). 없으면 None.

    입력: 본문 열의 중심 좌표(정렬 전). 출력: 판심 띠와 좌우 열 수.
    목적: 접은 자리를 «열 사이가 유난히 벌어진 곳»으로 찾는다 — 반엽 하나씩 찍은 스캔은
          벌어진 데가 없으므로 None이 되고, 부르는 쪽은 그대로 넘어간다.
    """
    # 같은 축의 여러 OCR 행은 물리적으로 한 열이므로 간격과 열 수에 한 번만 넣는다.
    xs = sorted(set(axes))
    if len(xs) < _MIN_COLUMNS:
        return None
    gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    med = statistics.median(gaps)
    if med <= 0:
        return None
    # 후보가 여럿이면 어느 틈이 접힌 자리인지 좌표만으로 확정할 수 없다.
    candidates = [i for i, gap in enumerate(gaps) if gap >= med * _FOLD_GAP]
    if len(candidates) != 1:
        return None
    widest = candidates[0]
    return xs[widest], xs[widest + 1], widest + 1, len(xs) - widest - 1


def analyze(lines: list[Line]) -> dict:
    """판식을 읽고 행마다 라벨을 붙인다.

    입력: 행 목록(bbox가 있는 것과 없는 것이 섞여 있어도 된다).
    출력: {
      "labels": {(쪽, 행 번호): "body"|"pansim"|"margin"},
      "fold": {"center": 배열 축의 좌표, "pages": 판심을 찾은 쪽 수} 또는 None,
      "columns": {(왼쪽 열, 오른쪽 열): 쪽 수}  — 목록의 «10행»과 견줄 값,
      "counts": {"body": n, "pansim": n, "margin": n, "unknown": n},
      "samples": {"pansim": [원문 …], "margin": [원문 …]},
    }
    목적: 규약을 찾을 때 종이의 것(판심제·장차·두주)을 빼고, 무엇을 뺐는지 사람에게 보인다.

    좌표가 없는 행은 "unknown"이고, 부르는 쪽은 그것을 본문처럼 다룬다 —
    텍스트로 가져온 문헌에서 이 기능이 아무것도 망치지 않아야 한다.
    """
    labels: dict[tuple[int, int], str] = {}
    by_page: dict[int, list[Line]] = {}
    for ln in lines:
        if not ln.text.strip():
            continue
        if line_length(ln) is None:
            labels[(ln.page, ln.line_index)] = "unknown"
            continue
        by_page.setdefault(ln.page, []).append(ln)
    if not by_page:
        # 좌표가 하나도 없다 — 텍스트로 가져온 문헌. 판식을 논하지 않고 전부 본문으로 둔다.
        return {
            "labels": labels,
            "regular": False,
            "fold": None,
            "columns": {},
            "haengja": None,
            "counts": {"body": 0, "pansim": 0, "margin": 0, "unknown": len(labels)},
            "samples": {"pansim": [], "margin": []},
        }

    # ① 본문 열의 길이 문턱은 **책 전체**에서 한 번 잰다 — 쪽마다 재면 본문이 두세 열뿐인
    #    마지막 쪽에서 그 열들이 스스로 기준이 되어 아무것도 못 거른다.
    cut = _body_cut([line_length(ln) for page in by_page.values() for ln in page])

    # ② 쪽마다 판심을 찾고, 책 전체의 «접은 자리»를 그 중앙값으로 정한다.
    #    쪽 하나가 이상해도 책의 판단은 흔들리지 않는다.
    folds: list[float] = []
    columns: dict[tuple[int, int], int] = {}
    page_fold: dict[int, tuple[float, float]] = {}
    for page, page_lines in by_page.items():
        body_axes = [line_axis(ln) for ln in page_lines if (line_length(ln) or 0) >= cut]
        body_axes = [a for a in body_axes if a is not None]
        found = _page_fold(body_axes)
        if found is None:
            continue
        lo, hi, left, right = found
        folds.append((lo + hi) / 2)
        columns[(left, right)] = columns.get((left, right), 0) + 1
        page_fold[page] = (lo, hi)

    # ③ 이 책의 판식이 «일정한가»를 먼저 정한다. 여기를 통과하지 못하면 아무 라벨도 붙이지
    #    않고 전부 본문으로 둔다 — 자신 없을 때 잠자코 있는 쪽이, 본문을 두주로 잘못 빼는
    #    것보다 훨씬 낫다.
    #
    #    왜 문이 필요한가(2026-09-08 실측): 길이만으로 가르면 天津談草의 별행 표제
    #    「天津奉使縁起」와 雲養集의 「雲養集巻之一」이 두주와 같은 크기라 함께 빠졌다. 그 두 책은
    #    반엽 하나씩 찍은 스캔이라 접은 자리가 없는데도 판심이 몇 쪽에서 우연히 잡혔고,
    #    좌우 열 수가 (3,5)·(7,8)처럼 쪽마다 달랐다. 浩齋는 61/64쪽에서 잡히고 (10,10)이
    #    35쪽으로 으뜸이다 — 목록(KORMARC 300▼b)의 「10行20字」와 같다.
    regular = False
    fold_center = None
    dominant: Optional[tuple[int, int]] = None
    if folds and len(folds) >= max(3, len(by_page) * _FOLD_PAGES):
        center = statistics.median(folds)
        # 좌표 최댓값은 너비가 아니다. 원점 이동이나 한 큰 쪽이 허용 오차를 늘리면 안 된다.
        page_width = statistics.median(
            [
                max(ln.bbox[2] if _is_vertical(ln) else ln.bbox[3] for ln in page)
                - min(ln.bbox[0] if _is_vertical(ln) else ln.bbox[1] for ln in page)
                for page in by_page.values()
            ]
        )
        spread = statistics.median(abs(f - center) for f in folds)
        agree = not page_width or spread / page_width <= _FOLD_AGREE
        dominant, n_dominant = max(columns.items(), key=lambda kv: kv[1])
        steady = n_dominant >= len(folds) * _COLUMNS_DOMINANT
        if agree and steady:
            regular = True
            fold_center = center

    # ④ 행마다 라벨 — 자리가 먼저고 크기가 다음이다.
    #    판심 띠 안이면 본문 열 크기여도 판심(판심제·장차).
    #    밖이면 «짧고, 본문 열처럼 윗변에서 시작하지도 않는» 것만 두주로 본다 — 별행 표제는
    #    짧아도 본문과 같은 윗변에서 시작한다(浩齋 실측: 판심제·표제 94행이 윗변 일치,
    #    두주 117행이 아래에서 시작).
    # 두주가 과반이어도 두주 자체가 본문 기준이 되지 않도록 긴 열만 참조한다.
    reference = [ln for page in by_page.values() for ln in page if line_length(ln) >= cut]
    top_med = statistics.median([_line_start(ln) for ln in reference])
    height_med = statistics.median([line_length(ln) for ln in reference])
    samples: dict[str, list[str]] = {"pansim": [], "margin": []}
    counts = {"body": 0, "pansim": 0, "margin": 0, "unknown": len(labels)}
    for page, page_lines in by_page.items():
        band = page_fold.get(page) if regular else None
        for ln in page_lines:
            axis = line_axis(ln)
            length = line_length(ln) or 0
            top_off = abs(_line_start(ln) - top_med)
            if band is not None and axis is not None and band[0] < axis < band[1]:
                label = "pansim"
            elif (
                regular
                and length < height_med * _MARGIN_RATIO
                and top_off > height_med * _TOP_ALIGN
            ):
                label = "margin"
            else:
                label = "body"
            # 판식을 유보하면 본문으로 세기만 하고 기하 라벨은 붙이지 않는다.
            if regular:
                labels[(ln.page, ln.line_index)] = label
            counts[label] += 1
            if label != "body" and len(samples[label]) < 8:
                samples[label].append(ln.text.strip()[:20])
    return {
        "labels": labels,
        "regular": regular,
        "fold": (
            None
            if fold_center is None
            else {"center": round(fold_center, 1), "pages": len(page_fold)}
        ),
        "columns": columns if regular else {},
        "haengja": dominant if regular else None,
        "counts": counts,
        "samples": samples,
    }


def body_lines(lines: list[Line], result: Optional[dict] = None) -> list[Line]:
    """규약을 찾을 때 볼 행만 남긴다 — 판심제·장차·두주를 뺀다.

    입력: 행 목록, (있으면) analyze() 결과. 출력: 본문 행 목록.
    목적: 종이의 규약이 글의 규약으로 세어지지 않게 한다. 좌표를 모르는 행은 남긴다.
    """
    result = analyze(lines) if result is None else result
    labels = result["labels"]
    return [
        ln for ln in lines if labels.get((ln.page, ln.line_index), "unknown") in ("body", "unknown")
    ]


def describe(result: dict) -> str:
    """사람에게 아주 짧게. 입력: analyze() 결과. 출력: 「판심 24행 · 두주 83행 · 반엽 10행」.

    화면은 좁다 — 여기서는 수만 말하고, 어떤 행을 뺐는지는 samples가 들고 있으니 툴팁이 보인다.
    """
    c = result["counts"]
    if not c["pansim"] and not c["margin"]:
        return ""
    parts = []
    if c["pansim"]:
        parts.append(f"판심 {c['pansim']}행")
    if c["margin"]:
        parts.append(f"두주 {c['margin']}행")
    if result.get("haengja"):
        parts.append(f"반엽 {result['haengja'][0]}행")
    return " · ".join(parts)


# ── 목록과 맞대기 (D-120 ③) ───────────────────────────────────────────────────
#
# 좌표에서 «반엽 몇 행»을 잰 것은 어디까지나 추정이다 — 반엽 하나씩 찍은 스캔에 빈 열이
# 되풀이되면 접은 자리처럼 보일 수 있다(Codex 지적 2026-09-08). 목록(KORMARC 300▼b)의
# 행자수가 있으면 그 추정을 확인하거나 반증할 수 있다. 둘은 서로 독립이라 검산이 된다.
_HAENGJA_RE = re.compile(r"(\d+)\s*[行행]")


def catalog_columns(printing_info: Optional[dict]) -> Optional[int]:
    """목록이 적어 둔 «반엽 몇 행». 없으면 None.

    입력: 서지의 printing_info(없어도 된다). 출력: 반엽의 행 수 또는 None.
    목적: 좌표에서 잰 값과 견줄 기준을 얻는다.
          갈라 담은 haengja를 먼저 보고, 없으면 원문에서 찾는다.
    """
    if not isinstance(printing_info, dict):
        return None
    for key in ("haengja", "summary"):
        text = printing_info.get(key)
        if not text:
            continue
        m = _HAENGJA_RE.search(str(text))
        if m:
            n = int(m.group(1))
            if 1 <= n <= 40:  # 반엽 40행을 넘는 판식은 없다 — 잘못 읽은 숫자를 거른다
                return n
    return None


def compare_with_catalog(result: dict, printing_info: Optional[dict]) -> Optional[dict]:
    """좌표에서 잰 행 수와 목록의 행자수를 맞댄다. 견줄 것이 없으면 None.

    입력: analyze() 결과, 서지의 printing_info.
    출력: {"catalog": n, "measured": [왼쪽, 오른쪽], "agree": bool, "summary": 한국어 한 줄}.
    목적: 판식 추정을 사람이 확인할 수 있게 한다. 어긋나도 고치지 않는다 — 어느 쪽이 틀렸는지는
          사람이 판단할 일이고, 어긋났다는 사실 자체가 «이 쪽 OCR을 다시 보라»는 신호다.
    """
    catalog = catalog_columns(printing_info)
    measured = result.get("haengja")
    if catalog is None and not measured:
        return None
    if catalog is None:
        return {
            "catalog": None,
            "measured": list(measured),
            "agree": None,
            "summary": (f"잰 값 {measured[0]}행 (목록에 행자수 없음)"),
        }
    if not measured:
        return {
            "catalog": catalog,
            "measured": None,
            "agree": None,
            "summary": (f"목록 {catalog}행 (좌표로는 판식을 읽지 못함)"),
        }
    agree = catalog in measured
    if agree:
        summary = f"목록과 일치({catalog}행)"
    else:
        summary = f"목록 {catalog}행 ≠ 잰 값 {measured[0]}·{measured[1]}행"
    return {"catalog": catalog, "measured": list(measured), "agree": agree, "summary": summary}
