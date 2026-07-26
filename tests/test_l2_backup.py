"""OCR 결과 되돌리기 테스트 — 다시 돌렸는데 더 나빠졌을 때.

왜 이 테스트가 있는가:
    원본 저장소는 Git으로 관리되지만 **L2_ocr/는 커밋되지 않는다.**
    그래서 OCR 결과는 «되돌리기»의 대상이 아니었다.

    문제가 되는 자리는 하나다 — 모델을 바꾸거나 레이아웃을 고쳐 다시
    돌리는 것이 추출 흐름의 일부인데(D-057), 그 결과가 이전만 못해도
    돌아갈 길이 없으면 «다시 돌려 보기»가 위험한 선택이 된다.
"""

import json

import pytest

from ocr.l2_backup import has_backup, restore_backup, save_backup


@pytest.fixture()
def doc(tmp_path):
    d = tmp_path / "doc"
    (d / "L2_ocr").mkdir(parents=True)
    return d


def _write(doc, page, text):
    (doc / "L2_ocr" / f"vol1_page_{page:03d}.json").write_text(
        json.dumps(
            {
                "part_id": "vol1",
                "page_number": page,
                "ocr_results": [{"layout_block_id": "p01_b01", "lines": [{"text": text}]}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _read(doc, page):
    d = json.loads((doc / "L2_ocr" / f"vol1_page_{page:03d}.json").read_text("utf-8"))
    return d["ocr_results"][0]["lines"][0]["text"]


def test_backup_then_restore(doc):
    """덮어쓰기 전에 남긴 것으로 돌아간다."""
    _write(doc, 1, "처음 결과")
    assert save_backup(doc, "vol1", 1) is True
    assert has_backup(doc, "vol1", 1) is True

    _write(doc, 1, "다시 돌린 결과 (더 나쁨)")
    assert _read(doc, 1) == "다시 돌린 결과 (더 나쁨)"

    assert restore_backup(doc, "vol1", 1) is True
    assert _read(doc, 1) == "처음 결과"


def test_restore_swaps_so_you_can_go_back(doc):
    """되돌린 뒤 한 번 더 누르면 원래대로 — 두 상태를 오갈 수 있다.

    어느 쪽이 나은지 비교하다 돌아올 수 있어야 한다.
    """
    _write(doc, 1, "A")
    save_backup(doc, "vol1", 1)
    _write(doc, 1, "B")

    restore_backup(doc, "vol1", 1)
    assert _read(doc, 1) == "A"
    restore_backup(doc, "vol1", 1)
    assert _read(doc, 1) == "B"


def test_empty_result_is_not_backed_up(doc):
    """«돌았는데 아무것도 못 읽은» 쪽은 백업하지 않는다.

    그런 쪽으로 되돌릴 이유가 없고, 남기면 되돌리기 버튼이 쓸모없는
    곳에도 뜬다.
    """
    (doc / "L2_ocr" / "vol1_page_001.json").write_text(
        json.dumps({"part_id": "vol1", "page_number": 1, "ocr_results": []}),
        encoding="utf-8",
    )
    assert save_backup(doc, "vol1", 1) is False
    assert has_backup(doc, "vol1", 1) is False


def test_missing_source_is_not_backed_up(doc):
    """L2 자체가 없으면 백업할 것도 없다."""
    assert save_backup(doc, "vol1", 9) is False


def test_restore_without_backup_returns_false(doc):
    """백업이 없으면 조용히 실패하지 않고 False를 준다."""
    _write(doc, 1, "현재")
    assert restore_backup(doc, "vol1", 1) is False
    assert _read(doc, 1) == "현재", "실패했는데 내용이 바뀌었다"


def test_backup_keeps_one_generation(doc):
    """한 세대만 남긴다 — 이력을 다 남기면 저장소가 부푼다."""
    _write(doc, 1, "1세대")
    save_backup(doc, "vol1", 1)
    _write(doc, 1, "2세대")
    save_backup(doc, "vol1", 1)
    _write(doc, 1, "3세대")

    restore_backup(doc, "vol1", 1)
    assert _read(doc, 1) == "2세대", "가장 최근 것으로만 돌아간다"


def test_backup_lives_under_l2(doc):
    """백업은 L2_ocr 안에 둔다 — 문헌을 옮기거나 지울 때 함께 따라간다."""
    _write(doc, 1, "본문")
    save_backup(doc, "vol1", 1)
    assert (doc / "L2_ocr" / ".backup" / "vol1_page_001.json").exists()
