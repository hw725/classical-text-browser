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
from typing import Any

import httpx
from lxml import html as lxml_html

from parsers.base import BaseFetcher, BaseMapper, register_parser

# KORCIS 베이스 URL
_KORCIS_BASE = "https://www.nl.go.kr"

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

        # 발행사항
        marc260 = raw_data.get("260", {})

        # 형태사항
        marc300 = raw_data.get("300", {})
        physical_parts = []
        if marc300.get("a"):
            physical_parts.append(marc300["a"])
        if marc300.get("c"):
            physical_parts.append(marc300["c"])
        physical_description = " ; ".join(p for p in physical_parts if p) if physical_parts else None

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

        bibliography = {
            "title": marc245.get("a"),
            "title_reading": raw_data.get("_title_kor"),  # 검색 결과에서 추출된 한글 제목
            "alternative_titles": None,
            "creator": creator,
            "contributors": _extract_contributors(raw_data),
            "date_created": marc260.get("c"),
            "edition_type": raw_data.get("250", {}).get("a"),
            "language": _extract_language(raw_data),
            "script": None,
            "physical_description": physical_description,
            "subject": subjects if subjects else None,
            "classification": classification if classification else None,
            "series_title": series_title,
            "material_type": None,
            "repository": None,  # KORCIS는 여러 소장처가 있으므로 별도 표시
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
                field_sources={
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
                },
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


# --- 파서 등록 ---
_fetcher = KorcisFetcher()
_mapper = KorcisMapper()
register_parser("korcis", _fetcher, _mapper)
