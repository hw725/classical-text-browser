"""전면 블록과 회전(D-126 덧붙임 2026-09-18).

자동으로 만든 전면 블록이 다른 회전에서 만들어졌으면 ensure_full_page_block이 지금 회전으로 다시
만든다 — 「권 전체 OCR」이 회전을 저장한 쪽을 다시 돌 때 파이프라인이 «다른 회전의 레이아웃»이라
거부하지 않게. 사람이 나눈 레이아웃은 그대로 둔다(D-123).
"""

import json


def _doc(tmp_path):
    import fitz

    from core.document import add_document
    from core.library import init_library

    lib = tmp_path / "lib"
    init_library(lib)
    src = tmp_path / "one.pdf"
    doc = fitz.open()
    doc.new_page(width=400, height=600)
    doc.save(str(src))
    doc.close()
    add_document(library_path=lib, doc_id="d", title="d", files=[src])
    return lib / "documents" / "d"


def _layout(doc_path):
    return json.loads((doc_path / "L3_layout" / "vol1_page_001.json").read_text(encoding="utf-8"))


def test_stale_full_page_block_is_rebuilt_for_new_rotation(tmp_path):
    from core.document import set_part_rotation
    from ocr.full_page_block import ensure_full_page_block

    doc_path = _doc(tmp_path)
    assert ensure_full_page_block(doc_path, "vol1", 1)["created"] is True
    before = _layout(doc_path)
    assert int(before.get("rotation") or 0) == 0
    # 같은 회전이면 그대로
    assert ensure_full_page_block(doc_path, "vol1", 1)["created"] is False

    # 쪽 범위 회전 90° 저장 → 전면 블록을 새 회전으로 다시 만든다(가로세로가 바뀐다)
    set_part_rotation(doc_path, "vol1", 90, (1, 1))
    info = ensure_full_page_block(doc_path, "vol1", 1)
    assert info["created"] is True
    after = _layout(doc_path)
    assert after["rotation"] == 90
    assert (after["image_width"], after["image_height"]) == (
        before["image_height"],
        before["image_width"],
    )
    assert ensure_full_page_block(doc_path, "vol1", 1)["created"] is False


def test_hand_made_layout_is_left_alone_after_rotation(tmp_path):
    from core.document import save_page_layout, set_part_rotation
    from ocr.full_page_block import ensure_full_page_block

    doc_path = _doc(tmp_path)
    ensure_full_page_block(doc_path, "vol1", 1)
    lay = _layout(doc_path)
    w, h = lay["image_width"], lay["image_height"]
    # 사람이 둘로 나눈 레이아웃 — 전면 블록이 아니다
    lay["analysis_method"] = "manual"
    lay["blocks"] = [
        {**lay["blocks"][0], "block_id": "p01_b01", "bbox": [0, 0, w // 2, h], "reading_order": 1},
        {**lay["blocks"][0], "block_id": "p01_b02", "bbox": [w // 2, 0, w, h], "reading_order": 2},
    ]
    save_page_layout(doc_path, "vol1", 1, lay)
    set_part_rotation(doc_path, "vol1", 90, None)
    info = ensure_full_page_block(doc_path, "vol1", 1)
    assert info["created"] is False and info["block_count"] == 2
    assert (
        int(_layout(doc_path).get("rotation") or 0) == 0
    )  # 손댄 것 없음 — 파이프라인이 거부하고 사람이 판단


def test_rebuilt_full_page_block_keeps_block_attributes(tmp_path):
    """사람이 만진 전면 블록의 속성은 회전이 바뀌어도 살아남는다.

    쓰기 방향·종류·skip·analysis_method를 말한다(Codex 지적 2026-09-18).
    새것으로 바뀌는 것은 기하(bbox·폭·높이·도장)뿐이다.
    """
    from core.document import save_page_layout, set_part_rotation
    from ocr.full_page_block import ensure_full_page_block

    doc_path = _doc(tmp_path)
    ensure_full_page_block(doc_path, "vol1", 1)
    lay = _layout(doc_path)
    lay["analysis_method"] = "manual"
    lay["blocks"][0]["writing_direction"] = "vertical_rtl"
    lay["blocks"][0]["block_type"] = "annotation"
    lay["blocks"][0]["skip"] = True
    save_page_layout(doc_path, "vol1", 1, lay)
    w, h = lay["image_width"], lay["image_height"]

    set_part_rotation(doc_path, "vol1", 270, None)
    assert ensure_full_page_block(doc_path, "vol1", 1)["created"] is True
    after = _layout(doc_path)
    assert after["rotation"] == 270 and (after["image_width"], after["image_height"]) == (h, w)
    b = after["blocks"][0]
    assert b["bbox"] == [0, 0, h, w]
    assert (
        b["writing_direction"] == "vertical_rtl"
        and b["block_type"] == "annotation"
        and b["skip"] is True
    )
    assert after["analysis_method"] == "manual"


def test_stale_l2_without_l3_counts_as_changed(tmp_path):
    """L3가 없고 L2만 있는 쪽: L2의 회전 도장이 지금 회전과 다르면 «바뀜» — 아니면 옛 좌표계의 L2가
    «이미 결과가 있다»로 건너뛰어진다(Codex 지적 2026-09-18)."""
    from core.document import set_part_rotation, write_json_atomic
    from ocr.layout_staleness import layout_changed_since_ocr

    doc_path = _doc(tmp_path)
    l2 = doc_path / "L2_ocr" / "vol1_page_001.json"
    l2.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(l2, {"part_id": "vol1", "page_number": 1, "rotation": 0, "blocks": []})
    assert layout_changed_since_ocr(doc_path, "vol1", 1) == (False, "")
    set_part_rotation(doc_path, "vol1", 90, None)
    changed, why = layout_changed_since_ocr(doc_path, "vol1", 1)
    assert changed is True and "0°" in why and "90°" in why
