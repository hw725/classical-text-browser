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
        """확정본이 없으면 **재지 못한 것**이다 — Tag 수로 대신하지 않는다.

        이 시험은 한 번 **헛통과했다.** 예전에는 Tag 30개를 서로 다른 단위 30개에
        하나씩 흩어 놓고 「닫힌다」를 확인했는데, 그 배치에서만 무게가 1.0으로
        바닥에 깔렸다. 코드는 확정본이 없으면 `Tag 수`로 떨어지고 있었으므로
        **같은 단위에 Tag 셋을 붙이면 무게 3.0으로 임계를 그대로 넘었다** —
        8항이 막으려던 「개수로 세기」가 복원되는 자리였다(2026-09-21 독립 검증).

        그래서 지금은 **개수가 위력을 발휘할 수 있는 배치**로 잰다. 한 단위에
        몰아 주는 쪽과 흩뿌리는 쪽 둘 다 닫혀야 한다.
        """
        _, _, interp_path = _make_library(tmp_path)

        def _tags(unit_ids):
            for unit_id in unit_ids:
                create_entity(
                    interp_path,
                    "tag",
                    {
                        "id": str(uuid.uuid4()),
                        "block_id": unit_id,
                        "surface": "王戎",
                        "core_category": "person",
                        "confidence": 1.0,
                        "status": "draft",
                    },
                )

        # ① 한 단위에 Tag 다섯 — 개수로 세면 5.0이라 임계를 넘는다.
        crowded = str(uuid.uuid4())
        _tags([crowded] * 5)
        sources = gather_sources(interp_path, "王戎")
        assert len(sources) == 1
        assert sources[0]["measured"] is False, "확정본이 없으면 «재지 못함»이어야 한다"
        assert sources[0]["occurrences"] == 0
        verdict = evaluate_promotion(sources)
        assert verdict["eligible"] is False
        assert "재지 못했습니다" in verdict["reason"], verdict["reason"]

        # ② 흩뿌린 쪽도 닫힌다.
        _tags([str(uuid.uuid4()) for _ in range(30)])
        spread = gather_sources(interp_path, "王戎")
        assert len(spread) == 31
        assert evaluate_promotion(spread)["eligible"] is False

    def test_measured_zero_differs_from_unmeasured(self, tmp_path, monkeypatch):
        """확정본은 있는데 표면형이 안 나오는 것은 «정상적인 0»이다.

        둘을 같은 말로 답하면 연구자가 「확정본을 채우라」는 답을 못 받는다.
        """
        _, _, interp_path = _make_library(tmp_path)
        unit_id = str(uuid.uuid4())
        create_entity(
            interp_path,
            "tag",
            {
                "id": str(uuid.uuid4()),
                "block_id": unit_id,
                "surface": "王戎",
                "core_category": "person",
                "status": "draft",
            },
        )
        monkeypatch.setattr(
            entity_mod,
            "_unit_view",
            lambda _p: [{"id": unit_id, "original_text": "다른 글자만 있는 확정본"}],
        )
        sources = gather_sources(interp_path, "王戎")
        assert sources[0]["measured"] is True
        assert sources[0]["occurrences"] == 0
        verdict = evaluate_promotion(sources)
        assert verdict["eligible"] is False
        assert "재지 못했습니다" not in verdict["reason"], verdict["reason"]

    def test_unparsable_explicit_weight_does_not_crash(self, tmp_path):
        """Tag의 metadata.weight 오타가 승격 전체를 떨어뜨리면 안 된다."""
        _, _, interp_path = _make_library(tmp_path)
        create_entity(
            interp_path,
            "tag",
            {
                "id": str(uuid.uuid4()),
                "block_id": str(uuid.uuid4()),
                "surface": "王戎",
                "core_category": "person",
                "status": "draft",
                "metadata": {"weight": "high"},
            },
        )
        sources = gather_sources(interp_path, "王戎")  # 예외 없이 지나가야 한다
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


# ──────────────────────────────────────
# 6항 — 출력 구획은 벽에 가깝다 (범위는 주소다)
# ──────────────────────────────────────


class TestScopeIsAnAddress:
    def test_other_document_concept_is_excluded_not_ranked_down(self, tmp_path):
        """다른 문헌의 개념은 순위가 낮아지는 것이 아니라 «아예 나오지 않는다»."""
        _, _, interp_path = _make_library(tmp_path)
        mine = {"id": str(uuid.uuid4()), "label": "王戎", "scope_document": "doc_a",
                "status": "draft"}
        theirs = {"id": str(uuid.uuid4()), "label": "王戎", "scope_document": "doc_b",
                  "status": "draft"}
        everywhere = {"id": str(uuid.uuid4()), "label": "王戎", "scope_document": None,
                      "status": "draft"}
        for c in (mine, theirs, everywhere):
            create_entity(interp_path, "concept", c)

        got = {c["id"] for c in list_entities(
            interp_path, "concept", {"scope_document": "doc_a"}
        )}
        assert mine["id"] in got
        assert everywhere["id"] in got  # 전역은 모든 주소에 걸린다
        assert theirs["id"] not in got  # 다른 주소다

    def test_global_only_query_excludes_scoped(self, tmp_path):
        """전역만 물으면 문헌 범위를 가진 개념은 주소가 다르다."""
        _, _, interp_path = _make_library(tmp_path)
        scoped_c = {"id": str(uuid.uuid4()), "label": "가", "scope_document": "doc_a",
                    "status": "draft"}
        global_c = {"id": str(uuid.uuid4()), "label": "나", "scope_document": None,
                    "status": "draft"}
        for c in (scoped_c, global_c):
            create_entity(interp_path, "concept", c)
        got = {c["id"] for c in list_entities(interp_path, "concept", {"scope_document": None})}
        assert got == {global_c["id"]}

    def test_scope_does_not_sort(self):
        """거르기만 하고 정렬하지 않는다 — 정렬하면 «순위 가중치»가 된다."""
        from core.concept_scope import scoped

        items = [
            {"id": "1", "scope_document": None},
            {"id": "2", "scope_document": "doc_a"},
            {"id": "3", "scope_document": None},
        ]
        assert [c["id"] for c in scoped(items, "doc_a")] == ["1", "2", "3"]

    def test_collection_side_is_not_walled(self, tmp_path):
        """**입력 쪽에는 벽을 세우지 않는다** — 6항은 출력 쪽 규칙이다 (9항).

        수집을 구획으로 막으면 연합 자체가 일어나지 않는다. 이 시험이 깨지면
        누군가 6항을 gather_sources 에까지 밀어 넣은 것이다.
        """
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
        assert len(gather_sources(interp_path, "王戎", document_id="아무_문헌")) == 3

    def test_rule_side_is_written_down(self):
        from core.concept_scope import OUTPUT_SIDE_ONLY_NOTE

        assert "모으는 쪽" in OUTPUT_SIDE_ONLY_NOTE


# ──────────────────────────────────────
# 7항 — 파트너 수·집중도는 설계 근거가 아니다
# ──────────────────────────────────────


class TestPartnerCountIsNotEvidence:
    def test_verdict_is_invariant_to_noise_partners(self):
        """잡음 출처를 500개 더해도 판정이 흔들리지 않는다.

        파트너 수는 계통마다 45~282로 6배 차이났다 — 설계 근거로 쓸 수 없는
        값이다. 판정에 들어가면 그 편차가 그대로 임계가 된다.
        """
        real = [{"weight": 9}]
        assert evaluate_promotion(real)["eligible"] is True
        noisy = real + [{"weight": 1} for _ in range(500)]
        assert evaluate_promotion(noisy)["eligible"] is True

        weak = [{"weight": 1}]
        assert evaluate_promotion(weak)["eligible"] is False
        assert evaluate_promotion(weak * 500)["eligible"] is False

    def test_concentration_is_reported_not_decided_on(self):
        """집중도는 «보여주는 값»이지 «판정하는 값»이 아니다."""
        from core.promotion import METRICS_NOT_USED_FOR_VERDICT

        # 집중도만 다르고 실질 무게가 같은 두 묶음은 같은 판정을 받아야 한다.
        concentrated = [{"weight": 12}]
        spread = [{"weight": 4}, {"weight": 4}, {"weight": 4}]
        a, b = evaluate_promotion(concentrated), evaluate_promotion(spread)
        assert a["eligible"] == b["eligible"] is True
        assert a["metrics"]["top10_share"] != b["metrics"]["top10_share"]
        # 판정에 쓰지 않기로 한 수치가 이름으로 적혀 있다.
        assert "source_count" in METRICS_NOT_USED_FOR_VERDICT
        assert "top10_share" in METRICS_NOT_USED_FOR_VERDICT


# ──────────────────────────────────────
# 화면에서 부를 수 있는가 (한계 보완)
# ──────────────────────────────────────


class TestMergeIsReachableFromTheApp:
    def test_merge_route_exists(self):
        """병합 라우트가 실제로 붙어 있는지 — 장부는 병합이 일어나야 쌓인다."""
        from app.routers.interpretations import router

        paths = {r.path for r in router.routes}
        assert "/api/interpretations/{interp_id}/entities/concepts/merge" in paths

    def test_scope_query_param_exists(self):
        """목록 라우트가 scope 를 받는지 (6항의 주소 질의)."""
        import inspect

        from app.routers.interpretations import api_list_entities

        assert "scope" in inspect.signature(api_list_entities).parameters


class TestLedgerIsVisibleInLists:
    """목록에도 장부가 반영되는가 (2026-09-21 브라우저 검증에서 찾은 결함).

    `get_entity`만 장부를 보고 `list_entities`는 보지 않았다. 그래서 화면의 엔티티
    «목록»에서는 이미 합쳐진 개념에 「합치기」 단추가 그대로 남고 «→ 새 ID» 표시도
    뜨지 않았다. 상태가 deprecated 인 것과 «합쳐졌다»는 것은 다른 사실이라
    상태로는 대신할 수 없다.
    """

    def test_list_shows_superseded_by(self, tmp_path):
        _, _, interp_path = _make_library(tmp_path)
        old_id = _concept(interp_path, "王戎")
        new_id = _concept(interp_path, "王戎(정리)")
        merge_concepts(interp_path, [old_id], new_id)

        by_id = {c["id"]: c for c in list_entities(interp_path, "concept")}
        assert by_id[old_id]["superseded_by"] == new_id
        assert by_id[old_id]["supersede_chain"] == [old_id, new_id]
        # 남은 쪽에는 붙지 않는다 — 대체된 것에만 붙는다.
        assert "superseded_by" not in by_id[new_id]

    def test_list_follows_a_chain(self, tmp_path):
        _, _, interp_path = _make_library(tmp_path)
        a, b, c = (_concept(interp_path, f"개념{i}") for i in "ABC")
        merge_concepts(interp_path, [a], b)
        merge_concepts(interp_path, [b], c)
        by_id = {x["id"]: x for x in list_entities(interp_path, "concept")}
        assert by_id[a]["superseded_by"] == c

    def test_empty_ledger_costs_nothing(self, tmp_path):
        """장부가 비면 목록을 손대지 않는다 — 없는 파일을 엔티티마다 읽지 않는다."""
        _, _, interp_path = _make_library(tmp_path)
        _concept(interp_path, "혼자")
        listed = list_entities(interp_path, "concept")
        assert all("superseded_by" not in c for c in listed)


class TestInjectedKeysNeverReachDisk:
    """조회가 덧붙인 `superseded_by`가 저장으로 돌아가지 않는가.

    왜 위험한가: `get_entity`·`list_entities`가 «지금 어디를 보라»를 덧붙이는데,
    concept·relation 스키마는 `additionalProperties: false`다. 읽은 것을 그대로
    저장하는 경로가 하나라도 있으면 그 순간 검증이 터지거나, 더 나쁘게는 장부가
    아니라 엔티티 파일에 대체 정보가 눌러앉아 장부와 두 벌이 된다.

    (2026-09-21 Codex 교차검증이 「병합 후 엔티티 저장 경로」를 의심 지점으로
    지목했으나 크레딧이 끊겨 확인하지 못했다. 그 자리를 여기서 직접 잰다.)
    """

    def test_update_after_merge_does_not_persist_the_annotation(self, tmp_path):
        from core.entity import update_entity

        _, _, interp_path = _make_library(tmp_path)
        old_id = _concept(interp_path, "王戎")
        new_id = _concept(interp_path, "王戎(정리)")
        merge_concepts(interp_path, [old_id], new_id)

        # 조회에는 붙는다.
        assert get_entity(interp_path, "concept", old_id)["superseded_by"] == new_id

        # 그 뒤 상태를 한 번 더 옮겨도 파일에는 들어가지 않는다.
        update_entity(interp_path, "concept", old_id, {"status": "archived"})
        raw = json.loads(
            (interp_path / "core_entities" / "concepts" / f"{old_id}.json").read_text(
                encoding="utf-8"
            )
        )
        assert "superseded_by" not in raw
        assert "supersede_chain" not in raw
        assert raw["status"] == "archived"

    def test_remerging_an_already_merged_concept_keeps_the_ledger_truthful(self, tmp_path):
        """이미 합쳐진 개념을 또 합쳐도 장부가 거짓이 되지 않는다."""
        _, _, interp_path = _make_library(tmp_path)
        a, b, c = (_concept(interp_path, f"개념{i}") for i in "ABC")
        merge_concepts(interp_path, [a], b)
        # a 는 이미 deprecated 이므로 상태 전이는 일어나지 않고 장부만 갱신된다.
        result = merge_concepts(interp_path, [a], c, note="다시 합침")
        assert result["merged"] == [a]
        assert resolve_id(interp_path, "concept", a)["id"] == c
        # 같은 (종류, 옛 id, 고리) 는 한 줄로 갱신된다 — 두 갈래가 생기지 않는다.
        rows = [
            e
            for e in load_id_map(interp_path)["entries"]
            if e["old_id"] == a and e["relation"] == "superseded_by"
        ]
        assert len(rows) == 1 and rows[0]["new_id"] == c


class TestWeightReadingIsRobust:
    """무게를 읽다가 이상한 값을 만나도 «열리지» 않는다.

    승격은 무게가 커질수록 열리므로, 읽기 실패가 큰 값으로 떨어지면 안 된다.
    """

    def test_nan_and_negative_fail_closed(self):
        from core.promotion import source_weight

        assert source_weight({"weight": float("nan")}) == 0.0
        assert source_weight({"weight": -10}) == 0.0
        assert source_weight({"weight": "숫자가 아님"}) == 0.0
        assert source_weight({}) == 0.0

    def test_boolean_weight_stays_in_the_noise_floor(self):
        """`True`가 무게로 들어와도 1.0이라 잡음 바닥 아래다."""
        from core.promotion import source_weight

        assert source_weight({"weight": True}) == 1.0
        assert evaluate_promotion([{"weight": True} for _ in range(50)])["eligible"] is False


class TestEveryReadDoorSeesTheLedger:
    """**읽기 문 전수**로 장부를 본다 (2026-09-21, 두 세션의 사각지대).

    왜 이 모양인가: 2항을 `get_entity`로만 재고 통과라고 적었는데, 같은 규칙을
    나눠 쓰는 `list_entities`가 장부를 안 봐서 화면 목록에서 합쳐진 개념이
    티가 나지 않았다. 시험 47건이 전부 초록이었다 — 아무도 그 문을 재지 않았다.

    문을 하나씩 재는 시험은 **넷째 문이 생기면 또 조용히 빠진다.** 그래서
    `QUERY_SURFACE`(3항이 못 박아 둔 읽기 문 목록)를 돌면서 전부 확인하고,
    「이 문은 픽스처로 못 닿았다」는 이유로 넘어가지 않는다 — 넘어가면
    헛통과가 되어 처음 그 결함을 놓친 것과 같은 일이 된다.

    문마다 검증 방식이 둘이다:
      - **직접**: 그 문으로 읽어 `superseded_by`가 붙는지 본다.
      - **위임**: 그 문이 스스로 파일을 읽지 않고 다른 문을 거치는 경우,
        실제로 거치는지를 확인한다. 거치면 주석은 자동으로 따라온다.
    """

    #: 위임으로 검증하는 문과, 무엇에 위임해야 하는가.
    DELEGATING_DOORS = {"list_entities_for_page": "list_entities"}

    def test_query_surface_is_fully_covered(self):
        """모든 읽기 문이 «직접» 또는 «위임» 중 하나로 덮여 있어야 한다.

        읽기 문을 늘리면 여기서 먼저 깨진다 — 늘린 사람이 장부를 봐야 하는지
        판단하고 이 시험에 자리를 만들게 하는 것이 목적이다.
        """
        direct = {"get_entity", "list_entities"}
        covered = direct | set(self.DELEGATING_DOORS)
        assert covered == set(entity_mod.QUERY_SURFACE), (
            "읽기 문이 늘었는데 장부 시험이 따라가지 않았다. "
            "direct 에 더하거나 DELEGATING_DOORS 에 위임 대상을 적어라 (D-128 2항)."
        )

    def test_direct_doors_mark_the_merged_concept(self, tmp_path):
        """직접 읽는 문 둘은 합쳐진 개념에 표시를 붙인다."""
        _, _, interp_path = _make_library(tmp_path)
        old_id = _concept(interp_path, "王戎")
        new_id = _concept(interp_path, "王戎(정리)")
        merge_concepts(interp_path, [old_id], new_id)

        assert get_entity(interp_path, "concept", old_id)["superseded_by"] == new_id

        listed = next(
            c for c in list_entities(interp_path, "concept") if c["id"] == old_id
        )
        assert listed["superseded_by"] == new_id

    def test_page_door_delegates_instead_of_reading_files_itself(self, tmp_path, monkeypatch):
        """쪽 조회는 스스로 파일을 읽지 않고 `list_entities`를 거친다.

        왜 직접 재지 않는가: 쪽 조회가 개념을 돌려주려면 단위·태그·관계가
        얽힌 상태가 필요해서, 픽스처로 닿지 못하면 «못 찾았으니 넘어감»이 되어
        헛통과한다. 대신 **파일을 자기가 읽지 않는다**는 구조를 확인한다 —
        `list_entities`를 거치는 한 장부 주석은 자동으로 따라온다.
        """
        _, _, interp_path = _make_library(tmp_path)
        _concept(interp_path, "王戎")

        seen: list[str] = []
        original = entity_mod.list_entities

        def _spy(path, entity_type, filters=None):
            seen.append(entity_type)
            return original(path, entity_type, filters)

        monkeypatch.setattr(entity_mod, "list_entities", _spy)
        entity_mod.list_entities_for_page(interp_path, "test_doc", 1)

        # 장부가 붙어야 하는 종류를 전부 그 문으로 읽었는가.
        for entity_type in ("concept", "agent", "relation", "tag"):
            assert entity_type in seen, (
                f"쪽 조회가 '{entity_type}'을 list_entities 를 거치지 않고 읽는다 — "
                "그러면 장부 주석이 빠진다 (D-128 2항)."
            )


class TestChainFollowingHasOneImplementation:
    """고리 따라가기가 한 곳에만 있는가 (D-128 2항의 구조 위생).

    처음에는 `resolve_id`와 `_annotate_superseded`가 같은 규칙을 각각 구현했다.
    그래서 이미 갈라져 있었다 — 한쪽은 순환을 만나면 경고를 남기고 다른 쪽은
    조용히 멈췄다. 이 저장소가 D-127에서 「기능마다 파서를 복제하면 한쪽만
    고쳐진다」고 적어 둔 것과 같은 자리다.

    지금은 `entity_id_map.follow_chain` 하나가 정본이다. 이 시험은 두 경로가
    **모든 경우에 같은 답**을 내는지 잰다 — 누군가 한쪽만 고치면 깨진다.
    """

    def _both_paths(self, interp_path, entity_id: str):
        """같은 id를 두 경로로 읽어 (단건 조회, 목록) 결과를 돌려준다."""
        single = resolve_id(interp_path, "concept", entity_id)
        listed = next(
            (c for c in list_entities(interp_path, "concept") if c["id"] == entity_id), None
        )
        return single, listed

    def test_straight_chain_agrees(self, tmp_path):
        _, _, interp_path = _make_library(tmp_path)
        a, b, c = (_concept(interp_path, f"개념{i}") for i in "ABC")
        merge_concepts(interp_path, [a], b)
        merge_concepts(interp_path, [b], c)

        single, listed = self._both_paths(interp_path, a)
        assert single["id"] == listed["superseded_by"] == c
        assert single["chain"] == listed["supersede_chain"] == [a, b, c]

    def test_cycle_agrees(self, tmp_path):
        """장부가 잘못 적혀 순환이 생겨도 두 경로가 같은 자리에서 멈춘다."""
        _, _, interp_path = _make_library(tmp_path)
        a = _concept(interp_path, "A")
        b = _concept(interp_path, "B")
        record_mapping(interp_path, entity_type="concept", old_id=a, new_id=b)
        record_mapping(interp_path, entity_type="concept", old_id=b, new_id=a)

        single, listed = self._both_paths(interp_path, a)
        assert single["id"] == listed["superseded_by"]
        assert single["chain"] == listed["supersede_chain"]

    def test_no_ledger_agrees(self, tmp_path):
        """장부가 비면 둘 다 «대체되지 않았다»로 답한다."""
        _, _, interp_path = _make_library(tmp_path)
        a = _concept(interp_path, "혼자")
        single, listed = self._both_paths(interp_path, a)
        assert single["superseded"] is False
        assert "superseded_by" not in listed

    def test_only_one_module_walks_the_chain(self):
        """`while current in lookup` 이 정본 한 곳에만 있어야 한다.

        복제가 다시 생기면 여기서 걸린다 — 갈라짐은 갈라진 뒤에는 잘 안 보인다.
        """
        import inspect
        from pathlib import Path as _Path

        from core import entity_id_map

        core_dir = _Path(inspect.getfile(entity_id_map)).parent
        walkers = [
            f.name
            for f in core_dir.glob("*.py")
            if "while current in lookup" in f.read_text(encoding="utf-8")
        ]
        assert walkers == ["entity_id_map.py"], (
            f"고리 따라가기가 여러 곳에 있다: {walkers}. "
            "entity_id_map.follow_chain 을 쓰도록 모으라 (D-128 2항)."
        )


class TestLedgerCannotBeCorrupted:
    """장부가 거짓이 되는 두 경로를 막는다 (2026-09-21 독립 검증 ②·④).

    2항의 존재 이유는 「구 ID를 죽이지 않는다」인데, 아래 둘은 장부 자체를
    쓸모없게 만든다 — 하나는 정본을 없애고 하나는 파일을 날린다.
    """

    def test_merging_into_an_already_merged_target_is_refused(self, tmp_path):
        """B→A 뒤 A→B를 허용하면 «대체되지 않은» 개념이 하나도 남지 않는다.

        조회는 순환을 끊어 멎지는 않지만, 정본이 사라지면 화면에서 되돌릴 길이
        없다 — 삭제 금지 규약 때문에 장부 항목을 지우는 길도 없기 때문이다.
        """
        _, _, interp_path = _make_library(tmp_path)
        a = _concept(interp_path, "A")
        b = _concept(interp_path, "B")
        merge_concepts(interp_path, [b], a)  # B → A

        with pytest.raises(ValueError, match="이미"):
            merge_concepts(interp_path, [a], b)  # A → B 는 순환이다

        # 정본이 남아 있다 — A 는 여전히 «대체되지 않은» 개념이다.
        listed = {c["id"]: c for c in list_entities(interp_path, "concept")}
        assert "superseded_by" not in listed[a]
        assert listed[b]["superseded_by"] == a

    def test_duplicate_source_ids_are_counted_once(self, tmp_path):
        """같은 id를 두 번 줘도 «2건 합쳤다»고 말하지 않는다."""
        _, _, interp_path = _make_library(tmp_path)
        a = _concept(interp_path, "A")
        b = _concept(interp_path, "B")
        result = merge_concepts(interp_path, [a, a], b)
        assert result["merged"] == [a]

    def test_broken_ledger_is_not_overwritten(self, tmp_path):
        """읽지 못한 장부 위에 새로 쓰지 않는다 — 쓰면 옛 매핑이 영영 사라진다.

        읽기는 빈 장부로 이어 가되(서고는 열려야 한다) **쓰기는 막는다.**
        이 방어가 없으면 장부가 한 번 깨진 뒤의 첫 병합이 파일을 새로 써서
        그때까지의 모든 구 ID → 신 ID 매핑을 지운다.
        """
        _, _, interp_path = _make_library(tmp_path)
        a = _concept(interp_path, "A")
        b = _concept(interp_path, "B")
        merge_concepts(interp_path, [a], b)

        path = interp_path / "core_entities" / "id_map.json"
        good = path.read_text(encoding="utf-8")
        path.write_text("{ 이건 JSON 이 아니다", encoding="utf-8")

        c = _concept(interp_path, "C")
        with pytest.raises(OSError, match="장부"):
            merge_concepts(interp_path, [c], b)

        # 파일은 손대지 않은 그대로다 — 되살릴 수 있다.
        assert path.read_text(encoding="utf-8") == "{ 이건 JSON 이 아니다"
        path.write_text(good, encoding="utf-8")
        assert resolve_id(interp_path, "concept", a)["id"] == b
