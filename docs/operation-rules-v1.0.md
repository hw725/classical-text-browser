# CJK Classical Text IDE

## Operation Rules -- Version 1.0

------------------------------------------------------------------------

# 0. Purpose

This document defines how the Core Schema (v1.3 Final Stable) is
operated.

The Core stores structure only. Interpretation, meaning, and
experimental layers exist outside the Core.

Core must remain stable.

------------------------------------------------------------------------

# 1. Fundamental Principles

1.  Core schema must not be modified casually.
2.  Interpretation must not be embedded into structural fields.
3.  All automatically generated data requires human validation.
4.  Deletion is prohibited. Use status transitions instead.
5.  Automation proposes. Humans decide.

------------------------------------------------------------------------

# 2. Entity Creation Rules

## 2.1 ID Generation

-   All entities must use UUID or deterministic unique ID.
-   File name must match entity ID.

## 2.2 Encoding

-   UTF-8 only.
-   LF line breaks.
-   Original text must never be altered.

## 2.3 Modification Policy

-   Direct overwrite discouraged.
-   Changes tracked via version control (Git).
-   Structural changes require documented reason.

## 2.4 Deletion Policy

Deletion is not allowed.

Instead: - status: draft - status: active - status: deprecated - status:
archived

## 2.5 Identity Continuity (D-128 2항)

승격·병합으로 새 id가 생기면 **구 id → 신 id 매핑을 남긴다.** 남기지 않으면 그
id를 인용한 과거 참조 — 논문 각주, 다른 해석 저장소, 이미 내보낸 사전 — 가
조용히 끊긴다. 2.4가 파일을 살려 두는 것과 별개의 문제다: 파일이 남아 있어도
「지금은 무엇을 봐야 하는가」를 알 수 없으면 참조는 끊긴 것이다.

- 장부는 `core_entities/id_map.json` 하나다(`core/entity_id_map.py`).
- 고리 둘: `superseded_by`(병합 — 조회가 따라간다) · `promoted_to`(Tag → Concept
  승격 — 따라가지 않는다. Tag는 승격 뒤에도 제 id로 살아 있다).
- 병합은 관계를 새 id로 고쳐 쓰지 않는다. 「그때 이 관계는 A를 가리켰다」는
  사실이 사라지기 때문이다 — 해석은 읽을 때 `resolve_id()`로 이루어진다.

------------------------------------------------------------------------

# 3. Folder Structure

Entities are stored under `core_entities/` within each interpretation
repository:

```
{doc_id}/
└── boundaries/{part_id}.json    (글 단위의 경계 목록 — D-092·D-097)

{interp_id}/
└── core_entities/
    ├── id_map.json              (구 ID → 신 ID 장부 — D-128 2항)
    ├── tags/{uuid}.json
    ├── concepts/{uuid}.json
    ├── agents/{uuid}.json
    └── relations/{uuid}.json
```

> **v1.3 변경**: `works/`와 `blocks/`는 없다. 단위(unit)는 파일 하나씩 저장하지 않고
> 권마다 하나인 경계 목록에서 계산하는 읽기 보기이며(D-092), 그 목록은 편성이 원본의
> 일이므로 **원본 저장소**에 산다(D-097). Work 엔티티는 없앴다(D-099).

Each entity stored as single JSON file. File name matches entity ID.

------------------------------------------------------------------------

# 4. LLM Collaboration Workflow

Step 1: Proposal - LLM generates Tag / Relation / Concept suggestions. -
Must include: - extractor: "llm" - confidence score - status: draft

Step 2: Human Review - Validate evidence_blocks. - Confirm predicate
validity. - Approve → status: active - Reject or modify → remain draft
or deprecated.

Step 3: Promotion - Tag → Concept only by explicit researcher action. -
Relation activation requires evidence verification.

------------------------------------------------------------------------

# 5. Predicate Governance

To prevent interpretation leakage:

1.  snake_case only.
2.  No spaces.
3.  Recommended maximum length: 32--64 characters.
4.  Structural verbs only.
5.  Interpretive nuance stored outside Core.

------------------------------------------------------------------------

# 6. Version Control

-   Git required.
-   Every structural update committed separately.
-   JSON validation (jsonschema) required before commit.

Version naming pattern:

v{major}.{minor}-{YYYYMMDD}-{shortdesc}

------------------------------------------------------------------------

# 7. Experimental Layer Policy (Planned)

> **Note**: Experimental zones are not yet implemented. This section
> describes the planned design.

Experiments must not modify Core entities directly.

Planned experimental zones:
- /experiments/meaning/
- /experiments/structure/
- /experiments/llm_outputs/

Experimental results can migrate into Core only after:
1. Reproducibility confirmed
2. Human validation
3. Structural compatibility check

------------------------------------------------------------------------

# 8. Data Lifecycle

draft → active → deprecated → archived

Data is never erased. The IDE is an accumulation system.

------------------------------------------------------------------------

Version: 1.0 Status: Operational Charter
