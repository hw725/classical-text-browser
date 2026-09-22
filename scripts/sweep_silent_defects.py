#!/usr/bin/env python3
"""조용한 결함을 전수로 쓴다 — 예외도 경고도 없이 빗나가는 자리 (2026-09-22).

왜 이 스크립트가 있는가:
    그날 결함 여섯이 «하나 고치면 그 옆에서 또» 하는 식으로 하루 종일 나왔다.
    여섯 다 예외도 경고도 없이 조용히 빗나가는 종류였고 **시험이 잡은 것은 0건**이다.
    그런데 여섯 다 기계로 판정할 수 있었다 — 부딪힐 때마다 재는 대신 한 번에 쓴다.

**여기 있는 것은 «거짓을 안 내는» 검사뿐이다.** 처음에 여덟 가지를 넣었더니 524건이
나왔고, 손으로 세어 보니 대부분 거짓이었다. 거짓을 내는 검사기는 없느니만 못하다 —
다음 사람이 목록을 믿지 않게 되고, 그러면 진짜가 섞여도 묻힌다. 그래서 다섯을 걷어냈다.

걷어낸 것과 이유 (다시 만들 사람을 위해):
    허공 호출        `_이름(` 을 세면 **함수 안의 지역 선언**(`const _v = …`)과
                    문자열 조각(`p02_b01`)과 주석 속 이름까지 걸린다. 7건 전부 거짓이었다.
                    제대로 하려면 JS 를 파싱해야 한다(정규식으로는 안 된다).
    닿을 수 없는 조작  다이얼로그는 `style.display = ""` 로 열린다 — `panelSections`
                    에도 모드 패널에도 없다. 58건 대부분이 그 다이얼로그들이었다.
                    «여는 주체»의 종류를 다 알아야 하는데 그 목록이 열려 있다.
    안 불리는 라우트   CLI·스크립트·다른 라우터가 부르는 것이 많고, 화면이 경로를
                    조각내어 조립하면 문자열로 안 잡힌다. 19건 대부분이 거짓이었다.
    죽은 파이썬 함수   435건이 나왔다. 메서드·데코레이터·간접 참조를 못 가린다.
    죽은 JS 함수      0건이었지만 위와 같은 이유로 믿을 수 없다.

남긴 셋은 **판정이 닫혀 있다** — 볼 것이 파일 안에 다 있고 예외 경로가 없다.

사용법: uv run python scripts/sweep_silent_defects.py [--verbose]
종료 코드: 발견 0이면 0, 있으면 1.
"""

from __future__ import annotations

import ast
import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
JS_DIR = REPO / "src" / "app" / "static" / "js"
INDEX = REPO / "src" / "app" / "static" / "index.html"
SRC = REPO / "src"

VERBOSE = "--verbose" in sys.argv


# ──────────────────────────────────────
# A — 전역 이름 겹침
# ──────────────────────────────────────
#
# 화면 JS 는 classic script 라 최상위 `function` 이 전부 전역이다. 두 파일이 같은
# 이름을 선언하면 **뒤에 적재된 쪽이 이기고**, 앞쪽 파일의 호출까지 남의 구현으로
# 돈다. 예외도 경고도 나지 않는다. 2026-09-22에 여섯이 겹쳐 있었고 — 번역 탭의
# 원문 칸과 현토 탭의 주석 목록이 **받아 놓고 안 그려지고** 있었다.
#
# 판정이 닫힌 이유: 적재 순서는 index.html 이 정하고, 최상위 `function` 선언은
# 줄 첫머리로 확정된다. 볼 것이 이 둘뿐이다.


def load_order() -> list[str]:
    return re.findall(r'src="/static/js/([\w.-]+)\.js', INDEX.read_text(encoding="utf-8"))


def sweep_a_collisions() -> list[str]:
    decls: dict[str, list[str]] = defaultdict(list)
    for name in load_order():
        f = JS_DIR / f"{name}.js"
        if not f.exists():
            continue
        for m in re.finditer(
            r"^(?:async\s+)?function\s+(\w+)\s*\(", f.read_text(encoding="utf-8"), re.M
        ):
            decls[m.group(1)].append(name)
    return [
        f"{k}: {sorted(set(v))} → 이기는 쪽 «{v[-1]}»"
        for k, v in sorted(decls.items())
        if len(set(v)) > 1
    ]


# ──────────────────────────────────────
# B — 느슨한 이스케이프 헬퍼
# ──────────────────────────────────────
#
# D-069 가 적어 둔 규칙이 이것이다 — 「화면에 넣는 파일명·OCR 원문은 이스케이프」.
# 큰따옴표를 안 막으면 `title="…"` 같은 속성 자리에서 속성을 벗어난다. 속성 전용
# 헬퍼(`_escAttr*`)는 작은따옴표까지 막아야 한다.
#
# **지금 텍스트 자리에만 쓰이는 헬퍼도 막아 둔다.** 2026-09-22에 뚫려 있던 자리가
# 정확히 그 모양이었다 — 느슨한 판이 한 배선 거리에서 속성 자리가 됐다.
#
# 판정이 닫힌 이유: 함수 본문 안에 `"/g` 가 있는지, 아니면 `textContent` 방식인지
# 둘 중 하나다.


def _fn_body(text: str, start: int) -> str:
    i = text.index("{", start)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[start : j + 1]
    return ""


def sweep_b_loose_escapes() -> list[str]:
    out = []
    for f in sorted(JS_DIR.glob("*.js")):
        t = f.read_text(encoding="utf-8")
        for m in re.finditer(r"^(?:async\s+)?function\s+(_esc\w*)\s*\(", t, re.M):
            name = m.group(1)
            body = _fn_body(t, m.start())
            if "textContent" in body:
                continue  # DOM 방식 — 브라우저가 전부 막는다
            if '"/g' not in body:
                out.append(f"{f.name}::{name} — 큰따옴표를 안 막는다")
            elif "attr" in name.lower() and "'/g" not in body:
                out.append(f"{f.name}::{name} — 속성용인데 작은따옴표를 안 막는다")
    return out


# ──────────────────────────────────────
# C — 파이썬 중복 정의 (본문까지 같은 것만)
# ──────────────────────────────────────
#
# **JS 의 겹침과 성질이 다르다.** 파이썬은 모듈마다 이름 공간이 따로라 서로 가리지
# 않는다 — 조용한 오동작이 아니라 **유지보수 위험**이다: 한쪽을 고치면 다른 쪽이
# 남고, 고친 사람은 다 고쳤다고 여긴다. 2026-09-22에 `entity.py` 와
# `interpretation.py` 의 `_get_source_head_commit` 이 그 모양이었다(Phase 8부터).
#
# 그래서 이 항목은 «0이어야 한다»가 아니다. 나란한 패키지가 같은 계약을 각자
# 구현하는 것(`ndlocr`·`ndlkotenocr` 의 `get_config_dir` 등)은 설계다. 보고만 하고
# 판단은 사람이 한다 — 다만 **모르는 채로 두지는 않는다.**
#
# 판정이 닫힌 이유: ast 로 본문을 떠서 해시를 견준다. 이름만 같고 본문이 다르면
# 보고하지 않는다 — 그건 우연한 동명이지 중복이 아니다.


def sweep_c_py_duplicates() -> list[str]:
    tops: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for p in SRC.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                dump = ast.dump(ast.Module(body=node.body, type_ignores=[]))
                tops[node.name].append(
                    (str(p.relative_to(REPO)).replace("\\", "/"),
                     hashlib.sha1(dump.encode()).hexdigest()[:8])
                )
    out = []
    for name, places in sorted(tops.items()):
        if len(places) < 2:
            continue
        if len({h for _f, h in places}) == 1:
            out.append(f"{name}: {[f for f, _ in places]}")
    return out


# ──────────────────────────────────────


def main() -> int:
    checks = [
        ("A 전역 이름 겹침 — 뒤가 이긴다", sweep_a_collisions()),
        ("B 느슨한 이스케이프 헬퍼", sweep_b_loose_escapes()),
        ("C 파이썬 중복 정의 — 본문 동일 (가림 아님·유지보수 위험)", sweep_c_py_duplicates()),
    ]
    print("=" * 68)
    print("조용한 결함 전수 검사 (2026-09-22)")
    print("=" * 68)
    total = 0
    for title, found in checks:
        total += len(found)
        print(f"{'✓' if not found else '·'} {title:36s} {len(found):3d}건")
        for item in (found if VERBOSE else found[:10]):
            print(f"      {item}")
        if not VERBOSE and len(found) > 10:
            print(f"      … 그리고 {len(found)-10}건 (--verbose)")
    print("-" * 68)
    silent = sum(len(f) for _t, f in checks[:2])
    print(f"  합계 {total}건 — 그중 «조용히 빗나가는 것» {silent}건 (A·B)")
    print("  이 검사는 «구조적으로 조용한 자리»만 본다 — 동작이 맞는지는 안 본다.")
    print("  시험이 그 함수를 도는지는 scripts/measure_blind_spots.py 가 본다.")
    print("  거짓을 내던 다섯 검사는 걷어냈다 — 이유는 이 파일 머리말에 있다.")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
