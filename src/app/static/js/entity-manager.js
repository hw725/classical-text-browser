/* ──────────────────────────────────────────
   Phase 8: 코어 스키마 엔티티 관리 모듈
   ──────────────────────────────────────────

   해석 저장소 내의 코어 스키마 엔티티
   (Work, TextBlock, Tag, Concept, Agent, Relation)를
   생성·조회·편집하는 프론트엔드 모듈.

   의존:
     - viewerState (sidebar-tree.js)
     - interpState (interpretation.js)
   ────────────────────────────────────────── */

// eslint-disable-next-line no-unused-vars
const entityState = {
  active: false,            // 엔티티 패널 활성 여부
  entities: {},             // 캐시: { works:[], blocks:[], tags:[], concepts:[], agents:[], relations:[] }
  currentFilter: "all",     // 유형 필터: all / text_block / tag / concept / agent / relation / work
  pageFilter: true,         // "현재 페이지만" 체크 여부
  editingEntity: null,      // 편집 중인 엔티티 (null이면 신규 생성)
  editingType: null,        // 편집 중인 엔티티 유형
};

// 엔티티 유형별 표시 정보
const ENTITY_TYPE_INFO = {
  work:       { label: "Work",      cssClass: "type-work",       displayField: "title" },
  text_block: { label: "TextBlock", cssClass: "type-text-block", displayField: "original_text" },
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

  // "TextBlock 만들기" 버튼
  const tbBtn = document.getElementById("entity-create-textblock-btn");
  if (tbBtn) {
    tbBtn.addEventListener("click", _openTextBlockCreator);
  }

  // "LLM에게 요청" 버튼
  const llmBtn = document.getElementById("entity-llm-request-btn");
  if (llmBtn) {
    llmBtn.addEventListener("click", _openLlmRequestDialog);
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

  const types = ["work", "text_block", "tag", "concept", "agent", "relation"];
  const typeMap = { work: "works", text_block: "blocks", tag: "tags", concept: "concepts", agent: "agents", relation: "relations" };

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

    return `<div class="entity-list-item" data-entity-type="${item._entityType}" data-entity-id="${item.id}">
      <span class="entity-type-badge ${info.cssClass}">${info.label}</span>
      <span class="entity-list-label" title="${_escHtml(label)}">${_escHtml(truncLabel)}</span>
      <span class="entity-status-badge status-${item.status || "draft"}">${item.status || "draft"}</span>
      <span class="entity-list-id">${shortId}</span>
      <span class="entity-list-actions">
        ${isTag ? `<button class="entity-promote-btn" data-tag-id="${item.id}" title="Concept으로 승격">승격</button>` : ""}
      </span>
    </div>`;
  }).join("");

  // 클릭 이벤트: 편집 다이얼로그
  container.querySelectorAll(".entity-list-item").forEach((el) => {
    el.addEventListener("click", (e) => {
      // 승격 버튼 클릭은 별도 처리
      if (e.target.classList.contains("entity-promote-btn")) return;
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
}


/**
 * 현재 필터에 따라 엔티티를 정렬·필터하여 반환한다.
 */
function _getFilteredEntities() {
  const ent = entityState.entities || {};
  const typeMap = {
    work: "works", text_block: "blocks", tag: "tags",
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
      <option value="work">Work (작품)</option>
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
        alert(entity.error);
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
    .catch((err) => alert(`엔티티 조회 실패: ${err.message}`));
}


/**
 * 엔티티 유형에 맞는 폼 필드 HTML을 생성한다.
 */
function _buildFormFields(entityType, existing) {
  const val = (field) => existing ? _escHtml(existing[field] || "") : "";
  const statusOptions = _buildStatusOptions(existing ? existing.status : "draft");

  switch (entityType) {
    case "work":
      return `
        <label class="bib-edit-label">제목 (title)</label>
        <input id="ef-title" type="text" class="bib-input" value="${val("title")}" placeholder="예: 蒙求" />
        <label class="bib-edit-label">저자 (author)</label>
        <input id="ef-author" type="text" class="bib-input" value="${val("author")}" placeholder="예: 李瀚" />
        <label class="bib-edit-label">시대 (period)</label>
        <input id="ef-period" type="text" class="bib-input" value="${val("period")}" placeholder="예: 唐" />
        <label class="bib-edit-label">상태 (status)</label>
        <select id="ef-status" class="bib-select" style="width:100%;">${statusOptions}</select>
      `;

    case "tag":
      return `
        <label class="bib-edit-label">TextBlock ID (block_id)</label>
        <input id="ef-block-id" type="text" class="bib-input" value="${val("block_id")}" placeholder="TextBlock UUID" />
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

    case "concept":
      return `
        <label class="bib-edit-label">라벨 (label)</label>
        <input id="ef-label" type="text" class="bib-input" value="${val("label")}" placeholder="예: 王戎" />
        <label class="bib-edit-label">유효 범위 Work ID (scope_work, 비우면 전역)</label>
        <input id="ef-scope-work" type="text" class="bib-input" value="${val("scope_work")}" placeholder="Work UUID (전역이면 비움)" />
        <label class="bib-edit-label">설명 (description)</label>
        <textarea id="ef-description" class="bib-textarea" rows="3" placeholder="학술적 설명">${val("description")}</textarea>
        <label class="bib-edit-label">상태 (status)</label>
        <select id="ef-status" class="bib-select" style="width:100%;">${statusOptions}</select>
      `;

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
        </select>
        <label class="bib-edit-label">자유 텍스트 목적어 (object_value, 선택)</label>
        <input id="ef-object-value" type="text" class="bib-input" value="${val("object_value")}" placeholder="예: 瑯邪臨沂" />
        <label class="bib-edit-label">신뢰도 (confidence): <span id="ef-conf-val">${existing ? (existing.confidence ?? 0.8) : 0.8}</span></label>
        <input id="ef-confidence" type="range" min="0" max="1" step="0.05" value="${existing ? (existing.confidence ?? 0.8) : 0.8}" class="corr-slider" />
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
    case "work": {
      const title = _val("ef-title");
      if (!title) return null;
      return {
        title,
        author: _val("ef-author") || null,
        period: _val("ef-period") || null,
        status: _val("ef-status") || "draft",
        metadata: null,
      };
    }

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
      return {
        label,
        scope_work: _val("ef-scope-work") || null,
        description: _val("ef-description") || null,
        concept_features: null,
        status: _val("ef-status") || "draft",
        metadata: null,
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
        evidence_blocks: null,
        confidence: _numVal("ef-confidence"),
        extractor: _val("ef-extractor") || "manual",
        status: _val("ef-status") || "draft",
        metadata: null,
      };
    }

    default:
      return null;
  }
}


function _closeEntityDialog() {
  document.getElementById("entity-dialog-overlay").style.display = "none";
  entityState.editingEntity = null;
  entityState.editingType = null;
}


/* ──────────────────────────
   TextBlock 생성 (source_ref 자동)
   ────────────────────────── */

/**
 * "TextBlock 만들기" 전용 다이얼로그를 연다.
 * source_ref 필드가 현재 문서/페이지 정보로 자동 채워진다.
 */
async function _openTextBlockCreator() {
  if (!interpState || !interpState.interpId || !viewerState || !viewerState.docId) {
    alert("해석 저장소와 문헌을 먼저 선택하세요.");
    return;
  }

  entityState.editingEntity = null;
  entityState.editingType = "text_block";

  const form = document.getElementById("entity-dialog-form");
  const title = document.getElementById("entity-dialog-title");
  title.textContent = "TextBlock 만들기 (source_ref 자동 채움)";

  // Work 목록 로드
  let works = [];
  try {
    const resp = await fetch(`/api/interpretations/${interpState.interpId}/entities/work`);
    if (!resp.ok) throw new Error(`서버 오류 (${resp.status})`);
    const data = await resp.json();
    works = data.entities || [];
  } catch { /* Work 목록 로드 실패 시 빈 목록으로 진행 */ }

  const workOptions = works.map((w) =>
    `<option value="${w.id}">${_escHtml(w.title)} (${w.id.substring(0, 8)})</option>`
  ).join("");

  form.innerHTML = `
    <label class="bib-edit-label">원본 문헌</label>
    <input type="text" class="bib-input" value="${viewerState.docId}" readonly />
    <label class="bib-edit-label">페이지</label>
    <input type="text" class="bib-input" value="${viewerState.pageNum || 1}" readonly />
    <label class="bib-edit-label">LayoutBlock ID (선택)</label>
    <input id="ef-tb-layout-block" type="text" class="bib-input" placeholder="예: p01_b01 (없으면 비움)" />
    <label class="bib-edit-label">원문 텍스트 (original_text)</label>
    <textarea id="ef-tb-original-text" class="bib-textarea" rows="3" placeholder="L4 텍스트에서 블록에 해당하는 부분을 붙여넣으세요"></textarea>
    <label class="bib-edit-label">소속 Work</label>
    <select id="ef-tb-work-id" class="bib-select" style="width:100%;">
      <option value="">Work를 선택하세요</option>
      ${workOptions}
    </select>
    <button id="ef-tb-auto-work" class="text-btn" type="button" style="margin-top:4px;">Work 자동 생성</button>
    <label class="bib-edit-label">순서 인덱스 (sequence_index, 0-based)</label>
    <input id="ef-tb-seq-index" type="number" class="bib-input" value="0" min="0" />
  `;

  // Work 자동 생성 버튼
  const autoWorkBtn = document.getElementById("ef-tb-auto-work");
  if (autoWorkBtn) {
    autoWorkBtn.addEventListener("click", async () => {
      autoWorkBtn.textContent = "생성 중...";
      autoWorkBtn.disabled = true;
      try {
        const resp = await fetch(
          `/api/interpretations/${interpState.interpId}/entities/work/auto-create`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ document_id: viewerState.docId }),
          }
        );
        if (!resp.ok) {
          const errBody = await resp.json().catch(() => ({}));
          throw new Error(errBody.error || `서버 오류 (${resp.status})`);
        }
        const result = await resp.json();
        if (result.work) {
          const sel = document.getElementById("ef-tb-work-id");
          const opt = document.createElement("option");
          opt.value = result.work.id;
          opt.textContent = `${result.work.title} (${result.work.id.substring(0, 8)})`;
          opt.selected = true;
          sel.appendChild(opt);
          autoWorkBtn.textContent = result.status === "existing" ? "기존 Work 사용" : "Work 생성 완료";
        }
      } catch (err) {
        autoWorkBtn.textContent = `실패: ${err.message}`;
      }
    });
  }

  // 저장 버튼 동작을 TextBlock 전용으로 교체
  const saveBtn = document.getElementById("entity-dialog-save");
  // 기존 리스너 제거를 위해 교체
  const newSaveBtn = saveBtn.cloneNode(true);
  saveBtn.parentNode.replaceChild(newSaveBtn, saveBtn);
  newSaveBtn.addEventListener("click", _saveTextBlockFromSource);

  document.getElementById("entity-dialog-status").textContent = "";
  document.getElementById("entity-dialog-overlay").style.display = "";
}


/**
 * TextBlock from source 저장 처리.
 */
async function _saveTextBlockFromSource() {
  const statusEl = document.getElementById("entity-dialog-status");

  const originalText = (document.getElementById("ef-tb-original-text") || {}).value?.trim();
  const workId = (document.getElementById("ef-tb-work-id") || {}).value;
  const seqIndex = parseInt((document.getElementById("ef-tb-seq-index") || {}).value, 10);
  const layoutBlockId = (document.getElementById("ef-tb-layout-block") || {}).value?.trim() || null;

  if (!originalText) {
    statusEl.textContent = "원문 텍스트를 입력하세요";
    statusEl.style.color = "#ef4444";
    return;
  }
  if (!workId) {
    statusEl.textContent = "소속 Work를 선택하세요";
    statusEl.style.color = "#ef4444";
    return;
  }

  statusEl.textContent = "저장 중...";
  statusEl.style.color = "#3b82f6";

  try {
    const resp = await fetch(
      `/api/interpretations/${interpState.interpId}/entities/text_block/from-source`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_id: viewerState.docId,
          part_id: viewerState.partId || "vol1",
          page_num: viewerState.pageNum || 1,
          layout_block_id: layoutBlockId,
          original_text: originalText,
          work_id: workId,
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
 * TextBlock 다이얼로그에서 교체된 저장 버튼을 원래 핸들러로 복원한다.
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
          scope_work: null,
          description: null,
        }),
      }
    );
    if (!resp.ok) {
      const errBody = await resp.json().catch(() => ({}));
      alert(errBody.error || `승격 실패: 서버 오류 (${resp.status})`);
      return;
    }
    const result = await resp.json();
    if (result.error) {
      alert(result.error);
      return;
    }
    _loadEntitiesForCurrentPage();
  } catch (err) {
    alert(`승격 실패: ${err.message}`);
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
      alert(errBody.error || `상태 변경 실패: 서버 오류 (${resp.status})`);
      return;
    }
    const result = await resp.json();
    if (result.error) {
      alert(result.error);
      return;
    }
    _loadEntitiesForCurrentPage();
  } catch (err) {
    alert(`상태 변경 실패: ${err.message}`);
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
