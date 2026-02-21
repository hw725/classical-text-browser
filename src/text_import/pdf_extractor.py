"""PDF 텍스트 레이어 추출기.

PyMuPDF(fitz)를 사용하여 PDF의 텍스트 레이어에서 텍스트를 추출한다.

왜 이렇게 하는가:
  텍스트 레이어가 있는 PDF는 OCR 없이 직접 텍스트를 가져올 수 있다.
  원문+번역+주석 혼합 PDF에서 정답 텍스트를 확보하는 첫 단계.
  추출한 텍스트를 LLM(text_separator.py)으로 원문/번역/주석 분리한다.

사용법:
    extractor = PdfTextExtractor(Path("참조문서.pdf"))
    if extractor.has_text_layer():
        pages = extractor.extract_all_pages()
        # → [{page_num: 1, text: "...", char_count: 234}, ...]
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class PdfTextExtractor:
    """PDF 텍스트 레이어에서 텍스트를 추출한다.

    PyMuPDF의 Page.get_text()를 사용한다.
    텍스트 레이어가 없는 스캔 PDF에서는 빈 텍스트가 반환되므로,
    has_text_layer()로 사전 확인이 필요하다.
    """

    def __init__(self, pdf_path: Path):
        """PDF 추출기 초기화.

        입력: PDF 파일 경로
        에러: FileNotFoundError — 파일이 없을 때
              ValueError — PDF를 열 수 없을 때
        """
        import fitz  # PyMuPDF

        self._path = Path(pdf_path)
        if not self._path.exists():
            raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {self._path}")

        try:
            self._doc = fitz.open(str(self._path))
        except Exception as e:
            raise ValueError(
                f"PDF 파일을 열 수 없습니다: {self._path}\n"
                f"→ 원인: {e}"
            ) from e

    @property
    def page_count(self) -> int:
        """PDF 전체 페이지 수."""
        return len(self._doc)

    def extract_page_text(self, page_num: int) -> str:
        """특정 페이지의 텍스트를 추출한다.

        입력: page_num — 1-indexed 페이지 번호
        출력: 해당 페이지의 텍스트 (줄바꿈 포함)
        에러: IndexError — 페이지 번호가 범위 밖일 때
        """
        if page_num < 1 or page_num > len(self._doc):
            raise IndexError(
                f"페이지 번호가 범위 밖입니다: {page_num} "
                f"(전체 {len(self._doc)}페이지)"
            )

        page = self._doc[page_num - 1]  # PyMuPDF는 0-indexed
        text = page.get_text("text")
        return text

    def extract_all_pages(self) -> list[dict]:
        """모든 페이지 텍스트를 추출한다.

        출력: [{page_num, text, char_count}, ...]
              page_num은 1-indexed.
              텍스트가 없는 페이지도 포함 (char_count=0).
        """
        pages = []
        for i in range(len(self._doc)):
            page = self._doc[i]
            text = page.get_text("text")
            pages.append({
                "page_num": i + 1,
                "text": text,
                "char_count": len(text.strip()),
            })
        return pages

    def extract_page_range(self, start: int, end: int) -> list[dict]:
        """지정 범위의 페이지 텍스트를 추출한다.

        입력:
            start — 시작 페이지 (1-indexed, 포함)
            end — 종료 페이지 (1-indexed, 포함)
        출력: [{page_num, text, char_count}, ...]
        """
        start = max(1, start)
        end = min(len(self._doc), end)

        pages = []
        for i in range(start - 1, end):
            page = self._doc[i]
            text = page.get_text("text")
            pages.append({
                "page_num": i + 1,
                "text": text,
                "char_count": len(text.strip()),
            })
        return pages

    def has_text_layer(self, sample_pages: int = 3) -> bool:
        """텍스트 레이어가 있는지 확인한다.

        첫 sample_pages 페이지 중 하나라도 텍스트가 있으면 True.
        텍스트 레이어가 없으면 OCR이 필요하다.

        입력: sample_pages — 확인할 페이지 수 (기본 3)
        출력: True/False
        """
        check_count = min(sample_pages, len(self._doc))
        for i in range(check_count):
            page = self._doc[i]
            text = page.get_text("text").strip()
            if len(text) > 10:  # 최소 10자 이상이면 텍스트 레이어 존재로 판정
                return True
        return False

    def get_sample_text(self, max_pages: int = 3) -> list[dict]:
        """미리보기용 샘플 텍스트를 추출한다.

        구조 분석(LLM)에 보낼 첫 몇 페이지의 텍스트.

        입력: max_pages — 추출할 최대 페이지 수
        출력: [{page_num, text, char_count}, ...]
        """
        return self.extract_page_range(1, max_pages)

    def close(self):
        """PDF 리소스를 해제한다."""
        if hasattr(self, "_doc") and self._doc:
            self._doc.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
