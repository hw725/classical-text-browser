"""LLM 기반 원문/번역/주석 분리기.

혼합 텍스트(원문+번역+주석이 섞인 PDF 등)에서
한문 원문만 추출하는 LLM 파이프라인.

왜 LLM인가:
  - 문서마다 원문/번역 배치 패턴이 다르다
  - 각주 번호, 번역 번호, 서명호 등 형식 단서가 다양하다
  - 규칙 기반은 새 형식마다 파서를 추가해야 하므로 비현실적
  - LLM은 첫 1~2페이지 예시만 보면 패턴을 학습한다

사용법:
    separator = TextSeparator(llm_router)
    structure = await separator.analyze_structure(sample_pages)
    result = await separator.separate_page(page_text, structure)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DocumentStructure:
    """문서 구조 분석 결과.

    LLM이 첫 몇 페이지를 보고 파악한 문서 내부의
    원문/번역/주석 배치 패턴.
    """
    pattern_type: str = "unknown"
    # "alternating" — 원문→번역 교차
    # "block" — 앞부분 원문, 뒷부분 번역
    # "interlinear" — 줄 단위 교차
    # "mixed" — 혼합 (원문+각주+번역)
    # "original_only" — 원문만 (분리 불필요)

    original_markers: str = ""     # 원문 식별 단서 (LLM이 서술)
    translation_markers: str = ""  # 번역 식별 단서
    note_markers: str = ""         # 주석 식별 단서
    special_instructions: str = "" # 추가 특수 지시 (예: "판본 목록도 원문에 포함")
    confidence: float = 0.0        # 구조 파악 확신도 (0.0 ~ 1.0)

    def to_dict(self) -> dict:
        """딕셔너리로 변환 (JSON 직렬화용)."""
        return {
            "pattern_type": self.pattern_type,
            "original_markers": self.original_markers,
            "translation_markers": self.translation_markers,
            "note_markers": self.note_markers,
            "special_instructions": self.special_instructions,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DocumentStructure:
        """딕셔너리에서 생성."""
        return cls(
            pattern_type=d.get("pattern_type", "unknown"),
            original_markers=d.get("original_markers", ""),
            translation_markers=d.get("translation_markers", ""),
            note_markers=d.get("note_markers", ""),
            special_instructions=d.get("special_instructions", ""),
            confidence=d.get("confidence", 0.0),
        )


@dataclass
class SeparationResult:
    """한 페이지의 텍스트 분리 결과."""
    page_num: int = 0
    original_text: str = ""      # 원문만 추출
    translation_text: str = ""   # 번역만 추출
    notes: list[str] = field(default_factory=list)  # 주석/각주
    uncertain: list[str] = field(default_factory=list)  # 분류 불확실한 부분

    def to_dict(self) -> dict:
        return {
            "page_num": self.page_num,
            "original_text": self.original_text,
            "translation_text": self.translation_text,
            "notes": self.notes,
            "uncertain": self.uncertain,
        }


# ─── 프롬프트 템플릿 ────────────────────────────────

_STRUCTURE_ANALYSIS_PROMPT = """\
다음은 학술 문헌 PDF에서 추출한 텍스트의 처음 몇 페이지입니다.
이 문서에서 한문 원문(漢文原文), 번역(飜譯), 주석(註釋/各註)이
어떤 패턴으로 배치되어 있는지 분석하세요.

{pages_text}

---

다음 JSON 형식으로 답하세요:
{{
  "pattern_type": "alternating" | "block" | "interlinear" | "mixed" | "original_only",
  "original_markers": "원문을 식별하는 단서 설명 (예: '번호 없는 한문 단락')",
  "translation_markers": "번역을 식별하는 단서 설명 (예: '아라비아 숫자로 시작하는 한국어')",
  "note_markers": "주석을 식별하는 단서 설명 (예: '1) 2) 각주 번호 뒤에 오는 설명')",
  "confidence": 0.0~1.0
}}

pattern_type 설명:
- "alternating": 원문 단락 → 번역 단락이 교차 반복
- "block": 전반부가 원문, 후반부가 번역 (또는 그 반대)
- "interlinear": 원문 한 줄 → 번역 한 줄이 줄 단위로 교차
- "mixed": 원문+각주+번역이 복합적으로 섞임
- "original_only": 원문만 있음 (번역 없음)

JSON만 출력하세요. 다른 텍스트는 포함하지 마세요.
"""

_SEPARATION_PROMPT = """\
다음은 학술 문헌 PDF의 한 페이지 텍스트입니다.
이 문서의 구조: {structure_description}

{custom_instructions}

이 페이지 텍스트에서 한문 원문(漢文原文)만 추출하세요.
번역(한국어/일본어/영어), 주석, 각주 번호, 페이지 번호는 제외하세요.

=== 페이지 텍스트 ===
{page_text}

=== 출력 형식 (JSON) ===
{{
  "original_text": "추출한 한문 원문 (줄바꿈 유지)",
  "translation_text": "추출한 번역 텍스트",
  "notes": ["주석1", "주석2", ...],
  "uncertain": ["분류 불확실한 부분1", ...]
}}

JSON만 출력하세요.
"""


class TextSeparator:
    """혼합 텍스트에서 원문/번역/주석을 LLM으로 분리한다."""

    def __init__(self, llm_router):
        """분리기 초기화.

        입력: llm_router — src/llm/router.py의 LlmRouter 인스턴스
        """
        self._router = llm_router

    async def analyze_structure(
        self,
        sample_pages: list[dict],
        force_provider: str | None = None,
        force_model: str | None = None,
    ) -> DocumentStructure:
        """첫 2~3페이지를 분석하여 문서 구조를 파악한다.

        입력:
            sample_pages — [{page_num, text}, ...] 첫 2~3페이지
            force_provider — 특정 프로바이더 강제 지정
            force_model — 특정 모델 강제 지정
        출력: DocumentStructure
        """
        # 페이지 텍스트를 하나로 합치기
        pages_text = ""
        for p in sample_pages:
            pages_text += f"\n--- 페이지 {p['page_num']} ---\n{p['text']}\n"

        prompt = _STRUCTURE_ANALYSIS_PROMPT.format(pages_text=pages_text)

        response = await self._router.call(
            prompt=prompt,
            system="당신은 동아시아 고전 문헌 전문가입니다. 한문 원문과 번역/주석의 구조를 분석합니다.",
            purpose="text_structure_analysis",
            force_provider=force_provider,
            force_model=force_model,
        )

        # JSON 파싱
        try:
            data = _parse_json_response(response.text)
            structure = DocumentStructure.from_dict(data)
            logger.info(
                "문서 구조 분석 완료: pattern=%s, confidence=%.2f",
                structure.pattern_type,
                structure.confidence,
            )
            return structure
        except Exception as e:
            logger.warning("구조 분석 JSON 파싱 실패: %s, 원본 응답: %s", e, response.text[:200])
            return DocumentStructure(
                pattern_type="unknown",
                original_markers=response.text[:500],
                confidence=0.0,
            )

    async def separate_page(
        self,
        page_text: str,
        structure: DocumentStructure,
        page_num: int = 0,
        custom_instructions: str = "",
        force_provider: str | None = None,
        force_model: str | None = None,
    ) -> SeparationResult:
        """한 페이지의 텍스트를 원문/번역/주석으로 분리한다.

        입력:
            page_text — 페이지 전체 텍스트
            structure — analyze_structure()의 결과
            page_num — 페이지 번호 (결과에 포함)
            custom_instructions — 사용자 추가 지시
            force_provider — 특정 프로바이더 강제 지정
            force_model — 특정 모델 강제 지정
        출력: SeparationResult
        """
        # 구조 설명 조합
        structure_desc = (
            f"패턴: {structure.pattern_type}, "
            f"원문 특징: {structure.original_markers}, "
            f"번역 특징: {structure.translation_markers}"
        )
        if structure.note_markers:
            structure_desc += f", 주석 특징: {structure.note_markers}"

        custom = ""
        if custom_instructions:
            custom = f"추가 지시: {custom_instructions}"
        if structure.special_instructions:
            custom += f"\n특수 규칙: {structure.special_instructions}"

        prompt = _SEPARATION_PROMPT.format(
            structure_description=structure_desc,
            custom_instructions=custom,
            page_text=page_text,
        )

        response = await self._router.call(
            prompt=prompt,
            system="당신은 동아시아 고전 문헌 전문가입니다. 텍스트에서 한문 원문만 정확하게 추출합니다.",
            purpose="text_separation",
            force_provider=force_provider,
            force_model=force_model,
        )

        # JSON 파싱
        try:
            data = _parse_json_response(response.text)
            return SeparationResult(
                page_num=page_num,
                original_text=data.get("original_text", ""),
                translation_text=data.get("translation_text", ""),
                notes=data.get("notes", []),
                uncertain=data.get("uncertain", []),
            )
        except Exception as e:
            logger.warning("분리 결과 JSON 파싱 실패 (page %d): %s", page_num, e)
            # 파싱 실패 시 전체 텍스트를 uncertain으로
            return SeparationResult(
                page_num=page_num,
                uncertain=[page_text],
            )

    async def separate_batch(
        self,
        pages: list[dict],
        structure: DocumentStructure,
        custom_instructions: str = "",
        force_provider: str | None = None,
        force_model: str | None = None,
    ) -> list[SeparationResult]:
        """여러 페이지를 순차적으로 분리한다.

        비용 절감: 구조가 동일하므로 system 프롬프트를 공유.
        병렬 처리는 LLM 라우터의 rate limit 때문에 순차 실행.

        입력:
            pages — [{page_num, text}, ...]
            structure — analyze_structure()의 결과
            custom_instructions — 사용자 추가 지시
        출력: [SeparationResult, ...]
        """
        results = []
        for page in pages:
            if not page.get("text", "").strip():
                # 빈 페이지는 빈 결과
                results.append(SeparationResult(page_num=page["page_num"]))
                continue

            result = await self.separate_page(
                page_text=page["text"],
                structure=structure,
                page_num=page["page_num"],
                custom_instructions=custom_instructions,
                force_provider=force_provider,
                force_model=force_model,
            )
            results.append(result)

        logger.info("배치 분리 완료: %d페이지", len(results))
        return results


def _parse_json_response(text: str) -> dict:
    """LLM 응답에서 JSON을 파싱한다.

    LLM이 ```json ... ``` 블록으로 감싸거나,
    앞뒤에 설명 텍스트를 붙이는 경우를 처리한다.
    """
    import re

    # ```json ... ``` 블록 추출
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1).strip())

    # { ... } 블록 직접 추출
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))

    raise ValueError(f"JSON을 찾을 수 없습니다: {text[:200]}")
