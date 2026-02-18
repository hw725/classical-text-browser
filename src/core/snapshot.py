"""JSON 스냅샷 Export/Import 모듈.

Phase 12-3: Work 전체(원본 L1~L4 + 해석 L5~L7 + 메타데이터)를
단일 JSON으로 직렬화(export)하고 역직렬화(import)한다.

왜 이렇게 하는가:
    Git 히스토리 없이 현재 HEAD 상태만 스냅샷하면
    백업, 복원, 다른 환경 이동이 간단해진다.
    schema_version을 포함해서 향후 마이그레이션도 가능하다.

Export 흐름:
    build_snapshot(library_path, doc_id, interp_id) → dict

Import 흐름:
    create_work_from_snapshot(library_path, data) → dict
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import git

logger = logging.getLogger(__name__)


# ──────────────────────────────────────
# Export: 스냅샷 조립
# ──────────────────────────────────────

PLATFORM_VERSION = "0.2.0"


def build_snapshot(
    library_path: str | Path,
    doc_id: str,
    interp_id: str,
) -> dict:
    """Work 전체를 JSON 스냅샷 딕셔너리로 조립한다.

    목적: /api/.../export/json 엔드포인트에서 호출.
    입력:
        library_path — 서고 경로.
        doc_id — 원본 문헌 ID.
        interp_id — 해석 저장소 ID.
    출력: 스냅샷 딕셔너리. JSON 직렬화하여 파일로 저장할 수 있다.
    """
    library_path = Path(library_path).resolve()
    doc_path = library_path / "documents" / doc_id
    interp_path = library_path / "interpretations" / interp_id

    return {
        "schema_version": "1.0",
        "export_timestamp": datetime.now(timezone.utc).isoformat(),
        "platform_version": PLATFORM_VERSION,
        "work": _serialize_work_metadata(doc_path, interp_path),
        "original": _serialize_original(doc_path),
        "interpretation": _serialize_interpretation(interp_path),
        "variant_characters": _serialize_variant_chars(library_path),
        "annotation_types": _serialize_annotation_types(library_path),
    }


def _serialize_work_metadata(doc_path: Path, interp_path: Path) -> dict:
    """Work 메타데이터를 직렬화한다.

    왜 이렇게 하는가:
        문헌 manifest + 해석 manifest에서 필요한 필드를 모아
        하나의 work 섹션으로 만든다.
    """
    result = {}

    # 문헌 manifest
    doc_manifest = _read_json(doc_path / "manifest.json")
    if doc_manifest:
        result["document_id"] = doc_manifest.get("document_id", "")
        result["title"] = doc_manifest.get("title", "")
        result["title_ko"] = doc_manifest.get("title_ko")
        result["parts"] = doc_manifest.get("parts", [])
        result["created_at"] = doc_manifest.get("created_at")
        result["notes"] = doc_manifest.get("notes")

    # 해석 manifest
    interp_manifest = _read_json(interp_path / "manifest.json")
    if interp_manifest:
        result["interpretation_id"] = interp_manifest.get("interpretation_id", "")
        result["interpretation_title"] = interp_manifest.get("title", "")
        result["interpreter"] = interp_manifest.get("interpreter")

    # 서지정보
    bib = _read_json(doc_path / "bibliography.json")
    if bib:
        result["bibliography"] = bib

    return result


def _serialize_original(doc_path: Path) -> dict:
    """원본 저장소(L1~L4)를 직렬화한다."""
    result = {
        "head_hash": _get_head_hash(doc_path),
        "layers": {},
    }

    # L1: 이미지/PDF — 경로 참조만
    l1_dir = doc_path / "L1_source"
    if l1_dir.exists():
        files = []
        for f in sorted(l1_dir.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                files.append({
                    "path": f.relative_to(doc_path).as_posix(),
                    "name": f.name,
                    "size_bytes": f.stat().st_size,
                })
        result["layers"]["L1_source"] = {
            "type": "reference",
            "note": "이미지/PDF 파일은 경로 참조만 포함. 바이너리 미포함.",
            "files": files,
        }

    # L3: 레이아웃 분석
    l3_dir = doc_path / "L3_layout"
    if l3_dir.exists():
        pages = []
        for f in sorted(l3_dir.glob("*.json")):
            data = _read_json(f)
            if data:
                pages.append(data)
        result["layers"]["L3_layout"] = {
            "type": "inline",
            "pages": pages,
        }

    # L4: 교정 텍스트 + 교정 기록
    l4_text_dir = doc_path / "L4_text" / "pages"
    l4_corrections_dir = doc_path / "L4_text" / "corrections"
    l4_pages = []
    if l4_text_dir.exists():
        for f in sorted(l4_text_dir.glob("*.txt")):
            text = f.read_text(encoding="utf-8")
            page_info = {
                "file_name": f.name,
                "text": text,
            }
            # 대응하는 교정 기록 찾기
            corr_name = f.stem + "_corrections.json"
            corr_path = l4_corrections_dir / corr_name
            if corr_path.exists():
                page_info["corrections"] = _read_json(corr_path)
            l4_pages.append(page_info)

    result["layers"]["L4_text"] = {
        "type": "inline",
        "pages": l4_pages,
    }

    return result


def _serialize_interpretation(interp_path: Path) -> dict:
    """해석 저장소(L5~L7 + 코어 엔티티)를 직렬화한다."""
    result = {
        "head_hash": _get_head_hash(interp_path),
        "layers": {},
    }

    # dependency.json
    dep = _read_json(interp_path / "dependency.json")
    if dep:
        result["base_original_hash"] = dep.get("source", {}).get("base_commit")
        result["dependency"] = dep

    # L5: 표점/현토
    result["layers"]["L5_punctuation"] = _collect_layer_json(
        interp_path, "L5_reading", "*_punctuation.json"
    )
    result["layers"]["L5_hyeonto"] = _collect_layer_json(
        interp_path, "L5_reading", "*_hyeonto.json"
    )

    # L6: 번역
    result["layers"]["L6_translation"] = _collect_layer_json(
        interp_path, "L6_translation", "*_translation.json"
    )

    # L7: 주석
    result["layers"]["L7_annotation"] = _collect_layer_json(
        interp_path, "L7_annotation", "*_annotation.json"
    )

    # 코어 엔티티 (Phase 8)
    entities = {}
    entity_dir = interp_path / "core_entities"
    if entity_dir.exists():
        for type_dir in sorted(entity_dir.iterdir()):
            if type_dir.is_dir():
                items = []
                for f in sorted(type_dir.glob("*.json")):
                    data = _read_json(f)
                    if data:
                        items.append(data)
                if items:
                    entities[type_dir.name] = items
    result["core_entities"] = entities

    return result


def _collect_layer_json(
    interp_path: Path, layer_dir_name: str, pattern: str,
) -> list[dict]:
    """특정 레이어 디렉토리에서 JSON 파일들을 수집한다.

    왜 이렇게 하는가:
        L5~L7은 main_text/, annotation/ 하위 디렉토리에
        페이지별 JSON이 있다. 모두 수집해서 리스트로 반환.
    """
    layer_dir = interp_path / layer_dir_name
    if not layer_dir.exists():
        return []

    results = []
    # 모든 하위 디렉토리 탐색 (main_text, annotation 등)
    for json_file in sorted(layer_dir.rglob(pattern)):
        data = _read_json(json_file)
        if data:
            # 상대 경로를 메타데이터로 추가 (import 시 복원에 필요)
            data["_source_path"] = json_file.relative_to(
                interp_path
            ).as_posix()
            results.append(data)

    return results


def _serialize_variant_chars(library_path: Path) -> dict:
    """이체자 사전을 직렬화한다."""
    # 서고 내 variant_chars.json
    vc_path = library_path / "variant_chars.json"
    if not vc_path.exists():
        # 프로젝트 전역 리소스에서 찾기
        project_root = Path(__file__).resolve().parent.parent.parent
        vc_path = project_root / "resources" / "variant_chars.json"

    if vc_path.exists():
        return _read_json(vc_path) or {}
    return {}


def _serialize_annotation_types(library_path: Path) -> list:
    """주석 유형 목록을 직렬화한다."""
    # 서고 내 커스텀 타입
    custom_path = library_path / "annotation_types_custom.json"
    custom_types = []
    if custom_path.exists():
        data = _read_json(custom_path)
        if data:
            custom_types = data.get("custom", [])

    # 기본 프리셋
    project_root = Path(__file__).resolve().parent.parent.parent
    default_path = project_root / "resources" / "annotation_types.json"
    default_types = []
    if default_path.exists():
        data = _read_json(default_path)
        if data:
            default_types = data.get("types", [])

    return default_types + custom_types


# ──────────────────────────────────────
# Import: 스냅샷에서 Work 생성
# ──────────────────────────────────────


def create_work_from_snapshot(
    library_path: str | Path,
    data: dict,
) -> dict:
    """스냅샷 데이터로 새 Work(문헌 + 해석 저장소)를 생성한다.

    목적: /api/.../import/json 엔드포인트에서 호출.
    입력:
        library_path — 서고 경로.
        data — JSON 스냅샷 딕셔너리.
    출력: {doc_id, interp_id, title, warnings} 결과.

    왜 이렇게 하는가:
        새 Work ID를 발급하여 충돌을 방지한다.
        같은 스냅샷을 여러 번 import해도 각각 독립된 Work가 된다.
    """
    library_path = Path(library_path).resolve()
    work = data.get("work", {})
    original = data.get("original", {})
    interpretation = data.get("interpretation", {})
    warnings = []

    # 새 ID 생성 (원본 ID에 타임스탬프 접미사)
    base_doc_id = work.get("document_id", "imported")
    timestamp_suffix = datetime.now().strftime("%Y%m%d%H%M%S")
    new_doc_id = f"{base_doc_id}_{timestamp_suffix}"

    base_interp_id = work.get("interpretation_id", "imported_interp")
    new_interp_id = f"{base_interp_id}_{timestamp_suffix}"

    doc_path = library_path / "documents" / new_doc_id
    interp_path = library_path / "interpretations" / new_interp_id

    doc_path.mkdir(parents=True, exist_ok=True)
    interp_path.mkdir(parents=True, exist_ok=True)

    # 1. 원본 저장소 복원
    _write_original_layers(doc_path, work, original, warnings)

    # 2. 해석 저장소 복원
    _write_interpretation_layers(interp_path, work, new_doc_id, interpretation, warnings)

    # 3. 이체자 사전
    variant_chars = data.get("variant_characters", {})
    if variant_chars:
        _write_json(library_path / "variant_chars.json", variant_chars)

    # 4. Git 초기 커밋
    _git_init_and_commit(doc_path, "Import: 스냅샷에서 원본 데이터 복원")
    _git_init_and_commit(interp_path, "Import: 스냅샷에서 해석 데이터 복원")

    # 5. library_manifest 업데이트
    _update_library_manifest(library_path, new_doc_id, new_interp_id, work)

    return {
        "doc_id": new_doc_id,
        "interp_id": new_interp_id,
        "title": work.get("title", ""),
        "warnings": warnings,
    }


def _write_original_layers(
    doc_path: Path, work: dict, original: dict, warnings: list,
) -> None:
    """원본 저장소(L1~L4)를 파일로 복원한다."""
    layers = original.get("layers", {})

    # manifest.json
    manifest = {
        "document_id": doc_path.name,
        "title": work.get("title", ""),
        "title_ko": work.get("title_ko"),
        "parts": work.get("parts", []),
        "completeness_status": "imported",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": f"스냅샷에서 Import됨. 원본 ID: {work.get('document_id', 'unknown')}",
    }
    _write_json(doc_path / "manifest.json", manifest)

    # bibliography
    bib = work.get("bibliography")
    if bib:
        _write_json(doc_path / "bibliography.json", bib)

    # L1: 경로 참조만 기록 (바이너리 미포함)
    l1 = layers.get("L1_source", {})
    if l1.get("files"):
        l1_dir = doc_path / "L1_source"
        l1_dir.mkdir(exist_ok=True)
        # 이미지 파일은 없으므로 참조 목록만 기록
        _write_json(l1_dir / "_imported_file_list.json", l1["files"])
        for f_info in l1["files"]:
            warnings.append(
                f"L1 이미지 파일은 포함되지 않음: {f_info.get('path', '?')}"
            )

    # L3: 레이아웃
    l3 = layers.get("L3_layout", {})
    if l3.get("pages"):
        l3_dir = doc_path / "L3_layout"
        l3_dir.mkdir(exist_ok=True)
        for page_data in l3["pages"]:
            part_id = page_data.get("part_id", "vol1")
            page_num = page_data.get("page_number", 0)
            fname = f"{part_id}_page_{page_num:03d}.json"
            _write_json(l3_dir / fname, page_data)

    # L4: 텍스트 + 교정
    l4 = layers.get("L4_text", {})
    if l4.get("pages"):
        pages_dir = doc_path / "L4_text" / "pages"
        corrections_dir = doc_path / "L4_text" / "corrections"
        pages_dir.mkdir(parents=True, exist_ok=True)
        corrections_dir.mkdir(exist_ok=True)

        for page_data in l4["pages"]:
            fname = page_data.get("file_name", "page.txt")
            text = page_data.get("text", "")
            (pages_dir / fname).write_text(text, encoding="utf-8")

            corr = page_data.get("corrections")
            if corr:
                corr_name = Path(fname).stem + "_corrections.json"
                _write_json(corrections_dir / corr_name, corr)


def _write_interpretation_layers(
    interp_path: Path,
    work: dict,
    new_doc_id: str,
    interpretation: dict,
    warnings: list,
) -> None:
    """해석 저장소(L5~L7 + 코어 엔티티)를 파일로 복원한다."""
    layers = interpretation.get("layers", {})

    # manifest.json
    manifest = {
        "interpretation_id": interp_path.name,
        "source_document_id": new_doc_id,
        "title": work.get("interpretation_title", work.get("title", "")),
        "interpreter": work.get("interpreter", {"type": "human", "name": "imported"}),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": f"스냅샷에서 Import됨. 원본 해석 ID: {work.get('interpretation_id', 'unknown')}",
    }
    _write_json(interp_path / "manifest.json", manifest)

    # dependency.json
    dep = interpretation.get("dependency")
    if dep:
        # source.document_id를 새 ID로 교체
        if "source" in dep:
            dep["source"]["document_id"] = new_doc_id
        _write_json(interp_path / "dependency.json", dep)

    # L5~L7: _source_path를 기반으로 파일 복원
    for layer_key in ["L5_punctuation", "L5_hyeonto", "L6_translation", "L7_annotation"]:
        layer_data = layers.get(layer_key, [])
        for item in layer_data:
            source_path = item.pop("_source_path", None)
            if source_path:
                target = interp_path / source_path
                target.parent.mkdir(parents=True, exist_ok=True)
                _write_json(target, item)
            else:
                # _source_path가 없으면 layer_key 기반 기본 경로 사용
                warnings.append(
                    f"{layer_key}: _source_path 없음, 복원 스킵"
                )

    # 코어 엔티티
    entities = interpretation.get("core_entities", {})
    for entity_type, items in entities.items():
        entity_dir = interp_path / "core_entities" / entity_type
        entity_dir.mkdir(parents=True, exist_ok=True)
        for item in items:
            entity_id = item.get("id", "unknown")
            _write_json(entity_dir / f"{entity_id}.json", item)


# ──────────────────────────────────────
# Import 결과 요약
# ──────────────────────────────────────


def detect_imported_layers(data: dict) -> list[str]:
    """스냅샷에서 import된 레이어 목록을 반환한다."""
    layers = []

    orig_layers = data.get("original", {}).get("layers", {})
    if orig_layers.get("L1_source", {}).get("files"):
        layers.append("L1")
    if orig_layers.get("L3_layout", {}).get("pages"):
        layers.append("L3")
    if orig_layers.get("L4_text", {}).get("pages"):
        layers.append("L4")

    interp_layers = data.get("interpretation", {}).get("layers", {})
    if interp_layers.get("L5_punctuation"):
        layers.append("L5_punctuation")
    if interp_layers.get("L5_hyeonto"):
        layers.append("L5_hyeonto")
    if interp_layers.get("L6_translation"):
        layers.append("L6_translation")
    if interp_layers.get("L7_annotation"):
        layers.append("L7_annotation")

    return layers


# ──────────────────────────────────────
# 유틸리티
# ──────────────────────────────────────


def _read_json(path: Path) -> dict | list | None:
    """JSON 파일을 읽는다. 없거나 에러면 None."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("JSON 읽기 실패: %s — %s", path, e)
        return None


def _write_json(path: Path, data: dict | list) -> None:
    """JSON 파일을 쓴다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _get_head_hash(repo_path: Path) -> str | None:
    """Git 저장소의 HEAD 해시를 반환한다."""
    try:
        repo = git.Repo(repo_path)
        return repo.head.commit.hexsha
    except (git.InvalidGitRepositoryError, ValueError, git.NoSuchPathError):
        return None


def _git_init_and_commit(repo_path: Path, message: str) -> None:
    """Git 저장소를 초기화하고 모든 파일을 커밋한다."""
    try:
        repo = git.Repo.init(repo_path)
        repo.index.add([str(f.relative_to(repo_path)) for f in repo_path.rglob("*") if f.is_file()])
        repo.index.commit(message)
    except Exception as e:
        logger.warning("Git 초기화/커밋 실패: %s — %s", repo_path, e)


def _update_library_manifest(
    library_path: Path,
    doc_id: str,
    interp_id: str,
    work: dict,
) -> None:
    """library_manifest.json에 새 문헌/해석 항목을 추가한다."""
    manifest_path = library_path / "library_manifest.json"
    if manifest_path.exists():
        manifest = _read_json(manifest_path) or {}
    else:
        manifest = {
            "name": library_path.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "documents": [],
            "interpretations": [],
        }

    # 문헌 추가
    docs = manifest.setdefault("documents", [])
    docs.append({
        "document_id": doc_id,
        "title": work.get("title", ""),
        "path": f"documents/{doc_id}",
    })

    # 해석 추가
    interps = manifest.setdefault("interpretations", [])
    interps.append({
        "interpretation_id": interp_id,
        "source_document_id": doc_id,
        "title": work.get("interpretation_title", work.get("title", "")),
        "path": f"interpretations/{interp_id}",
    })

    _write_json(manifest_path, manifest)
