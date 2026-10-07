"""엔진 인공물인 일본 신자체를 정자로 — 1:1 확정 글자만 (D-138).

NDL古典籍OCR(lite·full)은 일본 번각 관례로 학습해 원본의 정자(學·傳·歲)를 신자체(学·伝·歳)로
쓴다. 원본에 찍힌 글자가 아니라 엔진이 만든 형태이므로 D-080 결정 1(«사전으로 본문을 고치지
않는다»)의 예외로, **이 엔진들의 출력에만** 적용한다.

- 바꾸는 것: `resources/jp_shinjitai_seiji.json`의 `map`(1:1 확정, 293자 — 学→學·伝→傳 …).
- 바꾸지 않는 것: `ambiguous`(弁→辨·辯·瓣, 芸·余·台·欠처럼 원본이 그 글자일 수 있는 것).
  표시만 남긴다.
- 기록: 블록마다 바꾼 자리(줄·글자 위치·원래 글자)와 보류 자리를 돌려준다. 파이프라인이 이것을
  L2의 `ocr_config.script_normalize`에 쌓는다 — 글자 객체는 스키마가 추가 필드를 받지 않아서다.
  기록이 있으므로 원래 출력으로 되돌릴 수 있다(`revert_block`).
- 문헌 승인(D-080 결정 3): 보류 글자도 그 문헌이 승인한 쌍(예: 為↔爲)이면 바꾼다 —
  OCR 할 때(`normalize_block(approved=…)`)와 이미 저장된 L2 에(`apply_approvals`,
  `scripts/apply_script_approvals.py`).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Callable

TABLE = Path(__file__).resolve().parents[2] / "resources" / "jp_shinjitai_seiji.json"
ENGINES = frozenset({"ndlkotenocr", "ndlkotenocr-full"})


@lru_cache(maxsize=1)
def load_table() -> tuple[dict[str, str], dict[str, list[str]]]:
    data = json.loads(TABLE.read_text(encoding="utf-8"))
    return data["map"], data["ambiguous"]


def applies(engine_id: str | None) -> bool:
    return (engine_id or "") in ENGINES


Approved = Callable[[str, str], bool]


def _approved_target(ch: str, cands: list[str], approved: Approved | None) -> str | None:
    """보류 글자의 후보 가운데 이 문헌이 승인한 것이 **딱 하나**면 그 글자(D-080 결정 3)."""
    if approved is None:
        return None
    hits = [k for k in cands if approved(ch, k)]
    return hits[0] if len(hits) == 1 else None


def normalize_block(ocr_dict: dict, approved: Approved | None = None) -> dict:
    """블록 dict(OcrBlockResult.to_dict 형식)의 줄 text·글자 char 를 제자리에서 바꾼다.

    approved: 이 문헌의 승인 쌍 조회(`load_document_approvals(doc).is_variant`). 보류 글자라도
        후보 중 승인된 것이 하나뿐이면 바꾼다 — 예: 為↔爲 를 승인한 문헌에서만 為→爲.
    출력: {"changed": [[줄, 위치, 원래, 바뀐]] (승인에 따른 것은 끝에 "approved"),
           "ambiguous": [[줄, 위치, 글자, [후보]]]}. 기록 위치는 줄 text 기준.
    """
    conv, amb = load_table()
    rec: dict = {"changed": [], "ambiguous": []}
    for li, line in enumerate(ocr_dict.get("lines") or []):
        text = line.get("text") or ""
        out = []
        for ci, ch in enumerate(text):
            if ch in conv:
                rec["changed"].append([li, ci, ch, conv[ch]])
                out.append(conv[ch])
            elif ch in amb:
                tgt = _approved_target(ch, amb[ch], approved)
                if tgt:
                    rec["changed"].append([li, ci, ch, tgt, "approved"])
                    out.append(tgt)
                else:
                    rec["ambiguous"].append([li, ci, ch, amb[ch]])
                    out.append(ch)
            else:
                out.append(ch)
        line["text"] = "".join(out)
        chars = line.get("characters") or []
        for c in chars:
            ch = c.get("char", "")
            if ch in conv:
                c["char"] = conv[ch]
        if len(chars) == len(text):  # 승인 변환은 위치로만 옮긴다(길이가 맞을 때)
            for r in rec["changed"]:
                if r[0] == li and len(r) == 5 and chars[r[1]].get("char") == r[2]:
                    chars[r[1]]["char"] = r[3]
    return rec


def apply_approvals(ocr_dict: dict, rec: dict, approved: Approved) -> list[list]:
    """이미 저장된 블록에 나중에 승인한 쌍을 반영한다(다시 OCR 하지 않고).

    rec 의 보류 자리 가운데 승인된 것만 바꾸고 rec 를 갱신한다(보류 → changed + "approved").
    그 자리의 글자가 기록과 다르면(사람이 이미 고쳤다) 건드리지 않는다. 출력: 바꾼 항목들.
    """
    lines = ocr_dict.get("lines") or []
    done, keep = [], []
    for li, ci, ch, cands in rec.get("ambiguous", []):
        tgt = _approved_target(ch, cands, approved)
        text = list(lines[li].get("text") or "") if li < len(lines) else []
        if not tgt or ci >= len(text) or text[ci] != ch:
            keep.append([li, ci, ch, cands])
            continue
        text[ci] = tgt
        lines[li]["text"] = "".join(text)
        chars = lines[li].get("characters") or []
        if len(chars) == len(text) and chars[ci].get("char") == ch:
            chars[ci]["char"] = tgt
        done.append([li, ci, ch, tgt, "approved"])
    rec["ambiguous"] = keep
    rec["changed"] = list(rec.get("changed", [])) + done
    return done


def revert_block(ocr_dict: dict, rec: dict) -> None:
    """normalize_block 의 역. 기록된 자리만 원래 글자로 되돌린다."""
    lines = ocr_dict.get("lines") or []
    by_line: dict[int, dict[int, str]] = {}
    for r in rec.get("changed", []):
        by_line.setdefault(r[0], {})[r[1]] = r[2]
    for li, pos in by_line.items():
        if li >= len(lines):
            continue
        text = list(lines[li].get("text") or "")
        for ci, orig in pos.items():
            if ci < len(text):
                text[ci] = orig
        lines[li]["text"] = "".join(text)
        chars = lines[li].get("characters") or []
        if len(chars) == len(text):
            for ci, orig in pos.items():
                chars[ci]["char"] = orig


def summary(records: dict[str, dict]) -> dict:
    """ocr_config.script_normalize 값. 블록 ID → 기록."""
    return {"table": "resources/jp_shinjitai_seiji.json", "decision": "D-138",
            "blocks": {bid: r for bid, r in records.items() if r["changed"] or r["ambiguous"]}}
