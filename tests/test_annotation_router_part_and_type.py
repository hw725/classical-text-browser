"""L7 주석 라우트 — 권(part_id)을 고정하지 않고, 진단을 응답에 싣고, 범주가 바뀌면 유형도 따라간다.

Codex 교차검증(2026-09-16, 기준 a0f47a6) ④·⑦·⑧의 재현·회귀 시험이다. 픽스처·도우미는
`test_annotation_router_merge.py`(①)의 것을 빌려 쓴다.

왜 이 시험이 필요한가:
    ④ 조회 API는 `part_id`를 받는데 추가·수정·생성은 `"main"`을 박아 두어, 다권본의 둘째 권을
       열어도 첫째 권 파일에 읽고 썼다. 저장 경로는 권별 파일이므로 표시 이름의 문제가 아니다.
    ⑦ 잘린 답에서 건진 부분 결과가 «완료»로만 보였다 — 생성기가 붙인 진단이 응답까지 와야 한다.
    ⑧ 유형은 범주에서 정한다고 문서에 적어 두고, 사전 필드만 바꾸는 저장은 옛 유형을 남겼다.
"""

from __future__ import annotations

import asyncio

import pytest

import app.routers.annotation as R
from core.annotation import add_annotation, load_annotations, save_annotations
from tests.test_annotation_router_merge import (
    TEXT,
    _fake_request,
    _labels,
    _llm_item,
    _manual,
    _put_l4,
    make_interp,
)


@pytest.fixture
def interp(tmp_path, monkeypatch):
    return make_interp(tmp_path, monkeypatch)

# ──────────────────────────────────────
# ④ part_id "main" 고정
# ──────────────────────────────────────


def test_add_annotation_routes_to_requested_part(interp):
    body = R.AnnotationAddRequest(
        target={"start": 0, "end": 0},
        type="person",
        content={"label": "둘째 권", "description": "", "references": []},
    )
    resp = asyncio.run(R.api_add_annotation("interp1", 1, "b1", body, part_id="vol2"))
    assert resp.status_code == 201, resp.body

    assert _labels(interp, "vol2", 1, "b1") == ["둘째 권"]
    assert _labels(interp, "main", 1, "b1") == [], "둘째 권 주석이 main 파일에 들어갔다"


def test_stage1_reads_and_writes_requested_part(interp, monkeypatch):
    _put_l4(interp, "vol2", 1, "b1")  # main에는 L4가 없다 — main으로 읽으면 404

    async def fake(**kw):
        assert kw["original_text"] == TEXT
        return [_llm_item("from_original")]

    monkeypatch.setattr(R, "generate_stage1_from_original", fake)
    resp = asyncio.run(
        R.api_dict_generate_stage1(
            "interp1", 1, _fake_request(), R.DictStageRequest(block_id="b1"), part_id="vol2"
        )
    )
    assert isinstance(resp, dict), getattr(resp, "body", resp)
    assert _labels(interp, "vol2", 1, "b1") == ["丙丁"]
    assert _labels(interp, "main", 1, "b1") == []


# ──────────────────────────────────────
# ⑦ 부분 복구·거부가 응답에 실린다
# ──────────────────────────────────────


def test_stage1_response_carries_parse_diagnostics(interp, monkeypatch):
    from core.annotation_dict_llm import GeneratedAnnotations

    _put_l4(interp, "main", 1, "b1")

    async def fake(**kw):
        return GeneratedAnnotations(
            [_llm_item("from_original")],
            diagnostics={"parse_status": "recovered", "parsed_items": 3, "rejected_items": 2},
        )

    monkeypatch.setattr(R, "generate_stage1_from_original", fake)
    resp = asyncio.run(
        R.api_dict_generate_stage1(
            "interp1", 1, _fake_request(), R.DictStageRequest(block_id="b1"), part_id="main"
        )
    )
    assert isinstance(resp, dict), getattr(resp, "body", resp)
    assert resp["diagnostics"]["parse_status"] == "recovered"
    assert resp["diagnostics"]["rejected_items"] == 2


# ──────────────────────────────────────
# ⑧ 범주를 바꾸면 유형도 따라간다
# ──────────────────────────────────────


def test_update_dictionary_category_refreshes_type(interp):
    data = load_annotations(interp, "main", 1)
    ann = add_annotation(data, "b1", _manual(0, "王戎", "person"))
    ann["dictionary"] = {"headword": "王戎", "dictionary_meaning": "사람", "category": "Person"}
    save_annotations(interp, "main", 1, data)

    body = R.AnnotationUpdateRequest(
        dictionary={"headword": "王戎", "dictionary_meaning": "땅 이름", "category": "Place"}
    )
    resp = asyncio.run(R.api_update_annotation("interp1", 1, "b1", ann["id"], body, part_id="main"))
    assert isinstance(resp, dict), getattr(resp, "body", resp)
    assert resp["type"] == "place"

    saved = load_annotations(interp, "main", 1)["blocks"][0]["annotations"][0]
    assert saved["type"] == "place"
    assert saved["dictionary"]["category"] == "Place"


def test_update_dictionary_same_category_keeps_hand_picked_type(interp):
    """범주가 그대로면 사람이 고른 유형(allusion 등)을 건드리지 않는다."""
    data = load_annotations(interp, "main", 1)
    ann = add_annotation(data, "b1", _manual(0, "고사", "allusion"))
    ann["dictionary"] = {"headword": "고사", "dictionary_meaning": "…", "category": "Event"}
    save_annotations(interp, "main", 1, data)

    body = R.AnnotationUpdateRequest(
        dictionary={"headword": "고사", "dictionary_meaning": "고친 뜻", "category": "Event"}
    )
    resp = asyncio.run(R.api_update_annotation("interp1", 1, "b1", ann["id"], body, part_id="main"))
    assert isinstance(resp, dict), getattr(resp, "body", resp)
    assert resp["type"] == "allusion"
