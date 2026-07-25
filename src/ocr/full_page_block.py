"""페이지 전면을 덮는 LayoutBlock 하나를 만든다 (근현대 단일 컬럼 문헌용).

왜 필요한가:
    OCR 파이프라인은 L3 레이아웃의 LayoutBlock을 입구로 삼는다(D-009).
    블록이 없으면 OCR이 조용히 0건을 반환한다
    (status="partial", errors=["L3 레이아웃을 찾을 수 없습니다"]).

    고서는 한 페이지에 본문(大字)·주석(小字雙行)·판심제·장차가 섞여 있어
    영역을 나누는 일이 반드시 필요하다(D-002). 그러나 근현대 논문은
    대개 단일 컬럼이라 나눌 것이 없다. 그런데도 사용자는 "레이아웃 탭 →
    자동감지"를 거쳐야 하고, 기본 자동감지 엔진은 고전적 전용 모델이다.

    페이지 전체를 덮는 블록 하나를 만들어 두면 기존 파이프라인이
    **한 줄도 바뀌지 않고** 그대로 동작한다. 블록이 하나이므로
    "OCR이 읽는 순서를 지정한다"는 D-002의 의미론과도 어긋나지 않는다.

왜 파이프라인을 고치지 않는가:
    D-009는 "OcrPipeline을 통해서만 실행한다(엔진 직접 호출 금지)"와
    L3 → crop → 엔진 → L2 흐름을 계약으로 못박았다. 이 모듈은 그 계약의
    입력을 채워 줄 뿐 계약 자체를 건드리지 않는다. 나중에 좌표를 주는
    한글 엔진이 생기면 같은 경로가 그대로 줄 단위로 승격된다.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 페이지 이미지를 렌더할 때 쓰는 배율. image_utils.load_page_image_from_pdf()의
# 기본값과 같아야 L3의 image_width가 실제 렌더 크기와 맞는다. (2.0 = 144 DPI)
DEFAULT_RENDER_SCALE = 2.0

def full_page_block_id(page_number: int) -> str:
    """전면 블록의 ID를 만든다.

    layout_page.schema.json의 block_id는 '^p\\d+_b\\d+$' 패턴을 강제한다
    (예: p01_b01). 전용 이름("page_full")을 쓸 수 없으므로 이 규약을 따른다.
    블록이 하나뿐이므로 항상 b01이다.
    """
    return f"p{page_number:02d}_b01"


def is_full_page_layout(layout: dict) -> bool:
    """이 레이아웃이 자동 생성된 전면 블록인지 판별한다.

    입력: L3 레이아웃 dict.
    출력: 블록이 하나뿐이고 그 블록이 페이지 거의 전체를 덮으면 True.

    왜 ID로 판별하지 않는가: 스키마의 block_id 패턴 때문에 전용 이름을 쓸 수
    없다. 대신 "블록 1개 + 전면 덮음"이라는 형태로 알아본다.
    """
    blocks = layout.get("blocks") or []
    if len(blocks) != 1:
        return False
    bbox = blocks[0].get("bbox") or []
    width = layout.get("image_width")
    height = layout.get("image_height")
    if len(bbox) != 4 or not width or not height:
        return False
    covers = (bbox[2] - bbox[0]) >= width * 0.99 and (bbox[3] - bbox[1]) >= height * 0.99
    return bool(covers)


def build_full_page_layout(
    page_width_pt: float,
    page_height_pt: float,
    part_id: str,
    page_number: int,
    *,
    writing_direction: str = "horizontal_ltr",
    render_scale: float = DEFAULT_RENDER_SCALE,
) -> dict:
    """페이지 전면 블록 하나를 가진 L3 레이아웃 dict를 만든다.

    입력:
        page_width_pt / page_height_pt — PDF 페이지 크기(포인트, 72 DPI 기준).
        writing_direction — 근현대 문헌은 가로쓰기 좌→우가 기본.
        render_scale — 픽셀 좌표를 만들 때 쓸 렌더 배율.
    출력: layout_page.schema.json을 만족하는 dict.

    왜 bbox가 픽셀인가: L3의 bbox는 렌더된 페이지 이미지의 픽셀 좌표계를
    쓴다(image_width/image_height와 같은 기준). 파이프라인이 이 좌표로
    이미지를 자르므로 포인트가 아니라 픽셀이어야 한다.

    왜 정수로 반올림하는가: layout_page.schema.json이 image_width/height를
    `integer`로 규정한다(픽셀 수는 원래 정수다). PDF 페이지 크기는 실수라
    (예: 495.36pt × 2.0 = 990.72) 반올림하지 않으면 스키마 검증에 걸린다.
    실제로 합성 PDF(595pt → 1190.0)에서는 우연히 통과하고 실제 논문에서만
    터지는 형태였다. bbox는 스키마가 `number`라 실수도 되지만, 같은 좌표계를
    쓰는 값이므로 함께 정수로 맞춘다.
    """
    image_width = round(page_width_pt * render_scale)
    image_height = round(page_height_pt * render_scale)
    return {
        "part_id": part_id,
        "page_number": page_number,
        "image_width": image_width,
        "image_height": image_height,
        # 스키마의 enum(llm/manual/hybrid/auto_detect/null) 안에서 고른다.
        # 전용 값을 새로 만들면 layout_page.schema.json을 고쳐야 하는데,
        # lite mode는 저장 데이터에 아무것도 추가하지 않는다는 것이 설계 전제다.
        # 전면 블록인지는 is_full_page_layout()이 형태로 판별한다.
        "analysis_method": "auto_detect",
        "blocks": [
            {
                "block_id": full_page_block_id(page_number),
                "block_type": "main_text",
                "bbox": [0, 0, image_width, image_height],
                "reading_order": 1,
                "writing_direction": writing_direction,
                "skip": False,
            }
        ],
    }


def ensure_full_page_block(
    doc_path: str | Path,
    part_id: str,
    page_number: int,
    *,
    writing_direction: str = "horizontal_ltr",
    render_scale: float = DEFAULT_RENDER_SCALE,
) -> dict:
    """해당 페이지에 OCR 대상 블록이 없으면 전면 블록을 만들어 저장한다.

    입력:
        doc_path — 문헌 디렉토리. part_id — 권 식별자. page_number — 1-based.
    출력: {"created": bool, "reason": str, "block_count": int}

    왜 이미 있으면 건드리지 않는가:
        사용자가 손으로 잡았거나 자동감지로 만든 레이아웃을 덮어쓰면
        그 작업이 사라진다. 이 함수는 **비어 있을 때만** 채운다.

    Raises:
        FileNotFoundError: 문헌 또는 part의 PDF를 찾을 수 없을 때.
    """
    import fitz

    from core.document import get_page_layout, get_pdf_path, save_page_layout

    doc_path = Path(doc_path).resolve()

    # 이미 블록이 있으면 그대로 둔다.
    try:
        existing = get_page_layout(doc_path, part_id, page_number)
    except (FileNotFoundError, OSError):
        existing = None
    if existing and existing.get("blocks"):
        return {
            "created": False,
            "reason": "이미 레이아웃 블록이 있습니다.",
            "block_count": len(existing["blocks"]),
        }

    # PDF에서 페이지 크기를 읽는다. page.rect는 72 DPI(1x) 기준이다.
    pdf_path = get_pdf_path(doc_path, part_id)
    doc = fitz.open(str(pdf_path))
    try:
        if not 1 <= page_number <= doc.page_count:
            raise FileNotFoundError(
                f"{page_number}쪽은 이 권의 범위(1~{doc.page_count})를 벗어납니다.\n"
                "→ 해결: 쪽 번호를 확인하세요."
            )
        rect = doc[page_number - 1].rect
        width_pt, height_pt = rect.width, rect.height
    finally:
        doc.close()

    layout = build_full_page_layout(
        width_pt,
        height_pt,
        part_id,
        page_number,
        writing_direction=writing_direction,
        render_scale=render_scale,
    )
    save_page_layout(doc_path, part_id, page_number, layout)
    logger.info(
        f"전면 레이아웃 블록 생성: {doc_path.name}/{part_id}/page_{page_number:03d} "
        f"({layout['image_width']}×{layout['image_height']}px)"
    )
    return {
        "created": True,
        "reason": "레이아웃이 없어 페이지 전면 블록을 만들었습니다.",
        "block_count": 1,
    }
