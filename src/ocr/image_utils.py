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

    # 좌표 정규화: LLM이 x_min > x_max 또는 y_min > y_max로 반환할 수 있음
    if x_min > x_max:
        x_min, x_max = x_max, x_min
    if y_min > y_max:
        y_min, y_max = y_max, y_min

    # 범위 제한
    x_min = max(0, x_min)
    y_min = max(0, y_min)
    x_max = min(img_w, x_max)
    y_max = min(img_h, y_max)

    if x_max <= x_min or y_max <= y_min:
        raise OcrEngineError(f"유효하지 않은 크롭 영역: bbox={bbox}, image_size=({img_w}, {img_h})")

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
    max_long_side: int = 1600,
) -> bytes:
    """OCR 정확도를 높이기 위한 이미지 전처리.

    입력: 크롭된 이미지 바이트
    출력: 전처리된 이미지 바이트 (JPEG, 최대 max_long_side px)

    옵션:
      grayscale: 그레이스케일 변환 (대부분의 고전 텍스트는 흑백)
      binarize: 이진화 (흑/백만 남김)
      binarize_threshold: 이진화 임계값 (0~255)
      max_long_side: 긴 변 최대 픽셀 수. LLM 비전 모델은
          내부적으로 리사이즈하므로 고해상도가 불필요하고,
          대용량 이미지는 API 타임아웃/거부를 유발한다.

    주의:
      PaddleOCR은 자체 전처리가 있어서 기본적으로는 grayscale만.
      다른 엔진에서 필요하면 binarize도 사용.
    """
    img = Image.open(io.BytesIO(image_bytes))

    # 긴 변 기준 리사이즈 (비율 유지)
    img = _resize_if_needed(img, max_long_side)

    if grayscale and img.mode != "L":
        img = img.convert("L")

    if binarize:
        img = img.point(lambda x: 255 if x > binarize_threshold else 0, mode="1")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def resize_for_llm(image_bytes: bytes, max_long_side: int = 1600) -> bytes:
    """LLM 비전 호출용 이미지 리사이즈 + JPEG 압축.

    입력: 원본 이미지 바이트 (PNG, JPEG 등)
    출력: 리사이즈된 JPEG 바이트

    왜 필요한가:
      PDF에서 추출한 페이지 이미지는 10MB 이상이 될 수 있다.
      base64 인코딩하면 14MB+ → Ollama 클라우드 프록시가 타임아웃/거부.
      LLM 비전 모델은 내부적으로 리사이즈하므로 1600px이면 충분하다.
    """
    img = Image.open(io.BytesIO(image_bytes))
    img = _resize_if_needed(img, max_long_side)

    # RGB로 변환 (RGBA/P 등은 JPEG 불가)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _resize_if_needed(img: Image.Image, max_long_side: int) -> Image.Image:
    """긴 변이 max_long_side보다 크면 비율 유지하며 축소."""
    w, h = img.size
    long_side = max(w, h)
    if long_side <= max_long_side:
        return img
    scale = max_long_side / long_side
    new_w = int(w * scale)
    new_h = int(h * scale)
    return img.resize((new_w, new_h), Image.LANCZOS)


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


def resolve_part_pdf(doc_path: Path, part_id: Optional[str]) -> Optional[Path]:
    """문헌 디렉터리에서 **그 권의** PDF 경로를 찾는다.

    입력: doc_path — 문헌 디렉터리. part_id — 권 식별자(예: "vol2"). None이면 첫 권.
    출력: PDF 경로. 찾지 못하면 None.

    왜 이 함수가 필요한가 — **엉뚱한 권을 읽는 사고를 막기 위해서다.**
    `glob("*.pdf")[0]`을 쓰면 안 된다 — glob은 순서를 보장하지 않을뿐더러
    part_id를 아예 보지 않는다. 卷上·卷下가 함께 있는 문헌에서 2권 5쪽을
    OCR 하면 **1권 5쪽 이미지가 LLM에 넘어가고**, 오류 없이 그럴듯한 결과가
    저장된다. 원본과 텍스트의 대응이 조용히 끊어지는 것이라 발견하기가
    가장 어려운 종류다.

    manifest의 parts[].file이 정본이다(`core.document.get_pdf_path`). 그것을
    못 읽을 때만 파일 이름 정렬로 물러난다 — glob 순서에 기대지 않는다.
    """
    try:
        from core.document import get_pdf_path

        return get_pdf_path(doc_path, part_id)
    except Exception:  # noqa: BLE001 — manifest가 없거나 깨진 옛 문헌
        pass

    source_dir = doc_path / "L1_source"
    if not source_dir.exists():
        return None
    # 이름 순으로 정렬한다. vol1 → vol2 순서가 되어 «첫 권»이 실제로 첫 권이다.
    pdfs = sorted(source_dir.glob("*.pdf"), key=lambda p: p.name)
    if not pdfs:
        return None
    if part_id:
        for p in pdfs:
            if part_id.lower() in p.stem.lower():
                return p
    return pdfs[0]


# PDF 쪽을 렌더할 때의 기본(최소) 배율. 2.0 = 144 DPI. 글자만 있는 PDF는 이 배율로
# 충분하고, L3·L2·텍스트 레이어 내보내기가 예전부터 이 값을 전제로 좌표를 다뤘다.
DEFAULT_RENDER_SCALE = 2.0
# 렌더 결과의 긴 변 상한(px). 스캔 해상도가 아무리 높아도 이 위로는 키우지 않는다 —
# NDL 행 탐지는 1280px로 줄여 쓰고, PARSeq 행 크롭은 32px 높이라 그 이상은 시간만 든다.
MAX_RENDER_LONG_SIDE = 4000


def native_render_scale(page, default: float = DEFAULT_RENDER_SCALE) -> float:
    """쪽에 깔린 스캔 이미지의 화소 밀도에 맞는 렌더 배율을 구한다 (D-087).

    입력: fitz.Page
    출력: 배율(pt→px). 스캔 이미지가 없으면 default. default보다 작아지지는 않고,
          긴 변이 MAX_RENDER_LONG_SIDE를 넘지 않게 잡는다.

    왜 필요한가: 스캔 PDF는 300dpi 이상의 이미지를 담고 있는데 2.0(144dpi)으로 렌더하면
    원본 화소의 절반 이하만 엔진에 간다. 합성 쪽 실측에서 해상도 절반이 CER을
    0.087→0.106으로 올렸다(D-086). 원본 ndlkotenocr-lite는 스캔 파일을 그대로 읽는다.

    왜 이미지를 직접 꺼내지 않고 «그 배율로 렌더»하는가: 회전·자르기·여러 장 합성이
    있는 쪽도 렌더는 좌표계를 그대로 지킨다. 화소 밀도는 넓이의 제곱근으로 재서
    90도 회전에도 같은 값이 나온다. 쪽 넓이의 절반이 안 되는 이미지(삽화·도장)는 무시.
    """
    try:
        rect = page.rect
        page_area = float(rect.width * rect.height)
        if page_area <= 0:
            return default
        best = 0.0
        for info in page.get_image_info():
            bbox = info.get("bbox")
            w_px, h_px = info.get("width") or 0, info.get("height") or 0
            if not bbox or w_px <= 0 or h_px <= 0:
                continue
            bw, bh = float(bbox[2] - bbox[0]), float(bbox[3] - bbox[1])
            if bw <= 0 or bh <= 0 or (bw * bh) / page_area < 0.5:
                continue
            best = max(best, ((w_px * h_px) / (bw * bh)) ** 0.5)
        scale = max(default, best) if best > 0 else default
        long_pt = float(max(rect.width, rect.height))
        if long_pt > 0:
            scale = min(scale, MAX_RENDER_LONG_SIDE / long_pt)
        return scale
    except Exception:  # noqa: BLE001 — 배율 추정 실패는 기본값으로
        return default


def load_page_image_from_pdf(
    library_root: str,
    doc_id: str,
    page_number: int,
    scale: Optional[float] = None,
    part_id: Optional[str] = None,
) -> Optional[Image.Image]:
    """L1_source의 PDF에서 특정 페이지를 이미지로 추출한다.

    입력:
      library_root: 서고 루트 경로
      doc_id: 문서 ID
      page_number: 페이지 번호 (1-indexed)
      scale: 렌더링 배율. None(기본)이면 쪽에 깔린 스캔 이미지의 해상도에 맞춘다
             (native_render_scale, 최소 2.0). 숫자를 주면 그 배율로 고정.
      part_id: 권 식별자. **다권본에서는 반드시 넘겨야 한다** — 없으면 첫 권을 읽는다.

    출력: PIL Image 객체 (없으면 None)

    왜 필요한가:
      L1_source에 PDF만 있고 개별 이미지가 없는 경우,
      OCR을 위해 PDF에서 페이지를 추출해야 한다.
      pymupdf(fitz)를 사용 (없으면 None 반환).
    """
    doc_path = Path(library_root) / "documents" / doc_id
    pdf_path = resolve_part_pdf(doc_path, part_id)
    if pdf_path is None or not pdf_path.exists():
        return None

    try:
        import fitz  # pymupdf
    except ImportError:
        # pymupdf가 설치되지 않은 경우
        return None

    # with를 쓰는 이유: 예외가 나도 파일 핸들이 반드시 닫힌다. Windows에서는
    # 핸들이 남으면 그 PDF가 잠겨 다음 작업(문헌 삭제·이동)이 부분 실패한다.
    try:
        with fitz.open(str(pdf_path)) as doc:
            # page_number는 1-indexed, fitz는 0-indexed
            page_idx = page_number - 1
            if page_idx < 0 or page_idx >= len(doc):
                return None
            page = doc[page_idx]
            if scale is None:
                scale = native_render_scale(page)
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            # PNG 바이트 → PIL Image
            from io import BytesIO

            return Image.open(BytesIO(pix.tobytes("png")))
    except Exception:
        return None
