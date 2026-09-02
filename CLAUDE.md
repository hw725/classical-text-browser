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
- docs/maintenance.md — **유지보수 정본.** 되돌릴 수 없는 것, 파일 다루는 규칙,
  자동 테스트가 못 잡는 자리, 릴리스 절차. 아래 요약들의 원본이다
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

**GPU 스택은 이 환경(.venv)에 설치하지 않는다.** GPU는 별도 환경 `.venv-gpu`가
정본이며(`D-078`, user-guide §7-A.6-2), `start_server.bat`이 실행 시 자동 선택한다.
`.venv-gpu`에는 `uv sync`·`uv run` 금지 — python 직접 호출만.

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
| `torch`는 전용 인덱스(플랫폼 분기: Windows `pytorch-cu124`·Linux `pytorch-cu126`, 2026-08-20 실측) | CUDA 버전을 바꾸면 `[[tool.uv.index]]` URL도 함께 고쳐야 한다 |
| `ndl-lab/ndlocr-lite` **master**에서 모델 받기 | 원본이 v1.2.0에서 PARSeq 셋을 바꿔(16px→24px, 파일명 변경) 셋이 404. 모델 URL은 **태그 1.1.3**에 고정(`src/ocr/ndlocr/__init__.py`). 古典籍-Lite는 이미 1.3.1 고정 |
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
server.py는 FastAPI 앱 생성 + 라우터 마운트 + 미들웨어만 담당하는 조립 파일(152줄).
실제 API 엔드포인트 194개가 8개 라우터 모듈에 분산 (2026-09-02 기준 실측):

```
src/app/
├── server.py            ← 앱 생성 + 라우터 마운트 + configure()
├── _state.py            ← 공유 상태 + 헬퍼 + LLM 프롬프트/캐시/동적 토큰 계산
├── __main__.py          ← CLI 진입점 (python -m app serve)
└── routers/
    ├── library.py       ← 서고/설정/백업/휴지통 (16 라우트)
    ├── documents.py     ← 문헌 CRUD/페이지/교정/서지/파서 + 텍스트레이어 진단·가져오기·입히기 + 권 추가 + 경계 규칙 (41 라우트)
    ├── interpretations.py ← 해석 CRUD/레이어/의존/엔티티/내용 트리/경계 제안·적용 (28 라우트)
    ├── llm_ocr.py       ← LLM 상태·분석·초안 + OCR 엔진·실행·권단위 일괄·백업 되돌리기·판독 지침·LLM 교정 패스 (24 라우트)
    ├── alignment.py     ← 이체자 사전/정렬/일괄교정/문헌별 승인 (20 라우트)
    ├── reading.py       ← L5 표점·현토 + L6 번역 + 비고 + AI보조 (24 라우트)
    ├── annotation.py    ← L7 주석·사전형·인용마크 + AI보조 (34 라우트)
    └── version.py       ← Git 그래프/되돌리기/스냅샷/가져오기 (7 라우트)
```

- 라우터 간 직접 import 금지. 공유 상태는 반드시 _state.py를 통해 접근.
- 새 엔드포인트 추가 시 해당 도메인의 라우터 파일에 추가할 것.
  **위 라우트 수는 기계가 검사한다**(D-079) — 라우트를 늘리거나 줄이면 이 트리와
  `AGENTS.md`·`server.py` 머리말의 숫자도 함께 고쳐야 pytest가 통과한다.
  `uv run python scripts/check_doc_drift.py`가 어디가 어긋났는지 짚어 준다.
- Pydantic 모델은 사용하는 라우터 파일 내부에 정의.
- **API 응답에는 `Cache-Control: no-store`가 미들웨어에서 자동으로 붙는다**(D-066).
  호출부에 `cache: "no-store"`를 다시 적지 않아도 된다.

## 추출 모드 관련 모듈 (v1.2.0에서 추가)

논문 스캔본 경로에만 쓰이는 것들. 고서 흐름은 이 모듈들을 타지 않는다.

| 모듈 | 하는 일 |
|---|---|
| `src/ocr/full_page_block.py` | 레이아웃이 없는 쪽에 「쪽 전면 1블록」 L3를 만든다 |
| `src/ocr/layout_staleness.py` | 레이아웃을 고친 쪽을 찾아 다시 돌릴 대상을 고른다 |
| `src/ocr/page_backup.py` | OCR 재실행 **직전** 상태를 로컬 JSON으로 백업(D-065) |
| `src/ocr/line_detector.py` | 좌표를 주지 않는 엔진을 위해 줄 위치를 검출 |
| `src/export/text_layer_pdf.py` | 보이지 않는 텍스트를 얹은 PDF를 만들고 **결과를 다시 재서 검사**(D-068) |
| `src/cli/embed_folder.py` · `src/cli/__main__.py` | `ctb ocr` 한 줄 진입점 |

## OCR 품질 모듈 (D-080~D-084, 2026-09-02)

| 모듈 | 하는 일 |
|---|---|
| `src/ocr/ocr_prompt.py` | LLM OCR 프롬프트를 다섯 조각(정책·문헌 지침·블록 종류·자형 주의·앵커)으로 **조립**. `[?]`·`□`를 글자 신뢰도로 변환. 도메인 목록을 코드에 하드코딩하지 않는다 |
| `src/ocr/correction_pass.py` | 승급 사다리 1·2단계. 기계적 선별 → 앵커 있는 LLM 교정(사고 끔) → 정밀 판독(문맥 확대·사고 켬). **L2는 건드리지 않고** L4 초안만 만든다 |
| `src/ocr/eval_cer.py` · `scripts/eval_cer.py` | L4 확정본을 정답으로 L2·초안의 CER. 프롬프트를 바꿨으면 이것으로 잰다 |
| `src/core/variant_sources.py` · `scripts/build_variant_dicts.py` | 이체자 사전 원자료(OpenCC·Unihan·cjkvi) 파서와 생성. 파일마다 `_tier`·`_source` |
| `src/ocr/line_block_match.py` | 쪽 단위 엔진(NDL 셋)이 쪽 전체에서 찾은 행을 LayoutBlock에 배정. **블록 밖 행은 버린다.** 그래서 파이프라인이 커버리지 조건 없이 언제나 쪽 전체에 돌린다(D-086) |
| `src/core/segmentation.py` | 글 단위 경계 제안(D-088). 날짜 문법·사슬·형식 신호는 코드, 표제 어휘·억제 목록은 `manifest.segmentation_rules`. 제안은 저장하지 않고 승인한 구간만 TextBlock |
| `src/llm/providers/base.py::thinking_options` | 사고 예산을 답변 예산에 **더하는** 공통 해석. 비전 경로 4종이 이것을 따른다 |

- **사전은 지식이고 정책은 문헌의 것**: `strict`만 동치, `loose`·`script`는 힌트. 승인은 `documents/{doc_id}/variant_approvals.json`에만.
- **사고(thinking)는 전역 스위치가 아니다**: 기본 끔(D-074). 정밀 판독과 사용자가 명시한 호출만 켠다. thinking 필드를 본문으로 쓰는 폴백은 어디에도 없다.

## 파일 다루기 — 되풀이하지 말 것

| 규칙 | 왜 |
|---|---|
| **JSON 저장은 `core.document.write_json_atomic()`**. `Path.write_text()` 금지 | write_text는 먼저 0바이트로 자른다. 도중에 죽으면 manifest가 빈 파일이 되고 문헌이 통째로 열리지 않는다(D-069) |
| **PDF는 `resolve_part_pdf(doc_path, part_id)`로 연다**. `glob("*.pdf")[0]` 금지 | glob은 순서를 보장하지 않고 part_id도 안 본다. 다권본에서 엉뚱한 권을 읽는다(D-069) |
| **`fitz.open()`은 `with`로** | 예외 경로에서 핸들이 남으면 Windows가 그 PDF를 잠근다 |
| **기존 PDF에 덧쓸 때는 `page.wrap_contents()` 먼저** | 원본이 남긴 좌표 변환에 끌려 들어간다(D-068) |
| **L2 bbox를 쓸 때 배율은 L2의 `image_width`로 구한다**. 2.0 하드코딩 금지 | 스캔 PDF는 내장 이미지 해상도로 렌더하므로 쪽마다 배율이 다르다. 기록이 없는 옛 파일만 뷰포트×2.0(D-087) |
| **화면에 넣는 파일명·OCR 원문은 이스케이프** | 드롭한 파일명이 문헌 제목이 되어 `innerHTML`로 들어간다(D-069) |

## 코딩 규칙
- 이 프로젝트의 사용자는 비개발자 인문학 연구자다
- 코드 주석은 한국어로, 상세하게, 「왜 이렇게 하는지」 포함
- 함수마다 docstring에 입력/출력/목적 설명
- UTF-8 인코딩, LF 줄바꿈
- JSON 파일은 jsonschema로 검증
- 에러 메시지는 한국어로, 원인과 해결책 포함
- primary_data/ 또는 L1_source/ 내의 원본 파일은 절대 수정 금지

## 용어 규칙 (혼동 방지)
- LayoutBlock: 원본 저장소 L3의 페이지 영역 (OCR 읽기 순서 단위)
- OcrResult: 원본 저장소 L2의 OCR 인식 결과
- TextBlock: 코어 스키마의 해석용 텍스트 단위 (source_ref로 원본 추적)
- 「Block」이라고만 쓰지 말고 항상 위 세 이름 중 하나를 사용할 것

## 작업 방식: CLI를 적극 활용할 것
- 코드를 작성한 뒤 반드시 실행해서 확인하라. 작성만 하고 검증 없이 넘어가지 마라.
- API 엔드포인트를 만들면 curl이나 테스트 스크립트로 직접 호출해서 응답을 확인하라.
- 웹 스크래핑 파서를 작성할 때는 대상 사이트의 HTML 구조를 먼저 curl/wget으로 가져와서 확인하라.
- JSON 파일을 생성하면 jsonschema로 검증하라.
- 테스트를 작성했으면 실행해서 통과하는지 확인하라.
- 「될 것 같다」로 끝내지 말고, 실제로 동작하는 것을 보여줘라.

## Git 커밋 규칙
형식: <타입>: <설명>
타입: feat / fix / data / docs / refactor / test
예시: feat: Phase 2 — 서고 초기화 CLI 구현
