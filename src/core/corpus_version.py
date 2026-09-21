"""코퍼스 스냅샷 해시 — 데이터 버전을 «출력»에 각인한다 (D-128 1항).

무엇이 없었나:
    이 저장소에는 «스키마» 버전(core-schema-v1.3)은 있었지만 «데이터» 버전이
    없었다. 내보낸 사전 JSON이나 인용 목록을 논문에 쓰려면 「이 결과가 어느
    시점의 서고에서 나왔는가」를 나중에 지목할 수 있어야 하는데, 산출물 어디에도
    그 정보가 없었다. 둘은 다른 축이다 — 스키마가 그대로여도 원문 교정이 한 글자
    바뀌면 결과가 달라진다.

왜 «입력»이 아니라 «출력»인가:
    참고한 커넥톰 데이터베이스(neuPrint)는 접속할 때 데이터셋 이름을 주지 않으면
    연결조차 되지 않는다. 목적은 옳지만 그것은 서버·다중 데이터셋·다중 사용자
    환경의 방식이다. 이 도구는 자기 PC에서 서고 하나를 여는 로컬 도구이므로,
    같은 목적을 **사용자 부담 0**으로 달성한다 — 내보낼 때 코드가 알아서 찍는다.
    사용자는 아무것도 입력하지 않는다.

해시는 무엇을 담는가:
    산출물에 기여한 git 저장소들의 HEAD 커밋을 모아 하나의 다이제스트로 접는다.
    **시각·앱 판·스키마 판은 해시에 넣지 않는다.** 해시는 «어느 데이터인가»를
    가리켜야 하므로, 같은 데이터를 두 번 내보내면 같은 해시가 나와야 한다.
    내보낸 시각·앱 판은 옆자리에 따로 적는다.

깨끗하지 않은 작업 트리:
    커밋하지 않은 편집이 남은 채로 내보내면 그 HEAD는 산출물을 재현하지 못한다.
    그래서 저장소마다 `dirty`를 재고, 하나라도 더러우면 스냅샷 전체의
    `reproducible`을 False로 내린다 — 조용히 넘어가면 나중에 그 산출물을 인용한
    사람이 재현에 실패한다.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import git

logger = logging.getLogger(__name__)

# 산출물에 찍히는 접두어. 해시만 떠다니면 무엇의 해시인지 알 수 없다.
CORPUS_STAMP_PREFIX = "ctb-corpus"

# 다이제스트에서 잘라 쓰는 길이. 16진 16자 = 64비트로, 서고 하나에서 충돌할 일이
# 없으면서 사람이 논문 각주에 옮겨 적을 수 있는 길이다.
CORPUS_HASH_LENGTH = 16

# 코어 스키마 판. 데이터 버전과 **다른 축**이므로 해시에 넣지 않고 나란히 적는다.
CORE_SCHEMA_VERSION = "1.3"


def _platform_version() -> str:
    """설치된 패키지 메타데이터에서 앱 판을 읽는다. 실패하면 «unknown».

    왜 상수로 적지 않는가: 판을 적는 곳은 pyproject.toml 하나여야 한다.
    core/snapshot.py가 같은 이유로 같은 방식을 쓴다.
    """
    try:
        from importlib.metadata import version as _pkg_version

        return _pkg_version("classical-text-browser")
    except Exception:  # noqa: BLE001 — 개발 중 미설치 상태에서도 내보내기는 떠야 한다
        return "unknown"


def repo_state(repo_path: str | Path) -> dict:
    """저장소 하나의 HEAD와 더러움을 잰다.

    입력: repo_path — git 저장소 경로(문헌 또는 해석 저장소).
    출력: {"head": 40자 해시 | "no_git" | "empty", "dirty": bool}.

    왜 예외를 삼키는가: 아직 커밋이 없는 저장소·git 아닌 폴더에서도 내보내기는
    되어야 한다. 대신 그 사실을 값으로 남겨 «재현 가능»에서 빼도록 한다.
    """
    repo_path = Path(repo_path)
    try:
        repo = git.Repo(repo_path)
    except Exception:  # noqa: BLE001 — git.InvalidGitRepositoryError·NoSuchPathError 등
        return {"head": "no_git", "dirty": False}
    try:
        head = repo.head.commit.hexsha
    except Exception:  # noqa: BLE001 — 커밋이 하나도 없는 새 저장소
        return {"head": "empty", "dirty": True}
    try:
        # untracked_files=False — 아직 add하지 않은 임시 파일까지 «더럽다»고 보면
        # 거의 언제나 True가 되어 표시가 무의미해진다. 추적 중인 파일의 변경만 센다.
        dirty = bool(repo.is_dirty(untracked_files=False))
    except Exception:  # noqa: BLE001
        dirty = False
    return {"head": head, "dirty": dirty}


def _digest(sources: list[dict]) -> str:
    """기여 저장소 목록을 하나의 다이제스트로 접는다.

    입력: sources — [{"repo": 상대경로, "head": 해시}, ...].
    출력: `ctb-corpus:` 접두어가 붙은 문자열.

    왜 정렬하는가: 같은 데이터를 담은 두 산출물이 저장소를 세는 순서 때문에 다른
    해시를 갖게 되면 «같은 데이터인가»를 해시로 물을 수 없게 된다.
    """
    payload = json.dumps(
        [{"repo": s["repo"], "head": s["head"]} for s in sorted(sources, key=lambda s: s["repo"])],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:CORPUS_HASH_LENGTH]
    return f"{CORPUS_STAMP_PREFIX}:{digest}"


def corpus_snapshot(
    library_path: str | Path,
    *,
    document_ids: list[str] | tuple[str, ...] = (),
    interpretation_ids: list[str] | tuple[str, ...] = (),
) -> dict:
    """산출물에 각인할 코퍼스 스냅샷을 조립한다.

    입력:
        library_path — 서고 루트.
        document_ids — 이 산출물에 기여한 원본 문헌 id 목록.
        interpretation_ids — 기여한 해석 저장소 id 목록.
    출력:
        {
          "corpus_hash": "ctb-corpus:0123456789abcdef",
          "schema_version": "1.3",
          "platform_version": "1.2.3",
          "exported_at": "2026-09-21T...Z",
          "reproducible": True,
          "sources": [{"repo": "documents/hojae", "head": "...", "dirty": False}, ...]
        }

    왜 목록을 인자로 받는가: 산출물마다 기여한 저장소가 다르다. 사전 내보내기는
    해석 하나 + 문헌 하나지만, 서고 전체 보고서는 여럿이다. 함수가 스스로
    서고를 훑으면 «쓰지도 않은 문헌»이 해시에 섞여 무관한 편집에도 해시가 변한다.
    """
    library_path = Path(library_path).resolve()
    sources: list[dict] = []

    for doc_id in dict.fromkeys(document_ids):  # 중복 제거, 순서 유지
        state = repo_state(library_path / "documents" / doc_id)
        sources.append({"repo": f"documents/{doc_id}", **state})
    for interp_id in dict.fromkeys(interpretation_ids):
        state = repo_state(library_path / "interpretations" / interp_id)
        sources.append({"repo": f"interpretations/{interp_id}", **state})

    reproducible = bool(sources) and all(
        not s["dirty"] and s["head"] not in ("no_git", "empty") for s in sources
    )

    return {
        "corpus_hash": _digest(sources),
        "schema_version": CORE_SCHEMA_VERSION,
        "platform_version": _platform_version(),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "reproducible": reproducible,
        "sources": sources,
    }


def stamp(payload: dict, snapshot: dict, *, key: str = "corpus_version") -> dict:
    """JSON 산출물에 스냅샷을 붙인다 (제자리 수정 후 같은 dict를 돌려준다).

    입력: payload — 내보낼 dict. snapshot — corpus_snapshot() 결과.
    출력: 같은 dict(체이닝 편의).
    """
    payload[key] = snapshot
    return payload


def stamp_comment(snapshot: dict, *, prefix: str = "#") -> str:
    """CSV·텍스트 산출물의 머리에 붙일 한 줄을 만든다.

    입력: snapshot — corpus_snapshot() 결과. prefix — 주석 기호.
    출력: 예) `# ctb-corpus:0123456789abcdef · 스키마 1.3 · 앱 1.2.3 · 2026-09-21T…`

    왜 한 줄인가: CSV를 엑셀로 여는 사람이 있다. 여러 줄을 얹으면 표가 깨져 보이고,
    그러면 다음 사람이 «이 줄 지우고 쓰세요»라고 안내하게 되어 결국 사라진다.
    """
    parts = [
        snapshot.get("corpus_hash", ""),
        f"스키마 {snapshot.get('schema_version', '?')}",
        f"앱 {snapshot.get('platform_version', '?')}",
        snapshot.get("exported_at", ""),
    ]
    if not snapshot.get("reproducible", False):
        # 재현 불가를 조용히 넘기지 않는다 — 이 줄을 보고 커밋한 뒤 다시 내보내라는 뜻이다.
        parts.append("커밋되지 않은 편집 있음")
    return f"{prefix} " + " · ".join(p for p in parts if p)
