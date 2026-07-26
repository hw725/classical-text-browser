# 고전서지 통합 브라우저 (Classical Text Browser)

물리적 원본(PDF·이미지)과 디지털 텍스트의 연결이 끊어지지 않는,
사람과 LLM이 함께 고전 텍스트를 읽고 번역하고 연구하는 **통합 작업 환경**.

![작업 환경 전체 화면](docs/screenshots/01_workspace.png)

왼쪽에 서고 탐색기, 가운데에 원본 뷰어, 오른쪽에 텍스트 작업 패널이 놓인
VSCode 스타일 3단 화면입니다.

---

## 두 가지 쓰임

하나만 쓰는 사람이 대부분입니다. **자기 것부터 읽으면 됩니다.**

### 📄 추출 — 논문 스캔본에서 텍스트만 빠르게

근현대 논문·단행본처럼 표점·현토가 필요 없는 자료용입니다.
**끌어다 놓고 → OCR → 검색되는 PDF**까지 한 화면에서 끝납니다.
쪽마다 레이아웃을 잡을 필요가 없고, 중단해도 이어서 돕니다.

산출물은 원본 이미지 위에 보이지 않는 텍스트를 얹은 PDF라
복사·Ctrl+F·구조 분석·참고문헌 추출이 한꺼번에 살아납니다.

논문 한 편이면 앱을 열 필요도 없습니다.

```bash
ctb ocr "논문.pdf" --execute
```

→ [사용자 안내서 7-A](docs/user-guide.md#7-a-근현대-논문에서-텍스트만-빠르게-뽑기)

### 📜 교감 — 고전 원전을 읽고 해석하기

원본 이미지에서 텍스트를 만들고(레이아웃 → OCR → 교정),
그 위에 표점·현토·번역·주석을 겹겹이 쌓습니다.
**원본과 해석을 각각 다른 Git 저장소**에 두어, 해석이 여럿 병존해도
원본은 하나의 정본으로 남습니다.

→ [사용자 안내서](docs/user-guide.md) · [기능 소개](docs/features.md)

---

## 빠른 시작

1. [저장소 내려받기](https://github.com/hw725/classical-text-browser/archive/refs/heads/master.zip) 후 압축 풀기
2. `install.bat` 더블클릭 (Windows) 또는 `./install.sh` (macOS·Linux)
3. `start_server.bat` 더블클릭 (Windows) 또는 `./start_server.sh`
4. 브라우저에서 `http://localhost:8000`
5. **PDF나 이미지를 창 안에 끌어다 놓으세요.** 서고가 없으면 자동으로 만들어집니다.

Git을 아신다면 `git clone https://github.com/hw725/classical-text-browser.git`도 됩니다.

**기본 설치만으로 한글 논문 처리는 전부 됩니다** — OCR, 텍스트 레이어 PDF,
형광 위치까지. 아래는 다른 종류의 문헌을 다룰 때만 추가하세요.

| 추가 설치 | 언제 | 크기 |
|---|---|---|
| `uv sync --extra japanese` | 일본어 문헌(근현대) | 약 170MB |
| `uv sync --extra classical` | 고서(古典籍) | 약 170MB |
| `uv sync --extra classical-gpu` | 고서 최고 품질(TrOCR, GPU 권장) | 약 340MB |

> 뒤 둘은 **한글을 인식하지 못합니다** — 한글 논문에는 쓰지 마세요.
> Python은 3.10~3.12를 씁니다(paddlepaddle 휠이 3.13까지 나와 있지 않습니다).

---

## 문서 지도

### 쓰는 사람

| 문서 | 무엇이 있나 |
|---|---|
| [**사용자 안내서**](docs/user-guide.md) | 설치부터 산출물까지 **단계별 사용법** |
| [기능 소개](docs/features.md) | 이 프로그램이 무엇을 할 수 있나 |
| [릴리스 노트](docs/releases/v1.2.0.md) | 판마다 무엇이 바뀌었나 (v1.2.0 최신) |

### 고치는 사람

| 문서 | 무엇이 있나 |
|---|---|
| [**유지보수 안내**](docs/maintenance.md) | **고치기 전에 볼 것** — 되돌릴 수 없는 것, 되풀이하지 말 것, 테스트 사각지대 |
| [DECISIONS.md](docs/DECISIONS.md) | 설계 결정 근거 (D-001~D-069) |
| [아키텍처 다이어그램](docs/architecture-diagrams.md) | 전체 그림 (Mermaid 13종) |
| [platform-v7.md](docs/platform-v7.md) | 8층 모델·이중 저장소 설계 |
| [AGENTS.md](AGENTS.md) · [인지 부채 감사](cognitive-debt-audit.html) | 어디가 위험한가 |

### 자료 구조

| 문서 | 무엇이 있나 |
|---|---|
| [core-schema-v1.3.md](docs/core-schema-v1.3.md) · [operation-rules-v1.0.md](docs/operation-rules-v1.0.md) | 코어 엔티티 모델과 운영 규약 |
| [schemas/README.md](schemas/README.md) · [스키마 개요](docs/schema-overview.md) | JSON 스키마 19개 |
| [llm_architecture_design.md](docs/llm_architecture_design.md) | LLM 5단 폴백 설계 |
| [세션 기록](docs/sessions/session_navigator.md) · [회고](docs/retrospective/README.md) | 만들면서 무엇을 배웠나 |

---

## 8층 데이터 모델

| 층 | 이름 | 저장소 | 층 | 이름 | 저장소 |
|----|------|--------|----|------|--------|
| L1 | 원본 파일 | 원본 | L5 | 표점·현토 | 해석 |
| L2 | OCR 결과 | 원본 | L6 | 번역 | 해석 |
| L3 | 레이아웃 | 원본 | L7 | 주석·사전 | 해석 |
| L4 | 교정 텍스트 | 원본 | L8 | 관계 그래프 | 해석 |

원본(L1~L4)은 **단일 정본**으로 수렴하고, 해석(L5~L8)은 **여럿이 병존**합니다.
자세히: [platform-v7.md](docs/platform-v7.md) · [아키텍처 다이어그램](docs/architecture-diagrams.md)

## 기술 스택

Python + FastAPI · HTML + vanilla JS (빌드 도구 없음) · PDF.js · PyMuPDF · GitPython · jsonschema · uv

---

## 라이선스

[PolyForm Noncommercial 1.0.0](LICENSE)

- 비상업적 사용·수정·재배포: 자유
- 상업적 사용: 별도 협의 (LICENSE 파일 하단 연락처)

## 외부 모델 출처

외부 표점 서비스의 SikuRoBERTa 엔진은
[`yachagye/korean-classical-chinese-punctuation`](https://github.com/yachagye/korean-classical-chinese-punctuation)
모델을 HTTP 마이크로서비스로 연동합니다. 원 저장소 조건에 따라 원저작자와 출처를
표기하고 논문을 인용해야 합니다.

- 원저작자: Junghyun Yang (양정현)
- 모델: Korean Classical Chinese Punctuation Prediction Model v2.5
- 라이선스: CC BY-NC-SA 4.0
- DOI: https://doi.org/10.37924/JSSW.100.9

권장 인용:

```text
Yang, J. (2025). Development and Application of a Deep Learning-Based Model
for Automated Punctuation Inference in Korean Classical Chinese.
The Korean Journal of History (Yoksahak Yongu), 100, 267-297.
https://doi.org/10.37924/JSSW.100.9
```
