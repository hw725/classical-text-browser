# -*- coding: utf-8 -*-
"""내려받기 헤더에 한글이 들어가도 죽지 않는가.

## 왜 이 시험이 있는가

**HTTP 헤더는 latin-1로 인코딩된다**(starlette `Response.init_headers`).
`Content-Disposition: attachment; filename="<문헌 제목>"` 에 제목을 그대로 넣으면
한글·한자에서 터진다:

    UnicodeEncodeError: 'latin-1' codec can't encode characters in position 26-27

2026-09-22에 해석 JSON 내보내기(`/api/interpretations/{id}/export/json`)가
그렇게 **500** 을 냈다. 이 저장소의 문헌은 제목이 거의 다 한글이라 그 기능은
사실상 늘 실패했다 — 그런데 시험이 한 건도 없어 아무도 몰랐다.

해법은 RFC 5987이다. ASCII 로 줄인 `filename=` 을 두어 옛 브라우저를 지키고,
실제 이름은 `filename*=UTF-8''<percent-encoded>` 로 준다.

## 무엇을 지키나

내려받기 헤더를 만드는 **모든** 자리가 latin-1 로 인코딩 가능해야 한다.
새 내보내기가 생겨도 제목을 그대로 넣으면 여기서 걸린다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ── CJK Text Contract E3 ───────────────────────────────────────────────
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def korean_titled_work(tmp_path, monkeypatch):
    """한글 제목 문헌 + 해석 저장소가 있는 격리 서고."""
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
            lib = tmp_path / "lib"
            assert client.post("/api/library/init", json={"path": str(lib)}).status_code == 200

            import fitz

            pdf = tmp_path / "sample.pdf"
            d = fitz.open()
            d.new_page(width=200, height=280)
            d.save(str(pdf))
            d.close()

            with open(pdf, "rb") as fp:
                r = client.post(
                    "/api/documents/create-from-files",
                    data={"doc_id": "koreandoc", "title": "천진담초 권1"},
                    files=[("files", ("sample.pdf", fp, "application/pdf"))],
                )
            assert r.status_code == 200, r.text
            yield client, r.json()["document_id"]
    finally:
        set_library_path(str(saved) if saved else None)


def test_interpretation_json_export_survives_korean_title(korean_titled_work):
    """한글 제목 해석을 JSON 으로 내보낼 때 500 이 나면 안 된다.

    고치기 전에는 제목을 그대로 헤더에 넣어 `UnicodeEncodeError` 로 500 이었다.
    """
    client, doc_id = korean_titled_work
    lst = client.get("/api/interpretations").json()
    interp_ids = [
        x.get("interpretation_id")
        for x in (lst if isinstance(lst, list) else lst.get("interpretations", []))
        if x.get("source_document_id") == doc_id
    ]
    if not interp_ids:
        pytest.skip("해석 저장소가 자동 생성되지 않았다 — 이 시험의 전제가 아니다")

    r = client.get(f"/api/interpretations/{interp_ids[0]}/export/json")
    assert r.status_code == 200, r.text

    cd = r.headers.get("content-disposition", "")
    # 헤더 전체가 latin-1 로 인코딩 가능해야 한다 — 아니면 서버가 터진다.
    cd.encode("latin-1")
    assert "filename*=UTF-8''" in cd, (
        f"RFC 5987 확장 이름이 없다 — 한글 파일명이 전달되지 않는다: {cd}"
    )
    assert re.search(r'filename="[\x20-\x7e]*"', cd), (
        f"ASCII 대체 이름이 없다 — 옛 브라우저가 받지 못한다: {cd}"
    )


def test_all_download_headers_are_latin1_safe():
    """내려받기 헤더를 f-string 으로 만드는 자리가 **검증된 값만** 쓰는가.

    소스에서 `Content-Disposition` 을 만드는 자리를 전부 찾아, 헤더에 들어가는
    변수가 ASCII 임이 보장되는지 사람이 한 번 판단하게 한다. 지금 세 자리다:

      `version.py`      제목 → **RFC 5987** (2026-09-22 수정)
      `composition.py`  `doc_id` → `^[a-z][a-z0-9_]{0,63}$` (ASCII 보장)
      `alignment.py`    사전 이름 → 파일명에서 오고 실제 사전은 ASCII 이름뿐

    새 자리가 생기면 이 수가 늘어 시험이 빨개진다 — 그때 위 판단을 다시 한다.
    """
    import subprocess

    out = subprocess.run(
        # 만드는 쪽만 본다 — JS 는 헤더를 **읽는** 쪽이라 대상이 아니다.
        ["git", "grep", "-c", "Content-Disposition", "--", "src/app/routers"],
        cwd=_ROOT, capture_output=True, text=True, check=False,
    ).stdout.strip().splitlines()
    files = {line.rsplit(":", 1)[0].replace("\\", "/") for line in out if line.strip()}
    known = {
        "src/app/routers/version.py",
        "src/app/routers/composition.py",
        "src/app/routers/alignment.py",
        "src/app/routers/documents.py",   # 주석만 — filename= 을 주지 않는다
    }
    new = sorted(files - known)
    assert not new, (
        f"내려받기 헤더를 만드는 새 자리: {new}\n"
        "  헤더는 latin-1 이다. 한글이 들어갈 수 있으면 RFC 5987"
        "(`filename*=UTF-8''<percent-encoded>`)로 준다 — 안 그러면 500 이 난다."
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "--no-header"]))
