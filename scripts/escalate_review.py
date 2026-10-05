# -*- coding: utf-8 -*-
"""애매한 후보 2차 판정을 서버 없이 — Claude Code/Desktop 세션용 (D-137).

사용자가 «애매한 후보 판정해 줘»라고 하면 세션이 이렇게 한다(CLAUDE.md «Claude 세션에서»):

    uv run python scripts/escalate_review.py export --doc <문헌> --part <권> --out esc.txt
    (세션이 esc.txt의 지시문대로 직접 판정해 answers.json을 쓴다 — 외부 모델을 부르지 않는다)
    uv run python scripts/escalate_review.py import --doc <문헌> --part <권> --in answers.json

화면과 같은 core 함수(`core.escalate_review`)를 쓴다.
후보 목록은 편성 화면이 「판정 모델로 고르기」나
「애매한 후보 내보내기」 때 서고 메모(`<서고>/.escalate_review/`)에 적어 둔 것이다. 들인 판정은 같은
메모에 더해지고, 화면의 「판정 들이기 ▸ 저장된 판정 불러오기」가 체크 제안으로 불러온다.
**경계는 저장하지 않는다** — 저장은 사람이 화면에서 「적용」을 누를 때뿐이다.

이 스크립트는 네트워크를 쓰지 않는다. 모델을 부르는 코드가 없다.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# CJK Text Contract E3 — 한국어 Windows 콘솔(cp949)은 «—»를 print하면 즉사한다
from core.console import force_utf8_console  # noqa: E402

force_utf8_console()

from core.escalate_review import (  # noqa: E402
    CHUNK_SIZE,
    export_from_store,
    import_answers,
    store_path,
)
from core.segmentation import collect_document_lines  # noqa: E402


def _library(arg: str | None) -> pathlib.Path:
    """서고 경로. 주지 않으면 앱이 마지막으로 연 서고(설정 파일)."""
    if arg:
        return pathlib.Path(arg)
    from core.app_config import get_last_library

    last = get_last_library()
    if not last:
        sys.exit("서고를 찾지 못했습니다. --library <서고 폴더>로 알려 주세요.")
    return pathlib.Path(last)


def main(argv: list[str] | None = None) -> int:
    """입력: 명령줄. 출력: 종료 코드(0 성공, 1 실패 — 한국어 이유를 stderr에)."""
    ap = argparse.ArgumentParser(
        description="애매한 후보 2차 판정 — 내보내기·들이기(모델을 부르지 않는다)"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("export", "import"):
        p = sub.add_parser(name)
        p.add_argument("--library", help="서고 폴더(생략하면 마지막으로 연 서고)")
        p.add_argument("--doc", required=True, help="문헌 id")
        p.add_argument("--part", required=True, help="권 id")
        if name == "export":
            p.add_argument("--out", required=True, help="붙여 넣을 글을 쓸 파일")
            p.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
            p.add_argument("--book-type", choices=["diary", "collection"], default=None)
        else:
            p.add_argument(
                "--in", dest="inp", required=True, help="답(JSON — 울타리·설명이 섞여도 됨)"
            )
    a = ap.parse_args(argv)
    lib = _library(a.library)
    doc_path = lib / "documents" / a.doc
    if not doc_path.is_dir():
        print(f"문헌을 찾을 수 없습니다: {doc_path}", file=sys.stderr)
        return 1
    try:
        if a.cmd == "export":
            lines, _ = collect_document_lines(doc_path, a.part, None)
            out = export_from_store(lib, a.doc, a.part, lines, a.chunk_size, a.book_type)
            text = "\n\n".join(c["text"] for c in out["chunks"])
            pathlib.Path(a.out).write_text(text, encoding="utf-8")
            print(
                f"후보 {out['count']}개 · 묶음 {len(out['chunks'])}개 → {a.out}"
                + (f" · 확정본에서 사라져 뺀 것 {len(out['skipped'])}" if out["skipped"] else "")
            )
            return 0
        answer = pathlib.Path(a.inp).read_text(encoding="utf-8")
        res = import_answers(lib, a.doc, a.part, answer)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    c = res["counts"]
    print(
        f"예 {c['yes']} · 아니오 {c['no']} · 누락 {c['missing']} · 거부 {c['rejected']}"
        f" · 모양 틀림 {c['malformed']} · 아직 답 없음 {res['remaining']}"
    )
    if res["unknown_ids"]:
        print("거부한 id(후보에 없음): " + ", ".join(res["unknown_ids"][:20]))
    if res["missing_ids"]:
        print("누락 id: " + ", ".join(res["missing_ids"][:20]))
    print(
        f"메모: {store_path(lib, a.doc, a.part)} — 경계는 저장하지 않았습니다. 편성 화면 "
        "「판정 들이기 ▸ 저장된 판정 불러오기」 뒤 「적용」을 누르세요."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
