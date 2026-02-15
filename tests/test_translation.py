"""L6 번역 통합 테스트 — Phase 11-2.

테스트 범위:
    - translation_page.schema.json 검증
    - 번역 CRUD (add/update/remove)
    - 상태 요약 (get_translation_status)
    - 파일 I/O (save/load 라운드트립)
    - LLM Draft 커밋
    - _filter_annotations_for_range, _shift_annotations 유틸리티
"""

import json
import tempfile
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

from src.core.translation import (
    _gen_translation_id,
    add_translation,
    get_translation_status,
    load_translations,
    remove_translation,
    save_translations,
    update_translation,
)
from src.core.translation_llm import (
    _filter_annotations_for_range,
    _shift_annotations,
    commit_translation_draft,
)

# ──────────────────────────
# 스키마 로드
# ──────────────────────────

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "interp" / "translation_page.schema.json"


@pytest.fixture
def schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def sample_translation():
    """蒙求 첫 구절 번역 예시."""
    return {
        "part_id": "main",
        "page_number": 1,
        "translations": [
            {
                "id": "tr_001",
                "source": {"block_id": "p01_b01", "start": 0, "end": 7},
                "source_text": "王戎簡要裴楷清通",
                "hyeonto_text": "王戎은簡要하고裴楷ᅵ清通하니",
                "target_language": "ko",
                "translation": "왕융은 간결하고 배해는 맑고 통달하였다.",
                "translator": {
                    "type": "llm",
                    "model": "qwen3-vl:235b-cloud",
                    "draft_id": "draft_001",
                },
                "status": "draft",
                "reviewed_by": None,
                "reviewed_at": None,
            }
        ],
    }


# ──────────────────────────
# 스키마 검증 테스트
# ──────────────────────────


class TestTranslationSchema:
    """translation_page.schema.json 검증."""

    def test_valid_example(self, schema, sample_translation):
        """유효한 예시 데이터로 검증 통과."""
        validate(instance=sample_translation, schema=schema)

    def test_empty_translations(self, schema):
        """빈 translations 배열은 유효."""
        data = {"part_id": "main", "page_number": 1, "translations": []}
        validate(instance=data, schema=schema)

    def test_missing_part_id(self, schema):
        """part_id 누락 시 검증 실패."""
        data = {"page_number": 1, "translations": []}
        with pytest.raises(ValidationError):
            validate(instance=data, schema=schema)

    def test_human_translator(self, schema):
        """수동 번역 (translator.type = human)."""
        data = {
            "part_id": "main",
            "page_number": 1,
            "translations": [
                {
                    "id": "tr_002",
                    "source": {"block_id": "p01_b01", "start": 0, "end": 3},
                    "source_text": "王戎簡要",
                    "hyeonto_text": None,
                    "target_language": "ko",
                    "translation": "왕융은 간결하다.",
                    "translator": {"type": "human", "model": None, "draft_id": None},
                    "status": "accepted",
                    "reviewed_by": None,
                    "reviewed_at": None,
                }
            ],
        }
        validate(instance=data, schema=schema)


# ──────────────────────────
# CRUD 테스트
# ──────────────────────────


class TestTranslationCRUD:
    """번역 CRUD 연산."""

    def test_add_translation(self):
        """번역 추가 시 id 자동 생성."""
        data = {"part_id": "main", "page_number": 1, "translations": []}
        entry = {
            "source": {"block_id": "p01_b01", "start": 0, "end": 7},
            "source_text": "王戎簡要裴楷清通",
            "translation": "왕융은 간결하고 배해는 맑고 통달하였다.",
        }
        result = add_translation(data, entry)
        assert result["id"].startswith("tr_")
        assert len(data["translations"]) == 1
        assert result["status"] == "draft"
        assert result["translator"]["type"] == "human"

    def test_update_translation(self, sample_translation):
        """번역 수정."""
        result = update_translation(
            sample_translation, "tr_001", {"translation": "수정된 번역", "status": "accepted"}
        )
        assert result is not None
        assert result["translation"] == "수정된 번역"
        assert result["status"] == "accepted"

    def test_update_nonexistent(self, sample_translation):
        """존재하지 않는 ID 수정 시 None."""
        result = update_translation(sample_translation, "tr_999", {"translation": "x"})
        assert result is None

    def test_remove_translation(self, sample_translation):
        """번역 삭제."""
        assert remove_translation(sample_translation, "tr_001") is True
        assert len(sample_translation["translations"]) == 0

    def test_remove_nonexistent(self, sample_translation):
        """존재하지 않는 ID 삭제 시 False."""
        assert remove_translation(sample_translation, "tr_999") is False


# ──────────────────────────
# 상태 요약 테스트
# ──────────────────────────


class TestTranslationStatus:
    """번역 상태 요약."""

    def test_status_single_draft(self, sample_translation):
        status = get_translation_status(sample_translation)
        assert status["total"] == 1
        assert status["draft"] == 1
        assert status["accepted"] == 0

    def test_status_mixed(self):
        data = {
            "translations": [
                {"status": "draft"},
                {"status": "accepted"},
                {"status": "accepted"},
                {"status": "draft"},
            ]
        }
        status = get_translation_status(data)
        assert status["total"] == 4
        assert status["draft"] == 2
        assert status["accepted"] == 2


# ──────────────────────────
# 파일 I/O 테스트
# ──────────────────────────


class TestFileIO:
    """save/load 라운드트립."""

    def test_save_and_load(self, sample_translation):
        with tempfile.TemporaryDirectory() as tmpdir:
            interp_path = Path(tmpdir)
            save_translations(interp_path, "main", 1, sample_translation)
            loaded = load_translations(interp_path, "main", 1)

            assert loaded["part_id"] == "main"
            assert loaded["page_number"] == 1
            assert len(loaded["translations"]) == 1
            assert loaded["translations"][0]["id"] == "tr_001"

    def test_load_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data = load_translations(Path(tmpdir), "main", 99)
            assert data["translations"] == []

    def test_schema_validation_on_save(self):
        """스키마 불일치 시 저장 실패."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_data = {"part_id": "main", "page_number": 1}
            with pytest.raises(ValidationError):
                save_translations(Path(tmpdir), "main", 1, bad_data)


# ──────────────────────────
# Draft 커밋 테스트
# ──────────────────────────


class TestDraftCommit:
    """Draft 확정 로직."""

    def test_commit_updates_status(self, sample_translation):
        result = commit_translation_draft(sample_translation, "tr_001")
        assert result is not None
        assert result["status"] == "accepted"
        assert result["reviewed_at"] is not None

    def test_commit_with_modifications(self, sample_translation):
        result = commit_translation_draft(
            sample_translation, "tr_001", {"translation": "수정된 번역"}
        )
        assert result["translation"] == "수정된 번역"
        assert result["status"] == "accepted"

    def test_commit_nonexistent(self, sample_translation):
        result = commit_translation_draft(sample_translation, "tr_999")
        assert result is None


# ──────────────────────────
# 유틸리티 테스트
# ──────────────────────────


class TestLlmUtils:
    """LLM 관련 유틸리티."""

    def test_filter_annotations_for_range(self):
        """문장 범위에 해당하는 현토 필터링."""
        anns = [
            {"target": {"start": 0, "end": 0}, "text": "은", "position": "after"},
            {"target": {"start": 3, "end": 3}, "text": "하고", "position": "after"},
            {"target": {"start": 7, "end": 7}, "text": "하니", "position": "after"},
        ]
        # 범위 0~3 (첫 번째 문장)
        result = _filter_annotations_for_range(anns, 0, 3)
        assert len(result) == 2  # 0과 3

    def test_filter_annotations_empty(self):
        result = _filter_annotations_for_range([], 0, 7)
        assert result == []

    def test_shift_annotations(self):
        """현토 인덱스 이동."""
        anns = [
            {"target": {"start": 4, "end": 4}, "text": "ᅵ", "position": "after"},
            {"target": {"start": 7, "end": 7}, "text": "하니", "position": "after"},
        ]
        shifted = _shift_annotations(anns, 4)
        assert shifted[0]["target"]["start"] == 0
        assert shifted[0]["target"]["end"] == 0
        assert shifted[1]["target"]["start"] == 3

    def test_gen_translation_id(self):
        """ID 형식 확인."""
        tid = _gen_translation_id()
        assert tid.startswith("tr_")
        assert len(tid) == 9  # "tr_" + 6 hex chars
