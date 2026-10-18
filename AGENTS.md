# 프로젝트: 고전서지 통합 브라우저 (Classical Text Browser)

> 이 파일이 **규칙 정본**이다. `CLAUDE.md`는 `@AGENTS.md` 한 줄로 이 파일을 불러오는 포인터다.
> 2026-10-08 합침: 그 전에는 CLAUDE.md가 정본이었고, 이 파일은 앞쪽이 CLAUDE.md의 옛 요약 사본·뒤쪽이
> 고유한 인지 부채 지도인 혼합형이었다. 앞쪽은 절마다 대조해 CLAUDE.md에 없는 사실 하나(단위의 `source_ref`)만
> 살려 옮기고 버렸다. 이 파일의 「Claude」는 Codex 세션에서 「Codex」로 읽는다.


## 프로젝트 비전
물리적 원본(PDF/이미지)과 디지털 텍스트의 연결이 끊어지지 않는,
사람과 LLM이 함께 고전 텍스트를 읽고 번역하고 연구하는 통합 작업 환경.

개발자의 VSCode처럼, 연구자가 이 안에서 이미지 열람, 레이아웃 분석,
OCR, 교정, 번역, 주석 작업을 모두 수행한다.

## 설계 문서
- docs/platform-v7.md — 8층 모델, Git 저장소, 전체 아키텍처
- docs/core-schema-v1.3.md — 해석 저장소의 엔티티 모델
- docs/operation-rules-v1.0.md — 코어 스키마 운영 규약
- **docs/CHECKPOINTS.md — 결정의 지금 결론·되돌릴 수 없는 것·사고 난 자리 (반드시 읽을 것).**
  DECISIONS.md를 처음부터 읽지 말고 이것을 읽은 뒤 건드리는 자리의 D 번호만 원문에서 찾는다
- docs/DECISIONS.md — 설계 결정 기록 원문(근거)
- docs/module-map.md — 모듈마다 무엇을 하고 무엇을 지키는가(이 파일에서 옮긴 표)
- docs/backlog.md — 알려진 결함·미결 과제
- docs/maintenance.md — **유지보수 정본.** 되돌릴 수 없는 것, 파일 다루는 규칙,
  자동 테스트가 못 잡는 자리, 릴리스 절차. 아래 요약들의 원본이다
- docs/observability-roadmap.md — 관측 가능성(OpenTelemetry) 점진적 도입 로드맵
- 옛 설계서·세션 기록·회고(D-050까지)·인지 부채 감사 HTML(옛 `docs/_archive/`)은 2026-10-11에 저장소에서 뺐다 — 내용은 `git show 11944f1:docs/_archive/<경로>`로 본다(목록: `git show 11944f1:docs/_archive/README.md`)

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
| `torch`(cu124) ↔ `paddlepaddle-gpu` **같은 프로세스** | 둘이 cuDNN 9 DLL을 따로 들고 온다(`torch/lib`, `nvidia/cudnn/bin`). 판이 다르면 먼저 뜬 쪽이 이기고 뒤쪽이 WinError 127. 앱은 torch(NDL Full)를 먼저 읽어 **PaddleOCR이 사용 불가**로 보인다(2026-09-02 실측). 해법은 프로세스 분리 — PaddleOCR을 자식 프로세스로 돌린다(D-091). 자식은 **.venv-gpu 파이썬 + torch import 차단(`CTB_PADDLE_BLOCK_TORCH`)으로 먼저 띄워 GPU**로 돌고, 안 뜨면 `start_server.bat`이 놓은 `CTB_PADDLE_PYTHON=.venv`(CPU)로 내려간다(2026-09-10 덧붙임, 조각 하나 5초 → 0.06초). 충돌은 《한 프로세스》이지 《GPU를 같이 쓰는 것》이 아니다. `doctor.bat`이 판정한다 |
| `onnxruntime`(CPU판) ↔ `onnxruntime-gpu` | **같은 `onnxruntime` 패키지 디렉터리를 두 배포판이 제공** — 같이 두면 서로 덮어쓴다. `.venv-gpu`는 CPU판을 빼고 GPU판 1.24.4를 넣는다(user-guide 7-A.6-2). GPU판이면 ONNX 엔진 셋이 `ort_device()`로 cuda를 잡는다. **torch보다 onnxruntime을 먼저 쓰는 프로세스는 `preload_dlls`가 필요하다** — 안 하면 첫 세션이 조용히 CPU로 떨어진다(2026-09-10 실측). torch·ORT GPU판·paddle GPU판(워커)은 한 PC에서 충돌 없이 돈다 |
| `opencv-contrib-python`(paddlex) ↔ `opencv-python-headless`(extras) | **같은 `cv2`를 두 배포판이 제공.** 한쪽을 지우면 공유 디렉터리가 사라져 남은 쪽까지 깨진다 — `module 'cv2' has no attribute 'IMREAD_COLOR'`. extras도 contrib판으로 통일했다 |

**환경이 이상하면 먼저 `doctor.bat`(`uv run python scripts/doctor.py`).** `.venv`·`.venv-gpu`를
각각 조사해 어느 환경이 뜨는지, 파이썬 버전, paddle/onnxruntime/torch import, 엔진별 사용 불가
이유, 지울 것을 권고한다. 옛 `.venv-gpu`(3.13)가 남아 start_server가 그쪽을 고른 사례가 있었다.

**올릴 때 절차**

1. `uv lock --upgrade-package <이름>` — **전체 갱신은 하지 않는다.** 한꺼번에 올리면
   무엇이 깼는지 가릴 수 없다.
2. `uv run python -m pytest`
3. **실제 이미지로 OCR 1쪽.** 어디가 사각지대인지는 **재서 안다** — `uv run python scripts/measure_blind_spots.py <파일…>`이 시험이 도는 동안 `sys.monitoring`으로 **함수 진입**을 기록해 「초록인데 한 줄도 안 도는 자리」를 짚는다(줄 커버리지와 다르다: import 돼서 `def` 줄이 실행된 것을 실행으로 세지 않는다). 아래는 2026-09-21 실측이다:

   | 엔진 | 시험에서 실행되는 것 |
   |---|---|
   | `paddleocr_engine` | `recognize`(설치 시 실모델 1회, 단 `assert`는 engine_id뿐) |
   | `ndlocr_engine` | `recognize_page`·`_cascade_recognize`·`_process_detections` |
   | `honkoku_engine` | `recognize`·`recognize_page`(가짜 OCR 주입 — 변환 코드는 실행된다) |
   | `llm_ocr_engine` | `recognize`·`_recognize_async`(가짜 router) |
   | `line_detector` | `detect_lines`·`_get_detector` |
   | `ndlkotenocr_engine`·`ndlkotenocr_full_engine` | `_process_detections`·`_match_lines_to_blocks`(2026-09-21에 `tests/test_ocr_kotenocr_contract.py`로 메웠다 — 그 전에는 `is_available()`뿐이었다) |

   **주장에는 그것을 지키는 시험 이름을 붙인다.** 산문으로 《여기가 사각지대》라고 적으면 코드가
   바뀌어도 문장만 남는다(이 표도 그래서 두 달 동안 엉뚱한 곳을 가리켰다). 위 표가 거짓이 되면
   그 줄에 적힌 시험이 깨지도록 두는 것이 목표다.

   **아직 시험이 지키지 않는 것:** 실제 모델(RTMDet·PARSeq·TrOCR·PaddleOCR 가중치)의 인식
   품질. 엔진을 올린 뒤 **실제 이미지로 1쪽**과 `scripts/eval_cer.py`가 그 자리다. 배치·파이프라인
   경로가 `DummyOcrEngine`을 쓰는 것도 그대로다(뼈대만 잰다).
4. 스키마·저장 형식이 바뀌면 `docs/DECISIONS.md`에 마이그레이션 경로를 남긴다.
   기존 서고를 열 수 없게 되는 변경은 **되돌릴 수 없다.**

## 백엔드 모듈 구조 (src/app/)
server.py는 FastAPI 앱 생성 + 라우터 마운트 + 미들웨어만 담당하는 조립 파일.
실제 API 엔드포인트 235개가 9개 라우터 모듈에 분산 (2026-10-17 기준 실측):

```
src/app/
├── server.py            ← 앱 생성 + 라우터 마운트 + configure()
├── _state.py            ← 공유 상태 + 헬퍼 + LLM 프롬프트/캐시/동적 토큰 계산
├── __main__.py          ← CLI 진입점 (python -m app serve)
└── routers/
    ├── library.py       ← 서고/설정/백업/휴지통 + 스키마 검증 + 연결 설정·앱 업데이트·엔진 추가 설치·OAuth 프록시·Ollama 로그인·모델 골라 받기·판정 모델 상태·고르기 (31 라우트)
    ├── documents.py     ← 문헌 CRUD/페이지/교정/서지/파서 + 텍스트레이어 진단·가져오기·입히기 + 권 추가·회전 + 경계 규칙 + 찍은 자리·규칙 제안 + 강독 노트 들이기·장별 내보내기·틀로 내보내기 (48 라우트)
    ├── composition.py   ← 편성 — 내용 트리·경계 색인·넣기·옮기기·지우기 + 제안·목차·적용·자동 트리·신호 도출·LLM 표지 묻기·구조 통째로 묻기·애매한 후보 2차 판정(내보내기·들이기·불러오기) + 규칙 미리 보기·말로 규칙 넣기 + 쪼개기·리셋 (20 라우트)
    ├── interpretations.py ← 해석 CRUD/레이어/의존/엔티티/관계·태그 + 개념 병합·커넥톰 대조 (24 라우트)
    ├── llm_ocr.py       ← LLM 상태 + OCR 엔진·실행·권단위 일괄·백업 되돌리기·판독 지침·LLM 교정 패스·판독 계획·말로 작업 지시·노트 틀 (27 라우트)
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

## 모듈 지도 — 표는 `docs/module-map.md`

모듈마다 《무엇을 하고 무엇을 지키는가》 표(추출 모드·OCR 품질·판정 모델·말로 작업 지시·코어 스키마)는
**`docs/module-map.md`**로 옮겼다(2026-10-11 — 매 세션 자동으로 읽히는 이 파일을 줄이려고). 그 모듈을
고칠 때 그 표를 읽는다. 결정의 지금 결론은 **`docs/CHECKPOINTS.md`**. 아래는 모듈을 가로지르는 규칙이라 여기 둔다.

- **사전은 지식이고 정책은 문헌의 것**: `strict`만 동치, `loose`·`script`는 힌트. 승인은 `documents/{doc_id}/variant_approvals.json`에만.
- **Ollama 기본 비전 모델은 클라우드(`kimi-k3:cloud` — 글 기본과 같다)다**(D-114·D-143, v1.4.3까지는 `gemma4:cloud`). 로컬 기본을 두면 처음 켠 PC가 9.6GB를 받기만 한다. 클라우드 기본은 목록에 있어도 `_pick_vision_model`이 한 번 불러 보고(로그인 없음·은퇴면 실패) 로컬 후보로 내려간다.
- **Ollama 텍스트 호출은 답이 길면 문맥 창도 올린다**(`providers/ollama.py::_gen_options`, 2026-09-12). 기본 num_ctx 4,096이라 num_predict를 크게 줘도 《프롬프트 + 답》이 4,096을 넘는 순간 잘린다 — 사전형 주석이 매번 2,883토큰에서 끊겼다. 긴 JSON을 받는 호출은 잘린 답에서 완성된 항목만 건지는 파서도 둔다(`core.llm_json_items.recover_truncated_items`).
- **사고(thinking)는 전역 스위치가 아니다**: 기본 끔(D-074). 정밀 판독과 사용자가 명시한 호출만 켠다. **다만 Ollama 프로바이더에는 폴백이 있다** — `response`가 비고 `thinking`만 찼을 때 그것을 본문으로 쓴다(`providers/ollama.py` 텍스트·스트리밍·비전 셋). 사고에 num_predict를 다 쓴 reasoning 모델의 방어책이고, 비전 경로는 `allow_thinking_fallback=False`로 끌 수 있다. 다른 세 프로바이더에는 없다. 한때 이 줄이 「폴백은 어디에도 없다」로 적혀 있었다(Codex 지적 2026-09-22 — 문서를 믿은 호출자가 사고문을 결과로 받는다).

### Claude 세션에서 — 《애매한 후보 판정해 줘》 (D-137)

사용자가 편성 화면에서 「판정 모델로 고르기」를 돌린 뒤(또는 「애매한 후보 내보내기」를 한 번 누른 뒤) 이렇게 말하면:

1. `uv run python scripts/escalate_review.py export --doc <문헌> --part <권> --out <scratchpad>/esc.txt`
   (`--library` 생략 시 앱이 마지막으로 연 서고. 일기면 `--book-type diary`, 문집이면 `collection`)
2. esc.txt의 **지시문 그대로** 세션이 직접 판정해 `{"batch":"esc-…-N","answers":[{"id":…,"start":"yes"|"no","conf":…}, …]}`를
   `answers.json`에 쓴다 — 모든 id에 답하고, `batch`는 묶음 머리의 표지를 그대로 옮긴다(다른 권의 표지면
   들이기가 거부한다). **지시문·후보 줄을 answers.json에 넣지 않는다**(내보낸 글로 보고 거부한다).
   확률을 찾아보거나 규칙을 바꾸지 않는다.
3. `uv run python scripts/escalate_review.py import --doc <문헌> --part <권> --in answers.json` — 예·아니오·누락·거부 수를 사용자에게 옮긴다.
4. 사용자에게: 화면 「판정 들이기 ▸ 저장된 판정 불러오기」로 체크 제안을 보고 「적용」. **경계는 세션이 저장하지 않는다.**

**외부 모델(API·Ollama·codex 등)을 부르지 않는다.** 사용자가 그 실행에 쓸 모델을 명시적으로 이름 대면
그 한 번만 쓰고, 기본값으로 삼지 않는다.

### 코어 스키마 규약 (D-128)

**질의 표면은 좁게 유지한다**(3항). 읽기 문은 `entity.py`의 셋뿐이고(`QUERY_SURFACE`)
임의 순회를 여는 함수·엔드포인트가 없다. 관계를 따라가는 일이 생기면 **목록을 받아 거르는
순수 함수**로 만든다 — 저장소 경로를 안 받으므로 구조상 순회가 불가능하다.

**파트너 수·집중도는 판정에 넣지 않는다**(7항). 계통마다 6배·2.4배씩 달라 설계 근거가 되지
못하는 값이다. `promotion_metrics()`는 재서 **보여주기만** 하고 `evaluate_promotion()`의 판정에는
실질 무게 하나만 들어간다 — 이름은 `METRICS_NOT_USED_FOR_VERDICT`에 적혀 있다.

**저장 계층에 필드를 더할 때는 그 필드를 모르는 화면 코드가 무엇을 보내는지 함께 본다.**
`entity-manager.js::_collectFormData`가 Concept 저장에 `concept_features: null`을 무조건
보내고 있었고, 승격 근거가 거기 들어가는 순간 **설명 한 줄만 고쳐도 기록이 사라지는** 길이
됐다(D-128 구현 기록 4). 예외도 경고도 나지 않는다.

## 파일 다루기 — 되풀이하지 말 것

| 규칙 | 왜 |
|---|---|
| **JSON 저장은 `core.document.write_json_atomic()`**. `Path.write_text()` 금지 | write_text는 먼저 0바이트로 자른다. 도중에 죽으면 manifest가 빈 파일이 되고 문헌이 통째로 열리지 않는다(D-069) |
| **PDF는 `resolve_part_pdf(doc_path, part_id)`로 연다**. `glob("*.pdf")[0]` 금지 | glob은 순서를 보장하지 않고 part_id도 안 본다. 다권본에서 엉뚱한 권을 읽는다(D-069) |
| **`fitz.open()`은 `with`로** | 예외 경로에서 핸들이 남으면 Windows가 그 PDF를 잠근다 |
| **기존 PDF에 덧쓸 때는 `page.wrap_contents()` 먼저** | 원본이 남긴 좌표 변환에 끌려 들어간다(D-068) |
| **쪽 이미지는 `load_page_image_from_pdf`(또는 `rotate_page_image`)로 — `get_pixmap` 직접 호출 금지. 회전 값은 `page_rotation(doc, part, page)`로** | 권에 저장된 회전(`parts[].rotation`, D-123)과 쪽 범위 회전(`parts[].rotation_ranges`, D-126)을 그 함수가 얹는다. `part_rotation`만 읽으면 책 중간의 접은 그림·가로 표 구간에서만 좌표계가 어긋난다. 직접 렌더하면 OCR·화면·내보내기 중 그곳만 돌리기 전 좌표계가 된다. L2·L3의 `rotation` 도장이 지금 회전과 다르면 파이프라인이 거부한다 |
| **L2 bbox를 쓸 때 배율은 L2의 `image_width`로 구한다**. 2.0 하드코딩 금지 | 스캔 PDF는 내장 이미지 해상도로 렌더하므로 쪽마다 배율이 다르다. 기록이 없는 옛 파일만 뷰포트×2.0(D-087) |
| **화면에 넣는 파일명·OCR 원문은 이스케이프** | 드롭한 파일명이 문헌 제목이 되어 `innerHTML`로 들어간다(D-069) |
| **로컬 서비스는 `127.0.0.1`로 부른다**. `localhost` 금지 | Windows는 `localhost`를 IPv6(::1)부터 시도한다. IPv4에만 뜬 서비스(Ollama)면 제한 시간을 다 쓰고서야 IPv4로 넘어가 **호출마다 2초**를 버린다(실측 2.11s vs 0.04s, D-109) |
| **검증용 서버는 `CTB_CONFIG_DIR=<임시 폴더>`로 띄운다** | 설정 파일(`~/.classical-text-browser/config.json`)은 하나라, 복사본 서고로 띄운 서버가 《마지막 서고》를 덮어 아이콘으로 켠 앱이 임시 폴더를 열었다(2026-09-10). LLM 사용 기록도 서고가 없으면 같은 폴더로 간다(`usage_tracker.default_usage_log_path`) — pytest는 `tests/conftest.py`가 이 변수를 임시 폴더로 돌리고, 세션 맨 뒤 테스트가 홈 파일 크기가 변하지 않았는지 잰다. 서고 없이 `LlmConfig()`로 도는 라우터 테스트가 mock 응답 2,127행을 홈 기록에 섞었다(2026-09-10 확인) |
| **빠른 시험은 바깥 네트워크에 닿지 않는다** — 실제 사이트·API가 필요한 시험은 `@pytest.mark.network`(그리고 `slow`) | 이 PC에는 실제 LLM 키가 있다. 가짜 라우터를 빠뜨린 시험이 《200 또는 400》을 둘 다 통과로 받으며 매 verify마다 실제 LLM을 불렀다(2026-10-11, 5.2초). `tests/conftest.py`가 표지 없는 시험의 바깥 소켓 연결을 막는다(로컬 127.0.0.1은 허용 — **단 Ollama 11434·OAuth 프록시 10531~10540은 로컬이어도 막는다**, 그 데몬이 바깥으로 넘겨 부르므로. 2026-10-11) |
| **`.bat` 파일은 ASCII만** (주석도 영어) | `chcp 65001`의 cmd가 다중바이트 줄에서 위치를 잘못 세어 뒤쪽 줄 중간부터 읽는다. 새 콘솔에서만 재현(maintenance §1.6) |
| **배포되는 진입점은 맨 앞에서 `core.console.force_utf8_console()`** | 한국어 Windows 콘솔은 cp949다. 한글은 있지만 `—`·`《》`·`✓`는 **없어** 그 글자를 `print`하면 즉사한다. 이 PC는 `PYTHONUTF8=1`이 박혀 있어 **겪지 않는다** — 「내 PC에서 잘 돌았다」가 증거가 못 되는 자리다. 셋을 배포한다: `warmup_paddle.py`·`cli/__main__.py`·`app/__main__.py`(+`ctb_setup.py`는 홀로 도는 exe라 직접 품는다). `test_doc_drift.py`가 본다 |
| **`.ps1`은 UTF-8 BOM + CRLF** | BOM이 없으면 PowerShell 5.1이 ANSI로 읽어 한글이 깨진다. **구문은 멀쩡해 그냥 돈다** — 눈으로 보기 전엔 모른다. `.gitattributes`가 CRLF를, `test_doc_drift.py`가 BOM을 못박는다 |
| **LLM을 기다린 뒤 저장하는 라우트는 파일을 다시 읽어 그 위에 병합한다** | 아까 읽은 데이터를 저장하면 기다리는 동안 들어온 수동 주석이 오류 없이 사라진다(D-127). 해석 저장소 L5~L7 저장도 `write_json_atomic()`이다 |
| **LLM 답의 항목 목록은 `core.llm_json_items.parse_llm_items()`로 꺼낸다** | 기형 항목(null·문자열) 거부·잘린 답 복구·`status`(ok·recovered·no_json)를 한 곳에서. 기능마다 파서를 복제하면 한쪽만 고쳐진다(D-127) |
| **글자 좌표는 코드포인트(주석·현토·번역·표점·교정·인용 모두). 화면 JS는 편집기마다 둔 도우미(`_annChars`·`_htChars`·`_trChars`·`_puChars`·`_corrChars`, 모두 Array.from)로 센다 — 인용 편집기는 `Array.from`을 직접 쓴다. 화면에 보이려고 자르는 미리보기도 같다** — `.length`·`[i]`·`.slice` 금지 | 확장 한자(CJK 확장 B)는 UTF-16에서 두 단위라 그 뒤 주석이 한 칸 어긋난다(D-127). 주석 API는 `?part_id=`를 받는다 — `"main"` 고정 금지 |

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
- 단위(unit): 코어 스키마의 해석용 텍스트 단위. **v1.3(D-092)부터는 저장하지 않고** 경계 목록(`core/boundaries.py`)에서 만든 읽기 보기다. 단위의 id = 시작 경계의 id. 단위는 `source_ref`로 원본을 추적한다.
- 편성(composition): 경계를 정하는 일. **원본 저장소의 것이다**(D-097) — 해석 저장소는 그것을 참조만 하고 표점·현토·번역·주석을 담당한다.
  사이드바 「내용」 트리는 **문헌 > 권 > 단위**다(D-098). 저작 묶음은 층위 1의 《묶음》 경계가 나타낸다 — Work 엔티티는 D-099에서 없앴다.
  코드·API·스키마의 이름도 `unit`이다(D-093 — v1.2까지는 `text_block`·TextBlock). 저장 파일이 단위를 가리키는 필드는 아직 `block_id`다(B-003)
- 「Block」이라고만 쓰지 말고 항상 위 세 이름 중 하나를 사용할 것
- 해석 편집기 다섯(표점·현토·번역·주석·인용)의 《지금 단위》는 사이드바 「내용」 트리가 정한다(D-096).
  트리가 `unit-selected` 이벤트를 쏘고 감춰 둔 `<select>`에 값을 넣는다 — 편집기의 기존 《고르면 불러온다》 길을 그대로 쓴다

## 작업 방식: CLI를 적극 활용할 것
- 코드를 작성한 뒤 반드시 실행해서 확인하라. 작성만 하고 검증 없이 넘어가지 마라.
- API 엔드포인트를 만들면 curl이나 테스트 스크립트로 직접 호출해서 응답을 확인하라.
- 웹 스크래핑 파서를 작성할 때는 대상 사이트의 HTML 구조를 먼저 curl/wget으로 가져와서 확인하라.
- JSON 파일을 생성하면 jsonschema로 검증하라.
- 테스트를 작성했으면 실행해서 통과하는지 확인하라.
- 「될 것 같다」로 끝내지 말고, 실제로 동작하는 것을 보여줘라.

## 에이전트 작업 계약 (2026-10-01)
1. **추측하지 말고 원본 코드를 읽는다.** 이 문서의 표·요약은 위치를 좁혀 줄 뿐 근거가 아니다(기능 맵은 추후).
2. **완료 보고에는 영수증을 붙인다** — `uv run python scripts/receipt.py`가 빠른 계층 pytest(`-m "not slow"`)·ruff·
   `check_doc_drift`·금지 패턴(`tests/test_forbidden_patterns.py`)을 돌려 `logs/receipts/<UTC>_verify.json`을 쓴다.
   그 경로와 단계별 요약을 보고에 옮긴다. 영수증 없는 《완료》는 완료가 아니다.
3. **판정자가 없는 작업은 제안만 한다** — 판독 확정(L4)·이체자 승인·편성 경계 확정·시각 품질은 사람이 정한다.
4. **산문 규칙이 시험으로 옮겨지면 산문을 줄인다.** 위 「파일 다루기」 표의 네 줄(write_json_atomic·
   get_pixmap·glob pdf·localhost)은 `tests/test_forbidden_patterns.py`가 지킨다 — 새 규칙도 시험이 먼저다.

## Git 커밋 규칙
형식: <타입>: <설명>
타입: feat / fix / data / docs / refactor / test
예시: feat: Phase 2 — 서고 초기화 CLI 구현

## 인지 부채 지도

> 2026-07-04 최초 감사 · 2026-09-04 3차 감사(v1.3.0) · 2026-10-11 전수 검토로 정리. AI 작성 코드와 사용자 이해의 간극 요약.
> 3차 감사 HTML(퀴즈 포함)은 `git show 11944f1:docs/_archive/2026-09-04_cognitive-debt-audit/cognitive-debt-audit.html`. 2026-10-11 전수 검토가 찾은
> 동작 결함은 `docs/backlog.md` B-012~ — **시험이 초록인데 틀린 자리**가 대부분이다.

### 실제 하는 일 (문서에 없는 층위)
- "서버 시작" = 최대 3개 프로세스: start_server.bat가 uvicorn 외에 OpenAI OAuth 프록시
  (`npx -y openai-oauth`, 포트 10531–10540 스캔, Bearer 토큰 `oauth-proxy` 하드코딩)와
  SikuRoBERTa 표점 Docker(punctuation-service/.env 존재 시)를 자동 기동.
- 프론트(static/)가 약 4.7만 줄 — index.html 약 5.1천 줄 단일 파일, workspace.css 약 8.2천 줄,
  JS 34개(약 3.3만 줄). 테스트 110파일 — 그중 화면 JS를 node로 돌리는 것(`tests/js_harness.py`)은
  `tests/test_annotation_editor_js.py`(2026-09-16 Codex 교차검증 반영 때 처음)·
  `tests/test_entity_manager_js.py`(D-128)·`tests/test_structure_jev.py`·
  `tests/test_read_path_writes.py`(화면을 열기만 해도 쓰던 것, 2026-09-30)·
  `tests/test_correction_saves.py`(자유 편집 교정이 글자 교정 보기에 안 보이던 것·확정본을 다시 쓰면 교정이 어긋나던 것, 2026-10-02)·
  `tests/test_composition_apply_plan_js.py`(편성 ③ 《바뀐 것》과 「적용」이 다른 집합을 세던 것, 2026-10-05)·
  `tests/test_sweep_20261011.py`(2026-10-11 전수 결함 B-012~B-077과 릴리스 리뷰 B-078·시험 정리 B-079의 회귀 — 인용·현토·번역 좌표, 번역 집계, 시작 행 옮기기,
  사전 활성화, 백업·.env·휴지통 데이터 손실, 이스케이프)·
  `tests/test_default_models_20261018.py`(《자동》 기본 모델과 앞 순위 실패 알림 문구, D-143)·
  `tests/test_model_choice_memory_20261018.py`(작업 화면 「모델」 칸이 새로고침 뒤에도 고른 모델을 기억, D-143), **CI 없음.**
  (이미지 기본 kimi-k3는 `tests/test_vision_default_20261018.py`, 글 기본이 없을 때 glm 대체는
  `tests/test_text_fallback_20261018.py`가 본다 — 둘 다 화면 JS는 돌리지 않는다.)
  화면 《마크업》을 읽는 것도 둘이다 — `tests/test_ui_reachability.py`(조작 단추에 사람이
  닿을 수 있는가, B-008)와 `tests/test_connectome.py`(화면이 그 라우트를 부르는가).
  (2026-10-05 재실측. 2026-07-26 v1.2.0 감사 때 직전 대비 프론트가 줄어든 것은
  D-069에서 죽은 코드 약 1,000줄을 걷어냈기 때문이다.)

### 안다고 착각하기 쉬운 지점
3. LLM 결과 캐시(TTL 600초·최대 256건, `_state.py`의 `_llm_result_cache`) — 같은 텍스트 재요청 시 10분간
   옛 결과가 돌아올 수 있음. (1·2번 — `_parse_llm_json` 이중 정의와 잘린 답의 조용한 부분 반환 — 은
   2026-07-07 해소돼 지웠다: ee8db13·56000f8. 번호는 다른 문서가 가리키므로 그대로 둔다.)
4. "가져오기" 버튼의 "준비중"은 UI만 봉인(D-037). hwp-import.js 약 1천 줄과 백엔드
   엔드포인트(`/api/documents/import-hwp` 등)는 살아 있음 — 재구현하지 말고 복원할 것.
   **단 D-055 이후 이 버튼은 프로필에 따라 동작이 갈린다**: 「추출」 모드에서는
   hwp-import 다이얼로그가 아니라 `POST .../text-import/from-text-layer`(단순 추출)에
   연결된다. hwp-import 봉인 자체는 그대로다.
7. **기본 OCR 엔진은 문헌 성격을 보지 않는다** — "설치된 것 중 첫 번째"(`registry.py`).
   torch가 있으면 `ndlkotenocr-full`(고전적 전용, **한글 인식 불가**)이 기본이 된다.
   근현대 한글 문헌을 아무 설정 없이 OCR하면 결과가 깨진다. 배치 라우트는 시작 시점에
   경고하지만(D-055), 페이지 단위 라우트에는 그 경고가 없다.
8. **OCR은 L3 레이아웃이 없으면 조용히 실패한다** — 200 OK에 `status: "partial"`,
   `errors: ["L3 레이아웃을 찾을 수 없습니다"]`, 결과 0건. 예외가 아니므로
   호출부가 `ocr_results`를 확인하지 않으면 성공으로 오인한다.
9. **`el.hidden = true`만으로는 안 숨는다** — `workspace.css`가 `.mode-tab`,
   `.extract-panel` 등에 `display: flex`를 지정하고 있어, 작성자 스타일시트가
   브라우저 기본 `[hidden] { display: none }`을 우선순위로 덮어쓴다. 지금은 파일
   맨 위의 `[hidden] { display: none !important }`가 막고 있으니 **그 줄을 지우면
   숨김이 전부 깨진다.** jsdom은 이 결함을 재현하지 못하므로 브라우저 확인이 필요하다.
10. **정적 파일은 `_NoCacheStaticFiles`로 서빙된다**(server.py) — 기본 `StaticFiles`는
   `Cache-Control`을 붙이지 않아 브라우저가 고친 JS·CSS를 다시 받지 않는 사고가 있었다.
   `?v=` 쿼리에 의존하지 말 것.
12. **추출 패널에서 탭을 열 때는 `_switchMode()`를 직접 부르지 말 것**(D-057) —
   탭 하이라이트 처리가 그 함수가 아니라 `initModeBar()`의 클릭 핸들러 안에 있다.
   직접 부르면 화면은 바뀌는데 탭 표시가 그대로여서 《지금 어느 탭인가》가 어긋난다.
   `.mode-tab[data-mode="..."]`를 찾아 `.click()`하면 기존 경로를 그대로 탄다.
   또한 검수 목록의 확인 기록은 **localStorage**(`ctb.reviewed.<doc>.<part>`)에
   글자 수와 함께 저장된다 — 다시 OCR로 내용이 바뀌면 확인이 저절로 풀리게 하기 위함.
11. **배치 OCR의 《건너뛴다》는 두 조건이다**(D-057) — L2 결과가 있고 **그 결과가 지금
   L3와 맞을 때**만 건너뛴다. `ocr/layout_staleness.py`가 L2의 `layout_block_id` 집합과
   L3의 `block_id` 집합을 비교한다. 스키마에 타임스탬프가 없어서 이 방식을 쓴다
   (`layout_page`·`ocr_page` 둘 다 `additionalProperties: false`). 판정이 애매하면
   《안 바뀌었다》로 둔다 — 오판하면 쪽마다 LLM 호출이 다시 나가기 때문이다.
5. 서지 파서(`src/parsers/` korcis·archives_jp·kyujanggak·kostma·jsg·ndl)는 외부
   사이트 HTML 구조 의존 — 사이트 개편 시 침묵 파손. 테스트가 실제 네트워크를 안 타면 못 잡음.
6. `llm_usage_log.jsonl`은 서고 루트에, 서고 미설정 시 `~/.classical-text-browser/`에 기록 —
   예산(MONTHLY_BUDGET_USD) 추적이 서고별로 분산됨.

### 인지 부채 핫스팟 (위험 순)
| 순위 | 경로 | 위험 |
|---|---|---|
| 1 | `src/app/_state.py` (약 930줄) | 전역 상태+프롬프트+캐시+JSON 파서 응집 |
| 2 | `src/app/static/` 프론트 모놀리스 | CI 없음. 화면 JS를 node로 돌리는 시험은 위 《실제 하는 일》의 몇 파일뿐이고 index.html(약 5.1천 줄) 대부분은 시험 밖이다 — 정식 프론트 스모크 테스트는 미결(D-053 착수 조건). 2026-10-11 전수 검토의 동작 결함(B-012·B-016·B-018·B-019 등) 다수가 여기서 나왔다 |
| 3 | `start_server.bat` | 암묵 부수효과 3종(프록시·Docker·포트 스캔), 실패 시 원인 추적 곤란 |
| 4 | `src/parsers/` | 외부 사이트 의존 침묵 파손. 시험 픽스처가 실제 응답에 없는 키를 넣어 결함을 가린 사례가 있다(KORCIS 판식정보) |
| 6 | 봉인된 「외부 파일 → 새 문헌」 가져오기 | 존재를 모르면 중복 재구현, 알면 진입점 복원만으로 재개(D-037). 백엔드는 살아 있고 `_openHwpImportDialog()` 호출자가 0건일 뿐이다. **추출 모드의 「텍스트 바로 가져오기」(`/text-import/from-text-layer`)와 혼동하지 말 것** — 그쪽은 정상 동작하는 별개 경로다 |
| 7 | **합성 입력만으로 검증하는 습관** | D-068이 여기서 났다 — 시험용 PDF를 PyMuPDF로 만들어 써서, 실제 스캔본에만 있는 좌표 변환을 자동 테스트가 영영 만나지 못했다. 파일 형식·외부 엔진을 다루는 코드는 **실물로 한 번 돌려야** 한다 |
| 8 | **강독 결과 JSON을 저장 형식으로 오해하기** (D-131) | `core/reading_ingest.py`가 받는 JSON은 **LLM 답 형식**이지 저장 스키마가 아니다 — 들이면 L4·편성 경계·L6·L7로 흩어지고 노트는 매번 층에서 조립한다. 노트 형식이 바뀌면 `export/reading_note.render_*`만 고친다. 《노트를 파일로 두자》는 새 스키마는 사용자가 한 번 거절했다(2026-09-30). 장 목록은 두 곳에 있다: 원문 내보내기는 `read_plan/{권}.json`의 chapters, 강독 노트는 층위 1 경계. 들이기는 답의 chapter 제목이 계획의 장 제목과 **같을 때만** 계획의 쪽을 빌려 장 경계를 세우고(다르면 답의 가장 앞 쪽), 계획의 chapters는 고치지 않는다 — 제목을 다르게 적은 답은 두 장 목록을 어긋나게 한다 |
