"""서고 백업 및 복원 모듈.

서고를 폴더 그대로 백업 경로에 복사한다.
zip이 아닌 폴더 복사를 사용하는 이유:
    구글 드라이브 같은 클라우드 동기화 폴더에 넣으면
    파일 단위로 열람·검색이 가능하다.

.git/ 디렉토리는 백업에서 제외한다:
    .git은 로컬 이력 관리용이므로 백업에 불필요하고,
    오히려 오염 문제(추적 방지 대상)의 원인이 된다.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import git

logger = logging.getLogger(__name__)

# 백업 메타데이터 파일 이름
_BACKUP_META = "_backup_meta.json"


def backup_library(
    library_path: str | Path,
    backup_path: str | Path,
    exclude_git: bool = True,
) -> dict:
    """서고를 백업 경로에 폴더 그대로 복사한다.

    목적: 연구자가 구글 드라이브 등에 서고를 백업할 수 있게 한다.
    입력:
        library_path — 서고 루트 경로.
        backup_path — 백업 대상 폴더 경로.
        exclude_git — True이면 .git/ 디렉토리를 제외한다 (기본값).
    출력: {
        success: bool,
        backup_path: str,
        file_count: int,
        total_size: int,       # 바이트
        duration_sec: float,
        error: str | None,
    }
    """
    library_path = Path(library_path).resolve()
    backup_path = Path(backup_path).resolve()

    result = {
        "success": False,
        "backup_path": str(backup_path),
        "file_count": 0,
        "total_size": 0,
        "duration_sec": 0.0,
        "error": None,
    }

    # 서고 존재 확인
    if not (library_path / "library_manifest.json").exists():
        result["error"] = f"유효한 서고가 아닙니다: {library_path}"
        return result

    start = time.time()

    # .git/ 제외 콜백
    def _ignore_git(directory: str, contents: list[str]) -> list[str]:
        if not exclude_git:
            return []
        ignored = []
        for name in contents:
            if name == ".git" or name == ".git_backup":
                ignored.append(name)
        return ignored

    try:
        # 기존 백업이 있으면 _prev로 이동 (안전)
        if backup_path.exists():
            prev_path = backup_path.with_name(backup_path.name + "_prev")
            if prev_path.exists():
                shutil.rmtree(prev_path)
            backup_path.rename(prev_path)
            logger.info("이전 백업을 %s로 이동", prev_path)

        # 복사 실행
        shutil.copytree(
            library_path,
            backup_path,
            ignore=_ignore_git,
            dirs_exist_ok=False,
        )

        # 파일 개수와 총 크기 계산
        file_count = 0
        total_size = 0
        for f in backup_path.rglob("*"):
            if f.is_file():
                file_count += 1
                total_size += f.stat().st_size

        duration = time.time() - start

        # 메타데이터 저장
        meta = {
            "source": str(library_path),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "file_count": file_count,
            "total_size": total_size,
            "duration_sec": round(duration, 2),
            "exclude_git": exclude_git,
        }
        (backup_path / _BACKUP_META).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        result.update({
            "success": True,
            "file_count": file_count,
            "total_size": total_size,
            "duration_sec": round(duration, 2),
        })

    except Exception as e:
        result["error"] = str(e)
        result["duration_sec"] = round(time.time() - start, 2)

    return result


def restore_from_backup(
    backup_path: str | Path,
    restore_path: str | Path,
) -> dict:
    """백업에서 서고를 복원한다.

    목적: 백업 폴더를 새 위치에 복원하고 git 저장소를 재초기화한다.
    입력:
        backup_path — 백업 폴더 경로 (_backup_meta.json이 있어야 함).
        restore_path — 복원할 대상 경로 (비어있어야 함).
    출력: {
        success: bool,
        restore_path: str,
        repos_initialized: int,  # git init된 저장소 수
        error: str | None,
    }
    """
    backup_path = Path(backup_path).resolve()
    restore_path = Path(restore_path).resolve()

    result = {
        "success": False,
        "restore_path": str(restore_path),
        "repos_initialized": 0,
        "error": None,
    }

    # 백업 유효성 확인
    meta_file = backup_path / _BACKUP_META
    if not meta_file.exists():
        result["error"] = (
            f"유효한 백업이 아닙니다: {backup_path}\n"
            "→ _backup_meta.json 파일이 없습니다."
        )
        return result

    # 복원 대상이 비어있는지 확인 (안전 장치)
    if restore_path.exists() and any(restore_path.iterdir()):
        result["error"] = (
            f"복원 대상이 비어있지 않습니다: {restore_path}\n"
            "→ 빈 폴더를 지정하거나 새 경로를 사용하세요."
        )
        return result

    try:
        # 복사 (메타 파일 제외)
        def _ignore_meta(directory: str, contents: list[str]) -> list[str]:
            return [_BACKUP_META] if _BACKUP_META in contents else []

        shutil.copytree(
            backup_path,
            restore_path,
            ignore=_ignore_meta,
            dirs_exist_ok=False,
        )

        # git 저장소 재초기화 (documents/ + interpretations/)
        repos_initialized = 0
        for repo_type in ("documents", "interpretations"):
            type_dir = restore_path / repo_type
            if not type_dir.is_dir():
                continue
            for entry in type_dir.iterdir():
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                try:
                    repo = git.Repo.init(entry)
                    repo.git.add("-A")
                    repo.index.commit("feat: 백업에서 복원")
                    repos_initialized += 1
                except Exception as e:
                    logger.warning(
                        "복원 중 git 초기화 실패: %s — %s", entry, e
                    )

        result.update({
            "success": True,
            "repos_initialized": repos_initialized,
        })

    except Exception as e:
        result["error"] = str(e)

    return result


def get_backup_info(backup_path: str | Path) -> dict | None:
    """백업 메타데이터를 읽어 반환한다.

    입력: backup_path — 백업 폴더 경로.
    출력: {source, timestamp, file_count, total_size, ...} 또는 None.
    """
    backup_path = Path(backup_path).resolve()
    meta_file = backup_path / _BACKUP_META

    if not meta_file.exists():
        return None

    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
