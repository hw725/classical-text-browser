"""엔진 인공물 신자체 → 정자 (D-138).

지키는 것
  - 1:1 확정 글자만 바꾸고, 원본이 그 글자일 수 있는 글자(欠·余·芸·台·弁·内)는 바꾸지 않는다.
  - NDL古典籍OCR(lite·full) 출력에만 적용한다 — 다른 엔진 출력은 그대로(D-080 결정 1 유지).
  - 바꾼 자리를 L2 `ocr_config.script_normalize` 에 남기고, 그 기록으로 되돌릴 수 있다.
  - 블록 일부만 다시 인식해 합칠 때 남은 블록의 기록은 이어받는다.
  - 저장된 L2 가 ocr_page 스키마를 그대로 통과한다(글자 객체에 필드를 더하지 않는다).
"""

import copy
import json
from pathlib import Path

import jsonschema

from scripts.build_shinjitai_table import big5_level1, build
from src.ocr import script_normalize as sn
from src.ocr.pipeline import OcrPageResult, OcrPipeline
from src.ocr.registry import OcrEngineRegistry

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (ROOT / "schemas" / "source_repo" / "ocr_page.schema.json").read_text(encoding="utf-8")
)


def block(text, bid="b1"):
    return {"layout_block_id": bid,
            "lines": [{"text": text, "characters": [{"char": c, "confidence": 0.9} for c in text]}]}


def test_table_rule_converts_only_settled_pairs():
    conv, amb = sn.load_table()
    pairs = [("学", "學"), ("伝", "傳"), ("歳", "歲"), ("国", "國"), ("会", "會"), ("読", "讀")]
    for shin, sei in pairs:
        assert conv[shin] == sei
    for shin in ["欠", "余", "芸", "台", "弁", "内"]:
        assert shin not in conv and shin in amb


def test_build_rule_on_synthetic_lines():
    conv, amb = build("学\t學\n弁\t辨 辯 瓣\n内\t内 內\n欠\t缺\n# 주석\n")
    assert conv == {"学": "學"}
    assert set(amb) == {"弁", "内", "欠"}
    assert big5_level1("欠") and not big5_level1("学")


def test_normalize_and_revert_roundtrip():
    b = block("学問伝来欠")
    orig = copy.deepcopy(b)
    rec = sn.normalize_block(b)
    assert b["lines"][0]["text"] == "學問傳來欠"
    assert [c["char"] for c in b["lines"][0]["characters"]] == list("學問傳來欠")
    assert [r[2] for r in rec["changed"]] == ["学", "伝", "来"]
    assert rec["ambiguous"] == [[0, 4, "欠", ["缺"]]]
    sn.revert_block(b, rec)
    assert b == orig


def test_applies_only_to_ndl_koten_engines():
    assert sn.applies("ndlkotenocr") and sn.applies("ndlkotenocr-full")
    assert not sn.applies("llm_vision") and not sn.applies("paddleocr") and not sn.applies(None)


def _pipeline(tmp_path):
    (tmp_path / "documents" / "doc001").mkdir(parents=True)
    return OcrPipeline(OcrEngineRegistry(), library_root=str(tmp_path))


def _saved(tmp_path):
    p = tmp_path / "documents" / "doc001" / "L2_ocr" / "vol1_page_001.json"
    return json.loads(p.read_text(encoding="utf-8"))


def test_save_records_and_passes_schema(tmp_path):
    pl = _pipeline(tmp_path)
    r = OcrPageResult(doc_id="doc001", part_id="vol1", page_number=1, engine_id="ndlkotenocr-full",
                      ocr_results=[block("学欠", "b1"), block("王戎", "b2")])
    pl._save_ocr_result("doc001", "vol1", 1, r)
    data = _saved(tmp_path)
    jsonschema.validate(data, SCHEMA)
    assert data["ocr_results"][0]["lines"][0]["text"] == "學欠"
    blocks = data["ocr_config"]["script_normalize"]["blocks"]
    assert set(blocks) == {"b1"}  # 바꿀 것도 보류할 것도 없는 b2 는 기록하지 않는다
    assert r.ocr_results[0]["lines"][0]["text"] == "學欠"  # 호출자도 바뀐 글자를 본다


def test_other_engine_untouched(tmp_path):
    pl = _pipeline(tmp_path)
    r = OcrPageResult(doc_id="doc001", part_id="vol1", page_number=1, engine_id="llm_vision",
                      ocr_results=[block("学問", "b1")])
    pl._save_ocr_result("doc001", "vol1", 1, r)
    data = _saved(tmp_path)
    assert data["ocr_results"][0]["lines"][0]["text"] == "学問"
    assert data["ocr_config"] is None


def test_partial_rerun_keeps_records_of_untouched_blocks(tmp_path):
    pl = _pipeline(tmp_path)
    first = OcrPageResult(doc_id="doc001", part_id="vol1", page_number=1, engine_id="ndlkotenocr",
                          ocr_results=[block("学", "b1"), block("伝", "b2")])
    pl._save_ocr_result("doc001", "vol1", 1, first)
    # b2 만 다른 엔진으로 다시 인식 — b2 기록은 사라지고 b1 기록은 남아야 한다
    again = OcrPageResult(doc_id="doc001", part_id="vol1", page_number=1, engine_id="llm_vision",
                          ocr_results=[block("傳", "b2")])
    pl._save_ocr_result("doc001", "vol1", 1, again, merge_with_existing=True)
    data = _saved(tmp_path)
    jsonschema.validate(data, SCHEMA)
    assert set(data["ocr_config"]["script_normalize"]["blocks"]) == {"b1"}
    assert [x["lines"][0]["text"] for x in data["ocr_results"]] == ["學", "傳"]
