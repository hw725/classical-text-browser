"""API 응답의 캐시 금지 헤더 테스트.

왜 이 테스트가 있는가:
    API가 돌려주는 것은 작업 중에 바뀌는 데이터다(OCR 결과, 레이아웃, 교정,
    진행 상황). 응답에 Cache-Control이 없으면 브라우저가 스스로 캐시 기간을
    추정해 **고친 결과가 화면에 안 나타난다.**

    실제로 그 사고가 있었다 — 배치 OCR이 L3 전면 블록을 새로 만들었는데
    레이아웃 탭에는 «블록이 없던 시절»이 남아 있었다(D-063).
    점검해 보니 프론트에서 변하는 데이터를 캐시 지정 없이 읽는 곳이
    47군데였고, 한 곳씩 고치면 새 코드에서 또 빠지므로 서버에서 붙인다.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    from app.server import app

    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize(
    "path",
    [
        "/api/llm/status",
        "/api/ocr/engines",
        "/api/library",
        "/api/documents",
    ],
)
def test_api_responses_are_not_cached(client, path):
    """성공이든 실패든 API 응답에는 캐시 금지가 붙는다.

    오류 응답도 캐시되면 «고쳤는데 계속 같은 오류»가 된다.
    """
    r = client.get(path)
    assert r.headers.get("cache-control") == "no-store", (
        f"{path} 응답에 캐시 금지가 없다 (status={r.status_code})"
    )


def test_static_files_keep_revalidation(client):
    """정적 파일은 no-store가 아니라 no-cache다.

    내용이 그대로면 304로 끝나 본문 전송이 없다. API와 달리 재검증할
    값이 있으므로 구분한다.
    """
    r = client.get("/static/js/extract-panel.js")
    assert r.status_code == 200
    assert "no-cache" in (r.headers.get("cache-control") or "")


def test_non_api_pages_are_untouched(client):
    """API가 아닌 경로에는 이 미들웨어가 손대지 않는다."""
    r = client.get("/")
    assert r.headers.get("cache-control") != "no-store"


def test_original_pdf_revalidates_instead_of_no_store(client):
    """원본 PDF는 no-store가 아니라 no-cache다 (2026-09-05 성능 실측).

    왜: PDF는 «작업 중에 바뀌는 데이터»가 아니라 원본 파일이다. 78.9MB짜리 문헌에
    no-store를 붙이면 쪽을 넘길 때마다 조각을 다시 받는다. ETag가 나가므로 no-cache면
    바뀌지 않은 동안 304로 끝난다 — «고쳤는데 반영이 안 된다»는 그대로 막힌다.
    """
    r = client.get("/api/documents/없는문헌/pdf/vol1")
    cc = r.headers.get("cache-control") or ""
    assert "no-cache" in cc and "no-store" not in cc, (
        f"PDF 경로의 캐시 지시가 {cc!r}다 (status={r.status_code})"
    )
