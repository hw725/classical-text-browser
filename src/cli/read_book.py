"""`ctb read` — 작업 계획대로 책 한 권을 읽고 장별 문서로 낸다 (D-131).

화면의 「말로 작업 지시」와 같은 핵심 함수(core/read_plan, ocr/read_book, export/*)를 쓴다.
주 사용자는 화면을 쓴다 — 이 명령은 많은 쪽을 밤새 돌리거나 에이전트(Claude Code 등)가
직접 부를 때의 입구다.

하위 동작(한 명령에 차례로 붙는다):
    --said "…"      말 → 계획 초안(LLM). 계획 파일로 저장하고 멈춘다(돌리지 않는다).
    --plan 파일     계획을 문헌에 적용(회전·지침·장을 **저장**한다). --execute가 있으면 OCR까지.
    --note 파일     LLM이 돌려준 강독 결과를 기존 층에 나눠 담는다(교정 → L4, 항목 → 편성 경계,
                    국역 → L6, 어휘·비고 → L7). 노트 파일은 따로 저장하지 않는다.
    --export md,wiki 확정본(L4)과 층(경계·L6·L7)에서 장별 원문과 강독 노트를 새로 만든다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _doc_path(library: Path, doc_id: str) -> Path:
    return library / "documents" / doc_id


def ensure_document(library: Path, doc_id: str, pdf: Path | None, title: str) -> Path:
    """문헌이 없으면 PDF로 등록한다. 입력: 서고, 문헌 id, PDF(없으면 이미 있어야 한다), 제목."""
    from core.document import add_document
    from core.library import init_library

    if not (library / "library_manifest.json").exists():
        init_library(str(library))
    doc_path = _doc_path(library, doc_id)
    if not (doc_path / "manifest.json").exists():
        if pdf is None:
            raise FileNotFoundError(
                f"서고에 문헌 «{doc_id}»이 없습니다 — 처음 적용할 때는 PDF 경로를 함께 주세요. "
                f"예: ctb read 교재.pdf --doc-id {doc_id} --plan 계획.json"
            )
        add_document(library_path=library, title=title or pdf.stem, doc_id=doc_id, files=[pdf])
    return doc_path


def cmd_read(args) -> int:
    """ctb read 본체. 출력: 종료 코드."""
    import asyncio

    from core.read_plan import KNOWN_ENGINES, parse_pages, plan_from_words
    from ocr.read_book import apply_plan, load_plan, page_count_of, read_pages

    library = Path(args.library).expanduser().resolve()
    pdf = Path(args.pdf).resolve() if args.pdf else None
    doc_id = args.doc_id or (pdf.stem.lower() if pdf else None)
    if not doc_id or not doc_id.replace("_", "").isascii():
        print("문헌 id(--doc-id)를 영문 소문자·숫자·밑줄로 주세요. 예: --doc-id lecture_2026")
        return 2

    # 1) 말 → 계획 초안
    if args.said:
        count = None
        if pdf:
            import fitz

            with fitz.open(str(pdf)) as d:
                count = d.page_count
        else:
            count = page_count_of(_doc_path(library, doc_id), args.part)
        from cli.models import make_router
        from ocr.registry import OcrEngineRegistry

        # 모델에게는 **설치된** 엔진을 보인다 — 알려진 엔진 전부를 보이면 이 PC에서 안 도는
        # 엔진으로 계획을 짠다(Codex 지적 2026-09-30). 목록을 못 얻으면 알려진 엔진으로.
        try:
            reg = OcrEngineRegistry()
            reg.auto_register()
            available = [e["engine_id"] for e in reg.list_engines() if e.get("available")]
        except Exception:  # noqa: BLE001
            available = list(KNOWN_ENGINES)
        base = None
        if args.plan and Path(args.plan).exists():
            base = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        plan, meta = asyncio.run(
            plan_from_words(
                args.said,
                count,
                available or list(KNOWN_ENGINES),
                make_router(library),
                base_plan=base,
            )
        )
        if plan is None:
            print(f"계획을 만들지 못했습니다: {meta.get('error')}")
            return 1
        out = Path(args.plan or f"{doc_id}_plan.json")
        out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"계획 초안을 저장했습니다: {out}  (모델 {meta.get('provider')}:{meta.get('model')})")
        for u in meta["unsupported"]:
            print(f"  옮기지 못한 말 — {u['said']}: {u['why']}")
        print("계획을 확인·수정한 뒤 --plan 으로 다시 실행하세요.")
        return 0

    # 2) 계획 적용(+ OCR)
    if args.plan:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        try:
            doc_path = ensure_document(library, doc_id, pdf, plan.get("title") or "")
            applied = apply_plan(doc_path, args.part, plan)
        except (FileNotFoundError, ValueError) as e:
            print(f"계획을 적용하지 못했습니다: {e}")
            return 2
        for p in applied["problems"]:
            print(f"  계획 문제 — {p['where']}: {p['why']}")
        pages = applied["pages"]
        if args.pages:
            keep = set(parse_pages(args.pages))
            pages = [p for p in pages if p in keep]
        print(
            f"계획 적용: 돌릴 쪽 {len(pages)} · 건너뛸 쪽 {len(applied['skipped'])} · "
            f"회전 구간 {len(applied['rotation_ranges'])}"
        )
        for r in applied["engine_plan"]:
            print(f"  {r['from']}~{r['to']}쪽: {r['engine_id']} ({r['writing_direction']})")
        if args.execute and pages:
            from cli.embed_folder import build_pipeline

            pipeline, _ = build_pipeline(library)
            model_kwargs = {}
            if args.model:
                from cli.models import resolve

                try:
                    prov, mod = resolve(str(args.model), library=library)
                except ValueError as e:
                    print(f"오류: {e}")
                    return 2
                model_kwargs = {"force_provider": prov, **({"force_model": mod} if mod else {})}
                print(f"llm_vision 구간의 모델: {prov}:{mod or '(기본)'}")
            stats = read_pages(
                pipeline,
                doc_id,
                doc_path,
                args.part,
                pages,
                applied["engine_plan"],
                on_page=lambda e: print(
                    f"  {e['index']}/{e['total']} — {e['page']}쪽 ({e['engine']})", flush=True
                ),
                redo=args.redo,
                **model_kwargs,
            )
            print(
                f"OCR: 새로 {stats['done']} · 이어받음 {stats['resumed']} · "
                f"실패 {len(stats['failed'])}"
            )
            for f in stats["failed"]:
                print(f"  실패 {f['page']}쪽 — {f['error']}")
            if stats["kept_l4"]:
                print(f"  사람이 고친 확정본이라 두었습니다: {stats['kept_l4']}")
            try:
                from core.document import git_commit_document

                git_commit_document(doc_path, f"OCR: 작업 계획대로 {stats['done']}쪽")
            except Exception:  # noqa: BLE001
                pass
        elif pages:
            print(
                "계획을 저장했습니다(회전·판독 지침·장). "
                "OCR은 돌리지 않았습니다 — 돌리려면 --execute."
            )

    doc_path = _doc_path(library, doc_id)

    # 3) LLM 결과(강독 결과) 되들이기 — 기존 층(L4·경계·L6·L7)에 나눠 담는다
    from core.reading_ingest import default_interp_id, ingest_answer

    interp_id = args.interp or default_interp_id(doc_id)
    for note_file in args.note or []:
        note = json.loads(Path(note_file).read_text(encoding="utf-8"))
        try:
            res = ingest_answer(
                library, doc_id, args.part, note, interp_id=interp_id, model=args.model_name
            )
        except ValueError as e:
            print(f"들이지 못했습니다({note_file}): {e}")
            return 1
        print(
            f"반영: {note['chapter']} — 교정 {len(res['corrected'])}쪽 · "
            f"경계 +{res['boundaries_added']} −{res['boundaries_removed']} · "
            f"번역 {res['translations']} · 주석 {res['annotations']}"
            + (f" · 사람이 고친 쪽이라 둔 L4 {res['kept']}" if res["kept"] else "")
            + (
                f" · 사람 번역·주석이 가리켜 남긴 경계 {len(res['boundaries_kept'])}"
                if res["boundaries_kept"]
                else ""
            )
            + (
                f" · 자리 못 찾은 항목 {len(res['unplaced_sections'])}"
                if res["unplaced_sections"]
                else ""
            )
            + (
                f" · 자리 못 찾은 구획 {len(res['unplaced_segments'])}"
                if res["unplaced_segments"]
                else ""
            )
            + (
                f" · 글자가 조금 다른 구획 {len(res['approx_segments'])}"
                if res["approx_segments"]
                else ""
            )
        )
        for u in res["unplaced_sections"] + res["unplaced_segments"]:
            print(f"    · 못 찾음: {u}")
        for u in res["approx_segments"]:
            print(f"    · 근사: {u}")

    # 4) 내보내기
    if args.export:
        from export.reading_note import (
            assemble_notes,
            note_filename,
            render_markdown,
            render_wiki,
        )
        from export.text_export import export_document

        out_dir = Path(args.output or (Path.cwd() / f"{doc_id}_export")).resolve()
        for fmt in [f.strip() for f in args.export.split(",") if f.strip()]:
            files, stats = export_document(doc_path, args.part, fmt=fmt, keep_lines=args.keep_lines)
            target = out_dir / fmt
            target.mkdir(parents=True, exist_ok=True)
            for name, text in files.items():
                (target / name).write_text(text, encoding="utf-8", newline="\n")
            notes = assemble_notes(library, doc_id, args.part, interp_id)
            for order, n in enumerate(notes, 1):
                body = render_wiki(n, author=args.author) if fmt == "wiki" else render_markdown(n)
                (target / note_filename(order, n["chapter"], fmt)).write_text(
                    body, encoding="utf-8", newline="\n"
                )
            print(
                f"{fmt}: {target} — 장 {stats['chapters']} · 쪽 {stats['pages']} · "
                f"뺀 잡음 줄 {stats['noise_lines']} · 강독 노트 {len(notes)}"
            )
    # 5) 틀로 강독 노트만 — 모양은 틀이, 내용은 층이 정한다(export/note_template.py)
    if args.template:
        from export.note_template import render_with_template
        from export.reading_note import assemble_notes, note_filename

        tpl_path = Path(args.template)
        template = tpl_path.read_text(encoding="utf-8")
        ext = args.template_ext or "txt"
        target = Path(args.output or (Path.cwd() / f"{doc_id}_export")).resolve() / "notes"
        target.mkdir(parents=True, exist_ok=True)
        notes = assemble_notes(library, doc_id, args.part, interp_id)
        try:
            for order, n in enumerate(notes, 1):
                (target / note_filename(order, n["chapter"], ext)).write_text(
                    render_with_template(n, template), encoding="utf-8", newline="\n"
                )
        except ValueError as e:
            print(f"오류: {e}", file=sys.stderr)
            return 1
        print(f"틀({tpl_path.name}): {target} — 강독 노트 {len(notes)}")
    if not (args.said or args.plan or args.note or args.export or args.template):
        plan = load_plan(doc_path, args.part)
        print(
            json.dumps(plan, ensure_ascii=False, indent=2)
            if plan
            else "저장된 작업 계획이 없습니다."
        )
    return 0


def add_parser(subparsers, default_library: str) -> None:
    """ctb read 서브커맨드를 등록한다."""
    p = subparsers.add_parser(
        "read",
        help="작업 계획(말 또는 JSON)대로 책 한 권을 OCR하고 장별 마크다운·미디어위키로 낸다",
        description='예: ctb read 교재.pdf --doc-id lecture --said "5~69쪽은 시계 방향으로 누운 '
        '2쪽 펼침, 근대 활자 세로쓰기"  →  계획 확인  →  ctb read 교재.pdf --doc-id lecture '
        "--plan lecture_plan.json --execute --export md,wiki",
    )
    p.add_argument("pdf", nargs="?", help="PDF 경로 (문헌이 이미 서고에 있으면 생략)")
    p.add_argument("--doc-id", help="서고 안 문헌 id (영문 소문자·숫자·밑줄)")
    p.add_argument("--library", default=default_library, help="서고 경로")
    p.add_argument("--part", default="vol1", help="권 id (기본 vol1)")
    p.add_argument("--said", help="책에 대해 아는 것을 말로 — LLM이 작업 계획 초안으로 옮긴다")
    p.add_argument("--plan", help="작업 계획 JSON (schemas/source_repo/read_plan.schema.json)")
    p.add_argument("--pages", help="계획 중 이번에 돌릴 쪽만 (예: 1-69)")
    p.add_argument("--execute", action="store_true", help="실제로 OCR을 돌린다")
    p.add_argument("--redo", action="store_true", help="이미 결과가 있는 쪽도 다시 돌린다")
    p.add_argument(
        "--model", help="llm_vision 구간이 쓸 모델 («ctb models»의 번호·이름 일부·프로바이더:모델)"
    )
    p.add_argument(
        "--note",
        action="append",
        help="LLM이 돌려준 강독 결과 JSON (여러 번 줄 수 있다) — L4·경계·L6·L7에 나눠 담는다",
    )
    p.add_argument("--interp", help="강독 결과를 담을 해석 저장소 id (기본: <문헌 id>_reading)")
    p.add_argument(
        "--model-name", default="LLM", help="강독 결과를 만든 모델 이름(번역·주석 기록용)"
    )
    p.add_argument("--export", help="내보낼 형식 md,wiki")
    p.add_argument("-o", "--output", help="내보낼 폴더 (기본: ./<문헌id>_export)")
    p.add_argument(
        "--keep-lines", action="store_true", help="원문 줄바꿈을 그대로 둔다(열 잇기 끔)"
    )
    p.add_argument("--author", help="미디어위키 노트의 작성자 표기")
    p.add_argument(
        "--template", help="강독 노트 틀 파일(Jinja2 — 화면 ③ 「틀 받기」로 받은 것). notes/에 낸다"
    )
    p.add_argument("--template-ext", help="틀로 만든 파일의 확장자(기본 txt)")
    p.set_defaults(func=lambda a: sys.exit(cmd_read(a)))
