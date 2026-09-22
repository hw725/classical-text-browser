# -*- coding: utf-8 -*-
"""ruff 위반이 **늘지 않는가** — 자동 관문에 없어서 조용히 쌓였다.

## 왜 이 시험이 필요한가

`ruff`는 개발 의존성으로 선언돼 있고 `pyproject.toml`에 설정도 있지만,
**그것을 부르는 시험도 CI도 없었다.** 릴리스 절차(`docs/maintenance.md` 5장)
2단계에만 손으로 적혀 있어서, 릴리스를 자를 때 한 번 도는 것이 전부였다.

결과: v1.4.0 이후 86커밋 동안 **아무도 모르게 66건이 쌓였다**(2026-09-22 실측).

| 파일 | v1.4.0 | 2026-09-22 |
|---|---|---|
| `src/ocr/correction_pass.py` | 0 | 10 |
| `src/app/routers/llm_ocr.py` | 0 | 11 |
| `tests/test_correction_pass.py` | 0 | 17 |

전체 시험 1,571건은 그동안 계속 초록이었다 — **ruff를 아무도 안 불렀기 때문이다.**
「검사를 몇 번이나 돌렸는데 왜 이제 나오느냐」의 답이 이것이다: 그 검사들 중
어느 것도 ruff가 아니었다.

## 왜 「전부 고쳐라」가 아니라 「늘리지 마라」인가

66건 중 **62건이 `E501`(줄 길이)이고 전부 긴 한글 주석·docstring 줄**이다.
포매터로도 안 고쳐진다(2026-09-22 실험: `ruff format` 뒤에도 그대로 남았다) —
한글 주석을 손으로 접어야 하고, 그 파일들은 다른 세션이 작업 중이다.
제품 동작에는 영향이 없다.

그래서 기준선을 박아 **새로 늘어나는 것만** 막는다.
(`test_cjk_text_contract.py`의 R1 기준선과 같은 방식이다.)
빚을 갚으면 이 표의 숫자를 내린다 — 내리는 것은 자유이고, 올리는 것만 막는다.
"""

from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

# 2026-09-22 기준선. **내려도 되고 올리면 안 된다.**
# 여기 없는 파일은 0이어야 한다 — 새 파일이 위반을 들고 들어오는 것을 막는다.
_BASELINE: dict[str, int] = {
    "tests/test_correction_pass.py": 17,
    "src/app/routers/llm_ocr.py": 11,
    "src/ocr/correction_pass.py": 10,
    "tests/test_lite_mode_api.py": 7,
    "tests/test_page_survey.py": 5,
    "tests/test_structure_jev.py": 3,
    "tests/test_full_page_block_rotation.py": 3,
    "src/ocr/full_page_block.py": 2,
    "tests/test_eval_cer.py": 1,
    "tests/test_codex_review.py": 1,
    "src/ocr/layout_staleness.py": 1,
    "src/llm/ollama_catalog.py": 1,
    "src/core/page_survey.py": 1,
    "src/app/server.py": 1,
}


def _counts() -> Counter:
    """파일별 ruff 위반 수. 경로는 POSIX 꼴로 맞춘다."""
    res = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "src/", "tests/",
         "--output-format", "concise"],
        cwd=_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    if "No module named" in (res.stderr or ""):
        pytest.skip("ruff 가 이 환경에 없다 — `uv sync --dev` 로 넣는다")
    out: Counter = Counter()
    for line in res.stdout.splitlines():
        # `src\app\server.py:12:1: E501 ...` — 상대 경로라 콜론이 위치 구분뿐이다.
        # (절대 경로면 드라이브 문자의 콜론에 걸려 파싱이 깨진다 — 2026-09-22 실측.)
        if ":" not in line:
            continue
        path = line.split(":", 1)[0].replace("\\", "/")
        if path.startswith(("src/", "tests/")):
            out[path] += 1
    return out


def test_ruff_violations_do_not_grow():
    """파일마다 ruff 위반이 기준선을 넘지 않아야 한다.

    넘으면 **이번 변경이 새로 만든 것**이다 — 그 파일만 보면 된다.
    기준선에 없는 파일은 0이어야 한다.
    """
    now = _counts()
    grown = [
        f"{p}: {n}건 (기준선 {_BASELINE.get(p, 0)})"
        for p, n in sorted(now.items())
        if n > _BASELINE.get(p, 0)
    ]
    assert not grown, (
        "ruff 위반이 늘었다 — 이번 변경이 새로 만든 것이다:\n  "
        + "\n  ".join(grown)
        + "\n\n  고치는 법: `uv run ruff check <파일> --fix` (import 정렬 등은 자동)."
        "\n  줄 길이(E501)는 손으로 줄인다."
    )


def test_baseline_is_not_stale():
    """빚을 갚았으면 기준선도 내린다 — 안 내리면 그만큼 다시 쌓일 수 있다."""
    now = _counts()
    stale = [
        f"{p}: 기준선 {n} → 실제 {now.get(p, 0)}"
        for p, n in sorted(_BASELINE.items())
        if now.get(p, 0) < n
    ]
    assert not stale, (
        "기준선이 실제보다 높다 — 고친 만큼 내린다:\n  " + "\n  ".join(stale)
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "--no-header"]))
