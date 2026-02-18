"""LLM 기반 표점 Draft 생성.

LlmRouter를 통해 한문 원문에 표점 초안을 생성하고,
연구자가 검토/수정 후 확정하는 Draft→Review→Commit 패턴.
"""

import json
from pathlib import Path

import yaml

from core.punctuation import _gen_mark_id, save_punctuation
from llm.draft import LlmDraft
from llm.router import LlmRouter


def _load_prompt() -> dict:
    """표점 프롬프트를 로드한다."""
    prompt_path = (
        Path(__file__).parent.parent / "llm" / "prompts" / "punctuation.yaml"
    )
    with open(prompt_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_llm_json(text: str) -> dict:
    """LLM 응답에서 JSON을 추출한다.

    코드블록 감싸기(```json ... ```)를 자동 제거한다.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3].rstrip()
    return json.loads(text)


def _normalize_marks(raw_marks: list[dict]) -> list[dict]:
    """LLM이 생성한 marks를 스키마 호환 형식으로 정규화한다.

    LLM은 id를 생성하지 않으므로 자동 부여하고,
    before/after가 빠져 있으면 null로 채운다.
    """
    normalized = []
    for raw in raw_marks:
        mark = {
            "id": _gen_mark_id(),
            "target": {
                "start": raw.get("start", 0),
                "end": raw.get("end", raw.get("start", 0)),
            },
            "before": raw.get("before"),
            "after": raw.get("after"),
        }
        normalized.append(mark)
    return normalized


async def generate_punctuation_draft(
    original_text: str,
    router: LlmRouter,
) -> LlmDraft:
    """LLM으로 표점 Draft를 생성한다.

    목적: L4 원문에 대해 LLM이 표점 초안을 생성한다.
    입력:
        original_text — L4 원문 문자열.
        router — LlmRouter 인스턴스.
    출력: LlmDraft (status=pending, response_data에 marks 포함).
    Raises: Exception — LLM 호출 실패 또는 JSON 파싱 실패 시.
    """
    prompt_config = _load_prompt()

    # 프롬프트 조립
    user_prompt = prompt_config["prompt_template"].format(
        original_text=original_text,
        char_count=len(original_text),
    )

    # LLM 호출
    response = await router.call(
        prompt=user_prompt,
        system=prompt_config["system"],
        response_format="json",
        purpose="punctuation",
        max_tokens=2048,
    )

    # JSON 파싱 + 정규화
    parsed = _parse_llm_json(response.text)
    raw_marks = parsed.get("marks", [])
    marks = _normalize_marks(raw_marks)

    # Draft 생성
    draft = LlmDraft(
        purpose="punctuation",
        response_text=response.text,
        response_data={"marks": marks},
        provider=response.provider,
        model=response.model,
        cost_usd=getattr(response, "cost_usd", 0.0),
        elapsed_sec=getattr(response, "elapsed_sec", 0.0),
    )

    return draft


def commit_punctuation_draft(
    draft: LlmDraft,
    block_id: str,
    interp_path: str | Path,
    part_id: str,
    page_num: int,
    modifications: dict | None = None,
) -> Path:
    """검토 완료된 Draft를 확정하고 파일로 저장한다.

    목적: 연구자가 Draft를 검토/수정한 후 확정하면 파일에 기록.
    입력:
        draft — LlmDraft 인스턴스.
        block_id — 대상 블록 ID.
        interp_path — 해석 저장소 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호.
        modifications — 수정 사항 (있으면 반영).
    출력: 저장된 파일 경로.
    """
    marks = draft.response_data.get("marks", [])

    # 수정 사항 반영
    if modifications and "marks" in modifications:
        marks = modifications["marks"]

    data = {
        "block_id": block_id,
        "marks": marks,
    }

    return save_punctuation(interp_path, part_id, page_num, data)
