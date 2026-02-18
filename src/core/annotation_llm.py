"""LLM 기반 주석 자동 태깅.

LlmRouter를 통해 한문 원문의 인물·지명·용어·전거를 자동 식별하고,
Draft 상태로 저장하여 연구자가 검토/수정 후 확정하는 흐름.
"""

import json
from datetime import datetime
from pathlib import Path

import yaml

from core.annotation import (
    _gen_annotation_id,
    add_annotation,
    load_annotations,
    save_annotations,
)
from llm.draft import LlmDraft
from llm.router import LlmRouter


def _load_prompt() -> dict:
    """주석 프롬프트를 로드한다."""
    prompt_path = (
        Path(__file__).parent.parent / "llm" / "prompts" / "annotation.yaml"
    )
    with open(prompt_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_llm_annotations(response_text: str) -> list[dict]:
    """LLM 응답에서 주석 JSON 배열을 파싱한다.

    왜 이렇게 하는가:
        LLM이 JSON 외에 설명 텍스트를 붙일 수 있으므로,
        ```json ... ``` 블록이나 { ... } 패턴을 추출한다.
    """
    text = response_text.strip()

    # ```json ... ``` 블록 추출
    if "```" in text:
        start = text.find("```")
        # ```json 또는 ``` 다음의 내용
        content_start = text.find("\n", start)
        end = text.find("```", content_start)
        if content_start != -1 and end != -1:
            text = text[content_start:end].strip()

    # JSON 객체 추출 시도
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "annotations" in parsed:
            return parsed["annotations"]
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # { 부터 마지막 } 까지 추출 재시도
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1:
        try:
            parsed = json.loads(text[first_brace:last_brace + 1])
            if isinstance(parsed, dict) and "annotations" in parsed:
                return parsed["annotations"]
        except json.JSONDecodeError:
            pass

    return []


async def generate_annotation_drafts(
    original_text: str,
    block_id: str,
    router: LlmRouter,
    translation_text: str | None = None,
) -> list[dict]:
    """LLM으로 주석 Draft를 생성한다.

    목적: 원문에서 인물/지명/용어/전거를 자동 식별.
    입력:
        original_text — L4 원문 문자열.
        block_id — 대상 블록 ID.
        router — LlmRouter 인스턴스.
        translation_text — L6 번역 텍스트 (맥락으로 활용). None이면 생략.
    출력: 주석 항목 리스트 (annotation_page.json의 annotation 형식).
    """
    prompt_config = _load_prompt()

    # 번역이 있으면 맥락으로 포함
    translation_section = ""
    if translation_text:
        translation_section = f"번역 참고: {translation_text}"

    user_prompt = prompt_config["user_template"].format(
        original_text=original_text,
        translation_section=translation_section,
    )

    # LLM 호출
    response = await router.call(
        prompt=user_prompt,
        system=prompt_config["system"],
        purpose="annotation",
        max_tokens=2048,
    )

    # 응답 파싱
    raw_annotations = _parse_llm_annotations(response.text)

    # Draft 생성
    draft = LlmDraft(
        purpose="annotation",
        response_text=response.text,
        response_data={"annotations": raw_annotations},
        provider=response.provider,
        model=response.model,
        cost_usd=getattr(response, "cost_usd", 0.0),
        elapsed_sec=getattr(response, "elapsed_sec", 0.0),
    )

    # L7 형식으로 변환
    results = []
    text_len = len(original_text)

    for raw in raw_annotations:
        target = raw.get("target", {})
        start = target.get("start", 0)
        end = target.get("end", start)

        # 범위 검증: 원문 길이를 초과하면 무시
        if start < 0 or end < start or end >= text_len:
            continue

        ann_type = raw.get("type", "note")
        content = raw.get("content", {})

        annotation = {
            "id": _gen_annotation_id(),
            "target": {"start": start, "end": end},
            "type": ann_type,
            "content": {
                "label": content.get("label", ""),
                "description": content.get("description", ""),
                "references": content.get("references", []),
            },
            "annotator": {
                "type": "llm",
                "model": response.model,
                "draft_id": draft.draft_id,
            },
            "status": "draft",
            "reviewed_by": None,
            "reviewed_at": None,
        }
        results.append(annotation)

    return results


def commit_annotation_draft(
    data: dict,
    block_id: str,
    annotation_id: str,
    modifications: dict | None = None,
) -> dict | None:
    """검토 완료된 주석 Draft를 확정한다.

    목적: 연구자가 Draft를 검토/수정한 후 확정하면 status를 accepted로 변경.
    입력:
        data — annotation_page 데이터.
        block_id — 블록 ID.
        annotation_id — 확정할 주석 ID.
        modifications — 수정 사항. 예: {"content": {...}}.
    출력: 수정된 annotation. 없으면 None.
    """
    for block in data.get("blocks", []):
        if block["block_id"] == block_id:
            for ann in block["annotations"]:
                if ann["id"] == annotation_id:
                    if modifications:
                        for key, value in modifications.items():
                            ann[key] = value
                    ann["status"] = "accepted"
                    ann["reviewed_at"] = datetime.now().isoformat()
                    return ann
    return None


def commit_all_drafts(data: dict) -> int:
    """모든 draft 상태의 주석을 일괄 확정한다.

    목적: 페이지 전체 Draft를 한번에 승인.
    출력: 확정된 주석 개수.
    """
    count = 0
    now = datetime.now().isoformat()
    for block in data.get("blocks", []):
        for ann in block["annotations"]:
            if ann.get("status") == "draft":
                ann["status"] = "accepted"
                ann["reviewed_at"] = now
                count += 1
    return count
