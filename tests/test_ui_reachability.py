"""화면 코드가 **조용히 어긋나는 자리**를 기계로 짚는다.

세 가지를 재고, 셋 다 「있는 것」과 「동작하는 것」이 다른 자리다.
    ① 닿을 수 있는가 — 단추가 열리지 않는 조상 안에 있지 않은지 (B-008)
    ② 전역 이름이 겹치지 않는가 — 뒤에 적재된 파일이 남의 함수를 가린다 (B-009)
    ③ 이스케이프 헬퍼가 느슨하지 않은가 — 가려진 판이 느슨하면 남의 호출도 느슨하다

① 의 사연 (B-008).

2026-09-22에 `#interp-panel`이 **어느 모드에서도 열리지 않는다**는 것이 드러났다.
「비교」 탭을 `e84d800`(2026-02-24)이 지웠는데 그 커밋 제목이 「비교 탭 L6/L7 수정」
이었다 — 고치겠다고 한 것의 입구를 같은 커밋에서 지웠고, 일곱 달 동안 아무도 몰랐다.
그 안에 있던 「기반 업데이트」와 「변경 인지」는 **상태를 바꾸는 동작**인데 화면에서
부를 길이 없었다. 원본이 바뀐 해석 저장소는 그 사실을 볼 수만 있고 빠져나올 수 없었다.

왜 id 를 세는 시험으로는 못 잡는가: 단추는 `index.html` 에 멀쩡히 있고 JS 배선도
멀쩡하다. grep 도 초록이고 `getElementById` 도 찾아낸다. 죽은 것은 **조상**이다.

여기서 재는 것(사이드바 계열에 한정한다):
    어떤 조작 단추가 들어 있는 사이드바 섹션이, `workspace.js` 의 `panelSections`
    맵에 실려 있고 그 이름의 액티비티 단추가 `index.html` 에 실재하는가.

여기서 재지 **않는** 것: 일반적인 도달 가능성. 오른쪽 편집기 패널들은 모드 탭이
여는 다른 길이고, 이 시험은 그쪽을 보지 않는다. 일반 검사기는 별도 과제다.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
INDEX = REPO / "src" / "app" / "static" / "index.html"
WORKSPACE_JS = REPO / "src" / "app" / "static" / "js" / "workspace.js"


class _Ancestry(HTMLParser):
    """열린 태그의 id 를 쌓아 두었다가, id 가 있는 요소마다 조상 id 목록을 적는다.

    왜 직접 쓰는가: 이 검사에 필요한 것은 «누구 안에 있는가» 하나뿐이라
    외부 파서를 더할 이유가 없다. 닫히지 않는 태그(br·img…)는 건너뛴다.
    """

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str | None] = []
        self.ancestors: dict[str, list[str]] = {}

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        d = dict(attrs)
        eid = d.get("id")
        if eid:
            self.ancestors[eid] = [a for a in self.stack if a]
        self.stack.append(eid)

    def handle_startendtag(self, tag, attrs):
        d = dict(attrs)
        eid = d.get("id")
        if eid:
            self.ancestors[eid] = [a for a in self.stack if a]

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.stack:
            self.stack.pop()


@pytest.fixture(scope="module")
def ancestors() -> dict[str, list[str]]:
    p = _Ancestry()
    p.feed(INDEX.read_text(encoding="utf-8"))
    return p.ancestors


@pytest.fixture(scope="module")
def index_html() -> str:
    return INDEX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def panel_sections() -> dict[str, list[str]]:
    """`workspace.js` 의 `panelSections` 맵 — 액티비티 패널 이름 → 사이드바 섹션 id."""
    js = WORKSPACE_JS.read_text(encoding="utf-8")
    m = re.search(r"panelSections\s*=\s*\{(.*?)\n\s*\};", js, re.S)
    assert m, "workspace.js 에서 panelSections 맵을 찾지 못했다"
    out: dict[str, list[str]] = {}
    for name, body in re.findall(r"(\w+)\s*:\s*\[([^\]]*)\]", m.group(1)):
        out[name] = re.findall(r'"([^"]+)"', body)
    assert out, "panelSections 를 읽어내지 못했다"
    return out


def _opening_panel(section_id: str, panel_sections: dict[str, list[str]]) -> str | None:
    """이 사이드바 섹션을 여는 액티비티 패널 이름."""
    for name, ids in panel_sections.items():
        if section_id in ids:
            return name
    return None


def assert_reachable(
    control_id: str,
    ancestors: dict[str, list[str]],
    index_html: str,
    panel_sections: dict[str, list[str]],
) -> None:
    """이 조작 단추에 사람이 닿을 수 있는지 — 조상까지 거슬러 확인한다."""
    assert control_id in ancestors, f"{control_id} 가 index.html 에 없다"
    chain = ancestors[control_id]

    opened_by = [(a, _opening_panel(a, panel_sections)) for a in chain]
    live = [(a, n) for a, n in opened_by if n]
    assert live, (
        f"{control_id} 를 담은 조상 중 «여는 주체»가 있는 것이 없다.\n"
        f"  조상: {chain}\n"
        f"  → 화면에 있어도 사람이 닿을 수 없다(B-008 이 그 모양이었다)."
    )

    section_id, panel_name = live[0]
    assert f'data-panel="{panel_name}"' in index_html, (
        f"{control_id} 는 «{section_id}» 안에 있고 그것을 여는 이름은 «{panel_name}» 인데,\n"
        f"  `data-panel=\"{panel_name}\"` 단추가 index.html 에 없다 — 입구가 사라졌다."
    )


# ──────────────────────────────────────
# 해석 저장소의 계약을 지키는 동작 둘
# ──────────────────────────────────────


class TestDependencyActionsAreReachable:
    """원본이 바뀌었을 때 **빠져나올 수 있어야** 한다.

    읽는 쪽(어느 파일이 바뀌었나)은 사이드바가 그리고 있어 여태 티가 나지 않았다.
    막혀 있던 것은 쓰는 쪽 — `dependency/acknowledge` 와 `dependency/update-base` 다.
    """

    @pytest.mark.parametrize(
        "control_id", ["interp-dep-banner", "interp-dep-ack", "interp-dep-update"]
    )
    def test_reachable(self, control_id, ancestors, index_html, panel_sections):
        assert_reachable(control_id, ancestors, index_html, panel_sections)

    def test_the_actions_sit_with_what_they_act_on(self, ancestors):
        """경고와 «바뀐 파일 목록»이 같은 자리에 있다 — 보는 것과 누르는 것이 붙어 있게."""
        assert "dep-sidebar-section" in ancestors["interp-dep-banner"]
        assert "dep-sidebar-section" in ancestors["dep-file-list"]

    def test_the_only_callers_are_still_wired(self):
        """이 두 라우트를 부르는 곳이 여전히 배너 단추뿐인지 — 늘었으면 이 시험을 고친다."""
        js = (REPO / "src" / "app" / "static" / "js" / "interpretation.js").read_text(
            encoding="utf-8"
        )
        assert js.count("dependency/acknowledge") == 1
        assert js.count("dependency/update-base") == 1
        assert 'getElementById("interp-dep-ack")' in js
        assert 'getElementById("interp-dep-update")' in js


class TestSnapshotIsSymmetric:
    """가져올 수 있으면 내보낼 수도 있어야 한다.

    2026-09-22까지 `snapshot-import-btn` 은 살아 있는 사이드바에, `snapshot-export-btn`
    은 죽은 패널에 있었다 — 받을 수는 있는데 내보낼 수가 없었다.
    """

    @pytest.mark.parametrize(
        "control_id", ["snapshot-import-btn", "snapshot-export-btn"]
    )
    def test_reachable(self, control_id, ancestors, index_html, panel_sections):
        assert_reachable(control_id, ancestors, index_html, panel_sections)

    def test_they_live_side_by_side(self, ancestors):
        assert ancestors["snapshot-export-btn"] == ancestors["snapshot-import-btn"]


# ──────────────────────────────────────
# 이 시험 자신이 무엇을 재는지
# ──────────────────────────────────────


class TestTheCheckItselfCatchesTheBug:
    """검사기가 실제로 그 모양을 잡는지 — 안 그러면 초록이 아무 뜻이 없다."""

    def test_a_control_in_an_unopened_container_fails(
        self, ancestors, index_html, panel_sections
    ):
        """여는 주체가 없는 조상에 든 단추는 «닿을 수 없다»로 판정된다.

        기준을 «오른쪽 편집기 패널»에서 잡는다. 그쪽은 모드 탭이 여는 다른 길이라
        `panelSections` 에 없고, 이 검사는 사이드바 계열만 본다(파일 머리말의 한정).
        한때는 `#interp-panel` 안의 단추로 이것을 쟀는데, 그 패널을 2026-09-22에
        걷어내면서(B-008) 기준을 옮겼다.
        """
        # 레이아웃 편집기의 「저장」 — `#layout-props-panel` 안이고, 그 패널은
        # `data-mode="layout"` 탭이 여므로 `panelSections` 에 없다.
        baseline = "layout-save"
        assert baseline in ancestors, f"기준으로 삼은 단추가 사라졌다: {baseline}"
        assert not any(
            _opening_panel(a, panel_sections) for a in ancestors[baseline]
        ), "기준 단추가 사이드바로 옮겨졌다 — 다른 기준을 고른다"
        with pytest.raises(AssertionError, match="여는 주체"):
            assert_reachable(baseline, ancestors, index_html, panel_sections)

    def test_a_missing_entrance_fails(self, ancestors, index_html, panel_sections):
        """섹션은 맵에 있는데 그 이름의 액티비티 단추가 사라지면 걸린다."""
        broken = index_html.replace('data-panel="dependency"', 'data-panel="사라진것"')
        with pytest.raises(AssertionError, match="입구가 사라졌다"):
            assert_reachable("interp-dep-ack", ancestors, broken, panel_sections)

    def test_the_dead_panel_is_gone(self, panel_sections):
        """죽은 해석 패널을 **걷어냈다** (2026-09-22, B-008 철거분).

        되살아나는 것을 막는다. 2026-02-24 `e84d800` 이 「비교」 탭을 지우며
        `_switchMode` 에 폴백까지 넣었으니 의도된 제거였는데, 패널과 그 안의 것들이
        일곱 달 남아 의존 추적의 «쓰는 쪽»과 스냅샷 내보내기를 닿을 수 없게 했다.

        지금 L5~L7 은 다섯 편집기가 각자 패널과 모드 탭으로 맡는다(D-096).
        이 셋이 돌아오면 그 결정을 되짚는 것이므로 빨간불을 낸다.
        """
        html = INDEX.read_text(encoding="utf-8")
        assert 'id="interp-panel"' not in html, "죽은 해석 패널이 돌아왔다"
        assert 'data-mode="interpretation"' not in html, "지운 「비교」 탭이 돌아왔다"
        assert _opening_panel("interp-panel", panel_sections) is None
        # 그 안에 있던 스텁·중복도 함께 걷었다.
        assert 'id="llm-dialog-overlay"' not in html, "배선 없던 LLM 스텁 창이 돌아왔다"
        assert 'id="entity-create-textblock-btn"' not in html, (
            "행을 묻지 않는 옛 「단위 만들기」 폼이 돌아왔다 — "
            "손 경계는 사이드바 「＋ 경계 넣기」가 맡는다"
        )

    def test_the_hand_made_boundary_path_still_exists(self):
        """옛 폼을 걷어낸 대신 **더 나은 길이 남아 있어야** 한다.

        사용자가 「손으로 경계 만드는 길이 필요함」이라고 했다(2026-09-22).
        그 능력은 사이드바 「내용」의 「＋ 경계 넣기」가 맡는다 — 찍어서 (행·글자)를
        얻고(D-094), 안 되면 쪽·행·자를 숫자로 주며, 제목은 코드가 확정본에서 가져온다.
        """
        js = (
            REPO / "src" / "app" / "static" / "js" / "contents-tree.js"
        ).read_text(encoding="utf-8")
        assert "contents-insert-btn" in js, "「넣기」 단추가 사라졌다"
        assert 'data-k="line"' in js, "행을 고르는 칸이 사라졌다 — 옛 폼의 결함으로 되돌아간다"
        assert "/boundaries" in js, "경계 저장 라우트를 부르지 않는다"


# ──────────────────────────────────────
# ②③ 전역 이름 가림과 이스케이프 (B-009)
# ──────────────────────────────────────


def _load_order() -> list[str]:
    """`index.html` 이 화면 JS 를 적재하는 순서 — 뒤가 앞을 가린다."""
    html = INDEX.read_text(encoding="utf-8")
    return re.findall(r'src="/static/js/([\w.-]+)\.js', html)


def _toplevel_functions() -> dict[str, list[str]]:
    """{함수 이름: [선언한 파일…]} — 적재 순서대로."""
    js_dir = REPO / "src" / "app" / "static" / "js"
    out: dict[str, list[str]] = {}
    for name in _load_order():
        f = js_dir / f"{name}.js"
        if not f.exists():
            continue
        for m in re.finditer(
            r"^(?:async\s+)?function\s+(\w+)\s*\(", f.read_text(encoding="utf-8"), re.M
        ):
            out.setdefault(m.group(1), []).append(name)
    return out


class TestGlobalNamesDoNotShadow:
    """화면 JS 는 classic script 라 최상위 `function` 이 전부 전역이다.

    두 파일이 같은 이름을 선언하면 **뒤에 적재된 쪽이 이긴다.** 앞쪽 파일의
    호출까지 남의 구현으로 돌고, 예외도 경고도 나지 않는다.

    2026-09-22 실측으로 드러난 것: `_updateSaveStatus` 가 `text-editor.js`(교정 탭)와
    `interpretation.js`(죽은 해석 패널) 둘에 있었고 뒤인 interpretation 이 이겨,
    **교정 탭에서 저장해도 상태 표시가 안 바뀌고 있었다.** 죽은 패널을 걷어내면서
    (B-008) 그 정의가 사라져 함께 고쳐졌다 — 되살아나면 다시 깨진다.

    나머지 여섯은 아직 겹쳐 있다(B-009). 여기서는 **늘지 않는 것만** 지킨다 —
    고치는 것은 아홉 파일을 건드리는 일이라 따로 한다.
    """

    #: 2026-09-22 실측. 고칠 때는 이 목록에서 지운다(B-009).
    #: `_render*` 셋은 같은 날 풀었다 — 현토·번역 탭이 자기 화면이 아니라 주석 탭 요소를
    #: 그리고 있었고(실측: `#trans-source-text` 0자 / 숨은 `#ann-source-text` 1,656자,
    #: `#hyeonto-ann-list` 0자인데 `hyeontoState.annotations` 는 3건), 지는 쪽 이름을
    #: `_renderHyeontoAnnList`·`_renderTransSourceText`·`_renderTransStatusSummary` 로 바꿨다.
    #: 남은 이스케이프 셋은 **아직 무엇이 어긋나는지 재지 않았다** — 재기 전에는 고치지 않는다.
    KNOWN = {
        "_escAttr",
        "_escHtml",
        "_escapeHtml",
    }

    def test_no_new_shadowing(self):
        """새로 겹치는 이름이 생기지 않는다."""
        dups = {k: v for k, v in _toplevel_functions().items() if len(set(v)) > 1}
        new = set(dups) - self.KNOWN
        assert not new, (
            f"전역 함수 이름이 새로 겹쳤다: {sorted(new)}\n"
            f"  뒤에 적재된 파일이 이기고, 앞쪽 파일의 호출까지 그 구현으로 돈다.\n"
            f"  자세히: { {k: dups[k] for k in sorted(new)} }"
        )

    def test_known_list_is_not_stale(self):
        """고쳐진 것을 목록에 남겨 두지 않는다 — 남기면 다음 사람이 오해한다."""
        dups = set(k for k, v in _toplevel_functions().items() if len(set(v)) > 1)
        gone = self.KNOWN - dups
        assert not gone, (
            f"이 이름들은 이제 겹치지 않는다: {sorted(gone)}\n"
            f"  → KNOWN 에서 지우고 B-009 를 갱신한다."
        )

    def test_update_save_status_does_not_come_back(self):
        """`_updateSaveStatus` 는 `text-editor.js` 하나에만 있어야 한다."""
        decl = _toplevel_functions().get("_updateSaveStatus", [])
        assert decl == ["text-editor"], (
            f"_updateSaveStatus 가 {decl} 에 선언돼 있다 — "
            "`text-editor.js` 의 것을 가려 교정 탭의 저장 표시를 죽인다."
        )


class TestEscapeHelpersAreStrict:
    """이스케이프 헬퍼는 **큰따옴표까지** 막아야 한다.

    왜 전부 검사하는가: 이 이름들은 여러 파일이 각각 선언하고 그중 하나가 전역에서
    이긴다(위 B-009). 이기는 판이 느슨하면 **남의 호출까지 느슨해진다.** 실제로
    `annotation-editor.js` 의 `_escHtml` 에 `"` 처리가 없어서, `entity-manager.js` 가
    Concept 라벨을 `title="…"` 속성에 넣는 자리가 따옴표로 속성을 벗어날 수 있었다
    (2026-09-22 고침). 어느 판이 이길지에 안전이 달리지 않게, **전부** 엄격히 둔다.

    D-069 가 적어 둔 규칙이 이것이다 — 「화면에 넣는 파일명·OCR 원문은 이스케이프」.
    """

    def _impl(self, fname: str, fileno: str) -> str:
        js = (REPO / "src" / "app" / "static" / "js" / f"{fileno}.js").read_text(
            encoding="utf-8"
        )
        m = re.search(rf"^(?:async\s+)?function\s+{fname}\s*\(", js, re.M)
        assert m, f"{fileno}.js 에 {fname} 이 없다"
        i = js.index("{", m.start())
        depth = 0
        for j in range(i, len(js)):
            if js[j] == "{":
                depth += 1
            elif js[j] == "}":
                depth -= 1
                if depth == 0:
                    return js[m.start() : j + 1]
        raise AssertionError(f"{fname} 의 닫는 중괄호를 찾지 못했다")

    @pytest.mark.parametrize(
        ("fname", "fileno"),
        [
            ("_escHtml", "entity-manager"),
            ("_escHtml", "annotation-editor"),
            ("_escHtml", "batch-correction"),
            ("_escAttr", "annotation-editor"),
            ("_escAttr", "variant-manager"),
        ],
    )
    def test_quotes_are_escaped(self, fname, fileno):
        body = self._impl(fname, fileno)
        assert '"/g' in body or "textContent" in body, (
            f"{fileno}.js::{fname} 가 큰따옴표를 막지 않는다 — "
            "속성 안에 들어가면 따옴표로 속성을 벗어난다"
        )

    def test_the_winner_is_strict(self):
        """실제로 **이기는 판**이 엄격한지 — 적재 순서로 판정한다."""
        decl = _toplevel_functions().get("_escHtml", [])
        assert decl, "_escHtml 선언을 찾지 못했다"
        winner = decl[-1]
        body = self._impl("_escHtml", winner)
        assert '"/g' in body or "textContent" in body, (
            f"전역에서 이기는 _escHtml 은 {winner}.js 의 것인데 큰따옴표를 막지 않는다"
        )
