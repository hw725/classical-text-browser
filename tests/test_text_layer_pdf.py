"""텍스트 레이어 입히기(src/export/text_layer_pdf.py) 테스트.

왜 이 테스트가 있는가:
    논문 lite mode의 산출물 계약은 "텍스트 레이어를 가진 PDF"다.
    사이드카 .txt와 달리 이 산출물은 뷰어 복사·Ctrl+F·구조 분석·
    참고문헌 추출이 그대로 동작해야 하므로, 다음 셋을 매번 확인한다.
      1) 텍스트 레이어 PDF에서 텍스트가 실제로 추출되는가
      2) 검색 좌표가 OCR bbox가 가리킨 자리와 맞는가
      3) 원본 L1_source가 그대로인가

검증 근거:
    "폰트를 임베드하지 않으면 쪽당 +0.9KB"라는 설계 판단이 회귀하지 않도록
    크기 비교도 함께 잰다.
"""

import json
from pathlib import Path

import fitz
import pytest

from export.text_layer_pdf import embed_text_layer

# OCR이 인식했다고 가정할 줄과, 렌더 이미지(144 DPI) 픽셀 기준 bbox.
# PDF 포인트로는 각각 /2.0 한 값이 된다.
LINES = [
    ("18세기 필사본 유통과 독자층의 형성", [160.0, 200.0, 900.0, 240.0]),
    ("본고는 抄本의 유통 경로를 추적한다.", [160.0, 280.0, 860.0, 316.0]),
    ("주제어: 필사본, 유통, 독자층", [160.0, 360.0, 700.0, 396.0]),
]

PAGE_W, PAGE_H = 595.0, 842.0
RENDER_SCALE = 2.0


def _make_scanned_pdf(path: Path, pages: int = 2) -> None:
    """텍스트 레이어가 없는 스캔본 PDF를 만든다.

    한글을 그린 뒤 JPEG로 래스터화해 다시 넣으므로 get_text()가 빈 문자열이 된다.
    """
    out = fitz.open()
    for _ in range(pages):
        tmp = fitz.open()
        p = tmp.new_page(width=PAGE_W, height=PAGE_H)
        y = 100.0
        for text, _bbox in LINES:
            p.insert_text((80, y), text, fontname="korea", fontsize=14)
            y += 40
        jpg = p.get_pixmap(matrix=fitz.Matrix(RENDER_SCALE, RENDER_SCALE)).tobytes(
            "jpeg", jpg_quality=70
        )
        tmp.close()
        np_ = out.new_page(width=PAGE_W, height=PAGE_H)
        np_.insert_image(np_.rect, stream=jpg)
    out.save(str(path))
    out.close()


def _write_l2(doc_path: Path, part_id: str, page: int, *, with_bbox: bool) -> None:
    """L2 OCR 결과 JSON을 쓴다.

    with_bbox=False는 LLM Vision처럼 좌표를 주지 않는 엔진을 흉내낸다.
    """
    lines = []
    for text, bbox in LINES:
        line: dict = {"text": text}
        if with_bbox:
            line["bbox"] = bbox
        lines.append(line)
    data = {
        "part_id": part_id,
        "page_number": page,
        "ocr_engine": "ndlocr" if with_bbox else "llm_vision",
        "ocr_results": [{"layout_block_id": "page_full", "lines": lines}],
    }
    l2_dir = doc_path / "L2_ocr"
    l2_dir.mkdir(parents=True, exist_ok=True)
    (l2_dir / f"{part_id}_page_{page:03d}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _write_l3(doc_path: Path, part_id: str, page: int, image_width: float) -> None:
    """L3 레이아웃 JSON을 쓴다. 배율 계산에만 쓰인다."""
    data = {
        "part_id": part_id,
        "page_number": page,
        "image_width": image_width,
        "image_height": image_width * (PAGE_H / PAGE_W),
        "blocks": [
            {
                "block_id": "page_full",
                "block_type": "main_text",
                "bbox": [0, 0, image_width, image_width * (PAGE_H / PAGE_W)],
                "reading_order": 1,
            }
        ],
    }
    l3_dir = doc_path / "L3_layout"
    l3_dir.mkdir(parents=True, exist_ok=True)
    (l3_dir / f"{part_id}_page_{page:03d}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


@pytest.fixture()
def scanned_doc(tmp_path):
    """스캔본 PDF 1개(2쪽)를 가진 최소 문헌 디렉토리를 만든다.

    get_pdf_path()가 manifest.json의 parts[].file을 읽으므로
    실제 문헌과 같은 구조를 갖춰야 한다.
    """
    doc_path = tmp_path / "doc_paper"
    (doc_path / "L1_source").mkdir(parents=True)
    pdf_name = "paper.pdf"
    _make_scanned_pdf(doc_path / "L1_source" / pdf_name, pages=2)

    manifest = {
        "document_id": "doc_paper",
        "title": "18세기 필사본 유통 연구",
        "parts": [
            {
                "part_id": "vol1",
                "label": "본문",
                "file": f"L1_source/{pdf_name}",
                "page_count": 2,
            }
        ],
        "created_at": "2026-07-25T00:00:00",
    }
    (doc_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return doc_path


def test_scanned_source_has_no_text_layer(scanned_doc):
    """전제 확인: 원본 스캔본에는 텍스트 레이어가 없어야 한다."""
    src = fitz.open(str(scanned_doc / "L1_source" / "paper.pdf"))
    assert src[0].get_text("text").strip() == ""
    src.close()


def test_embed_with_bbox_positions_lines(scanned_doc):
    """좌표가 있는 OCR 결과는 제자리에 놓이고 검색으로 찾을 수 있어야 한다."""
    _write_l2(scanned_doc, "vol1", 1, with_bbox=True)
    _write_l2(scanned_doc, "vol1", 2, with_bbox=True)

    result = embed_text_layer(scanned_doc, "vol1")

    assert result.embedded_pages == 2
    assert result.skipped_pages == 0
    assert result.positioned_lines == len(LINES) * 2
    assert result.approximated_lines == 0

    out = fitz.open(result.output_path)
    try:
        page = out[0]
        extracted = page.get_text("text")
        for text, _bbox in LINES:
            assert text in extracted, f"추출 텍스트에 없음: {text}"

        # 검색 좌표가 OCR bbox가 가리킨 자리(픽셀/2.0)와 맞아야 한다.
        for text, bbox in LINES:
            hits = page.search_for(text)
            assert hits, f"검색 실패: {text}"
            expect_x0 = bbox[0] / RENDER_SCALE
            expect_y1 = bbox[3] / RENDER_SCALE
            assert abs(hits[0].x0 - expect_x0) < 2.0
            assert abs(hits[0].y1 - expect_y1) < 3.0
            # 폭도 bbox에 대체로 맞아야 한다 (하이라이트 길이).
            expect_w = (bbox[2] - bbox[0]) / RENDER_SCALE
            assert abs(hits[0].width - expect_w) < expect_w * 0.25
    finally:
        out.close()


def test_embed_without_bbox_still_extractable(scanned_doc):
    """좌표가 없는 엔진(LLM Vision)이어도 텍스트는 반드시 들어가야 한다.

    위치는 원본 자리가 아니게 되지만, 복사·Ctrl+F·구조 분석이 동작하려면
    텍스트의 존재 자체가 먼저다.

    검출을 끄고 본다: 여기서 확인할 것은 «좌표를 못 얻었을 때의 폴백»이다.
    검출이 켜져 있으면 위치가 채워져 이 경로를 타지 않는다.
    """
    _write_l2(scanned_doc, "vol1", 1, with_bbox=False)

    result = embed_text_layer(
        scanned_doc, "vol1", pages=[1], use_line_detection=False
    )

    assert result.positioned_lines == 0
    assert result.approximated_lines == len(LINES)

    out = fitz.open(result.output_path)
    try:
        extracted = out[0].get_text("text")
        for text, _bbox in LINES:
            assert text in extracted
        # 근사 배치임이 산출물 메타데이터에 남아야 한다.
        assert "page-approximated" in (out.metadata or {}).get("producer", "")
    finally:
        out.close()


def test_embed_skips_pages_without_ocr(scanned_doc):
    """OCR 결과가 없는 쪽은 건너뛰고 그 사실을 보고해야 한다."""
    _write_l2(scanned_doc, "vol1", 1, with_bbox=True)  # 2쪽은 결과 없음

    result = embed_text_layer(scanned_doc, "vol1")

    assert result.embedded_pages == 1
    assert result.skipped_pages == 1


def test_embed_does_not_touch_original(scanned_doc):
    """L1_source의 원본 PDF는 절대 수정되지 않아야 한다."""
    src = scanned_doc / "L1_source" / "paper.pdf"
    before_bytes = src.read_bytes()
    before_mtime = src.stat().st_mtime_ns

    _write_l2(scanned_doc, "vol1", 1, with_bbox=True)
    embed_text_layer(scanned_doc, "vol1")

    assert src.read_bytes() == before_bytes
    assert src.stat().st_mtime_ns == before_mtime
    # 결과는 exports/ 아래에 따로 생긴다.
    assert (scanned_doc / "exports" / "vol1_text.pdf").exists()


def test_embedded_font_is_much_larger(scanned_doc):
    """폰트 임베드는 파일을 크게 만든다 — 기본값이 비임베드인 이유.

    실측(2026-07-25): 비임베드 +0.9KB/쪽, subset 임베드 +10.6KB/쪽.
    이 관계가 뒤집히면 기본값 선택 근거가 무너지므로 회귀로 잡는다.
    """
    _write_l2(scanned_doc, "vol1", 1, with_bbox=True)
    _write_l2(scanned_doc, "vol1", 2, with_bbox=True)

    lean = embed_text_layer(scanned_doc, "vol1", output_path=scanned_doc / "lean.pdf")
    fat = embed_text_layer(
        scanned_doc, "vol1", output_path=scanned_doc / "fat.pdf", embed_font=True
    )

    assert lean.size_bytes < fat.size_bytes
    # 임베드 쪽에서도 텍스트는 정상 추출돼야 한다.
    out = fitz.open(fat.output_path)
    try:
        assert LINES[0][0] in out[0].get_text("text")
    finally:
        out.close()


def test_render_scale_read_from_l3(scanned_doc):
    """배율은 L3의 image_width에서 구한다 — 하드코딩 2.0보다 정확하다.

    3.0배(216 DPI)로 렌더한 것처럼 L3를 쓰고, 같은 bbox가 그만큼
    위쪽·왼쪽으로 옮겨 놓이는지 확인한다.
    """
    _write_l2(scanned_doc, "vol1", 1, with_bbox=True)
    _write_l3(scanned_doc, "vol1", 1, image_width=PAGE_W * 3.0)

    result = embed_text_layer(scanned_doc, "vol1", pages=[1])

    out = fitz.open(result.output_path)
    try:
        text, bbox = LINES[0]
        hits = out[0].search_for(text)
        assert hits
        assert abs(hits[0].x0 - bbox[0] / 3.0) < 2.0
    finally:
        out.close()


def test_embed_from_l4_corrected_text(scanned_doc):
    """교정된 L4 텍스트로도 구울 수 있어야 한다 (좌표 없이 쪽 단위)."""
    pages_dir = scanned_doc / "L4_text" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir / "vol1_page_001.txt").write_text(
        "교정된 첫 줄입니다\n교정된 둘째 줄입니다\n", encoding="utf-8"
    )

    result = embed_text_layer(scanned_doc, "vol1", pages=[1], source_layer="l4")

    assert result.source_layer == "l4"
    assert result.approximated_lines == 2
    out = fitz.open(result.output_path)
    try:
        assert "교정된 첫 줄입니다" in out[0].get_text("text")
    finally:
        out.close()


def test_invalid_source_layer_rejected(scanned_doc):
    """잘못된 source_layer는 한국어 안내와 함께 거부돼야 한다."""
    with pytest.raises(ValueError, match="source_layer"):
        embed_text_layer(scanned_doc, "vol1", source_layer="l9")


def test_unknown_part_id_rejected(scanned_doc):
    """없는 part_id는 한국어 안내와 함께 거부돼야 한다."""
    with pytest.raises(FileNotFoundError, match="권을 찾을 수 없습니다"):
        embed_text_layer(scanned_doc, "vol99")


def test_lines_without_bbox_are_stacked_not_placed(scanned_doc):
    """좌표가 없는 줄이 실제로 어떻게 놓이는지 못박아 둔다.

    왜 이 테스트가 있는가:
        «위치가 대략적»이라고 설명해 왔으나 실제 구현은 다르다.
        좌표를 모르므로 **모든 줄을 왼쪽 여백에서 시작해 세로로 균등 배치**한다.
        검색하면 형광이 한 줄 크기로 정확히 뜨지만 그 자리에 원본 글자가 없다.
        설명과 구현이 다시 어긋나지 않도록 실제 좌표를 검증한다.

        검출을 끈 상태의 동작이다. 검출로 위치를 얻으면 제자리에 놓이며,
        그 경로는 test_detection_fills_positions_only_when_counts_match가 본다.
    """
    import fitz

    _write_l2(scanned_doc, "vol1", 1, with_bbox=False)
    result = embed_text_layer(
        scanned_doc, "vol1", pages=[1], use_line_detection=False
    )
    assert result.approximated_lines == len(LINES)
    assert result.positioned_lines == 0

    out = fitz.open(result.output_path)
    try:
        spans = [
            (s["bbox"], s["text"])
            for b in out[0].get_text("dict")["blocks"]
            for line in b.get("lines", [])
            for s in line.get("spans", [])
        ]
        assert len(spans) >= len(LINES)

        # 1) 모든 줄이 같은 x에서 시작한다 (원본 정렬과 무관하게 왼쪽 붙임)
        xs = {round(bbox[0], 1) for bbox, _ in spans}
        assert len(xs) == 1, f"x 시작이 여러 개다: {xs}"

        # 2) 세로 간격이 일정하다 (균등 배치)
        ys = sorted(round(bbox[1], 1) for bbox, _ in spans)
        gaps = {round(ys[i + 1] - ys[i], 1) for i in range(len(ys) - 1)}
        assert len(gaps) == 1, f"y 간격이 일정하지 않다: {gaps}"

        # 3) OCR이 보고한 bbox와는 다른 자리다 — «제자리»가 아님을 분명히 한다
        ocr_x = LINES[0][1][0] / RENDER_SCALE  # 80.0pt
        assert abs(next(iter(xs)) - ocr_x) > 5, (
            "좌표 없는 줄이 우연히 OCR bbox 자리에 놓였다 — 이 테스트의 전제가 깨졌다"
        )
    finally:
        out.close()


def test_detection_fills_positions_only_when_counts_match(scanned_doc, monkeypatch):
    """검출 줄 수가 텍스트 줄 수와 같을 때만 위치를 채워야 한다.

    개수가 어긋난 상태에서 순서대로 짝지으면 모든 줄이 밀려 엉뚱한 자리를
    가리킨다. 그건 위치가 없는 것보다 나쁘다. 실제 논문 15쪽 중 3쪽이
    어긋났으므로 이 폴백이 반드시 동작해야 한다.
    """
    from ocr.line_detector import DetectedLine

    _write_l2(scanned_doc, "vol1", 1, with_bbox=False)

    # 1) 개수가 맞을 때 — 검출 위치로 채운다
    fake = [DetectedLine(100.0 + i * 10, 200.0 + i * 40, 800.0, 236.0 + i * 40)
            for i in range(len(LINES))]
    monkeypatch.setattr("ocr.line_detector.detect_lines", lambda *a, **k: fake)
    result = embed_text_layer(scanned_doc, "vol1", pages=[1],
                              output_path=scanned_doc / "matched.pdf")
    assert result.detected_lines == len(LINES)
    assert result.positioned_lines == len(LINES)
    assert result.approximated_lines == 0

    # 2) 개수가 어긋날 때 — 손대지 않고 순서 배치로 물러난다
    monkeypatch.setattr("ocr.line_detector.detect_lines", lambda *a, **k: fake[:1])
    result = embed_text_layer(scanned_doc, "vol1", pages=[1],
                              output_path=scanned_doc / "mismatched.pdf")
    assert result.detected_lines == 0, "개수가 다른데 위치를 채웠다 — 줄이 밀린다"
    assert result.approximated_lines == len(LINES)


def test_detection_can_be_disabled(scanned_doc, monkeypatch):
    """use_line_detection=False면 검출을 부르지 않는다."""
    called = []
    monkeypatch.setattr("ocr.line_detector.detect_lines",
                        lambda *a, **k: called.append(1) or [])

    _write_l2(scanned_doc, "vol1", 1, with_bbox=False)
    result = embed_text_layer(scanned_doc, "vol1", pages=[1],
                              use_line_detection=False)

    assert not called, "끄라고 했는데 검출을 불렀다"
    assert result.detected_lines == 0
    assert result.approximated_lines == len(LINES)


def test_detection_failure_falls_back_quietly(scanned_doc, monkeypatch):
    """검출이 실패해도 텍스트 레이어는 만들어져야 한다.

    검출은 위치를 개선하는 보조 수단이지 필수가 아니다.
    """
    def boom(*a, **k):
        raise RuntimeError("모델 로드 실패")

    monkeypatch.setattr("ocr.line_detector.detect_lines", boom)
    _write_l2(scanned_doc, "vol1", 1, with_bbox=False)

    result = embed_text_layer(scanned_doc, "vol1", pages=[1])

    assert result.embedded_pages == 1
    assert result.detected_lines == 0
    assert result.approximated_lines == len(LINES)


def test_existing_bbox_is_not_overwritten(scanned_doc, monkeypatch):
    """이미 좌표가 있는 줄(NDL·Paddle 인식)은 검출로 덮어쓰지 않는다."""
    from ocr.line_detector import DetectedLine

    fake = [DetectedLine(999.0, 999.0, 1000.0, 1010.0) for _ in LINES]
    monkeypatch.setattr("ocr.line_detector.detect_lines", lambda *a, **k: fake)

    _write_l2(scanned_doc, "vol1", 1, with_bbox=True)  # bbox 있음
    result = embed_text_layer(scanned_doc, "vol1", pages=[1])

    assert result.detected_lines == 0, "OCR이 준 좌표를 검출로 덮어썼다"
    assert result.positioned_lines == len(LINES)
