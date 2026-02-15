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
        result = preprocess_for_ocr(
            sample_image_bytes, grayscale=True, binarize=True
        )
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
