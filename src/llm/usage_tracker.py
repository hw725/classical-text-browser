"""LLM 사용량 추적.

서고별 llm_usage_log.jsonl에 매 호출 기록.
무료 provider(Ollama)도 기록하여 사용 패턴 분석.

관측 가능성(Observability) — OpenTelemetry Phase 1 (D-051):
    JSONL 각 줄은 OTel GenAI Semantic Conventions 키를 함께 기록한다.
    옛 키(provider/model/tokens_in/...)는 다운스트림(get_monthly_summary 등)
    호환을 위해 그대로 유지하며, 새 키(gen_ai.system/gen_ai.request.model/...)는
    Phase 2(opentelemetry-sdk 도입) 시 별도 작업 없이 그대로 활용된다.
    참고: docs/observability-roadmap.md
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# OTel GenAI Semantic Conventions (안정화 진행 중) 스키마 URL.
# Phase 1에서는 키 명명만 정렬하고, Phase 2에서 opentelemetry-sdk를 통해
# 동일한 키를 실제 span/log attribute로 승격할 예정이다.
_OTEL_SCHEMA_URL = "https://opentelemetry.io/schemas/1.30.0"


class UsageTracker:
    """LLM 사용량 추적. 서고별 llm_usage_log.jsonl에 기록."""

    def __init__(self, config):
        self.config = config
        self._log_path: Optional[Path] = None

    def _get_log_path(self) -> Path:
        """로그 파일 경로. 서고 루트가 없으면 홈 디렉토리."""
        if self._log_path:
            return self._log_path

        library_root = getattr(self.config, "_library_root", None)
        if library_root:
            self._log_path = Path(library_root) / "llm_usage_log.jsonl"
        else:
            self._log_path = Path.home() / ".classical-text-browser" / "llm_usage_log.jsonl"

        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        return self._log_path

    def log(self, response, purpose: str = ""):
        """호출 기록 추가."""
        from .providers.base import LlmResponse

        if not isinstance(response, LlmResponse):
            return

        ts_iso = datetime.now(timezone.utc).isoformat()
        tokens_in = response.tokens_in
        tokens_out = response.tokens_out
        cost_usd = response.cost_usd or 0.0
        elapsed_sec = response.elapsed_sec
        duration_ms = int((elapsed_sec or 0) * 1000)

        entry = {
            # ── 옛 키 (다운스트림 호환, Phase 2에서 제거 예정) ──
            "ts": ts_iso,
            "type": "call",
            "provider": response.provider,
            "model": response.model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "elapsed_sec": elapsed_sec,
            "purpose": purpose,
            # ── OTel GenAI Semantic Conventions (Phase 1) ──
            "schema_url": _OTEL_SCHEMA_URL,
            "event.name": "gen_ai.client.inference.operation.details",
            "@timestamp": ts_iso,
            "gen_ai.system": response.provider,
            "gen_ai.request.model": response.model,
            "gen_ai.response.model": response.model,
            "gen_ai.usage.input_tokens": tokens_in,
            "gen_ai.usage.output_tokens": tokens_out,
            "gen_ai.operation.name": purpose or "unknown",
            "duration_ms": duration_ms,
            # 도메인 확장 속성 (OTel 표준 없음 → harness.* 네임스페이스)
            "harness.cost_usd": cost_usd,
        }
        self._append(entry)

    def log_comparison(self, purpose, targets, results):
        """비교 모드 호출 기록."""
        from .providers.base import LlmResponse

        ts_iso = datetime.now(timezone.utc).isoformat()
        entry = {
            # ── 옛 키 ──
            "ts": ts_iso,
            "type": "comparison",
            "purpose": purpose,
            "targets": [{"provider": pid, "model": model} for pid, model in targets],
            "results": [
                {
                    "provider": r.provider if isinstance(r, LlmResponse) else None,
                    "model": r.model if isinstance(r, LlmResponse) else None,
                    "text_length": len(r.text) if isinstance(r, LlmResponse) else 0,
                    "elapsed_sec": (r.elapsed_sec if isinstance(r, LlmResponse) else None),
                    "error": str(r) if isinstance(r, Exception) else None,
                }
                for r in results
            ],
            # ── OTel — 비교 모드는 표준 GenAI 이벤트가 아니므로
            #    harness.* 네임스페이스의 도메인 이벤트로 분류 ──
            "schema_url": _OTEL_SCHEMA_URL,
            "event.name": "harness.llm.comparison",
            "@timestamp": ts_iso,
            "gen_ai.operation.name": purpose or "unknown",
        }
        self._append(entry)

    def _append(self, entry: dict):
        """JSONL 파일에 한 줄 추가."""
        path = self._get_log_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_monthly_summary(self) -> dict:
        """이번 달 사용량 요약."""
        path = self._get_log_path()
        if not path.exists():
            return {
                "total_calls": 0,
                "total_cost_usd": 0.0,
                "by_provider": {},
                "by_purpose": {},
            }

        now = datetime.now(timezone.utc)
        month_prefix = now.strftime("%Y-%m")

        total_calls = 0
        total_cost = 0.0
        by_provider: dict = {}
        by_purpose: dict = {}

        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") != "call":
                continue
            if not entry.get("ts", "").startswith(month_prefix):
                continue

            total_calls += 1
            cost = entry.get("cost_usd", 0.0) or 0.0
            total_cost += cost

            prov = entry.get("provider", "unknown")
            if prov not in by_provider:
                by_provider[prov] = {"calls": 0, "cost": 0.0}
            by_provider[prov]["calls"] += 1
            by_provider[prov]["cost"] += cost

            purp = entry.get("purpose", "unknown")
            by_purpose[purp] = by_purpose.get(purp, 0) + 1

        budget = float(self.config.get("monthly_budget_usd", 10.0) or 10.0)

        return {
            "total_calls": total_calls,
            "total_cost_usd": round(total_cost, 4),
            "by_provider": by_provider,
            "by_purpose": by_purpose,
            "budget_usd": budget,
            "budget_remaining_usd": round(budget - total_cost, 4),
        }
