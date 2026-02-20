"""LLM 기반 번역 Draft 생성.

LlmRouter를 통해 한문 원문을 한국어로 번역하고,
연구자가 검토/수정 후 확정하는 Draft→Review→Commit 패턴.

번역 단위는 문장(표점으로 분리)이며,
표점이 없으면 블록 전체를 하나의 문장으로 취급한다.
"""

from datetime import datetime
from pathlib import Path

import yaml

from core.hyeonto import load_hyeonto, render_hyeonto_text
from core.punctuation import load_punctuation, split_sentences
from core.translation import (
    _gen_translation_id,
    add_translation,
    load_translations,
    save_translations,
)
from llm.draft import LlmDraft
from llm.router import LlmRouter


def _load_prompt() -> dict:
    """번역 프롬프트를 로드한다."""
    prompt_path = (
        Path(__file__).parent.parent / "llm" / "prompts" / "translation.yaml"
    )
    with open(prompt_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


async def generate_translation_drafts(
    original_text: str,
    block_id: str,
    router: LlmRouter,
    marks: list[dict] | None = None,
    annotations: list[dict] | None = None,
    context: str = "",
    target_language: str = "ko",
    dictionary_annotations: list[dict] | None = None,
    reference_dict_context: str = "",
) -> list[dict]:
    """LLM으로 문장별 번역 Draft를 생성한다.

    목적: L4 원문을 문장 단위로 분리한 후 각각 LLM 번역.
    입력:
        original_text — L4 원문 문자열.
        block_id — 대상 블록 ID.
        router — LlmRouter 인스턴스.
        marks — L5 표점 marks (있으면 문장 분리에 사용).
        annotations — L5 현토 annotations (있으면 프롬프트에 포함).
        context — 맥락 텍스트 (앞뒤 블록 원문 등).
        target_language — 번역 대상 언어.
        dictionary_annotations — L7 사전형 주석 리스트 (있으면 번역 참고).
            형식: [{"headword": "王戎", "dictionary_meaning": "...", ...}, ...]
        reference_dict_context — 참조 사전 매칭 결과 텍스트 (format_for_translation_context 출력).
    출력: 번역 항목 리스트 (translation_page.json의 translations 형식).

    왜 dictionary_annotations를 추가하는가:
        사전형 주석이 있으면 번역의 일관성과 정확성이 높아진다.
        특히 고유명사(인물, 지명)의 번역 일관성에 효과적이다.
        "주석 참조 재번역" 기능의 핵심 파라미터이다.
    """
    prompt_config = _load_prompt()

    # 1. 문장 분리 (표점 있으면 분리, 없으면 블록 전체)
    if marks:
        sentences = split_sentences(original_text, marks)
    else:
        sentences = [{
            "start": 0,
            "end": len(original_text) - 1,
            "text": original_text,
        }]

    if not sentences:
        return []

    # 2. 각 문장에 대해 번역
    results = []
    for sent in sentences:
        source_text = sent["text"]
        start = sent["start"]
        end = sent["end"]

        # 현토가 있으면 해당 범위에 대해 합성 텍스트 생성
        hyeonto_text = None
        if annotations:
            # 현토 중 이 문장 범위에 해당하는 것만 필터링
            sent_anns = _filter_annotations_for_range(annotations, start, end)
            if sent_anns:
                hyeonto_text = render_hyeonto_text(source_text, _shift_annotations(sent_anns, start))

        # 프롬프트 조립
        hyeonto_section = ""
        if hyeonto_text:
            hyeonto_section = f"현토: {hyeonto_text}  (참고용)"

        # 사전 참고 섹션 조립
        dict_section = _build_dictionary_section(
            source_text, start, end,
            dictionary_annotations, reference_dict_context,
        )

        user_prompt = prompt_config["prompt_template"].format(
            original_text=source_text,
            hyeonto_section=hyeonto_section,
            context=context or "(첫 문장)",
        )

        # 사전 참고 섹션이 있으면 프롬프트 끝에 추가
        if dict_section:
            user_prompt += f"\n\n{dict_section}"

        # LLM 호출
        response = await router.call(
            prompt=user_prompt,
            system=prompt_config["system"],
            purpose="translation",
            max_tokens=1024,
        )

        # 번역 결과에서 앞뒤 공백/줄바꿈 제거
        translation_text = response.text.strip()

        # Draft 생성
        draft = LlmDraft(
            purpose="translation",
            response_text=translation_text,
            response_data={"translation": translation_text},
            provider=response.provider,
            model=response.model,
            cost_usd=getattr(response, "cost_usd", 0.0),
            elapsed_sec=getattr(response, "elapsed_sec", 0.0),
        )

        # annotation_context 구성: 사전 참조가 있었으면 기록
        ann_context = None
        if dictionary_annotations or reference_dict_context:
            used_ids = []
            if dictionary_annotations:
                used_ids = [a.get("id", "") for a in dictionary_annotations if a.get("id")]
            ref_filenames = []  # 참조 사전 파일명은 호출자가 제공해야 함
            ann_context = {
                "used_annotation_ids": used_ids,
                "reference_dict_filenames": ref_filenames,
            }

        # L6 형식으로 변환
        entry = {
            "id": _gen_translation_id(),
            "source": {
                "block_id": block_id,
                "start": start,
                "end": end,
            },
            "source_text": source_text,
            "hyeonto_text": hyeonto_text,
            "target_language": target_language,
            "translation": translation_text,
            "translator": {
                "type": "llm",
                "model": response.model,
                "draft_id": draft.draft_id,
            },
            "status": "draft",
            "reviewed_by": None,
            "reviewed_at": None,
            "annotation_context": ann_context,
        }
        results.append(entry)

        # 맥락 업데이트 (다음 문장은 이전 번역을 맥락으로 참조)
        context = f"이전 문장: {source_text} → {translation_text}"

    return results


def commit_translation_draft(
    data: dict,
    translation_id: str,
    modifications: dict | None = None,
) -> dict | None:
    """검토 완료된 번역 Draft를 확정한다.

    목적: 연구자가 Draft를 검토/수정한 후 확정하면 status를 accepted로 변경.
    입력:
        data — translation_page 데이터.
        translation_id — 확정할 번역 ID.
        modifications — 수정 사항 (있으면 반영). 예: {"translation": "수정된 번역"}.
    출력: 수정된 translation entry. 없으면 None.
    """
    for tr in data["translations"]:
        if tr["id"] == translation_id:
            if modifications:
                for key, value in modifications.items():
                    tr[key] = value
            tr["status"] = "accepted"
            tr["reviewed_at"] = datetime.now().isoformat()
            return tr
    return None


# ──────────────────────────────────────
# 내부 유틸리티
# ──────────────────────────────────────


def _filter_annotations_for_range(
    annotations: list[dict], start: int, end: int
) -> list[dict]:
    """주어진 글자 범위에 해당하는 현토만 필터링한다.

    왜 이렇게 하는가:
        문장별로 번역할 때, 해당 문장 범위의 현토만 필요하다.
        범위 밖의 현토는 무시한다.
    """
    result = []
    for ann in annotations:
        target = ann.get("target", {})
        ann_start = target.get("start", 0)
        ann_end = target.get("end", ann_start)
        # 현토의 범위가 문장 범위와 겹치면 포함
        if ann_end >= start and ann_start <= end:
            result.append(ann)
    return result


def _build_dictionary_section(
    source_text: str,
    start: int,
    end: int,
    dictionary_annotations: list[dict] | None,
    reference_dict_context: str,
) -> str:
    """번역 프롬프트에 포함할 사전 참고 섹션을 생성한다.

    목적: 사전형 주석과 참조 사전 정보를 번역 LLM이 참고할 수 있는 텍스트로 변환.
    입력:
        source_text — 현재 문장 원문.
        start, end — 현재 문장의 블록 내 범위.
        dictionary_annotations — L7 사전형 주석 리스트.
        reference_dict_context — 참조 사전 매칭 결과 텍스트 (이미 포맷됨).
    출력: 프롬프트에 추가할 텍스트. 비어있으면 빈 문자열.

    왜 이렇게 하는가:
        LLM에게 이미 확인된 어휘 정보를 제공하면 번역 일관성이 높아진다.
        사전 주석과 참조 사전 정보를 모두 하나의 섹션으로 통합한다.
    """
    lines = []

    # 1. L7 사전형 주석에서 이 문장 범위에 해당하는 항목 추출
    if dictionary_annotations:
        relevant = []
        for ann in dictionary_annotations:
            target = ann.get("target", {})
            ann_start = target.get("start", 0)
            ann_end = target.get("end", ann_start)
            # 범위가 겹치는 주석만 포함
            if ann_end >= start and ann_start <= end:
                dict_entry = ann.get("dictionary") or {}
                hw = dict_entry.get("headword", "")
                if hw:
                    reading = dict_entry.get("headword_reading") or ""
                    meaning = dict_entry.get("dictionary_meaning", "")
                    ctx = dict_entry.get("contextual_meaning") or ""
                    line = f"- {hw}"
                    if reading:
                        line += f"({reading})"
                    line += f": {meaning}"
                    if ctx:
                        line += f" / 문맥: {ctx}"
                    relevant.append(line)

        if relevant:
            lines.append("[이 블록의 사전 주석]")
            lines.extend(relevant)

    # 2. 참조 사전 컨텍스트 (이미 포맷된 텍스트)
    if reference_dict_context:
        if lines:
            lines.append("")  # 빈 줄로 구분
        lines.append(reference_dict_context)

    return "\n".join(lines)


def _shift_annotations(annotations: list[dict], offset: int) -> list[dict]:
    """현토의 인덱스를 offset만큼 이동한다.

    왜 이렇게 하는가:
        render_hyeonto_text()는 0부터 시작하는 인덱스를 기대하지만,
        문장이 원문의 중간에서 시작할 수 있다.
        예: 원문 "ABCDEFGH"에서 문장이 index 4부터 시작하면
            현토 target.start=5는 새 텍스트에서 1이 되어야 한다.
    """
    shifted = []
    for ann in annotations:
        new_ann = dict(ann)
        target = dict(ann.get("target", {}))
        target["start"] = target.get("start", 0) - offset
        target["end"] = target.get("end", target["start"] + offset) - offset
        new_ann["target"] = target
        shifted.append(new_ann)
    return shifted
