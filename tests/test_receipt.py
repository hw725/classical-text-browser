# -*- coding: utf-8 -*-
"""검증 영수증(`scripts/receipt.py`)이 «시험이 돌지 않은 실행»을 통과로 적지 않는가.

Codex 교차 리뷰(2026-10-01)가 짚은 자리: 예전 판정은 `종료 코드 == 0`뿐이라, 부모 셸의
`PYTEST_ADDOPTS=--collect-only`나 전부 skipped인 실행도 «통과» 영수증이 됐다. 영수증은
완료 보고의 증거이므로(AGENTS.md «에이전트 작업 계약» 2항) 그 거짓 초록을 여기서 막는다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "receipt.py"


@pytest.fixture(scope="module")
def receipt():
    spec = importlib.util.spec_from_file_location("ctb_receipt", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    "code,counts,ok",
    [
        (0, {"passed": 12}, True),
        (0, {}, False),  # --collect-only: 요약에 passed가 없다
        (0, {"skipped": 5}, False),  # 전부 건너뜀
        (0, {"deselected": 9}, False),
        (1, {"passed": 3, "failed": 1}, False),
        ("timeout", {"passed": 3}, False),
    ],
)
def test_pytest_step_needs_passed(receipt, code, counts, ok):
    """입력: pytest 단계의 종료 코드·건수. 출력: passed ≥ 1이고 실패 없을 때만 통과."""
    assert receipt._step_ok("fast_tests", code, counts) is ok


def test_non_pytest_step_uses_exit_code(receipt):
    """ruff·doc_drift는 건수가 없다 — 종료 코드만 본다."""
    assert receipt._step_ok("ruff", 0, None) is True
    assert receipt._step_ok("doc_drift", 1, None) is False


def test_collect_only_summary_has_no_passed(receipt):
    """실제 `--collect-only -q` 요약 줄을 건수로 바꾸면 passed가 없다 — 위 판정이 기대는 전제."""
    counts = receipt._pytest_counts("tests/test_x.py::test_a\n\n15 tests collected in 0.4s\n")
    assert "passed" not in counts
    assert receipt._step_ok("forbidden_patterns", 0, counts) is False
