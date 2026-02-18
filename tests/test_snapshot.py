"""JSON 스냅샷 Export/Import 테스트.

Phase 12-3: build_snapshot, create_work_from_snapshot, validate_snapshot,
detect_imported_layers 함수의 단위·통합 테스트.

테스트 구조:
    TestBuildSnapshot — Export 기능 (14개)
    TestValidateSnapshot — Import 전 검증 (10개)
    TestCreateWorkFromSnapshot — Import 기능 (8개)
    TestDetectImportedLayers — 레이어 감지 (3개)
    TestRoundTrip — Export → Import 순환 (2개)
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

import git
import pytest


# ──────────────────────────────────────
# 테스트 헬퍼: 서고 구조 생성
# ──────────────────────────────────────

def _make_library(tmp_path: Path, doc_id: str = "test_doc", interp_id: str = "test_interp"):
    """테스트용 서고 전체 구조를 생성한다.

    왜 이렇게 하는가:
        Export/Import 테스트에 필요한 최소한의 L1~L7 파일을
        한 번에 만들어서 각 테스트가 재사용할 수 있게 한다.
    """
    lib = tmp_path / "library"
    lib.mkdir()

    doc_path = lib / "documents" / doc_id
    interp_path = lib / "interpretations" / interp_id

    # ─── 원본 저장소 ───

    # manifest
    doc_path.mkdir(parents=True)
    (doc_path / "manifest.json").write_text(json.dumps({
        "document_id": doc_id,
        "title": "蒙求",
        "title_ko": "몽구",
        "parts": [{"part_id": "vol1", "title": "卷上"}],
        "created_at": "2025-01-01T00:00:00+00:00",
        "notes": "테스트용",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # bibliography
    (doc_path / "bibliography.json").write_text(json.dumps({
        "title": "蒙求",
        "author": "李瀚",
        "date": "唐",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # L1: 이미지 (더미 파일)
    l1 = doc_path / "L1_source"
    l1.mkdir()
    (l1 / "page_001.pdf").write_bytes(b"dummy-pdf-content")

    # L3: 레이아웃
    l3 = doc_path / "L3_layout"
    l3.mkdir()
    (l3 / "vol1_page_001.json").write_text(json.dumps({
        "part_id": "vol1",
        "page_number": 1,
        "blocks": [
            {"block_id": "blk_001", "type": "text", "order": 1, "bbox": [100, 100, 500, 200]},
            {"block_id": "blk_002", "type": "text", "order": 2, "bbox": [100, 200, 500, 300]},
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # L4: 텍스트
    l4_pages = doc_path / "L4_text" / "pages"
    l4_corr = doc_path / "L4_text" / "corrections"
    l4_pages.mkdir(parents=True)
    l4_corr.mkdir()
    (l4_pages / "vol1_page_001.txt").write_text("白起坑趙\n王翦滅楚", encoding="utf-8")
    (l4_corr / "vol1_page_001_corrections.json").write_text(json.dumps({
        "page": "vol1_page_001",
        "corrections": [{"position": 0, "original": "白", "corrected": "白", "note": "확인"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # Git 초기화 (원본)
    repo = git.Repo.init(doc_path)
    repo.index.add([str(f.relative_to(doc_path)) for f in doc_path.rglob("*") if f.is_file()])
    repo.index.commit("init: 테스트 원본 데이터")

    # ─── 해석 저장소 ───

    interp_path.mkdir(parents=True)
    (interp_path / "manifest.json").write_text(json.dumps({
        "interpretation_id": interp_id,
        "source_document_id": doc_id,
        "title": "蒙求 해석",
        "interpreter": {"type": "human", "name": "테스터"},
        "created_at": "2025-01-02T00:00:00+00:00",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # dependency.json
    (interp_path / "dependency.json").write_text(json.dumps({
        "source": {
            "document_id": doc_id,
            "base_commit": "abc123",
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # L5: 표점
    l5_dir = interp_path / "L5_reading" / "main_text"
    l5_dir.mkdir(parents=True)
    (l5_dir / "vol1_page_001_punctuation.json").write_text(json.dumps({
        "block_id": "blk_001",
        "punctuated_text": "白起坑趙，",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # L5: 현토
    (l5_dir / "vol1_page_001_hyeonto.json").write_text(json.dumps({
        "block_id": "blk_001",
        "hyeonto_text": "白起ㅣ 趙를 坑하니",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # L6: 번역
    l6_dir = interp_path / "L6_translation" / "main_text"
    l6_dir.mkdir(parents=True)
    (l6_dir / "vol1_page_001_translation.json").write_text(json.dumps({
        "translations": [
            {"source": {"block_id": "blk_001"}, "text": "백기가 조나라를 구덩이에 묻었다"},
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # L7: 주석
    l7_dir = interp_path / "L7_annotation" / "main_text"
    l7_dir.mkdir(parents=True)
    (l7_dir / "vol1_page_001_annotation.json").write_text(json.dumps({
        "blocks": [
            {
                "block_id": "blk_001",
                "annotations": [
                    {"type": "person", "text": "白起", "note": "진나라 장군"},
                ],
            },
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # 코어 엔티티
    person_dir = interp_path / "core_entities" / "person"
    person_dir.mkdir(parents=True)
    (person_dir / "ent_001.json").write_text(json.dumps({
        "id": "ent_001",
        "name": "白起",
        "type": "person",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # Git 초기화 (해석)
    repo2 = git.Repo.init(interp_path)
    repo2.index.add([str(f.relative_to(interp_path)) for f in interp_path.rglob("*") if f.is_file()])
    repo2.index.commit("init: 테스트 해석 데이터")

    # library_manifest
    (lib / "library_manifest.json").write_text(json.dumps({
        "name": "test_library",
        "documents": [{"document_id": doc_id, "title": "蒙求"}],
        "interpretations": [{"interpretation_id": interp_id, "source_document_id": doc_id, "title": "蒙求 해석"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    return lib, doc_id, interp_id


# ──────────────────────────────────────
# TestBuildSnapshot — Export
# ──────────────────────────────────────


class TestBuildSnapshot:
    """build_snapshot() Export 기능 테스트."""

    def test_snapshot_has_schema_version(self, tmp_path):
        """스냅샷에 schema_version이 포함된다."""
        from core.snapshot import build_snapshot
        lib, doc_id, interp_id = _make_library(tmp_path)
        result = build_snapshot(lib, doc_id, interp_id)
        assert result["schema_version"] == "1.0"

    def test_snapshot_has_export_timestamp(self, tmp_path):
        """스냅샷에 export_timestamp가 포함된다."""
        from core.snapshot import build_snapshot
        lib, doc_id, interp_id = _make_library(tmp_path)
        result = build_snapshot(lib, doc_id, interp_id)
        assert "export_timestamp" in result

    def test_work_metadata(self, tmp_path):
        """work 섹션에 문헌+해석 메타데이터가 포함된다."""
        from core.snapshot import build_snapshot
        lib, doc_id, interp_id = _make_library(tmp_path)
        result = build_snapshot(lib, doc_id, interp_id)
        work = result["work"]
        assert work["title"] == "蒙求"
        assert work["title_ko"] == "몽구"
        assert work["interpretation_title"] == "蒙求 해석"
        assert work["bibliography"]["author"] == "李瀚"

    def test_l1_reference_only(self, tmp_path):
        """L1은 경로 참조만 포함한다 (바이너리 미포함)."""
        from core.snapshot import build_snapshot
        lib, doc_id, interp_id = _make_library(tmp_path)
        result = build_snapshot(lib, doc_id, interp_id)
        l1 = result["original"]["layers"]["L1_source"]
        assert l1["type"] == "reference"
        assert len(l1["files"]) == 1
        assert l1["files"][0]["name"] == "page_001.pdf"
        assert "content" not in l1["files"][0]

    def test_l3_layout_inline(self, tmp_path):
        """L3 레이아웃이 inline으로 포함된다."""
        from core.snapshot import build_snapshot
        lib, doc_id, interp_id = _make_library(tmp_path)
        result = build_snapshot(lib, doc_id, interp_id)
        l3 = result["original"]["layers"]["L3_layout"]
        assert l3["type"] == "inline"
        assert len(l3["pages"]) == 1
        assert l3["pages"][0]["blocks"][0]["block_id"] == "blk_001"

    def test_l4_text_and_corrections(self, tmp_path):
        """L4 텍스트와 교정 기록이 포함된다."""
        from core.snapshot import build_snapshot
        lib, doc_id, interp_id = _make_library(tmp_path)
        result = build_snapshot(lib, doc_id, interp_id)
        l4 = result["original"]["layers"]["L4_text"]
        assert len(l4["pages"]) == 1
        assert "白起坑趙" in l4["pages"][0]["text"]
        assert "corrections" in l4["pages"][0]

    def test_l5_punctuation(self, tmp_path):
        """L5 표점이 수집된다."""
        from core.snapshot import build_snapshot
        lib, doc_id, interp_id = _make_library(tmp_path)
        result = build_snapshot(lib, doc_id, interp_id)
        l5p = result["interpretation"]["layers"]["L5_punctuation"]
        assert len(l5p) >= 1
        assert l5p[0]["block_id"] == "blk_001"
        # _source_path 메타데이터 포함 확인
        assert "_source_path" in l5p[0]

    def test_l5_hyeonto(self, tmp_path):
        """L5 현토가 수집된다."""
        from core.snapshot import build_snapshot
        lib, doc_id, interp_id = _make_library(tmp_path)
        result = build_snapshot(lib, doc_id, interp_id)
        l5h = result["interpretation"]["layers"]["L5_hyeonto"]
        assert len(l5h) >= 1
        assert l5h[0].get("hyeonto_text") is not None
        assert l5h[0]["block_id"] == "blk_001"

    def test_l6_translation(self, tmp_path):
        """L6 번역이 수집된다."""
        from core.snapshot import build_snapshot
        lib, doc_id, interp_id = _make_library(tmp_path)
        result = build_snapshot(lib, doc_id, interp_id)
        l6 = result["interpretation"]["layers"]["L6_translation"]
        assert len(l6) >= 1

    def test_l7_annotation(self, tmp_path):
        """L7 주석이 수집된다."""
        from core.snapshot import build_snapshot
        lib, doc_id, interp_id = _make_library(tmp_path)
        result = build_snapshot(lib, doc_id, interp_id)
        l7 = result["interpretation"]["layers"]["L7_annotation"]
        assert len(l7) >= 1

    def test_core_entities(self, tmp_path):
        """코어 엔티티가 수집된다."""
        from core.snapshot import build_snapshot
        lib, doc_id, interp_id = _make_library(tmp_path)
        result = build_snapshot(lib, doc_id, interp_id)
        entities = result["interpretation"]["core_entities"]
        assert "person" in entities
        assert entities["person"][0]["name"] == "白起"

    def test_dependency_included(self, tmp_path):
        """dependency.json이 포함된다."""
        from core.snapshot import build_snapshot
        lib, doc_id, interp_id = _make_library(tmp_path)
        result = build_snapshot(lib, doc_id, interp_id)
        assert result["interpretation"].get("dependency") is not None
        assert result["interpretation"]["base_original_hash"] == "abc123"

    def test_head_hash_included(self, tmp_path):
        """원본/해석 저장소의 HEAD 해시가 포함된다."""
        from core.snapshot import build_snapshot
        lib, doc_id, interp_id = _make_library(tmp_path)
        result = build_snapshot(lib, doc_id, interp_id)
        assert result["original"]["head_hash"] is not None
        assert result["interpretation"]["head_hash"] is not None

    def test_json_serializable(self, tmp_path):
        """스냅샷 전체가 JSON 직렬화 가능하다."""
        from core.snapshot import build_snapshot
        lib, doc_id, interp_id = _make_library(tmp_path)
        result = build_snapshot(lib, doc_id, interp_id)
        serialized = json.dumps(result, ensure_ascii=False, indent=2)
        assert len(serialized) > 100


# ──────────────────────────────────────
# TestValidateSnapshot
# ──────────────────────────────────────


class TestValidateSnapshot:
    """validate_snapshot() 검증 테스트."""

    def _minimal_snapshot(self):
        """검증 통과하는 최소 스냅샷."""
        return {
            "schema_version": "1.0",
            "work": {"title": "테스트"},
            "original": {"layers": {}},
            "interpretation": {"layers": {}},
        }

    def test_valid_minimal(self):
        """최소 스냅샷이 검증을 통과한다."""
        from core.snapshot_validator import validate_snapshot
        errors, warnings = validate_snapshot(self._minimal_snapshot())
        assert len(errors) == 0

    def test_missing_schema_version(self):
        """schema_version 누락 시 error."""
        from core.snapshot_validator import validate_snapshot
        data = self._minimal_snapshot()
        del data["schema_version"]
        errors, _ = validate_snapshot(data)
        assert any("schema_version" in e for e in errors)

    def test_unsupported_version(self):
        """지원하지 않는 버전 시 error."""
        from core.snapshot_validator import validate_snapshot
        data = self._minimal_snapshot()
        data["schema_version"] = "99.0"
        errors, _ = validate_snapshot(data)
        assert any("99.0" in e for e in errors)

    def test_missing_title(self):
        """work.title 누락 시 error."""
        from core.snapshot_validator import validate_snapshot
        data = self._minimal_snapshot()
        data["work"]["title"] = ""
        errors, _ = validate_snapshot(data)
        assert any("title" in e for e in errors)

    def test_missing_original(self):
        """original 섹션 누락 시 error."""
        from core.snapshot_validator import validate_snapshot
        data = self._minimal_snapshot()
        del data["original"]
        errors, _ = validate_snapshot(data)
        assert any("original" in e for e in errors)

    def test_l1_reference_warning(self):
        """L1 이미지 참조 시 warning."""
        from core.snapshot_validator import validate_snapshot
        data = self._minimal_snapshot()
        data["original"]["layers"]["L1_source"] = {
            "type": "reference",
            "files": [{"name": "page.pdf"}],
        }
        _, warnings = validate_snapshot(data)
        assert any("L1" in w for w in warnings)

    def test_l4_missing_warning(self):
        """L4 텍스트 없을 때 warning."""
        from core.snapshot_validator import validate_snapshot
        data = self._minimal_snapshot()
        _, warnings = validate_snapshot(data)
        assert any("L4" in w for w in warnings)

    def test_block_id_mismatch_warning(self):
        """L5 block_id가 L3에 없으면 warning."""
        from core.snapshot_validator import validate_snapshot
        data = self._minimal_snapshot()
        data["original"]["layers"]["L3_layout"] = {
            "pages": [{"blocks": [{"block_id": "blk_001"}]}],
        }
        data["interpretation"]["layers"]["L5_punctuation"] = [
            {"block_id": "blk_999"},  # L3에 없는 ID
        ]
        _, warnings = validate_snapshot(data)
        assert any("blk_999" in w for w in warnings)

    def test_block_id_match_no_warning(self):
        """L5 block_id가 L3에 있으면 warning 없음."""
        from core.snapshot_validator import validate_snapshot
        data = self._minimal_snapshot()
        data["original"]["layers"]["L3_layout"] = {
            "pages": [{"blocks": [{"block_id": "blk_001"}]}],
        }
        data["interpretation"]["layers"]["L5_punctuation"] = [
            {"block_id": "blk_001"},
        ]
        _, warnings = validate_snapshot(data)
        # block_id 관련 warning이 없어야 함
        assert not any("block_id" in w for w in warnings)

    def test_annotation_type_mismatch_warning(self):
        """L7 주석 type이 annotation_types에 없으면 warning."""
        from core.snapshot_validator import validate_snapshot
        data = self._minimal_snapshot()
        data["annotation_types"] = [{"id": "person"}]
        data["interpretation"]["layers"]["L7_annotation"] = [{
            "blocks": [{
                "block_id": "blk_001",
                "annotations": [{"type": "unknown_type", "text": "test"}],
            }],
        }]
        _, warnings = validate_snapshot(data)
        assert any("unknown_type" in w for w in warnings)


# ──────────────────────────────────────
# TestCreateWorkFromSnapshot
# ──────────────────────────────────────


class TestCreateWorkFromSnapshot:
    """create_work_from_snapshot() Import 기능 테스트."""

    def _export_then_import(self, tmp_path):
        """Export → Import 수행. 편의 헬퍼."""
        from core.snapshot import build_snapshot, create_work_from_snapshot

        lib, doc_id, interp_id = _make_library(tmp_path)
        snapshot = build_snapshot(lib, doc_id, interp_id)
        result = create_work_from_snapshot(lib, snapshot)
        return lib, result, snapshot

    def test_new_doc_id_generated(self, tmp_path):
        """새 doc_id가 생성된다 (원본과 다른 ID)."""
        lib, result, _ = self._export_then_import(tmp_path)
        assert result["doc_id"] != "test_doc"
        assert "test_doc" in result["doc_id"]  # 원본 ID가 접두사

    def test_new_interp_id_generated(self, tmp_path):
        """새 interp_id가 생성된다."""
        lib, result, _ = self._export_then_import(tmp_path)
        assert result["interp_id"] != "test_interp"
        assert "test_interp" in result["interp_id"]

    def test_manifest_created(self, tmp_path):
        """Import 후 문헌 manifest가 생성된다."""
        lib, result, _ = self._export_then_import(tmp_path)
        doc_path = lib / "documents" / result["doc_id"]
        manifest = json.loads((doc_path / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["document_id"] == result["doc_id"]
        assert manifest["title"] == "蒙求"

    def test_l4_text_restored(self, tmp_path):
        """L4 텍스트가 복원된다."""
        lib, result, _ = self._export_then_import(tmp_path)
        doc_path = lib / "documents" / result["doc_id"]
        text_file = doc_path / "L4_text" / "pages" / "vol1_page_001.txt"
        assert text_file.exists()
        content = text_file.read_text(encoding="utf-8")
        assert "白起坑趙" in content

    def test_l3_layout_restored(self, tmp_path):
        """L3 레이아웃이 복원된다."""
        lib, result, _ = self._export_then_import(tmp_path)
        doc_path = lib / "documents" / result["doc_id"]
        l3_files = list((doc_path / "L3_layout").glob("*.json"))
        assert len(l3_files) >= 1

    def test_interpretation_layers_restored(self, tmp_path):
        """해석 레이어(L5~L7)가 복원된다."""
        lib, result, _ = self._export_then_import(tmp_path)
        interp_path = lib / "interpretations" / result["interp_id"]
        # L5 표점
        l5_files = list(interp_path.rglob("*_punctuation.json"))
        assert len(l5_files) >= 1
        # L6 번역
        l6_files = list(interp_path.rglob("*_translation.json"))
        assert len(l6_files) >= 1

    def test_git_initialized(self, tmp_path):
        """Import 후 Git 저장소가 초기화된다."""
        lib, result, _ = self._export_then_import(tmp_path)
        doc_path = lib / "documents" / result["doc_id"]
        interp_path = lib / "interpretations" / result["interp_id"]
        assert (doc_path / ".git").exists()
        assert (interp_path / ".git").exists()

    def test_library_manifest_updated(self, tmp_path):
        """library_manifest.json에 새 항목이 추가된다."""
        lib, result, _ = self._export_then_import(tmp_path)
        manifest = json.loads((lib / "library_manifest.json").read_text(encoding="utf-8"))
        doc_ids = [d["document_id"] for d in manifest["documents"]]
        assert result["doc_id"] in doc_ids
        interp_ids = [i["interpretation_id"] for i in manifest["interpretations"]]
        assert result["interp_id"] in interp_ids


# ──────────────────────────────────────
# TestDetectImportedLayers
# ──────────────────────────────────────


class TestDetectImportedLayers:
    """detect_imported_layers() 테스트."""

    def test_full_snapshot(self, tmp_path):
        """모든 레이어가 있는 스냅샷에서 모두 감지한다."""
        from core.snapshot import build_snapshot, detect_imported_layers
        lib, doc_id, interp_id = _make_library(tmp_path)
        snapshot = build_snapshot(lib, doc_id, interp_id)
        layers = detect_imported_layers(snapshot)
        assert "L1" in layers
        assert "L3" in layers
        assert "L4" in layers
        assert "L5_punctuation" in layers

    def test_empty_snapshot(self):
        """빈 스냅샷에서 빈 리스트 반환."""
        from core.snapshot import detect_imported_layers
        layers = detect_imported_layers({})
        assert layers == []

    def test_partial_snapshot(self):
        """일부 레이어만 있는 스냅샷에서 해당 레이어만 감지."""
        from core.snapshot import detect_imported_layers
        data = {
            "original": {"layers": {
                "L4_text": {"pages": [{"text": "test"}]},
            }},
            "interpretation": {"layers": {
                "L6_translation": [{"text": "번역"}],
            }},
        }
        layers = detect_imported_layers(data)
        assert "L4" in layers
        assert "L6_translation" in layers
        assert "L1" not in layers


# ──────────────────────────────────────
# TestRoundTrip — Export → Import 순환
# ──────────────────────────────────────


class TestRoundTrip:
    """Export → Import → 재Export 순환 검증."""

    def test_roundtrip_text_preserved(self, tmp_path):
        """Export → Import 후 L4 텍스트 내용이 보존된다."""
        from core.snapshot import build_snapshot, create_work_from_snapshot

        lib, doc_id, interp_id = _make_library(tmp_path)

        # 1차 Export
        snapshot1 = build_snapshot(lib, doc_id, interp_id)

        # Import
        result = create_work_from_snapshot(lib, snapshot1)

        # 2차 Export (Import된 Work에서)
        snapshot2 = build_snapshot(lib, result["doc_id"], result["interp_id"])

        # L4 텍스트 비교
        text1 = snapshot1["original"]["layers"]["L4_text"]["pages"][0]["text"]
        text2 = snapshot2["original"]["layers"]["L4_text"]["pages"][0]["text"]
        assert text1 == text2

    def test_roundtrip_l3_blocks_preserved(self, tmp_path):
        """Export → Import 후 L3 block_id가 보존된다."""
        from core.snapshot import build_snapshot, create_work_from_snapshot

        lib, doc_id, interp_id = _make_library(tmp_path)
        snapshot1 = build_snapshot(lib, doc_id, interp_id)
        result = create_work_from_snapshot(lib, snapshot1)
        snapshot2 = build_snapshot(lib, result["doc_id"], result["interp_id"])

        blocks1 = snapshot1["original"]["layers"]["L3_layout"]["pages"][0]["blocks"]
        blocks2 = snapshot2["original"]["layers"]["L3_layout"]["pages"][0]["blocks"]
        ids1 = [b["block_id"] for b in blocks1]
        ids2 = [b["block_id"] for b in blocks2]
        assert ids1 == ids2
