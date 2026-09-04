"""서고 파일이 제 스키마를 지키는가 — 「검증 결과」 패널의 알맹이 (D-101).

무엇을 고정하는가:
  - 규칙을 지키는 서고는 어긋남 0
  - 한 곳을 어기면 그 파일·위치·까닭을 짚는다
  - 마이그레이션이 남긴 «물린» 폴더는 지금 규칙으로 재지 않는다
  - 아직 만들지 않은 층은 어긋남이 아니다(새 문헌이 늘 빨간불이면 안 된다)
"""

from __future__ import annotations

import json
from pathlib import Path

from src.core.validation import validate_repos


def _doc(root: Path) -> Path:
    doc = root / "documents" / "d"
    (doc / "L3_layout").mkdir(parents=True)
    (doc / "boundaries").mkdir(parents=True)
    (doc / "manifest.json").write_text(
        json.dumps(
            {
                "document_id": "d",
                "title": "蒙求",
                "created_at": "2026-01-01T00:00:00+00:00",
                "completeness_status": "file_only",
                "parts": [
                    {"part_id": "vol1", "label": "卷上", "file": "vol1.pdf", "page_count": 1}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (doc / "L3_layout" / "vol1_page_001.json").write_text(
        json.dumps(
            {
                "part_id": "vol1",
                "page_number": 1,
                "blocks": [
                    {
                        "block_id": "p01_b01",
                        "block_type": "main_text",
                        "reading_order": 1,
                        "bbox": [0, 0, 10, 10],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (doc / "boundaries" / "vol1.json").write_text(
        json.dumps(
            {
                "document_id": "d",
                "part_id": "vol1",
                "boundaries": [
                    {
                        "id": "b1",
                        "level": 2,
                        "start": {"page": 1, "line": 0, "offset": 0},
                        "status": "draft",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return doc


def test_clean_repo_has_no_issues(tmp_path):
    doc = _doc(tmp_path)
    result = validate_repos(doc)
    assert result["issue_count"] == 0, result["issues"]
    assert result["checked"] == 3  # manifest + L3 한 쪽 + 경계 목록
    assert result["groups"] == []


def test_a_broken_file_is_pinpointed(tmp_path):
    doc = _doc(tmp_path)
    f = doc / "L3_layout" / "vol1_page_001.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    data["blocks"][0]["block_id"] = "틀린id"  # ^p\d+_b\d+$ 를 어긴다
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    result = validate_repos(doc)

    assert result["issue_count"] == 1
    issue = result["issues"][0]
    assert issue["file"] == "L3_layout/vol1_page_001.json"
    assert issue["label"] == "L3 레이아웃"
    assert "blocks/0/block_id" in issue["where"]
    assert result["groups"] == [{"label": "L3 레이아웃", "issues": 1}]


def test_retired_folders_are_not_measured(tmp_path):
    """마이그레이션이 «되돌릴 수 있게» 남긴 자리는 지금 규칙으로 재지 않는다.

    왜: blocks_migrated_v1/·boundaries_migrated_v2/·works_removed_v1/은 옛 형식 그대로다
    (D-092·D-097·D-099). 재면 옛 서고가 영원히 빨간불이 된다.
    """
    doc = _doc(tmp_path)
    old = doc / "boundaries" / "boundaries_migrated_v2"
    old.mkdir()
    (old / "d__vol1.json").write_text(json.dumps({"엉망": True}), encoding="utf-8")

    assert validate_repos(doc)["issue_count"] == 0


def test_missing_layers_are_not_issues(tmp_path):
    """아직 만들지 않은 층은 어긋남이 아니다 — 새 문헌이 늘 빨간불이면 안 된다."""
    root = tmp_path / "lib"
    doc = root / "documents" / "d"
    doc.mkdir(parents=True)
    (doc / "manifest.json").write_text(
        json.dumps(
            {
                "document_id": "d",
                "title": "새 문헌",
                "created_at": "2026-01-01T00:00:00+00:00",
                "completeness_status": "file_only",
                "parts": [
                    {"part_id": "vol1", "label": "卷上", "file": "vol1.pdf", "page_count": 1}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = validate_repos(doc)

    assert result == {
        "checked": 1,
        "issue_count": 0,
        "issues": [],
        "truncated": False,
        "groups": [],
    }
