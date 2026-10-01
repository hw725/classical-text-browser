#!/usr/bin/env python3
"""검증 영수증 — 빠른 계층 시험·ruff·문서 드리프트·금지 패턴을 한 번에 돌려 기록한다.

사용법:
    uv run python scripts/receipt.py

하는 일 (순서대로, 앞 단계가 실패해도 뒤 단계는 돈다 — 영수증은 «전부»를 적어야 한다):
    1. fast_tests        — `pytest -m "not slow"` (빠른 계층, slow 마커는 pyproject에 등록)
    2. ruff              — `ruff check src/ tests/`
    3. doc_drift         — `scripts/check_doc_drift.py`
    4. forbidden_patterns — `tests/test_forbidden_patterns.py` (CLAUDE.md 금지 패턴, 위반 0)

결과: `logs/receipts/<UTC>_verify.json` 에 {git_rev, git_dirty, 단계별 exit·수·초}.
하나라도 실패하면 종료 코드 1.

왜 이것이 필요한가 — 에이전트의 «다 됐다»는 증거가 아니다. 완료 보고에는 이 파일의
경로와 요약을 붙인다(CLAUDE.md «에이전트 작업 계약»). `logs/`는 .gitignore 대상이라
영수증은 추적하지 않는다 — 대신 실행 끝에 경로를 찍으니 보고에 그 경로를 옮긴다.

사용자 설정을 건드리지 않는다: 모든 단계를 `CTB_CONFIG_DIR=<임시 폴더>`로 돌린다
(CLAUDE.md «검증용 서버는 CTB_CONFIG_DIR», 2026-09-10 설정 오염 사고). 외부 LLM은
부르지 않는다 — 빠른 계층 시험은 가짜 공급자만 쓴다.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# CJK Text Contract E3 — 한국어 Windows 콘솔(cp949)에서 «—»·«✓»를 print 하면 즉사한다.
from core.console import force_utf8_console

force_utf8_console()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# 한 단계가 멈춰도 영수증은 나와야 한다. pytest-timeout이 개별 시험을 끊지만,
# 수집 단계에서 멈추는 경우까지 막는 바깥 상한이다(빠른 계층 실측의 약 3배).
_STEP_TIMEOUT_SEC = 1200

_PYTEST_COUNT = re.compile(
    r"(\d+) (passed|failed|skipped|deselected|errors?|xfailed|xpassed)"
)


def _run(cmd: list[str], env: dict[str, str]) -> tuple[int | str, str, float]:
    """명령 하나를 돌려 (종료 코드, 출력, 초)를 돌려준다. 시간 초과면 코드 대신 "timeout"."""
    t0 = time.perf_counter()
    try:
        res = subprocess.run(
            cmd, cwd=ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=_STEP_TIMEOUT_SEC, check=False,
        )
        code: int | str = res.returncode
        out = (res.stdout or "") + (res.stderr or "")
    except subprocess.TimeoutExpired as e:
        code = "timeout"
        out = str(e.stdout or "")
    return code, out, round(time.perf_counter() - t0, 1)


def _pytest_counts(out: str) -> dict[str, int]:
    """pytest 요약 줄(마지막 «N passed, M deselected in Xs»)에서 건수를 꺼낸다."""
    summary = ""
    for line in reversed(out.splitlines()):
        if _PYTEST_COUNT.search(line):
            summary = line
            break
    counts: dict[str, int] = {}
    for n, kind in _PYTEST_COUNT.findall(summary):
        counts["errors" if kind.startswith("error") else kind] = int(n)
    return counts


def _ruff_count(out: str) -> int | None:
    if "All checks passed" in out:
        return 0
    m = re.search(r"Found (\d+) error", out)
    return int(m.group(1)) if m else None


def _drift_count(out: str) -> int | None:
    if "일치한다" in out:
        return 0
    m = re.search(r"어긋난 곳 (\d+)건", out)
    return int(m.group(1)) if m else None


def _git(*args: str) -> str:
    res = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    return res.stdout.strip()


def main() -> int:
    """네 단계를 돌리고 영수증을 쓴다. 출력: 종료 코드(전부 통과 0, 아니면 1)."""
    py = sys.executable
    steps: list[tuple[str, list[str]]] = [
        ("fast_tests", [py, "-m", "pytest", "-m", "not slow", "-q", "-p", "no:cacheprovider"]),
        ("ruff", [py, "-m", "ruff", "check", "src/", "tests/"]),
        ("doc_drift", [py, "scripts/check_doc_drift.py"]),
        ("forbidden_patterns", [
            py, "-m", "pytest", "tests/test_forbidden_patterns.py", "-q", "-p", "no:cacheprovider",
        ]),
    ]

    started = datetime.now(timezone.utc)
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="ctb-receipt-cfg-") as cfg:
        env = dict(os.environ, CTB_CONFIG_DIR=cfg, PYTHONUTF8="1")
        for name, cmd in steps:
            print(f"[receipt] {name} …", flush=True)
            code, out, sec = _run(cmd, env)
            entry: dict = {"step": name, "exit": code, "seconds": sec}
            if name in ("fast_tests", "forbidden_patterns"):
                entry["counts"] = _pytest_counts(out)
            elif name == "ruff":
                entry["violations"] = _ruff_count(out)
            elif name == "doc_drift":
                entry["mismatches"] = _drift_count(out)
            entry["ok"] = code == 0
            if not entry["ok"]:
                # 실패 원인을 영수증만 보고 짚을 수 있게 출력 꼬리를 남긴다.
                entry["tail"] = out.splitlines()[-30:]
            results.append(entry)
            # `or`로 이으면 0건(ruff 위반 0)이 거짓으로 읽혀 None이 찍힌다 — 키로 고른다.
            summary = next(
                (entry[k] for k in ("counts", "violations", "mismatches") if k in entry), None
            )
            print(f"[receipt] {name}: exit={code} {sec}s {summary}", flush=True)

    ok = all(r["ok"] for r in results)
    receipt = {
        "kind": "verify",
        "started_utc": started.isoformat(timespec="seconds"),
        "git_rev": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        # 커밋 안 된 변경이 있으면 영수증이 가리키는 rev와 실제 검사 대상이 다르다.
        "git_dirty": bool(_git("status", "--porcelain")),
        "ok": ok,
        "steps": results,
    }

    from core.document import write_json_atomic

    out_dir = ROOT / "logs" / "receipts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{started.strftime('%Y%m%dT%H%M%SZ')}_verify.json"
    write_json_atomic(out_path, receipt)
    print(f"[receipt] {'통과' if ok else '실패'} — {out_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
