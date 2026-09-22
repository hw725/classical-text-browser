/* ──────────────────────────────────────────
   Phase 8: 코어 스키마 엔티티 관리 모듈
   ──────────────────────────────────────────

   해석 저장소 내의 코어 스키마 엔티티
   (단위, Tag, Concept, Agent, Relation)를
   생성·조회·편집하는 프론트엔드 모듈.

   의존:
     - viewerState (sidebar-tree.js)
     - interpState (interpretation.js)
   ────────────────────────────────────────── */

// eslint-disable-next-line no-unused-vars
const entityState = {
  active: false,            // 엔티티 패널 활성 여부
  entities: {},             // 캐시: { units:[], tags:[], concepts:[], agents:[], relations:[] }
  currentFilter: "all",     // 유형 필터: all / unit / tag / concept / agent / relation
  pageFilter: true,         // "현재 페이지만" 체크 여부
  editingEntity: null,      // 편집 중인 엔티티 (null이면 신규 생성)
  editingType: null,        // 편집 중인 엔티티 유형
};

// 엔티티 유형별 표시 정보
const ENTITY_TYPE_INFO = {
  unit:       { label: "단위",      cssClass: "type-unit",       displayField: "original_text" },
  tag:        { label: "Tag",       cssClass: "type-tag",        displayField: "surface" },
  concept:    { label: "Concept",   cssClass: "type-concept",    displayField: "label" },
  agent:      { label: "Agent",     cssClass: "type-agent",      displayField: "name" },
  relation:   { label: "Relation",  cssClass: "type-relation",   displayField: "predicate" },
};

// Tag의 core_category 선택지
const CORE_CATEGORIES = [
  { value: "person",  label: "person (인물)" },
  { value: "place",   label: "place (지명)" },
  { value: "book",    label: "book (서명)" },
  { value: "office",  label: "office (관직)" },
  { value: "object",  label: "object (사물)" },
  { value: "concept", label: "concept (개념)" },
  { value: "event",   label: "event (사건)" },
  { value: "other",   label: "other (기타)" },
];

// 상태 전이 규칙 (서버와 동기화)
const VALID_TRANSITIONS = {
  draft:      ["active", "deprecated", "archived"],
  active:     ["deprecated", "archived"],
  deprecated: ["archived"],
  archived:   [],
};


/* ──────────────────────────
   초기화
   ────────────────────────── */

// eslint-disable-next-line no-unused-vars
function initEntityManager() {
  // 필터 버튼 이벤트
  document.querySelectorAll(".entity-filter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".entity-filter-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      entityState.currentFilter = btn.dataset.type;
      _renderEntityList();
    });
  });

  // "현재 페이지만" 체크박스
  const pageFilterCb = document.getElementById("entity-page-filter");
  if (pageFilterCb) {
    pageFilterCb.addEventListener("change", () => {
      entityState.pageFilter = pageFilterCb.checked;
      _loadEntitiesForCurrentPage();
    });
  }

  // "+ 새 엔티티" 버튼
  const createBtn = document.getElementById("entity-create-btn");
  if (createBtn) {
    createBtn.addEventListener("click", _showEntityTypeChooser);
  }

  // "단위 만들기" 버튼
  const tbBtn = document.getElementById("entity-create-textblock-btn");
  if (tbBtn) {
    tbBtn.addEventListener("click", _openUnitCreator);
  }

  // "LLM에게 요청" 버튼
  const llmBtn = document.getElementById("entity-llm-request-btn");
  if (llmBtn) {
    llmBtn.addEventListener("click", _openLlmRequestDialog);
  }

  // "커넥톰 대조" 버튼 (D-128 후속)
  const connBtn = document.getElementById("entity-connectome-btn");
  if (connBtn) {
    connBtn.addEventListener("click", _openConnectomeDialog);
  }

  // 다이얼로그 닫기/취소
  const dialogOverlay = document.getElementById("entity-dialog-overlay");
  const dialogClose = document.getElementById("entity-dialog-close");
  const dialogCancel = document.getElementById("entity-dialog-cancel");
  const dialogSave = document.getElementById("entity-dialog-save");

  if (dialogOverlay) {
    dialogOverlay.addEventListener("click", (e) => {
      if (e.target === dialogOverlay) _closeEntityDialog();
    });
  }
  if (dialogClose) dialogClose.addEventListener("click", _closeEntityDialog);
  if (dialogCancel) dialogCancel.addEventListener("click", _closeEntityDialog);
  if (dialogSave) dialogSave.addEventListener("click", _saveEntity);

  // LLM 다이얼로그 닫기
  const llmOverlay = document.getElementById("llm-dialog-overlay");
  const llmClose = document.getElementById("llm-dialog-close");
  if (llmOverlay) {
    llmOverlay.addEventListener("click", (e) => {
      if (e.target === llmOverlay) llmOverlay.style.display = "none";
    });
  }
  if (llmClose) {
    llmClose.addEventListener("click", () => {
      document.getElementById("llm-dialog-overlay").style.display = "none";
    });
  }
}


/* ──────────────────────────
   엔티티 로드 및 렌더링
   ────────────────────────── */

/**
 * 현재 페이지의 엔티티를 로드한다.
 * workspace.js의 하단 패널 탭 전환에서 호출된다.
 */
// eslint-disable-next-line no-unused-vars
function _loadEntitiesForCurrentPage() {
  if (!interpState || !interpState.interpId) {
    _renderEmptyList("해석 저장소를 먼저 선택하세요");
    return;
  }
  if (!viewerState || !viewerState.docId) {
    _renderEmptyList("문헌을 먼저 선택하세요");
    return;
  }

  // 해석 모드 버튼 표시
  _updateToolbarButtons();

  if (entityState.pageFilter && viewerState.pageNum) {
    // 페이지별 엔티티 조회
    const url = `/api/interpretations/${interpState.interpId}/entities/page/${viewerState.pageNum}?document_id=${viewerState.docId}`;
    fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(`서버 오류 (${r.status})`);
        return r.json();
      })
      .then((data) => {
        if (data.error) {
          _renderEmptyList(data.error);
          return;
        }
        entityState.entities = data;
        _renderEntityList();
        _renderLlmDraftReview();
      })
      .catch((err) => _renderEmptyList(`조회 실패: ${err.message}`));
  } else {
    // 전체 엔티티 조회 (유형별)
    _loadAllEntities();
  }
}


/**
 * 모든 엔티티를 유형별로 로드한다.
 */
function _loadAllEntities() {
  if (!interpState || !interpState.interpId) return;

  const types = ["unit", "tag", "concept", "agent", "relation"];
  const typeMap = { unit: "units", tag: "tags", concept: "concepts", agent: "agents", relation: "relations" };

  Promise.all(
    types.map((t) =>
      fetch(`/api/interpretations/${interpState.interpId}/entities/${t}`)
        .then((r) => {
          if (!r.ok) throw new Error(`서버 오류 (${r.status})`);
          return r.json();
        })
        .then((data) => ({ type: t, entities: data.entities || [] }))
        .catch(() => ({ type: t, entities: [] }))
    )
  ).then((results) => {
    entityState.entities = {};
    results.forEach(({ type, entities }) => {
      entityState.entities[typeMap[type]] = entities;
    });
    _renderEntityList();
    _renderLlmDraftReview();
  });
}


/**
 * 엔티티 목록을 렌더링한다.
 */
function _renderEntityList() {
  const container = document.getElementById("entity-list");
  if (!container) return;

  const allItems = _getFilteredEntities();

  if (allItems.length === 0) {
    container.innerHTML = '<div class="placeholder">엔티티가 없습니다</div>';
    return;
  }

  container.innerHTML = allItems.map((item) => {
    const info = ENTITY_TYPE_INFO[item._entityType] || {};
    const label = item[info.displayField] || item.id || "—";
    const truncLabel = label.length > 50 ? label.substring(0, 50) + "..." : label;
    const shortId = (item.id || "").substring(0, 8);
    const isTag = item._entityType === "tag";
    const isConcept = item._entityType === "concept";
    // 이미 다른 개념으로 합쳐진 것은 다시 합치지 않는다 — get_entity 가 붙여 주는 표시(D-128 2항).
    const merged = isConcept && item.superseded_by
      ? `<span class="entity-list-id" title="${_escHtml(item.superseded_by)} 로 합쳐짐">→ ${_escHtml(String(item.superseded_by).substring(0, 8))}</span>`
      : "";

    return `<div class="entity-list-item" data-entity-type="${item._entityType}" data-entity-id="${item.id}">
      <span class="entity-type-badge ${info.cssClass}">${info.label}</span>
      <span class="entity-list-label" title="${_escHtml(label)}">${_escHtml(truncLabel)}</span>
      <span class="entity-status-badge status-${item.status || "draft"}">${item.status || "draft"}</span>
      <span class="entity-list-id">${shortId}</span>
      ${merged}
      <span class="entity-list-actions">
        ${isTag ? `<button class="entity-promote-btn" data-tag-id="${item.id}" title="Concept으로 승격">승격</button>` : ""}
        ${isConcept && !item.superseded_by ? `<button class="entity-merge-btn" data-concept-id="${item.id}" title="다른 개념으로 합치기 (구 ID는 장부에 남는다)">합치기</button>` : ""}
      </span>
    </div>`;
  }).join("");

  // 클릭 이벤트: 편집 다이얼로그
  container.querySelectorAll(".entity-list-item").forEach((el) => {
    el.addEventListener("click", (e) => {
      // 승격·합치기 버튼 클릭은 별도 처리
      if (e.target.classList.contains("entity-promote-btn")) return;
      if (e.target.classList.contains("entity-merge-btn")) return;
      const type = el.dataset.entityType;
      const id = el.dataset.entityId;
      _openEntityEditDialog(type, id);
    });
  });

  // 승격 버튼 이벤트
  container.querySelectorAll(".entity-promote-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      _promoteTag(btn.dataset.tagId);
    });
  });

  // 합치기 버튼 이벤트 (D-128 2항)
  container.querySelectorAll(".entity-merge-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      _openMergeDialog(btn.dataset.conceptId);
    });
  });
}


/**
 * 현재 필터에 따라 엔티티를 정렬·필터하여 반환한다.
 */
function _getFilteredEntities() {
  const ent = entityState.entities || {};
  const typeMap = {
    unit: "units", tag: "tags",
    concept: "concepts", agent: "agents", relation: "relations",
  };

  let items = [];

  if (entityState.currentFilter === "all") {
    // 모든 유형
    for (const [type, key] of Object.entries(typeMap)) {
      (ent[key] || []).forEach((e) => items.push({ ...e, _entityType: type }));
    }
  } else {
    const key = typeMap[entityState.currentFilter];
    (ent[key] || []).forEach((e) => items.push({ ...e, _entityType: entityState.currentFilter }));
  }

  return items;
}


function _renderEmptyList(msg) {
  const container = document.getElementById("entity-list");
  if (container) {
    container.innerHTML = `<div class="placeholder">${_escHtml(msg)}</div>`;
  }
}


/* ──────────────────────────
   엔티티 생성 / 편집 다이얼로그
   ────────────────────────── */

/**
 * "+ 새 엔티티" 클릭 시 유형 선택 후 다이얼로그를 연다.
 */
function _showEntityTypeChooser() {
  // 간단한 유형 선택: 다이얼로그 내에서 유형 드롭다운을 보여주고 선택 후 폼을 렌더링
  entityState.editingEntity = null;
  entityState.editingType = null;

  const form = document.getElementById("entity-dialog-form");
  const title = document.getElementById("entity-dialog-title");
  title.textContent = "새 엔티티 만들기";

  form.innerHTML = `
    <label class="bib-edit-label">엔티티 유형</label>
    <select id="entity-new-type-select" class="bib-select entity-type-select">
      <option value="">유형을 선택하세요</option>
      <option value="tag">Tag (태그)</option>
      <option value="concept">Concept (개념)</option>
      <option value="agent">Agent (인물)</option>
      <option value="relation">Relation (관계)</option>
    </select>
    <div id="entity-type-form"></div>
  `;

  const select = document.getElementById("entity-new-type-select");
  select.addEventListener("change", () => {
    const type = select.value;
    if (!type) {
      document.getElementById("entity-type-form").innerHTML = "";
      return;
    }
    entityState.editingType = type;
    document.getElementById("entity-type-form").innerHTML = _buildFormFields(type, null);
  });

  document.getElementById("entity-dialog-status").textContent = "";
  document.getElementById("entity-dialog-overlay").style.display = "";
}


/**
 * 기존 엔티티 편집 다이얼로그를 연다.
 */
function _openEntityEditDialog(entityType, entityId) {
  if (!interpState || !interpState.interpId) return;

  fetch(`/api/interpretations/${interpState.interpId}/entities/${entityType}/${entityId}`)
    .then((r) => {
      if (!r.ok) throw new Error(`서버 오류 (${r.status})`);
      return r.json();
    })
    .then((entity) => {
      if (entity.error) {
        showToast(entity.error, 'error');
        return;
      }

      entityState.editingEntity = entity;
      entityState.editingType = entityType;

      const form = document.getElementById("entity-dialog-form");
      const title = document.getElementById("entity-dialog-title");
      const info = ENTITY_TYPE_INFO[entityType] || {};
      title.textContent = `${info.label} 편집`;

      form.innerHTML = _buildFormFields(entityType, entity);
      document.getElementById("entity-dialog-status").textContent = "";
      document.getElementById("entity-dialog-overlay").style.display = "";
    })
    .catch((err) => showToast(`엔티티 조회 실패: ${err.message}`, 'error'));
}


/**
 * 엔티티 유형에 맞는 폼 필드 HTML을 생성한다.
 */
function _buildFormFields(entityType, existing) {
  const val = (field) => existing ? _escHtml(existing[field] || "") : "";
  const statusOptions = _buildStatusOptions(existing ? existing.status : "draft");

  switch (entityType) {
    case "tag":
      return `
        <label class="bib-edit-label">단위 ID (block_id)</label>
        <input id="ef-block-id" type="text" class="bib-input" value="${val("block_id")}" placeholder="단위 UUID" />
        <label class="bib-edit-label">표면 문자열 (surface)</label>
        <input id="ef-surface" type="text" class="bib-input" value="${val("surface")}" placeholder="예: 王戎" />
        <label class="bib-edit-label">핵심 범주 (core_category)</label>
        <select id="ef-core-category" class="bib-select" style="width:100%;">
          ${CORE_CATEGORIES.map((c) =>
            `<option value="${c.value}" ${existing && existing.core_category === c.value ? "selected" : ""}>${c.label}</option>`
          ).join("")}
        </select>
        <label class="bib-edit-label">신뢰도 (confidence): <span id="ef-conf-val">${existing ? (existing.confidence ?? 0.8) : 0.8}</span></label>
        <input id="ef-confidence" type="range" min="0" max="1" step="0.05" value="${existing ? (existing.confidence ?? 0.8) : 0.8}" class="corr-slider" />
        <label class="bib-edit-label">추출 주체 (extractor)</label>
        <input id="ef-extractor" type="text" class="bib-input" value="${val("extractor")}" placeholder="manual / llm / regex" />
        <label class="bib-edit-label">상태 (status)</label>
        <select id="ef-status" class="bib-select" style="width:100%;">${statusOptions}</select>
      `;

    case "concept": {
      // 승격 때 잰 가중 기여도를 그대로 보여준다 (D-128 8항). 「왜 이 개념이
      // 올라왔는가」를 나중에 되짚을 수 있어야 하므로 읽기 전용으로 둔다.
      const promo = existing && existing.concept_features && existing.concept_features.promotion;
      const promoBox = promo
        ? `<div class="entity-promo-note">승격 판정: <b>${promo.eligible ? "충족" : "미충족"}</b> — ${_escHtml(promo.reason || "")}<br>
             실질 무게 ${promo.metrics ? promo.metrics.effective_weight : "?"} · 출처 ${promo.metrics ? promo.metrics.source_count : "?"}개
             (출처 «수»는 판정에 쓰지 않는다 — D-128 7·8항)</div>`
        : "";
      const supersededBox = existing && existing.superseded_by
        ? `<div class="entity-promo-note">이 개념은 <b>${_escHtml(existing.superseded_by)}</b> 로 합쳐졌다. 옛 ID는 장부에 남아 계속 조회된다 (D-128 2항).</div>`
        : "";
      return `
        ${supersededBox}
        ${promoBox}
        <label class="bib-edit-label">라벨 (label)</label>
        <input id="ef-label" type="text" class="bib-input" value="${val("label")}" placeholder="예: 王戎" />
        <label class="bib-edit-label">유효 범위 문헌 ID (scope_document, 비우면 전역)</label>
        <input id="ef-scope-doc" type="text" class="bib-input" value="${val("scope_document")}" placeholder="Work UUID (전역이면 비움)" />
        <label class="bib-edit-label">설명 (description)</label>
        <textarea id="ef-description" class="bib-textarea" rows="3" placeholder="학술적 설명">${val("description")}</textarea>
        <label class="bib-edit-label">상태 (status)</label>
        <select id="ef-status" class="bib-select" style="width:100%;">${statusOptions}</select>
      `;
    }

    case "agent":
      return `
        <label class="bib-edit-label">이름 (name)</label>
        <input id="ef-name" type="text" class="bib-input" value="${val("name")}" placeholder="예: 王戎" />
        <label class="bib-edit-label">활동 시기 (period)</label>
        <input id="ef-period" type="text" class="bib-input" value="${val("period")}" placeholder="예: 西晉" />
        <label class="bib-edit-label">약전 (biography_note)</label>
        <textarea id="ef-biography-note" class="bib-textarea" rows="3" placeholder="간략한 인물 설명">${val("biography_note")}</textarea>
        <label class="bib-edit-label">상태 (status)</label>
        <select id="ef-status" class="bib-select" style="width:100%;">${statusOptions}</select>
      `;

    case "relation":
      return `
        <label class="bib-edit-label">주어 ID (subject_id)</label>
        <input id="ef-subject-id" type="text" class="bib-input" value="${val("subject_id")}" placeholder="Agent 또는 Concept UUID" />
        <label class="bib-edit-label">주어 유형 (subject_type)</label>
        <select id="ef-subject-type" class="bib-select" style="width:100%;">
          <option value="agent" ${existing && existing.subject_type === "agent" ? "selected" : ""}>agent</option>
          <option value="concept" ${existing && existing.subject_type === "concept" ? "selected" : ""}>concept</option>
        </select>
        <label class="bib-edit-label">술어 (predicate, snake_case)</label>
        <input id="ef-predicate" type="text" class="bib-input" value="${val("predicate")}" placeholder="예: governs, utters" />
        <label class="bib-edit-label">목적어 ID (object_id, 선택)</label>
        <input id="ef-object-id" type="text" class="bib-input" value="${val("object_id")}" placeholder="Agent/Concept/Block UUID" />
        <label class="bib-edit-label">목적어 유형 (object_type)</label>
        <select id="ef-object-type" class="bib-select" style="width:100%;">
          <option value="">없음</option>
          <option value="agent" ${existing && existing.object_type === "agent" ? "selected" : ""}>agent</option>
          <option value="concept" ${existing && existing.object_type === "concept" ? "selected" : ""}>concept</option>
          <option value="block" ${existing && existing.object_type === "block" ? "selected" : ""}>block</option>
          <option value="relation" ${existing && existing.object_type === "relation" ? "selected" : ""}>relation (조절 대상)</option>
        </select>
        <label class="bib-edit-label">자유 텍스트 목적어 (object_value, 선택)</label>
        <input id="ef-object-value" type="text" class="bib-input" value="${val("object_value")}" placeholder="예: 瑯邪臨沂" />
        <label class="bib-edit-label">신뢰도 (confidence): <span id="ef-conf-val">${existing ? (existing.confidence ?? 0.8) : 0.8}</span></label>
        <input id="ef-confidence" type="range" min="0" max="1" step="0.05" value="${existing ? (existing.confidence ?? 0.8) : 0.8}" class="corr-slider" />
        <label class="bib-edit-label">무게 (weight, 비우면 미지정)</label>
        <input id="ef-weight" type="number" min="0" step="0.5" class="bib-input" value="${val("weight")}" placeholder="굵기 — 신뢰도와 다른 축이다" />
        <label class="bib-edit-label">부호 (polarity)</label>
        <select id="ef-polarity" class="bib-select" style="width:100%;">
          <option value="">미지정 (지지로 읽지 않는다)</option>
          <option value="support" ${existing && existing.polarity === "support" ? "selected" : ""}>지지 (support)</option>
          <option value="refute" ${existing && existing.polarity === "refute" ? "selected" : ""}>반박 (refute)</option>
          <option value="context_dependent" ${existing && existing.polarity === "context_dependent" ? "selected" : ""}>맥락 의존 (context_dependent)</option>
          <option value="undetermined" ${existing && existing.polarity === "undetermined" ? "selected" : ""}>불명 (undetermined)</option>
        </select>
        <label class="bib-edit-label">종류 (mode)</label>
        <select id="ef-mode" class="bib-select" style="width:100%;">
          <option value="">주장 (assert — 기본)</option>
          <option value="modulate" ${existing && existing.mode === "modulate" ? "selected" : ""}>조절 (modulate — 다른 관계의 무게를 바꾼다)</option>
        </select>
        <div class="entity-promo-note">조절(modulate)은 내용을 주장하지 않으므로 지지·반박 부호를 붙일 수 없고, 목적어가 concept 또는 relation 이어야 한다 (D-128 12항).</div>
        <label class="bib-edit-label">추출 주체 (extractor)</label>
        <input id="ef-extractor" type="text" class="bib-input" value="${val("extractor")}" placeholder="manual / llm" />
        <label class="bib-edit-label">상태 (status)</label>
        <select id="ef-status" class="bib-select" style="width:100%;">${statusOptions}</select>
      `;

    default:
      return '<div class="placeholder">지원하지 않는 엔티티 유형입니다</div>';
  }
}


/**
 * 상태 드롭다운 옵션을 생성한다.
 * 편집 시에는 현재 상태 + 유효한 전이 상태만 표시한다.
 */
function _buildStatusOptions(currentStatus) {
  const current = currentStatus || "draft";
  const allowed = VALID_TRANSITIONS[current] || [];
  const allStatuses = [current, ...allowed];

  return allStatuses.map((s) =>
    `<option value="${s}" ${s === current ? "selected" : ""}>${s}</option>`
  ).join("");
}


/**
 * 다이얼로그 "저장" 버튼 처리.
 */
async function _saveEntity() {
  const statusEl = document.getElementById("entity-dialog-status");
  const type = entityState.editingType;

  if (!type) {
    statusEl.textContent = "엔티티 유형을 선택하세요";
    return;
  }

  if (!interpState || !interpState.interpId) {
    statusEl.textContent = "해석 저장소가 선택되지 않았습니다";
    return;
  }

  // 폼에서 데이터 수집
  const data = _collectFormData(type);
  if (!data) {
    statusEl.textContent = "필수 필드를 확인하세요";
    return;
  }

  statusEl.textContent = "저장 중...";
  statusEl.style.color = "#3b82f6";

  try {
    let result;
    if (entityState.editingEntity) {
      // 수정 (PUT)
      const resp = await fetch(
        `/api/interpretations/${interpState.interpId}/entities/${type}/${entityState.editingEntity.id}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ updates: data }),
        }
      );
      if (!resp.ok) {
        // HTTP 오류 시 JSON 본문이 있으면 에러 메시지를 추출, 없으면 상태 코드 표시
        const errBody = await resp.json().catch(() => ({}));
        statusEl.textContent = errBody.error || `서버 오류 (${resp.status})`;
        statusEl.style.color = "#ef4444";
        return;
      }
      result = await resp.json();
    } else {
      // 생성 (POST)
      const resp = await fetch(
        `/api/interpretations/${interpState.interpId}/entities`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ entity_type: type, data: data }),
        }
      );
      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({}));
        statusEl.textContent = errBody.error || `서버 오류 (${resp.status})`;
        statusEl.style.color = "#ef4444";
        return;
      }
      result = await resp.json();
    }

    if (result.error) {
      statusEl.textContent = result.error;
      statusEl.style.color = "#ef4444";
      return;
    }

    _closeEntityDialog();
    _loadEntitiesForCurrentPage();
  } catch (err) {
    statusEl.textContent = `저장 실패: ${err.message}`;
    statusEl.style.color = "#ef4444";
  }
}


/**
 * 폼 데이터를 엔티티 유형에 맞게 수집한다.
 */
function _collectFormData(entityType) {
  const _val = (id) => {
    const el = document.getElementById(id);
    return el ? el.value.trim() : "";
  };
  const _numVal = (id) => {
    const el = document.getElementById(id);
    return el ? parseFloat(el.value) : null;
  };

  switch (entityType) {
    case "tag": {
      const surface = _val("ef-surface");
      const blockId = _val("ef-block-id");
      const category = _val("ef-core-category");
      if (!surface || !blockId || !category) return null;
      return {
        block_id: blockId,
        surface,
        core_category: category,
        confidence: _numVal("ef-confidence"),
        extractor: _val("ef-extractor") || "manual",
        status: _val("ef-status") || "draft",
        metadata: null,
      };
    }

    case "concept": {
      const label = _val("ef-label");
      if (!label) return null;
      // 편집이 승격 기록을 지우면 안 된다. concept_features.promotion 에는
      // 「왜 이 개념이 올라왔는가」(가중 기여도, D-128 8항)가 들어 있고,
      // metadata 에는 promoted_from_tag_id 가 있다. 예전에는 둘 다 null 로
      // 덮어써서, 연구자가 설명 한 줄을 고치면 그 기록이 통째로 사라졌다.
      const prev = entityState.editingEntity || {};
      return {
        label,
        scope_document: _val("ef-scope-doc") || null,
        description: _val("ef-description") || null,
        concept_features: prev.concept_features ?? null,
        status: _val("ef-status") || "draft",
        metadata: prev.metadata ?? null,
      };
    }

    case "agent": {
      const name = _val("ef-name");
      if (!name) return null;
      return {
        name,
        period: _val("ef-period") || null,
        biography_note: _val("ef-biography-note") || null,
        status: _val("ef-status") || "draft",
        metadata: null,
      };
    }

    case "relation": {
      const subjectId = _val("ef-subject-id");
      const subjectType = _val("ef-subject-type");
      const predicate = _val("ef-predicate");
      if (!subjectId || !subjectType || !predicate) return null;
      return {
        subject_id: subjectId,
        subject_type: subjectType,
        predicate,
        object_id: _val("ef-object-id") || null,
        object_type: _val("ef-object-type") || null,
        object_value: _val("ef-object-value") || null,
        evidence_blocks: (entityState.editingEntity || {}).evidence_blocks ?? null,
        confidence: _numVal("ef-confidence"),
        // 무게와 부호는 함께 저장한다 (D-128 11항). 빈 칸은 «미지정»이고,
        // 미지정을 지지로 읽지 않는 것은 서버 쪽 polarity_of() 가 지킨다.
        weight: _numVal("ef-weight"),
        polarity: _val("ef-polarity") || null,
        mode: _val("ef-mode") || null,
        extractor: _val("ef-extractor") || "manual",
        status: _val("ef-status") || "draft",
        metadata: (entityState.editingEntity || {}).metadata ?? null,
      };
    }

    default:
      return null;
  }
}


function _closeEntityDialog() {
  document.getElementById("entity-dialog-overlay").style.display = "none";
  // 합치기 다이얼로그가 숨겨 둔 공용 저장 단추를 되돌린다 — 되돌리지 않으면
  // 다음에 엔티티를 편집할 때 저장 단추가 사라진 채로 열린다.
  const saveBtn = document.getElementById("entity-dialog-save");
  if (saveBtn) saveBtn.style.display = "";
  entityState.editingEntity = null;
  entityState.editingType = null;
}


/* ──────────────────────────
   단위 생성 (source_ref 자동)
   ────────────────────────── */

/**
 * "단위 만들기" 전용 다이얼로그를 연다.
 * source_ref 필드가 현재 문서/페이지 정보로 자동 채워진다.
 */
async function _openUnitCreator() {
  if (!interpState || !interpState.interpId || !viewerState || !viewerState.docId) {
    showToast("해석 저장소와 문헌을 먼저 선택하세요.", 'warning');
    return;
  }

  entityState.editingEntity = null;
  entityState.editingType = "unit";

  const form = document.getElementById("entity-dialog-form");
  const title = document.getElementById("entity-dialog-title");
  title.textContent = "단위 만들기 (출처 자동 채움)";

  form.innerHTML = `
    <label class="bib-edit-label">원본 문헌</label>
    <input type="text" class="bib-input" value="${viewerState.docId}" readonly />
    <label class="bib-edit-label">페이지</label>
    <input type="text" class="bib-input" value="${viewerState.pageNum || 1}" readonly />
    <label class="bib-edit-label">LayoutBlock ID (선택)</label>
    <input id="ef-tb-layout-block" type="text" class="bib-input" placeholder="예: p01_b01 (없으면 비움)" />
    <label class="bib-edit-label">원문 텍스트 (original_text)</label>
    <textarea id="ef-tb-original-text" class="bib-textarea" rows="3" placeholder="L4 텍스트에서 블록에 해당하는 부분을 붙여넣으세요"></textarea>
    <label class="bib-edit-label">순서 인덱스 (sequence_index, 0-based)</label>
    <input id="ef-tb-seq-index" type="number" class="bib-input" value="0" min="0" />
  `;

  // 저장 버튼 동작을 단위 전용으로 교체
  const saveBtn = document.getElementById("entity-dialog-save");
  // 기존 리스너 제거를 위해 교체
  const newSaveBtn = saveBtn.cloneNode(true);
  saveBtn.parentNode.replaceChild(newSaveBtn, saveBtn);
  newSaveBtn.addEventListener("click", _saveUnitFromSource);

  document.getElementById("entity-dialog-status").textContent = "";
  document.getElementById("entity-dialog-overlay").style.display = "";
}


/**
 * 단위 from source 저장 처리.
 */
async function _saveUnitFromSource() {
  const statusEl = document.getElementById("entity-dialog-status");

  const originalText = (document.getElementById("ef-tb-original-text") || {}).value?.trim();
  const seqIndex = parseInt((document.getElementById("ef-tb-seq-index") || {}).value, 10);
  const layoutBlockId = (document.getElementById("ef-tb-layout-block") || {}).value?.trim() || null;

  if (!originalText) {
    statusEl.textContent = "원문 텍스트를 입력하세요";
    statusEl.style.color = "#ef4444";
    return;
  }

  statusEl.textContent = "저장 중...";
  statusEl.style.color = "#3b82f6";

  try {
    const resp = await fetch(
      `/api/interpretations/${interpState.interpId}/entities/unit/from-source`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: viewerState.docId,
          part_id: viewerState.partId || "vol1",
          page_num: viewerState.pageNum || 1,
          layout_block_id: layoutBlockId,
          original_text: originalText,
            sequence_index: isNaN(seqIndex) ? 0 : seqIndex,
        }),
      }
    );
    if (!resp.ok) {
      const errBody = await resp.json().catch(() => ({}));
      statusEl.textContent = errBody.error || `서버 오류 (${resp.status})`;
      statusEl.style.color = "#ef4444";
      return;
    }
    const result = await resp.json();

    if (result.error) {
      statusEl.textContent = result.error;
      statusEl.style.color = "#ef4444";
      return;
    }

    _closeEntityDialog();
    // 저장 버튼 원복
    _restoreSaveButton();
    _loadEntitiesForCurrentPage();
  } catch (err) {
    statusEl.textContent = `저장 실패: ${err.message}`;
    statusEl.style.color = "#ef4444";
  }
}


/**
 * 단위 다이얼로그에서 교체된 저장 버튼을 원래 핸들러로 복원한다.
 */
function _restoreSaveButton() {
  const saveBtn = document.getElementById("entity-dialog-save");
  if (saveBtn) {
    const newBtn = saveBtn.cloneNode(true);
    saveBtn.parentNode.replaceChild(newBtn, saveBtn);
    newBtn.addEventListener("click", _saveEntity);
  }
}


/* ──────────────────────────
   Tag → Concept 승격
   ────────────────────────── */

async function _promoteTag(tagId) {
  if (!interpState || !interpState.interpId) return;

  // 간단한 확인
  const label = prompt("Concept 라벨 (Tag의 surface가 기본값):");
  if (label === null) return; // 취소

  try {
    const resp = await fetch(
      `/api/interpretations/${interpState.interpId}/entities/tags/${tagId}/promote`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label: label || null,
          scope_document: null,
          description: null,
        }),
      }
    );
    if (!resp.ok) {
      const errBody = await resp.json().catch(() => ({}));
      showToast(errBody.error || `승격 실패: 서버 오류 (${resp.status})`, 'error');
      return;
    }
    const result = await resp.json();
    if (result.error) {
      showToast(result.error, 'error');
      return;
    }
    _loadEntitiesForCurrentPage();
  } catch (err) {
    showToast(`승격 실패: ${err.message}`, 'error');
  }
}


/**
 * Concept 합치기 다이얼로그를 연다 (D-128 2항).
 *
 * 입력: sourceId — 흡수되는 개념의 id.
 * 출력: 없음 (성공하면 목록을 다시 읽는다).
 *
 * 왜 «지우기»가 아니라 «합치기»인가: 개념을 지우면 그 id를 인용한 과거 참조 —
 * 논문 각주, 이미 내보낸 사전 — 가 조용히 끊긴다. 합치기는 옛 개념을 그대로 두고
 * 상태만 deprecated 로 내린 뒤 「이제 무엇을 보라」를 장부에 적는다. 옛 id로
 * 조회하면 서버가 새 id를 알려준다.
 */
function _openMergeDialog(sourceId) {
  if (!interpState || !interpState.interpId) return;

  const concepts = (entityState.entities || {}).concepts || [];
  const source = concepts.find((c) => c.id === sourceId);
  // 자기 자신과 이미 합쳐진 것은 대상이 될 수 없다.
  const targets = concepts.filter((c) => c.id !== sourceId && !c.superseded_by);
  if (targets.length === 0) {
    showToast("합칠 대상 개념이 없습니다. 먼저 남길 개념을 만드세요.", "error");
    return;
  }

  const overlay = document.getElementById("entity-dialog-overlay");
  const form = document.getElementById("entity-dialog-form");
  const title = document.getElementById("entity-dialog-title");
  if (!overlay || !form || !title) return;

  // 이 다이얼로그는 «저장»이 아니라 «합치기»다 — 공용 저장 단추를 숨기고
  // 폼 안에 전용 단추를 둔다. _closeEntityDialog 가 다시 보이게 되돌린다.
  entityState.editingEntity = null;
  entityState.editingType = null;
  const saveBtn = document.getElementById("entity-dialog-save");
  if (saveBtn) saveBtn.style.display = "none";
  const statusEl = document.getElementById("entity-dialog-status");
  if (statusEl) statusEl.textContent = "";

  title.textContent = "개념 합치기";
  form.innerHTML = `
    <div class="entity-promo-note">
      <b>${_escHtml((source && source.label) || sourceId)}</b> 를 다른 개념으로 합칩니다.<br>
      이 개념의 파일은 지워지지 않고 상태만 «deprecated» 가 되며, 옛 ID는 장부에
      남아 계속 조회됩니다 (D-128 2항).
    </div>
    <label class="bib-edit-label">남길 개념 (target)</label>
    <select id="ef-merge-target" class="bib-select" style="width:100%;">
      ${targets.map((c) => `<option value="${_escHtml(c.id)}">${_escHtml(c.label || c.id)} (${_escHtml(String(c.id).substring(0, 8))})</option>`).join("")}
    </select>
    <label class="bib-edit-label">사유 (note, 선택)</label>
    <input id="ef-merge-note" type="text" class="bib-input" placeholder="예: 같은 인물" />
    <div class="bib-edit-actions">
      <button id="ef-merge-run" type="button">합치기</button>
    </div>
  `;
  overlay.style.display = "";

  document.getElementById("ef-merge-run").addEventListener("click", async () => {
    const targetId = document.getElementById("ef-merge-target").value;
    const note = document.getElementById("ef-merge-note").value || null;
    try {
      const resp = await fetch(
        `/api/interpretations/${interpState.interpId}/entities/concepts/merge`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_ids: [sourceId], target_id: targetId, note }),
        }
      );
      const result = await resp.json().catch(() => ({}));
      if (!resp.ok || result.error) {
        showToast(result.error || `합치기 실패: 서버 오류 (${resp.status})`, "error");
        return;
      }
      _closeEntityDialog();
      showToast(`합쳤습니다 — 옛 ID는 장부에 남습니다 (${result.merged.length}건)`, "success");
      _loadEntitiesForCurrentPage();
    } catch (err) {
      showToast(`합치기 실패: ${err.message}`, "error");
    }
  });
}


/**
 * 커넥톰 대조를 열어 «나란히» 보여 준다 (D-128 후속).
 *
 * 입력: 없음 (지금 해석 저장소를 쓴다).
 * 출력: 없음 (다이얼로그를 띄운다).
 *
 * 왜 점수가 없는가: 「연합 구조와 82% 닮았다」 같은 숫자를 띄우면 그 숫자를
 * 올리는 것이 목표가 된다. 커넥톰은 참고 좌표이지 목표가 아니다 — 차이만
 * 보여 주고 해석은 연구자가 한다. 그래서 이 화면에는 총점이 없고, 눈에
 * 들어와야 하는 것은 표가 아니라 «짚어 주는 말»(notes)이다.
 *
 * 왜 「기준값 다시 재기」가 400을 그대로 보여 주는가: 그 사유 문구는 배포본에서
 * 「이건 애초에 없는 기능이다」를 연구자에게 설명하기 위해 쓴 것이다. 토스트로
 * 줄여 버리면 줄바꿈으로 적은 «왜·해결»이 사라진다.
 */
function _openConnectomeDialog() {
  if (!interpState || !interpState.interpId) {
    showToast("해석 저장소를 먼저 선택하세요", "error");
    return;
  }

  const overlay = document.getElementById("entity-dialog-overlay");
  const form = document.getElementById("entity-dialog-form");
  const title = document.getElementById("entity-dialog-title");
  if (!overlay || !form || !title) return;

  // 읽기만 하는 화면이다 — 공용 저장 단추를 숨긴다.
  // _closeEntityDialog 가 다시 보이게 되돌린다.
  entityState.editingEntity = null;
  entityState.editingType = null;
  const saveBtn = document.getElementById("entity-dialog-save");
  if (saveBtn) saveBtn.style.display = "none";
  const statusEl = document.getElementById("entity-dialog-status");
  if (statusEl) statusEl.textContent = "";

  title.textContent = "커넥톰 대조";
  form.innerHTML = '<div class="entity-promo-note">재는 중…</div>';
  overlay.style.display = "";

  _renderConnectome(false);
}


/**
 * 대조 결과를 받아 그린다.
 *
 * 입력: live — true 면 기준값을 neuPrint 에 직접 물어 새로 뽑는다.
 * 출력: 없음.
 */
async function _renderConnectome(live) {
  const form = document.getElementById("entity-dialog-form");
  if (!form) return;

  let data;
  let resp;
  try {
    resp = await fetch(
      `/api/interpretations/${interpState.interpId}/connectome-comparison?live=${live ? "true" : "false"}`
    );
    data = await resp.json().catch(() => ({}));
  } catch (err) {
    form.innerHTML = `<div class="entity-promo-note">대조하지 못했습니다: ${_escHtml(err.message)}</div>`;
    return;
  }

  if (!resp.ok || data.error) {
    // 400 의 사유는 줄바꿈으로 «왜·해결»을 적은 글이다 — 그대로 보여 준다.
    const back = live
      ? '<div class="bib-edit-actions"><button id="ef-conn-recorded" type="button">기록된 기준값으로 보기</button></div>'
      : "";
    form.innerHTML =
      `<div class="entity-promo-note" style="white-space:pre-wrap;">${_escHtml(data.error || `서버 오류 (${resp.status})`)}</div>` +
      back;
    const b = document.getElementById("ef-conn-recorded");
    if (b) b.addEventListener("click", () => _renderConnectome(false));
    return;
  }

  const lib = data.library || {};
  const ref = data.reference || {};
  const rows = data.rows || [];
  const notes = data.notes || [];

  const fmt = (v) => (typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "—");
  const gap = (v) =>
    typeof v === "number"
      ? `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%p`
      : "—";

  form.innerHTML = `
    <div class="entity-promo-note">
      이 저장소의 관계 <b>${lib.count || 0}</b>건을 커넥톰 연합 구조
      (<b>${_escHtml(ref.lineage || "")}</b>, ${_escHtml(ref.source || "")})와
      나란히 놓습니다. <b>점수를 매기지 않습니다</b> — 커넥톰은 참고 좌표이지
      목표가 아닙니다.
    </div>
    ${
      notes.length
        ? `<ul class="entity-promo-note" style="margin:8px 0;padding-left:18px;">${notes
            .map((n) => `<li>${_escHtml(n)}</li>`)
            .join("")}</ul>`
        : ""
    }
    <table class="bib-table" style="width:100%;margin-top:8px;">
      <thead>
        <tr><th>항목</th><th>이 저장소</th><th>커넥톰</th><th>차이</th></tr>
      </thead>
      <tbody>
        ${rows
          .map(
            (r) => `<tr>
              <td>${_escHtml(r.label)}</td>
              <td>${fmt(r.library)}</td>
              <td>${fmt(r.reference)}${r.reference_live ? ' <span title="이 줄은 방금 neuPrint 에 물어 새로 쟀습니다">◆</span>' : ""}</td>
              <td>${gap(r.gap)}</td>
            </tr>`
          )
          .join("")}
      </tbody>
    </table>
    ${
      data.live
        ? '<div class="entity-promo-note" style="margin-top:6px;">◆ 표시한 줄만 방금 다시 쟀습니다. 나머지는 기록된 기준값입니다 — 무게 분포는 부호 질의로 뽑을 수 없습니다.</div>'
        : ""
    }
    <div class="bib-edit-actions">
      <button id="ef-conn-live" type="button" title="neuPrint 에 직접 물어 기준값을 새로 뽑습니다 — 배포본에는 없는 기능입니다">
        기준값 다시 재기
      </button>
    </div>
  `;

  const liveBtn = document.getElementById("ef-conn-live");
  if (liveBtn) {
    liveBtn.addEventListener("click", () => {
      liveBtn.disabled = true;
      liveBtn.textContent = "재는 중…";
      _renderConnectome(true);
    });
  }
}


/* ──────────────────────────
   LLM 협업 (UI 스텁)
   ────────────────────────── */

function _openLlmRequestDialog() {
  document.getElementById("llm-dialog-overlay").style.display = "";
}


/**
 * LLM 초안 (extractor=llm, status=draft) 엔티티를 검토 영역에 표시한다.
 */
function _renderLlmDraftReview() {
  const section = document.getElementById("entity-llm-review");
  const list = document.getElementById("entity-llm-review-list");
  if (!section || !list) return;

  // 모든 엔티티 중 extractor=llm, status=draft 인 것만
  const drafts = [];
  const ent = entityState.entities || {};
  const typeMap = {
    tag: "tags", concept: "concepts", agent: "agents", relation: "relations",
  };

  for (const [type, key] of Object.entries(typeMap)) {
    (ent[key] || []).forEach((e) => {
      if (e.extractor === "llm" && e.status === "draft") {
        drafts.push({ ...e, _entityType: type });
      }
    });
  }

  if (drafts.length === 0) {
    section.style.display = "none";
    return;
  }

  section.style.display = "";
  list.innerHTML = drafts.map((d) => {
    const info = ENTITY_TYPE_INFO[d._entityType] || {};
    const label = d[info.displayField] || d.id?.substring(0, 8) || "—";
    return `<div class="llm-review-item" data-entity-type="${d._entityType}" data-entity-id="${d.id}">
      <span class="entity-type-badge ${info.cssClass}">${info.label}</span>
      <span class="entity-list-label">${_escHtml(label)}</span>
      <span class="llm-review-actions">
        <button class="llm-approve-btn" data-action="approve">승인</button>
        <button class="llm-edit-btn" data-action="edit">수정</button>
        <button class="llm-reject-btn" data-action="reject">거부</button>
      </span>
    </div>`;
  }).join("");

  // 버튼 이벤트
  list.querySelectorAll(".llm-review-item").forEach((item) => {
    item.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const action = btn.dataset.action;
        const type = item.dataset.entityType;
        const id = item.dataset.entityId;
        _handleLlmReviewAction(action, type, id);
      });
    });
  });
}


/**
 * LLM 검토 액션 처리: 승인(active), 수정(편집 다이얼로그), 거부(deprecated).
 */
async function _handleLlmReviewAction(action, entityType, entityId) {
  if (!interpState || !interpState.interpId) return;

  if (action === "edit") {
    _openEntityEditDialog(entityType, entityId);
    return;
  }

  const newStatus = action === "approve" ? "active" : "deprecated";

  try {
    const resp = await fetch(
      `/api/interpretations/${interpState.interpId}/entities/${entityType}/${entityId}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ updates: { status: newStatus } }),
      }
    );
    if (!resp.ok) {
      const errBody = await resp.json().catch(() => ({}));
      showToast(errBody.error || `상태 변경 실패: 서버 오류 (${resp.status})`, 'error');
      return;
    }
    const result = await resp.json();
    if (result.error) {
      showToast(result.error, 'error');
      return;
    }
    _loadEntitiesForCurrentPage();
  } catch (err) {
    showToast(`상태 변경 실패: ${err.message}`, 'error');
  }
}


/* ──────────────────────────
   도구 바 버튼 표시/숨김
   ────────────────────────── */

function _updateToolbarButtons() {
  const tbBtn = document.getElementById("entity-create-textblock-btn");
  const llmBtn = document.getElementById("entity-llm-request-btn");

  const show = interpState && interpState.active && interpState.interpId;
  if (tbBtn) tbBtn.style.display = show ? "" : "none";
  if (llmBtn) llmBtn.style.display = show ? "" : "none";
  // 「커넥톰 대조」는 여기서 다루지 않는다 — 이 둘이 사는 `#interp-panel` 은
  // 어느 모드에서도 열리지 않고(2026-09-22 실측), `interpState.active` 가 참이
  // 되는 길도 없다. 그 단추는 살아 있는 엔티티 사이드바에 두고 항상 보인다.
}


/* ──────────────────────────
   유틸리티
   ────────────────────────── */

function _escHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
