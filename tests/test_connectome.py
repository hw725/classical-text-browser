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
    LIVE_FIELDS,
    NEUPRINT_TOKEN_ENV,
    NT_CLASSES,
    POLARITY_QUERY,
    RECORDED_REFERENCE,
    STRONG_CUT,
    _token_from_file,
    _token_present,
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


# ──────────────────────────────────────
# 화면에서 부를 수 있는가
# ──────────────────────────────────────


class TestReachableFromTheScreen:
    """라우트가 있는 것과 연구자가 쓸 수 있는 것은 다르다.

    이 저장소의 사용자는 비개발자다 — URL 을 손으로 치는 것은 기능이 아니다.
    2026-09-22 실측에서 이 자리가 비어 있었고, 그때 시험은 전부 초록이었다.
    라우트만 재고 있었기 때문이다.
    """

    def _js(self) -> str:
        return (REPO / "src" / "app" / "static" / "js" / "entity-manager.js").read_text(
            encoding="utf-8"
        )

    def test_the_screen_calls_the_route(self):
        """화면 코드가 대조 라우트를 실제로 부른다."""
        assert "connectome-comparison" in self._js(), (
            "화면이 커넥톰 대조 라우트를 부르지 않는다 — "
            "라우트만 있으면 연구자는 그 기능에 닿을 수 없다"
        )

    def test_there_is_a_button_for_it(self):
        """도구 바에 단추가 있고, 화면 코드가 그 id 를 배선한다."""
        html = (REPO / "src" / "app" / "static" / "index.html").read_text(encoding="utf-8")
        assert 'id="entity-connectome-btn"' in html
        assert "entity-connectome-btn" in self._js()

    def _render_body(self) -> str:
        """`_renderConnectome` 의 본문만 잘라 온다."""
        js = self._js()
        start = js.index("function _renderConnectome")
        end = js.index("function _openLlmRequestDialog", start)
        return js[start:end]

    def test_the_screen_shows_the_server_table_it_does_not_build_one(self):
        """표의 항목 이름과 값은 **서버가 준 것**을 쓴다.

        왜 중요한가: 화면이 「무게 1~2가 가진 비중」 같은 이름을 스스로 적으면,
        서버가 그 줄의 뜻을 바꿔도 화면은 옛 이름을 붙들고 초록으로 남는다.
        `compare()` 가 label 까지 함께 주는 이유가 이것이다.
        """
        body = self._render_body()
        assert "data.rows" in body, "서버가 준 표를 쓰지 않는다"
        assert "r.label" in body, "항목 이름을 화면이 스스로 적고 있다"
        # 기준값의 숫자를 화면에 박아 두면 D-128 표와 갈라진다.
        for hardcoded in ("0.840", "0.471", "84.0", "47.1"):
            assert hardcoded not in body, f"기준값을 화면에 박아 두었다: {hardcoded}"

    def test_the_screen_does_not_total_the_rows(self):
        """줄을 합쳐 총점을 만들지 않는다 — 점수를 내놓으면 그것을 올리는 것이 목표가 된다.

        서버(`compare`)는 의도적으로 점수를 주지 않는다. 화면이 합계를 만들면
        서버가 거부한 것을 화면이 되살리는 셈이다.
        """
        body = self._render_body()
        for forbidden in (".reduce(", "similarity", "유사도", "닮았"):
            assert forbidden not in body, f"화면이 총점을 만들고 있다: {forbidden}"

    def test_the_gate_reason_is_shown_whole(self):
        """400 의 사유는 줄바꿈째로 보여 준다 — 토스트로 줄이면 «왜·해결»이 사라진다."""
        js = self._js()
        assert "white-space:pre-wrap" in js, (
            "사유 문구를 그대로 보여 주지 않으면 줄바꿈으로 적은 «왜·해결»이 한 줄로 뭉친다"
        )


# ──────────────────────────────────────
# 토큰을 파일에서 읽는 길
# ──────────────────────────────────────


class TestTokenFromFile:
    """이 길은 2026-09-22 실측까지 시험에서 한 번도 돌지 않았다.

    neuprint 가 없어도 돌 수 있는 코드인데(파일을 읽고 파싱할 뿐) 덮이지 않았다 —
    「게이트 뒤에 있으니 못 잰다」는 설명은 이 함수에는 해당하지 않았다.
    """

    def _write(self, tmp_path: Path, body: str) -> Path:
        p = tmp_path / "토큰.env"
        p.write_text(body, encoding="utf-8")
        return p

    def test_reads_the_value(self, monkeypatch, tmp_path):
        import core.connectome as mod

        p = self._write(tmp_path, f"{NEUPRINT_TOKEN_ENV}=abc123\n")
        monkeypatch.setattr(mod, "NEUPRINT_TOKEN_FILE", p)
        assert _token_from_file() == "abc123"

    def test_strips_quotes_and_spaces(self, monkeypatch, tmp_path):
        """`.env` 는 값을 따옴표로 감싸는 일이 흔하다 — 그대로 보내면 인증이 실패한다."""
        import core.connectome as mod

        p = self._write(tmp_path, f'  {NEUPRINT_TOKEN_ENV} = "abc123"  \n')
        monkeypatch.setattr(mod, "NEUPRINT_TOKEN_FILE", p)
        assert _token_from_file() == "abc123"

    def test_other_keys_are_ignored(self, monkeypatch, tmp_path):
        import core.connectome as mod

        p = self._write(tmp_path, f"OTHER=zzz\n{NEUPRINT_TOKEN_ENV}=abc123\n")
        monkeypatch.setattr(mod, "NEUPRINT_TOKEN_FILE", p)
        assert _token_from_file() == "abc123"

    def test_missing_key_is_empty_not_an_exception(self, monkeypatch, tmp_path):
        import core.connectome as mod

        p = self._write(tmp_path, "OTHER=zzz\n")
        monkeypatch.setattr(mod, "NEUPRINT_TOKEN_FILE", p)
        assert _token_from_file() == ""

    def test_presence_and_value_agree(self, monkeypatch, tmp_path):
        """«있다»고 판정한 파일에서 값이 나와야 한다 — 두 파서가 갈라지면 여기서 걸린다.

        `_token_present()` 와 `_token_from_file()` 이 같은 줄을 각자 파싱한다.
        한쪽만 고치면 「토큰이 있다고 했는데 값이 빈 문자열」이 되고, 그때 실패는
        게이트가 아니라 neuPrint 인증에서 나므로 사유가 엉뚱해진다.
        """
        import core.connectome as mod

        monkeypatch.delenv(NEUPRINT_TOKEN_ENV, raising=False)
        for body in (
            f"{NEUPRINT_TOKEN_ENV}=abc123\n",
            f'{NEUPRINT_TOKEN_ENV}="abc123"\n',
            f"  {NEUPRINT_TOKEN_ENV} = abc123 \n",
        ):
            p = self._write(tmp_path, body)
            monkeypatch.setattr(mod, "NEUPRINT_TOKEN_FILE", p)
            assert _token_present() is True, f"있다고 못 봤다: {body!r}"
            assert _token_from_file() == "abc123", f"값을 못 읽었다: {body!r}"

    def test_empty_value_is_not_present(self, monkeypatch, tmp_path):
        import core.connectome as mod

        monkeypatch.delenv(NEUPRINT_TOKEN_ENV, raising=False)
        p = self._write(tmp_path, f"{NEUPRINT_TOKEN_ENV}=\n")
        monkeypatch.setattr(mod, "NEUPRINT_TOKEN_FILE", p)
        assert _token_present() is False
        assert _token_from_file() == ""


# ──────────────────────────────────────
# 측정 규약 — 정본과 같은가
# ──────────────────────────────────────


class TestMeasurementProtocol:
    """살아 있는 재측정이 정본(`jt725/scripts/cns_structure_stats.py`)과 같은 자로 재는가.

    2026-09-22에 실제로 돌려 보니 **같지 않았다** — 조절 비중이 12.5% → 65.2%로
    나왔다. 주석에는 「정본과 같아야 한다」고 적혀 있었다. 주석은 코드를 지키지
    못한다. 정본 스크립트는 이 저장소 밖에 있어(개인 환경) 의존할 수 없으므로,
    규약을 상수로 꺼내 여기서 대조한다.

    이 시험은 neuPrint에 붙지 않는다 — 질의문과 상수만 본다. 붙어야만 아는 것은
    붙을 수 있는 환경에서 `measure_reference()`를 직접 돌려 기록된 값과 견준다
    (2026-09-22에 그렇게 해서 여섯 칸 전부 ±0.0005 안으로 맞는 것을 확인했다).
    """

    def test_it_asks_for_the_consensus_not_the_prediction(self):
        """`consensusNt`(합의값)를 묻는다 — `predictedNt`(기계 예측)가 아니다.

        이 한 낱말이 조절 비중을 12.5% → 65.2%로 만들었다. 질의 «상수»만 본다 —
        주석은 그 잘못을 설명하느라 옛 이름을 적고 있어야 하므로 파일 전체를
        grep 하면 이 시험이 자기 설명에 걸린다(처음 쓸 때 실제로 걸렸다).
        """
        assert "consensusNt" in POLARITY_QUERY, "합의값을 묻지 않는다"
        assert "predictedNt" not in POLARITY_QUERY, (
            "기계 예측값을 쓰고 있다 — 정본은 합의값을 쓴다"
        )

    def test_null_weights_are_excluded(self):
        assert "w.weight IS NOT NULL" in POLARITY_QUERY

    def test_the_lineage_is_matched_whole_not_by_prefix(self):
        """`=~`(전체 일치)로 계통을 고른다 — 접두 대조는 변종까지 끌어온다."""
        assert "b.type =~" in POLARITY_QUERY
        assert "STARTS WITH" not in POLARITY_QUERY, "접두 대조로 되돌아갔다"

    def test_unknown_transmitters_stay_in_the_denominator(self):
        """nt를 모르는 무게도 `unclear`로 세어 분모에 넣는다.

        버리면 「아는 것들 사이의 비율」이 되어 기록된 값과 잣대가 어긋난다.
        """
        assert "coalesce(a.consensusNt,'unclear')" in POLARITY_QUERY

    def test_the_query_still_formats(self):
        """상수로 꺼낸 뒤에도 실제로 채워지는가 — 칸 이름이 어긋나면 여기서 걸린다."""
        q = POLARITY_QUERY.format(lineage="KCg-m", strong_cut=STRONG_CUT)
        assert "'KCg-m'" in q
        assert "w.weight>=5" in q
        assert "{" not in q, "채우지 못한 칸이 남았다"

    def test_glutamate_is_not_folded_into_inhibition(self):
        """글루탐산은 억제에 합산하지 않는다 — 모호로 따로 둔다."""
        assert NT_CLASSES["ambiguous"] == ("glutamate",)
        assert "glutamate" not in NT_CLASSES["refute"]
        assert NT_CLASSES["refute"] == ("gaba", "histamine")

    def test_the_strong_cut_matches_the_recorded_table(self):
        """강연결 절단은 D-128 표와 같은 5다."""
        assert STRONG_CUT == 5
        d128 = (REPO / "docs" / "DECISIONS.md").read_text(encoding="utf-8").split("## D-128", 1)[1]
        assert "무게 5" in d128 or "5 이상" in d128

    def test_only_the_remeasured_fields_are_labelled_live(self):
        """다시 잰 칸만 «살아 있는» 것으로 표시한다.

        한때 `{**RECORDED_REFERENCE, "source": "직접 질의"}`로 돌려주어, 기록된
        값인 `noise_share`·`top10_share`에까지 「방금 쟀다」는 이름표가 붙었다 —
        대조 다섯 줄 중 셋이 거짓이 되는 자리였다.
        """
        assert set(LIVE_FIELDS) == {"polarity", "polarity_strong"}
        assert "noise_share" not in LIVE_FIELDS
        assert "top10_share" not in LIVE_FIELDS

    def test_rows_say_whether_their_reference_is_live(self):
        """줄마다 «이 기준값이 방금 잰 것인가»가 붙는다."""
        rels = [_rel(weight=9, polarity="support")]
        # 기록된 값으로 대조하면 어느 줄도 «방금 잰 것»이 아니다.
        for row in compare(rels)["rows"]:
            assert row["reference_live"] is False

        # 부호만 다시 잰 기준값을 주면 부호 줄만 표시된다.
        live_ref = {
            **RECORDED_REFERENCE,
            "live_fields": list(LIVE_FIELDS),
        }
        rows = {r["key"]: r["reference_live"] for r in compare(rels, reference=live_ref)["rows"]}
        assert rows["refute"] is True
        assert rows["modulate"] is True
        assert rows["refute_strong"] is True
        assert rows["noise_share"] is False, "무게 분포는 부호 질의로 뽑을 수 없다"
        assert rows["top10_share"] is False

    def test_the_screen_marks_the_live_rows(self):
        """화면이 그 표시를 실제로 그린다 — 데이터에만 있으면 사람은 모른다."""
        js = (
            REPO / "src" / "app" / "static" / "js" / "entity-manager.js"
        ).read_text(encoding="utf-8")
        assert "reference_live" in js, "화면이 «방금 잰 줄»을 구분하지 않는다"
