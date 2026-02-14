# 고전 텍스트 디지털 서고 플랫폼

물리적 원본(PDF/이미지)과 디지털 텍스트의 연결이 끊어지지 않는,
사람과 LLM이 함께 고전 텍스트를 읽고 번역하고 연구하는 **통합 작업 환경**.

개발자의 VSCode처럼, 연구자가 이 안에서 이미지 열람, 레이아웃 분석,
OCR, 교정, 번역, 주석 작업을 모두 수행합니다.

## 기술 스택

| 영역 | 기술 |
|------|------|
| 백엔드 | Python + FastAPI |
| 프론트엔드 | HTML + vanilla JS + CSS (빌드 도구 없음) |
| PDF 렌더링 | PDF.js |
| 버전 관리 | GitPython |
| 스키마 검증 | jsonschema |

## 설치

[uv](https://docs.astral.sh/uv/)를 사용합니다.

```bash
# 저장소 클론
git clone <repository-url>
cd classical-text-platform

# 의존성 설치 (.venv 자동 생성)
uv sync

# 개발 의존성 포함 설치
uv sync --group dev
```

## 사용법

```bash
# 서고 초기화
uv run python -m cli init-library <경로>

# 문헌 등록
uv run python -m cli add-document <서고경로> --title "蒙求" --doc-id monggu

# 문헌 목록 확인
uv run python -m cli list-documents <서고경로>

# 웹 서버 실행
uv run python -m app serve --library <서고경로>
```

## 프로젝트 구조

```
classical-text-platform/
├── docs/                  # 설계 문서
│   ├── platform-v7.md     #   8층 모델, Git 저장소, 전체 아키텍처
│   ├── core-schema-v1.3.md#   해석 저장소의 엔티티 모델
│   ├── operation-rules-v1.0.md # 코어 스키마 운영 규약
│   └── DECISIONS.md       #   설계 결정 기록
├── src/
│   ├── core/              #   핵심 로직 (CLI·GUI 공용)
│   ├── parsers/           #   서지정보 파서
│   ├── cli/               #   CLI 도구 (자동화/스크립팅)
│   └── app/               #   웹 앱 (GUI — 주 인터페이스)
│       ├── routes/        #     FastAPI 라우트
│       └── static/        #     정적 파일 (CSS, JS)
├── schemas/
│   ├── source_repo/       #   원본 저장소 JSON 스키마
│   └── core/              #   코어 스키마 (해석 저장소)
├── tests/                 # 테스트
├── examples/              # 예제 데이터
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
