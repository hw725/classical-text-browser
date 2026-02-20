"""사전형 주석 4단계 LLM 생성 파이프라인.

기존 annotation_llm.py(단순 태깅)와 별도로, 사전 형식의 주석을
4단계에 걸쳐 누적 생성하는 파이프라인.

Stage 1 (from_original): 표점된 원문에서 표제어 + 사전적 의미 생성
Stage 2 (from_translation): 번역을 참조하여 문맥적 의미 보강
Stage 3 (from_both): 원문+번역 종합하여 최종 통합
Stage 4 (reviewed): 사람이 검토하여 확정 (코드 개입 없음, UI에서 처리)

일괄 생성 모드: 원문+번역이 모두 준비된 경우 Stage 3으로 직행.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from core.annotation import _gen_annotation_id
from llm.draft import LlmDraft
from llm.router import LlmRouter

# ──────────────────────────────────────
# 프롬프트 로드
# ──────────────────────────────────────

_PROMPT_DIR = Path(__file__).parent.parent / "llm" / "prompts"


def _load_prompt(stage: str) -> dict:
    """단계별 프롬프트 YAML을 로드한다.

    왜 이렇게 하는가:
        각 단계(stage1/2/3)는 서로 다른 system 지시와 user_template을 사용한다.
        프롬프트를 YAML 파일로 분리하면 코드 수정 없이 프롬프트를 반복 개선할 수 있다.
    """
    prompt_path = _PROMPT_DIR / f"annotation_dict_{stage}.yaml"
    with open(prompt_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ──────────────────────────────────────
# LLM 응답 파싱
# ──────────────────────────────────────


def _parse_llm_annotations(response_text: str) -> list[dict]:
    """LLM 응답에서 주석 JSON 배열을 파싱한다.

    왜 이렇게 하는가:
        LLM이 JSON 외에 설명 텍스트를 붙일 수 있으므로,
        ```json ... ``` 블록이나 { ... } 패턴을 추출한다.
        annotation_llm.py와 동일한 파싱 로직 재사용.
    """
    text = response_text.strip()

    # ```json ... ``` 블록 추출
    if "```" in text:
        start = text.find("```")
        content_start = text.find("\n", start)
        end = text.find("```", content_start)
        if content_start != -1 and end != -1:
            text = text[content_start:end].strip()

    # JSON 파싱 시도
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
            parsed = json.loads(text[first_brace : last_brace + 1])
            if isinstance(parsed, dict) and "annotations" in parsed:
                return parsed["annotations"]
        except json.JSONDecodeError:
            pass

    return []


# ──────────────────────────────────────
# 기존 주석을 프롬프트용 JSON으로 직렬화
# ──────────────────────────────────────


def _serialize_existing_annotations(annotations: list[dict]) -> str:
    """기존 주석 목록을 LLM 프롬프트에 포함할 JSON 문자열로 변환한다.

    왜 이렇게 하는가:
        2/3단계에서 LLM은 이전 단계의 결과를 입력으로 받아 보강한다.
        id, target, type, dictionary 필드만 추출하여 프롬프트를 간결하게 유지.
    """
    if not annotations:
        return "(없음)"

    items = []
    for ann in annotations:
        item = {
            "id": ann.get("id"),
            "target": ann.get("target"),
            "type": ann.get("type"),
            "content": ann.get("content"),
        }
        if ann.get("dictionary"):
            item["dictionary"] = ann["dictionary"]
        items.append(item)

    return json.dumps(items, ensure_ascii=False, indent=2)


# ──────────────────────────────────────
# LLM 결과를 L7 형식으로 변환
# ──────────────────────────────────────


def _build_annotation_from_raw(
    raw: dict,
    text_len: int,
    response_model: str,
    draft_id: str,
    stage: str,
    original_text: str | None,
    translation_text: str | None,
    existing_id: str | None = None,
) -> dict | None:
    """LLM 원시 응답 하나를 L7 annotation 형식으로 변환한다.

    입력:
        raw — LLM 응답의 개별 annotation dict.
        text_len — 원문 길이 (범위 검증용).
        response_model — LLM 모델명.
        draft_id — LLM Draft ID.
        stage — 현재 생성 단계.
        original_text — 원문 스냅샷.
        translation_text — 번역 스냅샷.
        existing_id — 기존 주석의 id (매칭된 경우).
    출력: annotation dict. 범위 무효시 None.
    """
    target = raw.get("target", {})
    start = target.get("start", 0)
    end = target.get("end", start)

    # 범위 검증: 음수이거나 순서 역전이면 정규화
    if start < 0:
        start = 0
    if end < start:
        start, end = end, start
    # 원문 길이 초과시 무시
    if start >= text_len:
        return None
    if end >= text_len:
        end = text_len - 1

    ann_type = raw.get("type", "note")
    content = raw.get("content", {})
    dictionary = raw.get("dictionary")

    now = datetime.now(timezone.utc).isoformat()

    # generation_history 스냅샷
    history_entry = {
        "stage": stage,
        "timestamp": now,
        "content_snapshot": {
            "label": content.get("label", ""),
            "description": content.get("description", ""),
            "references": content.get("references", []),
        },
        "dictionary_snapshot": dictionary,
        "generator": {
            "type": "llm",
            "model": response_model,
            "draft_id": draft_id,
        },
        "input_sources": {
            "original_text": original_text,
            "translation_text": translation_text,
            "previous_stage": None,
        },
    }

    annotation = {
        "id": existing_id or raw.get("id") or _gen_annotation_id(),
        "target": {"start": start, "end": end},
        "type": ann_type,
        "content": {
            "label": content.get("label", ""),
            "description": content.get("description", ""),
            "references": content.get("references", []),
        },
        "dictionary": dictionary,
        "current_stage": stage,
        "generation_history": [history_entry],
        "source_text_snapshot": original_text,
        "translation_snapshot": translation_text,
        "annotator": {
            "type": "llm",
            "model": response_model,
            "draft_id": draft_id,
        },
        "status": "draft",
        "reviewed_by": None,
        "reviewed_at": None,
    }
    return annotation


# ──────────────────────────────────────
# 기존 주석과 LLM 결과 병합
# ──────────────────────────────────────


def _merge_annotations(
    existing: list[dict],
    llm_results: list[dict],
    stage: str,
) -> list[dict]:
    """기존 주석 목록에 LLM 생성 결과를 병합한다.

    왜 이렇게 하는가:
        2/3단계에서 LLM은 기존 항목의 id를 유지하면서 필드를 보강한다.
        id가 매칭되면 dictionary 필드를 업데이트하고 history에 추가.
        매칭되지 않는 새 항목은 리스트에 추가.
        사람이 편집한(status=accepted) 항목은 덮어쓰지 않고 history에만 기록.

    입력:
        existing — 기존 annotation 목록.
        llm_results — LLM이 생성한 annotation 목록 (이미 L7 형식으로 변환됨).
        stage — 현재 생성 단계.
    출력: 병합된 annotation 목록.
    """
    # 기존 주석을 id로 인덱싱
    existing_by_id = {ann["id"]: ann for ann in existing}
    merged = list(existing)  # 기존 목록 복사

    for llm_ann in llm_results:
        llm_id = llm_ann.get("id")

        if llm_id and llm_id in existing_by_id:
            # 매칭된 기존 항목 업데이트
            target_ann = existing_by_id[llm_id]

            # 사람이 확정한 항목은 덮어쓰지 않음
            if target_ann.get("status") == "accepted":
                # history에만 LLM 제안 기록
                if llm_ann.get("generation_history"):
                    target_ann.setdefault("generation_history", [])
                    target_ann["generation_history"].extend(
                        llm_ann["generation_history"]
                    )
                continue

            # dictionary 필드 업데이트
            if llm_ann.get("dictionary"):
                target_ann["dictionary"] = llm_ann["dictionary"]

            # content 업데이트 (LLM이 보강한 label/description)
            if llm_ann.get("content"):
                target_ann["content"] = llm_ann["content"]

            # current_stage 업데이트
            target_ann["current_stage"] = stage

            # history 추가
            if llm_ann.get("generation_history"):
                target_ann.setdefault("generation_history", [])
                target_ann["generation_history"].extend(
                    llm_ann["generation_history"]
                )

            # 스냅샷 업데이트
            if llm_ann.get("source_text_snapshot"):
                target_ann["source_text_snapshot"] = llm_ann["source_text_snapshot"]
            if llm_ann.get("translation_snapshot"):
                target_ann["translation_snapshot"] = llm_ann["translation_snapshot"]

            # annotator 업데이트 (최신 LLM 정보)
            target_ann["annotator"] = llm_ann["annotator"]
        else:
            # 새 항목 추가
            merged.append(llm_ann)

    return merged


# ──────────────────────────────────────
# Stage 1: 원문에서 사전 항목 초안 생성
# ──────────────────────────────────────


async def generate_stage1_from_original(
    original_text: str,
    block_id: str,
    router: LlmRouter,
    existing_annotations: list[dict] | None = None,
) -> list[dict]:
    """Stage 1: 표점된 원문만으로 사전 항목 초안을 생성한다.

    목적: 원문에서 인물/지명/용어/전거를 식별하고, 표제어와 사전적 의미를 기록.
    입력:
        original_text — L4 원문 문자열.
        block_id — 대상 블록 ID.
        router — LlmRouter 인스턴스.
        existing_annotations — 기존 주석 목록 (있으면 프롬프트에 포함).
    출력: annotation 항목 리스트 (annotation_page v2 형식).
    """
    prompt_config = _load_prompt("stage1")

    existing_section = ""
    if existing_annotations:
        existing_section = (
            "기존 주석 (참고용):\n"
            + _serialize_existing_annotations(existing_annotations)
        )

    user_prompt = prompt_config["user_template"].format(
        original_text=original_text,
        existing_section=existing_section,
    )

    response = await router.call(
        prompt=user_prompt,
        system=prompt_config["system"],
        purpose="annotation_dict_stage1",
        max_tokens=4096,
    )

    raw_annotations = _parse_llm_annotations(response.text)

    draft = LlmDraft(
        purpose="annotation_dict_stage1",
        response_text=response.text,
        response_data={"annotations": raw_annotations},
        provider=response.provider,
        model=response.model,
        cost_usd=getattr(response, "cost_usd", 0.0),
        elapsed_sec=getattr(response, "elapsed_sec", 0.0),
    )

    text_len = len(original_text)
    results = []
    for raw in raw_annotations:
        ann = _build_annotation_from_raw(
            raw=raw,
            text_len=text_len,
            response_model=response.model,
            draft_id=draft.draft_id,
            stage="from_original",
            original_text=original_text,
            translation_text=None,
        )
        if ann:
            results.append(ann)

    return results


# ──────────────────────────────────────
# Stage 2: 번역을 참조하여 보강
# ──────────────────────────────────────


async def generate_stage2_from_translation(
    original_text: str,
    translation_text: str,
    block_id: str,
    router: LlmRouter,
    existing_annotations: list[dict],
) -> list[dict]:
    """Stage 2: 번역을 참조하여 기존 주석의 문맥적 의미를 보강한다.

    목적: 1단계에서 생성된 사전 항목에 번역 기반 contextual_meaning을 추가.
    입력:
        original_text — L4 원문.
        translation_text — L6 번역 텍스트.
        block_id — 대상 블록 ID.
        router — LlmRouter 인스턴스.
        existing_annotations — 1단계 결과 (기존 주석 목록).
    출력: 보강된 annotation 항목 리스트. 기존 항목과 병합하여 사용.
    """
    prompt_config = _load_prompt("stage2")

    user_prompt = prompt_config["user_template"].format(
        original_text=original_text,
        translation_text=translation_text,
        existing_annotations_json=_serialize_existing_annotations(existing_annotations),
    )

    response = await router.call(
        prompt=user_prompt,
        system=prompt_config["system"],
        purpose="annotation_dict_stage2",
        max_tokens=4096,
    )

    raw_annotations = _parse_llm_annotations(response.text)

    draft = LlmDraft(
        purpose="annotation_dict_stage2",
        response_text=response.text,
        response_data={"annotations": raw_annotations},
        provider=response.provider,
        model=response.model,
        cost_usd=getattr(response, "cost_usd", 0.0),
        elapsed_sec=getattr(response, "elapsed_sec", 0.0),
    )

    text_len = len(original_text)
    results = []
    for raw in raw_annotations:
        # id가 있으면 기존 항목 매칭 시도
        existing_id = raw.get("id")
        ann = _build_annotation_from_raw(
            raw=raw,
            text_len=text_len,
            response_model=response.model,
            draft_id=draft.draft_id,
            stage="from_translation",
            original_text=original_text,
            translation_text=translation_text,
            existing_id=existing_id,
        )
        if ann:
            results.append(ann)

    # 기존 주석과 병합
    return _merge_annotations(existing_annotations, results, "from_translation")


# ──────────────────────────────────────
# Stage 3: 최종 통합 (일괄 생성 겸용)
# ──────────────────────────────────────


async def generate_stage3_from_both(
    original_text: str,
    translation_text: str,
    block_id: str,
    router: LlmRouter,
    existing_annotations: list[dict] | None = None,
) -> list[dict]:
    """Stage 3: 원문+번역을 종합하여 최종 통합한다.

    이 함수는 두 가지 모드로 사용된다:
    1. 3단계 통합: existing_annotations에 1+2단계 결과가 있을 때 → 최종 점검.
    2. 일괄 생성: existing_annotations가 비어 있을 때 → 처음부터 모든 항목 생성.

    목적: 사전 항목의 사전적 의미와 문맥적 의미를 최종 확정.
    입력:
        original_text — L4 원문.
        translation_text — L6 번역 텍스트.
        block_id — 대상 블록 ID.
        router — LlmRouter 인스턴스.
        existing_annotations — 이전 단계 결과. None이면 일괄 생성 모드.
    출력: 최종 통합된 annotation 항목 리스트.
    """
    if existing_annotations is None:
        existing_annotations = []

    prompt_config = _load_prompt("stage3")

    user_prompt = prompt_config["user_template"].format(
        original_text=original_text,
        translation_text=translation_text,
        existing_annotations_json=_serialize_existing_annotations(existing_annotations),
    )

    response = await router.call(
        prompt=user_prompt,
        system=prompt_config["system"],
        purpose="annotation_dict_stage3",
        max_tokens=4096,
    )

    raw_annotations = _parse_llm_annotations(response.text)

    draft = LlmDraft(
        purpose="annotation_dict_stage3",
        response_text=response.text,
        response_data={"annotations": raw_annotations},
        provider=response.provider,
        model=response.model,
        cost_usd=getattr(response, "cost_usd", 0.0),
        elapsed_sec=getattr(response, "elapsed_sec", 0.0),
    )

    text_len = len(original_text)
    results = []
    for raw in raw_annotations:
        # "deleted": true인 항목은 건너뜀
        if raw.get("deleted"):
            continue

        existing_id = raw.get("id")
        ann = _build_annotation_from_raw(
            raw=raw,
            text_len=text_len,
            response_model=response.model,
            draft_id=draft.draft_id,
            stage="from_both",
            original_text=original_text,
            translation_text=translation_text,
            existing_id=existing_id,
        )
        if ann:
            results.append(ann)

    # 일괄 생성 모드 (기존 항목이 없을 때)는 결과를 그대로 반환
    if not existing_annotations:
        return results

    # 기존 항목이 있으면 병합
    return _merge_annotations(existing_annotations, results, "from_both")
