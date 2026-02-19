# 아키텍처 다이어그램

> Mermaid 문법으로 작성. GitHub, VSCode(Mermaid 확장), 또는 [Mermaid Live Editor](https://mermaid.live)에서 렌더링 가능.

---

## 1. 8층 데이터 모델

원본 저장소(L1~L4)와 해석 저장소(L5~L8)의 구조 및 의존 관계.

```mermaid
flowchart TB
  subgraph source["원본 저장소 (L1~L4) — 정답이 있는 층"]
    L1["L1 이미지/PDF<br>(불변 원본)"]
    L2["L2 OCR 결과<br>(글자·좌표·신뢰도)"]
    L3["L3 레이아웃<br>(본문/주석/서문 구분)"]
    L4["L4 교정 텍스트<br>(사람 확정본)"]
    L1 --> L2 --> L3 --> L4
  end

  subgraph interp["해석 저장소 (L5~L8) — 다수 해석 병존"]
    L5["L5 표점·현토<br>(句讀, 懸吐)"]
    L6["L6 번역<br>(현대어, 다국어)"]
    L7["L7 주석<br>(인물·사건·전거)"]
    L8["L8 외부연계<br>(DB, API)"]
    L5 --> L6 --> L7 --> L8
  end

  L4 ==>|저장소 경계| L5

  style source fill:#e8f4e8,stroke:#2d6a2d
  style interp fill:#e8e8f4,stroke:#2d2d6a
```

**핵심 원칙:**
- 원본 저장소는 **단일 정본**으로 수렴 (정답이 있다)
- 해석 저장소는 **다수 병존** (해석은 연구자마다 다르다)
- L4 확정 → 해석 저장소의 시작점 (저장소 경계)

---

## 2. 사용자 워크플로우 (UI 탭 기반)

탭 순서대로의 작업 흐름. 원본 작업(초록) → 해석 작업(보라) → 교차 뷰어(빨강).

```mermaid
flowchart LR
  subgraph source["원본 저장소 작업"]
    direction TB
    A["1. 열람\n(PDF/이미지 뷰어)"]
    B["2. 레이아웃\n(영역 자동감지 + 편집)"]
    C["3. 교정\n(OCR→텍스트 교정)"]
    D["4. 편성\n(LayoutBlock→TextBlock)"]
  end

  subgraph interp["해석 저장소 작업"]
    direction TB
    E["5. 표점\n(句讀 삽입)"]
    F["6. 현토\n(懸吐 달기)"]
    G["7. 번역\n(LLM draft→교정)"]
    H["8. 주석\n(인물·사건 태깅)"]
  end

  I["9. 교차 뷰어\n(L5~L7 통합 열람)"]

  A --> B --> C --> D
  D --> E --> F --> G --> H
  H --> I

  style source fill:#e8f4e8,stroke:#2d6a2d
  style interp fill:#e8e8f4,stroke:#2d2d6a
  style I fill:#f4e8e8,stroke:#6a2d2d
```

**LLM 협업 패턴:** LLM이 draft → 사람이 review → 사람이 commit (2~8층 공통)

---

## 3. 시스템 아키텍처

프론트엔드, 백엔드, 저장소, 외부 서비스의 연결 구조.

```mermaid
flowchart TB
  subgraph ui["프론트엔드 (vanilla JS)"]
    viewer["PDF.js 뷰어"]
    tabs["모드 탭<br>(열람~교차 뷰어)"]
    sidebar["사이드바<br>(문헌·권·페이지)"]
  end

  subgraph backend["백엔드 (FastAPI)"]
    api["REST API"]
    subgraph engines["처리 엔진"]
      ocr["OCR<br>(LLM Vision + PaddleOCR)"]
      llm["LLM 라우터<br>(5 providers)"]
      hwp["HWP/HWPX<br>(텍스트 추출)"]
      schema["스키마 검증<br>(jsonschema)"]
    end
  end

  subgraph storage["Git 저장소 (로컬)"]
    srcrepo["원본 저장소<br>(L1~L4)"]
    intrepo["해석 저장소<br>(L5~L8)"]
  end

  subgraph external["외부 서비스 (온라인)"]
    providers["Gemini / OpenAI / Anthropic<br>Ollama / Base44"]
    remote["Git 원격<br>(GitHub 등)"]
  end

  ui <--> api
  api <--> engines
  api <--> storage
  llm <-.-> providers
  storage <-.->|push/pull| remote

  style ui fill:#fff3e0,stroke:#e65100
  style backend fill:#e3f2fd,stroke:#1565c0
  style storage fill:#e8f5e9,stroke:#2e7d32
  style external fill:#fce4ec,stroke:#c62828
```

**역할 분리:**
- **Git**: 저장, 이력, 버전, diff → 이미 있는 인프라
- **앱**: 관계, 의미, 경고, UI → 만들어야 할 것
- **원격 호스팅**: 백업, 동기화 → 교체 가능

---

## 4. 코어 스키마 엔티티 관계 (해석 저장소)

해석 저장소 내부의 엔티티 모델 (core-schema-v1.3).

```mermaid
erDiagram
  Work ||--o{ TextBlock : contains
  TextBlock ||--o{ Tag : "has tags"
  Tag }o--o| Concept : "promotes to"
  Agent }o--o{ Relation : "subject/object"
  Concept }o--o{ Relation : "subject/object"
  TextBlock }o--o{ Relation : "evidence"

  Work {
    string id PK
    string title
    string author
    string period
  }

  TextBlock {
    string id PK
    string work_id FK
    int sequence_index
    string original_text
    string normalized_text
  }

  Tag {
    string id PK
    string block_id FK
    string surface
    string core_category
    float confidence
    string extractor
  }

  Concept {
    string id PK
    string label
    string scope_work
    string description
    json concept_features
  }

  Agent {
    string id PK
    string name
    string period
    string biography_note
  }

  Relation {
    string id PK
    string subject_id
    string subject_type
    string predicate
    string object_id
    string object_type
  }
```

**설계 보장:**
- 구조(Structure) ≠ 해석(Interpretation) — 코어는 구조만 저장
- 온톨로지 잠금 없음 — Concept는 자유 확장
- Tag → Concept 승격은 연구자 판단 (선택적)
- Predicate는 snake_case, 구조적 행위만 (해석 배제)

---

## 5. 층별 의존 관계

하위 층 변경이 상위 층에 미치는 영향.

```mermaid
flowchart LR
  subgraph source["원본 저장소"]
    s1["L1 변경"] -.->|거의 없음| s2["L2"]
    s2 -->|OCR 재실행| s3["L3"]
    s3 -->|레이아웃 재분류| s4["L4"]
  end

  subgraph boundary["저장소 경계"]
    s4 ==>|모든 해석에 경고| i5
  end

  subgraph interp["해석 저장소"]
    i5["L5"] -->|표점 변경| i6["L6"]
    i6 -->|번역 변경| i7["L7"]
    i7 -->|주석 변경| i8["L8"]
  end

  style source fill:#e8f4e8,stroke:#2d6a2d
  style interp fill:#e8e8f4,stroke:#2d2d6a
```
