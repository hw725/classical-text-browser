"""훅이 커밋을 막았는데 《커밋됨》을 돌려주지 않는다 — 2026-11-11 결함 재현(조건 COMMIT-HOOK-BLOCK).

결함: `git_commit_interpretation`·`git_commit_document` 와 저장소 생성 두 곳이
GitPython `repo.index.commit()` 의 `HookExecutionError` 를 《post-commit(LFS 등) 실패라
커밋은 됐다》고 보고 삼켰다. 그러나 pre-commit·commit-msg 훅이 실패하면 커밋은 생기지 않는다.
GitPython 3.2.1 부터 `core.hooksPath` 를 따르므로 이 PC 의 전역 doc-sync commit-msg 게이트가
`feat:` 커밋을 실제로 막을 수 있었고, 그때 함수는 이전 커밋의 hash 를 담아
`{"committed": True}` 를 돌려줬다 — 이력이 남지 않았는데 남은 것으로 보인다.

시험은 사용자 전역 git 설정과 격리돼 있다(conftest `_isolate_git_config`, 조건 GIT-HERMETIC).
훅은 저장소 로컬 `core.hooksPath` 로만 건다. 훅 폴더는 저장소 안에 둔다 — GitPython 이 Windows
에서 bash 에 작업 폴더 기준 상대 경로로 넘기기 때문이다.
"""

from __future__ import annotations

from pathlib import Path

import git
import pytest

from core.document import git_commit_document
from core.interpretation import git_commit_interpretation


def _repo_with_first_commit(path: Path) -> git.Repo:
    """첫 커밋이 있는 저장소를 만든다(훅 없이)."""
    path.mkdir(parents=True)
    repo = git.Repo.init(path)
    (path / "a.txt").write_text("처음", encoding="utf-8")
    repo.git.add("-A")
    repo.index.commit("chore: 시작")
    return repo


def _install_hook(repo: git.Repo, name: str, exit_code: int) -> None:
    """저장소 로컬 core.hooksPath 에 훅 하나를 둔다."""
    hooks = Path(repo.working_dir) / ".git" / "test-hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / name
    hook.write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8", newline="\n")
    hook.chmod(0o755)
    with repo.config_writer() as cw:
        cw.set_value("core", "hooksPath", ".git/test-hooks")


def _change(repo: git.Repo) -> None:
    (Path(repo.working_dir) / "a.txt").write_text("고침", encoding="utf-8")


COMMITTERS = {
    "interpretation": git_commit_interpretation,
    "document": git_commit_document,
}


@pytest.mark.parametrize("hook", ["pre-commit", "commit-msg"])
@pytest.mark.parametrize("kind", sorted(COMMITTERS))
def test_blocking_hook_is_not_reported_as_committed(tmp_path, kind, hook):
    repo = _repo_with_first_commit(tmp_path / "repo")
    before = repo.head.commit.hexsha
    _install_hook(repo, hook, 1)
    _change(repo)

    result = COMMITTERS[kind](tmp_path / "repo", "feat: 시험 저장")

    assert repo.head.commit.hexsha == before, "훅이 막았는데 커밋이 생겼다"
    assert result["committed"] is False, result
    assert result.get("reason") == "hook_blocked", result
    assert result.get("hash") != before, "이전 커밋의 hash 를 새 커밋처럼 돌려준다"


@pytest.mark.parametrize("kind", sorted(COMMITTERS))
def test_failing_post_commit_still_counts_as_committed(tmp_path, kind):
    repo = _repo_with_first_commit(tmp_path / "repo")
    before = repo.head.commit.hexsha
    _install_hook(repo, "post-commit", 1)
    _change(repo)

    result = COMMITTERS[kind](tmp_path / "repo", "feat: 시험 저장")

    after = repo.head.commit.hexsha
    assert after != before, "post-commit 만 실패했는데 커밋이 없다"
    assert result["committed"] is True, result
    assert result["hash"] == after


@pytest.mark.parametrize("kind", sorted(COMMITTERS))
def test_repo_without_local_hookspath_gets_hooks_disabled(tmp_path, kind):
    """로컬 hooksPath 가 없는 기존 저장소는 커밋할 때 훅을 끈다(.git/hooks 의 훅이 안 돈다)."""
    repo = _repo_with_first_commit(tmp_path / "repo")
    before = repo.head.commit.hexsha
    hook = Path(repo.git_dir) / "hooks" / "pre-commit"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")
    hook.chmod(0o755)
    _change(repo)

    result = COMMITTERS[kind](tmp_path / "repo", "feat: 시험 저장")

    assert result["committed"] is True, result
    assert repo.head.commit.hexsha != before
    with repo.config_reader("repository") as cr:
        hooks_path = cr.get("core", "hooksPath", fallback="")
    assert hooks_path, "로컬 core.hooksPath 가 설정되지 않았다"
    hooks_dir = Path(hooks_path)
    if not hooks_dir.is_absolute():
        hooks_dir = Path(repo.working_dir) / hooks_dir
    assert hooks_dir.is_dir() and not any(hooks_dir.iterdir()), "훅 폴더가 비어 있지 않다"


def test_new_interpretation_repo_has_hooks_disabled(tmp_path):
    """새 해석 저장소는 생성 때 문서 저장소처럼 로컬 core.hooksPath 를 빈 폴더로 둔다."""
    from core.document import add_document
    from core.interpretation import create_interpretation
    from core.library import init_library

    lib = tmp_path / "lib"
    init_library(lib)
    add_document(lib, "시험 문헌", "doc_hook")
    interp = create_interpretation(lib, "interp_hook", "doc_hook", "human", title="시험")

    repo = git.Repo(interp)
    with repo.config_reader("repository") as cr:
        hooks_path = cr.get("core", "hooksPath", fallback="")
    assert hooks_path, "해석 저장소에 로컬 core.hooksPath 가 없다"
    assert repo.head.is_valid(), "초기 커밋이 없다"
