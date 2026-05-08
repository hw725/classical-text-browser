"""표점 엔진 추상화.

본 서비스는 여러 엔진을 플러그인 방식으로 지원한다:

- MockEngine: 모델 없이 즉시 응답하는 더미 엔진. 본체 통합 테스트용.
- SikuRoBERTaEngine: yachagye/korean-classical-chinese-punctuation 기반 실제 추론.
  Phase 1b에서 구현한다 — 현재는 자리만 잡아둔 상태.

엔진 선택은 환경변수 PUNCT_ENGINE으로 한다 (mock | sikurroberta).
모델 가중치 경로는 PUNCT_MODEL_PATH로 지정한다.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import TypedDict


class Mark(TypedDict):
    """표점 마크 한 개. 본체(classical-text-browser)의 marks 스키마와 호환되어야 한다.

    - start, end: 원문 문자열에서 부호가 들어갈 위치(0-based, end-exclusive 슬라이스).
                  현재는 점 부호이므로 start == end - 1 == 부호 직전 글자 인덱스.
    - before:    부호 앞에 들어갈 문자(보통 공백). 현재는 ""만 사용.
    - after:     실제 표점 부호(예: "。", "，", "·").
    """

    start: int
    end: int
    before: str
    after: str


class Result(TypedDict):
    punctuated: str
    marks: list[Mark]


class PunctuationEngine(ABC):
    """모든 표점 엔진이 구현해야 하는 공통 인터페이스."""

    name: str

    @abstractmethod
    def ready(self) -> bool:
        """엔진이 추론 가능 상태인지 (모델 로드 완료 등)."""

    @abstractmethod
    def punctuate(self, text: str) -> Result:
        """원문을 받아 표점이 붙은 문자열과 마크 배열을 반환."""


# 7-class 라벨. yachagye 모델의 라벨 인덱스 0~6에 대응한다.
# 변경 금지 — 모델 출력 인덱스와 1:1 매칭되어야 한다.
LABELS: list[str] = [",", "。", "·", "?", "!", "《", "》"]


class MockEngine(PunctuationEngine):
    """더미 엔진 — 입력 문장을 그대로 두고 8자마다 가짜 句점(。)을 찍는다.

    실제 모델 없이 본체↔서비스 간 HTTP 계약을 검증하기 위한 용도.
    가중치 다운로드 전에도 본체 UI/어댑터를 끝까지 테스트할 수 있다.
    """

    name = "mock"

    def ready(self) -> bool:
        return True

    def punctuate(self, text: str) -> Result:
        chars = list(text)
        marks: list[Mark] = []
        # 마지막 글자 뒤에는 굳이 찍지 않는다.
        for i in range(7, len(chars) - 1, 8):
            marks.append({"start": i, "end": i + 1, "before": "", "after": "。"})
        # 마크를 적용한 결과 문자열도 함께 만들어 두면 디버깅이 쉽다.
        out: list[str] = []
        mark_by_pos: dict[int, str] = {m["end"]: m["after"] for m in marks}
        for idx, ch in enumerate(chars):
            out.append(ch)
            if (idx + 1) in mark_by_pos:
                out.append(mark_by_pos[idx + 1])
        return {"punctuated": "".join(out), "marks": marks}


class SikuRoBERTaEngine(PunctuationEngine):
    """SikuRoBERTa 기반 실제 표점 엔진.

    동작:
        - PUNCT_MODEL_PATH(환경변수)에 .ckpt 파일 경로를 지정한다.
          가중치는 yachagye/korean-classical-chinese-punctuation README의
          Google Drive 링크에서 받는다.
        - 첫 추론 호출 시 가중치를 로드한다 (lazy init). /health에서 ready()는
          파일 존재 여부만 확인하므로 빠르다.
        - PUNCT_DEVICE(환경변수, 기본 "auto") = cuda | cpu | auto.

    의존성:
        torch + transformers + numpy 가 필요하다.
        `uv sync --extra real` 로 설치된다.
    """

    name = "sikurroberta"

    def __init__(self) -> None:
        # 환경변수는 인스턴스 생성 시점에 한 번만 읽는다.
        self._model_path = os.getenv("PUNCT_MODEL_PATH", "").strip()
        self._device = os.getenv("PUNCT_DEVICE", "auto").strip() or "auto"
        self._predictor = None  # 첫 호출 시 lazy 로드

    def ready(self) -> bool:
        """가중치 파일 존재 여부만 빠르게 확인.

        실제 모델 로드는 첫 punctuate() 호출 때 수행. /health가 무거운 로드를
        트리거하지 않도록 의도적으로 가벼운 검사만 한다.
        """
        if not self._model_path:
            return False
        from pathlib import Path as _P
        return _P(self._model_path).is_file()

    def punctuate(self, text: str) -> Result:
        if self._predictor is None:
            if not self._model_path:
                raise RuntimeError(
                    "PUNCT_MODEL_PATH 환경변수가 설정되지 않았습니다. "
                    "yachagye 레포에서 .ckpt를 받아 경로를 지정하세요."
                )
            # 무거운 import는 첫 호출 시점까지 지연.
            # 내부에서 transformers·torch가 없으면 ImportError가 그대로 전파되어
            # api.py가 500을 반환한다 (PUNCT_ENGINE=sikurroberta 인데 의존성 누락 상황).
            from .sikurroberta import PunctuationPredictor
            self._predictor = PunctuationPredictor(self._model_path, device=self._device)
        punctuated, marks = self._predictor.punctuate(text)
        return {"punctuated": punctuated, "marks": marks}


def get_engine(name: str) -> PunctuationEngine:
    """이름으로 엔진 인스턴스를 생성. 알 수 없는 이름은 ValueError."""
    key = (name or "mock").strip().lower()
    if key == "mock":
        return MockEngine()
    if key == "sikurroberta":
        return SikuRoBERTaEngine()
    raise ValueError(f"알 수 없는 PUNCT_ENGINE: {name!r} (mock | sikurroberta 중 하나여야 함)")
