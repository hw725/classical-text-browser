"""L7 주석(Annotation) 통합 테스트.

Phase 11-3: 스키마 검증, CRUD, 필터링, 요약, Draft 확정, 유형 관리.
"""

import json
import tempfile
import uuid
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

# ──────────────────────────────────────
# 스키마 테스트
# ──────────────────────────────────────

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "interp" / "annotation_page.schema.json"


@pytest.fixture
def schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


class TestAnnotationSchema:
    """스키마 검증 테스트."""

    def test_valid_example(self, schema):
        """蒙求 첫 구절 주석 예시가 스키마를 통과해야 한다."""
        data = {
            "part_id": "main",
            "page_number": 1,
            "blocks": [
                {
                    "block_id": "p01_b01",
                    "annotations": [
                        {
                            "id": "ann_001",
                            "target": {"start": 0, "end": 1},
                            "type": "person",
                            "content": {
                                "label": "왕융(王戎)",
                                "description": "서진의 죽림칠현 중 한 명. 자는 준충(濬沖).",
                                "references": ["진서(晉書) 왕융전"],
                            },
                            "annotator": {"type": "llm", "model": "claude", "draft_id": "d_001"},
                            "status": "draft",
                            "reviewed_by": None,
                            "reviewed_at": None,
                        }
                    ],
                }
            ],
        }
        validate(instance=data, schema=schema)

    def test_empty_blocks(self, schema):
        """빈 blocks도 유효해야 한다."""
        data = {"part_id": "main", "page_number": 1, "blocks": []}
        validate(instance=data, schema=schema)

    def test_missing_part_id(self, schema):
        """part_id 누락 시 ValidationError."""
        data = {"page_number": 1, "blocks": []}
        with pytest.raises(ValidationError):
            validate(instance=data, schema=schema)

    def test_human_annotator(self, schema):
        """사람 작성 주석도 유효해야 한다."""
        data = {
            "part_id": "vol1",
            "page_number": 3,
            "blocks": [
                {
                    "block_id": "p03_b01",
                    "annotations": [
                        {
                            "id": "ann_002",
                            "target": {"start": 4, "end": 5},
                            "type": "term",
                            "content": {
                                "label": "간요(簡要)",
                                "description": "간결하고 핵심적임.",
                            },
                            "annotator": {"type": "human", "model": None, "draft_id": None},
                            "status": "accepted",
                            "reviewed_by": "연구자A",
                            "reviewed_at": "2026-02-16T12:00:00",
                        }
                    ],
                }
            ],
        }
        validate(instance=data, schema=schema)

    def test_multiple_blocks(self, schema):
        """여러 블록의 주석이 유효해야 한다."""
        data = {
            "part_id": "main",
            "page_number": 1,
            "blocks": [
                {"block_id": "p01_b01", "annotations": []},
                {"block_id": "p01_b02", "annotations": []},
            ],
        }
        validate(instance=data, schema=schema)


# ──────────────────────────────────────
# CRUD 테스트
# ──────────────────────────────────────

from src.core.annotation import (
    add_annotation,
    get_annotation_summary,
    get_annotations_by_type,
    remove_annotation,
    update_annotation,
)


def _empty_data():
    return {"part_id": "main", "page_number": 1, "blocks": []}


class TestAnnotationCRUD:
    """주석 추가/수정/삭제 테스트."""

    def test_add_annotation(self):
        data = _empty_data()
        ann = add_annotation(data, "p01_b01", {
            "target": {"start": 0, "end": 1},
            "type": "person",
            "content": {"label": "왕융(王戎)", "description": "죽림칠현"},
        })
        assert ann["id"].startswith("ann_")
        assert ann["status"] == "draft"
        assert len(data["blocks"]) == 1
        assert len(data["blocks"][0]["annotations"]) == 1

    def test_add_to_existing_block(self):
        data = _empty_data()
        add_annotation(data, "p01_b01", {
            "target": {"start": 0, "end": 1},
            "type": "person",
            "content": {"label": "A", "description": ""},
        })
        add_annotation(data, "p01_b01", {
            "target": {"start": 2, "end": 3},
            "type": "person",
            "content": {"label": "B", "description": ""},
        })
        # 같은 블록에 2개
        assert len(data["blocks"]) == 1
        assert len(data["blocks"][0]["annotations"]) == 2

    def test_add_to_different_blocks(self):
        data = _empty_data()
        add_annotation(data, "p01_b01", {
            "target": {"start": 0, "end": 1},
            "type": "person",
            "content": {"label": "A", "description": ""},
        })
        add_annotation(data, "p01_b02", {
            "target": {"start": 0, "end": 1},
            "type": "place",
            "content": {"label": "B", "description": ""},
        })
        assert len(data["blocks"]) == 2

    def test_update_annotation(self):
        data = _empty_data()
        ann = add_annotation(data, "p01_b01", {
            "target": {"start": 0, "end": 1},
            "type": "person",
            "content": {"label": "원본", "description": ""},
        })
        result = update_annotation(data, "p01_b01", ann["id"], {
            "content": {"label": "수정됨", "description": "새 설명"},
        })
        assert result is not None
        assert result["content"]["label"] == "수정됨"

    def test_update_nonexistent(self):
        data = _empty_data()
        result = update_annotation(data, "p01_b01", "ann_nonexist", {"type": "place"})
        assert result is None

    def test_remove_annotation(self):
        data = _empty_data()
        ann = add_annotation(data, "p01_b01", {
            "target": {"start": 0, "end": 1},
            "type": "person",
            "content": {"label": "삭제대상", "description": ""},
        })
        assert remove_annotation(data, "p01_b01", ann["id"]) is True
        assert len(data["blocks"][0]["annotations"]) == 0

    def test_remove_nonexistent(self):
        data = _empty_data()
        assert remove_annotation(data, "p01_b01", "ann_xxx") is False


# ──────────────────────────────────────
# 필터링 + 요약 테스트
# ──────────────────────────────────────


class TestAnnotationFilter:
    """유형별 필터링 테스트."""

    def test_get_by_type(self):
        data = _empty_data()
        add_annotation(data, "p01_b01", {
            "target": {"start": 0, "end": 1}, "type": "person",
            "content": {"label": "A", "description": ""},
        })
        add_annotation(data, "p01_b01", {
            "target": {"start": 2, "end": 3}, "type": "place",
            "content": {"label": "B", "description": ""},
        })
        add_annotation(data, "p01_b02", {
            "target": {"start": 0, "end": 1}, "type": "person",
            "content": {"label": "C", "description": ""},
        })

        persons = get_annotations_by_type(data, "person")
        assert len(persons) == 2

        places = get_annotations_by_type(data, "place")
        assert len(places) == 1

        terms = get_annotations_by_type(data, "term")
        assert len(terms) == 0


class TestAnnotationSummary:
    """상태 요약 테스트."""

    def test_mixed_summary(self):
        data = _empty_data()
        ann1 = add_annotation(data, "p01_b01", {
            "target": {"start": 0, "end": 1}, "type": "person",
            "content": {"label": "A", "description": ""},
            "status": "draft",
        })
        ann2 = add_annotation(data, "p01_b01", {
            "target": {"start": 2, "end": 3}, "type": "place",
            "content": {"label": "B", "description": ""},
            "status": "accepted",
        })
        ann3 = add_annotation(data, "p01_b02", {
            "target": {"start": 0, "end": 1}, "type": "term",
            "content": {"label": "C", "description": ""},
            "status": "accepted",
        })

        summary = get_annotation_summary(data)
        assert summary["total"] == 3
        assert summary["by_type"]["person"] == 1
        assert summary["by_type"]["place"] == 1
        assert summary["by_type"]["term"] == 1
        assert summary["by_status"]["draft"] == 1
        assert summary["by_status"]["accepted"] == 2


# ──────────────────────────────────────
# 파일 I/O 테스트
# ──────────────────────────────────────

from src.core.annotation import load_annotations, save_annotations


class TestAnnotationFileIO:
    """저장/로드 라운드트립 테스트."""

    def test_save_and_load(self, tmp_path):
        interp_path = tmp_path / "test_interp"
        interp_path.mkdir()

        data = {
            "part_id": "main",
            "page_number": 1,
            "blocks": [
                {
                    "block_id": "p01_b01",
                    "annotations": [
                        {
                            "id": "ann_001",
                            "target": {"start": 0, "end": 1},
                            "type": "person",
                            "content": {"label": "왕융(王戎)", "description": "설명", "references": []},
                            "annotator": {"type": "human", "model": None, "draft_id": None},
                            "status": "accepted",
                            "reviewed_by": None,
                            "reviewed_at": None,
                        }
                    ],
                }
            ],
        }

        save_annotations(interp_path, "main", 1, data)
        loaded = load_annotations(interp_path, "main", 1)

        assert loaded["part_id"] == "main"
        assert len(loaded["blocks"]) == 1
        assert loaded["blocks"][0]["annotations"][0]["id"] == "ann_001"

    def test_load_nonexistent(self, tmp_path):
        interp_path = tmp_path / "empty_interp"
        interp_path.mkdir()

        data = load_annotations(interp_path, "main", 1)
        assert data["blocks"] == []

    def test_schema_validation_on_save(self, tmp_path):
        interp_path = tmp_path / "bad_interp"
        interp_path.mkdir()

        bad_data = {"page_number": 1, "blocks": []}  # part_id 누락
        with pytest.raises(ValidationError):
            save_annotations(interp_path, "main", 1, bad_data)


# ──────────────────────────────────────
# Draft 확정 테스트
# ──────────────────────────────────────

from src.core.annotation_llm import commit_all_drafts, commit_annotation_draft


class TestDraftCommit:
    """Draft 확정 테스트."""

    def test_commit_single(self):
        data = _empty_data()
        ann = add_annotation(data, "p01_b01", {
            "target": {"start": 0, "end": 1}, "type": "person",
            "content": {"label": "A", "description": "설명"},
            "status": "draft",
        })

        result = commit_annotation_draft(data, "p01_b01", ann["id"])
        assert result is not None
        assert result["status"] == "accepted"
        assert result["reviewed_at"] is not None

    def test_commit_with_modifications(self):
        data = _empty_data()
        ann = add_annotation(data, "p01_b01", {
            "target": {"start": 0, "end": 1}, "type": "person",
            "content": {"label": "원본", "description": ""},
            "status": "draft",
        })

        result = commit_annotation_draft(data, "p01_b01", ann["id"], {
            "content": {"label": "수정됨", "description": "새 설명", "references": []},
        })
        assert result["status"] == "accepted"
        assert result["content"]["label"] == "수정됨"

    def test_commit_nonexistent(self):
        data = _empty_data()
        result = commit_annotation_draft(data, "p01_b01", "ann_xxx")
        assert result is None

    def test_commit_all(self):
        data = _empty_data()
        add_annotation(data, "p01_b01", {
            "target": {"start": 0, "end": 1}, "type": "person",
            "content": {"label": "A", "description": ""},
            "status": "draft",
        })
        add_annotation(data, "p01_b01", {
            "target": {"start": 2, "end": 3}, "type": "place",
            "content": {"label": "B", "description": ""},
            "status": "draft",
        })
        add_annotation(data, "p01_b02", {
            "target": {"start": 0, "end": 1}, "type": "term",
            "content": {"label": "C", "description": ""},
            "status": "accepted",  # 이미 확정
        })

        count = commit_all_drafts(data)
        assert count == 2  # draft 2개만 확정

        summary = get_annotation_summary(data)
        assert summary["by_status"]["accepted"] == 3
        assert summary["by_status"]["draft"] == 0


# ──────────────────────────────────────
# 주석 유형 관리 테스트
# ──────────────────────────────────────

from src.core.annotation_types import (
    add_custom_type,
    load_annotation_types,
    remove_custom_type,
    validate_type,
)


class TestAnnotationTypes:
    """주석 유형 관리 테스트."""

    def test_load_default_types(self):
        types = load_annotation_types()
        assert len(types["types"]) == 5
        ids = [t["id"] for t in types["types"]]
        assert "person" in ids
        assert "place" in ids
        assert "term" in ids
        assert "allusion" in ids
        assert "note" in ids

    def test_validate_default_type(self):
        assert validate_type(None, "person") is True
        assert validate_type(None, "nonexistent") is False

    def test_add_custom_type(self, tmp_path):
        work_path = tmp_path / "work"
        work_path.mkdir()

        result = add_custom_type(work_path, {
            "id": "sutra_ref",
            "label": "경전 참조",
            "color": "#FF6600",
            "icon": "🙏",
        })
        assert result["id"] == "sutra_ref"

        types = load_annotation_types(work_path)
        assert any(t["id"] == "sutra_ref" for t in types["all"])

    def test_add_duplicate_type(self, tmp_path):
        work_path = tmp_path / "work2"
        work_path.mkdir()

        # person은 기본 프리셋에 있으므로 중복
        with pytest.raises(ValueError, match="이미 존재"):
            add_custom_type(work_path, {
                "id": "person",
                "label": "중복",
                "color": "#000",
            })

    def test_remove_custom_type(self, tmp_path):
        work_path = tmp_path / "work3"
        work_path.mkdir()

        add_custom_type(work_path, {
            "id": "custom1",
            "label": "커스텀",
            "color": "#111",
        })
        assert remove_custom_type(work_path, "custom1") is True

        types = load_annotation_types(work_path)
        assert not any(t["id"] == "custom1" for t in types["all"])

    def test_remove_nonexistent(self, tmp_path):
        work_path = tmp_path / "work4"
        work_path.mkdir()
        assert remove_custom_type(work_path, "nonexistent") is False


# ──────────────────────────────────────
# LLM 파서 테스트
# ──────────────────────────────────────

from src.core.annotation_llm import _parse_llm_annotations


class TestLlmParser:
    """LLM 응답 파서 테스트."""

    def test_parse_clean_json(self):
        text = '{"annotations": [{"target": {"start": 0, "end": 1}, "type": "person", "content": {"label": "A", "description": "B"}}]}'
        result = _parse_llm_annotations(text)
        assert len(result) == 1
        assert result[0]["type"] == "person"

    def test_parse_with_markdown_block(self):
        text = '설명 텍스트\n```json\n{"annotations": [{"target": {"start": 0, "end": 1}, "type": "place", "content": {"label": "C", "description": "D"}}]}\n```\n끝'
        result = _parse_llm_annotations(text)
        assert len(result) == 1
        assert result[0]["type"] == "place"

    def test_parse_empty(self):
        result = _parse_llm_annotations("이 텍스트에는 주석할 것이 없습니다.")
        assert result == []

    def test_parse_bare_list(self):
        text = '[{"target": {"start": 0, "end": 1}, "type": "term", "content": {"label": "E", "description": "F"}}]'
        result = _parse_llm_annotations(text)
        assert len(result) == 1
