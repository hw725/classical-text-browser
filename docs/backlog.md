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

## B-008 해석 패널이 어느 모드에서도 열리지 않는다 (2026-09-22 실측)

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

**남은 것은 철거다.** `#interp-panel` 과 그 안의 D-096 이전 통합 편집기(「해석 (L5~L7)」
+ 층별 서브탭), 그리고 `activateInterpretationMode`·`deactivateInterpretationMode`·
`interpState.active`·`_updateToolbarButtons` 의 죽은 조건과 「단위 만들기」·
「LLM에게 요청」·공용 「저장」.

- 옛 통합 편집기와 죽은 조건은 **지금 걷어내도 된다.** 「LLM에게 요청」은 그 편집기에
  딸린 것이고, 공용 「저장」도 그 패널의 것이다.
- **「단위 만들기」만 따로 판단한다.** 이것은 죽은 v1.2 잔재가 **아니다** — 누르면
  `entities/unit/from-source` → `create_entity("unit")` → `entity.py:607` 이
  `_create_boundary_from_unit` 으로 보내 원본 저장소의 `boundaries/{part}.json` 에
  **경계를 쓴다**(D-092·D-097). 하는 일은 지금 규약대로다.

  **그런데 폼이 v1.2 모양이다**(`entity-manager.js::_openUnitCreator`). 묻는 것이
  원본 문헌(읽기 전용)·**쪽**·LayoutBlock ID·원문 텍스트·`sequence_index` 인데,
  경계는 (쪽, **행**)·깊이·제목·앵커 글자다 — **행을 묻지 않는다.** 그리고 사람에게
  「L4 텍스트에서 블록에 해당하는 부분을 붙여넣으세요」라고 한다.

  편성에는 같은 일을 더 잘하는 길이 이미 둘 있다 — 「여기서 시작」(D-122 덧붙임,
  행 단위이고 붙여넣기가 없다)과 `position_at_point`(D-094, 이미지에서 찍은 점을
  (행·글자)로). 폼을 그대로 옮기면 **경계를 만드는 길이 둘이 되는데 그중 하나는
  행을 못 고르고**, 「저장 자리는 «적용» 하나」라는 D-122 와도 어긋난다(이 단추는
  누르는 즉시 쓴다).

  그래서 **진짜 물음은 「어디에 둘까」가 아니라 「편성 밖에서 손으로 경계를 만드는
  길이 따로 필요한가」**다.
    - 필요 없다 → 폼과 단추를 걷고 `from-source` 라우트는 남긴다(API 로는 쓸 데가 있다).
    - 필요하다 → 폼을 **경계 모양**으로 새로 짠다(쪽·**행**을 고르고 텍스트는 코드가
      L4 에서 가져온다). 자리는 편성 탭 ③ 옆 — 내용 트리는 **읽는 곳**이지 만드는
      곳이 아니다(D-096 에서 트리가 받은 역할은 «지금 단위»를 정하는 것뿐이다).
- 철거하면 `test_ui_reachability.py::test_the_dead_panel_is_still_dead` 가 빨간불이
  난다. **그것이 신호다** — 그때 이 항목을 다시 읽고 닫는다.
- 함께 볼 것: `activateInterpretationMode`·`deactivateInterpretationMode`·`_acknowledgeChanges`·
  `_updateBase`(interpretation.js), `_updateToolbarButtons`(entity-manager.js),
  `workspace.js:1842`(스냅샷 export 배선), contents-tree.js 38행의 「네 자리」 주석.
- 같이 나온 것(같은 실측): `entity.py:153 _get_source_head_commit`이 `interpretation.py:232`와
  **본문이 같은 중복 정의**이고 시험에서 안 돈다(Phase 8부터) · `entity.auto_create_units_from_text`는
  부르는 곳이 없다 · `entity.create_unit_from_source`는 라우트(`interpretations.py:676`)가
  부르는데 시험이 한 번도 안 들어간다. 셋 다 D-128과 무관하다.

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
