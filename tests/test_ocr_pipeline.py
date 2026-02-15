"""OCR 파이프라인 테스트.

실제 OCR 엔진 없이 더미 엔진으로 파이프라인 흐름을 검증한다.
"""

import json
import pytest
from PIL import Image

from src.ocr.base import BaseOcrEngine, OcrBlockResult, OcrLineResult, OcrCharResult
from src.ocr.registry import OcrEngineRegistry
from src.ocr.pipeline import OcrPipeline


class DummyOcrEngine(BaseOcrEngine):
    """테스트용 더미 OCR 엔진."""
    engine_id = "dummy"
    display_name = "Dummy"
    requires_network = False

    def is_available(self) -> bool:
        return True

    def recognize(self, image_bytes, writing_direction="vertical_rtl",
                  language="classical_chinese", **kwargs) -> OcrBlockResult:
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
                ),
            ],
            engine_id="dummy",
            language=language,
            writing_direction=writing_direction,
        )


@pytest.fixture
def test_library(tmp_path):
    """테스트용 서고 디렉토리 구조 생성.

    실제 프로젝트 경로 규칙:
      {library_root}/documents/{doc_id}/L3_layout/{part_id}_page_{NNN}.json
      {library_root}/documents/{doc_id}/L1_source/{part_id}_page_{NNN}.png
    """
    doc_dir = tmp_path / "documents" / "doc001"

    # L1 이미지 생성 (L1_source에 저장)
    l1_dir = doc_dir / "L1_source"
    l1_dir.mkdir(parents=True)
    img = Image.new("RGB", (1000, 1500), "white")
    img.save(l1_dir / "vol1_page_001.png")

    # L3 레이아웃 생성
    l3_dir = doc_dir / "L3_layout"
    l3_dir.mkdir(parents=True)
    layout = {
        "part_id": "vol1",
        "page_number": 1,
        "blocks": [
            {
                "block_id": "p01_b01",
                "bbox": [0.1, 0.05, 0.3, 0.4],
                "reading_order": 1,
                "writing_direction": "vertical_rtl",
                "skip": False,
            },
            {
                "block_id": "p01_b02",
                "bbox": [0.5, 0.05, 0.3, 0.4],
                "reading_order": 2,
                "writing_direction": "vertical_rtl",
                "skip": False,
            },
            {
                "block_id": "p01_b03",
                "bbox": [0.1, 0.6, 0.8, 0.1],
                "reading_order": 3,
                "skip": True,  # 건너뛸 블록
            },
        ],
    }
    with open(l3_dir / "vol1_page_001.json", "w", encoding="utf-8") as f:
        json.dump(layout, f)

    return tmp_path


class TestOcrPipeline:
    def test_run_page_full(self, test_library):
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(test_library))

        result = pipeline.run_page("doc001", "vol1", 1)

        assert result.processed_blocks == 2
        assert result.skipped_blocks == 1
        assert result.total_blocks == 3
        assert len(result.ocr_results) == 2
        assert result.ocr_results[0]["layout_block_id"] == "p01_b01"
        assert result.errors == []

    def test_run_page_saves_l2(self, test_library):
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(test_library))

        pipeline.run_page("doc001", "vol1", 1)

        # L2 파일이 생성되었는지 확인 (프로젝트 네이밍 컨벤션)
        l2_path = test_library / "documents" / "doc001" / "L2_ocr" / "vol1_page_001.json"
        assert l2_path.exists()

        with open(l2_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["part_id"] == "vol1"
        assert data["page_number"] == 1
        assert len(data["ocr_results"]) == 2

    def test_run_page_specific_blocks(self, test_library):
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(test_library))

        result = pipeline.run_page("doc001", "vol1", 1, block_ids=["p01_b01"])
        assert result.processed_blocks == 1
        assert len(result.ocr_results) == 1
        assert result.ocr_results[0]["layout_block_id"] == "p01_b01"

    def test_run_page_no_layout(self, test_library):
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(test_library))

        result = pipeline.run_page("doc001", "vol1", 999)
        assert len(result.errors) == 1
        assert "L3 레이아웃" in result.errors[0]

    def test_run_page_no_image(self, test_library):
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())

        # 이미지 제거 (unlink 대신 새 디렉토리에서 이미지 없이 테스트)
        no_img_dir = test_library / "documents" / "doc002"
        l3_dir = no_img_dir / "L3_layout"
        l3_dir.mkdir(parents=True)
        layout = {
            "page_number": 1,
            "blocks": [{"block_id": "b1", "bbox": [0.1, 0.1, 0.3, 0.3]}],
        }
        with open(l3_dir / "vol1_page_001.json", "w") as f:
            json.dump(layout, f)

        pipeline = OcrPipeline(registry, library_root=str(test_library))
        result = pipeline.run_page("doc002", "vol1", 1)
        assert len(result.errors) == 1
        assert "L1 이미지" in result.errors[0]

    def test_run_block(self, test_library):
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(test_library))

        result = pipeline.run_block("doc001", "vol1", 1, "p01_b02")
        assert result.processed_blocks == 1
        assert result.ocr_results[0]["layout_block_id"] == "p01_b02"

    def test_to_dict_schema_format(self, test_library):
        """to_dict()가 ocr_page.schema.json 형식을 따르는지."""
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(test_library))

        result = pipeline.run_page("doc001", "vol1", 1)
        d = result.to_dict()

        # 스키마 필수 필드
        assert "part_id" in d
        assert "page_number" in d
        assert "ocr_results" in d

        # ocr_results 내부 구조
        for ocr_result in d["ocr_results"]:
            assert "layout_block_id" in ocr_result
            assert "lines" in ocr_result
            for line in ocr_result["lines"]:
                assert "text" in line

    def test_to_summary_format(self, test_library):
        """to_summary()가 API 응답 형식을 따르는지."""
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(test_library))

        result = pipeline.run_page("doc001", "vol1", 1)
        s = result.to_summary()

        assert "status" in s
        assert "engine" in s
        assert "total_blocks" in s
        assert "processed_blocks" in s
        assert "elapsed_sec" in s
        assert "ocr_results" in s
        assert s["status"] == "completed"
