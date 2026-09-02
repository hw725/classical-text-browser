"""OCR 파이프라인 테스트.

실제 OCR 엔진 없이 더미 엔진으로 파이프라인 흐름을 검증한다.
"""

import json

import pytest
from PIL import Image

from src.ocr.base import BaseOcrEngine, OcrBlockResult, OcrCharResult, OcrLineResult
from src.ocr.pipeline import OcrPipeline
from src.ocr.registry import OcrEngineRegistry


class DummyOcrEngine(BaseOcrEngine):
    """테스트용 더미 OCR 엔진."""

    engine_id = "dummy"
    display_name = "Dummy"
    requires_network = False

    def is_available(self) -> bool:
        return True

    def recognize(
        self, image_bytes, writing_direction="vertical_rtl", language="classical_chinese", **kwargs
    ) -> OcrBlockResult:
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

    def test_run_block_merges_existing_l2_results(self, test_library):
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(test_library))

        pipeline.run_page("doc001", "vol1", 1)
        pipeline.run_block("doc001", "vol1", 1, "p01_b02")

        l2_path = test_library / "documents" / "doc001" / "L2_ocr" / "vol1_page_001.json"
        with open(l2_path, encoding="utf-8") as f:
            data = json.load(f)

        block_ids = [item.get("layout_block_id") for item in data.get("ocr_results", [])]
        assert "p01_b01" in block_ids
        assert "p01_b02" in block_ids
        assert len(data.get("ocr_results", [])) == 2

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


# ── D-086: 쪽 단위 엔진은 언제나 쪽 전체 + 블록 밖 행 제외 ──────────────


class PageLevelDummyEngine(BaseOcrEngine):
    """recognize_page()만 쓰는 더미. recognize()가 불리면 실패 — 크롭 경로 감지용."""

    engine_id = "pagedummy"
    display_name = "PageDummy"
    requires_network = False
    supports_page_level = True

    def __init__(self):
        self.page_calls: list[list[str]] = []

    def is_available(self):
        return True

    def recognize(self, image_bytes, **kwargs):
        raise AssertionError("쪽 단위 엔진에 블록 크롭이 넘어왔다")

    def recognize_page(self, page_image_bytes, blocks, progress_callback=None, **kwargs):
        ids = [b["block_id"] for b in blocks if not b.get("skip")]
        self.page_calls.append(ids)
        return [{"layout_block_id": bid, "lines": [{"text": f"T-{bid}"}]} for bid in ids]


class TestPageLevelAlways:
    def test_low_coverage_still_page_level(self, test_library):
        """픽스처 블록은 쪽의 70% 미만을 덮는다 — 예전에는 크롭 경로로 떨어졌다."""
        registry = OcrEngineRegistry()
        eng = PageLevelDummyEngine()
        registry.register(eng)
        pipeline = OcrPipeline(registry, library_root=str(test_library))
        result = pipeline.run_page("doc001", "vol1", 1)
        assert eng.page_calls == [["p01_b01", "p01_b02"]]
        assert sorted(r["layout_block_id"] for r in result.ocr_results) == ["p01_b01", "p01_b02"]

    def test_single_block_rerun_uses_page_level_and_merges(self, test_library):
        registry = OcrEngineRegistry()
        eng = PageLevelDummyEngine()
        registry.register(eng)
        pipeline = OcrPipeline(registry, library_root=str(test_library))
        pipeline.run_page("doc001", "vol1", 1)
        pipeline.run_block("doc001", "vol1", 1, "p01_b02")
        # 두 번째 호출은 요청한 블록만 넘긴다 — 그 블록 안의 행만 남는다
        assert eng.page_calls[-1] == ["p01_b02"]
        l2 = json.loads(
            (test_library / "documents" / "doc001" / "L2_ocr" / "vol1_page_001.json").read_text(
                encoding="utf-8"
            )
        )
        ids = sorted(r["layout_block_id"] for r in l2["ocr_results"])
        assert ids == ["p01_b01", "p01_b02"], "한 블록 재실행이 다른 블록 결과를 지웠다"


class TestMatchLinesToBlocks:
    def _blocks(self):
        return [
            {"block_id": "a", "bbox": [0, 0, 100, 400]},
            {"block_id": "b", "bbox": [200, 0, 300, 400]},
            {"block_id": "s", "bbox": [400, 0, 500, 400], "skip": True},
        ]

    def test_center_inside(self):
        from src.ocr.line_block_match import match_lines_to_blocks

        lines = [
            {"text": "x", "bbox": [10, 10, 40, 300]},
            {"text": "y", "bbox": [210, 10, 240, 300]},
        ]
        out = match_lines_to_blocks(lines, self._blocks())
        assert [ln["text"] for ln in out["a"]] == ["x"]
        assert [ln["text"] for ln in out["b"]] == ["y"]

    def test_outside_lines_are_dropped_not_nearest(self):
        """블록 사이 빈 곳의 행은 버린다 — 예전에는 가장 가까운 블록에 들어갔다."""
        from src.ocr.line_block_match import match_lines_to_blocks

        out = match_lines_to_blocks([{"text": "gap", "bbox": [120, 10, 180, 300]}], self._blocks())
        assert out == {}

    def test_partial_overlap_threshold(self):
        from src.ocr.line_block_match import match_lines_to_blocks

        # 중심(x=105)은 a 밖이지만 넓이의 60%가 a 안 → 배정
        out = match_lines_to_blocks([{"text": "p", "bbox": [70, 0, 120, 100]}], self._blocks())
        assert "a" in out and out["a"][0]["text"] == "p"
        # 30%만 들어가면 제외
        out = match_lines_to_blocks([{"text": "q", "bbox": [85, 0, 135, 100]}], self._blocks())
        assert out == {}

    def test_skip_block_never_receives(self):
        from src.ocr.line_block_match import match_lines_to_blocks

        out = match_lines_to_blocks([{"text": "z", "bbox": [410, 10, 440, 300]}], self._blocks())
        assert out == {}

    def test_no_blocks_unmatched(self):
        from src.ocr.line_block_match import match_lines_to_blocks

        lines = [{"text": "z", "bbox": [0, 0, 10, 10]}]
        assert match_lines_to_blocks(lines, []) == {"unmatched": lines}


class TestL2ImageSize:
    """L2에 bbox 좌표계(이미지 크기)를 기록하고, 병합 때 옛 좌표를 환산한다 (D-087)."""

    def _l2(self, test_library):
        return json.loads(
            (test_library / "documents" / "doc001" / "L2_ocr" / "vol1_page_001.json").read_text(
                encoding="utf-8"
            )
        )

    def test_image_size_recorded(self, test_library):
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(test_library))
        pipeline.run_page("doc001", "vol1", 1)
        l2 = self._l2(test_library)
        assert (l2["image_width"], l2["image_height"]) == (1000, 1500)

    def test_merge_rescales_old_coordinates(self, test_library):
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(test_library))
        pipeline.run_page("doc001", "vol1", 1)
        # 옛 파일 흉내: 절반 크기 이미지 위의 좌표였다고 기록을 고친다
        path = test_library / "documents" / "doc001" / "L2_ocr" / "vol1_page_001.json"
        l2 = json.loads(path.read_text(encoding="utf-8"))
        l2["image_width"], l2["image_height"] = 500, 750
        path.write_text(json.dumps(l2), encoding="utf-8")
        pipeline.run_block("doc001", "vol1", 1, "p01_b02")
        l2 = json.loads(path.read_text(encoding="utf-8"))
        assert (l2["image_width"], l2["image_height"]) == (1000, 1500)
        by_id = {r["layout_block_id"]: r for r in l2["ocr_results"]}
        # 건드리지 않은 블록의 좌표가 2배로 환산됐다 (더미 엔진 bbox [0,0,50,200] → [0,0,100,400])
        assert by_id["p01_b01"]["lines"][0]["bbox"] == [0, 0, 100, 400]
        assert by_id["p01_b01"]["lines"][0]["characters"][1]["bbox"] == [0, 100, 100, 200]
        # 다시 돌린 블록은 현재 좌표계 그대로
        assert by_id["p01_b02"]["lines"][0]["bbox"] == [0, 0, 50, 200]

    def test_rescale_helper_keeps_text(self):
        results = [{"layout_block_id": "x", "lines": [{"text": "王", "bbox": [1, 2, 3, 4]}]}]
        out = OcrPipeline._rescale_ocr_results(results, 2.0, 0.5)
        assert out[0]["lines"][0] == {"text": "王", "bbox": [2, 1, 6, 2]}
        assert results[0]["lines"][0]["bbox"] == [1, 2, 3, 4], "원본을 바꾸면 안 된다"
