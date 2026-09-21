"""Relation 의 부호·무게·조절 (D-128 11·12·13항).

왜 부호가 필요한가 — 그리고 왜 «강한 엣지»에서 특히 필요한가:
    커넥톰의 연합 구조에서 억제성 입력은 전체 무게의 12.0%인데, **강한 연결만
    보면 27.7%**로 두 배 넘게 뛴다(시각 전달도 35.0% → 42.5%). 약한 연결은
    대체로 흥분성이고 **반대 방향은 강한 꼬리에 몰려 있다**는 뜻이다.
    그래서 「강한 엣지로 주 경로를 잡는」 순회를 부호 없이 구현하면, 반박이 가장
    밀집한 자리를 골라 지지와 똑같이 세는 셈이 된다. 무게와 부호는 **함께** 저장한다.

왜 이진이 아닌가 (13항):
    글루탐산성 입력이 두 계통에서 11~12%인데, 초파리에서 그 극성은 학계에서도
    확정적이지 않다. 「지지 아니면 반박」으로 몰아넣으면 그 11%가 통째로 거짓
    신호가 된다. 그래서 부호는 넷이다 — 지지·반박·맥락의존·불명. **적히지 않은
    것을 지지로 읽지 않는다**(`polarity_of`가 `undetermined`를 돌려준다).

왜 «조절»이 따로 있는가 (12항):
    조절계 입력은 연합 구조에만 유의미하게 존재했다(KCg-m 12.5%, 나머지 0%대).
    내용을 주장하지 않고 **다른 관계의 무게를 바꾸는** 입력이다. 이 저장소에도
    대응물이 이미 있다 — 출처 신뢰도, 「이 판정은 폐기됨」, holder 표시 같은 것들이
    Relation 이 아니라 각 층에 흩어져 있었다. 연합 층(Concept)에 한해 1급으로 둔다.
"""

import logging

logger = logging.getLogger(__name__)

# 부호 넷. 이진이 아니다 (13항).
POLARITY_SUPPORT = "support"
POLARITY_REFUTE = "refute"
POLARITY_CONTEXT_DEPENDENT = "context_dependent"
POLARITY_UNDETERMINED = "undetermined"

POLARITIES = (
    POLARITY_SUPPORT,
    POLARITY_REFUTE,
    POLARITY_CONTEXT_DEPENDENT,
    POLARITY_UNDETERMINED,
)

# 「지지도 반박도 아니다」 — 이 둘을 지지·반박 어느 쪽으로도 접지 않는다.
AMBIGUOUS_POLARITIES = (POLARITY_CONTEXT_DEPENDENT, POLARITY_UNDETERMINED)

MODE_ASSERT = "assert"
MODE_MODULATE = "modulate"
MODES = (MODE_ASSERT, MODE_MODULATE)

# 조절형이 가리킬 수 있는 자리. 연합 층(Concept)과 «다른 관계» 둘이다 (12항).
MODULATION_OBJECT_TYPES = ("concept", "relation")

# 실측에서 «강연결»을 자른 값. **임의 절단이고 값 자체가 결론이 아니다** —
# D-128 극성 표의 단서가 그렇게 밝히고 있다. 데이터가 있으면
# suggest_strong_threshold()로 갈음하고, 없을 때의 마지막 기본값으로만 쓴다.
MEASURED_STRONG_THRESHOLD = 5.0


def polarity_of(relation: dict) -> str:
    """관계의 부호를 읽는다. **적히지 않은 것을 지지로 읽지 않는다.**

    입력: relation — Relation dict.
    출력: POLARITIES 중 하나.

    왜 기본이 undetermined 인가: 부호를 아직 정하지 않은 관계를 지지로 세면,
    순회가 「모두가 이 주장을 지지한다」는 그림을 저절로 만들어 낸다. 모름은
    모름으로 남아야 한다 (13항).
    """
    value = relation.get("polarity")
    if value in POLARITIES:
        return value
    if value is not None:
        logger.warning("알 수 없는 polarity 값입니다(%r). undetermined 로 읽습니다.", value)
    return POLARITY_UNDETERMINED


def mode_of(relation: dict) -> str:
    """관계의 종류를 읽는다. 적히지 않았으면 assert(내용을 주장한다).

    입력: relation — Relation dict. 출력: MODES 중 하나.
    """
    value = relation.get("mode")
    return value if value in MODES else MODE_ASSERT


def weight_of(relation: dict, *, default: float = 1.0) -> float:
    """관계의 무게를 읽는다. 적히지 않았으면 default.

    입력: relation — Relation dict. default — 무게가 없을 때의 값.
    출력: 0 이상의 실수.

    왜 기본이 1인가: 무게를 적지 않은 옛 관계를 0으로 보면 임계를 세우는 순간
    전부 사라진다 — 약한 것을 지우지 말라는 4항과 정반대가 된다. 1은 «있다»는
    뜻의 가장 작은 값이고, 실측의 잡음 바닥(1~2)과도 맞는다.
    """
    value = relation.get("weight")
    if value is None:
        return default
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        logger.warning("weight 를 숫자로 읽지 못했습니다(%r). %s 로 봅니다.", value, default)
        return default


def suggest_strong_threshold(relations: list[dict]) -> float:
    """«강연결» 임계를 데이터에서 정한다 (상수로 박지 않는다).

    입력: relations — Relation dict 목록.
    출력: 임계 무게.

    왜 데이터에서인가: 상위 10% 엣지가 가진 무게가 계통마다 42~63%로 달랐다.
    한 값을 코드에 박으면 어떤 자료에서는 거의 모두가 강연결이 되고 다른
    자료에서는 하나도 남지 않는다. 여기서는 무게 분포의 90번째 백분위를 쓰고,
    잴 것이 없으면 실측에서 쓴 임의 절단값으로 내려온다.

    **이 함수가 답하지 않는 질문**: 「어느 확신도부터 믿을 만한가」. 백분위는
    분포와 무관하게 언제나 10%를 자르므로, 대부분이 맞는 자료에서는 맞는 것까지
    잘라 낸다. 그런 임계는 정답을 아는 표본으로 **교정해서** 정해야 하고, 그것은
    다른 도구의 일이다. 여기가 답하는 것은 「무게의 두꺼운 꼬리가 어디부터인가」
    하나뿐이며, D-128의 실측 표가 상위 10%를 기준으로 쓴 것과 같은 물음이다.
    """
    weights = sorted(weight_of(r) for r in relations)
    if len(weights) < 10:
        return MEASURED_STRONG_THRESHOLD
    # 상위 10%의 경계. 인덱스는 0-based라 ceil 대신 int()로 잘라도 90% 지점에 선다.
    return weights[int(len(weights) * 0.9)]


def strong_edges(relations: list[dict], threshold: float | None = None) -> list[dict]:
    """무게가 임계 이상인 관계만 고른다 (지우지 않고 거른다).

    입력: relations — Relation 목록. threshold — None 이면 데이터에서 정한다.
    출력: 걸러진 목록.
    """
    if threshold is None:
        threshold = suggest_strong_threshold(relations)
    return [r for r in relations if weight_of(r) >= threshold]


def polarity_breakdown(relations: list[dict]) -> dict:
    """부호별 무게 구성을 잰다 — 실측 표와 같은 모양으로.

    입력: relations — Relation 목록.
    출력: {부호: 무게 비중(0~1)} + {"total_weight": ..., "count": ...}.

    왜 개수가 아니라 무게 비중인가: 약한 연결까지 평균 내면 부호의 의미가
    희석된다는 것이 11항의 관찰이다. 개수로 세면 정확히 그 희석이 일어난다.
    """
    totals: dict[str, float] = {p: 0.0 for p in POLARITIES}
    modulate = 0.0
    total = 0.0
    for r in relations:
        w = weight_of(r)
        total += w
        if mode_of(r) == MODE_MODULATE:
            modulate += w
            continue
        totals[polarity_of(r)] += w
    result = {p: (round(totals[p] / total, 4) if total else 0.0) for p in POLARITIES}
    result["modulate"] = round(modulate / total, 4) if total else 0.0
    result["total_weight"] = round(total, 4)
    result["count"] = len(relations)
    return result


def unsigned_strong_relations(relations: list[dict], threshold: float | None = None) -> list[dict]:
    """부호가 없는 «강한» 관계를 찾아낸다 — 11항이 경고하는 자리.

    입력: relations, threshold(None 이면 데이터에서).
    출력: 부호가 undetermined 인 강연결 목록.

    왜 필요한가: 강한 꼬리에 반대 방향이 몰려 있으므로, 부호를 안 적은 강연결은
    「지지로 잘못 셀 위험이 가장 큰 자리」다. 순회 전에 여기를 먼저 채워야 한다.
    """
    return [
        r
        for r in strong_edges(relations, threshold)
        if polarity_of(r) == POLARITY_UNDETERMINED and mode_of(r) == MODE_ASSERT
    ]


def validate_relation_semantics(data: dict) -> None:
    """저장 전에 부호·조절의 뜻이 맞는지 본다 (JSON 스키마로 못 적는 규칙).

    입력: data — Relation dict.
    출력: 없음. 어긋나면 ValueError.

    검사 둘:
        ① 조절형(modulate)은 연합 층에만 붙는다 — object_type 이 concept 또는
           relation 이어야 한다 (12항). 조절계 입력이 연합 구조에만 유의미하게
           존재했다는 관찰을 코드에서 지키는 자리다.
        ② 조절형에는 지지/반박 부호를 붙이지 않는다. 조절은 내용을 주장하지 않고
           다른 관계의 무게를 바꾸므로, 지지·반박 축에 놓는 것 자체가 범주 오류다.
    """
    mode = mode_of(data)
    if mode != MODE_MODULATE:
        return

    object_type = data.get("object_type")
    if object_type not in MODULATION_OBJECT_TYPES:
        raise ValueError(
            f"조절형(mode=modulate) 관계의 object_type 은 "
            f"{' 또는 '.join(MODULATION_OBJECT_TYPES)} 여야 합니다 (지금: {object_type!r}).\n"
            "→ 왜: 조절 입력은 연합 층(Concept)에만 붙는다는 것이 D-128 12항의 관찰입니다.\n"
            "→ 해결: 조절 대상을 Concept 이나 다른 Relation 으로 지정하거나, "
            "mode 를 assert 로 두세요."
        )

    polarity = data.get("polarity")
    if polarity in (POLARITY_SUPPORT, POLARITY_REFUTE):
        raise ValueError(
            f"조절형(mode=modulate) 관계에는 '{polarity}' 부호를 붙일 수 없습니다.\n"
            "→ 왜: 조절은 내용을 주장하지 않고 다른 관계의 무게를 바꿉니다 (D-128 12항).\n"
            "→ 해결: polarity 를 비워 두거나 context_dependent 로 두세요."
        )
