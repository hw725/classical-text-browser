#!/usr/bin/env python3
"""사각지대 실측 — 시험이 «본문을 돌린» 함수를 센다.

왜 이 스크립트가 필요한가:
    이 저장소는 사각지대를 기억이 아니라 실측으로 찾기로 했다(CLAUDE.md
    「올릴 때 절차」 3). 그 측정을 두 세션이 각자 스크래치패드에 다시 써서
    두 번 버렸다 — 2026-09-21 古典籍 Lite·Full(인식 코드가 한 줄도 안 돌고
    있었다), 2026-09-22 D-128 모듈 여섯(죽은 함수 셋과 「화면 없는 라우트」가
    거기서 나왔다). 세 번째로 다시 쓰지 않도록 여기 둔다.

줄 커버리지와 무엇이 다른가:
    coverage.py 의 줄 커버리지는 「import 돼서 `def` 줄이 실행됐다」를 실행으로
    센다. 여기서 묻는 것은 **「그 함수의 본문이 한 번이라도 돌았는가」**다.
    엔진 클래스가 import 되고 `is_available()`만 불리는 상황에서 줄 커버리지는
    그럴듯한 숫자를 주지만, 인식 코드는 한 줄도 안 돈다.

한계 — 이 측정이 주장하지 않는 것:
    「들어갔다」는 「제대로 잰다」가 아니다. 한 번 들어갔어도 분기 절반이 안 돌 수
    있고, 시험이 값을 확인하지 않아도 진입은 기록된다. 이 측정이 짚는 것은
    **초록인데 한 줄도 안 도는 자리**뿐이다. 그 이상을 주장하면 안 된다.

사용법:
    uv run python scripts/measure_blind_spots.py src/core/connectome.py
    uv run python scripts/measure_blind_spots.py src/ocr/ndlocr_engine.py -- -q tests/test_ocr.py

    `--` 뒤는 pytest 에 그대로 넘긴다(없으면 시험 전체를 돌린다).
    `--json <경로>`로 결과를 저장한다.

주의: 계측 때문에 시험이 느려진다(전체 스위트 실측 7분 → 10분). 첫 진입만
    기록하고 그 자리를 끄기 때문에 이 정도에서 멈춘다.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


# CJK Text Contract E3 — 한국어 Windows 콘솔은 cp949 라 «—»·«✓» 를 print 하면
# UnicodeEncodeError 로 즉사한다. 이 PC 는 PYTHONUTF8=1 이 박혀 있어 겪지 않는다.
from core.console import force_utf8_console

force_utf8_console()

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"


def defined_functions(path: Path) -> dict[str, int]:
    """파일에 정의된 함수의 「정규화 이름」 → 시작 줄.

    입력: path — 파이썬 소스 파일.
    출력: {qualname: lineno}. 클래스 안의 메서드는 `Klass.method`,
          중첩 함수는 `outer.<locals>.inner` — `code.co_qualname`과 맞춘 꼴이다.

    왜 ast 인가: import 해서 `inspect` 로 훑으면 import 부작용이 돌고, 조건부로
    정의된 함수를 놓친다. 소스를 읽는 편이 「정의된 것 전부」에 가깝다.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, int] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix}{child.name}"
                out[qual] = child.lineno
                walk(child, f"{qual}.<locals>.")
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            else:
                walk(child, prefix)

    walk(tree, "")
    return out


def main(argv: list[str]) -> int:
    """대상 파일을 계측하며 pytest 를 돌리고, 안 도는 함수를 짚는다.

    입력: argv — 대상 파일들 + 선택 `--json <경로>` + 선택 `-- <pytest 인자…>`.
    출력: pytest 의 종료 코드. 사람이 읽는 표는 표준출력으로 찍는다.
    """
    if "--" in argv:
        cut = argv.index("--")
        targets_raw, pytest_args = argv[:cut], argv[cut + 1 :]
    else:
        targets_raw, pytest_args = argv, []

    json_out = None
    if "--json" in targets_raw:
        i = targets_raw.index("--json")
        if i + 1 >= len(targets_raw):
            print("--json 뒤에 저장할 경로가 없습니다.")
            return 2
        json_out = Path(targets_raw[i + 1])
        targets_raw = targets_raw[:i] + targets_raw[i + 2 :]

    if not targets_raw:
        print(__doc__)
        return 2

    targets: dict[str, str] = {}
    for raw in targets_raw:
        p = Path(raw)
        if not p.is_absolute():
            p = (REPO / raw).resolve()
        if not p.exists():
            print(f"대상 파일이 없습니다: {p}\n→ 저장소 루트 기준 경로로 주세요.")
            return 2
        try:
            label = str(p.relative_to(SRC))
        except ValueError:
            label = p.name
        targets[str(p)] = label.replace("\\", "/")

    entered: set[tuple[str, str]] = set()
    mon = sys.monitoring
    tool_id = 5  # 0~5 중 뒤쪽 — coverage.py 가 쓰는 것과 겹치지 않게

    def on_py_start(code, instruction_offset):  # noqa: ANN001, ARG001
        """함수 본문에 들어갈 때마다 불린다.

        `DISABLE`을 돌려주어 같은 자리에서 다시 불리지 않게 한다 — 이것이 없으면
        시험 전체가 몇 배 느려진다(첫 진입만 알면 되는 측정이다).
        """
        label = targets.get(code.co_filename)
        if label is not None:
            entered.add((label, code.co_qualname))
        return mon.DISABLE

    mon.use_tool_id(tool_id, "blindspots")
    mon.register_callback(tool_id, mon.events.PY_START, on_py_start)
    mon.set_events(tool_id, mon.events.PY_START)

    sys.path.insert(0, str(SRC))
    import pytest  # noqa: PLC0415 — 계측을 켠 뒤에 들여온다

    rc = pytest.main(pytest_args or ["-q", "--no-header", "-p", "no:cacheprovider"])

    mon.set_events(tool_id, 0)
    mon.free_tool_id(tool_id)

    report: dict[str, dict] = {}
    for path_str, label in targets.items():
        defined = defined_functions(Path(path_str))
        hit = {q for (n, q) in entered if n == label}
        missed = {q: ln for q, ln in defined.items() if q not in hit}
        # 컴프리헨션·람다는 co_qualname 꼴이 달라 노이즈가 된다 — 이름으로 걸러낸다.
        for q in [q for q in missed if "<" in q and "<locals>" not in q]:
            missed.pop(q, None)
        report[label] = {
            "defined": len(defined),
            "entered": len(defined) - len(missed),
            "missed": dict(sorted(missed.items(), key=lambda kv: kv[1])),
        }

    print("\n" + "=" * 64)
    print("함수 진입 실측 — 시험이 「본문을 돌린」 함수")
    print("=" * 64)
    total_def = total_hit = 0
    for label, r in report.items():
        total_def += r["defined"]
        total_hit += r["entered"]
        mark = "✓" if not r["missed"] else "·"
        print(f"{mark} {label:34s} {r['entered']:3d}/{r['defined']:3d}")
        for q, ln in r["missed"].items():
            print(f"    안 돈다  {label}:{ln}  {q}")
    print("-" * 64)
    print(f"  합계 {total_hit}/{total_def}")
    print("  「들어갔다」는 「제대로 잰다」가 아니다 — 한 줄도 안 도는 자리만 짚는다.")

    if json_out is not None:
        json_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  보고서: {json_out}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
