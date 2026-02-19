# Phase 12-1: Git 그래프 완전판

> Claude Code 세션 지시문
> 이 문서를 읽고 작업 순서대로 구현하라.

---

## 사전 준비

1. CLAUDE.md를 먼저 읽어라.
2. docs/DECISIONS.md를 읽어라.
3. docs/phase11_12_design_decisions.md를 읽어라.
4. **docs/phase12_design.md를 읽어라** — 12-1 상세 설계가 정의되어 있다.
5. 이 문서 전체를 읽은 후 작업을 시작하라.
6. 기존 코드 구조를 먼저 파악하라: `src/core/`, `src/api/`, `static/js/`.
7. **Phase 9의 타임라인 구현을 확인하라** — 간략 뷰와의 통합이 필요하다.

---

## 설계 요약 — 반드시 이해한 후 구현

### 핵심 원칙

- **사다리형 이분 그래프**: 왼쪽 레인에 원본 저장소(L1~L4) 커밋, 오른쪽에 해석 저장소(L5~L7) 커밋
- **의존 관계 = 가로선**: 해석 커밋이 어떤 원본 시점을 기반했는지 연결
- **커밋 매칭**: Git commit trailer `Based-On-Original: <hash>` 로 명시적 추적
- **Phase 9 통합**: 간략 타임라인(Phase 9) ↔ 상세 Git 그래프(12-1) 탭 전환

### 결정 사항

| 항목 | 결정 |
|------|------|
| 렌더링 엔진 | d3.js (SVG) |
| 레이아웃 | 고정 2레인 + 시간축 Y좌표 |
| 커밋 매칭 | `Based-On-Original` Git trailer |
| 브랜치 | 단일 브랜치 뷰 + 드롭다운 선택 |
| Phase 9 관계 | 같은 영역에서 탭 전환 |

---

## 작업 1: 커밋 Trailer 자동 기록

해석 저장소에 커밋할 때, 원본 저장소의 현재 HEAD hash를 trailer로 자동 기록하는 로직을 추가한다.

### 수정 대상

기존 해석 저장소 커밋 함수를 찾아서 수정하라. `src/core/` 아래 Git 관련 모듈에 있을 것이다.

### 구현

```python
def commit_interpretation(work_id, message, layers_affected):
    """해석 저장소에 커밋. 원본 저장소 HEAD를 trailer로 기록."""
    
    # 1. 원본 저장소의 현재 HEAD hash
    original_repo = get_original_repo(work_id)
    original_head = original_repo.head.commit.hexsha
    
    # 2. trailer 포함 커밋 메시지
    full_message = f"{message}\n\nBased-On-Original: {original_head}"
    
    # 3. 해석 저장소에 커밋
    interp_repo = get_interpretation_repo(work_id)
    interp_repo.index.add(staged_files)
    interp_repo.index.commit(full_message)
```

### 주의

- 기존 커밋 함수의 시그니처를 변경하지 마라. 내부에서 trailer를 추가하는 것만.
- 원본 저장소가 없는 경우(아직 L1~L4 미생성) → trailer 생략, 경고 로그.
- **기존 테스트가 깨지지 않는지 확인하라.**

커밋: `feat(git): 해석 커밋에 Based-On-Original trailer 자동 기록`

---

## 작업 2: Git 그래프 API

두 저장소의 커밋 로그를 합쳐서 그래프 데이터로 반환하는 API.

### 엔드포인트

```
GET /api/work/{work_id}/git-graph
```

### Query Parameters

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `original_branch` | string | `"main"` | 원본 저장소 브랜치 |
| `interp_branch` | string | `"main"` | 해석 저장소 브랜치 |
| `limit` | int | `50` | 각 저장소별 최대 커밋 수 |
| `offset` | int | `0` | 페이지네이션 |

### 응답 스키마

```json
{
  "original": {
    "branch": "main",
    "branches_available": ["main"],
    "commits": [
      {
        "hash": "abc123...",
        "short_hash": "abc123d",
        "message": "L4: 3장 확정텍스트 수정",
        "author": "researcher",
        "timestamp": "2026-02-15T10:30:00Z",
        "layers_affected": ["L4"],
        "tags": []
      }
    ]
  },
  "interpretation": {
    "branch": "main",
    "branches_available": ["main"],
    "commits": [
      {
        "hash": "def456...",
        "short_hash": "def456a",
        "message": "L5: 3장 표점 작업",
        "author": "researcher",
        "timestamp": "2026-02-15T11:00:00Z",
        "layers_affected": ["L5_punctuation"],
        "base_original_hash": "abc123...",
        "base_match_type": "explicit",
        "tags": []
      }
    ]
  },
  "links": [
    {
      "original_hash": "abc123...",
      "interp_hash": "def456...",
      "match_type": "explicit"
    }
  ],
  "pagination": {
    "total_original": 120,
    "total_interpretation": 85,
    "has_more": true
  }
}
```

### 커밋 매칭 로직 (links 생성)

```python
def build_links(original_commits, interp_commits):
    """해석 커밋의 trailer를 파싱하여 링크 생성."""
    links = []
    
    for ic in interp_commits:
        # 1. trailer에서 Based-On-Original 파싱
        base_hash = parse_trailer(ic.message, "Based-On-Original")
        
        if base_hash:
            # 명시적 매칭
            links.append({
                "original_hash": base_hash,
                "interp_hash": ic.hash,
                "match_type": "explicit"
            })
        else:
            # fallback: 타임스탬프 기반 추정
            # 해석 커밋 직전의 원본 커밋을 찾음
            nearest = find_nearest_original_before(
                ic.timestamp, original_commits
            )
            if nearest:
                links.append({
                    "original_hash": nearest.hash,
                    "interp_hash": ic.hash,
                    "match_type": "estimated"
                })
    
    return links
```

### trailer 파싱 함수

```python
import re

def parse_trailer(commit_message: str, key: str) -> str | None:
    """Git commit message에서 trailer 값을 추출."""
    pattern = rf'^{re.escape(key)}:\s*(.+)$'
    for line in reversed(commit_message.strip().splitlines()):
        match = re.match(pattern, line.strip())
        if match:
            return match.group(1).strip()
    return None
```

### `layers_affected` 추출

커밋 메시지의 prefix로 판단한다:
- `"L1:"`, `"L2:"`, `"L3:"`, `"L4:"` → 원본 저장소
- `"L5:"`, `"L6:"`, `"L7:"` → 해석 저장소
- prefix 없으면 → `["unknown"]`

### 파일 위치

- `src/api/git_graph.py` — API 엔드포인트
- `src/core/git_graph.py` — 커밋 로그 수집, 링크 생성 로직

커밋: `feat(api): Git 그래프 API — /api/work/{id}/git-graph`

---

## 작업 3: 레이아웃 계산 모듈 (프론트엔드)

두 저장소 커밋의 Y좌표를 계산하는 JavaScript 모듈.

### 파일

`static/js/git_graph/graphLayout.js`

### 알고리즘

```javascript
/**
 * 두 저장소 커밋을 시간순 통합 정렬하여 Y좌표 계산.
 * 
 * 입력: { original: commits[], interpretation: commits[] }
 * 출력: Map<hash, { x, y, lane }>
 */
export function calculateLayout(data, config) {
    const NODE_MIN_GAP = 50;   // 커밋 간 최소 Y 간격 (px)
    const LANE_ORIGINAL = 150;  // 원본 레인 X좌표
    const LANE_INTERP = 450;    // 해석 레인 X좌표
    
    // 1. 모든 커밋을 timestamp로 통합 정렬 (최신 먼저)
    const allCommits = [
        ...data.original.commits.map(c => ({ ...c, lane: 'original' })),
        ...data.interpretation.commits.map(c => ({ ...c, lane: 'interpretation' }))
    ].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
    
    // 2. Y좌표 할당 (등간격)
    const positions = new Map();
    allCommits.forEach((commit, index) => {
        positions.set(commit.hash, {
            x: commit.lane === 'original' ? LANE_ORIGINAL : LANE_INTERP,
            y: index * NODE_MIN_GAP + 30,  // 상단 여백 30px
            lane: commit.lane
        });
    });
    
    return positions;
}
```

### 설정값

```javascript
// static/js/git_graph/graphColors.js

export const LAYER_COLORS = {
    // 원본 저장소
    L1: '#94a3b8',       // slate
    L2: '#60a5fa',       // blue
    L3: '#818cf8',       // indigo
    L4: '#2563eb',       // blue-dark (강조)
    
    // 해석 저장소
    L5_punctuation: '#34d399',  // emerald
    L5_hyeonto: '#10b981',      // green
    L6: '#f59e0b',              // amber
    L7: '#f97316',              // orange
    
    unknown: '#6b7280'          // gray
};

export const LINK_STYLES = {
    explicit: { stroke: '#64748b', dasharray: 'none', width: 1.5 },
    estimated: { stroke: '#94a3b8', dasharray: '6,3', width: 1 }
};
```

커밋: `feat(frontend): Git 그래프 레이아웃 계산 모듈`

---

## 작업 4: d3.js SVG 렌더링

### 파일

`static/js/git_graph/LadderGraph.js`

### 구현 사항

1. **SVG 컨테이너 생성**: `<svg>` 내부에 `<g>` 그룹으로 레인 라벨, 커밋 노드, 세로선, 가로선 분리
2. **레인 라벨**: 상단에 "원본 저장소 (L1~L4)" / "해석 저장소 (L5~L7)" 텍스트
3. **커밋 노드**: `<circle>` r=8, 색상은 `layers_affected`의 첫 번째 레이어 기준 (`graphColors.js`)
4. **세로 연결선**: 같은 레인 내 인접 커밋 간 `<line>`, 색상 `#e2e8f0`
5. **가로 연결선**: `links` 배열 기반, explicit=실선, estimated=점선, 화살표(marker-end)

### 구조

```javascript
export function renderLadderGraph(container, data) {
    const positions = calculateLayout(data);
    const svg = d3.select(container).append('svg');
    
    // 1. 레인 라벨
    renderLaneLabels(svg);
    
    // 2. 세로 연결선 (같은 레인 내)
    renderVerticalLines(svg, data, positions);
    
    // 3. 가로 연결선 (의존 관계)
    renderHorizontalLinks(svg, data.links, positions);
    
    // 4. 커밋 노드
    renderCommitNodes(svg, data, positions);
}
```

### d3.js 사용법

- d3.js는 CDN으로 로드: `<script src="https://d3js.org/d3.v7.min.js">`
- 기존 프로젝트에서 d3.js를 쓰고 있는지 먼저 확인하라. 이미 있으면 재사용.
- 없으면 `static/js/lib/` 또는 CDN 참조 추가.

커밋: `feat(frontend): d3.js 사다리형 Git 그래프 렌더링`

---

## 작업 5: 인터랙션

### 5-1. 커밋 노드 호버 → 툴팁

```javascript
function addTooltip(nodeSelection) {
    const tooltip = d3.select('body').append('div')
        .attr('class', 'git-graph-tooltip')
        .style('display', 'none');
    
    nodeSelection
        .on('mouseenter', (event, d) => {
            tooltip.html(`
                <strong>${d.short_hash}</strong><br>
                ${d.message}<br>
                <small>${d.author} · ${formatDate(d.timestamp)}</small><br>
                <small>레이어: ${d.layers_affected.join(', ')}</small>
            `);
            tooltip.style('display', 'block')
                .style('left', (event.pageX + 12) + 'px')
                .style('top', (event.pageY - 10) + 'px');
        })
        .on('mouseleave', () => tooltip.style('display', 'none'));
}
```

### 5-2. 커밋 노드 클릭 → 상세 패널

- 클릭 시 기존 커밋 상세 패널을 재사용하거나 새로 만든다.
- Phase 9에 이미 커밋 상세 보기가 있다면 그것을 호출.
- 없으면 사이드 패널에 커밋 메시지 전문 + 변경 파일 목록 표시.

### 5-3. 가로선 호버 → 하이라이트

```javascript
function addLinkHighlight(linkSelection, nodeSelection) {
    linkSelection
        .on('mouseenter', (event, d) => {
            // 관련 없는 요소 opacity 낮춤
            nodeSelection.style('opacity', n =>
                n.hash === d.original_hash || n.hash === d.interp_hash ? 1 : 0.2
            );
            linkSelection.style('opacity', l => l === d ? 1 : 0.1);
        })
        .on('mouseleave', () => {
            nodeSelection.style('opacity', 1);
            linkSelection.style('opacity', 1);
        });
}
```

커밋: `feat(frontend): Git 그래프 인터랙션 — 툴팁, 클릭, 하이라이트`

---

## 작업 6: Phase 9 간략 뷰 통합

### 구현

기존 Phase 9 타임라인이 있는 컨테이너에 탭 전환 UI를 추가한다.

```html
<div class="git-view-tabs">
    <button class="tab active" data-view="simple">간략 타임라인</button>
    <button class="tab" data-view="detail">상세 Git 그래프</button>
</div>
<div class="git-view-container">
    <!-- 선택된 뷰가 여기에 렌더링 -->
</div>
```

- "간략 타임라인" = Phase 9의 기존 구현
- "상세 Git 그래프" = 이번 12-1의 사다리형 그래프
- 탭 전환 시 `git-view-container` 내용을 교체

### 주의

- Phase 9 타임라인 코드를 **수정하지 마라**. 래핑만 추가.
- Phase 9 코드가 없는 경우(미구현 또는 다른 위치), 상세 그래프만 단독으로 렌더링하고, 통합은 TODO로 남겨라.

커밋: `feat(frontend): 간략/상세 Git 뷰 탭 전환`

---

## 작업 7: 통합 테스트

### 테스트 시나리오

1. **trailer 기록 테스트**:
   - 해석 저장소에 커밋 → commit message에 `Based-On-Original:` trailer 존재 확인
   - 원본 저장소 HEAD와 trailer 값 일치 확인

2. **API 테스트**:
   - `GET /api/work/{id}/git-graph` 호출 → 양쪽 커밋 반환 확인
   - `links` 배열에 `match_type: "explicit"` 링크 존재 확인
   - trailer 없는 레거시 커밋 → `match_type: "estimated"` 확인

3. **렌더링 테스트** (수동):
   - 두 레인에 커밋 노드 표시 확인
   - 가로선이 올바른 커밋 쌍을 연결하는지 확인
   - explicit=실선, estimated=점선 구분 확인
   - 툴팁 표시 확인

4. **브랜치 전환 테스트**:
   - 드롭다운에서 다른 브랜치 선택 → 그래프 갱신 확인

커밋: `test: Phase 12-1 Git 그래프 통합 테스트`

---

## 완료 체크리스트

- [ ] 해석 커밋에 `Based-On-Original` trailer 자동 기록
- [ ] `GET /api/work/{id}/git-graph` 엔드포인트
- [ ] trailer 파싱 + 타임스탬프 fallback 매칭
- [ ] `graphLayout.js` — Y좌표 계산
- [ ] `graphColors.js` — 레이어별 색상 상수
- [ ] `LadderGraph.js` — d3.js SVG 렌더링
- [ ] 커밋 호버 툴팁
- [ ] 커밋 클릭 상세 패널
- [ ] 가로선 하이라이트
- [ ] Phase 9 간략 뷰 탭 전환
- [ ] 통합 테스트 통과

---

## ⏭️ 다음 세션: Phase 12-3 — JSON 스냅샷

```
이 세션(12-1)이 완료되면 다음 작업은 Phase 12-3 — JSON 스냅샷 export/import이다.

12-1에서 만든 것:
  ✅ Git trailer 기반 커밋 매칭
  ✅ 사다리형 Git 그래프 API + 렌더링
  ✅ Phase 9 통합 (탭 전환)

12-3에서 만들 것:
  - JSON 스냅샷 스키마 (schema_version 포함)
  - Export API (Work 전체 → JSON)
  - Import API (JSON → 새 Work 생성)
  - Import 검증 (sentence_id 참조 무결성 등)
  - GUI 버튼 연결

세션 문서: phase12_3_json_snapshot_session.md
```
