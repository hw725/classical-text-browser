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
> `openrouter` decider)와 `judge_thresholds(client)`(OpenRouter 경유 Jev는 Jev 문턱). «책별»에 더해 «모델별»로
> 재야 하고, 위 숫자는 Jev 기준이다.
>
> **2026-10-11 갱신(D-139).** 주 판정자는 다시 Jev이고 decider는 v1.1로 바뀌어 Jev가 실패한 호출만 답한다.
> decider v1.1 문턱은 0.997/0.69이고 0.997은 경계값이다(0.996이면 천진담초 정밀이 Jev 아래). 그래서 이 과제의
> 주 대상은 다시 Jev 문턱이다.

막혀 있는 것 셋 (코드로 확인함):

- **판정 확률이 저장되지 않는다**(D-129 9항). 권별 곁파일로 남길지, 재조정 때 1권을 다시 부를지(권당 약 $0.024) 사용자가 정한다.
- **저장된 경계에 출처가 없다.** 「적용」의 `SegmentationSpan`에 reasons·prob·band가 없다. 정답 쪽으로는 쓸 수 있다.
- **체크되지 않은 escalate는 음성이 아니다.** 기본으로 숨겨져 사람이 안 봤을 수 있다 — 음성으로 세면 확신 구간이
  부풀려진다(체크 출처 `prevKeys`, D-129 «미리 체크의 예외»와 같은 뿌리). 최소안은 정답 쪽(재현·하한 아래 손실)만 쓴다.

하지 말 것: 규칙 후보와의 일치로 재기(D-129 1항), 책 종류 분류로 임계 고르기, 새 라우트·저장 자리.
인계 메모는 우산 저장소 head-repo `docs/handoff_ctb-jev-rethreshold.md`.

---

> 아래 B-036은 2026-10-11 전수 검토(코드 파일 대상)에서 남긴 작은 것이다(그날 고친 결함은 맨 아래 «닫힌 항목»,
> 그날 찾아 열어 둔 B-040은 바로 아래에 있다). 행 번호는 2026-10-11 기준이고,
> 등재할 때 코드를 열어 한 번씩 다시 확인했다. 확인하지 못한 부분은 «(미확인)»으로 적는다.

## B-040 승격 출처 수집이 문헌 하나 범위다 — D-128 9항 «넓게 모은다»가 실현되지 않음 (2026-10-11 전수)

`promotion.gather_sources`는 document_id로 거르지 않지만 받는 것이 해석 저장소 하나(`interp_path`)이고 해석 저장소는
문헌 하나를 보므로, 실제로 모이는 출처는 그 문헌의 것뿐이다. 서고의 여러 해석 저장소를 훑는 수집은 없다. 설명은
사실대로 고쳤다(promotion.py·concept_scope.py·interpretations.py). 넓게 모으게 바꾸면 승격 판정이 달라지는 설계
변경이라 따로 정한다 — 무엇을 «같은 개념»으로 볼지(표면형만인가, 문헌별 scope는 어떻게 하나)가 먼저다.

## B-036 2026-10-11 전수에서 남긴 작은 것 (고치지 않음 — 이유 함께)

- `generic_llm` 매퍼 — LLM이 classification에 중첩 객체를, creator에 모르는 키를 넣으면 서지 저장 검증이 거부한다(미확인,
  실제 답으로 재지 않음). 지금은 저장 단계의 스키마 검증이 막는다(조용히 깨진 서지가 남지는 않는다).
- `asset_detector` 장식 이미지 패턴이 부분 문자열 일치라 lexicon·bg·nav가 든 콘텐츠 파일명도 빠질 수 있다 — 실사용 빈도 모름.
- `text_separator`가 자체 JSON 파서를 쓴다(JSON 강제는 2026-10-11에 더했다). 잘린 답 복구는 없다.
- KORCIS `title_reading`은 검색 결과에서만 온다 — URL·상세 조회 길에서는 비어 있다(출처 표기에 밝혔다).
- `annotation_llm`·`punctuation_llm`·`translation_llm`의 `generate_*` — 앱이 부르지 않는 옛 경로. 시험이 내부 도우미를
  재고 있어 지우면 시험 수가 줄어 계약 C-001에 걸린다. 머리말에 «쓰이지 않는다»를 밝혔다. 지우려면 시험부터 옮긴다.
- `test_connectome.py`의 토큰 누출 시험은 neuprint가 없는 환경에서 패키지 사유만 돌려받아 토큰 경로를 재지 못한다(환경 의존).
- `ocr-panel.js`의 선택 상태 300ms 폴링 — 설계 선택(이벤트를 잇는 대신 짧게 묻기). 동작 결함이 아니라 남긴다.
- 화면 JS 여러 호출부의 `cache: "no-store"` — D-066 미들웨어로 필요 없지만 해가 없다. 지우는 이득이 적어 남긴다.
- 계약 C-001(`.venv` 파이썬 직접)과 C-002(`uv run`)의 실행 방식 차이, C-002 `fail_regex`의 «assert » — 계약을 바꾸면
  재승인이 필요하고 지금 동작에 문제가 없어 남긴다.
- `tests/test_embed_folder_resume.py`가 «L2가 있으면 이어 한다»만 재고 L3 대조(D-057 두 조건)는 재지 않는다 —
  폴더 배치 OCR은 늘 쪽 전면 블록을 만들어 L3가 바뀌지 않으므로 실제 위험은 없다.
- `tests/test_lite_mode_api.py`의 «건너뛴다» 시험 셋은 `engine_id="llm_vision"`을 그대로 쓴다 — 퇴행하면 처리 0·호출 0
  단언이 깨지고, conftest가 Ollama 포트·바깥 연결을 막아 실제 호출은 나가지 않는다. «LLM 호출 0회»를 그 엔진으로
  재는 것이 시험의 뜻이라 더미로 바꾸지 않았다.

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
| B-019 | 권 전체 OCR이 고른 모델을 무시 | `ocr-llm-model-select`를 읽음(2026-10-11) — 같은 시험. 가로쓰기 고정 방향은 B-061에서 고침 |
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
| B-037 | 스냅샷 가져오기가 `../`로 서고 밖에 쓸 수 있음(2차 전수 S-20261011-185238) | `core.snapshot.unsafe_snapshot_paths` — 문헌·해석 id·L3 part·L4 file_name·경계 part·작업 계획 권·`_source_path`·엔티티 종류·id를 검증이 422로 막고, 들이기 함수가 한 번 더 막고 쓰는 자리마다 서고 안인지 본다. 긴 원래 id가 새 id 64자를 넘던 것도 자름(2026-10-11) — `test_snapshot_paths_that_escape_the_library_are_refused` 등 |
| B-038 | 폴더 배치 OCR이 중단 뒤 이어 하지 못함(같은 편이 다른 id) | 문헌 id를 원본 경로의 해시로(`embed_folder._safe_doc_id(path)` — 크기·수정 시각은 B-063에서 더함), 작업 공간 정리가 `startswith(doc_id)`로 다른 편의 해석 저장소까지 지우던 것도 고침(2026-10-11) — `test_embed_folder_doc_id_is_stable_per_file` |
| B-039 | PaddleOCR 워커에 시간 제한 없음(엔진 목록 무한 대기) | `_worker_call`이 timeout을 실제로 지키고, 넘으면 그 워커를 끄고 실패로 돌려줌(2026-10-11) — `test_paddle_worker_call_honours_its_timeout` |
| B-041 | 화면 JS 이스케이프 함수가 따옴표를 막지 않음(속성 자리 다섯 곳) | 이스케이프 함수 15개+toast가 큰·작은따옴표를 모두 막게(종류 전체), 시험은 함수를 자동으로 찾아 node로 실행. `test_ui_reachability`의 «textContent면 엄격» 전제 제거, bibliography 파서 id 이스케이프(2026-10-11) — `test_every_escape_helper_blocks_both_quotes` |
| B-042 | 현토·번역·교정·표점 편집기와 경계 찍기가 글자 좌표를 UTF-16으로 셈(확장 한자 뒤 한 칸 어긋남) | 편집기마다 코드포인트 도우미(`_htChars`·`_trChars`·`_corrChars`·`_puChars`), 교정 char_index도 서버와 같은 자. 표점 글자·표점·mark id 이스케이프(2026-10-11) — `test_*_counts_code_points` |
| B-043 | Tag·Agent 편집이 metadata를 null로 덮음 | 편집 전 metadata를 실어 보냄(2026-10-11) — `test_entity_edit_keeps_metadata` |
| B-044 | 비고 2초 저장이 쪽을 옮긴 뒤 새 쪽 파일을 덮음 | 예약할 때 자리를 붙잡고 쪽을 불러오기 전에 먼저 내보냄(2026-10-11) — `test_notes_pending_save_goes_to_the_page_it_was_written_on` |
| B-045 | 새로 그린 레이아웃 블록 id가 남은 블록과 겹침 | 남은 `bNN` 최댓값+1(2026-10-11) — `test_new_layout_block_id_never_repeats_a_remaining_one` |
| B-046 | 사전 필드 저장이 출전의 section·url과 폼에 없는 칸을 지움 | 편집 전 사전 위에 덮고 출전은 제목으로 짝지어 살림(2026-10-11) — `test_dictionary_save_keeps_source_section_and_url` |
| B-047 | 인용 «원문 변경» 경고가 영영 안 보임·불확정 진행 막대가 멈춰 보임 | CSS의 display:none 제거, `@keyframes progress-pulse` 정의(2026-10-11) — `test_elements_shown_with_empty_display_are_not_hidden_by_the_stylesheet`·`test_every_used_animation_has_keyframes` |
| B-048 | Ctrl+S가 숨은 텍스트 편집기의 옛 글로 확정본을 덮음 | 보이고 수정된 때만 저장(2026-10-11) — `test_ctrl_s_saves_text_only_when_this_editor_is_shown_and_dirty` |
| B-049 | 백업 폴더로 고른 폴더를 통째로 옮기고 두 번째 백업에서 지움(**데이터 손실**) | 다른 파일이 든 폴더면 하위 폴더에, 이 앱이 만든 백업(`_backup_meta.json`)만 교체(2026-10-11) — `test_backup_never_moves_or_deletes_a_folder_it_did_not_make` |
| B-050 | `.env`를 못 읽으면 관리 키 저장이 다른 줄을 지움(**데이터 손실**) | cp949로 한 번 더 읽고, 그래도 못 읽으면 쓰지 않음(2026-10-11) — `test_env_write_keeps_other_lines_of_a_cp949_file` |
| B-051 | 휴지통 옮기기가 잠금 때 완전한 사본을 지우고 원본 조각만 옮김(**데이터 손실**)·매니페스트 중복 | `os.rename`만(복원도), 휴지통으로 보내면 매니페스트에서 빼고 등록은 같은 id를 바꿔 끼움(2026-10-11) — `test_trash_move_never_falls_back_to_copy_and_delete`·`test_manifest_has_one_entry_per_id_after_trash_and_recreate` |
| B-052 | zip 사본의 자동 업데이트가 사용자가 고친 파일을 덮음 | 바꿀 때 파일 지문을 적고 받기 전에 대조, 콘솔 고정은 진입점에서만(2026-10-11) — `test_zip_copy_does_not_overwrite_files_edited_after_conversion` |
| B-053 | HWP 대두 위치가 늘 0·첫 글자 앞 표점 구별 없음·거짓 설명 | 대두 pos를 실제 글자 자리로, 선행 표점에 `position: before`, 머리말·docstring 바로잡음(2026-10-11) — `test_hwp_taidu_pos_points_at_the_raised_character` |
| B-054 | 빠른 시험이 로컬 Ollama·OAuth 프록시를 거쳐 바깥에 닿음 | conftest가 그 포트를 로컬이어도 막음, llm_vision 강제 시험은 더미 엔진(2026-10-11) — `test_local_daemons_that_relay_outside_are_blocked_too` |
| B-055 | 화면 라이브러리를 CDN에서 불러 오프라인 첫 실행에서 PDF가 안 뜸(추정) | `static/vendor/`에 싣고 MIME을 못박음(D-140) — `test_screen_libraries_are_served_locally_with_browser_mime_types` |
| B-056 | 라벨에 날것 `\u201c` 표시·리셋 단추 «이 쪽»(권 전체) | 글자로 넣고 «이 권»으로(2026-10-11) — `test_index_html_has_no_literal_unicode_escapes` |
| B-057 | 자유 편집의 «교정 모두 삭제»가 비우지 못하고 실패를 알리지 않음·`layout_correction` 라벨 없음 | 원문을 보내고 저장 성공 여부를 돌려줌, 여섯째 유형 라벨·색(2026-10-11) — `test_reset_corrections_in_free_edit_really_empties_and_reports_failure` |
| B-058 | 서지 수동 편집에서 칸을 비워도 지워지지 않음 | 칸이 있으면 빈 값은 null(2026-10-11) — `test_bibliography_manual_edit_can_clear_a_field` |
| B-059 | 스트리밍 LLM 호출이 실패하면 같은 호출을 폴백 URL로 다시 보냄(유료면 비용 두 번)·서버 오류 문구를 삼킴 | 스트림이 열리기 전 실패에만 폴백(2026-10-11) — `test_fetch_with_sse_falls_back_only_before_the_stream_opens` |
| B-060 | 해석 저장소가 없으면 «default»라는 없는 저장소로 요청(주석·인용 20곳) | 요청하지 않고 동작이면 까닭을 알림(2026-10-11) — `test_no_request_to_a_default_interpretation_when_none_is_chosen` |
| B-061 | 쪽 OCR 도중 쪽을 옮기면 옛 쪽 결과를 지금 쪽에 그림·권 전체 OCR 방향 세로 고정 | 늦은 결과는 그리지 않음, 방향은 프로필을 따름(2026-10-11) — `test_page_ocr_result_is_not_drawn_on_another_page`·`test_part_ocr_direction_follows_the_profile` |
| B-062 | 레이아웃 리셋 실패 알림이 닿지 않음·자동 감지가 기존 블록을 묻지 않고 덮음 | `_saveLayout`이 성공 여부를 돌려줌, 덮기 전에 확인(2026-10-11) — `test_layout_reset_reports_a_failed_save` |
| B-063 | 스냅샷의 id 없는 엔티티가 서로 덮음·폴더 배치 id가 같은 경로의 다른 스캔에 옛 OCR을 이어 씀 | 새 UUID·경고, id에 크기·수정 시각(2026-10-11) — `test_snapshot_entities_without_id_do_not_overwrite_each_other`·`test_embed_folder_doc_id_is_stable_per_file` |
| B-064 | 판정 미리 보기 비용에 폴백 몫이 없음 | 폴백이 모두 떠맡을 때의 최대를 따로(2026-10-11) — `test_dry_run_names_the_judge` |
| B-065 | 시험 기반의 구멍 — 배포 zip에서 수집 오류(test_doc_drift)·픽스처가 전역 서고 경로를 되돌리지 않음·아무것도 안 재는 갈래·뒤로 가기가 문헌 정보를 갱신 안 함 | git 없을 때 폴더를 훑음, conftest가 경로 복원, 전제 단언, popstate는 해시 복원 길로(2026-10-11) |
| B-066 | 설명이 주인 함수에서 떨어짐(원래 다섯 + 새로 넣은 도우미 다섯)·오류 문구 무이스케이프·낡은 서술(라우터 «무료», features 이름, 그림 파서 목록, 로드맵 import 경로) | 제자리로 옮기고 고침(2026-10-11) — `test_no_docstring_is_separated_from_its_function` |
| B-067 | 보충 재확인(바뀐 80파일): 찍기 미리보기 ReferenceError(교정본이 빈 글일 때)·하위 폴더 백업을 «마지막 백업»이 못 읽음·엔티티·인용·비고만 있는 해석 저장소를 «비었다»로 휴지통에 보냄 | `correctionState.pageText`로, `get_backup_info(경로, 서고 이름)`, 빈 판정에 `core_entities`·`citation_marks`·`_notes`(2026-10-11) — `test_pick_from_correction_char_without_corrected_text`·`test_backup_info_finds_the_subfolder_backup`·`test_interpretation_with_entities_or_citations_is_not_empty` |
| B-068 | 휴지통 되돌리기가 한 번만 해 보고 500·매니페스트에 다시 안 적음, 잠금 실패가 500이고 안내가 두 번 감싸짐, 화면에 없는 «설정 → 휴지통» 안내 | 보내기와 같은 재시도(`_rename_with_retry`)·`_readd_to_manifest`, 409로 안내 그대로, `.trash` 손 복원 안내(2026-10-11) — `test_trash_restore_retries_and_puts_the_item_back_in_the_manifest`·`test_trash_routes_report_a_locked_folder_as_409_once` |
| B-069 | 교정 리셋 저장 실패 때 상태만 비고 화면은 옛 교정, 쪼개기·단위 삭제가 207(일부 실패)을 «완료»로, 주석 유형 이름·아이콘·색 무이스케이프 | 실패하면 되돌림, 207이면 오류 알림·«새 경계 N개», `_escHtml`·`_escAttr`(2026-10-11) — `test_correction_reset_rolls_back_when_the_save_fails`·`test_split_and_delete_report_partial_failure`·`test_annotation_card_type_is_escaped` |
| B-070 | PDF를 한 번 못 열면 캔버스 DOM이 지워져 다른 문헌 PDF도 안 그려짐, 비고 저장 중 다음 저장이 조용히 사라짐 | 안내를 따로 얹고 캔버스는 숨김(`_showPdfLoadFailed`), 앞 저장을 기다렸다가 저장(2026-10-11) — `test_pdf_load_failure_keeps_the_canvas`·`test_notes_save_waits_for_the_running_save` |
| B-071 | 화면 문구·입력칸이 동작과 다름 — URL 모드는 ID를 비울 수 없었음, 일괄 교정 칸 maxlength=1(확장 한자 못 넣음), 위 바 쪽 번호가 ◀▶에서 안 바뀜, 해시 복원이 문헌 프로필을 안 따름, «JSON 내보내기» 단추 글자 | 미리보기 후보 id, 코드포인트 검사, `onPageChanged`·`_restoreFromHash` 보강(2026-10-11) — `test_screen_text_matches_behaviour` |
| B-072 | 지문 없는 옛 zip 표시면 고친 파일을 «고친 것 없음»으로 읽고 덮음, 쓸 수 없는 ChatGPT 계정을 «무료»로, Ollama 사고 재호출이 문맥 창을 안 늘림 | 덮기 전에 설정 폴더 `update-backup/`에 남김(`_keep_zip_files`), «구독», `_gen_options` 재계산(2026-10-11) — `test_zip_copy_with_an_old_mark_keeps_differing_files`·`test_llm_cost_and_ollama_retry_window` |
| B-073 | 서지 판식 값 무이스케이프·원본 주소에 `javascript:` 링크 가능 | 판식 이스케이프·`<br>`, http(s)만 링크(2026-10-11) — `test_bibliography_source_link_is_http_only` |
| B-074 | 서버 엔진 자동 감지가 묻지 않고 블록을 덮음·0건이면 기존 블록을 지움·감지 중 쪽을 옮기면 옛 쪽 블록을 새 쪽에 저장, LLM 교정 초안이 다른 쪽에 그려짐 | 덮기 전에 묻고(`_confirmReplaceBlocks`), 쪽이 바뀌면 버림(`_layoutStillOn`), 저장 실패를 알림(2026-10-11) — `test_server_autodetect_asks_and_ignores_a_moved_page`·`test_llm_correction_draft_is_not_drawn_on_another_page` |
| B-075 | AI 번역 저장 실패도 성공으로 셈, 해석 층 dict JSON 저장이 UnboundLocalError(라우트 400·git 커밋 건너뜀), id가 빈 스냅샷 엔티티가 422 | false를 돌려줌, 쓴 파일에서 크기, 빈 id는 새 UUID(2026-10-11) — `test_ai_translation_reports_a_failed_save`·`test_dict_layer_json_save_returns_its_size`·`test_snapshot_entity_with_empty_id_gets_a_new_id_instead_of_422` |
| B-076 | `.env` cp949 판독이 라틴 8비트 파일도 받음·LLM 설정과 설정 화면이 같은 `.env`를 다르게 읽음, 지역 이스케이프의 작은따옴표, 쪽 수만 세는 PDF 열기가 통째로 받음, 레이아웃 교정 배지 배경·토스트 줄바꿈, 화면 미리보기의 UTF-16 자르기 | 한글일 때만 cp949·같은 판독, 따옴표·옵션·CSS·`Array.from`(2026-10-11) — `test_env_reader_refuses_non_korean_8bit_and_llm_config_reads_cp949`·`test_small_ui_fixes_are_in_place`·`test_display_previews_cut_by_code_points` |
| B-077 | 낡은 서술 일괄(보충 재확인) — D-139 뒤 «Jev 폴백·decider 주» 잔재, 스트리밍 폴백, CDN·오프라인 범위, 이스케이프 주석의 옛 이름, D-023·D-028·D-102·D-112·D-134 «일부 바뀜», B-005 오인용, D-055·D-128 번호, platform-v7 예시(교환 스키마 오류 10건 → 0)·저장소 트리, 그림 4의 LLM 소비자, 표점 프리셋 이름(쌍반점·쌍점) 등 | 문서·주석을 지금 동작대로(2026-10-11) — `test_no_docstring_is_separated_from_its_function`(설명 위치)·`check_doc_drift` |
| B-078 | 릴리스 리뷰(Codex, 2026-10-11): zip에서 바꾼 뒤 사용자가 만든 파일을 새 판이 추적하면 `reset --hard`가 묻지 않고 덮음(**데이터 손실**)·옛 zip 표시 백업이 `git add`한 수정과 한글 경로를 빠뜨림, 늦게 온 옛 쪽 비고를 지금 쪽에 그림(고치면 지금 쪽 파일에 저장), 같은 책 다른 대목 출전이 사전 저장 때 마지막 대목으로 바뀜 | `reset --hard` 두 자리 앞에서 겹치는 추적 밖 파일을 `update-backup/`에(`_keep_untracked_collisions`), `git diff HEAD -z`, `_notesStillOn`, 제목마다 옛 출전을 순서대로. 재검토 반영: 폴더·조상 파일 모양도 남김, git 조회 실패면 reset 없이 멈춤, 같은 초 백업은 새 폴더(2026-10-11, 사본에서 고침 여덟 자리를 하나씩 되돌려 모두 빨개짐을 확인) — `test_reset_hard_keeps_user_files_the_new_version_starts_tracking`·`test_old_zip_mark_backup_includes_staged_and_korean_paths`·`test_late_notes_response_is_not_drawn_on_another_page`·`test_dictionary_save_keeps_every_section_of_the_same_book`·`test_collision_backup_covers_folder_and_ancestor_shapes`·`test_collision_lookup_runs_before_each_reset_and_failure_stops_it`·`test_update_backups_in_the_same_second_do_not_overwrite_each_other` |
