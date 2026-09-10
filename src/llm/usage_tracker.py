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
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# OTel GenAI Semantic Conventions (안정화 진행 중) 스키마 URL.
# Phase 1에서는 키 명명만 정렬하고, Phase 2에서 opentelemetry-sdk를 통해
# 동일한 키를 실제 span/log attribute로 승격할 예정이다.
_OTEL_SCHEMA_URL = "https://opentelemetry.io/schemas/1.30.0"

USAGE_LOG_NAME = "llm_usage_log.jsonl"


def default_usage_log_path(library_root=None) -> Path:
    """사용 기록 파일의 자리를 정하는 **유일한** 규칙.

    입력: 서고 루트(없으면 None).
    출력: 기록 파일 경로. 서고가 있으면 그 안, 없으면 앱 설정 폴더.

    앱 설정 폴더는 `core/app_config.py`와 같은 규칙으로 고른다 —
    `CTB_CONFIG_DIR`가 있으면 그곳, 없으면 `~/.classical-text-browser`.
    왜 환경 변수를 여기서 다시 읽는가: 검증 서버·pytest처럼 사용자의 홈을
    건드리면 안 되는 프로세스가 스위치 하나로 기록까지 딴 곳에 두게 하려는
    것이다. 실제로 서고 없이 만든 `LlmConfig()`로 도는 라우터 테스트가 mock
    응답 2,100여 행을 사용자 홈의 기록에 섞어 넣었다(2026-09-10 확인).
    `app_config.CONFIG_DIR`를 import하지 않고 매번 읽는 이유는, 그 상수가
    import 시점에 굳어 conftest가 뒤늦게 바꾼 값을 못 보기 때문이다.

    라우터 쪽(`routers/llm_ocr.py`)의 «지금까지 쌓인 줄 수» 계산도 이 함수를
    써야 같은 파일을 본다.
    """
    if library_root:
        return Path(library_root) / USAGE_LOG_NAME
    config_dir = os.environ.get("CTB_CONFIG_DIR")
    base = Path(config_dir) if config_dir else Path.home() / ".classical-text-browser"
    return base / USAGE_LOG_NAME


class UsageTracker:
    """LLM 사용량 추적. 서고별 llm_usage_log.jsonl에 기록."""

    def __init__(self, config, log_path: Optional[Path] = None):
        """입력: LlmConfig(서고 루트를 `_library_root`로 가짐)와,
        시험·도구가 기록 자리를 직접 정하고 싶을 때 주는 `log_path`.
        `log_path`를 주면 서고·환경 변수보다 우선한다."""
        self.config = config
        self._injected_path: Optional[Path] = Path(log_path) if log_path else None
        self._log_path: Optional[Path] = None

    def _get_log_path(self) -> Path:
        """로그 파일 경로. 서고 루트가 없으면 앱 설정 폴더(`default_usage_log_path`).

        처음 한 번만 자리를 정하고 부모 폴더를 만든다.
        """
        if self._log_path:
            return self._log_path

        if self._injected_path:
            self._log_path = self._injected_path
        else:
            library_root = getattr(self.config, "_library_root", None)
            self._log_path = default_usage_log_path(library_root)

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
