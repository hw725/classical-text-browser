# -*- coding: utf-8 -*-
"""LLM 비전에 보내는 쪽 이미지(`llm_ocr._load_page_image`)가 정본 렌더 함수로 옮긴 뒤에도 같은가.

## 왜 이 시험이 필요한가

`_load_page_image`의 PDF 경로는 `get_pixmap`을 직접 불러 2.0배로 렌더하고 `page_rotation`을
따로 얹었다. 금지 패턴 시험(`test_forbidden_patterns.py`)을 비우려고 이것을
`ocr.image_utils.load_page_image_from_pdf(scale=2.0)`로 옮겼다(2026-10-01). 옮김은 «같은 결과»
일 때만 옳다 — 특히 권 회전(D-123)과 **쪽 범위 회전**(D-126)이 예전과 같은 방향으로 얹히는가.

그래서 예전 구현을 이 파일에 그대로 떠 두고(`_old_load`), 같은 서고에서 둘의 **최종 바이트**
(resize_for_llm이 만든 JPEG)를 견준다. 회전 0·90·180·270과 범위 회전 쪽을 모두 지난다.
그림은 비대칭(왼쪽 위 검은 네모 + 오른쪽 아래 회색 띠)이라 방향이 틀리면 바이트가 달라진다.
"""

from __future__ import annotations

import json
from io import BytesIO

import fitz
import pytest
from PIL import Image


def _make_library(tmp_path):
    """네 쪽 PDF 한 권. 권 회전 90(1쪽), 범위 회전 2쪽 180·3쪽 270·4쪽 0."""
    lib = tmp_path / "lib"
    doc = lib / "documents" / "d1"
    (doc / "L1_source").mkdir(parents=True)
    pdf = fitz.open()
    for i in range(4):
        page = pdf.new_page(width=120, height=200)
        page.draw_rect(fitz.Rect(5, 5, 30, 20), color=(0, 0, 0), fill=(0, 0, 0))
        grey = (0.5, 0.5, 0.5)
        page.draw_rect(fitz.Rect(80, 150 + i * 5, 115, 190), color=grey, fill=grey)
    pdf.save(str(doc / "L1_source" / "v1.pdf"))
    pdf.close()
    manifest = {
        "document_id": "d1",
        "title": "t",
        "parts": [
            {
                "part_id": "v1",
                "label": "v1",
                "file": "L1_source/v1.pdf",
                "page_count": 4,
                "rotation": 90,
                "rotation_ranges": [
                    {"from": 2, "to": 2, "rotation": 180},
                    {"from": 3, "to": 3, "rotation": 270},
                    {"from": 4, "to": 4, "rotation": 0},
                ],
            }
        ],
        "completeness_status": "file_only",
    }
    (doc / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return lib, doc


def _old_load(doc_dir, part_id, page):
    """2026-10-01 이전 `_load_page_image`의 PDF 경로를 그대로 뜬 것(비교 기준)."""
    from core.document import page_rotation
    from ocr.image_utils import resize_for_llm, resolve_part_pdf, rotate_page_image

    pdf_path = resolve_part_pdf(doc_dir, part_id)
    with fitz.open(str(pdf_path)) as doc:
        pix = doc[page - 1].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        raw = pix.tobytes("png")
        rot = page_rotation(doc_dir, part_id, page)
        if rot:
            buf = BytesIO()
            rotate_page_image(Image.open(BytesIO(raw)), rot).save(buf, format="PNG")
            raw = buf.getvalue()
        return resize_for_llm(raw, max_long_side=2000)


@pytest.mark.parametrize("page,expected_rot", [(1, 90), (2, 180), (3, 270), (4, 0)])
def test_load_page_image_matches_old_render(tmp_path, monkeypatch, page, expected_rot):
    """입력: 권 회전 90 + 범위 회전이 섞인 권의 쪽. 출력: 예전 구현과 같은 JPEG 바이트."""
    from app import _state
    from app.routers import llm_ocr
    from core.document import page_rotation

    lib, doc = _make_library(tmp_path)
    monkeypatch.setattr(_state, "_library_path", lib)
    # 시험 서고가 의도대로 회전을 갖는지 먼저 — 모두 0이면 비교가 회전을 검사하지 못한다
    assert page_rotation(doc, "v1", page) == expected_rot

    new = llm_ocr._load_page_image("d1", page, part_id="v1")
    old = _old_load(doc, "v1", page)
    assert new is not None
    assert new == old
    # 크기도 회전을 따른다: 120×200pt × 2.0 → 240×400, 90·270이면 가로로 눕는다
    img = Image.open(BytesIO(new)).convert("L")
    w, h = img.size
    assert (w > h) == (expected_rot in (90, 270))
    # 방향은 예전 구현과 견주는 것만으로는 못 지킨다 — 둘이 같은 rotate_page_image를 쓰므로
    # 그 함수의 부호가 뒤집혀도 바이트는 같다(Codex 교차 리뷰 2026-10-01). 그래서 검은 네모
    # (쪽 왼쪽 위, 렌더 좌표 중심 (35, 25))가 **시계 방향** 회전 뒤 있어야 할 자리를 따로 잰다.
    W, H = 240, 400
    x, y = 35, 25
    where = {0: (x, y), 90: (H - 1 - y, x), 180: (W - 1 - x, H - 1 - y), 270: (y, W - 1 - x)}
    wx, wy = where[expected_rot]
    assert img.getpixel((wx, wy)) < 80, f"{expected_rot}°: 검은 네모가 ({wx},{wy})에 없다"
    # 반대 방향(반시계)이었다면 올 자리는 비어 있어야 한다
    if expected_rot in (90, 270):
        ox, oy = where[360 - expected_rot]
        assert img.getpixel((ox, oy)) > 100  # 검은 네모가 아니다(회색 띠 127은 허용)


def test_load_page_image_missing_page_is_none(tmp_path, monkeypatch):
    """입력: 없는 쪽(99). 출력: None — 예전 계약과 같다."""
    from app import _state
    from app.routers import llm_ocr

    lib, _doc = _make_library(tmp_path)
    monkeypatch.setattr(_state, "_library_path", lib)
    assert llm_ocr._load_page_image("d1", 99, part_id="v1") is None
