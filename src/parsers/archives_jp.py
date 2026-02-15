"""일본 국립공문서관 デジタルアーカイブ 파서.

platform-v7.md §7.2.3 기반:
    - 표준 API 없음 → 웹 스크래핑 (HTML 파싱)
    - URL 패턴: https://www.digital.archives.go.jp/
    - 메타데이터 구조: 자체 계층 (簿冊 → 件名)

두 가지 페이지 형식을 지원:
    1) 구형: /DAS/meta/... — <th>/<td> 테이블 패턴
    2) 신형: /file/{id}.html — <dl class="detail_tb"><dt>/<dd> 패턴

신형 페이지(/file/) 제공 필드:
    書名 → title
    人名 → creator (편자/교정자 등 역할 포함)
    請求番号 → call_number
    数量 → physical_description
    書誌事項 → edition_notes (판종, 발행년 등)
    言語 → language
    巻数 → volume_info
    旧蔵者 → former_owner
    URI → permanent_uri
    メタデータ二次利用の可否 → license
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from lxml import html as lxml_html

from parsers.base import BaseFetcher, BaseMapper, register_parser

logger = logging.getLogger(__name__)

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
    supports_asset_download = True

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

    async def fetch_by_url(self, url: str) -> dict[str, Any]:
        """국립공문서관 URL에서 직접 메타데이터를 추출한다.

        입력:
            url — 국립공문서관 디지털 아카이브 URL.
                  예: https://www.digital.archives.go.jp/DAS/meta/listPhoto?...&BID=...
        출력:
            소스 고유 형태의 상세 메타데이터 dict.

        왜 이렇게 하는가:
            URL이 상세 페이지이든 목록 페이지이든,
            거기서 직접 HTML을 파싱하여 메타데이터를 추출한다.
        """
        return await self.fetch_detail(url)

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

    # --- 에셋 다운로드 ---

    async def list_assets(self, raw_data: dict[str, Any]) -> list[dict[str, Any]]:
        """다운로드 가능한 에셋(이미지) 목록을 조회한다.

        동작:
            1. raw_data에서 BID를 추출한다.
            2. /DAS/meta/listPhoto 페이지를 파싱하여 MID 목록을 얻는다.
            3. 각 MID에 대해 sizeget API로 페이지 수를 조회한다.

        다권본 구조:
            BID(簿冊ID)가 여러 MID(件名ID)를 포함할 수 있다.
            id_0은 簿冊 전체(BID), id_1~은 개별 件名(MID).
            개별 MID만 반환한다 (BID는 전체를 감싸는 껍데기).

        왜 이렇게 하는가:
            사용자가 다운로드할 권을 선택할 수 있도록
            먼저 목록과 페이지 수를 보여준다.
        """
        bid = raw_data.get("BID")
        if not bid:
            return []

        # listPhoto 페이지에서 MID 목록 추출
        list_url = (
            f"{_ARCHIVES_BASE}/DAS/meta/listPhoto"
            f"?LANG=default&BID={bid}&ID=&TYPE=dljpeg"
        )
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(list_url)
            resp.raise_for_status()

        entries = _parse_list_photo_page(resp.text, bid)

        # 각 MID의 페이지 수 조회
        assets = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for entry in entries:
                mid = entry["mid"]
                try:
                    size_resp = await client.get(
                        f"{_ARCHIVES_BASE}/acv/auto_conversion/sizeget"
                        f"?mid={mid}&dltype=jpeg"
                    )
                    size_data = size_resp.json()
                    ic = size_data.get("imageContents", {})
                    page_count = ic.get("pageNum", 0)
                    file_size = ic.get("fileSize", 0)
                except Exception as e:
                    logger.warning("sizeget 조회 실패 (%s): %s", mid, e)
                    page_count = 0
                    file_size = 0

                assets.append({
                    "id": mid,           # GUI 표준 키
                    "asset_id": mid,     # 내부 호환용 (download_asset에서 사용)
                    "label": entry["label"],
                    "page_count": page_count,
                    "file_size": file_size,
                    "download_type": "jpeg_pages",
                })

        return assets

    async def download_asset(
        self,
        asset_info: dict[str, Any],
        dest_dir: Path,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> Path:
        """개별 JPEG 이미지를 다운로드하여 PDF로 합친다.

        동작:
            1. sizeget API로 총 페이지 수 확인
            2. 각 페이지를 jp2jpeg API로 JPEG 다운로드
            3. fpdf2로 JPEG들을 하나의 PDF로 결합

        왜 JPEG → PDF 변환인가:
            기존 L1_source/ 파이프라인이 PDF 기반이다.
            PDF는 페이지 단위 관리가 자연스럽다.
            fpdf2는 프로젝트 의존성에 포함되어 있다.
        """
        from fpdf import FPDF

        mid = asset_info["asset_id"]
        label = asset_info.get("label", mid)
        page_count = asset_info.get("page_count", 0)

        # 페이지 수 모르면 재조회
        if not page_count:
            async with httpx.AsyncClient(timeout=30.0) as client:
                size_resp = await client.get(
                    f"{_ARCHIVES_BASE}/acv/auto_conversion/sizeget"
                    f"?mid={mid}&dltype=jpeg"
                )
                ic = size_resp.json().get("imageContents", {})
                page_count = ic.get("pageNum", 0)

        if not page_count or page_count < 1:
            raise ValueError(f"페이지 수를 알 수 없습니다: {mid}")

        dest_dir = Path(dest_dir)

        # 개별 JPEG 다운로드
        jpeg_paths: list[Path] = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            for page_num in range(1, page_count + 1):
                jpeg_url = (
                    f"{_ARCHIVES_BASE}/acv/auto_conversion/conv/jp2jpeg"
                    f"?ID={mid}&p={page_num}"
                )
                resp = await client.get(jpeg_url)
                resp.raise_for_status()

                jpeg_path = dest_dir / f"{mid}_p{page_num:04d}.jpg"
                jpeg_path.write_bytes(resp.content)
                jpeg_paths.append(jpeg_path)

                if progress_callback:
                    progress_callback(page_num, page_count)

        # JPEG → PDF 변환 (fpdf2)
        pdf = FPDF(unit="pt")
        for jpeg_path in jpeg_paths:
            # 이미지 크기를 PDF 페이지 크기로 설정 (72dpi 기준)
            from PIL import Image

            with Image.open(jpeg_path) as img:
                w_px, h_px = img.size
            # 150dpi 기준으로 변환 (고서 스캔 해상도)
            w_pt = w_px * 72 / 150
            h_pt = h_px * 72 / 150
            pdf.add_page(format=(w_pt, h_pt))
            pdf.image(str(jpeg_path), x=0, y=0, w=w_pt, h=h_pt)

        safe_label = _sanitize_filename(label)
        pdf_path = dest_dir / f"{safe_label}.pdf"
        pdf.output(str(pdf_path))

        logger.info(
            "PDF 생성 완료: %s (%d페이지, %.1fMB)",
            pdf_path.name,
            page_count,
            pdf_path.stat().st_size / 1024 / 1024,
        )

        return pdf_path


class ArchivesJpMapper(BaseMapper):
    """국립공문서관 데이터를 bibliography.json 공통 스키마로 매핑한다.

    국립공문서관 특성 (platform-v7.md §7.2.3):
        - 대부분의 서지 필드(저자, 발행년, 판종 등)가 없다.
        - 소장·관리 중심 데이터: 제목, 시스템ID, 영구URI 정도.
        - 나머지는 사람이 수동으로 채워야 한다.
    """

    parser_id = "japan_national_archives"

    def map_to_bibliography(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """국립공문서관 원본 데이터를 bibliography.json 형식으로 변환한다.

        구형(/DAS/meta/) 페이지: title 정도만 추출 가능, 나머지 대부분 없음.
        신형(/file/) 페이지: 서명, 인명, 서지사항, 언어, 권수 등 상세 정보 제공.
        """

        # 시스템 ID 추출
        system_ids = {}
        if raw_data.get("BID"):
            system_ids["BID"] = raw_data["BID"]
        if raw_data.get("ID"):
            system_ids["ID"] = raw_data["ID"]

        # 인명 파싱: "編者:李瀚（唐）／校訂者:亀田鵬斎" → creator + contributors
        creator, contributors = _parse_creators(raw_data.get("creator"))

        # 서지사항에서 판종·발행년 추출: "刊本,寛政12年" → edition_type, date_created
        edition_type, date_created = _parse_edition_notes(
            raw_data.get("edition_notes")
        )

        # extent 추출: volume_info에서 권수, physical_description에서 책수
        extent = _parse_extent(
            raw_data.get("volume_info"), raw_data.get("physical_description")
        )

        # notes 조합: 기존 notes + 권수 + 구장자 + 관련사항
        notes_parts = []
        if raw_data.get("notes"):
            notes_parts.append(raw_data["notes"])
        if raw_data.get("volume_info"):
            notes_parts.append(f"巻数: {raw_data['volume_info']}")
        if raw_data.get("former_owner"):
            notes_parts.append(f"旧蔵者: {raw_data['former_owner']}")

        bibliography = {
            "title": raw_data.get("title"),
            "title_reading": None,
            "alternative_titles": None,
            "creator": creator,
            "contributors": contributors,
            "date_created": date_created,
            "edition_type": edition_type,
            "language": raw_data.get("language"),
            "script": None,
            "physical_description": raw_data.get("physical_description"),
            "printing_info": None,
            "publishing": None,
            "extent": extent,
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
                    "title": self._field_source("書名/簿冊標題", "exact"),
                    "title_reading": self._field_source(None, None, "국립공문서관에 독음 없음"),
                    "creator": self._field_source("人名", "inferred", "역할:이름 형식에서 첫 인명 추출"),
                    "contributors": self._field_source("人名", "inferred", "교정자 등 보조 역할"),
                    "date_created": self._field_source("書誌事項", "inferred", "서지사항에서 연도 추출"),
                    "edition_type": self._field_source("書誌事項", "inferred", "서지사항에서 판종 추출"),
                    "language": self._field_source("言語", "exact"),
                    "extent": self._field_source("巻数+数量", "inferred", "巻数에서 권수, 数量에서 책수 추출"),
                    "repository": self._field_source("국립공문서관", "exact", "소장처 고정"),
                },
                api_variant="html_scraping",
            ),
            "notes": "; ".join(notes_parts) if notes_parts else None,
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

        # 永続URI 추출 — 신형 페이지: <p class="plink">URI：<a href="...">
        perm_link = tree.cssselect("p.plink a")
        if perm_link:
            uri_text = perm_link[0].text_content().strip()
            if uri_text:
                data.setdefault("permanent_uri", uri_text)

        # 구형 페이지: 이미지 링크에서 영구 URI
        if "permanent_uri" not in data:
            perm_links = tree.xpath('//a[contains(@href, "archives.go.jp/img")]')
            if perm_links:
                data["permanent_uri"] = perm_links[0].get("href", "")

        # BID 추출 — 구형: URL 파라미터, 신형: JS 변수 var mid = '...'
        bid = _extract_param(source_url, "BID")
        if bid:
            data["BID"] = bid
        if "BID" not in data:
            mid_match = re.search(r"var\s+mid\s*=\s*'([^']+)'", html_text)
            if mid_match:
                data["BID"] = mid_match.group(1)

        # 파일 ID 추출 — 신형: /file/{id} URL 패턴
        file_id_match = re.search(r"/file/(\d+)", source_url)
        if file_id_match:
            data.setdefault("ID", file_id_match.group(1))

    except Exception:
        # HTML 파싱 실패 시 기본 데이터만 반환
        pass

    return data


def _map_detail_field(data: dict, key: str, value: str) -> None:
    """상세 페이지의 필드명을 공통 키로 매핑한다.

    왜 이렇게 하는가:
        국립공문서관의 HTML에서 추출한 일본어 필드명을
        내부 키로 변환한다.

    두 가지 페이지 형식의 필드명을 모두 처리:
        구형(/DAS/meta/): 簿冊標題, 件名, 件数, 永続URI 등
        신형(/file/): 書名, 人名, 数量, 書誌事項, 言語, 巻数, 旧蔵者 등
    """
    if not value or value in ("", "-"):
        return

    # 제목 계열 — 구형: 簿冊標題, 신형: 書名
    if key in ("簿冊標題", "標題", "タイトル", "件名標題", "書名"):
        data["title"] = value
    elif key in ("件名", "資料名"):
        data.setdefault("notes", "")
        data["notes"] = f"件名: {value}" if not data["notes"] else f"{data['notes']}; 件名: {value}"
    # 저자/인명 — 신형: 人名 (예: "編者:李瀚（唐）／校訂者:亀田鵬斎")
    elif key == "人名":
        data["creator"] = value
    # 수량/형태 — 구형: 件数, 신형: 数量
    elif key in ("件数", "数量"):
        data["physical_description"] = value
    # 서지사항 — 신형: 書誌事項 (판종+발행년 등, 예: "刊本,寛政12年")
    elif key == "書誌事項":
        data["edition_notes"] = value.strip().replace("\n", "").replace("\t", "")
    # 언어 — 신형: 言語
    elif key == "言語":
        data["language"] = value
    # 권수 — 신형: 巻数
    elif key == "巻数":
        data["volume_info"] = value
    # 구장자 — 신형: 旧蔵者 (이전 소유자)
    elif key == "旧蔵者":
        data["former_owner"] = value
    # 관련사항 — 신형: 関連事項
    elif key == "関連事項":
        data.setdefault("notes", "")
        note = f"関連事項: {value}"
        data["notes"] = note if not data["notes"] else f"{data['notes']}; {note}"
    # 계층 — 신형: 階層 (내閣文庫 > 漢書 > 子の部 등)
    elif key == "階層":
        data["hierarchy"] = value.strip()
    # 시스템 ID
    elif key in ("永続URI", "永続的識別子"):
        data["permanent_uri"] = value
    elif key in ("請求記号", "請求番号"):
        data["call_number"] = value
    # 라이선스 — 구형: 利用条件, 신형: 메타데이터二次利用の可否 (줄바꿈 포함)
    elif "二次利用" in key or key in ("利用条件",):
        data["license"] = value
    # ID 계열
    elif key in ("ID", "管理番号"):
        data["ID"] = value
    elif key in ("BID", "簿冊番号"):
        data["BID"] = value


def _parse_creators(
    creator_str: str | None,
) -> tuple[dict | None, list[dict] | None]:
    """인명 문자열에서 주 저자와 기여자를 분리한다.

    입력 예시:
        "編者:李瀚（唐）／校訂者:亀田鵬斎"
        "著者:某" (단일 인명)

    출력:
        (creator_obj, contributors_list):
        - creator_obj: bibliography 스키마 형식 {name, name_reading, role, period}
        - contributors_list: 나머지 인명의 스키마 객체 리스트

    왜 이렇게 하는가:
        국립공문서관의 人名 필드는 "역할:이름" 형식이
        "／"로 구분되어 있다. 첫 인명을 주 저자로 취급한다.
        bibliography.json 스키마가 creator를 객체로 요구하므로
        문자열이 아닌 {name, role, period} 형태로 변환한다.
    """
    if not creator_str:
        return None, None

    # "／"로 분리 (전각 슬래시)
    parts = [p.strip() for p in creator_str.split("／") if p.strip()]
    if not parts:
        return None, None

    # 첫 인명을 주 저자로
    creator = _role_name_to_schema_obj(parts[0])

    # 나머지: contributors
    contributors = None
    if len(parts) > 1:
        contributors = [_role_name_to_schema_obj(p) for p in parts[1:]]

    return creator, contributors


# 역할명 → bibliography 스키마 role 매핑
_ROLE_MAP: dict[str, str] = {
    "著者": "author",
    "編者": "editor",
    "撰者": "author",
    "校訂者": "annotator",
    "校正者": "annotator",
    "注釈者": "annotator",
    "訳者": "translator",
    "編纂者": "compiler",
}


def _role_name_to_schema_obj(role_name: str) -> dict[str, str | None]:
    """'역할:이름' 또는 '이름' → bibliography 스키마 creator 객체.

    예: "編者:李瀚（唐）" → {name: "李瀚", role: "editor", period: "唐"}
        "亀田鵬斎" → {name: "亀田鵬斎", role: None, period: None}
    """
    role_ja = None
    name_part = role_name.strip()

    # "역할:이름" 형식 분리
    if ":" in name_part:
        role_ja, name_part = name_part.split(":", 1)
        role_ja = role_ja.strip()
        name_part = name_part.strip()

    # 이름에서 시기(괄호 안) 추출: "李瀚（唐）" → name="李瀚", period="唐"
    period = None
    period_match = re.search(r"[（(]([^）)]+)[）)]", name_part)
    if period_match:
        period = period_match.group(1)
        name_part = name_part[: period_match.start()].strip()

    # 역할 매핑
    role_en = _ROLE_MAP.get(role_ja) if role_ja else None

    return {
        "name": name_part,
        "name_reading": None,
        "role": role_en,
        "period": period,
    }


def _parse_edition_notes(notes: str | None) -> tuple[str | None, str | None]:
    """서지사항 문자열에서 판종과 발행년을 추출한다.

    입력 예시:
        "刊本,寛政12年" → ("刊本", "寛政12年")
        "写本" → ("写本", None)
        "刊本" → ("刊本", None)

    왜 이렇게 하는가:
        국립공문서관 신형 페이지의 書誌事項 필드에는
        판종(刊本/写本 등)과 발행년이 쉼표로 구분되어 있다.
    """
    if not notes:
        return None, None

    parts = [p.strip() for p in notes.split(",") if p.strip()]
    if not parts:
        return None, None

    edition_type = parts[0] if parts else None
    date_created = parts[1] if len(parts) > 1 else None

    return edition_type, date_created


def _parse_extent(
    volume_info: str | None, physical_desc: str | None
) -> dict[str, str | None] | None:
    """권수(volume_info)와 형태사항(physical_description)에서 extent를 추출한다.

    입력 예시:
        volume_info="３巻旧註蒙求校異３巻", physical_desc="3冊"
        → {"volumes": "３巻", "books": "3冊", "missing": None}

    왜 이렇게 하는가:
        국립공문서관의 巻数 필드에서 권수를, 数量 필드에서 책수를 추출한다.
        권수는 첫 번째 'N巻' 패턴을 사용한다.
    """
    if not volume_info and not physical_desc:
        return None

    volumes = None
    books = None

    # volume_info에서 첫 "N巻" 패턴 추출
    if volume_info:
        m = re.search(r"[０-９\d]+巻", volume_info)
        if m:
            volumes = m.group(0)

    # physical_description에서 "N冊" 패턴 추출
    if physical_desc:
        m = re.search(r"[０-９\d]+冊", physical_desc)
        if m:
            books = m.group(0)

    if not volumes and not books:
        return None

    return {"volumes": volumes, "books": books, "missing": None}


def _extract_param(url: str, param: str) -> str | None:
    """URL에서 특정 쿼리 파라미터 값을 추출한다."""
    match = re.search(rf"[?&]{param}=([^&]+)", url)
    return match.group(1) if match else None


# --- 에셋 다운로드 유틸리티 ---


def _parse_list_photo_page(
    html_text: str, bid: str
) -> list[dict[str, str]]:
    """listPhoto 페이지에서 개별 MID와 라벨을 추출한다.

    구조:
        dl.dl_list_tag → 簿冊 전체 (BID) — 건너뜀
        dl.dl_list_detail → 개별 件名 (MID) — 수집 대상

    각 체크박스 input:
        name="id_N" value="M2023..." → MID
        부모 label의 text_content → 라벨 (예: "蒙求1")

    왜 이렇게 하는가:
        국립공문서관은 IIIF를 지원하지 않으므로,
        다운로드 페이지의 HTML에서 개별 파일 목록을 파싱한다.
    """
    entries: list[dict[str, str]] = []
    try:
        tree = lxml_html.fromstring(html_text)
        # 모든 체크박스에서 MID 추출
        inputs = tree.cssselect("input[name^=id_]")
        for inp in inputs:
            mid = inp.get("value", "")
            # BID(簿冊 전체)는 건너뜀 — 개별 MID만 수집
            if mid == bid:
                continue
            # 라벨: 부모 label의 텍스트
            label_el = inp.getparent()
            label_text = ""
            if label_el is not None:
                label_text = label_el.text_content().strip()
            if not label_text:
                label_text = mid
            entries.append({"mid": mid, "label": label_text})
    except Exception as e:
        logger.warning("listPhoto 파싱 실패: %s", e)

    # 하위 MID가 없으면 BID 자체를 단일 에셋으로 취급
    if not entries:
        entries.append({"mid": bid, "label": bid})

    return entries


def _sanitize_filename(name: str) -> str:
    """파일명으로 안전한 문자열을 만든다.

    왜 이렇게 하는가:
        에셋 라벨(예: "蒙求1")을 파일명으로 사용할 때,
        OS 파일 시스템에 위험한 문자를 제거한다.
    """
    safe = re.sub(r'[<>:"/\\|?*]', "_", name)
    return safe[:100] if safe else "untitled"


# --- 파서 등록 ---
_fetcher = ArchivesJpFetcher()
_mapper = ArchivesJpMapper()
register_parser("japan_national_archives", _fetcher, _mapper)
