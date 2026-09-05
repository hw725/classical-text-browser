"""새 판이 나왔는지 보고, 앱 안에서 받아 온다 (D-103).

왜 필요한가: 사용자가 GitHub 저장소를 열어 보지 않으면 새 판이 나온 줄 모른다. 「구버전만
가진 사람이 직접 깃허브에 들어오지 않고도」가 요구였다.

무엇을 하지 않는가:
  - **서고를 건드리지 않는다.** 서고는 앱 폴더 밖에 있고, 이 모듈은 앱 저장소만 다룬다.
  - **작업 트리가 더러우면 받지 않는다.** `git pull --ff-only`가 실패하면 그대로 알린다 —
    사용자가 고친 코드를 조용히 덮어쓰는 일이 없어야 한다.
  - **저절로 받지 않는다.** 확인은 자동, 내려받기는 사람이 누를 때만.

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
_TIMEOUT = 6.0


def app_root() -> Path:
    """앱 저장소 뿌리 (src/core/updater.py → …/classical-text-browser)."""
    return Path(__file__).resolve().parent.parent.parent


def current_version() -> str:
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
    if not out["update_available"] and is_git_checkout():
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


def is_git_checkout() -> bool:
    return (app_root() / ".git").exists()


def working_tree_dirty() -> tuple[bool, str]:
    """고친 것이 남아 있는가. 있으면 받지 않는다 — 조용히 덮어쓰면 안 된다."""
    code, out = _run(["git", "status", "--porcelain"], app_root(), 30)
    if code != 0:
        return True, out or "git status 실패"
    return bool(out.strip()), out.strip()


def apply_update() -> dict:
    """새 판을 받아 의존까지 맞춘다. 출력: {"ok", "steps": [{name, ok, output}], "hint"}

    순서: 더러운지 확인 → `git pull --ff-only` → `uv sync`. 어느 단계든 실패하면 거기서 멈추고
    무엇이 실패했는지 그대로 돌려준다.
    """
    root = app_root()
    steps: list[dict] = []
    if not is_git_checkout():
        return {
            "ok": False,
            "steps": [],
            "hint": (
                "이 설치는 Git 사본이 아닙니다(zip으로 받은 폴더). 새 판 zip을 내려받아 "
                "덮어써 주세요 — 서고는 앱 폴더 밖에 있으므로 영향이 없습니다."
            ),
        }
    dirty, detail = working_tree_dirty()
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
    from core.extras import sync_args

    for name, args, timeout in (
        ("새 판 받기 (git pull)", ["git", "pull", "--ff-only"], 300),
        ("의존 맞추기 (uv sync)", sync_args(), 900),
    ):
        try:
            code, out = _run(args, root, timeout)
            # 히스토리를 다시 쓴 뒤에는 fast-forward가 안 된다. 작업 트리가 깨끗한 것은 위에서
            # 확인했으니(사용자 수정 없음) 원격 main에 그대로 맞춘다.
            if code != 0 and args[:2] == ["git", "pull"]:
                steps.append({"name": name, "ok": False, "output": out[:2000]})
                name = "원격에 맞추기 (git reset --hard origin/main)"
                code, out = _run(["git", "fetch", "origin", "main"], root, 300)
                if code == 0:
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
