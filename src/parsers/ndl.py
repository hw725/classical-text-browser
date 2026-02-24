"""NDL Search (国立国会図書館サーチ) 파서.

platform-v7.md §7.2.2 기반:
    - OpenSearch API: https://ndlsearch.ndl.go.jp/api/opensearch
    - 응답 형식: RSS/XML (DC-NDL 스키마)
    - 인증: 비영리는 불필요
    - 검색 결과 500건 제한

DC-NDL 주요 필드 매핑:
    dc:title → title
    dcndl:titleTranscription → title_reading
    dc:creator → creator.name
    dcndl:creatorTranscription → creator.name_reading
    dcterms:issued → date_created
    dc:extent → physical_description
    dc:subject → subject
    dcndl:NDLC / dcndl:NDC10 → classification
    dcndl:materialType → material_type
    dcndl:seriesTitle → series_title
    rdfs:seeAlso → digital_source.source_url
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from parsers.base import BaseFetcher, BaseMapper, register_parser

logger = logging.getLogger(__name__)

# NDL Digital Collections IIIF API 패턴
_NDL_IIIF_MANIFEST_URL = "https://dl.ndl.go.jp/api/iiif/{pid}/manifest.json"

# XML 네임스페이스 맵 — NDL OpenSearch 응답에서 사용
_NS = {
    "rss": "http://purl.org/rss/1.0/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcndl": "http://ndl.go.jp/dcndl/terms/",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "openSearch": "http://a9.com/-/spec/opensearchrss/1.0/",
}

# NDL OpenSearch API 엔드포인트
_NDL_OPENSEARCH_URL = "https://ndlsearch.ndl.go.jp/api/opensearch"


class NdlFetcher(BaseFetcher):
    """NDL OpenSearch API에서 서지 데이터를 추출한다.

    왜 OpenSearch를 선택하는가:
        - SRU보다 파라미터가 단순하다 (any=키워드, cnt=건수).
        - 비영리 이용 시 인증이 필요 없다.
        - 응답에 DC-NDL 전체 필드가 포함된다.
    """

    parser_id = "ndl"
    parser_name = "国立国会図書館サーチ (NDL Search)"
    api_variant = "opensearch"
    supports_asset_download = True

    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        """NDL OpenSearch로 키워드 검색을 수행한다.

        입력:
            query — 검색어 (예: "蒙求").
            cnt — 반환 건수 (기본 10, 최대 500).
            mediatype — 자료 유형 필터 (1=본, 2=기사, 9=디지털 등).
        출력:
            [{title, creator, item_id, summary, raw}, ...]
            raw에는 XML 요소에서 추출한 전체 필드가 들어 있다.
        """
        cnt = kwargs.get("cnt", 10)
        mediatype = kwargs.get("mediatype", None)

        params: dict[str, Any] = {
            "any": query,
            "cnt": cnt,
        }
        if mediatype is not None:
            params["mediatype"] = mediatype

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(_NDL_OPENSEARCH_URL, params=params)
            response.raise_for_status()

        # XML 파싱
        # NDL OpenSearch는 RSS 2.0 형식: <rss><channel><item>...</item></channel></rss>
        # <item> 요소에는 네임스페이스가 없다 (RSS 2.0 표준).
        root = ET.fromstring(response.content)
        items = root.findall(".//item")

        results = []
        for item in items:
            raw = _parse_item_xml(item)
            results.append({
                "title": raw.get("dc:title"),
                "creator": raw.get("dc:creator"),
                "item_id": raw.get("dcndl:NDLBibID"),
                "material_type": raw.get("dcndl:materialType"),
                "issued": raw.get("dcterms:issued"),
                "summary": _build_summary(raw),
                "raw": raw,
            })

        return results

    async def fetch_by_url(self, url: str) -> dict[str, Any]:
        """NDL URL에서 NDLBibID를 추출하여 상세 정보를 가져온다.

        지원 URL 패턴:
            - https://ndlsearch.ndl.go.jp/books/R100000002-I...
              → NDLBibID는 URL 끝 숫자 9자리
            - https://dl.ndl.go.jp/info:ndljp/pid/...
              → PID 기반 — PID를 검색어로 사용
            - https://id.ndl.go.jp/bib/...
              → NDLBibID 직접 포함

        왜 이렇게 하는가:
            연구자가 NDL 웹사이트에서 복사한 URL을 붙여넣으면,
            검색 없이 바로 서지정보를 가져올 수 있다.
        """
        # 패턴 1: ndlsearch.ndl.go.jp/books/R100000002-I{NDLBibID}
        m = re.search(r"ndlsearch\.ndl\.go\.jp/books/R\d+-I(\d+)", url)
        if m:
            return await self.fetch_detail(m.group(1))

        # 패턴 2: id.ndl.go.jp/bib/{NDLBibID}
        m = re.search(r"id\.ndl\.go\.jp/bib/(\d+)", url)
        if m:
            return await self.fetch_detail(m.group(1))

        # 패턴 3: dl.ndl.go.jp/info:ndljp/pid/{PID} 또는 dl.ndl.go.jp/pid/{PID}
        m = re.search(r"dl\.ndl\.go\.jp/(?:info:ndljp/)?pid/(\d+)", url)
        if m:
            pid = m.group(1)
            # PID를 검색어로 사용하여 관련 서지 레코드를 찾는다
            results = await self.search(pid, cnt=1)
            if results:
                raw_data = results[0]["raw"]
            else:
                raw_data = {}

            # IIIF manifest에서 추가 메타데이터 보강 + PID 저장
            # 왜: list_assets()에서 PID로 IIIF 이미지를 다운로드하기 위해.
            # 실패해도 OpenSearch 결과는 그대로 유지한다.
            raw_data["_ndl_pid"] = pid
            try:
                from parsers.iiif_utils import extract_iiif_metadata, fetch_iiif_manifest

                manifest_url = _NDL_IIIF_MANIFEST_URL.format(pid=pid)
                manifest = await fetch_iiif_manifest(manifest_url)
                iiif_meta = extract_iiif_metadata(manifest)
                raw_data["_iiif_metadata"] = iiif_meta
                raw_data["_iiif_manifest_url"] = manifest_url
                # IIIF 메타데이터로 누락 필드 보강 (OpenSearch에 없는 경우)
                if not raw_data.get("dc:title") and iiif_meta.get("title"):
                    raw_data["dc:title"] = iiif_meta["title"]
            except Exception as e:
                logger.warning("IIIF manifest 가져오기 실패 (PID=%s): %s", pid, e)

            if not raw_data.get("dc:title"):
                raise FileNotFoundError(
                    f"NDL에서 PID {pid}에 대한 서지 정보를 찾을 수 없습니다.\n"
                    "→ 해결: URL이 올바른지 확인하세요."
                )
            return raw_data

        # 어떤 패턴에도 매칭되지 않으면 URL 자체를 검색어로 시도
        raise ValueError(
            f"NDL URL에서 ID를 추출할 수 없습니다: {url}\n"
            "→ 지원 URL: ndlsearch.ndl.go.jp/books/..., "
            "id.ndl.go.jp/bib/..., dl.ndl.go.jp/pid/..."
        )

    async def fetch_detail(self, item_id: str, **kwargs) -> dict[str, Any]:
        """NDLBibID로 특정 항목의 상세 정보를 가져온다.

        왜 이렇게 하는가:
            NDL OpenSearch는 검색 결과에 이미 전체 필드를 포함하므로,
            별도의 상세 조회가 불필요한 경우가 많다.
            하지만 NDLBibID로 정확히 1건을 가져올 때 사용한다.
        """
        params = {"any": item_id, "cnt": 1}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(_NDL_OPENSEARCH_URL, params=params)
            response.raise_for_status()

        root = ET.fromstring(response.content)
        items = root.findall(".//item")

        if not items:
            raise FileNotFoundError(
                f"NDL에서 항목을 찾을 수 없습니다: {item_id}\n"
                "→ 해결: NDLBibID를 확인하세요."
            )

        return _parse_item_xml(items[0])

    async def list_assets(self, raw_data: dict[str, Any]) -> list[dict[str, Any]]:
        """IIIF manifest에서 다운로드 가능한 에셋(이미지) 목록을 조회한다.

        동작:
            1. raw_data에서 _ndl_pid를 추출한다.
            2. IIIF manifest에서 캔버스 목록을 가져온다.
            3. 전체를 하나의 에셋으로 묶어 반환한다.

        왜 전체를 하나의 에셋으로:
            NDL Digital Collections의 PID는 하나의 자료를 가리킨다.
            국립공문서관처럼 BID→MID 계층이 없으므로,
            PID 전체 = 하나의 에셋이 자연스럽다.

        출력: [{asset_id, id, label, page_count, download_type, _canvases}, ...]
        """
        pid = raw_data.get("_ndl_pid")
        if not pid:
            return []

        from parsers.iiif_utils import extract_iiif_canvases, fetch_iiif_manifest

        manifest_url = raw_data.get(
            "_iiif_manifest_url",
            _NDL_IIIF_MANIFEST_URL.format(pid=pid),
        )
        try:
            manifest = await fetch_iiif_manifest(manifest_url)
            canvases = extract_iiif_canvases(manifest)
        except Exception as e:
            logger.warning("IIIF 캔버스 목록 조회 실패: %s", e)
            return []

        if not canvases:
            return []

        label = raw_data.get("dc:title") or f"NDL-{pid}"
        return [{
            "asset_id": f"ndl_iiif_{pid}",
            "id": f"ndl_iiif_{pid}",
            "label": label,
            "page_count": len(canvases),
            "file_size": None,  # IIIF는 전체 크기를 사전에 알 수 없음
            "download_type": "iiif",
            "_canvases": canvases,
            "_manifest_url": manifest_url,
        }]

    async def download_asset(
        self,
        asset_info: dict[str, Any],
        dest_dir: Path,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> Path:
        """IIIF 이미지를 다운로드하여 PDF로 변환한다.

        왜 이렇게 하는가:
            archives_jp.py의 JPEG→PDF 패턴과 동일한 방식.
            IIIF Image API의 size 파라미터로 적절한 해상도를 선택한다.
        """
        from parsers.iiif_utils import download_iiif_images_as_pdf

        canvases = asset_info.get("_canvases", [])
        if not canvases:
            raise ValueError("에셋에 캔버스 정보가 없습니다.")

        label = asset_info.get("label", "ndl_download")
        return await download_iiif_images_as_pdf(
            canvases=canvases,
            dest_dir=Path(dest_dir),
            label=label,
            progress_callback=progress_callback,
            max_dimension=1500,
        )


class NdlMapper(BaseMapper):
    """NDL DC-NDL 데이터를 bibliography.json 공통 스키마로 매핑한다.

    매핑 테이블 (platform-v7.md §7.3.2):
        dc:title → title
        dcndl:titleTranscription → title_reading
        dc:creator → creator.name
        dcndl:creatorTranscription → creator.name_reading
        dcterms:issued / dc:date → date_created
        dc:extent → physical_description
        dc:subject (자유어) → subject
        dc:subject[@type=dcndl:NDLC] → classification.NDLC
        dc:subject[@type=dcndl:NDC10] → classification.NDC10
        dcndl:materialType → material_type
        dcndl:seriesTitle → series_title
        rdfs:seeAlso → digital_source.source_url
        dcndl:NDLBibID → digital_source.system_ids.NDLBibID
        dcndl:JPNO → digital_source.system_ids.JPNO
    """

    parser_id = "ndl"

    def map_to_bibliography(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """NDL 원본 데이터를 bibliography.json 형식으로 변환한다.

        입력: raw_data — NdlFetcher가 반환한 파싱된 dict.
        출력: bibliography.schema.json 준수 dict.
        """
        # 분류 정보 추출
        classification = {}
        ndlc = raw_data.get("dcndl:NDLC")
        ndc9 = raw_data.get("dcndl:NDC9")
        ndc10 = raw_data.get("dcndl:NDC10")
        if ndlc:
            classification["NDLC"] = ndlc
        if ndc9:
            classification["NDC9"] = ndc9
        if ndc10:
            classification["NDC10"] = ndc10

        # 시스템 ID 추출
        system_ids = {}
        bib_id = raw_data.get("dcndl:NDLBibID")
        jpno = raw_data.get("dcndl:JPNO")
        isbn = raw_data.get("dcndl:ISBN")
        if bib_id:
            system_ids["NDLBibID"] = bib_id
        if jpno:
            system_ids["JPNO"] = jpno
        if isbn:
            system_ids["ISBN"] = isbn

        # 주제어 추출 (분류 제외한 자유 주제어)
        subjects = raw_data.get("dc:subject_list", [])

        # 기여자 추출
        contributors_raw = raw_data.get("dcterms:contributor_list", [])
        contributors = None
        if contributors_raw:
            contributors = [
                {"name": c, "name_reading": None, "role": None, "period": None}
                for c in contributors_raw
            ]

        # seeAlso에서 URL 추출
        see_also = raw_data.get("rdfs:seeAlso")

        bibliography = {
            "title": raw_data.get("dc:title"),
            "title_reading": raw_data.get("dcndl:titleTranscription"),
            "alternative_titles": None,
            "creator": self._map_creator(raw_data),
            "contributors": contributors,
            "date_created": raw_data.get("dcterms:issued") or raw_data.get("dc:date"),
            "edition_type": None,  # NDL에는 판종 필드가 없다
            "language": None,
            "script": None,
            "physical_description": raw_data.get("dc:extent"),
            "subject": subjects if subjects else None,
            "classification": classification if classification else None,
            "series_title": raw_data.get("dcndl:seriesTitle"),
            "material_type": raw_data.get("dcndl:materialType"),
            "repository": None,
            "digital_source": {
                "platform": "NDL Search (国立国会図書館サーチ)",
                "source_url": see_also,
                "permanent_uri": see_also,
                "system_ids": system_ids if system_ids else None,
                "license": "CC-BY 4.0 (NDL 자관 데이터)",
                "accessed_at": None,
            },
            "raw_metadata": {
                "source_system": "ndl",
                **raw_data,
            },
            "_mapping_info": self._make_mapping_info(
                field_sources={
                    "title": self._field_source("dc:title", "exact"),
                    "title_reading": self._field_source("dcndl:titleTranscription", "exact"),
                    "creator.name": self._field_source("dc:creator", "exact"),
                    "creator.name_reading": self._field_source(
                        "dcndl:creatorTranscription", "exact"
                    ),
                    "date_created": self._field_source("dcterms:issued", "exact"),
                    "edition_type": self._field_source(None, None, "NDL에 해당 필드 없음"),
                    "physical_description": self._field_source("dc:extent", "exact"),
                    "subject": self._field_source("dc:subject", "exact"),
                    "classification": self._field_source(
                        "dc:subject[@type=dcndl:NDLC/NDC]", "exact"
                    ),
                    "material_type": self._field_source("dcndl:materialType", "exact"),
                    "series_title": self._field_source("dcndl:seriesTitle", "exact"),
                },
                api_variant="opensearch",
            ),
            "notes": raw_data.get("dc:description"),
        }

        return bibliography

    def _map_creator(self, raw_data: dict) -> dict | None:
        """저자 정보를 매핑한다."""
        name = raw_data.get("dc:creator")
        if not name:
            return None
        return {
            "name": name,
            "name_reading": raw_data.get("dcndl:creatorTranscription"),
            "role": "author",
            "period": None,
        }


# --- XML 파싱 유틸리티 ---


def _parse_item_xml(item: ET.Element) -> dict[str, Any]:
    """RSS item 요소에서 DC-NDL 필드를 추출한다.

    왜 이렇게 하는가:
        NDL OpenSearch 응답의 각 <item>에는 다양한 네임스페이스의
        요소가 섞여 있다. 이 함수에서 필요한 필드만 추출하여
        평탄한 dict로 변환한다.
    """
    data: dict[str, Any] = {}

    # 단일 값 필드
    _extract_text(item, "dc:title", data, _NS)
    _extract_text(item, "dcndl:titleTranscription", data, _NS)
    _extract_text(item, "dc:creator", data, _NS)
    _extract_text(item, "dcndl:creatorTranscription", data, _NS)
    _extract_text(item, "dc:publisher", data, _NS)
    _extract_text(item, "dcndl:publicationPlace", data, _NS)
    _extract_text(item, "dcterms:issued", data, _NS)
    _extract_text(item, "dc:date", data, _NS)
    _extract_text(item, "dc:extent", data, _NS)
    _extract_text(item, "dc:description", data, _NS)
    _extract_text(item, "dcndl:volume", data, _NS)
    _extract_text(item, "dcndl:seriesTitle", data, _NS)
    _extract_text(item, "dcndl:seriesTitleTranscription", data, _NS)
    _extract_text(item, "dcndl:price", data, _NS)

    # materialType — rdfs:label 속성에서 읽기
    mat_type_el = item.find("dcndl:materialType", _NS)
    if mat_type_el is not None:
        label = mat_type_el.get(f"{{{_NS['rdfs']}}}label", "")
        data["dcndl:materialType"] = label or mat_type_el.text

    # identifier 계열 — xsi:type 속성으로 구분
    for ident_el in item.findall("dc:identifier", _NS):
        xsi_type = ident_el.get(f"{{{_NS['xsi']}}}type", "")
        text = ident_el.text or ""
        if "NDLBibID" in xsi_type:
            data["dcndl:NDLBibID"] = text
        elif "JPNO" in xsi_type:
            data["dcndl:JPNO"] = text
        elif "ISBN" in xsi_type:
            data["dcndl:ISBN"] = text

    # subject — 분류와 자유어를 분리
    subject_list = []
    for subj_el in item.findall("dc:subject", _NS):
        xsi_type = subj_el.get(f"{{{_NS['xsi']}}}type", "")
        text = subj_el.text or ""
        if "NDLC" in xsi_type:
            data["dcndl:NDLC"] = text
        elif "NDC9" in xsi_type:
            data["dcndl:NDC9"] = text
        elif "NDC10" in xsi_type:
            data["dcndl:NDC10"] = text
        elif text:
            subject_list.append(text)
    if subject_list:
        data["dc:subject_list"] = subject_list

    # contributor 목록
    contributor_list = []
    for contrib_el in item.findall("dcterms:contributor", _NS):
        if contrib_el.text:
            contributor_list.append(contrib_el.text)
    if contributor_list:
        data["dcterms:contributor_list"] = contributor_list

    # seeAlso — rdf:resource 속성에서 URL 추출
    see_also_el = item.find("rdfs:seeAlso", _NS)
    if see_also_el is not None:
        data["rdfs:seeAlso"] = see_also_el.get(f"{{{_NS['rdf']}}}resource", "")

    # link (RSS 표준 필드)
    link_el = item.find("link")
    if link_el is not None and link_el.text:
        data["link"] = link_el.text

    return data


def _extract_text(
    parent: ET.Element,
    tag: str,
    data: dict,
    ns: dict,
) -> None:
    """XML 요소의 텍스트를 추출하여 dict에 저장한다. (유틸리티)"""
    el = parent.find(tag, ns)
    if el is not None and el.text:
        data[tag] = el.text


def _build_summary(raw: dict) -> str:
    """검색 결과 요약 문자열을 생성한다.

    왜 이렇게 하는가:
        GUI에서 검색 결과를 표시할 때, 제목·저자·발행년을
        한 줄로 보여주기 위해 사용한다.
    """
    parts = []
    if raw.get("dc:title"):
        parts.append(raw["dc:title"])
    if raw.get("dc:creator"):
        parts.append(f"/ {raw['dc:creator']}")
    if raw.get("dcterms:issued"):
        parts.append(f"({raw['dcterms:issued']})")
    if raw.get("dcndl:materialType"):
        parts.append(f"[{raw['dcndl:materialType']}]")
    return " ".join(parts) if parts else "(정보 없음)"


# --- 파서 등록 ---
# import 시 자동으로 레지스트리에 등록된다.
_fetcher = NdlFetcher()
_mapper = NdlMapper()
register_parser("ndl", _fetcher, _mapper)
