"""다권본에서 **그 권의** PDF를 읽는지 확인한다 (D-069).

왜 이 시험이 따로 필요한가:
    예전에는 `L1_source/*.pdf`를 glob 해서 첫 번째를 썼다. part_id를 아예
    보지 않았으므로 卷下 5쪽을 OCR 하면 卷上 5쪽 이미지가 엔진에 넘어갔다.
    **오류가 나지 않는다** — 그럴듯한 인식 결과가 그대로 저장되고, 원본과
    텍스트의 대응이 조용히 끊어진다. 이 저장소가 지키려는 것이 바로 그
    대응이므로, 가장 아프면서 가장 늦게 발견되는 종류의 결함이다.

    기존 OCR 테스트는 더미 엔진과 단권 문헌만 쓴다. 이 부류를 잡지 못한다.
"""

import json
from pathlib import Path

import fitz
import pytest

from ocr.image_utils import load_page_image_from_pdf, resolve_part_pdf

PAGE_W, PAGE_H = 300, 400


def _make_volume(path: Path, vol: int, pages: int = 3) -> None:
    """쪽마다 «몇 권 몇 쪽»이 크게 찍힌 PDF를 만든다."""
    doc = fitz.open()
    try:
        for pg in range(1, pages + 1):
            page = doc.new_page(width=PAGE_W, height=PAGE_H)
            page.insert_text((40, 200), f"VOL{vol} PAGE{pg}", fontname="helv", fontsize=28)
        doc.save(str(path))
    finally:
        doc.close()


@pytest.fixture()
def multivol_library(tmp_path):
    """卷上·卷下 두 권을 가진 문헌이 든 서고."""
    doc_path = tmp_path / "documents" / "multi"
    (doc_path / "L1_source").mkdir(parents=True)
    _make_volume(doc_path / "L1_source" / "multi_vol1.pdf", 1)
    _make_volume(doc_path / "L1_source" / "multi_vol2.pdf", 2)

    (doc_path / "manifest.json").write_text(
        json.dumps(
            {
                "document_id": "multi",
                "title": "다권본 시험",
                "parts": [
                    {
                        "part_id": "vol1",
                        "label": "卷上",
                        "file": "L1_source/multi_vol1.pdf",
                        "page_count": 3,
                    },
                    {
                        "part_id": "vol2",
                        "label": "卷下",
                        "file": "L1_source/multi_vol2.pdf",
                        "page_count": 3,
                    },
                ],
                "created_at": "2026-07-26T00:00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return tmp_path, doc_path


def test_resolve_part_pdf_picks_the_right_volume(multivol_library):
    """part_id가 가리키는 권의 파일을 골라야 한다."""
    _, doc_path = multivol_library

    assert resolve_part_pdf(doc_path, "vol1").name == "multi_vol1.pdf"
    assert resolve_part_pdf(doc_path, "vol2").name == "multi_vol2.pdf"
    # part_id가 없으면 첫 권. glob 순서가 아니라 manifest 순서다.
    assert resolve_part_pdf(doc_path, None).name == "multi_vol1.pdf"


def test_page_image_differs_between_volumes(multivol_library):
    """같은 쪽 번호라도 권이 다르면 **다른 이미지**여야 한다.

    이것이 무너지면 卷下를 OCR 해도 卷上 글자가 저장된다.
    """
    lib_root, _ = multivol_library

    img1 = load_page_image_from_pdf(str(lib_root), "multi", 2, part_id="vol1")
    img2 = load_page_image_from_pdf(str(lib_root), "multi", 2, part_id="vol2")

    assert img1 is not None and img2 is not None
    assert img1.tobytes() != img2.tobytes(), "두 권의 같은 쪽이 같은 이미지로 나왔다"


def test_falls_back_when_manifest_is_broken(multivol_library):
    """manifest를 못 읽어도 **이름 순서**로 물러난다 — glob 순서에 기대지 않는다."""
    _, doc_path = multivol_library
    (doc_path / "manifest.json").write_text("{ 깨진 JSON", encoding="utf-8")

    # part_id가 파일 이름에 들어 있으면 그것으로 찾는다.
    assert resolve_part_pdf(doc_path, "vol2").name == "multi_vol2.pdf"
    # 단서가 없으면 이름 순 첫 번째.
    assert resolve_part_pdf(doc_path, None).name == "multi_vol1.pdf"


def test_missing_part_does_not_crash(multivol_library):
    """없는 권을 물어도 예외 대신 첫 권 또는 None으로 답한다."""
    lib_root, doc_path = multivol_library

    resolved = resolve_part_pdf(doc_path, "vol9")
    # manifest에 없는 권이면 get_pdf_path가 예외 → 이름 매칭 실패 → 첫 권
    assert resolved is None or resolved.exists()

    img = load_page_image_from_pdf(str(lib_root), "multi", 99, part_id="vol1")
    assert img is None, "범위 밖 쪽은 None이어야 한다"


def test_source_pdfs_are_not_modified(multivol_library):
    """L1_source는 읽기만 한다 — 이미지를 뽑아도 원본이 바뀌면 안 된다."""
    lib_root, doc_path = multivol_library
    before = {
        p.name: p.read_bytes() for p in (doc_path / "L1_source").glob("*.pdf")
    }

    for part_id in ("vol1", "vol2"):
        for page in (1, 2, 3):
            load_page_image_from_pdf(str(lib_root), "multi", page, part_id=part_id)

    after = {p.name: p.read_bytes() for p in (doc_path / "L1_source").glob("*.pdf")}
    assert after == before
