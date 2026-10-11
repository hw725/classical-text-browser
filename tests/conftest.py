"""pytest 전역 설정 — 테스트를 사용자의 홈·바깥 네트워크·전역 서고 경로에서 격리한다.

세 가지를 한다(아래 «왜 있는가»는 첫째의 사연):
    1. 앱 설정 폴더(`CTB_CONFIG_DIR`)를 임시 폴더로 — 홈의 기록·최근 서고 목록에 쓰지 않게.
    2. 표지(`network`) 없는 시험의 바깥 연결을 막는다 — 루프백이어도 바깥으로 넘겨 부르는 데몬
       (Ollama 11434·OAuth 프록시 10531~10540)은 막는다(2026-10-11).
    3. 시험마다 전역 서고 경로(`app._state`)를 되돌린다 — 앞 시험의 서고가 뒤 시험에 새지 않게.

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

import ipaddress
import os
import socket
import tempfile
from pathlib import Path

import pytest

# 세션 시작 때 잰 «사용자 홈 기록 크기». -1이면 파일이 없었다.
HOME_USAGE_LOG_SIZE_KEY = pytest.StashKey[int]()
# 세션 시작 때 잰 «사용자 홈 config.json 크기». -1이면 파일이 없었다.
HOME_CONFIG_SIZE_KEY = pytest.StashKey[int]()

# 실행 순서를 맨 뒤로 보낼 마커 이름
LEAK_CHECK_MARK = "home_leak_check"

# 외부 네트워크를 써도 되는 시험의 마커 이름
NETWORK_MARK = "network"
NETWORK_BLOCKED_MESSAGE = "시험 중 외부 네트워크 차단"


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
    config.addinivalue_line(
        "markers",
        f"{NETWORK_MARK}: 외부 네트워크(실제 사이트·API)를 쓰는 시험 — 이 표지가 없으면 막힌다",
    )


# 루프백이어도 막는 포트 — 바깥으로 넘겨 부르는 로컬 데몬이다(2026-10-11 2차 전수).
#   11434: Ollama — `:cloud` 모델을 ollama.com으로 넘겨 부른다(구독 한도 소모)
#   10531~10540: OpenAI OAuth 프록시(start_server.bat이 띄움) — OpenAI로 넘겨 부른다
RELAYING_LOCAL_PORTS = frozenset({11434, *range(10531, 10541)})


def _is_relaying_local_daemon(address) -> bool:
    return isinstance(address, tuple) and len(address) >= 2 and address[1] in RELAYING_LOCAL_PORTS


def _is_loopback(address) -> bool:
    """소켓 주소가 이 PC 안(127.0.0.1·::1·localhost)이거나 AF_UNIX 경로인가."""
    if not isinstance(address, tuple):  # AF_UNIX 경로 등
        return True
    host = address[0]
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False  # 이름으로 온 바깥 호스트


@pytest.fixture(autouse=True)
def _restore_library_path():
    """시험이 바꾼 전역 서고 경로(`app._state`)를 시험 뒤에 되돌린다.

    왜: 여러 픽스처(`client` — test_sweep·test_read_plan·test_parsers 등)가 quick-start로
    서고를 만들고 그 경로를 되돌리지 않아, 뒤 시험이 앞 시험의 임시 서고를 보고 돌았다
    (2026-10-11 전수). 픽스처마다
    고치면 새 픽스처에서 또 빠지므로 여기 한 곳에서 지킨다. 바뀐 때만 되돌린다 — 되돌리기는 라우터·
    파이프라인 캐시를 비우므로, 경로를 건드리지 않은 시험의 캐시는 그대로 둔다.
    """
    try:
        from app import _state
    except Exception:  # noqa: BLE001 — 앱을 import하지 않는 시험 환경
        yield
        return
    saved = _state.get_library_path()
    yield
    if _state.get_library_path() != saved:
        _state.set_library_path(saved)


@pytest.fixture(autouse=True)
def _block_external_network(request, monkeypatch):
    """`network` 표지가 없는 시험은 바깥으로 나가는 소켓 연결을 막는다.

    왜: 이 PC에는 실제 OpenRouter·Gemini·Cloudflare 키가 있다. 가짜 라우터를 빠뜨린 시험이
    «200 또는 400»을 둘 다 통과로 받으며 매 verify마다 실제 LLM을 불렀다(2026-10-11 실측 —
    편성 «말로 넣기» 시험 둘이 5.2초·3.6초, google.genai 클라이언트 생성, B-035). 키가 없는
    PC에서는 같은 시험이 다른 길로 초록이 되어 아무도 몰랐다. 외부 연결이 «조용히 되는»
    길을 막아야 그런 시험이 빨간불로 드러난다.

    로컬(127.0.0.1·::1)은 막지 않는다 — 시험이 띄운 서버·워커와 말하는 길이다.
    **단 Ollama·OAuth 프록시 포트는 로컬이어도 막는다**(RELAYING_LOCAL_PORTS) — 그 데몬이 바깥으로
    넘겨 부르므로, 열어 두면 «외부 연결이 조용히 되는 길»이 그대로 남는다(2026-10-11 2차 전수:
    llm_vision 강제 시험과 계정 라우트 시험이 PC에 Ollama가 떠 있으면 클라우드 모델까지 닿았다).
    """
    if request.node.get_closest_marker(NETWORK_MARK):
        return
    import errno

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def _blocked(address) -> bool:
        return not _is_loopback(address) or _is_relaying_local_daemon(address)

    def guarded_connect(self, address):
        if _blocked(address):
            raise ConnectionRefusedError(
                f"{NETWORK_BLOCKED_MESSAGE}: {address!r} — 실제 사이트·API(또는 로컬 Ollama·OAuth "
                f"프록시)를 쓰는 시험이면 @pytest.mark.{NETWORK_MARK}(그리고 slow)를 붙이고, "
                "아니면 가짜로 바꾸세요."
            )
        return original_connect(self, address)

    def guarded_connect_ex(self, address):
        if _blocked(address):
            # connect_ex는 예외 대신 오류 번호를 돌려준다(OS마다 값이 다르다 — 111은 리눅스 값)
            return errno.ECONNREFUSED
        return original_connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)


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
