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
