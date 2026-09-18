"""D-126 — 쪽 훑어보기: 모델은 정해진 답만 하고, 코드가 구간을 묶고 설치된 엔진만 권한다."""

import json

from core.page_survey import (
    group_engine_ranges,
    group_rotation_ranges,
    parse_survey,
    recommend_engine,
    target_rotation,
)
from tests.test_segmentation import _setup, client  # noqa: F401 — fixture 재사용


def test_parse_survey_accepts_only_known_values():
    assert parse_survey('{"orientation": "needs_cw", "contents": ["kunten"]}') == (
        "needs_cw",
        ["kunten"],
    )
    assert parse_survey('{"orientation": "needs_cw", "content": "kunten"}') == (
        "needs_cw",
        ["kunten"],
    )
    assert parse_survey('{"orientation": "sideways", "contents": ["poem", "hangul"]}') == (
        None,
        ["hangul"],
    )
    assert parse_survey("답: needs_ccw, hangul 입니다") == ("needs_ccw", ["hangul"])
    assert parse_survey("") == (None, [])


def test_mixed_page_is_flagged_not_assigned():
    from core.page_survey import is_mixed, text_contents

    assert is_mixed(["kunten", "hangul"]) and not is_mixed(["kunten"])
    assert not is_mixed(["kunten", "blank"])
    # 한 엔진이 함께 읽는 짝은 섞임이 아니다 — 한글 논문(활자+한글)·훈점본(판본+훈점)
    from core.page_survey import primary_content

    for pair, rep in (
        (["modern_print", "hangul"], "hangul"),
        (["classical_print", "kunten"], "kunten"),
        (["kunten", "handwriting"], "kunten"),
    ):
        assert not is_mixed(pair) and primary_content(pair) == rep
    assert is_mixed(["modern_print", "handwriting"])
    assert primary_content(["modern_print", "handwriting"]) is None
    assert is_mixed(["kunten", "hangul", "classical_print"])
    # 같은 답 둘은 하나
    assert primary_content(["classical_print", "classical_print"]) == "classical_print"
    assert primary_content(["blank"]) == "blank" and primary_content([]) is None
    assert text_contents(["blank", "hangul"]) == ["hangul"]


def _stripes(vertical: bool, w=300, h=400) -> bytes:
    """세로 줄무늬(세로쓰기 열) 또는 가로 줄무늬 그림."""
    from io import BytesIO

    from PIL import Image, ImageDraw

    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    if vertical:
        for x in range(20, w - 20, 24):
            d.rectangle([x, 20, x + 10, h - 20], fill=0)
    else:
        for y in range(20, h - 20, 24):
            d.rectangle([20, y, w - 20, y + 10], fill=0)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_projection_tells_upright_from_sideways_by_writing_direction():
    from core.page_survey import orientation_by_projection, sideways_target

    up, r1 = orientation_by_projection(_stripes(vertical=True), "vertical_rtl")
    side, r2 = orientation_by_projection(_stripes(vertical=False), "vertical_rtl")
    assert up == "upright" and side == "sideways" and r1 > 1.5 > 1 / 1.5 > r2
    # 가로쓰기 책은 관계가 뒤집힌다
    assert orientation_by_projection(_stripes(vertical=False), "horizontal_ltr")[0] == "upright"
    assert orientation_by_projection(_stripes(vertical=True), "horizontal_ltr")[0] == "sideways"
    # 백지·못 읽는 것은 모름
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("L", (100, 100), 255).save(buf, format="PNG")
    assert orientation_by_projection(buf.getvalue())[0] is None
    assert orientation_by_projection(b"not an image")[0] is None
    assert sideways_target(90) == 0 and sideways_target(0) == 90
    # 권이 180°면 0°를 제안하면 안 된다(후보 0°·180° 둘 다 여전히 누움) — ±90°인 90°를 제안한다
    assert sideways_target(180) == 90 and sideways_target(270) == 0


def test_ocr_scores_pick_the_readable_candidate():
    """가짜 OCR: 0°로 돌린 조각만 많이 읽힌다 → 0을 고른다. 점수가 비슷하면 모름."""
    from core.page_survey import ocr_score, orientation_by_ocr_scores

    class Line:
        def __init__(self, text, conf):
            self.text = text
            self.characters = [type("C", (), {"confidence": conf})() for _ in text]

    class Res:
        def __init__(self, lines):
            self.lines = lines

    assert ocr_score(Res([Line("四字", 0.5), Line("二", 1.0)])) == 3 * (0.5 * 4 + 1.0 * 2) / 6
    calls = []

    def fake(image_bytes, writing_direction="vertical_rtl"):
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(image_bytes))
        calls.append(img.size)
        upright = img.size[0] < img.size[1]  # 세로로 긴 조각 = 0°/180° 후보 — 첫 호출만 잘 읽힌다
        n = 60 if (upright and len(calls) == 1) else 20
        return Res([Line("字" * n, 1.0 if n == 60 else 0.4)])

    best, scores = orientation_by_ocr_scores(_stripes(True, 300, 400), fake, (0, 180))
    assert best == 0 and scores[0] > scores[180] * 1.3

    def same(image_bytes, writing_direction="vertical_rtl"):
        return Res([Line("字" * 10, 0.9)])

    assert orientation_by_ocr_scores(_stripes(True), same, (90, 270))[0] is None
    assert orientation_by_ocr_scores(b"bad", same, (0, 180)) == (None, {})


def test_target_rotation_adds_to_current():
    assert target_rotation(90, "upright") == 90
    assert target_rotation(90, "needs_ccw") == 0  # 90 + 270
    assert target_rotation(0, "upside_down") == 180
    assert target_rotation(0, None) is None


def test_recommend_engine_uses_installed_only():
    assert recommend_engine("kunten", {"honkoku", "ndlocr"}) == "honkoku"
    assert recommend_engine("kunten", {"ndlkotenocr", "ndlocr"}) == "ndlkotenocr"  # 대안
    assert recommend_engine("hangul", {"paddleocr"}) == "paddleocr"
    assert recommend_engine("handwriting", {"ndlkotenocr-full", "honkoku"}) == "ndlkotenocr-full"
    assert (
        recommend_engine("blank", {"ndlocr"}) is None and recommend_engine(None, {"ndlocr"}) is None
    )


def test_rotation_ranges_stop_at_upright_and_absorb_unknown():
    rows = [
        {"page": 1, "current": 90, "target": 90},
        {"page": 2, "current": 90, "target": 0},
        {"page": 3, "current": 90, "target": None},  # 모름 — 끊지 않는다
        {"page": 4, "current": 90, "target": 0},
        {"page": 5, "current": 90, "target": 90},  # 바로 선 쪽 — 구간 끝
        {"page": 6, "current": 90, "target": 0},
        {"page": 7, "current": 90, "target": 180},
    ]
    out = group_rotation_ranges(rows)
    assert out == [
        {"from": 2, "to": 4, "rotation": 0, "pages": 2},
        {"from": 6, "to": 6, "rotation": 0, "pages": 1},
        {"from": 7, "to": 7, "rotation": 180, "pages": 1},
    ]


def test_engine_ranges_group_consecutive_and_skip_blank():
    rows = [
        {"page": 1, "engine": "ndlocr", "content": "modern_print"},
        {"page": 2, "engine": None, "content": "blank"},
        {"page": 3, "engine": "ndlocr", "content": "modern_print"},
        {"page": 4, "engine": "honkoku", "content": "kunten"},
        {"page": 5, "engine": "honkoku", "content": "kunten"},
    ]
    out = group_engine_ranges(rows)
    assert [(r["from"], r["to"], r["engine"], r["pages"]) for r in out] == [
        (1, 3, "ndlocr", 2),
        (4, 5, "honkoku", 2),
    ]


def test_route_is_gpu_only(client, tmp_path, monkeypatch):  # noqa: F811
    """CPU 환경(torch 없음)에서는 dry_run조차 400 — 쪽마다 OCR 두 번은 CPU에서 한 시간이다."""
    from core import env_doctor

    _lib, part_id = _setup(client, tmp_path)
    monkeypatch.setattr(env_doctor, "_GPU_RUNTIME", False)
    r = client.post(f"/api/documents/d1/parts/{part_id}/rotation/suggest", json={"dry_run": True})
    assert r.status_code == 400 and r.json()["gpu_only"] is True
    assert "GPU 환경" in r.json()["error"]
    assert client.get("/api/ocr/engines").json()["gpu_runtime"] is False


def test_route_dry_run_and_survey_with_fake_vision(client, tmp_path, monkeypatch):  # noqa: F811
    from app import _state
    from core import env_doctor

    monkeypatch.setattr(env_doctor, "_GPU_RUNTIME", True)  # GPU 환경인 척
    _lib, part_id = _setup(client, tmp_path)
    url = f"/api/documents/d1/parts/{part_id}/rotation/suggest"
    r = client.post(url, json={"dry_run": True})
    assert r.status_code == 200
    assert r.json() == {"dry_run": True, "pages": 3, "calls": 3, "ocr_calls": 6}
    r = client.post(url, json={"dry_run": True, "pages": [2, 3]})
    assert r.json()["pages"] == 2

    answers = iter(
        [
            '{"orientation": "upright", "contents": ["modern_print"]}',
            '{"orientation": "needs_cw", "contents": ["kunten"]}',
            '{"orientation": "needs_cw", "contents": ["kunten", "hangul"]}',  # 섞인 쪽
        ]
    )

    class FakeVision:
        calls = []

        async def call_with_image(self, prompt, image, **kwargs):
            self.calls.append(kwargs)

            class R:
                text, provider, model = next(answers), "fake", "v-1"

            return R()

    monkeypatch.setattr(_state, "_llm_router", FakeVision())
    r = client.post(url, json={})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["checked"] == 3 and d["unknown"] == 0 and d["model"] == "v-1"
    # 빈 PDF 쪽은 투영이 모름이라 모델의 방향 답을 쓴다
    assert d["rotation"] == [
        {
            "from": 2,
            "to": 3,
            "rotation": 90,
            "pages": 2,
            "current_rotation": 0,
            "effect": 0,
            "guess": False,
        }
    ]
    assert d["per_page"][0]["heuristic"]["orientation"] is None
    assert [(e["from"], e["to"], e["content"]) for e in d["engines"]] == [
        (1, 1, "modern_print"),
        (2, 2, "kunten"),
    ]
    assert d["mixed"] == [
        {"page": 3, "contents": ["kunten", "hangul"], "label": "훈점 달림 + 한글 있음"}
    ]
    assert d["per_page"][2]["engine"] is None and d["per_page"][2]["mixed"] is True
    assert FakeVision.calls[0]["response_format"] == "json"
    assert FakeVision.calls[0]["image_mime"] == "image/jpeg"
    # 회전 제안을 그대로 PUT하면 쪽 범위 회전이 된다
    r = client.put(
        f"/api/documents/d1/parts/{part_id}/rotation", json={"rotation": 90, "pages": [2, 3]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["ranges"] == [{"from": 2, "to": 3, "rotation": 90}]
    got = client.get(f"/api/documents/d1/parts/{part_id}/rotation").json()
    assert got["rotation"] == 0 and got["ranges"] == [{"from": 2, "to": 3, "rotation": 90}]
    body = json.loads(r.text)
    assert body["rotation"] == 0


def test_route_streams_progress(client, tmp_path, monkeypatch):  # noqa: F811
    """stream=True면 SSE — start, 쪽마다 page, 마지막 complete(결과 전체). 진행 막대가 읽는다."""
    import json as _json

    from app import _state
    from core import env_doctor

    monkeypatch.setattr(env_doctor, "_GPU_RUNTIME", True)
    _lib, part_id = _setup(client, tmp_path)

    class FakeVision:
        async def call_with_image(self, prompt, image, **kwargs):
            class R:
                text = '{"orientation": "upright", "contents": ["classical_print"]}'
                provider, model = "fake", "v-1"

            return R()

    monkeypatch.setattr(_state, "_llm_router", FakeVision())
    url = f"/api/documents/d1/parts/{part_id}/rotation/suggest"
    with client.stream("POST", url, json={"stream": True, "pages": [1, 2]}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        events = [_json.loads(ln[6:]) for ln in r.iter_lines() if ln.startswith("data: ")]
    assert [e["type"] for e in events] == ["start", "page", "page", "complete"]
    assert events[0]["total"] == 2
    assert events[1]["page"] == 1 and events[1]["content"] == "classical_print"
    assert events[1]["label"]
    assert events[-1]["checked"] == 2 and events[-1]["model"] == "v-1" and "engines" in events[-1]
    # stream을 켜지 않으면 전처럼 JSON 하나
    d = client.post(url, json={"pages": [1, 2]}).json()
    assert d["checked"] == 2 and "rotation" in d


# ── «돌아간 쪽은 세워서»(D-126 덧붙임 2026-09-18) — orientation_only ─────────────────────


class _NoVision:
    """방향만 잴 때 비전 모델을 부르면 안 된다 — 부르면 곧 실패."""

    async def call_with_image(self, prompt, image, **kwargs):
        raise AssertionError("orientation_only인데 비전 모델을 불렀다")


class _FakePaddle:
    """가짜 PaddleOCR — 후보마다 recognize가 불린 횟수를 센다. 첫 후보(90°)만 많이 읽힌다."""

    engine_id = "paddleocr"

    def __init__(self):
        self.calls = 0

    def is_available(self):
        return True

    def recognize(self, image_bytes, writing_direction="vertical_rtl"):
        self.calls += 1

        class Line:
            def __init__(self, text, conf):
                self.text = text
                self.characters = [type("C", (), {"confidence": conf})() for _ in text]

        n = 60 if self.calls % 2 == 1 else 20
        return type("R", (), {"lines": [Line("字" * n, 1.0 if n == 60 else 0.4)]})()


class _FakeRegistry:
    def __init__(self, paddle):
        self._paddle = paddle

    def list_engines(self):
        return []

    def get_engine(self, engine_id):
        return self._paddle if engine_id == "paddleocr" else None


def _patch_pages(monkeypatch):
    """1·3쪽은 세로 줄(바로 섬), 2쪽은 가로 줄(누움)."""
    from app.routers import llm_ocr

    monkeypatch.setattr(
        llm_ocr,
        "_load_page_image",
        lambda doc_id, page, part_id=None: _stripes(vertical=(page != 2)),
    )


def test_orientation_only_runs_on_cpu_without_model(client, tmp_path, monkeypatch):  # noqa: F811
    """CPU 환경 + 비전 모델 없음: 투영만으로 누운 쪽을 찾고 추정(guess)으로 돌려준다. OCR 점수는 재지 않는다."""
    from app import _state
    from app.routers import llm_ocr
    from core import env_doctor

    _lib, part_id = _setup(client, tmp_path)
    monkeypatch.setattr(env_doctor, "_GPU_RUNTIME", False)
    monkeypatch.setattr(_state, "_llm_router", _NoVision())
    paddle = _FakePaddle()
    monkeypatch.setattr(llm_ocr, "_get_ocr_pipeline", lambda: (None, _FakeRegistry(paddle)))
    _patch_pages(monkeypatch)
    url = f"/api/documents/d1/parts/{part_id}/rotation/suggest"

    # GPU 게이트를 지나지 않는다 — dry_run도 호출 0
    r = client.post(url, json={"dry_run": True, "orientation_only": True})
    assert r.status_code == 200 and r.json()["calls"] == 0
    # 같은 환경에서 방향만이 아니면 여전히 막힌다
    assert client.post(url, json={"dry_run": True}).status_code == 400

    r = client.post(url, json={"orientation_only": True})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["calls"] == 0 and d["model"] is None and d["engines"] == [] and d["mixed"] == []
    assert d["unknown"] == 0
    assert d["rotation"] == [
        {
            "from": 2,
            "to": 2,
            "rotation": 90,
            "pages": 1,
            "current_rotation": 0,
            "effect": 0,
            "guess": True,  # CPU라 90/270을 못 가려 추정 — 화면이 미리보기로 묻는다
        }
    ]
    assert paddle.calls == 0
    assert [p["orientation"] for p in d["per_page"]] == ["upright", "sideways", "upright"]


def test_orientation_only_scores_sideways_pages_on_gpu(client, tmp_path, monkeypatch):  # noqa: F811
    """GPU 환경: 누운 쪽에서만 PaddleOCR 점수(후보 둘)를 재어 90/270을 확정한다. 선 쪽은 180° 검사를 하지 않는다."""
    import json as _json

    from app import _state
    from app.routers import llm_ocr
    from core import env_doctor

    _lib, part_id = _setup(client, tmp_path)
    monkeypatch.setattr(env_doctor, "_GPU_RUNTIME", True)
    monkeypatch.setattr(_state, "_llm_router", _NoVision())
    paddle = _FakePaddle()
    monkeypatch.setattr(llm_ocr, "_get_ocr_pipeline", lambda: (None, _FakeRegistry(paddle)))
    _patch_pages(monkeypatch)
    url = f"/api/documents/d1/parts/{part_id}/rotation/suggest"

    with client.stream("POST", url, json={"orientation_only": True, "stream": True}) as r:
        assert r.status_code == 200
        events = [_json.loads(ln[6:]) for ln in r.iter_lines() if ln.startswith("data: ")]
    assert [e["type"] for e in events] == ["start", "page", "page", "page", "complete"]
    # 종류 라벨이 없으니 진행 표시는 방향을 보인다
    assert [e["label"] for e in events[1:4]] == ["바로 섬", "누움", "바로 섬"]
    d = events[-1]
    assert paddle.calls == 2  # 누운 2쪽에서만 후보 둘 — 선 쪽 1·3은 재지 않는다
    assert d["rotation"] == [
        {
            "from": 2,
            "to": 2,
            "rotation": 90,
            "pages": 1,
            "current_rotation": 0,
            "effect": 0,
            "guess": False,
        }
    ]
    assert d["per_page"][1]["heuristic"]["ocr_scores"].keys() == {"90", "270"}


def test_orientation_only_counts_pages_from_pdf_when_manifest_lacks_page_count(
    client, tmp_path, monkeypatch
):  # noqa: F811
    """add_document로 만든 문헌은 manifest에 page_count가 없다 — PDF를 열어 센다(E2E 실측 2026-09-18: «쪽 수를 몰라» 400)."""
    import json as _json
    from pathlib import Path

    from app import _state
    from core import env_doctor

    lib, part_id = _setup(client, tmp_path)
    monkeypatch.setattr(env_doctor, "_GPU_RUNTIME", False)
    monkeypatch.setattr(_state, "_llm_router", _NoVision())
    _patch_pages(monkeypatch)
    mf = Path(lib) / "documents" / "d1" / "manifest.json"
    data = _json.loads(mf.read_text(encoding="utf-8"))
    for p in data["parts"]:
        p["page_count"] = None
    mf.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")

    r = client.post(f"/api/documents/d1/parts/{part_id}/rotation/suggest", json={"orientation_only": True})
    assert r.status_code == 200, r.text
    assert r.json()["checked"] == 3
