# 설계 결정 기록 (DECISIONS.md)

---

## D-001: "IDE"는 비유다 — 프로젝트의 정체성

**날짜**: 2026-02-14
**맥락**: 프로젝트 문서에서 "CJK Classical Text IDE"라고 명명했는데, 이것의 의미를 명확히 할 필요가 있다.

**결정**:

"IDE"는 비유적 표현이다. 개발자가 VSCode 하나에서 코드 편집, 파일 탐색, 터미널, Git, 디버깅, 확장 프로그램을 모두 하듯이, 고전 텍스트 연구자가 **이미지 열람부터 최종 DB 구축까지의 전체 프로세스를 한 곳에서 관리**할 수 있는 통합 작업 환경이 필요하다는 뜻이다.

| VSCode | 이 플랫폼 |
|---|---|
| 파일 탐색기 (Explorer) | 서고 브라우저 — 문서 목록, 권·페이지 탐색 |
| 에디터 (Editor) | 병렬 뷰어 — PDF 이미지 + 텍스트 나란히 |
| 멀티탭 | 층별 탭 — 원문, 교정, 현토, 번역, 주석 |
| 터미널 (Terminal) | Git 이력 패널 — 커밋, diff, 브랜치 |
| 소스 제어 (Source Control) | 의존 추적 — 원본↔해석 변경 감지 |
| 확장 프로그램 (Extensions) | 파서, OCR 엔진, LLM 연동 |
| 설정 (Settings) | 서고 설정, OCR 프로필, 프롬프트 관리 |
| 문제 패널 (Problems) | 검증 결과 — 스키마 오류, 의존 경고 |

**함의**:
- 이 프로젝트의 산출물은 "도구 모음"이 아니라 **하나의 통합 앱**이다
- CLI는 자동화/스크립팅용 보조이고, 주 인터페이스는 GUI다
- UI 설계 시 "연구자가 하루 종일 이 안에서 작업한다"를 전제로 해야 한다

---

## D-002: L3 레이아웃의 Block = OCR 읽기 순서 단위

**날짜**: 2026-02-14
**맥락**: "Block"이라는 단어가 L2/L3과 코어 스키마에서 모두 쓰이는데 혼동의 여지가 있었다. L3의 Block이 정확히 무엇인지 명확히 한다.

**결정**:

L3 레이아웃의 Block은 **OCR이 읽는 순서를 지정하기 위한 영역 단위**다.

고전 텍스트의 한 페이지에는 성격이 다른 영역이 섞여 있다:

```
┌─────────────────────────────────────┐
│  판심제 "蒙求卷上"                    │  ← reading_order: 0 (또는 skip)
├───────┬─────────────┬───────────────┤
│       │             │               │
│ 본문  │  주석       │  주석          │
│ (大字) │  (小字雙行)  │  (小字雙行)    │
│ 세로  │  세로       │  세로          │
│ RTL   │  RTL        │  RTL          │
│       │             │               │
│ [1]   │  [2]        │  [3]          │  ← reading_order
│       │             │               │
├───────┴─────────────┴───────────────┤
│  장차 "第三張"                        │  ← reading_order: 4 (또는 skip)
└─────────────────────────────────────┘
```

OCR 엔진은 이 영역들을 어떤 순서로 읽어야 하는지 모른다. 사람(또는 LLM)이 지정해야 한다.

**LayoutBlock 스키마**:

```json
{
  "block_id": "p01_b01",
  "block_type": "main_text",
  "bbox": [50, 30, 180, 600],
  "reading_order": 1,
  "writing_direction": "vertical_rtl",
  "ocr_config": {
    "engine": "paddleocr",
    "language": "classical_chinese",
    "line_style": "single_line",
    "font_size_class": "large"
  },
  "refers_to_block": null
}
```

**파이프라인에서의 위치**:

```
L1 이미지 (불변)
     │
     ▼
L3 레이아웃 분석 ← 사람 또는 LLM이 이미지 위에 영역을 그린다
  │  "이 사각형은 본문, reading_order 1"
  │  "이 사각형은 주석, reading_order 2"
  │
  ▼
L2 OCR ← 각 블록을 reading_order 순서대로, 블록별 설정으로 OCR 실행
  │
  ▼
L4 사람 교정 ← 블록별로 교정 (본문 따로, 주석 따로)
```

**⚠️ 순서**: v7 기획서에서는 L2(OCR) → L3(레이아웃)이었지만, 실제 작업 흐름은 L3 → L2가 더 자연스럽다. 두 경로 모두 지원:

- **경로 A**: L3 먼저 → L2 블록별 OCR (정밀)
- **경로 B**: L2 전체 OCR 먼저 → L3으로 블록 분류 (빠름, 덜 정밀)

---

## D-003: Block이라는 용어의 세 가지 쓰임 정리

**날짜**: 2026-02-14

| 이름 | 위치 | 정체 | 예시 |
|---|---|---|---|
| **LayoutBlock** | 원본 저장소 L3 | 페이지 이미지 위의 사각형 영역. OCR 읽기 순서 단위. | `p01_b01`, bbox, reading_order |
| **OcrResult** | 원본 저장소 L2 | LayoutBlock 안에서 OCR이 인식한 글자들. | characters: [{char, bbox, conf}] |
| **TextBlock** | 코어 스키마 | 해석 작업의 최소 텍스트 단위 (문장/절/구). | `original_text: "王戎簡要"` |

**관계**:

```
LayoutBlock (L3) → OcrResult (L2) → L4 교정 → TextBlock (코어 스키마)
                                                  └─ source_ref로 원본 추적
```

**명명 규칙** (코드에서):
- `LayoutBlock` — L3의 영역
- `OcrResult` — L2의 인식 결과 (Block이라는 이름 사용하지 않음)
- `TextBlock` — 코어 스키마의 Block

---

## D-004: 층 번호와 실제 작업 순서는 다를 수 있다

**날짜**: 2026-02-14

층 번호(1, 2, 3, 4...)는 **데이터의 추상화 수준**을 나타내지, 반드시 작업 순서를 의미하지 않는다:

- **경로 A**: L3(영역 지정) → L2(블록별 OCR) → L4(교정) — 정밀
- **경로 B**: L2(전체 OCR) → L3(블록 분류) → L4(교정) — 빠름
- **경로 C**: L4(수동 입력) → L3(나중에) — OCR 없이 직접 타이핑

모두 유효한 워크플로우. 앱은 세 경로를 모두 지원해야 한다.

---

## D-005: Block 간 원천 추적 (source_ref)

**날짜**: 2026-02-14

코어 스키마의 TextBlock은 원본 저장소의 L4 확정 텍스트에서 생성되며, `source_ref`로 자기가 어디서 왔는지를 항상 추적한다:

```json
{
  "id": "<uuid>",
  "work_id": "<uuid>",
  "sequence_index": 1,
  "original_text": "王戎簡要裴楷清通",
  "source_ref": {
    "document_id": "monggu",
    "page": 1,
    "layout_block_id": "p01_b01",
    "layer": "L4",
    "commit": "a1b2c3d"
  }
}
```

---

## D-006: 프로젝트 이름 (미정)

**날짜**: 2026-02-14
**상태**: 미결

v7 섹션 13에 "프로젝트 이름"이 미결 사항으로 남아 있다.
확정: classical-text-browser (고전서지 통합 브라우저)

---

## D-007: 저장소·백업·공유 전략

**날짜**: 2026-02-14
**맥락**: Git을 모르는 연구자에게 Google Drive만 쓰게 하면 되지 않느냐는 질문이 나왔다.

**분석**:

이 플랫폼에서 Git 명령어를 연구자가 직접 치지는 않는다. 앱이 GitPython을 통해 처리한다:
- "저장" 버튼 → 앱이 git commit
- "이전 버전" 버튼 → 앱이 git log + diff
- "변경됨 ⚠️" 경고 → 앱이 git diff --name-only

단, 연구자가 해야 하는 **설정·연동 절차**는 있다 (모두 앱 UI를 통해):
- 초기: "서고 만들기" → 로컬 폴더 선택 → 앱이 git init
- 원격: "원격 연결" → GitHub/GitLab URL 입력 → 앱이 git remote add
- 일상: "동기화" 버튼 → 앱이 git push/pull
- 협업: "서고 가져오기" → URL 입력 → 앱이 git clone

즉 **Git의 개념(저장·이력·동기화)은 이해해야 하지만, 명령어는 몰라도 된다**.

"파일을 어디에 두느냐"와 "이력을 어떻게 관리하느냐"는 별개의 문제:

| 역할 | 수단 | 대체 불가 여부 |
|---|---|---|
| 버전 이력·diff·의존 추적 | Git (내부) | **대체 불가** — 핵심 기능이 의존 |
| 원격 백업·협업 | GitHub / GitLab / Gitea | 교체 가능 |
| 파일 백업·비개발자 공유 | Google Drive | 보조 수단 |
| 실제 작업 | 로컬 폴더 | 필수 (오프라인 퍼스트) |

**결정**:

개발자(혜원) 기본 설정은 세 가지를 모두 사용:

```
[로컬 폴더] ←→ [Git 내부 관리] ←→ [GitHub 원격]
     │
     └── Google Drive 동기화 (백업 + 비개발자 공유)
```

- **로컬**: 실제 작업 공간. 오프라인에서도 완전 동작.
- **Git (내부)**: 앱이 자동으로 관리. 연구자에게 노출 안 됨.
- **GitHub**: git push/pull로 원격 백업 및 협업.
- **Google Drive**: 프로젝트 폴더를 동기화 폴더에 배치. 비개발자 공유용.

**⚠️ Google Drive + .git 충돌 문제**:
Google Drive 동기화 폴더 안에 `.git` 폴더가 있으면 동기화 충돌이 날 수 있다.
배포 시 설치 가이드에서 이 부분을 안내해야 한다 (예: .git을 동기화 제외 설정).

**미결: 비개발자 배포 시나리오**
Git을 모르는 연구자에게는:
- 앱 설치 시 Git을 자동 포함 (내부 번들)
- 또는 Git 없이도 기본 기능(뷰어·편집·저장)은 동작하되, 이력·의존 추적은 비활성
→ Phase 10 이후 배포 단계에서 결정.

---

## D-009: OCR 엔진 플러그인 아키텍처

**날짜**: 2026-02-15
**상태**: 확정

**결정**:

모든 OCR 엔진은 `BaseOcrEngine`을 상속하고, `OcrEngineRegistry`로 등록/조회하며,
`OcrPipeline`을 통해서만 실행한다 (엔진 직접 호출 금지).

| 구성 요소 | 역할 |
|-----------|------|
| `BaseOcrEngine` | 추상 클래스 — `recognize(image_bytes)` 인터페이스 |
| `OcrEngineRegistry` | 엔진 등록/조회/기본 엔진 관리 |
| `OcrPipeline` | L3 bbox → 이미지 크롭 → OCR → L2 JSON 저장 |
| `PaddleOcrEngine` | 기본 엔진 — 오프라인 퍼스트, 한문 세로쓰기 지원 |

**파이프라인 흐름**:
```
L3 LayoutBlock (bbox) → image_utils.crop_block() → OCR 엔진 → OcrBlockResult → L2 JSON
```

**스키마**:
- 입력: `layout_page.schema.json` (L3)
- 출력: `ocr_page.schema.json` (L2)
- `additionalProperties: false` — 스키마에 없는 필드는 저장 금지

**근거**: 파서(BaseFetcher/BaseMapper)와 동일한 플러그인 패턴으로 일관성 유지.
오프라인 퍼스트 원칙 (PaddleOCR는 네트워크 불필요).

---

## D-010: LLM 4단 폴백 아키텍처

**날짜**: 2026-02-15
**맥락**: LLM 호출을 어떤 구조로 관리할 것인가. 프로젝트 초기라 API 키가 없을 수도, 로컬 모델만 쓸 수도, 유료 API를 쓸 수도 있다.

**결정**:

4단 폴백 + 단일 진입점(Router) 아키텍처를 채택한다.

| 순위 | Provider | 특징 |
|------|----------|------|
| 1순위 | Base44 HTTP (agent-chat) | 무료, 로컬 실행 필요 |
| 2순위 | Base44 Bridge (Node.js) | 무료, Node.js subprocess |
| 3순위 | Ollama (로컬 프록시) | 무료, 모델 선택 자유 |
| 4순위 | Anthropic (Claude API) | 유료, 최고 품질 |

**핵심 원칙**:
- **LlmRouter가 유일한 진입점**: 모든 코드는 provider를 직접 호출하지 않고, Router를 통해야 한다
- **Draft → Review → Commit**: LLM 결과는 항상 Draft 상태로 생성. 사람이 검토(accept/modify/reject) 후 확정
- **비교 모드**: 같은 입력을 여러 모델에 보내서 결과를 나란히 비교 가능
- **사용량 추적**: 서고별 llm_usage_log.jsonl에 모든 호출 기록 (무료 포함)
- **force_provider/force_model**: 품질 테스트용 폴백 우회 옵션

**파일 구조**:
```
src/llm/
├── __init__.py          # 공개 API
├── config.py            # 설정 관리 (.env → 환경변수 → 기본값)
├── router.py            # 단일 진입점 (폴백 + 비교)
├── draft.py             # Draft → Review → Commit
├── usage_tracker.py     # JSONL 사용량 추적
├── providers/
│   ├── base.py          # 추상 클래스 + LlmResponse
│   ├── base44_http.py   # 1순위
│   ├── base44_bridge.py # 2순위
│   ├── ollama.py        # 3순위
│   └── anthropic_provider.py  # 4순위
├── bridge/
│   ├── invoke.js        # Node.js 텍스트 브릿지
│   └── invoke_vision.js # Node.js 비전 브릿지
└── prompts/
    └── layout_analysis.yaml  # 레이아웃 분석 프롬프트
```

---

## D-012: 정렬 엔진 — difflib + 이체자 보정

**날짜**: 2026-02-15
**상태**: 확정

**맥락**: OCR 결과(L2)와 확정 텍스트(L4)를 글자 단위로 대조하는 정렬 엔진이 필요하다.
고전 한문에서는 같은 글자의 다른 자형(이체자, 同字異形)이 흔해서 단순 문자열 비교로는 불충분하다.

**결정**:

`difflib.SequenceMatcher`를 기반으로 한 글자 단위 정렬 + 이체자 사전 보정 방식을 채택한다.

| 구성 요소 | 역할 |
|-----------|------|
| `align_texts()` | 두 텍스트를 글자 단위로 정렬, SequenceMatcher 사용 |
| `VariantCharDict` | 이체자 사전 — 양방향 조회, JSON 파일 기반 |
| `align_page()` | L2 + L4 파일을 읽어 블록별 + 페이지 전체 대조 |
| `_find_best_match_in_ref()` | L4 평문에서 L2 블록에 대응하는 구간을 슬라이딩 윈도우로 탐색 |

**매치 타입** (5종):

| 타입 | 의미 | 예시 |
|------|------|------|
| `exact` | 완전 일치 | 王 ↔ 王 |
| `variant` | 이체자 일치 (사전 등록 필요) | 裴 ↔ 裵 |
| `mismatch` | 불일치 (OCR 오류 또는 원문 차이) | 寬 ↔ 寒 |
| `insertion` | L4에만 존재 (OCR 누락) | — ↔ 清 |
| `deletion` | L2에만 존재 (OCR 오삽입) | 餘 ↔ — |

**L4 블록 매칭 전략**:
L4는 평문 텍스트(.txt)로 블록 경계가 없다. 블록별 대조를 위해:
1. L2 블록 텍스트 길이와 동일한 윈도우로 L4 전체를 슬라이딩 탐색
2. SequenceMatcher.ratio()가 최대인 구간을 해당 블록의 대응 구간으로 결정
3. 2글자 마진 확장을 시도하여 정확도가 올라가면 채택

**근거**:
- difflib은 Python 표준 라이브러리로 의존성 없음
- 이체자 사전은 사용자가 직접 관리 (연구자 도메인 지식 반영)
- GUI에서 불일치 글자 클릭 → 이체자 등록이 가능하여 사전이 점진적으로 풍부해짐

---

## D-013: KORCIS 파서 고도화 — 008 해석 + 판식정보 + OpenAPI 보강

**날짜**: 2026-02-15
**맥락**: Phase 10-4. 기존 KORCIS 파서(HTML 스크래핑 + MARC 팝업)로는 판식정보(printing_info), 간행사항(publishing), 권책수(extent) 등 고서 핵심 서지정보를 채울 수 없었다.

**결정**:

1. **KORMARC 008 고정길이 필드 해석기 추가** — 위치 06(날짜유형), 07-10(연도1), 11-14(연도2), 35-37(언어코드), 38(수정기호)를 코드 테이블로 해석.
2. **판식정보 구조화 추출기 추가** — 정규표현식으로 광곽/행자수/어미/계선/판구/판심제 등을 `printing_info` 스키마 필드로 매핑. 원문은 `summary`에 보존.
3. **KORCIS OpenAPI 보강 경로** — 기존 HTML 스크래핑을 유지하면서, OpenAPI(`nl.go.kr/korcis/openapi/`)를 보조 소스로 추가. FORM_INFO(판식정보), HOLDINFO(소장처)는 OpenAPI에서만 제공.
4. **매퍼 통합** — MARC 260(간행사항→`publishing`), MARC 300(형태사항→`extent`), OpenAPI FORM_INFO(→`printing_info`)를 `map_to_bibliography()`에 반영.
5. **GUI 라이트그레이 테마** — CSS 변수 기반 다크/라이트 테마 전환. `[data-theme="light"]`로 변수 오버라이드, localStorage에 저장, 액티비티 바 하단에 토글 버튼.

**근거**:
- 기존 HTML 스크래핑 경로를 제거하지 않고 보강하여 하위 호환성 유지
- OpenAPI는 API 키 없이도 동작(KORCIS 공식 가이드)
- CSS 변수 기반 테마 전환은 빌드 도구 없는 프로젝트에 적합

---

## 미결 사항 (v7 섹션 13 기반)

## D-014: L5 끊어읽기(표점)·현토 편집기 아키텍처

**날짜**: 2026-02-15
**맥락**: 고전 한문에 구두점(句讀)과 한글 현토(懸吐)를 붙이는 L5 계층 편집기가 필요하다.

**결정**:

1. **before/after 모델**: 표점·현토 모두 `target: {start, end}` + before/after 문자열 삽입 방식.
   원문은 절대 변형하지 않고, 삽입 위치만 기록.
2. **감싸기 부호**: 서명호(《》) 등은 before + after를 동시 지정. 범위 선택이 필요.
3. **표점/현토 분리 저장**: 같은 L5_reading/main_text 디렉토리에 `_punctuation.json`과 `_hyeonto.json` 접미사로 구분.
4. **프리셋 팔레트**: 10종 기본 부호를 `resources/punctuation_presets.json`에 정의. API로 제공.
5. **미리보기 알고리즘**: 글자별 before/after 버퍼를 만들어 `before[i] + char[i] + after[i]` 연결.
   클라이언트/서버 양쪽에서 동일 알고리즘 사용.
6. **LLM Draft**: 표점만 LLM 자동 생성 지원 (현토는 향후). Draft→Review→Commit 패턴 재사용.

**대안**:
- 오프셋 기반 삽입 대신 텍스트 변환 방식 → 원문 변형 발생하므로 불가.
- 표점/현토 통합 파일 → CRUD가 복잡해지므로 분리 채택.

---

## D-015: L6 번역 데이터 모델 + LLM 번역 워크플로우

**날짜**: 2026-02-16
**맥락**: L5 표점으로 분리된 문장 단위의 번역을 관리하는 L6 계층이 필요하다.

**결정**:

1. **문장 단위 번역**: L5 `split_sentences()`로 분리된 문장이 기본 번역 단위.
   표점이 없으면 블록 전체를 하나의 문장으로 취급.
2. **SourceRef 추적**: 각 번역은 `source: {block_id, start, end}`로 원문 위치를 정확히 참조.
   `source_text`에 원문 스냅샷을 보관하여 L4 변경 시 비교 가능.
3. **현토 스냅샷**: `hyeonto_text`에 현토 적용 텍스트를 선택적으로 보존.
   번역 프롬프트에 현토를 포함하면 품질 향상.
4. **상태 생명주기**: `draft → reviewed → accepted`. LLM 결과는 항상 draft로 시작.
5. **Translator 정보**: `type: "llm" | "human"`, `model`, `draft_id`로 번역자 추적.
6. **파일 경로**: `L6_translation/main_text/{part_id}_page_{NNN}_translation.json`
   기존 `.txt` 파일과 `_translation` 접미사로 구분.
7. **Draft→Review→Commit 재사용**: Phase 10-2의 LlmDraft 패턴을 번역에도 적용.

**스키마**: `schemas/interp/translation_page.schema.json`

**대안**:
- 블록 단위 번역 → 문장이 너무 길어 번역 품질 저하. 문장 단위 채택.
- 번역을 L5에 통합 → 표점/현토와 번역은 독립적 작업이므로 분리 채택.

---

## D-016: L7 주석 데이터 모델 + 주석 유형 관리

**날짜**: 2026-02-16
**맥락**: 원문의 인물·지명·용어·전거(고사/출전)에 주석을 다는 L7 계층이 필요하다.

**결정**:

1. **블록 단위 주석 관리**: annotation_page.json은 blocks 배열로 블록별 주석을 묶는다.
   각 블록 안에서 target(start/end)으로 원문 범위를 지정.
2. **유형은 사용자 정의 가능**: 고정 enum이 아니라 annotation_types.json으로 관리.
   기본 프리셋 5종(person, place, term, allusion, note) + custom 확장.
3. **서고별 커스텀 유형**: 기본 프리셋은 resources/에, 사용자 정의는 서고 안에 저장.
   서고를 공유하면 유형도 함께 이동.
4. **상태 생명주기**: L6과 동일한 draft → reviewed → accepted 패턴.
5. **LLM 자동 태깅**: 원문 전체를 LLM에 보내 한번에 태깅. JSON 응답 파싱.
6. **파일 경로**: `L7_annotation/main_text/{part_id}_page_{NNN}_annotation.json`

**스키마**: `schemas/interp/annotation_page.schema.json`

**대안**:
- 주석을 L6에 통합 → 번역과 주석은 독립적 작업이므로 분리 채택.
- 유형을 schema enum으로 고정 → 연구 분야마다 필요한 유형이 다르므로 유연한 관리 채택.

---

## D-017: Git 그래프 — 사다리형 이분 그래프 + Based-On-Original trailer

**날짜**: 2026-02-16
**맥락**: 원본 저장소(L1~L4)와 해석 저장소(L5~L7)의 커밋 이력을
나란히 보여주면, 해석 작업이 어떤 원본 시점을 기반했는지 직관적으로 파악할 수 있다.

**결정**:

1. **Based-On-Original trailer**: 해석 커밋 시 원본 저장소 HEAD hash를 Git trailer로 자동 기록.
2. **이분 그래프 렌더링**: d3.js SVG로 좌측 원본 레인, 우측 해석 레인 + 가로 연결선.
3. **커밋 매칭 이중 전략**: trailer 있으면 explicit, 없으면 타임스탬프 기반 estimated.
4. **간략/상세 뷰 전환**: 기존 커밋 목록(간략) ↔ 사다리형 그래프(상세) 탭 전환.
5. **API**: `GET /api/interpretations/{interp_id}/git-graph` — 해석 저장소 manifest에서 원본 자동 결정.

**스키마**: 응답은 `{original, interpretation, links, pagination}` 구조.

**대안**:
- 단일 타임라인에 모두 합침 → 두 저장소의 독립성이 사라져 거부.
- trailer 없이 타임스탬프만 사용 → 정확도 낮아 명시적 trailer 병행 채택.

---

## D-018: JSON 스냅샷 Export/Import — 교환 형식 설계

**날짜**: 2026-02-18
**맥락**: Work(원본 L1~L4 + 해석 L5~L7 + 메타데이터)를 단일 JSON으로
직렬화하여 백업, 복원, 다른 환경 이동을 지원해야 한다.

**결정**:

1. **schema_version**: 모든 스냅샷에 `"schema_version": "1.0"` 포함. 향후 마이그레이션 지원.
2. **L1 이미지 참조만**: 바이너리 미포함, 경로·파일명·크기만 기록. JSON 경량화.
3. **_source_path 메타데이터**: L5~L7 각 JSON에 원본 상대 경로를 기록하여 Import 시 정확한 위치에 복원.
4. **항상 새 Work 생성**: Import 시 타임스탬프 접미사로 새 ID 발급. 기존 데이터 덮어쓰기 방지.
5. **2단계 검증**: errors(import 차단)와 warnings(경고만) 분리. block_id 참조 무결성은 warning.
6. **Export API**: `GET /api/interpretations/{interp_id}/export/json` — Content-Disposition 다운로드.
7. **Import API**: `POST /api/import/json` — Request body에 JSON 직접 전송.

**대안**:
- ZIP 아카이브 (이미지 포함) → 파일 크기 과대, JSON 단순성 상실로 거부.
- Git bundle → 히스토리 불필요한 경우가 더 많아 HEAD 스냅샷만 채택.

---

## D-019: 사전형 주석 (Dictionary Annotation) 아키텍처

**날짜**: 2026-02-20
**맥락**: L7 주석이 단순 태깅(인물/지명/용어 식별 + label/description)만 지원하여,
연구자가 원하는 사전 형식의 체계적 주석이 불가능했다. 표제어, 사전적 의미, 문맥적 의미,
출전을 기록하고, LLM이 4단계에 걸쳐 누적적으로 생성하며, 다른 문헌에서도 참조할 수 있는
독립 사전으로 내보낼 수 있는 시스템이 필요했다.

**결정**:

1. **기존 태깅을 사전으로 확장**: 별도 엔티티가 아니라 기존 Annotation 객체에 `dictionary` 필드 추가.
   기존 UI 유지하면서 사전 필드를 점진적으로 채움. 스키마 v2 (`annotation_page.schema.json`).
2. **v1→v2 lazy migration**: 기존 파일 수정 없이 로드 시점에 기본값 채움. 저장 시에만 v2 형식.
3. **4단계 누적 생성**: (1) 원문→사전항목, (2) 번역→보강, (3) 원문+번역 통합, (4) 사람 검토.
   각 단계가 이전 결과를 enrichment. `generation_history`에 스냅샷 보존.
4. **Stage 3 직행 (일괄 생성)**: 완성된 원문+번역 쌍에서 1→2 건너뛰고 바로 3단계 실행.
   용도: 이미 완성된 작업에서 사전 추출 → 다른 문헌 번역 시 참조.
5. **해석별 독립 사전 + 명시적 내보내기/가져오기**: 각 해석이 자체 사전을 가지며,
   필요 시 JSON으로 내보내기하여 다른 해석에서 가져오기. headword 기반 병합.
6. **참조 사전 자동 매칭 + 사용자 확인**: 가져온 사전의 headword를 원문에서 부분 문자열 검색.
   매칭 결과를 사용자가 체크박스로 선택 → 번역 프롬프트에 참고 사전으로 포함.
7. **번역↔주석 양방향 연동**: 번역 변경 시 `translation_snapshot` 비교로 감지,
   주석 수정 후 "주석 참조 재번역" 수동 트리거. 양방향 모두 사용자가 명시적으로 실행.
   `translation_page.schema.json`에 `annotation_context` 필드 추가 — 번역 시 참조한 주석 ID와 참조 사전 파일명을 기록.
8. **사람이 편집한 항목 보호**: `status == "accepted"` 주석은 LLM이 덮어쓰지 않음.
   LLM 제안은 `generation_history`에만 기록.

**스키마 변경**:
- `annotation_page.schema.json` v1→v2: `dictionary`(DictionaryEntry), `current_stage`, `generation_history`(GenerationStage[]), `source_text_snapshot`, `translation_snapshot` 추가
- `translation_page.schema.json`: `annotation_context`(AnnotationContext) 추가 — `used_annotation_ids`, `reference_dict_filenames`

**새 파일**:
- `src/core/annotation_dict_llm.py` — 4단계 사전 생성 파이프라인
- `src/core/annotation_dict_io.py` — 사전 내보내기/가져오기
- `src/core/annotation_dict_match.py` — 참조 사전 매칭 엔진
- `src/llm/prompts/annotation_dict_stage{1,2,3}.yaml` — 단계별 프롬프트

**대안**:
- 사전을 별도 엔티티로 분리 → 기존 태깅 UI와 이중 관리 부담으로 거부.
- LLM 1회 호출로 사전 생성 → 원문만/번역만 있는 단계에서 활용 불가로 거부.
- 참조 사전 자동 적용 → 연구자 통제권 약화로 거부. 수동 확인 채택.

---

## D-020: 인용 마크 시스템 (Citation Mark) 아키텍처

**날짜**: 2026-02-20
**맥락**: 연구자가 원문(L4)이나 번역(L6)을 읽으면서 나중에 논문에 인용할 구절을
마크업하고, 마크된 구절에 대해 원문+표점본+번역+주석을 한눈에 보며,
학술 인용 형식으로 내보내는 기능이 필요했다.

**인용 형식**: `著者名, 書名卷數, 작품제목, 관련페이지(부가정보) : 표점된 원문`
예시: `朴趾源, 燕岩集卷2, 答巡使書 25면(韓國文集叢刊252집, 48면) : 若吾所樂者善，而所敬者天也。`

**결정**:

1. **인용 마크는 해석 레이어가 아닌 연구 도구**: L5~L8 해석 데이터와 구분하여
   `{interp_id}/citation_marks/` 별도 디렉토리에 저장.
2. **교차 레이어 해석(resolve)**: 단일 인용 마크에서 L4 원문, L5 표점본, L6 번역,
   L7 주석을 자동으로 통합 조회. SourceRange(block_id, start, end)를 공유 좌표로 사용.
3. **citation_override**: 서지정보(bibliography.json)에서 자동 추출 불가능한
   작품제목·페이지·부가정보를 연구자가 수동 입력하는 필드.
   서지정보 자동값보다 override가 우선.
4. **텍스트 선택 개선**: annotation-editor.js의 `text.indexOf()` 문제를 수정하여
   Selection Range API로 정확한 char offset을 계산. 동일 텍스트 반복 시에도 올바른 위치 추출.
5. **상태 관리**: active(마크 직후) → used(논문에 사용) → archived(폐기).
   라벨과 태그로 마크를 분류.
6. **내보내기**: 선택한 마크들을 학술 인용 형식으로 일괄 변환, 클립보드 복사.
   번역 포함 여부 선택 가능.

**새 파일**:
- `schemas/interp/citation_mark_page.schema.json` — 인용 마크 스키마
- `src/core/citation_mark.py` — CRUD + resolve + format
- `src/app/static/js/citation-editor.js` — 프론트엔드 에디터
- `tests/test_citation_mark.py` — 백엔드 테스트 (15개)

**수정 파일**: `server.py` (7 엔드포인트), `index.html`, `workspace.js`, `workspace.css`

**대안**:
- 인용을 L8(외부참조) 레이어에 저장 → 연구 도구와 해석 데이터의 성격이 다르므로 거부.
- 별도 DB(SQLite)에 저장 → 기존 JSON+Git 아키텍처와 불일치로 거부.

---

## D-021: 범용 에셋 감지 + 다운로드 (Generic Asset Detection)

**날짜**: 2026-02-20
**맥락**: 기존에는 일본 국립공문서관(`archives_jp`)만 PDF 자동 다운로드를 지원했다.
다른 기관 URL에서도 PDF나 이미지 파일을 자동으로 감지하여 다운로드할 수 있어야 한다.

**결정**:

1. **범용 에셋 감지기 신설**: `src/parsers/asset_detector.py` — 파서와 독립된 유틸리티.
   URL에 HEAD 요청을 보내 Content-Type으로 직접 다운로드 가능 여부를 판별하고,
   마크다운에서 PDF/이미지 링크를 정규표현식으로 추출.
2. **이미지 번들→PDF 변환**: 같은 디렉토리의 이미지 2개 이상은 "이미지 번들"로 그룹핑.
   fpdf2 + PIL로 합쳐서 단일 PDF로 변환 (archives_jp 패턴 재사용, 150dpi 가정).
3. **장식 이미지 필터링**: logo, icon, favicon, banner 등 장식 이미지는
   `_DECORATIVE_PATTERNS` 정규표현식으로 자동 제외.
4. **generic_llm 파서 확장**: `supports_asset_download = True` 플래그 추가.
   `list_assets()`와 `download_asset()`을 asset_detector에 위임.
5. **서버 폴백**: `preview-from-url` 엔드포인트에서 파서가 에셋 감지를 지원하지 않더라도
   URL 자체가 PDF/이미지인지 직접 확인하는 폴백 경로 추가.

**에셋 유형**: `pdf`, `image`, `image_bundle`

**새 파일**:
- `src/parsers/asset_detector.py` — 에셋 감지 + 다운로드 유틸리티
- `tests/test_asset_detector.py` — 32개 테스트

**수정 파일**: `src/parsers/generic_llm.py`, `src/app/server.py`, `src/core/document.py`

**대안**:
- 각 파서에 에셋 감지 로직 개별 구현 → 중복 코드, 일관성 결여로 거부.
- 서버 측에서 모든 에셋 감지 → 파서별 특화 로직과 혼재로 거부. 유틸리티 분리 채택.

---

## D-022: GUI에서 서고(Library) 관리

**날짜**: 2026-02-20
**맥락**: 서고 경로(`--library`)는 CLI 인자로만 지정 가능하고, 서버 시작 후 변경할 수 없었다.
GUI에서 서고를 전환·생성·최근 목록 조회할 수 있어야 한다.

**결정**:

1. **앱 설정 파일**: `~/.classical-text-browser/config.json`에 최근 서고 목록 저장.
   서고 경로와 무관한 앱 수준 설정이므로 서고 외부(홈 디렉토리)에 배치.
2. **런타임 서고 전환**: `configure()` 함수를 재호출하여 서고를 동적으로 변경.
   LLM 라우터 캐시를 초기화하여 서고별 `.env` 설정 차이를 반영.
3. **`--library` 선택 인자화**: 미지정 시 마지막 사용 서고를 자동 선택.
   마지막 서고도 없으면 서고 없이 서버 시작 → GUI에서 선택/생성 유도.
4. **프론트엔드 전체 리로드**: 서고 전환 시 `location.reload()`로 상태 초기화.
   부분 갱신보다 안전하고 단순.

**새 API 엔드포인트**:
- `POST /api/library/switch` — 서고 전환 (경로 검증 → configure() → 응답)
- `POST /api/library/init` — 새 서고 생성 (init_library() → configure())
- `GET  /api/library/recent` — 최근 서고 목록 (최대 10개, 최신 순)

**새 파일**:
- `src/core/app_config.py` — 앱 전역 설정 관리

**수정 파일**: `src/app/server.py`, `src/app/__main__.py`,
`src/app/static/index.html`, `src/app/static/js/workspace.js`,
`src/app/static/css/workspace.css`

**대안**:
- 서고 설정을 서고 내부에 저장 → 서고 경로 자체를 기억해야 하므로 불가.
- 서고 전환 시 서버 재시작 → 사용자 경험 저하로 거부. 런타임 전환 채택.

---

## D-023: 휴지통 시스템 (Trash/Restore)

**날짜**: 2026-02-20
**맥락**: 문헌이나 해석 저장소를 삭제할 때 영구 삭제는 위험하다.
복원 가능한 소프트 삭제가 필요하다.

**결정**:

1. **서고 내부 `.trash/` 폴더**: `library/.trash/documents/`와 `.trash/interpretations/`에
   삭제된 항목을 타임스탬프 접두사(`{YYYYMMDD}T{HHMMSS}_{원래ID}`)로 이동.
2. **OS 독립적**: OS 휴지통(Recycle Bin)은 플랫폼마다 API가 달라 사용하지 않음.
   `shutil.move`로 서고 내 이동만 수행.
3. **연관 해석 저장소 경고**: 문헌 삭제 시 해당 문헌을 `source_document_id`로 참조하는
   해석 저장소 목록을 반환하여 프론트엔드에서 경고 표시.
4. **복원**: 타임스탬프 접두사를 제거하고 원래 위치로 `shutil.move`.
   같은 ID가 이미 존재하면 `FileExistsError`.

**API 엔드포인트**:
- `DELETE /api/documents/{doc_id}` — 문헌을 휴지통으로 이동
- `DELETE /api/interpretations/{interp_id}` — 해석 저장소를 휴지통으로 이동
- `GET    /api/trash` — 휴지통 목록
- `POST   /api/trash/{trash_type}/{trash_name}/restore` — 복원

**수정 파일**: `src/core/library.py` (trash_document, trash_interpretation,
list_trash, restore_from_trash 함수 추가), `src/app/server.py`

**대안**:
- 영구 삭제 + 확인 대화상자 → 사용자 실수 시 복구 불가로 거부.
- Git에서 복구 → 대용량 파일(PDF)은 git-lfs라 복잡, 비개발자에게 부적합.

---

### 원본 저장소
- [ ] JSON 스키마 각 필드의 상세 정의 → Phase 1에서 해결
- [ ] 서지정보 파싱 상세 → Phase 5에서 해결
- [ ] git-lfs 설정 상세 → Phase 2에서 해결
- [ ] block_type 어휘 확장 → 점진적

### OCR
- [x] OCR 엔진 플러그인 아키텍처 → D-009 (Phase 10-1)
- [x] PaddleOCR 기본 엔진 설치 확정 — paddlepaddle 3.3.0 + paddleocr 2.10.0
- [ ] OCR 엔진 비교 평가 → Phase 10 이후

### LLM 협업
- [x] LLM 호출 아키텍처 → D-010 (Phase 10-2)
- [x] 프롬프트 설계 원칙 → layout_analysis.yaml (Phase 10-2)
- [x] 비용 관리 → UsageTracker + 월별 예산 (Phase 10-2)

### 저장소 연결
- [x] 사다리형 git 그래프 구현 → D-017 (Phase 12-1)
- [ ] git 호스팅 선정

### 해석 저장소
- [x] 5~8층 데이터 모델 상세 → D-014(L5), D-015(L6), D-016(L7)
- [x] 본문/주석 번역의 연결 구조 → D-015 (SourceRef)
- [x] 사전형 주석 (Dictionary Annotation) → D-019
- [x] 인용 마크 시스템 (Citation Mark) → D-020
- [ ] 협업 모델

### 서고 관리
- [x] 범용 에셋 감지 + 다운로드 → D-021
- [x] GUI에서 서고 관리 (전환/생성/최근 목록) → D-022
- [x] 휴지통 시스템 (Trash/Restore) → D-023

### 배포·설치
- [ ] Google Drive + .git 충돌 회피 가이드 → Phase 10 이후
- [ ] 비개발자용 Git 번들링 또는 Git-free 모드 → Phase 10 이후

### 전체
- [ ] 라이선스/공개 범위
- [ ] 프로젝트 이름
