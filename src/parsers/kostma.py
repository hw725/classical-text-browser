"""고려대학교 해외한국학자료센터 (KOSTMA) 파서.

platform-v7.md 기반:
    - 표준 API 없음 → 웹 스크래핑 (HTML 파싱)
    - URL 패턴: http://kostma.korea.ac.kr/viewer/viewerDes?uci=...
    - 메타데이터 구조: 뷰어 페이지 내 서지사항 팝업 (table.info)
    - 이미지 구조: JS 변수 bookInfos에 전체 권/페이지 목록 포함

서지정보 추출:
    뷰어 페이지의 section.layer_sj > table.info > tr > th + td 패턴.
    필드: 분류, 판종, 발행사항, 형태사항, 주기사항, 현소장처, 청구기호 등.

이미지 다운로드:
    JS 변수 bookInfos에서 각 권(book)의 이미지 파일 목록을 추출.
    이미지 URL 패턴: /data/des/{UCI}/IMG/{bookPath}/{fname}
    개별 JPEG를 다운로드하여 fpdf2로 PDF로 합친다.

왜 전용 파서인가:
    generic_llm 폴백으로는 bookInfos JS 변수를 파싱할 수 없어
    이미지 다운로드가 불가능하다. 서지정보도 팝업 안에 숨겨져 있어
    markdown 변환으로는 추출이 어렵다.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from lxml import html as lxml_html

from parsers.base import BaseFetcher, BaseMapper, register_parser

logger = logging.getLogger(__name__)

# KOSTMA 베이스 URL (HTTP — HTTPS 미지원)
_KOSTMA_BASE = "http://kostma.korea.ac.kr"


class KostmaFetcher(BaseFetcher):
    """해외한국학자료센터에서 HTML을 파싱하여 메타데이터와 이미지 목록을 추출한다.

    왜 웹 스크래핑인가:
        KOSTMA는 API를 제공하지 않는다.
        뷰어 페이지(viewerDes)에 서지정보와 이미지 목록이 모두 포함되어 있으므로
        한 번의 HTTP 요청으로 양쪽 데이터를 모두 추출할 수 있다.
    """

    parser_id = "kostma"
    parser_name = "해외한국학자료센터 (KOSTMA)"
    api_variant = "html_scraping"
    supports_asset_download = True

    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        """키워드로 검색하여 후보 목록을 반환한다.

        입력:
            query — 검색어 (예: "蒙求").
        출력:
            [{title, item_id, summary, detail_url, raw}, ...]

        주의:
            KOSTMA 검색 페이지는 복잡한 폼 기반이라 현재 미구현.
            URL 직접 입력(fetch_by_url)을 사용하는 것을 권장한다.
        """
        # TODO: KOSTMA 검색 기능은 추후 구현
        logger.warning("KOSTMA 검색 기능은 아직 구현되지 않았습니다. URL 직접 입력을 사용하세요.")
        return []

    async def fetch_by_url(self, url: str) -> dict[str, Any]:
        """KOSTMA 뷰어 URL에서 직접 메타데이터와 이미지 목록을 추출한다.

        입력:
            url — KOSTMA 뷰어 URL.
                  예: http://kostma.korea.ac.kr/viewer/viewerDes?uci=RIKS+CRMA+...
        출력:
            서지정보 + 이미지 목록이 포함된 dict.

        왜 이렇게 하는가:
            KOSTMA는 뷰어 페이지 하나에 서지정보(팝업)와
            이미지 목록(JS 변수)이 모두 포함되어 있으므로,
            별도의 상세 페이지 조회가 필요 없다.
        """
        return await self.fetch_detail(url)

    async def fetch_detail(self, item_id: str, **kwargs) -> dict[str, Any]:
        """뷰어 페이지에서 메타데이터와 이미지 목록을 추출한다.

        입력:
            item_id — 뷰어 페이지 URL 또는 UCI 식별자.
        출력:
            서지정보 + bookInfos가 포함된 dict.
        """
        # URL이 아니면 UCI로 간주하여 뷰어 URL 생성
        if item_id.startswith("http"):
            url = item_id
        else:
            url = f"{_KOSTMA_BASE}/viewer/viewerDes?uci={item_id}"

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()

        return _parse_viewer_page(response.text, url)

    # --- 에셋 다운로드 ---

    async def list_assets(self, raw_data: dict[str, Any]) -> list[dict[str, Any]]:
        """다운로드 가능한 에셋(이미지 권) 목록을 조회한다.

        동작:
            raw_data["book_infos"]에서 각 권의 bookPath와 이미지 수를 추출한다.
            book_infos는 _parse_viewer_page에서 JS의 bookInfos를 파싱한 결과.

        왜 이렇게 하는가:
            다권본(10卷10冊 등)일 때 사용자가 다운로드할 권을 선택할 수 있도록
            먼저 목록과 페이지 수를 보여준다.
        """
        book_infos = raw_data.get("book_infos", [])
        title = raw_data.get("title", "")
        uci = raw_data.get("uci", "")

        assets = []
        for i, book in enumerate(book_infos):
            img_infos = book.get("imgInfos", [])
            if not img_infos:
                continue

            book_num = img_infos[0].get("bookNum", str(i + 1))
            book_path = img_infos[0].get("bookPath", "")

            # 라벨: "제목 권N" 또는 "bookPath"
            label = f"{title} 권{int(book_num)}" if title else book_path

            assets.append({
                "id": book_path,
                "asset_id": book_path,
                "label": label,
                "page_count": len(img_infos),
                "file_size": 0,
                "download_type": "kostma_jpeg",
                # 다운로드에 필요한 추가 정보
                "_uci": uci,
                "_img_infos": img_infos,
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
            1. asset_info의 _img_infos에서 각 이미지의 bookPath + fname 추출
            2. /data/des/{UCI}/IMG/{bookPath}/{fname} URL로 JPEG 다운로드
            3. fpdf2로 JPEG들을 하나의 PDF로 결합

        왜 JPEG → PDF 변환인가:
            기존 L1_source/ 파이프라인이 PDF 기반이다.
            PDF는 페이지 단위 관리가 자연스럽다.
        """
        from fpdf import FPDF

        uci = asset_info["_uci"]
        img_infos = asset_info["_img_infos"]
        label = asset_info.get("label", asset_info["asset_id"])
        page_count = len(img_infos)
        dest_dir = Path(dest_dir)

        if not img_infos:
            raise ValueError(f"이미지 목록이 비어있습니다: {label}")

        # 개별 JPEG 다운로드
        jpeg_paths: list[Path] = []
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            for page_num, img in enumerate(img_infos, 1):
                book_path = img["bookPath"]
                fname = img["fname"]
                img_url = f"{_KOSTMA_BASE}/data/des/{uci}/IMG/{book_path}/{fname}"

                resp = await client.get(img_url)
                resp.raise_for_status()

                jpeg_path = dest_dir / f"{book_path}_{fname}"
                jpeg_path.write_bytes(resp.content)
                jpeg_paths.append(jpeg_path)

                if progress_callback:
                    progress_callback(page_num, page_count)

        # JPEG → PDF 변환 (fpdf2)
        pdf = FPDF(unit="pt")
        for jpeg_path in jpeg_paths:
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


class KostmaMapper(BaseMapper):
    """KOSTMA 데이터를 bibliography.json 공통 스키마로 매핑한다.

    KOSTMA 특성:
        - 서지정보가 뷰어 팝업 안에 있어 필드가 제한적이다.
        - 저자/편저자 정보가 없는 경우가 많다 (별도 상세 페이지 없음).
        - 분류, 판종, 형태사항, 소장처, 청구기호는 비교적 안정적으로 제공.
    """

    parser_id = "kostma"

    def map_to_bibliography(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """KOSTMA 원본 데이터를 bibliography.json 형식으로 변환한다."""

        # 형태사항에서 권수/책수 추출: "10卷10冊 : 無匡郭..." → extent
        extent = _parse_extent(raw_data.get("형태사항"))

        # 발행사항에서 발행지/발행처/발행년 추출
        pub_place, publisher, pub_date = _parse_publication(
            raw_data.get("발행사항")
        )

        # 분류에서 material_type 추론
        material_type = _classify_material_type(raw_data.get("분류"))

        # notes 조합
        notes_parts = []
        if raw_data.get("주기사항"):
            notes_parts.append(raw_data["주기사항"])

        bibliography = {
            "title": raw_data.get("title"),
            "title_reading": None,
            "alternative_titles": None,
            "creator": None,   # KOSTMA 뷰어 페이지에는 저자 정보 없음
            "contributors": None,
            "date_created": pub_date,
            "edition_type": raw_data.get("판종"),
            "language": None,
            "script": None,
            "physical_description": raw_data.get("형태사항"),
            "printing_info": None,
            "publishing": {
                "place": pub_place,
                "publisher": publisher,
                "date": pub_date,
            } if any([pub_place, publisher, pub_date]) else None,
            "extent": extent,
            "subject": raw_data.get("분류"),
            "classification": None,
            "series_title": None,
            "material_type": material_type,
            "repository": {
                "name": raw_data.get("현소장처"),
                "name_ko": raw_data.get("현소장처"),
                "country": _infer_country(raw_data.get("현소장처")),
                "call_number": raw_data.get("청구기호"),
            } if raw_data.get("현소장처") else None,
            "digital_source": {
                "platform": "해외한국학자료센터 (KOSTMA)",
                "source_url": raw_data.get("source_url"),
                "permanent_uri": None,
                "system_ids": {"uci": raw_data.get("uci")} if raw_data.get("uci") else None,
                "license": None,
                "accessed_at": None,
            },
            "raw_metadata": {
                "source_system": "kostma",
                **{k: v for k, v in raw_data.items() if k != "book_infos"},
            },
            "_mapping_info": self._make_mapping_info(
                field_sources={
                    "title": self._field_source(
                        "SimpleTree 트리제목", "inferred", "뷰어 트리에서 추출"
                    ),
                    "creator": self._field_source(None, None, "KOSTMA 뷰어에 저자 정보 없음"),
                    "date_created": self._field_source(
                        "발행사항", "inferred", "발행사항에서 연도 추출"
                    ),
                    "edition_type": self._field_source("판종", "exact"),
                    "physical_description": self._field_source("형태사항", "exact"),
                    "extent": self._field_source(
                        "형태사항", "inferred", "형태사항에서 권수/책수 추출"
                    ),
                    "subject": self._field_source("분류", "exact"),
                    "repository": self._field_source("현소장처+청구기호", "exact"),
                },
                api_variant="html_scraping",
            ),
            "notes": "; ".join(notes_parts) if notes_parts else None,
        }

        return bibliography


# --- HTML 파싱 유틸리티 ---


def _parse_viewer_page(html_text: str, source_url: str) -> dict[str, Any]:
    """KOSTMA 뷰어 페이지에서 서지정보와 이미지 목록을 추출한다.

    추출 대상:
        1. section.layer_sj 팝업 안의 table.info → 서지정보
        2. var bookInfos = [...] JS 변수 → 이미지 목록
        3. UCI 식별자 → URL에서 추출

    왜 이렇게 하는가:
        KOSTMA는 뷰어 페이지 하나에 모든 정보가 들어있다.
        서지정보는 display:none 팝업 안에, 이미지 목록은 JS 변수에 있어
        일반적인 markdown 변환으로는 추출할 수 없다.
    """
    data: dict[str, Any] = {"source_url": source_url}

    # UCI 추출 — URL의 uci 파라미터
    uci_match = re.search(r"[?&]uci=([^&]+)", source_url)
    if uci_match:
        data["uci"] = uci_match.group(1)

    try:
        tree = lxml_html.fromstring(html_text)

        # --- 서지사항 팝업 파싱 ---
        # section.layer_sj > div.popcontent_sj > table.info > tr > th + td
        info_table = tree.cssselect("section.layer_sj table.info")
        if info_table:
            rows = info_table[0].xpath(".//tr[th and td]")
            for row in rows:
                th = row.xpath("th")
                td = row.xpath("td")
                if th and td:
                    key = th[0].text_content().strip()
                    value = _clean_text(td[0].text_content())
                    # "· " 접두사 제거 (예: "· 분류" → "분류")
                    key = key.lstrip("·").strip()
                    if key and value:
                        data[key] = value

        # --- 제목 추출 ---
        # p.tree_tit에 문서 전체 제목이 있다 (예: "청구야담(靑丘野談)")
        if "title" not in data:
            tree_tit = tree.cssselect("p.tree_tit")
            if tree_tit:
                data["title"] = _clean_text(tree_tit[0].text_content())

    except Exception as e:
        logger.warning("KOSTMA 서지정보 파싱 실패: %s", e)

    # --- bookInfos JS 변수 파싱 ---
    # var bookInfos = [{imgInfos: [{bookNum, bookPath, fname, imgNum}, ...]}, ...]
    try:
        book_match = re.search(r"var\s+bookInfos\s*=\s*(\[.*?\])\s*;", html_text, re.DOTALL)
        if book_match:
            book_infos = json.loads(book_match.group(1))
            data["book_infos"] = book_infos
        else:
            data["book_infos"] = []
            logger.warning("bookInfos JS 변수를 찾을 수 없습니다.")
    except (json.JSONDecodeError, ValueError) as e:
        data["book_infos"] = []
        logger.warning("bookInfos 파싱 실패: %s", e)

    return data


def _clean_text(text: str) -> str:
    """HTML에서 추출한 텍스트를 정리한다.

    왜 이렇게 하는가:
        KOSTMA HTML에는 불필요한 공백, 탭, 줄바꿈이 많다.
        연속된 공백을 하나로 줄이고 앞뒤 공백을 제거한다.
    """
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_extent(physical_desc: str | None) -> dict[str, str | None] | None:
    """형태사항에서 권수(volumes)와 책수(books)를 추출한다.

    입력 예시:
        "10卷10冊 : 無匡郭, 無界, 10行20字, 無魚尾 ; 25.0 X 17.5 cm"
        → {"volumes": "10卷", "books": "10冊", "missing": None}

    왜 이렇게 하는가:
        bibliography.json 스키마의 extent 필드에 맞추기 위해
        형태사항 문자열에서 "N卷"과 "N冊" 패턴을 추출한다.
    """
    if not physical_desc:
        return None

    volumes = None
    books = None

    # "N卷" 패턴
    m = re.search(r"(\d+)卷", physical_desc)
    if m:
        volumes = f"{m.group(1)}卷"

    # "N冊" 패턴
    m = re.search(r"(\d+)冊", physical_desc)
    if m:
        books = f"{m.group(1)}冊"

    if not volumes and not books:
        return None

    return {"volumes": volumes, "books": books, "missing": None}


def _parse_publication(
    pub_info: str | None,
) -> tuple[str | None, str | None, str | None]:
    """발행사항에서 발행지, 발행처, 발행년을 추출한다.

    입력 예시:
        "[발행지불명] : [발행처불명], [발행년불명]"
        "서울 : 홍문관, 1900"
        "[발행지불명] : [발행처불명], 正祖24年(1800)"

    출력:
        (발행지, 발행처, 발행년) — 불명이면 None.

    왜 이렇게 하는가:
        KOSTMA의 발행사항은 "장소 : 출판사, 연도" 형식이다.
        "[불명]" 표기는 실제 정보가 없으므로 None으로 변환한다.
    """
    if not pub_info:
        return None, None, None

    place = None
    publisher = None
    date = None

    # "장소 : 출판사, 연도" 패턴
    parts = re.split(r"\s*:\s*", pub_info, maxsplit=1)
    if len(parts) == 2:
        place_raw = parts[0].strip()
        rest = parts[1].strip()

        # 발행지
        if "[발행지불명]" not in place_raw and place_raw:
            place = place_raw

        # "출판사, 연도" 분리
        rest_parts = re.split(r",\s*", rest, maxsplit=1)
        pub_raw = rest_parts[0].strip()
        if "[발행처불명]" not in pub_raw and pub_raw:
            publisher = pub_raw

        if len(rest_parts) == 2:
            date_raw = rest_parts[1].strip()
            if "[발행년불명]" not in date_raw and date_raw:
                date = date_raw

    return place, publisher, date


def _classify_material_type(classification: str | None) -> str | None:
    """분류 문자열에서 자료 유형을 추론한다.

    입력 예시:
        "고서-기타 | 교육/문화-문학/저술 | 집부-수필류"

    왜 이렇게 하는가:
        bibliography.json의 material_type에 넣을 대분류를 추출한다.
    """
    if not classification:
        return None

    if "고서" in classification:
        return "고서"
    if "고문서" in classification:
        return "고문서"
    if "근대서" in classification:
        return "근대서"

    return None


def _infer_country(repository_name: str | None) -> str | None:
    """소장처 이름에서 국가 코드를 추론한다.

    왜 이렇게 하는가:
        KOSTMA는 '해외' 한국학 자료센터이므로 소장처가 해외 기관이다.
        소장처 이름에 포함된 국가/지역명으로 국가 코드를 추론한다.
    """
    if not repository_name:
        return None

    country_hints = {
        "미국": "US", "버클리": "US", "하버드": "US", "콜럼비아": "US",
        "예일": "US", "UCLA": "US", "의회도서관": "US",
        "일본": "JP", "東京": "JP", "京都": "JP", "도쿄": "JP",
        "영국": "GB", "런던": "GB", "옥스포드": "GB", "케임브리지": "GB",
        "프랑스": "FR", "파리": "FR",
        "독일": "DE", "베를린": "DE",
        "중국": "CN", "北京": "CN", "上海": "CN",
        "러시아": "RU", "모스크바": "RU",
        "대만": "TW", "臺灣": "TW",
    }

    for hint, code in country_hints.items():
        if hint in repository_name:
            return code

    return None


def _sanitize_filename(name: str) -> str:
    """파일명으로 안전한 문자열을 만든다.

    왜 이렇게 하는가:
        에셋 라벨(예: "蒙求 권1")을 파일명으로 사용할 때,
        OS 파일 시스템에 위험한 문자를 제거한다.
    """
    safe = re.sub(r'[<>:"/\\|?*]', "_", name)
    return safe[:100] if safe else "untitled"


# --- 파서 등록 ---
_fetcher = KostmaFetcher()
_mapper = KostmaMapper()
register_parser("kostma", _fetcher, _mapper)
