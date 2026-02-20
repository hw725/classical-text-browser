"""annotation_dict_io.py 내보내기/가져오기 테스트.

테스트 항목:
1. export_dictionary — 사전 항목 추출 + 중복 표제어 통합
2. save_export — 파일 저장 + JSON 검증
3. import_dictionary — 새 항목 가져오기
4. import merge 전략 — merge / skip_existing / overwrite
5. 라운드트립 — export → import → re-export 일관성
"""

import json
import tempfile
from pathlib import Path

from core.annotation import save_annotations, load_annotations
from core.annotation_dict_io import (
    export_dictionary,
    save_export,
    import_dictionary,
    _extract_page_num,
    _deduplicate_entries,
)


def _make_interp(tmp: Path) -> Path:
    """테스트용 해석 저장소를 생성하고 사전 주석 2페이지를 저장한다."""
    interp = tmp / "test_interp"
    interp.mkdir(parents=True)

    # 페이지 1: 王戎, 裴楷
    page1 = {
        "part_id": "main",
        "page_number": 1,
        "schema_version": "2.0",
        "blocks": [
            {
                "block_id": "p01_b01",
                "annotations": [
                    {
                        "id": "ann_001",
                        "target": {"start": 0, "end": 1},
                        "type": "person",
                        "content": {"label": "왕융(王戎)", "description": "죽림칠현의 한 사람"},
                        "dictionary": {
                            "headword": "王戎",
                            "headword_reading": "왕융",
                            "dictionary_meaning": "竹林七賢의 한 사람. 晉代 정치가.",
                            "contextual_meaning": "간결한 학문의 모범",
                            "source_references": [{"title": "晉書", "section": "列傳 第十三"}],
                            "related_terms": ["竹林七賢", "嵇康"],
                            "notes": None,
                        },
                        "current_stage": "from_both",
                        "generation_history": [],
                        "source_text_snapshot": "王戎簡要裴楷清通",
                        "translation_snapshot": None,
                        "annotator": {"type": "llm", "model": "test", "draft_id": None},
                        "status": "draft",
                        "reviewed_by": None,
                        "reviewed_at": None,
                    },
                    {
                        "id": "ann_002",
                        "target": {"start": 4, "end": 5},
                        "type": "person",
                        "content": {"label": "배해(裴楷)", "description": "진대 명사"},
                        "dictionary": {
                            "headword": "裴楷",
                            "headword_reading": "배해",
                            "dictionary_meaning": "晉代 명사. 맑고 통달함으로 유명.",
                            "contextual_meaning": None,
                            "source_references": [{"title": "晉書"}],
                            "related_terms": [],
                            "notes": None,
                        },
                        "current_stage": "from_original",
                        "generation_history": [],
                        "source_text_snapshot": "王戎簡要裴楷清通",
                        "translation_snapshot": None,
                        "annotator": {"type": "llm", "model": "test", "draft_id": None},
                        "status": "draft",
                        "reviewed_by": None,
                        "reviewed_at": None,
                    },
                ],
            }
        ],
    }
    save_annotations(interp, "main", 1, page1)

    # 페이지 2: 王戎 다시 등장 (중복 테스트) + 새 항목 簡要
    page2 = {
        "part_id": "main",
        "page_number": 2,
        "schema_version": "2.0",
        "blocks": [
            {
                "block_id": "p02_b01",
                "annotations": [
                    {
                        "id": "ann_003",
                        "target": {"start": 0, "end": 1},
                        "type": "person",
                        "content": {"label": "왕융(王戎)", "description": "죽림칠현"},
                        "dictionary": {
                            "headword": "王戎",
                            "headword_reading": "왕융",
                            "dictionary_meaning": "竹林七賢의 한 사람.",
                            "contextual_meaning": "다른 문맥",
                            "source_references": [],
                            "related_terms": ["阮籍"],
                            "notes": None,
                        },
                        "current_stage": "from_both",
                        "generation_history": [],
                        "source_text_snapshot": "王戎另一段",
                        "translation_snapshot": None,
                        "annotator": {"type": "llm", "model": "test", "draft_id": None},
                        "status": "draft",
                        "reviewed_by": None,
                        "reviewed_at": None,
                    },
                    {
                        "id": "ann_004",
                        "target": {"start": 2, "end": 3},
                        "type": "term",
                        "content": {"label": "간요(簡要)", "description": "간결하고 요긴함"},
                        "dictionary": {
                            "headword": "簡要",
                            "headword_reading": "간요",
                            "dictionary_meaning": "간결하고 요긴함. 문장이나 학문이 핵심만 담김.",
                            "contextual_meaning": None,
                            "source_references": [],
                            "related_terms": [],
                            "notes": None,
                        },
                        "current_stage": "from_original",
                        "generation_history": [],
                        "source_text_snapshot": None,
                        "translation_snapshot": None,
                        "annotator": {"type": "llm", "model": "test", "draft_id": None},
                        "status": "draft",
                        "reviewed_by": None,
                        "reviewed_at": None,
                    },
                    # dictionary 없는 주석 (내보내기에서 제외되어야 함)
                    {
                        "id": "ann_005",
                        "target": {"start": 5, "end": 6},
                        "type": "note",
                        "content": {"label": "메모", "description": "일반 메모"},
                        "dictionary": None,
                        "current_stage": "none",
                        "generation_history": [],
                        "source_text_snapshot": None,
                        "translation_snapshot": None,
                        "annotator": {"type": "human", "model": None, "draft_id": None},
                        "status": "draft",
                        "reviewed_by": None,
                        "reviewed_at": None,
                    },
                ],
            }
        ],
    }
    save_annotations(interp, "main", 2, page2)

    return interp


# ────────────────────────────────
# 테스트 1: _extract_page_num
# ────────────────────────────────

def test_extract_page_num():
    assert _extract_page_num("main_page_001_annotation.json") == 1
    assert _extract_page_num("main_page_012_annotation.json") == 12
    assert _extract_page_num("vol1_page_100_annotation.json") == 100
    assert _extract_page_num("invalid_filename.json") is None
    assert _extract_page_num("no_page_here.json") is None
    print("  [PASS] _extract_page_num")


# ────────────────────────────────
# 테스트 2: _deduplicate_entries
# ────────────────────────────────

def test_deduplicate():
    entries = [
        {
            "headword": "王戎",
            "occurrences": [{"page_number": 1}],
            "related_terms": ["竹林七賢"],
        },
        {
            "headword": "王戎",
            "occurrences": [{"page_number": 2}],
            "related_terms": ["竹林七賢", "阮籍"],
        },
        {
            "headword": "裴楷",
            "occurrences": [{"page_number": 1}],
            "related_terms": [],
        },
    ]
    result = _deduplicate_entries(entries)
    assert len(result) == 2, f"기대 2, 실제 {len(result)}"

    # 王戎: occurrences 합쳐졌는지
    wang = [e for e in result if e["headword"] == "王戎"][0]
    assert len(wang["occurrences"]) == 2
    # related_terms 합집합
    assert "竹林七賢" in wang["related_terms"]
    assert "阮籍" in wang["related_terms"]

    print("  [PASS] _deduplicate_entries")


# ────────────────────────────────
# 테스트 3: export_dictionary
# ────────────────────────────────

def test_export():
    with tempfile.TemporaryDirectory() as tmp:
        interp = _make_interp(Path(tmp))

        result = export_dictionary(
            interp_path=interp,
            doc_id="test_doc",
            doc_title="테스트 문서",
            interp_id="test_interp_001",
        )

        # 기본 구조 검증
        assert result["schema_version"] == "1.0"
        assert result["export_type"] == "dictionary"
        assert result["source"]["document_id"] == "test_doc"
        assert result["source"]["document_title"] == "테스트 문서"

        entries = result["entries"]
        # 王戎(p1+p2 통합), 裴楷(p1), 簡要(p2) = 3개
        # dictionary 없는 ann_005는 제외
        assert len(entries) == 3, f"기대 3, 실제 {len(entries)}"

        headwords = {e["headword"] for e in entries}
        assert headwords == {"王戎", "裴楷", "簡要"}

        # 王戎: 중복 통합되어 occurrences가 2개
        wang = [e for e in entries if e["headword"] == "王戎"][0]
        assert len(wang["occurrences"]) == 2
        # related_terms 합집합: 竹林七賢, 嵇康, 阮籍
        assert set(wang["related_terms"]) == {"竹林七賢", "嵇康", "阮籍"}

        # 통계
        stats = result["statistics"]
        assert stats["total_entries"] == 3
        # person: 王戎 2회 + 裴楷 1회 (중복 전), term: 簡要 1회
        # 주의: by_type은 중복 제거 전의 개별 annotation 기준
        assert stats["by_type"].get("person", 0) >= 2

        print("  [PASS] export_dictionary")
        return result


# ────────────────────────────────
# 테스트 4: save_export
# ────────────────────────────────

def test_save_export():
    with tempfile.TemporaryDirectory() as tmp:
        interp = _make_interp(Path(tmp))
        exported = export_dictionary(interp, "doc1", "문서1", "interp1")

        saved_path = save_export(interp, exported)
        assert saved_path.exists()
        assert saved_path.suffix == ".json"
        assert "dictionary_" in saved_path.name

        # 저장된 내용이 유효한 JSON인지
        with open(saved_path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["schema_version"] == "1.0"
        assert len(loaded["entries"]) == 3

        print("  [PASS] save_export")


# ────────────────────────────────
# 테스트 5: import_dictionary (새 항목)
# ────────────────────────────────

def test_import_new():
    with tempfile.TemporaryDirectory() as tmp:
        interp = Path(tmp) / "target_interp"
        interp.mkdir()

        # 외부 사전 데이터
        dict_data = {
            "schema_version": "1.0",
            "export_type": "dictionary",
            "source": {"document_id": "src_doc", "document_title": "출처문서"},
            "entries": [
                {
                    "headword": "王戎",
                    "headword_reading": "왕융",
                    "type": "person",
                    "dictionary_meaning": "竹林七賢의 한 사람.",
                    "source_references": [{"title": "晉書", "section": "列傳"}],
                    "related_terms": ["嵇康"],
                },
                {
                    "headword": "裴楷",
                    "headword_reading": "배해",
                    "type": "person",
                    "dictionary_meaning": "晉代 명사.",
                    "source_references": [],
                    "related_terms": [],
                },
            ],
        }

        result = import_dictionary(interp, dict_data)
        assert result["imported"] == 2
        assert result["merged"] == 0
        assert result["skipped"] == 0

        # 저장 확인
        loaded = load_annotations(interp, "main", 1)
        imported_block = None
        for b in loaded["blocks"]:
            if b["block_id"] == "_imported":
                imported_block = b
        assert imported_block is not None, "_imported 블록이 없음"
        assert len(imported_block["annotations"]) == 2

        # 항목 내용 검증
        ann0 = imported_block["annotations"][0]
        assert ann0["dictionary"]["headword"] == "王戎"
        assert "[출처문서에서 가져옴]" in ann0["dictionary"]["notes"]
        assert ann0["target"] == {"start": 0, "end": 0}  # 위치 미지정
        assert ann0["status"] == "draft"

        print("  [PASS] import_dictionary (새 항목)")


# ────────────────────────────────
# 테스트 6: import merge 전략
# ────────────────────────────────

def test_import_merge():
    """이미 王戎 주석이 있는 해석에 王戎 사전을 가져올 때 merge 동작 검증."""
    with tempfile.TemporaryDirectory() as tmp:
        interp = _make_interp(Path(tmp))

        dict_data = {
            "source": {"document_title": "외부문서"},
            "entries": [
                {
                    "headword": "王戎",
                    "headword_reading": "왕융",
                    "type": "person",
                    "dictionary_meaning": "다른 정의.",
                    "source_references": [{"title": "世說新語", "section": "德行"}],
                    "related_terms": ["山濤"],
                },
            ],
        }

        # merge 전략
        result = import_dictionary(interp, dict_data, target_page=1, merge_strategy="merge")
        assert result["merged"] == 1
        assert result["imported"] == 0

        # 기존 王戎 주석에 source_references가 추가되었는지
        loaded = load_annotations(interp, "main", 1)
        wang_ann = None
        for b in loaded["blocks"]:
            for ann in b["annotations"]:
                if ann.get("dictionary", {}).get("headword") == "王戎":
                    wang_ann = ann
                    break
        assert wang_ann is not None

        refs = [r["title"] for r in wang_ann["dictionary"]["source_references"]]
        assert "晉書" in refs, "기존 출전 유지"
        assert "世說新語" in refs, "새 출전 추가"

        terms = wang_ann["dictionary"]["related_terms"]
        assert "竹林七賢" in terms, "기존 관련어 유지"
        assert "山濤" in terms, "새 관련어 추가"

        assert "[외부문서에서 가져옴]" in (wang_ann["dictionary"].get("notes") or "")

        print("  [PASS] import merge 전략")


# ────────────────────────────────
# 테스트 7: import skip_existing 전략
# ────────────────────────────────

def test_import_skip():
    with tempfile.TemporaryDirectory() as tmp:
        interp = _make_interp(Path(tmp))

        dict_data = {
            "source": {"document_title": "외부"},
            "entries": [
                {"headword": "王戎", "dictionary_meaning": "skip 테스트"},
                {"headword": "新項目", "headword_reading": "신항목", "dictionary_meaning": "새 항목"},
            ],
        }

        result = import_dictionary(interp, dict_data, target_page=1, merge_strategy="skip_existing")
        assert result["skipped"] == 1  # 王戎 skip
        assert result["imported"] == 1  # 新項目 import

        print("  [PASS] import skip_existing 전략")


# ────────────────────────────────
# 테스트 8: 라운드트립 (export → import → re-export)
# ────────────────────────────────

def test_roundtrip():
    """문헌A에서 export → 문헌B에서 import → 문헌B에서 re-export 시 항목이 보존되는지."""
    with tempfile.TemporaryDirectory() as tmp:
        # 문헌A: 원본
        interp_a = _make_interp(Path(tmp))

        # export
        exported = export_dictionary(interp_a, "docA", "문헌A", "interpA")
        assert len(exported["entries"]) == 3

        # 문헌B: 빈 해석
        interp_b = Path(tmp) / "interp_b"
        interp_b.mkdir()

        # import
        result = import_dictionary(interp_b, exported, target_page=1)
        assert result["imported"] == 3

        # 문헌B에서 re-export
        re_exported = export_dictionary(interp_b, "docB", "문헌B", "interpB")

        # 항목 수 보존
        assert len(re_exported["entries"]) == 3
        re_headwords = {e["headword"] for e in re_exported["entries"]}
        assert re_headwords == {"王戎", "裴楷", "簡要"}

        # source 정보는 문헌B로 변경
        assert re_exported["source"]["document_id"] == "docB"

        print("  [PASS] 라운드트립")


# ────────────────────────────────
# 테스트 9: page_range 필터
# ────────────────────────────────

def test_export_page_range():
    with tempfile.TemporaryDirectory() as tmp:
        interp = _make_interp(Path(tmp))

        # 페이지 1만 export
        result = export_dictionary(interp, "doc", "문서", "interp", page_range=(1, 1))
        headwords = {e["headword"] for e in result["entries"]}
        assert "王戎" in headwords
        assert "裴楷" in headwords
        assert "簡要" not in headwords  # 페이지 2에만 있음

        print("  [PASS] export page_range 필터")


if __name__ == "__main__":
    print("annotation_dict_io 테스트 시작...")
    test_extract_page_num()
    test_deduplicate()
    test_export()
    test_save_export()
    test_import_new()
    test_import_merge()
    test_import_skip()
    test_roundtrip()
    test_export_page_range()
    print("\n모든 테스트 통과!")
