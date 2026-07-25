"""부분 재-OCR 판정 테스트 — 레이아웃을 다시 잡은 쪽만 골라내는가.

왜 이 테스트가 있는가:
    논문 수십 쪽을 한 번에 OCR 한 뒤, 결과가 나쁜 몇 쪽만 레이아웃 탭에서
    영역을 나누어 다시 돌리는 것이 실제 작업 흐름이다. 이때 두 방향의
    오판이 각각 다른 대가를 치른다.

      - 바뀐 쪽을 «안 바뀌었다»고 판정 → 손으로 고친 작업이 반영되지 않는다.
        사용자는 왜 결과가 그대로인지 알 수 없다.
      - 안 바뀐 쪽을 «바뀌었다»고 판정 → 쪽마다 LLM 호출이 다시 나간다.
        300쪽이면 실제 돈이 나간다.

    그래서 «확실할 때만 다시 돈다»가 설계 원칙이고, 이 테스트가 그 경계를
    고정한다.
"""

import json

import pytest

from ocr.layout_staleness import (
    find_stale_pages,
    has_ocr_result,
    layout_changed_since_ocr,
)


@pytest.fixture()
def doc(tmp_path):
    """L2/L3 디렉터리를 갖춘 빈 문헌 폴더."""
    d = tmp_path / "doc_test"
    (d / "L2_ocr").mkdir(parents=True)
    (d / "L3_layout").mkdir(parents=True)
    return d


def _write_layout(doc, page: int, block_ids: list[str], *, skip: set[str] = frozenset()):
    """L3 레이아웃을 쓴다. block_ids 순서대로 블록을 만든다."""
    path = doc / "L3_layout" / f"vol1_page_{page:03d}.json"
    path.write_text(
        json.dumps(
            {
                "part_id": "vol1",
                "page_number": page,
                "image_width": 1000,
                "image_height": 1400,
                "blocks": [
                    {
                        "block_id": bid,
                        "block_type": "main_text",
                        "bbox": [0, 0, 1000, 1400],
                        "reading_order": i + 1,
                        "skip": bid in skip,
                    }
                    for i, bid in enumerate(block_ids)
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _write_ocr(doc, page: int, block_ids: list[str | None], *, lines: int = 3):
    """L2 OCR 결과를 쓴다. block_ids에 None을 넣으면 경로 B(레이아웃 전 OCR)."""
    path = doc / "L2_ocr" / f"vol1_page_{page:03d}.json"
    path.write_text(
        json.dumps(
            {
                "part_id": "vol1",
                "page_number": page,
                "ocr_engine": "llm_vision",
                "ocr_results": [
                    {
                        "layout_block_id": bid,
                        "lines": [{"text": f"{bid} 본문 {i}"} for i in range(lines)],
                    }
                    for bid in block_ids
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
#  has_ocr_result — 재개 판정
# ---------------------------------------------------------------------------


def test_no_l2_means_not_done(doc):
    """L2 파일이 없으면 아직 안 한 쪽이다."""
    assert has_ocr_result(doc, "vol1", 1) is False


def test_l2_with_results_means_done(doc):
    """결과가 있으면 한 쪽이다."""
    _write_ocr(doc, 1, ["p01_b01"])
    assert has_ocr_result(doc, "vol1", 1) is True


def test_empty_l2_means_not_done(doc):
    """파일만 있고 결과가 비면 다시 돌려야 한다.

    실패한 쪽을 영원히 건너뛰면 사용자는 왜 그 쪽만 비었는지 알 수 없다.
    """
    _write_ocr(doc, 1, [])
    assert has_ocr_result(doc, "vol1", 1) is False


def test_corrupt_l2_means_not_done(doc):
    """깨진 JSON은 «안 한 것»으로 본다 (다시 돌면 고쳐진다)."""
    (doc / "L2_ocr" / "vol1_page_001.json").write_text("{ 깨짐", encoding="utf-8")
    assert has_ocr_result(doc, "vol1", 1) is False


# ---------------------------------------------------------------------------
#  layout_changed_since_ocr — 블록 집합 비교
# ---------------------------------------------------------------------------


def test_same_blocks_not_stale(doc):
    """같은 블록으로 돌린 결과는 다시 돌 이유가 없다."""
    _write_layout(doc, 1, ["p01_b01"])
    _write_ocr(doc, 1, ["p01_b01"])
    changed, why = layout_changed_since_ocr(doc, "vol1", 1)
    assert changed is False
    assert why == ""


def test_split_into_more_blocks_is_stale(doc):
    """전면 블록 1개 → 3개로 나누면 다시 돌아야 한다. (핵심 시나리오)"""
    _write_ocr(doc, 1, ["p01_b01"])
    _write_layout(doc, 1, ["p01_b01", "p01_b02", "p01_b03"])
    changed, why = layout_changed_since_ocr(doc, "vol1", 1)
    assert changed is True
    assert "1개" in why and "3개" in why


def test_merged_into_fewer_blocks_is_stale(doc):
    """반대 방향(여러 개 → 1개)도 마찬가지다."""
    _write_ocr(doc, 1, ["p01_b01", "p01_b02"])
    _write_layout(doc, 1, ["p01_b01"])
    changed, _ = layout_changed_since_ocr(doc, "vol1", 1)
    assert changed is True


def test_skip_blocks_excluded_from_comparison(doc):
    """skip=True 블록은 OCR이 건너뛰므로 비교에서 빠진다.

    포함시키면 집합이 영원히 어긋나 매번 다시 돈다.
    """
    _write_ocr(doc, 1, ["p01_b01"])
    _write_layout(doc, 1, ["p01_b01", "p01_b02"], skip={"p01_b02"})
    changed, _ = layout_changed_since_ocr(doc, "vol1", 1)
    assert changed is False


def test_null_block_id_is_not_compared(doc):
    """경로 B(레이아웃 전 페이지 전체 OCR)는 비교 대상이 아니다.

    layout_block_id가 null이면 어느 블록을 읽은 것인지 알 수 없으므로
    «바뀌었다»고 단정하지 않는다 — 확실할 때만 다시 돈다.
    """
    _write_ocr(doc, 1, [None])
    _write_layout(doc, 1, ["p01_b01", "p01_b02"])
    changed, _ = layout_changed_since_ocr(doc, "vol1", 1, use_mtime=False)
    assert changed is False


def test_no_layout_is_not_stale(doc):
    """레이아웃이 없으면 전면 블록이 새로 생길 것이므로 판정하지 않는다."""
    _write_ocr(doc, 1, ["p01_b01"])
    changed, _ = layout_changed_since_ocr(doc, "vol1", 1)
    assert changed is False


def test_no_ocr_is_not_stale(doc):
    """OCR 결과가 없으면 애초에 건너뛸 쪽이 아니다."""
    _write_layout(doc, 1, ["p01_b01"])
    changed, _ = layout_changed_since_ocr(doc, "vol1", 1)
    assert changed is False


# ---------------------------------------------------------------------------
#  파일 시각 보조 판정
# ---------------------------------------------------------------------------


def test_layout_saved_later_is_stale(doc):
    """블록 구성은 같은데 영역만 조정한 경우는 시각으로 잡는다."""
    import os

    _write_ocr(doc, 1, ["p01_b01"])
    l3 = _write_layout(doc, 1, ["p01_b01"])
    # L3를 넉넉히 나중에 저장한 것으로 만든다 (여유 5초를 넘겨야 한다).
    l2_mtime = (doc / "L2_ocr" / "vol1_page_001.json").stat().st_mtime
    os.utime(l3, (l2_mtime + 60, l2_mtime + 60))

    changed, why = layout_changed_since_ocr(doc, "vol1", 1)
    assert changed is True
    assert "수정" in why


def test_mtime_tolerance_absorbs_same_run(doc):
    """한 번의 실행에서 L3 → L2를 잇달아 쓴 경우는 다시 돌지 않는다.

    파이프라인은 L3를 읽은 직후 L2를 쓴다. 시각이 1초 안쪽으로 붙으므로
    여유가 없으면 멀쩡한 쪽이 매번 다시 돈다 (= 불필요한 LLM 호출).
    """
    import os

    _write_ocr(doc, 1, ["p01_b01"])
    l3 = _write_layout(doc, 1, ["p01_b01"])
    l2_mtime = (doc / "L2_ocr" / "vol1_page_001.json").stat().st_mtime
    os.utime(l3, (l2_mtime + 1.0, l2_mtime + 1.0))

    changed, _ = layout_changed_since_ocr(doc, "vol1", 1)
    assert changed is False


def test_use_mtime_false_disables_time_check(doc):
    """시각을 믿을 수 없는 상황(git으로 다시 받은 직후)에서는 끌 수 있다."""
    import os

    _write_ocr(doc, 1, ["p01_b01"])
    l3 = _write_layout(doc, 1, ["p01_b01"])
    l2_mtime = (doc / "L2_ocr" / "vol1_page_001.json").stat().st_mtime
    os.utime(l3, (l2_mtime + 600, l2_mtime + 600))

    changed, _ = layout_changed_since_ocr(doc, "vol1", 1, use_mtime=False)
    assert changed is False


# ---------------------------------------------------------------------------
#  find_stale_pages — 여러 쪽에서 고른 쪽만
# ---------------------------------------------------------------------------


def test_finds_only_changed_pages(doc):
    """15쪽 중 12쪽만 고쳤으면 [12]만 나와야 한다. (사용자 시나리오 그대로)"""
    for page in range(1, 16):
        _write_ocr(doc, page, [f"p{page:02d}_b01"])
        _write_layout(doc, page, [f"p{page:02d}_b01"])

    # 12쪽만 2단으로 나눴다.
    _write_layout(doc, 12, ["p12_b01", "p12_b02"])

    assert find_stale_pages(doc, "vol1", list(range(1, 16))) == [12]
