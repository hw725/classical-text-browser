# Phase 10-4: KORCIS 파서 고도화 (선택적)

> Claude Code 세션 지시문
> 이 문서를 읽고 작업 순서대로 구현하라.
>
> ⚠️ 이 세션은 **선택적**이다.
> 파서 수선 세션에서 KORCIS 기본 구현이 충분하면 건너뛸 수 있다.
> 시작 전에 혜원과 확인하라.

---

## 사전 준비

1. CLAUDE.md를 먼저 읽어라.
2. 파서 수선 세션에서 만든 KORCIS 파서 코드를 확인하라:
   - `src/parsers/` 에서 KORCIS 관련 파일 찾기
   - 어떤 기능이 이미 구현되어 있는지 파악
3. D-008 보고서 (판식정보/서지정보 스키마 설계)를 읽어라.
4. 이 문서 전체를 읽은 후 작업을 시작하라.

---

## 배경: 무엇이 이미 있고, 무엇이 없는가

파서 수선 세션에서 KORCIS 파서의 **기본 기능**이 구현되었을 것이다:
- 웹 스크래핑 기반 서지 데이터 수집
- 기본 필드 매핑 (제목, 저자, 연대 등)
- BaseFetcher + BaseMapper 패턴

이 세션에서 추가할 **고급 기능**:
1. KORCIS OpenAPI 연동 (academic-mcp의 NLProvider 이식)
2. KORMARC 데이터의 완전한 매핑 (008 고서 코드 해석)
3. 판식정보(版式情報) 자동 추출

---

## 참조 프로젝트: academic-mcp

KORCIS API 구현의 참조 코드가 이미 존재한다:

```
C:\Users\junto\Downloads\head-repo\claude\academic-mcp\
  src/academic_mcp/
    config.py          ← Settings (pydantic-settings, .env 로드)
    server.py          ← Provider 초기화 + API 키 주입
    models/
      paper.py         ← Paper, PaperDetail, SearchQuery, Author, ProviderCategory
    providers/
      base.py          ← BaseProvider (api_key, httpx AsyncClient, search/get_detail)
      nl.py            ← NLProvider — 한국고문헌종합목록 (KORCIS)
      __init__.py      ← 전체 Provider export
```

### academic-mcp 아키텍처 요약

```python
# base.py — 모든 Provider의 추상 클래스
class BaseProvider(ABC):
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None
    
    async def search(self, query: SearchQuery) -> list[Paper]: ...
    async def get_detail(self, paper_id: str) -> PaperDetail | None: ...
    def is_available(self) -> bool: ...

# config.py — .env에서 API 키 로드
class Settings(BaseSettings):
    nl_api_key: str | None = None  # 국립중앙도서관
    # ... 기타 API 키들

# server.py — Provider 초기화
providers["nl"] = NLProvider(api_key=settings.nl_api_key)

# models/paper.py — 데이터 모델
class Paper(BaseModel):
    id, source, title, authors, journal, year, doi, url, abstract

class PaperDetail(Paper):
    keywords, volume, issue, pages, citation_count, references, publisher, language
```

### KORCIS OpenAPI (nl.py) 핵심

```python
class NLProvider(BaseProvider):
    name = "nl"
    display_name = "한국고문헌종합목록"
    category = ProviderCategory.ANCIENT

    SEARCH_URL = "https://www.nl.go.kr/korcis/openapi/search.do"
    DETAIL_URL = "https://www.nl.go.kr/korcis/openapi/detail.do"

    # ⚠️ API 키 필요 — .env의 NL_API_KEY
    # nl.py의 is_available()이 True를 무조건 반환하는 건 구현 미비.
    # 실제로는 API 키가 필요하다.

    # 검색: GET search.do?search_field=total&search_value=蒙求&page=1&display=10
    # 상세: GET detail.do?rec_key=...
    # 응답: XML (ElementTree로 파싱)
    # 검색 필드: RECORD → REC_KEY, TITLE, KOR_TITLE, AUTHOR, KOR_AUTHOR,
    #            PUBYEAR, PUBLISHER, EDIT_NAME(판종), LIB_NAME(소장기관)
    # 상세 필드: BIBINFO → TITLE_INFO, PUBLISH_INFO, EDITION_INFO,
    #            FORM_INFO(형태사항=판식정보 포함), NOTE_INFO
    #            HOLDINFO → LIB_NAME (소장기관 목록)
```

---

## 설계 요약

### 2. KORMARC 008 고서 코드 해석

KORMARC의 008 필드(고정 길이 데이터 요소)에서 고서 관련 코드를 해석한다:

```python
# 008 필드의 위치별 의미 (고서)
# 위치 06: 간행연대구분 — a(확실), b(추정), c(세기), ...
# 위치 07-10: 간행연도 — 4자리 숫자 또는 ####
# 위치 35-37: 언어코드 — chi(중국어), kor(한국어), ...
# 위치 38: 수정기록 — 공백(수정없음), d(수정), ...
```

이것은 기존 KORCIS 파서의 매핑 로직에 추가할 코드이다.

### 3. 판식정보 자동 추출

D-008 보고서의 P0 항목에서 정의된 판식정보 필드:

```
광곽(匡郭): 사주단변, 사주쌍변, 좌우쌍변 등
행자수(行字數): 10행 20자
판심(版心): 상하내향흑어미 등
판종(版種): 목판본, 활자본, 필사본 등
어미(魚尾): 상하내향흑어미, 상하백어미 등
계선(界線): 유계, 무계
```

이 정보를 서지 레코드에서 자동으로 추출하여 구조화된 형태로 저장한다.

---

## 작업 순서

### 작업 1: 현재 KORCIS 파서 상태 확인

먼저 기존 코드를 확인하고 부족한 부분을 목록으로 정리하라:

```bash
# 1. KORCIS 파서 파일 찾기
find src/parsers/ -name "*korcis*" -o -name "*KORCIS*"

# 2. 기존 코드 읽기 — 어떤 필드가 매핑되어 있는가?

# 3. 테스트 데이터 확인 — 실제 KORCIS 응답 샘플이 있는가?
```

확인 결과를 아래 형식으로 정리:

```markdown
## 기존 구현 상태
- [x] 기본 서지 검색 (키워드)
- [x] 제목, 저자, 연대 매핑
- [ ] 008 고서 코드 해석
- [ ] 판식정보 구조화
- [ ] API 키 기반 검색
```

커밋 없음 (확인만)

---

### 작업 2: KORMARC 008 코드 해석기

기존 KORCIS 매퍼에 008 필드 해석 로직을 추가한다:

```python
"""KORMARC 008 고서 코드 해석기.

KORMARC 008 필드의 각 위치별 코드를 사람이 읽을 수 있는 텍스트로 변환한다.
고서(古書) 레코드에 특화된 코드 테이블.
"""

# 간행연대구분 (위치 06)
PUBLICATION_DATE_TYPE = {
    "a": "확실한 간행연도",
    "b": "추정 간행연도",
    "c": "세기 단위",
    "d": "연대 미상",
    "e": "복수 연도 (시작~끝)",
}

# 언어코드 (위치 35-37)
LANGUAGE_CODES = {
    "chi": "중국어(한문)",
    "kor": "한국어",
    "jpn": "일본어",
    "mul": "다국어",
}

def parse_008_field(field_008: str) -> dict:
    """008 필드를 해석한다.

    입력: 40자 고정 길이 문자열
    출력: 해석된 딕셔너리
    """
    if not field_008 or len(field_008) < 40:
        return {"error": f"008 필드 길이 부족: {len(field_008) if field_008 else 0}자"}

    return {
        "date_type": PUBLICATION_DATE_TYPE.get(field_008[6], f"미확인({field_008[6]})"),
        "publication_year": field_008[7:11].strip("#"),
        "language": LANGUAGE_CODES.get(field_008[35:38], field_008[35:38]),
        "raw": field_008,
    }
```

테스트와 함께 구현하라.

커밋: `feat(parser): KORMARC 008 고서 코드 해석기`

---

### 작업 3: 판식정보 구조화 추출

서지 레코드의 판식정보(版式情報) 텍스트를 파싱하여 구조화한다:

```python
"""판식정보 파서.

입력 예: "四周雙邊 半郭 22.5×15.2cm 有界 10行20字 上下內向黑魚尾"
출력: {
    "광곽": "사주쌍변",
    "반곽_크기": {"가로": 22.5, "세로": 15.2, "단위": "cm"},
    "계선": "유계",
    "행자수": {"행": 10, "자": 20},
    "어미": "상하내향흑어미",
}

주의:
  - 판식정보의 형식은 표준화되어 있지 않아서 다양한 변형이 있다.
  - 정규식으로 주요 패턴을 매칭하고, 매칭 안 되는 부분은 원본 텍스트로 보존.
  - 완벽한 파싱보다 안전한 파싱 — 에러 없이 가능한 만큼만 추출.
"""

import re
from typing import Optional


def parse_pansik_info(text: str) -> dict:
    """판식정보 텍스트를 구조화된 딕셔너리로 변환한다.

    입력: 판식정보 원문 텍스트
    출력: 구조화된 딕셔너리 + 파싱하지 못한 나머지 텍스트
    """
    result = {"원문": text}
    remaining = text

    # 광곽 (匡郭)
    광곽_patterns = {
        r"四周雙邊": "사주쌍변",
        r"四周單邊": "사주단변",
        r"左右雙邊": "좌우쌍변",
    }
    for pattern, value in 광곽_patterns.items():
        if re.search(pattern, remaining):
            result["광곽"] = value
            remaining = re.sub(pattern, "", remaining)
            break

    # 반곽 크기
    size_match = re.search(r"(\d+\.?\d*)\s*[×x]\s*(\d+\.?\d*)\s*cm", remaining, re.IGNORECASE)
    if size_match:
        result["반곽_크기"] = {
            "세로": float(size_match.group(1)),
            "가로": float(size_match.group(2)),
            "단위": "cm",
        }
        remaining = remaining[:size_match.start()] + remaining[size_match.end():]

    # 계선 (界線)
    if "有界" in remaining:
        result["계선"] = "유계"
        remaining = remaining.replace("有界", "")
    elif "無界" in remaining:
        result["계선"] = "무계"
        remaining = remaining.replace("無界", "")

    # 행자수 (行字數)
    hj_match = re.search(r"(\d+)行\s*(\d+)字", remaining)
    if hj_match:
        result["행자수"] = {"행": int(hj_match.group(1)), "자": int(hj_match.group(2))}
        remaining = remaining[:hj_match.start()] + remaining[hj_match.end():]

    # 어미 (魚尾)
    어미_patterns = [
        (r"上下內向黑魚尾", "상하내향흑어미"),
        (r"上下白魚尾", "상하백어미"),
        (r"上下內向花紋魚尾", "상하내향화문어미"),
        (r"上黑魚尾", "상흑어미"),
    ]
    for pattern, value in 어미_patterns:
        if re.search(pattern, remaining):
            result["어미"] = value
            remaining = re.sub(pattern, "", remaining)
            break

    # 나머지 (파싱하지 못한 부분)
    remaining = remaining.strip().strip("半郭").strip()
    if remaining:
        result["기타"] = remaining

    return result
```

테스트와 함께 구현하라. 판식정보의 변형이 많으므로 여러 케이스를 테스트한다.

커밋: `feat(parser): 판식정보 구조화 추출 — 광곽, 행자수, 어미, 계선`

---

### 작업 4: KORCIS OpenAPI 연동

academic-mcp의 NLProvider 로직을 플랫폼의 KORCIS 파서로 이식한다.

**참조 파일 전체 경로**:
```
C:\Users\junto\Downloads\head-repo\claude\academic-mcp\src\academic_mcp\
  providers\base.py      ← BaseProvider 패턴
  providers\nl.py        ← NLProvider (KORCIS 검색/상세)
  config.py              ← Settings (.env에서 nl_api_key 로드)
  server.py              ← Provider 초기화 (api_key 주입)
  models\paper.py        ← Paper, PaperDetail 데이터 모델
```

```python
# 플랫폼의 BaseFetcher 패턴에 맞춰 구현

class KorcisFetcher(BaseFetcher):
    """한국고문헌종합목록 OpenAPI 데이터 수집기.

    참조: academic-mcp/src/academic_mcp/providers/nl.py
    
    ⚠️ API 키 필요: .env의 NL_API_KEY (또는 KORCIS_API_KEY)
    키 발급: https://www.data.go.kr/ 에서 "국립중앙도서관" 검색

    특징:
    - API 키 필요 (공공데이터포털 경유 발급)
    - 응답 형식: XML (ElementTree 파싱)
    - 검색 + 상세 조회 2단계
    """

    SEARCH_URL = "https://www.nl.go.kr/korcis/openapi/search.do"
    DETAIL_URL = "https://www.nl.go.kr/korcis/openapi/detail.do"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def is_available(self) -> bool:
        """API 키가 설정되어 있는지 확인."""
        return self.api_key is not None

    def fetch(self, query: str, max_results: int = 10) -> list[dict]:
        """검색 → 레코드 목록 반환."""
        if not self.is_available():
            raise ValueError("KORCIS API 키가 설정되지 않았습니다. .env에 NL_API_KEY를 추가하세요.")

        params = {
            "search_field": "total",
            "search_value": query,
            "page": "1",
            "display": str(max_results),
        }
        response = requests.get(self.SEARCH_URL, params=params)
        response.raise_for_status()
        return self._parse_search_xml(response.content)

    def fetch_detail(self, rec_key: str) -> dict:
        """상세 조회 → 서지 상세 정보 반환."""
        params = {"rec_key": rec_key}
        response = requests.get(self.DETAIL_URL, params=params)
        response.raise_for_status()
        return self._parse_detail_xml(response.content)

    def _parse_search_xml(self, xml_bytes: bytes) -> list[dict]:
        """검색 결과 XML 파싱.

        nl.py의 _parse_search_response() 참조.
        RECORD 요소에서:
          REC_KEY, TITLE, KOR_TITLE, AUTHOR, KOR_AUTHOR,
          PUBYEAR, PUBLISHER, EDIT_NAME, LIB_NAME 추출.
        """
        import xml.etree.ElementTree as ET
        records = []
        root = ET.fromstring(xml_bytes)
        for record in root.findall(".//RECORD"):
            records.append({
                "rec_key": _get_text(record, "REC_KEY"),
                "title": _get_text(record, "TITLE"),
                "kor_title": _get_text(record, "KOR_TITLE"),
                "author": _get_text(record, "AUTHOR"),
                "kor_author": _get_text(record, "KOR_AUTHOR"),
                "pub_year": _get_text(record, "PUBYEAR"),
                "publisher": _get_text(record, "PUBLISHER"),
                "edit_name": _get_text(record, "EDIT_NAME"),
                "lib_name": _get_text(record, "LIB_NAME"),
            })
        return records

    def _parse_detail_xml(self, xml_bytes: bytes) -> dict:
        """상세 정보 XML 파싱.

        nl.py의 _parse_detail_response() 참조.
        BIBINFO에서:
          TITLE_INFO, PUBLISH_INFO, EDITION_INFO,
          FORM_INFO(=판식정보 포함), NOTE_INFO 추출.
        HOLDINFO에서: 소장기관 목록 추출.

        FORM_INFO에 판식정보가 포함되어 있으면
        → 작업 3의 parse_pansik_info()로 구조화.
        """
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_bytes)
        bib = root.find(".//BIBINFO")
        if bib is None:
            return {}

        result = {
            "title_info": _get_text(bib, "TITLE_INFO"),
            "publish_info": _get_text(bib, "PUBLISH_INFO"),
            "edition_info": _get_text(bib, "EDITION_INFO"),
            "form_info": _get_text(bib, "FORM_INFO"),
            "note_info": _get_text(bib, "NOTE_INFO"),
        }

        # 소장기관
        hold_libs = []
        for hold in root.findall(".//HOLDINFO"):
            lib = _get_text(hold, "LIB_NAME")
            if lib and lib not in hold_libs:
                hold_libs.append(lib)
        result["hold_libs"] = hold_libs

        # FORM_INFO에서 판식정보 구조화 시도
        if result["form_info"]:
            result["pansik_parsed"] = parse_pansik_info(result["form_info"])

        return result


def _get_text(element, tag: str) -> str:
    """XML 요소 텍스트 추출. nl.py와 동일한 헬퍼."""
    if element is None:
        return ""
    child = element.find(tag)
    if child is None or not child.text:
        return ""
    return child.text.strip()
```

nl.py와의 차이점:
- nl.py는 async + httpx → 플랫폼은 동기 requests (기존 패턴 따름)
- nl.py는 Paper/PaperDetail 모델 → 플랫폼은 bibliography.schema.json 매핑
- nl.py의 `is_available()`은 키 체크 없이 True 반환 → 플랫폼에서는 키 체크 필수
- FORM_INFO 필드에서 판식정보 자동 구조화 (작업 3의 parse_pansik_info 연결)

.env에 추가:
```env
# KORCIS (한국고문헌종합목록) API 키
# 발급: https://www.data.go.kr/ 에서 "국립중앙도서관" 검색
NL_API_KEY=your_key_here
```

커밋: `feat(parser): KORCIS OpenAPI 연동 — 검색 + 상세 조회 (API 키 필요)`

---

### 작업 5: 기존 매퍼에 통합 + 테스트

기존 KORCIS 매퍼에 작업 2~4의 결과를 통합한다:

1. 서지 레코드 매핑 시 008 필드 자동 해석
2. 판식정보 텍스트 자동 구조화
3. 기존 스키마 (bibliography.schema.json 등)와 호환 확인

```bash
uv run pytest tests/test_korcis*.py -v
```

최종 커밋: `feat: Phase 10-4 완료 — KORCIS 파서 고도화`

---

### 작업 6: GUI 라이트그레이 테마 추가

현재 GUI에 다크그레이(VSCode 스타일) 테마만 있다. 라이트그레이 테마를 추가한다.

#### 6-A: 현재 테마 구조 확인

먼저 기존 CSS 구조를 확인하라:

```bash
# 기존 테마 관련 CSS 변수/클래스 찾기
grep -rn "color\|background\|theme\|--" static/css/ | head -50
grep -rn "dark\|theme" static/js/ | head -20
```

기존 다크 테마가 CSS 변수(`:root { --bg-primary: ... }`)를 쓰고 있는지,
하드코딩된 색상값인지에 따라 접근이 달라진다.

#### 6-B: 라이트그레이 색상 팔레트

```css
/* 라이트그레이 테마 — CSS 변수 정의 */

[data-theme="light"] {
  /* 배경 */
  --bg-primary: #FAFAFA;       /* 메인 배경 */
  --bg-secondary: #F5F5F5;     /* 사이드바, 패널 배경 */
  --bg-tertiary: #EEEEEE;      /* 호버, 선택 상태 */
  --bg-elevated: #FFFFFF;       /* 카드, 모달 */

  /* 텍스트 */
  --text-primary: #333333;      /* 본문 */
  --text-secondary: #666666;    /* 부제목, 레이블 */
  --text-muted: #999999;        /* 비활성, 힌트 */

  /* 테두리 */
  --border-primary: #E0E0E0;    /* 주요 구분선 */
  --border-secondary: #EEEEEE;  /* 약한 구분선 */

  /* 강조색 — 기존 다크 테마의 강조색을 유지하되 명도 조정 */
  --accent-primary: #1976D2;    /* 주 강조 (파란 계열) */
  --accent-hover: #1565C0;      /* 호버 */
  --accent-bg: #E3F2FD;         /* 강조 배경 (연파랑) */

  /* 상태 색상 */
  --success: #2E7D32;
  --warning: #F57F17;
  --error: #C62828;
  --info: #0277BD;

  /* 그림자 — 라이트 테마에서는 그림자가 더 눈에 띄므로 부드럽게 */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.06);
  --shadow-md: 0 2px 8px rgba(0, 0, 0, 0.08);
  --shadow-lg: 0 4px 16px rgba(0, 0, 0, 0.10);

  /* 코드/에디터 영역 — 약간 다른 배경으로 구분 */
  --editor-bg: #FFFFFF;
  --editor-gutter: #F5F5F5;
  --editor-line-highlight: #F0F7FF;

  /* 한문 텍스트 전용 — 가독성 최우선 */
  --text-classical: #1A1A1A;    /* 원문은 좀 더 진하게 */
  --annotation-bg: #FFF8E1;     /* 현토/주석 배경 (연노랑) */
}
```

#### 6-C: 테마 전환 구현

```javascript
// static/js/theme-switcher.js (또는 기존 settings 패널에 통합)

class ThemeSwitcher {
    constructor() {
        // 저장된 테마 불러오기 (기본값: dark)
        this.currentTheme = localStorage.getItem('app-theme') || 'dark';
        this.apply(this.currentTheme);
    }

    toggle() {
        const next = this.currentTheme === 'dark' ? 'light' : 'dark';
        this.apply(next);
    }

    apply(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('app-theme', theme);
        this.currentTheme = theme;

        // 토글 버튼 아이콘 업데이트
        const btn = document.getElementById('theme-toggle');
        if (btn) {
            btn.textContent = theme === 'dark' ? '☀️' : '🌙';
            btn.title = theme === 'dark' ? '라이트 모드로 전환' : '다크 모드로 전환';
        }
    }
}

// 초기화
const themeSwitcher = new ThemeSwitcher();
```

#### 6-D: 토글 버튼 위치

헤더 우측에 테마 전환 버튼 추가:

```html
<!-- 헤더 우측, 기존 버튼들 옆 -->
<button id="theme-toggle"
        onclick="themeSwitcher.toggle()"
        class="theme-toggle-btn"
        title="테마 전환">
    🌙
</button>
```

```css
.theme-toggle-btn {
    background: none;
    border: 1px solid var(--border-primary);
    border-radius: 4px;
    padding: 4px 8px;
    cursor: pointer;
    font-size: 16px;
    transition: background 0.2s;
}
.theme-toggle-btn:hover {
    background: var(--bg-tertiary);
}
```

#### 6-E: 기존 CSS 마이그레이션

기존 하드코딩된 색상을 CSS 변수로 전환해야 한다:

```css
/* 변환 전 (다크 테마 하드코딩) */
.sidebar { background: #1E1E1E; color: #CCCCCC; }

/* 변환 후 (CSS 변수 사용) */
.sidebar { background: var(--bg-secondary); color: var(--text-primary); }
```

⚠️ 주의:
- 한 번에 전부 바꾸지 말고, 영역별로 (헤더 → 사이드바 → 메인 패널 → 에디터) 순서대로 진행
- 변환할 때마다 다크/라이트 모두에서 확인
- 한문 텍스트 표시 영역은 가독성 테스트 필수 (작은 글자가 연한 배경에서 잘 보이는지)

테스트:
1. 다크 → 라이트 → 다크 전환 시 깜빡임 없이 전환되는지
2. 새로고침 후 선택한 테마가 유지되는지
3. 모든 페이지(레이아웃, 교정, 뷰어, 설정)에서 라이트 테마 정상 표시
4. 대조 뷰의 색상(exact 초록, variant 노랑, mismatch 빨강)이 라이트 배경에서 잘 구분되는지

커밋: `feat(gui): 라이트그레이 테마 추가 — 다크/라이트 전환 지원`

---

## 체크리스트

- [ ] 기존 KORCIS 파서의 현재 상태 파악 완료
- [ ] KORMARC 008 코드 해석기 동작
- [ ] 판식정보 구조화 추출 동작 (주요 패턴 매칭)
- [ ] KORCIS OpenAPI 연동 (API 키 필요)
- [ ] 기존 테스트 통과 유지
- [ ] 새 테스트 통과
- [ ] GUI 라이트그레이 테마 동작 + 전환 토글
- [ ] 다크/라이트 모두에서 전체 페이지 확인
- [ ] `docs/phase10_12_design.md`의 Phase 10-4에 "✅ 완료" 표시

---

## ⏭️ 다음 세션: Phase 11-1 — 끊어읽기·현토 편집기 (L5)

```
이 세션(10-4)이 완료되면 (또는 건너뛰면) Phase 11로 넘어간다.

Phase 10 전체에서 만든 것:
  ✅ 10-2: LLM 4단 폴백 아키텍처 + 레이아웃 분석
  ✅ 10-1: OCR 엔진 연동 (PaddleOCR)
  ✅ 10-3: 정렬 엔진 (OCR ↔ 텍스트 대조)
  ✅ 10-4: KORCIS 파서 고도화 (선택)

⚠️ Phase 11-1은 혜원의 전문 영역과 직결된다.
   세션 시작 전에 아래 사항을 혜원과 확인해야 한다:

   1. 현토 토의 분류 체계 (임규직 3분류 기본? 확장?)
   2. 삽입 위치 표현 방식 (글자 뒤? 위? 아래?)
   3. 여러 현토안 병렬 표현 방법
   4. 구두점과 현토의 관계
   5. 편집기 UX 선호도
   6. dansa-research와의 연동

세션 문서: phase11_1_hyeonto_session.md (확인 후 작성)
```
