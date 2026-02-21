"""HWP/HWPX 파일 처리 모듈.

가져오기(import)만 지원. 내보내기(export)는 나중에 추가 예정.

모듈 구성:
  reader.py       — hwp-hwpx-parser 기반 통합 리더 (HWP+HWPX)
  text_cleaner.py — 표점·현토 분리, 대두 감지, 반각→전각 정규화
"""

from .reader import UnifiedReader, detect_format, get_reader
from .text_cleaner import CleanResult, clean_hwp_text, normalize_punctuation

__all__ = [
    "UnifiedReader",
    "detect_format",
    "get_reader",
    "CleanResult",
    "clean_hwp_text",
    "normalize_punctuation",
]
