"""PaddleOCR 결과 파싱 회귀 테스트 (2.x / 3.x 양쪽).

왜 있는가 (2026-08-12):
  `_parse_result`의 v3 감지 조건이 `not isinstance(raw_result, list)`였다.
  그런데 PaddleOCR 3.x의 predict()는 **이미지별 결과의 리스트**를 돌려준다.
  그래서 v3 분기가 한 번도 실행되지 않고 v2 파서로 흘러, dict를 순회하며
  키(str)를 item으로 받아 «구조 이상 — 건너뜀» 경고만 남기고 0줄을 돌려줬다.

  예외가 안 나고 로그 경고만 남아서 상위에서는 「OCR 실패」로만 보였다.
  게다가 기본 엔진이 llm_vision이라 이 경로는 `--engine paddleocr`를 명시할
  때만 타므로 오래 방치됐다.

  모델을 띄우지 않고 파서만 검증한다 — GPU도 네트워크도 필요 없다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ocr.paddleocr_engine import PaddleOcrEngine  # noqa: E402

HORIZONTAL = "horizontal"


def _poly(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


class _V3AttrResult:
    """속성으로 접근되는 3.x 결과 객체."""

    def __init__(self, texts, scores, polys):
        self.rec_texts = texts
        self.rec_scores = scores
        self.rec_polys = polys
        self.dt_polys = polys


@pytest.fixture
def engine():
    return PaddleOcrEngine(lang="korean", use_gpu=False)


def test_v3_dict_in_list(engine):
    """3.7.0 실제 형태 — dict가 리스트에 담겨 온다. 이게 깨져 있었다."""
    raw = [
        {
            "rec_texts": ["운양 김윤식", "傳統儒學思想"],
            "rec_scores": [0.98, 0.91],
            "rec_polys": [_poly(10, 20, 110, 45), _poly(10, 60, 130, 85)],
        }
    ]
    lines = engine._parse_result(raw, HORIZONTAL)
    assert [ln.text for ln in lines] == ["운양 김윤식", "傳統儒學思想"]
    assert lines[0].bbox == [10, 20, 110, 45]


def test_v3_attribute_object_in_list(engine):
    """속성 접근형 결과 객체도 리스트에 담겨 올 수 있다."""
    raw = [_V3AttrResult(["가나다"], [0.95], [_poly(1, 2, 3, 4)])]
    lines = engine._parse_result(raw, HORIZONTAL)
    assert len(lines) == 1
    assert lines[0].text == "가나다"


def test_v3_bare_object_without_list(engine):
    """리스트로 감싸지 않고 오는 판본도 계속 동작해야 한다."""
    raw = _V3AttrResult(["단독"], [0.9], [_poly(0, 0, 5, 5)])
    lines = engine._parse_result(raw, HORIZONTAL)
    assert [ln.text for ln in lines] == ["단독"]


def test_v3_nested_under_res(engine):
    """일부 판본은 알맹이를 .res 아래에 둔다."""

    class Wrapper:
        def __init__(self, inner):
            self.res = inner

    raw = [Wrapper(_V3AttrResult(["중첩"], [0.9], [_poly(0, 0, 5, 5)]))]
    lines = engine._parse_result(raw, HORIZONTAL)
    assert [ln.text for ln in lines] == ["중첩"]


def test_v2_format_still_parsed(engine):
    """2.x 형식은 그대로 동작해야 한다 — v3 감지가 오탐하면 안 된다."""
    raw = [
        [
            [_poly(5, 5, 50, 25), ("옛형식", 0.97)],
            [_poly(5, 30, 60, 50), ("두번째줄", 0.88)],
        ]
    ]
    lines = engine._parse_result(raw, HORIZONTAL)
    assert [ln.text for ln in lines] == ["옛형식", "두번째줄"]


def test_rec_polys_preferred_over_dt_polys(engine):
    """dt_polys는 인식 안 된 검출까지 담을 수 있어 인덱스가 어긋난다."""
    raw = [
        {
            "rec_texts": ["첫줄", "둘째줄"],
            "rec_scores": [0.9, 0.9],
            "rec_polys": [_poly(0, 0, 10, 10), _poly(0, 20, 10, 30)],
            "dt_polys": [
                _poly(99, 99, 100, 100),  # 인식 실패한 잡음이 앞에 낀 경우
                _poly(0, 0, 10, 10),
                _poly(0, 20, 10, 30),
            ],
        }
    ]
    lines = engine._parse_result(raw, HORIZONTAL)
    assert lines[0].bbox == [0, 0, 10, 10]  # dt_polys를 썼다면 [99,99,100,100]이 된다


def test_empty_and_blank_are_dropped(engine):
    raw = [{"rec_texts": ["", "   ", "실제"], "rec_scores": [0.1, 0.1, 0.9],
            "rec_polys": [_poly(0, 0, 1, 1), _poly(0, 2, 1, 3), _poly(0, 4, 1, 5)]}]
    lines = engine._parse_result(raw, HORIZONTAL)
    assert [ln.text for ln in lines] == ["실제"]


def test_empty_result_is_safe(engine):
    assert engine._parse_result([], HORIZONTAL) == []
    assert engine._parse_result(None, HORIZONTAL) == []


@pytest.mark.parametrize(
    "setting,expected",
    [("cpu", False), ("gpu", True), ("0", False), ("1", True), ("false", False)],
)
def test_device_setting_is_explicit(setting, expected):
    """auto가 아닌 명시 지정은 환경과 무관하게 그대로 지켜져야 한다.

    GPU 없는 사람이 쓰는 기본값(auto)은 설치된 paddle에 따라 갈리므로
    여기서 단정하지 않는다 — 명시 지정만 검증한다.
    """
    assert PaddleOcrEngine._resolve_use_gpu(setting) is expected
