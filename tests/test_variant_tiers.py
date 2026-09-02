"""이체자 사전 3층·문헌별 승인·원자료 파서 테스트 (D-080).

무엇을 고정하는가:
  - 층(tier)이 없는 기존 파일은 strict로 읽힌다 — 예전 판정이 바뀌지 않는다
  - TieredVariantDicts: strict만 동치, loose·script는 힌트. 여러 사전이면 가장 강한 층
  - align_texts: strict 쌍은 variant, loose·script 쌍은 mismatch + variant_hint
  - 문헌별 승인: 파일이 없으면 빈 사전, 승인·철회가 문헌 디렉터리에만 저장된다
  - 파서: OpenCC / Unihan / cjkvi CSV / jp-old-style(IVS 제거)가 쌍을 올바르게 뽑는다
  - 페이로드에 _tier·_source(URL·파일·라이선스·날짜)가 남는다
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.alignment import (
    MatchType,
    TieredVariantDicts,
    VariantCharDict,
    align_texts,
    load_document_approvals,
    save_document_approvals,
)
from src.core.variant_sources import (
    build_dict_payload,
    pairs_to_variants,
    parse_cjkvi_csv,
    parse_jp_old_style,
    parse_opencc,
    parse_unihan_variants,
)


def _write_dict(path: Path, variants: dict, tier: str | None = None, source: dict | None = None):
    data = {"variants": variants}
    if tier:
        data["_tier"] = tier
    if source:
        data["_source"] = source
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return VariantCharDict(str(path))


# ─── 층 읽기·쓰기 ───────────────────────────────────────────────


class TestTierMetadata:
    def test_legacy_file_is_strict(self, tmp_path):
        vd = _write_dict(tmp_path / "v.json", {"說": ["説"], "説": ["說"]})
        assert vd.tier == "strict" and vd.source is None

    def test_tier_and_source_loaded(self, tmp_path):
        vd = _write_dict(
            tmp_path / "v.json", {"专": ["專"]}, tier="script", source={"name": "OpenCC"}
        )
        assert vd.tier == "script" and vd.source == {"name": "OpenCC"}

    def test_unknown_tier_falls_back_to_strict(self, tmp_path):
        vd = _write_dict(tmp_path / "v.json", {"a": ["b"]}, tier="weird")
        assert vd.tier == "strict"

    def test_save_preserves_tier_and_source(self, tmp_path):
        vd = _write_dict(
            tmp_path / "v.json", {"专": ["專"]}, tier="loose", source={"name": "x", "url": "u"}
        )
        vd.save(str(tmp_path / "out.json"))
        again = VariantCharDict(str(tmp_path / "out.json"))
        assert again.tier == "loose" and again.source["url"] == "u"

    def test_save_of_legacy_dict_stays_legacy(self, tmp_path):
        vd = _write_dict(tmp_path / "v.json", {"說": ["説"], "説": ["說"]})
        vd.save(str(tmp_path / "out.json"))
        data = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
        assert "_tier" not in data and "_source" not in data


# ─── TieredVariantDicts ───────────────────────────────────────────


@pytest.fixture
def bundle(tmp_path):
    strict = _write_dict(tmp_path / "s.json", {"說": ["説"], "説": ["說"]})
    loose = _write_dict(tmp_path / "l.json", {"丘": ["业"], "业": ["丘"]}, tier="loose")
    script = _write_dict(tmp_path / "c.json", {"专": ["專"], "專": ["专"]}, tier="script")
    # 같은 쌍이 두 층에 있으면 강한 층이 이긴다
    both = _write_dict(tmp_path / "b.json", {"專": ["专"], "专": ["專"]}, tier="strict")
    return TieredVariantDicts([strict, loose, script]), both


class TestTieredVariantDicts:
    def test_classify_by_tier(self, bundle):
        b, _ = bundle
        assert b.classify("說", "説") == "strict"
        assert b.classify("丘", "业") == "loose"
        assert b.classify("专", "專") == "script"
        assert b.classify("王", "裴") is None

    def test_is_variant_only_strict(self, bundle):
        b, _ = bundle
        assert b.is_variant("說", "説") is True
        assert b.is_variant("丘", "业") is False  # 넓은 사전은 동치가 아니다
        assert b.is_variant("专", "專") is False

    def test_hint_for_non_strict(self, bundle):
        b, _ = bundle
        assert b.hint("丘", "业") == "loose"
        assert b.hint("专", "專") == "script"
        assert b.hint("說", "説") is None
        assert b.hint("王", "裴") is None

    def test_strongest_tier_wins(self, bundle):
        b, both = bundle
        b.add(both)
        assert b.classify("专", "專") == "strict"
        assert b.is_variant("专", "專") is True


# ─── align_texts 힌트 ─────────────────────────────────────────────


class TestAlignHints:
    def test_strict_is_variant_and_loose_is_hinted_mismatch(self, bundle):
        b, _ = bundle
        pairs = align_texts("說丘专王", "説业專裴", variant_dict=b)
        by_ocr = {p.ocr_char: p for p in pairs}
        assert by_ocr["說"].match_type == MatchType.VARIANT
        assert by_ocr["說"].variant_hint is None
        assert by_ocr["丘"].match_type == MatchType.MISMATCH
        assert by_ocr["丘"].variant_hint == "loose"
        assert by_ocr["专"].match_type == MatchType.MISMATCH
        assert by_ocr["专"].variant_hint == "script"
        assert by_ocr["王"].match_type == MatchType.MISMATCH
        assert by_ocr["王"].variant_hint is None

    def test_hint_serialized_only_when_present(self, bundle):
        b, _ = bundle
        pairs = align_texts("丘王", "业裴", variant_dict=b)
        d = [p.to_dict() for p in pairs]
        assert d[0]["variant_hint"] == "loose"
        assert "variant_hint" not in d[1]

    def test_plain_dict_still_works(self, tmp_path):
        """예전처럼 VariantCharDict 하나를 넘겨도 동작한다 (hint 메서드 없음)."""
        vd = _write_dict(tmp_path / "v.json", {"說": ["説"], "説": ["說"]})
        pairs = align_texts("說王", "説裴", variant_dict=vd)
        assert pairs[0].match_type == MatchType.VARIANT
        assert pairs[1].match_type == MatchType.MISMATCH and pairs[1].variant_hint is None


# ─── 문헌별 승인 ─────────────────────────────────────────────────


class TestDocumentApprovals:
    def test_missing_file_is_empty_strict(self, tmp_path):
        vd = load_document_approvals(tmp_path)
        assert vd.size == 0 and vd.tier == "strict"
        assert not (tmp_path / "variant_approvals.json").exists()

    def test_approve_and_reload(self, tmp_path):
        vd = load_document_approvals(tmp_path)
        vd.add_pair("丘", "业")
        path = save_document_approvals(tmp_path, vd)
        assert Path(path).name == "variant_approvals.json"
        again = load_document_approvals(tmp_path)
        assert again.is_variant("丘", "业") and again.tier == "strict"
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert data["_tier"] == "strict" and data["_source"]["name"] == "document_approval"

    def test_approval_promotes_only_in_bundle(self, tmp_path):
        loose = _write_dict(tmp_path / "l.json", {"丘": ["业"], "业": ["丘"]}, tier="loose")
        b = TieredVariantDicts([loose])
        assert b.is_variant("丘", "业") is False
        approvals = load_document_approvals(tmp_path)
        approvals.add_pair("丘", "业")
        b.add(approvals)
        assert b.is_variant("丘", "业") is True
        # 넓은 사전 파일 자체는 바뀌지 않았다
        assert VariantCharDict(str(tmp_path / "l.json")).tier == "loose"

    def test_revoke(self, tmp_path):
        vd = load_document_approvals(tmp_path)
        vd.add_pair("丘", "业")
        save_document_approvals(tmp_path, vd)
        vd = load_document_approvals(tmp_path)
        assert vd.remove_pair("丘", "业") is True
        assert vd.remove_pair("丘", "业") is False


# ─── 파서 ────────────────────────────────────────────────────────


class TestParsers:
    def test_opencc(self):
        text = "# comment\n专\t專\n业\t業\n干\t幹 乾 干\n中国\t中國\n"
        pairs = parse_opencc(text)
        assert ("专", "專") in pairs and ("业", "業") in pairs
        assert ("干", "幹") in pairs and ("干", "乾") in pairs
        assert ("干", "干") not in pairs
        assert all(len(a) == 1 and len(b) == 1 for a, b in pairs)  # 어구는 제외

    def test_unihan_fields_and_source_tags(self):
        text = (
            "# Unihan\n"
            "U+4E00\tkSemanticVariant\tU+58F9<kFenn U+5F0C\n"
            "U+4E00\tkZVariant\tU+F0FF\n"
            "U+4E13\tkTraditionalVariant\tU+5C08\n"
        )
        loose = parse_unihan_variants(text, ["kSemanticVariant"])
        assert ("一", "壹") in loose and ("一", "弌") in loose
        strict = parse_unihan_variants(text, ["kZVariant"])
        assert strict == [("一", "")]
        script = parse_unihan_variants(text, ["kTraditionalVariant"])
        assert script == [("专", "專")]

    def test_cjkvi_csv_skips_declarations_and_ids(self):
        text = (
            "twedu/variant,<reverse>,twedu/regular\n"
            "twedu/variant,<name>,異體字（民國教育部）\n"
            "一,twedu/variant,弌\n"
            "丘,twedu/variant,业\n"
            "#充[⿱亠厶],hydzd/variant,充[⿻一厶]\n"
            "劫,hydzd/variant,刼[刼=⿰去刃]\n"
        )
        pairs = parse_cjkvi_csv(text)
        assert pairs == [("一", "弌"), ("丘", "业"), ("劫", "刼")]

    def test_jp_old_style_strips_ivs(self):
        text = (
            "# header\n亜\U000e0100\t亞\U000e0100\n逢\U000e0100\t逢\U000e0101\n"
            "亥\U000e0100\t\t\t# ★\n医\U000e0100\t醫\U000e0100\n"
        )
        pairs = parse_jp_old_style(text)
        assert ("亜", "亞") in pairs and ("医", "醫") in pairs
        assert all("\U000e0100" not in a + b for a, b in pairs)
        assert ("逢", "逢") not in pairs  # IVS만 다른 것은 같은 글자

    def test_pairs_to_variants_bidirectional(self):
        v = pairs_to_variants([("专", "專"), ("專", "专"), ("业", "業")])
        assert v == {"专": ["專"], "專": ["专"], "业": ["業"], "業": ["业"]}

    def test_payload_records_provenance(self):
        payload = build_dict_payload(
            [("专", "專")],
            tier="script",
            source_name="OpenCC",
            source_url="https://example/",
            source_files=["STCharacters.txt"],
            license_note="Apache-2.0",
            retrieved="2026-09-02",
        )
        assert payload["_tier"] == "script"
        assert payload["_source"]["pair_count"] == 1
        assert payload["_source"]["files"] == ["STCharacters.txt"]
        assert payload["_source"]["license"] == "Apache-2.0"
        assert payload["_source"]["retrieved"] == "2026-09-02"
        # 저장소 사전 형식과 호환 — 그대로 읽힌다
        assert set(payload["variants"]) == {"专", "專"}

    def test_payload_rejects_unknown_tier(self):
        with pytest.raises(ValueError):
            build_dict_payload(
                [], tier="fuzzy", source_name="", source_url="", source_files=[], license_note=""
            )
