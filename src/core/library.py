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


def _write_json(path: Path, data: dict) -> None:
    """JSON 파일을 UTF-8로 저장한다. (내부 유틸리티)"""
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
