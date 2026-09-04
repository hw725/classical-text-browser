"""내용 트리 테스트 (D-085 1단계 → D-092 경계 목록 위의 보기 → B-004 문헌 > 권 > 단위).

무엇을 고정하는가:
  - 문헌 > 권 > 단위. 단위는 권 안에서 원본 위치 순이다 (Work로 묶지 않는다 — B-004)
  - 단위의 pages는 본문이 있는 쪽들이다(경계 사이의 L4 쪽). 두 쪽에 걸친 단위는 둘이다
  - 다른 문헌의 편성은 섞이지 않는다 (D-097 — 편성은 문헌의 것)
  - 미리보기는 L4에서 잘라 온 본문의 첫 글자들이다 — 본문은 저장하지 않는다(D-092)
  - 층위(level)와 제목이 항목에 붙는다

왜 서고 전체를 만드는가: 단위의 본문은 경계 목록만으로는 나오지 않고 원본 문헌의 L4에서
잘라 온다. 그래서 픽스처가 documents/{doc}/L4_text/pages 까지 갖춰야 한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.core import boundaries as B
from src.core.entity import doc_contents

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


def _lib(tmp_path: Path) -> Path:
    lib = tmp_path / "lib"
    _doc(lib, "d1", {3: P3, 4: P4, 7: P7})
    _doc(lib, "d2", {1: "다른 문헌"})
    # 파일에는 뒤섞어 넣어도 위치순으로 읽힌다. b2는 3쪽 둘째 행부터 7쪽 앞까지(두 쪽에 걸친다)
    b2 = B.new_boundary({"page": 3, "line": 1, "offset": 0}, title="裴楷", boundary_id="b2")
    b1 = B.new_boundary({"page": 3, "line": 0, "offset": 0}, title="王戎", boundary_id="b1")
    b9 = B.new_boundary({"page": 7, "line": 0, "offset": 0}, title="孔明", boundary_id="b9")
    b9["level"] = 2  # 3으로 두면 b2(층위 2) 안의 조각이 되어 b2가 7쪽까지 이어진다
    B.save_doc_boundaries(
        lib / "documents" / "d1",
        {"document_id": "d1", "part_id": "v1", "boundaries": [b2, b1, b9]},
    )
    other = B.new_boundary({"page": 1, "line": 0, "offset": 0}, title="다른", boundary_id="other")
    B.save_doc_boundaries(
        lib / "documents" / "d2",
        {"document_id": "d2", "part_id": "v1", "boundaries": [other]},
    )
    return lib


def _tree(tmp_path: Path, doc_id: str = "d1") -> dict:
    return doc_contents(_lib(tmp_path) / "documents" / doc_id, doc_id)


class TestListContents:
    def test_document_part_unit(self, tmp_path):
        """문헌 > 권 > 단위. 단위는 권 안에서 원본 위치 순이다 (B-004)."""
        tree = _tree(tmp_path)
        assert tree["document_id"] == "d1"
        assert [p["part_id"] for p in tree["parts"]] == ["v1"]
        part = tree["parts"][0]
        assert [u["id"] for u in part["units"]] == ["b1", "b2", "b9"]
        assert part["unit_count"] == 3 and tree["total_units"] == 3
        # 차례는 권 안에서 0부터 — Work마다 따로 세지 않는다
        assert [u["sequence_index"] for u in part["units"]] == [0, 1, 2]

    def test_pages_span_and_level(self, tmp_path):
        units = {u["id"]: u for u in _tree(tmp_path)["parts"][0]["units"]}
        b2 = units["b2"]
        assert [p["page"] for p in b2["pages"]] == [3, 4]
        assert b2["pages"][0] == {"page": 3, "part_id": "v1", "layout_block_ids": []}
        assert b2["level"] == 2 and b2["title"] == "裴楷"
        assert units["b1"]["pages"] == [{"page": 3, "part_id": "v1", "layout_block_ids": []}]
        assert units["b9"]["level"] == 2

    def test_preview_and_count_come_from_l4(self, tmp_path):
        units = {u["id"]: u for u in _tree(tmp_path)["parts"][0]["units"]}
        assert units["b2"]["preview"] == "裴楷清通王戎簡要續" and units["b2"]["char_count"] == 9
        assert units["b1"]["preview"] == "王戎簡要" and units["b1"]["char_count"] == 4

    def test_another_documents_composition_does_not_leak(self, tmp_path):
        """편성은 문헌마다 따로다 (D-097). d2의 「other」는 d1 트리에 없다."""
        tree = _tree(tmp_path)
        assert "other" not in [u["id"] for p in tree["parts"] for u in p["units"]]
        assert _tree(tmp_path, "d2")["total_units"] == 1

    def test_empty_document(self, tmp_path):
        tree = doc_contents(tmp_path / "없는문헌", "x")
        assert tree == {"document_id": "x", "title": "x", "parts": [], "total_units": 0}
