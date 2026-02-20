# JSON Schema 정의

이 디렉토리는 프로젝트의 모든 데이터 구조를 JSON Schema로 정의한다.
코드를 짜기 전에 "어떤 JSON을 만들 것인지"를 확정하는 것이 목적이다.

## 스키마 구성

### source_repo/ — 원본 저장소 (1~4층)

| 스키마 | 설명 | 근거 |
|--------|------|------|
| `manifest.schema.json` | 문헌 매니페스트 (document_id, parts[], 완성도) | v7 섹션 5.1, 10.1 |
| `bibliography.schema.json` | 서지정보 (모든 필드 nullable, raw_metadata 보존) | v7 섹션 7.5 |
| `layout_page.schema.json` | L3 레이아웃 분석 — LayoutBlock 정의 | DECISIONS D-002 |
| `ocr_page.schema.json` | L2 OCR 결과 — OcrResult 정의 | v7 섹션 5.2 |
| `corrections.schema.json` | L4 교정 기록 (6종 교정 유형) | v7 섹션 5.4 |
| `dependency.schema.json` | 해석→원본 저장소 의존 추적 | v7 섹션 4.2 |

### core/ — 코어 스키마 (해석 저장소)

| 스키마 | 설명 | 근거 |
|--------|------|------|
| `work.schema.json` | 작품 | core-schema-v1.3 섹션 1 |
| `text_block.schema.json` | 해석용 텍스트 단위 (source_ref 포함) | core-schema-v1.3 섹션 2, D-005 |
| `tag.schema.json` | 표면 주석 (LLM/자동 추출) | core-schema-v1.3 섹션 3 |
| `concept.schema.json` | 승격된 의미 엔티티 | core-schema-v1.3 섹션 4 |
| `agent.schema.json` | 역사적/서사적 행위자 | core-schema-v1.3 섹션 5 |
| `relation.schema.json` | 엔티티 간 관계 | core-schema-v1.3 섹션 6 |

### interp/ — 해석 저장소 (5~7층)

| 스키마 | 설명 | 근거 |
|--------|------|------|
| `punctuation_page.schema.json` | L5 표점(句讀) — 블록별 글자 인덱스에 부호 삽입 | v7 섹션 8.1, D-014 |
| `hyeonto_page.schema.json` | L5 현토(懸吐) — 블록별 글자 인덱스에 한국어 토 | v7 섹션 8.2, D-015 |
| `translation_page.schema.json` | L6 번역 — 문장별 번역 + 번역자 정보 + 주석 맥락(`annotation_context`) | v7 섹션 8.3, D-016 |
| `annotation_page.schema.json` | L7 주석 **v2** — 기존 태깅 + 사전형 주석(`DictionaryEntry`) + 4단계 누적 생성 이력(`GenerationStage`) | v7 섹션 8.4, D-017~D-019 |
| `citation_mark_page.schema.json` | L7 인용 마크 — 논문 인용을 위한 텍스트 마크업 + 서지정보 수동 오버라이드 | D-020 |

### exchange.schema.json — 교환 형식

단일 JSON으로 문서 상태를 스냅샷. 내보내기/가져오기용. (v7 섹션 11.2)

## 용어 규칙 (DECISIONS.md D-003)

"Block"이라고만 쓰지 않는다. 항상 다음 세 이름 중 하나를 사용한다:

| 이름 | 위치 | 정체 |
|------|------|------|
| **LayoutBlock** | 원본 저장소 L3 (`layout_page.schema.json`) | 페이지 이미지 위의 사각형 영역. OCR 읽기 순서 단위. |
| **OcrResult** | 원본 저장소 L2 (`ocr_page.schema.json`) | LayoutBlock 안에서 OCR이 인식한 글자들. |
| **TextBlock** | 코어 스키마 (`text_block.schema.json`) | 해석 작업의 최소 텍스트 단위 (문장/절/구). |

## 데이터 흐름

원본에서 해석까지의 흐름:

```
L1 이미지/PDF (불변)
     │
     ▼
L3 레이아웃 분석 ─── layout_page.schema.json
  │  LayoutBlock: 영역 구분, block_type, reading_order
  │
  ▼
L2 OCR 글자해독 ──── ocr_page.schema.json
  │  OcrResult: 글자 + bbox + confidence
  │  layout_block_id로 LayoutBlock 참조
  │
  ▼
L4 사람 교정 ─────── corrections.schema.json
  │  교정 유형: ocr_error, variant_reading, variant_char,
  │             decoding_error, uncertain, layout_correction
  │
  ═══ 저장소 경계 ═══
  │
  ▼
TextBlock ──────────── text_block.schema.json
  │  source_ref로 원본(L4) 추적
  │  해석 저장소의 시작점
  │
  ├─→ Tag ───────────── tag.schema.json
  │     LLM/자동 추출, 승격 가능
  │
  ├─→ Concept ────────── concept.schema.json
  │     Tag에서 연구자 판단으로 승격
  │
  ├─→ Agent ──────────── agent.schema.json
  │     역사적 인물/행위자
  │
  └─→ Relation ────────── relation.schema.json
        Agent/Concept/TextBlock 간 관계

--- 해석 작업 (interp/) ---

L4 텍스트 (교정 완료)
     │
     ├─→ L5 표점 ──────── punctuation_page.schema.json
     │     블록별 글자 인덱스에 부호 삽입 (before/after)
     │
     ├─→ L5 현토 ──────── hyeonto_page.schema.json
     │     블록별 글자 인덱스에 한국어 토
     │
     ├─→ L6 번역 ──────── translation_page.schema.json
     │     문장별 번역 + annotation_context (주석 참조)
     │
     ├─→ L7 주석 ──────── annotation_page.schema.json (v2)
     │     │  기존 태깅 + 사전형 주석 (DictionaryEntry)
     │     │  4단계 누적 생성: from_original → from_translation
     │     │                   → from_both → reviewed
     │     │
     │     └─→ L6 번역과 양방향 연동
     │           번역→주석: annotation_context에 참조 기록
     │           주석→번역: dictionary_section으로 번역 품질 향상
     │
     └─→ L7 인용 마크 ── citation_mark_page.schema.json
           논문 인용을 위한 구절 마크업 + 서지정보 해소
```

## 공통 규칙

- **id**: 모든 코어 엔티티는 UUID 사용 (operation-rules 2.1)
- **status**: `draft → active → deprecated → archived` (삭제 금지, operation-rules 2.4)
- **인코딩**: UTF-8, LF 줄바꿈 (operation-rules 2.2)
- **검증**: jsonschema로 커밋 전 검증 (operation-rules 6)

## 저장소 간 의존

```
[원본 저장소]                    [해석 저장소]
  manifest.json                   dependency.json
  bibliography.json                 ├─ source.document_id → manifest
  L3_layout/ (LayoutBlock)          ├─ source.base_commit
  L2_ocr/ (OcrResult)              └─ tracked_files[]
  L4_text/ (교정 텍스트)                ├─ path (원본 파일)
  corrections.json                     ├─ hash_at_base
                                       └─ status
```

`dependency.schema.json`이 두 저장소를 파일 단위로 연결한다.
