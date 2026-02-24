"""버전 관리 라우터.

Git 그래프, 커밋 미리보기, 되돌리기, JSON 스냅샷 내보내기/가져오기,
해석 저장소 폴더 가져오기 등 버전·이력 관련 API를 모아둔다.

왜 분리하는가:
    server.py가 너무 길어져 유지보수가 어렵다.
    버전 관리 기능은 독립적이므로 별도 라우터로 분리한다.

API 엔드포인트:
    GET  /api/interpretations/{interp_id}/git-graph
    GET  /api/repos/{repo_type}/{repo_id}/commits/{commit_hash}/files
    GET  /api/repos/{repo_type}/{repo_id}/commits/{commit_hash}/files/{file_path:path}
    POST /api/repos/{repo_type}/{repo_id}/revert
    GET  /api/interpretations/{interp_id}/export/json
    POST /api/import/json
    POST /api/import/interpretation-folder
"""

import io
import json
import logging
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from core.git_graph import (
    get_git_graph_data,
    get_commit_file_list,
    get_commit_file_content,
    revert_to_commit,
)
from core.interpretation import _append_based_on_trailer
from core.snapshot import build_snapshot, create_work_from_snapshot, detect_imported_layers
from core.snapshot_validator import validate_snapshot

from app._state import get_library_path, _resolve_repo_path

logger = logging.getLogger(__name__)

router = APIRouter(tags=["version"])


# ── Pydantic 모델 ─────────────────────────────────


class RevertRequest(BaseModel):
    """되돌리기 요청 바디."""
    target_hash: str
    message: str | None = None


# ──────────────────────────────────────
# Phase 12-2: 사다리형 이분 그래프 API
# ──────────────────────────────────────


@router.get("/api/interpretations/{interp_id}/git-graph")
async def api_git_graph(
    interp_id: str,
    original_branch: str = Query("auto", description="원본 저장소 브랜치"),
    interp_branch: str = Query("auto", description="해석 저장소 브랜치"),
    limit: int = Query(50, ge=1, le=200, description="각 저장소별 최대 커밋 수"),
    offset: int = Query(0, ge=0, description="페이지네이션 오프셋"),
    pushed_only: bool = Query(False, description="push된 커밋만 반환"),
):
    """사다리형 이분 그래프 데이터를 반환한다.

    목적: 원본 저장소(L1~L4)와 해석 저장소(L5~L7)의 커밋을
        나란히 보여주는 그래프 데이터를 생성한다.
    입력:
        interp_id — 해석 저장소 ID.
        original_branch — 원본 저장소 브랜치 이름.
        interp_branch — 해석 저장소 브랜치 이름.
        limit — 각 저장소별 최대 커밋 수.
        offset — 페이지네이션 오프셋.
    출력: {original, interpretation, links, pagination} 데이터.

    왜 이렇게 하는가:
        해석 저장소의 manifest.json에서 source_document_id를 읽어
        원본 저장소 경로를 자동으로 결정한다.
        사용자가 doc_id를 별도로 지정할 필요가 없다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    manifest_path = interp_path / "manifest.json"

    if not manifest_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    doc_id = manifest.get("source_document_id", "")

    if not doc_id:
        return JSONResponse(
            {"error": "해석 저장소의 manifest에 source_document_id가 없습니다."},
            status_code=400,
        )

    data = get_git_graph_data(
        library_path=_library_path,
        doc_id=doc_id,
        interp_id=interp_id,
        original_branch=original_branch,
        interp_branch=interp_branch,
        limit=limit,
        offset=offset,
        pushed_only=pushed_only,
    )

    return data


# ──────────────────────────────────────
# Phase 12-2: 버전 미리보기 + 되돌리기 API
# ──────────────────────────────────────


@router.get("/api/repos/{repo_type}/{repo_id}/commits/{commit_hash}/files")
async def api_commit_files(repo_type: str, repo_id: str, commit_hash: str):
    """특정 저장 시점의 파일 목록을 반환한다.

    목적: 연구자가 과거 시점에 어떤 파일이 있었는지 확인한다.
    입력:
        repo_type — "documents" 또는 "interpretations".
        repo_id — 문헌 ID 또는 해석 저장소 ID.
        commit_hash — 대상 커밋 해시.
    출력: {commit_hash, short_hash, message, timestamp, files: [{path, size}]}.
    """
    repo_path = _resolve_repo_path(repo_type, repo_id)
    if repo_path is None:
        return JSONResponse(
            {"error": "서고가 설정되지 않았거나, 저장소 유형이 올바르지 않습니다."},
            status_code=400,
        )

    if not repo_path.exists():
        return JSONResponse(
            {"error": f"저장소를 찾을 수 없습니다: {repo_id}"},
            status_code=404,
        )

    result = get_commit_file_list(repo_path, commit_hash)
    if "error" in result:
        return JSONResponse(result, status_code=404)
    return result


@router.get("/api/repos/{repo_type}/{repo_id}/commits/{commit_hash}/files/{file_path:path}")
async def api_commit_file_content(
    repo_type: str, repo_id: str, commit_hash: str, file_path: str
):
    """특정 저장 시점의 파일 내용을 반환한다.

    목적: 연구자가 과거 시점의 특정 파일 내용을 읽기 전용으로 확인한다.
    입력:
        repo_type — "documents" 또는 "interpretations".
        repo_id — 문헌 ID 또는 해석 저장소 ID.
        commit_hash — 대상 커밋 해시.
        file_path — 저장소 내 상대 파일 경로.
    출력: {commit_hash, file_path, content, is_binary}.
    """
    repo_path = _resolve_repo_path(repo_type, repo_id)
    if repo_path is None:
        return JSONResponse(
            {"error": "서고가 설정되지 않았거나, 저장소 유형이 올바르지 않습니다."},
            status_code=400,
        )

    if not repo_path.exists():
        return JSONResponse(
            {"error": f"저장소를 찾을 수 없습니다: {repo_id}"},
            status_code=404,
        )

    result = get_commit_file_content(repo_path, commit_hash, file_path)
    if "error" in result and "content" not in result:
        return JSONResponse(result, status_code=404)
    return result


@router.post("/api/repos/{repo_type}/{repo_id}/revert")
async def api_revert_to_commit(repo_type: str, repo_id: str, body: RevertRequest):
    """특정 저장 시점으로 되돌리는 새 커밋을 생성한다.

    목적: 연구자가 "이 버전으로 되돌리기"를 클릭했을 때,
        해당 시점의 파일 상태로 복원하고 새 커밋으로 기록한다.
        기존 이력은 모두 보존된다.
    입력:
        repo_type — "documents" 또는 "interpretations".
        repo_id — 문헌 ID 또는 해석 저장소 ID.
        body.target_hash — 복원할 커밋 해시.
        body.message — 커밋 메시지 (선택).
    출력: {reverted, new_commit_hash, message, target_hash}.
    """
    repo_path = _resolve_repo_path(repo_type, repo_id)
    if repo_path is None:
        return JSONResponse(
            {"error": "서고가 설정되지 않았거나, 저장소 유형이 올바르지 않습니다."},
            status_code=400,
        )

    if not repo_path.exists():
        return JSONResponse(
            {"error": f"저장소를 찾을 수 없습니다: {repo_id}"},
            status_code=404,
        )

    # 커밋 메시지 결정
    commit_message = body.message

    # 해석 저장소인 경우 Based-On-Original trailer를 추가한다
    if repo_type == "interpretations":
        short_hash = body.target_hash[:7]
        if commit_message is None:
            commit_message = f"revert: {short_hash} 시점으로 되돌리기"
        commit_message = _append_based_on_trailer(repo_path, commit_message)

    result = revert_to_commit(repo_path, body.target_hash, commit_message)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return result


# ──────────────────────────────────────
# Phase 12-3: JSON 스냅샷 API
# ──────────────────────────────────────


@router.get("/api/interpretations/{interp_id}/export/json")
async def api_export_json(interp_id: str):
    """해석 저장소 + 원본 전체를 JSON 스냅샷으로 내보낸다.

    목적: 백업, 공유, 다른 환경 이동용 단일 JSON 파일 생성.
    입력: interp_id — 해석 저장소 ID (manifest에서 원본 문헌 자동 결정).
    출력: JSON 파일 다운로드 (Content-Disposition: attachment).

    왜 이렇게 하는가:
        Git 히스토리 없이 현재 HEAD 상태만 직렬화하면
        파일 크기가 작고 복원 시 충돌이 없다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    manifest_path = interp_path / "manifest.json"

    if not manifest_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    doc_id = manifest.get("source_document_id", "")

    if not doc_id:
        return JSONResponse(
            {"error": "manifest에 source_document_id가 없습니다."},
            status_code=400,
        )

    snapshot = build_snapshot(_library_path, doc_id, interp_id)

    # JSON 파일 다운로드
    title = snapshot.get("work", {}).get("title", interp_id)
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{title}_{date_str}.json"

    content = json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/import/json")
async def api_import_json(request: Request):
    """JSON 스냅샷에서 새 Work(문헌 + 해석 저장소)를 생성한다.

    목적: 다른 환경에서 export한 스냅샷을 현재 서고에 import.
    입력: Request body에 JSON 직접 전송 (Content-Type: application/json).
    출력: {status, doc_id, interp_id, title, layers_imported, warnings}.

    왜 이렇게 하는가:
        항상 "새 Work 생성"으로 처리하여 기존 데이터에 영향을 주지 않는다.
        같은 스냅샷을 여러 번 import해도 각각 독립된 Work가 된다.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    try:
        body = await request.body()
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return JSONResponse(
            {"error": f"JSON 파싱 실패: {e}"},
            status_code=400,
        )

    # 검증
    errors, warnings = validate_snapshot(data)
    if errors:
        return JSONResponse(
            {
                "status": "error",
                "message": "스냅샷 검증 실패",
                "errors": errors,
                "warnings": warnings,
            },
            status_code=422,
        )

    # 새 Work 생성
    result = create_work_from_snapshot(_library_path, data)

    return {
        "status": "success",
        "doc_id": result["doc_id"],
        "interp_id": result["interp_id"],
        "title": result["title"],
        "layers_imported": detect_imported_layers(data),
        "warnings": result["warnings"] + warnings,
    }


@router.post("/api/import/interpretation-folder")
async def api_import_interpretation_folder(files: list[UploadFile] = File(...)):
    """기존 해석 저장소 폴더를 현재 서고로 가져온다.

    목적:
        JSON 스냅샷을 새로 만들지 않고, 기존 해석 저장소 디렉토리 자체를
        업로드하여 interpretations/ 하위에 등록한다.

    입력:
        multipart/form-data의 files[] (디렉토리 업로드 결과).
        파일 경로는 filename(webkitRelativePath)로 전달된다.
        overwrite=true이면 기존 저장소를 .trash로 이동 후 덮어쓴다.

    출력:
        {status, interp_id, source_document_id, file_count, skipped_count}.
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    if not files:
        return JSONResponse(
            {"error": "업로드된 파일이 없습니다. 해석 저장소 폴더를 선택하세요."},
            status_code=400,
        )

    normalized_files: list[tuple[UploadFile, str]] = []
    for uploaded in files:
        raw_name = (uploaded.filename or "").replace("\\", "/").strip().strip("/")
        if not raw_name:
            continue
        normalized_files.append((uploaded, raw_name))

    if not normalized_files:
        return JSONResponse(
            {"error": "유효한 파일 경로를 찾지 못했습니다."},
            status_code=400,
        )

    # 폴더 루트 접두사(예: interp_xxx/) 추정
    root_candidates = {name.split("/", 1)[0] for _, name in normalized_files if "/" in name}
    root_prefix = next(iter(root_candidates)) if len(root_candidates) == 1 else ""

    manifest_file: UploadFile | None = None
    for uploaded, name in normalized_files:
        if name.endswith("/manifest.json") or name == "manifest.json":
            manifest_file = uploaded
            break

    if manifest_file is None:
        return JSONResponse(
            {"error": "manifest.json이 없습니다. 해석 저장소 루트 폴더를 선택하세요."},
            status_code=400,
        )

    try:
        manifest_raw = (await manifest_file.read()).decode("utf-8")
        manifest = json.loads(manifest_raw)
    except UnicodeDecodeError:
        return JSONResponse(
            {"error": "manifest.json 인코딩이 UTF-8이 아닙니다."},
            status_code=400,
        )
    except json.JSONDecodeError as e:
        return JSONResponse(
            {"error": f"manifest.json 파싱 실패: {e}"},
            status_code=400,
        )

    interp_id = manifest.get("interpretation_id")
    source_document_id = manifest.get("source_document_id")

    if not isinstance(interp_id, str) or not interp_id:
        return JSONResponse(
            {"error": "manifest.json의 interpretation_id가 누락되었습니다."},
            status_code=400,
        )
    if not re.match(r"^[a-z][a-z0-9_]{0,63}$", interp_id):
        return JSONResponse(
            {
                "error": (
                    f"해석 저장소 ID 형식이 올바르지 않습니다: '{interp_id}'\n"
                    "→ 해결: 영문 소문자로 시작하고, 소문자·숫자·밑줄만 사용하세요."
                )
            },
            status_code=400,
        )

    if not isinstance(source_document_id, str) or not source_document_id:
        return JSONResponse(
            {"error": "manifest.json의 source_document_id가 누락되었습니다."},
            status_code=400,
        )

    source_manifest = _library_path / "documents" / source_document_id / "manifest.json"
    if not source_manifest.exists():
        return JSONResponse(
            {
                "error": (
                    f"원본 문헌을 찾을 수 없습니다: {source_document_id}\n"
                    "→ 해결: 같은 서고에 해당 문헌을 먼저 준비한 뒤 다시 시도하세요."
                )
            },
            status_code=404,
        )

    target_interp_path = _library_path / "interpretations" / interp_id

    # ── 이미 존재하면: 파일 건드리지 않고 등록만 확인하고 끝 ──
    if target_interp_path.exists():
        _register_interp_in_library(
            _library_path, interp_id, source_document_id, manifest.get("title"),
        )
        return {
            "status": "success",
            "interp_id": interp_id,
            "source_document_id": source_document_id,
            "file_count": 0,
            "skipped_count": 0,
            "message": "이미 존재하는 해석 저장소를 불러왔습니다.",
        }

    # ── 새로 가져오기: 파일 쓰기 ──
    written_count = 0
    skipped_count = 0

    try:
        target_interp_path.mkdir(parents=True, exist_ok=False)

        for uploaded, original_name in normalized_files:
            rel_name = original_name
            if root_prefix and rel_name.startswith(root_prefix + "/"):
                rel_name = rel_name[len(root_prefix) + 1:]

            if not rel_name:
                continue

            posix_path = PurePosixPath(rel_name)
            if posix_path.is_absolute() or ".." in posix_path.parts:
                raise ValueError(f"잘못된 파일 경로가 포함되어 있습니다: {original_name}")

            # 안전 규칙: .git 메타데이터는 가져오지 않는다.
            if ".git" in posix_path.parts:
                skipped_count += 1
                continue

            content = await uploaded.read()
            target_file = target_interp_path.joinpath(*posix_path.parts)
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_bytes(content)
            written_count += 1

        # manifest는 파싱 성공본으로 최종 저장 (손상 업로드 방지)
        target_manifest = target_interp_path / "manifest.json"
        target_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # dependency.json이 없는 구버전/부분 폴더를 위해 최소값 생성
        dependency_path = target_interp_path / "dependency.json"
        if not dependency_path.exists():
            fallback_dependency = {
                "interpretation_id": interp_id,
                "interpreter": manifest.get("interpreter", {"type": "human", "name": None}),
                "source": {
                    "document_id": source_document_id,
                    "remote": None,
                    "base_commit": "no_git",
                },
                "tracked_files": [],
                "last_checked": datetime.now(timezone.utc).isoformat(),
                "dependency_status": "current",
            }
            dependency_path.write_text(
                json.dumps(fallback_dependency, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        # .gitignore 자동 보강
        gitignore_path = target_interp_path / ".gitignore"
        if not gitignore_path.exists():
            gitignore_path.write_text(
                (
                    "# 안전 규칙: 저장소 내부 Git 메타데이터는 절대 추적하지 않는다.\n"
                    ".git\n"
                    ".git/\n"
                    "**/.git\n"
                    "**/.git/**\n"
                    "\n"
                    "# 임시/캐시 파일\n"
                    "__pycache__/\n"
                    "*.py[cod]\n"
                    "*.tmp\n"
                    "*.temp\n"
                    "\n"
                    "# 에디터/OS 잡파일\n"
                    ".DS_Store\n"
                    "Thumbs.db\n"
                    ".vscode/\n"
                    ".idea/\n"
                ),
                encoding="utf-8",
            )

        # Git 저장소가 없으면 초기화
        if not (target_interp_path / ".git").exists():
            init_proc = subprocess.run(
                ["git", "init"],
                cwd=str(target_interp_path),
                capture_output=True,
                text=True,
            )
            if init_proc.returncode == 0:
                subprocess.run(["git", "add", "."], cwd=str(target_interp_path), capture_output=True)
                subprocess.run(
                    ["git", "commit", "-m", f"feat: 해석 저장소 폴더 가져오기 — {interp_id}"],
                    cwd=str(target_interp_path),
                    capture_output=True,
                    text=True,
                )

        _register_interp_in_library(
            _library_path, interp_id, source_document_id, manifest.get("title"),
        )

        return {
            "status": "success",
            "interp_id": interp_id,
            "source_document_id": source_document_id,
            "file_count": written_count,
            "skipped_count": skipped_count,
        }

    except ValueError as e:
        shutil.rmtree(target_interp_path, ignore_errors=True)
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        shutil.rmtree(target_interp_path, ignore_errors=True)
        return JSONResponse(
            {"error": f"해석 저장소 폴더 가져오기 실패: {e}"},
            status_code=500,
        )


# ── 헬퍼 함수 ─────────────────────────────────


def _register_interp_in_library(
    library_path: Path, interp_id: str, source_document_id: str, title: str | None,
):
    """library_manifest.json에 해석 저장소 항목을 등록한다 (이미 있으면 무시)."""
    manifest_path = library_path / "library_manifest.json"
    try:
        if manifest_path.exists():
            lib_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        else:
            lib_manifest = {"documents": [], "interpretations": []}

        interps = lib_manifest.setdefault("interpretations", [])
        if not any(x.get("interpretation_id") == interp_id for x in interps):
            interps.append({
                "interpretation_id": interp_id,
                "source_document_id": source_document_id,
                "title": title,
                "path": f"interpretations/{interp_id}",
            })
            manifest_path.write_text(
                json.dumps(lib_manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    except Exception:
        pass
