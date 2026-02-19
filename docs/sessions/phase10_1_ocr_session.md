# Phase 10-1: OCR 엔진 연동 파이프라인

> Claude Code 세션 지시문
> 이 문서를 읽고 작업 순서대로 구현하라.

---

## 사전 준비

1. CLAUDE.md를 먼저 읽어라.
2. docs/DECISIONS.md를 읽어라. 특히 D-002(LayoutBlock), D-003(Block 세 종류), D-004(작업 순서).
3. docs/phase10_12_design.md의 Phase 10-1 섹션을 읽어라.
4. schemas/source_repo/ocr_page.schema.json을 읽어라.
5. 이 문서 전체를 읽은 후 작업을 시작하라.
6. 기존 코드 구조를 먼저 파악하라: `src/` 디렉토리 전체, `src/core/`, `src/api/`, `static/js/`.
7. **Phase 10-2에서 만든 `src/llm/` 구조를 참고하라** — 같은 플러그인 패턴을 OCR에 적용한다.

---

## 설계 요약 — 반드시 이해한 후 구현

### 핵심 원칙

- **모든 OCR 호출은 OCR 파이프라인(`src/core/ocr_pipeline.py`)을 통해야 한다.** 엔진을 직접 호출하지 않는다.
- **플러그인 아키텍처**: 파서(BaseFetcher + BaseMapper)와 동일한 패턴. 새 OCR 엔진 추가 시 파일 하나만 추가.
- **오프라인 퍼스트**: 기본 엔진은 PaddleOCR (로컬 실행, 무료). 온라인 엔진은 선택적.
- **L3 → L2 흐름**: LayoutBlock(L3)의 bbox로 이미지 크롭 → OCR → OcrResult(L2)로 저장.
- **블록 단위 처리**: 페이지 전체가 아니라 블록별로 OCR. 재실행 시 특정 블록만 가능.

### 파이프라인 흐름

```
1. 사용자가 레이아웃 모드에서 "OCR 실행" 클릭
2. 앱이 L3 layout_page.json에서 블록 목록 읽기
3. 각 블록에 대해 (reading_order 순):
   a. L1 이미지에서 bbox 영역 크롭
   b. 블록의 ocr_config에서 엔진/언어/방향 읽기 (없으면 기본값)
   c. 해당 엔진의 recognize() 호출
   d. 결과를 OcrResult 형태로 변환
4. ocr_page.schema.json으로 검증
5. L2_ocr/page_NNN.json으로 저장
6. git commit: "L2: page 001 OCR — paddleocr, 3 blocks"
```

### 디렉토리 구조 (최종)

```
src/ocr/
  __init__.py               ← from .pipeline import OcrPipeline 노출
  base.py                   ← BaseOcrEngine, OcrBlockResult, OcrLineResult, OcrCharResult
  paddleocr_engine.py       ← PaddleOCR 래퍼 (오프라인, 1순위)
  google_vision.py          ← Google Cloud Vision (온라인, 향후)
  claude_vision.py          ← Claude API multimodal (온라인, 향후 — src/llm/ 활용)
  registry.py               ← 엔진 등록/조회
  image_utils.py            ← 이미지 크롭, 회전, 전처리
  pipeline.py               ← OCR 파이프라인 (페이지/블록 단위 실행)
```

### 데이터 흐름 다이어그램

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   L1 이미지       │     │   L3 레이아웃     │     │   L2 OCR 결과     │
│   (PDF/PNG)      │     │   layout_page.json│     │   page_NNN.json  │
│                  │     │                  │     │                  │
│  전체 페이지 이미지│     │  블록 bbox 좌표   │     │  블록별 인식 텍스트 │
└────────┬─────────┘     └────────┬─────────┘     └────────▲─────────┘
         │                        │                        │
         │   ┌────────────────────┘                        │
         ▼   ▼                                             │
    ┌──────────────┐     ┌──────────────┐     ┌────────────┴──┐
    │ image_utils  │────▶│  OCR Engine  │────▶│  OcrPipeline  │
    │ crop_block() │     │ recognize()  │     │ 검증 + 저장    │
    └──────────────┘     └──────────────┘     └───────────────┘
```

---

## 작업 순서

아래 작업을 번호 순서대로 구현하라. 각 작업이 끝나면 테스트를 실행하고 통과 확인 후 다음으로 넘어가라.

---

### 작업 1: 의존성 설치 + 디렉토리 생성

```bash
# OCR 관련 의존성
uv add Pillow
# PaddleOCR은 작업 3에서 설치 (paddlepaddle이 무겁기 때문에 분리)

# 디렉토리 생성
mkdir -p src/ocr
mkdir -p tests
```

`src/ocr/__init__.py` 작성:

```python
"""OCR 엔진 연동 모듈.

플러그인 아키텍처로 다양한 OCR 엔진을 지원한다.
기본 엔진: PaddleOCR (오프라인).

사용법:
    from src.ocr import OcrPipeline, OcrEngineRegistry

    registry = OcrEngineRegistry()
    pipeline = OcrPipeline(registry)
    result = pipeline.run_page(doc_id, part_id, page_number)
"""

from .pipeline import OcrPipeline
from .registry import OcrEngineRegistry
from .base import BaseOcrEngine, OcrBlockResult

__all__ = ["OcrPipeline", "OcrEngineRegistry", "BaseOcrEngine", "OcrBlockResult"]
```

커밋: `build(ocr): 디렉토리 구조 + __init__.py`

---

### 작업 2: BaseOcrEngine + 결과 데이터 모델

`src/ocr/base.py` — 모든 OCR 엔진의 추상 클래스와 결과 데이터 모델.

```python
"""OCR 엔진 추상 클래스 + 결과 데이터 모델.

모든 OCR 엔진은 BaseOcrEngine을 상속하고 recognize()를 구현한다.
파서(BaseFetcher + BaseMapper)와 동일한 플러그인 패턴.

결과 데이터 모델:
  OcrCharResult: 글자 하나의 인식 결과
  OcrLineResult: 줄 하나의 인식 결과 (글자들의 모음)
  OcrBlockResult: 블록 하나의 인식 결과 (줄들의 모음)
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
        """스키마 호환 딕셔너리로 변환."""
        result = {"char": self.char, "confidence": round(self.confidence, 4)}
        if self.bbox:
            result["bbox"] = [round(v, 2) for v in self.bbox]
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
        result = {"text": self.text}
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
        """ocr_page.schema.json의 ocr_results[i] 형식으로 변환.

        주의: layout_block_id는 파이프라인에서 추가한다 (엔진은 모름).
        """
        return {
            "text": self.full_text,
            "lines": [l.to_dict() for l in self.lines],
            "confidence": round(self.avg_confidence, 4),
            "engine": self.engine_id,
            "language": self.language,
            "writing_direction": self.writing_direction,
            "char_count": self.char_count,
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
```

테스트 파일 `tests/test_ocr_base.py`:

```python
"""BaseOcrEngine + 결과 데이터 모델 테스트."""

from src.ocr.base import (
    OcrCharResult, OcrLineResult, OcrBlockResult,
    BaseOcrEngine, OcrEngineError, OcrEngineUnavailableError,
)


class TestOcrCharResult:
    def test_to_dict_basic(self):
        c = OcrCharResult(char="王", confidence=0.95)
        d = c.to_dict()
        assert d["char"] == "王"
        assert d["confidence"] == 0.95
        assert "bbox" not in d

    def test_to_dict_with_bbox(self):
        c = OcrCharResult(char="王", bbox=[10.0, 20.0, 30.0, 50.0], confidence=0.987654)
        d = c.to_dict()
        assert d["bbox"] == [10.0, 20.0, 30.0, 50.0]
        assert d["confidence"] == 0.9877  # rounded to 4 decimals


class TestOcrLineResult:
    def test_to_dict(self):
        line = OcrLineResult(
            text="王戎",
            bbox=[0, 0, 50, 100],
            characters=[
                OcrCharResult(char="王", confidence=0.95),
                OcrCharResult(char="戎", confidence=0.88),
            ],
        )
        d = line.to_dict()
        assert d["text"] == "王戎"
        assert len(d["characters"]) == 2


class TestOcrBlockResult:
    def test_full_text(self):
        block = OcrBlockResult(
            lines=[
                OcrLineResult(text="王戎簡要"),
                OcrLineResult(text="裴楷清通"),
            ],
            engine_id="paddleocr",
        )
        assert block.full_text == "王戎簡要\n裴楷清通"

    def test_avg_confidence(self):
        block = OcrBlockResult(
            lines=[
                OcrLineResult(
                    text="王戎",
                    characters=[
                        OcrCharResult(char="王", confidence=0.9),
                        OcrCharResult(char="戎", confidence=0.7),
                    ],
                ),
            ],
        )
        assert abs(block.avg_confidence - 0.8) < 0.001

    def test_avg_confidence_no_chars(self):
        block = OcrBlockResult(lines=[OcrLineResult(text="test")])
        assert block.avg_confidence == 0.0

    def test_to_dict(self):
        block = OcrBlockResult(
            lines=[OcrLineResult(text="王戎簡要")],
            engine_id="paddleocr",
            language="classical_chinese",
            writing_direction="vertical_rtl",
        )
        d = block.to_dict()
        assert d["text"] == "王戎簡要"
        assert d["engine"] == "paddleocr"
        assert d["language"] == "classical_chinese"


class DummyEngine(BaseOcrEngine):
    """테스트용 더미 엔진."""
    engine_id = "dummy"
    display_name = "Dummy Engine"
    requires_network = False

    def is_available(self) -> bool:
        return True

    def recognize(self, image_bytes, writing_direction="vertical_rtl",
                  language="classical_chinese", **kwargs) -> OcrBlockResult:
        return OcrBlockResult(
            lines=[OcrLineResult(text="더미결과")],
            engine_id=self.engine_id,
            language=language,
            writing_direction=writing_direction,
        )


class TestBaseOcrEngine:
    def test_dummy_engine(self):
        engine = DummyEngine()
        assert engine.is_available()
        result = engine.recognize(b"fake_image")
        assert result.full_text == "더미결과"
        assert result.engine_id == "dummy"

    def test_get_info(self):
        engine = DummyEngine()
        info = engine.get_info()
        assert info["engine_id"] == "dummy"
        assert info["available"] is True
```

커밋: `feat(ocr): BaseOcrEngine 추상 클래스 + 결과 데이터 모델`

---

### 작업 3: 이미지 유틸리티

`src/ocr/image_utils.py` — 이미지 크롭, 전처리, PDF→이미지 변환.

```python
"""이미지 유틸리티: 크롭, 전처리, PDF→이미지 변환.

입력: 전체 페이지 이미지 + LayoutBlock의 bbox
출력: 크롭된 블록 이미지 (bytes)

bbox 형식:
  phase10_12_design.md에서 정의된 비율 좌표 사용.
  [x, y, width, height] — 0.0~1.0 비율.
  예: [0.1, 0.05, 0.35, 0.9] → 왼쪽 10%, 위 5%에서 시작, 폭 35%, 높이 90%.
"""

from __future__ import annotations
import io
from typing import Optional
from PIL import Image

from .base import OcrEngineError


def load_page_image(image_path: str) -> Image.Image:
    """페이지 이미지를 로드한다.

    입력: 이미지 파일 경로 (PNG, JPEG, TIFF 등)
    출력: PIL Image 객체

    에러: OcrEngineError — 파일을 열 수 없을 때
    """
    try:
        img = Image.open(image_path)
        img.load()  # lazy loading 방지
        return img
    except Exception as e:
        raise OcrEngineError(f"이미지를 열 수 없습니다: {image_path} — {e}")


def crop_block(
    page_image: Image.Image,
    bbox: list[float],
    padding_px: int = 2,
) -> bytes:
    """페이지 이미지에서 블록 영역을 크롭한다.

    입력:
      page_image: 전체 페이지 PIL Image
      bbox: [x, y, width, height] — 비율 좌표 (0.0~1.0)
      padding_px: 크롭 영역에 추가할 여백 (픽셀). 글자가 잘리는 것 방지.

    출력: 크롭된 이미지의 PNG 바이트

    bbox 좌표 변환:
      비율 → 픽셀:
      x_px = x * image_width
      y_px = y * image_height
      w_px = width * image_width
      h_px = height * image_height
    """
    img_w, img_h = page_image.size

    # 비율 → 픽셀 변환
    x, y, w, h = bbox
    x_min = int(x * img_w) - padding_px
    y_min = int(y * img_h) - padding_px
    x_max = int((x + w) * img_w) + padding_px
    y_max = int((y + h) * img_h) + padding_px

    # 범위 제한
    x_min = max(0, x_min)
    y_min = max(0, y_min)
    x_max = min(img_w, x_max)
    y_max = min(img_h, y_max)

    if x_max <= x_min or y_max <= y_min:
        raise OcrEngineError(
            f"유효하지 않은 크롭 영역: bbox={bbox}, image_size=({img_w}, {img_h})"
        )

    cropped = page_image.crop((x_min, y_min, x_max, y_max))

    # PNG 바이트로 변환
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()


def preprocess_for_ocr(
    image_bytes: bytes,
    writing_direction: str = "vertical_rtl",
    grayscale: bool = True,
    binarize: bool = False,
    binarize_threshold: int = 128,
) -> bytes:
    """OCR 정확도를 높이기 위한 이미지 전처리.

    입력: 크롭된 이미지 바이트
    출력: 전처리된 이미지 바이트

    옵션:
      grayscale: 그레이스케일 변환 (대부분의 고전 텍스트는 흑백)
      binarize: 이진화 (흑/백만 남김)
      binarize_threshold: 이진화 임계값 (0~255)

    주의:
      PaddleOCR은 자체 전처리가 있어서 기본적으로는 grayscale만.
      다른 엔진에서 필요하면 binarize도 사용.
    """
    img = Image.open(io.BytesIO(image_bytes))

    if grayscale and img.mode != "L":
        img = img.convert("L")

    if binarize:
        img = img.point(lambda x: 255 if x > binarize_threshold else 0, mode="1")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_page_image_path(
    library_root: str,
    doc_id: str,
    part_id: str,
    page_number: int,
) -> Optional[str]:
    """L1 이미지의 파일 경로를 찾는다.

    입력:
      library_root: 서고 루트 경로
      doc_id: 문서 ID
      part_id: 파트 ID
      page_number: 페이지 번호 (1-indexed)

    출력: 이미지 파일 경로 (없으면 None)

    탐색 순서:
      1. {library_root}/sources/{doc_id}/{part_id}/L1_images/page_{NNN}.png
      2. {library_root}/sources/{doc_id}/{part_id}/L1_images/page_{NNN}.jpg
      3. {library_root}/sources/{doc_id}/{part_id}/L1_images/page_{NNN}.tiff
      4. 원본 PDF에서 추출 (향후 구현)

    주의: 현재는 이미지 파일이 이미 존재한다고 가정.
         PDF → 이미지 변환은 별도 유틸리티로 구현할 수 있다.
    """
    import os

    page_str = f"page_{page_number:03d}"
    base_dir = os.path.join(library_root, "sources", doc_id, part_id, "L1_images")

    for ext in ("png", "jpg", "jpeg", "tiff", "tif"):
        path = os.path.join(base_dir, f"{page_str}.{ext}")
        if os.path.exists(path):
            return path

    return None
```

테스트 파일 `tests/test_ocr_image_utils.py`:

```python
"""이미지 유틸리티 테스트."""

import io
from PIL import Image

from src.ocr.image_utils import crop_block, preprocess_for_ocr, load_page_image
from src.ocr.base import OcrEngineError
import pytest


def _make_test_image(width: int = 1000, height: int = 1500, color: str = "white") -> Image.Image:
    """테스트용 이미지 생성."""
    return Image.new("RGB", (width, height), color)


class TestCropBlock:
    def test_basic_crop(self):
        img = _make_test_image(1000, 1500)
        # bbox: 왼쪽 10%, 위 5%, 폭 30%, 높이 40%
        result = crop_block(img, [0.1, 0.05, 0.3, 0.4], padding_px=0)
        cropped = Image.open(io.BytesIO(result))
        assert cropped.size == (300, 600)  # 0.3*1000, 0.4*1500

    def test_crop_with_padding(self):
        img = _make_test_image(1000, 1500)
        result = crop_block(img, [0.1, 0.05, 0.3, 0.4], padding_px=5)
        cropped = Image.open(io.BytesIO(result))
        # padding 5px씩 양쪽에 추가 → 310 x 610
        assert cropped.size == (310, 610)

    def test_crop_clamped_to_bounds(self):
        img = _make_test_image(100, 100)
        # bbox가 이미지 밖으로 나가도 에러 없이 클램핑
        result = crop_block(img, [0.0, 0.0, 1.0, 1.0], padding_px=10)
        cropped = Image.open(io.BytesIO(result))
        assert cropped.size == (100, 100)  # 원본 크기를 넘지 않음

    def test_invalid_crop(self):
        img = _make_test_image(100, 100)
        with pytest.raises(OcrEngineError):
            crop_block(img, [0.9, 0.9, 0.0, 0.0], padding_px=0)


class TestPreprocess:
    def test_grayscale(self):
        img = _make_test_image()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = preprocess_for_ocr(buf.getvalue(), grayscale=True, binarize=False)
        processed = Image.open(io.BytesIO(result))
        assert processed.mode == "L"

    def test_no_grayscale(self):
        img = _make_test_image()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = preprocess_for_ocr(buf.getvalue(), grayscale=False, binarize=False)
        processed = Image.open(io.BytesIO(result))
        assert processed.mode == "RGB"
```

커밋: `feat(ocr): 이미지 유틸리티 — crop_block, preprocess, page_image_path`

---

### 작업 4: OCR 엔진 레지스트리

`src/ocr/registry.py` — 엔진 등록, 조회, 기본 엔진 선택.

```python
"""OCR 엔진 레지스트리.

사용 가능한 OCR 엔진을 등록하고 조회한다.
파서의 ParserRegistry와 동일한 패턴.

엔진은 코드에 하드코딩하지 않고 register()로 등록한다.
앱 초기화 시 사용 가능한 엔진을 자동 등록.
"""

from __future__ import annotations
import logging
from typing import Optional

from .base import BaseOcrEngine, OcrEngineUnavailableError

logger = logging.getLogger(__name__)


class OcrEngineRegistry:
    """OCR 엔진 레지스트리.

    사용법:
        registry = OcrEngineRegistry()
        registry.auto_register()  # 사용 가능한 엔진 자동 등록
        engine = registry.get_engine("paddleocr")
    """

    def __init__(self):
        self._engines: dict[str, BaseOcrEngine] = {}
        self._default_engine_id: Optional[str] = None

    def register(self, engine: BaseOcrEngine) -> None:
        """엔진을 등록한다.

        이미 같은 engine_id가 등록되어 있으면 덮어쓴다.
        """
        self._engines[engine.engine_id] = engine
        logger.info(f"OCR 엔진 등록: {engine.engine_id} ({engine.display_name})")

        # 첫 번째로 사용 가능한 엔진을 기본값으로
        if self._default_engine_id is None and engine.is_available():
            self._default_engine_id = engine.engine_id

    def get_engine(self, engine_id: Optional[str] = None) -> BaseOcrEngine:
        """엔진을 조회한다.

        입력: engine_id (None이면 기본 엔진)
        출력: BaseOcrEngine 인스턴스

        에러: OcrEngineUnavailableError — 엔진이 없거나 사용 불가
        """
        if engine_id is None:
            engine_id = self._default_engine_id

        if engine_id is None:
            raise OcrEngineUnavailableError("등록된 OCR 엔진이 없습니다.")

        engine = self._engines.get(engine_id)
        if engine is None:
            available = list(self._engines.keys())
            raise OcrEngineUnavailableError(
                f"엔진 '{engine_id}'를 찾을 수 없습니다. 사용 가능: {available}"
            )

        if not engine.is_available():
            raise OcrEngineUnavailableError(
                f"엔진 '{engine_id}'이(가) 사용할 수 없는 상태입니다."
            )

        return engine

    def list_engines(self) -> list[dict]:
        """등록된 모든 엔진의 정보를 반환한다. API 응답용."""
        return [engine.get_info() for engine in self._engines.values()]

    @property
    def default_engine_id(self) -> Optional[str]:
        return self._default_engine_id

    @default_engine_id.setter
    def default_engine_id(self, engine_id: str) -> None:
        if engine_id not in self._engines:
            raise ValueError(f"등록되지 않은 엔진: {engine_id}")
        self._default_engine_id = engine_id

    def auto_register(self) -> None:
        """사용 가능한 엔진을 자동으로 등록한다.

        각 엔진 모듈을 import 시도하고, 성공하면 등록.
        import 실패 = 해당 엔진의 의존성이 설치되지 않음 → 건너뜀.
        """
        # 1순위: PaddleOCR (오프라인)
        try:
            from .paddleocr_engine import PaddleOcrEngine
            engine = PaddleOcrEngine()
            self.register(engine)
        except ImportError:
            logger.info("PaddleOCR 미설치 — 건너뜀")
        except Exception as e:
            logger.warning(f"PaddleOCR 초기화 실패: {e}")

        # 향후: Google Vision, Claude Vision 등 추가
        # try:
        #     from .google_vision import GoogleVisionEngine
        #     ...
        # except ImportError:
        #     ...

        if not self._engines:
            logger.warning("사용 가능한 OCR 엔진이 없습니다!")
```

테스트 파일 `tests/test_ocr_registry.py`:

```python
"""OCR 엔진 레지스트리 테스트."""

import pytest
from src.ocr.base import BaseOcrEngine, OcrBlockResult, OcrLineResult, OcrEngineUnavailableError
from src.ocr.registry import OcrEngineRegistry


class FakeEngine(BaseOcrEngine):
    engine_id = "fake"
    display_name = "Fake Engine"
    requires_network = False

    def __init__(self, available: bool = True):
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def recognize(self, image_bytes, **kwargs) -> OcrBlockResult:
        return OcrBlockResult(lines=[OcrLineResult(text="fake")])


class TestOcrEngineRegistry:
    def test_register_and_get(self):
        reg = OcrEngineRegistry()
        reg.register(FakeEngine())
        engine = reg.get_engine("fake")
        assert engine.engine_id == "fake"

    def test_default_engine(self):
        reg = OcrEngineRegistry()
        reg.register(FakeEngine())
        engine = reg.get_engine()  # None → 기본
        assert engine.engine_id == "fake"

    def test_unavailable_engine(self):
        reg = OcrEngineRegistry()
        reg.register(FakeEngine(available=False))
        with pytest.raises(OcrEngineUnavailableError):
            reg.get_engine("fake")

    def test_no_engines(self):
        reg = OcrEngineRegistry()
        with pytest.raises(OcrEngineUnavailableError):
            reg.get_engine()

    def test_list_engines(self):
        reg = OcrEngineRegistry()
        reg.register(FakeEngine())
        engines = reg.list_engines()
        assert len(engines) == 1
        assert engines[0]["engine_id"] == "fake"
        assert engines[0]["available"] is True
```

커밋: `feat(ocr): 엔진 레지스트리 — 자동 등록 + 기본 엔진 선택`

---

### 작업 5: PaddleOCR 엔진 구현

먼저 PaddleOCR 의존성 설치:

```bash
# CPU 버전 (GPU 없는 환경)
uv add paddlepaddle paddleocr

# ⚠️ paddlepaddle이 무거울 수 있다 (~500MB).
# 설치 실패 시: pip install paddlepaddle==2.6.2 -i https://pypi.tuna.tsinghua.edu.cn/simple
# 또는: uv add paddlepaddle-gpu (GPU 있는 경우)
```

`src/ocr/paddleocr_engine.py`:

```python
"""PaddleOCR 엔진 래퍼.

오프라인 퍼스트 원칙에 따른 기본(1순위) OCR 엔진.
PP-OCRv4 모델 사용 — 중국어 고전 텍스트에 적합.

특징:
  - 로컬 실행, 무료
  - 세로쓰기 지원 (PP-OCR 자체 방향 감지)
  - 줄 단위 + 글자 단위 bbox 제공 (글자 단위는 rec_char_info 옵션)
  - 신뢰도(confidence) 제공
"""

from __future__ import annotations
import logging
import io
from typing import Optional

from .base import (
    BaseOcrEngine, OcrBlockResult, OcrLineResult, OcrCharResult,
    OcrEngineError, OcrEngineUnavailableError,
)

logger = logging.getLogger(__name__)


class PaddleOcrEngine(BaseOcrEngine):
    """PaddleOCR 엔진.

    초기화 시 PaddleOCR 모델을 로드한다 (첫 호출 시 모델 다운로드 발생).

    사용법:
        engine = PaddleOcrEngine()
        if engine.is_available():
            result = engine.recognize(image_bytes, writing_direction="vertical_rtl")
    """

    engine_id = "paddleocr"
    display_name = "PaddleOCR (오프라인)"
    requires_network = False

    def __init__(self, lang: str = "ch", use_gpu: bool = False):
        """PaddleOCR 엔진 초기화.

        입력:
          lang: PaddleOCR 언어 코드 ("ch" = 중국어/한자)
          use_gpu: GPU 사용 여부

        주의: 초기화가 느릴 수 있다 (모델 로드).
             첫 호출 시 모델 자동 다운로드 (~100MB).
        """
        self._lang = lang
        self._use_gpu = use_gpu
        self._ocr = None  # lazy init
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """PaddleOCR 패키지가 설치되어 있는지 확인."""
        if self._available is not None:
            return self._available

        try:
            import paddleocr  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False
            logger.info("PaddleOCR 미설치 — uv add paddlepaddle paddleocr")

        return self._available

    def _get_ocr(self):
        """PaddleOCR 인스턴스를 lazy 초기화."""
        if self._ocr is None:
            if not self.is_available():
                raise OcrEngineUnavailableError("PaddleOCR이 설치되지 않았습니다.")

            from paddleocr import PaddleOCR as _PaddleOCR

            self._ocr = _PaddleOCR(
                lang=self._lang,
                use_angle_cls=True,   # 방향 감지 (세로쓰기 지원)
                use_gpu=self._use_gpu,
                show_log=False,       # 로그 최소화
            )
            logger.info("PaddleOCR 모델 로드 완료")

        return self._ocr

    def recognize(
        self,
        image_bytes: bytes,
        writing_direction: str = "vertical_rtl",
        language: str = "classical_chinese",
        **kwargs,
    ) -> OcrBlockResult:
        """PaddleOCR로 텍스트를 인식한다.

        입력: 크롭된 블록 이미지 (PNG/JPEG 바이트)
        출력: OcrBlockResult

        PaddleOCR 출력 형식:
          result = ocr.ocr(image)
          result[0] = [
            [bbox_points, (text, confidence)],
            ...
          ]
          bbox_points = [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]  (4꼭짓점)

        변환:
          4꼭짓점 → [x_min, y_min, x_max, y_max]
          (text, confidence) → OcrLineResult
        """
        import numpy as np
        from PIL import Image

        ocr = self._get_ocr()

        # bytes → numpy array (PaddleOCR 입력 형식)
        img = Image.open(io.BytesIO(image_bytes))
        img_array = np.array(img)

        try:
            raw_result = ocr.ocr(img_array, cls=True)
        except Exception as e:
            raise OcrEngineError(f"PaddleOCR 인식 실패: {e}")

        # PaddleOCR 결과 파싱
        lines = []

        if raw_result and raw_result[0]:
            for item in raw_result[0]:
                bbox_points = item[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                text = item[1][0]
                confidence = float(item[1][1])

                # 4꼭짓점 → [x_min, y_min, x_max, y_max]
                xs = [p[0] for p in bbox_points]
                ys = [p[1] for p in bbox_points]
                line_bbox = [min(xs), min(ys), max(xs), max(ys)]

                # 글자 단위 결과 생성 (PaddleOCR 기본은 줄 단위)
                # 글자 단위 bbox가 없으므로 줄 bbox를 균등 분할
                characters = self._split_line_to_chars(
                    text, line_bbox, confidence, writing_direction
                )

                lines.append(OcrLineResult(
                    text=text,
                    bbox=line_bbox,
                    characters=characters,
                ))

        # 세로쓰기일 때: 줄을 오른쪽→왼쪽 순서로 정렬
        if writing_direction == "vertical_rtl" and lines:
            lines.sort(key=lambda l: -(l.bbox[0] if l.bbox else 0))

        return OcrBlockResult(
            lines=lines,
            engine_id=self.engine_id,
            language=language,
            writing_direction=writing_direction,
            raw_engine_output={"paddle_result": str(raw_result)[:500]},  # 디버깅용, 잘라서 저장
        )

    def _split_line_to_chars(
        self,
        text: str,
        line_bbox: list[float],
        line_confidence: float,
        writing_direction: str,
    ) -> list[OcrCharResult]:
        """줄의 텍스트를 글자별로 분할하고 bbox를 추정한다.

        PaddleOCR은 기본적으로 줄 단위 결과만 제공.
        글자 단위 bbox는 줄 bbox를 균등 분할하여 추정.

        세로쓰기: y축 방향으로 균등 분할
        가로쓰기: x축 방향으로 균등 분할
        """
        if not text:
            return []

        x_min, y_min, x_max, y_max = line_bbox
        n = len(text)
        chars = []

        for i, ch in enumerate(text):
            if writing_direction == "vertical_rtl":
                # 세로쓰기: y축 분할
                ch_y_min = y_min + (y_max - y_min) * i / n
                ch_y_max = y_min + (y_max - y_min) * (i + 1) / n
                char_bbox = [x_min, ch_y_min, x_max, ch_y_max]
            else:
                # 가로쓰기: x축 분할
                ch_x_min = x_min + (x_max - x_min) * i / n
                ch_x_max = x_min + (x_max - x_min) * (i + 1) / n
                char_bbox = [ch_x_min, y_min, ch_x_max, y_max]

            chars.append(OcrCharResult(
                char=ch,
                bbox=char_bbox,
                confidence=line_confidence,  # 줄 confidence를 글자에도 동일 적용
            ))

        return chars
```

테스트 `tests/test_ocr_paddle.py` (PaddleOCR 미설치 환경에서도 동작):

```python
"""PaddleOCR 엔진 테스트.

PaddleOCR이 설치되지 않은 환경에서도 기본 테스트가 통과해야 한다.
실제 인식 테스트는 PaddleOCR 설치 후 수동으로 실행.
"""

import pytest
from src.ocr.paddleocr_engine import PaddleOcrEngine


class TestPaddleOcrEngine:
    def test_engine_info(self):
        engine = PaddleOcrEngine()
        assert engine.engine_id == "paddleocr"
        assert engine.requires_network is False

    def test_is_available_check(self):
        engine = PaddleOcrEngine()
        # 설치 여부에 따라 True/False — 에러 없이 반환만 확인
        result = engine.is_available()
        assert isinstance(result, bool)

    def test_split_line_to_chars_vertical(self):
        engine = PaddleOcrEngine()
        chars = engine._split_line_to_chars(
            text="王戎",
            line_bbox=[10.0, 0.0, 30.0, 100.0],
            line_confidence=0.95,
            writing_direction="vertical_rtl",
        )
        assert len(chars) == 2
        assert chars[0].char == "王"
        assert chars[1].char == "戎"
        # 세로쓰기: y축 분할
        assert chars[0].bbox[1] == 0.0   # 王은 위쪽
        assert chars[1].bbox[1] == 50.0  # 戎은 아래쪽

    def test_split_line_to_chars_horizontal(self):
        engine = PaddleOcrEngine()
        chars = engine._split_line_to_chars(
            text="AB",
            line_bbox=[0.0, 10.0, 100.0, 30.0],
            line_confidence=0.9,
            writing_direction="horizontal_ltr",
        )
        assert len(chars) == 2
        assert chars[0].char == "A"
        # 가로쓰기: x축 분할
        assert chars[0].bbox[0] == 0.0
        assert chars[1].bbox[0] == 50.0

    @pytest.mark.skipif(
        not PaddleOcrEngine().is_available(),
        reason="PaddleOCR 미설치"
    )
    def test_recognize_real(self):
        """실제 PaddleOCR 인식 테스트 (PaddleOCR 설치 시에만 실행)."""
        from PIL import Image, ImageDraw, ImageFont
        import io

        # 간단한 한자 이미지 생성
        img = Image.new("RGB", (200, 200), "white")
        draw = ImageDraw.Draw(img)
        # 시스템 기본 폰트로 텍스트 그리기 (한자 폰트가 없을 수 있음)
        draw.text((50, 50), "王", fill="black")

        buf = io.BytesIO()
        img.save(buf, format="PNG")

        engine = PaddleOcrEngine()
        result = engine.recognize(buf.getvalue())
        # 결과가 있으면 OK (실제 인식률은 폰트/해상도에 따라 다름)
        assert result.engine_id == "paddleocr"
```

커밋: `feat(ocr): PaddleOCR 엔진 구현 — 세로쓰기 + 글자 분할`

---

### 작업 6: OCR 파이프라인 코어 로직

`src/ocr/pipeline.py` — 페이지/블록 단위 OCR 실행, 결과 검증·저장.

```python
"""OCR 파이프라인.

L3 레이아웃 → 이미지 크롭 → OCR 엔진 → L2 결과 저장.
모든 OCR 실행은 이 파이프라인을 통해야 한다.

사용법:
    from src.ocr import OcrPipeline, OcrEngineRegistry

    registry = OcrEngineRegistry()
    registry.auto_register()

    pipeline = OcrPipeline(registry, library_root="/path/to/library")
    result = pipeline.run_page(doc_id="doc001", part_id="vol1", page_number=1)
"""

from __future__ import annotations
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from .base import OcrBlockResult, OcrEngineError
from .registry import OcrEngineRegistry
from .image_utils import load_page_image, crop_block, preprocess_for_ocr, get_page_image_path

logger = logging.getLogger(__name__)


@dataclass
class OcrPageResult:
    """한 페이지의 OCR 결과.

    파이프라인의 최종 출력.
    ocr_page.schema.json 형식으로 저장된다.
    """
    doc_id: str
    part_id: str
    page_number: int
    ocr_results: list[dict] = field(default_factory=list)
    engine_id: str = ""
    total_blocks: int = 0
    processed_blocks: int = 0
    skipped_blocks: int = 0
    elapsed_sec: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """ocr_page.schema.json 호환 딕셔너리."""
        return {
            "page_number": self.page_number,
            "ocr_results": self.ocr_results,
            "metadata": {
                "engine": self.engine_id,
                "total_blocks": self.total_blocks,
                "processed_blocks": self.processed_blocks,
                "skipped_blocks": self.skipped_blocks,
                "elapsed_sec": round(self.elapsed_sec, 2),
                "errors": self.errors,
            },
        }


class OcrPipeline:
    """OCR 파이프라인.

    주요 메서드:
      run_page(): 페이지의 모든 블록을 OCR
      run_block(): 단일 블록만 OCR (재실행용)
    """

    def __init__(
        self,
        registry: OcrEngineRegistry,
        library_root: str,
    ):
        """파이프라인 초기화.

        입력:
          registry: OCR 엔진 레지스트리 (auto_register() 호출 완료 상태)
          library_root: 서고 루트 경로

        주의: library_root는 앱 설정에서 가져온다.
        """
        self.registry = registry
        self.library_root = library_root

    def run_page(
        self,
        doc_id: str,
        part_id: str,
        page_number: int,
        engine_id: Optional[str] = None,
        block_ids: Optional[list[str]] = None,
    ) -> OcrPageResult:
        """페이지의 블록들을 OCR 실행한다.

        입력:
          doc_id: 문서 ID
          part_id: 파트 ID
          page_number: 페이지 번호 (1-indexed)
          engine_id: OCR 엔진 (None이면 기본 엔진)
          block_ids: OCR할 블록 ID 목록 (None이면 전체)

        출력: OcrPageResult

        처리 순서:
          1. L3 layout_page.json 로드 → 블록 목록
          2. L1 이미지 로드
          3. 각 블록: 크롭 → OCR → 결과 수집
          4. 결과를 L2 JSON으로 저장
        """
        start_time = time.time()
        result = OcrPageResult(
            doc_id=doc_id, part_id=part_id, page_number=page_number
        )

        # 1. 엔진 확인
        engine = self.registry.get_engine(engine_id)
        result.engine_id = engine.engine_id

        # 2. L3 레이아웃 로드
        layout = self._load_layout(doc_id, part_id, page_number)
        if layout is None:
            result.errors.append(f"L3 레이아웃을 찾을 수 없습니다: page {page_number}")
            return result

        blocks = layout.get("blocks", [])
        result.total_blocks = len(blocks)

        # block_ids 필터링
        if block_ids is not None:
            blocks = [b for b in blocks if b.get("block_id") in block_ids]

        # reading_order로 정렬
        blocks.sort(key=lambda b: b.get("reading_order", 999))

        # 3. 이미지 로드
        image_path = get_page_image_path(
            self.library_root, doc_id, part_id, page_number
        )
        if image_path is None:
            result.errors.append(f"L1 이미지를 찾을 수 없습니다: page {page_number}")
            return result

        page_image = load_page_image(image_path)

        # 4. 블록별 OCR
        for block in blocks:
            block_id = block.get("block_id", "unknown")
            skip = block.get("skip", False)

            if skip:
                result.skipped_blocks += 1
                logger.debug(f"블록 건너뜀 (skip=true): {block_id}")
                continue

            try:
                ocr_result = self._process_block(engine, page_image, block)
                ocr_result["layout_block_id"] = block_id
                result.ocr_results.append(ocr_result)
                result.processed_blocks += 1
            except OcrEngineError as e:
                error_msg = f"블록 {block_id} OCR 실패: {e}"
                result.errors.append(error_msg)
                logger.warning(error_msg)

        result.elapsed_sec = time.time() - start_time

        # 5. L2 JSON 저장
        self._save_ocr_result(doc_id, part_id, page_number, result)

        logger.info(
            f"OCR 완료: {doc_id}/{part_id}/page_{page_number:03d} — "
            f"{result.processed_blocks}/{result.total_blocks} 블록, "
            f"{result.elapsed_sec:.1f}초"
        )

        return result

    def run_block(
        self,
        doc_id: str,
        part_id: str,
        page_number: int,
        block_id: str,
        engine_id: Optional[str] = None,
    ) -> OcrPageResult:
        """단일 블록만 OCR 실행 (재실행용).

        기존 L2 결과에서 해당 블록만 업데이트한다.
        """
        return self.run_page(
            doc_id, part_id, page_number,
            engine_id=engine_id,
            block_ids=[block_id],
        )

    def _process_block(
        self,
        engine,
        page_image,
        block: dict,
    ) -> dict:
        """단일 블록을 OCR 처리한다.

        입력: 엔진, 페이지 이미지, 블록 정보(L3)
        출력: OCR 결과 딕셔너리 (ocr_page.schema.json 형식)
        """
        bbox = block.get("bbox")
        if not bbox or len(bbox) != 4:
            raise OcrEngineError(f"유효하지 않은 bbox: {bbox}")

        # 이미지 크롭
        cropped = crop_block(page_image, bbox)

        # 전처리
        writing_direction = block.get("writing_direction", "vertical_rtl")
        language = block.get("language", "classical_chinese")
        processed = preprocess_for_ocr(cropped, writing_direction=writing_direction)

        # OCR 실행
        ocr_result: OcrBlockResult = engine.recognize(
            processed,
            writing_direction=writing_direction,
            language=language,
        )

        return ocr_result.to_dict()

    def _load_layout(
        self, doc_id: str, part_id: str, page_number: int,
    ) -> Optional[dict]:
        """L3 layout_page.json을 로드한다.

        탐색 경로:
          {library_root}/sources/{doc_id}/{part_id}/L3_layout/page_{NNN}.json
        """
        page_str = f"page_{page_number:03d}"
        layout_path = os.path.join(
            self.library_root, "sources", doc_id, part_id,
            "L3_layout", f"{page_str}.json"
        )

        if not os.path.exists(layout_path):
            return None

        with open(layout_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_ocr_result(
        self,
        doc_id: str,
        part_id: str,
        page_number: int,
        result: OcrPageResult,
    ) -> str:
        """OCR 결과를 L2 JSON으로 저장한다.

        저장 경로:
          {library_root}/sources/{doc_id}/{part_id}/L2_ocr/page_{NNN}.json

        반환: 저장된 파일 경로
        """
        page_str = f"page_{page_number:03d}"
        l2_dir = os.path.join(
            self.library_root, "sources", doc_id, part_id, "L2_ocr"
        )
        os.makedirs(l2_dir, exist_ok=True)

        output_path = os.path.join(l2_dir, f"{page_str}.json")

        data = result.to_dict()

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"L2 OCR 결과 저장: {output_path}")
        return output_path
```

테스트 `tests/test_ocr_pipeline.py`:

```python
"""OCR 파이프라인 테스트.

실제 OCR 엔진 없이 더미 엔진으로 파이프라인 흐름을 검증한다.
"""

import json
import os
import io
import pytest
from PIL import Image

from src.ocr.base import BaseOcrEngine, OcrBlockResult, OcrLineResult, OcrCharResult
from src.ocr.registry import OcrEngineRegistry
from src.ocr.pipeline import OcrPipeline


class DummyOcrEngine(BaseOcrEngine):
    """테스트용 더미 OCR 엔진."""
    engine_id = "dummy"
    display_name = "Dummy"
    requires_network = False

    def is_available(self) -> bool:
        return True

    def recognize(self, image_bytes, writing_direction="vertical_rtl",
                  language="classical_chinese", **kwargs) -> OcrBlockResult:
        return OcrBlockResult(
            lines=[
                OcrLineResult(
                    text="王戎簡要",
                    bbox=[0, 0, 50, 200],
                    characters=[
                        OcrCharResult(char="王", confidence=0.95, bbox=[0, 0, 50, 50]),
                        OcrCharResult(char="戎", confidence=0.90, bbox=[0, 50, 50, 100]),
                        OcrCharResult(char="簡", confidence=0.88, bbox=[0, 100, 50, 150]),
                        OcrCharResult(char="要", confidence=0.92, bbox=[0, 150, 50, 200]),
                    ],
                ),
            ],
            engine_id="dummy",
            language=language,
            writing_direction=writing_direction,
        )


@pytest.fixture
def test_library(tmp_path):
    """테스트용 서고 디렉토리 구조 생성."""
    doc_dir = tmp_path / "sources" / "doc001" / "vol1"

    # L1 이미지 생성
    l1_dir = doc_dir / "L1_images"
    l1_dir.mkdir(parents=True)
    img = Image.new("RGB", (1000, 1500), "white")
    img.save(l1_dir / "page_001.png")

    # L3 레이아웃 생성
    l3_dir = doc_dir / "L3_layout"
    l3_dir.mkdir(parents=True)
    layout = {
        "page_number": 1,
        "blocks": [
            {
                "block_id": "p01_b01",
                "bbox": [0.1, 0.05, 0.3, 0.4],
                "reading_order": 1,
                "writing_direction": "vertical_rtl",
                "skip": False,
            },
            {
                "block_id": "p01_b02",
                "bbox": [0.5, 0.05, 0.3, 0.4],
                "reading_order": 2,
                "writing_direction": "vertical_rtl",
                "skip": False,
            },
            {
                "block_id": "p01_b03",
                "bbox": [0.1, 0.6, 0.8, 0.1],
                "reading_order": 3,
                "skip": True,  # 건너뛸 블록
            },
        ],
    }
    with open(l3_dir / "page_001.json", "w") as f:
        json.dump(layout, f)

    return tmp_path


class TestOcrPipeline:
    def test_run_page_full(self, test_library):
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(test_library))

        result = pipeline.run_page("doc001", "vol1", 1)

        assert result.processed_blocks == 2
        assert result.skipped_blocks == 1
        assert result.total_blocks == 3
        assert len(result.ocr_results) == 2
        assert result.ocr_results[0]["layout_block_id"] == "p01_b01"
        assert result.errors == []

    def test_run_page_saves_l2(self, test_library):
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(test_library))

        pipeline.run_page("doc001", "vol1", 1)

        # L2 파일이 생성되었는지 확인
        l2_path = test_library / "sources" / "doc001" / "vol1" / "L2_ocr" / "page_001.json"
        assert l2_path.exists()

        with open(l2_path) as f:
            data = json.load(f)
        assert data["page_number"] == 1
        assert len(data["ocr_results"]) == 2

    def test_run_page_specific_blocks(self, test_library):
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(test_library))

        result = pipeline.run_page("doc001", "vol1", 1, block_ids=["p01_b01"])
        assert result.processed_blocks == 1
        assert len(result.ocr_results) == 1
        assert result.ocr_results[0]["layout_block_id"] == "p01_b01"

    def test_run_page_no_layout(self, test_library):
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(test_library))

        result = pipeline.run_page("doc001", "vol1", 999)
        assert len(result.errors) == 1
        assert "L3 레이아웃" in result.errors[0]

    def test_run_page_no_image(self, test_library):
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())

        # 이미지 삭제
        img_path = test_library / "sources" / "doc001" / "vol1" / "L1_images" / "page_001.png"
        img_path.unlink()

        pipeline = OcrPipeline(registry, library_root=str(test_library))
        result = pipeline.run_page("doc001", "vol1", 1)
        assert len(result.errors) == 1
        assert "L1 이미지" in result.errors[0]

    def test_run_block(self, test_library):
        registry = OcrEngineRegistry()
        registry.register(DummyOcrEngine())
        pipeline = OcrPipeline(registry, library_root=str(test_library))

        result = pipeline.run_block("doc001", "vol1", 1, "p01_b02")
        assert result.processed_blocks == 1
        assert result.ocr_results[0]["layout_block_id"] == "p01_b02"
```

커밋: `feat(ocr): OCR 파이프라인 — 페이지/블록 단위 실행 + L2 저장`

---

### 작업 7: API 엔드포인트

기존 API 라우터에 OCR 엔드포인트를 추가한다.
(기존 API 구조를 먼저 확인하고 동일한 패턴으로 추가하라.)

```python
# src/api/ 에 ocr_routes.py 추가 (또는 기존 라우터에 병합)
# 아래는 엔드포인트 정의의 골격

# ── 엔진 상태 ──

# GET /api/ocr/engines
# 등록된 OCR 엔진 목록 + 사용 가능 여부
# 응답: { "engines": [...], "default_engine": "paddleocr" }

# ── OCR 실행 ──

# POST /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr
# 입력: {
#   "engine_id": "paddleocr",    // null이면 기본 엔진
#   "block_ids": ["p01_b01"],    // null이면 전체 블록
# }
# 응답: {
#   "status": "completed",
#   "engine": "paddleocr",
#   "processed_blocks": 2,
#   "skipped_blocks": 1,
#   "elapsed_sec": 3.5,
#   "ocr_results": [...],
#   "errors": []
# }

# ── OCR 결과 조회 ──

# GET /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr
# L2_ocr/page_NNN.json의 내용을 반환
# 없으면 404

# ── 단일 블록 재실행 ──

# POST /api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/ocr/{block_id}
# 특정 블록만 OCR 재실행
# 기존 L2 결과에서 해당 블록 업데이트
```

구현 시 주의사항:

1. 기존 API 구조(FastAPI 또는 Flask)를 확인하고 동일한 패턴으로 작성하라.
2. OcrPipeline과 OcrEngineRegistry는 앱 초기화 시 한 번만 생성한다.
3. OCR 실행은 시간이 걸릴 수 있다 — 프로그레스 정보를 응답에 포함한다.
4. 에러 발생 시에도 부분 결과를 반환한다 (3블록 중 2블록 성공이면 2블록 결과 + 에러 메시지).

커밋: `feat(api): OCR 엔드포인트 — 엔진 상태, 실행, 결과 조회`

---

### 작업 8: GUI — OCR 실행 + 결과 표시

기존 GUI 코드를 확인하고 레이아웃 모드에 OCR 기능을 추가한다.

#### 8-A: 레이아웃 모드 — OCR 실행 패널

레이아웃 모드 사이드 패널에 추가:

```
┌────────────────────────────┐
│  OCR 실행                   │
│                            │
│  엔진: [PaddleOCR ▼]       │ ← 사용 가능한 엔진 목록 (GET /api/ocr/engines)
│  언어: [고전중국어 ▼]       │ ← classical_chinese, korean, japanese
│                            │
│  [전체 OCR 실행]           │ ← POST .../ocr (block_ids: null)
│  [선택 블록 OCR]           │ ← POST .../ocr (선택된 block_ids)
│                            │
│  ── 프로그레스 ──           │
│  처리 중: 2/5 블록          │
│  [████████░░░░░] 40%       │
│                            │
│  ── 결과 미리보기 ──        │
│  블록 1: "王戎簡要" (95%)   │ ← confidence 표시
│  블록 2: "裴楷清通" (88%)   │
│  블록 3: (건너뜀)           │
└────────────────────────────┘
```

구현 포인트:

1. **엔진 드롭다운**: 앱 로드 시 `GET /api/ocr/engines`로 목록 조회. `available: true`인 것만 표시.
2. **전체/선택 OCR 버튼**: 선택된 블록이 없으면 "전체" 버튼만 활성화.
3. **프로그레스**: OCR 실행 중 로딩 스피너 표시. 완료 후 결과 표시.
4. **결과 미리보기**: 블록별 인식 텍스트 + confidence. confidence < 0.8이면 노란 배경.

#### 8-B: 교정 모드 — OCR 결과 자동 채움

교정 모드의 텍스트 편집기에:

1. **자동 채움 옵션**: OCR 결과가 있으면 "OCR 결과로 채우기" 버튼 표시.
2. **Confidence 하이라이팅**:
   - confidence ≥ 0.8: 기본 색상 (정상)
   - 0.5 ≤ confidence < 0.8: 노란 밑줄 (주의)
   - confidence < 0.5: 빨간 밑줄 (위험)
3. **글자별 tooltip**: 마우스 호버 시 해당 글자의 confidence 표시.

#### 8-C: 이미지 오버레이

pdf-renderer.js (또는 이미지 표시 컴포넌트)에:

1. **OCR 오버레이 레이어**: 인식된 글자를 원본 bbox 위치에 반투명 표시.
2. **토글 버튼**: `[오버레이 표시/숨기기]` — 기본은 숨김.
3. **색상 구분**: confidence에 따라 초록(≥0.8), 노랑(0.5~0.8), 빨강(<0.5).

구현 시 주의:
- bbox는 크롭 이미지 기준이므로, 전체 페이지에 표시하려면 블록의 bbox 오프셋을 더해야 한다.
- 오버레이는 Canvas 또는 absolute positioned DOM으로.

커밋: `feat(gui): OCR 실행 패널 + 결과 표시 + 이미지 오버레이`

---

### 작업 9: 통합 테스트

test_library의 더미 데이터 또는 蒙求 데이터로 전체 흐름을 검증한다.

```python
# tests/test_ocr_integration.py

"""OCR 통합 테스트.

전체 흐름: L3 레이아웃 → 이미지 크롭 → OCR → L2 저장 → API → GUI.
"""

class TestOcrIntegration:

    def test_full_flow_with_dummy_engine(self, test_library):
        """더미 엔진으로 전체 흐름 검증."""
        # 1. 레지스트리 + 파이프라인 생성
        # 2. run_page() 실행
        # 3. L2 JSON 생성 확인
        # 4. 스키마 검증 (ocr_page.schema.json이 있으면)
        # 5. 결과에 layout_block_id가 올바르게 매핑되었는지
        pass

    def test_api_endpoint_flow(self, test_client, test_library):
        """API를 통한 OCR 실행 + 결과 조회."""
        # 1. POST /api/.../ocr → 실행
        # 2. GET /api/.../ocr → 결과 조회
        # 3. 응답 형식 검증
        pass

    def test_partial_failure(self, test_library):
        """일부 블록 실패 시에도 나머지 결과가 저장되는지."""
        # bbox가 잘못된 블록 1개 포함
        # → 2블록 성공 + 1블록 에러 메시지
        pass
```

모든 테스트 실행:

```bash
uv run pytest tests/test_ocr_base.py tests/test_ocr_image_utils.py tests/test_ocr_registry.py tests/test_ocr_paddle.py tests/test_ocr_pipeline.py tests/test_ocr_integration.py -v
```

커밋: `test(ocr): 통합 테스트 — 파이프라인, API, 부분 실패`

---

### 작업 10: 최종 정리

1. `src/ocr/__init__.py`에 모든 주요 클래스를 export:

```python
from .pipeline import OcrPipeline
from .registry import OcrEngineRegistry
from .base import BaseOcrEngine, OcrBlockResult, OcrLineResult, OcrCharResult
from .base import OcrEngineError, OcrEngineUnavailableError
from .image_utils import crop_block, preprocess_for_ocr, load_page_image
```

2. `docs/DECISIONS.md`에 추가:

```markdown
## D-009: OCR 엔진 플러그인 아키텍처

- 결정일: 2026-02-XX
- 상태: 확정
- 내용:
  - 모든 OCR 엔진은 BaseOcrEngine을 상속
  - OcrEngineRegistry로 등록/조회
  - OcrPipeline을 통해 실행 (엔진 직접 호출 금지)
  - 기본 엔진: PaddleOCR (오프라인 퍼스트)
  - L3 bbox → 이미지 크롭 → OCR → L2 JSON 저장
- 근거: 파서와 동일한 플러그인 패턴으로 일관성 유지, 오프라인 퍼스트
```

3. `docs/phase10_12_design.md`의 Phase 10-1 섹션에 "✅ 완료" 표시.

4. `.env.example`에 OCR 설정 항목 추가 (필요하면):

```env
# === OCR 설정 ===
# OCR_DEFAULT_ENGINE=paddleocr
# OCR_DEFAULT_LANGUAGE=classical_chinese
# OCR_DEFAULT_WRITING_DIRECTION=vertical_rtl
```

최종 커밋: `feat: Phase 10-1 완료 — OCR 엔진 연동 (PaddleOCR)`

---

## 체크리스트

작업 완료 후 아래를 모두 확인하라:

- [ ] `src/ocr/` 전체 구조가 위 디렉토리 구조와 일치
- [ ] `from src.ocr import OcrPipeline, OcrEngineRegistry` 정상 동작
- [ ] 모든 테스트 통과 (`uv run pytest tests/test_ocr_*.py -v`)
- [ ] PaddleOCR 미설치 환경에서도 나머지 코드 에러 없음
- [ ] L3 layout_page.json → L2 ocr_page.json 변환 정상
- [ ] .env.example에 OCR 설정 항목 추가됨
- [ ] DECISIONS.md에 D-009 추가됨
- [ ] API 엔드포인트가 기존 앱에 등록됨 (`GET /api/ocr/engines` 접근 가능)
- [ ] GUI에 OCR 실행 패널 + 결과 표시 + 오버레이 동작

---

## ⏭️ 다음 세션: Phase 10-3 — 정렬 엔진

```
이 세션(10-1)이 완료되면 다음 작업은 Phase 10-3 — 정렬 엔진이다.

10-1에서 만든 것:
  ✅ OCR 플러그인 아키텍처 (BaseOcrEngine + Registry)
  ✅ PaddleOCR 엔진 (오프라인)
  ✅ OCR 파이프라인 (L3 → 크롭 → OCR → L2)
  ✅ API 엔드포인트
  ✅ GUI — OCR 실행 + 결과 표시 + 오버레이

10-3에서 만들 것:
  - OCR 결과(L2)와 확정 텍스트(L4)를 글자 단위 대조
  - 이체자 사전으로 이체자(同字異形) 보정
  - 불일치 하이라이팅 GUI

세션 문서: phase10_3_alignment_session.md
사전 준비:
  - L2 OCR 결과와 L4 확정 텍스트가 모두 있는 테스트 페이지 확인
  - resources/variant_chars.json (이체자 사전) 초기 데이터 준비
```
