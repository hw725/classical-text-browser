"""이미 OCR 한 쪽에 문헌 승인 쌍(예: 為↔爲)을 반영한다 — 다시 OCR 하지 않고 (D-138 후속).

승인은 대개 OCR 뒤에 한다(정렬 화면에서 «이 문헌에서는 같은 글자»로 승인). 그때 이미 저장된 L2 의
`ocr_config.script_normalize` 보류 자리 가운데 승인된 쌍만 바꾼다.

- 기본은 미리보기(무엇이 몇 자 바뀌는지만). `--apply` 일 때만 쓴다 — D-080 의 일괄교정 원칙
  (사람이 범위를 지정하고 미리보기를 본 뒤 실행).
- 쓰기 전에 쪽마다 `page_backup.save_backup` 으로 직전 상태를 남긴다(되돌리기 = 백업 복원).
- L2 만 고친다. L4(사람이 확정한 교정 텍스트)는 건드리지 않는다(D-080 결정 1).
- 그 자리의 글자가 기록과 다르면(사람이 이미 고쳤다) 건너뛴다.

사용:
    uv run python scripts/apply_script_approvals.py --library <서고> --doc <문헌 id>
        [--part <권>] [--apply]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 한자 출력 — Windows cp949 콘솔에서 죽지 않게(CJK 계약 E3)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from core.alignment import load_document_approvals  # noqa: E402
from core.document import write_json_atomic  # noqa: E402
from src.ocr import page_backup  # noqa: E402
from src.ocr.script_normalize import apply_approvals  # noqa: E402


def run(library: Path, doc_id: str, part: str | None, do_apply: bool) -> dict:
    doc = library / "documents" / doc_id
    approved = load_document_approvals(doc).is_variant
    l2 = doc / "L2_ocr"
    totals = {"pages": 0, "changed_pages": 0, "chars": 0, "by_pair": {}}
    for f in sorted(l2.glob(f"{part or '*'}_page_*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        cfg = (data.get("ocr_config") or {}).get("script_normalize") or {}
        blocks = cfg.get("blocks") or {}
        if not blocks:
            continue
        totals["pages"] += 1
        by_id = {r.get("layout_block_id"): r for r in data.get("ocr_results", [])}
        page_done = []
        for bid, rec in blocks.items():
            item = by_id.get(bid)
            if item is None:
                continue
            page_done += apply_approvals(item, rec, approved)
        if not page_done:
            continue
        totals["changed_pages"] += 1
        totals["chars"] += len(page_done)
        for r in page_done:
            key = f"{r[2]}→{r[3]}"
            totals["by_pair"][key] = totals["by_pair"].get(key, 0) + 1
        kinds = "".join(sorted({f"{r[2]}→{r[3]} " for r in page_done}))
        print(f"  {f.name}: {len(page_done)}자 ({kinds.strip()})")
        if do_apply:
            stem = f.stem  # {part}_page_NNN
            p_id, _, num = stem.rpartition("_page_")
            page_backup.save_backup(doc, p_id, int(num))
            write_json_atomic(f, data)
    return totals


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--library", required=True, type=Path)
    ap.add_argument("--doc", required=True)
    ap.add_argument("--part")
    ap.add_argument("--apply", action="store_true",
                    help="미리보기가 아니라 실제로 쓴다(쪽마다 백업 후)")
    a = ap.parse_args(argv)
    t = run(a.library, a.doc, a.part, a.apply)
    mode = "반영" if a.apply else "미리보기(쓰지 않음)"
    print(f"[{mode}] 기록 있는 쪽 {t['pages']} · 바뀌는 쪽 {t['changed_pages']} · "
          f"{t['chars']}자 · {t['by_pair']}")
    if not a.apply and t["chars"]:
        print("  실제로 쓰려면 --apply (쪽마다 직전 상태를 백업한다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
