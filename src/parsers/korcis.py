"""한국고문헌종합목록 (KORCIS) 파서.

대상: 국립중앙도서관 한국고문헌종합목록
URL: https://www.nl.go.kr/korcis/

접근 방법:
    - 검색: POST /korcis/search/simpleResultList.do
      파라미터: searchCondition=all, searchKeyword=검색어
    - 상세: 세션 쿠키 필요 (검색 → 상세 순서대로 접근)
    - MARC 팝업: GET /korcis/search/popup/marcInfo.do?vdkvgwkey=ID&marcKey=ID&marcTarget=BIB
      (직접 접근 가능, 가장 구조화된 데이터)

MARC 필드 매핑:
    100 ▼a → creator.name, ▼c → creator.period, ▼e → creator.role
    245 ▼a → title, ▼d → creator 원문
    250 ▼a → edition_type
    260 ▼a → 발행지, ▼b → 발행자, ▼c → date_created
    300 ▼a → physical_description (권책), ▼c → 크기
    440 ▼a → series_title
    500 ▼a → notes
    653 ▼a → subject
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from lxml import html as lxml_html

from parsers.base import BaseFetcher, BaseMapper, register_parser

# KORCIS 베이스 URL
_KORCIS_BASE = "https://www.nl.go.kr"

# KORCIS OpenAPI 엔드포인트
# 참조: academic-mcp/src/academic_mcp/providers/nl.py
_OPENAPI_SEARCH_URL = f"{_KORCIS_BASE}/korcis/openapi/search.do"
_OPENAPI_DETAIL_URL = f"{_KORCIS_BASE}/korcis/openapi/detail.do"

# 검색 URL
_SEARCH_URL = f"{_KORCIS_BASE}/korcis/search/simpleResultList.do"

# MARC 팝업 URL (GET 직접 접근 가능)
_MARC_URL = f"{_KORCIS_BASE}/korcis/search/popup/marcInfo.do"

# 상세 페이지 URL
_DETAIL_URL = f"{_KORCIS_BASE}/korcis/search/searchResultDetail.do"


class KorcisFetcher(BaseFetcher):
    """KORCIS에서 한국 고문헌 서지 데이터를 추출한다.

    왜 HTML 스크래핑 + MARC 파싱인가:
        KORCIS는 표준 API를 제공하지 않는다.
        검색 결과는 HTML 스크래핑, 상세 정보는 MARC 팝업(GET 가능)에서
        가져오는 것이 가장 안정적이다.
    """

    parser_id = "korcis"
    parser_name = "한국고문헌종합목록 (KORCIS)"
    api_variant = "html_scraping_marc"

    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        """키워드로 검색하여 후보 목록을 반환한다.

        입력:
            query — 검색어 (한글 또는 한자, 예: "몽구" 또는 "蒙求").
        출력:
            [{title, creator, item_id, summary, raw}, ...]
            item_id는 vdkvgwkey 값 (MARC 조회 키).

        왜 이렇게 하는가:
            검색 결과 HTML의 checkbox value에 메타데이터가
            ^ 구분자로 들어있어서 파싱이 용이하다.
        """
        data = {
            "searchCondition": "all",
            "searchKeyword": query,
        }

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.post(_SEARCH_URL, data=data)
            response.raise_for_status()

        return _parse_search_results(response.text)

    async def fetch_detail(self, item_id: str, **kwargs) -> dict[str, Any]:
        """MARC 팝업에서 상세 메타데이터를 가져온다.

        입력:
            item_id — vdkvgwkey 값 (예: "302554414").
        출력:
            MARC 필드를 파싱한 dict.

        왜 MARC 팝업을 사용하는가:
            상세 페이지는 세션 쿠키가 필요하지만,
            MARC 팝업은 GET으로 직접 접근할 수 있고
            구조화된 MARC 데이터를 제공한다.
        """
        params = {
            "vdkvgwkey": item_id,
            "marcKey": item_id,
            "marcTarget": "BIB",
        }

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(_MARC_URL, params=params)
            response.raise_for_status()

        marc_data = _parse_marc_html(response.text)
        marc_data["vdkvgwkey"] = item_id
        marc_data["source_url"] = (
            f"{_KORCIS_BASE}/korcis/search/searchResultDetail.do"
            f"?vdkvgwkey={item_id}"
        )
        return marc_data

    async def fetch_by_url(self, url: str) -> dict[str, Any]:
        """KORCIS URL에서 자료 ID를 추출하여 메타데이터를 가져온다.

        입력:
            url — KORCIS 페이지 URL.
                  예: https://www.nl.go.kr/korcis/search/searchResultDetail.do?vdkvgwkey=302554414
        출력:
            MARC 필드를 파싱한 dict.

        왜 이렇게 하는가:
            연구자가 KORCIS에서 복사한 URL을 붙여넣으면
            vdkvgwkey를 추출하여 MARC 데이터를 가져온다.
        """
        # vdkvgwkey 파라미터에서 ID 추출
        m = re.search(r"vdkvgwkey=(\d+)", url)
        if m:
            return await self.fetch_detail(m.group(1))

        # fnDetail('ID') 패턴에서 추출 (혹시 JS 링크를 복사한 경우)
        m = re.search(r"fnDetail\(['\"](\d+)['\"]\)", url)
        if m:
            return await self.fetch_detail(m.group(1))

        # marcKey 파라미터에서 ID 추출 (MARC 팝업 URL)
        m = re.search(r"marcKey=(\d+)", url)
        if m:
            return await self.fetch_detail(m.group(1))

        raise ValueError(
            f"KORCIS URL에서 자료 ID를 추출할 수 없습니다: {url}\n"
            "→ 지원 URL: https://www.nl.go.kr/korcis/search/searchResultDetail.do"
            "?vdkvgwkey=..."
        )


class KorcisMapper(BaseMapper):
    """KORCIS MARC 데이터를 bibliography.json 공통 스키마로 매핑한다.

    한국 고문헌 특성 고려:
        - 저자: 한자명 + 한글 독음 병기 (MARC 100/245)
        - 판종: 목판본, 활자본, 필사본, 영인본 등 (MARC 250)
        - 총서: 叢書 정보 (MARC 440)
        - 소장처: 여러 기관이 각각 소장 가능
    """

    parser_id = "korcis"

    def map_to_bibliography(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """KORCIS MARC 데이터를 bibliography.json 형식으로 변환한다.

        입력: raw_data — KorcisFetcher가 반환한 파싱된 MARC dict.
        출력: bibliography.schema.json 준수 dict.
        """
        # 저자 매핑
        # MARC 100이 있으면 100을 기본으로, 없으면 245 ▼d에서 추출
        creator = None
        marc100 = raw_data.get("100", {})
        marc245 = raw_data.get("245", {})
        if marc100.get("a"):
            creator = {
                "name": marc245.get("d") or marc100.get("a"),
                "name_reading": marc100.get("a"),
                "role": marc100.get("e") or "author",
                "period": marc100.get("c"),
            }
        elif marc245.get("d"):
            # 100 필드가 없을 때 245 ▼d에서 저자 추출
            creator = {
                "name": marc245["d"],
                "name_reading": None,
                "role": "author",
                "period": None,
            }

        # 발행사항 (MARC 260)
        marc260 = raw_data.get("260", {})

        # publishing 객체 (간행사항)
        publishing = None
        if marc260.get("a") or marc260.get("b"):
            publishing = {
                "place": marc260.get("a"),
                "publisher": marc260.get("b"),
                "publication_type": None,  # MARC 260에서는 간행 유형을 직접 제공하지 않음
            }

        # 형태사항
        marc300 = raw_data.get("300", {})
        physical_parts = []
        if marc300.get("a"):
            physical_parts.append(marc300["a"])
        if marc300.get("c"):
            physical_parts.append(marc300["c"])
        physical_description = " ; ".join(p for p in physical_parts if p) if physical_parts else None

        # extent 객체 (권책수)
        # MARC 300 ▼a에서 권(卷)과 책(冊) 정보 추출
        extent = _extract_extent(marc300.get("a", ""))

        # printing_info 객체 (판식정보)
        # OpenAPI enrichment로 form_info가 있으면 파싱
        printing_info = None
        openapi_data = raw_data.get("_openapi_detail", {})
        form_info_text = openapi_data.get("form_info", "")
        if form_info_text:
            pansik = parse_pansik_info(form_info_text)
            if pansik and len(pansik) > 1:  # summary 외에 파싱된 필드가 있으면
                printing_info = pansik

        # 008 필드 해석
        info_008 = {}
        marc008_raw = raw_data.get("008", "")
        if marc008_raw:
            info_008 = parse_008_field(marc008_raw)

        # 언어: 008 해석 결과 또는 기존 코드 추출
        language = _extract_language(raw_data)

        # 총서명 (440 필드, 여러 개 가능)
        series_titles = raw_data.get("440_list", [])
        series_title = " / ".join(series_titles) if series_titles else None

        # 주제어 (653 필드)
        subjects = raw_data.get("653_list", [])

        # 주기사항 (500 필드)
        notes_list = raw_data.get("500_list", [])
        notes = "\n".join(notes_list) if notes_list else None

        # 시스템 ID
        system_ids = {}
        control_no = raw_data.get("001")
        if control_no:
            system_ids["control_number"] = control_no
        vdkvgwkey = raw_data.get("vdkvgwkey")
        if vdkvgwkey:
            system_ids["vdkvgwkey"] = vdkvgwkey
        marc035 = raw_data.get("035", {})
        if marc035.get("a"):
            system_ids["system_control_number"] = marc035["a"]

        # 분류
        classification = {}
        marc052 = raw_data.get("052", {})
        if marc052.get("a"):
            classification["call_number"] = marc052["a"]
        marc085 = raw_data.get("085", {})
        if marc085.get("a"):
            classification["classification_number"] = marc085["a"]
            if marc085.get("2"):
                classification["classification_scheme"] = marc085["2"]

        # 소장기관 (OpenAPI enrichment에서)
        repository = None
        hold_libs = openapi_data.get("hold_libs", [])
        if hold_libs:
            # 첫 번째 소장기관을 대표로 설정
            repository = {
                "name": hold_libs[0],
                "name_ko": hold_libs[0],
                "country": "KR",
                "call_number": None,
            }

        # 매핑 소스 추적
        field_sources = {
            "title": self._field_source("MARC 245 ▼a", "exact"),
            "title_reading": self._field_source(
                "검색결과 한글 제목", "inferred", "검색 결과 HTML에서 추출"
            ),
            "creator.name": self._field_source("MARC 245 ▼d / 100 ▼a", "exact"),
            "creator.name_reading": self._field_source("MARC 100 ▼a", "exact"),
            "creator.period": self._field_source("MARC 100 ▼c", "exact"),
            "date_created": self._field_source("MARC 260 ▼c", "exact"),
            "edition_type": self._field_source("MARC 250 ▼a", "exact"),
            "physical_description": self._field_source("MARC 300 ▼a+▼c", "exact"),
            "series_title": self._field_source("MARC 440 ▼a", "exact"),
            "subject": self._field_source("MARC 653 ▼a", "exact"),
        }
        if publishing:
            field_sources["publishing"] = self._field_source("MARC 260 ▼a/▼b", "exact")
        if extent:
            field_sources["extent"] = self._field_source(
                "MARC 300 ▼a", "inferred", "정규식으로 권/책 추출"
            )
        if printing_info:
            field_sources["printing_info"] = self._field_source(
                "OpenAPI FORM_INFO", "inferred", "판식정보 텍스트에서 정규식 파싱"
            )
        if info_008 and "error" not in info_008:
            field_sources["language"] = self._field_source("MARC 008[35:38]", "exact")

        bibliography = {
            "title": marc245.get("a"),
            "title_reading": raw_data.get("_title_kor"),  # 검색 결과에서 추출된 한글 제목
            "alternative_titles": None,
            "creator": creator,
            "contributors": _extract_contributors(raw_data),
            "date_created": marc260.get("c"),
            "edition_type": raw_data.get("250", {}).get("a"),
            "language": language,
            "script": None,
            "physical_description": physical_description,
            "printing_info": printing_info,
            "publishing": publishing,
            "extent": extent,
            "subject": subjects if subjects else None,
            "classification": classification if classification else None,
            "series_title": series_title,
            "material_type": None,
            "repository": repository,
            "digital_source": {
                "platform": "한국고문헌종합목록 (KORCIS)",
                "source_url": raw_data.get("source_url"),
                "permanent_uri": None,
                "system_ids": system_ids if system_ids else None,
                "license": None,
                "accessed_at": None,
            },
            "raw_metadata": {
                "source_system": "korcis",
                **raw_data,
            },
            "_mapping_info": self._make_mapping_info(
                field_sources=field_sources,
                api_variant="html_scraping_marc",
            ),
            "notes": notes,
        }

        return bibliography


# --- HTML/MARC 파싱 유틸리티 ---


def _parse_search_results(html_text: str) -> list[dict[str, Any]]:
    """검색 결과 HTML을 파싱하여 항목 목록을 추출한다.

    왜 이렇게 하는가:
        KORCIS 검색 결과의 checkbox value에 메타데이터가 ^ 구분자로 들어있다.
        형식: ID^한자제목^한자저자^한자발행처^한자발행년^한글제목^한글저자^한글발행처^한글발행년^...
    """
    results = []
    try:
        tree = lxml_html.fromstring(html_text)

        # checkbox value에서 메타데이터 추출
        checkboxes = tree.cssselect("input[name='check']")
        for i, cb in enumerate(checkboxes):
            value = cb.get("value", "")
            parts = value.split("^")
            if len(parts) < 6:
                continue

            item_id = parts[0]           # vdkvgwkey
            title_hanja = parts[1]       # 한자 제목
            creator_hanja = parts[2]     # 한자 저자
            publisher_hanja = parts[3]   # 한자 발행처
            date_hanja = parts[4]        # 한자 발행년
            title_kor = parts[5] if len(parts) > 5 else ""  # 한글 제목
            creator_kor = parts[6] if len(parts) > 6 else ""  # 한글 저자

            # 요약 문자열 생성
            summary_parts = [title_hanja]
            if creator_hanja:
                summary_parts.append(f"/ {creator_hanja}")
            if date_hanja:
                summary_parts.append(f"({date_hanja})")
            summary = " ".join(summary_parts)

            results.append({
                "title": title_hanja,
                "title_kor": title_kor,
                "creator": creator_hanja,
                "item_id": item_id,
                "summary": summary,
                "raw": {
                    "vdkvgwkey": item_id,
                    "title_hanja": title_hanja,
                    "title_kor": title_kor,
                    "creator_hanja": creator_hanja,
                    "creator_kor": creator_kor,
                    "publisher_hanja": publisher_hanja,
                    "date_hanja": date_hanja,
                    "_title_kor": title_kor,
                },
            })

    except Exception:
        pass

    return results


def _parse_marc_html(html_text: str) -> dict[str, Any]:
    """MARC 팝업 HTML을 파싱하여 MARC 필드를 추출한다.

    왜 이렇게 하는가:
        MARC 팝업은 <table> 형태로 TAG / IND / 내용 컬럼을 제공한다.
        각 행에서 TAG 번호와 서브필드(▼a, ▼b 등)를 추출한다.
    """
    data: dict[str, Any] = {}

    try:
        tree = lxml_html.fromstring(html_text)
        rows = tree.cssselect("table.tbl tbody tr")

        # 반복 가능한 필드를 위한 리스트
        notes_list: list[str] = []
        series_list: list[str] = []
        subject_list: list[str] = []
        contributor_list: list[dict] = []

        for row in rows:
            cells = row.cssselect("td")
            if len(cells) < 3:
                continue

            tag = cells[0].text_content().strip()
            content = cells[2].text_content().strip()

            if not tag or not content:
                continue

            # 서브필드 파싱
            subfields = _parse_marc_subfields(content)

            if tag == "001":
                data["001"] = content
            elif tag == "008":
                data["008"] = content
            elif tag == "035":
                data["035"] = subfields
            elif tag == "052":
                data["052"] = subfields
            elif tag == "085":
                data["085"] = subfields
            elif tag == "100":
                data["100"] = subfields
            elif tag == "245":
                data["245"] = subfields
            elif tag == "246":
                data.setdefault("246_list", []).append(subfields)
            elif tag == "250":
                data["250"] = subfields
            elif tag == "260":
                data["260"] = subfields
            elif tag == "300":
                data["300"] = subfields
            elif tag == "440":
                title_a = subfields.get("a", "")
                num_n = subfields.get("n", "")
                full = f"{title_a} {num_n}".strip() if num_n else title_a
                if full:
                    series_list.append(full)
            elif tag == "500":
                note = subfields.get("a", content)
                if note:
                    notes_list.append(note)
            elif tag == "653":
                for val in subfields.values():
                    if val:
                        subject_list.append(val)
            elif tag == "700":
                contributor_list.append(subfields)
            elif tag == "740":
                data.setdefault("740_list", []).append(subfields.get("a", content))

        if notes_list:
            data["500_list"] = notes_list
        if series_list:
            data["440_list"] = series_list
        if subject_list:
            data["653_list"] = subject_list
        if contributor_list:
            data["700_list"] = contributor_list

    except Exception:
        pass

    return data


def _parse_marc_subfields(content: str) -> dict[str, str]:
    """MARC 서브필드 문자열을 파싱한다.

    입력: "▼a蒙求 / ▼d李瀚(後晉) 撰. ▼n1-2"
    출력: {"a": "蒙求 /", "d": "李瀚(後晉) 撰.", "n": "1-2"}

    왜 이렇게 하는가:
        KORCIS MARC 데이터에서 ▼ (U+25BC) 기호가 서브필드 구분자다.
        각 서브필드 코드(a, b, c 등)와 값을 분리한다.
    """
    result: dict[str, str] = {}

    # ▼ 기호로 분리
    parts = re.split(r"▼", content)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 첫 글자가 서브필드 코드
        code = part[0]
        value = part[1:].strip()
        # 후행 구두점 정리 (MARC 종결부호 /, ., ; 등)
        value = re.sub(r"[/;.,]+\s*$", "", value).strip()
        if value:
            result[code] = value

    return result


def _extract_contributors(raw_data: dict) -> list[dict] | None:
    """MARC 700 필드에서 기여자 목록을 추출한다."""
    contributors_raw = raw_data.get("700_list", [])
    if not contributors_raw:
        return None

    contributors = []
    for sub in contributors_raw:
        name = sub.get("a", "")
        if name:
            contributors.append({
                "name": name,
                "name_reading": None,
                "role": sub.get("e"),
                "period": sub.get("c"),
            })
    return contributors if contributors else None


def _extract_language(raw_data: dict) -> str | None:
    """MARC 008 필드에서 언어 코드를 추출한다.

    008 필드의 35-37 위치에 언어 코드가 있다.
    """
    marc008 = raw_data.get("008", "")
    if len(marc008) >= 38:
        lang = marc008[35:38].strip()
        if lang and lang != "   ":
            return lang
    return None


def _extract_extent(physical_desc: str) -> dict[str, Any] | None:
    """형태사항(MARC 300 ▼a)에서 권책수를 추출한다.

    입력:
        physical_desc — MARC 300 ▼a 값. 예: "3卷1冊", "卷1-2 2冊", "零本"
    출력:
        {"volumes": "3卷", "books": "1冊", "missing": null} 또는 None

    왜 이렇게 하는가:
        고서의 물리적 규모(권수·책수)를 구조화하면
        여러 문헌의 규모를 비교하거나 결락을 추적할 수 있다.
    """
    if not physical_desc:
        return None

    result: dict[str, Any] = {}

    # 권수 (卷): 숫자+卷 또는 "卷숫자-숫자"
    vol_match = re.search(r"(\d+)\s*卷", physical_desc)
    if vol_match:
        result["volumes"] = f"{vol_match.group(1)}卷"

    # 책수 (冊)
    book_match = re.search(r"(\d+)\s*冊", physical_desc)
    if book_match:
        result["books"] = f"{book_match.group(1)}冊"

    # 결락 (零本, 缺 등)
    if "零本" in physical_desc:
        result["missing"] = "零本"
    elif "缺" in physical_desc:
        lack_match = re.search(r"(卷\d+缺|[^,]+缺)", physical_desc)
        result["missing"] = lack_match.group(1) if lack_match else "缺"

    if not result:
        return None

    # 없는 필드는 null로 채움
    result.setdefault("volumes", None)
    result.setdefault("books", None)
    result.setdefault("missing", None)

    return result


# --- KORMARC 008 고서 코드 해석기 (작업 2) ---
#
# KORMARC의 008 필드(40자 고정 길이)에서 고서 관련 코드를 해석한다.
# 각 위치별 의미는 KORMARC 통합서지용 포맷 기반이다.

# 간행연대구분 (위치 06)
_DATE_TYPE_008 = {
    "a": "확실한 간행연도",
    "b": "추정 간행연도",
    "c": "세기 단위",
    "d": "연대 미상",
    "e": "복수 연도 (시작~끝)",
    "n": "연대 불명",
    "s": "단일 확정 연도",
    "m": "복수 확정 연도",
    "q": "의문스러운 연도",
    "r": "복간/영인 연도",
    " ": "미부호",
}

# 언어 코드 (위치 35-37, ISO 639-2/B 기반)
_LANG_CODES_008 = {
    "chi": "중국어(한문)",
    "kor": "한국어",
    "jpn": "일본어",
    "mul": "다국어",
    "und": "미확인",
    "   ": "미부호",
}

# 수정 기록 (위치 38)
_MODIFIED_008 = {
    " ": "수정 없음",
    "d": "수정됨",
    "o": "수정됨 (완전 개정)",
    "r": "수정됨 (일부 개정)",
    "s": "수정됨 (축약)",
    "x": "수정됨 (기타)",
}


def parse_008_field(field_008: str) -> dict[str, Any]:
    """KORMARC 008 필드를 해석한다.

    입력:
        field_008 — 40자 고정 길이 문자열.
    출력:
        해석된 딕셔너리. 주요 키:
        - date_type: 간행연대구분 (위치 06)
        - date_type_code: 원본 코드
        - publication_year: 간행연도 (위치 07-10)
        - publication_year_2: 두 번째 연도 (위치 11-14, 복수 연도일 때)
        - language: 언어 (위치 35-37)
        - language_code: 원본 언어 코드
        - modified: 수정 기록 (위치 38)
        - raw: 원본 문자열

    왜 이렇게 하는가:
        008 필드에는 간행 시기, 언어 등 핵심 서지 정보가 코드화되어 있다.
        이를 사람이 읽을 수 있는 한국어로 변환하면
        연구자가 서지 데이터를 쉽게 이해할 수 있다.
    """
    if not field_008 or len(field_008) < 35:
        return {"error": f"008 필드 길이 부족: {len(field_008) if field_008 else 0}자"}

    result: dict[str, Any] = {"raw": field_008}

    # 위치 06: 간행연대구분
    date_type_code = field_008[6] if len(field_008) > 6 else " "
    result["date_type_code"] = date_type_code
    result["date_type"] = _DATE_TYPE_008.get(date_type_code, f"미확인({date_type_code})")

    # 위치 07-10: 간행연도 (####은 미상)
    if len(field_008) >= 11:
        year_str = field_008[7:11]
        cleaned = year_str.replace("#", "").replace(" ", "").strip()
        result["publication_year"] = cleaned if cleaned else None
    else:
        result["publication_year"] = None

    # 위치 11-14: 두 번째 연도 (복수 연도일 때)
    if len(field_008) >= 15:
        year2_str = field_008[11:15]
        cleaned2 = year2_str.replace("#", "").replace(" ", "").strip()
        result["publication_year_2"] = cleaned2 if cleaned2 else None
    else:
        result["publication_year_2"] = None

    # 위치 35-37: 언어 코드
    if len(field_008) >= 38:
        lang_code = field_008[35:38]
        result["language_code"] = lang_code
        result["language"] = _LANG_CODES_008.get(lang_code, lang_code)
    else:
        result["language_code"] = None
        result["language"] = None

    # 위치 38: 수정 기록
    if len(field_008) >= 39:
        mod_code = field_008[38]
        result["modified"] = _MODIFIED_008.get(mod_code, f"미확인({mod_code})")
    else:
        result["modified"] = None

    return result


# --- 판식정보 구조화 추출 (작업 3) ---
#
# 고서의 판식정보(版式情報) 텍스트를 파싱하여 구조화된 필드로 분리한다.
# 판식정보는 형태서지학에서 판본 감별의 핵심 요소다.
#
# 입력 예: "四周雙邊 半郭 22.5×15.2cm 有界 10行20字 注雙行 上下內向黑魚尾"
# 출력: bibliography.schema.json의 printing_info 객체

# 광곽(匡郭) 패턴 → 한국어 독음
_GWANGWAK_PATTERNS = [
    (re.compile(r"四周雙邊"), "사주쌍변"),
    (re.compile(r"四周單邊"), "사주단변"),
    (re.compile(r"左右雙邊"), "좌우쌍변"),
    (re.compile(r"無邊"), "무변"),
]

# 어미(魚尾) 패턴 → 한국어 독음
# 순서 중요: 긴 패턴을 먼저 매칭해야 짧은 패턴에 잘못 걸리지 않는다.
_EOMI_PATTERNS = [
    (re.compile(r"上下內向二葉花紋魚尾"), "상하내향이엽화문어미"),
    (re.compile(r"上下內向花紋魚尾"), "상하내향화문어미"),
    (re.compile(r"上下內向黑魚尾"), "상하내향흑어미"),
    (re.compile(r"上下白魚尾"), "상하백어미"),
    (re.compile(r"上下黑魚尾"), "상하흑어미"),
    (re.compile(r"上黑魚尾"), "상흑어미"),
    (re.compile(r"下黑魚尾"), "하흑어미"),
    (re.compile(r"上白魚尾"), "상백어미"),
    (re.compile(r"下白魚尾"), "하백어미"),
    (re.compile(r"無魚尾"), "무어미"),
]

# 판구(版口) 패턴 → 한국어 독음
_PANGOO_PATTERNS = [
    (re.compile(r"大黑口"), "대흑구"),
    (re.compile(r"小黑口"), "소흑구"),
    (re.compile(r"白口"), "백구"),
]


def parse_pansik_info(text: str) -> dict[str, Any]:
    """판식정보 텍스트를 구조화된 딕셔너리로 변환한다.

    입력:
        text — 판식정보 원문 텍스트.
               예: "四周雙邊 半郭 22.5×15.2cm 有界 10行20字 注雙行 上下內向黑魚尾"
    출력:
        bibliography.schema.json의 printing_info 스키마에 대응하는 dict.
        파싱하지 못한 부분은 summary에 원문을 보존.

    왜 이렇게 하는가:
        판식정보의 형식은 표준화되어 있지 않아서 다양한 변형이 있다.
        정규식으로 주요 패턴을 매칭하고, 매칭 안 되는 부분은 원문으로 보존한다.
        완벽한 파싱보다 안전한 파싱 — 에러 없이 가능한 만큼만 추출.
    """
    if not text or not text.strip():
        return {}

    result: dict[str, Any] = {"summary": text.strip()}
    remaining = text.strip()

    # 1. 광곽 (匡郭)
    for pattern, value in _GWANGWAK_PATTERNS:
        if pattern.search(remaining):
            result["gwangwak"] = value
            remaining = pattern.sub("", remaining)
            break

    # 2. 반곽 크기 (세로×가로 cm)
    size_match = re.search(
        r"(?:半郭)?\s*(\d+\.?\d*)\s*[×xX]\s*(\d+\.?\d*)\s*(?:cm|㎝)",
        remaining, re.IGNORECASE,
    )
    if size_match:
        result["gwangwak_size"] = f"{size_match.group(1)} × {size_match.group(2)} cm"
        remaining = remaining[:size_match.start()] + remaining[size_match.end():]

    # "半郭" 단독 키워드 제거 (크기와 함께 쓰이지 않은 경우)
    remaining = re.sub(r"半郭", "", remaining)

    # 3. 계선 (界線)
    if "有界" in remaining:
        result["gyeseon"] = "유계"
        remaining = remaining.replace("有界", "")
    elif "無界" in remaining:
        result["gyeseon"] = "무계"
        remaining = remaining.replace("無界", "")

    # 4. 행자수 (行字數)
    hj_match = re.search(r"(\d+)\s*行\s*(\d+)\s*字", remaining)
    if hj_match:
        rows = int(hj_match.group(1))
        chars = int(hj_match.group(2))
        result["haengja"] = f"반엽 {rows}행 {chars}자"
        remaining = remaining[:hj_match.start()] + remaining[hj_match.end():]

    # 5. 주(注) 행자수
    ju_match = re.search(r"注雙行|주쌍행", remaining)
    if ju_match:
        result["ju_haengja"] = "주쌍행"
        remaining = remaining[:ju_match.start()] + remaining[ju_match.end():]
    else:
        ju_match2 = re.search(r"注單行|주단행", remaining)
        if ju_match2:
            result["ju_haengja"] = "주단행"
            remaining = remaining[:ju_match2.start()] + remaining[ju_match2.end():]

    # 6. 판구 (版口)
    for pattern, value in _PANGOO_PATTERNS:
        if pattern.search(remaining):
            result["pangoo"] = value
            remaining = pattern.sub("", remaining)
            break

    # 7. 어미 (魚尾) — 긴 패턴 우선
    for pattern, value in _EOMI_PATTERNS:
        if pattern.search(remaining):
            result["eomi"] = value
            remaining = pattern.sub("", remaining)
            break

    # 8. 판심제 (版心題) — "版心題 <서명>" 패턴
    pansimje_match = re.search(r"版心題\s*[:：]?\s*(.+?)(?:\s{2,}|$)", remaining)
    if pansimje_match:
        result["pansimje"] = pansimje_match.group(1).strip()
        remaining = remaining[:pansimje_match.start()] + remaining[pansimje_match.end():]

    return result


# --- KORCIS OpenAPI 유틸리티 (작업 4) ---
#
# academic-mcp/src/academic_mcp/providers/nl.py를 참조하여 구현.
# 기존 HTML 스크래핑과 별도로, OpenAPI를 통한 검색/상세 조회를 제공한다.
# OpenAPI의 장점: FORM_INFO(판식정보), HOLDINFO(소장기관) 등
# HTML 스크래핑에서는 얻기 어려운 필드를 제공한다.


def _get_xml_text(element: ET.Element | None, tag: str) -> str:
    """XML 요소에서 텍스트를 안전하게 추출한다.

    왜 별도 함수인가:
        ET.Element.find()가 None을 반환할 수 있고,
        child.text도 None일 수 있어서 안전하게 처리해야 한다.
    """
    if element is None:
        return ""
    child = element.find(tag)
    if child is None or not child.text:
        return ""
    return child.text.strip()


async def openapi_search(
    query: str,
    max_results: int = 20,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """KORCIS OpenAPI로 검색한다.

    입력:
        query — 검색어 (한글 또는 한자).
        max_results — 최대 결과 수 (기본 20, 최대 100).
        api_key — API 키 (현재 KORCIS OpenAPI는 키 없이도 동작).
    출력:
        [{rec_key, title, kor_title, author, kor_author,
          pub_year, publisher, edit_name, lib_name}, ...]

    왜 이렇게 하는가:
        기존 HTML 스크래핑 대비 OpenAPI의 장점:
        - 안정적인 XML 응답 형식 (HTML 구조 변경에 영향 없음)
        - 표준화된 필드명 (REC_KEY, TITLE 등)
        - 상세 조회 시 FORM_INFO(판식정보) 제공
    """
    params: dict[str, str] = {
        "search_field": "total",
        "search_value": query,
        "page": "1",
        "display": str(min(max_results, 100)),
    }
    if api_key:
        params["key"] = api_key

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(_OPENAPI_SEARCH_URL, params=params)
            response.raise_for_status()

        return _parse_openapi_search_xml(response.content)

    except Exception as e:
        raise ConnectionError(
            f"KORCIS OpenAPI 검색 실패: {e}\n"
            f"→ URL: {_OPENAPI_SEARCH_URL}"
        ) from e


async def openapi_detail(
    rec_key: str,
    api_key: str | None = None,
) -> dict[str, Any]:
    """KORCIS OpenAPI로 상세 정보를 조회한다.

    입력:
        rec_key — 레코드 키 (검색 결과의 REC_KEY).
        api_key — API 키 (현재 KORCIS OpenAPI는 키 없이도 동작).
    출력:
        {title_info, publish_info, edition_info, form_info, note_info,
         hold_libs: [...], pansik_parsed: {...}}

        form_info가 있으면 parse_pansik_info()로 자동 구조화.

    왜 이렇게 하는가:
        OpenAPI 상세 조회의 FORM_INFO 필드에 판식정보가 들어있다.
        이를 parse_pansik_info()와 연결하면 구조화된 판식정보를 얻을 수 있다.
        MARC 팝업에서는 FORM_INFO를 직접 제공하지 않아서
        OpenAPI가 필요한 이유다.
    """
    params: dict[str, str] = {"rec_key": rec_key}
    if api_key:
        params["key"] = api_key

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(_OPENAPI_DETAIL_URL, params=params)
            response.raise_for_status()

        return _parse_openapi_detail_xml(response.content)

    except Exception as e:
        raise ConnectionError(
            f"KORCIS OpenAPI 상세 조회 실패 (rec_key={rec_key}): {e}\n"
            f"→ URL: {_OPENAPI_DETAIL_URL}"
        ) from e


def _parse_openapi_search_xml(xml_bytes: bytes) -> list[dict[str, Any]]:
    """OpenAPI 검색 결과 XML을 파싱한다.

    XML 구조:
        <RESULT>
          <RECORD>
            <REC_KEY>...</REC_KEY>
            <TITLE>한자제목</TITLE>
            <KOR_TITLE>한글제목</KOR_TITLE>
            <AUTHOR>한자저자</AUTHOR>
            <KOR_AUTHOR>한글저자</KOR_AUTHOR>
            <PUBYEAR>발행년</PUBYEAR>
            <PUBLISHER>발행처</PUBLISHER>
            <EDIT_NAME>판종</EDIT_NAME>
            <LIB_NAME>소장기관</LIB_NAME>
          </RECORD>
          ...
        </RESULT>
    """
    records: list[dict[str, Any]] = []
    root = ET.fromstring(xml_bytes)

    for record in root.findall(".//RECORD"):
        rec_key = _get_xml_text(record, "REC_KEY")
        if not rec_key:
            continue

        records.append({
            "rec_key": rec_key,
            "title": _get_xml_text(record, "TITLE"),
            "kor_title": _get_xml_text(record, "KOR_TITLE"),
            "author": _get_xml_text(record, "AUTHOR"),
            "kor_author": _get_xml_text(record, "KOR_AUTHOR"),
            "pub_year": _get_xml_text(record, "PUBYEAR"),
            "publisher": _get_xml_text(record, "PUBLISHER"),
            "edit_name": _get_xml_text(record, "EDIT_NAME"),
            "lib_name": _get_xml_text(record, "LIB_NAME"),
        })

    return records


def _parse_openapi_detail_xml(xml_bytes: bytes) -> dict[str, Any]:
    """OpenAPI 상세 정보 XML을 파싱한다.

    XML 구조:
        <RESULT>
          <BIBINFO>
            <TITLE_INFO>제목정보</TITLE_INFO>
            <PUBLISH_INFO>발행사항</PUBLISH_INFO>
            <EDITION_INFO>판사항</EDITION_INFO>
            <FORM_INFO>형태사항(판식정보)</FORM_INFO>
            <NOTE_INFO>주기사항</NOTE_INFO>
          </BIBINFO>
          <HOLDINFO>
            <LIB_NAME>소장기관</LIB_NAME>
          </HOLDINFO>
          ...
        </RESULT>
    """
    root = ET.fromstring(xml_bytes)
    bib = root.find(".//BIBINFO")

    result: dict[str, Any] = {
        "title_info": _get_xml_text(bib, "TITLE_INFO") if bib is not None else "",
        "publish_info": _get_xml_text(bib, "PUBLISH_INFO") if bib is not None else "",
        "edition_info": _get_xml_text(bib, "EDITION_INFO") if bib is not None else "",
        "form_info": _get_xml_text(bib, "FORM_INFO") if bib is not None else "",
        "note_info": _get_xml_text(bib, "NOTE_INFO") if bib is not None else "",
    }

    # 소장기관 목록 (중복 제거)
    hold_libs: list[str] = []
    for hold in root.findall(".//HOLDINFO"):
        lib_name = _get_xml_text(hold, "LIB_NAME")
        if lib_name and lib_name not in hold_libs:
            hold_libs.append(lib_name)
    result["hold_libs"] = hold_libs

    # FORM_INFO에서 판식정보 구조화 시도
    if result["form_info"]:
        result["pansik_parsed"] = parse_pansik_info(result["form_info"])

    return result


# --- 파서 등록 ---
_fetcher = KorcisFetcher()
_mapper = KorcisMapper()
register_parser("korcis", _fetcher, _mapper)
