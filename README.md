# 고전 텍스트 디지털 서고 플랫폼

물리적 원본(PDF/이미지)과 디지털 텍스트의 연결이 끊어지지 않는,
사람과 LLM이 함께 고전 텍스트를 읽고 번역하고 연구하는 **통합 작업 환경**.

개발자의 VSCode처럼, 연구자가 이 안에서 이미지 열람, 레이아웃 분석,
OCR, 교정, 번역, 주석 작업을 모두 수행합니다.


## 핵심 개념

### 원문의 구성 요소

고전 텍스트 원본에는 여러 종류의 텍스트가 공존합니다. 이 플랫폼에서는 이들을 명확히 구분합니다:

| 구분 | 설명 | 예시 | 플랫폼에서의 위치 |
|------|------|------|-------------------|
| **본문(本文)** | 저자가 쓴 원래 텍스트. 작품의 핵심 내용. | 蒙求 본문: "王戎簡要 裴楷清通" | LayoutBlock `block_type: main_text` |
| **원주(原注/舊注)** | 원저자 또는 동시대 주석자가 붙인 주석. 원본에 이미 포함된 것. | 蒙求 구주: "裴楷字叔則 清通..." | LayoutBlock `block_type: annotation` |
| **역주(譯注)** | 현대 연구자(번역자)가 새로 작성하는 주석. 원본에는 없는 것. | "王戎(234-305)은 竹林七賢의 한 사람으로..." | 해석 저장소 L7 주석 |

**본문**과 **원주**는 원본 이미지에 물리적으로 존재하며, L3 레이아웃 분석에서 LayoutBlock으로 구분됩니다.
**역주**는 연구자가 해석 저장소(L7)에 새로 작성하는 것으로, 원본 저장소에는 없습니다.

### 원본 저장소와 해석 저장소

```
원본 저장소 (Source Repository)          해석 저장소 (Interpretation Repository)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━          ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
L1: 원본 파일 (PDF/이미지)               TextBlock (편성된 논리적 텍스트 단위)
L2: OCR 결과                             L5: 표점(句讀) + 현토(懸吐)
L3: 레이아웃 (LayoutBlock)               L6: 번역
L4: 교정된 텍스트 + 교정 기록            L7: 역주 (연구자가 새로 작성)
                                         L8: 관계 (엔티티 간 연결)

※ 각각 독립 Git 저장소로 관리
※ 원본 저장소는 수정 불가 (교정 기록은 별도 파일)
※ 해석 저장소는 원본 저장소를 source_ref로 참조
```

### 작업 단위: LayoutBlock과 TextBlock

- **LayoutBlock** (L3): 원본 이미지의 물리적 영역. OCR과 교정의 단위.
- **TextBlock** (해석 저장소): 해석 작업의 논리적 단위. 표점·현토·번역의 단위.

편성(Composition) 단계에서 LayoutBlock을 TextBlock으로 변환합니다:
- 1:1 매핑 (가장 흔함): LayoutBlock 하나 = TextBlock 하나
- 합치기: 여러 LayoutBlock의 텍스트를 하나의 TextBlock으로 결합
- 쪼개기: 하나의 LayoutBlock에서 본문과 원주를 분리하여 별도 TextBlock으로


## 주요 기능

### 원본 관리 (L1~L4)
- **PDF/이미지 뷰어** — PDF.js 기반, 페이지 탐색·확대·축소
- **레이아웃 분석** — LLM 비전으로 텍스트 영역(LayoutBlock) 자동 감지, 수동 편집
- **OCR** — LLM 비전 기반 고전 한문 텍스트 인식 (세로쓰기, 이체자 대응)
- **교정** — 글자 단위 교정 (OCR 오류, 이체자, 판본 이문 구분), Git 이력 관리

### 텍스트 편성
- **자동 편성** — 모든 LayoutBlock을 1:1로 TextBlock 자동 생성
- **합치기** — 여러 LayoutBlock을 선택하여 하나의 TextBlock으로 결합
- **교정 자동 적용** — 편성 시 교정 기록이 반영된 텍스트 사용

### 해석 작업 (L5~L7)
- **표점(句讀)** — 고전 한문에 구두점 삽입, LLM 자동 제안 + 수동 편집
- **현토(懸吐)** — 한문에 한국어 토 달기
- **번역** — LLM 자동 번역 + 수동 교정, Draft → 확정 워크플로우
- **역주(譯注)** — 인물·사건·전거 등 연구자가 새로 작성하는 주석

### 교정·비교
- **글자 단위 대조** — OCR 결과와 교정본을 글자별로 정렬·비교
- **이체자 사전** — 이체자/약자 매핑 관리

### 저장소 관리
- **원본 저장소 + 해석 저장소** 분리 — 각각 독립적인 Git 저장소
- **원격 저장소 설정** — GitHub 등 원격 URL 설정, Push/Pull
- **Git 그래프** — 커밋 히스토리 시각화

### LLM 연동
- **다중 프로바이더** — Base44 Bridge, Ollama (클라우드 모델 프록시), Anthropic
- **자동 폴백** — 1순위 실패 시 차순위 프로바이더로 자동 전환
- **비전 모델 필터링** — OCR/레이아웃은 비전 지원 모델만 표시

### 추가 예정 기능

- **PaddleOCR 연동** — LLM 비전 외에 PaddleOCR 엔진 지원 (한문/일본어 고전 특화)
- **PDF 텍스트 추출** — 텍스트가 내장된 PDF에서 OCR 없이 직접 텍스트 추출
- **HWP/HWPX 가져오기** — 한글 문서에서 텍스트 및 이미지 가져오기


## 기술 스택

| 영역 | 기술 |
|------|------|
| 백엔드 | Python + FastAPI |
| 프론트엔드 | HTML + vanilla JS + CSS (빌드 도구 없음) |
| PDF 렌더링 | PDF.js |
| 이미지 처리 | Pillow, PyMuPDF |
| LLM 라우터 | 자체 구현 (Base44, Ollama, Anthropic) |
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
```


## 사용법

### 서버 실행

```bash
# 기본 실행 (포트 8765)
uv run python -m app serve --library <서고경로>

# 포트 변경
uv run python -m app serve --library <서고경로> --port 8080

# 예제 서고로 실행
uv run python -m app serve --library examples/monggu_library
```

서버 실행 후 `http://localhost:8765`에서 웹 UI에 접속합니다.

> **참고**: `--library` 인수는 필수입니다. 서고 경로를 지정해야 합니다.
> 향후 GUI에서 서고 경로를 선택하는 기능이 추가될 예정입니다.

#### Windows 배치 파일 (편의용)

매번 명령어를 입력하기 번거로우면 배치 파일을 만들어 사용하세요:

```bat
@echo off
REM start_server.bat — 서고 서버 실행
cd /d "%~dp0"
uv run python -m app serve --library examples\monggu_library --port 8765
pause
```

이 파일을 프로젝트 루트에 `start_server.bat`로 저장하고 더블클릭하면 서버가 시작됩니다.

### CLI (서고 관리)

```bash
# 서고 초기화
uv run python -m cli init-library <경로>

# 문헌 등록 (PDF/이미지를 L1_source에 복사)
uv run python -m cli add-document <서고경로> --title "蒙求" --doc-id monggu

# 문헌 목록 확인
uv run python -m cli list-documents <서고경로>
```


## 작업 워크플로우

연구자의 일반적인 작업 순서입니다. 각 단계는 웹 UI의 탭에 대응합니다.

### 1단계: 원본 준비

| 탭 | 작업 | 결과물 |
|----|------|--------|
| **열람** | 문헌 선택, 페이지 탐색, PDF 열람 | — |
| **레이아웃** | "AI 분석" → LayoutBlock 자동 감지 → 수동 조정 | L3 레이아웃 JSON |
| — | "전체 OCR" 또는 "선택 블록 OCR" → LLM 비전 인식 | L2 OCR 결과 + L4 텍스트 |

### 2단계: 교정

| 탭 | 작업 | 결과물 |
|----|------|--------|
| **교정** | "OCR 채우기" → OCR 결과를 텍스트로 → 글자 단위 교정 | L4 교정 기록 (JSON) |

교정 유형:
- **OCR 오류**: LLM이 잘못 읽은 글자 (예: 寬→寒)
- **이체자**: 다른 자형이지만 같은 글자 (예: 說↔説)
- **판본 이문**: 다른 판본에서 다른 글자가 쓰인 경우
- **판독 불가→가능**: 원래 읽을 수 없었으나 맥락에서 추정

### 3단계: 편성

| 탭 | 작업 | 결과물 |
|----|------|--------|
| **편성** | 교정된 LayoutBlock → TextBlock 변환 | 해석 저장소 core_entities/blocks/ |

편성 방법:
- **자동 편성**: 모든 LayoutBlock을 1:1로 TextBlock 자동 생성 (대부분의 경우)
- **합치기**: 페이지를 넘어가는 문장 등, 여러 블록을 하나의 TextBlock으로 결합

> **왜 편성이 필요한가?**
> 교정까지는 원본 이미지의 물리적 영역(LayoutBlock) 단위로 작업하지만,
> 표점·번역부터는 의미 단위(TextBlock)로 작업해야 합니다.
> 예를 들어 한 문장이 두 페이지에 걸쳐 있으면, 두 LayoutBlock을 합쳐서
> 하나의 TextBlock으로 만든 뒤 표점을 찍어야 합니다.

### 4단계: 해석

| 탭 | 작업 | 결과물 |
|----|------|--------|
| **표점** | TextBlock에 구두점(。，；：) 삽입, LLM 자동 제안 | L5 표점 데이터 |
| **현토** | 한문에 한국어 토(吐) 달기, LLM 자동 제안 | L5 현토 데이터 |
| **해석** | L5~L7 레이어별 내용 확인·편집 | 해석 저장소 각 레이어 |
| **번역** | LLM 자동 번역 → 수동 교정 → 확정 | L6 번역 텍스트 |
| **주석** | 역주 작성: 인물·사건·전거 등 연구자가 추가 | L7 주석 데이터 |

> **원주(原注)와 역주(譯注)의 차이**:
> - 원주는 원본에 이미 있는 주석입니다. LayoutBlock으로 인식되어 OCR→교정→편성을 거칩니다.
> - 역주는 현대 연구자가 새로 작성하는 주석입니다. 주석(L7) 탭에서 직접 입력합니다.


## LLM 프로바이더 설정

| 프로바이더 | 설정 방법 | 비전 지원 |
|-----------|----------|----------|
| Base44 Bridge | 자동 (Node.js 서브프로세스) | O |
| Ollama | `http://localhost:11434` (로컬 또는 클라우드 프록시) | 모델 의존 |
| Anthropic | 환경변수 `ANTHROPIC_API_KEY` | O (유료) |

OCR/레이아웃 분석에는 비전 지원 모델만 사용 가능합니다.
드롭다운에서 눈 아이콘이 있는 모델이 비전 지원 모델입니다.


## 8층 데이터 모델

| 층 | 이름 | 내용 | 저장소 | 예시 |
|----|------|------|--------|------|
| L1 | 원본 파일 | PDF/이미지 원본 | 원본 | `L1_source/vol1.pdf` |
| L2 | OCR 결과 | 글자 인식 결과 (좌표 포함) | 원본 | `L2_ocr/vol1_page_001.json` |
| L3 | 레이아웃 | 페이지 영역 구분 (본문/원주/제목) | 원본 | `L3_layout/vol1_page_001.json` |
| L4 | 텍스트+교정 | OCR 텍스트 + 글자 단위 교정 기록 | 원본 | `L4_text/pages/`, `L4_text/corrections/` |
| L5 | 표점/현토 | 구두점, 한국어 토 | 해석 | `L5_reading/main_text/` |
| L6 | 번역 | 현대어 번역 | 해석 | `L6_translation/main_text/` |
| L7 | 역주 | 연구자가 작성하는 주석 | 해석 | `L7_annotation/` |
| L8 | 관계 | 엔티티 간 관계 그래프 | 해석 | `core_entities/relations/` |

> L4의 텍스트 파일(`.txt`)은 원본을 유지하고, 교정 기록은 별도 JSON 파일로 저장됩니다.
> 편성 단계에서 원본 텍스트 + 교정 기록이 합쳐져 TextBlock이 됩니다.


## 프로젝트 구조

```
classical-text-platform/
├── docs/                  # 설계 문서
│   ├── platform-v7.md     #   8층 모델, Git 저장소, 전체 아키텍처
│   ├── core-schema-v1.3.md#   해석 저장소의 엔티티 모델
│   ├── operation-rules-v1.0.md # 코어 스키마 운영 규약
│   └── DECISIONS.md       #   설계 결정 기록
├── src/
│   ├── core/              #   핵심 로직 (문서, 해석, 편성 등)
│   ├── llm/               #   LLM 라우터 + 프로바이더 (Base44, Ollama, Anthropic)
│   ├── ocr/               #   OCR 엔진 + 이미지 전처리 파이프라인
│   ├── parsers/           #   서지정보 파서
│   ├── cli/               #   CLI 도구 (자동화/스크립팅)
│   └── app/               #   웹 앱 (GUI — 주 인터페이스)
│       ├── server.py      #     FastAPI 서버 (모든 API 엔드포인트)
│       └── static/        #     정적 파일 (CSS, JS)
├── schemas/
│   ├── source_repo/       #   원본 저장소 JSON 스키마
│   ├── interp/            #   해석 저장소 레이어 스키마
│   └── core/              #   코어 스키마 (TextBlock, Work, Tag 등)
├── examples/              # 예제 서고 (monggu_library)
├── resources/             # 공유 리소스 (block_types 등)
├── pyproject.toml         # 프로젝트 설정 및 의존성
└── CLAUDE.md              # 프로젝트 규칙 및 코딩 가이드
```


## 설계 문서

자세한 아키텍처와 설계 결정은 `docs/` 폴더를 참고하세요:

- **platform-v7.md** — 8층 데이터 모델, 원본·해석 저장소 분리, 전체 아키텍처
- **core-schema-v1.3.md** — 해석 저장소(5~8층)의 엔티티 모델
- **operation-rules-v1.0.md** — 코어 스키마 운영 규약
- **DECISIONS.md** — 주요 설계 결정과 근거


## 라이선스

미정 (DECISIONS.md 미결 사항 참고)
