# 백로그 — 합의된 추후 과제

릴리스에 묶이지 않은 개선 요청과 아직 고치지 않은 결함을 기록한다. 착수 시 DECISIONS에 설계 결정을 남기고,
닫으면 본문에서 지우고 맨 끝 «닫힌 항목» 표에 한 줄(번호·제목·근거)만 남긴다.

## B-001 세로쓰기 대조 교정 뷰 (2026-08-21, 운양 프로젝트 사용 경험에서)

원문 이미지와 텍스트를 나란히 놓고 **세로쓰기(vertical-rl) + 행별 하이라이팅**
상태에서 행 텍스트를 교체(교정)하고 이력이 남는 뷰. 현재 교정 UI는 가로쓰기 중심이라,
고서 대조 교감에는 외부 뷰어(운양 `viewer/index.html` + `17_viewer_server.py`)를 따로 썼다.

- 요구: ① 세로쓰기 텍스트 패널 ② 이미지 bbox ↔ 행 클릭 동기 하이라이팅
  ③ 행 단위 텍스트 교체 저장 ④ 수정 이력 누적(git 이력에 연결만)
- 참고 구현: 운양 뷰어의 층위 규약(text < text_corrected < text_human,
  append-only human_edits.jsonl)과 PDF.js 오버레이 방식
- 관련 우려: 속음청사급(18권 3,018쪽) 문헌을 감당하는지 1권 파일럿 실측 필요 — 적재·편집·git 커밋 응답속도

## B-003 저장 파일의 `block_id` → `unit_id` (2026-09-03, D-093에서 남김)

D-093이 이름을 `unit`으로 바꿨지만 **저장 파일이 단위를 가리키는 필드는 `block_id` 그대로**다.
표점·현토 파일 이름의 `_blk_` 조각도 마찬가지다.

- 왜 미뤘나: 필드·파일 이름이 바뀌면 이미 표점·번역을 한 서고에서 그 작업이 **조용히 안 보이게** 된다 —
  자동 테스트가 못 잡는 자리다.
- 함께 있어야 할 것: ① 쓰는 쪽을 `unit_id`로 ② 읽는 쪽은 한 판 동안 둘 다 받기
  ③ 옛 파일을 옮기는 스크립트(파일 이름의 `_blk_` 포함, 해석 저장소 커밋) ④ 다음 판에서 `block_id` 읽기 삭제.
- 대상 파일: `L5_reading/**`(표점·현토), `L6_translation/**`, `L7_annotation/**`,
  `citation_marks/**`, `core_entities/tags/*.json`. 스키마 넷(`schemas/interp/*_page.schema.json`)의
  `block_id` 설명 «예: p01_b01»도 이때 고친다.
- 지금 서고에는 이 파일이 0건이라 급하지 않다.

## B-005 PaddleOCR CPU 쪽당 50~75초 (2026-09-05 실측)

Windows + paddlepaddle 3.3.1 CPU에서 한 쪽(1376×1929, 33행) 인식이 server 검출 75초,
mobile 검출 52초, 스레드 20개로도 61초. OneDNN을 켜면 `ConvertPirAttribute2RuntimeAttribute not support`로
크래시(D-078 시절과 같음). GPU는 1초.

- 해 둔 것: 사용자 가이드 7-A.4에 실측치를 적고 여러 쪽이면 LLM Vision을 권함.
- 해 볼 것: paddlepaddle 3.4+에서 OneDNN 크래시가 풀렸는지, onnxruntime 경로(NDL 엔진, 7초/쪽)로 검출만 옮기기.
- 실측 스크립트: scratchpad `paddle_prof2.py` (server|mobile|mkldnn|threads).

## B-006 PaddleOCR 검출을 onnxruntime으로 (2026-09-06, 실측 조건부 → **미달, 보류**)

기본 번들의 PaddleOCR은 인식이 아니라 **글자 위치 검출**(형광 자리, D-055) 때문에 들어 있다.
대가는 설치 651MB, 첫 실행 모델 240MB(Baidu), Windows CPU의 OneDNN 크래시 회피 경로다.
같은 검출 모델을 onnxruntime으로 돌리면(예: rapidocr-onnxruntime) 이 셋이 사라진다.

- **조건**: 현동 이안중 연구 논문(15쪽)으로 교체 전후를 같은 잣대(`embed_text_layer`의 positioned/detected +
  D-068 잉크 검사)로 재서 **제자리 줄 수가 유지될 때만** 바꾼다.
- 바꾸면: paddlepaddle은 `--extra paddle`(선택)로, 기본은 onnxruntime + 검출 모델. install.ps1 5단계(모델 미리 받기) 불필요.

**실측 결과(2026-09-06) — 미달, 바꾸지 않았다.** 기준 L2는 ChatGPT 계정(OAuth) gpt-5.4-mini로 새로 만든 것.
같은 L2 위에 검출기만 바꿔 `embed_text_layer`를 돌렸다(스크립트 `C:\tmp\b006_compare.py`).

| 검출기 | 제자리 줄 | 검출 시간/쪽 | 전체 |
|---|---|---|---|
| PaddleOCR TextDetection(현재, PP-OCRv6 medium) | **142**/440 | 8.1s | 133s |
| rapidocr 3.x(onnxruntime) PP-OCRv6 small, 기본 설정 | 97/440 | 0.9s | 25s |
| rapidocr PP-OCRv6 medium, limit 736/min | 97/440 | — | 190s |
| rapidocr PP-OCRv6 medium, limit 1280/max | 97/440 | — | 186s |
| rapidocr PP-OCRv6 medium, limit 64/min | 97/440 | — | 181s |
| rapidocr PP-OCRv6 medium, box_thresh 0.6·unclip 1.5(Paddle 기본값) | 97/440 | — | 174s |
| rapidocr **PP-OCRv5 server**, 기본 설정 | **142**/440 | 약 10s | 158s |

잉크 경고는 전부 0건. v6 계열은 검출이 9배 빠르지만 142 → 97줄로 조건을 못 지켰고, 축소 크기·후처리를 바꿔도
97줄 그대로였다(모델 세대 차이). **PP-OCRv5 server는 142줄로 같지만** 쪽당 약 10초로 Paddle(8초)보다 느리다.
그래서 PaddleOCR 기본 번들 유지(2026-09-06 사용자 결정). 남는 이점은 설치 크기(651MB → 수십 MB)와
OneDNN 회피 경로 제거뿐이라, 원하면 v5 server 검출로 바꿀 수 있다.
(기준 L2가 바뀌어 처음 적은 433/502와 절대값이 다르다 — 같은 L2 안의 비교만 뜻이 있다.)

## B-011 Jev 본문 판정 임계를 책별로 재조정 (2026-09-27, D-129 적용 기록의 열린 질문)

본문 판정의 두 임계(accept 0.85 · reject 0.5, `structure_llm.JEV_ACCEPT_AT`·`JEV_REJECT_AT`)는
모든 책에 같은 고정값이다. 두 책 저장 측정에서 하한 0.5는 같이 들었지만 상한은 책을 탔다(천진담초는
escalate 정답 6건 중 5건이 0.8~0.85, 운양집은 50건이 0.5~0.85에 고루). 목차의 `derive_toc_threshold`처럼
**그 책에서 사람이 적용한 경계**로 재서 다음 권부터 옮겨 쓰자는 과제다. 책 둘뿐이라 신뢰도는 낮다.

> **2026-10-05 갱신(D-136).** 문턱은 **모델마다** 있다 — `structure_llm.JUDGE_THRESHOLDS`(`typesafe` 0.85/0.5,
> `openrouter` decider 0.95/0.35)와 `judge_thresholds(client)`(OpenRouter 경유 Jev는 Jev 문턱). 기본이 decider로
> 바뀌어 escalate가 Jev의 약 2배(천진담초 131행·운양집 1책 424행)다. «책별»에 더해 «모델별»로 재야 하고,
> 위 숫자는 Jev 기준이다. decider 하한 0.35는 운양집 정답 0.33·0.364에 걸려 여유가 얇다(D-136 3항).

막혀 있는 것 셋 (코드로 확인함):

- **판정 확률이 저장되지 않는다**(D-129 9항). 권별 곁파일로 남길지, 재조정 때 1권을 다시 부를지(권당 약 $0.024) 사용자가 정한다.
- **저장된 경계에 출처가 없다.** 「적용」의 `SegmentationSpan`에 reasons·prob·band가 없다. 정답 쪽으로는 쓸 수 있다.
- **체크되지 않은 escalate는 음성이 아니다.** 기본으로 숨겨져 사람이 안 봤을 수 있다 — 음성으로 세면 확신 구간이
  부풀려진다(체크 출처 `prevKeys`, D-129 «미리 체크의 예외»와 같은 뿌리). 최소안은 정답 쪽(재현·하한 아래 손실)만 쓴다.

하지 말 것: 규칙 후보와의 일치로 재기(D-129 1항), 책 종류 분류로 임계 고르기, 새 라우트·저장 자리.
인계 메모는 우산 저장소 head-repo `docs/handoff_ctb-jev-rethreshold.md`.

---

> 아래 B-012~B-030은 2026-10-11 전수 검토(코드 파일 대상)에서 찾은 결함이다. 행 번호는 2026-10-11 기준이고,
> 등재할 때 코드를 열어 한 번씩 다시 확인했다. 확인하지 못한 부분은 «(미확인)»으로 적는다.

## B-036 2026-10-11 전수에서 남긴 작은 것 (고치지 않음 — 이유 함께)

- `ocr-panel.js` 권 전체 OCR의 `writing_direction: "vertical_rtl"` 고정 — 계획 없는 가로쓰기 책에서 전면 블록이
  세로로 잡히는지는 실물로 재지 않았다(미확인). 계획이 있으면 구간별 방향을 쓴다(D-131).
- `generic_llm` 매퍼 — LLM이 classification에 중첩 객체를, creator에 모르는 키를 넣으면 서지 저장 검증이 거부한다(미확인,
  실제 답으로 재지 않음). 지금은 저장 단계의 스키마 검증이 막는다(조용히 깨진 서지가 남지는 않는다).
- `asset_detector` 장식 이미지 패턴이 부분 문자열 일치라 lexicon·bg·nav가 든 콘텐츠 파일명도 빠질 수 있다 — 실사용 빈도 모름.
- `text_separator`가 자체 JSON 파서를 쓴다(JSON 강제는 2026-10-11에 더했다). 잘린 답 복구는 없다.
- KORCIS `title_reading`은 검색 결과에서만 온다 — URL·상세 조회 길에서는 비어 있다(출처 표기에 밝혔다).
- `annotation_llm`·`punctuation_llm`·`translation_llm`의 `generate_*` — 앱이 부르지 않는 옛 경로. 시험이 내부 도우미를
  재고 있어 지우면 시험 수가 줄어 계약 C-001에 걸린다. 머리말에 «쓰이지 않는다»를 밝혔다. 지우려면 시험부터 옮긴다.
- `test_connectome.py`의 토큰 누출 시험은 neuprint가 없는 환경에서 패키지 사유만 돌려받아 토큰 경로를 재지 못한다(환경 의존).

## 닫힌 항목

| 번호 | 제목 | 닫은 근거 |
|---|---|---|
| B-004 | Windows 설치 파일(exe) | D-113, `c01b322` |
| B-007 | 자동 업데이트 | D-112, `ed37f01` |
| B-008 | 해석 패널이 어느 모드에서도 열리지 않는다 | `46190ee`(의존 경고·스냅샷 내보내기 이사), `f95399e`(옛 통합 편집기 철거·손 경계 500 고침) |
| B-009 | 화면 JS 전역 함수 이름 겹침 여섯 | `b92711b`(_render* 셋), `f26c799`(이스케이프 셋, `KNOWN` 비움) |
| B-010 | D-128 8항 승격 무게에 남은 구멍 셋 | `0548aa2`; `tests/test_codex_review.py` 8건 통과(2026-10-11 실행) |
| B-012 | 엔티티 «현재 페이지만»에서 단위가 안 보임 | 응답 키 `units`(2026-10-11) — 회귀 시험 `tests/test_sweep_20261011.py` |
| B-013 | 스냅샷 왕복이 경계·작업 계획·승인·사전·주석 유형을 잃음 | 교환 스키마에 원본 층 셋, 사전은 서고 `resources/`에서 읽고 들일 때 합침(2026-10-11) — 같은 시험 |
| B-014 | 들인 manifest의 «imported»가 스키마 위반 | manifest enum에 `imported`(2026-10-11) — 같은 시험 |
| B-015 | honkoku L2의 koji 칸이 스키마 위반 | OcrLine에 `koji`(2026-10-11), `test_ocr_honkoku.py`가 출력을 스키마로 검증 |
| B-016 | 인용 편집기 코드포인트·권 구분 | 글자 배열로 셈·모든 호출에 `part_id`·없는 상수 참조 제거(2026-10-11) — 같은 시험 |
| B-017 | 원문 내보내기에 교정이 안 들어감 | `get_corrected_text`로(2026-10-11) — 같은 시험 |
| B-018 | 참조 사전 «적용»이 효과 없음·일괄 번역 실패 집계 | `reference_context` 전송·서버가 «참고만»으로 실음, 단일 번역이 참·거짓을 돌려줌(2026-10-11) — 같은 시험 |
| B-019 | 권 전체 OCR이 고른 모델을 무시 | `ocr-llm-model-select`를 읽음(2026-10-11) — 같은 시험. 가로쓰기 고정 방향은 B-036 |
| B-020 | LLM 교정이 앱 폴더 사전을 읽음 | 서고 활성 사전(`library_active_dict_path`)(2026-10-11) — 같은 시험 |
| B-021 | L6·들인 L4가 CRLF | `newline=""`(2026-10-11) — 같은 시험 |
| B-022 | 주석 라우터의 없는 L4·메타 경로, 삭제 커밋 없음 | 원본 문헌 L4·manifest에서 읽고 단위로 블록 목록, 삭제도 커밋(2026-10-11) — 같은 시험 |
| B-023 | 스냅샷 검증기의 거짓 «L3에 없음» | 단위(경계) id도 아는 id로(2026-10-11) — 같은 시험 |
| B-024 | 저장소 id 정규식 두 곳 | `core.repo_id` import(2026-10-11) — 같은 시험 |
| B-025 | 시작 행 ▲▼가 해석 저장소 없이 무시됨 | 조건 제거(2026-10-11) — 같은 시험 |
| B-026 | 이체자 사전 활성화에 닿을 길 없음 | 「활성으로」 단추(2026-10-11) — 같은 시험 |
| B-027 | PaddleOCR 안내의 설치 명령이 반대 | `doctor.bat` 안내로(2026-10-11) |
| B-028 | OCR 라우트의 doc_id 미검증 | 모두 `require_repo_path`(2026-10-11) — 같은 시험 |
| B-029 | 이스케이프 빠진 화면 자리 | 고침 + 정의 안 된 CSS 변수 0(2026-10-11) — 같은 시험 |
| B-030 | 낡은 머리말·죽은 경로 | 파일마다 고침, 죽은 코드(대조 뷰 사전 대화창·`_commitBatch`·`_fillFromOcr`·`auto_create_units_from_text`·옛 이름 장치) 제거(2026-10-11). 남긴 것은 B-036 |
| B-031 | KORCIS 판식·소장처가 늘 빔 | `fetch_detail`이 OpenAPI 상세를 싣고 `note_info`까지 판식으로 읽음(2026-10-11) — 같은 시험, `test_korcis.py` URL 시험이 실제 함수를 부름 |
| B-032 | 외부 텍스트 쪽 경계가 앞당겨짐 | 앵커의 쪽 안 자리로 쪽 시작을 추정(2026-10-11) — 같은 시험, `test_text_import_align.py`가 쪽 원문과 대조 |
| B-033 | 장서각·KOSTMA·규장각 서지가 스키마에 막힘 | subject 목록·classification 객체(2026-10-11) — 같은 시험 |
| B-034 | 이미지 묶음 쪽 순서 p1,p10,p2 | 자연 정렬(2026-10-11) — 같은 시험 |
| B-035 | 시험이 재지 못하는 자리 | 외부 연결 차단(`tests/conftest.py`, 표지 `network`)·NDL 시험 slow·편성 «말로 넣기» 시험 가짜 라우터·각 시험 단언 강화(2026-10-11). 남은 것은 B-036 |
