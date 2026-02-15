/**
 * 서지정보 패널 — bibliography.json 표시 + 외부 소스 가져오기
 *
 * 기능:
 *   1. 문헌 선택 시 bibliography.json 내용을 사이드바 하단에 표시
 *   2. 빈 필드는 [미입력] 표시
 *   3. "서지정보 가져오기" 버튼 → 파서 선택 + 검색 다이얼로그
 *   4. 검색 결과 선택 → 매핑 → 저장
 *   5. 수동 편집 가능
 *
 * 의존성: sidebar-tree.js (viewerState)
 *
 * 왜 이렇게 하는가:
 *   - 비개발자 연구자가 서지정보를 한눈에 확인하고,
 *     외부 소스(NDL, 국립공문서관)에서 자동으로 가져올 수 있도록 한다.
 *   - platform-v7.md §7.3의 파서 아키텍처와 GUI가 연결되는 지점.
 */


/* ──────────────────────────
   전역 상태
   ────────────────────────── */

/** 현재 표시 중인 서지정보 데이터 */
let _currentBibliography = null;

/** 등록된 파서 목록 (초기화 시 로드) */
let _parsers = [];


/* ──────────────────────────
   초기화
   ────────────────────────── */

/**
 * 서지정보 패널을 초기화한다.
 *
 * 목적: workspace.js의 DOMContentLoaded에서 호출되어,
 *       파서 목록을 로드하고 이벤트를 바인딩한다.
 */
// eslint-disable-next-line no-unused-vars
function initBibliography() {
  _loadParsers();
  _bindEvents();
}


/**
 * 등록된 파서 목록을 서버에서 로드한다.
 */
async function _loadParsers() {
  try {
    const res = await fetch("/api/parsers");
    if (!res.ok) return;
    const data = await res.json();
    _parsers = data.parsers || [];
  } catch {
    // 파서 로드 실패는 치명적이지 않다
    _parsers = [];
  }
}


/**
 * 이벤트를 바인딩한다.
 */
function _bindEvents() {
  // "서지정보 가져오기" 버튼
  const fetchBtn = document.getElementById("bib-fetch-btn");
  if (fetchBtn) {
    fetchBtn.addEventListener("click", _openFetchDialog);
  }

  // 수동 편집 버튼
  const editBtn = document.getElementById("bib-edit-btn");
  if (editBtn) {
    editBtn.addEventListener("click", _openEditDialog);
  }

  // 다이얼로그 닫기 버튼들
  document.querySelectorAll(".bib-dialog-close").forEach((btn) => {
    btn.addEventListener("click", _closeAllDialogs);
  });

  // 다이얼로그 오버레이 클릭으로 닫기
  // — 오버레이 배경(반투명 영역)을 클릭할 때만 닫고,
  //   다이얼로그 내부(입력칸 등)를 클릭할 때는 닫지 않는다.
  const overlay = document.getElementById("bib-dialog-overlay");
  if (overlay) {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) _closeAllDialogs();
    });
  }

  // 검색 실행 버튼
  const searchBtn = document.getElementById("bib-search-btn");
  if (searchBtn) {
    searchBtn.addEventListener("click", _executeSearch);
  }

  // 검색 입력에서 Enter 키
  const searchInput = document.getElementById("bib-search-input");
  if (searchInput) {
    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") _executeSearch();
    });
  }

  // URL 가져오기 버튼
  const urlBtn = document.getElementById("bib-url-btn");
  if (urlBtn) {
    urlBtn.addEventListener("click", _fetchFromUrl);
  }

  // URL 입력에서 Enter 키
  const urlInput = document.getElementById("bib-url-input");
  if (urlInput) {
    urlInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") _fetchFromUrl();
    });
  }

  // 탭 전환 버튼
  document.querySelectorAll(".bib-tab").forEach((tab) => {
    tab.addEventListener("click", () => _switchTab(tab.dataset.tab));
  });

  // 편집 저장 버튼
  const editSaveBtn = document.getElementById("bib-edit-save-btn");
  if (editSaveBtn) {
    editSaveBtn.addEventListener("click", _saveEditedBibliography);
  }
}


/* ──────────────────────────
   서지정보 로드 + 표시
   ────────────────────────── */

/**
 * 문헌의 서지정보를 로드하여 패널에 표시한다.
 *
 * sidebar-tree.js의 _selectPage()에서 호출된다.
 */
// eslint-disable-next-line no-unused-vars
function loadBibliography(docId) {
  if (!docId) return;

  const section = document.getElementById("bib-section");
  if (!section) return;

  // 서지정보 섹션 표시
  section.style.display = "";

  fetch(`/api/documents/${docId}/bibliography`)
    .then((res) => {
      if (!res.ok) throw new Error("서지정보 조회 실패");
      return res.json();
    })
    .then((bib) => {
      _currentBibliography = bib;
      _renderBibliography(bib);
    })
    .catch(() => {
      _currentBibliography = null;
      _renderBibliography({});
    });
}


/**
 * 서지정보를 패널에 렌더링한다.
 *
 * 왜 이렇게 하는가:
 *   - 비개발자가 서지정보를 한눈에 파악할 수 있도록,
 *     각 필드를 라벨-값 쌍으로 표시한다.
 *   - 빈 필드는 [미입력]으로 표시하여, 아직 채워지지 않은 부분을 알 수 있다.
 */
function _renderBibliography(bib) {
  const container = document.getElementById("bib-fields");
  if (!container) return;

  const fields = [
    { key: "title", label: "제목" },
    { key: "title_reading", label: "독음" },
    { key: "creator", label: "저자", format: _formatCreator },
    { key: "contributors", label: "기여자", format: _formatContributors },
    { key: "date_created", label: "성립/간행" },
    { key: "edition_type", label: "판종" },
    { key: "physical_description", label: "형태사항" },
    { key: "material_type", label: "자료유형" },
    { key: "subject", label: "주제어", format: _formatArray },
    { key: "classification", label: "분류", format: _formatClassification },
    { key: "series_title", label: "총서명" },
    { key: "repository", label: "소장처", format: _formatRepository },
    { key: "digital_source", label: "디지털 원본", format: _formatDigitalSource },
    { key: "notes", label: "비고" },
  ];

  let html = "";
  for (const field of fields) {
    const value = bib[field.key];
    let display;

    if (field.format) {
      display = field.format(value);
    } else if (value === null || value === undefined || value === "") {
      display = '<span class="bib-empty">[미입력]</span>';
    } else {
      display = _escapeHtml(String(value));
    }

    html += `
      <div class="bib-field">
        <span class="bib-label">${field.label}</span>
        <span class="bib-value">${display}</span>
      </div>
    `;
  }

  // 매핑 정보 (있으면 표시)
  if (bib._mapping_info) {
    html += `
      <div class="bib-field bib-mapping-info">
        <span class="bib-label">매핑 출처</span>
        <span class="bib-value">${bib._mapping_info.parser_id || "수동"} (${bib._mapping_info.api_variant || "-"})</span>
      </div>
    `;
  }

  container.innerHTML = html;
}


/* ──────────────────────────
   탭 전환
   ────────────────────────── */

/**
 * 서지정보 가져오기 다이얼로그의 탭을 전환한다.
 *
 * 왜 이렇게 하는가:
 *   URL 붙여넣기가 주 워크플로우이므로 기본 탭이다.
 *   직접 검색은 URL을 모를 때 사용하는 보조 기능이다.
 */
function _switchTab(tabName) {
  // 탭 버튼 활성화
  document.querySelectorAll(".bib-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === tabName);
  });

  // 탭 내용 전환
  const urlTab = document.getElementById("bib-tab-url");
  const searchTab = document.getElementById("bib-tab-search");
  if (urlTab) urlTab.style.display = tabName === "url" ? "" : "none";
  if (searchTab) searchTab.style.display = tabName === "search" ? "" : "none";
}


/* ──────────────────────────
   URL 붙여넣기로 서지정보 가져오기
   ────────────────────────── */

/**
 * URL을 자동 판별하여 서지정보를 가져온다.
 *
 * 왜 이렇게 하는가:
 *   연구자가 외부 사이트에서 URL을 복사해 붙여넣기만 하면
 *   파서 선택·검색·결과 선택 과정 없이 서지정보가 채워진다.
 */
async function _fetchFromUrl() {
  if (!viewerState.docId) return;

  const urlInput = document.getElementById("bib-url-input");
  const statusEl = document.getElementById("bib-url-status");
  if (!urlInput) return;

  const url = urlInput.value.trim();
  if (!url) {
    if (statusEl) statusEl.textContent = "URL을 입력하세요.";
    return;
  }

  if (statusEl) {
    statusEl.textContent = "가져오는 중...";
    statusEl.className = "bib-url-status";
  }

  try {
    // 문서에 바로 저장하는 편의 엔드포인트 사용
    const res = await fetch(
      `/api/documents/${viewerState.docId}/bibliography/from-url`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      }
    );

    const data = await res.json();

    if (!res.ok) {
      let errorMsg = data.error || "가져오기 실패";
      // 지원 소스 안내
      if (data.supported_sources) {
        errorMsg += "\n지원: " + data.supported_sources
          .map((s) => s.description)
          .join(", ");
      }
      throw new Error(errorMsg);
    }

    // 성공: 패널 갱신 + 다이얼로그 닫기
    _currentBibliography = data.bibliography;
    _renderBibliography(data.bibliography);
    _closeAllDialogs();

    if (statusEl) {
      statusEl.textContent = `저장 완료 (${data.parser_id})`;
      statusEl.className = "bib-url-status bib-url-success";
    }
  } catch (err) {
    if (statusEl) {
      statusEl.textContent = err.message;
      statusEl.className = "bib-url-status bib-url-error";
    }
  }
}


/* ──────────────────────────
   서지정보 가져오기 다이얼로그
   ────────────────────────── */

/**
 * "서지정보 가져오기" 다이얼로그를 연다.
 */
function _openFetchDialog() {
  if (!viewerState.docId) {
    alert("문헌을 먼저 선택하세요.");
    return;
  }

  const overlay = document.getElementById("bib-dialog-overlay");
  const dialog = document.getElementById("bib-fetch-dialog");
  if (!overlay || !dialog) return;

  // 파서 목록으로 드롭다운 채우기
  const parserSelect = document.getElementById("bib-parser-select");
  if (parserSelect) {
    parserSelect.innerHTML = _parsers
      .map((p) => `<option value="${p.id}">${p.name}</option>`)
      .join("");
  }

  // 검색 결과 초기화
  const resultsContainer = document.getElementById("bib-search-results");
  if (resultsContainer) resultsContainer.innerHTML = "";

  // 검색 입력 초기화
  const searchInput = document.getElementById("bib-search-input");
  if (searchInput) {
    // 현재 문헌 제목을 기본 검색어로
    searchInput.value = _currentBibliography?.title || "";
  }

  overlay.style.display = "flex";
  dialog.style.display = "";
  document.getElementById("bib-edit-dialog")?.style.setProperty("display", "none");
}


/**
 * 모든 다이얼로그를 닫는다.
 */
function _closeAllDialogs() {
  const overlay = document.getElementById("bib-dialog-overlay");
  if (overlay) overlay.style.display = "none";
}


/**
 * 파서 검색을 실행한다.
 */
async function _executeSearch() {
  const parserSelect = document.getElementById("bib-parser-select");
  const searchInput = document.getElementById("bib-search-input");
  const resultsContainer = document.getElementById("bib-search-results");
  const statusEl = document.getElementById("bib-search-status");

  if (!parserSelect || !searchInput || !resultsContainer) return;

  const parserId = parserSelect.value;
  const query = searchInput.value.trim();

  if (!query) {
    if (statusEl) statusEl.textContent = "검색어를 입력하세요.";
    return;
  }

  // 로딩 표시
  resultsContainer.innerHTML = '<div class="bib-loading">검색 중...</div>';
  if (statusEl) statusEl.textContent = "";

  try {
    const res = await fetch(`/api/parsers/${parserId}/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, cnt: 10 }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || "검색 실패");
    }

    const data = await res.json();
    const results = data.results || [];

    if (results.length === 0) {
      resultsContainer.innerHTML = '<div class="bib-no-results">검색 결과가 없습니다.</div>';
      if (statusEl) statusEl.textContent = "0건";
      return;
    }

    if (statusEl) statusEl.textContent = `${results.length}건`;

    // 검색 결과 렌더링
    resultsContainer.innerHTML = results
      .map(
        (r, i) => `
        <div class="bib-result-item" data-index="${i}">
          <div class="bib-result-title">${_escapeHtml(r.title || "(제목 없음)")}</div>
          <div class="bib-result-summary">${_escapeHtml(r.summary || "")}</div>
        </div>
      `
      )
      .join("");

    // 결과 항목 클릭 이벤트
    resultsContainer.querySelectorAll(".bib-result-item").forEach((item) => {
      item.addEventListener("click", () => {
        _selectSearchResult(parserId, results[parseInt(item.dataset.index)]);
      });
    });
  } catch (err) {
    resultsContainer.innerHTML = `<div class="bib-error">${_escapeHtml(err.message)}</div>`;
  }
}


/**
 * 검색 결과 항목을 선택하여 매핑 + 저장한다.
 *
 * 왜 fetch-and-map을 사용하는가:
 *   NDL은 검색 결과에 전체 메타데이터가 포함되므로 map만으로 충분하다.
 *   하지만 KORCIS는 검색 결과에 기본 정보만 있고, MARC 데이터는
 *   별도의 fetch_detail 호출이 필요하다.
 *   fetch-and-map 엔드포인트는 둘 다 처리한다.
 */
async function _selectSearchResult(parserId, result) {
  if (!viewerState.docId) return;

  const statusEl = document.getElementById("bib-search-status");
  if (statusEl) statusEl.textContent = "매핑 중...";

  try {
    // item_id가 있으면 fetch-and-map (상세 조회 + 매핑), 없으면 기존 map
    let bibliography;
    if (result.item_id) {
      const fetchMapRes = await fetch(`/api/parsers/${parserId}/fetch-and-map`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_id: result.item_id }),
      });
      if (!fetchMapRes.ok) {
        const err = await fetchMapRes.json();
        throw new Error(err.error || "매핑 실패");
      }
      const fetchMapData = await fetchMapRes.json();
      bibliography = fetchMapData.bibliography;
    } else {
      // 기존 방식: raw_data로 직접 매핑
      const mapRes = await fetch(`/api/parsers/${parserId}/map`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw_data: result.raw }),
      });
      if (!mapRes.ok) {
        const err = await mapRes.json();
        throw new Error(err.error || "매핑 실패");
      }
      const mapData = await mapRes.json();
      bibliography = mapData.bibliography;
    }

    // 저장 요청
    const saveRes = await fetch(`/api/documents/${viewerState.docId}/bibliography`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bibliography),
    });

    if (!saveRes.ok) {
      const err = await saveRes.json();
      throw new Error(err.error || "저장 실패");
    }

    // 성공: 패널 갱신 + 다이얼로그 닫기
    _currentBibliography = bibliography;
    _renderBibliography(bibliography);
    _closeAllDialogs();

    if (statusEl) statusEl.textContent = "저장 완료";
  } catch (err) {
    if (statusEl) statusEl.textContent = `오류: ${err.message}`;
  }
}


/* ──────────────────────────
   수동 편집 다이얼로그
   ────────────────────────── */

/**
 * 수동 편집 다이얼로그를 연다.
 */
function _openEditDialog() {
  if (!viewerState.docId) {
    alert("문헌을 먼저 선택하세요.");
    return;
  }

  const overlay = document.getElementById("bib-dialog-overlay");
  const dialog = document.getElementById("bib-edit-dialog");
  if (!overlay || !dialog) return;

  // 현재 서지정보로 폼 채우기
  const bib = _currentBibliography || {};

  _setEditField("bib-edit-title", bib.title);
  _setEditField("bib-edit-title-reading", bib.title_reading);
  _setEditField("bib-edit-creator-name", bib.creator?.name);
  _setEditField("bib-edit-creator-reading", bib.creator?.name_reading);
  _setEditField("bib-edit-creator-role", bib.creator?.role);
  _setEditField("bib-edit-creator-period", bib.creator?.period);
  _setEditField("bib-edit-date", bib.date_created);
  _setEditField("bib-edit-edition", bib.edition_type);
  _setEditField("bib-edit-physical", bib.physical_description);
  _setEditField("bib-edit-material", bib.material_type);
  _setEditField("bib-edit-series", bib.series_title);
  _setEditField("bib-edit-notes", bib.notes);

  overlay.style.display = "flex";
  dialog.style.display = "";
  document.getElementById("bib-fetch-dialog")?.style.setProperty("display", "none");
}


/**
 * 편집 폼의 내용을 서지정보로 저장한다.
 */
async function _saveEditedBibliography() {
  if (!viewerState.docId) return;

  const bib = _currentBibliography || {};

  // 폼에서 값 수집
  const title = _getEditField("bib-edit-title");
  const creatorName = _getEditField("bib-edit-creator-name");

  const updated = {
    ...bib,
    title: title || bib.title,
    title_reading: _getEditField("bib-edit-title-reading") || bib.title_reading,
    creator: creatorName
      ? {
          name: creatorName,
          name_reading: _getEditField("bib-edit-creator-reading") || bib.creator?.name_reading || null,
          role: _getEditField("bib-edit-creator-role") || bib.creator?.role || null,
          period: _getEditField("bib-edit-creator-period") || bib.creator?.period || null,
        }
      : bib.creator || null,
    date_created: _getEditField("bib-edit-date") || bib.date_created,
    edition_type: _getEditField("bib-edit-edition") || bib.edition_type,
    physical_description: _getEditField("bib-edit-physical") || bib.physical_description,
    material_type: _getEditField("bib-edit-material") || bib.material_type,
    series_title: _getEditField("bib-edit-series") || bib.series_title,
    notes: _getEditField("bib-edit-notes") || bib.notes,
  };

  const statusEl = document.getElementById("bib-edit-status");

  try {
    const res = await fetch(`/api/documents/${viewerState.docId}/bibliography`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updated),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || "저장 실패");
    }

    _currentBibliography = updated;
    _renderBibliography(updated);
    _closeAllDialogs();
  } catch (err) {
    if (statusEl) statusEl.textContent = `오류: ${err.message}`;
  }
}


/* ──────────────────────────
   포맷 유틸리티
   ────────────────────────── */

function _formatCreator(creator) {
  if (!creator) return '<span class="bib-empty">[미입력]</span>';
  let text = _escapeHtml(creator.name || "");
  if (creator.name_reading) text += ` (${_escapeHtml(creator.name_reading)})`;
  if (creator.period) text += ` — ${_escapeHtml(creator.period)}`;
  return text || '<span class="bib-empty">[미입력]</span>';
}

function _formatContributors(contributors) {
  if (!contributors || contributors.length === 0) {
    return '<span class="bib-empty">[미입력]</span>';
  }
  return contributors
    .map((c) => {
      let text = _escapeHtml(c.name || "");
      if (c.role) text += ` (${_escapeHtml(c.role)})`;
      return text;
    })
    .join(", ");
}

function _formatArray(arr) {
  if (!arr || arr.length === 0) return '<span class="bib-empty">[미입력]</span>';
  return arr.map((s) => _escapeHtml(s)).join(", ");
}

function _formatClassification(cls) {
  if (!cls || typeof cls !== "object") return '<span class="bib-empty">[미입력]</span>';
  return Object.entries(cls)
    .map(([k, v]) => `${_escapeHtml(k)}: ${_escapeHtml(v)}`)
    .join(", ");
}

function _formatRepository(repo) {
  if (!repo) return '<span class="bib-empty">[미입력]</span>';
  let text = _escapeHtml(repo.name || "");
  if (repo.name_ko) text += ` (${_escapeHtml(repo.name_ko)})`;
  if (repo.call_number) text += ` — ${_escapeHtml(repo.call_number)}`;
  return text || '<span class="bib-empty">[미입력]</span>';
}

function _formatDigitalSource(ds) {
  if (!ds) return '<span class="bib-empty">[미입력]</span>';
  let text = _escapeHtml(ds.platform || "");
  if (ds.source_url) {
    text += ` <a href="${_escapeHtml(ds.source_url)}" target="_blank" class="bib-link">열기</a>`;
  }
  return text || '<span class="bib-empty">[미입력]</span>';
}

function _escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function _setEditField(id, value) {
  const el = document.getElementById(id);
  if (el) el.value = value || "";
}

function _getEditField(id) {
  const el = document.getElementById(id);
  return el ? el.value.trim() : "";
}
