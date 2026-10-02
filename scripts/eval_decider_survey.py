#!/usr/bin/env python3
"""판정 모델(Perplexity Decider)의 «무슨 글인가» 판정을 우리 책으로 잰다 (D-134).

사용법:
    # 1) 보내지 않고 쪽 수·어림 비용만 (기본)
    uv run python scripts/eval_decider_survey.py --library ~/서고 --doc doc001 --part vol1 --pages 1-30
    # 2) 실제로 보내고 확률을 저장
    uv run python scripts/eval_decider_survey.py ... --run --out decider.json
    # 3) 정답과 견주기 — 정답은 {"쪽": ["classical_print", "kunten"], ...} 꼴의 JSON
    uv run python scripts/eval_decider_survey.py --score decider.json --truth truth.json

왜 있는가:
    업체 문서에는 한문·고서 이미지에서의 정확도가 없다(기반 모델 Qwen3.8-27B라는 것뿐). 그래서
    자동 스캔의 기본 모델로 올리기 전에 **우리 책으로** 종류별 재현·정밀도를 재고, 종류를 «있다»로
    받을 문턱을 그 결과로 정한다(지금 값 0.5는 잰 값이 아니다 — page_survey.DECIDER_CONTENT_THRESHOLD).

실행 게이트(전역 규칙 11): `--run` 없이는 한 건도 보내지 않는다. `--max-pages`(기본 60)를 넘으면
보내기 전에 거부한다. 비용은 쪽당 약 2,400 입력 토큰 × $0.04/M(문서 단가 — 실측은 끝에 usage로 찍는다).
"""

from __future__ import annotations

import argparse
import json
import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from core.console import force_utf8_console  # noqa: E402

force_utf8_console()

EST_TOKENS_PER_PAGE = 2400


def _parse_pages(spec: str) -> list[int]:
    pages: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        elif chunk:
            pages.append(int(chunk))
    return pages


def _page_jpeg(library: Path, doc: str, part: str, page: int) -> bytes | None:
    """쪽 이미지(저장된 회전을 얹은 것)를 2000px 이하 JPEG로."""
    from ocr.image_utils import load_page_image_from_pdf

    img = load_page_image_from_pdf(str(library), doc, page, part_id=part)
    if img is None:
        return None
    img = img.convert("RGB")
    img.thumbnail((2000, 2000))
    out = BytesIO()
    img.save(out, format="JPEG", quality=88)
    return out.getvalue()


def run(args) -> int:
    from core.page_survey import DECIDER_STATE, decider_questions, parse_decider_answers
    from llm.decider import DECIDER_INPUT_USD_PER_M, DeciderClient

    pages = _parse_pages(args.pages)
    est = len(pages) * EST_TOKENS_PER_PAGE * DECIDER_INPUT_USD_PER_M / 1e6
    print(f"쪽 {len(pages)} · 호출 {len(pages)}회 · 어림 비용 ${est:.5f} (문서 단가, 실측 아님)")
    if not args.run:
        print("보내지 않았습니다 — 실제로 재려면 --run")
        return 0
    if len(pages) > args.max_pages:
        print(f"거부: {len(pages)}쪽이 상한 {args.max_pages}쪽을 넘습니다(--max-pages).")
        return 2
    library = Path(args.library).expanduser()
    client = DeciderClient(library_root=library, max_calls=len(pages) + 2)
    if not client.has_key:
        print("Perplexity 키가 없습니다 — 설정 → 판정 모델에서 넣으세요.")
        return 2
    rows = []
    for p in pages:
        img = _page_jpeg(library, args.doc, args.part, p)
        if img is None:
            rows.append({"page": p, "error": "이미지 없음"})
            continue
        try:
            ans = client.ask(
                DECIDER_STATE,
                decider_questions(),
                images=[(img, "image/jpeg")],
                purpose="eval_decider",
            )
        except Exception as e:  # noqa: BLE001
            rows.append({"page": p, "error": f"{type(e).__name__} {getattr(e, 'status', '')}"})
            continue
        o, contents, probs = parse_decider_answers(ans)
        rows.append({"page": p, "orientation": o, "contents": contents, "probs": probs})
        print(f"{p}쪽: {o} {contents}")
    out = {"doc": args.doc, "part": args.part, "rows": rows, "usage": client.usage()}
    if args.out:
        Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"저장: {args.out}")
    print(f"실측 사용량: {client.usage()}")
    return 0


def score(args) -> int:
    """정답과 견준다 — 종류마다 문턱별 정밀도·재현율, 그리고 F1이 가장 높은 문턱."""
    from core.page_survey import DECIDER_CONTENT_QUESTIONS

    data = json.loads(Path(args.score).read_text(encoding="utf-8"))
    truth = {
        int(k): set(v) for k, v in json.loads(Path(args.truth).read_text(encoding="utf-8")).items()
    }
    rows = [r for r in data["rows"] if "probs" in r and r["page"] in truth]
    print(f"정답과 겹치는 쪽 {len(rows)}개 — 표본이 작으면 문턱은 참고값일 뿐이다")
    for kind in DECIDER_CONTENT_QUESTIONS:
        best = None
        line = []
        for t in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
            tp = fp = fn = 0
            for r in rows:
                pred = r["probs"]["contents"].get(kind, 0.0) >= t
                real = kind in truth[r["page"]]
                tp += pred and real
                fp += pred and not real
                fn += (not pred) and real
            prec = tp / (tp + fp) if tp + fp else None
            rec = tp / (tp + fn) if tp + fn else None
            f1 = 2 * prec * rec / (prec + rec) if prec and rec else 0.0
            line.append(
                f"{t}: P={prec if prec is None else round(prec, 2)} R={rec if rec is None else round(rec, 2)}"
            )
            if tp + fn and (best is None or f1 > best[1]):
                best = (t, f1)
        positives = sum(1 for r in rows if kind in truth[r["page"]])
        print(
            f"- {kind} (정답 {positives}쪽): "
            + " · ".join(line)
            + (f" → 문턱 {best[0]}" if best else " → 정답에 없음")
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--library")
    ap.add_argument("--doc")
    ap.add_argument("--part")
    ap.add_argument("--pages")
    ap.add_argument("--run", action="store_true", help="실제로 보낸다(없으면 어림만)")
    ap.add_argument("--max-pages", type=int, default=60)
    ap.add_argument("--out")
    ap.add_argument("--score", help="--run --out으로 저장한 JSON")
    ap.add_argument("--truth", help="정답 JSON {쪽: [종류…]}")
    args = ap.parse_args()
    if args.score:
        if not args.truth:
            ap.error("--score에는 --truth가 필요합니다")
        return score(args)
    if not (args.library and args.doc and args.part and args.pages):
        ap.error("--library --doc --part --pages가 필요합니다")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
