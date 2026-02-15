"""페이지 단위 대조 테스트.

실제 프로젝트 경로 규칙:
  - L2: {library_root}/documents/{doc_id}/L2_ocr/{part_id}_page_{NNN}.json
  - L4: {library_root}/documents/{doc_id}/L4_text/pages/{part_id}_page_{NNN}.txt
"""

import json

import pytest

from src.core.alignment import MatchType, VariantCharDict, align_page


@pytest.fixture
def variant_dict(tmp_path):
    data = {"variants": {"裴": ["裵"], "裵": ["裴"]}}
    path = tmp_path / "variants.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return VariantCharDict(str(path))


@pytest.fixture
def test_library(tmp_path):
    """L2 + L4 데이터가 있는 테스트 서고.

    실제 프로젝트 경로 규칙을 따른다:
      documents/doc001/L2_ocr/vol1_page_001.json
      documents/doc001/L4_text/pages/vol1_page_001.txt
    """
    doc_dir = tmp_path / "documents" / "doc001"

    # L2 OCR 결과 (실제 L2 스키마 형식: lines 배열)
    l2_dir = doc_dir / "L2_ocr"
    l2_dir.mkdir(parents=True)
    l2_data = {
        "part_id": "vol1",
        "page_number": 1,
        "ocr_results": [
            {
                "layout_block_id": "p01_b01",
                "lines": [
                    {"text": "王戎簡要裵楷通", "bbox": [0, 0, 50, 350]},
                ],
            },
            {
                "layout_block_id": "p01_b02",
                "lines": [
                    {"text": "孔明臥龍", "bbox": [0, 0, 50, 200]},
                    {"text": "呂望非熊", "bbox": [0, 200, 50, 400]},
                ],
            },
        ],
    }
    with open(l2_dir / "vol1_page_001.json", "w", encoding="utf-8") as f:
        json.dump(l2_data, f, ensure_ascii=False)

    # L4 확정 텍스트 (plain text)
    l4_dir = doc_dir / "L4_text" / "pages"
    l4_dir.mkdir(parents=True)
    l4_text = "王戎簡要裴楷清通\n孔明臥龍\n呂望非熊\n"
    with open(l4_dir / "vol1_page_001.txt", "w", encoding="utf-8") as f:
        f.write(l4_text)

    return tmp_path


class TestAlignPage:
    def test_basic(self, test_library, variant_dict):
        """기본 대조: 2블록 + 페이지 전체."""
        results = align_page(
            str(test_library), "doc001", "vol1", 1,
            variant_dict=variant_dict,
        )

        # 블록 2개 + 페이지 전체(*) = 3개
        assert len(results) == 3

        # 마지막은 페이지 전체 대조
        page_result = results[-1]
        assert page_result.layout_block_id == "*"
        assert page_result.stats is not None
        assert page_result.stats.exact >= 10  # 대부분 일치

    def test_block_level_stats(self, test_library, variant_dict):
        """블록별 통계 확인."""
        results = align_page(
            str(test_library), "doc001", "vol1", 1,
            variant_dict=variant_dict,
        )

        # 블록 2 (孔明臥龍呂望非熊) 는 완전 일치해야 함
        b2 = [r for r in results if r.layout_block_id == "p01_b02"]
        assert len(b2) == 1
        assert b2[0].stats.accuracy == 1.0

    def test_page_total_includes_variant(self, test_library, variant_dict):
        """페이지 전체 대조에 이체자가 포함되는지."""
        results = align_page(
            str(test_library), "doc001", "vol1", 1,
            variant_dict=variant_dict,
        )
        page_result = results[-1]
        assert page_result.stats.variant >= 1  # 裵/裴

    def test_missing_l2(self, test_library):
        """L2 파일이 없으면 에러."""
        results = align_page(str(test_library), "doc001", "vol1", 999)
        assert len(results) == 1
        assert results[0].error is not None
        assert "L2" in results[0].error

    def test_missing_l4(self, tmp_path):
        """L4 파일이 없으면 에러."""
        # L2만 만들고 L4는 안 만듦
        doc_dir = tmp_path / "documents" / "doc002"
        l2_dir = doc_dir / "L2_ocr"
        l2_dir.mkdir(parents=True)
        l2_data = {
            "part_id": "vol1",
            "page_number": 1,
            "ocr_results": [
                {"layout_block_id": "b01", "lines": [{"text": "테스트"}]},
            ],
        }
        with open(l2_dir / "vol1_page_001.json", "w", encoding="utf-8") as f:
            json.dump(l2_data, f, ensure_ascii=False)

        results = align_page(str(tmp_path), "doc002", "vol1", 1)
        assert results[0].error is not None
        assert "L4" in results[0].error

    def test_to_dict_serializable(self, test_library, variant_dict):
        """결과가 JSON 직렬화 가능한지."""
        results = align_page(
            str(test_library), "doc001", "vol1", 1,
            variant_dict=variant_dict,
        )
        for result in results:
            d = result.to_dict()
            # JSON으로 변환 가능해야 함
            serialized = json.dumps(d, ensure_ascii=False)
            assert len(serialized) > 0

    def test_multiline_l2_block(self, test_library, variant_dict):
        """L2 블록에 여러 줄이 있을 때 텍스트가 합쳐지는지."""
        results = align_page(
            str(test_library), "doc001", "vol1", 1,
            variant_dict=variant_dict,
        )
        # p01_b02는 2줄 (孔明臥龍 + 呂望非熊)
        b2 = [r for r in results if r.layout_block_id == "p01_b02"]
        assert len(b2) == 1
        assert b2[0].ocr_text == "孔明臥龍呂望非熊"
