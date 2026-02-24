"""LLM 모듈 통합 테스트.

Phase 10-2: LLM 4단 폴백 아키텍처 검증.
외부 API 없이 동작하도록 mock provider를 사용.

테스트 항목:
  - LlmConfig: 설정 로드, .env 파싱
  - LlmDraft: Draft → accept/modify/reject 워크플로우
  - UsageTracker: JSONL 기록, 월별 요약
  - LlmRouter: 폴백, 강제 선택, 모델 목록, 상태 조회
  - layout_analyzer: JSON 파싱 헬퍼
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

# src/ 디렉토리를 경로에 추가
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from llm.config import LlmConfig
from llm.draft import LlmDraft
from llm.providers.base import (
    BaseLlmProvider,
    LlmProviderError,
    LlmResponse,
    LlmUnavailableError,
)
from llm.usage_tracker import UsageTracker


# ─── Mock Provider ───────────────────────────────────────────

class MockProvider(BaseLlmProvider):
    """테스트용 모의 provider.

    is_available/call/call_with_image의 동작을 외부에서 제어 가능.
    """

    def __init__(
        self,
        config,
        provider_id: str = "mock",
        display_name: str = "Mock",
        available: bool = True,
        supports_image: bool = True,
        response_text: str = "mock response",
        should_error: bool = False,
    ):
        super().__init__(config)
        self.provider_id = provider_id
        self.display_name = display_name
        self._available = available
        self.supports_image = supports_image
        self._response_text = response_text
        self._should_error = should_error
        self.call_count = 0

    async def is_available(self) -> bool:
        return self._available

    async def call(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        response_format: str = "text",
        model: Optional[str] = None,
        max_tokens: int = 4096,
        purpose: str = "text",
        **kwargs,
    ) -> LlmResponse:
        if self._should_error:
            raise LlmProviderError(f"{self.provider_id} 에러")
        self.call_count += 1
        return LlmResponse(
            text=self._response_text,
            provider=self.provider_id,
            model=model or "mock-model",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.0,
            elapsed_sec=0.1,
        )

    async def call_with_image(
        self,
        prompt: str,
        image: bytes,
        *,
        image_mime: str = "image/png",
        system: Optional[str] = None,
        response_format: str = "text",
        model: Optional[str] = None,
        max_tokens: int = 4096,
        **kwargs,
    ) -> LlmResponse:
        if self._should_error:
            raise LlmProviderError(f"{self.provider_id} 이미지 에러")
        self.call_count += 1
        return LlmResponse(
            text=self._response_text,
            provider=self.provider_id,
            model=model or "mock-vision",
            tokens_in=100,
            tokens_out=200,
            cost_usd=0.01,
            elapsed_sec=2.5,
        )


# ─── LlmConfig 테스트 ───────────────────────────────────────

class TestLlmConfig:
    """LLM 설정 관리 테스트."""

    def test_defaults(self):
        """기본값이 올바르게 반환된다."""
        config = LlmConfig()
        assert config.get("ollama_url") == "http://localhost:11434"
        assert config.get("nonexistent", "fallback") == "fallback"

    def test_dotenv_loading(self):
        """.env 파일에서 설정을 로드한다."""
        with tempfile.TemporaryDirectory() as td:
            env_path = Path(td) / ".env"
            env_path.write_text(
                "ANTHROPIC_API_KEY=test-key-123\n"
                "MONTHLY_BUDGET_USD=5.0\n"
                "# 주석은 무시\n"
                "\n"
                "AGENT_CHAT_URL=http://custom:9999\n",
                encoding="utf-8",
            )
            config = LlmConfig(library_root=Path(td))
            assert config.get_api_key("anthropic") == "test-key-123"
            assert config.get("agent_chat_url") == "http://custom:9999"

    def test_api_key_not_found(self):
        """등록되지 않은 provider의 API 키는 None."""
        config = LlmConfig()
        assert config.get_api_key("unknown_provider") is None


# ─── LlmDraft 테스트 ────────────────────────────────────────

class TestLlmDraft:
    """Draft → Review → Commit 워크플로우."""

    def test_initial_status_pending(self):
        """새 Draft는 pending 상태."""
        draft = LlmDraft(purpose="layout_analysis")
        assert draft.status == "pending"
        assert draft.draft_id  # 자동 생성된 ID
        assert draft.created_at  # 타임스탬프

    def test_accept(self):
        """Draft 승인."""
        draft = LlmDraft(purpose="test")
        draft.accept(quality_rating=4, notes="정확함")
        assert draft.status == "accepted"
        assert draft.quality_rating == 4
        assert draft.quality_notes == "정확함"
        assert draft.reviewed_at is not None

    def test_modify(self):
        """Draft 수정 후 승인."""
        draft = LlmDraft(purpose="test")
        draft.modify("블록 2개 합침", quality_rating=3)
        assert draft.status == "modified"
        assert draft.modifications == "블록 2개 합침"
        assert draft.quality_rating == 3

    def test_reject(self):
        """Draft 거부."""
        draft = LlmDraft(purpose="test")
        draft.reject("완전히 틀림")
        assert draft.status == "rejected"
        assert draft.quality_notes == "완전히 틀림"

    def test_to_dict(self):
        """JSON 직렬화에서 None 필드 제외."""
        draft = LlmDraft(purpose="layout_analysis", provider="ollama")
        d = draft.to_dict()
        assert "purpose" in d
        assert "provider" in d
        # None인 필드는 제외
        assert "modifications" not in d
        assert "quality_rating" not in d


# ─── UsageTracker 테스트 ─────────────────────────────────────

class TestUsageTracker:
    """JSONL 사용량 추적 테스트."""

    def test_log_and_read(self):
        """호출 기록이 JSONL에 저장된다."""
        with tempfile.TemporaryDirectory() as td:
            config = LlmConfig(library_root=Path(td))
            tracker = UsageTracker(config)

            response = LlmResponse(
                text="답변",
                provider="ollama",
                model="test-model",
                tokens_in=50,
                tokens_out=100,
                cost_usd=0.001,
                elapsed_sec=1.5,
            )
            tracker.log(response, purpose="layout_analysis")

            log_path = Path(td) / "llm_usage_log.jsonl"
            assert log_path.exists()

            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 1

            entry = json.loads(lines[0])
            assert entry["type"] == "call"
            assert entry["provider"] == "ollama"
            assert entry["model"] == "test-model"
            assert entry["purpose"] == "layout_analysis"

    def test_monthly_summary(self):
        """월별 요약이 올바르게 집계된다."""
        with tempfile.TemporaryDirectory() as td:
            config = LlmConfig(library_root=Path(td))
            tracker = UsageTracker(config)

            # 3건 기록
            for i in range(3):
                response = LlmResponse(
                    text=f"답변 {i}",
                    provider="ollama" if i < 2 else "anthropic",
                    model="model-x",
                    cost_usd=0.0 if i < 2 else 0.05,
                    elapsed_sec=1.0,
                )
                tracker.log(response, purpose="test")

            summary = tracker.get_monthly_summary()
            assert summary["total_calls"] == 3
            assert summary["total_cost_usd"] == pytest.approx(0.05, abs=0.001)
            assert summary["by_provider"]["ollama"]["calls"] == 2
            assert summary["by_provider"]["anthropic"]["calls"] == 1
            assert summary["by_purpose"]["test"] == 3

    def test_empty_log_summary(self):
        """로그 파일이 없어도 요약이 정상 반환된다."""
        with tempfile.TemporaryDirectory() as td:
            config = LlmConfig(library_root=Path(td))
            tracker = UsageTracker(config)
            summary = tracker.get_monthly_summary()
            assert summary["total_calls"] == 0
            assert summary["total_cost_usd"] == 0.0

    def test_log_comparison(self):
        """비교 모드 기록이 JSONL에 저장된다."""
        with tempfile.TemporaryDirectory() as td:
            config = LlmConfig(library_root=Path(td))
            tracker = UsageTracker(config)

            results = [
                LlmResponse(
                    text="result1", provider="ollama", model="m1",
                    elapsed_sec=1.0,
                ),
                ValueError("에러 발생"),
            ]
            tracker.log_comparison(
                "layout_analysis",
                [("ollama", "m1"), ("anthropic", None)],
                results,
            )

            log_path = Path(td) / "llm_usage_log.jsonl"
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            entry = json.loads(lines[0])
            assert entry["type"] == "comparison"
            assert len(entry["results"]) == 2
            assert entry["results"][0]["provider"] == "ollama"
            assert entry["results"][1]["error"] is not None


# ─── LlmRouter 테스트 (Mock Provider) ───────────────────────

class TestLlmRouter:
    """LlmRouter 폴백 + 강제선택 + 비교 테스트.

    실제 provider 대신 MockProvider를 주입.
    """

    def _make_router(self, providers):
        """MockProvider 목록으로 router를 구성."""
        with tempfile.TemporaryDirectory() as td:
            config = LlmConfig(library_root=Path(td))

            from llm.router import LlmRouter
            router = LlmRouter(config)
            router.providers = providers
            return router, config

    @pytest.mark.asyncio
    async def test_fallback_order(self):
        """첫 번째 사용 불가 → 두 번째로 폴백."""
        config = LlmConfig()
        p1 = MockProvider(config, provider_id="first", available=False)
        p2 = MockProvider(config, provider_id="second", available=True,
                          response_text="second response")

        from llm.router import LlmRouter
        router = LlmRouter(config)
        router.providers = [p1, p2]

        response = await router.call("테스트")
        assert response.provider == "second"
        assert response.text == "second response"
        assert p2.call_count == 1

    @pytest.mark.asyncio
    async def test_all_unavailable(self):
        """모든 provider 사용 불가 시 LlmUnavailableError."""
        config = LlmConfig()
        p1 = MockProvider(config, provider_id="a", available=False)
        p2 = MockProvider(config, provider_id="b", available=False)

        from llm.router import LlmRouter
        router = LlmRouter(config)
        router.providers = [p1, p2]

        with pytest.raises(LlmUnavailableError):
            await router.call("테스트")

    @pytest.mark.asyncio
    async def test_force_provider(self):
        """force_provider로 특정 provider 직접 호출."""
        config = LlmConfig()
        p1 = MockProvider(config, provider_id="first", response_text="p1")
        p2 = MockProvider(config, provider_id="second", response_text="p2")

        from llm.router import LlmRouter
        router = LlmRouter(config)
        router.providers = [p1, p2]

        response = await router.call("테스트", force_provider="second")
        assert response.provider == "second"
        assert response.text == "p2"

    @pytest.mark.asyncio
    async def test_force_unknown_provider(self):
        """존재하지 않는 provider 지정 시 에러."""
        config = LlmConfig()
        p1 = MockProvider(config, provider_id="first")

        from llm.router import LlmRouter
        router = LlmRouter(config)
        router.providers = [p1]

        with pytest.raises(LlmProviderError, match="찾을 수 없습니다"):
            await router.call("테스트", force_provider="nonexistent")

    @pytest.mark.asyncio
    async def test_force_unavailable_provider(self):
        """사용 불가 provider 강제 지정 시 에러."""
        config = LlmConfig()
        p1 = MockProvider(config, provider_id="first", available=False)

        from llm.router import LlmRouter
        router = LlmRouter(config)
        router.providers = [p1]

        with pytest.raises(LlmProviderError, match="사용할 수 없습니다"):
            await router.call("테스트", force_provider="first")

    @pytest.mark.asyncio
    async def test_error_fallback(self):
        """첫 provider가 에러 → 다음으로 폴백."""
        config = LlmConfig()
        p1 = MockProvider(config, provider_id="err", should_error=True)
        p2 = MockProvider(config, provider_id="ok", response_text="ok")

        from llm.router import LlmRouter
        router = LlmRouter(config)
        router.providers = [p1, p2]

        response = await router.call("테스트")
        assert response.provider == "ok"

    @pytest.mark.asyncio
    async def test_call_with_image_skip_non_vision(self):
        """이미지 호출 시 supports_image=False provider는 건너뛴다."""
        config = LlmConfig()
        p1 = MockProvider(config, provider_id="text_only",
                          supports_image=False)
        p2 = MockProvider(config, provider_id="vision",
                          supports_image=True, response_text="vision ok")

        from llm.router import LlmRouter
        router = LlmRouter(config)
        router.providers = [p1, p2]

        response = await router.call_with_image("분석해줘", b"fake-image")
        assert response.provider == "vision"

    @pytest.mark.asyncio
    async def test_compare(self):
        """비교 모드: 여러 provider 병렬 호출."""
        config = LlmConfig()
        p1 = MockProvider(config, provider_id="a", response_text="a result")
        p2 = MockProvider(config, provider_id="b", response_text="b result")

        from llm.router import LlmRouter
        router = LlmRouter(config)
        router.providers = [p1, p2]

        results = await router.compare(
            "테스트", targets=["a", "b"]
        )
        assert len(results) == 2
        texts = {r.text for r in results if isinstance(r, LlmResponse)}
        assert "a result" in texts
        assert "b result" in texts

    @pytest.mark.asyncio
    async def test_compare_with_error(self):
        """비교 모드: 일부 provider 에러 시 Exception 포함."""
        config = LlmConfig()
        p1 = MockProvider(config, provider_id="ok", response_text="ok")
        p2 = MockProvider(config, provider_id="err", should_error=True)

        from llm.router import LlmRouter
        router = LlmRouter(config)
        router.providers = [p1, p2]

        results = await router.compare("테스트", targets=["ok", "err"])
        assert len(results) == 2
        assert isinstance(results[0], LlmResponse)
        assert isinstance(results[1], Exception)

    @pytest.mark.asyncio
    async def test_get_status(self):
        """각 provider 가용 상태 조회."""
        config = LlmConfig()
        p1 = MockProvider(config, provider_id="avail",
                          display_name="Available", available=True)
        p2 = MockProvider(config, provider_id="down",
                          display_name="Down", available=False)

        from llm.router import LlmRouter
        router = LlmRouter(config)
        router.providers = [p1, p2]

        status = await router.get_status()
        assert status["avail"]["available"] is True
        assert status["down"]["available"] is False

    @pytest.mark.asyncio
    async def test_get_available_models(self):
        """GUI 모델 목록 조회."""
        config = LlmConfig()
        p1 = MockProvider(config, provider_id="mock_p",
                          display_name="Mock P", available=True)

        from llm.router import LlmRouter
        router = LlmRouter(config)
        router.providers = [p1]

        models = await router.get_available_models()
        assert len(models) >= 1
        assert models[0]["provider"] == "mock_p"
        assert models[0]["available"] is True


# ─── layout_analyzer JSON 파싱 테스트 ────────────────────────

class TestLayoutAnalyzerParsing:
    """레이아웃 분석 헬퍼 함수 테스트."""

    def test_parse_clean_json(self):
        """정상 JSON 파싱."""
        from core.layout_analyzer import _parse_llm_json

        text = '{"blocks": [{"block_type": "main_text"}]}'
        result = _parse_llm_json(text)
        assert "blocks" in result
        assert result["blocks"][0]["block_type"] == "main_text"

    def test_parse_code_block_wrapped(self):
        """```json ... ``` 감싸진 JSON 파싱."""
        from core.layout_analyzer import _parse_llm_json

        text = '```json\n{"blocks": [], "page_description": "테스트"}\n```'
        result = _parse_llm_json(text)
        assert result["page_description"] == "테스트"

    def test_parse_code_block_no_lang(self):
        """``` ... ``` (언어 표시 없음) 파싱."""
        from core.layout_analyzer import _parse_llm_json

        text = '```\n{"blocks": []}\n```'
        result = _parse_llm_json(text)
        assert result["blocks"] == []

    def test_parse_invalid_json(self):
        """잘못된 JSON은 JSONDecodeError."""
        from core.layout_analyzer import _parse_llm_json

        with pytest.raises(json.JSONDecodeError):
            _parse_llm_json("이것은 JSON이 아닙니다")

    def test_load_prompt(self):
        """레이아웃 분석 프롬프트가 로드된다."""
        from core.layout_analyzer import _load_prompt

        prompt = _load_prompt()
        assert "system" in prompt
        assert "prompt_template" in prompt
        assert "bbox_ratio" in prompt["prompt_template"]
