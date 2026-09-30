"""작업 계획을 문헌에 적용하고, 계획대로 쪽을 읽는다 (D-131).

화면(「말로 작업 지시」)과 CLI(`ctb read`)가 **같은 함수**를 쓴다 — 두 입구가 따로 구현하면
한쪽만 고쳐진다.

흐름:
    1. apply_plan — 계획을 문헌 폴더에 **권마다** 저장(read_plan/{권}.json)하고, 회전 구간을
       manifest에, 판독 지침을 manifest.ocr_guidance에 적는다. 돌릴 쪽과 «구간별 엔진 계획»을
       돌려준다.
    2. read_pages — 쪽마다 전면 블록(계획의 쓰기 방향) → 계획의 엔진으로 OCR → L4 채우기.
       이미 L2가 있는 쪽은 건너뛴다(L2 자체가 체크포인트 — 끊겨도 이어서 돈다).
       화면은 이 함수 대신 기존 「권 전체 OCR」(ocr/batch)에 engine_plan을 넘겨 같은 일을 한다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

PLAN_DIR = "read_plan"
LEGACY_PLAN_FILE = "read_plan.json"  # v1.4.2 개발 중 한때 쓰던 자리(권 구분 없음) — 읽기만 한다
_PART_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def check_part_id(part_id: str) -> str:
    """권 id가 파일 이름에 써도 안전한가 — 경로 구분자·glob 문자를 막는다. 틀리면 ValueError."""
    if not _PART_RE.match(str(part_id or "")):
        raise ValueError(f"권 id가 올바르지 않습니다: {part_id!r} (영문·숫자·_·- 64자 이내)")
    return part_id


def plan_path(doc_path: str | Path, part_id: str) -> Path:
    """권의 작업 계획 파일. 원본 저장소에 두어 Git 이력이 남는다(편성과 같은 이유, D-097).

    왜 권마다인가: 회전·장·쪽 이름표는 권마다 다르다. 한 파일에 두면 둘째 권의 계획이 첫째 권의
    장 목록을 덮는다(Codex 지적 2026-09-30).
    """
    return Path(doc_path) / PLAN_DIR / f"{check_part_id(part_id)}.json"


def load_plan(doc_path: str | Path, part_id: str) -> Optional[dict]:
    """저장된 작업 계획. 없거나 깨졌으면 None. 권별 파일이 없으면 옛 자리(권 구분 없음)를 읽는다."""
    for p in (plan_path(doc_path, part_id), Path(doc_path) / LEGACY_PLAN_FILE):
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
    return None


def page_count_of(doc_path: str | Path, part_id: str) -> int:
    """권의 쪽 수 — PDF를 직접 센다(manifest의 page_count가 비어 있는 옛 문헌도 있다)."""
    import fitz

    from ocr.image_utils import resolve_part_pdf

    with fitz.open(str(resolve_part_pdf(doc_path, part_id))) as pdf:
        return pdf.page_count


def engine_plan_of(settings: dict[int, dict]) -> list[dict]:
    """쪽별 설정을 일괄 OCR의 engine_plan 모양으로 묶는다.

    출력: [{from, to, engine_id, writing_direction}].
    엔진과 쓰기 방향이 둘 다 같은 이어진 쪽끼리 한 구간이 된다.
    """
    out: list[dict] = []
    for p in sorted(settings):
        s = settings[p]
        if s.get("skip"):
            continue
        key = (s["engine"], s["writing"])
        if (
            out
            and (out[-1]["engine_id"], out[-1]["writing_direction"]) == key
            and out[-1]["to"] == p - 1
        ):
            out[-1]["to"] = p
        else:
            out.append({"from": p, "to": p, "engine_id": key[0], "writing_direction": key[1]})
    return out


def apply_plan(doc_path: str | Path, part_id: str, plan: dict) -> dict:
    """계획을 문헌에 적용한다. OCR은 돌리지 않는다.

    입력: 문헌 경로, 권 id, 계획(validate_plan을 거친 것이 아니어도 된다 — 여기서 다시 확인한다).
    출력: {"plan", "problems", "pages": 돌릴 쪽 목록, "skipped", "engine_plan",
          "rotation_ranges": manifest에 저장된 범위, "rotation_runs": 계획의 구간}.
    왜 회전을 «범위»로 적는가: 권 전체 회전(D-123)으로는 누운 쪽과 선 쪽이 섞인 책을 표현할 수
    없다. 쪽 범위 회전(D-126)이 그 자리다. 계획에 없는 쪽의 회전은 건드리지 않는다.
    쓰기는 **확인이 다 끝난 뒤에만** 한다 — 확인 도중에 틀리면 아무것도 바뀌지 않는다.
    """
    from core.document import (
        get_document_info,
        part_rotation_ranges,
        set_part_rotation,
        write_json_atomic,
    )
    from core.read_plan import page_settings, rotation_runs, validate_plan

    doc_path = Path(doc_path).resolve()
    check_part_id(part_id)
    count = page_count_of(doc_path, part_id)
    clean, problems = validate_plan(plan, count)
    settings = page_settings(clean, count)
    runs = rotation_runs(settings)
    for a, b, rot in runs:
        set_part_rotation(doc_path, part_id, rot, pages=(a, b))
    # 판독 지침 — 비어 있으면 기존 지침을 지우지 않는다(계획에 안 적었을 뿐일 수 있다)
    if clean["guidance"]:
        manifest = get_document_info(doc_path)
        manifest["ocr_guidance"] = clean["guidance"]
        write_json_atomic(doc_path / "manifest.json", manifest)
    target = plan_path(doc_path, part_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(target, clean)
    return {
        "plan": clean,
        "problems": problems,
        "pages": [p for p in sorted(settings) if not settings[p].get("skip")],
        "skipped": [p for p in sorted(settings) if settings[p].get("skip")],
        "engine_plan": engine_plan_of(settings),
        # 화면이 서버와 같은 것을 보도록 manifest에 실제로 남은 범위(권의 회전과 같은 조각은 빠짐)
        "rotation_ranges": part_rotation_ranges(doc_path, part_id),
        "rotation_runs": [{"from": a, "to": b, "rotation": r} for a, b, r in runs],
    }


def l4_is_hand_edited(doc_path: Path, part_id: str, page: int) -> bool:
    """확정본(L4)이 있고, 지금 L2를 그대로 옮긴 것과 다른가 — 그러면 덮지 않는다.

    일괄 OCR 라우트의 같은 판정과 같은 규칙이다(D-115 보강). **OCR을 다시 돌리기 전에** 불러야
    한다 — 돌린 뒤에는 L2가 바뀌어 옛 자동 L4가 «사람이 고친 것»으로 보인다.
    """
    from core.document import get_corrected_text
    from ocr.correction_pass import compose_page_text

    try:
        l4 = (get_corrected_text(doc_path, part_id, page).get("corrected_text") or "").strip()
    except Exception:  # noqa: BLE001 — 확정본이 없으면 지킬 것도 없다
        return False
    if not l4:
        return False
    l2_path = doc_path / "L2_ocr" / f"{part_id}_page_{page:03d}.json"
    if not l2_path.exists():
        return True
    try:
        l2 = json.loads(l2_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    return compose_page_text(l2, None).strip() != l4


def read_pages(
    pipeline,
    doc_id: str,
    doc_path: str | Path,
    part_id: str,
    pages: list[int],
    engine_plan: list[dict],
    on_page: Optional[Callable[[dict], None]] = None,
    redo: bool = False,
    **engine_kwargs,
) -> dict:
    """계획대로 쪽을 읽는다(CLI 경로). 화면은 같은 일을 ocr/batch 라우트로 한다.

    입력: OcrPipeline, 문헌 id·경로, 권, 돌릴 쪽, engine_plan(apply_plan의 것), 쪽마다 부를 콜백,
          redo(True면 L2가 있어도 다시),
          engine_kwargs(force_provider·force_model — llm_vision 구간에만).
    출력: {"done", "resumed", "failed": [{"page", "error"}], "kept_l4": [쪽]}.
    계획에 없는 쪽은 돌리지 않는다(무엇으로 읽을지 모르는 쪽을 추측하지 않는다).
    """
    from core.document import save_page_text
    from ocr.correction_pass import compose_page_text
    from ocr.full_page_block import ensure_full_page_block
    from ocr.layout_staleness import has_ocr_result

    doc_path = Path(doc_path)
    by_page = {}
    for r in engine_plan:
        for p in range(r["from"], r["to"] + 1):
            by_page[p] = r
    stats = {"done": 0, "resumed": 0, "failed": [], "kept_l4": []}
    for i, page in enumerate(pages, 1):
        r = by_page.get(page)
        if r is None:
            continue
        if not redo and has_ocr_result(doc_path, part_id, page):
            stats["resumed"] += 1
            continue
        try:
            # 보호 판정은 OCR 전에 — 뒤에 하면 L2가 바뀌어 판정이 뒤집힌다(Codex 지적 2026-09-30)
            keep = l4_is_hand_edited(doc_path, part_id, page)
            ensure_full_page_block(
                doc_path, part_id, page, writing_direction=r["writing_direction"]
            )
            result = pipeline.run_page(
                doc_id=doc_id,
                part_id=part_id,
                page_number=page,
                engine_id=r["engine_id"],
                # force_provider·force_model은 llm_vision만 본다(다른 엔진은 무시한다)
                **(engine_kwargs if r["engine_id"] == "llm_vision" else {}),
            )
            summary = result.to_summary()
            if summary.get("errors") and not summary.get("ocr_results"):
                raise RuntimeError("; ".join(str(e) for e in summary["errors"]))
            if keep:
                stats["kept_l4"].append(page)
            else:
                text = compose_page_text({"ocr_results": summary.get("ocr_results") or []}, None)
                save_page_text(doc_path, part_id, page, text)
            stats["done"] += 1
        except Exception as e:  # noqa: BLE001 — 한 쪽이 실패해도 나머지는 돈다. 실패는 모아 알린다
            stats["failed"].append({"page": page, "error": f"{type(e).__name__}: {e}"})
        if on_page:
            on_page({"page": page, "index": i, "total": len(pages), "engine": r["engine_id"]})
    return stats
