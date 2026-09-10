"""みんなで翻刻OCR(honkoku-ocr-py) 엔진 어댑터 — 모델 없이 계약만 잰다.

실제 모델(289MB)은 여기서 돌리지 않는다. honkoku의 PageResult 모양을 흉내 낸 대역으로
«행 → L3 블록 배정», «본문 글자만 저장», «좌표 x,y,w,h → x1,y1,x2,y2»를 고정한다.
"""

import importlib.util
from dataclasses import dataclass, field

import pytest

from src.ocr.honkoku_engine import HonkokuOcrEngine


@dataclass
class _Line:
    reading_order: int
    x: float
    y: float
    width: float
    height: float
    detection_confidence: float
    raw: str
    koji: str
    plain: str
    stop_reason: str = "eos"


@dataclass
class _Page:
    lines: list
    warnings: list = field(default_factory=list)


class _FakeOcr:
    """honkoku_ocr.OCR 대역 — process()가 정해진 행을 돌려준다."""

    def __init__(self, lines):
        self.lines = lines
        self.calls = []

    def process(self, image, boxes=None):
        self.calls.append((image.size, boxes))
        return _Page(self.lines)


def _png_bytes(w=200, h=300):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return buf.getvalue()


def _engine_with(lines):
    eng = HonkokuOcrEngine()
    eng._ocr = _FakeOcr(lines)
    eng.is_available = lambda: True
    return eng


class TestHonkokuAdapter:
    def test_page_lines_are_assigned_to_blocks_as_plain_text(self):
        """입력: 두 행(한 행은 태그 있음). 출력: 블록별 본문과 x1y1x2y2. 목적: 읽기 보조는 뺀다."""
        lines = [
            _Line(1, 150, 10, 20, 100, 0.9, "甲乙丙", "甲乙丙", "甲乙丙"),
            _Line(
                2,
                20,
                10,
                20,
                100,
                0.8,
                "<ruby>丁<rt>てい</rt></ruby>戊<KAERI>レ</KAERI>",
                "丁（てい）戊＿レ",
                "丁てい戊レ",
            ),
        ]
        eng = _engine_with(lines)
        blocks = [
            {"block_id": "p01_b01", "bbox": [100, 0, 200, 300]},
            {"block_id": "p01_b02", "bbox": [0, 0, 100, 300]},
            {"block_id": "p01_b03", "bbox": [0, 0, 200, 300], "skip": True},
        ]
        out = eng.recognize_page(_png_bytes(), blocks)
        by_id = {r["layout_block_id"]: r for r in out}
        assert set(by_id) == {"p01_b01", "p01_b02"}  # skip 블록은 뺀다
        assert by_id["p01_b01"]["lines"][0]["text"] == "甲乙丙"
        assert by_id["p01_b01"]["lines"][0]["bbox"] == [150.0, 10.0, 170.0, 110.0]
        assert by_id["p01_b02"]["lines"][0]["text"] == "丁戊"  # 루비 읽기·返り点은 본문이 아니다
        assert by_id["p01_b02"]["lines"][0]["koji"] == "丁（てい）戊＿レ"  # 표기는 따로 남는다
        assert [c["char"] for c in by_id["p01_b02"]["lines"][0]["characters"]] == ["丁", "戊"]

    def test_block_crop_recognize_returns_lines(self):
        """입력: 크롭 이미지. 출력: OcrBlockResult. 목적: 블록 단위 경로도 같은 변환을 쓴다."""
        eng = _engine_with([_Line(1, 5, 5, 10, 50, 0.7, "己", "己", "己")])
        r = eng.recognize(_png_bytes(50, 80))
        assert r.full_text == "己" and r.lines[0].bbox == [5.0, 5.0, 15.0, 55.0]
        assert r.lines[0].characters[0].confidence == pytest.approx(0.7)

    def test_empty_lines_are_dropped(self):
        """입력: 빈 素テキスト 행. 출력: 저장하지 않는다."""
        eng = _engine_with([_Line(1, 0, 0, 10, 10, 0.5, "<BLOCK>", "", "")])
        out = eng.recognize_page(_png_bytes(), [{"block_id": "b", "bbox": [0, 0, 200, 300]}])
        assert out[0]["lines"] == []

    def test_registry_lists_engine(self):
        """입력: 레지스트리 자동 등록. 출력: honkoku가 목록에 있다(설치 여부와 무관)."""
        from src.ocr.registry import OcrEngineRegistry

        reg = OcrEngineRegistry()
        reg.auto_register()
        ids = [e["engine_id"] for e in reg.list_engines()]
        assert "honkoku" in ids
        assert ids.index("honkoku") < ids.index("ndlocr")  # 고서 엔진 다음, 근현대 엔진 앞


def test_body_text_keeps_original_glyphs_only():
    """입력: 디코더 원문(루비·返り点·送り仮名·割書·縦点). 출력: 원문 글자만. 목적: 보조는 뺀다."""
    from src.ocr.honkoku_engine import body_text

    raw = (
        "<ruby>化物<rt>ばけもの</rt></ruby>也<KAERI>レ</KAERI><OKURI>リ</OKURI>"
        "<WARI>右<WARI_SEP>左</WARI><TATE>"
    )
    assert body_text(raw) == "化物也右左ー"
    assert body_text("") == ""


@pytest.mark.skipif(importlib.util.find_spec("honkoku_ocr") is None, reason="honkoku-ocr-py 미설치")
def test_engine_reports_available_when_installed():
    """입력: honkoku-ocr-py가 깔린 환경. 출력: 사용 가능. 목적: import 조건이 패키지와 맞는다."""
    assert HonkokuOcrEngine().is_available() is True
