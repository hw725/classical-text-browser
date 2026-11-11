"""훅이 커밋을 막으면 화면에 알린다 — D-149 후속(조건 COMMIT-BLOCKED-NOTICE).

D-149는 막힌 커밋을 `committed: False`로 돌려주게 했지만, 해석 저장소 저장 호출처 22곳 중
16곳(표점·현토·번역·주석·비고 저장 등)은
`try: git_commit_interpretation(...) except Exception: pass`로 결과를 버린다.
그 자리에서 막힌 커밋은 서버 경고 기록에만 남고 연구자는 모른다.
LLM 폴백 알림(D-143, `llm/fallback_notice.py`)과 같은 길로 푼다 — `commit_index`가 막힌 커밋을
요청 단위 목록에 적고, 미들웨어가 응답 머리 `X-CTB-Commit-Blocked`에 싣고, 화면(toast.js)의
fetch 한 곳이 그 머리를 보고 알린다. 라우트마다 응답에 꼬리표를 붙이면 새 저장 화면에서 또 빠진다.
"""

from __future__ import annotations

from pathlib import Path

import git

from core.interpretation import git_commit_interpretation

HEADER = "X-CTB-Commit-Blocked"


def _blocked_repo(path: Path) -> git.Repo:
    path.mkdir(parents=True)
    repo = git.Repo.init(path)
    (path / "a.txt").write_text("처음", encoding="utf-8")
    repo.git.add("-A")
    repo.index.commit("chore: 시작")
    hooks = path / ".git" / "test-hooks"
    hooks.mkdir()
    hook = hooks / "commit-msg"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")
    hook.chmod(0o755)
    with repo.config_writer() as cw:
        cw.set_value("core", "hooksPath", ".git/test-hooks")
    return repo


def test_response_carries_header_when_a_swallowed_commit_was_blocked(tmp_path):
    """호출처가 결과를 버려도(except Exception: pass) 응답 머리로 화면에 닿는다."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.server import _commit_blocked_header

    repo_path = tmp_path / "interp"
    _blocked_repo(repo_path)
    mini = FastAPI()
    mini.middleware("http")(_commit_blocked_header)

    @mini.post("/api/save")
    def save():  # 동기 라우트 — 실제 저장 라우트처럼 스레드에서 돈다
        (repo_path / "a.txt").write_text("고침", encoding="utf-8")
        try:
            git_commit_interpretation(repo_path, "feat: L5 표점 저장 — page 1")
        except Exception:
            pass
        return {"success": True}

    @mini.get("/api/quiet")
    def quiet():
        return {}

    c = TestClient(mini)
    got = c.post("/api/save")
    assert got.status_code == 200 and got.json() == {"success": True}
    assert got.headers.get(HEADER) == "1", dict(got.headers)
    assert HEADER not in c.get("/api/quiet").headers


def test_real_app_registers_the_middleware():
    from app.server import _commit_blocked_header, app

    dispatches = [m.kwargs.get("dispatch") for m in app.user_middleware]
    assert _commit_blocked_header in dispatches


def test_screen_turns_header_into_a_notice(tmp_path):
    from tests.js_harness import run_js

    out = run_js(
        tmp_path,
        "toast.js",
        ["_commitBlockedNotice"],
        "",
        "console.log(JSON.stringify({ msg: _commitBlockedNotice('2'),"
        " none: _commitBlockedNotice(null) }));",
    )
    assert "버전 이력" in out["msg"] and "저장" in out["msg"], out
    assert out["none"] is None


def test_fetch_watch_shows_toast_for_blocked_commit(tmp_path):
    """fetch 감시 한 곳이 머리를 보고 토스트를 띄운다(LLM 폴백 머리와 함께)."""
    from tests.js_harness import run_js

    setup = (
        "const shown = [];"
        "globalThis.window = { showToast: (m, kind) => shown.push([m, kind]) };"
        "function _res(h) { return { headers: { get: (k) => (k in h ? h[k] : null) } }; }"
    )
    out = run_js(
        tmp_path,
        "toast.js",
        ["_llmFallbackNotice", "_commitBlockedNotice", "_watchResponseNotices"],
        setup,
        "_watchResponseNotices(_res({'X-CTB-Commit-Blocked': '1'}));"
        "const afterBlocked = shown.length;"
        "_watchResponseNotices(_res({}));"
        "console.log(JSON.stringify({ afterBlocked, total: shown.length,"
        " kind: shown[0] && shown[0][1], msg: shown[0] && shown[0][0] }));",
    )
    assert out["afterBlocked"] == 1 and out["total"] == 1, out
    assert out["kind"] == "warning" and "버전 이력" in out["msg"], out
