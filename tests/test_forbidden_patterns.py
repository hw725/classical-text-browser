# -*- coding: utf-8 -*-
"""CLAUDE.md 「파일 다루기」 표의 금지 패턴이 **늘지 않는가** — 산문 규칙을 시험으로.

## 왜 이 시험이 필요한가

CLAUDE.md·`docs/maintenance.md` 1장의 규칙은 산문으로만 있었다. 그래서 규칙을 적은
뒤에도 그 규칙을 어긴 코드가 남아 있었다(2026-10-01 감사 — `write_text(json.dumps)`
셋, 허용 밖 `get_pixmap` 하나). 아무 검사도 그 자리를 부르지 않았기 때문이다.
`test_lint_does_not_grow.py`와 같은 **래칫**이다: 지금 있는 위반은 기준선에 적고,
**새 위반이 생기면 빨간불**, 갚았는데 기준선을 안 내리면 그것도 빨간불.

## 무엇을 보나 — 기계로 판정할 수 있는 넷만

키 — 규칙(CLAUDE.md 표) — AST 판정:

- `write_text_json` — JSON 저장은 `write_json_atomic()`
  — `.write_text(...)` 인자 안에 `.dumps(...)` 호출
- `get_pixmap` — 쪽 이미지는 `load_page_image_from_pdf`로
  — `.get_pixmap(...)` 호출, 허용 파일 밖
- `glob_pdf` — PDF는 `resolve_part_pdf()`로
  — `.glob("*.pdf")` 호출(대소문자 무시), 허용 파일 밖
- `localhost_url` — 로컬 서비스는 `127.0.0.1`
  — 문자열 상수 안의 `http(s)://localhost`(독스트링 제외)

**허용 파일**은 그 규칙이 가리키는 정본 함수가 사는 곳이다.

- `get_pixmap`: `src/ocr/image_utils.py`(`load_page_image_from_pdf` 본체),
  `src/export/text_layer_pdf.py`(D-068 — 쪽 이미지가 아니라 **방금 만든 산출물 PDF**를
  다시 렌더해 잉크 밀도를 잰다. 회전을 얹으면 오히려 틀린다).
- `glob_pdf`: `src/ocr/image_utils.py`(`resolve_part_pdf` — manifest를 못 읽을 때의
  이름 정렬 물러섬). `rglob`은 보지 않는다 — `cli/embed_folder.py`는 문헌이 아니라
  «PDF가 든 폴더»를 훑는 진입점이라 권(part) 개념이 없다.

**보지 않는 것**(판정이 산문 판단에 기대는 것): `fitz.open()`의 `with`,
`wrap_contents()` 선행, bbox 배율 2.0, innerHTML 이스케이프, `.bat` ASCII(이건
`test_doc_drift.py`가 본다). 이 넷 중 하나라도 기계 판정을 얻으면 여기에 키를 더한다.

## 기준선 — 2026-10-01, 고치지 않고 적었다(수정은 사람이 정한다)

- `write_text_json`: `src/text_import/common.py` 2(86·127행), `src/cli/read_book.py` 1(95행)
  — 감사가 짚은 셋. 그리고 **감사의 grep이 놓친 여섯**(호출이 여러 줄이라 한 줄 grep에
  `write_text`와 `json.dumps`가 함께 안 걸렸다): `src/app/routers/llm_ocr.py` 1(2000행,
  `ocr_results` 저장), `src/app/routers/version.py` 3(517·537·642행, 가져오기 manifest·
  의존 파일), `src/core/app_config.py` 1(60행, 앱 설정), `src/core/backup.py` 1(116행,
  백업 메타). AST로 처음 돌렸을 때 이 여섯이 빨간불로 나왔다.
- `get_pixmap`: `src/app/routers/llm_ocr.py` 1(396행 — `Matrix(2.0)`로 직접 렌더, 회전 미반영)

## 빨간불 확인 (maintenance §3 «빨간불만 증거», 2026-10-01)

기준선에서 `("get_pixmap", "src/app/routers/llm_ocr.py")` 한 줄을 지우고 돌리자
`test_forbidden_patterns_do_not_grow`가 «get_pixmap: src/app/routers/llm_ocr.py:
1건 (기준선 0)»으로 **실패했다**(1 failed, 13 passed). 원복하니 14 passed. 탐지기
자체는 `test_detector_catches_and_ignores`가 양·음 표본으로 지킨다 — `_find_violations`의
`write_text` 분기를 끄자 그 양성 표본 둘과 `test_baseline_is_not_stale`이 빨개졌다
(3 failed). 원복 후 초록.
"""

from __future__ import annotations

import ast
import re
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"

# 규칙이 가리키는 정본 함수가 사는 파일 — 여기서는 그 호출이 곧 구현이다.
_ALLOWED: dict[str, frozenset[str]] = {
    "get_pixmap": frozenset({"src/ocr/image_utils.py", "src/export/text_layer_pdf.py"}),
    "glob_pdf": frozenset({"src/ocr/image_utils.py"}),
}

# 기준선. **내려도 되고 올리면 안 된다.** (키, 파일) → 건수.
# 갚으면 그 줄을 지운다 — 안 지우면 test_baseline_is_not_stale 이 빨간불이다.
_BASELINE: dict[tuple[str, str], int] = {
    ("write_text_json", "src/text_import/common.py"): 2,
    ("write_text_json", "src/cli/read_book.py"): 1,
    # 아래 다섯 파일은 감사(grep 한 줄)가 놓친 것 — 호출이 여러 줄이라 AST가 처음 잡았다.
    ("write_text_json", "src/app/routers/llm_ocr.py"): 1,
    ("write_text_json", "src/app/routers/version.py"): 3,
    ("write_text_json", "src/core/app_config.py"): 1,
    ("write_text_json", "src/core/backup.py"): 1,
    ("get_pixmap", "src/app/routers/llm_ocr.py"): 1,
}

_LOCALHOST_URL = re.compile(r"(?i)\b(?:https?|wss?)://localhost\b")
_PDF_GLOB = re.compile(r"(?i)^\*\.pdf$")


def _docstring_ids(tree: ast.AST) -> set[int]:
    """식 문장으로 홀로 선 문자열(독스트링·설명 문자열)의 노드 id.

    독스트링은 «localhost로 띄우면 IPv6부터…» 같은 **설명**이지 호출이 아니다.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            ids.add(id(node.value))
    return ids


def _find_violations(source: str, rel: str) -> list[tuple[str, int]]:
    """한 파일의 소스에서 (키, 행) 목록을 돌려준다.

    입력: source — 파이썬 소스, rel — `src/...` POSIX 상대 경로(허용 파일 판정용).
    출력: 위반 (키, 행번호) 목록.
    """
    tree = ast.parse(source)
    skip = _docstring_ids(tree)
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr == "write_text":
                # 인자 어디에든 .dumps(...) 가 있으면 «JSON을 write_text로»다.
                for arg in [*node.args, *(k.value for k in node.keywords)]:
                    if any(
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "dumps"
                        for sub in ast.walk(arg)
                    ):
                        found.append(("write_text_json", node.lineno))
                        break
            elif attr == "get_pixmap" and rel not in _ALLOWED["get_pixmap"]:
                found.append(("get_pixmap", node.lineno))
            elif (
                attr == "glob"
                and rel not in _ALLOWED["glob_pdf"]
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and _PDF_GLOB.match(node.args[0].value)
            ):
                found.append(("glob_pdf", node.lineno))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skip
            and _LOCALHOST_URL.search(node.value)
        ):
            found.append(("localhost_url", node.lineno))
    return found


@lru_cache(maxsize=1)
def _scan() -> tuple[Counter, dict[tuple[str, str], list[int]]]:
    """src/ 전체를 훑어 (키, 파일)별 건수와 행 목록."""
    counts: Counter = Counter()
    lines: dict[tuple[str, str], list[int]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(_ROOT).as_posix()
        src = path.read_text(encoding="utf-8")
        for key, lineno in _find_violations(src, rel):
            counts[(key, rel)] += 1
            lines.setdefault((key, rel), []).append(lineno)
    return counts, lines


def test_forbidden_patterns_do_not_grow():
    """(키, 파일)마다 위반이 기준선을 넘지 않아야 한다 — 넘으면 이번 변경이 만든 것."""
    counts, lines = _scan()
    grown = [
        f"{key}: {rel}:{','.join(map(str, lines[(key, rel)]))} "
        f"{n}건 (기준선 {_BASELINE.get((key, rel), 0)})"
        for (key, rel), n in sorted(counts.items())
        if n > _BASELINE.get((key, rel), 0)
    ]
    assert not grown, (
        "CLAUDE.md 「파일 다루기」 금지 패턴이 늘었다:\n  "
        + "\n  ".join(grown)
        + "\n\n  write_text_json → core.document.write_json_atomic()"
        "\n  get_pixmap      → ocr.image_utils.load_page_image_from_pdf()"
        "\n  glob_pdf        → ocr.image_utils.resolve_part_pdf()"
        "\n  localhost_url   → 127.0.0.1"
    )


def test_baseline_is_not_stale():
    """갚았으면 기준선도 내린다 — 안 내리면 그만큼 다시 쌓일 수 있다."""
    counts, _ = _scan()
    stale = [
        f"{key}: {rel} 기준선 {n} → 실제 {counts.get((key, rel), 0)}"
        for (key, rel), n in sorted(_BASELINE.items())
        if counts.get((key, rel), 0) < n
    ]
    assert not stale, "기준선이 실제보다 높다 — 고친 만큼 내린다:\n  " + "\n  ".join(stale)


_CASES = [
    # (소스, 파일, 기대 키 목록)
    ('p.write_text(json.dumps(d), encoding="utf-8")', "src/x.py", ["write_text_json"]),
    ('p.write_text(text=json.dumps(d))', "src/x.py", ["write_text_json"]),
    ('p.write_text("plain")', "src/x.py", []),
    ("pix = page.get_pixmap()", "src/x.py", ["get_pixmap"]),
    ("pix = page.get_pixmap()", "src/ocr/image_utils.py", []),
    ('pdf = d.glob("*.PDF")[0]', "src/x.py", ["glob_pdf"]),
    ('pdfs = d.rglob("*.pdf")', "src/x.py", []),
    ('pdfs = d.glob("*.pdf")', "src/ocr/image_utils.py", []),
    ('URL = "http://localhost:11434/api"', "src/x.py", ["localhost_url"]),
    ('u = f"https://localhost:{port}/x"', "src/x.py", ["localhost_url"]),
    ('u = url.replace("://localhost:", "://127.0.0.1:")', "src/x.py", []),
    ('def f():\n    """http://localhost:1 로 띄우면 느리다."""\n', "src/x.py", []),
]


@pytest.mark.parametrize("source,rel,expected", _CASES)
def test_detector_catches_and_ignores(source, rel, expected):
    """탐지기가 잡을 것은 잡고 정본·설명은 놓아 준다 — 탐지기 자체의 빨간불 장치."""
    assert [k for k, _ in _find_violations(source, rel)] == expected


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "--no-header"]))
