# 蒙求 워크스루 — 전체 파이프라인 통합 테스트

## 개요

더미 蒙求 PDF를 사용하여 서고 생성 → 문헌 등록 → 텍스트 입력/교정 → 해석 저장소 → 엔티티 관리 → 의존 감지까지 전체 파이프라인을 API로 실행한 기록.

## Step 1-2: 서고 생성 + 문서 등록

```python
from core.library import init_library
init_library('examples/monggu_library')

from core.document import add_document
add_document('examples/monggu_library', title='蒙求', doc_id='monggu', files=['examples/dummy_monggu.pdf'])
```

결과: `examples/monggu_library/documents/monggu/` 생성, L1_source에 PDF 복사, git init + 최초 커밋.

## Step 3: 워크스페이스에서 열기

```bash
cd src && uv run python -m app serve --library ../examples/monggu_library --port 8765
```

API 확인: `GET /api/documents` → `[{"document_id": "monggu", "title": "蒙求", ...}]`

## Step 4: 서지정보 수집 (NDL)

- `POST /api/parsers/ndl/search` `{"query": "蒙求"}` → 10건 (관련 논문/서적)
- NDL은 일본 도서관이라 중국 고전 蒙求 자체는 직접 나오지 않음
- `PUT /api/documents/monggu/bibliography` 수동 입력:
  - title: 蒙求, creator: 李翰(李瀨), period: 唐
  - contributors: 徐子光 (annotator, 南宋)
  - language: classical_chinese

결과 파일: [step4_bibliography_saved.json](step4_bibliography_saved.json)

## Step 5: 레이아웃 편집

`PUT /api/documents/monggu/pages/1/layout?part_id=vol1`:

| block_id | block_type | reading_order | 설명 |
|----------|-----------|--------------|------|
| p01_b01 | main_text | 0 | 본문 영역 |
| p01_b02 | annotation | 1 | 주석 영역 (refers_to: p01_b01) |

결과 파일: [step5_layout_page1.json](step5_layout_page1.json)

## Step 6: 텍스트 수동 입력 + 교정

본문 입력 (의도적 오자 포함):
```
王戎簡要
裴楷清通
孔明臥龍
呂望非態
楊震關西
丁寛巨鹿   ← 寛(오자)
```

교정 기록:
- type: variant_char
- original_ocr: 寬 → corrected: 寒
- 이유: 字形誤認. 丁寒は巨鹿の人.
- git auto-commit: `4cadeaa L4: page 001 교정`

## Step 7: 해석 저장소 생성

```
POST /api/interpretations
{
  "interp_id": "monggu_interp_001",
  "source_document_id": "monggu",
  "interpreter_type": "human",
  "interpreter_name": "walkthrough_user",
  "title": "蒙求 解釈 v1"
}
```

## Step 8: TextBlock + Tag + Agent + Relation 생성

### 엔티티 요약

| 유형 | 수량 | 예시 |
|------|------|------|
| Work | 1 | 蒙求 (auto-create from bibliography) |
| TextBlock | 1 | 王戎簡要 裴楷清通... (source_ref 자동 채움) |
| Tag | 10 | 王戎(person), 裴楷(person), 關西(place), 巨鹿(place) 등 |
| Concept | 2 | 王戎 (Tag에서 승격, description 추가) |
| Agent | 2 | 王戎(西晉), 裴楷(西晉) |
| Relation | 1 | 王戎 →described_as→ 簡要 |

### Tag → Concept 승격

王戎 태그를 Concept으로 승격:
- tag status: draft → (승격 후 내부적으로 변경 없음, 별도 concept 생성)
- concept: label=王戎, description="西晉の人。簡要で知られる。"

결과 파일: [step8_summary.json](step8_summary.json)

## Step 9: 의존 감지 확인

1. 원본 저장소에서 page 1 텍스트 수정 (페이지 말미 추가)
2. `GET /api/interpretations/monggu_interp_001/dependency` 확인

```json
{
  "dependency_status": "outdated",
  "changed_files": 1,
  "changed_count": 1,
  "tracked_files": [
    {"path": "L4_text/pages/vol1_page_001.txt", "status": "changed"}
  ]
}
```

의존 변경 감지 성공.

결과 파일: [step9_dependency.json](step9_dependency.json)

## Step 10: Git 이력 확인

### 원본 저장소 (monggu)
```
a86144b L4: page 001 페이지 말미 추가
387e63d L4: page 002 텍스트 입력
4cadeaa L4: page 001 교정 — variant_char 1건
784325d L4: page 001 교정 — variant_char 1건
4bd3255 feat: 문헌 등록 — 蒙求
```

### 해석 저장소 (monggu_interp_001)
```
9ea071f feat: tag 엔티티 생성 — f1388fb0
75881ce feat: tag 엔티티 생성 — e0c08d55
5465fe0 feat: tag 엔티티 생성 — b51b2e69
a847e19 feat: relation 엔티티 생성 — 0d9717cc
0647c4f feat: agent 엔티티 생성 — b41d1fe1
509b1bb feat: agent 엔티티 생성 — 103c6116
f9dc17b feat: tag 엔티티 생성 — 732d3ff0
c538c0c feat: TextBlock 생성 — page 001 p01_b01
aa84f1f feat: Work 자동 생성 — 蒙求
f0ab4e6 feat: 해석 저장소 생성 — 蒙求 解釈 v1
```

결과 파일: [step10_git_log.json](step10_git_log.json)

## 결론

10단계 파이프라인이 모두 정상 동작 확인됨:
- 서고/문헌/해석 저장소 CRUD
- 레이아웃(L3) / 텍스트(L4) / 교정(L4) 저장
- 서지정보 NDL 검색 + 매핑 + 수동 저장
- 코어 스키마 엔티티 6종 생성 (Phase 8)
- Tag → Concept 승격 (Promotion Flow)
- 의존 감지 (원본 변경 → 해석 저장소 outdated)
- 양쪽 저장소 Git 자동 커밋
