"""경계 목록(D-092) — 단위의 정본. 순수 계산·파일·마이그레이션·entity 보기를 고정한다.

왜 이 시험이 필요한가:
    단위를 없애고 경계 목록으로 바꾸는 것은 저장 형식 변경이다. «끝은 다음 경계가 정한다»,
    «id는 시작 경계에 붙는다», «층위 n을 손대도 더 얕은 층위의 id는 그대로», «옛 blocks/는 손실
    없이 옮겨진다»가 깨지면 관계·태그·표점 파일의 참조가 끊긴다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core import boundaries as B
from src.core.segmentation import Line

L0 = "○七日晴朝食後往訪金生歸路遇雨○八日雨終日在家讀書"
L1 = "夜半風止○九日晴與客論詩至暮"
L2 = "本文本文本文本文本文本文本文本文本文本文"
PAGE1 = "\n".join([L0, L1, L2])
K8 = L0.index("○八日")
K9 = L1.index("○九日")


def _lines():
    lines = [Line(1, 0, L0), Line(1, 1, L1), Line(1, 2, L2)]
    off = 0
    for ln in lines:
        ln.char_start = off
        off += len(ln.text) + 1
    return lines, {1: PAGE1}


def _data(*items):
    return {"document_id": "d", "part_id": "v1", "boundaries": list(items)}


class TestPositions:
    def test_char_and_position_round_trip(self):
        pt = {1: PAGE1}
        pos = B.position_from_char(pt, 1, len(L0) + 1 + K9)
        assert pos == {"page": 1, "line": 1, "offset": K9}
        assert B.char_from_position(pt, pos) == len(L0) + 1 + K9
        assert B.anchor_text_at(pt, pos) == L1[K9 : K9 + B.ANCHOR_TEXT_LEN]
        assert B.char_from_position(pt, {"page": 1, "line": 9, "offset": 0}) is None


class TestUnits:
    def test_end_is_next_boundary_of_same_or_shallower_level(self):
        lines, pt = _lines()
        b1 = B.new_boundary(
            {"page": 1, "line": 0, "offset": 0}, level=2, title="七日", page_texts=pt
        )
        b2 = B.new_boundary(
            {"page": 1, "line": 0, "offset": K8}, level=3, title="八日 조각", page_texts=pt
        )
        b3 = B.new_boundary(
            {"page": 1, "line": 1, "offset": K9}, level=2, title="九日", page_texts=pt
        )
        units = B.compute_units(_data(b1, b2, b3), lines, pt)
        by = {u["metadata"]["title"]: u for u in units}
        # 층위 2 단위 «七日»은 층위 3 경계를 건너뛰고 다음 층위 2 경계(九日) 앞까지
        assert by["七日"]["original_text"] == L0 + "\n" + L1[:K9]
        # 층위 3 조각은 다음 경계(층위 2도 «같은 층위 이상»)에서 끝난다
        assert by["八日 조각"]["original_text"] == L0[K8:] + "\n" + L1[:K9]
        assert by["九日"]["original_text"] == L1[K9:] + "\n" + L2
        assert by["九日"]["source_refs"][0]["char_range"] == [len(L0) + 1 + K9, len(PAGE1)]
        assert [u["sequence_index"] for u in units] == [0, 1, 2]
        assert (
            by["七日"]["metadata"]["level"] == 2
            and by["八日 조각"]["metadata"]["anchor"]["level"] == 3
        )

    def test_deprecated_boundary_makes_no_unit_and_does_not_end_others(self):
        lines, pt = _lines()
        b1 = B.new_boundary({"page": 1, "line": 0, "offset": 0}, title="a", page_texts=pt)
        b2 = B.new_boundary(
            {"page": 1, "line": 1, "offset": 0}, title="b", status="deprecated", page_texts=pt
        )
        units = B.compute_units(_data(b1, b2), lines, pt)
        assert [u["metadata"]["title"] for u in units] == ["a"]
        assert units[0]["original_text"] == PAGE1

    def test_missing_line_gives_empty_unit_not_crash(self):
        lines, pt = _lines()
        b = B.new_boundary({"page": 1, "line": 7, "offset": 0}, title="x")
        units = B.compute_units(_data(b), lines, pt)
        assert units[0]["original_text"] == "" and units[0]["source_refs"][0]["char_range"] is None


class TestCrud:
    def test_delete_merges_into_previous_and_keeps_front_id(self):
        lines, pt = _lines()
        a = B.new_boundary({"page": 1, "line": 0, "offset": 0}, title="a", page_texts=pt)
        b = B.new_boundary({"page": 1, "line": 1, "offset": 0}, title="b", page_texts=pt)
        data = _data(a, b)
        B.delete_boundary(data, b["id"])
        units = B.compute_units(data, lines, pt)
        assert [u["id"] for u in units] == [a["id"]] and units[0]["original_text"] == PAGE1

    def test_insert_splits_and_new_id_goes_to_back_part(self):
        lines, pt = _lines()
        a = B.new_boundary({"page": 1, "line": 0, "offset": 0}, title="a", page_texts=pt)
        data = _data(a)
        c = B.new_boundary({"page": 1, "line": 0, "offset": K8}, title="c", page_texts=pt)
        B.insert_boundary(data, c)
        units = B.compute_units(data, lines, pt)
        assert [u["id"] for u in units] == [a["id"], c["id"]]
        assert units[0]["original_text"] == L0[:K8] and units[1]["original_text"].startswith(
            "○八日"
        )

    def test_move_only_changes_start_and_neighbours_follow(self):
        lines, pt = _lines()
        a = B.new_boundary({"page": 1, "line": 0, "offset": 0}, title="a", page_texts=pt)
        b = B.new_boundary({"page": 1, "line": 1, "offset": 0}, title="b", page_texts=pt)
        data = _data(a, b)
        B.move_boundary(data, b["id"], {"page": 1, "line": 0, "offset": K8}, pt)
        units = B.compute_units(data, lines, pt)
        assert units[0]["original_text"] == L0[:K8]
        assert B.find_boundary(data, b["id"])["anchor_text"] == L0[K8 : K8 + B.ANCHOR_TEXT_LEN]

    def test_insert_duplicate_id_refused(self):
        a = B.new_boundary({"page": 1, "line": 0, "offset": 0}, boundary_id="x")
        data = _data(a)
        with pytest.raises(FileExistsError):
            B.insert_boundary(
                data, B.new_boundary({"page": 1, "line": 1, "offset": 0}, boundary_id="x")
            )


class TestRematch:
    def test_shifted_text_is_found_by_anchor_text(self):
        pt_old = {1: PAGE1}
        b = B.new_boundary(
            {"page": 1, "line": 1, "offset": K9}, title="九日", page_texts=pt_old, l4_commit="c1"
        )
        data = _data(b)
        # 교감으로 앞 행이 두 자 늘었다 — 오프셋은 틀리고 anchor_text는 그대로
        pt_new = {1: "\n".join([L0, "追記" + L1, L2])}
        n = B.rematch(data, pt_new, "c2")
        assert n == 1
        assert b["start"] == {"page": 1, "line": 1, "offset": K9 + 2} and b["l4_commit"] == "c2"
        assert b.get("anchor_status") != "stale"

    def test_vanished_anchor_is_marked_stale_not_moved(self):
        pt_old = {1: PAGE1}
        b = B.new_boundary({"page": 1, "line": 1, "offset": K9}, page_texts=pt_old, l4_commit="c1")
        data = _data(b)
        B.rematch(data, {1: "\n".join([L0, "全然別文", L2])}, "c2")
        assert b["anchor_status"] == "stale" and b["start"]["offset"] == K9

    def test_same_commit_is_untouched(self):
        b = B.new_boundary(
            {"page": 1, "line": 1, "offset": K9}, page_texts={1: PAGE1}, l4_commit="c1"
        )
        data = _data(b)
        assert B.rematch(data, {1: "\n".join([L0, "追記" + L1, L2])}, "c1") == 0


class TestFilesAndMigration:
    def _interp(self, tmp_path: Path):
        lib = tmp_path / "lib"
        doc = lib / "documents" / "d"
        (doc / "L4_text" / "pages").mkdir(parents=True)
        (doc / "manifest.json").write_text(
            json.dumps({"document_id": "d", "parts": [{"part_id": "v1", "page_count": 1}]}),
            encoding="utf-8",
        )
        (doc / "L4_text" / "pages" / "v1_page_001.txt").write_text(PAGE1, encoding="utf-8")
        interp = lib / "interpretations" / "i"
        (interp / "core_entities" / "blocks").mkdir(parents=True)
        return lib, interp

    def test_save_load_validates_and_sorts(self, tmp_path):
        _lib, interp = self._interp(tmp_path)
        b2 = B.new_boundary({"page": 1, "line": 1, "offset": 0}, title="b")
        b1 = B.new_boundary({"page": 1, "line": 0, "offset": 0}, title="a")
        B.save_boundaries(interp, _data(b2, b1))
        data = B.load_boundaries(interp, "d", "v1")
        assert [x["title"] for x in data["boundaries"]] == ["a", "b"]
        assert B.list_boundary_parts(interp) == [("d", "v1")]
        with pytest.raises(Exception):
            B.save_boundaries(interp, _data({"id": "x", "level": 2}))  # start·status 빠짐

    def test_migrate_keeps_ids_and_positions_and_renames_blocks(self, tmp_path):
        lib, interp = self._interp(tmp_path)
        blocks = interp / "core_entities" / "blocks"
        old = {
            "id": "11111111-1111-1111-1111-111111111111",
            "work_id": "22222222-2222-2222-2222-222222222222",
            "sequence_index": 1,
            "original_text": L1[K9:] + "\n" + L2,
            "source_refs": [
                {
                    "document_id": "d",
                    "part_id": "v1",
                    "page": 1,
                    "layout_block_id": None,
                    "char_range": [len(L0) + 1 + K9, len(PAGE1)],
                    "layer": "L4",
                }
            ],
            "status": "active",
            "metadata": {
                "part_id": "v1",
                "title": "九日",
                "kind": "date",
                "anchor": {"level": 2, "status": "approved", "confidence": 0.9, "l4_commit": "c0"},
            },
        }
        first = {
            **old,
            "id": "33333333-3333-3333-3333-333333333333",
            "sequence_index": 0,
            "original_text": L0 + "\n" + L1[:K9],
            "source_refs": [
                {
                    "document_id": "d",
                    "part_id": "v1",
                    "page": 1,
                    "layout_block_id": None,
                    "char_range": [0, len(L0) + 1 + K9],
                    "layer": "L4",
                }
            ],
            "metadata": {"part_id": "v1", "title": "七日"},
        }
        legacy = {
            **old,
            "id": "44444444-4444-4444-4444-444444444444",
            "status": "deprecated",
            "source_refs": [
                {
                    "document_id": "d",
                    "part_id": "v1",
                    "page": 1,
                    "layout_block_id": "p01_b01",
                    "char_range": None,
                    "layer": "L4",
                }
            ],
        }
        for blk in (old, first, legacy):
            (blocks / f"{blk['id']}.json").write_text(
                json.dumps(blk, ensure_ascii=False), encoding="utf-8"
            )
        assert B.needs_migration(interp)
        result = B.migrate_from_blocks(interp, lib)
        assert result["parts"] == [("d", "v1", 3)] and result["skipped"] == []
        assert not blocks.exists() and (interp / "core_entities" / "blocks_migrated_v1").exists()
        data = B.load_boundaries(interp, "d", "v1")
        ids = [b["id"] for b in data["boundaries"]]
        assert ids[0] == first["id"] and old["id"] in ids and legacy["id"] in ids
        nine = B.find_boundary(data, old["id"])
        assert nine["start"] == {"page": 1, "line": 1, "offset": K9} and nine["level"] == 2
        assert (
            nine["confidence"] == 0.9
            and nine["l4_commit"] == "c0"
            and nine["anchor_text"] == L1[K9 : K9 + 8]
        )
        # char_range 없는 옛 참조는 쪽 첫 행, deprecated는 단위를 만들지 않는다
        assert B.find_boundary(data, legacy["id"])["start"] == {"page": 1, "line": 0, "offset": 0}
        from src.core.segmentation import collect_document_lines

        lines, pt = collect_document_lines(lib / "documents" / "d", "v1", None)
        units = B.compute_units(data, lines, pt)
        assert [u["id"] for u in units] == [first["id"], old["id"]]
        assert units[1]["original_text"] == L1[K9:] + "\n" + L2  # 옛 본문과 같다 — 손실 없음
        assert not B.needs_migration(interp)


class TestEntityView:
    def test_entity_api_reads_and_writes_boundaries(self, tmp_path):
        from src.core import entity as E

        lib = tmp_path / "lib"
        doc = lib / "documents" / "d"
        (doc / "L4_text" / "pages").mkdir(parents=True)
        (doc / "manifest.json").write_text(
            json.dumps({"document_id": "d", "parts": [{"part_id": "v1", "page_count": 1}]}),
            encoding="utf-8",
        )
        (doc / "L4_text" / "pages" / "v1_page_001.txt").write_text(PAGE1, encoding="utf-8")
        interp = lib / "interpretations" / "i"
        (interp / "core_entities" / "works").mkdir(parents=True)
        created = E.create_entity(
            interp,
            "unit",
            {
                "work_id": "22222222-2222-2222-2222-222222222222",
                "sequence_index": 0,
                "original_text": "무시된다 — 본문은 L4에서 온다",
                "source_refs": [
                    {
                        "document_id": "d",
                        "part_id": "v1",
                        "page": 1,
                        "layout_block_id": None,
                        "char_range": [len(L0) + 1 + K9, len(PAGE1)],
                        "layer": "L4",
                    }
                ],
                "status": "draft",
                "metadata": {"part_id": "v1", "title": "九日", "anchor": {"level": 2}},
            },
        )
        assert created["file_path"] == "core_entities/boundaries/d__v1.json"
        assert not (interp / "core_entities" / "blocks").exists() or not list(
            (interp / "core_entities" / "blocks").glob("*.json")
        )
        got = E.get_entity(interp, "unit", created["id"])
        assert got["original_text"] == L1[K9:] + "\n" + L2 and got["metadata"]["title"] == "九日"
        assert E.list_entities(interp, "unit", {"status": "draft"})[0]["id"] == created["id"]
        E.update_entity(
            interp,
            "unit",
            created["id"],
            {"status": "active", "metadata": {"title": "九日談"}},
        )
        got2 = E.get_entity(interp, "unit", created["id"])
        assert got2["status"] == "active" and got2["metadata"]["title"] == "九日談"
        with pytest.raises(ValueError):
            E.update_entity(interp, "unit", created["id"], {"status": "draft"})  # 역전이 금지
        with pytest.raises(FileNotFoundError):
            E.get_entity(interp, "unit", "없는-id")
        tree = E.list_contents(interp, "d")
        assert tree["unassigned"][0]["level"] == 2 and tree["unassigned"][0]["title"] == "九日談"


class TestRoles:
    """역할(role)은 깊이(level)와 따로 산다 — «기사»가 2단에도 3단에도 오는 책이 있다(D-092 후속).

    왜 시험하는가: 숫자에 뜻을 붙이면 다층 문집(集 > 卷 > 기사 > 협주)에서 기사가 3단으로
    내려가는 순간 번역·주석의 단위가 조용히 «조각»이 된다.
    """

    def test_new_boundary_keeps_only_known_roles(self):
        pos = {"page": 1, "line": 0, "offset": 0}
        assert B.new_boundary(pos, role="container")["role"] == "container"
        assert B.new_boundary(pos, role="기사")["role"] is None  # 모르는 값은 버린다
        assert B.new_boundary(pos)["role"] is None  # 안 주면 비워 두고 깊이로 추정

    def test_missing_role_is_guessed_from_level(self):
        assert B.role_for_level(1) == "container"
        assert B.role_for_level(2) == "article"
        assert B.role_for_level(7) == "fragment"
        lines, pt = _lines()
        old = B.new_boundary({"page": 1, "line": 0, "offset": 0}, level=1, page_texts=pt)
        del old["role"]  # 역할 칸이 없던 옛 파일
        units = B.compute_units(_data(old), lines, pt)
        assert units[0]["metadata"]["role"] == "container"

    def test_deep_level_can_still_be_an_article(self):
        lines, pt = _lines()
        b = B.new_boundary(
            {"page": 1, "line": 0, "offset": 0}, level=5, role="article", page_texts=pt
        )
        units = B.compute_units(_data(b), lines, pt)
        assert units[0]["metadata"]["level"] == 5
        assert units[0]["metadata"]["role"] == "article"

    def test_update_boundary_can_change_role(self):
        b = B.new_boundary({"page": 1, "line": 0, "offset": 0}, level=2, role="article")
        data = _data(b)
        B.update_boundary(data, b["id"], {"role": "fragment"})
        assert data["boundaries"][0]["role"] == "fragment"


def test_insert_at_same_place_and_level_is_idempotent():
    """경계 제안을 두 번 적용해도 같은 자리에 경계가 둘 생기지 않는다(먼저 있던 id가 남는다)."""
    a = B.new_boundary({"page": 1, "line": 0, "offset": 0}, level=2, title="a")
    data = _data(a)
    again = B.new_boundary({"page": 1, "line": 0, "offset": 0}, level=2, title="a2")
    kept = B.insert_boundary(data, again)
    assert kept is a and len(data["boundaries"]) == 1
    # 층위가 다르면 같은 자리라도 다른 경계다(기사 첫머리에 서는 조각)
    frag = B.new_boundary({"page": 1, "line": 0, "offset": 0}, level=3, title="frag")
    assert B.insert_boundary(data, frag) is frag and len(data["boundaries"]) == 2
