"""한국학중앙연구원 장서각 (JSG) 파서.

platform-v7.md 기반:
    - 표준 API 없음 → 웹 스크래핑 (HTML 파싱)
    - URL 패턴: https://jsg.aks.ac.kr/dir/view?dataId=JSG_K2-163
    - 메타데이터 구조: dir/view 페이지 내 table의 th/td 행
    - 이미지 구조: goOrgDataView 호출로 book ID 추출, ajaxThumbs API로 이미지 ID 수집

서지정보 추출:
    dir/view 페이지의 section.layer_sj 또는 table.info > tr > th + td 패턴.
    필드: 자료명, 청구기호, 판본, 크기, 장정, 수량, 작성시기, 소장정보 등.

이미지 다운로드:
    1. dir/view 페이지에서 goOrgDataView 호출로 book ID 추출
    2. /jsgimg/view 에서 pgCtx.dataCount와 첫 이미지 ID 추출
    3. /jsgimg/view/ajaxThumbs 로 전체 이미지 ID 목록 수집
    4. /jsgimg/downloadImage?id={id} 로 JPEG 다운로드
    5. fpdf2로 PDF 결합

왜 전용 파서인가:
    generic_llm 폴백으로는 goOrgDataView JS 호출과 ajaxThumbs API를
    파싱할 수 없어 이미지 다운로드가 불가능하다.
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

# 장서각 베이스 URL
_JSG_BASE = "https://jsg.aks.ac.kr"


class JsgFetcher(BaseFetcher):
    """장서각에서 HTML을 파싱하여 메타데이터와 이미지 목록을 추출한다.

    왜 웹 스크래핑인가:
        장서각은 공개 API를 제공하지 않는다.
        dir/view 페이지에 서지정보 테이블과 goOrgDataView 링크가 있으므로
        HTML 파싱으로 양쪽 데이터를 추출한다.
    """

    parser_id = "jsg"
    parser_name = "한국학중앙연구원 장서각"
    api_variant = "html_scraping"
    supports_asset_download = True

    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        """키워드로 검색하여 후보 목록을 반환한다.

        입력:
            query — 검색어 (예: "故事撮要").
        출력:
            [{title, item_id, summary, detail_url, raw}, ...]

        주의:
            장서각 검색은 복잡한 폼 기반이라 현재 미구현.
            URL 직접 입력(fetch_by_url)을 사용하는 것을 권장한다.
        """
        logger.warning("장서각 검색 기능은 아직 구현되지 않았습니다. URL 직접 입력을 사용하세요.")
        return []

    async def fetch_by_url(self, url: str) -> dict[str, Any]:
        """장서각 dir/view URL에서 직접 메타데이터와 이미지 목록을 추출한다.

        입력:
            url — 장서각 자료 URL.
                  예: https://jsg.aks.ac.kr/dir/view?dataId=JSG_K2-163
        출력:
            서지정보 + 이미지 관련 정보가 포함된 dict.

        왜 이렇게 하는가:
            장서각 dir/view 페이지 하나에 서지정보 테이블과
            book ID 링크가 모두 있으므로 별도 페이지 조회가 필요 없다.
        """
        return await self.fetch_detail(url)

    async def fetch_detail(self, item_id: str, **kwargs) -> dict[str, Any]:
        """dir/view 페이지에서 메타데이터와 book ID 목록을 추출한다.

        입력:
            item_id — dir/view 페이지 URL 또는 dataId 식별자.
        출력:
            서지정보 + book_ids가 포함된 dict.
        """
        # URL이 아니면 dataId로 간주하여 URL 생성
        if item_id.startswith("http"):
            url = item_id
        else:
            url = f"{_JSG_BASE}/dir/view?dataId={item_id}"

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()

        return _parse_dir_view_page(response.text, url)

    # --- 에셋 다운로드 ---

    async def list_assets(self, raw_data: dict[str, Any]) -> list[dict[str, Any]]:
        """다운로드 가능한 에셋(이미지 권) 목록을 조회한다.

        동작:
            1. raw_data["book_ids"]에서 각 book ID 추출
            2. 각 book ID에 대해 /jsgimg/view 페이지를 조회하여 총 이미지 수 파악
            3. ajaxThumbs API로 전체 이미지 ID 수집

        왜 이렇게 하는가:
            다권본일 때 사용자가 다운로드할 권을 선택할 수 있도록
            먼저 목록과 페이지 수를 보여준다.
        """
        book_ids = raw_data.get("book_ids", [])
        title = raw_data.get("title", "")

        assets = []
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for i, book_id in enumerate(book_ids):
                # /jsgimg/view 페이지에서 총 이미지 수와 첫 이미지 ID 추출
                viewer_url = f"{_JSG_BASE}/jsgimg/view?qCond=bookId&q={book_id}"
                resp = await client.get(viewer_url)
                resp.raise_for_status()

                data_count = 0
                # dataCount 추출 — "dataCount : 62" 형태
                m = re.search(r"dataCount\s*[:=]\s*['\"]?(\d+)", resp.text)
                if m:
                    data_count = int(m.group(1))

                # 전체 이미지 ID 수집 (ajaxThumbs 페이지네이션)
                image_ids = await _collect_all_image_ids(client, book_id, data_count)

                label = f"{title} 권{i + 1}" if title else book_id

                assets.append(
                    {
                        "id": book_id,
                        "asset_id": book_id,
                        "label": label,
                        "page_count": len(image_ids),
                        "file_size": 0,
                        "download_type": "jsg_jpeg",
                        # 다운로드에 필요한 추가 정보
                        "_book_id": book_id,
                        "_image_ids": image_ids,
                    }
                )

        return assets

    async def download_asset(
        self,
        asset_info: dict[str, Any],
        dest_dir: Path,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> Path:
        """개별 JPEG 이미지를 다운로드하여 PDF로 합친다.

        동작:
            1. asset_info의 _image_ids에서 각 이미지 ID 추출
            2. /jsgimg/downloadImage?id={id} URL로 JPEG 다운로드
            3. fpdf2로 JPEG들을 하나의 PDF로 결합

        왜 JPEG → PDF 변환인가:
            기존 L1_source/ 파이프라인이 PDF 기반이다.
            PDF는 페이지 단위 관리가 자연스럽다.
        """
        from fpdf import FPDF

        image_ids = asset_info["_image_ids"]
        label = asset_info.get("label", asset_info["asset_id"])
        page_count = len(image_ids)
        dest_dir = Path(dest_dir)

        if not image_ids:
            raise ValueError(f"이미지 목록이 비어있습니다: {label}")

        # 개별 JPEG 다운로드
        jpeg_paths: list[Path] = []
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            for page_num, img_id in enumerate(image_ids, 1):
                img_url = f"{_JSG_BASE}/jsgimg/downloadImage?id={img_id}"
                resp = await client.get(img_url)
                resp.raise_for_status()

                jpeg_path = dest_dir / f"{_sanitize_filename(img_id)}.jpg"
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


class JsgMapper(BaseMapper):
    """장서각 데이터를 bibliography.json 공통 스키마로 매핑한다.

    장서각 특성:
        - dir/view 페이지에 서지정보가 테이블 형태로 잘 정리되어 있다.
        - 자료명, 청구기호, 판본, 크기, 장정, 수량, 작성시기 등 풍부한 필드 제공.
        - 소장정보는 항상 "한국학중앙연구원 장서각"으로 고정.
    """

    parser_id = "jsg"

    def map_to_bibliography(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """장서각 원본 데이터를 bibliography.json 형식으로 변환한다.

        입력:
            raw_data — JsgFetcher가 반환한 서지정보 dict.
        출력:
            bibliography.schema.json 준수 dict.
        """
        # 수량에서 권수/책수 추출: "3권(卷) 3책(冊)" → extent
        extent = _parse_extent(raw_data.get("수량"))

        # 크기 + 장정에서 physical_description 조합
        phys_parts = []
        if raw_data.get("크기(cm)"):
            phys_parts.append(raw_data["크기(cm)"])
        if raw_data.get("장정"):
            phys_parts.append(raw_data["장정"])
        physical_description = "; ".join(phys_parts) if phys_parts else None

        # notes 조합: 기록시기, 인장, 마이크로필름 등
        notes_parts = []
        if raw_data.get("기록시기"):
            notes_parts.append(f"기록시기: {raw_data['기록시기']}")
        if raw_data.get("인장"):
            notes_parts.append(f"인장: {raw_data['인장']}")
        if raw_data.get("마이크로필름"):
            notes_parts.append(f"마이크로필름: {raw_data['마이크로필름']}")

        # date_created: 작성시기에서 [刊年未詳] 등 불명 표기 처리
        date_created = raw_data.get("작성시기")
        if date_created and "미상" in date_created.lower():
            date_created = None

        bibliography = {
            "title": raw_data.get("title") or raw_data.get("자료명"),
            "title_reading": None,
            "alternative_titles": (
                [raw_data["자료명(이칭)"]] if raw_data.get("자료명(이칭)") else None
            ),
            "creator": None,
            "contributors": None,
            "date_created": date_created,
            "edition_type": raw_data.get("판본"),
            "language": None,
            "script": None,
            "physical_description": physical_description,
            "printing_info": None,
            "publishing": None,
            "extent": extent,
            "subject": raw_data.get("사부분류"),
            "classification": raw_data.get("유형분류"),
            "series_title": None,
            "material_type": _classify_material_type(raw_data.get("유형분류")),
            "repository": {
                "name": "한국학중앙연구원 장서각",
                "name_ko": "한국학중앙연구원 장서각",
                "country": "KR",
                "call_number": raw_data.get("청구기호"),
            },
            "digital_source": {
                "platform": "한국학중앙연구원 장서각",
                "source_url": raw_data.get("source_url"),
                "permanent_uri": None,
                "system_ids": (
                    {"dataId": raw_data.get("dataId")} if raw_data.get("dataId") else None
                ),
                "license": None,
                "accessed_at": None,
            },
            "raw_metadata": {
                "source_system": "jsg",
                **{k: v for k, v in raw_data.items() if k not in ("book_ids",)},
            },
            "_mapping_info": self._make_mapping_info(
                field_sources={
                    "title": self._field_source("자료명", "exact"),
                    "creator": self._field_source(None, None, "장서각 dir/view에 저자 정보 없음"),
                    "date_created": self._field_source("작성시기", "exact"),
                    "edition_type": self._field_source("판본", "exact"),
                    "physical_description": self._field_source("크기+장정", "exact"),
                    "extent": self._field_source("수량", "inferred", "수량에서 권수/책수 추출"),
                    "subject": self._field_source("사부분류", "exact"),
                    "repository": self._field_source("소장정보+청구기호", "exact"),
                },
                api_variant="html_scraping",
            ),
            "notes": "; ".join(notes_parts) if notes_parts else None,
        }

        return bibliography


# --- HTML 파싱 유틸리티 ---


def _parse_dir_view_page(html_text: str, source_url: str) -> dict[str, Any]:
    """장서각 dir/view 페이지에서 서지정보와 book ID를 추출한다.

    추출 대상:
        1. 테이블의 th/td 행에서 서지정보 추출
        2. goOrgDataView 호출에서 book ID 목록 추출
        3. dataId 식별자 — URL에서 추출

    왜 이렇게 하는가:
        장서각 dir/view 페이지에 서지정보 테이블과 이미지 뷰어 링크가
        모두 포함되어 있으므로 한 번의 요청으로 추출 가능하다.
    """
    data: dict[str, Any] = {"source_url": source_url}

    # dataId 추출 — URL의 dataId 파라미터
    data_id_match = re.search(r"[?&]dataId=([^&]+)", source_url)
    if data_id_match:
        data["dataId"] = data_id_match.group(1)

    try:
        tree = lxml_html.fromstring(html_text)

        # --- 서지정보 테이블 파싱 ---
        # section.layer_sj table.info 또는 일반 table에서 th/td 추출
        rows = tree.xpath("//table//tr[th and td]")
        for row in rows:
            th = row.xpath("th")
            td = row.xpath("td")
            if th and td:
                key = th[0].text_content().strip()
                value = _clean_text(td[0].text_content())
                # "· " 접두사 제거 (예: "· 자료명(한글)" → "자료명(한글)")
                key = key.lstrip("·").strip()
                if key and value:
                    data[key] = value

        # --- 제목 추출 ---
        # 자료명 필드가 있으면 title로 사용
        if "자료명" in data:
            data["title"] = data["자료명"]
        elif "자료명(한글)" in data:
            data["title"] = data["자료명(한글)"]

    except Exception as e:
        logger.warning("장서각 서지정보 파싱 실패: %s", e)

    # --- book ID 추출 ---
    # goOrgDataView('IMOK_JSG','IMG_K2-163_001') 형태에서 book ID 추출.
    # 주의: goOrgDataView('IMG_JSG','IMG_20170519184442974','K2-163_001') 처럼
    #       타임스탬프 ID가 섞여 있을 수 있으므로, 순수 숫자 ID는 제외한다.
    book_ids = []

    # 패턴 1: goOrgDataView('IMOK_JSG','IMG_{book_id}') — 청구기호 형태
    for m in re.finditer(r"goOrgDataView\s*\(\s*'IMOK_JSG'\s*,\s*'IMG_([^']+)'", html_text):
        bid = m.group(1)
        if bid not in book_ids:
            book_ids.append(bid)

    # 패턴 2: goOrgDataView('IMG_JSG','IMG_{timestamp}','{book_id}') — 3번째 인자
    if not book_ids:
        for m in re.finditer(
            r"goOrgDataView\s*\([^)]*'IMG_JSG'[^)]*'([A-Za-z0-9]+-\d+_\d+)'", html_text
        ):
            bid = m.group(1)
            if bid not in book_ids:
                book_ids.append(bid)

    data["book_ids"] = book_ids

    return data


async def _collect_all_image_ids(
    client: httpx.AsyncClient, book_id: str, data_count: int
) -> list[str]:
    """ajaxThumbs API를 반복 호출하여 전체 이미지 ID를 수집한다.

    동작:
        /jsgimg/view/ajaxThumbs?qCond=bookId&q={book_id}&startIndex={0,20,...}
        각 응답에서 data-item-id 또는 /jsgimg/thumb/{id} 패턴으로 ID 추출.

    왜 이렇게 하는가:
        장서각 이미지 뷰어는 20개씩 페이지네이션된다.
        전체 이미지 ID를 수집하려면 모든 페이지를 순회해야 한다.
    """
    image_ids: list[str] = []
    page_unit = 20
    # data_count가 0이면 200까지 시도 (안전 상한)
    max_pages = data_count if data_count > 0 else 200

    for start_idx in range(0, max_pages, page_unit):
        thumb_url = (
            f"{_JSG_BASE}/jsgimg/view/ajaxThumbs"
            f"?qCond=bookId&q={book_id}"
            f"&startIndex={start_idx}&pageIndex=1&pageUnit={page_unit}&sortField="
        )
        resp = await client.get(thumb_url)
        resp.raise_for_status()

        found_in_page = []

        # data-item-id 속성에서 이미지 ID 추출
        for m in re.finditer(r'data-item-id="([^"]+)"', resp.text):
            img_id = m.group(1)
            if img_id not in image_ids:
                found_in_page.append(img_id)

        # 대안: /jsgimg/thumb/{id} img src 패턴에서 추출
        if not found_in_page:
            for m in re.finditer(r'/jsgimg/thumb/([^"\s?]+)', resp.text):
                img_id = m.group(1)
                if img_id not in image_ids and img_id not in found_in_page:
                    found_in_page.append(img_id)

        # 이 페이지에서 새 ID가 없으면 종료
        if not found_in_page:
            break

        image_ids.extend(found_in_page)

        # 수집된 이미지가 data_count 이상이면 중단
        if data_count > 0 and len(image_ids) >= data_count:
            break

    return image_ids


def _clean_text(text: str) -> str:
    """HTML에서 추출한 텍스트를 정리한다.

    왜 이렇게 하는가:
        장서각 HTML에는 불필요한 공백, 탭, 줄바꿈이 많다.
        연속된 공백을 하나로 줄이고 앞뒤 공백을 제거한다.
    """
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_extent(quantity_str: str | None) -> dict[str, str | None] | None:
    """수량 문자열에서 권수(volumes)와 책수(books)를 추출한다.

    입력 예시:
        "3권(卷) 3책(冊)" → {"volumes": "3卷", "books": "3冊", "missing": None}

    왜 이렇게 하는가:
        bibliography.json 스키마의 extent 필드에 맞추기 위해
        수량 문자열에서 "N권(卷)"과 "N책(冊)" 패턴을 추출한다.
    """
    if not quantity_str:
        return None

    volumes = None
    books = None

    # "N권(卷)" 패턴
    m = re.search(r"(\d+)\s*권\s*\(?\s*卷\s*\)?", quantity_str)
    if m:
        volumes = f"{m.group(1)}卷"
    else:
        # "N卷" 패턴 (직접 한자)
        m = re.search(r"(\d+)卷", quantity_str)
        if m:
            volumes = f"{m.group(1)}卷"

    # "N책(冊)" 패턴
    m = re.search(r"(\d+)\s*책\s*\(?\s*冊\s*\)?", quantity_str)
    if m:
        books = f"{m.group(1)}冊"
    else:
        # "N冊" 패턴 (직접 한자)
        m = re.search(r"(\d+)冊", quantity_str)
        if m:
            books = f"{m.group(1)}冊"

    if not volumes and not books:
        return None

    return {"volumes": volumes, "books": books, "missing": None}


def _classify_material_type(classification: str | None) -> str | None:
    """유형분류 문자열에서 자료 유형을 추론한다.

    입력 예시:
        "고서/기타" → "고서"

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


def _sanitize_filename(name: str) -> str:
    """파일명으로 안전한 문자열을 만든다.

    왜 이렇게 하는가:
        에셋 라벨이나 이미지 ID를 파일명으로 사용할 때,
        OS 파일 시스템에 위험한 문자를 제거한다.
    """
    safe = re.sub(r'[<>:"/\\|?*]', "_", name)
    return safe[:100] if safe else "untitled"


# --- 파서 등록 ---
_fetcher = JsgFetcher()
_mapper = JsgMapper()
register_parser("jsg", _fetcher, _mapper)
