"""인용 마크(Citation Mark) 코어 로직 테스트.

테스트 대상: src/core/citation_mark.py
실행 방법:
  PYTHONPATH=src python tests/test_citation_mark.py
  또는: uv run pytest tests/test_citation_mark.py -v
"""

import json
import sys
import tempfile
from pathlib import Path

# PYTHONPATH에 src 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.citation_mark import (
    _adjust_mark_offsets,
    _filter_marks_for_range,
    _gen_cite_id,
    add_citation_mark,
    export_citations,
    format_citation,
    list_all_citation_marks,
    load_citation_marks,
    remove_citation_mark,
    save_citation_marks,
    update_citation_mark,
)


def _make_empty_page(part_id="main", page_num=1):
    """빈 인용 마크 페이지 구조 생성."""
    return {
        "part_id": part_id,
        "page_number": page_num,
        "marks": [],
    }


def _make_mark(block_id="p01_b01", start=0, end=3, text="王戎簡要"):
    """테스트용 인용 마크 생성."""
    return {
        "source": {"block_id": block_id, "start": start, "end": end},
        "marked_from": "original",
        "source_text_snapshot": text,
    }


# ──────────────────────────────────────
# 1. ID 생성
# ──────────────────────────────────────


def test_gen_cite_id():
    """cite_xxxxxx 형식의 ID가 생성되는지 확인."""
    cid = _gen_cite_id()
    assert cid.startswith("cite_")
    assert len(cid) == 11  # cite_ + 6자리 hex

    # 유일성 확인
    ids = {_gen_cite_id() for _ in range(100)}
    assert len(ids) == 100


# ──────────────────────────────────────
# 2. CRUD
# ──────────────────────────────────────


def test_add_citation_mark():
    """인용 마크 추가: id, created_at, status 자동 생성."""
    data = _make_empty_page()
    mark = _make_mark()

    result = add_citation_mark(data, mark)

    assert result["id"].startswith("cite_")
    assert result["created_at"]  # ISO 8601 문자열
    assert result["status"] == "active"
    assert result["label"] is None
    assert result["tags"] == []
    assert result["citation_override"] is None
    assert len(data["marks"]) == 1


def test_update_citation_mark():
    """인용 마크 수정: label, tags, status 변경."""
    data = _make_empty_page()
    mark = _make_mark()
    added = add_citation_mark(data, mark)
    mark_id = added["id"]

    updated = update_citation_mark(data, mark_id, {
        "label": "핵심 논거",
        "tags": ["서론", "핵심"],
        "status": "used",
    })

    assert updated is not None
    assert updated["label"] == "핵심 논거"
    assert updated["tags"] == ["서론", "핵심"]
    assert updated["status"] == "used"


def test_update_immutable_fields():
    """id, source, created_at는 수정 불가."""
    data = _make_empty_page()
    mark = _make_mark()
    added = add_citation_mark(data, mark)
    original_id = added["id"]
    original_source = added["source"]

    update_citation_mark(data, original_id, {
        "id": "hacked_id",
        "source": {"block_id": "p99_b99", "start": 99, "end": 99},
    })

    assert data["marks"][0]["id"] == original_id
    assert data["marks"][0]["source"] == original_source


def test_remove_citation_mark():
    """인용 마크 삭제."""
    data = _make_empty_page()
    m1 = add_citation_mark(data, _make_mark(start=0, end=1))
    m2 = add_citation_mark(data, _make_mark(start=2, end=3))

    assert len(data["marks"]) == 2
    assert remove_citation_mark(data, m1["id"]) is True
    assert len(data["marks"]) == 1
    assert data["marks"][0]["id"] == m2["id"]

    # 존재하지 않는 ID
    assert remove_citation_mark(data, "cite_nonexist") is False


def test_update_citation_override():
    """citation_override 필드 수정."""
    data = _make_empty_page()
    added = add_citation_mark(data, _make_mark())

    override = {
        "work_title": "答巡使書",
        "page_ref": "25면",
        "supplementary": "韓國文集叢刊252집, 48면",
    }
    updated = update_citation_mark(data, added["id"], {
        "citation_override": override,
    })

    assert updated["citation_override"]["work_title"] == "答巡使書"
    assert updated["citation_override"]["page_ref"] == "25면"
    assert updated["citation_override"]["supplementary"] == "韓國文集叢刊252집, 48면"


# ──────────────────────────────────────
# 3. 파일 I/O + 스키마 검증
# ──────────────────────────────────────


def test_save_load_roundtrip():
    """저장 → 로드 라운드트립 + 스키마 검증."""
    with tempfile.TemporaryDirectory() as tmpdir:
        interp_path = Path(tmpdir)
        data = _make_empty_page(part_id="vol1", page_num=2)

        mark = _make_mark(text="裴楷清通")
        add_citation_mark(data, mark)

        # 저장
        saved_path = save_citation_marks(interp_path, "vol1", 2, data)
        assert saved_path.exists()
        assert "citation_marks" in str(saved_path)

        # 로드
        loaded = load_citation_marks(interp_path, "vol1", 2)
        assert loaded["part_id"] == "vol1"
        assert loaded["page_number"] == 2
        assert len(loaded["marks"]) == 1
        assert loaded["marks"][0]["source_text_snapshot"] == "裴楷清通"


def test_load_nonexistent_returns_empty():
    """존재하지 않는 파일 로드 시 빈 구조 반환."""
    with tempfile.TemporaryDirectory() as tmpdir:
        loaded = load_citation_marks(Path(tmpdir), "main", 999)
        assert loaded["part_id"] == "main"
        assert loaded["page_number"] == 999
        assert loaded["marks"] == []


def test_schema_validation_rejects_invalid():
    """스키마 검증: 필수 필드 누락 시 에러."""
    import jsonschema

    with tempfile.TemporaryDirectory() as tmpdir:
        # marks에 잘못된 항목
        data = {
            "part_id": "main",
            "page_number": 1,
            "marks": [{"bad_field": "value"}],
        }
        try:
            save_citation_marks(Path(tmpdir), "main", 1, data)
            assert False, "스키마 검증 실패 예상"
        except jsonschema.ValidationError:
            pass  # 예상된 동작


# ──────────────────────────────────────
# 4. 전체 마크 수집
# ──────────────────────────────────────


def test_list_all_citation_marks():
    """여러 페이지의 인용 마크를 통합 수집."""
    with tempfile.TemporaryDirectory() as tmpdir:
        interp_path = Path(tmpdir)

        # 페이지 1: 마크 2개
        data1 = _make_empty_page(page_num=1)
        add_citation_mark(data1, _make_mark(start=0, end=1, text="王戎"))
        add_citation_mark(data1, _make_mark(start=4, end=5, text="裴楷"))
        save_citation_marks(interp_path, "main", 1, data1)

        # 페이지 2: 마크 1개
        data2 = _make_empty_page(page_num=2)
        add_citation_mark(data2, _make_mark(start=0, end=3, text="孔明臥龍"))
        save_citation_marks(interp_path, "main", 2, data2)

        all_marks = list_all_citation_marks(interp_path, "main")
        assert len(all_marks) == 3

        # 페이지 번호 포함 확인
        pages = [m["page_number"] for m in all_marks]
        assert 1 in pages
        assert 2 in pages


# ──────────────────────────────────────
# 5. 표점 필터 유틸리티
# ──────────────────────────────────────


def test_filter_marks_for_range():
    """인용 범위 내 표점만 필터."""
    marks = [
        {"id": "pm_1", "target": {"start": 0, "end": 0}, "before": None, "after": "，"},
        {"id": "pm_2", "target": {"start": 3, "end": 3}, "before": None, "after": "。"},
        {"id": "pm_3", "target": {"start": 7, "end": 7}, "before": None, "after": "，"},
    ]
    # 범위: 0~5 → pm_1, pm_2만 포함
    filtered = _filter_marks_for_range(marks, 0, 5)
    assert len(filtered) == 2
    assert filtered[0]["id"] == "pm_1"
    assert filtered[1]["id"] == "pm_2"


def test_adjust_mark_offsets():
    """오프셋 조정: start=3인 표점 → offset 3 → start=0."""
    marks = [
        {"id": "pm_1", "target": {"start": 3, "end": 3}, "before": None, "after": "。"},
        {"id": "pm_2", "target": {"start": 5, "end": 5}, "before": None, "after": "，"},
    ]
    adjusted = _adjust_mark_offsets(marks, 3)
    assert adjusted[0]["target"]["start"] == 0
    assert adjusted[0]["target"]["end"] == 0
    assert adjusted[1]["target"]["start"] == 2
    assert adjusted[1]["target"]["end"] == 2


# ──────────────────────────────────────
# 6. 인용 형식 변환
# ──────────────────────────────────────


def test_format_citation_full():
    """서지정보 + override + 표점본 → 완전한 인용 형식."""
    context = {
        "mark": {
            "id": "cite_test01",
            "source": {"block_id": "p01_b01", "start": 0, "end": 15},
            "citation_override": {
                "work_title": "答巡使書",
                "page_ref": "25면",
                "supplementary": "韓國文集叢刊252집, 48면",
            },
        },
        "original_text": "若吾所樂者善而所敬者天也",
        "punctuated_text": "若吾所樂者善，而所敬者天也。",
        "translations": [
            {"id": "tr_1", "translation": "만약 내가 즐기는 것이 선이요, 공경하는 것이 하늘이라면", "status": "accepted"}
        ],
        "annotations": [],
        "bibliography": {
            "title": "燕岩集",
            "creator": "朴趾源",
            "physical_description": {"volumes": "卷2"},
        },
    }

    result = format_citation(context, include_translation=False)
    assert "朴趾源" in result
    assert "燕岩集" in result
    assert "答巡使書" in result
    assert "25면" in result
    assert "韓國文集叢刊252집" in result
    assert "若吾所樂者善，而所敬者天也。" in result

    # 번역 포함
    result_with_trans = format_citation(context, include_translation=True)
    assert "만약 내가 즐기는 것이 선이요" in result_with_trans


def test_format_citation_minimal():
    """서지정보 없는 경우에도 원문은 출력."""
    context = {
        "mark": {
            "id": "cite_test02",
            "source": {"block_id": "p01_b01", "start": 0, "end": 3},
            "citation_override": None,
        },
        "original_text": "王戎簡要",
        "punctuated_text": "王戎簡要",
        "translations": [],
        "annotations": [],
        "bibliography": {},
    }

    result = format_citation(context)
    assert "王戎簡要" in result


def test_export_citations_multiple():
    """여러 인용 일괄 변환."""
    ctx1 = {
        "mark": {"id": "cite_1", "source": {"block_id": "p01_b01", "start": 0, "end": 3}, "citation_override": None},
        "punctuated_text": "王戎簡要，",
        "translations": [],
        "bibliography": {"title": "蒙求"},
    }
    ctx2 = {
        "mark": {"id": "cite_2", "source": {"block_id": "p01_b01", "start": 4, "end": 7}, "citation_override": None},
        "punctuated_text": "裴楷清通。",
        "translations": [],
        "bibliography": {"title": "蒙求"},
    }

    result = export_citations([ctx1, ctx2], include_translation=False)
    assert "王戎簡要" in result
    assert "裴楷清通" in result
    # 두 인용 사이에 빈 줄
    assert "\n\n" in result


# ──────────────────────────────────────
# 실행
# ──────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_gen_cite_id,
        test_add_citation_mark,
        test_update_citation_mark,
        test_update_immutable_fields,
        test_remove_citation_mark,
        test_update_citation_override,
        test_save_load_roundtrip,
        test_load_nonexistent_returns_empty,
        test_schema_validation_rejects_invalid,
        test_list_all_citation_marks,
        test_filter_marks_for_range,
        test_adjust_mark_offsets,
        test_format_citation_full,
        test_format_citation_minimal,
        test_export_citations_multiple,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {t.__name__} — {e}")
            failed += 1

    print(f"\n결과: {passed} passed, {failed} failed / {len(tests)} total")
    if failed > 0:
        sys.exit(1)
