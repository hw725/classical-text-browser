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

## B-005 교환 형식이 두 벌이다 — 문서·스키마와 구현이 다르다 (2026-09-04, D-099 후속에서 발견)

`schemas/exchange.schema.json`(= platform-v7 §11.2)과 실제 내보내기(`core/snapshot.py`)가
**다른 모양**이다. 그리고 그 스키마는 **파이썬 어디서도 참조하지 않는다**(실측).

| | 문서·스키마 | 구현 |
|---|---|---|
| 머리말 | `export_info` + `source_info` | `export_timestamp` + `platform_version` + `source_info` |
| 본문 | `parts` + `pages` + `corrected_text` + `corrections` | `original` + `interpretation` |
| 덤 | 없음 | `variant_characters` + `annotation_types` |

- 지금 무엇이 문제인가: 스키마가 검증에 쓰이지 않으므로 **깨진 스냅샷을 막지 못한다**.
  검증은 `snapshot_validator.py`의 손으로 적은 규칙뿐이다. 문서를 믿고 만든 외부 도구는
  가져오기가 안 된다.
- 하려면 정할 것: ① 어느 쪽을 정본으로 삼는가(구현 쪽이 실제로 도는 것이다)
  ② 스키마를 구현에 맞춘 뒤 `build_snapshot` 결과를 그 스키마로 검증할 것인가
  ③ `schema_version`을 올릴 것인가(옛 스냅샷 가져오기 폴백이 이미 있다 — `source_info(data)`).
- 급하지 않은 이유: 스냅샷 내보내기·가져오기는 지금 한 사람이 한 서고에서만 쓴다.
