"""엔진 추가 설치 (D-106) — uv sync를 실제로 돌리지 않고 인자·기록·거절 규칙을 검사한다.

왜 이 검사가 있는가:
    uv sync는 `--extra`로 적지 않은 extras를 **지운다.** 기록을 빠뜨리면 업데이트 한 번에
    고서 엔진이 사라진다. 그 규칙이 코드에서 빠지면 여기서 잡힌다.
"""

import json
from pathlib import Path

import pytest

from core import extras


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch):
    """앱 루트를 임시 폴더로 돌리고 probe를 고정한다 — 진짜 파이썬을 띄우지 않는다."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\n'
        "[project.optional-dependencies]\n"
        'classical = ["onnxruntime"]\njapanese = ["onnxruntime"]\n'
        'classical-gpu = ["torch"]\nempty = []\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(extras, "app_root", lambda: tmp_path)
    monkeypatch.setattr(extras, "_probe", lambda module: module == "onnxruntime")
    extras._probe_cache.clear()
    return tmp_path


def test_first_record_comes_from_probe(isolated: Path):
    """기록이 없으면 지금 깔린 것으로 처음 기록을 만든다."""
    assert extras.recorded_extras() == ["classical", "japanese"]
    saved = json.loads((isolated / ".ctb-extras.json").read_text(encoding="utf-8"))
    assert saved == {"extras": ["classical", "japanese"]}


def test_sync_args_keep_recorded_extras(isolated: Path):
    """추가 설치·업데이트가 넘기는 인자에 기록된 extras가 전부 들어 있다."""
    extras._save_record(["japanese"])
    assert extras.sync_args() == ["uv", "sync", "--extra", "japanese"]
    assert extras.sync_args(["classical"]) == [
        "uv", "sync", "--extra", "classical", "--extra", "japanese",
    ]


def test_blocked_and_unknown_are_refused(isolated: Path):
    """GPU판은 이 환경에 넣지 않고(D-078), pyproject에 없는 이름은 거절한다."""
    r = extras.start_install("classical-gpu")
    assert r["ok"] is False and ".venv-gpu" in r["error"]
    r = extras.start_install("nonexistent")
    assert r["ok"] is False and "모르는" in r["error"]
    assert extras._job["running"] is False


def test_status_shape(isolated: Path):
    """화면이 2초마다 묻는 응답 — 이름·설명·깔림·기록·작업 상태."""
    s = extras.status()
    names = [e["name"] for e in s["extras"]]
    assert names == list(extras.KNOWN_EXTRAS)
    for e in s["extras"]:
        assert {"label", "for", "size", "installed", "recorded"} <= set(e)
        assert e["installed"] is True  # probe가 onnxruntime을 «있음»으로 고정
    assert s["job"]["running"] is False
    assert isinstance(s["job"]["log"], list)


def test_probe_is_cached(isolated: Path, monkeypatch):
    """probe는 자식 프로세스라 30초 동안 기억한다. force면 다시 본다."""
    calls = []
    monkeypatch.setattr(extras, "_probe", lambda m: calls.append(m) or True)
    extras._probe_cache.clear()
    extras.installed_extras()
    extras.installed_extras()
    assert calls == ["onnxruntime"]  # 두 extras가 같은 probe → 한 번, 두 번째 호출은 캐시
    extras.installed_extras(force=True)
    assert calls == ["onnxruntime", "onnxruntime"]
