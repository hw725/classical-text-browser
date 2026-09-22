# -*- coding: utf-8 -*-
"""ruff 위반이 **늘지 않는가** — 자동 관문에 없어서 조용히 쌓였다.

## 왜 이 시험이 필요한가

`ruff`는 개발 의존성으로 선언돼 있고 `pyproject.toml`에 설정도 있지만,
**그것을 부르는 시험도 CI도 없었다.** 릴리스 절차(`docs/maintenance.md` 5장)
2단계에만 손으로 적혀 있어서, 릴리스를 자를 때 한 번 도는 것이 전부였다.

결과: v1.4.0 이후 86커밋 동안 **아무도 모르게 64건이 쌓였다**(2026-09-22 실측 —
`git archive` 로 두 트리를 풀어 각각 재었다. v1.4.0 태그 트리는 0건이다).

| 파일 | v1.4.0 | 2026-09-22 |
|---|---|---|
| `src/ocr/correction_pass.py` | 0 | 10 |
| `src/app/routers/llm_ocr.py` | 0 | 11 |
| `tests/test_correction_pass.py` | 0 | 17 |

전체 시험 1,571건은 그동안 계속 초록이었다 — **ruff를 아무도 안 불렀기 때문이다.**
「검사를 몇 번이나 돌렸는데 왜 이제 나오느냐」의 답이 이것이다: 그 검사들 중
어느 것도 ruff가 아니었다.

## 기준선은 비어 있다 — 2026-09-22 에 64건을 다 갚았다

처음에는 기준선을 박아 «늘어나는 것만» 막을 셈이었다. 같은 날 다 고쳐서
지금은 비어 있고, 빈 기준선은 **어느 파일이든 0** 을 뜻한다.

고친 방법은 한 가지가 아니었다. 무엇이 긴 줄인지 보고 갈랐다:

| 무엇 | 어떻게 |
|---|---|
| 코드 줄·import 정렬 | `ruff format`, `--fix` |
| 주석·docstring | 폭에 맞춰 접는다 |
| 코드 안의 긴 문자열 | 암시적 이어붙이기로 나눈다(값은 그대로) |
| **시험이 비교하는 문자열** | 손대지 않고 **그 문자열 하나만** 면제한다 |

마지막 줄이 요점이다. `tests/test_structure_jev.py` 의 긴 줄은 화면 JS 에 넘기는
제안 목록을 그대로 적은 것이라 **줄을 바꾸면 검사 대상 자체가 바뀐다**.

**면제는 좁게 건다.** 처음에는 파일 머리에 `# ruff: noqa: E501` 을 두었다
(`test_annotation_editor_js.py`·`test_entity_manager_js.py` 의 선례를 따라). 그러나
그 파일은 코드도 사는 528줄짜리라, 파일 전체를 끄면 **파이썬 코드 줄까지 영영 검사 밖**에
놓인다. ruff 는 여러 줄 문자열의 진단을 **닫는 따옴표 줄로 옮겨** 보므로, 닫는 줄에
붙이면 그 문자열 하나만 면제된다(교차검토 지적, 실측 확인). 지금은 그렇게 되어 있다.

접는 일에도 함정이 둘 있었다(둘 다 2026-09-22 실측):

* ruff 는 글자 수가 아니라 **표시 폭**으로 잰다. 한자·한글은 2칸이다.
  `len()` 으로 세면 66자짜리 줄을 「이미 짧다」로 보고 한 줄도 접지 못한다.
* **여러 줄 문자열 «안»의 줄에는 `# noqa` 를 붙일 수 없다.** 그 자리에서는 주석이
  아니라 문자열의 내용이 되어, 검사는 그대로 걸리고 문자열만 더러워진다.
  그렇다고 파일 전체를 끄는 것은 과하다 — **닫는 따옴표 줄**에 붙이면 그 문자열만 면제된다.
"""

from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

# 기준선. **내려도 되고 올리면 안 된다.**
# 2026-09-22 에 64건을 다 갚아 비었다 — 비어 있으면 「어느 파일이든 0」이다.
# 갚지 못할 빚이 생기면 그 파일만 여기 적고, 갚는 대로 다시 뺀다.
_BASELINE: dict[str, int] = {}


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
