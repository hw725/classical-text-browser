"""텍스트 가져오기 통합 모듈.

HWP/HWPX 텍스트 가져오기(Part C)와 PDF 참조 텍스트 추출(Part D)을
하나의 모듈에서 관리한다.

모듈 구성:
  pdf_extractor.py   — PDF 텍스트 레이어 추출 (PyMuPDF)
  text_separator.py  — LLM 기반 원문/번역/주석 분리
  common.py          — L4 저장, 페이지 매핑 등 공통 로직

HWP 관련 모듈은 기존 src/hwp/에 유지:
  hwp/reader.py      — HWP/HWPX 파일 읽기 (hwp-hwpx-parser)
  hwp/text_cleaner.py — 표점·현토 분리
"""

from .common import save_text_to_l4, save_punctuation_sidecar
from .pdf_extractor import PdfTextExtractor

__all__ = [
    "PdfTextExtractor",
    "save_text_to_l4",
    "save_punctuation_sidecar",
]
