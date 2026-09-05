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

## B-004 Windows 설치 파일(exe) (2026-09-05, v1.4.0으로 미룸)

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

## B-007 자동 업데이트 (2026-09-06, 사용자 제안)

지금은 설정 ▸ 「새 판 확인」 → 「받기」를 사람이 누른다(D-103, «저절로 받지 않는다»). 새 판이
잦고 다른 PC에서 매번 받게 하는 것이 부담이라, 켤 때 확인해서 알림을 띄우거나(옵트인) 조용히
받아 두고 다음 기동에 적용하는 선택지를 검토한다.

- 전제: 되돌릴 수 없는 판(서고 형식 변경)은 자동으로 받지 않는다 — 동의를 받는다.
- 함께 볼 것: B-004(exe)·Git 없는 업데이트 경로. 자동 적용은 그 경로가 있어야 zip 사용자도 받는다.
