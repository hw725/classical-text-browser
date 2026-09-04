"""서고 파일이 제 스키마를 지키는가 — 「검증 결과」 패널의 알맹이.

무엇을 검사하는가: 문헌 저장소와 (있으면) 해석 저장소의 JSON 파일을 훑어, 파일마다 정해진
스키마로 검증한다. 어긋난 곳을 «파일 · 위치 · 무엇이 틀렸나»로 돌려준다.

왜 필요한가: 스키마는 v1.2까지 «적어 두기만 한 것»이었다. 저장하는 쪽 몇 군데만 검증을
불렀고, 나머지는 아무도 보지 않았다 — 실제로 교환 형식 스키마와 구현이 다른 것을 아무도
몰랐고(D-100), 시험 픽스처가 만들던 데이터가 전부 스키마를 어기고 있었다. 사람이 언제든
「지금 내 서고가 규칙을 지키는가」를 볼 수 있어야 그런 어긋남이 조용히 쌓이지 않는다.

무엇을 검사하지 않는가: 참조 무결성(이 id가 저기 있는가)은 여기서 보지 않는다. 스키마가
말할 수 있는 것만 본다 — 그 경계를 흐리면 «검증»이 무엇인지 모호해진다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 파일 자리 → 스키마. (라벨, 글롭, 스키마 파일)
#
# 글롭은 저장소 뿌리 기준이다. 없는 자리는 그냥 건너뛴다 — 아직 안 만든 층을
# «어긋남»으로 세면 새 문헌이 늘 빨간불이 된다.
DOC_TARGETS: list[tuple[str, str, str]] = [
    ("문헌 manifest", "manifest.json", "source_repo/manifest.schema.json"),
    ("서지정보", "bibliography.json", "source_repo/bibliography.schema.json"),
    ("L2 인식결과", "L2_ocr/*.json", "source_repo/ocr_page.schema.json"),
    ("L3 레이아웃", "L3_layout/*.json", "source_repo/layout_page.schema.json"),
    ("L4 교정기록", "L4_text/corrections/*.json", "source_repo/corrections.schema.json"),
    ("경계 목록", "boundaries/*.json", "core/boundaries.schema.json"),
]

INTERP_TARGETS: list[tuple[str, str, str]] = [
    ("해석 manifest", "manifest.json", "source_repo/interp_manifest.schema.json"),
    ("의존 정보", "dependency.json", "source_repo/dependency.schema.json"),
    ("L5 표점", "L5_reading/**/*_punctuation.json", "interp/punctuation_page.schema.json"),
    ("L5 현토", "L5_reading/**/*_hyeonto.json", "interp/hyeonto_page.schema.json"),
    ("L6 번역", "L6_translation/**/*.json", "interp/translation_page.schema.json"),
    ("L7 주석", "L7_annotation/**/*.json", "interp/annotation_page.schema.json"),
    ("인용 마크", "citation_marks/**/*.json", "interp/citation_mark_page.schema.json"),
    ("Tag", "core_entities/tags/*.json", "core/tag.schema.json"),
    ("Concept", "core_entities/concepts/*.json", "core/concept.schema.json"),
    ("Agent", "core_entities/agents/*.json", "core/agent.schema.json"),
    ("Relation", "core_entities/relations/*.json", "core/relation.schema.json"),
]

# 마이그레이션이 «되돌릴 수 있게» 남긴 자리 — 지금 규칙으로 재면 안 된다(D-092·D-097·D-099)
RETIRED_DIRS = frozenset(
    {"blocks", "blocks_migrated_v1", "boundaries_migrated_v2", "works", "works_removed_v1"}
)

_SCHEMA_CACHE: dict[str, dict] = {}
_MAX_ISSUES = 200  # 화면에 실을 최대 개수. 넘으면 «그 밖 N건»으로 줄인다


def _schemas_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "schemas"


def _schema(rel: str) -> dict | None:
    if rel not in _SCHEMA_CACHE:
        p = _schemas_dir() / rel
        if not p.exists():
            logger.warning("스키마가 없습니다: %s", rel)
            return None
        _SCHEMA_CACHE[rel] = json.loads(p.read_text(encoding="utf-8"))
    return _SCHEMA_CACHE[rel]


def _check(root: Path, targets: list[tuple[str, str, str]], scope: str) -> tuple[int, list[dict]]:
    """한 저장소를 훑는다. (검사한 파일 수, 어긋난 것 목록)."""
    import jsonschema

    checked = 0
    issues: list[dict] = []
    for label, pattern, schema_rel in targets:
        schema = _schema(schema_rel)
        if schema is None:
            continue
        validator = jsonschema.Draft202012Validator(schema)
        for f in sorted(root.glob(pattern)):
            if not f.is_file() or set(f.relative_to(root).parts) & RETIRED_DIRS:
                continue
            checked += 1
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                issues.append(
                    {
                        "scope": scope,
                        "label": label,
                        "file": f.relative_to(root).as_posix(),
                        "where": "(파일)",
                        "message": f"읽지 못했습니다: {e}",
                    }
                )
                continue
            for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
                issues.append(
                    {
                        "scope": scope,
                        "label": label,
                        "file": f.relative_to(root).as_posix(),
                        "where": "/".join(str(p) for p in err.absolute_path) or "(최상위)",
                        "message": err.message,
                    }
                )
    return checked, issues


def validate_repos(doc_path: Path | str, interp_path: Path | str | None = None) -> dict:
    """문헌(과 해석) 저장소의 JSON이 제 스키마를 지키는지 본다.

    입력: 문헌 경로, (선택) 해석 저장소 경로.
    출력: {
        "checked": 검사한 파일 수,
        "issue_count": 어긋난 곳 수,
        "issues": [{scope, label, file, where, message}, …]  # 최대 200건
        "truncated": 잘렸는가,
        "groups": [{"label", "checked", "issues"}]           # 종류별 요약
    }
    """
    checked, issues = _check(Path(doc_path), DOC_TARGETS, "문헌")
    if interp_path:
        p = Path(interp_path)
        if p.exists():
            c2, i2 = _check(p, INTERP_TARGETS, "해석")
            checked += c2
            issues += i2

    groups: dict[str, dict] = {}
    for label, _pattern, _s in DOC_TARGETS + INTERP_TARGETS:
        groups.setdefault(label, {"label": label, "issues": 0})
    for it in issues:
        groups[it["label"]]["issues"] += 1

    total = len(issues)
    return {
        "checked": checked,
        "issue_count": total,
        "issues": issues[:_MAX_ISSUES],
        "truncated": total > _MAX_ISSUES,
        "groups": [g for g in groups.values() if g["issues"]],
    }
