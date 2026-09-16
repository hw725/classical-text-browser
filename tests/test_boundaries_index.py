"""단위 계산이 행 색인을 한 번만 만든다 — 행마다 경계가 있어도 O(N²)이 되지 않는다.

Codex 교차검증(2026-09-16) ⑨.

왜 이 시험이 필요한가:
    `compute_units()`가 경계마다 `keys.index()`(선형 탐색)를 세 번 넘게 불렀다. 행 N·단위 B에
    O(B·N) — 일기류처럼 거의 행마다 경계가 서면 O(N²)이다. 시간을 재는 대신 **비교 횟수를 센다**:
    행 번호를 `==` 호출을 세는 int 하위형으로 만들어, 선형 탐색이면 N²급·사전 색인이면 N급이 된다.
"""

from __future__ import annotations

from src.core import boundaries as B
from src.core.segmentation import Line


class CountingInt(int):
    """`==`가 불린 횟수를 세는 정수. 튜플 비교(`keys.index`)가 원소마다 이것을 부른다."""

    calls = 0

    def __eq__(self, other):
        CountingInt.calls += 1
        return int.__eq__(self, other)

    def __ne__(self, other):
        return not self.__eq__(other)

    __hash__ = int.__hash__


def _make(n_lines: int):
    pt: dict[int, str] = {}
    lines: list[Line] = []
    bounds: list[dict] = []
    lines_per_page = 10
    for i in range(n_lines):
        page = i // lines_per_page + 1
        li = i % lines_per_page
        text = f"○{i:04d}日晴本文本文"
        pt.setdefault(page, [])
        pt[page].append(text)
        lines.append(Line(CountingInt(page), li, text))
        bounds.append({"page": page, "line": li, "offset": 0, "level": 2, "title": str(i)})
    page_texts = {p: "\n".join(t) for p, t in pt.items()}
    off = {}
    for ln in lines:
        ln.char_start = off.get(ln.page, 0)
        off[ln.page] = ln.char_start + len(ln.text) + 1
    items = [
        B.new_boundary(
            {"page": b["page"], "line": b["line"], "offset": 0},
            level=2,
            title=b["title"],
            page_texts=page_texts,
        )
        for b in bounds
    ]
    return {"document_id": "d", "part_id": "v1", "boundaries": items}, lines, page_texts


def test_units_are_correct_with_boundary_on_every_line():
    data, lines, pt = _make(30)
    units = B.compute_units(data, lines, pt)
    assert len(units) == 30
    assert units[0]["original_text"] == lines[0].text
    assert units[29]["original_text"] == lines[29].text
    # 쪽을 넘는 마지막 단위도 자기 행만
    assert units[9]["original_text"] == lines[9].text


def test_equality_comparisons_scale_linearly_not_quadratically():
    n = 600
    data, lines, pt = _make(n)
    CountingInt.calls = 0
    units = B.compute_units(data, lines, pt)
    assert len(units) == n
    # 선형 탐색이면 경계마다 평균 N/2 비교 × 세 번 ≈ 1.5·N² = 540,000.
    # 사전 색인이면 해시 충돌 확인만 — 경계당 몇 번. 20·N을 넘으면 어딘가 다시 선형이다.
    assert CountingInt.calls < 20 * n, f"행 비교 {CountingInt.calls}회 — O(N²) 탐색이 남아 있다"
