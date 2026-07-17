# 프로젝트: 고전서지 통합 브라우저 (Classical Text Browser)

## 프로젝트 비전
물리적 원본(PDF/이미지)과 디지털 텍스트의 연결이 끊어지지 않는,
사람과 LLM이 함께 고전 텍스트를 읽고 번역하고 연구하는 통합 작업 환경.

개발자의 VSCode처럼, 연구자가 이 안에서 이미지 열람, 레이아웃 분석,
OCR, 교정, 번역, 주석 작업을 모두 수행한다.

## 설계 문서
- docs/platform-v7.md — 8층 모델, Git 저장소, 전체 아키텍처
- docs/core-schema-v1.3.md — 해석 저장소의 엔티티 모델
- docs/operation-rules-v1.0.md — 코어 스키마 운영 규약
- docs/DECISIONS.md — 설계 결정 기록 (반드시 읽을 것)
- docs/observability-roadmap.md — 관측 가능성(OpenTelemetry) 점진적 도입 로드맵
- docs/retrospective/ — 회고용 뷰 (원본 무수정). 결정·세션·패턴·하네스 권고 + 인터랙티브 뷰어

## 기술 스택
- 백엔드: Python + FastAPI
- 프론트엔드: HTML + vanilla JS + CSS (빌드 도구 없음)
- PDF 렌더링: PDF.js
- 버전관리: GitPython
- 스키마 검증: jsonschema
- 패키지 관리: uv (pip 사용 금지)
  - 패키지 추가: uv add <패키지명>
  - 개발 의존성: uv add --dev <패키지명>
  - 실행: uv run python -m <모듈>
  - uv.lock은 git에 포함

## 백엔드 모듈 구조 (src/app/)
server.py는 FastAPI 앱 생성 + 라우터 마운트만 담당하는 조립 파일(~85줄).
실제 API 엔드포인트는 8개 라우터 모듈에 분산:

```
src/app/
├── server.py            ← 앱 생성 + 라우터 마운트 + configure()
├── _state.py            ← 공유 상태 + 헬퍼 + LLM 프롬프트/캐시/동적 토큰 계산
├── __main__.py          ← CLI 진입점 (python -m app serve)
└── routers/
    ├── library.py       ← 서고/설정/백업/휴지통 (15 라우트)
    ├── documents.py     ← 문헌 CRUD/페이지/교정/서지/파서 (34 라우트)
    ├── interpretations.py ← 해석 CRUD/레이어/의존/엔티티 (23 라우트)
    ├── llm_ocr.py       ← LLM 상태·분석·초안 + OCR 엔진·실행 (14 라우트)
    ├── alignment.py     ← 이체자 사전/정렬/일괄교정 (17 라우트)
    ├── reading.py       ← L5 표점·현토 + L6 번역 + 비고 + AI보조 (25 라우트)
    ├── annotation.py    ← L7 주석·사전형·인용마크 + AI보조 (34 라우트)
    └── version.py       ← Git 그래프/되돌리기/스냅샷/가져오기 (7 라우트)
```

- 라우터 간 직접 import 금지. 공유 상태는 반드시 _state.py를 통해 접근.
- 새 엔드포인트 추가 시 해당 도메인의 라우터 파일에 추가할 것.
- Pydantic 모델은 사용하는 라우터 파일 내부에 정의.

## 코딩 규칙
- 이 프로젝트의 사용자는 비개발자 인문학 연구자다
- 코드 주석은 한국어로, 상세하게, "왜 이렇게 하는지" 포함
- 함수마다 docstring에 입력/출력/목적 설명
- UTF-8 인코딩, LF 줄바꿈
- JSON 파일은 jsonschema로 검증
- 에러 메시지는 한국어로, 원인과 해결책 포함
- primary_data/ 또는 L1_source/ 내의 원본 파일은 절대 수정 금지

## 용어 규칙 (혼동 방지)
- LayoutBlock: 원본 저장소 L3의 페이지 영역 (OCR 읽기 순서 단위)
- OcrResult: 원본 저장소 L2의 OCR 인식 결과
- TextBlock: 코어 스키마의 해석용 텍스트 단위 (source_ref로 원본 추적)
- "Block"이라고만 쓰지 말고 항상 위 세 이름 중 하나를 사용할 것

## 작업 방식: CLI를 적극 활용할 것
- 코드를 작성한 뒤 반드시 실행해서 확인하라. 작성만 하고 검증 없이 넘어가지 마라.
- API 엔드포인트를 만들면 curl이나 테스트 스크립트로 직접 호출해서 응답을 확인하라.
- 웹 스크래핑 파서를 작성할 때는 대상 사이트의 HTML 구조를 먼저 curl/wget으로 가져와서 확인하라.
- JSON 파일을 생성하면 jsonschema로 검증하라.
- 테스트를 작성했으면 실행해서 통과하는지 확인하라.
- "될 것 같다"로 끝내지 말고, 실제로 동작하는 것을 보여줘라.

## Git 커밋 규칙
형식: <타입>: <설명>
타입: feat / fix / data / docs / refactor / test
예시: feat: Phase 2 — 서고 초기화 CLI 구현

## 인지 부채 지도

> 2026-07-04 감사. AI 작성 코드와 사용자 이해의 간극 요약. 상세·퀴즈: 루트 cognitive-debt-audit.html

### 실제 하는 일 (문서에 없는 층위)
- "서버 시작" = 최대 3개 프로세스: start_server.bat가 uvicorn 외에 OpenAI OAuth 프록시
  (`npx -y openai-oauth`, 포트 10531–10540 스캔, Bearer 토큰 `oauth-proxy` 하드코딩)와
  SikuRoBERTa 표점 Docker(punctuation-service/.env 존재 시)를 자동 기동.
- 코드 총 77,344줄 중 프론트(static/)가 약 30,000줄 — index.html 4,477줄 단일 파일,
  workspace.css 6,826줄, JS 에디터 20여 개. 테스트 28파일은 전부 백엔드, 프론트 테스트 0, CI 없음.

### 안다고 착각하기 쉬운 지점
1. ~~`src/app/_state.py`에 `_parse_llm_json`이 **두 번 정의**~~ → **해소됨(ee8db13)**, 아래
   "인지부채 해소 반영" 참조. 현재는 단일 정의다.
2. ~~LLM 응답이 잘리면 조용히 부분 결과 반환~~ → **해소됨(56000f8·b91f3ef)**: `_truncated`
   플래그가 UI 경고로 노출된다. 아래 "인지부채 해소 반영" 참조.
3. LLM 결과 캐시(TTL 600초·최대 256건, _state.py:317) — 같은 텍스트 재요청 시 10분간
   옛 결과가 돌아올 수 있음.
4. "가져오기" 버튼의 "준비중"은 UI만 봉인(D-037). hwp-import.js 1,034줄과 백엔드
   엔드포인트(`/api/documents/import-hwp` 등)는 살아 있음 — 재구현하지 말고 복원할 것.
5. 서지 파서 5종(`src/parsers/` korcis 1,807줄·archives_jp·kyujanggak·kostma·ndl)은 외부
   사이트 HTML 구조 의존 — 사이트 개편 시 침묵 파손. 테스트가 실제 네트워크를 안 타면 못 잡음.
6. `llm_usage_log.jsonl`은 서고 루트에, 서고 미설정 시 `~/.classical-text-browser/`에 기록 —
   예산(MONTHLY_BUDGET_USD) 추적이 서고별로 분산됨.

### 인지 부채 핫스팟 (위험 순)
| 순위 | 경로 | 위험 |
|---|---|---|
| 1 | `src/app/_state.py` (968줄) | 전역 상태+프롬프트+캐시+JSON 파서 응집, 중복 정의 잠복 |
| 2 | `src/app/static/` 프론트 모놀리스 | 테스트 0·CI 없음, index.html 4,477줄 수정 회귀 감지 불가 |
| 3 | `start_server.bat` | 암묵 부수효과 3종(프록시·Docker·포트 스캔), 실패 시 원인 추적 곤란 |
| 4 | `src/parsers/` 5종 | 외부 사이트 의존 침묵 파손 |
| 5 | 봉인된 HWP 가져오기 경로 | 존재를 모르면 중복 재구현, 알면 onclick 복원만으로 재개 |

## ✅ 인지부채 해소 반영 (2026-07-07)

> 위 "인지 부채 지도"의 일부 항목이 실제 코드 수정으로 해소되었다. 아래는 문제 → 해소, 커밋해시.

- `_state.py`의 `_parse_llm_json` 이중 정의(앞 정의가 `# type: ignore[no-redef]` 뒤 정의에 shadow되던 호출 불가 죽은 코드) → 앞 정의 제거, AST로 단일 정의 확인. 커밋 `ee8db13`. (위 "안다고 착각하기 쉬운 지점" 1번 → 해소됨. 단, 지도 본문의 행번호 775·906은 수정 이전 스냅샷 기준.)
- 잘린 LLM 응답 복구 시 `_truncated` 플래그로 조용한 부분 결과 누락 방지 → 플래그 도입. 커밋 `56000f8`. (위 "안다고 착각하기 쉬운 지점" 2번의 조용한 부분 반환 위험 완화.)
