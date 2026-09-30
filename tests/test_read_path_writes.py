"""화면을 «열기만 해도» 서고에 쓰던 것 셋을 고정한다(2026-09-30 스크린샷 갱신 중 발견).

왜 이 시험이 필요한가:
    1. 단위 목록을 읽는 길(doc_units)이 원본 저장소 HEAD가 바뀔 때마다 모든 경계의 l4_commit
       도장을 새 해시로 고쳐 저장했다 — 커밋하지 않아 경계 파일이 «수정됨»으로 남았다
       (lecture_2026 273개). 자리가 실제로 바뀔 때만 쓰고, 쓰면 커밋까지 한다.
    2. 쪽 텍스트를 읽는 화면 코드(loadPageText)가 모든 모드에서 빈 확정본을 OCR로 채웠다.
       자동 채우기는 교정 탭의 것이다(user-guide «교정 인덱스는 … 저절로 채웁니다»).
    3. 편성 탭 「단위 손보기」만 단위 번호를 order+1로 세어 트리·편집기와 하나씩 어긋났다.
"""

from __future__ import annotations

import json
from pathlib import Path

import git

from src.core import boundaries as B
from src.core import entity as E
from tests.js_harness import run_js

L0 = "○七日晴朝食後往訪金生歸路遇雨○八日雨終日在家讀書"
L1 = "夜半風止○九日晴與客論詩至暮"
PAGE1 = "\n".join([L0, L1])


def _doc_repo(tmp_path: Path, stamp: str | None) -> Path:
    """L4 한 쪽 + 경계 둘(앵커 글자 있음)을 커밋한 원본 저장소."""
    doc = tmp_path / "lib" / "documents" / "d"
    (doc / "L4_text" / "pages").mkdir(parents=True)
    (doc / "manifest.json").write_text(
        json.dumps({"document_id": "d", "parts": [{"part_id": "v1", "page_count": 1}]}),
        encoding="utf-8",
    )
    (doc / "L4_text" / "pages" / "v1_page_001.txt").write_text(PAGE1, encoding="utf-8")
    items = []
    for line, off, title in ((0, 0, "七日"), (1, L1.index("○九日"), "九日")):
        b = B.new_boundary({"page": 1, "line": line, "offset": off}, title=title)
        b["anchor_text"] = B.anchor_text_at({1: PAGE1}, b["start"])
        b["l4_commit"] = stamp
        items.append(b)
    B.save_doc_boundaries(doc, {"document_id": "d", "part_id": "v1", "boundaries": items})
    repo = git.Repo.init(doc)
    repo.git.add("-A")
    repo.index.commit("init")
    return doc


def _status(doc: Path) -> str:
    return git.Repo(doc).git.status("--porcelain")


class TestDocUnitsReadPath:
    def test_stamp_only_change_is_not_written(self, tmp_path):
        """도장만 다르면(자리·앵커 그대로) 파일도 커밋도 건드리지 않는다."""
        doc = _doc_repo(tmp_path, stamp=None)
        before = (doc / "boundaries" / "v1.json").read_bytes()
        n_commits = len(list(git.Repo(doc).iter_commits()))
        E._PART_LINES_CACHE.clear()

        units = E.doc_units(doc, "d", "v1")

        assert [u["metadata"]["title"] for u in units] == ["七日", "九日"]
        assert (doc / "boundaries" / "v1.json").read_bytes() == before
        assert _status(doc) == ""
        assert len(list(git.Repo(doc).iter_commits())) == n_commits

    def test_real_move_is_saved_and_committed_once(self, tmp_path):
        """L4가 바뀌어 자리가 옮겨지면 저장하고 커밋한다 — 작업 트리는 깨끗, 다음 읽기는 조용."""
        doc = _doc_repo(tmp_path, stamp="old")
        repo = git.Repo(doc)
        # 사람이 교정해 둘째 줄 앞에 글자를 넣고 커밋했다 — «○九日» 자리가 두 칸 밀린다
        (doc / "L4_text" / "pages" / "v1_page_001.txt").write_text(
            "\n".join([L0, "追記" + L1]), encoding="utf-8"
        )
        repo.git.add("-A")
        repo.index.commit("교정")
        E._PART_LINES_CACHE.clear()

        E.doc_units(doc, "d", "v1")

        data = json.loads((doc / "boundaries" / "v1.json").read_text(encoding="utf-8"))
        nine = next(b for b in data["boundaries"] if b["title"] == "九日")
        assert nine["start"]["offset"] == L1.index("○九日") + 2
        assert _status(doc) == ""
        head_after = repo.head.commit.hexsha
        assert "경계 자리를 다시 찾음" in repo.head.commit.message

        # 커밋으로 HEAD가 바뀌어도 자리는 그대로라 다시 쓰지 않는다(쓰기 ↔ 커밋이 돌지 않는다)
        E._PART_LINES_CACHE.clear()
        E.doc_units(doc, "d", "v1")
        assert repo.head.commit.hexsha == head_after
        assert _status(doc) == ""

    def test_commit_takes_only_the_boundary_file(self, tmp_path):
        """사람이 저장만 해 둔 다른 파일은 재대조 커밋에 끌려 들어가지 않는다."""
        doc = _doc_repo(tmp_path, stamp="old")
        repo = git.Repo(doc)
        (doc / "L4_text" / "pages" / "v1_page_001.txt").write_text(
            "\n".join([L0, "追記" + L1]), encoding="utf-8"
        )
        repo.git.add("-A")
        repo.index.commit("교정")
        (doc / "notes.txt").write_text("저장만 한 메모", encoding="utf-8")
        E._PART_LINES_CACHE.clear()

        E.doc_units(doc, "d", "v1")

        assert _status(doc) == "?? notes.txt"
        assert repo.head.commit.stats.files.keys() == {"boundaries/v1.json"}


# ── 화면 JS ─────────────────────────────────────────────────────────────

_FILL_SETUP = """
const calls = [];
const _fillInFlight = new Map();
let currentMode = "view";
const viewerState = {docId: "d", partId: "v1", pageNum: 2};
let l4 = "";
function showToast() {}
const el = {style: {}, value: "", textContent: "", classList: {add() {}, remove() {}}};
const document = {getElementById: () => el};
async function fetch(url, init) {
  const m = (init && init.method) || "GET";
  calls.push(m + " " + url);
  if (url.includes("/ocr/fill-text")) {
    l4 = "OCR 글";
    return {ok: true, json: async () => ({filled: 1})};
  }
  const file_path = "L4_text/pages/v1_page_002.txt";
  return {ok: true, json: async () => ({exists: !!l4, text: l4, file_path})};
}
"""


def test_load_page_text_fills_only_in_correction_mode(tmp_path):
    """열람·추출 등 다른 모드에서 쪽을 열면 fill-text(POST)를 부르지 않는다.

    교정 탭에서만 채운다.
    """
    out = run_js(
        tmp_path,
        "text-editor.js",
        ["fillEmptyPageText", "_inCorrectionMode", "loadPageText"],
        _FILL_SETUP,
        """
        try { await loadPageText("d", "v1", 2); } catch (e) {}
        const viewPosts = calls.filter((c) => c.startsWith("POST")).length;
        calls.length = 0;
        currentMode = "correction";
        try { await loadPageText("d", "v1", 2); } catch (e) {}
        const corrPosts = calls.filter((c) => c.startsWith("POST")).length;
        console.log(JSON.stringify({viewPosts, corrPosts, text: el.value}));
        """,
    )
    assert out["viewPosts"] == 0
    assert out["corrPosts"] == 1
    assert out["text"] == "OCR 글"


def test_fill_is_one_request_per_page_even_if_asked_twice(tmp_path):
    """교정 편집기와 텍스트 편집기가 같은 쪽을 동시에 채워도 요청은 한 번."""
    out = run_js(
        tmp_path,
        "text-editor.js",
        ["fillEmptyPageText"],
        _FILL_SETUP,
        """
        const [a, b] = await Promise.all([
          fillEmptyPageText("d", "v1", 2),
          fillEmptyPageText("d", "v1", 2),
        ]);
        const posts = calls.filter((c) => c.startsWith("POST")).length;
        console.log(JSON.stringify({a, b, posts}));
        """,
    )
    assert out == {"a": True, "b": True, "posts": 1}


def test_composition_numbers_units_like_the_tree(tmp_path):
    """「단위 손보기」의 #N은 사이드바 트리·편집기와 같은 sequence_index다(order+1이 아니다)."""
    out = run_js(
        tmp_path,
        "composition-editor.js",
        ["_loadCompositionData"],
        """
        const compState = {units: [], active: false, pendingUnitId: null};
        const viewerState = {docId: "lecture_2026", partId: "vol1", pageNum: 173};
        function _renderUnits() {}
        function _updateBlockCount() {}
        function _renderCurrentBoundaries() {}
        async function fetch() {
          return {ok: true, json: async () => ({boundaries: [
            {id: "a", order: 266, sequence_index: 266, title: "앞"},
            {id: "u", order: 267, sequence_index: 267, title: "愛蓮説"},
          ]})};
        }
        """,
        """
        await _loadCompositionData();
        console.log(JSON.stringify(compState.units.map((u) => [u.id, u.sequence_index])));
        """,
    )
    assert out == [["a", 266], ["u", 267]]
