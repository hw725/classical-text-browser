from src.app._state import get_external_punctuation_url


def test_external_punctuation_url_defaults_to_local_service(monkeypatch):
    monkeypatch.delenv("EXTERNAL_PUNCT_URL", raising=False)
    monkeypatch.delenv("PUNCT_HOST", raising=False)
    monkeypatch.delenv("PUNCT_PORT", raising=False)

    assert get_external_punctuation_url() == "http://127.0.0.1:8765"


def test_external_punctuation_url_uses_explicit_override(monkeypatch):
    monkeypatch.setenv("EXTERNAL_PUNCT_URL", "http://punctuation.local:9000")

    assert get_external_punctuation_url() == "http://punctuation.local:9000"


def test_external_punctuation_url_can_follow_punct_port(monkeypatch):
    monkeypatch.delenv("EXTERNAL_PUNCT_URL", raising=False)
    monkeypatch.setenv("PUNCT_HOST", "0.0.0.0")
    monkeypatch.setenv("PUNCT_PORT", "9876")

    assert get_external_punctuation_url() == "http://127.0.0.1:9876"


def test_external_punctuation_url_can_be_disabled(monkeypatch):
    monkeypatch.setenv("EXTERNAL_PUNCT_URL", "off")

    assert get_external_punctuation_url() is None
