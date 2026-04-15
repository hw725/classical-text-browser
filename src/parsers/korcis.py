"""한국고문헌종합목록 (KORCIS) 파서.

대상: 국립중앙도서관 한국고문헌종합목록 + 원문 뷰어
URL: https://www.nl.go.kr/korcis/
     https://viewer.nl.go.kr/

지원하는 URL 형식 (fetch_by_url):
    ── KORCIS 검색/상세 ──
    1) https://www.nl.go.kr/korcis/search/searchResultDetail.do?vdkvgwkey=101121303
    2) https://www.nl.go.kr/korcis/search/popup/marcInfo.do?vdkvgwkey=ID&marcKey=ID&marcTarget=BIB

    ── 목차/해제 팝업 (controlNo 기반) ── ★ 권장
    3) https://nl.go.kr/korcis/search/popup/contentsInfo.do?controlNo=KOL000000392
    4) https://nl.go.kr/korcis/search/popup/abstractsInfo.do?controlNo=KOL000000392
       → 목차(目次)와 해제(解題)를 가져온다.
       → controlNo만으로는 MARC 데이터를 가져올 수 없다.
         vdkvgwkey URL도 함께 입력하면 MARC + 목차 + 해제가 모두 보강된다.

    ── 소장/로컬 MARC 팝업 ──
    5) marcInfo.do?...&marcTarget=HOLD  → vdkvgwkey 추출 → BIB MARC 조회 + 소장 보강
    6) marcInfo.do?...&marcTarget=LOCAL → vdkvgwkey 추출 → BIB MARC 조회

    ── 원문 뷰어 ──
    7) https://viewer.nl.go.kr/main.wviewer?cno=KOL000021131
       → 서지 + 이미지 다운로드 (에셋)

접근 방법:
    - 검색: POST /korcis/search/simpleResultList.do
      파라미터: searchCondition=all, searchKeyword=검색어
    - MARC 팝업: GET /korcis/search/popup/marcInfo.do?vdkvgwkey=ID&marcKey=ID&marcTarget=BIB
      (직접 접근 가능, 가장 구조화된 데이터)
    - 목차 팝업: GET /korcis/search/popup/contentsInfo.do?controlNo=KOL...
    - 해제 팝업: GET /korcis/search/popup/abstractsInfo.do?controlNo=KOL...
    - 원문 뷰어: POST viewer.nl.go.kr/main.wviewer (Referer + ax=Y 세션)

MARC 필드 매핑:
    012 ▼a → controlNo (KOL...) — 목차/해제 조회 키
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

import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from lxml import html as lxml_html

from parsers.base import BaseFetcher, BaseMapper, register_parser

logger = logging.getLogger(__name__)

# KORCIS 베이스 URL 및 팝업 엔드포인트
_KORCIS_BASE = "https://www.nl.go.kr"

# 목차 팝업 (GET, controlNo 기반)
_CONTENTS_INFO_URL = f"{_KORCIS_BASE}/korcis/search/popup/contentsInfo.do"

# 해제 팝업 (GET, controlNo 기반)
_ABSTRACTS_INFO_URL = f"{_KORCIS_BASE}/korcis/search/popup/abstractsInfo.do"

# 국립중앙도서관 원문 뷰어 URL
_VIEWER_BASE = "https://viewer.nl.go.kr"
_VIEWER_URL = f"{_VIEWER_BASE}/main.wviewer"

# 뷰어 이미지 엔드포인트
_VIEWER_IMAGE_URL = f"{_VIEWER_BASE}/nlmivs/view_image.jsp"

# 뷰어 접근에 필요한 공통 헤더
# 왜 이렇게 하는가:
#     viewer.nl.go.kr은 Referer 없이 직접 접근하면 404를 반환한다.
#     실제 브라우저에서 접근할 때와 동일한 헤더를 보내야 한다.
_VIEWER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.nl.go.kr/",
}

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

    supports_asset_download = True
    """KORCIS 원문 뷰어(viewer.nl.go.kr) 이미지 다운로드를 지원한다.

    왜 이렇게 하는가:
        연구자가 viewer URL을 붙여넣으면 서지정보 + 원문 이미지를
        한 번에 가져와 문헌을 생성할 수 있어야 한다.
        에셋 다운로드 플래그를 켜면 GUI에서 "문헌 생성" 버튼이 활성화된다.
    """

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
        """KORCIS 또는 원문 뷰어 URL에서 메타데이터를 가져온다.

        입력:
            url — KORCIS 또는 뷰어 URL.
                  예1: https://www.nl.go.kr/korcis/search/searchResultDetail.do?vdkvgwkey=302554414
                  예2: https://viewer.nl.go.kr/main.wviewer?cno=KOL000021131
        출력:
            MARC 필드 또는 뷰어 메타데이터를 파싱한 dict.

        왜 이렇게 하는가:
            연구자가 KORCIS 또는 뷰어에서 복사한 URL을 붙여넣으면
            적절한 방법으로 서지정보를 가져온다.
            뷰어 URL의 경우 이미지 다운로드용 메타데이터도 함께 포함한다.
        """
        # ── 원문 뷰어 URL (viewer.nl.go.kr) ──
        if "viewer.nl.go.kr" in url:
            m = re.search(r"[?&]cno=([A-Z0-9]+)", url, re.IGNORECASE)
            if m:
                return await self._fetch_viewer(m.group(1))
            raise ValueError(
                f"뷰어 URL에서 cno를 추출할 수 없습니다: {url}\n"
                "→ 지원 URL: https://viewer.nl.go.kr/main.wviewer?cno=KOL..."
            )

        # ── 목차/해제 팝업 URL (controlNo 기반) ──
        # contentsInfo.do?controlNo=KOL... 또는 abstractsInfo.do?controlNo=KOL...
        m_ctrl = re.search(r"[?&]controlNo=([A-Z0-9]+)", url, re.IGNORECASE)
        if m_ctrl and ("contentsInfo" in url or "abstractsInfo" in url):
            control_no = m_ctrl.group(1)
            return await self._fetch_by_control_no(control_no)

        # ── MARC 팝업 URL (BIB/HOLD/LOCAL) ──
        m_vdk = re.search(r"vdkvgwkey=(\d+)", url)
        if m_vdk:
            item_id = m_vdk.group(1)
            # HOLD/LOCAL 타겟이더라도 vdkvgwkey로 BIB MARC를 가져온 뒤 보강한다.
            data = await self.fetch_detail(item_id)
            # BIB MARC의 012 필드에서 controlNo 추출 → 목차/해제 보강
            await self._enrich_with_contents(data)
            return data

        # fnDetail('ID') 패턴에서 추출 (혹시 JS 링크를 복사한 경우)
        m = re.search(r"fnDetail\(['\"](\d+)['\"]\)", url)
        if m:
            data = await self.fetch_detail(m.group(1))
            await self._enrich_with_contents(data)
            return data

        # marcKey 파라미터에서 ID 추출 (MARC 팝업 URL)
        m = re.search(r"marcKey=(\d+)", url)
        if m:
            data = await self.fetch_detail(m.group(1))
            await self._enrich_with_contents(data)
            return data

        raise ValueError(
            f"KORCIS URL에서 자료 ID를 추출할 수 없습니다: {url}\n"
            "→ 지원 URL 형식:\n"
            "  - https://www.nl.go.kr/korcis/.../searchResultDetail.do?vdkvgwkey=...\n"
            "  - https://nl.go.kr/korcis/.../contentsInfo.do?controlNo=KOL...\n"
            "  - https://nl.go.kr/korcis/.../abstractsInfo.do?controlNo=KOL...\n"
            "  - https://viewer.nl.go.kr/main.wviewer?cno=KOL..."
        )

    async def _fetch_by_control_no(self, control_no: str) -> dict[str, Any]:
        """controlNo(KOL...)로 목차와 해제를 가져온다.

        입력:
            control_no — KORCIS 제어번호 (예: "KOL000000392").
        출력:
            {_contents_info, _abstracts_info, control_no, source_url, ...}

        왜 이렇게 하는가:
            contentsInfo/abstractsInfo URL에는 controlNo만 있고
            vdkvgwkey가 없다. MARC 조회는 불가하지만,
            목차와 해제는 controlNo만으로 직접 가져올 수 있다.
            연구자가 이 URL을 붙여넣었다면 목차/해제 데이터가 목적이다.
        """
        data: dict[str, Any] = {"control_no": control_no}

        contents = await _fetch_contents_info(control_no)
        if contents:
            data["_contents_info"] = contents

        abstracts = await _fetch_abstracts_info(control_no)
        if abstracts:
            data["_abstracts_info"] = abstracts

        data["source_url"] = (
            f"{_KORCIS_BASE}/korcis/search/popup/contentsInfo.do"
            f"?controlNo={control_no}"
        )

        return data

    async def _enrich_with_contents(self, data: dict[str, Any]) -> None:
        """BIB MARC 데이터에 목차와 해제를 보강한다.

        입력/출력:
            data — fetch_detail이 반환한 MARC dict. 직접 수정한다.

        왜 이렇게 하는가:
            MARC 012 필드에 controlNo(KOL...)가 들어있다.
            이를 추출하여 contentsInfo/abstractsInfo를 가져오면
            MARC 서지 + 목차 + 해제가 한 번에 보강된다.
            012 필드가 없으면 보강 없이 넘어간다.
        """
        # MARC 012 ▼a 또는 035 ▼a에서 controlNo 추출
        control_no = None
        marc012 = data.get("012", {})
        if isinstance(marc012, dict) and marc012.get("a"):
            control_no = marc012["a"].strip()
        if not control_no:
            marc035 = data.get("035", {})
            if isinstance(marc035, dict) and marc035.get("a"):
                # "(011001)KOL000000392" → "KOL000000392"
                m = re.search(r"(KOL\d+)", marc035["a"])
                if m:
                    control_no = m.group(1)

        if not control_no:
            return

        data["control_no"] = control_no

        try:
            contents = await _fetch_contents_info(control_no)
            if contents:
                data["_contents_info"] = contents

            abstracts = await _fetch_abstracts_info(control_no)
            if abstracts:
                data["_abstracts_info"] = abstracts
        except Exception as e:
            logger.warning("목차/해제 보강 실패 (controlNo=%s): %s", control_no, e)

    async def _fetch_viewer(self, cno: str) -> dict[str, Any]:
        """국립중앙도서관 원문 뷰어에서 서지정보와 페이지 메타데이터를 추출한다.

        입력:
            cno — 제어번호 (예: "KOL000021131").
        출력:
            서지정보 + 뷰어 메타데이터 dict.
            {title, creator, date, publisher, cno, vol_maxpage, maxpage, ...}

        왜 이렇게 하는가:
            viewer.nl.go.kr은 2단계 세션 인증이 필요하다:
            1) POST main.wviewer (ax=Y) → JSESSIONID 획득
            2) 응답 HTML에서 서지정보와 JavaScript 변수 파싱
            Referer 헤더 없이는 404를 반환하므로 브라우저 헤더를 모방한다.
        """
        form_data = {
            "cno": cno,
            "ax": "Y",
            "sip": "0.0.0.0",
        }

        # 뷰어 서버가 응답이 느릴 수 있으므로 타임아웃을 넉넉히 설정한다.
        async with httpx.AsyncClient(
            timeout=60.0,
            follow_redirects=True,
            headers=_VIEWER_HEADERS,
        ) as client:
            response = await client.post(_VIEWER_URL, data=form_data)
            response.raise_for_status()

        return _parse_viewer_html(response.text, cno)

    async def list_assets(self, raw_data: dict[str, Any]) -> list[dict[str, Any]]:
        """원문 뷰어에서 다운로드 가능한 에셋 목록을 반환한다.

        입력:
            raw_data — fetch_by_url 또는 _fetch_viewer가 반환한 dict.
                       _viewer 키에 뷰어 메타데이터가 포함되어 있어야 한다.
        출력:
            [{asset_id, label, page_count, download_type}, ...]

        왜 이렇게 하는가:
            뷰어 HTML의 JavaScript 변수에서 볼륨별 페이지 수를 알 수 있다.
            vol_maxpage가 쉼표 구분 문자열로 각 볼륨의 최대 페이지를 제공한다.
        """
        viewer = raw_data.get("_viewer", {})
        if not viewer:
            return []

        cno = viewer.get("cno", "")
        title = viewer.get("title", cno)

        # vol_maxpage: "143" 또는 "50,60,33" (볼륨별 페이지 수)
        vol_pages_str = viewer.get("vol_maxpage", "")
        if not vol_pages_str:
            return []

        vol_pages = [p.strip() for p in vol_pages_str.split(",") if p.strip()]
        assets = []
        for vol_idx, pages_str in enumerate(vol_pages, 1):
            try:
                page_count = int(pages_str)
            except ValueError:
                continue
            assets.append({
                "asset_id": cno,
                "vol": vol_idx,
                "label": f"{title}_v{vol_idx}" if len(vol_pages) > 1 else title,
                "page_count": page_count,
                "download_type": "viewer_png",
            })

        return assets

    async def download_asset(
        self,
        asset_info: dict[str, Any],
        dest_dir: Path,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> Path:
        """원문 뷰어에서 이미지를 다운로드하여 PDF로 합친다.

        입력:
            asset_info — list_assets()가 반환한 항목.
                         {asset_id(=cno), vol, page_count, label, download_type}
            dest_dir — 파일을 저장할 디렉토리.
            progress_callback — (현재 페이지, 총 페이지)를 받는 콜백.
        출력:
            생성된 PDF 파일의 Path.

        왜 이렇게 하는가:
            viewer.nl.go.kr은 각 페이지를 PNG로 제공한다.
            세션 쿠키가 있어야 이미지를 받을 수 있으므로,
            먼저 POST로 세션을 획득한 뒤 개별 페이지를 순차 다운로드한다.
            fpdf2로 PNG들을 하나의 PDF로 결합한다.
        """
        from fpdf import FPDF
        from PIL import Image

        cno = asset_info["asset_id"]
        vol = asset_info.get("vol", 1)
        page_count = asset_info["page_count"]
        label = asset_info.get("label", cno)
        dest_dir = Path(dest_dir)

        # 1. 세션 획득 (POST main.wviewer)
        form_data = {"cno": cno, "ax": "Y", "sip": "0.0.0.0"}

        async with httpx.AsyncClient(
            timeout=60.0,
            follow_redirects=True,
            headers=_VIEWER_HEADERS,
        ) as client:
            session_resp = await client.post(_VIEWER_URL, data=form_data)
            session_resp.raise_for_status()
            # 세션 쿠키는 client가 자동 관리한다.

            # 2. 각 페이지 이미지 다운로드
            png_paths: list[Path] = []
            for page_num in range(1, page_count + 1):
                params = {
                    "cno": cno,
                    "vol": str(vol),
                    "page": str(page_num),
                    "twoThreeYn": "N",
                }
                resp = await client.get(_VIEWER_IMAGE_URL, params=params)
                resp.raise_for_status()

                # 빈 응답 건너뛰기 (일부 페이지가 비어있을 수 있음)
                if len(resp.content) < 100:
                    logger.warning(
                        "빈 이미지 응답 (cno=%s, vol=%d, page=%d): %d bytes",
                        cno, vol, page_num, len(resp.content),
                    )
                    continue

                png_path = dest_dir / f"{cno}_v{vol}_p{page_num:04d}.png"
                png_path.write_bytes(resp.content)
                png_paths.append(png_path)

                if progress_callback:
                    progress_callback(page_num, page_count)

        if not png_paths:
            raise ValueError(
                f"다운로드된 이미지가 없습니다: cno={cno}, vol={vol}\n"
                "→ 원인: 뷰어 세션이 만료되었거나 접근이 차단되었을 수 있습니다."
            )

        # 3. PNG → PDF 결합
        pdf = FPDF(unit="pt")
        for png_path in png_paths:
            with Image.open(png_path) as img:
                w_px, h_px = img.size
            # 150dpi 기준으로 포인트 변환 (고서 스캔 표준)
            w_pt = w_px * 72 / 150
            h_pt = h_px * 72 / 150
            pdf.add_page(format=(w_pt, h_pt))
            pdf.image(str(png_path), x=0, y=0, w=w_pt, h=h_pt)

        safe_label = re.sub(r'[<>:"/\\|?*]', "_", label)
        pdf_path = dest_dir / f"{safe_label}.pdf"
        pdf.output(str(pdf_path))

        logger.info(
            "PDF 생성 완료 (KORCIS 뷰어): %s (%d페이지, %.1fMB)",
            pdf_path.name,
            len(png_paths),
            pdf_path.stat().st_size / 1024 / 1024,
        )

        return pdf_path


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
        """KORCIS MARC 또는 뷰어 데이터를 bibliography.json 형식으로 변환한다.

        입력: raw_data — KorcisFetcher가 반환한 파싱된 dict.
              MARC 데이터이면 245, 100 등의 키가 있고,
              뷰어 데이터이면 title, author, _viewer 키가 있다.
        출력: bibliography.schema.json 준수 dict.
        """
        # ── 뷰어 데이터 경로 ──
        if "_viewer" in raw_data:
            return self._map_viewer_to_bibliography(raw_data)

        # ── controlNo-only 경로 (목차/해제만 있고 MARC 없음) ──
        if "control_no" in raw_data and "245" not in raw_data:
            return self._map_control_no_to_bibliography(raw_data)

        # ── MARC 데이터 경로 ──
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

        # 목차 정보 (contentsInfo 보강)
        contents_info = raw_data.get("_contents_info")

        # 해제 정보 (abstractsInfo 보강)
        abstracts_info = raw_data.get("_abstracts_info")

        # 시스템 ID
        system_ids = {}
        control_no = raw_data.get("control_no") or raw_data.get("001")
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
        if contents_info:
            field_sources["contents"] = self._field_source(
                "contentsInfo 팝업", "exact", "controlNo 기반 목차 조회"
            )
        if abstracts_info:
            field_sources["abstracts"] = self._field_source(
                "abstractsInfo 팝업", "exact", "controlNo 기반 해제 조회"
            )

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
            "contents": contents_info,
            "abstracts": abstracts_info,
        }

        return bibliography

    def _map_control_no_to_bibliography(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """controlNo-only 데이터를 bibliography.json으로 매핑한다.

        왜 이렇게 하는가:
            연구자가 contentsInfo/abstractsInfo URL을 붙여넣으면
            MARC 없이 목차와 해제만 있다. 이 경우에도
            최소한의 bibliography 객체를 반환하여
            나중에 MARC 데이터와 병합할 수 있도록 한다.
        """
        control_no = raw_data.get("control_no", "")
        contents_info = raw_data.get("_contents_info")
        abstracts_info = raw_data.get("_abstracts_info")

        system_ids = {"control_number": control_no}

        field_sources: dict[str, dict] = {}
        if contents_info:
            field_sources["contents"] = self._field_source(
                "contentsInfo 팝업", "exact"
            )
        if abstracts_info:
            field_sources["abstracts"] = self._field_source(
                "abstractsInfo 팝업", "exact"
            )

        bibliography = {
            "title": None,
            "title_reading": None,
            "alternative_titles": None,
            "creator": None,
            "contributors": None,
            "date_created": None,
            "edition_type": None,
            "language": None,
            "script": None,
            "physical_description": None,
            "printing_info": None,
            "publishing": None,
            "extent": None,
            "subject": None,
            "classification": None,
            "series_title": None,
            "material_type": None,
            "repository": None,
            "digital_source": {
                "platform": "한국고문헌종합목록 (KORCIS)",
                "source_url": raw_data.get("source_url"),
                "permanent_uri": None,
                "system_ids": system_ids,
                "license": None,
                "accessed_at": None,
            },
            "raw_metadata": {
                "source_system": "korcis",
                **raw_data,
            },
            "_mapping_info": self._make_mapping_info(
                field_sources=field_sources,
                api_variant="control_no_popup",
            ),
            "notes": None,
            "contents": contents_info,
            "abstracts": abstracts_info,
        }

        return bibliography

    def _map_viewer_to_bibliography(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """뷰어 HTML에서 추출한 데이터를 bibliography.json으로 매핑한다.

        왜 이렇게 하는가:
            뷰어 데이터는 MARC보다 필드가 적지만,
            연구자가 뷰어 URL만 알 때도 최소한의 서지정보를 제공할 수 있다.
            MARC 조회 없이도 제목, 저자, 발행일, 발행자는 확보된다.
        """
        viewer = raw_data.get("_viewer", {})
        title = raw_data.get("title")
        author = raw_data.get("author")

        creator = None
        if author:
            creator = {
                "name": author,
                "name_reading": None,
                "role": "author",
                "period": None,
            }

        date_created = raw_data.get("date_created")
        # 뷰어의 "1714----" 같은 형식 정리
        if date_created:
            date_created = re.sub(r"-+$", "", date_created).strip() or None

        publisher = raw_data.get("publisher")
        publishing = None
        if publisher:
            publishing = {
                "place": None,
                "publisher": publisher,
                "publication_type": None,
            }

        cno = viewer.get("cno", "")
        system_ids = {"control_number": cno}
        kolis_no = viewer.get("kolis_no")
        if kolis_no and kolis_no != cno:
            system_ids["kolis_number"] = kolis_no

        field_sources = {
            "title": self._field_source("뷰어 hidden input erBookTitle", "exact"),
            "creator.name": self._field_source("뷰어 hidden input erAuthor", "exact"),
            "date_created": self._field_source("뷰어 bookInfo 발행일", "exact"),
        }
        if publishing:
            field_sources["publishing"] = self._field_source(
                "뷰어 bookInfo 발행자", "exact"
            )

        bibliography = {
            "title": title,
            "title_reading": None,
            "alternative_titles": None,
            "creator": creator,
            "contributors": None,
            "date_created": date_created,
            "edition_type": None,
            "language": None,
            "script": None,
            "physical_description": None,
            "printing_info": None,
            "publishing": publishing,
            "extent": None,
            "subject": None,
            "classification": None,
            "series_title": None,
            "material_type": None,
            "repository": None,
            "digital_source": {
                "platform": "국립중앙도서관 원문 뷰어",
                "source_url": raw_data.get("source_url"),
                "permanent_uri": None,
                "system_ids": system_ids,
                "license": raw_data.get("copyright_type"),
                "accessed_at": None,
            },
            "raw_metadata": {
                "source_system": "korcis_viewer",
                **raw_data,
            },
            "_mapping_info": self._make_mapping_info(
                field_sources=field_sources,
                api_variant="viewer_html_scraping",
            ),
            "notes": None,
        }

        return bibliography


# --- 목차/해제 팝업 파싱 유틸리티 ---


async def _fetch_contents_info(control_no: str) -> list[dict[str, str]] | None:
    """목차 팝업에서 목차 정보를 가져온다.

    입력:
        control_no — KORCIS 제어번호 (예: "KOL000000392").
    출력:
        [{"title": "海東諸國紀", "page": "1"}, ...] 또는 None.

    왜 이렇게 하는가:
        목차 팝업은 GET으로 직접 접근 가능하며,
        "제목 = 페이지번호" 형식의 간단한 HTML을 반환한다.
        이 구조를 파싱하여 목차 리스트로 반환한다.
    """
    params = {"controlNo": control_no}
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(_CONTENTS_INFO_URL, params=params)
            response.raise_for_status()

        return _parse_contents_html(response.text)
    except Exception as e:
        logger.warning("목차 조회 실패 (controlNo=%s): %s", control_no, e)
        return None


async def _fetch_abstracts_info(control_no: str) -> str | None:
    """해제 팝업에서 해제(학술 해설) 텍스트를 가져온다.

    입력:
        control_no — KORCIS 제어번호 (예: "KOL000000392").
    출력:
        해제 텍스트 문자열 또는 None.

    왜 이렇게 하는가:
        해제 팝업은 GET으로 직접 접근 가능하며,
        <kabs> 태그 안에 수천 자의 학술 해설이 들어있다.
        고전 문헌 연구에 극히 귀중한 정보다.
    """
    params = {"controlNo": control_no}
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(_ABSTRACTS_INFO_URL, params=params)
            response.raise_for_status()

        return _parse_abstracts_html(response.text)
    except Exception as e:
        logger.warning("해제 조회 실패 (controlNo=%s): %s", control_no, e)
        return None


def _parse_contents_html(html_text: str) -> list[dict[str, str]] | None:
    """목차 팝업 HTML을 파싱한다.

    입력 예 (popupContent 내부):
        表紙&nbsp;=&nbsp;0<br/>
        海東諸國紀&nbsp;=&nbsp;1<br/>
    출력:
        [{"title": "表紙", "page": "0"}, {"title": "海東諸國紀", "page": "1"}]

    왜 이렇게 하는가:
        목차 HTML은 "제목 = 페이지" 형식이 <br/> 로 구분되어 있다.
        &nbsp;는 공백으로, =는 구분자로 처리한다.
    """
    # popupContent div 안의 내용 추출
    m = re.search(
        r'class="popupContent[^"]*"[^>]*>(.*?)</div>',
        html_text,
        re.DOTALL,
    )
    if not m:
        return None

    content = m.group(1)
    # HTML 엔티티 정리
    content = content.replace("&nbsp;", " ").replace("&amp;", "&")

    entries: list[dict[str, str]] = []
    # <br/> 또는 <br> 로 분리
    lines = re.split(r"<br\s*/?>", content)
    for line in lines:
        # HTML 태그 제거
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line:
            continue

        # "제목 = 페이지번호" 패턴 분리
        if "=" in line:
            parts = line.rsplit("=", 1)
            title = parts[0].strip()
            page = parts[1].strip() if len(parts) > 1 else ""
            if title:
                entries.append({"title": title, "page": page})
        else:
            # = 없는 줄은 제목만
            entries.append({"title": line, "page": ""})

    return entries if entries else None


def _parse_abstracts_html(html_text: str) -> str | None:
    """해제 팝업 HTML에서 해제 텍스트를 추출한다.

    입력 예:
        <id>KOL000000392<br><kabs><br> 『해동제국기...』는 ...
    출력:
        정리된 해제 텍스트 문자열.

    왜 이렇게 하는가:
        해제 HTML은 비표준 태그(<id>, <kabs>)를 사용하며,
        <br> 태그로 문단을 구분한다.
        HTML을 정리하여 읽기 좋은 텍스트로 변환한다.
    """
    # popupContent div 안의 내용 추출
    m = re.search(
        r'class="popupContent[^"]*"[^>]*>(.*?)</div>',
        html_text,
        re.DOTALL,
    )
    if not m:
        return None

    content = m.group(1)

    # <id>...</id> 또는 <id>...<br> 태그 제거 (제어번호)
    content = re.sub(r"<id>[^<]*(?:<br>|</id>)", "", content)
    # <kabs> 태그 제거
    content = re.sub(r"</?kabs>", "", content)
    # <br> → 줄바꿈
    content = re.sub(r"<br\s*/?>", "\n", content)
    # 나머지 HTML 태그 제거
    content = re.sub(r"<[^>]+>", "", content)
    # HTML 엔티티
    content = content.replace("&nbsp;", " ").replace("&amp;", "&")
    # 연속 줄바꿈 정리
    content = re.sub(r"\n{3,}", "\n\n", content)

    text = content.strip()
    return text if text else None


# --- 뷰어 HTML 파싱 유틸리티 ---


def _parse_viewer_html(html_text: str, cno: str) -> dict[str, Any]:
    """원문 뷰어 HTML에서 서지정보와 페이지 메타데이터를 추출한다.

    입력:
        html_text — POST main.wviewer 응답 HTML.
        cno — 제어번호 (fallback 용).
    출력:
        MARC 파서와 호환되는 dict +  _viewer 키에 뷰어 메타데이터.

    왜 이렇게 하는가:
        뷰어 HTML에는 두 가지 형태로 데이터가 들어있다:
        1) hidden input / bookInfo <ul> — 서지 정보
        2) JavaScript 변수 — 페이지·볼륨 메타데이터
        둘 다 파싱하여 하나의 dict로 합친다.
    """
    data: dict[str, Any] = {}

    # ── 1. hidden input에서 서지 기본 정보 추출 ──
    # <input type="hidden" name="erBookTitle" title="서명" value="海東諸國紀" />
    hidden_fields = {
        "erControlNo": "control_no",
        "erBookTitle": "title",
        "erAuthor": "author",
        "erFlag": "system_code",
    }
    for field_name, key in hidden_fields.items():
        m = re.search(
            rf'name="{field_name}"[^>]*value="([^"]*)"',
            html_text,
        )
        if m and m.group(1):
            data[key] = m.group(1)

    # ── 2. bookInfo <ul>에서 상세 서지 추출 ──
    # <span class="label tispan">서명</span>
    # <span class="text">海東諸國紀</span>
    label_map = {
        "tispan": "title",
        "authorspan": "author",
        "issuedatespan": "date_created",
        "issuerspan": "publisher",
        "copyspan": "copyright_type",
    }
    for css_class, key in label_map.items():
        # label 다음의 text span 값 추출
        pattern = (
            rf'class="label\s+{css_class}"[^>]*>.*?</span>\s*'
            rf'<span class="text">([^<]*)</span>'
        )
        m = re.search(pattern, html_text, re.DOTALL)
        if m and m.group(1).strip():
            # bookInfo가 hidden input보다 우선 (더 상세할 수 있음)
            data[key] = m.group(1).strip()

    # ── 3. JavaScript 변수에서 페이지/볼륨 메타데이터 추출 ──
    viewer_meta: dict[str, Any] = {"cno": cno}

    js_vars = {
        "srcpath": "srcpath",
        "maxpage": "maxpage",
        "ext": "ext",
        "vol_maxpage": "vol_maxpage",
        "curVol": "cur_vol",
        "kolis_no": "kolis_no",
        "DataClassCd": "data_class",
        "saveYn": "save_yn",
        "printYn": "print_yn",
    }
    for js_name, key in js_vars.items():
        # var name = "value"; 또는 var name = 123; 패턴
        m = re.search(
            rf'var\s+{js_name}\s*=\s*["\']?([^"\';\n]+)["\']?\s*;',
            html_text,
        )
        if m and m.group(1).strip():
            viewer_meta[key] = m.group(1).strip()

    # title을 viewer_meta에도 복사 (list_assets에서 label로 사용)
    viewer_meta["title"] = data.get("title", cno)

    data["_viewer"] = viewer_meta

    # 뷰어 URL을 source_url로 설정
    data["source_url"] = f"{_VIEWER_BASE}/main.wviewer?cno={cno}"

    return data


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

            if tag == "012":
                # 012 ▼a = controlNo (KOL...) — 목차/해제 조회 키
                data["012"] = subfields
            elif tag == "001":
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
