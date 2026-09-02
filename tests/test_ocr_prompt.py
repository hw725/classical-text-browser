"""OCR 프롬프트 조립기 테스트 (D-081).

무엇을 고정하는가:
  - 다섯 조각(정책·문헌·블록·자형·앵커)이 있을 때만 자리가 생기고, 없으면 빠진다
  - 정책 문장은 «보이는 대로·정규화 금지»를 말하고, 자형 목록은 정규화 지시가 아니다
  - [?]·□ 마커가 글자별 신뢰도로 바뀌고 텍스트에는 남지 않는다
  - LlmOcrEngine이 kwargs의 문맥을 프롬프트에 싣고, 마커를 신뢰도로 옮긴다
  - 파이프라인이 block_type과 문헌 지침을 엔진에 넘긴다
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from llm.providers.base import LlmResponse  # noqa: E402
from ocr.base import BaseOcrEngine, OcrBlockResult, OcrLineResult  # noqa: E402
from ocr.llm_ocr_engine import LlmOcrEngine  # noqa: E402
from ocr.ocr_prompt import (  # noqa: E402
    CERTAIN_CONFIDENCE,
    ILLEGIBLE_CONFIDENCE,
    UNCERTAIN_CONFIDENCE,
    build_block_guidance,
    build_document_guidance,
    build_system_prompt,
    build_user_prompt,
    build_variant_hints,
    load_document_guidance,
    parse_uncertainty,
)
from ocr.pipeline import OcrPipeline  # noqa: E402
from ocr.registry import OcrEngineRegistry  # noqa: E402

# ─── 정책 ───────────────────────────────────────────────────────


class TestSystemPrompt:
    def test_policy_says_as_is_and_no_normalization(self):
        s = build_system_prompt()
        assert "보이는 대로" in s
        assert "정규화 금지" in s
        assert "[?]" in s and "□" in s
        assert '{"lines"' in s

    def test_system_prompt_is_stable(self):
        """문헌·블록 정보는 사용자 프롬프트에 — 시스템 프롬프트는 호출마다 같아야 캐시가 먹는다."""
        assert build_system_prompt() == build_system_prompt()


# ─── 문헌 지침 ─────────────────────────────────────────────────


class TestDocumentGuidance:
    def test_empty_when_nothing_known(self):
        assert build_document_guidance(None, None) == ""
        assert build_document_guidance({}, {}) == ""

    def test_bibliography_facts(self):
        bib = {
            "title": "蒙求",
            "date_created": "1500년경",
            "edition_type": "목판본",
            "script": "漢字",
            "language": "classical_chinese",
        }
        g = build_document_guidance({"title": "x"}, bib)
        assert g.startswith("문헌: 蒙求.")
        assert "목판본" in g and "1500년경" in g and "고전 한문" in g

    def test_manifest_guidance_appended_last(self):
        g = build_document_guidance(
            {"title": "T", "ocr_guidance": "인명 長尾欽彌·藤島亥治郞가 자주 나온다."}, None
        )
        assert g.endswith("인명 長尾欽彌·藤島亥治郞가 자주 나온다.")
        assert g.startswith("문헌: T.")

    def test_load_from_directory(self, tmp_path):
        (tmp_path / "manifest.json").write_text(
            json.dumps({"title": "甲", "ocr_guidance": "구자체 유지"}), encoding="utf-8"
        )
        (tmp_path / "bibliography.json").write_text(
            json.dumps({"title": "甲", "edition_type": "필사본"}), encoding="utf-8"
        )
        g = load_document_guidance(tmp_path)
        assert "필사본" in g and "구자체 유지" in g

    def test_load_missing_or_broken_is_empty(self, tmp_path):
        assert load_document_guidance(tmp_path / "nope") == ""
        (tmp_path / "manifest.json").write_text("{broken", encoding="utf-8")
        assert load_document_guidance(tmp_path) == ""


# ─── 블록 지침 ─────────────────────────────────────────────────


class TestBlockGuidance:
    def test_annotation_reading_hint(self):
        g = build_block_guidance("annotation")
        assert "주석" in g and "쌍행" in g

    def test_unknown_and_none_are_empty(self):
        assert build_block_guidance(None) == ""
        assert build_block_guidance("unknown") == ""

    def test_unlisted_type_still_named(self):
        g = build_block_guidance("custom_zone")
        assert "custom_zone" in g


# ─── 자형 주의 ─────────────────────────────────────────────────


class TestVariantHints:
    def test_empty(self):
        assert build_variant_hints(None) == ""
        assert build_variant_hints([]) == ""

    def test_pairs_and_disclaimer(self):
        h = build_variant_hints([["說", "説"], "裴/裵"])
        assert "說/説" in h and "裴/裵" in h
        # 정규화 지시가 아니라 주의 목록임을 문장이 명시한다 (D-080)
        assert "어느 쪽이 맞다는 뜻이 아닙니다" in h

    def test_capped(self):
        pairs = [[chr(0x4E00 + i), chr(0x4E00 + i + 1)] for i in range(100)]
        h = build_variant_hints(pairs)
        assert h.count("/") == 30


# ─── 사용자 프롬프트 조립 ──────────────────────────────────────


class TestUserPrompt:
    def test_minimal_has_no_optional_sections(self):
        p = build_user_prompt("vertical_rtl", "classical_chinese")
        assert "세로쓰기" in p and "고전 한문" in p
        for tag in ("[문헌 정보]", "[영역 정보]", "[자형 주의]", "[1차 인식 결과", "[주변 문맥"):
            assert tag not in p

    def test_all_sections_present_in_order(self):
        p = build_user_prompt(
            "horizontal_ltr",
            "korean",
            block_type="annotation",
            doc_guidance="문헌: 甲.",
            variant_hints=[["說", "説"]],
            anchor_text="王戎簡要",
            context_before="앞줄",
            context_after="뒷줄",
        )
        order = [
            p.index("[문헌 정보]"),
            p.index("[영역 정보]"),
            p.index("[자형 주의]"),
            p.index("[주변 문맥"),
            p.index("[1차 인식 결과"),
        ]
        assert order == sorted(order)
        assert "참고만" in p  # 앵커는 참고일 뿐이다
        assert "옮기지 말고 판독에만 참고" in p  # 문맥은 옮기지 않는다


# ─── 불확실 표기 파싱 ──────────────────────────────────────────


class TestParseUncertainty:
    def test_markers_to_confidence(self):
        text, confs = parse_uncertainty("王戎[?]簡要□")
        assert text == "王戎簡要□"
        assert confs == [
            CERTAIN_CONFIDENCE,
            UNCERTAIN_CONFIDENCE,
            CERTAIN_CONFIDENCE,
            CERTAIN_CONFIDENCE,
            ILLEGIBLE_CONFIDENCE,
        ]

    def test_marker_never_survives(self):
        text, _ = parse_uncertainty("[?]甲[?][?]乙 [?]")
        assert "[?]" not in text and text == "甲乙"

    def test_whitespace_skipped(self):
        text, confs = parse_uncertainty("甲 乙\t丙")
        assert text == "甲乙丙" and len(confs) == 3

    def test_empty(self):
        assert parse_uncertainty("") == ("", [])


# ─── 엔진 통합 ─────────────────────────────────────────────────


class _CapturingRouter:
    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []
        self.systems: list[str] = []
        self.providers = [SimpleNamespace(supports_image=True)]

    async def call_with_image(self, prompt, image, **kwargs):
        self.prompts.append(prompt)
        self.systems.append(kwargs.get("system", ""))
        return LlmResponse(text=self.reply, provider="fake", model="m")


class TestEngineUsesAssembledPrompt:
    def test_context_reaches_prompt_and_markers_become_confidence(self):
        router = _CapturingRouter('{"lines":[{"text":"王戎[?]簡要□"}]}')
        engine = LlmOcrEngine(router)
        result = engine.recognize(
            b"img",
            block_type="annotation",
            doc_guidance="문헌: 蒙求. 판종 목판본.",
            variant_hints=[["說", "説"]],
            anchor_text="王戍簡要",
        )
        prompt = router.prompts[0]
        assert (
            "목판본" in prompt and "주석" in prompt and "說/説" in prompt and "王戍簡要" in prompt
        )
        assert "보이는 대로" in router.systems[0]

        line = result.lines[0]
        assert line.text == "王戎簡要□"
        assert [round(c.confidence, 1) for c in line.characters] == [0.9, 0.5, 0.9, 0.9, 0.1]

    def test_line_of_only_markers_is_dropped(self):
        router = _CapturingRouter('{"lines":[{"text":"[?]"},{"text":"甲"}]}')
        result = LlmOcrEngine(router).recognize(b"img")
        assert [ln.text for ln in result.lines] == ["甲"]


# ─── 파이프라인 통합 ──────────────────────────────────────────


class _RecordingEngine(BaseOcrEngine):
    engine_id = "recording"
    display_name = "Recording"
    requires_network = False

    def __init__(self):
        self.calls: list[dict] = []

    def is_available(self) -> bool:
        return True

    def recognize(
        self, image_bytes, writing_direction="vertical_rtl", language="classical_chinese", **kwargs
    ):
        self.calls.append(dict(kwargs, writing_direction=writing_direction))
        return OcrBlockResult(
            lines=[OcrLineResult(text="甲")],
            engine_id=self.engine_id,
            language=language,
            writing_direction=writing_direction,
        )


@pytest.fixture
def library_with_metadata(tmp_path):
    doc = tmp_path / "documents" / "doc1"
    (doc / "L1_source").mkdir(parents=True)
    Image.new("RGB", (800, 1200), "white").save(doc / "L1_source" / "v1_page_001.png")
    (doc / "manifest.json").write_text(
        json.dumps({"title": "蒙求", "ocr_guidance": "인명 王戎이 자주 나온다."}), encoding="utf-8"
    )
    (doc / "bibliography.json").write_text(
        json.dumps({"title": "蒙求", "edition_type": "목판본"}), encoding="utf-8"
    )
    (doc / "L3_layout").mkdir()
    layout = {
        "part_id": "v1",
        "page_number": 1,
        "blocks": [
            {
                "block_id": "b1",
                "block_type": "main_text",
                "bbox": [0.1, 0.1, 0.3, 0.5],
                "reading_order": 1,
                "writing_direction": "vertical_rtl",
            },
            {
                "block_id": "b2",
                "block_type": "annotation",
                "bbox": [0.5, 0.1, 0.3, 0.5],
                "reading_order": 2,
                "writing_direction": "vertical_rtl",
            },
        ],
    }
    (doc / "L3_layout" / "v1_page_001.json").write_text(json.dumps(layout), encoding="utf-8")
    return tmp_path


class TestPipelinePassesContext:
    def test_block_type_and_guidance_forwarded(self, library_with_metadata):
        engine = _RecordingEngine()
        registry = OcrEngineRegistry()
        registry.register(engine)
        pipeline = OcrPipeline(registry, library_root=str(library_with_metadata))

        pipeline.run_page("doc1", "v1", 1)

        assert [c["block_type"] for c in engine.calls] == ["main_text", "annotation"]
        for c in engine.calls:
            assert "목판본" in c["doc_guidance"] and "王戎" in c["doc_guidance"]

    def test_caller_guidance_wins(self, library_with_metadata):
        engine = _RecordingEngine()
        registry = OcrEngineRegistry()
        registry.register(engine)
        pipeline = OcrPipeline(registry, library_root=str(library_with_metadata))

        pipeline.run_page("doc1", "v1", 1, doc_guidance="호출자 지침")

        assert all(c["doc_guidance"] == "호출자 지침" for c in engine.calls)
