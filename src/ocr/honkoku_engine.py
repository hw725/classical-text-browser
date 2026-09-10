"""みんなで翻刻OCR (honkoku-ocr-py) 엔진 — くずし字(초서·변체가나) 고서 전용, 오프라인.

무엇인가:
    橋本雄太의 브라우저판 「みんなで翻刻OCR」(honkoku-ocr-web, CC BY 4.0)의 추론 파이프라인을
    mkpoli가 Python/onnxruntime으로 옮긴 honkoku-ocr-py(MIT)를 감싼다. 행 검출은 NDL古典籍OCR-Lite와
    같은 RTMDet-s, 읽기 순서는 XY-Cut(세로쓰기는 오른쪽 단부터), 행 인식은 ConvNeXt V2 encoder +
    RoBERTa decoder(kuzushiji v18, 어휘 7,710). 브라우저판과 같은 가중치다.

왜 하나 더 두는가:
    NDL 계열은 인쇄·판본 한문에 강하고, 이 모델은 **붓으로 흘려 쓴 くずし字**에 특화돼 있다.
    필사본·초서 일기류에서 둘의 읽기를 행 단위로 견줄 수 있다(같은 행 검출기라 자리가 맞는다).

무엇을 저장하는가:
    L2의 text는 **본문 글자**(body_text) — 루비는 밑글자만, 返り点·送り仮名는 버린다. Koji 기법
    (태그 포함)은 행의 koji 칸에 남긴다. 좌표는 원본 이미지 좌표(EXIF 보정 뒤)라 그대로 L2 bbox다.

지원 언어: 일본어 고문서(くずし字)·한문. 한글은 인식하지 못한다.
모델: v18 (~289MB) — 첫 사용 때 자동으로 받고 SHA-256을 대조한다(HONKOKU_OCR_MODELS로 위치 지정).
의존성 (선택 설치): uv sync --extra honkoku → honkoku-ocr-py, onnxruntime, onnx.

원본: https://github.com/mkpoli/honkoku-ocr-py (MIT)
상류: https://github.com/yuta1984/honkoku-ocr-web (CC BY 4.0)
"""

from __future__ import annotations

import io
import logging
import os
import re
from typing import Callable, Optional

from PIL import Image

from .base import (
    BaseOcrEngine,
    OcrBlockResult,
    OcrCharResult,
    OcrEngineError,
    OcrEngineUnavailableError,
    OcrLineResult,
)
from .line_block_match import match_lines_to_blocks

logger = logging.getLogger(__name__)

MODEL_VERSION = "v18"

# 디코더의 특수 토큰(honkoku_ocr.koji와 같은 규약)
_RUBY = re.compile(r"<ruby>([^<]*)<rt>([^<]*)</rt>(?:<rt2>([^<]*)</rt2>)?</ruby>")
_DROP = re.compile(r"<KAERI>[^<]*</KAERI>|<OKURI>[^<]*</OKURI>")
_TAG = re.compile(r"<[^>]+>")


def body_text(raw: str) -> str:
    """디코더 원문(태그 열) → 저장할 본문. 입력: raw. 출력: 문자열.

    왜 라이브러리의 plain을 쓰지 않는가: raw_to_plain은 태그만 벗겨 **후리가나 읽기까지 본문에
    잇는다**
    (실측: 「化物（ばけもの）」→ 「化物ばけもの」). 이 프로그램의 L2는 원문 글자여야 하므로
    루비는 밑글자만, 返り点·送り仮名(일본어 훈독 보조)는 버리고, 割書는 오른쪽·왼쪽을 이어 붙이며,
    縦点은 koji와 같이 「ー」로 둔다. Koji 기법 전체는 행의 `koji` 칸에 따로 남긴다.
    """
    if not raw:
        return ""
    s = _RUBY.sub(lambda m: m.group(1), raw)
    s = _DROP.sub("", s)
    s = s.replace("<TATE>", "ー").replace("<WARI_SEP>", "")
    return _TAG.sub("", s).strip()


class HonkokuOcrEngine(BaseOcrEngine):
    """honkoku-ocr-py 래퍼. 쪽 단위 인식(권장)과 블록 크롭 인식을 지원한다."""

    engine_id = "honkoku"
    display_name = "みんなで翻刻OCR (honkoku-ocr-py v18 · くずし字·오프라인)"
    requires_network = False
    supports_page_level = True
    # 행 검출은 하지만 블록 종류(본문·주석·삽화)를 가르지 않는다 — 레이아웃 탐지는 NDL 엔진에 맡긴다
    supports_layout_detection = False

    def __init__(self):
        self._ocr = None  # honkoku_ocr.OCR — 첫 사용 때 만들고 재사용한다(모델 세션이 무겁다)
        self._unavailable_reason: Optional[str] = None

    # ── 사용 가능 여부 ────────────────────────────────────────────────────────
    def is_available(self) -> bool:
        """honkoku_ocr와 onnxruntime을 import할 수 있는가. 모델은 첫 사용 때 받는다."""
        try:
            import honkoku_ocr  # noqa: F401
            import onnxruntime  # noqa: F401
        except ImportError as e:
            self._unavailable_reason = (
                f"honkoku-ocr-py 또는 onnxruntime이 없습니다 ({e}). 설치: uv sync --extra honkoku"
            )
            return False
        self._unavailable_reason = None
        return True

    def _device(self) -> str:
        """HONKOKU_OCR_DEVICE(cpu|cuda). 비우면 onnxruntime-gpu가 있을 때만 cuda."""
        env = (os.environ.get("HONKOKU_OCR_DEVICE") or "").strip().lower()
        if env in ("cpu", "cuda"):
            return env
        try:
            import onnxruntime

            return (
                "cuda"
                if "CUDAExecutionProvider" in onnxruntime.get_available_providers()
                else "cpu"
            )
        except Exception:  # noqa: BLE001
            return "cpu"

    def _get_ocr(self):
        """OCR 인스턴스를 lazy로 만든다. 모델이 없으면 여기서 받는다(실패는 사용 불가)."""
        if self._ocr is not None:
            return self._ocr
        if not self.is_available():
            raise OcrEngineUnavailableError(self._unavailable_reason or "honkoku-ocr-py 사용 불가")
        from honkoku_ocr import OCR, ModelSetupError

        try:
            self._ocr = OCR(MODEL_VERSION, device=self._device(), quiet=True)
        except ModelSetupError as e:
            raise OcrEngineUnavailableError(
                f"みんなで翻刻OCR 모델을 준비하지 못했습니다: {e}\n"
                "→ 해결: 네트워크를 확인하거나 `honkoku-ocr --download`로 미리 받으세요."
            ) from e
        return self._ocr

    # ── 인식 ──────────────────────────────────────────────────────────────────
    @staticmethod
    def _line_dicts(page) -> list[dict]:
        """honkoku LineResult → 이 프로젝트의 행 dict. 좌표는 원본 이미지 좌표(네 꼭짓점)."""
        out = []
        for ln in page.lines:
            text = body_text(ln.raw)
            if not text:
                continue
            out.append(
                {
                    "text": text,
                    "koji": ln.koji,  # 태그 포함 표기(みんなで翻刻 기법) — 대조·검토용
                    "bbox": [
                        round(float(ln.x), 2),
                        round(float(ln.y), 2),
                        round(float(ln.x + ln.width), 2),
                        round(float(ln.y + ln.height), 2),
                    ],
                    "confidence": float(ln.detection_confidence),
                    "reading_order": int(ln.reading_order),
                }
            )
        return out

    def _process(self, image: Image.Image, boxes=None):
        """honkoku OCR을 돌린다. 실패는 OcrEngineError로 바꾼다."""
        from honkoku_ocr import ModelSetupError

        try:
            return self._get_ocr().process(image, boxes)
        except ModelSetupError as e:
            raise OcrEngineUnavailableError(f"みんなで翻刻OCR 모델 오류: {e}") from e
        except Exception as e:  # noqa: BLE001 — 엔진 내부 예외를 한 종류로 모은다
            raise OcrEngineError(f"みんなで翻刻OCR 인식 실패: {e}") from e

    def recognize(
        self,
        image_bytes: bytes,
        writing_direction: str = "vertical_rtl",
        language: str = "classical_chinese",
        **kwargs,
    ) -> OcrBlockResult:
        """블록 크롭 하나를 인식한다 — 크롭 안에서 행을 찾아 읽는다.

        입력: 크롭 이미지 바이트. 출력: OcrBlockResult(행·글자). 글자 신뢰도는 행 검출 신뢰도로
        대신한다(모델이 글자별 확률을 내지 않는다).
        """
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        page = self._process(image)
        lines = []
        for d in self._line_dicts(page):
            chars = [OcrCharResult(char=c, confidence=d["confidence"]) for c in d["text"]]
            lines.append(OcrLineResult(text=d["text"], bbox=d["bbox"], characters=chars))
        return OcrBlockResult(
            lines=lines,
            engine_id=self.engine_id,
            writing_direction=writing_direction,
            language=language,
        )

    def recognize_page(
        self,
        page_image_bytes: bytes,
        blocks: list[dict],
        progress_callback: Optional[Callable] = None,
        **kwargs,
    ) -> list[dict]:
        """쪽 전체에서 행을 찾아 읽고 L3 블록에 배정한다 (권장 경로).

        입력: 쪽 이미지(PNG 바이트 — 권 회전이 저장돼 있으면 이미 돌린 것, D-123), L3 블록 목록.
        출력: [{"layout_block_id", "lines": [{"text","bbox","characters"}]}] — skip 블록은 뺀다.
        """
        image = Image.open(io.BytesIO(page_image_bytes)).convert("RGB")
        processable = [b for b in blocks if not b.get("skip", False)]
        if progress_callback:
            progress_callback(
                {
                    "current": 0,
                    "total": len(processable),
                    "block_id": "",
                    "status": "detecting_lines",
                }
            )
        page = self._process(image)
        lines = self._line_dicts(page)
        for w in page.warnings or []:
            logger.info(f"みんなで翻刻OCR: {w}")
        if progress_callback:
            progress_callback(
                {
                    "current": 0,
                    "total": len(processable),
                    "block_id": "",
                    "status": "matching_blocks",
                }
            )
        by_block = match_lines_to_blocks(lines, blocks)
        results = []
        done = 0
        for block in blocks:
            if block.get("skip", False):
                continue
            block_id = block.get("block_id", "unknown")
            line_dicts = []
            for d in by_block.get(block_id, []):
                line_dicts.append(
                    {
                        "text": d["text"],
                        "koji": d["koji"],
                        "bbox": d["bbox"],
                        "characters": [
                            OcrCharResult(char=c, confidence=d["confidence"]).to_dict()
                            for c in d["text"]
                        ],
                    }
                )
            results.append({"layout_block_id": block_id, "lines": line_dicts})
            done += 1
            if progress_callback:
                progress_callback(
                    {
                        "current": done,
                        "total": len(processable),
                        "block_id": block_id,
                        "status": "processing",
                    }
                )
        logger.info(f"みんなで翻刻OCR 페이지 인식 완료: {len(lines)}행 → {len(results)}블록")
        return results

    def get_info(self) -> dict:
        info = super().get_info()
        info["supported_languages"] = ["classical_japanese", "classical_chinese"]
        info["language_warning"] = (
            "くずし字(초서·변체가나) 고문서 전용입니다. 한글은 인식할 수 없고, "
            "인쇄된 한문 판본에는 NDL古典籍OCR-Lite가 나을 수 있습니다."
        )
        info["model_source"] = (
            "mkpoli/honkoku-ocr-py 0.3 (MIT) — RTMDet-s(행) + ConvNeXt V2/RoBERTa kuzushiji v18 "
            "(みんなで翻刻OCR, CC BY 4.0)"
        )
        if self._unavailable_reason:
            info["unavailable_reason"] = self._unavailable_reason
        return info
