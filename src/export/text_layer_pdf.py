"""L1 원본 스캔 PDF에 보이지 않는 텍스트 레이어를 얹어 새 PDF를 입힌다.

왜 이 모듈이 필요한가:
    스캔본에서 뽑은 텍스트를 사이드카 .txt로만 내면 반쪽이다.
    텍스트 레이어를 원본 이미지 위에 입혀 넣으면 다음이 한꺼번에 살아난다.
      - 뷰어에서 복사·Ctrl+F
      - 구조 분석(PageIndex)·참고문헌 추출 도구가 그대로 동작
      - 인용 마커와 p.N 점프
    사이드카 텍스트로는 이 넷 중 어느 것도 그냥 되지 않는다.

어떻게 하는가:
    PDF 표준의 render_mode 3 = "invisible"이다. 글자를 그리되 화면에는
    칠하지 않는다. 원본 이미지는 그대로 보이고 그 위에 검색 가능한
    텍스트만 겹친다. OCRmyPDF가 하는 일과 같은 원리이며,
    PyMuPDF만으로 되므로 새 의존성이 필요 없다.

폰트를 왜 임베드하는가 (기본값 embed_font=True):
    처음에는 임베드하지 않았다. Adobe-Korea1 CID 폰트를 참조만 하면
    쪽당 +0.9KB로 끝나기 때문이다(실측 2026-07-25).

    그런데 실제 논문에서 **글자가 조용히 사라졌다.** 전수 집계
    (실측 2026-07-26, 15쪽 논문): L2에는 있는데 PDF에 없는 글자가
    **51종 130자.** `郎`(27회) `儂`(22회) `研`(16회) — 전부 한자이고
    하필 한시 인용문에 몰려 있었다. Adobe-Korea1 charset에 없는 글자를
    insert_text가 버린 것이다. 처음 실측이 «정상»이라고 한 것은
    시험 텍스트가 우연히 그 charset 안에 있었기 때문이다.

    임베드하면 누락이 51종 130자 → **2종 2자**로 줄고(남은 둘은 OCR이
    잘못 읽은 한글 자모 조각이라 폰트 문제가 아니다), 크기는
    **쪽당 +4.9KB**다. 3,358쪽이면 +16MB — 검색되지 않는 한자와 바꿀
    값이 아니다.

    산출물의 계약은 «검색되는 PDF»다. 연구자가 가장 찾고 싶어 할 글자가
    빠지면 그 계약이 깨진다. 그래서 크기를 치르고 임베드한다.
    embed_font=False로 끌 수 있지만, 그때는 위 손실을 감수하는 것이다.

좌표를 어떻게 되돌리는가:
    OCR 결과의 bbox는 **렌더된 페이지 이미지의 픽셀** 좌표다(base.py 참조).
    PDF의 좌표 단위는 포인트(72 DPI)다. 그래서 배율로 나눠야 한다.
    배율은 L3 레이아웃의 image_width를 PDF 페이지 폭으로 나눠 구한다.
    L3가 없으면 저장소 기본 렌더 배율 2.0(=144 DPI)을 쓴다.

원본은 건드리지 않는다:
    L1_source/의 파일은 절대 수정하지 않고(CLAUDE.md 규칙),
    결과는 <문헌>/exports/ 아래에 새 파일로 쓴다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import fitz

from core.document import get_pdf_path

logger = logging.getLogger(__name__)

# 저장소가 페이지 이미지를 렌더할 때 쓰는 기본 배율.
# image_utils.load_page_image_from_pdf()의 scale 기본값이자
# llm_ocr.py가 하드코딩한 fitz.Matrix(2.0, 2.0)과 같은 값이다(=144 DPI).
DEFAULT_RENDER_SCALE = 2.0

# 임베드 없이 쓰는 PDF 표준 CJK 폰트. 한글·한자·라틴을 모두 담는다.
CJK_FONT = "korea"

# 좌표가 없어 줄을 순서대로 늘어놓을 때, 페이지 상하좌우에 두는 여백(포인트).
PAGE_MARGIN = 40.0


@dataclass
class EmbedResult:
    """텍스트 레이어 입히기 결과 요약.

    왜 dataclass인가: 라우터가 그대로 JSON으로 돌려주고,
    테스트가 필드 단위로 검증할 수 있게 하기 위함이다.
    """

    output_path: str
    total_pages: int
    embedded_pages: int  # 텍스트를 실제로 얹은 쪽 수
    skipped_pages: int  # OCR 결과가 없어 건너뛴 쪽 수
    total_lines: int
    positioned_lines: int  # bbox가 있어 제자리에 놓은 줄 수
    approximated_lines: int  # 좌표가 없어 원본 자리가 아닌 곳에 늘어놓은 줄 수
    detected_lines: int  # 검출로 위치를 찾아 제자리에 놓은 줄 수
    size_bytes: int
    source_layer: str  # "l2"(OCR 결과) 또는 "l4"(교정 텍스트)
    embed_font: bool
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """API 응답용 dict로 변환한다."""
        return {
            "output_path": self.output_path,
            "total_pages": self.total_pages,
            "embedded_pages": self.embedded_pages,
            "skipped_pages": self.skipped_pages,
            "total_lines": self.total_lines,
            "positioned_lines": self.positioned_lines,
            "approximated_lines": self.approximated_lines,
            "detected_lines": self.detected_lines,
            "size_bytes": self.size_bytes,
            "source_layer": self.source_layer,
            "embed_font": self.embed_font,
            "warnings": self.warnings,
        }


def _l2_path(doc_path: Path, part_id: str, page_num: int) -> Path:
    """L2 OCR 결과 파일 경로를 조립한다.

    컨벤션은 pipeline._save_ocr_result()와 같아야 한다:
    L2_ocr/{part_id}_page_{NNN}.json
    """
    return doc_path / "L2_ocr" / f"{part_id}_page_{page_num:03d}.json"


def _l3_path(doc_path: Path, part_id: str, page_num: int) -> Path:
    """L3 레이아웃 파일 경로를 조립한다. (배율 계산에만 쓴다)"""
    return doc_path / "L3_layout" / f"{part_id}_page_{page_num:03d}.json"


def _read_json(path: Path) -> dict | None:
    """JSON을 읽되, 없거나 깨졌으면 None을 돌려준다.

    왜 예외를 삼키는가: 한 쪽의 결과가 깨졌다고 300쪽 입히기 전체가
    중단되면 안 된다. 호출부가 건너뛰고 warnings에 기록한다.
    """
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"읽을 수 없는 JSON을 건너뜁니다: {path} ({e})")
        return None


def _render_scale(doc_path: Path, part_id: str, page_num: int, pdf_width: float) -> float:
    """OCR bbox의 픽셀 좌표를 PDF 포인트로 되돌릴 배율을 구한다.

    입력:
        pdf_width — PDF 페이지의 폭(포인트).
    출력: 배율. pixel / scale = point.

    우선순위: L2의 image_width(D-087, bbox가 만들어진 바로 그 이미지) → L3의 image_width
    → 기본 2.0. L2 기록이 없는 옛 파일은 배율 2.0으로 렌더된 것이지만, L3에 다른 배율이
    적혀 있으면 그쪽이 더 정확할 수 있어 예전 순서를 유지한다.
    """
    l2 = _read_json(_l2_path(doc_path, part_id, page_num))
    if l2:
        image_width = l2.get("image_width")
        if isinstance(image_width, (int, float)) and image_width > 0 and pdf_width > 0:
            return float(image_width) / float(pdf_width)
    layout = _read_json(_l3_path(doc_path, part_id, page_num))
    if layout:
        image_width = layout.get("image_width")
        if isinstance(image_width, (int, float)) and image_width > 0 and pdf_width > 0:
            return float(image_width) / float(pdf_width)
    return DEFAULT_RENDER_SCALE


def _collect_lines(l2: dict) -> list[tuple[str, list[float] | None]]:
    """L2 OCR 결과에서 (텍스트, bbox) 목록을 읽기 순서대로 뽑는다.

    출력: [(text, bbox 또는 None), ...]
    bbox는 렌더 이미지의 픽셀 좌표 [x1, y1, x2, y2]이다.

    왜 bbox가 None일 수 있는가: LLM Vision 엔진은 좌표를 반환하지 않는다
    (llm_ocr_engine.py). 그런 줄은 호출부가 왼쪽 여백에 순서대로 늘어놓는다.
    """
    lines: list[tuple[str, list[float] | None]] = []
    for result in l2.get("ocr_results") or []:
        for line in result.get("lines") or []:
            text = (line.get("text") or "").strip()
            if not text:
                continue
            bbox = line.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4:
                lines.append((text, [float(c) for c in bbox]))
            else:
                lines.append((text, None))
    return lines


def _fit_fontsize(
    text: str,
    target_width: float,
    target_height: float,
    fontname: str,
    font: fitz.Font | None = None,
) -> float:
    """bbox 안에 텍스트가 꼭 맞도록 글자 크기를 정한다.

    입력:
        fontname — 임베드하지 않을 때 쓰는 PDF 표준 폰트 이름.
        font — 임베드할 때 실제로 쓰는 폰트 객체. 주어지면 이것으로 잰다.

    왜 폭까지 맞추는가: 보이지 않는 텍스트라도 **검색 하이라이트의 위치와
    길이**가 이 글자 크기로 정해진다. 높이만 보고 정하면 하이라이트가
    실제 글자보다 길거나 짧아져 어긋난 위치를 가리킨다.

    왜 «실제로 쓸 폰트»로 재야 하는가:
        임베드 폰트와 CID 폰트는 글리프 폭이 다르다. 항상 CID 기준으로
        재면 임베드했을 때 하이라이트가 **26% 좁아진다**(실측 2026-07-26:
        270pt 자리에 199pt). 쓰는 폰트와 재는 폰트가 같아야 한다.
    """
    # 높이 기준 후보. 행간을 감안해 0.85를 곱한다.
    size = max(target_height * 0.85, 1.0)
    if target_width > 0:
        try:
            measured = (
                font.text_length(text, fontsize=size)
                if font is not None
                else fitz.get_text_length(text, fontname=fontname, fontsize=size)
            )
        except Exception:  # noqa: BLE001 — 폰트에 없는 글리프 등. 높이 기준으로 둔다.
            measured = 0
        if measured > 0:
            # 폭이 넘치면 줄이고, 남으면 늘려서 bbox 폭에 맞춘다.
            size = size * (target_width / measured)
    # 지나치게 작거나 큰 값은 잘라낸다 (PDF 렌더러 호환).
    return max(1.0, min(size, 300.0))


def _embed_page(
    page: fitz.Page,
    lines: list[tuple[str, list[float] | None]],
    scale: float,
    fontname: str,
    font: fitz.Font | None,
) -> tuple[int, int, list[str]]:
    """한 쪽에 보이지 않는 텍스트를 얹는다.

    입력:
        page — 대상 PDF 페이지 (원본 이미지가 이미 들어 있다).
        lines — (텍스트, bbox) 목록. bbox는 이미지 픽셀 좌표이거나 None.
        scale — 픽셀 → 포인트 변환 배율.
        font — embed_font=True일 때만 주어지는 임베드용 폰트 객체.
    출력: (제자리에 놓은 줄 수, 자리를 몰라 늘어놓은 줄 수, 경고 목록)
    """
    positioned = 0
    approximated = 0
    warnings: list[str] = []

    page_rect = page.rect
    with_bbox = [(t, b) for t, b in lines if b is not None]
    without_bbox = [t for t, b in lines if b is None]

    # 원본 페이지가 남긴 좌표 변환을 끊는다. **이것이 없으면 텍스트가
    # 엉뚱한 크기·자리에 박힌다.**
    #
    # 무슨 일이 있었나: 스캔 PDF는 픽셀 단위로 작업하려고 내용 스트림 첫
    # 줄에 배율을 걸어 두는 일이 흔하다. 실제로 이 논문은 이렇게 시작한다.
    #
    #     0.24 0 0 0.24 0 0 cm     ← q 없이, 되돌리는 Q도 없다
    #     q 2064 0 0 2893 0 0 cm /I0 Do Q
    #
    # 첫 줄의 `cm`이 q/Q 밖에 있어 **그 뒤에 덧붙이는 모든 것이 0.24배로
    # 줄어든다.** 40pt 자리에 넣은 글자가 9.6pt 자리에, 12pt 글자가 2.88pt로
    # 들어갔다 — 495×694 쪽의 왼쪽 아래 구석에 우표만 하게. 텍스트는
    # 「있는데」 드래그로 잡히지도, 원문 위에서 형광이 뜨지도 않는다.
    #
    # 왜 이제야 드러났나: page.insert_text()는 자기 출력을 q/Q로 감싸 이
    # 영향을 받지 않는다. 폰트 임베드를 기본으로 바꾸면서(D-062) TextWriter
    # 경로로 갈아탔는데, TextWriter.write_text()는 감싸지 않는다.
    # 자동 테스트는 **PyMuPDF로 만든 깨끗한 시험 PDF**를 써서 이 상황이
    # 아예 생기지 않았다.
    #
    # wrap_contents()는 기존 스트림을 q…Q로 감싸 그 안에서 끝나게 한다.
    if not page.is_wrapped:
        page.wrap_contents()

    writer = fitz.TextWriter(page_rect) if font is not None else None

    def _emit(text: str, x: float, baseline_y: float, size: float) -> bool:
        """한 줄을 실제로 써넣는다. 성공하면 True.

        왜 예외를 잡는가: 폰트에 없는 글리프가 섞이면 PyMuPDF가 예외를
        던진다. 한 줄 때문에 전체가 실패하면 안 되므로 건너뛰고 기록한다.
        """
        try:
            if writer is not None:
                writer.append((x, baseline_y), text, font=font, fontsize=size)
            else:
                page.insert_text(
                    (x, baseline_y),
                    text,
                    fontname=fontname,
                    fontsize=size,
                    render_mode=3,  # invisible — 원본 이미지를 가리지 않는다
                )
            return True
        except (ValueError, RuntimeError) as e:
            warnings.append(f"줄을 건너뜀({text[:16]}…): {e}")
            return False

    # ── 1) 좌표가 있는 줄: 제자리에 놓는다
    for text, bbox in with_bbox:
        x0, y0, x1, y1 = (c / scale for c in bbox)
        height = max(y1 - y0, 1.0)
        width = max(x1 - x0, 1.0)
        size = _fit_fontsize(text, width, height, fontname, font)
        # 베이스라인은 박스 아래쪽에서 살짝 올린 지점.
        if _emit(text, x0, y1 - height * 0.2, size):
            positioned += 1

    # ── 2) 좌표가 없는 줄: 쪽 전체에 균등 배치한다
    #
    # 왜 이렇게라도 넣는가: 텍스트가 PDF 안에 있어야 복사·Ctrl+F·구조 분석·
    # 참고문헌 추출이 동작한다. 위치 정확도보다 텍스트의 존재가 먼저다.
    #
    # 다만 이것이 «대략의 위치»가 아니라는 점을 분명히 해 둔다. 좌표를 모르므로
    # 모든 줄이 왼쪽 여백에서 시작해 세로로 균등하게 놓인다. 검색했을 때
    # 형광은 한 줄 크기로 정확히 뜨지만 **그 자리에 원본 글자가 없다.**
    # 원본이 가운데 정렬이어도 형광은 왼쪽에 뜬다.
    # 이 사실은 호출부가 producer 메타데이터(page-approximated)에 남긴다.
    if without_bbox:
        usable_h = max(page_rect.height - PAGE_MARGIN * 2, 1.0)
        usable_w = max(page_rect.width - PAGE_MARGIN * 2, 1.0)
        step = usable_h / len(without_bbox)
        # 줄 간격이 너무 커지지 않도록 상한을 둔다.
        size_base = min(step * 0.8, 12.0)
        for idx, text in enumerate(without_bbox):
            baseline = PAGE_MARGIN + step * (idx + 1)
            size = _fit_fontsize(text, usable_w, size_base / 0.85, fontname, font)
            # 폭에 맞춘 크기가 행간보다 크면 겹치므로 잘라낸다.
            size = min(size, size_base)
            if _emit(text, PAGE_MARGIN, baseline, size):
                approximated += 1

    if writer is not None:
        writer.write_text(page, render_mode=3)

    return positioned, approximated, warnings


def embed_text_layer(
    doc_path: str | Path,
    part_id: str,
    *,
    output_path: str | Path | None = None,
    pages: list[int] | None = None,
    source_layer: str = "l2",
    embed_font: bool = True,
    use_line_detection: bool = True,
) -> EmbedResult:
    """문헌의 한 권(part)에 텍스트 레이어를 입혀 새 PDF를 만든다.

    입력:
        doc_path — 문헌 디렉토리 경로.
        part_id — 권 식별자 (예: "vol1").
        output_path — 결과 파일 경로. None이면 <문헌>/exports/{part_id}_text.pdf.
        pages — 대상 쪽 번호(1-based) 목록. None이면 전체.
        source_layer — "l2"(OCR 결과, 좌표 있음) 또는 "l4"(사람이 교정한 텍스트).
                       l4는 좌표가 없어 왼쪽 여백에 순서대로 놓인다.
        embed_font — 폰트를 임베드한다(기본 True). 끄면 쪽당 4.9KB를 아끼는
            대신 Adobe-Korea1에 없는 한자가 **조용히 사라진다**(위 설명 참조).
        use_line_detection — 좌표 없는 줄에 검출로 찾은 위치를 채운다.
            PaddleOCR가 없으면 조용히 건너뛴다. 끄면 항상 순서 배치가 된다.
    출력: EmbedResult.

    왜 원본을 복사해서 쓰는가: L1_source/의 PDF는 절대 수정하지 않는다.
    fitz.open()으로 연 뒤 다른 경로에 저장하므로 원본 파일은 그대로 남는다.

    Raises:
        FileNotFoundError: 문헌 또는 part의 PDF를 찾을 수 없을 때.
        ValueError: source_layer 값이 잘못됐을 때.
    """
    if source_layer not in ("l2", "l4"):
        raise ValueError(
            f"source_layer는 'l2' 또는 'l4'여야 합니다: {source_layer!r}\n"
            "→ l2 = OCR 결과(엔진에 따라 좌표 있음), "
            "l4 = 사람이 교정한 텍스트(좌표 없음 — 순서대로 배치)"
        )

    doc_path = Path(doc_path).resolve()
    pdf_path = get_pdf_path(doc_path, part_id)  # 없으면 여기서 한국어 예외가 난다

    if output_path is None:
        export_dir = doc_path / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        output_path = export_dir / f"{part_id}_text.pdf"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    font = fitz.Font(CJK_FONT) if embed_font else None

    doc = fitz.open(str(pdf_path))
    try:
        total_pages = doc.page_count
        targets = pages if pages is not None else list(range(1, total_pages + 1))

        embedded = skipped = total_lines = positioned = approximated = 0
        detected_lines = 0

        for page_num in targets:
            if not 1 <= page_num <= total_pages:
                warnings.append(f"{page_num}쪽은 PDF 범위(1~{total_pages})를 벗어나 건너뜁니다.")
                continue

            page = doc[page_num - 1]
            lines = _load_lines(doc_path, part_id, page_num, source_layer)
            if not lines:
                skipped += 1
                continue

            scale = _render_scale(doc_path, part_id, page_num, page.rect.width)

            # 좌표가 없는 줄에 «글자가 있는 자리»를 채워 넣는다.
            # LLM Vision은 텍스트만 주므로, 검출로 얻은 줄 위치와 순서를 맞춘다.
            # 실패하면 그대로 두고 아래에서 순서 배치로 물러난다.
            if use_line_detection:
                lines, filled = _fill_positions_by_detection(page, lines, scale)
                detected_lines += filled

            pos, approx, warns = _embed_page(page, lines, scale, CJK_FONT, font)

            total_lines += len(lines)
            positioned += pos
            approximated += approx
            warnings.extend(warns)
            if pos or approx:
                embedded += 1
            else:
                skipped += 1

        if embed_font:
            # 실제로 쓴 글리프만 남겨 파일 크기를 줄인다.
            try:
                doc.subset_fonts(verbose=False)
            except Exception as e:  # noqa: BLE001 — 서브셋 실패는 치명적이지 않다
                warnings.append(f"폰트 서브셋에 실패했습니다(크기만 커집니다): {e}")

        # 산출물의 출처와 정밀도를 파일 자체에 남긴다.
        # 왜: 나중에 이 PDF만 보고도 텍스트가 OCR 산출물인지,
        #     좌표가 근사인지 판별할 수 있어야 한다.
        precision = "line-positioned" if approximated == 0 else "page-approximated"
        doc.set_metadata(
            {
                **(doc.metadata or {}),
                "producer": (
                    f"classical-text-browser text-layer embed "
                    f"(source={source_layer}, precision={precision})"
                ),
            }
        )

        doc.save(str(output_path), garbage=3, deflate=True)
    finally:
        doc.close()

    # 만든 것을 **다시 열어 확인한다.**
    #
    # 왜 필요한가: 여기까지의 숫자(제자리 N줄)는 «넣으려고 시도한» 기록일 뿐
    # 결과가 아니다. 실제로 D-068에서, 줄 수와 좌표 계산이 전부 맞는데도
    # 원본 PDF가 남긴 좌표 변환에 끌려 글자가 0.24배로 쪽 구석에 박혔다.
    # 로그도 API 응답도 «30줄 제자리»라고 말했고 아무도 이상을 몰랐다.
    # 산출물을 직접 재어야만 그 부류가 드러난다.
    # 제자리에 놓았다고 주장한 쪽이 있을 때만 «잉크 위인가»까지 잰다.
    # 좌표를 못 얻어 순서대로 늘어놓은 쪽은 원래 글자 위가 아니다(이미 알린다).
    warnings.extend(_audit_output(output_path, check_ink=positioned > 0))

    size = output_path.stat().st_size
    logger.info(
        f"텍스트 레이어 입히기 완료: {output_path} — "
        f"{embedded}/{len(targets)}쪽, {positioned}줄 제자리"
        f"(검출 {detected_lines}줄 포함)·{approximated}줄 순서배치, "
        f"{size / 1024:.0f}KB"
    )

    return EmbedResult(
        output_path=str(output_path),
        total_pages=total_pages,
        embedded_pages=embedded,
        skipped_pages=skipped,
        total_lines=total_lines,
        positioned_lines=positioned,
        approximated_lines=approximated,
        detected_lines=detected_lines,
        size_bytes=size,
        source_layer=source_layer,
        embed_font=embed_font,
        warnings=warnings,
    )


def _ink_check(page, spans: list[dict]) -> float | None:
    """이 쪽의 텍스트가 **실제 글자 위**에 놓였는지 잉크 밀도로 잰다.

    입력: 대상 페이지와 그 쪽의 span 목록.
    출력: (텍스트가 덮은 자리의 검은 화소 비율) ÷ (쪽 전체 비율).
          1보다 충분히 크면 글자 위, 1 언저리 이하면 빈 곳이다. 잴 수 없으면 None.

    왜 이렇게까지 하는가: 줄 수·좌표 계산이 전부 맞아도 산출물이 틀릴 수
    있다는 것을 D-068에서 겪었다. 「몇 줄 넣었다」는 시도의 기록이지
    결과가 아니다. 원본은 이미지뿐이므로, 텍스트가 제자리인지 확인할
    유일한 방법은 **그 자리에 잉크가 있는지 보는 것**이다.

    실측(2026-07-26, 박준원 2001 1쪽): 제자리일 때 4.3배(25.6% vs 5.96%).
    """
    try:
        import numpy as np

        pix = page.get_pixmap(colorspace=fitz.csGRAY)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    except Exception:  # noqa: BLE001 — 렌더 실패는 확인을 포기할 뿐이다
        return None

    dark = arr < 128
    page_ratio = float(dark.mean())
    if page_ratio <= 0:
        return None  # 완전한 백지 — 비교할 기준이 없다

    # 쪽마다 최대 30줄만 본다. 전부 재도 결론은 같고 시간만 든다.
    sx = pix.width / max(page.rect.width, 1e-6)
    sy = pix.height / max(page.rect.height, 1e-6)
    hits = 0
    total = 0
    for s in spans[:30]:
        x0, y0, x1, y1 = s["bbox"]
        a = int(max(0, x0 * sx))
        b = int(max(0, y0 * sy))
        c = int(min(pix.width, x1 * sx))
        d = int(min(pix.height, y1 * sy))
        if c <= a or d <= b:
            continue
        region = dark[b:d, a:c]
        hits += int(region.sum())
        total += region.size
    if total == 0:
        return None
    return (hits / total) / page_ratio


def _audit_output(output_path: Path, *, check_ink: bool = False) -> list[str]:
    """만든 PDF를 다시 열어 텍스트가 «쓸 만한 자리에» 있는지 잰다.

    입력: 방금 저장한 PDF 경로.
    출력: 사람에게 보여 줄 경고 목록. 이상이 없으면 빈 목록.

    무엇을 재는가 (쪽마다):
        1. 글자 크기 — 너무 작으면 드래그로 잡히지 않는다.
        2. 텍스트가 덮는 넓이 — 한 구석에 뭉쳐 있으면 원문과 어긋난 것이다.
    두 가지 모두 D-068에서 실제로 벌어진 일이다(12pt → 2.88pt,
    495×694 쪽의 왼쪽 아래 100×150pt 구석).

    왜 «틀렸다»가 아니라 경고인가: 표지처럼 글자가 몇 자뿐인 쪽은 정상적으로도
    좁게 나온다. 막지 않고 알린다 — 판단은 사람이 한다.
    """
    MIN_FONT_PT = 5.0  # 이보다 작으면 화면에서 잡을 수 없다
    MIN_COVERAGE = 0.02  # 쪽 넓이의 2% 미만이면 뭉친 것으로 본다
    MIN_LINES_TO_JUDGE = 5  # 줄이 적은 쪽은 좁아도 정상이다
    MIN_INK_RATIO = 1.3  # 쪽 평균보다 이만큼은 진해야 «글자 위»로 본다
    INK_SAMPLE_PAGES = 3  # 잉크 확인은 표본만 — 300쪽을 다 렌더하지 않는다

    problems: list[str] = []
    try:
        doc = fitz.open(str(output_path))
    except Exception as e:  # noqa: BLE001 — 확인 자체가 실패해도 산출물은 남긴다
        return [f"산출물을 다시 열어 확인하지 못했습니다: {e}"]

    try:
        # 잉크를 확인할 표본 쪽: 처음·가운데·끝. 한쪽 끝만 보면 놓친다.
        n = doc.page_count
        ink_targets: set[int] = set()
        if check_ink and n:
            ink_targets = {1, (n + 1) // 2, n}
            ink_targets = set(sorted(ink_targets)[:INK_SAMPLE_PAGES])

        for idx, page in enumerate(doc, start=1):
            spans = [
                s
                for b in page.get_text("dict")["blocks"]
                if b["type"] == 0
                for line in b["lines"]
                for s in line["spans"]
            ]
            if not spans:
                continue

            smallest = min(s["size"] for s in spans)
            if smallest < MIN_FONT_PT:
                problems.append(
                    f"{idx}쪽: 글자가 {smallest:.1f}pt로 너무 작습니다 — "
                    f"드래그로 선택되지 않습니다."
                )

            if len(spans) >= MIN_LINES_TO_JUDGE:
                union = fitz.Rect(spans[0]["bbox"])
                for s in spans[1:]:
                    union |= fitz.Rect(s["bbox"])
                page_area = page.rect.get_area()
                coverage = union.get_area() / page_area if page_area else 0.0
                if coverage < MIN_COVERAGE:
                    problems.append(
                        f"{idx}쪽: 텍스트가 쪽의 {coverage * 100:.1f}%에만 몰려 "
                        f"있습니다 — 원문 위가 아닐 수 있습니다."
                    )

            if idx in ink_targets and len(spans) >= MIN_LINES_TO_JUDGE:
                ratio = _ink_check(page, spans)
                if ratio is not None and ratio < MIN_INK_RATIO:
                    problems.append(
                        f"{idx}쪽: 텍스트가 놓인 자리에 글자가 거의 없습니다"
                        f"(쪽 평균의 {ratio:.1f}배) — 위치가 어긋났을 수 있습니다."
                    )
    finally:
        doc.close()

    # 300쪽짜리에서 전부 나열하면 읽을 수 없다. 앞의 몇 개만 보이고 수를 알린다.
    if len(problems) > 5:
        rest = len(problems) - 5
        problems = problems[:5] + [f"…같은 문제 {rest}쪽 더 있습니다."]
    return problems


def _fill_positions_by_detection(
    page, lines: list[tuple[str, list[float] | None]], scale: float
) -> tuple[list[tuple[str, list[float] | None]], int]:
    """좌표가 없는 줄에 검출로 찾은 «글자가 있는 자리»를 채운다.

    입력:
        page — 대상 PDF 페이지. lines — (텍스트, bbox 또는 None) 목록.
        scale — 픽셀 → 포인트 배율.
    출력: (좌표를 채운 목록, 채운 줄 수)

    왜 줄 수가 같을 때만 채우는가:
        검출과 인식은 서로 다른 도구라 줄을 나누는 방식이 다를 수 있다.
        개수가 어긋난 상태에서 순서대로 짝지으면 **모든 줄이 밀려** 엉뚱한
        자리를 가리키게 된다. 그건 위치가 없는 것보다 나쁘다.
        그래서 개수가 정확히 맞을 때만 쓰고, 아니면 손대지 않는다.
        (실측: 15쪽 논문에서 12쪽이 일치. 나머지는 순서 배치로 남는다.)

    이미 좌표가 있는 줄(NDL·Paddle 인식 결과)은 건드리지 않는다.
    """
    missing = [i for i, (_t, bbox) in enumerate(lines) if bbox is None]
    if not missing:
        return lines, 0

    try:
        from ocr.line_detector import detect_lines
    except Exception:  # noqa: BLE001 — 모듈이 없으면 조용히 물러난다
        return lines, 0

    try:
        import fitz

        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        # 목표 줄 수를 함께 넘긴다. 쪽마다 알맞은 임계값이 달라
        # 고정값으로는 2단 목차와 한시 대역을 동시에 맞출 수 없다.
        detected = detect_lines(pix.tobytes("png"), float(pix.width), target_count=len(lines))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"줄 위치 검출을 건너뜁니다: {e}")
        return lines, 0

    if len(detected) != len(lines):
        logger.info(
            f"검출 {len(detected)}줄 ≠ 텍스트 {len(lines)}줄 — "
            "순서가 밀릴 수 있어 위치를 채우지 않습니다."
        )
        return lines, 0

    filled = []
    count = 0
    for (text, bbox), det in zip(lines, detected):
        if bbox is None:
            filled.append((text, det.as_bbox()))
            count += 1
        else:
            filled.append((text, bbox))
    return filled, count


def _load_lines(
    doc_path: Path, part_id: str, page_num: int, source_layer: str
) -> list[tuple[str, list[float] | None]]:
    """한 쪽의 (텍스트, bbox) 목록을 지정한 층에서 읽어 온다.

    l2 — OCR 결과. 엔진에 따라 bbox가 있을 수도(NDL·Paddle) 없을 수도(LLM) 있다.
    l4 — 사람이 교정한 텍스트. 좌표가 없으므로 전부 None이다.
    """
    if source_layer == "l4":
        from core.document import get_page_text

        try:
            data = get_page_text(doc_path, part_id, page_num)
        except (FileNotFoundError, OSError):
            return []
        text = (data or {}).get("text") or ""
        return [(ln.strip(), None) for ln in text.splitlines() if ln.strip()]

    l2 = _read_json(_l2_path(doc_path, part_id, page_num))
    if not l2:
        return []
    return _collect_lines(l2)
