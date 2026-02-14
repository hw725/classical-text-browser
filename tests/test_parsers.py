"""서지정보 파서 테스트.

Phase 5: NDL Search, 국립공문서관 파서 동작 확인.
네트워크 접근이 필요한 테스트는 실제 API를 호출한다.
"""

import asyncio
import sys
from pathlib import Path

import pytest

# src/ 디렉토리를 경로에 추가
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)


class TestParserRegistry:
    """파서 레지스트리 테스트."""

    def test_list_parsers(self):
        """등록된 파서 목록이 반환된다."""
        from parsers.base import list_parsers
        import parsers  # noqa: F401 — 자동 등록 트리거

        result = list_parsers()
        assert len(result) >= 2

        ids = [p["id"] for p in result]
        assert "ndl" in ids
        assert "japan_national_archives" in ids

    def test_get_parser(self):
        """parser_id로 fetcher/mapper를 가져올 수 있다."""
        from parsers.base import get_parser
        import parsers  # noqa: F401

        fetcher, mapper = get_parser("ndl")
        assert fetcher.parser_id == "ndl"
        assert mapper.parser_id == "ndl"

    def test_get_parser_not_found(self):
        """존재하지 않는 parser_id는 KeyError."""
        from parsers.base import get_parser

        with pytest.raises(KeyError):
            get_parser("nonexistent")

    def test_registry_json(self):
        """registry.json을 읽을 수 있다."""
        from parsers.base import get_registry_json

        data = get_registry_json()
        assert "parsers" in data
        assert len(data["parsers"]) >= 2


class TestNdlParser:
    """NDL Search 파서 테스트 (네트워크 필요)."""

    @pytest.mark.asyncio
    async def test_search_monggu(self):
        """'蒙求'로 NDL 검색 시 결과가 반환된다."""
        import parsers  # noqa: F401
        from parsers.base import get_parser

        fetcher, _mapper = get_parser("ndl")
        results = await fetcher.search("蒙求", cnt=5)

        assert len(results) > 0
        # 첫 번째 결과에 제목이 있어야 한다
        assert results[0]["title"] is not None
        # raw 데이터가 포함되어야 한다
        assert "raw" in results[0]
        assert results[0]["raw"].get("dc:title") is not None

    @pytest.mark.asyncio
    async def test_map_to_bibliography(self):
        """NDL 검색 결과를 bibliography.json 형식으로 매핑할 수 있다."""
        import parsers  # noqa: F401
        from parsers.base import get_parser

        fetcher, mapper = get_parser("ndl")
        results = await fetcher.search("蒙求", cnt=3)
        assert len(results) > 0

        # 첫 번째 결과를 매핑
        bib = mapper.map_to_bibliography(results[0]["raw"])

        # 필수 필드 확인
        assert "title" in bib
        assert bib["title"] is not None
        assert "raw_metadata" in bib
        assert bib["raw_metadata"]["source_system"] == "ndl"
        assert "_mapping_info" in bib
        assert bib["_mapping_info"]["parser_id"] == "ndl"
        assert bib["_mapping_info"]["api_variant"] == "opensearch"

    @pytest.mark.asyncio
    async def test_mapping_fields(self):
        """매핑된 필드가 bibliography.schema.json 구조를 따른다."""
        import parsers  # noqa: F401
        from parsers.base import get_parser

        fetcher, mapper = get_parser("ndl")
        results = await fetcher.search("蒙求", cnt=1)
        assert len(results) > 0

        bib = mapper.map_to_bibliography(results[0]["raw"])

        # 스키마 필드 존재 확인
        expected_fields = [
            "title", "title_reading", "alternative_titles",
            "creator", "contributors", "date_created",
            "edition_type", "physical_description",
            "subject", "classification", "series_title",
            "material_type", "repository", "digital_source",
            "raw_metadata", "_mapping_info", "notes",
        ]
        for field in expected_fields:
            assert field in bib, f"필드 누락: {field}"

        # edition_type은 NDL에 없으므로 None
        assert bib["edition_type"] is None

        # digital_source 구조 확인
        if bib["digital_source"]:
            assert bib["digital_source"]["platform"] == "NDL Search (国立国会図書館サーチ)"


class TestNdlMapperUnit:
    """NDL Mapper 단위 테스트 (네트워크 불필요)."""

    def test_map_minimal_data(self):
        """최소 데이터로도 매핑이 성공한다."""
        from parsers.ndl import NdlMapper

        mapper = NdlMapper()
        raw = {"dc:title": "テスト"}

        bib = mapper.map_to_bibliography(raw)
        assert bib["title"] == "テスト"
        assert bib["creator"] is None
        assert bib["edition_type"] is None

    def test_map_full_data(self):
        """전체 필드가 있는 데이터를 매핑한다."""
        from parsers.ndl import NdlMapper

        mapper = NdlMapper()
        raw = {
            "dc:title": "蒙求",
            "dcndl:titleTranscription": "モウギュウ",
            "dc:creator": "李瀚",
            "dcndl:creatorTranscription": "リ カン",
            "dcterms:issued": "2024.2",
            "dc:extent": "174 p",
            "dcndl:materialType": "図書",
            "dcndl:NDLC": "Y84",
            "dcndl:NDC10": "726.1",
            "dcndl:NDLBibID": "033286846",
            "dcndl:seriesTitle": "FUZ comics",
            "rdfs:seeAlso": "https://ndlsearch.ndl.go.jp/books/R100000002-I033286846",
        }

        bib = mapper.map_to_bibliography(raw)
        assert bib["title"] == "蒙求"
        assert bib["title_reading"] == "モウギュウ"
        assert bib["creator"]["name"] == "李瀚"
        assert bib["creator"]["name_reading"] == "リ カン"
        assert bib["date_created"] == "2024.2"
        assert bib["physical_description"] == "174 p"
        assert bib["material_type"] == "図書"
        assert bib["classification"]["NDLC"] == "Y84"
        assert bib["classification"]["NDC10"] == "726.1"
        assert bib["series_title"] == "FUZ comics"
        assert bib["digital_source"]["system_ids"]["NDLBibID"] == "033286846"
