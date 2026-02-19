# Phase 11-1: 끊어읽기·표점·현토 편집기 (L5)

> Claude Code 세션 지시문
> 이 문서를 읽고 작업 순서대로 구현하라.

---

## 사전 준비

1. CLAUDE.md를 먼저 읽어라.
2. docs/DECISIONS.md를 읽어라.
3. docs/phase11_12_design_decisions.md를 읽어라 — L4 역할 확장, L5 표점/현토 스키마가 정의되어 있다.
4. 이 문서 전체를 읽은 후 작업을 시작하라.
5. 기존 코드 구조를 먼저 파악하라: `src/` 디렉토리 전체, `src/core/`, `src/api/`, `src/llm/`, `static/js/`.
6. **Phase 10-2에서 만든 `src/llm/` 구조를 참고하라** — LLM 표점 Draft 생성에 LlmRouter를 재사용한다.

---

## 설계 요약 — 반드시 이해한 후 구현

### 핵심 원칙

- **L5는 두 파일로 분리된다**: `punctuation_page.json`(표점)과 `hyeonto_page.json`(현토).
- **원본 문자열은 절대 변형하지 않는다**: L4 텍스트는 그대로 유지. 표점과 현토는 위치+내용만 기록.
- **L4와 L5의 구분**: 원본에 있던 구두/현토 = L4에 전재. 연구자가 새로 만든 것 = L5.
- **LLM 표점 Draft**: 번역(11-2) 전에 LLM이 표점 초안을 생성할 수 있다. Draft→Review→Commit 패턴.
- **현토 분류 체계는 아직 미정**: `category` 필드를 null로 두고, 향후 확정 시 채운다.

### L5 표점 데이터 모델 — 통합 before/after 방식

모든 표점을 **범위의 앞(before)과 뒤(after)에 무엇을 붙이느냐**로 통일한다.

```json
{
  "block_id": "p01_b01",
  "marks": [
    {
      "id": "pm_001",
      "target": { "start": 3, "end": 3 },
      "before": null,
      "after": "，"
    },
    {
      "id": "pm_002",
      "target": { "start": 7, "end": 7 },
      "before": null,
      "after": "。"
    },
    {
      "id": "pm_003",
      "target": { "start": 10, "end": 11 },
      "before": "《",
      "after": "》"
    }
  ]
}
```

표점 유형별 패턴:

| 유형 | before | after | 예시 |
|------|--------|-------|------|
| 句讀 (마침표) | null | 。 | 王戎簡要裴楷清通。 |
| 句讀 (쉼표) | null | ， | 王戎簡要，裴楷清通。 |
| 서명호 | 《 | 》 | 《論語》 |
| 편명호 | 〈 | 〉 | 〈學而〉 |
| 인용부호 | 「 | 」 | 「仁者愛人」 |

- `start`/`end`: 0-based 글자 인덱스 (inclusive). `start == end`면 단일 글자 위치.
- 표점 부호는 **학술 표준 기본 프리셋 + 사용자 추가 가능**. 고정 enum이 아니다.
- 밑줄(인명호 등) 렌더링은 별도 `style` 필드로 확장 가능 (이번 Phase에서는 구현하지 않음).

### L5 현토 데이터 모델 — 범위(start/end) + position

```json
{
  "block_id": "p01_b01",
  "annotations": [
    {
      "id": "ht_001",
      "target": { "start": 0, "end": 1 },
      "position": "after",
      "text": "은",
      "category": null
    },
    {
      "id": "ht_002",
      "target": { "start": 2, "end": 3 },
      "position": "after",
      "text": "하고",
      "category": null
    }
  ]
}
```

- `start`/`end`: 0-based 글자 인덱스 (inclusive). `start == end`면 단일 글자에 붙는 토.
- `position`: "after" 기본. 향후 필요시 확장.
- `category`: **현재 null**. 분류 체계 확정 후 채움.
- 병렬 현토안: 해석 저장소 분기로 처리 (기존 메커니즘). 향후 `alternatives` 배열로 확장 여지.

### LLM 표점 흐름

```
L4 원문
  → LlmRouter.generate() with 표점 프롬프트
  → L5 표점 Draft 생성
  → 연구자 검토 (GUI에서 수정 가능)
  → Commit → punctuation_page.json 저장 + git commit
```

---

## 작업 순서

### 작업 1: L5 스키마 파일 생성

두 개의 JSON 스키마를 만들어라:

```
schemas/interp/punctuation_page.schema.json
schemas/interp/hyeonto_page.schema.json
```

위의 데이터 모델을 JSON Schema로 정의한다.
- punctuation: block_id, marks 배열 (id, target{start,end}, before, after)
- hyeonto: block_id, annotations 배열 (id, target{start,end}, position, text, category)
- 둘 다 `$schema`, `title`, `description`, `required` 포함

테스트: 예시 JSON으로 검증 통과 확인.

커밋: `feat: L5 표점/현토 JSON Schema 정의`

### 작업 2: 표점 부호 프리셋 관리

```
resources/punctuation_presets.json
```

학술 표준 기본 프리셋을 정의한다:

```json
{
  "presets": [
    { "id": "period", "label": "마침표", "before": null, "after": "。" },
    { "id": "comma", "label": "쉼표", "before": null, "after": "，" },
    { "id": "semicolon", "label": "쌍점", "before": null, "after": "；" },
    { "id": "colon", "label": "고리점", "before": null, "after": "：" },
    { "id": "question", "label": "물음표", "before": null, "after": "？" },
    { "id": "exclamation", "label": "느낌표", "before": null, "after": "！" },
    { "id": "book_title", "label": "서명호", "before": "《", "after": "》" },
    { "id": "chapter_title", "label": "편명호", "before": "〈", "after": "〉" },
    { "id": "quote_single", "label": "인용부호", "before": "「", "after": "」" },
    { "id": "quote_double", "label": "겹인용부호", "before": "『", "after": "』" }
  ],
  "custom": []
}
```

사용자가 `custom`에 추가할 수 있는 구조.

커밋: `feat: 표점 부호 프리셋 정의`

### 작업 3: 표점 코어 로직

```
src/core/punctuation.py
```

구현할 함수:

- `load_punctuation(work_path, interp_id, part_id, page_number) → dict`: L5 표점 파일 로드
- `save_punctuation(work_path, interp_id, part_id, page_number, data) → None`: 스키마 검증 후 저장
- `add_mark(data, block_id, mark) → dict`: 표점 추가 (id 자동 생성)
- `remove_mark(data, block_id, mark_id) → dict`: 표점 삭제
- `update_mark(data, block_id, mark_id, updates) → dict`: 표점 수정
- `render_punctuated_text(original_text, marks) → str`: 원문 + 표점 합성 텍스트 생성 (표시용)
- `split_sentences(original_text, marks) → list[dict]`: 표점 기반으로 문장 분리 (번역 단위용)

`render_punctuated_text` 예시:
- 입력: "王戎簡要裴楷清通", marks에 index 3 뒤 "，", index 7 뒤 "。"
- 출력: "王戎簡要，裴楷清通。"

`split_sentences` 예시:
- 입력: 같은 데이터
- 출력: [{"start": 0, "end": 3, "text": "王戎簡要"}, {"start": 4, "end": 7, "text": "裴楷清通"}]

테스트: 蒙求 첫 구절로 단위 테스트 작성.

커밋: `feat: L5 표점 코어 로직`

### 작업 4: 현토 코어 로직

```
src/core/hyeonto.py
```

구현할 함수:

- `load_hyeonto(work_path, interp_id, part_id, page_number) → dict`: L5 현토 파일 로드
- `save_hyeonto(work_path, interp_id, part_id, page_number, data) → None`: 스키마 검증 후 저장
- `add_annotation(data, block_id, annotation) → dict`: 현토 추가
- `remove_annotation(data, block_id, annotation_id) → dict`: 현토 삭제
- `update_annotation(data, block_id, annotation_id, updates) → dict`: 현토 수정
- `render_hyeonto_text(original_text, annotations) → str`: 원문 + 현토 합성 텍스트 생성

`render_hyeonto_text` 예시:
- 입력: "王戎簡要裴楷清通", annotations에 (0,1)→"은", (2,3)→"하고", (4,5)→"ᅵ", (6,7)→"하니"
- 출력: "王戎은簡要하고裴楷ᅵ清通하니"

테스트: 蒙求 첫 구절로 단위 테스트 작성.

커밋: `feat: L5 현토 코어 로직`

### 작업 5: LLM 표점 Draft 생성

```
src/llm/prompts/punctuation.yaml
src/core/punctuation_llm.py
```

표점 프롬프트:

```yaml
id: punctuation_classical_chinese_v1

system: |
  당신은 한문 고전 텍스트의 표점(句讀) 전문가입니다.
  원문에 현대 학술 표점부호를 삽입하세요.
  
  사용 가능한 부호: 。，；：？！《》〈〉「」『』
  
  규칙:
  - 문장이 끝나면 。
  - 절이 이어지면 ，
  - 서명은 《》, 편명은 〈〉
  - 인용은 「」

user_template: |
  다음 한문 원문에 표점을 삽입하세요.
  
  원문: {original_text}
  
  JSON 형식으로 응답하세요:
  {{"marks": [{{"start": 숫자, "end": 숫자, "before": 문자열|null, "after": 문자열|null}}, ...]}}
```

`punctuation_llm.py` 함수:

- `generate_punctuation_draft(work_path, interp_id, part_id, page_number, block_id) → LlmDraft`
  - L4에서 원문 로드
  - LlmRouter.generate()로 표점 Draft 생성
  - JSON 파싱 후 스키마 검증
  - Draft 상태로 저장
- `commit_punctuation_draft(draft_id, modifications) → None`
  - 수정 사항 반영
  - punctuation_page.json에 저장
  - git commit

테스트: 蒙求 첫 페이지로 LLM 표점 생성 테스트 (LLM 미연결 시 mock).

커밋: `feat: LLM 표점 Draft 생성 로직`

### 작업 6: API 엔드포인트 — 표점

```python
# src/api/punctuation.py

# 표점 조회
GET /api/interpretations/{interp_id}/pages/{page}/punctuation
  → 200: punctuation_page.json 내용

# 표점 저장 (전체 덮어쓰기)
PUT /api/interpretations/{interp_id}/pages/{page}/punctuation
  입력: { "block_id": "...", "marks": [...] }
  → 200: 저장 결과

# 개별 표점 추가
POST /api/interpretations/{interp_id}/pages/{page}/punctuation/{block_id}/marks
  입력: { "target": {"start": N, "end": N}, "before": "...", "after": "..." }
  → 201: 생성된 mark (id 포함)

# 개별 표점 삭제
DELETE /api/interpretations/{interp_id}/pages/{page}/punctuation/{block_id}/marks/{mark_id}
  → 204

# LLM 표점 Draft 생성
POST /api/interpretations/{interp_id}/pages/{page}/punctuation/{block_id}/llm-draft
  → 200: { "draft_id": "...", "marks": [...], "status": "draft" }

# LLM 표점 Draft 확정
POST /api/interpretations/{interp_id}/pages/{page}/punctuation/{block_id}/llm-draft/{draft_id}/commit
  입력: { "modifications": {...} }
  → 200: 확정 결과

# 합성 텍스트 미리보기
GET /api/interpretations/{interp_id}/pages/{page}/punctuation/{block_id}/preview
  → 200: { "rendered": "王戎簡要，裴楷清通。" }
```

커밋: `feat: L5 표점 API 엔드포인트`

### 작업 7: API 엔드포인트 — 현토

```python
# src/api/hyeonto.py

# 현토 조회
GET /api/interpretations/{interp_id}/pages/{page}/hyeonto
  → 200: hyeonto_page.json 내용

# 현토 저장 (전체 덮어쓰기)
PUT /api/interpretations/{interp_id}/pages/{page}/hyeonto
  입력: { "block_id": "...", "annotations": [...] }
  → 200: 저장 결과

# 개별 현토 추가
POST /api/interpretations/{interp_id}/pages/{page}/hyeonto/{block_id}/annotations
  입력: { "target": {"start": N, "end": N}, "position": "after", "text": "은" }
  → 201: 생성된 annotation (id 포함)

# 개별 현토 삭제
DELETE /api/interpretations/{interp_id}/pages/{page}/hyeonto/{block_id}/annotations/{ann_id}
  → 204

# 합성 텍스트 미리보기
GET /api/interpretations/{interp_id}/pages/{page}/hyeonto/{block_id}/preview
  → 200: { "rendered": "王戎은簡要하고裴楷ᅵ清通하니" }
```

커밋: `feat: L5 현토 API 엔드포인트`

### 작업 8: GUI — 표점 편집기

작업 모드 탭에 [표점] 추가:

```
[열람] [레이아웃] [교정] [표점] [현토]
                            │
         ┌──────────────────┴──────────────────┐
         │ 상단: 원문 블록 표시                  │
         │   "王戎簡要裴楷清通孔明臥龍呂望非熊"  │
         │                                      │
         │ 중단: 표점 삽입 영역                  │
         │   글자 사이 클릭 → 표점 부호 선택     │
         │   [。] [，] [；] [《》] [〈〉] [「」]  │
         │                                      │
         │ 하단: 미리보기                        │
         │   "王戎簡要，裴楷清通。孔明臥龍，..."  │
         │                                      │
         │ [AI 표점] [초기화] [저장]             │
         └──────────────────────────────────────┘
```

구현 사항:
- 원문의 글자 사이에 커서를 놓으면 표점 삽입 위치 선택
- 표점 부호 팔레트에서 클릭하여 삽입
- 감싸기 부호(《》 등)는 범위 선택 후 삽입
- [AI 표점] 버튼 → LLM Draft 생성 → Draft 리뷰 UI (Phase 10-2 패턴 재사용)
- 실시간 미리보기 갱신

커밋: `feat: L5 표점 편집기 GUI`

### 작업 9: GUI — 현토 편집기

작업 모드 탭에 [현토] 추가:

```
[열람] [레이아웃] [교정] [표점] [현토]
                                  │
         ┌────────────────────────┴────────────────────────┐
         │ 상단: 원문 블록 표시 (표점 적용됨)               │
         │   "王戎簡要，裴楷清通。"                          │
         │                                                  │
         │ 중단: 현토 삽입 영역                              │
         │   글자(범위) 클릭 → 현토 입력 팝업                │
         │   위치: after ▼  토: [     ] [삽입]              │
         │                                                  │
         │ 하단: 미리보기                                    │
         │   "王戎은簡要하고，裴楷ᅵ清通하니。"               │
         │                                                  │
         │ [초기화] [저장]                                   │
         └──────────────────────────────────────────────────┘
```

구현 사항:
- 글자 클릭 시 해당 글자 선택 (단일). 드래그 시 범위 선택.
- 선택 후 현토 입력 팝업: position 선택 + 토 텍스트 입력
- 삽입된 현토는 원문 위/옆에 시각적으로 표시
- 표점이 있으면 함께 반영된 미리보기

커밋: `feat: L5 현토 편집기 GUI`

### 작업 10: 통합 테스트

테스트 시나리오 (蒙求 첫 구절):

1. L4에 원문 "王戎簡要裴楷清通" 확인
2. [표점] 모드에서 AI 표점 실행 → Draft 생성 확인
3. Draft 수정 후 확정 → punctuation_page.json 저장 확인
4. [현토] 모드에서 수동으로 현토 삽입
5. 미리보기에서 "王戎은簡要하고，裴楷ᅵ清通하니。" 확인
6. git log에서 커밋 기록 확인

커밋: `test: L5 표점/현토 통합 테스트`

---

## 완료 체크리스트

- [ ] schemas/interp/punctuation_page.schema.json 생성
- [ ] schemas/interp/hyeonto_page.schema.json 생성
- [ ] resources/punctuation_presets.json 생성
- [ ] src/core/punctuation.py — 표점 CRUD + 렌더링 + 문장 분리
- [ ] src/core/hyeonto.py — 현토 CRUD + 렌더링
- [ ] src/llm/prompts/punctuation.yaml — 표점 프롬프트
- [ ] src/core/punctuation_llm.py — LLM 표점 Draft 생성
- [ ] src/api/punctuation.py — 표점 API 엔드포인트
- [ ] src/api/hyeonto.py — 현토 API 엔드포인트
- [ ] GUI에 [표점] 모드 탭 + 표점 편집기
- [ ] GUI에 [현토] 모드 탭 + 현토 편집기
- [ ] 통합 테스트 통과

---

## ⏸️ 이번 Phase에서 구현하지 않는 것

- 현토 분류 체계 (category enum) — 미정, null로 둠
- 밑줄(인명호) 렌더링 — style 필드 확장은 향후
- LLM 자동 현토 — 모델 학습 후, 스키마에 확장 여지만 남김
- 현토 병렬 비교 UI — 해석 저장소 분기로 처리

---

## ⏭️ 다음 세션: Phase 11-2 — 번역 워크플로우 + LLM (L6)

```
이 세션(11-1)이 완료되면 다음 작업은 Phase 11-2 — 번역 워크플로우이다.

11-1에서 만든 것:
  ✅ L5 표점 스키마 + 코어 로직 + API + GUI
  ✅ L5 현토 스키마 + 코어 로직 + API + GUI
  ✅ LLM 표점 Draft 생성
  ✅ split_sentences() — 표점 기반 문장 분리

11-2에서 만들 것:
  - L6 번역 스키마 + 코어 로직
  - LLM 번역 Draft 생성 (문장 단위)
  - 번역 편집기 GUI
  - Draft→Review→Commit 워크플로우

세션 문서: phase11_2_translation_session.md
사전 준비:
  - 11-1의 split_sentences()가 정상 동작하는지 확인
  - 10-2의 LlmRouter가 정상 동작하는지 재확인
```
