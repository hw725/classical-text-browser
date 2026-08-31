#!/usr/bin/env python3
"""문서 드리프트 검사 — 셀 수 있는 수치는 기계가 센다.

왜 이 스크립트가 필요한가:
    문서에 손으로 적은 수치는 반드시 어긋난다. 실제로 `server.py` 머리말이
    documents 34·interpretations 23·llm_ocr 14로 오래 어긋나 있었다
    (실제 40·25·20 — docs/maintenance.md 6장). 릴리스 절차의 /doc-sync
    게이트는 「문서를 봤는가」는 강제하지만, 숫자가 맞는지는 사람 눈에
    의존한다. 셀 수 있는 것은 기계가 세는 편이 낫다.

무엇을 재는가 (코드 = 기준):
    - 라우터별 라우트 수:  src/app/routers/*.py 의 @router.<verb>( 데코레이터
    - 라우트 총수·라우터 모듈 수
    - JS 모듈 수:          src/app/static/js/*.js
    - 스키마 수:           schemas/**/*.json (원본·해석·코어·교환 그룹별 포함)
    - 테스트 파일 수:      tests/test_*.py

어디에 적힌 수치와 대조하는가:
    README.md · AGENTS.md · CLAUDE.md · docs/maintenance.md ·
    docs/architecture-diagrams.md · src/app/server.py 머리말 주석

사용법:
    uv run python scripts/check_doc_drift.py
    어긋난 항목이 있으면 목록을 출력하고 종료 코드 1.
    tests/test_doc_drift.py 가 같은 로직을 pytest 로 감싸므로,
    릴리스 절차 1단계(pytest 전체 통과)에서 자동으로 걸린다.

한계 (알고 쓰기):
    - 문서의 «주장»은 정규식으로 찾는다. 아래 CLAIM_PATTERNS 에 없는 표현으로
      수치를 적으면 이 검사는 그 주장을 보지 못한다. 새 종류의 수치를 문서에
      적을 때는 여기에 패턴도 함께 늘릴 것.
    - **줄 수(38,633줄 같은 것)는 일부러 세지 않는다.** 파일을 한 줄만 고쳐도
      바뀌므로 게이트로 삼으면 거의 매 커밋이 빨개진다. 자주 틀리는 게이트는
      곧 무시되고, 무시되는 게이트는 없는 것만 못하다.
    - **DECISIONS.md·docs/releases/ 는 일부러 보지 않는다.** 거기 적힌 수치는
      «그때 그렇게 검증했다»는 기록이지 현재 상태에 대한 주장이 아니다.
      과거 기록을 현재값으로 고치면 그것은 동기화가 아니라 역사 위조다.
    - 검사 대상 문서가 **「예전에 이렇게 틀려 있었다」며 그 숫자를 인용**하면
      이 검사기는 그것을 현재 주장으로 읽고 걸어 버린다(실제로 겪었다).
      틀렸던 값의 기록은 검사 대상이 아닌 DECISIONS.md 에 남기고, 대상 문서에는
      숫자 없이 쓴다. **일부러 무시 표시(drift-ignore 류)는 두지 않았다** —
      이 저장소의 사고는 전부 «가드가 실패를 침묵으로 바꾼» 모양이었고
      (maintenance.md 3장), 억제 장치는 언젠가 진짜 드리프트를 덮는다.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

# 이 파일은 scripts/ 아래에 있으므로 저장소 루트는 한 단계 위다.
ROOT = Path(__file__).resolve().parent.parent

# 수치가 적혀 있어 대조 대상이 되는 문서·코드 파일 (저장소 루트 기준 상대 경로).
#
# README.md·AGENTS.md 가 들어 있는 이유: 실제로 드리프트가 살던 곳이다.
# 이 검사기를 처음 붙인 날 AGENTS.md 의 «테스트 39파일»이 실제 41과
# 어긋나 있었는데, 그때 대상이 아래 넷뿐이라 검사기가 그것을 보지 못했다.
# 사람이 읽는 문서가 아니라 **에이전트가 먼저 읽는 문서**라 더 위험하다.
DOC_TARGETS = [
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/maintenance.md",
    "docs/architecture-diagrams.md",
    "src/app/server.py",  # 머리말 docstring 에 라우터별 수치가 있다
]

# FastAPI 라우트 데코레이터. maintenance.md 6장의 «세는 명령»(grep)과 같은 기준을
# 쓴다 — 두 곳이 다른 기준으로 세면 검사 자체가 새 드리프트가 된다.
ROUTE_DECORATOR = re.compile(r"^@router\.(?:get|post|put|patch|delete)\(", re.MULTILINE)


@dataclass
class Mismatch:
    """문서의 주장과 실측이 어긋난 한 건."""

    relpath: str  # 어느 문서
    lineno: int  # 몇째 줄
    desc: str  # 무엇에 대한 주장인가
    claimed: int  # 문서에 적힌 값
    actual: int  # 코드에서 실측한 값
    line: str  # 해당 줄 원문 (사람이 바로 찾아 고치도록)

    def format(self) -> str:
        return (
            f"  {self.relpath}:{self.lineno} — {self.desc}: "
            f"문서 {self.claimed} ≠ 실측 {self.actual}\n"
            f"      | {self.line.strip()}"
        )


def measure_facts(root: Path = ROOT) -> dict:
    """코드에서 셀 수 있는 사실을 전부 실측한다.

    반환:
        {
          "routers":       {"documents": 40, ...},   # 라우터별 라우트 수
          "route_total":   183,
          "router_count":  8,
          "js_count":      29,
          "schema_groups": {"source_repo": 7, "interp": 5, "core": 6, "exchange": 1},
          "schema_total":  19,
          "test_file_count": 41,
        }
    """
    routers: dict[str, int] = {}
    for p in sorted((root / "src" / "app" / "routers").glob("*.py")):
        if p.name == "__init__.py":
            continue
        routers[p.stem] = len(ROUTE_DECORATOR.findall(p.read_text(encoding="utf-8")))

    schemas_dir = root / "schemas"
    schema_groups = {
        "source_repo": len(list((schemas_dir / "source_repo").glob("*.json"))),
        "interp": len(list((schemas_dir / "interp").glob("*.json"))),
        "core": len(list((schemas_dir / "core").glob("*.json"))),
        # 교환 스키마(exchange.schema.json)는 하위 폴더 없이 루트에 있다.
        "exchange": len(list(schemas_dir.glob("*.json"))),
    }

    return {
        "routers": routers,
        "route_total": sum(routers.values()),
        "router_count": len(routers),
        "js_count": len(list((root / "src" / "app" / "static" / "js").glob("*.js"))),
        "schema_groups": schema_groups,
        "schema_total": sum(schema_groups.values()),
        "test_file_count": len(list((root / "tests").glob("test_*.py"))),
    }


# ── 문서 속 «주장» 추출 패턴 ──────────────────────────────────────────────
#
# 각 항목: (설명, 정규식, 사실 키 목록).
# 정규식의 캡처 그룹 순서대로 사실 키와 짝을 맞춘다.
# 사실 키가 "router:<이름>" 이면 라우터별 수, 그 외에는 measure_facts() 의 키다.
#
# 왜 줄 단위로 검사하나: 어긋난 곳의 줄 번호를 바로 보여 주기 위해서다.
# 지금 문서들의 수치 주장은 전부 한 줄 안에 들어 있다.
#
# 순서가 의미를 가진다: 같은 자리에 두 패턴이 걸리면 먼저 온 것이 이긴다
# (예: «8개 도메인 라우터»는 라우터 패턴이 잡고, 더 느슨한 «N개 도메인»
# 패턴은 겹침 검사로 건너뛴다).
CLAIM_PATTERNS: list[tuple[str, re.Pattern, list[str]]] = [
    # 「documents.py … (40 라우트)」 — CLAUDE.md 트리·server.py 머리말
    (
        "라우터별 라우트 수",
        re.compile(r"([a-z_][a-z0-9_]*)\.py[^\n]*?\((\d+)\s*라우트\)"),
        ["router:@1"],  # 그룹1 = 라우터 이름, 그룹2 = 주장값 (아래 scan 에서 특별 처리)
    ),
    # 「엔드포인트 183개」
    ("라우트 총수", re.compile(r"엔드포인트\s*(\d+)개"), ["route_total"]),
    # 「라우트 183개」
    ("라우트 총수", re.compile(r"라우트\s*(\d+)개"), ["route_total"]),
    # 「(현재 8개, 183 라우트)」 — maintenance.md 6장
    (
        "라우터 수·라우트 총수",
        re.compile(r"현재\s*(\d+)개,\s*(\d+)\s*라우트"),
        ["router_count", "route_total"],
    ),
    # 「8개 라우터」·「8개 도메인 라우터」·「8개 라우터 모듈」
    ("라우터 수", re.compile(r"(\d+)개\s*(?:도메인\s*)?라우터"), ["router_count"]),
    # 「FastAPI + 8 라우터」 (개 없이)
    ("라우터 수", re.compile(r"(\d+)\s+라우터"), ["router_count"]),
    # 「8개 모듈에 분산」 — server.py 머리말
    ("라우터 수", re.compile(r"(\d+)개\s*(?:라우터\s*)?모듈에\s*분산"), ["router_count"]),
    # 「routers/ -- 8개 도메인」 — 다이어그램 노드 라벨
    ("라우터 수", re.compile(r"(\d+)개\s*도메인"), ["router_count"]),
    # 「JS 모듈 29개」·「29개 JS 모듈」
    ("JS 모듈 수", re.compile(r"JS\s*모듈\s*(\d+)개"), ["js_count"]),
    ("JS 모듈 수", re.compile(r"(\d+)개(?:의)?\s*JS\s*모듈"), ["js_count"]),
    # 「JS 29개」 — AGENTS.md 인지 부채 지도의 축약 표기
    ("JS 모듈 수", re.compile(r"JS\s*(\d+)개"), ["js_count"]),
    # 「테스트 41파일」 — AGENTS.md. 테스트 «건수»가 아니라 «파일 수»다.
    # 건수(671 같은 것)는 pytest 를 실제로 돌려야 알 수 있어 정적 검사로는
    # 세지 않는다 — 그래서 문서에도 건수를 박아 두지 않는 편이 낫다.
    ("테스트 파일 수", re.compile(r"테스트\s*(\d+)\s*파일"), ["test_file_count"]),
    # 「코어 스키마 6종」·「코어 스키마 6개 엔티티」 — 반드시 아래의 총수 패턴보다
    # 먼저 와야 한다. 뒤에 오면 «스키마 6개»가 총수 주장으로 오독된다 (실측된 오탐).
    ("코어 스키마 수", re.compile(r"코어\s*스키마\s*(\d+)\s*[개종]"), ["schema_group:core"]),
    # 「스키마 19개」·「19개 스키마」
    ("스키마 총수", re.compile(r"스키마\s*(\d+)개"), ["schema_total"]),
    ("스키마 총수", re.compile(r"(\d+)개\s*스키마"), ["schema_total"]),
    # 「원본 7 + 해석 5 + 코어 6 + 교환 1」 — architecture-diagrams.md
    (
        "스키마 그룹별 수",
        re.compile(r"원본\s*(\d+)\s*\+\s*해석\s*(\d+)\s*\+\s*코어\s*(\d+)\s*\+\s*교환\s*(\d+)"),
        [
            "schema_group:source_repo",
            "schema_group:interp",
            "schema_group:core",
            "schema_group:exchange",
        ],
    ),
    # 「원본 저장소 스키마 (7개)」 등 — maintenance.md 7장 트리
    (
        "원본 스키마 수",
        re.compile(r"원본\s*저장소\s*스키마\s*\((\d+)개\)"),
        ["schema_group:source_repo"],
    ),
    (
        "해석 스키마 수",
        re.compile(r"해석\s*저장소\s*스키마\s*\((\d+)개\)"),
        ["schema_group:interp"],
    ),
    ("코어 스키마 수", re.compile(r"코어\s*엔티티\s*스키마\s*\((\d+)개\)"), ["schema_group:core"]),
]


def _resolve_actual(key: str, facts: dict) -> int | None:
    """사실 키를 실측값으로 푼다. 없는 키면 None (검사 불가로 보고)."""
    if key.startswith("schema_group:"):
        return facts["schema_groups"].get(key.split(":", 1)[1])
    return facts.get(key)


def scan_text(text: str, relpath: str, facts: dict) -> list[Mismatch]:
    """문서 한 편을 줄 단위로 훑어 수치 주장을 찾고 실측과 대조한다.

    입력:  문서 전체 텍스트, 보고용 상대 경로, measure_facts() 결과
    출력:  어긋난 주장 목록 (없으면 빈 리스트)
    """
    mismatches: list[Mismatch] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        # 같은 줄에서 이미 매칭된 구간 — 느슨한 패턴이 앞선 매칭을 다시 잡아
        # 같은 주장을 두 번 보고하는 것을 막는다.
        used_spans: list[tuple[int, int]] = []
        for desc, pattern, keys in CLAIM_PATTERNS:
            for m in pattern.finditer(line):
                if any(m.start() < e and m.end() > s for s, e in used_spans):
                    continue
                used_spans.append(m.span())

                if keys == ["router:@1"]:
                    # 라우터별 주장: 그룹1이 라우터 이름, 그룹2가 주장값.
                    name, claimed = m.group(1), int(m.group(2))
                    actual = facts["routers"].get(name)
                    if actual is None:
                        # 문서가 존재하지 않는 라우터를 말하고 있다 — 그 자체가 드리프트.
                        mismatches.append(
                            Mismatch(relpath, lineno, f"라우터 {name}.py (실존하지 않음)",
                                     claimed, -1, line)
                        )
                    elif actual != claimed:
                        mismatches.append(
                            Mismatch(relpath, lineno, f"{name}.py 라우트 수",
                                     claimed, actual, line)
                        )
                    continue

                for group_idx, key in enumerate(keys, start=1):
                    claimed = int(m.group(group_idx))
                    actual = _resolve_actual(key, facts)
                    if actual is not None and actual != claimed:
                        mismatches.append(
                            Mismatch(relpath, lineno, f"{desc}({key})", claimed, actual, line)
                        )
    return mismatches


def collect_mismatches(root: Path = ROOT) -> list[Mismatch]:
    """대상 문서 전부를 실측과 대조해 어긋난 목록을 돌려준다."""
    facts = measure_facts(root)
    result: list[Mismatch] = []
    for rel in DOC_TARGETS:
        path = root / rel
        # 문서가 사라진 것도 드리프트지만, 여기서는 검사 대상 누락으로 즉시 알린다.
        if not path.exists():
            raise FileNotFoundError(f"검사 대상이 없다: {rel} — DOC_TARGETS 를 손봐야 한다")
        result.extend(scan_text(path.read_text(encoding="utf-8"), rel, facts))
    return result


def main() -> int:
    # Windows 콘솔 기본 인코딩(cp949)에서 한국어가 깨지지 않게 UTF-8 로 강제.
    # 읽을 수 없는 보고는 보고가 아니다 (doc-sync hook.py 에서 실측한 교훈).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    facts = measure_facts()
    mismatches = collect_mismatches()

    print("── 문서 드리프트 검사 ──")
    print(f"실측: 라우트 {facts['route_total']} (라우터 {facts['router_count']}개), "
          f"JS 모듈 {facts['js_count']}개, 스키마 {facts['schema_total']}개 "
          f"(원본 {facts['schema_groups']['source_repo']}·해석 {facts['schema_groups']['interp']}·"
          f"코어 {facts['schema_groups']['core']}·교환 {facts['schema_groups']['exchange']}), "
          f"테스트 {facts['test_file_count']}파일")

    if not mismatches:
        print("문서와 코드가 일치한다. ✓")
        return 0

    print(f"\n어긋난 곳 {len(mismatches)}건 — 문서와 코드가 다르면 코드가 기준이다:")
    for mm in mismatches:
        print(mm.format())
    print("\n→ 위 문서의 수치를 실측값으로 고친 뒤 다시 실행할 것.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
