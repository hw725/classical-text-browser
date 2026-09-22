# 백로그 — 합의된 추후 과제

릴리스에 묶이지 않은 개선 요청을 기록한다. 착수 시 DECISIONS에 설계 결정을 남기고
이 항목을 지운다.

## B-001 세로쓰기 대조 교정 뷰 (2026-08-21, 운양 프로젝트 사용 경험에서)

원문 이미지와 텍스트를 나란히 놓고 **세로쓰기(vertical-rl) + 행별 하이라이팅**
상태에서 행 텍스트를 교체(교정)하고 이력이 남는 뷰. 현재 ctb의 교정 UI는 가로쓰기
중심이라, 고서(세로쓰기) 대조 교감 작업에는 외부 뷰어(운양 `viewer/index.html` +
`17_viewer_server.py`)를 따로 만들어 썼다.

- 요구: ① 세로쓰기 텍스트 패널 ② 이미지 bbox ↔ 행 클릭 동기 하이라이팅
  ③ 행 단위 텍스트 교체 저장 ④ 수정 이력 누적(ctb는 git 이력이 이미 있으므로 연결만)
- 참고 구현: 운양 뷰어의 층위 규약(text < text_corrected < text_human,
  append-only human_edits.jsonl)과 PDF.js 오버레이 방식
- 관련 우려(같은 대화에서): 속음청사급(18권 3,018쪽) 대규모 문헌을 ctb가 감당하는지
  1권 파일럿 실측 필요 — 적재·편집·git 커밋 응답속도

## B-009 화면 JS 의 전역 함수 이름이 여섯 겹친다 (2026-09-22 실측)

화면 JS 는 classic script 라 최상위 `function` 이 전부 전역이다. 두 파일이 같은 이름을
선언하면 **뒤에 적재된 쪽이 이기고**, 앞쪽 파일의 호출까지 남의 구현으로 돈다.
예외도 경고도 나지 않는다. 지금 여섯이 겹쳐 있고 **여섯 다 구현이 다르다.**

| 이름 | 선언한 파일(적재 순) | 이기는 쪽 |
|---|---|---|
| `_escapeHtml` | correction-editor · bibliography · hwp-import · alignment-view · git-graph | git-graph |
| `_escHtml` | entity-manager · variant-manager · batch-correction · annotation-editor | annotation-editor |
| `_escAttr` | variant-manager · annotation-editor | annotation-editor |
| `_renderAnnList` | hyeonto-editor · annotation-editor | annotation-editor |
| `_renderSourceText` | translation-editor · annotation-editor | annotation-editor |
| `_renderStatusSummary` | translation-editor · annotation-editor | annotation-editor |

**어떻게 드러났나:** `_updateSaveStatus` 가 `text-editor.js`(교정 탭)와
`interpretation.js`(죽은 해석 패널) 둘에 있었고 뒤인 interpretation 이 이겨,
**교정 탭에서 저장해도 상태 표시가 안 바뀌고 있었다.** B-008 철거로 그 정의가
사라져 함께 고쳐졌고, 그 자리를 세다가 나머지 여섯을 찾았다.

**이미 고친 것 하나 — 이스케이프.** 이기던 `annotation-editor.js::_escHtml` 이
**큰따옴표를 막지 않았다.** `entity-manager.js` 가 Concept 라벨을 `title="…"` 속성에
넣는 자리(entity-manager.js:215)가 따옴표로 속성을 벗어날 수 있었다 — D-069 가
경고한 「화면에 넣는 것은 이스케이프」의 바로 그 자리다. 이기는 판을 엄격하게
만들어 모든 호출부가 함께 안전해지게 했다(적재 순서를 node 로 재현해 확인:
`x" onmouseover="bad()` → `x&quot; onmouseover=&quot;bad()`).

**남은 것은 `_render*` 셋이고, 「흉한 것」이 아니다.** 건드리는 요소가 서로 완전히
다르다 — 적재 순서는 hyeonto(5118) → translation(5119) → **annotation(5120)** 이라
주석 편집기 판이 이긴다.

| 함수 | 이기는 annotation 판이 건드리는 것 | 지던 판이 건드리던 것 |
|---|---|---|
| `_renderAnnList` | `ann-list` · `ann-type-filter` | **`hyeonto-ann-list` · `hyeonto-ann-count`** |
| `_renderSourceText` | `ann-source-text` | **`trans-source-text`** |
| `_renderStatusSummary` | `ann-status-summary` | **`trans-status-summary`** |

**id 가 하나도 겹치지 않는다.** 그러니 현토 탭이 `_renderAnnList()` 를 부르면
주석 탭의 목록을 그리고 `#hyeonto-ann-list` 는 영영 갱신되지 않는다. 번역 탭도
같아서 **원문 칸(`#trans-source-text`)과 상태 요약이 죽어 있다.**

**쟀다 (2026-09-22). 추론이 아니라 실측이다.** headless Chrome 으로 단위를 고른 뒤
탭을 열어 요소를 직접 읽었다. 파일은 고치지 않았다.

① 실행 중에 전역으로 묶인 구현이 «누구 것인가» — `Function.prototype.toString()` 의
지문으로 판정했다. `_renderAnnList`·`_renderSourceText`·`_renderStatusSummary`·
`_escHtml` **넷 다 `annotation-editor` 의 것**이었다.

② 단위를 고르고 **번역 탭**을 열었을 때:

| 요소 | 보임 | 글자수 |
|---|---|---|
| `#trans-source-text` (번역 탭의 **원문 칸**) | true | **0** |
| `#trans-status-summary` | true | **0** |
| `#ann-source-text` (숨어 있는 주석 탭 요소) | false | 8 «(텍스트 없음)» |
| `#ann-status-summary` (숨어 있는 것) | false | 18 «전체 0 / 확정 0 / 초안 0» |

**보이는 칸은 비어 있고 숨은 칸이 채워진다.** 대조군으로 **주석 탭**을 열면 같은
단위에서 `#ann-source-text` 가 **1,656자**(「Ⅱ. 擬人體文學의 槪念 「擬人」의…」)다 —
`_renderSourceText` 는 제대로 돌지만 **언제나 주석 탭 요소에 쓴다.** 번역 탭의 원문
칸이 채워지는 길이 없다.

③ 현토 탭은 `#hyeonto-ann-list` 가 보이면서 비어 있고 `#hyeonto-ann-count` 는
처음 값 «0» 그대로다. 이 서고에는 주석이 0건이라 **「주석이 없어서 빈 것」과
구분되지 않는다** — 주석이 있는 자료로 다시 재야 확정된다. 번역 쪽은 확정이다.

콘솔 오류 0건. 즉 **예외 없이 조용히 빗나간다.**

재는 스크립트는 스크래치패드의 `b009_measure.py` 다(읽기 전용).
- 고치는 방향은 `_escHtml` 과 다르다. 이스케이프는 「이기는 판을 가장 엄격하게」로
  한 줄이면 됐지만, 여기는 **구현이 서로 다른 화면을 그리므로 합칠 수 없다.**
  지는 쪽 셋의 이름을 바꾼다(`_renderHyeontoAnnList`·`_renderTransSourceText`·
  `_renderTransStatusSummary`). 부르는 자리까지 열댓 줄이다.
- `_escapeHtml` 다섯은 세 구현이고 전부 텍스트 자리로 보이지만, 그것도 재 보지 않았다.
- 기계가 지키는 것: `tests/test_ui_reachability.py::TestGlobalNamesDoNotShadow` 가
  **늘지 않는 것**을 지키고(`KNOWN` 목록), 고치면 `test_known_list_is_not_stale` 가
  「목록에서 지워라」고 알려 준다. `TestEscapeHelpersAreStrict` 는 이스케이프 헬퍼가
  느슨해지는 것을 막는다.

## B-008 해석 패널이 어느 모드에서도 열리지 않는다 (2026-09-22 실측 → **같은 날 철거로 닫음**)

`#interp-panel`은 `_switchMode("interpretation")`만 여는데 `data-mode="interpretation"`
탭이 `index.html`에 없다. 그래서 그 안의 도구 바 단추 둘(「단위 만들기」·「LLM에게 요청」)과
공용 「저장」(`interp-save`)이 **보이지 않는다.** `interpState.active`도 참이 되는 길이 없어
`_updateToolbarButtons()`의 조건이 항상 거짓이다.

- 어떻게 알았나: 커넥톰 대조 단추를 그 도구 바에 붙였다가 headless Chrome 으로 눌러 보니
  보이지 않았고, 조상을 거슬러 올라가 패널이 `display:none`인 것을 찾았다. 모드 탭 열을
  전부 눌러 봐도 `active`는 끝까지 false 였다.

**탭은 사고로 지워졌다 — 그러나 되살리면 안 된다** (2026-09-22, 다른 세션이 이력을 캐고
이쪽에서 다시 확인했다).

- 탭 이름은 「비교」였다. `ce9743a`(2026-02-14, Phase 7)가 넣었고 `e84d800`(2026-02-24)이
  지웠다. 그 커밋 제목은 **「비교 탭 L6/L7 수정」**이고 본문에도 탭을 없앴다는 말이 없다 —
  고치겠다고 한 것의 **입구를 같은 커밋에서 지웠다.** 대신 들어온 탭도 없다(diff 확인).
  D-096(2026-09)보다 일곱 달 앞이라 「다섯으로 갈라지며 남은 자리」가 아니다.
- 그런데 그 패널의 본체는 **D-096 이전의 통합 편집기**(「해석 (L5~L7)」 + 층별 서브탭)다.
  지금은 다섯이 각자 패널(`punct-panel`·`hyeonto-panel`·`trans-panel`·`ann-panel`·
  `cite-panel`)과 모드 탭을 갖고 있으므로, 탭을 되살리면 **대체된 옛 편집기가 함께 돌아온다.**

**무엇이 실제로 빠지는가** — 「단추 셋이 안 보인다」보다 좁기도 하고 넓기도 하다.

| | 상태 | 어디에 |
|---|---|---|
| 의존 **정보**(어느 파일이 바뀌었나) | **살아 있다** | 액티비티 바 「의존 추적」 → `#dep-sidebar-section`(`dep-status-summary`·`dep-file-list`) |
| 의존 **경고**(「원본이 변경되었습니다」) | 죽었다 | `interp-dep-banner` |
| `diff` · **변경 인지** · **기반 업데이트** | 죽었다 | `interp-dep-diff`·`interp-dep-ack`·`interp-dep-update` |
| 스냅샷 **가져오기** | **살아 있다** | `snapshot-import-btn`(`#interp-section`) |
| 스냅샷 **내보내기** | 죽었다 | `snapshot-export-btn` |
| 「단위 만들기」·「LLM에게 요청」·공용 「저장」 | 죽었다 | `interp-toolbar` |

즉 **상태를 바꾸는 두 동작**(`dependency/acknowledge`·`dependency/update-base`)에 화면에서
닿을 길이 없다. 읽는 쪽은 사이드바가 대신하고 있어 여태 티가 나지 않았다. 스냅샷은
**가져오기만 살고 내보내기가 죽은 비대칭**이다.

**이사는 끝났다 (2026-09-22, `46190ee`).** 사용자가 자리를 정해 주었다.

- 의존 경고와 「확인」·「기반 업데이트」 → **「의존 추적」 사이드바 안**. 「어느 파일이
  바뀌었나」를 그리는 자리(`dep-file-list`) 바로 위라 보는 것과 누르는 것이 모인다.
  `diff` 단추는 걷어냈다 — 하던 일이 그 사이드바를 대신 눌러 주는 것뿐이라
  제자리걸음이 된다. 좁은 폭에서 「기반 업데이트」가 잘리지 않게 CSS 가 줄을 접는다.
- 스냅샷 **내보내기** → 「JSON 가져오기」 바로 옆. 받을 수는 있는데 내보낼 수가 없던
  비대칭이 사라졌다.
- `tests/test_ui_reachability.py`(11건)가 **「닿을 수 있는가」를 기계로 지킨다** —
  조작 단추가 든 사이드바 섹션이 `panelSections` 에 실려 있고 그 이름의 액티비티
  단추가 실재하는지 본다. id 를 세는 검사로는 이 버그가 안 잡힌다(단추도 배선도
  멀쩡했다 — 죽은 것은 조상이다).

**철거했다 (2026-09-22, 사용자 지시).** 「손으로 경계 만드는 길이 필요함. 옛 통합
편집기와 죽은 조건 걷어내.」

**이것은 `e84d800` 이 시작한 일을 끝낸 것이다** — 앞의 「사고 삭제」 판정을 고친다.
그 커밋은 탭을 지우면서 `_switchMode` 머리에 `// Interpretation mode tab is removed
from UI. Fallback to view if called externally.` 를 **함께** 넣었다. 의도된 제거였고
코드에 스스로 적어 두었다. 커밋 메시지와 DECISIONS 에만 안 적혔을 뿐이다. 실패한
것은 «지웠다»가 아니라 «절반만 지웠다»였다 — 패널과 그 안의 것들을 남겨 두어
의존 추적의 쓰는 쪽과 스냅샷 내보내기가 일곱 달 닿을 수 없었다.

걷어낸 것:

| 어디 | 무엇 |
|---|---|
| `index.html` | `#interp-panel` 106줄 · `#llm-dialog-overlay` 66줄 |
| `interpretation.js` | `_loadLayerContent`·`_saveLayerContent`·`_updateSaveStatus`·`_updateFileInfo` 108줄 · `activate/deactivateInterpretationMode` · `interpState` 의 `active`·`currentLayer`·`currentSubType`·`isDirty` |
| `workspace.js` | `_switchMode` 의 해석 가지 둘 · 머리의 폴백 · `interpState.active` 블록 · `interpPanel` 변수 |
| `entity-manager.js` | 「단위 만들기」 118줄(`_openUnitCreator`·`_saveUnitFromSource`) · LLM 스텁 · `_updateToolbarButtons` |
| `workspace.css` | `.interp-subtab*`·`.interp-subtype-bar`·`.interp-panel`·`.interp-content` 100줄 |

**LLM 스텁 창도 함께 걷었다.** `#llm-dialog-overlay` 는 입력 넷과 「요청」 단추에
**배선이 하나도 없어 닫기만 되는 창**이었고(2026-09-22 확인), 그것을 여는 단추가
죽은 패널 안이었다. 해석 저장소에서 LLM 을 부르는 길은 각 편집기의 「AI 보조」다.

**라우트 `entities/unit/from-source` 는 남겼다** — `create_entity("unit")` 이
`_create_boundary_from_unit` 으로 보내 지금 규약대로 경계를 쓴다(entity.py:607).

### 손으로 경계 만드는 길 — 남겼고, 그 전에 **고쳐야 했다**

사용자가 필요하다고 한 능력은 사이드바 「내용」의 **「＋ 경계 넣기」**가 맡는다.
찍어서 (행·글자)를 얻고(D-094), 안 되면 「숫자로 적기」로 쪽·행·자를 주며, 제목과
본문은 코드가 확정본에서 가져온다. 저장은 `POST /api/documents/{doc}/boundaries`(D-097).

**그런데 눌러 보니 500 이었다.** 세션 둘이 각각 코드를 읽고 「살아 있음」으로 판정한
길이다 — `data-panel="explorer"` 도 `panelSections` 도 조건 없는 렌더도 다 맞았는데,
**닿는 것과 도는 것이 또 달랐다.** `anchor_bbox` 의 `list(idx["boxes"][k])` 에서
`TypeError: 'NoneType' object is not iterable`. 그 문헌은 행 상자가 전부 None 이었다
(1쪽 27/27 · 2쪽 34/34 · 3쪽 35/35) — LLM 비전 판독은 글자만 주고 좌표를 주지 않는다.
즉 **좌표 없는 문헌에서는 손으로 경계를 넣는 길이 통째로 막혀 있었다.** 여러 쪽
CPU 환경에 LLM 비전을 권하고 있으니(B-005) 드문 자료가 아니다.

고쳤다 — 좌표가 없으면 `None` 을 돌려준다. 그 함수 독스트링의 「틀린 좌표보다 안
보여 주는 게 낫다」와 같은 자리이고, `boundary_bbox` 가 이미 None 을 받아 처리하며
스키마도 bbox 없이 저장한다. **경계는 (쪽, 행)이고 좌표는 점선을 그리기 위한
캐시일 뿐이다.** 시험 4건(`TestAnchorWithoutCoordinates`)을 붙였고, 고침을 되돌리면
정확히 그 TypeError 로 셋이 빨강이 된다.

**만약 이것을 안 고친 채 철거했다면**, 사용자가 「필요하다」고 한 능력이 화면에는
있는데 누르면 500 이 나는 상태가 됐을 것이다. B-008 에 적어 둔 순서(«자리를 정한
뒤에 걷어낸다»)가 지킨 것은 «옮기기»뿐이 아니었다 — **대신할 길이 실제로 도는지
재는 것**까지였다.

### 확인한 방법

모드 탭 10 개와 액티비티 패널 8 개를 headless Chrome 으로 차례로 눌러 **콘솔 오류
0**, 지운 id 여섯이 DOM 에 없음, 「＋ 경계 넣기」로 경계가 실제로 늘어남(1 → 2).
시험은 `test_ui_reachability.py` 의 `test_the_dead_panel_is_gone`(되살아나면 빨강)과
`test_the_hand_made_boundary_path_still_exists`(행 칸·라우트가 사라지면 빨강)가 지킨다.

**함께 나온 것(같은 실측, D-128 과 무관):** `entity.py:153 _get_source_head_commit`
이 `interpretation.py:232` 와 본문이 같은 중복 정의이고 시험에서 안 돈다 ·
`entity.auto_create_units_from_text` 는 부르는 곳이 없다 ·
`entity.create_unit_from_source` 는 라우트가 부르는데 시험이 한 번도 안 들어간다.

## B-003 저장 파일의 `block_id` → `unit_id` (2026-09-03, D-093에서 남김)

D-093이 이름을 `unit`으로 바꿨지만 **저장 파일이 단위를 가리키는 필드는 `block_id` 그대로**다.
표점·현토 파일 이름의 `_blk_` 조각도 마찬가지다.

- 왜 미뤘나: 필드·파일 이름을 바꾸면 저장 형식이 바뀐다. 이미 표점·번역을 한 서고에서
  파일 이름이 어긋나면 그 작업이 **조용히 안 보이게** 된다 — 자동 테스트가 못 잡는 자리다.
- 하려면 함께 있어야 할 것: ① 쓰는 쪽을 `unit_id`로 ② 읽는 쪽은 한 판 동안 둘 다 받기
  ③ 옛 파일을 옮기는 스크립트(파일 이름의 `_blk_` 포함, 해석 저장소 커밋)
  ④ 다음 판에서 `block_id` 읽기 삭제.
- 대상 파일: `L5_reading/**`(표점·현토), `L6_translation/**`, `L7_annotation/**`,
  `citation_marks/**`, `core_entities/tags/*.json`.
- 지금 서고에는 이 파일이 0건이라 급하지 않다.

## B-004 Windows 설치 파일(exe) (2026-09-05 → **2026-09-06 D-113으로 구현**)

> 구현됨: `CTB-Setup.exe`(설치 프로그램, 약 11MB, `installer/ctb_setup.py`). 앱을 내려받아 `install.ps1`을
> 돌리고 바탕화면 아이콘을 만든다. 업데이트는 D-112 자동 경로. 아래는 미루던 때의 기록.

지금 설치는 zip → `install.bat`(ASCII 껍데기) → `install.ps1`이 Python·Git·uv를 받아 깐다.
처음 접하는 사람에게는 exe 하나가 낫다는 데 합의했지만 v1.3.0에는 넣지 않았다.

- 왜 미뤘나: 앱 안 업데이트(D-103)가 `git pull --ff-only` + `uv sync`라 **Git 사본이
  아니면 동작하지 않는다.** exe로 깐 사람에게는 업데이트 길이 없어진다 — 그 판을 먼저
  내보내면 exe 사용자만 갱신이 막힌다.
- 먼저 있어야 할 것: ① «릴리스 자산을 받아 제자리 교체» 업데이트 경로(Git 없이) ② 그 경로와
  D-103 경로를 설치 방식에 따라 고르는 판별 ③ 서고·키·엔진 기록(`.ctb-extras.json`)이 앱 폴더
  교체에 살아남는지 확인(서고는 밖에 있어 안전, 엔진 기록은 앱 루트라 옮겨야 한다)
- 후보 도구: PyInstaller(onedir) 또는 uv의 임베디드 파이썬 + Inno Setup. OCR 스택(830MB)이
  그대로 들어가므로 설치 파일도 그 크기다 — 엔진을 뺀 «본체만» exe와 엔진 추가 설치(D-106)의
  조합이 현실적이다.
- 관련: D-103(업데이트), D-106(엔진 설치 GUI), 사용자 가이드 0장.

## B-005 PaddleOCR CPU 쪽당 50~75초 (2026-09-05 실측)

Windows + paddlepaddle 3.3.1 CPU에서 한 쪽(1376×1929, 33행) 인식이 server 검출 75초,
mobile 검출 52초, 스레드 20개로도 61초. OneDNN을 켜면 여전히
`ConvertPirAttribute2RuntimeAttribute not support`로 크래시(D-078 시절과 같음). GPU는 1초.

- 지금 해 둔 것: 사용자 가이드 7-A.4에 실측치를 적고 여러 쪽이면 LLM Vision을 권함.
- 해 볼 것: paddlepaddle 3.4+에서 OneDNN 크래시가 풀렸는지(풀리면 CPU가 몇 배 빨라진다),
  PaddleOCR 대신 onnxruntime 경로(NDL 엔진이 쓰는 것, 7초/쪽)로 검출만 옮기기.
- 실측 스크립트: scratchpad `paddle_prof2.py` (server|mobile|mkldnn|threads).

## B-006 PaddleOCR 검출을 onnxruntime으로 (2026-09-06, 실측 조건부 — 제자리 줄 수 유지 시 교체 → **미달, 보류**)

기본 번들의 PaddleOCR은 인식이 아니라 **글자 위치 검출**(형광 자리, D-055) 때문에 들어 있다.
대가가 크다 — 설치 651MB, 첫 실행 모델 240MB(Baidu), Windows CPU에서 OneDNN 크래시 회피 경로.
같은 PP-OCRv5 검출 모델을 onnxruntime으로 돌리면(예: rapidocr-onnxruntime) 이 셋이 사라진다.

- **조건**: 현동 이안중 연구 논문(15쪽, 기준 433/502줄 제자리)으로 교체 전후를 같은 잣대
  (`embed_text_layer`의 positioned/detected + D-068 잉크 검사)로 재서 **숫자가 유지될 때만** 바꾼다.
  인식 품질은 기본 흐름(LLM이 읽음)과 무관하지만, Paddle을 직접 고르는 경우를 위해 CER도 잰다.
- 바꾸면: paddlepaddle은 `--extra paddle`(선택)로, 기본은 onnxruntime + 검출 모델. install.ps1의
  5단계(모델 미리 받기)는 필요 없어진다.
- 실측 스크립트·결과는 이 항목 아래에 덧붙인다.

**실측 결과(2026-09-06) — 미달, 바꾸지 않았다.** 같은 논문 15쪽, 기준 L2는 ChatGPT 계정(OAuth)
gpt-5.4-mini로 새로 만든 것(첫 시도는 D-110의 OAuth 이미지 거부로 막혀 고친 뒤 다시 돌렸다).
같은 L2 위에 검출기만 바꿔 `embed_text_layer`를 돌렸다(스크립트 `C:	mp006_compare.py`).

| 검출기 | 제자리 줄 | 검출 시간/쪽 | 전체 |
|---|---|---|---|
| PaddleOCR TextDetection(현재, PP-OCRv6 medium) | **142**/440 | 8.1s | 133s |
| rapidocr 3.x(onnxruntime) PP-OCRv6 small, 기본 설정 | 97/440 | 0.9s | 25s |
| rapidocr PP-OCRv6 medium, limit 736/min | 97/440 | — | 190s |
| rapidocr PP-OCRv6 medium, limit 1280/max | 97/440 | — | 186s |
| rapidocr PP-OCRv6 medium, limit 64/min | 97/440 | — | 181s |
| rapidocr PP-OCRv6 medium, box_thresh 0.6·unclip 1.5(Paddle 기본값) | 97/440 | — | 174s |
| rapidocr **PP-OCRv5 server**, 기본 설정 | **142**/440 | 약 10s | 158s |

잉크 경고는 전부 0건. v6 small·medium은 검출이 9배 빠르지만 제자리 줄이 142 → 97로 줄어 조건을 못 지켰다.
**PP-OCRv5 server는 142줄로 Paddle과 같다** — 다만 쪽당 약 10초로 Paddle(8초)보다 느려 속도 이득이 없다.
그래서 v1.3.0은 PaddleOCR 기본 번들 그대로 간다(2026-09-06 사용자 결정: 나아지는 것이 없으면 유지).
남는 이점은 설치 크기(paddle 스택 651MB → onnxruntime 수십 MB)와 OneDNN 회피 경로 제거뿐이라, 그것을
원하면 v1.4.0에서 v5 server 검출로 바꿀 수 있다.
(기준 L2가 바뀌어 위의 433/502와는 절대값이 다르다 — 같은 L2 안의 비교만 뜻이 있다.)
v6 계열은 축소 크기(64~1280)·후처리를 바꿔도 97줄 그대로였다 — 모델 세대 차이지 설정 차이가 아니다.

## B-007 자동 업데이트 (2026-09-06, 사용자 제안 → **같은 날 D-112로 구현**)

> 구현됨: `start_server`가 서버를 켜기 전에 받고, 앱을 열면 저절로 확인해 알린다. zip 설치는
> git 사본으로 바꿔 같은 길을 탄다. 아래는 제안 당시 기록.

지금은 설정 ▸ 「새 판 확인」 → 「받기」를 사람이 누른다(D-103, «저절로 받지 않는다»). 새 판이
잦고 다른 PC에서 매번 받게 하는 것이 부담이라, 켤 때 확인해서 알림을 띄우거나(옵트인) 조용히
받아 두고 다음 기동에 적용하는 선택지를 검토한다.

- 전제: 되돌릴 수 없는 판(서고 형식 변경)은 자동으로 받지 않는다 — 동의를 받는다.
- 함께 볼 것: B-004(exe)·Git 없는 업데이트 경로. 자동 적용은 그 경로가 있어야 zip 사용자도 받는다.
