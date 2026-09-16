"""L5·L6·L7 저장이 원자적인가 — 쓰기 도중 죽어도 예전 파일이 남는다.

D-069. Codex 교차검증(2026-09-16) ②.

왜 이 시험이 필요한가:
    `docs/maintenance.md` 1.1은 JSON 저장에 `write_json_atomic()`을 요구한다. 그런데
    표점·현토·번역·주석 저장 함수 넷은 `Path.write_text()`로 바로 덮어썼다 — 먼저 0바이트로
    자르고 쓰므로, 그 사이에 디스크 부족·강제 종료가 나면 연구자가 쌓아 온 주석 파일이 빈 파일이
    된다. 스키마 검증은 이 실패를 막지 못한다(검증은 쓰기 전이다).

    시험은 `os.replace`를 죽여 «임시 파일에는 다 썼는데 갈아 끼우는 순간 죽는» 상황을 만든다.
    write_text 경로는 os.replace를 부르지 않으므로 예외 없이 새 내용으로 덮어써 이 시험이 실패한다.
"""

from __future__ import annotations

import json

import pytest

from core.annotation import load_annotations, save_annotations
from core.hyeonto import save_hyeonto
from core.punctuation import save_punctuation
from core.translation import save_translations


def _annotation_page(label: str) -> dict:
    return {
        "part_id": "main",
        "page_number": 1,
        "schema_version": "2.0",
        "blocks": [
            {
                "block_id": "b1",
                "annotations": [
                    {
                        "id": "ann_1",
                        "target": {"start": 0, "end": 1},
                        "type": "person",
                        "content": {"label": label, "description": "", "references": []},
                        "annotator": {"type": "human", "model": None, "draft_id": None},
                        "status": "accepted",
                        "reviewed_by": None,
                        "reviewed_at": None,
                    }
                ],
            }
        ],
    }


def _translation_page(text: str) -> dict:
    return {
        "part_id": "main",
        "page_number": 1,
        "translations": [
            {
                "id": "tr_001",
                "source": {"block_id": "b1", "start": 0, "end": 3},
                "source_text": "甲乙丙丁",
                "target_language": "ko",
                "translation": text,
                "translator": {"type": "human", "model": None, "draft_id": None},
                "status": "draft",
                "reviewed_by": None,
                "reviewed_at": None,
            }
        ],
    }


def _punctuation_block(after: str) -> dict:
    return {
        "block_id": "b1",
        "marks": [
            {"id": "pm_001", "target": {"start": 3, "end": 3}, "before": None, "after": after}
        ],
    }


def _hyeonto_block(text: str) -> dict:
    return {
        "block_id": "b1",
        "annotations": [
            {
                "id": "ht_001",
                "target": {"start": 0, "end": 1},
                "position": "after",
                "text": text,
                "category": None,
            }
        ],
    }


CASES = [
    ("annotation", save_annotations, _annotation_page("첫 저장"), _annotation_page("둘째 저장")),
    (
        "translation",
        save_translations,
        _translation_page("첫 번역"),
        _translation_page("둘째 번역"),
    ),
    ("punctuation", save_punctuation, _punctuation_block("，"), _punctuation_block("。")),
    ("hyeonto", save_hyeonto, _hyeonto_block("은"), _hyeonto_block("는")),
]


@pytest.mark.parametrize("name,save,first,second", CASES, ids=[c[0] for c in CASES])
def test_failed_save_keeps_previous_file(tmp_path, monkeypatch, name, save, first, second):
    interp = tmp_path / "interp"
    interp.mkdir()
    path = save(interp, "main", 1, first)
    before = json.loads(path.read_text(encoding="utf-8"))

    def boom(src, dst):
        raise OSError("디스크가 가득 찼습니다")

    monkeypatch.setattr("os.replace", boom)
    with pytest.raises(OSError):
        save(interp, "main", 1, second)

    assert json.loads(path.read_text(encoding="utf-8")) == before, f"{name}: 예전 내용이 깨졌다"
    leftovers = [p.name for p in path.parent.iterdir() if p.name != path.name]
    assert leftovers == [], f"{name}: 임시 파일이 남았다: {leftovers}"


@pytest.mark.parametrize("name,save,first,second", CASES, ids=[c[0] for c in CASES])
def test_successful_save_round_trips(tmp_path, name, save, first, second):
    """평범한 저장은 그대로 읽혀야 한다 — 원자적 저장기로 바꿔도 내용·개행은 같다."""
    interp = tmp_path / "interp"
    interp.mkdir()
    path = save(interp, "main", 1, second)
    raw = path.read_text(encoding="utf-8")
    assert json.loads(raw) == second
    assert raw.endswith("\n") and "\r\n" not in raw


def test_annotation_round_trip_through_loader(tmp_path):
    interp = tmp_path / "interp"
    interp.mkdir()
    save_annotations(interp, "main", 1, _annotation_page("라운드트립"))
    loaded = load_annotations(interp, "main", 1)
    assert loaded["blocks"][0]["annotations"][0]["content"]["label"] == "라운드트립"
