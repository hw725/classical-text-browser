"""LLM 응답에서 항목 목록을 꺼내는 공통 파서 — 기형 항목 격리·잘린 답 복구·진단.

Codex 교차검증(2026-09-16) ⑥·⑦·⑪.

왜 이 시험이 필요한가:
    ⑥ JSON 문법만 맞는 기형 응답(`annotations: null`, `[null]`, 시작 위치가 문자열)이 정상 항목까지
       끌고 500으로 끝났다. 항목 하나가 이상하면 그 항목만 버려야 한다.
    ⑦ 잘린 답에서 완성된 항목만 건진 것과 정상 완료가 화면에서 구분되지 않았다. 파서는 «어떻게
       읽었는지»(ok·recovered·no_json)와 버린 개수를 함께 돌려준다.
    ⑪ 사전형 주석 파서와 일반 주석 파서가 갈라져 같은 잘린 답에 한쪽은 1건·한쪽은 0건이었다.
       둘 다 같은 공통 파서를 쓴다.
"""

from __future__ import annotations

import json

import pytest

from core import annotation_dict_llm, annotation_llm
from core.annotation_dict_llm import _build_annotation_from_raw
from core.llm_json_items import parse_llm_items

ITEM = {"target": {"start": 0, "end": 1}, "content": {"label": "王戎", "description": "…"}}
TRUNCATED = (
    '{"annotations": [' + json.dumps(ITEM, ensure_ascii=False) + ', {"target": {"start": 2, "en'
)


def test_well_formed_object_and_list():
    r = parse_llm_items(json.dumps({"annotations": [ITEM]}, ensure_ascii=False))
    assert r.status == "ok" and r.items == [ITEM] and r.rejected == 0
    r = parse_llm_items(json.dumps([ITEM], ensure_ascii=False))
    assert r.status == "ok" and r.items == [ITEM]


def test_fenced_block_and_prose_around_json():
    text = "다음과 같습니다.\n```json\n" + json.dumps({"annotations": [ITEM]}) + "\n```\n끝."
    r = parse_llm_items(text)
    assert r.status == "ok" and r.items == [ITEM]


@pytest.mark.parametrize(
    "payload,expected_items,expected_rejected",
    [
        ({"annotations": None}, 0, 0),
        ({"annotations": "王戎"}, 0, 1),
        ({"annotations": [None, ITEM, 3, "x"]}, 1, 3),
    ],
)
def test_malformed_items_are_isolated_not_fatal(payload, expected_items, expected_rejected):
    r = parse_llm_items(json.dumps(payload, ensure_ascii=False))
    assert r.status == "ok"
    assert len(r.items) == expected_items
    assert r.rejected == expected_rejected
    assert all(isinstance(it, dict) for it in r.items)


def test_truncated_answer_is_recovered_and_flagged():
    r = parse_llm_items(TRUNCATED)
    assert r.items == [ITEM]
    assert r.status == "recovered"


def test_no_json_is_distinguished_from_empty():
    r = parse_llm_items("죄송합니다. 이 글에는 주석할 항목이 없습니다.")
    assert r.items == [] and r.status == "no_json"
    r = parse_llm_items('{"annotations": []}')
    assert r.items == [] and r.status == "ok"


def test_both_annotation_parsers_share_the_recovery():
    """⑪ 같은 잘린 답 → 두 파서가 같은 결과."""
    a = annotation_dict_llm._parse_llm_annotations(TRUNCATED)
    b = annotation_llm._parse_llm_annotations(TRUNCATED)
    assert a == b == [ITEM]


# ── ⑥ 항목 좌표 검증 ──


def _build(raw, text_len=10):
    return _build_annotation_from_raw(
        raw=raw,
        text_len=text_len,
        response_model="m",
        draft_id="d",
        stage="from_original",
        original_text="甲" * text_len,
        translation_text=None,
    )


def test_non_dict_raw_is_rejected_without_exception():
    assert _build(None) is None
    assert _build("王戎") is None
    assert _build({"target": "0-1", "content": {"label": "x"}}) is None


def test_string_start_is_rejected_bool_is_rejected_digit_string_is_accepted():
    assert _build({"target": {"start": "abc", "end": 3}, "content": {"label": "x"}}) is None
    assert _build({"target": {"start": True, "end": 3}, "content": {"label": "x"}}) is None
    ann = _build({"target": {"start": "2", "end": "3"}, "content": {"label": "x"}})
    assert ann is not None and ann["target"] == {"start": 2, "end": 3}


def test_zero_start_negative_end_normalizes_to_zero_zero():
    ann = _build({"target": {"start": 0, "end": -1}, "content": {"label": "x"}})
    assert ann is not None
    assert ann["target"] == {"start": 0, "end": 0}


def test_negative_start_positive_end_clamps_start():
    ann = _build({"target": {"start": -3, "end": 2}, "content": {"label": "x"}})
    assert ann is not None and ann["target"] == {"start": 0, "end": 2}


# ── ⑧ 병합이 범주에서 나온 유형을 따라간다 ──


def test_merge_updates_type_when_llm_recategorizes():
    existing = [
        {
            "id": "ann_1",
            "target": {"start": 0, "end": 1},
            "type": "person",
            "content": {"label": "x", "description": "", "references": []},
            "dictionary": {"headword": "x", "dictionary_meaning": "…", "category": "Person"},
            "status": "draft",
            "annotator": {"type": "llm", "model": "m", "draft_id": "d"},
        }
    ]
    llm = _build(
        {
            "id": "ann_1",
            "target": {"start": 0, "end": 1},
            "content": {"label": "x", "description": "지명"},
            "dictionary": {"headword": "x", "dictionary_meaning": "땅", "category": "Place"},
        }
    )
    merged = annotation_dict_llm.merge_annotations(existing, [llm], "from_translation")
    assert merged[0]["dictionary"]["category"] == "Place"
    assert merged[0]["type"] == "place"
