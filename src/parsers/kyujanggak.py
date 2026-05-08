"""서울대학교 규장각한국학연구원 (Kyujanggak) 파서.

platform-v7.md 기반:
    - 표준 API 없음 → 웹 스크래핑 (HTML 파싱)
    - URL 패턴: https://kyudb.snu.ac.kr/book/view.do?book_cd=GK12715_00
    - 메타데이터 구조: book/view.do 페이지 내 table의 th/td 행
    - 이미지 구조: viewImgList.do API + ImageServlet.do 다운로드

서지정보 추출:
    book/view.do 페이지의 table > tr > th + td 패턴.
    필드: 원서명, 현대어서명, 청구기호, 편저자, 판본사항, 책권수, 책크기 등.

이미지 다운로드:
    1. book/view.do 페이지에서 fn_originalImg 호출로 item_cd 추출
    2. 책권수에서 권 수를 파악하여 vol_no 목록 생성
    3. /pf01/viewImgList.do POST로 각 권의 이미지 파일 목록 조회
    4. /ImageServlet.do로 JPEG 다운로드
    5. fpdf2로 PDF 결합

왜 전용 파서인가:
    generic_llm 폴백으로는 viewImgList.do API를 호출할 수 없어
    이미지 다운로드가 불가능하다.

SSL 주의:
    kyudb.snu.ac.kr은 SSL 인증서 문제가 있으므로 verify=_SSL_CTX로 요청한다.
"""

from __future__ import annotations

import logging
import re
import ssl
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import urllib3
from lxml import html as lxml_html

from parsers.base import BaseFetcher, BaseMapper, register_parser

# SSL 인증서 경고 억제 — kyudb.snu.ac.kr의 SSL 문제 대응
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# kyudb.snu.ac.kr용 SSL 컨텍스트 — 인증서 검증 비활성화.
# 왜 이렇게 하는가:
#     kyudb.snu.ac.kr의 SSL 인증서가 올바르지 않아 기본 검증이 실패한다.
#     httpx의 verify=_SSL_CTX가 일부 환경에서 동작하지 않으므로
#     명시적 ssl.SSLContext를 사용한다.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

logger = logging.getLogger(__name__)

# 규장각 베이스 URL
_KYU_BASE = "https://kyudb.snu.ac.kr"


class KyujanggakFetcher(BaseFetcher):
    """규장각에서 HTML을 파싱하여 메타데이터와 이미지 목록을 추출한다.

    왜 웹 스크래핑인가:
        규장각은 공개 API를 제공하지 않는다.
        book/view.do 페이지에 서지정보 테이블이 있고,
        viewImgList.do POST API로 이미지 목록을 조회할 수 있다.

    SSL 주의:
        kyudb.snu.ac.kr은 SSL 인증서 문제가 있으므로
        모든 httpx 요청에 verify=_SSL_CTX를 사용한다.
    """

    parser_id = "kyujanggak"
    parser_name = "서울대학교 규장각한국학연구원"
    api_variant = "html_scraping"
    supports_asset_download = True

    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        """키워드로 검색하여 후보 목록을 반환한다.

        입력:
            query — 검색어 (예: "海東諸國記").
        출력:
            [{title, item_id, summary, detail_url, raw}, ...]

        주의:
            규장각 검색은 복잡한 폼 기반이라 현재 미구현.
            URL 직접 입력(fetch_by_url)을 사용하는 것을 권장한다.
        """
        logger.warning("규장각 검색 기능은 아직 구현되지 않았습니다. URL 직접 입력을 사용하세요.")
        return []

    async def fetch_by_url(self, url: str) -> dict[str, Any]:
        """규장각 book/view.do URL에서 직접 메타데이터를 추출한다.

        입력:
            url — 규장각 자료 URL.
                  예: https://kyudb.snu.ac.kr/book/view.do?book_cd=GK12715_00
        출력:
            서지정보 + 이미지 관련 정보가 포함된 dict.
        """
        return await self.fetch_detail(url)

    async def fetch_detail(self, item_id: str, **kwargs) -> dict[str, Any]:
        """book/view.do 페이지에서 메타데이터를 추출한다.

        입력:
            item_id — book/view.do 페이지 URL 또는 book_cd 식별자.
        출력:
            서지정보 + item_cd, book_cd, vol 정보가 포함된 dict.
        """
        # URL이 아니면 book_cd로 간주하여 URL 생성
        if item_id.startswith("http"):
            url = item_id
        else:
            url = f"{_KYU_BASE}/book/view.do?book_cd={item_id}"

        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, verify=_SSL_CTX
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        return _parse_book_view_page(response.text, url)

    # --- 에셋 다운로드 ---

    async def list_assets(self, raw_data: dict[str, Any]) -> list[dict[str, Any]]:
        """다운로드 가능한 에셋(이미지 권) 목록을 조회한다.

        동작:
            1. raw_data에서 item_cd, book_cd, vol 목록 추출
            2. 각 vol에 대해 viewImgList.do를 호출하여 이미지 파일 수 확인
            3. 목록과 페이지 수를 반환

        왜 이렇게 하는가:
            다권본일 때 사용자가 다운로드할 권을 선택할 수 있도록
            먼저 목록과 페이지 수를 보여준다.
        """
        item_cd = raw_data.get("item_cd", "")
        book_cd = raw_data.get("book_cd", "")
        vol_list = raw_data.get("vol_list", [])
        title = raw_data.get("title", "")

        if not item_cd or not book_cd:
            logger.warning("item_cd 또는 book_cd를 추출할 수 없습니다.")
            return []

        assets = []
        async with httpx.AsyncClient(
            timeout=30.0, follow_redirects=True, verify=_SSL_CTX
        ) as client:
            for vol_no in vol_list:
                # viewImgList.do POST로 이미지 파일 목록 조회
                file_list = await _fetch_image_list(client, item_cd, book_cd, vol_no)

                label = f"{title} vol.{vol_no}" if title else f"{book_cd} vol.{vol_no}"

                assets.append(
                    {
                        "id": f"{book_cd}_{vol_no}",
                        "asset_id": f"{book_cd}_{vol_no}",
                        "label": label,
                        "page_count": len(file_list),
                        "file_size": 0,
                        "download_type": "kyujanggak_jpeg",
                        # 다운로드에 필요한 추가 정보
                        "_item_cd": item_cd,
                        "_book_cd": book_cd,
                        "_vol_no": vol_no,
                        "_file_list": file_list,
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
            1. asset_info의 _file_list에서 각 파일 정보 추출
            2. /ImageServlet.do URL로 JPEG 다운로드
            3. fpdf2로 JPEG들을 하나의 PDF로 결합

        왜 JPEG → PDF 변환인가:
            기존 L1_source/ 파이프라인이 PDF 기반이다.
            PDF는 페이지 단위 관리가 자연스럽다.
        """
        from fpdf import FPDF

        file_list = asset_info["_file_list"]
        item_cd = asset_info["_item_cd"]
        book_cd = asset_info["_book_cd"]
        vol_no = asset_info["_vol_no"]
        label = asset_info.get("label", asset_info["asset_id"])
        page_count = len(file_list)
        dest_dir = Path(dest_dir)

        if not file_list:
            raise ValueError(f"이미지 목록이 비어있습니다: {label}")

        # 개별 JPEG 다운로드
        jpeg_paths: list[Path] = []
        async with httpx.AsyncClient(
            timeout=60.0, follow_redirects=True, verify=_SSL_CTX
        ) as client:
            for page_num, file_info in enumerate(file_list, 1):
                file_nm = file_info["FILE_NM"]
                img_url = (
                    f"{_KYU_BASE}/ImageServlet.do"
                    f"?imgFileNm={file_nm}"
                    f"&path=/data01/stream/{item_cd}/IMG/{book_cd}/{book_cd}_{vol_no}/{file_nm}"
                )

                resp = await client.get(img_url)
                resp.raise_for_status()

                jpeg_path = dest_dir / f"{_sanitize_filename(file_nm)}"
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


class KyujanggakMapper(BaseMapper):
    """규장각 데이터를 bibliography.json 공통 스키마로 매핑한다.

    규장각 특성:
        - book/view.do 페이지에 서지정보가 테이블 형태로 잘 정리되어 있다.
        - 원서명, 현대어서명, 편저자, 청구기호, 판본사항 등 풍부한 필드 제공.
        - 편저자 필드에서 이름, 시대, 역할을 파싱할 수 있다.
    """

    parser_id = "kyujanggak"

    def map_to_bibliography(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """규장각 원본 데이터를 bibliography.json 형식으로 변환한다.

        입력:
            raw_data — KyujanggakFetcher가 반환한 서지정보 dict.
        출력:
            bibliography.schema.json 준수 dict.
        """
        # 편저자 파싱: "申叔舟(朝鮮) 編" → {name, period, role}
        creator = _parse_creator(raw_data.get("편저자(한자)"))

        # 책권수에서 extent 추출: "2冊, 地圖" → {"books": "2冊"}
        extent = _parse_extent(raw_data.get("책권수"))

        # date_created: 간행연도에서 [刊年未詳] 등 불명 표기 처리
        date_created = raw_data.get("간행연도")
        if date_created and "[" in date_created and "未詳" in date_created:
            date_created = None

        # notes 조합: 자료소개, 서발권수권말
        notes_parts = []
        if raw_data.get("자료소개"):
            notes_parts.append(raw_data["자료소개"])
        if raw_data.get("서,발,권수,권말"):
            notes_parts.append(f"서발권수권말: {raw_data['서,발,권수,권말']}")
        if raw_data.get("M/F번호"):
            notes_parts.append(f"M/F번호: {raw_data['M/F번호']}")

        bibliography = {
            "title": raw_data.get("title") or raw_data.get("원서명"),
            "title_reading": raw_data.get("현대어서명"),
            "alternative_titles": None,
            "creator": creator,
            "contributors": None,
            "date_created": date_created,
            "edition_type": raw_data.get("판본사항"),
            "language": None,
            "script": None,
            "physical_description": raw_data.get("책크기"),
            "printing_info": None,
            "publishing": {
                "place": _clean_unknown(raw_data.get("간행지")),
                "publisher": _clean_unknown(raw_data.get("간행자")),
                "date": date_created,
            }
            if any(
                [
                    _clean_unknown(raw_data.get("간행지")),
                    _clean_unknown(raw_data.get("간행자")),
                    date_created,
                ]
            )
            else None,
            "extent": extent,
            "subject": raw_data.get("사부분류"),
            "classification": None,
            "series_title": None,
            "material_type": None,
            "repository": {
                "name": "서울대학교 규장각한국학연구원",
                "name_ko": "서울대학교 규장각한국학연구원",
                "country": "KR",
                "call_number": raw_data.get("청구기호"),
            },
            "digital_source": {
                "platform": "서울대학교 규장각한국학연구원",
                "source_url": raw_data.get("source_url"),
                "permanent_uri": None,
                "system_ids": (
                    {"book_cd": raw_data.get("book_cd")} if raw_data.get("book_cd") else None
                ),
                "license": None,
                "accessed_at": None,
            },
            "raw_metadata": {
                "source_system": "kyujanggak",
                **{k: v for k, v in raw_data.items() if k not in ("vol_list", "_file_lists")},
            },
            "_mapping_info": self._make_mapping_info(
                field_sources={
                    "title": self._field_source("원서명", "exact"),
                    "title_reading": self._field_source("현대어서명", "exact"),
                    "creator": self._field_source(
                        "편저자(한자)",
                        "inferred",
                        "편저자 문자열에서 이름/시대/역할 파싱",
                    ),
                    "date_created": self._field_source("간행연도", "exact"),
                    "edition_type": self._field_source("판본사항", "exact"),
                    "physical_description": self._field_source("책크기", "exact"),
                    "extent": self._field_source("책권수", "inferred", "책권수에서 冊 수 추출"),
                    "subject": self._field_source("사부분류", "exact"),
                    "repository": self._field_source(
                        None, "exact", "하드코딩: 서울대학교 규장각한국학연구원"
                    ),
                },
                api_variant="html_scraping",
            ),
            "notes": "; ".join(notes_parts) if notes_parts else None,
        }

        return bibliography


# --- HTML 파싱 유틸리티 ---


def _parse_book_view_page(html_text: str, source_url: str) -> dict[str, Any]:
    """규장각 book/view.do 페이지에서 서지정보를 추출한다.

    추출 대상:
        1. 테이블의 th/td 행에서 서지정보 추출
        2. fn_originalImg 호출에서 item_cd 추출
        3. 책권수에서 vol 수 파악
        4. book_cd — URL에서 추출

    왜 이렇게 하는가:
        규장각 book/view.do 페이지에 서지정보 테이블과 이미지 뷰어 링크가
        모두 포함되어 있으므로 한 번의 요청으로 추출 가능하다.
    """
    data: dict[str, Any] = {"source_url": source_url}

    # book_cd 추출 — URL의 book_cd 파라미터
    book_cd_match = re.search(r"[?&]book_cd=([^&]+)", source_url)
    if book_cd_match:
        data["book_cd"] = book_cd_match.group(1)

    try:
        tree = lxml_html.fromstring(html_text)

        # --- 서지정보 테이블 파싱 ---
        rows = tree.xpath("//table//tr[th and td]")
        for row in rows:
            th = row.xpath("th")
            td = row.xpath("td")
            if th and td:
                key = th[0].text_content().strip()
                value = _clean_text(td[0].text_content())
                if key and value:
                    data[key] = value

        # --- 제목 추출 ---
        if "원서명" in data:
            data["title"] = data["원서명"]

    except Exception as e:
        logger.warning("규장각 서지정보 파싱 실패: %s", e)

    # --- item_cd 추출 ---
    # fn_originalImg('POL', 'GK12715_00', '', '') 에서 item_cd 추출
    item_cd_match = re.search(r"fn_originalImg\s*\(\s*'([^']+)'", html_text)
    if item_cd_match:
        data["item_cd"] = item_cd_match.group(1)
    else:
        # 폴백: 일반적인 item_cd 값 시도
        data["item_cd"] = ""

    # --- vol 목록 추출 ---
    # <option value="0001">0001</option> 패턴에서 vol_no 추출
    vol_list = []

    # option 태그에서 vol_no 추출 시도
    try:
        tree = lxml_html.fromstring(html_text)
        # #vol_sel select 또는 일반 select에서 option 추출
        options = tree.xpath("//select//option")
        for opt in options:
            val = opt.get("value", "").strip()
            # 4자리 숫자 형태의 vol_no만 (예: 0001, 0002)
            if val and re.match(r"^\d{4}$", val):
                if val not in vol_list:
                    vol_list.append(val)
    except Exception:
        pass

    # option에서 추출 실패 시, 책권수에서 권 수 추론
    if not vol_list and data.get("책권수"):
        vol_count = _infer_vol_count(data["책권수"])
        vol_list = [f"{i:04d}" for i in range(1, vol_count + 1)]

    # 최소 1권은 있어야 함
    if not vol_list:
        vol_list = ["0001"]

    data["vol_list"] = vol_list

    return data


async def _fetch_image_list(
    client: httpx.AsyncClient, item_cd: str, book_cd: str, vol_no: str
) -> list[dict[str, str]]:
    """viewImgList.do API를 호출하여 이미지 파일 목록을 조회한다.

    입력:
        item_cd — 아이템 분류 코드 (예: "POL")
        book_cd — 도서 코드 (예: "GK12715_00")
        vol_no — 권 번호 (예: "0001")

    출력:
        [{"FILE_NM": "GK12715_00_IH_0001_000a.jpg", "ITEM_CD": "POL", ...}, ...]

    왜 이렇게 하는가:
        규장각은 viewImgList.do POST API로 각 권의 이미지 파일 목록을 제공한다.
        이 목록에서 FILE_NM을 추출하여 ImageServlet.do로 다운로드한다.
    """
    url = f"{_KYU_BASE}/pf01/viewImgList.do"
    resp = await client.post(
        url,
        data={"item_cd": item_cd, "book_cd": book_cd, "vol_no": vol_no},
    )
    resp.raise_for_status()

    try:
        result = resp.json()
        return result.get("list", [])
    except Exception as e:
        logger.warning("viewImgList.do 응답 파싱 실패 (vol=%s): %s", vol_no, e)
        return []


def _clean_text(text: str) -> str:
    """HTML에서 추출한 텍스트를 정리한다.

    왜 이렇게 하는가:
        규장각 HTML에는 불필요한 공백, 탭, 줄바꿈이 많다.
        연속된 공백을 하나로 줄이고 앞뒤 공백을 제거한다.
    """
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _clean_unknown(value: str | None) -> str | None:
    """[刊地未詳] 등 불명 표기를 None으로 변환한다.

    왜 이렇게 하는가:
        규장각 서지정보에서 [未詳] 표기는 실제 정보가 없는 것이므로
        None으로 변환하여 빈 값 처리한다.
    """
    if not value:
        return None
    if "[" in value and "未詳" in value:
        return None
    return value


def _parse_creator(creator_str: str | None) -> dict[str, str | None] | None:
    """편저자 문자열에서 이름, 시대, 역할을 파싱한다.

    입력 예시:
        "申叔舟(朝鮮) 編" → {"name": "申叔舟", "period": "朝鮮", "role": "editor"}

    왜 이렇게 하는가:
        bibliography.json 스키마의 creator 필드에 구조화된 정보를 넣기 위해
        편저자 문자열을 파싱한다.
    """
    if not creator_str:
        return None

    name = None
    period = None
    role = None

    # "이름(시대) 역할" 패턴
    m = re.match(r"(.+?)\(([^)]+)\)\s*(.*)", creator_str)
    if m:
        name = m.group(1).strip()
        period = m.group(2).strip()
        role_raw = m.group(3).strip()
    else:
        # 괄호 없는 경우: "이름 역할" 또는 "이름"
        parts = creator_str.strip().rsplit(None, 1)
        if len(parts) == 2:
            name = parts[0]
            role_raw = parts[1]
        else:
            name = creator_str.strip()
            role_raw = ""

    # 역할 매핑: 한자 → 영어
    role_map = {
        "編": "editor",
        "著": "author",
        "撰": "author",
        "譯": "translator",
        "校": "collator",
        "註": "annotator",
        "纂": "compiler",
    }
    if role_raw:
        role = role_map.get(role_raw, role_raw)

    return {"name": name, "period": period, "role": role}


def _parse_extent(quantity_str: str | None) -> dict[str, str | None] | None:
    """책권수 문자열에서 권수와 책수를 추출한다.

    입력 예시:
        "2冊, 地圖" → {"books": "2冊"}
        "3卷2冊" → {"volumes": "3卷", "books": "2冊"}

    왜 이렇게 하는가:
        bibliography.json 스키마의 extent 필드에 맞추기 위해
        책권수 문자열에서 "N卷"과 "N冊" 패턴을 추출한다.
    """
    if not quantity_str:
        return None

    volumes = None
    books = None

    # "N卷" 패턴
    m = re.search(r"(\d+)卷", quantity_str)
    if m:
        volumes = f"{m.group(1)}卷"

    # "N冊" 패턴
    m = re.search(r"(\d+)冊", quantity_str)
    if m:
        books = f"{m.group(1)}冊"

    if not volumes and not books:
        return None

    return {"volumes": volumes, "books": books, "missing": None}


def _infer_vol_count(quantity_str: str) -> int:
    """책권수 문자열에서 권 수를 추론한다.

    입력 예시:
        "2冊, 地圖" → 2
        "3卷2冊" → 2 (冊 우선)

    왜 이렇게 하는가:
        option 태그에서 vol 목록을 추출할 수 없을 때,
        책권수 필드에서 물리적 책 수(冊)를 추론하여 vol_no를 생성한다.
    """
    # 冊 수 우선
    m = re.search(r"(\d+)\s*冊", quantity_str)
    if m:
        return int(m.group(1))

    # 卷 수 폴백
    m = re.search(r"(\d+)\s*卷", quantity_str)
    if m:
        return int(m.group(1))

    return 1


def _sanitize_filename(name: str) -> str:
    """파일명으로 안전한 문자열을 만든다.

    왜 이렇게 하는가:
        파일명이나 이미지 ID를 파일명으로 사용할 때,
        OS 파일 시스템에 위험한 문자를 제거한다.
    """
    safe = re.sub(r'[<>:"/\\|?*]', "_", name)
    return safe[:100] if safe else "untitled"


# --- 파서 등록 ---
_fetcher = KyujanggakFetcher()
_mapper = KyujanggakMapper()
register_parser("kyujanggak", _fetcher, _mapper)
