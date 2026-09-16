"""L5 표점·현토와 L6 번역 라우트가 권(part_id)을 고정하지 않는다 (D-127 후속, 2026-09-16).

왜 이 시험이 필요한가:
    주석(L7) 라우터의 `"main"` 고정을 풀면서(Codex 교차검증 ④) 같은 고정이 reading.py에도 열 곳 남아
    있었다. 다권본의 둘째 권을 열고 표점·현토·번역을 저장하면 첫째 권 파일(`main_page_…`)에
    들어간다.
    저장 경로는 권별 파일이므로 표시 이름의 문제가 아니다.
"""

from __future__ import annotations

import asyncio

import pytest

import app.routers.reading as R
from core.hyeonto import load_hyeonto
from core.punctuation import load_punctuation
from core.translation import load_translations


@pytest.fixture
def interp(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    interp_path = lib / "interpretations" / "interp1"
    interp_path.mkdir(parents=True)
    monkeypatch.setattr(R, "get_library_path", lambda: lib)
    monkeypatch.setattr(R, "require_repo_path", lambda t, i: lib / t / i)
    monkeypatch.setattr(R, "git_commit_interpretation", lambda *a, **k: None)
    return interp_path


def _ok(resp):
    assert not hasattr(resp, "status_code") or resp.status_code < 300, getattr(resp, "body", resp)
    return resp


def test_punctuation_save_and_get_use_requested_part(interp):
    body = R.PunctuationSaveRequest(
        block_id="b1",
        marks=[{"id": "pm_1", "target": {"start": 1, "end": 1}, "before": None, "after": "。"}],
    )
    _ok(asyncio.run(R.api_save_punctuation("interp1", 1, body, part_id="vol2")))

    assert load_punctuation(interp, "vol2", 1, "b1")["marks"][0]["after"] == "。"
    assert load_punctuation(interp, "main", 1, "b1")["marks"] == [], "둘째 권 표점이 main에"

    got = _ok(asyncio.run(R.api_get_punctuation("interp1", 1, block_id="b1", part_id="vol2")))
    assert got["marks"][0]["after"] == "。"


def test_add_mark_uses_requested_part(interp):
    body = R.MarkAddRequest(target={"start": 2, "end": 2}, after="，")
    _ok(asyncio.run(R.api_add_mark("interp1", 1, "b1", body, part_id="vol2")))
    assert load_punctuation(interp, "vol2", 1, "b1")["marks"][0]["after"] == "，"
    assert load_punctuation(interp, "main", 1, "b1")["marks"] == []


def test_hyeonto_save_uses_requested_part(interp):
    body = R.HyeontoSaveRequest(
        block_id="b1",
        annotations=[
            {
                "id": "ht_1",
                "target": {"start": 0, "end": 1},
                "position": "after",
                "text": "은",
                "category": None,
            }
        ],
    )
    _ok(asyncio.run(R.api_save_hyeonto("interp1", 1, body, part_id="vol2")))
    assert load_hyeonto(interp, "vol2", 1, "b1")["annotations"][0]["text"] == "은"
    assert load_hyeonto(interp, "main", 1, "b1")["annotations"] == []


def test_translation_add_uses_requested_part(interp):
    body = R.TranslationAddRequest(
        source={"block_id": "b1", "start": 0, "end": 3},
        source_text="甲乙丙丁",
        translation="갑을병정.",
    )
    _ok(asyncio.run(R.api_add_translation("interp1", 1, body, part_id="vol2")))
    assert load_translations(interp, "vol2", 1)["translations"][0]["translation"] == "갑을병정."
    assert load_translations(interp, "main", 1)["translations"] == []


def test_no_route_in_reading_keeps_main_hardcoded():
    """코드 층의 회귀 잠금 — 라우트 본문에 `part_id = "main"`이 다시 생기면 잡는다."""
    import inspect

    src = inspect.getsource(R)
    assert 'part_id = "main"' not in src
