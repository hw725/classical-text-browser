"""이미지 유틸리티: 크롭, 전처리, PDF→이미지 변환.

입력: 전체 페이지 이미지 + LayoutBlock의 bbox
출력: 크롭된 블록 이미지 (bytes)

bbox 형식:
  [x, y, width, height] — 0.0~1.0 비율.
  예: [0.1, 0.05, 0.35, 0.9] → 왼쪽 10%, 위 5%에서 시작, 폭 35%, 높이 90%.
"""

from __future__ import annotations
import io
from pathlib import Path
from typing import Optional

from PIL import Image

from .base import OcrEngineError


def load_page_image(image_path: str) -> Image.Image:
    """페이지 이미지를 로드한다.

    입력: 이미지 파일 경로 (PNG, JPEG, TIFF 등)
    출력: PIL Image 객체

    에러: OcrEngineError — 파일을 열 수 없을 때
    """
    try:
        img = Image.open(image_path)
        img.load()  # lazy loading 방지
        return img
    except Exception as e:
        raise OcrEngineError(f"이미지를 열 수 없습니다: {image_path} — {e}")


def crop_block(
    page_image: Image.Image,
    bbox: list[float],
    padding_px: int = 2,
) -> bytes:
    """페이지 이미지에서 블록 영역을 크롭한다.

    입력:
      page_image: 전체 페이지 PIL Image
      bbox: 두 가지 형식 모두 지원:
        - [x1, y1, x2, y2] 픽셀 좌표 (L3 layout 형식, 값 > 1)
        - [x, y, width, height] 비율 좌표 (LLM 분석 형식, 값 0.0~1.0)
      padding_px: 크롭 영역에 추가할 여백 (픽셀). 글자가 잘리는 것 방지.

    출력: 크롭된 이미지의 PNG 바이트

    왜 자동 감지인가:
      L3 layout은 [x1,y1,x2,y2] 픽셀로 저장하고,
      LLM 레이아웃 분석은 [x,y,w,h] 비율로 반환한다.
      두 경로 모두 이 함수를 사용하므로, 형식을 자동 감지한다.
    """
    img_w, img_h = page_image.size

    # 자동 감지: 모든 값이 0~1 범위이면 비율, 아니면 픽셀 좌표
    is_ratio = all(0 <= v <= 1.0 for v in bbox)

    if is_ratio:
        # 비율 [x, y, width, height] → 픽셀
        x, y, w, h = bbox
        x_min = int(x * img_w) - padding_px
        y_min = int(y * img_h) - padding_px
        x_max = int((x + w) * img_w) + padding_px
        y_max = int((y + h) * img_h) + padding_px
    else:
        # 픽셀 [x1, y1, x2, y2] — L3 layout 형식
        x1, y1, x2, y2 = bbox
        x_min = int(x1) - padding_px
        y_min = int(y1) - padding_px
        x_max = int(x2) + padding_px
        y_max = int(y2) + padding_px

    # 범위 제한
    x_min = max(0, x_min)
    y_min = max(0, y_min)
    x_max = min(img_w, x_max)
    y_max = min(img_h, y_max)

    if x_max <= x_min or y_max <= y_min:
        raise OcrEngineError(
            f"유효하지 않은 크롭 영역: bbox={bbox}, image_size=({img_w}, {img_h})"
        )

    cropped = page_image.crop((x_min, y_min, x_max, y_max))

    # PNG 바이트로 변환
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()


def preprocess_for_ocr(
    image_bytes: bytes,
    writing_direction: str = "vertical_rtl",
    grayscale: bool = True,
    binarize: bool = False,
    binarize_threshold: int = 128,
) -> bytes:
    """OCR 정확도를 높이기 위한 이미지 전처리.

    입력: 크롭된 이미지 바이트
    출력: 전처리된 이미지 바이트

    옵션:
      grayscale: 그레이스케일 변환 (대부분의 고전 텍스트는 흑백)
      binarize: 이진화 (흑/백만 남김)
      binarize_threshold: 이진화 임계값 (0~255)

    주의:
      PaddleOCR은 자체 전처리가 있어서 기본적으로는 grayscale만.
      다른 엔진에서 필요하면 binarize도 사용.
    """
    img = Image.open(io.BytesIO(image_bytes))

    if grayscale and img.mode != "L":
        img = img.convert("L")

    if binarize:
        img = img.point(lambda x: 255 if x > binarize_threshold else 0, mode="1")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_page_image_path(
    library_root: str,
    doc_id: str,
    part_id: str,
    page_number: int,
) -> Optional[str]:
    """L1 이미지의 파일 경로를 찾는다.

    입력:
      library_root: 서고 루트 경로
      doc_id: 문서 ID
      part_id: 파트 ID
      page_number: 페이지 번호 (1-indexed)

    출력: 이미지 파일 경로 (없으면 None)

    실제 프로젝트 경로 규칙:
      {library_root}/documents/{doc_id}/L1_source/ 아래에서 이미지를 탐색.
      이미지 파일이 없으면 None 반환 (PDF 추출은 load_page_image_from_pdf 사용).

    탐색 순서 — 페이지 번호에 해당하는 이미지 파일을 찾는다:
      1. {part_id}_page_{NNN}.{ext}  (프로젝트 네이밍 컨벤션)
      2. page_{NNN}.{ext}            (간단한 형식)
      3. *_p{NNN}.{ext}             (외부 다운로드 이미지)
    """
    source_dir = Path(library_root) / "documents" / doc_id / "L1_source"

    if not source_dir.exists():
        return None

    page_str = f"page_{page_number:03d}"
    extensions = ("png", "jpg", "jpeg", "tiff", "tif")

    # 1순위: {part_id}_page_{NNN}.{ext} (프로젝트 네이밍 컨벤션)
    for ext in extensions:
        path = source_dir / f"{part_id}_{page_str}.{ext}"
        if path.exists():
            return str(path)

    # 2순위: page_{NNN}.{ext}
    for ext in extensions:
        path = source_dir / f"{page_str}.{ext}"
        if path.exists():
            return str(path)

    # 3순위: 패턴 매칭으로 p{NNN} 포함 이미지 탐색
    for pattern in [f"*_p{page_number:03d}.*", f"*_p{page_number:04d}.*"]:
        matches = list(source_dir.glob(pattern))
        for m in matches:
            if m.suffix.lower().lstrip(".") in extensions:
                return str(m)

    return None


def load_page_image_from_pdf(
    library_root: str,
    doc_id: str,
    page_number: int,
    scale: float = 2.0,
) -> Optional[Image.Image]:
    """L1_source의 PDF에서 특정 페이지를 이미지로 추출한다.

    입력:
      library_root: 서고 루트 경로
      doc_id: 문서 ID
      page_number: 페이지 번호 (1-indexed)
      scale: 렌더링 배율 (기본 2.0 = 144 DPI)

    출력: PIL Image 객체 (없으면 None)

    왜 필요한가:
      L1_source에 PDF만 있고 개별 이미지가 없는 경우,
      OCR을 위해 PDF에서 페이지를 추출해야 한다.
      pymupdf(fitz)를 사용 (없으면 None 반환).
    """
    source_dir = Path(library_root) / "documents" / doc_id / "L1_source"
    if not source_dir.exists():
        return None

    pdf_files = list(source_dir.glob("*.pdf"))
    if not pdf_files:
        return None

    try:
        import fitz  # pymupdf

        doc = fitz.open(str(pdf_files[0]))
        # page_number는 1-indexed, fitz는 0-indexed
        page_idx = page_number - 1
        if page_idx < 0 or page_idx >= len(doc):
            doc.close()
            return None

        pdf_page = doc[page_idx]
        pix = pdf_page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        # PNG 바이트 → PIL Image
        from io import BytesIO
        pil_image = Image.open(BytesIO(pix.tobytes("png")))
        doc.close()
        return pil_image
    except ImportError:
        # pymupdf가 설치되지 않은 경우
        return None
    except Exception:
        return None
