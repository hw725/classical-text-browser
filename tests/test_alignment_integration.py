"""정렬 엔진 통합 테스트.

전체 흐름: L2 + L4 데이터 → align_page → 블록별 + 페이지 전체 대조.
실제 프로젝트 경로 규칙 준수.
"""

import json

import pytest

from src.core.alignment import (
    AlignmentStats,
    BlockAlignment,
    MatchType,
    VariantCharDict,
    align_page,
    align_texts,
    compute_stats,
)


@pytest.fixture
def variant_dict(tmp_path):
    """이체자 사전."""
    data = {
        "variants": {
            "裴": ["裵"], "裵": ["裴"],
            "說": ["説"], "説": ["說"],
        },
    }
    path = tmp_path / "variants.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return VariantCharDict(str(path))


@pytest.fixture
def full_test_library(tmp_path):
    """3블록 L2 + L4 텍스트가 있는 테스트 서고.

    경로 규칙:
      documents/monggu_test/L2_ocr/vol1_page_001.json
      documents/monggu_test/L4_text/pages/vol1_page_001.txt
    """
    doc_dir = tmp_path / "documents" / "monggu_test"

    # L2 OCR 결과
    l2_dir = doc_dir / "L2_ocr"
    l2_dir.mkdir(parents=True)
    l2_data = {
        "part_id": "vol1",
        "page_number": 1,
        "ocr_engine": "dummy",
        "ocr_results": [
            {
                "layout_block_id": "p01_b01",
                "lines": [
                    {"text": "王戎簡要", "bbox": [0, 0, 50, 200]},
                    {"text": "裵楷通", "bbox": [0, 200, 50, 350]},
                ],
            },
            {
                "layout_block_id": "p01_b02",
                "lines": [
                    {"text": "孔明臥龍", "bbox": [100, 0, 150, 200]},
                    {"text": "呂望非熊", "bbox": [100, 200, 150, 400]},
                ],
            },
            {
                "layout_block_id": "p01_b03",
                "lines": [
                    {"text": "楊震關西", "bbox": [200, 0, 250, 200]},
                    {"text": "丁寬巨鹿", "bbox": [200, 200, 250, 400]},
                ],
            },
        ],
    }
    with open(l2_dir / "vol1_page_001.json", "w", encoding="utf-8") as f:
        json.dump(l2_data, f, ensure_ascii=False)

    # L4 확정 텍스트
    l4_dir = doc_dir / "L4_text" / "pages"
    l4_dir.mkdir(parents=True)
    # 裴(L4) vs 裵(L2): 이체자
    # 清(L4)이 L2에 없음: OCR 누락
    # 寬(L2) vs 寒(L4): OCR 오류
    l4_text = "王戎簡要\n裴楷清通\n孔明臥龍\n呂望非熊\n楊震關西\n丁寒巨鹿\n"
    with open(l4_dir / "vol1_page_001.txt", "w", encoding="utf-8") as f:
        f.write(l4_text)

    return tmp_path


class TestAlignmentIntegration:
    def test_full_flow(self, full_test_library, variant_dict):
        """전체 흐름: align_page → 블록별 + 페이지 전체 결과 검증."""
        results = align_page(
            str(full_test_library), "monggu_test", "vol1", 1,
            variant_dict=variant_dict,
        )

        # 블록 3개 + 페이지 전체(*) = 4개
        assert len(results) == 4

        # 마지막은 페이지 전체
        page_result = results[-1]
        assert page_result.layout_block_id == "*"
        assert page_result.stats is not None
        assert page_result.stats.total_chars > 0

        # 이체자 1개 이상 (裵/裴)
        assert page_result.stats.variant >= 1

    def test_block2_perfect_match(self, full_test_library, variant_dict):
        """블록 2 (孔明臥龍呂望非熊)는 완전 일치."""
        results = align_page(
            str(full_test_library), "monggu_test", "vol1", 1,
            variant_dict=variant_dict,
        )
        b2 = [r for r in results if r.layout_block_id == "p01_b02"]
        assert len(b2) == 1
        assert b2[0].stats.accuracy == 1.0
        assert b2[0].stats.mismatch == 0

    def test_serialization(self, full_test_library, variant_dict):
        """전체 결과가 JSON 직렬화 가능한지."""
        results = align_page(
            str(full_test_library), "monggu_test", "vol1", 1,
            variant_dict=variant_dict,
        )
        for r in results:
            d = r.to_dict()
            serialized = json.dumps(d, ensure_ascii=False)
            # 역직렬화도 가능
            parsed = json.loads(serialized)
            assert parsed["layout_block_id"] == r.layout_block_id

    def test_empty_l2_text(self, tmp_path):
        """OCR 결과 블록의 텍스트가 비어있을 때."""
        doc_dir = tmp_path / "documents" / "empty_test"

        l2_dir = doc_dir / "L2_ocr"
        l2_dir.mkdir(parents=True)
        l2_data = {
            "part_id": "vol1",
            "page_number": 1,
            "ocr_results": [
                {"layout_block_id": "b01", "lines": [{"text": ""}]},
            ],
        }
        with open(l2_dir / "vol1_page_001.json", "w", encoding="utf-8") as f:
            json.dump(l2_data, f, ensure_ascii=False)

        l4_dir = doc_dir / "L4_text" / "pages"
        l4_dir.mkdir(parents=True)
        with open(l4_dir / "vol1_page_001.txt", "w", encoding="utf-8") as f:
            f.write("테스트 텍스트\n")

        results = align_page(str(tmp_path), "empty_test", "vol1", 1)
        # 빈 블록은 건너뜀, 페이지 전체만 있어야 함
        assert any(r.layout_block_id == "*" for r in results)

    def test_without_variant_dict(self, full_test_library):
        """이체자 사전 없이도 기본 동작 (variant 분류만 안 됨)."""
        results = align_page(
            str(full_test_library), "monggu_test", "vol1", 1,
            variant_dict=None,
        )
        assert len(results) >= 1
        page_result = results[-1]
        assert page_result.stats is not None
        # variant_dict 없으면 variant=0
        assert page_result.stats.variant == 0

    def test_align_texts_chinese_punctuation(self):
        """구두점이 포함된 고전 텍스트 대조."""
        pairs = align_texts(
            "王戎簡要。裴楷清通。",
            "王戎簡要。裴楷清通。",
        )
        assert all(p.match_type == MatchType.EXACT for p in pairs)
        assert len(pairs) == 10

    def test_stats_accuracy_calculation(self, variant_dict):
        """정확도 계산: exact + variant = 일치."""
        pairs = align_texts("王裵甲", "王裴乙", variant_dict=variant_dict)
        stats = compute_stats(pairs)
        # 王: exact, 裵/裴: variant, 甲/乙: mismatch
        assert stats.exact == 1
        assert stats.variant == 1
        assert stats.mismatch == 1
        assert abs(stats.accuracy - 2 / 3) < 0.001
