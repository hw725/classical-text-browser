"""古典籍 OCR 둘(Lite·Full)의 변환 코드를 모델 없이 돌려 본다.

**왜 이 파일이 생겼나(2026-09-21).** 시험이 도는 동안 `sys.monitoring`으로 엔진 파일의 함수
진입을 기록해 보니, 이 둘만 `is_available()` 말고는 **한 줄도 실행되지 않고** 있었다. 고서 판본·
손글씨의 주력 엔진인데 탐지 → XML → 읽기 순서 → 인식 → 블록 배정으로 이어지는 변환 코드가
시험에서 한 번도 돌지 않았다. 모델 파일이 없는 환경에서도 그 코드는 돌 수 있다 —
탐지기(RTMDet)와 인식기(PARSeq) 자리에 가짜를 꽂으면 된다(`test_ocr_honkoku.py`와 같은 결).

**여기서 재는 것과 재지 않는 것.** 재는 것은 «엔진 자신의 변환 규약»이다 — 탐지 상자가 읽기
순서가 붙은 행이 되는가, 블록 밖의 행을 버리는가(D-086), 빈 인식 결과를 어떻게 다루는가.
재지 않는 것은 모델의 인식 품질이다(그것은 실제 이미지로 1쪽, `scripts/eval_cer.py`).
"""

from __future__ import annotations

import numpy as np
import pytest

from ocr.ndlkotenocr_engine import NdlkotenOcrEngine
from ocr.ndlkotenocr_full_engine import NdlkotenOcrFullEngine

# 클래스 이름표는 **저장소에 실린 설정에서 읽는다.** 손으로 베껴 적으면 업스트림이 이름을 바꿀 때
# 시험만 옛 이름을 붙들고 초록으로 남는다(`ndl_parser`가 `classes.index('block_ad')`로 찾으므로
# 이름 하나만 달라도 실제 경로는 죽는다 — 처음 이 시험을 손으로 적었다가 여기서 걸렸다).
def _classes() -> dict:
    from pathlib import Path

    from yaml import safe_load

    import ocr.ndlkotenocr as pkg

    cfg = Path(pkg.__file__).parent / "config" / "ndl.yaml"
    return safe_load(cfg.read_text(encoding="utf-8"))["names"]


class _FakeRtmdet:
    """탐지기 자리 — 클래스 이름표만 있으면 변환 코드가 돈다."""

    classes = _classes()


class _FakeParseq:
    """Lite의 인식기 자리 — 크롭 하나씩 받아(`read`) 미리 정한 글자를 돌려준다."""

    def __init__(self, texts: list[str]) -> None:
        self.texts = list(texts)
        self.calls = 0

    def read(self, _img) -> str:
        self.calls += 1
        return self.texts.pop(0) if self.texts else ""


class _FakeTrocr:
    """Full의 인식기 자리 — **크롭을 한꺼번에** 받는다(`read_batch`).

    둘의 차이가 여기 있다: Lite는 PARSeq를 행마다 부르고, Full은 TrOCR에 배치로 넘긴다
    (GPU에서 2~5배). 그래서 «행마다 한 번»이라는 셈이 Full에는 적용되지 않는다.
    """

    def __init__(self, texts: list[str]) -> None:
        self.texts = list(texts)
        self.calls = 0

    def read_batch(self, crops) -> list[str]:
        self.calls += 1
        out = [self.texts.pop(0) if self.texts else "" for _ in crops]
        return out


def _engine(cls, texts: list[str]):
    """모델을 올리지 않은 엔진에 가짜 탐지기·인식기를 꽂는다.

    인식기 자리는 엔진마다 다르다 — Lite는 `_parseq.read`, Full은 `_trocr.read_batch`.
    엔진이 어느 칸을 쓰는지 시험이 알고 있어야 하므로 둘 다 꽂지 않고 **있는 칸만** 채운다.
    """
    eng = cls()
    eng._rtmdet = _FakeRtmdet()
    if hasattr(eng, "_trocr"):
        eng._trocr = _FakeTrocr(texts)
    else:
        eng._parseq = _FakeParseq(texts)
    return eng


def _recognizer_calls(eng) -> int:
    """인식기를 몇 번 불렀나 — Lite는 행 수만큼, Full은 배치라 한 번."""
    return (getattr(eng, "_trocr", None) or eng._parseq).calls


def _page(width: int = 400, height: int = 600) -> np.ndarray:
    """흰 쪽 하나. 크롭이 비지 않기만 하면 되므로 내용은 상관없다."""
    return np.full((height, width, 3), 255, dtype=np.uint8)


@pytest.mark.parametrize("cls", [NdlkotenOcrEngine, NdlkotenOcrFullEngine])
class TestDetectionsBecomeLines:
    """탐지 상자 → 행(글자·bbox·읽기 순서). 두 엔진이 같은 규약을 따른다."""

    def test_each_detection_becomes_a_line_with_text_and_bbox(self, cls):
        """입력: 탐지 둘. 출력: 행 둘 — 글자는 인식기가 준 것, bbox는 탐지 상자."""
        eng = _engine(cls, ["甲乙", "丙丁"])
        dets = [
            {"box": [300, 50, 340, 250], "confidence": 0.9},  # 오른쪽 행(세로쓰기 먼저)
            {"box": [200, 50, 240, 250], "confidence": 0.8},
        ]
        lines = eng._process_detections(_page(), dets)

        assert len(lines) == 2
        assert {tuple(ln["bbox"]) for ln in lines} == {(300, 50, 340, 250), (200, 50, 240, 250)}
        assert all(isinstance(ln["text"], str) for ln in lines)
        assert [ln["order"] for ln in lines] == sorted(ln["order"] for ln in lines)
        # Lite는 행마다 한 번(PARSeq), Full은 배치라 한 번(TrOCR) — 헛돌지 않는지만 본다
        assert 1 <= _recognizer_calls(eng) <= 2

    def test_a_detection_outside_the_page_is_skipped_not_crashed(self, cls):
        """쪽 밖 상자는 크롭이 비어 건너뛴다 — 예외로 터지면 한 쪽이 통째로 죽는다."""
        eng = _engine(cls, ["甲"])
        dets = [
            {"box": [300, 50, 340, 250], "confidence": 0.9},
            {"box": [900, 900, 950, 1100], "confidence": 0.9},  # 400×600 밖
        ]
        lines = eng._process_detections(_page(), dets)
        assert len(lines) == 1 and lines[0]["bbox"] == [300, 50, 340, 250]

    def test_no_detection_means_no_line(self, cls):
        eng = _engine(cls, [])
        assert eng._process_detections(_page(), []) == []


@pytest.mark.parametrize("cls", [NdlkotenOcrEngine, NdlkotenOcrFullEngine])
class TestLinesAreMatchedToBlocks:
    """행을 L3 블록에 배정하는 규약(D-086) — 블록 밖의 행은 **버린다**.

    가장 가까운 블록에 주지 않는 것이 핵심이다. 그래서 파이프라인이 블록 커버리지와 무관하게
    언제나 쪽 전체에 탐지를 돌릴 수 있다.
    """

    def test_a_line_inside_a_block_goes_to_that_block(self, cls):
        eng = _engine(cls, [])
        lines = [{"text": "甲", "bbox": [110, 110, 130, 200], "order": 0}]
        blocks = [{"block_id": "p01_b01", "bbox": [100, 100, 300, 400]}]
        got = eng._match_lines_to_blocks(lines, blocks)
        assert list(got) == ["p01_b01"] and got["p01_b01"][0]["text"] == "甲"

    def test_a_line_outside_every_block_is_dropped(self, cls):
        eng = _engine(cls, [])
        lines = [{"text": "乙", "bbox": [10, 10, 30, 90], "order": 0}]
        blocks = [{"block_id": "p01_b01", "bbox": [100, 100, 300, 400]}]
        got = eng._match_lines_to_blocks(lines, blocks)
        assert all(not rows for rows in got.values())
