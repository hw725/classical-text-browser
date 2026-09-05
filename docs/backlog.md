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
