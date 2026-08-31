"""문서 수치가 코드 실측과 일치하는지 검사한다 (scripts/check_doc_drift.py 편입).

왜 이 시험이 필요한가:
    문서에 손으로 적은 수치는 반드시 어긋난다. `server.py` 머리말이 라우트 수를
    documents 34·interpretations 23·llm_ocr 14로 적은 채 실제(40·25·20)와 오래
    어긋나 있었다 (docs/maintenance.md 6장). 셀 수 있는 수치의 드리프트는
    사람 눈이 아니라 기계가 잡아야 한다.

왜 pytest 에 얹는가:
    릴리스 절차 1단계가 «pytest 전부 통과»이고, feat/refactor/release 커밋은
    doc-sync 게이트가 이미 걸려 있다. 별도 게이트를 새로 만들면 게이트가
    늘어나기만 하므로, 기존 관문(pytest)에 편입한다.

검사 로직의 정본은 scripts/check_doc_drift.py 하나다 — 여기서는 그것을
경로로 불러 쓸 뿐, 판정 규칙을 복제하지 않는다 (두 벌이 되면 그 자체가
새 드리프트가 된다).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _load_checker():
    """scripts/check_doc_drift.py 를 모듈로 불러온다.

    scripts/ 는 배포 패키지(src/*)가 아니므로 import 경로에 없다.
    경로로 직접 불러와야 검사 로직을 한 벌로 유지할 수 있다.

    sys.modules 등록이 필요한 이유: 그 파일은 `from __future__ import
    annotations`를 쓰는데, dataclass 가 문자열 어노테이션을 풀 때
    sys.modules[모듈명]을 찾는다. 등록 없이 exec 하면 AttributeError 가 난다.
    """
    path = _ROOT / "scripts" / "check_doc_drift.py"
    spec = importlib.util.spec_from_file_location("check_doc_drift", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_doc_drift"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return _load_checker()


def test_docs_match_code(checker):
    """대상 문서 4곳의 수치 주장이 전부 실측과 일치해야 한다."""
    mismatches = checker.collect_mismatches(_ROOT)
    detail = "\n".join(mm.format() for mm in mismatches)
    assert not mismatches, (
        f"문서와 코드가 어긋났다 ({len(mismatches)}건) — 코드가 기준이다:\n{detail}"
    )


def test_scanner_actually_catches_drift(checker):
    """검사기가 틀린 수치를 정말 잡는지 확인한다.

    왜: 이 저장소의 교훈 — 시험은 «그 버그를 실제로 잡는지»까지 봐야 한다
    (D-073: 3.x 분기가 존재만 하고 실행되지 않았다). 문서가 지금 다 맞으면
    test_docs_match_code 는 검사기가 죽어 있어도 통과한다. 일부러 틀린
    문장을 넣어 검사기가 잡아내는지를 본다.
    """
    facts = checker.measure_facts(_ROOT)
    wrong_total = facts["route_total"] + 1
    wrong_js = facts["js_count"] + 3
    sample = (
        f"실제 API 엔드포인트 {wrong_total}개가 8개 라우터 모듈에 분산\n"
        f"documents.py — 문헌 CRUD (999 라우트)\n"
        f"JS 모듈 {wrong_js}개\n"
        f"ghost_router.py — 존재하지 않는 라우터 (5 라우트)\n"
    )
    found = checker.scan_text(sample, "sample.md", facts)
    descs = [mm.desc for mm in found]

    assert any("라우트 총수" in d for d in descs), "라우트 총수 드리프트를 놓쳤다"
    assert any(d == "documents.py 라우트 수" for d in descs), "라우터별 드리프트를 놓쳤다"
    assert any("JS 모듈 수" in d for d in descs), "JS 모듈 수 드리프트를 놓쳤다"
    assert any("ghost_router" in d for d in descs), "실존하지 않는 라우터 언급을 놓쳤다"


def test_scanner_silent_on_correct_claims(checker):
    """맞는 수치는 잡지 않아야 한다 — 오탐이 잦은 게이트는 곧 무시된다."""
    facts = checker.measure_facts(_ROOT)
    sample = (
        f"엔드포인트 {facts['route_total']}개, {facts['router_count']}개 라우터\n"
        f"JS 모듈 {facts['js_count']}개 · 스키마 {facts['schema_total']}개\n"
    )
    assert checker.scan_text(sample, "sample.md", facts) == []
