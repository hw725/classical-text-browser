"""사전형 주석 v2 — 범주·범위·해설(D-019 덧붙임 2026-09-12).

1. normalize_dictionary — 정해진 범주·범위만 남기고, 별칭·대소문자는 맞추며, 지어낸 값은 null.
2. type_for — 주석 type은 범주에서(모델이 적었으면 그것).
3. _build_annotation_from_raw — 세 칸이 든 항목이 annotation_page 스키마를 통과한다.
   옛 항목(세 칸 없음)도.
4. 프롬프트 셋이 범주·scope·sense_note를 말한다.
"""

import json
from pathlib import Path

import jsonschema

from core.annotation_dict_llm import (
    CATEGORIES,
    TYPE_FOR_CATEGORY,
    _build_annotation_from_raw,
    _load_prompt,
    normalize_dictionary,
    type_for,
)

SCHEMA = json.loads(
    (Path(__file__).parent.parent / "schemas" / "interp" / "annotation_page.schema.json").read_text(
        encoding="utf-8"
    )
)


def _page(ann: dict) -> dict:
    return {
        "part_id": "main",
        "page_number": 1,
        "schema_version": "2.0",
        "blocks": [{"block_id": "p01_b01", "annotations": [ann]}],
    }


def test_normalize_keeps_only_known_categories_and_scopes():
    d = normalize_dictionary(
        {"headword": "王戎", "dictionary_meaning": "…", "category": "person", "scope": "General"}
    )
    assert d["category"] == "Person" and d["scope"] == "general"
    d = normalize_dictionary({"headword": "x", "dictionary_meaning": "…", "category": "artwork"})
    assert d["category"] == "ArtWork" and d["scope"] is None and d["sense_note"] is None
    d = normalize_dictionary(
        {
            "headword": "x",
            "dictionary_meaning": "…",
            "category": "Deity",
            "scope": "sentence",
            "sense_note": " 해설 ",
        }
    )
    assert d["category"] is None and d["scope"] is None and d["sense_note"] == "해설"
    assert normalize_dictionary(None) is None
    assert set(TYPE_FOR_CATEGORY) == set(CATEGORIES)


def test_type_comes_from_category_unless_model_said():
    assert type_for(None, "Person") == "person"
    assert type_for(None, "Record") == "book_title"
    assert type_for(None, "Grammar") == "grammar"
    assert type_for(None, "Food") == "term"
    assert type_for(None, None) == "term"
    assert type_for("allusion", "Person") == "allusion"


def test_built_annotation_with_new_fields_passes_schema():
    raw = {
        "target": {"start": 0, "end": 1},
        "content": {"label": "왕융(王戎)", "description": "죽림칠현"},
        "dictionary": {
            "headword": "王戎",
            "headword_reading": "왕융",
            "category": "Person",
            "scope": "general",
            "dictionary_meaning": "서진의 관료.",
            "sense_note": "「戎」은 «융»으로 읽는다.",
            "contextual_meaning": None,
            "source_references": [{"title": "晉書", "section": "列傳"}],
            "related_terms": ["竹林七賢"],
            "notes": None,
        },
    }
    ann = _build_annotation_from_raw(raw, 20, "m", "d1", "from_original", "王戎…", None)
    assert ann["type"] == "person"
    assert ann["dictionary"]["category"] == "Person" and ann["dictionary"]["sense_note"]
    jsonschema.validate(_page(ann), SCHEMA)
    # 옛 모양(세 칸 없음)도 스키마를 통과하고 type은 term으로 내려간다
    old = {
        "target": {"start": 2, "end": 3},
        "content": {"label": "x", "description": ""},
        "dictionary": {"headword": "山陽", "dictionary_meaning": "지명."},
    }
    ann2 = _build_annotation_from_raw(old, 20, "m", "d1", "from_original", "王戎…", None)
    assert ann2["type"] == "term" and ann2["dictionary"]["category"] is None
    jsonschema.validate(_page(ann2), SCHEMA)


def test_prompts_mention_categories_scope_and_note():
    for stage in ("stage1", "stage2", "stage3"):
        p = _load_prompt(stage)
        text = p["system"] + p["user_template"]
        assert "Grammar" in text and "this_text_unit" in text and "sense_note" in text, stage
        assert p["version"].startswith("2"), stage
