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


def _write_l2_custom(doc_path: Path, part_id: str, page: int, lines) -> None:
    """줄 목록을 직접 주어 L2를 쓴다 (글리프 누락 시험용)."""
    doc_path = Path(doc_path)
    (doc_path / "L2_ocr").mkdir(parents=True, exist_ok=True)
    (doc_path / "L2_ocr" / f"{part_id}_page_{page:03d}.json").write_text(
        json.dumps(
            {
                "part_id": part_id,
                "page_number": page,
                "ocr_engine": "test",
                "ocr_results": [
                    {
                        "layout_block_id": f"p{page:02d}_b01",
                        "lines": [{"text": t, "bbox": b} for t, b in lines],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


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

    result = embed_text_layer(scanned_doc, "vol1", pages=[1], use_line_detection=False)

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


def test_embedded_font_costs_size_but_is_the_default(scanned_doc):
    """폰트 임베드는 파일을 키운다. 그래도 그것이 기본값이다.

    처음에는 비임베드가 기본이었다(쪽당 +0.9KB, 실측 2026-07-25).
    그런데 실제 논문에서 **Adobe-Korea1 charset에 없는 한자가 조용히
    사라졌다** — 51종 130자, 하필 한시 인용문에 몰려 있었다
    (실측 2026-07-26). 산출물의 계약은 «검색되는 PDF»이므로
    크기(쪽당 +4.9KB)를 치르고 임베드하는 쪽으로 뒤집었다.

    여기서 고정하는 것은 **크기 관계**다. 임베드가 더 작아지면
    측정이나 구현이 달라진 것이니 다시 봐야 한다.
    """
    _write_l2(scanned_doc, "vol1", 1, with_bbox=True)
    _write_l2(scanned_doc, "vol1", 2, with_bbox=True)

    lean = embed_text_layer(
        scanned_doc, "vol1", output_path=scanned_doc / "lean.pdf", embed_font=False
    )
    fat = embed_text_layer(scanned_doc, "vol1", output_path=scanned_doc / "fat.pdf")

    assert fat.embed_font is True, "임베드가 기본값이어야 한다"
    assert lean.embed_font is False
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
    result = embed_text_layer(scanned_doc, "vol1", pages=[1], use_line_detection=False)
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
    fake = [
        DetectedLine(100.0 + i * 10, 200.0 + i * 40, 800.0, 236.0 + i * 40)
        for i in range(len(LINES))
    ]
    monkeypatch.setattr("ocr.line_detector.detect_lines", lambda *a, **k: fake)
    result = embed_text_layer(
        scanned_doc, "vol1", pages=[1], output_path=scanned_doc / "matched.pdf"
    )
    assert result.detected_lines == len(LINES)
    assert result.positioned_lines == len(LINES)
    assert result.approximated_lines == 0

    # 2) 개수가 어긋날 때 — 손대지 않고 순서 배치로 물러난다
    monkeypatch.setattr("ocr.line_detector.detect_lines", lambda *a, **k: fake[:1])
    result = embed_text_layer(
        scanned_doc, "vol1", pages=[1], output_path=scanned_doc / "mismatched.pdf"
    )
    assert result.detected_lines == 0, "개수가 다른데 위치를 채웠다 — 줄이 밀린다"
    assert result.approximated_lines == len(LINES)


def test_detection_can_be_disabled(scanned_doc, monkeypatch):
    """use_line_detection=False면 검출을 부르지 않는다."""
    called = []
    monkeypatch.setattr("ocr.line_detector.detect_lines", lambda *a, **k: called.append(1) or [])

    _write_l2(scanned_doc, "vol1", 1, with_bbox=False)
    result = embed_text_layer(scanned_doc, "vol1", pages=[1], use_line_detection=False)

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


# Adobe-Korea1 charset에 없어 비임베드 방식에서 조용히 사라지던 글자들.
# 실측(2026-07-26, 15쪽 논문)에서 51종 130자가 누락됐고 그중 상위 셋이다.
# 전부 한시 인용문에 쓰이는 한자라, 연구자가 가장 찾고 싶어 할 글자다.
LOST_CHARS = "郎儂研"


def test_chars_outside_korea1_survive(scanned_doc):
    """Adobe-Korea1에 없는 한자가 PDF에서 사라지면 안 된다.

    이것이 임베드를 기본값으로 뒤집은 이유다. 산출물의 계약은
    «검색되는 PDF»인데, 검색하고 싶은 글자가 빠지면 계약이 깨진다.
    """
    text = f"勸{LOST_CHARS[0]}合歡酒 {LOST_CHARS[1]}不信 李安中{LOST_CHARS[2]}究"
    _write_l2_custom(scanned_doc, "vol1", 1, [(text, [160.0, 200.0, 900.0, 240.0])])

    result = embed_text_layer(scanned_doc, "vol1")
    out = fitz.open(result.output_path)
    try:
        got = out[0].get_text()
    finally:
        out.close()

    missing = [c for c in LOST_CHARS if c not in got]
    assert not missing, f"PDF에서 사라진 글자: {missing}"


def test_chars_are_searchable(scanned_doc):
    """사라지지 않을 뿐 아니라 **검색되어야** 한다.

    글자가 텍스트로는 뽑히는데 search_for가 못 찾으면 사용자에게는
    없는 것과 같다.
    """
    _write_l2_custom(scanned_doc, "vol1", 1, [("玄同 李安中研究", [160.0, 200.0, 900.0, 240.0])])
    result = embed_text_layer(scanned_doc, "vol1")
    out = fitz.open(result.output_path)
    try:
        assert out[0].search_for("李安中研究"), "임베드했는데도 검색되지 않는다"
    finally:
        out.close()


def test_without_embedding_the_loss_is_real(scanned_doc):
    """임베드를 끄면 실제로 사라진다 — 기본값을 되돌리면 안 되는 이유.

    이 테스트가 실패하면 (a) PyMuPDF가 동작을 바꿨거나 (b) 측정이
    틀렸다는 뜻이므로, 기본값 결정을 다시 봐야 한다.
    """
    _write_l2_custom(
        scanned_doc, "vol1", 1, [(f"李安中{LOST_CHARS[2]}究", [160.0, 200.0, 900.0, 240.0])]
    )
    result = embed_text_layer(scanned_doc, "vol1", embed_font=False)
    out = fitz.open(result.output_path)
    try:
        got = out[0].get_text()
    finally:
        out.close()
    assert LOST_CHARS[2] not in got, "비임베드에서도 살아남았다 — 측정 전제를 다시 볼 것"


# ── 실제 스캔본의 «남은 좌표 변환» 회귀 (D-068) ──────────────────
#
# 왜 이 시험이 따로 필요한가: 위의 fixture는 PyMuPDF가 만든 **깨끗한** PDF다.
# 실제 스캔 PDF는 픽셀 단위로 작업하려고 내용 스트림 첫 줄에 배율을 걸어 두고
# 되돌리지 않는 일이 흔하다. 그 상태에서 TextWriter로 덧붙이면 텍스트가
# 통째로 축소돼 쪽 구석에 박힌다 — get_text()로는 «있다»고 나오므로
# 기존 시험은 전부 통과한다. 실제 논문에서만 드러났던 결함이다.


def _make_unwrapped_scan(path: Path, pages: int = 1) -> None:
    """내용 스트림이 `0.24 … cm`으로 시작하고 되돌리지 않는 스캔본을 만든다.

    실제 논문(박준원 2001)의 스트림 모양을 그대로 본떴다:
        0.24 0 0 0.24 0 0 cm      ← q 없이, Q도 없다
        q 2064 0 0 2893 0 0 cm /I0 Do Q
    """
    scale = 0.24
    img_w, img_h = round(PAGE_W / scale), round(PAGE_H / scale)

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
        # 내용 스트림을 실제 스캔본 모양으로 갈아 끼운다.
        # 이미지 이름은 방금 넣은 것에서 읽어 온다 — 이름을 지어내면 이미지가
        # 그려지지 않아 시험이 «글자 없는 흰 종이»를 상대하게 된다.
        img_name = np_.get_images()[0][7]
        xref = np_.get_contents()[0]
        out.update_stream(
            xref,
            (
                f"{scale} 0 0 {scale} 0 0 cm\nq\n{img_w} 0 0 {img_h} 0 0 cm\n/{img_name} Do\nQ\n"
            ).encode(),
        )
    out.save(str(path))
    out.close()


@pytest.fixture
def unwrapped_doc(tmp_path):
    """되돌리지 않은 좌표 변환을 가진 스캔본 문헌."""
    doc_path = tmp_path / "doc_unwrapped"
    (doc_path / "L1_source").mkdir(parents=True)
    _make_unwrapped_scan(doc_path / "L1_source" / "paper.pdf", pages=1)
    (doc_path / "manifest.json").write_text(
        json.dumps(
            {
                "document_id": "doc_unwrapped",
                "title": "좌표 변환이 남은 스캔본",
                "parts": [
                    {
                        "part_id": "vol1",
                        "label": "본문",
                        "file": "L1_source/paper.pdf",
                        "page_count": 1,
                    }
                ],
                "created_at": "2026-07-26T00:00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return doc_path


def test_source_really_has_unwrapped_transform(unwrapped_doc):
    """시험 대상이 실제로 «되돌리지 않은 변환»을 갖고 있는지부터 확인한다.

    이것이 깨지면 아래 두 시험은 아무것도 지키지 못한 채 통과한다.
    """
    doc = fitz.open(str(unwrapped_doc / "L1_source" / "paper.pdf"))
    try:
        page = doc[0]
        assert page.is_wrapped is False
        assert page.read_contents().startswith(b"0.24 0 0 0.24 0 0 cm")
    finally:
        doc.close()


@pytest.mark.parametrize("embed_font", [True, False])
def test_text_lands_at_full_page_scale(unwrapped_doc, embed_font):
    """남은 변환에 끌려가지 않고 제 크기·제자리에 놓여야 한다.

    임베드(TextWriter)와 비임베드(insert_text) 양쪽을 모두 건다 —
    실제로 깨진 것은 TextWriter 쪽이었지만, 어느 경로로 바뀌든
    산출물 계약은 같아야 한다.
    """
    _write_l2(unwrapped_doc, "vol1", 1, with_bbox=True)

    result = embed_text_layer(
        unwrapped_doc, "vol1", pages=[1], embed_font=embed_font, use_line_detection=False
    )

    out = fitz.open(result.output_path)
    try:
        page = out[0]
        spans = [
            s
            for b in page.get_text("dict")["blocks"]
            if b["type"] == 0
            for line in b["lines"]
            for s in line["spans"]
        ]
        assert spans, "텍스트가 하나도 들어가지 않았다"

        # 1) 글자 크기: 0.24배로 끌려가면 14pt가 3.4pt가 된다.
        assert min(s["size"] for s in spans) > 6.0, (
            f"글자가 너무 작다 — 남은 변환에 끌려갔다: {[round(s['size'], 1) for s in spans]}"
        )

        # 2) 놓인 자리: L2 bbox는 x=160px(=80pt)에서 시작한다.
        #    0.24배로 끌려가면 19pt 언저리로 몰린다.
        assert min(s["bbox"][0] for s in spans) > 40.0

        # 3) 세로로도 쪽 전체에 퍼져 있어야 한다 (구석에 뭉치지 않는다).
        top = min(s["bbox"][1] for s in spans)
        bottom = max(s["bbox"][3] for s in spans)
        assert (bottom - top) > PAGE_H * 0.1

        # 4) 검색 형광이 OCR이 가리킨 자리와 겹치는가.
        #    좌표를 점으로 비교하지 않는 이유: 글자 크기를 bbox 폭에 맞추므로
        #    글리프 높이가 bbox보다 조금 크거나 작을 수 있다. 중요한 것은
        #    형광이 **그 줄 위에 뜨는가**지 위끝이 몇 pt 어긋났는가가 아니다.
        text, bbox = LINES[0]
        hits = page.search_for(text)
        assert hits, "검색되지 않는다"
        want = fitz.Rect(
            bbox[0] / RENDER_SCALE,
            bbox[1] / RENDER_SCALE,
            bbox[2] / RENDER_SCALE,
            bbox[3] / RENDER_SCALE,
        )
        got = hits[0]
        assert abs(got.x0 - want.x0) < 3.0, f"가로 시작이 어긋났다: {got.x0} vs {want.x0}"
        assert (got & want).get_area() > want.get_area() * 0.5, (
            f"형광이 그 줄을 벗어났다: {got} vs {want}"
        )
    finally:
        out.close()


def test_source_pdf_untouched_by_wrapping(unwrapped_doc):
    """wrap_contents()는 **산출물에만** 적용되어야 한다 — 원본은 그대로다."""
    src = unwrapped_doc / "L1_source" / "paper.pdf"
    before = src.read_bytes()

    _write_l2(unwrapped_doc, "vol1", 1, with_bbox=True)
    embed_text_layer(unwrapped_doc, "vol1", pages=[1])

    assert src.read_bytes() == before, "L1_source 원본이 바뀌었다"


def test_audit_catches_shrunken_text(tmp_path):
    """산출물 검사가 «축소돼 구석에 박힌 텍스트»를 잡아내는가.

    D-068에서 실제로 나온 모양을 그대로 만든다 — 495×694 쪽의 왼쪽 아래에
    2.9pt 글자가 뭉쳐 있는 상태. 고침이 사라져 이 모양이 다시 나오면
    embed_text_layer()의 warnings에 그대로 실려 화면까지 올라간다.
    """
    from export.text_layer_pdf import _audit_output

    bad = tmp_path / "bad.pdf"
    doc = fitz.open()
    page = doc.new_page(width=495.36, height=694.32)
    y = 539.0
    for text, _bbox in LINES * 3:
        page.insert_text((9.6, y), text, fontname="korea", fontsize=2.88, render_mode=3)
        y += 4.9
    doc.save(str(bad))
    doc.close()

    problems = _audit_output(bad)

    assert problems, "축소된 텍스트를 그대로 통과시켰다"
    joined = " ".join(problems)
    assert "너무 작" in joined, joined
    assert "몰려" in joined, joined


def test_audit_stays_quiet_on_good_output(unwrapped_doc):
    """정상 산출물에는 경고를 붙이지 않는다 (거짓 경보 방지)."""
    _write_l2(unwrapped_doc, "vol1", 1, with_bbox=True)
    result = embed_text_layer(unwrapped_doc, "vol1", pages=[1], use_line_detection=False)
    assert result.warnings == [], result.warnings


def test_render_scale_prefers_l2_record(scanned_doc):
    """L2에 image_width가 있으면 그것이 bbox의 좌표계다 — L3보다 앞선다 (D-087)."""
    from export.text_layer_pdf import _l2_path, _render_scale

    _write_l2(scanned_doc, "vol1", 1, with_bbox=True)
    _write_l3(scanned_doc, "vol1", 1, image_width=PAGE_W * 3.0)
    p = _l2_path(scanned_doc, "vol1", 1)
    l2 = json.loads(p.read_text(encoding="utf-8"))
    l2["image_width"], l2["image_height"] = round(PAGE_W * 5), round(PAGE_H * 5)
    p.write_text(json.dumps(l2), encoding="utf-8")
    assert abs(_render_scale(scanned_doc, "vol1", 1, PAGE_W) - 5.0) < 0.01
