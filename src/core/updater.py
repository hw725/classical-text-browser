"""새 판이 나왔는지 보고, 앱 안에서 받아 온다 (D-103).

왜 필요한가: 사용자가 GitHub 저장소를 열어 보지 않으면 새 판이 나온 줄 모른다. 「구버전만
가진 사람이 직접 깃허브에 들어오지 않고도」가 요구였다.

무엇을 하지 않는가:
  - **서고를 건드리지 않는다.** 서고는 앱 폴더 밖에 있고, 이 모듈은 앱 저장소만 다룬다.
  - **작업 트리가 더러우면 받지 않는다.** `git pull --ff-only`가 실패하면 그대로 알린다 —
    사용자가 고친 코드를 조용히 덮어쓰는 일이 없어야 한다.
  - **앱 안에서는 저절로 받지 않는다.** 확인은 자동, 내려받기는 사람이 누를 때만.
    다만 `start_server`가 서버를 켜기 **전**에는 저절로 받는다(D-112) — 켜기 전이라 도중에
    코드가 바뀌는 일이 없고, 사용자가 고친 파일이 있으면 받지 않는다.
  - **zip으로 받은 폴더도 새 판을 안다.** `.git`이 없으면 git 사본으로 바꾼다(파일은 그대로,
    HEAD·index만 원격 main) — 그 뒤로는 커밋으로 비교하고 「받기」가 된다(D-112).

되돌릴 수 없는 판: 릴리스 본문에 「되돌릴 수 없는 변화 — 있음」이 있으면 그 사실을 함께
돌려준다. 화면이 그것을 보여 주고 동의를 받은 뒤에만 받게 하기 위해서다(D-092·D-097처럼
서고 형식을 바꾸는 판이 실제로 있었다).
"""

from __future__ import annotations

import json
import logging
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

REPO = "hw725/classical-text-browser"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
REMOTE_URL = f"https://github.com/{REPO}.git"
_TIMEOUT = 6.0
# zip 폴더를 git 사본으로 바꾼 뒤 «아직 원격에 맞추지 않았다»는 표시. 있으면 작업 트리의 차이는
# 사용자 수정이 아니라 zip 시점의 옛 파일이므로, 「받기」가 reset --hard로 맞춘다.
ZIP_MARK = ".ctb-from-zip"


def app_root() -> Path:
    """앱 저장소 뿌리 (src/core/updater.py → …/classical-text-browser)."""
    return Path(__file__).resolve().parent.parent.parent


def current_version() -> str:
    """지금 판 번호 — **pyproject.toml**에서 읽는다.

    dist-info는 실행 인터프리터의 것이라, GPU PC(.venv-gpu로 뜸)에서는 uv sync가 갱신하는 .venv와
    어긋나 «새 판 있음»이 영원히 켜졌다(리뷰 실측: .venv-gpu 1.2.1 vs pyproject 1.3.0).
    """
    try:
        import tomllib

        with open(app_root() / "pyproject.toml", "rb") as f:
            v = tomllib.load(f).get("project", {}).get("version")
        if v:
            return str(v)
    except Exception:  # noqa: BLE001
        pass
    try:
        from importlib.metadata import version

        return version("classical-text-browser")
    except Exception:  # noqa: BLE001 — 편집 가능 설치가 아닐 때 등
        return "unknown"


def _as_tuple(v: str) -> tuple:
    """«1.3.0» → (1,3,0). 견줄 수 없는 값은 (-1,)로 뒤로 보낸다."""
    parts = v.strip().lstrip("vV").split("-")[0].split(".")
    try:
        return tuple(int(x) for x in parts)
    except ValueError:
        return (-1,)


def check(timeout: float = _TIMEOUT) -> dict:
    """새 판이 있는가.

    출력: {"current", "latest", "update_available", "html_url", "published_at",
           "breaking", "title", "error"}
    네트워크가 없거나 GitHub이 답하지 않으면 error에 까닭을 담고 나머지는 비운다 —
    인터넷 없이 쓰는 것이 정상 사용이므로 이것으로 화면이 막히면 안 된다.
    """
    cur = current_version()
    out = {
        "current": cur,
        "latest": None,
        "update_available": False,
        "html_url": f"https://github.com/{REPO}/releases",
        "published_at": None,
        "breaking": False,
        "title": None,
        "error": None,
    }
    req = urllib.request.Request(
        RELEASES_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "ctb"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001 — 오프라인이 정상 상태의 하나다
        out["error"] = f"새 판을 확인하지 못했습니다: {str(e)[:150]}"
        return out

    latest = (data.get("tag_name") or "").lstrip("vV")
    body = data.get("body") or ""
    out.update(
        {
            "latest": latest or None,
            "html_url": data.get("html_url") or out["html_url"],
            "published_at": data.get("published_at"),
            "title": data.get("name"),
            "breaking": "되돌릴 수 없는 변화 — 있음" in body,
            "update_available": bool(latest) and _as_tuple(latest) > _as_tuple(cur),
        }
    )
    # 같은 판 번호 안에서 고친 것 — 태그를 옮겨 다시 낸 경우. 번호만 보면 «최신»이라 받지 못한다
    # (2026-09-05, v1.3.0을 유지한 채 고친 판을 다른 PC가 받지 못한 보고). 커밋을 비교한다.
    # zip 폴더면 먼저 git 사본으로 바꾼다 — 그래야 비교할 것이 생긴다(D-112).
    if not is_git_checkout():
        conv = ensure_git_checkout()
        if not conv["ok"]:
            out["note"] = f"zip 설치라 고친 것을 비교하지 못합니다({conv['reason']})."
    if not out["update_available"] and is_git_checkout():
        if from_zip():
            if zip_differs():
                out["update_available"] = True
                out["same_version"] = True
                out["commits_behind"] = None  # zip에는 커밋이 없어 «몇 건»은 모른다
                out["from_zip"] = True
        else:
            behind = commits_behind()
            if behind:
                out["update_available"] = True
                out["same_version"] = True
                out["commits_behind"] = behind
    return out


def commits_behind(timeout: int = 30) -> int:
    """원격 main에 있고 여기에는 없는 커밋 수. 네트워크가 없거나 git이 아니면 0.

    히스토리를 다시 쓴 뒤(강제 푸시)에는 «뒤처짐»이 아니라 «갈라짐»이다 — 그것도 받을 것으로
    센다(사용자는 커밋을 만들지 않으므로 갈라짐은 곧 원격이 새로 쓴 것이다).
    """
    root = app_root()
    try:
        # main이 아닌 브랜치(개발 중)에서는 «뒤처짐»을 세지 않는다 — 언제나 뒤처진 것으로 보인다.
        code, branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root, timeout)
        if code != 0 or branch.strip() != "main":
            return 0
        code, _ = _run(["git", "fetch", "--quiet", "origin", "main"], root, timeout)
        if code != 0:
            return 0
        code, out = _run(["git", "rev-list", "--count", "HEAD..origin/main"], root, timeout)
        if code != 0:
            return 0
        return int(out.strip() or 0)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return 0


def _run(args: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    p = subprocess.run(
        args, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", timeout=timeout
    )
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def is_git_checkout(root: Path | None = None) -> bool:
    return ((root or app_root()) / ".git").exists()


def git_available() -> bool:
    """git 명령이 있는가. 설치 스크립트가 Git을 깔지만, 손으로 푼 zip에는 없을 수 있다."""
    try:
        code, _ = _run(["git", "--version"], app_root(), 15)
        return code == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def working_tree_dirty(root: Path | None = None) -> tuple[bool, str]:
    """고친 것이 남아 있는가. 있으면 받지 않는다 — 조용히 덮어쓰면 안 된다.

    추적하지 않는 파일(logs·.env 같은 것)은 세지 않는다 — pull이 덮어쓰지 않고, 겹치는 경로가
    있으면 git이 스스로 거부한다.
    """
    code, out = _run(
        ["git", "status", "--porcelain", "--untracked-files=no"], root or app_root(), 30
    )
    if code != 0:
        return True, out or "git status 실패"
    return bool(out.strip()), out.strip()


def ensure_git_checkout(
    root: Path | None = None, remote: str = REMOTE_URL, timeout: int = 180
) -> dict:
    """zip으로 푼 폴더를 git 사본으로 바꾼다 — **파일은 건드리지 않는다.**

    입력: root — 앱 폴더(기본 app_root). remote — 원격 주소(테스트는 로컬 경로).
    출력: {"ok", "converted", "reason"}.
    하는 일: git init → origin 추가 → main 받기(depth 50) → HEAD·index만 origin/main으로
    (`git reset --mixed`). 작업 트리는 zip 그대로라, 그 뒤 `git status`가 보여 주는 차이가
    곧 «zip 시점 이후 바뀐 것»이다. ZIP_MARK를 남겨 「받기」가 그 차이를 사용자 수정으로
    오해하지 않게 한다.
    왜: 설치 안내가 zip → install.bat이라 다른 PC에는 .git이 없었고, 판 번호가 같으면 «최신»으로만
    보였다(2026-09-06 보고 — «커밋이 바뀌어도 업데이트가 안 된다»).
    """
    root = root or app_root()
    if is_git_checkout(root):
        return {"ok": True, "converted": False, "reason": ""}
    if not git_available():
        return {"ok": False, "converted": False, "reason": "git이 없습니다"}
    steps = (
        ["git", "init", "-q"],
        ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
        ["git", "remote", "add", "origin", remote],
        ["git", "fetch", "-q", "--depth=50", "origin", "main"],
        ["git", "reset", "-q", "--mixed", "origin/main"],
        ["git", "branch", "--set-upstream-to=origin/main", "main"],
    )
    for args in steps:
        try:
            code, out = _run(args, root, timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            code, out = 1, str(e)
        if code != 0:
            return {"ok": False, "converted": False, "reason": f"{' '.join(args[:2])}: {out[:200]}"}
    try:
        (root / ZIP_MARK).write_text("converted from zip\n", encoding="utf-8")
    except OSError:
        pass
    return {"ok": True, "converted": True, "reason": ""}


def from_zip(root: Path | None = None) -> bool:
    return ((root or app_root()) / ZIP_MARK).exists()


def zip_differs(root: Path | None = None) -> bool:
    """zip에서 바꾼 사본의 파일이 원격 main과 다른가(= 받을 것이 있는가)."""
    root = root or app_root()
    try:
        _run(["git", "fetch", "-q", "origin", "main"], root, 60)
        _run(["git", "reset", "-q", "--mixed", "origin/main"], root, 30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    dirty, _ = working_tree_dirty(root)
    return dirty


def apply_update() -> dict:
    """새 판을 받아 의존까지 맞춘다. 출력: {"ok", "steps": [{name, ok, output}], "hint"}

    순서: 더러운지 확인 → `git pull --ff-only` → `uv sync`. 어느 단계든 실패하면 거기서 멈추고
    무엇이 실패했는지 그대로 돌려준다.
    """
    root = app_root()
    steps: list[dict] = []
    if not is_git_checkout():
        conv = ensure_git_checkout()
        if not conv["ok"]:
            return {
                "ok": False,
                "steps": [],
                "hint": (
                    f"이 설치는 Git 사본이 아니고 바꾸지도 못했습니다({conv['reason']}). "
                    "새 판 zip을 내려받아 덮어써 주세요 — 서고는 앱 폴더 밖에 있으므로 "
                    "영향이 없습니다."
                ),
            }
    dirty, detail = working_tree_dirty()
    if dirty and from_zip():
        # zip 시점의 옛 파일이지 사용자 수정이 아니다 — 원격에 그대로 맞춘다(한 번뿐, 마커 삭제)
        dirty = False
    if dirty:
        return {
            "ok": False,
            "steps": [{"name": "작업 트리 확인", "ok": False, "output": detail[:2000]}],
            "hint": (
                "고친 파일이 남아 있어 받지 않았습니다. 덮어쓰면 그 수정이 사라집니다 — "
                "먼저 커밋하거나 되돌린 뒤 다시 시도하세요."
            ),
        }
    # uv sync는 적지 않은 extras를 **지운다.** 기록된 엔진 묶음을 같이 넘겨야 업데이트가
    # 고서 엔진을 뽑아 버리지 않는다(D-106).
    from core.extras import JOB_LOCK, sync_args

    if not JOB_LOCK.acquire(blocking=False):
        return {
            "ok": False,
            "steps": [],
            "hint": "엔진 설치가 도는 중입니다. 끝난 뒤 다시 받으세요.",
        }
    try:
        return _apply_update_locked(root, steps, sync_args)
    except Exception as e:  # noqa: BLE001 — 500으로 새면 화면은 «받지 못했습니다»조차 못 보여 준다
        steps.append({"name": "업데이트", "ok": False, "output": f"{type(e).__name__}: {e}"[:2000]})
        return {
            "ok": False,
            "steps": steps,
            "hint": "업데이트 도중 오류가 났습니다. 위 기록을 보세요.",
        }
    finally:
        JOB_LOCK.release()


def _apply_update_locked(root: Path, steps: list[dict], sync_args) -> dict:
    if from_zip(root):
        # zip에서 바꾼 사본: 파일을 원격 main에 맞추는 것이 곧 «받기»다
        for name, args in (
            ("원격 main 받기 (git fetch)", ["git", "fetch", "-q", "origin", "main"]),
            (
                "파일을 새 판에 맞추기 (git reset --hard origin/main)",
                ["git", "reset", "--hard", "origin/main"],
            ),
        ):
            code, out = _run(args, root, 300)
            steps.append({"name": name, "ok": code == 0, "output": out[:4000]})
            if code != 0:
                return {"ok": False, "steps": steps, "hint": f"{name}에서 멈췄습니다."}
        try:
            (root / ZIP_MARK).unlink()
        except OSError:
            pass
    for name, args, timeout in (
        ("새 판 받기 (git pull)", ["git", "pull", "--ff-only"], 300),
        ("의존 맞추기 (uv sync)", None, 900),
    ):
        try:
            if args is None:
                # 실행 직전에 계산 — 그 사이 기록된 extras를 빠뜨리지 않게
                args = sync_args()
            code, out = _run(args, root, timeout)
            # 히스토리를 다시 쓴 뒤에는 fast-forward가 안 된다. 작업 트리가 깨끗한 것은 위에서
            # 확인했으니(사용자 수정 없음) 원격 main에 그대로 맞춘다.
            if code != 0 and args[:2] == ["git", "pull"]:
                steps.append({"name": name, "ok": False, "output": out[:2000]})
                # 원격에 맞추기는 **main에서, 여기만의 커밋이 없을 때만**. 개발 PC의 미푸시
                # 커밋·기능 브랜치를 덮으면 되돌릴 수 없다(리뷰 지적 2026-09-05).
                name = "원격에 맞추기 (git reset --hard origin/main)"
                code, out = _run(["git", "fetch", "origin", "main"], root, 300)
                if code == 0:
                    rc1, branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root, 30)
                    rc2, ahead = _run(["git", "rev-list", "--count", "origin/main..HEAD"], root, 30)
                    # 조회가 실패하면(rc≠0·빈 출력) «로컬 커밋 없음»으로 보지 않는다 —
                    # 맞추지 않는다.
                    checks_ok = rc1 == 0 and rc2 == 0 and ahead.strip().isdigit()
                    if not checks_ok or branch.strip() != "main" or ahead.strip() != "0":
                        code, out = 1, (
                            f"지금 브랜치 {branch.strip()!r}, "
                            f"원격에 없는 로컬 커밋 {ahead.strip() or '?'}개 — "
                            "덮어쓰면 사라지므로 맞추지 않았습니다. "
                            "먼저 푸시하거나 main으로 옮기세요."
                        )
                    else:
                        code, out = _run(["git", "reset", "--hard", "origin/main"], root, 60)
        except (OSError, subprocess.TimeoutExpired) as e:
            steps.append({"name": name, "ok": False, "output": str(e)[:2000]})
            return {"ok": False, "steps": steps, "hint": f"{name}에서 멈췄습니다."}
        steps.append({"name": name, "ok": code == 0, "output": out[:4000]})
        if code != 0:
            return {"ok": False, "steps": steps, "hint": f"{name}에서 멈췄습니다."}
    return {
        "ok": True,
        "steps": steps,
        "hint": "받았습니다. **서버를 껐다 켜고 브라우저를 새로 고치세요**(Ctrl+Shift+R).",
    }


def auto_update(timeout: float = _TIMEOUT) -> dict:
    """서버를 켜기 전에 새 판이 있으면 받는다(D-112). 출력: {"did", "why", "result"}.

    받는 조건: git 사본(zip이면 먼저 바꾼다) · 새 판 또는 같은 판의 고친 것 있음 · 사용자가 고친
    파일 없음. 어느 하나라도 아니면 아무것도 하지 않고 까닭만 돌려준다. 네트워크가 없으면
    바로 끝난다.
    """
    if not git_available():
        return {"did": False, "why": "git 없음", "result": None}
    info = check(timeout=timeout)
    if info.get("error"):
        return {"did": False, "why": info["error"], "result": None}
    if not info.get("update_available"):
        return {"did": False, "why": "최신", "result": None}
    if not is_git_checkout():
        return {"did": False, "why": info.get("note") or "git 사본 아님", "result": None}
    dirty, _ = working_tree_dirty()
    if dirty and not from_zip():
        return {"did": False, "why": "고친 파일이 있어 받지 않음", "result": None}
    result = apply_update()
    return {
        "did": bool(result.get("ok")),
        "why": "받음" if result.get("ok") else result.get("hint", ""),
        "result": result,
    }


def auto_update_cli() -> int:
    """start_server가 부르는 한 줄 진입점. 무슨 일이 있어도 0으로 끝난다 — 서버 켜기를 막지 않는다.

    입력: 없음(환경변수 CTB_NO_AUTO_UPDATE=1이면 건너뛴다). 출력: 종료 코드 0.
    """
    import os

    if os.environ.get("CTB_NO_AUTO_UPDATE"):
        print("  자동 업데이트: 끔(CTB_NO_AUTO_UPDATE)")
        return 0
    try:
        r = auto_update()
    except Exception as e:  # noqa: BLE001
        print(f"  자동 업데이트: 건너뜀 ({type(e).__name__}: {str(e)[:100]})")
        return 0
    if r["did"]:
        print("  자동 업데이트: 새 판을 받았습니다.")
    else:
        print(f"  자동 업데이트: {r['why']}")
    return 0


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(auto_update_cli())

