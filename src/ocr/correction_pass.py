"""LLM 교정 패스 — 승급 사다리의 1·2단계 (D-082).

사다리:
    0단계  엔진 OCR (Paddle·NDL)                        → L2
    1단계  LLM 교정: 블록 이미지 + 엔진 결과(앵커), 사고 끔  ← 이 모듈 (mode="fast")
    2단계  LLM 정밀 판독: + 앞뒤 문맥, 사고 켬·예산 분리     ← 이 모듈 (mode="precise")
    3단계  사람

이 모듈이 하는 일:
    1. select_candidates()  — 어느 블록을 다시 볼지 **기계적으로** 고른다. LLM을 부르지 않는다.
    2. run_correction()     — 고른 블록을 LLM Vision으로 다시 읽는다. L2는 건드리지 않고
                              초안(draft)으로 저장한다. 앵커(L2 텍스트)와의 정렬 결과를 함께 준다.
    3. apply_draft()        — 사람이(또는 자동 수용 기준이) 받아들인 블록만 L4에 쓴다.
    4. rejected_block_ids() · list_review_pages() — 사다리의 «이음». 1단계에서 떨어진
       블록을 2단계로 올릴 목록과, 일괄 실행 뒤 사람이 볼 쪽 목록을 준다.

초안은 쪽마다 파일 하나이고 **블록 단위로 병합된다** (2026-09-18). 정밀 판독을 블록 하나에
돌려도 같은 쪽의 다른 블록 결과는 남는다. 한 블록에 1단계 결과가 있는 채로 2단계를 돌리면
1단계 답을 `stage1`에 보관하고, 2단계의 수용 기준은 앵커가 아니라 **두 단계의 일치**다
(D-082 표의 2단계 «1·2단계 일치»). 두 답이 다르면 둘 다 사람에게 보인다.

왜 L2를 덮지 않는가:
    L2는 엔진이 본 것의 기록이다. 교정본이 더 나쁠 수 있고(D-065), 그때 돌아갈 곳이
    L2다. 교정 결과는 L4 초안이고, 정렬 엔진이 둘의 차이를 보여 준다.

행초(行草):
    흘림체는 자형 하나로는 풀리지 않는다. precise 모드는 같은 쪽의 앞뒤 블록 텍스트와
    앞뒤 쪽의 확정본(있으면)을 함께 넘기고 사고를 켠다. 모델이 이미지와 문맥을 동시에
    놓고 추론해야 «이 획이 무엇인가»가 정리된다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─── 선별 기준 (기계적, LLM 없음) ────────────────────────────────

# 엔진 신뢰도가 이 아래면 다시 본다. Paddle·NDL은 글자별 실제 확률을 낸다.
DEFAULT_CONFIDENCE_THRESHOLD = 0.85

# 엔진이 약한 블록 종류. 협주는 작은 글자 쌍행, 방주는 여백의 흘림체가 많다.
WEAK_BLOCK_TYPES = ("annotation", "marginal_note")

# 한글을 인식하지 못하는 엔진 (routers/llm_ocr.py의 HANGUL_INCAPABLE_ENGINES와 같은 목록).
# 라우터에서 import하면 순환이 되므로 여기 한 번 더 둔다 — 두 곳이 어긋나면
# tests/test_correction_pass.py가 잡는다.
HANGUL_INCAPABLE_ENGINES = ("ndlocr", "ndlkotenocr", "ndlkotenocr-full", "honkoku")

# 1단계 자동 수용 기준: 앵커와의 글자 일치율(exact+variant)이 이 이상이고 [?]가 없으면
# 사람 검토 없이 받아들인다. 그 아래면 2단계 또는 사람으로 올라간다.
DEFAULT_ACCEPT_AGREEMENT = 0.90

DRAFT_DIRNAME = "correction_drafts"


@dataclass
class Candidate:
    """다시 볼 블록 하나와 그 이유들."""

    block_id: str
    reasons: list[str] = field(default_factory=list)
    avg_confidence: Optional[float] = None
    block_type: Optional[str] = None
    anchor_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _block_confidence(ocr_result: dict) -> Optional[float]:
    """L2 블록 결과의 글자 평균 신뢰도. 글자 신뢰도가 하나도 없으면 None(모른다)."""
    confs: list[float] = []
    for line in ocr_result.get("lines") or []:
        for ch in line.get("characters") or []:
            c = ch.get("confidence")
            if isinstance(c, (int, float)):
                confs.append(float(c))
    if not confs:
        return None
    return sum(confs) / len(confs)


def block_text(ocr_result: dict) -> str:
    """L2 블록 결과의 줄 텍스트를 줄바꿈으로 이어 붙인다 (앵커용)."""
    return "\n".join((ln.get("text") or "") for ln in (ocr_result.get("lines") or []))


def _has_hangul(text: str) -> bool:
    return any("가" <= ch <= "힣" or "ㄱ" <= ch <= "ㆎ" for ch in text)


def select_candidates(
    l2_page: dict,
    layout: Optional[dict],
    *,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    document_language: Optional[str] = None,
    force_block_ids: Optional[list[str]] = None,
    select_all: bool = False,
) -> list[Candidate]:
    """1단계 입구 — 어느 블록을 LLM에 넘길지 고른다. LLM을 부르지 않는다.

    입력:
      l2_page             — L2 OCR 쪽 JSON (ocr_results, ocr_engine).
      layout              — L3 레이아웃 (block_type을 본다). None 허용.
      confidence_threshold— 엔진 평균 신뢰도가 이 아래면 후보.
      document_language   — 서지의 language. korean/mixed이고 엔진이 한글을 못 읽으면 전부 후보.
      force_block_ids     — 사람이 지정한 블록. 이유 «user»로 무조건 후보.
      select_all          — 전량 (표본 감사·«전체» 모드).
    출력: Candidate 목록 (L2 순서). 이유가 없는 블록은 빠진다.

    기준은 전부 이미 있는 데이터다. 신뢰도가 높은데 틀린 경우는 여기서 안 잡힌다 —
    그것은 표본 감사(select_all로 일부 무작위 쪽)와 D-084의 CER이 맡는다.
    """
    engine = (l2_page.get("ocr_engine") or "").strip()
    types_by_id: dict[str, str] = {}
    for b in (layout or {}).get("blocks", []) or []:
        if b.get("block_id"):
            types_by_id[b["block_id"]] = b.get("block_type") or ""
    forced = set(force_block_ids or [])
    hangul_gap = engine in HANGUL_INCAPABLE_ENGINES and (document_language or "") in (
        "korean",
        "mixed",
    )

    out: list[Candidate] = []
    for r in l2_page.get("ocr_results") or []:
        bid = str(r.get("layout_block_id") or "").strip()
        if not bid:
            continue
        cand = Candidate(
            block_id=bid,
            avg_confidence=_block_confidence(r),
            block_type=types_by_id.get(bid) or None,
            anchor_text=block_text(r),
        )
        if select_all:
            cand.reasons.append("all")
        if bid in forced:
            cand.reasons.append("user")
        if cand.avg_confidence is not None and cand.avg_confidence < confidence_threshold:
            cand.reasons.append(f"low_confidence<{confidence_threshold:g}")
        if cand.block_type in WEAK_BLOCK_TYPES:
            cand.reasons.append(f"block_type:{cand.block_type}")
        if hangul_gap:
            cand.reasons.append(f"hangul_incapable_engine:{engine}")
        elif engine in HANGUL_INCAPABLE_ENGINES and _has_hangul(cand.anchor_text):
            # 언어 정보가 없어도 결과에 한글 조각이 섞여 있으면 한글 문헌이다.
            cand.reasons.append(f"hangul_incapable_engine:{engine}")
        if cand.reasons:
            out.append(cand)
    return out


# ─── 문맥 조립 ───────────────────────────────────────────────────

CONTEXT_CHARS = 200


def build_context(
    l2_page: dict,
    block_id: str,
    *,
    prev_page_text: Optional[str] = None,
    next_page_text: Optional[str] = None,
    precise: bool = False,
) -> tuple[str, str]:
    """이 블록 앞뒤의 문맥 텍스트를 만든다.

    fast 모드: 같은 쪽에서 바로 앞·뒤 블록의 텍스트.
    precise 모드: 같은 쪽의 모든 앞 블록·뒤 블록 + 앞 쪽 확정본 끝부분·뒤 쪽 확정본 첫부분.
                  행초처럼 자형만으로 안 풀리는 곳에 «앞뒤를 최대한» 준다 (D-082).
    출력: (context_before, context_after). 각각 CONTEXT_CHARS 안으로 자른다.
    """
    results = l2_page.get("ocr_results") or []
    idx = next(
        (i for i, r in enumerate(results) if str(r.get("layout_block_id") or "") == block_id),
        None,
    )
    if idx is None:
        return "", ""
    if precise:
        before_parts = [block_text(r) for r in results[:idx]]
        after_parts = [block_text(r) for r in results[idx + 1 :]]
        if prev_page_text:
            before_parts.insert(0, prev_page_text.strip())
        if next_page_text:
            after_parts.append(next_page_text.strip())
    else:
        before_parts = [block_text(results[idx - 1])] if idx > 0 else []
        after_parts = [block_text(results[idx + 1])] if idx + 1 < len(results) else []
    before = "\n".join(p for p in before_parts if p).replace("\n", " ").strip()
    after = "\n".join(p for p in after_parts if p).replace("\n", " ").strip()
    return before[-CONTEXT_CHARS:], after[:CONTEXT_CHARS]


def llm_kwargs_for_mode(
    mode: str,
    *,
    thinking_budget: Optional[int] = None,
    force_provider: Optional[str] = None,
    force_model: Optional[str] = None,
) -> dict:
    """모드별 LLM 엔진 인자. fast는 사고 끔, precise는 사고 켬 + 예산 분리 (D-083)."""
    kw: dict = {"think": False}
    if mode == "precise":
        kw["think"] = True
        if thinking_budget:
            kw["thinking_budget"] = int(thinking_budget)
    if force_provider:
        kw["force_provider"] = force_provider
    if force_model:
        kw["force_model"] = force_model
    return kw


# ─── 실행 ────────────────────────────────────────────────────────


def draft_path(doc_path: Path, part_id: str, page_number: int) -> Path:
    """초안 파일 경로. L4_text/correction_drafts/{part}_page_{NNN}.json."""
    return Path(doc_path) / "L4_text" / DRAFT_DIRNAME / f"{part_id}_page_{page_number:03d}.json"


def load_draft(doc_path: Path, part_id: str, page_number: int) -> Optional[dict]:
    path = draft_path(doc_path, part_id, page_number)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning(f"교정 초안을 읽지 못했습니다: {path} — {e}")
        return None


def evaluate_block(
    anchor_text: str,
    corrected_lines: list[dict],
    variant_dict=None,
    *,
    accept_agreement: float = DEFAULT_ACCEPT_AGREEMENT,
) -> dict:
    """교정 결과 한 블록을 앵커와 대조해 수용 여부를 판정한다.

    입력: anchor_text — L2 텍스트. corrected_lines — LLM 결과 lines (text·characters).
          variant_dict — 정렬용 사전(TieredVariantDicts 등). None 허용.
    출력: {corrected_text, agreement, uncertain_count, illegible_count, accepted, pairs}
      agreement       — 앵커 글자 중 exact+variant 비율 (0~1). 앵커가 비면 0.
      uncertain_count — 신뢰도가 0.9 미만인 글자 수 ([?] 표시된 글자).
      accepted        — agreement ≥ 기준이고 uncertain이 0이면 True (1단계 자동 수용).
    """
    from core.alignment import MatchType, align_texts

    corrected_text = "\n".join((ln.get("text") or "") for ln in corrected_lines)
    a = anchor_text.replace("\n", "")
    c = corrected_text.replace("\n", "")
    pairs = align_texts(a, c, variant_dict=variant_dict) if (a or c) else []
    ok = sum(1 for p in pairs if p.match_type in (MatchType.EXACT, MatchType.VARIANT))
    denom = max(len(a), len(c), 1)
    agreement = ok / denom

    uncertain = 0
    illegible = 0
    for ln in corrected_lines:
        for ch in ln.get("characters") or []:
            conf = ch.get("confidence")
            if ch.get("char") == "□":
                illegible += 1
            elif isinstance(conf, (int, float)) and conf < 0.9:
                uncertain += 1

    return {
        "corrected_text": corrected_text,
        "agreement": round(agreement, 4),
        "uncertain_count": uncertain,
        "illegible_count": illegible,
        "accepted": agreement >= accept_agreement and uncertain == 0 and bool(c),
        "pairs": [p.to_dict() for p in pairs],
    }


def text_agreement(a: str, b: str, variant_dict=None) -> float:
    """두 텍스트의 글자 일치율 (exact+variant ÷ 긴 쪽 길이). 둘 다 비면 0.

    1단계와 2단계의 답을 견주는 데 쓴다 — evaluate_block이 앵커와 교정본을 견주는 것과
    같은 잣대라, «앵커와 90% 일치»와 «두 단계가 90% 일치»가 같은 뜻이 된다.
    """
    from core.alignment import MatchType, align_texts

    a = (a or "").replace("\n", "")
    b = (b or "").replace("\n", "")
    if not a and not b:
        return 0.0
    pairs = align_texts(a, b, variant_dict=variant_dict)
    ok = sum(1 for p in pairs if p.match_type in (MatchType.EXACT, MatchType.VARIANT))
    return round(ok / max(len(a), len(b), 1), 4)


def _judge_stage2(entry: dict, stage1: Optional[dict], variant_dict=None) -> None:
    """2단계 결과의 수용 판정 (제자리에서 entry를 고친다).

    1단계 답이 있으면 D-082 표대로 **두 단계의 일치**로 판정한다 — 앵커(엔진 결과)와의
    일치는 참고값으로만 남긴다. 사고를 켜고 문맥을 넓혀 읽은 답이 사고 없이 읽은 답과
    같으면 그 글자는 이미지가 그렇게 생긴 것이고, 다르면 사람이 둘을 보고 골라야 한다.
    1단계 답이 없으면(사람이 곧장 정밀 판독을 눌렀다) 앵커 기준을 그대로 쓴다.
    """
    if entry.get("error") or not stage1 or not stage1.get("corrected_text"):
        entry["accept_basis"] = "anchor"
        return
    entry["stage1"] = {
        "corrected_text": stage1.get("corrected_text", ""),
        "agreement": stage1.get("agreement"),
        "uncertain_count": stage1.get("uncertain_count"),
    }
    agree = text_agreement(stage1.get("corrected_text", ""), entry.get("corrected_text", ""), variant_dict)
    entry["stages_agreement"] = agree
    entry["accept_basis"] = "stages"
    entry["accepted"] = (
        agree >= DEFAULT_ACCEPT_AGREEMENT
        and not entry.get("uncertain_count")
        and not entry.get("illegible_count")
        and bool(entry.get("corrected_text"))
    )


def merge_draft(existing: Optional[dict], fresh: dict) -> dict:
    """새 실행 결과(fresh)를 기존 초안(existing) 위에 **블록 단위로** 얹는다.

    왜: 예전에는 실행마다 초안 파일을 통째로 다시 썼다. 1단계로 블록 둘을 본 뒤 블록
    하나에 정밀 판독을 돌리면 나머지 블록의 결과가 사라졌고, «적용한 블록» 기록도 함께
    없어졌다(2026-09-17 재현). 같은 block_id는 새 결과로 바꾸고, 없는 블록은 그대로 둔다.
    출력: 병합된 초안. mode는 마지막 실행의 것, applied_blocks는 합집합.
    """
    if not existing:
        return fresh
    by_id = {b.get("block_id"): b for b in existing.get("blocks", [])}
    order = [b.get("block_id") for b in existing.get("blocks", [])]
    for b in fresh.get("blocks", []):
        bid = b.get("block_id")
        if bid not in by_id:
            order.append(bid)
        by_id[bid] = b
    merged = dict(fresh)
    merged["blocks"] = [by_id[bid] for bid in order]
    merged["applied_blocks"] = sorted(
        set(existing.get("applied_blocks") or []) | set(fresh.get("applied_blocks") or [])
    )
    return merged


def rejected_block_ids(draft: dict) -> list[str]:
    """사다리에서 다음 단계로 올릴 블록 — 결과는 있는데 자동 수용을 못 받은 것.

    오류가 난 블록은 올리지 않는다(같은 오류를 비싼 단계에서 되풀이한다). 이미 적용된
    블록도 올리지 않는다(사람이 이미 골랐다).
    """
    applied = set(draft.get("applied_blocks") or [])
    out = []
    for b in draft.get("blocks", []):
        if b.get("error") or b.get("accepted") or b.get("block_id") in applied:
            continue
        out.append(b["block_id"])
    return out


def draft_status(draft: Optional[dict]) -> dict:
    """초안 한 장의 셈: 사람이 볼 것(pending)·자동 수용(accepted)·적용됨(applied)·오류.

    «pending»이 사람 단계(3단계)의 입구다 — 결과는 있는데 자동 수용도 적용도 안 된 블록.
    """
    if not draft:
        return {"pending": 0, "accepted": 0, "applied": 0, "errors": 0, "blocks": 0}
    applied = set(draft.get("applied_blocks") or [])
    pending = accepted = errors = 0
    for b in draft.get("blocks", []):
        bid = b.get("block_id")
        if b.get("error"):
            errors += 1
        elif bid in applied:
            continue
        elif b.get("accepted"):
            accepted += 1
        elif b.get("corrected_text"):
            pending += 1
    return {
        "pending": pending,
        "accepted": accepted,
        "applied": len(applied),
        "errors": errors,
        "blocks": len(draft.get("blocks", [])),
    }


def list_review_pages(doc_path: Path, part_id: str) -> list[dict]:
    """한 권에서 사람이 볼 초안이 있는 쪽 목록 (쪽 번호 순).

    일괄 실행이 끝난 뒤 «어느 쪽을 열어야 하나»에 답한다. 초안 파일을 하나씩 읽어
    pending·errors가 있는 쪽만 돌려준다. 파일이 깨졌으면 그 쪽은 건너뛴다(load_draft가
    경고를 남긴다).
    출력: [{"page": n, "pending": p, "accepted": a, "applied": d, "errors": e, "mode": m}]
    """
    drafts_dir = Path(doc_path) / "L4_text" / DRAFT_DIRNAME
    if not drafts_dir.exists():
        return []
    out = []
    prefix = f"{part_id}_page_"
    for path in sorted(drafts_dir.glob(f"{prefix}*.json")):
        try:
            page = int(path.stem[len(prefix) :])
        except ValueError:
            continue
        draft = load_draft(doc_path, part_id, page)
        st = draft_status(draft)
        if st["pending"] or st["errors"]:
            out.append({"page": page, "mode": (draft or {}).get("mode"), **st})
    return out


def mark_applied(doc_path: Path, part_id: str, page_number: int, block_ids: list[str]) -> None:
    """초안의 applied_blocks에 블록을 더해 저장한다.

    일괄 OCR이 compose_page_text로 자동 수용 블록을 L4에 넣을 때 부른다 — 적지 않으면
    검토 목록이 이미 들어간 블록을 «자동 수용됐는데 안 적용됨»으로 다시 센다.
    """
    draft = load_draft(doc_path, part_id, page_number)
    if not draft or not block_ids:
        return
    from core.document import write_json_atomic

    draft["applied_blocks"] = sorted(set(draft.get("applied_blocks") or []) | set(block_ids))
    write_json_atomic(draft_path(doc_path, part_id, page_number), draft)


def run_correction(
    pipeline,
    engine,
    doc_path: Path,
    doc_id: str,
    part_id: str,
    page_number: int,
    candidates: list[Candidate],
    *,
    mode: str = "fast",
    llm_kwargs: Optional[dict] = None,
    variant_dict=None,
    variant_hint_pairs: Optional[list] = None,
    prev_page_text: Optional[str] = None,
    next_page_text: Optional[str] = None,
    save: bool = True,
    fresh: bool = False,
) -> dict:
    """후보 블록들을 LLM으로 다시 읽어 초안을 만든다. L2는 건드리지 않는다.

    입력:
      pipeline  — OcrPipeline (prepare_page·recognize_block을 쓴다).
      engine    — LLM Vision 엔진 (registry.get_engine("llm_vision")).
      candidates— select_candidates() 결과.
      mode      — "fast"(사고 끔) | "precise"(사고 켬·문맥 확대).
      llm_kwargs— llm_kwargs_for_mode() 결과.
      variant_dict / variant_hint_pairs — 정렬 사전과 프롬프트 자형 주의 목록 (D-080·D-081).
      prev/next_page_text — precise 모드의 앞뒤 쪽 확정본.
      fresh     — True면 기존 초안을 버리고 새로 시작한다. 일괄 OCR이 L2를 새로 만든 직후에
                  쓴다 — 옛 초안의 앵커는 새 L2와 맞지 않는다.
    출력: 초안 dict(기존 초안과 **블록 단위로 병합**된 것) —
          {doc_id, part_id, page, mode, engine, created_at, applied_blocks,
           blocks: [{block_id, stage, reasons, anchor_text, corrected_text, agreement,
                     uncertain_count, accepted, accept_basis, lines, pairs,
                     stage1?, stages_agreement?, error?}]}
    """
    draft = {
        "doc_id": doc_id,
        "part_id": part_id,
        "page": page_number,
        "mode": mode,
        "engine": getattr(engine, "engine_id", "llm_vision"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "blocks": [],
    }
    existing = None if fresh else load_draft(doc_path, part_id, page_number)
    if not candidates:
        # 다시 볼 블록이 없으면 이미지도 열지 않고 초안 파일도 만들지 않는다.
        # 빈 초안이 남으면 eval_cer가 «교정 초안이 있는 쪽»으로 세어 통계가 부푼다.
        return merge_draft(existing, draft)
    prior_by_id = {b.get("block_id"): b for b in (existing or {}).get("blocks", [])}

    l2_path = Path(doc_path) / "L2_ocr" / f"{part_id}_page_{page_number:03d}.json"
    l2_page = json.loads(l2_path.read_text(encoding="utf-8")) if l2_path.exists() else {}

    wanted = {c.block_id for c in candidates}
    prepared = pipeline.prepare_page(doc_id, part_id, page_number, sorted(wanted))
    if prepared.error:
        raise RuntimeError(prepared.error)
    blocks_by_id = {b.get("block_id"): b for b in prepared.blocks}
    for cand in candidates:
        block = blocks_by_id.get(cand.block_id)
        entry = {
            "block_id": cand.block_id,
            "stage": mode,
            "reasons": cand.reasons,
            "anchor_text": cand.anchor_text,
        }
        if block is None or block.get("skip"):
            entry["error"] = "레이아웃에 없는 블록이거나 skip 표시된 블록입니다."
            draft["blocks"].append(entry)
            continue
        before, after = build_context(
            l2_page,
            cand.block_id,
            prev_page_text=prev_page_text,
            next_page_text=next_page_text,
            precise=(mode == "precise"),
        )
        kwargs = dict(llm_kwargs or {})
        kwargs.update(
            anchor_text=cand.anchor_text or None,
            context_before=before or None,
            context_after=after or None,
            variant_hints=variant_hint_pairs or None,
        )
        try:
            ocr_dict = pipeline.recognize_block(engine, prepared.page_image, block, **kwargs)
            lines = ocr_dict.get("lines") or []
            entry.update(evaluate_block(cand.anchor_text, lines, variant_dict))
            entry["lines"] = lines
            entry["accept_basis"] = "anchor"
            if mode == "precise":
                # 같은 블록에 1단계 답이 있으면 2단계 판정은 «두 단계의 일치»다.
                prior = prior_by_id.get(cand.block_id)
                stage1 = prior if prior and prior.get("stage", "fast") == "fast" else None
                _judge_stage2(entry, stage1, variant_dict)
        except Exception as e:  # noqa: BLE001 — 한 블록 실패로 쪽 전체를 버리지 않는다
            entry["error"] = str(e)
            entry["accepted"] = False
        draft["blocks"].append(entry)

    merged = merge_draft(existing, draft)
    if save:
        from core.document import write_json_atomic

        write_json_atomic(draft_path(doc_path, part_id, page_number), merged)
    return merged


def compose_page_text(l2_page: dict, draft: Optional[dict], block_ids: Optional[set] = None) -> str:
    """L2 순서대로 쪽 텍스트를 만들되, 초안에서 받아들인 블록은 교정본으로 바꾼다.

    입력: l2_page — L2 쪽 JSON. draft — run_correction 결과(None이면 L2만).
          block_ids — 적용할 블록 집합. None이면 draft에서 accepted=True인 블록.
    출력: 블록 사이는 빈 줄, 블록 안은 줄바꿈 — 일괄 OCR의 L4 채우기와 같은 모양.
    """
    replacements: dict[str, str] = {}
    for b in (draft or {}).get("blocks", []):
        if b.get("error") or not b.get("corrected_text"):
            continue
        if block_ids is not None:
            if b["block_id"] in block_ids:
                replacements[b["block_id"]] = b["corrected_text"]
        elif b.get("accepted"):
            replacements[b["block_id"]] = b["corrected_text"]
    parts = []
    for r in l2_page.get("ocr_results") or []:
        bid = str(r.get("layout_block_id") or "")
        parts.append(replacements.get(bid, block_text(r)))
    return "\n\n".join(p for p in parts if p is not None)


def apply_draft(
    doc_path: Path, part_id: str, page_number: int, block_ids: Optional[list[str]]
) -> dict:
    """초안의 블록을 **현재 L4 위에** 적용한다. block_ids가 None이면 accepted 블록만.

    출력: {"applied_blocks": [...], "not_found_blocks": [...], "text_length": N}

    왜 L2에서 다시 조립하지 않는가:
        예전 구현은 L2 텍스트 + 이번에 고른 블록으로 쪽 전체를 다시 만들어 덮어썼다.
        그러면 «적용»을 두 번째 누를 때 첫 번째 적용이 되돌아가고, 연구자가 L4
        편집기에서 손으로 고친 것도 사라진다. 그래서 지금 L4를 읽어 그 블록의
        엔진 원문(앵커)만 교정본으로 바꾼다. 앵커를 못 찾으면(이미 손으로 고쳤거나
        구조가 달라졌으면) 건드리지 않고 not_found로 알린다.
        L4가 아직 비어 있을 때만 L2 기준으로 조립한다.

    적용한 블록 목록은 초안 파일의 applied_blocks에 누적된다.
    """
    from core.document import get_page_text, save_page_text, write_json_atomic

    l2_path = Path(doc_path) / "L2_ocr" / f"{part_id}_page_{page_number:03d}.json"
    if not l2_path.exists():
        raise FileNotFoundError(f"L2 OCR 결과가 없습니다: {l2_path}")
    l2_page = json.loads(l2_path.read_text(encoding="utf-8"))
    draft = load_draft(doc_path, part_id, page_number)
    if draft is None:
        raise FileNotFoundError("교정 초안이 없습니다. 먼저 LLM 교정을 실행하세요.")

    entries = {
        b["block_id"]: b
        for b in draft.get("blocks", [])
        if not b.get("error") and b.get("corrected_text")
    }
    if block_ids is not None:
        chosen = [bid for bid in block_ids if bid in entries]
    else:
        chosen = [bid for bid, b in entries.items() if b.get("accepted")]
    already = set(draft.get("applied_blocks") or [])

    try:
        current = get_page_text(doc_path, part_id, page_number).get("text") or ""
    except Exception:  # noqa: BLE001 — 매니페스트가 없어도 L4 파일 유무로 판단한다
        l4 = Path(doc_path) / "L4_text" / "pages" / f"{part_id}_page_{page_number:03d}.txt"
        current = l4.read_text(encoding="utf-8") if l4.exists() else ""

    applied: list[str] = []
    not_found: list[str] = []
    if not current.strip():
        # L4가 비어 있다 — L2 기준으로 조립 (이전에 적용한 블록 + 이번 선택)
        text = compose_page_text(l2_page, draft, already | set(chosen))
        applied = [bid for bid in chosen if bid in entries]
    else:
        text = current
        anchors = {
            str(r.get("layout_block_id") or ""): block_text(r)
            for r in l2_page.get("ocr_results") or []
        }
        for bid in chosen:
            corrected = entries[bid]["corrected_text"]
            anchor = anchors.get(bid, "")
            if anchor and anchor in text:
                text = text.replace(anchor, corrected, 1)
                applied.append(bid)
            elif bid in already or (corrected and corrected in text):
                applied.append(bid)  # 이미 적용되어 있다
            else:
                not_found.append(bid)

    save_page_text(doc_path, part_id, page_number, text)
    draft["applied_blocks"] = sorted(already | set(applied))
    write_json_atomic(draft_path(doc_path, part_id, page_number), draft)
    return {"applied_blocks": applied, "not_found_blocks": not_found, "text_length": len(text)}
