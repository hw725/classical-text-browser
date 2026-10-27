"""B-085 덧붙임: 세로쓰기 쪽의 잉크 검사 — 제자리 열은 《어긋났다》고 하지 않고, 어긋난 열은 잡는다.

무엇이 있었나 (2026-10-28, B-085-2를 고친 뒤 운양집 E2E):
    세로 열을 열 상자에 꼭 맞게 놓았는데도 쪽마다 《텍스트가 놓인 자리에 글자가 거의 없습니다(쪽
    평균의 1.0배·0.6배)》 경고가 떴다. 잉크 검사가 고정 문턱(회색 128)을 써서 목판의 옅은 회색 획은
    잉크로 보지 못하고 스캔 가장자리의 검은 띠만 잡았고, 열이 쪽 대부분을 덮는 세로쓰기 쪽에
    가로쓰기 논문에서 정한 1.3배 문턱을 걸었다.

이 시험이 지키는 것: 옅은 회색 획 + 검은 가장자리 띠의 세로쓰기 스캔에서
    - 열 상자가 제자리면 잉크 경고가 없다.
    - 열 상자를 열 폭의 0.7만큼 옆으로 밀면 잉크 경고가 뜬다(검사가 무뎌지지 않았다).
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz

from export.text_layer_pdf import embed_text_layer

PAGE_W, PAGE_H = 600.0, 460.0
SCALE = 2.0
TEXT = "天地玄黃宇宙洪荒日月盈昃辰宿列張"
COL_W, PITCH = 26.0, 36.0  # 포인트 — 열 폭과 열 간격(목판처럼 열이 쪽 대부분을 덮는다)
N_COLS = 12


def _columns(shift: float = 0.0) -> list[tuple[str, list[float]]]:
    cols = []
    for i in range(N_COLS):
        x1 = PAGE_W - 60 - i * PITCH
        x0 = x1 - COL_W
        box = [(x0 + shift) * SCALE, 60 * SCALE, (x1 + shift) * SCALE, 0]
        cols.append((TEXT[: 10 + i % 5], box))
    for t, b in cols:
        b[3] = (60 + COL_W * len(t)) * SCALE
    return cols


def _make_doc(tmp_path: Path, shift: float) -> Path:
    doc = tmp_path / f"doc_{shift}"
    (doc / "L1_source").mkdir(parents=True)
    tmp = fitz.open()
    p = tmp.new_page(width=PAGE_W, height=PAGE_H)
    # 스캔 가장자리의 검은 띠(책 바깥)
    p.draw_rect(fitz.Rect(0, 0, 28, PAGE_H), color=(0, 0, 0), fill=(0, 0, 0))
    p.draw_rect(fitz.Rect(PAGE_W - 22, 0, PAGE_W, PAGE_H), color=(0, 0, 0), fill=(0, 0, 0))
    for text, b in _columns():
        x0, y0 = b[0] / SCALE, b[1] / SCALE
        for k, ch in enumerate(text):
            p.insert_text((x0 + 1, y0 + COL_W * (k + 1) - 4), ch, fontname="china-t",
                          fontsize=COL_W - 2, color=(0.45, 0.45, 0.45))  # 옅은 회색 획
    jpg = p.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE)).tobytes("jpeg", jpg_quality=85)
    tmp.close()
    out = fitz.open()
    np_ = out.new_page(width=PAGE_W, height=PAGE_H)
    np_.insert_image(np_.rect, stream=jpg)
    out.save(str(doc / "L1_source" / "v.pdf"))
    out.close()
    (doc / "manifest.json").write_text(
        json.dumps({"document_id": doc.name, "title": "t",
                    "parts": [{"part_id": "vol1", "file": "L1_source/v.pdf", "page_count": 1}]}),
        encoding="utf-8",
    )
    (doc / "L2_ocr").mkdir()
    (doc / "L2_ocr" / "vol1_page_001.json").write_text(
        json.dumps({"image_width": PAGE_W * SCALE,
                    "ocr_results": [
                        {"lines": [{"text": t, "bbox": b} for t, b in _columns(shift)]}
                    ]},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    return doc


def _ink_warnings(result) -> list[str]:
    return [w for w in result.warnings if "글자가 거의 없습니다" in w]


def test_vertical_columns_in_place_raise_no_ink_warning(tmp_path):
    result = embed_text_layer(_make_doc(tmp_path, 0.0), "vol1", use_line_detection=False)
    assert result.positioned_lines == N_COLS
    assert not _ink_warnings(result), result.warnings


def test_vertical_columns_shifted_raise_ink_warning(tmp_path):
    result = embed_text_layer(_make_doc(tmp_path, COL_W * 0.7), "vol1", use_line_detection=False)
    assert _ink_warnings(result), result.warnings
