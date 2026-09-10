"""pytest 전역 설정 — 테스트가 사용자의 홈 폴더에 쓰지 않게 격리한다.

왜 있는가:
    서고 없이 만든 `LlmConfig()`로 도는 라우터 테스트는 `UsageTracker`가
    «서고가 없으면 앱 설정 폴더»로 내려가, mock 응답(provider `second`·`ok`·
    `vision`, model `mock-model`)을 사용자의
    `~/.classical-text-browser/llm_usage_log.jsonl`에 쌓았다(2026-09-10 확인,
    2,202행 중 2,127행이 시험 행). 최근 서고 목록(config.json)도 같은 폴더다.

어떻게:
    앱 설정 폴더 스위치 `CTB_CONFIG_DIR`(core/app_config.py, 검증 서버용으로
    이미 있던 것)를 세션 시작 때 pytest 임시 폴더로 돌린다. 테스트 모듈이
    src를 import하기 **전**(collection 전)에 환경 변수가 서야 하므로
    `pytest_sessionstart`에서 한다. 자식 프로세스(워커·CLI 시험)는 환경을
    물려받으므로 함께 격리된다.

새는지 검사:
    세션 시작 때 사용자 홈 기록의 크기를 재어 두고, `test_usage_log_isolation.py`
    의 마지막 테스트가 세션 끝에서 같은지 본다. 그 테스트는 아래
    `pytest_collection_modifyitems`가 실행 순서의 맨 뒤로 보낸다 — 앞에서 돈
    테스트 전부가 검사 대상이 되도록.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# 세션 시작 때 잰 «사용자 홈 기록 크기». -1이면 파일이 없었다.
HOME_USAGE_LOG_SIZE_KEY = pytest.StashKey[int]()
# 세션 시작 때 잰 «사용자 홈 config.json 크기». -1이면 파일이 없었다.
HOME_CONFIG_SIZE_KEY = pytest.StashKey[int]()

# 실행 순서를 맨 뒤로 보낼 마커 이름
LEAK_CHECK_MARK = "home_leak_check"


def real_home_config_dir() -> Path:
    """사용자의 진짜 앱 설정 폴더. 환경 변수와 무관하게 홈 기준이다.

    격리 스위치가 가리키는 곳이 아니라, 격리가 **지켜야 할** 곳이다.
    """
    return Path.home() / ".classical-text-browser"


def _size_or_missing(path: Path) -> int:
    return path.stat().st_size if path.exists() else -1


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{LEAK_CHECK_MARK}: 세션 맨 뒤에서 돌며 사용자 홈에 새 기록이 없는지 본다",
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    """src를 import하기 전에 앱 설정 폴더를 임시 폴더로 돌리고, 홈 파일 크기를 재 둔다."""
    home_dir = real_home_config_dir()
    session.config.stash[HOME_USAGE_LOG_SIZE_KEY] = _size_or_missing(
        home_dir / "llm_usage_log.jsonl"
    )
    session.config.stash[HOME_CONFIG_SIZE_KEY] = _size_or_missing(home_dir / "config.json")

    # pytest의 basetemp 아래에 두면 pytest가 최근 3회분만 남기고 알아서 정리한다.
    # (tmp_path 픽스처는 테스트 안에서만 쓸 수 있어 세션 훅에서는 팩토리를 직접 쓴다.)
    factory = getattr(session.config, "_tmp_path_factory", None)
    if factory is not None:
        config_dir = factory.mktemp("ctb-config", numbered=True)
    else:  # 팩토리가 없는 환경(플러그인 비활성) — 시스템 임시 폴더로
        config_dir = Path(tempfile.mkdtemp(prefix="ctb-test-config-"))

    # 사용자가 셸에 CTB_CONFIG_DIR를 둔 채 pytest를 돌려도(검증 서버용) 그곳을
    # 쓰지 않는다 — 테스트는 언제나 자기 임시 폴더에만 쓴다.
    os.environ["CTB_CONFIG_DIR"] = str(config_dir)


@pytest.fixture()
def home_config_dir() -> Path:
    """사용자의 진짜 앱 설정 폴더 — 격리가 지켜야 할 곳."""
    return real_home_config_dir()


@pytest.fixture()
def home_baseline_sizes(request) -> dict:
    """세션 시작 때 잰 사용자 홈 파일 크기. 키: usage_log · config (-1은 없었음)."""
    stash = request.config.stash
    return {
        "usage_log": stash[HOME_USAGE_LOG_SIZE_KEY],
        "config": stash[HOME_CONFIG_SIZE_KEY],
    }


def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items) -> None:
    """`home_leak_check` 마커가 붙은 테스트를 실행 순서의 맨 뒤로 보낸다."""
    last = [it for it in items if it.get_closest_marker(LEAK_CHECK_MARK)]
    if not last:
        return
    rest = [it for it in items if not it.get_closest_marker(LEAK_CHECK_MARK)]
    items[:] = rest + last
