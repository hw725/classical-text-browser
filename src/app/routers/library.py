"""서고 관리 라우터.

서고 전환, 생성, 최근 목록, 설정, 백업/복원, Git 동기화,
휴지통 조회/복원 등 서고 수준 API를 모아둔다.

왜 분리하는가:
    server.py가 너무 길어져 유지보수가 어렵다.
    서고 관리 기능은 독립적이므로 별도 라우터로 분리한다.
"""

import asyncio
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from core.library import (
    check_git_health,
    get_library_info,
    list_trash,
    repair_git_contamination,
    restore_from_trash,
)

from app._state import get_library_path, configure_library, _resolve_repo_path

logger = logging.getLogger(__name__)

router = APIRouter(tags=["library"])

# 정적 파일 디렉토리 — routers/ 는 app/ 아래이므로 한 단계 더 올라간다
_static_dir = Path(__file__).parent.parent / "static"


# ── Pydantic 모델 ─────────────────────────────────

class SwitchLibraryRequest(BaseModel):
    """서고 전환 요청."""
    path: str


class InitLibraryRequest(BaseModel):
    """새 서고 생성 요청."""
    path: str


class BackupPathRequest(BaseModel):
    """백업 경로 설정 요청."""
    path: str  # 백업 폴더 경로


class RestoreRequest(BaseModel):
    """복원 요청."""
    backup_path: str   # 백업 폴더 경로
    restore_path: str  # 복원할 대상 경로


class SetRemoteRequest(BaseModel):
    """원격 저장소 URL 설정 요청."""
    repo_type: str   # "documents" 또는 "interpretations"
    repo_id: str     # 저장소 ID
    remote_url: str  # 원격 URL


class GitPushPullRequest(BaseModel):
    """Git push/pull 요청."""
    repo_type: str   # "documents" 또는 "interpretations"
    repo_id: str
    action: str      # "push" 또는 "pull"


# ── 헬퍼 ──────────────────────────────────────────

_tk_executor = ThreadPoolExecutor(max_workers=1)


def _open_folder_dialog():
    """네이티브 폴더 선택 대화상자를 연다 (동기식).

    왜 tkinter인가:
        이 앱은 로컬 전용이므로 네이티브 대화상자가 가장 직관적이다.
        tkinter는 Python 표준 라이브러리라 추가 설치가 필요 없다.
    """
    from tkinter import Tk
    from tkinter.filedialog import askdirectory

    root = Tk()
    root.withdraw()
    # 대화상자를 브라우저 위에 표시
    root.attributes("-topmost", True)
    path = askdirectory(title="서고 폴더를 선택하세요")
    root.destroy()
    return path


def _get_git_remote(repo_dir: Path) -> str | None:
    """Git 저장소의 origin remote URL을 반환한다."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(repo_dir), capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


# ── 라우트 ─────────────────────────────────────────

@router.get("/")
async def index():
    """메인 워크스페이스 페이지를 반환한다."""
    return FileResponse(str(_static_dir / "index.html"))


@router.get("/api/library")
async def api_library():
    """서고 정보를 반환한다."""
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse(
            {"error": "서고가 설정되지 않았습니다."},
            status_code=500,
        )
    try:
        return get_library_info(_library_path)
    except FileNotFoundError:
        return JSONResponse(
            {"error": f"서고를 찾을 수 없습니다: {_library_path}"},
            status_code=404,
        )


@router.post("/api/library/switch")
async def api_switch_library(body: SwitchLibraryRequest):
    """서고를 전환한다.

    목적: 런타임에 서고 경로를 변경한다.
    입력: { "path": "/abs/path/to/library" }
    출력: { "ok": true, "library_path": "..." }
    에러: 경로가 유효한 서고가 아니면 400.
    """
    from pathlib import Path as _Path
    target = _Path(body.path).resolve()

    if not target.exists():
        return JSONResponse(
            {"error": f"경로가 존재하지 않습니다: {target}"},
            status_code=400,
        )
    if not (target / "library_manifest.json").exists():
        return JSONResponse(
            {"error": f"유효한 서고가 아닙니다 (library_manifest.json 없음): {target}"},
            status_code=400,
        )

    configure_library(str(target))
    return {"ok": True, "library_path": str(get_library_path())}


@router.post("/api/library/init")
async def api_init_library(body: InitLibraryRequest):
    """새 서고를 생성하고 전환한다.

    목적: GUI에서 새 서고를 만들 수 있게 한다.
    입력: { "path": "/abs/path/to/new_library" }
    출력: { "ok": true, "library_path": "..." }
    에러: 이미 서고가 있으면 409.
    """
    from core.library import init_library
    from pathlib import Path as _Path

    target = _Path(body.path).resolve()

    try:
        init_library(target)
    except FileExistsError:
        return JSONResponse(
            {"error": f"이 경로에 이미 서고가 존재합니다: {target}"},
            status_code=409,
        )
    except Exception as e:
        return JSONResponse(
            {"error": f"서고 생성 실패: {e}"},
            status_code=500,
        )

    configure_library(str(target))
    return {"ok": True, "library_path": str(get_library_path())}


@router.get("/api/library/recent")
async def api_recent_libraries():
    """최근 사용한 서고 목록을 반환한다.

    출력: { "libraries": [{path, name, last_used}, ...] }
    """
    from core.app_config import get_recent_libraries
    _library_path = get_library_path()
    return {
        "libraries": get_recent_libraries(),
        "current": str(_library_path) if _library_path else None,
    }


@router.post("/api/library/browse")
async def api_browse_folder():
    """네이티브 폴더 선택 대화상자를 열고 선택된 경로를 반환한다.

    목적: 사용자가 경로를 직접 타이핑하지 않고 폴더를 선택할 수 있게 한다.
    출력: { "path": "..." } 또는 취소 시 { "cancelled": true }
    """
    loop = asyncio.get_event_loop()
    path = await loop.run_in_executor(_tk_executor, _open_folder_dialog)
    if not path:
        return {"cancelled": True}
    return {"path": path}


@router.get("/api/library/git-health")
async def api_git_health():
    """서고 내 Git 저장소의 .git 오염 상태를 검사한다.

    목적: 수동으로 .git/ 파일 오염 여부를 점검하고 수리할 수 있다.
    출력: { contaminated: [...], repaired: [...] }
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse(
            {"error": "서고가 설정되지 않았습니다."},
            status_code=500,
        )

    contaminated = check_git_health(_library_path)
    repaired = []

    for item in contaminated:
        result = repair_git_contamination(item["repo_path"])
        repaired.append({
            "repo_id": item["repo_id"],
            "repo_type": item["repo_type"],
            "contaminated_files": len(item["contaminated_files"]),
            "repaired": result["repaired"],
            "method": result["method"],
            "error": result["error"],
        })

    return {
        "contaminated_count": len(contaminated),
        "repaired": repaired,
    }


@router.get("/api/settings")
async def api_get_settings():
    """현재 서고 설정 정보를 반환한다.

    서고 경로, 원본/해석 저장소의 원격 URL을 포함한다.
    """
    _library_path = get_library_path()

    info = {
        "library_path": str(_library_path) if _library_path else None,
        "documents": [],
        "interpretations": [],
    }

    if _library_path is None:
        return info

    # 원본 저장소의 원격 URL 수집
    doc_dir = _library_path / "documents"
    if doc_dir.exists():
        for d in sorted(doc_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            remote_url = _get_git_remote(d)
            info["documents"].append({
                "id": d.name,
                "path": str(d),
                "remote_url": remote_url,
            })

    # 해석 저장소의 원격 URL 수집
    interp_dir = _library_path / "interpretations"
    if interp_dir.exists():
        for d in sorted(interp_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            remote_url = _get_git_remote(d)
            info["interpretations"].append({
                "id": d.name,
                "path": str(d),
                "remote_url": remote_url,
            })

    # 백업 경로 및 백업 정보 포함
    from core.app_config import get_backup_path
    from core.backup import get_backup_info
    bp = get_backup_path()
    info["backup_path"] = bp
    info["backup_info"] = get_backup_info(bp) if bp else None

    return info


# ── 백업/복원 API ─────────────────────────────────────

@router.post("/api/settings/backup-path")
async def api_set_backup_path(body: BackupPathRequest):
    """백업 폴더 경로를 설정한다.

    구글 드라이브 동기화 폴더를 지정하면 자동으로 클라우드에 동기화된다.
    """
    from core.app_config import set_backup_path
    bp = Path(body.path)
    if not bp.exists():
        return JSONResponse(
            {"error": f"폴더가 존재하지 않습니다: {body.path}"},
            status_code=400,
        )
    if not bp.is_dir():
        return JSONResponse(
            {"error": f"폴더가 아닙니다: {body.path}"},
            status_code=400,
        )
    set_backup_path(body.path)
    return {"backup_path": str(bp.resolve())}


@router.post("/api/library/backup")
async def api_backup_library():
    """서고를 백업 경로에 복사한다.

    .git/ 디렉토리는 제외하고 폴더 그대로 복사한다.
    백업 경로가 미설정이면 에러를 반환한다.
    """
    from core.app_config import get_backup_path
    from core.backup import backup_library

    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse(
            {"error": "서고가 설정되지 않았습니다."},
            status_code=500,
        )

    bp = get_backup_path()
    if not bp:
        return JSONResponse(
            {"error": "백업 경로가 설정되지 않았습니다.\n→ 설정에서 백업 폴더를 먼저 지정하세요."},
            status_code=400,
        )

    result = backup_library(_library_path, bp)
    if not result["success"]:
        return JSONResponse(
            {"error": f"백업 실패: {result['error']}"},
            status_code=500,
        )

    return result


@router.post("/api/library/restore")
async def api_restore_library(body: RestoreRequest):
    """백업에서 서고를 복원한다.

    새 경로에 서고를 복원하고 git 저장소를 재초기화한다.
    """
    from core.backup import restore_from_backup

    result = restore_from_backup(body.backup_path, body.restore_path)
    if not result["success"]:
        return JSONResponse(
            {"error": f"복원 실패: {result['error']}"},
            status_code=500,
        )

    return result


@router.post("/api/settings/remote")
async def api_set_remote(body: SetRemoteRequest):
    """원본/해석 저장소의 원격 URL을 설정한다."""
    repo_dir = _resolve_repo_path(body.repo_type, body.repo_id)
    if repo_dir is None:
        return JSONResponse(
            {"error": "저장소 유형 또는 ID가 올바르지 않습니다."},
            status_code=400,
        )
    if not repo_dir.exists():
        return JSONResponse(
            {"error": f"저장소를 찾을 수 없습니다: {body.repo_type}/{body.repo_id}"},
            status_code=404,
        )

    git_dir = repo_dir / ".git"
    if not git_dir.exists():
        return JSONResponse(
            {"error": f"Git 저장소가 아닙니다: {body.repo_type}/{body.repo_id}"},
            status_code=400,
        )

    try:
        # 기존 origin 제거 (있으면)
        subprocess.run(
            ["git", "remote", "remove", "origin"],
            cwd=str(repo_dir), capture_output=True,
        )
        # 새 origin 추가
        result = subprocess.run(
            ["git", "remote", "add", "origin", body.remote_url],
            cwd=str(repo_dir), capture_output=True, text=True,
        )
        if result.returncode != 0:
            return JSONResponse(
                {"error": f"원격 설정 실패: {result.stderr}"},
                status_code=500,
            )
        return {"status": "ok", "remote_url": body.remote_url}
    except Exception as e:
        return JSONResponse({"error": f"원격 설정 실패: {e}"}, status_code=500)


@router.post("/api/settings/git-sync")
async def api_git_sync(body: GitPushPullRequest):
    """원본/해석 저장소를 원격에 push 또는 pull한다."""
    repo_dir = _resolve_repo_path(body.repo_type, body.repo_id)
    if repo_dir is None:
        return JSONResponse(
            {"error": "저장소 유형 또는 ID가 올바르지 않습니다."},
            status_code=400,
        )
    if not repo_dir.exists():
        return JSONResponse(
            {"error": f"저장소를 찾을 수 없습니다: {body.repo_type}/{body.repo_id}"},
            status_code=404,
        )

    if body.action not in ("push", "pull"):
        return JSONResponse({"error": "action은 push 또는 pull이어야 합니다."}, status_code=400)

    # Push 전 안전검사: 작업트리에 .git 내부 파일이 추적되면
    # 저장소 메타데이터까지 원격에 밀려 대용량/비정상 push가 발생한다.
    # 이 경우 branch(main/master) 문제가 아니라 저장소 상태 문제이므로 즉시 차단한다.
    if body.action == "push":
        try:
            ls_files = subprocess.run(
                ["git", "ls-files"],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                timeout=20,
            )
            tracked = ls_files.stdout.splitlines() if ls_files.returncode == 0 else []
            tracked_git_internal = [
                p for p in tracked if p.startswith(".git/") or p.startswith("./.git/")
            ]

            if tracked_git_internal:
                sample = "\n".join(tracked_git_internal[:5])
                return JSONResponse(
                    {
                        "error": "push 차단: 저장소 내부 .git 파일이 추적되고 있습니다.",
                        "detail": f"추적 예시:\n{sample}",
                        "hint": (
                            "branch(main/master) 문제가 아닙니다. "
                            "해당 저장소에서 `git rm -r --cached .git` 후 커밋하고 다시 push 하세요. "
                            "필요하면 저장소를 새로 초기화하는 것이 가장 안전합니다."
                        ),
                    },
                    status_code=400,
                )
        except Exception:
            # 안전검사 실패는 치명 오류로 보지 않고 기존 흐름을 유지한다.
            pass

    def _run_git_sync(cmd: list[str], timeout_sec: int = 180):
        """git 명령을 실행하고 (성공여부, stdout, stderr, returncode)를 반환한다."""
        proc = subprocess.run(
            cmd,
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        return proc.returncode == 0, proc.stdout.strip(), proc.stderr.strip(), proc.returncode

    try:
        # 현재 브랜치 이름
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo_dir), capture_output=True, text=True,
        )
        branch = branch_result.stdout.strip() or "master"

        if body.action == "push":
            success, out, err, code = _run_git_sync(
                ["git", "push", "-u", "origin", branch],
                timeout_sec=180,
            )

            # Windows/HTTPS에서 자주 발생하는 RPC/HTTP 500 계열 오류는
            # HTTP/1.1 강제 + postBuffer 확장으로 1회 재시도한다.
            retry_used = False
            retry_reason = ""
            rpc_http_500 = (
                ("RPC failed" in err)
                or ("The requested URL returned error: 500" in err)
                or ("send-pack: unexpected disconnect while reading sideband packet" in err)
                or ("the remote end hung up unexpectedly" in err)
            )

            if (not success) and rpc_http_500:
                retry_used = True
                retry_reason = "원격 HTTP 500/RPC 실패 감지"
                success, out, err, code = _run_git_sync(
                    [
                        "git",
                        "-c",
                        "http.version=HTTP/1.1",
                        "-c",
                        "http.postBuffer=524288000",
                        "push",
                        "-u",
                        "origin",
                        branch,
                    ],
                    timeout_sec=300,
                )

            if not success:
                hint = (
                    "원격 서버(또는 네트워크)에서 연결을 끊었습니다. "
                    "잠시 후 재시도하거나, 원격 URL/권한(PAT)과 저장소 용량 제한을 확인하세요."
                )
                return JSONResponse(
                    {
                        "error": f"push 실패 (exit={code})",
                        "detail": err or out or "알 수 없는 git 오류",
                        "hint": hint,
                        "retried": retry_used,
                        "retry_reason": retry_reason,
                    },
                    status_code=500,
                )

            return {
                "status": "ok",
                "action": body.action,
                "output": out or "성공",
                "retried": retry_used,
                "retry_reason": retry_reason,
            }
        else:
            success, out, err, code = _run_git_sync(
                ["git", "pull", "origin", branch],
                timeout_sec=180,
            )
            if not success:
                return JSONResponse(
                    {
                        "error": f"pull 실패 (exit={code})",
                        "detail": err or out or "알 수 없는 git 오류",
                        "hint": "원격 URL/브랜치/인증 상태를 확인하세요.",
                    },
                    status_code=500,
                )
            return {
                "status": "ok",
                "action": body.action,
                "output": out or "성공",
            }
    except subprocess.TimeoutExpired:
        return JSONResponse(
            {
                "error": "git 동기화 타임아웃",
                "detail": "명령 실행 시간이 제한을 초과했습니다.",
                "hint": "네트워크 상태를 확인하고 다시 시도하세요.",
            },
            status_code=500,
        )
    except Exception as e:
        return JSONResponse(
            {
                "error": f"{body.action} 실패",
                "detail": str(e),
                "hint": "로컬 git 설정과 원격 접근 권한을 확인하세요.",
            },
            status_code=500,
        )


# ── 휴지통 API ─────────────────────────────────────

@router.get("/api/trash")
async def api_trash():
    """휴지통 목록을 반환한다.

    목적: .trash/ 폴더 안의 삭제된 문헌·해석 저장소 목록을 조회한다.
    출력: {"documents": [...], "interpretations": [...]}
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    return list_trash(_library_path)


@router.post("/api/trash/{trash_type}/{trash_name}/restore")
async def api_restore_from_trash(trash_type: str, trash_name: str):
    """휴지통에서 문헌 또는 해석 저장소를 복원한다.

    목적: .trash/에 있는 항목을 원래 위치로 되돌린다.
    입력:
        trash_type -- "documents" 또는 "interpretations".
        trash_name -- 휴지통 내 폴더명 (예: "20260220T153000_kameda_monggu").
    출력: {"status": "restored", "original_id": "..."}.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    if trash_type not in ("documents", "interpretations"):
        return JSONResponse(
            {"error": f"올바르지 않은 유형: {trash_type}. 'documents' 또는 'interpretations'만 가능합니다."},
            status_code=400,
        )

    try:
        original_id = restore_from_trash(_library_path, trash_type, trash_name)
        return {"status": "restored", "original_id": original_id}
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except FileExistsError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
