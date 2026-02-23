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


def save_translation_sidecar(
    doc_path: Path,
    part_id: str,
    page_num: int,
    translation_text: str,
    source: str = "hwp_import",
) -> Path | None:
    """분리된 번역 텍스트를 사이드카 파일로 저장한다.

    L4_text/pages/{part_id}_page_{NNN}_translation.txt에 저장.
    나중에 L6(해석 저장소 번역층)으로 가져갈 수 있도록 중간 보관.

    왜 이렇게 하는가:
      원문/번역 분리 후, 원문은 L4 .txt에, 번역은 이 사이드카에 보관한다.
      해석 저장소가 만들어지면 이 파일에서 L6로 가져올 수 있다.

    입력:
        doc_path — 문헌 디렉토리
        part_id — 권 식별자
        page_num — 페이지 번호
        translation_text — 번역 텍스트
        source — 출처 식별자
    출력: 저장된 파일 경로 (텍스트가 비어있으면 None)
    """
    if not translation_text or not translation_text.strip():
        return None

    pages_dir = doc_path / "L4_text" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    file_path = pages_dir / f"{part_id}_page_{page_num:03d}_translation.txt"
    file_path.write_text(translation_text, encoding="utf-8")
    logger.info("번역 사이드카 저장: %s (%d자)", file_path.name, len(translation_text))
    return file_path


def separate_by_script(text: str, han_threshold: float = 0.8) -> dict:
    """한문(漢字)과 한글을 유니코드 문자 유형 기반으로 분리한다.

    왜 이렇게 하는가:
      HWP/PDF의 고전 텍스트는 한문 원문과 한국어 번역이 줄 단위로
      교차 배치되거나 단락 단위로 나뉘는 경우가 대부분이다.
      LLM 없이도 각 줄의 한자/한글 비율만으로 정확하게 분류할 수 있다.

    알고리즘:
      1. 텍스트를 줄 단위로 분할
      2. 각 줄의 한자(\\p{Han}) 개수 vs 한글(\\p{Hangul}) 개수로 비율 계산
      3. 한자 비율이 임계값(기본 80%) 이상이면 원문, 미만이면 번역
         — 왜 80%인가: 번역문에도 한자(人名·地名·術語)가 꽤 쓰이지만,
           한국어 조사·어미(은/는/이/가/을/를/에 등)가 반드시 있으므로
           한자 비율은 대개 60~70% 이하. 반면 순한문은 거의 100%.
           현토(懸吐)가 섞인 한문도 한자 비율이 80% 이상.
      4. 둘 다 0이면(숫자·기호·라틴 등) 직전 분류를 따른다
      5. 빈 줄은 단락 구분자로 양쪽에 유지

    입력:
        text — HWP/PDF에서 추출한 전체 텍스트 (한문+번역 혼합)
        han_threshold — 원문으로 분류할 한자 비율 임계값 (기본 0.8 = 80%)
    출력:
        {
            "original_text": str,      # 한문 원문
            "translation_text": str,   # 한국어 번역
            "stats": {
                "total_lines": int,
                "original_lines": int,
                "translation_lines": int,
                "skipped_lines": int,
            }
        }
    """
    import regex

    lines = text.split("\n")
    original_parts: list[str] = []
    translation_parts: list[str] = []

    # 직전 분류 추적 (한자/한글 모두 0인 줄의 분류에 사용)
    last_type = "original"  # 기본값: 원문

    stats = {"total_lines": len(lines), "original_lines": 0,
             "translation_lines": 0, "skipped_lines": 0}

    for line in lines:
        stripped = line.strip()

        # 빈 줄 → 단락 구분자로 양쪽에 추가
        if not stripped:
            if original_parts and original_parts[-1] != "":
                original_parts.append("")
            if translation_parts and translation_parts[-1] != "":
                translation_parts.append("")
            continue

        # 줄 번호·괄호 번호 등 접두사 제거 후 분석
        # 예: "1. 昔有善牧者" → "昔有善牧者" 부분만 분석
        content_for_analysis = regex.sub(
            r"^[\s\d\.\)\]\】\》\>\-\–\—]+", "", stripped
        )

        # 유니코드 카테고리별 문자 수 계산
        han_count = len(regex.findall(r"\p{Han}", content_for_analysis))
        hangul_count = len(regex.findall(r"\p{Hangul}", content_for_analysis))

        if han_count == 0 and hangul_count == 0:
            # 순수 숫자/기호/라틴 → 직전 분류 따르기
            if last_type == "original":
                original_parts.append(stripped)
                stats["original_lines"] += 1
            else:
                translation_parts.append(stripped)
                stats["translation_lines"] += 1
            continue

        # 비율 기반 분류:
        #   한자 비율 >= 임계값(80%) → 원문 (순한문 또는 현토 섞인 한문)
        #   한자 비율 < 임계값 → 번역 (한자가 섞여 있더라도 한글 문장)
        total_cjk_hangul = han_count + hangul_count
        han_ratio = han_count / total_cjk_hangul

        if han_ratio >= han_threshold:
            original_parts.append(stripped)
            last_type = "original"
            stats["original_lines"] += 1
        else:
            translation_parts.append(stripped)
            last_type = "translation"
            stats["translation_lines"] += 1

    # 끝의 빈 줄 정리
    while original_parts and original_parts[-1] == "":
        original_parts.pop()
    while translation_parts and translation_parts[-1] == "":
        translation_parts.pop()

    return {
        "original_text": "\n".join(original_parts).strip(),
        "translation_text": "\n".join(translation_parts).strip(),
        "stats": stats,
    }


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
