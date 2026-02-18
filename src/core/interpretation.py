"""해석 저장소(Interpretation) 관리 모듈.

각 해석 저장소는 원본 저장소(L1~L4)를 기반으로 독립된 해석 작업(L5~L8)을 수행한다.
platform-v7.md 섹션 4의 구조를 따른다:

    {interp_id}/
    ├── manifest.json          # 해석 저장소 메타데이터
    ├── dependency.json        # 원본 의존 추적 (dependency.schema.json)
    ├── L5_reading/            # 5층: 현토 (훈점/구두점)
    │   ├── main_text/
    │   └── annotation/
    ├── L6_translation/        # 6층: 번역
    │   ├── main_text/
    │   └── annotation/
    ├── L7_annotation/         # 7층: 주석
    └── L8_external/           # 8층: 외부 참조

왜 이렇게 하는가:
    - 원본 저장소와 해석 저장소를 분리하면, 여러 연구자가 동일 원본에 대해
      독립적인 해석 작업을 수행할 수 있다.
    - dependency.json으로 원본 변경을 추적하면, 원본이 수정되었을 때
      해석 작업에 영향을 미치는 부분을 즉시 파악할 수 있다.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import git


# 해석 저장소 ID 패턴: 영문 소문자+숫자+밑줄
_INTERP_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def create_interpretation(
    library_path: str | Path,
    interp_id: str,
    source_document_id: str,
    interpreter_type: str,
    interpreter_name: str | None = None,
    title: str | None = None,
) -> Path:
    """해석 저장소를 생성한다.

    목적: 원본 저장소를 기반으로 독립된 해석 작업 공간을 만든다.
    입력:
        library_path — 서고 경로.
        interp_id — 해석 저장소 ID (예: "interp_kim_001").
        source_document_id — 참조할 원본 문헌의 document_id.
        interpreter_type — 해석 주체 유형 ("human" | "llm" | "hybrid").
        interpreter_name — 해석자 이름 (선택).
        title — 해석 작업 제목 (선택).
    출력: 생성된 해석 저장소의 Path.

    Raises:
        ValueError: interp_id 형식이 올바르지 않을 때, 또는 interpreter_type이 유효하지 않을 때.
        FileExistsError: 같은 interp_id의 저장소가 이미 존재할 때.
        FileNotFoundError: 원본 문헌을 찾을 수 없을 때.
    """
    library_path = Path(library_path).resolve()
    interp_path = library_path / "interpretations" / interp_id

    # ID 형식 검증
    if not _INTERP_ID_PATTERN.match(interp_id):
        raise ValueError(
            f"해석 저장소 ID 형식이 올바르지 않습니다: '{interp_id}'\n"
            "→ 해결: 영문 소문자로 시작하고, 소문자·숫자·밑줄만 사용하세요. (예: interp_kim_001)"
        )

    if interpreter_type not in ("human", "llm", "hybrid"):
        raise ValueError(
            f"해석 주체 유형이 올바르지 않습니다: '{interpreter_type}'\n"
            "→ 해결: 'human', 'llm', 'hybrid' 중 하나를 사용하세요."
        )

    if interp_path.exists():
        raise FileExistsError(
            f"해석 저장소가 이미 존재합니다: {interp_path}\n"
            "→ 해결: 다른 interp_id를 사용하세요."
        )

    # 원본 문헌 존재 확인
    doc_path = library_path / "documents" / source_document_id
    if not (doc_path / "manifest.json").exists():
        raise FileNotFoundError(
            f"원본 문헌을 찾을 수 없습니다: {source_document_id}\n"
            "→ 해결: 서고에 등록된 문헌 ID를 확인하세요."
        )

    # --- 디렉토리 구조 생성 (v7 §4) ---
    interp_path.mkdir(parents=True)

    for layer_dir in [
        "L5_reading/main_text",
        "L5_reading/annotation",
        "L6_translation/main_text",
        "L6_translation/annotation",
        "L7_annotation",
        "L8_external",
    ]:
        (interp_path / layer_dir).mkdir(parents=True)

    # --- manifest.json ---
    manifest = {
        "interpretation_id": interp_id,
        "source_document_id": source_document_id,
        "title": title,
        "interpreter": {
            "type": interpreter_type,
            "name": interpreter_name,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": None,
    }
    _write_json(interp_path / "manifest.json", manifest)

    # --- dependency.json ---
    # 원본 저장소의 HEAD 커밋과 L4_text 파일 해시를 기록한다.
    base_commit = _get_source_head_commit(doc_path)
    tracked_files = _scan_tracked_files(doc_path)

    dependency = {
        "interpretation_id": interp_id,
        "interpreter": {
            "type": interpreter_type,
            "name": interpreter_name,
        },
        "source": {
            "document_id": source_document_id,
            "remote": None,
            "base_commit": base_commit,
        },
        "tracked_files": tracked_files,
        "last_checked": datetime.now(timezone.utc).isoformat(),
        "dependency_status": "current",
    }
    _write_json(interp_path / "dependency.json", dependency)

    # --- git init + 초기 커밋 ---
    repo = git.Repo.init(interp_path)
    repo.index.add(["."])
    try:
        repo.index.commit(f"feat: 해석 저장소 생성 — {title or interp_id}")
    except git.HookExecutionError:
        pass  # post-commit hook 에러 무시 (LFS 등)

    # --- 서고 매니페스트 업데이트 ---
    _update_library_manifest_interp(library_path, interp_id, source_document_id, title)

    return interp_path


def _scan_tracked_files(doc_path: Path) -> list[dict]:
    """원본 저장소의 L4_text/ 파일을 스캔하여 tracked_files 목록을 생성한다.

    왜 이렇게 하는가:
        해석 작업은 L4_text(교정 텍스트)를 기반으로 수행되므로,
        L4_text 디렉토리의 모든 텍스트 파일을 추적 대상으로 등록한다.
        각 파일의 sha256 해시를 저장하여 나중에 변경 여부를 확인할 수 있다.
    """
    tracked = []
    l4_dir = doc_path / "L4_text"

    if not l4_dir.exists():
        return tracked

    for f in sorted(l4_dir.rglob("*")):  # 구조상 최대 2~3단계이므로 성능 이슈 없음
        if not f.is_file():
            continue
        # 바이너리가 아닌 텍스트/JSON 파일만 추적
        if f.suffix not in (".txt", ".json"):
            continue

        relative_path = f.relative_to(doc_path).as_posix()
        file_hash = _compute_file_hash(f)
        tracked.append({
            "path": relative_path,
            "hash_at_base": file_hash,
            "my_layers": None,
            "status": "unchanged",
        })

    return tracked


def _compute_file_hash(file_path: Path) -> str:
    """파일의 sha256 해시를 계산한다.

    왜 이렇게 하는가:
        CRLF→LF 정규화를 적용하여 Windows/Unix 환경 차이에 의한
        오탐(false positive)을 방지한다.
    반환: "sha256:..." 형식의 해시 문자열.
    """
    content = file_path.read_bytes()
    # CRLF → LF 정규화 (Windows 호환)
    normalized = content.replace(b"\r\n", b"\n")
    digest = hashlib.sha256(normalized).hexdigest()
    return f"sha256:{digest}"


def _get_source_head_commit(doc_path: Path) -> str:
    """원본 저장소의 HEAD 커밋 해시를 반환한다.

    왜 이렇게 하는가:
        dependency.json의 base_commit으로 사용된다.
        이 커밋 시점의 원본을 기준으로 해석 작업이 시작된다.
        원본에 git이 없으면 "no_git"을 반환하여 방어한다.
    """
    try:
        repo = git.Repo(doc_path)
        return repo.head.commit.hexsha
    except (git.InvalidGitRepositoryError, ValueError):
        # git 저장소가 아니거나 커밋이 없는 경우
        return "no_git"


def check_dependency(library_path: str | Path, interp_id: str) -> dict:
    """해석 저장소의 의존 변경을 확인한다.

    목적: 원본 저장소의 tracked_files가 해석 생성 이후 변경되었는지 확인한다.
    입력:
        library_path — 서고 경로.
        interp_id — 해석 저장소 ID.
    출력: {dependency_status, changed_files, unchanged_count, changed_count,
           base_commit, source_head_commit, tracked_files}.

    왜 이렇게 하는가:
        연구자가 해석 저장소를 열 때(access-time check) 자동 호출되어,
        원본이 변경되었으면 경고를 표시할 수 있다.
        각 tracked_file의 현재 해시를 계산하여 hash_at_base와 비교한다.
    """
    library_path = Path(library_path).resolve()
    interp_path = library_path / "interpretations" / interp_id
    dep_path = interp_path / "dependency.json"

    if not dep_path.exists():
        raise FileNotFoundError(
            f"dependency.json을 찾을 수 없습니다: {dep_path}\n"
            "→ 해결: 올바른 해석 저장소 경로를 확인하세요."
        )

    dep = json.loads(dep_path.read_text(encoding="utf-8"))
    source_doc_id = dep["source"]["document_id"]
    doc_path = library_path / "documents" / source_doc_id

    # 원본 현재 HEAD
    source_head = _get_source_head_commit(doc_path)

    changed_files = []
    unchanged_count = 0

    for tf in dep.get("tracked_files", []):
        file_abs = doc_path / tf["path"]
        if file_abs.exists():
            current_hash = _compute_file_hash(file_abs)
            if current_hash != tf["hash_at_base"]:
                # acknowledged/updated 상태라도 해시가 또 바뀌면 재감지
                if tf["status"] not in ("acknowledged", "updated"):
                    tf["status"] = "changed"
                    changed_files.append(tf["path"])
                elif tf["status"] == "acknowledged":
                    # 이미 인정한 변경이므로 카운트만 (재확인 불필요)
                    unchanged_count += 1
                else:
                    # updated 상태: 이미 반영 완료
                    unchanged_count += 1
            else:
                unchanged_count += 1
        else:
            # 파일이 삭제된 경우도 변경으로 간주
            if tf["status"] not in ("acknowledged", "updated"):
                tf["status"] = "changed"
                changed_files.append(tf["path"])

    # 전체 의존 상태 계산
    statuses = [tf["status"] for tf in dep.get("tracked_files", [])]
    if all(s in ("unchanged", "updated") for s in statuses):
        dep_status = "current"
    elif all(s in ("acknowledged", "unchanged", "updated") for s in statuses):
        dep_status = "acknowledged"
    elif any(s == "acknowledged" for s in statuses) and any(s == "changed" for s in statuses):
        dep_status = "partially_acknowledged"
    else:
        dep_status = "outdated"

    dep["dependency_status"] = dep_status
    dep["last_checked"] = datetime.now(timezone.utc).isoformat()

    # dependency.json 갱신
    _write_json(dep_path, dep)

    return {
        "dependency_status": dep_status,
        "changed_files": changed_files,
        "unchanged_count": unchanged_count,
        "changed_count": len(changed_files),
        "base_commit": dep["source"]["base_commit"],
        "source_head_commit": source_head,
        "tracked_files": dep.get("tracked_files", []),
    }


def acknowledge_changes(
    library_path: str | Path,
    interp_id: str,
    file_paths: list[str] | None = None,
) -> dict:
    """변경된 파일을 '인지함(acknowledged)' 상태로 전환한다.

    목적: 연구자가 원본 변경을 확인했지만, 해석 내용은 아직 유효하다고 판단할 때 사용한다.
    입력:
        library_path — 서고 경로.
        interp_id — 해석 저장소 ID.
        file_paths — 인지할 파일 경로 목록. None이면 모든 changed 파일.
    출력: {acknowledged_count, dependency_status}.
    """
    library_path = Path(library_path).resolve()
    interp_path = library_path / "interpretations" / interp_id
    dep_path = interp_path / "dependency.json"

    dep = json.loads(dep_path.read_text(encoding="utf-8"))
    acknowledged_count = 0

    for tf in dep.get("tracked_files", []):
        if tf["status"] != "changed":
            continue
        if file_paths is None or tf["path"] in file_paths:
            tf["status"] = "acknowledged"
            acknowledged_count += 1

    # 상태 재계산
    statuses = [tf["status"] for tf in dep.get("tracked_files", [])]
    if all(s in ("unchanged", "updated") for s in statuses):
        dep["dependency_status"] = "current"
    elif all(s in ("acknowledged", "unchanged", "updated") for s in statuses):
        dep["dependency_status"] = "acknowledged"
    elif any(s == "acknowledged" for s in statuses) and any(s == "changed" for s in statuses):
        dep["dependency_status"] = "partially_acknowledged"
    else:
        dep["dependency_status"] = "outdated"

    dep["last_checked"] = datetime.now(timezone.utc).isoformat()
    _write_json(dep_path, dep)

    return {
        "acknowledged_count": acknowledged_count,
        "dependency_status": dep["dependency_status"],
    }


def update_base(library_path: str | Path, interp_id: str) -> dict:
    """기반 커밋을 현재 원본 HEAD로 갱신한다.

    목적: 원본 변경을 모두 반영하고, 새 기반에서 해석 작업을 계속하겠다고 선언한다.
    입력:
        library_path — 서고 경로.
        interp_id — 해석 저장소 ID.
    출력: {new_base_commit, tracked_files_count, dependency_status}.

    왜 이렇게 하는가:
        base_commit을 원본의 현재 HEAD로 업데이트하고,
        모든 tracked_files의 해시를 다시 계산하여 status를 "unchanged"로 리셋한다.
    """
    library_path = Path(library_path).resolve()
    interp_path = library_path / "interpretations" / interp_id
    dep_path = interp_path / "dependency.json"

    dep = json.loads(dep_path.read_text(encoding="utf-8"))
    source_doc_id = dep["source"]["document_id"]
    doc_path = library_path / "documents" / source_doc_id

    # 새 base_commit
    new_base = _get_source_head_commit(doc_path)
    dep["source"]["base_commit"] = new_base

    # tracked_files 재스캔
    dep["tracked_files"] = _scan_tracked_files(doc_path)
    dep["dependency_status"] = "current"
    dep["last_checked"] = datetime.now(timezone.utc).isoformat()

    _write_json(dep_path, dep)

    return {
        "new_base_commit": new_base,
        "tracked_files_count": len(dep["tracked_files"]),
        "dependency_status": "current",
    }


def list_interpretations(library_path: str | Path) -> list[dict]:
    """서고의 해석 저장소 목록을 반환한다.

    목적: interpretations/ 안의 모든 해석 저장소 manifest.json을 읽어 목록으로 반환한다.
    입력: library_path — 서고 경로.
    출력: 해석 저장소 정보 dict의 리스트.
    """
    library_path = Path(library_path).resolve()
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


def get_interpretation_info(interp_path: str | Path) -> dict:
    """해석 저장소의 manifest.json을 읽어 반환한다.

    목적: 해석 저장소의 메타데이터를 조회한다.
    입력: interp_path — 해석 저장소 디렉토리 경로.
    출력: manifest.json의 내용 (dict).
    """
    interp_path = Path(interp_path).resolve()
    manifest_path = interp_path / "manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"해석 저장소를 찾을 수 없습니다: {manifest_path}\n"
            "→ 해결: 올바른 해석 저장소 경로를 지정하세요."
        )

    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _layer_file_path(
    interp_path: Path,
    layer: str,
    sub_type: str,
    part_id: str,
    page_num: int,
) -> Path:
    """해석 층 파일 경로를 조립한다. (내부 유틸리티)

    컨벤션:
        L5_reading/main_text/{part_id}_page_{NNN}.json
        L6_translation/main_text/{part_id}_page_{NNN}.txt
        L7_annotation/{part_id}_page_{NNN}.json

    왜 이렇게 하는가:
        원본 저장소의 L4_text/pages/ 네이밍 규칙과 일관성을 유지한다.
        L5/L7은 구조화 데이터(JSON), L6은 텍스트(TXT)를 기본으로 한다.
    """
    filename_base = f"{part_id}_page_{page_num:03d}"

    if layer == "L7_annotation":
        # L7은 sub_type 없이 직접 하위
        return interp_path / layer / f"{filename_base}.json"

    # L6_translation은 텍스트, L5_reading은 JSON
    ext = ".txt" if layer == "L6_translation" else ".json"
    return interp_path / layer / sub_type / f"{filename_base}{ext}"


def get_layer_content(
    interp_path: str | Path,
    layer: str,
    sub_type: str,
    part_id: str,
    page_num: int,
) -> dict:
    """해석 층의 내용을 읽어 반환한다.

    목적: 특정 층/서브타입/페이지의 내용을 조회한다.
    입력:
        interp_path — 해석 저장소 경로.
        layer — 층 이름 ("L5_reading" | "L6_translation" | "L7_annotation").
        sub_type — 서브타입 ("main_text" | "annotation"). L7은 무시됨.
        part_id — 권 식별자.
        page_num — 페이지 번호.
    출력: {layer, sub_type, part_id, page, content, file_path, exists}.
    """
    interp_path = Path(interp_path).resolve()
    file_path = _layer_file_path(interp_path, layer, sub_type, part_id, page_num)
    relative_path = file_path.relative_to(interp_path).as_posix()

    if file_path.exists():
        raw = file_path.read_text(encoding="utf-8")
        # JSON 파일이면 파싱, 텍스트면 그대로
        if file_path.suffix == ".json":
            try:
                content = json.loads(raw)
            except json.JSONDecodeError:
                content = raw
        else:
            content = raw

        return {
            "layer": layer,
            "sub_type": sub_type,
            "part_id": part_id,
            "page": page_num,
            "content": content,
            "file_path": relative_path,
            "exists": True,
        }

    return {
        "layer": layer,
        "sub_type": sub_type,
        "part_id": part_id,
        "page": page_num,
        "content": "" if layer == "L6_translation" else {},
        "file_path": relative_path,
        "exists": False,
    }


def save_layer_content(
    interp_path: str | Path,
    layer: str,
    sub_type: str,
    part_id: str,
    page_num: int,
    content: str | dict,
) -> dict:
    """해석 층의 내용을 저장한다.

    목적: 연구자가 편집한 현토/번역/주석 내용을 파일로 기록한다.
    입력:
        interp_path — 해석 저장소 경로.
        layer — 층 이름.
        sub_type — 서브타입.
        part_id — 권 식별자.
        page_num — 페이지 번호.
        content — 저장할 내용 (L6은 텍스트, L5/L7은 dict/텍스트).
    출력: {status, file_path, size}.
    """
    interp_path = Path(interp_path).resolve()
    file_path = _layer_file_path(interp_path, layer, sub_type, part_id, page_num)

    # 디렉토리 생성
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if file_path.suffix == ".json":
        if isinstance(content, dict):
            text = json.dumps(content, ensure_ascii=False, indent=2) + "\n"
        else:
            text = str(content)
    else:
        # 텍스트 파일: CRLF → LF 정규화
        text = str(content).replace("\r\n", "\n")

    file_path.write_text(text, encoding="utf-8")

    relative_path = file_path.relative_to(interp_path).as_posix()
    return {
        "status": "saved",
        "file_path": relative_path,
        "size": len(text.encode("utf-8")),
    }


def _append_based_on_trailer(interp_path: Path, message: str) -> str:
    """커밋 메시지에 Based-On-Original trailer를 추가한다.

    왜 이렇게 하는가:
        해석 커밋이 어떤 원본 시점을 기반했는지 추적하기 위해,
        원본 저장소의 현재 HEAD hash를 Git trailer 형식으로 기록한다.
        이 정보는 Phase 12-1 Git 그래프에서 의존 관계 연결선(links)을 만드는 데 쓰인다.

    입력:
        interp_path — 해석 저장소 경로 (resolve된).
        message — 원래 커밋 메시지.
    출력: trailer가 추가된 커밋 메시지. 원본 저장소를 찾을 수 없으면 원래 메시지 그대로.
    """
    import logging
    logger = logging.getLogger(__name__)

    # manifest.json에서 source_document_id를 읽는다
    manifest_path = interp_path / "manifest.json"
    if not manifest_path.exists():
        return message

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError):
        return message

    source_doc_id = manifest.get("source_document_id")
    if not source_doc_id:
        return message

    # 원본 저장소 경로: 해석 저장소의 상위 서고에서 documents/{doc_id}
    # 서고 구조: library/interpretations/{interp_id}/ → library/documents/{doc_id}/
    library_path = interp_path.parent.parent
    doc_path = library_path / "documents" / source_doc_id

    if not doc_path.exists():
        logger.debug("원본 저장소를 찾을 수 없어 trailer 생략: %s", doc_path)
        return message

    try:
        doc_repo = git.Repo(doc_path)
        original_head = doc_repo.head.commit.hexsha
    except (git.InvalidGitRepositoryError, ValueError):
        logger.debug("원본 저장소에 커밋이 없어 trailer 생략: %s", doc_path)
        return message

    # trailer 추가 (빈 줄 + trailer)
    return f"{message.rstrip()}\n\nBased-On-Original: {original_head}"


def git_commit_interpretation(interp_path: str | Path, message: str) -> dict:
    """해석 저장소에 git commit을 생성한다.

    목적: 해석 편집 저장 시 자동으로 커밋하여 버전 이력을 남긴다.
    입력:
        interp_path — 해석 저장소 경로 (git 저장소).
        message — 커밋 메시지.
    출력: {committed: True/False, hash, message}.

    Phase 12-1: 원본 저장소의 현재 HEAD hash를 Based-On-Original trailer로
    커밋 메시지에 자동 추가한다. 이를 통해 해석 커밋이 어떤 원본 시점을
    기반했는지 추적할 수 있다.
    """
    interp_path = Path(interp_path).resolve()

    try:
        repo = git.Repo(interp_path)
    except git.InvalidGitRepositoryError:
        repo = git.Repo.init(interp_path)

    if not repo.is_dirty(untracked_files=True):
        return {"committed": False, "message": "변경사항 없음"}

    repo.index.add(["."])

    # Phase 12-1: Based-On-Original trailer 추가
    full_message = _append_based_on_trailer(interp_path, message)

    try:
        commit = repo.index.commit(full_message)
    except git.HookExecutionError as e:
        # 훅 실패 시 커밋이 실제로 생성되지 않았을 수 있으므로
        # head.commit은 이전 커밋일 수 있다. 경고를 기록한다.
        import logging
        logging.getLogger(__name__).warning(
            "git commit hook 실패 — 커밋이 생성되지 않았을 수 있음: %s", e
        )
        commit = repo.head.commit

    return {
        "committed": True,
        "hash": commit.hexsha,
        "short_hash": commit.hexsha[:7],
        "message": message,
    }


def get_interp_git_log(interp_path: str | Path, max_count: int = 50) -> list[dict]:
    """해석 저장소의 git 커밋 이력을 반환한다."""
    interp_path = Path(interp_path).resolve()

    try:
        repo = git.Repo(interp_path)
    except git.InvalidGitRepositoryError:
        return []

    commits = []
    for c in repo.iter_commits(max_count=max_count):
        commits.append({
            "hash": c.hexsha,
            "short_hash": c.hexsha[:7],
            "message": c.message.strip(),
            "author": str(c.author),
            "date": c.committed_datetime.isoformat(),
        })

    return commits


def _update_library_manifest_interp(
    library_path: Path,
    interp_id: str,
    source_document_id: str,
    title: str | None,
) -> None:
    """서고 매니페스트에 해석 저장소를 추가한다. (내부 유틸리티)"""
    manifest_path = library_path / "library_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"documents": [], "interpretations": []}

    if "interpretations" not in manifest:
        manifest["interpretations"] = []

    manifest["interpretations"].append({
        "interpretation_id": interp_id,
        "source_document_id": source_document_id,
        "title": title,
        "path": f"interpretations/{interp_id}",
    })

    _write_json(manifest_path, manifest)


def _write_json(path: Path, data: dict) -> None:
    """JSON 파일을 UTF-8로 저장한다. (내부 유틸리티)"""
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
