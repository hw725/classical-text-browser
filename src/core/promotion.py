"""Concept 승격의 저울 — 개수가 아니라 무게 (D-128 8·9·10항).

무엇이 문제였나:
    「출처가 몇 개 모이면 Concept으로 올리는가」를 **개수**로 정하면 안 된다.
    커넥톰 수렴 측정에서 연합 구조(버섯체 케니언세포)는 입력 파트너가 269개나
    되는데 그중 **84.0%가 무게 1~2**, 즉 잡음 바닥이었다. 개수를 세면 잡음
    여럿이 실제 기여자 하나를 이긴다. 무게 상위 꼬리를 보면 상위 10%가 입력
    무게의 47.1%를 쥐고 있다 — 저울은 거기에 달아야 한다.

이 모듈이 정하는 것 셋:

    ① **잡음 바닥**(`NOISE_WEIGHT_CEILING`) — 무게가 여기 이하인 출처는 승격
       근거로 세지 않는다. 지우지는 않는다(D-128 4항: 약한 관계를 지우지 말고
       무게를 붙인다). 세지 않을 뿐이고 목록에는 남아 언제든 임계를 내리면 돌아온다.

    ② **넓게 모아서 좁게 내보낸다 — 연합 구조에 한한다**(9항). 출처 수집은
       문헌 구획으로 막지 않고(`gather_sources`가 서고의 모든 해석 대상 문헌에서
       모은다), 승격된 Concept은 `scope_document` 하나를 갖는다. 연합 구조에서
       수렴은 62.1%로 열려 있고 발산은 83.2%로 자기 구획에 머무는 것과 같은 모양이다.
       **어디에 적용하지 않는가**는 `SCOPE_BLIND_COLLECTION_NOTE`에 적었다.

    ③ **승격은 출처를 줄이는 단계가 아니다**(10항). 초판은 하행뉴런을 「모아서
       내보내는 깔때기」로 보고 대조했으나 전수 재측정에서 철회됐다 — 연합 구조는
       입출력이 거의 대칭(269↔282)이고, 어느 계통도 파트너 수로 «모은다»고 말할 수
       없었다. 남는 차이는 **무게 집중도**다. 그래서 승격은 Tag를 지우거나 합치지
       않고, 같은 폭을 유지한 채 **무게만 재배치**한다.

무게는 어디서 오는가:
    기본 도출은 「그 단위의 확정 원문에 그 표면형이 몇 번 나오는가」 × 「그 단위에서
    잡힌 Tag의 최대 신뢰도」다. 시냅스 수와 같은 뜻의 양 — 「이 출처가 이 개념을
    몇 번 건드렸는가」 — 을 지금 가진 데이터로 셀 수 있는 유일한 방법이다.
    `metadata.weight`가 적혀 있으면 도출을 건너뛰고 그 값을 쓴다(사람·도구가 직접 잰 값).
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 잡음 바닥. 커넥톰 연합 구조에서 무게 1~2인 엣지가 입력의 84.0%였다 — 여기가
# 바닥이라는 뜻이고, 이 값 이하는 «있다»는 사실 외에 아무것도 말하지 않는다.
NOISE_WEIGHT_CEILING: float = 2.0

# 승격에 필요한 실질 무게(잡음 바닥을 넘는 출처들의 무게 합). 3은 「바닥을 넘는
# 출처가 최소 하나는 있어야 한다」는 뜻이다 — 바닥이 2이므로 3이 그 바로 위다.
DEFAULT_MIN_EFFECTIVE_WEIGHT: float = 3.0

# 판정에 **들어가지 못하는** 수치 (D-128 7항).
#
# 파트너 수와 집중도는 계통마다 너무 달라서 설계 근거가 되지 못한다 — 전수
# 기준으로 출력 파트너 수가 45~282로 6배, 상위 3 집중도가 13.1~31.9%로 2.4배
# 차이났다. 「커넥톰은 이렇다」고 말할 수 있는 값이 아니다.
#
# 그래서 promotion_metrics()는 이 값들을 **재서 보여주기만** 하고,
# evaluate_promotion()의 판정에는 effective_weight 하나만 들어간다. 사람이
# 화면에서 「왜 승격되지 않는가」를 이해하는 데는 필요하지만, 임계로 쓰면
# 그 순간 계통 편차를 설계에 박아 넣는 것이 된다.
#
# 검사: tests/test_d128.py::TestPartnerCountIsNotEvidence — 잡음 출처를 500개
# 더해도 판정이 흔들리지 않는지 잰다.
METRICS_NOT_USED_FOR_VERDICT = ("source_count", "effective_count", "top10_share", "noise_share")

# 9항이 어디까지인가를 코드 옆에 적어 둔다. 주석이 아니라 상수인 이유는,
# 이 규칙을 다른 곳에 퍼뜨리려는 사람이 검색으로 여기 닿게 하기 위해서다.
SCOPE_BLIND_COLLECTION_NOTE = (
    "구획을 넘어 모으는 것은 «연합 구조»인 Concept 승격에만 적용한다. "
    "커넥톰에서 이 비대칭의 방향은 계통마다 반대였다 — 운동출력 계통은 좁게 모아 "
    "넓게 뿌리고(수렴 68.7% · 발산 43.0%), 감각 전달은 양쪽 다 좁다(85.8% / 87.2%). "
    "따라서 편성(경계·권 구조)·OCR·레이아웃처럼 임무가 다른 층에는 적용하지 않는다. "
    "그 층들에서 문헌 구획은 사전확률이 아니라 주소다."
)


def source_weight(source: dict) -> float:
    """출처 하나의 무게를 읽는다.

    입력: source — {"weight": ...} 또는 {"occurrences": N, "confidence": c}.
    출력: 0 이상의 실수.

    왜 이 순서인가: 사람·도구가 직접 잰 값(`weight`)이 있으면 그것이 정본이고,
    없을 때만 도출한다. 도출이 명시값을 덮으면 잰 사람이 다시 잴 방법이 없다.
    """
    if source.get("weight") is not None:
        try:
            return max(0.0, float(source["weight"]))
        except (TypeError, ValueError):
            logger.warning("출처의 weight를 숫자로 읽지 못했습니다: %r", source.get("weight"))
    occurrences = source.get("occurrences") or 0
    confidence = source.get("confidence")
    if confidence is None:
        confidence = 1.0
    try:
        return max(0.0, float(occurrences) * float(confidence))
    except (TypeError, ValueError):
        return 0.0


def promotion_metrics(
    sources: list[dict],
    *,
    noise_ceiling: float = NOISE_WEIGHT_CEILING,
) -> dict:
    """출처 묶음의 무게 분포를 잰다 (판정은 하지 않는다).

    입력: sources — 출처 dict 목록. noise_ceiling — 잡음 바닥.
    출력:
        {
          "source_count": 출처 수,
          "total_weight": 전체 무게,
          "effective_weight": 바닥을 넘는 출처들의 무게 합,
          "effective_count": 바닥을 넘는 출처 수,
          "noise_share": 바닥 이하가 가진 무게 비중 (0~1),
          "top_weight": 가장 무거운 출처의 무게,
          "top10_share": 상위 10% 출처가 가진 무게 비중 (0~1),
        }

    왜 판정과 나누는가: 화면에 「왜 승격되지 않는가」를 보여주려면 수치가 따로
    있어야 한다. 판정만 돌려주면 연구자는 임계를 손볼 근거를 못 본다.
    """
    weights = sorted((source_weight(s) for s in sources), reverse=True)
    total = sum(weights)
    effective = [w for w in weights if w > noise_ceiling]
    # 상위 10% — 출처가 적으면 최소 하나는 본다(0개를 보면 언제나 0%가 된다).
    top_n = max(1, int(len(weights) * 0.1)) if weights else 0
    top10 = sum(weights[:top_n])
    return {
        "source_count": len(weights),
        "total_weight": round(total, 4),
        "effective_weight": round(sum(effective), 4),
        "effective_count": len(effective),
        "noise_share": round((total - sum(effective)) / total, 4) if total else 0.0,
        "top_weight": round(weights[0], 4) if weights else 0.0,
        "top10_share": round(top10 / total, 4) if total else 0.0,
    }


def evaluate_promotion(
    sources: list[dict],
    *,
    noise_ceiling: float = NOISE_WEIGHT_CEILING,
    min_effective_weight: float = DEFAULT_MIN_EFFECTIVE_WEIGHT,
) -> dict:
    """승격해도 되는지 판정한다 — 개수가 아니라 무게로.

    입력: sources — 출처 목록. noise_ceiling / min_effective_weight — 임계.
    출력: {"eligible": bool, "reason": 한국어 사유, "metrics": promotion_metrics 결과,
           "thresholds": {...}}

    핵심 성질: 무게 1짜리 출처가 **몇 개든** 실질 무게는 0이므로 승격되지 않고,
    무게 8짜리 출처 **하나**는 승격된다. 개수를 세면 정반대가 된다 — 그것이
    D-128 8항이 막으려는 것이다.

    왜 판정을 강제하지 않는가: 이 함수는 저울이지 잠금장치가 아니다. 연구자가
    명시적으로 승격을 누르면 그대로 승격되고, 다만 그 판정과 수치가 Concept에
    함께 적힌다(`concept_features.promotion`) — 나중에 왜 올렸는지 되짚을 수 있다.
    """
    metrics = promotion_metrics(sources, noise_ceiling=noise_ceiling)
    eligible = metrics["effective_weight"] >= min_effective_weight
    if eligible:
        reason = (
            f"실질 무게 {metrics['effective_weight']}"
            f"(출처 {metrics['effective_count']}개)가 임계 {min_effective_weight} 이상입니다."
        )
    elif metrics["source_count"] == 0:
        reason = "출처가 없습니다."
    elif metrics["effective_count"] == 0:
        reason = (
            f"출처 {metrics['source_count']}개가 모두 잡음 바닥(무게 {noise_ceiling} 이하)입니다. "
            "출처 «수»가 아니라 «무게»로 재기 때문에, 약한 출처가 여럿이어도 승격되지 않습니다."
        )
    else:
        reason = (
            f"실질 무게 {metrics['effective_weight']}가 임계 {min_effective_weight}에 못 미칩니다."
        )
    return {
        "eligible": eligible,
        "reason": reason,
        "metrics": metrics,
        "thresholds": {
            "noise_ceiling": noise_ceiling,
            "min_effective_weight": min_effective_weight,
        },
    }


def gather_sources(
    interp_path: str | Path,
    surface: str,
    *,
    document_id: str | None = None,
) -> list[dict]:
    """표면형 하나에 대한 승격 출처를 모은다 — **구획으로 막지 않는다**(9항).

    입력:
        interp_path — 해석 저장소 경로.
        surface — 표면 문자열 (예: 王戎).
        document_id — **거르는 값이 아니다.** 모은 출처에 「어느 문헌의 것인가」를
            적어 돌려줄 때 쓰는 기본값이며, 이 값과 다른 문헌의 출처도 그대로 모은다.
    출력: [{"unit_id", "document_id", "tag_ids", "occurrences", "confidence", "weight"}, ...]

    왜 거르지 않는가: 수집을 구획으로 막으면 연합이 일어나지 않는다. 연합 구조의
    수렴은 62.1%로 열려 있고, 그것이 「출처는 어디서든 오고 합성된 개념은 한 영역에
    속한다」는 모양이다. 적용 범위는 SCOPE_BLIND_COLLECTION_NOTE 참조.

    무게 도출: 그 단위의 원문에 표면형이 나온 횟수 × 그 단위에서 잡힌 Tag의 최대
    신뢰도. Tag에 `metadata.weight`가 적혀 있으면 그 값이 이긴다.
    """
    from .entity import _unit_view, list_entities

    interp_path = Path(interp_path).resolve()
    if not surface:
        return []

    tags = [t for t in list_entities(interp_path, "tag") if t.get("surface") == surface]
    units = {u.get("id"): u for u in _unit_view(interp_path)}

    by_unit: dict[str, dict] = {}
    for tag in tags:
        unit_id = tag.get("block_id")  # 필드 이름은 v1.2까지의 것 — B-003
        bucket = by_unit.setdefault(
            unit_id,
            {
                "unit_id": unit_id,
                "document_id": document_id,
                "tag_ids": [],
                "occurrences": 0,
                "confidence": None,
                "weight": None,
            },
        )
        bucket["tag_ids"].append(tag.get("id"))
        conf = tag.get("confidence")
        if conf is not None:
            bucket["confidence"] = max(bucket["confidence"] or 0.0, float(conf))
        explicit = (tag.get("metadata") or {}).get("weight")
        if explicit is not None:
            # 명시값이 여럿이면 가장 큰 것 — 누군가 이미 잰 값을 깎지 않는다.
            bucket["weight"] = max(bucket["weight"] or 0.0, float(explicit))

    for unit_id, bucket in by_unit.items():
        unit = units.get(unit_id) or {}
        text = unit.get("original_text") or ""
        # 같은 단위 안에서 몇 번 건드렸는가. 원문을 못 찾으면 Tag 수로 대신한다.
        bucket["occurrences"] = text.count(surface) or len(bucket["tag_ids"])
        src_doc = ((unit.get("source_ref") or {}) or {}).get("document_id")
        if src_doc:
            bucket["document_id"] = src_doc

    return sorted(by_unit.values(), key=source_weight, reverse=True)
