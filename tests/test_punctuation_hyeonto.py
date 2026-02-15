"""L5 표점/현토 코어 로직 단위 테스트.

蒙求 첫 구절(王戎簡要裴楷清通)을 기준으로 검증한다.
"""

import json
import tempfile
from pathlib import Path

import pytest
from jsonschema import validate

from src.core.punctuation import (
    add_mark,
    load_punctuation,
    remove_mark,
    render_punctuated_text,
    save_punctuation,
    split_sentences,
    update_mark,
)
from src.core.hyeonto import (
    add_annotation,
    load_hyeonto,
    remove_annotation,
    render_hyeonto_text,
    save_hyeonto,
    update_annotation,
)


# ──────────────────────────────────────
# 스키마 로드
# ──────────────────────────────────────

_SCHEMA_DIR = Path(__file__).parent.parent / "schemas" / "interp"


@pytest.fixture
def punct_schema():
    with open(_SCHEMA_DIR / "punctuation_page.schema.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def hyeonto_schema():
    with open(_SCHEMA_DIR / "hyeonto_page.schema.json", encoding="utf-8") as f:
        return json.load(f)


# ──────────────────────────────────────
# 표점 스키마 검증 테스트
# ──────────────────────────────────────


class TestPunctuationSchema:
    def test_valid_example(self, punct_schema):
        """세션 문서의 예시 데이터가 스키마를 통과하는지 확인."""
        example = {
            "block_id": "p01_b01",
            "marks": [
                {"id": "pm_001", "target": {"start": 3, "end": 3}, "before": None, "after": "，"},
                {"id": "pm_002", "target": {"start": 7, "end": 7}, "before": None, "after": "。"},
                {"id": "pm_003", "target": {"start": 10, "end": 11}, "before": "《", "after": "》"},
            ],
        }
        validate(instance=example, schema=punct_schema)

    def test_empty_marks(self, punct_schema):
        """빈 marks 배열도 유효."""
        data = {"block_id": "p01_b01", "marks": []}
        validate(instance=data, schema=punct_schema)

    def test_missing_block_id(self, punct_schema):
        """block_id 누락 시 검증 실패."""
        with pytest.raises(Exception):
            validate(instance={"marks": []}, schema=punct_schema)


# ──────────────────────────────────────
# 현토 스키마 검증 테스트
# ──────────────────────────────────────


class TestHyeontoSchema:
    def test_valid_example(self, hyeonto_schema):
        """세션 문서의 예시 데이터가 스키마를 통과하는지 확인."""
        example = {
            "block_id": "p01_b01",
            "annotations": [
                {"id": "ht_001", "target": {"start": 0, "end": 1}, "position": "after", "text": "은", "category": None},
                {"id": "ht_002", "target": {"start": 2, "end": 3}, "position": "after", "text": "하고", "category": None},
            ],
        }
        validate(instance=example, schema=hyeonto_schema)

    def test_empty_annotations(self, hyeonto_schema):
        """빈 annotations 배열도 유효."""
        data = {"block_id": "p01_b01", "annotations": []}
        validate(instance=data, schema=hyeonto_schema)


# ──────────────────────────────────────
# 표점 렌더링 테스트
# ──────────────────────────────────────


class TestRenderPunctuatedText:
    """蒙求 첫 구절 기반 표점 렌더링 테스트."""

    def test_basic_comma_period(self):
        """쉼표 + 마침표 기본 삽입."""
        text = "王戎簡要裴楷清通"
        marks = [
            {"id": "pm_001", "target": {"start": 3, "end": 3}, "before": None, "after": "，"},
            {"id": "pm_002", "target": {"start": 7, "end": 7}, "before": None, "after": "。"},
        ]
        result = render_punctuated_text(text, marks)
        assert result == "王戎簡要，裴楷清通。"

    def test_book_title_brackets(self):
        """서명호 《》 감싸기."""
        text = "讀論語孟子"
        marks = [
            {"id": "pm_001", "target": {"start": 1, "end": 2}, "before": "《", "after": "》"},
            {"id": "pm_002", "target": {"start": 3, "end": 4}, "before": "《", "after": "》"},
        ]
        result = render_punctuated_text(text, marks)
        assert result == "讀《論語》《孟子》"

    def test_empty_text(self):
        """빈 원문."""
        assert render_punctuated_text("", []) == ""

    def test_no_marks(self):
        """표점 없으면 원문 그대로."""
        text = "王戎簡要"
        assert render_punctuated_text(text, []) == text

    def test_out_of_range_mark(self):
        """범위 밖 표점은 무시."""
        text = "ABC"
        marks = [{"id": "pm_001", "target": {"start": 5, "end": 5}, "before": None, "after": "。"}]
        assert render_punctuated_text(text, marks) == "ABC"

    def test_multiple_marks_same_position(self):
        """같은 위치에 여러 표점."""
        text = "ABCD"
        marks = [
            {"id": "pm_001", "target": {"start": 1, "end": 1}, "before": None, "after": "，"},
            {"id": "pm_002", "target": {"start": 1, "end": 1}, "before": None, "after": "。"},
        ]
        result = render_punctuated_text(text, marks)
        # 두 부호 모두 B 뒤에 붙음
        assert result == "AB，。CD"


# ──────────────────────────────────────
# 문장 분리 테스트
# ──────────────────────────────────────


class TestSplitSentences:
    def test_basic_split(self):
        """마침표 기준 문장 분리."""
        text = "王戎簡要裴楷清通"
        marks = [
            {"id": "pm_001", "target": {"start": 3, "end": 3}, "before": None, "after": "，"},
            {"id": "pm_002", "target": {"start": 7, "end": 7}, "before": None, "after": "。"},
        ]
        sentences = split_sentences(text, marks)
        assert len(sentences) == 1  # 。는 index 7 → 문장 하나
        assert sentences[0]["text"] == "王戎簡要裴楷清通"
        assert sentences[0]["start"] == 0
        assert sentences[0]["end"] == 7

    def test_two_sentences(self):
        """두 문장 분리."""
        text = "王戎簡要裴楷清通孔明臥龍呂望非熊"
        marks = [
            {"id": "pm_001", "target": {"start": 7, "end": 7}, "before": None, "after": "。"},
            {"id": "pm_002", "target": {"start": 15, "end": 15}, "before": None, "after": "。"},
        ]
        sentences = split_sentences(text, marks)
        assert len(sentences) == 2
        assert sentences[0]["text"] == "王戎簡要裴楷清通"
        assert sentences[1]["text"] == "孔明臥龍呂望非熊"

    def test_no_marks(self):
        """표점 없으면 전체가 한 문장."""
        text = "王戎簡要"
        sentences = split_sentences(text, [])
        assert len(sentences) == 1
        assert sentences[0]["text"] == text

    def test_empty_text(self):
        """빈 원문."""
        assert split_sentences("", []) == []

    def test_question_mark_as_ender(self):
        """물음표도 문장 종결."""
        text = "何謂仁"
        marks = [{"id": "pm_001", "target": {"start": 2, "end": 2}, "before": None, "after": "？"}]
        sentences = split_sentences(text, marks)
        assert len(sentences) == 1
        assert sentences[0]["end"] == 2


# ──────────────────────────────────────
# 표점 CRUD 테스트
# ──────────────────────────────────────


class TestPunctuationCRUD:
    def test_add_mark(self):
        """표점 추가 — id 자동 생성."""
        data = {"block_id": "p01_b01", "marks": []}
        mark = {"target": {"start": 3, "end": 3}, "before": None, "after": "，"}
        result = add_mark(data, mark)
        assert result["id"].startswith("pm_")
        assert len(data["marks"]) == 1

    def test_remove_mark(self):
        """표점 삭제."""
        data = {
            "block_id": "p01_b01",
            "marks": [
                {"id": "pm_001", "target": {"start": 3, "end": 3}, "before": None, "after": "，"},
            ],
        }
        assert remove_mark(data, "pm_001") is True
        assert len(data["marks"]) == 0

    def test_remove_nonexistent(self):
        """없는 표점 삭제 시도 → False."""
        data = {"block_id": "p01_b01", "marks": []}
        assert remove_mark(data, "pm_999") is False

    def test_update_mark(self):
        """표점 수정."""
        data = {
            "block_id": "p01_b01",
            "marks": [
                {"id": "pm_001", "target": {"start": 3, "end": 3}, "before": None, "after": "，"},
            ],
        }
        result = update_mark(data, "pm_001", {"after": "。"})
        assert result["after"] == "。"

    def test_update_nonexistent(self):
        """없는 표점 수정 → None."""
        data = {"block_id": "p01_b01", "marks": []}
        assert update_mark(data, "pm_999", {"after": "。"}) is None


# ──────────────────────────────────────
# 현토 렌더링 테스트
# ──────────────────────────────────────


class TestRenderHyeontoText:
    """蒙求 첫 구절 기반 현토 렌더링 테스트."""

    def test_basic_hyeonto(self):
        """기본 현토 삽입."""
        text = "王戎簡要裴楷清通"
        annotations = [
            {"id": "ht_001", "target": {"start": 0, "end": 1}, "position": "after", "text": "은"},
            {"id": "ht_002", "target": {"start": 2, "end": 3}, "position": "after", "text": "하고"},
            {"id": "ht_003", "target": {"start": 4, "end": 5}, "position": "after", "text": "ᅵ"},
            {"id": "ht_004", "target": {"start": 6, "end": 7}, "position": "after", "text": "하니"},
        ]
        result = render_hyeonto_text(text, annotations)
        assert result == "王戎은簡要하고裴楷ᅵ清通하니"

    def test_empty_text(self):
        assert render_hyeonto_text("", []) == ""

    def test_no_annotations(self):
        text = "王戎簡要"
        assert render_hyeonto_text(text, []) == text

    def test_single_char_annotation(self):
        """단일 글자에 토."""
        text = "人"
        annotations = [
            {"id": "ht_001", "target": {"start": 0, "end": 0}, "position": "after", "text": "이"},
        ]
        assert render_hyeonto_text(text, annotations) == "人이"

    def test_before_position(self):
        """before 위치 현토."""
        text = "ABC"
        annotations = [
            {"id": "ht_001", "target": {"start": 1, "end": 1}, "position": "before", "text": "~"},
        ]
        assert render_hyeonto_text(text, annotations) == "A~BC"


# ──────────────────────────────────────
# 현토 CRUD 테스트
# ──────────────────────────────────────


class TestHyeontoCRUD:
    def test_add_annotation(self):
        """현토 추가 — id 자동 생성."""
        data = {"block_id": "p01_b01", "annotations": []}
        ann = {"target": {"start": 0, "end": 1}, "position": "after", "text": "은"}
        result = add_annotation(data, ann)
        assert result["id"].startswith("ht_")
        assert result["category"] is None
        assert len(data["annotations"]) == 1

    def test_remove_annotation(self):
        """현토 삭제."""
        data = {
            "block_id": "p01_b01",
            "annotations": [
                {"id": "ht_001", "target": {"start": 0, "end": 1}, "position": "after", "text": "은", "category": None},
            ],
        }
        assert remove_annotation(data, "ht_001") is True
        assert len(data["annotations"]) == 0

    def test_update_annotation(self):
        """현토 수정."""
        data = {
            "block_id": "p01_b01",
            "annotations": [
                {"id": "ht_001", "target": {"start": 0, "end": 1}, "position": "after", "text": "은", "category": None},
            ],
        }
        result = update_annotation(data, "ht_001", {"text": "이"})
        assert result["text"] == "이"


# ──────────────────────────────────────
# 파일 I/O 테스트
# ──────────────────────────────────────


class TestFileIO:
    def test_save_and_load_punctuation(self, tmp_path):
        """표점 저장 후 로드 라운드트립."""
        interp_path = tmp_path / "test_interp"
        interp_path.mkdir()

        data = {
            "block_id": "p01_b01",
            "marks": [
                {"id": "pm_001", "target": {"start": 3, "end": 3}, "before": None, "after": "，"},
            ],
        }

        save_punctuation(interp_path, "main", 1, data)
        loaded = load_punctuation(interp_path, "main", 1, "p01_b01")

        assert loaded["block_id"] == "p01_b01"
        assert len(loaded["marks"]) == 1
        assert loaded["marks"][0]["after"] == "，"

    def test_load_nonexistent_punctuation(self, tmp_path):
        """존재하지 않는 파일 로드 시 빈 marks 반환."""
        interp_path = tmp_path / "empty_interp"
        interp_path.mkdir()

        loaded = load_punctuation(interp_path, "main", 1, "p01_b01")
        assert loaded["block_id"] == "p01_b01"
        assert loaded["marks"] == []

    def test_save_and_load_hyeonto(self, tmp_path):
        """현토 저장 후 로드 라운드트립."""
        interp_path = tmp_path / "test_interp"
        interp_path.mkdir()

        data = {
            "block_id": "p01_b01",
            "annotations": [
                {"id": "ht_001", "target": {"start": 0, "end": 1}, "position": "after", "text": "은", "category": None},
            ],
        }

        save_hyeonto(interp_path, "main", 1, data)
        loaded = load_hyeonto(interp_path, "main", 1, "p01_b01")

        assert loaded["block_id"] == "p01_b01"
        assert len(loaded["annotations"]) == 1
        assert loaded["annotations"][0]["text"] == "은"

    def test_schema_validation_on_save(self, tmp_path):
        """잘못된 데이터 저장 시 스키마 검증 실패."""
        interp_path = tmp_path / "test_interp"
        interp_path.mkdir()

        # marks가 아니라 annotations → 스키마 불일치
        bad_data = {"block_id": "p01_b01", "annotations": []}
        with pytest.raises(Exception):
            save_punctuation(interp_path, "main", 1, bad_data)


# ──────────────────────────────────────
# LLM Draft 정규화 테스트
# ──────────────────────────────────────


class TestLlmNormalize:
    def test_normalize_marks(self):
        """LLM 응답 marks 정규화."""
        from src.core.punctuation_llm import _normalize_marks

        raw = [
            {"start": 3, "end": 3, "before": None, "after": "，"},
            {"start": 7, "end": 7, "after": "。"},  # before 누락
        ]
        result = _normalize_marks(raw)
        assert len(result) == 2
        assert result[0]["id"].startswith("pm_")
        assert result[0]["target"]["start"] == 3
        assert result[1]["before"] is None  # 누락 시 None 보정
        assert result[1]["after"] == "。"

    def test_parse_llm_json(self):
        """LLM 응답 JSON 파싱 (코드블록 포함)."""
        from src.core.punctuation_llm import _parse_llm_json

        raw = '```json\n{"marks": [{"start": 3, "end": 3, "after": "。"}]}\n```'
        result = _parse_llm_json(raw)
        assert "marks" in result
        assert len(result["marks"]) == 1

    def test_parse_plain_json(self):
        """일반 JSON 파싱."""
        from src.core.punctuation_llm import _parse_llm_json

        raw = '{"marks": []}'
        result = _parse_llm_json(raw)
        assert result == {"marks": []}
