# 유지보수 안내

> 이 저장소를 **고칠 때** 지켜야 하는 것들. 무엇을 만들지가 아니라
> 무엇을 깨뜨리지 않을지에 대한 문서다.
> 대상: 이 코드를 손대는 사람(사람이든 에이전트든).
> 설계 근거는 [DECISIONS.md](DECISIONS.md), 사용법은 [user-guide.md](user-guide.md).
> 최종 확인: 2026-07-26 (v1.2.0)

---

## 0. 되돌릴 수 없는 것 넷

먼저 이것부터. 나머지는 고치면 되지만 아래는 고칠 수 없다.

| 무엇 | 왜 되돌릴 수 없나 |
|---|---|
| `L1_source/` 안의 원본 파일 | 사용자가 스캔한 논문·고서 그 자체다. 덮어쓰면 끝이다. **읽기만 한다.** |
| `manifest.json` | 깨지면 그 문헌이 통째로 열리지 않는다. git 커밋 이전이면 복구 경로도 없다. |
| 저장 형식·스키마 변경 | 기존 서고를 열 수 없게 되는 변경은 마이그레이션 경로 없이 내보내면 안 된다. |
| 영구 삭제 | 이 저장소의 삭제는 **전부 휴지통 이동**이다. `rm`·`Remove-Item` 금지. |

---

## 1. 파일을 다룰 때 — 되풀이하지 말 것

다섯 가지 모두 **실제로 사고가 난 뒤** 적힌 것이다. 각각의 사고 기록이 괄호 안에 있다.

### 1.1 JSON 저장은 `write_json_atomic()` (D-069)

```python
from core.document import write_json_atomic
write_json_atomic(path, data)          # ✅
path.write_text(json.dumps(data))      # ❌ 절대 금지
```

`Path.write_text()`는 **먼저 파일을 0바이트로 자르고** 쓴다. 그 사이에 정전·강제종료·
디스크 부족이 나면 `manifest.json`이 빈 파일로 남는다. `write_json_atomic()`은
임시 파일에 다 쓰고 `fsync` 한 뒤 `os.replace`로 갈아 끼우므로, 실패해도 예전
내용이 그대로 남는다.

다섯 모듈(`document`·`entity`·`interpretation`·`library`·`snapshot`)의 `_write_json`이
전부 이 하나를 부른다. **새 모듈에서 또 복제하지 말 것.**

### 1.2 PDF는 `resolve_part_pdf(doc_path, part_id)`로 연다 (D-069)

```python
from ocr.image_utils import resolve_part_pdf
pdf = resolve_part_pdf(doc_path, part_id)   # ✅
pdf = list(source_dir.glob("*.pdf"))[0]      # ❌
```

`glob()`은 순서를 보장하지 않을뿐더러 **`part_id`를 아예 보지 않는다.**
卷上·卷下가 함께 있는 문헌에서 卷下 5쪽을 OCR 하면 卷上 5쪽 이미지가 엔진에
넘어가고, **오류 없이** 그럴듯한 결과가 저장된다. 원본과 텍스트의 대응이
조용히 끊어지는 것이라 나중에 발견하기가 가장 어렵다.

### 1.3 `fitz.open()`은 `with`로

```python
with fitz.open(str(pdf_path)) as doc:   # ✅
    ...
```

예외 경로에서 핸들이 남으면 **Windows가 그 PDF를 잠근다.** 이후 문헌 삭제·이동이
부분 실패한다. 이 저장소는 Windows가 기본이고 같은 PDF를 반복해서 연다.

### 1.4 기존 PDF에 덧쓸 때는 `page.wrap_contents()` 먼저 (D-068)

스캔 PDF는 픽셀 단위로 작업하려고 내용 스트림 첫 줄에 배율을 걸어 두고
되돌리지 않는 일이 흔하다.

```
0.24 0 0 0.24 0 0 cm      ← q 없이, 되돌리는 Q도 없다
q 2064 0 0 2893 0 0 cm /I0 Do Q
```

그 뒤에 덧붙이는 **모든 것이 0.24배로 줄어든다.** 실제로 텍스트 레이어가
495×694pt 쪽의 왼쪽 아래 구석에 2.9pt 크기로 박혔다. `page.insert_text()`는
자기 출력을 `q…Q`로 감싸 무사하지만 `TextWriter.write_text()`는 감싸지 않는다.

### 1.5 화면에 넣는 외부 문자열은 이스케이프 (D-069)

신뢰 경계 **밖**인 것: 드롭한 파일명(→ 문헌 제목), OCR 원문, 외부 사전·표점
임포트, 서버 오류 메시지. `innerHTML`에 넣기 전에 각 파일의 이스케이프 헬퍼를 쓴다.

`<img src=x onerror=…>.pdf`라는 이름의 파일을 끌어다 놓으면 스크립트가 돌았다.

---

## 2. 의존성을 올릴 때

OCR 스택 셋(**paddlepaddle+paddleocr** / **onnxruntime+opencv** / **torch+transformers**)이
전이 의존을 공유한다 — `numpy`·`protobuf`·`pyyaml`·`typing-extensions`·`setuptools`·
`networkx`·`pillow`.

**하나를 올리면 다른 스택이 조용히 죽는다.** 엔진 등록 실패는 예외가 아니라
`available=False`로 나타나고, 라우터는 말없이 다음 엔진으로 넘어간다(D-044·D-056).
즉 **화면에는 아무 일도 없어 보이는데 결과만 나빠진다.**

### 이미 겪은 결합 지점

| 무엇 | 결과 |
|---|---|
| `paddleocr` 2.x → 3.x | `show_log`·`use_angle_cls`·`use_gpu` 제거, `ocr.ocr()` → `ocr.predict()` |
| `paddleocr` 3.7이 `pyyaml==6.0.2` 고정 | 이 저장소의 하한도 6.0.2로 내림 |
| `paddlepaddle` 휠이 cp312까지 | `requires-python`에 `<3.13` (D-059) |
| Windows + paddlepaddle 3.x | OneDNN이 PIR 속성 변환 미지원 → `FLAGS_use_mkldnn=0` 회피 |
| `torch`는 전용 인덱스(`pytorch-cu124`) | CUDA 버전을 바꾸면 `[[tool.uv.index]]` URL도 함께 |
| `opencv-contrib-python` ↔ `opencv-python-headless` | **같은 `cv2`를 두 배포판이 제공.** 한쪽을 지우면 공유 디렉터리가 사라져 남은 쪽까지 깨진다 |

### 절차

```bash
uv lock --upgrade-package <이름>   # 전체 갱신 금지 — 무엇이 깼는지 가려진다
uv run python -m pytest
# 그리고 실제 이미지로 OCR 1쪽 ← 아래 3장 참조
```

---

## 3. 자동 테스트가 못 잡는 것

**655개가 통과해도 안심할 수 없는 자리들이다.** 전부 실제로 사고가 났다.

| 사각지대 | 왜 못 잡나 | 무엇으로 대신하나 |
|---|---|---|
| **파일 형식을 다루는 코드** | 시험용 PDF를 PyMuPDF로 만들면 실제 스캐너 출력의 특성이 없다. D-068이 정확히 여기서 났다 | **실제 스캔본 1쪽**을 태우고 산출물을 직접 열어 본다 |
| **OCR 엔진 API** | 검출(`line_detector`)은 순수 함수만 검증하고, 배치·파이프라인은 더미 엔진을 쓴다 | 엔진을 올린 뒤 **실제 이미지로 1쪽** |
| **다권본** | 시험 문헌이 대부분 단권이다 | 2권짜리로 **같은 쪽 번호의 결과가 다른지** 확인 |
| **프론트엔드 전체** | 테스트 0개, CI 없음 | jsdom 일회성 하네스. **정식 스모크 테스트는 미결**(D-053) |
| **「없다」의 증명** | 정적 검사는 «볼 곳»만 좁혀 준다 | 오탐을 사람이 하나씩 걸러야 한다 |

### 특히 — 침묵하는 실패

이 저장소에서 나온 심각한 결함은 **전부 같은 모양**이었다.
오류를 던지지 않고, 그럴듯한 답을 내고, 테스트는 초록이었다.

- `if (!x) return` — 화면 요소가 사라져도 조용히 넘어간다. 죽은 코드 1,000줄이
  이렇게 살아남았다(D-069).
- `typeof f === "function"` — 없는 함수를 삼킨다. 버튼이 그냥 안 눌렸다(D-063).
- `except Exception: pass` — 부분 결과가 «전부»로 반환된다.
- `available=False` — 엔진이 죽어도 다음 것으로 넘어간다.

**null 가드와 폴백은 실패를 침묵으로 바꾼다.** 정말 없어도 되는 것에는 맞고,
반드시 있어야 하는 것에는 틀리다. 새로 쓸 때 «이게 없으면 화면이 잘못된
결과를 보여주는가»를 물어보고, 그렇다면 가드 대신 **경고를 남긴다.**

### 그래서 넣은 방어

| 무엇 | 어디 | 잡는 것 |
|---|---|---|
| 산출물 재검사 | `text_layer_pdf._audit_output()` | 만든 PDF를 다시 열어 글자 크기·덮은 넓이·**그 자리의 잉크 밀도**를 잰다 |
| 원자적 쓰기 | `core.document.write_json_atomic()` | 저장 중 중단으로 인한 파일 손상 |
| 응답 경합 가드 | 쪽 로더 3종 | 늦게 온 응답이 새 쪽을 덮는 것 |
| `Cache-Control: no-store` | `server.py` 미들웨어 | 고쳤는데 화면에 반영 안 되는 것 |

**한계를 분명히 해 둔다** — 이것들은 **이미 아는 모양**만 잡는다.
새로운 종류의 침묵하는 실패는 여전히 사람이 산출물을 봐야 안다.

---

## 4. 데이터가 상했을 때

| 증상 | 어디를 보나 |
|---|---|
| 문헌이 안 열린다 | `manifest.json`이 빈 파일인지 확인. 그 문헌의 `.git`에서 직전 커밋을 꺼낸다 |
| OCR 결과가 갑자기 나빠졌다 | 추출 모드 「되돌리기」는 **다시 돌리기 직전**으로만 간다(D-065). 그 전 차수는 `.page_backup/`에 없다 |
| 레이아웃이 화면과 어긋난다 | L3의 `image_width`와 PDF 뷰포트의 비율을 본다. 데이터를 고치지 말고 **환산**해야 한다(D-067) |
| 텍스트 레이어 PDF가 이상하다 | 앱이 이미 재서 경고를 띄운다. 없으면 `_audit_output()`을 직접 호출해 본다 |
| 서고 폴더가 안 지워진다 | Windows가 PDF 핸들을 잡고 있다. `fitz.open()`이 `with` 밖에서 열린 곳을 찾는다 |

원본 저장소·해석 저장소 모두 git이다. **커밋된 것은 되돌릴 수 있다.**
커밋되지 않은 것은 되돌릴 수 없으므로, 위험한 작업 전에는 커밋이 있는지 본다.

---

## 5. 릴리스 절차

1. `uv run python -m pytest` — 전부 통과
2. `uv run ruff check src/ tests/`
3. JS 문법: `for f in src/app/static/js/*.js; do node --check "$f"; done`
4. **실제 문헌으로 E2E** — 등록 → OCR → 검수 → PDF → 내려받기, 그리고
   **산출물을 열어서 본다.** 숫자만 보지 않는다.
5. `docs/DECISIONS.md`에 결정 카드(다음 번호)
6. `docs/releases/vX.Y.Z.md` — 되돌릴 수 없는 변화는 **맨 위에** 적는다
7. 버전 올리기: **`pyproject.toml` 한 곳뿐이다.** `server.py`와 화면 아래
   상태바는 설치된 패키지 메타데이터에서 읽는다(`/api/app/version`).
   **여기에 버전을 새로 적지 말 것** — 적는 곳이 둘 이상이면 반드시 어긋난다
8. `/doc-sync` (Release/Range Mode, base = 직전 태그)
9. 커밋 → 푸시 → `git tag -a vX.Y.Z` → `git push origin vX.Y.Z`

`release`·`feat`·`refactor` 커밋은 doc-sync 게이트가 걸린다.
`--no-verify`로 우회하지 않는다.

### 태그를 이미 낸 뒤에 옮겨야 할 때

**GitHub 릴리스는 태그에 매달려 있다.** 태그를 지우면 릴리스가 조용히
**초안(draft)** 으로 떨어지고, 목록에서는 그 전 판이 다시 «Latest»가 된다.
오류도 경고도 없다 — 사람이 릴리스 목록을 봐야 안다.

순서를 지킨다. **릴리스는 언제나 마지막이다.**

```bash
git tag -d vX.Y.Z                      # 로컬
git push origin :refs/tags/vX.Y.Z      # 원격
git tag -a vX.Y.Z -m "..."             # 새 커밋에 다시
git push origin vX.Y.Z
gh release edit vX.Y.Z --draft=false   # ← 초안으로 떨어진 것을 게시
```

확인은 SHA만 보지 말고 **목록의 «Latest» 표시**까지 본다.

```bash
gh release list --limit 3              # v X.Y.Z 가 Latest 인가
git rev-parse refs/tags/vX.Y.Z^{}      # HEAD와 같은가
```

---

## 6. 구조 규칙

- **라우터 간 직접 import 금지.** 공유 상태는 `_state.py`를 통해서만.
- 새 엔드포인트는 해당 도메인의 라우터 파일에(현재 8개, 183 라우트).
  **문서의 라우트 수는 손으로 적은 것이라 어긋난다.** 세는 명령:

  ```bash
  grep -c "^@router\.\(get\|post\|put\|patch\|delete\)(" src/app/routers/*.py
  ```

  실제로 `server.py` 머리말이 documents 34·interpretations 23·llm_ocr 14로
  오래 어긋나 있었다(실제 40·25·20). 문서와 코드가 다르면 **코드가 기준**이다.
- Pydantic 모델은 쓰는 라우터 파일 안에 정의.
- JSON 파일은 `jsonschema`로 검증(스키마 19개).
- 코드 주석은 한국어로, **왜 그렇게 했는지**를 담는다. 이 저장소의
  사용자는 비개발자 연구자이고, 주석이 유일한 설명이다.
- 용어: `LayoutBlock`(L3 영역) / `OcrResult`(L2 인식 결과) / `TextBlock`(해석용 단위).
  **「Block」이라고만 쓰지 않는다.**

---

## 7. 디렉터리 지도

```
src/
├── core/         # 핵심 로직 (표점, 번역, 주석 등)
├── hwp/          # HWP/HWPX 처리 (hwp-hwpx-parser)
├── text_import/  # 텍스트 가져오기 (HWP 표점분리 + PDF 참조텍스트)
├── llm/          # LLM 라우터 + 프로바이더
├── ocr/          # OCR 엔진 (NDL古典籍OCR Full/Lite + NDLOCR + LLM 비전 + PaddleOCR)
│              #  + line_detector: 인식 없이 줄 위치만 찾는다 (텍스트 레이어 배치용)
├── export/       # 연구 산출물 내보내기 (텍스트 레이어를 텍스트 레이어 PDF)
├── parsers/      # 서지정보 파서 (NDL, 국립공문서관, KORCIS, KOSTMA, 장서각, 규장각 + 범용 LLM)
├── cli/          # CLI 도구
└── app/          # 웹 앱 (FastAPI + static)
schemas/
├── source_repo/  # 원본 저장소 스키마 (7개)
├── interp/       # 해석 저장소 스키마 (5개)
└── core/         # 코어 엔티티 스키마 (6개)
```

---

## 관련 문서

| 문서 | 언제 보나 |
|---|---|
| [DECISIONS.md](DECISIONS.md) | 왜 이렇게 되어 있는지 — **고치기 전에 반드시** |
| [architecture-diagrams.md](architecture-diagrams.md) | 전체 그림이 필요할 때 |
| [../AGENTS.md](../AGENTS.md) | 인지 부채 지도 — 어디가 위험한지 |
| [../CLAUDE.md](../CLAUDE.md) | 작업 규칙 요약(이 문서의 축약본) |
| [core-schema-v1.3.md](core-schema-v1.3.md) · [operation-rules-v1.0.md](operation-rules-v1.0.md) | 스키마를 건드릴 때 |
