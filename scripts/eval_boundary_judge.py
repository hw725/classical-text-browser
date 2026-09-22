# -*- coding: utf-8 -*-
"""경계 판정을 재는 자 — «글이 시작하는 행»과 «목차 항목이 본문 어느 행인가» 둘.

두 측정기를 한 파일에 둔 까닭: 같은 책 설정(`BOOKS`)·같은 본문 적재(`load_lines`)·같은 유사도를
쓰는데 파일이 둘이라 한쪽이 다른 쪽을 import하고 있었다. 하나로 두면 책을 더할 때 한 곳만 고친다.

    starts — 규칙(D-116)과 판정 모델을 같은 자로 견준다(«이 행에서 새 글이 시작하는가»).
    toc    — 목차 대조를 «고르기»로 바꿔 지금의 정렬과 견준다.

정답 자리 맞춤(starts):
    CSV의 «행»은 4차 확정본 기준이 아니다(그 전 판독이나 앵커 규약을 따른다). 그대로 쓰면 모델이
    맞혀도 «놓침»으로 세어 측정이 틀어진다. CSV가 적어 둔 글과 같은 행을 ±3행 안에서 찾아 옮기고,
    못 찾은 행은 정답에서 뺀다 — 다만 그냥 빼면 그 자리를 찾아낸 방법이 벌을 받으므로, 뺀 행
    둘레를 «모르는 자리»로 묶어 맞음에도 헛것에도 세지 않는다.

정답이 없는 측정(toc):
    목차 대조에는 독립 정답표가 없다 — 앵커 CSV(개별 작품)와 총목(集 이름)이 겹치는 항목이
    2개뿐이다(2026-09-21 확인). 그래서 점수 대신 **정답 없이 검증되는 성질**을 잰다:
    ① 본문에 없는 항목에 «없음»을 고르는가(지어내기 저항) ② 고른 행에서 제목이 실제로 시작하는가.

쓰는 법:
    uv run python scripts/eval_boundary_judge.py starts --book cheonjin
    uv run python scripts/eval_boundary_judge.py starts --book unyang01 --run --save nouls.json
    uv run python scripts/eval_boundary_judge.py starts --book unyang01 --score nouls.json
    uv run python scripts/eval_boundary_judge.py toc --run --save toc.json
    uv run python scripts/eval_boundary_judge.py toc --score toc.json

본문과 정답 CSV는 **읽기만** 한다. `--run`이 없으면 한 건도 보내지 않는다(전역 규칙 11).
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
from core.toc import (  # noqa: E402
    align_toc_to_body,
    detect_toc_pages,
    extract_toc_entries_rule,
    match_toc_entries_jev,
    toc_candidates,
)

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

ABSENT = 0.5  # (toc) 본문 최고 유사도가 이보다 낮으면 «본문에 없는 항목»으로 본다
PRESENT = 0.85  # (toc) 이보다 높으면 «본문에 있는 항목»


# ── 공통 ────────────────────────────────────────────────────────────────────
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
    """CSV가 적어 둔 글이 이 행에 얼마나 들어 있는가. 출력: 0~1(겹친 글자 ÷ 적어 둔 글자).

    글자 다중집합으로 센다 — OCR 판독차(旣/既·瓷/資)가 한두 자 있어도 같은 행임을 알아야 하고,
    부분 일치(제목이 행의 앞머리)도 1.0이 되어야 한다.
    """
    a, b = _fold(mark), _fold(line)
    if not a or not b:
        return 0.0
    ca, cb = collections.Counter(a), collections.Counter(b)
    return sum((ca & cb).values()) / len(a)


# ── starts: 규칙 대 판정 모델 ───────────────────────────────────────────────
def load_truth(spec: dict, lines: list[Line], min_sim: float = 0.7) -> tuple[set, set, dict]:
    """정답 자리·«모르는 자리»·통계. 출력: (확인된 정답, 모르는 자리, 통계).

    자리를 확인하지 못한 정답 행(제목이 본문에 없거나 OCR이 너무 달라 못 찾은 것)도 그 근처에서
    글이 시작하는 것은 사실이다. 그냥 정답에서 빼면 **그 자리를 찾아낸 방법이 헛것을 냈다고
    벌을 받으므로**, 둘레 ±3행을 «모르는 자리»로 묶어 맞음에도 헛것에도 세지 않는다.
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
            if mark.startswith("["):  # 편집자가 붙인 이름 — 본문에 없다
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


def starts_report(lines: list[Line], nouls: list, truth: set, gray: set = frozenset()) -> None:
    """규칙·모델·둘의 조합을 한 표에. 조합이 요점이다 — «코드가 후보를 만들고 모델은 고르기만»."""
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


def cmd_starts(args) -> int:
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
        starts_report(lines, json.loads(args.score.read_text(encoding="utf-8"))["nouls"],
                      truth, gray)
        return 0

    size = jev_structure_size(lines, args.max_chars, args.questions)
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
    starts_report(lines, meta["nouls"], truth, gray)
    return 0


# ── toc: 목차 대조를 «고르기»로 ─────────────────────────────────────────────
def prepare(book: str = "unyang01"):
    """목차 항목·본문 행·지금 정렬의 결과. 출력: (entries, body, toc_pages, matches, unmatched)."""
    spec = BOOKS[book]
    full = load_lines(spec["text_dir"], 2, spec["last"])
    pages: dict[int, list[str]] = {}
    for ln in full:
        pages.setdefault(ln.page, []).append(ln.text)
    toc_pages = detect_toc_pages(pages)
    entries = extract_toc_entries_rule(pages, toc_pages)
    body = [ln for ln in full if ln.page >= spec["first"]]
    matches, unmatched = align_toc_to_body(entries, body)
    return entries, body, toc_pages, matches, unmatched


def bucket(entries, body) -> dict:
    """항목을 «본문에 있다/없다/모른다»로 나눈다 — 최고 유사도만으로."""
    out = {"present": [], "absent": [], "unsure": []}
    for i, e in enumerate(entries):
        cands = toc_candidates(getattr(e, "title", ""), body, 1)
        top = cands[0][1] if cands else 0.0
        out["present" if top >= PRESENT else "absent" if top < ABSENT else "unsure"].append(i)
    return out


def toc_report(entries, body, matches, buckets, result) -> None:
    """지금 정렬과 고르기를 견준다. 점수가 아니라 «어디서 갈리는가»를 보인다."""
    picked = {p["entry"]: p for p in result["picks"]}
    none = {n["entry"] for n in result["none"]}
    aligned = {m.entry_index: m for m in matches}

    print(f"\n목차 항목 {len(entries)} · 지금 정렬이 붙인 것 {len(aligned)}")
    for name, label in (("absent", "본문에 없는 항목"), ("present", "본문에 있는 항목"),
                        ("unsure", "애매한 항목")):
        idx = buckets[name]
        if not idx:
            continue
        print(
            f"  {label} {len(idx):>3}개 — 고르기: «없음» {sum(1 for i in idx if i in none)}"
            f" · 행 고름 {sum(1 for i in idx if i in picked)}"
            f" · (지금 정렬이 붙인 것 {sum(1 for i in idx if i in aligned)})"
        )
    absent = buckets["absent"]
    if absent:
        wrong = [picked[i] for i in absent if i in picked]
        print(f"\n지어내기 저항: 본문에 없는 {len(absent)}개 중 «없음» "
              f"{len(absent) - len(wrong)}개 ({(len(absent) - len(wrong)) / len(absent):.0%})")
        for p in wrong[:8]:
            print(f"    골라 버린 것: 「{p['title'][:14]}」 → {p['text'][:20]} (확률 {p['prob']})")
    print("\n본문에 있는 항목에서 고른 행 — 제목이 그 행에서 시작하는가:")
    for i in buckets["present"]:
        if i not in picked:
            mark = "정렬도 못 붙임" if i not in aligned else "정렬은 붙임"
            print(f"    «없음»으로 답함: 「{getattr(entries[i], 'title', '')[:14]}」 ({mark})")
            continue
        p = picked[i]
        same = "정렬과 같음" if (i in aligned and aligned[i].line_index == p["line_index"]
                              and aligned[i].page == p["page"]) else "정렬과 다름"
        print(f"    「{p['title'][:14]}」 → p{p['page']}-L{p['line_index']} {p['text'][:18]}"
              f" · {'일치' if p['sim'] >= PRESENT else '다른 행'} · {same} · 확률 {p['prob']}")


def cmd_toc(args) -> int:
    entries, body, toc_pages, matches, _unmatched = prepare(args.book)
    buckets = bucket(entries, body)
    print(
        f"[{args.book}] 목차 쪽 {toc_pages} · 항목 {len(entries)} · 본문 행 {len(body)}\n"
        f"본문에 있음 {len(buckets['present'])} · 없음 {len(buckets['absent'])} · "
        f"애매 {len(buckets['unsure'])} · 지금 정렬이 붙인 것 {len(matches)}"
    )
    if args.score:
        toc_report(entries, body, matches, buckets,
                   json.loads(args.score.read_text(encoding="utf-8")))
        return 0

    asked = sum(1 for e in entries if len(str(getattr(e, "title", ""))) >= 2)
    print(f"호출 {asked}회 · 항목마다 후보 {args.top_k}개 · 예상 $0.001~$0.003")
    if not args.run:
        print("보내지 않았습니다. 실제로 부르려면 --run.")
        return 0

    from llm.jev import JevClient  # noqa: PLC0415

    client = JevClient(max_calls=args.max_calls)
    if not client.has_key:
        print("TYPESAFE_API_KEY를 찾지 못했습니다.")
        return 1
    client.gate(asked)
    result = match_toc_entries_jev(entries, body, client, args.top_k)
    print(f"\n{client.usage()}")
    if result["failed"]:
        print(f"실패 {len(result['failed'])}건:", result["failed"][:3])
    if args.save:
        args.save.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        print("결과를 남겼습니다:", args.save)
    toc_report(entries, body, matches, buckets, result)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="경계 판정을 잰다 — starts(글 시작 행)·toc(목차 대조)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("starts", help="규칙과 판정 모델을 같은 자로 견준다")
    s.add_argument("--book", choices=sorted(BOOKS), default="cheonjin")
    s.add_argument("--min-sim", type=float, default=0.7, help="정답 자리 맞춤 문턱")
    s.add_argument("--max-chars", type=int, default=3000, help="한 묶음(state)의 글자 수")
    s.add_argument("--questions", type=int, default=100, help="한 번에 보낼 질문 수")
    s.add_argument("--max-calls", type=int, default=40, help="호출 상한 — 넘으면 거부한다")
    s.add_argument("--threshold", type=float, default=0.5)
    s.add_argument("--run", action="store_true", help="실제로 부른다")
    s.add_argument("--save", type=pathlib.Path, help="확률을 JSON으로 남긴다")
    s.add_argument("--score", type=pathlib.Path, help="남긴 JSON으로 다시 잰다(호출 없음)")
    s.set_defaults(func=cmd_starts)

    t = sub.add_parser("toc", help="목차 대조를 고르기로 바꿔 잰다")
    t.add_argument("--book", choices=sorted(BOOKS), default="unyang01")
    t.add_argument("--top-k", type=int, default=6, help="항목마다 보여 줄 후보 행 수")
    t.add_argument("--max-calls", type=int, default=140)
    t.add_argument("--run", action="store_true")
    t.add_argument("--save", type=pathlib.Path)
    t.add_argument("--score", type=pathlib.Path, help="남긴 결과로 다시 잰다(호출 없음)")
    t.set_defaults(func=cmd_toc)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
