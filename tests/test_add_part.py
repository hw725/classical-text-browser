"""문헌에 권(part)을 나중에 더하는 기능 테스트.

왜 이 테스트가 있는가:
    `parts`는 지금까지 **문헌을 만들 때 한 번 정해지면 끝**이었다
    (add_document / create-from-files 안에서만 채워졌다). 그래서 卷下를
    뒤늦게 구하면 문헌을 지우고 처음부터 다시 만들어야 했고, 그러면 이미 한
    OCR·교정이 전부 사라졌다.

    이 라우트는 manifest를 고치는 몇 안 되는 경로다. 잘못 쓰면 문헌이 통째로
    열리지 않게 되므로, «실패하면 아무것도 바꾸지 않는다»를 회귀로 고정한다.
"""

import json

import fitz
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))

    from app._state import get_library_path, set_library_path
    from app.server import app

    saved = get_library_path()
    set_library_path(None)
    try:
        with TestClient(app) as c:
            c.post("/api/library/quick-start")
            yield c, tmp_path
    finally:
        set_library_path(str(saved) if saved else None)


def _pdf(path, pages: int, text: str):
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((70, 100), f"{text} {i + 1}", fontname="korea", fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def _make_doc(client, tmp_path, doc_id="monggu"):
    src = _pdf(tmp_path / "卷上.pdf", 3, "卷上")
    with open(src, "rb") as f:
        r = client.post(
            "/api/documents/create-from-files",
            data={"doc_id": doc_id, "title": "蒙求"},
            files=[("files", ("卷上.pdf", f.read(), "application/pdf"))],
        )
    assert r.status_code == 200, r.text
    return r.json()["document_id"]


def _add(client, doc_id, path, name, label=None):
    with open(path, "rb") as f:
        return client.post(
            f"/api/documents/{doc_id}/parts",
            files=[("files", (name, f.read(), "application/pdf"))],
            data={"label": label} if label else None,
        )


def test_adds_part_with_page_count(client, tmp_path):
    """권을 더하면 쪽 수까지 함께 기록된다."""
    c, tmp = client
    doc_id = _make_doc(c, tmp)

    r = _add(c, doc_id, _pdf(tmp / "卷下.pdf", 5, "卷下"), "卷下.pdf", label="卷下")
    assert r.status_code == 200, r.text
    added = r.json()["added"]
    assert len(added) == 1
    assert added[0]["part_id"] == "vol2"
    assert added[0]["label"] == "卷下"
    assert added[0]["page_count"] == 5

    parts = c.get(f"/api/documents/{doc_id}").json()["parts"]
    assert [p["part_id"] for p in parts] == ["vol1", "vol2"]


def test_label_defaults_to_filename(client, tmp_path):
    """이름을 안 주면 파일 이름을 쓴다."""
    c, tmp = client
    doc_id = _make_doc(c, tmp)
    r = _add(c, doc_id, _pdf(tmp / "부록.pdf", 2, "부록"), "부록.pdf")
    assert r.json()["added"][0]["label"] == "부록"


def test_same_filename_does_not_overwrite(client, tmp_path):
    """같은 이름을 또 넣어도 앞선 권의 원본을 덮지 않는다.

    덮으면 그 권의 OCR 결과가 가리키는 원본이 사라진다.
    """
    c, tmp = client
    doc_id = _make_doc(c, tmp)
    src = _pdf(tmp / "같은이름.pdf", 2, "A")
    _add(c, doc_id, src, "같은이름.pdf")
    _add(c, doc_id, src, "같은이름.pdf")

    files = [p["file"] for p in c.get(f"/api/documents/{doc_id}").json()["parts"]]
    assert len(files) == len(set(files)), f"파일이 겹친다: {files}"
    assert any("같은이름_2" in f for f in files)


def test_part_ids_stay_unique(client, tmp_path):
    """part_id는 문헌 안에서 유일해야 한다 (스키마 패턴도 지킨다)."""
    import re

    c, tmp = client
    doc_id = _make_doc(c, tmp)
    for i in range(3):
        _add(c, doc_id, _pdf(tmp / f"p{i}.pdf", 1, "본문"), f"p{i}.pdf")

    ids = [p["part_id"] for p in c.get(f"/api/documents/{doc_id}").json()["parts"]]
    assert len(ids) == len(set(ids)) == 4
    for pid in ids:
        assert re.fullmatch(r"[a-z][a-z0-9_]{0,31}", pid), pid


def test_rejects_non_pdf(client, tmp_path):
    """PDF가 아니면 거부한다. 트리가 권을 PDF.js로 열기 때문이다."""
    c, tmp = client
    doc_id = _make_doc(c, tmp)
    r = c.post(
        f"/api/documents/{doc_id}/parts",
        files=[("files", ("메모.txt", b"hello", "text/plain"))],
    )
    assert r.status_code == 400
    assert "PDF" in r.json()["error"]
    # 아무것도 안 늘었다
    assert len(c.get(f"/api/documents/{doc_id}").json()["parts"]) == 1


def test_unknown_document_is_404(client, tmp_path):
    c, tmp = client
    r = _add(c, "nosuchdoc", _pdf(tmp / "x.pdf", 1, "x"), "x.pdf")
    assert r.status_code == 404


def test_manifest_stays_valid(client, tmp_path):
    """추가 후에도 manifest가 스키마를 만족한다."""
    import jsonschema

    c, tmp = client
    doc_id = _make_doc(c, tmp)
    _add(c, doc_id, _pdf(tmp / "卷下.pdf", 4, "卷下"), "卷下.pdf", label="卷下")

    from pathlib import Path

    from app._state import get_library_path

    manifest = json.loads(
        (Path(get_library_path()) / "documents" / doc_id / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    schema = json.loads(
        (Path("schemas/source_repo/manifest.schema.json")).read_text(encoding="utf-8")
    )
    jsonschema.validate(instance=manifest, schema=schema)


def test_existing_ocr_survives(client, tmp_path):
    """권을 더해도 기존 권의 OCR 결과가 남는다.

    이 라우트를 만든 이유가 «다시 만들면 작업이 사라진다»이므로,
    더하는 행위 자체가 작업을 지우면 앞뒤가 안 맞는다.
    """
    from pathlib import Path

    from app._state import get_library_path

    c, tmp = client
    doc_id = _make_doc(c, tmp)
    doc_path = Path(get_library_path()) / "documents" / doc_id
    (doc_path / "L2_ocr").mkdir(exist_ok=True)
    marker = doc_path / "L2_ocr" / "vol1_page_001.json"
    marker.write_text('{"part_id":"vol1","page_number":1,"ocr_results":[]}', "utf-8")

    before = c.get(f"/api/documents/{doc_id}").json()["parts"][0]
    _add(c, doc_id, _pdf(tmp / "卷下.pdf", 2, "卷下"), "卷下.pdf")

    assert marker.exists(), "권을 더했더니 기존 OCR 결과가 사라졌다"
    # 기존 권의 원본 파일도 그대로여야 한다. (create-from-files는 파일명을
    # <doc_id>_pdfN.pdf 로 바꾸므로 이름을 짐작하지 말고 manifest에서 읽는다.)
    after = c.get(f"/api/documents/{doc_id}").json()["parts"][0]
    assert after == before, f"기존 권 정보가 바뀌었다: {before} → {after}"
    assert (doc_path / before["file"]).exists(), "기존 권의 원본이 사라졌다"
