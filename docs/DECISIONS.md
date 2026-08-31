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

## D-057: 부분 재-OCR — 레이아웃을 고친 쪽을 기계가 찾아낸다

**날짜**: 2026-07-26

**맥락**: 논문 수십 쪽을 한 번에 OCR 하면 대개는 잘 나오지만 몇 쪽은 그렇지 않다.
2단 조판, 한시 원문과 번역이 나란한 쪽, 표가 있는 쪽이다. 이런 쪽은 레이아웃
탭에서 영역을 손으로 나눈 뒤 **그 쪽만** 다시 돌려야 한다.

그런데 배치 OCR은 «L2 결과가 있으면 건너뛴다»가 기본이다(중단 후 이어 돌리기
위해서다 — L2 자체가 체크포인트다). 그래서 손으로 고친 쪽까지 건너뛴다.
사용자 입장에서는 **영역을 나눴는데 결과가 그대로**다. 왜 그런지 화면에
설명이 없다.

**결정**:

1. **레이아웃이 OCR 이후에 바뀐 쪽을 자동으로 다시 돌린다** (`redo_changed_layout`,
   기본 켜짐). 사용자가 어느 쪽을 고쳤는지 기억해 쪽 번호를 입력할 필요가 없다.
2. **판정은 이미 저장된 데이터로 한다.** L2의 각 OcrResult에는 어느 LayoutBlock을
   읽었는지가 `layout_block_id`로 남아 있다. 이 집합과 현재 L3의 `block_id` 집합을
   비교한다 — 전면 블록 1개로 돌린 쪽을 3개로 나누면 집합이 달라진다.
   블록 수는 같고 영역만 조정한 경우는 파일 수정 시각으로 보되 **5초의 여유**를 둔다
   (파이프라인이 L3를 읽은 직후 L2를 쓰므로 시각이 붙어 있다).
3. **확실할 때만 다시 돈다.** `layout_block_id`가 null이거나(경로 B), L3가 없거나,
   판정에 필요한 정보가 부족하면 «안 바뀌었다»로 둔다. 오판의 대가가 비대칭이기
   때문이다 — 잘못 «바뀌었다»고 하면 쪽마다 LLM 호출이 다시 나간다.
4. **실행 전에 규모를 보여 준다** (`GET .../ocr/pending`). 몇 쪽이 미처리이고
   몇 쪽이 레이아웃 수정분인지, 그 쪽 번호가 무엇인지 버튼 옆에 적는다.
5. **수동 지정 경로를 함께 둔다** — 쪽 범위와 강제 재실행(`skip_existing: false`,
   패널의 「이미 처리한 쪽도 다시」)은 **독립된 두 스위치**다. 자동 판정은
   레이아웃이 바뀐 쪽만 찾으므로 «판형은 멀쩡한데 인쇄가 흐려 틀리게 읽힌 쪽»,
   «다른 모델로 다시 해 보고 싶은 쪽»은 사람이 골라야 한다.
   `pages=[12]` + `skip_existing=false` = **12쪽만 무조건 다시**.
   예상 규모 표시도 두 스위치를 함께 반영한다 — 범위를 무시하고 «전체가 다시
   돕니다»라고 말하면 300쪽 문헌에서 한 쪽을 고치려는 사람에게 300회를
   태울 것처럼 보인다. 범위만 지정하고 체크박스를 안 켰을 때는
   «켜세요»라고 안내해 이 경로를 발견할 수 있게 한다.
6. **폴더 배치에 쪽 단위 재개를 넣는다.** 기록 파일(`_load_done`)은 편 단위 재개만
   해 준다. 한 편의 중간에서 멈추면 그 편이 1쪽부터 다시 돌거나(비용 이중 지출)
   문헌 ID 충돌로 영영 실패했다. 문헌이 이미 있으면 다시 만들지 않고, 결과가 있는
   쪽은 건너뛴다.

7. **어느 쪽이 나쁜지 알아낼 수단을 함께 둔다** (`GET .../ocr/overview`).
   1~6은 전부 «12쪽이 나쁘다»를 이미 안다는 전제 위에 서 있었다. 그런데 텍스트를
   보는 경로가 쪽 단위뿐이라 15쪽이면 15번 눌러야 알 수 있고 300쪽이면 불가능하다.
   쪽마다 줄 수·글자 수·좌표 유무·본문 앞머리를 한 번에 돌려주고,
   `empty`(돌았는데 결과 없음) / `not_run`(아직 안 돌림) / `few_chars`(중앙값의
   40% 미만) / `no_position`으로 표시한다.
8. **훑어보기를 남겨 둔 탭으로 잇는다.** D-055는 추출 모드에 열람·레이아웃·교정을
   남겼는데, 정작 추출 패널은 그 탭들이 없는 것처럼 동작했다. 발견한 문제의
   모든 길이 «다시 OCR»로만 이어졌고, **같은 엔진·같은 레이아웃이면 결과도
   대체로 같다.** 행마다 세 갈래를 둔다 — 「대조」→ 교정 탭(원본 옆에서 글자를
   고친다. 몇 글자 오독은 이쪽이 빠르고 확실하다), 「영역」→ 레이아웃 탭
   (2단·표), 행 클릭 → 쪽 범위 편입(엔진·모델을 바꿔 다시 돌릴 때).
   탭 전환은 `_switchMode()`를 직접 부르지 않고 **탭 버튼을 클릭**한다 —
   하이라이트 처리가 `initModeBar()`의 핸들러 안에 있어 직접 부르면 어긋난다.
9. **만들기 전에 «다 봤는가»를 알린다.** 결과에 확신이 있으면 추출 화면에서 바로
   텍스트 레이어 PDF를 만드는 것이 가장 편한데, 그 확신은 쪽마다 대조해야 생기고
   300쪽에서는 기억에 의존하면 반드시 빠뜨린다. 쪽마다 확인 표시를 두고 진행률
   (`3/15쪽 확인`)과 남은 쪽을 산출물 절에 표시한다. **막지는 않고 알리기만 한다.**
   확인 기록은 **localStorage**에 둔다 — 사람의 작업 상태이지 문헌 데이터가
   아니고, 저장소에 넣으려면 스키마를 고쳐야 한다(작업 프로필과 같은 판단, D-055).
   확인 당시의 글자 수를 함께 적어 **다시 OCR 해서 내용이 바뀌면 확인이 저절로
   풀리게** 한다. 안 그러면 보지 않은 결과를 봤다고 기록한 셈이 된다.

**근거**:

- 스키마에 타임스탬프를 넣지 않은 이유: `layout_page` / `ocr_page` 스키마는 둘 다
  `additionalProperties: false`다. 시각 필드를 넣으려면 스키마를 고쳐야 하고
  교환 형식(D-018)에 영향이 간다. **판정에 필요한 정보가 이미 저장돼 있다.**
- 훑어보기를 만들자마자 실제 서고의 15쪽 논문에서 **1·2·3·13쪽이 빈 채로 남아
  있는 것**을 발견했다. 그 전까지 아무도 몰랐다 — 훑어볼 수단이 없었기 때문이다.
  미리보기 덕분에 머리글이 `玄同`이어야 할 쪽이 `友同`으로 읽힌 것도 함께 나왔다.
  **글자 수만으로는 정상으로 보이는 쪽이었다.**
- `few_chars`를 «틀렸다»가 아니라 «봐 두라»로 둔 이유: 표지·간지·참고문헌 쪽은
  원래 글자가 적다. 자동 판정으로 걸러 버리면 정상인 쪽을 다시 돌리게 된다.
  실제 글자 수와 본문 앞머리를 함께 주고 최종 판단은 사람에게 남긴다.
- **통계로 잡히는 것과 잡히지 않는 것을 구분해 화면에 적는다.** 훑어보기가
  잡는 것은 글자 수처럼 숫자로 드러나는 문제뿐이다. 위 `玄同`→`友同` 오독은
  글자 수가 다른 쪽과 같아 표시가 붙지 않는다. «표시 없는 쪽 = 문제 없는 쪽»으로
  읽히면 훑어보기가 오히려 확인을 방해한다. 그래서 안내문 첫머리에
  «표시가 없어도 틀렸을 수 있습니다»를 넣고 「대조」로 유도한다.
- 빈 쪽 4개를 실제로 열어 보니 **정상적인 본문 첫 페이지**였다(제목·목차·본문·
  각주가 빽빽하다). 글자가 없어서 빈 것이 아니라 호출이 실패한 것이다.
  그래서 `empty`는 «다시 돌리면 나올 가능성이 높은» 쪽으로 안내하고,
  나머지 오독은 «다시 돌려도 대체로 같으니 교정에서 고치라»고 갈라 적는다.
- 중앙값은 **글자가 나온 쪽만** 놓고 낸다. 빈 쪽을 섞으면 기준선이 끌려 내려가
  진짜 부실한 쪽이 정상으로 보인다(위 논문에서 840 → 939).
- 사용자가 원래 구상한 흐름(«특정 쪽만 레이아웃을 다시 잡아 그 쪽만 다시 돌린 뒤
  전체 텍스트를 갱신») 그대로다. 마지막 «전체 갱신»은 `embed_after`가 권 전체를
  다시 입히므로 이미 성립한다.

**트레이드오프**:

- 채택: 자동 판정. 거부: 쪽 범위를 손으로 입력 — 어느 쪽을 고쳤는지 사람이
  기억해야 하고, 틀리면 조용히 반영되지 않는다.
- 파일 수정 시각을 보조로 쓰므로 git으로 저장소를 다시 받은 직후에는 오판할 수
  있다. `use_mtime=False`로 끌 수 있게 두었고, 최악의 결과는 «불필요하게 한 번 더
  돈다»이지 데이터 손상이 아니다.
- `skip` 블록은 비교에서 제외한다. 포함시키면 집합이 영원히 어긋나 매번 다시 돈다.

**검증**: `uv run python -m pytest` — **598 passed** (신규 30).
수동 지정 경로는 6가지 조합(범위 유무 × 강제 유무)을 실제 마크업·실제 함수로
확인했고, 백엔드가 `pages=[3]` + `skip_existing=false`에서 **3쪽만** 건드리는 것을
회귀로 고정했다 — 범위를 무시하면 300쪽 문헌에서 한 쪽을 고치려다 300회를 태운다.
훑어보기는 실제 서고의 15쪽 논문에 걸어 **1·2·3·13쪽이 비어 있음**을 찾아냈다
(그 전까지 «15쪽 전부 완료»로 알고 있었다 — 훑어볼 수단이 없어 아무도 몰랐다).
훑어보기·검수 UI는 실제 응답을 jsdom에 태워 25가지를 확인 — 살펴볼 쪽 4개 표시,
«좌표 없음»이 모든 쪽에 해당할 때 한 번만 안내, 쪽 클릭 시 이동·범위 편입·해제,
「대조」·「영역」이 탭을 열되 쪽 범위는 건드리지 않음(stopPropagation),
확인 표시가 localStorage에 글자 수와 함께 남고 **내용이 바뀌면 저절로 풀림**.
실제 데이터 확인: 15쪽 논문(`C:\tmp\ctb_ui2`)에서 다시 돌 쪽 `[]` → 사본의 12쪽을
2단으로 나눈 뒤 `[12]`, 사유 «OCR 당시 블록 1개 → 현재 2개». 2단 레이아웃은
`save_page_layout()`의 스키마 검증을 통과했다. CLI 재개는 가짜 파이프라인으로
확인 — 2쪽까지 돌고 끊긴 뒤 재실행하면 3쪽만 호출된다.

**관련**: [D-055](#d-055-추출-모드--작업-모드-분리--텍스트-레이어-산출물) 추출 모드의 배치 OCR에 붙는다.
[D-009](#d-009-ocr-파이프라인-계약) 계약은 그대로다 — 이 판정은 파이프라인 바깥에서 «돌릴지 말지»만 정한다.

---

## D-058: 배포용 LLM 연결 — 「닿는가」와 「인증됐는가」를 나눈다

**날짜**: 2026-07-26

**맥락**: 배포판에서는 각자 자기 계정으로 LLM을 연결해야 한다. API 키 방식은
«`.env`에 키를 넣으세요»로 끝나지만, 구독형(Ollama 클라우드·OpenAI OAuth)은
**터미널 로그인**이 필요하고 앱이 대신할 수 없다.

더 나쁜 것은 그 중간 상태다. **Ollama 서버는 로그인하지 않아도 뜬다.** 그래서
`is_available()`은 True인데 `:cloud` 모델을 부르면 실패하고, 라우터가 조용히
다음 프로바이더(유료 API)로 넘어간다. D-056에서 실제로 겪은 사고가 이것이다 —
무료로 도는 줄 알았는데 Gemini가 처리하고 있었다.

**결정**:

1. **`GET /api/llm/accounts` 신설.** 프로바이더마다 «닿는가(`reachable`)»와
   «인증됐는가(`authenticated`)»를 **따로** 판정하고, 넷 중 하나로 요약한다:
   `ready` / `needs_signin` / `needs_key` / `offline`.
   `/api/llm/status`는 «가용한가»만 주므로 이 구분을 담을 수 없다.
2. **못 쓰는 프로바이더는 무엇을 해야 하는지 함께 준다** (`setup_kind`, `setup_steps`).
   `env_key`는 키 발급 URL과 `.env` 변수명을, `cli_signin`은 터미널 명령을 그대로 적는다.
   앱이 대신 로그인할 수 없으므로 **화면에 명령이 있어야 한다.**
3. **Ollama의 로그인 계정을 조회한다** (`BaseLlmProvider.account_info()`).
   실측으로 `POST /api/me`가 이메일과 요금제를 준다는 것을 확인했다
   (GET은 405). 조회 수단이 없는 프로바이더는 `None`을 돌려준다 —
   **모르는 것을 안다고 하지 않는다.**
4. **과금 표시는 «실제로 쓸 모델» 기준으로 한다.** Ollama의 클래스 기본값은
   `free`(로컬)지만 이 PC가 실제로 고르는 비전 모델은 `qwen3.5:397b-cloud`다.
   클래스 값을 그대로 띄우면 «로컬 무료»로 보여 D-056의 오해가 재발한다.
   `_pick_vision_model()`을 물어 그 모델의 `billing_for_model()`을 쓴다.
5. **API 키는 응답에 싣지 않는다.** 화면은 «키가 있는가»만 알면 된다.

**곁다리로 고친 것**: `openai_oauth.is_available()`이 포트 10531~10540을
**직렬로** 훑어 프록시가 없으면 20.2초가 걸렸다(실측). 설정 화면이 그동안
멈추고, 이 프로바이더 하나 때문에 나머지 넷의 상태도 못 본다.
포트 스캔과 프로바이더 확인을 모두 `asyncio.gather`로 바꿔 **21.1초 → 2.2초**.

**근거**:

- 배포 시나리오에서 «왜 안 되는지»를 사용자가 스스로 알 수 있어야 한다.
  폴백이 조용히 다음으로 넘어가므로 화면에 표시가 없으면 원인을 알 방법이 없다.
- 이 저장소의 사용자는 비개발자 연구자다. «OAuth 프록시를 띄우세요»가 아니라
  칠 명령을 그대로 보여 줘야 한다.

**트레이드오프**:

- 채택: 상태 표시 + 명령 안내. 거부: 앱이 로그인을 대행 —
  `ollama signin`·`openai-oauth`는 브라우저 인증을 거치므로 앱이 자격증명을
  다루게 된다. 다루지 않는 것이 안전하다.
- 채택: 조회 수단이 없으면 `authenticated: null`. 거부: 추측으로 채우기.
- **남은 한도는 여전히 알 수 없다.** `/api/me`는 요금제만 주고 사용량·잔여
  한도가 없다(실측 2026-07-26: 응답 헤더에도 `X-RateLimit-*` 없음).
  D-056의 «제공자 대시보드로 안내» 결정은 그대로다.
- 브라우저 육안 확인을 못 했다(Chrome 확장 미연결). 실제 서버 응답 + jsdom으로
  렌더링을 검증했으나, D-055에서 jsdom이 놓친 CSS 결함 같은 것은 이 방법으로
  잡히지 않는다. 프론트 테스트 미결(D-053)이 여기서도 걸린다.

**검증**: `uv run python -m pytest` — **598 passed** (신규 12).
실제 확인: 이 PC에서 Ollama `ready`(hw725@g.skku.edu, pro, `qwen3.5:397b-cloud`
→ 구독 한도), OpenAI OAuth `offline`, Gemini·OpenAI `ready`(종량), Anthropic
`needs_key`. 응답에 API 키가 실리지 않는 것을 회귀 테스트로 고정했다.
설정 패널 렌더링은 실제 서버 응답을 jsdom에 태워 5행이 빈 칸 없이 그려지는 것을 확인.

**관련**: [D-056](#d-056-llm-사용-투명성--어느-모델로-얼마를-썼는지-보여-준다)의 연장이다.
D-056이 «쓰고 나서 얼마를 썼나»라면 이것은 «쓰기 전에 무엇으로 도는가»다.


---

## D-059: 설치 프로필 — 무엇에 쓰는지가 이름에 보이게

**날짜**: 2026-07-26

**맥락**: 「논문만 OCR 하려는 사람에게 전체 앱이 무겁고 복잡하지 않겠나」라는
물음에서 시작했다. 재 보니 **기본 설치는 이미 가벼웠다** — 무거운 것은 전부
extra였다(paddle 376.8MB, cv2 133.7MB, 그 전이 의존 165MB).

진짜 문제는 용량이 아니라 **안내**였다. README가
«오프라인 OCR 설치: `--extra ndlkotenocr` (고전적 전용, **권장**)»이라고 적어
두었는데, 그 엔진은 **한글을 인식하지 못한다.** 한글 논문을 하려는 사람이
안내를 따르면 170MB를 깔고 결과도 못 얻는다.
ndlocr / ndlkotenocr / ndlkotenocr-full이 나란히 있어 「오프라인 OCR」로
뭉뚱그려진 것이 원인이다.

**결정**:

1. **PaddleOCR를 기본 번들로 올린다** (약 377MB). 없으면 텍스트는 들어가되
   줄 위치를 몰라 왼쪽 여백에 균등 배치된다 — 검색은 되지만 형광이 글자 없는
   자리에 뜬다(실측: 502줄 중 433줄 제자리 → 0줄). «설치 안내를 따랐는데
   형광이 엉뚱한 곳에 뜬다»를 기본값으로 두지 않는다. 사용자 판단.
2. **extra 이름을 용도로 짓는다** — `japanese`(일본어 근현대) /
   `classical`(고서) / `classical-gpu`(고서 최고 품질).
   예전 이름은 별칭으로 남겨 기존 스크립트를 깨뜨리지 않는다.
3. **`requires-python`에 상한을 적는다** (`>=3.10,<3.13`).
   원인은 **paddlepaddle**이다 — paddleocr는 순수 파이썬에 `>=3.8`이라 3.13에서도
   설치된다. paddlepaddle이 컴파일 패키지인데 휠이 cp310·cp311·cp312까지만 있다
   (uv.lock 실측). 하한 3.10은 그대로 둔다 — 기본 의존성 **열 개**가 `>=3.10`을
   선언하므로 근거가 있다(fastapi·uvicorn·pymupdf·pillow·jsonschema·google-genai·
   regex·cssselect·fpdf2·python-multipart).
4. **CLI가 OCR 결과를 남기는 것을 기본으로 한다** (`--drop-workspace`로 지움).
   기존 기본값은 지우는 것이었는데, 그러면 «CLI로 빠르게 돌리고 이상하면 GUI로
   검수한다»는 흐름이 **성립하지 않는다.** 볼 것이 없어 OCR을 처음부터 다시
   돌려야 하고 쪽마다 LLM 호출이 다시 나간다.
5. **CLI 출력을 UTF-8로 고정한다.** 한국어 Windows의 cp949 콘솔에서
   `--help`가 `UnicodeEncodeError`로 **죽고 있었다**(실측). 안내문에 «—»가
   들어 있기 때문이다. 도움말을 볼 수 없으면 CLI를 쓸 수 없다.

**근거**:

- 앱을 둘로 나누지 않는다. 하나의 저장소에 **두 진입점**(CLI·GUI)이 있고
  CLI의 산출물이 곧 GUI의 입력이다. 4번이 없으면 그 연결이 끊긴다.
- 이름이 용도를 말하지 않으면 사용자는 문서를 읽어야 알 수 있고, 문서가
  틀리면 그대로 잘못 설치한다. `ndlkotenocr`보다 `classical`이 낫다.

**트레이드오프**:

- 기본 설치가 약 377MB 커진다. 대신 «형광이 엉뚱한 곳에 뜨는» 기본 상태가
  사라진다. 사용자가 용량보다 결과의 쓸모를 택했다.
- Python 3.13을 쓸 수 없다. paddlepaddle이 3.13 휠을 내면 상한을 풀 수 있다.
  이 제약은 원래도 `.python-version`으로 걸려 있었고, 메타데이터에 옮겨 적어
  실패 메시지를 알아볼 수 있게 만든 것이다.
- 작업 서고를 남기므로 디스크를 더 쓴다(실측 문헌당 약 29KB, 대부분 `.git`).
  63편이면 2MB 미만이라 검수 가능성과 바꿀 만하다.

**검증**: `uv run python -m pytest` — **605 passed** (신규 2).
`uv run python -m cli embed-folder X --help`가 정상 출력(이전에는 종료 코드 1로
죽었다). extras 재편 후 `tomllib`로 파싱 확인 — japanese·classical·classical-gpu와
예전 이름 3종이 모두 해석된다.
의존성 무게는 site-packages 실측: paddle 376.8MB, cv2 133.7MB, pymupdf 50.6MB,
pandas 40.6MB, onnxruntime 34.8MB.

**관련**: [D-057](#d-057-부분-재-ocr--레이아웃을-고친-쪽을-기계가-찾아낸다)의 쪽별 검수가
CLI 뒤에 이어지려면 4번이 필요하다.


---

## D-060: 논문 한 편의 경로 — 단계·메뉴·명령을 하나씩 줄인다

**날짜**: 2026-07-26

**맥락**: 추출 모드를 만들면서 탭은 줄였는데(D-055) 나머지는 그대로였다.
사용자가 셋을 짚었다 — 「사이드바 메뉴도 대부분 불필요하지 않나」,
「파일 첨부하면 두 단계씩 내려가야 되던데」, 「논문만 돌릴 사람에게
전체 앱이 무겁고 복잡하지 않겠나」.

**결정**:

1. **권이 하나뿐이면 트리에서 그 단계를 건너뛴다.** 문헌 → 권 → 쪽 구조는
   여러 권으로 나뉜 고서(蒙求 등) 때문에 필요하지만, 논문은 권이 언제나
   하나여서 그 단계가 **아무 정보도 주지 않으면서 클릭만 한 번 더 요구한다.**
   `manifest.parts`는 손대지 않는다 — 표시만 접는다.
   추출 모드 전용 규칙이 아니다. 단권 고서에도 그대로 이득이다.
2. **해석 저장소 전용 사이드바 패널 5종을 추출 모드에서 숨긴다** —
   검증 결과·의존 추적·엔티티·비고·인용 양식. 전부 해석 저장소를 읽거나
   (`interpretation.js`, `{interp_path}/_notes/`) 추출 모드에 없는 탭 전용이다
   (인용 양식 → 인용 탭). 탭과 같은 `data-profile="collation"` 표시를 붙여
   기존 로직이 그대로 처리하게 한다.
   **서고 브라우저·Git 이력·설정은 남긴다** — 셋 다 원본 저장소 쪽이다.
3. **한 줄 진입점 `cli ocr`을 만든다.** `embed-folder`는 「주제 폴더로 정리된
   수백 편」을 전제해 폴더 경로와 `--library`를 모두 요구한다. 한 편만
   처리하려는 사람에게는 그 전제가 전부 장벽이다.

       uv run python -m cli ocr 논문.pdf --execute

   파일 하나를 받아 임시 구조를 만들고, 서고는 `~/Documents/고전서지서고_추출`에
   알아서 잡고, 산출물을 **원본 옆에** `<이름>_text.pdf`로 놓는다.
   작업 서고는 남긴다 — 결과가 이상하면 GUI로 열어 검수해야 하기 때문이다(D-059).

**근거**:

- 앱을 둘로 나누지 않는다. 하나의 저장소에 두 진입점이 있고 CLI의 산출물이
  곧 GUI의 입력이다. 줄일 것은 **앱이 아니라 한 편을 처리하는 데 필요한
  동작 수**다.
- 사이드바 절은 재 보니 **10개 중 9개가 이미 조건부 숨김**이었다. 문제는
  「절이 다 떠 있다」가 아니라 눌러도 쓸모없는 버튼이 남아 있는 것이었다.
  실측하지 않았으면 없는 문제를 고칠 뻔했다.

**트레이드오프**:

- 단권 문헌에서 권 이름(`label`)이 화면에 나오지 않는다. 권이 하나면 그
  이름이 문헌 제목과 사실상 같으므로 잃는 정보가 없다고 봤다.
- 숨긴 패널을 보고 있다가 추출 모드로 바꾸면 서고 브라우저로 되돌린다.
  탭과 같은 처리다 — 안 하면 **돌아올 방법이 없는 화면에 갇힌다.**
- `cli ocr`은 파일을 임시 폴더로 복사한다. 원본을 아카이브로 「옮기는」
  단계가 원본을 건드리지 않게 하기 위해서다. 큰 PDF에서는 복사 비용이 든다.

**검증**: `uv run python -m pytest` — **605 passed**.
트리는 실제 구조로 jsdom 검증 8가지 — 단권은 권 노드 0개·쪽 15개가 한 번에
나오고 문헌 뱃지가 «15p»로 덮이지 않으며, 다권은 권 2개가 그대로 남고
권을 눌러야 쪽이 나온다.
사이드바는 **CSS를 주입해** `getComputedStyle().display === "none"`까지 확인했다
— D-055에서 `display: flex`가 `[hidden]`을 덮어쓴 전례가 있어 속성만 봐서는
부족하다.
`cli ocr`은 실제 논문으로 미리보기 실행 — 파일 하나를 받아 «15쪽, LLM 호출
예상 15회»를 보고하고 아무것도 바꾸지 않는다.

**관련**: [D-055](#d-055-추출-모드--작업-모드-분리--텍스트-레이어-산출물)가 탭에 쓴 방식을 사이드바로 넓힌다.
[D-059](#d-059-설치-프로필--무엇에-쓰는지가-이름에-보이게)가 작업 서고를 남기게 했으므로 `cli ocr` 뒤에 GUI 검수가 이어진다.


---

## D-061: 권 추가 — 문헌은 만든 뒤에도 자란다 (문헌 병합은 설계 필요)

**날짜**: 2026-07-26

**맥락**: D-060이 «권이 하나면 트리에서 그 단계를 접는다»로 가자, 사용자가
곧바로 되물었다 — 「그럼 반대로 단권에서 추가하거나 단권 두 개를 합치는
기능도 있어야겠지?」

재 보니 **둘 다 아예 없었다.** `parts`는 `add_document`와 `create-from-files`
**안에서만** 채워지고, 그 뒤에 손대는 API가 없다. 卷下를 뒤늦게 구하면
문헌을 지우고 처음부터 다시 만드는 수밖에 없었고, 그러면 이미 한 OCR·교정이
전부 사라진다. D-060이 이 문제를 만든 것은 아니지만 **더 드러나게 했다** —
단권 문헌에서 권 줄이 사라지면 «여기에 권을 더한다»는 자리 자체가 없어진다.

**결정 (①만 지금 한다)**:

1. **`POST /api/documents/{doc_id}/parts`** — 이미 있는 문헌에 PDF를 권으로
   더한다. 쪽 수는 열어서 세고, `part_id`는 스키마 패턴(`^[a-z][a-z0-9_]{0,31}$`)을
   지키며 문헌 안에서 유일한 다음 번호를 쓴다.
2. **PDF만 받는다.** 트리가 권을 PDF.js로 연다(`part.file`). 이미지 묶음을
   받으려면 `create-from-files`처럼 PDF로 합치는 처리가 필요한데 그것은 생성
   경로의 몫으로 두고, 여기서는 «이미 PDF인 것을 더한다»만 한다. 경계를 좁게
   두면 이 라우트가 생성 경로와 갈라질 여지가 줄어든다.
3. **같은 이름이 있으면 덮지 않고 `_2`를 붙인다.** 덮으면 앞선 권의 OCR
   결과가 가리키는 원본이 사라진다.
4. **저장 전에 manifest를 스키마로 검증하고, 실패하면 넣은 파일까지 되돌린다.**
   manifest가 깨지면 문헌이 통째로 열리지 않는다. 부분적으로 바뀐 상태를
   남기지 않는다.
5. **트리의 문헌 노드에 「＋」 버튼**(hover 시 노출, 삭제 버튼과 같은 방식).
   더하고 나면 트리를 다시 그리므로, 권이 2개가 되면서 D-060의 접힘이
   저절로 풀린다.

**미결 — ② 문헌 병합은 설계가 필요하다**:

따로 등록해 버린 卷上·卷下를 하나로 합치는 일이다. ①보다 훨씬 무겁고,
정하지 않은 것이 여럿이라 **지금 구현하지 않는다.**

- **쪽 번호가 겹친다.** 두 문헌 모두 L2/L3/L4가 1쪽부터 시작한다. 합치면
  뒤 문헌의 쪽을 밀어야 하는데, 그러면 이미 저장된 파일 이름
  (`{part_id}_page_NNN.json`)과 그것을 가리키는 참조를 전부 다시 써야 한다.
- **해석 저장소를 어떻게 할지 모른다.** 각각 붙어 있으면 둘을 합칠지, 하나를
  버릴지, 둘 다 남길지가 데이터 손실과 직결된다.
- **Git 이력 둘을 어떻게 할지 정해야 한다.** 한쪽을 정본으로 삼으면 다른 쪽의
  작업 이력이 끊긴다.
- **되돌릴 수 없다.** ①은 잘못 더해도 그 권만 빼면 되지만, 병합은 두 문헌의
  구조를 섞는다.

**언제 다시 볼 것인가**: 실제로 겹치는 사례가 생겼을 때, 그 데이터를 보고
설계한다. 지금 상상으로 정하면 실제 사례와 어긋날 가능성이 크다.
그때까지의 대안은 **애초에 여러 권짜리는 등록할 때 파일을 여러 개 넣는 것**이다
— `create-from-files`가 PDF마다 별도 권으로 잡는다.

**근거**:

- 「卷下를 뒤늦게 구했다」가 「이미 따로 등록해 버렸다」보다 훨씬 흔하다.
  흔한 쪽을 먼저 막는다.
- ①이 있으면 ②가 필요한 상황이 줄어든다 — 새로 등록하는 대신 더하면 된다.

**트레이드오프**:

- 이미지를 권으로 더할 수 없다. 새 문헌으로 만든 뒤 합쳐야 하는데 그 «합치기»가
  바로 미결인 ②다. 이미지 묶음을 뒤늦게 더하는 일이 실제로 생기면 그때 2번
  결정을 다시 본다.
- 권 이름을 `window.prompt`로 묻는다. 이 저장소의 다른 다이얼로그와 모양이
  다르지만, 파일 하나를 더하는 데 전용 다이얼로그를 만드는 것은 과하다.

**검증**: `uv run python -m pytest tests/test_add_part.py` — **8 passed**.
쪽 수 자동 인식, 이름 기본값, 같은 이름 충돌 회피, `part_id` 유일성·패턴,
PDF 아닌 것 거부, 없는 문헌 404, 추가 후 manifest 스키마 통과,
**기존 권의 OCR 결과와 원본이 그대로 남는 것**까지 고정했다.
실제 실행으로도 확인 — 蒙求(卷上 3쪽)에 卷下 5쪽을 더해 `vol2`가 붙었다.

**관련**: [D-060](#d-060-논문-한-편의-경로--단계메뉴명령을-하나씩-줄인다)이 접은 단계를 다시 펼 수 있게 한다.


---

## D-062: 폰트 임베드를 기본으로 — 검색되지 않는 한자를 남기지 않는다

**날짜**: 2026-07-26

**맥락**: Ollama로 한 편을 완주한 뒤 산출물을 대조하다 발견했다.
L2에는 있는 글자가 **PDF에서 사라져 있었다.**

```
L2 : 玄同 李安中研究     →  PDF: 玄同 李安中究
L2 : 勸郎合歡酒          →  PDF: 勸合歡酒
```

전수 집계(15쪽 논문): **51종 130자 누락.** `郎`(27회) `儂`(22회) `研`(16회) —
전부 한자이고 하필 **한시 인용문에 몰려 있었다.** Adobe-Korea1 charset에 없는
글자를 `insert_text(fontname="korea")`가 조용히 버린 것이다.

D-055는 이 방식을 «쪽당 +0.9KB, 추출·좌표검색 정상»으로 판단해 골랐다.
그 실측이 틀린 것이 아니라, **시험 텍스트가 우연히 Adobe-Korea1 안에
있었을 뿐**이다. 합성 데이터가 숨긴 결함이 하나 더 있었던 셈이다.

**결정**:

1. **`embed_font=True`를 기본값으로 한다.** 누락이 51종 130자 → **2종 2자**로
   줄고(남은 둘은 OCR이 잘못 읽은 한글 자모 조각이라 폰트 문제가 아니다),
   크기는 **쪽당 +4.9KB**다. 3,358쪽이면 +16MB.
2. **글자 크기를 «실제로 쓸 폰트»로 잰다.** `_fit_fontsize`가 항상 CID 폰트로
   재고 있어, 임베드하면 검색 형광 상자가 **26% 좁아졌다**(270pt 자리에 199pt).
   보이지 않는 텍스트라도 형광의 위치와 길이는 이 크기가 정한다.
3. **비임베드로도 끌 수 있게 남긴다.** 다만 그때는 위 손실을 감수하는 것임을
   docstring과 옵션 설명에 적는다.

**근거**:

- 산출물의 계약은 **«검색되는 PDF»**다(D-055). 연구자가 가장 찾고 싶어 할
  한자가 빠지면 그 계약이 깨진다. 0.9%(130/14,211자)라는 비율이 작아 보여도
  **손실이 균등하지 않다** — 평범한 한글 본문은 멀쩡하고 인용 한문만 빠진다.
- +16MB는 원본 스캔본(수백 MB) 옆에서 무시할 만하다.

**트레이드오프**:

- 파일이 5.4배 커진다(쪽당 0.9KB → 4.9KB). 원래 D-055가 피하려던 것인데,
  당시 계산의 대안은 **subset 없는 임베드(+1,663KB)** 였다. `subset_fonts()`를
  거친 실제 비용은 그보다 두 자릿수 작다.
- **이미 만든 산출물은 전부 이 결함을 갖고 있다.** 다시 만들어야 하지만
  OCR을 다시 돌릴 필요는 없다 — 입히기만 하면 되고 쪽당 1초 안쪽이다.

**검증**: `uv run python -m pytest` — **620 passed** (신규 3).
비임베드에서 **실제로 사라지는 것**까지 회귀로 고정했다
(`test_without_embedding_the_loss_is_real`) — 이 테스트가 깨지면 측정 전제가
달라진 것이므로 기본값 결정을 다시 봐야 한다.
실제 논문 재생성: 누락 51종 130자 → 2종 2자, 733KB,
`李安中研究` 5건 · `大東文化研究` 7건 · `勸郎合歡酒` 1건 · `儂不信` 1건 검색 성공
(고치기 전에는 0건).

**관련**: [D-055](#d-055-추출-모드--작업-모드-분리--텍스트-레이어-산출물)의 폰트 결정을 뒤집는다.


---

## D-063: 실사용에서 드러난 셋 — 없는 함수, 캐시, 겹치는 단위

**날짜**: 2026-07-26

**맥락**: 사용자가 실제로 써 보며 세 가지를 짚었다. 셋 다 자동 검증이
초록이었는데도 화면에서는 안 되던 것들이다.

**결정과 원인**:

1. **`goToPage`가 아예 없었다.** 추출 패널의 「대조」·「영역」·「다음 미확인
   쪽」이 전부 `typeof goToPage === "function"` 가드에 걸려 **조용히 아무
   일도 하지 않았다.** 오류도 콘솔 경고도 없었다.
   쪽 이동은 지금까지 **트리 노드를 클릭하는 것**으로만 됐다
   (`_selectPage`는 docInfo와 노드를 받는 비공개 함수다).
   → `sidebar-tree.js`에 `goToPage(pageNum)`를 만들었다. 노드가 있으면
   클릭해 기존 경로(저장 확인·프로필 전환·하이라이트·`onPageChanged`)를
   그대로 타고, 트리가 접혀 있으면 `_selectPage`를 직접 부른다.
   → 호출부의 «없으면 조용히 넘어가기»를 **화면에 알리기**로 바꿨다.
   가드가 결함을 숨기면 없는 것과 같다.
2. **레이아웃 탭이 늦게 반영됐다.** `loadPageLayout`만 `cache: "no-store"`
   없이 요청하고 있었다 — 저장소의 다른 8곳은 붙어 있고, **교정 탭은 세
   요청 모두 붙어 있다.** 그래서 «교정 탭은 바로 반영되는데 레이아웃만
   늦다»는 증상이 됐다. 배치 OCR이 L3 전면 블록을 새로 만들어도 브라우저가
   예전 응답을 그대로 줬다.
   → `no-store`를 붙이고, 배치 완료 시 텍스트와 함께 레이아웃도 다시 읽는다.
3. **«쪽»이 개수와 번호를 겸했다.** 쪽 범위를 비운 채 «실행하면 3쪽이 돕니다
   — 3쪽 미처리»가 뜨면 «3번 쪽»으로 읽힌다.
   → **개수는 「개」, 번호는 「쪽」**으로 갈랐다.
   «실행하면 쪽 3개가 돕니다 — 아직 안 함: 1, 2, 3쪽»

**함께 정한 것 (사용자 판단)**:

- **Git 이력을 추출 모드에서 숨긴다.** 확인해 보니 추출 흐름에서 원본 저장소에
  커밋되는 것은 문헌 등록·교정 저장·서지정보·권 추가뿐이고,
  **`L2_ocr/`·`L3_layout/`·`exports/`는 추적조차 되지 않는다**(untracked).
  즉 OCR 결과는 애초에 이력에 없다.
- **설정의 원격 저장소 절도 숨긴다.** Git 이력을 숨기는 것과 같은 이유다.
  추출은 산출물 PDF를 밖으로 내보내는 흐름이고, 저장소 동기화는 교감의 관심사다.
  → 추출 모드의 사이드바 아이콘은 **8개 중 2개**(서고 브라우저·설정)만 남는다.

**근거**:

- 셋 다 **자동 검증이 잡지 못한 것**이다. 특히 1번은 내가 검증에서 없는 함수를
  **가짜로 주입해** 통과시켰다. 스텁이 실제 계약과 어긋나면 테스트는 자기
  자신을 검증한다. 그래서 이번 검증은 **실제 `goToPage`를 그대로 실행**한다.
- 2번은 «교정 탭은 되는데 레이아웃만 늦다»는 사용자의 관찰이 원인을 곧바로
  좁혀 줬다. 두 화면의 차이가 `cache` 옵션 하나였다.

**트레이드오프**:

- 트리가 접힌 상태에서 `goToPage`를 쓰면 사이드바 하이라이트가 생기지 않는다.
  화면 이동은 정상이므로 기능은 성립하고, 하이라이트를 위해 트리를 강제로
  펼치는 것은 사용자가 접어 둔 뜻을 거스른다.
- Git 이력을 숨기면 추출 모드에서 교정 이력을 볼 수 없다. 교감 모드로 돌리면
  그대로 보이고, 데이터는 아무것도 지워지지 않는다.

**검증**: `uv run python -m pytest` — **620 passed**.
쪽 이동은 **실제 `goToPage`로** jsdom 검증 11가지 — 트리가 펼쳐졌을 때는
노드 클릭 경로를 타 하이라이트·`onPageChanged`까지 걸리고, 접혔을 때도
PDF 로드가 일어나며, 쪽 번호가 없으면 false를 준다.
사이드바는 CSS를 주입해 숨긴 6개와 원격 저장소 절의 computed display가
`none`인 것, 교감 모드로 돌아오면 8개가 다 보이는 것까지 확인했다.
문구는 6조합(범위 유무 × 강제 유무)을 다시 돌려 «개/쪽»이 섞이지 않는 것을 봤다.

**관련**: [D-060](#d-060-논문-한-편의-경로--단계메뉴명령을-하나씩-줄인다)의 사이드바 정리를 이어간다.
[D-057](#d-057-부분-재-ocr--레이아웃을-고친-쪽을-기계가-찾아낸다)의 「대조」·「다음 미확인 쪽」이 이 수정으로 비로소 동작한다.


---

## D-064: OCR 결과 되돌리기 + 아이콘 줄 접기

**날짜**: 2026-07-26

**맥락**: 두 가지가 이어서 나왔다.

첫째, **L2는 Git으로 추적되지 않는다**(D-063에서 확인). 모델을 바꾸거나
레이아웃을 고쳐 다시 돌리는 것이 추출 흐름의 일부인데(D-057), 결과가
이전만 못해도 돌아갈 길이 없었다. 그러면 «다시 돌려 보기»가 위험한 선택이 된다.

둘째, 추출 모드의 사이드바 아이콘이 둘만 남자(D-063) **줄 자체가 군더더기**가
됐다. 사이드바는 접을 수 있지만 **아이콘 줄은 접어도 남는다.**

**결정**:

1. **덮어쓰기 직전에 그 쪽의 작업 결과를 한 벌 남긴다** (`ocr/page_backup.py`).
   `<문헌>/.page_backup/{part}_page_NNN/` — 문헌 안에 두므로 옮기거나 지울 때
   함께 따라간다. **되돌아갈 수 있는 것은 직전 한 단계뿐이다** —
   백업은 덮어쓸 때마다 새로 뜨므로 `A → B → C`에서 되돌리면 **B**로 가고
   A는 이미 사라졌다. «맨 처음 OCR로 되돌리기»가 아니다.
   Git으로 이력을 다 남기지 않는 이유: L2는 쪽마다 수십~수백 KB이고 돌릴
   때마다 통째로 바뀐다. 실제로 필요한 상황은 «방금 돌린 게 이전만 못하다»이고
   그건 한 단계로 해결된다.
1-1. **L2만이 아니라 L4까지 남긴다.** 처음에는 OCR 결과만 남겼는데,
   배치는 `fill_text_layer`로 **L4 교정 텍스트도 덮어쓴다**(교정 탭이 L4를
   읽으므로 채워 줘야 한다). 즉 **손으로 고친 교정이 재실행 때 사라졌다.**
   당시 코드 주석에 «사람이 고친 교정은 안전하다»고 적어 두었는데 사실이
   아니었다. L2만 되돌리면 «OCR은 예전 것인데 교정은 사라진» 어긋난 상태가
   되므로, `L2_ocr` · `L4_text/pages` · `L4_text/corrections` 셋을 함께 다룬다.
   백업 시점에 없던 파일은 되돌릴 때 **지운다** — 안 그러면 «그때 없던 교정»이
   되살아난다.
2. **되돌리기는 자리를 바꾼다** (`POST .../ocr/restore?pages=3`).
   되돌린 뒤 백업을 지우지 않고 현재 결과를 그 자리에 넣는다 —
   **두 상태를 오갈 수 있다.** 어느 쪽이 나은지 비교하다 돌아올 수 있어야 한다.
3. **빈 결과는 백업하지 않는다.** «돌았는데 아무것도 못 읽은» 쪽으로 되돌릴
   이유가 없고, 남기면 되돌리기 버튼이 쓸모없는 곳에도 뜬다.
4. **아이콘 줄을 접을 수 있게 한다.** 폭을 `--activity-width` 변수로 묶어
   CSS와 JS가 한 곳을 보게 하고(전에는 세 곳에 `48px`이 박혀 있었다),
   접으면 `0px` + `display: none`이 된다.
5. **토글은 모드 바 왼쪽 끝에 둔다.** 줄을 접으면 그 안의 버튼으로는 되돌릴
   수 없다. **되돌릴 수단은 줄 밖에, 항상 보이는 자리에** 있어야 한다.
6. **펼 때는 서고 브라우저로 맞춘다.** 줄을 펴는 행동은 대개 «문헌을 보러
   간다»는 뜻이고 설정은 어쩌다 한 번 쓴다. 접기 직전에 설정을 보고 있었다는
   이유로 다시 설정이 열리면 한 번 더 눌러야 한다.

**근거**:

- 사용자 표현 그대로다 — «그냥 로컬에다가 json으로 백업해두는 편이 심플».
  Git에 넣으면 저장소가 부풀고, 정작 필요한 것은 직전 한 단계뿐이다.
- 아이콘 줄은 «접을 수 없는 것»이 아니라 «접을 이유가 없던 것»이었다.
  아이콘이 여덟일 때는 줄이 정보였고, 둘이 되니 여백이 됐다.

**트레이드오프**:

- 백업이 문헌마다 L2 한 벌만큼 디스크를 더 쓴다(쪽당 수십~수백 KB).
  `backup_before_overwrite: false`로 끌 수 있다.
- 되돌리기는 **한 단계**뿐이다. 세 번 돌려 보고 첫 번째로 가고 싶으면
  방법이 없다. 이력을 다 남기는 비용과 바꿨다.
  **설명에서 이 점을 흐리면 안 된다** — «한 세대만 남긴다»는 표현은
  «맨 처음 것을 남긴다»로 읽힌다. 화면·문서·docstring 모두 «바로 직전»이라고
  적고, `A → B → C → 되돌리기 = B` 예를 함께 둔다.
- 아이콘 줄 접기는 교감 모드에서도 동작한다. 추출 모드 전용으로 막지 않은
  이유는, 아이콘이 여덟이어도 «지금은 넓게 보고 싶다»가 있을 수 있어서다.

**검증**: `uv run python -m pytest` — **633 passed** (신규 13).
백업은 되돌리기·자리바꿈·**직전 한 단계만 유지**(A→B→C에서 B로 감)·빈 결과 제외·백업 없을 때 False,
그리고 **손으로 고친 교정이 함께 되돌아오는 것**과 «백업 시점에 없던 파일은
되돌릴 때 사라지는 것»까지 고정했다.
화면은 되돌릴 수 있는 쪽에만 버튼이 뜨고, 누르면 `?pages=2`로 요청하며,
쪽 범위를 건드리지 않는 것(stopPropagation)을 확인했다. 라우트는 배치 2회 실행 후 `has_backup`이 False → True로 바뀌고
되돌리기가 `{"restored": [1]}`을 주는 것을 확인했다.
아이콘 줄은 CSS를 주입해 접었을 때 `display: none`·폭 변수 `0px`,
**토글이 줄 밖에 있어 접힌 상태에서도 눌리는 것**, 펼 때 서고 브라우저로
전환되는 것, 상태가 다음 실행에 유지되는 것까지 12가지를 확인했다.

**관련**: [D-063](#d-063-실사용에서-드러난-셋--없는-함수-캐시-겹치는-단위)에서 «L2가 이력 밖에 있다»고 적은 것에 답한다.


---

## D-065: 되돌리기의 자리 — 「새 OCR이 더 나쁠 때」 하나

**날짜**: 2026-07-26

**맥락**: D-064에서 쪽 되돌리기를 만들고 나서 설명이 계속 꼬였다. 사용자가
같은 것을 여섯 번 다시 물었고, 그때마다 답이 달라 보였다. 원인은 기능이
아니라 **내가 규칙을 두 개로 만들어 놓고 하나처럼 설명한 것**이었다.

**결정**:

1. **백업은 OCR 재실행 때만 뜬다.** 교정 저장에는 두지 않는다.
   한때 «저장할 때마다»로 넓혔다가 되돌렸다 — 교정을 되돌리는 수단은
   교정 탭에 **이미 있고 더 낫다**: 항목별 삭제(고친 글자 하나만)와
   「모두 삭제」(그 쪽 교정 전부). 교정 기록은 «어느 글자를 무엇으로»의
   목록이라 **차수 제한이 없다.** 그 위에 쪽 통째 1단계 스냅샷을 얹으면
   성능은 더 낮으면서 개념만 늘어난다.
2. **용도를 이름과 안내에 박는다.** 버튼은 「OCR 되돌리기」이고,
   **새로 돌린 결과가 이전만 못할 때** 쓴다. 그 하나뿐이다.
3. **「직전 교정을 새 결과에 자동 재적용」은 하지 않는다.**

**왜 재적용을 하지 않는가** (사용자가 제기하고 사용자가 반박한 안):

   같은 글자는 또 잘못 읽힐 확률이 높으니 교정을 다시 적용하는 것이
   이상적으로 보인다. 교정 항목이 `original_ocr → corrected` 형태라
   위치와 무관하게 적용할 수도 있다. 그러나 세 가지로 깨진다.

   - 새 OCR이 **다르게** 틀리면 기록과 안 맞아 재적용이 안 된다
   - 새 OCR이 **맞게** 읽었으면 규칙만 남는다
   - **맞게 읽힌 글자까지 바꾼다** — `1 → 一` 규칙이 본문의 `1998`을 망친다

   이체자 사전 일괄 교정이 안전한 것은 **사람이 고른 대응표를 의도적으로**
   적용하기 때문이다. 한 쪽의 임시 교정을 자동 재생하는 것과는 다르다.
   지금의 «덮어쓰기»는 게으른 선택이 아니라 **보수적인 선택**이다.

**근거**:

- 도구가 하나의 문장으로 설명되지 않으면 그 도구는 잘못 놓인 것이다.
  「방금 한 것 취소」로 만들려다 조건이 붙었고, 「새 OCR이 나쁠 때」로
  좁히니 한 문장이 됐다.
- 이미 있는 수단(교정 목록)보다 못한 것을 새로 얹지 않는다.

**트레이드오프**:

- 교정을 두 번 저장하면 첫 저장 이전으로는 갈 수 없다. 그건 교정 목록의
  일이고, 되돌리기가 감당할 범위가 아니다.
- 재실행 뒤 교정을 다시 하는 수고는 남는다. 자동 재적용의 위험보다 낫다고 봤다.

**검증**: `uv run python -m pytest` — **633 passed**.
실측으로 핵심 흐름을 확인했다 — 1차 OCR 후 교정 → 재실행(교정 덮임) →
되돌리기 → **교정이 돌아온다.**

**관련**: [D-064](#d-064-ocr-결과-되돌리기--아이콘-줄-접기)의 범위를 좁힌다.


---

## D-066: 전체 점검 — API 응답에 캐시 금지를 서버가 붙인다

**날짜**: 2026-07-26

**맥락**: 유틸리티 전체를 훑어 이번 세션에 드러난 결함 부류가 더 남아 있는지
확인했다. 네 가지를 기계적으로 검사했다.

| 검사 | 결과 |
|---|---|
| 정의 없이 `typeof X === "function"`으로 부르는 함수 | **0건** (오탐 1건은 매개변수) |
| 프론트 API 호출 ↔ 백엔드 라우트 짝 (172 ↔ 180) | **0건** (오탐 22건은 정규식이 템플릿·쿼리를 자른 것) |
| 프론트가 읽는 응답 키 ↔ 백엔드가 내보내는 키 | **0건** (오탐 17건은 요청 본문·localStorage·프론트 자체 값) |
| 변하는 데이터를 캐시 지정 없이 읽는 GET | **47건** ← 실제 문제 |

**결정**:

1. **API 응답에 `Cache-Control: no-store`를 붙이는 미들웨어를 둔다.**
   API가 돌려주는 것은 작업 중에 바뀌는 데이터다(OCR 결과·레이아웃·교정·
   진행 상황). 헤더가 없으면 브라우저가 캐시 기간을 스스로 추정한다.
2. **호출부 47곳을 고치지 않는다.** 한 곳씩 붙이면 새로 쓰는 코드에서 또
   빠진다. 서버가 한 번 붙이면 그 부류가 통째로 사라진다.
3. **정적 파일은 `no-cache`를 유지한다.** 내용이 그대로면 304로 끝나
   본문 전송이 없다. API는 매번 달라지는 것이 정상이라 재검증할 값이 없다.
4. 추출 모드에서 **「OCR 채우기」 버튼을 숨긴다.** 배치가 L4를 이미 채워
   두므로 눌러도 같은 값을 다시 넣을 뿐이고, 손으로 고친 교정이 있으면 덮는다.

**근거**:

- D-063에서 레이아웃 탭이 늦게 반영되던 것이 정확히 이 부류였고,
  당시에는 그 한 곳만 고쳤다. 점검해 보니 같은 모양이 46곳 더 있었다.
  **한 곳을 고치고 끝냈으면 나머지는 사고가 날 때까지 남아 있었을 것이다.**
- 오탐이 39건 나온 것도 기록해 둔다. 자동 검사는 «없다»를 증명하지 못하고
  «볼 곳»만 좁혀 준다 — 39건은 사람이 하나씩 확인해 걸러냈다.

**트레이드오프**:

- 모든 API 응답에 헤더가 붙어 조건부 요청(304)의 이득을 포기한다.
  로컬에서 도는 앱이라 왕복 비용이 무시할 수준이고, «고쳤는데 반영이
  안 된다»가 사라지는 값이 더 크다.

**검증**: `uv run python -m pytest` — **639 passed** (신규 6).
`/api/*`가 성공이든 실패(500)든 `no-store`를 돌려주는 것, 정적 파일은
`no-cache`를 유지하는 것, API가 아닌 경로는 손대지 않는 것을 고정했다.
`ruff check src/ tests/` 전부 통과(세션 내내 남아 있던 기존 2건 포함 정리),
JS 29개 파일 문법 검사 통과.

**관련**: [D-063](#d-063-실사용에서-드러난-셋--없는-함수-캐시-겹치는-단위)에서 한 곳만 고쳤던 것을 전체로 넓힌다.

---

## D-067: 레이아웃은 열면 이미 잡혀 있다 — 좌표는 환산하고, 저장은 앱이 한다

**날짜**: 2026-07-26

**맥락**: 배치 OCR을 돌린 뒤 레이아웃 탭을 열면 블록이 보이지 않았다.
저장 버튼을 누르면 그제야 나타났다. 실제 서고를 열어 보니 원인이 둘이었다.

| 쪽 | `image_width` | 만든 주체 |
|---|---|---|
| 1쪽 | 495 | 사람이 화면에서 저장 |
| 2~15쪽 | **991** | 배치 OCR(`ensure_full_page_block`, 2배 렌더) |

L3의 bbox는 «렌더된 페이지 이미지의 픽셀» 좌표인데, **몇 배로 렌더했는지가
만든 주체마다 달랐다.** 화면은 언제나 PDF 뷰포트(1배) 기준이라 991짜리 블록이
두 배 크기로 그려져 캔버스 밖으로 나갔다. 프론트는 이 차이를 만나면 bbox를
**통째로 고쳐 쓰고** `isDirty = true`로 표시했다 — 그래서 쪽마다 저장이 필요했다.

**결정**:

1. **데이터를 고치지 않고 그릴 때만 환산한다.** `_layoutScale() =
   뷰포트폭 / L3 image_width`를 두고 `_imageToCanvas`·`_canvasToImage`가
   함께 쓴다. L3는 자기 좌표계를 그대로 지킨다.
2. **블록이 0개인 쪽을 열면 「페이지 전면 1블록」을 만들어 곧바로 저장한다.**
   추출 모드만이 아니라 **교감 모드에서도** 그렇게 한다. 쓰기 방향만
   프로필로 가른다(논문 `horizontal_ltr` / 고서 `vertical_rtl`).
3. 블록이 **이미 있으면 절대 건드리지 않는다.** 자동 생성은 0개일 때만이다.

**근거**:

- 좌표계를 고쳐 쓰는 방식은 **L2와의 정합을 깬다.** L2의 줄 bbox는 파이프라인이
  실제 렌더 크기로 저장하고, 텍스트 레이어 PDF는 배율을 `L3 image_width /
  페이지 폭`으로 구한다(`text_layer_pdf._render_scale`). L3만 1배로 다시 쓰면
  좌표를 주는 엔진(Paddle·NDL)에서 글자가 두 배 어긋난 자리에 박힌다.
  **환산해서 그리기만 하면 어느 배율이든 정합이 유지된다.**
- 전면 블록 자동 저장은 D-004가 승인한 경로 B(레이아웃을 먼저 확정하고 OCR)의
  기본값을 앱이 대신 깔아 주는 것이다. 「쪽 전체가 본문」은 논문이든 고서든
  가장 흔한 출발점이고, 300쪽짜리에서 사람이 사각형을 그리고 저장을 누르면
  600동작이 된다. 이상하면 그때 고친다.

**트레이드오프**:

- 교감 모드에서 레이아웃 탭을 **열기만 해도** L3 파일이 생긴다. 되돌리기
  어려운 변화는 아니지만(블록 1개, git 커밋 없음), «만진 적 없는데 파일이
  생겼다»는 놀람은 남는다. 사람이 그린 블록을 덮을 위험은 없다 — 0개일 때만이다.
- 이번 변경은 **프론트 전용**이라 pytest가 지키지 못한다. jsdom으로 좌표 환산과
  자동 저장을 검증했지만 정식 테스트로 승격하지는 않았다(D-053의 프론트 스모크
  테스트 부채가 그대로 남는다).

**검증**: `uv run python -m pytest` — **639 passed**(회귀 없음).
jsdom 13항목: 2배 L3(991)·1배 L3(495) 모두 블록이 캔버스(743×1041)에 오차 2px
안으로 꼭 맞게 그려지는 것, 그 과정에서 `isDirty`가 서지 않는 것,
`image_width`가 991로 유지되는 것, 블록 0개일 때만 PUT이 한 번 나가고
쓰기 방향이 프로필대로 갈리는 것을 고정했다.

**함께 고친 것**: 추출 패널이 `flex-shrink: 0`이라 부모(`overflow: hidden`)보다
길어지면 아래가 잘렸다 — 「쪽별 검수」를 펼치면 목록 끝과 「검색되는 PDF 만들기」
절이 통째로 보이지 않았다. 높이를 55%로 묶고 패널 안에서 스크롤시킨다.

**관련**: [D-055](#d-055)의 전면 블록 생성을 화면 쪽으로 넓힌다.
[D-053](#d-053)의 프론트 테스트 부채가 여전히 유효하다.

---

## D-068: 산출물은 다시 열어 재야 한다 — 텍스트 레이어가 0.24배로 박혔다

**날짜**: 2026-07-26

**맥락**: 내려받은 텍스트 레이어 PDF에서 드래그가 전혀 되지 않는다는 신고.
파일을 열어 재 보니 텍스트는 **있었다** — 495×694pt 쪽의 왼쪽 아래 구석에,
2.0~2.9pt 크기로.

| | 넣으려던 값 | 실제로 들어간 값 |
|---|---|---|
| 가로 위치 | 40pt | **9.6pt** |
| 글자 크기 | 12pt | **2.88pt** |
| 텍스트가 덮은 넓이 | 쪽의 약 60% | **쪽의 4%** |

두 값 모두 정확히 **0.24배**다. 원본 스캔 PDF의 내용 스트림이 이렇게 시작한다.

```
0.24 0 0 0.24 0 0 cm      ← q 밖에 있고, 되돌리는 Q도 없다
q 2064 0 0 2893 0 0 cm /I0 Do Q
```

스캐너가 2064×2893 픽셀을 495×694pt 종이에 맞추려고 적어 둔 배율이다
(495.36 ÷ 2064 = 0.24). 그 `cm`이 `q…Q` 밖에 있어 **그 뒤에 덧붙이는 모든
것이 0.24배로 줄어든다.** OCR도, 좌표 계산도, 배율 환산도 전부 맞았다.
마지막 «PDF에 써넣기» 한 단계에서만 끌려갔다.

**왜 이제야 드러났나**: `page.insert_text()`는 자기 출력을 `q…Q`로 감싸므로
이 영향을 받지 않는다. **폰트 임베드를 기본으로 바꾸면서(D-062)
`TextWriter` 경로로 갈아탔는데, `TextWriter.write_text()`는 감싸지 않는다.**

**왜 테스트가 못 잡았나**: `tests/test_text_layer_pdf.py`의 시험용 PDF를
**PyMuPDF로 만들었다.** 깨끗한 스트림이라 이 상황이 아예 생기지 않는다.
18개 시험이 전부 초록이었고, D-055는 «좌표 오차 0.2pt»라고, D-062는
«한자 소실 2자»라고 보고했다. 전부 **합성 PDF에서만** 참인 값이었다.

**결정**:

1. **`page.wrap_contents()`로 원본이 남긴 좌표 변환을 끊는다.** 기존 스트림을
   `q…Q`로 감싸 그 안에서 끝나게 한다. 원본 파일은 건드리지 않는다 —
   메모리에 연 사본에만 적용되고, `L1_source/`는 그대로다.
2. **산출물을 다시 열어 잰다**(`_audit_output`). 쪽마다 ①글자 크기 ②텍스트가
   덮은 넓이를 보고, 표본 3쪽은 ③**그 자리에 잉크가 있는지**까지 잰다.
   이상이 있으면 `warnings`에 실려 화면에 **남는다**(토스트가 아니다).
3. **시험용 PDF에 «되돌리지 않은 변환»을 가진 것을 추가한다.** 실제 논문의
   스트림 모양을 그대로 본떴다.

**근거**:

- 「제자리 502줄」 같은 숫자는 **시도의 기록이지 결과가 아니다.** 이번에
  로그도 API 응답도 «30줄 제자리»라고 말했고, 그것은 사실이었다 —
  그 30줄이 어디에 얼마만 하게 놓였는지는 아무도 재지 않았을 뿐이다.
  원본이 이미지뿐인 이상, 확인할 길은 **결과물의 잉크를 재는 것**밖에 없다.
- 실측(박준원 2001, 15쪽): 고친 뒤 글자 7.4~32.6pt, 쪽의 62%를 덮고,
  텍스트가 놓인 자리의 잉크 밀도가 쪽 평균의 **2.7~4.8배**. 고침을 빼면
  0.7배로 떨어지고 검사기가 잡아낸다(양방향 확인).

**트레이드오프**:

- 산출물을 한 번 더 열고 표본 3쪽을 렌더한다. 15쪽에서 1초 미만이고,
  300쪽이어도 표본은 3쪽으로 고정이라 늘지 않는다.
- 잉크 검사는 **좌표를 얻은 쪽에만** 건다. 좌표가 없어 순서대로 늘어놓은
  쪽은 원래 글자 위가 아니므로(이미 알린다) 거짓 경보가 된다.

**되돌릴 수 없는 결과**: **이 고침 이전에 만든 텍스트 레이어 PDF는 전부
쓸 수 없다.** 서고 4개를 훑어 확인했고(최소 글자 1.2~1.8pt) 다시 만들었다.
사용자가 이미 내보낸 파일이 있다면 그것도 다시 만들어야 한다.

**관련**: [D-062](#d-062)의 폰트 임베드 전환이 이 결함을 들여왔다.
[D-053](#d-053)의 «프론트·실물 검증 부채»가 백엔드에도 있었음이 드러났다 —
합성 입력만으로는 파일 형식을 다루는 코드를 지킬 수 없다.

---

## D-069: 릴리스 전 전수 감사 — 조용히 틀리던 넷과 죽은 코드 1,000줄

**날짜**: 2026-07-26

**맥락**: v1.2.0 직전에 저장소 전체를 훑었다. 프론트 27,257줄·백엔드 111개
모듈을 정적 분석 + 정독으로 봤고, **오류를 내지 않고 조용히 틀리는** 부류를
찾는 데 집중했다. D-068이 정확히 그 부류였기 때문이다.

**결정 1 — 다권본에서 엉뚱한 권을 읽던 것을 고친다.**

세 곳(`image_utils.py` · `pipeline.py` · `llm_ocr.py`)이 `L1_source/*.pdf`를
glob 해서 **첫 번째**를 썼다. glob은 순서를 보장하지 않을뿐더러 **part_id를
아예 보지 않았다.** 卷下 5쪽을 OCR 하면 卷上 5쪽 이미지가 엔진에 넘어가고,
오류 없이 그럴듯한 결과가 저장된다. **원본과 텍스트의 대응이 조용히
끊어지는 것**이라 이 저장소가 지키려는 것을 정면으로 때린다.

`resolve_part_pdf(doc_path, part_id)` 하나로 모았다 — manifest가 정본이고,
못 읽을 때만 **이름 순서**로 물러난다. D-061(권 추가)로 다권본이 정상
기능이 된 뒤로 실제 사고 가능성이 열려 있었다.

**결정 2 — 사용자가 고른 LLM 모델이 무시되던 것을 고친다.**

L7 주석 AI 보조 4개 경로가 `llm_router.force_provider = ...`로 **라우터
객체에 속성을 대입**했다. `LlmRouter`에 그런 속성이 없다. 화면에서
«Claude로 돌려라»를 골라도 기본 폴백 순서대로 돌았고, 오류가 나지 않아
알 길이 없었다. `router.call(..., force_provider=...)` 인자로 바꿨다.

**결정 3 — JSON 저장을 원자적으로 한다.**

`Path.write_text()`는 **먼저 파일을 0바이트로 자르고** 쓴다. 그 사이에
정전·강제종료가 나면 `manifest.json`이 빈 파일이 되고 그 문헌은 통째로
열리지 않는다. 커밋 이전이면 되돌릴 길도 없다. `write_json_atomic()`
(임시 파일 → `fsync` → `os.replace`)을 정본으로 두고, 다섯 모듈에
복제돼 있던 `_write_json`이 전부 그것을 부르게 했다.

**결정 4 — 신뢰 경계 밖 문자열을 이스케이프한다.**

이 저장소에는 이스케이프 헬퍼가 이미 13개 있었다. 적용이 빠진 것이다.
가장 뚜렷한 경로: **드롭한 파일명 → 문헌 제목 → 사이드바 `innerHTML`**
(`documents.py:836` → `sidebar-tree.js`). `<img src=x onerror=…>.pdf`라는
이름의 파일을 끌어다 놓으면 스크립트가 돈다. OCR 원문·외부 사전 임포트도
같은 경계 밖이다. 12곳에 적용했다.

**결정 5 — 죽은 코드를 걷어낸다 (약 1,000줄).**

전부 «마크업이 사라졌는데 JS는 null 가드로 조용히 넘어간» 같은 패턴이었다.

| 무엇 | 규모 | 왜 죽었나 |
|---|---|---|
| 해석 저장소 「비교 모드」 | 약 880줄 + CSS 150줄 | DOM id 8개가 index.html에 **하나도 없다** |
| 「L5 종류: ○표점 ○현토」 라디오 | 마크업 + 상태 | 고른 값을 읽는 곳이 비교 모드뿐이었다 — **눌러도 아무 일도 안 일어났다** |
| `_renderVariantList` | 30줄 + CSS | 이체자 관리가 전용 탭으로 옮겨 가며 자리가 사라졌다 |
| `initPanelToggle` · `setupRowResize` | 30줄 | 하단 패널이 사이드바로 옮겨 갔다 |
| `_resolveAiAnnotationRange` · `PdfSeparateRequest` · 도달 불가 `return` 1줄 | — | 리팩터링 잔재 |

`hwp-import.js`(1,035줄)는 **남긴다.** D-037로 봉인된 것이고 AGENTS.md가
«재구현하지 말고 복원할 것»이라고 명시한다 — 죽은 코드가 아니라 잠긴 기능이다.

**근거**:

- 다섯 가지 모두 **자동 테스트가 초록인 채로** 살아 있었다. 테스트는
  단권 문헌·더미 엔진·합성 PDF·성공 경로만 본다. D-068과 같은 구조다.
- 죽은 참조 17건이 전부 `if (!x) return`으로 감싸여 있었다. 예외가 나지
  않으니 «되지 않는다»가 «없다»처럼 보였다. 개발 중에는 `getElementById`
  실패를 경고로 남기는 편이 이 계열을 즉시 드러낸다(후속 과제).

**트레이드오프**:

- 「L5 종류」 라디오는 **화면에서 사라진다.** 실제로는 아무 동작도 하지
  않던 것이라 기능 손실은 없지만, 눈에 보이던 것이 없어진다.
  표점·현토는 상단 작업 탭으로 각각 들어간다.
- 「비교 모드」 880줄을 되살리려면 마크업부터 다시 만들어야 한다.
  삭제 지점마다 «무엇이 있었고 되살리려면 어떻게 하는지» 주석을 남겼다.

**검증**: `uv run python -m pytest` — **655 passed**(신규 10:
다권본 5 + 원자적 쓰기 5). ruff·JS 문법 29개 통과. 임포트 107개 전수 성공
(선택적 의존성 3개 제외). 죽은 참조 17건 → **1건 → 0건**.
XSS는 jsdom으로 실제 페이로드 4종을 넣어 «실행되지 않고 글자로만 보이는 것»을
확인했다(대조군으로 이스케이프 없으면 실제로 `<img>`가 생기는 것도 함께 고정).
다권본은 卷上·卷下 2권을 만들어 **같은 쪽 번호의 이미지가 서로 다른 것**을
직접 확인했다 — 자동 테스트가 못 잡는 자리라 실물로 봐야 한다.
서버를 띄워 화면·정적 파일·API 7종이 200으로 응답하는 것까지 확인했다.

**관련**: [D-068](#d-068)과 같은 부류를 찾으려고 시작한 감사다.
[D-061](#d-061)의 권 추가가 결정 1의 위험을 실제로 열어 두고 있었다.

---

## D-070: 설치는 두 갈래, 엔진 이름은 NDL 그대로

**날짜**: 2026-07-26

**맥락**: README의 빠른 시작이 「저장소 통째로 내려받기」와 「기본 설치만으로
전부 됩니다」를 나란히 적어 두어, 읽는 사람이 **설치가 가벼운 줄로** 읽었다.
실측하면 표준 설치는 **약 828MB**다(paddle 377 · cv2 121 · pymupdf 51 · 나머지).

**결정 1 — 「가벼운 설치」는 두지 않는다.**

PaddleOCR를 빼는 경로는 D-055가 기본 번들로 못박은 것을 정확히 빼는 것이다.
게다가 OCR·PDF를 제외한 나머지 전부가 127MB라 무엇을 빼도 828MB 중 2%다.
갈림길은 기본 설치 안이 아니라 **기본(828MB)과 고서 GPU(+4.5GB)** 사이에 있다.

**결정 2 — 설치 규모와 쓰는 방식을 분리해 안내한다.**

「CLI는 가볍고 앱은 무겁다」는 오해가 있었다. 사실이 아니다 — `ctb` 명령과
웹 앱은 **같은 패키지, 같은 의존성**을 쓴다. 갈리는 것은 설치 규모(표준/가벼운)와
쓰는 방식(명령 한 줄/앱)이고, **둘은 서로 독립**이다. 빠른 시작을
1단계 내려받기 → 2단계 설치(두 갈래) → 3단계 쓰기(두 방식)로 나눴다.

**결정 3 — 오프라인 엔진은 NDL 이름을 앞세운다.**

extra 이름은 용도(`japanese`·`classical`·`classical-gpu`)로 두되, 문서에서는
**NDLOCR-Lite · NDL古典籍OCR-Lite · NDL古典籍OCR Full**을 엔진 이름으로 먼저 쓴다.

- 용도 이름을 붙인 이유(한글 논문에 고전적 전용 엔진을 설치하는 사고)는 그대로 유효하다.
- 그러나 세 엔진은 **일본 국립국회도서관이 CC BY 4.0으로 공개한 것**이고,
  출처 표기는 라이선스 의무다. 이름에서 NDL을 지우면 그 사실이 사라진다.
- 둘 다 적으면 된다 — 무엇에 쓰는지(extra 이름)와 무엇인지(엔진 이름).

**결정 4 — 비교 모드 백엔드를 걷어낸다.**

D-069에서 프론트 880줄을 지우고 백엔드는 「태그와 어긋나지 않게」 두었는데,
그 유예가 곧 잊혀질 부채다. `reading.py`의 `l5_compare`·`l5_compare_at_commit`
두 라우트와 `core.interpretation.get_l5_compare_at_commit()`을 지웠다(**301줄**).
라우트 185 → **183개**. 부르는 곳은 0이었다.

**트레이드오프**:

- 가벼운 설치는 `uv`의 `--no-install-package`에 기대므로 다른 설치 도구를
  쓰면 그대로 옮겨지지 않는다. 대상 사용자가 uv를 쓰는 것이 전제다.
- 828MB는 **개발 의존(pytest·ruff) 포함 실측**이다. 사용자 설치는 조금 더 작다.
- 비교 모드를 되살리려면 백엔드도 다시 써야 한다. 지운 자리에 주석을 남기지
  않았다 — 커밋과 이 카드가 기록이다.

**검증**: `uv run python -m pytest` — **655 passed**(라우트 삭제 후에도 동일).
ruff 통과. 서버를 띄워 화면·정적·API 4종 200 응답, 지운 `l5_compare`가 **404**를
돌려주는 것까지 확인. 용량은 `.venv/Lib/site-packages` 실측
(paddle 376.8MB · cv2 121MB · pymupdf 50.6MB · 전체 828.1MB).

**관련**: [D-055](#d-055)가 paddle을 기본으로 올린 근거는 유지한다.
[D-059](#d-059)의 extra 재편에 NDL 이름을 되살린다.
[D-069](#d-069)가 미룬 백엔드 정리를 끝낸다.

---

## D-071: 표점 컨테이너를 누구나 만들 수 있게 — 그리고 설치 용량을 실측으로

**날짜**: 2026-07-26

**맥락**: 「설치가 무겁다」의 실체를 실물로 재고서야 무엇이 무거운지,
무엇이 문제인지가 갈렸다.

| 무엇 | 문서 기재 | 실측 | 출처 |
|---|---|---|---|
| 기본 `uv sync` | 없었음 | **828MB** | 이 저장소 `.venv` |
| `--extra classical-gpu` | **약 340MB** | **약 4.5GB** | Windows torch 2.6+cu124 실측 |
| 표점 Docker | 없었음 | 본체와 무관 | 외부 모델·별도 서비스 |

**결정 1 — 표점 Dockerfile의 베이스를 인자로 받는다. 이것이 핵심이다.**

베이스가 특정 이미지로 고정돼 있으면 그것이 없는 PC에서는 GPU로 표점을
쓰려 해도 **빌드 자체가 불가능**하다.

```dockerfile
ARG BASE_IMAGE=pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime
FROM ${BASE_IMAGE}
```

공식 이미지가 기본이라 GPU만 있으면 누구나 만든다. 이미 torch+CUDA 이미지를
가진 사람은 `BASE_IMAGE`로 넘겨 내려받기 3.5GB를 아낀다.

`docker-compose.yml`의 HuggingFace 캐시 볼륨도 `external: true`라 같은 문제였다 —
그 볼륨이 없는 PC에서는 **볼륨을 찾을 수 없다**며 기동이 실패한다.
이름만 인자로 받게 바꿔 기본은 알아서 만들어지게 했다.

**결정 2 — transformers에 `<5` 상한을 둔다.**

상한 없이 빌드했더니 **5.14.1**이 들어왔다. 이 서비스가 실제로 도는 것을 확인한
조합은 **4.57.3**뿐이다. `AutoModel` import는 5.x에서도 되지만 가중치를 실제로
불러 추론한 적이 없다. 이 저장소의 경험상 NLP 스택의 메이저 상승은 예외가 아니라
**조용한 오작동**으로 나타난다(D-044·D-056). 확인한 뒤에 올린다.

**결정 3 — `--extra classical-gpu`를 「약 4.5GB」로 정정한다.**

13배 틀린 값이 문서 세 곳에 있었다. Windows에서는 CUDA 런타임이 별도
`nvidia-*` 패키지가 아니라 **`torch/lib` 안에 통째로** 들어간다 — 그 폴더
하나가 4,359MB다. Linux도 torch 1,550 + nvidia 2,742 + triton 440 ≈ 4.7GB로 비슷하다.

**결정 4 — 「가벼운 설치」는 성립하지 않는다.**

PaddleOCR를 빼면 D-055가 기본 번들로 정한 것을 빼는 것이 되고, OCR·PDF를 뺀
나머지 전부가 127MB라 다른 무엇을 빼도 828MB 중 2%다. 갈림길은
기본(828MB)과 고서 GPU(+4.5GB)이지 기본 설치 안에 있지 않다.

**검증**: 공식 베이스에서 **실제로 빌드했다**(2026-07-26).
컨테이너 안에서 torch 2.6.0+cu124 · `torch.cuda.is_available()` **True** ·
RTX 3070 Ti 인식 · transformers 4.57.6 확인. 컨테이너를 띄워 `/health` 200
(`ready: true`), `/punctuate` 200 응답까지 확인. `docker compose config`로
기본 경로와 `BASE_IMAGE`·`HF_CACHE_VOLUME` 재정의 경로 양쪽 해석 확인.

**관련**: [D-070](#d-070)의 설치 안내를 실측으로 바로잡는다.
[D-055](#d-055)의 paddle 기본 번들 결정은 그대로다.

---

## D-072: 화면이 옛 버전을 말하고 있었다 — 버전의 정본은 한 곳

**날짜**: 2026-07-26

**맥락**: 사용자가 추출 모드 화면을 캡처해 보냈다. 오른쪽 아래 상태바에
**`v1.1.4`**가 떠 있었다. v1.2.0을 태그하고 릴리스까지 낸 뒤였다.

버전을 적는 곳이 **셋**이었다.

| 어디 | 값 | 누가 고쳤나 |
|---|---|---|
| `pyproject.toml` | 1.2.0 | 릴리스 때 |
| `src/app/server.py` | 1.2.0 | 릴리스 때 |
| `index.html` 상태바 | **1.1.4** | **아무도** |

세 번째는 존재를 몰랐다. `docs/maintenance.md`에 릴리스 절차를 쓸 때도
「버전 올리기: pyproject.toml, server.py **두 곳**」이라고 적었다 —
정본이라고 세운 문서가 이미 틀린 사실을 담고 있었다.

**결정 1 — 버전의 정본을 `pyproject.toml` 하나로 줄인다.**

`server.py`는 `importlib.metadata.version()`으로 설치된 배포판에서 읽고,
화면 상태바는 새 엔드포인트 `GET /api/app/version`에서 받아 채운다.
`index.html`의 하드코딩은 지웠다. **적을 곳이 하나면 어긋날 수 없다.**

**결정 2 — 「실행 대상」 문구를 고친다.**

같은 화면에 「실행하면 쪽 2개가 돕니다」가 떠 있었다. 한국어가 되지 않는다.
D-063에서 «3쪽»이 번호인지 개수인지 애매한 것을 피하려고 «쪽 N개»로 바꿨는데,
애매함을 없애려다 문장을 깨뜨렸다. 개수와 번호를 한 문장에 섞지 않는다.

    실행 대상: 레이아웃 수정: 1, 4쪽 (2쪽)

번호가 앞에 오므로 뒤의 «2쪽»이 번호로 읽힐 여지가 없다.

**근거**:

- 이 결함은 **자동 검사로 잡을 수 없었다.** 하드코딩된 문자열이 문법적으로
  옳고, 테스트는 상태바를 보지 않으며, 정적 검사에 「이 숫자가 낡았다」를
  판정할 근거가 없다. **사람이 화면을 보고서야** 드러났다.
- 그리고 그 사람이 개발자가 아니라 **사용자**였다. 이 저장소의 자동 검증이
  화면에 대해 사실상 아무것도 못 본다는 것을 다시 확인한 셈이다(D-053).

**트레이드오프**:

- `importlib.metadata`는 **설치된** 배포판을 읽는다. `uv sync` 없이 소스만
  두고 돌리면 «unknown»이 된다. 이 저장소는 `uv sync`가 전제이므로 문제되지
  않지만, 실패해도 화면이 죽지 않게 빈 문자열로 물러난다.
- 상태바가 버전을 표시하려면 HTTP 요청 한 번이 더 든다. 로컬 앱이라 무시할
  수준이고, 어긋난 버전을 보여 주는 것보다 낫다.

**검증**: 서버를 띄워 `/api/app/version` → `{"version":"1.2.0"}`,
OpenAPI `info.version` → `1.2.0`, `index.html` 응답에서 주석을 제거하면
`v1.1.4`가 **0건**(상태바 요소는 비어 있고 JS가 채운다)을 확인했다.

**관련**: [D-063](#d-063)의 «개/쪽» 정리가 문장을 깨뜨린 것을 바로잡는다.
[D-053](#d-053) — 화면을 보는 자동 검증이 없다는 부채가 또 실현됐다.

---

## D-073: 3.x 대응 코드가 있는데 한 번도 실행되지 않았다

**날짜**: 2026-08-12

**맥락**: `--engine paddleocr`로 돌리면 「OCR 실패 — 텍스트를 얹은 쪽이
없습니다」만 나왔다. 예외도 traceback도 없다. 원인은 판별 한 줄이다.

```python
if not isinstance(raw_result, list) and hasattr(raw_result, "rec_texts"):
```

PaddleOCR 3.x의 `predict()`는 **이미지별 결과의 리스트**를 돌려준다. 이 조건은
언제나 거짓이 되고, 3.x 파서(`_parse_v3_result`)는 존재만 할 뿐 실행되지
않았다. 2.x 파서가 dict를 순회하며 키(문자열)를 항목으로 받아 「구조 이상」
경고만 남기고 빈 결과를 냈다.

**결정 — 리스트를 벗겨 보고, 속성·키 양쪽으로 읽는다.** 판본에 따라 결과가
객체이기도 dict이기도 하고, `.res` 아래에 한 겹 더 들어가기도 한다. 한쪽만
가정하면 **조용히** 빈 결과가 된다. 좌표는 `rec_polys`를 `dt_polys`보다 먼저
쓴다 — `dt_polys`에는 검출만 되고 인식은 안 된 것이 섞여 텍스트와 짝이
어긋난다.

**근거**: 세 겹이 겹쳐 오래 숨었다.
① 3.x 분기가 **있어서** 대응된 것처럼 보였다.
② 예외 없이 경고 로그만 남아 상위에서는 「실패」로만 보였다.
③ 기본 엔진이 `llm_vision`이고 PaddleOCR은 검출(위치) 전용이라, 인식 경로는
`--engine paddleocr`를 명시할 때만 탄다 — 그리고 도움말이 그것을 말리고 있었다.
사실상 사문화된 경로였다.

**범위**: 검출(위치)은 영향 없다. `line_detector._raw_boxes`는 처음부터 3.x를
올바로 다뤘다. 기존 사용자의 형광·드래그 위치는 정상이었다.

**검증**: 회귀 테스트 13건을 새로 두되, **그 테스트가 이 버그를 실제로 잡는지**
확인했다 — 옛 판별 조건을 되살리면 0줄, 고친 코드는 정상. 모델도 GPU도
네트워크도 필요 없는 순수 파서 테스트다.

**관련**: [D-069](#d-069) — 「조용히 틀리는」 결함의 계보에 하나 더.

---

## D-074: LLM이 «생각한 내용»을 본문으로 구웠다

**날짜**: 2026-08-12

**맥락**: reasoning 모델로 OCR 하면 본문 대신 사고문이 PDF 텍스트 레이어에
박혔다 — 「The user wants me to extract text from the provided image...」.

Ollama는 사고 흐름을 `thinking` 필드로 분리한다. 프로바이더에 「`response`가
비면 `thinking`이라도 쓴다」는 폴백이 있었다. 일반 대화라면 무응답보다 낫다.

**결정 — OCR에서는 이 폴백을 쓰지 않는다.** 호출자가
`allow_thinking_fallback=False`를 주면 빈 결과를 그대로 돌려준다. 그리고 OCR
호출은 `think=False`로 사고를 아예 끈다.

**근거**: OCR에서 사고문 오염은 **빈 결과보다 나쁘다.** 빈 결과는 「실패」로
드러나기라도 하지만, 오염된 PDF는 멀쩡해 보이면서 검색이 안 되고 복사하면
영어 사고문이 나온다. 드러나지 않는 오류가 드러나는 오류보다 비싸다.

또 OCR은 판단이 아니라 옮겨 적기다. 사고를 끄는 편이 결과가 낫다.
실측(qwen3.5:4b, 1쪽): 사고 기본값 → response 0자·thinking 2,742자,
`think=False` → response 1,106자·thinking 0자.

**트레이드오프**: `think=False`를 받으면 응답까지 비우는 모델이 있다는 관찰이
코드 주석에 있었다(텍스트 경로). 비전 경로에서는 실측으로 반대였다. 그래서 둘
다 둔다 — 사고를 끄고, 그래도 비면 오염 대신 실패로 남긴다.

**검증**: 로컬 4B·클라우드 235B 각 1쪽 E2E. 오염 0, 클라우드 모델에서 줄 위치
42개 정상.

---

## D-075: 받아 놓고 쓰지 않던 인자가 형광을 무너뜨렸다

**날짜**: 2026-08-12

**맥락**: Ollama 비전 호출이 `max_tokens`를 인자로 받아 놓고 payload에 넣지
않았다. 응답이 모델 기본값에서 잘리고, 잘린 JSON은 파싱에 실패한다. 그러면
원문 JSON 문자열이 통째로 텍스트 레이어에 박히고, 줄 정보가 없으므로 한
덩어리로 얹힌다 — 서로 다른 y 위치 42개 → **1개**.

**결정 — `options.num_predict`로 넘긴다.** 받은 인자를 쓰지 않는 것은 그 자체로
결함이다. 특히 그 결과가 「조용히 절반만 하고 성공으로 보이는」 형태일 때는.

**관련**: [D-062](#d-062) — 폰트 미임베드로 한자가 조용히 사라지던 것과 같은
계열. 산출물은 만들어지는데 내용이 틀린다.

---

## D-076: 장치와 언어는 고를 수 있어야 한다 — 기본값은 auto

**날짜**: 2026-08-12

**맥락**: `registry.auto_register()`가 `PaddleOcrEngine()`을 인자 없이 만든다.
그래서 CLI로 들어오면 언어와 장치를 **바꿀 방법이 없었다.** 국한문 혼용 한국
논문에 중국어 간체 모델(`ch`)이 걸려 한글이 통째로 빠지는데도 손댈 수 없었다.
그리고 3.x는 `use_gpu` 대신 `device`를 받는데 그 인자를 넘기지 않고 있어,
`use_gpu` 설정 자체가 3.x 경로에서 무시되고 있었다.

**결정 1 — `--paddle-lang`·`--paddle-device`를 연다.** 환경변수
`CTB_PADDLE_LANG`·`CTB_PADDLE_DEVICE`로도 받는다. 호출부를 고치지 않고 바깥에서
지정할 수 있어야 한다.

**결정 2 — 장치 기본값은 `auto`다.** 설치된 paddle이 CUDA 빌드이고 장치가
실제로 보일 때만 GPU를 고른다. **GPU가 없는 환경은 아무것도 지정하지 않아도
예전과 똑같이 동작한다.** 새 옵션이 기존 사용자에게 부담이 되면 안 된다.

**결정 3 — 검출기도 같은 선택을 따른다.** 이걸 맞추지 않으면
`--paddle-device cpu`를 줘도 검출만 GPU로 가서 「CPU로 재본다」가 성립하지
않는다. 옵션이 절반만 듣는 것은 옵션이 없는 것보다 나쁘다.

**근거**: 실측(RTX 3070 Ti Laptop, 200DPI, korean 모델) **CPU 52.1초/쪽 →
GPU 1.0초/쪽**. 513쪽 배치가 7시간 반에서 8분이 된다. 검출은 이 저장소의 필수
경로이므로 이 비용이 전체 처리량을 그대로 결정한다.

**결정 4 — 그래도 GPU판을 기본 의존성으로 올리지는 않는다.**

한 번 올렸다가 되돌렸다. 실측하면 설치가 **828MB → 약 4.3GB**가 된다
(paddle 1,077MB + nvidia-* 런타임 2,708MB). 이 저장소가 별도 opt-in으로 둔
`classical-gpu`(+4.5GB)와 맞먹는 덩치다. **GPU 스택은 언제나 선택으로 둔다**는
방침을 패치 릴리스에서 뒤집을 이유가 없다. 「내 기기를 GPU로 쓰겠다」는 요구는
저장소 기본값을 바꾸지 않고도 충족된다 — 배포판을 교체하면 코드는 그대로
`auto`가 잡는다.

전환 절차와 함정 셋은 `docs/user-guide.md`에 적었다.

- `uv sync`는 정본(CPU판)을 복원하므로 전환이 되돌아간다.
- Windows에서는 sync가 CUDA 런타임까지 지운다 — 휠이 nvidia-* 의존성에 linux
  마커만 달아 두었는데 Windows 빌드도 그 DLL을 찾는다.
  `cublas64_12.dll ... error code 126`.
- `classical-gpu`와 병용하려면 CUDA 버전을 맞춰야 한다. Linux에서 torch와
  paddle이 nvidia-* 런타임을 공유하며 서로 다른 «정확한» 버전을 고정한다.

**교훈**: 「이 기기에서 GPU를 쓰자」와 「모든 사용자가 GPU 스택을 받게 하자」는
다른 결정이다. 앞의 것을 하려다 뒤의 것을 하고 있었다. 용량을 **실측한 뒤에야**
드러났다 — 내려받기 크기(약 2.2GB)만 보고 있었고 설치 크기(4.3GB)는 재지
않았다. 배포 판단은 설치 크기로 한다.

## D-077: 성좌형 대안 구조 — 정본은 파일 계약이고, 이 앱은 그 소비자 중 하나다 (회고)

**날짜**: 2026-08-20

**맥락**: 운양 김윤식 프로젝트(`Downloads/운양`)에서 이 저장소의
NdlkotenOcrEngine을 직접 import해 필사본 3,607쪽을 초벌 OCR하고, 쪽당
JSON(줄 단위 텍스트·`bbox_pdf`·읽기순서 `order`) 하나를 파일 계약으로 정한 뒤,
그 계약만 읽는 **단일 파일 300줄 뷰어**(PDF.js + 오버레이 + 세로쓰기 대조
패널)로 원본↔OCR↔LLM 교감 대조가 성립했다. 「ctb를 애초에 이런 경량 뷰어
기반으로 만들었어야 했나」라는 질문이 나왔다.

**관찰 — 그 뷰어가 가벼울 수 있었던 이유는 이 저장소가 무거움을 이미 흡수했기
때문이다**: ① 읽기 전용이라 쓰기 경로(교정 저장·Git 이력·스키마 검증·해석
병존)가 통째로 없다. 「행 하나 고쳐서 저장」이 붙는 순간 그 답을 제대로 내면
ctb를 닮아간다. ② NDL 업스트림 호환(class 1 하드코딩)·XY-Cut·의존성 지뢰밭은
이 저장소가 이미 풀어 둔 것을 import 한 줄로 가져갔다. ③ 쪽·줄·bbox·읽기순서를
파일로 고정하는 발상 자체가 L2/L3 설계의 문법이다.

**결정 — 재작성하지 않는다. 대신 방향을 명문화한다**: 정본은 앱이 아니라
**파일 계약**이고, 이 앱은 그 계약의 (가장 두꺼운) 소비자다. 외부의 얇은
소비자(경량 뷰어·일회성 스크립트)가 같은 데이터를 읽는 구성은 설계 위반이
아니라 **의도된 사용법**이다. `ctb ocr` 한 줄 CLI를 나중에 붙였던 것도 같은
끌림의 증거다. 후속 후보(백로그): 운양식 쪽 단위 JSON(외부 계약)과 L2
`ocr_page` 스키마 사이의 왕복 변환기 — 성사되면 무거운 쓰기 경로(사람
교정·이력)는 ctb가, 빠른 열람·대조는 외부 얇은 도구가 맡는 분업이 된다.

**교훈**: 「경량」은 유지되는 성질이 아니라 출발 상태다(그 뷰어도 회전 0 전제,
CDN 의존, 단일 파일이라는 부채의 씨앗을 이미 품고 있다). 무게를 비교할 때는
UI가 아니라 **쓰기 경로와 계약의 무게**를 비교한다. 그리고 얇은 도구가 쉽게
태어날 수 있는가는 그 자체로 파일 계약의 품질 지표다.

## D-078: GPU는 별도 환경이다 — 단일 venv 수동 스왑 폐기, `.venv`/`.venv-gpu` 이원화

**날짜**: 2026-08-20

**맥락**: D-076은 GPU 문제를 두 층으로 나눠 실행 층(장치 `auto`)은 자동화했지만,
설치 층은 「단일 venv에 GPU판 수동 교체 + 함정 문서화」로 남겼다. user-guide에
「`uv sync`를 돌리면 되돌아갑니다」라고 적어 둔 것이 그 증거다 — **문서화된
반복 함정은 설계 결함의 자백이다.** 실제로 2026-08-20 운양 프로젝트 작업 중
`uv sync --extra ndlkotenocr` 한 번에 수동 설치된 paddlepaddle-gpu가 증발했고,
이어 `uv run`의 락 복원이 수동 상향(huggingface-hub·safetensors)을 두 차례
되돌렸다. 같은 사고 계열이 세 번 났다.

**결정 — 환경을 두 개로 이원화하고, 선택은 기계가 한다**:

- `.venv` = **CPU 정본.** 락파일과 항상 일치. `uv sync`·`uv run` 자유.
- `.venv-gpu` = **GPU 환경.** `UV_PROJECT_ENVIRONMENT=.venv-gpu uv sync --extra
  ndlkotenocr --extra classical-gpu`(락 기반) 위에 paddlepaddle-gpu만 오버레이.
  이 환경에는 `uv sync`·`uv run` **금지** — python 직접 호출만.
- `start_server.bat`이 실행 시 `nvidia-smi`로 감지해 자동 선택한다. 사용자가
  고를 것은 없다.

**함정 실측 두 가지**(재발 방지용 기록): ① `uv pip`은
`UV_PROJECT_ENVIRONMENT`를 무시하고 기본 `.venv`에 설치한다 — `.venv-gpu`
조작에는 반드시 `--python .venv-gpu\Scripts\python.exe`. ② `uv run`은 실행 전
락 기준 동기화로 환경을 되돌린다 — GPU 환경 실행은 python 직접 호출.

**교훈**: 「수동 상태 + 그것을 지우는 도구 + 경고 문서」의 삼각형은 언젠가
반드시 무너진다. 상태가 도구와 싸우게 두지 말고, 도구가 존중하는 단위(별도
환경)로 상태를 분리한다. 이 결정은 처음 GPU 전환을 설계한 시점(D-076,
2026-08-12)에 내렸어야 했다.

---

## D-079: 셀 수 있는 것은 기계가 센다 — 문서 수치 드리프트 검사

**날짜**: 2026-09-01

**맥락**: `server.py` 머리말이 라우트 수를 documents 34·interpretations 23·
llm_ocr 14로 적은 채 실제(40·25·20)와 오래 어긋나 있었다. 릴리스 절차에
`/doc-sync` 게이트가 이미 있지만 그것은 **「문서를 봤는가」를 강제할 뿐**
숫자가 맞는지는 사람 눈에 의존한다. 그리고 사람 눈은 이 종류를 놓친다 —
문법적으로 옳고, 테스트는 초록이고, 화면에도 아무 일이 없다(D-072와 같은 계열).

**결정 — 셀 수 있는 사실은 코드에서 세어 문서와 대조한다.**

`scripts/check_doc_drift.py`가 라우터별 라우트 수·라우트 총수·라우터 모듈 수·
JS 모듈 수·스키마 수(그룹별 포함)·테스트 파일 수를 실측하고,
README.md·AGENTS.md·CLAUDE.md·`docs/maintenance.md`·
`docs/architecture-diagrams.md`·`server.py` 머리말의 수치와 대조한다.
어긋나면 `파일:줄 — 문서 값 ≠ 실측 값`을 출력하고 종료 코드 1.

**결정 — 새 게이트를 늘리지 않고 기존 관문에 얹는다.**

`tests/test_doc_drift.py`로 pytest에 편입했다. 릴리스 절차 1단계가 이미
「pytest 전부 통과」이고, `feat`·`refactor`·`release` 커밋에는 doc-sync 게이트가
걸려 있다. 게이트를 하나 더 만들면 지켜야 할 관문만 늘고 실제로는 잊힌다.

**무엇을 세지 않는가** (이 선택이 이 결정의 핵심이다):

| 세지 않는 것 | 왜 |
|---|---|
| 줄 수(38,633줄 같은 것) | 한 줄만 고쳐도 바뀐다. 거의 매 커밋이 빨개지는 게이트는 곧 무시되고, 무시되는 게이트는 없는 것만 못하다 |
| 테스트 **건수**(671) | pytest를 실제로 돌려야 안다(14분). 정적으로 지킬 수 없다 |
| `DECISIONS.md`·`docs/releases/` | 거기 수치는 **「그때 그렇게 검증했다」는 기록**이지 현재 상태에 대한 주장이 아니다. 과거 기록을 현재값으로 고치는 것은 동기화가 아니라 역사 위조다 |

**검증**: 붙이자마자 **몰랐던 드리프트 둘**을 잡았다.
① `AGENTS.md`의 `reading.py (26 라우트)` — 실제 24. 이 결정이 겨냥한 바로 그
사고가 다른 문서에서 조용히 재발해 있었다.
② `AGENTS.md`의 「테스트 39파일」 — 실제 41.

검사기가 정말 잡는지도 따로 시험했다(`test_scanner_actually_catches_drift`) —
일부러 틀린 문장을 넣어 탐지를 확인한다. D-073에서 「분기가 존재만 하고 한 번도
실행되지 않은」 것을 겪었으므로, **검사기가 살아 있다는 것 자체를 시험한다.**
전체 671건 통과·ruff 통과.

**한계**: 문서의 주장은 정규식으로 찾으므로 `CLAIM_PATTERNS`에 없는 표현으로
적은 수치는 보지 못한다. 새 종류의 수치를 문서에 쓸 때 패턴도 함께 늘려야 한다.
지킬 수 없는 수치는 **애초에 문서에 적지 않는 편**이 낫다 —
`maintenance.md` 3장의 「655개가 통과해도」를 건수 없는 문장으로 바꾼 이유다.

**관련**: [D-072](#d-072) — 「사람이 화면을 보고서야 드러났다」의 반대편.
사람이 봐야만 하던 것 중 셀 수 있는 부분을 기계로 옮겼다.
[D-073](#d-073) — 시험이 그 결함을 실제로 잡는지까지 확인하는 관행.

---

### 배포·설치
- [ ] Google Drive + .git 충돌 회피 가이드 → Phase 10 이후
- [ ] 비개발자용 Git 번들링 또는 Git-free 모드 → Phase 10 이후

### 문헌 구조
- [ ] **문헌 병합** — 따로 등록한 卷上·卷下를 하나로 합치기.
      쪽 번호 충돌, 해석 저장소 둘의 처리, Git 이력 둘의 처리를 정해야 한다.
      되돌릴 수 없는 작업이라 상상으로 정하지 않고 **실제 사례가 생겼을 때**
      그 데이터를 보고 설계한다. 상세: [D-061](#d-061-권-추가--문헌은-만든-뒤에도-자란다-문헌-병합은-설계-필요)
      대안: 여러 권짜리는 등록할 때 파일을 여러 개 넣으면 된다.

### 전체
- [ ] 라이선스/공개 범위
- [ ] 프로젝트 이름
