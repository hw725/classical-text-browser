"""문헌·해석 저장소의 git 커밋을 훅에 휘둘리지 않게, 실패를 숨기지 않게 만든다.

왜 이 모듈이 있는가(2026-11-11):
    GitPython 의 `repo.index.commit()` 은 pre-commit → commit-msg → 커밋 생성 → post-commit
    순서로 돈다. 훅이 실패하면 어느 단계든 같은 `git.HookExecutionError` 를 낸다.
    예전 코드는 이것을 모두 《post-commit(LFS 등) 실패라 커밋은 됐다》고 보고 삼킨 뒤
    `repo.head.commit`(= 이전 커밋)을 새 커밋처럼 돌려줬다. 그러나 pre-commit·commit-msg 가
    실패하면 커밋은 생기지 않는다 — 이력이 남지 않았는데 남은 것으로 보였다.
    GitPython 3.2.1 부터 `core.hooksPath` 를 따르므로, 사용자 PC 의 전역 훅(예: 커밋 메시지
    검사 게이트)이 서고 저장소의 `feat:` 커밋을 실제로 막을 수 있었다.

    두 가지로 막는다.
    1. `disable_repo_hooks()` — 서고 저장소는 앱이 버전 관리용으로만 쓰므로 로컬
       `core.hooksPath` 를 빈 폴더로 돌려 훅을 끈다(문서 저장소가 생성 때 하던 일을 해석
       저장소와 그 처리가 없는 옛 저장소까지 넓힌다). 사용자가 로컬 hooksPath 를 직접
       정해 두었으면 그대로 둔다.
    2. `commit_index()` — 그래도 훅이 실패하면 호출 전후 HEAD 를 비교해 커밋이 실제로
       생겼는지 판정한다. 옮겼으면(post-commit 만 실패) 그 커밋으로 성공, 그대로면 실패로
       알린다. 훅 이름(오류 문구)을 읽지 않는 것은 GitPython 내부 문구 형식에 기대지 않으려고다.
"""

from __future__ import annotations

import logging
from pathlib import Path

import git

logger = logging.getLogger(__name__)

# 훅을 끌 때 hooksPath 로 지정하는 빈 폴더 이름(.git 아래). 문서 저장소가 처음부터 쓰던 이름이다.
EMPTY_HOOKS_DIRNAME = "no-hooks"


def disable_repo_hooks(repo: git.Repo) -> bool:
    """저장소 로컬 core.hooksPath 가 없으면 빈 폴더로 지정해 훅을 끈다.

    입력: repo — GitPython 저장소.
    출력: 이번에 설정했으면 True, 이미 로컬 설정이 있어 그대로 두었으면 False.
    왜: 시스템 git 템플릿(git-lfs 등)이나 사용자 전역 core.hooksPath 의 훅이 서고 저장소의
        커밋을 막거나 깨뜨리지 않게 한다. 빈 폴더를 지정하면 git 이 훅을 찾지 못해 그냥 통과한다.
        사용자가 이 저장소에 로컬 hooksPath 를 직접 정했다면 그 뜻을 존중해 건드리지 않는다
        — 그 훅이 커밋을 막으면 `commit_index()` 가 실패로 알린다.
    """
    with repo.config_reader("repository") as cr:
        if cr.get("core", "hooksPath", fallback=""):
            return False
    empty = Path(repo.git_dir) / EMPTY_HOOKS_DIRNAME
    empty.mkdir(exist_ok=True)
    with repo.config_writer("repository") as cw:
        # Windows 에서도 git config 는 forward slash 를 받는다.
        cw.set_value("core", "hooksPath", str(empty).replace("\\", "/"))
    return True


def _head_sha(repo: git.Repo) -> str | None:
    """지금 HEAD 커밋의 hash. 첫 커밋 전(HEAD 가 가리킬 것이 없음)이면 None."""
    try:
        return repo.head.commit.hexsha
    except ValueError:
        return None


def commit_index(repo: git.Repo, message: str) -> tuple[git.Commit | None, str | None]:
    """색인(스테이징)을 커밋하고, 훅이 커밋을 막았는지 판정한다.

    입력: repo — GitPython 저장소(이미 add 를 마친 상태), message — 커밋 메시지.
    출력: (커밋, None) — 커밋이 생겼다(post-commit 훅만 실패한 경우 포함).
          (None, 오류 문구) — 훅이 커밋을 막아 HEAD 가 그대로다.
    왜: 훅 실패를 예외 한 종류로만 받으므로, 커밋이 실제로 생겼는지는 HEAD 가 옮겼는가로
        판정한다. 막힌 경우 스테이징은 남아 있으므로 다음 저장 때 다시 커밋을 시도한다.
    """
    before = _head_sha(repo)
    try:
        return repo.index.commit(message), None
    except git.HookExecutionError as e:
        after = _head_sha(repo)
        if after is not None and after != before:
            logger.warning("git post-commit 훅 실패 — 커밋은 생성됨(%s): %s", after[:7], e)
            return repo.head.commit, None
        logger.warning("git 훅이 커밋을 막았습니다 — 커밋되지 않음: %s", e)
        return None, str(e)


def blocked_result(message: str, error: str) -> dict:
    """훅이 커밋을 막았을 때 커밋 함수들이 돌려주는 결과.

    입력: message — 커밋 메시지, error — 훅 오류 문구.
    출력: {committed: False, reason: "hook_blocked", message, error, detail}.
    왜: 파일 저장은 커밋 전에 이미 끝났으므로 저장 자체를 실패로 만들지 않되,
        《커밋됨》이라고 거짓으로 알리지 않는다. 응답의 `git` 칸에 실리면 화면·로그가 이것을 본다.
    """
    return {
        "committed": False,
        "reason": "hook_blocked",
        "message": message,
        "error": error,
        "detail": (
            "git 훅이 커밋을 막아 이번 변경은 버전 이력에 남지 않았습니다(파일 저장은 됐습니다). "
            "→ 해결: 이 저장소의 .git/config 에 core.hooksPath 를 직접 정했다면 "
            "그 훅을 확인하세요. "
            "다음 저장 때 다시 커밋을 시도합니다."
        ),
    }
