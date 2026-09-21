"""커넥톰 대조 — 배포에서 빠지는가, 그리고 대조가 맞는가 (D-128 후속).

이 기능의 요구는 둘이고 서로 반대 방향이다.
    ① 선생님 PC에서는 열린다 — neuprint-python(extra `connectome`) + 토큰.
    ② **배포본에서는 닫힌다** — 설치 파일이 그 extra를 선택지로도 내놓지 않고,
       없으면 라우트가 400에 «왜»를 담아 답한다.

②가 조용히 깨지는 것이 가장 위험하다. extra 이름을 install.ps1의 어느 가지에
슬쩍 넣으면, 설치 파일을 받은 사람이 4.5GB 옆에 이것까지 받고도 토큰이 없어
쓰지 못한다. 사람 눈으로는 diff 한 줄이라 지나가기 쉬워 기계가 지킨다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.connectome import (
    NEUPRINT_TOKEN_ENV,
    RECORDED_REFERENCE,
    compare,
    is_live_available,
    library_profile,
)

REPO = Path(__file__).resolve().parent.parent


def _rel(weight=None, polarity=None, mode=None) -> dict:
    out = {"id": "r", "predicate": "governs"}
    if weight is not None:
        out["weight"] = weight
    if polarity is not None:
        out["polarity"] = polarity
    if mode is not None:
        out["mode"] = mode
    return out


# ──────────────────────────────────────
# ② 배포에서 빠지는가
# ──────────────────────────────────────


class TestExcludedFromDistribution:
    def test_connectome_is_an_optional_extra(self):
        """기본 의존성이 아니라 extra 여야 한다."""
        text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        optional = text.split("[project.optional-dependencies]", 1)[1]
        assert "connectome = [" in optional
        # 기본 dependencies 절에는 없어야 한다.
        base = text.split("[project.optional-dependencies]", 1)[0]
        assert "neuprint" not in base

    def test_installer_never_offers_connectome(self):
        """`install.ps1`의 어느 선택지도 이 extra를 고르지 않는다.

        이 시험이 깨지면 설치 파일을 받은 사람에게 이 기능이 딸려 간다는 뜻이다.
        """
        ps1 = (REPO / "install.ps1").read_text(encoding="utf-8")
        picks = [ln for ln in ps1.splitlines() if "--extra" in ln]
        assert picks, "install.ps1에서 extra를 고르는 줄을 찾지 못했다"
        for line in picks:
            assert "connectome" not in line, f"설치 선택지에 connectome이 들어갔다: {line.strip()}"

    def test_setup_exe_pick_choices_are_unchanged(self):
        """설치 파일의 `--pick`은 1~4뿐이다 — 새 선택지가 생기지 않았는지."""
        setup = (REPO / "installer" / "ctb_setup.py").read_text(encoding="utf-8")
        m = re.search(r'choices=\[([^\]]+)\]', setup)
        assert m, "--pick의 choices를 찾지 못했다"
        assert m.group(1).replace('"', "").replace(" ", "") == "1,2,3,4"


# ──────────────────────────────────────
# 게이트가 «왜»를 말하는가
# ──────────────────────────────────────


class TestLiveGateExplainsItself:
    def test_missing_package_says_it_is_not_included(self, monkeypatch):
        """패키지가 없으면 「고장」이 아니라 「포함되지 않았다」로 말해야 한다."""
        import builtins

        real_import = builtins.__import__

        def _no_neuprint(name, *a, **k):
            if name == "neuprint":
                raise ImportError("no neuprint")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", _no_neuprint)
        ok, reason = is_live_available()
        assert ok is False
        assert "포함되지 않았습니다" in reason
        assert "uv sync --extra connectome" in reason

    def test_missing_token_is_a_different_reason(self, monkeypatch, tmp_path):
        """토큰이 없는 것과 패키지가 없는 것은 다른 사유다 — 해결책이 다르다."""
        pytest.importorskip("neuprint")
        import core.connectome as mod

        monkeypatch.delenv(NEUPRINT_TOKEN_ENV, raising=False)
        monkeypatch.setattr(mod, "NEUPRINT_TOKEN_FILE", tmp_path / "없는.env")
        ok, reason = is_live_available()
        assert ok is False
        assert "토큰이 없습니다" in reason

    def test_token_value_never_leaves_the_module(self, monkeypatch):
        """사유 문구에 토큰 값이 섞이면 안 된다 — 화면에 그대로 뜨는 글이다."""
        monkeypatch.setenv(NEUPRINT_TOKEN_ENV, "SECRET-TOKEN-VALUE")
        _ok, reason = is_live_available()
        assert "SECRET-TOKEN-VALUE" not in reason


# ──────────────────────────────────────
# 대조가 맞는가 (의존성 없이 도는 쪽)
# ──────────────────────────────────────


class TestComparisonWorksOffline:
    def test_compare_runs_without_neuprint(self):
        """기록된 기준값 대조는 패키지 없이 돌아야 한다 — 배포본의 기능이다."""
        result = compare([_rel(weight=10, polarity="support")])
        assert result["reference"]["lineage"] == "KCg-m"
        assert [r["key"] for r in result["rows"]] == [
            "noise_share",
            "top10_share",
            "refute",
            "modulate",
            "refute_strong",
        ]

    def test_empty_store_says_so_instead_of_dividing_by_zero(self):
        result = compare([])
        assert result["library"]["count"] == 0
        assert any("대조할 것이 없습니다" in n for n in result["notes"])

    def test_all_weak_edges_show_a_high_noise_share(self):
        """무게 1짜리만 쌓인 서고는 잡음 비중 1.0으로 나와야 한다."""
        profile = library_profile([_rel(weight=1) for _ in range(20)])
        assert profile["noise_share"] == 1.0

    def test_no_refute_is_pointed_out(self):
        """반박이 하나도 없으면 짚어 준다 — 자료 탓일 수도, 안 적은 탓일 수도."""
        result = compare([_rel(weight=9, polarity="support") for _ in range(5)])
        assert any("반박이 한 건도 없습니다" in n for n in result["notes"])

    def test_unsigned_strong_edges_are_pointed_out(self):
        """부호 없는 강연결은 11항이 경고하는 자리다."""
        result = compare([_rel(weight=20) for _ in range(3)])
        assert any("부호가 없는 강연결이 3개" in n for n in result["notes"])

    def test_same_ruler_as_relation_polarity(self):
        """서고와 기준값을 **같은 자**로 재야 한다 — 정의가 갈라지면 차이가 무의미하다."""
        from core.relation_polarity import polarity_breakdown

        relations = [_rel(weight=8, polarity="refute"), _rel(weight=2, polarity="support")]
        profile = library_profile(relations)
        assert profile["polarity"]["refute"] == polarity_breakdown(relations)["refute"]

    def test_recorded_reference_matches_d128(self):
        """기록된 기준값이 D-128 표와 같은지 — 문서와 코드가 갈라지면 대조가 거짓이 된다."""
        decisions = (REPO / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        d128 = decisions.split("## D-128", 1)[1]
        assert "84.0%" in d128  # 무게 1~2 비율 (수렴)
        assert "47.1%" in d128  # 상위 10% 무게비중 (수렴)
        assert "12.5%" in d128  # 조절 비중
        assert RECORDED_REFERENCE["noise_share"] == 0.840
        assert RECORDED_REFERENCE["top10_share"] == 0.471
        assert RECORDED_REFERENCE["polarity"]["modulate"] == 0.125
