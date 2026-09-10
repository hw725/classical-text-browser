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


def test_route_dry_run_and_survey_with_fake_vision(client, tmp_path, monkeypatch):  # noqa: F811
    from app import _state

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
