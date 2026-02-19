# 고전 텍스트 디지털 서고 플랫폼

물리적 원본(PDF/이미지)과 디지털 텍스트의 연결이 끊어지지 않는,
사람과 LLM이 함께 고전 텍스트를 읽고 번역하고 연구하는 **통합 작업 환경**.

개발자의 VSCode처럼, 연구자가 이 안에서 이미지 열람, 레이아웃 분석,
OCR, 교정, 번역, 주석 작업을 모두 수행합니다.

## 주요 기능

### 원본 관리 (L1~L3)
- **PDF/이미지 뷰어** — PDF.js 기반, 페이지 탐색·확대·축소
- **레이아웃 분석** — LLM 비전으로 텍스트 영역(LayoutBlock) 자동 감지, 수동 편집
- **OCR** — LLM 비전 기반 고전 한문 텍스트 인식 (세로쓰기, 이체자 대응)
- **PaddleOCR** — 오프라인 OCR 엔진 (GPU 없이도 동작, 선택 설치)
- **HWP/HWPX 가져오기** — 한글 파일에서 텍스트 추출, 표점·현토 자동 분리, 대두 감지

### 해석 작업 (L5~L7)
- **표점(句讀)** — 고전 한문에 구두점 삽입, LLM 자동 제안 + 수동 편집
- **현토(懸吐)** — 한문에 한국어 토 달기
- **번역** — LLM 자동 번역 + 수동 교정, Draft → 확정 워크플로우
- **주석** — 인물·사건·전거 등 주석 작성, LLM 자동 태깅

### 교정·비교
- **글자 단위 대조** — OCR 결과와 교정본을 글자별로 정렬·비교
- **이체자 사전** — 이체자/약자 매핑 관리

### 저장소 관리
- **원본 저장소 + 해석 저장소** 분리 — 각각 독립적인 Git 저장소
- **원격 저장소 설정** — GitHub 등 원격 URL 설정, Push/Pull
- **Git 그래프** — 커밋 히스토리 시각화

### LLM 연동
- **다중 프로바이더** — Base44 Bridge, Ollama, Anthropic, Gemini, OpenAI
- **자동 폴백** — 1순위 실패 시 차순위 프로바이더로 자동 전환
- **비전 모델 필터링** — OCR/레이아웃은 비전 지원 모델만 표시

## 기술 스택

| 영역 | 기술 |
|------|------|
| 백엔드 | Python + FastAPI |
| 프론트엔드 | HTML + vanilla JS + CSS (빌드 도구 없음) |
| PDF 렌더링 | PDF.js |
| 이미지 처리 | Pillow, PyMuPDF |
| OCR 엔진 | LLM 비전 + PaddleOCR (선택) |
| HWP 처리 | python-hwpx, olefile |
| LLM 라우터 | 자체 구현 (Base44, Ollama, Anthropic, Gemini, OpenAI) |
| 버전 관리 | GitPython |
| 스키마 검증 | jsonschema |
| 패키지 관리 | uv |

## 설치

[uv](https://docs.astral.sh/uv/)를 사용합니다.

```bash
# 저장소 클론
git clone https://github.com/hw725/classical-text-platform.git
cd classical-text-platform

# 의존성 설치 (.venv 자동 생성)
uv sync

# 개발 의존성 포함 설치
uv sync --group dev

# (선택) PaddleOCR 오프라인 엔진 설치 (~500MB)
uv sync --extra paddleocr
```

## 사용법

### CLI (서고 관리)

```bash
# 서고 초기화
uv run python -m cli init-library <경로>

# 문헌 등록 (PDF/이미지를 L1_source에 복사)
uv run python -m cli add-document <서고경로> --title "蒙求" --doc-id monggu

# 문헌 목록 확인
uv run python -m cli list-documents <서고경로>
```

### 웹 서버

```bash
# 서버 실행 (기본 포트 8765)
uv run python -m app serve --library <서고경로>

# 포트 변경
uv run python -m app serve --library <서고경로> --port 8080
```

서버 실행 후 `http://localhost:8765`에서 웹 UI에 접속합니다.

### 작업 워크플로우

1. **문헌 선택** — 좌측 사이드바에서 문헌 → 권 → 페이지 선택
2. **레이아웃 분석** — 레이아웃 모드에서 "AI 분석" 클릭 → 텍스트 영역 자동 감지 → L3에 자동 저장
3. **OCR** — 레이아웃 모드에서 "전체 OCR" 또는 "선택 블록 OCR" 클릭 → LLM 비전으로 글자 인식
4. **HWP 가져오기** — 사이드바 "HWP" 버튼 → 파일 선택 → 미리보기 → 표점·현토 분리 옵션 설정 → 가져오기
5. **교정** — 교정 모드에서 "OCR 채우기" → OCR 결과를 텍스트로 변환 → 글자 단위 교정
6. **해석** — 표점 → 현토 → 번역 → 주석 순서로 작업

### LLM 프로바이더 설정

| 프로바이더 | 설정 방법 | 비전 지원 |
|-----------|----------|----------|
| Base44 Bridge | 자동 (Node.js 서브프로세스) | O |
| Ollama | `http://localhost:11434` (로컬 또는 클라우드 프록시) | 모델 의존 |
| Anthropic | 환경변수 `ANTHROPIC_API_KEY` | O (유료) |
| Gemini | 환경변수 `GEMINI_API_KEY` | O |
| OpenAI | 환경변수 `OPENAI_API_KEY` | O |

OCR/레이아웃 분석에는 비전 지원 모델만 사용 가능합니다.
드롭다운에서 눈 아이콘(👁)이 있는 모델이 비전 지원 모델입니다.

## 프로젝트 구조

```
classical-text-platform/
├── docs/                  # 설계 문서
│   ├── platform-v7.md     #   8층 모델, Git 저장소, 전체 아키텍처
│   ├── core-schema-v1.3.md#   해석 저장소의 엔티티 모델
│   ├── operation-rules-v1.0.md # 코어 스키마 운영 규약
│   └── DECISIONS.md       #   설계 결정 기록
├── src/
│   ├── core/              #   핵심 로직 (표점, 번역, 주석 등)
│   ├── hwp/               #   HWP/HWPX 파일 처리 (텍스트 추출, 표점·현토 분리)
│   ├── llm/               #   LLM 라우터 + 프로바이더 (Base44, Ollama, Anthropic, Gemini, OpenAI)
│   ├── ocr/               #   OCR 엔진 (LLM 비전 + PaddleOCR) + 이미지 전처리
│   ├── parsers/           #   서지정보 파서
│   ├── cli/               #   CLI 도구 (자동화/스크립팅)
│   └── app/               #   웹 앱 (GUI — 주 인터페이스)
│       ├── server.py      #     FastAPI 서버 (모든 API 엔드포인트)
│       └── static/        #     정적 파일 (CSS, JS)
├── schemas/
│   ├── source_repo/       #   원본 저장소 JSON 스키마
│   └── core/              #   코어 스키마 (해석 저장소)
├── examples/              # 예제 서고 (monggu_library)
├── resources/             # 공유 리소스 (block_types 등)
├── pyproject.toml         # 프로젝트 설정 및 의존성
└── CLAUDE.md              # 프로젝트 규칙 및 코딩 가이드
```

## 8층 데이터 모델

| 층 | 이름 | 설명 | 저장소 |
|----|------|------|--------|
| L1 | 원본 파일 | PDF/이미지 원본 | 원본 |
| L2 | OCR 결과 | 글자 인식 결과 | 원본 |
| L3 | 레이아웃 | 페이지 영역 구분 | 원본 |
| L4 | 서지정보 | 제목, 저자 등 메타데이터 | 원본 |
| L5 | 표점/현토 | 구두점, 한국어 토 | 해석 |
| L6 | 번역 | 현대어 번역 | 해석 |
| L7 | 주석 | 인물, 사건, 전거 주석 | 해석 |
| L8 | 관계 | 엔티티 간 관계 그래프 | 해석 |

## 설계 문서

자세한 아키텍처와 설계 결정은 `docs/` 폴더를 참고하세요:

- **platform-v7.md** — 8층 데이터 모델, 원본·해석 저장소 분리, 전체 아키텍처
- **core-schema-v1.3.md** — 해석 저장소(5~8층)의 엔티티 모델
- **operation-rules-v1.0.md** — 코어 스키마 운영 규약
- **DECISIONS.md** — 주요 설계 결정과 근거

## 라이선스

미정 (DECISIONS.md 미결 사항 참고)
