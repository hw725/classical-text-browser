# -*- coding: utf-8 -*-
"""AGENTS.md 「파일 다루기」 표의 금지 패턴이 **하나도 없는가** — 산문 규칙을 시험으로.

## 왜 이 시험이 필요한가

CLAUDE.md·`docs/maintenance.md` 1장의 규칙은 산문으로만 있었다. 그래서 규칙을 적은
뒤에도 그 규칙을 어긴 코드가 남아 있었다(2026-10-01 감사 — `write_text(json.dumps)`
셋, 허용 밖 `get_pixmap` 하나). 아무 검사도 그 자리를 부르지 않았기 때문이다.
처음에는 `test_lint_does_not_grow.py`와 같은 **래칫**(기준선 10건)으로 들였고, 같은 날
10건을 모두 갚아 **기준선을 비웠다** — 이제 위반이 하나라도 생기면 빨간불이고,
기준선에 예외를 다시 적는 것도 `test_baseline_stays_empty`가 막는다. 정말 예외가
필요하면 기준선이 아니라 `_ALLOWED`(정본 함수가 사는 파일)에 이유와 함께 적는다.

## 무엇을 보나 — 기계로 판정할 수 있는 다섯만

키 — 규칙(CLAUDE.md 표) — AST 판정:

- `write_text_json` — JSON 저장은 `write_json_atomic()`
  — `.write_text(...)` 인자 안에 `dumps(...)` 호출, 또는 같은 함수에서 `dumps` 결과를
  대입받은 이름을 넘김(`text = json.dumps(d); p.write_text(text)`)
- `json_dump_open` — 같은 규칙. `with open(p, "w") as f` / `p.open("w")`로 연 핸들에
  `json.dump(d, f)`. `os.fdopen(mkstemp…)` → `os.replace`(원자적 쓰기의 다른 꼴)는 보지 않는다
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
- `json_dump_open`: `src/ocr/ndlocr/ndl_parser.py`(NDL 원본을 그대로 들여온 파일,
  `json_to_file`은 부르는 곳이 없다).

**탐지 범위의 한계**(«0건»은 이 꼴들이 없다는 뜻이지 규칙 준수의 증명이 아니다):
다른 함수에서 만든 문자열을 넘기는 경우, `open` 핸들을 변수로 돌려 쓰는 경우,
변수에 담은 glob 패턴은 놓친다. `src/`만 훑는다(scripts·tests는 서고 파일을 쓰지 않는다).

**보지 않는 것**(판정이 산문 판단에 기대는 것): `fitz.open()`의 `with`,
`wrap_contents()` 선행, bbox 배율 2.0, innerHTML 이스케이프, `.bat` ASCII(이건
`test_doc_drift.py`가 본다). 이 넷 중 하나라도 기계 판정을 얻으면 여기에 키를 더한다.

## 갚은 기록 — 2026-10-01 기준선 10건 → 0건

- `write_text_json` 9건 → `core.document.write_json_atomic()`: `src/text_import/common.py` 2
  (표점·서식 사이드카), `src/cli/read_book.py` 1(계획 초안), `src/app/routers/llm_ocr.py` 1
  (`ocr_results` 저장), `src/app/routers/version.py` 3(가져오기 manifest·의존 파일·서고
  manifest), `src/core/app_config.py` 1(앱 설정), `src/core/backup.py` 1(백업 메타).
  셋은 감사의 grep이 짚었고 여섯은 놓쳤다(호출이 여러 줄이라 한 줄 grep에 `write_text`와
  `json.dumps`가 함께 안 걸렸다 — AST가 처음 잡았다). 형식은 `indent=2`·`ensure_ascii=False`
  그대로이고, 끝 줄바꿈이 없던 넷에 줄바꿈 하나가 붙고 Windows에서 CRLF였던 것이 LF가 된다.
  읽는 쪽은 모두 `json.loads`다.
- `get_pixmap` 1건(`llm_ocr._load_page_image`) → `ocr.image_utils.load_page_image_from_pdf(
  scale=2.0)`. 예전 구현도 `page_rotation`을 얹고 있었으므로 결과는 같아야 하고,
  `tests/test_llm_ocr_page_image.py`가 예전 구현을 떠 두고 권 회전 90 + 범위 회전 180·270·0
  쪽에서 **최종 JPEG 바이트**를 견주고, 검은 네모가 시계 방향 회전 뒤 있어야 할 자리를
  따로 잰다(둘이 같은 `rotate_page_image`를 쓰므로 바이트 비교만으로는 방향을 못 지킨다).
- 같은 날 Codex 교차 리뷰가 탐지기의 빈틈(두 줄 꼴·`from json import dumps`·
  `open("w")`+`json.dump`)을 짚었다. 넓히자 7건이 더 나와 함께 갚았다:
  `src/core/annotation_dict_io.py`·`annotation_dict_match.py`·`annotation_types.py`·
  `citation_mark.py` 각 1, `src/core/interpretation.py` 2(해석 저장소 파일 쓰기),
  `src/ocr/pipeline.py` 1(L2 OCR 결과 저장, `json_dump_open`).

## 빨간불 확인 (maintenance §3 «빨간불만 증거»)

래칫 시절(2026-10-01): 기준선에서 `("get_pixmap", "src/app/routers/llm_ocr.py")` 한 줄을
지우자 «get_pixmap: src/app/routers/llm_ocr.py: 1건 (기준선 0)»으로 **실패했다**. 탐지기
자체는 `test_detector_catches_and_ignores`가 양·음 표본으로 지킨다 — `_find_violations`의
`write_text` 분기를 끄자 그 양성 표본 둘이 빨개졌다.
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
    # NDL 원본(CC BY 4.0)을 그대로 들여온 파일. json_to_file은 이 저장소에서 부르는 곳이 없고,
    # 상류 원문을 고치면 동기화 diff만 커진다 — 서고 파일을 쓰는 경로가 아니다.
    "json_dump_open": frozenset({"src/ocr/ndlocr/ndl_parser.py"}),
}

# 기준선. **비어 있어야 한다**(2026-10-01에 10건을 모두 갚았다). (키, 파일) → 건수.
# 여기에 줄을 더하면 test_baseline_stays_empty 가 빨간불이다 — 예외는 _ALLOWED 로.
_BASELINE: dict[tuple[str, str], int] = {}

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


def _call_name(node: ast.AST) -> str | None:
    """호출의 함수 이름 — `json.dumps`→"dumps", `from json import dumps`의 `dumps`→"dumps"."""
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        if isinstance(node.func, ast.Name):
            return node.func.id
    return None


def _has_dumps(expr: ast.AST) -> bool:
    return any(_call_name(sub) == "dumps" for sub in ast.walk(expr))


def _dumps_names(scope: ast.AST) -> set[str]:
    """이 범위(함수·모듈)에서 `.dumps(...)`가 든 식을 대입받은 이름들.

    `text = json.dumps(d) + "\\n"` 다음 줄의 `p.write_text(text)`를 잡기 위해서다 —
    한 줄 판정만 하면 이 두 줄짜리 꼴이 통째로 빠진다(Codex 교차 리뷰 2026-10-01, 실제로
    src/core 다섯 곳이 이 꼴이었다).
    """
    names: set[str] = set()
    for node in ast.walk(scope):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            if _has_dumps(node.value):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names.update(t.id for t in targets if isinstance(t, ast.Name))
    return names


def _open_for_write_names(scope: ast.AST) -> set[str]:
    """`with open(p, "w") as f` / `with p.open("w") as f`의 f — 0바이트로 자른 뒤 쓰는 핸들.

    `os.fdopen(fd, "w")`(mkstemp 임시 파일 → os.replace)은 원자적 쓰기의 한 꼴이라 넣지 않는다.
    """
    names: set[str] = set()
    for node in ast.walk(scope):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        for item in node.items:
            call = item.context_expr
            if _call_name(call) != "open" or not isinstance(item.optional_vars, ast.Name):
                continue
            consts = [*call.args, *(k.value for k in call.keywords if k.arg == "mode")]
            if any(
                isinstance(a, ast.Constant) and isinstance(a.value, str) and "w" in a.value
                and len(a.value) <= 3
                for a in consts
            ):
                names.add(item.optional_vars.id)
    return names


def _find_violations(source: str, rel: str) -> list[tuple[str, int]]:
    """한 파일의 소스에서 (키, 행) 목록을 돌려준다.

    입력: source — 파이썬 소스, rel — `src/...` POSIX 상대 경로(허용 파일 판정용).
    출력: 위반 (키, 행번호) 목록.
    """
    tree = ast.parse(source)
    skip = _docstring_ids(tree)
    found: list[tuple[str, int]] = []
    seen: set[int] = set()  # 중첩 함수가 바깥 범위와 겹쳐 두 번 세지 않게

    # 범위(모듈·함수)마다 «dumps를 담은 이름»과 «쓰기로 연 핸들»을 모아 판정한다.
    funcs = (ast.FunctionDef, ast.AsyncFunctionDef)
    scopes = [tree, *(n for n in ast.walk(tree) if isinstance(n, funcs))]
    for scope in scopes:
        dumped = _dumps_names(scope)
        handles = _open_for_write_names(scope)
        for node in ast.walk(scope):
            if not isinstance(node, ast.Call) or id(node) in seen:
                continue
            name = _call_name(node)
            args = [*node.args, *(k.value for k in node.keywords)]
            if name == "write_text" and isinstance(node.func, ast.Attribute):
                # 인자에 dumps 호출이 있거나 dumps 결과를 담은 이름을 넘기면
                # «JSON을 write_text로»다.
                if any(
                    _has_dumps(a) or (isinstance(a, ast.Name) and a.id in dumped) for a in args
                ):
                    seen.add(id(node))
                    found.append(("write_text_json", node.lineno))
            elif name == "dump" and rel not in _ALLOWED["json_dump_open"]:
                # json.dump(data, f) — f가 open(..., "w")로 연 핸들이면 write_text와 같은 위험.
                fp = node.args[1] if len(node.args) > 1 else next(
                    (k.value for k in node.keywords if k.arg == "fp"), None
                )
                if isinstance(fp, ast.Name) and fp.id in handles:
                    seen.add(id(node))
                    found.append(("json_dump_open", node.lineno))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr == "get_pixmap" and rel not in _ALLOWED["get_pixmap"]:
                found.append(("get_pixmap", node.lineno))
            elif attr == "glob" and rel not in _ALLOWED["glob_pdf"]:
                pattern = node.args[0] if node.args else next(
                    (k.value for k in node.keywords if k.arg == "pattern"), None
                )
                if (
                    isinstance(pattern, ast.Constant)
                    and isinstance(pattern.value, str)
                    and _PDF_GLOB.match(pattern.value)
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


def test_no_forbidden_patterns():
    """src/ 어디에도 금지 패턴이 없어야 한다(기준선이 비었으므로 위반 0을 뜻한다)."""
    counts, lines = _scan()
    grown = [
        f"{key}: {rel}:{','.join(map(str, lines[(key, rel)]))} "
        f"{n}건 (기준선 {_BASELINE.get((key, rel), 0)})"
        for (key, rel), n in sorted(counts.items())
        if n > _BASELINE.get((key, rel), 0)
    ]
    assert not grown, (
        "AGENTS.md 「파일 다루기」 금지 패턴이 있다:\n  "
        + "\n  ".join(grown)
        + "\n\n  write_text_json → core.document.write_json_atomic()"
        "\n  json_dump_open  → core.document.write_json_atomic()"
        "\n  get_pixmap      → ocr.image_utils.load_page_image_from_pdf()"
        "\n  glob_pdf        → ocr.image_utils.resolve_part_pdf()"
        "\n  localhost_url   → 127.0.0.1"
    )


def test_baseline_stays_empty():
    """기준선에 예외를 다시 적어 빨간불을 끄는 길을 막는다 — 위반 0이 계약이다."""
    assert not _BASELINE, (
        "금지 패턴 기준선은 비어 있어야 한다(2026-10-01 10건 상환). 위반은 고치고, "
        "정본 함수 자체라면 _ALLOWED 에 이유와 함께 적는다:\n  "
        + "\n  ".join(f"{k}: {r} {n}" for (k, r), n in sorted(_BASELINE.items()))
    )


def test_scanner_sees_src():
    """훑기가 실제로 파일을 읽는가 — src/ 경로가 바뀌어 0개를 훑으면 «위반 0»은 거짓 초록이다."""
    n = sum(1 for p in _SRC.rglob("*.py") if "__pycache__" not in p.parts)
    assert n > 100, f"src/ 아래 .py가 {n}개뿐 — 훑는 경로가 맞는지 본다"
    # 정본 함수 자리가 있어야 _ALLOWED 가 가리키는 대상이 실재한다
    for rels in _ALLOWED.values():
        for rel in rels:
            assert (_ROOT / rel).is_file(), f"_ALLOWED 의 {rel} 이 없다"


_CASES = [
    # (소스, 파일, 기대 키 목록)
    ('p.write_text(json.dumps(d), encoding="utf-8")', "src/x.py", ["write_text_json"]),
    ('p.write_text(text=json.dumps(d))', "src/x.py", ["write_text_json"]),
    ('p.write_text("plain")', "src/x.py", []),
    # 두 줄 꼴·이름 import 꼴(Codex 교차 리뷰 2026-10-01 — 그 전 탐지기는 셋 다 놓쳤다)
    (
        'def f(p, d):\n    s = json.dumps(d) + "\\n"\n    p.write_text(s)\n',
        "src/x.py",
        ["write_text_json"],
    ),
    ("from json import dumps\np.write_text(dumps(d))", "src/x.py", ["write_text_json"]),
    ('def f(p):\n    s = "plain"\n    p.write_text(s)\n', "src/x.py", []),
    (
        'def f(p, d):\n    with open(p, "w", encoding="utf-8") as fh:\n        json.dump(d, fh)\n',
        "src/x.py",
        ["json_dump_open"],
    ),
    (
        'def f(p, d):\n    with p.open("w") as fh:\n        json.dump(d, fp=fh)\n',
        "src/x.py",
        ["json_dump_open"],
    ),
    # mkstemp → os.fdopen → os.replace 는 원자적 쓰기의 한 꼴이다(core/alignment.py)
    (
        'def f(fd, d):\n    with os.fdopen(fd, "w") as fh:\n        json.dump(d, fh)\n',
        "src/x.py",
        [],
    ),
    ('def f(p, d):\n    with open(p) as fh:\n        x = json.load(fh)\n', "src/x.py", []),
    ('pdf = d.glob(pattern="*.pdf")', "src/x.py", ["glob_pdf"]),
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
