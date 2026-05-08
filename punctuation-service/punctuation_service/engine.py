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
    """SikuRoBERTa 기반 실제 표점 엔진 (자리표시).

    Phase 1b에서 구현한다. 구현 시 참고할 사항:

    1. 모델 구조: BERT backbone + Dropout + Linear classifier (7-way multi-label).
       yachagye 레포의 inference/구두점7_추론모델.py 참조.
    2. 토크나이저: AutoTokenizer.from_pretrained(<base_model>) — SikuBERT 또는 RoBERTa-classical-chinese.
    3. 체크포인트 형식: PyTorch Lightning .ckpt — torch.load() 후 state_dict 추출.
       Lightning 의존성 없이 로드하려면 키 이름을 직접 매핑해야 한다.
    4. 추론 흐름: tokenize(max_length=512) → BERT → linear → sigmoid → threshold(0.5)
       → token-level 예측을 char 단위로 정렬하여 마크 생성.
    5. 512 초과 텍스트는 sliding window로 분할 (overlap 64자 권장).

    구현이 끝나면 ready()를 모델 로드 성공 여부로 바꾸고 punctuate()를 채운다.
    """

    name = "sikurroberta"

    def __init__(self) -> None:
        self._model = None
        self._tokenizer = None
        self._model_path = os.getenv("PUNCT_MODEL_PATH", "")

    def ready(self) -> bool:
        # Phase 1b 미구현 상태에서는 항상 False.
        # /health 엔드포인트가 이를 보고 서비스 미준비 상태임을 본체에 알린다.
        return False

    def punctuate(self, text: str) -> Result:
        raise NotImplementedError(
            "SikuRoBERTa 어댑터는 아직 구현되지 않았습니다 (Phase 1b 예정). "
            "PUNCT_ENGINE=mock 으로 본체 통합을 먼저 테스트하세요."
        )


def get_engine(name: str) -> PunctuationEngine:
    """이름으로 엔진 인스턴스를 생성. 알 수 없는 이름은 ValueError."""
    key = (name or "mock").strip().lower()
    if key == "mock":
        return MockEngine()
    if key == "sikurroberta":
        return SikuRoBERTaEngine()
    raise ValueError(f"알 수 없는 PUNCT_ENGINE: {name!r} (mock | sikurroberta 중 하나여야 함)")
