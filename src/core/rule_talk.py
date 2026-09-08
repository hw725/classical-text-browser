"""사람이 말한 것을 규칙 변경으로 옮긴다 (D-121 두 번째 입구).

왜 필요한가:
    연구자는 자기 책을 이미 안다. 「談草로 끝나는 게 표제야」·「날짜로 기사가 나뉘어」 같은 것을
    지금은 체크박스 위치로 번역해 넣어야 하는데, 그 번역이 어렵다. 말로 넣게 한다.

무엇을 하지 않는가:
    경계를 만들지 않는다. 규칙도 저장하지 않는다. **말을 규칙 «변경 제안»으로 옮기기만** 하고,
    그것이 무엇을 바꾸는지는 rule_preview가 재고, 적용은 사람이 정한다(D-121의 같은 관문).

가장 중요한 계약 — 옮기지 못한 말은 반드시 말한다:
    지금 규칙에는 범위도 조건도 없다. 「권2부터는 卷頭로」·「날짜 앞에 ○가 있을 때만」은 표현할 수
    없다. 그런 말을 비슷한 것으로 조용히 바꿔치기하면, 사람은 말했다고 여기는데 시스템은 다른 일을
    한다. 그래서 모델의 답에는 `unsupported` 칸이 있고,
    코드는 아는 칸이 아닌 것을 전부 그리로 옮긴다.

모델을 믿지 않는 방법:
    ① 답은 정해진 칸 이름과 연산(add·remove·set)만 받는다. ② 어휘를 더하라는 말은 **전문에서 세어**
    몇 번 나오는지 함께 돌려준다 — 0번이면 그 말이 이 책의 것이 아니라는 뜻이다. ③ 그래도 켤지는
    사람이 정한다. D-117 verify_pattern이 LLM에게 하던 것을 사람의 말에도 똑같이 한다.
"""

from __future__ import annotations

from typing import Optional

from core.segmentation import (
    Line,
    fold_text,
    normalize_rules,
    signal_on,
)

# 말로 바꿀 수 있는 칸. 여기 없는 것을 모델이 말하면 unsupported로 옮긴다.
LIST_FIELDS = (
    "title_words",  # 행을 끝맺는 표제 어휘
    "head_words",  # 행 첫머리 어휘
    "symbols",  # 되풀이되는 기호 한 글자
    "head_templates",  # 행 첫머리 꼴(접은 글자 N·G·Z)
    "tail_templates",  # 행 끝 꼴
    "suppress",  # 표제로 보지 않을 행
    "furniture",  # 판심·엽수처럼 종이의 규약인 행
)
SWITCH_FIELDS = ("date", "mark", "volume", "short_line", "after_short", "indent")
NUMBER_FIELDS = ("max_title_chars", "min_confidence")

SYSTEM_PROMPT = (
    "당신은 한문 고서를 편성하는 도구의 «말 옮김이»입니다. 연구자가 자기 책에 대해 아는 것을 "
    "말하면, 그것을 이 프로그램이 가진 규칙 칸으로 옮깁니다. "
    "규칙: (1) 주어진 칸 이름만 씁니다. (2) 어떤 칸으로도 옮길 수 없는 말은 지어내지 말고 "
    "unsupported에 그대로 적습니다 — 비슷한 칸으로 바꿔치기하는 것이 가장 나쁜 답입니다. "
    "(3) 연구자가 말하지 않은 것을 더하지 않습니다. (4) 반드시 JSON만 출력합니다."
)


def _field_guide() -> str:
    """모델에게 보일 칸 설명. 책에서 나온 값은 예로 들지 않는다(D-119·2026-09-08 지적)."""
    return (
        "쓸 수 있는 칸과 연산:\n"
        "  목록 칸 (op: add | remove, value: 글자 한 덩어리)\n"
        "    title_words      — 글의 제목 행을 «끝맺는» 말\n"
        "    head_words       — 제목 행의 «첫머리»에 오는 말\n"
        "    symbols          — 새 글 앞에 되풀이되는 기호 한 글자(한자가 아닌 글자)\n"
        "    head_templates   — 제목 행 첫머리의 «꼴». 한자 수사는 N, 天干은 G, 地支는 Z로 적는다\n"
        "    tail_templates   — 제목 행 끝의 «꼴». 같은 접기 표를 쓴다\n"
        "    suppress         — 제목처럼 보이지만 제목이 아닌 행(원문 그대로)\n"
        "    furniture        — 판심·엽수처럼 종이에 딸린 행(원문 그대로)\n"
        "  스위치 칸 (op: set, value: true | false)\n"
        "    signals.date     — 행 첫머리의 날짜로 글이 나뉜다\n"
        "    signals.mark     — 기호 뒤의 날짜로 글이 나뉜다\n"
        "    signals.volume   — 행 끝의 卷 이름으로 묶음이 나뉜다\n"
        "    signals.short_line / signals.after_short / signals.indent — 판식 보조 신호\n"
        "    indent_alone     — 내려쓴 것만으로 새 글이 시작한다\n"
        "  수 칸 (op: set, value: 숫자)\n"
        "    max_title_chars  — 별행 제목으로 볼 최대 글자 수\n"
        "    min_confidence   — 후보를 채택할 최소 신뢰도(0~1)\n"
        "\n"
        "이 프로그램의 규칙에는 «범위»도 «조건»도 없습니다. 「어느 권부터」·「무엇이 있을 때만」·"
        "「이 책은 무슨 성격이다」 같은 말은 어떤 칸으로도 옮길 수 없습니다. "
        "unsupported에 그대로 적으십시오.\n"
    )


def count_in_text(lines: list[Line], field: str, value: str, rules: Optional[dict] = None) -> int:
    """그 말이 이 책에 몇 번 나오는가. 입력: 행·칸·값. 출력: 횟수. 목적: 사람의 말도 세어 본다.

    0번이면 그 말이 이 책의 것이 아니라는 뜻이다 — 오타이거나 다른 책의 기억이다. 버리지는 않는다.
    """
    rules = normalize_rules(rules)
    texts = [ln.text.strip() for ln in lines if ln.text.strip()]
    limit = rules["max_title_chars"] + 8
    if not value:
        return 0
    if field == "title_words":
        return sum(1 for t in texts if t.endswith(value) and len(t) <= limit)
    if field == "head_words":
        return sum(1 for t in texts if t.startswith(value))
    if field == "symbols":
        return sum(1 for t in texts if value in t)
    if field == "head_templates":
        return sum(1 for t in texts if fold_text(t).startswith(value))
    if field == "tail_templates":
        return sum(1 for t in texts if fold_text(t).endswith(value) and len(t) <= limit)
    if field in ("suppress", "furniture"):
        return sum(1 for t in texts if t == value or t.startswith(value))
    return 0


def apply_changes(
    rules: Optional[dict], changes: list[dict], lines: Optional[list[Line]] = None
) -> tuple[dict, list[dict], list[dict]]:
    """모델이 말한 변경을 규칙에 얹는다. 저장하지 않는다.

    입력: 지금 규칙, 변경 목록([{field, op, value, why}]), (있으면) 세어 볼 행 목록.
    출력: (바꾼 규칙, 받아들인 변경, 옮기지 못한 것).
    목적: 아는 칸만 받고 나머지는 그대로 돌려준다 — 조용히 비슷한 칸으로 바꾸지 않는다.
    """
    out = normalize_rules(rules)
    accepted: list[dict] = []
    rejected: list[dict] = []
    for ch in changes or []:
        if not isinstance(ch, dict):
            continue
        field = str(ch.get("field") or "").strip()
        op = str(ch.get("op") or "").strip()
        value = ch.get("value")
        why = str(ch.get("why") or "")[:200]
        row = {"field": field, "op": op, "value": value, "why": why}
        if field in LIST_FIELDS and op in ("add", "remove") and isinstance(value, str):
            text = value.strip()
            if not text:
                rejected.append({**row, "reason": "값이 비어 있습니다"})
                continue
            current = list(out.get(field) or [])
            if op == "add" and text not in current:
                current.append(text)
            elif op == "remove" and text in current:
                current.remove(text)
            out[field] = current
            if lines is not None:
                row["count"] = count_in_text(lines, field, text, out)
            accepted.append(row)
            continue
        if field.startswith("signals.") and op == "set" and isinstance(value, bool):
            key = field.split(".", 1)[1]
            if key in SWITCH_FIELDS:
                out["signals"] = {**(out.get("signals") or {}), key: value}
                row["before"] = signal_on(rules or {}, key)
                accepted.append(row)
                continue
        if field == "indent_alone" and op == "set" and isinstance(value, bool):
            out["indent_alone"] = value
            accepted.append(row)
            continue
        if field in NUMBER_FIELDS and op == "set" and isinstance(value, (int, float)):
            out[field] = value
            accepted.append(row)
            continue
        rejected.append({**row, "reason": "이 프로그램의 규칙 칸으로 옮길 수 없습니다"})
    return normalize_rules(out), accepted, rejected


async def rules_from_words(
    said: str,
    lines: list[Line],
    rules: Optional[dict],
    router,
    force_provider: Optional[str] = None,
    force_model: Optional[str] = None,
    sample_limit: int = 60,
) -> tuple[Optional[dict], dict]:
    """사람이 말한 것을 규칙 변경으로 옮긴다. 저장하지 않고 경계도 만들지 않는다.

    입력: 사람이 쓴 문장, 행 목록(세어 보려고), 지금 규칙, LLM 라우터.
    출력: (바꾼 규칙 또는 None, {"accepted", "unsupported", "note", "provider", "model", "error"}).
    목적: D-121의 두 번째 입구. 옮긴 결과는 rule_preview가 재고 사람이 승인한다.
    """
    from core.rule_induction import sample_start_lines
    from core.toc import lenient_json

    meta: dict = {
        "accepted": [],
        "unsupported": [],
        "note": "",
        "provider": None,
        "model": None,
        "error": None,
        "raw": None,
    }
    said = (said or "").strip()
    if not said:
        meta["error"] = "무엇을 아는지 한 줄 적어 주세요."
        return None, meta
    rules = normalize_rules(rules)
    sample = sample_start_lines(lines, rules, limit=sample_limit)
    prompt = (
        _field_guide()
        + "\n지금 켜져 있는 규칙(JSON):\n"
        + _rules_digest(rules)
        + "\n\n이 책에서 «글이 시작할 법한 자리»의 표본입니다(참고용):\n"
        + "\n".join(sample)
        + "\n\n연구자가 한 말:\n"
        + said
        + '\n\n형식: {"changes": [{"field": "...", "op": "add|remove|set", '
        + '"value": ..., "why": "..."}], '
        + '"unsupported": [{"said": "...", "why": "..."}], "note": "..."}'
    )
    kwargs = {
        "system": SYSTEM_PROMPT,
        "response_format": "json",
        "max_tokens": 1024,
        "purpose": "segmentation_rules",
        "think": False,  # 칸으로 옮기는 일이다 — 사고 예산을 쓸 일이 아니다(D-083)
    }
    if force_provider:
        kwargs["force_provider"] = force_provider
    if force_model:
        kwargs["force_model"] = force_model
    try:
        response = await router.call(prompt, **kwargs)
    except Exception as e:  # noqa: BLE001 — 모델이 없어도 체크박스로 고치는 길은 남아 있다
        meta["error"] = f"{type(e).__name__}: {e}"
        return None, meta
    meta["provider"] = getattr(response, "provider", None)
    meta["model"] = getattr(response, "model", None)
    data = lenient_json(getattr(response, "text", "") or "")
    if not isinstance(data, dict):
        meta["error"] = "JSON 응답을 해석할 수 없습니다."
        return None, meta
    meta["raw"] = str(getattr(response, "text", ""))[:1000]
    changes = data.get("changes")
    if not isinstance(changes, list):
        changes = []
    proposed, accepted, rejected = apply_changes(rules, changes, lines)
    said_unsupported = [
        {"said": str(u.get("said") or "")[:200], "why": str(u.get("why") or "")[:200]}
        for u in (data.get("unsupported") or [])
        if isinstance(u, dict)
    ]
    # 모델이 «못 옮기겠다»고 한 것과, 코드가 «그런 칸은 없다»고 되돌린 것을 함께 보인다
    meta["accepted"] = accepted
    meta["unsupported"] = said_unsupported + [
        {"said": f"{r['field']} {r['op']} {r['value']}", "why": r["reason"]} for r in rejected
    ]
    meta["note"] = str(data.get("note") or "")[:500]
    if not accepted:
        return None, meta
    return proposed, meta


def _rules_digest(rules: dict) -> str:
    """모델에게 보일 «지금 규칙» 간추림. 해제·판심 목록처럼 긴 것은 수만 적는다."""
    import json

    digest = {
        "signals": {k: signal_on(rules, k) for k in SWITCH_FIELDS},
        "indent_alone": rules.get("indent_alone"),
        "max_title_chars": rules.get("max_title_chars"),
        "min_confidence": rules.get("min_confidence"),
    }
    for field in LIST_FIELDS:
        values = list(rules.get(field) or [])
        digest[field] = values if len(values) <= 12 else f"{len(values)}개"
    return json.dumps(digest, ensure_ascii=False, indent=1)
