# -*- coding: utf-8 -*-
"""목차 항목을 본문 행에 붙이는 일을 «고르기»로 바꿔 잰다 (운양집 1책).

왜 이 측정이 보통 측정과 다른가:
    목차 대조에는 **독립 정답표가 없다.** 앵커 CSV(142자리)는 개별 작품이고 총목 102항목은
    集 이름이라, 둘이 겹치는 것이 2개뿐이다(2026-09-21 확인) — 층이 다르다. 그래서 점수를
    매기는 대신 **정답 없이 검증되는 성질** 하나를 잰다.

무엇을 재는가 — 지어내기 저항:
    총목 102항목 중 60항목은 그 글자가 본문에 아예 없다(목차 제목 ≠ 본문 표제). 그 항목들의
    정답은 «없음»이다. 후보를 닮지 않은 행으로 채워 놓고 모델이 «없음»을 고르는지 센다.
    나머지(본문에 있는 항목)에서는 지금의 정렬(`align_toc_to_body`)과 어디서 갈리는지 본다.

쓰는 법:
    uv run python scripts/eval_toc_match.py            # 보내지 않고 양과 값만
    uv run python scripts/eval_toc_match.py --run --save toc.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core.toc import (  # noqa: E402
    align_toc_to_body,
    detect_toc_pages,
    extract_toc_entries_rule,
    match_toc_entries_jev,
    toc_candidates,
)

sys.path.insert(0, str(ROOT / "scripts"))
from eval_structure_starts import BOOKS, load_lines  # noqa: E402

ABSENT = 0.5  # 본문 최고 유사도가 이보다 낮으면 «본문에 없는 항목»으로 본다
PRESENT = 0.85  # 이보다 높으면 «본문에 있는 항목»


def prepare(book: str = "unyang01"):
    """목차 항목·본문 행·지금 정렬의 결과를 한 번에. 출력: (entries, body, matches, unmatched)."""
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
    """항목을 «본문에 있다/없다/모른다»로 나눈다 — 최고 유사도만으로. 출력: {이름: [index]}."""
    out = {"present": [], "absent": [], "unsure": []}
    for i, e in enumerate(entries):
        cands = toc_candidates(getattr(e, "title", ""), body, 1)
        top = cands[0][1] if cands else 0.0
        out["present" if top >= PRESENT else "absent" if top < ABSENT else "unsure"].append(i)
    return out


def report(entries, body, matches, buckets, result) -> None:
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
        chose_none = sum(1 for i in idx if i in none)
        chose_line = sum(1 for i in idx if i in picked)
        by_align = sum(1 for i in idx if i in aligned)
        print(
            f"  {label} {len(idx):>3}개 — 고르기: «없음» {chose_none} · 행 고름 {chose_line}"
            f" · (지금 정렬이 붙인 것 {by_align})"
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
            e = entries[i]
            mark = "정렬도 못 붙임" if i not in aligned else "정렬은 붙임"
            print(f"    «없음»으로 답함: 「{getattr(e, 'title', '')[:14]}」 ({mark})")
            continue
        p = picked[i]
        ok = "일치" if p["sim"] >= PRESENT else "다른 행"
        same = "정렬과 같음" if (i in aligned and aligned[i].line_index == p["line_index"]
                              and aligned[i].page == p["page"]) else "정렬과 다름"
        print(f"    「{p['title'][:14]}」 → p{p['page']}-L{p['line_index']} {p['text'][:18]}"
              f" · {ok} · {same} · 확률 {p['prob']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="목차 대조를 고르기로 바꿔 잰다")
    ap.add_argument("--book", default="unyang01")
    ap.add_argument("--top-k", type=int, default=6, help="항목마다 보여 줄 후보 행 수")
    ap.add_argument("--max-calls", type=int, default=140)
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--save", type=pathlib.Path)
    ap.add_argument("--score", type=pathlib.Path, help="남긴 결과로 다시 잰다(호출 없음)")
    args = ap.parse_args()

    entries, body, toc_pages, matches, unmatched = prepare(args.book)
    buckets = bucket(entries, body)
    print(
        f"[{args.book}] 목차 쪽 {toc_pages} · 항목 {len(entries)} · 본문 행 {len(body)}\n"
        f"본문에 있음 {len(buckets['present'])} · 없음 {len(buckets['absent'])} · "
        f"애매 {len(buckets['unsure'])} · 지금 정렬이 붙인 것 {len(matches)}"
    )

    if args.score:
        report(entries, body, matches, buckets, json.loads(args.score.read_text(encoding="utf-8")))
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
    report(entries, body, matches, buckets, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
