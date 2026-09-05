"""zip으로 푼 폴더도 새 판을 알고 받는다 (D-112).

왜: 설치 안내가 zip → install.bat이라 다른 PC의 앱 폴더에는 .git이 없었다. 판 번호가 같으면
커밋을 비교해야 하는데 비교할 것이 없어 «최신»으로만 보였다(2026-09-06 보고).
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from core import updater  # noqa: E402


def _git(args, cwd):
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


@pytest.fixture
def origin_and_zip(tmp_path):
    """원격(main에 커밋 둘)과, 첫 커밋 시점에 푼 zip 폴더."""
    if shutil.which("git") is None:
        pytest.skip("git이 없다")
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(["init", "-q"], origin)
    _git(["symbolic-ref", "HEAD", "refs/heads/main"], origin)
    _git(["config", "user.email", "t@example.com"], origin)
    _git(["config", "user.name", "t"], origin)
    (origin / "app.py").write_text("v1\n", encoding="utf-8")
    _git(["add", "."], origin)
    _git(["commit", "-q", "-m", "first"], origin)
    zipdir = tmp_path / "zip"
    zipdir.mkdir()
    (zipdir / "app.py").write_text("v1\n", encoding="utf-8")
    (zipdir / ".env").write_text("SECRET=1\n", encoding="utf-8")  # 사용자 파일(추적 안 함)
    (origin / "app.py").write_text("v2\n", encoding="utf-8")
    _git(["commit", "-q", "-am", "second"], origin)
    return origin, zipdir


def test_zip_folder_becomes_git_checkout_without_touching_files(origin_and_zip):
    origin, zipdir = origin_and_zip
    r = updater.ensure_git_checkout(zipdir, remote=str(origin))
    assert r["ok"] and r["converted"], r
    assert (zipdir / ".git").exists() and updater.from_zip(zipdir)
    assert (zipdir / "app.py").read_text(encoding="utf-8") == "v1\n"  # 파일은 그대로
    assert (zipdir / ".env").exists()
    # zip 시점 이후 바뀐 것이 있으니 «받을 것 있음»
    assert updater.zip_differs(zipdir) is True
    # 두 번 불러도 다시 바꾸지 않는다
    assert updater.ensure_git_checkout(zipdir, remote=str(origin))["converted"] is False


def test_zip_checkout_reports_clean_when_zip_is_current(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git이 없다")
    origin = tmp_path / "o"
    origin.mkdir()
    _git(["init", "-q"], origin)
    _git(["symbolic-ref", "HEAD", "refs/heads/main"], origin)
    _git(["config", "user.email", "t@example.com"], origin)
    _git(["config", "user.name", "t"], origin)
    (origin / "a.txt").write_text("same\n", encoding="utf-8")
    _git(["add", "."], origin)
    _git(["commit", "-q", "-m", "only"], origin)
    z = tmp_path / "z"
    z.mkdir()
    (z / "a.txt").write_text("same\n", encoding="utf-8")
    assert updater.ensure_git_checkout(z, remote=str(origin))["ok"]
    assert updater.zip_differs(z) is False


def test_dirty_check_ignores_untracked_files(origin_and_zip):
    origin, zipdir = origin_and_zip
    updater.ensure_git_checkout(zipdir, remote=str(origin))
    _git(["reset", "-q", "--hard", "origin/main"], zipdir)
    (zipdir / "logs.txt").write_text("x", encoding="utf-8")  # 추적하지 않는 파일
    dirty, _ = updater.working_tree_dirty(zipdir)
    assert dirty is False
    (zipdir / "app.py").write_text("edited\n", encoding="utf-8")
    dirty, _ = updater.working_tree_dirty(zipdir)
    assert dirty is True
