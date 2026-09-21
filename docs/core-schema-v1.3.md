# CJK Classical Text IDE

## Core Schema -- Stable Version 1.3 (Final Core)

------------------------------------------------------------------------

# 0. Core Philosophy

This schema stores structure. It does NOT store interpretation.

Meaning and interpretation are handled outside the Core layer.

Core must remain stable, minimal, and future-proof.

> **스키마 판과 데이터 판은 다른 축이다 (D-128 1항)**: 이 문서가 정하는 `1.3`은
> **스키마** 버전이다. 「이 결과가 어느 시점 코퍼스에서 나왔는가」는 그것으로
> 답할 수 없다 — 스키마가 그대로여도 원문 교정 한 글자로 결과가 달라진다.
> 그 자리는 **출력 쪽**에서 채운다: 내보내기·인용·보고서에
> `core/corpus_version.py`가 코퍼스 스냅샷 해시를 자동으로 찍고, 사용자는
> 아무것도 입력하지 않는다.

------------------------------------------------------------------------

# 1. Work — removed (D-099)

The Work entity was dropped in v1.3. In practice every Work was auto-created
from the document title, duplicating what the document manifest and
`bibliography.json` already hold, and after D-097/D-098 nothing referenced it:
composition lives in the document store and a collection holding several works
is expressed by level-1 «container» boundaries. Existing `core_entities/works/`
folders are renamed to `works_removed_v1/` (not deleted) the first time the
store is opened.

If cross-witness linking (이본 대조) is built later, that anchor belongs *above*
the documents — at the library level — not inside one interpretation store, so
it will be a new design rather than this entity.

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

> **D-098/D-099**: `work_id` was dropped and the Work entity itself removed.
> A collection holding several works is expressed by level-1 «container»
> boundaries instead. `sequence_index` now counts within the part.

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

Fields: - id - label - scope_document (nullable; was `scope_work` until
D-099 removed the Work entity) - description (optional scholarly note) -
concept_features (JSON, optional) - metadata

Concept_features: - Fully optional. - No predefined required flags. -
Absence of feature means "unspecified". - May be extended without schema
migration.

> **D-128 6항 — `scope_document`는 «주소»다 (2026-09-21)**: 조회할 때 다른 문헌의
> 개념은 **순위가 낮아지는 것이 아니라 목록에 들어오지 않는다.** 전역(null)은
> 모든 문헌 주소에 걸린다. 연합·감각 계통에서 출력 무게의 83.2%·87.2%가 자기
> 구획에 머물렀다는 전수 측정이 근거다 — 구획은 사전확률이 아니라 벽에 가깝다.
> 구현은 `core/concept_scope.py`, 질의는 `?scope=` (`core/entity.py::list_entities`).
>
> **이것은 내보내는 쪽 규칙이다.** 승격 출처를 모으는 쪽은 구획으로 막지 않는다
> (9항, `core/promotion.py::gather_sources`). 둘을 같은 규칙으로 합치면 연합이
> 일어나지 않거나 개념이 문헌 사이로 새어 나간다.
>
> **`concept_features.promotion`은 편집으로 지우지 않는다.** 승격 판정 근거가
> 거기 산다 — 저장 경로가 이 필드를 `null`로 덮으면 「왜 올라왔는가」가 조용히
> 사라진다(실제로 화면에서 그런 일이 있었다. `tests/test_entity_manager_js.py`).

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
block \| relation \| null) - object_value (free text, nullable) -
evidence_blocks (array of block_ids) - confidence (optional) - weight
(optional) - polarity (optional) - mode (optional) - extractor
(optional) - metadata

> **D-128 11·12·13항 (2026-09-21)**: `weight`·`polarity`·`mode` 셋이 늘었다.
> 전부 선택이고 기본은 null이라 기존 관계 파일은 그대로 읽힌다.
>
> - `weight` — 관계의 굵기. `confidence`(「이 관계가 참인가」)와 **다른 축**이다.
>   약한 관계를 지우지 않고 무게를 붙여 두었다가 순회할 때 임계로 거른다.
>   병합은 되돌릴 수 없고 임계는 되돌릴 수 있다.
> - `polarity` — `support` · `refute` · `context_dependent` · `undetermined`.
>   **이진이 아니다.** 「지지 아니면 반박」으로 몰아넣으면 맥락 의존인 관계를
>   통째로 잘못 분류한다. 적히지 않은 것을 지지로 읽지 않는다
>   (`core/relation_polarity.py::polarity_of`).
> - `mode` — `assert`(내용을 주장한다) · `modulate`(주장하지 않고 **다른 관계의
>   무게를 바꾼다**). 조절형은 연합 층에만 붙으므로 `object_type`이 `concept`
>   또는 `relation`이어야 하고, 지지·반박 부호를 가질 수 없다. 검사는
>   `core/relation_polarity.py::validate_relation_semantics` — JSON 스키마로는
>   적을 수 없는 «뜻»의 규칙이라 코드에 둔다.
>
> 무게와 부호는 **함께** 저장한다. 부호 없이 「강한 엣지로 주 경로를 잡는」
> 순회를 만들면, 반대 방향이 가장 밀집한 자리를 지지와 똑같이 세게 된다.

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

> **D-128 3항 — 질의 표면도 좁게 (2026-09-21)**: 위 규칙이 «서술어» 축을 좁게
> 잡는다면, «접근 경로» 축을 좁게 잡는 것은 `core/entity.py::QUERY_SURFACE`다.
> 읽기 문은 셋뿐이고(`get_entity` · `list_entities` · `list_entities_for_page`)
> 임의 순회를 여는 함수·엔드포인트가 없다. 관계를 따라가는 일이 필요하면
> **목록을 받아 거르는 순수 함수**로 만든다 — 저장소 경로를 인자로 받지 않으므로
> 구조상 순회가 불가능하다(`core/relation_polarity.py::strong_edges`).
> 둘은 다른 축이라 서로를 대신하지 못한다.

------------------------------------------------------------------------

# 7. Promotion Flow

Tag → Concept (optional, researcher decision).

Promotion does not enforce ontology creation.

> **D-128 8·9·10항 (2026-09-21)**: 승격의 저울은 `core/promotion.py`다.
>
> - **개수가 아니라 무게** — 「출처가 몇 개 모이면 올리는가」로 정하면 약한 출처
>   여럿이 강한 출처 하나를 이긴다. 무게 1~2는 잡음 바닥으로 보고 **세지 않되
>   지우지 않는다**(임계를 내리면 돌아온다). 판정과 수치는 승격된 Concept의
>   `concept_features.promotion`에 남는다.
> - **넓게 모아서 좁게 내보낸다** — 출처 수집(`gather_sources`)은 문헌 구획으로
>   거르지 않고, 만들어진 Concept은 `scope_document` 하나를 갖는다. 이것은
>   **연합 구조인 Concept 승격에만** 해당하는 규칙이다. 편성·OCR·레이아웃처럼
>   임무가 다른 층에는 적용하지 않는다(`SCOPE_BLIND_COLLECTION_NOTE`).
> - **승격은 출처를 줄이는 단계가 아니다** — Tag를 지우거나 합치지 않는다. 폭은
>   그대로 두고 무게 배치만 기록한다.
> - 저울은 **잠금장치가 아니다.** 연구자가 누르면 승격되고, 판정이 함께 적힐
>   뿐이다. 무게 미달을 막으려면 `promote_tag_to_concept(..., require_weight=True)`.
> - **잴 수 없을 때는 세지 않는다**: 무게 도출이 「그 단위의 확정본(L4)에 표면형이
>   몇 번 나오는가」이므로, L4를 못 찾으면 **«재지 못한 것»**(`measured: false`)으로
>   두고 무게 0이 된다. Tag 개수로 대신하지 않는다 — 대신하게 두었더니 한 단위에
>   같은 표면형 Tag가 셋만 붙어도 임계를 넘어, 8항이 막으려던 「개수로 세기」가
>   그대로 복원됐다(2026-09-21 독립 검증에서 잡힘).
>   「확정본은 있는데 표면형이 안 나온다」는 **정상적인 0**이므로 판정 사유가 다르다 —
>   연구자는 전자에서 「확정본을 먼저 채우라」는 답을 받아야 한다.

> **식별자 연속성**: 승격·병합으로 생긴 id 변화는 `core_entities/id_map.json`에
> 남는다(D-128 2항, operation-rules 2.5). 옛 id로 조회하면 `get_entity()`가
> 「지금은 무엇을 보라」를 알려준다.

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
