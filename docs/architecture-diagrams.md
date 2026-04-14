# 아키텍처 다이어그램

> 2026-03-14 기준. Mermaid 문법으로 작성.
> GitHub, VSCode (Mermaid 확장), [Mermaid Live Editor](https://mermaid.live)에서 렌더링 가능.
>
> **구성**: 12개 다이어그램 — 데이터 모델(1-3), 시스템 아키텍처(4-5), 워크플로우(6-7), 스키마(8-9), 저장소(10-11), UI(12)

---

## 1. 8층 데이터 모델

원본 저장소(L1-L4, 단일 정본)와 해석 저장소(L5-L8, 다수 병존)의 구조.
저장소 경계에서 `dependency.json`이 변경을 추적한다.

```mermaid
flowchart TB
    subgraph SOURCE["원본 저장소 (L1-L4) -- 단일 정본, 정답이 있는 층"]
        direction LR
        L1["<b>L1 이미지/PDF</b><br/>불변 원본 · 수정 금지<br/><i>manifest · bibliography</i>"]
        L2["<b>L2 OCR 글자해독</b><br/>글자 + 좌표 + 신뢰도<br/><i>ocr_page</i>"]
        L3["<b>L3 레이아웃 분석</b><br/>본문/주석/서문 구분 · 읽기 순서<br/><i>layout_page (LayoutBlock)</i>"]
        L4["<b>L4 사람 수정</b><br/>OCR 교정 · 이체자 확인 · 확정본<br/><i>corrections</i>"]
        L1 --> L2 --> L3 --> L4
    end

    subgraph BOUNDARY["저장소 경계"]
        DEP["<b>dependency.json</b><br/>파일 해시 · 커밋 추적 · 변경 경고"]
    end

    subgraph INTERP["해석 저장소 (L5-L8) -- 다수 해석 병존, 정답 없음"]
        direction LR
        L5["<b>L5 표점 · 현토</b><br/>句讀 삽입 · 懸吐 달기<br/><i>punctuation_page · hyeonto_page</i>"]
        L6["<b>L6 번역</b><br/>현대어역 · 다국어<br/><i>translation_page</i>"]
        L7["<b>L7 주석 · 사전</b><br/>인물/지명 태깅 · 사전형 주석 · 인용마크<br/><i>annotation_page v2 · citation_mark_page</i>"]
        L8["<b>L8 외부연계</b><br/>DB · API · 학술 네트워크<br/><i>relation (코어)</i>"]
        L5 --> L6 --> L7 --> L8
    end

    subgraph CORE["코어 스키마 엔티티"]
        Work["Work"]
        TextBlock["TextBlock"]
        Tag["Tag"]
        PROMO["승격 (선택적)"]
        Concept["Concept"]
        Agent["Agent"]
        Relation["Relation"]
        Work --- TextBlock --- Tag
        Tag -.-> PROMO -.-> Concept
        Concept --- Relation
        Agent --- Relation
    end

    SOURCE --> BOUNDARY --> INTERP
    INTERP --- CORE

    style SOURCE fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style L1 fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style L2 fill:#e8f5e9,stroke:#2e7d32
    style L3 fill:#e8f5e9,stroke:#2e7d32
    style L4 fill:#e8f5e9,stroke:#2e7d32
    style BOUNDARY fill:#ffe0b2,stroke:#e65100,stroke-width:2px
    style DEP fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style INTERP fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    style L5 fill:#e3f2fd,stroke:#1565c0
    style L6 fill:#e3f2fd,stroke:#1565c0
    style L7 fill:#e3f2fd,stroke:#1565c0
    style L8 fill:#e3f2fd,stroke:#1565c0
    style CORE fill:#e1bee7,stroke:#6a2d6a,stroke-width:2px
    style Work fill:#fef3c7,stroke:#b45309
    style TextBlock fill:#fef3c7,stroke:#b45309
    style Tag fill:#fef3c7,stroke:#b45309
    style Concept fill:#fef3c7,stroke:#b45309
    style Agent fill:#fef3c7,stroke:#b45309
    style Relation fill:#fef3c7,stroke:#b45309
    style PROMO fill:#f3e5f5,stroke:#7b1fa2
```

**핵심 원칙:**
- 원본 저장소는 **단일 정본**으로 수렴 (정답이 있다)
- 해석 저장소는 **다수 병존** (해석은 연구자마다 다르다)
- L4 확정 → `dependency.json` → 해석 저장소 시작점 (저장소 경계)
- 코어 스키마 6개 엔티티(Work, TextBlock, Tag, Concept, Agent, Relation)는 해석 저장소 내부에 위치

---

## 2. 전체 시스템 아키텍처

프론트엔드(27개 JS 모듈) · 백엔드(FastAPI + 8 라우터) · 처리 엔진(OCR 5종 + LLM 4단) · Git 저장소 · 외부 서비스.

```mermaid
flowchart TB
    subgraph GIT["Git 저장소 (로컬)"]
        GIT_SRC["원본 저장소<br/>L1-L4"]
        GIT_INT["해석 저장소<br/>L5-L8 (다수)"]
        GIT_MAN["library_manifest.json<br/>서고 전체 지도"]
    end

    subgraph FE["프론트엔드 (Vanilla JS · 빌드 도구 없음)"]
        direction TB
        subgraph FE_CORE["코어 UI"]
            direction LR
            WS["workspace.js<br/>메인 오케스트레이션"]
            PDF["pdf-renderer.js<br/>PDF.js 뷰어"]
            TREE["sidebar-tree.js<br/>문헌/권/페이지 탐색"]
        end
        subgraph FE_SRC["원본 작업 (L1-L4)"]
            direction LR
            LE["layout-editor.js<br/>L3 영역 편집"]
            CE["correction-editor.js<br/>L4 텍스트 교정"]
            BC["batch-correction.js<br/>일괄 이체자 교정"]
        end
        subgraph FE_INT["해석 작업 (L5-L8)"]
            direction LR
            PE["punctuation-editor.js<br/>L5 표점"]
            HE["hyeonto-editor.js<br/>L5 현토"]
            TE["translation-editor.js<br/>L6 번역"]
            AE["annotation-editor.js<br/>L7 주석"]
            CIE["citation-editor.js<br/>L7 인용마크"]
        end
        subgraph FE_SUP["지원 모듈"]
            direction LR
            INTJS["interpretation.js"]
            ENT["entity-manager.js"]
            GG["git-graph.js"]
            OP["ocr-panel.js"]
            BIB["bibliography.js"]
            NP["notes-panel.js"]
            HWP["hwp-import.js"]
            AV["alignment-view.js"]
        end
    end

    FE <-->|"REST API"| BE

    subgraph BE["백엔드 (Python · FastAPI)"]
        direction TB
        SRV["server.py<br/>앱 생성 + 라우터 마운트 (~85줄)"]
        ST["_state.py<br/>공유 상태 · 헬퍼 · LLM/OCR 캐시"]
        subgraph ROUTERS["8개 도메인 라우터 (158 API)"]
            direction LR
            R1["library <b>15</b>"]
            R2["documents <b>32</b>"]
            R3["interpretations <b>22</b>"]
            R4["llm_ocr <b>13</b>"]
            R5["alignment <b>17</b>"]
            R6["reading <b>24</b>"]
            R7["annotation <b>32</b>"]
            R8["version <b>7</b>"]
        end
    end

    BE --> ENGINE

    subgraph ENGINE["처리 엔진"]
        direction LR
        subgraph OCR_ENG["OCR 엔진 (registry.py)"]
            O1["NDL古典籍OCR Full (TrOCR)"]
            O2["NDL古典籍OCR-Lite (ONNX)"]
            O3["NDLOCR-Lite"]
            O4["LLM Vision OCR"]
            O5["PaddleOCR"]
        end
        subgraph LLM_ENG["LLM 라우터 (router.py)"]
            LR1["1. Base44 HTTP"]
            LR2["2. Base44 Bridge"]
            LR3["3. Ollama 프록시"]
            LR4["4. 직접 API"]
        end
        subgraph ETC_ENG["기타"]
            JS_VAL["jsonschema 검증"]
            HWP_P["HWP/HWPX 파서"]
            BIB_P["서지 파서<br/>(NDL · KORCIS · Archives.JP)"]
        end
    end

    subgraph EXT["외부 서비스"]
        EXT_LLM["Gemini · OpenAI · Anthropic"]
        EXT_OLL["Ollama Server"]
        EXT_GIT["GitHub · GitLab<br/>(백업/동기화)"]
        EXT_BIB["NDL · KORCIS<br/>(서지 API)"]
    end

    ENGINE -.-> EXT

    style GIT fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style GIT_SRC fill:#fef3c7,stroke:#b45309
    style GIT_INT fill:#fef3c7,stroke:#b45309
    style FE fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style BE fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    style SRV fill:#fef3c7,stroke:#b45309
    style ST fill:#fef3c7,stroke:#b45309
    style ENGINE fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    style EXT fill:#fce4ec,stroke:#c62828,stroke-width:2px,stroke-dasharray: 5 5
    style EXT_LLM fill:#fef3c7,stroke:#b45309
```

**역할 분리:**
- **Git**: 저장, 이력, 버전, diff → 이미 있는 인프라
- **앱**: 관계, 의미, 경고, UI → 만들어야 할 것
- **원격 호스팅**: 백업, 동기화 → 교체 가능
- **오프라인 퍼스트**: 핵심 작업(교정, 열람, 커밋)은 인터넷 없이 완전히 동작

---

## 3. 코어 스키마 엔티티 관계 (ER Diagram)

해석 저장소 내부의 6개 엔티티 모델. core-schema-v1.3 기준.
모든 엔티티는 `draft → active → deprecated → archived` 상태 전이를 따른다 (삭제 금지).

```mermaid
flowchart TB
    subgraph SCHEMA["6개 엔티티 -- 해석 저장소 내부"]
        direction TB
        subgraph ROW1[" "]
            direction LR
            WORK["<b>Work</b><br/>id: UUID (PK)<br/>title: 원어 제목 (필수)<br/>author: 저자<br/>period: 시대<br/>status: draft|active|deprecated|archived<br/>metadata: 자유 확장 필드"]
            TB_NODE["<b>TextBlock</b><br/>id: UUID (PK)<br/>work_id: FK → Work<br/>sequence_index: 순서 (필수)<br/>original_text: 원문 (불변, 필수)<br/>normalized_text: 정규화<br/>source_ref: 출처 추적 JSON<br/>status: draft|active|..."]
            TAG["<b>Tag</b><br/>id: UUID (PK)<br/>block_id: FK → TextBlock<br/>surface: 표면 텍스트 (필수)<br/>core_category: person|place|...<br/>confidence: 신뢰도 0-1<br/>extractor: llm|rule|human<br/>status: draft|active|..."]
        end
        subgraph ROW2[" "]
            direction LR
            CONCEPT["<b>Concept</b><br/>id: UUID (PK)<br/>label: 대표 이름 (필수)<br/>scope_work: 범위 Work (선택)<br/>description: 학술 설명<br/>concept_features: 자유 확장<br/>status: draft|active|..."]
            AGENT["<b>Agent</b><br/>id: UUID (PK)<br/>name: 이름 (필수)<br/>period: 활동 시대<br/>biography_note: 약전<br/>status: draft|active|..."]
            RELATION["<b>Relation</b><br/>id: UUID (PK)<br/>subject_id / subject_type<br/>predicate: snake_case (필수)<br/>object_id / object_type<br/>object_value: 자유 텍스트<br/>evidence_blocks: TextBlock ID[]<br/>confidence / status"]
        end

        WORK -->|"contains"| TB_NODE
        TB_NODE -->|"has tags"| TAG
        TAG -.->|"승격"| CONCEPT
        AGENT -->|"subject/object"| RELATION
        CONCEPT -->|"subject/object"| RELATION
        TB_NODE -->|"evidence"| RELATION
    end

    style SCHEMA fill:#f3e5f5,stroke:#6a2d6a,stroke-width:2px
    style WORK fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style TB_NODE fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style TAG fill:#e3f2fd,stroke:#1565c0
    style CONCEPT fill:#e3f2fd,stroke:#1565c0
    style AGENT fill:#e3f2fd,stroke:#1565c0
    style RELATION fill:#e3f2fd,stroke:#1565c0
    style ROW1 fill:transparent,stroke:none
    style ROW2 fill:transparent,stroke:none
```

**설계 보장:**
- 구조(Structure) ≠ 해석(Interpretation) — 코어는 구조만 저장
- 온톨로지 잠금 없음 — Concept의 `concept_features`는 자유 확장
- Tag → Concept 승격은 연구자 판단 (선택적, Promotion Flow)
- Predicate는 snake_case, 구조적 행위만 (해석 배제)
- `source_ref`로 원본 저장소 역참조 (document_id + page + layout_block_id + git commit)

---

## 4. LLM 4단 폴백 아키텍처

전체 프로젝트 공용 LLM 연동. `src/llm/router.py`가 단일 진입점.
자동으로 1순위부터 시도, 실패 시 다음으로 폴백.

```mermaid
flowchart TB
    ENTRY["<b>src/llm/router.py</b><br/>LLMRouter -- 단일 진입점 · 자동 폴백"]

    ENTRY -->|"시도"| TIER1
    TIER1["<b>1순위: Base44 InvokeLLM (HTTP)</b><br/>localhost:8787/api/chat<br/>agent-chat 서버 경유 · 무료 · 이미지 분석 · MCP 도구"]
    TIER1 -->|"실패 시"| TIER2
    TIER2["<b>2순위: Base44 Bridge (Node.js)</b><br/>subprocess: node invoke.js<br/>backend-44 SDK 직접 호출 · 서버 없이 1회성 호출"]
    TIER2 -->|"실패 시"| TIER3

    subgraph TIER3_GROUP["3순위: Ollama (로컬 프록시)"]
        TIER3_MAIN["localhost:11434 -- 클라우드 모델 로컬 프록시"]
        TIER3_M1["Qwen3-VL"]
        TIER3_M2["Kimi-K2.5"]
        TIER3_M3["GLM-5"]
        TIER3_M4["Gemini-3-Flash"]
    end

    TIER3_GROUP -->|"실패 시"| TIER4

    subgraph TIER4_GROUP["4순위: 직접 API 호출"]
        direction LR
        T4_A["Anthropic<br/>Claude"]
        T4_B["OpenAI<br/>GPT"]
        T4_C["Google<br/>Gemini"]
    end

    subgraph CONSUMERS["LLM 소비자 (src/core/)"]
        direction LR
        C1["punctuation_llm.py<br/>L5 표점 초안"]
        C2["hyeonto.py<br/>L5 현토 초안"]
        C3["translation_llm.py<br/>L6 번역 초안"]
        C4["annotation_llm.py<br/>L7 주석 자동생성"]
        C5["annotation_dict_llm.py<br/>L7 사전 생성"]
        C6["draft.py<br/>범용 LLM 초안"]
    end

    CONSUMERS --> ENTRY

    subgraph CONFIG["설정 (config.py)"]
        CF1["환경변수"]
        CF2[".env 파일<br/>(프로젝트 · 서고)"]
        CF3["기본값"]
        CF1 --> CF2 --> CF3
    end

    subgraph USAGE["사용량 추적"]
        UT["usage_tracker.py<br/>토큰 · 비용 · 모델별 집계"]
    end

    style ENTRY fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style TIER1 fill:#e8f5e9,stroke:#2e7d32
    style TIER2 fill:#fff3e0,stroke:#e65100
    style TIER3_GROUP fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    style TIER3_MAIN fill:#f3e5f5,stroke:#7b1fa2
    style TIER4_GROUP fill:#fce4ec,stroke:#c62828,stroke-width:2px
    style CONSUMERS fill:#eceff1,stroke:#546e7a,stroke-width:2px
    style CONFIG fill:#e8f5e9,stroke:#2e7d32
    style CF1 fill:#fef3c7,stroke:#b45309
    style CF2 fill:#fef3c7,stroke:#b45309
    style CF3 fill:#fef3c7,stroke:#b45309
    style USAGE fill:#eceff1,stroke:#546e7a
```

**LLM 협업 패턴 (2-8층 공통):**
1. LLM이 draft 생성
2. 사람이 review
3. 사람이 commit (Git 자동 저장)

---

## 5. OCR 엔진 파이프라인

5개 OCR 엔진의 레지스트리 기반 자동 선택. LayoutBlock 단위로 이미지 크롭 → 전처리 → 인식 → 후처리.

```mermaid
flowchart LR
    subgraph INPUT["입력"]
        IN1["L1 이미지/PDF<br/>페이지 단위"]
        IN2["L3 LayoutBlock<br/>영역 · 읽기순서 · block_type"]
    end

    subgraph REGISTRY["OCR 레지스트리 (registry.py)"]
        REG["자동 등록<br/>우선순위 기반 선택<br/>엔진 불가시 폴백"]
    end

    subgraph ENGINES["OCR 엔진 (우선순위순)"]
        direction TB
        E1["<b>1.</b> NDL古典籍OCR Full<br/><i>TrOCR · RTMDet · GPU 권장</i>"]
        E2["<b>2.</b> NDL古典籍OCR-Lite<br/><i>ONNX 경량 · CPU 가능</i>"]
        E3["<b>3.</b> NDLOCR-Lite<br/><i>현대/인쇄 · ParseQ · DEIM</i>"]
        E4["<b>4.</b> LLM Vision OCR<br/><i>LLM 비전 모델 활용</i>"]
        E5["<b>5.</b> PaddleOCR<br/><i>다국어 · 멀티라인</i>"]
    end

    subgraph PIPELINE["파이프라인 (pipeline.py)"]
        direction TB
        P1["이미지 크롭<br/>(LayoutBlock bbox)"]
        P2["전처리<br/>(BGR/RGB · 리사이즈)"]
        P3["글자 인식<br/>(엔진별 추론)"]
        P4["후처리<br/>(신뢰도 필터 · 좌표 매핑)"]
        P1 --> P2 --> P3 --> P4
    end

    subgraph OUTPUT["출력"]
        OUT1["<b>L2 OcrResult</b><br/>ocr_page.json"]
        OUT2["OcrLine → OcrCharacter<br/>char · bbox · confidence"]
    end

    subgraph ORDERING["읽기 순서"]
        OR1["XY-Cut 알고리즘"]
        OR2["Smooth Ordering"]
        OR3["割注 블록 감지"]
    end

    INPUT --> REGISTRY --> ENGINES --> PIPELINE --> OUTPUT
    OUTPUT --- ORDERING

    style INPUT fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style REGISTRY fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style REG fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style ENGINES fill:#fce4ec,stroke:#c62828,stroke-width:2px
    style PIPELINE fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style OUTPUT fill:#fce4ec,stroke:#c62828,stroke-width:2px
    style OUT1 fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style ORDERING fill:#eceff1,stroke:#546e7a,stroke-width:2px
```

---

## 6. 사용자 워크플로우

연구자의 작업 흐름. 자료 수집 → 원본 작업(L1-L4) → 해석 작업(L5-L8) → 관리.

```mermaid
flowchart TB
    subgraph PHASE1["Phase 1: 자료 수집"]
        direction LR
        P1A["문헌 가져오기<br/>PDF/이미지 업로드 · HWP 임포트"]
        P1B["서지정보 파싱<br/>NDL · KORCIS · Archives.JP"]
    end

    PHASE1 -->|"↓"| PHASE2

    subgraph PHASE2["Phase 2: 원본 작업 (L1-L4)"]
        direction LR
        P2A["열람<br/>PDF.js 뷰어<br/>이미지 확대/축소"]
        P2B["레이아웃 분석<br/>영역 자동감지 (LLM)<br/>수동 편집 · 읽기순서"]
        P2C["OCR 실행<br/>엔진 선택<br/>블록별 인식"]
        P2D["교정<br/>OCR→텍스트 대조<br/>이체자 확인 · 확정"]
        P2E["편성<br/>LayoutBlock→TextBlock<br/>source_ref 추적"]
        P2A --> P2B --> P2C --> P2D --> P2E
    end

    PHASE2 ==>|"저장소 경계"| PHASE3

    subgraph PHASE3["Phase 3: 해석 작업 (L5-L8)"]
        direction LR
        P3A["표점 (L5)<br/>句讀 삽입<br/>글자 인덱스 기반"]
        P3B["현토 (L5)<br/>懸吐 달기<br/>after/before/over/under"]
        P3C["번역 (L6)<br/>LLM draft→사람 review<br/>사전 참조 · 주석 컨텍스트"]
        P3D["주석 (L7)<br/>4단계 사전 생성<br/>인물/지명 자동태깅"]
        P3E["인용마크 (L7)<br/>학술 인용 구절 지정<br/>교차 레이어 해소"]
        P3A --> P3B --> P3C --> P3D --> P3E
    end

    PHASE3 --> PHASE4

    subgraph PHASE4["Phase 4: 관리"]
        direction LR
        P4A["Git 이력<br/>커밋 · diff · 되돌리기"]
        P4B["스냅샷<br/>JSON 내보내기/가져오기"]
        P4C["이체자 정렬<br/>일괄 교정"]
        P4D["이체자 사전<br/>variant_chars.json"]
    end

    subgraph LLM_PATTERN["LLM 협업 패턴 (2-8층 공통)"]
        direction TB
        LP1["LLM이 draft 생성"]
        LP2["사람이 review"]
        LP3["사람이 commit<br/>(Git 자동 저장)"]
        LP1 --> LP2 --> LP3
    end

    style PHASE1 fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style PHASE2 fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style PHASE3 fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    style PHASE4 fill:#eceff1,stroke:#546e7a,stroke-width:2px
    style LLM_PATTERN fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style LP1 fill:#fef3c7,stroke:#b45309
    style LP2 fill:#fef3c7,stroke:#b45309
    style LP3 fill:#fef3c7,stroke:#b45309
```

---

## 7. 스키마 간 참조 관계도

19개 스키마(원본 7 + 해석 5 + 코어 6 + 교환 1)의 연결 구조.
화살표는 참조 방향: A → B = "A가 B를 참조".

```mermaid
flowchart TB
    subgraph SRC_SCHEMA["원본 저장소 스키마 (7개)"]
        direction TB
        S_MAN["<b>manifest</b><br/><i>document_id, parts, completeness_status</i>"]
        S_BIB["<b>bibliography</b><br/><i>서지정보, raw_metadata, _mapping_info</i>"]
        S_OCR["<b>ocr_page</b><br/><i>OcrResult · char, bbox, confidence</i>"]
        S_LAY["<b>layout_page</b><br/><i>LayoutBlock · block_id, bbox, reading_order</i>"]
        S_COR["<b>corrections</b><br/><i>Correction · type, original_ocr, corrected</i>"]
        S_IMP["<b>interp_manifest</b><br/><i>interpretation_id, source_document_id</i>"]
        S_DEP["<b>dependency</b><br/><i>source.base_commit, tracked_files, status</i>"]
    end

    subgraph INT_SCHEMA["해석 저장소 스키마 (5개)"]
        direction TB
        I_PUN["<b>punctuation_page</b><br/><i>block_id, marks, target, before/after</i>"]
        I_HYE["<b>hyeonto_page</b><br/><i>block_id, annotations, position, text</i>"]
        I_TRA["<b>translation_page</b><br/><i>source, translations, status, annotation_context</i>"]
        I_ANN["<b>annotation_page v2</b><br/><i>blocks, annotations, dictionary, generation_history</i>"]
        I_CIT["<b>citation_mark_page</b><br/><i>marks, source, marked_from, citation_override</i>"]
    end

    subgraph CORE_SCHEMA["코어 스키마 (6개)"]
        direction TB
        C_WOR["<b>Work</b><br/><i>title, author, period</i>"]
        C_TB["<b>TextBlock</b><br/><i>work_id, original_text, source_ref</i>"]
        C_TAG["<b>Tag</b><br/><i>block_id, surface, core_category</i>"]
        C_CON["<b>Concept</b><br/><i>label, concept_features</i>"]
        C_AGE["<b>Agent</b><br/><i>name, period</i>"]
        C_REL["<b>Relation</b><br/><i>subject, predicate, object, evidence_blocks</i>"]
    end

    subgraph EXCHANGE["교환 형식 (1개)"]
        EX["<b>exchange</b><br/><i>단일 JSON 스냅샷 · 내보내기/가져오기</i>"]
    end

    S_LAY --> S_MAN
    S_OCR --> S_MAN
    S_OCR --> S_LAY
    S_COR --> S_LAY
    S_IMP --> S_MAN
    S_DEP --> S_MAN
    I_PUN --> S_LAY
    I_HYE --> S_LAY
    I_TRA --> S_LAY
    I_ANN --> S_LAY
    I_CIT --> S_LAY
    I_TRA <-->|"annotation_context"| I_ANN
    C_TB --> C_WOR
    C_TAG --> C_TB
    C_TAG -.->|"승격"| C_CON
    C_REL --> C_AGE
    C_REL --> C_CON
    C_REL --> C_TB
    C_TB -.->|"source_ref 역참조"| S_MAN

    style SRC_SCHEMA fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style S_MAN fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style INT_SCHEMA fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    style CORE_SCHEMA fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    style EXCHANGE fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style EX fill:#fef3c7,stroke:#b45309,stroke-width:2px
```

**참조 패턴 요약:**
- 원본 내부: `layout_page/ocr_page` → `manifest`, `ocr_page/corrections` → `layout_page`
- 저장소 간: `interp_manifest/dependency` → `manifest` (document_id + base_commit)
- 해석→원본: 모든 해석 스키마 → `layout_page` (block_id로 연결)
- 해석 내부: `translation_page` ↔ `annotation_page` (annotation_context)
- 코어→원본: `TextBlock.source_ref` → `manifest` (역참조)

---

## 8. 백엔드 모듈 의존 구조

`server.py`(조립) → 8개 라우터 → `_state.py`(공유 상태) → core/llm/ocr 모듈.
라우터 간 직접 import 금지. `_state.py`가 lazy import로 순환 방지.

```mermaid
flowchart TB
    subgraph APP["src/app/ -- API 레이어"]
        direction TB
        MAIN["__main__.py<br/>CLI 진입점"]
        SRV["<b>server.py</b><br/>FastAPI 앱 생성 · 라우터 마운트"]
        STATE["<b>_state.py</b><br/>공유 상태, 헬퍼 · LLM 캐시, 토큰 계산"]
        subgraph ROUTERS["routers/ -- 8개 도메인"]
            direction LR
            R1["library <b>15</b>"]
            R2["documents <b>32</b>"]
            R3["interpretations <b>22</b>"]
            R4["llm_ocr <b>13</b>"]
            R5["alignment <b>17</b>"]
            R6["reading <b>24</b>"]
            R7["annotation <b>32</b>"]
            R8["version <b>7</b>"]
        end
        MAIN --> SRV --> ROUTERS --> STATE
    end

    APP -->|"lazy import"| CORE_MOD
    APP -->|"lazy import"| LLM_MOD
    APP -->|"lazy import"| OCR_MOD

    subgraph CORE_MOD["src/core/ -- 비즈니스 로직"]
        direction TB
        CM1["library"]
        CM2["document"]
        CM3["interpretation"]
        CM4["entity"]
        CM5["punctuation / punctuation_llm"]
        CM6["hyeonto"]
        CM7["translation / translation_llm"]
        CM8["annotation / annotation_llm<br/>annotation_dict_llm / annotation_dict_match"]
        CM9["citation_mark"]
        CM10["alignment"]
        CM11["git_graph"]
        CM12["snapshot / snapshot_validator"]
        CM13["backup"]
        CM14["layout_analyzer"]
    end

    subgraph LLM_MOD["src/llm/ -- LLM 통합"]
        direction TB
        LM1["<b>router.py -- 4단 폴백</b>"]
        LM2["config.py"]
        LM3["draft.py"]
        LM4["usage_tracker.py"]
        subgraph PROVIDERS["providers/"]
            LP1["base44_bridge"]
            LP2["ollama"]
            LP3["openai"]
            LP4["anthropic"]
            LP5["gemini"]
        end
    end

    subgraph OCR_MOD["src/ocr/ -- OCR 엔진"]
        direction TB
        OM1["registry.py"]
        OM2["pipeline.py"]
        OM3["ndlkotenocr_full"]
        OM4["ndlkotenocr_lite"]
        OM5["ndlocr_lite"]
        OM6["llm_ocr"]
        OM7["paddleocr"]
    end

    subgraph MISC["기타 모듈"]
        direction TB
        MI1["src/parsers/<br/>ndl, korcis, archives_jp"]
        MI2["src/hwp/<br/>reader, text_cleaner"]
        MI3["src/text_import/<br/>pdf_extractor"]
        MI4["src/cli/"]
    end

    CORE_MOD --> LLM_MOD
    CORE_MOD --> OCR_MOD

    style APP fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style SRV fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style STATE fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style CORE_MOD fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style LLM_MOD fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style LM1 fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style OCR_MOD fill:#fce4ec,stroke:#c62828,stroke-width:2px
    style MISC fill:#eceff1,stroke:#546e7a,stroke-width:2px
```

**규칙:**
- 라우터 간 직접 import 금지 → 공유 로직은 `_state.py`에 배치
- `_state.py`는 core/llm/ocr 모듈을 lazy import (순환 방지)
- Pydantic 모델은 사용하는 라우터 파일 내부에 정의

---

## 9. Git 저장소 모델

하나의 원본 저장소 위에 여러 해석 저장소가 독립 Git 리포로 병존.
`library_manifest.json`이 서고 전체 지도 역할.

```mermaid
flowchart TB
    subgraph LIBRARY["서고 (library_manifest.json)"]
        LIB["<b>library_manifest.json</b><br/>서고 전체 지도 · 문헌 목록, 해석 목록"]
    end

    subgraph SRC_REPO["원본 저장소 (Git repo)"]
        direction TB
        SR_MAN["manifest.json<br/>document_id, parts"]
        SR_L1["<b>L1_source/</b><br/>PDF, 이미지 (불변)"]
        SR_L2["L2_ocr/<br/>ocr_page JSON"]
        SR_L3["L3_layout/<br/>layout_page JSON"]
        SR_L4["L4_text/<br/>corrections JSON"]
        SR_BIB["bibliography.json"]
        SR_GIT["Git 이력: commit, diff, log"]
    end

    subgraph REMOTE["원격 호스팅 (선택)"]
        REM["GitHub / GitLab / Gitea<br/>← push/pull →"]
    end

    subgraph INTERP_A["해석 A (연구자 김, Git repo)"]
        direction TB
        IA_MAN["interp_manifest.json -- interpreter: 김"]
        IA_DEP["<b>dependency.json -- base_commit 추적</b>"]
        IA_L5["L5/<br/>punctuation, hyeonto"]
        IA_L6["L6/<br/>translation"]
        IA_L7["L7/<br/>annotation, citation"]
        IA_CORE["core/ -- Work, TextBlock, Tag, Concept, Agent, Relation"]
    end

    subgraph INTERP_B["해석 B (LLM draft, Git repo)"]
        direction TB
        IB_MAN["interp_manifest.json -- interpreter: LLM"]
        IB_DEP["dependency.json"]
        IB_L5["L5/"]
        IB_L6["L6/ LLM 번역"]
    end

    subgraph INTERP_C["해석 C (공동연구, Git repo)"]
        direction TB
        IC_MAN["interp_manifest.json -- interpreter: 팀"]
        IC_DEP["dependency.json"]
        IC_L5["L5/"]
        IC_L6["L6/"]
        IC_L7["L7/"]
    end

    LIBRARY --> SRC_REPO
    LIBRARY --> INTERP_A
    LIBRARY --> INTERP_B
    LIBRARY --> INTERP_C
    IA_DEP -.->|"base_commit"| SRC_REPO
    IB_DEP -.->|"base_commit"| SRC_REPO
    IC_DEP -.->|"base_commit"| SRC_REPO
    SRC_REPO <-->|"push/pull"| REMOTE

    style LIBRARY fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style LIB fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style SRC_REPO fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style SR_L1 fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style REMOTE fill:#eceff1,stroke:#546e7a,stroke-width:2px,stroke-dasharray: 5 5
    style INTERP_A fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    style IA_DEP fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style INTERP_B fill:#e8eaf6,stroke:#3f51b5
    style INTERP_C fill:#ede7f6,stroke:#5e35b1
    style IA_CORE fill:#f3e5f5,stroke:#7b1fa2
```

---

## 10. 층별 의존 관계

하위층 변경이 상위층에 미치는 영향. `dependency.json`의 `dependency_status` 상태 전이.

```mermaid
flowchart LR
    subgraph SRC_DEP["원본 저장소 내부"]
        direction TB
        D_L1["L1 이미지 (불변)"]
        D_L2["L2 OCR"]
        D_L3["L3 레이아웃"]
        D_L4["L4 교정"]
        D_L1 -->|"거의 없음"| D_L2
        D_L2 -->|"OCR 재실행 필요"| D_L3
        D_L3 -->|"블록 재분류 필요"| D_L4
    end

    subgraph BOUNDARY_DEP["저장소 경계"]
        direction TB
        BD["<b>경고 발생</b><br/>dependency.json<br/>tracked_files hash 비교"]
        BD_NOTE["모든 해석에 경고 전파"]
    end

    subgraph INT_DEP["해석 저장소 내부"]
        direction TB
        I_L5["L5 표점/현토"]
        I_L6["L6 번역"]
        I_L7["L7 주석"]
        I_L8["L8 외부연계"]
        I_L5 -->|"표점 변경시 번역 재검토"| I_L6
        I_L6 -->|"번역 변경시 주석 재검토"| I_L7
        I_L7 -->|"주석 변경시"| I_L8
    end

    subgraph STATUS["dependency_status 상태"]
        direction TB
        ST_SYNC["<b>synced</b><br/>일치"]
        ST_STALE["<b>stale</b><br/>변경 감지"]
        ST_ACK["<b>acknowledged</b><br/>확인 완료"]
        ST_SYNC -->|"변경 발생"| ST_STALE
        ST_STALE -->|"확인"| ST_ACK
        ST_ACK -->|"다시 synced"| ST_SYNC
    end

    SRC_DEP ==> BOUNDARY_DEP ==> INT_DEP

    style SRC_DEP fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style BOUNDARY_DEP fill:#ffe0b2,stroke:#e65100,stroke-width:2px
    style BD fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style INT_DEP fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    style STATUS fill:#eceff1,stroke:#546e7a,stroke-width:2px
    style ST_SYNC fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style ST_STALE fill:#fce4ec,stroke:#c62828
    style ST_ACK fill:#fff3e0,stroke:#e65100
```

---

## 11. 프론트엔드 UI 구조

VSCode 스타일 3패널 레이아웃. 왼쪽(탐색) · 가운데(PDF 뷰어) · 오른쪽(작업 탭).

```mermaid
flowchart TB
    subgraph LAYOUT["VSCode 스타일 3패널 레이아웃"]
        direction LR
        subgraph LEFT["왼쪽: 액티비티 바 + 사이드바"]
            direction TB
            ACT["액티비티 바<br/>8개 패널 전환"]
            SIDE_TREE["sidebar-tree.js<br/>문헌 목록 · 권/페이지 트리"]
            SIDE_INT["interpretation.js<br/>해석 저장소 목록 · 생성/선택/삭제"]
        end
        subgraph CENTER["가운데: PDF/이미지 뷰어"]
            direction TB
            PDF_R["<b>pdf-renderer.js</b><br/>PDF.js 통합 · 확대/축소/회전"]
            LAY_E["layout-editor.js<br/>LayoutBlock 오버레이 · 영역 편집/읽기순서"]
        end
        subgraph RIGHT["오른쪽: 작업 패널 (탭 전환)"]
            direction TB
            TAB1["교정 탭 -- correction-editor.js<br/>OCR vs 교정 텍스트"]
            TAB2["표점 탭 -- punctuation-editor.js<br/>구두점 삽입"]
            TAB3["현토 탭 -- hyeonto-editor.js<br/>懸吐 달기"]
            TAB4["번역 탭 -- translation-editor.js<br/>LLM draft + 편집"]
            TAB5["주석 탭 -- annotation-editor.js<br/>사전형 주석 + 태깅"]
            TAB6["인용 탭 -- citation-editor.js<br/>학술 인용 마크"]
            TAB7["비고 탭 -- notes-panel.js<br/>페이지별 메모"]
        end
    end

    subgraph BOTTOM["하단/팝업"]
        direction LR
        BT1["toast.js<br/>알림"]
        BT2["ocr-panel.js<br/>OCR 엔진 선택/실행"]
        BT3["git-graph.js<br/>커밋 이력/diff"]
        BT4["bibliography.js<br/>서지정보 편집"]
        BT5["alignment-view.js<br/>이체자 정렬"]
        BT6["entity-manager.js<br/>코어 엔티티 관리"]
        BT7["hwp-import.js<br/>HWP 가져오기"]
        BT8["batch-correction.js<br/>일괄 교정"]
    end

    style LAYOUT fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style LEFT fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style CENTER fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style PDF_R fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style RIGHT fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    style BOTTOM fill:#eceff1,stroke:#546e7a,stroke-width:2px
```

---

## 12. L7 주석 4단계 누적 생성 워크플로우

annotation_page v2의 4단계 `current_stage` 전이. 각 단계마다 `generation_history`에 스냅샷 저장.

```mermaid
flowchart TB
    subgraph STAGE1["Stage 1: from_original"]
        direction LR
        S1A["L4 교정 텍스트<br/>(원문)"]
        S1B["<b>LLM 분석</b><br/>인물/지명/용어 추출"]
        S1C["기본 주석 생성<br/>type, label, description"]
        S1A --> S1B --> S1C
    end

    STAGE1 -->|"Stage 1 스냅샷 저장"| STAGE2

    subgraph STAGE2["Stage 2: from_translation"]
        direction LR
        S2A["L6 번역문<br/>(현대어)"]
        S2B["<b>LLM 보강</b><br/>번역 맥락 반영"]
        S2C["사전 의미 보강<br/>dict_meaning, ctx_meaning"]
        S2A --> S2B --> S2C
    end

    STAGE2 -->|"Stage 2 스냅샷 저장"| STAGE3

    subgraph STAGE3["Stage 3: from_both"]
        direction LR
        S3A["원문 + 번역<br/>(양쪽 참조)"]
        S3B["<b>LLM 교차 검증</b><br/>누락 보완"]
        S3C["교차 검증 완료<br/>sources, related 추가"]
        S3A --> S3B --> S3C
    end

    STAGE3 -->|"Stage 3 스냅샷 저장"| STAGE4

    subgraph STAGE4["Stage 4: reviewed"]
        direction LR
        S4A["연구자 검토"]
        S4B["<b>수동 편집</b><br/>추가/삭제/수정"]
        S4C["최종 확정<br/>status: accepted"]
        S4A --> S4B --> S4C
    end

    subgraph DICT["사전형 주석 (DictionaryEntry)"]
        direction TB
        D1["<b>headword</b>: 표제어"]
        D2["reading: 독음"]
        D3["dict_meaning: 사전 의미"]
        D4["ctx_meaning: 문맥 의미"]
        D5["sources: 출처"]
        D6["related: 관련 항목"]
    end

    subgraph HIST["generation_history"]
        direction TB
        H1["Stage 1 스냅샷"]
        H2["Stage 2 스냅샷"]
        H3["Stage 3 스냅샷"]
    end

    style STAGE1 fill:#fff3e0,stroke:#e65100,stroke-width:2px
    style S1B fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style STAGE2 fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    style S2B fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style STAGE3 fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style S3B fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style STAGE4 fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style S4B fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style S4C fill:#c8e6c9,stroke:#2e7d32,stroke-width:2px
    style DICT fill:#fef3c7,stroke:#b45309,stroke-width:2px
    style D1 fill:#fef3c7,stroke:#b45309
    style HIST fill:#eceff1,stroke:#546e7a,stroke-width:2px
```

---

## 부록: 설계 원칙 요약

| 원칙 | 설명 |
|------|------|
| **원본 불변** | L1 파일, raw_metadata, original_text — 수정 금지 |
| **모든 필드 Nullable** | 소스에 없는 필드는 비워두고 나중에 채운다 |
| **삭제 금지, 상태 전이만** | `draft → active → deprecated → archived` |
| **원문 비변형** | 표점/현토/번역은 글자 인덱스 오버레이. 원문은 그대로 |
| **매핑 투명성** | `_mapping_info`에 출처/신뢰도 기록 |
| **출처 추적** | `source_ref`로 원본 저장소 역참조 |
| **온톨로지 비강제** | Concept 자유 확장. 부재 = 미지정 |
| **Promotion Flow** | Tag(잠정) → Concept(확정), 연구자 판단 |
| **용어 규칙** | LayoutBlock / OcrResult / TextBlock. "Block" 단독 사용 금지 |
| **오프라인 퍼스트** | 핵심 작업(교정, 열람, 커밋)은 인터넷 없이 동작 |

---
