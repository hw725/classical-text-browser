"""B-085-2: 세로쓰기 쪽의 글자층(L2)이 열을 따라 제자리·제 크기로 놓이는지 재현 시험.

무엇이 있었나 (2026-10-28 릴리스 E2E, 운양집 세로쓰기 목판 3쪽):
    NDL古典籍 OCR의 줄 상자는 폭 60px·높이 1,370px쯤의 세로 열이다. `_embed_lines`는 모든 줄을
    가로로 쓰고 글자 크기를 《상자 폭에 글줄 전체가 들어가게》 맞췄다 — 열마다 12자가 폭 30pt에
    가로로 욱여넣어져 1pt 안팎 크기로 열 아래 끝에 얹혔다. 쪽마다 《글자가 1.0pt로 너무 작습니다 —
    드래그로 선택되지 않습니다》 경고가 떴다.

이 시험이 지키는 것 (내려받은 PDF를 다시 열어 잰다):
    - 열마다 추출되는 글줄이 그 열의 글을 그대로(순서대로) 담는다.
    - 그 글줄의 상자가 열 상자 안에 있고 열 높이의 대부분을 덮는다(아래 끝에 몰리지 않는다).
    - 글자 크기가 열 폭 수준이다(1pt가 아니다) — 크기 경고가 없다.
    - 한 글자를 찾으면 그 글자의 자리(열 안의 몇 번째 칸)에 형광이 뜬다.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from export.text_layer_pdf import embed_text_layer

PAGE_W, PAGE_H = 560.0, 480.0
SCALE = 2.0  # 렌더 픽셀 = 포인트 × 2

# (글, 열 상자[px]) — 오른쪽 열부터(세로쓰기 읽는 순서). 열 폭 60px = 30pt, 12자 높이 720px = 360pt.
COLUMNS = [
    ("中衆何品英洞宮浚自關真人", [960.0, 120.0, 1020.0, 840.0]),
    ("補碧淫席中有黎瓊仙譽花長", [860.0, 120.0, 920.0, 840.0]),
    ("十里波境一笠守殿林低樹夕", [760.0, 120.0, 820.0, 840.0]),
]


def _make_vertical_scan(path: Path) -> None:
    """세로 열마다 글자를 위에서 아래로 그린 뒤 이미지로 굳힌 스캔본."""
    out = fitz.open()
    tmp = fitz.open()
    p = tmp.new_page(width=PAGE_W, height=PAGE_H)
    for text, (x0, y0, x1, _y1) in COLUMNS:
        cell = (x1 - x0) / SCALE
        for i, ch in enumerate(text):
            p.insert_text(
                (x0 / SCALE + 1, y0 / SCALE + cell * (i + 1) - 4), ch,
                fontname="china-t", fontsize=cell - 2,
            )
    jpg = p.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE)).tobytes("jpeg", jpg_quality=80)
    tmp.close()
    page = out.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_image(page.rect, stream=jpg)
    out.save(str(path))
    out.close()


@pytest.fixture()
def vertical_doc(tmp_path):
    doc = tmp_path / "doc_v"
    (doc / "L1_source").mkdir(parents=True)
    _make_vertical_scan(doc / "L1_source" / "v.pdf")
    (doc / "manifest.json").write_text(
        json.dumps(
            {"document_id": "doc_v", "title": "세로",
             "parts": [{"part_id": "vol1", "file": "L1_source/v.pdf", "page_count": 1}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (doc / "L2_ocr").mkdir()
    (doc / "L2_ocr" / "vol1_page_001.json").write_text(
        json.dumps(
            {
                "part_id": "vol1",
                "page_number": 1,
                "ocr_engine": "ndlkotenocr-full",
                "image_width": PAGE_W * SCALE,
                "ocr_results": [
                    {
                        "layout_block_id": "p01_b01",
                        "lines": [{"text": t, "bbox": b} for t, b in COLUMNS],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return doc


def _lines(page) -> list[dict]:
    d = page.get_text("dict")
    return [ln for b in d["blocks"] if b["type"] == 0 for ln in b["lines"]]


def test_vertical_columns_become_column_text(vertical_doc):
    result = embed_text_layer(vertical_doc, "vol1", source_layer="l2", use_line_detection=False)

    assert result.positioned_lines == 3
    assert not [w for w in result.warnings if "너무 작습니다" in w], result.warnings

    out = fitz.open(result.output_path)
    try:
        page = out[0]
        lines = _lines(page)
        for text, bbox in COLUMNS:
            col = fitz.Rect(*(c / SCALE for c in bbox))
            mine = [
                ln for ln in lines
                if fitz.Rect(ln["bbox"]).intersects(col)
                and "".join(s["text"] for s in ln["spans"]).strip()
            ]
            joined = "".join(s["text"] for ln in mine for s in ln["spans"]).replace(" ", "")
            assert joined == text, f"열 글이 다르다: {joined!r} ≠ {text!r}"
            union = fitz.Rect(mine[0]["bbox"])
            for ln in mine[1:]:
                union |= fitz.Rect(ln["bbox"])
            # 열 상자 안(±2pt)에 있고, 열 높이의 85% 이상을 덮는다
            assert union.x0 >= col.x0 - 2 and union.x1 <= col.x1 + 2, (union, col)
            assert union.y0 >= col.y0 - 2 and union.y1 <= col.y1 + 2, (union, col)
            assert union.height >= col.height * 0.85, (union, col)
            sizes = [s["size"] for ln in mine for s in ln["spans"]]
            assert min(sizes) >= col.width * 0.6, (
                f"글자 크기 {min(sizes):.1f}pt — 열 폭 {col.width:.0f}pt"
            )
    finally:
        out.close()


def test_vertical_search_highlights_the_right_cell(vertical_doc):
    """열의 일곱째 글자(宮)를 찾으면 그 열 일곱째 칸에 형광이 뜬다."""
    result = embed_text_layer(vertical_doc, "vol1", source_layer="l2", use_line_detection=False)
    out = fitz.open(result.output_path)
    try:
        hits = out[0].search_for("宮")
        assert hits, "宮을 찾지 못했다"
        text, bbox = COLUMNS[0]
        col = fitz.Rect(*(c / SCALE for c in bbox))
        cell = col.height / len(text)
        want_center_y = col.y0 + cell * (text.index("宮") + 0.5)
        h = hits[0]
        assert col.x0 - 2 <= (h.x0 + h.x1) / 2 <= col.x1 + 2, (h, col)
        assert abs((h.y0 + h.y1) / 2 - want_center_y) <= cell * 0.6, (h, want_center_y)
    finally:
        out.close()


def test_horizontal_lines_unchanged(tmp_path):
    """가로 줄은 예전처럼 한 줄로 가로 놓인다(세로 판정이 가로 줄을 건드리지 않는다)."""
    doc = tmp_path / "doc_h"
    (doc / "L1_source").mkdir(parents=True)
    src = fitz.open()
    src.new_page(width=PAGE_W, height=PAGE_H)
    src.save(str(doc / "L1_source" / "h.pdf"))
    src.close()
    (doc / "manifest.json").write_text(
        json.dumps({"document_id": "doc_h", "title": "가로",
                    "parts": [{"part_id": "vol1", "file": "L1_source/h.pdf", "page_count": 1}]}),
        encoding="utf-8",
    )
    (doc / "L2_ocr").mkdir()
    (doc / "L2_ocr" / "vol1_page_001.json").write_text(
        json.dumps({"ocr_results": [
            {"lines": [{"text": "二十一", "bbox": [100.0, 100.0, 205.0, 161.0]}]}
        ]}),
        encoding="utf-8",
    )
    result = embed_text_layer(doc, "vol1", use_line_detection=False)
    out = fitz.open(result.output_path)
    try:
        lines = _lines(out[0])
        assert len(lines) == 1
        assert tuple(round(v, 3) for v in lines[0]["dir"]) == (1.0, 0.0)
    finally:
        out.close()
