"""웹 앱 서버.

FastAPI 기반. 서고 데이터를 API로 제공하고 정적 파일(HTML/CSS/JS)을 서빙한다.
D-001: 이 플랫폼의 주 인터페이스는 GUI이며, CLI는 보조 도구다.

API 엔드포인트:
    GET /            → index.html (워크스페이스)
    GET /api/library → 서고 정보
    GET /api/documents → 문헌 목록
    GET /api/documents/{doc_id} → 특정 문헌 정보
    GET /api/documents/{doc_id}/pdf/{part_id} → PDF 파일 서빙
    GET /api/documents/{doc_id}/pages/{page_num}/text → 페이지 텍스트 조회
    PUT /api/documents/{doc_id}/pages/{page_num}/text → 페이지 텍스트 저장
    GET /api/documents/{doc_id}/bibliography → 서지정보 조회
    PUT /api/documents/{doc_id}/bibliography → 서지정보 저장
    GET /api/documents/{doc_id}/pages/{page_num}/corrections → 교정 기록 조회
    PUT /api/documents/{doc_id}/pages/{page_num}/corrections → 교정 기록 저장 (자동 git commit)
    GET /api/documents/{doc_id}/git/log → git 커밋 이력
    GET /api/documents/{doc_id}/git/diff/{commit_hash} → 커밋 diff
    GET /api/parsers → 등록된 파서 목록
    POST /api/parsers/{parser_id}/search → 외부 소스 검색
    POST /api/parsers/{parser_id}/map → 검색 결과를 bibliography 형식으로 매핑

    --- Phase 7: 해석 저장소 API ---
    POST /api/interpretations → 해석 저장소 생성
    GET  /api/interpretations → 해석 저장소 목록
    GET  /api/interpretations/{interp_id} → 해석 저장소 상세
    GET  /api/interpretations/{interp_id}/dependency → 의존 변경 확인
    POST /api/interpretations/{interp_id}/dependency/acknowledge → 변경 인지
    POST /api/interpretations/{interp_id}/dependency/update-base → 기반 업데이트
    GET  /api/interpretations/{interp_id}/layers/{layer}/{sub_type}/pages/{page_num} → 층 내용 조회
    PUT  /api/interpretations/{interp_id}/layers/{layer}/{sub_type}/pages/{page_num} → 층 내용 저장
    GET  /api/interpretations/{interp_id}/git/log → git 이력

    --- Phase 10: URL → 문헌 자동 생성 API ---
    POST /api/documents/preview-from-url → URL에서 서지정보 + 에셋 미리보기
    POST /api/documents/create-from-url → URL에서 문헌 자동 생성

    --- Phase 10-2: LLM 4단 폴백 아키텍처 API ---
    GET  /api/llm/status → 각 provider 가용 상태
    GET  /api/llm/models → GUI 드롭다운용 모델 목록
    GET  /api/llm/usage  → 이번 달 사용량 요약
    POST /api/llm/analyze-layout/{doc_id}/{page} → 레이아웃 분석 (Draft 반환)
    POST /api/llm/compare-layout/{doc_id}/{page} → 레이아웃 분석 비교
    POST /api/llm/drafts/{draft_id}/review → Draft 검토 (accept/modify/reject)

    --- Phase 10-1: OCR 엔진 연동 API ---
    GET  /api/ocr/engines → 등록된 OCR 엔진 목록 + 사용 가능 여부
    POST /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr → OCR 실행
    GET  /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr → OCR 결과 조회
    DELETE /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr → OCR 결과 삭제(.trash 이동)
    POST /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr/{block_id} → 단일 블록 재실행

    --- Phase 10-3: 정렬 엔진 API ---
    POST /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/alignment → 대조 실행
    GET  /api/alignment/variant-dict → 이체자 사전 조회
    POST /api/alignment/variant-dict → 이체자 쌍 추가

    --- Phase 11-1: L5 표점/현토 API ---
    GET  /api/interpretations/{interp_id}/pages/{page}/punctuation → 표점 조회
    PUT  /api/interpretations/{interp_id}/pages/{page}/punctuation → 표점 저장
    POST /api/interpretations/{interp_id}/pages/{page}/punctuation/{block_id}/marks → 표점 추가
    DELETE /api/interpretations/{interp_id}/pages/{page}/punctuation/{block_id}/marks/{id} → 표점 삭제
    GET  /api/interpretations/{interp_id}/pages/{page}/punctuation/{block_id}/preview → 표점 미리보기
    GET  /api/interpretations/{interp_id}/pages/{page}/hyeonto → 현토 조회
    PUT  /api/interpretations/{interp_id}/pages/{page}/hyeonto → 현토 저장
    POST /api/interpretations/{interp_id}/pages/{page}/hyeonto/{block_id}/annotations → 현토 추가
    DELETE /api/interpretations/{interp_id}/pages/{page}/hyeonto/{block_id}/annotations/{id} → 현토 삭제
    GET  /api/interpretations/{interp_id}/pages/{page}/hyeonto/{block_id}/preview → 현토 미리보기

    --- Phase 11-2: L6 번역 API ---
    GET  /api/interpretations/{interp_id}/pages/{page}/translation → 번역 조회
    GET  /api/interpretations/{interp_id}/pages/{page}/translation/status → 상태 요약
    POST /api/interpretations/{interp_id}/pages/{page}/translation → 수동 번역 입력
    PUT  /api/interpretations/{interp_id}/pages/{page}/translation/{id} → 번역 수정
    POST /api/interpretations/{interp_id}/pages/{page}/translation/{id}/commit → Draft 확정
    DELETE /api/interpretations/{interp_id}/pages/{page}/translation/{id} → 번역 삭제

    --- Phase 11-3: L7 주석 API ---
    GET  /api/interpretations/{interp_id}/pages/{page}/annotations → 주석 조회 (?type= 필터)
    GET  /api/interpretations/{interp_id}/pages/{page}/annotations/summary → 주석 요약
    POST /api/interpretations/{interp_id}/pages/{page}/annotations/{block_id} → 수동 주석 추가
    PUT  /api/interpretations/{interp_id}/pages/{page}/annotations/{block_id}/{ann_id} → 주석 수정
    DELETE /api/interpretations/{interp_id}/pages/{page}/annotations/{block_id}/{ann_id} → 주석 삭제
    POST /api/interpretations/{interp_id}/pages/{page}/annotations/{block_id}/{ann_id}/commit → Draft 확정
    POST /api/interpretations/{interp_id}/pages/{page}/annotations/commit-all → 일괄 확정
    GET  /api/annotation-types → 주석 유형 목록
    POST /api/annotation-types → 사용자 정의 유형 추가
    DELETE /api/annotation-types/{type_id} → 사용자 정의 유형 삭제

    --- Phase 11-4: 사전형 주석 (Dictionary Annotation) API ---
    POST /api/interpretations/{interp_id}/pages/{page}/annotations/generate-stage1 → 1단계 사전 생성 (원문→주석)
    POST /api/interpretations/{interp_id}/pages/{page}/annotations/generate-stage2 → 2단계 사전 보강 (번역→보강)
    POST /api/interpretations/{interp_id}/pages/{page}/annotations/generate-stage3 → 3단계 사전 통합 (원문+번역)
    POST /api/interpretations/{interp_id}/annotations/generate-batch → 일괄 사전 생성
    GET  /api/interpretations/{interp_id}/export/dictionary → 사전 내보내기
    POST /api/interpretations/{interp_id}/export/dictionary/save → 사전 JSON 파일로 저장
    POST /api/interpretations/{interp_id}/import/dictionary → 사전 가져오기
    GET  /api/interpretations/{interp_id}/reference-dicts → 참조 사전 목록
    POST /api/interpretations/{interp_id}/reference-dicts → 참조 사전 등록
    DELETE /api/interpretations/{interp_id}/reference-dicts/{filename} → 참조 사전 삭제
    POST /api/interpretations/{interp_id}/reference-dicts/match → 참조 사전 매칭
    GET  /api/interpretations/{interp_id}/pages/{page}/annotations/translation-changed → 번역 변경 감지

    --- Phase 11-5: 인용 마크 (Citation Mark) API ---
    GET  /api/interpretations/{interp_id}/pages/{page}/citation-marks → 인용 마크 조회
    POST /api/interpretations/{interp_id}/pages/{page}/citation-marks → 인용 마크 추가
    PUT  /api/interpretations/{interp_id}/pages/{page}/citation-marks/{mark_id} → 인용 마크 수정
    DELETE /api/interpretations/{interp_id}/pages/{page}/citation-marks/{mark_id} → 인용 마크 삭제
    GET  /api/interpretations/{interp_id}/citation-marks/all → 전체 인용 마크 목록
    POST /api/interpretations/{interp_id}/pages/{page}/citation-marks/{mark_id}/resolve → 교차 레이어 해석
    POST /api/interpretations/{interp_id}/citation-marks/export → 학술 인용 형식 내보내기

    --- Phase 12-1: Git 그래프 API ---
    GET  /api/interpretations/{interp_id}/git-graph → 사다리형 이분 그래프 데이터

    --- Phase 12-3: JSON 스냅샷 API ---
    GET  /api/interpretations/{interp_id}/export/json → JSON 스냅샷 Export (다운로드)
    POST /api/import/json → JSON 스냅샷 Import (새 Work 생성)
    POST /api/import/interpretation-folder → 기존 해석 저장소 폴더 Import

    --- Phase 8: 코어 스키마 엔티티 API ---
    POST /api/interpretations/{interp_id}/entities → 엔티티 생성
    GET  /api/interpretations/{interp_id}/entities/{entity_type} → 유형별 목록
    GET  /api/interpretations/{interp_id}/entities/{entity_type}/{entity_id} → 단일 조회
    PUT  /api/interpretations/{interp_id}/entities/{entity_type}/{entity_id} → 엔티티 수정
    GET  /api/interpretations/{interp_id}/entities/page/{page_num} → 페이지별 엔티티
    POST /api/interpretations/{interp_id}/entities/text_block/from-source → TextBlock 생성
    POST /api/interpretations/{interp_id}/entities/work/auto-create → Work 자동 생성
    POST /api/interpretations/{interp_id}/entities/tags/{tag_id}/promote → Tag→Concept 승격

    --- 서고 관리 API ---
    POST /api/library/switch                          → 서고 전환
    POST /api/library/init                            → 새 서고 생성
    GET  /api/library/recent                          → 최근 서고 목록

    --- 휴지통 (문헌/해석 저장소 삭제) API ---
    DELETE /api/documents/{doc_id}                    → 문헌을 휴지통으로 이동
    DELETE /api/interpretations/{interp_id}            → 해석 저장소를 휴지통으로 이동
    GET    /api/trash                                  → 휴지통 목록
    POST   /api/trash/{trash_type}/{trash_name}/restore → 휴지통에서 복원
"""

import json
import logging
import os
import sys
import shutil
from datetime import datetime
from pathlib import Path

# src/ 디렉토리를 Python 경로에 추가
_src_dir = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from fastapi import BackgroundTasks, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.library import (
    get_library_info,
    list_documents,
    list_interpretations,
    list_trash,
    restore_from_trash,
    trash_document,
    trash_interpretation,
)
from core.document import (
    create_document_from_hwp,
    create_document_from_url,
    get_bibliography,
    get_corrected_text,
    get_document_info,
    get_git_diff,
    get_git_log,
    get_page_corrections,
    get_page_layout,
    get_page_text,
    get_pdf_path,
    git_commit_document,
    import_hwp_text_to_document,
    list_pages,
    match_hwp_text_to_layout_blocks,
    save_bibliography,
    save_page_corrections,
    save_page_layout,
    save_page_text,
)
from core.interpretation import (
    acknowledge_changes,
    check_dependency,
    create_interpretation,
    get_interp_git_log,
    get_interpretation_info,
    get_layer_content,
    get_page_notes,
    git_commit_interpretation,
    save_layer_content,
    save_page_notes,
    update_base,
)
from core.citation_mark import (
    add_citation_mark,
    export_citations,
    format_citation,
    list_all_citation_marks,
    load_citation_marks,
    remove_citation_mark,
    resolve_citation_context,
    save_citation_marks,
    update_citation_mark,
)
from core.git_graph import get_git_graph_data
from core.snapshot import build_snapshot, create_work_from_snapshot, detect_imported_layers
from core.snapshot_validator import validate_snapshot
from core.entity import (
    auto_create_work,
    create_entity,
    create_textblock_from_source,
    get_entity,
    list_entities,
    list_entities_for_page,
    promote_tag_to_concept,
    update_entity,
)
from core.punctuation import (
    add_mark,
    load_punctuation,
    remove_mark,
    render_punctuated_text,
    save_punctuation,
    split_sentences,
)
from core.hyeonto import (
    add_annotation,
    load_hyeonto,
    remove_annotation,
    render_hyeonto_text,
    save_hyeonto,
)


app = FastAPI(
    title="고전 텍스트 디지털 서고 플랫폼",
    description="사람과 LLM이 함께 고전 텍스트를 읽고 번역하고 연구하는 통합 작업 환경",
    version="0.2.0",
)


class TextSaveRequest(BaseModel):
    """텍스트 저장 요청 본문. PUT /api/documents/{doc_id}/pages/{page_num}/text 에서 사용."""
    text: str


class LayoutSaveRequest(BaseModel):
    """레이아웃 저장 요청 본문. PUT /api/documents/{doc_id}/pages/{page_num}/layout 에서 사용.

    layout_page.schema.json 형식의 JSON을 그대로 전달받는다.
    """
    part_id: str
    page_number: int
    image_width: int | None = None
    image_height: int | None = None
    analysis_method: str | None = None
    blocks: list = []

# 서고 경로 — serve 명령에서 설정된다
_library_path: Path | None = None

# 정적 파일 디렉토리
_static_dir = Path(__file__).parent / "static"


def configure(library_path: str | Path) -> FastAPI:
    """서고 경로를 설정하고 정적 파일 마운트를 수행한다.

    목적: 서버 시작 전(또는 런타임에 서고 전환 시) 서고 경로를 지정한다.
    입력: library_path — 서고 디렉토리 경로.
    출력: 설정된 FastAPI 앱 인스턴스.

    서고 전환 시 주의:
        - LLM 라우터 캐시를 초기화한다 (서고별 .env가 다를 수 있음).
        - 최근 서고 목록에 추가한다.
    """
    global _library_path, _llm_router
    _library_path = Path(library_path).resolve()

    # LLM 라우터 캐시 초기화 (서고 전환 시 .env가 달라질 수 있으므로)
    _llm_router = None

    # 최근 서고 목록에 추가
    try:
        from core.app_config import add_recent_library
        lib_name = _library_path.name
        # library_manifest.json에서 이름 읽기 (있으면)
        manifest_path = _library_path / "library_manifest.json"
        if manifest_path.exists():
            import json
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            lib_name = manifest.get("name", lib_name)
        add_recent_library(str(_library_path), lib_name)
    except Exception as e:
        logger.debug(f"최근 서고 기록 실패 (무시): {e}")

    # 정적 파일 서빙 (CSS, JS 등)
    # mount는 한 번만 — 이미 마운트된 경우 스킵
    routes_paths = [r.path for r in app.routes]
    if "/static" not in routes_paths:
        app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

    return app


# --- 페이지 라우트 ---

@app.get("/")
async def index():
    """메인 워크스페이스 페이지를 반환한다."""
    return FileResponse(str(_static_dir / "index.html"))


# --- API 라우트 ---

@app.get("/api/library")
async def api_library():
    """서고 정보를 반환한다."""
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


class SwitchLibraryRequest(BaseModel):
    """서고 전환 요청."""
    path: str


@app.post("/api/library/switch")
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

    configure(str(target))
    return {"ok": True, "library_path": str(_library_path)}


class InitLibraryRequest(BaseModel):
    """새 서고 생성 요청."""
    path: str


@app.post("/api/library/init")
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

    configure(str(target))
    return {"ok": True, "library_path": str(_library_path)}


@app.get("/api/library/recent")
async def api_recent_libraries():
    """최근 사용한 서고 목록을 반환한다.

    출력: { "libraries": [{path, name, last_used}, ...] }
    """
    from core.app_config import get_recent_libraries
    return {
        "libraries": get_recent_libraries(),
        "current": str(_library_path) if _library_path else None,
    }


@app.get("/api/settings")
async def api_get_settings():
    """현재 서고 설정 정보를 반환한다.

    서고 경로, 원본/해석 저장소의 원격 URL을 포함한다.
    """
    import subprocess

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

    return info


class SetRemoteRequest(BaseModel):
    """원격 저장소 URL 설정 요청."""
    repo_type: str   # "documents" 또는 "interpretations"
    repo_id: str     # 저장소 ID
    remote_url: str  # 원격 URL


@app.post("/api/settings/remote")
async def api_set_remote(body: SetRemoteRequest):
    """원본/해석 저장소의 원격 URL을 설정한다."""
    import subprocess

    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    repo_dir = _library_path / body.repo_type / body.repo_id
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


class GitPushPullRequest(BaseModel):
    """Git push/pull 요청."""
    repo_type: str   # "documents" 또는 "interpretations"
    repo_id: str
    action: str      # "push" 또는 "pull"


@app.post("/api/settings/git-sync")
async def api_git_sync(body: GitPushPullRequest):
    """원본/해석 저장소를 원격에 push 또는 pull한다."""
    import subprocess

    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    repo_dir = _library_path / body.repo_type / body.repo_id
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


def _get_git_remote(repo_dir: Path) -> str | None:
    """Git 저장소의 origin remote URL을 반환한다."""
    import subprocess
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


@app.get("/api/documents")
async def api_documents():
    """서고의 문헌 목록을 반환한다."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    return list_documents(_library_path)


@app.delete("/api/documents/{doc_id}")
async def api_delete_document(doc_id: str):
    """문헌을 휴지통(.trash/documents/)으로 이동한다.

    목적: 문헌 폴더를 영구 삭제하지 않고 서고 내 .trash/로 옮긴다.
    응답에 related_interpretations가 포함되므로
    프론트엔드에서 연관 해석 저장소 경고를 표시할 수 있다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    try:
        result = trash_document(_library_path, doc_id)
        return result
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


# =========================================
#   Phase 10: URL → 문헌 자동 생성 API
# =========================================


def _suggest_doc_id(title: str) -> str:
    """서지 제목에서 문헌 ID 후보를 자동 생성한다.

    목적: 사용자가 doc_id를 직접 입력하지 않아도 되도록 서지 제목에서
          영문 소문자/숫자/밑줄로 구성된 ID를 자동으로 만든다.
    입력: title — 서지 제목 (한자/가나/한글 포함 가능).
    출력: doc_id 후보 문자열 (최대 64자, ^[a-z][a-z0-9_]*$ 형식).

    왜 ASCII만 사용하는가:
        doc_id는 파일시스템 디렉토리명으로 사용되므로,
        manifest.schema.json 규칙에 따라 영문 소문자+숫자+밑줄만 허용한다.
        한자 제목인 경우 사용자가 직접 입력하도록 빈 제안값을 반환한다.
    """
    # ASCII 영문숫자와 공백/밑줄/하이픈만 추출
    cleaned = []
    for ch in title:
        if ch.isascii() and ch.isalnum():
            cleaned.append(ch.lower())
        elif ch in " _-":
            cleaned.append("_")
        # 비 ASCII 문자(한자, 가나, 한글 등)는 건너뜀
    result = "".join(cleaned).strip("_")
    # 연속 밑줄 제거
    while "__" in result:
        result = result.replace("__", "_")
    # 영문 소문자로 시작하지 않으면 접두어 추가
    if result and not result[0].isalpha():
        result = "doc_" + result
    # 64자 제한
    return result[:64] if result else ""


class PreviewFromUrlRequest(BaseModel):
    """URL에서 서지정보 + 에셋 목록 미리보기 요청."""
    url: str


@app.post("/api/documents/preview-from-url")
async def api_preview_from_url(body: PreviewFromUrlRequest):
    """URL에서 서지정보와 다운로드 가능한 에셋 목록을 미리보기한다.

    목적: 문헌 생성 전에 서지정보와 이미지 목록을 확인한다 (2단계 워크플로우의 1단계).
    입력: { "url": "https://www.digital.archives.go.jp/file/1078619.html" }
    출력: {
        "parser_id": "japan_national_archives",
        "bibliography": {...},
        "assets": [{"id": "...", "label": "...", "page_count": 77}, ...],
        "suggested_doc_id": "蒙求"
    }
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    import parsers as _parsers_mod  # noqa: F401
    from parsers.base import detect_parser_from_url, get_parser, get_supported_sources

    url = body.url.strip()
    if not url:
        return JSONResponse({"error": "URL이 비어있습니다."}, status_code=400)

    # 1. 파서 판별
    parser_id = detect_parser_from_url(url)
    if parser_id is None:
        sources = get_supported_sources()
        return JSONResponse(
            {
                "error": "이 URL은 자동 인식할 수 없습니다.",
                "supported_sources": sources,
            },
            status_code=400,
        )

    # 2. fetch + 매핑
    try:
        fetcher, mapper = get_parser(parser_id)
        raw_data = await fetcher.fetch_by_url(url)
        bibliography = mapper.map_to_bibliography(raw_data)
    except Exception as e:
        return JSONResponse(
            {"error": f"서지정보 가져오기 실패: {e}"},
            status_code=502,
        )

    # 3. 에셋 목록 조회
    # - 전용 에셋 다운로더가 있는 파서 → list_assets() 사용
    # - 없는 파서(NDL, KORCIS 등) → URL 자체가 PDF/이미지인지 폴백 감지
    assets = []
    if fetcher.supports_asset_download:
        try:
            assets = await fetcher.list_assets(raw_data)
        except Exception as e:
            # 에셋 목록 실패는 치명적이지 않음 — 경고만
            assets = []
            bibliography.setdefault("_warnings", []).append(
                f"에셋 목록 조회 실패: {e}"
            )
    else:
        # 폴백: URL 자체가 다운로드 가능한 파일(PDF/이미지)인지 확인
        try:
            from parsers.asset_detector import detect_direct_download
            direct = await detect_direct_download(url)
            if direct:
                assets = [direct]
        except Exception as e:
            logger.debug(f"폴백 에셋 감지 실패 (무시): {e}")

    # 4. doc_id 후보 생성
    title = bibliography.get("title", "")
    suggested_doc_id = _suggest_doc_id(title) if title else "untitled"

    return {
        "parser_id": parser_id,
        "bibliography": bibliography,
        "assets": assets,
        "suggested_doc_id": suggested_doc_id,
    }


class CreateFromUrlRequest(BaseModel):
    """URL에서 문헌 자동 생성 요청."""
    url: str
    doc_id: str
    title: str | None = None
    selected_assets: list[str] | None = None


@app.post("/api/documents/create-from-url")
async def api_create_from_url(body: CreateFromUrlRequest):
    """URL에서 서지정보와 이미지를 가져와 문헌을 자동 생성한다.

    목적: URL 하나로 서지정보 추출 + 이미지 다운로드 + 문서 폴더 생성을 한 번에 수행.
          2단계 워크플로우의 2단계 (미리보기 후 실행).
    입력: {
        "url": "https://...",
        "doc_id": "monggu",
        "title": "蒙求",
        "selected_assets": ["M2023...156"]  // null이면 전체 다운로드
    }
    출력: create_document_from_url()의 결과.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    url = body.url.strip()
    doc_id = body.doc_id.strip()
    if not url:
        return JSONResponse({"error": "URL이 비어있습니다."}, status_code=400)
    if not doc_id:
        return JSONResponse({"error": "doc_id가 비어있습니다."}, status_code=400)

    try:
        result = await create_document_from_url(
            library_path=_library_path,
            url=url,
            doc_id=doc_id,
            title=body.title,
            selected_assets=body.selected_assets,
        )
        return result
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except FileExistsError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except Exception as e:
        return JSONResponse(
            {"error": f"문헌 생성 실패: {e}"},
            status_code=502,
        )


# --- HWP 가져오기 ---


@app.post("/api/documents/preview-hwp")
async def api_preview_hwp(file: UploadFile = File(...)):
    """HWP/HWPX 파일을 미리보기한다.

    목적: 가져오기 전에 파일 내용과 표점·현토 감지 결과를 확인한다.
    입력: multipart/form-data로 HWP/HWPX 파일 업로드.
    출력:
        {
            "metadata": {title, author, format, ...},
            "text_preview": str (앞부분 500자),
            "sections_count": int,
            "detected_punctuation": bool,
            "detected_hyeonto": bool,
            "sample_clean_text": str (첫 섹션의 정리 결과),
        }
    """
    import tempfile

    from hwp.reader import detect_format, get_reader
    from hwp.text_cleaner import clean_hwp_text

    # 업로드된 파일을 임시 파일로 저장
    suffix = Path(file.filename or "").suffix or ".hwpx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # 형식 감지
        fmt = detect_format(tmp_path)
        if fmt is None:
            return JSONResponse(
                {"error": f"지원하지 않는 파일 형식입니다: {suffix}"},
                status_code=400,
            )

        # 텍스트 추출
        reader = get_reader(tmp_path)
        metadata = reader.extract_metadata()

        if hasattr(reader, "extract_sections"):
            sections = reader.extract_sections()
            full_text = "\n\n".join(s["text"] for s in sections)
            sections_count = len(sections)
        else:
            full_text = reader.extract_text()
            sections_count = len([
                t for t in full_text.split("\n\n") if t.strip()
            ])

        # 표점·현토 감지 (샘플)
        sample_text = full_text[:2000]
        sample_result = clean_hwp_text(sample_text)

        return {
            "metadata": metadata,
            "text_preview": full_text[:500],
            "full_text_length": len(full_text),
            "sections_count": sections_count,
            "detected_punctuation": sample_result.had_punctuation,
            "detected_hyeonto": sample_result.had_hyeonto,
            "detected_taidu": sample_result.had_taidu,
            "sample_clean_text": sample_result.clean_text[:500],
            "punct_count": len(sample_result.punctuation_marks),
            "hyeonto_count": len(sample_result.hyeonto_annotations),
        }
    except Exception as e:
        return JSONResponse(
            {"error": f"HWP 파일 읽기 실패: {e}"},
            status_code=400,
        )
    finally:
        # 임시 파일 정리
        try:
            tmp_path.unlink()
        except OSError:
            pass


@app.post("/api/documents/import-hwp")
async def api_import_hwp(
    file: UploadFile = File(...),
    doc_id: str = Form(...),
    title: str = Form(None),
    page_mapping: str = Form(None),
    strip_punctuation: bool = Form(True),
    strip_hyeonto: bool = Form(True),
):
    """HWP/HWPX 파일에서 텍스트를 가져온다.

    목적: HWP 텍스트를 기존 문서의 L4에 가져오거나, 새 문헌을 생성한다.
    입력: multipart/form-data
        file — HWP/HWPX 파일
        doc_id — 문헌 ID
        title — 제목 (선택, 새 문헌 생성 시)
        page_mapping — JSON 문자열 (선택, 시나리오 1의 섹션↔페이지 매핑)
        strip_punctuation — 표점 제거 여부 (기본 true)
        strip_hyeonto — 현토 제거 여부 (기본 true)
    모드 자동 판별:
        - doc_id가 이미 존재하면 → 시나리오 1 (기존 문서에 텍스트 가져오기)
        - doc_id가 없으면 → 시나리오 2 (새 문헌 생성)
    출력: {document_id, title, mode, pages_saved, text_pages, cleaned_stats}
    """
    import tempfile

    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    if not doc_id or not doc_id.strip():
        return JSONResponse({"error": "doc_id가 비어있습니다."}, status_code=400)
    doc_id = doc_id.strip()

    # page_mapping JSON 파싱
    parsed_mapping = None
    if page_mapping:
        try:
            parsed_mapping = json.loads(page_mapping)
        except json.JSONDecodeError:
            return JSONResponse(
                {"error": "page_mapping이 올바른 JSON이 아닙니다."},
                status_code=400,
            )

    # 업로드된 파일을 임시 파일로 저장
    suffix = Path(file.filename or "").suffix or ".hwpx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        doc_path = _library_path / "documents" / doc_id

        if doc_path.exists():
            # 시나리오 1: 기존 문서에 텍스트 가져오기
            result = import_hwp_text_to_document(
                library_path=_library_path,
                doc_id=doc_id,
                hwp_file=tmp_path,
                page_mapping=parsed_mapping,
                strip_punctuation=strip_punctuation,
                strip_hyeonto=strip_hyeonto,
            )
        else:
            # 시나리오 2: 새 문헌 생성
            result = create_document_from_hwp(
                library_path=_library_path,
                hwp_file=tmp_path,
                doc_id=doc_id,
                title=title,
                strip_punctuation=strip_punctuation,
                strip_hyeonto=strip_hyeonto,
            )

        return result
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except FileExistsError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse(
            {"error": f"HWP 가져오기 실패: {e}"},
            status_code=500,
        )
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


class MatchHwpToBlocksRequest(BaseModel):
    """HWP 텍스트를 LayoutBlock에 매칭하는 요청."""
    part_id: str
    page_num: int
    block_text_mapping: list[dict]


@app.post("/api/documents/{doc_id}/match-hwp-to-blocks")
async def api_match_hwp_to_blocks(doc_id: str, body: MatchHwpToBlocksRequest):
    """페이지 텍스트를 LayoutBlock 단위로 매칭한다 (2단계).

    목적: 1단계(페이지 매핑) 완료 후, 레이아웃 분석(L3)이 있으면
          HWP 텍스트를 LayoutBlock 단위로 분할·매칭한다.
    전제: 레이아웃 분석(L3) 완료.
    입력: {
        "part_id": "vol1",
        "page_num": 1,
        "block_text_mapping": [
            {"layout_block_id": "p01_b01", "text": "天地之道..."},
            ...
        ]
    }
    출력: {matched_blocks, ocr_result_saved}
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    try:
        result = match_hwp_text_to_layout_blocks(
            library_path=_library_path,
            doc_id=doc_id,
            part_id=body.part_id,
            page_num=body.page_num,
            block_text_mapping=body.block_text_mapping,
        )
        return result
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse(
            {"error": f"블록 매칭 실패: {e}"},
            status_code=500,
        )


# --- PDF 참조 텍스트 추출 (Part D) ---


@app.post("/api/text-import/pdf/analyze")
async def api_pdf_analyze(file: UploadFile = File(...)):
    """PDF 텍스트 레이어를 분석한다.

    목적: PDF에 텍스트 레이어가 있는지 확인하고,
          첫 몇 페이지의 텍스트를 추출하여 구조 분석(LLM)을 수행한다.
    입력: multipart/form-data로 PDF 파일 업로드.
    출력:
        {
            "page_count": int,
            "has_text_layer": bool,
            "sample_pages": [{page_num, text, char_count}, ...],
            "detected_structure": {pattern_type, original_markers, ...} | null,
        }
    """
    import tempfile

    from text_import.pdf_extractor import PdfTextExtractor

    suffix = Path(file.filename or "").suffix or ".pdf"
    if suffix.lower() != ".pdf":
        return JSONResponse(
            {"error": f"PDF 파일만 지원합니다 (받은 형식: {suffix})"},
            status_code=400,
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        extractor = PdfTextExtractor(tmp_path)
        has_text = extractor.has_text_layer()
        page_count = extractor.page_count
        sample_pages = extractor.get_sample_text(max_pages=3)

        # 텍스트 레이어가 있으면 LLM으로 구조 분석 시도
        detected_structure = None
        if has_text and _llm_router is not None:
            try:
                from text_import.text_separator import TextSeparator

                separator = TextSeparator(_llm_router)
                structure = await separator.analyze_structure(sample_pages)
                detected_structure = structure.to_dict()
            except Exception as e:
                logging.getLogger(__name__).warning("구조 분석 실패 (비치명적): %s", e)

        extractor.close()

        return {
            "page_count": page_count,
            "has_text_layer": has_text,
            "sample_pages": sample_pages,
            "detected_structure": detected_structure,
        }
    except Exception as e:
        return JSONResponse(
            {"error": f"PDF 분석 실패: {e}"},
            status_code=400,
        )
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


class PdfSeparateRequest(BaseModel):
    """PDF 텍스트 분리 요청."""
    structure: dict  # DocumentStructure 딕셔너리
    pages: list[dict] | None = None  # [{page_num, text}] — None이면 전체
    custom_instructions: str = ""
    force_provider: str | None = None
    force_model: str | None = None


@app.post("/api/text-import/pdf/separate")
async def api_pdf_separate(
    file: UploadFile = File(...),
    body: str = Form(...),
):
    """PDF 텍스트를 원문/번역/주석으로 분리한다 (LLM).

    목적: analyze에서 확인된 구조를 바탕으로, 전체(또는 지정) 페이지의
          텍스트를 원문/번역/주석으로 분리한다.
    입력:
        file — PDF 파일 (multipart)
        body — JSON 문자열 {structure, pages, custom_instructions, ...}
    출력:
        {
            "results": [{page_num, original_text, translation_text, notes, uncertain}, ...]
        }
    """
    import tempfile

    if _llm_router is None:
        return JSONResponse(
            {"error": "LLM이 설정되지 않았습니다. API 키를 확인하세요."},
            status_code=500,
        )

    # body JSON 파싱
    try:
        params = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse({"error": "body가 올바른 JSON이 아닙니다."}, status_code=400)

    suffix = Path(file.filename or "").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        from text_import.pdf_extractor import PdfTextExtractor
        from text_import.text_separator import DocumentStructure, TextSeparator

        # 구조 복원
        structure = DocumentStructure.from_dict(params.get("structure", {}))
        custom_instructions = params.get("custom_instructions", "")
        force_provider = params.get("force_provider")
        force_model = params.get("force_model")

        # 페이지 텍스트 준비
        pages = params.get("pages")
        if pages is None:
            # 전체 페이지 추출
            extractor = PdfTextExtractor(tmp_path)
            pages = extractor.extract_all_pages()
            extractor.close()

        # LLM 분리 실행
        separator = TextSeparator(_llm_router)
        results = await separator.separate_batch(
            pages=pages,
            structure=structure,
            custom_instructions=custom_instructions,
            force_provider=force_provider,
            force_model=force_model,
        )

        return {
            "results": [r.to_dict() for r in results],
        }
    except Exception as e:
        return JSONResponse(
            {"error": f"텍스트 분리 실패: {e}"},
            status_code=500,
        )
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


class PdfApplyRequest(BaseModel):
    """PDF 분리 결과를 문서에 적용하는 요청."""
    doc_id: str
    results: list[dict]  # [{page_num, original_text, ...}]
    page_mapping: list[dict] | None = None  # [{source_page, target_page, part_id}]
    save_translation_to_l6: bool = False
    strip_punctuation: bool = True
    strip_hyeonto: bool = True


@app.post("/api/text-import/pdf/apply")
async def api_pdf_apply(body: PdfApplyRequest, background_tasks: BackgroundTasks):
    """PDF 분리 결과를 문서의 L4에 적용한다.

    목적: 사용자가 확인/수정한 분리 결과를 실제 문서에 저장한다.
    입력: PdfApplyRequest
    출력: {pages_saved, l4_files}
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / body.doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌이 존재하지 않습니다: {body.doc_id}"},
            status_code=404,
        )

    try:
        from hwp.text_cleaner import clean_hwp_text
        from text_import.common import (
            save_formatting_sidecar,
            save_punctuation_sidecar,
            save_text_to_l4,
        )

        # 매니페스트에서 기본 part_id
        manifest = get_document_info(doc_path)
        parts = manifest.get("parts", [])
        default_part_id = parts[0]["part_id"] if parts else "vol1"

        l4_files = []
        pages_saved = 0

        for item in body.results:
            page_num = item.get("page_num", 0)
            original_text = item.get("original_text", "")
            if not original_text.strip():
                continue

            # page_mapping이 있으면 대상 페이지/part 변환
            target_page = page_num
            target_part = default_part_id
            if body.page_mapping:
                for m in body.page_mapping:
                    if m.get("source_page") == page_num:
                        target_page = m.get("target_page", page_num)
                        target_part = m.get("part_id", default_part_id)
                        break

            # 표점·현토 분리 (옵션)
            if body.strip_punctuation or body.strip_hyeonto:
                result = clean_hwp_text(
                    original_text,
                    strip_punct=body.strip_punctuation,
                    strip_hyeonto=body.strip_hyeonto,
                )
                text_to_save = result.clean_text

                # 사이드카 데이터 저장
                save_punctuation_sidecar(
                    doc_path, target_part, target_page,
                    result.punctuation_marks, result.hyeonto_annotations,
                    raw_text_length=len(original_text),
                    clean_text_length=len(result.clean_text),
                    source="pdf_import",
                )

                if result.taidu_marks:
                    save_formatting_sidecar(
                        doc_path, target_part, target_page,
                        result.taidu_marks,
                    )
            else:
                text_to_save = original_text

            # L4 텍스트 저장
            file_path = save_text_to_l4(doc_path, target_part, target_page, text_to_save)
            l4_files.append(file_path.relative_to(doc_path).as_posix())
            pages_saved += 1

        # completeness_status 업데이트
        manifest["completeness_status"] = "text_imported"
        (doc_path / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # git commit (백그라운드)
        background_tasks.add_task(
            git_commit_document,
            doc_path,
            f"feat: PDF 참조 텍스트 가져오기 — {pages_saved}페이지",
        )

        return {
            "pages_saved": pages_saved,
            "l4_files": l4_files,
        }
    except Exception as e:
        return JSONResponse(
            {"error": f"PDF 텍스트 적용 실패: {e}"},
            status_code=500,
        )


@app.get("/api/documents/{doc_id}")
async def api_document(doc_id: str):
    """특정 문헌의 정보를 반환한다 (manifest + pages)."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    try:
        info = get_document_info(doc_path)
        info["pages"] = list_pages(doc_path)
        return info
    except FileNotFoundError:
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )


@app.get("/api/documents/{doc_id}/pdf/{part_id}")
async def api_document_pdf(doc_id: str, part_id: str):
    """문헌의 특정 권(part) PDF 파일을 반환한다.

    목적: 좌측 PDF 뷰어에서 원본 PDF를 렌더링하기 위해 파일을 서빙한다.
    입력:
        doc_id — 문헌 ID.
        part_id — 권 식별자 (예: "vol1").
    출력: PDF 파일 (application/pdf).
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    try:
        pdf_path = get_pdf_path(doc_path, part_id)
        return FileResponse(
            str(pdf_path),
            media_type="application/pdf",
            filename=pdf_path.name,
        )
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.get("/api/documents/{doc_id}/pages/{page_num}/text")
async def api_page_text(
    doc_id: str,
    page_num: int,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """특정 페이지의 텍스트를 반환한다.

    목적: 우측 텍스트 에디터에 페이지 텍스트를 로드하기 위해 사용한다.
    입력:
        doc_id — 문헌 ID.
        page_num — 페이지 번호 (1부터 시작).
        part_id — 쿼리 파라미터, 권 식별자.
    출력: {document_id, part_id, page, text, file_path, exists}.
          파일이 없으면 text=""과 exists=false를 반환한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    try:
        return get_page_text(doc_path, part_id, page_num)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.put("/api/documents/{doc_id}/pages/{page_num}/text")
async def api_save_page_text(
    doc_id: str,
    page_num: int,
    body: TextSaveRequest,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """특정 페이지의 텍스트를 저장한다.

    목적: 우측 텍스트 에디터에서 입력한 텍스트를 L4_text/pages/에 기록한다.
    입력:
        doc_id — 문헌 ID.
        page_num — 페이지 번호.
        part_id — 쿼리 파라미터, 권 식별자.
        body — {text: "저장할 텍스트"}.
    출력: {status: "saved", file_path, size}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    try:
        return save_page_text(doc_path, part_id, page_num, body.text)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


# --- 레이아웃 API (Phase 4) ---


@app.get("/api/documents/{doc_id}/pages/{page_num}/layout")
async def api_page_layout(
    doc_id: str,
    page_num: int,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """특정 페이지의 레이아웃(LayoutBlock 목록)을 반환한다.

    목적: 레이아웃 편집기에서 기존 LayoutBlock을 로드하기 위해 사용한다.
    입력:
        doc_id — 문헌 ID.
        page_num — 페이지 번호 (1부터 시작).
        part_id — 쿼리 파라미터, 권 식별자.
    출력: layout_page.schema.json 형식 + _meta (document_id, file_path, exists).
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    try:
        return get_page_layout(doc_path, part_id, page_num)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.put("/api/documents/{doc_id}/pages/{page_num}/layout")
async def api_save_page_layout(
    doc_id: str,
    page_num: int,
    body: LayoutSaveRequest,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """특정 페이지의 레이아웃을 저장한다.

    목적: 레이아웃 편집기에서 작성한 LayoutBlock 데이터를 L3_layout/에 기록한다.
    입력:
        doc_id — 문헌 ID.
        page_num — 페이지 번호.
        part_id — 쿼리 파라미터, 권 식별자.
        body — layout_page.schema.json 형식의 레이아웃 데이터.
    출력: {status: "saved", file_path, block_count}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    layout_data = body.model_dump()
    try:
        return save_page_layout(doc_path, part_id, page_num, layout_data)
    except Exception as e:
        # jsonschema.ValidationError 등
        return JSONResponse(
            {"error": f"레이아웃 저장 실패: {e}"},
            status_code=400,
        )


@app.get("/api/resources/block_types")
async def api_block_types():
    """블록 타입 어휘 목록을 반환한다.

    목적: 레이아웃 편집기에서 block_type 드롭다운을 채우기 위해 사용한다.
    출력: resources/block_types.json의 내용.
    """
    block_types_path = (
        Path(__file__).resolve().parent.parent.parent
        / "resources" / "block_types.json"
    )
    if not block_types_path.exists():
        return JSONResponse(
            {"error": "block_types.json을 찾을 수 없습니다."},
            status_code=404,
        )
    import json
    data = json.loads(block_types_path.read_text(encoding="utf-8"))
    return data


# --- 교정 API (Phase 6) ---


class CorrectionItem(BaseModel):
    """개별 교정 항목. corrections.schema.json의 Correction 정의와 대응."""
    page: int | None = None
    block_id: str | None = None
    line: int | None = None
    char_index: int | None = None
    type: str
    original_ocr: str
    corrected: str
    common_reading: str | None = None
    corrected_by: str | None = None
    confidence: float | None = None
    note: str | None = None


class CorrectionsSaveRequest(BaseModel):
    """교정 저장 요청 본문. corrections.schema.json 형식."""
    part_id: str | None = None
    corrections: list[CorrectionItem] = []


@app.get("/api/documents/{doc_id}/pages/{page_num}/corrections")
async def api_page_corrections(
    doc_id: str,
    page_num: int,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """특정 페이지의 교정 기록을 반환한다.

    목적: 교정 편집기에서 기존 교정 기록을 로드하기 위해 사용한다.
    입력:
        doc_id — 문헌 ID.
        page_num — 페이지 번호 (1부터 시작).
        part_id — 쿼리 파라미터, 권 식별자.
    출력: corrections.schema.json 형식 + _meta.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    try:
        return get_page_corrections(doc_path, part_id, page_num)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.put("/api/documents/{doc_id}/pages/{page_num}/corrections")
async def api_save_page_corrections(
    doc_id: str,
    page_num: int,
    body: CorrectionsSaveRequest,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """특정 페이지의 교정 기록을 저장하고 자동으로 git commit한다.

    목적: 교정 편집기에서 작성한 교정 데이터를 L4_text/corrections/에 기록하고,
          교정 내역을 요약한 커밋 메시지로 자동 commit한다.
    입력:
        doc_id — 문헌 ID.
        page_num — 페이지 번호.
        part_id — 쿼리 파라미터, 권 식별자.
        body — corrections.schema.json 형식의 교정 데이터.
    출력: {status, file_path, correction_count, git}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    corrections_data = body.model_dump()
    try:
        save_result = save_page_corrections(doc_path, part_id, page_num, corrections_data)
    except Exception as e:
        return JSONResponse(
            {"error": f"교정 저장 실패: {e}"},
            status_code=400,
        )

    # 교정 유형별 건수 집계 → git commit 메시지 생성
    from collections import Counter
    type_counts = Counter(c["type"] for c in corrections_data.get("corrections", []))
    summary_parts = [f"{t} {n}건" for t, n in type_counts.items()]
    summary = ", ".join(summary_parts) if summary_parts else "없음"
    commit_msg = f"L4: page {page_num:03d} 교정 — {summary}"

    try:
        git_result = git_commit_document(
            doc_path,
            commit_msg,
            add_paths=[save_result.get("file_path", "")],
        )
    except Exception as e:
        git_result = {
            "committed": False,
            "message": f"git commit 실패: {e}",
        }

    save_result["git"] = git_result

    return save_result


# --- 교정 적용 텍스트 API (편성 탭용) ---


@app.get("/api/documents/{doc_id}/pages/{page_num}/corrected-text")
async def api_corrected_text(
    doc_id: str,
    page_num: int,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """교정이 적용된 텍스트를 반환한다.

    목적: 편성(composition) 탭에서 교정된 텍스트를 블록별로 표시하기 위해 사용한다.
          L4_text/pages/ 원본에 L4_text/corrections/ 교정 기록을 적용한 결과.
    입력:
        doc_id — 문헌 ID.
        page_num — 페이지 번호 (1부터 시작).
        part_id — 쿼리 파라미터, 권 식별자.
    출력: {document_id, part_id, page, original_text, corrected_text, correction_count, blocks}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    try:
        return get_corrected_text(doc_path, part_id, page_num)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


# --- Git API (Phase 6) ---


@app.get("/api/documents/{doc_id}/git/log")
async def api_git_log(
    doc_id: str,
    max_count: int = Query(50, description="최대 커밋 수"),
):
    """문헌 저장소의 git 커밋 이력을 반환한다.

    목적: 하단 패널의 Git 이력 탭에 커밋 목록을 표시하기 위해 사용한다.
    입력:
        doc_id — 문헌 ID.
        max_count — 최대 커밋 수 (기본 50).
    출력: [{hash, short_hash, message, author, date}, ...].
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    return {"commits": get_git_log(doc_path, max_count=max_count)}


@app.get("/api/documents/{doc_id}/git/diff/{commit_hash}")
async def api_git_diff(doc_id: str, commit_hash: str):
    """특정 커밋과 그 부모 사이의 diff를 반환한다.

    목적: Git 이력에서 커밋을 선택했을 때 변경 내용을 표시하기 위해 사용한다.
    입력:
        doc_id — 문헌 ID.
        commit_hash — 대상 커밋 해시.
    출력: {commit_hash, message, diffs: [{file, change_type, diff_text}, ...]}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    result = get_git_diff(doc_path, commit_hash)
    if "error" in result:
        return JSONResponse({"error": result["error"]}, status_code=404)

    return result


# --- 서지정보 API (Phase 5) ---


@app.get("/api/documents/{doc_id}/bibliography")
async def api_bibliography(doc_id: str):
    """문헌의 서지정보를 반환한다.

    목적: 서지정보 패널에 bibliography.json 내용을 표시하기 위해 사용한다.
    입력: doc_id — 문헌 ID.
    출력: bibliography.json의 내용.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    try:
        return get_bibliography(doc_path)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


class DocumentBibFromUrlRequest(BaseModel):
    """문서에 URL로 서지정보를 가져와 바로 저장하는 요청 본문."""
    url: str


@app.post("/api/documents/{doc_id}/bibliography/from-url")
async def api_document_bib_from_url(doc_id: str, body: DocumentBibFromUrlRequest):
    """URL에서 서지정보를 가져와 해당 문서에 바로 저장한다.

    목적: 연구자의 워크플로우를 1단계로 줄인다.
          문서 선택 → URL 붙여넣기 → 가져오기 → 끝.
    입력: { "url": "https://..." }
    처리:
        1. URL에서 bibliography 생성
        2. 해당 문서의 bibliography.json에 저장
        3. git commit
    출력: { "status": "saved", "parser_id": "ndl", "bibliography": {...} }
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    import parsers as _parsers_mod  # noqa: F401
    from parsers.base import detect_parser_from_url, get_parser, get_supported_sources

    url = body.url.strip()
    if not url:
        return JSONResponse({"error": "URL이 비어있습니다."}, status_code=400)

    # URL 판별
    parser_id = detect_parser_from_url(url)
    if parser_id is None:
        sources = get_supported_sources()
        return JSONResponse(
            {
                "error": "이 URL은 자동 인식할 수 없습니다.",
                "supported_sources": sources,
            },
            status_code=400,
        )

    # 파서 가져오기 + fetch + 매핑
    try:
        fetcher, mapper = get_parser(parser_id)
        raw_data = await fetcher.fetch_by_url(url)
        bibliography = mapper.map_to_bibliography(raw_data)
    except Exception as e:
        return JSONResponse(
            {"error": f"서지정보 가져오기 실패: {e}"},
            status_code=502,
        )

    # 저장
    try:
        save_bibliography(doc_path, bibliography)
    except Exception as e:
        return JSONResponse(
            {"error": f"서지정보 저장 실패: {e}"},
            status_code=400,
        )

    # git commit
    git_result = git_commit_document(doc_path, f"L0: 서지정보 URL 가져오기 ({parser_id})")

    return {
        "status": "saved",
        "parser_id": parser_id,
        "bibliography": bibliography,
        "git": git_result,
    }


class BibliographySaveRequest(BaseModel):
    """서지정보 저장 요청 본문. bibliography.schema.json 형식."""
    title: str | None = None
    title_reading: str | None = None
    alternative_titles: list[str] | None = None
    creator: dict | None = None
    contributors: list[dict] | None = None
    date_created: str | None = None
    edition_type: str | None = None
    language: str | None = None
    script: str | None = None
    physical_description: str | None = None
    subject: list[str] | None = None
    classification: dict | None = None
    series_title: str | None = None
    material_type: str | None = None
    repository: dict | None = None
    digital_source: dict | None = None
    raw_metadata: dict | None = None
    _mapping_info: dict | None = None
    notes: str | None = None


@app.put("/api/documents/{doc_id}/bibliography")
async def api_save_bibliography(doc_id: str, body: BibliographySaveRequest):
    """문헌의 서지정보를 저장한다.

    목적: 파서가 가져온 서지정보 또는 사용자가 수동 편집한 내용을 저장한다.
    입력:
        doc_id — 문헌 ID.
        body — bibliography.schema.json 형식의 데이터.
    출력: {status: "saved", file_path}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    bib_data = body.model_dump(exclude_none=False)
    try:
        return save_bibliography(doc_path, bib_data)
    except Exception as e:
        return JSONResponse(
            {"error": f"서지정보 저장 실패: {e}"},
            status_code=400,
        )


# --- 파서 API (Phase 5) ---


@app.get("/api/parsers")
async def api_parsers():
    """등록된 파서 목록을 반환한다.

    목적: GUI에서 파서 선택 드롭다운을 채우기 위해 사용한다.
    출력: [{id, name, api_variant}, ...]
    """
    # 파서 모듈을 지연 import (parsers 패키지가 register_parser를 호출)
    import parsers  # noqa: F401
    from parsers.base import list_parsers, get_registry_json

    return {
        "parsers": list_parsers(),
        "registry": get_registry_json(),
    }


class BibliographyFromUrlRequest(BaseModel):
    """URL에서 서지정보를 가져오는 요청 본문."""
    url: str


@app.post("/api/bibliography/from-url")
async def api_bibliography_from_url(body: BibliographyFromUrlRequest):
    """URL을 자동 판별하여 서지정보를 가져온다.

    목적: 연구자가 URL을 붙여넣기만 하면 서지정보를 자동으로 가져온다.
          파서 선택·검색·결과 선택 과정이 필요 없다.
    입력: { "url": "https://..." }
    처리:
        1. detect_parser_from_url(url) → parser_id
        2. fetcher.fetch_by_url(url) → raw_data
        3. mapper.map_to_bibliography(raw_data) → bibliography
    출력: { "parser_id": "ndl", "bibliography": {...} }
    에러: URL을 인식할 수 없으면 → 지원하는 소스 목록 안내
    """
    import parsers  # noqa: F401
    from parsers.base import detect_parser_from_url, get_parser, get_supported_sources

    url = body.url.strip()
    if not url:
        return JSONResponse(
            {"error": "URL이 비어있습니다."},
            status_code=400,
        )

    # 1. URL 패턴으로 파서 자동 판별
    parser_id = detect_parser_from_url(url)
    if parser_id is None:
        sources = get_supported_sources()
        return JSONResponse(
            {
                "error": "이 URL은 자동 인식할 수 없습니다.",
                "supported_sources": sources,
                "hint": "지원하는 소스의 URL을 붙여넣거나, '직접 검색' 기능을 사용하세요.",
            },
            status_code=400,
        )

    # 2. 파서 가져오기
    try:
        fetcher, mapper = get_parser(parser_id)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)

    # 3. URL에서 메타데이터 추출
    try:
        raw_data = await fetcher.fetch_by_url(url)
    except (ValueError, FileNotFoundError) as e:
        return JSONResponse(
            {"error": f"URL에서 데이터를 가져올 수 없습니다: {e}"},
            status_code=400,
        )
    except Exception as e:
        return JSONResponse(
            {
                "error": f"외부 소스 접속 실패: {e}",
                "hint": "네트워크 연결을 확인하고 다시 시도하세요.",
            },
            status_code=502,
        )

    # 4. 매핑
    try:
        bibliography = mapper.map_to_bibliography(raw_data)
    except Exception as e:
        return JSONResponse(
            {"error": f"서지정보 매핑 실패: {e}"},
            status_code=400,
        )

    return {"parser_id": parser_id, "bibliography": bibliography}


class ParserSearchRequest(BaseModel):
    """파서 검색 요청 본문."""
    query: str
    cnt: int = 10
    mediatype: int | None = None


@app.post("/api/parsers/{parser_id}/search")
async def api_parser_search(parser_id: str, body: ParserSearchRequest):
    """외부 소스에서 서지정보를 검색한다.

    목적: GUI의 "서지정보 가져오기" 다이얼로그에서 사용.
    입력:
        parser_id — 파서 ID (예: "ndl", "japan_national_archives").
        body — {query: "검색어", cnt: 10}.
    출력: {results: [{title, creator, item_id, summary, raw}, ...]}.
    """
    import parsers  # noqa: F401
    from parsers.base import get_parser

    try:
        fetcher, _mapper = get_parser(parser_id)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)

    try:
        results = await fetcher.search(
            body.query,
            cnt=body.cnt,
            mediatype=body.mediatype,
        )
        return {"results": results}
    except Exception as e:
        return JSONResponse(
            {"error": f"검색 실패: {e}\n→ 해결: 네트워크 연결과 검색어를 확인하세요."},
            status_code=502,
        )


class ParserMapRequest(BaseModel):
    """파서 매핑 요청 본문. 검색 결과의 raw 데이터를 전달한다."""
    raw_data: dict


@app.post("/api/parsers/{parser_id}/map")
async def api_parser_map(parser_id: str, body: ParserMapRequest):
    """검색 결과를 bibliography.json 형식으로 매핑한다.

    목적: 사용자가 검색 결과에서 항목을 선택하면,
          해당 항목의 raw 데이터를 공통 스키마로 변환한다.
    입력:
        parser_id — 파서 ID.
        body — {raw_data: {...}} (Fetcher가 반환한 raw dict).
    출력: bibliography.schema.json 형식의 dict.
    """
    import parsers  # noqa: F401
    from parsers.base import get_parser

    try:
        _fetcher, mapper = get_parser(parser_id)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)

    try:
        bibliography = mapper.map_to_bibliography(body.raw_data)
        return {"bibliography": bibliography}
    except Exception as e:
        return JSONResponse(
            {"error": f"매핑 실패: {e}"},
            status_code=400,
        )


class ParserFetchAndMapRequest(BaseModel):
    """상세 조회 + 매핑 결합 요청 본문."""
    item_id: str


@app.post("/api/parsers/{parser_id}/fetch-and-map")
async def api_parser_fetch_and_map(parser_id: str, body: ParserFetchAndMapRequest):
    """항목의 상세 정보를 가져와서 bibliography로 매핑한다.

    목적: 검색 결과에서 항목을 선택했을 때,
          KORCIS처럼 검색 결과에 전체 메타데이터가 없는 소스에서
          fetch_detail + map_to_bibliography를 한 번에 수행한다.
    입력:
        parser_id — 파서 ID.
        body — {item_id: "..."} (검색 결과의 item_id).
    출력: bibliography.schema.json 형식의 dict.
    """
    import parsers  # noqa: F401
    from parsers.base import get_parser

    try:
        fetcher, mapper = get_parser(parser_id)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)

    try:
        raw_data = await fetcher.fetch_detail(body.item_id)
        bibliography = mapper.map_to_bibliography(raw_data)
        return {"bibliography": bibliography}
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse(
            {"error": f"상세 조회/매핑 실패: {e}"},
            status_code=502,
        )


# =========================================
#   Phase 7: 해석 저장소 API
# =========================================


class CreateInterpretationRequest(BaseModel):
    """해석 저장소 생성 요청 본문."""
    interp_id: str
    source_document_id: str
    interpreter_type: str
    interpreter_name: str | None = None
    title: str | None = None


class LayerContentSaveRequest(BaseModel):
    """층 내용 저장 요청 본문."""
    content: str | dict
    part_id: str


class AcknowledgeRequest(BaseModel):
    """변경 인지 요청 본문."""
    file_paths: list[str] | None = None


@app.post("/api/interpretations")
async def api_create_interpretation(body: CreateInterpretationRequest):
    """해석 저장소를 생성한다.

    목적: 원본 문헌을 기반으로 새 해석 저장소를 만든다.
    입력:
        body — {interp_id, source_document_id, interpreter_type, interpreter_name, title}.
    출력: 생성된 해석 저장소의 manifest 정보.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    try:
        interp_path = create_interpretation(
            _library_path,
            interp_id=body.interp_id,
            source_document_id=body.source_document_id,
            interpreter_type=body.interpreter_type,
            interpreter_name=body.interpreter_name,
            title=body.title,
        )
        info = get_interpretation_info(interp_path)
        return {"status": "created", "interpretation": info}
    except (ValueError, FileExistsError, FileNotFoundError) as e:
        status = 400 if isinstance(e, (ValueError, FileExistsError)) else 404
        return JSONResponse({"error": str(e)}, status_code=status)


@app.get("/api/interpretations")
async def api_interpretations():
    """해석 저장소 목록을 반환한다."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    return list_interpretations(_library_path)


@app.delete("/api/interpretations/{interp_id}")
async def api_delete_interpretation(interp_id: str):
    """해석 저장소를 휴지통(.trash/interpretations/)으로 이동한다.

    목적: 해석 저장소 폴더를 영구 삭제하지 않고 서고 내 .trash/로 옮긴다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    try:
        result = trash_interpretation(_library_path, interp_id)
        return result
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.get("/api/interpretations/{interp_id}")
async def api_interpretation(interp_id: str):
    """특정 해석 저장소의 상세 정보를 반환한다."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    try:
        return get_interpretation_info(interp_path)
    except FileNotFoundError:
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )


@app.get("/api/interpretations/{interp_id}/dependency")
async def api_check_dependency(interp_id: str):
    """해석 저장소의 의존 변경을 확인한다.

    목적: 원본 저장소가 변경되었는지 확인하여 경고 배너를 표시하기 위해 사용한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    try:
        return check_dependency(_library_path, interp_id)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.post("/api/interpretations/{interp_id}/dependency/acknowledge")
async def api_acknowledge_changes(interp_id: str, body: AcknowledgeRequest):
    """변경된 파일을 '인지함' 상태로 전환한다.

    목적: 연구자가 원본 변경을 확인했지만 해석은 유효하다고 판단할 때 사용한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    try:
        return acknowledge_changes(_library_path, interp_id, body.file_paths)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.post("/api/interpretations/{interp_id}/dependency/update-base")
async def api_update_base(interp_id: str):
    """기반 커밋을 현재 원본 HEAD로 갱신한다.

    목적: 원본 변경을 모두 반영하고 새 기반에서 작업을 계속한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    try:
        return update_base(_library_path, interp_id)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@app.get("/api/interpretations/{interp_id}/layers/{layer}/{sub_type}/pages/{page_num}")
async def api_layer_content(
    interp_id: str,
    layer: str,
    sub_type: str,
    page_num: int,
    part_id: str = Query(..., description="권 식별자 (예: vol1)"),
):
    """해석 층의 내용을 반환한다.

    목적: 해석 뷰어에서 특정 층/서브타입/페이지의 내용을 로드하기 위해 사용한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        return get_layer_content(interp_path, layer, sub_type, part_id, page_num)
    except FileNotFoundError:
        return JSONResponse(
            {"error": f"레이어 내용을 찾을 수 없습니다: {layer}/{sub_type} page {page_num}"},
            status_code=404,
        )
    except Exception as e:
        return JSONResponse(
            {"error": f"레이어 조회 중 오류: {e}"},
            status_code=500,
        )


@app.put("/api/interpretations/{interp_id}/layers/{layer}/{sub_type}/pages/{page_num}")
async def api_save_layer_content(
    interp_id: str,
    layer: str,
    sub_type: str,
    page_num: int,
    body: LayerContentSaveRequest,
):
    """해석 층의 내용을 저장하고 자동 git commit한다.

    목적: 해석 뷰어에서 편집한 내용을 저장하고 버전 이력을 남긴다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        save_result = save_layer_content(
            interp_path, layer, sub_type, body.part_id, page_num, body.content,
        )
    except Exception as e:
        return JSONResponse({"error": f"저장 실패: {e}"}, status_code=400)

    # 자동 git commit
    layer_label = {"L5_reading": "구두점", "L6_translation": "번역", "L7_annotation": "주석"}.get(layer, layer)
    commit_msg = f"{layer}: page {page_num:03d} {layer_label} 편집 ({sub_type})"
    git_result = git_commit_interpretation(interp_path, commit_msg)
    save_result["git"] = git_result

    return save_result


@app.get("/api/interpretations/{interp_id}/git/log")
async def api_interp_git_log(
    interp_id: str,
    max_count: int = Query(50, description="최대 커밋 수"),
):
    """해석 저장소의 git 커밋 이력을 반환한다."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    return {"commits": get_interp_git_log(interp_path, max_count=max_count)}


class ManualCommitRequest(BaseModel):
    """수동 커밋 요청 본문."""
    message: str = "batch: 배치 작업 커밋"


@app.post("/api/interpretations/{interp_id}/git/commit")
async def api_interp_manual_commit(interp_id: str, body: ManualCommitRequest, bg: BackgroundTasks):
    """해석 저장소에 수동으로 git commit을 생성한다 (백그라운드).

    목적: 배치 작업(쪼개기, 리셋 등)에서 no_commit=true로 여러 변경을
          모은 뒤, 마지막에 한 번만 커밋한다. 커밋은 백그라운드에서 실행되어
          API가 즉시 응답한다.
    입력: message — 커밋 메시지 (기본값: "batch: 배치 작업 커밋")
    출력: {committed: "background", message}
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    bg.add_task(git_commit_interpretation, interp_path, body.message)
    return {"committed": "background", "message": body.message}


# =========================================
#   Phase 8: 코어 스키마 엔티티 API
# =========================================


class EntityCreateRequest(BaseModel):
    """엔티티 생성 요청 본문."""
    entity_type: str   # work, text_block, tag, concept, agent, relation
    data: dict         # 스키마에 맞는 엔티티 데이터


class EntityUpdateRequest(BaseModel):
    """엔티티 수정 요청 본문."""
    updates: dict      # 갱신할 필드 딕셔너리


class TextBlockFromSourceRequest(BaseModel):
    """TextBlock 생성 요청 (source_ref 자동 채움)."""
    document_id: str
    part_id: str
    page_num: int
    layout_block_id: str | None = None
    original_text: str
    work_id: str
    sequence_index: int


class PromoteTagRequest(BaseModel):
    """Tag → Concept 승격 요청."""
    label: str | None = None
    scope_work: str | None = None
    description: str | None = None


class AutoCreateWorkRequest(BaseModel):
    """Work 자동 생성 요청."""
    document_id: str


@app.post("/api/interpretations/{interp_id}/entities")
async def api_create_entity(interp_id: str, body: EntityCreateRequest):
    """코어 스키마 엔티티를 생성한다.

    목적: Work, TextBlock, Tag, Concept, Agent, Relation 엔티티를 해석 저장소에 추가한다.
    입력: entity_type + data (JSON 스키마 형식).
    출력: {"status": "created", "entity_type": ..., "id": ..., "file_path": ...}
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        result = create_entity(interp_path, body.entity_type, body.data)
    except (ValueError, FileExistsError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"엔티티 생성 실패: {e}"}, status_code=400)

    # 자동 git commit
    commit_msg = f"feat: {body.entity_type} 엔티티 생성 — {result['id'][:8]}"
    result["git"] = git_commit_interpretation(interp_path, commit_msg)

    return result


@app.get("/api/interpretations/{interp_id}/entities/page/{page_num}")
async def api_entities_for_page(
    interp_id: str,
    page_num: int,
    document_id: str = Query(..., description="원본 문헌 ID"),
):
    """현재 페이지와 관련된 엔티티를 모두 반환한다.

    목적: 하단 패널 "엔티티" 탭에서 현재 페이지에 연결된 엔티티를 표시한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        return list_entities_for_page(interp_path, document_id, page_num)
    except Exception as e:
        return JSONResponse({"error": f"엔티티 조회 실패: {e}"}, status_code=400)


@app.get("/api/interpretations/{interp_id}/entities/{entity_type}")
async def api_list_entities(
    interp_id: str,
    entity_type: str,
    status: str | None = Query(None, description="상태 필터"),
    block_id: str | None = Query(None, description="TextBlock ID 필터"),
    page: int | None = Query(None, description="페이지 번호 필터 (source_ref.page)"),
    document_id: str | None = Query(None, description="문헌 ID 필터 (source_ref.document_id)"),
):
    """특정 유형의 엔티티 목록을 반환한다."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    filters = {}
    if status:
        filters["status"] = status
    if block_id:
        filters["block_id"] = block_id

    try:
        entities = list_entities(interp_path, entity_type, filters or None)

        # page/document_id 필터 (source_ref, source_refs 기반)
        if page is not None or document_id is not None:
            filtered = []
            for ent in entities:
                refs = ent.get("source_refs") or []
                ref = ent.get("source_ref")
                match = False
                # source_refs 배열 검사
                for r in refs:
                    page_ok = page is None or r.get("page") == page
                    doc_ok = document_id is None or r.get("document_id") == document_id
                    if page_ok and doc_ok:
                        match = True
                        break
                # source_ref 단일 검사 (하위 호환)
                if not match and ref:
                    page_ok = page is None or ref.get("page") == page
                    doc_ok = document_id is None or ref.get("document_id") == document_id
                    if page_ok and doc_ok:
                        match = True
                if match:
                    filtered.append(ent)
            entities = filtered

        return {"entity_type": entity_type, "count": len(entities), "entities": entities}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/interpretations/{interp_id}/entities/{entity_type}/{entity_id}")
async def api_get_entity(interp_id: str, entity_type: str, entity_id: str):
    """단일 엔티티를 조회한다."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        return get_entity(interp_path, entity_type, entity_id)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.put("/api/interpretations/{interp_id}/entities/{entity_type}/{entity_id}")
async def api_update_entity(
    interp_id: str,
    entity_type: str,
    entity_id: str,
    body: EntityUpdateRequest,
    bg: BackgroundTasks,
    no_commit: bool = Query(False, description="True이면 git commit을 건너뛴다 (배치 작업용)"),
):
    """엔티티를 수정한다 (상태 전이 포함).

    목적: 엔티티 필드를 갱신한다. 삭제는 불가능하며 상태 전이만 허용된다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        result = update_entity(interp_path, entity_type, entity_id, body.updates)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"엔티티 수정 중 오류: {e}"}, status_code=500)

    # git commit — 백그라운드로 실행하여 API 즉시 응답
    if not no_commit:
        commit_msg = f"fix: {entity_type} 엔티티 수정 — {entity_id[:8]}"
        bg.add_task(git_commit_interpretation, interp_path, commit_msg)
        result["git"] = "background"
    else:
        result["git"] = {"committed": False, "reason": "no_commit=true"}

    return result


@app.post("/api/interpretations/{interp_id}/entities/text_block/from-source")
async def api_create_textblock_from_source(
    interp_id: str,
    body: TextBlockFromSourceRequest,
):
    """L4 확정 텍스트에서 TextBlock을 생성한다 (source_ref 자동 채움).

    목적: 연구자가 현재 보고 있는 페이지/블록에서 TextBlock을 만들면,
          source_ref가 자동으로 채워진다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        result = create_textblock_from_source(
            interp_path,
            _library_path,
            body.document_id,
            body.part_id,
            body.page_num,
            body.layout_block_id,
            body.original_text,
            body.work_id,
            body.sequence_index,
        )
    except Exception as e:
        return JSONResponse({"error": f"TextBlock 생성 실패: {e}"}, status_code=400)

    # 자동 git commit
    block_info = body.layout_block_id or ""
    commit_msg = f"feat: TextBlock 생성 — page {body.page_num:03d} {block_info}"
    result["git"] = git_commit_interpretation(interp_path, commit_msg)

    return result


class CompositionSourceRef(BaseModel):
    """편성용 소스 참조 하나."""
    document_id: str
    page: int
    layout_block_id: str | None = None
    char_range: list[int] | None = None  # [start, end) or null


class ComposeTextBlockRequest(BaseModel):
    """편성 탭에서 TextBlock을 생성하는 요청.

    여러 LayoutBlock을 합치거나 하나를 쪼개서 TextBlock을 만든다.
    source_refs 배열 순서대로 텍스트를 이어붙인다.
    """
    work_id: str
    sequence_index: int
    original_text: str
    part_id: str
    source_refs: list[CompositionSourceRef]


@app.post("/api/interpretations/{interp_id}/entities/text_block/compose")
async def api_compose_textblock(
    interp_id: str,
    body: ComposeTextBlockRequest,
    bg: BackgroundTasks,
    no_commit: bool = Query(False, description="True이면 git commit을 건너뛴다 (배치 작업용)"),
):
    """편성 탭에서 TextBlock을 생성한다 (source_refs 배열 지원).

    목적: 여러 LayoutBlock을 합치거나, 하나의 LayoutBlock을 쪼개서
          TextBlock을 만든다. source_refs로 출처를 정확히 추적한다.
    입력:
        work_id — 소속 Work UUID.
        sequence_index — 작품 내 순서.
        original_text — 편성된 텍스트 (교정 적용 후).
        part_id — 파트 ID.
        source_refs — 출처 참조 배열 (순서대로 이어붙인 것).
        no_commit — True이면 git commit을 건너뛴다 (쪼개기 등 배치 작업 시).
    출력: {"status": "created", "id": ..., "text_block": {...}}
    """
    import uuid as _uuid

    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    # source_refs에 commit 해시 자동 채움
    import git as _git
    refs_with_commit = []
    for ref in body.source_refs:
        doc_path = _library_path / "documents" / ref.document_id
        commit_hash = None
        try:
            repo = _git.Repo(doc_path)
            commit_hash = repo.head.commit.hexsha
        except Exception:
            pass
        refs_with_commit.append({
            "document_id": ref.document_id,
            "page": ref.page,
            "layout_block_id": ref.layout_block_id,
            "char_range": ref.char_range,
            "layer": "L4",
            "commit": commit_hash,
        })

    # 하위 호환: 첫 번째 ref를 source_ref로도 저장
    first_ref = refs_with_commit[0] if refs_with_commit else None
    source_ref_compat = None
    if first_ref:
        source_ref_compat = {
            k: v for k, v in first_ref.items() if k != "char_range"
        }

    text_block_data = {
        "id": str(_uuid.uuid4()),
        "work_id": body.work_id,
        "sequence_index": body.sequence_index,
        "original_text": body.original_text,
        "normalized_text": None,
        "source_ref": source_ref_compat,
        "source_refs": refs_with_commit,
        "status": "draft",
        "notes": None,
        "metadata": {"part_id": body.part_id},
    }

    try:
        result = create_entity(interp_path, "text_block", text_block_data)
    except Exception as e:
        return JSONResponse({"error": f"TextBlock 생성 실패: {e}"}, status_code=400)

    # git commit — 백그라운드로 실행하여 API 즉시 응답
    if not no_commit:
        block_ids = [r.layout_block_id or "?" for r in body.source_refs]
        commit_msg = f"feat: TextBlock 편성 — {'+'.join(block_ids)}"
        bg.add_task(git_commit_interpretation, interp_path, commit_msg)
        result["git"] = "background"
    else:
        result["git"] = {"committed": False, "reason": "no_commit=true"}
    result["text_block"] = text_block_data

    return result


class SplitTextBlockRequest(BaseModel):
    """TextBlock 쪼개기 요청 본문."""
    original_text_block_id: str
    part_id: str
    pieces: list[str]  # === 구분선으로 나눈 텍스트 조각들


@app.post("/api/interpretations/{interp_id}/entities/text_block/split")
async def api_split_textblock(interp_id: str, body: SplitTextBlockRequest, bg: BackgroundTasks):
    """TextBlock을 여러 조각으로 쪼갠다 (백그라운드 git commit).

    목적: 한 TextBlock을 단락 단위로 나누는 배치 작업.
          모든 조각 생성 + 원본 deprecated 를 한 번의 git commit으로 처리하여
          사용자 대기 시간을 최소화한다.

    처리 순서:
        1. 원본 TextBlock에서 source_refs, work_id 상속
        2. 각 조각마다 새 TextBlock 생성 (git commit 없이)
        3. 원본 TextBlock을 deprecated 전환 (git commit 없이)
        4. 마지막에 한 번만 git commit
    """
    import uuid as _uuid

    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    # 원본 TextBlock 로드
    try:
        original = get_entity(interp_path, "text_block", body.original_text_block_id)
    except FileNotFoundError:
        return JSONResponse(
            {"error": f"원본 TextBlock을 찾을 수 없습니다: {body.original_text_block_id}"},
            status_code=404,
        )

    base_seq = int(original.get("sequence_index", 0))
    work_id = original.get("work_id")
    if not work_id:
        return JSONResponse({"error": "원본 TextBlock의 work_id가 없습니다."}, status_code=400)

    pieces = [str(piece).strip() for piece in (body.pieces or []) if str(piece).strip()]
    if len(pieces) < 2:
        return JSONResponse({"error": "쪼개기 조각은 2개 이상이어야 합니다."}, status_code=400)

    inherited_refs = original.get("source_refs") or []
    # source_ref(단수) 하위호환
    if not inherited_refs and original.get("source_ref"):
        inherited_refs = [original["source_ref"]]

    # source_refs에 현재 원본 commit 해시 채우기
    import git as _git
    for ref in inherited_refs:
        if not ref.get("commit"):
            doc_path = _library_path / "documents" / ref.get("document_id", "")
            try:
                repo = _git.Repo(doc_path)
                ref["commit"] = repo.head.commit.hexsha
            except Exception:
                pass

    # 하위 호환: 첫 번째 ref를 source_ref로도 저장
    first_ref = inherited_refs[0] if inherited_refs else None
    source_ref_compat = None
    if first_ref:
        source_ref_compat = {k: v for k, v in first_ref.items() if k != "char_range"}

    created_ids = []
    errors = []

    # 순서 보존: 원본 뒤에 있는 활성 TextBlock의 sequence를 뒤로 민다.
    try:
        active_blocks = [
            tb for tb in list_entities(interp_path, "text_block")
            if tb.get("id") != body.original_text_block_id
            and tb.get("status") not in ("deprecated", "archived")
            and int(tb.get("sequence_index", 0)) > base_seq
        ]
        active_blocks.sort(key=lambda tb: int(tb.get("sequence_index", 0)))

        shift = len(pieces) - 1
        for tb in active_blocks:
            seq = int(tb.get("sequence_index", 0))
            update_entity(interp_path, "text_block", tb["id"], {"sequence_index": seq + shift})
    except Exception as e:
        return JSONResponse({"error": f"sequence 재배치 실패: {e}"}, status_code=400)

    # 각 조각마다 새 TextBlock 생성 (원래 위치에 연속 삽입)
    for i, piece_text in enumerate(pieces):

        text_block_data = {
            "id": str(_uuid.uuid4()),
            "work_id": work_id,
            "sequence_index": base_seq + i,
            "original_text": piece_text,
            "normalized_text": None,
            "source_ref": source_ref_compat,
            "source_refs": [
                {**r, "char_range": None} for r in inherited_refs
            ],
            "status": "draft",
            "notes": None,
            "metadata": {"part_id": body.part_id},
        }

        try:
            create_entity(interp_path, "text_block", text_block_data)
            created_ids.append(text_block_data["id"])
        except Exception as e:
            errors.append(f"조각 {i + 1}: {e}")

    # 원본 TextBlock을 deprecated 전환
    if created_ids:
        try:
            update_entity(
                interp_path, "text_block",
                body.original_text_block_id,
                {"status": "deprecated"},
            )
        except Exception as e:
            errors.append(f"원본 deprecated 실패: {e}")

    # 백그라운드 git commit — API는 즉시 응답
    commit_msg = f"feat: TextBlock 쪼개기 — {len(created_ids)}개 생성"
    bg.add_task(git_commit_interpretation, interp_path, commit_msg)

    if errors:
        return JSONResponse({
            "created_count": len(created_ids),
            "errors": errors,
            "git": "background",
        }, status_code=207)

    return {
        "created_count": len(created_ids),
        "created_ids": created_ids,
        "deprecated_id": body.original_text_block_id,
        "git": "background",
    }


class ResetCompositionRequest(BaseModel):
    """편성 리셋 요청 본문."""
    text_block_ids: list[str]  # deprecated로 전환할 TextBlock ID 목록


@app.post("/api/interpretations/{interp_id}/entities/text_block/reset")
async def api_reset_composition(interp_id: str, body: ResetCompositionRequest, bg: BackgroundTasks):
    """여러 TextBlock을 한꺼번에 deprecated 전환한다 (백그라운드 git commit).

    목적: 편성 리셋 시 모든 TextBlock을 배치로 deprecated 전환.
          개별 PUT 호출 대신 단일 엔드포인트로 처리하여 속도를 높인다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    deprecated_count = 0
    errors = []

    for tb_id in body.text_block_ids:
        try:
            update_entity(interp_path, "text_block", tb_id, {"status": "deprecated"})
            deprecated_count += 1
        except Exception as e:
            errors.append(f"{tb_id[:8]}: {e}")

    # 백그라운드 git commit — API는 즉시 응답
    commit_msg = f"fix: TextBlock 편성 리셋 — {deprecated_count}개 deprecated"
    bg.add_task(git_commit_interpretation, interp_path, commit_msg)

    if errors:
        return JSONResponse({
            "deprecated_count": deprecated_count,
            "errors": errors,
            "git": "background",
        }, status_code=207)

    return {
        "deprecated_count": deprecated_count,
        "git": "background",
    }


@app.post("/api/interpretations/{interp_id}/entities/work/auto-create")
async def api_auto_create_work(interp_id: str, body: AutoCreateWorkRequest):
    """문헌 메타데이터로부터 Work 엔티티를 자동 생성한다.

    목적: TextBlock 생성에 필요한 Work가 없을 때,
          문헌의 서지정보/매니페스트에서 자동으로 Work를 만든다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        result = auto_create_work(interp_path, _library_path, body.document_id)
    except Exception as e:
        return JSONResponse({"error": f"Work 자동 생성 실패: {e}"}, status_code=400)

    # 기존 Work 반환인 경우 커밋 불필요
    if result["status"] == "created":
        work_title = result["work"].get("title", "")
        commit_msg = f"feat: Work 자동 생성 — {work_title}"
        result["git"] = git_commit_interpretation(interp_path, commit_msg)

    return result


@app.post("/api/interpretations/{interp_id}/entities/tags/{tag_id}/promote")
async def api_promote_tag(
    interp_id: str,
    tag_id: str,
    body: PromoteTagRequest,
):
    """Tag를 Concept으로 승격한다.

    목적: 연구자가 확인한 Tag를 의미 엔티티(Concept)로 격상한다.
          core-schema-v1.3.md 섹션 7: Promotion Flow.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        result = promote_tag_to_concept(
            interp_path,
            tag_id,
            label=body.label,
            scope_work=body.scope_work,
            description=body.description,
        )
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": f"Tag 승격 실패: {e}"}, status_code=400)

    # 자동 git commit
    label = result.get("concept", {}).get("label", "")
    commit_msg = f"feat: Tag → Concept 승격 — {label}"
    result["git"] = git_commit_interpretation(interp_path, commit_msg)

    return result


# ===========================================================================
#  Phase 10-2: LLM 4단 폴백 아키텍처 API
# ===========================================================================

# LLM Router 인스턴스 (serve 시 초기화)
_llm_router = None


def _get_llm_router():
    """LLM Router를 lazy-init한다.

    왜 lazy-init인가:
        _library_path는 serve 명령에서 설정된다.
        LlmConfig가 서고의 .env를 읽으려면 경로가 필요하다.
    """
    global _llm_router
    if _llm_router is None:
        from llm.config import LlmConfig
        from llm.router import LlmRouter
        config = LlmConfig(library_root=_library_path)
        _llm_router = LlmRouter(config)
    return _llm_router


class DraftReviewRequest(BaseModel):
    """Draft 검토 요청 본문."""
    action: str  # "accept" | "modify" | "reject"
    quality_rating: int | None = None
    quality_notes: str | None = None
    modifications: str | None = None


class CompareLayoutRequest(BaseModel):
    """레이아웃 비교 요청 본문."""
    targets: list[str] | None = None


# Draft 저장소 (메모리 — 서버 재시작 시 소멸)
_llm_drafts: dict = {}


@app.get("/api/llm/status")
async def api_llm_status():
    """각 provider의 가용 상태."""
    router = _get_llm_router()
    return await router.get_status()


@app.get("/api/llm/models")
async def api_llm_models():
    """GUI 드롭다운용 모델 목록."""
    router = _get_llm_router()
    return await router.get_available_models()


@app.get("/api/llm/usage")
async def api_llm_usage():
    """이번 달 사용량 요약."""
    router = _get_llm_router()
    return router.usage_tracker.get_monthly_summary()


@app.post("/api/llm/analyze-layout/{doc_id}/{page}")
async def api_analyze_layout(
    doc_id: str,
    page: int,
    force_provider: str | None = Query(None),
    force_model: str | None = Query(None),
):
    """페이지 이미지를 LLM으로 레이아웃 분석. Draft 반환.

    왜 별도 엔드포인트인가:
        기존 layout-editor의 수동 블록 편집과 독립적으로,
        LLM이 제안하는 블록을 Draft로 관리한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    from core.layout_analyzer import analyze_page_layout

    router = _get_llm_router()

    # 페이지 이미지 로드
    page_image = _load_page_image(doc_id, page)
    if not page_image:
        return JSONResponse(
            {"error": f"페이지 이미지 없음: {doc_id} page {page}"},
            status_code=404,
        )

    try:
        draft = await analyze_page_layout(
            router, page_image,
            force_provider=force_provider,
            force_model=force_model,
        )
    except Exception as e:
        return JSONResponse({"error": f"레이아웃 분석 실패: {e}"}, status_code=500)

    # Draft 저장
    _llm_drafts[draft.draft_id] = draft
    return draft.to_dict()


@app.post("/api/llm/compare-layout/{doc_id}/{page}")
async def api_compare_layout(doc_id: str, page: int, body: CompareLayoutRequest):
    """여러 모델로 레이아웃 분석 비교."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    from core.layout_analyzer import compare_layout_analysis

    router = _get_llm_router()

    page_image = _load_page_image(doc_id, page)
    if not page_image:
        return JSONResponse(
            {"error": f"페이지 이미지 없음: {doc_id} page {page}"},
            status_code=404,
        )

    # targets 파싱: ["base44_bridge", "ollama:glm-5:cloud"]
    parsed_targets = None
    if body.targets:
        parsed_targets = []
        for t in body.targets:
            if ":" in t:
                parts = t.split(":", 1)
                parsed_targets.append((parts[0], parts[1]))
            else:
                parsed_targets.append(t)

    try:
        drafts = await compare_layout_analysis(
            router, page_image, targets=parsed_targets,
        )
    except Exception as e:
        return JSONResponse({"error": f"레이아웃 비교 실패: {e}"}, status_code=500)

    # Draft들 저장
    for d in drafts:
        _llm_drafts[d.draft_id] = d

    return [d.to_dict() for d in drafts]


@app.post("/api/llm/drafts/{draft_id}/review")
async def api_review_draft(draft_id: str, body: DraftReviewRequest):
    """Draft를 검토 (accept/modify/reject)."""
    draft = _llm_drafts.get(draft_id)
    if not draft:
        return JSONResponse({"error": f"Draft 없음: {draft_id}"}, status_code=404)

    if body.action == "accept":
        draft.accept(
            quality_rating=body.quality_rating,
            notes=body.quality_notes or "",
        )
    elif body.action == "modify":
        draft.modify(
            modifications=body.modifications or "",
            quality_rating=body.quality_rating,
        )
    elif body.action == "reject":
        draft.reject(reason=body.quality_notes or "")
    else:
        return JSONResponse(
            {"error": f"알 수 없는 action: {body.action}"},
            status_code=400,
        )

    return draft.to_dict()


def _load_page_image(doc_id: str, page: int) -> bytes | None:
    """페이지 이미지를 바이트로 로드한다 (LLM 전송용 리사이즈 포함).

    L1_source에서 PDF를 찾아 해당 페이지를 이미지로 변환.
    또는 이미 이미지 파일이면 직접 읽는다.
    LLM 비전 모델에 보내기 위해 최대 2000px, JPEG 압축을 적용한다.

    왜 리사이즈하는가:
        PDF에서 144 DPI로 추출하면 10MB+ PNG가 된다.
        base64 인코딩 시 14MB+ → Ollama 클라우드 프록시가 타임아웃/거부.
        LLM 비전 모델은 내부적으로 리사이즈하므로 2000px이면 충분하다.
    """
    from ocr.image_utils import resize_for_llm

    if _library_path is None:
        return None

    doc_dir = _library_path / "documents" / doc_id

    # 1. L1_source에서 이미지 파일 직접 찾기 (JPEG)
    source_dir = doc_dir / "L1_source"
    if source_dir.exists():
        # 페이지 번호에 해당하는 이미지 찾기
        for pattern in [
            f"*_p{page:03d}.*",
            f"*_p{page:04d}.*",
            f"*_{page:03d}.*",
            f"*_{page:04d}.*",
            f"page_{page}.*",
            f"p{page}.*",
        ]:
            matches = list(source_dir.glob(pattern))
            for m in matches:
                if m.suffix.lower() in (".jpg", ".jpeg", ".png", ".tiff", ".tif"):
                    raw = m.read_bytes()
                    return resize_for_llm(raw, max_long_side=2000)

    # 2. PDF에서 페이지 추출 (pymupdf/fitz 사용)
    pdf_files = list(source_dir.glob("*.pdf")) if source_dir.exists() else []
    if pdf_files:
        try:
            import fitz  # pymupdf

            doc = fitz.open(str(pdf_files[0]))
            # page는 1-indexed (API 경로), fitz는 0-indexed
            page_idx = page - 1
            if 0 <= page_idx < len(doc):
                pdf_page = doc[page_idx]
                # scale=2.0 → 144 DPI (기본 72 DPI × 2)
                pix = pdf_page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                raw = pix.tobytes("png")
                doc.close()
                return resize_for_llm(raw, max_long_side=2000)
            doc.close()
        except ImportError:
            pass  # pymupdf가 없으면 건너뜀

    return None


# ===========================================================================
#  Phase 10-1: OCR 엔진 연동 API
# ===========================================================================

# OCR Pipeline + Registry 인스턴스 (서버 시작 시 lazy init)
_ocr_registry = None
_ocr_pipeline = None


def _get_ocr_pipeline():
    """OCR Pipeline과 Registry를 lazy-init한다.

    왜 lazy-init인가:
        _library_path는 serve 명령에서 설정된다.
        OcrPipeline은 library_root가 필요하므로 앱 초기화 후에 생성해야 한다.
    """
    global _ocr_registry, _ocr_pipeline
    if _ocr_registry is None:
        from ocr.registry import OcrEngineRegistry
        from ocr.pipeline import OcrPipeline

        _ocr_registry = OcrEngineRegistry()
        _ocr_registry.auto_register()

        # LLM Vision OCR 엔진에 라우터 주입
        # auto_register()에서 LlmOcrEngine이 등록되었으면, 라우터를 연결한다.
        # register() 시점에는 라우터가 없어 is_available()=False였으므로
        # 기본 엔진도 여기서 설정한다.
        llm_engine = _ocr_registry._engines.get("llm_vision")
        if llm_engine is not None:
            router = _get_llm_router()
            llm_engine.set_router(router)
            if _ocr_registry._default_engine_id is None and llm_engine.is_available():
                _ocr_registry._default_engine_id = "llm_vision"

        _ocr_pipeline = OcrPipeline(_ocr_registry, library_root=str(_library_path))

    return _ocr_pipeline, _ocr_registry


class OcrRunRequest(BaseModel):
    """OCR 실행 요청 본문."""
    engine_id: str | None = None        # None이면 기본 엔진
    block_ids: list[str] | None = None  # None이면 전체 블록
    force_provider: str | None = None   # LLM 프로바이더 지정 (llm_vision 엔진 전용)
    force_model: str | None = None      # LLM 모델 지정 (llm_vision 엔진 전용)
    paddle_lang: str | None = None      # PaddleOCR 언어 코드 (paddleocr 엔진 전용: ch, chinese_cht, korean, japan, en)


@app.get("/api/ocr/engines")
async def api_ocr_engines():
    """등록된 OCR 엔진 목록과 사용 가능 여부를 반환한다.

    목적: GUI의 OCR 실행 패널에서 엔진 드롭다운을 채우기 위해 사용한다.
    출력: {
        "engines": [{"engine_id": "paddleocr", "display_name": "PaddleOCR", "available": true, ...}],
        "default_engine": "paddleocr"
    }
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    _pipeline, registry = _get_ocr_pipeline()
    return {
        "engines": registry.list_engines(),
        "default_engine": registry.default_engine_id,
    }


@app.post("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr")
async def api_run_ocr(
    doc_id: str,
    part_id: str,
    page_number: int,
    body: OcrRunRequest,
):
    """페이지의 블록들을 OCR 실행한다.

    목적: 레이아웃 모드에서 OCR을 실행하고 결과를 L2_ocr/에 저장한다.
    입력:
        doc_id — 문헌 ID.
        part_id — 권 식별자.
        page_number — 페이지 번호 (1-indexed).
        body — {"engine_id": null, "block_ids": null}.
    출력: OcrPageResult.to_summary() 형식.
          일부 블록 실패 시에도 성공한 블록 결과를 반환한다 (부분 성공).

    처리 순서:
        1. L3 layout_page.json에서 블록 목록 로드
        2. L1_source에서 이미지 로드 (개별 파일 또는 PDF 페이지 추출)
        3. 각 블록: bbox 크롭 → 전처리 → OCR 엔진 인식
        4. 결과를 L2_ocr/{part_id}_page_{NNN}.json에 저장
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    pipeline, _registry = _get_ocr_pipeline()

    # LLM 엔진용 추가 인자 (force_provider, force_model)
    engine_kwargs = {}
    if body.force_provider:
        engine_kwargs["force_provider"] = body.force_provider
    if body.force_model:
        engine_kwargs["force_model"] = body.force_model

    # PaddleOCR 엔진: 언어 런타임 변경
    if body.paddle_lang and body.engine_id == "paddleocr":
        try:
            paddle_engine = _registry.get_engine("paddleocr")
            paddle_engine.lang = body.paddle_lang
        except Exception:
            pass  # 엔진이 없거나 사용 불가 — 무시 (아래 run_page에서 에러 처리)

    try:
        result = pipeline.run_page(
            doc_id=doc_id,
            part_id=part_id,
            page_number=page_number,
            engine_id=body.engine_id,
            block_ids=body.block_ids,
            **engine_kwargs,
        )
        return result.to_summary()
    except Exception as e:
        return JSONResponse(
            {"error": f"OCR 실행 실패: {e}"},
            status_code=500,
        )


@app.get("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr")
async def api_get_ocr_result(
    doc_id: str,
    part_id: str,
    page_number: int,
):
    """특정 페이지의 OCR 결과(L2)를 반환한다.

    목적: 교정 모드에서 기존 OCR 결과를 로드하기 위해 사용한다.
    입력:
        doc_id — 문헌 ID.
        part_id — 권 식별자.
        page_number — 페이지 번호 (1-indexed).
    출력: L2_ocr/{part_id}_page_{NNN}.json의 내용.
          파일이 없으면 404.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    import json as _json

    filename = f"{part_id}_page_{page_number:03d}.json"
    ocr_path = _library_path / "documents" / doc_id / "L2_ocr" / filename

    if not ocr_path.exists():
        return JSONResponse(
            {"error": f"OCR 결과가 없습니다: {doc_id}/{part_id}/page_{page_number:03d}"},
            status_code=404,
        )

    data = _json.loads(ocr_path.read_text(encoding="utf-8"))
    data["_meta"] = {
        "document_id": doc_id,
        "part_id": part_id,
        "page_number": page_number,
        "file_path": str(ocr_path.relative_to(_library_path)),
    }
    return data


@app.delete("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr")
async def api_delete_ocr_result(
    doc_id: str,
    part_id: str,
    page_number: int,
):
    """특정 페이지의 OCR 결과(L2)를 휴지통으로 이동한다."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    filename = f"{part_id}_page_{page_number:03d}.json"
    legacy_filename = f"page_{page_number:03d}.json"
    ocr_path = doc_path / "L2_ocr" / filename

    if not ocr_path.exists():
        legacy_path = doc_path / "L2_ocr" / legacy_filename
        if legacy_path.exists():
            ocr_path = legacy_path
            filename = legacy_filename
        else:
            return JSONResponse(
                {"error": f"삭제할 OCR 결과가 없습니다: {doc_id}/{part_id}/page_{page_number:03d}"},
                status_code=404,
            )

    trash_dir = _library_path / ".trash" / "ocr"
    trash_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    trash_name = f"{timestamp}_{doc_id}_{filename}"
    trash_path = trash_dir / trash_name

    try:
        shutil.move(str(ocr_path), str(trash_path))
    except Exception as e:
        return JSONResponse({"error": f"OCR 결과 삭제 실패: {e}"}, status_code=500)

    return {
        "status": "trashed",
        "document_id": doc_id,
        "part_id": part_id,
        "page_number": page_number,
        "trash_path": str(trash_path.relative_to(_library_path)).replace("\\", "/"),
    }


@app.delete("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr/{block_id}")
async def api_delete_ocr_block_result(
    doc_id: str,
    part_id: str,
    page_number: int,
    block_id: str,
    index: int = Query(-1),
):
    """특정 OCR 결과 1건을 block_id + index로 강제 매칭하여 삭제한다.

    왜 이렇게 하는가:
      같은 페이지에서 layout_block_id가 겹치거나 중복 OCR 항목이 생길 수 있다.
      block_id만으로 삭제하면 여러 항목이 함께 지워질 위험이 있으므로,
      프론트가 보낸 index와 block_id를 동시에 검증해 단건만 삭제한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    import json as _json

    filename = f"{part_id}_page_{page_number:03d}.json"
    legacy_filename = f"page_{page_number:03d}.json"
    ocr_path = doc_path / "L2_ocr" / filename

    if not ocr_path.exists():
        legacy_path = doc_path / "L2_ocr" / legacy_filename
        if legacy_path.exists():
            ocr_path = legacy_path
        else:
            return JSONResponse(
                {"error": f"OCR 결과가 없습니다: {doc_id}/{part_id}/page_{page_number:03d}"},
                status_code=404,
            )

    try:
        data = _json.loads(ocr_path.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"error": f"OCR 파일 읽기 실패: {e}"}, status_code=500)

    ocr_results = data.get("ocr_results")
    if not isinstance(ocr_results, list):
        return JSONResponse({"error": "OCR 결과 형식이 올바르지 않습니다."}, status_code=500)

    if index < 0 or index >= len(ocr_results):
        return JSONResponse(
            {
                "error": "삭제할 OCR 항목 index가 유효하지 않습니다.",
                "index": index,
                "total": len(ocr_results),
            },
            status_code=400,
        )

    normalized_block_id = str(block_id or "").strip()
    target = ocr_results[index]
    target_block_id = str(target.get("layout_block_id") or "").strip()

    if target_block_id != normalized_block_id:
        return JSONResponse(
            {
                "error": "block_id와 OCR 항목 index가 일치하지 않습니다.",
                "expected_block_id": normalized_block_id,
                "actual_block_id": target_block_id,
                "index": index,
            },
            status_code=409,
        )

    deleted_item = ocr_results.pop(index)
    data["ocr_results"] = ocr_results

    try:
        ocr_path.write_text(
            _json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        return JSONResponse({"error": f"OCR 파일 저장 실패: {e}"}, status_code=500)

    return {
        "status": "deleted",
        "document_id": doc_id,
        "part_id": part_id,
        "page_number": page_number,
        "block_id": normalized_block_id,
        "index": index,
        "remaining": len(ocr_results),
        "deleted_text": "".join(
            [(line.get("text") or "") for line in (deleted_item.get("lines") or [])]
        ),
    }


@app.post("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr/{block_id}")
async def api_rerun_ocr_block(
    doc_id: str,
    part_id: str,
    page_number: int,
    block_id: str,
    body: OcrRunRequest,
):
    """특정 블록만 OCR을 재실행한다.

    목적: 하나의 블록만 다시 OCR 처리하고 기존 L2 결과에 반영한다.
          인식 결과가 좋지 않은 블록을 개별적으로 재시도할 때 사용한다.
    입력:
        doc_id — 문헌 ID.
        part_id — 권 식별자.
        page_number — 페이지 번호 (1-indexed).
        block_id — 재실행할 블록 ID (L3 layout의 block_id).
        body — {"engine_id": null} (다른 엔진으로 시도 가능).
    출력: OcrPageResult.to_summary() 형식 (해당 블록만 포함).
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    pipeline, _registry = _get_ocr_pipeline()

    # PaddleOCR 엔진: 언어 런타임 변경
    if body.paddle_lang and body.engine_id == "paddleocr":
        try:
            paddle_engine = _registry.get_engine("paddleocr")
            paddle_engine.lang = body.paddle_lang
        except Exception:
            pass

    # LLM 엔진용 추가 인자
    engine_kwargs = {}
    if body.force_provider:
        engine_kwargs["force_provider"] = body.force_provider
    if body.force_model:
        engine_kwargs["force_model"] = body.force_model

    try:
        result = pipeline.run_block(
            doc_id=doc_id,
            part_id=part_id,
            page_number=page_number,
            block_id=block_id,
            engine_id=body.engine_id,
            **engine_kwargs,
        )
        return result.to_summary()
    except Exception as e:
        return JSONResponse(
            {"error": f"OCR 블록 재실행 실패: {e}"},
            status_code=500,
        )


# ===========================================================================
#  Phase 10-3: 정렬 엔진 — OCR ↔ 텍스트 대조 API
# ===========================================================================

# ── 이체자 사전 관리 (다중 사전 지원) ──
# resources/ 폴더에 여러 사전 파일이 공존할 수 있다.
# 활성 사전 이름은 resources/.active_variant_dict 에 기록.
_variant_dict = None
_variant_dict_name: str | None = None  # 현재 로드된 사전 파일명


def _get_resources_dir() -> str:
    """resources/ 디렉토리의 절대 경로를 반환한다."""
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "resources")
    )


def _get_active_dict_name() -> str:
    """활성 이체자 사전 파일명을 반환한다.

    resources/.active_variant_dict 파일에 기록된 이름을 읽는다.
    파일이 없으면 기본값 'variant_chars'를 반환한다.
    """
    marker = os.path.join(_get_resources_dir(), ".active_variant_dict")
    if os.path.exists(marker):
        with open(marker, "r", encoding="utf-8") as f:
            name = f.read().strip()
            if name:
                return name
    return "variant_chars"


def _set_active_dict_name(name: str) -> None:
    """활성 이체자 사전 이름을 저장한다."""
    marker = os.path.join(_get_resources_dir(), ".active_variant_dict")
    with open(marker, "w", encoding="utf-8") as f:
        f.write(name)


def _dict_name_to_path(name: str) -> str:
    """사전 이름을 파일 경로로 변환한다. 예: 'variant_chars' → '.../resources/variant_chars.json'"""
    return os.path.join(_get_resources_dir(), f"{name}.json")


def _get_variant_dict(name: str | None = None):
    """이체자 사전을 로드한다.

    name이 None이면 활성 사전을 로드한다.
    이미 같은 이름이 로드되어 있으면 캐시를 반환한다.
    """
    global _variant_dict, _variant_dict_name
    from core.alignment import VariantCharDict

    if name is None:
        name = _get_active_dict_name()

    # 캐시된 사전과 같은 이름이면 그대로 반환
    if _variant_dict is not None and _variant_dict_name == name:
        return _variant_dict

    path = _dict_name_to_path(name)
    _variant_dict = VariantCharDict(dict_path=path)
    _variant_dict_name = name
    return _variant_dict


def _save_variant_dict(vd, name: str | None = None) -> str:
    """이체자 사전을 파일로 저장하고 경로를 반환한다."""
    if name is None:
        name = _get_active_dict_name()
    path = _dict_name_to_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    vd.save(path)
    return path


def _list_variant_dicts() -> list[dict]:
    """resources/ 폴더의 이체자 사전 파일 목록을 반환한다.

    variant_chars*.json 패턴에 맞는 파일만 포함한다.
    반환: [{"name": "variant_chars", "path": "...", "active": True}, ...]
    """
    import glob as glob_mod
    resources = _get_resources_dir()
    active = _get_active_dict_name()
    result = []
    # variant_ 로 시작하는 JSON 파일 탐색
    for path in sorted(glob_mod.glob(os.path.join(resources, "variant_*.json"))):
        basename = os.path.basename(path)
        name = basename.rsplit(".json", 1)[0]
        result.append({
            "name": name,
            "file": basename,
            "active": name == active,
        })
    return result


@app.post("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/alignment")
async def api_run_alignment(
    doc_id: str,
    part_id: str,
    page_number: int,
):
    """페이지의 OCR 결과(L2)와 확정 텍스트(L4)를 글자 단위로 대조한다.

    목적: 교정 모드에서 OCR 인식 결과와 사람이 확정한 텍스트의 차이를 시각적으로 보여준다.
    입력:
        doc_id — 문헌 ID.
        part_id — 권 식별자.
        page_number — 페이지 번호 (1-indexed).
    전제 조건:
        L2(OCR 결과)와 L4(확정 텍스트)가 모두 있어야 한다.
    출력: {
        "blocks": [BlockAlignment.to_dict(), ...],  # 블록별 대조 결과
        "page_stats": AlignmentStats.to_dict()       # 페이지 전체 통계 (* 블록)
    }
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = _library_path / "documents" / doc_id
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    from core.alignment import align_page

    variant_dict = _get_variant_dict()

    try:
        block_results = align_page(
            library_root=str(_library_path),
            doc_id=doc_id,
            part_id=part_id,
            page_number=page_number,
            variant_dict=variant_dict,
        )
    except Exception as e:
        return JSONResponse(
            {"error": f"대조 실행 실패: {e}"},
            status_code=500,
        )

    # 에러만 있는 경우
    if len(block_results) == 1 and block_results[0].error:
        return JSONResponse(
            {"error": block_results[0].error},
            status_code=404,
        )

    # 페이지 전체 통계 (* 블록)
    page_stats = None
    blocks_output = []
    for br in block_results:
        blocks_output.append(br.to_dict())
        if br.layout_block_id == "*" and br.stats:
            page_stats = br.stats.to_dict()

    return {
        "blocks": blocks_output,
        "page_stats": page_stats,
    }


# ── 기존 호환 API (활성 사전에 프록시) ──

@app.get("/api/alignment/variant-dict")
async def api_get_variant_dict():
    """활성 이체자 사전 내용을 반환한다. (기존 API 호환)"""
    variant_dict = _get_variant_dict()
    return {
        "variants": variant_dict.to_dict(),
        "size": variant_dict.size,
        "pair_count": variant_dict.pair_count,
        "active_name": _get_active_dict_name(),
    }


class VariantPairRequest(BaseModel):
    """이체자 쌍 추가/삭제 요청."""
    char_a: str
    char_b: str


@app.post("/api/alignment/variant-dict")
async def api_add_variant_pair(body: VariantPairRequest):
    """활성 사전에 이체자 쌍을 추가한다. (기존 API 호환)"""
    variant_dict = _get_variant_dict()

    if not body.char_a or not body.char_b:
        return JSONResponse({"error": "두 글자 모두 입력해야 합니다."}, status_code=400)
    if body.char_a == body.char_b:
        return JSONResponse({"error": "같은 글자는 이체자로 등록할 수 없습니다."}, status_code=400)

    variant_dict.add_pair(body.char_a, body.char_b)
    _save_variant_dict(variant_dict)
    return {"status": "ok", "size": variant_dict.size}


@app.delete("/api/alignment/variant-dict")
async def api_delete_variant_pair(body: VariantPairRequest):
    """활성 사전에서 이체자 쌍을 삭제한다."""
    variant_dict = _get_variant_dict()

    if not body.char_a or not body.char_b:
        return JSONResponse({"error": "두 글자 모두 입력해야 합니다."}, status_code=400)

    removed = variant_dict.remove_pair(body.char_a, body.char_b)
    if not removed:
        return JSONResponse({"error": "해당 이체자 쌍이 존재하지 않습니다."}, status_code=404)

    _save_variant_dict(variant_dict)
    return {"status": "ok", "removed": True, "size": variant_dict.size}


class VariantImportRequest(BaseModel):
    """이체자 대량 가져오기 요청."""
    text: str
    format: str = "auto"


@app.post("/api/alignment/variant-dict/import")
async def api_import_variant_dict(body: VariantImportRequest):
    """활성 사전에 이체자 데이터를 대량 가져온다. (기존 API 호환)"""
    if not body.text or not body.text.strip():
        return JSONResponse(
            {"error": "가져올 데이터가 비어 있습니다."}, status_code=400
        )

    variant_dict = _get_variant_dict()
    result = variant_dict.import_bulk(body.text, body.format)

    if result["added"] > 0:
        _save_variant_dict(variant_dict)

    return {
        "status": "ok",
        "added": result["added"],
        "skipped": result["skipped"],
        "errors": result["errors"],
        "size": variant_dict.size,
    }


# ── 다중 사전 관리 API ──

@app.get("/api/variant-dicts")
async def api_list_variant_dicts():
    """resources/ 폴더의 이체자 사전 목록을 반환한다.

    출력: { "dicts": [{"name": "variant_chars", "file": "variant_chars.json", "active": true}] }
    """
    return {"dicts": _list_variant_dicts()}


@app.get("/api/variant-dicts/{name}")
async def api_get_variant_dict_by_name(name: str):
    """특정 이름의 이체자 사전 내용을 반환한다."""
    path = _dict_name_to_path(name)
    if not os.path.exists(path):
        return JSONResponse({"error": f"사전을 찾을 수 없습니다: {name}"}, status_code=404)

    vd = _get_variant_dict(name)
    return {
        "name": name,
        "variants": vd.to_dict(),
        "size": vd.size,
        "pair_count": vd.pair_count,
        "active": name == _get_active_dict_name(),
    }


class CreateDictRequest(BaseModel):
    """새 사전 생성 요청."""
    name: str


@app.post("/api/variant-dicts")
async def api_create_variant_dict(body: CreateDictRequest):
    """빈 이체자 사전을 새로 생성한다.

    이름은 자동으로 'variant_' 접두사가 붙는다.
    예: 'kangxi' → 'variant_kangxi'
    """
    import re
    # variant_ 접두사 자동 추가
    raw_name = body.name.strip()
    if not raw_name.startswith("variant_"):
        raw_name = f"variant_{raw_name}"

    if not re.match(r'^variant_[a-zA-Z0-9_\-]+$', raw_name):
        return JSONResponse(
            {"error": "사전 이름은 영문, 숫자, 밑줄, 하이픈만 사용할 수 있습니다."},
            status_code=400,
        )

    path = _dict_name_to_path(raw_name)
    if os.path.exists(path):
        return JSONResponse({"error": f"이미 존재하는 사전입니다: {raw_name}"}, status_code=409)

    from core.alignment import VariantCharDict
    vd = VariantCharDict(dict_path=None)  # 빈 사전
    vd.save(path)
    return {"status": "ok", "name": raw_name}


class CopyDictRequest(BaseModel):
    """사전 복제 요청."""
    new_name: str


@app.post("/api/variant-dicts/{name}/copy")
async def api_copy_variant_dict(name: str, body: CopyDictRequest):
    """기존 사전을 새 이름으로 복제한다."""
    import re
    new_name = body.new_name.strip()
    if not new_name.startswith("variant_"):
        new_name = f"variant_{new_name}"

    if not re.match(r'^variant_[a-zA-Z0-9_\-]+$', new_name):
        return JSONResponse(
            {"error": "사전 이름은 영문, 숫자, 밑줄, 하이픈만 사용할 수 있습니다."},
            status_code=400,
        )

    src_path = _dict_name_to_path(name)
    if not os.path.exists(src_path):
        return JSONResponse({"error": f"원본 사전을 찾을 수 없습니다: {name}"}, status_code=404)

    dst_path = _dict_name_to_path(new_name)
    if os.path.exists(dst_path):
        return JSONResponse({"error": f"이미 존재하는 사전입니다: {new_name}"}, status_code=409)

    shutil.copy2(src_path, dst_path)
    return {"status": "ok", "name": new_name}


@app.delete("/api/variant-dicts/{name}")
async def api_delete_variant_dict(name: str):
    """사전 파일을 삭제한다 (휴지통으로 이동).

    활성 사전은 삭제할 수 없다.
    """
    active = _get_active_dict_name()
    if name == active:
        return JSONResponse(
            {"error": "활성 사전은 삭제할 수 없습니다. 먼저 다른 사전을 활성화하세요."},
            status_code=400,
        )

    path = _dict_name_to_path(name)
    if not os.path.exists(path):
        return JSONResponse({"error": f"사전을 찾을 수 없습니다: {name}"}, status_code=404)

    # 휴지통으로 이동 (CLAUDE.md: 영구 삭제 금지)
    try:
        import subprocess
        subprocess.run(
            ["powershell", "-Command",
             f"Add-Type -AssemblyName Microsoft.VisualBasic; "
             f"[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
             f"'{path}', 'OnlyErrorDialogs', 'SendToRecycleBin')"],
            check=True, capture_output=True,
        )
    except Exception:
        # PowerShell 실패 시 (Linux 등) — 이름 변경으로 "삭제"
        trash_path = path + ".deleted"
        os.rename(path, trash_path)

    return {"status": "ok", "deleted": name}


@app.put("/api/variant-dicts/{name}/activate")
async def api_activate_variant_dict(name: str):
    """지정한 사전을 활성 사전으로 설정한다."""
    path = _dict_name_to_path(name)
    if not os.path.exists(path):
        return JSONResponse({"error": f"사전을 찾을 수 없습니다: {name}"}, status_code=404)

    _set_active_dict_name(name)

    # 캐시 무효화 → 다음 _get_variant_dict() 호출 시 새 사전 로드
    global _variant_dict, _variant_dict_name
    _variant_dict = None
    _variant_dict_name = None

    return {"status": "ok", "active": name}


@app.post("/api/variant-dicts/{name}/pair")
async def api_add_pair_to_dict(name: str, body: VariantPairRequest):
    """지정한 사전에 이체자 쌍을 추가한다."""
    path = _dict_name_to_path(name)
    if not os.path.exists(path):
        return JSONResponse({"error": f"사전을 찾을 수 없습니다: {name}"}, status_code=404)
    if not body.char_a or not body.char_b:
        return JSONResponse({"error": "두 글자 모두 입력해야 합니다."}, status_code=400)
    if body.char_a == body.char_b:
        return JSONResponse({"error": "같은 글자는 이체자로 등록할 수 없습니다."}, status_code=400)

    vd = _get_variant_dict(name)
    vd.add_pair(body.char_a, body.char_b)
    _save_variant_dict(vd, name)
    return {"status": "ok", "size": vd.size}


@app.delete("/api/variant-dicts/{name}/pair")
async def api_delete_pair_from_dict(name: str, body: VariantPairRequest):
    """지정한 사전에서 이체자 쌍을 삭제한다."""
    path = _dict_name_to_path(name)
    if not os.path.exists(path):
        return JSONResponse({"error": f"사전을 찾을 수 없습니다: {name}"}, status_code=404)

    vd = _get_variant_dict(name)
    removed = vd.remove_pair(body.char_a, body.char_b)
    if not removed:
        return JSONResponse({"error": "해당 이체자 쌍이 존재하지 않습니다."}, status_code=404)

    _save_variant_dict(vd, name)
    return {"status": "ok", "removed": True, "size": vd.size}


@app.post("/api/variant-dicts/{name}/import")
async def api_import_to_dict(name: str, body: VariantImportRequest):
    """지정한 사전에 이체자 데이터를 대량 가져온다."""
    path = _dict_name_to_path(name)
    if not os.path.exists(path):
        return JSONResponse({"error": f"사전을 찾을 수 없습니다: {name}"}, status_code=404)
    if not body.text or not body.text.strip():
        return JSONResponse({"error": "가져올 데이터가 비어 있습니다."}, status_code=400)

    vd = _get_variant_dict(name)
    result = vd.import_bulk(body.text, body.format)

    if result["added"] > 0:
        _save_variant_dict(vd, name)

    return {
        "status": "ok",
        "added": result["added"],
        "skipped": result["skipped"],
        "errors": result["errors"],
        "size": vd.size,
    }


@app.get("/api/variant-dicts/{name}/export")
async def api_export_variant_dict(name: str, format: str = "json"):
    """이체자 사전을 파일로 내보낸다.

    format: "json" (기본) 또는 "csv"
    """
    path = _dict_name_to_path(name)
    if not os.path.exists(path):
        return JSONResponse({"error": f"사전을 찾을 수 없습니다: {name}"}, status_code=404)

    vd = _get_variant_dict(name)

    if format == "csv":
        from starlette.responses import Response
        csv_text = vd.export_csv()
        return Response(
            content=csv_text,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
        )
    else:
        # JSON: 원본 파일을 그대로 반환
        from starlette.responses import FileResponse
        return FileResponse(
            path=path,
            media_type="application/json; charset=utf-8",
            filename=f"{name}.json",
        )


# ───────────────────────────────────────────────────
# 일괄 교정 (Batch Correction)
# ───────────────────────────────────────────────────


class BatchCorrectionRequest(BaseModel):
    """일괄 교정 요청."""
    part_id: str
    page_start: int
    page_end: int
    original_char: str
    corrected_char: str
    correction_type: str = "ocr_error"
    note: str | None = None


@app.post("/api/documents/{doc_id}/batch-corrections/preview")
async def api_batch_correction_preview(doc_id: str, body: BatchCorrectionRequest):
    """일괄 교정 미리보기 — 대상 글자가 어느 페이지에서 몇 건 매칭되는지 반환한다."""
    doc_path = _library_path / "documents" / doc_id

    from core.document import search_char_in_pages

    results = search_char_in_pages(
        doc_path, body.part_id, body.page_start, body.page_end, body.original_char
    )
    total = sum(r["count"] for r in results)
    return {
        "original_char": body.original_char,
        "corrected_char": body.corrected_char,
        "total_matches": total,
        "pages": results,
    }


@app.post("/api/documents/{doc_id}/batch-corrections/execute")
async def api_batch_correction_execute(
    doc_id: str,
    body: BatchCorrectionRequest,
    background_tasks: BackgroundTasks,
):
    """일괄 교정 실행 — 매칭되는 모든 위치에 교정을 적용한다."""
    doc_path = _library_path / "documents" / doc_id

    from core.document import apply_batch_corrections, git_commit_document

    result = apply_batch_corrections(
        doc_path,
        body.part_id,
        body.page_start,
        body.page_end,
        body.original_char,
        body.corrected_char,
        body.correction_type,
        body.note,
    )

    # git commit은 백그라운드로 (성능)
    if result["total_corrected"] > 0:
        msg = (
            f"fix: 일괄 교정 '{body.original_char}'→'{body.corrected_char}' "
            f"({result['total_corrected']}건, {result['pages_affected']}페이지)"
        )
        background_tasks.add_task(git_commit_document, doc_path, msg)

    return result


# ───────────────────────────────────────────────────
# Phase 11-1: 표점 프리셋 조회
# ───────────────────────────────────────────────────

@app.get("/api/punctuation-presets")
async def api_punctuation_presets():
    """표점 부호 프리셋 목록을 반환한다."""
    presets_path = Path(__file__).parent.parent.parent / "resources" / "punctuation_presets.json"
    if not presets_path.exists():
        return {"presets": [], "custom": []}
    import json as _json
    with open(presets_path, encoding="utf-8") as f:
        return _json.load(f)


# ───────────────────────────────────────────────────
# Phase 11-1: L5 표점(句讀) API
# ───────────────────────────────────────────────────


class PunctuationSaveRequest(BaseModel):
    """표점 저장 요청."""
    block_id: str
    marks: list


class MarkAddRequest(BaseModel):
    """개별 표점 추가 요청."""
    target: dict
    before: str | None = None
    after: str | None = None


@app.get("/api/interpretations/{interp_id}/pages/{page_num}/punctuation")
async def api_get_punctuation(interp_id: str, page_num: int, block_id: str = Query(...)):
    """표점 조회.

    목적: 특정 블록의 L5 표점 데이터를 반환한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 저장소 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    # part_id는 문헌에서 자동 추론 (현재는 "main" 기본값)
    part_id = "main"
    data = load_punctuation(interp_path, part_id, page_num, block_id)
    return data


@app.put("/api/interpretations/{interp_id}/pages/{page_num}/punctuation")
async def api_save_punctuation(interp_id: str, page_num: int, body: PunctuationSaveRequest):
    """표점 저장 (전체 덮어쓰기).

    목적: 블록의 표점 데이터를 저장한다. 스키마 검증 후 파일 기록.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 저장소 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    part_id = "main"
    data = {"block_id": body.block_id, "marks": body.marks}

    try:
        file_path = save_punctuation(interp_path, part_id, page_num, data)
        # git commit
        try:
            git_commit_interpretation(interp_path, f"feat: L5 표점 저장 — page {page_num}")
        except Exception:
            pass  # git 실패는 저장 성공에 영향 없음
        return {"success": True, "file_path": str(file_path.relative_to(_library_path))}
    except Exception as e:
        return JSONResponse({"error": f"표점 저장 실패: {e}"}, status_code=400)


@app.post("/api/interpretations/{interp_id}/pages/{page_num}/punctuation/{block_id}/marks")
async def api_add_mark(interp_id: str, page_num: int, block_id: str, body: MarkAddRequest):
    """개별 표점 추가."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_punctuation(interp_path, part_id, page_num, block_id)
    mark = {"target": body.target, "before": body.before, "after": body.after}
    result = add_mark(data, mark)

    try:
        save_punctuation(interp_path, part_id, page_num, data)
        return JSONResponse(result, status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.delete("/api/interpretations/{interp_id}/pages/{page_num}/punctuation/{block_id}/marks/{mark_id}")
async def api_delete_mark(interp_id: str, page_num: int, block_id: str, mark_id: str):
    """개별 표점 삭제."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_punctuation(interp_path, part_id, page_num, block_id)
    removed = remove_mark(data, mark_id)

    if not removed:
        return JSONResponse({"error": f"표점 '{mark_id}'를 찾을 수 없습니다."}, status_code=404)

    save_punctuation(interp_path, part_id, page_num, data)
    return JSONResponse(status_code=204, content=None)


@app.get("/api/interpretations/{interp_id}/pages/{page_num}/punctuation/{block_id}/preview")
async def api_punctuation_preview(interp_id: str, page_num: int, block_id: str):
    """합성 텍스트 미리보기.

    L4 원문에 표점을 적용한 결과 + 문장 분리를 반환.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    # 표점 로드
    punct_data = load_punctuation(interp_path, part_id, page_num, block_id)

    # L4 원문 로드 (해석 저장소의 L5_reading에서)
    layer_result = get_layer_content(interp_path, "L5_reading", "main_text", part_id, page_num)
    original_text = ""
    if layer_result.get("exists") and isinstance(layer_result.get("content"), str):
        original_text = layer_result["content"]

    rendered = render_punctuated_text(original_text, punct_data.get("marks", []))
    sentences = split_sentences(original_text, punct_data.get("marks", []))

    return {
        "original_text": original_text,
        "rendered": rendered,
        "sentences": sentences,
    }


# ───────────────────────────────────────────────────
# Phase 11-1: L5 현토(懸吐) API
# ───────────────────────────────────────────────────


class HyeontoSaveRequest(BaseModel):
    """현토 저장 요청."""
    block_id: str
    annotations: list


class AnnotationAddRequest(BaseModel):
    """개별 현토 추가 요청."""
    target: dict
    position: str = "after"
    text: str
    category: str | None = None


@app.get("/api/interpretations/{interp_id}/pages/{page_num}/hyeonto")
async def api_get_hyeonto(interp_id: str, page_num: int, block_id: str = Query(...)):
    """현토 조회."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 저장소 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    part_id = "main"
    data = load_hyeonto(interp_path, part_id, page_num, block_id)
    return data


@app.put("/api/interpretations/{interp_id}/pages/{page_num}/hyeonto")
async def api_save_hyeonto(interp_id: str, page_num: int, body: HyeontoSaveRequest):
    """현토 저장 (전체 덮어쓰기)."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 저장소 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    part_id = "main"
    data = {"block_id": body.block_id, "annotations": body.annotations}

    try:
        file_path = save_hyeonto(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(interp_path, f"feat: L5 현토 저장 — page {page_num}")
        except Exception:
            pass
        return {"success": True, "file_path": str(file_path.relative_to(_library_path))}
    except Exception as e:
        return JSONResponse({"error": f"현토 저장 실패: {e}"}, status_code=400)


@app.post("/api/interpretations/{interp_id}/pages/{page_num}/hyeonto/{block_id}/annotations")
async def api_add_annotation(interp_id: str, page_num: int, block_id: str, body: AnnotationAddRequest):
    """개별 현토 추가."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_hyeonto(interp_path, part_id, page_num, block_id)
    annotation = {
        "target": body.target,
        "position": body.position,
        "text": body.text,
        "category": body.category,
    }
    result = add_annotation(data, annotation)

    try:
        save_hyeonto(interp_path, part_id, page_num, data)
        return JSONResponse(result, status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.delete("/api/interpretations/{interp_id}/pages/{page_num}/hyeonto/{block_id}/annotations/{ann_id}")
async def api_delete_annotation(interp_id: str, page_num: int, block_id: str, ann_id: str):
    """개별 현토 삭제."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_hyeonto(interp_path, part_id, page_num, block_id)
    removed = remove_annotation(data, ann_id)

    if not removed:
        return JSONResponse({"error": f"현토 '{ann_id}'를 찾을 수 없습니다."}, status_code=404)

    save_hyeonto(interp_path, part_id, page_num, data)
    return JSONResponse(status_code=204, content=None)


@app.get("/api/interpretations/{interp_id}/pages/{page_num}/hyeonto/{block_id}/preview")
async def api_hyeonto_preview(interp_id: str, page_num: int, block_id: str):
    """현토 합성 텍스트 미리보기.

    표점이 있으면 함께 적용한 결과를 반환.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    # L4 원문 로드
    layer_result = get_layer_content(interp_path, "L5_reading", "main_text", part_id, page_num)
    original_text = ""
    if layer_result.get("exists") and isinstance(layer_result.get("content"), str):
        original_text = layer_result["content"]

    # 현토 로드
    ht_data = load_hyeonto(interp_path, part_id, page_num, block_id)
    rendered = render_hyeonto_text(original_text, ht_data.get("annotations", []))

    # 표점도 함께 적용한 결과
    punct_data = load_punctuation(interp_path, part_id, page_num, block_id)
    # 표점 + 현토 합성: 먼저 현토 적용 후 표점 적용
    combined = render_punctuated_text(rendered, punct_data.get("marks", []))

    return {
        "original_text": original_text,
        "rendered_hyeonto": rendered,
        "rendered_combined": combined,
    }


# ───────────────────────────────────────────────────
# Phase 11-2: L6 번역(Translation) API
# ───────────────────────────────────────────────────

from core.translation import (
    add_translation,
    get_translation_status,
    load_translations,
    remove_translation,
    save_translations,
    update_translation,
)
from core.translation_llm import commit_translation_draft


class TranslationAddRequest(BaseModel):
    """수동 번역 입력 요청."""
    source: dict
    source_text: str
    translation: str
    target_language: str = "ko"
    hyeonto_text: str | None = None


class TranslationUpdateRequest(BaseModel):
    """번역 수정 요청."""
    translation: str | None = None
    status: str | None = None


class TranslationCommitRequest(BaseModel):
    """Draft 확정 요청."""
    modifications: dict | None = None


@app.get("/api/interpretations/{interp_id}/pages/{page_num}/translation")
async def api_get_translations(interp_id: str, page_num: int):
    """번역 조회.

    목적: 특정 페이지의 L6 번역 데이터를 반환한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 저장소 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    part_id = "main"
    data = load_translations(interp_path, part_id, page_num)
    return data


@app.get("/api/interpretations/{interp_id}/pages/{page_num}/translation/status")
async def api_translation_status(interp_id: str, page_num: int):
    """번역 상태 요약.

    목적: 페이지의 번역 진행 상황을 한눈에 파악.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"
    data = load_translations(interp_path, part_id, page_num)
    return get_translation_status(data)


@app.post("/api/interpretations/{interp_id}/pages/{page_num}/translation")
async def api_add_translation(interp_id: str, page_num: int, body: TranslationAddRequest):
    """수동 번역 입력.

    목적: 사용자가 직접 번역을 입력한다. translator.type = "human", status = "accepted".
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_translations(interp_path, part_id, page_num)

    entry = {
        "source": body.source,
        "source_text": body.source_text,
        "hyeonto_text": body.hyeonto_text,
        "target_language": body.target_language,
        "translation": body.translation,
        "translator": {"type": "human", "model": None, "draft_id": None},
        "status": "accepted",
        "reviewed_by": None,
        "reviewed_at": None,
    }
    result = add_translation(data, entry)

    try:
        save_translations(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(interp_path, f"feat: L6 번역 추가 — page {page_num}")
        except Exception:
            pass
        return JSONResponse(result, status_code=201)
    except Exception as e:
        return JSONResponse({"error": f"번역 저장 실패: {e}"}, status_code=400)


@app.put("/api/interpretations/{interp_id}/pages/{page_num}/translation/{translation_id}")
async def api_update_translation(
    interp_id: str, page_num: int, translation_id: str, body: TranslationUpdateRequest
):
    """번역 수정."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_translations(interp_path, part_id, page_num)
    updates = {}
    if body.translation is not None:
        updates["translation"] = body.translation
    if body.status is not None:
        updates["status"] = body.status

    result = update_translation(data, translation_id, updates)
    if result is None:
        return JSONResponse({"error": f"번역 '{translation_id}'를 찾을 수 없습니다."}, status_code=404)

    try:
        save_translations(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(interp_path, f"feat: L6 번역 수정 — page {page_num}")
        except Exception:
            pass
        return result
    except Exception as e:
        return JSONResponse({"error": f"번역 저장 실패: {e}"}, status_code=400)


@app.post("/api/interpretations/{interp_id}/pages/{page_num}/translation/{translation_id}/commit")
async def api_commit_translation(
    interp_id: str, page_num: int, translation_id: str, body: TranslationCommitRequest
):
    """Draft 확정.

    목적: 연구자가 Draft를 검토 후 확정. status → "accepted".
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_translations(interp_path, part_id, page_num)
    result = commit_translation_draft(data, translation_id, body.modifications)

    if result is None:
        return JSONResponse({"error": f"번역 '{translation_id}'를 찾을 수 없습니다."}, status_code=404)

    try:
        save_translations(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(interp_path, f"feat: L6 번역 확정 — page {page_num}")
        except Exception:
            pass
        return result
    except Exception as e:
        return JSONResponse({"error": f"번역 저장 실패: {e}"}, status_code=400)


@app.delete("/api/interpretations/{interp_id}/pages/{page_num}/translation/{translation_id}")
async def api_delete_translation(interp_id: str, page_num: int, translation_id: str):
    """번역 삭제."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_translations(interp_path, part_id, page_num)
    removed = remove_translation(data, translation_id)

    if not removed:
        return JSONResponse({"error": f"번역 '{translation_id}'를 찾을 수 없습니다."}, status_code=404)

    save_translations(interp_path, part_id, page_num, data)
    return JSONResponse(status_code=204, content=None)


# ───────────────────────────────────────────────────
# Phase 11-3: L7 주석(Annotation) API
# ───────────────────────────────────────────────────

from core.annotation import (
    add_annotation as add_ann,
    check_translation_changed,
    get_annotation_summary,
    get_annotations_by_type,
    get_annotations_by_stage,
    load_annotations,
    remove_annotation as remove_ann,
    save_annotations,
    update_annotation as update_ann,
)
from core.annotation_llm import commit_annotation_draft, commit_all_drafts
from core.annotation_dict_llm import (
    generate_stage1_from_original,
    generate_stage2_from_translation,
    generate_stage3_from_both,
)
from core.annotation_dict_io import (
    export_dictionary,
    import_dictionary,
    save_export,
)
from core.annotation_dict_match import (
    format_for_translation_context,
    list_reference_dicts,
    load_reference_dict,
    match_page_blocks,
    register_reference_dict,
    remove_reference_dict,
)
from core.annotation_types import (
    add_custom_type,
    load_annotation_types,
    remove_custom_type,
)


class AnnotationAddRequest(BaseModel):
    """수동 주석 추가 요청."""
    target: dict
    type: str
    content: dict


class AnnotationUpdateRequest(BaseModel):
    """주석 수정 요청."""
    target: dict | None = None
    type: str | None = None
    content: dict | None = None
    status: str | None = None


class AnnotationCommitRequest(BaseModel):
    """주석 Draft 확정 요청."""
    modifications: dict | None = None


class CustomTypeRequest(BaseModel):
    """사용자 정의 주석 유형 추가 요청."""
    id: str
    label: str
    color: str
    icon: str = "🏷️"


@app.get("/api/interpretations/{interp_id}/pages/{page_num}/annotations")
async def api_get_annotations(interp_id: str, page_num: int, type: str | None = None):
    """주석 조회.

    목적: 특정 페이지의 L7 주석 데이터를 반환한다.
    쿼리 파라미터: type — 특정 유형만 필터링 (선택).
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 저장소 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    part_id = "main"
    data = load_annotations(interp_path, part_id, page_num)

    if type:
        filtered = get_annotations_by_type(data, type)
        return {"part_id": part_id, "page_number": page_num, "filtered_type": type, "results": filtered}

    return data


@app.get("/api/interpretations/{interp_id}/pages/{page_num}/annotations/summary")
async def api_annotation_summary(interp_id: str, page_num: int):
    """주석 상태 요약.

    목적: 페이지의 주석 현황을 한눈에 파악.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"
    data = load_annotations(interp_path, part_id, page_num)
    return get_annotation_summary(data)


@app.post("/api/interpretations/{interp_id}/pages/{page_num}/annotations/{block_id}")
async def api_add_annotation(
    interp_id: str, page_num: int, block_id: str, body: AnnotationAddRequest
):
    """수동 주석 추가.

    목적: 사용자가 직접 주석을 입력한다. annotator.type = "human", status = "accepted".
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_annotations(interp_path, part_id, page_num)

    annotation = {
        "target": body.target,
        "type": body.type,
        "content": body.content,
        "annotator": {"type": "human", "model": None, "draft_id": None},
        "status": "accepted",
        "reviewed_by": None,
        "reviewed_at": None,
    }
    result = add_ann(data, block_id, annotation)

    try:
        save_annotations(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(interp_path, f"feat: L7 주석 추가 — page {page_num}")
        except Exception:
            pass
        return JSONResponse(result, status_code=201)
    except Exception as e:
        return JSONResponse({"error": f"주석 저장 실패: {e}"}, status_code=400)


@app.put("/api/interpretations/{interp_id}/pages/{page_num}/annotations/{block_id}/{ann_id}")
async def api_update_annotation(
    interp_id: str, page_num: int, block_id: str, ann_id: str,
    body: AnnotationUpdateRequest,
):
    """주석 수정."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_annotations(interp_path, part_id, page_num)
    updates = {}
    if body.target is not None:
        updates["target"] = body.target
    if body.type is not None:
        updates["type"] = body.type
    if body.content is not None:
        updates["content"] = body.content
    if body.status is not None:
        updates["status"] = body.status

    result = update_ann(data, block_id, ann_id, updates)
    if result is None:
        return JSONResponse({"error": f"주석 '{ann_id}'를 찾을 수 없습니다."}, status_code=404)

    try:
        save_annotations(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(interp_path, f"feat: L7 주석 수정 — page {page_num}")
        except Exception:
            pass
        return result
    except Exception as e:
        return JSONResponse({"error": f"주석 저장 실패: {e}"}, status_code=400)


@app.delete("/api/interpretations/{interp_id}/pages/{page_num}/annotations/{block_id}/{ann_id}")
async def api_delete_annotation(
    interp_id: str, page_num: int, block_id: str, ann_id: str
):
    """주석 삭제."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_annotations(interp_path, part_id, page_num)
    removed = remove_ann(data, block_id, ann_id)

    if not removed:
        return JSONResponse({"error": f"주석 '{ann_id}'를 찾을 수 없습니다."}, status_code=404)

    save_annotations(interp_path, part_id, page_num, data)
    return JSONResponse(status_code=204, content=None)


@app.post("/api/interpretations/{interp_id}/pages/{page_num}/annotations/{block_id}/{ann_id}/commit")
async def api_commit_annotation(
    interp_id: str, page_num: int, block_id: str, ann_id: str,
    body: AnnotationCommitRequest,
):
    """주석 Draft 개별 확정.

    목적: 연구자가 Draft를 검토 후 확정. status → "accepted".
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_annotations(interp_path, part_id, page_num)
    result = commit_annotation_draft(data, block_id, ann_id, body.modifications)

    if result is None:
        return JSONResponse({"error": f"주석 '{ann_id}'를 찾을 수 없습니다."}, status_code=404)

    try:
        save_annotations(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(interp_path, f"feat: L7 주석 확정 — page {page_num}")
        except Exception:
            pass
        return result
    except Exception as e:
        return JSONResponse({"error": f"주석 저장 실패: {e}"}, status_code=400)


@app.post("/api/interpretations/{interp_id}/pages/{page_num}/annotations/commit-all")
async def api_commit_all_annotations(interp_id: str, page_num: int):
    """주석 Draft 일괄 확정.

    목적: 페이지의 모든 draft 주석을 한번에 accepted로 변경.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    part_id = "main"

    data = load_annotations(interp_path, part_id, page_num)
    count = commit_all_drafts(data)

    if count == 0:
        return {"message": "확정할 draft 주석이 없습니다.", "committed": 0}

    try:
        save_annotations(interp_path, part_id, page_num, data)
        try:
            git_commit_interpretation(interp_path, f"feat: L7 주석 일괄 확정 — page {page_num}")
        except Exception:
            pass
        return {"message": f"{count}개 주석을 확정했습니다.", "committed": count}
    except Exception as e:
        return JSONResponse({"error": f"주석 저장 실패: {e}"}, status_code=400)


# --- 주석 유형 관리 API ---

@app.get("/api/annotation-types")
async def api_get_annotation_types():
    """주석 유형 목록.

    목적: 기본 프리셋 + 사용자 정의 유형을 반환한다.
    """
    work_path = _library_path if _library_path else None
    data = load_annotation_types(work_path)
    return data


@app.post("/api/annotation-types")
async def api_add_annotation_type(body: CustomTypeRequest):
    """사용자 정의 주석 유형 추가."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    try:
        type_def = {"id": body.id, "label": body.label, "color": body.color, "icon": body.icon}
        result = add_custom_type(_library_path, type_def)
        return JSONResponse(result, status_code=201)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.delete("/api/annotation-types/{type_id}")
async def api_delete_annotation_type(type_id: str):
    """사용자 정의 주석 유형 삭제.

    주의: 기본 프리셋(person, place, term, allusion, note)은 삭제할 수 없다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    removed = remove_custom_type(_library_path, type_id)
    if not removed:
        return JSONResponse({"error": f"유형 '{type_id}'를 찾을 수 없거나 기본 프리셋입니다."}, status_code=404)

    return JSONResponse(status_code=204, content=None)


# ──────────────────────────────────────────────────────────
# 사전형 주석 API (L7 Dictionary Annotation)
# ──────────────────────────────────────────────────────────


class DictStageRequest(BaseModel):
    """사전형 주석 단계별 생성 요청."""
    block_id: str
    force_provider: str | None = None
    force_model: str | None = None


class DictBatchRequest(BaseModel):
    """사전형 주석 일괄 생성 요청 (Stage 3 직행)."""
    pages: list[int] | None = None  # None이면 전체 페이지
    force_provider: str | None = None
    force_model: str | None = None


class DictImportRequest(BaseModel):
    """사전 가져오기 요청."""
    dictionary_data: dict
    merge_strategy: str = "merge"
    target_page: int = 1


class RefDictRegisterRequest(BaseModel):
    """참조 사전 등록 요청."""
    dictionary_data: dict
    filename: str | None = None


class RefDictMatchRequest(BaseModel):
    """참조 사전 매칭 요청."""
    blocks: list[dict]
    ref_filenames: list[str] | None = None


# ── 단계별 사전 생성 ──


@app.post("/api/interpretations/{interp_id}/pages/{page_num}/annotations/generate-stage1")
async def api_dict_generate_stage1(interp_id: str, page_num: int, body: DictStageRequest):
    """1단계 사전 생성: 원문에서 사전 항목 추출.

    목적: L4 원문을 분석하여 표제어, 독음, 사전적 의미, 출전을 생성한다.
    전제 조건: L4 원문이 존재해야 한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    try:
        router = _get_llm_router()
        if body.force_provider:
            router.force_provider = body.force_provider
        if body.force_model:
            router.force_model = body.force_model

        result = await generate_stage1_from_original(
            interp_path=interp_path,
            part_id="main",
            page_num=page_num,
            block_id=body.block_id,
            router=router,
        )
        return result
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": f"1단계 사전 생성 실패: {e}"}, status_code=500)


@app.post("/api/interpretations/{interp_id}/pages/{page_num}/annotations/generate-stage2")
async def api_dict_generate_stage2(interp_id: str, page_num: int, body: DictStageRequest):
    """2단계 사전 생성: 번역으로 보강.

    목적: 1단계 결과에 L6 번역의 문맥적 의미를 보강한다.
    전제 조건: 1단계 완료 + L6 번역이 존재해야 한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    try:
        router = _get_llm_router()
        if body.force_provider:
            router.force_provider = body.force_provider
        if body.force_model:
            router.force_model = body.force_model

        result = await generate_stage2_from_translation(
            interp_path=interp_path,
            part_id="main",
            page_num=page_num,
            block_id=body.block_id,
            router=router,
        )
        return result
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": f"2단계 사전 생성 실패: {e}"}, status_code=500)


@app.post("/api/interpretations/{interp_id}/pages/{page_num}/annotations/generate-stage3")
async def api_dict_generate_stage3(interp_id: str, page_num: int, body: DictStageRequest):
    """3단계 사전 생성: 원문+번역 최종 통합.

    목적: 원문과 번역을 종합하여 사전 항목을 최종 정리한다.
    전제 조건: 원문 + 번역이 모두 존재. 1→2단계 완료 또는 일괄 생성 모드.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    try:
        router = _get_llm_router()
        if body.force_provider:
            router.force_provider = body.force_provider
        if body.force_model:
            router.force_model = body.force_model

        result = await generate_stage3_from_both(
            interp_path=interp_path,
            part_id="main",
            page_num=page_num,
            block_id=body.block_id,
            router=router,
        )
        return result
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": f"3단계 사전 생성 실패: {e}"}, status_code=500)


@app.post("/api/interpretations/{interp_id}/annotations/generate-batch")
async def api_dict_generate_batch(interp_id: str, body: DictBatchRequest):
    """일괄 사전 생성 (Stage 3 직행).

    목적: 완성된 원문+번역 쌍에서 모든 페이지의 사전을 한번에 생성한다.
    용도: 이미 완성된 작업에서 사전을 추출하여 다른 문헌 참조 사전으로 활용.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    try:
        router = _get_llm_router()
        if body.force_provider:
            router.force_provider = body.force_provider
        if body.force_model:
            router.force_model = body.force_model

        # 대상 페이지 결정
        if body.pages:
            pages = body.pages
        else:
            # L4 텍스트 파일이 있는 모든 페이지를 스캔
            text_dir = interp_path / "L4_text" / "main_text"
            if not text_dir.exists():
                return JSONResponse({"error": "L4 텍스트가 없습니다."}, status_code=404)
            pages = sorted(
                int(f.stem.split("_page_")[1].split("_")[0])
                for f in text_dir.glob("main_page_*_text.json")
            )

        # 각 페이지별 블록에 대해 Stage 3 실행
        total_results = {"pages_processed": 0, "total_annotations": 0, "errors": []}

        for page_num in pages:
            try:
                # 페이지의 모든 블록 찾기
                ann_data = load_annotations(interp_path, "main", page_num)
                block_ids = [b["block_id"] for b in ann_data.get("blocks", [])]

                # 블록이 없으면 L4 텍스트에서 블록 ID 추출
                if not block_ids:
                    text_file = text_dir / f"main_page_{page_num:03d}_text.json"
                    if text_file.exists():
                        import json as _json
                        with open(text_file, encoding="utf-8") as f:
                            text_data = _json.load(f)
                        block_ids = [b["block_id"] for b in text_data.get("blocks", [])]

                for block_id in block_ids:
                    result = await generate_stage3_from_both(
                        interp_path=interp_path,
                        part_id="main",
                        page_num=page_num,
                        block_id=block_id,
                        router=router,
                    )
                    total_results["total_annotations"] += len(result.get("annotations", []))

                total_results["pages_processed"] += 1
            except Exception as e:
                total_results["errors"].append({"page": page_num, "error": str(e)})

        return total_results
    except Exception as e:
        return JSONResponse({"error": f"일괄 사전 생성 실패: {e}"}, status_code=500)


# ── 사전 내보내기/가져오기 ──


@app.get("/api/interpretations/{interp_id}/export/dictionary")
async def api_export_dictionary(interp_id: str, page_start: int | None = None, page_end: int | None = None):
    """사전 내보내기.

    목적: 해석의 L7 사전형 주석을 독립 사전 JSON으로 추출한다.
    쿼리 파라미터: page_start, page_end — 페이지 범위 (선택).
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    # 문서 정보 가져오기
    meta_file = interp_path / "interpretation.json"
    doc_id = interp_id
    doc_title = interp_id
    if meta_file.exists():
        import json as _json
        with open(meta_file, encoding="utf-8") as f:
            meta = _json.load(f)
        doc_id = meta.get("document_id", interp_id)
        doc_title = meta.get("document_title", interp_id)

    page_range = None
    if page_start is not None and page_end is not None:
        page_range = (page_start, page_end)

    result = export_dictionary(
        interp_path=interp_path,
        doc_id=doc_id,
        doc_title=doc_title,
        interp_id=interp_id,
        page_range=page_range,
    )

    return result


@app.post("/api/interpretations/{interp_id}/export/dictionary/save")
async def api_save_export(interp_id: str):
    """사전 내보내기 파일 저장.

    목적: 내보내기 결과를 해석 저장소의 exports/ 디렉토리에 저장한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    # 먼저 전체 내보내기 생성
    meta_file = interp_path / "interpretation.json"
    doc_id = interp_id
    doc_title = interp_id
    if meta_file.exists():
        import json as _json
        with open(meta_file, encoding="utf-8") as f:
            meta = _json.load(f)
        doc_id = meta.get("document_id", interp_id)
        doc_title = meta.get("document_title", interp_id)

    dictionary_data = export_dictionary(interp_path, doc_id, doc_title, interp_id)
    saved_path = save_export(interp_path, dictionary_data)

    return {
        "saved_path": str(saved_path),
        "total_entries": dictionary_data["statistics"]["total_entries"],
    }


@app.post("/api/interpretations/{interp_id}/import/dictionary")
async def api_import_dictionary(interp_id: str, body: DictImportRequest):
    """사전 가져오기.

    목적: 다른 문헌에서 내보낸 사전을 현재 해석에 병합한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    result = import_dictionary(
        interp_path=interp_path,
        dictionary_data=body.dictionary_data,
        target_page=body.target_page,
        merge_strategy=body.merge_strategy,
    )

    return result


# ── 참조 사전 관리 ──


@app.get("/api/interpretations/{interp_id}/reference-dicts")
async def api_list_reference_dicts(interp_id: str):
    """참조 사전 목록 조회.

    목적: 등록된 참조 사전 파일 목록을 반환한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    dicts = list_reference_dicts(interp_path)
    return {"reference_dicts": dicts}


@app.post("/api/interpretations/{interp_id}/reference-dicts")
async def api_register_reference_dict(interp_id: str, body: RefDictRegisterRequest):
    """참조 사전 등록.

    목적: 내보내기된 사전 파일을 참조 사전으로 등록한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    saved_path = register_reference_dict(interp_path, body.dictionary_data, body.filename)
    return {"saved_path": str(saved_path), "filename": saved_path.name}


@app.delete("/api/interpretations/{interp_id}/reference-dicts/{filename}")
async def api_remove_reference_dict(interp_id: str, filename: str):
    """참조 사전 삭제."""
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    removed = remove_reference_dict(interp_path, filename)
    if not removed:
        return JSONResponse({"error": f"참조 사전 '{filename}'을 찾을 수 없습니다."}, status_code=404)

    return JSONResponse(status_code=204, content=None)


@app.post("/api/interpretations/{interp_id}/reference-dicts/match")
async def api_match_reference_dicts(interp_id: str, body: RefDictMatchRequest):
    """참조 사전 매칭.

    목적: 원문 블록에서 참조 사전의 표제어를 자동 매칭한다.
    입력: blocks — [{block_id, text}, ...], ref_filenames — 사용할 참조 사전 (선택).
    출력: 매칭 결과 리스트.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    matches = match_page_blocks(interp_path, body.blocks, body.ref_filenames)

    return {"matches": matches}


# ── 번역↔주석 연동 ──


@app.get("/api/interpretations/{interp_id}/pages/{page_num}/annotations/translation-changed")
async def api_check_translation_changed(interp_id: str, page_num: int):
    """번역 변경 감지.

    목적: 주석의 translation_snapshot과 현재 번역을 비교하여 변경 여부를 반환한다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse({"error": f"해석 '{interp_id}'를 찾을 수 없습니다."}, status_code=404)

    part_id = "main"
    ann_data = load_annotations(interp_path, part_id, page_num)

    from core.translation import load_translations
    tr_data = load_translations(interp_path, part_id, page_num)

    changed = check_translation_changed(ann_data, tr_data)
    return {"translation_changed": len(changed) > 0, "changed_annotations": changed}


# --- 비고/메모 API ---


class NotesSaveRequest(BaseModel):
    """비고 저장 요청 모델."""
    entries: list[dict]


@app.get("/api/interpretations/{interp_id}/pages/{page_num}/notes")
async def api_get_notes(
    interp_id: str,
    page_num: int,
    part_id: str = Query("main", description="권 식별자"),
):
    """페이지 비고(메모)를 조회한다.

    목적: 연구자가 작성한 자유 메모를 불러온다.
          아직 어디로 편입될지 미확정인 내용(임시 메모, 질문 등)을 보관한다.
    입력:
        interp_id — 해석 저장소 ID.
        page_num — 페이지 번호.
        part_id — 권 식별자 (기본 "main").
    출력: {part_id, page, entries, exists}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    return get_page_notes(interp_path, part_id, page_num)


@app.put("/api/interpretations/{interp_id}/pages/{page_num}/notes")
async def api_save_notes(
    interp_id: str,
    page_num: int,
    body: NotesSaveRequest,
    part_id: str = Query("main", description="권 식별자"),
):
    """페이지 비고(메모)를 저장한다.

    목적: 연구자가 작성한 자유 메모를 _notes/ 디렉토리에 저장하고 자동 커밋한다.
    입력:
        interp_id — 해석 저장소 ID.
        page_num — 페이지 번호.
        body — {entries: [{text, created_at, updated_at}, ...]}.
        part_id — 권 식별자 (기본 "main").
    출력: {status, file_path, count}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    try:
        result = save_page_notes(interp_path, part_id, page_num, body.entries)
        # 자동 git commit
        try:
            git_commit_interpretation(
                interp_path,
                f"docs: 비고 저장 — page {page_num}",
            )
        except Exception:
            pass
        return result
    except Exception as e:
        return JSONResponse({"error": f"비고 저장 실패: {e}"}, status_code=400)


# ──────────────────────────────────────
# 인용 마크 (Citation Mark) API
# ──────────────────────────────────────


class CitationMarkAddRequest(BaseModel):
    """인용 마크 추가 요청."""
    block_id: str
    start: int
    end: int
    marked_from: str  # "original" | "translation"
    source_text_snapshot: str
    label: str | None = None
    tags: list[str] = []


class CitationMarkUpdateRequest(BaseModel):
    """인용 마크 수정 요청."""
    label: str | None = None
    tags: list[str] | None = None
    citation_override: dict | None = None
    status: str | None = None
    marked_from: str | None = None


class CitationExportRequest(BaseModel):
    """인용 내보내기 요청."""
    mark_ids: list[str]
    include_translation: bool = True


@app.get("/api/interpretations/{interp_id}/pages/{page_num}/citation-marks")
async def api_get_citation_marks(
    interp_id: str,
    page_num: int,
    part_id: str = Query("main", description="권 식별자"),
):
    """페이지의 인용 마크 목록을 반환한다.

    목적: 인용 편집기에서 해당 페이지의 마크 목록을 표시.
    입력:
        interp_id — 해석 저장소 ID.
        page_num — 페이지 번호.
        part_id — 권 식별자.
    출력: {part_id, page_number, marks: [...]}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    return load_citation_marks(interp_path, part_id, page_num)


@app.post("/api/interpretations/{interp_id}/pages/{page_num}/citation-marks")
async def api_add_citation_mark(
    interp_id: str,
    page_num: int,
    body: CitationMarkAddRequest,
    part_id: str = Query("main", description="권 식별자"),
):
    """인용 마크를 추가한다.

    목적: 연구자가 원문 또는 번역에서 텍스트를 드래그하여 인용 마크를 생성.
    입력:
        body — {block_id, start, end, marked_from, source_text_snapshot, label?, tags?}.
    출력: 추가된 인용 마크.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    data = load_citation_marks(interp_path, part_id, page_num)
    mark = {
        "source": {
            "block_id": body.block_id,
            "start": body.start,
            "end": body.end,
        },
        "marked_from": body.marked_from,
        "source_text_snapshot": body.source_text_snapshot,
        "label": body.label,
        "tags": body.tags,
    }

    try:
        import asyncio
        added = add_citation_mark(data, mark)
        save_citation_marks(interp_path, part_id, page_num, data)
        # git commit을 별도 스레드에서 실행하여 이벤트 루프 블로킹 방지
        asyncio.get_event_loop().create_task(
            asyncio.to_thread(
                git_commit_interpretation, interp_path,
                f"feat: 인용 마크 추가 — page {page_num}, {body.block_id}",
            )
        )
        return added
    except Exception as e:
        return JSONResponse({"error": f"인용 마크 추가 실패: {e}"}, status_code=400)


@app.put("/api/interpretations/{interp_id}/pages/{page_num}/citation-marks/{mark_id}")
async def api_update_citation_mark(
    interp_id: str,
    page_num: int,
    mark_id: str,
    body: CitationMarkUpdateRequest,
    part_id: str = Query("main", description="권 식별자"),
):
    """인용 마크를 수정한다.

    목적: 라벨, 태그, citation_override, 상태 등을 수정.
    입력:
        mark_id — 인용 마크 ID.
        body — 수정할 필드.
    출력: 수정된 인용 마크.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    data = load_citation_marks(interp_path, part_id, page_num)

    # body에서 None이 아닌 필드만 업데이트
    updates = {}
    if body.label is not None:
        updates["label"] = body.label
    if body.tags is not None:
        updates["tags"] = body.tags
    if body.citation_override is not None:
        updates["citation_override"] = body.citation_override
    if body.status is not None:
        updates["status"] = body.status
    if body.marked_from is not None:
        updates["marked_from"] = body.marked_from

    updated = update_citation_mark(data, mark_id, updates)
    if updated is None:
        return JSONResponse(
            {"error": f"인용 마크를 찾을 수 없습니다: {mark_id}"},
            status_code=404,
        )

    try:
        import asyncio
        save_citation_marks(interp_path, part_id, page_num, data)
        asyncio.get_event_loop().create_task(
            asyncio.to_thread(
                git_commit_interpretation, interp_path,
                f"fix: 인용 마크 수정 — {mark_id}",
            )
        )
        return updated
    except Exception as e:
        return JSONResponse({"error": f"인용 마크 수정 실패: {e}"}, status_code=400)


@app.delete("/api/interpretations/{interp_id}/pages/{page_num}/citation-marks/{mark_id}")
async def api_delete_citation_mark(
    interp_id: str,
    page_num: int,
    mark_id: str,
    part_id: str = Query("main", description="권 식별자"),
):
    """인용 마크를 삭제한다.

    목적: 더 이상 인용하지 않을 마크를 삭제.
    입력: mark_id — 인용 마크 ID.
    출력: {status: "deleted"}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    data = load_citation_marks(interp_path, part_id, page_num)
    removed = remove_citation_mark(data, mark_id)

    if not removed:
        return JSONResponse(
            {"error": f"인용 마크를 찾을 수 없습니다: {mark_id}"},
            status_code=404,
        )

    try:
        import asyncio
        save_citation_marks(interp_path, part_id, page_num, data)
        asyncio.get_event_loop().create_task(
            asyncio.to_thread(
                git_commit_interpretation, interp_path,
                f"fix: 인용 마크 삭제 — {mark_id}",
            )
        )
        return {"status": "deleted", "mark_id": mark_id}
    except Exception as e:
        return JSONResponse({"error": f"인용 마크 삭제 실패: {e}"}, status_code=400)


@app.get("/api/interpretations/{interp_id}/citation-marks/all")
async def api_list_all_citation_marks(
    interp_id: str,
    part_id: str = Query("main", description="권 식별자"),
):
    """전체 페이지의 인용 마크를 통합 수집하여 반환한다.

    목적: 인용 패널의 "전체 보기" 모드.
    입력: interp_id, part_id.
    출력: [{page_number, id, source, ...}, ...].
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    return list_all_citation_marks(interp_path, part_id)


@app.post("/api/interpretations/{interp_id}/pages/{page_num}/citation-marks/{mark_id}/resolve")
async def api_resolve_citation_mark(
    interp_id: str,
    page_num: int,
    mark_id: str,
    part_id: str = Query("main", description="권 식별자"),
):
    """인용 마크 1개의 통합 컨텍스트(L4+L5+L6+L7+서지정보)를 조회한다.

    목적: 연구자가 인용 마크를 클릭했을 때 원문+표점본+번역+주석을 통합 표시.
    입력: interp_id, page_num, mark_id.
    출력: {mark, original_text, punctuated_text, translations, annotations, bibliography, text_changed}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    # 인용 마크 찾기
    data = load_citation_marks(interp_path, part_id, page_num)
    mark = None
    for m in data.get("marks", []):
        if m["id"] == mark_id:
            mark = m
            break

    if mark is None:
        return JSONResponse(
            {"error": f"인용 마크를 찾을 수 없습니다: {mark_id}"},
            status_code=404,
        )

    import json

    # 문서 ID 조회 (해석 매니페스트에서)
    manifest_path = interp_path / "manifest.json"
    if not manifest_path.exists():
        return JSONResponse(
            {"error": "해석 매니페스트를 찾을 수 없습니다."},
            status_code=404,
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    doc_id = manifest.get("source_document_id", "")

    try:
        context = resolve_citation_context(
            library_path=_library_path,
            doc_id=doc_id,
            interp_path=interp_path,
            part_id=part_id,
            page_num=page_num,
            mark=mark,
        )
        return context
    except Exception as e:
        return JSONResponse({"error": f"인용 컨텍스트 조회 실패: {e}"}, status_code=500)


@app.post("/api/interpretations/{interp_id}/citation-marks/export")
async def api_export_citations(
    interp_id: str,
    body: CitationExportRequest,
    part_id: str = Query("main", description="권 식별자"),
):
    """선택한 인용 마크들을 학술 인용 형식으로 변환한다.

    목적: 연구자가 선택한 마크들을 논문에 붙여넣을 수 있는 형식으로 내보내기.
    입력:
        body — {mark_ids: [...], include_translation: bool}.
    출력: {citations: "formatted text", count: N}.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    if not interp_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    import json

    # 문서 ID 조회
    manifest_path = interp_path / "manifest.json"
    if not manifest_path.exists():
        return JSONResponse(
            {"error": "해석 매니페스트를 찾을 수 없습니다."},
            status_code=404,
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    doc_id = manifest.get("source_document_id", "")

    # 전체 마크에서 선택된 것 찾기
    all_marks = list_all_citation_marks(interp_path, part_id)
    mark_map = {m["id"]: m for m in all_marks}

    contexts = []
    for mid in body.mark_ids:
        if mid not in mark_map:
            continue
        mark = mark_map[mid]
        page_num = mark.get("page_number", 1)
        try:
            ctx = resolve_citation_context(
                library_path=_library_path,
                doc_id=doc_id,
                interp_path=interp_path,
                part_id=part_id,
                page_num=page_num,
                mark=mark,
            )
            contexts.append(ctx)
        except Exception:
            continue

    citations_text = export_citations(contexts, include_translation=body.include_translation)
    return {
        "citations": citations_text,
        "count": len(contexts),
    }


# ──────────────────────────────────────
# Phase 12-1: Git 그래프 API
# ──────────────────────────────────────


@app.get("/api/interpretations/{interp_id}/git-graph")
async def api_git_graph(
    interp_id: str,
    original_branch: str = Query("auto", description="원본 저장소 브랜치"),
    interp_branch: str = Query("auto", description="해석 저장소 브랜치"),
    limit: int = Query(50, ge=1, le=200, description="각 저장소별 최대 커밋 수"),
    offset: int = Query(0, ge=0, description="페이지네이션 오프셋"),
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
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    manifest_path = interp_path / "manifest.json"

    if not manifest_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    import json
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
    )

    return data


# ──────────────────────────────────────
# Phase 12-3: JSON 스냅샷 API
# ──────────────────────────────────────


@app.get("/api/interpretations/{interp_id}/export/json")
async def api_export_json(interp_id: str):
    """해석 저장소 + 원본 전체를 JSON 스냅샷으로 내보낸다.

    목적: 백업, 공유, 다른 환경 이동용 단일 JSON 파일 생성.
    입력: interp_id — 해석 저장소 ID (manifest에서 원본 문헌 자동 결정).
    출력: JSON 파일 다운로드 (Content-Disposition: attachment).

    왜 이렇게 하는가:
        Git 히스토리 없이 현재 HEAD 상태만 직렬화하면
        파일 크기가 작고 복원 시 충돌이 없다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    interp_path = _library_path / "interpretations" / interp_id
    manifest_path = interp_path / "manifest.json"

    if not manifest_path.exists():
        return JSONResponse(
            {"error": f"해석 저장소를 찾을 수 없습니다: {interp_id}"},
            status_code=404,
        )

    import json as _json
    manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
    doc_id = manifest.get("source_document_id", "")

    if not doc_id:
        return JSONResponse(
            {"error": "manifest에 source_document_id가 없습니다."},
            status_code=400,
        )

    snapshot = build_snapshot(_library_path, doc_id, interp_id)

    # JSON 파일 다운로드
    import io
    from datetime import datetime

    title = snapshot.get("work", {}).get("title", interp_id)
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"{title}_{date_str}.json"

    content = _json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/import/json")
async def api_import_json(request: Request):
    """JSON 스냅샷에서 새 Work(문헌 + 해석 저장소)를 생성한다.

    목적: 다른 환경에서 export한 스냅샷을 현재 서고에 import.
    입력: Request body에 JSON 직접 전송 (Content-Type: application/json).
    출력: {status, doc_id, interp_id, title, layers_imported, warnings}.

    왜 이렇게 하는가:
        항상 "새 Work 생성"으로 처리하여 기존 데이터에 영향을 주지 않는다.
        같은 스냅샷을 여러 번 import해도 각각 독립된 Work가 된다.
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    import json as _json

    try:
        body = await request.body()
        data = _json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, _json.JSONDecodeError) as e:
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


@app.post("/api/import/interpretation-folder")
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
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    if not files:
        return JSONResponse(
            {"error": "업로드된 파일이 없습니다. 해석 저장소 폴더를 선택하세요."},
            status_code=400,
        )

    import json as _json
    import re as _re
    import subprocess as _subprocess
    from datetime import timezone as _timezone
    from pathlib import PurePosixPath as _PurePosixPath

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
        manifest = _json.loads(manifest_raw)
    except UnicodeDecodeError:
        return JSONResponse(
            {"error": "manifest.json 인코딩이 UTF-8이 아닙니다."},
            status_code=400,
        )
    except _json.JSONDecodeError as e:
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
    if not _re.match(r"^[a-z][a-z0-9_]{0,63}$", interp_id):
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

            posix_path = _PurePosixPath(rel_name)
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
            _json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
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
                "last_checked": datetime.now(_timezone.utc).isoformat(),
                "dependency_status": "current",
            }
            dependency_path.write_text(
                _json.dumps(fallback_dependency, ensure_ascii=False, indent=2) + "\n",
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
            init_proc = _subprocess.run(
                ["git", "init"],
                cwd=str(target_interp_path),
                capture_output=True,
                text=True,
            )
            if init_proc.returncode == 0:
                _subprocess.run(["git", "add", "."], cwd=str(target_interp_path), capture_output=True)
                _subprocess.run(
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


def _register_interp_in_library(
    library_path: Path, interp_id: str, source_document_id: str, title: str | None,
):
    """library_manifest.json에 해석 저장소 항목을 등록한다 (이미 있으면 무시)."""
    import json as _json
    manifest_path = library_path / "library_manifest.json"
    try:
        if manifest_path.exists():
            lib_manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
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
                _json.dumps(lib_manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    except Exception:
        pass


# ===========================================================================
#  LLM 연동: 표점 / 번역 / 주석 AI
# ===========================================================================
#
# 왜 여기에 모아두는가:
#   레이아웃 분석, OCR, 표점, 번역, 주석 모두 동일한 LLM 라우터를 사용한다.
#   _get_llm_router()가 프로바이더 폴백(base44_bridge → ollama → openai → anthropic)을 관리하므로,
#   각 기능은 프롬프트만 다르고 호출 방식은 동일하다.
#
# 커스텀 방법:
#   1. 프롬프트 수정: 아래 _LLM_PROMPT_* 딕셔너리를 수정
#   2. 프로바이더 변경: force_provider 파라미터로 특정 프로바이더 지정
#   3. 모델 변경: force_model 파라미터로 특정 모델 지정
#   4. 새 기능 추가: _get_llm_router().call() 또는 .call_with_image() 호출
# ===========================================================================

# ─── LLM 프롬프트 템플릿 (수정 용이하도록 분리) ──────────────

_LLM_PROMPTS = {
    "punctuation": {
        "system": (
            "당신은 고전 한문 표점(句讀) 전문가입니다.\n"
            "주어진 원문에 현대 학술 표점부호를 삽입하세요.\n\n"
            "사용 가능한 부호: 。，、；：？！《》〈〉「」『』\n\n"
            "규칙:\n"
            "- 문장이 끝나면(句) 。\n"
            "- 절이 이어지면(讀) ，\n"
            "- 단순 나열·병렬(竝列)은 、\n"
            "- 대구·열거가 길면 ；\n"
            "- 서명은 《》, 편명은 〈〉\n"
            "- 인용은 「」\n"
            "- 의문문은 ？, 감탄문은 ！\n\n"
            "중요:\n"
            "- start/end는 0-based 글자 인덱스 (inclusive)\n"
            "- 단일 글자 뒤에 부호를 넣으면 start == end\n"
            "- 부호를 글자 뒤에 넣으려면 after에, 앞에 넣으려면 before에 넣으세요\n"
            "- 원문 글자를 절대 변경하지 마세요\n"
            "- JSON만 반환하세요. 설명 텍스트를 넣지 마세요.\n\n"
            "출력 형식:\n"
            '{"marks": [{"start": 1, "end": 1, "before": null, "after": "，"}, '
            '{"start": 3, "end": 3, "before": null, "after": "。"}]}'
        ),
        "user": "다음 고전 한문에 표점을 삽입하세요:\n\n{text}",
    },
    "translation": {
        "system": (
            "당신은 고전 한문 번역 전문가입니다.\n"
            "주어진 문장을 한국어로 번역하세요.\n"
            "규칙:\n"
            "1. 원문의 뜻을 정확하게 전달하되, 자연스러운 한국어로 번역합니다.\n"
            "2. 고유명사(인명, 지명)는 한자를 병기합니다. 예: 왕융(王戎)\n"
            "3. 반드시 순수 JSON만 출력하세요.\n"
            "출력 형식:\n"
            '{"translation": "번역문", "notes": "번역 참고사항(선택)"}'
        ),
        "user": "다음 고전 한문을 한국어로 번역하세요:\n\n{text}",
    },
    "annotation": {
        "system": (
            "당신은 고전 한문 주석 전문가입니다.\n"
            "주어진 텍스트에서 주석이 필요한 항목을 태깅하세요.\n"
            "규칙:\n"
            "1. 인명(person), 지명(place), 관직(official_title), 서명(book_title), "
            "전고(allusion), 용어(term)를 식별합니다.\n"
            "2. 각 항목에 간단한 설명을 덧붙이세요.\n"
            "3. 원문의 시작 인덱스(start)와 끝 인덱스(end)를 포함하세요.\n"
            "4. 반드시 순수 JSON만 출력하세요.\n"
            "출력 형식:\n"
            '{"annotations": [{"text": "王戎", "type": "person", '
            '"start": 0, "end": 2, '
            '"label": "왕융(王戎)", "description": "竹林七賢의 한 사람"}]}'
        ),
        "user": "다음 고전 한문에서 주석 대상을 태깅하세요:\n\n{text}",
    },
}


class AiPunctuationRequest(BaseModel):
    """AI 표점 요청."""
    text: str                         # 표점할 원문 텍스트
    force_provider: str | None = None
    force_model: str | None = None


class AiTranslationRequest(BaseModel):
    """AI 번역 요청."""
    text: str                         # 번역할 원문 텍스트
    force_provider: str | None = None
    force_model: str | None = None


class AiAnnotationRequest(BaseModel):
    """AI 주석 태깅 요청."""
    text: str                         # 태깅할 원문 텍스트
    force_provider: str | None = None
    force_model: str | None = None


async def _call_llm_text(purpose: str, text: str,
                          force_provider=None, force_model=None) -> dict:
    """공통 LLM 텍스트 호출. 프롬프트 템플릿 + JSON 파싱.

    왜 이렇게 하는가:
        표점, 번역, 주석 모두 동일한 패턴이다:
        1. 시스템 프롬프트 + 사용자 프롬프트 구성
        2. LLM 라우터로 호출
        3. JSON 응답 파싱
        4. 결과 반환

    커스텀:
        _LLM_PROMPTS 딕셔너리를 수정하면 프롬프트를 바꿀 수 있다.

    폴백 전략:
        자동 모드(force_provider 없음)에서 프로바이더가 JSON이 아닌
        거절 응답을 반환하면 다음 프로바이더로 자동 재시도한다.
        Base44 agent-chat은 MCP 도구 기반이라 자유 형식 텍스트 요청을
        "도구가 없습니다"로 거절할 수 있다.
    """
    import json as _json
    import logging as _logging

    _logger = _logging.getLogger(__name__)

    prompts = _LLM_PROMPTS.get(purpose)
    if not prompts:
        raise ValueError(f"알 수 없는 LLM purpose: {purpose}")

    router = _get_llm_router()
    system_prompt = prompts["system"]
    user_prompt = prompts["user"].format(text=text)

    # ── force_provider가 지정된 경우: 해당 프로바이더만 시도 ──
    if force_provider:
        response = await router.call(
            user_prompt,
            system=system_prompt,
            force_provider=force_provider,
            force_model=force_model,
            purpose=purpose,
        )
        return _parse_llm_json(response, _json)

    # ── 자동 모드: 프로바이더 순서대로 시도, JSON 파싱 실패 시 다음으로 ──
    errors = []
    for provider in router.providers:
        try:
            if not await provider.is_available():
                continue

            response = await provider.call(
                user_prompt,
                system=system_prompt,
                response_format="text",
                max_tokens=4096,
                purpose=purpose,
            )
            router.usage_tracker.log(response, purpose=purpose)

            # JSON 파싱 시도 — 실패하면 다음 프로바이더로
            return _parse_llm_json(response, _json)

        except Exception as e:
            _logger.info(
                f"LLM {purpose} — {provider.provider_id} 실패: {e}, "
                f"다음 프로바이더로 시도"
            )
            errors.append(f"{provider.provider_id}: {e}")
            continue

    raise ValueError(
        f"모든 LLM 프로바이더가 {purpose} 요청에 실패했습니다:\n"
        + "\n".join(f"  - {e}" for e in errors)
    )


def _parse_llm_json(response, _json) -> dict:
    """LLM 응답에서 JSON을 추출한다.

    왜 별도 함수인가:
        _call_llm_text의 자동 폴백에서 반복 사용.
        파싱 실패 시 ValueError를 발생시켜 다음 프로바이더로 넘긴다.
    """
    raw = response.text.strip()

    # markdown 코드 블록 제거
    if "```" in raw:
        parts = raw.split("```")
        if len(parts) >= 3:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError:
        # JSON 부분만 추출 시도
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = _json.loads(raw[start:end])
            except _json.JSONDecodeError:
                raise ValueError(
                    f"LLM 응답 JSON 파싱 실패 ({response.provider}): {raw[:200]}"
                )
        else:
            raise ValueError(
                f"LLM 응답에 JSON이 없음 ({response.provider}): {raw[:200]}"
            )

    data["_provider"] = response.provider
    data["_model"] = response.model
    return data


def _normalize_punct_marks(raw_marks: list) -> list:
    """LLM이 반환한 marks를 {start, end, before, after} 형식으로 정규화.

    왜 이렇게 하는가:
        LLM은 프롬프트와 다른 형식으로 응답할 수 있다.
        구형식 {after_char_index, mark}이든 신형식 {start, end, before, after}이든
        클라이언트가 일관되게 처리할 수 있도록 표준화한다.
    """
    normalized = []
    for m in raw_marks:
        if "after_char_index" in m:
            # 구형식: {after_char_index: int, mark: str}
            # → after_char_index번째 글자 뒤에 mark를 삽입
            idx = m["after_char_index"]
            normalized.append({
                "start": idx, "end": idx,
                "before": None, "after": m.get("mark"),
            })
        else:
            # 신형식: 이미 {start, end, before, after}
            normalized.append({
                "start": m.get("start", 0),
                "end": m.get("end", m.get("start", 0)),
                "before": m.get("before"),
                "after": m.get("after"),
            })
    return normalized


@app.post("/api/llm/punctuation")
async def api_llm_punctuation(body: AiPunctuationRequest):
    """AI 표점 생성.

    입력: 원문 텍스트
    출력: 표점이 삽입된 텍스트 + marks 배열
    """
    try:
        result = await _call_llm_text(
            "punctuation", body.text,
            force_provider=body.force_provider,
            force_model=body.force_model,
        )
        # LLM 응답의 marks를 표준 형식으로 정규화
        if "marks" in result and isinstance(result["marks"], list):
            result["marks"] = _normalize_punct_marks(result["marks"])
        return result
    except Exception as e:
        return JSONResponse({"error": f"AI 표점 실패: {e}"}, status_code=500)


@app.post("/api/llm/translation")
async def api_llm_translation(body: AiTranslationRequest):
    """AI 번역.

    입력: 원문 텍스트
    출력: 한국어 번역 + 참고사항
    """
    try:
        result = await _call_llm_text(
            "translation", body.text,
            force_provider=body.force_provider,
            force_model=body.force_model,
        )
        return result
    except Exception as e:
        return JSONResponse({"error": f"AI 번역 실패: {e}"}, status_code=500)


@app.post("/api/llm/annotation")
async def api_llm_annotation(body: AiAnnotationRequest):
    """AI 주석 태깅.

    입력: 원문 텍스트
    출력: 태깅된 주석 배열 (인명, 지명, 관직, 전고 등)
    """
    try:
        result = await _call_llm_text(
            "annotation", body.text,
            force_provider=body.force_provider,
            force_model=body.force_model,
        )
        return result
    except Exception as e:
        return JSONResponse({"error": f"AI 주석 실패: {e}"}, status_code=500)


# ──────────────────────────────────────
# 휴지통 API (문헌/해석 저장소 삭제·복원)
# ──────────────────────────────────────


@app.get("/api/trash")
async def api_trash():
    """휴지통 목록을 반환한다.

    목적: .trash/ 폴더 안의 삭제된 문헌·해석 저장소 목록을 조회한다.
    출력: {"documents": [...], "interpretations": [...]}
    """
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)
    return list_trash(_library_path)


@app.post("/api/trash/{trash_type}/{trash_name}/restore")
async def api_restore_from_trash(trash_type: str, trash_name: str):
    """휴지통에서 문헌 또는 해석 저장소를 복원한다.

    목적: .trash/에 있는 항목을 원래 위치로 되돌린다.
    입력:
        trash_type — "documents" 또는 "interpretations".
        trash_name — 휴지통 내 폴더명 (예: "20260220T153000_kameda_monggu").
    출력: {"status": "restored", "original_id": "..."}.
    """
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
