# 고전 텍스트 연구자를 위한 디지털 서고 플랫폼

## 프로젝트 기획서 v7

---

## 1. 프로젝트 비전

### 한 줄 정의

**물리적 원본과 디지털 텍스트의 연결이 끊어지지 않는, 사람과 LLM이 함께 고전 텍스트를 읽고 번역하고 연구하는 플랫폼.**

### 문제 인식

현재 고전 텍스트의 디지털화 과정에서 근본적인 단절이 발생한다:

- PDF나 이미지를 다운받는 순간, 서지정보와의 연결이 끊어진다
- 텍스트를 입력하는 순간, 물리적 원본의 어디에 있었는지가 사라진다
- 교정하는 순간, 이전 버전과 그에 의존한 번역/주석의 관계가 불투명해진다
- LLM이 번역하는 순간, 어떤 버전의 원문을 보고 번역했는지가 기록되지 않는다

### 핵심 통찰

고품질 텍스트 데이터베이스를 구축하려면 가장 근본—물리적 원본과 디지털 데이터의 연결—부터 다루지 않으면, 실물과 문자열 데이터는 계속 유리된다.

### 설계 전제

1. **LLM 협업**: 사람과 LLM의 협업을 처음부터 전제. LLM이 draft하고 사람이 review/commit한다.
2. **점진적 완성**: 모든 것이 미완성 상태로 존재할 수 있고, 천천히 채워간다.
3. **물리적 원본 연결**: 모든 텍스트는 자기 출처(provenance)를 갖는다.
4. **오프라인 퍼스트**: 핵심 작업(교정, 열람, 커밋)은 인터넷 없이 완전히 동작한다. 온라인 기능(LLM, 동기화, 서지파싱)은 인터넷이 있을 때 추가된다.

---

## 2. 8층 모델

### 2.1 전체 구조

```
8. 외부연계         API, 다른 DB, 다른 연구자의 서고, 학술 네트워크
7. 주석/링크/사전    어휘 풀이, 전거 참조, 사전 연동, 인물/지명 DB
6. 번역             현대어역, 다국어 번역 (수동 + LLM)
─────────────────── 해석의 경계 ───────────────────
5. 끊어읽기·표점·현토  구두점, 문장 경계, 한문 독법(懸吐) 표기
━━━━━━━━━━━━━━━━━━ 저장소 경계 ━━━━━━━━━━━━━━━━━━
4. 사람 수정         OCR 교정, 이체자 확인, 수동 입력, 판본 이문 기록
─────────────────── 확정의 경계 ───────────────────
3. 레이아웃 분석     본문/주석/서문/간기 구분, 블록 구조 파악
2. OCR 글자해독      엔진 인식 결과 + 좌표 + 신뢰도
1. 이미지/PDF        물리적 원본 (불변)
```

### 2.2 왜 8층인가 (v6까지는 7층이었다)

v6까지의 7층 모델은 "OCR이 글자를 읽는다(2층) → 사람이 교정한다(3층)"였다.
하지만 실제 문헌(일본 국립공문서관 소장 《蒙求》)을 걸어보니 중간에 빠진 단계가 발견되었다:

> OCR은 글자를 읽지만, "이 글자가 본문인지 주석인지"를 모른다.

고전 텍스트는 하나의 페이지 안에 **본문(大字), 주석(小字 雙行), 서문, 간기, 인장** 등 성격이 다른 영역이 혼재한다. 이것을 구분하지 않으면:
- 사람이 교정할 때 뭐가 본문이고 뭐가 주석인지 모른 채 작업해야 하고
- 해석 저장소에서 "본문 번역"과 "주석 번역"을 분리할 수 없고
- LLM에게 "본문만 번역해줘"라고 지시할 수 없다

이 작업은 2층(OCR)도 아니고 4층(교정)도 아닌 독립된 단계다.
따라서 **3층: 레이아웃 분석**을 신설했다.

### 2.3 각 층에서의 사람과 LLM의 역할

| 층 | 이름 | LLM의 역할 | 사람의 역할 | 구현 |
|---|---|---|---|---|
| 1 | 이미지/PDF | — | 원본 스캔/업로드 + 에셋 자동 감지 | ✓ |
| 2 | OCR 글자해독 | PaddleOCR + LLM Vision | OCR 엔진 선택, 설정 조정 | ✓ |
| 3 | 레이아웃 분석 | 이미지 보고 영역 구분 (본문/주석/서문 등) | 검토, 수정, 확정 | ✓ |
| 4 | 사람 수정 | 교정 제안: 이체자 판별, 문맥 기반 오류 후보 | 최종 교정 판단, 확정 | ✓ |
| 5 | 끊어읽기·현토 | 표점·현토 초안 (여러 안 병렬 제시) | 검토, 선택, 수정, 확정 | ✓ |
| 6 | 번역 | draft 생성 (사전 참조 포함) | 검토, 수정, 확정 | ✓ |
| 7 | 주석/사전 | 4단계 사전 생성 + 자동 태깅 | 검증, 편집, 사전 내보내기/가져오기 | ✓ |
| 8 | 외부연계 | 유사 문헌 추천, 외부 DB 매핑 | 연계 판단, 연구 방향 설정 | — |

**패턴: LLM이 draft → 사람이 review → 사람이 commit** (2~8층 공통)

### 2.4 두 개의 저장소

| | 원본 저장소 (1~4층) | 해석 저장소 (5~8층) |
|---|---|---|
| **본질** | 원본 충실 재현 (Digitization) | 해석과 활용 (Scholarship) |
| **정답** | 있다 (원본에 쓰인 그대로) | 없다 (해석은 연구자마다 다름) |
| **분기** | 드묾 | 빈번 |
| **LLM 역할** | 보조 (OCR·레이아웃·교정 제안) | 핵심 (draft 생성) |
| **저장소 성격** | 단일 정본(正本) 수렴 | 다수 해석 병존 |

### 2.5 병렬 저장소 모델

4층이 확정되는 순간, 그 위에 여러 해석 저장소가 독립적으로 생겨난다:

```
[원본 저장소]
 L1─L2─L3─L4 ──●── v1.0 ──●── v2.0 ──●── v3.0
                      │          │          │
[해석 A] (사람, 수동)  │     ┌────┘          │
                      │     ▼               │
                      │    L5 현토 ── L6 번역 ── L7 주석
                      │                     │
[해석 B] (LLM draft)  │                ┌────┘
                      │                ▼
                      │               L6 LLM 번역
                      │
[해석 C] (LLM→사람)   │
                 ┌────┘
                 ▼
                L5 현토(LLM→수정) ── L6 번역(수정)
```

### 2.6 층별 의존 관계

```
[원본 저장소 내부]
1층 변경 → 거의 없음 (원본은 불변)
2층 변경 → 3~4층 영향 (OCR 재실행)
3층 변경 → 4층 영향 (레이아웃 재분류)
4층 변경 → 모든 해석 저장소에 경고

[저장소 경계]
4층 확정 → 해석 저장소의 시작점

[해석 저장소 내부]
5층 변경 → 6~8층 영향
6층 변경 → 7~8층 영향
7층 변경 → 8층에만 영향
8층 변경 → 자체 완결
```

### 2.7 층별 분기 특성

| 층 | 저장소 | 분기 빈도 | 예시 |
|---|---|---|---|
| 1 | 원본 | 없음 | 원본은 하나 |
| 2 | 원본 | 드묾 | PaddleOCR vs Claude Vision |
| 3 | 원본 | 드묾 | 다른 레이아웃 해석 |
| 4 | 원본 | 드묾 | 이체자 판단 차이, 판본 이문 |
| 5 | 해석 | **핵심 분기** | 사람/LLM 각각의 현토·표점 |
| 6 | 해석 | 자주 | 사람 번역, LLM 한국어역, LLM 영역 |
| 7 | 해석 | 자유 | 사람 주석, LLM 자동 주석 |
| 8 | 해석 | 자유 | LLM 자동 탐색, 사람 큐레이션 |

---

## 3. 아키텍처: 앱 + Git

### 3.1 핵심 설계 결정

**Git은 저장소. 앱이 두뇌.**

독립된 git 저장소들은 서로의 존재를 모른다.
저장소 간의 관계를 이해하고, 의존성을 추적하고, 경고를 발생시키고,
사다리형 그래프를 그리는 것은 전부 **앱 레이어**가 한다.

```
┌──────────────────────────────────────────────────┐
│  앱 (UI + 로직)                    ← 두뇌         │
│                                                  │
│  ├─ library_manifest.json 읽기 (서고 전체 지도)    │
│  ├─ 원본 repo 접근 (git 명령)                     │
│  ├─ 해석 repo 접근 (git 명령)                     │
│  ├─ dependency.json 해석                         │
│  ├─ 파일 단위 변경 감지 (git diff)                 │
│  ├─ 경고 생성                                    │
│  ├─ 분할 화면 렌더링                              │
│  ├─ 사다리형 git 그래프 렌더링                     │
│  └─ LLM API 호출 & 결과 관리 (온라인)             │
│                                                  │
├──────────────────────────────────────────────────┤
│  Git repos (로컬)                  ← 저장소       │
│  ├─ doc_001/                (원본)                │
│  ├─ doc_001_interp_kim/     (해석)                │
│  └─ ...                                         │
│                                                  │
├──────────────────────────────────────────────────┤
│  Git 원격 호스팅 (온라인)          ← 백업/동기화   │
│  GitLab self-host / Gitea / GitHub / 아무거나      │
└──────────────────────────────────────────────────┘
```

**역할 분리:**
- **Git**: 저장, 이력, 버전, diff → 이미 있는 인프라
- **앱**: 관계, 의미, 경고, UI → 만들어야 할 것
- **원격 호스팅**: 백업, 동기화 → 교체 가능

### 3.2 오프라인/온라인 구분

| 기능 | 오프라인 | 온라인 |
|---|---|---|
| 텍스트 교정/편집 | ✓ | ✓ |
| git commit/diff/log | ✓ | ✓ |
| 분할 화면 뷰어 | ✓ | ✓ |
| 의존 변경 감지 (로컬) | ✓ | ✓ |
| 의존 변경 감지 (원격) | — | ✓ fetch 필요 |
| git push/pull (동기화) | — | ✓ |
| 서지정보 파싱 | — | ✓ |
| LLM API 호출 | — | ✓ |
| OCR (클라우드 엔진) | — | ✓ (로컬 엔진이면 ✓) |

**원칙: 오프라인에서 핵심 작업이 막히는 일은 없어야 한다.**
온라인이 되면 "밀린 동기화 + LLM draft 요청"을 일괄 처리.

### 3.3 호스팅 비종속

이 시스템에서 "fork"는 git fork와 다르다.
`dependency.json`으로 관계를 직접 관리하므로 호스팅의 fork 기능에 의존하지 않는다.

| 이슈 | GitHub | GitLab CE | Gitea |
|---|---|---|---|
| 자기 repo fork | ✕ | ○ | ○ |
| self-hosting | ✕ | ○ 무료 | ○ 무료, 경량 |
| LFS (대용량) | 유료 | 내장 | 내장 |
| CI/CD | Actions | 내장 | 외부 연동 |

**결론**: 아키텍처는 호스팅에 종속되지 않는다.

### 3.4 데스크톱 앱 ↔ 웹 앱

| | 데스크톱 앱 | 웹 앱 |
|---|---|---|
| 접근 | 로컬 git repo 직접 읽기 | 원격 git repo 통해 접근 |
| 오프라인 | ✓ 완전 동작 | — |
| 이미지 처리 | ✓ 유리 | 제한적 |
| LLM 연동 | 온라인 시 | 자연스러움 |

둘 다 같은 데이터, 같은 UI.
기술적으로 **웹 기술로 만들고, 데스크톱은 감싸는 것**(Electron/Tauri)이 코드베이스 통일에 유리.

동기화 흐름:
```
[데스크톱 오프라인 작업] → push → [원격 repo] → pull → [웹 앱에서 이어서 작업]
```

---

## 4. 파일 단위 의존 추적

### 4.1 문제

"원본 저장소가 업데이트됐다" → 부족.
"내가 참조한 파일이 바뀌었는가" → 이것을 알아야 한다.

### 4.2 dependency.json

```json
{
  "interpretation_id": "interp_kim_001",
  "interpreter": {
    "type": "human",
    "name": "연구자 김"
  },
  "source": {
    "document_id": "monggu",
    "remote": "https://git.example.com/library/monggu.git",
    "base_commit": "a1b2c3d4e5f6..."
  },
  "tracked_files": [
    {
      "path": "L4_text/pages/page_001.txt",
      "hash_at_base": "sha256:aaa111...",
      "my_layers": [5, 6],
      "status": "unchanged"
    },
    {
      "path": "L4_text/pages/page_003.txt",
      "hash_at_base": "sha256:ccc333...",
      "my_layers": [6],
      "status": "unchanged"
    }
  ],
  "last_checked": "2025-03-01T10:00:00",
  "dependency_status": "current"
}
```

### 4.3 변경 감지: 열 때 확인 (access-time check)

실시간 감시가 아니라, **앱이 해석 저장소를 열 때** 확인한다.

```
[사용자가 해석 저장소를 연다]
  ↓
[앱] dependency.json 읽기
  ↓
[앱] 원본 저장소의 최신 커밋 확인
  ↓
[앱] base_commit 이후 변경 파일 추출 (git diff --name-only)
  ↓
[앱] tracked_files와 대조
  ├─ 변경 없음 → "최신 상태" ✓
  └─ 변경 있음 → ⚠️ 파일별 경고
     ├─ [diff 보기]
     ├─ [기반 업데이트] → base_commit 갱신
     └─ [무시] → acknowledged 마킹
```

### 4.4 status 값

tracked_files 각 파일:
- `unchanged`: 원본과 동일
- `changed`: 원본 갱신됨 ⚠️
- `acknowledged`: changed 인지했지만 내 작업은 유효
- `updated`: 새 원본에 맞춰 수정 완료

전체 dependency_status:
- `current` / `outdated` / `partially_acknowledged` / `acknowledged`

---

## 5. 원본 저장소 (1~4층) 상세

### 5.1 1층: 이미지/PDF (물리층)

**원칙: 불변. 절대 수정하지 않는다.**
**git-lfs 필수.** 이미지/PDF는 수십~수백 MB이므로 일반 git으로 관리할 수 없다.

| 원본 형태 | 관리 단위 |
|---|---|
| 이미지 세트 | 폴더 = 문헌, 개별 이미지 = 페이지 |
| PDF | 파일 = 문헌, PDF 내 페이지 = 페이지 |

#### 다권본(多卷本) 지원

하나의 작품이 물리적으로 여러 파일로 구성될 수 있다.
manifest.json의 `parts` 필드로 관리한다.

```json
{
  "document_id": "monggu",
  "title": "蒙求",
  "parts": [
    {
      "part_id": "vol1",
      "label": "蒙求1",
      "file": "L1_source/蒙求1.pdf",
      "page_count": 42
    },
    {
      "part_id": "vol2",
      "label": "蒙求2",
      "file": "L1_source/蒙求2.pdf",
      "page_count": 38
    },
    {
      "part_id": "vol3",
      "label": "蒙求3",
      "file": "L1_source/蒙求3.pdf",
      "page_count": 35
    }
  ]
}
```

하나의 git repo 안에 다권본의 모든 파일이 들어간다.
parts가 1개이면 단권본, 여러 개이면 다권본. 동일한 구조.

### 5.2 2층: OCR 글자해독 (인식층)

| 설정 항목 | 옵션 |
|---|---|
| OCR 엔진 | **PaddleOCR (기본 설치)**, Tesseract, Google Cloud Vision, 커스텀 |
| LLM 보조 | Claude Vision, GPT-4V, Gemini Vision 등 (텍스트만, 좌표 없음) |
| 언어 | 한문(繁/簡), 한글, 일문, 만주어, 기타 |
| 방향 | 세로쓰기, 가로쓰기, 혼합 |
| 레이아웃 | 단일 컬럼, 다단, 주석란 포함, 혼합 |

**2층의 출력**: 글자 + 좌표(bbox) + 신뢰도(confidence). 글자가 본문인지 주석인지는 모른다.

**OCR 설정은 블록별로 다를 수 있다:**
같은 페이지 안에서 본문(대자 세로쓰기)과 주석(소자 쌍행)의 방향/크기가 다를 수 있음.
다만 2층에서는 아직 블록 구분이 안 되었으므로, 페이지 단위로 기본 설정을 적용하고,
3층(레이아웃 분석) 후에 블록별 재처리가 가능하다.

### 5.3 3층: 레이아웃 분석 (구조층) — NEW

**입력**: 2층의 글자+좌표
**출력**: 각 영역에 구조적 역할(block type) 부여

#### block type 어휘

| block_type | 설명 | 예시 |
|---|---|---|
| `main_text` | 본문 (대자) | 王戎簡要裴楷清通 |
| `annotation` | 주석 (소자, 흔히 쌍행) | 王戎字濬沖瑯邪臨沂人... |
| `preface` | 서문 | 李華《蒙求序》 |
| `colophon` | 간기 (간행 정보) | 嘉熙己亥上元重刊于聚德堂 |
| `memorial` | 표문 | 李良《荐蒙求表》 |
| `page_title` | 판심제 | 蒙求卷上 |
| `page_number` | 장차 | 第三張 |
| `seal` | 인장 | 소장 인장 |
| `illustration` | 삽화 | — |
| `marginal_note` | 방주(傍注), 두주(頭注) | 페이지 상단/옆 메모 |
| `table_of_contents` | 목차 | — |
| `unknown` | 판별 불가 | — |

이 어휘는 확장 가능하다. 문헌 유형에 따라 필요한 type이 달라질 수 있다.

#### 블록별 속성

```json
{
  "block_id": "p01_b03",
  "block_type": "annotation",
  "bbox": [120, 50, 200, 600],
  "writing_direction": "vertical_rtl",
  "line_style": "double_line",
  "font_size_class": "small",
  "refers_to_block": "p01_b01",
  "characters": [
    {"char": "王", "bbox": [125, 55, 140, 70], "confidence": 0.97},
    ...
  ]
}
```

`writing_direction`이 **블록별**로 설정된다 (문서 전체가 아니라).
`refers_to_block`으로 "이 주석은 저 본문 블록에 달린 것"임을 표현한다.

#### LLM의 역할 (3층)

LLM은 페이지 이미지를 보고:
1. 영역을 구분한다 (여기서부터 여기까지가 본문, 여기는 주석)
2. 각 영역에 block_type을 부여한다
3. 주석이 어느 본문에 달린 것인지 연결한다

사람이 검토하고 확정한다.

### 5.4 4층: 사람 수정 (교정층)

3층에서 본문/주석이 구분되었으므로, 교정 시 맥락이 명확하다.

#### 교정 유형

| 유형 | 설명 | 예시 |
|---|---|---|
| `ocr_error` | OCR 인식 오류 | 元→玄 (기계 오인식) |
| `decoding_error` | 해독 불가 → 해독 | □→黃 |
| `variant_char` | 이체자 판단 | 說↔説 |
| `variant_reading` | **판본 이문** | 이 판본에서는 다른 판본과 다르게 기록됨 |
| `uncertain` | 불확실 (보류) | 확신 없음 |
| `layout_correction` | 3층 레이아웃 오류 수정 | 주석인데 본문으로 분류된 것 |

**`variant_reading`**: OCR 오류가 아니라, 이 판본 자체가 다른 판본과 다른 글자를 갖고 있는 경우.
"원본에 쓰인 그대로"를 기록하되, 다른 판본과의 차이를 메모로 남긴다.

```json
{
  "page": 3, "line": 2, "char_index": 5,
  "type": "variant_reading",
  "this_edition": "元",
  "common_reading": "玄",
  "note": "이 판본에서는 元으로 씌어 있으나, 다른 판본들은 玄. 피휘(避諱) 가능성."
}
```

### 5.5 매핑 정밀도 스펙트럼

| 정밀도 | 조건 | 데이터 |
|---|---|---|
| 글자 단위 | OCR 좌표 + 정렬 완료 | 글자별 bbox, confidence |
| 행 단위 | OCR 행 인식 가능 | 행별 bbox + 텍스트 |
| 영역 단위 | 다단, 주석란 | 영역별 bbox + 텍스트 |
| 페이지 단위 | OCR 불가, 수동 입력 | 페이지 ↔ 텍스트 |
| 파일 단위 | 최소 연결 | 파일 ↔ 파일 |

**정밀도가 낮아도 연결은 존재해야 한다.**

### 5.6 문헌 완성도

```
[파일만] → [서지정보] → [OCR 완료] → [레이아웃 분석] → [교정 중] → [교정 완료] → [확정]
```

---

## 6. 해석 저장소 (5~8층) 개요

**별도 솔루션으로 설계. 여기서는 연결 인터페이스만 정의.**

### 6.1 각 층

| 층 | 내용 | LLM | 사람 | 구현 상태 |
|---|---|---|---|---|
| 5 끊어읽기·현토 | 구두점, 독법 | 초안 (여러 안) | 검토, 확정 | ✓ D-014 |
| 6 번역 | 현대어역, 문장 단위 | draft (다양한 스타일) | 수정, 확정 | ✓ D-015 |
| 7 주석/사전 | 태깅 + 사전형 주석 | 4단계 누적 생성 | 검증, 편집 | ✓ D-016, D-019 |
| — 인용 마크 | 논문 인용 구절 마크업 | — | 선택, 포맷 | ✓ D-020 |
| 8 외부연계 | 다른 DB | 자동 탐색 | 판단 | 미구현 |

### 6.2 본문과 주석의 구분

3층(레이아웃 분석)에서 본문과 주석이 구분되었으므로,
해석 저장소에서도 **본문에 대한 해석과 주석에 대한 해석을 분리**할 수 있다.

```
L5_reading/
  ├─ main_text/           # 본문의 끊어읽기·현토
  │   ├─ page_001.json
  │   └─ ...
  └─ annotation/          # 주석의 끊어읽기 (필요시)
      └─ page_001.json

L6_translation/
  ├─ main_text/           # 본문 번역
  │   ├─ ko_modern.txt
  │   └─ en_academic.txt
  └─ annotation/          # 주석 번역
      └─ ko_modern.txt
```

본문과 주석은 성격이 다르다:
- 본문(四言韻文): "王戎簡要" → "왕융은 간결했다"
- 주석(散文解說): "王戎字濬沖瑯邪臨沂人..." → "왕융의 자는 준충이고..."

LLM에게 번역을 요청할 때도 "본문만", "주석만", "둘 다"를 지정할 수 있어야 한다.

### 6.3 연결 규칙

- 해석 저장소는 원본 저장소의 특정 커밋을 참조한다
- 참조는 파일 단위로 추적된다 (섹션 4)
- 원본 변경 시 앱이 파일 단위로 경고를 생성한다
- 해석 저장소는 원본을 수정할 수 없다 (읽기 전용 참조)

---

## 7. 서지정보 연동

### 7.1 데이터 소스

| 소스 | 용도 | 접근 방법 | 메타데이터 기반 | 인증 |
|---|---|---|---|---|
| KORCIS (한국고문헌종합목록) | 한국 고전적 | REST API (XML) | KORMARC | API키 필요 |
| NDL Search (일본 국립국회도서관) | 일본 문헌 전반 | SRU / OpenSearch (XML) | DC-NDL (Dublin Core + NDL 확장) | 비영리: 불필요 |
| 일본 국립공문서관 デジタルアーカイブ | 일본 소장 한적·화서 | 웹 스크래핑 | 자체 계층 (簿冊→件名) | 불필요 |
| **범용 LLM 파서** | 등록된 파서 없는 모든 URL | markdown.new + LLM | 자유 형식 | 불필요 |
| 수동 입력 | 출처 불문 | 직접 입력 | — | — |

**각 소스의 메타데이터 구조가 근본적으로 다르다.** 이 차이를 흡수하는 것이 파서 아키텍처의 핵심.

### 7.2 소스별 메타데이터 구조 상세

#### 7.2.1 KORCIS (한국고문헌종합목록)

국립중앙도서관이 운영. 국내외 140개 이상 기관의 고문헌 서지데이터 약 51만 건.

**접근 방법:**
- KORCIS OpenAPI: `https://www.nl.go.kr/korcis/` (REST, XML 응답)
- 공공데이터포털: `data.go.kr` 데이터셋 15077395 (CSV 대량 다운로드도 가능)
- API키: 국립중앙도서관 사이트에서 발급

**기반 규격:** KORMARC (한국문헌자동화목록형식). MARC21과 유사하되, 한국 고전적 특화 필드가 있음.

**제공 필드:** 서명(245), 저자(100/700), 발행지(260$a), 발행자(260$b), 발행년(260$c), **판종**(고전적 특화), 형태사항(300), 주기사항(500), 청구기호(090/852), 소장처(852$a), 원문URL

**고전적 특화 강점:**
- `판종`: 목판본/활자본/필사본/석인본 등 — 고전적 연구에 핵심적. NDL에는 없는 필드
- `소장처`: 다수 기관의 소장 현황 포괄
- MARC 데이터 제공 (인증된 기관에 한함)

**한계:**
- 저자명 독음(reading) 없음 (MARC에 포함되지 않는 경우 다수)
- 고문헌 특성상 저자 불명, 발행년 불명이 빈번
- API 응답 구조가 공식 문서에 상세히 기술되어 있지 않음 (PDF 매뉴얼 제공)

#### 7.2.2 NDL Search (일본 국립국회도서관 サーチ)

**접근 방법:**
- SRU: `https://ndlsearch.ndl.go.jp/api/sru` — 가장 고기능 (CQL 검색, 정렬, 완전일치/전방일치)
- OpenSearch: `https://ndlsearch.ndl.go.jp/api/opensearch` — 심플 파라미터
- OAI-PMH: 대량 수집용
- 비영리는 신청 불요, 영리는 이용 신청 필요

**기반 규격:** DC-NDL (Dublin Core + NDL 독자 확장). `recordSchema=dcndl`으로 요청 시 상세 필드.

**DC-NDL 주요 필드 (SRU/OpenSearch, dcndl 스키마):**

```xml
<!-- 표제 + 독음 -->
<dc:title>蒙求</dc:title>
<dcndl:titleTranscription>モウギュウ</dcndl:titleTranscription>

<!-- 저자 + 독음 -->
<dc:creator>李瀚</dc:creator>
<dcndl:creatorTranscription>リ カン</dcndl:creatorTranscription>

<!-- 출판 -->
<dc:publisher>芳文社</dc:publisher>
<dcndl:publicationPlace>JP</dcndl:publicationPlace>
<dcterms:issued>2024.2</dcterms:issued>

<!-- 물리 기술 -->
<dc:extent>174 p</dc:extent>

<!-- 권차, 총서 -->
<dcndl:volume>1</dcndl:volume>
<dcndl:seriesTitle>FUZ comics</dcndl:seriesTitle>
<dcndl:seriesTitleTranscription>...</dcndl:seriesTitleTranscription>

<!-- 식별자 (복수) -->
<dc:identifier xsi:type="dcndl:ISBN">978-4-8322-0365-5</dc:identifier>
<dc:identifier xsi:type="dcndl:NDLBibID">033286846</dc:identifier>
<dc:identifier xsi:type="dcndl:JPNO">23942939</dc:identifier>

<!-- 분류 -->
<dc:subject xsi:type="dcndl:NDLC">Y84</dc:subject>
<dc:subject xsi:type="dcndl:NDC10">726.1</dc:subject>

<!-- 자료 유형, 장르 -->
<dcndl:materialType rdfs:label="図書"/>
<dcndl:genre>漫画</dcndl:genre>

<!-- 가격 -->
<dcndl:price>720円</dcndl:price>

<!-- 링크 -->
<rdfs:seeAlso rdf:resource="https://ndlsearch.ndl.go.jp/books/R100000002-I033286846"/>
```

**NDL 특화 강점:**
- **독음(Transcription)**: 표제, 저자명, 총서명 모두 카타카나/로마자 독음 제공
- **분류 체계**: NDLC + NDC(9판/10판) 동시 제공
- **다중 데이터프로바이더**: NDL 자관 외에 각 도서관의 데이터도 검색 가능 (`dpid` 파라미터)
- **메타데이터 라이선스**: NDL 자관 데이터는 CC-BY 4.0

**한계:**
- 판종(edition type) 필드 없음 — 고전적 연구에서 중요한 목판/활자/필사 구분 불가
- 검색 결과 500건 제한 (페이지네이션 불가)
- 응답 속도가 느릴 수 있음

#### 7.2.3 일본 국립공문서관 デジタルアーカイブ

**접근 방법:**
- 표준 API 없음. 웹 스크래핑 또는 수동 입력
- URL 패턴: `https://www.digital.archives.go.jp/`

**메타데이터 구조:** 자체 계층. 도서관 표준(MARC, DC)과 완전히 다르다.

```
簿冊(volume) = 작품 단위
  └─ 件名(item) = 물리 단위 (예: 蒙求1, 蒙求2, 蒙求3)
```

**제공 필드:**
- 簿冊標題 (작품명)
- 件名 (물리 단위명, 예: "蒙求1")
- 件数 (전체 건수, 예: "全3件中 No.1")
- 永続URI / システムID (BID, ID)

**특징:**
- 저자, 발행년, 판종 등 서지 필드가 **대부분 없음**
- 도서관이 아닌 문서관(archive) 특성 → 서지보다는 소장·관리 중심
- 라이선스가 비교적 개방적 ("二次利用自由" 다수)

### 7.3 파서 아키텍처

#### 7.3.1 전체 흐름

```
[KORCIS API]        → korcis_fetcher    → korcis_mapper    ─┐
[NDL Search API]    → ndl_fetcher       → ndl_mapper        ─┤
[국립공문서관 HTML]  → archives_fetcher  → archives_mapper   ─┼→ bibliography.json
[임의의 URL]        → generic_llm       → generic_mapper    ─┤
[수동 입력 폼]      →                   → manual_mapper     ─┘
                     ↑ 추출(Extract)      ↑ 매핑(Map)         ↑ 공통 스키마
```

각 소스에 대해 두 단계:
1. **Fetcher** (추출): 해당 소스에서 원본 데이터를 가져온다 (API 호출, HTML 파싱)
2. **Mapper** (매핑): 소스별 필드를 공통 스키마 필드에 대응시킨다

**범용 LLM 파서 (generic_llm)**:
등록된 파서가 없는 URL에 대한 폴백. markdown.new로 웹페이지를 마크다운으로 변환한 뒤
LLM이 서지정보를 추출한다. 에셋(PDF/이미지) 자동 감지 + 다운로드도 지원한다.

**에셋 감지 (asset_detector)**:
파서와 독립된 유틸리티. URL의 Content-Type 확인, 마크다운에서 PDF/이미지 링크 추출,
이미지 번들→PDF 변환을 수행한다. generic_llm 파서가 위임하고,
다른 파서(NDL, KORCIS)는 서버 폴백으로 활용한다.

#### 7.3.2 필드 매핑 테이블

| 공통 필드 | KORCIS (MARC) | NDL (DC-NDL) | 일본 국립공문서관 |
|---|---|---|---|
| `title` | 245$a 서명 | `dc:title` | 簿冊標題 |
| `title_reading` | — (없는 경우 다수) | `dcndl:titleTranscription` | — |
| `alternative_titles` | 246 다른표제 | — | — |
| `creator.name` | 100$a 저자 | `dc:creator` | — (대부분 없음) |
| `creator.reading` | — | `dcndl:creatorTranscription` | — |
| `contributors` | 700 부출저자 | `dcterms:contributor` | — |
| `date_created` | 260$c 발행년 | `dcterms:issued` / `dc:date` | — |
| `edition_type` | **판종** ✓ (KORCIS 고유) | — (없음) | — |
| `physical_description` | 300 형태사항 | `dc:extent` | — |
| `notes` | 500 주기사항 | `dc:description` | — |
| `subject` | 650 주제명 | `dc:subject` (자유어) | — |
| `classification` | 분류기호 | `dcndl:NDLC` / `dcndl:NDC9` / `dcndl:NDC10` | — |
| `call_number` | 090/852 청구기호 | — | — |
| `repository.name` | 852$a 소장처 | (데이터프로바이더에 따라) | "国立公文書館" 고정 |
| `system_ids` | KORCIS 제어번호 | `dcndl:NDLBibID` / `dcndl:JPNO` | BID / ID |
| `isbn` | 020$a | `dc:identifier[@type=dcndl:ISBN]` | — |
| `volume_info` | 245$n 권차 | `dcndl:volume` | 件名 ("蒙求1"), 件数 |
| `series_title` | 490 총서명 | `dcndl:seriesTitle` | — |
| `material_type` | — | `dcndl:materialType` | — |
| `digital_url` | 원문 URL | `rdfs:seeAlso` | 永続URI |

**핵심 관찰:**
- KORCIS만 가진 것: **판종(edition_type)**, 청구기호, 소장처 정보
- NDL만 가진 것: **독음(reading/transcription)**, NDC/NDLC 분류, 자료유형
- 국립공문서관: 대부분의 서지 필드가 **비어 있음** → 사람이 채워야 한다
- 같은 개념인데 이름이 다르고, 있는 곳도 있고 없는 곳도 있다

#### 7.3.3 설계 원칙

**원칙 1: 모든 공통 필드는 null을 허용한다.**
채울 수 없으면 비워두되, `raw_metadata`에 원본이 온전히 보존되어 있으므로 나중에 사람이 채울 수 있다.

**원칙 2: raw_metadata는 건드리지 않는다.**
파서가 공통 필드에 매핑한 뒤에도, 소스에서 가져온 원본 데이터는 `raw_metadata`에 그대로 유지한다. 매핑 과정에서 정보가 손실되더라도 원본에서 복구할 수 있다.

**원칙 3: 매핑 판단은 기록한다.**
자동 매핑이 확실하지 않은 경우 (예: 국립공문서관의 件名 "蒙求1"에서 권차를 추출할 때) `mapping_confidence`를 기록하여 사람이 검토할 수 있게 한다.

**원칙 4: 파서는 플러그인이다.**
새로운 소스가 추가될 때 기존 코드를 수정하지 않고, 새로운 fetcher + mapper 쌍만 등록하면 된다.

#### 7.3.4 파서 등록 구조

```json
// parsers/registry.json
{
  "parsers": [
    {
      "id": "korcis",
      "name": "한국고문헌종합목록 (KORCIS)",
      "country": "KR",
      "fetcher": "korcis_fetcher",
      "mapper": "korcis_mapper",
      "access_method": "api",
      "base_url": "https://www.nl.go.kr/korcis/",
      "response_format": "xml",
      "requires_auth": true,
      "metadata_standard": "KORMARC"
    },
    {
      "id": "ndl",
      "name": "国立国会図書館サーチ (NDL Search)",
      "country": "JP",
      "fetcher": "ndl_fetcher",
      "mapper": "ndl_mapper",
      "access_method": "api",
      "base_url": "https://ndlsearch.ndl.go.jp/api/",
      "response_format": "xml",
      "requires_auth": false,
      "metadata_standard": "DC-NDL",
      "api_variants": ["sru", "opensearch"]
    },
    {
      "id": "japan_national_archives",
      "name": "国立公文書館デジタルアーカイブ",
      "country": "JP",
      "fetcher": "archives_jp_fetcher",
      "mapper": "archives_jp_mapper",
      "access_method": "scraping",
      "base_url": "https://www.digital.archives.go.jp/",
      "response_format": "html",
      "requires_auth": false,
      "metadata_standard": "custom_hierarchical"
    },
    {
      "id": "generic_llm",
      "name": "범용 LLM 파서 (모든 URL)",
      "country": null,
      "fetcher": "generic_llm_fetcher",
      "mapper": "generic_llm_mapper",
      "access_method": "scraping+llm",
      "base_url": null,
      "response_format": "markdown",
      "requires_auth": false,
      "metadata_standard": null,
      "note": "등록된 파서가 없는 모든 URL의 폴백. markdown.new로 변환 후 LLM 추출."
    },
    {
      "id": "manual",
      "name": "수동 입력",
      "country": null,
      "fetcher": null,
      "mapper": "manual_mapper",
      "access_method": "manual",
      "requires_auth": false,
      "metadata_standard": null
    }
  ]
}
```

#### 7.3.5 매핑 결과 기록

매퍼가 공통 스키마를 생성할 때, 각 필드의 출처와 신뢰도를 기록한다:

```json
// bibliography.json 내부의 _mapping_info (선택적)
{
  "_mapping_info": {
    "parser_id": "ndl",
    "fetched_at": "2026-02-13T15:00:00",
    "api_variant": "opensearch",
    "field_sources": {
      "title": {"source_field": "dc:title", "confidence": "exact"},
      "title_reading": {"source_field": "dcndl:titleTranscription", "confidence": "exact"},
      "creator.name": {"source_field": "dc:creator", "confidence": "exact"},
      "edition_type": {"source_field": null, "confidence": null, "note": "NDL에 해당 필드 없음"}
    }
  }
}
```

`confidence` 값:
- `exact`: 1:1 대응 (예: `dc:title` → `title`)
- `inferred`: 추론으로 추출 (예: 件名 "蒙求1" → volume_info "1")
- `partial`: 부분 매핑 (예: 형태사항에서 크기만 추출)
- `null`: 소스에 해당 필드 없음

### 7.4 두 가지 진입 경로

**경로 A: 서지정보 → 파일**
서지정보 페이지 URL/검색 → 파서가 자동 추출·매핑 → bibliography.json 생성 → 파일과 연결

**경로 B: 파일 → 서지정보 (나중에)**
스캔본 먼저 올림 → bibliography.json 비워둠 → 나중에 채움 (수동 또는 파서)

**서지정보가 없어도 파일은 저장소에 존재할 수 있다.**

### 7.5 bibliography.json 스키마

```json
{
  "title": "蒙求",
  "title_reading": "もうぎゅう / 몽구",
  "alternative_titles": [
    "標題徐狀元補注蒙求",
    "補注蒙求"
  ],
  "creator": {
    "name": "李瀚(李翰)",
    "name_reading": null,
    "role": "author",
    "period": "唐"
  },
  "contributors": [
    {
      "name": "徐子光",
      "name_reading": null,
      "role": "annotator",
      "period": "南宋"
    }
  ],
  "date_created": "唐代(原著), 南宋(補注)",
  "edition_type": null,
  "language": "classical_chinese",
  "script": "漢字",
  "physical_description": null,
  "subject": [],
  "classification": {},
  "series_title": null,
  "material_type": null,

  "repository": {
    "name": "国立公文書館",
    "name_ko": "일본 국립공문서관",
    "country": "JP",
    "call_number": null
  },

  "digital_source": {
    "platform": "国立公文書館デジタルアーカイブ",
    "source_url": "https://www.digital.archives.go.jp/DAS/meta/listPhoto?...",
    "permanent_uri": "https://www.digital.archives.go.jp/img.pdf/5057014",
    "system_ids": {
      "BID": "F1000000000000102443",
      "ID": "M2023060105423300156"
    },
    "license": "二次利用自由",
    "accessed_at": "2026-02-13"
  },

  "raw_metadata": {
    "source_system": "japan_national_archives",
    "簿冊標題": "蒙求",
    "件名": "蒙求1",
    "件数": "全3件中 No.1"
  },

  "_mapping_info": {
    "parser_id": "japan_national_archives",
    "fetched_at": "2026-02-13T15:00:00",
    "field_sources": {
      "title": {"source_field": "簿冊標題", "confidence": "exact"},
      "creator.name": {"source_field": null, "confidence": null, "note": "소스에 저자 정보 없음. 사람이 채워야 함."}
    }
  },

  "notes": "唐 李瀚 찬, 宋 徐子光 보주. 일본 전래 삼권본 계통."
}
```

**핵심 설계:**
- **모든 필드 nullable**: 소스에 따라 채울 수 있는 것만 채운다
- `creator.name_reading`: NDL의 `dcndl:creatorTranscription`을 수용하는 필드
- `classification`: NDL의 NDLC/NDC를 `{"NDLC": "...", "NDC9": "...", "NDC10": "..."}` 형태로 저장
- `edition_type`: KORCIS에서만 채워지는 고전적 특화 필드
- `contributors`로 저자/주석자/편자/교정자 등 다양한 역할 표현
- `title_reading`으로 일본어/한국어 독음 지원
- `alternative_titles`로 동일 작품의 다른 명칭 수용
- `digital_source.system_ids`로 아카이브 시스템 고유 ID 보존
- `raw_metadata`에 원본 메타데이터를 그대로 보존 (파싱 후에도 원본 유지)
- `_mapping_info`로 매핑 과정의 투명성 확보

### 7.6 소스 간 교차 보완

같은 작품이 여러 소스에 있을 수 있다. 예: 한국 소장 《蒙求》는 KORCIS에, 일본 소장본은 NDL에.

```
KORCIS에서:  title ✓, creator ✓, edition_type ✓, reading ✗
NDL에서:     title ✓, creator ✓, edition_type ✗, reading ✓
```

**교차 보완 규칙:**
- 자동 병합하지 않는다. 소장본이 다르면 판본도 다를 수 있다.
- 같은 저장소의 같은 소장본에 대해서만, 빈 필드를 다른 소스로 채울 수 있다.
- 병합 시 `_mapping_info`에 복수 소스 기록.

---

## 8. LLM 협업 설계

### 8.1 기본 원칙

1. **동등한 추적**: LLM 출력물도 사람 작업물과 동일한 버전 관리
2. **출처 투명성**: 모델, 프롬프트, 입력 버전이 기록됨
3. **Draft → Review → Commit**: LLM 생성 → 사람 검토 → 확정
4. **병렬 생성**: 여러 안을 동시에 제시 가능
5. **재현 가능성**: 같은 입력 + 같은 프롬프트 → 유사한 결과
6. **온라인 전용**: LLM API는 온라인에서만 호출. 오프라인에서는 기존 draft 검토만.

### 8.2 LLM 작업 기록

```json
{
  "agent": {
    "type": "llm",
    "model": "claude-sonnet-4-5-20250929",
    "provider": "anthropic"
  },
  "input": {
    "source_document": "monggu",
    "source_version": "v2.0",
    "source_commit": "a1b2c3d4...",
    "text_range": {"from": "page_001", "to": "page_010"},
    "block_types_included": ["main_text"]
  },
  "prompt": {
    "template_id": "translation_ko_modern_v1",
    "template_hash": "sha256:def456...",
    "parameters": {"style": "현대어 직역", "target": "main_text_only"}
  },
  "output": {
    "generated_at": "2025-03-15T14:00:00",
    "layer": 6,
    "status": "draft",
    "reviewed_by": null
  }
}
```

`block_types_included`: 본문만 보고 번역했는지, 주석도 포함했는지 기록.

### 8.3 협업 패턴

**패턴 1: LLM Draft → 사람 Review** — 기본. 모든 층에서 동일.
**패턴 2: 병렬 Draft 비교** — 같은 원문, 다른 스타일/모델.
**패턴 3: 반복 정제** — 사람 피드백 → LLM 재생성 → 수렴.
**패턴 4: LLM 교정 보조 (2~4층)** — OCR 신뢰도 낮은 글자에 문맥 기반 제안.
**패턴 5: LLM 레이아웃 분석 (3층)** — 이미지 보고 본문/주석/서문 구분.

### 8.4 프롬프트 관리

```
src/llm/prompts/                    # YAML 기반 프롬프트 (구현)
  ├─ layout_analysis.yaml           # L3 레이아웃 분석
  ├─ punctuation.yaml               # L5 표점 자동 생성
  ├─ translation.yaml               # L6 번역 생성
  ├─ annotation.yaml                # L7 주석 자동 태깅
  ├─ annotation_dict_stage1.yaml    # L7 사전 1단계: 원문→주석
  ├─ annotation_dict_stage2.yaml    # L7 사전 2단계: 번역→보강
  └─ annotation_dict_stage3.yaml    # L7 사전 3단계: 통합/일괄
```

**번역↔주석 양방향 연동**: 번역 생성 시 사전형 주석을 참고 컨텍스트로 포함하고,
번역 변경 시 `translation_snapshot` 비교로 주석 갱신 필요 여부를 감지한다.

---

## 9. UI: 분할 화면

### 9.1 메인 뷰

```
┌───────────────────────────┬───────────────────────────┐
│     원본 저장소 (1~4층)     │     해석 저장소 (5~8층)     │
│                           │                           │
│  ┌─────────┐              │  5층: 끊어읽기·현토          │
│  │ 스캔     │  본문:       │  [본문] 王戎은簡要하고       │
│  │ 이미지   │  天 ✓        │  [주석] 王戎의字는濬沖이니   │
│  │         │  地 ✓        │                           │
│  │  [天]   │  주석:       │  6층: 번역                  │
│  │  [地]   │  王 ✓        │  [본문] 왕융은 간결하고...   │
│  │  [玄]←  │  戎 ✓        │  [주석] 왕융의 자는 준충...  │
│  │  [黃]   │  字 ✓        │  [LLM draft] [사람 수정]     │
│  │         │              │                           │
│  └─────────┘              │  7층: 주석                  │
│                           │  王戎: 字 濬沖. 瑯邪 臨沂人  │
│  OCR 신뢰도: 0.95         │  → 《晉書》 참조 [LLM]      │
│  블록: 본문(大字) ✓        │                           │
│  상태: 교정 완료 v2.0      │  ⚠️ page_003 원본 변경됨    │
├───────────────────────────┴───────────────────────────┤
│                    Git 그래프                           │
│  원본: ──●──●──●── v2.0 ──●── v3.0                    │
│                     │         ╎                        │
│  해석A (사람):       ├──●──●──●──●                      │
│  해석B (LLM):       └──○──○                            │
│  ● 사람  ○ LLM  ◐ LLM+사람  ─ current  ╎ outdated    │
└───────────────────────────────────────────────────────┘
```

**3층(레이아웃 분석) 반영**: 좌측에 "블록: 본문(大字) ✓"가 표시되고,
우측의 현토·번역이 본문/주석으로 구분되어 보인다.

---

### 9.2 JSON 스키마 파일 일람

`schemas/` 디렉토리에 모든 데이터 구조를 JSON Schema로 정의한다.
상세 설명은 `schemas/README.md` 참조.

| 디렉토리 | 스키마 | 버전/상태 | 설명 |
|----------|--------|----------|------|
| `source_repo/` | `manifest.schema.json` | — | 문헌 매니페스트 |
| | `bibliography.schema.json` | — | 서지정보 |
| | `layout_page.schema.json` | — | L3 레이아웃 (LayoutBlock) |
| | `ocr_page.schema.json` | — | L2 OCR (OcrResult) |
| | `corrections.schema.json` | — | L4 교정 기록 |
| | `dependency.schema.json` | — | 해석→원본 의존 추적 |
| | `interp_manifest.schema.json` | — | 해석 저장소 매니페스트 |
| `interp/` | `punctuation_page.schema.json` | v1 | L5 표점(句讀) |
| | `hyeonto_page.schema.json` | v1 | L5 현토(懸吐) |
| | `translation_page.schema.json` | **v1.1** | L6 번역 + `annotation_context` |
| | `annotation_page.schema.json` | **v2** | L7 주석 + 사전형(DictionaryEntry) + 4단계 이력 |
| | `citation_mark_page.schema.json` | v1 | L7 인용 마크 |
| `core/` | `work.schema.json` | — | 코어: 작품 |
| | `text_block.schema.json` | — | 코어: TextBlock |
| | `tag.schema.json` | — | 코어: Tag |
| | `concept.schema.json` | — | 코어: Concept |
| | `agent.schema.json` | — | 코어: Agent |
| | `relation.schema.json` | — | 코어: Relation |
| — | `exchange.schema.json` | v1 | 교환 형식 (스냅샷) |

**주요 스키마 변경 이력:**
- `annotation_page` v1→v2 (D-019): `dictionary`, `current_stage`, `generation_history`, `source_text_snapshot`, `translation_snapshot` 추가
- `translation_page` v1→v1.1 (D-019): `annotation_context` (`used_annotation_ids`, `reference_dict_filenames`) 추가
- `citation_mark_page` 신규 (D-020): 인용 마크 + `citation_override`

---

## 10. 데이터 구조

### 10.1 원본 저장소

```
monggu/                           # = git repository
├── .git/
├── .gitattributes                # git-lfs 설정
├── manifest.json                 # 문헌 메타데이터 + 완성도 + parts
├── bibliography.json             # 서지정보 (섹션 7.3)
├── L1_source/                    # 1층: 원본 (불변, git-lfs)
│   ├── 蒙求1.pdf
│   ├── 蒙求2.pdf
│   └── 蒙求3.pdf
├── L2_ocr/                       # 2층: OCR 결과
│   ├── config.json               # 엔진/설정
│   ├── vol1/
│   │   ├── page_001.json         # 글자 + bbox + confidence
│   │   └── ...
│   └── vol2/
│       └── ...
├── L3_layout/                    # 3층: 레이아웃 분석 (NEW)
│   ├── config.json               # 분석 방법 (LLM/수동/혼합)
│   ├── vol1/
│   │   ├── page_001.json         # 블록 구분 + block_type + refers_to
│   │   └── ...
│   └── vol2/
│       └── ...
├── L4_text/                      # 4층: 교정 텍스트
│   ├── full_text.txt
│   ├── pages/
│   │   ├── vol1_page_001.txt
│   │   └── ...
│   ├── corrections/              # 교정 기록
│   │   └── corrections.json
│   └── alignment/                # OCR↔텍스트 정렬
│       └── vol1_page_001.json
└── user_metadata.json
```

### 10.2 해석 저장소

```
monggu_interp_kim/                # = 별도 git repository
├── .git/
├── dependency.json               # 원본 참조 + 파일 단위 추적
├── manifest.json
├── L5_reading/                   # 5층: 끊어읽기·표점·현토
│   ├── main_text/                # 본문 끊어읽기
│   │   ├── page_001_punctuation.json  # 표점
│   │   └── page_001_hyeonto.json      # 현토
│   └── annotation/               # 주석 끊어읽기 (선택)
│       └── page_001.json
├── L6_translation/               # 6층: 번역 (문장 단위)
│   └── main_text/
│       └── vol1_page_001_translation.json
├── L7_annotation/                # 7층: 주석 + 사전형 주석
│   └── main_text/
│       └── vol1_page_001_annotation.json  # dictionary 필드 포함
├── L8_external/                  # 8층
│   └── external_links.json
├── citation_marks/               # 인용 마크 (연구 도구, 해석 레이어와 별도)
│   └── vol1_page_001_citation_marks.json
├── reference_dicts/              # 참조 사전 (다른 해석에서 가져온 것)
│   └── imported_dict_001.json
├── notes/                        # 자유 연구 노트
│   └── vol1_page_001_notes.json
└── llm_logs/
    └── draft_001.json
```

### 10.3 전체 서고

```
library/
├── library_manifest.json
├── collections/
├── documents/                    # 원본 저장소들
│   ├── monggu/
│   └── cheonjamun/
├── interpretations/              # 해석 저장소들
│   ├── monggu_interp_kim/
│   ├── monggu_llm_claude/
│   └── cheonjamun_interp_kim/
├── resources/
│   ├── block_types.json          # 블록 타입 어휘 정의
│   ├── variant_chars.json        # 이체자 테이블
│   ├── annotation_types.json     # 사용자 정의 주석 유형
│   ├── punctuation_presets.json  # 표점 프리셋 (10종)
│   ├── ocr_profiles/
│   └── prompts/
├── .trash/                       # 휴지통 (D-023)
│   ├── documents/                # 삭제된 문헌 ({timestamp}_{doc_id}/)
│   └── interpretations/          # 삭제된 해석 ({timestamp}_{interp_id}/)
└── .library_config.json

~/.classical-text-browser/        # 앱 전역 설정 (서고 외부, D-022)
└── config.json                   # recent_libraries 등
```

---

## 11. 교환 형식 (내보내기/가져오기)

내부 작업 형식(다수 파일, git 버전관리)과 별도로,
**단일 JSON으로 문서 상태를 스냅샷**하는 교환 형식을 정의한다.

### 11.1 용도

- 다른 연구자에게 현재 상태를 공유
- 외부 시스템과 데이터 교환
- 앱으로 가져오기 (import)

### 11.2 교환 형식 스키마

```json
{
  "schema_version": "1.0",
  "export_info": {
    "exported_at": "2026-02-13T...",
    "source_repo": "https://git.example.com/library/monggu.git",
    "source_commit": "a1b2c3d4...",
    "source_version_tag": "v2.0"
  },

  "source_info": {
    "title": "蒙求",
    "source_type": "manuscript",
    "original_language": "classical_chinese",
    "date_created": "唐代(原著), 南宋(補注)",
    "provenance": "国立公文書館",
    "external_link": "https://..."
  },

  "parts": [
    {
      "part_id": "vol1",
      "label": "蒙求1",
      "file_type": "pdf",
      "file_url": "https://...",
      "file_hash": "sha256:...",
      "page_count": 42
    }
  ],

  "pages": [
    {
      "part_id": "vol1",
      "page_number": 1,
      "mapping_precision": "character",
      "ocr": {
        "blocks": [
          {
            "block_id": "p01_b01",
            "block_type": "main_text",
            "bbox": [50, 30, 180, 600],
            "writing_direction": "vertical_rtl",
            "lines": [
              {
                "text": "王戎簡要裴楷清通",
                "bbox": [50, 30, 70, 600],
                "characters": [
                  {"char": "王", "bbox": [50, 30, 70, 55], "confidence": 0.98}
                ]
              }
            ]
          },
          {
            "block_id": "p01_b02",
            "block_type": "annotation",
            "refers_to_block": "p01_b01",
            "bbox": [120, 30, 200, 600],
            "writing_direction": "vertical_rtl",
            "line_style": "double_line",
            "font_size_class": "small",
            "lines": [...]
          }
        ]
      }
    }
  ],

  "corrected_text": {
    "main_text": "王戎簡要 裴楷清通 孔明臥龍...",
    "annotation": "王戎字濬沖瑯邪臨沂人..."
  },

  "corrections": [
    {
      "page": 3, "block_id": "p03_b01", "line": 2, "char_index": 5,
      "type": "variant_reading",
      "original_ocr": "元",
      "corrected": "元",
      "common_reading": "玄",
      "note": "이 판본에서는 元. 피휘 가능성."
    }
  ]
}
```

**내부 작업 형식 → 교환 형식 변환:**
앱이 원본 저장소의 L1~L4 데이터를 합쳐서 이 JSON을 생성.
**교환 형식 → 내부 작업 형식 변환:**
앱이 이 JSON을 분해해서 L1/L2/L3/L4에 배치하고 git init.

---

## 12. 구현 로드맵

### 현실적 접근

전체 앱을 한꺼번에 만들지 않는다.
각 Milestone이 **독립적으로 쓸 수 있는 도구**를 만들어낸다.

### Phase 1: 원본 저장소 도구 (1~4층) — ✓ 완료

**M1.1 서고 구조 초기화** ✓
- `init_library.py`: 서고 디렉토리 구조 생성
- `add_document.py`: 이미지/PDF를 서고에 등록 + git init + git-lfs 설정
- manifest (다권본 parts 포함) 자동 생성

**M1.2 서지정보 파싱 (파서 아키텍처)** ✓
- 파서 등록 구조 구현 (registry.json)
- 구현된 파서: KORCIS, NDL Search, 일본 국립공문서관, **범용 LLM 파서** (D-021)
- 범용 LLM 파서: markdown.new + LLM으로 모든 URL 지원
- 에셋 자동 감지 + 다운로드 (PDF/이미지 번들)
- raw_metadata 보존, _mapping_info 기록

**M1.3 OCR 파이프라인** ✓
- PaddleOCR 기본 엔진 (paddlepaddle 3.3.0 + paddleocr 2.10.0)
- LLM Vision 엔진 (Ollama/Gemini/OpenAI)
- 표준 JSON 출력 (글자 + bbox + confidence)

**M1.4 레이아웃 분석 도구** ✓
- LLM에게 페이지 이미지를 보내 블록 구분
- block_type 12종 어휘 적용
- 사람 검토 인터페이스

**M1.5 정렬 엔진** ✓
- OCR 결과 ↔ 확정 텍스트 글자 단위 정렬 (D-012)
- 이체자 사전 보정

**M1.6 교정 뷰어 (HTML)** ✓
- 이미지 + 텍스트 나란히 보기
- 불일치 하이라이팅
- 교정 유형 선택 (ocr_error / variant_reading 등)
- 교정 + git commit 연동

### Phase 2: 저장소 연결 + LLM — ✓ 완료

**M2.1 해석 저장소 구조 + dependency.json** ✓
**M2.2 파일 단위 변경 감지 (access-time check)** ✓
**M2.3 LLM 협업 인터페이스 (draft → review → commit)** ✓ (D-010)
**M2.4 분할 화면 (좌: 원본, 우: 해석, 본문/주석 구분)** ✓
**M2.5 사다리형 git 그래프** ✓ (D-017)

### Phase 3: 해석 도구 (5~8층) — 대부분 완료

**M3.1 끊어읽기·표점·현토 (5층)** ✓ (D-014)
**M3.2 번역 워크플로우 + LLM (6층)** ✓ (D-015)
- 문장 단위 번역, SourceRef 추적, 현토 스냅샷
- LLM 번역 생성 + 사전형 주석 참조 기능 추가
**M3.3 주석/사전 연동 (7층)** ✓ (D-016, D-019)
- 주석 태깅 + 사전형 주석 (dictionary 필드, 4단계 LLM 누적 생성)
- 사전 내보내기/가져오기/참조 매칭
- 인용 마크 시스템 (D-020)
**M3.4 외부연계 (8층)** — 미구현

### Phase 4: 인프라 — 진행 중

**M4.1 서지정보 소스 추가** ✓ 범용 LLM 파서로 모든 URL 지원
**M4.2 OCR 엔진 추가** ✓ PaddleOCR + LLM Vision
**M4.3 웹 인터페이스** ✓ FastAPI + vanilla JS (빌드 도구 없음)

### Phase 5: 서고 관리 — ✓ 완료 (2026-02-20 추가)

**M5.1 GUI에서 서고 전환/생성** ✓ (D-022)
**M5.2 최근 서고 목록 + 자동 선택** ✓ (D-022)
**M5.3 휴지통 시스템** ✓ (D-023)
**M5.4 JSON 스냅샷 Export/Import** ✓ (D-018)

---

## 13. 미결 사항 & 추후 논의

### 원본 저장소

1. ~~JSON 스키마 각 필드의 상세 정의~~ → 완료 (jsonschema 검증)
2. ~~서지정보 파싱 상세~~ → 완료 (4개 파서 + 범용 LLM 파서)
3. OCR 엔진 비교 평가 (PaddleOCR vs LLM Vision 벤치마크)
4. git-lfs 설정 상세 (어떤 확장자를 LFS로 관리할지)
5. block_type 어휘 확장 (문헌 유형별 필요한 type)

### LLM 협업

6. ~~LLM 호출 아키텍처~~ → 완료 (D-010, 4단 폴백)
7. ~~프롬프트 설계 원칙~~ → 완료 (층별 YAML 프롬프트)
8. ~~비용 관리~~ → 완료 (UsageTracker + 월별 예산)

### 저장소 연결

9. ~~사다리형 git 그래프 구현~~ → 완료 (D-017)
10. git 호스팅 선정

### 해석 저장소

11. ~~5~8층 데이터 모델 상세~~ → 완료 (D-014~D-016, D-019~D-020)
12. ~~본문/주석 번역의 연결 구조~~ → 완료 (D-015 SourceRef)
13. 협업 모델 (다수 연구자 참여 시)
14. L8(외부연계) 설계 상세

### 배포·설치

15. Google Drive + .git 충돌 회피 가이드
16. 비개발자용 Git 번들링 또는 Git-free 모드
17. HWP 가져오기/내보내기 (Part C 계획 수립됨, 미구현)

### 전체

18. 라이선스/공개 범위
19. **프로젝트 이름**

---

## 부록 A: 이 기획서의 형성 과정

1. 매핑 유틸리티 → 글자 단위 매핑 + 오류 하이라이팅 + 교정/커밋
2. → OCR 불가 케이스 포함, 매핑 정밀도 스펙트럼
3. → 유니버설 앱, 엔진/언어/레이아웃 설정 가능
4. → 물리적 원본과 디지털 텍스트의 연결이 끊어지지 않는 구조 (provenance)
5. → 연구자의 개인 디지털 서고 (도서관 규모)
6. → 서지정보 자동 파싱 + 점진적 완성
7. → 버전관리 + 파생물 계보 추적 (GitHub 모델)
8. → 7층 모델: 원본 저장소(1~3) + 해석 저장소(4~7) 분리
9. → 병렬 저장소: 3층 확정 시점에서 독립 저장소 분기
10. → 분할 화면 UI + 사다리형 git 그래프
11. → Git 백엔드: 로컬/원격 동기화, 협업, 백업
12. → LLM 협업을 설계 전제로: Draft → Review → Commit
13. → GitHub fork 제약 → 독립 repo + dependency.json 참조 방식 확정
14. → 파일 단위 의존 추적 + access-time check
15. → 아키텍처 확정: Git은 저장소, 앱이 두뇌 — 호스팅 비종속
16. → 오프라인 퍼스트: 핵심 작업은 오프라인, LLM은 온라인
17. → 데스크톱 ↔ 웹 전환: git repo가 상태이므로 앱 형태 무관
18. → 교환 형식: 내보내기/가져오기용 단일 JSON
19. → **《蒙求》 워크스루로 실증 검증**: 9개 문제 발견, 8층 모델로 확장
    - 다권본 지원 (manifest.parts)
    - 레이아웃 분석 층 신설 (3층)
    - block_type 어휘 정의
    - 블록별 writing_direction
    - 판본 이문(variant_reading) 교정 유형
    - bibliography.json 확장 (독음, 별제, 기여자, 시스템ID)
    - 본문/주석 구분된 해석 저장소 구조
    - git-lfs 필수 확정
20. → 해석 도구 전층 구현: L5 표점/현토, L6 번역, L7 주석 + 사전형 주석 + 인용 마크
21. → 범용 에셋 감지 (모든 URL에서 PDF/이미지 자동 다운로드)
22. → GUI 서고 관리 (런타임 전환, 최근 목록, 새 서고 생성)
23. → 휴지통 시스템 (소프트 삭제 + 복원)

## 부록 B: 핵심 설계 결정 요약

| # | 결정 사항 | 선택 | 이유 |
|---|---|---|---|
| 1 | 층 수 | **8층** (v6까지 7층) | 레이아웃 분석이 독립 단계 (《蒙求》 검증) |
| 2 | 저장소 구조 | 독립 repo + dependency.json | git fork 제약 회피, 호스팅 비종속 |
| 3 | 변경 감지 | access-time check | 실시간 불필요, 인프라 최소화 |
| 4 | 의존 추적 | 파일 단위 해시 | "내가 참조한 파일이 변경됨" |
| 5 | 역할 분리 | git=저장, 앱=관계/의미/UI | git에 없는 기능을 앱이 담당 |
| 6 | LLM | 설계 전제 (1등 참여자) | Draft → Review → Commit |
| 7 | LLM 호출 | 온라인 전용 | 로컬 LLM으로 고전 한문 처리 비현실적 |
| 8 | 호스팅 | 비종속 (교체 가능) | 데이터 모델이 호스팅에 의존하지 않음 |
| 9 | 저장소 분리 | 원본(1~4) / 해석(5~8) | 성격이 다르다 (재현 vs 해석) |
| 10 | 대용량 파일 | git-lfs 필수 | PDF 수십MB, 이미지 수백MB |
| 11 | 다권본 | manifest.parts | 하나의 작품 = 여러 물리적 파일 |
| 12 | 블록 구분 | block_type 어휘 | 본문/주석/서문/간기 등 구조적 역할 |
| 13 | 네트워크 | 오프라인 퍼스트 | 핵심 작업은 오프라인, LLM/동기화는 온라인 |
| 14 | 앱 형태 | 웹 기술 + 데스크톱 래핑 | 코드베이스 통일, 데스크톱↔웹 전환 가능 |
| 15 | 교환 형식 | 단일 JSON 스냅샷 | 내보내기/가져오기용, 내부 형식과 별도 |
| 16 | 서지 파서 | 플러그인 (fetcher + mapper) | 소스마다 구조가 다름, 새 소스 추가 시 기존 코드 수정 없음 |
| 17 | 매핑 원칙 | 모든 필드 nullable + raw 보존 | 소스에 없는 필드는 비우고, 원본은 항상 유지 |
| 18 | 주석 확장 | 기존 태깅 + dictionary 필드 | 별도 엔티티보다 점진적 확장이 효율적 (D-019) |
| 19 | 인용 마크 | 해석 레이어와 별도 디렉토리 | 연구 도구와 해석 데이터의 성격이 다름 (D-020) |
| 20 | 에셋 감지 | 범용 유틸리티 (파서 독립) | 모든 URL에서 PDF/이미지 자동 다운로드 (D-021) |
| 21 | 서고 관리 | 앱 설정 + GUI 전환 | 런타임 서고 전환, CLI 인자 선택화 (D-022) |
| 22 | 삭제 정책 | 서고 내 .trash/ 소프트 삭제 | OS 독립적 복원 가능 (D-023) |

## 부록 C: 《蒙求》 워크스루 결과

v7에서 반영된 문제들:

| # | 발견된 문제 | 해결 방식 | 반영 위치 |
|---|---|---|---|
| 1 | 다권본 구조 없음 | manifest.parts 도입 | 5.1 |
| 2 | 서지정보 필드 부족 | bibliography.json 확장 | 7.5 |
| 3 | 일본 아카이브 메타데이터 | 파싱 대상 추가 + raw_metadata | 7.1, 7.2, 7.5 |
| 4 | block type 어휘 없음 | block_type 어휘 정의 | 5.3 |
| 5 | 레이아웃 분석 단계 없음 | **3층 신설, 7층→8층 확장** | 2.1, 5.3 |
| 6 | writing_direction 문서 단위 | 블록별 설정으로 변경 | 5.3 |
| 7 | 판본 이문 교정 유형 없음 | variant_reading 추가 | 5.4 |
| 8 | 본문/주석 해석 구분 없음 | main_text/annotation 하위 디렉토리 | 6.2 |
| 9 | git-lfs 필수 확인 | 미결→필수로 격상 | 5.1, 부록B #10 |
