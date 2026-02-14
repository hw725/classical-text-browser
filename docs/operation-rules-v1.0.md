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

/project_root /works /blocks /tags /concepts /agents /relations
/variants /assertions /experiments

Each entity stored as single JSON file.

Experiments folder is outside Core integrity.

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
-   schema_version field must be verified.
-   JSON validation required before commit.

Version naming pattern:

v{major}.{minor}-{YYYYMMDD}-{shortdesc}

------------------------------------------------------------------------

# 7. Experimental Layer Policy

Experiments must not modify Core entities directly.

Allowed experimental zones: - /experiments/meaning/ -
/experiments/structure/ - /experiments/llm_outputs/

Experimental results can migrate into Core only after: 1.
Reproducibility confirmed 2. Human validation 3. Structural
compatibility check

------------------------------------------------------------------------

# 8. Data Lifecycle

draft → active → deprecated → archived

Data is never erased. The IDE is an accumulation system.

------------------------------------------------------------------------

Version: 1.0 Status: Operational Charter
