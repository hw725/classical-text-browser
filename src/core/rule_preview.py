"""규칙을 바꾸면 무엇이 달라지는가 — 적용하기 전에 재서 보인다 (D-121).

왜 필요한가:
    규칙 변경은 세 곳에서 온다. ① 사람이 화면에서 체크를 고치거나 말로 이르는 것,
    ② 통계가 «이 둘은 같은 기호로 보입니다»라고 제안하는 것, ③ LLM이 책을 읽고 제안하는 것.
    셋 다 «맞을 수도 틀릴 수도 있는 주장»이라는 점에서 같다.

    이 프로젝트는 이미 그 태도를 갖고 있다 — LLM이 표지를 말하면 코드가 전문에서 세어
    되풀이되지 않으면 버린다(D-117 verify_pattern). 여기서는 한 걸음 더 나아가, 규칙을 켰을 때
    **경계가 실제로 어떻게 달라지는지**를 미리 세어 보인다. 그래야 사람이 «후보 86 → 92,
    새로 잡히는 자리 여섯»을 보고 받아들일지 정할 수 있다.

무엇을 하지 않는가:
    저장하지 않는다. 경계를 만들지도 지우지도 않는다. 두 규칙으로 제안을 각각 세어 견줄 뿐이다.
    적용은 지금까지처럼 「골라 적용」·「전부 적용해 새로 세우기」가 한다.

왜 여기 있는가:
    제안을 세는 일(segmentation)과 규칙을 찾는 일(rule_induction)은 이미 나뉘어 있다.
    «바꾸면 어떻게 되는가»는 그 둘 어디에도 속하지 않는 셋째 질문이라 따로 둔다.
"""

from __future__ import annotations

from typing import Optional

from core.segmentation import Line, normalize_rules, propose_boundaries

# 화면에 늘어놓을 «달라지는 자리»의 최대 수. 넘으면 수만 알린다 — 583개를 늘어놓아야
# 사람이 읽지 못한다(浩齋 실측).
_MAX_EXAMPLES = 12


def _key(p: dict) -> tuple:
    """제안 하나를 자리로 식별한다. 입력: 제안. 출력: (쪽, 행, 글자). 목적: 두 셈을 견준다."""
    return (int(p.get("page", 0)), int(p.get("line_index", 0)), int(p.get("char_offset") or 0))


def _accepted(result: dict) -> dict[tuple, dict]:
    return {_key(p): p for p in result.get("proposals") or [] if p.get("accepted")}


def changed_fields(before: dict, after: dict) -> list[dict]:
    """두 규칙에서 달라진 칸만.

    입력: 규칙 둘. 출력: [{칸, 전, 후}]. 목적: 무엇을 바꾸는지 말한다.
    """
    from core.segmentation import signal_on

    raw_before, raw_after = before, after
    before, after = normalize_rules(before), normalize_rules(after)
    out = []
    for key in sorted(set(before) | set(after)):
        if key in ("origin", "reference_text"):
            continue  # 제안에 영향을 주지 않는다 — 견줄 것이 아니다
        b, a = before.get(key), after.get(key)
        if key == "signals":
            # 스위치는 «적힌 값»이 아니라 «듣는 값»을 견준다 — 안 적힌 스위치는 켜진 것이고,
            # 그대로 보이면 «None → False»처럼 사람이 못 알아볼 말이 된다
            for sig in sorted(set(b or {}) | set(a or {})):
                was, now = signal_on(raw_before or {}, sig), signal_on(raw_after or {}, sig)
                if was != now:
                    out.append({"field": f"signals.{sig}", "before": was, "after": now})
            continue
        if isinstance(b, list) and isinstance(a, list):
            # 목록은 «무엇이 늘고 줄었는가»만 말한다. 순서만 바뀐 것은 달라진 것이 아니다
            gained = [x for x in a if x not in b]
            lost = [x for x in b if x not in a]
            if gained or lost:
                out.append({"field": key, "added": gained, "removed": lost})
            continue
        if b != a:
            out.append({"field": key, "before": b, "after": a})
    return out


def preview_rule_change(
    lines: list[Line],
    before: Optional[dict],
    after: Optional[dict],
    toc_matches: Optional[list[dict]] = None,
) -> dict:
    """규칙을 바꾸면 경계가 어떻게 달라지는지 미리 센다. 저장하지 않는다.

    입력:
        lines — 확정본 행 목록(제안을 세는 데 쓰는 것과 같은 것).
        before — 지금 규칙(없으면 기본값).
        after — 바꾸려는 규칙.
        toc_matches — 목차 대조 결과(있으면 양쪽에 똑같이 준다 — 목차는 규칙이 아니다).
    출력: {
        "before": {"proposals": n, "accepted": m},
        "after":  {"proposals": n, "accepted": m},
        "added":   [{page, line_index, title, reasons, confidence} …],  새로 잡히는 자리
        "removed": [{…} …],                                            빠지는 자리
        "added_total", "removed_total",  — 늘어놓은 것보다 많을 수 있다
        "changes": [{field, before, after} …],
        "summary": 한국어 한 줄,
    }
    목적: 어디서 온 주장이든(사람·통계·LLM) 같은 관문을 지나게 한다. 사람은 숫자를 보고 정한다.
    """
    b_result = propose_boundaries(lines, before, toc_matches=toc_matches)
    a_result = propose_boundaries(lines, after, toc_matches=toc_matches)
    b_acc, a_acc = _accepted(b_result), _accepted(a_result)

    added_keys = [k for k in a_acc if k not in b_acc]
    removed_keys = [k for k in b_acc if k not in a_acc]

    def _show(source: dict[tuple, dict], keys: list[tuple]) -> list[dict]:
        # 자리 순서로 — 사람이 책을 훑는 순서와 같아야 한다
        rows = []
        for k in sorted(keys)[:_MAX_EXAMPLES]:
            p = source[k]
            rows.append(
                {
                    "page": p.get("page"),
                    "line_index": p.get("line_index"),
                    "char_offset": p.get("char_offset") or 0,
                    "title": (p.get("title") or "").strip()[:30],
                    "reasons": p.get("reasons") or [],
                    "confidence": p.get("confidence"),
                }
            )
        return rows

    b_stats, a_stats = b_result["stats"], a_result["stats"]
    parts = [
        f"후보 {b_stats['proposals']} → {a_stats['proposals']}",
        f"채택 {b_stats['accepted']} → {a_stats['accepted']}",
    ]
    if added_keys:
        parts.append(f"새로 잡히는 자리 {len(added_keys)}")
    if removed_keys:
        parts.append(f"빠지는 자리 {len(removed_keys)}")
    if not added_keys and not removed_keys:
        parts.append("경계는 그대로입니다")
    return {
        "before": {"proposals": b_stats["proposals"], "accepted": b_stats["accepted"]},
        "after": {"proposals": a_stats["proposals"], "accepted": a_stats["accepted"]},
        "added": _show(a_acc, added_keys),
        "removed": _show(b_acc, removed_keys),
        "added_total": len(added_keys),
        "removed_total": len(removed_keys),
        "changes": changed_fields(before, after),
        "summary": " · ".join(parts),
    }
