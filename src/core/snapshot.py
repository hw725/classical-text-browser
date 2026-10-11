"""JSON 스냅샷 Export/Import 모듈.

Phase 12-3: 문헌 하나와 그 해석 저장소(원본 L1 참조·L3·L4·편성 경계·작업 계획·문헌별 승인 +
해석 L5~L7·코어 엔티티 + 서고의 이체자 사전·주석 유형)를 단일 JSON으로 직렬화(export)하고
역직렬화(import)한다. L2(OCR)와 원본 이미지는 담지 않는다.

v1.4.3까지는 원본 쪽에 L1·L3·L4만 담아, 내보냈다 들이면 편성 경계(D-097 뒤 원본 저장소의 것)·
작업 계획·문헌별 승인이 사라졌다. 사전·주석 유형도 서고의 옛 자리를 읽어 빠졌다(B-013).

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


def source_info(data: dict) -> dict:
    """스냅샷의 머리말 절. 옛 이름("work")으로 적힌 파일도 받는다 (D-099 후속).

    입력: 스냅샷 dict. 출력: {document_id, title, parts, bibliography,
    interpretation_id, interpretation_title, interpreter, ...}.
    이미 내보낸 스냅샷을 다시 가져올 수 있어야 하므로 읽기는 두 이름을 다 본다.
    """
    return data.get("source_info") or data.get("work") or {}


def normalize_snapshot(data: dict) -> dict:
    """옛 스냅샷을 지금 모양으로 맞춘다 (얕은 사본을 돌려준다).

    왜 필요한가: 교환 형식의 정본은 `schemas/exchange.schema.json`
    하나다(D-100 — 옛 백로그 B-005, 그 번호는 지금 다른 항목). 검증도
    가져오기도 그 스키마를 쓰려면, 옛 이름으로 적힌 파일을 **먼저** 지금 이름으로 옮겨야
    한다 — 스키마에 옛 이름까지 넣으면 정본이 둘이 된다.

    지금 옮기는 것: `work` → `source_info` (v1.3, D-099).
    """
    if "work" not in data:
        return data
    out = dict(data)
    out["source_info"] = out.pop("work") or {}
    return out


# ──────────────────────────────────────
# Import 경로 검사 — 스냅샷의 이름이 서고 밖을 가리키지 못하게
# ──────────────────────────────────────

# 한 칸 이름(파일·폴더 하나)에 들어가면 안 되는 글자. 경로 구분자·드라이브 콜론·Windows 금지 문자.
_BAD_NAME_CHARS = set('/\\:*?"<>|\0')
# 새 문헌 id = 원래 id + «_» + 14자리 시각. 저장소 id는 64자까지라 원래 id는 49자로 자른다.
_IMPORT_ID_BASE_MAX = 64 - 15


def _is_safe_name(name) -> bool:
    """파일·폴더 이름 «한 칸»으로 써도 되는가. 입력: 스냅샷의 값. 출력: 참이면 안전.

    왜: 스냅샷은 남이 만든 파일일 수 있다. `../` 하나로 서고 밖에 파일을 쓸 수 있으면 안 된다
    (2026-10-11 전수 검토 — 폴더 가져오기 라우트에는 이 검사가 있었고 JSON 가져오기에는 없었다).
    점으로 시작하는 이름(`.git` 등)도 막는다 — 숨김 메타데이터를 덮어쓰지 않게.
    """
    return (
        isinstance(name, str)
        and bool(name)
        and not name.startswith(".")
        and not (set(name) & _BAD_NAME_CHARS)
        and name.strip() == name
    )


def _is_safe_relpath(rel) -> bool:
    """`_source_path`처럼 여러 칸짜리 상대 경로가 해석 저장소 안에 머무는가."""
    if not isinstance(rel, str) or not rel or "\\" in rel:
        return False
    parts = rel.split("/")
    return all(_is_safe_name(p) for p in parts)


def unsafe_snapshot_paths(data: dict) -> list[str]:
    """스냅샷 안에서 파일 경로로 쓰일 값 중 안전하지 않은 것을 사람 말로 돌려준다.

    입력: 스냅샷 dict(옛 이름도 받는다). 출력: 문제 목록 — 비어 있으면 들여도 된다.
    검사하는 자리(가져오기가 경로로 쓰는 값 전부): 문헌·해석 id, L3 쪽의 part_id,
    L4 쪽의 file_name, 편성 경계의 part_id, 작업 계획의 권 열쇠, L5~L7의 `_source_path`,
    코어 엔티티의 종류 이름과 id.
    """
    data = normalize_snapshot(data)
    src = source_info(data)
    problems: list[str] = []

    from core.repo_id import REPO_ID_RULE_TEXT, is_valid_repo_id

    for key in ("document_id", "interpretation_id"):
        if key in src and not is_valid_repo_id(str(src.get(key) or "")):
            problems.append(
                f"source_info.{key} '{src.get(key)}'가 저장소 id 규칙"
                f"({REPO_ID_RULE_TEXT})에 맞지 않습니다"
            )

    o_layers = (data.get("original") or {}).get("layers") or {}
    for i, page in enumerate((o_layers.get("L3_layout") or {}).get("pages") or []):
        if not _is_safe_name(str(page.get("part_id", "vol1"))):
            problems.append(
                f"L3 {i}번째 쪽의 part_id '{page.get('part_id')}'를 파일 이름으로 쓸 수 없습니다"
            )
        if not isinstance(page.get("page_number", 0), int):
            problems.append(f"L3 {i}번째 쪽의 page_number가 정수가 아닙니다")
    for i, page in enumerate((o_layers.get("L4_text") or {}).get("pages") or []):
        if not _is_safe_name(page.get("file_name", "page.txt")):
            problems.append(
                f"L4 {i}번째 쪽의 file_name '{page.get('file_name')}'를 "
                "파일 이름으로 쓸 수 없습니다"
            )
    for part in (o_layers.get("boundaries") or {}).get("parts") or []:
        pid = part.get("part_id")
        if pid and not _is_safe_name(pid):
            problems.append(f"편성 경계의 part_id '{pid}'를 파일 이름으로 쓸 수 없습니다")
    for pid in ((o_layers.get("read_plan") or {}).get("parts") or {}):
        if not _is_safe_name(pid):
            problems.append(f"작업 계획의 권 '{pid}'를 파일 이름으로 쓸 수 없습니다")

    interp = data.get("interpretation") or {}
    i_layers = interp.get("layers") or {}
    for layer_key in ("L5_punctuation", "L5_hyeonto", "L6_translation", "L7_annotation"):
        for item in i_layers.get(layer_key) or []:
            sp = item.get("_source_path") if isinstance(item, dict) else None
            if sp is not None and not _is_safe_relpath(sp):
                problems.append(
                    f"{layer_key}의 _source_path '{sp}'가 해석 저장소 밖을 가리키거나 "
                    "쓸 수 없는 이름입니다"
                )
    for etype, items in (interp.get("core_entities") or {}).items():
        if not _is_safe_name(etype):
            problems.append(f"코어 엔티티 종류 '{etype}'를 폴더 이름으로 쓸 수 없습니다")
        for item in items or []:
            if isinstance(item, dict) and not item.get("id"):
                continue  # id가 없거나 비면 들일 때 새 UUID를 붙인다 — 경로 문제가 아니다
            eid = str(item.get("id")) if isinstance(item, dict) else ""
            if not _is_safe_name(eid):
                problems.append(f"코어 엔티티 id '{eid}'를 파일 이름으로 쓸 수 없습니다")
    return problems


def _inside(base: Path, target: Path) -> Path:
    """target이 base 안에 있는지 마지막으로 한 번 더 본다(이름 검사를 피한 길이 있어도 막도록)."""
    resolved = target.resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise ValueError(f"스냅샷의 경로가 저장소 밖을 가리킵니다: {target}")
    return target


def _schemas_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "schemas"


def exchange_schema() -> dict:
    """교환 형식 스키마(정본). schemas/exchange.schema.json을 읽어 캐시한다."""
    global _EXCHANGE_SCHEMA
    if _EXCHANGE_SCHEMA is None:
        _EXCHANGE_SCHEMA = json.loads(
            (_schemas_dir() / "exchange.schema.json").read_text(encoding="utf-8")
        )
    return _EXCHANGE_SCHEMA


def exchange_validator():
    """교환 형식 검증기. 다른 스키마를 `$ref`로 물 수 있게 레지스트리를 붙인다.

    왜 이렇게 하는가: 스냅샷 안의 L3 쪽·교정 기록·서지·dependency·코어 엔티티는 **이미 각자
    스키마가 있다**(`schemas/source_repo/…`, `schemas/core/…`). 교환 스키마가 그 모양을 다시
    베끼면 정본이 또 갈라진다 — `$ref`로 물면 고칠 곳이 언제나 하나다(D-100).

    `$id`가 `layout_page.schema.json`처럼 파일 이름뿐이라 기본 해석기로는 찾지 못한다.
    schemas/ 아래를 훑어 이름 → 스키마 레지스트리를 만들어 넘긴다.
    """
    import jsonschema
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    global _EXCHANGE_VALIDATOR
    if _EXCHANGE_VALIDATOR is None:
        resources = []
        for f in sorted(_schemas_dir().rglob("*.schema.json")):
            doc = json.loads(f.read_text(encoding="utf-8"))
            # default_specification: $schema를 적지 않은 스키마도 레지스트리에 들어가게
            resources.append(
                (
                    doc.get("$id") or f.name,
                    Resource.from_contents(doc, default_specification=DRAFT202012),
                )
            )
        registry = Registry().with_resources(resources)
        _EXCHANGE_VALIDATOR = jsonschema.Draft202012Validator(exchange_schema(), registry=registry)
    return _EXCHANGE_VALIDATOR


_EXCHANGE_SCHEMA: dict | None = None
_EXCHANGE_VALIDATOR = None


def _platform_version() -> str:
    """설치된 패키지 메타데이터에서 앱 판을 읽는다. 실패하면 «unknown».

    왜 여기 적지 않는가: **버전을 적는 곳은 pyproject.toml 하나여야 한다**(릴리스 절차 7).
    v1.1.4부터 v1.2.3까지 이 상수가 "1.1.4"에 멈춰 있어 스냅샷마다 거짓 판을 적고 있었다
    (실측 2026-09-04) — 적는 곳이 둘이면 반드시 어긋난다는 그 규칙의 사례다.
    """
    try:
        from importlib.metadata import version as _pkg_version

        return _pkg_version("classical-text-browser")
    except Exception:  # noqa: BLE001 — 개발 중 미설치 상태에서도 스냅샷은 떠야 한다
        return "unknown"


PLATFORM_VERSION = _platform_version()


def build_snapshot(
    library_path: str | Path,
    doc_id: str,
    interp_id: str,
) -> dict:
    """문헌 하나와 그 해석 저장소를 JSON 스냅샷 딕셔너리로 조립한다.

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

    from .corpus_version import corpus_snapshot

    return {
        "schema_version": "1.0",
        "export_timestamp": datetime.now(timezone.utc).isoformat(),
        "platform_version": PLATFORM_VERSION,
        # 데이터 버전 각인 (D-128 1항). schema_version은 «스키마» 판이고 이것은
        # «데이터» 판이다 — 스키마가 그대로여도 원문 교정 한 글자로 결과가 달라진다.
        "corpus_version": corpus_snapshot(
            library_path, document_ids=[doc_id], interpretation_ids=[interp_id]
        ),
        # D-099 후속: 옛 이름은 "work"였다. Work 엔티티를 없앤 뒤로 «엔티티 Work»와 헷갈려서
        # 이름을 바꿨다 — 이 절은 엔티티가 아니라 «이 스냅샷이 어느 문헌·해석의 것인가»다.
        "source_info": _serialize_source_info(doc_path, interp_path),
        "original": _serialize_original(doc_path),
        "interpretation": _serialize_interpretation(interp_path),
        "variant_characters": _serialize_variant_chars(library_path),
        "annotation_types": _serialize_annotation_types(library_path),
    }


def _serialize_source_info(doc_path: Path, interp_path: Path) -> dict:
    """이 스냅샷이 어느 문헌·해석의 것인지를 직렬화한다.

    왜 이렇게 하는가:
        문헌 manifest + 해석 manifest에서 필요한 필드를 모아 하나의 머리말로 만든다.
        v1.3까지 이름이 "work"였는데, 코어 스키마의 Work 엔티티(D-099에서 삭제)와
        이름만 같고 다른 것이라 헷갈렸다.
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
    """원본 저장소를 직렬화한다 — L1 파일 목록(참조)·L3·L4·편성 경계·작업 계획·이체자 승인.
    L2(OCR)는 담지 않는다."""
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
                files.append(
                    {
                        "path": f.relative_to(doc_path).as_posix(),
                        "name": f.name,
                        "size_bytes": f.stat().st_size,
                    }
                )
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

    # 편성 경계 — D-097 뒤 글 단위의 정본은 원본 저장소의 경계 목록이다(B-013)
    b_parts = []
    b_dir = doc_path / "boundaries"
    if b_dir.exists():
        for f in sorted(b_dir.glob("*.json")):
            data = _read_json(f)
            if isinstance(data, dict) and data.get("boundaries") is not None:
                b_parts.append(data)
    if b_parts:
        result["layers"]["boundaries"] = {"type": "inline", "parts": b_parts}

    # 작업 계획 — 권마다 read_plan/{part}.json (D-131). 열쇠는 파일 이름(권 id)
    plans = {}
    p_dir = doc_path / "read_plan"
    if p_dir.exists():
        for f in sorted(p_dir.glob("*.json")):
            data = _read_json(f)
            if isinstance(data, dict):
                plans[f.stem] = data
    if plans:
        result["layers"]["read_plan"] = {"type": "inline", "parts": plans}

    # 문헌별 이체자 승인 (D-080 결정 3)
    approvals = _read_json(doc_path / "variant_approvals.json")
    if isinstance(approvals, dict):
        result["layers"]["variant_approvals"] = approvals

    return result


# 물린 폴더 — 스냅샷에 담지 않는다.
#
# 왜: 마이그레이션이 옛 파일을 지우지 않고 이름만 바꿔 남기는데(blocks → 경계 목록 D-092,
# 경계 → 원본 저장소 D-097, Work 삭제 D-099), 그것은 «되돌릴 수 있게» 남긴 흔적이지 지금의
# 엔티티가 아니다. 담으면 스냅샷이 커지고, 가져오기가 남의 서고에 죽은 폴더를 되살린다
# (실측 2026-09-04: 천진담초 스냅샷의 core_entities가 물린 폴더 셋뿐이었다).
RETIRED_ENTITY_DIRS = frozenset(
    {"blocks", "blocks_migrated_v1", "boundaries", "boundaries_migrated_v2", "works_removed_v1"}
)


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
            if type_dir.is_dir() and type_dir.name not in RETIRED_ENTITY_DIRS:
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
    interp_path: Path,
    layer_dir_name: str,
    pattern: str,
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
            data["_source_path"] = json_file.relative_to(interp_path).as_posix()
            results.append(data)

    return results


def _serialize_variant_chars(library_path: Path) -> dict:
    """서고의 활성 이체자 사전을 직렬화한다. 없으면 앱이 들고 온 기본값, 그것도 없으면 빈 dict.

    왜 서고 resources/인가: 사람이 쌓는 사전은 D-104부터 서고에 산다. 예전처럼 서고 루트의
    variant_chars.json을 찾으면 언제나 없어 앱 폴더의 옛 파일이 실렸다(B-013).
    """
    from .alignment import library_active_dict_path

    found = library_active_dict_path(library_path)
    vc_path = Path(found) if found else None
    if vc_path is None:
        project_root = Path(__file__).resolve().parent.parent.parent
        vc_path = project_root / "resources" / "variant_chars.json"

    if vc_path.exists():
        return _read_json(vc_path) or {}
    return {}


def _serialize_annotation_types(library_path: Path) -> list:
    """주석 유형 목록을 직렬화한다 = 앱 기본 프리셋 + 서고의 커스텀.

    서고의 커스텀은 core/annotation_types.py가 쓰는 {서고}/annotation_types.json의 «custom»이다.
    예전에는 annotation_types_custom.json을 찾아 커스텀이 한 번도 실리지 않았다(B-013).
    """
    custom_path = library_path / "annotation_types.json"
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
# Import: 스냅샷에서 문헌 + 해석 저장소 생성
# ──────────────────────────────────────


def create_work_from_snapshot(
    library_path: str | Path,
    data: dict,
) -> dict:
    """스냅샷 데이터로 새 문헌 + 해석 저장소를 만든다.

    (이름의 «work»는 Work 엔티티(D-099에서 없앰)와 무관한 옛 이름이다 — 라우트가 부르므로 유지.)

    목적: /api/.../import/json 엔드포인트에서 호출.
    입력:
        library_path — 서고 경로.
        data — JSON 스냅샷 딕셔너리.
    출력: {doc_id, interp_id, title, warnings} 결과.

    왜 이렇게 하는가:
        새 id(원래 id + 시각)를 발급하여 충돌을 방지한다.
        같은 스냅샷을 여러 번 들여도 각각 독립된 문헌·해석 저장소가 된다.
    """
    library_path = Path(library_path).resolve()
    data = normalize_snapshot(data)
    # 아무것도 만들기 전에 막는다 — 라우트는 validate_snapshot에서 같은 검사로 422를 낸다.
    # 여기서 한 번 더 보는 것은 라우트를 거치지 않는 호출도 서고 밖에 쓰지 못하게 하려는 것이다
    problems = unsafe_snapshot_paths(data)
    if problems:
        raise ValueError("스냅샷의 경로가 안전하지 않아 들이지 않았습니다: " + "; ".join(problems))
    src_info = source_info(data)
    original = data.get("original", {})
    interpretation = data.get("interpretation", {})
    warnings = []

    # 새 ID 생성 (원본 ID에 타임스탬프 접미사). 저장소 id는 64자까지라 원래 id를 잘라 맞춘다
    base_doc_id = (src_info.get("document_id") or "imported")[:_IMPORT_ID_BASE_MAX]
    timestamp_suffix = datetime.now().strftime("%Y%m%d%H%M%S")
    new_doc_id = f"{base_doc_id}_{timestamp_suffix}"

    base_interp_id = (src_info.get("interpretation_id") or "imported_interp")[:_IMPORT_ID_BASE_MAX]
    new_interp_id = f"{base_interp_id}_{timestamp_suffix}"

    doc_path = library_path / "documents" / new_doc_id
    interp_path = library_path / "interpretations" / new_interp_id

    doc_path.mkdir(parents=True, exist_ok=True)
    interp_path.mkdir(parents=True, exist_ok=True)

    # 1. 원본 저장소 복원
    _write_original_layers(doc_path, src_info, original, warnings)

    # 2. 해석 저장소 복원
    _write_interpretation_layers(interp_path, src_info, new_doc_id, interpretation, warnings)

    # 3. 이체자 사전 — 받는 서고의 사용자 사전에 쌍을 합친다(덮어쓰지 않는다, B-013)
    variant_chars = data.get("variant_characters", {})
    if variant_chars:
        _merge_variant_chars(library_path, variant_chars, warnings)

    # 3-1. 주석 유형 — 기본 프리셋에도 받는 서고에도 없는 커스텀만 더한다
    _merge_annotation_types(library_path, data.get("annotation_types") or [])

    # 4. Git 초기 커밋
    _git_init_and_commit(doc_path, "Import: 스냅샷에서 원본 데이터 복원")
    _git_init_and_commit(interp_path, "Import: 스냅샷에서 해석 데이터 복원")

    # 5. library_manifest 업데이트
    _update_library_manifest(library_path, new_doc_id, new_interp_id, src_info)

    return {
        "doc_id": new_doc_id,
        "interp_id": new_interp_id,
        "title": src_info.get("title", ""),
        "warnings": warnings,
    }


def _write_original_layers(
    doc_path: Path,
    src_info: dict,
    original: dict,
    warnings: list,
) -> None:
    """원본 저장소를 파일로 복원한다 — L3·L4·편성 경계·작업 계획·이체자 승인.

    L1은 참조만 담기고 L2는 없다.
    """
    layers = original.get("layers", {})

    # manifest.json
    manifest = {
        "document_id": doc_path.name,
        "title": src_info.get("title", ""),
        "title_ko": src_info.get("title_ko"),
        "parts": src_info.get("parts", []),
        "completeness_status": "imported",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": f"스냅샷에서 Import됨. 원본 ID: {src_info.get('document_id', 'unknown')}",
    }
    _write_json(doc_path / "manifest.json", manifest)

    # bibliography
    bib = src_info.get("bibliography")
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
            warnings.append(f"L1 이미지 파일은 포함되지 않음: {f_info.get('path', '?')}")

    # L3: 레이아웃
    l3 = layers.get("L3_layout", {})
    if l3.get("pages"):
        l3_dir = doc_path / "L3_layout"
        l3_dir.mkdir(exist_ok=True)
        for page_data in l3["pages"]:
            part_id = page_data.get("part_id", "vol1")
            page_num = page_data.get("page_number", 0)
            fname = f"{part_id}_page_{page_num:03d}.json"
            _write_json(_inside(doc_path, l3_dir / fname), page_data)

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
            # newline="" — Path.write_text는 Windows에서 CRLF로 쓴다(B-021)
            with open(_inside(doc_path, pages_dir / fname), "w", encoding="utf-8", newline="") as f:
                f.write(text)

            corr = page_data.get("corrections")
            if corr:
                corr_name = Path(fname).stem + "_corrections.json"
                _write_json(_inside(doc_path, corrections_dir / corr_name), corr)

    # 편성 경계 — 문헌 id는 새 id로 고쳐 적는다(경계 목록 스키마의 document_id)
    for part in (layers.get("boundaries") or {}).get("parts") or []:
        part_id = part.get("part_id")
        if not part_id:
            continue
        b_dir = doc_path / "boundaries"
        b_dir.mkdir(exist_ok=True)
        _write_json(
            _inside(doc_path, b_dir / f"{part_id}.json"), dict(part, document_id=doc_path.name)
        )

    # 작업 계획
    for part_id, plan in ((layers.get("read_plan") or {}).get("parts") or {}).items():
        p_dir = doc_path / "read_plan"
        p_dir.mkdir(exist_ok=True)
        _write_json(_inside(doc_path, p_dir / f"{part_id}.json"), plan)

    # 문헌별 이체자 승인
    if isinstance(layers.get("variant_approvals"), dict):
        _write_json(doc_path / "variant_approvals.json", layers["variant_approvals"])


def _write_interpretation_layers(
    interp_path: Path,
    src_info: dict,
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
        "title": src_info.get("interpretation_title", src_info.get("title", "")),
        "interpreter": src_info.get("interpreter", {"type": "human", "name": "imported"}),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": (
            f"스냅샷에서 Import됨. 원본 해석 ID: {src_info.get('interpretation_id', 'unknown')}"
        ),
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
                target = _inside(interp_path, interp_path / source_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                _write_json(target, item)
            else:
                # _source_path가 없으면 어디에 쓸지 몰라 복원하지 않고 경고로 남긴다
                warnings.append(f"{layer_key}: _source_path 없음, 복원 스킵")

    # 코어 엔티티
    entities = interpretation.get("core_entities", {})
    for entity_type, items in entities.items():
        entity_dir = _inside(interp_path, interp_path / "core_entities" / entity_type)
        entity_dir.mkdir(parents=True, exist_ok=True)
        for item in items:
            entity_id = item.get("id")
            if not entity_id:
                # id 없는 엔티티가 모두 unknown.json 하나로 써져 서로 덮였다(2026-10-11 전수) —
                # 새 UUID를 붙여 저장하고 그렇게 했다고 알린다
                import uuid

                entity_id = str(uuid.uuid4())
                item = {**item, "id": entity_id}
                warnings.append(f"{entity_type}: id 없는 엔티티에 새 id {entity_id}를 붙였습니다")
            _write_json(_inside(interp_path, entity_dir / f"{entity_id}.json"), item)


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
    # 2026-10-11부터 내보내기·들이기 대상(B-013) — «들인 층» 요약에서 빠져 있었다
    if (orig_layers.get("boundaries") or {}).get("parts"):
        layers.append("boundaries")
    if (orig_layers.get("read_plan") or {}).get("parts"):
        layers.append("read_plan")
    if orig_layers.get("variant_approvals"):
        layers.append("variant_approvals")

    interp_layers = data.get("interpretation", {}).get("layers", {})
    if interp_layers.get("L5_punctuation"):
        layers.append("L5_punctuation")
    if interp_layers.get("L5_hyeonto"):
        layers.append("L5_hyeonto")
    if interp_layers.get("L6_translation"):
        layers.append("L6_translation")
    if interp_layers.get("L7_annotation"):
        layers.append("L7_annotation")
    if data.get("interpretation", {}).get("core_entities"):
        layers.append("core_entities")

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
    """JSON을 원자적으로 저장한다. 정본은 core.document.write_json_atomic이다.

    왜 위임하는가: 같은 함수가 다섯 모듈에 복제돼 있었다. 한 곳만 안전하게
    고치면 나머지 넷은 그대로 위험한 채 남는다.
    """
    from .document import write_json_atomic

    write_json_atomic(path, data)


def _merge_variant_chars(library_path: Path, data: dict, warnings: list) -> None:
    """스냅샷의 이체자 사전을 받는 서고의 사용자 사전(resources/variant_chars.json)에 합친다.

    왜 합치는가: 받는 서고에도 사람이 쌓은 사전이 있다. 예전처럼 통째로 쓰면 그것이 사라지고,
    그나마 쓰던 자리(서고 루트)는 아무도 읽지 않는 곳이었다(B-013).
    """
    import tempfile

    from .alignment import VariantCharDict

    target = library_path / "resources" / "variant_chars.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        incoming_path = Path(tmp) / "incoming.json"
        _write_json(incoming_path, data)
        try:
            incoming = VariantCharDict(dict_path=str(incoming_path))
        except Exception as e:  # noqa: BLE001 — 사전이 깨져도 문헌 들이기는 계속한다
            warnings.append(f"이체자 사전을 읽지 못해 합치지 않았습니다: {e}")
            return
    if target.exists():
        mine = VariantCharDict(dict_path=str(target))
    else:
        mine = VariantCharDict.empty(str(target))
    for a, alts in incoming.to_dict().items():
        for b in alts:
            mine.add_pair(a, b)
    mine.save(str(target))


def _merge_annotation_types(library_path: Path, types: list) -> None:
    """스냅샷의 주석 유형 중 기본 프리셋에도 받는 서고에도 없는 것을 서고의 커스텀에 더한다."""
    project_root = Path(__file__).resolve().parent.parent.parent
    defaults = _read_json(project_root / "resources" / "annotation_types.json") or {}
    known = {t.get("id") for t in defaults.get("types", []) if isinstance(t, dict)}
    path = library_path / "annotation_types.json"
    work = _read_json(path) or {"custom": [], "hidden": []}
    custom = work.setdefault("custom", [])
    known |= {t.get("id") for t in custom if isinstance(t, dict)}
    added = [t for t in types if isinstance(t, dict) and t.get("id") and t["id"] not in known]
    if added:
        custom.extend(added)
        _write_json(path, work)


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
        # repo.git.add()는 git 바이너리 호출 — .git/ 내부 추가 방지
        repo.git.add("-A")
        repo.index.commit(message)
    except Exception as e:
        logger.warning("Git 초기화/커밋 실패: %s — %s", repo_path, e)


def _update_library_manifest(
    library_path: Path,
    doc_id: str,
    interp_id: str,
    src_info: dict,
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

    # 문헌 추가 — 같은 id는 바꿔 끼운다(document._update_library_manifest와 같게)
    docs = manifest["documents"] = [
        d for d in manifest.get("documents", []) if d.get("document_id") != doc_id
    ]
    docs.append(
        {
            "document_id": doc_id,
            "title": src_info.get("title", ""),
            "path": f"documents/{doc_id}",
        }
    )

    # 해석 추가
    interps = manifest["interpretations"] = [
        i for i in manifest.get("interpretations", []) if i.get("interpretation_id") != interp_id
    ]
    interps.append(
        {
            "interpretation_id": interp_id,
            "source_document_id": doc_id,
            "title": src_info.get("interpretation_title", src_info.get("title", "")),
            "path": f"interpretations/{interp_id}",
        }
    )

    _write_json(manifest_path, manifest)
