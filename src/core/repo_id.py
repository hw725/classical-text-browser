"""저장소 ID 규칙 — 단일 진실원 (single source of truth).

doc_id(원본 저장소)와 interp_id(해석 저장소)가 공유하는 ID 형식 규칙을
여기 한 곳에만 정의한다.

왜 분리된 모듈인가:
    2026-07-17 인지부채 감사에서 같은 정규식이 8곳(코어 2, 라우터 3,
    프론트 2, _state 1)에 독립 복제되어 있음이 확인되었다. 한 곳만 바꾸면
    층간 검증이 즉시 갈라지는(drift) 구조였다. 이제 파이썬 쪽은 전부
    이 모듈을 import하고, 프론트(JS)는 create-document.js의
    _DOC_ID_PATTERN 상수 하나만 이 규칙과 짝을 맞춘다 — 규칙을 바꿀 때는
    이 파일과 그 상수, 두 곳만 고치면 된다.

왜 이 규칙인가:
    ID는 파일시스템 디렉토리명 + git 저장소명으로 쓰이므로,
    manifest.schema.json 규칙에 따라 영문 소문자로 시작하고
    소문자·숫자·밑줄만 허용한다(최대 64자). ../ 같은 경로 탈출 문자가
    원천적으로 불가능한 문자 집합이다.
"""

import re

# ^[a-z]      — 영문 소문자로 시작
# [a-z0-9_]   — 이후 소문자·숫자·밑줄만
# {0,63}      — 총 길이 최대 64자
REPO_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# 에러 메시지에 붙이는 규칙 설명 — 문구도 한 곳에서만 관리한다.
REPO_ID_RULE_TEXT = "영문 소문자로 시작, 소문자·숫자·밑줄만 사용 (최대 64자)"


def is_valid_repo_id(repo_id: str) -> bool:
    """ID가 저장소 ID 규칙에 맞는지 검사한다.

    입력: repo_id — 검사할 문자열 (doc_id 또는 interp_id).
    출력: 규칙에 맞으면 True.
    """
    return bool(repo_id) and REPO_ID_PATTERN.match(repo_id) is not None
