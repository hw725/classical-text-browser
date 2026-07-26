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

## 의존성 업그레이드 — 먼저 볼 것

OCR 스택 셋(**paddlepaddle+paddleocr** / **onnxruntime+opencv** / **torch+transformers**)이
전이 의존을 공유한다 — `numpy`·`protobuf`·`pyyaml`·`typing-extensions`·`setuptools`·
`networkx`·`pillow`. 하나를 올리면 다른 스택이 **조용히** 죽는다: 엔진 등록 실패는
예외가 아니라 `available=False`로 나타나고 라우터는 다음 엔진으로 넘어간다(D-044·D-056).

**이미 겪은 결합 지점**

| 무엇 | 결과 |
|---|---|
| `paddleocr` 2.x → 3.x | `show_log`·`use_angle_cls`·`use_gpu` 제거, `ocr.ocr()` → `ocr.predict()` (a3894c2) |
| `paddleocr` 3.7이 `pyyaml==6.0.2` 고정 | 이 저장소의 하한도 6.0.2로 내림 |
| `paddlepaddle` 휠이 cp312까지 | `requires-python`에 `<3.13` (D-059) |
| Windows + paddlepaddle 3.x | OneDNN이 PIR 속성 변환 미지원 → `FLAGS_use_mkldnn=0` 회피 |
| `torch`는 전용 인덱스(`pytorch-cu124`) | CUDA 버전을 바꾸면 `[[tool.uv.index]]` URL도 함께 고쳐야 한다 |
| `opencv-contrib-python`(paddlex) ↔ `opencv-python-headless`(extras) | **같은 `cv2`를 두 배포판이 제공.** 한쪽을 지우면 공유 디렉터리가 사라져 남은 쪽까지 깨진다 — `module 'cv2' has no attribute 'IMREAD_COLOR'`. extras도 contrib판으로 통일했다 |

**올릴 때 절차**

1. `uv lock --upgrade-package <이름>` — **전체 갱신은 하지 않는다.** 한꺼번에 올리면
   무엇이 깼는지 가릴 수 없다.
2. `uv run python -m pytest`
3. **실제 이미지로 OCR 1쪽.** 자동 테스트의 사각지대가 여기다 —
   `test_ocr_paddle.py::test_recognize_real`이 PaddleOCR `recognize()`를 실제로
   부르지만(설치 시에만), **검출(`line_detector`)은 순수 함수만 검증하고
   배치·파이프라인 경로는 더미 엔진을 쓴다.** 엔진 API가 바뀌어도 초록으로 통과한다.
4. 스키마·저장 형식이 바뀌면 `docs/DECISIONS.md`에 마이그레이션 경로를 남긴다.
   기존 서고를 열 수 없게 되는 변경은 **되돌릴 수 없다.**

## 백엔드 모듈 구조 (src/app/)
server.py는 FastAPI 앱 생성 + 라우터 마운트만 담당하는 조립 파일(~85줄).
실제 API 엔드포인트는 8개 라우터 모듈에 분산 (2026-07-26 기준 실측):

```
src/app/
├── server.py            ← 앱 생성 + 라우터 마운트 + configure()
├── _state.py            ← 공유 상태 + 헬퍼 + LLM 프롬프트/캐시/동적 토큰 계산
├── __main__.py          ← CLI 진입점 (python -m app serve)
└── routers/
    ├── library.py       ← 서고/설정/백업/휴지통 (16 라우트)
    ├── documents.py     ← 문헌 CRUD/페이지/교정/서지/파서 + 텍스트레이어 진단·가져오기·입히기 + 권 추가 (40 라우트)
    ├── interpretations.py ← 해석 CRUD/레이어/의존/엔티티 (25 라우트)
    ├── llm_ocr.py       ← LLM 상태·분석·초안 + OCR 엔진·실행·권단위 일괄 (18 라우트)
    ├── alignment.py     ← 이체자 사전/정렬/일괄교정 (17 라우트)
    ├── reading.py       ← L5 표점·현토 + L6 번역 + 비고 + AI보조 (26 라우트)
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
