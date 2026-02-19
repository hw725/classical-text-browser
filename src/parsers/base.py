"""서지정보 파서 프레임워크 — BaseFetcher, BaseMapper, 파서 레지스트리.

platform-v7.md §7.3 아키텍처:
    [소스 API/HTML] → Fetcher(추출) → Mapper(매핑) → bibliography.json

각 소스(NDL, 국립공문서관 등)는 이 두 추상 클래스를 구현한다.
새 소스 추가 시 기존 코드를 수정하지 않고, fetcher + mapper 쌍만 등록하면 된다.

왜 이렇게 하는가:
    - 각 소스의 메타데이터 구조가 근본적으로 다르다 (MARC, DC-NDL, 커스텀 HTML).
    - Fetcher/Mapper를 분리하면 같은 소스의 다른 API 변형도 수용할 수 있다.
    - raw_metadata는 건드리지 않고, 매핑 판단을 _mapping_info에 기록한다.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BaseFetcher(ABC):
    """소스에서 원본 메타데이터를 추출하는 추상 클래스.

    각 소스(NDL, Archives 등)마다 하나의 Fetcher를 구현한다.
    Fetcher는 API 호출 또는 HTML 파싱을 담당하며,
    결과를 소스 고유 형태(dict)로 반환한다.
    """

    parser_id: str = ""       # 파서 식별자 (예: "ndl", "japan_national_archives")
    parser_name: str = ""     # 사람이 읽는 파서 이름
    api_variant: str = ""     # 사용된 API 변형 (예: "opensearch", "sru")

    @abstractmethod
    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        """키워드로 검색하여 후보 목록을 반환한다.

        입력:
            query — 검색어 (예: "蒙求").
            **kwargs — 소스별 추가 파라미터 (예: cnt, mediatype).
        출력:
            검색 결과 목록. 각 항목은 소스 고유 형태의 dict.
            [{title: ..., raw: {...}}, ...]

        왜 이렇게 하는가:
            검색 결과가 여러 건일 수 있으므로, 사용자가 올바른 항목을
            선택할 수 있도록 후보 목록을 반환한다.
        """

    @abstractmethod
    async def fetch_detail(self, item_id: str, **kwargs) -> dict[str, Any]:
        """특정 항목의 상세 메타데이터를 가져온다.

        입력:
            item_id — 소스 시스템의 고유 식별자.
        출력:
            소스 고유 형태의 상세 메타데이터 dict.

        왜 이렇게 하는가:
            검색 결과 목록에는 요약 정보만 있을 수 있으므로,
            선택된 항목의 전체 메타데이터를 별도로 가져온다.
            (NDL OpenSearch는 검색 결과에 전체 필드를 포함하므로,
             이 경우 search 결과를 그대로 반환할 수 있다.)
        """

    # --- 에셋 다운로드 인터페이스 (선택 구현) ---

    supports_asset_download: bool = False
    """이 Fetcher가 이미지/PDF 다운로드를 지원하는지 여부.

    왜 이렇게 하는가:
        모든 소스가 이미지 다운로드를 지원하지는 않는다.
        KORCIS는 메타데이터 전용이고, NDL은 IIIF를 지원하나 아직 미구현.
        이 플래그로 GUI에서 "문헌 생성" 버튼을 조건부 표시한다.
    """

    async def list_assets(self, raw_data: dict[str, Any]) -> list[dict[str, Any]]:
        """다운로드 가능한 에셋(이미지/PDF) 목록을 반환한다.

        입력:
            raw_data — fetch_detail/fetch_by_url이 반환한 메타데이터.
                       BID, MID 등 소스별 ID가 포함되어 있다.
        출력:
            [{
                "asset_id": "M2023...",          # 소스 시스템 ID
                "label": "蒙求1",                 # 사람이 읽는 이름
                "page_count": 42,                 # 페이지 수 (알면)
                "file_size": 12345678,            # 바이트 (알면)
                "download_type": "jpeg_pages",    # jpeg_pages | pdf | iiif
            }, ...]

        왜 이렇게 하는가:
            다권본(簿冊)은 하위에 여러 MID가 있다.
            사용자에게 어떤 권을 다운로드할지 보여주기 위해
            먼저 목록을 조회한다.
        """
        return []

    async def download_asset(
        self,
        asset_info: dict[str, Any],
        dest_dir: Path,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> Path:
        """에셋을 다운로드하여 dest_dir에 저장한다.

        입력:
            asset_info — list_assets()가 반환한 항목 하나.
            dest_dir — 파일을 저장할 디렉토리 (임시 디렉토리).
            progress_callback — (current_page, total_pages)를 받는 콜백.
        출력:
            다운로드된 파일의 Path (PDF 등).

        왜 이렇게 하는가:
            소스마다 다운로드 방식이 다르다.
            국립공문서관은 개별 JPEG를 받아 PDF로 합치고,
            NDL은 IIIF manifest에서 이미지를 받을 수 있다.
        """
        raise NotImplementedError(
            f"이 파서({self.parser_id})는 에셋 다운로드를 지원하지 않습니다."
        )


class BaseMapper(ABC):
    """소스별 메타데이터를 bibliography.json 공통 스키마로 매핑하는 추상 클래스.

    매핑 원칙 (platform-v7.md §7.3.3):
        1. 모든 공통 필드는 null 허용 — 채울 수 없으면 비워둔다.
        2. raw_metadata는 건드리지 않는다 — 원본 데이터 그대로 보존.
        3. 매핑 판단은 기록한다 — _mapping_info.field_sources에 출처와 신뢰도.
        4. 파서는 플러그인이다 — 새 소스 추가 시 기존 코드 수정 없음.
    """

    parser_id: str = ""

    @abstractmethod
    def map_to_bibliography(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """소스 데이터를 bibliography.json 형식으로 매핑한다.

        입력:
            raw_data — Fetcher가 반환한 소스 고유 형태의 dict.
        출력:
            bibliography.schema.json 준수 dict.
            raw_metadata와 _mapping_info가 포함되어야 한다.

        왜 이렇게 하는가:
            각 소스의 필드명과 구조가 다르므로, 이 함수에서
            공통 스키마로 변환하고, 매핑 판단(출처/신뢰도)을 기록한다.
        """

    def _make_mapping_info(
        self,
        field_sources: dict[str, dict],
        api_variant: str | None = None,
    ) -> dict:
        """_mapping_info 블록을 생성한다. (공통 유틸리티)

        왜 이렇게 하는가:
            매핑 결과의 투명성을 위해, 각 필드가 어디서 왔는지,
            매핑 신뢰도는 어떤지 기록한다.
        """
        return {
            "parser_id": self.parser_id,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "api_variant": api_variant,
            "field_sources": field_sources,
        }

    def _field_source(
        self,
        source_field: str | None,
        confidence: str | None = "exact",
        note: str | None = None,
    ) -> dict:
        """개별 필드의 매핑 출처를 생성한다. (공통 유틸리티)

        confidence 값:
            "exact" — 1:1 대응
            "inferred" — 추론으로 추출
            "partial" — 부분 매핑
            None — 소스에 해당 필드 없음
        """
        return {
            "source_field": source_field,
            "confidence": confidence,
            "note": note,
        }


# --- 파서 레지스트리 ---


# 등록된 파서 인스턴스를 보관한다. {parser_id: (fetcher, mapper)}
_PARSER_REGISTRY: dict[str, tuple[BaseFetcher, BaseMapper]] = {}


def register_parser(parser_id: str, fetcher: BaseFetcher, mapper: BaseMapper) -> None:
    """파서를 레지스트리에 등록한다.

    왜 이렇게 하는가:
        파서를 플러그인으로 관리하기 위해,
        import 시 자동으로 레지스트리에 등록되도록 한다.
    """
    _PARSER_REGISTRY[parser_id] = (fetcher, mapper)


def get_parser(parser_id: str) -> tuple[BaseFetcher, BaseMapper]:
    """레지스트리에서 파서를 가져온다.

    Raises:
        KeyError: 등록되지 않은 parser_id.
    """
    if parser_id not in _PARSER_REGISTRY:
        available = list(_PARSER_REGISTRY.keys())
        raise KeyError(
            f"등록되지 않은 파서입니다: '{parser_id}'\n"
            f"→ 사용 가능한 파서: {available}"
        )
    return _PARSER_REGISTRY[parser_id]


def list_parsers() -> list[dict[str, str]]:
    """등록된 파서 목록을 반환한다.

    출력: [{id, name, api_variant}, ...]
    """
    result = []
    for pid, (fetcher, _mapper) in _PARSER_REGISTRY.items():
        result.append({
            "id": pid,
            "name": fetcher.parser_name,
            "api_variant": fetcher.api_variant,
        })
    return result


# --- URL 자동 판별 ---


# URL 패턴 → parser_id 매핑 테이블.
# 각 항목은 (정규식 패턴, parser_id) 쌍이다.
# 왜 이렇게 하는가:
#     연구자가 URL을 붙여넣으면, 어느 소스인지 자동으로 판별하여
#     올바른 fetcher를 호출할 수 있다.
_URL_PATTERNS: list[tuple[re.Pattern, str]] = [
    # NDL (国立国会図書館): 여러 하위 도메인을 포괄
    (re.compile(r"https?://ndlsearch\.ndl\.go\.jp/"), "ndl"),
    (re.compile(r"https?://dl\.ndl\.go\.jp/"), "ndl"),
    (re.compile(r"https?://id\.ndl\.go\.jp/"), "ndl"),
    # 일본 국립공문서관 デジタルアーカイブ
    (re.compile(r"https?://(www\.)?digital\.archives\.go\.jp/"), "japan_national_archives"),
    # KORCIS (한국고문헌종합목록) — 국립중앙도서관 내
    (re.compile(r"https?://(www\.)?nl\.go\.kr/korcis/"), "korcis"),
    # ── 범용 LLM 파서 대상 사이트 ──
    # 전용 파서 없이 markdown.new + LLM으로 서지정보를 추출한다.
    # 일본국문학연구자료관 (국서종합목록)
    (re.compile(r"https?://(www\.)?kokusho\.nijl\.ac\.jp/"), "generic_llm"),
    # 해외한국학자료센터 (고려대)
    (re.compile(r"https?://kostma\.korea\.ac\.kr/"), "generic_llm"),
    # 한국학자료센터 (한국학중앙연구원)
    (re.compile(r"https?://kostma\.aks\.ac\.kr/"), "generic_llm"),
    # 국사편찬위원회 한국사데이터베이스
    (re.compile(r"https?://db\.history\.go\.kr/"), "generic_llm"),
    # 한국고전번역원 한국고전종합DB
    (re.compile(r"https?://db\.itkc\.or\.kr/"), "generic_llm"),
]


def detect_parser_from_url(url: str) -> str | None:
    """URL 패턴으로 어느 파서를 쓸지 자동 판별한다.

    입력:
        url — 외부 서지정보 페이지 URL.
    출력:
        parser_id 문자열, 또는 인식할 수 없으면 None.

    매칭 규칙:
        1순위 — 전용 파서:
            - ndlsearch.ndl.go.jp, dl.ndl.go.jp, id.ndl.go.jp → "ndl"
            - digital.archives.go.jp → "japan_national_archives"
            - nl.go.kr/korcis/ → "korcis"
        2순위 — 범용 LLM 파서 (등록된 사이트):
            - kokusho.nijl.ac.jp, kostma.korea.ac.kr, kostma.aks.ac.kr,
              db.history.go.kr, db.itkc.or.kr → "generic_llm"
        3순위 — 폴백:
            - http/https로 시작하는 모든 URL → "generic_llm"

    왜 이렇게 하는가:
        연구자가 URL을 붙여넣기만 하면 검색 없이 서지정보를
        바로 가져올 수 있도록 하기 위해서다.
        전용 파서가 없는 사이트도 markdown.new + LLM으로 추출을 시도한다.
    """
    for pattern, parser_id in _URL_PATTERNS:
        if pattern.search(url):
            return parser_id

    # 폴백: 전용 패턴에 없는 http/https URL은 범용 LLM 파서로 시도.
    # 왜 이렇게 하는가:
    #     연구자가 사용하는 서지 DB는 수십 개에 달한다.
    #     모든 사이트에 전용 파서를 만들 수 없으므로,
    #     LLM으로 서지 필드를 추출하는 범용 폴백을 제공한다.
    if url.startswith(("http://", "https://")):
        return "generic_llm"

    return None


def get_supported_sources() -> list[dict[str, str]]:
    """URL 자동 판별이 지원하는 소스 목록을 반환한다.

    출력: [{parser_id, url_example, description}, ...]

    왜 generic_llm 항목도 포함하는가:
        연구자에게 "이 사이트도 URL 붙여넣기로 가져올 수 있다"는 것을
        알려주기 위해서. 전용 파서보다 정확도가 낮을 수 있지만 동작은 한다.
    """
    return [
        # ── 전용 파서 (높은 정확도) ──
        {
            "parser_id": "ndl",
            "url_example": "https://ndlsearch.ndl.go.jp/books/R...",
            "description": "国立国会図書館サーチ (NDL Search)",
        },
        {
            "parser_id": "japan_national_archives",
            "url_example": "https://www.digital.archives.go.jp/...",
            "description": "国立公文書館デジタルアーカイブ",
        },
        {
            "parser_id": "korcis",
            "url_example": "https://www.nl.go.kr/korcis/...",
            "description": "한국고문헌종합목록 (KORCIS)",
        },
        # ── 범용 LLM 추출 (markdown.new + LLM) ──
        {
            "parser_id": "generic_llm",
            "url_example": "https://kokusho.nijl.ac.jp/...",
            "description": "일본국문학연구자료관 (국서종합목록)",
        },
        {
            "parser_id": "generic_llm",
            "url_example": "https://kostma.korea.ac.kr/...",
            "description": "해외한국학자료센터",
        },
        {
            "parser_id": "generic_llm",
            "url_example": "https://kostma.aks.ac.kr/...",
            "description": "한국학자료센터",
        },
        {
            "parser_id": "generic_llm",
            "url_example": "https://db.history.go.kr/...",
            "description": "국사편찬위원회 한국사데이터베이스",
        },
        {
            "parser_id": "generic_llm",
            "url_example": "https://db.itkc.or.kr/...",
            "description": "한국고전번역원 한국고전종합DB",
        },
        {
            "parser_id": "generic_llm",
            "url_example": "https://example.com/catalog/...",
            "description": "기타 URL (LLM 자동 추출 — 정확도 낮을 수 있음)",
        },
    ]


def get_registry_json() -> dict:
    """parsers/registry.json을 읽어 반환한다.

    왜 이렇게 하는가:
        GUI에서 파서 목록과 메타정보(국가, 접근방법 등)를 표시하기 위해 사용.
    """
    registry_path = Path(__file__).parent / "registry.json"
    if registry_path.exists():
        return json.loads(registry_path.read_text(encoding="utf-8"))
    return {"parsers": []}
