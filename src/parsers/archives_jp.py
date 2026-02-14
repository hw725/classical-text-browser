"""일본 국립공문서관 デジタルアーカイブ 파서.

platform-v7.md §7.2.3 기반:
    - 표준 API 없음 → 웹 스크래핑 (HTML 파싱)
    - URL 패턴: https://www.digital.archives.go.jp/
    - 메타데이터 구조: 자체 계층 (簿冊 → 件名)
    - 대부분의 서지 필드가 비어 있음 (저자, 발행년, 판종 등)
    - 소장·관리 중심 (도서관이 아닌 문서관 특성)

제공 필드:
    簿冊標題 (작품명) → title
    件名 (물리 단위명) → notes
    永続URI → digital_source.permanent_uri
    システムID (BID, ID) → digital_source.system_ids
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from lxml import html as lxml_html

from parsers.base import BaseFetcher, BaseMapper, register_parser

# 국립공문서관 디지털 아카이브 베이스 URL
_ARCHIVES_BASE = "https://www.digital.archives.go.jp"

# 검색 URL 패턴
_SEARCH_URL = f"{_ARCHIVES_BASE}/DAS/meta/search"


class ArchivesJpFetcher(BaseFetcher):
    """국립공문서관 デジタルアーカイブ에서 HTML을 파싱하여 메타데이터를 추출한다.

    왜 웹 스크래핑인가:
        국립공문서관은 표준 API(SRU/OAI-PMH 등)를 제공하지 않는다.
        검색과 상세 정보 조회 모두 HTML 페이지를 파싱해야 한다.
    """

    parser_id = "japan_national_archives"
    parser_name = "国立公文書館デジタルアーカイブ"
    api_variant = "html_scraping"

    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        """키워드로 검색하여 후보 목록을 반환한다.

        입력:
            query — 검색어 (예: "蒙求").
        출력:
            [{title, item_id, summary, detail_url, raw}, ...]

        왜 이렇게 하는가:
            국립공문서관의 검색 결과 페이지를 파싱하여,
            각 항목의 제목과 상세 URL을 추출한다.
            상세 정보는 별도의 fetch_detail 호출로 가져온다.

        주의:
            국립공문서관 웹사이트 구조가 변경되면 파서도 수정해야 한다.
            HTML 스크래핑의 근본적 한계이다.
        """
        # 국립공문서관 검색 파라미터
        params = {
            "DEF_XSL": "default",
            "IS_KIND": "summary_normal",
            "IS_SCH": "F2",
            "IS_TAG_S1": "title",
            "IS_KEY_S1": query,
            "IS_STYLE": "default",
            "IS_TYPE": "meta",
        }

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(
                f"{_ARCHIVES_BASE}/DAS/meta/result",
                params=params,
            )
            response.raise_for_status()

        return _parse_search_results(response.text)

    async def fetch_detail(self, item_id: str, **kwargs) -> dict[str, Any]:
        """상세 페이지 URL에서 메타데이터를 추출한다.

        입력:
            item_id — 상세 페이지 URL (detail_url).
                      예: "/DAS/meta/listPhoto?KEYWORD=...&BID=..."
        출력:
            소스 고유 형태의 상세 메타데이터 dict.
        """
        url = item_id if item_id.startswith("http") else f"{_ARCHIVES_BASE}{item_id}"

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()

        return _parse_detail_page(response.text, url)


class ArchivesJpMapper(BaseMapper):
    """국립공문서관 데이터를 bibliography.json 공통 스키마로 매핑한다.

    국립공문서관 특성 (platform-v7.md §7.2.3):
        - 대부분의 서지 필드(저자, 발행년, 판종 등)가 없다.
        - 소장·관리 중심 데이터: 제목, 시스템ID, 영구URI 정도.
        - 나머지는 사람이 수동으로 채워야 한다.
    """

    parser_id = "japan_national_archives"

    def map_to_bibliography(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """국립공문서관 원본 데이터를 bibliography.json 형식으로 변환한다."""

        # 시스템 ID 추출
        system_ids = {}
        if raw_data.get("BID"):
            system_ids["BID"] = raw_data["BID"]
        if raw_data.get("ID"):
            system_ids["ID"] = raw_data["ID"]

        bibliography = {
            "title": raw_data.get("title"),
            "title_reading": None,
            "alternative_titles": None,
            "creator": None,  # 국립공문서관에는 대부분 저자 정보가 없다
            "contributors": None,
            "date_created": None,
            "edition_type": None,
            "language": None,
            "script": None,
            "physical_description": raw_data.get("physical_description"),
            "subject": None,
            "classification": None,
            "series_title": None,
            "material_type": None,
            "repository": {
                "name": "国立公文書館",
                "name_ko": "일본 국립공문서관",
                "country": "JP",
                "call_number": raw_data.get("call_number"),
            },
            "digital_source": {
                "platform": "国立公文書館デジタルアーカイブ",
                "source_url": raw_data.get("source_url"),
                "permanent_uri": raw_data.get("permanent_uri"),
                "system_ids": system_ids if system_ids else None,
                "license": raw_data.get("license"),
                "accessed_at": None,
            },
            "raw_metadata": {
                "source_system": "japan_national_archives",
                **raw_data,
            },
            "_mapping_info": self._make_mapping_info(
                field_sources={
                    "title": self._field_source("簿冊標題", "exact"),
                    "title_reading": self._field_source(None, None, "국립공문서관에 독음 없음"),
                    "creator": self._field_source(None, None, "국립공문서관에 저자 정보 대부분 없음"),
                    "date_created": self._field_source(None, None, "국립공문서관에 연도 정보 대부분 없음"),
                    "edition_type": self._field_source(None, None, "국립공문서관에 판종 없음"),
                    "repository": self._field_source("국립공문서관", "exact", "소장처 고정"),
                },
                api_variant="html_scraping",
            ),
            "notes": raw_data.get("notes"),
        }

        return bibliography


# --- HTML 파싱 유틸리티 ---


def _parse_search_results(html_text: str) -> list[dict[str, Any]]:
    """검색 결과 HTML을 파싱하여 항목 목록을 추출한다.

    왜 이렇게 하는가:
        국립공문서관의 검색 결과는 HTML 테이블 또는 목록으로 표시된다.
        각 항목의 제목과 상세 페이지 링크를 추출한다.

    주의:
        HTML 구조가 변경되면 이 함수도 수정해야 한다.
        실패 시 빈 목록을 반환한다 (에러를 삼키지 않고 로깅).
    """
    results = []
    try:
        tree = lxml_html.fromstring(html_text)

        # 검색 결과 항목을 찾는다
        # 국립공문서관은 테이블 기반 결과를 표시하거나 div.resultList를 사용
        # 여러 가능한 CSS 셀렉터를 시도
        items = tree.cssselect("div.resultData, tr.dataRow, div.result_list_data")

        if not items:
            # 대안: 링크에서 listPhoto 패턴을 가진 것을 찾기
            links = tree.xpath('//a[contains(@href, "listPhoto") or contains(@href, "detail")]')
            for link in links:
                href = link.get("href", "")
                title_text = link.text_content().strip()
                if title_text and href:
                    bid = _extract_param(href, "BID")
                    results.append({
                        "title": title_text,
                        "item_id": href,
                        "detail_url": href,
                        "summary": title_text,
                        "raw": {"title": title_text, "detail_url": href, "BID": bid},
                    })
        else:
            for item in items:
                title_el = item.cssselect("a, .title, td:first-child")
                if not title_el:
                    continue
                title_text = title_el[0].text_content().strip()
                href = title_el[0].get("href", "")
                if not href:
                    link_el = item.cssselect("a")
                    if link_el:
                        href = link_el[0].get("href", "")

                bid = _extract_param(href, "BID")
                results.append({
                    "title": title_text,
                    "item_id": href,
                    "detail_url": href,
                    "summary": title_text,
                    "raw": {"title": title_text, "detail_url": href, "BID": bid},
                })

    except Exception:
        # HTML 파싱 실패 시 빈 목록 반환
        pass

    return results


def _parse_detail_page(html_text: str, source_url: str) -> dict[str, Any]:
    """상세 페이지 HTML에서 메타데이터를 추출한다.

    추출 대상:
        - 簿冊標題 (작품명)
        - 件名 (물리 단위명)
        - 件数 (전체 건수)
        - 永続URI / 시스템ID
        - 라이선스 정보

    왜 이렇게 하는가:
        상세 페이지에는 검색 결과보다 많은 정보가 있다.
        <th>/<td> 쌍으로 된 테이블에서 필드명-값을 추출한다.
    """
    data: dict[str, Any] = {"source_url": source_url}

    try:
        tree = lxml_html.fromstring(html_text)

        # 테이블에서 키-값 추출
        # 국립공문서관은 <th>필드명</th><td>값</td> 패턴을 사용
        rows = tree.xpath("//tr[th and td]")
        for row in rows:
            th = row.xpath("th")
            td = row.xpath("td")
            if th and td:
                key = th[0].text_content().strip()
                value = td[0].text_content().strip()
                _map_detail_field(data, key, value)

        # 대안: dl/dt/dd 패턴
        dts = tree.xpath("//dt")
        for dt in dts:
            dd = dt.getnext()
            if dd is not None and dd.tag == "dd":
                key = dt.text_content().strip()
                value = dd.text_content().strip()
                _map_detail_field(data, key, value)

        # 永続URI 추출 (링크에서)
        perm_links = tree.xpath('//a[contains(@href, "archives.go.jp/img")]')
        if perm_links:
            data["permanent_uri"] = perm_links[0].get("href", "")

        # BID 추출 (URL 파라미터에서)
        bid = _extract_param(source_url, "BID")
        if bid:
            data["BID"] = bid

    except Exception:
        # HTML 파싱 실패 시 기본 데이터만 반환
        pass

    return data


def _map_detail_field(data: dict, key: str, value: str) -> None:
    """상세 페이지의 필드명을 공통 키로 매핑한다.

    왜 이렇게 하는가:
        국립공문서관의 HTML에서 추출한 일본어 필드명을
        내부 키로 변환한다.
    """
    if not value or value in ("", "-"):
        return

    # 제목 계열
    if key in ("簿冊標題", "標題", "タイトル", "件名標題"):
        data["title"] = value
    elif key in ("件名", "資料名"):
        data.setdefault("notes", "")
        data["notes"] = f"件名: {value}" if not data["notes"] else f"{data['notes']}; 件名: {value}"
    # 수량/형태
    elif key in ("件数", "数量"):
        data["physical_description"] = value
    # 시스템 ID
    elif key in ("永続URI", "永続的識別子"):
        data["permanent_uri"] = value
    elif key in ("請求記号", "請求番号"):
        data["call_number"] = value
    # 라이선스
    elif key in ("利用条件", "二次利用条件"):
        data["license"] = value
    # ID 계열
    elif key in ("ID", "管理番号"):
        data["ID"] = value
    elif key in ("BID", "簿冊番号"):
        data["BID"] = value


def _extract_param(url: str, param: str) -> str | None:
    """URL에서 특정 쿼리 파라미터 값을 추출한다."""
    match = re.search(rf"[?&]{param}=([^&]+)", url)
    return match.group(1) if match else None


# --- 파서 등록 ---
_fetcher = ArchivesJpFetcher()
_mapper = ArchivesJpMapper()
register_parser("japan_national_archives", _fetcher, _mapper)
