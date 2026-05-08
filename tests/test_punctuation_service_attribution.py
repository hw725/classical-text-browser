import sys
from pathlib import Path

_PUNCT_SERVICE_DIR = Path(__file__).resolve().parent.parent / "punctuation-service"
if str(_PUNCT_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(_PUNCT_SERVICE_DIR))

from punctuation_service.api import PunctuateResponse  # noqa: E402
from punctuation_service.attribution import MODEL_ATTRIBUTION  # noqa: E402


def test_model_attribution_contains_required_notice():
    assert MODEL_ATTRIBUTION["source"] == "yachagye/korean-classical-chinese-punctuation"
    assert MODEL_ATTRIBUTION["author"] == "Junghyun Yang (양정현)"
    assert MODEL_ATTRIBUTION["license"] == "CC BY-NC-SA 4.0"
    assert MODEL_ATTRIBUTION["doi"] == "10.37924/JSSW.100.9"
    assert "citation required" in MODEL_ATTRIBUTION["use_terms"]


def test_sikurroberta_response_can_include_model_attribution():
    response = PunctuateResponse(
        engine="sikurroberta",
        punctuated="",
        marks=[],
        attribution=MODEL_ATTRIBUTION,
    )

    assert response.attribution["source"] == MODEL_ATTRIBUTION["source"]
    assert response.attribution["citation"] == MODEL_ATTRIBUTION["citation"]


def test_mock_response_does_not_claim_model_attribution():
    response = PunctuateResponse(engine="mock", punctuated="", marks=[])

    assert response.attribution is None
