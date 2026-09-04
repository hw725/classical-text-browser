# CJK Classical Text IDE

## Core Schema -- Stable Version 1.3 (Final Core)

------------------------------------------------------------------------

# 0. Core Philosophy

This schema stores structure. It does NOT store interpretation.

Meaning and interpretation are handled outside the Core layer.

Core must remain stable, minimal, and future-proof.

------------------------------------------------------------------------

# 1. Work

Represents a textual work.

Fields: - id - title - author - period - metadata

------------------------------------------------------------------------

# 2. Unit (단위)

Smallest structural unit (sentence / clause / segment).

> **Implementation note**: In code the entity type is `unit` (D-093; it was
> `text_block` through v1.2). Since v1.3 units are not stored one file each —
> they are a read-only view computed from the boundary list in
> `documents/{doc}/boundaries/{part}.json` (D-092; moved from the
> interpretation store to the document store in D-097), and the schema file is
> `unit.schema.json`. See CLAUDE.md "용어 규칙" for the distinction between
> LayoutBlock, OcrResult, and unit.

Fields: - id - sequence_index - original_text -
normalized_text (optional) - source_ref - source_refs - notes - metadata

> **D-098**: `work_id` was dropped. Units no longer point at a Work — a Work
> belongs to the interpretation store while composition belongs to the document
> (D-097). A collection holding several works is expressed by level-1
> «container» boundaries instead. `sequence_index` now counts within the part.

------------------------------------------------------------------------

# 3. Tag (Surface Annotation Layer)

Provisional extraction layer (LLM or automatic tools).

Fields: - id - block_id - surface - core_category (person \| place \|
book \| office \| object \| concept \| event \| other) - confidence -
extractor - metadata

Tags are optional and may or may not be promoted.

------------------------------------------------------------------------

# 4. Concept (Promoted Semantic Entity)

Single unified entity type.

No enforced ontology. No mandatory semantic classification.

Fields: - id - label - scope_work (nullable) - description (optional
scholarly note) - concept_features (JSON, optional) - metadata

Concept_features: - Fully optional. - No predefined required flags. -
Absence of feature means "unspecified". - May be extended without schema
migration.

------------------------------------------------------------------------

# 5. Agent

Concrete historical or narrative actor.

Fields: - id - name - period (optional) - biography_note (optional) -
metadata

------------------------------------------------------------------------

# 6. Relation

Connects Agent / Concept / Block.

Fields: - id - subject_id - subject_type (agent \| concept) -
predicate - object_id (nullable) - object_type (agent \| concept \|
block \| null) - object_value (free text, nullable) - evidence_blocks
(array of block_ids) - confidence (optional) - extractor (optional) -
metadata

------------------------------------------------------------------------

# 6.1 Predicate Rules (Core Stability Rule)

To prevent interpretation leakage into structure:

1.  Must use snake_case.
2.  No spaces allowed.
3.  Recommended length: 32--64 characters maximum.
4.  Should represent structural action, not full interpretation.
5.  Detailed interpretation must be stored outside Core.

Examples (acceptable):

-   governs
-   utters
-   sacrifices_life
-   appoints_official
-   performs_ritual

Examples (not acceptable):

-   ought_to_sacrifice_life_when_facing_moral_danger
-   should_be_trustworthy_before_governing_people

------------------------------------------------------------------------

# 7. Promotion Flow

Tag → Concept (optional, researcher decision).

Promotion does not enforce ontology creation.

------------------------------------------------------------------------

# 8. Design Guarantees

✔ Structure without interpretation\
✔ No ontology lock-in\
✔ LLM collaboration ready\
✔ External DB compatible\
✔ Future expansion without Core break\
✔ Minimal semantic assumption

------------------------------------------------------------------------

Version: 1.3 Status: Final Core Stable
