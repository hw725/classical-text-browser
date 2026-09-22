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
import subprocess
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


# ── 배치 파일은 ASCII만 ─────────────────────────────────────────


@pytest.mark.parametrize("name", ["start_server.bat", "doctor.bat", "install.bat"])
def test_batch_files_are_ascii(name):
    """`.bat` 파일에 비ASCII 바이트가 없어야 한다.

    왜: `chcp 65001` 상태의 cmd.exe는 다중바이트 문자가 든 배치 파일에서 자기 위치를
    잘못 세어, 뒤쪽 줄의 중간부터 다시 읽는다. 한글 REM 주석이 늘어나자 새 콘솔에서
    `'3개처럼' is not recognized as an internal or external command`가 찍혔다
    (2026-09-03 실측, 주석을 영어로 바꾸자 사라짐). 하네스 안(콘솔 없음)에서는
    chcp가 실패해 cp949로 읽히므로 재현되지 않는다 — 그래서 사람 눈이 아니라
    바이트 검사로 막는다. install.bat도 ASCII 껍데기가 됐다(한글은 install.ps1에).
    """
    data = (_ROOT / name).read_bytes()
    bad = [(i + 1, line) for i, line in enumerate(data.split(b"\n")) if any(b > 127 for b in line)]
    assert not bad, f"{name}에 비ASCII 줄이 있습니다 (cmd 파싱 오류 원인): {bad[:3]}"


def _tracked_ps1() -> list[str]:
    """추적되는 `.ps1` 전부 — 파일 하나가 아니라 **종류**를 덮는다.

    2026-09-22에 `install.ps1`만 검사하고 있어서, 같은 규칙이 필요한
    `scripts/build_installer.ps1`이 **한글 150바이트에 BOM 없이 LF**로 남아 있었다.
    새 `.ps1`이 생겨도 자동으로 걸리도록 목록을 git에서 받는다.
    """
    import subprocess

    out = subprocess.run(
        ["git", "ls-files", "*.ps1"],
        cwd=_ROOT, capture_output=True, text=True, check=False,
    ).stdout.split()
    assert out, "추적되는 .ps1을 찾지 못했다"
    return out


@pytest.mark.parametrize("name", _tracked_ps1())
def test_ps1_files_have_bom_and_crlf(name):
    """`.ps1`은 UTF-8 BOM + CRLF여야 한다 — 한 파일이 아니라 전부.

    BOM이 없으면 PowerShell 5.1이 ANSI로 읽어 **한글이 깨진다.** 깨진 채로도
    스크립트는 돌기 때문에(구문이 아니라 글자만 깨진다) 눈으로 보기 전에는 모른다 —
    그래서 바이트로 막는다. `.gitattributes`도 `*.ps1 text eol=crlf`로 못박는다.
    """
    raw = (_ROOT / name).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), f"{name}에 UTF-8 BOM이 없다"
    assert b"\r\n" in raw, f"{name} 줄바꿈은 CRLF여야 한다"
    assert b"\n" not in raw.replace(b"\r\n", b""), f"{name}에 LF만 있는 줄이 섞여 있다"


def test_installer_zip_tag_matches_pyproject():
    """설치 파일이 받는 판이 `pyproject.toml`의 판과 같아야 한다.

    왜 기계가 봐야 하는가: `installer/ctb_setup.py`의 `ZIP_URL`은 릴리스 태그를
    **손으로 박아 둔다**(`docs/maintenance.md` 9-1이 그 단계를 적어 두었다).
    잊으면 `CTB-Setup.exe`가 **조용히 옛 판을 내려받는다** — 받는 사람은 새 판을
    깐 줄 안다. 이 저장소는 같은 모양에 이미 한 번 물렸다: `.venv-gpu`의
    메타데이터가 1.2.1에 멈춰 화면이 옛 판을 표시했고, Codex·문서 에이전트·
    pytest 1,017건을 전부 통과한 뒤에 사람 눈에 띄었다.

    여기서 **태그가 원격에 실제로 있는지는 보지 않는다** — 판을 올린 뒤 태그를
    밀기 전 사이에는 없는 것이 정상이고, 시험이 네트워크에 매달리면 안 된다.
    그 확인은 릴리스 절차의 몫이다.
    """
    import re

    import tomllib

    version = tomllib.loads(
        (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    setup = (_ROOT / "installer" / "ctb_setup.py").read_text(encoding="utf-8")
    m = re.search(r"archive/refs/tags/v([\d.]+)\.zip", setup)
    assert m, "ctb_setup.py에서 ZIP_URL의 태그를 찾지 못했다"
    assert m.group(1) == version, (
        f"설치 파일이 받는 판 v{m.group(1)} 이 pyproject {version} 과 다르다 — "
        "판을 올렸으면 installer/ctb_setup.py의 ZIP_URL도 함께 고친다"
        "(docs/maintenance.md 9-1)."
    )


# ─────────────────────────────────────────────────────────────
# 배포되는 진입점이 cp949 콘솔에서 죽지 않는가
# ─────────────────────────────────────────────────────────────

# 남의 PC에서 도는 것. `scripts/*.py`는 여기 없지만 **예외가 아니다** —
# `test_cjk_contract_is_clean`이 `scripts/` 전체를 본다. 한때 「개발용이라 해당
# 없음」으로 빼 두었다가, 그 안에 `doctor.py`가 있는 것을 놓쳤다(2026-09-22):
# `doctor.bat`이 부르는 것이라 **환경이 깨졌을 때 사용자가 누르는** 자리다.
_SHIPPED_ENTRYPOINTS = (
    "installer/ctb_setup.py",    # CTB-Setup.exe — 표준 라이브러리만이라 같은 처리를 직접 품는다
    "scripts/warmup_paddle.py",  # install.ps1 [5/5] · install.sh 5단계
    "src/cli/__main__.py",       # `ctb` 명령
    "src/app/__main__.py",       # start_server.bat 이 `-m app serve --reload`로 띄운다
)


@pytest.mark.parametrize("name", _SHIPPED_ENTRYPOINTS)
def test_shipped_entrypoints_harden_the_console(name):
    """배포 진입점은 콘솔을 UTF-8로 고정해야 한다 — **의존성 없는 바닥.**

    왜 필요한가: 한국어 Windows 콘솔의 기본은 cp949다. 한글은 cp949에 있지만
    `—`·`«»`·`✓`는 **없어서**, 그런 글자를 `print`하면 `UnicodeEncodeError`로
    프로그램이 즉사한다.

    이 개발 PC는 사용자 환경변수 `PYTHONUTF8=1`이 박혀 있어 **겪지 않는다.**
    받는 사람의 PC에는 없다 — 「내 PC에서 잘 돌았다」가 증거가 못 되는 자리다.

    여기서는 **탐지하지 않고 구조만 본다**(고정을 부르는가). 탐지는
    `test_cjk_contract_is_clean`이 정본 판정기로 한다. 판정을 두 곳에 두면
    반드시 어긋난다 — claude-skills에서 자체 탐지기를 만들었다가 `fitz.open()`·
    `path.open("rb")`·지역 함수 `read_text()`를 위반으로 읽어 거짓 5건을 냈다
    (2026-09-22).

    이 시험은 claude-skills가 없어도 돈다. 그래서 바닥이다.
    """
    import ast

    source = (_ROOT / name).read_text(encoding="utf-8")
    tree = ast.parse(source)

    def _hardens(node) -> list[int]:
        return [
            n.lineno
            for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and (
                (isinstance(n.func, ast.Name) and n.func.id == "force_utf8_console")
                or (isinstance(n.func, ast.Attribute) and n.func.attr == "reconfigure")
            )
        ]

    assert _hardens(tree), (
        f"{name}: 콘솔 고정을 부르지 않는다 — 진입점 맨 앞에서 "
        "`from core.console import force_utf8_console` 를 부른다"
        "(홀로 도는 exe는 같은 처리를 직접 품는다)."
    )

    # **부르는 것만으로는 부족하다 — 먼저 불러야 한다.**
    # `installer/ctb_setup.py` 는 2026-09-22까지 고정을 `parse_args()`·`gui()` **뒤**에
    # 두고 있었다. 그래서 `--auto` 경로에서만 실행됐고 `--help` 와 GUI 는 고정 없이
    # 돌았다. 그때는 그 앞에서 찍는 cp949 불가 문자가 없어 안 죽었지만, help 문구에
    # «—» 하나만 들어가면 사용자 콘솔에서 `--help` 가 죽는다.
    # 「문자열이 있다」만 보는 시험은 이것을 구조적으로 볼 수 없다 — 닿는다 ≠ 돈다.
    #
    # 보는 범위는 **진입 함수의 몸통 안**이다. 파일 전체로 보면 앞쪽에 정의된 헬퍼의
    # `print` 에 걸려 거짓이 난다 — 줄 순서는 실행 순서가 아니다(이 시험을 처음 쓸 때
    # 실제로 `src/cli/__main__.py` 를 그렇게 잘못 잡았다).
    entry_names = {
        n.func.id
        for blk in tree.body
        if isinstance(blk, ast.If)
        for n in ast.walk(blk)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    entries = [
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name in entry_names
    ]
    if not entries:
        return  # `if __name__` 블록이 함수를 안 부르면 순서를 말할 수 없다

    for fn in entries:
        h = _hardens(fn)
        if not h:
            continue  # 모듈 최상위에서 고정하는 모양 — 언제나 먼저다
        outputs = [
            n.lineno
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and (
                (isinstance(n.func, ast.Name) and n.func.id in ("print", "input"))
                or (isinstance(n.func, ast.Attribute)
                    and n.func.attr in ("parse_args", "print_help", "error"))
            )
        ]
        if outputs:
            assert min(h) < min(outputs), (
                f"{name}: 콘솔 고정(L{min(h)})이 «{fn.name}» 안의 첫 출력·인자 파싱"
                f"(L{min(outputs)})보다 **뒤**에 있다 — 그 앞 경로는 고정 없이 돈다. "
                "진입 함수 맨 앞으로 옮긴다."
            )


def _canonical_checker() -> Path | None:
    """CJK 텍스트 계약의 **정본 판정기**를 찾는다 — 없으면 None.

    두 저장소는 `head-repo/hw725/` 아래 나란히 산다(head-repo CLAUDE.md 구조 지도).
    워크트리에서 돌 때도 찾도록 부모를 거슬러 올라가며 본다.
    """
    for base in [_ROOT, *_ROOT.parents]:
        cand = base / "hw725" / "claude-skills" / "scripts" / "check_cjk_text_contract.py"
        if cand.exists():
            return cand
        cand = base.parent / "claude-skills" / "scripts" / "check_cjk_text_contract.py"
        if cand.exists():
            return cand
    return None


def test_cjk_contract_is_clean():
    r"""`src/`·`scripts/`·`installer/`가 CJK 텍스트 계약을 지키는가.

    조항의 정의와 판정은 이 저장소에 없다 — 정본은
    `hw725/claude-skills`의 `skills/hanmun-research-assistant/SKILL.md`(본문)와
    `scripts/check_cjk_text_contract.py`(AST 판정기)다. 여기서는 **불러 쓴다.**

    | 조항 | 무엇 |
    |---|---|
    | E1 | 내장 `open()` 텍스트 모드에 `encoding=` 의무 |
    | E2 | `Path.read_text()`·`write_text()`에 `encoding=` 의무 |
    | E3 | 한글·한자를 출력하는 진입점은 stdout/stderr를 UTF-8로 고정 |
    | R1 | CJK 문자클래스는 `regex`의 `\p{Han}`·`\p{Hangul}`로 (stdlib `re` 금지) |

    2026-09-22에 처음 돌렸을 때 16건이 나왔다. 그중 **셋은 배포되는 것**이었다 —
    `src/core/updater.py`·`src/ocr/paddle_worker.py`·`scripts/doctor.py`. 특히
    `doctor.py`는 `doctor.bat`이 부르는 것이라 **환경이 깨졌을 때 사용자가 누르는**
    자리인데, 세 파일 모두 `«`·`»`·`—`·`✓`를 품고 있어 cp949 콘솔에서 죽었다.

    `src/ocr/ndlocr/`는 뺀다 — 국립국회도서관(NDL)에서 벤더링한 상류 원본이다
    (`LICENCE`, CC-BY-4.0). 전역 규칙 §8: 상류 원문은 손대지 않는다. 무엇을
    빼는지 보이도록 `--exclude`를 **호출 자리에** 적는다.
    """
    checker = _canonical_checker()
    if checker is None:
        pytest.skip(
            "CJK 계약 정본 판정기를 찾지 못했다 — hw725/claude-skills가 옆에 있어야 한다. "
            "배포본에는 없는 것이 정상이고, 그때는 위의 바닥 시험만 돈다."
        )
    res = subprocess.run(
        [sys.executable, str(checker),
         str(_ROOT / "src"), str(_ROOT / "scripts"), str(_ROOT / "installer"),
         "--exclude", "*/ndlocr/*"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    bad = [ln for ln in res.stdout.splitlines() if ln[:2] in ("E1", "E2", "E3", "R1")]
    assert not bad, "CJK 텍스트 계약 위반:\n" + "\n".join(
        ln.replace(str(_ROOT) + "\\", "") for ln in bad[:12]
    )


def test_doctor_registers_src_before_importing_core():
    """`scripts/doctor.py` 가 **경로를 먼저 등록하고** core 를 import 하는가.

    docstring 이 「어느 파이썬으로 실행해도 된다」고 약속하고, `doctor.bat` 도
    가상환경이 둘 다 없으면 시스템 파이썬으로 부른다 — 설치가 중간에 깨진 사람이
    진단을 부르는 바로 그 상황이다. 그 순서가 뒤집히면 그 사람은 진단 보고서 대신
    ModuleNotFoundError 를 받는다(Codex 지적 2026-09-22).

    문자열이 있는지가 아니라 **순서**를 본다 — 둘 다 있어도 순서가 틀리면 못 돈다.
    """
    import ast

    src = (_ROOT / "scripts" / "doctor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    insert_line = None
    core_import_line = None
    for node in ast.walk(tree):
        if (
            insert_line is None
            and isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "insert"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "path"
        ):
            insert_line = node.lineno
        if (
            core_import_line is None
            and isinstance(node, ast.ImportFrom)
            and (node.module or "").startswith("core")
        ):
            core_import_line = node.lineno

    assert insert_line is not None, "doctor.py 가 sys.path 에 src 를 등록하지 않는다"
    assert core_import_line is not None, "doctor.py 가 core 를 import 하지 않는다"
    assert insert_line < core_import_line, (
        "doctor.py: sys.path.insert(%d행)가 core import(%d행)보다 **뒤**다.\n"
        "  가상환경 밖의 파이썬으로 부르면 ModuleNotFoundError 가 난다 —\n"
        "  doctor.bat 이 그렇게 부르는 길이 있다." % (insert_line, core_import_line)
    )

    # **그리고 콘솔 고정은 여전히 첫 출력보다 앞이어야 한다**(E3).
    # 경로 등록을 앞으로 옮기면서 고정이 뒤로 밀릴 수 있는데, 순서 검사 하나만으로는
    # 그것을 못 본다 — 둘 다 만족해야 맞다(Codex 지적 2026-09-23).
    harden_line = None
    first_output = None
    for node in ast.walk(tree):
        if (
            harden_line is None
            and isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "force_utf8_console"
        ):
            harden_line = node.lineno
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
            and (first_output is None or node.lineno < first_output)
        ):
            first_output = node.lineno

    assert harden_line is not None, "doctor.py 가 force_utf8_console() 을 부르지 않는다"
    assert first_output is None or harden_line < first_output, (
        "doctor.py: 콘솔 고정(%s행)이 첫 print(%s행)보다 뒤다 — cp949 콘솔에서 죽는다"
        % (harden_line, first_output)
    )


def test_installer_launch_rebuilds_path():
    """설치본의 「지금 실행」이 **PATH 를 다시 만들어** 넘기는가.

    `install.ps1` 은 uv 를 깔고 자기 창의 PATH 를 갱신하지만 그것은 자식 프로세스다.
    설치본이 낡은 환경 그대로 `start_server.bat` 을 띄우면, bat 이 맨 앞에서
    `uv --version` 을 보고 없다며 「install.bat 을 먼저 실행하세요」로 끝난다 —
    **uv 가 없던 PC 의 사람이 설치에 성공하고도 첫 실행에서 막힌다**
    (Codex 지적 2026-09-22). 이 판이 겨냥한 바로 그 사람이다.

    `launch()` 안에서 `env=` 로 넘기는지까지 본다 — 함수만 있고 안 쓰면 소용없다.
    """
    import ast

    src = (_ROOT / "installer" / "ctb_setup.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    launch = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "launch"),
        None,
    )
    assert launch is not None, "ctb_setup.py 에 launch() 가 없다"

    body = ast.dump(launch)
    assert "fresh_path" in body, (
        "launch() 가 PATH 를 다시 만들지 않는다 — 방금 깐 uv 를 못 찾는다"
    )
    popen = next(
        (n for n in ast.walk(launch)
         if isinstance(n, ast.Call)
         and isinstance(n.func, ast.Attribute)
         and n.func.attr == "Popen"),
        None,
    )
    assert popen is not None, "launch() 가 프로세스를 띄우지 않는다"
    assert any(kw.arg == "env" for kw in popen.keywords), (
        "launch() 의 Popen 이 env= 를 넘기지 않는다 — 다시 만든 PATH 가 쓰이지 않는다"
    )


def test_download_reads_rfc5987_filename():
    """화면이 내려받기 이름으로 **`filename*=` 를 먼저** 읽는가.

    HTTP 헤더는 latin-1 이라 한글 제목은 RFC 5987 로만 실어 보낼 수 있고, 서버는
    ASCII 대체 이름과 함께 둘을 보낸다. 화면이 `filename=` 만 읽으면 **서버를 고쳐도
    사람이 받는 이름은 그대로 비어 있다** — 500 은 없어졌는데 한글 이름은 안 돌아온다
    (Codex 지적 2026-09-22). 고친 자리가 화면까지 닿는지 보지 않은 자리였다.
    """
    src = (_ROOT / "src" / "app" / "static" / "js" / "workspace.js").read_text(
        encoding="utf-8"
    )
    assert "filename\\*=UTF-8''" in src or "filename\\*=" in src, (
        "workspace.js 가 filename*= 를 읽지 않는다 — 한글 파일명이 화면에서 사라진다"
    )
    assert "decodeURIComponent" in src, (
        "filename*= 를 찾아도 percent-decode 하지 않으면 %EC%B2%9C… 가 파일 이름이 된다"
    )
