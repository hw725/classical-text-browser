"""B-085-3: 화면에서 만든 글자층 PDF에 검수에서 저장한 교정이 들어가는지 재현 시험.

무엇이 있었나 (2026-10-28 릴리스 E2E):
    추출 패널의 「텍스트 레이어 PDF 다시 만들기」 단추(주석: 《교정 후 갱신용》)가 `body: {}`를 보내
    API 기본값 `source_layer="l2"`(OCR 원본)로 구웠다. 검수에서 衆→巖으로 고쳐 저장해도 화면으로
    만든 PDF에는 衆이 남았다. 권 전체 OCR 뒤 자동으로 굽는 PDF(`embed_after`)도 L2로 구워, 일부 쪽만
    다시 돌리면 다른 쪽의 교정이 PDF에서 빠졌다.

고친 뒤의 약속:
    - 화면의 두 길(단추·권 OCR 뒤 자동)은 교정본(L4 + 교정 기록)으로 굽는다.
    - 교정본 줄 수가 OCR 줄 수와 같으면 OCR 줄 좌표를 그대로 쓴다(L4는 L2를 줄 그대로 옮긴 것 —
      text_export.line_geometry와 같은 전제). 그래서 교정본으로 구워도 글자가 제자리에 선다.
    - 확정본(L4)이 없는 쪽은 OCR 결과로 넣는다 — 교정본을 골랐다고 그 쪽 글이 PDF에서 빠지지 않는다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import fitz

from export.text_layer_pdf import embed_text_layer
from tests.test_lite_mode_api import (  # noqa: F401 — fixture 재사용
    _sse_events,
    batch_ready,
    isolated_app,
)
from tests.test_text_layer_pdf import LINES, _write_l2, scanned_doc  # noqa: F401 — fixture 재사용

ROOT = Path(__file__).resolve().parent.parent


def test_screen_button_bakes_corrected_layer():
    """추출 패널 단추가 교정본(l4)을 고른다 — 빈 본문이면 API 기본값 l2(OCR 원본)로 구워진다."""
    js = (ROOT / "src" / "app" / "static" / "js" / "extract-panel.js").read_text(encoding="utf-8")
    m = re.search(r"async function _embedExtractPdf\(\)\s*\{(.*?)\n\}", js, re.S)
    assert m, "_embedExtractPdf를 찾지 못했다"
    body = m.group(1)
    assert re.search(r"source_layer:\s*[\"']l4[\"']", body), (
        "단추가 source_layer l4를 보내지 않는다"
    )


def test_l4_uses_l2_positions_when_line_counts_match(scanned_doc):  # noqa: F811
    """교정본 줄 수가 OCR 줄 수와 같으면 OCR 좌표에 교정된 글을 놓는다."""
    _write_l2(scanned_doc, "vol1", 1, with_bbox=True)
    pages_dir = scanned_doc / "L4_text" / "pages"
    pages_dir.mkdir(parents=True)
    corrected = [LINES[0][0].replace("필사본", "筆寫本"), LINES[1][0], LINES[2][0]]
    (pages_dir / "vol1_page_001.txt").write_text("\n".join(corrected) + "\n", encoding="utf-8")

    result = embed_text_layer(
        scanned_doc, "vol1", pages=[1], source_layer="l4", use_line_detection=False
    )

    assert result.positioned_lines == 3 and result.approximated_lines == 0, result.to_dict()
    out = fitz.open(result.output_path)
    try:
        hits = out[0].search_for("筆寫本")
        assert hits, "교정된 글이 PDF에 없다"
        # OCR 줄 상자(포인트) 안에 형광이 선다 — 가로 줄의 글꼴 상자는 줄 높이보다 조금 커서(L2로
        # 구워도 같다, 2026-10-28 실측 92.1～122.1pt / 상자 100～120pt) 위아래 끝이 아니라 가운데로
        # 잰다
        bbox = [c / 2.0 for c in LINES[0][1]]
        cy = (hits[0].y0 + hits[0].y1) / 2
        assert bbox[1] <= cy <= bbox[3], (hits[0], bbox)
        assert bbox[0] - 2 <= hits[0].x0 and hits[0].x1 <= bbox[2] + 2, (hits[0], bbox)
        assert "필사본 유통과" not in out[0].get_text("text")
    finally:
        out.close()


def test_l4_falls_back_to_ocr_on_pages_without_l4(scanned_doc):  # noqa: F811
    """확정본이 없는 쪽은 OCR 결과로 넣는다 — 교정본을 골라도 그 쪽 글이 빠지지 않는다."""
    _write_l2(scanned_doc, "vol1", 1, with_bbox=True)
    _write_l2(scanned_doc, "vol1", 2, with_bbox=True)
    pages_dir = scanned_doc / "L4_text" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir / "vol1_page_001.txt").write_text(
        "\n".join(t for t, _b in LINES) + "\n", encoding="utf-8"
    )

    result = embed_text_layer(scanned_doc, "vol1", source_layer="l4", use_line_detection=False)

    assert result.embedded_pages == 2, result.to_dict()
    assert any("2쪽" in w or "확정본" in w for w in result.warnings), result.warnings
    out = fitz.open(result.output_path)
    try:
        assert LINES[0][0] in out[1].get_text("text")
    finally:
        out.close()


def test_batch_auto_bake_keeps_saved_corrections(batch_ready):  # noqa: F811
    """권 OCR 뒤 자동으로 굽는 PDF에도 저장해 둔 교정이 들어간다."""
    client, doc_id, part_id = batch_ready
    client.post(
        f"/api/documents/{doc_id}/parts/{part_id}/ocr/batch",
        json={"engine_id": "dummy", "embed_after": False},
    )
    url = f"/api/documents/{doc_id}/pages/1/corrections"
    text = client.get(
        f"/api/documents/{doc_id}/pages/1/text", params={"part_id": part_id}
    ).json()["text"]
    assert "필사본" in text
    r = client.put(
        url,
        params={"part_id": part_id},
        json={"part_id": part_id, "corrected_text": text.replace("필사본", "筆寫本"),
              "corrections": []},
    )
    assert r.status_code == 200, r.text

    # 다시 권 OCR(있는 쪽은 건너뜀) → 자동으로 굽는다
    events = _sse_events(
        client.post(
            f"/api/documents/{doc_id}/parts/{part_id}/ocr/batch", json={"engine_id": "dummy"}
        )
    )
    done = [e for e in events if e.get("type") == "complete"][-1]
    assert done.get("embedded"), done

    dl = client.get(f"/api/documents/{doc_id}/parts/{part_id}/export/text-layer-pdf")
    doc = fitz.open(stream=dl.content, filetype="pdf")
    try:
        page1 = doc[0].get_text("text")
        assert "筆寫本" in page1, "자동으로 구운 PDF에 교정이 없다"
        assert done["embedded"]["approximated_lines"] == 0, done["embedded"]
    finally:
        doc.close()


def test_saved_l2_json_untouched_by_l4_bake(scanned_doc):  # noqa: F811
    """교정본으로 구워도 L2 파일은 읽기만 한다."""
    _write_l2(scanned_doc, "vol1", 1, with_bbox=True)
    p = scanned_doc / "L2_ocr" / "vol1_page_001.json"
    before = p.read_bytes()
    embed_text_layer(scanned_doc, "vol1", pages=[1], source_layer="l4", use_line_detection=False)
    assert p.read_bytes() == before
    assert json.loads(before)  # 그대로 읽힌다
