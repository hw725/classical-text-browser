"""시험 안의 git 이 사용자 전역 git 설정(훅 경로 등)을 읽지 않는다 — 2026-11-11 사고 재현.

사고: 이 PC 의 전역 `core.hooksPath`(doc-sync 훅)를 GitPython 3.2 가 따르면서, 시험이
임시 폴더에 만든 저장소의 `repo.index.commit()` 이 그 훅을 bash 상대 경로로 불렀고,
Git Bash 가 %TEMP% 를 /tmp 로 마운트해 경로가 깨져 exit 127 로 죽었다(77 실패·5 오류).
%TEMP% 밖이었다면 doc-sync 게이트가 `feat:` 커밋을 막았다.
CI 는 전역 훅이 없어 통과했다. 시험은 PC 의 전역 설정과 무관하게 같은 결과를 내야 한다.
"""

from __future__ import annotations

import os
import subprocess

import git


def test_gitpython_does_not_see_user_global_config(tmp_path):
    repo = git.Repo.init(tmp_path / "repo")
    with repo.config_reader() as cr:
        hooks = cr.get("core", "hooksPath", fallback="")
        assert hooks == "", "사용자 전역 core.hooksPath 가 시험에 보인다"
        assert cr.get("user", "name", fallback="") == "ctb-test"


def test_git_cli_does_not_see_user_global_config(tmp_path):
    out = subprocess.run(["git", "config", "--global", "--list"], capture_output=True, text=True,
                         encoding="utf-8", cwd=tmp_path, env=os.environ.copy())
    assert "hookspath" not in out.stdout.lower(), out.stdout
    assert "user.name=ctb-test" in out.stdout, out.stdout


def test_feat_commit_in_temp_repo_succeeds(tmp_path):
    repo = git.Repo.init(tmp_path / "repo")
    (tmp_path / "repo" / "a.txt").write_text("x", encoding="utf-8")
    repo.index.add(["a.txt"])
    commit = repo.index.commit("feat: 문헌 등록 — 시험")
    assert repo.head.commit == commit
