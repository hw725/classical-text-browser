# Phase 12-3: JSON 스냅샷 Export/Import

> Claude Code 세션 지시문
> 이 문서를 읽고 작업 순서대로 구현하라.

---

## 사전 준비

1. CLAUDE.md를 먼저 읽어라.
2. docs/DECISIONS.md를 읽어라.
3. docs/phase11_12_design_decisions.md를 읽어라.
4. **docs/phase12_design.md를 읽어라** — 12-3 JSON 스키마 상세 설계가 정의되어 있다.
5. 이 문서 전체를 읽은 후 작업을 시작하라.
6. 기존 코드 구조를 먼저 파악하라: `src/core/`, `src/api/`, `schemas/`.
7. **L5 표점/현토, L6 번역, L7 주석의 실제 스키마 파일을 확인하라** — JSON 스냅샷이 이들을 정확히 직렬화해야 한다.

---

## 설계 요약 — 반드시 이해한 후 구현

### 핵심 원칙

- **현재 HEAD 스냅샷만**: Git 히스토리는 제외. 용량 + 복원 시 충돌 방지.
- **`schema_version` 필수**: 모든 스냅샷에 `"schema_version": "1.0"` 포함. 향후 마이그레이션용.
- **L1 이미지는 경로 참조만**: 기본 Export에 이미지 바이너리 미포함. ZIP 옵션은 별도.
- **Import는 "새 Work 생성"만**: 덮어쓰기/병합은 향후 구현.

### 포함 범위

| 포함 | 제외 |
|------|------|
| L1~L4 원본 데이터 | Git 히스토리 |
| L5 표점 + 현토 | .git 설정 |
| L6 번역 | 캐시/임시 파일 |
| L7 주석 | LLM 작업 로그 |
| 이체자 사전 (사용자 등록분) | |
| annotation_types.json | |
| Work 메타데이터 | |

---

## 작업 1: JSON 스냅샷 스키마 정의

### 파일

`schemas/snapshot_v1.py` (Pydantic 모델 또는 JSON Schema)

### 스키마 구조

기존 프로젝트에서 스키마를 어떻게 정의하고 있는지 확인하라 (Pydantic, JSON Schema 파일, 또는 dataclass). 같은 방식으로 작성하라.

### 최상위 구조

```json
{
  "schema_version": "1.0",
  "export_timestamp": "ISO 8601",
  "platform_version": "프로젝트 버전",
  
  "work": { ... },
  "original": { ... },
  "interpretation": { ... },
  "variant_characters": { ... },
  "annotation_types": [ ... ]
}
```

### work 섹션

```json
{
  "id": "work_001",
  "title": "論語集註",
  "created_at": "ISO 8601",
  "description": "설명 텍스트"
}
```

Work 모델이 이미 있을 것이다. 그 필드를 그대로 직렬화하라.

### original 섹션

```json
{
  "current_branch": "main",
  "head_hash": "커밋 해시",
  "layers": {
    "L1_raw_image": {
      "type": "reference",
      "files": [
        { "path": "pages/001.jpg", "page_number": 1 }
      ]
    },
    "L2_raw_text": {
      "type": "inline",
      "pages": [ { "page_number": 1, "text": "..." } ]
    },
    "L3_ocr_corrected": {
      "type": "inline",
      "pages": [
        {
          "page_number": 1,
          "text": "...",
          "corrections": [
            { "position": 15, "original": "読", "corrected": "說", "note": "..." }
          ]
        }
      ]
    },
    "L4_confirmed": {
      "type": "inline",
      "data": "... L4 파일의 실제 구조를 그대로 직렬화 ..."
    }
  }
}
```

**중요**: L1~L4의 실제 파일 구조를 먼저 확인하고, 그 구조를 그대로 JSON에 담아라. 위 예시는 참고용이다. 실제 프로젝트의 L4 데이터 구조(블록 기반인지, 페이지 기반인지 등)에 맞춰라.

### interpretation 섹션

```json
{
  "current_branch": "main",
  "head_hash": "커밋 해시",
  "base_original_hash": "원본 저장소 HEAD (이 해석이 기반한 원본 시점)",
  "layers": {
    "L5_punctuation": "... punctuation_page.json 구조 그대로 ...",
    "L5_hyeonto": "... hyeonto_page.json 구조 그대로 ...",
    "L6_translation": "... translation_page.json 구조 그대로 ...",
    "L7_annotations": "... annotation_page.json 구조 그대로 ..."
  }
}
```

**핵심**: 각 레이어의 JSON 파일을 읽어서 그대로 중첩시키면 된다. 별도 변환 없이.

### variant_characters 섹션

프로젝트에서 이체자 사전을 어떤 형식으로 저장하고 있는지 확인하고 그대로 포함하라. 비어 있으면 빈 객체/배열.

### annotation_types 섹션

`annotation_types.json` 파일의 내용을 그대로 포함.

커밋: `feat(schema): JSON 스냅샷 스키마 v1.0 정의`

---

## 작업 2: Export API

### 엔드포인트

```
GET /api/work/{work_id}/export/json
```

### Query Parameters

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `branch` | string | `"main"` | 스냅샷 대상 브랜치 |

### 구현

```python
# src/api/export.py

@router.get("/work/{work_id}/export/json")
async def export_json_snapshot(work_id: str, branch: str = "main"):
    """Work 전체를 JSON 스냅샷으로 내보내기."""
    
    work = get_work(work_id)
    if not work:
        raise HTTPException(404, "Work not found")
    
    snapshot = build_snapshot(work, branch)
    
    # JSON 파일로 다운로드
    filename = f"{work.title}_{datetime.now().strftime('%Y%m%d')}.json"
    return StreamingResponse(
        io.BytesIO(json.dumps(snapshot, ensure_ascii=False, indent=2).encode('utf-8')),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
```

### build_snapshot 함수

```python
# src/core/snapshot.py

def build_snapshot(work, branch: str) -> dict:
    """Work 데이터를 JSON 스냅샷 딕셔너리로 조립."""
    
    return {
        "schema_version": "1.0",
        "export_timestamp": datetime.utcnow().isoformat() + "Z",
        "platform_version": get_platform_version(),
        
        "work": serialize_work_metadata(work),
        "original": serialize_original_layers(work, branch),
        "interpretation": serialize_interpretation_layers(work, branch),
        "variant_characters": serialize_variant_chars(work),
        "annotation_types": serialize_annotation_types(work),
    }
```

### 각 serialize 함수

- `serialize_work_metadata`: Work 모델의 기본 정보 (id, title, created_at, description)
- `serialize_original_layers`: 원본 저장소의 L1~L4 파일을 읽어서 딕셔너리로
- `serialize_interpretation_layers`: 해석 저장소의 L5~L7 파일을 읽어서 딕셔너리로
- `serialize_variant_chars`: 이체자 사전 파일 읽기
- `serialize_annotation_types`: annotation_types.json 읽기

**각 함수는 해당 레이어의 실제 파일 구조를 반영해야 한다. 기존 코드에서 데이터를 어떻게 읽고 있는지 참고하라.**

### 파일 위치

- `src/api/export.py` — API 엔드포인트
- `src/core/snapshot.py` — 스냅샷 조립 로직

커밋: `feat(api): JSON 스냅샷 Export — GET /api/work/{id}/export/json`

---

## 작업 3: Import 검증 함수

### 파일

`src/core/snapshot_validator.py`

### 검증 항목

```python
def validate_snapshot(data: dict) -> tuple[list[str], list[str]]:
    """
    스냅샷 데이터 검증.
    
    Returns:
        (errors, warnings)
        errors: Import를 차단하는 심각한 문제
        warnings: Import는 가능하지만 주의가 필요한 사항
    """
    errors = []
    warnings = []
    
    # 1. 필수 필드
    if "schema_version" not in data:
        errors.append("schema_version 필드 누락")
        return errors, warnings  # 더 이상 검증 불가
    
    # 2. 버전 호환성
    supported = ["1.0"]
    if data["schema_version"] not in supported:
        errors.append(f"지원하지 않는 스키마 버전: {data['schema_version']}")
        return errors, warnings
    
    # 3. work 섹션 필수 필드
    work = data.get("work", {})
    if not work.get("title"):
        errors.append("work.title 누락")
    
    # 4. original 섹션 존재
    if "original" not in data:
        errors.append("original 섹션 누락")
    
    # 5. sentence/block ID 참조 무결성
    #    L5, L6, L7의 참조가 L4에 존재하는지 확인
    #    (실제 L4 구조에 맞춰 구현할 것)
    l4_ids = extract_l4_ids(data)
    
    for layer_name in ["L5_punctuation", "L5_hyeonto", "L6_translation", "L7_annotations"]:
        layer_data = data.get("interpretation", {}).get("layers", {}).get(layer_name, [])
        ref_ids = extract_reference_ids(layer_data, layer_name)
        orphans = ref_ids - l4_ids
        if orphans:
            warnings.append(
                f"{layer_name}에서 L4에 없는 ID 참조: {', '.join(list(orphans)[:5])}"
                + (f" 외 {len(orphans)-5}개" if len(orphans) > 5 else "")
            )
    
    # 6. annotation_types 참조 무결성
    defined_types = {t["id"] for t in data.get("annotation_types", [])}
    l7_data = data.get("interpretation", {}).get("layers", {}).get("L7_annotations", [])
    used_types = extract_annotation_types_used(l7_data)
    undefined = used_types - defined_types
    if undefined:
        warnings.append(f"L7 주석에서 미정의 유형 사용: {', '.join(undefined)}")
    
    return errors, warnings
```

### extract 헬퍼 함수들

실제 L4 데이터 구조에 맞춰 구현하라. block_id 기반인지 sentence_id 기반인지 확인 후 작성.

커밋: `feat(core): JSON 스냅샷 Import 검증`

---

## 작업 4: Import API

### 엔드포인트

```
POST /api/work/import/json
Content-Type: multipart/form-data
```

### Body

| 필드 | 타입 | 설명 |
|------|------|------|
| `file` | File | .json 파일 |

### 구현

```python
# src/api/import_.py  (import는 예약어이므로 import_)

@router.post("/work/import/json")
async def import_json_snapshot(file: UploadFile):
    """JSON 스냅샷에서 새 Work 생성."""
    
    # 1. 파일 읽기 + JSON 파싱
    content = await file.read()
    try:
        data = json.loads(content.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(400, f"JSON 파싱 실패: {e}")
    
    # 2. 검증
    errors, warnings = validate_snapshot(data)
    if errors:
        raise HTTPException(422, {
            "message": "스냅샷 검증 실패",
            "errors": errors,
            "warnings": warnings
        })
    
    # 3. 새 Work 생성
    work = create_work_from_snapshot(data)
    
    # 4. 응답
    return {
        "status": "success",
        "work_id": work.id,
        "summary": {
            "title": work.title,
            "layers_imported": detect_imported_layers(data),
            "warnings": warnings
        }
    }
```

### create_work_from_snapshot 함수

```python
# src/core/snapshot.py에 추가

def create_work_from_snapshot(data: dict):
    """스냅샷 데이터로 새 Work 생성."""
    
    # 1. Work 메타데이터 생성
    #    id는 새로 발급 (원본 id와 충돌 방지)
    work = create_new_work(
        title=data["work"]["title"],
        description=data["work"].get("description", "")
    )
    
    # 2. 원본 저장소 초기화 + L1~L4 데이터 쓰기
    write_original_layers(work, data["original"])
    
    # 3. 해석 저장소 초기화 + L5~L7 데이터 쓰기
    write_interpretation_layers(work, data["interpretation"])
    
    # 4. 이체자 사전 쓰기
    write_variant_chars(work, data.get("variant_characters", {}))
    
    # 5. annotation_types 쓰기
    write_annotation_types(work, data.get("annotation_types", []))
    
    # 6. 초기 커밋
    commit_original(work, "Import: 스냅샷에서 원본 데이터 복원")
    commit_interpretation(work, "Import: 스냅샷에서 해석 데이터 복원")
    
    return work
```

### 주의

- **새 Work ID 발급**: Import된 Work의 id는 원본과 다르게 새로 생성. 같은 스냅샷을 여러 번 import해도 충돌 없어야 한다.
- **Git 저장소 초기화**: 새 Work이므로 원본/해석 저장소를 새로 init한다.
- **이미지 파일 경고**: L1 이미지 경로가 실제 존재하지 않으면 warning에 추가하되 import는 중단하지 않는다.

커밋: `feat(api): JSON 스냅샷 Import — POST /api/work/import/json`

---

## 작업 5: GUI 연결

### Export 버튼

Work 설정 메뉴 또는 헤더 영역에 "내보내기(Export)" 버튼 추가.

```javascript
async function exportSnapshot(workId) {
    const response = await fetch(`/api/work/${workId}/export/json`);
    const blob = await response.blob();
    
    // 다운로드 트리거
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = response.headers.get('Content-Disposition')
        ?.match(/filename="(.+)"/)?.[1] || 'snapshot.json';
    a.click();
    URL.revokeObjectURL(url);
}
```

### Import 버튼

메인 화면(Work 목록)에 "가져오기(Import)" 버튼 추가.

```javascript
async function importSnapshot() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        
        const formData = new FormData();
        formData.append('file', file);
        
        const response = await fetch('/api/work/import/json', {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (result.status === 'success') {
            // 성공: Work 목록 갱신 + 알림
            showNotification(`"${result.summary.title}" 가져오기 완료`);
            if (result.summary.warnings.length > 0) {
                showWarnings(result.summary.warnings);
            }
            refreshWorkList();
        } else {
            // 실패: 에러 표시
            showErrors(result.errors);
        }
    };
    input.click();
}
```

### 버튼 위치

- Export: Work 내부 — 상단 메뉴 또는 설정(⚙️) 드롭다운
- Import: Work 목록 화면 — "새 Work" 버튼 옆에 "가져오기" 버튼

커밋: `feat(gui): JSON 스냅샷 내보내기/가져오기 버튼`

---

## 작업 6: 통합 테스트

### 테스트 시나리오

1. **Export 기본 테스트**:
   - 테스트 Work에 L4 + L5 표점 + L6 번역 + L7 주석 데이터 있는 상태
   - `GET /api/work/{id}/export/json` 호출
   - 응답 JSON에 `schema_version: "1.0"` 존재 확인
   - 모든 레이어 데이터 포함 확인

2. **Import 기본 테스트**:
   - Export한 JSON 파일로 `POST /api/work/import/json` 호출
   - 새 Work 생성 확인 (ID가 다름)
   - Import된 Work의 L4, L5, L6, L7 데이터가 원본과 동일한지 확인

3. **왕복(Round-trip) 테스트**:
   - Work A → Export → Import → Work B
   - Work A와 B의 텍스트 데이터 비교 → 동일해야 함
   - Work B에서 다시 Export → JSON 비교 (메타데이터 제외 동일)

4. **검증 테스트**:
   - `schema_version` 누락 JSON → 에러 반환 확인
   - 존재하지 않는 sentence_id 참조 → warning 반환 확인
   - 미정의 annotation type → warning 반환 확인

5. **빈 레이어 테스트**:
   - L4만 있고 L5~L7이 없는 Work → Export 성공
   - 해당 JSON Import → 성공, L5~L7은 빈 상태

커밋: `test: Phase 12-3 JSON 스냅샷 통합 테스트`

---

## 완료 체크리스트

- [ ] `schemas/snapshot_v1.py` — 스냅샷 스키마 정의
- [ ] `src/core/snapshot.py` — build_snapshot + create_work_from_snapshot
- [ ] `src/core/snapshot_validator.py` — validate_snapshot
- [ ] `src/api/export.py` — Export 엔드포인트
- [ ] `src/api/import_.py` — Import 엔드포인트
- [ ] GUI Export 버튼 (Work 내부)
- [ ] GUI Import 버튼 (Work 목록)
- [ ] 왕복(Round-trip) 테스트 통과
- [ ] 검증 테스트 통과

---

## 향후 확장 (이번 세션에서 구현하지 않음)

| 항목 | 우선순위 | 비고 |
|------|----------|------|
| ZIP Export (이미지 포함) | 중 | `include_images=true` 옵션 |
| Import 덮어쓰기 모드 | 낮 | 확인 다이얼로그 필수 |
| Import 병합 모드 | 낮 | 레이어별 선택 병합 |
| CSV Export | 중 | 별도 세션 |
| 합성 텍스트 Export | 중 | synthesis_rules.json 필요 |
| TEI XML | 낮 | 매핑 테이블 설계 선행 |
