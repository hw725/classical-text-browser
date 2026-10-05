"""편성 ③ «바뀐 것»과 「적용」이 같은 것을 세는가 (2026-10-05, D-121 후속).

무엇을 고정하는가:
  - «바뀐 것»은 **체크한 행**에서 나온다. 저장된 경계가 없을 때 판정의 확신 후보(accept)를 세던
    옛 식은, 애매한 후보(escalate)를 「판정 들이기」·손으로 체크하면 «새로 잡히는 자리 27»인데
    「적용」은 45개를 쓰는 어긋남을 냈다(headless 확인).
  - 미리 보기 숫자 == 실제 서버가 쓴 수. 화면 함수 `_planApply`의 구간을 **진짜 apply 라우트**에
    보내 `new`·`removed`가 미리 보기와 같은지 본다 — 저장된 경계가 (a) 없을 때 (b) 있고 일부 체크를
    뺐을 때(+ 깊이만 바꾼 행, 「(앞부분)」 구간).
  - 가림(2차 아니오 숨기기)은 표시일 뿐 — 체크만 같으면 숫자가 같다.
"""

from __future__ import annotations

import json

from tests.js_harness import run_js
from tests.test_segmentation import _setup, client  # noqa: F401 — fixture 재사용

NAMES = [
    "_planApply",
    "_propKey",
    "_propRoleLevel",
    "_mergeCurrentBoundaries",
    "_isProposalBoundary",
]

SETUP_TMPL = """
const proposeState = { roles: new Map(), levels: new Map(), checked: new Set() };
const compState = { currentBoundaries: __BOUNDARIES__ };
const data = __DATA__;
"""


def _plan(tmp_path, data: dict, boundaries: list, body: str) -> dict:
    setup = SETUP_TMPL.replace("__DATA__", json.dumps(data, ensure_ascii=False)).replace(
        "__BOUNDARIES__", json.dumps(boundaries, ensure_ascii=False)
    )
    return run_js(tmp_path, "composition-editor.js", NAMES, setup, body)


def _propose(client, part_id):  # noqa: F811
    client.put(
        "/api/documents/d1/segmentation-rules", json={"rules": {"title_words": ["談草", "口談"]}}
    )
    r = client.post("/api/documents/d1/segmentation/propose", json={"part_id": part_id})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["lines"] and len(data["proposals"]) >= 3
    return data


def _apply(client, part_id, plan):  # noqa: F811
    r = client.post(
        "/api/documents/d1/segmentation/apply",
        json={
            "part_id": part_id,
            "spans": plan["spans"],
            "replace": "listed",
            "drop": plan["drop"],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_preview_counts_checked_not_accepted_when_nothing_saved(client, tmp_path):  # noqa: F811
    """(a) 저장된 경계 없음: 확신 후보 일부 + 애매한 후보를 체크 → 미리 보기 = 실제 쓴 수."""
    lib, part_id = _setup(client, tmp_path)
    data = _propose(client, part_id)
    # 판정 모델 답을 흉내 낸다 — 마지막 후보 둘은 애매한 대역(accept 아님)인데 체크했다
    props = data["proposals"]
    for p in props[-2:]:
        p["accepted"] = False
        p["band"] = "escalate"
    body = """
      // 모든 후보 체크(애매한 것 둘 포함) — 「판정 들이기」가 «예»를 체크한 것과 같은 상태
      for (const p of data.proposals) proposeState.checked.add(_propKey(p));
      const plan = _planApply(data, proposeState.checked, compState.currentBoundaries);
      const accepted = data.proposals.filter((p) => p.accepted).length;
      console.log(JSON.stringify({ spans: plan.spans, drop: plan.drop, added: plan.added.length,
        removed: plan.removed.length, accepted }));
    """
    got = _plan(tmp_path, data, [], body)
    # 옛 식(accept만)과 달라야 시험이 뜻이 있다
    assert got["added"] > got["accepted"]
    assert got["added"] == len(got["spans"]) and got["removed"] == 0
    res = _apply(client, part_id, got)
    assert res["new"] == got["added"] and res["removed"] == got["removed"]
    total = client.get(f"/api/documents/d1/boundaries?part_id={part_id}").json()["total"]
    assert total == got["added"]


def test_preview_matches_apply_with_saved_boundaries_some_unchecked(client, tmp_path):  # noqa: F811
    """(b) 저장된 경계 있음: 일부 체크 해제·깊이만 바꾼 행 → 미리 보기 +/− = 서버 new/removed."""
    lib, part_id = _setup(client, tmp_path)
    data = _propose(client, part_id)
    # 1차: 확신 후보만 저장
    first = _plan(
        tmp_path,
        data,
        [],
        """
      for (const p of data.proposals) if (p.accepted) proposeState.checked.add(_propKey(p));
      const plan = _planApply(data, proposeState.checked, []);
      console.log(JSON.stringify({ spans: plan.spans, drop: plan.drop, added: plan.added.length }));
    """,
    )
    res = _apply(client, part_id, first)
    assert res["new"] == first["added"]
    saved = client.get(f"/api/documents/d1/boundaries?part_id={part_id}").json()["boundaries"]
    assert len(saved) >= 3
    # 2차: 화면이 하듯 저장된 경계를 ③에 합치고(체크), 하나는 체크를 빼고, 하나는 깊이만 바꾼다
    data2 = _propose(client, part_id)
    body = """
      _mergeCurrentBoundaries(data);
      for (const p of data.proposals) if (p.boundary_id) proposeState.checked.add(_propKey(p));
      const saved = data.proposals.filter((p) => p.boundary_id && p.kind !== "front");
      // 체크 해제 → 지움. 첫 행은 피한다: 빼면 「(앞부분)」이 같은 자리에 서서 남는다
      proposeState.checked.delete(_propKey(saved[1]));
      proposeState.levels.set(_propKey(saved[2]), 3);            // 깊이만 바꿈 → 서버는 새로 세운다
      const extra = data.proposals.find((p) => !p.boundary_id);  // 저장 안 된 후보 하나 더 체크
      if (extra) proposeState.checked.add(_propKey(extra));
      const plan = _planApply(data, proposeState.checked, compState.currentBoundaries);
      console.log(JSON.stringify({ spans: plan.spans, drop: plan.drop, added: plan.added.length,
        removed: plan.removed.length }));
    """
    data2.setdefault("stats", {})
    got = _plan(tmp_path, data2, saved, body)
    assert got["removed"] == 1 and got["added"] >= 1
    # dry_run 숫자(확인창)도 같아야 한다
    r = client.post(
        "/api/documents/d1/segmentation/apply",
        json={
            "part_id": part_id,
            "spans": got["spans"],
            "replace": "listed",
            "drop": got["drop"],
            "dry_run": True,
        },
    )
    assert r.json()["would_create"] == got["added"] and r.json()["removed"] == got["removed"]
    res = _apply(client, part_id, got)
    assert res["new"] == got["added"] and res["removed"] == got["removed"]
    after = client.get(f"/api/documents/d1/boundaries?part_id={part_id}").json()["total"]
    assert after == len(saved) + got["added"] - got["removed"]


def test_hiding_second_no_does_not_change_preview(tmp_path):
    """2차 «아니오» 가림은 체크를 건드리지 않는다 — 같은 체크면 같은 미리 보기."""
    data = {
        "lines": [{"page": 1, "line_index": i, "text": f"行{i}"} for i in range(6)],
        "proposals": [
            {"page": 1, "line_index": 0, "title": "가", "accepted": True, "reasons": []},
            {
                "page": 1,
                "line_index": 2,
                "title": "나",
                "accepted": False,
                "band": "escalate",
                "second": "no",
                "reasons": [],
            },
            {
                "page": 1,
                "line_index": 4,
                "title": "다",
                "accepted": False,
                "band": "escalate",
                "second": "yes",
                "reasons": [],
            },
        ],
    }
    body = """
      proposeState.checked.add("1:0:0"); proposeState.checked.add("1:4:0");
      const a = _planApply(data, proposeState.checked, []);
      proposeState.hideSecondNo = true;   // 가림 손잡이 — 표시 상태일 뿐
      const b = _planApply(data, proposeState.checked, []);
      console.log(JSON.stringify({ a: a.added.length, b: b.added.length, spans: a.spans.length }));
    """
    got = _plan(tmp_path, data, [], body)
    # 체크 2(확신 1 + 2차 예 1) — accept만 세던 옛 식이면 1이었다
    assert got == {"a": 2, "b": 2, "spans": 2}
