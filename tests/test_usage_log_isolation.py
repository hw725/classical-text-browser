"""테스트가 사용자 홈의 LLM 사용 기록에 쓰지 않는지 검사한다.

배경: 서고 없이 만든 `LlmConfig()`로 도는 라우터 테스트가 mock 응답을
`~/.classical-text-browser/llm_usage_log.jsonl`에 2,100여 행 쌓았다
(2026-09-10 확인). conftest.py가 `CTB_CONFIG_DIR`를 임시 폴더로 돌려 막는다.

세 가지를 본다:
  1. 서고 없는 추적기의 기록 자리가 `CTB_CONFIG_DIR` 아래다(홈이 아니다).
  2. 라우터의 «줄 수 세기»(`llm_ocr._usage_log_path`)가 추적기와 같은 파일을 본다.
  3. (세션 맨 뒤) 사용자 홈의 기록·설정 파일 크기가 세션 시작 때와 같다 —
     앞에서 돈 테스트 전부가 검사 대상이다. conftest가 이 테스트를 마지막으로
     보낸다.
"""

import os
import sys
from pathlib import Path

import pytest

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from llm.config import LlmConfig  # noqa: E402
from llm.providers.base import LlmResponse  # noqa: E402
from llm.usage_tracker import UsageTracker, default_usage_log_path  # noqa: E402


def _size(path: Path) -> int:
    return path.stat().st_size if path.exists() else -1


def test_conftest_redirected_config_dir(home_config_dir):
    """conftest가 앱 설정 폴더를 임시 폴더로 돌렸고, 그곳은 사용자 홈이 아니다."""
    config_dir = os.environ.get("CTB_CONFIG_DIR")
    assert config_dir, "conftest.pytest_sessionstart가 CTB_CONFIG_DIR를 세우지 않았다"
    assert Path(config_dir).resolve() != home_config_dir.resolve()


def test_tracker_without_library_writes_under_config_dir(home_config_dir):
    """서고 없는 LlmConfig()의 추적기는 CTB_CONFIG_DIR 아래에 쓴다 — 홈이 아니다."""
    home_log = home_config_dir / "llm_usage_log.jsonl"
    before = _size(home_log)

    tracker = UsageTracker(LlmConfig())
    tracker.log(
        LlmResponse(text="x", provider="isolation-test", model="mock-model", elapsed_sec=0.0),
        purpose="isolation_check",
    )

    path = tracker._get_log_path()
    assert path.parent.resolve() == Path(os.environ["CTB_CONFIG_DIR"]).resolve()
    assert path.exists()
    assert "isolation-test" in path.read_text(encoding="utf-8")

    assert _size(home_log) == before, "서고 없는 추적기가 사용자 홈 기록에 썼다"


def test_injected_log_path_wins(tmp_path):
    """log_path를 직접 주면 서고·환경 변수보다 우선한다."""
    target = tmp_path / "sub" / "usage.jsonl"
    tracker = UsageTracker(LlmConfig(library_root=tmp_path), log_path=target)
    tracker.log(LlmResponse(text="x", provider="p", model="m", elapsed_sec=0.0), purpose="t")
    assert target.exists()
    assert not (tmp_path / "llm_usage_log.jsonl").exists()


def test_default_path_rule(tmp_path, monkeypatch, home_config_dir):
    """규칙: 서고 > CTB_CONFIG_DIR > ~/.classical-text-browser."""
    assert default_usage_log_path(tmp_path) == tmp_path / "llm_usage_log.jsonl"

    monkeypatch.setenv("CTB_CONFIG_DIR", str(tmp_path / "cfg"))
    assert default_usage_log_path(None) == tmp_path / "cfg" / "llm_usage_log.jsonl"

    monkeypatch.delenv("CTB_CONFIG_DIR")
    assert default_usage_log_path(None) == home_config_dir / "llm_usage_log.jsonl"


def test_router_snapshot_reads_same_file_as_tracker():
    """llm_ocr의 줄 수 세기가 추적기와 같은 파일을 본다 (서고 없을 때)."""
    from app._state import get_library_path, set_library_path
    from app.routers.llm_ocr import _usage_log_path

    saved = get_library_path()
    set_library_path(None)
    try:
        assert _usage_log_path() == UsageTracker(LlmConfig())._get_log_path()
    finally:
        set_library_path(saved)


@pytest.mark.home_leak_check
def test_home_files_untouched_by_whole_session(home_config_dir, home_baseline_sizes):
    """세션 맨 뒤: 사용자 홈의 기록·설정 파일이 세션 시작 때와 같은 크기다.

    이 테스트만 따로 돌리면(-k) 앞 테스트가 없어 당연히 통과한다 — 뜻이 있는
    것은 전체 pytest에서다.
    """
    log = home_config_dir / "llm_usage_log.jsonl"
    assert _size(log) == home_baseline_sizes["usage_log"], (
        f"이 세션의 어떤 테스트가 사용자 홈 기록에 썼다: {log} "
        f"({home_baseline_sizes['usage_log']} → {_size(log)} bytes)"
    )

    cfg = home_config_dir / "config.json"
    assert _size(cfg) == home_baseline_sizes["config"], (
        f"이 세션의 어떤 테스트가 사용자 홈 설정에 썼다: {cfg} "
        f"({home_baseline_sizes['config']} → {_size(cfg)} bytes)"
    )
