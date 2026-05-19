# 관측 가능성 로드맵 — OpenTelemetry 점진적 도입

> 강의 11(Walking Labs)의 "OpenTelemetry로 표준화하라" 권고에 대한 본 프로젝트의 도입 로드맵.
> Phase 1은 적용 완료. Phase 2/3은 본 문서에 메모만 남겨 두고 필요 시 발동한다.

## 배경

본 프로젝트는 이미 강한 **프로세스 관측 가능성**(process observability)을 갖추고 있다.

- 결정 카드 50개([`DECISIONS.md`](DECISIONS.md))
- 세션 카드 14개([`sessions/`](sessions/))의 4단 구조
- 릴리스 노트의 재실행 가능한 검증 명령([`releases/v1.1.4.md`](releases/v1.1.4.md))
- `CLAUDE.md`라는 단일 진실 원천

그러나 **런타임 관측 가능성**(runtime observability)은 부분적이다.

- `llm_usage_log.jsonl` (provider · model · tokens · cost · elapsed)
- OCR/정렬/SSE 등 다른 결정 경계에는 구조화 로그 없음
- 한 작업이 LLM → OCR → 정렬 → 사용자 검토로 어떻게 흘러갔는지 *트레이스가 없음*

OpenTelemetry는 단일 도구가 아니라 **데이터 모델 + SDK + 프로토콜(OTLP)** 의 집합이다. 이 로드맵은 비용을 단계적으로 분산한다.

---

## Phase 1 — 키 명명만 정렬 (완료, 2026-05-19)

**범위**: 코드 구조·동작·의존성 변경 없음. 기존 JSONL 로그의 키 이름을 OTel GenAI Semantic Conventions에 맞춤.

**결정**: [D-051 LLM 사용 로그 OTel 명명 정렬](DECISIONS.md#d-051)

**구현 파일**: [`src/llm/usage_tracker.py`](../src/llm/usage_tracker.py)

**키 매핑** (옛 키는 호환을 위해 함께 유지):

| 옛 키 | OTel 키 | 출처 |
|---|---|---|
| `ts` | `@timestamp` | OTel Logs Data Model |
| `provider` | `gen_ai.system` | GenAI SemConv |
| `model` | `gen_ai.request.model`, `gen_ai.response.model` | GenAI SemConv |
| `tokens_in` | `gen_ai.usage.input_tokens` | GenAI SemConv |
| `tokens_out` | `gen_ai.usage.output_tokens` | GenAI SemConv |
| `elapsed_sec` × 1000 | `duration_ms` | OTel 공통 |
| `purpose` | `gen_ai.operation.name` | GenAI SemConv |
| `cost_usd` | `harness.cost_usd` | 도메인 확장 (OTel 표준 없음) |
| `type` | `event.name` | OTel Logs Data Model |
| — | `schema_url` | OTel 식별자 |

**검증**:

```powershell
uv run python -c "from src.llm.usage_tracker import UsageTracker; print('ok')"
```

**효과**:
- 다운스트림(`get_monthly_summary()`)은 옛 키를 그대로 읽으므로 **무파괴**.
- Phase 2 도입 시 코드 수정 없이 OTel 키가 그대로 span attribute로 승격된다.
- 외부 분석 도구(예: jq)도 두 키 중 어느 쪽을 골라도 작동한다.

```bash
# 새 OTel 키로 조회 예시
jq 'select(."gen_ai.system"=="openai") | ."gen_ai.usage.input_tokens"' llm_usage_log.jsonl

# 옛 키로 조회 (호환)
jq 'select(.provider=="openai") | .tokens_in' llm_usage_log.jsonl
```

---

## Phase 2 — opentelemetry-sdk 도입 (예정, 발동 조건 충족 시)

**범위**: SDK 추가 + 콘솔 익스포터로 시작. 백엔드 없이도 트레이스 확인.

**발동 조건** (다음 중 하나 충족 시):

- LLM·OCR·정렬 호출 간 *흐름 추적*이 디버깅 병목이 될 때
- 한 사용자 작업의 latency breakdown이 필요할 때
- 외부 OTel-호환 백엔드(Jaeger·Tempo·Honeycomb 등) 도입 결정이 날 때

**작업 목록**:

1. `pyproject.toml`에 의존성 추가
   ```toml
   "opentelemetry-api>=1.27.0",
   "opentelemetry-sdk>=1.27.0",
   "opentelemetry-instrumentation-fastapi>=0.48b0",
   "opentelemetry-instrumentation-httpx>=0.48b0",
   "opentelemetry-exporter-otlp-proto-http>=1.27.0",
   ```

2. `src/app/_state.py` 또는 `src/app/server.py`에 초기화 (10~15줄)
   ```python
   from opentelemetry import trace
   from opentelemetry.sdk.trace import TracerProvider
   from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
   from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

   trace.set_tracer_provider(TracerProvider())
   trace.get_tracer_provider().add_span_processor(
       BatchSpanProcessor(ConsoleSpanExporter())
   )
   FastAPIInstrumentor.instrument_app(app)
   ```

3. `src/llm/router.py`·`src/ocr/pipeline.py`·`src/core/alignment.py` 결정 경계에 수동 span 추가
   ```python
   tracer = trace.get_tracer(__name__)
   with tracer.start_as_current_span(
       "gen_ai.client.inference",
       attributes={
           "gen_ai.system": provider_id,
           "gen_ai.request.model": model,
           "gen_ai.operation.name": purpose,
       },
   ) as span:
       response = provider.complete(...)
       span.set_attribute("gen_ai.usage.input_tokens", response.tokens_in)
       span.set_attribute("gen_ai.usage.output_tokens", response.tokens_out)
   ```

4. `UsageTracker.log()`는 그대로 두되, span context를 받아 `trace_id`·`span_id`도 entry에 기록 — 로그와 트레이스 상호 참조.

5. SSE 스트림([D-028](DECISIONS.md#d-028))은 stream span의 하위 이벤트로 토큰 청크 기록.

**비-목표**: 외부 백엔드 부착은 Phase 3로 미룬다. Phase 2까지는 콘솔 출력만으로도 디버깅 가치가 있다.

**예상 비용**: 1~2일 작업 + 시작 시 ~200MB SDK 의존성.

---

## Phase 3 — 백엔드 부착 (예정, 사용자 수요 시)

**범위**: Jaeger 또는 Tempo를 Docker로 띄우고 UI에서 트레이스 시각화.

**발동 조건**:

- 다중 사용자/세션의 트레이스 비교 필요
- 시간 단위 latency 회귀 모니터링 필요
- 외부 협력자에게 트레이스 공유 필요

**작업 목록**:

1. `docker-compose.observability.yml` 추가
   ```yaml
   services:
     jaeger:
       image: jaegertracing/all-in-one:1.62
       ports: ["16686:16686", "4317:4317", "4318:4318"]
       environment:
         - COLLECTOR_OTLP_ENABLED=true
   ```

2. `.env`에 `OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318` 추가.

3. SDK 초기화의 `ConsoleSpanExporter`를 `OTLPSpanExporter`로 교체.

4. `start_server.bat`에 Jaeger Docker 자동 기동 추가 (이미 [D-048](DECISIONS.md#d-048) SikuRoBERTa, [D-049](DECISIONS.md#d-049) OAuth 자동 기동 패턴이 있어 동일 방식 적용 가능).

5. `docs/user-guide.md`의 "9. 문제 해결" 절에 "Jaeger UI에서 트레이스 확인하기" 단락 추가.

**비-목표**:
- 유료 SaaS(Datadog·Honeycomb 등) 도입. 이 프로젝트는 비상업적 라이선스(PolyForm Noncommercial)이며 외부 SaaS 비용은 어울리지 않는다.
- 메트릭(Prometheus·OTel Metrics) 도입. 본 도구는 단일 사용자 데스크톱 환경이라 메트릭의 가치가 낮다.

---

## 회피해야 할 함정

- **벤더 락인**: Datadog·Honeycomb·New Relic 등 특정 SaaS의 독자 SDK를 도입하면 OTel의 가치(백엔드 교체 가능성)가 사라진다.
- **결정 카드의 OTel 대체 시도**: 결정 카드는 *프로세스 관측 가능성*, OTel은 *런타임 관측 가능성*이다. 강의 11이 말하는 **계층화된 관측 가능성**(layered observability)은 둘이 함께 가야 한다.
- **모든 함수에 span 추가**: span은 *결정 경계*에만 둔다. LLM 호출, OCR 호출, 정렬 호출, 사용자 검토 같은 곳. 내부 헬퍼 함수는 trace에 잡지 않는다.

## 참고

- OTel GenAI Semantic Conventions: https://opentelemetry.io/docs/specs/semconv/gen-ai/
- OTel Logs Data Model: https://opentelemetry.io/docs/specs/otel/logs/data-model/
- Walking Labs 강의 11: https://walkinglabs.github.io/learn-harness-engineering/ko/lectures/lecture-11-why-observability-belongs-inside-the-harness/
- 본 프로젝트의 패턴 회고: [`retrospective/04_patterns.md`](retrospective/04_patterns.md)
- 하네스 권고와의 관계: [`retrospective/05_harness.md`](retrospective/05_harness.md) (H5 검증 코드화·H8 회고 가능한 오류와 직접 결합)
