"""L7 사전 생성 라우트 — LLM 대기 중 들어온 수동 주석을 잃지 않는다.

Codex 교차검증(2026-09-16, 기준 a0f47a6) ①의 재현·회귀 시험이다. 같은 라우트의 권(part_id)·
진단·유형 갱신(④·⑦·⑧)은 `test_annotation_router_part_and_type.py`에 있고 이 파일의 픽스처를
빌려 쓴다.

왜 이 시험이 필요한가:
    사전 생성 라우트는 《쪽 파일을 읽고 → LLM을 기다리고(수 초~수십 초) → 아까 읽은 데이터에
    결과를 얹어 저장》했다. 기다리는 동안 같은 쪽에 사람이 넣은 주석은 아까 읽은 데이터에 없으므로
    저장 순간 사라졌다 — 오류도 없이. 저장 직전에 파일을 **다시 읽어** 지금 상태 위에 병합해야 한다.
"""

from __future__ import annotations

import asyncio

import pytest
from starlette.requests import Request

import app.routers.annotation as R
from core.annotation import add_annotation, load_annotations, save_annotations
from core.annotation_dict_llm import _build_annotation_from_raw
from core.translation import save_translations

TEXT = "甲乙丙丁"


def _fake_request() -> Request:
    return Request(
        {"type": "http", "method": "POST", "path": "/", "query_string": b"", "headers": []}
    )


def make_interp(tmp_path, monkeypatch):
    """서고·해석 저장소를 임시 폴더로 돌린 라우터 이름 공간.

    다른 시험 모듈(part_and_type)도 이것으로 자기 픽스처를 만든다.
    """
    lib = tmp_path / "lib"
    interp_path = lib / "interpretations" / "interp1"
    interp_path.mkdir(parents=True)
    monkeypatch.setattr(R, "get_library_path", lambda: lib)
    monkeypatch.setattr(R, "require_repo_path", lambda t, i: lib / t / i)
    monkeypatch.setattr(R, "_get_llm_router", lambda: object())
    monkeypatch.setattr(R, "git_commit_interpretation", lambda *a, **k: None)
    # 원문은 그 쪽의 편성 단위(경계 목록에서 만든 보기)에서 온다 — 라우트의 _load_page_blocks가
    # list_entities(…, "unit")를 읽는다. _put_l4가 여기에 단위를 넣는다(B-022 뒤 자리).
    _UNITS[str(interp_path)] = []

    def fake_list_entities(path, kind, *a, **k):
        return list(_UNITS.get(str(path), [])) if kind == "unit" else []

    monkeypatch.setattr(R, "list_entities", fake_list_entities)
    return interp_path


# 픽스처별 단위 목록(해석 저장소 경로 → 단위들)
_UNITS: dict[str, list[dict]] = {}


@pytest.fixture
def interp(tmp_path, monkeypatch):
    return make_interp(tmp_path, monkeypatch)


def _put_l4(interp_path, part_id: str, page: int, block_id: str, text: str = TEXT) -> None:
    """그 쪽에 원문 text를 가진 편성 단위 하나를 둔다(id = block_id).

    예전에는 해석 저장소의 L4_text/main_text/*_text.json에 썼다 — 실제 서고에는 생기지 않는
    자리라, 라우트가 그곳을 읽던 동안 시험만 통과하고 실제로는 늘 폴백으로 갔다(2026-10-11 B-022).
    """
    _UNITS.setdefault(str(interp_path), []).append(
        {
            "id": block_id,
            "original_text": text,
            "source_ref": {"page": page, "part_id": part_id},
        }
    )


def _put_l6(interp_path, part_id: str, page: int, block_id: str) -> None:
    save_translations(
        interp_path,
        part_id,
        page,
        {
            "part_id": part_id,
            "page_number": page,
            "translations": [
                {
                    "id": "tr_001",
                    "source": {"block_id": block_id, "start": 0, "end": 3},
                    "source_text": TEXT,
                    "target_language": "ko",
                    "translation": "갑을병정.",
                    "translator": {"type": "human", "model": None, "draft_id": None},
                    "status": "draft",
                    "reviewed_by": None,
                    "reviewed_at": None,
                }
            ],
        },
    )


def _manual(start: int, label: str, ann_type: str = "person") -> dict:
    return {
        "target": {"start": start, "end": start},
        "type": ann_type,
        "content": {"label": label, "description": "", "references": []},
        "annotator": {"type": "human", "model": None, "draft_id": None},
        "status": "accepted",
        "reviewed_by": None,
        "reviewed_at": None,
    }


def _llm_item(stage: str, start: int = 2, end: int = 3, headword: str = "丙丁") -> dict:
    ann = _build_annotation_from_raw(
        raw={
            "target": {"start": start, "end": end},
            "content": {"label": headword, "description": "설명"},
            "dictionary": {"headword": headword, "dictionary_meaning": "뜻", "category": "Person"},
        },
        text_len=len(TEXT),
        response_model="mock",
        draft_id="draft_x",
        stage=stage,
        original_text=TEXT,
        translation_text=None,
    )
    assert ann is not None
    return ann


def _labels(interp_path, part_id: str, page: int, block_id: str) -> list[str]:
    data = load_annotations(interp_path, part_id, page)
    for b in data["blocks"]:
        if b["block_id"] == block_id:
            return [a["content"]["label"] for a in b["annotations"]]
    return []


# ──────────────────────────────────────
# ① 생성 대기 중 수동 주석 유실
# ──────────────────────────────────────


def _interleaving_generator(interp_path, stage: str, part_id: str = "main"):
    """LLM을 흉내 낸다 — 기다리는 동안 《다른 요청》이 같은 쪽에 수동 주석을 저장한다."""

    async def fake(**kw):
        data = load_annotations(interp_path, part_id, 1)
        add_annotation(data, "b1", _manual(0, "manual_during_llm"))
        save_annotations(interp_path, part_id, 1, data)
        await asyncio.sleep(0)
        return [_llm_item(stage)]

    return fake


def test_stage1_keeps_manual_annotation_added_during_llm_wait(interp, monkeypatch):
    _put_l4(interp, "main", 1, "b1")
    monkeypatch.setattr(
        R, "generate_stage1_from_original", _interleaving_generator(interp, "from_original")
    )

    resp = asyncio.run(
        R.api_dict_generate_stage1(
            "interp1", 1, _fake_request(), R.DictStageRequest(block_id="b1"), part_id="main"
        )
    )
    assert isinstance(resp, dict), getattr(resp, "body", resp)

    labels = _labels(interp, "main", 1, "b1")
    assert "manual_during_llm" in labels, "대기 중 넣은 수동 주석이 사라졌다"
    assert "丙丁" in labels


def test_stage2_keeps_manual_annotation_added_during_llm_wait(interp, monkeypatch):
    _put_l4(interp, "main", 1, "b1")
    _put_l6(interp, "main", 1, "b1")
    monkeypatch.setattr(
        R,
        "generate_stage2_from_translation",
        _interleaving_generator(interp, "from_translation"),
    )

    resp = asyncio.run(
        R.api_dict_generate_stage2(
            "interp1", 1, _fake_request(), R.DictStageRequest(block_id="b1"), part_id="main"
        )
    )
    assert isinstance(resp, dict), getattr(resp, "body", resp)
    labels = _labels(interp, "main", 1, "b1")
    assert "manual_during_llm" in labels
    assert "丙丁" in labels


def test_stage3_keeps_manual_annotation_added_during_llm_wait(interp, monkeypatch):
    _put_l4(interp, "main", 1, "b1")
    _put_l6(interp, "main", 1, "b1")
    monkeypatch.setattr(
        R, "generate_stage3_from_both", _interleaving_generator(interp, "from_both")
    )

    resp = asyncio.run(
        R.api_dict_generate_stage3(
            "interp1", 1, _fake_request(), R.DictStageRequest(block_id="b1"), part_id="main"
        )
    )
    assert isinstance(resp, dict), getattr(resp, "body", resp)
    labels = _labels(interp, "main", 1, "b1")
    assert "manual_during_llm" in labels
    assert "丙丁" in labels


def test_batch_keeps_manual_annotation_added_during_llm_wait(interp, monkeypatch):
    """일괄 생성도 같은 구조다 — 쪽 데이터를 먼저 읽고 블록마다 기다린 뒤 한 번에 저장한다."""
    _put_l4(interp, "main", 1, "b1")
    _put_l6(interp, "main", 1, "b1")
    monkeypatch.setattr(
        R, "generate_stage3_from_both", _interleaving_generator(interp, "from_both")
    )

    resp = asyncio.run(
        R.api_dict_generate_batch("interp1", R.DictBatchRequest(pages=[1]), part_id="main")
    )
    assert isinstance(resp, dict), getattr(resp, "body", resp)
    assert resp["errors"] == []
    labels = _labels(interp, "main", 1, "b1")
    assert "manual_during_llm" in labels
    assert "丙丁" in labels


def test_stage_result_is_merged_not_duplicated(interp, monkeypatch):
    """다시 읽어 병합할 때 LLM 항목이 두 번 들어가면 안 된다."""
    _put_l4(interp, "main", 1, "b1")

    async def fake(**kw):
        return [_llm_item("from_original")]

    monkeypatch.setattr(R, "generate_stage1_from_original", fake)
    asyncio.run(
        R.api_dict_generate_stage1(
            "interp1", 1, _fake_request(), R.DictStageRequest(block_id="b1"), part_id="main"
        )
    )
    assert _labels(interp, "main", 1, "b1") == ["丙丁"]
