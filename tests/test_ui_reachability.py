"""화면의 «닿을 수 있는가» — 있는 것과 누를 수 있는 것은 다르다 (B-008).

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

        `#interp-panel` 은 모드 탭이 여는 자리라 `panelSections` 에 없다 — B-008 이
        남아 있는 동안 그 안의 단추는 이 검사를 통과하지 못해야 한다.
        """
        assert "entity-create-textblock-btn" in ancestors, "기준으로 삼은 단추가 사라졌다"
        assert "interp-panel" in ancestors["entity-create-textblock-btn"]
        with pytest.raises(AssertionError, match="여는 주체"):
            assert_reachable(
                "entity-create-textblock-btn", ancestors, index_html, panel_sections
            )

    def test_a_missing_entrance_fails(self, ancestors, index_html, panel_sections):
        """섹션은 맵에 있는데 그 이름의 액티비티 단추가 사라지면 걸린다."""
        broken = index_html.replace('data-panel="dependency"', 'data-panel="사라진것"')
        with pytest.raises(AssertionError, match="입구가 사라졌다"):
            assert_reachable("interp-dep-ack", ancestors, broken, panel_sections)

    def test_the_dead_panel_is_still_dead(self, panel_sections):
        """B-008 이 아직 열려 있음을 못박는다 — 누가 고치면 이 시험이 알려 준다.

        `#interp-panel` 이 `panelSections` 에 들어오거나 `data-mode="interpretation"`
        탭이 돌아오면 여기서 빨간불이 난다. 그때는 B-008 을 다시 읽고, 옛 통합
        편집기가 함께 돌아오는 것이 맞는지부터 정한다.
        """
        assert _opening_panel("interp-panel", panel_sections) is None
        assert 'data-mode="interpretation"' not in INDEX.read_text(encoding="utf-8")
