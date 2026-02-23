"""서고(Library) 관리 모듈.

서고는 여러 문헌(원본 저장소)과 해석 저장소를 관리하는 최상위 디렉토리다.
platform-v7.md 섹션 10.3의 구조를 따른다:

    library/
    ├── library_manifest.json     # 서고 메타데이터
    ├── collections/              # 컬렉션
    ├── documents/                # 원본 저장소들
    ├── interpretations/          # 해석 저장소들
    ├── resources/                # 공유 리소스
    └── .library_config.json      # 서고 설정
"""

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def init_library(path: str | Path) -> Path:
    """서고 디렉토리 구조를 생성한다.

    목적: 빈 서고를 만들어 문헌을 등록할 준비를 한다.
    입력: path — 서고를 생성할 경로 (문자열 또는 Path).
    출력: 생성된 서고의 Path.

    Raises:
        FileExistsError: 해당 경로에 이미 서고(library_manifest.json)가 있을 때.
            → 해결: 다른 경로를 지정하거나 기존 서고를 사용하세요.
    """
    library_path = Path(path).resolve()

    if (library_path / "library_manifest.json").exists():
        raise FileExistsError(
            f"서고가 이미 존재합니다: {library_path}\n"
            "→ 해결: 다른 경로를 지정하거나 기존 서고를 사용하세요."
        )

    # v7 §10.3 서고 디렉토리 구조
    dirs = [
        "documents",
        "interpretations",
        "collections",
        "resources",
        "resources/ocr_profiles",
        "resources/prompts",
    ]
    for d in dirs:
        (library_path / d).mkdir(parents=True, exist_ok=True)

    # library_manifest.json — 서고의 전체 지도 역할
    manifest = {
        "name": library_path.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "documents": [],
        "interpretations": [],
    }

    _write_json(library_path / "library_manifest.json", manifest)

    return library_path


def get_library_info(path: str | Path) -> dict:
    """library_manifest.json을 읽어 반환한다.

    목적: 서고의 메타데이터와 등록된 문헌 목록을 조회한다.
    입력: path — 서고 경로.
    출력: library_manifest.json의 내용 (dict).

    Raises:
        FileNotFoundError: 서고를 찾을 수 없을 때.
    """
    library_path = Path(path).resolve()
    manifest_path = library_path / "library_manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"서고를 찾을 수 없습니다: {library_path}\n"
            "→ 해결: 'init-library' 명령으로 서고를 먼저 생성하세요."
        )

    return json.loads(manifest_path.read_text(encoding="utf-8"))


def list_documents(path: str | Path) -> list[dict]:
    """서고의 문헌 목록을 반환한다.

    목적: documents/ 안의 모든 문헌 manifest.json을 읽어 목록으로 반환한다.
    입력: path — 서고 경로.
    출력: 문헌 정보 dict의 리스트. 각 항목은 manifest.json 내용.
    """
    library_path = Path(path).resolve()
    docs_dir = library_path / "documents"

    if not docs_dir.exists():
        return []

    documents = []
    for doc_dir in sorted(docs_dir.iterdir()):
        if not doc_dir.is_dir():
            continue
        manifest_path = doc_dir / "manifest.json"
        if manifest_path.exists():
            doc_info = json.loads(manifest_path.read_text(encoding="utf-8"))
            documents.append(doc_info)

    return documents


def list_interpretations(path: str | Path) -> list[dict]:
    """서고의 해석 저장소 목록을 반환한다.

    목적: interpretations/ 안의 모든 해석 저장소 manifest.json을 읽어 목록으로 반환한다.
    입력: path — 서고 경로.
    출력: 해석 저장소 정보 dict의 리스트. 각 항목은 manifest.json 내용.
    """
    library_path = Path(path).resolve()
    interp_dir = library_path / "interpretations"

    if not interp_dir.exists():
        return []

    interpretations = []
    for d in sorted(interp_dir.iterdir()):
        if not d.is_dir():
            continue
        manifest_path = d / "manifest.json"
        if manifest_path.exists():
            info = json.loads(manifest_path.read_text(encoding="utf-8"))
            interpretations.append(info)

    return interpretations


def trash_document(library_path: str | Path, doc_id: str) -> dict:
    """문헌을 휴지통(.trash/documents/)으로 이동한다.

    목적: 문헌 폴더를 영구 삭제하지 않고 서고 내 휴지통으로 옮긴다.
          나중에 restore_from_trash()로 복원할 수 있다.
    입력: library_path — 서고 경로, doc_id — 삭제할 문헌 ID.
    출력: {"trash_name": str, "related_interpretations": list} — 이동된 휴지통 이름과
          이 문헌을 참조하는 해석 저장소 목록.

    Raises:
        FileNotFoundError: 문헌이 존재하지 않을 때.
    """
    library_path = Path(library_path).resolve()
    doc_dir = library_path / "documents" / doc_id

    if not doc_dir.exists():
        raise FileNotFoundError(
            f"문헌을 찾을 수 없습니다: {doc_id}\n"
            "→ 해결: 문헌 ID를 확인하세요."
        )

    # 이 문헌을 참조하는 해석 저장소 목록 수집 (프론트에서 경고 표시용)
    related = _find_related_interpretations(library_path, doc_id)

    # 휴지통 폴더 생성 + 이동
    trash_name = _move_to_trash(library_path, "documents", doc_id)

    return {"trash_name": trash_name, "related_interpretations": related}


def trash_interpretation(library_path: str | Path, interp_id: str) -> dict:
    """해석 저장소를 휴지통(.trash/interpretations/)으로 이동한다.

    목적: 해석 저장소 폴더를 영구 삭제하지 않고 서고 내 휴지통으로 옮긴다.
    입력: library_path — 서고 경로, interp_id — 삭제할 해석 저장소 ID.
    출력: {"trash_name": str} — 이동된 휴지통 이름.

    Raises:
        FileNotFoundError: 해석 저장소가 존재하지 않을 때.
    """
    library_path = Path(library_path).resolve()
    interp_dir = library_path / "interpretations" / interp_id

    if not interp_dir.exists():
        raise FileNotFoundError(
            f"해석 저장소를 찾을 수 없습니다: {interp_id}\n"
            "→ 해결: 해석 저장소 ID를 확인하세요."
        )

    trash_name = _move_to_trash(library_path, "interpretations", interp_id)

    return {"trash_name": trash_name}


def list_trash(library_path: str | Path) -> dict:
    """휴지통 내용을 반환한다.

    목적: .trash/ 폴더 안의 문헌과 해석 저장소 목록을 조회한다.
    입력: library_path — 서고 경로.
    출력: {"documents": [...], "interpretations": [...]} — 각 항목은
          {"trash_name", "original_id", "trashed_at", "title"} 형태.
    """
    library_path = Path(library_path).resolve()
    trash_dir = library_path / ".trash"

    result = {"documents": [], "interpretations": []}

    for category in ("documents", "interpretations"):
        cat_dir = trash_dir / category
        if not cat_dir.exists():
            continue
        for d in sorted(cat_dir.iterdir()):
            if not d.is_dir():
                continue
            info = _parse_trash_entry(d)
            if info:
                result[category].append(info)

    return result


def restore_from_trash(
    library_path: str | Path, trash_type: str, trash_name: str
) -> str:
    """휴지통에서 문헌 또는 해석 저장소를 복원한다.

    목적: .trash/에 있는 항목을 원래 위치(documents/ 또는 interpretations/)로 되돌린다.
    입력: library_path — 서고 경로,
          trash_type — "documents" 또는 "interpretations",
          trash_name — 휴지통 내 폴더명 (예: "20260220T153000_monggu").
    출력: 복원된 원래 ID (str).

    Raises:
        FileNotFoundError: 휴지통에 해당 항목이 없을 때.
        FileExistsError: 복원 대상 위치에 이미 같은 ID의 항목이 있을 때.
    """
    library_path = Path(library_path).resolve()
    trash_path = library_path / ".trash" / trash_type / trash_name

    if not trash_path.exists():
        raise FileNotFoundError(
            f"휴지통에서 찾을 수 없습니다: {trash_type}/{trash_name}\n"
            "→ 해결: 휴지통 목록을 확인하세요."
        )

    # 타임스탬프 접두사 제거 → 원래 ID 추출
    # 형식: "20260220T153000_원래id" → 첫 번째 '_' 이후 전부가 원래 ID
    parts = trash_name.split("_", 1)
    if len(parts) < 2:
        raise ValueError(
            f"휴지통 폴더명 형식이 올바르지 않습니다: {trash_name}\n"
            "→ 예상 형식: 20260220T153000_original_id"
        )
    original_id = parts[1]

    restore_target = library_path / trash_type / original_id
    if restore_target.exists():
        raise FileExistsError(
            f"복원 위치에 이미 같은 ID가 있습니다: {trash_type}/{original_id}\n"
            "→ 해결: 기존 항목을 먼저 삭제하거나 이름을 변경하세요."
        )

    shutil.move(str(trash_path), str(restore_target))
    return original_id


# ──────────────────────────
#   내부 유틸리티
# ──────────────────────────


def _close_git_handles(repo_path: Path) -> None:
    """GitPython이 열어둔 .git 파일 핸들을 해제한다.

    왜 필요한가:
        GitPython의 Repo 객체가 .git/objects/pack 등을 열어두면
        Windows에서 shutil.move가 PermissionError를 던진다.
        gc.collect()로 참조가 끊긴 Repo 객체를 정리하고,
        혹시 남아있는 git.cmd 프로세스도 clear_cache()로 닫는다.
    """
    import gc
    gc.collect()
    try:
        import git
        git.cmd.Git.clear_cache()
    except Exception:
        pass


def _move_to_trash(library_path: Path, category: str, item_id: str) -> str:
    """항목을 .trash/{category}/ 로 이동한다. (내부 유틸리티)

    왜 서고 내부 .trash/ 폴더를 사용하는가:
        OS 휴지통(Recycle Bin)은 플랫폼마다 다르고 프로그래밍 접근이 복잡하다.
        서고 내부 .trash/ 폴더를 사용하면 OS 독립적이고 복원도 간단하다.

    반환: 휴지통 내 폴더명 (타임스탬프_원래ID).
    """
    import stat

    source = library_path / category / item_id
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    trash_name = f"{timestamp}_{item_id}"

    trash_dir = library_path / ".trash" / category
    trash_dir.mkdir(parents=True, exist_ok=True)

    dest = trash_dir / trash_name

    # Git 핸들 해제 (Windows에서 .git/objects 파일 잠김 방지)
    _close_git_handles(source)

    # 1차 시도: shutil.move (같은 파일시스템이면 빠른 rename)
    try:
        shutil.move(str(source), str(dest))
        return trash_name
    except PermissionError:
        # 부분 이동이 발생했을 수 있으므로 dest 정리
        if dest.exists():
            shutil.rmtree(str(dest), ignore_errors=True)

    # 2차 시도: 읽기 전용 해제 후 재시도
    for root, dirs, files in os.walk(str(source)):
        for f in files:
            fp = os.path.join(root, f)
            try:
                os.chmod(fp, stat.S_IWRITE | stat.S_IREAD)
            except Exception:
                pass

    shutil.move(str(source), str(dest))
    return trash_name


def _find_related_interpretations(library_path: Path, doc_id: str) -> list[str]:
    """특정 문헌을 참조하는 해석 저장소 ID 목록을 반환한다. (내부 유틸리티)

    왜 이 함수가 필요한가:
        문헌 삭제 시 이 문헌을 source_document_id로 참조하는 해석 저장소가 있으면
        프론트엔드에서 사용자에게 경고를 표시해야 한다.
    """
    interp_dir = library_path / "interpretations"
    if not interp_dir.exists():
        return []

    related = []
    for d in interp_dir.iterdir():
        if not d.is_dir():
            continue
        manifest_path = d / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            info = json.loads(manifest_path.read_text(encoding="utf-8"))
            if info.get("source_document_id") == doc_id:
                related.append(info.get("interpretation_id", d.name))
        except (json.JSONDecodeError, OSError):
            continue

    return related


def _parse_trash_entry(trash_folder: Path) -> dict | None:
    """휴지통 폴더 하나를 파싱하여 정보를 반환한다. (내부 유틸리티)

    폴더명 형식: "20260220T153000_원래id"
    manifest.json이 있으면 title도 읽어온다.
    """
    name = trash_folder.name
    parts = name.split("_", 1)
    if len(parts) < 2:
        return None

    timestamp_str, original_id = parts

    # manifest.json에서 제목 읽기 (있으면)
    title = original_id
    manifest_path = trash_folder / "manifest.json"
    if manifest_path.exists():
        try:
            info = json.loads(manifest_path.read_text(encoding="utf-8"))
            title = info.get("title", original_id)
        except (json.JSONDecodeError, OSError):
            pass

    # 타임스탬프 파싱
    try:
        trashed_at = datetime.strptime(timestamp_str, "%Y%m%dT%H%M%S").replace(
            tzinfo=timezone.utc
        ).isoformat()
    except ValueError:
        trashed_at = None

    return {
        "trash_name": name,
        "original_id": original_id,
        "title": title,
        "trashed_at": trashed_at,
    }


def _write_json(path: Path, data: dict) -> None:
    """JSON 파일을 UTF-8로 저장한다. (내부 유틸리티)"""
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
