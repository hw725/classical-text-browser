"""이체자 사전 테스트."""

import json

import pytest

from src.core.alignment import VariantCharDict


@pytest.fixture
def variant_dict(tmp_path):
    """테스트용 이체자 사전 (사용자가 직접 만드는 형식)."""
    data = {
        "_format_guide": {"설명": "이체자 사전 — 양방향 등록 필수"},
        "variants": {
            "說": ["説"],
            "説": ["說"],
            "裴": ["裵"],
            "裵": ["裴"],
            "經": ["経"],
            "経": ["經"],
        },
    }
    path = tmp_path / "variant_chars.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return VariantCharDict(str(path))


class TestVariantCharDict:
    def test_is_variant_true(self, variant_dict):
        assert variant_dict.is_variant("說", "説") is True
        assert variant_dict.is_variant("裴", "裵") is True

    def test_is_variant_bidirectional(self, variant_dict):
        assert variant_dict.is_variant("説", "說") is True
        assert variant_dict.is_variant("裵", "裴") is True

    def test_is_variant_false(self, variant_dict):
        assert variant_dict.is_variant("王", "裴") is False

    def test_same_char_not_variant(self, variant_dict):
        assert variant_dict.is_variant("王", "王") is False

    def test_unknown_char(self, variant_dict):
        assert variant_dict.is_variant("가", "나") is False

    def test_size(self, variant_dict):
        assert variant_dict.size == 6

    def test_missing_file(self):
        d = VariantCharDict("/nonexistent/path.json")
        assert d.size == 0
        assert d.is_variant("說", "説") is False

    def test_add_pair(self, variant_dict):
        assert variant_dict.is_variant("齒", "歯") is False
        variant_dict.add_pair("齒", "歯")
        assert variant_dict.is_variant("齒", "歯") is True
        assert variant_dict.is_variant("歯", "齒") is True

    def test_add_pair_same_char(self, variant_dict):
        old_size = variant_dict.size
        variant_dict.add_pair("王", "王")
        assert variant_dict.size == old_size

    def test_save_and_reload(self, tmp_path, variant_dict):
        save_path = str(tmp_path / "saved.json")
        variant_dict.save(save_path)
        reloaded = VariantCharDict(save_path)
        assert reloaded.is_variant("說", "説") is True
        assert reloaded.is_variant("裴", "裵") is True

    def test_to_dict(self, variant_dict):
        d = variant_dict.to_dict()
        assert "裴" in d
        assert "裵" in d["裴"]
