"""HWP 텍스트 정리기 — 표점·현토·대두 분리.

HWP에서 추출한 텍스트에는 표점(구두점), 현토(한글 토씨), 대두(존경 공백)가
포함되어 있을 수 있다. L4(원문)에는 순수 한자만 저장하고,
분리된 표점·현토는 L5에 자동 저장한다.

처리 순서:
  1. 대두(擡頭) 감지 — 줄머리 공백 패턴 분석
  2. 줄바꿈·탭 → 공백으로 정규화
  3. 각 글자를 순회하며 분류: 한자(원문) / 표점 / 현토(한글) / 공백
  4. [표점][공백*] 세트 → 표점만 추출, 공백 제거
  5. [현토][표점?][공백*] 세트 → 현토·표점 각각 추출, 공백 제거
  6. 원문 글자만 연결 → clean_text
  7. 표점·현토의 pos는 clean_text 기준 인덱스 (제거 후 재계산)

사용법:
    from src.hwp.text_cleaner import clean_hwp_text

    result = clean_hwp_text("天地之道。忠恕而已矣，")
    # result.clean_text == "天地之道忠恕而已矣"
    # result.punctuation_marks == [{"pos": 3, "mark": "。"}, {"pos": 8, "mark": "，"}]
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional


# ─── 문자 분류 상수 ──────────────────────────────────

# 전각 (중국식) 표점
FULLWIDTH_PUNCTUATION = set("。，；：？！《》〈〉「」『』·")
# 반각 (한국식) 표점
HALFWIDTH_PUNCTUATION = set(".,;:?!()")
# 따옴표류
QUOTE_MARKS = set("\u201c\u201d\u2018\u2019")  # "" ''
# 전체 표점
ALL_PUNCTUATION = FULLWIDTH_PUNCTUATION | HALFWIDTH_PUNCTUATION | QUOTE_MARKS

# 반각 → 전각 정규화 매핑
HALFWIDTH_TO_FULLWIDTH = {
    ".": "。", ",": "，", ";": "；", ":": "：",
    "?": "？", "!": "！",
}

# CJK 한자 유니코드 범위 (CJK Unified Ideographs + Extension A)
_CJK_RANGES = [
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0x3400, 0x4DBF),    # CJK Extension A
    (0x20000, 0x2A6DF),  # CJK Extension B
    (0xF900, 0xFAFF),    # CJK Compatibility Ideographs
    (0x2F800, 0x2FA1F),  # CJK Compatibility Supplement
]

# 한글 음절 블록: U+AC00 ~ U+D7A3
_HANGUL_SYLLABLE_START = 0xAC00
_HANGUL_SYLLABLE_END = 0xD7A3


# ─── 결과 데이터 모델 ────────────────────────────────

@dataclass
class CleanResult:
    """텍스트 정리 결과.

    clean_text에서의 pos는 0-indexed이며, clean_text[pos] 글자 **뒤**에 해당한다.
    예: pos=3이면 clean_text[3] 뒤에 표점·현토가 위치.
    """
    clean_text: str                    # 순수 원문 (L4 .txt용)
    punctuation_marks: list[dict] = field(default_factory=list)
    # [{pos, mark, original_mark}] — pos: clean_text 기준 인덱스
    hyeonto_annotations: list[dict] = field(default_factory=list)
    # [{pos, text, position}] — position: "after" (글자 뒤)
    taidu_marks: list[dict] = field(default_factory=list)
    # [{pos, raise_chars, note}] — pos: clean_text 기준 인덱스
    had_punctuation: bool = False
    had_hyeonto: bool = False
    had_taidu: bool = False


# ─── 유틸리티 ────────────────────────────────────────

def _is_cjk(ch: str) -> bool:
    """한자(CJK 통합 표의문자)인지 확인."""
    cp = ord(ch)
    return any(start <= cp <= end for start, end in _CJK_RANGES)


def _is_hangul(ch: str) -> bool:
    """한글 음절 블록인지 확인."""
    cp = ord(ch)
    return _HANGUL_SYLLABLE_START <= cp <= _HANGUL_SYLLABLE_END


def _is_punctuation(ch: str) -> bool:
    """표점(구두점)인지 확인."""
    return ch in ALL_PUNCTUATION


def normalize_punctuation(mark: str) -> str:
    """반각 표점을 전각(프로젝트 표준)으로 정규화한다.

    예: '.' → '。', ',' → '，', '?' → '？'
    전각은 그대로 반환. 매핑에 없는 문자는 그대로 반환.
    """
    return HALFWIDTH_TO_FULLWIDTH.get(mark, mark)


# ─── 대두 감지 ───────────────────────────────────────

def detect_taidu(text: str) -> list[dict]:
    """대두(擡頭) 공백을 감지한다.

    대두: 존경의 의미로 줄머리에 1~3자의 공백을 두는 서식.

    감지 패턴: [줄바꿈 또는 문단시작][공백1~3자][한자]
    일반 들여쓰기(4자 이상)와 구분한다.

    입력: 원시 텍스트 (줄바꿈 포함)
    출력: [{raw_pos, raise_chars, following_char, context}]
           raw_pos: 원본 텍스트에서의 위치 (공백 시작)
           raise_chars: 공백 수 (1~3)
           following_char: 공백 뒤의 첫 한자
           context: 앞뒤 문맥 (UI 표시용)

    주의: 자동 감지 결과이므로 사용자 확인이 필요하다.
    """
    candidates = []

    # 줄바꿈으로 분할하여 각 줄의 시작 검사
    lines = text.split("\n")
    pos = 0

    for line in lines:
        # 줄 시작의 공백 패턴: 1~3자 공백 + 한자
        match = re.match(r"^( {1,3})(\S)", line)
        if match:
            spaces = match.group(1)
            following = match.group(2)

            # 뒤따르는 글자가 한자일 때만 대두 후보
            if _is_cjk(following):
                # 문맥: 공백 주변 텍스트
                context_start = max(0, len(spaces))
                context_end = min(len(line), context_start + 10)
                context_text = line[context_start:context_end]

                candidates.append({
                    "raw_pos": pos,
                    "raise_chars": len(spaces),
                    "following_char": following,
                    "context": context_text,
                })

        pos += len(line) + 1  # +1 for \n

    return candidates


# ─── 현토 감지 ───────────────────────────────────────

def detect_hyeonto(text: str) -> list[dict]:
    """한자 사이에 끼어있는 한글(현토)을 감지한다.

    현토 패턴: [한자][한글1~4자][한자 또는 표점 또는 줄끝]
    예: "天地之道는忠恕" → "는"이 현토

    입력: 표점이 포함된 원시 텍스트
    출력: [{raw_pos, text, preceding_char, following_char}]
    """
    results = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        # 한글을 만나면
        if _is_hangul(ch):
            # 앞 글자가 한자인지 확인
            if i > 0 and _is_cjk(text[i - 1]):
                # 연속 한글 수집 (최대 4자)
                hangul_start = i
                while i < n and _is_hangul(text[i]) and (i - hangul_start) < 4:
                    i += 1
                hangul_text = text[hangul_start:i]

                # 뒤 글자가 한자, 표점, 공백, 줄끝 중 하나인지 확인
                if i >= n or _is_cjk(text[i]) or _is_punctuation(text[i]) or text[i] in " \n":
                    results.append({
                        "raw_pos": hangul_start,
                        "text": hangul_text,
                        "preceding_char": text[hangul_start - 1],
                        "following_char": text[i] if i < n else "",
                    })
                continue
        i += 1

    return results


# ─── 핵심 정리 함수 ──────────────────────────────────

def clean_hwp_text(
    raw_text: str,
    strip_punct: bool = True,
    strip_hyeonto: bool = True,
) -> CleanResult:
    """HWP 텍스트에서 표점·현토·공백을 분리하고 순수 원문만 반환한다.

    처리 순서:
      1. 대두 감지 (줄바꿈 기반, 대두 공백 분리)
      2. 줄바꿈·탭 → 공백으로 정규화
      3. 각 글자를 순회하며 분류: 한자(원문) / 표점 / 현토(한글) / 공백
      4. [표점][공백*] 세트 → 표점만 추출, 공백 제거
      5. [현토][표점?][공백*] 세트 → 현토·표점 각각 추출, 공백 제거
      6. 원문 글자만 연결 → clean_text
      7. 표점·현토의 pos는 clean_text 기준 인덱스 (제거 후 재계산)

    입력: HWP에서 추출한 원시 텍스트 (표점·현토·공백 포함 가능)
    출력: CleanResult
    """
    if not raw_text or not raw_text.strip():
        return CleanResult(clean_text="")

    # 1. 대두 감지 (줄바꿈이 있는 원본에서 수행)
    taidu_candidates = detect_taidu(raw_text)

    # 2. 줄바꿈·탭 정규화 — 대두 공백 제거는 여기서 처리
    # 대두 위치의 공백을 먼저 마킹
    taidu_positions = set()
    for t in taidu_candidates:
        for offset in range(t["raise_chars"]):
            taidu_positions.add(t["raw_pos"] + offset)

    # 3. 글자별 순회 + 분류
    punctuation_marks: list[dict] = []
    hyeonto_annotations: list[dict] = []
    clean_chars: list[str] = []  # 순수 원문 글자들

    i = 0
    n = len(raw_text)

    while i < n:
        ch = raw_text[i]

        # 대두 공백은 건너뛰기 (taidu_marks에서 이미 기록)
        if i in taidu_positions:
            i += 1
            continue

        # 줄바꿈/탭 → 무시 (원문에 포함하지 않음)
        if ch in "\n\r\t":
            i += 1
            continue

        # --- 표점 처리 ---
        if _is_punctuation(ch) and strip_punct:
            original_mark = ch
            normalized = normalize_punctuation(ch)

            # pos: 바로 앞 원문 글자의 인덱스 (= 현재까지의 clean_chars 길이 - 1)
            pos = len(clean_chars) - 1 if clean_chars else 0
            punctuation_marks.append({
                "pos": pos,
                "mark": normalized,
                "original_mark": original_mark,
            })

            i += 1
            # 표점 뒤의 공백 세트 제거
            while i < n and raw_text[i] == " ":
                i += 1
            continue

        # --- 현토 처리 ---
        if _is_hangul(ch) and strip_hyeonto:
            # 앞 글자가 원문(한자)인지 확인
            if clean_chars and _is_cjk(clean_chars[-1]):
                # 연속 한글 수집 (최대 4자)
                hangul_start = i
                while i < n and _is_hangul(raw_text[i]) and (i - hangul_start) < 4:
                    i += 1
                hangul_text = raw_text[hangul_start:i]

                pos = len(clean_chars) - 1 if clean_chars else 0
                hyeonto_annotations.append({
                    "pos": pos,
                    "text": hangul_text,
                    "position": "after",
                })

                # 현토 뒤의 표점+공백 세트도 처리
                if i < n and _is_punctuation(raw_text[i]) and strip_punct:
                    original_mark = raw_text[i]
                    normalized = normalize_punctuation(raw_text[i])
                    punctuation_marks.append({
                        "pos": pos,
                        "mark": normalized,
                        "original_mark": original_mark,
                    })
                    i += 1

                # 공백 제거
                while i < n and raw_text[i] == " ":
                    i += 1
                continue

        # --- 공백 처리 ---
        if ch == " ":
            # 원문 한자 사이의 불필요한 공백 제거
            i += 1
            continue

        # --- 원문 글자 ---
        # 한자 + 기타 유의미한 글자(숫자 등)는 원문으로 포함
        clean_chars.append(ch)
        i += 1

    # 4. 결과 조립
    clean_text = "".join(clean_chars)

    # 대두 마크를 clean_text 기준 pos로 변환
    # 대두의 pos = 대두 공백 뒤의 첫 글자가 clean_text에서 몇 번째인지
    taidu_marks_clean: list[dict] = []
    for t in taidu_candidates:
        following = t["following_char"]
        # clean_text에서 해당 글자의 위치 찾기 (근사값)
        # 대두 뒤의 한자가 clean_text에서 어디에 있는지 순차 검색
        # (정확한 매핑은 복잡하므로, 순서 기반으로 추정)
        # 여기서는 대두 후보를 그대로 반환하고, 호출자가 확인하도록 함
        taidu_marks_clean.append({
            "pos": 0,  # 호출자가 매핑할 것
            "raise_chars": t["raise_chars"],
            "note": f"{t['following_char']} 앞 대두 {t['raise_chars']}자",
            "raw_pos": t["raw_pos"],
            "following_char": t["following_char"],
            "context": t.get("context", ""),
        })

    return CleanResult(
        clean_text=clean_text,
        punctuation_marks=punctuation_marks,
        hyeonto_annotations=hyeonto_annotations,
        taidu_marks=taidu_marks_clean,
        had_punctuation=len(punctuation_marks) > 0,
        had_hyeonto=len(hyeonto_annotations) > 0,
        had_taidu=len(taidu_candidates) > 0,
    )


# ─── 편집 후 재계산 ─────────────────────────────────

def reclean_after_edit(
    clean_text: str,
    edits: list[dict],
    punctuation_marks: list[dict],
    hyeonto_annotations: list[dict],
) -> CleanResult:
    """사용자가 clean_text를 수정한 후, 표점·현토 위치를 재계산한다.

    edits: [{type, pos, old_char, new_char}]
      type: "replace" | "insert" | "delete"
      pos: clean_text 기준 위치

    처리:
      1. edits를 pos 내림차순으로 정렬 (뒤에서부터 적용)
      2. 각 edit에 따라 clean_text 수정
      3. 표점·현토의 pos를 edit에 따라 시프트
      4. 삭제된 범위에 걸친 표점·현토는 warnings에 포함

    페이지 경계에는 영향 없음 (페이지 내 텍스트만 변경).
    """
    # edit를 pos 내림차순으로 정렬 (뒤에서부터 적용 → 앞쪽 pos 불변)
    sorted_edits = sorted(edits, key=lambda e: e["pos"], reverse=True)

    new_text = list(clean_text)
    new_punct = [dict(p) for p in punctuation_marks]
    new_hyeonto = [dict(h) for h in hyeonto_annotations]

    for edit in sorted_edits:
        edit_type = edit["type"]
        pos = edit["pos"]

        if edit_type == "replace":
            # 글자 교체: pos 변경 없음, 텍스트만 수정
            if 0 <= pos < len(new_text):
                new_text[pos] = edit.get("new_char", new_text[pos])

        elif edit_type == "insert":
            # 삽입: pos 이후의 모든 pos를 +1
            new_char = edit.get("new_char", "")
            if new_char:
                new_text.insert(pos, new_char)
                for p in new_punct:
                    if p["pos"] >= pos:
                        p["pos"] += 1
                for h in new_hyeonto:
                    if h["pos"] >= pos:
                        h["pos"] += 1

        elif edit_type == "delete":
            # 삭제: pos 이후의 모든 pos를 -1
            if 0 <= pos < len(new_text):
                new_text.pop(pos)
                # 삭제된 위치의 표점·현토는 제거
                new_punct = [p for p in new_punct if p["pos"] != pos]
                new_hyeonto = [h for h in new_hyeonto if h["pos"] != pos]
                # 이후 pos 시프트
                for p in new_punct:
                    if p["pos"] > pos:
                        p["pos"] -= 1
                for h in new_hyeonto:
                    if h["pos"] > pos:
                        h["pos"] -= 1

    return CleanResult(
        clean_text="".join(new_text),
        punctuation_marks=new_punct,
        hyeonto_annotations=new_hyeonto,
        had_punctuation=len(new_punct) > 0,
        had_hyeonto=len(new_hyeonto) > 0,
    )
