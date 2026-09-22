"""승격 임계가 실측 무게를 벗어나는 경로의 재현 시험."""

from core.promotion import evaluate_promotion
import pytest
from core import entity
from core import entity_id_map
from core.promotion import gather_sources


def test_rounding_promotes_weight_below_threshold():
    """입력 weight=2.99996 -> 잘못된 출력 effective_weight=3.0, eligible=True."""
    verdict = evaluate_promotion([{"unit_id": "u1", "weight": 2.99996}])
    assert verdict["eligible"] is False, verdict


def test_duplicate_unit_is_counted_twice():
    """입력 동일 u1의 weight=2.1 두 번 -> 잘못된 출력 effective_weight=4.2, eligible=True."""
    source = {"unit_id": "u1", "weight": 2.1, "measured": True}
    verdict = evaluate_promotion([source, dict(source)])
    assert verdict["eligible"] is False, verdict


def test_unmeasured_source_can_supply_promotion_weight():
    """입력 measured=False, weight=3 -> 잘못된 출력 eligible=True, unmeasured_count=1."""
    verdict = evaluate_promotion([{"unit_id": "u1", "weight": 3, "measured": False}])
    assert verdict["eligible"] is False, verdict


def test_default_promotion_creates_concept_with_ineligible_zero_weight(monkeypatch, tmp_path):
    """입력 L4 없음, weight 없음, require_weight 생략 -> eligible=False인데 Concept 생성 호출."""
    tag = {"id": "t1", "surface": "x", "block_id": "u1"}
    monkeypatch.setattr(entity, "get_entity", lambda *args: tag)
    monkeypatch.setattr(entity, "list_entities", lambda *args: [tag])
    monkeypatch.setattr(entity, "_unit_view", lambda *args: [])
    created = []

    def capture_create(*args):
        """입력 생성 인수를 기록하고 빈 저장 결과를 반환하여 실제 파일 쓰기를 피한다."""
        created.append(args[-1])
        return {}

    monkeypatch.setattr(entity, "create_entity", capture_create)
    monkeypatch.setattr(entity_id_map, "record_mapping", lambda *args, **kwargs: None)
    try:
        entity.promote_tag_to_concept(tmp_path, "t1")
    except ValueError:
        pass
    assert not created, created


def test_infinite_confidence_turns_one_occurrence_into_infinite_weight(monkeypatch, tmp_path):
    """입력 L4의 x 1회, confidence=inf, 명시 무게 없음 -> weight=inf, eligible=True."""
    tag = {"id": "t1", "surface": "x", "block_id": "u1", "confidence": float("inf")}
    monkeypatch.setattr(entity, "list_entities", lambda *args: [tag])
    monkeypatch.setattr(entity, "_unit_view", lambda *args: [{"id": "u1", "original_text": "x"}])
    sources = gather_sources(tmp_path, "x")
    verdict = evaluate_promotion(sources)
    assert verdict["eligible"] is False, (sources, verdict)


@pytest.mark.parametrize("weight", [float("inf"), "1e309"])
def test_nonfinite_metadata_weight_promotes_without_confirmed_text(monkeypatch, tmp_path, weight):
    """입력 L4 없음, metadata.weight=inf 또는 1e309 문자열 -> weight=inf, eligible=True."""
    tag = {"id": "t1", "surface": "x", "block_id": "u1", "metadata": {"weight": weight}}
    monkeypatch.setattr(entity, "list_entities", lambda *args: [tag])
    monkeypatch.setattr(entity, "_unit_view", lambda *args: [])
    sources = gather_sources(tmp_path, "x")
    verdict = evaluate_promotion(sources)
    assert verdict["eligible"] is False, (sources, verdict)


def test_renamed_concept_borrows_other_surface_weight(monkeypatch, tmp_path):
    """입력 y Tag의 L4 빈도 0, label=x, 다른 x Tag의 빈도 3 -> require_weight=True인데 생성 호출."""
    target = {"id": "t1", "surface": "y", "block_id": "u1", "confidence": 1.0}
    other = {"id": "t2", "surface": "x", "block_id": "u1", "confidence": 1.0}
    monkeypatch.setattr(entity, "get_entity", lambda *args: target)
    monkeypatch.setattr(entity, "list_entities", lambda *args: [target, other])
    monkeypatch.setattr(entity, "_unit_view", lambda *args: [{"id": "u1", "original_text": "xxx"}])
    created = []

    def capture_create(*args):
        """입력 생성 인수를 기록하고 빈 결과를 반환하여 저장 없이 판정 흐름을 검증한다."""
        created.append(args[-1])
        return {}

    monkeypatch.setattr(entity, "create_entity", capture_create)
    monkeypatch.setattr(entity_id_map, "record_mapping", lambda *args, **kwargs: None)
    try:
        entity.promote_tag_to_concept(tmp_path, "t1", label="x", require_weight=True)
    except ValueError:
        pass
    assert not created, created
