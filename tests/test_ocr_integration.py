"""OCR 통합 테스트.

전체 흐름: L3 레이아웃 → 이미지 크롭 → OCR → L2 저장 → 스키마 검증.
"""

import json
from pathlib import Path

import pytest
from PIL import Image

from src.ocr.base import BaseOcrEngine, OcrBlockResult, OcrCharResult, OcrEngineError, OcrLineResult
from src.ocr.pipeline import OcrPipeline
from src.ocr.registry import OcrEngineRegistry


class FailingOcrEngine(BaseOcrEngine):
    """일부 이미지에서 실패하는 더미 엔진. 부분 실패 테스트용."""

    engine_id = "failing"
    display_name = "Failing"
    requires_network = False
    call_count = 0

    def is_available(self):
        return True

    def recognize(self, image_bytes, **kwargs):
        self.call_count += 1
        if self.call_count % 2 == 0:
            raise OcrEngineError("의도적 실패")
        return OcrBlockResult(
            lines=[
                OcrLineResult(
                    text="성공",
                    characters=[
                        OcrCharResult(char="성", confidence=0.9),
                        OcrCharResult(char="공", confidence=0.85),
                    ],
                )
            ],
            engine_id="failing",
        )


class DummyOcrEngine(BaseOcrEngine):
    """정상 동작하는 더미 엔진."""

    engine_id = "dummy"
    display_name = "Dummy"
    requires_network = False

    def is_available(self):
        return True

    def recognize(self, image_bytes, **kwargs):
        return OcrBlockResult(
            lines=[
                OcrLineResult(
                    text="王戎簡要",
                    bbox=[0, 0, 50, 200],
                    characters=[
                        OcrCharResult(char="王", confidence=0.95, bbox=[0, 0, 50, 50]),
                        OcrCharResult(char="戎", confidence=0.90, bbox=[0, 50, 50, 100]),
                        OcrCharResult(char="簡", confidence=0.88, bbox=[0, 100, 50, 150]),
                        OcrCharResult(char="要", confidence=0.92, bbox=[0, 150, 50, 200]),
                    ],
                )
            ],
            engine_id="dummy",
        )


@pytest.fixture
def full_test_library(tmp_path):
    """통합 테스트용 서고 (2개 블록 + 1개 스킵 블록)."""
    doc_dir = tmp_path / "documents" / "test_doc"

    # L1 이미지
    l1_dir = doc_dir / "L1_source"
    l1_dir.mkdir(parents=True)
    img = Image.new("RGB", (800, 1200), "white")
    img.save(l1_dir / "vol1_page_001.png")

    # L3 레이아웃
    l3_dir = doc_dir / "L3_layout"
    l3_dir.mkdir(parents=True)
    layout = {
        "part_id": "vol1",
        "page_number": 1,
        "blocks": [
            {
                "block_id": "b01",
                "bbox": [0.05, 0.05, 0.4, 0.8],
                "reading_order": 1,
                "writing_direction": "vertical_rtl",
            },
            {
                "block_id": "b02",
                "bbox": [0.55, 0.05, 0.4, 0.8],
                "reading_order": 2,
                "writing_direction": "vertical_rtl",
            },
            {
                "block_id": "b03_skip",
                "bbox": [0.1, 0.9, 0.8, 0.05],
                "reading_order": 99,
                "skip": True,
            },
        ],
    }
    with open(l3_dir / "vol1_page_001.json", "w", encoding="utf-8") as f:
        json.dump(layout, f)

    return tmp_path


class TestOcrIntegration:
    def test_partial_failure(self, full_test_library):
        """일부 블록 실패 시에도 나머지 결과가 저장되는지."""
        registry = OcrEngineRegistry()
        failing_engine = FailingOcrEngine()
        registry.register(failing_engine)
        pipeline = OcrPipeline(registry, library_root=str(full_test_library))

        result = pipeline.run_page("test_doc", "vol1", 1)

        # 2블록 중 1블록 성공, 1블록 실패
        assert result.processed_blocks == 1
        assert len(result.errors) == 1
        assert "의도적 실패" in result.errors[0]

        # L2 파일에는 성공한 블록만 포함
        l2_path = full_test_library / "documents" / "test_doc" / "L2_ocr" / "vol1_page_001.json"
        assert l2_path.exists()

        with open(l2_path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["ocr_results"]) == 1

    def test_schema_validation(self, full_test_library):
        """L2 출력이 ocr_page.schema.json으로 검증 가능한지."""
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(full_test_library))

        pipeline.run_page("test_doc", "vol1", 1)

        l2_path = full_test_library / "documents" / "test_doc" / "L2_ocr" / "vol1_page_001.json"
        with open(l2_path, encoding="utf-8") as f:
            data = json.load(f)

        # 스키마로 검증한다 — 스키마는 저장소에 늘 있다. 예전에는 «없으면 기본 키만 보고 통과»
        # 갈래가 있어, 경로가 틀어지면 검증 없이 초록이 됐다(2026-10-12 시험 중복 정리)
        import jsonschema

        schema_path = (
            Path(__file__).parent.parent / "schemas" / "source_repo" / "ocr_page.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)
        # 줄·글자 구조 — 전체 흐름 시험(정리하며 지움)에서 옮긴 단언
        assert len(data["ocr_results"]) == 2
        for ocr_result in data["ocr_results"]:
            for line in ocr_result["lines"]:
                assert "text" in line
                for ch in line.get("characters", []):
                    assert "char" in ch
