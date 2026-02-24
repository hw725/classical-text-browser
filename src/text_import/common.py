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
import unicodedata
from collections import Counter, defaultdict
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


def _nfc(text: str) -> str:
    """유니코드 NFC 정규화.

    왜 NFC인가:
      - 같은 한자가 합성(composed)과 분해(decomposed) 형태로 저장될 수 있다.
        예: '가' = U+AC00(NFC) vs U+1100+U+1161(NFD)
      - OCR 출력과 HWP/PDF 추출본의 인코딩이 다르면 동일 글자도 불일치.
      - NFC는 합성 형태로 통일하되, NFKC와 달리 호환 분해를 하지 않아
        한자의 의미 구분 (예: ﬀ→ff 같은 변환)을 방지한다.
    """
    return unicodedata.normalize("NFC", text)


def _build_ngram_index(text: str, n: int = 5) -> dict[str, list[int]]:
    """텍스트의 n-gram 인덱스를 구축한다.

    왜 이렇게 하는가:
      앵커를 텍스트에서 찾을 때 str.find() 정확 매칭이 실패하면,
      기존에는 슬라이딩 윈도우로 SequenceMatcher를 매번 호출했다 (O(n*m)).
      n-gram 인덱스를 한 번 구축하면, 이후 앵커 탐색은 후보 위치를
      O(1)로 좁힌 뒤 후보만 검증하므로 훨씬 빠르다.

    입력:
        text — 인덱싱할 텍스트 (한자만 추출된 문자열)
        n — n-gram 크기 (기본 5)
    출력: {n-gram문자열: [등장위치, ...]} 매핑
    """
    index: dict[str, list[int]] = defaultdict(list)
    for i in range(len(text) - n + 1):
        index[text[i:i + n]].append(i)
    return index


def _find_anchor_in_index(
    anchor: str,
    search_start: int,
    ngram_index: dict[str, list[int]],
    han_string: str,
    ngram_size: int = 5,
) -> tuple[int, float]:
    """n-gram 인덱스를 사용하여 앵커를 빠르게 탐색한다.

    왜 이렇게 하는가:
      기존 퍼지 매칭은 슬라이딩 윈도우 전수 탐색으로 느렸다.
      n-gram 인덱스에서 앵커의 부분 n-gram들이 출현하는 위치를 모아,
      다수가 겹치는 위치를 후보로 추리면 검증 범위를 95% 이상 줄인다.

    입력:
        anchor — 탐색할 앵커 문자열
        search_start — 검색 시작 위치 (이전 매칭 이후)
        ngram_index — _build_ngram_index()로 구축한 인덱스
        han_string — 전체 한자 문자열
        ngram_size — 인덱스에 사용된 n-gram 크기
    출력: (위치, 신뢰도) 튜플. 실패 시 (-1, 0.0).
    """
    from difflib import SequenceMatcher

    anchor_len = len(anchor)

    # 1차: 정확 매칭 (가장 빠름)
    pos = han_string.find(anchor, search_start)
    if pos >= 0:
        return pos, 1.0

    if anchor_len < ngram_size:
        # 앵커가 n-gram보다 짧으면 단순 슬라이딩 윈도우
        return _fuzzy_search_range(
            anchor, han_string, search_start, len(han_string),
        )

    # 2차: n-gram 후보 추출
    # 앵커에서 n-gram을 겹침 없이 추출 (stride = ngram_size // 2 + 1)
    stride = max(1, ngram_size // 2 + 1)
    sub_ngrams = []
    for i in range(0, anchor_len - ngram_size + 1, stride):
        ng = anchor[i:i + ngram_size]
        sub_ngrams.append((ng, i))  # (n-gram, 앵커 내 오프셋)

    if not sub_ngrams:
        return -1, 0.0

    # 각 n-gram의 출현 위치에서 앵커 시작 위치를 역산
    pos_counter: Counter = Counter()
    for ng, offset in sub_ngrams:
        for hit in ngram_index.get(ng, []):
            # 이 n-gram이 앵커의 offset 위치에 있다면, 앵커 시작 = hit - offset
            estimated_start = hit - offset
            if estimated_start >= search_start:
                pos_counter[estimated_start] += 1

    if not pos_counter:
        return -1, 0.0

    # 절반 이상의 n-gram이 지목한 위치만 후보로 채택
    min_votes = max(1, len(sub_ngrams) // 2)
    candidates = sorted(
        pos for pos, cnt in pos_counter.items() if cnt >= min_votes
    )

    if not candidates:
        # 투표 실패 시, 가장 많은 표를 받은 위치 1개라도 검증
        best_candidate = pos_counter.most_common(1)[0][0]
        candidates = [best_candidate]

    # 동적 임계값: 앵커 길이에 비례 (긴 앵커일수록 엄격)
    threshold = max(0.6, 1.0 - (2.0 / anchor_len))

    # 후보에서만 SequenceMatcher 실행
    best_pos = -1
    best_ratio = 0.0
    for cand in candidates:
        end = cand + anchor_len
        if end > len(han_string):
            end = len(han_string)
        window = han_string[cand:end]
        if not window:
            continue
        ratio = SequenceMatcher(None, anchor, window).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_pos = cand

    if best_ratio >= threshold:
        return best_pos, best_ratio

    return -1, best_ratio


def _fuzzy_search_range(
    anchor: str,
    han_string: str,
    start: int,
    end: int,
) -> tuple[int, float]:
    """지정 범위 내에서 슬라이딩 윈도우 퍼지 매칭을 수행한다.

    캐스케이드 복구(Pass 2)와 짧은 앵커 처리에 사용.
    범위를 제한하여 전수 탐색의 비용을 줄인다.

    입력:
        anchor — 탐색할 앵커
        han_string — 전체 한자 문자열
        start, end — 검색 범위
    출력: (위치, 유사도) 튜플
    """
    from difflib import SequenceMatcher

    anchor_len = len(anchor)
    # 동적 임계값
    threshold = max(0.6, 1.0 - (2.0 / anchor_len)) if anchor_len > 2 else 0.6

    best_pos = -1
    best_ratio = 0.0
    search_end = min(end, len(han_string))

    for i in range(start, max(start, search_end - anchor_len + 1)):
        window = han_string[i:i + anchor_len]
        ratio = SequenceMatcher(None, anchor, window).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_pos = i

    if best_ratio >= threshold:
        return best_pos, best_ratio
    return -1, best_ratio


def _extract_multi_anchors(
    page_han: str,
    anchor_length: int,
) -> list[str]:
    """한 페이지의 한자 문자열에서 다중 앵커(시작부·중간부·끝부)를 추출한다.

    왜 다중 앵커인가:
      단일 앵커(중간부만)는 해당 위치의 OCR 오류 하나로 매칭이 실패한다.
      3개 앵커를 추출하여 투표하면, 1개가 오류여도 나머지 2개로 복구 가능.
      또한 시작부·끝부 앵커는 페이지 경계 추정에도 직접 도움이 된다.

    입력:
        page_han — 페이지의 한자만 추출한 문자열
        anchor_length — 각 앵커의 길이
    출력: 앵커 문자열 리스트 (최대 3개, 길이 미달 시 1개)
    """
    n = len(page_han)
    if n < anchor_length:
        # 앵커 길이에 미달 → 전체를 단일 앵커로
        return [page_han] if page_han else []

    if n < anchor_length * 2:
        # 앵커 2개를 겹침 없이 추출하기 어려움 → 시작부·끝부 2개
        return [
            page_han[:anchor_length],
            page_han[n - anchor_length:],
        ]

    # 3개 앵커: 시작부, 중간부, 끝부
    mid = n // 2
    half = anchor_length // 2
    return [
        page_han[:anchor_length],                              # 시작부
        page_han[mid - half:mid - half + anchor_length],       # 중간부
        page_han[n - anchor_length:],                          # 끝부
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

    알고리즘 (다중 앵커 투표 + 해시 탐색 + 캐스케이드 복구):
      0. NFC 유니코드 정규화로 인코딩 차이를 제거
      1. 외부 텍스트에서 한자(\\p{Han})만 추출 → han_string + 위치 맵
      2. han_string의 n-gram 인덱스 구축 (1회, 이후 앵커 탐색에 재사용)
      3. 각 페이지에서 다중 앵커(시작·중간·끝) 추출 + 투표로 위치 결정
      4. Pass 1 실패한 앵커를 인접 성공 위치 범위에서 재탐색 (캐스케이드 복구)
      5. 앵커 위치를 원본 텍스트 위치로 역매핑하여 페이지 경계 결정
      6. 미매칭 페이지를 인접 경계에서 균등 보간

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
            anchor: str,            # 사용된 대표 앵커 문자열
        }]
    """
    import regex

    # ── 0단계: NFC 정규화 ──
    imported_text = _nfc(imported_text)

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

    # ── 2단계: n-gram 인덱스 구축 ──
    NGRAM = 5
    ngram_index = _build_ngram_index(han_string, NGRAM)

    # ── 3단계: 각 페이지의 다중 앵커 추출 + 투표 매칭 ──
    page_anchors: list[dict] = []
    match_positions: list[dict] = []
    search_start = 0

    for page in page_texts:
        page_text = _nfc(page.get("text", ""))
        page_han = "".join(regex.findall(r"\p{Han}", page_text))
        anchors = _extract_multi_anchors(page_han, anchor_length)
        ocr_preview = page_text.strip()[:80]

        page_anchors.append({
            "page_num": page["page_num"],
            "anchors": anchors,
            "page_han": page_han,
            "ocr_preview": ocr_preview,
        })

        if not anchors:
            match_positions.append({
                "han_pos": -1, "confidence": 0.0, "anchor": "",
            })
            continue

        # 각 앵커를 독립적으로 탐색
        anchor_results: list[tuple[int, float, str]] = []  # (pos, confidence, anchor)
        for anc in anchors:
            pos, conf = _find_anchor_in_index(
                anc, search_start, ngram_index, han_string, NGRAM,
            )
            anchor_results.append((pos, conf, anc))

        # 성공한 앵커들 (pos >= 0)
        successes = [(p, c, a) for p, c, a in anchor_results if p >= 0]

        if len(successes) >= 2:
            # 2개 이상 성공 → 중앙값 위치, 평균 신뢰도
            positions = sorted(s[0] for s in successes)
            median_pos = positions[len(positions) // 2]
            avg_conf = sum(s[1] for s in successes) / len(successes)
            best_anchor = max(successes, key=lambda s: s[1])[2]
            match_positions.append({
                "han_pos": median_pos,
                "confidence": avg_conf,
                "anchor": best_anchor,
            })
            search_start = median_pos + anchor_length
        elif len(successes) == 1:
            # 1개만 성공 → 해당 위치 사용, 신뢰도 페널티 (×0.8)
            pos, conf, anc = successes[0]
            match_positions.append({
                "han_pos": pos,
                "confidence": conf * 0.8,
                "anchor": anc,
            })
            search_start = pos + anchor_length
        else:
            # 모두 실패 → 가장 높은 유사도의 앵커 정보 보존
            best = max(anchor_results, key=lambda x: x[1])
            match_positions.append({
                "han_pos": -1,
                "confidence": best[1],
                "anchor": best[2],
            })

    # ── 4단계: 캐스케이드 복구 (Pass 2) ──
    # 실패한 앵커를 인접 성공 위치 범위 내에서 재탐색
    _recover_failed_matches(match_positions, page_anchors, han_string, NGRAM, ngram_index)

    # ── 5단계: 앵커 위치 → 페이지 경계 계산 ──
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
        mid_pt = (anchor_text_positions[i] + anchor_text_positions[i + 1]) // 2
        page_boundaries.append(mid_pt)
    page_boundaries.append(len(imported_text))  # 마지막 경계 = 텍스트 끝

    # ── 6단계: 결과 생성 ──
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


def _recover_failed_matches(
    match_positions: list[dict],
    page_anchors: list[dict],
    han_string: str,
    ngram_size: int,
    ngram_index: dict[str, list[int]],
) -> None:
    """Pass 1에서 실패한 앵커를 인접 성공 위치 범위 내에서 재탐색한다.

    왜 이렇게 하는가:
      순차 매칭에서 한 페이지가 실패하면 search_start가 정체하여
      후속 페이지도 연쇄 실패한다. Pass 2에서는 성공한 앵커 쌍 사이의
      범위만 검색하므로 안전하게 복구할 수 있다.

    입력:
        match_positions — Pass 1 결과 리스트 (제자리 수정)
        page_anchors — 페이지별 앵커 정보
        han_string — 전체 한자 문자열
        ngram_size — n-gram 크기
        ngram_index — n-gram 인덱스
    """
    n = len(match_positions)
    if n == 0:
        return

    # 성공한 앵커의 인덱스와 위치
    success_indices = [
        (i, mp["han_pos"])
        for i, mp in enumerate(match_positions) if mp["han_pos"] >= 0
    ]

    for i, mp in enumerate(match_positions):
        if mp["han_pos"] >= 0:
            continue  # 이미 성공

        anchors = page_anchors[i].get("anchors", [])
        if not anchors:
            continue

        # 직전·직후 성공 위치를 찾아 검색 범위 결정
        prev_pos = 0
        next_pos = len(han_string)
        for si, sp in success_indices:
            if si < i:
                prev_pos = max(prev_pos, sp)
            elif si > i:
                next_pos = min(next_pos, sp)
                break  # 가장 가까운 후속 성공만 필요

        # 범위가 너무 좁으면 건너뛰기
        if next_pos - prev_pos < 3:
            continue

        # 각 앵커를 축소된 범위에서 재탐색
        best_pos = -1
        best_conf = 0.0
        best_anchor = mp["anchor"]
        for anc in anchors:
            # n-gram 인덱스 기반 탐색 (범위를 search_start로 제한)
            pos, conf = _find_anchor_in_index(
                anc, prev_pos, ngram_index, han_string, ngram_size,
            )
            # 범위 내인지 확인
            if pos >= 0 and prev_pos <= pos <= next_pos and conf > best_conf:
                best_conf = conf
                best_pos = pos
                best_anchor = anc

        if best_pos >= 0:
            # 복구 성공 — 신뢰도에 복구 페널티 적용 (×0.9)
            mp["han_pos"] = best_pos
            mp["confidence"] = best_conf * 0.9
            mp["anchor"] = best_anchor
            logger.info(
                "캐스케이드 복구 성공: 페이지 %s (위치=%d, 신뢰도=%.2f)",
                page_anchors[i]["page_num"], best_pos, mp["confidence"],
            )


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
