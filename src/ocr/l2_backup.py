"""OCR 결과를 덮어쓰기 전에 한 벌 남긴다 (되돌리기용).

무엇을 푸는가:
    원본 저장소는 Git으로 관리되지만 **L2_ocr/·L3_layout/·exports/는
    추적되지 않는다**(.gitignore가 아니라 애초에 커밋하지 않는다).
    그래서 OCR 결과는 «되돌리기»의 대상이 아니다.

    문제가 되는 자리는 하나다 — **다시 돌렸는데 더 나빠졌을 때.**
    모델을 바꿔 보거나 레이아웃을 고쳐 다시 돌리는 것이 추출 흐름의
    일부인데(D-057), 그 결과가 이전만 못해도 돌아갈 방법이 없었다.

왜 Git이 아니라 파일 한 벌인가:
    L2는 쪽마다 수십~수백 KB의 JSON이고 OCR을 돌릴 때마다 통째로 바뀐다.
    이력을 다 남기면 저장소가 빠르게 부푼다. 실제로 필요한 것은
    «방금 돌리기 직전»뿐이므로 **한 세대만** 남긴다.

    사용자 표현 그대로다 — "그냥 로컬에다가 json으로 백업해두는 편이 심플".

어디에 두는가:
    <문헌>/L2_ocr/.backup/{part_id}_page_NNN.json
    L2_ocr 안에 두므로 문헌을 옮기거나 지울 때 함께 따라간다.
    점(.)으로 시작해 목록에서 눈에 띄지 않는다.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

BACKUP_DIRNAME = ".backup"


def backup_path(doc_path: str | Path, part_id: str, page_number: int) -> Path:
    """이 쪽의 백업 파일 경로."""
    return (
        Path(doc_path)
        / "L2_ocr"
        / BACKUP_DIRNAME
        / f"{part_id}_page_{page_number:03d}.json"
    )


def has_backup(doc_path: str | Path, part_id: str, page_number: int) -> bool:
    """되돌릴 수 있는 백업이 있는지."""
    return backup_path(doc_path, part_id, page_number).exists()


def save_backup(doc_path: str | Path, part_id: str, page_number: int) -> bool:
    """지금 L2를 백업해 둔다. 덮어쓰기 **직전에** 부른다.

    입력: doc_path, part_id, page_number — 1-based.
    출력: 백업했으면 True. 원본이 없거나 비어 있으면 False.

    왜 빈 결과는 백업하지 않는가:
        «돌았는데 아무것도 못 읽은» 쪽으로 되돌릴 이유가 없다.
        그런 쪽까지 남기면 되돌리기 버튼이 쓸모없는 곳에도 뜬다.
    """
    from ocr.layout_staleness import ocr_path, read_page_json

    src = ocr_path(Path(doc_path), part_id, page_number)
    data = read_page_json(src)
    if not data or not data.get("ocr_results"):
        return False

    dest = backup_path(doc_path, part_id, page_number)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # 한 세대만 남긴다 — 이전 백업은 그대로 덮는다.
        shutil.copy2(src, dest)
    except OSError as e:
        # 백업 실패로 OCR을 막지는 않는다. 다만 되돌릴 수 없게 되므로 남긴다.
        logger.warning(f"L2 백업 실패({page_number}쪽): {e}")
        return False
    return True


def restore_backup(doc_path: str | Path, part_id: str, page_number: int) -> bool:
    """백업을 되돌린다.

    입력: doc_path, part_id, page_number.
    출력: 되돌렸으면 True. 백업이 없으면 False.

    되돌린 뒤 백업은 **지우지 않는다.** 되돌리기를 한 번 더 눌러 원래대로
    가고 싶어질 수 있는데, 지워 버리면 그 길이 막힌다. 대신 되돌리는
    순간의 현재 결과를 새 백업으로 바꿔 두어 **두 상태를 오갈 수 있게** 한다.
    """
    from ocr.layout_staleness import ocr_path

    src = backup_path(doc_path, part_id, page_number)
    if not src.exists():
        return False

    current = ocr_path(Path(doc_path), part_id, page_number)
    try:
        # 지금 것을 임시로 들고, 백업을 제자리에 놓고, 들고 있던 것을 백업으로.
        holding = current.read_bytes() if current.exists() else None
        current.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, current)
        if holding is not None:
            src.write_bytes(holding)
    except OSError as e:
        logger.warning(f"L2 되돌리기 실패({page_number}쪽): {e}")
        return False
    return True
