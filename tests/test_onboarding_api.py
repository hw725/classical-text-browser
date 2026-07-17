"""온보딩(첫 실행) API 경로 테스트.

대상:
    - POST /api/library/quick-start — 기본 서고 자동 생성/재사용
    - POST /api/documents/create-from-files — doc_id 자동 생성 (드래그 앤 드롭 온보딩)

왜 이 테스트가 있는가:
    2026-07-17 인지부채 감사에서 "서고 초기화 → 문헌 생성" 온보딩 경로가
    테스트 0건임이 확인되었다. 드래그 앤 드롭 온보딩이 이 경로 위에
    세워졌으므로, 최소한의 API 레벨 안전망을 여기서 시작한다.
    (이 저장소의 첫 API 레벨(TestClient) 테스트다.)
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def isolated_app(tmp_path, monkeypatch):
    """가짜 홈 디렉토리로 격리된 TestClient를 만든다.

    왜 홈을 격리하는가:
        quick-start는 Path.home() 아래에 서고를 만들고,
        최근 서고 목록은 ~/.classical-text-browser/config.json에 기록된다.
        실제 사용자 홈을 건드리면 안 된다.

    왜 전역 서고 상태를 저장/복원하는가:
        _state._library_path는 프로세스 전역이라, 이 테스트가
        서고를 전환한 채로 끝나면 다른 테스트가 오염된다.
    """
    # Windows에서 Path.home()은 USERPROFILE을 먼저 본다 (POSIX는 HOME).
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
            yield client, fake_home
    finally:
        set_library_path(str(saved) if saved else None)


def _make_test_pdf(path, pages=2):
    """PyMuPDF로 작은 진짜 PDF를 만든다 (업로드 헤더 검증 %PDF 통과용)."""
    import fitz

    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=200, height=280)
    doc.save(str(path))
    doc.close()
    return path


def test_quick_start_creates_then_reuses(isolated_app):
    """quick-start: 첫 호출은 생성(created=true), 재호출은 재사용(created=false)."""
    client, fake_home = isolated_app

    # 서고 미설정 상태 확인
    assert client.get("/api/library").status_code == 500

    r1 = client.post("/api/library/quick-start")
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["ok"] is True
    assert body1["created"] is True
    assert "고전서지서고" in body1["library_path"]

    # 이제 서고가 연결되어 있어야 한다
    assert client.get("/api/library").status_code == 200

    # 재호출 — 같은 서고 재사용
    r2 = client.post("/api/library/quick-start")
    assert r2.status_code == 200
    assert r2.json()["created"] is False
    assert r2.json()["library_path"] == body1["library_path"]


def test_create_from_files_auto_doc_id_cjk(isolated_app, tmp_path):
    """한자 파일명 + doc_id 미지정: 날짜 기반 doc_id 자동 생성, 제목은 원본 보존."""
    client, _ = isolated_app
    client.post("/api/library/quick-start")

    pdf = _make_test_pdf(tmp_path / "src.pdf")

    def upload():
        with open(pdf, "rb") as fp:
            return client.post(
                "/api/documents/create-from-files",
                files=[("files", ("舊注蒙求.pdf", fp, "application/pdf"))],
            )

    r1 = upload()
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    # 한자 파일명 → ASCII 후보가 비므로 doc_YYYYMMDD 형식
    assert d1["document_id"].startswith("doc_")
    # 제목은 원본 파일명(한자) 보존
    assert d1["title"] == "舊注蒙求"

    # 기본 해석 저장소가 함께 자동 생성된다 (D-054)
    assert d1["interpretation_id"] == d1["document_id"] + "_interp"
    assert d1["warning"] is None
    interp_list = client.get("/api/interpretations").json()
    interp_ids = [
        i.get("interpretation_id") or i.get("id") for i in interp_list
    ]
    assert d1["interpretation_id"] in interp_ids

    # 같은 조건 재업로드 → 충돌 회피 접미사
    r2 = upload()
    assert r2.status_code == 200, r2.text
    assert r2.json()["document_id"] == d1["document_id"] + "_2"


def test_create_from_files_auto_doc_id_ascii(isolated_app, tmp_path):
    """ASCII 파일명 + doc_id 미지정: 파일명 기반 doc_id, 형식 규칙 준수."""
    import re

    client, _ = isolated_app
    client.post("/api/library/quick-start")

    pdf = _make_test_pdf(tmp_path / "src.pdf")
    with open(pdf, "rb") as fp:
        r = client.post(
            "/api/documents/create-from-files",
            files=[("files", ("Monggu-Vol1.pdf", fp, "application/pdf"))],
        )
    assert r.status_code == 200, r.text
    doc_id = r.json()["document_id"]
    assert doc_id == "monggu_vol1"
    assert re.match(r"^[a-z][a-z0-9_]{0,63}$", doc_id)


def test_create_from_files_explicit_doc_id_unchanged(isolated_app, tmp_path):
    """명시적 doc_id는 기존 동작 그대로 (자동 생성이 이를 덮지 않는다)."""
    client, _ = isolated_app
    client.post("/api/library/quick-start")

    pdf = _make_test_pdf(tmp_path / "src.pdf")
    with open(pdf, "rb") as fp:
        r = client.post(
            "/api/documents/create-from-files",
            data={"doc_id": "my_doc"},
            files=[("files", ("any.pdf", fp, "application/pdf"))],
        )
    assert r.status_code == 200, r.text
    assert r.json()["document_id"] == "my_doc"

    # 잘못된 형식은 여전히 400
    with open(pdf, "rb") as fp:
        r_bad = client.post(
            "/api/documents/create-from-files",
            data={"doc_id": "한글아이디"},
            files=[("files", ("any.pdf", fp, "application/pdf"))],
        )
    assert r_bad.status_code == 400
