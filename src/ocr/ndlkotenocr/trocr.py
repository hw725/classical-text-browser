"""TrOCR 문자 인식기 (NDL古典籍OCR 풀 모델).

NDL古典籍OCR(ndlkotenocr_cli ver.3)의 TrOCR 기반 문자 인식 모듈.
PARSeq-tiny(lite)보다 인식 품질이 높지만, PyTorch + GPU가 필요하다.

RTMDet ONNX(lite)가 탐지한 LINE 크롭 이미지를 입력받아 텍스트를 반환.
PARSeq의 read() 인터페이스와 호환되므로, 엔진에서 drop-in 교체 가능.

핵심 동작 (업스트림 text_recognition.py의 create_textline + predict 참조):
  - 세로쓰기 행(h > w): 반시계 90도 회전 후 입력
  - TrOCRProcessor로 전처리 → VisionEncoderDecoderModel.generate() → 디코드

원본: https://github.com/ndl-lab/ndlkotenocr_cli/blob/master/
      src/text_kotenseki_recognition/text_recognition.py
라이선스: CC BY 4.0 (National Diet Library, Japan)

의존성 (선택 설치):
  uv sync --extra ndlkotenocr-full
  → torch>=2.6.0, transformers>=4.47.0
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class TrOCRRecognizer:
    """NDL古典籍 TrOCR 문자 인식기.

    HuggingFace VisionEncoderDecoderModel 기반.
    3개 모델 디렉토리가 필요:
      - trocr-base-preprocessor: TrOCRProcessor (이미지 전처리)
      - decoder-roberta-v3: AutoTokenizer (텍스트 디코더)
      - kotenseki-trocr-honkoku-ver2: VisionEncoderDecoderModel (본체)

    PARSeq.read() 인터페이스와 호환:
      - read(line_img) → str: 단일 LINE 인식
      - read_batch(line_images) → list[str]: 배치 인식
    """

    def __init__(
        self,
        preprocessor_path: str,
        tokenizer_path: str,
        model_path: str,
        device: str = "auto",
        batch_size: int = 16,
    ) -> None:
        """TrOCR 모델을 로드한다.

        입력:
          preprocessor_path: TrOCRProcessor 디렉토리 경로
          tokenizer_path: AutoTokenizer 디렉토리 경로
          model_path: VisionEncoderDecoderModel 디렉토리 경로
          device: "auto" (CUDA 자동 감지), "cpu", "cuda:0" 등
          batch_size: 배치 추론 크기 (기본 16)
        """
        import torch
        from transformers import (
            AutoTokenizer,
            TrOCRProcessor,
            VisionEncoderDecoderModel,
        )

        # device 결정: "auto"이면 CUDA 유무 자동 감지
        if device == "auto":
            self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        self.batch_size = batch_size

        logger.info(
            f"TrOCR 모델 로딩 중... (device={self.device})\n"
            f"  preprocessor: {preprocessor_path}\n"
            f"  tokenizer: {tokenizer_path}\n"
            f"  model: {model_path}"
        )

        self.processor = TrOCRProcessor.from_pretrained(preprocessor_path)
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
        self.model = VisionEncoderDecoderModel.from_pretrained(model_path)
        self.model.to(self.device)
        self.model.eval()

        logger.info(f"TrOCR 모델 로딩 완료 (device={self.device})")

    def read(self, line_img: np.ndarray) -> str:
        """단일 LINE 이미지에서 텍스트를 인식한다.

        PARSeq.read()와 동일한 인터페이스.

        입력:
          line_img: RGB numpy 배열 (행 크롭 이미지).
                    세로쓰기(h > w)이면 내부에서 반시계 90도 회전.

        출력:
          인식된 텍스트 문자열. 인식 실패 시 빈 문자열.
        """
        import cv2
        import torch

        if line_img is None or line_img.size == 0:
            return ""

        try:
            # 세로쓰기 행 처리: h > w이면 반시계 90도 회전
            # 업스트림 ndlkotenocr_cli의 create_textline()과 동일
            h, w = line_img.shape[:2]
            if h > w:
                line_img = cv2.rotate(line_img, cv2.ROTATE_90_COUNTERCLOCKWISE)

            # 업스트림은 좌우 10% 여백을 잘라내지만(xshift), 우리 파이프라인에서는
            # RTMDet가 이미 정확한 bbox를 제공하므로 추가 크롭은 하지 않는다.
            # (업스트림: xshift = (xmax - xmin) // 10)

            pil_img = Image.fromarray(line_img)
            pixel_values = self.processor(pil_img, return_tensors="pt").pixel_values
            pixel_values = pixel_values.to(self.device, torch.float)

            with torch.no_grad():
                generated_ids = self.model.generate(pixel_values)

            text = self.tokenizer.batch_decode(
                generated_ids, skip_special_tokens=True,
            )[0]

            return text.strip()

        except Exception as e:
            logger.warning(f"TrOCR 인식 실패: {e}")
            return ""

    def read_batch(self, line_images: list[np.ndarray]) -> list[str]:
        """여러 LINE 이미지를 배치로 인식한다 (속도 최적화).

        GPU가 있을 때 전체 페이지의 LINE을 한 번에 처리하면
        개별 호출 대비 2-5배 빠르다.

        입력:
          line_images: RGB numpy 배열 목록

        출력:
          인식 텍스트 문자열 목록 (입력과 같은 순서)
        """
        import cv2
        import torch

        if not line_images:
            return []

        results: list[str] = []

        for i in range(0, len(line_images), self.batch_size):
            batch_imgs = line_images[i : i + self.batch_size]
            pil_batch = []

            for img in batch_imgs:
                if img is None or img.size == 0:
                    # 빈 이미지는 1×1 더미로 대체 (배치 크기 유지)
                    pil_batch.append(Image.new("RGB", (1, 1)))
                    continue

                h, w = img.shape[:2]
                if h > w:
                    img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
                pil_batch.append(Image.fromarray(img))

            try:
                pixel_values = self.processor(
                    pil_batch, return_tensors="pt",
                ).pixel_values
                pixel_values = pixel_values.to(self.device, torch.float)

                with torch.no_grad():
                    generated_ids = self.model.generate(pixel_values)

                texts = self.tokenizer.batch_decode(
                    generated_ids, skip_special_tokens=True,
                )
                results.extend(t.strip() for t in texts)

            except Exception as e:
                logger.warning(f"TrOCR 배치 인식 실패 (batch {i}~): {e}")
                # 실패한 배치는 빈 문자열로 채움
                results.extend("" for _ in batch_imgs)

        return results