"""내용 트리 테스트 (D-085 1단계 → D-092 경계 목록 위의 보기).

무엇을 고정하는가:
  - Work → 단위를 원본 위치 순으로 묶는다. Work가 없는 단위는 unassigned로
  - 단위의 pages는 본문이 있는 쪽들이다(경계 사이의 L4 쪽). 두 쪽에 걸친 단위는 둘이다
  - document_id 필터가 다른 문헌의 단위를 걸러낸다
  - 미리보기는 L4에서 잘라 온 본문의 첫 글자들이다 — 본문은 저장하지 않는다(D-092)
  - 층위(level)와 제목이 항목에 붙는다

왜 서고 전체를 만드는가: 단위의 본문은 경계 목록만으로는 나오지 않고 원본 문헌의 L4에서
잘라 온다. 그래서 픽스처가 documents/{doc}/L4_text/pages 까지 갖춰야 한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.core import boundaries as B
from src.core.entity import list_contents

P3 = "王戎簡要\n裴楷清通"
P4 = "王戎簡要續"
P7 = "孔明臥龍"


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _doc(lib: Path, doc_id: str, pages: dict[int, str]) -> None:
    doc = lib / "documents" / doc_id
    _write(
        doc / "manifest.json",
        {"document_id": doc_id, "parts": [{"part_id": "v1", "page_count": max(pages)}]},
    )
    for n, text in pages.items():
        p = doc / "L4_text" / "pages" / f"v1_page_{n:03d}.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def _interp(tmp_path: Path) -> Path:
    lib = tmp_path / "lib"
    _doc(lib, "d1", {3: P3, 4: P4, 7: P7})
    _doc(lib, "d2", {1: "다른 문헌"})
    root = lib / "interpretations" / "i"
    _write(
        root / "core_entities" / "works" / "w1.json",
        {"id": "w1", "title": "蒙求", "author": "李瀚"},
    )
    _write(root / "core_entities" / "works" / "w2.json", {"id": "w2", "title": "빈 작품"})
    # 파일에는 뒤섞어 넣어도 위치순으로 읽힌다. b2는 3쪽 둘째 행부터 7쪽 앞까지(두 쪽에 걸친다)
    b2 = B.new_boundary(
        {"page": 3, "line": 1, "offset": 0}, title="裴楷", work_id="w1", boundary_id="b2"
    )
    b1 = B.new_boundary(
        {"page": 3, "line": 0, "offset": 0}, title="王戎", work_id="w1", boundary_id="b1"
    )
    b9 = B.new_boundary(
        {"page": 7, "line": 0, "offset": 0}, title="孔明", work_id="w-gone", boundary_id="b9"
    )
    b9["level"] = 2  # 3으로 두면 b2(층위 2) 안의 조각이 되어 b2가 7쪽까지 이어진다
    B.save_boundaries(root, {"document_id": "d1", "part_id": "v1", "boundaries": [b2, b1, b9]})
    other = B.new_boundary(
        {"page": 1, "line": 0, "offset": 0}, title="다른", work_id="w1", boundary_id="other"
    )
    B.save_boundaries(root, {"document_id": "d2", "part_id": "v1", "boundaries": [other]})
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

    def test_pages_span_and_level(self, tmp_path):
        tree = list_contents(_interp(tmp_path), "d1")
        b2 = next(b for w in tree["works"] for b in w["blocks"] if b["id"] == "b2")
        assert [p["page"] for p in b2["pages"]] == [3, 4]
        assert b2["pages"][0] == {"page": 3, "part_id": "v1", "layout_block_ids": []}
        assert b2["level"] == 2 and b2["title"] == "裴楷"
        b1 = next(b for w in tree["works"] for b in w["blocks"] if b["id"] == "b1")
        assert b1["pages"] == [{"page": 3, "part_id": "v1", "layout_block_ids": []}]
        assert tree["unassigned"][0]["level"] == 2

    def test_preview_and_count_come_from_l4(self, tmp_path):
        tree = list_contents(_interp(tmp_path), "d1")
        b2 = next(b for w in tree["works"] for b in w["blocks"] if b["id"] == "b2")
        assert b2["preview"] == "裴楷清通王戎簡要續" and b2["char_count"] == 9
        b1 = next(b for w in tree["works"] for b in w["blocks"] if b["id"] == "b1")
        assert b1["preview"] == "王戎簡要" and b1["char_count"] == 4

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
