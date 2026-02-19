"""HWP/HWPX 파일 리더.

HWPX: python-hwpx 라이브러리를 사용하여 텍스트+메타데이터 추출.
HWP (레거시): olefile로 PrvText 스트림에서 텍스트 추출.

사용법:
    # HWPX
    reader = HwpxReader(Path("문서.hwpx"))
    text = reader.extract_text()
    sections = reader.extract_sections()

    # HWP (레거시)
    reader = HwpReader(Path("문서.hwp"))
    text = reader.extract_text()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class HwpxReader:
    """HWPX 파일에서 텍스트+메타데이터를 추출한다.

    HWPX는 OOXML 기반의 한글 문서 형식이다.
    python-hwpx 라이브러리의 TextExtractor를 사용한다.
    """

    def __init__(self, file_path: Path):
        """HWPX 리더 초기화.

        입력: HWPX 파일 경로
        에러: FileNotFoundError — 파일이 없을 때
        """
        self._path = Path(file_path)
        if not self._path.exists():
            raise FileNotFoundError(f"HWPX 파일을 찾을 수 없습니다: {self._path}")
        if not self._path.suffix.lower() == ".hwpx":
            logger.warning(f"확장자가 .hwpx가 아닙니다: {self._path.suffix}")

    def extract_text(self) -> str:
        """전체 텍스트를 하나의 문자열로 추출한다.

        출력: 전체 문서 텍스트 (단락 사이 줄바꿈)
        """
        from hwpx import TextExtractor

        extractor = TextExtractor(str(self._path))
        try:
            return extractor.extract_text(
                paragraph_separator="\n",
                skip_empty=True,
                preserve_breaks=True,
            )
        finally:
            extractor.close()

    def extract_sections(self) -> list[dict]:
        """섹션별 텍스트를 추출한다.

        HWPX의 섹션 = 원본 문서의 페이지 구분에 해당할 수 있다.
        (반드시 1:1은 아니지만, 페이지 매핑의 기본 단위로 사용)

        출력: [{"index": 0, "name": "section0.xml", "text": "..."}, ...]
        """
        from hwpx import TextExtractor

        extractor = TextExtractor(str(self._path))
        sections = []

        try:
            for section_info in extractor.iter_sections():
                # 섹션 내 단락 텍스트 수집
                paragraphs = []
                for para in extractor.iter_paragraphs(section_info.element):
                    text = extractor.paragraph_text(para)
                    if text and text.strip():
                        paragraphs.append(text)

                sections.append({
                    "index": section_info.index,
                    "name": section_info.name,
                    "text": "\n".join(paragraphs),
                })
        finally:
            extractor.close()

        return sections

    def extract_metadata(self) -> dict:
        """문서 메타데이터를 추출한다.

        출력: {"title": ..., "author": ..., "sections_count": ..., "file_size": ...}
        """
        from hwpx import TextExtractor

        extractor = TextExtractor(str(self._path))
        try:
            sections = list(extractor.iter_sections())
            sections_count = len(sections)
        except Exception:
            sections_count = 0
        finally:
            extractor.close()

        return {
            "title": self._path.stem,
            "author": None,
            "sections_count": sections_count,
            "file_size": self._path.stat().st_size,
            "format": "hwpx",
        }

    def extract_images(self, dest: Path) -> list[Path]:
        """HWPX 내장 이미지를 추출한다.

        HWPX는 ZIP 기반이므로 BinData/ 폴더의 이미지를 추출.

        입력: 이미지 저장 경로
        출력: 추출된 이미지 파일 경로 목록
        """
        import zipfile

        images: list[Path] = []
        dest.mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(self._path, "r") as zf:
                for name in zf.namelist():
                    # BinData/ 폴더의 이미지 파일
                    if name.startswith("BinData/") and any(
                        name.lower().endswith(ext)
                        for ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff")
                    ):
                        filename = Path(name).name
                        out_path = dest / filename
                        out_path.write_bytes(zf.read(name))
                        images.append(out_path)
                        logger.info(f"이미지 추출: {name} → {out_path}")
        except zipfile.BadZipFile:
            logger.warning(f"HWPX 파일이 손상되었거나 ZIP 형식이 아닙니다: {self._path}")

        return images


class HwpReader:
    """레거시 HWP 파일에서 텍스트를 추출한다.

    HWP 5.0 형식은 OLE2 구조를 사용한다.
    olefile로 PrvText (미리보기 텍스트) 스트림을 읽는다.

    주의: PrvText는 서식 없는 평문만 포함하며,
          원본 텍스트와 100% 동일하지 않을 수 있다.
          더 정확한 추출이 필요하면 hwp5txt 등을 사용해야 한다.
    """

    def __init__(self, file_path: Path):
        """HWP 리더 초기화.

        입력: HWP 파일 경로
        에러: FileNotFoundError — 파일이 없을 때
        """
        self._path = Path(file_path)
        if not self._path.exists():
            raise FileNotFoundError(f"HWP 파일을 찾을 수 없습니다: {self._path}")

    def extract_text(self) -> str:
        """PrvText 스트림에서 텍스트를 추출한다.

        출력: 문서 전체 텍스트
        에러: ValueError — PrvText 스트림이 없을 때
        """
        import olefile

        ole = olefile.OleFileIO(str(self._path))
        try:
            if not ole.exists("PrvText"):
                raise ValueError(
                    "HWP 파일에 PrvText 스트림이 없습니다.\n"
                    "이 파일은 한글 5.0 이전 버전이거나, "
                    "PrvText가 비활성화된 상태로 저장되었을 수 있습니다."
                )

            raw = ole.openstream("PrvText").read()
            # PrvText는 UTF-16 LE 인코딩
            text = raw.decode("utf-16-le", errors="replace")
            # null 문자 제거
            text = text.replace("\x00", "")
            return text.strip()
        finally:
            ole.close()

    def extract_metadata(self) -> dict:
        """문서 메타데이터를 추출한다.

        OLE2의 SummaryInformation에서 제목/저자 정보를 읽는다.
        """
        import olefile

        ole = olefile.OleFileIO(str(self._path))
        try:
            meta = ole.get_metadata()
            return {
                "title": (meta.title.decode("utf-8", errors="replace")
                          if meta.title else self._path.stem),
                "author": (meta.author.decode("utf-8", errors="replace")
                           if meta.author else None),
                "file_size": self._path.stat().st_size,
                "format": "hwp",
            }
        except Exception:
            return {
                "title": self._path.stem,
                "author": None,
                "file_size": self._path.stat().st_size,
                "format": "hwp",
            }
        finally:
            ole.close()


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


def get_reader(file_path: Path) -> HwpxReader | HwpReader:
    """파일 형식에 맞는 리더를 반환한다.

    입력: HWP 또는 HWPX 파일 경로
    출력: HwpxReader 또는 HwpReader
    에러: ValueError — 지원하지 않는 형식
    """
    fmt = detect_format(file_path)
    if fmt == "hwpx":
        return HwpxReader(file_path)
    if fmt == "hwp":
        return HwpReader(file_path)
    raise ValueError(
        f"지원하지 않는 파일 형식입니다: {file_path.suffix}\n"
        "지원 형식: .hwp (한글 5.0), .hwpx (한글 2014+)"
    )
