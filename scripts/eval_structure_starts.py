# -*- coding: utf-8 -*-
"""«글이 시작하는 행»을 누가 더 잘 고르는가 — 규칙(D-116)과 Jev 판정(D-125 대안)을 같은 자로 잰다.

두 책을 안다(둘 다 운양 DB의 4차 확정본을 읽기만 한다).

    천진담초 — 일기류. 정답 `cheonjin_sessions.csv`(회차 37). 날짜 표지가 또렷해 **규칙이 잘 듣는**
        책이다. 여기서 재는 것은 «모델이 규칙만큼 하는가»다.
    운양집   — 문집. 정답 `article_anchors_munjip.csv`(자동 앵커 = silver). 표제가 제각각이라
        **규칙이 듣지 않는** 책이고, D-125(구조 통째로 묻기)가 애초에 겨냥한 자리다.

정답 자리 맞춤:
    두 CSV의 «행»은 4차 확정본 기준이 아니다(그 전 판독이나 앵커 규약을 따른다). 그대로 쓰면
    모델이 맞혀도 «놓침»으로 세어 측정이 틀어진다. 그래서 CSV가 적어 둔 글(원표기·제목)과 같은
    행을 ±3행 안에서 찾아 그쪽으로 옮기고, 못 찾은 행은 **정답에서 뺀다** — 자리를 확인할 수
    없는 정답으로 정밀도를 말할 수는 없다. 뺀 수는 늘 함께 찍는다.

쓰는 법:
    uv run python scripts/eval_structure_starts.py --book cheonjin --dry-run
    uv run python scripts/eval_structure_starts.py --book unyang01 --run --save nouls.json
    uv run python scripts/eval_structure_starts.py --book unyang01 --score nouls.json
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.segmentation import Line, normalize_rules, propose_boundaries  # noqa: E402
from core.structure_llm import ask_structure_jev, jev_structure_size  # noqa: E402

UNYANG = pathlib.Path(r"C:\Users\junto\Downloads\운양")
_PAGE = re.compile(r"p(\d+)\.")

# 책마다 «본문은 어디에, 정답은 어디에, 어떤 열이 그 자리의 글인가».
BOOKS: dict[str, dict] = {
    "cheonjin": {
        "text_dir": UNYANG / "ocr/cheonjindamcho/천진담초_규장각",
        "truth": UNYANG / "db/extracts/cheonjin_sessions.csv",
        "mark_col": "원표기",
        "book_col": None,
        "book": None,
        "first": 0,
        "last": 0,
    },
    # 운양집 1책 — 확정본이 있는 쪽은 2~87이고 목차(총목)는 9~13쪽이다. 목차 쪽은 본문이 아니라
    # 제목만 늘어선 쪽이라 규칙 길도 세지 않는다(D-116) — 그래서 본문 14쪽부터 잰다.
    "unyang01": {
        "text_dir": UNYANG / "ocr/unyangjip/운양집_01",
        "truth": UNYANG / "db/extracts/article_anchors_munjip.csv",
        "mark_col": "제목",
        "book_col": "책",
        "book": "운양집_01",
        "first": 14,
        "last": 87,
    },
}


def load_lines(text_dir: pathlib.Path, first: int = 0, last: int = 0) -> list[Line]:
    """확정본(사람이 고친 4차 판독)을 Line 목록으로. 한 파일이 한 쪽, 한 줄이 한 행(0기준)."""
    out: list[Line] = []
    for path in sorted(text_dir.glob("p*.corrected.md")):
        m = _PAGE.search(path.name)
        if not m:
            continue
        page = int(m.group(1))
        if (first and page < first) or (last and page > last):
            continue
        for i, text in enumerate(path.read_text(encoding="utf-8").splitlines()):
            out.append(Line(page=page, line_index=i, text=text.strip()))
    return out


def _fold(s: str) -> str:
    return re.sub(r"[\s\[\]〔〕（）()○●◯、。,.·]", "", str(s or ""))


def similarity(mark: str, line: str) -> float:
    """CSV가 적어 둔 글이 이 행에 얼마나 들어 있는가. 출력: 0~1(겹친 글자 수 ÷ 적어 둔 글자 수).

    글자 다중집합으로 센다 — OCR 판독차(旣/既·瓷/資)가 한두 자 있어도 같은 행임을 알아야 하고,
    부분 일치(제목이 행의 앞머리)도 1.0이 되어야 한다.
    """
    a, b = _fold(mark), _fold(line)
    if not a or not b:
        return 0.0
    ca, cb = collections.Counter(a), collections.Counter(b)
    return sum((ca & cb).values()) / len(a)


def load_truth(
    spec: dict, lines: list[Line], min_sim: float = 0.7
) -> tuple[set, set, dict]:
    """정답 자리·«모르는 자리»·통계. 입력: 책 설정, 본문, 자리 맞춤 문턱.

    출력: (확인된 정답 {(쪽, 행)}, 모르는 자리 {(쪽, 행)}, 통계).

    **왜 «모르는 자리»가 따로 있는가:** 자리를 확인하지 못한 정답 행(제목이 본문에 없거나 —
    «[擊磬集序]»처럼 편집자가 붙인 이름 — OCR이 너무 달라 못 찾은 것)도 그 근처 어딘가에서
    글이 시작하는 것은 사실이다. 그것을 그냥 정답에서 빼 버리면, **그 자리를 찾아낸 방법이
    헛것을 냈다고 벌을 받는다.** 그래서 그 둘레 ±3행을 «모르는 자리»로 묶어 맞음에도 헛것에도
    세지 않고, 몇 개가 거기 떨어졌는지만 따로 센다.
    """
    by = {(ln.page, ln.line_index): ln.text for ln in lines}
    truth: set[tuple[int, int]] = set()
    gray: set[tuple[int, int]] = set()
    stats = {"rows": 0, "snapped": 0, "dropped": 0, "bracketed": 0}
    first, last = spec["first"], spec["last"]
    with spec["truth"].open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if spec["book_col"] and row.get(spec["book_col"]) != spec["book"]:
                continue
            try:
                page, line = int(row["시작쪽"]), int(row["시작행"])
            except (KeyError, TypeError, ValueError):
                continue
            if (first and page < first) or (last and page > last):
                continue
            stats["rows"] += 1
            mark = str(row.get(spec["mark_col"]) or "")
            if mark.startswith("["):
                stats["bracketed"] += 1
                gray |= {(page, line + d) for d in range(-3, 4)}
                continue
            near = (0, 1, -1, 2, -2, 3, -3)
            best = max(
                ((similarity(mark, by.get((page, line + d), "")), d) for d in near),
                default=(0.0, 0),
            )
            if best[0] < min_sim:
                stats["dropped"] += 1
                gray |= {(page, line + d) for d in range(-3, 4)}
                continue
            if best[1]:
                stats["snapped"] += 1
            truth.add((page, line + best[1]))
    return truth, gray - truth, stats


def score(picked: set, truth: set, gray: set = frozenset()) -> dict:
    """맞음·헛것·놓침. «모르는 자리»에 떨어진 것은 헛것으로 세지 않고 ignored로 따로 센다."""
    ignored = len(picked & gray)
    picked = picked - gray
    hit = len(picked & truth)
    false = len(picked - truth)
    miss = len(truth - picked)
    prec = hit / (hit + false) if hit + false else 0.0
    rec = hit / len(truth) if truth else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"picked": len(picked), "hit": hit, "false": false, "miss": miss,
            "ignored": ignored, "precision": round(prec, 3), "recall": round(rec, 3),
            "f1": round(f1, 3)}


def _row(name: str, picked: set, truth: set, gray: set) -> None:
    s = score(picked, truth, gray)
    print(
        f"{name:<26} {s['picked']:>5} {s['hit']:>5} {s['false']:>5} {s['miss']:>5} "
        f"{s['ignored']:>5} {s['precision']:>6.3f} {s['recall']:>6.3f} {s['f1']:>6.3f}"
    )


def report(lines: list[Line], nouls: list, truth: set, gray: set = frozenset()) -> None:
    """규칙·Jev·둘의 조합을 한 표에 놓는다. 조합이 이 측정의 요점이다 —
    «코드가 후보를 만들고 모델은 고르기만»(D-117)을 숫자로 확인하는 자리."""
    by_pos = {(int(p), int(ln)): float(v) for p, ln, v in nouls}
    r = propose_boundaries(lines, normalize_rules(None))
    accepted = {(p["page"], p["line_index"]) for p in r["proposals"] if p.get("accepted")}
    candidates = {(p["page"], p["line_index"]) for p in r["proposals"]}

    print(f"\n정답 {len(truth)}자리 · 답을 받은 행 {len(nouls)}개")
    head = f"{'':<26} {'고름':>5} {'맞음':>5} {'헛것':>5} {'놓침':>5} {'모름':>5}"
    print(f"{head} {'정밀':>6} {'재현':>6} {'F1':>6}")
    _row("규칙 채택", accepted, truth, gray)
    _row("규칙 후보 전부", candidates, truth, gray)
    for t in (0.5, 0.6, 0.7, 0.8, 0.9):
        _row(f"Jev ≥ {t}", {p for p, v in by_pos.items() if v >= t}, truth, gray)
    for t in (0.5, 0.6, 0.7, 0.8):
        _row(f"규칙 후보 ∩ Jev ≥ {t}",
             {p for p in candidates if by_pos.get(p, 0) >= t}, truth, gray)
    for t in (0.7, 0.8):
        _row(f"규칙 채택 ∪ Jev ≥ {t}",
             accepted | {p for p, v in by_pos.items() if v >= t}, truth, gray)

    text = {(ln.page, ln.line_index): ln.text for ln in lines}
    missed = sorted((by_pos.get(p, -1.0), p) for p in truth)[:6]
    show = [(p, round(v, 2), text.get(p, "")[:12]) for v, p in missed]
    print("\n놓친 자리(Jev 확률 낮은 순):", show)
    wrong = sorted(
        ((v, p) for p, v in by_pos.items() if p not in truth and p not in gray), reverse=True
    )[:6]
    print("헛것(확률 높은 순):", [(p, round(v, 2), text.get(p, "")[:12]) for v, p in wrong])


def main() -> int:
    ap = argparse.ArgumentParser(description="«글이 시작하는 행»을 규칙과 Jev로 재어 견준다")
    ap.add_argument("--book", choices=sorted(BOOKS), default="cheonjin")
    ap.add_argument("--min-sim", type=float, default=0.7, help="정답 자리 맞춤 문턱")
    ap.add_argument("--max-chars", type=int, default=3000, help="한 묶음(state)의 글자 수")
    ap.add_argument("--questions", type=int, default=100, help="한 번에 보낼 질문 수")
    ap.add_argument("--max-calls", type=int, default=40, help="호출 상한 — 넘으면 거부한다")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--run", action="store_true", help="실제로 부른다")
    ap.add_argument("--save", type=pathlib.Path, help="확률을 JSON으로 남긴다")
    ap.add_argument("--score", type=pathlib.Path, help="남긴 JSON으로 다시 잰다(호출 없음)")
    args = ap.parse_args()

    spec = BOOKS[args.book]
    lines = load_lines(spec["text_dir"], spec["first"], spec["last"])
    if not lines:
        print(f"본문을 찾지 못했습니다: {spec['text_dir']}")
        return 1
    truth, gray, tstats = load_truth(spec, lines, args.min_sim)
    print(
        f"[{args.book}] 정답 CSV {tstats['rows']}행 → 자리 {len(truth)}개 "
        f"(맞춘 것 {tstats['snapped']} · 자리 확인 못 해 뺀 것 {tstats['dropped']} · "
        f"대괄호 제목 {tstats['bracketed']}) · 모르는 자리 {len(gray)}행"
    )

    if args.score:
        report(lines, json.loads(args.score.read_text(encoding="utf-8"))["nouls"], truth, gray)
        return 0

    size = jev_structure_size(lines, args.max_chars, args.questions)
    # 토큰은 CJK 한 글자를 1~1.5토큰으로 어림한다(실측은 호출 뒤 usage로 바꾼다).
    lo = (size["chars"] + size["questions"] * 120) / 1_000_000 * 0.042
    print(
        f"쪽 {lines[0].page}~{lines[-1].page} · 행 {size['lines']} · 글자 {size['chars']:,} · "
        f"{size['calls']}회 호출 · 질문 {size['questions']}개 · ${lo:.4f}~${lo * 1.5:.4f}"
    )
    if not args.run:
        print("보내지 않았습니다. 실제로 부르려면 --run.")
        return 0

    from llm.jev import JevClient  # noqa: PLC0415 — 키가 없어도 여기까지는 돌아야 한다

    client = JevClient(max_calls=args.max_calls)
    if not client.has_key:
        print("TYPESAFE_API_KEY를 찾지 못했습니다(~/.claude/data/triage/.env 확인).")
        return 1
    client.gate(size["calls"])
    props, meta = ask_structure_jev(
        lines, client, max_chars=args.max_chars,
        questions_per_call=args.questions, threshold=args.threshold,
    )
    print(f"\n호출 {meta['calls']}회 · 질문 {meta['questions']}개 · {client.usage()}")
    if meta.get("error"):
        print("오류:", meta["error"])
    print(f"후보 {len(props)}개(문턱 {args.threshold})")
    if args.save:
        args.save.write_text(
            json.dumps({"book": args.book, "nouls": meta["nouls"], "usage": client.usage()},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        print("확률을 남겼습니다:", args.save)
    report(lines, meta["nouls"], truth, gray)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
