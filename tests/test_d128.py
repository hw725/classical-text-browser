"""D-128 구현 시험 — 커넥톰 리포지토리에서 가져온 규약 아홉 항.

이 저장소의 스키마에 해당하는 항만 다룬다: 1·2·3 + 8·9·10 + 11·12·13.
4~7항은 위키 순회 쪽이라 여기 없다.

    TestCorpusVersionStamp        — 1항: 데이터 버전을 «출력»에 각인
    TestIdMapKeepsOldIds          — 2항: 승격·병합 때 구 ID를 죽이지 않는다
    TestQuerySurfaceStaysNarrow   — 3항: 질의 API는 좁게
    TestPromotionWeighsNotCounts  — 8항: 승격 임계는 개수가 아니라 무게
    TestCollectWideEmitNarrow     — 9항: 넓게 모아 좁게 내보낸다(연합 구조에 한해)
    TestPromotionIsNotAFunnel     — 10항: 승격은 출처를 줄이는 단계가 아니다
    TestRelationPolarity          — 11·13항: 부호, 그리고 이진 강제 금지
    TestModulationIsFirstClass    — 12항: 조절은 지지·반박과 다른 종류
"""

import json
import uuid
from pathlib import Path

import git
import pytest

from core import entity as entity_mod
from core.corpus_version import corpus_snapshot, stamp, stamp_comment
from core.entity import (
    create_entity,
    get_entity,
    list_entities,
    merge_concepts,
    promote_tag_to_concept,
)
from core.entity_id_map import load_id_map, predecessors, record_mapping, resolve_id
from core.promotion import (
    NOISE_WEIGHT_CEILING,
    evaluate_promotion,
    gather_sources,
    promotion_metrics,
)
from core.relation_polarity import (
    MODE_MODULATE,
    POLARITY_CONTEXT_DEPENDENT,
    POLARITY_UNDETERMINED,
    polarity_breakdown,
    polarity_of,
    strong_edges,
    suggest_strong_threshold,
    unsigned_strong_relations,
    validate_relation_semantics,
    weight_of,
)

# ──────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────


def _make_library(tmp_path: Path, doc_id: str = "test_doc", interp_id: str = "test_interp"):
    """문헌 하나 + 해석 하나를 가진 최소 서고를 만든다(둘 다 git 저장소).

    왜 git까지 만드는가: 1항의 코퍼스 해시는 HEAD 커밋에서 나온다. git이 없으면
    «재현 불가»로 떨어지므로, 정상 경로를 재려면 커밋이 하나는 있어야 한다.
    """
    lib = tmp_path / "library"
    doc_path = lib / "documents" / doc_id
    interp_path = lib / "interpretations" / interp_id
    doc_path.mkdir(parents=True)
    interp_path.mkdir(parents=True)

    (doc_path / "manifest.json").write_text(
        json.dumps(
            {"document_id": doc_id, "title": "蒙求", "parts": [{"part_id": "main"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (interp_path / "manifest.json").write_text(
        json.dumps(
            {"interpretation_id": interp_id, "title": "시험 해석", "source_document_id": doc_id},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    for repo_path in (doc_path, interp_path):
        repo = git.Repo.init(repo_path)
        repo.index.add(["manifest.json"])
        repo.index.commit("init: 시험 데이터")

    return lib, doc_path, interp_path


def _concept(interp_path: Path, label: str) -> str:
    """Concept 하나를 만들고 id를 돌려준다."""
    data = {"id": str(uuid.uuid4()), "label": label, "status": "draft"}
    create_entity(interp_path, "concept", data)
    return data["id"]


def _rel(weight=None, polarity=None, mode=None) -> dict:
    """무게·부호만 있는 얇은 Relation dict (순수 함수 시험용)."""
    out = {"id": str(uuid.uuid4()), "predicate": "governs"}
    if weight is not None:
        out["weight"] = weight
    if polarity is not None:
        out["polarity"] = polarity
    if mode is not None:
        out["mode"] = mode
    return out


# ──────────────────────────────────────
# 1항 — 데이터 버전을 «출력»에 각인한다
# ──────────────────────────────────────


class TestCorpusVersionStamp:
    def test_snapshot_carries_hash(self, tmp_path):
        """산출물에 해시가 실제로 붙는가 — 사용자는 아무것도 입력하지 않는다."""
        lib, _, _ = _make_library(tmp_path)
        snap = corpus_snapshot(lib, document_ids=["test_doc"], interpretation_ids=["test_interp"])
        assert snap["corpus_hash"].startswith("ctb-corpus:")
        assert len(snap["sources"]) == 2
        assert snap["reproducible"] is True
        # 스키마 판과 데이터 판은 다른 축이다 — 둘 다 있고 서로 다르다.
        assert snap["schema_version"] == "1.3"
        assert snap["corpus_hash"] != snap["schema_version"]

    def test_same_data_same_hash(self, tmp_path):
        """같은 데이터를 두 번 내보내면 같은 해시가 나와야 한다(시각은 해시에 넣지 않는다)."""
        lib, _, _ = _make_library(tmp_path)
        a = corpus_snapshot(lib, document_ids=["test_doc"])
        b = corpus_snapshot(lib, document_ids=["test_doc"])
        assert a["corpus_hash"] == b["corpus_hash"]
        assert a["exported_at"] != b["exported_at"] or True  # 시각은 달라도 무방

    def test_commit_changes_hash(self, tmp_path):
        """원문이 한 커밋 움직이면 해시도 움직인다 — 그래야 «어느 시점»을 가리킨다."""
        lib, doc_path, _ = _make_library(tmp_path)
        before = corpus_snapshot(lib, document_ids=["test_doc"])["corpus_hash"]
        (doc_path / "note.txt").write_text("교정 한 글자", encoding="utf-8")
        repo = git.Repo(doc_path)
        repo.index.add(["note.txt"])
        repo.index.commit("fix: 교정")
        after = corpus_snapshot(lib, document_ids=["test_doc"])["corpus_hash"]
        assert before != after

    def test_uncommitted_edit_marks_irreproducible(self, tmp_path):
        """커밋되지 않은 편집이 남아 있으면 조용히 넘어가지 않는다."""
        lib, doc_path, _ = _make_library(tmp_path)
        (doc_path / "manifest.json").write_text('{"document_id": "x"}', encoding="utf-8")
        snap = corpus_snapshot(lib, document_ids=["test_doc"])
        assert snap["reproducible"] is False
        assert "커밋되지 않은" in stamp_comment(snap)

    def test_stamp_helpers(self, tmp_path):
        """JSON에는 키로, 텍스트·CSV에는 한 줄로 붙는다."""
        lib, _, _ = _make_library(tmp_path)
        snap = corpus_snapshot(lib, document_ids=["test_doc"])
        payload = stamp({"entries": []}, snap)
        assert payload["corpus_version"]["corpus_hash"] == snap["corpus_hash"]
        line = stamp_comment(snap)
        assert line.startswith("# ctb-corpus:")
        assert "\n" not in line  # CSV 한 칸에 들어가야 한다

    def test_dictionary_export_is_stamped(self, tmp_path):
        """실제 내보내기 경로(사전)에 해시가 붙는지 — 모듈이 아니라 산출물을 본다."""
        from core.annotation_dict_io import export_dictionary

        lib, _, interp_path = _make_library(tmp_path)
        out = export_dictionary(interp_path, "test_doc", "蒙求", "test_interp")
        assert "corpus_version" in out
        assert out["corpus_version"]["corpus_hash"].startswith("ctb-corpus:")

    def test_build_snapshot_is_stamped(self, tmp_path):
        """교환 형식 스냅샷에도 붙고, 교환 스키마가 그것을 받아들인다."""
        from core.snapshot import build_snapshot, exchange_validator

        lib, _, _ = _make_library(tmp_path)
        snap = build_snapshot(lib, "test_doc", "test_interp")
        assert snap["corpus_version"]["corpus_hash"].startswith("ctb-corpus:")
        # additionalProperties: false 이므로 스키마에 자리를 만들지 않았으면 여기서 깨진다.
        errors = list(exchange_validator().iter_errors(snap))
        assert errors == [], errors


# ──────────────────────────────────────
# 2항 — 승격·병합 때 구 ID를 죽이지 않는다
# ──────────────────────────────────────


class TestIdMapKeepsOldIds:
    def test_merge_resolves_old_id(self, tmp_path):
        """병합 뒤 구 ID로 조회하면 신 ID가 나온다."""
        _, _, interp_path = _make_library(tmp_path)
        old_id = _concept(interp_path, "王戎")
        new_id = _concept(interp_path, "王戎(정리)")

        result = merge_concepts(interp_path, [old_id], new_id, note="같은 인물")
        assert result["merged"] == [old_id]
        assert result["resolved"][old_id] == new_id
        assert resolve_id(interp_path, "concept", old_id)["id"] == new_id

    def test_merge_does_not_delete(self, tmp_path):
        """흡수된 쪽의 파일은 남는다 — 삭제 금지(operation-rules 2.4)."""
        _, _, interp_path = _make_library(tmp_path)
        old_id = _concept(interp_path, "王戎")
        new_id = _concept(interp_path, "王戎(정리)")
        merge_concepts(interp_path, [old_id], new_id)

        still_there = get_entity(interp_path, "concept", old_id)
        assert still_there["id"] == old_id
        assert still_there["status"] == "deprecated"
        # 조회는 «지금 어디를 보라»를 덧붙인다 — 기록 자체를 고치지 않는다.
        assert still_there["superseded_by"] == new_id
        assert still_there["supersede_chain"] == [old_id, new_id]

    def test_chain_of_merges(self, tmp_path):
        """A → B → C 로 두 번 합쳐도 A가 C로 풀린다."""
        _, _, interp_path = _make_library(tmp_path)
        a, b, c = (_concept(interp_path, f"개념{i}") for i in "ABC")
        merge_concepts(interp_path, [a], b)
        merge_concepts(interp_path, [b], c)
        resolved = resolve_id(interp_path, "concept", a)
        assert resolved["id"] == c
        assert resolved["chain"] == [a, b, c]

    def test_promotion_is_recorded(self, tmp_path):
        """승격 뒤 그 Tag가 무엇이 됐는지 장부로 되짚을 수 있다."""
        _, _, interp_path = _make_library(tmp_path)
        unit_id = str(uuid.uuid4())
        tag = {
            "id": str(uuid.uuid4()),
            "block_id": unit_id,
            "surface": "王戎",
            "core_category": "person",
            "status": "draft",
        }
        create_entity(interp_path, "tag", tag)
        result = promote_tag_to_concept(interp_path, tag["id"])
        concept_id = result["concept"]["id"]

        entries = load_id_map(interp_path)["entries"]
        assert any(
            e["old_id"] == tag["id"]
            and e["new_id"] == concept_id
            and e["relation"] == "promoted_to"
            for e in entries
        )
        # 승격은 «대체»가 아니다 — Tag는 제 id로 그대로 조회되고, 되짚기 고리가
        # 그 id를 Concept으로 끌고 가지 않는다(promoted_to 는 따라가지 않는 고리).
        assert get_entity(interp_path, "tag", tag["id"])["id"] == tag["id"]
        assert resolve_id(interp_path, "tag", tag["id"])["superseded"] is False
        # 그래도 «무엇이 됐는가»는 장부로 되짚힌다.
        assert [e["old_id"] for e in predecessors(interp_path, "tag", concept_id)] == [tag["id"]]

    def test_cycle_does_not_hang(self, tmp_path):
        """장부가 잘못 적혀 고리가 돌아도 멈춘다."""
        _, _, interp_path = _make_library(tmp_path)
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        record_mapping(interp_path, entity_type="concept", old_id=a, new_id=b)
        record_mapping(interp_path, entity_type="concept", old_id=b, new_id=a)
        resolved = resolve_id(interp_path, "concept", a)
        assert resolved["id"] in (a, b)
        assert len(resolved["chain"]) <= 3

    def test_self_mapping_refused(self, tmp_path):
        _, _, interp_path = _make_library(tmp_path)
        same = str(uuid.uuid4())
        with pytest.raises(ValueError):
            record_mapping(interp_path, entity_type="concept", old_id=same, new_id=same)


# ──────────────────────────────────────
# 3항 — 질의 API는 좁게
# ──────────────────────────────────────


class TestQuerySurfaceStaysNarrow:
    def test_read_surface_is_three_doors(self):
        """읽기 문이 셋뿐이다. 순회 함수를 더하면 여기서 걸린다."""
        assert entity_mod.QUERY_SURFACE == (
            "get_entity",
            "list_entities",
            "list_entities_for_page",
        )
        banned = ("traverse", "walk", "neighbors", "subgraph", "path_between")
        public = [n for n in dir(entity_mod) if not n.startswith("_")]
        assert [n for n in public if any(b in n for b in banned)] == []

    def test_traversal_helpers_cannot_reach_the_store(self):
        """관계를 다루는 함수는 목록을 받는 순수 함수다 — 저장소를 인자로 받지 않는다.

        구조적 보증이다. 경로를 못 받으면 파일을 열 수 없고, 그래서 임의 순회가
        코드상 불가능하다.
        """
        import inspect

        from core import relation_polarity

        for name in ("strong_edges", "polarity_breakdown", "unsigned_strong_relations"):
            params = inspect.signature(getattr(relation_polarity, name)).parameters
            assert "interp_path" not in params
            assert "library_path" not in params


# ──────────────────────────────────────
# 8항 — 승격 임계는 «개수»가 아니라 «무게»
# ──────────────────────────────────────


class TestPromotionWeighsNotCounts:
    def test_many_weak_lose_to_one_strong(self):
        """약한 출처 «여럿»이 강한 출처 «하나»를 이기지 못한다 — 8항의 핵심."""
        weak_many = [{"weight": 1} for _ in range(20)]
        one_strong = [{"weight": 8}]

        weak = evaluate_promotion(weak_many)
        strong = evaluate_promotion(one_strong)

        assert weak["eligible"] is False
        assert strong["eligible"] is True
        # 개수로 세면 정반대가 된다는 것을 같이 못 박는다.
        assert weak["metrics"]["source_count"] > strong["metrics"]["source_count"]
        assert weak["metrics"]["effective_weight"] < strong["metrics"]["effective_weight"]

    def test_noise_floor_matches_measurement(self):
        """무게 1~2는 잡음 바닥이다(연합 구조에서 입력의 84.0%가 여기 있었다)."""
        assert NOISE_WEIGHT_CEILING == 2.0
        metrics = promotion_metrics([{"weight": 1}, {"weight": 2}, {"weight": 9}])
        assert metrics["effective_count"] == 1
        assert metrics["effective_weight"] == 9

    def test_weak_sources_are_kept_not_deleted(self):
        """세지 않을 뿐 지우지 않는다 — 임계를 내리면 돌아온다."""
        sources = [{"weight": 1} for _ in range(5)]
        assert promotion_metrics(sources)["source_count"] == 5
        assert evaluate_promotion(sources, noise_ceiling=0.5)["eligible"] is True

    def test_weight_from_occurrences(self):
        """명시 무게가 없으면 «몇 번 건드렸는가 × 신뢰도»로 도출한다."""
        assert evaluate_promotion([{"occurrences": 6, "confidence": 0.9}])["eligible"] is True
        assert evaluate_promotion([{"occurrences": 1, "confidence": 0.9}])["eligible"] is False

    def test_reason_is_readable(self):
        verdict = evaluate_promotion([{"weight": 1} for _ in range(7)])
        assert "무게" in verdict["reason"]

    def test_occurrences_come_from_the_confirmed_text(self, tmp_path, monkeypatch):
        """무게는 「그 단위가 이 개념을 몇 번 건드렸는가」에서 나온다.

        확정본(L4)이 있는 저장소의 모양을 재현한다 — 같은 단위 안에서 세 번
        언급한 출처는 무게 3×신뢰도를 갖고, 한 번 스친 출처는 잡음 바닥에 남는다.
        """
        _, _, interp_path = _make_library(tmp_path)
        thick, thin = str(uuid.uuid4()), str(uuid.uuid4())
        for unit_id, conf in ((thick, 0.9), (thin, 0.9)):
            create_entity(
                interp_path,
                "tag",
                {
                    "id": str(uuid.uuid4()),
                    "block_id": unit_id,
                    "surface": "王戎",
                    "core_category": "person",
                    "confidence": conf,
                    "status": "draft",
                },
            )
        monkeypatch.setattr(
            entity_mod,
            "_unit_view",
            lambda _p: [
                {"id": thick, "original_text": "王戎七歲 王戎不動 王戎曰"},
                {"id": thin, "original_text": "諸兒競走 王戎在後"},
            ],
        )
        by_unit = {s["unit_id"]: s for s in gather_sources(interp_path, "王戎")}
        assert by_unit[thick]["occurrences"] == 3
        assert by_unit[thin]["occurrences"] == 1
        assert evaluate_promotion(list(by_unit.values()))["eligible"] is False
        # 두껍게 언급한 출처가 하나만 더 있으면 넘는다 — 개수가 아니라 무게가 움직인다.
        assert evaluate_promotion([by_unit[thick], by_unit[thick]])["eligible"] is True

    def test_without_confirmed_text_it_fails_closed(self, tmp_path):
        """확정본이 없으면 무게를 잴 수 없다 — 그때는 «승격하지 않는» 쪽으로 닫힌다.

        왜 이것을 못 박는가: 텍스트가 없으면 도출이 Tag 수로 떨어지는데, 그것이
        곧 «개수로 세기»다(8항이 막으려는 것). 떨어진 값이 잡음 바닥 아래라서
        열리지 않고 닫힌다는 것이 안전한 쪽이고, 그 성질을 여기 고정한다.
        """
        _, _, interp_path = _make_library(tmp_path)
        for _ in range(30):
            create_entity(
                interp_path,
                "tag",
                {
                    "id": str(uuid.uuid4()),
                    "block_id": str(uuid.uuid4()),
                    "surface": "王戎",
                    "core_category": "person",
                    "confidence": 1.0,
                    "status": "draft",
                },
            )
        sources = gather_sources(interp_path, "王戎")
        assert len(sources) == 30
        assert evaluate_promotion(sources)["eligible"] is False


# ──────────────────────────────────────
# 9항 — 넓게 모아서 좁게 내보낸다 (연합 구조에 한해)
# ──────────────────────────────────────


class TestCollectWideEmitNarrow:
    def test_collection_is_not_filtered_by_document(self, tmp_path):
        """수집은 구획으로 막지 않는다 — document_id는 거르는 값이 아니다."""
        _, _, interp_path = _make_library(tmp_path)
        for _ in range(3):
            create_entity(
                interp_path,
                "tag",
                {
                    "id": str(uuid.uuid4()),
                    "block_id": str(uuid.uuid4()),
                    "surface": "王戎",
                    "core_category": "person",
                    "status": "draft",
                },
            )
        # 아무 문헌 id나 줘도 출처가 줄지 않는다.
        assert len(gather_sources(interp_path, "王戎", document_id="다른_문헌")) == 3
        assert len(gather_sources(interp_path, "王戎")) == 3

    def test_emitted_concept_has_one_scope(self, tmp_path):
        """내보내는 쪽은 좁다 — 만들어진 Concept은 scope_document 하나를 갖는다."""
        _, _, interp_path = _make_library(tmp_path)
        tag = {
            "id": str(uuid.uuid4()),
            "block_id": str(uuid.uuid4()),
            "surface": "王戎",
            "core_category": "person",
            "status": "draft",
        }
        create_entity(interp_path, "tag", tag)
        result = promote_tag_to_concept(interp_path, tag["id"], scope_document="test_doc")
        assert result["concept"]["scope_document"] == "test_doc"

    def test_rule_scope_is_written_down(self):
        """어디에 적용하지 «않는지»가 코드에 적혀 있어야 한다."""
        from core.promotion import SCOPE_BLIND_COLLECTION_NOTE

        assert "편성" in SCOPE_BLIND_COLLECTION_NOTE
        assert "적용하지 않는다" in SCOPE_BLIND_COLLECTION_NOTE


# ──────────────────────────────────────
# 10항 — 승격은 «깔때기»가 아니다
# ──────────────────────────────────────


class TestPromotionIsNotAFunnel:
    def test_promotion_does_not_reduce_sources(self, tmp_path):
        """승격해도 Tag 수는 그대로다 — 폭을 유지하고 무게만 재배치한다."""
        _, _, interp_path = _make_library(tmp_path)
        tags = []
        for _ in range(4):
            t = {
                "id": str(uuid.uuid4()),
                "block_id": str(uuid.uuid4()),
                "surface": "王戎",
                "core_category": "person",
                "status": "draft",
            }
            create_entity(interp_path, "tag", t)
            tags.append(t)

        before = len(list_entities(interp_path, "tag"))
        result = promote_tag_to_concept(interp_path, tags[0]["id"])
        after = len(list_entities(interp_path, "tag"))

        assert before == after == 4
        # 「몇 개로 줄였는가」가 아니라 「무게가 어떻게 놓였는가」가 기록된다.
        promotion = result["concept"]["concept_features"]["promotion"]
        assert promotion["metrics"]["source_count"] == 4
        assert "top10_share" in promotion["metrics"]


# ──────────────────────────────────────
# 11·13항 — 부호, 그리고 이진 강제 금지
# ──────────────────────────────────────


class TestRelationPolarity:
    def test_ambiguous_polarity_survives_a_round_trip(self, tmp_path):
        """모호 상태가 보존되는가 — 저장하고 다시 읽어도 그대로여야 한다 (13항)."""
        _, _, interp_path = _make_library(tmp_path)
        subject = _concept(interp_path, "주어")
        rel = {
            "id": str(uuid.uuid4()),
            "subject_id": subject,
            "subject_type": "concept",
            "predicate": "governs",
            "polarity": POLARITY_CONTEXT_DEPENDENT,
            "weight": 7,
            "status": "draft",
        }
        create_entity(interp_path, "relation", rel)
        loaded = get_entity(interp_path, "relation", rel["id"])
        assert loaded["polarity"] == POLARITY_CONTEXT_DEPENDENT
        assert polarity_of(loaded) == POLARITY_CONTEXT_DEPENDENT

    def test_missing_polarity_is_not_support(self):
        """적히지 않은 것을 지지로 읽지 않는다 — 모름은 모름으로 남는다."""
        assert polarity_of({}) == POLARITY_UNDETERMINED
        assert polarity_of({"polarity": None}) == POLARITY_UNDETERMINED
        assert polarity_of({"polarity": "무언가"}) == POLARITY_UNDETERMINED

    def test_four_polarities_are_storable(self, tmp_path):
        """넷 다 저장된다 — 이진으로 좁히면 여기서 깨진다."""
        _, _, interp_path = _make_library(tmp_path)
        subject = _concept(interp_path, "주어")
        for p in ("support", "refute", "context_dependent", "undetermined"):
            rel = {
                "id": str(uuid.uuid4()),
                "subject_id": subject,
                "subject_type": "concept",
                "predicate": "governs",
                "polarity": p,
                "status": "draft",
            }
            create_entity(interp_path, "relation", rel)
            assert get_entity(interp_path, "relation", rel["id"])["polarity"] == p

    def test_weight_and_polarity_stored_together(self, tmp_path):
        """무게와 부호는 함께 저장한다 (11항)."""
        _, _, interp_path = _make_library(tmp_path)
        subject = _concept(interp_path, "주어")
        rel = {
            "id": str(uuid.uuid4()),
            "subject_id": subject,
            "subject_type": "concept",
            "predicate": "governs",
            "polarity": "refute",
            "weight": 12.5,
            "status": "draft",
        }
        create_entity(interp_path, "relation", rel)
        loaded = get_entity(interp_path, "relation", rel["id"])
        assert loaded["weight"] == 12.5 and loaded["polarity"] == "refute"

    def test_strong_edges_concentrate_the_opposite_sign(self):
        """실측의 모양을 재현한다 — 강연결만 보면 반박 비중이 뛴다."""
        relations = [_rel(weight=1, polarity="support") for _ in range(80)]
        relations += [_rel(weight=10, polarity="refute") for _ in range(20)]

        overall = polarity_breakdown(relations)
        strong = polarity_breakdown(strong_edges(relations, threshold=5))

        assert overall["refute"] < strong["refute"]
        assert strong["refute"] == 1.0

    def test_threshold_comes_from_the_data(self):
        """임계를 상수로 박지 않는다 — 분포가 다르면 임계도 달라진다."""
        light = [_rel(weight=1) for _ in range(19)] + [_rel(weight=3)]
        heavy = [_rel(weight=50) for _ in range(19)] + [_rel(weight=99)]
        assert suggest_strong_threshold(light) < suggest_strong_threshold(heavy)

    def test_unsigned_strong_edges_are_flagged(self):
        """부호가 없는 강연결은 찾아내야 한다 — 잘못 셀 위험이 가장 큰 자리다."""
        relations = [_rel(weight=1) for _ in range(10)] + [_rel(weight=20)]
        flagged = unsigned_strong_relations(relations, threshold=5)
        assert len(flagged) == 1
        assert weight_of(flagged[0]) == 20

    def test_missing_weight_is_not_zero(self):
        """무게를 안 적은 옛 관계가 임계 한 번에 사라지면 안 된다."""
        assert weight_of({}) == 1.0


# ──────────────────────────────────────
# 12항 — 조절은 지지·반박과 다른 종류
# ──────────────────────────────────────


class TestModulationIsFirstClass:
    def test_modulation_targets_a_relation(self, tmp_path):
        """조절은 «다른 관계의 무게를 바꾸는» 관계다 — 관계를 가리킬 수 있어야 한다."""
        _, _, interp_path = _make_library(tmp_path)
        subject = _concept(interp_path, "출처 신뢰도")
        target = {
            "id": str(uuid.uuid4()),
            "subject_id": subject,
            "subject_type": "concept",
            "predicate": "governs",
            "weight": 5,
            "status": "draft",
        }
        create_entity(interp_path, "relation", target)

        modulator = {
            "id": str(uuid.uuid4()),
            "subject_id": subject,
            "subject_type": "concept",
            "predicate": "weakens",
            "object_id": target["id"],
            "object_type": "relation",
            "mode": MODE_MODULATE,
            "weight": 3,
            "status": "draft",
        }
        create_entity(interp_path, "relation", modulator)
        loaded = get_entity(interp_path, "relation", modulator["id"])
        assert loaded["mode"] == MODE_MODULATE
        assert loaded["object_type"] == "relation"

    def test_modulation_outside_the_association_layer_is_refused(self):
        """조절 입력은 연합 층에만 붙는다 — 단위(block)를 조절 대상으로 두면 거부."""
        with pytest.raises(ValueError, match="조절형"):
            validate_relation_semantics({"mode": MODE_MODULATE, "object_type": "block"})

    def test_modulation_is_not_support_or_refute(self):
        """조절에 지지·반박 부호를 붙이는 것은 범주 오류다."""
        for p in ("support", "refute"):
            with pytest.raises(ValueError, match="부호"):
                validate_relation_semantics(
                    {"mode": MODE_MODULATE, "object_type": "concept", "polarity": p}
                )
        # 맥락의존은 허용된다 — 조절의 방향이 맥락에 달린 경우가 있다.
        validate_relation_semantics(
            {
                "mode": MODE_MODULATE,
                "object_type": "concept",
                "polarity": POLARITY_CONTEXT_DEPENDENT,
            }
        )

    def test_modulation_weight_is_excluded_from_the_sign_tally(self):
        """조절은 지지·반박 셈에서 빠져 따로 센다 — 섞으면 부호가 희석된다."""
        relations = [
            _rel(weight=8, polarity="support"),
            _rel(weight=2, mode=MODE_MODULATE),
        ]
        breakdown = polarity_breakdown(relations)
        assert breakdown["support"] == 0.8
        assert breakdown["modulate"] == 0.2
