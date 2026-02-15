"""LLM 기반 레이아웃 분석.

이미지를 LLM에 보내서 LayoutBlock 제안을 받고, Draft로 반환.
"""

import json
from pathlib import Path
from typing import Optional

import yaml

from src.llm.draft import LlmDraft
from src.llm.providers.base import LlmResponse
from src.llm.router import LlmRouter


def _load_prompt() -> dict:
    """레이아웃 분석 프롬프트를 로드한다."""
    prompt_path = (
        Path(__file__).parent.parent / "llm" / "prompts" / "layout_analysis.yaml"
    )
    with open(prompt_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_llm_json(text: str) -> dict:
    """LLM 응답에서 JSON을 추출한다.

    코드블록 감싸기(```json ... ```)를 자동 제거한다.
    """
    text = text.strip()
    if text.startswith("```"):
        # 첫 줄 (```json 등) 제거
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text)


async def analyze_page_layout(
    router: LlmRouter,
    page_image: bytes,
    *,
    image_mime: str = "image/png",
    force_provider: Optional[str] = None,
    force_model: Optional[str] = None,
) -> LlmDraft:
    """페이지 이미지 → LLM 레이아웃 분석 → Draft 반환.

    반환된 Draft의 response_data에 blocks 배열이 들어있다.
    status는 "pending" — 사용자가 검토 후 accept/modify/reject.
    """
    prompt_config = _load_prompt()

    response: LlmResponse = await router.call_with_image(
        prompt_config["prompt_template"],
        page_image,
        image_mime=image_mime,
        system=prompt_config["system"],
        response_format="json",
        force_provider=force_provider,
        force_model=force_model,
        purpose="layout_analysis",
    )

    # JSON 파싱 시도
    response_data = None
    try:
        response_data = _parse_llm_json(response.text)
    except (json.JSONDecodeError, IndexError):
        response_data = {"raw_text": response.text, "parse_error": True}

    draft = LlmDraft(
        purpose="layout_analysis",
        provider=response.provider,
        model=response.model,
        prompt_used=prompt_config["prompt_template"][:200],
        response_text=response.text,
        response_data=response_data,
        cost_usd=response.cost_usd or 0.0,
        elapsed_sec=response.elapsed_sec or 0.0,
    )

    return draft


async def compare_layout_analysis(
    router: LlmRouter,
    page_image: bytes,
    *,
    targets: Optional[list] = None,
) -> list[LlmDraft]:
    """여러 모델로 레이아웃 분석 비교. Draft 목록 반환."""
    prompt_config = _load_prompt()

    results = await router.compare(
        prompt_config["prompt_template"],
        image=page_image,
        system=prompt_config["system"],
        targets=targets,
        purpose="layout_analysis",
    )

    drafts = []
    for r in results:
        if isinstance(r, Exception):
            drafts.append(LlmDraft(
                purpose="layout_analysis",
                status="rejected",
                quality_notes=f"호출 실패: {r}",
            ))
        else:
            response_data = None
            try:
                response_data = _parse_llm_json(r.text)
            except (json.JSONDecodeError, IndexError):
                response_data = {"raw_text": r.text, "parse_error": True}

            drafts.append(LlmDraft(
                purpose="layout_analysis",
                provider=r.provider,
                model=r.model,
                response_text=r.text,
                response_data=response_data,
                cost_usd=r.cost_usd or 0.0,
                elapsed_sec=r.elapsed_sec or 0.0,
            ))

    return drafts
