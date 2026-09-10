"""권 단위 회전 저장(D-123) — 좌표계 하나를 지키는가.

회전은 «바로 세우려면 시계 방향으로 몇 도»다. 서버(PIL)·화면(PDF.js)·내보내기(/Rotate)가 같은
부호를 쓰는지, 옛 좌표계를 조용히 늘여 쓰지 않는지, 저장 라우트가 지우지 않고 알리는지를 잰다.
"""

import json

import fitz
import pytest
from PIL import Image

from src.core.document import part_rotation, set_part_rotation
from src.ocr.image_utils import rotate_page_image, unrotate_bbox, unrotate_point


def _dot_image(w=60, h=100, dot=(10, 20)):
    """흰 바탕에 검은 점 하나. 점의 자리로 회전 부호를 잰다."""
    img = Image.new("L", (w, h), 255)
    img.putpixel(dot, 0)
    return img


def _find_dot(img):
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            if px[x, y] == 0:
                return x, y
    raise AssertionError("점이 없다")


class TestRotationMath:
    """PIL 회전과 unrotate_point가 서로의 역인지 — 부호를 여기서 고정한다."""

    @pytest.mark.parametrize("rotation", [0, 90, 180, 270])
    def test_unrotate_point_inverts_pil_rotation(self, rotation):
        """입력: 점 하나를 돌린 이미지. 출력: 되돌린 좌표 = 원래 자리. 목적: 부호 규약."""
        img = _dot_image()
        rot = rotate_page_image(img, rotation)
        if rotation % 180 == 90:
            assert rot.size == (img.height, img.width)  # 90°·270°는 폭·높이가 바뀐다
        rx, ry = _find_dot(rot)
        # 화소 중심으로 되돌린다 — 경계 좌표와 화소 인덱스는 반 화소 차이가 난다
        x, y = unrotate_point(rx + 0.5, ry + 0.5, rotation, rot.width, rot.height)
        assert (int(x), int(y)) == (10, 20)

    def test_clockwise_is_pdf_convention(self):
        """입력: 왼쪽 위 점을 90° 돌림. 출력: 오른쪽 위. 목적: 시계 방향(PDF /Rotate·PDF.js)이다."""
        rot = rotate_page_image(_dot_image(dot=(0, 0)), 90)
        assert _find_dot(rot) == (rot.width - 1, 0)

    def test_unrotate_bbox_wraps_all_corners(self):
        """입력: 돌린 이미지의 bbox. 출력: 되돌린 bbox가 정렬돼 있다(x0<x1, y0<y1)."""
        b = unrotate_bbox([10, 20, 30, 50], 90, rot_w=100, rot_h=60)
        assert b[0] < b[2] and b[1] < b[3]
        assert b == [20.0, 70.0, 50.0, 90.0]


def _make_doc(tmp_path, rotation=0):
    """세로 PDF(100×200pt) 한 쪽과 manifest를 가진 문헌. 쪽 왼쪽 위에 검은 네모."""
    lib = tmp_path / "lib"
    doc = lib / "documents" / "d1"
    (doc / "L1_source").mkdir(parents=True)
    pdf = fitz.open()
    page = pdf.new_page(width=100, height=200)
    page.draw_rect(fitz.Rect(5, 5, 25, 15), color=(0, 0, 0), fill=(0, 0, 0))
    pdf.save(str(doc / "L1_source" / "v1.pdf"))
    pdf.close()
    manifest = {
        "document_id": "d1",
        "title": "t",
        "parts": [{"part_id": "v1", "label": "v1", "file": "L1_source/v1.pdf", "page_count": 1}],
        "completeness_status": "file_only",
    }
    if rotation:
        manifest["parts"][0]["rotation"] = rotation
    (doc / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return lib, doc


class TestServerImage:
    def test_missing_rotation_reads_as_zero(self, tmp_path):
        """입력: rotation이 없는 옛 manifest. 출력: 0. 목적: 스키마 default는 런타임 값이 아니다."""
        _lib, doc = _make_doc(tmp_path)
        assert part_rotation(doc, "v1") == 0
        assert part_rotation(doc, "no_such") == 0

    def test_page_image_is_rotated_for_the_part(self, tmp_path):
        """입력: rotation=90인 권. 출력: 돌린 이미지(가로). 목적: OCR이 받는 이미지가 좌표계다."""
        from src.ocr.image_utils import load_page_image_from_pdf

        lib, _doc = _make_doc(tmp_path, rotation=90)
        img = load_page_image_from_pdf(str(lib), "d1", 1, scale=1.0, part_id="v1")
        assert img.size == (200, 100)
        # 원본 왼쪽 위의 검은 네모가 시계 90° 뒤에는 오른쪽 위에 있다
        assert img.convert("L").getpixel((200 - 10, 15)) < 128
        assert img.convert("L").getpixel((10, 15)) > 128

    def test_set_rotation_validates_and_writes(self, tmp_path):
        """입력: 90 저장. 출력: manifest에 남고 읽힌다. 잘못된 값은 ValueError."""
        _lib, doc = _make_doc(tmp_path)
        set_part_rotation(doc, "v1", 90)
        assert part_rotation(doc, "v1") == 90
        with pytest.raises(ValueError):
            set_part_rotation(doc, "v1", 45)
        with pytest.raises(FileNotFoundError):
            set_part_rotation(doc, "v9", 90)


class TestStaleCoordinates:
    def test_layout_from_other_rotation_is_refused(self, tmp_path):
        """입력: 0°에서 만든 L3, 지금은 90°. 출력: 자르지 않고 오류. 목적: 늘여 쓰면 엉뚱한 데."""
        from src.ocr.pipeline import OcrPipeline
        from src.ocr.registry import OcrEngineRegistry

        lib, doc = _make_doc(tmp_path, rotation=90)
        (doc / "L3_layout").mkdir()
        layout = {
            "part_id": "v1",
            "page_number": 1,
            "image_width": 100,
            "image_height": 200,
            "rotation": 0,
            "blocks": [
                {
                    "block_id": "b1",
                    "block_type": "main_text",
                    "bbox": [0, 0, 100, 200],
                    "reading_order": 1,
                    "writing_direction": "vertical_rtl",
                    "skip": False,
                }
            ],
        }
        (doc / "L3_layout" / "v1_page_001.json").write_text(json.dumps(layout), encoding="utf-8")
        prepared = OcrPipeline(OcrEngineRegistry(), str(lib)).prepare_page("d1", "v1", 1)
        assert prepared.error and "다른 회전" in prepared.error

    def test_staleness_reports_rotation_change(self, tmp_path):
        """입력: 0° 도장의 L2·L3, 지금 90°. 출력: 낡음 + 사유. 목적: 재실행 대상으로 잡힌다."""
        from src.ocr.layout_staleness import layout_changed_since_ocr

        lib, doc = _make_doc(tmp_path, rotation=90)
        (doc / "L3_layout").mkdir()
        (doc / "L2_ocr").mkdir()
        (doc / "L3_layout" / "v1_page_001.json").write_text(
            json.dumps({"part_id": "v1", "page_number": 1, "blocks": [{"block_id": "b1"}]}),
            encoding="utf-8",
        )
        (doc / "L2_ocr" / "v1_page_001.json").write_text(
            json.dumps(
                {
                    "part_id": "v1",
                    "page_number": 1,
                    "ocr_results": [{"layout_block_id": "b1", "lines": []}],
                }
            ),
            encoding="utf-8",
        )
        changed, why = layout_changed_since_ocr(doc, "v1", 1, use_mtime=False)
        assert changed and "회전" in why


class TestExport:
    def test_text_layer_lands_on_ink_when_part_is_rotated(self, tmp_path):
        """입력: 90° 권의 L2(돌린 이미지 좌표). 출력: 출력 PDF가 /Rotate 90, 글자가 네모 위.

        목적: L2 픽셀 → 표시 공간 → 쪽 공간의 사슬이 맞는지를 산출물에서 잰다(D-068의 태도).
        """
        from src.export.text_layer_pdf import _ink_check, embed_text_layer

        lib, doc = _make_doc(tmp_path, rotation=90)
        # 돌린 이미지(200×100 @ scale 1)에서 검은 네모는 x 185~195, y 5~25 — L2는 배율 2로 적는다
        (doc / "L2_ocr").mkdir()
        l2 = {
            "part_id": "v1",
            "page_number": 1,
            "image_width": 400,
            "image_height": 200,
            "rotation": 90,
            "ocr_results": [
                {
                    "layout_block_id": "b1",
                    "lines": [
                        {"text": "甲乙", "bbox": [370, 10, 390, 50]},
                        # 표시 공간의 왼쪽 아래 — 쪽 공간에서는 y가 커서 잘림이 있으면 여기서 드러난다
                        {"text": "丙丁", "bbox": [10, 150, 30, 190]},
                    ],
                }
            ],
        }
        (doc / "L2_ocr" / "v1_page_001.json").write_text(
            json.dumps(l2, ensure_ascii=False), encoding="utf-8"
        )
        out = tmp_path / "out.pdf"
        result = embed_text_layer(doc, "v1", output_path=out, use_line_detection=False)
        assert result.positioned_lines >= 1, result
        with fitz.open(str(out)) as pdf:
            page = pdf[0]
            assert page.rotation == 90  # 다른 뷰어에서도 바로 선다
            words = sorted(page.get_text("words"), key=lambda w: w[4])
            assert [w[4] for w in words] == ["丙丁", "甲乙"], words
            # 표시 공간(회전 적용)에서 글자의 자리가 네모(원본 왼쪽 위 → 표시 오른쪽 위) 위여야 한다
            rect = fitz.Rect(words[1][:4]) * page.rotation_matrix
            assert rect.x0 > 150 and rect.y1 < 40, rect
            low = fitz.Rect(words[0][:4]) * page.rotation_matrix
            assert low.x0 < 40 and low.y0 > 60, low  # 표시 공간 왼쪽 아래에 그대로
            ratio = _ink_check(page, [{"bbox": words[1][:4]}])
            assert ratio is not None and ratio > 1.5, ratio
