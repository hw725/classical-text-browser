# 세션 회고 (Phase 10 ~ 12)

> 원본: [`../sessions/`](../sessions/) — 이 문서는 14개 세션 파일의 메타데이터·구조를 회고용으로 압축한 것이다. **원본을 수정하지 않는다.**

총 14개의 세션 문서가 있고, 합계 313,480 byte, 9,354 줄이다.

## 세션 일람

| 파일 | 분류 | 줄수 | 크기 | H2 개수 |
|---|---|---|---|---|
| [D-008_bibliography_verification.md](../sessions/D-008_bibliography_verification.md) | 서지 스키마 검증 | 279 | 10.1 KB | 9 |
| [phase10_1_ocr_session.md](../sessions/phase10_1_ocr_session.md) | Phase 10-1 | 1854 | 60.3 KB | 6 |
| [phase10_12_design_pointer.md](../sessions/phase10_12_design_pointer.md) | 설계 포인터 | 6 | 0.3 KB | 0 |
| [phase10_2_llm_session.md](../sessions/phase10_2_llm_session.md) | Phase 10-2 | 2351 | 75.7 KB | 6 |
| [phase10_3_alignment_session.md](../sessions/phase10_3_alignment_session.md) | Phase 10-3 | 1072 | 35.2 KB | 5 |
| [phase10_4_korcis_session.md](../sessions/phase10_4_korcis_session.md) | Phase 10-4 | 687 | 22.1 KB | 8 |
| [phase11_1_hyeonto_session.md](../sessions/phase11_1_hyeonto_session.md) | Phase 11-1 | 457 | 16.0 KB | 6 |
| [phase11_2_translation_session.md](../sessions/phase11_2_translation_session.md) | Phase 11-2 | 294 | 11.0 KB | 5 |
| [phase11_3_annotation_session.md](../sessions/phase11_3_annotation_session.md) | Phase 11-3 | 334 | 12.7 KB | 6 |
| [phase12_1_git_graph_session.md](../sessions/phase12_1_git_graph_session.md) | Phase 12-1 | 476 | 14.2 KB | 11 |
| [phase12_3_json_snapshot_session.md](../sessions/phase12_3_json_snapshot_session.md) | Phase 12-3 | 530 | 15.7 KB | 10 |
| [phase12_design.md](../sessions/phase12_design.md) | Phase 12 설계 | 655 | 19.4 KB | 3 |
| [session_fix_parsers.md](../sessions/session_fix_parsers.md) | 파서 수정 | 183 | 6.6 KB | 5 |
| [session_navigator.md](../sessions/session_navigator.md) | 메타-네비게이터 | 176 | 6.9 KB | 5 |

## 세션별 카드

### bibliography.schema.json 검증 보고서

- **파일**: [`D-008_bibliography_verification.md`](../sessions/D-008_bibliography_verification.md)
- **분류**: 서지 스키마 검증
- **규모**: 279줄, 10.1 KB, H2 9개

**개요**

> 현재 bibliography.schema.json은 **디지털 아카이브 메타데이터** 관점에서는 잘 설계되어 있다. Dublin Core 15요소와의 매핑이 양호하고, raw_metadata / _mapping_info라는 투명성 장치가 특히 우수하다. 그러나 **고전서지학(형태서지학)** 관점에서 보면, 한중일 고서 판본 감별의 핵심 요소인 **판식정보**가 구조적으로 빠져 있다. 문헌정보학 관점에서는 **간행사항**과 **권책수** 구조도 부재하다.

**구성**

- 1. 검증 요약
- 2. 현재 스키마의 강점
- 3. 누락 항목 분석
- 4. 제안: printing_info 필드 설계 초안
- 5. 제안: publishing 필드 설계 초안
- 6. 제안: extent 필드 설계 초안
- 7. 기존 필드 소규모 보완 제안
- 8. 적용 로드맵
- 9. 참고 자료

---

### Phase 10-1: OCR 엔진 연동 파이프라인

- **파일**: [`phase10_1_ocr_session.md`](../sessions/phase10_1_ocr_session.md)
- **분류**: Phase 10-1
- **규모**: 1854줄, 60.3 KB, H2 6개

**개요**

> 1. CLAUDE.md를 먼저 읽어라. 2. docs/DECISIONS.md를 읽어라. 특히 D-002(LayoutBlock), D-003(Block 세 종류), D-004(작업 순서). 3. docs/phase10_12_design.md의 Phase 10-1 섹션을 읽어라. 4. schemas/source_repo/ocr_page.schema.json을 읽어라.

**구성**

- 사전 준비
- 설계 요약 — 반드시 이해한 후 구현
- 작업 순서
- D-009: OCR 엔진 플러그인 아키텍처
- 체크리스트
- ⏭️ 다음 세션: Phase 10-3 — 정렬 엔진

---

### Phase 10-12 상세 설계 및 세션 지시문

- **파일**: [`phase10_12_design_pointer.md`](../sessions/phase10_12_design_pointer.md)
- **분류**: 설계 포인터
- **규모**: 6줄, 0.3 KB, H2 0개

---

### Phase 10-2: LLM 4단 폴백 아키텍처 + 레이아웃 분석

- **파일**: [`phase10_2_llm_session.md`](../sessions/phase10_2_llm_session.md)
- **분류**: Phase 10-2
- **규모**: 2351줄, 75.7 KB, H2 6개

**개요**

> 1. CLAUDE.md를 먼저 읽어라. 2. docs/phase10_12_design.md의 Phase 10-2 섹션을 읽어라. 3. 이 문서 전체를 읽은 후 작업을 시작하라. 4. 기존 코드 구조를 먼저 파악하라: `src/` 디렉토리 전체, `src/core/`, `src/api/`, `static/js/`.

**구성**

- 사전 준비
- 설계 요약 — 반드시 이해한 후 구현
- 작업 순서
- D-010: LLM 호출 아키텍처 — 4단 폴백 + 모델 선택
- 체크리스트
- ⏭️ 다음 세션: Phase 10-1 — OCR 엔진 연동

---

### Phase 10-3: 정렬 엔진 — OCR ↔ 텍스트 대조

- **파일**: [`phase10_3_alignment_session.md`](../sessions/phase10_3_alignment_session.md)
- **분류**: Phase 10-3
- **규모**: 1072줄, 35.2 KB, H2 5개

**개요**

> 1. CLAUDE.md를 먼저 읽어라. 2. docs/DECISIONS.md를 읽어라. 3. docs/phase10_12_design.md의 Phase 10-3 섹션을 읽어라. 4. 이 문서 전체를 읽은 후 작업을 시작하라. 5. **이미 완료된 Phase 10-1(OCR), 10-2(LLM)의 코드 구조를 확인하라**:

**구성**

- 사전 준비
- 설계 요약 — 반드시 이해한 후 구현
- 작업 순서
- 체크리스트
- ⏭️ 다음 세션: Phase 10-4 — KORCIS 파서 고도화 (선택)

---

### Phase 10-4: KORCIS 파서 고도화 (선택적)

- **파일**: [`phase10_4_korcis_session.md`](../sessions/phase10_4_korcis_session.md)
- **분류**: Phase 10-4
- **규모**: 687줄, 22.1 KB, H2 8개

**개요**

> 1. CLAUDE.md를 먼저 읽어라. 2. 파서 수선 세션에서 만든 KORCIS 파서 코드를 확인하라: 3. D-008 보고서 (판식정보/서지정보 스키마 설계)를 읽어라. 4. 이 문서 전체를 읽은 후 작업을 시작하라. 파서 수선 세션에서 KORCIS 파서의 **기본 기능**이 구현되었을 것이다: 이 세션에서 추가할 **고급 기능**:

**구성**

- 사전 준비
- 배경: 무엇이 이미 있고, 무엇이 없는가
- 참조 프로젝트: academic-mcp
- 설계 요약
- 작업 순서
- 기존 구현 상태
- 체크리스트
- ⏭️ 다음 세션: Phase 11-1 — 끊어읽기·현토 편집기 (L5)

---

### Phase 11-1: 끊어읽기·표점·현토 편집기 (L5)

- **파일**: [`phase11_1_hyeonto_session.md`](../sessions/phase11_1_hyeonto_session.md)
- **분류**: Phase 11-1
- **규모**: 457줄, 16.0 KB, H2 6개

**개요**

> 1. CLAUDE.md를 먼저 읽어라. 2. docs/DECISIONS.md를 읽어라. 3. docs/phase11_12_design_decisions.md를 읽어라 — L4 역할 확장, L5 표점/현토 스키마가 정의되어 있다. 4. 이 문서 전체를 읽은 후 작업을 시작하라. 5. 기존 코드 구조를 먼저 파악하라: `src/` 디렉토리 전체, `src/core/`, `src/api/`, `src/llm/`, `static/js/`.

**구성**

- 사전 준비
- 설계 요약 — 반드시 이해한 후 구현
- 작업 순서
- 완료 체크리스트
- ⏸️ 이번 Phase에서 구현하지 않는 것
- ⏭️ 다음 세션: Phase 11-2 — 번역 워크플로우 + LLM (L6)

---

### Phase 11-2: 번역 워크플로우 + LLM (L6)

- **파일**: [`phase11_2_translation_session.md`](../sessions/phase11_2_translation_session.md)
- **분류**: Phase 11-2
- **규모**: 294줄, 11.0 KB, H2 5개

**개요**

> 1. CLAUDE.md를 먼저 읽어라. 2. docs/DECISIONS.md를 읽어라. 3. docs/phase11_12_design_decisions.md를 읽어라 — L6 번역 스키마가 정의되어 있다. 4. 이 문서 전체를 읽은 후 작업을 시작하라. 5. 기존 코드 구조를 먼저 파악하라: `src/core/punctuation.py`의 `split_sentences()`, `src/llm/router.py`.

**구성**

- 사전 준비
- 설계 요약 — 반드시 이해한 후 구현
- 작업 순서
- 완료 체크리스트
- ⏭️ 다음 세션: Phase 11-3 — 주석/사전 연동 (L7)

---

### Phase 11-3: 주석/사전 연동 (L7)

- **파일**: [`phase11_3_annotation_session.md`](../sessions/phase11_3_annotation_session.md)
- **분류**: Phase 11-3
- **규모**: 334줄, 12.7 KB, H2 6개

**개요**

> 1. CLAUDE.md를 먼저 읽어라. 2. docs/DECISIONS.md를 읽어라. 3. docs/phase11_12_design_decisions.md를 읽어라 — L7 주석 스키마가 정의되어 있다. 4. 이 문서 전체를 읽은 후 작업을 시작하라. 5. 기존 코드 구조를 먼저 파악하라: `src/core/`, `src/llm/`, `src/api/`, `static/js/`.

**구성**

- 사전 준비
- 설계 요약 — 반드시 이해한 후 구현
- 작업 순서
- 완료 체크리스트
- ⏸️ 이번 Phase에서 구현하지 않는 것
- ⏭️ 다음 세션: Phase 12-1 — Git 그래프 완전판

---

### Phase 12-1: Git 그래프 완전판

- **파일**: [`phase12_1_git_graph_session.md`](../sessions/phase12_1_git_graph_session.md)
- **분류**: Phase 12-1
- **규모**: 476줄, 14.2 KB, H2 11개

**개요**

> 1. CLAUDE.md를 먼저 읽어라. 2. docs/DECISIONS.md를 읽어라. 3. docs/phase11_12_design_decisions.md를 읽어라. 4. **docs/phase12_design.md를 읽어라** — 12-1 상세 설계가 정의되어 있다. 5. 이 문서 전체를 읽은 후 작업을 시작하라. 6. 기존 코드 구조를 먼저 파악하라: `src/core/`, `src/api/`, `static/js/`.

**구성**

- 사전 준비
- 설계 요약 — 반드시 이해한 후 구현
- 작업 1: 커밋 Trailer 자동 기록
- 작업 2: Git 그래프 API
- 작업 3: 레이아웃 계산 모듈 (프론트엔드)
- 작업 4: d3.js SVG 렌더링
- 작업 5: 인터랙션
- 작업 6: Phase 9 간략 뷰 통합
- 작업 7: 통합 테스트
- 완료 체크리스트
- ⏭️ 다음 세션: Phase 12-3 — JSON 스냅샷

---

### Phase 12-3: JSON 스냅샷 Export/Import

- **파일**: [`phase12_3_json_snapshot_session.md`](../sessions/phase12_3_json_snapshot_session.md)
- **분류**: Phase 12-3
- **규모**: 530줄, 15.7 KB, H2 10개

**개요**

> 1. CLAUDE.md를 먼저 읽어라. 2. docs/DECISIONS.md를 읽어라. 3. docs/phase11_12_design_decisions.md를 읽어라. 4. **docs/phase12_design.md를 읽어라** — 12-3 JSON 스키마 상세 설계가 정의되어 있다. 5. 이 문서 전체를 읽은 후 작업을 시작하라. 6. 기존 코드 구조를 먼저 파악하라: `src/core/`, `src/api/`, `schemas/`.

**구성**

- 사전 준비
- 설계 요약 — 반드시 이해한 후 구현
- 작업 1: JSON 스냅샷 스키마 정의
- 작업 2: Export API
- 작업 3: Import 검증 함수
- 작업 4: Import API
- 작업 5: GUI 연결
- 작업 6: 통합 테스트
- 완료 체크리스트
- 향후 확장 (이번 세션에서 구현하지 않음)

---

### Phase 12 상세 설계: Git 그래프 (12-1) + JSON 스냅샷 (12-3)

- **파일**: [`phase12_design.md`](../sessions/phase12_design.md)
- **분류**: Phase 12 설계
- **규모**: 655줄, 19.4 KB, H2 3개

**개요**

> Phase 9의 간략 타임라인을 **원본⇔해석 사다리형 이분 그래프(ladder bipartite graph)**로 확장한다. ``` 원본 저장소 (L1-L4)          해석 저장소 (L5-L7) ──────────────────          ────────────────── ● abc123 │ "L4: 3장 확정텍스트" │                     ╌╌╌╌→ ● def456

**구성**

- 12-1: Git 그래프 완전판
- 12-3: JSON 스냅샷 (집중 범위)
- 미결 사항 (Phase 11 완료 후 확인)

---

### 세션: 서지정보 파서 보완 — URL 자동 인식 + KORCIS

- **파일**: [`session_fix_parsers.md`](../sessions/session_fix_parsers.md)
- **분류**: 파서 수정
- **규모**: 183줄, 6.6 KB, H2 5개

**개요**

> Phase 9까지 완료된 상태다. Phase 10으로 넘어가기 전에 Phase 5의 미완성 부분을 수선한다. 현재 서지정보 가져오기는 "파서 선택 → 키워드 검색 → 결과 선택 → 매핑"이라는 수동 4단계다. **의도한 동작**은 이것이다: 1. 연구자가 URL을 붙여넣는다 2. 앱이 URL 패턴을 보고 어느 소스인지 자동 판별한다 3. 해당 페이지에서 메타데이터를 가져온다

**구성**

- 문제
- 현재 파일 구조 (확인 필요)
- 작업 목록
- 작업 방식
- 확인 사항

---

### 세션 네비게이터 — Phase 10-12 구현 로드맵

- **파일**: [`session_navigator.md`](../sessions/session_navigator.md)
- **분류**: 메타-네비게이터
- **규모**: 176줄, 6.9 KB, H2 5개

**개요**

> **상태 범례**: ✅ 완료 / 🔄 구현 중 / ⏭️ 다음 / ⬜ 대기 각 세션이 끝나면 아래 절차를 따른다:

**구성**

- 진행 현황
- 세션 전환 프로토콜
- 세션별 다음 안내
- 추가 작업 (Phase 외)
- 사용법

---
