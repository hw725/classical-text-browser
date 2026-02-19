# Phase 12 상세 설계: Git 그래프 (12-1) + JSON 스냅샷 (12-3)

> 작성일: 2026-02-16  
> 사전 조건: Phase 11 완료 (L5-L7 스키마 확정)  
> 12-2(데스크톱 래핑)는 당분간 웹 앱 유지, 향후 Tauri 전환  
> 12-3은 JSON 스냅샷에 집중, CSV·합성텍스트·TEI XML은 이후 구현

---

## 12-1: Git 그래프 완전판

### 1. 개요

Phase 9의 간략 타임라인을 **원본⇔해석 사다리형 이분 그래프(ladder bipartite graph)**로 확장한다.

```
  원본 저장소 (L1~L4)          해석 저장소 (L5~L7)
  ──────────────────          ──────────────────
  ● abc123                    
  │ "L4: 3장 확정텍스트"       
  │                     ╌╌╌╌→ ● def456
  │                            │ "L5: 3장 표점"
  ● 789fed                     │
  │ "L3: OCR 재처리"           │
  │                     ╌╌╌╌→ ● aaa111
  │                            │ "L6: 3장 번역"
  ● ...                        ● ...
```

왼쪽 레인에 원본 저장소 커밋, 오른쪽 레인에 해석 저장소 커밋이 시간순으로 나란히 표시되고, 의존 관계를 가로 점선으로 연결한다.

### 2. 핵심 결정사항

| 항목 | 결정 | 근거 |
|------|------|------|
| 렌더링 엔진 | **d3.js (SVG)** | SVG 노드에 클릭·툴팁 부착 용이, 커밋 수가 수천 단위 아님 |
| 레이아웃 | **고정 2레인 + 시간축** | d3-force 불필요, 시간 기반 Y좌표가 더 직관적 |
| 커밋 매칭 | **`Based-On-Original` trailer** | Git-native, 명시적, 파싱 용이 |
| 브랜치 | **단일 브랜치 뷰 + 드롭다운** | 초기 버전 복잡도 통제 |
| Phase 9 관계 | **간략 뷰(Phase 9) ↔ 상세 뷰(12-1) 토글** | 동일 영역에서 전환 |


### 3. 커밋 매칭 메커니즘

#### 문제
해석 저장소의 커밋이 원본 저장소의 **어떤 시점**을 기반으로 작업했는지 추적해야 사다리 가로선을 정확히 그릴 수 있다.

#### 해결: Git Commit Trailer

Phase 11 구현 시, L5~L7 커밋을 생성할 때 **원본 저장소의 현재 HEAD hash를 commit trailer로 자동 기록**한다.

```
L5: 3장 표점 작업 완료

Based-On-Original: abc123def456789fed...
```

**왜 trailer인가:**
- Git 표준 관행 (`Signed-off-by`, `Co-authored-by`와 같은 패턴)
- `git log --format="%(trailers:key=Based-On-Original)"` 로 바로 파싱 가능
- 별도 메타데이터 파일 관리 불필요
- 커밋 자체에 정보가 내장되어 히스토리 추적에 유리

**trailer가 없는 커밋 (레거시/수동 커밋):**
- 타임스탬프 기반 추정으로 fallback
- UI에서 추정 연결은 점선, 명시적 연결은 실선으로 구분

#### 백엔드 구현 포인트 (Phase 11)

```python
# 해석 저장소 커밋 시 자동으로 trailer 추가
def commit_interpretation(work_id, message, layers_affected):
    # 1. 원본 저장소의 현재 HEAD 가져오기
    original_head = get_original_repo_head(work_id)
    
    # 2. trailer 포함 커밋 메시지 생성
    full_message = f"{message}\n\nBased-On-Original: {original_head}"
    
    # 3. 해석 저장소에 커밋
    interp_repo.commit(full_message, layers_affected)
```


### 4. API 설계

#### 엔드포인트

```
GET /api/work/{work_id}/git-graph
```

#### Query Parameters

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `original_branch` | string | `"main"` | 원본 저장소 브랜치 |
| `interp_branch` | string | `"main"` | 해석 저장소 브랜치 |
| `limit` | int | `50` | 각 저장소별 최대 커밋 수 |
| `offset` | int | `0` | 페이지네이션 오프셋 |

#### 응답 구조

```json
{
  "original": {
    "repo_type": "original",
    "branch": "main",
    "branches_available": ["main", "review-kimjs"],
    "commits": [
      {
        "hash": "abc123def456...",
        "short_hash": "abc123d",
        "message": "L4: 3장 확정텍스트 수정",
        "author": "researcher-a",
        "timestamp": "2026-02-15T10:30:00Z",
        "layers_affected": ["L4"],
        "tags": ["v1.0"]
      }
    ]
  },
  "interpretation": {
    "repo_type": "interpretation",
    "branch": "main",
    "branches_available": ["main", "experiment-punctuation"],
    "commits": [
      {
        "hash": "def456aaa111...",
        "short_hash": "def456a",
        "message": "L5: 3장 표점 작업",
        "author": "researcher-a",
        "timestamp": "2026-02-15T11:00:00Z",
        "layers_affected": ["L5_punctuation"],
        "base_original_hash": "abc123def456...",
        "base_match_type": "explicit",
        "tags": []
      }
    ]
  },
  "links": [
    {
      "original_hash": "abc123def456...",
      "interp_hash": "def456aaa111...",
      "match_type": "explicit",
      "direction": "based_on"
    }
  ],
  "pagination": {
    "total_original": 120,
    "total_interpretation": 85,
    "offset": 0,
    "limit": 50,
    "has_more": true
  }
}
```

#### `match_type` 값

| 값 | 의미 | UI 표현 |
|----|------|---------|
| `"explicit"` | `Based-On-Original` trailer 존재 | **실선** 가로연결 |
| `"estimated"` | 타임스탬프 기반 추정 | **점선** 가로연결 |

#### `layers_affected` 가능 값

원본 저장소: `"L1"`, `"L2"`, `"L3"`, `"L4"`  
해석 저장소: `"L5_punctuation"`, `"L5_hyeonto"`, `"L6"`, `"L7"`


### 5. 시각화 레이아웃

#### 좌표 시스템

```
X축: 고정 2레인
  - 원본 레인: x = 150px (중앙 기준 왼쪽)
  - 해석 레인: x = 450px (중앙 기준 오른쪽)
  - 레인 간 간격: 300px (가로선 시인성 확보)

Y축: 시간 기반
  - 최신 커밋이 위 (y=0 근처)
  - 과거로 갈수록 y 증가
  - 커밋 간 최소 간격: 50px
  - 시간 간격 압축: 24시간 이상 차이는 로그 스케일로 압축
```

#### 노드 디자인

```
원본 커밋 노드:
  ● 원형 (r=8)
  색상: 레이어별 구분
    L1 → #94a3b8 (slate)
    L2 → #60a5fa (blue)
    L3 → #818cf8 (indigo)
    L4 → #2563eb (blue-dark, 가장 빈번하므로 강조)

해석 커밋 노드:
  ● 원형 (r=8)
  색상: 레이어별 구분
    L5_punctuation → #34d399 (emerald)
    L5_hyeonto    → #10b981 (green)
    L6            → #f59e0b (amber)
    L7            → #f97316 (orange)

복수 레이어 영향 커밋:
  ● 원형에 작은 컬러 도트들을 반원 배치
```

#### 가로 연결선

```
explicit (명시적):  ─────────→  실선, 색상 #64748b, 화살표
estimated (추정):   ╌╌╌╌╌╌╌╌→  점선, 색상 #94a3b8, 화살표
```

#### 세로 연결선 (같은 레인 내)

```
일반 커밋 간:  │  실선, 색상 #e2e8f0
브랜치 있을 때: (향후 확장)
```


### 6. 인터랙션 설계

#### 6-1. 커밋 노드 호버 → 툴팁

```
┌─────────────────────────────┐
│ abc123d                      │
│ L4: 3장 확정텍스트 수정        │
│ researcher-a                 │
│ 2026-02-15 10:30             │
│ 영향 레이어: L4               │
│ ────────────────────         │
│ → 연결된 해석 커밋: 2개        │
└─────────────────────────────┘
```

#### 6-2. 커밋 노드 클릭 → 상세 패널

오른쪽 사이드 패널 또는 하단 패널에 표시:
- 커밋 전체 메시지
- 변경된 파일 목록 (diff stat)
- 연결된 상대 저장소 커밋 목록 (클릭으로 이동)
- "이 커밋으로 복원" 버튼 (Phase 9 연동)

#### 6-3. 가로선 호버 → 관계 하이라이트

- 호버된 가로선과 양쪽 커밋 노드가 하이라이트
- 나머지 요소는 opacity 감소 (0.3)

#### 6-4. 스크롤 & 페이지네이션

- 마우스 휠로 Y축 스크롤 (과거 커밋 탐색)
- 하단 도달 시 자동으로 다음 페이지 로드 (infinite scroll)
- 또는 "더 보기" 버튼

#### 6-5. Phase 9 간략 뷰 토글

```
┌─────────────────────────────────────┐
│  [간략 타임라인]  [상세 Git 그래프]   │  ← 탭 전환
│─────────────────────────────────────│
│  (선택된 뷰 렌더링)                   │
└─────────────────────────────────────┘
```


### 7. 프론트엔드 컴포넌트 구조

```
GitGraphPanel/
├── GitGraphPanel.jsx          // 최상위 컨테이너 (탭 전환 포함)
├── LadderGraph.jsx            // d3.js SVG 렌더링 메인 컴포넌트
├── CommitNode.jsx             // 개별 커밋 노드 (호버/클릭)
├── LinkLine.jsx               // 가로 연결선 렌더링
├── CommitTooltip.jsx          // 호버 툴팁
├── CommitDetailPanel.jsx      // 클릭 시 상세 패널
├── BranchSelector.jsx         // 브랜치 드롭다운 (원본/해석 각각)
├── graphLayout.js             // Y좌표 계산, 시간축 압축 로직
└── graphColors.js             // 레이어별 색상 상수
```


### 8. 구현 순서

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 1 | 커밋 trailer 자동 기록 로직 | Phase 11 커밋 함수에 `Based-On-Original` 추가 |
| 2 | Git 로그 파싱 API | `GET /api/work/{id}/git-graph` 엔드포인트 |
| 3 | 레이아웃 계산 모듈 | `graphLayout.js` — 시간축 Y좌표 + 링크 매칭 |
| 4 | d3.js SVG 렌더링 | `LadderGraph.jsx` — 노드, 세로선, 가로선 |
| 5 | 인터랙션 | 툴팁, 클릭 상세, 하이라이트 |
| 6 | Phase 9 통합 | 간략/상세 탭 전환 |
| 7 | 페이지네이션 | infinite scroll 또는 "더 보기" |

커밋: `feat: Phase 12-1 — Git 그래프 완전판`

---

## 12-3: JSON 스냅샷 (집중 범위)

> CSV, 합성 텍스트, TEI XML은 이후 구현으로 유보

### 1. 개요

Work 전체 데이터의 현재 HEAD 상태를 하나의 JSON 파일로 직렬화(export)하고, 역직렬화(import)하는 기능. 백업, 복원, 다른 환경으로의 이동에 사용한다.

### 2. 포함 범위

| 포함 | 제외 |
|------|------|
| L1~L4 원본 텍스트 데이터 | Git 히스토리 (용량 + 충돌 문제) |
| L5 표점 데이터 | Git 설정 (.gitconfig 등) |
| L5 현토 데이터 | 캐시/임시 파일 |
| L6 번역 데이터 | LLM 작업 로그 |
| L7 주석 데이터 | |
| 이체자 사전 (사용자 등록분) | |
| annotation_types.json (사용자 정의 주석 유형) | |
| Work 메타데이터 (제목, 생성일 등) | |

### 3. JSON 스키마

```json
{
  "schema_version": "1.0",
  "export_timestamp": "2026-02-16T14:30:00Z",
  "platform_version": "0.1.0",
  
  "work": {
    "id": "work_001",
    "title": "論語集註",
    "created_at": "2026-01-10T09:00:00Z",
    "description": "논어집주 학이편"
  },

  "original": {
    "current_branch": "main",
    "head_hash": "abc123def456...",
    "layers": {
      "L1_raw_image": {
        "type": "reference",
        "note": "이미지 파일은 별도 관리. 경로 목록만 포함.",
        "files": [
          { "path": "pages/001.jpg", "page_number": 1 },
          { "path": "pages/002.jpg", "page_number": 2 }
        ]
      },
      "L2_raw_text": {
        "type": "inline",
        "pages": [
          {
            "page_number": 1,
            "text": "學而時習之不亦說乎..."
          }
        ]
      },
      "L3_ocr_corrected": {
        "type": "inline",
        "pages": [
          {
            "page_number": 1,
            "text": "學而時習之不亦說乎...",
            "corrections": [
              {
                "position": 15,
                "original": "読",
                "corrected": "說",
                "note": "OCR 오인식 교정"
              }
            ]
          }
        ]
      },
      "L4_confirmed": {
        "type": "inline",
        "sentences": [
          {
            "id": "s001",
            "text": "學而時習之",
            "page_number": 1,
            "simple_punctuation": "。",
            "original_punctuation": null,
            "original_hyeonto": null
          },
          {
            "id": "s002",
            "text": "不亦說乎",
            "page_number": 1,
            "simple_punctuation": "。",
            "original_punctuation": null,
            "original_hyeonto": null
          }
        ]
      }
    }
  },

  "interpretation": {
    "current_branch": "main",
    "head_hash": "def456aaa111...",
    "base_original_hash": "abc123def456...",
    "layers": {
      "L5_punctuation": [
        {
          "sentence_id": "s001",
          "marks": [
            {
              "char_index": 4,
              "position": "after",
              "mark": "，"
            }
          ]
        }
      ],
      "L5_hyeonto": [
        {
          "sentence_id": "s001",
          "annotations": [
            {
              "start_char": 0,
              "end_char": 0,
              "position": "after",
              "text": "ᄒᆞᆫ"
            },
            {
              "start_char": 2,
              "end_char": 2,
              "position": "after", 
              "text": "에"
            }
          ]
        }
      ],
      "L6_translation": [
        {
          "sentence_id": "s001",
          "translation": "배우고 때때로 익히면",
          "translator": "researcher-a",
          "method": "manual"
        }
      ],
      "L7_annotations": [
        {
          "sentence_id": "s001",
          "annotations": [
            {
              "id": "ann001",
              "type": "term",
              "target_text": "學",
              "char_start": 0,
              "char_end": 0,
              "content": "배우다. 본받다.",
              "tags": ["유학용어"]
            }
          ]
        }
      ]
    }
  },

  "variant_characters": {
    "entries": [
      {
        "standard": "說",
        "variants": ["読", "悅"],
        "note": "說 = 기쁘다(悅)의 의미로 사용"
      }
    ]
  },

  "annotation_types": [
    {
      "id": "person",
      "label": "인물",
      "color": "#ef4444",
      "description": "역사적 인물 표기"
    },
    {
      "id": "place",
      "label": "지명",
      "color": "#3b82f6",
      "description": "지명 표기"
    },
    {
      "id": "term",
      "label": "용어",
      "color": "#8b5cf6",
      "description": "전문 용어 주석"
    },
    {
      "id": "allusion",
      "label": "전고",
      "color": "#f59e0b",
      "description": "인용·전거 표기"
    },
    {
      "id": "note",
      "label": "비고",
      "color": "#6b7280",
      "description": "일반 메모"
    }
  ]
}
```

### 4. 핵심 설계 포인트

#### 4-1. `schema_version` 필드 (필수)

모든 JSON 스냅샷에 `"schema_version": "1.0"`을 포함한다. 향후 스키마 변경 시:

```python
def import_snapshot(data):
    version = data.get("schema_version", "0.0")
    
    if version == "1.0":
        return import_v1(data)
    elif version == "1.1":
        return import_v1_1(data)  # 마이그레이션 포함
    else:
        raise UnsupportedVersionError(f"지원하지 않는 스키마 버전: {version}")
```

#### 4-2. L1 이미지 처리

이미지 파일은 JSON에 직접 포함하지 않고 **경로 참조**만 기록한다.

- Export 시: 파일 경로 목록만 JSON에 포함
- 별도 옵션: "이미지 포함 Export" → ZIP 파일로 JSON + 이미지 묶음
- Import 시: 이미지 경로가 실제 존재하는지 검증, 없으면 경고

#### 4-3. 해석 저장소의 `base_original_hash`

JSON 스냅샷에도 "이 해석 데이터가 어떤 원본 시점에 기반했는지"를 기록한다. Import 시 원본 저장소의 HEAD와 비교하여 불일치 시 경고를 표시할 수 있다.

#### 4-4. Import 충돌 처리 전략

```
Import 모드:
  1. "새 Work로 생성" — 항상 안전, 기존 데이터 영향 없음
  2. "기존 Work에 덮어쓰기" — 확인 다이얼로그 필수
  3. "기존 Work에 병합" — (향후) 레이어별 선택 병합
```

초기 구현은 **모드 1만 지원**한다. 모드 2, 3은 사용 패턴을 보고 추가.


### 5. API 설계

#### Export

```
GET /api/work/{work_id}/export/json
```

Query Parameters:
| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `include_images` | bool | `false` | true면 ZIP으로 반환 |
| `branch` | string | `"main"` | 스냅샷 대상 브랜치 |

응답:
- `include_images=false` → `application/json` (JSON 파일 다운로드)
- `include_images=true` → `application/zip` (JSON + images/ 폴더)

#### Import

```
POST /api/work/import/json
Content-Type: multipart/form-data

Body:
  file: snapshot.json (또는 snapshot.zip)
  mode: "new"  // 초기에는 "new"만 지원
```

응답:
```json
{
  "status": "success",
  "work_id": "work_002",
  "summary": {
    "title": "論語集註",
    "layers_imported": ["L1", "L2", "L3", "L4", "L5", "L6", "L7"],
    "sentences_count": 245,
    "annotations_count": 89,
    "warnings": [
      "L1 이미지 3개 중 1개 파일 경로 확인 불가: pages/003.jpg"
    ]
  }
}
```


### 6. Import 검증 체크리스트

```python
def validate_snapshot(data):
    errors = []
    warnings = []
    
    # 1. 필수 필드 확인
    if "schema_version" not in data:
        errors.append("schema_version 필드 누락")
    
    # 2. 버전 호환성
    if data.get("schema_version") not in SUPPORTED_VERSIONS:
        errors.append(f"지원하지 않는 버전: {data['schema_version']}")
    
    # 3. sentence_id 참조 무결성
    #    L5, L6, L7의 sentence_id가 L4에 존재하는지
    l4_ids = {s["id"] for s in data["original"]["layers"]["L4_confirmed"]["sentences"]}
    for layer in ["L5_punctuation", "L5_hyeonto", "L6_translation", "L7_annotations"]:
        for item in data["interpretation"]["layers"].get(layer, []):
            if item["sentence_id"] not in l4_ids:
                warnings.append(f"{layer}의 sentence_id '{item['sentence_id']}'가 L4에 없음")
    
    # 4. annotation_types 참조 무결성
    #    L7 주석의 type이 annotation_types에 정의되어 있는지
    defined_types = {t["id"] for t in data.get("annotation_types", [])}
    for ann_group in data["interpretation"]["layers"].get("L7_annotations", []):
        for ann in ann_group.get("annotations", []):
            if ann["type"] not in defined_types:
                warnings.append(f"L7 주석 type '{ann['type']}'이 annotation_types에 미정의")
    
    return errors, warnings
```


### 7. 구현 순서

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 1 | JSON 스키마 확정 + 검증 함수 | `schemas/snapshot_v1.py` |
| 2 | Export API | `GET /api/work/{id}/export/json` |
| 3 | Import 검증 + 생성 | `POST /api/work/import/json` |
| 4 | GUI 버튼 연결 | Work 설정 메뉴에 내보내기/가져오기 |
| 5 | ZIP 포함 옵션 | 이미지 포함 export/import |

커밋: `feat: Phase 12-3 — JSON 스냅샷 export/import`

---

## 미결 사항 (Phase 11 완료 후 확인)

| 항목 | 관련 Phase | 상태 |
|------|------------|------|
| L5 표점·현토 분리 스키마 최종 확인 | 11 → 12-3 | Phase 11 확정 대기 |
| L4 `simple_punctuation` 필드 존재 여부 | 11 → 12-3 | Phase 11 확정 대기 |
| 커밋 trailer 파싱 성능 (대량 커밋 시) | 11 → 12-1 | 구현 후 벤치마크 |
| Phase 9 타임라인 컴포넌트 재사용 범위 | 9 → 12-1 | Phase 9 코드 리뷰 후 결정 |
