"""텍스트 가져오기 공통 로직.

HWP와 PDF 가져오기가 공유하는 L4 저장, 사이드카 데이터 관리 함수.

왜 공통 모듈인가:
  HWP 가져오기(Part C)와 PDF 참조 텍스트 추출(Part D) 모두
  최종적으로 L4_text/pages/에 원문을 저장하고,
  표점·현토 데이터를 사이드카 JSON으로 보관하는 동일한 패턴을 따른다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def save_text_to_l4(
    doc_path: Path,
    part_id: str,
    page_num: int,
    text: str,
) -> Path:
    """정리된 원문 텍스트를 L4 페이지 파일에 저장한다.

    입력:
        doc_path — 문헌 디렉토리 (예: library/documents/monggu)
        part_id — 권 식별자 (예: "vol1")
        page_num — 페이지 번호 (1-indexed)
        text — 저장할 순수 원문 텍스트
    출력: 저장된 파일 경로
    """
    pages_dir = doc_path / "L4_text" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    file_path = pages_dir / f"{part_id}_page_{page_num:03d}.txt"
    file_path.write_text(text, encoding="utf-8")
    logger.info("L4 텍스트 저장: %s (%d자)", file_path.name, len(text))
    return file_path


def save_punctuation_sidecar(
    doc_path: Path,
    part_id: str,
    page_num: int,
    punctuation_marks: list[dict],
    hyeonto_annotations: list[dict],
    raw_text_length: int = 0,
    clean_text_length: int = 0,
    source: str = "hwp_import",
) -> Path | None:
    """표점·현토 데이터를 사이드카 JSON으로 저장한다.

    L4_text/pages/ 옆에 _hwp_clean.json 파일로 저장.
    나중에 L5(해석 저장소)로 이전할 수 있도록 중간 보관.

    입력:
        doc_path — 문헌 디렉토리
        part_id — 권 식별자
        page_num — 페이지 번호
        punctuation_marks — [{pos, mark, original_mark}]
        hyeonto_annotations — [{pos, text, position}]
        raw_text_length — 원본 텍스트 길이
        clean_text_length — 정리 후 텍스트 길이
        source — 출처 식별자 ("hwp_import" | "pdf_import")
    출력: 저장된 파일 경로 (데이터가 없으면 None)
    """
    if not punctuation_marks and not hyeonto_annotations:
        return None

    pages_dir = doc_path / "L4_text" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    file_path = pages_dir / f"{part_id}_page_{page_num:03d}_hwp_clean.json"
    data = {
        "source": source,
        "raw_text_length": raw_text_length,
        "clean_text_length": clean_text_length,
        "punctuation_marks": punctuation_marks,
        "hyeonto_annotations": hyeonto_annotations,
    }
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "사이드카 저장: %s (표점 %d, 현토 %d)",
        file_path.name,
        len(punctuation_marks),
        len(hyeonto_annotations),
    )
    return file_path


def save_formatting_sidecar(
    doc_path: Path,
    part_id: str,
    page_num: int,
    taidu_marks: list[dict],
) -> Path | None:
    """서식 메타데이터(대두 등)를 사이드카 JSON으로 저장한다.

    L4_text/pages/{part_id}_page_{NNN}_formatting.json에 저장.
    L4 txt는 순수 원문 유지, 서식 정보는 별도 파일에 보관.

    입력:
        doc_path — 문헌 디렉토리
        part_id — 권 식별자
        page_num — 페이지 번호
        taidu_marks — [{pos, raise_chars, note}]
    출력: 저장된 파일 경로 (데이터가 없으면 None)
    """
    if not taidu_marks:
        return None

    pages_dir = doc_path / "L4_text" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    file_path = pages_dir / f"{part_id}_page_{page_num:03d}_formatting.json"
    data = {
        "taidu": [
            {"pos": t["pos"], "raise_chars": t["raise_chars"], "note": t.get("note", "")}
            for t in taidu_marks
        ],
    }
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("서식 사이드카 저장: %s (대두 %d)", file_path.name, len(taidu_marks))
    return file_path


def build_auto_page_mapping(
    section_count: int,
    default_part_id: str,
    start_page: int = 1,
) -> list[dict]:
    """섹션 수 기반으로 자동 1:1 페이지 매핑을 생성한다.

    입력:
        section_count — HWP 섹션(또는 PDF 페이지) 수
        default_part_id — 기본 part_id (예: "vol1")
        start_page — 시작 페이지 번호 (기본 1)
    출력: [{"section_index": 0, "page_num": 1, "part_id": "vol1"}, ...]
    """
    return [
        {
            "section_index": i,
            "page_num": start_page + i,
            "part_id": default_part_id,
        }
        for i in range(section_count)
    ]
