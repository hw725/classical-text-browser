"""커넥톰 대조 — 이 서고의 관계 분포를 연합 구조와 맞대어 본다 (D-128 후속).

무엇을 하는가:
    D-128의 규약들은 커넥톰 연합 구조(버섯체 케니언세포)의 측정에서 나왔다.
    그 규약대로 만들어 놓고 나면 다음 물음이 남는다 — **이 서고가 실제로 그런
    모양인가?** 관계를 수천 개 쌓았는데 전부 무게 1이고 부호가 하나도 없다면,
    규약은 지켜졌지만 그 규약이 가정한 구조는 아직 생기지 않은 것이다.

    이 모듈은 서고의 Relation 분포를 재어 연합 구조의 실측값과 나란히 놓는다.
    **판정하지 않는다** — 「닮았다/아니다」로 점수를 매기면 연구자가 그 점수를
    올리려고 데이터를 손대게 된다. 숫자를 나란히 보여 주고 해석은 사람이 한다.

두 층으로 나뉘는 이유:
    - **기록된 기준값**(`RECORDED_REFERENCE`)은 의존성이 없다. 배포되는 앱에서도
      대조가 돌아간다. 수치는 D-128에 적힌 것이고 2026-09-21에 다시 재어 24개가
      전부 일치함을 확인했다.
    - **살아 있는 재측정**(`measure_reference`)은 neuPrint에 직접 물어 기준값을
      새로 뽑는다. 커넥톰 데이터셋이 갱신되면 기록된 값이 낡기 때문이다.
      이쪽은 `neuprint-python`과 토큰이 있어야 하고, **배포본에는 그 둘이 없다**
      (`is_live_available()`이 False를 돌려주고 라우트가 400으로 답한다).

왜 이 구조인가 — 이 저장소의 기존 관례를 그대로 따른다:
    OCR 엔진들은 extra를 설치하지 않으면 `is_available()`이 False가 되고
    레지스트리가 조용히 목록에서 뺀다(D-044·D-056). 판독 계획은 CPU 환경이면
    라우트가 400을 주고 화면에서 단추가 숨는다(D-126). 커넥톰도 같은 틀이다 —
    `pyproject.toml`의 `connectome` extra이고, **`install.ps1`의 어느 선택지에도
    들어 있지 않다.** 설치 파일을 받은 사람에게는 선택지로도 보이지 않는다.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# 살아 있는 재측정에 필요한 것 둘. 토큰은 값을 읽지 않고 «있는가»만 본다.
NEUPRINT_TOKEN_ENV = "NEUPRINT_APPLICATION_CREDENTIALS"
NEUPRINT_TOKEN_FILE = Path.home() / ".claude" / "data" / "triage" / ".env"
NEUPRINT_DATASET = "male-cns:v1.0"

# 이 저장소가 유비로 삼는 계통. 버섯체 케니언세포는 연합·기억 구조라 지식
# 그래프가 하는 일과 성격이 같다. 하행뉴런(운동출력)은 내보내는 통로라 유비가
# 아니다 — D-128의 「이 저장소의 유비는 KCg-m이다」를 코드에도 적어 둔다.
REFERENCE_LINEAGE = "KCg-m"

#: 연합 구조의 실측값. 출처는 D-128이고, 2026-09-21에
#: `jt725/scripts/cns_structure_stats.py`로 다시 재어 전부 일치함을 확인했다.
#: 여기 적힌 것은 **입력 쪽(수렴)** 값이다 — 승격이 하는 일이 수렴이기 때문이다.
RECORDED_REFERENCE: dict = {
    "lineage": REFERENCE_LINEAGE,
    "dataset": NEUPRINT_DATASET,
    "measured_at": "2026-09-21",
    "source": "docs/DECISIONS.md D-128 (jt725/scripts/cns_structure_stats.py로 재생산)",
    # 무게 1~2인 엣지의 비율. 이것이 «잡음 바닥»의 근거다.
    "noise_share": 0.840,
    # 상위 10% 엣지가 가진 무게 비중.
    "top10_share": 0.471,
    # 입력 무게의 부호 구성. 글루탐산은 맥락 의존이라 억제에 합산하지 않는다.
    "polarity": {"support": 0.747, "refute": 0.120, "ambiguous": 0.005, "modulate": 0.125},
    # 강연결(무게 5 이상)만 봤을 때. 11항의 근거 — 반대 방향은 강한 꼬리에 몰린다.
    "polarity_strong": {"support": 0.651, "refute": 0.277},
}


def is_live_available() -> tuple[bool, str]:
    """살아 있는 재측정을 할 수 있는가.

    출력: (가능한가, 한국어 사유). 가능하면 사유는 빈 문자열.

    왜 사유를 함께 돌려주는가: 라우트가 400으로 답할 때 「왜 안 되는가」를
    화면에 그대로 띄울 수 있어야 한다. 「사용 불가」만 뜨면 연구자는 자기 PC가
    고장 난 줄 안다 — 이건 애초에 배포본에 없는 기능이다.
    """
    try:
        import neuprint  # noqa: F401
    except ImportError:
        return (
            False,
            "커넥톰 재측정은 이 설치에 포함되지 않았습니다.\n"
            "→ 왜: neuprint-python은 선택 항목이고 설치 파일의 선택지에 없습니다.\n"
            "→ 직접 쓰시려면: uv sync --extra connectome",
        )
    if not _token_present():
        return (
            False,
            "neuPrint 토큰이 없습니다.\n"
            f"→ 어디에: 환경변수 {NEUPRINT_TOKEN_ENV} 또는 {NEUPRINT_TOKEN_FILE}\n"
            "→ 토큰은 neuprint.janelia.org에서 발급합니다(읽기 전용으로 충분합니다).",
        )
    return True, ""


def _token_present() -> bool:
    """토큰이 있는지만 본다 — **값은 읽지도 돌려주지도 않는다.**"""
    if os.environ.get(NEUPRINT_TOKEN_ENV):
        return True
    if not NEUPRINT_TOKEN_FILE.exists():
        return False
    try:
        for line in NEUPRINT_TOKEN_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith(NEUPRINT_TOKEN_ENV) and "=" in line:
                return bool(line.split("=", 1)[1].strip())
    except OSError as e:  # noqa: BLE001 — 읽지 못하면 «없다»로 본다
        logger.warning("토큰 파일을 읽지 못했습니다(%s): %s", NEUPRINT_TOKEN_FILE, e)
    return False


def library_profile(relations: list[dict]) -> dict:
    """이 서고의 관계 분포를 잰다 (커넥톰과 같은 자로).

    입력: relations — Relation dict 목록.
    출력: {"count", "noise_share", "top10_share", "polarity", "polarity_strong",
           "unsigned_strong"}

    왜 `core/relation_polarity.py`의 함수를 그대로 쓰는가: 대조가 의미를 가지려면
    **양쪽을 같은 자로 재야 한다.** 여기서 따로 계산하면 정의가 갈라지고, 갈라진
    뒤에는 차이가 실제 차이인지 자의 차이인지 알 수 없다.
    """
    from .relation_polarity import (
        polarity_breakdown,
        strong_edges,
        unsigned_strong_relations,
        weight_of,
    )

    if not relations:
        return {
            "count": 0,
            "noise_share": None,
            "top10_share": None,
            "polarity": None,
            "polarity_strong": None,
            "unsigned_strong": 0,
        }

    weights = sorted((weight_of(r) for r in relations), reverse=True)
    total = sum(weights)
    # 잡음 바닥(무게 1~2)이 가진 무게 비중 — 커넥톰 표의 「무게 1~2 비율」과 같은 뜻.
    noise = sum(w for w in weights if w <= 2.0)
    top_n = max(1, int(len(weights) * 0.1))

    breakdown = polarity_breakdown(relations)
    strong = strong_edges(relations, threshold=5.0)  # 실측과 같은 절단
    return {
        "count": len(relations),
        "noise_share": round(noise / total, 4) if total else 0.0,
        "top10_share": round(sum(weights[:top_n]) / total, 4) if total else 0.0,
        "polarity": {
            "support": breakdown["support"],
            "refute": breakdown["refute"],
            "ambiguous": round(breakdown["context_dependent"] + breakdown["undetermined"], 4),
            "modulate": breakdown["modulate"],
        },
        "polarity_strong": (
            {
                "support": polarity_breakdown(strong)["support"],
                "refute": polarity_breakdown(strong)["refute"],
            }
            if strong
            else None
        ),
        "unsigned_strong": len(unsigned_strong_relations(relations, threshold=5.0)),
    }


def compare(relations: list[dict], reference: dict | None = None) -> dict:
    """서고와 기준값을 나란히 놓는다. **판정하지 않는다.**

    입력: relations — Relation 목록. reference — 기준값(기본은 기록된 것).
    출력: {"reference": {...}, "library": {...}, "rows": [...], "notes": [...]}
        rows 항목: {"key", "label", "library", "reference", "gap"}

    왜 점수를 매기지 않는가: 「연합 구조와 82% 닮았다」 같은 숫자를 내놓으면
    그 숫자를 올리는 것이 목표가 된다. 커넥톰은 **참고 좌표**이지 목표가 아니다 —
    이 저장소의 관계는 사람이 읽고 판단해서 쌓는 것이고, 분포가 달라야 마땅한
    이유도 얼마든지 있다. 그래서 차이만 보여 주고 해석은 사람에게 남긴다.
    """
    reference = reference or RECORDED_REFERENCE
    profile = library_profile(relations)

    def _row(key: str, label: str, lib, ref):
        gap = None
        if isinstance(lib, (int, float)) and isinstance(ref, (int, float)):
            gap = round(lib - ref, 4)
        return {"key": key, "label": label, "library": lib, "reference": ref, "gap": gap}

    pol = profile["polarity"] or {}
    rows = [
        _row(
            "noise_share", "무게 1~2가 가진 비중", profile["noise_share"], reference["noise_share"]
        ),
        _row(
            "top10_share", "상위 10%가 가진 비중", profile["top10_share"], reference["top10_share"]
        ),
        _row("refute", "반박 비중", pol.get("refute"), reference["polarity"]["refute"]),
        _row("modulate", "조절 비중", pol.get("modulate"), reference["polarity"]["modulate"]),
        _row(
            "refute_strong",
            "강연결에서의 반박 비중",
            (profile["polarity_strong"] or {}).get("refute"),
            reference["polarity_strong"]["refute"],
        ),
    ]

    notes: list[str] = []
    if profile["count"] == 0:
        notes.append("관계가 아직 없습니다 — 대조할 것이 없습니다.")
    if profile["unsigned_strong"]:
        notes.append(
            f"부호가 없는 강연결이 {profile['unsigned_strong']}개 있습니다. "
            "반대 방향은 강한 꼬리에 몰리므로(D-128 11항), 거기를 먼저 채우면 "
            "이 대조의 아래 두 줄이 달라집니다."
        )
    if profile["count"] and (pol.get("refute") or 0) == 0:
        notes.append(
            "반박이 한 건도 없습니다. 연합 구조에서는 입력 무게의 12.0%가 억제였습니다 — "
            "자료가 그럴 수도 있지만, 부호를 아직 안 적은 것일 수도 있습니다."
        )
    return {"reference": reference, "library": profile, "rows": rows, "notes": notes}


def measure_reference(lineage: str = REFERENCE_LINEAGE) -> dict:
    """neuPrint에 직접 물어 기준값을 새로 뽑는다 (**살아 있는 재측정**).

    입력: lineage — 계통 이름(기본은 연합 구조 KCg-m).
    출력: RECORDED_REFERENCE와 같은 모양의 dict. `measured_at`은 오늘 날짜다.

    Raises:
        RuntimeError: neuprint-python이 없거나 토큰이 없을 때 — 한국어 사유를 담는다.

    왜 이 함수만 게이트 뒤에 있는가: 위의 `compare`는 기록된 기준값으로 돌아가므로
    배포본에서도 쓸 수 있다. 커넥톰 데이터셋이 갱신돼 기록된 값이 낡았을 때만
    이쪽이 필요하고, 그건 이 도구를 만드는 쪽의 일이지 쓰는 쪽의 일이 아니다.

    읽기 전용이다 — neuPrint에 아무것도 쓰지 않는다.
    """
    ok, reason = is_live_available()
    if not ok:
        raise RuntimeError(reason)

    from neuprint import Client, fetch_adjacencies, fetch_neurons  # noqa: F401

    token = os.environ.get(NEUPRINT_TOKEN_ENV) or _token_from_file()
    client = Client("neuprint.janelia.org", dataset=NEUPRINT_DATASET, token=token)

    # 측정 규약은 jt725/scripts/cns_structure_stats.py와 같아야 한다 — 전수이고,
    # 구획화는 primary ROI로 제한하며, 글루탐산은 억제에 합산하지 않는다.
    # 그 스크립트가 정본이므로 여기서는 부호 구성만 다시 뽑는다(대조에 쓰는 값이다).
    from datetime import date

    query = f"""
    MATCH (a:Neuron)-[w:ConnectsTo]->(b:Neuron)
    WHERE b.type STARTS WITH '{lineage}'
    RETURN a.predictedNt AS nt, sum(w.weight) AS total
    """
    df = client.fetch_custom(query)
    by_nt = {str(r.nt): float(r.total) for r in df.itertuples() if r.nt}
    grand = sum(by_nt.values()) or 1.0

    def _share(*names: str) -> float:
        return round(sum(by_nt.get(n, 0.0) for n in names) / grand, 4)

    return {
        **RECORDED_REFERENCE,
        "measured_at": date.today().isoformat(),
        "source": f"neuPrint {NEUPRINT_DATASET} 직접 질의",
        "polarity": {
            "support": _share("acetylcholine"),
            "refute": _share("gaba", "histamine"),
            "ambiguous": _share("glutamate"),
            "modulate": _share("dopamine", "octopamine", "serotonin"),
        },
    }


def _token_from_file() -> str:
    """토큰 파일에서 값을 읽는다 — `measure_reference`만 쓴다(로그에 남기지 않는다)."""
    for line in NEUPRINT_TOKEN_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip().startswith(NEUPRINT_TOKEN_ENV) and "=" in line:
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""
