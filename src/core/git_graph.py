"""Git 그래프 데이터 생성 모듈.

Phase 12-1: 원본 저장소(L1~L4)와 해석 저장소(L5~L7)의 커밋을
사다리형 이분 그래프로 시각화하기 위한 데이터를 생성한다.

왜 이렇게 하는가:
    두 저장소의 커밋 이력을 한 화면에 나란히 보여주면,
    해석 작업이 어떤 원본 시점을 기반했는지 직관적으로 파악할 수 있다.
    Based-On-Original trailer로 명시적 연결을, 타임스탬프로 추정 연결을 만든다.
"""

import re
from pathlib import Path

import git


# ──────────────────────────────────────
# trailer 파싱
# ──────────────────────────────────────


def parse_trailer(commit_message: str, key: str) -> str | None:
    """Git commit message에서 trailer 값을 추출한다.

    목적: Based-On-Original 등의 trailer를 커밋 메시지 끝에서 찾는다.
    입력:
        commit_message — 전체 커밋 메시지.
        key — trailer 키. 예: "Based-On-Original".
    출력: trailer 값 (해시 문자열). 없으면 None.
    """
    pattern = rf'^{re.escape(key)}:\s*(.+)$'
    for line in reversed(commit_message.strip().splitlines()):
        match = re.match(pattern, line.strip())
        if match:
            return match.group(1).strip()
    return None


def extract_layers_affected(commit_message: str) -> list[str]:
    """커밋 메시지에서 영향받은 레이어를 추출한다.

    왜 이렇게 하는가:
        커밋 메시지의 prefix로 어떤 층이 변경되었는지 판단한다.
        예: "feat: L5 표점 추가" → ["L5"]
        prefix가 없으면 "unknown"을 반환한다.
    """
    first_line = commit_message.strip().split("\n")[0]
    layers = []

    # L1~L8 패턴 검색
    for match in re.finditer(r'\bL(\d)\b', first_line):
        layer = f"L{match.group(1)}"
        if layer not in layers:
            layers.append(layer)

    # 세부 레이어 (L5_punctuation, L5_hyeonto 등)
    # layers를 순회하면서 동시에 추가하면 무한 루프가 발생하므로 복사본 사용
    base_layers = list(layers)
    for sub in ["punctuation", "hyeonto", "reading", "translation", "annotation"]:
        if sub in first_line.lower():
            for base in base_layers:
                refined = f"{base}_{sub}"
                if refined not in layers:
                    layers.append(refined)

    return layers if layers else ["unknown"]


# ──────────────────────────────────────
# 커밋 로그 수집
# ──────────────────────────────────────


def _collect_commits(
    repo_path: Path,
    branch: str = "auto",
    max_count: int = 50,
    offset: int = 0,
    pushed_only: bool = False,
) -> tuple[list[dict], int, list[str], str | None]:
    """Git 저장소에서 커밋 로그를 수집한다.

    출력: (커밋 리스트, 전체 커밋 수, 가용 브랜치 목록, HEAD 해시).

    왜 HEAD 해시를 반환하는가:
        Phase 12-2에서 그래프에 "현재 작업 시점"을 표시하기 위해,
        프론트엔드가 어떤 커밋이 HEAD인지 알아야 한다.
    왜 pushed_only가 필요한가:
        교정 저장마다 자동 커밋이 생기므로, push 시점의 커밋만 보면
        급행 정거장처럼 의미 있는 단위만 확인할 수 있다.
    """
    try:
        repo = git.Repo(repo_path)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        return [], 0, [], None

    # HEAD 해시 추출
    try:
        head_hash = repo.head.commit.hexsha
    except (ValueError, TypeError):
        head_hash = None

    # 가용 브랜치
    branches = [b.name for b in repo.branches]

    selected_branch = _resolve_branch_name(repo, branch, branches)

    # pushed_only 모드: reflog에서 push 시점 해시만 추출하여 필터링
    milestone_hashes = None
    if pushed_only:
        milestone_hashes = _get_push_milestone_hashes(repo, selected_branch)
        # 마일스톤이 없으면 전체 표시로 폴백
        if not milestone_hashes:
            milestone_hashes = None

    # 해당 브랜치의 커밋
    try:
        total = sum(1 for _ in repo.iter_commits(selected_branch))
    except (git.GitCommandError, ValueError):
        total = 0
        return [], total, branches, head_hash

    commits = []
    if milestone_hashes is not None:
        # 급행 정거장 모드: 마일스톤 해시에 해당하는 커밋만 수집
        for h in milestone_hashes[:max_count]:
            try:
                c = repo.commit(h)
                commits.append({
                    "hash": c.hexsha,
                    "short_hash": c.hexsha[:7],
                    "message": c.message.strip(),
                    "author": str(c.author),
                    "timestamp": c.committed_datetime.isoformat(),
                    "layers_affected": extract_layers_affected(c.message),
                    "tags": [t.name for t in c.tags] if hasattr(c, "tags") else [],
                })
            except (git.BadName, ValueError):
                continue
    else:
        for i, c in enumerate(repo.iter_commits(selected_branch, max_count=max_count + offset)):
            if i < offset:
                continue
            commits.append({
                "hash": c.hexsha,
                "short_hash": c.hexsha[:7],
                "message": c.message.strip(),
                "author": str(c.author),
                "timestamp": c.committed_datetime.isoformat(),
                "layers_affected": extract_layers_affected(c.message),
                "tags": [t.name for t in c.tags] if hasattr(c, "tags") else [],
            })

    return commits, total if milestone_hashes is None else len(commits), branches, head_hash


def _get_push_milestone_hashes(
    repo: git.Repo, branch_name: str
) -> list[str] | None:
    """원격 추적 브랜치의 reflog에서 push 시점의 커밋 해시를 추출한다.

    목적: 그래프에서 급행 정거장 모드를 지원하기 위해,
          push가 실행된 시점의 HEAD 커밋 해시만 모은다.
    출력: 최신순 해시 리스트, 또는 원격이 없으면 None.
    """
    remote_ref = _find_remote_ref(repo, branch_name)
    if not remote_ref:
        return None

    try:
        raw = repo.git.execute(
            ["git", "reflog", "show", remote_ref, "--format=%H|%gs"]
        )
    except git.GitCommandError:
        return None

    if not raw.strip():
        return None

    hashes = []
    for line in raw.strip().split("\n"):
        parts = line.split("|", 1)
        if len(parts) < 2:
            continue
        h, subject = parts
        if "push" in subject.lower():
            hashes.append(h)

    return hashes if hashes else None


def _find_remote_ref(repo: git.Repo, branch_name: str) -> str | None:
    """로컬 브랜치에 대응하는 원격 추적 참조를 찾는다.

    목적: pushed_only 필터에서 원격에 존재하는 커밋 범위를 특정한다.
    출력: 'origin/main' 같은 참조 문자열, 또는 원격이 없으면 None.
    """
    # 1) tracking branch 직접 조회
    try:
        for b in repo.branches:
            if b.name == branch_name:
                tracking = b.tracking_branch()
                if tracking:
                    return tracking.name
                break
    except (TypeError, ValueError):
        pass

    # 2) origin/<branch> 존재 여부 확인
    for remote in repo.remotes:
        ref_name = f"{remote.name}/{branch_name}"
        try:
            repo.commit(ref_name)
            return ref_name
        except (git.BadName, ValueError):
            continue

    return None


def _resolve_branch_name(repo: git.Repo, requested: str, branches: list[str]) -> str:
    """요청 브랜치를 실제 사용할 브랜치명으로 해석한다.

    우선순위:
    1) requested가 명시되어 있고 존재하면 그대로 사용
    2) active branch
    3) main / master
    4) 첫 번째 브랜치
    """
    req = (requested or "").strip()

    if req and req != "auto" and req in branches:
        return req

    try:
        active = repo.active_branch.name
        if active in branches:
            return active
    except TypeError:
        pass
    except ValueError:
        pass

    for candidate in ("main", "master"):
        if candidate in branches:
            return candidate

    if branches:
        return branches[0]

    return req or "main"


# ──────────────────────────────────────
# 링크 생성 (커밋 매칭)
# ──────────────────────────────────────


def build_links(
    original_commits: list[dict],
    interp_commits: list[dict],
) -> list[dict]:
    """해석 커밋의 trailer를 파싱하여 원본과의 링크를 생성한다.

    매칭 전략:
    1. explicit: Based-On-Original trailer에서 직접 매칭.
    2. estimated: trailer가 없으면 타임스탬프 기반으로 추정.
       해석 커밋 직전의 원본 커밋을 찾는다.
    """
    links = []
    # 원본 커밋을 타임스탬프 역순으로 정렬 (최신 먼저)
    orig_sorted = sorted(
        original_commits,
        key=lambda c: c["timestamp"],
        reverse=True,
    )

    for ic in interp_commits:
        # 1. trailer에서 Based-On-Original 파싱
        base_hash = parse_trailer(ic["message"], "Based-On-Original")

        if base_hash:
            # 명시적 매칭 — 전체 해시 또는 접두사 매칭
            matched = any(
                oc["hash"] == base_hash or oc["hash"].startswith(base_hash)
                for oc in original_commits
            )
            links.append({
                "original_hash": base_hash,
                "interp_hash": ic["hash"],
                "match_type": "explicit",
            })
        else:
            # 2. fallback: 타임스탬프 기반 추정
            nearest = _find_nearest_original_before(ic["timestamp"], orig_sorted)
            if nearest:
                links.append({
                    "original_hash": nearest["hash"],
                    "interp_hash": ic["hash"],
                    "match_type": "estimated",
                })

    return links


def _find_nearest_original_before(
    interp_timestamp: str,
    original_commits_sorted: list[dict],
) -> dict | None:
    """해석 커밋 직전의 원본 커밋을 찾는다.

    왜 이렇게 하는가:
        trailer가 없는 레거시 커밋에 대해, 해석 작업 시점에
        가장 최근이었던 원본 커밋을 추정한다.
    """
    for oc in original_commits_sorted:
        if oc["timestamp"] <= interp_timestamp:
            return oc
    # 모든 원본이 해석 이후 → 가장 오래된 것 반환
    return original_commits_sorted[-1] if original_commits_sorted else None


# ──────────────────────────────────────
# 메인 API 데이터 생성
# ──────────────────────────────────────


def get_git_graph_data(
    library_path: str | Path,
    doc_id: str,
    interp_id: str,
    original_branch: str = "auto",
    interp_branch: str = "auto",
    limit: int = 50,
    offset: int = 0,
    pushed_only: bool = False,
) -> dict:
    """두 저장소의 커밋 로그를 합쳐서 그래프 데이터를 생성한다.

    목적: /api/git-graph 엔드포인트에서 호출.
    입력:
        library_path — 서고 경로.
        doc_id — 원본 문헌 ID.
        interp_id — 해석 저장소 ID.
        original_branch, interp_branch — 브랜치 이름.
        limit — 각 저장소별 최대 커밋 수.
        offset — 페이지네이션.
    출력: {original: {...}, interpretation: {...}, links: [...], pagination: {...}}.
    """
    library_path = Path(library_path).resolve()
    doc_path = library_path / "documents" / doc_id
    interp_path = library_path / "interpretations" / interp_id

    # 원본 저장소 커밋
    orig_selected_branch = original_branch
    interp_selected_branch = interp_branch

    try:
        orig_repo = git.Repo(doc_path)
        orig_selected_branch = _resolve_branch_name(orig_repo, original_branch, [b.name for b in orig_repo.branches])
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        pass

    try:
        interp_repo = git.Repo(interp_path)
        interp_selected_branch = _resolve_branch_name(interp_repo, interp_branch, [b.name for b in interp_repo.branches])
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        pass

    orig_commits, orig_total, orig_branches, orig_head = _collect_commits(
        doc_path, orig_selected_branch, limit, offset, pushed_only=pushed_only
    )

    # 해석 저장소 커밋
    interp_commits, interp_total, interp_branches, interp_head = _collect_commits(
        interp_path, interp_selected_branch, limit, offset, pushed_only=pushed_only
    )

    # 해석 커밋에 base_original_hash 필드 추가
    for ic in interp_commits:
        base_hash = parse_trailer(ic["message"], "Based-On-Original")
        ic["base_original_hash"] = base_hash
        ic["base_match_type"] = "explicit" if base_hash else "estimated"

    # 링크 생성
    links = build_links(orig_commits, interp_commits)

    return {
        "doc_id": doc_id,
        "original": {
            "branch": orig_selected_branch,
            "requested_branch": original_branch,
            "branches_available": orig_branches,
            "commits": orig_commits,
            "head_hash": orig_head,
        },
        "interpretation": {
            "branch": interp_selected_branch,
            "requested_branch": interp_branch,
            "branches_available": interp_branches,
            "commits": interp_commits,
            "head_hash": interp_head,
        },
        "links": links,
        "pagination": {
            "total_original": orig_total,
            "total_interpretation": interp_total,
            "has_more": (offset + limit) < max(orig_total, interp_total),
        },
    }


# ──────────────────────────────────────
# Phase 12-2: 커밋 시점 파일 조회
# ──────────────────────────────────────


def get_commit_file_list(
    repo_path: Path,
    commit_hash: str,
) -> dict:
    """특정 커밋 시점의 파일 트리를 반환한다.

    목적: 연구자가 과거 시점에 어떤 파일이 있었는지 확인한다.
    입력:
        repo_path — 저장소 경로.
        commit_hash — 대상 커밋 해시 (전체 또는 단축).
    출력: {commit_hash, short_hash, message, timestamp, files: [{path, size}]}.

    왜 이렇게 하는가:
        git show로 커밋 시점의 트리를 순회하면
        그 당시의 파일 목록과 크기를 알 수 있다.
        연구자에게 "그 시점에 무엇이 저장되어 있었는지"를 보여준다.
    """
    try:
        repo = git.Repo(repo_path)
        commit = repo.commit(commit_hash)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        return {"error": f"저장소를 찾을 수 없습니다: {repo_path}"}
    except (git.BadName, ValueError):
        return {"error": f"저장 시점을 찾을 수 없습니다: {commit_hash}"}

    files = []
    for blob in commit.tree.traverse():
        if blob.type == "blob":
            files.append({
                "path": blob.path,
                "size": blob.size,
            })

    return {
        "commit_hash": commit.hexsha,
        "short_hash": commit.hexsha[:7],
        "message": commit.message.strip(),
        "timestamp": commit.committed_datetime.isoformat(),
        "author": str(commit.author),
        "files": sorted(files, key=lambda f: f["path"]),
    }


# 파일 내용 조회 시 최대 크기 (5MB)
_MAX_FILE_CONTENT_SIZE = 5 * 1024 * 1024


def get_commit_file_content(
    repo_path: Path,
    commit_hash: str,
    file_path: str,
) -> dict:
    """특정 커밋 시점의 파일 내용을 반환한다.

    목적: 연구자가 과거 시점의 특정 파일 내용을 읽기 전용으로 확인한다.
    입력:
        repo_path — 저장소 경로.
        commit_hash — 대상 커밋 해시 (전체 또는 단축).
        file_path — 저장소 내 상대 경로.
    출력: {commit_hash, file_path, content, is_binary}.

    왜 이렇게 하는가:
        git show {commit}:{path}와 동일한 효과를 GitPython으로 구현한다.
        바이너리 파일은 is_binary=True를 반환하여 UI에서 안전하게 처리한다.
        5MB 초과 파일은 거부하여 메모리 과다 사용을 방지한다.
    """
    try:
        repo = git.Repo(repo_path)
        commit = repo.commit(commit_hash)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        return {"error": f"저장소를 찾을 수 없습니다: {repo_path}"}
    except (git.BadName, ValueError):
        return {"error": f"저장 시점을 찾을 수 없습니다: {commit_hash}"}

    try:
        blob = commit.tree / file_path
    except KeyError:
        return {"error": f"해당 시점에 파일이 존재하지 않습니다: {file_path}"}

    # 크기 제한
    if blob.size > _MAX_FILE_CONTENT_SIZE:
        return {
            "commit_hash": commit.hexsha,
            "file_path": file_path,
            "content": None,
            "is_binary": False,
            "error": f"파일이 너무 큽니다 ({blob.size:,} 바이트). 최대 {_MAX_FILE_CONTENT_SIZE:,} 바이트까지 지원합니다.",
        }

    # 바이너리 판별 (최초 8KB에서 null 바이트 확인)
    data = blob.data_stream.read()
    sample = data[:8192]
    if b'\x00' in sample:
        return {
            "commit_hash": commit.hexsha,
            "file_path": file_path,
            "content": None,
            "is_binary": True,
        }

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")

    return {
        "commit_hash": commit.hexsha,
        "file_path": file_path,
        "content": text,
        "is_binary": False,
    }


# ──────────────────────────────────────
# Phase 12-2: 안전한 되돌리기
# ──────────────────────────────────────


def revert_to_commit(
    repo_path: Path,
    target_commit_hash: str,
    message: str | None = None,
) -> dict:
    """특정 커밋 시점의 상태로 되돌리는 새 커밋을 생성한다.

    목적: 연구자가 "이 버전으로 되돌리기"를 선택했을 때,
        해당 시점의 전체 파일 상태를 현재 작업 디렉토리에 복원하고
        새 커밋으로 기록한다. 기존 이력은 보존된다.

    왜 이렇게 하는가:
        git reset이 아니라 git checkout {hash} -- . + 새 커밋 방식을 사용한다.
        이렇게 하면 되돌리기 자체가 이력에 남아, 언제든 되돌리기의 되돌리기가 가능하다.
        연구 데이터에서 이력 손실은 절대 허용하지 않는다.

    입력:
        repo_path — 저장소 경로.
        target_commit_hash — 복원할 시점의 커밋 해시.
        message — 커밋 메시지. None이면 자동 생성.
    출력: {reverted: True/False, new_commit_hash, message, target_hash}.
    """
    try:
        repo = git.Repo(repo_path)
        target = repo.commit(target_commit_hash)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        return {"error": f"저장소를 찾을 수 없습니다: {repo_path}"}
    except (git.BadName, ValueError):
        return {"error": f"저장 시점을 찾을 수 없습니다: {target_commit_hash}"}

    short_hash = target.hexsha[:7]

    if message is None:
        message = f"revert: {short_hash} 시점으로 되돌리기"

    # 커밋되지 않은 변경이 있으면 거부 (데이터 손실 방지)
    if repo.is_dirty(untracked_files=True):
        return {
            "error": "커밋되지 않은 변경사항이 있습니다. 먼저 저장한 뒤 다시 시도해 주세요.",
        }

    try:
        # 대상 커밋의 파일 상태를 현재 작업 디렉토리에 복원
        repo.git.checkout(target.hexsha, "--", ".")

        # 대상 커밋에 없는 파일 제거
        # (git checkout {hash} -- . 은 새로 추가된 파일을 자동 삭제하지 않으므로)
        target_paths = set()
        for blob in target.tree.traverse():
            if blob.type == "blob":
                target_paths.add(blob.path)

        # 현재 인덱스에서 대상에 없는 파일 제거
        entries_to_remove = []
        for entry in repo.index.entries:
            path = entry[0] if isinstance(entry, tuple) else entry
            if path not in target_paths:
                entries_to_remove.append(path)

        if entries_to_remove:
            repo.index.remove(entries_to_remove, working_tree=True)

        repo.git.add("-A")

        # 변경사항이 없으면 (이미 같은 상태) 스킵
        if not repo.is_dirty(index=True):
            return {
                "reverted": False,
                "message": "현재 상태가 이미 해당 시점과 동일합니다.",
                "target_hash": target.hexsha,
            }

        new_commit = repo.index.commit(message)

        return {
            "reverted": True,
            "new_commit_hash": new_commit.hexsha,
            "new_short_hash": new_commit.hexsha[:7],
            "message": message,
            "target_hash": target.hexsha,
        }
    except git.GitCommandError as e:
        return {"error": f"되돌리기 실패: {e}"}
