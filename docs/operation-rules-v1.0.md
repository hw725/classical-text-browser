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

------------------------------------------------------------------------

# 3. Folder Structure

Entities are stored under `core_entities/` within each interpretation
repository:

```
{doc_id}/
└── boundaries/{part_id}.json    (글 단위의 경계 목록 — D-092·D-097)

{interp_id}/
└── core_entities/
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
