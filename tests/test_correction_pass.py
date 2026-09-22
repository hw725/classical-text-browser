"""LLM 교정 패스 테스트 (D-082).

무엇을 고정하는가:
  - 선별은 기계적이다: 낮은 신뢰도·약한 블록 종류·한글 미지원 엔진·사용자 지정·전량
  - 문맥 조립: fast는 앞뒤 블록 하나, precise는 쪽 전체 + 앞뒤 쪽 확정본
  - 모드별 LLM 인자: fast는 사고 끔, precise는 사고 켬 + 예산
  - 평가: 앵커와의 일치율·[?] 수로 자동 수용 판정
  - run_correction은 L2를 건드리지 않고 초안만 쓰며, 앵커·문맥·자형 주의를 엔진에 넘긴다
  - compose/apply: 수용된 블록만 교정본으로 바꿔 L4에 쓴다
  - 한글 미지원 엔진 목록이 라우터의 것과 같다 (두 곳이 어긋나면 여기서 잡힌다)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ocr.base import BaseOcrEngine, OcrBlockResult, OcrCharResult, OcrLineResult  # noqa: E402
from ocr.correction_pass import (  # noqa: E402
    HANGUL_INCAPABLE_ENGINES,
    apply_draft,
    build_context,
    compose_page_text,
    draft_path,
    evaluate_block,
    llm_kwargs_for_mode,
    run_correction,
    select_candidates,
)
from ocr.pipeline import OcrPipeline  # noqa: E402
from ocr.registry import OcrEngineRegistry  # noqa: E402


def _l2(engine="paddleocr"):
    def block(bid, text, conf):
        return {
            "layout_block_id": bid,
            "lines": [
                {
                    "text": text,
                    "characters": [{"char": ch, "confidence": conf} for ch in text],
                }
            ],
        }

    return {
        "ocr_engine": engine,
        "ocr_results": [
            block("b1", "王戎簡要", 0.97),
            block("b2", "裴楷清通", 0.60),
            block("b3", "孔明卧龍", 0.95),
        ],
    }


LAYOUT = {
    "blocks": [
        {"block_id": "b1", "block_type": "main_text"},
        {"block_id": "b2", "block_type": "main_text"},
        {"block_id": "b3", "block_type": "annotation"},
    ]
}


class TestSelectCandidates:
    def test_low_confidence_and_weak_type(self):
        cands = {c.block_id: c for c in select_candidates(_l2(), LAYOUT)}
        assert "b1" not in cands
        assert any(r.startswith("low_confidence") for r in cands["b2"].reasons)
        assert "block_type:annotation" in cands["b3"].reasons
        assert cands["b2"].anchor_text == "裴楷清通"

    def test_user_forced(self):
        cands = select_candidates(_l2(), LAYOUT, force_block_ids=["b1"])
        assert any(c.block_id == "b1" and "user" in c.reasons for c in cands)

    def test_select_all(self):
        cands = select_candidates(_l2(), LAYOUT, select_all=True)
        assert [c.block_id for c in cands] == ["b1", "b2", "b3"]

    def test_hangul_incapable_engine_with_korean_document(self):
        cands = select_candidates(_l2(engine="ndlocr"), None, document_language="korean")
        assert len(cands) == 3
        assert all(any(r.startswith("hangul_incapable_engine") for r in c.reasons) for c in cands)

    def test_hangul_fragment_without_language(self):
        l2 = _l2(engine="ndlkotenocr")
        l2["ocr_results"][0]["lines"][0]["text"] = "王戎ㄱ簡"
        cands = {c.block_id: c for c in select_candidates(l2, None)}
        assert "b1" in cands

    def test_no_confidence_is_unknown_not_low(self):
        l2 = {
            "ocr_engine": "x",
            "ocr_results": [{"layout_block_id": "b1", "lines": [{"text": "甲"}]}],
        }
        assert select_candidates(l2, None) == []

    def test_engine_list_matches_router(self):
        from app.routers.llm_ocr import HANGUL_INCAPABLE_ENGINES as ROUTER_LIST

        assert tuple(ROUTER_LIST) == tuple(HANGUL_INCAPABLE_ENGINES)


class TestContextAndMode:
    def test_fast_context_is_neighbors(self):
        before, after = build_context(_l2(), "b2")
        assert before == "王戎簡要" and after == "孔明卧龍"

    def test_precise_context_includes_pages(self):
        before, after = build_context(
            _l2(), "b2", prev_page_text="앞쪽끝", next_page_text="뒷쪽처음", precise=True
        )
        assert before.startswith("앞쪽끝") and before.endswith("王戎簡要")
        assert after.startswith("孔明卧龍") and after.endswith("뒷쪽처음")

    def test_unknown_block(self):
        assert build_context(_l2(), "zzz") == ("", "")

    def test_mode_kwargs(self):
        assert llm_kwargs_for_mode("fast") == {"think": False}
        kw = llm_kwargs_for_mode("precise", thinking_budget=3000, force_provider="ollama")
        assert (
            kw["think"] is True
            and kw["thinking_budget"] == 3000
            and kw["force_provider"] == "ollama"
        )


class TestEvaluate:
    def _lines(self, text, confs=None):
        confs = confs or [0.9] * len(text)
        return [
            {
                "text": text,
                "characters": [{"char": c, "confidence": k} for c, k in zip(text, confs)],
            }
        ]

    def test_identical_is_accepted(self):
        r = evaluate_block("王戎簡要", self._lines("王戎簡要"))
        assert r["agreement"] == 1.0 and r["accepted"] is True

    def test_uncertain_blocks_acceptance(self):
        r = evaluate_block("王戎簡要", self._lines("王戎簡要", [0.9, 0.5, 0.9, 0.9]))
        assert r["uncertain_count"] == 1 and r["accepted"] is False

    def test_low_agreement_not_accepted(self):
        r = evaluate_block("王戎簡要", self._lines("甲乙丙丁"))
        assert r["agreement"] == 0.0 and r["accepted"] is False
        assert len(r["pairs"]) == 4

    def test_empty_correction_not_accepted(self):
        r = evaluate_block("王戎", self._lines(""))
        assert r["accepted"] is False


# ─── run_correction / apply (더미 엔진·임시 서고) ─────────────────


class _EchoLlmEngine(BaseOcrEngine):
    """앵커를 받아 «교정본»을 돌려주는 가짜 LLM 엔진. 받은 kwargs를 기록한다."""

    engine_id = "llm_vision"
    display_name = "fake llm"
    requires_network = False

    def __init__(self, reply_by_block: dict):
        self.reply_by_block = reply_by_block
        self.calls: list[dict] = []

    def is_available(self) -> bool:
        return True

    def recognize(
        self, image_bytes, writing_direction="vertical_rtl", language="classical_chinese", **kwargs
    ):
        self.calls.append(kwargs)
        text = self.reply_by_block.get(kwargs.get("anchor_text"), kwargs.get("anchor_text") or "")
        return OcrBlockResult(
            lines=[
                OcrLineResult(
                    text=text, characters=[OcrCharResult(char=c, confidence=0.9) for c in text]
                )
            ],
            engine_id=self.engine_id,
            language=language,
            writing_direction=writing_direction,
        )


@pytest.fixture
def library(tmp_path):
    doc = tmp_path / "documents" / "doc1"
    (doc / "L1_source").mkdir(parents=True)
    Image.new("RGB", (1000, 1500), "white").save(doc / "L1_source" / "v1_page_001.png")
    (doc / "manifest.json").write_text(
        json.dumps({"document_id": "doc1", "title": "T"}), encoding="utf-8"
    )
    (doc / "L3_layout").mkdir()
    layout = {
        "part_id": "v1",
        "page_number": 1,
        "image_width": 1000,
        "image_height": 1500,
        "blocks": [
            {
                "block_id": "b1",
                "block_type": "main_text",
                "bbox": [50, 50, 300, 700],
                "reading_order": 1,
            },
            {
                "block_id": "b2",
                "block_type": "main_text",
                "bbox": [350, 50, 600, 700],
                "reading_order": 2,
            },
            {
                "block_id": "b3",
                "block_type": "annotation",
                "bbox": [650, 50, 900, 700],
                "reading_order": 3,
            },
        ],
    }
    (doc / "L3_layout" / "v1_page_001.json").write_text(json.dumps(layout), encoding="utf-8")
    (doc / "L2_ocr").mkdir()
    (doc / "L2_ocr" / "v1_page_001.json").write_text(json.dumps(_l2()), encoding="utf-8")
    return tmp_path, doc


class TestRunAndApply:
    def test_run_saves_draft_not_l2(self, library):
        root, doc = library
        engine = _EchoLlmEngine({"裴楷清通": "裴楷淸通", "孔明卧龍": "孔明臥龍"})
        registry = OcrEngineRegistry()
        registry.register(engine)
        pipeline = OcrPipeline(registry, library_root=str(root))
        l2_before = (doc / "L2_ocr" / "v1_page_001.json").read_text(encoding="utf-8")

        cands = select_candidates(
            _l2(), json.loads((doc / "L3_layout" / "v1_page_001.json").read_text())
        )
        draft = run_correction(
            pipeline,
            engine,
            doc,
            "doc1",
            "v1",
            1,
            cands,
            mode="precise",
            llm_kwargs=llm_kwargs_for_mode("precise", thinking_budget=2048),
            variant_hint_pairs=[["淸", "清"]],
            prev_page_text="앞쪽",
        )

        # L2는 그대로, 초안은 저장됨
        assert (doc / "L2_ocr" / "v1_page_001.json").read_text(encoding="utf-8") == l2_before
        assert draft_path(doc, "v1", 1).exists()
        by_id = {b["block_id"]: b for b in draft["blocks"]}
        assert set(by_id) == {"b2", "b3"}
        assert by_id["b2"]["corrected_text"] == "裴楷淸通"
        assert 0 < by_id["b2"]["agreement"] < 1  # 淸/清 한 글자 차이
        assert by_id["b3"]["corrected_text"] == "孔明臥龍"

        # 엔진에 앵커·문맥·자형 주의·사고 설정이 전달됐다
        call = next(c for c in engine.calls if c.get("anchor_text") == "裴楷清通")
        assert call["think"] is True and call["thinking_budget"] == 2048
        assert call["variant_hints"] == [["淸", "清"]]
        assert "王戎簡要" in call["context_before"] and "앞쪽" in call["context_before"]
        assert call["block_type"] == "main_text"

    def test_compose_and_apply(self, library):
        root, doc = library
        engine = _EchoLlmEngine({"裴楷清通": "裴楷清通", "孔明卧龍": "孔明臥龍"})
        registry = OcrEngineRegistry()
        registry.register(engine)
        pipeline = OcrPipeline(registry, library_root=str(root))
        cands = select_candidates(_l2(), LAYOUT)
        draft = run_correction(pipeline, engine, doc, "doc1", "v1", 1, cands)
        by_id = {b["block_id"]: b for b in draft["blocks"]}
        assert by_id["b2"]["accepted"] is True  # 동일 → 자동 수용
        assert by_id["b3"]["accepted"] is False  # 卧/臥 불일치 → 사람에게

        # 자동 수용만 적용: b3는 엔진 결과 그대로
        text = compose_page_text(_l2(), draft)
        assert text == "王戎簡要\n\n裴楷清通\n\n孔明卧龍"
        # 사람이 b3를 고르면 교정본으로
        text = compose_page_text(_l2(), draft, {"b3"})
        assert text.endswith("孔明臥龍")

        result = apply_draft(doc, "v1", 1, ["b3"])
        assert result["applied_blocks"] == ["b3"]
        saved = (doc / "L4_text" / "pages" / "v1_page_001.txt").read_text(encoding="utf-8")
        assert saved.endswith("孔明臥龍")

    def test_apply_without_draft_fails_loudly(self, library):
        _, doc = library
        with pytest.raises(FileNotFoundError):
            apply_draft(doc, "v1", 1, None)


class TestApplyPreservesPriorWork:
    def _setup(self, library):
        root, doc = library
        engine = _EchoLlmEngine({"裴楷清通": "裴楷淸通", "孔明卧龍": "孔明臥龍"})
        registry = OcrEngineRegistry()
        registry.register(engine)
        pipeline = OcrPipeline(registry, library_root=str(root))
        cands = select_candidates(_l2(), LAYOUT)
        run_correction(pipeline, engine, doc, "doc1", "v1", 1, cands)
        return doc

    def test_sequential_apply_keeps_earlier_block(self, library):
        doc = self._setup(library)
        apply_draft(doc, "v1", 1, ["b2"])
        apply_draft(doc, "v1", 1, ["b3"])
        saved = (doc / "L4_text" / "pages" / "v1_page_001.txt").read_text(encoding="utf-8")
        assert "裴楷淸通" in saved and "孔明臥龍" in saved  # 둘 다 살아 있다
        from ocr.correction_pass import load_draft

        assert load_draft(doc, "v1", 1)["applied_blocks"] == ["b2", "b3"]

    def test_manual_l4_edit_is_preserved(self, library):
        doc = self._setup(library)
        l4 = doc / "L4_text" / "pages" / "v1_page_001.txt"
        l4.parent.mkdir(parents=True, exist_ok=True)
        # 연구자가 L4를 손으로 고쳐 둔 상태 (첫 블록을 바꾸고 메모 줄을 덧붙임)
        l4.write_text("王戎簡要(손으로 고침)\n\n裴楷清通\n\n孔明卧龍\n\n[메모]", encoding="utf-8")
        result = apply_draft(doc, "v1", 1, ["b3"])
        saved = l4.read_text(encoding="utf-8")
        assert result["applied_blocks"] == ["b3"] and result["not_found_blocks"] == []
        assert saved.startswith("王戎簡要(손으로 고침)") and saved.endswith("[메모]")
        assert "孔明臥龍" in saved and "孔明卧龍" not in saved

    def test_missing_anchor_is_reported_not_overwritten(self, library):
        doc = self._setup(library)
        l4 = doc / "L4_text" / "pages" / "v1_page_001.txt"
        l4.parent.mkdir(parents=True, exist_ok=True)
        l4.write_text("전혀 다른 내용", encoding="utf-8")
        result = apply_draft(doc, "v1", 1, ["b3"])
        assert result["not_found_blocks"] == ["b3"] and result["applied_blocks"] == []
        assert l4.read_text(encoding="utf-8") == "전혀 다른 내용"

    def test_no_candidates_writes_no_draft(self, library):
        root, doc = library
        engine = _EchoLlmEngine({})
        registry = OcrEngineRegistry()
        registry.register(engine)
        pipeline = OcrPipeline(registry, library_root=str(root))
        draft = run_correction(pipeline, engine, doc, "doc1", "v1", 1, [])
        assert draft["blocks"] == []
        assert not draft_path(doc, "v1", 1).exists()
        assert engine.calls == []


# ─── 사다리의 «이음» (2026-09-18) ─────────────────────────────────────
# 무엇을 고정하는가:
#   - 초안은 블록 단위로 병합된다: 정밀 판독을 블록 하나에 돌려도 다른 블록 결과가 남는다
#   - 2단계 판정은 1단계 답이 있으면 «두 단계의 일치»다(앵커가 아니라)
#   - 검토 목록(list_review_pages)은 사람이 볼 블록이 남은 쪽만 센다
#   - mark_applied는 applied_blocks를 누적한다

from ocr.correction_pass import (  # noqa: E402
    Candidate,
    draft_status,
    list_review_pages,
    load_draft,
    mark_applied,
    merge_draft,
    rejected_block_ids,
    text_agreement,
)


def _pipeline(root, engine):
    registry = OcrEngineRegistry()
    registry.register(engine)
    return OcrPipeline(registry, library_root=str(root))


class TestLadderJoints:
    def test_precise_merges_onto_fast_draft(self, library):
        root, doc = library
        engine = _EchoLlmEngine({"裴楷清通": "裴楷淸通", "孔明卧龍": "孔明臥龍"})
        pipeline = _pipeline(root, engine)
        cands = select_candidates(_l2(), LAYOUT)
        assert {c.block_id for c in cands} == {"b2", "b3"}

        run_correction(pipeline, engine, doc, "doc1", "v1", 1, cands, mode="fast")
        apply_draft(doc, "v1", 1, ["b2"])  # 사람이 하나 적용해 둔 상태

        # 블록 하나에만 정밀 판독 — 예전 구현은 여기서 b2와 applied_blocks가 사라졌다
        b3 = [c for c in cands if c.block_id == "b3"]
        draft = run_correction(pipeline, engine, doc, "doc1", "v1", 1, b3, mode="precise")
        by_id = {b["block_id"]: b for b in draft["blocks"]}
        assert set(by_id) == {"b2", "b3"}
        assert by_id["b2"]["stage"] == "fast"
        assert by_id["b3"]["stage"] == "precise"
        assert draft["applied_blocks"] == ["b2"]
        # 파일에도 같은 것이 남았다
        on_disk = load_draft(doc, "v1", 1)
        assert {b["block_id"] for b in on_disk["blocks"]} == {"b2", "b3"}

    def test_stage2_is_judged_by_stage_agreement(self, library):
        root, doc = library
        # 1단계: 卧→臥 한 글자 바꿈(앵커와 75%라 불합격). 2단계도 같은 답 → 두 단계 일치 → 수용
        engine = _EchoLlmEngine({"孔明卧龍": "孔明臥龍"})
        pipeline = _pipeline(root, engine)
        b3 = [c for c in select_candidates(_l2(), LAYOUT) if c.block_id == "b3"]
        d1 = run_correction(pipeline, engine, doc, "doc1", "v1", 1, b3, mode="fast")
        assert d1["blocks"][0]["accepted"] is False
        assert d1["blocks"][0]["accept_basis"] == "anchor"

        d2 = run_correction(pipeline, engine, doc, "doc1", "v1", 1, b3, mode="precise")
        e = d2["blocks"][0]
        assert e["accept_basis"] == "stages"
        assert e["stage1"]["corrected_text"] == "孔明臥龍"
        assert e["stages_agreement"] == 1.0
        assert e["accepted"] is True  # 앵커와는 75%지만 두 단계가 같다

    def test_stage2_disagreement_goes_to_human(self, library):
        root, doc = library
        engine = _EchoLlmEngine({"孔明卧龍": "孔明臥龍"})
        pipeline = _pipeline(root, engine)
        b3 = [c for c in select_candidates(_l2(), LAYOUT) if c.block_id == "b3"]
        run_correction(pipeline, engine, doc, "doc1", "v1", 1, b3, mode="fast")
        # 2단계는 다른 답을 낸다
        engine.reply_by_block["孔明卧龍"] = "孔明臥竜"
        d2 = run_correction(pipeline, engine, doc, "doc1", "v1", 1, b3, mode="precise")
        e = d2["blocks"][0]
        assert e["accepted"] is False
        assert e["stage1"]["corrected_text"] == "孔明臥龍" and e["corrected_text"] == "孔明臥竜"
        assert 0 < e["stages_agreement"] < 1
        # 사람이 볼 목록에 선다
        assert draft_status(d2)["pending"] == 1
        assert [p["page"] for p in list_review_pages(doc, "v1")] == [1]

    def test_precise_without_stage1_uses_anchor(self, library):
        root, doc = library
        engine = _EchoLlmEngine({"裴楷清通": "裴楷清通"})
        pipeline = _pipeline(root, engine)
        b2 = [c for c in select_candidates(_l2(), LAYOUT) if c.block_id == "b2"]
        d = run_correction(pipeline, engine, doc, "doc1", "v1", 1, b2, mode="precise")
        assert d["blocks"][0]["accept_basis"] == "anchor"
        assert d["blocks"][0]["accepted"] is True
        assert "stage1" not in d["blocks"][0]

    def test_fresh_discards_old_draft(self, library):
        root, doc = library
        engine = _EchoLlmEngine({})
        pipeline = _pipeline(root, engine)
        cands = select_candidates(_l2(), LAYOUT)
        run_correction(pipeline, engine, doc, "doc1", "v1", 1, cands, mode="fast")
        b2 = [c for c in cands if c.block_id == "b2"]
        d = run_correction(pipeline, engine, doc, "doc1", "v1", 1, b2, mode="fast", fresh=True)
        assert [b["block_id"] for b in d["blocks"]] == ["b2"]

    def test_rejected_and_review_accounting(self, library):
        root, doc = library
        engine = _EchoLlmEngine({"裴楷清通": "裴楷清通", "孔明卧龍": "孔明臥龍"})
        pipeline = _pipeline(root, engine)
        cands = select_candidates(_l2(), LAYOUT)
        d = run_correction(pipeline, engine, doc, "doc1", "v1", 1, cands, mode="fast")
        assert rejected_block_ids(d) == ["b3"]  # b2는 자동 수용
        assert draft_status(d) == {
            "pending": 1,
            "accepted": 1,
            "applied": 0,
            "errors": 0,
            "conflicts": 0,
            "blocks": 2,
        }

        mark_applied(doc, "v1", 1, ["b2"])
        st = draft_status(load_draft(doc, "v1", 1))
        assert st["accepted"] == 0 and st["applied"] == 1 and st["pending"] == 1
        pages = list_review_pages(doc, "v1")
        assert pages and pages[0]["page"] == 1 and pages[0]["pending"] == 1

        mark_applied(doc, "v1", 1, ["b3"])
        assert list_review_pages(doc, "v1") == []  # 남은 것이 없으면 목록에서 빠진다
        assert rejected_block_ids(load_draft(doc, "v1", 1)) == []

    def test_merge_and_agreement_helpers(self):
        old = {
            "mode": "fast",
            "applied_blocks": ["a"],
            "blocks": [{"block_id": "a"}, {"block_id": "b", "v": 1}],
        }
        new = {"mode": "precise", "blocks": [{"block_id": "b", "v": 2}, {"block_id": "c"}]}
        m = merge_draft(old, new)
        assert [b["block_id"] for b in m["blocks"]] == ["a", "b", "c"]
        assert next(b for b in m["blocks"] if b["block_id"] == "b")["v"] == 2
        assert m["applied_blocks"] == ["a"] and m["mode"] == "precise"
        assert merge_draft(None, new) is new
        assert text_agreement("孔明臥龍", "孔明臥龍") == 1.0
        assert text_agreement("", "") == 0.0
        assert text_agreement("孔明臥龍", "孔明臥竜") == 0.75
        assert Candidate("x").to_dict()["block_id"] == "x"


class TestLadderRoute:
    """라우터의 mode="ladder": 1단계 전부 → 떨어진 블록만 2단계 (D-082의 «이음» ①)."""

    def test_ladder_escalates_only_rejected(self, library, monkeypatch):
        root, doc = library
        from app.routers import llm_ocr as router_mod

        engine = _EchoLlmEngine({"裴楷清通": "裴楷清通", "孔明卧龍": "孔明臥龍"})
        pipeline = _pipeline(root, engine)
        registry = pipeline.registry
        draft = router_mod._run_page_correction(
            doc, "doc1", "v1", 1, pipeline, registry, mode="ladder"
        )
        by_id = {b["block_id"]: b for b in draft["blocks"]}
        # b2는 1단계에서 수용 → 1단계에 머문다. b3만 2단계로 올라갔다
        assert by_id["b2"]["stage"] == "fast" and by_id["b2"]["accepted"] is True
        assert by_id["b3"]["stage"] == "precise"
        assert "stage1_rejected" in by_id["b3"]["reasons"]
        assert by_id["b3"]["accept_basis"] == "stages"
        assert by_id["b3"]["accepted"] is True  # 두 단계가 같은 답(臥)
        # 엔진 호출: 1단계 둘(사고 끔) + 2단계 하나(사고 켬)
        thinks = [c.get("think") for c in engine.calls]
        assert thinks == [False, False, True]

    def test_ladder_stops_when_all_accepted(self, library):
        root, doc = library
        from app.routers import llm_ocr as router_mod

        engine = _EchoLlmEngine({"裴楷清通": "裴楷清通", "孔明卧龍": "孔明卧龍"})
        pipeline = _pipeline(root, engine)
        draft = router_mod._run_page_correction(
            doc, "doc1", "v1", 1, pipeline, pipeline.registry, mode="ladder"
        )
        assert all(b["stage"] == "fast" for b in draft["blocks"])
        assert len(engine.calls) == 2


class TestLadderJointsMore:
    """2026-09-18 자기 점검에서 잡은 둘: 정밀 판독을 거듭해도 1단계 답이 남는다,
    자동 수용됐는데 L4에 안 들어간 쪽도 검토 목록에 선다."""

    def test_repeated_precise_keeps_stage1(self, library):
        root, doc = library
        engine = _EchoLlmEngine({"孔明卧龍": "孔明臥龍"})
        pipeline = _pipeline(root, engine)
        b3 = [c for c in select_candidates(_l2(), LAYOUT) if c.block_id == "b3"]
        run_correction(pipeline, engine, doc, "doc1", "v1", 1, b3, mode="fast")
        engine.reply_by_block["孔明卧龍"] = "孔明臥竜"
        run_correction(pipeline, engine, doc, "doc1", "v1", 1, b3, mode="precise")
        engine.reply_by_block["孔明卧龍"] = "孔明臥龍"
        d3 = run_correction(pipeline, engine, doc, "doc1", "v1", 1, b3, mode="precise")
        e = d3["blocks"][0]
        assert e["stage1"]["corrected_text"] == "孔明臥龍"  # 첫 1단계 답이 그대로
        assert e["accept_basis"] == "stages" and e["accepted"] is True

    def test_accepted_unapplied_page_is_listed(self, library):
        root, doc = library
        engine = _EchoLlmEngine({"裴楷清通": "裴楷清通", "孔明卧龍": "孔明卧龍"})
        pipeline = _pipeline(root, engine)
        d = run_correction(
            pipeline, engine, doc, "doc1", "v1", 1, select_candidates(_l2(), LAYOUT), mode="fast"
        )
        assert all(b["accepted"] for b in d["blocks"])
        pages = list_review_pages(doc, "v1")
        assert pages and pages[0]["accepted"] == 2 and pages[0]["pending"] == 0
        mark_applied(doc, "v1", 1, ["b2", "b3"])
        assert list_review_pages(doc, "v1") == []


# ─── 교차검증(2026-09-18) 지적에 대한 회귀 테스트 ─────────────────────
from ocr.correction_pass import (  # noqa: E402
    discard_draft,
    draft_is_stale,
    l2_fingerprint,
    needs_human,
)


class _FlakyEngine(_EchoLlmEngine):
    """think=True(2단계) 호출에서만 터지는 엔진 — 2단계 실패 시 1단계 초안 보존을 본다."""

    def recognize(
        self, image_bytes, writing_direction="vertical_rtl", language="classical_chinese", **kwargs
    ):
        if kwargs.get("think"):
            raise RuntimeError("2단계 모델이 죽었다")
        return super().recognize(image_bytes, writing_direction, language, **kwargs)


class _EmptyEngine(_EchoLlmEngine):
    """빈 답을 내는 엔진."""

    def recognize(
        self, image_bytes, writing_direction="vertical_rtl", language="classical_chinese", **kwargs
    ):
        self.calls.append(kwargs)
        return OcrBlockResult(
            lines=[],
            engine_id=self.engine_id,
            language=language,
            writing_direction=writing_direction,
        )


class TestCrossReviewFixes:
    def test_stage1_rejects_illegible(self):
        # □가 섞이면 1단계도 자동 수용하지 않는다 — 2단계와 같은 잣대
        r = evaluate_block(
            "孔明臥龍",
            [
                {
                    "text": "孔明□龍",
                    "characters": [
                        {"char": "孔", "confidence": 0.95},
                        {"char": "明", "confidence": 0.95},
                        {"char": "□", "confidence": 0.1},
                        {"char": "龍", "confidence": 0.95},
                    ],
                }
            ],
        )
        assert r["illegible_count"] == 1 and r["accepted"] is False

    def test_empty_answer_is_counted_as_error(self, library):
        root, doc = library
        engine = _EmptyEngine({})
        pipeline = _pipeline(root, engine)
        cands = select_candidates(_l2(), LAYOUT)
        d = run_correction(pipeline, engine, doc, "doc1", "v1", 1, cands, mode="fast")
        st = draft_status(d)
        assert st["errors"] == 2 and st["pending"] == 0 and st["accepted"] == 0
        assert st["pending"] + st["accepted"] + st["errors"] + st["applied"] == st["blocks"]
        assert needs_human(st)
        assert [p["page"] for p in list_review_pages(doc, "v1")] == [1]

    def test_stale_draft_detected_and_refused(self, library):
        root, doc = library
        engine = _EchoLlmEngine({"孔明卧龍": "孔明臥龍"})
        pipeline = _pipeline(root, engine)
        b3 = [c for c in select_candidates(_l2(), LAYOUT) if c.block_id == "b3"]
        d = run_correction(pipeline, engine, doc, "doc1", "v1", 1, b3, mode="fast")
        assert d["l2_fingerprint"] == l2_fingerprint(doc, "v1", 1)
        assert draft_is_stale(doc, "v1", 1, d) is False
        # OCR을 다시 돌린 셈 — L2가 바뀐다
        l2 = _l2()
        l2["ocr_results"][2]["lines"][0]["text"] = "孔明臥龍"
        (doc / "L2_ocr" / "v1_page_001.json").write_text(json.dumps(l2), encoding="utf-8")
        assert draft_is_stale(doc, "v1", 1, load_draft(doc, "v1", 1)) is True
        pages = list_review_pages(doc, "v1")
        assert pages and pages[0]["stale"] is True  # 감추지 않고 «낡음»으로 올린다
        from ocr.correction_pass import StaleDraftError

        with pytest.raises(StaleDraftError):
            apply_draft(doc, "v1", 1, ["b3"])  # 적용 거부
        # 새 실행은 낡은 초안 위에 병합하지 않는다
        b2 = [c for c in select_candidates(_l2(), LAYOUT) if c.block_id == "b2"]
        d2 = run_correction(pipeline, engine, doc, "doc1", "v1", 1, b2, mode="fast")
        assert [b["block_id"] for b in d2["blocks"]] == ["b2"]
        assert draft_is_stale(doc, "v1", 1, d2) is False

    def test_fresh_with_no_candidates_discards_old_draft(self, library):
        root, doc = library
        engine = _EchoLlmEngine({})
        pipeline = _pipeline(root, engine)
        run_correction(
            pipeline, engine, doc, "doc1", "v1", 1, select_candidates(_l2(), LAYOUT), mode="fast"
        )
        assert draft_path(doc, "v1", 1).exists()
        d = run_correction(pipeline, engine, doc, "doc1", "v1", 1, [], mode="fast", fresh=True)
        assert d["blocks"] == [] and not draft_path(doc, "v1", 1).exists()
        assert discard_draft(doc, "v1", 1) is False

    def test_corrupt_draft_is_listed_not_hidden(self, library):
        root, doc = library
        p = draft_path(doc, "v1", 1)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json", encoding="utf-8")
        pages = list_review_pages(doc, "v1")
        assert pages == [
            {
                "page": 1,
                "mode": None,
                "corrupt": True,
                "pending": 0,
                "accepted": 0,
                "applied": 0,
                "errors": 1,
                "conflicts": 0,
                "blocks": 0,
            }
        ]
        # 깨진 L2는 낡음(409)이 아니라 다른 오류로 구분된다
        assert not issubclass(
            json.JSONDecodeError, __import__("ocr.correction_pass", fromlist=["x"]).StaleDraftError
        )

    def test_review_pages_sort_numerically(self, library):
        root, doc = library
        for n in (1000, 999, 7):
            p = draft_path(doc, "v1", n)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps({"blocks": [{"block_id": "x", "corrected_text": "甲"}]}),
                encoding="utf-8",
            )
        assert [p["page"] for p in list_review_pages(doc, "v1")] == [7, 999, 1000]

    def test_conflict_after_reapplying_precise(self, library):
        root, doc = library
        engine = _EchoLlmEngine({"孔明卧龍": "孔明臥龍"})
        pipeline = _pipeline(root, engine)
        b3 = [c for c in select_candidates(_l2(), LAYOUT) if c.block_id == "b3"]
        run_correction(pipeline, engine, doc, "doc1", "v1", 1, b3, mode="fast")
        apply_draft(doc, "v1", 1, ["b3"])
        d = load_draft(doc, "v1", 1)
        assert d["blocks"][0]["applied_text"] == "孔明臥龍"
        assert draft_status(d)["applied"] == 1 and draft_status(d)["pending"] == 0
        # 적용 뒤 다시 읽었더니 답이 다르다 → 충돌 → 사람이 다시 본다
        engine.reply_by_block["孔明卧龍"] = "孔明臥竜"
        d2 = run_correction(pipeline, engine, doc, "doc1", "v1", 1, b3, mode="precise")
        st = draft_status(d2)
        assert st["conflicts"] == 1 and st["pending"] == 1 and st["applied"] == 0
        assert list_review_pages(doc, "v1")[0]["conflicts"] == 1
        # 충돌을 사람이 새 답으로 해소한다 → L4의 옛 적용문이 새 답으로 바뀌고 충돌이 풀린다
        r = apply_draft(doc, "v1", 1, ["b3"])
        assert r["applied_blocks"] == ["b3"] and r["not_found_blocks"] == []
        from core.document import get_page_text

        assert "孔明臥竜" in get_page_text(doc, "v1", 1)["text"]
        assert draft_status(load_draft(doc, "v1", 1))["conflicts"] == 0

    def test_conflict_apply_reports_not_found_when_old_text_gone(self, library):
        root, doc = library
        engine = _EchoLlmEngine({"孔明卧龍": "孔明臥龍"})
        pipeline = _pipeline(root, engine)
        b3 = [c for c in select_candidates(_l2(), LAYOUT) if c.block_id == "b3"]
        run_correction(pipeline, engine, doc, "doc1", "v1", 1, b3, mode="fast")
        apply_draft(doc, "v1", 1, ["b3"])
        engine.reply_by_block["孔明卧龍"] = "孔明臥竜"
        run_correction(pipeline, engine, doc, "doc1", "v1", 1, b3, mode="precise")
        # 사람이 L4를 손으로 고쳐 옛 적용문이 사라졌다 → «전에 적용했다»로 성공 처리하면 안 된다
        from core.document import save_page_text

        save_page_text(doc, "v1", 1, "王戎簡要\n\n裴楷清通\n\n손으로 고침")
        r = apply_draft(doc, "v1", 1, ["b3"])
        assert r["applied_blocks"] == [] and r["not_found_blocks"] == ["b3"]

    def test_stage2_error_block_is_not_reescalated(self):
        d = {
            "applied_blocks": [],
            "blocks": [
                {
                    "block_id": "x",
                    "corrected_text": "甲",
                    "accepted": False,
                    "stage2_error": "죽음",
                },
                {"block_id": "y", "corrected_text": "乙", "accepted": False},
            ],
        }
        assert rejected_block_ids(d) == ["y"]

    def test_draft_without_fingerprint_is_stale(self, library):
        root, doc = library
        assert draft_is_stale(doc, "v1", 1, {"blocks": []}) is True
        assert draft_is_stale(doc, "v1", 1, None) is False

    def test_fingerprint_ignores_non_anchor_fields(self, library):
        root, doc = library
        before = l2_fingerprint(doc, "v1", 1)
        l2 = _l2()
        l2["rotation"] = 90  # 앵커와 무관한 필드
        (doc / "L2_ocr" / "v1_page_001.json").write_text(json.dumps(l2), encoding="utf-8")
        assert l2_fingerprint(doc, "v1", 1) == before

    def test_error_block_is_not_escalated(self):
        d = {
            "applied_blocks": [],
            "blocks": [
                {"block_id": "e", "error": "x"},
                {"block_id": "p", "corrected_text": "甲", "accepted": False},
                {"block_id": "a", "corrected_text": "乙", "accepted": True},
                {"corrected_text": "無"},
            ],
        }
        assert rejected_block_ids(d) == ["p"]
        assert merge_draft(
            {"blocks": [{"v": 1}], "applied_blocks": []}, {"blocks": [{"block_id": "p"}]}
        )["blocks"] == [{"block_id": "p"}]

    def test_run_mode_is_recorded(self, library):
        root, doc = library
        engine = _EchoLlmEngine({})
        pipeline = _pipeline(root, engine)
        d = run_correction(
            pipeline,
            engine,
            doc,
            "doc1",
            "v1",
            1,
            select_candidates(_l2(), LAYOUT),
            mode="fast",
            run_mode="ladder",
        )
        assert d["run_mode"] == "ladder" and d["mode"] == "fast"


class TestLadderRouteMore:
    def test_ladder_with_user_block_ids(self, library):
        root, doc = library
        from app.routers import llm_ocr as router_mod

        engine = _EchoLlmEngine({"王戎簡要": "王戎簡要"})
        pipeline = _pipeline(root, engine)
        # b1은 기계적 선별에 안 걸리는 블록 — 사람이 지정하면 사다리를 탄다
        d = router_mod._run_page_correction(
            doc, "doc1", "v1", 1, pipeline, pipeline.registry, block_ids=["b1"]
        )
        assert [b["block_id"] for b in d["blocks"]] == ["b1"]
        assert d["blocks"][0]["reasons"] == ["user"] and d["blocks"][0]["accepted"] is True
        assert d["run_mode"] == "ladder"

    def test_stage2_failure_keeps_stage1_draft(self, library):
        root, doc = library
        from app.routers import llm_ocr as router_mod

        engine = _FlakyEngine({"裴楷清通": "裴楷清通", "孔明卧龍": "孔明臥龍"})
        pipeline = _pipeline(root, engine)
        d = router_mod._run_page_correction(
            doc, "doc1", "v1", 1, pipeline, pipeline.registry, mode="ladder"
        )
        by_id = {b["block_id"]: b for b in d["blocks"]}
        # 블록 단위 오류는 run_correction이 삼키고 항목에 적는다 — 1단계 답은 그대로 남는다
        assert set(by_id) == {"b2", "b3"} and by_id["b3"]["stage"] == "fast"
        assert by_id["b3"]["corrected_text"] == "孔明臥龍" and by_id["b3"]["accepted"] is False
        assert "2단계 모델이 죽었다" in by_id["b3"]["stage2_error"]
        assert draft_status(d)["pending"] == 1  # 사람에게 간다
        on_disk = load_draft(doc, "v1", 1)
        assert {b["block_id"] for b in on_disk["blocks"]} == {"b2", "b3"}
        assert [p["page"] for p in list_review_pages(doc, "v1")] == [1]


class TestConcurrency:
    """일괄(교정 실행)과 사람(적용)이 같은 쪽을 동시에 만질 때 기록이 유실되지 않는다(쪽 잠금)."""

    def test_apply_during_correction_is_not_lost(self, library):
        import threading
        import time

        root, doc = library

        class _SlowEngine(_EchoLlmEngine):
            def recognize(
                self,
                image_bytes,
                writing_direction="vertical_rtl",
                language="classical_chinese",
                **kwargs,
            ):
                time.sleep(0.6)  # LLM을 기다리는 동안 사람이 「적용」을 누른다
                return super().recognize(image_bytes, writing_direction, language, **kwargs)

        engine = _SlowEngine({"裴楷清通": "裴楷清通", "孔明卧龍": "孔明臥龍"})
        pipeline = _pipeline(root, engine)
        cands = select_candidates(_l2(), LAYOUT)
        run_correction(pipeline, engine, doc, "doc1", "v1", 1, cands, mode="fast")  # 1단계 둘

        b3 = [c for c in cands if c.block_id == "b3"]
        t = threading.Thread(
            target=run_correction,
            args=(pipeline, engine, doc, "doc1", "v1", 1, b3),
            kwargs={"mode": "precise"},
        )
        t.start()
        time.sleep(0.2)
        apply_draft(doc, "v1", 1, ["b2"])  # 정밀 판독이 LLM을 기다리는 동안
        t.join(timeout=10)
        assert not t.is_alive()

        d = load_draft(doc, "v1", 1)
        by_id = {b["block_id"]: b for b in d["blocks"]}
        assert d["applied_blocks"] == ["b2"]  # 예전 구현은 여기서 사라졌다
        assert by_id["b2"].get("applied_text") == "裴楷清通"
        assert by_id["b3"]["stage"] == "precise"

    def test_parallel_applies_both_recorded(self, library):
        import threading

        root, doc = library
        engine = _EchoLlmEngine({"裴楷清通": "裴楷淸通", "孔明卧龍": "孔明臥龍"})
        pipeline = _pipeline(root, engine)
        run_correction(
            pipeline, engine, doc, "doc1", "v1", 1, select_candidates(_l2(), LAYOUT), mode="fast"
        )
        errors = []

        def go(bid):
            try:
                apply_draft(doc, "v1", 1, [bid])
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        ts = [threading.Thread(target=go, args=(b,)) for b in ("b2", "b3") for _ in range(3)]
        for x in ts:
            x.start()
        for x in ts:
            x.join(timeout=10)
        assert not errors
        d = load_draft(doc, "v1", 1)
        assert d["applied_blocks"] == ["b2", "b3"]
        from core.document import get_page_text

        text = get_page_text(doc, "v1", 1)["text"]
        assert "裴楷淸通" in text and "孔明臥龍" in text
