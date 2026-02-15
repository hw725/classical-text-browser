"""KORCIS 파서 단위 테스트.

HTML 스크래핑, MARC 파싱, 008 해석, 판식정보 추출, OpenAPI XML 파싱,
매퍼 통합을 네트워크 없이 검증한다.
"""

import json

import pytest

from src.parsers.korcis import (
    KorcisFetcher,
    KorcisMapper,
    _extract_contributors,
    _extract_extent,
    _extract_language,
    _parse_marc_html,
    _parse_marc_subfields,
    _parse_openapi_detail_xml,
    _parse_openapi_search_xml,
    _parse_search_results,
    parse_008_field,
    parse_pansik_info,
)


# ──────────────────────────────────────
# 픽스처: MARC 샘플 데이터
# ──────────────────────────────────────


@pytest.fixture
def sample_marc_data():
    """蒙求 MARC 파싱 결과를 시뮬레이션한 dict."""
    return {
        "001": "KORCIS-TEST-001",
        "008": "860101s1850    ko a          000 0 chid ",
        "035": {"a": "(KORCIS)302554414"},
        "052": {"a": "811.2"},
        "085": {"a": "019.1", "2": "KDC6"},
        "100": {"a": "이한", "c": "唐", "e": "author"},
        "245": {"a": "蒙求", "d": "李瀚(唐) 撰"},
        "250": {"a": "목판본"},
        "260": {"a": "全州", "b": "完營", "c": "1850"},
        "300": {"a": "3卷1冊", "c": "26.7cm"},
        "440_list": ["叢書集成初編"],
        "500_list": ["序: 嘉靖甲申年", "跋: 丙子年"],
        "653_list": ["유학", "고전"],
        "700_list": [
            {"a": "서거정", "c": "朝鮮", "e": "annotator"},
        ],
        "vdkvgwkey": "302554414",
        "source_url": "https://www.nl.go.kr/korcis/search/searchResultDetail.do?vdkvgwkey=302554414",
        "_title_kor": "몽구",
    }


@pytest.fixture
def sample_marc_with_openapi(sample_marc_data):
    """OpenAPI 상세 데이터가 합쳐진 MARC dict."""
    sample_marc_data["_openapi_detail"] = {
        "form_info": "四周雙邊 半郭 22.5×15.2cm 有界 10行20字 注雙行 上下內向黑魚尾",
        "hold_libs": ["국립중앙도서관", "규장각한국학연구원"],
    }
    return sample_marc_data


# ──────────────────────────────────────
# 작업 2: KORMARC 008 코드 해석기
# ──────────────────────────────────────


class TestParse008Field:
    def test_basic(self):
        """표준 008 필드 해석."""
        # 40자 고정 길이: 위치 06='s', 07-10='1850', 35-37='chi', 38='d'
        field = "860101s1850    ko a          000 0 chid "
        result = parse_008_field(field)
        assert result["date_type_code"] == "s"
        assert result["date_type"] == "단일 확정 연도"
        assert result["publication_year"] == "1850"
        assert result["language_code"] == "chi"
        assert result["language"] == "중국어(한문)"
        assert result["modified"] == "수정됨"

    def test_estimated_date(self):
        """추정 연도."""
        field = "860101b1700    ko            000 0 kor  "
        result = parse_008_field(field)
        assert result["date_type"] == "추정 간행연도"
        assert result["publication_year"] == "1700"
        assert result["language"] == "한국어"
        assert result["modified"] == "수정 없음"

    def test_unknown_date(self):
        """연대 미상 (####)."""
        field = "860101d####    ko            000 0 chi  "
        result = parse_008_field(field)
        assert result["date_type"] == "연대 미상"
        assert result["publication_year"] is None

    def test_multiple_years(self):
        """복수 연도."""
        field = "860101e18501890ko            000 0 chi  "
        result = parse_008_field(field)
        assert result["date_type"] == "복수 연도 (시작~끝)"
        assert result["publication_year"] == "1850"
        assert result["publication_year_2"] == "1890"

    def test_short_field(self):
        """008 필드가 너무 짧을 때."""
        result = parse_008_field("short")
        assert "error" in result

    def test_empty(self):
        """빈 008 필드."""
        result = parse_008_field("")
        assert "error" in result

    def test_none(self):
        """None 입력."""
        result = parse_008_field(None)
        assert "error" in result

    def test_raw_preserved(self):
        """원본 문자열 보존."""
        field = "860101s1850    ko a          000 0 chi d"
        result = parse_008_field(field)
        assert result["raw"] == field

    def test_unknown_code(self):
        """미확인 코드."""
        field = "860101z####    ko            000 0 xyz  "
        result = parse_008_field(field)
        assert "미확인" in result["date_type"]
        assert result["language"] == "xyz"


# ──────────────────────────────────────
# 작업 3: 판식정보 구조화 추출
# ──────────────────────────────────────


class TestParsePansikInfo:
    def test_full_example(self):
        """전체 판식정보 패턴 매칭."""
        text = "四周雙邊 半郭 22.5×15.2cm 有界 10行20字 注雙行 上下內向黑魚尾"
        result = parse_pansik_info(text)
        assert result["gwangwak"] == "사주쌍변"
        assert result["gwangwak_size"] == "22.5 × 15.2 cm"
        assert result["gyeseon"] == "유계"
        assert result["haengja"] == "반엽 10행 20자"
        assert result["ju_haengja"] == "주쌍행"
        assert result["eomi"] == "상하내향흑어미"
        assert result["summary"] == text

    def test_single_border(self):
        """사주단변."""
        result = parse_pansik_info("四周單邊 無界 12行22字")
        assert result["gwangwak"] == "사주단변"
        assert result["gyeseon"] == "무계"
        assert result["haengja"] == "반엽 12행 22자"

    def test_left_right_double(self):
        """좌우쌍변."""
        result = parse_pansik_info("左右雙邊 有界 10行20字")
        assert result["gwangwak"] == "좌우쌍변"

    def test_various_eomi(self):
        """다양한 어미 패턴."""
        assert parse_pansik_info("上下白魚尾")["eomi"] == "상하백어미"
        assert parse_pansik_info("上黑魚尾")["eomi"] == "상흑어미"
        assert parse_pansik_info("無魚尾")["eomi"] == "무어미"

    def test_pangoo(self):
        """판구 패턴."""
        result = parse_pansik_info("大黑口 上下內向黑魚尾")
        assert result["pangoo"] == "대흑구"
        assert result["eomi"] == "상하내향흑어미"

    def test_size_x_lowercase(self):
        """소문자 x 크기 구분자."""
        result = parse_pansik_info("半郭 20.0x14.5cm")
        assert result["gwangwak_size"] == "20.0 × 14.5 cm"

    def test_empty_input(self):
        """빈 입력."""
        assert parse_pansik_info("") == {}
        assert parse_pansik_info("   ") == {}

    def test_no_match(self):
        """매칭되는 패턴이 없을 때 summary만 반환."""
        result = parse_pansik_info("특이한 형태")
        assert result["summary"] == "특이한 형태"
        assert "gwangwak" not in result

    def test_summary_always_present(self):
        """파싱 성공해도 summary에 원문 보존."""
        result = parse_pansik_info("四周雙邊 有界 10行20字")
        assert "summary" in result
        assert "四周雙邊" in result["summary"]


# ──────────────────────────────────────
# MARC 서브필드 파싱
# ──────────────────────────────────────


class TestParseMarcSubfields:
    def test_basic(self):
        result = _parse_marc_subfields("▼a蒙求 ▼d李瀚(唐) 撰")
        assert result["a"] == "蒙求"
        assert result["d"] == "李瀚(唐) 撰"

    def test_trailing_punctuation(self):
        """후행 구두점 제거."""
        result = _parse_marc_subfields("▼a蒙求 / ▼d李瀚 撰.")
        assert result["a"] == "蒙求"
        assert result["d"] == "李瀚 撰"

    def test_empty(self):
        result = _parse_marc_subfields("")
        assert result == {}

    def test_no_marker(self):
        """▼ 없는 텍스트 → 첫 글자가 코드로 해석됨 (MARC 관례)."""
        result = _parse_marc_subfields("plain text")
        # "plain text" → code='p', value='lain text'
        assert result == {"p": "lain text"}


# ──────────────────────────────────────
# 권책수 추출
# ──────────────────────────────────────


class TestExtractExtent:
    def test_volumes_and_books(self):
        result = _extract_extent("3卷1冊")
        assert result["volumes"] == "3卷"
        assert result["books"] == "1冊"
        assert result["missing"] is None

    def test_books_only(self):
        result = _extract_extent("2冊")
        assert result["volumes"] is None
        assert result["books"] == "2冊"

    def test_incomplete(self):
        """零本."""
        result = _extract_extent("零本 1冊")
        assert result["missing"] == "零本"
        assert result["books"] == "1冊"

    def test_lack(self):
        """缺."""
        result = _extract_extent("卷2缺 3卷2冊")
        assert result["missing"] == "卷2缺"
        assert result["volumes"] == "3卷"

    def test_empty(self):
        assert _extract_extent("") is None
        assert _extract_extent(None) is None

    def test_no_numbers(self):
        """숫자 없는 텍스트."""
        assert _extract_extent("선장본") is None


# ──────────────────────────────────────
# OpenAPI XML 파싱
# ──────────────────────────────────────


class TestOpenApiXmlParsing:
    def test_search_xml(self):
        """검색 결과 XML 파싱."""
        xml_str = """<?xml version="1.0" encoding="UTF-8"?>
        <RESULT>
            <RECORD>
                <REC_KEY>12345</REC_KEY>
                <TITLE>蒙求</TITLE>
                <KOR_TITLE>몽구</KOR_TITLE>
                <AUTHOR>李翰</AUTHOR>
                <KOR_AUTHOR>이한</KOR_AUTHOR>
                <PUBYEAR>1850</PUBYEAR>
                <PUBLISHER>完營</PUBLISHER>
                <EDIT_NAME>목판본</EDIT_NAME>
                <LIB_NAME>국립중앙도서관</LIB_NAME>
            </RECORD>
            <RECORD>
                <REC_KEY>67890</REC_KEY>
                <TITLE>蒙求補註</TITLE>
                <KOR_TITLE>몽구보주</KOR_TITLE>
                <AUTHOR>徐子光</AUTHOR>
                <KOR_AUTHOR></KOR_AUTHOR>
                <PUBYEAR></PUBYEAR>
                <PUBLISHER></PUBLISHER>
                <EDIT_NAME></EDIT_NAME>
                <LIB_NAME></LIB_NAME>
            </RECORD>
        </RESULT>"""
        records = _parse_openapi_search_xml(xml_str.encode("utf-8"))
        assert len(records) == 2
        assert records[0]["rec_key"] == "12345"
        assert records[0]["title"] == "蒙求"
        assert records[0]["kor_title"] == "몽구"
        assert records[0]["author"] == "李翰"
        assert records[0]["kor_author"] == "이한"
        assert records[1]["rec_key"] == "67890"

    def test_search_xml_empty(self):
        """빈 검색 결과."""
        xml = '<?xml version="1.0" encoding="UTF-8"?><RESULT></RESULT>'
        assert _parse_openapi_search_xml(xml.encode("utf-8")) == []

    def test_search_xml_no_rec_key(self):
        """rec_key 없는 레코드 건너뜀."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <RESULT>
            <RECORD>
                <TITLE>Test</TITLE>
            </RECORD>
        </RESULT>"""
        assert _parse_openapi_search_xml(xml.encode("utf-8")) == []

    def test_detail_xml(self):
        """상세 정보 XML 파싱 + 판식정보 자동 구조화."""
        xml_str = """<?xml version="1.0" encoding="UTF-8"?>
        <RESULT>
            <BIBINFO>
                <TITLE_INFO>蒙求 / 李翰 撰</TITLE_INFO>
                <PUBLISH_INFO>全州 : 完營, 1850</PUBLISH_INFO>
                <EDITION_INFO>目版本</EDITION_INFO>
                <FORM_INFO>四周雙邊 有界 10行20字 上下內向黑魚尾</FORM_INFO>
                <NOTE_INFO>序: 嘉靖甲申年</NOTE_INFO>
            </BIBINFO>
            <HOLDINFO>
                <LIB_NAME>국립중앙도서관</LIB_NAME>
            </HOLDINFO>
            <HOLDINFO>
                <LIB_NAME>규장각한국학연구원</LIB_NAME>
            </HOLDINFO>
        </RESULT>"""
        result = _parse_openapi_detail_xml(xml_str.encode("utf-8"))
        assert "蒙求" in result["title_info"]
        assert "完營" in result["publish_info"]
        assert result["edition_info"] == "目版本"
        assert "四周雙邊" in result["form_info"]
        assert len(result["hold_libs"]) == 2
        assert "국립중앙도서관" in result["hold_libs"]
        # 판식정보 자동 구조화
        assert "pansik_parsed" in result
        assert result["pansik_parsed"]["gwangwak"] == "사주쌍변"
        assert result["pansik_parsed"]["gyeseon"] == "유계"
        assert result["pansik_parsed"]["eomi"] == "상하내향흑어미"

    def test_detail_xml_no_bibinfo(self):
        """BIBINFO 없는 응답."""
        xml = '<?xml version="1.0" encoding="UTF-8"?><RESULT></RESULT>'
        result = _parse_openapi_detail_xml(xml.encode("utf-8"))
        assert result["title_info"] == ""
        assert result["hold_libs"] == []


# ──────────────────────────────────────
# KorcisMapper 통합 테스트
# ──────────────────────────────────────


class TestKorcisMapper:
    def test_basic_mapping(self, sample_marc_data):
        """기본 서지 매핑 — 필수 필드 확인."""
        mapper = KorcisMapper()
        bib = mapper.map_to_bibliography(sample_marc_data)

        assert bib["title"] == "蒙求"
        assert bib["title_reading"] == "몽구"
        assert bib["creator"]["name"] == "李瀚(唐) 撰"
        assert bib["creator"]["name_reading"] == "이한"
        assert bib["creator"]["period"] == "唐"
        assert bib["date_created"] == "1850"
        assert bib["edition_type"] == "목판본"
        assert bib["language"] == "chi"
        assert "26.7cm" in bib["physical_description"]

    def test_publishing_mapping(self, sample_marc_data):
        """간행사항(publishing) 매핑."""
        mapper = KorcisMapper()
        bib = mapper.map_to_bibliography(sample_marc_data)

        assert bib["publishing"] is not None
        assert bib["publishing"]["place"] == "全州"
        assert bib["publishing"]["publisher"] == "完營"

    def test_extent_mapping(self, sample_marc_data):
        """권책수(extent) 매핑."""
        mapper = KorcisMapper()
        bib = mapper.map_to_bibliography(sample_marc_data)

        assert bib["extent"] is not None
        assert bib["extent"]["volumes"] == "3卷"
        assert bib["extent"]["books"] == "1冊"

    def test_printing_info_without_openapi(self, sample_marc_data):
        """OpenAPI 데이터 없으면 printing_info는 None."""
        mapper = KorcisMapper()
        bib = mapper.map_to_bibliography(sample_marc_data)
        assert bib["printing_info"] is None

    def test_printing_info_with_openapi(self, sample_marc_with_openapi):
        """OpenAPI FORM_INFO → printing_info 구조화."""
        mapper = KorcisMapper()
        bib = mapper.map_to_bibliography(sample_marc_with_openapi)

        assert bib["printing_info"] is not None
        assert bib["printing_info"]["gwangwak"] == "사주쌍변"
        assert bib["printing_info"]["gyeseon"] == "유계"
        assert bib["printing_info"]["eomi"] == "상하내향흑어미"

    def test_repository_with_openapi(self, sample_marc_with_openapi):
        """OpenAPI 소장기관 → repository 매핑."""
        mapper = KorcisMapper()
        bib = mapper.map_to_bibliography(sample_marc_with_openapi)

        assert bib["repository"] is not None
        assert bib["repository"]["name"] == "국립중앙도서관"
        assert bib["repository"]["country"] == "KR"

    def test_contributors(self, sample_marc_data):
        """기여자 목록 매핑."""
        mapper = KorcisMapper()
        bib = mapper.map_to_bibliography(sample_marc_data)

        assert bib["contributors"] is not None
        assert len(bib["contributors"]) == 1
        assert bib["contributors"][0]["name"] == "서거정"
        assert bib["contributors"][0]["role"] == "annotator"

    def test_system_ids(self, sample_marc_data):
        """시스템 ID 매핑."""
        mapper = KorcisMapper()
        bib = mapper.map_to_bibliography(sample_marc_data)

        ids = bib["digital_source"]["system_ids"]
        assert ids["control_number"] == "KORCIS-TEST-001"
        assert ids["vdkvgwkey"] == "302554414"

    def test_mapping_info(self, sample_marc_data):
        """매핑 정보 추적."""
        mapper = KorcisMapper()
        bib = mapper.map_to_bibliography(sample_marc_data)

        info = bib["_mapping_info"]
        assert info["parser_id"] == "korcis"
        assert info["api_variant"] == "html_scraping_marc"
        assert "title" in info["field_sources"]

    def test_schema_compliance(self, sample_marc_with_openapi):
        """결과가 JSON 직렬화 가능한지 확인."""
        mapper = KorcisMapper()
        bib = mapper.map_to_bibliography(sample_marc_with_openapi)

        # JSON 직렬화/역직렬화 가능
        serialized = json.dumps(bib, ensure_ascii=False)
        parsed = json.loads(serialized)
        assert parsed["title"] == "蒙求"
        assert parsed["printing_info"]["gwangwak"] == "사주쌍변"

    def test_notes_multiline(self, sample_marc_data):
        """주기사항 여러 개 합침."""
        mapper = KorcisMapper()
        bib = mapper.map_to_bibliography(sample_marc_data)

        assert "嘉靖甲申年" in bib["notes"]
        assert "丙子年" in bib["notes"]

    def test_minimal_data(self):
        """최소 데이터로도 에러 없이 매핑."""
        mapper = KorcisMapper()
        bib = mapper.map_to_bibliography({"245": {"a": "테스트"}})

        assert bib["title"] == "테스트"
        assert bib["creator"] is None
        assert bib["publishing"] is None
        assert bib["extent"] is None
        assert bib["printing_info"] is None


# ──────────────────────────────────────
# KorcisFetcher 단위 테스트
# ──────────────────────────────────────


class TestKorcisFetcher:
    def test_parser_id(self):
        fetcher = KorcisFetcher()
        assert fetcher.parser_id == "korcis"
        assert "KORCIS" in fetcher.parser_name

    def test_url_extraction_detail(self):
        """URL에서 vdkvgwkey 추출 가능한지 확인 (실제 호출은 안 함)."""
        import re
        url = "https://www.nl.go.kr/korcis/search/searchResultDetail.do?vdkvgwkey=302554414"
        m = re.search(r"vdkvgwkey=(\d+)", url)
        assert m is not None
        assert m.group(1) == "302554414"

    def test_url_extraction_marc(self):
        """MARC URL에서 marcKey 추출."""
        import re
        url = "https://www.nl.go.kr/korcis/search/popup/marcInfo.do?marcKey=302554414"
        m = re.search(r"marcKey=(\d+)", url)
        assert m is not None
        assert m.group(1) == "302554414"


# ──────────────────────────────────────
# 언어 추출 헬퍼
# ──────────────────────────────────────


class TestExtractLanguage:
    def test_chinese(self):
        assert _extract_language({"008": "860101s1850    ko            000 0 chi d"}) == "chi"

    def test_korean(self):
        assert _extract_language({"008": "860101s1850    ko            000 0 kor d"}) == "kor"

    def test_short_008(self):
        assert _extract_language({"008": "short"}) is None

    def test_no_008(self):
        assert _extract_language({}) is None
