"""Concept의 범위는 «주소»다 — 순위 가중치가 아니다 (D-128 6항).

무엇을 정하는가:
    `Concept.scope_document`를 조회에서 어떻게 다루는가. 둘 중 하나다 —
    ① 다른 문헌의 개념도 목록에 넣되 순위를 낮춘다(사전확률) ② 다른 문헌의
    개념은 **아예 다른 주소**라 목록에 들어오지 않는다(벽). D-128은 ②를 택했다.

왜 ②인가 — 실측이 한 번 뒤집힌 자리다:
    운동출력 계통만 봤을 때 출력 무게의 43.0%만 자기 구획에 머물러서, 처음에는
    «구획은 사전확률일 뿐»으로 읽혔다. 그런데 그 계통은 구획을 건너 배포하는 것이
    임무라서 그랬다. 전수로 다시 재니 연합 구조는 **83.2%**, 감각 전달은 **87.2%**로
    출력 무게의 대부분이 자기 구획에 머물렀다. 이 저장소의 임무는 연합이므로
    벽 쪽이 유비에 맞는다.

**이것은 출력 쪽 규칙이다** (D-128 9항):
    들어오는 쪽 — 승격 출처 수집 — 은 구획으로 막지 않는다. 연합 구조에서 수렴은
    62.1%로 열려 있고 발산이 83.2%로 좁다. 수집을 막으면 연합 자체가 일어나지
    않는다. `core/promotion.py::gather_sources`가 문헌으로 거르지 않는 것이 그
    규칙이고, 이 모듈은 그것을 **뒤집지 않는다.**

전역(scope_document = None)의 뜻:
    「어느 문헌에서 보아도 이 개념이다」. 주소로 말하면 모든 주소에 걸린다.
    문헌 범위를 물었을 때 전역 개념이 함께 나오는 이유이고, 그 반대 —
    문헌 A의 개념이 B를 물었을 때 나오는 일 — 은 없다.
"""

import logging

logger = logging.getLogger(__name__)

# 전역 범위를 나타내는 값. 「이 개념은 서고 전체에서 같은 것」이라는 뜻이다.
SCOPE_GLOBAL = None

# 9항이 여기를 뒤집지 못하게 옆에 적어 둔다. 검색으로 닿게 하려고 상수로 둔다.
OUTPUT_SIDE_ONLY_NOTE = (
    "범위를 주소로 보는 것은 «내보내는 쪽»(조회·참조)의 규칙이다. "
    "«모으는 쪽»(승격 출처 수집)은 구획으로 막지 않는다 — core/promotion.py의 "
    "gather_sources 와 SCOPE_BLIND_COLLECTION_NOTE 를 보라. 둘을 같은 규칙으로 "
    "합치면 연합이 일어나지 않거나(수집을 막으면) 개념이 문헌 사이로 새어 나간다."
)


def in_scope(concept: dict, document_id: str | None) -> bool:
    """이 개념이 그 문헌의 주소에 걸리는가.

    입력:
        concept — Concept dict.
        document_id — 물어보는 문헌 id. None이면 «전역만» 묻는 것이다.
    출력: 걸리면 True.

    규칙 셋:
        - 전역 개념(scope_document 없음)은 **언제나** 걸린다.
        - 같은 문헌 범위면 걸린다.
        - 다른 문헌 범위면 **걸리지 않는다.** 순위를 낮추는 것이 아니라 아니다.
    """
    scope = concept.get("scope_document")
    if scope in (None, ""):
        return True
    if document_id in (None, ""):
        # 전역만 물었는데 문헌 범위를 가진 개념이면 주소가 다르다.
        return False
    return scope == document_id


def scoped(concepts: list[dict], document_id: str | None) -> list[dict]:
    """주소에 걸리는 개념만 남긴다 (순위를 매기지 않는다).

    입력: concepts — Concept dict 목록. document_id — 문헌 id 또는 None.
    출력: 걸러진 목록. **순서는 그대로다** — 이 함수는 정렬하지 않는다.

    왜 정렬하지 않는가: 정렬을 하는 순간 「범위가 순위에 영향을 준다」는 말이
    되고, 그것이 6항이 버린 쪽이다. 여기는 넣고 빼기만 한다.
    """
    return [c for c in concepts if in_scope(c, document_id)]


# 한때 `address_of`(주소를 튜플로)와 `resolve_by_label`(라벨로 찾기)이 여기 있었으나
# 부르는 곳이 한 번도 생기지 않아 걷어냈다(2026-09-22 실측). `resolve_by_label`은
# **범위로 정렬**하고 있었다 — 이 모듈의 계약을 어기는 예외를 독스트링의 변론과 함께
# 죽은 코드로 두면, 다음 사람이 그 변론을 읽지 않고 배선한다. 「같은 라벨이 문헌마다
# 다른 개념일 수 있다」는 문제는 여전히 참이다. 필요해지면 6항을 다시 열고 결정으로
# 남긴 뒤 만든다.
