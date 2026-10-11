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

## B-012 엔티티 패널 «현재 페이지만»에서 단위가 하나도 안 보인다 (2026-10-11)

- 틀린 곳: `src/core/entity.py:916` `list_entities_for_page`가 단위를 `"blocks"` 키로 돌려주고(1003행),
  라우트(`routers/interpretations.py:486`)가 그대로 넘긴다. 화면 `entity-manager.js:262`의 `typeMap`은 `unit → "units"`에서 찾는다.
- 보이는 것: «현재 페이지만»은 기본 켬(`entity-manager.js:19`)이라, 엔티티 패널을 열면 단위가 목록에 없다. 체크를 끄면(전체 조회) 나온다.
- 확인: 단위가 있는 쪽에서 패널을 열고 «단위» 거르기 → 0건, 체크 해제 → N건. 한쪽 키 이름을 맞추면 된다.

## B-013 스냅샷 왕복이 편성 경계·작업 계획을 잃는다 (2026-10-11)

- 틀린 곳: `src/core/snapshot.py:200` `_serialize_original`은 L1 참조·L3·L4만 담는다. 원본 저장소의
  `documents/{doc}/boundaries/`(D-097 뒤 글 단위의 정본)·`read_plan/`·`variant_approvals.json`·`L2_ocr/`가 빠지고,
  해석 쪽 `core_entities/boundaries`는 `RETIRED_ENTITY_DIRS`(271행)로 버린다. `exchange.schema.json`에도 경계 칸이 없다.
- 같은 파일: `_serialize_variant_chars`(352)는 서고 루트 `variant_chars.json`을 읽는데 D-104 뒤 사전은 서고 `resources/`에 산다;
  `_serialize_annotation_types`(366)는 `annotation_types_custom.json`을 읽는데 `core/annotation_types.py:43`은 `{서고}/annotation_types.json`에 쓴다.
- 보이는 것: 내보냈다 들이면 편성 경계·작업 계획·문헌별 이체자 승인이 사라지고, 사용자 이체자 사전·주석 유형이 내보내기에 안 실린다. 예외 없음.
- 확인: 경계가 있는 문헌을 내보내기 → 새 서고로 들이기 → 「내용」 트리 단위 0개.

## B-014 들인 문헌의 manifest가 스키마 위반 — 회전 저장 등이 막힌다 (2026-10-11)

- 틀린 곳: `src/core/snapshot.py:471`이 `completeness_status: "imported"`를 쓰는데
  `schemas/source_repo/manifest.schema.json:75` enum(file_only … finalized)에 없다.
- 보이는 것: manifest를 검증하고 저장하는 길(`core/document.py:464` `set_part_rotation` 등)이 ValidationError로 실패한다. 「검증 결과」 패널도 어긋남으로 센다.
- 확인: 스냅샷으로 들인 문헌에서 권 회전 저장. 고치려면 enum에 더하거나 들이기 값을 enum 안의 것으로(어느 쪽인지는 결정 필요).

## B-015 みんなで翻刻 엔진이 만든 L2가 스키마 위반 (koji 칸) (2026-10-11)

- 틀린 곳: `src/ocr/honkoku_engine.py:138·263`이 L2 행에 `koji`를 넣는데 `schemas/source_repo/ocr_page.schema.json:89`
  `OcrLine`은 `additionalProperties: false`이고 koji가 없다. D-124·user-guide 5.0-1의 «스키마의 행은 additionalProperties»와 모순.
- 보이는 것: 파이프라인은 저장 때 검증하지 않아 조용히 저장되고, 「검증 결과」 패널(`core/validation.py`)이 그 쪽들을 행마다 어긋남으로 센다.
- 확인: honkoku로 1쪽 OCR → 검증 결과. 스키마에 `koji`를 더할지(D-124 의도) 곁파일로 뺄지 결정 필요.

## B-016 인용 마크 편집기 — 코드포인트 좌표·권 구분이 없다 (2026-10-11)

- 틀린 곳: `src/app/static/js/citation-editor.js`가 원문 렌더·선택 범위를 `text.length`·`text[i]`(453·734~758행)로
  UTF-16 단위로 센다 — AGENTS «주석 좌표는 코드포인트»(D-127) 위반. 인용 마크 호출 8곳(401·603·824·930·969·1028·1269·1360)이
  `?part_id=`를 붙이지 않아 서버 기본값 «main»으로 간다(`routers/annotation.py:1405` 등).
- 보이는 것: 확장 한자(CJK 확장 B) 뒤의 인용 마크가 한 칸씩 어긋나고, 다권본에서 인용 마크가 권을 가리지 못한다(resolve는 part «main»의 L4를 찾는다).
- 잠복: `_getCiteFieldOrder`(1227)가 정의되지 않은 `CITE_PRESETS`를 참조한다 — `#cite-field-order-list`가 index.html:3225에 있어
  지금은 닿지 않지만 그 요소가 없으면 ReferenceError.
- 같은 모양(UTF-16 셈): `hyeonto-editor.js`의 현토 좌표 — 확장 한자 뒤에서 서버와 어긋날 수 있다(미확인, 실물 미측정).
- 확인: 확장 B 한자 뒤에 인용 마크를 달고 저장된 start/end를 파이썬 코드포인트와 비교; 다권본 vol2에서 마크 저장 위치 확인.

## B-017 원문 내보내기에 교정이 들어가지 않는다 (2026-10-11)

- 틀린 곳: `src/export/text_export.py:651~658` `export_document`가 `L4_text/pages/*.txt`를 그대로 읽는다. 교정 탭은 corrections 파일만 쓰고
  쪽 파일은 그대로 두므로 글자 교정·자유 편집이 빠진다. 머리말(5행)은 «교정 탭에서 L4를 고치면 그대로 반영된다»고 적는다.
- 보이는 것: 교정 탭에서 고친 글자가 «들이기·내보내기» 탭의 텍스트 내려받기에 교정 전 글로 나온다.
- 같은 문제를 `text_layer_pdf._load_lines`는 2026-10-02에 `get_corrected_text`로 고쳤다 — 같은 방식으로.
- 확인: 한 쪽에서 글자 하나를 교정 → 원문 내려받기 → 그 글자 확인.

## B-018 번역 탭 — 참조 사전 «적용»이 효과 없고, 일괄 AI 번역이 실패를 성공으로 센다 (2026-10-11)

- 틀린 곳 ①: `translation-editor.js:1090` `_applyRefDictSelection`이 `transState._refDictContext`(1113)를 적기만 하고 읽는 곳이 static 전체에 0건.
  서버 쪽 고리도 끊겨 있다 — `annotation_dict_match.format_for_translation_context`(327)와 `translation_llm.generate_translation_drafts`를 부르는 곳이 src에 없다.
- 틀린 곳 ②: `_aiTranslateAll`(763)이 `Promise.allSettled`로 세지만 `_aiTranslateSingle`(694)은 오류를 안에서 잡아 토스트만 띄우고 정상 반환한다(취소·문장 없음도 정상 반환).
- 보이는 것: 「적용」을 눌러도 다음 AI 번역에 사전이 실리지 않는다; 일괄 번역 끝 알림이 늘 «실패 0건».
- 확인: 참조 사전 적용 뒤 AI 번역 요청 본문(네트워크 탭)에 사전 문맥이 없음; 키 없이 일괄 번역 → «성공 N건».

## B-019 권 전체 OCR이 사람이 고른 LLM 모델을 무시한다 (2026-10-11)

- 틀린 곳: `src/app/static/js/ocr-panel.js:998`(`_runPartOcr`, 893)이 `getLlmModelSelection()`을 인자 없이 불러 언제나 «auto»가 된다
  (`workspace.js:2305` — select가 없으면 auto). 쪽 OCR(325)·1152행은 `"ocr-llm-model-select"`를 넘긴다.
- 보이는 것: LLM Vision으로 권 전체 OCR을 돌리면 고른 모델이 아니라 폴백 순서의 모델로 돈다. 확인 창에도 모델이 안 나온다.
- 경미: 같은 body의 `writing_direction: "vertical_rtl"` 고정(1009) — 계획 없는 가로쓰기 책은 전면 블록이 세로로 잡힌다(미확인, 실물 미측정).
- 확인: 모델을 고르고 권 전체 OCR → 요청 body의 `force_model`이 null.

## B-020 LLM 교정이 서고의 이체자 사전이 아니라 앱 폴더 사전을 읽는다 (2026-10-11)

- 틀린 곳: `src/core/alignment.py:223` `VariantCharDict._find_default_path`가 작업 디렉터리·앱 폴더의 `resources/variant_chars.json`을 찾는다.
  인자 없이 부르는 `routers/llm_ocr.py:1642`(`_correction_dicts`, LLM 교정의 strict 사전)가 이 길을 탄다. D-104 뒤 사람이 쌓는 사전은
  **서고 `resources/`**에 살고(`routers/alignment.py:47`), 앱 폴더의 그 파일은 `.gitignore:94`로 배포되지 않는다.
- 보이는 것: 이체자 탭에서 쌓은 사전이 LLM 교정에 쓰이지 않는다(배포본은 빈 사전, 개발 PC는 옛 파일).
- 확인: 서고 사전에 쌍을 넣고 LLM 교정 후보 → 그 쌍이 strict로 잡히지 않음.

## B-021 L6 텍스트·스냅샷 L4가 Windows에서 CRLF로 저장된다 (2026-10-11)

- 틀린 곳: `src/core/interpretation.py:749` `save_layer_content`가 «CRLF → LF 정규화»(782) 뒤 `Path.write_text`(784)로 쓴다 —
  Windows에서는 `\n`이 다시 `\r\n`이 된다. `core/snapshot.py:514`(들인 L4 쪽 글)도 같다. `document.save_page_text`는 `newline=""`을 준다.
- 보이는 것: 해석 저장소 L6 .txt·들인 문헌 L4가 CRLF가 되어 git diff가 줄 전체로 잡히고, 의존 추적 해시(CRLF 정규화)와 별개로 파일이 갈린다. AGENTS «LF 줄바꿈» 위반.
- 확인: Windows에서 L6 텍스트 저장 뒤 `git diff --stat`·`file`로 줄끝 확인.

## B-022 주석 라우터가 없는 L4 경로·없는 메타 파일을 읽는다 (2026-10-11)

- 틀린 곳 ①: `src/app/routers/annotation.py:212` `_l4_text_file`·217 `_load_page_blocks`·1077 generate-batch가 **해석 저장소**의
  `L4_text/main_text/{part}_page_NNN_text.json`을 읽는다. L4는 원본 저장소 `L4_text/pages/*.txt`에 산다 — 언제나 없음으로 폴백만 돈다
  (`_resolve_stage_block_id`의 4순위·일괄 생성의 L4 쪽 수집이 죽은 길).
- 틀린 곳 ②: 사전 내보내기 두 라우트(1182·1228, 읽는 자리 1202·1243)가 `interpretation.json`을 읽는데 해석 저장소 메타는 `manifest.json`이다.
- 틀린 곳 ③(경미): 주석 삭제(665)만 git 커밋 없이 저장한다.
- 보이는 것: 사전 내보내기의 문헌 id·제목이 언제나 해석 저장소 id로 나온다; 주석 삭제가 이력에 안 남는다. ①의 화면 영향은 (미확인).
- 확인: 사전 내보내기 결과의 `doc_title`; 주석 삭제 뒤 `git log`.

## B-023 스냅샷 검증기가 단위를 가리키는 해석 파일마다 거짓 경고를 낸다 (2026-10-11)

- 틀린 곳: `src/core/snapshot_validator.py:88` `_validate_interpretation`이 L5~L7의 `block_id`를 L3 LayoutBlock id(93~105)와 견준다.
  v1.3(D-092·D-093)부터 그 필드는 단위(경계) id다(B-003).
- 보이는 것: 지금 서고의 스냅샷을 들일 때 표점·현토·번역·주석마다 «L3에 없음» 경고가 쏟아진다 — 진짜 경고가 묻힌다.
- 확인: 표점이 있는 문헌을 내보내고 검증 → 경고 수. 대조 대상을 경계 id로 바꾼다.

## B-024 저장소 id 정규식이 두 곳에 있다 (2026-10-11)

- 틀린 곳: `src/core/reading_ingest.py:48`이 `^[a-z][a-z0-9_]{0,63}$`를 따로 정의해 `check_interp_id`(483)에 쓴다.
  `src/core/repo_id.py` 머리말은 «파이썬 쪽은 전부 이 모듈을 import한다»고 적는다.
- 보이는 것: 지금은 같다. 규칙을 `repo_id.py`에서만 바꾸면 강독 들이기의 id 검사만 옛 규칙으로 남는다(그 모듈이 막으려던 drift).
- 확인: `grep -rn "a-z0-9_" src` — `repo_id.REPO_ID_PATTERN`을 import하게 바꾼다.

## B-025 「내용」 트리의 시작 행 ▲▼가 해석 저장소 없이는 말없이 무시된다 (2026-10-11)

- 틀린 곳: `src/app/static/js/contents-tree.js:841` `_shiftBoundary`의 `if (!block.anchor || !contentsState.interpId) return;`.
  부르는 라우트는 문헌의 경계 PUT(`_boundaryUrl`, 853)이라 해석 저장소가 필요 없다(D-097). 같은 파일의 ⇤⇥·×·경계 넣기는 그 조건이 없다.
- 보이는 것: 해석 저장소를 고르지 않은 채 ▲▼를 누르면 아무 반응도 알림도 없다.
- 확인: 해석 저장소 없이 문헌을 열고 ▲ 클릭 → 확인 창이 안 뜸. 조건에서 `interpId`를 뺀다.

## B-026 이체자 사전 «활성화»에 화면에서 닿을 길이 없다 (2026-10-11)

- 틀린 곳: 서버 `PUT /api/variant-dicts/{name}/activate`(`routers/alignment.py:551`)를 static 전체에서 부르는 곳이 0건.
  `variant-manager.js` 머리말은 «다중 사전 관리(생성/복제/삭제/활성화)»라 적는다.
- 보이는 것: 드롭다운에서 사전을 고르면 보기·쌍 추가는 그 사전에 가지만, 대조·일괄 교정이 쓰는 «활성» 사전은 그대로다. 사람은 바꿨다고 여긴다.
- 확인: 다른 사전을 고르고 대조 실행 → 서버의 활성 사전 이름 그대로.

## B-027 PaddleOCR 오류 안내의 설치 명령이 지금 설치 방식과 반대다 (2026-10-11)

- 틀린 곳: `src/ocr/paddleocr_engine.py:392`(머리말 8행도)가 «설치: uv add --optional paddleocr paddlepaddle paddleocr»,
  350행이 «`uv sync --extra paddleocr`이 끝났는지»를 안내한다. pyproject에서 paddleocr는 기본 의존성(65행)이고 `paddleocr` extra는 빈 목록(159행)이며, GPU판은 `.venv-gpu`가 정본(D-078).
- 보이는 것: 엔진 사용 불가 이유로 이 문구가 화면에 뜬다 — 앞 명령은 pyproject를 고치고, 뒤 명령은 아무것도 설치하지 않는다.
- 확인: paddle 없는 환경에서 엔진 목록의 사용 불가 이유 문구. `doctor.bat` 안내로 바꾼다.

## B-028 OCR 라우트 여럿이 doc_id를 검증 없이 경로로 조립한다 (2026-10-11)

- 틀린 곳: `src/app/routers/llm_ocr.py`의 347·796·1090·2021·2086·2183·2218·2280·2386·2461·2528·2581·2677·2803행이
  `library_path / "documents" / doc_id`로 직접 만든다. 같은 파일에도 `require_repo_path`(`_state.py:49`) 호출이 10곳 있어 섞여 있다.
- 보이는 것: 지금 화면에서는 보이지 않는다. `_state.RepoPathError` docstring이 말한 «ID 검증 누락» 감사(2026-07-17 축②)의 남은 자리다.
  실제로 경로 밖에 닿을 수 있는지는 (미확인) — FastAPI 경로 매개변수는 `/`를 받지 않는다.
- 확인: `doc_id=..` 등으로 각 라우트를 불러 응답 확인 후 `require_repo_path`로 통일.

## B-029 화면에 넣는 문자열의 이스케이프가 빠진 자리 (2026-10-11)

D-069 «화면에 넣는 파일명·OCR 원문은 이스케이프»의 남은 자리. 악용 가능성은 자리마다 (미확인) — 대부분 사용자 자신의 데이터다.

- `citation-editor.js` 번역 상태 `[${t.status}]`·`data-cite-id="${m.id}"` · `composition-editor.js:1550·2066` 오류 문구 ·
  `hyeonto-editor.js:388·391·394·566·567` 현토 글자·원문 · `interpretation.js:214·215·519` 저장소 제목·문헌 id·의존 파일 경로 ·
  `translation-editor.js:496·502` 번역문·문장 · `workspace.js:1013·1021` repo.id·remote_url, `renderDocumentList`(2457) 제목 ·
  `entity-manager.js` id를 data 속성에 · `contents-tree.js:904` `data-block-id`를 `CSS.escape` 없이 셀렉터에 ·
  `hwp-import.js:876·878` textContent식 이스케이프를 `title` 속성에(봉인됨).
- 확인: 각 자리에 `"<img onerror>` 든 값을 넣어 headless Chrome으로 렌더.

## B-030 낡은 머리말·죽은 경로 정리 (2026-10-11)

동작에 영향 없는 낡은 docstring·주석·죽은 코드. 파일별 내용은 2026-10-11 전수 검토 기록(scratchpad `mismatches.md`)에 있다.

- 파일: `src/app/server.py`(라우터별 수 composition 17·llm_ocr 26·library 29 — 실측 20·27·30, 합계만 맞음; `check_doc_drift.py`는 라우터별 수를 안 봄) ·
  `src/app/routers/interpretations.py`·`version.py`(Work·overwrite 서술) · `src/app/routers/llm_ocr.py`(포함 라우트 목록 15/27, 백업 서술 모순) ·
  `src/app/static/js/` alignment-view(죽은 사전 추가·가져오기 진입) · composition-editor(머리말 자동 편성·합치기, `_executeSplit` 서술, 죽은 `_commitBatch`) ·
  contents-tree(내부 모순 docstring, «전부 적용해 새로 세우기») · entity-manager(«Work UUID», «entity.py:607») · hwp-import(«LLM» 서술, 이중 바인딩 — 봉인돼 닿지 않음) ·
  hyeonto-editor(source_refs 우선순위) · interpretation(층별 편집 서술) · layout-editor(저장 경로·no-store 주석) · notes-panel(`viewerState.interpId`) ·
  ocr-panel(죽은 `_fillFromOcr`) · translation-editor(«향후 연결», 단추 글자 «AI») · variant-manager(활성화 서술) · workspace(currentMode·Work·하단 패널 주석) ·
  `src/app/static/index.html`(«(LLM)» 단추 이름, Work·LayoutBlock 주석, 정의 안 된 CSS 변수 `--color-bg-secondary`·`--color-border`) ·
  `src/app/static/css/workspace.css`(낡은 주석 둘, 죽은 `.type-work`, 정의 안 된 변수 `--bg-hover`·`--error`·`--border-color`·`--border-muted`·`--font-body`) ·
  `src/cli/__main__.py`(사용법 셋·«pip install») · `src/core/alignment.py`(사용법 `src.` 가져오기) · `annotation_dict_match.py` · `annotation_llm.py`·`punctuation_llm.py`·`translation_llm.py`
  (부르는 곳 없는 초안 생성 함수; translation_llm의 commit은 draft_id를 안 뗌) · `boundaries.py`·`entity.py`(옛 경계 경로, «단위 만들기»·«하단 패널»;
  `_get_source_head_commit` 중복(entity.py:153 = interpretation.py:233), 부르는 곳 없는 `auto_create_units_from_text`(1282), 시험이 안 들어가는 `create_unit_from_source`) ·
  `interpretation.py`(«비교 탭», 화면이 안 부르는 layers 라우트) · `snapshot.py`(Work 용어) · `toc.py`(«실험이다» — 지금 목차 대조 경로) · `src/ocr/__init__.py`(gemma4:e4b·uv add·3.13) ·
  `src/export/text_export.py`(B-017 고친 뒤 머리말) · `punctuation-service/punctuation_service/engine.py`(«자리만 잡아둔») · `pyproject.toml`(63행 없는 절 가리킴) ·
  `install.sh:175~178`·`scripts/install_ollama_step.ps1:118~122`(«판독 계획 기본 모델» — D-132·D-135 뒤) · `schemas/interp/*_page.schema.json` `block_id` 설명(B-003과 함께).
- 2026-10-11 전수 검토 2차(tests·parsers·text_import 94개)에서 더한 것: `src/core/entity.py:60` `LEGACY_ENTITY_TYPES`(D-093이 «v1.4에서 지운다»고 했다) ·
  `start_server.bat:45~49`(«PaddleOCR runs in .venv (CPU worker)» — GPU 워커가 먼저다, D-091 덧붙임) · `start_server.sh`(포트 범위 안내, 업데이트 전에 브라우저를 엶) ·
  `src/parsers/archives_jp.py`(`except: pass` 두 곳 — 로그 없는 빈 결과, 낡은 IIIF·dpi 주석) · `ndl.py`(주석 셋, 발행자를 뽑고 매퍼가 안 씀) ·
  `src/text_import/pdf_extractor.py`(`fitz.open`을 `with` 없이 쓰는 호출자 셋 — AGENTS 규칙과 어긋남) · `src/text_import/common.py`(겹침 주석, `Path.write_text`로 CRLF) ·
  시험 머리말이 낡은 것: `test_annotation_dict_io`·`test_connectome`·`test_d128`·`test_doc_drift`·`test_forbidden_patterns`(CLAUDE.md → AGENTS.md)·`test_ocr_paddle`·
  `test_snapshot`(클래스 개수)·`test_ui_reachability`(B-009 «여섯 남음» — 이미 0).

## B-031 KORCIS 서지에 판식정보·소장처가 늘 비어 있다 (2026-10-11)

- 틀린 곳: `src/parsers/korcis.py:580·638`이 `printing_info`·`repository`를 `raw_data["_openapi_detail"]`에서만 채우는데,
  src 어디에서도 그 키를 넣지 않고 `openapi_detail()`을 부르는 곳도 없다(grep 0건).
- 보이는 것: KORCIS로 가져온 서지의 판식·소장처 칸이 비어, 편성의 «목록과 맞대기»(D-120 `compare_with_catalog`)에 재료가 생기지 않는다. 오류 없음.
- 시험이 가린다: `tests/test_korcis.py:155·159~166` 픽스처가 실제 수집 경로가 넣지 않는 `_openapi_detail`·`_title_kor`를 직접 넣는다. 627~643의 URL 시험 둘은
  `fetch_by_url`이 아니라 시험 안에 다시 적은 정규식을 돌린다(늘 통과).
- 확인: 실제 KORCIS URL 하나로 fetch-and-map → printing_info가 None인지. `openapi_detail()`을 수집 경로에 잇는다.

## B-032 외부 텍스트 쪽 대조가 쪽 경계를 앞당겨 자른다 (2026-10-11)

- 틀린 곳: `src/text_import/common.py:619~675` `align_text_to_pages`가 앵커 위치의 중앙값을 쪽 위치로, 이웃 쪽과의 중간점을 경계로 삼는다.
- 보이는 것: OCR과 외부 텍스트가 똑같아도 쪽마다 끝 글자가 다음 쪽으로 넘어간다(실측: 24자 쪽 3자, 60자 쪽 7자, 쪽 원문과 일치 0/3).
  호출처는 `documents.py:1682`(외부 텍스트 쪽 대조).
- 시험이 가린다: `tests/test_text_import_align.py:200~206`은 confidence와 «비어 있지 않음»만 본다.
- 확인: 같은 글 두 벌로 matched_text == 쪽 원문을 단언하는 시험 먼저.

## B-033 장서각(jsg) 서지 저장이 스키마에 막힌다 (2026-10-11)

- 틀린 곳: `src/parsers/jsg.py:289~290`이 `subject`에 «사부분류» 문자열, `classification`에 «유형분류» 문자열을 넣는다 —
  `bibliography.schema.json`은 `subject`=array|null, `classification`=object|null.
- 보이는 것: 그 두 칸이 있는 장서각 자료는 `core/document.py:1080` `save_bibliography`의 검증에서 저장이 실패한다(스크립트로 오류 2건 재현).
- 확인: 장서각 매퍼 출력을 스키마로 검증하는 시험.

## B-034 이미지 묶음 PDF의 쪽 순서가 p1, p10, p2로 뒤섞인다 (2026-10-11)

- 틀린 곳: `src/parsers/asset_detector.py:533~534` — 주석은 «파일명 기준 자연 정렬»인데 코드는 경로 문자열 사전순이다.
- 보이는 것: 0으로 채우지 않은 순번 이미지(p1~p10)로 만든 PDF의 쪽 순서가 예외·경고 없이 바뀐다. `test_asset_detector`는 한 자리 순번만 쓴다.
- 확인: p1~p12 이미지 URL로 순서 단언.

## B-035 시험이 재지 못하는 자리 (2026-10-11 전수 검토)

초록이어도 주장을 지키지 못하는 시험. 고칠 때는 «주장을 깨뜨려 빨간불»(maintenance §3)부터.

- `tests/test_paddle_worker.py:133~147` — torch 차단을 주장하지만 `.venv`에는 torch가 없어 차단 없이도 통과한다(`.venv-gpu`에서만 뜻이 있다).
- `tests/test_lite_mode_api.py` — 1704·1738·1788의 정리가 `registry._engines`에서 `llm_vision`을 pop만 해 진짜 엔진이 세션 나머지에서 사라진다(전역 레지스트리 오염).
  1220 시험은 `skip_existing=False`로 실제 `llm_vision`을 부를 수 있어 키가 있는 PC에서 실제 LLM 호출이 날 수 있다(미확인). 743~758은 L4 본문을 보지 않는다.
- `tests/test_llm_accounts.py:155~156` — 허용 상태에 `no_model`이 없어 비전 모델이 없는 PC에서 거짓 실패한다.
- `tests/test_composition_apply_plan_js.py:149~184` — `_planApply`가 `hideSecondNo`를 읽지 않아 «가림은 표시일 뿐»을 재지 못한다.
- `tests/test_ocr_image_utils.py:50~60·94~99`, `tests/test_annotation_dict_match.py:210`, `tests/test_correction_pass.py:702~705`, `tests/test_d128.py:134`(`or True`),
  `tests/test_read_plan.py:340·607`(모듈 상수 NOTE를 바꿈), `tests/test_ocr_kotenocr_contract.py`(빈 인식 결과 시험 없음).
- **결정 필요** — `tests/test_parsers.py:61~139`의 NDL 시험 셋은 실제 NDL API를 부르는데 `slow` 표지가 없어 빠른 계층과 완료 영수증에 든다.
  오프라인·NDL 장애 때 영수증이 코드와 무관하게 빨개진다. 표지를 달아 뺄지, 서지 파서 침묵 파손을 잡는 값으로 둘지 정한다.
- (미확인) `src/parsers/ndl.py:228~242` `fetch_detail`이 NDLBibID 키워드 검색의 첫 건을 ID 대조 없이 돌려준다.

## 닫힌 항목

| 번호 | 제목 | 닫은 근거 |
|---|---|---|
| B-004 | Windows 설치 파일(exe) | D-113, `c01b322` |
| B-007 | 자동 업데이트 | D-112, `ed37f01` |
| B-008 | 해석 패널이 어느 모드에서도 열리지 않는다 | `46190ee`(의존 경고·스냅샷 내보내기 이사), `f95399e`(옛 통합 편집기 철거·손 경계 500 고침) |
| B-009 | 화면 JS 전역 함수 이름 겹침 여섯 | `b92711b`(_render* 셋), `f26c799`(이스케이프 셋, `KNOWN` 비움) |
| B-010 | D-128 8항 승격 무게에 남은 구멍 셋 | `0548aa2`; `tests/test_codex_review.py` 8건 통과(2026-10-11 실행) |
