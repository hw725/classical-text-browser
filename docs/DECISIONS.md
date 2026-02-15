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
현재 코드명: classical-text-platform (임시)

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

### 원본 저장소
- [ ] JSON 스키마 각 필드의 상세 정의 → Phase 1에서 해결
- [ ] 서지정보 파싱 상세 → Phase 5에서 해결
- [ ] git-lfs 설정 상세 → Phase 2에서 해결
- [ ] block_type 어휘 확장 → 점진적

### OCR
- [x] OCR 엔진 플러그인 아키텍처 → D-009 (Phase 10-1)
- [ ] OCR 엔진 비교 평가 → Phase 10 이후

### LLM 협업
- [x] LLM 호출 아키텍처 → D-010 (Phase 10-2)
- [x] 프롬프트 설계 원칙 → layout_analysis.yaml (Phase 10-2)
- [x] 비용 관리 → UsageTracker + 월별 예산 (Phase 10-2)

### 저장소 연결
- [ ] 사다리형 git 그래프 구현
- [ ] git 호스팅 선정

### 해석 저장소
- [ ] 5~8층 데이터 모델 상세
- [ ] 본문/주석 번역의 연결 구조
- [ ] 협업 모델

### 배포·설치
- [ ] Google Drive + .git 충돌 회피 가이드 → Phase 10 이후
- [ ] 비개발자용 Git 번들링 또는 Git-free 모드 → Phase 10 이후

### 전체
- [ ] 라이선스/공개 범위
- [ ] 프로젝트 이름
