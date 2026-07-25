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

## D-010: LLM 5단 폴백 아키텍처

**날짜**: 2026-02-15 (최종 갱신: 2026-05-08)
**맥락**: LLM 호출을 어떤 구조로 관리할 것인가. 프로젝트 초기라 API 키가 없을 수도, 로컬 모델만 쓸 수도, 유료 API를 쓸 수도 있다.

**결정**:

5단 폴백 + 단일 진입점(Router) 아키텍처를 채택한다.

| 순위 | Provider | 특징 |
|------|----------|------|
| 1순위 | Ollama (로컬 gemma4:e4b) | 무료, 멀티모달 |
| 2순위 | OpenAI OAuth | ChatGPT 계정 프록시, API 키 없이 무료 |
| 3순위 | Gemini (Google AI) | 저렴, 비전 포함 |
| 4순위 | OpenAI | 중간 비용, 비전 포함 |
| 5순위 | Anthropic (Claude API) | 최후 폴백 |

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
│   ├── base.py              # 추상 클래스 + LlmResponse
│   ├── ollama.py            # 1순위 (gemma4:e4b)
│   ├── openai_oauth_provider.py # 2순위
│   ├── gemini_provider.py   # 3순위
│   ├── openai_provider.py   # 4순위
│   └── anthropic_provider.py # 5순위
└── prompts/
    ├── layout_analysis.yaml       # L3 레이아웃 분석
    ├── punctuation.yaml           # L5 표점
    ├── translation.yaml           # L6 번역
    ├── annotation.yaml            # L7 주석
    ├── annotation_dict_stage1.yaml # L7 사전형 주석 1단계
    ├── annotation_dict_stage2.yaml # L7 사전형 주석 2단계
    └── annotation_dict_stage3.yaml # L7 사전형 주석 3단계
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
**맥락**: 원본 저장소(L1-L4)와 해석 저장소(L5-L7)의 커밋 이력을
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
**맥락**: Work(원본 L1-L4 + 해석 L5-L7 + 메타데이터)를 단일 JSON으로
직렬화하여 백업, 복원, 다른 환경 이동을 지원해야 한다.

**결정**:

1. **schema_version**: 모든 스냅샷에 `"schema_version": "1.0"` 포함. 향후 마이그레이션 지원.
2. **L1 이미지 참조만**: 바이너리 미포함, 경로·파일명·크기만 기록. JSON 경량화.
3. **_source_path 메타데이터**: L5-L7 각 JSON에 원본 상대 경로를 기록하여 Import 시 정확한 위치에 복원.
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

1. **인용 마크는 해석 레이어가 아닌 연구 도구**: L5-L8 해석 데이터와 구분하여
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

## D-024: .git 오염 버그 수정 + 서고 백업

**날짜**: 2026-02-24
**맥락**: `document.py`의 `repo.index.add(["."])`(GitPython 저수준 API)가
`.git/` 내부 파일까지 인덱스에 추가하여, push가 차단되는 버그 발생.
또한 비개발자 연구자가 구글 드라이브 등에 서고를 쉽게 백업할 방법이 없었다.

**결정**:

1. **`repo.index.add(["."])` → `repo.git.add("-A")`**:
   `repo.git.add()`는 실제 git 바이너리를 호출하므로 `.gitignore`를 존중하고
   `.git/` 내부를 절대 추가하지 않음. `interpretation.py`는 이미 이 패턴을 사용 중.
   document.py 5개소, snapshot.py 1개소 수정.

2. **기동 시 자동 건강 검사**: `configure()` 호출 시 모든 저장소의 `.git/` 오염을
   탐지하고 자동 수리. 사용자 확인 불필요.

3. **폴더 그대로 백업 (zip 아닌 복사)**: `shutil.copytree()`로 `.git/` 제외 복사.
   구글 드라이브에 폴더 그대로 넣으면 파일 단위로 열람 가능.

4. **필수/선택 구분 UI**: 서고 경로만 "필수", 백업·원격 저장소는 "선택" 배지 표시.
   "설정하지 않아도 모든 기능이 동작합니다" 안내.

**수정 파일**: `document.py`, `snapshot.py`, `library.py`, `backup.py`(신규),
`app_config.py`, `server.py`, `index.html`, `workspace.js`, `workspace.css`

**대안**:
- `.gitignore`에 `.git` 추가만 → 이미 커밋된 파일은 계속 추적됨, 근본 해결 안 됨.
- zip 백업 → 구글 드라이브에서 파일 단위 열람 불가, 비개발자에게 불편.

---

## D-025: 하단 패널 → 액티비티 바 이동 + 급행 정거장 커밋 뷰

**날짜**: 2026-02-24
**맥락**: 하단 패널의 5개 탭(Git 이력, 검증 결과, 의존 추적, 엔티티, 비고)이
가로로 늘어서 화면을 차지하고, Git 커밋 목록은 교정 저장마다 자동 생성되어
불필요하게 길었다.

**결정**:

1. **하단 패널 전체를 액티비티 바 5개 독립 버튼으로 이동**:
   각 탭을 사이드바 섹션으로 변환. 하단 패널과 리사이즈 핸들 완전 제거.
   메인 영역이 전체 높이를 사용할 수 있게 됨.

2. **Git 사다리형 그래프를 세로 방향으로 재작성**:
   사이드바(260px 폭)에 맞추어 가로→세로 레이아웃으로 전환.
   정렬 방향 토글(최신↑/↓) 버튼 추가.

3. **급행 정거장 커밋 뷰 (Push Milestone)**:
   원격 추적 브랜치의 reflog에서 "update by push" 엔트리를 추출하여,
   push 실행 시점의 커밋만 마일스톤 카드로 표시.
   각 카드에 포함된 커밋 수와 레이어별 요약을 표시.
   기본 ON, 토글로 전체 커밋 펼치기 가능.

**수정 파일**: `index.html`, `workspace.js`, `workspace.css`, `git-graph.js`,
`correction-editor.js`, `interpretation.js`, `document.py`, `git_graph.py`, `server.py`

**대안**:
- 하단 패널 유지 + 탭 개수 축소 → 구조적 변화 없이는 화면 효율 개선 불가.
- 날짜별 그룹 접기 → push 시점이 더 의미 있는 단위.
- git squash 도구 → 이력 파괴 위험, 시각적 요약이 더 안전.

---

- [x] 하단 패널 → 액티비티 바 이동 + 급행 커밋 뷰 → D-025
- [x] 비교 탭 L5 표점/현토 표시 수정 → D-026
- [x] server.py 모놀리스 → 8개 라우터 분할 → D-027

---

## D-026: 비교 탭 L5 표점/현토 표시 수정

**날짜**: 2026-02-24
**맥락**: 교차뷰어 비교 모드에서 L5(구두점) 탭을 선택하면 내용이 표시되지 않는 버그.
비교 탭이 `/layers/L5_reading/main_text/pages/{num}` API를 호출하는데,
이 API가 찾는 `page_001.json` 파일은 존재하지 않았다.
실제 L5 데이터는 `_punctuation.json`과 `_hyeonto.json` 접미사 파일에 저장되기 때문.

**결정**:

1. **페이지 단위 L5 비교 전용 API 신설**:
   `GET /api/interpretations/{id}/pages/{num}/l5_compare?kind=punctuation|hyeonto`
   한 페이지의 모든 블록의 표점 또는 현토 파일을 glob으로 수집하여
   `blocks`(원본 JSON)과 `text_summary`(줄 단위 비교용 텍스트)를 반환.

2. **L5 종류 선택 UI 추가**: 교차뷰어 서브탭 바 아래에 "표점/현토" 라디오 버튼.
   L5_reading 탭에서만 표시. 기본값은 표점(punctuation).

3. **비교 패널 API 분기**: `_fetchComparePane()`에서 L5 레이어일 때
   기존 `/layers/` API 대신 `/l5_compare` API를 호출.

**수정 파일**: `server.py`, `interpretation.js`, `index.html`, `workspace.css`

**근거**:
- 기존 `/punctuation`, `/hyeonto` API는 `block_id` 필수 → 페이지 단위 비교에 부적합.
- 새 API로 기존 엔드포인트에 영향 없이 비교 전용 기능 추가.

---

## D-027: server.py 모놀리스 → 8개 라우터 분할

**날짜**: 2026-02-24
**맥락**: server.py가 7,718줄, 158개 라우트, 67개 Pydantic 모델을 담은 모놀리스로 성장.
LLM 컨텍스트 윈도우(500-2,000줄이 적정)를 초과하여 코드 리뷰·수정 시 효율 저하.
3-AI 크로스 리뷰(Claude/Codex/Gemini)에서 공통 1순위로 분할이 권고됨.

**결정**:

1. **도메인별 8개 APIRouter 모듈로 분할**:
   FastAPI의 `APIRouter` 패턴으로, 각 도메인(서고/문헌/해석/LLM·OCR/정렬/독해/주석/버전)을
   독립 파일로 추출. server.py는 ~85줄 조립 파일로 축소.

2. **공유 상태 모듈 `_state.py` 신설**:
   전역 상태(`_library_path`, `_llm_router`, `_llm_drafts`, `_ocr_pipeline`)와
   공유 헬퍼(`_get_llm_router()`, `_resolve_repo_path()`, `_call_llm_text()` 등)를 집약.
   라우터는 `_state.py`에서만 상태를 가져오고, 라우터 간 직접 import 금지.

3. **순환 import 방지**: `_state.py`는 core/llm/ocr 모듈을 lazy import.
   라우터→`_state`→core 단방향 의존만 허용.

4. **하위 호환**: `from app.server import configure, app, _get_llm_router` 경로 유지.
   `__main__.py`, `parsers/generic_llm.py` 등 기존 코드 변경 불필요.

**파일 구조** (2026-04-14 기준):
```
src/app/
├── server.py            ← 앱 생성 + 라우터 마운트 + configure() (~85줄)
├── _state.py            ← 공유 상태 + 헬퍼 (~930줄)
├── __main__.py          ← CLI 진입점
└── routers/
    ├── library.py       ← 서고/설정/백업/휴지통 (15 라우트, ~640줄)
    ├── documents.py     ← 문헌 CRUD/페이지/교정/서지/파서 (32 라우트, ~1,810줄)
    ├── interpretations.py ← 해석 CRUD/레이어/의존/엔티티 (23 라우트, ~1,020줄)
    ├── llm_ocr.py       ← LLM 상태·분석·초안 + OCR (14 라우트, ~830줄)
    ├── alignment.py     ← 이체자 사전/정렬/일괄교정 (17 라우트, ~580줄)
    ├── reading.py       ← L5 표점·현토 + L6 번역 + AI보조 (25 라우트, ~1,150줄)
    ├── annotation.py    ← L7 주석·사전형·인용마크 + AI보조 (34 라우트, ~1,740줄)
    └── version.py       ← Git 그래프/되돌리기/스냅샷 (7 라우트, ~610줄)
```

**검증**: 전체 테스트 476 passed.

**대안**:
- 기능별 분할 (CRUD/LLM/Git) → 도메인 문맥이 파편화되어 거부.
- 마이크로서비스 분리 → 단일 프로세스 아키텍처에 과잉.

---

## D-028: SSE 스트리밍 LLM 호출 + 진행 바 UI

**날짜**: 2026-02-24
**맥락**: LLM 분석(표점·번역·주석)은 10-30초가 걸리는데, 기존 구현은
응답이 올 때까지 UI가 멈춘 것처럼 보였다. 사용자가 진행 상황을 실시간으로
확인할 수 있어야 한다.

**결정**:

1. **SSE(Server-Sent Events) 스트리밍 엔드포인트 추가**:
   - `/api/llm/punctuation/stream` — 표점 생성
   - `/api/llm/translation/stream` — 번역
   - `/api/llm/annotation/stream` — 주석 태깅
   기존 비스트리밍 엔드포인트를 수정하지 않고 `/stream` 접미사로 신설.
   SSE 실패 시 기존 엔드포인트로 자동 폴백.

2. **`_call_llm_text_stream()` 백엔드 함수**:
   `asyncio.Queue`에 `progress`, `complete`, `error` 이벤트를 넣고,
   `StreamingResponse`가 queue에서 꺼내 클라이언트로 전달.
   기존 `_call_llm_text()`를 수정하지 않아 하위 호환성 유지.

3. **Provider별 `call_stream()` 메서드**:
   `base.py`에 추상 메서드 추가, Gemini/Ollama/OpenAI 각각 구현.
   `progress_callback`으로 경과 시간, 토큰 수, 프로바이더명을 전달.

4. **공용 `fetchWithSSE()` 프론트엔드 헬퍼**:
   SSE 스트림 수신 + progress 콜백 + 자동 폴백을 한 함수로 캡슐화.
   표점/번역/주석 에디터에서 공용 사용.

5. **주석 일괄 저장 API**:
   `.../annotations/{block_id}/batch` — AI 태깅 후 N건을 1 POST로 저장.
   기존 N번 왕복 → 1번으로 최적화.

**수정 파일**: `_state.py`, `llm/router.py`, `llm/providers/*.py`,
`routers/annotation.py`, `routers/reading.py`,
`workspace.js`, `punctuation-editor.js`, `translation-editor.js`,
`annotation-editor.js`, `index.html`, `workspace.css`

**대안**:
- WebSocket → SSE보다 복잡하고 양방향이 불필요. 단방향 SSE로 충분.
- 폴링 → 지연이 크고 서버 부하가 높아 거부.

---

## D-029: 인용 내보내기 양식 관리자 (Cite Format Manager)

**날짜**: 2026-02-24
**맥락**: D-020에서 인용 마크의 기본 내보내기 형식을 구현했으나,
학술지마다 인용 양식이 다르다. 연구자가 양식을 정의·저장·재사용할 수 있어야 한다.

**결정**:

1. **양식 라이브러리**: `localStorage`에 양식 프리셋(필드 순서, 구분자, 변환 규칙)을 저장.
   서고 경로와 무관한 사용자 개인 설정이므로 서버가 아닌 브라우저 저장소 사용.
2. **필드 순서 드래그앤드롭**: 인용 필드(저자, 서명권수, 작품면수, 원문, 번역)를
   사용자가 드래그로 재배치. HTML5 Drag and Drop API 사용.
3. **변환 규칙**: 서명호(「」↔〈〉, 『』↔《》) 변환, 따옴표 감싸기 등을
   체크박스로 선택.
4. **액티비티 바 통합**: "인용 양식" 버튼을 액티비티 바에 추가,
   사이드바 패널에서 양식 CRUD.

**새 파일**: `cite-format-manager.js`

**수정 파일**: `citation-editor.js`, `index.html`, `workspace.css`, `workspace.js`

**대안**:
- 서버 측 JSON 파일에 저장 → 서고 간 공유가 필요 없고 개인 설정이므로 localStorage로 충분.
- CSS/HTML 기반 양식 → 구조화된 필드 정의가 필요하므로 JS 객체 기반 채택.

---

## D-030: 전문 편집기 파일 경로 통합 (Layer File Path Reconciliation)

**날짜**: 2026-02-24
**맥락**: D-027(라우터 분할) 후 세 가지 경로 불일치 버그 발견.

1. `_get_resources_dir()`가 `src/resources/`(존재하지 않음)를 가리킴 → 이체자 탭 전체 동작 불가.
2. `core/alignment.py`의 `from src.core.document` → 정식 import 경로가 아님.
3. `get_layer_content()`가 전문 편집기(표점·번역·주석)의 실제 저장 경로를 모름 → 비교 탭 내용 미표시.

**결정**:

1. **`_get_resources_dir()` 경로 수정**: `src/app/routers/alignment.py`에서
   `"..", ".."` → `"..", "..", ".."` (2단계→3단계 상위).
   라우터 분할로 파일 위치가 `src/app/server.py` → `src/app/routers/alignment.py`로
   한 단계 깊어졌기 때문.

2. **import 경로 정규화**: `from src.core.document` → `from core.document`.
   `__main__.py`가 `src/`를 sys.path에 추가하므로 `core.xxx`가 정식 경로.

3. **`_find_specialized_file()` 폴백 탐색 함수 추가**:
   `core/interpretation.py`의 `get_layer_content()`에서 기본 경로에 파일이 없을 때
   전문 편집기가 실제로 사용하는 경로를 탐색:

   | 층 | `_layer_file_path()` 기본 경로 | 전문 편집기 실제 경로 |
   |---|---|---|
   | L5 | `L5_reading/main_text/{pid}_page_{NNN}.json` | `{pid}_page_{NNN}_blk_{BID}_punctuation.json` |
   | L6 | `L6_translation/main_text/{pid}_page_{NNN}.txt` | `{pid}_page_{NNN}_translation.json` |
   | L7 | `L7_annotation/{pid}_page_{NNN}.json` | `L7_annotation/main_text/{pid}_page_{NNN}_annotation.json` |

   기본 경로(`_layer_file_path()`)는 `save_layer_content()`에서도 사용하므로
   변경하지 않고, 읽기 전용 폴백 탐색을 추가.

**수정 파일**: `src/app/routers/alignment.py`, `src/core/alignment.py`, `src/core/interpretation.py`

**교훈**: 리팩토링 시 `__file__` 기반 상대 경로는 파일 이동에 취약.
향후 프로젝트 루트를 `_state.py`에 상수로 등록하는 것을 검토.

---

## D-031: 표점 오프셋 보정 (Display → Original 변환)

**날짜**: 2026-02-24
**맥락**: 원문에 표점 부호(。！？ 등)를 삽입하여 DOM에 표시하면,
Selection API가 반환하는 문자 오프셋에 표점 문자가 포함되어
원문 기준 `start/end`와 불일치하는 버그 발생.
주석 편집기와 인용 편집기 모두에서 동일 문제.

**결정**:

1. **`_annDisplayOffsetToOriginal()` / `_citeDisplayOffsetToOriginal()` 함수 추가**:
   DOM 표시 위치(표점 포함) → 원문 오프셋(표점 미포함) 변환.
   글자별 before/after 버퍼를 구성하여 표점 문자 수만큼 차감.

2. **교정 텍스트 우선 사용**: TextBlock의 `original_text`는 편성(composition) 시점
   스냅샷이므로, `source_refs` → `/api/documents/{id}/pages/{num}/corrected-text`로
   최신 교정 텍스트를 조회. 실패 시 `original_text` 폴백.
   주석·인용·번역·현토 에디터 4곳에 동일 패턴 적용.

**수정 파일**: `annotation-editor.js`, `citation-editor.js`,
`translation-editor.js`, `hyeonto-editor.js`

**대안**:
- 표점 없는 별도 `data-offset` 속성 → DOM 구조가 복잡해져 거부. 계산 방식이 더 단순.

---

## D-032: 정렬 알고리즘 최적화 — n-gram 후보 필터링

**날짜**: 2026-02-24
**맥락**: `_find_best_match_in_ref()`가 O(n*m) 전수 탐색으로,
대량 텍스트(수천 자)에서 느려지는 문제.

**결정**:

1. **n-gram 후보 필터링**: 5-gram 부분 문자열 검색으로 후보 위치를 수집하고,
   후보 주변에서만 `SequenceMatcher`를 실행. O(n*m) → O(k*m) (k << n).
2. **3-gram 폴백**: 5-gram으로 후보가 없으면 3-gram으로 재시도.
3. **NFC 정규화**: `unicodedata.normalize("NFC")`로 인코딩 차이 제거.
   같은 글자의 결합형/완성형 차이로 매칭 실패하는 문제 방지.

**수정 파일**: `src/core/alignment.py`

---

### 원본 저장소
- [ ] JSON 스키마 각 필드의 상세 정의 → Phase 1에서 해결
- [ ] 서지정보 파싱 상세 → Phase 5에서 해결
- [ ] git-lfs 설정 상세 → Phase 2에서 해결
- [ ] block_type 어휘 확장 → 점진적

### OCR
- [x] OCR 엔진 플러그인 아키텍처 → D-009 (Phase 10-1)
- [x] PaddleOCR 기본 엔진 설치 확정 — paddlepaddle 3.3.0 + paddleocr 2.10.0
- [x] NDLOCR-Lite (근현대 범용) 통합 → D-038
- [x] NDL古典籍OCR-Lite (고전적 전용) 통합 → D-039
- [x] PaddleOCR 레이스 컨디션 수정 → D-039
- [x] NDL古典籍OCR Full (TrOCR, 하이브리드) 통합 → D-044
- [ ] OCR 엔진 비교 평가 → Phase 10 이후

### LLM 협업
- [x] LLM 호출 아키텍처 → D-010 (Phase 10-2)
- [x] 프롬프트 설계 원칙 → layout_analysis.yaml (Phase 10-2)
- [x] 비용 관리 → UsageTracker + 월별 예산 (Phase 10-2)
- [x] SSE 스트리밍 LLM 호출 + 진행 바 → D-028

### 저장소 연결
- [x] 사다리형 git 그래프 구현 → D-017 (Phase 12-1)
- [ ] git 호스팅 선정

### 해석 저장소
- [x] 5-8층 데이터 모델 상세 → D-014(L5), D-015(L6), D-016(L7)
- [x] 본문/주석 번역의 연결 구조 → D-015 (SourceRef)
- [x] 사전형 주석 (Dictionary Annotation) → D-019
- [x] 인용 마크 시스템 (Citation Mark) → D-020
- [x] 인용 내보내기 양식 관리자 → D-029
- [x] 전문 편집기 파일 경로 통합 → D-030
- [x] 표점 오프셋 보정 → D-031
- [x] 정렬 알고리즘 최적화 → D-032
- [x] LLM 응답 잘림 방지 + 결과 캐시 → D-033
- [x] 비교 탭 L6/L7 표시 + 전용 API 호출 분기 → D-034
- [x] 주석 라우터 확장 (블록 탐색 + 수정 필드) → D-035
- [x] 주석 유형 관리 UX 개선 (모달 다이얼로그) → D-036
- [ ] 협업 모델

### 서고 관리
- [x] 범용 에셋 감지 + 다운로드 → D-021
- [x] GUI에서 서고 관리 (전환/생성/최근 목록) → D-022
- [x] 휴지통 시스템 (Trash/Restore) → D-023
- [x] .git 오염 버그 수정 + 서고 백업 → D-024

## D-033: LLM 응답 잘림 방지 + 결과 캐시

**날짜**: 2026-02-24
**맥락**: LLM JSON 응답이 `max_tokens` 한도에서 잘려 파싱 오류가 발생하거나,
동일 입력에 대해 불필요한 반복 호출이 발생하는 문제.

**결정**:

1. **목적별 동적 `max_tokens` 계산**: `_state.py`에 `_get_max_tokens_for_purpose(purpose, text_len)` 추가.
   표점(768-2048), 번역(1400-4096), 주석(4096-16384)으로 입력 길이에 비례하여 동적 조절.
2. **잘림 감지 + 예외 발생**: Gemini/OpenAI provider에서 `finish_reason`이 `length`/`max_tokens`이면
   `LlmProviderError`를 발생시켜 잘린 JSON이 조용히 통과하는 것을 방지.
3. **결과 캐시**: `_state.py`에 입력 해시(SHA-256) 기반 인메모리 캐시 (TTL 10분, 최대 256건).
   동일 블록·동일 목적에 대한 반복 호출을 방지.

**수정 파일**: `_state.py`, `gemini_provider.py`, `openai_provider.py`

---

## D-034: 비교 탭 L6/L7 표시 + 전용 API 호출 분기

**날짜**: 2026-02-24
**맥락**: D-026에서 L5 비교를 수정했으나, L6(번역)·L7(주석) 비교 탭도
범용 `/layers/` API가 전문 편집기의 실제 저장 경로를 찾지 못해 빈 화면이 표시되는 동일 문제.
또한 Git 커밋 기반 비교에서도 전문 편집기 파일 경로 우선순위가 역전되어 빈 파일을 읽는 버그.

**결정**:

1. **`_buildCompareUrls()` URL 빌더**: 레이어별로 전용 API URL 목록을 생성하고 순서대로 시도.
   - L5: `/l5_compare` API (블록 지향)
   - L6: `/translation` API → `/layers/` 폴백
   - L7: `/annotations` API → `/layers/` 폴백
   `partId` 불일치도 처리 (실제 partId → "main" 폴백).

2. **Git 커밋 비교 경로 우선순위 수정**: `core/interpretation.py`의 `get_layer_content_at_commit()`에서
   전문 편집기 경로(`_translation.json`, `_annotation.json`)를 기본 경로보다 먼저 탐색.
   기존에는 기본 경로가 먼저여서 빈 파일에 매칭.

3. **L5/L7 레거시 폴백**: 블록별 파일이 없고 페이지 단위 JSON만 있을 때
   해당 JSON의 blocks 배열을 사용하는 레거시 폴백 경로 추가. 현재 API + Git 비교 양쪽 적용.

4. **비교 텍스트 요약 개선**: 빈 marks/annotations 블록은 건너뛰고,
   텍스트 기반 블록에도 원문 텍스트를 표시하도록 제네릭 폴백 추가.

**수정 파일**: `interpretation.js`, `core/interpretation.py`, `routers/reading.py`

---

## D-035: 주석 라우터 확장 — 블록 탐색 + 원문 로드 + 수정 필드 확장

**날짜**: 2026-02-24
**맥락**: 사전형 주석(D-019)의 4단계 생성과 AI 태깅이 블록별 원문 텍스트를
직접 로드해야 하는데, 기존에는 별도 헬퍼 없이 라우터 핸들러 안에서 인라인 처리.
또한 주석 수정 API(`PUT`)가 기본 필드(target, type, content, status)만 허용하여
사전형 필드(dictionary, generation_history 등)를 수정할 수 없었다.

**결정**:

1. **블록 탐색 헬퍼 3종**: `annotation.py`에 `_load_page_blocks()`, `_load_page_block_ids()`,
   `_load_original_block_text()` 추가. L4 원문 → L6 번역 → 엔티티 순으로 폴백.
2. **수정 가능 필드 확장**: `AnnotationUpdateRequest`에 `dictionary`, `current_stage`,
   `generation_history`, `source_text_snapshot`, `translation_snapshot`, `annotator` 추가.
3. **AI 태깅 결과 캐시 통합**: `_state.py`의 `_llm_result_cache`와 연동.

**수정 파일**: `routers/annotation.py`, `_state.py`

---

## D-036: 주석 유형 관리 UX 개선 — 모달 다이얼로그

**날짜**: 2026-02-24
**맥락**: 주석 유형 관리가 `prompt()` 4연타로 ID/라벨/색상/아이콘을 입력받는 구조.
기존 유형 목록 확인 불가, 삭제 UI 없음, 컬러 피커 없음.

**결정**:

1. **bib-dialog 패턴 모달**: 기본 프리셋(읽기전용) + 사용자 정의(삭제 가능) + 추가 폼을
   한 화면에서 관리하는 모달 다이얼로그로 교체.
2. **`<input type="color">` 컬러 피커**: hex 직접 입력 대신 브라우저 내장 컬러 피커.
3. **ID 검증**: 영문으로 시작, 영문·숫자·밑줄만 허용하는 정규표현식 클라이언트 검증.
4. **모달 닫기 시 자동 갱신**: 유형 필터 셀렉트, 편집 패널 유형 셀렉트를 자동 갱신.

**수정 파일**: `index.html`, `annotation-editor.js`, `workspace.css`

---

## D-037: HWP/HWPX/PDF 가져오기 기능 일시 비활성화

**날짜**: 2026-02-24
**상태**: 준비중

**맥락**: hwp-import.js로 구현된 HWP/HWPX/PDF 텍스트 가져오기 기능이
아직 안정적이지 않아 사용자에게 혼란을 줄 수 있다.

**결정**:

1. **버튼 비활성화**: 사이드바의 "HWP" 버튼을 "가져오기"로 변경하고,
   클릭 시 `showToast('준비중입니다', 'info')`만 표시.
   `opacity: 0.5`로 시각적 비활성화 상태 표현.
2. **코드 보존**: `hwp-import.js`와 `#hwp-import-overlay` HTML은 삭제하지 않음.
   기능이 준비되면 `onclick`만 `_openHwpImportDialog()`로 복원하면 됨.
3. **백엔드 엔드포인트 유지**: `/api/documents/import-hwp`, `/api/text-import/pdf/*` 등
   API 엔드포인트도 그대로 유지. 프론트엔드 진입점만 차단.

**수정 파일**: `index.html`

**복원 방법**: `index.html`의 `import-hwp-btn` onclick을
`_openHwpImportDialog()`로 복원하고 opacity/cursor 스타일 제거.

---

## D-038: NDLOCR-Lite 통합 — 세 번째 OCR 엔진 + 서버사이드 레이아웃 감지

**날짜**: 2026-02-25
**맥락**: PaddleOCR이 Python 3.13 + Windows 환경에서 PaddlePaddle의 OneDNN 런타임 오류로
동작하지 않는 문제. 대안으로 일본 국립국회도서관의 ndlocr-lite를 세 번째 OCR 엔진으로 통합.

**결정**:

1. **ONNX Runtime 기반 오프라인 OCR**: PaddlePaddle 의존 없이 ONNX Runtime만으로 동작.
   Python 3.10+ (3.13 포함) 호환. 별도 설치: `uv sync --extra ndlocr`.

2. **페이지 단위 인식 (Page-Level OCR)**: 기존 블록별 크롭→인식과 다른 경로.
   - DEIM(DEIMv2): 전체 페이지에서 17클래스 레이아웃+행 탐지
   - PARSeq 캐스케이드: 행 이미지에서 문자 인식 (30/50/100자 모델 단계적 적용)
   - XY-Cut: 읽기 순서 결정
   - L3 블록 매칭: 인식된 행을 기존 L3 블록의 bbox와 공간적으로 매칭

3. **BaseOcrEngine 확장**: `supports_page_level: bool` 속성과 `recognize_page()` 메서드를
   선택적(non-abstract)으로 추가. 기존 PaddleOCR/LLM Vision은 `False`(기본값)이므로 무영향.

4. **파이프라인 분기**: `pipeline.py`에서 `getattr(engine, 'supports_page_level', False)`로
   방어적 접근. 조건 충족 시 페이지 단위 경로, 실패 시 블록별 경로로 자동 폴백.

5. **서버사이드 레이아웃 감지 API**: `POST /api/ocr/detect-layout/{doc_id}/{page}`.
   DEIM 17클래스를 프로젝트 block_type으로 매핑. KotenLayout(브라우저 5클래스)의 대안.
   프론트엔드에서 엔진 드롭다운으로 선택.

6. **언어 제한 고지**: 한문(CJK 한자)/일본어만 지원. 한글 미인식.
   OCR 패널에서 ndlocr 선택 시 경고 표시.

7. **모델 자동 다운로드**: ONNX 모델(~147MB)은 git에 포함하지 않고,
   `~/.cache/classical-text-browser/ndlocr-models/`에 첫 사용 시 GitHub에서 자동 다운로드.

8. **소스 벤더링**: ndlocr-lite 소스를 `src/ocr/ndlocr/`에 벤더링.
   import 경로를 상대 경로로 수정. 라이선스 CC BY 4.0 (NDL, Japan).

**ndlocr 카테고리 → block_type 매핑**:
| ndlocr class | 이름 | block_type |
|---|---|---|
| 0 | text_block | main_text |
| 1 | line_main | main_text |
| 2 | line_caption | annotation |
| 4 | line_note (割注) | annotation |
| 5 | line_note_tochu (頭注) | marginal_note |
| 6 | block_fig | illustration |
| 8 | block_pillar (柱) | page_title |
| 9 | block_folio | page_number |
| 16 | line_title | main_text |

**파일 구조**:
```
src/ocr/
├── base.py              ← +supports_page_level, +recognize_page()
├── pipeline.py          ← +페이지 단위 분기, +_page_image_to_bytes()
├── registry.py          ← +ndlocr 등록 블록
├── ndlocr_engine.py     ← 신규: NdlocrEngine (OCR + 레이아웃 감지)
└── ndlocr/              ← 신규: 벤더링된 ndlocr-lite 소스
    ├── __init__.py      ← 모델 다운로드 관리
    ├── deim.py          ← DEIM 레이아웃 탐지기
    ├── parseq.py        ← PARSeq 문자 인식기
    ├── ndl_parser.py    ← XML 변환기
    ├── reading_order/   ← XY-Cut 읽기순서 모듈
    └── config/          ← ndl.yaml, NDLmoji.yaml
```

**수정 파일**: `base.py`, `pipeline.py`, `registry.py`, `pyproject.toml`,
`llm_ocr.py` (+detect-layout 엔드포인트), `index.html`, `ocr-panel.js`,
`layout-editor.js`, `workspace.css`, `ocr/__init__.py`

**신규 파일**: `ndlocr_engine.py`, `src/ocr/ndlocr/` (벤더링 ~15파일)

**대안**:
- Tesseract OCR → CJK 세로쓰기 정확도가 현저히 낮아 거부.
- EasyOCR → PyTorch 의존으로 설치 크기가 과대, Python 3.13 호환 미확인.
- 브라우저 전용 OCR (Tesseract.js) → CJK 품질 부족.

---

## D-039: NDL古典籍OCR-Lite 통합 — 고전적 전용 OCR 엔진 + PaddleOCR 레이스 컨디션 수정

**날짜**: 2026-02-25
**맥락**: D-038에서 통합한 NDLOCR-Lite는 근현대 인쇄 자료 범용 엔진이다.
에도 이전 와고서, 청대 이전 한적 등 고전적(古典籍) 자료에 특화된
ndlkotenocr-lite를 네 번째 OCR 엔진으로 추가하고, 기존 PaddleOCR의
공유 인스턴스 레이스 컨디션 버그도 함께 수정한다.

**결정**:

1. **RTMDet 레이아웃 탐지기 벤더링**: ndlkotenocr-lite의 RTMDet(1280×1280 입력, BGR)을
   `src/ocr/ndlkotenocr/rtmdet.py`에 벤더링. 업스트림은 `class_index=1`을 하드코딩하지만,
   우리 버전은 **실제 모델 출력 class_id를 보존**하여 16클래스 레이아웃 감지를 지원한다.

2. **단일 PARSeq 모델 (캐스케이드 없음)**: ndlocr의 3단계 PARSeq 캐스케이드와 달리,
   ndlkotenocr는 단일 PARSeq 모델(32×384)만 사용. 고전적 문자셋(NDLmoji.yaml, ~42KB) 전용.

3. **코드 공유**: `parseq.py`, `ndl_parser.py`, `reading_order/` 모듈은 기존 ndlocr 패키지에서 공유.
   RTMDet와 config 파일만 별도 벤더링하여 최소한의 코드 추가.

4. **ndl.yaml 호환성 매핑**: ndlkotenocr의 16개 클래스를 ndlocr의 ndl_parser.py와 호환:
   - `table` → `block_table` (ndl_parser가 인식하는 이름)
   - `line_note_dummy` → `line_note_tochu` (두주 클래스)

5. **엔진 등록 순서 변경**:
   NDL古典籍OCR-Lite(1순위, 기본 엔진) → NDLOCR-Lite(2순위) → LLM Vision(3순위, "느릴 수 있음") → PaddleOCR(4순위, Python 3.13 미지원)
   고전적 전용 엔진이 드롭다운에서 먼저 보이고, 첫 번째 사용 가능 엔진이 기본 엔진으로 선택된다.

6. **detect-layout API 일반화**: `engine_id` 쿼리 파라미터 추가.
   기존 하드코딩된 ndlocr 전용 → 어떤 `supports_layout_detection=True` 엔진이든 사용 가능.
   `engine_id=None`이면 레이아웃 감지를 지원하는 첫 번째 사용 가능 엔진을 자동 선택.

7. **프론트엔드 일반화**: `_runAutoDetectNdlocr()` → `_runAutoDetectServer(engineId)`로 리팩토링.
   엔진별 개별 함수 대신 범용 서버사이드 감지 함수로 통합.
   드롭다운에 ndlkotenocr 옵션 추가.

8. **PaddleOCR 레이스 컨디션 수정 (Codex CLI 교차검증 발견)**:
   - **문제**: `paddle_engine.lang = body.paddle_lang`이 공유 싱글톤을 mutation.
     동시 요청 시 언어가 뒤바뀌는 레이스 컨디션 발생.
   - **수정**: `engine_kwargs["paddle_lang"]`으로 전달하여 공유 인스턴스를 변경하지 않음.
     `PaddleOcrEngine._get_ocr(lang=...)`가 언어별 인스턴스를 캐시하여 안전하게 처리.
     `pipeline.run_block()`도 `**engine_kwargs`를 전달하도록 수정.

9. **모델 자동 다운로드**: ONNX 모델(~74MB)은 git에 포함하지 않고,
   `~/.cache/classical-text-browser/ndlkotenocr-models/`에 GitHub 1.3.1 태그에서 자동 다운로드.

**ndlkotenocr 16클래스 → block_type 매핑**:
| class | 이름 | block_type |
|---|---|---|
| 0 | text_block | main_text |
| 1 | line_main | main_text |
| 2 | line_caption | annotation |
| 3 | line_ad | unknown |
| 4 | line_note | annotation |
| 5 | line_note_tochu | marginal_note |
| 6 | block_fig | illustration |
| 7 | block_ad | unknown |
| 8 | block_pillar (柱) | page_title |
| 9 | block_folio (ノンブル) | page_number |
| 10 | block_rubi | unknown |
| 11 | block_chart | illustration |
| 12 | block_eqn | unknown |
| 13 | block_cfm | unknown |
| 14 | block_eng | unknown |
| 15 | block_table | illustration |

**파일 구조**:
```
src/ocr/
├── base.py                   ← +supports_layout_detection 속성
├── pipeline.py               ← run_block() **engine_kwargs 전달 수정
├── registry.py               ← 4개 엔진 등록 순서 변경
├── paddleocr_engine.py       ← 언어별 인스턴스 캐시 (레이스 컨디션 수정)
├── ndlocr_engine.py          ← +supports_layout_detection = True
├── ndlkotenocr_engine.py     ← 신규: NdlkotenOcrEngine (단일 PARSeq + RTMDet)
└── ndlkotenocr/              ← 신규: 벤더링된 RTMDet + config
    ├── __init__.py            ← 모델 다운로드 관리 (~74MB)
    ├── rtmdet.py              ← RTMDet 레이아웃 탐지기 (class_id 보존)
    └── config/
        ├── ndl.yaml           ← 16클래스 (block_table로 매핑)
        └── NDLmoji.yaml       ← 고전적 전용 문자셋
```

**수정 파일**: `base.py`, `pipeline.py`, `registry.py`, `paddleocr_engine.py`,
`ndlocr_engine.py`, `llm_ocr.py`, `pyproject.toml`, `index.html`, `layout-editor.js`

**신규 파일**: `ndlkotenocr_engine.py`, `src/ocr/ndlkotenocr/` (3파일 + config 2파일)

**검증**: Codex CLI (gpt-5.3-codex) 교차검증 완료. 6건 발견 → 자체 코드 3건 수정 완료.

**대안**:
- ndlkotenocr를 ndlocr의 서브클래스로 구현 → RTMDet/DEIM 입력 차이가 커서 별도 클래스가 더 명확.
- PaddleOCR lang mutation을 Lock으로 보호 → Lock은 비동기 환경에서 복잡. 인스턴스 캐시가 더 단순.

---

## D-040: ndlkotenocr OCR 파이프라인 — 업스트림 class_index 호환성 복원

**날짜**: 2026-02-25

**맥락**: ndlkotenocr-lite 통합 후 OCR 결과가 비정상적으로 나오는 문제 발생.
업스트림 소스 비교 결과, 근본 원인은 `_process_detections()`에서
RTMDet 탐지의 실제 `class_id`를 보존한 채 `resultobj`에 분배한 것.

**원인 분석**:
- 업스트림 `rtmdet.py`의 `postprocess()`는 **모든 탐지의 class_index를 1(line_main)로 하드코딩**
- 이는 OCR 파이프라인(ndl_parser → XY-Cut → PARSeq)이 모든 탐지를 LINE으로 처리하도록 설계됐기 때문
- 우리 벤더링은 `detect_layout()` 지원을 위해 실제 class_id를 보존했으나,
  `_process_detections()`에서도 실제 class_id를 사용하여 탐지가 16개 슬롯에 분산
- 결과: 실제 행인데 class 0(text_block)으로 분류된 탐지가 LINE XML 요소가 되지 못하고
  PARSeq 인식에서 누락 → 텍스트 빠짐, 순서 꼬임

**결정**:
1. `_process_detections()`: 모든 탐지를 class 1(line_main) 슬롯에 추가 (업스트림 호환)
2. `recognize()`: class_id 기반 LINE 필터 제거, 탐지 존재 여부만 확인
3. `conf_threshold`: 0.25 → 0.3 (업스트림 동일)
4. RTMDet 자체는 실제 class_id 보존 유지 (`detect_layout()`에서 활용)

**원칙**: OCR 파이프라인은 업스트림 동작을 충실히 재현한다.
실제 class_id는 `detect_layout()`에서만 활용하며, OCR 경로에서는 사용하지 않는다.

---

## D-041: ndlkotenocr PARSeq — RGB 입력 (BGR 변환 금지)

**날짜**: 2026-02-25

**맥락**: D-040 수정 후에도 ndlkotenocr OCR 결과가 비정상적.
업스트림 소스를 세밀하게 비교한 결과, PARSeq 전처리의 색상 채널 차이를 발견.

**원인 분석**:
- ndlocr-lite PARSeq (`parseq.py`): 전처리에서 `resized[:,:,::-1]` (RGB→**BGR** 변환)
- ndlkotenocr-lite PARSeq: 전처리에서 **RGB 그대로** (변환 없음)
- 두 모델의 학습 데이터 전처리가 다름: ndlocr=BGR, ndlkotenocr=RGB
- 우리 코드는 ndlocr의 PARSeq 클래스를 공유하므로,
  ndlkotenocr 모델에 BGR 입력이 들어가 빨강↔파랑 채널 반전
- 채널 반전으로 문자 특징이 왜곡되어 인식 정확도 대폭 하락

**결정**:
1. 공유 `PARSEQ` 클래스에 `bgr_input: bool = True` 파라미터 추가
2. `bgr_input=True` (기본값): ndlocr 호환 — RGB→BGR 변환 수행
3. `bgr_input=False`: ndlkotenocr 호환 — RGB 그대로 유지
4. `ndlkotenocr_engine.py`에서 `PARSEQ(..., bgr_input=False)` 설정

**근거**: ndlocr/ndlkotenocr 두 모델의 학습 전처리가 다르므로
공유 클래스에서 런타임에 전환할 수 있어야 한다.
코드 중복(별도 parseq.py) 없이 파라미터 하나로 해결.

---

## D-042: loadOcrResults() 브라우저 캐시 누락 버그

**날짜**: 2026-02-25

**맥락**: D-040·D-041 수정 후 백엔드는 정상 OCR 결과를 생성하지만,
GUI에서 "이전 결과와 같다"는 보고. 원인 조사 결과 프론트엔드 캐시 문제.

**원인 분석**:
- `ocr-panel.js`의 `loadOcrResults()` — 페이지 전환 시 L2 OCR 결과를 불러오는 함수
- `fetch()` 호출에 `cache: "no-store"` 옵션이 빠져 있음
- 같은 파일의 `_fillFromOcr()`, `_deleteCurrentPageOcr()`에는 이미 있었음
- 브라우저가 기본 캐싱 정책으로 이전 응답을 재사용
- OCR 재실행 후에도 캐시된 옛 결과(D-041 수정 전 결과)가 표시됨

**결정**: `loadOcrResults()`의 fetch에 `{ cache: "no-store" }` 추가.

**영향**: 페이지 전환·새로고침 시 항상 서버에서 최신 OCR 결과를 가져온다.

---

## D-043: NDL古典籍OCR-Lite — 모델 한계와 커스텀 모델 사용 안내

**날짜**: 2026-02-25

**맥락**: ndlkotenocr-lite의 PARSeq 모델은 "tiny" 버전(~37MB)으로,
인식 정확도에 한계가 있다. 일부 행에서 □(U+25A1) 문자, 히라가나 오인식,
단일 문자 행 등이 발생한다. 비-lite 풀 모델을 사용하면 정확도가 올라가지만,
모델 크기가 크고 설치가 복잡하다.

**현재 모델 사양**:
- RTMDet-S: `rtmdet-s-1280x1280.onnx` (~38MB) — 레이아웃/행 탐지
- PARSeq tiny: `parseq-ndl-32x384-tiny-10.onnx` (~37MB) — 문자 인식
- 합계 ~74MB, 자동 다운로드

**결정**: 프로젝트에서 제공하는 기본 모델은 lite 버전을 유지한다.
정확도가 필요한 사용자를 위해 커스텀 모델 교체 방법을 문서화한다.

**커스텀 모델 사용 방법**:

1. **환경변수로 모델 디렉토리 지정**:
   ```
   NDLKOTENOCR_MODEL_PATH=/path/to/custom-models
   ```
   이 디렉토리에 `rtmdet-s-1280x1280.onnx`와 PARSeq `.onnx` 파일을 넣는다.

2. **PARSeq 풀 모델 사용** (정확도 향상):
   - ndlkotenocr (비-lite) 저장소에서 풀 모델 다운로드:
     https://github.com/ndl-lab/ndlkotenocr
   - `parseq-ndl-32x384-tiny-10.onnx`를 풀 모델로 교체
   - 파일명이 다를 경우 `ndlkotenocr_engine.py`의 `_init_models()` 수정 필요

3. **RTMDet 교체** (탐지 정밀도 향상):
   - 같은 입력 사양(1280×1280, BGR, 동일 mean/std)의 모델이면 드롭인 교체 가능
   - 클래스 매핑이 다르면 `config/ndl.yaml`도 함께 교체

4. **문자셋 교체**:
   - 풀 모델이 다른 문자셋을 사용할 경우 `config/NDLmoji.yaml` 교체

**주의사항**:
- lite 모델과 풀 모델의 ONNX 입출력 텐서 형식이 다를 수 있다.
  교체 전 `onnxruntime` 세션으로 입출력 shape를 확인할 것.
- 풀 모델의 PARSeq는 캐스케이드(3단계) 구조일 수 있다.
  단일 모델만 사용하는 현재 코드로는 동작하지 않으며,
  캐스케이드 지원이 필요하면 `ndlocr_engine.py`의 패턴을 참고하여 확장.

---

## D-044: NDL古典籍OCR Full (TrOCR) — 하이브리드 고품질 OCR 엔진

**날짜**: 2026-02-25

**맥락**: D-039에서 통합한 NDL古典籍OCR-Lite의 PARSeq-tiny 모델은
경량(~37MB)이지만 인식 정확도에 한계가 있다(D-043).
NDL古典籍OCR 풀 버전(ndlkotenocr_cli ver.3)은 TrOCR 기반으로
정확도가 훨씬 높지만, PyTorch + GPU가 필요하다.

**결정**: RTMDet ONNX (lite) + TrOCR PyTorch (full) 하이브리드 엔진을 추가한다.

| 구성요소 | lite 엔진 | full 엔진 (하이브리드) |
|----------|----------|----------------------|
| 레이아웃 탐지 | RTMDet ONNX (~38MB) | RTMDet ONNX (lite 공유) |
| 문자 인식 | PARSeq-tiny ONNX (~37MB) | TrOCR PyTorch (~450MB) |
| GPU 필요 | 아니오 | 사실상 필요 (CPU도 동작하나 매우 느림) |
| 의존성 | onnxruntime (~50MB) | torch+CUDA ~4GB, transformers |

**하이브리드 접근 이유**:
- 업스트림 풀 버전은 CascadeRCNN(mmcv+mmdet)을 레이아웃에 사용하지만,
  Windows에서 mmcv/mmdet 설치가 극히 어려움
- RTMDet ONNX는 이미 검증되었고 동일한 클래스(16클래스) 구조를 공유
- 품질 향상의 대부분은 문자 인식(TrOCR)에서 발생

**등록 우선순위** (registry.py auto_register):
1. ndlkotenocr-full (TrOCR) — 최고 품질, torch+GPU 필요
2. ndlkotenocr (PARSeq-tiny) — 경량, CPU OK
3. ndlocr — 근현대 자료 범용
4. llm_vision — LLM 비전 기반
5. paddleocr — Python 3.13 미지원

**의존성 전략**:
- `ndlkotenocr-full` optional extra로 분리
- torch/torchvision은 PyTorch CUDA 인덱스(`cu124`)에서 설치
- torch 미설치 시 `is_available()=False` → 등록하지 않음 → 기존 동작 무영향
- `opencv-python-headless`를 ndlocr/ndlkotenocr/ndlkotenocr-full 3개 extra에 추가

**모델 다운로드**:
- TrOCR 모델 3개 디렉토리 (~450MB): NDL 공식 서버에서 zip 자동 다운로드
- 캐시: `~/.cache/classical-text-browser/ndlkotenocr-full-models/`
- 환경변수: `NDLKOTENOCR_FULL_MODEL_PATH`로 커스텀 경로 지정 가능

**파일 변경**:
- 신규: `src/ocr/ndlkotenocr/trocr.py`, `src/ocr/ndlkotenocr_full_engine.py`
- 수정: `registry.py`, `ndlkotenocr/__init__.py`, `pyproject.toml`, `.gitignore`

**검증 결과** (RTX 3070 Ti Laptop GPU):
- 모델 로딩: ~9초 (CUDA)
- 단일 추론: ~1.4초 (첫 실행 워밍업)
- 배치(4개): ~0.17초 (GPU 효율)
- 세로쓰기 자동 회전: 정상 동작

---

## D-045: 서지 파서 확장 — 국립공문서관 IIIF + KOSTMA + 장서각 + 규장각

**날짜**: 2026-04-15

**맥락**: 기존 파서 체계(NDL, 국립공문서관, KORCIS, 범용 LLM)에서
국립공문서관의 신형 `/file/` 페이지가 PDF 다운로드 실패했고,
한국 고전적 주요 DB(KOSTMA, 장서각, 규장각)는 범용 LLM 폴백만 가능하여
이미지 다운로드가 불가능했다.

**결정**: 4건의 파서 작업을 수행한다.

| 작업 | 파서 | 변경 유형 | 핵심 |
|------|------|----------|------|
| 국립공문서관 IIIF 지원 | archives_jp | 기존 수정 | 신형 `/file/` 페이지의 `/img/{id}` → IIIF manifest 기반 다운로드 |
| KOSTMA 전용 파서 | kostma (신규) | 신규 추가 | 뷰어 팝업 서지 + bookInfos JS → JPEG → PDF |
| 장서각 전용 파서 | jsg (신규) | 신규 추가 | dir/view 테이블 서지 + ajaxThumbs API → JPEG → PDF |
| 규장각 전용 파서 | kyujanggak (신규) | 신규 추가 | book/view.do 서지 + viewImgList.do API → JPEG → PDF |

**국립공문서관 수정 상세**:
- 원인: 신형 페이지에 BID/MID가 없어 `list_assets()`가 빈 목록 반환
- 해법: `_parse_detail_page`에서 `/img/{id}` 링크 → `img_ids` 추출,
  `list_assets`에 IIIF manifest 경로 추가, `download_asset`에 IIIF 분기 추가
- 구형(BID/sizeget/jp2jpeg)과 신형(IIIF)을 `download_type` 필드로 분기

**공통 아키텍처 원칙** (platform-v7.md §7.3 준수):
- BaseFetcher + BaseMapper 쌍으로 구현, register_parser()로 자동 등록
- `supports_asset_download = True`, `list_assets()` + `download_asset()` 구현
- JPEG → PDF 변환은 fpdf2 + PIL 공통 패턴
- URL 자동 판별: `_URL_PATTERNS`에 등록, generic_llm → 전용 파서로 승격

**대안 검토**:
- 범용 LLM 폴백으로 충분한가? → 불충분. JS 변수(bookInfos), 숨겨진 팝업, POST API 등
  HTML 스크래핑 없이는 이미지 URL을 추출할 수 없다.
- 규장각 SSL 문제 → `verify=False` + ssl.SSLContext로 우회 (공공기관 인증서 문제)

**파일 변경**:
- 신규: `src/parsers/kostma.py`, `src/parsers/jsg.py`, `src/parsers/kyujanggak.py`
- 수정: `src/parsers/archives_jp.py` (IIIF 경로 추가),
  `src/parsers/__init__.py`, `src/parsers/base.py`, `src/parsers/registry.json`

## D-046: 교정 편집기 자유 편집 모드 — diff 기반 corrections 자동 생성

**날짜**: 2026-04-15

**맥락**: 교정 시스템이 `char_index` 기반 1:1 글자 치환만 지원하여,
연구자가 OCR 오류를 수정할 때 글자 추가나 삭제가 불가능했다.

**결정**: `corrected_text`를 자유 편집의 primary source로 전환.
저장 시 `difflib.SequenceMatcher`로 원본과 diff하여
`char_index` 기반 corrections를 자동 생성한다.

- 기존 `char_index` 체계를 폐기하지 않는다. 방향만 역전:
  `corrections → corrected_text` (기존) → `corrected_text → corrections` (신규)
- "글자 교정"(span 클릭) + "자유 편집"(textarea) 이중 모드를 토글로 전환
- 기존 corrections의 메타데이터(유형, 비고, 이문 등)는 `_merge_corrections()`로 보존
- corrections.schema.json에 `corrected_text` nullable 필드 추가 (하위 호환)
- 일괄 교정 시스템은 이번 스코프 밖 (기존 방식 유지, 추후 전환)

**대안 검토**:
- A. `char_index` 기반 유지 + 시프트 관리 → 시프트 누적 관리 복잡, 기각
- B. `corrected_text`를 primary로 전환 + diff → corrections 자동 생성 → **채택**

**파일 변경**:
- `src/core/document.py`: `_diff_to_corrections`, `_merge_corrections` 추가, `get_corrected_text` 수정
- `schemas/source_repo/corrections.schema.json`: `corrected_text` 필드 추가
- `src/app/routers/documents.py`: PUT 핸들러 diff 분기 추가
- `src/app/static/js/correction-editor.js`: 이중 모드 + textarea + 저장 분기
- `src/app/static/css/workspace.css`: 자유 편집 스타일
- `src/app/static/index.html`: 모드 토글 버튼

---

## D-047: OpenAI OAuth 프록시 프로바이더 추가

**날짜**: 2026-04-16

**맥락**: API 키 없이 ChatGPT 계정으로 OpenAI 모델을 무료로 사용할 수 있는
openai-oauth 프록시 연동 필요.

**결정**: `OpenAiProvider`를 상속하는 `OpenAiOAuthProvider`를 생성하고,
`_create_client()` 오버라이드로 `base_url`만 변경한다.
포트 10531~10540을 자동 스캔하여 실행 중인 프록시에 연결한다.

- 기존 `OpenAiProvider`에서 `_create_client()` 헬퍼를 추출하여 오버라이드 가능하게 변경
- 폴백 순서: Ollama → OpenAI OAuth → Gemini → OpenAI → Anthropic (4단→5단)
- 프록시 미실행 시 자동 스킵, 다음 프로바이더로 폴백

**대안 검토**:
- A. 기존 `OpenAiProvider`에 `base_url` 옵션 추가 → 프로바이더 분리가 더 깔끔하여 기각
- B. 별도 독립 클래스로 구현 → 코드 중복 발생하여 기각
- C. 상속 + `_create_client()` 오버라이드 → **채택**

**파일 변경**:
- `src/llm/providers/openai_oauth_provider.py`: 신규 프로바이더 클래스
- `src/llm/providers/openai_provider.py`: `_create_client()` 헬퍼 추출
- `src/llm/router.py`: 5단 폴백 순서 반영

**영향**: 프록시 실행 시 API 비용 $0

---

## D-048: 외부 SikuRoBERTa 표점 서비스 자동 연동

**날짜**: 2026-05-08

**맥락**: yachagye의 Korean Classical Chinese Punctuation Prediction Model v2.5를
본체에 직접 넣으면 torch/transformers/대용량 가중치 때문에 설치가 무거워진다.
동시에 사용자는 본체에서 환경변수를 매번 지정하지 않고 표점 탭에서 바로 쓰길 원한다.

**결정**:
- 본체의 외부 표점 기본 URL은 `http://127.0.0.1:8765`로 둔다.
- 명시적으로 끌 때만 `EXTERNAL_PUNCT_URL=off`를 사용한다.
- `start_server.bat` / `start_server.sh`는 `punctuation-service/.env` 또는
  `PUNCT_MODEL_HOST_PATH`가 있으면 Docker Compose로 표점 서비스를 자동 기동한다.
- 모델 출처는 UI/API 응답에 `SikuRoBERTa, 양정현 2025`와 DOI로 표기한다.

**영향**: Docker Desktop과 모델 경로만 준비되어 있으면 배치파일 하나로 본체+표점 서비스가 함께 올라온다.

---

## D-049: Windows 시작 배치파일의 OpenAI OAuth 자동 기동

**날짜**: 2026-05-08

**맥락**: UI에는 OpenAI OAuth 프로바이더가 노출되어 있으나 프록시를 따로 띄워야 하면
비개발자 사용자의 실행 단계가 늘어난다.

**결정**:
- `start_server.bat`가 `npx.cmd -y openai-oauth`를 별도 창에서 자동 실행한다.
- 포트 `10531~10540`의 `/v1/models`를 확인하여 실제 프록시 URL을 찾고
  `OPENAI_OAUTH_BASE_URL`로 본체에 전달한다.
- 자동 기동을 건너뛰려면 `OPENAI_OAUTH_AUTO_START=0`을 사용한다.

**영향**: 배치파일 하나로 무료 온라인 LLM 폴백까지 준비된다. 첫 실행 로그인은 열린 프록시 창에서 진행한다.

---

## D-050: 주석·인용 탭의 블록 선택 및 원문 스냅샷 폴백

**날짜**: 2026-05-08

**맥락**: 번역까지 마친 뒤 주석/인용 탭으로 이동하면 드롭다운에 블록이 비거나,
인용 마크의 통합 컨텍스트에서 원문이 비는 e2e 문제가 발견되었다.

**결정**:
- 주석/인용 탭은 TextBlock, LayoutBlock, 이전 탭의 현재 블록, `pNN_b01` 기본값을
  순서대로 사용해 블록 선택을 복구한다.
- 인용 편집기는 원문 드래그 선택으로 즉시 마크 생성 프롬프트를 열고,
  원본 블록을 다시 찾지 못하면 저장된 `source_text_snapshot`으로 컨텍스트를 구성한다.

**영향**: 표점→현토→번역 이후에도 주석/인용 단계가 같은 블록 흐름을 이어받는다.

---

## D-051: 관측 가능성 — LLM 사용 로그 OTel 시맨틱 컨벤션 명명 정렬 (Phase 1)

**날짜**: 2026-05-19
**상태**: 확정 (Phase 1만 적용. Phase 2/3은 [`observability-roadmap.md`](observability-roadmap.md) 참조)

**맥락**: 본 프로젝트는 결정 카드(D-001~D-050)·세션 카드·검증 명령으로 **프로세스 관측 가능성**(process observability)을 잘 갖추고 있지만, **런타임 관측 가능성**(runtime observability)은 `llm_usage_log.jsonl` 한 종류에 그친다. Walking Labs의 "하네스 엔지니어링" 강의 11은 **계층화된 관측 가능성**(layered observability)을 위해 OpenTelemetry로 신호의 모양을 표준화하라고 권한다. 새 도구·SDK 도입은 비용을 동반하므로, *데이터 모델만 먼저 표준에 맞추고 SDK·백엔드는 단계적으로 미루는* 접근을 택한다.

**결정**:

1. **Phase 1: 키 명명만 정렬, 코드·의존성·동작 변경 없음.**
   - [`src/llm/usage_tracker.py`](../src/llm/usage_tracker.py)의 JSONL 각 줄에 OTel GenAI Semantic Conventions 키를 **함께 기록** (이중 기록).
   - 옛 키(`provider`·`model`·`tokens_in`·`tokens_out`·`cost_usd`·`elapsed_sec`·`purpose`·`ts`·`type`)는 다운스트림 호환을 위해 **그대로 유지**.
   - 새 키: `gen_ai.system`·`gen_ai.request.model`·`gen_ai.response.model`·`gen_ai.usage.input_tokens`·`gen_ai.usage.output_tokens`·`gen_ai.operation.name`·`duration_ms`·`@timestamp`·`event.name`·`schema_url`. OTel 표준 없는 비용은 `harness.cost_usd`로 자체 네임스페이스.

2. **Phase 2 (보류): `opentelemetry-sdk` 도입 + 콘솔 익스포터.** 발동 조건은 `observability-roadmap.md`. LLM·OCR·정렬 호출 결정 경계에 수동 span. FastAPI 자동 계측.

3. **Phase 3 (보류): Jaeger/Tempo Docker 부착.** [D-048](#d-048)·[D-049](#d-049)의 외부 서비스 자동 기동 패턴을 그대로 따른다.

4. **벤더 락인 금지**: Datadog·Honeycomb·New Relic 등 SaaS 도입 금지. OTel-호환 백엔드만 허용 (라이선스가 PolyForm Noncommercial이라 유료 SaaS는 어울리지 않음).

**근거**:
- Phase 1은 다운스트림(`get_monthly_summary()`) 코드 한 줄도 안 건드린다. 이중 기록이라 JSONL 줄당 크기가 ~30% 늘지만 분석 도구가 어느 키를 골라도 작동.
- 미래 Phase 2 도입 시 옛 키만 제거하면 끝. 코드 마이그레이션 비용이 0에 수렴.
- OTel은 단일 벤더 제품이 아니라 *데이터 모델 + SDK + OTLP 프로토콜*의 집합이므로 표준화 자체가 락인을 줄이는 방향이다.

**트레이드오프**:
- 채택: 이중 기록 — 무파괴, 점진적.
- 거부 (하드 컷오버): 새 키만 출력하고 다운스트림을 동시에 수정. 깔끔하지만 기존 `llm_usage_log.jsonl` 파일을 한 번 마이그레이션해야 함. 가치 대비 비용 큼.
- 거부 (Phase 2 즉시 도입): `opentelemetry-sdk` 즉시 추가. 의존성 ~200MB 증가, 본 프로젝트의 단일 사용자 데스크톱 사용 패턴에서 ROI가 아직 명확하지 않음.

**검증**:

```powershell
uv run python -c "from src.llm.usage_tracker import UsageTracker; print('import ok')"
uv run python -c "from src.llm.usage_tracker import _OTEL_SCHEMA_URL; print(_OTEL_SCHEMA_URL)"
```

**관련**:
- 로드맵 문서: [`observability-roadmap.md`](observability-roadmap.md)
- 회고에서의 위치: [`retrospective/05_harness.md`](retrospective/05_harness.md) H5(검증 명령) · H8(회고 가능한 오류)와 결합
- 강의 11 (Walking Labs): https://walkinglabs.github.io/learn-harness-engineering/ko/lectures/lecture-11-why-observability-belongs-inside-the-harness/

---

## D-052: 드래그 앤 드롭 온보딩 — 경로 설정 없는 첫 시작

**날짜**: 2026-07-17

**결정**:
1. **파일 드롭 = 새 문헌 생성 진입점.** 창 어디에나 PDF/이미지(폴더 포함)를 끌어다 놓으면
   새 문헌 다이얼로그가 파일이 채워진 Step 2 상태로 열린다 (`static/js/drag-drop.js` 신설).
2. **드롭은 경로 참조가 아니라 바이트 업로드.** 기존 `POST /api/documents/create-from-files`를
   그대로 재사용해 `L1_source/`로 복사한다.
3. **doc_id 자동 생성은 서버 책임.** `create-from-files`의 doc_id가 비면 첫 파일명에서
   ASCII 후보를 만들고, 한자/한글뿐이면 `doc_YYYYMMDD`, 충돌 시 `_2`·`_3`을 붙인다.
   제목이 비면 첫 파일명 stem(한자 보존)을 쓴다.
4. **기본 서고 원클릭 확보.** `POST /api/library/quick-start` 신설 —
   `~/Documents/고전서지서고`를 만들거나(없으면) 재사용해 즉시 전환한다.
   서고 미설정 상태에서 드롭하면 프론트가 이를 자동 호출한 뒤 토스트로 위치를 알린다.

**근거**:
- 기존 온보딩은 “서고 설정 열기 → 폴더 선택(tkinter) → init → + 새 문헌 → 파일 추가 →
  doc_id 영문 입력 → 생성”의 6단계 이상이었고, 특히 한자 파일명이면 doc_id 자동 후보가
  빈 문자열이라 연구자가 영문 ID를 지어내야 했다.
- 브라우저 보안상 드롭 파일의 절대 경로는 읽을 수 없다. 그러나 이 플랫폼은 애초에
  원본을 L1_source로 **복사해 불변층으로 격리**하는 설계(platform-v7)라, 경로 참조가
  아닌 바이트 복사가 설계와 정합한다. 원본 이동 시 링크가 끊기는 Zotero식 문제도 없다.
- doc_id 생성을 프론트가 아닌 서버에 두는 이유: 유일성 판정(기존 문헌과 충돌 회피)은
  documents/ 디렉토리를 아는 쪽만 할 수 있다.

**트레이드오프**:
- 채택: 웹앱 유지 + 업로드 복사. 거부 (네이티브 앱 재작성): 드롭 경로 획득·파일 연결은
  얻지만, 라우트 169개·JS 28모듈 이식 비용과 “빌드 도구 없음” 원칙 훼손이 크다.
  나중에 필요하면 pywebview로 현 코드를 그대로 감쌀 수 있다 (되돌리기 쉬운 결정).
- 채택: 드롭 후 Step 2 확인 화면 경유(클릭 1회). 거부 (드롭 즉시 무확인 생성):
  잘못 떨어뜨린 파일이 곧장 git 커밋된 문헌이 되는 위험이 절약되는 클릭 1회보다 크다.

**검증**: `uv run python -m pytest tests/test_onboarding_api.py -q` (API 4건) +
브라우저 실측 (서고 미설정 → 드롭 → quick-start → 생성까지 E2E, 2026-07-17).

**관련**: [D-022](#d-022-gui에서-서고library-관리) GUI 서고 관리 위에 얹힘.
explain-diff: [`sessions/session_dragdrop_onboarding.md`](sessions/session_dragdrop_onboarding.md)

---

## D-053: 구조 부채 상환 — ID 규칙 단일화 + 경로 검증 통일 + 생성 롤백

**날짜**: 2026-07-17

**배경**: 같은 날의 인지부채 감사(4축 리뷰)가 확인한 구조 부채 3건.
D-052(드래그 앤 드롭 온보딩)가 밟는 땅의 위생 문제였다.

**결정**:
1. **ID 규칙 단일 진실원**: `core/repo_id.py` 신설. 8곳에 복제돼 있던
   `^[a-z][a-z0-9_]{0,63}$`을 파이썬 1곳(이 모듈) + JS 1곳
   (create-document.js `_DOC_ID_PATTERN`, 정본과 짝 명시)으로 수렴.
   기존 이름(`_DOC_ID_PATTERN`·`_INTERP_ID_PATTERN`·`_REPO_ID_PATTERN`)은
   하위 호환 별칭으로 유지.
2. **경로 검증 통일**: `_state.require_repo_path(repo_type, repo_id)` 신설 —
   실패 시 `RepoPathError`를 던지고 server.py의 예외 핸들러가 이 프로젝트
   에러 규약(`{"error": ...}` + 400/500)으로 변환한다. 6개 라우터 ~95지점의
   인라인 `_library_path / "documents" / id` 조립을 1줄 치환으로 대체.
   read 경로도 이제 ID 형식(경로 탈출)을 검증한다. best-effort 루프 2곳
   (source_refs 커밋 해시 보강)은 요청을 거절하지 않도록 `_resolve_repo_path`
   (None 반환)로 처리해 기존 관용 동작을 유지.
3. **create-from-url 롤백**: add_document 성공 이후의 마무리 단계(manifest
   재작성·git commit) 실패 시 문헌 폴더를 정리하고 예외를 재전파 —
   “실패 = 아무것도 안 남음”을 create-from-files와 등가로 보장.
   git.Repo는 with 문으로 열어 Windows 핸들 잠금을 줄였다.
4. **사이드바 갱신 단일화**: create-document.js `_refreshSidebar`가
   workspace.js `loadLibraryInfo`(정본)에 위임. 해시 복원은
   `{restoreHash: false}` 옵션으로 꺼서 생성 직후 화면 재탐색을 방지.

**의도적 보류 — JS 전역 결합(ES 모듈 전환)**: 28개 비모듈 스크립트와
`viewerState` 전역 변이는 남는다. 전환은 전 파일 이식 + 로드 순서 재설계가
필요한 재작성급 변경인데 프론트 테스트가 0건이라 위험/이득이 맞지 않는다.
착수 조건: 프론트 스모크 테스트(최소 초기화·문헌 열람 경로)가 먼저 생겨야 한다.

**행동 변화(의도됨)**: 형식이 잘못된 ID로 read API를 부르면 이전에는
404(“없음”)였지만 이제 400(“형식이 올바르지 않습니다”)이다. 프론트는
`data.error`만 소비하므로 영향 없음. 트래버설 문자가 든 경로는 종전처럼
라우팅 단계에서 404로 걸러지고, 인코딩을 우회해 도달해도 검증에 걸린다.

**검증**: 전체 pytest 490 통과 + 라이브 API 실측(형식위반→400 통일 메시지,
미존재→404 유지, 정상→200; documents·interpretations·reading 라우터 표본).

**관련**: [D-052](#d-052-드래그-앤-드롭-온보딩--경로-설정-없는-첫-시작) ·
explain-diff: [`sessions/session_dragdrop_onboarding.md`](sessions/session_dragdrop_onboarding.md)

---

## D-054: 문헌 생성 시 기본 해석 저장소 자동 생성 + 시작 창 정리

**날짜**: 2026-07-17

**결정**:
1. **기본 해석 저장소 자동 생성**: `create-from-files`·`create-from-url` 성공 직후
   `<doc_id>_interp`(hybrid, 문헌 제목 승계)를 자동 생성한다
   (documents.py `_auto_create_default_interpretation`). 실패해도 문헌 생성은
   유효하므로 예외를 삼키고 응답 `warning`으로만 알린다. 응답에
   `interpretation_id`가 추가되고 완료 메시지에 표시된다.
2. **시작 창 정리 (start_server.bat)**: 브라우저 오프너를 2초짜리 cmd 창 대신
   숨김 PowerShell(`start /b` + `-WindowStyle Hidden`)로 바꾸고, OpenAI OAuth
   프록시는 **창 없이**(`start /b`) 백그라운드로 돌리며 출력을
   `logs\openai-oauth.log`로 보낸다 — 보이는 창은 메인 서버 창 하나다.
   (1차 시도였던 `start /min` 최소화는 Windows 11 기본 터미널인 Windows
   Terminal이 최소화 지시를 무시해 실패했다 — 2026-07-17 실측. conhost 강제도
   실환경에서 실패해 창 없는 방식으로 확정. 로그인 안내는 로그 파일로 확인하고,
   메인 창을 닫으면 프록시도 함께 종료되어 잔여 프로세스가 없다.)

**근거**:
- 해석 저장소는 표점·번역·주석(L5-L7)의 전제 조건인데, 지금까지는 문헌 등록
  후 해석 탭에서 ID를 지어 수동 생성해야 했다 — doc_id와 같은 종류의 마찰.
  D-052의 “드롭 → 바로 작업”을 완성하려면 이 단계도 없어져야 한다.
  생성 비용은 폴더 골격 + git init 수준으로 저렴하고, 다중 해석 저장소
  모델(독립 해석 작업)과도 충돌하지 않는다 — 기본 하나가 미리 있을 뿐이다.
- `start_server.sh`(macOS/Linux)는 이미 `&` 백그라운드라 변경 불필요.
- 외부 표점 서비스는 모델 가중치를 **첫 표점 호출 때** lazy 로드해 수 분
  걸릴 수 있다. 본체 타임아웃을 60→300초로 늘리고, 상태 확인 엔드포인트
  (`GET /api/llm/punctuation/external/health`)와 경과 시간 진행 표시를 붙여
  “멈춘 게 아니라 로딩 중”임을 보여준다. 진행률(%)은 원리상 알 수 없어
  경과 시간 방식을 택했다.

**트레이드오프**:
- 채택: 항상 자동 생성. 거부 (옵트인 체크박스): 다이얼로그에 선택지를 하나
  더 얹는 것 자체가 이번에 없애려는 마찰이다. 원치 않으면 해석 탭에서
  삭제(휴지통)하면 된다.
- interp_id는 doc_id를 54자로 잘라 `_interp`를 붙인다 — 64자 규칙
  (core/repo_id.py) 안에서 충돌 접미사(_N) 여유를 남기기 위해서다.

**검증**: `tests/test_onboarding_api.py`에 interpretation_id·목록 등재 단언 추가,
전체 pytest 통과. 배치 파일은 수동 실행 확인 필요(창 2개 감소 기대).

**관련**: [D-052](#d-052-드래그-앤-드롭-온보딩--경로-설정-없는-첫-시작) 온보딩의 완결편.

---

## D-055: 추출 모드 — 작업 모드 분리 + 텍스트 레이어 산출물

**날짜**: 2026-07-25

**맥락**: 이 앱은 고서(古書)를 읽기 위해 만들어졌고 상단 탭 10개가 그 작업 순서를
그대로 드러낸다. 그런데 근현대 논문 스캔본에서 텍스트만 뽑으려 할 때 이 의례가 과하다.
수요는 형제 저장소 `cjk-refmanager`에서 나왔다 — 그쪽은 스캔 PDF를 **진단만 하고
넘기기로** 결정했고(비전 OCR을 서지 관리 유틸리티에 넣으면 유틸리티가 파이프라인이 된다),
그 공백을 이 저장소가 받는다.

실측(2026-07-25, 합성 논문 스캔본 3쪽)으로 확인한 마찰:
문헌 등록까지는 이미 **드롭 + 클릭 1회**로 끝난다(D-052·D-054). 병목은 그 다음이다.
텍스트를 얻으려면 «레이아웃 탭 → 자동감지 → OCR → 교정 탭 → OCR 채우기»가
**페이지마다** 필요하고, `POST .../ocr`은 레이아웃이 없으면 200 OK에 `status: partial`,
`errors: ["L3 레이아웃을 찾을 수 없습니다"]`로 **조용히 0건**을 반환한다.
게다가 기본 엔진은 «설치된 것 중 첫 번째»(registry.py)라 논문에도
`ndlkotenocr-full`(고전적 전용, **한글 인식 불가**)이 잡힌다.

**결정**:

1. **가르는 축은 문헌 종류가 아니라 «한 글자씩 교감(校勘)하는 작업인가»이다.**
   `collation`(교감, 탭 10개)과 `extract`(추출, 3개)를 상단 탭 오른쪽 토글로 오간다.
   추출 모드는 교감 전용 탭 7개(**편성·표점·현토·번역·주석·인용·이체자**)를
   `hidden`으로 감출 뿐이다. 모드 전환 함수 `_switchMode`, 각 패널, 저장 데이터는
   **하나도 바뀌지 않는다**. 숨겨진 탭이 활성이면 열람으로 폴백한다
   (제거된 `interpretation` 모드와 같은 방식).

   **왜 «고서/논문»이 아닌가**: 근대 영인본·활자본 문집·한문으로 쓴 논문처럼
   경계가 애매한 자료에서 사용자에게 «이건 둘 중 뭐냐»를 판정하라고 강요하게 된다.
   실제로 그 토글이 하는 일은 문헌 분류가 아니라 «표점·현토·이체자 단계를 쓸 것이냐»다.

   **남기는 셋에는 각각 이유가 있다**:
   열람(원본을 봐야 한다), 레이아웃(드물지만 일본어 세로쓰기 다단은 영역 지정이 필요하다),
   교정(인쇄 품질이 나쁘면 OCR 결과를 손봐야 한다).
   번역·주석·인용은 서지 관리 도구(cjk-refmanager)로 넘길 일이라 여기서 감춘다.

   **판별은 하지 않는다.** 앱이 «이건 논문이다»라고 추측하지 않고 사용자가 직접 고른다.
   자동으로 판단하는 것은 텍스트 레이어 유무뿐이며, 그것은 파일 속성이라 확실히 알 수 있다.
2. **모드는 문헌별로 `localStorage`에 기억한다** (`ctb.profile.<doc_id>`).
   한 서고에 고서와 논문이 섞이므로 문헌을 바꾸면 따라간다.
   문헌 파일에는 **아무것도 기록하지 않는다.**
3. **추출 모드로 바꿀 때 «비어 있는» 해석 저장소는 휴지통으로 옮긴다.**
   문헌을 만들면 해석 저장소가 함께 생기는데(D-054) 추출 작업은 L5-L7을 쓰지 않아
   빈 채로 목록에 쌓인다. 단 **내용이 하나라도 있으면 건드리지 않고** 그 사실을 알린다 —
   모드 전환은 표시를 바꾸는 일이지 데이터를 지우는 일이 아니다.
   삭제가 아니라 휴지통이므로 되돌릴 수 있다.
3. **스캔본 OCR은 «페이지 전면 LayoutBlock 1개»로 푼다** (`src/ocr/full_page_block.py`).
   레이아웃이 **비어 있을 때만** 페이지 전체를 덮는 블록 하나를 만든다. 그러면 기존
   파이프라인이 한 줄도 바뀌지 않고 그대로 돈다. 사람이 잡아 둔 레이아웃은 건드리지 않는다.
4. **권 단위 일괄 OCR** `POST /api/documents/{doc_id}/parts/{part_id}/ocr/batch` (SSE).
   **L2 자체가 체크포인트다** — 결과가 있는 쪽은 건너뛰므로, 끊고 다시 보내면 이어서 돈다.
   별도 상태 파일이 없다. 한글 불가 엔진(`ndlocr`, `ndlkotenocr`, `ndlkotenocr-full`)을
   고르면 **시작 시점에** 경고한다.
5. **산출물은 «텍스트 레이어를 텍스트 레이어 PDF»다** (`src/export/text_layer_pdf.py`).
   사이드카 `.txt`와 달리 복사·Ctrl+F·구조 분석(PageIndex)·참고문헌 추출이 한꺼번에 살아난다.
   `page.insert_text(..., render_mode=3)`(invisible)로 원본 이미지 위에 겹친다.
   출력은 `<문헌>/exports/{part_id}_text.pdf` — **`L1_source/`는 읽기만 한다.**
6. **born-digital PDF는 OCR을 아예 건너뛴다.** 등록 응답과 전용 라우트가
   텍스트 레이어를 진단하고(`born_digital` / `partial` / `scanned`),
   `POST .../text-import/from-text-layer`가 활자를 그대로 L4로 옮긴다.

**근거**:

- **D-004의 미구현분 이행이지 새 결정이 아니다.** D-004는 "층 번호와 실제 작업 순서는
  다를 수 있다"며 경로 B(L2 전체 OCR → L3 → L4)와 경로 C를 이미 유효하다고 못박았고
  "앱은 세 경로를 모두 지원해야 한다"고 적었다. `user-guide.md`도 "이 순서가 필수는
  아닙니다"라고 안내한다. **건너뛰기는 문서화돼 있었는데 UI에서 숨길 방법이 없었을 뿐이다.**
- **D-009의 계약을 깨지 않는다.** `L3 → crop → 엔진 → L2`와 "파이프라인 경유"를 그대로
  지킨다. 전면 블록은 그 계약의 **입력을 채워 줄 뿐**이고, 배치 라우트는 `run_page()`를
  부르는 루프다. 블록이 하나뿐이므로 "OCR이 읽는 순서를 지정한다"는 D-002의 의미론에도 맞다.
- **저장 데이터에 아무것도 추가하지 않으므로** `additionalProperties: false`인 스키마 7종,
  D-018 스냅샷(`schema_version: "1.0"`), 용어 규칙이 전부 무영향이다. 구현 중 스키마가
  실제로 두 번 막아섰고(`analysis_method` enum, `block_id` 패턴 `^p\d+_b\d+$`),
  둘 다 스키마를 고치지 않고 기존 값에 맞췄다.
- **텍스트 레이어 입히기는 새 의존성이 필요 없다.** PyMuPDF 1.27.1이 이미 있고,
  OCRmyPDF·Tesseract는 도입하지 않았다(D-039가 Tesseract를 CJK 정확도로 거부한 바 있다).

**트레이드오프**:

- 채택: **폰트를 임베드하지 않는 PDF 표준 CJK 폰트**(`fontname="korea"`) — 실측 **쪽당 +0.9KB**.
  거부: `TextWriter` + 폰트 임베드 — 같은 텍스트에 **+1,663KB/쪽**, `subset_fonts()`를 써도
  +10.6KB/쪽. 300쪽이면 감당할 수 없다. 대신 CJK CMap을 못 읽는 뷰어를 위해
  `embed_font=True` 옵션을 남겼다.
- 채택: **`localStorage`에 문헌별 프로필.** 거부: manifest에 `document_type` 필드 추가 —
  스키마가 `additionalProperties: false`라 개정이 강제되고 D-018 스냅샷 버전까지 파급된다.
  거부: 서버 설정 키 — `~/.classical-text-browser/config.json`에는 UI 토글을 담는 키가 없다.
- 채택: **전역 기본 엔진은 그대로 두고 요청 단위로 지정.** 거부: `registry`의 기본값을
  `llm_vision`으로 바꾸기 — 고서 사용자의 기본 동작이 바뀐다.
- 채택: **born-digital용 단순 추출 라우트 신설.** 거부: D-037로 봉인된 hwp-import 다이얼로그
  해제 — 그쪽은 "원문+번역+주석을 LLM으로 나눈다"는 다른 목적이고 "아직 안정적이지 않다"는
  D-037의 판단이 유효하다. 논문은 나눌 갈래가 없다. 사이드바 "가져오기" 버튼은
  **추출 모드에서만** 이 새 경로에 연결되고, 교감 모드에서는 봉인 그대로다.
7. **위치는 검출로 따로 얻는다** (`src/ocr/line_detector.py`).
   `llm_vision`은 bbox를 반환하지 않으므로(`llm_ocr_engine.py`) 그것만으로는
   텍스트를 원본 글자 자리에 놓을 수 없다. 그래서 **인식은 LLM Vision이,
   위치는 PaddleOCR 검출이** 맡는 분업을 쓴다. 검출은 «글자가 어디 있는지»만
   보므로 언어와 무관하다.

   **왜 PaddleOCR로 읽지 않는가** (실측 2026-07-25, 국한문 혼용 논문 1쪽):
   `lang=korean`은 한글 479자·**한자 0자**, `lang=chinese_cht`는 한자 202자·
   **한글 0자**를 읽었다. 두 모델이 상보적이라 국한문 혼용은 어느 하나로도
   읽을 수 없다. 반면 검출은 두 경우 모두 같은 위치를 정확히 짚었다.

   **줄 수가 정확히 맞을 때만 위치를 채운다.** 검출과 인식은 줄을 나누는 방식이
   다를 수 있는데, 어긋난 채로 순서를 맞추면 **모든 줄이 밀려** 위치가 없는 것보다
   나빠진다. 개수가 다르면 손대지 않고 순서 배치로 남긴다.

   **임계값은 쪽마다 탐색한다.** 고정값으로는 불가능하다는 것이 실측으로 드러났다 —
   2단 목차는 가로 간격 6% 이하여야 좌우가 갈리는데, 한시 대역이 있는 쪽은
   12% 이상이어야 낱말이 안 쪼개진다. 요구가 모순된다. 그러나 **정답 줄 수를
   이미 알고 있으므로**(LLM이 읽은 줄 수) 그것을 목표로 조합을 훑어 고른다.

   실측(같은 논문 15쪽): 고정 임계값 365/502줄(73%) → 적응적 탐색 **433/502줄(86%)**.
   못 맞춘 69줄은 순서 배치로 남았다. 쪽당 약 8초가 더 든다.

- **알려진 한계**: 검출로 자리를 못 찾은 줄은 왼쪽 여백에서 시작해 세로로 균등
  배치된다(x 고정, y 간격 일정). 그런 줄의 형광은 **한 줄 크기로 정확히 뜨지만
  그 자리에 글자가 없다.** 「위치가 대략적」이 아니라 **「위치가 틀렸다」**가 정확한
  서술이다. 한 줄이라도 그렇게 되면 산출물 메타데이터(`producer`)에
  `page-approximated`로 남겨 이 PDF만 보고도 알 수 있게 한다.
  PaddleOCR가 없는 환경에서는 검출 없이 전부 이 방식이 된다.
- **프론트 테스트 0건**이라는 D-053의 착수 조건에 걸린다. 그래서 변경을 마크업 속성
  추가와 함수 몇 개로 최소화하고 `_switchMode`를 건드리지 않았다. 검증은 jsdom 하네스로
  실제 `index.html` + `workspace.js`를 올려 44건 실측했으나, **이 하네스는 저장소에
  포함하지 않았다**(npm 의존성 도입은 별건). 정식 프론트 스모크 테스트는 여전히 미결이다.
- **`hidden` 속성이 CSS에 져서 탭이 하나도 숨지 않았다** — 구현 중 실제로 겪은 결함이다.
  `hidden`의 기본 동작(`display:none`)은 브라우저 기본 스타일시트라, 작성자 스타일시트의
  `.mode-tab { display: flex }`가 우선순위로 덮어쓴다. 속성은 정확히 붙었고 JS도 정상인데
  화면은 그대로였다. `workspace.css` 맨 위에 `[hidden] { display: none !important }`를
  두어 해결했다. `!important`를 쓴 것은 «이 요소는 지금 의미가 없다»가 어떤 레이아웃
  규칙보다 우선해야 하고, 그러지 않으면 `display`를 지정하는 규칙을 추가할 때마다
  같은 함정을 다시 밟기 때문이다.
  **jsdom은 이 결함을 재현하지 못한다** — 수정을 빼고 돌려도 탭 검사는 통과했다.
  즉 이 부류의 버그는 현재 하네스로 잡히지 않으며, 브라우저 실측이 유일한 수단이다.
- **정적 파일에 `Cache-Control`이 없어 고친 JS·CSS가 반영되지 않았다.** 기본
  `StaticFiles`는 캐시 헤더를 붙이지 않아 브라우저가 `Last-Modified`로 캐시 기간을
  스스로 추정한다. `?v=` 쿼리를 손으로 올리는 방식은 올리는 것을 잊으면 같은 일이
  벌어진다. `_NoCacheStaticFiles`로 `no-cache, must-revalidate`를 붙였다.
  ETag가 함께 나가므로 변경이 없으면 304로 끝나 로컬에서는 비용이 없다.

**검증**: `uv run python -m pytest` — **550 passed**
(기존 490 + 신규 60: `test_text_layer_pdf.py` 19, `test_lite_mode_api.py` 27, `test_line_detector.py` 14).
API는 TestClient로 직접 호출해 응답을 확인했고(진단 3분류, 배치 재개 2/3건너뜀,
입히기 후 `search_for()` 좌표 오차 0.2pt, 원본 무수정, 빈 해석 저장소 정리 시
작업물 보존), 프론트는 jsdom으로 44건 + 부팅 재현(29개 스크립트 전 로드 후
DOMContentLoaded 발생) + CSS 계산 8건 실측. 브라우저 실측으로 최종 확인.

**관련**: [D-004](#d-004-층-번호와-실제-작업-순서는-다를-수-있다) 경로 B·C의 UI 이행.
[D-009](#d-009-ocr-엔진-플러그인-아키텍처) 파이프라인 계약 무손상.
[D-037](#d-037-hwphwpxpdf-가져오기-기능-일시-비활성화) 봉인 유지.
[D-054](#d-054-문헌-생성-시-기본-해석-저장소-자동-생성--시작-창-정리) 생성 흐름 무개입.
explain-diff: [`sessions/session_extract_mode.md`](sessions/session_extract_mode.md)

---

## D-056: LLM 사용 투명성 — 어느 모델로 얼마를 썼는지 보여 준다

**날짜**: 2026-07-26

**맥락**: OCR을 15쪽 돌리는 동안 사용자도 나도 **무엇이 처리하고 있는지 몰랐다.**
폴백 순서(Ollama → OAuth → Gemini → OpenAI → Anthropic)만 보고 «1순위가 무료
로컬이니 비용이 0일 것»이라고 여겼는데, `llm_usage_log.jsonl`을 열어 보니
전부 `gemini-2.5-flash`가 찍혀 있었다.

원인은 `ollama.py`의 비전 기본 모델 `gemma4:e4b`가 **설치돼 있지 않아서**였다.
호출이 실패하면 라우터가 조용히 다음 프로바이더로 넘어가므로 화면에는 아무 표시도
남지 않는다. 실제 금액은 $0.0084(15쪽)로 작았지만, **모르는 채로 유료 API가
소모되고 있었다는 것**이 문제다.

**결정**:

1. **Ollama 비전 모델을 자동으로 고른다.** 기본값이 설치돼 있지 않으면 설치된
   비전 모델 중에서 찾되 **클라우드를 우선**한다(로컬 소형 모델은 이 PC 사양에서
   성능이 떨어진다는 사용자 판단). `.env`의 `OLLAMA_VISION_MODEL`이 있으면 그것을
   먼저 쓴다. 결과는 캐시한다 — 매 쪽마다 `/api/show`를 부르면 OCR이 느려진다.
2. **과금 방식을 프로바이더 속성으로 명시한다** (`BaseLlmProvider.billing_model`).
   `metered`(Gemini·OpenAI·Anthropic) / `subscription`(OpenAI OAuth, Ollama 클라우드) /
   `free`(Ollama 로컬). Ollama는 한 프로바이더에 로컬·클라우드가 섞여 있으므로
   `billing_for_model()`이 모델 이름으로 가른다.
3. **구독 한도 사용을 «무료»라고 표시하지 않는다.** 구독형은 금액이 0으로
   기록되는데 그대로 «$0.00»을 띄우면 공짜로 오해한다. 실제로는 계정 한도를
   쓰고 있다. 호출 횟수·토큰을 보여 주고 «한도가 소모됩니다»라고 적는다.
4. **배치 완료 응답에 이번 실행의 사용량을 싣는다** — 모델, 호출 수, 토큰, 금액,
   과금 방식, 안내 문구. 추출 패널이 그것을 화면에 남긴다.
5. **추출 패널에서 비전 모델을 고를 수 있게 한다.** 목록에 과금 방식을 함께
   적는다(«구독 한도» / «종량 과금» / «로컬 무료»). 비우면 폴백 순서를 따른다.

**근거**:

- 이 저장소의 사용자는 비개발자 연구자다. 어느 API가 도는지 로그를 뒤져
  확인하라고 할 수 없다. **쓴 자리에서 보여야 한다.**
- 3,358쪽을 돌리면 종량제로는 약 $1.89, 구독형으로는 한도의 상당량이다.
  어느 쪽인지 모르고 시작하면 안 된다.

**트레이드오프**:

- 채택: 남은 한도는 **제공자 대시보드로 안내**. 거부: 앱에서 한도 조회 —
  실측(2026-07-25)으로 확인한 결과 Ollama 클라우드는 응답 헤더에 rate limit
  정보를 주지 않고(`X-RateLimit-*` 없음), 본문에도 사용량·잔여 한도가 없다.
  로컬 `/api/version`·`/api/ps`도 마찬가지다. 조회할 방법이 확인되지 않았으므로
  **있는 것처럼 만들지 않는다.**
- 채택: 비전 모델 **자동 탐지**. 거부: 기본값을 다른 모델로 하드코딩 —
  그 모델이 없는 환경에서 같은 사고가 반복된다.

**검증**: `uv run python -m pytest` — **556 passed**
(신규 4: 과금 분류, «무료»로 표시하지 않음, 배치 응답의 usage, Ollama 모델별 판정).
실제 확인: Ollama 비전 모델 자동 선택 → `qwen3.5:397b-cloud`,
사용 기록 집계 → `gemini/gemini-2.5-flash` 15회 $0.0084.

**관련**: [D-055](#d-055-추출-모드--작업-모드-분리--텍스트-레이어-산출물) 추출 모드의 OCR 경로에 붙는다.

---

### 배포·설치
- [ ] Google Drive + .git 충돌 회피 가이드 → Phase 10 이후
- [ ] 비개발자용 Git 번들링 또는 Git-free 모드 → Phase 10 이후

### 전체
- [ ] 라이선스/공개 범위
- [ ] 프로젝트 이름
