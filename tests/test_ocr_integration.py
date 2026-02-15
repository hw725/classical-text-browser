"""OCR 통합 테스트.

전체 흐름: L3 레이아웃 → 이미지 크롭 → OCR → L2 저장 → 스키마 검증.
"""

import json
from pathlib import Path

import pytest
from PIL import Image

from src.ocr.base import BaseOcrEngine, OcrBlockResult, OcrLineResult, OcrCharResult, OcrEngineError
from src.ocr.registry import OcrEngineRegistry
from src.ocr.pipeline import OcrPipeline


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
            lines=[OcrLineResult(text="성공", characters=[
                OcrCharResult(char="성", confidence=0.9),
                OcrCharResult(char="공", confidence=0.85),
            ])],
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
            lines=[OcrLineResult(
                text="王戎簡要",
                bbox=[0, 0, 50, 200],
                characters=[
                    OcrCharResult(char="王", confidence=0.95, bbox=[0, 0, 50, 50]),
                    OcrCharResult(char="戎", confidence=0.90, bbox=[0, 50, 50, 100]),
                    OcrCharResult(char="簡", confidence=0.88, bbox=[0, 100, 50, 150]),
                    OcrCharResult(char="要", confidence=0.92, bbox=[0, 150, 50, 200]),
                ],
            )],
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
    def test_full_flow_with_dummy_engine(self, full_test_library):
        """더미 엔진으로 전체 흐름 검증."""
        # 1. 레지스트리 + 파이프라인 생성
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(full_test_library))

        # 2. run_page() 실행
        result = pipeline.run_page("test_doc", "vol1", 1)

        # 3. 기본 검증
        assert result.processed_blocks == 2
        assert result.skipped_blocks == 1
        assert result.errors == []
        assert result.engine_id == "dummy"

        # 4. L2 JSON 생성 확인
        l2_path = full_test_library / "documents" / "test_doc" / "L2_ocr" / "vol1_page_001.json"
        assert l2_path.exists()

        with open(l2_path, encoding="utf-8") as f:
            data = json.load(f)

        # 5. 스키마 호환성 확인
        assert data["part_id"] == "vol1"
        assert data["page_number"] == 1
        assert len(data["ocr_results"]) == 2

        # 6. layout_block_id가 올바르게 매핑되었는지
        block_ids = [r["layout_block_id"] for r in data["ocr_results"]]
        assert "b01" in block_ids
        assert "b02" in block_ids
        # skip 블록은 포함 안 됨
        assert "b03_skip" not in block_ids

        # 7. 각 OcrResult의 구조 검증
        for ocr_result in data["ocr_results"]:
            assert "lines" in ocr_result
            for line in ocr_result["lines"]:
                assert "text" in line
                if "characters" in line:
                    for ch in line["characters"]:
                        assert "char" in ch

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

        # 스키마 파일이 있으면 jsonschema로 검증
        schema_path = Path(__file__).parent.parent / "schemas" / "source_repo" / "ocr_page.schema.json"
        if schema_path.exists():
            import jsonschema
            with open(schema_path, encoding="utf-8") as f:
                schema = json.load(f)
            jsonschema.validate(data, schema)
        else:
            # 스키마 없으면 기본 구조만 검증
            assert "part_id" in data
            assert "page_number" in data
            assert "ocr_results" in data

    def test_rerun_single_block(self, full_test_library):
        """run_block()으로 단일 블록 재실행."""
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(full_test_library))

        result = pipeline.run_block("test_doc", "vol1", 1, "b02")
        assert result.processed_blocks == 1
        assert result.ocr_results[0]["layout_block_id"] == "b02"
