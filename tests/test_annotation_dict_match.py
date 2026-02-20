"""annotation_dict_match.py 참조 사전 매칭 테스트.

테스트 항목:
1. 참조 사전 등록/목록/로드/삭제
2. match_text — 단순 부분 문자열 매칭
3. match_text — 중복 매칭 방지, 복수 사전
4. match_page_blocks — 블록별 매칭
5. format_for_translation_context — 번역 프롬프트 생성
6. 통합: export → register → match 워크플로우
"""

import json
import tempfile
from pathlib import Path

from core.annotation import save_annotations
from core.annotation_dict_io import export_dictionary
from core.annotation_dict_match import (
    list_reference_dicts,
    register_reference_dict,
    load_reference_dict,
    remove_reference_dict,
    match_text,
    match_page_blocks,
    format_for_translation_context,
    _build_headword_index,
)


def _sample_dict(doc_id="monggu", doc_title="蒙求"):
    """테스트용 사전 데이터."""
    return {
        "schema_version": "1.0",
        "export_type": "dictionary",
        "export_timestamp": "2026-02-20T10:00:00Z",
        "source": {
            "document_id": doc_id,
            "document_title": doc_title,
            "interpretation_id": f"{doc_id}_interp",
        },
        "entries": [
            {
                "headword": "王戎",
                "headword_reading": "왕융",
                "type": "person",
                "dictionary_meaning": "竹林七賢의 한 사람. 晉代 정치가. 자(字)는 濬沖.",
                "contextual_meaning": "간결한 학문의 모범",
                "source_references": [{"title": "晉書", "section": "列傳 第十三"}],
                "related_terms": ["竹林七賢", "嵇康"],
            },
            {
                "headword": "裴楷",
                "headword_reading": "배해",
                "type": "person",
                "dictionary_meaning": "晉代 명사. 맑고 통달함으로 유명.",
                "contextual_meaning": None,
                "source_references": [{"title": "晉書"}],
                "related_terms": [],
            },
            {
                "headword": "簡要",
                "headword_reading": "간요",
                "type": "term",
                "dictionary_meaning": "간결하고 요긴함.",
                "contextual_meaning": None,
                "source_references": [],
                "related_terms": [],
            },
            {
                "headword": "竹林七賢",
                "headword_reading": "죽림칠현",
                "type": "term",
                "dictionary_meaning": "위진시대 일곱 명사의 총칭.",
                "contextual_meaning": None,
                "source_references": [{"title": "世說新語"}],
                "related_terms": ["嵇康", "阮籍", "山濤", "向秀", "劉伶", "王戎", "阮咸"],
            },
        ],
        "statistics": {"total_entries": 4, "by_type": {"person": 2, "term": 2}},
    }


# ────────────────────────────────
# 테스트 1: 참조 사전 등록/목록/로드/삭제
# ────────────────────────────────

def test_register_and_list():
    with tempfile.TemporaryDirectory() as tmp:
        interp = Path(tmp) / "interp"
        interp.mkdir()

        # 등록
        data = _sample_dict()
        path = register_reference_dict(interp, data)
        assert path.exists()
        assert path.suffix == ".json"

        # 목록
        dicts = list_reference_dicts(interp)
        assert len(dicts) == 1
        assert dicts[0]["source_document_title"] == "蒙求"
        assert dicts[0]["total_entries"] == 4

        # 로드
        loaded = load_reference_dict(interp, dicts[0]["filename"])
        assert len(loaded["entries"]) == 4

        # 삭제
        assert remove_reference_dict(interp, dicts[0]["filename"])
        assert len(list_reference_dicts(interp)) == 0
        assert not remove_reference_dict(interp, "nonexistent.json")

        print("  [PASS] 참조 사전 등록/목록/로드/삭제")


# ────────────────────────────────
# 테스트 2: match_text 기본 매칭
# ────────────────────────────────

def test_match_basic():
    data = _sample_dict()
    data["_filename"] = "test_dict.json"

    text = "王戎簡要裴楷清通"
    matches = match_text(text, [data])

    # 王戎(0-1), 簡要(2-3), 裴楷(4-5) → 3개 매칭
    headwords = {m["headword"] for m in matches}
    assert "王戎" in headwords
    assert "裴楷" in headwords
    assert "簡要" in headwords

    # 竹林七賢은 텍스트에 없으므로 매칭 안 됨
    assert "竹林七賢" not in headwords

    # 위치 확인: 王戎 → start=0, end=1
    wang = [m for m in matches if m["headword"] == "王戎"][0]
    assert wang["match_positions"][0]["start"] == 0
    assert wang["match_positions"][0]["end"] == 1

    # 소스 정보 확인
    assert wang["source_dict"] == "test_dict.json"
    assert wang["source_document"] == "蒙求"

    print("  [PASS] match_text 기본 매칭")


# ────────────────────────────────
# 테스트 3: 같은 표제어가 여러 번 출현
# ────────────────────────────────

def test_match_multiple_occurrences():
    data = _sample_dict()
    data["_filename"] = "test.json"

    # 王戎이 두 번 출현
    text = "王戎簡要王戎再現"
    matches = match_text(text, [data])

    wang = [m for m in matches if m["headword"] == "王戎"][0]
    assert len(wang["match_positions"]) == 2
    assert wang["match_positions"][0]["start"] == 0
    assert wang["match_positions"][1]["start"] == 4

    print("  [PASS] 같은 표제어 복수 출현")


# ────────────────────────────────
# 테스트 4: 복수 참조 사전에서 같은 headword
# ────────────────────────────────

def test_match_multiple_dicts():
    dict1 = _sample_dict("monggu", "蒙求")
    dict1["_filename"] = "monggu.json"

    dict2 = {
        "source": {"document_id": "other", "document_title": "다른문헌"},
        "entries": [
            {
                "headword": "王戎",
                "headword_reading": "왕융",
                "type": "person",
                "dictionary_meaning": "다른 문헌에서의 王戎 설명.",
                "source_references": [],
                "related_terms": [],
            },
        ],
        "_filename": "other.json",
    }

    text = "王戎簡要"
    matches = match_text(text, [dict1, dict2])

    # 같은 headword가 다른 사전에서 → 별개 매칭 항목
    wang_matches = [m for m in matches if m["headword"] == "王戎"]
    assert len(wang_matches) == 2
    sources = {m["source_dict"] for m in wang_matches}
    assert sources == {"monggu.json", "other.json"}

    print("  [PASS] 복수 참조 사전 매칭")


# ────────────────────────────────
# 테스트 5: 긴 표제어 우선 매칭
# ────────────────────────────────

def test_match_longer_first():
    """竹林七賢이 먼저 매칭되어야 한다 (王戎보다 길기 때문에)."""
    data = {
        "source": {"document_title": "test"},
        "entries": [
            {"headword": "竹林七賢", "dictionary_meaning": "일곱 현인"},
            {"headword": "七賢", "dictionary_meaning": "일곱 현인 약칭"},
        ],
        "_filename": "test.json",
    }

    text = "竹林七賢也"
    matches = match_text(text, [data])

    # 둘 다 매칭되지만 竹林七賢이 더 앞에 있어야 함
    assert len(matches) == 2
    assert matches[0]["headword"] == "竹林七賢"  # 긴 것 먼저

    print("  [PASS] 긴 표제어 우선 매칭")


# ────────────────────────────────
# 테스트 6: match_page_blocks
# ────────────────────────────────

def test_match_page_blocks():
    with tempfile.TemporaryDirectory() as tmp:
        interp = Path(tmp) / "interp"
        interp.mkdir()

        # 참조 사전 등록
        data = _sample_dict()
        register_reference_dict(interp, data, filename="monggu.json")

        # 블록 텍스트
        blocks = [
            {"block_id": "p01_b01", "text": "王戎簡要裴楷清通"},
            {"block_id": "p01_b02", "text": "王戎又見於此"},
        ]

        matches = match_page_blocks(interp, blocks)

        # 王戎: p01_b01 + p01_b02 → positions 2개
        wang = [m for m in matches if m["headword"] == "王戎"][0]
        block_ids = [p.get("block_id") for p in wang["match_positions"]]
        assert "p01_b01" in block_ids
        assert "p01_b02" in block_ids

        print("  [PASS] match_page_blocks")


# ────────────────────────────────
# 테스트 7: format_for_translation_context
# ────────────────────────────────

def test_format_context():
    matches = [
        {
            "headword": "王戎",
            "headword_reading": "왕융",
            "type": "person",
            "dictionary_meaning": "竹林七賢의 한 사람.",
            "contextual_meaning": "간결한 학문의 모범",
            "source_references": [{"title": "晉書"}],
            "related_terms": [],
            "source_dict": "test.json",
            "source_document": "蒙求",
            "match_positions": [{"start": 0, "end": 1}],
        },
    ]

    result = format_for_translation_context(matches)
    assert "[참고 사전]" in result
    assert "王戎(왕융)" in result
    assert "[person]" in result
    assert "竹林七賢" in result
    assert "간결한 학문의 모범" in result
    assert "晉書" in result

    # 빈 매칭
    assert format_for_translation_context([]) == ""

    print("  [PASS] format_for_translation_context")


# ────────────────────────────────
# 테스트 8: 빈 입력 처리
# ────────────────────────────────

def test_empty_inputs():
    assert match_text("", [_sample_dict()]) == []
    assert match_text("test", []) == []
    assert match_text("", []) == []

    with tempfile.TemporaryDirectory() as tmp:
        interp = Path(tmp) / "interp"
        interp.mkdir()
        assert match_page_blocks(interp, []) == []

    print("  [PASS] 빈 입력 처리")


# ────────────────────────────────
# 테스트 9: 통합 — export → register → match
# ────────────────────────────────

def test_full_workflow():
    """문헌A에서 export → 문헌B에 register → 문헌B 원문에서 match."""
    with tempfile.TemporaryDirectory() as tmp:
        # 문헌A: 사전 주석이 있는 해석
        interp_a = Path(tmp) / "interp_a"
        interp_a.mkdir()
        page1 = {
            "part_id": "main",
            "page_number": 1,
            "schema_version": "2.0",
            "blocks": [{
                "block_id": "p01_b01",
                "annotations": [{
                    "id": "ann_001",
                    "target": {"start": 0, "end": 1},
                    "type": "person",
                    "content": {"label": "왕융(王戎)", "description": "죽림칠현"},
                    "dictionary": {
                        "headword": "王戎",
                        "headword_reading": "왕융",
                        "dictionary_meaning": "竹林七賢의 한 사람.",
                        "source_references": [{"title": "晉書"}],
                        "related_terms": [],
                    },
                    "current_stage": "from_both",
                    "generation_history": [],
                    "source_text_snapshot": "王戎簡要",
                    "translation_snapshot": None,
                    "annotator": {"type": "llm", "model": "test", "draft_id": None},
                    "status": "draft",
                    "reviewed_by": None,
                    "reviewed_at": None,
                }],
            }],
        }
        save_annotations(interp_a, "main", 1, page1)

        # Step 1: Export
        exported = export_dictionary(interp_a, "docA", "문헌A", "interpA")
        assert len(exported["entries"]) == 1

        # Step 2: 문헌B에 참조 사전 등록
        interp_b = Path(tmp) / "interp_b"
        interp_b.mkdir()
        register_reference_dict(interp_b, exported, filename="docA_dict.json")

        # Step 3: 문헌B 원문에서 매칭
        blocks = [{"block_id": "p01_b01", "text": "王戎簡要裴楷清通"}]
        matches = match_page_blocks(interp_b, blocks)

        # 王戎이 매칭되어야 함
        assert len(matches) == 1
        assert matches[0]["headword"] == "王戎"
        assert matches[0]["match_positions"][0]["start"] == 0

        # Step 4: 번역 컨텍스트로 변환
        context = format_for_translation_context(matches)
        assert "王戎" in context
        assert "竹林七賢" in context

        print("  [PASS] 통합 워크플로우 (export → register → match)")


if __name__ == "__main__":
    print("annotation_dict_match 테스트 시작...")
    test_register_and_list()
    test_match_basic()
    test_match_multiple_occurrences()
    test_match_multiple_dicts()
    test_match_longer_first()
    test_match_page_blocks()
    test_format_context()
    test_empty_inputs()
    test_full_workflow()
    print("\n모든 테스트 통과!")
