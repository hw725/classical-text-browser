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
from abc import ABC, abstractmethod
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


def get_registry_json() -> dict:
    """parsers/registry.json을 읽어 반환한다.

    왜 이렇게 하는가:
        GUI에서 파서 목록과 메타정보(국가, 접근방법 등)를 표시하기 위해 사용.
    """
    registry_path = Path(__file__).parent / "registry.json"
    if registry_path.exists():
        return json.loads(registry_path.read_text(encoding="utf-8"))
    return {"parsers": []}
