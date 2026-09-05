"""화면에서 하는 연결 설정과 새 판 확인 (D-102 · D-103).

무엇을 고정하는가:
  - 키는 **서고** .env에 쓴다. 사람이 적어 둔 다른 줄은 건드리지 않는다
  - 읽기는 값을 돌려주지 않는다 — «있는가»와 끝 네 글자뿐
  - 빈 값을 주면 그 줄을 지운다
  - 새 판 확인은 네트워크가 없어도 화면을 막지 않는다
  - 작업 트리가 더러우면 받지 않는다(고친 코드를 덮어쓰지 않는다)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.core import env_settings as ES


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """빈 서고 하나를 가리키는 앱. 키는 그 서고 .env에만 쓴다 — 진짜 서고를 건드리지 않는다."""
    import json

    lib = tmp_path / "서고"
    lib.mkdir()
    (lib / "library_manifest.json").write_text(
        json.dumps({"name": "t", "documents": [], "interpretations": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    for d in ("documents", "interpretations"):
        (lib / d).mkdir()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    from app._state import configure_library
    from app.server import app

    configure_library(lib)
    with TestClient(app) as c:
        c.library_path = lib
        yield c


def test_key_is_written_to_library_env_without_touching_other_lines(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / ".env").write_text(
        "# 내 메모\nCTB_SOMETHING=1\nANTHROPIC_API_KEY=old-1234\n", encoding="utf-8"
    )

    ES.write_values(lib, {"anthropic": "sk-ant-new-WXYZ", "openai": "sk-oai-QRST"})

    lines = (lib / ".env").read_text(encoding="utf-8").strip().split("\n")
    assert "# 내 메모" in lines and "CTB_SOMETHING=1" in lines  # 남의 줄은 그대로
    assert "ANTHROPIC_API_KEY=sk-ant-new-WXYZ" in lines  # 갈아 끼운다
    assert "OPENAI_API_KEY=sk-oai-QRST" in lines  # 없던 것은 더한다


def test_read_status_never_returns_the_value(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    ES.write_values(lib, {"gemini": "AIza-super-secret-VALUE"})

    status = ES.read_status(lib)

    assert status["keys"]["gemini"] == {
        "set": True,
        "hint": "…ALUE",
        "env_name": "GOOGLE_API_KEY",
    }
    assert "super-secret" not in repr(status)


def test_empty_value_removes_the_line(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    ES.write_values(lib, {"openai": "sk-oai-1234", "gemini": "AIza-5678"})

    ES.write_values(lib, {"openai": ""})

    body = (lib / ".env").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in body
    assert "GOOGLE_API_KEY=AIza-5678" in body
    assert ES.read_status(lib)["keys"]["openai"]["set"] is False


def test_unknown_provider_is_ignored(tmp_path):
    """아는 열쇠만 손댄다 — 모르는 이름으로 .env를 어지럽히지 않는다."""
    lib = tmp_path / "lib"
    lib.mkdir()
    ES.write_values(lib, {"뭔가이상한것": "x"})
    assert not (lib / ".env").exists()


def test_ollama_detect_reports_unreachable_without_raising():
    """Ollama가 없는 것은 정상 상태의 하나다 — 예외로 화면을 막지 않는다."""
    r = ES.detect_ollama("http://127.0.0.1:9", timeout=0.5)
    assert r["reachable"] is False and r["models"] == [] and r["error"]


def test_update_check_is_offline_safe(monkeypatch):
    """네트워크가 없으면 error만 담고 나머지는 비운다 — 인터넷 없이 쓰는 것이 정상이다."""
    from src.core import updater

    def boom(*a, **k):
        raise OSError("네트워크 없음")

    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    r = updater.check(timeout=0.1)
    assert r["update_available"] is False
    assert r["error"] and "확인하지 못했습니다" in r["error"]
    assert r["current"]  # 지금 판은 언제나 알 수 있다


def test_version_compare_handles_odd_values():
    from src.core.updater import _as_tuple

    assert _as_tuple("v1.3.0") == (1, 3, 0)
    assert _as_tuple("1.10.0") > _as_tuple("1.9.9")
    assert _as_tuple("unknown") == (-1,)
    assert _as_tuple("1.3.0") > _as_tuple("unknown")


def test_update_refuses_when_working_tree_is_dirty(monkeypatch):
    """고친 파일이 남아 있으면 받지 않는다 — 조용히 덮어쓰면 안 된다."""
    from src.core import updater

    monkeypatch.setattr(updater, "is_git_checkout", lambda: True)
    monkeypatch.setattr(updater, "working_tree_dirty", lambda: (True, " M src/foo.py"))

    r = updater.apply_update()

    assert r["ok"] is False
    assert "덮어쓰면" in r["hint"]
    assert r["steps"][0]["ok"] is False


def test_update_tells_zip_users_what_to_do(monkeypatch):
    """Git 사본이 아니면 앱 안에서 받을 수 없다 — 무엇을 해야 하는지 알린다."""
    from src.core import updater

    monkeypatch.setattr(updater, "is_git_checkout", lambda: False)
    r = updater.apply_update()
    assert r["ok"] is False and "zip" in r["hint"]


def test_api_never_echoes_the_key(client, tmp_path):
    """API로 저장한 키가 응답에 그대로 돌아오지 않는다."""
    r = client.post("/api/settings/llm-keys", json={"anthropic": "sk-ant-DO-NOT-ECHO-9999"})
    assert r.status_code == 200, r.text
    assert "DO-NOT-ECHO" not in r.text
    assert r.json()["keys"]["anthropic"]["hint"] == "…9999"

    r2 = client.get("/api/settings/llm-keys")
    assert "DO-NOT-ECHO" not in r2.text


def test_env_written_by_api_lands_in_the_library(client):
    """API가 쓰는 자리는 서고 루트다(프로젝트 루트가 아니다).

    왜 중요한가: 프로젝트 루트에 쓰면 앱을 새 판으로 갈 때 키가 날아가고, 실수로 저장소에
    커밋될 자리이기도 하다. 서고는 앱 폴더 밖이라 둘 다 일어나지 않는다.
    """
    client.post("/api/settings/llm-keys", json={"openai": "sk-oai-LAND"})
    path = Path(client.get("/api/settings/llm-keys").json()["path"])
    assert path.name == ".env"
    assert path.parent == Path(client.library_path)
    assert path.exists()


def test_variant_dictionary_lives_in_the_library(client):
    """이체자 사전은 앱 폴더가 아니라 서고에 산다 (D-104).

    왜: 사전은 사람이 늘려 가는 작업물이다. 앱 폴더에 쓰면 `git pull`로 새 판을 받을 때
    충돌하거나 사라지고, 실제로 앱 업데이트(D-103)가 「작업 트리가 더러워 받지 않습니다」로
    막힌다 — 이체자를 하나만 넣어도 그렇게 된다(실측 2026-09-05).
    """
    import json as _json

    app_res = Path(__file__).resolve().parent.parent / "resources"
    # 손으로 쌓은 사전은 배포본에 들어가면 안 된다(D-105 — 2026-02-15부터 공개돼 있던 것을
    # 히스토리에서까지 지웠다). 누가 다시 넣으면 여기서 막힌다.
    assert not (app_res / "variant_chars.json").exists(), (
        "resources/variant_chars.json은 공개 저장소에 두지 않는다 — 서고의 resources/에 산다"
    )
    shipped = sorted(p.name for p in app_res.glob("variant_*.json"))

    r = client.post("/api/alignment/variant-dict", json={"char_a": "檢", "char_b": "検"})
    assert r.status_code == 200, r.text

    lib_res = Path(client.library_path) / "resources"
    lib_dict = lib_res / "variant_chars.json"
    assert lib_dict.exists(), "서고에 사전이 만들어지지 않았다"
    assert "檢" in _json.loads(lib_dict.read_text(encoding="utf-8")).get("variants", {})

    # 앱이 들고 온 사전(OpenCC 파생본)은 **전부** 서고에 옮겨 심겨야 한다. 하나만 옮기면
    # 나머지가 목록에서 사라진다 — D-104 첫 판의 버그였다.
    for name in shipped:
        assert (lib_res / name).exists(), f"{name}이 서고에 복사되지 않았다"
        assert _json.loads((lib_res / name).read_text(encoding="utf-8")) == _json.loads(
            (app_res / name).read_text(encoding="utf-8")
        )
