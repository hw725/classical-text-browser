"""범용 LLM 서지정보 파서 — markdown.new + LLM 추출.

platform-v7.md §7.3 아키텍처 확장:
    기존 전용 파서(NDL, 국립공문서관, KORCIS)가 없는 사이트에 대해
    markdown.new로 웹페이지를 마크다운으로 변환하고,
    LLM으로 서지 필드를 추출하는 범용 파서.

왜 이렇게 하는가:
    - 연구자가 사용하는 서지 DB는 수십 개에 달한다.
    - 각 사이트마다 전용 파서를 만드는 것은 비현실적이다.
    - markdown.new는 웹페이지를 깔끔한 마크다운으로 변환해 주므로,
      LLM이 HTML보다 훨씬 적은 토큰으로 구조를 파악할 수 있다.

지원 사이트 (전용 패턴 등록):
    - kokusho.nijl.ac.jp — 일본국문학연구자료관 (국서종합목록)
    - kostma.korea.ac.kr — 해외한국학자료센터
    - kostma.aks.ac.kr — 한국학자료센터
    - db.history.go.kr — 국사편찬위원회
    - db.itkc.or.kr — 한국고전번역원
    + 위 외에도 인식되지 않는 모든 http/https URL에 대해 폴백 작동.

사용법:
    from parsers.base import get_parser
    fetcher, mapper = get_parser("generic_llm")
    raw = await fetcher.fetch_by_url("https://db.itkc.or.kr/...")
    bib = mapper.map_to_bibliography(raw)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from parsers.base import BaseMapper, BaseFetcher, register_parser

logger = logging.getLogger(__name__)


# ── 마크다운 변환 서비스 설정 ──

# 1순위: markdown.new API 엔드포인트.
# GET https://markdown.new/api?url=<target> → 마크다운 텍스트 반환.
# Cloudflare Workers 기반. 무료.
_MARKDOWNER_API = "https://markdown.new/api"

# 2순위: Jina Reader (markdown.new 실패 시 폴백).
# GET https://r.jina.ai/<target> → 마크다운 텍스트 반환.
# JavaScript SPA도 렌더링 가능. 무료.
_JINA_READER_API = "https://r.jina.ai/"

# 요청 타임아웃 (초).
# 일부 대상 사이트가 느릴 수 있으므로 넉넉하게 설정.
_MARKDOWNER_TIMEOUT = 60.0


# ── LLM 서지 추출 프롬프트 ──

_SYSTEM_PROMPT = """\
당신은 동아시아 고전 문헌(한문, 한국 고서, 일본 고서)의 서지정보 전문가입니다.
웹페이지의 마크다운 텍스트를 받아 서지 필드를 정확하게 추출합니다.

반드시 아래 JSON 형식으로만 응답하세요. 설명이나 부연 없이 JSON만 출력합니다.
확인할 수 없는 필드는 null로 두세요. 추측하지 마세요.

```json
{
    "title": "문헌 제목 (원제, 한문 등 원본 표기 그대로)",
    "title_reading": "제목 읽기 (가나, 한글 독음 등)",
    "alternative_titles": ["별칭/약칭 등, 없으면 null"],
    "creator": {
        "name": "저자/편자/찬자 이름",
        "name_reading": "저자 이름 읽기",
        "role": "author/editor/compiler 중 하나",
        "period": "활동 시기 (예: 唐, 조선 중기)"
    },
    "contributors": [
        {
            "name": "기여자 이름 (주석자, 교정자 등)",
            "name_reading": "이름 읽기",
            "role": "annotator/editor/translator 등",
            "period": "활동 시기"
        }
    ],
    "date_created": "성립/간행 연도 (예: 1672, 唐代)",
    "edition_type": "판종 (예: 초간본, 필사본, 覆刻本, 和刻本)",
    "language": "사용 언어 (예: 한문, 일본어, 한국어)",
    "script": "문자 (예: 漢字, 한글+한문 혼용)",
    "physical_description": "형태사항 (크기, 장정, 권수책수 등)",
    "subject": ["주제어, 분류어 등"],
    "classification": {
        "call_number": "청구기호",
        "category": "분류 (사부분류 등)"
    },
    "series_title": "총서명/시리즈명",
    "material_type": "자료유형 (고서, 필사본, 인쇄본 등)",
    "repository": {
        "name": "소장처/소장 기관명 (원본 기관명)",
        "name_ko": "소장처 한국어명 (있으면)",
        "country": "소장 국가 (JP, KR, CN 등)",
        "call_number": "소장처 청구기호"
    },
    "platform_name": "웹사이트/DB 이름 (예: 한국고전번역원 DB, 국서종합목록)",
    "permanent_uri": "이 자료의 고유 URL (permalink, DOI 등)",
    "system_ids": {
        "키": "값 (예: ITKC ID, 관리번호 등)"
    },
    "license": "이용 조건/라이선스 (있으면)",
    "notes": "기타 중요 정보 (비고, 해제, 번역 원문 정보 등)"
}
```

특히 주의할 점:
- 한문 서명(書名)은 원문 그대로 유지 (예: 蒙求, 論語集注)
- 판식정보(版式情報)가 있으면 physical_description에 포함
- 여러 저자/기여자가 있으면 모두 포함
- 웹페이지에 없는 정보는 null로 두세요 — 절대로 추측하지 마세요
"""

_USER_PROMPT_TEMPLATE = """\
아래는 서지정보 웹페이지({url})를 마크다운으로 변환한 텍스트입니다.
이 페이지에서 서지 필드를 추출하여 JSON으로 반환해 주세요.

---
{markdown}
---
"""


# ── Fetcher ──


class GenericLlmFetcher(BaseFetcher):
    """markdown.new + LLM으로 임의의 서지 웹페이지에서 서지정보를 추출한다.

    처리 흐름:
        1. markdown.new API로 대상 URL의 웹페이지를 마크다운으로 변환
        2. LLM에 마크다운 + 서지 필드 목록을 보내 구조화된 JSON 추출
        3. 결과를 raw_data dict로 반환

    왜 이렇게 하는가:
        전용 파서가 없는 수십 개의 서지 DB를 하나의 파서로 커버한다.
        markdown.new가 HTML→마크다운 변환을 해 주므로, LLM은 깨끗한
        텍스트에서 서지 필드를 찾기만 하면 된다.
    """

    parser_id = "generic_llm"
    parser_name = "범용 LLM 추출 (markdown.new)"
    api_variant = "markdown_new_llm"

    def __init__(self):
        # LlmRouter는 첫 호출 시 lazy 초기화.
        # 왜 lazy인가: 파서 등록(import 시)에는 서고 경로가 아직 없다.
        # 실제 fetch_by_url 호출 시점에는 서버가 초기화된 상태.
        self._router = None

    def _get_router(self):
        """LlmRouter를 lazy 초기화한다.

        왜 이렇게 하는가:
            server.py의 _get_llm_router()와 동일한 패턴.
            파서 모듈 import 시점에는 서고 경로가 없으므로,
            실제 호출 시점에 초기화한다.
        """
        if self._router is None:
            # server.py가 이미 _library_path 기반으로 라우터를 만들었을 수 있으므로,
            # 가능하면 server의 라우터를 재사용한다.
            try:
                from app.server import _get_llm_router
                self._router = _get_llm_router()
            except Exception:
                # server.py 외부에서 사용할 때 (CLI, 테스트 등)
                from llm.config import LlmConfig
                from llm.router import LlmRouter
                self._router = LlmRouter(LlmConfig())
        return self._router

    async def fetch_by_url(self, url: str) -> dict[str, Any]:
        """URL에서 마크다운 변환 + LLM 서지 추출을 수행한다.

        입력:
            url — 서지정보가 있는 웹페이지 URL.
        출력:
            {
                "source_url": str,
                "markdown_text": str,
                "llm_extracted": dict,  # LLM이 추출한 서지 필드
                "extraction_model": str,  # 사용된 LLM 모델명
            }
        에러:
            - markdown.new 실패 → 직접 HTML 가져와서 간단 변환 시도
            - LLM 실패 → LlmUnavailableError 전파
        """
        # 1. 마크다운 변환
        markdown_text = await self._fetch_markdown(url)

        # 2. LLM 서지 필드 추출
        llm_result = await self._extract_with_llm(markdown_text, url)

        return {
            "source_url": url,
            "markdown_text": markdown_text,
            "llm_extracted": llm_result,
            "extraction_model": llm_result.get("_model", "unknown"),
        }

    async def _fetch_markdown(self, url: str) -> str:
        """웹페이지를 마크다운으로 변환한다.

        입력:
            url — 대상 웹페이지 URL.
        출력:
            마크다운 텍스트.

        폴백 순서:
            1. markdown.new API (사용자 지정 기본 서비스)
            2. Jina Reader (JavaScript SPA 렌더링 가능)
            3. 직접 HTTP GET + HTML 태그 제거 (최후 수단)

        왜 markdown.new를 쓰는가:
            - HTML을 깔끔한 마크다운으로 변환해 준다
            - JavaScript 렌더링도 처리 (Cloudflare Workers 기반)
            - LLM 토큰을 80% 이상 절약
        """
        # ── 1순위: markdown.new ──
        try:
            markdown = await self._try_markdowner(url)
            if markdown:
                return markdown
        except Exception as e:
            logger.warning(f"markdown.new 실패: {e}")

        # ── 2순위: Jina Reader ──
        try:
            markdown = await self._try_jina_reader(url)
            if markdown:
                return markdown
        except Exception as e:
            logger.warning(f"Jina Reader 실패: {e}")

        # ── 3순위: 직접 HTTP + 태그 제거 ──
        return await self._fetch_html_fallback(url)

    async def _try_markdowner(self, url: str) -> str | None:
        """markdown.new API로 웹페이지를 마크다운으로 변환한다.

        왜 이렇게 하는가:
            사용자가 지정한 기본 마크다운 변환 서비스.
            GET https://markdown.new/api?url=<target>

        출력:
            마크다운 텍스트. 실패 시 None.
        """
        encoded_url = quote(url, safe="")
        api_url = f"{_MARKDOWNER_API}?url={encoded_url}"

        async with httpx.AsyncClient(timeout=_MARKDOWNER_TIMEOUT) as client:
            response = await client.get(api_url)
            response.raise_for_status()

        markdown = response.text.strip()

        if not markdown or len(markdown) < 50:
            logger.warning(
                f"markdown.new 응답이 너무 짧습니다 ({len(markdown)}자)."
            )
            return None

        logger.info(f"markdown.new 변환 완료: {url} → {len(markdown)}자")
        return markdown

    async def _try_jina_reader(self, url: str) -> str | None:
        """Jina Reader로 웹페이지를 마크다운으로 변환한다.

        왜 이렇게 하는가:
            markdown.new가 실패하거나 SPA를 처리하지 못할 때의 폴백.
            Jina Reader는 JavaScript 렌더링을 지원하므로
            SPA 기반 서지 DB(ITKC, NIJL 등)도 처리 가능.
            GET https://r.jina.ai/<target>
        """
        api_url = f"{_JINA_READER_API}{url}"

        async with httpx.AsyncClient(timeout=_MARKDOWNER_TIMEOUT) as client:
            response = await client.get(api_url)
            response.raise_for_status()

        markdown = response.text.strip()

        if not markdown or len(markdown) < 50:
            logger.warning(
                f"Jina Reader 응답이 너무 짧습니다 ({len(markdown)}자)."
            )
            return None

        logger.info(f"Jina Reader 변환 완료: {url} → {len(markdown)}자")
        return markdown

    async def _fetch_html_fallback(self, url: str) -> str:
        """markdown.new 실패 시 직접 HTML을 가져와 간단 변환한다.

        왜 이렇게 하는가:
            markdown.new가 일시적으로 다운되거나 대상 사이트를 처리하지
            못할 수 있다. 직접 가져온 HTML에서 최소한의 텍스트라도
            추출하면 LLM이 서지 필드를 찾을 가능성이 있다.
        """
        import re as _re

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; ClassicalTextPlatform/1.0; "
                        "+https://github.com/hw725/classical-text-platform)"
                    ),
                },
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

            html = response.text

            # 간단한 HTML → 텍스트 변환 (정교하지 않지만 없는 것보다 낫다)
            # 스크립트/스타일 제거
            html = _re.sub(r"<script[^>]*>.*?</script>", "", html, flags=_re.DOTALL)
            html = _re.sub(r"<style[^>]*>.*?</style>", "", html, flags=_re.DOTALL)
            # 태그 제거
            text = _re.sub(r"<[^>]+>", " ", html)
            # 연속 공백 정리
            text = _re.sub(r"\s+", " ", text).strip()

            # 너무 길면 자르기 (LLM 토큰 절약)
            if len(text) > 15000:
                text = text[:15000] + "\n\n[... 이하 생략 ...]"

            logger.info(
                f"HTML 직접 가져오기 완료: {url} → {len(text)}자"
            )
            return text

        except Exception as e:
            raise RuntimeError(
                f"웹페이지를 가져올 수 없습니다: {url}\n"
                f"원인: {e}\n"
                f"확인: 네트워크 연결과 URL이 올바른지 확인하세요."
            ) from e

    async def _extract_with_llm(self, markdown: str, url: str) -> dict:
        """LLM으로 마크다운에서 서지 필드를 추출한다.

        입력:
            markdown — 웹페이지의 마크다운 텍스트.
            url — 원본 URL (프롬프트에 포함하여 LLM이 사이트를 식별하도록).
        출력:
            LLM이 추출한 서지 필드 dict.
            _provider, _model 키가 자동으로 추가된다.

        왜 이렇게 하는가:
            LLM은 마크다운의 테이블, 헤딩, 리스트 구조를 보고
            서지 필드를 높은 정확도로 추출할 수 있다.
            프롬프트에 출력 형식을 JSON으로 고정하여 파싱 가능성을 높인다.
        """
        router = self._get_router()

        # 마크다운이 너무 길면 자르기 (LLM 컨텍스트 절약)
        max_markdown_len = 12000
        if len(markdown) > max_markdown_len:
            markdown = markdown[:max_markdown_len] + "\n\n[... 이하 생략 ...]"

        user_prompt = _USER_PROMPT_TEMPLATE.format(url=url, markdown=markdown)

        # base44_http(agent-chat)는 MCP 도구 기반이라 자유 형식 텍스트 요청을
        # 처리할 수 없으므로 건너뛴다 (server.py의 _call_llm_text와 동일한 패턴).
        _SKIP_FOR_TEXT = {"base44_http"}

        errors = []
        for provider in router.providers:
            if provider.provider_id in _SKIP_FOR_TEXT:
                continue

            try:
                if not await provider.is_available():
                    continue

                response = await provider.call(
                    user_prompt,
                    system=_SYSTEM_PROMPT,
                    response_format="text",
                    max_tokens=4096,
                    purpose="bibliography_extraction",
                )
                router.usage_tracker.log(response, purpose="bibliography_extraction")

                # JSON 파싱
                result = self._parse_llm_json(response.text)
                result["_provider"] = response.provider
                result["_model"] = response.model
                return result

            except Exception as e:
                logger.info(
                    f"LLM 서지추출 — {provider.provider_id} 실패: {e}, "
                    f"다음 프로바이더로 시도"
                )
                errors.append(f"{provider.provider_id}: {e}")
                continue

        raise ValueError(
            f"모든 LLM 프로바이더가 서지 추출에 실패했습니다:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    @staticmethod
    def _parse_llm_json(raw_text: str) -> dict:
        """LLM 응답에서 JSON을 추출한다.

        왜 별도 메서드인가:
            server.py의 _parse_llm_json()과 동일한 로직.
            LLM이 마크다운 코드블록으로 감싸거나 부연 설명을 붙일 수 있으므로,
            여러 전략으로 JSON을 추출한다.
        """
        raw = raw_text.strip()

        # markdown 코드 블록 제거
        if "```" in raw:
            parts = raw.split("```")
            if len(parts) >= 3:
                raw = parts[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # JSON 부분만 추출 시도
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end])
            except json.JSONDecodeError:
                pass

        raise ValueError(f"LLM 응답에서 JSON을 추출할 수 없습니다: {raw[:300]}")

    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        """범용 LLM 파서는 키워드 검색을 지원하지 않는다.

        왜:
            이 파서는 이미 특정 페이지 URL이 주어졌을 때만 동작한다.
            임의의 사이트에서 키워드 검색 API를 호출할 수는 없다.
        """
        raise NotImplementedError(
            "범용 LLM 파서는 검색을 지원하지 않습니다.\n"
            "URL을 직접 붙여넣기하여 서지정보를 가져오세요."
        )

    async def fetch_detail(self, item_id: str, **kwargs) -> dict[str, Any]:
        """범용 LLM 파서는 ID로 상세 조회를 지원하지 않는다.

        왜:
            item_id 형식이 사이트마다 다르므로 범용적으로 처리할 수 없다.
        """
        raise NotImplementedError(
            "범용 LLM 파서는 ID 검색을 지원하지 않습니다.\n"
            "URL을 직접 붙여넣기하여 서지정보를 가져오세요."
        )


# ── Mapper ──


class GenericLlmMapper(BaseMapper):
    """LLM이 추출한 서지 필드를 bibliography.json 공통 스키마로 매핑한다.

    왜 Mapper가 필요한가:
        LLM이 직접 bibliography 형식에 가까운 JSON을 반환하지만,
        raw_metadata, _mapping_info 등 메타 필드를 추가하고,
        필드명을 정확히 맞추는 정리 작업이 필요하다.
    """

    parser_id = "generic_llm"

    def map_to_bibliography(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """LLM 추출 결과를 bibliography.json 형식으로 변환한다.

        입력:
            raw_data — GenericLlmFetcher.fetch_by_url()이 반환한 dict.
                {source_url, markdown_text, llm_extracted, extraction_model}
        출력:
            bibliography.schema.json 준수 dict.
        """
        ext = raw_data.get("llm_extracted", {})

        # creator 필드 정규화: LLM이 문자열로 반환할 수 있으므로 dict로 변환
        creator = ext.get("creator")
        if isinstance(creator, str):
            creator = {"name": creator, "name_reading": None, "role": "author", "period": None}

        # contributors 정규화
        contributors = ext.get("contributors")
        if isinstance(contributors, list):
            normalized = []
            for c in contributors:
                if isinstance(c, str):
                    normalized.append({
                        "name": c, "name_reading": None,
                        "role": None, "period": None,
                    })
                elif isinstance(c, dict):
                    normalized.append(c)
            contributors = normalized if normalized else None
        else:
            contributors = None

        # classification 정규화
        classification = ext.get("classification")
        if isinstance(classification, str):
            classification = {"category": classification}

        # repository 정규화
        repository = ext.get("repository")
        if isinstance(repository, str):
            repository = {"name": repository, "name_ko": None, "country": None, "call_number": None}

        # system_ids 정규화
        system_ids = ext.get("system_ids")
        if not system_ids or not isinstance(system_ids, dict):
            system_ids = None

        # subject 정규화
        subject = ext.get("subject")
        if isinstance(subject, str):
            subject = [subject]
        elif isinstance(subject, list):
            subject = subject if subject else None
        else:
            subject = None

        # alternative_titles 정규화
        alt_titles = ext.get("alternative_titles")
        if isinstance(alt_titles, str):
            alt_titles = [alt_titles]
        elif isinstance(alt_titles, list):
            alt_titles = alt_titles if alt_titles else None
        else:
            alt_titles = None

        bibliography = {
            "title": ext.get("title"),
            "title_reading": ext.get("title_reading"),
            "alternative_titles": alt_titles,
            "creator": creator,
            "contributors": contributors,
            "date_created": ext.get("date_created"),
            "edition_type": ext.get("edition_type"),
            "language": ext.get("language"),
            "script": ext.get("script"),
            "physical_description": ext.get("physical_description"),
            "subject": subject,
            "classification": classification,
            "series_title": ext.get("series_title"),
            "material_type": ext.get("material_type"),
            "repository": repository,
            "digital_source": {
                "platform": ext.get("platform_name", "Unknown"),
                "source_url": raw_data.get("source_url"),
                "permanent_uri": ext.get("permanent_uri"),
                "system_ids": system_ids,
                "license": ext.get("license"),
                "accessed_at": datetime.now(timezone.utc).isoformat(),
            },
            "raw_metadata": {
                "source_system": "generic_llm",
                "source_url": raw_data.get("source_url"),
                "markdown_text": raw_data.get("markdown_text"),
                "llm_extracted": ext,
                "extraction_model": raw_data.get("extraction_model"),
            },
            "_mapping_info": self._make_mapping_info(
                field_sources={
                    "title": self._field_source(
                        "llm_extraction", "inferred",
                        "LLM이 마크다운에서 추출. 정확도는 사이트에 따라 다를 수 있음."
                    ),
                    "creator": self._field_source(
                        "llm_extraction", "inferred",
                        "LLM이 마크다운에서 추출."
                    ),
                    "date_created": self._field_source(
                        "llm_extraction", "inferred",
                        "LLM이 마크다운에서 추출."
                    ),
                    "repository": self._field_source(
                        "llm_extraction", "inferred",
                        "LLM이 마크다운에서 추출."
                    ),
                },
                api_variant="markdown_new_llm",
            ),
            "notes": ext.get("notes"),
        }

        return bibliography


# ── 파서 등록 ──
# import 시 자동으로 레지스트리에 등록된다.

_fetcher = GenericLlmFetcher()
_mapper = GenericLlmMapper()
register_parser("generic_llm", _fetcher, _mapper)
