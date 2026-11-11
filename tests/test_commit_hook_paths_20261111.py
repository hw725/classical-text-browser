"""서고 저장소에 커밋하는 모든 길이 훅을 끄고, 막히면 숨기지 않는다.

D-149 후속, 계약 조건 COMMIT-HOOK-PATHS.

D-149는 `git_commit_interpretation`·`git_commit_document`와 생성 두 곳만 고쳤다. 그 밖에도
`repo.index.commit()`을 직접 부르는 길이 있었다 — 되돌리기(`git_graph.revert_to_commit`),
백업 복원, 스냅샷에서 작업 만들기, 해석 저장소 폴더 가져오기(git CLI), .git 오염 자동 수리.
새로 `git init`한 저장소나 훅을 끄지 않은 옛 저장소에서는 사용자 전역 훅·git 템플릿 훅이
그 커밋을 막을 수 있다(이 PC에서는 `~/.gitconfig` includeIf 우회가 가리고 있었다).

시험은 사용자 전역 git 설정과 격리돼 있다(GIT-HERMETIC). 새 저장소의 훅은 `GIT_TEMPLATE_DIR`
(git init이 .git/hooks로 복사하는 틀)로, 기존 저장소의 훅은 .git/hooks 또는 저장소 로컬
core.hooksPath로 건다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import git
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"


def _failing_hook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")
    path.chmod(0o755)


@pytest.fixture
def failing_template(tmp_path, monkeypatch):
    """git init이 실패하는 pre-commit 훅을 .git/hooks에 복사하게 한다(LFS 템플릿과 같은 경로)."""
    tpl = tmp_path / "git-template"
    _failing_hook(tpl / "hooks" / "pre-commit")
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(tpl))
    return tpl


def _two_commit_repo(path: Path) -> tuple[git.Repo, str]:
    path.mkdir(parents=True)
    repo = git.Repo.init(path)
    (path / "a.txt").write_text("하나", encoding="utf-8")
    repo.git.add("-A")
    first = repo.index.commit("chore: 하나").hexsha
    (path / "a.txt").write_text("둘", encoding="utf-8")
    (path / "b.txt").write_text("새 파일", encoding="utf-8")
    repo.git.add("-A")
    repo.index.commit("chore: 둘")
    return repo, first


def test_no_direct_commit_outside_guard():
    """서고 저장소 커밋은 core/git_commit_guard.commit_index 하나로만 한다."""
    offenders = []
    for py in SRC.rglob("*.py"):
        if py.name == "git_commit_guard.py":
            continue
        text = py.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r"\bindex\.commit\(", line) or re.search(
                r"""\[\s*["']git["']\s*,\s*["']commit["']""", line
            ):
                offenders.append(f"{py.relative_to(SRC)}:{i}: {line.strip()}")
    assert not offenders, "commit_index()를 거치지 않는 커밋:\n" + "\n".join(offenders)


def test_revert_disables_hooks_on_repo_without_local_hookspath(tmp_path):
    from core.git_graph import revert_to_commit

    repo, first = _two_commit_repo(tmp_path / "repo")
    _failing_hook(Path(repo.git_dir) / "hooks" / "pre-commit")
    before = repo.head.commit.hexsha

    result = revert_to_commit(tmp_path / "repo", first)

    assert result.get("reverted") is True, result
    assert repo.head.commit.hexsha != before
    assert (tmp_path / "repo" / "a.txt").read_text(encoding="utf-8") == "하나"


def test_revert_blocked_by_hook_is_not_reported_and_leaves_tree_clean(tmp_path):
    from core.git_graph import revert_to_commit

    repo, first = _two_commit_repo(tmp_path / "repo")
    hooks = Path(repo.working_dir) / ".git" / "test-hooks"
    _failing_hook(hooks / "pre-commit")
    with repo.config_writer() as cw:
        cw.set_value("core", "hooksPath", ".git/test-hooks")
    before = repo.head.commit.hexsha

    result = revert_to_commit(tmp_path / "repo", first)

    assert result.get("reverted") is False, result
    assert result.get("reason") == "hook_blocked", result
    assert repo.head.commit.hexsha == before
    # 막혔으면 작업 폴더를 되돌리기 전 상태로 둔다
    # — 남기면 다음 되돌리기가 《커밋되지 않은 변경》으로 거부된다
    assert not repo.is_dirty(untracked_files=True)
    assert (tmp_path / "repo" / "b.txt").exists()


def test_backup_restore_commits_despite_template_hook(tmp_path, failing_template):
    from core.backup import restore_from_backup

    backup = tmp_path / "backup"
    (backup / "documents" / "doc_a").mkdir(parents=True)
    (backup / "documents" / "doc_a" / "manifest.json").write_text("{}", encoding="utf-8")
    (backup / "interpretations" / "interp_a").mkdir(parents=True)
    (backup / "interpretations" / "interp_a" / "manifest.json").write_text("{}", encoding="utf-8")
    (backup / "_backup_meta.json").write_text(json.dumps({"v": 1}), encoding="utf-8")

    result = restore_from_backup(backup, tmp_path / "restored")

    assert result["repos_initialized"] == 2, result
    for sub in ("documents/doc_a", "interpretations/interp_a"):
        assert git.Repo(tmp_path / "restored" / sub).head.is_valid(), f"{sub} 커밋 없음"


def test_snapshot_init_commit_despite_template_hook(tmp_path, failing_template):
    from core.snapshot import _git_init_and_commit

    target = tmp_path / "work"
    target.mkdir()
    (target / "a.txt").write_text("x", encoding="utf-8")

    _git_init_and_commit(target, "feat: 스냅샷에서 작업 생성")

    assert git.Repo(target).head.is_valid(), "스냅샷 저장소에 커밋이 없다"
