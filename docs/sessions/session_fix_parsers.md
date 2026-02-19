# 세션: 서지정보 파서 보완 — URL 자동 인식 + KORCIS

Phase 9까지 완료된 상태다. Phase 10으로 넘어가기 전에 Phase 5의 미완성 부분을 수선한다.

## 문제

현재 서지정보 가져오기는 "파서 선택 → 키워드 검색 → 결과 선택 → 매핑"이라는 수동 4단계다.
**의도한 동작**은 이것이다:

1. 연구자가 URL을 붙여넣는다
2. 앱이 URL 패턴을 보고 어느 소스인지 자동 판별한다
3. 해당 페이지에서 메타데이터를 가져온다
4. bibliography.json에 자동 채운다

키워드 검색도 여전히 필요하지만, **URL 붙여넣기가 주 워크플로우**여야 한다.
또한 KORCIS(한국고문헌종합목록) 파서가 아예 없다.

## 현재 파일 구조 (확인 필요)

```
src/parsers/
  base.py              — BaseFetcher, BaseMapper, 레지스트리 (완성)
  ndl.py               — NDL Search OpenSearch API (완성)
  archives_jp.py       — 일본 국립공문서관 HTML 스크래핑 (완성)
  registry.json        — 파서 메타정보 (KORCIS 없음)
  __init__.py
```

```
src/app/server.py 관련 API:
  GET  /api/parsers                      — 파서 목록 (완성)
  POST /api/parsers/{parser_id}/search   — 키워드 검색 (완성)
  POST /api/parsers/{parser_id}/map      — 매핑 (완성)
  ❌ URL → 자동 판별 → fetch → map 엔드포인트 없음
```

## 작업 목록

### 작업 1: URL 자동 판별 + fetch 엔드포인트

src/parsers/base.py에 URL 패턴 매칭 함수를 추가한다:

```python
def detect_parser_from_url(url: str) -> str | None:
    """URL 패턴으로 어느 파서를 쓸지 자동 판별한다.
    
    매칭 규칙:
      - ndlsearch.ndl.go.jp, dl.ndl.go.jp, id.ndl.go.jp → "ndl"
      - digital.archives.go.jp → "japan_national_archives"
      - korcis.nl.go.kr → "korcis"
      - None → 인식할 수 없는 URL
    """
```

각 Fetcher에 `fetch_by_url(url)` 메서드를 추가한다:
- URL에서 ID를 추출하고 fetch_detail을 호출
- NDL: URL에서 NDLBibID 추출 → fetch_detail
- 국립공문서관: URL 자체가 상세 페이지이므로 바로 파싱
- KORCIS: URL에서 자료 ID 추출 → 파싱

server.py에 새 엔드포인트를 추가한다:

```
POST /api/bibliography/from-url
  입력: { "url": "https://..." }
  처리:
    1. detect_parser_from_url(url) → parser_id
    2. fetcher.fetch_by_url(url) → raw_data
    3. mapper.map_to_bibliography(raw_data) → bibliography
  출력: { "parser_id": "ndl", "bibliography": {...} }
  에러: URL을 인식할 수 없으면 → 지원하는 소스 목록 안내
```

### 작업 2: KORCIS 파서 신규 작성

src/parsers/korcis.py를 새로 만든다.

대상: 국립중앙도서관 한국고문헌종합목록
URL 패턴: https://korcis.nl.go.kr/

먼저 실제 사이트를 확인해야 한다:
- korcis.nl.go.kr에 접속해서 검색 결과 페이지와 상세 페이지의 HTML 구조를 확인
- API가 있는지 확인 (네트워크 탭에서 XHR 요청 확인)
- 없으면 HTML 스크래핑 (archives_jp.py 패턴 참고)

KorcisFetcher:
- search(query) → 검색 결과 목록
- fetch_detail(item_id) → 상세 메타데이터
- fetch_by_url(url) → URL에서 직접 메타데이터 추출

KorcisMapper:
- map_to_bibliography(raw_data) → bibliography.json 형식

매핑 시 한국 고문헌 특성 고려:
- 저자(creator): 한자명 + 한글 독음이 있을 수 있음
- 판종(edition_type): 목판본, 활자본, 필사본 등 한국 고유 어휘
- 소장처(repository): 국립중앙도서관 등

registry.json에 KORCIS 항목을 추가한다.

### 작업 3: NDL 파서에 fetch_by_url 추가

src/parsers/ndl.py의 NdlFetcher에 추가:

```python
async def fetch_by_url(self, url: str) -> dict[str, Any]:
    """NDL URL에서 NDLBibID를 추출하여 상세 정보를 가져온다.
    
    지원 URL 패턴:
      - https://ndlsearch.ndl.go.jp/books/R...
      - https://dl.ndl.go.jp/info:ndljp/pid/...
      - https://id.ndl.go.jp/bib/...
    """
```

### 작업 4: 국립공문서관 파서에 fetch_by_url 추가

src/parsers/archives_jp.py의 ArchivesJpFetcher에 추가:

```python
async def fetch_by_url(self, url: str) -> dict[str, Any]:
    """국립공문서관 URL에서 직접 메타데이터를 추출한다.
    
    URL이 상세 페이지이면 바로 파싱, 아니면 적절한 상세 페이지로 이동.
    """
```

### 작업 5: GUI 연동

서지정보 패널(사이드바 또는 문서 상세)에 URL 입력 기능을 추가한다.

현재 GUI에 서지정보 관련 UI가 어떻게 되어 있는지 먼저 확인하라:
- src/app/static/ 아래의 HTML/JS 파일을 읽어봐
- "서지정보", "bibliography", "parser" 관련 코드를 찾아봐

추가할 UI:
1. URL 입력 필드 + "가져오기" 버튼
   - URL 붙여넣기 → "가져오기" 클릭
   - POST /api/bibliography/from-url 호출
   - 결과를 서지정보 폼에 자동 채움
   - 인식할 수 없는 URL이면 에러 메시지 + 지원 소스 안내

2. 기존 키워드 검색도 유지
   - "직접 검색" 버튼 또는 탭
   - 파서 선택 → 키워드 입력 → 검색 → 선택 → 채움

3. 자동 채움 후 수동 편집 가능
   - 빈 필드는 [미입력]으로 표시
   - 연구자가 직접 수정 가능

### 작업 6: from-url을 문서에 바로 저장하는 편의 엔드포인트

```
POST /api/documents/{doc_id}/bibliography/from-url
  입력: { "url": "https://..." }
  처리:
    1. URL에서 bibliography 생성
    2. 해당 문서의 bibliography.json에 저장
    3. git commit
  출력: { "status": "saved", "parser_id": "ndl", "bibliography": {...} }
```

이것으로 연구자의 워크플로우가 된다:
문서 선택 → URL 붙여넣기 → 가져오기 → 끝 (1단계)

## 작업 방식

CLAUDE.md의 "CLI를 적극 활용할 것" 규칙을 따른다. 이 세션에서 특히:

- KORCIS 파서 작성 전에 `curl https://korcis.nl.go.kr/...` 로 실제 HTML 구조를 확인하라
- NDL/국립공문서관의 fetch_by_url을 구현한 후, 실제 URL로 테스트하라
- `POST /api/bibliography/from-url` 엔드포인트를 만들면 서버를 띄우고 curl로 직접 호출해서 응답을 확인하라
- "될 것 같다"로 끝내지 말고, 실제 URL을 넣어서 동작하는 것을 보여줘라

## 확인 사항

각 파서 테스트:
1. NDL: "蒙求"로 검색 → 결과 확인, NDL URL 붙여넣기 → 자동 채움 확인
2. 국립공문서관: 실제 URL 붙여넣기 → 자동 채움 확인
3. KORCIS: 실제 URL 붙여넣기 → 자동 채움 확인

커밋: "fix: 서지정보 파서 보완 — URL 자동 인식 + KORCIS 파서 추가"
