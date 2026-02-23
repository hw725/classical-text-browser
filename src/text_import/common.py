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


def align_text_to_pages(
    page_texts: list[dict],
    imported_text: str,
    anchor_length: int = 15,
) -> list[dict]:
    """기존 페이지 텍스트와 외부 텍스트를 한자 앵커로 대조하여 페이지별 매핑을 생성한다.

    왜 이렇게 하는가:
      기존 문헌에 이미 OCR/L4 텍스트가 있고, 외부 HWP/PDF에서 추출한 고품질
      텍스트를 가져다 붙이려 할 때, 외부 텍스트의 어느 부분이 어느 페이지에
      해당하는지 자동으로 알아내야 한다.
      한자 시퀀스는 유니코드 블록이 독특하여 15자면 거의 고유한 지문이 된다.
      페이지 순서가 보장되므로 순차 검색으로 효율적 매칭이 가능하다.

    알고리즘 (한자 앵커 순차 매칭):
      1. 외부 텍스트에서 한자(\\p{Han})만 추출 → han_string + 위치 맵
      2. 각 페이지의 기존 텍스트에서 한자 추출 → 중간 N자를 앵커로 사용
      3. han_string에서 앵커를 순차 검색 (이전 매칭 위치 이후부터)
      4. 앵커 위치를 원본 텍스트 위치로 역매핑하여 페이지 경계 결정
      5. 정확 매칭 실패 시 difflib로 퍼지 매칭 폴백
      6. OCR 텍스트가 없으면 균등 분할 폴백

    입력:
        page_texts — [{page_num, text}] 기존 문헌의 페이지별 OCR/L4 텍스트
        imported_text — 분리된 원문 텍스트 (연속 문자열)
        anchor_length — 앵커로 사용할 한자 수 (기본 15)
    출력:
        [{
            page_num: int,
            matched_text: str,      # 외부 텍스트 중 이 페이지에 해당하는 부분
            ocr_preview: str,       # 기존 텍스트 미리보기 (첫 80자)
            confidence: float,      # 매칭 신뢰도 (0.0~1.0)
            anchor: str,            # 사용된 앵커 문자열
        }]
    """
    import regex
    from difflib import SequenceMatcher

    # ── 1단계: 외부 텍스트에서 한자 추출 + 위치 맵 구축 ──
    # han_to_pos[i] = imported_text에서 i번째 한자의 실제 위치
    han_chars: list[str] = []
    han_to_pos: list[int] = []
    for i, ch in enumerate(imported_text):
        if regex.match(r"\p{Han}", ch):
            han_chars.append(ch)
            han_to_pos.append(i)
    han_string = "".join(han_chars)

    if not han_string:
        # 외부 텍스트에 한자가 없으면 전체를 page 1에 매핑
        return [{
            "page_num": page_texts[0]["page_num"] if page_texts else 1,
            "matched_text": imported_text,
            "ocr_preview": "",
            "confidence": 0.0,
            "anchor": "",
        }]

    # ── 2단계: 각 페이지의 한자 앵커 추출 ──
    page_anchors: list[dict] = []
    for page in page_texts:
        page_han = "".join(regex.findall(r"\p{Han}", page.get("text", "")))
        if len(page_han) >= anchor_length:
            # 중간 부분에서 앵커 추출 (OCR 오류가 가장 적은 영역)
            mid = len(page_han) // 2
            half = anchor_length // 2
            anchor = page_han[mid - half : mid - half + anchor_length]
        elif page_han:
            anchor = page_han  # 짧으면 전체 사용
        else:
            anchor = ""
        page_anchors.append({
            "page_num": page["page_num"],
            "anchor": anchor,
            "page_han": page_han,
            "ocr_preview": page.get("text", "").strip()[:80],
        })

    # ── 3단계: 순차 앵커 매칭 ──
    # 각 앵커를 han_string에서 찾아 매칭 위치 결정
    match_positions: list[dict] = []  # [{han_pos, confidence, anchor}]
    search_start = 0

    for pa in page_anchors:
        anchor = pa["anchor"]
        if not anchor:
            match_positions.append({
                "han_pos": -1, "confidence": 0.0, "anchor": "",
            })
            continue

        # 정확 매칭 시도
        pos = han_string.find(anchor, search_start)
        if pos >= 0:
            match_positions.append({
                "han_pos": pos, "confidence": 1.0, "anchor": anchor,
            })
            search_start = pos + len(anchor)
            continue

        # 정확 매칭 실패 → 퍼지 매칭 (슬라이딩 윈도우)
        best_pos = -1
        best_ratio = 0.0
        window_size = len(anchor)
        # 검색 범위 제한: search_start부터 합리적 범위까지
        search_end = min(len(han_string), search_start + window_size * 20)

        for i in range(search_start, max(search_start, search_end - window_size + 1)):
            window = han_string[i : i + window_size]
            ratio = SequenceMatcher(None, anchor, window).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_pos = i

        if best_ratio >= 0.6:  # 60% 이상 일치하면 매칭으로 인정
            match_positions.append({
                "han_pos": best_pos, "confidence": best_ratio, "anchor": anchor,
            })
            search_start = best_pos + window_size
        else:
            match_positions.append({
                "han_pos": -1, "confidence": best_ratio, "anchor": anchor,
            })

    # ── 4단계: 앵커 위치 → 페이지 경계 계산 ──
    # 앵커는 각 페이지의 **중간**에서 추출했으므로,
    # 페이지 경계는 연속된 앵커 위치의 중간점으로 설정한다.
    #   Page 1: 0 ~ mid(anchor1, anchor2)
    #   Page 2: mid(anchor1, anchor2) ~ mid(anchor2, anchor3)
    #   Page N: mid(anchorN-1, anchorN) ~ end

    # 앵커 위치를 실제 텍스트 위치로 변환
    anchor_text_positions: list[int] = []
    for mp in match_positions:
        if mp["han_pos"] >= 0 and mp["han_pos"] < len(han_to_pos):
            anchor_text_positions.append(han_to_pos[mp["han_pos"]])
        else:
            anchor_text_positions.append(-1)

    # 미매칭(-1)을 보간
    _interpolate_missing(anchor_text_positions, len(imported_text))

    # 앵커 중간점으로 페이지 경계 생성
    page_boundaries: list[int] = [0]  # 첫 페이지는 항상 0에서 시작
    for i in range(len(anchor_text_positions) - 1):
        mid = (anchor_text_positions[i] + anchor_text_positions[i + 1]) // 2
        page_boundaries.append(mid)
    page_boundaries.append(len(imported_text))  # 마지막 경계 = 텍스트 끝

    # ── 5단계: 결과 생성 ──
    results: list[dict] = []
    for idx, pa in enumerate(page_anchors):
        start = page_boundaries[idx]
        end = page_boundaries[idx + 1]
        matched = imported_text[start:end].strip()

        results.append({
            "page_num": pa["page_num"],
            "matched_text": matched,
            "ocr_preview": pa["ocr_preview"],
            "confidence": match_positions[idx]["confidence"],
            "anchor": match_positions[idx]["anchor"],
        })

    return results


def _interpolate_missing(boundaries: list[int], total_length: int) -> None:
    """매칭 실패한 페이지 경계를 인접 성공 경계 사이에서 균등 보간한다.

    boundaries 리스트를 제자리(in-place)로 수정한다.
    -1인 항목을 직전 성공 위치와 다음 성공 위치 사이에서 균등 분배.

    왜 이렇게 하는가:
      일부 페이지의 OCR 텍스트가 비어있거나 매칭에 실패할 수 있다.
      이 경우 인접 페이지의 매칭 결과를 기반으로 합리적인 경계를 추정한다.

    입력:
        boundaries — 페이지별 시작 위치 리스트 (-1이면 미매칭)
        total_length — 전체 텍스트 길이
    """
    # 첫 번째가 -1이면 0으로
    if boundaries and boundaries[0] == -1:
        boundaries[0] = 0

    # 연속된 -1 구간을 찾아 보간
    i = 0
    while i < len(boundaries):
        if boundaries[i] == -1:
            # -1 구간의 시작
            gap_start = i
            while i < len(boundaries) and boundaries[i] == -1:
                i += 1
            # 직전 값
            prev_val = boundaries[gap_start - 1] if gap_start > 0 else 0
            # 다음 값
            next_val = boundaries[i] if i < len(boundaries) else total_length
            # 균등 보간
            gap_count = i - gap_start
            step = (next_val - prev_val) / (gap_count + 1)
            for j in range(gap_count):
                boundaries[gap_start + j] = int(prev_val + step * (j + 1))
        else:
            i += 1
