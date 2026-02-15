# Phase 11-3: 주석/사전 연동 (L7)

> Claude Code 세션 지시문
> 이 문서를 읽고 작업 순서대로 구현하라.

---

## 사전 준비

1. CLAUDE.md를 먼저 읽어라.
2. docs/DECISIONS.md를 읽어라.
3. docs/phase11_12_design_decisions.md를 읽어라 — L7 주석 스키마가 정의되어 있다.
4. 이 문서 전체를 읽은 후 작업을 시작하라.
5. 기존 코드 구조를 먼저 파악하라: `src/core/`, `src/llm/`, `src/api/`, `static/js/`.
6. **Phase 10-2의 LlmRouter와 Phase 11-1/11-2의 Draft→Review→Commit 패턴을 참고하라.**

---

## 설계 요약 — 반드시 이해한 후 구현

### 핵심 원칙

- **주석 유형은 사용자 정의 가능**: 고정 enum이 아니라 `annotation_types.json`으로 관리.
- **기본 프리셋 5종**: person(인물), place(지명), term(용어), allusion(전거), note(메모).
- **LLM 자동 태깅**: 원문 전체를 보내고 한번에 태깅. Draft→Review→Commit.
- **범위 기반 타겟**: L5 표점/현토와 동일한 start/end 패턴.

### L7 주석 데이터 모델

```json
{
  "block_id": "p01_b01",
  "annotations": [
    {
      "id": "ann_001",
      "target": { "start": 0, "end": 1 },
      "type": "person",
      "content": {
        "label": "왕융(王戎)",
        "description": "서진의 죽림칠현 중 한 명. 자는 준충(濬沖).",
        "references": []
      },
      "annotator": { "type": "llm", "model": "...", "draft_id": "..." },
      "status": "draft"
    }
  ]
}
```

- `target`: start/end로 원문 범위 지정 (0-based, inclusive)
- `type`: annotation_types.json에 정의된 유형 id
- `content.label`: 표제어 (표시용)
- `content.description`: 풀이/설명
- `content.references`: 출전/참고문헌 배열
- `annotator.type`: "llm" 또는 "human"
- `status`: "draft" → "reviewed" → "accepted"

### 주석 유형 관리

```json
// resources/annotation_types.json
{
  "types": [
    { "id": "person", "label": "인물", "color": "#4A90D9", "icon": "👤" },
    { "id": "place", "label": "지명", "color": "#67B76C", "icon": "📍" },
    { "id": "term", "label": "용어", "color": "#D4A843", "icon": "📖" },
    { "id": "allusion", "label": "전거", "color": "#C75B8E", "icon": "📜" },
    { "id": "note", "label": "메모", "color": "#999999", "icon": "📝" }
  ],
  "custom": []
}
```

사용자가 `custom`에 유형을 추가할 수 있다. 예: `{ "id": "sutra_ref", "label": "경전 참조", "color": "#...", "icon": "🙏" }`

### LLM 자동 태깅 흐름

```
1. 사용자가 [주석] 모드에서 [AI 태깅] 클릭
2. 해당 페이지(또는 블록)의 원문 전체를 LLM에 전송
3. LLM이 인물/지명/용어/전거를 식별하고 JSON으로 반환
4. 결과를 Draft 상태로 저장
5. 사용자가 각 주석을 검토/수정/삭제
6. 확정 시 status → "accepted", git commit
```

---

## 작업 순서

### 작업 1: L7 스키마 파일 생성

```
schemas/interp/annotation_page.schema.json
```

위의 데이터 모델을 JSON Schema로 정의한다.
- `type`은 enum으로 고정하지 않는다 (자유 문자열, annotation_types.json으로 검증)

테스트: 예시 JSON으로 검증 통과 확인.

커밋: `feat: L7 주석 JSON Schema 정의`

### 작업 2: 주석 유형 관리

```
resources/annotation_types.json
src/core/annotation_types.py
```

`annotation_types.py` 함수:

- `load_annotation_types(work_path) → dict`: 기본 프리셋 + 사용자 정의 로드
- `add_custom_type(work_path, type_def) → dict`: 사용자 정의 유형 추가
- `remove_custom_type(work_path, type_id) → dict`: 사용자 정의 유형 삭제
- `validate_type(work_path, type_id) → bool`: 유형 id가 유효한지 확인

커밋: `feat: 주석 유형 관리 (프리셋 + 사용자 정의)`

### 작업 3: 주석 코어 로직

```
src/core/annotation.py
```

구현할 함수:

- `load_annotations(work_path, interp_id, part_id, page_number) → dict`: L7 주석 파일 로드
- `save_annotations(work_path, interp_id, part_id, page_number, data) → None`: 스키마 검증 후 저장
- `add_annotation(data, block_id, annotation) → dict`: 주석 추가 (id 자동 생성)
- `update_annotation(data, block_id, annotation_id, updates) → dict`: 주석 수정
- `remove_annotation(data, block_id, annotation_id) → dict`: 주석 삭제
- `get_annotations_by_type(data, type_id) → list`: 특정 유형의 주석만 필터링
- `get_annotation_summary(data) → dict`: 유형별 개수, 상태별 개수

커밋: `feat: L7 주석 코어 로직`

### 작업 4: LLM 자동 태깅

```
src/llm/prompts/annotation.yaml
src/core/annotation_llm.py
```

태깅 프롬프트:

```yaml
id: annotation_classical_chinese_v1

system: |
  당신은 한문 고전 텍스트의 주석 전문가입니다.
  원문에서 인물, 지명, 용어, 전거(고사/출전)를 식별하고 주석을 달아주세요.

user_template: |
  다음 한문 원문의 주요 어휘에 주석을 달아주세요.
  
  원문: {original_text}
  {translation_section}
  
  각 주석에 대해 JSON 형식으로 응답하세요:
  {{"annotations": [
    {{
      "target": {{"start": 숫자, "end": 숫자}},
      "type": "person|place|term|allusion",
      "content": {{
        "label": "표제어",
        "description": "설명",
        "references": ["출전1", "출전2"]
      }}
    }}
  ]}}
```

`annotation_llm.py` 함수:

- `generate_annotation_draft(work_path, interp_id, part_id, page_number, block_ids=None) → list[LlmDraft]`
  - block_ids가 None이면 페이지 전체 원문
  - L4에서 원문 로드, L6 번역이 있으면 맥락으로 포함
  - LlmRouter.generate()로 태깅
  - JSON 파싱 후 스키마 검증
  - Draft 상태로 저장

- `commit_annotation_drafts(work_path, interp_id, part_id, page_number, draft_ids, modifications) → None`
  - 선택된 Draft만 확정 (전부 승인 / 개별 승인 / 개별 삭제)
  - annotation_page.json에 저장 + git commit

테스트: 蒙求 첫 구절로 LLM 태깅 테스트 (LLM 미연결 시 mock).

커밋: `feat: LLM 자동 주석 태깅`

### 작업 5: API 엔드포인트

```python
# src/api/annotation.py

# 주석 조회
GET /api/interpretations/{interp_id}/pages/{page}/annotations
  쿼리: ?type=person (선택적 필터)
  → 200: annotation_page.json 내용

# 주석 요약
GET /api/interpretations/{interp_id}/pages/{page}/annotations/summary
  → 200: { "by_type": {"person": 3, "place": 1, ...}, "by_status": {"draft": 2, "accepted": 2} }

# 수동 주석 추가
POST /api/interpretations/{interp_id}/pages/{page}/annotations/{block_id}
  입력: { "target": {...}, "type": "person", "content": {...} }
  → 201: 생성된 주석 (annotator.type = "human", status = "accepted")

# 주석 수정
PUT /api/interpretations/{interp_id}/pages/{page}/annotations/{block_id}/{ann_id}
  → 200

# 주석 삭제
DELETE /api/interpretations/{interp_id}/pages/{page}/annotations/{block_id}/{ann_id}
  → 204

# LLM 자동 태깅
POST /api/interpretations/{interp_id}/pages/{page}/annotations/llm-tag
  입력: { "block_ids": null }  (null = 페이지 전체)
  → 200: { "drafts": [...] }

# Draft 개별 승인
POST /api/interpretations/{interp_id}/pages/{page}/annotations/{block_id}/{ann_id}/commit
  → 200

# Draft 일괄 승인
POST /api/interpretations/{interp_id}/pages/{page}/annotations/commit-all
  → 200

# 주석 유형 관리
GET /api/annotation-types → 200: 전체 유형 목록
POST /api/annotation-types → 201: 사용자 정의 유형 추가
DELETE /api/annotation-types/{type_id} → 204: 사용자 정의 유형 삭제
```

커밋: `feat: L7 주석 API 엔드포인트`

### 작업 6: GUI — 주석 편집기

작업 모드 탭에 [주석] 추가:

```
[열람] [레이아웃] [교정] [표점] [현토] [번역] [주석]
                                                │
    ┌───────────────────────────────────────────┴───────────────────────────────────────────┐
    │ 상단: 원문 표시 (주석이 달린 어휘에 색상 하이라이팅)                                    │
    │   "👤王戎簡要👤裴楷清通"                                                               │
    │                                                                                       │
    │ 좌측: 주석 목록                                                                        │
    │   ┌─────────────────────────────────────┐                                             │
    │   │ 👤 왕융(王戎) [accepted]             │                                             │
    │   │ 서진의 죽림칠현 중 한 명...          │                                             │
    │   ├─────────────────────────────────────┤                                             │
    │   │ 👤 배해(裴楷) [draft]               │                                             │
    │   │ 서진의 관료. 자는 숙칙...            │                                             │
    │   └─────────────────────────────────────┘                                             │
    │                                                                                       │
    │ 우측: 주석 편집 패널 (선택 시)                                                          │
    │   유형: [person ▼]  상태: [draft ▼]                                                   │
    │   표제어: [왕융(王戎)      ]                                                           │
    │   설명:  [서진의 죽림칠현...  ]                                                        │
    │   참고:  [+ 참고문헌 추가]                                                             │
    │   [✅ 승인] [🗑 삭제]                                                                  │
    │                                                                                       │
    │ 하단: [AI 태깅] [전체 승인] [유형 관리] [저장]                                          │
    └───────────────────────────────────────────────────────────────────────────────────────┘
```

구현 사항:
- 원문의 주석 범위에 유형별 색상 하이라이팅
- 텍스트 범위 선택 → 수동 주석 추가 팝업
- [AI 태깅] → 페이지 전체 LLM 태깅 → Draft 목록 표시
- 각 Draft에 대해 개별 승인/수정/삭제
- [유형 관리] → 사용자 정의 유형 추가/삭제 다이얼로그
- 주석 목록은 유형별 필터링 가능

커밋: `feat: L7 주석 편집기 GUI`

### 작업 7: 통합 테스트

테스트 시나리오 (蒙求 첫 구절):

1. [주석] 모드 진입
2. [AI 태깅] → "王戎"(인물), "裴楷"(인물) 등이 자동 식별되는지 확인
3. Draft 목록에서 개별 승인/수정 테스트
4. 수동 주석 추가: "簡要"(용어)에 "간결하고 핵심적임" 주석
5. 사용자 정의 유형 추가 테스트
6. annotation_page.json 저장 + git commit 확인
7. 유형별 필터링 동작 확인

커밋: `test: L7 주석 통합 테스트`

---

## 완료 체크리스트

- [ ] schemas/interp/annotation_page.schema.json 생성
- [ ] resources/annotation_types.json — 기본 프리셋 5종
- [ ] src/core/annotation_types.py — 유형 관리
- [ ] src/core/annotation.py — 주석 CRUD + 필터링 + 요약
- [ ] src/llm/prompts/annotation.yaml — 태깅 프롬프트
- [ ] src/core/annotation_llm.py — LLM 자동 태깅
- [ ] src/api/annotation.py — 주석 API 엔드포인트
- [ ] GUI에 [주석] 모드 탭 + 주석 편집기
- [ ] 사용자 정의 유형 관리 UI
- [ ] 통합 테스트 통과

---

## ⏸️ 이번 Phase에서 구현하지 않는 것

- 외부 사전/DB 연동 (한국고전종합DB, CBETA 등) — Phase 12 이후
- 주석 간 상호 참조 (같은 인물이 여러 곳에 등장할 때 연결) — 향후
- 용어집 자동 구축 (주석 누적 → 용어집) — 향후

---

## ⏭️ 다음 세션: Phase 12-1 — Git 그래프 완전판

```
이 세션(11-3)이 완료되면 Phase 11 전체가 완료된다.

11-3에서 만든 것:
  ✅ L7 주석 스키마 + 코어 로직 + API + GUI
  ✅ 사용자 정의 주석 유형
  ✅ LLM 자동 태깅

다음 세션은 Phase 12-1 — Git 그래프 완전판.
Phase 9 결과물을 확인한 후 세션 문서를 작성할 것.

세션 문서: phase12_1_git_graph_session.md (작성 예정)
```
