"""OCR 이미지 유틸리티 테스트.

crop_block, preprocess_for_ocr, get_page_image_path, load_page_image를 검증한다.
"""

import io

import pytest
from PIL import Image

from src.ocr.base import OcrEngineError
from src.ocr.image_utils import (
    crop_block,
    get_page_image_path,
    load_page_image,
    preprocess_for_ocr,
)


@pytest.fixture
def sample_image():
    """테스트용 100x200 RGB 이미지."""
    img = Image.new("RGB", (100, 200), "white")
    return img


@pytest.fixture
def sample_image_bytes(sample_image):
    """sample_image의 PNG 바이트."""
    buf = io.BytesIO()
    sample_image.save(buf, format="PNG")
    return buf.getvalue()


class TestLoadPageImage:
    def test_load_png(self, tmp_path):
        img = Image.new("RGB", (50, 50), "red")
        path = tmp_path / "test.png"
        img.save(path)

        loaded = load_page_image(str(path))
        assert loaded.size == (50, 50)

    def test_load_nonexistent(self, tmp_path):
        with pytest.raises(OcrEngineError, match="이미지를 열 수 없습니다"):
            load_page_image(str(tmp_path / "nonexistent.png"))


class TestCropBlock:
    def test_basic_crop(self, sample_image):
        """비율 좌표로 크롭한 결과가 올바른 크기인지."""
        # bbox: [x=0.1, y=0.2, w=0.5, h=0.6]
        # image: 100x200
        # 기대: x_min=10-2=8, y_min=40-2=38, x_max=60+2=62, y_max=160+2=162
        result_bytes = crop_block(sample_image, [0.1, 0.2, 0.5, 0.6], padding_px=2)

        img = Image.open(io.BytesIO(result_bytes))
        # 크롭 결과는 대략 54x124 정도 (패딩 포함)
        assert img.width > 0
        assert img.height > 0

    def test_full_image_crop(self, sample_image):
        """전체 이미지를 크롭하면 원본 크기에 가까운 결과."""
        result_bytes = crop_block(sample_image, [0.0, 0.0, 1.0, 1.0], padding_px=0)
        img = Image.open(io.BytesIO(result_bytes))
        assert img.size == (100, 200)

    def test_invalid_bbox_zero_area(self, sample_image):
        """영역이 0인 bbox는 에러."""
        with pytest.raises(OcrEngineError, match="유효하지 않은 크롭 영역"):
            crop_block(sample_image, [0.5, 0.5, 0.0, 0.0], padding_px=0)

    def test_output_is_png_bytes(self, sample_image):
        """출력이 PNG 바이트인지 확인."""
        result_bytes = crop_block(sample_image, [0.0, 0.0, 0.5, 0.5])
        assert isinstance(result_bytes, bytes)
        # PNG 매직 넘버 확인
        assert result_bytes[:4] == b"\x89PNG"


class TestPreprocessForOcr:
    def test_grayscale(self, sample_image_bytes):
        """그레이스케일 변환이 정상 동작하는지."""
        result = preprocess_for_ocr(sample_image_bytes, grayscale=True)
        img = Image.open(io.BytesIO(result))
        assert img.mode == "L"

    def test_no_grayscale(self, sample_image_bytes):
        """grayscale=False이면 원본 모드 유지."""
        result = preprocess_for_ocr(sample_image_bytes, grayscale=False)
        img = Image.open(io.BytesIO(result))
        assert img.mode == "RGB"

    def test_binarize(self, sample_image_bytes):
        """이진화가 정상 동작하는지."""
        result = preprocess_for_ocr(sample_image_bytes, grayscale=True, binarize=True)
        img = Image.open(io.BytesIO(result))
        # 이진화된 이미지는 mode="1" 또는 "L"
        assert img.mode in ("1", "L")


class TestGetPageImagePath:
    def test_find_image_convention(self, tmp_path):
        """프로젝트 네이밍 컨벤션 ({part_id}_page_{NNN}.png)으로 찾기."""
        doc_dir = tmp_path / "documents" / "doc001" / "L1_source"
        doc_dir.mkdir(parents=True)
        (doc_dir / "vol1_page_001.png").write_bytes(b"fake png")

        result = get_page_image_path(str(tmp_path), "doc001", "vol1", 1)
        assert result is not None
        assert "vol1_page_001.png" in result

    def test_find_simple_name(self, tmp_path):
        """page_{NNN}.png 형식으로 찾기."""
        doc_dir = tmp_path / "documents" / "doc001" / "L1_source"
        doc_dir.mkdir(parents=True)
        (doc_dir / "page_001.jpg").write_bytes(b"fake jpg")

        result = get_page_image_path(str(tmp_path), "doc001", "vol1", 1)
        assert result is not None
        assert "page_001.jpg" in result

    def test_not_found(self, tmp_path):
        """이미지가 없으면 None."""
        doc_dir = tmp_path / "documents" / "doc001" / "L1_source"
        doc_dir.mkdir(parents=True)

        result = get_page_image_path(str(tmp_path), "doc001", "vol1", 1)
        assert result is None

    def test_no_source_dir(self, tmp_path):
        """L1_source 디렉토리 자체가 없으면 None."""
        result = get_page_image_path(str(tmp_path), "doc001", "vol1", 1)
        assert result is None


class TestNativeRenderScale:
    """스캔 PDF는 내장 이미지 해상도에 맞춰 렌더한다 (D-087)."""

    @staticmethod
    def _pdf_with_image(path, page_w, page_h, img_w, img_h, cover=1.0):
        import fitz

        img = Image.new("RGB", (img_w, img_h), "white")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        doc = fitz.open()
        page = doc.new_page(width=page_w, height=page_h)
        rect = fitz.Rect(0, 0, page_w * cover, page_h * cover)
        page.insert_image(rect, stream=buf.getvalue())
        doc.save(str(path))
        doc.close()

    def test_scanned_page_renders_at_image_resolution(self, tmp_path):
        import fitz

        from src.ocr.image_utils import native_render_scale

        pdf = tmp_path / "scan.pdf"
        self._pdf_with_image(pdf, 400, 600, 2000, 3000)  # 5 px/pt
        with fitz.open(str(pdf)) as doc:
            assert abs(native_render_scale(doc[0]) - 5.0) < 0.05

    def test_text_only_page_keeps_default(self, tmp_path):
        import fitz

        from src.ocr.image_utils import DEFAULT_RENDER_SCALE, native_render_scale

        pdf = tmp_path / "text.pdf"
        doc = fitz.open()
        doc.new_page(width=400, height=600).insert_text((40, 80), "text", fontsize=20)
        doc.save(str(pdf))
        with fitz.open(str(pdf)) as d:
            assert native_render_scale(d[0]) == DEFAULT_RENDER_SCALE

    def test_small_illustration_is_ignored(self, tmp_path):
        import fitz

        from src.ocr.image_utils import DEFAULT_RENDER_SCALE, native_render_scale

        pdf = tmp_path / "ill.pdf"
        self._pdf_with_image(pdf, 400, 600, 2000, 3000, cover=0.3)  # 쪽의 9%
        with fitz.open(str(pdf)) as d:
            assert native_render_scale(d[0]) == DEFAULT_RENDER_SCALE

    def test_long_side_is_capped(self, tmp_path):
        import fitz

        from src.ocr.image_utils import MAX_RENDER_LONG_SIDE, native_render_scale

        pdf = tmp_path / "huge.pdf"
        self._pdf_with_image(pdf, 400, 600, 6000, 9000)  # 15 px/pt → 9000px는 상한 초과
        with fitz.open(str(pdf)) as d:
            scale = native_render_scale(d[0])
            assert abs(scale * 600 - MAX_RENDER_LONG_SIDE) < 1

    def test_load_page_image_from_pdf_uses_native_scale(self, tmp_path):
        from src.ocr.image_utils import load_page_image_from_pdf

        doc_dir = tmp_path / "documents" / "d" / "L1_source"
        doc_dir.mkdir(parents=True)
        self._pdf_with_image(doc_dir / "v1.pdf", 400, 600, 2000, 3000)
        (tmp_path / "documents" / "d" / "manifest.json").write_text(
            '{"parts": [{"part_id": "v1", "file": "L1_source/v1.pdf"}]}', encoding="utf-8"
        )
        img = load_page_image_from_pdf(str(tmp_path), "d", 1, part_id="v1")
        assert img is not None and img.size == (2000, 3000)
        fixed = load_page_image_from_pdf(str(tmp_path), "d", 1, scale=2.0, part_id="v1")
        assert fixed.size == (800, 1200)
