"""HWP/HWPX 파일 리더.

hwp-hwpx-parser 라이브러리를 사용하여 HWP(5.0)와 HWPX 모두
통합 API로 텍스트·이미지·메타데이터를 추출한다.

이전에는 python-hwpx(HWPX) + olefile(HWP PrvText)를 사용했으나,
hwp-hwpx-parser가 두 형식을 모두 처리하고 HWP도 전체 파싱하므로 교체.

사용법:
    reader = get_reader(Path("문서.hwpx"))
    text = reader.extract_text()
    sections = reader.extract_sections()   # HWPX: 실제 섹션별, HWP: 단락 기반 분할
    metadata = reader.extract_metadata()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from hwp_hwpx_parser import (
    ExtractOptions,
    FileType,
    Reader,
)

logger = logging.getLogger(__name__)


class UnifiedReader:
    """HWP/HWPX 통합 리더.

    hwp-hwpx-parser의 Reader를 감싸서, 기존 코드와 호환되는
    extract_text(), extract_sections(), extract_metadata() 인터페이스를 제공한다.
    """

    def __init__(self, file_path: Path):
        """통합 리더 초기화.

        입력: HWP 또는 HWPX 파일 경로
        에러: FileNotFoundError — 파일이 없을 때
              ValueError — 지원하지 않는 형식이거나 손상된 파일
        """
        self._path = Path(file_path)
        if not self._path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {self._path}")

        self._reader = Reader(self._path)

        if not self._reader.is_valid:
            raise ValueError(
                f"유효하지 않은 HWP/HWPX 파일입니다: {self._path}\n"
                "→ 파일이 손상되었거나, 지원하지 않는 형식일 수 있습니다."
            )

        if self._reader.is_encrypted:
            raise ValueError(
                f"암호화된 HWP/HWPX 파일입니다: {self._path}\n"
                "→ 파일의 암호를 해제한 뒤 다시 시도하세요."
            )

    @property
    def file_type(self) -> str:
        """파일 형식을 반환한다. "hwpx" | "hwp" """
        ft = self._reader.file_type
        if ft == FileType.HWPX:
            return "hwpx"
        elif ft == FileType.HWP5:
            return "hwp"
        return "unknown"

    def extract_text(self) -> str:
        """전체 텍스트를 하나의 문자열로 추출한다.

        출력: 전체 문서 텍스트 (단락 사이 줄바꿈)
        """
        opts = ExtractOptions(
            paragraph_separator="\n",
            line_separator="\n",
            include_empty_paragraphs=False,
        )
        return self._reader.extract_text(opts)

    def extract_sections(self) -> list[dict]:
        """섹션별 텍스트를 추출한다.

        HWPX: 파일 내부의 실제 섹션(section0.xml, section1.xml ...)별로 추출.
        HWP: 전체 텍스트를 빈 줄 2개 이상 기준으로 분할하여 섹션화.

        출력: [{"index": 0, "name": "section0.xml", "text": "..."}, ...]

        왜 섹션이 필요한가:
          HWP/HWPX 가져오기에서 섹션은 PDF 페이지와 매핑하는 최소 단위이다.
          HWPX의 섹션이 반드시 PDF 페이지와 1:1은 아니지만,
          자동 매핑의 출발점으로 사용한다.
        """
        if self._reader.file_type == FileType.HWPX:
            return self._extract_hwpx_sections()
        else:
            return self._extract_hwp_sections()

    def _extract_hwpx_sections(self) -> list[dict]:
        """HWPX 파일의 실제 섹션별 텍스트를 추출한다.

        HWPXReader의 내부 메서드 _get_section_files()와 _extract_section()을 사용하여
        각 섹션(section0.xml 등)의 텍스트를 개별적으로 추출한다.
        """
        hwpx_reader = self._reader._get_reader()
        opts = ExtractOptions(
            paragraph_separator="\n",
            line_separator="\n",
            include_empty_paragraphs=False,
        )

        section_files = hwpx_reader._get_section_files()
        sections = []

        for i, section_file in enumerate(section_files):
            text = hwpx_reader._extract_section(section_file, opts)
            if text.strip():
                sections.append({
                    "index": i,
                    "name": Path(section_file).name,
                    "text": text.strip(),
                })

        return sections

    def _extract_hwp_sections(self) -> list[dict]:
        """HWP 파일의 텍스트를 단락 기반으로 섹션화한다.

        HWP 5.0은 섹션 경계가 텍스트에 명시적으로 드러나지 않으므로,
        빈 줄 2개 이상(\n\n+)을 단락/페이지 구분자로 사용한다.
        """
        import re

        full_text = self.extract_text()
        paragraphs = [t.strip() for t in re.split(r"\n{2,}", full_text) if t.strip()]

        sections = []
        for i, text in enumerate(paragraphs):
            sections.append({
                "index": i,
                "name": f"paragraph_{i}",
                "text": text,
            })

        return sections

    def extract_metadata(self) -> dict:
        """문서 메타데이터를 추출한다.

        출력: {"title": ..., "author": ..., "format": ..., "sections_count": ..., "file_size": ...}
        """
        # 섹션 수 추출
        try:
            sections = self.extract_sections()
            sections_count = len(sections)
        except Exception:
            sections_count = 0

        return {
            "title": self._path.stem,
            "author": None,
            "sections_count": sections_count,
            "file_size": self._path.stat().st_size,
            "format": self.file_type,
        }

    def extract_text_with_notes(self) -> dict:
        """본문 텍스트와 각주·미주를 함께 추출한다.

        출력: {
            "text": str,
            "footnotes": [{"number": int, "text": str}, ...],
            "endnotes": [{"number": int, "text": str}, ...],
        }
        """
        opts = ExtractOptions(
            paragraph_separator="\n",
            line_separator="\n",
            include_empty_paragraphs=False,
        )
        result = self._reader.extract_text_with_notes(opts)

        footnotes = [
            {"number": n.number, "text": n.text}
            for n in result.footnotes
        ]
        endnotes = [
            {"number": n.number, "text": n.text}
            for n in result.endnotes
        ]

        return {
            "text": result.text,
            "footnotes": footnotes,
            "endnotes": endnotes,
        }

    def extract_images(self, dest: Path) -> list[Path]:
        """문서 내장 이미지를 추출한다.

        입력: 이미지 저장 경로
        출력: 추출된 이미지 파일 경로 목록
        """
        dest.mkdir(parents=True, exist_ok=True)
        return self._reader.save_images(dest)

    def close(self):
        """리더 리소스를 해제한다."""
        self._reader.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def detect_format(file_path: Path) -> Optional[str]:
    """파일 형식을 감지한다.

    출력: "hwpx" | "hwp" | None

    판별 방법:
      - .hwpx 확장자 또는 ZIP 시그니처 → hwpx
      - .hwp 확장자 또는 OLE2 시그니처 → hwp
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == ".hwpx":
        return "hwpx"
    if ext == ".hwp":
        return "hwp"

    # 시그니처로 판별
    try:
        with open(path, "rb") as f:
            header = f.read(8)
        if header[:4] == b"PK\x03\x04":
            return "hwpx"  # ZIP = HWPX
        if header[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            return "hwp"  # OLE2 = HWP
    except Exception:
        pass

    return None


def get_reader(file_path: Path) -> UnifiedReader:
    """파일 형식에 맞는 통합 리더를 반환한다.

    입력: HWP 또는 HWPX 파일 경로
    출력: UnifiedReader
    에러: ValueError — 지원하지 않는 형식
    """
    fmt = detect_format(file_path)
    if fmt is None:
        raise ValueError(
            f"지원하지 않는 파일 형식입니다: {file_path.suffix}\n"
            "지원 형식: .hwp (한글 5.0), .hwpx (한글 2014+)"
        )
    return UnifiedReader(file_path)
