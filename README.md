# 고전 텍스트 디지털 서고 플랫폼

물리적 원본(PDF/이미지)과 디지털 텍스트의 연결이 끊어지지 않는,
사람과 LLM이 함께 고전 텍스트를 읽고 번역하고 연구하는 **통합 작업 환경**.

> **처음 사용하시나요?** [사용자 가이드](docs/user-guide.md)를 먼저 읽어주세요.

## 주요 기능

| 영역 | 기능 |
|------|------|
| **원본 관리** | PDF/이미지 뷰어, 레이아웃 분석, OCR(LLM 비전 + PaddleOCR), HWP 가져오기 |
| **해석 작업** | 표점(句讀), 현토(懸吐), 번역(LLM+수동), 주석(태깅+사전형) |
| **연구 도구** | 인용 마크, 사전 내보내기/가져오기, 교차 뷰어 |
| **저장소 관리** | 원본·해석 분리 Git 저장소, 사다리형 그래프, JSON 스냅샷 |
| **LLM 연동** | Ollama, Base44, Anthropic, Gemini, OpenAI (자동 폴백) |

## 빠른 시작

```bash
# 설치
git clone https://github.com/hw725/classical-text-platform.git
cd classical-text-platform
uv sync

# (선택) 오프라인 OCR
uv sync --extra paddleocr
# 주의: Windows + Python 3.13 + PaddlePaddle 3.x(CPU) 조합은 런타임 충돌 가능

# 서버 실행
uv run python -m app serve --library <서고경로>
```

브라우저에서 `http://localhost:8765` 접속.

`--library` 없이 실행하면 GUI에서 서고를 선택/생성할 수 있습니다.

PaddleOCR은 기본 설치 대상이 아니며, 충돌 없는 환경 사용자만 개별 설치를 권장합니다.

## 기술 스택

Python + FastAPI | HTML + vanilla JS (빌드 도구 없음) | PDF.js | GitPython | jsonschema | uv

## 8층 데이터 모델

| 층 | 이름 | 저장소 | 층 | 이름 | 저장소 |
|----|------|--------|----|------|--------|
| L1 | 원본 파일 | 원본 | L5 | 표점/현토 | 해석 |
| L2 | OCR 결과 | 원본 | L6 | 번역 | 해석 |
| L3 | 레이아웃 | 원본 | L7 | 주석/사전 | 해석 |
| L4 | 교정 텍스트 | 원본 | L8 | 관계 그래프 | 해석 |

## 프로젝트 구조

```
src/
├── core/       # 핵심 로직 (표점, 번역, 주석 등)
├── hwp/        # HWP/HWPX 처리
├── llm/        # LLM 라우터 + 프로바이더
├── ocr/        # OCR 엔진 (LLM 비전 + PaddleOCR)
├── parsers/    # 서지정보 파서
├── cli/        # CLI 도구
└── app/        # 웹 앱 (FastAPI + static)
schemas/
├── source_repo/  # 원본 저장소 스키마 (7개)
├── interp/       # 해석 저장소 스키마 (5개)
└── core/         # 코어 엔티티 스키마 (6개)
```

## 문서 안내

| 문서 | 대상 | 내용 |
|------|------|------|
| [**user-guide.md**](docs/user-guide.md) | 연구자 | 사용 방법 단계별 안내 |
| [platform-v7.md](docs/platform-v7.md) | 개발자 | 전체 아키텍처 |
| [DECISIONS.md](docs/DECISIONS.md) | 개발자 | 설계 결정 근거 (D-001~D-023) |
| [core-schema-v1.3.md](docs/core-schema-v1.3.md) | 개발자 | 코어 엔티티 모델 |
| [schemas/README.md](schemas/README.md) | 개발자 | JSON 스키마 구조 |
| [architecture-diagrams.md](docs/architecture-diagrams.md) | 전체 | Mermaid 다이어그램 |
| [schema_overview.html](docs/schema_overview.html) | 전체 | 스키마 개요도 (브라우저, 19개) |
| [llm_architecture_design.md](docs/llm_architecture_design.md) | 개발자 | LLM 4단 폴백 설계 |
| [docs/sessions/](docs/sessions/session_navigator.md) | 개발자 | 구현 세션 기록 (Phase 10~12) |

## 라이선스

[PolyForm Noncommercial 1.0.0](LICENSE)

- 비상업적 사용·수정·재배포: 자유
- 상업적 사용: 별도 협의 필요 (LICENSE 파일 하단 연락처 참고)
