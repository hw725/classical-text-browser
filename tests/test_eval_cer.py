"""CER 평가 하네스 테스트 (D-084).

무엇을 고정하는가:
  - CER 계산: 불일치·삽입·누락을 정답 글자 수로 나눈다. 공백·줄바꿈은 세지 않는다.
  - strict 이체자는 오류가 아니고, loose 힌트 관계는 오류다 (D-080 층을 따른다)
  - L4가 없는 쪽은 측정 불가로 건너뛴다. 교정 초안이 있으면 초안 CER도 낸다
  - 요약은 엔진별 글자 수 가중 평균이다
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.alignment import TieredVariantDicts, VariantCharDict  # noqa: E402
from ocr.eval_cer import compute_cer, evaluate_part, format_table  # noqa: E402


def _dict(tmp_path, name, variants, tier=None):
    data = {"variants": variants}
    if tier:
        data["_tier"] = tier
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return VariantCharDict(str(p))


class TestComputeCer:
    def test_identical(self):
        assert compute_cer("王戎簡要", "王戎簡要") == 0.0

    def test_whitespace_ignored(self):
        assert compute_cer("王戎\n簡要", "王戎 簡要") == 0.0

    def test_errors_counted(self):
        # 1 불일치(裴→表) + 1 누락(通) → 2/4
        assert compute_cer("表楷清", "裴楷清通") == 0.5

    def test_empty_reference(self):
        assert compute_cer("甲", "") is None

    def test_variant_tiers(self, tmp_path):
        strict = _dict(tmp_path, "s", {"說": ["説"], "説": ["說"]})
        loose = _dict(tmp_path, "l", {"丘": ["业"], "业": ["丘"]}, tier="loose")
        bundle = TieredVariantDicts([strict, loose])
        assert compute_cer("説丘", "說业", bundle) == 0.5  # 説/說은 일치, 业/丘는 오류


def _library(tmp_path):
    doc = tmp_path / "documents" / "d1"
    (doc / "L2_ocr").mkdir(parents=True)
    (doc / "L4_text" / "pages").mkdir(parents=True)
    (doc / "manifest.json").write_text(
        json.dumps({"document_id": "d1", "title": "T"}), encoding="utf-8"
    )

    def l2(page, engine, texts):
        (doc / "L2_ocr" / f"v1_page_{page:03d}.json").write_text(
            json.dumps(
                {
                    "ocr_engine": engine,
                    "ocr_results": [
                        {"layout_block_id": f"b{i}", "lines": [{"text": t}]}
                        for i, t in enumerate(texts, 1)
                    ],
                }
            ),
            encoding="utf-8",
        )

    l2(1, "paddleocr", ["王戎簡要", "表楷清通"])  # 1 오류 / 8자
    (doc / "L4_text" / "pages" / "v1_page_001.txt").write_text(
        "王戎簡要\n裴楷清通", encoding="utf-8"
    )
    l2(2, "paddleocr", ["孔明卧龍"])  # L4 없음
    l2(3, "ndlocr", ["甲乙丙丁"])  # 2 오류 / 4자
    (doc / "L4_text" / "pages" / "v1_page_003.txt").write_text("甲乙戊己", encoding="utf-8")
    # 3쪽 교정 초안: b1을 정답으로 고친 것이 자동 수용됨
    (doc / "L4_text" / "correction_drafts").mkdir()
    (doc / "L4_text" / "correction_drafts" / "v1_page_003.json").write_text(
        json.dumps(
            {
                "mode": "fast",
                "blocks": [{"block_id": "b1", "corrected_text": "甲乙戊己", "accepted": True}],
            }
        ),
        encoding="utf-8",
    )
    return doc


class TestEvaluatePart:
    def test_report(self, tmp_path):
        doc = _library(tmp_path)
        report = evaluate_part(doc, "d1", "v1")
        by_page = {p.page: p for p in report.pages}
        assert by_page[1].l2_cer == 0.125 and by_page[1].engine == "paddleocr"
        assert by_page[2].l2_cer is None and "측정 불가" in by_page[2].note
        assert by_page[3].l2_cer == 0.5
        assert by_page[3].draft_cer == 0.0 and by_page[3].draft_mode == "fast"

        s = report.summary()
        assert s["measured_pages"] == 2 and s["skipped_pages"] == 1
        assert s["engines"]["paddleocr"]["cer"] == 0.125
        assert s["engines"]["ndlocr"]["cer"] == 0.5
        assert s["draft"]["cer"] == 0.0 and s["draft"]["pages"] == 1

    def test_page_filter_and_table(self, tmp_path):
        doc = _library(tmp_path)
        report = evaluate_part(doc, "d1", "v1", pages=[3])
        assert [p.page for p in report.pages] == [3]
        table = format_table(report)
        assert "ndlocr" in table and "50.0%" in table and "교정 초안" in table
        assert json.dumps(report.to_dict(), ensure_ascii=False)  # 직렬화 가능
