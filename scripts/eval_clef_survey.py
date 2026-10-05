#!/usr/bin/env python3
"""판정 모델(Cloudflare clef)의 방향·종류 판정을 사람 라벨 없이 만든 작은 정답지로 잰다 (D-135).

사용법:
    # 1) 계획만 (기본) — 쪽을 그려 본문을 실제로 만들어 상한을 검사하고, 호출 수·어림 토큰을 찍는다.
    #    네트워크를 쓰지 않는다
    uv run python scripts/eval_clef_survey.py
    # 2) 실제로 보낸다 — 이미지 1장 = 호출 1회, 결과는 JSONL로 한 줄씩(중간에 죽어도 남는다)
    uv run python scripts/eval_clef_survey.py --run
    # 3) 끊긴 것 잇기 — 같은 --out에 이미 있는 항목은 건너뛴다
    uv run python scripts/eval_clef_survey.py --run --out <그 JSONL> --resume

정답지 (사람 라벨 없이):
    (a) 방향 — 바로 선 것을 확인한 쪽 8개를 코드가 90/180/270°로 돌린 사본을 만든다. 돌린 각을
        코드가 알므로 정답은 **구성으로** 정해진다. 쪽마다 원본(0°) 1장 + 돌린 사본
        2장(각은 돌아가며
        고르게) = 24장.
    (b) 종류 — 책 단위로 종류가 알려진 문헌의 쪽만 고른다(GOLD의 source·confidence). 같은 쪽의
        돌린 사본에도 같은 종류 정답을 쓴다(돌려도 글의 종류는 같다 — 돌린 쪽에서 종류 판정이
        흔들리는지도 함께 보인다). 정답이 애매한 종류는 «재지 않음»(None)으로 두고 세지 않는다.
    **한계**: 쪽 8개뿐이고 훈점·백지 양성 표본이 없다. 종류 정답의 «바로 섰다»·«이 쪽에 그 종류가
    보인다»는 Claude가 축소판을 보고 확인한 것이다(2026-10-04) — 사람이 확인한 것이 아니다.
    문턱(page_survey.DECIDER_CONTENT_THRESHOLD = 0.5)을 이것으로 정하지 않는다 — 표본이 너무 작다.

실행 게이트(전역 규칙 11): `--run` 없이는 한 건도 보내지 않는다. 계획 호출 수가 `--max-calls`
(기본 24)를 넘으면 보내기 전에 거부한다. clef는 입력 토큰만 청구($0.24/M), 무료 몫은 하루
10,000 neurons ≈ 458K 토큰(사용자 전달 문서 요약 2026-10-04 — 실측 아님). 이미지 한 장의 토큰 수는
문서에 없어 Decider 문서의 «메가픽셀당 약 1,000토큰»으로 어림한다(**가정**) —
실측은 끝에 usage로 찍는다.

서고는 `~/.classical-text-browser/config.json`의 첫 서고(`--library`로 덮는다). 정답 쪽 대부분은
서고의 휴지통(`.trash/documents/…`)에 있다 — 휴지통을 비우면 그 쪽은 «이미지 없음»으로 빠진다.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from core.console import force_utf8_console  # noqa: E402

force_utf8_console()

# 어림(가정): 메가픽셀당 1,000토큰(Decider 문서) + 질문 7개 ≈ 400토큰.
# clef 문서에는 이미지 토큰 수가 없다
EST_TOKENS_PER_MP = 1000
EST_QUESTION_TOKENS = 400
FREE_TOKENS_PER_DAY = 458_000  # 10,000 neurons — 사용자 전달 문서 요약(실측 아님)
LONG_SIDE = 2000  # 자동 스캔 라우트(_load_page_image)와 같은 크기 — 실제로 보내는 것과 같게 잰다

# 종류 정답. True=있다, False=없다, 칸이 없으면 «재지 않음». 근거·신뢰도는 쪽마다 적는다.
_PRINTED_PAPER = {
    "modern_print": True,
    "hangul": True,
    "classical_print": False,
    "handwriting": False,
    "kunten": False,
    "blank": False,
}
GOLD: list[dict] = [
    {
        "key": "mongu_naikaku_p30",
        "container": ".trash",
        "doc": "20261002T060858_doc_20261002",
        "page": 30,
        "kinds": {
            "classical_print": True,
            "modern_print": False,
            "handwriting": False,
            "hangul": False,
            "blank": False,
            # kunten: 재지 않음 — 일본 소장 한적이라 훈점이 있을 수 있는데 축소판으로는 가릴 수 없다
        },
        "source": "舊注蒙求攷異提要(국립공문서관 내각문고 이미지, 쪽에 소장처 표시). "
        "목판 판식(광곽·계선)",
        "confidence": "보통",
    },
    {
        "key": "kol571_p100",
        "container": ".trash",
        "doc": "20260907T081649_kol000000571",
        "page": 100,
        "kinds": {
            "classical_print": True,
            "modern_print": False,
            "handwriting": False,
            "hangul": False,
            "kunten": False,
            "blank": False,
        },
        "source": "국립중앙도서관 KOL000000571 — 서지 정보 없음, "
        "쪽 축소판의 판식·각자(刻字)로 목판본",
        "confidence": "보통",
    },
    {
        "key": "hojae001_p40",
        "container": ".trash",
        "doc": "20260906T083018_pb6b_104_001_93",
        "page": 40,
        "kinds": {
            "classical_print": True,
            "modern_print": False,
            "handwriting": False,
            "hangul": False,
            "kunten": False,
            "blank": False,
        },
        "source": "浩齋辰巳日錄 PB6B-104_001 — D-126 벤치마크(2026-09-11)가 «석인본»으로 분류. "
        "석인본은 «목판·옛 활자»의 문자 그대로는 아니어서 판본 질문의 정답이 흔들릴 수 있다",
        "confidence": "보통",
    },
    {
        "key": "cheonjin_p20",
        "container": ".trash",
        "doc": "20260906T064516_doc_20260902",
        "page": 20,
        "kinds": {
            "handwriting": True,
            "classical_print": False,
            "kunten": False,
            "blank": False,
            # modern_print·hangul: 재지 않음 — 규장각 이미지 머리·꼬리에 디지털 표시(한글·활자)가
            # 얹혀 있고 괘지 여백에 인쇄 문구가 있다
        },
        "source": "天津談草(규장각 원문 이미지) — 괘지에 붓으로 쓴 필사본",
        "confidence": "보통",
    },
    {
        "key": "cheonjin_p100",
        "container": ".trash",
        "doc": "20260906T064516_doc_20260902",
        "page": 100,
        "kinds": {
            "handwriting": True,
            "classical_print": False,
            "kunten": False,
            "blank": False,
        },
        "source": "같은 책 — 위와 같다",
        "confidence": "보통",
    },
    {
        "key": "paper2001_p5",
        "container": ".trash",
        "doc": "20260917T091342_doc_2001",
        "page": 5,
        "kinds": dict(_PRINTED_PAPER),
        "source": "간호윤 2001 학술 논문(PDF) — 근현대 활자 + 한글 본문",
        "confidence": "높음",
    },
    {
        "key": "paper2007_p5",
        "container": ".trash",
        "doc": "20260917T092202_doc_2007",
        "page": 5,
        "kinds": dict(_PRINTED_PAPER),
        "source": "한의숭 2007 학술 논문(PDF) — 근현대 활자 + 한글 본문",
        "confidence": "높음",
    },
    {
        "key": "kimil_p4",
        "container": ".trash",
        "doc": "20261002T053436_doc_20260917",
        "page": 4,
        "kinds": dict(_PRINTED_PAPER),
        "source": "김일렬 擬人體文學 硏究 — 국한문 혼용 활자 논문(한글은 토·어미로 섞임)",
        "confidence": "높음",
    },
]
# 돌린 사본의 각(시계 방향으로 «흐트러뜨린» 각). 쪽마다 둘 — 셋이 고르게 돌아가도록
_ROT_PAIRS = [(90, 180), (180, 270), (270, 90)]


def _truth_orientation(disturb: int) -> str:
    """시계 방향 disturb°로 흐트러뜨린 쪽의 정답.

    바로 세우려면 시계 방향 (360 − disturb)°가 필요하다.

    page_survey.DELTA(답 → 더할 시계 각)의 역으로 구한다 — 부호를 두 곳에 따로 적지 않는다.
    """
    from core.page_survey import DELTA

    need = (360 - disturb) % 360
    return next(o for o, d in DELTA.items() if d == need)


def plan_items() -> list[dict]:
    """보낼 이미지 목록 — 쪽마다 0° 하나와 돌린 사본 둘."""
    items = []
    for i, g in enumerate(GOLD):
        for d in (0, *_ROT_PAIRS[i % len(_ROT_PAIRS)]):
            items.append({**g, "id": f"{g['key']}_r{d}", "disturb": d})
    return items


def default_library() -> Path | None:
    """설정 파일의 첫 서고. 없으면 None."""
    p = Path.home() / ".classical-text-browser" / "config.json"
    try:
        libs = json.loads(p.read_text(encoding="utf-8")).get("recent_libraries") or []
        return Path(libs[0]["path"]) if libs else None
    except (OSError, ValueError, KeyError, IndexError):
        return None


def render(library: Path, item: dict) -> tuple[bytes, int, int] | None:
    """쪽을 그려(저장된 회전을 얹고) 긴 변 2000px로 줄이고 흐트러뜨린 각만큼 돌린다.

    출력: (JPEG, 폭, 높이) 또는 None(이미지 없음).
    """
    from ocr.image_utils import load_page_image_from_pdf, rotate_page_image

    img = load_page_image_from_pdf(
        str(library / item["container"]) if item["container"] else str(library),
        item["doc"],
        item["page"],
        part_id="vol1",
    )
    if img is None:
        return None
    img = img.convert("RGB")
    img.thumbnail((LONG_SIDE, LONG_SIDE))
    img = rotate_page_image(img, item["disturb"])
    out = BytesIO()
    img.save(out, format="JPEG", quality=88)
    return out.getvalue(), img.width, img.height


def _summary(rows: list[dict]) -> dict:
    """방향 정확도(전체·각별), 종류마다 정확도·정밀도·재현율(재지 않음 제외), 지연."""
    from core.page_survey import DECIDER_CONTENT_QUESTIONS

    ok = [r for r in rows if not r.get("error")]
    out: dict = {"images": len(rows), "answered": len(ok), "errors": len(rows) - len(ok)}
    o_hits = [r["pred_orientation"] == r["truth_orientation"] for r in ok]
    out["orientation_acc"] = round(sum(o_hits) / len(o_hits), 3) if o_hits else None
    by_angle = {}
    for d in (0, 90, 180, 270):
        hs = [r["pred_orientation"] == r["truth_orientation"] for r in ok if r["disturb"] == d]
        by_angle[str(d)] = f"{sum(hs)}/{len(hs)}" if hs else "-"
    out["orientation_by_disturb"] = by_angle
    kinds = {}
    for kind in DECIDER_CONTENT_QUESTIONS:
        tp = fp = fn = tn = 0
        for r in ok:
            truth = r["truth_kinds"].get(kind)
            if truth is None:
                continue
            pred = kind in r["pred_contents_raw"]
            tp += pred and truth
            fp += pred and not truth
            fn += (not pred) and truth
            tn += (not pred) and not truth
        n = tp + fp + fn + tn
        kinds[kind] = {
            "n": n,
            "acc": round((tp + tn) / n, 3) if n else None,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None,
            "positives": tp + fn,
        }
    out["kinds_at_0.5"] = kinds
    lat = sorted(r["latency_s"] for r in ok if r.get("latency_s") is not None)
    if lat:
        out["latency_s"] = {
            "median": round(statistics.median(lat), 2),
            "p90": round(lat[min(len(lat) - 1, int(len(lat) * 0.9))], 2),
            "max": round(lat[-1], 2),
        }
    return out


def _vision_asker(library: Path):
    """기준선: 자동 스캔이 비전 모델에 묻는 것과 같은 프롬프트·옵션·파서로 한 장을 판정한다.

    입력: 서고 경로. 출력: 함수(jpeg 바이트 → (방향, 종류 목록, "provider:model")).
    왜 같은 2MP로 줄이는가: clef(ClefClient)가 2MP로 줄여 보내므로,
    해상도 차이가 비교에 섞이지 않게 한다.
    """
    import asyncio

    from core.page_survey import (
        SURVEY_FALLBACK_MODEL,
        SURVEY_PROMPT,
        SURVEY_SYSTEM_PROMPT,
        parse_survey,
    )
    from llm.clef_cf import DEFAULT_IMAGE_PIXELS, fit_image_clef
    from llm.config import LlmConfig
    from llm.router import LlmRouter

    router = LlmRouter(LlmConfig(library_root=library))
    provider, model = SURVEY_FALLBACK_MODEL
    kwargs = {
        "image_mime": "image/jpeg",
        "system": SURVEY_SYSTEM_PROMPT,
        "response_format": "json",
        "purpose": "vision",
        "max_tokens": 800,  # llm_ocr의 자동 스캔과 같다(200이면 kimi가 사고에 다 써 잘린다)
        "think": False,
        "force_provider": provider,
        "force_model": model,
    }

    def ask(jpeg: bytes):
        img, _mime = fit_image_clef(jpeg, "image/jpeg", max_pixels=DEFAULT_IMAGE_PIXELS)
        resp = asyncio.run(router.call_with_image(SURVEY_PROMPT, img, **kwargs))
        o, contents = parse_survey(getattr(resp, "text", "") or "")
        who = f"{getattr(resp, 'provider', provider)}:{getattr(resp, 'model', model)}"
        return o, contents, who

    return ask


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--library", help="서고 경로(없으면 설정 파일의 첫 서고)")
    ap.add_argument("--run", action="store_true", help="실제로 보낸다(없으면 계획만)")
    ap.add_argument("--max-calls", type=int, default=24)
    ap.add_argument("--out", help="결과 JSONL(기본 logs/eval_clef/<UTC>.jsonl)")
    ap.add_argument("--resume", action="store_true", help="--out에 이미 있는 항목은 건너뛴다")
    ap.add_argument(
        "--engine",
        choices=("clef", "vision"),
        default="clef",
        help="clef = Cloudflare 판정 모델, vision = 화면의 종류 판정 기본 비전 모델"
        "(page_survey.SURVEY_FALLBACK_MODEL) — 같은 그림·같은 2MP로 견주는 기준선",
    )
    args = ap.parse_args()

    from core.page_survey import DECIDER_STATE, decider_questions, parse_decider_answers
    from llm.clef_cf import CLEF_INPUT_USD_PER_M, ClefClient, check_body_size

    library = Path(args.library).expanduser() if args.library else default_library()
    if library is None or not library.exists():
        print("서고를 찾지 못했습니다 — --library로 경로를 주세요.")
        return 2
    items = plan_items()

    # 계획: 쪽을 실제로 그리고 본문을 실제로 만들어 상한을 검사한다(보내지 않는다)
    dry = ClefClient(api_key="dry-run", account_id="dry-run", max_calls=0)
    questions = decider_questions()
    images: dict[str, bytes] = {}
    est_tokens = 0
    missing = []
    for it in items:
        r = render(library, it)
        if r is None:
            missing.append(it["id"])
            continue
        jpeg, w, h = r
        images[it["id"]] = jpeg
        check_body_size(dry._body(DECIDER_STATE, questions, [(jpeg, "image/jpeg")]))
        est_tokens += int(w * h / 1e6 * EST_TOKENS_PER_MP) + EST_QUESTION_TOKENS
    calls = len(images)
    angles = {
        d: sum(1 for it in items if it["disturb"] == d and it["id"] in images)
        for d in (0, 90, 180, 270)
    }
    print(f"서고: {library}")
    print(
        f"계획: 쪽 {len(GOLD)}개 × (원본 1 + 돌린 사본 2) = 이미지 {calls}장 · 호출 {calls}회 "
        f"(흐트러뜨린 각 0°:{angles[0]} 90°:{angles[90]} 180°:{angles[180]} 270°:{angles[270]})"
    )
    print(
        f"어림 입력 토큰 {est_tokens:,} "
        f"(가정: MP당 {EST_TOKENS_PER_MP}토큰 + 질문 {EST_QUESTION_TOKENS}) · "
        f"명목 비용 ${est_tokens * CLEF_INPUT_USD_PER_M / 1e6:.4f} · "
        f"하루 무료 몫 ≈{FREE_TOKENS_PER_DAY:,}의 "
        f"{est_tokens / FREE_TOKENS_PER_DAY:.0%} "
        f"(어림이 3배 틀려도 {3 * est_tokens / FREE_TOKENS_PER_DAY:.0%})"
    )
    print("본문 상한(13MiB)·이미지 상한 검사: 통과")
    if missing:
        print(f"이미지 없음(빠짐): {', '.join(missing)} — 휴지통을 비웠으면 GOLD를 고치세요")
    live = ClefClient(library_root=library, max_calls=max(calls, 1))
    vision = args.engine == "vision"
    if vision:
        from core.page_survey import SURVEY_FALLBACK_MODEL

        print(f"엔진: 비전 모델 {':'.join(SURVEY_FALLBACK_MODEL)} (Ollama 구독 — 추가 요금 없음)")
    else:
        print(f"Cloudflare 키(토큰+계정 id): {'있음' if live.has_key else '없음'}")
    if not args.run:
        print("보내지 않았습니다 — 실제로 재려면 --run")
        return 0
    if calls > args.max_calls:
        print(f"거부: 호출 {calls}회가 상한 {args.max_calls}회를 넘습니다(--max-calls).")
        return 2
    if not vision and not live.has_key:
        print("Cloudflare 키가 없습니다 — 설정 → 판정 모델, 또는 Windows 사용자 환경변수.")
        return 2
    ask_vision = _vision_asker(library) if vision else None

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else ROOT / "logs" / "eval_clef" / f"{stamp}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    done: set[str] = set()
    if args.resume and out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if not row.get("error"):
                done.add(row["id"])
    if not vision:
        live.gate(sum(1 for i in images if i not in done))
    with out.open("a", encoding="utf-8", newline="\n") as f:
        for it in items:
            if it["id"] not in images or it["id"] in done:
                continue
            row = {
                "id": it["id"],
                "key": it["key"],
                "doc": it["doc"],
                "page": it["page"],
                "disturb": it["disturb"],
                "truth_orientation": _truth_orientation(it["disturb"]),
                "truth_kinds": it["kinds"],
                "confidence": it["confidence"],
            }
            t0 = time.monotonic()
            if vision:
                try:
                    o, contents, who = ask_vision(images[it["id"]])
                    row["latency_s"] = round(time.monotonic() - t0, 3)
                    row.update(
                        {
                            "pred_orientation": o,
                            "pred_contents": contents,
                            "pred_contents_raw": contents,
                            "engine": who,
                        }
                    )
                except Exception as e:  # noqa: BLE001 — 한 장이 실패해도 나머지는 잰다
                    row["latency_s"] = round(time.monotonic() - t0, 3)
                    row["error"] = f"{type(e).__name__} {e}"[:300]
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                print(
                    f"{it['id']}: 방향 {row.get('pred_orientation')} "
                    f"(정답 {row['truth_orientation']}) 종류 {row.get('pred_contents')} "
                    f"{row.get('error', '')}"
                )
                continue
            try:
                ans = live.ask(
                    DECIDER_STATE,
                    questions,
                    images=[(images[it["id"]], "image/jpeg")],
                    purpose="eval_clef",
                )
                row["latency_s"] = round(time.monotonic() - t0, 3)
                o, contents, probs = parse_decider_answers(ans)
                # 백지 규칙(백지면 나머지 지움)을 거치기 전의 «문턱 이상» 목록 — 종류마다 따로 센다
                raw = [k for k, p in (probs.get("contents") or {}).items() if p >= 0.5]
                row.update(
                    {
                        "pred_orientation": o,
                        "pred_contents": contents,
                        "pred_contents_raw": raw,
                        "probs": probs,
                    }
                )
            except Exception as e:  # noqa: BLE001 — 한 장이 실패해도 나머지는 잰다
                row["latency_s"] = round(time.monotonic() - t0, 3)
                status = getattr(e, "status", "") or ""
                detail = getattr(e, "detail", "") or e
                row["error"] = f"{type(e).__name__} {status} {detail}"[:300]
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(
                f"{it['id']}: 방향 {row.get('pred_orientation')} (정답 {row['truth_orientation']}) "
                f"종류 {row.get('pred_contents')} {row.get('error', '')}"
            )
    rows = []
    for ln in out.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(ln))
        except ValueError:
            continue
    # 이어 받기로 같은 항목이 두 번(실패 → 성공) 있으면 뒤의 것만 센다
    rows = list({r["id"]: r for r in rows if "id" in r}.values())
    summary = {
        "jsonl": str(out),
        "engine": args.engine,
        **({} if vision else {"usage": live.usage()}),
        **_summary(rows),
    }
    summ_path = out.with_suffix(".summary.json")
    summ_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"저장: {out} · {summ_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
