"""OpenAI OAuth 프록시 띄우기 (D-107) — 프록시를 실제로 띄우지 않고 판독·거절 규칙을 검사한다."""

from core import oauth_proxy as op


def test_ready_and_login_url_are_parsed():
    """프록시 출력에서 «준비됨» 주소와 로그인 주소를 건진다.

    내 컴퓨터 주소(127.0.0.1)는 로그인 주소가 아니다.
    """
    m = op._READY.search("OpenAI-compatible endpoint ready at http://127.0.0.1:10532/v1")
    assert m and m.group(1) == "http://127.0.0.1:10532/v1"
    urls = op._LOGIN_URL.findall("Open https://auth.openai.com/oauth/authorize?x=1 to sign in")
    assert urls == ["https://auth.openai.com/oauth/authorize?x=1"]
    assert op._LOGIN_URL.findall("ready at http://127.0.0.1:10532/v1") == []


def test_status_without_proxy(monkeypatch):
    """프록시가 없으면 ready=False, 주소 없음. npx 유무는 그대로 알려 준다."""
    monkeypatch.setattr(op, "_probe", lambda port, timeout=1.5: False)
    monkeypatch.setattr(op, "find_npx", lambda: None)
    s = op.status()
    assert s["ready"] is False and s["base_url"] is None and s["npx"] is False
    assert isinstance(s["log"], list)


def test_start_refuses_without_npx(monkeypatch):
    """Node.js가 없으면 무엇을 깔아야 하는지 말하고 띄우지 않는다."""
    monkeypatch.setattr(op, "_probe", lambda port, timeout=1.5: False)
    monkeypatch.setattr(op, "find_npx", lambda: None)
    r = op.start()
    assert "nodejs.org" in r["error"]
    assert r["ready"] is False


def test_start_reuses_running_proxy(monkeypatch):
    """start_server.bat이 이미 띄운 프록시가 있으면 새로 띄우지 않는다."""
    monkeypatch.setattr(op, "_probe", lambda port, timeout=1.5: port == 10533)
    monkeypatch.setattr(op, "find_npx", lambda: "npx.cmd")
    spawned = []
    monkeypatch.setattr(op.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)
    r = op.start()
    assert spawned == []
    assert r["ready"] is True and r["base_url"] == "http://127.0.0.1:10533/v1"
