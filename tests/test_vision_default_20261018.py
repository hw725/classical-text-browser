"""Ollama 이미지(비전) 기본 모델도 kimi-k3:cloud다 (D-143 보충, 2026-10-18 사용자 지적).

무엇을 지키는가:
    D-143은 Ollama 《기본》을 glm-5.2·glm-5.3·kimi-k3 가운데서 고르라는 인계를 글 작업에만
    적용하고 이미지 기본은 `gemma4:cloud`(D-114)로 남겼다. 사용자: 《이미지도 kimi나 glm 5.2
    쓰라니까》. 세 후보 가운데 이미지를 받는 것은 kimi-k3:cloud뿐이다(Ollama /api/show
    capabilities 실측 2026-10-18 — glm-5.2·glm-5.3에는 vision이 없다). 그래서
    1. 앱의 이미지 기본(`ollama_catalog.DEFAULT_VISION_MODEL` → OllamaProvider)은 kimi-k3:cloud.
    2. 설정에 OLLAMA_VISION_MODEL이 없으면 OCR은 kimi-k3:cloud를 고른다(목록에 gemma4가 있어도).
    3. 설치 스크립트가 등록하는 기본 모델도 kimi-k3:cloud 하나다(gemma4:cloud를 따로 받지 않는다).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from llm.config import LlmConfig
from llm.providers.ollama import OllamaProvider

ROOT = Path(__file__).resolve().parents[1]


def test_vision_default_is_kimi_k3():
    from llm import ollama_catalog

    assert ollama_catalog.DEFAULT_VISION_MODEL == "kimi-k3:cloud"
    assert OllamaProvider.DEFAULT_MODELS["vision"] == "kimi-k3:cloud"


def test_ocr_picks_kimi_even_when_gemma_is_installed(monkeypatch):
    monkeypatch.delenv("OLLAMA_VISION_MODEL", raising=False)
    cfg = LlmConfig()
    cfg._env_cache = {}
    p = OllamaProvider(cfg)
    monkeypatch.setattr(p, "_shared_get", lambda key: None)
    monkeypatch.setattr(p, "_shared_set", lambda key, value: None)

    async def models(**kw):
        # gemma4가 목록의 앞에 있어도 기본(kimi-k3)을 먼저 본다
        return [
            {"name": "gemma4:cloud", "vision": True},
            {"name": "kimi-k3:cloud", "vision": True},
        ]

    async def alive(model):
        return True

    monkeypatch.setattr(p, "list_models", models)
    monkeypatch.setattr(p, "_is_model_alive", alive)
    assert asyncio.run(p._pick_vision_model()) == "kimi-k3:cloud"


def test_install_registers_kimi_not_gemma():
    """설치 스크립트 둘이 기본 이미지 모델로 gemma4:cloud를 받거나 안내하지 않는다."""
    step = (ROOT / "scripts/install_ollama_step.ps1").read_text(encoding="utf-8-sig")
    install = (ROOT / "install.ps1").read_text(encoding="utf-8-sig")
    assert "gemma4:cloud" not in step
    assert "gemma4:cloud" not in install
    assert '"pull", "kimi-k3:cloud"' in step
