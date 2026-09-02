"""CER 평가 하네스 — L4 확정본을 정답으로 L2·교정 초안의 글자 오류율을 잰다 (D-084).

왜 있는가:
    D-081·D-082·D-083으로 프롬프트와 흐름을 바꿨다. 바꾼 뒤 «정말 나아졌는가»를 잴
    도구가 없으면 비교 대상 저장소와 같은 자리에 선다 — 그쪽은 정확도 수치를 적었지만
    측정 스크립트도 결과도 없다. 프롬프트 공학의 주장은 전부 가설이다.

무엇을 재는가:
    CER = (불일치 + 삽입 + 누락) / 정답 글자 수.
    정렬은 기존 align_texts()를 재사용하고, 이체자는 D-080의 층을 따라 strict만
    일치로 센다 (loose·script 힌트는 여전히 오류로 센다 — 문헌이 승인하지 않은 관계는
    같은 글자가 아니다).

정답은 L4다:
    사람이 교정을 끝낸 쪽에서만 잴 수 있다. 그것이 맞다 — 이 도구는 회귀 검사기이지
    벤치마크가 아니다. L4가 없는 쪽은 «측정 불가»로 표시하고 건너뛴다.

비교 대상:
    - L2 엔진 결과 (ocr_engine 별로 묶는다)
    - 교정 초안(L4_text/correction_drafts/)이 있으면 그 블록의 교정본을 넣은 텍스트
      → «교정 패스가 CER을 낮췄는가»를 같은 쪽에서 바로 비교한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class PageCer:
    """한 쪽의 측정 결과."""

    page: int
    engine: Optional[str]
    ref_chars: int
    l2_cer: Optional[float]
    draft_cer: Optional[float] = None
    draft_mode: Optional[str] = None
    note: str = ""

    def to_dict(self) -> dict:
        d = {
            "page": self.page,
            "engine": self.engine,
            "ref_chars": self.ref_chars,
            "l2_cer": self.l2_cer,
        }
        if self.draft_cer is not None:
            d["draft_cer"] = self.draft_cer
            d["draft_mode"] = self.draft_mode
        if self.note:
            d["note"] = self.note
        return d


@dataclass
class CerReport:
    doc_id: str
    part_id: str
    pages: list[PageCer] = field(default_factory=list)

    def summary(self) -> dict:
        """엔진별 평균 CER(글자 수 가중)과 초안 비교."""
        by_engine: dict[str, dict] = {}
        draft_tot = {"errors": 0.0, "chars": 0, "pages": 0}
        for p in self.pages:
            if p.l2_cer is None:
                continue
            key = p.engine or "unknown"
            acc = by_engine.setdefault(key, {"errors": 0.0, "chars": 0, "pages": 0})
            acc["errors"] += p.l2_cer * p.ref_chars
            acc["chars"] += p.ref_chars
            acc["pages"] += 1
            if p.draft_cer is not None:
                draft_tot["errors"] += p.draft_cer * p.ref_chars
                draft_tot["chars"] += p.ref_chars
                draft_tot["pages"] += 1
        out = {
            "engines": {
                k: {
                    "pages": v["pages"],
                    "ref_chars": v["chars"],
                    "cer": round(v["errors"] / v["chars"], 4) if v["chars"] else None,
                }
                for k, v in by_engine.items()
            },
            "measured_pages": sum(1 for p in self.pages if p.l2_cer is not None),
            "skipped_pages": sum(1 for p in self.pages if p.l2_cer is None),
        }
        if draft_tot["pages"]:
            out["draft"] = {
                "pages": draft_tot["pages"],
                "ref_chars": draft_tot["chars"],
                "cer": round(draft_tot["errors"] / draft_tot["chars"], 4),
            }
        return out

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "part_id": self.part_id,
            "pages": [p.to_dict() for p in self.pages],
            "summary": self.summary(),
        }


def compute_cer(hyp: str, ref: str, variant_dict=None) -> Optional[float]:
    """가설 텍스트와 정답 텍스트의 CER. 정답이 비면 None.

    줄바꿈·공백은 글자로 세지 않는다 — L2와 L4는 줄 나눔 규칙이 다르다.
    """
    from core.alignment import MatchType, align_texts

    h = "".join(hyp.split())
    r = "".join(ref.split())
    if not r:
        return None
    pairs = align_texts(h, r, variant_dict=variant_dict)
    errors = sum(
        1
        for p in pairs
        if p.match_type in (MatchType.MISMATCH, MatchType.INSERTION, MatchType.DELETION)
    )
    return round(errors / len(r), 4)


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError):
        return None


def _reference_text(doc_path: Path, part_id: str, page: int) -> Optional[str]:
    """정답 = 교정이 적용된 L4. 없으면 L4 원문. 둘 다 없으면 None."""
    try:
        from core.document import get_corrected_text

        corrected = get_corrected_text(doc_path, part_id, page)
        text = corrected.get("corrected_text") or ""
        if text.strip():
            return text
    except Exception:  # noqa: BLE001 — 교정 기록이 없으면 원문으로
        pass
    l4 = doc_path / "L4_text" / "pages" / f"{part_id}_page_{page:03d}.txt"
    if l4.exists():
        text = l4.read_text(encoding="utf-8")
        return text if text.strip() else None
    return None


def evaluate_page(doc_path: Path, part_id: str, page: int, variant_dict=None) -> PageCer:
    """한 쪽의 L2(및 초안) CER을 잰다."""
    from ocr.correction_pass import block_text, compose_page_text, load_draft

    l2 = _read_json(doc_path / "L2_ocr" / f"{part_id}_page_{page:03d}.json")
    ref = _reference_text(doc_path, part_id, page)
    engine = (l2 or {}).get("ocr_engine")
    if l2 is None:
        return PageCer(page, engine, 0, None, note="L2 없음")
    if ref is None:
        return PageCer(page, engine, 0, None, note="L4 확정본 없음 — 측정 불가")

    l2_text = "\n".join(block_text(r) for r in l2.get("ocr_results") or [])
    ref_chars = len("".join(ref.split()))
    result = PageCer(page, engine, ref_chars, compute_cer(l2_text, ref, variant_dict))

    draft = load_draft(doc_path, part_id, page)
    if draft:
        # 자동 수용된 블록만 넣은 텍스트 — 일괄 OCR이 실제로 L4에 쓰는 것과 같은 규칙
        draft_text = compose_page_text(l2, draft)
        result.draft_cer = compute_cer(draft_text, ref, variant_dict)
        result.draft_mode = draft.get("mode")
    return result


def evaluate_part(
    doc_path: Path,
    doc_id: str,
    part_id: str,
    pages: Optional[list[int]] = None,
    variant_dict=None,
) -> CerReport:
    """권 하나(또는 지정한 쪽들)의 보고서. pages가 None이면 L2가 있는 모든 쪽."""
    if pages is None:
        l2_dir = doc_path / "L2_ocr"
        pages = sorted(
            int(p.stem.rsplit("_page_", 1)[1])
            for p in l2_dir.glob(f"{part_id}_page_*.json")
            if p.stem.rsplit("_page_", 1)[1].isdigit()
        )
    report = CerReport(doc_id=doc_id, part_id=part_id)
    for page in pages:
        report.pages.append(evaluate_page(doc_path, part_id, page, variant_dict))
    return report


def format_table(report: CerReport) -> str:
    """사람이 읽는 표. 쪽별 한 줄 + 요약."""
    lines = [f"문헌 {report.doc_id} / 권 {report.part_id}", ""]
    lines.append(f"{'쪽':>4}  {'엔진':<16}{'정답글자':>8}  {'L2 CER':>8}  {'초안 CER':>8}  비고")
    for p in report.pages:
        l2 = f"{p.l2_cer:.1%}" if p.l2_cer is not None else "-"
        dr = f"{p.draft_cer:.1%}" if p.draft_cer is not None else "-"
        lines.append(
            f"{p.page:>4}  {(p.engine or '-'):<16}{p.ref_chars:>8}  {l2:>8}  {dr:>8}  {p.note}"
        )
    s = report.summary()
    lines.append("")
    lines.append(f"측정 {s['measured_pages']}쪽 · 건너뜀 {s['skipped_pages']}쪽")
    for eng, v in s["engines"].items():
        cer = f"{v['cer']:.1%}" if v["cer"] is not None else "-"
        lines.append(f"  {eng:<16} {v['pages']}쪽 {v['ref_chars']}자  CER {cer}")
    if "draft" in s:
        d = s["draft"]
        lines.append(f"  교정 초안 적용 시   {d['pages']}쪽 {d['ref_chars']}자  CER {d['cer']:.1%}")
    return "\n".join(lines)
