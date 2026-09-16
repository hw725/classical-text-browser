"""브라우저 없이 화면 JS의 순수 함수를 node로 돌리는 얇은 도구.

왜 있는가:
    `src/app/static/js/*.js`는 빌드 도구 없는 브라우저 스크립트라 import할 수 없다. 함수 이름으로
    본문을 잘라 내어(파일이 prettier 형식이라 최상위 함수는 `^function name(` … `^}`) 스텁과
    함께 node에 먹인다. DOM 전체를 흉내 내지 않고, 시험이 필요한 만큼만 `document`·`fetch`를 준다.

    node가 없으면 시험을 건너뛴다(`require_node`).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

# CTB_JS_DIR — 다른 판의 JS(예: 수정 전 커밋의 복사본)로 같은 시험을 돌려
# «수정 전 실패»를 확인할 때.
STATIC_JS = Path(
    os.environ.get("CTB_JS_DIR") or Path(__file__).parent.parent / "src" / "app" / "static" / "js"
)


def require_node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node가 없어 화면 JS 시험을 건너뛴다")
    return node


# 거의 모든 함수가 기대는 작은 도우미 — 있으면 늘 함께 붙인다(없는 파일이면 건너뛴다).
ALWAYS_INCLUDE = ["_annChars", "_annCpLength", "_annCpIndex", "_annUtf16Index", "_escHtml"]


def extract_js(source: str, names: list[str]) -> str:
    """최상위 `function name(`·`async function name(`·`const name = …` 정의를 이름대로 잘라 붙인다.

    파일이 prettier 형식이라 최상위 함수는 `^}` 줄에서 끝난다.
    """
    out = []
    names = list(names) + [
        n
        for n in ALWAYS_INCLUDE
        if n not in names and re.search(rf"^function {re.escape(n)}\(", source, re.MULTILINE)
    ]
    for name in names:
        pat = re.compile(
            rf"^(?:async )?function {re.escape(name)}\(.*?^\}}$", re.MULTILINE | re.DOTALL
        )
        m = pat.search(source)
        if m is None:
            pat = re.compile(
                rf"^(?:const|let|var) {re.escape(name)} = .*?^\}};?$", re.MULTILINE | re.DOTALL
            )
            m = pat.search(source)
        if m is None:  # 짧은 상수(정규식·숫자 등) — 줄 끝 `;`까지
            pat = re.compile(
                rf"^(?:const|let|var) {re.escape(name)} =.*?;[ \t]*$", re.MULTILINE | re.DOTALL
            )
            m = pat.search(source)
        if m is None:
            raise AssertionError(f"JS 정의를 찾지 못했다: {name}")
        out.append(m.group(0))
    return "\n\n".join(out)


def run_js(tmp_path: Path, js_file: str, names: list[str], setup: str, body: str) -> dict:
    """setup(스텁) + 잘라 낸 함수들 + body(async, 결과를 JSON으로 console.log)를 node로 돌린다."""
    node = require_node()
    source = (STATIC_JS / js_file).read_text(encoding="utf-8")
    script = "\n".join(
        [
            setup,
            extract_js(source, names),
            "(async () => {",
            body,
            "})().catch((e) => {"
            " console.log(JSON.stringify({__error: String((e && e.stack) || e)})); });",
        ]
    )
    path = tmp_path / "harness.js"
    path.write_text(script, encoding="utf-8")
    proc = subprocess.run(
        [node, str(path)], capture_output=True, text=True, encoding="utf-8", timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    last = [ln for ln in proc.stdout.splitlines() if ln.strip()][-1]
    result = json.loads(last)
    assert "__error" not in result, result["__error"]
    return result
