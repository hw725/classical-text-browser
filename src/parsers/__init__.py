"""서지정보 파서 패키지.

파서 아키텍처 (platform-v7.md §7.3):
    각 소스(NDL, 국립공문서관 등)마다 Fetcher + Mapper 쌍을 구현한다.
    이 패키지를 import하면 등록된 파서들이 자동으로 레지스트리에 등록된다.

사용법:
    from parsers.base import get_parser, list_parsers
    fetcher, mapper = get_parser("ndl")
    results = await fetcher.search("蒙求")
    bibliography = mapper.map_to_bibliography(results[0]["raw"])
"""

# 파서 모듈을 import하면 register_parser()가 호출되어 자동 등록된다.
from parsers import ndl  # noqa: F401
from parsers import archives_jp  # noqa: F401
from parsers import korcis  # noqa: F401
from parsers import generic_llm  # noqa: F401  — markdown.new + LLM 범용 파서
