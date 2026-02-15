"""OCR 엔진 추상 클래스 + 결과 데이터 모델.

모든 OCR 엔진은 BaseOcrEngine을 상속하고 recognize()를 구현한다.
파서(BaseFetcher + BaseMapper)와 동일한 플러그인 패턴.

결과 데이터 모델:
  OcrCharResult: 글자 하나의 인식 결과
  OcrLineResult: 줄 하나의 인식 결과 (글자들의 모음)
  OcrBlockResult: 블록 하나의 인식 결과 (줄들의 모음)

스키마 호환:
  to_dict() 출력은 ocr_page.schema.json과 호환되어야 한다.
  스키마에 additionalProperties: false이므로, 허용된 필드만 출력.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


# ─── 결과 데이터 모델 ──────────────────────────────────

@dataclass
class OcrCharResult:
    """글자 하나의 인식 결과.

    입력: OCR 엔진이 인식한 글자 하나
    출력: 글자, 위치(bbox), 신뢰도

    bbox 형식: [x_min, y_min, x_max, y_max]
    좌표는 크롭된 블록 이미지 기준 (픽셀).
    """

    char: str                          # 인식된 글자 (예: "王")
    bbox: Optional[list[float]] = None  # [x_min, y_min, x_max, y_max] — 없을 수도 있음
    confidence: float = 0.0            # 0.0~1.0

    def to_dict(self) -> dict:
        """ocr_page.schema.json의 OcrCharacter 호환 딕셔너리.

        스키마 허용 필드: char, bbox, confidence
        """
        result: dict = {"char": self.char}
        if self.bbox:
            result["bbox"] = [round(v, 2) for v in self.bbox]
        if self.confidence > 0:
            result["confidence"] = round(self.confidence, 4)
        return result


@dataclass
class OcrLineResult:
    """줄 하나의 인식 결과.

    세로쓰기: 한 줄 = 한 행 (위에서 아래)
    가로쓰기: 한 줄 = 한 행 (왼쪽에서 오른쪽)
    """

    text: str                           # 줄 전체 텍스트 (예: "王戎簡要")
    bbox: Optional[list[float]] = None  # 줄의 bbox
    characters: list[OcrCharResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        """ocr_page.schema.json의 OcrLine 호환 딕셔너리.

        스키마 허용 필드: text, bbox, characters
        """
        result: dict = {"text": self.text}
        if self.bbox:
            result["bbox"] = [round(v, 2) for v in self.bbox]
        if self.characters:
            result["characters"] = [c.to_dict() for c in self.characters]
        return result


@dataclass
class OcrBlockResult:
    """블록 하나의 OCR 인식 결과.

    입력: 크롭된 블록 이미지
    출력: 줄 목록 + 전체 텍스트 + 평균 신뢰도 + 메타데이터

    이것이 최종적으로 ocr_page.json의 ocr_results[i]가 된다.

    주의: to_dict()는 스키마 호환(lines, layout_block_id만).
          엔진/언어 등 메타데이터는 내부 속성으로만 보유한다.
    """

    lines: list[OcrLineResult] = field(default_factory=list)
    engine_id: str = ""                 # 어떤 엔진으로 인식했는지
    language: str = ""                  # 인식 언어 (예: "classical_chinese")
    writing_direction: str = ""         # "vertical_rtl", "horizontal_ltr" 등
    raw_engine_output: Optional[dict] = None  # 엔진의 원래 출력 (디버깅용)

    @property
    def full_text(self) -> str:
        """모든 줄의 텍스트를 합친 전체 텍스트."""
        return "\n".join(line.text for line in self.lines)

    @property
    def avg_confidence(self) -> float:
        """모든 글자의 평균 신뢰도."""
        all_chars = [c for line in self.lines for c in line.characters]
        if not all_chars:
            return 0.0
        return sum(c.confidence for c in all_chars) / len(all_chars)

    @property
    def char_count(self) -> int:
        """인식된 총 글자 수."""
        return sum(len(line.text) for line in self.lines)

    def to_dict(self) -> dict:
        """ocr_page.schema.json의 OcrResult 호환 딕셔너리.

        스키마 허용 필드: layout_block_id, lines
        layout_block_id는 파이프라인에서 추가한다 (엔진은 모름).
        """
        return {
            "lines": [line.to_dict() for line in self.lines],
        }


# ─── 에러 ──────────────────────────────────────────────

class OcrEngineError(Exception):
    """OCR 엔진 실행 중 에러."""
    pass


class OcrEngineUnavailableError(OcrEngineError):
    """OCR 엔진을 사용할 수 없음 (미설치, 초기화 실패 등)."""
    pass


# ─── 추상 클래스 ───────────────────────────────────────

class BaseOcrEngine(ABC):
    """OCR 엔진 추상 클래스.

    모든 OCR 엔진은 이 클래스를 상속하고:
    1. 클래스 속성(engine_id, display_name, requires_network) 정의
    2. is_available() 구현 — 엔진이 사용 가능한지 확인
    3. recognize() 구현 — 이미지를 받아 OcrBlockResult 반환

    is_available()이 False이면 recognize()를 호출하면 안 된다.
    """

    engine_id: str = ""           # 예: "paddleocr"
    display_name: str = ""        # 예: "PaddleOCR"
    requires_network: bool = False  # True이면 온라인 엔진

    @abstractmethod
    def is_available(self) -> bool:
        """엔진이 사용 가능한지 확인.

        PaddleOCR: paddleocr 패키지가 설치되어 있는지
        Google Vision: API 키가 설정되어 있는지
        Claude Vision: src/llm/ LlmRouter가 동작하는지
        """
        raise NotImplementedError

    @abstractmethod
    def recognize(
        self,
        image_bytes: bytes,
        writing_direction: str = "vertical_rtl",
        language: str = "classical_chinese",
        **kwargs,
    ) -> OcrBlockResult:
        """이미지에서 텍스트를 인식한다.

        입력:
          image_bytes: 크롭된 블록 이미지 (PNG 또는 JPEG 바이트)
          writing_direction: "vertical_rtl" (고전 한문 기본), "horizontal_ltr" 등
          language: "classical_chinese", "korean", "japanese" 등
          **kwargs: 엔진별 추가 옵션

        출력:
          OcrBlockResult — lines + characters + confidence

        에러:
          OcrEngineError — 인식 실패
          OcrEngineUnavailableError — 엔진 사용 불가
        """
        raise NotImplementedError

    def get_info(self) -> dict:
        """엔진 정보를 딕셔너리로 반환. API 응답용."""
        return {
            "engine_id": self.engine_id,
            "display_name": self.display_name,
            "requires_network": self.requires_network,
            "available": self.is_available(),
        }
