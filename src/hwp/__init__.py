"""HWP/HWPX 파일 처리 모듈.

가져오기(import)만 지원. 내보내기(export)는 나중에 추가 예정.

모듈 구성:
  reader.py       — HWPX/HWP 파일에서 텍스트·메타데이터 추출
  text_cleaner.py — 표점·현토 분리, 대두 감지, 반각→전각 정규화
"""

from .reader import HwpxReader, HwpReader
from .text_cleaner import CleanResult, clean_hwp_text, normalize_punctuation

__all__ = [
    "HwpxReader",
    "HwpReader",
    "CleanResult",
    "clean_hwp_text",
    "normalize_punctuation",
]
