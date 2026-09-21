"""엔티티 편집기 화면 JS — 승격 기록 보존과 Relation 부호·무게 (D-128).

왜 이 시험이 필요한가:
    ① **편집이 승격 기록을 지웠다.** `_collectFormData`의 concept 분기가
       `concept_features: null`·`metadata: null`을 무조건 보냈다. D-128 8항으로
       승격 근거(가중 기여도)가 `concept_features.promotion`에 들어가게 되면서,
       연구자가 설명 한 줄만 고쳐도 「왜 이 개념이 올라왔는가」가 통째로
       사라지는 자리가 됐다. 예외도 경고도 나지 않는다 — 조용히 없어진다.
    ② **무게와 부호는 함께 저장해야 한다**(11항). 화면에서 부호를 넣을 길이
       없으면 저장 계층에만 있고 아무도 못 쓰는 필드가 된다. 그리고 부호를
       비워 둔 것을 «지지»로 바꿔 보내면 13항이 깨진다.
"""

from __future__ import annotations

from tests.js_harness import run_js

# ruff: noqa: E501 — 스텁 JS를 그대로 넣은 문자열이라 줄 길이 규칙을 이 파일에서는 끈다

JS = "entity-manager.js"

# ── 폼 입력값을 흉내 내는 최소 DOM ──
#
# _collectFormData 는 document.getElementById(...).value 만 읽는다. 그래서 «어떤
# id에 어떤 값이 들어 있는가»만 주면 된다 — DOM 전체를 흉내 내지 않는다.
FAKE_DOM = r"""
globalThis.__fields = {};
globalThis.document = {
  getElementById: (id) => (id in globalThis.__fields ? { value: globalThis.__fields[id] } : null),
};
"""


def _run(tmp_path, fields: dict, entity_type: str, editing: dict | None):
    """폼 값 `fields`로 `_collectFormData(entity_type)`를 돌려 결과를 돌려준다."""
    import json as _json

    setup = (
        FAKE_DOM
        + f"globalThis.__fields = {_json.dumps(fields, ensure_ascii=False)};\n"
        + f"globalThis.entityState = {{ editingEntity: {_json.dumps(editing, ensure_ascii=False)} }};\n"
    )
    return run_js(
        tmp_path,
        JS,
        ["_collectFormData"],
        setup,
        f"console.log(JSON.stringify({{ built: _collectFormData({entity_type!r}) }}));",
    )["built"]


def test_editing_a_concept_keeps_the_promotion_record(tmp_path):
    """설명만 고쳐도 승격 근거가 살아 있어야 한다 (D-128 8항)."""
    promotion = {
        "eligible": True,
        "reason": "실질 무게 9.0(출처 1개)가 임계 3.0 이상입니다.",
        "metrics": {"source_count": 4, "effective_weight": 9.0},
    }
    existing = {
        "id": "c1",
        "label": "王戎",
        "concept_features": {"promotion": promotion},
        "metadata": {"promoted_from_tag_id": "t1"},
    }
    built = _run(
        tmp_path,
        {
            "ef-label": "王戎",
            "ef-scope-doc": "",
            "ef-description": "설명을 한 줄 고쳤다",
            "ef-status": "active",
        },
        "concept",
        existing,
    )
    assert built["description"] == "설명을 한 줄 고쳤다"
    assert built["concept_features"] == {"promotion": promotion}
    assert built["metadata"] == {"promoted_from_tag_id": "t1"}


def test_new_concept_has_no_promotion_record(tmp_path):
    """새로 만드는 개념에는 보존할 기록이 없다 — null 이어야 한다."""
    built = _run(
        tmp_path,
        {"ef-label": "새 개념", "ef-scope-doc": "", "ef-description": "", "ef-status": "draft"},
        "concept",
        None,
    )
    assert built["concept_features"] is None
    assert built["metadata"] is None


def test_relation_sends_weight_and_polarity_together(tmp_path):
    """무게와 부호는 함께 저장한다 (D-128 11항)."""
    built = _run(
        tmp_path,
        {
            "ef-subject-id": "s1",
            "ef-subject-type": "concept",
            "ef-predicate": "governs",
            "ef-object-id": "o1",
            "ef-object-type": "concept",
            "ef-object-value": "",
            "ef-confidence": "0.8",
            "ef-weight": "12.5",
            "ef-polarity": "refute",
            "ef-mode": "",
            "ef-extractor": "manual",
            "ef-status": "draft",
        },
        "relation",
        None,
    )
    assert built["weight"] == 12.5
    assert built["polarity"] == "refute"
    assert built["mode"] is None  # 빈 칸은 assert(기본)이다


def test_blank_polarity_is_not_turned_into_support(tmp_path):
    """부호를 비워 두면 null 로 간다 — 화면이 «지지»로 바꿔 보내면 13항이 깨진다."""
    built = _run(
        tmp_path,
        {
            "ef-subject-id": "s1",
            "ef-subject-type": "concept",
            "ef-predicate": "governs",
            "ef-object-id": "",
            "ef-object-type": "",
            "ef-object-value": "",
            "ef-confidence": "0.8",
            "ef-weight": "",
            "ef-polarity": "",
            "ef-mode": "",
            "ef-extractor": "manual",
            "ef-status": "draft",
        },
        "relation",
        None,
    )
    assert built["polarity"] is None
    assert built["weight"] is None  # 빈 칸은 «미지정»이지 0이 아니다


def test_modulate_mode_is_sent(tmp_path):
    """조절 관계를 화면에서 만들 수 있어야 한다 (D-128 12항)."""
    built = _run(
        tmp_path,
        {
            "ef-subject-id": "s1",
            "ef-subject-type": "concept",
            "ef-predicate": "weakens",
            "ef-object-id": "r1",
            "ef-object-type": "relation",
            "ef-object-value": "",
            "ef-confidence": "0.8",
            "ef-weight": "3",
            "ef-polarity": "",
            "ef-mode": "modulate",
            "ef-extractor": "manual",
            "ef-status": "draft",
        },
        "relation",
        None,
    )
    assert built["mode"] == "modulate"
    assert built["object_type"] == "relation"
