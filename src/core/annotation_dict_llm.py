"""사전형 주석 4단계 LLM 생성 파이프라인.

기존 annotation_llm.py(단순 태깅)와 별도로, 사전 형식의 주석을
4단계에 걸쳐 누적 생성하는 파이프라인.

Stage 1 (from_original): 표점된 원문에서 표제어 + 사전적 의미 생성
Stage 2 (from_translation): 번역을 참조하여 문맥적 의미 보강
Stage 3 (from_both): 원문+번역 종합하여 최종 통합
Stage 4 (reviewed): 사람이 검토하여 확정 (코드 개입 없음, UI에서 처리)

일괄 생성 모드: 원문+번역이 모두 준비된 경우 Stage 3으로 직행.

v2(2026-09-12, D-019 덧붙임): 항목에 범주(category 11종)·범위(scope)·학술 해설(sense_note)이 붙는다.
사용자가 바깥에서 쓰던 «전문 한문학자» 프롬프트(15개 내외·범주·scope·sense_note)를 옮긴 것이다.
주석 type(person·place·term…)은 category에서 코드가 정한다 — 모델에게 같은 것을 두 번 묻지 않는다.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from core.annotation import _gen_annotation_id
from core.llm_json_items import parse_llm_items
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
# 사전 항목의 범주·범위 (D-019 덧붙임 2026-09-12)
# ──────────────────────────────────────

CATEGORIES = (
    "Person",
    "Place",
    "Event",
    "Timespan",
    "Object",
    "Record",
    "ArtWork",
    "Food",
    "Clothing",
    "Concept",
    "Grammar",
)
SCOPES = ("general", "this_text_unit")
# 답변 예산 — 항목 15개 × (정의 2-3문장 + 해설 + 출전)이면 4,096으로는 잘린다(2026-09-12 실측)
DICT_MAX_TOKENS = 8192
# 범주 → 주석 type(resources/annotation_types.json의 기본 유형). 화면의 색·필터가 type을 본다.
TYPE_FOR_CATEGORY = {
    "Person": "person",
    "Place": "place",
    "Record": "book_title",
    "Grammar": "grammar",
    "Event": "term",
    "Timespan": "term",
    "Object": "term",
    "ArtWork": "term",
    "Food": "term",
    "Clothing": "term",
    "Concept": "term",
}
_CATEGORY_ALIASES = {c.lower(): c for c in CATEGORIES} | {"artwork": "ArtWork", "time": "Timespan"}


def normalize_dictionary(raw) -> dict | None:
    """LLM이 준 dictionary를 스키마 모양으로 다듬는다. 입력: dict 또는 None. 출력: dict 또는 None.

    category·scope는 정해진 값만 남기고(대소문자·별칭은 맞춰 준다) 아니면 None — 모델이 지어낸
    범주가 저장 스키마를 깨지 않게. 옛 항목(v1)은 세 칸이 없으므로 None으로 채운다.
    """
    if not isinstance(raw, dict):
        return None
    d = dict(raw)
    cat = d.get("category")
    d["category"] = _CATEGORY_ALIASES.get(str(cat).strip().lower()) if cat else None
    scope = str(d.get("scope") or "").strip().lower()
    d["scope"] = scope if scope in SCOPES else None
    note = d.get("sense_note")
    d["sense_note"] = str(note).strip() if note else None
    return d


# 기본 주석 유형(resources/annotation_types.json). 모델이 이 밖의 것을 적으면 범주에서 정한다 —
# 실측(2026-09-12): 기존 항목을 참고로 보여 주자 모델이 type에 "Place"(범주 이름)를 그대로
# 적어 왔다.
KNOWN_TYPES = frozenset(
    {"person", "place", "term", "allusion", "official_title", "book_title", "grammar", "note"}
)


def type_for(raw_type, category) -> str:
    """주석 type — 아는 유형을 적었으면 그것, 범주 이름을 적었거나 비었으면 범주에서."""
    t = str(raw_type or "").strip()
    if t.lower() in KNOWN_TYPES:
        return t.lower()
    cat = _CATEGORY_ALIASES.get(t.lower()) or category
    return TYPE_FOR_CATEGORY.get(cat or "", "term")


# ──────────────────────────────────────
# LLM 응답 파싱
# ──────────────────────────────────────


class GeneratedAnnotations(list):
    """생성 결과 목록 — list 그대로 쓰되 «어떻게 읽었는지»(diagnostics)를 붙인다.

    왜 list 하위형인가: 라우터·시험·병합이 이 결과를 list로 다룬다. 반환형을 바꾸면 그 전부가
    깨지므로, list인 채로 진단만 얹는다. 라우터는 `getattr(result, "diagnostics", None)`으로 읽어
    응답에 실고, 화면이 «완료»와 «부분 완료(잘린 답·거부 항목)»를 가른다(⑦).
    """

    def __init__(self, items=(), diagnostics: dict | None = None):
        super().__init__(items)
        self.diagnostics = dict(diagnostics or {})


def _parse_llm_annotations(response_text: str) -> list[dict]:
    """LLM 응답에서 주석 항목 목록만 꺼낸다(진단 없이). 공통 파서(core.llm_json_items)의 얇은 껍질.

    진단까지 필요한 자리(생성 단계 셋)는 `parse_llm_items()`를 직접 쓴다.
    """
    return parse_llm_items(response_text).items


def _as_index(value) -> int | None:
    """좌표 값을 int로. int(bool 제외)·숫자 문자열만 받고 아니면 None.

    기형 항목은 예외 대신 None으로 — 그 항목만 버린다(⑥).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _diagnostics(parsed, built: list, skipped: int = 0) -> dict:
    """생성 단계의 진단 — 파서 상태 + 좌표 검증에서 버린 항목 수(⑦).

    입력: parsed — parse_llm_items() 결과. built — _build_annotation_from_raw()를 통과한 항목.
          skipped — 모델이 deleted로 표시해 뺀 수(거부가 아니라 의도된 것).
    """
    d = parsed.diagnostics()
    d["rejected_items"] += max(len(parsed.items) - len(built) - skipped, 0)
    d["kept_items"] = len(built)
    return d


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

    기형 항목은 예외 대신 None — 항목 하나가 정상 항목 전부를 500으로 끌고 가면 안 된다(⑥).
    raw가 dict가 아니거나, target이 dict가 아니거나, 좌표가 정수(또는 숫자 문자열)가 아니면 None.
    """
    if not isinstance(raw, dict):
        return None
    target = raw.get("target")
    if not isinstance(target, dict):
        return None
    start = _as_index(target.get("start", 0))
    end = _as_index(target.get("end", start))
    if start is None or end is None:
        return None

    # 범위 정규화: 순서가 뒤집혔으면 바꾸고, 음수는 0으로. 순서: 뒤집기 → 자르기 —
    # 전에는 자르기 → 뒤집기여서 (0, -1)이 (-1, 0)이 되어 음수가 저장됐다.
    if end < start:
        start, end = end, start
    start = max(start, 0)
    end = max(end, start)
    # 원문 길이 초과시 무시
    if start >= text_len:
        return None
    if end >= text_len:
        end = text_len - 1

    content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
    dictionary = normalize_dictionary(raw.get("dictionary"))
    ann_type = type_for(raw.get("type"), (dictionary or {}).get("category"))

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


def merge_annotations(
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
                    target_ann["generation_history"].extend(llm_ann["generation_history"])
                continue

            # dictionary 필드 업데이트 — 범주가 바뀌면 type도 따라간다(⑧). type은 범주에서
            # 정하기로 했으므로(D-019 덧붙임) dictionary만 갈아 끼우면 화면 색·필터가 옛 유형을
            # 본다.
            if llm_ann.get("dictionary"):
                old_cat = (target_ann.get("dictionary") or {}).get("category")
                target_ann["dictionary"] = llm_ann["dictionary"]
                new_cat = llm_ann["dictionary"].get("category")
                if new_cat and new_cat != old_cat and llm_ann.get("type"):
                    target_ann["type"] = llm_ann["type"]

            # content 업데이트 (LLM이 보강한 label/description)
            if llm_ann.get("content"):
                target_ann["content"] = llm_ann["content"]

            # current_stage 업데이트
            target_ann["current_stage"] = stage

            # history 추가
            if llm_ann.get("generation_history"):
                target_ann.setdefault("generation_history", [])
                target_ann["generation_history"].extend(llm_ann["generation_history"])

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
    force_provider: str | None = None,
    force_model: str | None = None,
) -> list[dict]:
    """Stage 1: 표점된 원문만으로 사전 항목 초안을 생성한다.

    목적: 원문에서 인물/지명/용어/전거를 식별하고, 표제어와 사전적 의미를 기록.
    입력:
        original_text — L4 원문 문자열.
        block_id — 대상 블록 ID.
        router — LlmRouter 인스턴스.
        force_provider / force_model — 사용자가 화면에서 고른 공급자·모델.
            **반드시 router.call()로 전달해야 한다** — 예전에는 라우터 객체에
            속성으로 대입했는데 그런 속성이 없어 조용히 무시됐다(D-069).
        existing_annotations — 기존 주석 목록 (있으면 프롬프트에 포함).
    출력: annotation 항목 리스트 (annotation_page v2 형식).
    """
    prompt_config = _load_prompt("stage1")

    existing_section = ""
    if existing_annotations:
        existing_section = "기존 주석 (참고용):\n" + _serialize_existing_annotations(
            existing_annotations
        )

    user_prompt = prompt_config["user_template"].format(
        original_text=original_text,
        existing_section=existing_section,
    )

    response = await router.call(
        prompt=user_prompt,
        system=prompt_config["system"],
        purpose="annotation_dict_stage1",
        max_tokens=DICT_MAX_TOKENS,
        force_provider=force_provider,
        force_model=force_model,
    )

    parsed = parse_llm_items(response.text)
    raw_annotations = parsed.items

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

    return GeneratedAnnotations(results, _diagnostics(parsed, results))


# ──────────────────────────────────────
# Stage 2: 번역을 참조하여 보강
# ──────────────────────────────────────


async def generate_stage2_from_translation(
    original_text: str,
    translation_text: str,
    block_id: str,
    router: LlmRouter,
    existing_annotations: list[dict],
    force_provider: str | None = None,
    force_model: str | None = None,
    merge: bool = True,
) -> list[dict]:
    """Stage 2: 번역을 참조하여 기존 주석의 문맥적 의미를 보강한다.

    목적: 1단계에서 생성된 사전 항목에 번역 기반 contextual_meaning을 추가.
    입력:
        original_text — L4 원문.
        translation_text — L6 번역 텍스트.
        block_id — 대상 블록 ID.
        router — LlmRouter 인스턴스.
        force_provider / force_model — 사용자가 화면에서 고른 공급자·모델.
            **반드시 router.call()로 전달해야 한다** — 예전에는 라우터 객체에
            속성으로 대입했는데 그런 속성이 없어 조용히 무시됐다(D-069).
        existing_annotations — 1단계 결과 (기존 주석 목록).
        merge — True면 existing_annotations 위에 병합한 목록을, False면 LLM 항목만 돌려준다.
            라우터는 False로 받아 **지금 파일 상태** 위에 병합한다 — LLM을 기다리는 동안 들어온
            수동 주석을 지키기 위해(Codex 교차검증 2026-09-16 ①).
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
        max_tokens=DICT_MAX_TOKENS,
        force_provider=force_provider,
        force_model=force_model,
    )

    parsed = parse_llm_items(response.text)
    raw_annotations = parsed.items

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
    diag = _diagnostics(parsed, results)
    if not merge:
        return GeneratedAnnotations(results, diag)
    return GeneratedAnnotations(
        merge_annotations(existing_annotations, results, "from_translation"), diag
    )


# ──────────────────────────────────────
# Stage 3: 최종 통합 (일괄 생성 겸용)
# ──────────────────────────────────────


async def generate_stage3_from_both(
    original_text: str,
    translation_text: str,
    block_id: str,
    router: LlmRouter,
    existing_annotations: list[dict] | None = None,
    force_provider: str | None = None,
    force_model: str | None = None,
    merge: bool = True,
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
        force_provider / force_model — 사용자가 화면에서 고른 공급자·모델.
            **반드시 router.call()로 전달해야 한다** — 예전에는 라우터 객체에
            속성으로 대입했는데 그런 속성이 없어 조용히 무시됐다(D-069).
        existing_annotations — 이전 단계 결과. None이면 일괄 생성 모드.
        merge — False면 병합하지 않고 LLM 항목만 돌려준다(라우터가 지금 파일 위에 병합한다, ①).
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
        max_tokens=DICT_MAX_TOKENS,
        force_provider=force_provider,
        force_model=force_model,
    )

    parsed = parse_llm_items(response.text)
    raw_annotations = parsed.items

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
    deleted = 0
    for raw in raw_annotations:
        # "deleted": true인 항목은 건너뜀 — 모델이 «지워라»고 표시한 것이라 거부가 아니다
        if isinstance(raw, dict) and raw.get("deleted"):
            deleted += 1
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
    diag = _diagnostics(parsed, results, skipped=deleted)
    if not existing_annotations or not merge:
        return GeneratedAnnotations(results, diag)

    # 기존 항목이 있으면 병합
    return GeneratedAnnotations(merge_annotations(existing_annotations, results, "from_both"), diag)
