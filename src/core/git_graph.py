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
    branch: str = "main",
    max_count: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int, list[str]]:
    """Git 저장소에서 커밋 로그를 수집한다.

    출력: (커밋 리스트, 전체 커밋 수, 가용 브랜치 목록).
    """
    try:
        repo = git.Repo(repo_path)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        return [], 0, []

    # 가용 브랜치
    branches = [b.name for b in repo.branches]

    # 해당 브랜치의 커밋
    try:
        total = sum(1 for _ in repo.iter_commits(branch))
    except (git.GitCommandError, ValueError):
        total = 0
        return [], total, branches

    commits = []
    for i, c in enumerate(repo.iter_commits(branch, max_count=max_count + offset)):
        if i < offset:
            continue
        commits.append({
            "hash": c.hexsha,
            "short_hash": c.hexsha[:7],
            "message": c.message.strip(),
            "author": str(c.author),
            "timestamp": c.committed_datetime.isoformat(),
            "layers_affected": extract_layers_affected(c.message),
            "tags": [t.name for t in c.tags] if hasattr(c, 'tags') else [],
        })

    return commits, total, branches


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
    original_branch: str = "main",
    interp_branch: str = "main",
    limit: int = 50,
    offset: int = 0,
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
    orig_commits, orig_total, orig_branches = _collect_commits(
        doc_path, original_branch, limit, offset
    )

    # 해석 저장소 커밋
    interp_commits, interp_total, interp_branches = _collect_commits(
        interp_path, interp_branch, limit, offset
    )

    # 해석 커밋에 base_original_hash 필드 추가
    for ic in interp_commits:
        base_hash = parse_trailer(ic["message"], "Based-On-Original")
        ic["base_original_hash"] = base_hash
        ic["base_match_type"] = "explicit" if base_hash else "estimated"

    # 링크 생성
    links = build_links(orig_commits, interp_commits)

    return {
        "original": {
            "branch": original_branch,
            "branches_available": orig_branches,
            "commits": orig_commits,
        },
        "interpretation": {
            "branch": interp_branch,
            "branches_available": interp_branches,
            "commits": interp_commits,
        },
        "links": links,
        "pagination": {
            "total_original": orig_total,
            "total_interpretation": interp_total,
            "has_more": (offset + limit) < max(orig_total, interp_total),
        },
    }
