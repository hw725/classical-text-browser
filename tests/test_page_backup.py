"""쪽 되돌리기 테스트 — 다시 돌렸는데 더 나빠졌을 때.

왜 이 테스트가 있는가:
    원본 저장소는 Git으로 관리되지만 **L2_ocr/는 커밋되지 않는다.**
    그래서 OCR 결과는 «되돌리기»의 대상이 아니었다.

    문제가 되는 자리는 하나다 — 모델을 바꾸거나 레이아웃을 고쳐 다시
    돌리는 것이 추출 흐름의 일부인데(D-057), 그 결과가 이전만 못해도
    돌아갈 길이 없으면 «다시 돌려 보기»가 위험한 선택이 된다.
"""

import json

import pytest

from ocr.page_backup import has_backup, restore_backup, save_backup


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


def test_backup_lives_under_document(doc):
    """백업은 문헌 안에 둔다 — 옮기거나 지울 때 함께 따라간다."""
    _write(doc, 1, "본문")
    save_backup(doc, "vol1", 1)
    assert (doc / ".page_backup" / "vol1_page_001" / "l2.json").exists()


def _write_l4(doc, page, text, corrections=None):
    """교정 텍스트와 교정 기록을 쓴다 (사람이 손댄 상태를 흉내낸다)."""
    pages = doc / "L4_text" / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    (pages / f"vol1_page_{page:03d}.txt").write_text(text, encoding="utf-8")
    if corrections is not None:
        corr = doc / "L4_text" / "corrections"
        corr.mkdir(parents=True, exist_ok=True)
        (corr / f"vol1_page_{page:03d}_corrections.json").write_text(
            json.dumps({"corrections": corrections}, ensure_ascii=False),
            encoding="utf-8",
        )


def _read_l4(doc, page):
    f = doc / "L4_text" / "pages" / f"vol1_page_{page:03d}.txt"
    return f.read_text(encoding="utf-8") if f.exists() else None


def test_manual_corrections_are_restored_too(doc):
    """손으로 고친 교정도 함께 되돌아온다.

    배치는 fill_text_layer로 **L4 교정 텍스트도 덮어쓴다**(교정 탭이 L4를
    읽으므로 채워 줘야 한다). L2만 되돌리면 «OCR은 예전 것인데 교정은
    사라진» 어긋난 상태가 된다.
    """
    _write(doc, 1, "OCR 원문 A")
    _write_l4(doc, 1, "사람이 고친 텍스트", corrections=[{"from": "A", "to": "B"}])
    assert save_backup(doc, "vol1", 1) is True

    # 다시 돌려 둘 다 덮였다
    _write(doc, 1, "OCR 원문 B")
    _write_l4(doc, 1, "OCR 원문 B")

    assert restore_backup(doc, "vol1", 1) is True
    assert _read(doc, 1) == "OCR 원문 A"
    assert _read_l4(doc, 1) == "사람이 고친 텍스트", "교정이 되돌아오지 않았다"
    corr = doc / "L4_text" / "corrections" / "vol1_page_001_corrections.json"
    assert corr.exists(), "교정 기록이 되돌아오지 않았다"


def test_files_absent_at_backup_time_are_removed_on_restore(doc):
    """백업 시점에 없던 파일은 되돌릴 때 사라져야 한다.

    안 그러면 «그때 없던 교정»이 되살아나 그 시점 상태와 달라진다.
    """
    _write(doc, 1, "OCR만 있던 시절")
    save_backup(doc, "vol1", 1)  # L4 없음

    _write_l4(doc, 1, "나중에 생긴 교정")
    assert _read_l4(doc, 1) == "나중에 생긴 교정"

    restore_backup(doc, "vol1", 1)
    assert _read_l4(doc, 1) is None, "백업 시점에 없던 파일이 남았다"

    # 한 번 더 되돌리면 다시 생긴다 (두 상태를 오간다)
    restore_backup(doc, "vol1", 1)
    assert _read_l4(doc, 1) == "나중에 생긴 교정"
