"""쪽 훑어보기 (D-126) — 쪽마다 «바로 섰는가»와 «무슨 글인가»를 비전 모델에 묻고, 코드가 회전 구간과
알맞은 OCR 엔진을 제안한다.

왜 있는가:
    책 중간에 접은 그림·가로 표처럼 권의 회전과 다른 구간이 있고, 같은 책 안에 활자·손글씨·훈점 단
    쪽이 섞인다. 사람이 182쪽을 넘기며 찾는 대신, 모델에게 쪽 썸네일을 보이고 정해진 답만 받는다.

무엇을 하지 않는가:
    모델의 답을 그대로 저장하지 않는다. 방향은 넷(+모름), 내용은 여섯(+모름)뿐이고, 코드가 «지금
    회전과 다른 쪽»만 구간으로 묶고, 내용은 **설치된 엔진** 중에서만 권한다. 한 쪽에 종류가 둘
    이상이면(한글+훈점) 엔진을 고르지 않고 «영역을 나눠 영역별로 OCR»하라고 따로 알린다 — 쪽 단위
    엔진으로는 풀 수 없는 일이다. 저장·실행은 사람이 누른다.
"""

from __future__ import annotations

from typing import Optional

from core.toc import lenient_json

SURVEY_SYSTEM_PROMPT = (
    "당신은 스캔된 책의 쪽을 훑어보는 편집자입니다. 두 가지만 판정해 JSON 하나로 답하십시오. "
    '{"orientation": "upright" | "needs_cw" | "needs_ccw" | "upside_down" | "unknown", '
    '"contents": ["modern_print" | "classical_print" | "handwriting" | "kunten" | "hangul" | '
    '"blank" | "unknown", ...]}. '
    "orientation: 글자가 읽는 방향으로 바로 서 있으면 upright, 시계 방향으로 90° 돌려야 서면 "
    "needs_cw, 반시계 90°면 needs_ccw, 180°면 upside_down. "
    "contents: 이 쪽에 있는 글의 종류를 **모두** 적으십시오. 근현대 활자(명조·고딕 인쇄)는 "
    "modern_print, 목판·활자 고서 판본의 한문은 classical_print, 붓·펜 손글씨(초서·행서)는 "
    "handwriting, 한문 옆에 훈점·오쿠리가나·가에리텐이 달려 있으면 kunten, 한글이 있으면 hangul, "
    "글자가 없으면 blank. "
    "확실하지 않으면 unknown."
)
SURVEY_PROMPT = "이 쪽의 방향과, 이 쪽에 있는 글의 종류를 모두 판정하십시오. JSON으로만 답하십시오."

ORIENTATIONS = ("upright", "needs_cw", "needs_ccw", "upside_down")
CONTENTS = ("modern_print", "classical_print", "handwriting", "kunten", "hangul", "blank")
# 답 → 지금 회전에 **더할** 시계 방향 각도
DELTA = {"upright": 0, "needs_cw": 90, "needs_ccw": 270, "upside_down": 180}
# 내용 → 권할 엔진(사용자 지정 2026-09-10: 활자 → NDLOCR, 손글씨 → 古典籍 Full, 훈점 → みんなで翻刻,
# 한글 → LLM 비전). 판본 한문은 古典籍 Lite. 뒤의 것은 앞의 것이 설치돼 있지 않을 때의 대안이다.
ENGINE_FOR_CONTENT: dict[str, tuple[str, ...]] = {
    "modern_print": ("ndlocr", "paddleocr", "llm_vision"),
    "classical_print": ("ndlkotenocr", "ndlkotenocr-full", "honkoku", "llm_vision"),
    "handwriting": ("ndlkotenocr-full", "honkoku", "ndlkotenocr", "llm_vision"),
    "kunten": ("honkoku", "ndlkotenocr-full", "ndlkotenocr", "llm_vision"),
    "hangul": ("llm_vision", "paddleocr"),
}
CONTENT_LABELS = {
    "modern_print": "근현대 활자",
    "classical_print": "고서 판본",
    "handwriting": "손글씨",
    "kunten": "훈점 달림",
    "hangul": "한글 있음",
    "blank": "백지",
}


def parse_survey(text: str) -> tuple[Optional[str], list[str]]:
    """모델 답 → (방향, 내용 목록). 정해진 값이 아니면 방향은 None, 내용은 빠진다.

    내용은 목록이다 — 한 쪽에 한글과 훈점이 함께 있을 수 있다. 옛 모양(`content` 하나)도 받는다.
    """
    data = lenient_json(text or "")
    if isinstance(data, dict):
        o = str(data.get("orientation") or "").strip().lower()
        raw = data.get("contents")
        if raw is None:
            raw = data.get("content")
        items = raw if isinstance(raw, list) else [raw]
        contents: list[str] = []
        for c in items:
            c = str(c or "").strip().lower()
            if c in CONTENTS and c not in contents:
                contents.append(c)
        return (o if o in ORIENTATIONS else None), contents
    t = (text or "").strip().lower()
    o = next((k for k in ("upside_down", "needs_ccw", "needs_cw", "upright") if k in t), None)
    return o, [k for k in CONTENTS if k in t]


def _otsu_threshold(a) -> int:
    """오츠 문턱 — 종이색이 누렇거나 어두운 스캔에서 고정 128은 종이를 잉크로 센다."""
    import numpy as np

    hist, _edges = np.histogram(a, bins=256, range=(0, 256))
    prob = hist / max(hist.sum(), 1)
    w = np.cumsum(prob)
    mu = np.cumsum(prob * np.arange(256))
    var = (mu[-1] * w - mu) ** 2 / np.maximum(w * (1 - w), 1e-9)
    return int(np.argmax(var))


def _periodicity(v, lo: int = 6, hi: int = 90) -> float:
    """프로필의 되풀이 세기 — 글줄 간격의 자기상관 최대값(0~1). 평평하면 0."""
    import numpy as np

    v = v - v.mean()
    if not np.any(v):
        return 0.0
    ac = np.correlate(v, v, mode="full")[len(v) - 1 :]
    ac = ac / ac[0]
    hi = min(hi, len(ac) - 1)
    return float(ac[lo:hi].max()) if hi > lo else 0.0


def orientation_by_projection(
    image_bytes: bytes, writing_direction: str = "vertical_rtl"
) -> tuple[Optional[str], float]:
    """글줄의 방향을 잉크 투영의 **주기성**으로 잰다 — 모델을 부르지 않는다.

    입력: 쪽 이미지(JPEG/PNG 바이트), 이 책의 쓰기 방향(vertical_* / horizontal_*).
    출력: ("upright" | "sideways" | None, ratio). ratio = 열 프로필 주기성 / 행 프로필 주기성.

    왜 코드로 재는가: 비전 모델은 세로쓰기 한문 쪽의 방향을 자주 틀린다(2026-09-10 실측
    gemma4:cloud — 90° 누운 쪽 둘을 upside_down·upright라고 답함). 글줄은 일정한 간격으로
    되풀이되므로, 세로쓰기 쪽을 바로 세우면 **열 방향 프로필**에 열 간격의 주기가 또렷하고 행
    프로필은 밋밋하다. 누우면 반대다. 변동계수(분산)로 재면 검은 띠·테두리 하나가 행 프로필을
    흔들어 틀리지만(같은 날 실측 — 훈점이 촘촘한 속몽구에서 반반), 자기상관은 «되풀이»만 보므로
    띠에 강하다: 속몽구 6~25쪽 0°/90° 40판정을 다 맞혔다(비율 1.9배↑ vs 0.58배↓).
    가로쓰기 책은 관계가 뒤집힌다 — 그래서 쓰기 방향을 받는다. 180°는 투영으로 알 수 없다.
    비율이 1.5배 안이면 None(모름)이다 — 백지·그림·표는 판단하지 않는다.
    """
    try:
        from io import BytesIO

        import numpy as np
        from PIL import Image

        img = Image.open(BytesIO(image_bytes)).convert("L")
        img.thumbnail((700, 700))
        a = np.asarray(img, dtype=np.float32)
        h, w = a.shape
        a = a[int(h * 0.08) : int(h * 0.92), int(w * 0.08) : int(w * 0.92)]  # 테두리·검은 띠
        # «<=»인 이유: 검정·흰색 둘뿐인 그림은 오츠 문턱이 0이 되어 «< 0»이면 잉크가 하나도 없다
        ink = (a <= _otsu_threshold(a)).astype(np.float32)
        if ink.mean() < 0.005:  # 백지
            return None, 1.0
        ratio = _periodicity(ink.sum(axis=0)) / max(_periodicity(ink.sum(axis=1)), 1e-6)
    except Exception:  # noqa: BLE001 — 그림을 못 읽으면 모름
        return None, 1.0
    vertical = str(writing_direction or "").startswith("vertical")
    if ratio > 1.5:
        return ("upright" if vertical else "sideways"), ratio
    if ratio < 1 / 1.5:
        return ("sideways" if vertical else "upright"), ratio
    return None, ratio


def sideways_target(current: int) -> int:
    """누운 쪽의 목표 회전(추정). 90인지 270인지는 투영으로 알 수 없으니 «원래(0°)로 되돌리기»를
    먼저 제안하고, 권 자체가 0°면 시계 90°를 제안한다 — 화면이 미리보기로 확인받고 반대쪽도
    묻는다."""
    return 0 if int(current) % 360 != 0 else 90


def target_rotation(current: int, orientation: Optional[str]) -> Optional[int]:
    """지금 회전에 답을 더한 목표 회전. 모름이면 None."""
    if orientation not in DELTA:
        return None
    return (int(current) + DELTA[orientation]) % 360


def text_contents(contents: list[str]) -> list[str]:
    """글이 있는 종류만(백지 제외)."""
    return [c for c in contents if c != "blank"]


def is_mixed(contents: list[str]) -> bool:
    """한 쪽에 글의 종류가 둘 이상인가 — 쪽 단위 엔진 하나로는 풀 수 없다."""
    return len(text_contents(contents)) >= 2


def recommend_engine(content: Optional[str], available: set[str]) -> Optional[str]:
    """내용 종류에 맞는 엔진 중 **설치된** 첫 것. 백지·모름이면 None."""
    for eid in ENGINE_FOR_CONTENT.get(content or "", ()):
        if eid in available:
            return eid
    return None


def group_rotation_ranges(per_page: list[dict]) -> list[dict]:
    """쪽별 판정을 «지금과 다른 회전» 구간으로 묶는다.

    입력: [{"page", "current", "target"}] (target None = 모름).
    출력: [{"from","to","rotation","pages"}].
    바로 선 쪽(target == current)이 나오면 구간이 끝나고, 모름 쪽은 구간을 끊지 않는다 — 모름은
    «못 봤다»이지 «바로 섰다»가 아니다. 구간에 모름을 흡수해도 쪽 수(pages)는 판정된 쪽만 센다.
    """
    rows = sorted(per_page, key=lambda r: int(r["page"]))
    out: list[dict] = []
    cur: Optional[dict] = None
    for row in rows:
        page, tgt = int(row["page"]), row.get("target")
        if tgt is None:
            continue
        if tgt == row.get("current"):
            cur = None
            continue
        if cur and cur["rotation"] == tgt:
            cur["to"] = page
            cur["pages"] += 1
            continue
        cur = {"from": page, "to": page, "rotation": tgt, "pages": 1}
        out.append(cur)
    return out


def group_engine_ranges(per_page: list[dict]) -> list[dict]:
    """쪽별 권장 엔진을 연속 구간으로 묶는다.

    입력: [{"page", "engine", "content"}] (engine None = 백지·모름·섞인 쪽). 출력:
    [{"from","to","engine","content","pages"}]. 엔진 없는 쪽은 구간을 끊지 않는다.
    """
    rows = sorted(per_page, key=lambda r: int(r["page"]))
    out: list[dict] = []
    cur: Optional[dict] = None
    for row in rows:
        page, eng = int(row["page"]), row.get("engine")
        if not eng:
            continue
        if cur and cur["engine"] == eng:
            cur["to"] = page
            cur["pages"] += 1
            continue
        cur = {"from": page, "to": page, "engine": eng, "content": row.get("content"), "pages": 1}
        out.append(cur)
    return out
