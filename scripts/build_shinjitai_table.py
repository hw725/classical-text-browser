"""일본 신자체 → 정자 단방향 변환표를 만든다 (D-138).

OCR 엔진 중 NDL古典籍OCR(lite·full)은 일본 번각 관례로 학습해 원본의 정자(學·傳·歲)를
신자체(学·伝·歳)로 쓴다. 원본의 글자가 아니라 엔진의 인공물이므로 엔진 출력 단계에서
정자로 되돌린다. 단 **1:1로 확정되는 글자만** 바꾸고, 갈리는 글자는 바꾸지 않고 표시만 한다.

판정 규칙 (OpenCC `JPShinjitaiCharacters.txt`의 한 줄 = 신자체 TAB 후보들):
  바꾼다    후보가 자기 자신을 뺀 정자 하나뿐이고, 자기 자신이 후보에 없고,
            신자체 글자가 Big5 상용자 구역(1단계, A440–C67E)에 없다.
  보류한다  그 밖 전부. 예) 弁(辨·辯·瓣) — 후보 여럿, 内(内·內) — 자기 자신도 후보,
            欠(缺) — 欠 자체가 한문의 상용자(Big5 1단계)라 원본이 欠일 수 있다.
  Big5 1단계 판정을 쓰는 이유: «이 글자가 중국·대만 정자 문헌에서 독립 글자로 흔히 쓰이는가»를
  외부 자료 없이 재는 가장 싼 근사다. 伝은 Big5 2단계(드문 글자)라 바꾸고, 欠·余·芸·台는
  1단계라 보류한다(2026-10-07 실측).

입력: --opencc-file 로 받은 파일, 없으면 OpenCC 저장소에서 내려받는다(Apache-2.0).
출력: resources/jp_shinjitai_seiji.json — {_source, _rule, map{신:정}, ambiguous{신:[후보]}}
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

# 한자 출력 — Windows cp949 콘솔에서 죽지 않게(CJK 계약 E3)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "resources" / "jp_shinjitai_seiji.json"
URL = "https://raw.githubusercontent.com/BYVoid/OpenCC/master/data/dictionary/JPShinjitaiCharacters.txt"


def big5_level1(ch: str) -> bool:
    try:
        b = ch.encode("cp950")
    except UnicodeEncodeError:
        return False
    return len(b) == 2 and 0xA440 <= int.from_bytes(b, "big") <= 0xC67E


def build(text: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    conv: dict[str, str] = {}
    amb: dict[str, list[str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "\t" not in line:
            continue
        shin, vals = line.split("\t", 1)
        shin = shin.strip()
        values = vals.split()
        if len(shin) != 1:
            continue
        cands = [v for v in values if v != shin and len(v) == 1]
        if not cands:
            continue
        if len(cands) == 1 and shin not in values and not big5_level1(shin):
            conv[shin] = cands[0]
        else:
            amb[shin] = cands
    return conv, amb


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--opencc-file", type=Path, help="이미 내려받은 JPShinjitaiCharacters.txt")
    ap.add_argument("--opencc-commit", default="", help="그 파일의 OpenCC 커밋 SHA(출처 기록용)")
    a = ap.parse_args(argv)
    if a.opencc_file:
        text = a.opencc_file.read_text(encoding="utf-8")
    else:
        with urllib.request.urlopen(URL, timeout=120) as r:  # noqa: S310 — 고정 URL
            text = r.read().decode("utf-8")
    conv, amb = build(text)
    data = {
        "_source": {"name": "OpenCC (BYVoid/OpenCC) data/dictionary/JPShinjitaiCharacters.txt",
                    "url": URL,
                    "commit": a.opencc_commit or None, "license": "Apache-2.0 (https://github.com/BYVoid/OpenCC/blob/master/LICENSE)",
                    "retrieved": date.today().isoformat()},
        "_rule": (
            "1:1 확정만 map — 후보 하나·자기 자신 후보 아님·신자체가 Big5 1단계 상용자 아님. "
            "나머지는 ambiguous(바꾸지 않고 표시). D-138"
        ),
        "map": dict(sorted(conv.items())),
        "ambiguous": dict(sorted(amb.items())),
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{OUT} — 변환 {len(conv)}자 · 보류 {len(amb)}자")
    return 0


if __name__ == "__main__":
    sys.exit(main())
