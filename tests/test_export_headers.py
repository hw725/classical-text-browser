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
    """내려받기 헤더를 만드는 **자리마다** 검증된 값만 쓰는가.

    소스에서 `Content-Disposition` 을 만드는 자리를 전부 찾아, 헤더에 들어가는
    변수가 ASCII 임이 보장되는지 사람이 한 번 판단하게 한다. 지금 이렇다:

      `version.py`      제목 → **RFC 5987** (2026-09-22 수정)
      `composition.py`  `doc_id` → `^[a-z][a-z0-9_]{0,63}$` (ASCII 보장)
      `alignment.py`    사전 이름 → 파일명에서 오고 실제 사전은 ASCII 이름뿐

    **파일 집합이 아니라 자리 수로 센다.** 집합으로 세면 이미 허용된 파일 **안에**
    한글을 그대로 넣는 새 헤더를 더해도 집합이 그대로라 통과한다 —
    릴리스 노트가 약속한 「새 내보내기가 생기면 걸립니다」보다 좁았다
    (Codex 지적 2026-09-22).
    """
    import subprocess

    out = subprocess.run(
        # 만드는 쪽만 본다 — JS 는 헤더를 **읽는** 쪽이라 대상이 아니다.
        # 사전 키 꼴로 찾는다: docstring·주석의 언급은 헤더를 만들지 않는데,
        # 그것까지 세면 주석 한 줄에도 시험이 빨개지고 다음 사람은 원인을 안 보고
        # 숫자만 올린다.
        ["git", "grep", "-c", '"Content-Disposition":', "--", "src/app/routers"],
        cwd=_ROOT, capture_output=True, text=True, check=False,
    ).stdout.strip().splitlines()

    counts: dict[str, int] = {}
    for line in out:
        if not line.strip():
            continue
        path, n = line.rsplit(":", 1)
        counts[path.replace("\\", "/")] = int(n)

    # 자리 **수**까지 못박는다. 늘면 그 자리를 사람이 본다.
    known = {
        "src/app/routers/version.py": 1,
        "src/app/routers/composition.py": 1,
        "src/app/routers/alignment.py": 1,
    }
    grown = sorted(
        "%s: %d곳 (알던 것 %d곳)" % (p, n, known.get(p, 0))
        for p, n in counts.items()
        if n != known.get(p, 0)
    )
    assert not grown, (
        "내려받기 헤더를 만드는 자리가 달라졌다:\n  " + "\n  ".join(grown) + "\n\n"
        "  헤더는 latin-1 이다. 한글이 들어갈 수 있으면 RFC 5987"
        "(`filename*=UTF-8''<percent-encoded>`)로 준다 — 안 그러면 500 이 난다.\n"
        "  그리고 **화면이 filename*= 를 읽는지**까지 본다 — 서버만 고치면\n"
        "  사람이 받는 이름은 그대로 비어 있다."
    )


def test_screen_turns_rfc5987_header_into_a_korean_filename():
    """화면이 그 헤더로 만들어 내는 **파일 이름**에 한글 제목이 들어가는가.

    위 시험들은 서버가 보내는 헤더만 본다. 서버를 RFC 5987 로 고쳐도 화면이
    `filename=` 만 읽으면 사람이 받는 이름은 `interpretation_….json` 그대로다 —
    500 은 없어졌는데 약속한 것은 안 돌아온다(Codex 지적 2026-09-22).

    **파싱 조각을 `workspace.js` 에서 떼어 node 로 실제 돌린다.** 베껴 적으면
    화면이 망가져도 이 시험은 자기 사본을 보고 초록으로 남는다.
    """
    import json
    import shutil
    import subprocess
    import tempfile
    import urllib.parse

    if shutil.which("node") is None:
        pytest.skip("node 가 없다 — 화면 JS 를 돌릴 수 없다")

    title, date = "천진담초", "20260922"
    header = (
        f'attachment; filename="interpretation_{date}.json"; '
        "filename*=UTF-8''" + urllib.parse.quote(f"{title}_{date}.json", safe="")
    )
    header.encode("latin-1")  # 헤더는 latin-1 이다 — 여기서 터지면 서버가 500 이다

    src = (_ROOT / "src/app/static/js/workspace.js").read_text(encoding="utf-8")
    start = src.index("const ext = disposition.match(/filename")
    end = src.index("// Blob → 다운로드 트리거", start)
    snippet = src[start:end].strip()

    code = (
        "const disposition = process.argv[2];\n"
        'const interpId = "unyang_interp";\n'
        "let filename = `${interpId}.json`;\n"
        + snippet
        + "\nconsole.log(JSON.stringify({ filename }));\n"
    )
    with tempfile.NamedTemporaryFile(
        "w", suffix=".js", delete=False, encoding="utf-8", newline=""
    ) as f:
        f.write(code)
        path = f.name

    r = subprocess.run(
        ["node", path, header],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    assert r.returncode == 0, f"화면 파싱 조각이 돌지 않는다: {r.stderr[:300]}"
    got = json.loads(r.stdout.strip())["filename"]
    assert got == f"{title}_{date}.json", (
        f"사람이 받는 이름에 한글 제목이 없다: {got!r}\n"
        "  화면이 filename*=UTF-8''… 를 읽어 percent-decode 해야 한다."
    )

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "--no-header"]))
