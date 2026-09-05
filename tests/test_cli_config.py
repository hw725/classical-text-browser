"""ctb config·ctb models — 기본값 저장과 모델 고르기. 네트워크·LLM 없이 규칙만 검사한다."""

import json
from pathlib import Path

import pytest

from cli import config as cli_config
from cli import models as cli_models

MODELS = [
    {"provider": "ollama", "model": "glm-ocr:latest", "display": "Ollama", "cost": "free"},
    {"provider": "openai_oauth", "model": "gpt-6-astra", "display": "OAuth", "cost": "free"},
    {"provider": "openai_oauth", "model": "gpt-5.6-sol", "display": "…", "cost": "free"},
    {"provider": "openai_oauth", "model": "gpt-5.6-luna", "display": "…", "cost": "free"},
    {"provider": "gemini", "model": "gemini-2.5-flash", "display": "…", "cost": "low"},
]


@pytest.fixture
def home(tmp_path: Path, monkeypatch):
    """설정 파일을 임시 홈에 둔다 — 사람의 진짜 기본값을 건드리지 않는다."""
    monkeypatch.setattr(cli_config, "config_path", lambda: tmp_path / "cli.json")
    return tmp_path


def test_save_and_load_roundtrip(home: Path):
    cli_config.save({"model": "openai_oauth:gpt-6-astra", "paddle_lang": "korean", "bogus": 1})
    saved = json.loads((home / "cli.json").read_text(encoding="utf-8"))
    assert "bogus" not in saved, "모르는 키는 저장하지 않는다"
    assert cli_config.load() == {"model": "openai_oauth:gpt-6-astra", "paddle_lang": "korean"}


def test_load_survives_missing_or_broken_file(home: Path):
    assert cli_config.load() == {}
    (home / "cli.json").write_text("{not json", encoding="utf-8")
    assert cli_config.load() == {}


def test_coerce_types_and_rejections():
    assert cli_config.coerce("line_detection", "false") is False
    assert cli_config.coerce("sleep", "1.5") == 1.5
    with pytest.raises(ValueError):
        cli_config.coerce("sleep", "abc")
    with pytest.raises(ValueError):
        cli_config.coerce("paddle_device", "tpu")
    with pytest.raises(ValueError):
        cli_config.coerce("nonsense", "x")


def test_resolve_number_partial_exact_and_provider():
    """번호·이름 일부·정확한 이름·프로바이더만 — 네 가지 모두 (provider, model)로."""
    assert cli_models.resolve("2", MODELS) == ("openai_oauth", "gpt-6-astra")
    assert cli_models.resolve("astra", MODELS) == ("openai_oauth", "gpt-6-astra")
    assert cli_models.resolve("openai_oauth:gpt-7-new", MODELS) == ("openai_oauth", "gpt-7-new")
    assert cli_models.resolve("gemini", MODELS) == ("gemini", None)


def test_resolve_ambiguous_and_missing_explain():
    with pytest.raises(ValueError) as e:
        cli_models.resolve("5.6", MODELS)
    assert "gpt-5.6-sol" in str(e.value) and "gpt-5.6-luna" in str(e.value)
    with pytest.raises(ValueError):
        cli_models.resolve("99", MODELS)
    with pytest.raises(ValueError):
        cli_models.resolve("zzz", MODELS)


def test_format_list_labels_subscription_not_free():
    """구독으로 도는 것은 «무료»가 아니라 «구독 한도»다(D-056)."""
    text = cli_models.format_list(MODELS)
    assert "openai_oauth:gpt-6-astra    구독 한도" in text
    assert "ollama:glm-ocr:latest    로컬 무료" in text
    assert "gemini:gemini-2.5-flash    종량 과금" in text
