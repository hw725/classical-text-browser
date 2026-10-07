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
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

TABLE = Path(__file__).resolve().parents[2] / "resources" / "jp_shinjitai_seiji.json"
ENGINES = frozenset({"ndlkotenocr", "ndlkotenocr-full"})


@lru_cache(maxsize=1)
def load_table() -> tuple[dict[str, str], dict[str, list[str]]]:
    data = json.loads(TABLE.read_text(encoding="utf-8"))
    return data["map"], data["ambiguous"]


def applies(engine_id: str | None) -> bool:
    return (engine_id or "") in ENGINES


def normalize_block(ocr_dict: dict) -> dict:
    """블록 dict(OcrBlockResult.to_dict 형식)의 줄 text·글자 char 를 제자리에서 바꾼다.

    출력: {"changed": [[줄, 글자위치, 원래, 바뀐]], "ambiguous": [[줄, 글자위치, 글자, [후보]]]}.
    줄 text 와 characters 는 따로 바꾼다(엔진에 따라 길이가 다를 수 있다). 기록 위치는 줄 text 기준.
    """
    conv, amb = load_table()
    rec = {"changed": [], "ambiguous": []}
    for li, line in enumerate(ocr_dict.get("lines") or []):
        text = line.get("text") or ""
        out = []
        for ci, ch in enumerate(text):
            if ch in conv:
                rec["changed"].append([li, ci, ch, conv[ch]])
                out.append(conv[ch])
            else:
                if ch in amb:
                    rec["ambiguous"].append([li, ci, ch, amb[ch]])
                out.append(ch)
        line["text"] = "".join(out)
        for c in line.get("characters") or []:
            ch = c.get("char", "")
            if ch in conv:
                c["char"] = conv[ch]
    return rec


def revert_block(ocr_dict: dict, rec: dict) -> None:
    """normalize_block 의 역. 기록된 자리만 원래 글자로 되돌린다."""
    lines = ocr_dict.get("lines") or []
    by_line: dict[int, dict[int, str]] = {}
    for li, ci, orig, _new in rec.get("changed", []):
        by_line.setdefault(li, {})[ci] = orig
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
