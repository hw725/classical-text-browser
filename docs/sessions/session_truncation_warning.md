# 세션: 잘린 LLM 응답 화면 경고 — 설계 설명 (explain-diff)

> 2026-07-06. 커밋 `56000f8`(1차·백엔드 플래그) → `b91f3ef`(2차·UI 소비)에 대한 「왜」 설명 문서.
> 대상 독자: 인문학 연구자(코드 상세보다 흐름·의도 위주). 코드가 도는 방식을 이해하면
> 유지보수 때 「내 PC에선 되는데 왜 저기선 안 되지」 같은 함정을 피할 수 있다.

## 배경 — 무엇이 문제였나

AI 표점·주석 기능은 LLM에게 JSON 배열(`marks`, `annotations`)을 받아온다.
그런데 LLM 응답이 토큰 한도 등으로 **중간에 끊기면** JSON이 깨진 채 도착한다.

1차 수정(`56000f8`)에서 백엔드(`_state.py`의 `_salvage_truncated_array_payload`)가
이 깨진 배열에서 **완성된 항목만 건져내고**, 결과 dict에 잘림 사실을 표시하도록 했다:

```python
return {key: items, "_truncated": True, "_recovered_count": len(items)}
```

문제는 이 `_truncated` 플래그를 **읽어서 화면에 보여주는 곳이 없었다**는 것.
즉 응답이 잘려 일부만 복구됐는데도 화면상으로는 조용해서, 연구자가 불완전한
표점·주석을 완전한 것으로 오인할 위험이 있었다. 2차 수정(`b91f3ef`)이 이 마지막
한 걸음 — 「도착한 플래그를 소비해 경고 토스트를 띄우는 것」 — 을 채웠다.

## 변경 요약 (2차, 4파일 +69줄)

| 파일 | 변경 |
|---|---|
| `static/js/workspace.js` | `notifyLlmTruncation()` 공용 헬퍼 추가 — `_truncated`면 경고 토스트 |
| `static/js/punctuation-editor.js` | AI 표점 결과 수신 후 헬퍼 호출 |
| `static/js/annotation-editor.js` | 단일 경로는 헬퍼 호출, 문장 병렬 경로는 집계 후 1회 경고 |
| `static/index.html` | 수정 3파일 캐시 버전(`?v=`) 갱신 |

경고 문구: 「LLM 표점 응답이 중간에 잘려 완성된 N개 항목만 복구했습니다 —
누락 가능성이 있으니 재실행을 권장합니다.」

---

## 핵심 「왜」 — 세 가지 설계 판단

### 질문 1. 왜 백엔드는 거의 안 고쳐도 됐나

`_truncated` 플래그가 **파싱 결과 dict 안에** 들어 있고, 그 dict가
**아무 가공 없이 그대로 흘러가기** 때문이다.

```
_parse_llm_json → {annotations:[...], _truncated:true, _recovered_count:2, _provider:..., _model:...}
        │  이 dict를 통째로
        ▼
_call_llm_text → return parsed          (그대로 반환)
        ▼
라우터(annotation.py 등) → return result  (그대로 반환)
        ▼  FastAPI가 JSON으로 직렬화
프론트 fetchWithSSE → return result       (SSE·폴백 양쪽 모두 그대로 반환)
```

이 경로 어디에도 「필요한 키만 골라 새 dict를 만든다」거나 「`_`로 시작하는 키를
지운다」는 코드가 없다(확인함). 이미 `_provider`·`_model` 같은 메타 필드가 같은
방식으로 프론트까지 잘 도착하고 있었고(프론트가 `data._provider`를 이미 사용),
`_truncated`도 **자동으로 같은 파이프를 타고** 프론트 손끝까지 와 있었다.

→ 그래서 백엔드 수정은 0줄. 남은 일은 도착한 값을 **읽어서 띄우는** 것뿐이었다.

**교훈**: 데이터에 메타 정보를 실어 흘려보내는 구조에서는, 새 메타 필드 하나를
파이프 입구에서 실으면 출구까지 저절로 도달한다. 손댈 곳은 「소비 지점」 하나뿐.

### 질문 2. 왜 주석 문장 병렬 경로는 문장마다가 아니라 「집계 후 1회」 경고인가

긴 텍스트의 주석 태깅은 문장 단위로 쪼개 **동시에 여러 번 LLM을 호출**한다
(코드상 `CONCURRENCY = 3`). 40문장이면 40번 호출이고, 그중 여럿이 각각 잘릴 수 있다.

헬퍼를 문장마다 호출하면 → **토스트가 10개, 20개씩 우르르** 뜬다. 화면 우상단이
경고로 도배되면 오히려 연구자가 무시하게 되고(경고 피로, alert fatigue), 정작
「몇 문장이 문제인지」 파악이 안 된다.

그래서 루프 동안 개수만 세어두고, 전부 끝난 뒤 **딱 한 번** 종합해 보여준다:

```javascript
let truncatedSentences = 0;   // 잘린 문장 수
let truncatedRecovered = 0;   // 복구된 총 항목 수
// ... 각 문장 결과에서 누적 ...
if (truncatedSentences > 0) {
  showToast(`LLM 주석 응답이 ${truncatedSentences}개 문장에서 잘려 ` +
            `완성된 ${truncatedRecovered}개 항목만 복구했습니다 — ...`, "warning");
}
```

짧은 텍스트의 단일 호출 경로는 애초에 호출이 하나뿐이라 그냥 헬퍼를 바로 부른다.

**교훈**: 알림은 「빠짐없이」보다 「무시당하지 않게」가 우선. N번 반복되는 작업의
경고는 집계해서 1회로 묶는다.

### 질문 3. 왜 JS를 고쳤는데 `index.html`의 `?v=` 숫자를 바꿨나

이 앱은 **빌드 도구가 없는 순수 vanilla JS**다(webpack·vite 같은 번들러 없음).
브라우저는 성능을 위해 한 번 받은 `workspace.js`를 **디스크에 캐시**해두고, 다음
방문 때 서버에 다시 안 물어보고 캐시본을 쓴다.

```html
<script src="/static/js/workspace.js?v=20260224c"></script>   ← 이전
<script src="/static/js/workspace.js?v=20260706a"></script>   ← 변경 후
```

브라우저 입장에서 `...js?v=20260224c`와 `...js?v=20260706a`는 **URL이 다른 =
다른 파일**이다. `?v=` 뒤 문자열을 바꾸면 캐시를 무시하고 서버에서 **새 파일을
강제로 다시 받는다**(cache-busting, 캐시 무효화 기법).

이걸 안 바꿨다면 — 코드를 아무리 잘 고쳐도 연구자 브라우저는 옛 캐시본을 계속
써서 **경고가 안 뜨는** 상황이 생긴다. 「내 PC에선 되는데 사용자한텐 안 되는」
전형적 함정. 그래서 내용을 바꾼 3개 파일만 버전을 올렸고, 안 건드린 `toast.js`는
그대로 뒀다(불필요한 재다운로드 방지).

**교훈**: 무빌드 정적 앱에서 JS/CSS를 수정하면 반드시 해당 파일의 `?v=`를 갱신한다.
바꾼 파일만.

---

## 검증 (실행 확인)

1. **백엔드 전파 단위 테스트**: 잘린 `annotations`/`marks` 문자열을
   `_parse_llm_json`에 넣어 `_truncated:True` + 정확한 `_recovered_count` 확인.
   완전한 응답은 플래그 없음(오탐 0). 통과.
2. **JS 문법**: 수정 3파일 `node --check` 통과.
3. **실제 파일 바이트로 헬퍼 로직 테스트**: 잘림 → 토스트 1회, 정상 → 토스트 0. 통과.
4. **라이브 브라우저 확인**: `uv run python -m app serve`로 앱 구동 후, 실행 중인
   페이지에서 `notifyLlmTruncation({_truncated:true, _recovered_count:5}, "표점")`
   호출 → 우상단에 `toast-warning`(호박색) 배너가 정확한 한국어 문구로 렌더링됨을
   스크린샷으로 확인. 정상 응답에는 미표시.

## 관련 파일·함수 포인터

- 백엔드 복구·플래그: `src/app/_state.py` — `_salvage_truncated_array_payload`,
  `_parse_llm_json`(906행 정의가 실사용; 775행 정의는 재정의로 덮임)
- 진입 함수: `_call_llm_text`(비스트림) / `_call_llm_text_stream`(SSE)
- 라우터: `routers/annotation.py`, `routers/reading.py`
- 프론트 헬퍼: `static/js/workspace.js`의 `notifyLlmTruncation`, `fetchWithSSE`
- 토스트: `static/js/toast.js`의 `showToast(message, type, duration)`

## 후속 참고

- **번역(translation)** 은 배열 salvage 대상이 아니라(단일 문자열 반환)
  `_truncated`가 뜰 수 없어 이번 변경에서 제외했다. 훗날 번역도 배열 복구를
  도입하면 `translation-editor.js`에도 `notifyLlmTruncation` 호출을 추가하면 된다.
