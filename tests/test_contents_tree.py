"""내용 트리 테스트 (D-085 1단계).

무엇을 고정하는가:
  - Work → TextBlock을 sequence_index 순으로 묶는다. Work가 없는 블록은 unassigned로
  - 블록의 pages는 source_refs를 쪽 번호로 묶은 것이고, 두 쪽에 걸친 블록은 둘이다
  - part_id는 참조에 있을 때만 채워진다 (예전 참조는 null)
  - document_id 필터가 다른 문헌의 블록을 걸러낸다
  - 미리보기는 공백을 걷어 낸 첫 글자들이다
  - 저장 형식은 건드리지 않는다 — 읽기만 한다
"""

from __future__ import annotations

import json
from pathlib import Path

from src.core.entity import list_contents


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _interp(tmp_path: Path) -> Path:
    root = tmp_path / "interp"
    _write(
        root / "core_entities" / "works" / "w1.json",
        {"id": "w1", "title": "蒙求", "author": "李瀚"},
    )
    _write(root / "core_entities" / "works" / "w2.json", {"id": "w2", "title": "빈 작품"})
    # 순서가 뒤섞인 블록 셋 + 두 쪽에 걸친 블록 + Work 없는 블록 + 다른 문헌 블록
    _write(
        root / "core_entities" / "blocks" / "b2.json",
        {
            "id": "b2",
            "work_id": "w1",
            "sequence_index": 2,
            "original_text": "裴楷 清通\n王戎簡要",
            "source_refs": [
                {"document_id": "d1", "part_id": "v1", "page": 3, "layout_block_id": "p03_b02"},
                {"document_id": "d1", "part_id": "v1", "page": 4, "layout_block_id": "p04_b01"},
            ],
        },
    )
    _write(
        root / "core_entities" / "blocks" / "b1.json",
        {
            "id": "b1",
            "work_id": "w1",
            "sequence_index": 1,
            "original_text": "王戎簡要",
            "source_ref": {"document_id": "d1", "page": 3, "layout_block_id": "p03_b01"},
        },
    )
    _write(
        root / "core_entities" / "blocks" / "b9.json",
        {
            "id": "b9",
            "work_id": "w-gone",
            "sequence_index": None,
            "original_text": "孔明臥龍",
            "source_refs": [{"document_id": "d1", "page": 7, "layout_block_id": "p07_b01"}],
        },
    )
    _write(
        root / "core_entities" / "blocks" / "other.json",
        {
            "id": "other",
            "work_id": "w1",
            "sequence_index": 0,
            "original_text": "다른 문헌",
            "source_refs": [{"document_id": "d2", "page": 1, "layout_block_id": "x"}],
        },
    )
    return root


class TestListContents:
    def test_grouping_and_order(self, tmp_path):
        tree = list_contents(_interp(tmp_path), "d1")
        works = {w["id"]: w for w in tree["works"]}
        assert [b["id"] for b in works["w1"]["blocks"]] == ["b1", "b2"]
        assert works["w1"]["title"] == "蒙求" and works["w1"]["block_count"] == 2
        assert works["w2"]["block_count"] == 0
        # 빈 Work는 뒤로
        assert tree["works"][-1]["id"] == "w2"
        assert [b["id"] for b in tree["unassigned"]] == ["b9"]
        assert tree["total_blocks"] == 3

    def test_pages_span_and_part_id(self, tmp_path):
        tree = list_contents(_interp(tmp_path), "d1")
        b2 = next(b for w in tree["works"] for b in w["blocks"] if b["id"] == "b2")
        assert [p["page"] for p in b2["pages"]] == [3, 4]
        assert b2["pages"][0] == {"page": 3, "part_id": "v1", "layout_block_ids": ["p03_b02"]}
        b1 = next(b for w in tree["works"] for b in w["blocks"] if b["id"] == "b1")
        assert b1["pages"] == [{"page": 3, "part_id": None, "layout_block_ids": ["p03_b01"]}]

    def test_preview_and_count(self, tmp_path):
        tree = list_contents(_interp(tmp_path), "d1")
        b2 = next(b for w in tree["works"] for b in w["blocks"] if b["id"] == "b2")
        assert b2["preview"] == "裴楷清通王戎簡要" and b2["char_count"] == 8

    def test_document_filter(self, tmp_path):
        root = _interp(tmp_path)
        all_tree = list_contents(root, None)
        assert all_tree["total_blocks"] == 4
        d2 = list_contents(root, "d2")
        assert d2["total_blocks"] == 1
        assert d2["works"][0]["blocks"][0]["id"] == "other"

    def test_empty_store(self, tmp_path):
        tree = list_contents(tmp_path / "empty", None)
        assert tree == {"works": [], "unassigned": [], "total_blocks": 0}
