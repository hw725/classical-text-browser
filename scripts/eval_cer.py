#!/usr/bin/env python3
"""CER 평가 — L4 확정본을 정답으로 L2 엔진 결과와 LLM 교정 초안의 글자 오류율을 잰다 (D-084).

사용법:
    uv run python scripts/eval_cer.py --library ~/서고 --doc doc001 --part vol1
    uv run python scripts/eval_cer.py --library ~/서고 --doc doc001 --part vol1 --pages 1-10,15
    uv run python scripts/eval_cer.py --library ~/서고 --doc doc001 --part vol1 --json out.json

무엇을 비교하는가:
    같은 쪽에 대해 (a) 엔진 OCR(L2) (b) LLM 교정 초안을 자동 수용 규칙으로 적용한 텍스트를
    각각 사람이 확정한 L4와 대조한다. (b)가 (a)보다 낮으면 교정 패스가 도움이 된 것이다.
    이체자는 strict 층(기본 사전 + 이 문헌의 승인 쌍)만 일치로 센다.

정답이 L4이므로 사람이 교정을 끝낸 쪽에서만 잴 수 있다. 회귀 검사기이지 벤치마크가 아니다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _parse_pages(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    pages: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(chunk))
    return sorted(set(pages))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--library", required=True, type=Path, help="서고 루트")
    ap.add_argument("--doc", required=True, help="문헌 ID")
    ap.add_argument("--part", required=True, help="권 ID (part_id)")
    ap.add_argument("--pages", help="쪽 범위 (예: 1-10,15). 비우면 L2가 있는 모든 쪽")
    ap.add_argument("--json", type=Path, help="보고서를 JSON으로도 저장")
    args = ap.parse_args(argv)

    from core.alignment import TieredVariantDicts, VariantCharDict, load_document_approvals
    from ocr.eval_cer import evaluate_part, format_table

    doc_path = args.library / "documents" / args.doc
    if not doc_path.exists():
        print(f"문헌을 찾을 수 없습니다: {doc_path}", file=sys.stderr)
        return 2

    bundle = TieredVariantDicts([VariantCharDict(), load_document_approvals(doc_path)])
    report = evaluate_part(doc_path, args.doc, args.part, _parse_pages(args.pages), bundle)
    print(format_table(report))
    if args.json:
        args.json.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nJSON 저장: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
