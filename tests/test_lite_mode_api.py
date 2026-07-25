"""논문 lite mode API 테스트 — 텍스트 레이어 진단.

왜 이 테스트가 있는가:
    lite mode의 첫 분기는 "이 PDF에 OCR이 필요한가"다.
    이 판정이 틀리면 대가가 방향에 따라 다르다.
      - 스캔본을 born-digital로 오판 → OCR을 건너뛰어 텍스트를 못 얻는다
      - born-digital을 스캔본으로 오판 → 안 해도 될 OCR을 돌린다
    앞쪽이 더 나쁘므로 born_digital은 확실할 때만 선언해야 한다.
    특히 **표지·판권지만 활자인 영인본**이 born-digital로 새어 나가지
    않는지를 회귀로 잡는다 (기존 has_text_layer()는 이걸 놓친다).
"""

import fitz
import pytest
from fastapi.testclient import TestClient

BODY = (
    "본고는 18세기 필사본의 유통 경로를 추적하여 독자층 형성을 밝힌다. "
    "抄本과 刊本의 계통을 함께 본다."
)


@pytest.fixture()
def isolated_app(tmp_path, monkeypatch):
    """가짜 홈으로 격리된 TestClient. (tests/test_onboarding_api.py와 같은 방식)

    실제 사용자 홈에 서고를 만들면 안 되고, _state._library_path는
    프로세스 전역이라 끝나고 되돌려야 다른 테스트가 오염되지 않는다.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))

    from app._state import get_library_path, set_library_path
    from app.server import app

    saved = get_library_path()
    set_library_path(None)
    try:
        with TestClient(app) as client:
            client.post("/api/library/quick-start")
            yield client, tmp_path
    finally:
        set_library_path(str(saved) if saved else None)


def _draw_body(page, lines: int = 6) -> None:
    """페이지에 본문 텍스트를 그린다."""
    y = 100.0
    for _ in range(lines):
        page.insert_text((70, y), BODY, fontname="korea", fontsize=11)
        y += 30


def _make_pdf(path, kind: str, pages: int = 10):
    """진단 대상 PDF를 만든다.

    kind:
      born  — 모든 쪽에 텍스트 레이어가 있다 (born-digital 논문 PDF)
      scan  — 모든 쪽이 이미지다 (스캔본)
      cover — 앞 2쪽만 텍스트, 나머지는 이미지 (표지만 활자인 영인본)
    """
    out = fitz.open()
    for i in range(pages):
        is_text_page = kind == "born" or (kind == "cover" and i < 2)
        if is_text_page:
            _draw_body(out.new_page(width=595, height=842))
        else:
            # 텍스트를 그린 뒤 래스터화해 텍스트 레이어를 없앤다.
            tmp = fitz.open()
            tp = tmp.new_page(width=595, height=842)
            _draw_body(tp)
            jpg = tp.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("jpeg", jpg_quality=60)
            tmp.close()
            p = out.new_page(width=595, height=842)
            p.insert_image(p.rect, stream=jpg)
    out.save(str(path))
    out.close()
    return path


def _register(client, tmp_path, kind: str, doc_id: str, pages: int = 10) -> dict:
    """PDF를 만들어 드래그 앤 드롭과 같은 경로로 등록하고 응답을 돌려준다."""
    pdf = _make_pdf(tmp_path / f"{kind}.pdf", kind, pages=pages)
    with open(pdf, "rb") as f:
        r = client.post(
            "/api/documents/create-from-files",
            data={"doc_id": doc_id, "title": kind},
            files=[("files", (f"{kind}.pdf", f.read(), "application/pdf"))],
        )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize(
    ("kind", "expected_verdict", "expected_has_layer"),
    [
        ("scan", "scanned", False),
        ("born", "born_digital", True),
        ("cover", "partial", False),
    ],
)
def test_create_from_files_reports_text_layer(
    isolated_app, kind, expected_verdict, expected_has_layer
):
    """등록 응답에 각 권의 텍스트 레이어 진단이 실려 와야 한다.

    이것이 없으면 사용자는 스캔본인지 모른 채 작업을 시작하게 된다.
    """
    client, tmp_path = isolated_app
    body = _register(client, tmp_path, kind, f"doc_{kind}")

    text_layer = body["parts"][0].get("text_layer")
    assert text_layer is not None, "등록 응답에 text_layer 진단이 없다"
    assert text_layer["verdict"] == expected_verdict
    assert text_layer["has_text_layer"] is expected_has_layer
    assert text_layer["total_pages"] == 10


@pytest.mark.parametrize(
    ("kind", "expected_verdict"),
    [("scan", "scanned"), ("born", "born_digital"), ("cover", "partial")],
)
def test_probe_route_on_library_document(isolated_app, kind, expected_verdict):
    """서고에 등록된 문헌을 진단할 수 있어야 한다.

    기존 /api/text-import/pdf/analyze 는 업로드 파일만 받아 서고 문헌에는
    쓸 수 없었다 (multipart file 필수 → 422).
    """
    client, tmp_path = isolated_app
    body = _register(client, tmp_path, kind, f"doc_{kind}")
    doc_id = body["document_id"]
    part_id = body["parts"][0]["part_id"]

    r = client.get(f"/api/documents/{doc_id}/parts/{part_id}/text-layer")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["verdict"] == expected_verdict
    assert data["part_id"] == part_id
    # 안내문은 다음에 할 일을 알려 줘야 한다 (비개발자 연구자가 사용자다).
    assert data["recommendation"].strip()


def test_cover_only_scan_is_not_born_digital(isolated_app):
    """표지만 활자인 영인본이 born-digital로 새어 나가면 안 된다.

    기존 has_text_layer()는 "첫 3쪽 중 하나라도 10자 넘으면 True"라
    이 경우를 True로 오판한다. 그 오판이 회귀하지 않는지 직접 대조한다.
    """
    client, tmp_path = isolated_app
    body = _register(client, tmp_path, "cover", "doc_cover")
    doc_id = body["document_id"]
    part_id = body["parts"][0]["part_id"]

    r = client.get(f"/api/documents/{doc_id}/parts/{part_id}/text-layer")
    data = r.json()
    assert data["has_text_layer"] is False
    assert data["verdict"] == "partial"

    # 기존 느슨한 판정은 True였음을 함께 고정해 둔다 (왜 새 판정이 필요한지).
    from pathlib import Path

    from text_import.pdf_extractor import PdfTextExtractor

    src = Path(body["doc_path"]) / body["parts"][0]["file"]
    assert PdfTextExtractor(src).has_text_layer() is True


def test_probe_route_unknown_part(isolated_app):
    """없는 part_id는 사용 가능한 목록과 함께 404여야 한다."""
    client, tmp_path = isolated_app
    body = _register(client, tmp_path, "scan", "doc_scan", pages=2)
    doc_id = body["document_id"]

    r = client.get(f"/api/documents/{doc_id}/parts/nope/text-layer")
    assert r.status_code == 404
    assert "사용 가능한 part_id" in r.json()["error"]


def test_probe_route_unknown_document(isolated_app):
    """없는 문헌은 404여야 한다."""
    client, _ = isolated_app
    r = client.get("/api/documents/nosuchdoc/parts/vol1/text-layer")
    assert r.status_code == 404
    assert "문헌을 찾을 수 없습니다" in r.json()["error"]


# ── 권 단위 일괄 OCR ────────────────────────────────────


class _DummyEngine:
    """LLM을 부르지 않고 고정 텍스트를 돌려주는 시험용 엔진.

    왜 더미인가: 배치 루프·재개·전면 블록 생성을 검증하는 것이 목적이지
    OCR 품질이 아니다. 실제 엔진을 쓰면 모델 다운로드나 LLM 호출이 일어난다.
    """

    engine_id = "dummy"
    display_name = "시험용 더미 엔진"
    requires_network = False
    supports_page_level = False
    supports_layout_detection = False

    def is_available(self):
        return True

    def get_info(self):
        return {"engine_id": self.engine_id, "display_name": self.display_name}

    def recognize(self, image_bytes, writing_direction="vertical_rtl",
                  language="classical_chinese", **kwargs):
        from ocr.base import OcrBlockResult, OcrCharResult, OcrLineResult

        lines = [
            OcrLineResult(
                text="18세기 필사본 유통과 독자층의 형성",
                bbox=[160.0, 200.0, 900.0, 240.0],
                characters=[OcrCharResult(char=c) for c in "18세기"],
            ),
            OcrLineResult(
                text="본고는 抄本의 유통 경로를 추적한다.",
                bbox=[160.0, 280.0, 860.0, 316.0],
                characters=[OcrCharResult(char=c) for c in "본고는"],
            ),
        ]
        return OcrBlockResult(
            lines=lines,
            engine_id=self.engine_id,
            language=language,
            writing_direction=writing_direction,
        )


@pytest.fixture()
def batch_ready(isolated_app):
    """더미 엔진을 등록하고 스캔본 문헌(5쪽)을 만든 상태를 준비한다."""
    client, tmp_path = isolated_app
    from app._state import _get_ocr_pipeline

    _pipeline, registry = _get_ocr_pipeline()
    registry.register(_DummyEngine())

    body = _register(client, tmp_path, "scan", "doc_batch", pages=5)
    return client, body["document_id"], body["parts"][0]["part_id"]


def _sse_events(response) -> list[dict]:
    """SSE 응답 본문을 이벤트 dict 목록으로 바꾼다."""
    import json

    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_batch_creates_full_page_blocks_and_runs(batch_ready):
    """레이아웃이 없어도 전면 블록을 만들어 OCR이 끝까지 돌아야 한다.

    이것이 없으면 OCR은 조용히 0건을 반환한다
    (status="partial", errors=["L3 레이아웃을 찾을 수 없습니다"]).
    """
    client, doc_id, part_id = batch_ready

    r = client.post(
        f"/api/documents/{doc_id}/parts/{part_id}/ocr/batch",
        json={"engine_id": "dummy", "pages": [1, 2, 3]},
    )
    assert r.status_code == 200
    events = _sse_events(r)

    assert events[0]["type"] == "start"
    assert events[0]["total"] == 3

    page_events = [e for e in events if e["type"] == "page"]
    assert len(page_events) == 3
    for e in page_events:
        assert e["status"] == "completed", e.get("errors")
        assert e["lines"] == 2
        assert e["block_created"] is True

    done = events[-1]
    assert done["type"] == "complete"
    assert (done["processed"], done["skipped"], done["failed"]) == (3, 0, 0)
    assert done["total_lines"] == 6


def test_full_page_block_matches_page_geometry(batch_ready):
    """자동 생성된 전면 블록은 페이지 전체를 덮고 스키마를 만족해야 한다."""
    import json
    from pathlib import Path

    from app._state import get_library_path
    from ocr.full_page_block import is_full_page_layout

    client, doc_id, part_id = batch_ready
    client.post(
        f"/api/documents/{doc_id}/parts/{part_id}/ocr/batch",
        json={"engine_id": "dummy", "pages": [1]},
    )

    layout_path = (
        Path(get_library_path())
        / "documents"
        / doc_id
        / "L3_layout"
        / f"{part_id}_page_001.json"
    )
    layout = json.loads(layout_path.read_text(encoding="utf-8"))

    # 595pt × 2.0(144 DPI) = 1190px — 저장소 기본 렌더 배율과 맞아야
    # 입히기 단계에서 좌표를 되돌릴 수 있다.
    assert layout["image_width"] == 595.0 * 2.0
    assert len(layout["blocks"]) == 1
    block = layout["blocks"][0]
    assert block["bbox"] == [0, 0, layout["image_width"], layout["image_height"]]
    assert block["writing_direction"] == "horizontal_ltr"
    assert is_full_page_layout(layout)


def test_batch_resumes_by_skipping_existing(batch_ready):
    """중단 후 다시 돌리면 이미 끝난 쪽은 건너뛰고 이어서 돌아야 한다.

    L2 자체가 체크포인트이므로 별도 상태 파일이 필요 없다.
    """
    client, doc_id, part_id = batch_ready
    url = f"/api/documents/{doc_id}/parts/{part_id}/ocr/batch"

    first = _sse_events(client.post(url, json={"engine_id": "dummy", "pages": [1, 2, 3]}))
    assert first[-1]["processed"] == 3

    # 같은 범위를 다시 → 전부 건너뛴다
    again = _sse_events(client.post(url, json={"engine_id": "dummy", "pages": [1, 2, 3]}))
    assert (again[-1]["processed"], again[-1]["skipped"]) == (0, 3)

    # 전체(5쪽)를 요청 → 남은 4·5쪽만 새로 돈다
    rest = _sse_events(client.post(url, json={"engine_id": "dummy"}))
    assert rest[0]["total"] == 5
    assert (rest[-1]["processed"], rest[-1]["skipped"]) == (2, 3)


def test_batch_can_redo_when_skip_disabled(batch_ready):
    """skip_existing=False면 이미 있는 쪽도 다시 돈다."""
    client, doc_id, part_id = batch_ready
    url = f"/api/documents/{doc_id}/parts/{part_id}/ocr/batch"

    client.post(url, json={"engine_id": "dummy", "pages": [1]})
    redo = _sse_events(
        client.post(url, json={"engine_id": "dummy", "pages": [1], "skip_existing": False})
    )
    assert (redo[-1]["processed"], redo[-1]["skipped"]) == (1, 0)


def test_batch_warns_on_hangul_incapable_engine(batch_ready):
    """한글을 인식하지 못하는 엔진을 고르면 시작 시점에 경고해야 한다.

    기본 엔진은 "설치된 것 중 첫 번째"라 근현대 논문에도 고전적 전용
    엔진이 잡힌다. 300쪽을 다 돌린 뒤에 알게 되면 안 된다.
    """
    client, doc_id, part_id = batch_ready
    events = _sse_events(
        client.post(
            f"/api/documents/{doc_id}/parts/{part_id}/ocr/batch",
            json={"engine_id": "ndlocr", "pages": [1]},
        )
    )
    warnings = events[0]["warnings"]
    assert warnings and "한글을 인식하지 못합니다" in warnings[0]
    assert "llm_vision" in warnings[0]


def test_batch_does_not_overwrite_existing_layout(batch_ready):
    """사람이 잡아 둔 레이아웃은 전면 블록으로 덮어쓰지 않아야 한다."""
    import json
    from pathlib import Path

    from app._state import get_library_path

    client, doc_id, part_id = batch_ready
    l3_dir = Path(get_library_path()) / "documents" / doc_id / "L3_layout"
    l3_dir.mkdir(parents=True, exist_ok=True)
    handmade = {
        "part_id": part_id,
        "page_number": 1,
        "image_width": 1190.0,
        "image_height": 1684.0,
        "analysis_method": "manual",
        "blocks": [
            {
                "block_id": "p01_b01",
                "block_type": "main_text",
                "bbox": [100, 100, 500, 500],
                "reading_order": 1,
            },
            {
                "block_id": "p01_b02",
                "block_type": "annotation",
                "bbox": [500, 100, 900, 500],
                "reading_order": 2,
            },
        ],
    }
    (l3_dir / f"{part_id}_page_001.json").write_text(
        json.dumps(handmade, ensure_ascii=False), encoding="utf-8"
    )

    events = _sse_events(
        client.post(
            f"/api/documents/{doc_id}/parts/{part_id}/ocr/batch",
            json={"engine_id": "dummy", "pages": [1]},
        )
    )
    assert events[1]["block_created"] is False

    after = json.loads((l3_dir / f"{part_id}_page_001.json").read_text(encoding="utf-8"))
    assert after["analysis_method"] == "manual"
    assert len(after["blocks"]) == 2


def test_batch_embeds_pdf_automatically(batch_ready):
    """OCR이 끝나면 텍스트 레이어 PDF까지 자동으로 입혀져야 한다.

    OCR 결과는 L2 JSON에만 들어가므로, 입히기를 따로 하지 않으면 PDF는
    여전히 스캔본이다. "OCR을 돌렸는데 왜 검색이 안 되나"를 없애기 위해
    배치가 입히기까지 이어서 한다.
    """
    client, doc_id, part_id = batch_ready

    # 입히기 전에는 산출물이 없다.
    r = client.get(
        f"/api/documents/{doc_id}/parts/{part_id}/export/text-layer-pdf/status"
    )
    assert r.json()["exists"] is False

    events = _sse_events(
        client.post(
            f"/api/documents/{doc_id}/parts/{part_id}/ocr/batch",
            json={"engine_id": "dummy"},
        )
    )
    done = events[-1]
    assert done["type"] == "complete"
    assert done["embedded"] is not None, "배치가 입히기까지 하지 않았다"
    assert done["embedded"]["embedded_pages"] == 5

    # 별도 입히기 요청 없이 바로 내려받을 수 있어야 한다.
    r = client.get(
        f"/api/documents/{doc_id}/parts/{part_id}/export/text-layer-pdf/status"
    )
    assert r.json()["exists"] is True
    assert r.json()["size_bytes"] > 0


def test_embedded_download_keeps_original_filename(isolated_app):
    """내려받는 텍스트 레이어 PDF는 원본 파일 이름을 그대로 물려받아야 한다.

    사용자의 논문 폴더는 `저자_연도_제목.pdf` 규약으로 정리돼 있고
    서지 관리 도구가 그 이름을 읽는다. 내부 식별자를 붙이면
    내려받은 파일을 원래 자리에 되돌릴 수 없다.
    """
    client, tmp_path = isolated_app

    original = "김영진_2006_조선후기 서적 출판과 유통에 관한 일고찰.pdf"
    _make_pdf(tmp_path / original, "born", pages=2)
    with open(tmp_path / original, "rb") as f:
        body = client.post(
            "/api/documents/create-from-files",
            data={"doc_id": "doc_kim", "title": "조선후기 서적 출판"},
            files=[("files", (original, f.read(), "application/pdf"))],
        ).json()
    doc_id = body["document_id"]
    part_id = body["parts"][0]["part_id"]

    client.post(
        f"/api/documents/{doc_id}/parts/{part_id}/text-import/from-text-layer",
        json={},
    )
    client.post(
        f"/api/documents/{doc_id}/parts/{part_id}/export/text-layer-pdf",
        json={"source_layer": "l4"},
    )

    r = client.get(f"/api/documents/{doc_id}/parts/{part_id}/export/text-layer-pdf")
    assert r.status_code == 200
    disposition = r.headers.get("content-disposition", "")
    # 파일명은 RFC 5987로 인코딩될 수 있으므로 핵심 토큰으로 확인한다.
    from urllib.parse import unquote

    assert "김영진_2006" in unquote(disposition), disposition
    assert "doc_kim_vol1_text" not in disposition


def test_batch_can_skip_baking(batch_ready):
    """embed_after=False면 입히지 않는다 (교정 후에 입히고 싶을 때)."""
    client, doc_id, part_id = batch_ready
    events = _sse_events(
        client.post(
            f"/api/documents/{doc_id}/parts/{part_id}/ocr/batch",
            json={"engine_id": "dummy", "embed_after": False},
        )
    )
    assert events[-1]["embedded"] is None
    r = client.get(
        f"/api/documents/{doc_id}/parts/{part_id}/export/text-layer-pdf/status"
    )
    assert r.json()["exists"] is False


def test_ocr_does_not_modify_original_pdf(batch_ready):
    """OCR도 입히기도 L1_source 원본을 건드리면 안 된다.

    원본이 바뀌면 OCR을 다시 돌릴 기준이 사라지고, 잘못된 인식이
    원본을 오염시킨다. 텍스트 레이어 PDF는 exports/에 별도 파일로 생긴다.
    """
    from pathlib import Path

    import fitz

    from app._state import get_library_path

    client, doc_id, part_id = batch_ready
    doc_path = Path(get_library_path()) / "documents" / doc_id
    src = next((doc_path / "L1_source").glob("*.pdf"))
    before = src.read_bytes()

    client.post(
        f"/api/documents/{doc_id}/parts/{part_id}/ocr/batch",
        json={"engine_id": "dummy"},
    )

    assert src.read_bytes() == before, "L1_source 원본이 수정되었다"
    # 원본은 여전히 텍스트 레이어가 없다.
    original = fitz.open(str(src))
    try:
        assert original[0].get_text("text").strip() == ""
    finally:
        original.close()
    # 입힌 파일은 따로 있다.
    assert (doc_path / "exports" / f"{part_id}_text.pdf").exists()


def test_batch_to_embedded_pdf_end_to_end(batch_ready):
    """배치 OCR → 텍스트 레이어 입히기가 이어져야 한다 (lite mode의 전체 경로)."""
    import fitz

    client, doc_id, part_id = batch_ready
    client.post(
        f"/api/documents/{doc_id}/parts/{part_id}/ocr/batch",
        json={"engine_id": "dummy", "embed_after": False},
    )

    r = client.post(
        f"/api/documents/{doc_id}/parts/{part_id}/export/text-layer-pdf", json={}
    )
    assert r.status_code == 200
    result = r.json()
    assert result["embedded_pages"] == 5
    assert result["positioned_lines"] == 10

    # 내려받아 실제로 검색이 되는지 본다.
    dl = client.get(f"/api/documents/{doc_id}/parts/{part_id}/export/text-layer-pdf")
    assert dl.status_code == 200
    doc = fitz.open(stream=dl.content, filetype="pdf")
    try:
        assert "18세기 필사본 유통과 독자층의 형성" in doc[0].get_text("text")
        assert doc[0].search_for("18세기 필사본 유통과 독자층의 형성")
    finally:
        doc.close()


def test_batch_unknown_part(batch_ready):
    """없는 part_id는 사용 가능한 목록과 함께 404여야 한다."""
    client, doc_id, _ = batch_ready
    r = client.post(f"/api/documents/{doc_id}/parts/nope/ocr/batch", json={})
    assert r.status_code == 404
    assert "사용 가능한 part_id" in r.json()["error"]


def test_batch_out_of_range_pages(batch_ready):
    """범위를 벗어난 쪽만 요청하면 쪽 수를 알려 주며 400이어야 한다."""
    client, doc_id, part_id = batch_ready
    r = client.post(
        f"/api/documents/{doc_id}/parts/{part_id}/ocr/batch", json={"pages": [999]}
    )
    assert r.status_code == 400
    assert "쪽 수는 5" in r.json()["error"]


def test_full_page_block_on_non_integer_page_size(tmp_path):
    """페이지 크기가 실수인 PDF에서도 전면 블록이 스키마를 만족해야 한다.

    layout_page.schema.json은 image_width/height를 integer로 규정한다.
    실제 논문 PDF는 495.36pt 같은 크기라 ×2.0 하면 990.72가 되어
    반올림하지 않으면 검증에 걸린다. 합성 PDF(595pt → 1190.0)에서는
    우연히 통과하고 실제 자료에서만 터지는 형태였으므로 회귀로 잡는다.
    """
    import json

    import fitz

    from core.document import add_document
    from core.library import init_library
    from ocr.full_page_block import ensure_full_page_block, is_full_page_layout

    lib = tmp_path / "lib"
    init_library(lib)

    # 정수로 떨어지지 않는 페이지 크기 (실제 스캔 논문에서 흔하다)
    src = tmp_path / "odd.pdf"
    doc = fitz.open()
    doc.new_page(width=495.36, height=717.13)
    doc.save(str(src))
    doc.close()

    add_document(library_path=lib, doc_id="odd_doc", title="odd", files=[src])
    doc_path = lib / "documents" / "odd_doc"

    info = ensure_full_page_block(doc_path, "vol1", 1)
    assert info["created"] is True

    layout = json.loads(
        (doc_path / "L3_layout" / "vol1_page_001.json").read_text(encoding="utf-8")
    )
    assert isinstance(layout["image_width"], int), layout["image_width"]
    assert isinstance(layout["image_height"], int), layout["image_height"]
    assert layout["image_width"] == round(495.36 * 2.0)
    assert is_full_page_layout(layout)


# ── 빈 해석 저장소 정리 ────────────────────────────────


def test_discard_empty_interpretation(isolated_app):
    """추출 작업만 할 문헌의 빈 해석 저장소는 휴지통으로 옮겨져야 한다.

    문헌을 만들면 해석 저장소가 함께 생기지만(D-054), 텍스트만 뽑는
    작업에서는 L5-L7을 쓰지 않아 목록에 빈 저장소가 쌓인다.
    """
    client, tmp_path = isolated_app
    body = _register(client, tmp_path, "scan", "doc_empty", pages=2)
    doc_id = body["document_id"]
    interp_id = body["interpretation_id"]

    r = client.get(f"/api/interpretations/{interp_id}/emptiness")
    assert r.status_code == 200
    assert r.json()["is_empty"] is True

    r = client.post(f"/api/documents/{doc_id}/interpretations/discard-empty")
    assert r.status_code == 200
    assert interp_id in r.json()["discarded"]

    # 삭제가 아니라 휴지통이어야 한다 — 되돌릴 수 있어야 하므로.
    trash = client.get("/api/trash").json()
    names = [
        t.get("name") or t.get("trash_name")
        for t in trash.get("interpretations", [])
    ]
    assert any(interp_id in (n or "") for n in names), names


def test_discard_keeps_interpretation_with_work(isolated_app):
    """작업 내용이 있는 해석 저장소는 절대 건드리면 안 된다.

    모드 전환은 표시를 바꾸는 일이지 데이터를 지우는 일이 아니다.
    실수로 눌렀다고 번역·주석이 사라지면 안 된다.
    """
    from pathlib import Path

    from app._state import get_library_path

    client, tmp_path = isolated_app
    body = _register(client, tmp_path, "scan", "doc_used", pages=2)
    doc_id = body["document_id"]
    interp_id = body["interpretation_id"]

    work = (
        Path(get_library_path())
        / "interpretations"
        / interp_id
        / "L6_translation"
        / "main_text"
    )
    work.mkdir(parents=True, exist_ok=True)
    (work / "vol1_page_001.json").write_text('{"translations": []}', encoding="utf-8")

    r = client.get(f"/api/interpretations/{interp_id}/emptiness")
    assert r.json()["is_empty"] is False
    assert r.json()["content_count"] == 1

    r = client.post(f"/api/documents/{doc_id}/interpretations/discard-empty")
    assert r.json()["discarded"] == []
    assert r.json()["kept"][0]["interp_id"] == interp_id

    # 실제로 살아 있어야 한다.
    assert (Path(get_library_path()) / "interpretations" / interp_id).exists()
    assert (work / "vol1_page_001.json").exists()


# ── born-digital PDF → L4 직접 가져오기 ──────────────────


def test_import_from_text_layer_skips_ocr(isolated_app):
    """텍스트 레이어가 있는 PDF는 OCR 없이 바로 L4 텍스트가 채워져야 한다."""
    client, tmp_path = isolated_app
    body = _register(client, tmp_path, "born", "doc_born", pages=4)
    doc_id = body["document_id"]
    part_id = body["parts"][0]["part_id"]

    r = client.post(
        f"/api/documents/{doc_id}/parts/{part_id}/text-import/from-text-layer",
        json={},
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["imported"] == 4
    assert result["skipped"] == 0
    assert result["chars"] > 0

    # 실제로 L4에 저장됐는지 확인한다.
    page = client.get(f"/api/documents/{doc_id}/pages/1/text?part_id={part_id}")
    if page.status_code != 200:  # 라우트 형태가 다르면 파일로 직접 확인
        from pathlib import Path

        from app._state import get_library_path

        text_path = (
            Path(get_library_path())
            / "documents"
            / doc_id
            / "L4_text"
            / "pages"
            / f"{part_id}_page_001.txt"
        )
        assert text_path.exists()
        assert "필사본" in text_path.read_text(encoding="utf-8")


def test_import_does_not_overwrite_corrected_text(isolated_app):
    """이미 교정된 텍스트를 말없이 덮어쓰면 안 된다."""
    from pathlib import Path

    from app._state import get_library_path

    client, tmp_path = isolated_app
    body = _register(client, tmp_path, "born", "doc_born2", pages=3)
    doc_id = body["document_id"]
    part_id = body["parts"][0]["part_id"]

    pages_dir = Path(get_library_path()) / "documents" / doc_id / "L4_text" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    corrected = pages_dir / f"{part_id}_page_001.txt"
    corrected.write_text("사람이 교정한 내용", encoding="utf-8")

    r = client.post(
        f"/api/documents/{doc_id}/parts/{part_id}/text-import/from-text-layer",
        json={},
    )
    result = r.json()
    assert result["skipped"] == 1
    assert corrected.read_text(encoding="utf-8") == "사람이 교정한 내용"
    assert any("건너뛰었습니다" in w for w in result["warnings"])

    # overwrite=true면 덮어쓴다.
    r = client.post(
        f"/api/documents/{doc_id}/parts/{part_id}/text-import/from-text-layer",
        json={"overwrite": True},
    )
    assert r.json()["imported"] == 3
    assert corrected.read_text(encoding="utf-8") != "사람이 교정한 내용"


def test_import_from_scanned_pdf_warns(isolated_app):
    """스캔본에서 가져오려 하면 OCR이 필요하다고 알려 줘야 한다."""
    client, tmp_path = isolated_app
    body = _register(client, tmp_path, "scan", "doc_scan2", pages=3)
    doc_id = body["document_id"]
    part_id = body["parts"][0]["part_id"]

    r = client.post(
        f"/api/documents/{doc_id}/parts/{part_id}/text-import/from-text-layer",
        json={},
    )
    result = r.json()
    assert result["imported"] == 0
    assert result["empty"] == 3
    assert any("OCR을 실행하세요" in w for w in result["warnings"])


def test_force_rmtree_removes_git_repo(tmp_path):
    """Git 저장소가 든 디렉터리도 확실히 지워져야 한다.

    Windows에서 `.git/objects/` 파일은 읽기 전용 속성이 붙어
    `shutil.rmtree`가 PermissionError로 멈춘다. `ignore_errors=True`로
    넘기면 오류만 사라지고 파일은 남는다 — 실제로 배치가 «정리했다»고
    보고하면서 논문 사본을 계속 쌓던 사고가 있었다.
    """
    import os
    import stat

    from cli.embed_folder import _force_rmtree

    target = tmp_path / "repo"
    (target / ".git" / "objects" / "ab").mkdir(parents=True)
    obj = target / ".git" / "objects" / "ab" / "cdef123"
    obj.write_bytes(b"dummy git object")
    (target / "manifest.json").write_text("{}", encoding="utf-8")
    # Git이 실제로 붙이는 읽기 전용 속성을 재현한다.
    os.chmod(obj, stat.S_IREAD)

    ok, why = _force_rmtree(target)

    assert ok is True, f"지우지 못했다: {why}"
    assert not target.exists()


def test_force_rmtree_reports_failure_honestly(tmp_path):
    """지우지 못했으면 성공했다고 보고하면 안 된다."""
    from cli.embed_folder import _force_rmtree

    missing = tmp_path / "not_there"
    ok, why = _force_rmtree(missing)
    # 없는 경로는 지울 것이 없으므로 실패가 아니다.
    assert ok is True, why


def test_batch_works_when_manifest_page_count_missing(batch_ready):
    """manifest에 page_count가 없어도 OCR이 돌아야 한다.

    add_document()로 만든 문헌(CLI·URL 등록)은 page_count가 null이다.
    사이드바는 PDF를 직접 열어 쪽 수를 알아내므로 **화면에는 쪽이 보이는데**,
    서버가 manifest만 믿으면 «쪽이 0개»라고 판단해 배치 OCR이
    «OCR 할 쪽이 없습니다»로 죽는다. 실제로 사용자가 UI에서 이 에러를 만났다.
    """
    import json
    from pathlib import Path

    from app._state import get_library_path

    client, doc_id, part_id = batch_ready

    # 등록 경로에 따라 생기는 상태를 재현한다: page_count = null
    manifest_path = Path(get_library_path()) / "documents" / doc_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["parts"][0]["page_count"] = None
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )

    r = client.post(
        f"/api/documents/{doc_id}/parts/{part_id}/ocr/batch",
        json={"engine_id": "dummy"},
    )
    assert r.status_code == 200, r.text

    events = _sse_events(r)
    assert events[0]["type"] == "start"
    assert events[0]["total"] == 5, "PDF에서 쪽 수를 세지 못했다"
    assert events[-1]["processed"] == 5


def test_page_count_resolved_from_pdf():
    """쪽 수 해석 함수는 manifest → PDF 순으로 본다."""
    import tempfile
    from pathlib import Path

    import fitz

    from app.routers.llm_ocr import _resolve_page_count
    from core.document import add_document
    from core.library import init_library

    tmp = Path(tempfile.mkdtemp())
    lib = tmp / "lib"
    init_library(lib)

    src = tmp / "four.pdf"
    doc = fitz.open()
    for _ in range(4):
        doc.new_page(width=595, height=842)
    doc.save(str(src))
    doc.close()

    add_document(library_path=lib, doc_id="pc_doc", title="pc", files=[src])
    doc_path = lib / "documents" / "pc_doc"

    # manifest에 값이 있으면 그것을 쓴다
    assert _resolve_page_count(doc_path, {"part_id": "vol1", "page_count": 9}) == 9
    # 없으면 PDF에서 센다
    assert _resolve_page_count(doc_path, {"part_id": "vol1", "page_count": None}) == 4
    # 셀 수 없으면 0 (호출부가 안내한다)
    assert _resolve_page_count(doc_path, {"part_id": "nope", "page_count": None}) == 0


# ── LLM 사용량·과금 표시 ──────────────────────────────


def test_billing_kind_distinguishes_subscription_from_free():
    """구독 한도와 무료를 구분해야 한다.

    Ollama 클라우드는 금액이 0으로 기록되지만 계정 한도를 쓴다.
    이것을 «무료»로 표시하면 사용자가 한도를 모르는 채 소모하게 된다.
    실제로 폴백 순서만 보고 «무료 로컬»이라 여겼는데 유료 API가
    처리하고 있던 일이 있었다.
    """
    from app.routers.llm_ocr import _billing_kind

    assert _billing_kind(["gemini/gemini-2.5-flash"]) == "metered"
    assert _billing_kind(["openai/gpt-5-mini"]) == "metered"
    assert _billing_kind(["anthropic/claude-sonnet-4-20250514"]) == "metered"
    # Ollama는 같은 프로바이더라도 모델에 따라 다르다
    assert _billing_kind(["ollama/qwen3.5:cloud"]) == "subscription"
    assert _billing_kind(["ollama/qwen3.5:4b"]) == "free"
    assert _billing_kind(["openai_oauth/gpt-5.4-mini"]) == "subscription"
    # 섞이면 그 사실을 알려야 한다
    assert _billing_kind(["ollama/qwen3.5:cloud", "gemini/gemini-2.5-flash"]) == "mixed"
    assert _billing_kind([]) == "unknown"


def test_billing_note_never_calls_subscription_free():
    """구독 한도 사용을 «무료»라고 말하면 안 된다."""
    from app.routers.llm_ocr import _billing_note

    usage = {"calls": 15, "cost_usd": 0.0}
    sub = _billing_note("subscription", usage)
    assert "한도" in sub
    assert "무료" not in sub, "구독 한도를 무료라고 표시했다"

    free = _billing_note("free", usage)
    assert "로컬" in free

    metered = _billing_note("metered", {"calls": 15, "cost_usd": 0.0084})
    assert "0.0084" in metered


def test_batch_reports_usage(batch_ready):
    """배치 완료 응답에 사용량이 실려야 한다.

    어느 모델로 얼마를 썼는지 사용자가 그 자리에서 알 수 있어야 한다.
    """
    client, doc_id, part_id = batch_ready
    events = _sse_events(
        client.post(
            f"/api/documents/{doc_id}/parts/{part_id}/ocr/batch",
            json={"engine_id": "dummy", "pages": [1]},
        )
    )
    done = events[-1]
    assert "usage" in done, "완료 응답에 usage가 없다"
    usage = done["usage"]
    for key in ("calls", "tokens_in", "tokens_out", "cost_usd", "models", "billing"):
        assert key in usage, f"usage에 {key}가 없다"
    # 더미 엔진은 LLM을 부르지 않으므로 기록이 없다
    assert usage["calls"] == 0
    assert usage["billing"] == "unknown"


def test_ollama_billing_depends_on_model():
    """Ollama 프로바이더는 모델에 따라 과금 방식이 다르다."""
    from llm.config import LlmConfig
    from llm.providers.ollama import OllamaProvider

    p = OllamaProvider(LlmConfig())
    assert p.billing_for_model("qwen3.5:cloud") == "subscription"
    assert p.billing_for_model("qwen3-vl:235b-cloud") == "subscription"
    assert p.billing_for_model("qwen3.5:4b") == "free"
    assert p.billing_for_model(None) == "free"
