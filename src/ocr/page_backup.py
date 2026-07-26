"""쪽의 작업 결과를 덮어쓰기 전에 한 벌 남긴다 (되돌리기용).

무엇을 푸는가:
    원본 저장소는 Git으로 관리되지만 **L2_ocr/·L3_layout/·exports/는
    커밋되지 않는다.** 그래서 OCR 결과는 «되돌리기»의 대상이 아니었다.

    문제가 되는 자리는 하나다 — **다시 돌렸는데 더 나빠졌을 때.**
    모델을 바꿔 보거나 레이아웃을 고쳐 다시 돌리는 것이 추출 흐름의
    일부인데(D-057), 그 결과가 이전만 못해도 돌아갈 방법이 없었다.

왜 L2만이 아닌가:
    처음에는 L2(OCR 결과)만 남겼다. 그런데 배치는 `fill_text_layer`로
    **L4 교정 텍스트도 덮어쓴다**(교정 탭이 L4를 읽으므로 채워 줘야 한다).
    즉 손으로 고친 교정이 재실행 때 사라진다.

    L2만 되돌리면 «OCR은 예전 것인데 교정은 사라진» 어긋난 상태가 된다.
    한 쪽의 작업 결과는 함께 움직여야 하므로 세 가지를 같이 남긴다.

        L2_ocr/{part}_page_NNN.json                            OCR 결과
        L4_text/pages/{part}_page_NNN.txt                      교정 텍스트
        L4_text/corrections/{part}_page_NNN_corrections.json   교정 기록

규칙은 하나다 — **저장할 때마다 직전 상태를 남긴다**:
    OCR 실행이든 교정 저장이든 가리지 않는다. 그래서 되돌리기는 언제나
    «방금 저장한 것 취소»다. `Ctrl+Z` 한 번과 같다.

        교정 저장  →  되돌리기 = 그 교정만 취소
        OCR 실행   →  되돌리기 = 그 실행만 취소

    처음에는 OCR에만 백업을 뒀는데, 그러면 되돌리기가 언제 눌렀느냐에
    따라 한 단계가 되기도 두 단계가 되기도 했다(실측 2026-07-26:
    3차 OCR 뒤 교정하고 눌렀더니 2차 OCR로 갔다). 규칙이 둘이면
    사용자도 설명하는 쪽도 매번 조건을 따져야 한다.

    **두 번은 안 된다.** 남기는 것은 직전 하나뿐이다. L2는 쪽마다
    수십~수백 KB이고 저장할 때마다 통째로 바뀌므로 세대를 쌓으면
    저장소가 빠르게 부푼다.

어디에 두는가:
    <문헌>/.page_backup/{part_id}_page_NNN/
    문헌 안에 두므로 옮기거나 지울 때 함께 따라간다.
    점(.)으로 시작해 목록에서 눈에 띄지 않는다.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

BACKUP_DIRNAME = ".page_backup"


def _members(doc_path: Path, part_id: str, page_number: int) -> list[tuple[Path, str]]:
    """한 쪽의 작업 결과를 이루는 파일들. (원본 경로, 백업 안에서 쓸 이름)

    백업 안에서 이름을 단순화하는 이유: 원본 경로 구조를 그대로 흉내 내면
    되돌릴 때 어느 파일이 어디로 가는지 다시 계산해야 한다. 짧은 이름과
    복원 위치를 한 자리에서 짝지어 두면 그 계산이 필요 없다.
    """
    stem = f"{part_id}_page_{page_number:03d}"
    return [
        (doc_path / "L2_ocr" / f"{stem}.json", "l2.json"),
        (doc_path / "L4_text" / "pages" / f"{stem}.txt", "l4_text.txt"),
        (
            doc_path / "L4_text" / "corrections" / f"{stem}_corrections.json",
            "l4_corrections.json",
        ),
    ]


def backup_dir(doc_path: str | Path, part_id: str, page_number: int) -> Path:
    """이 쪽의 백업 디렉터리."""
    return Path(doc_path) / BACKUP_DIRNAME / f"{part_id}_page_{page_number:03d}"


def has_backup(doc_path: str | Path, part_id: str, page_number: int) -> bool:
    """되돌릴 수 있는 백업이 있는지.

    L2가 들어 있을 때만 True다 — OCR 결과 없이 교정 텍스트만 되돌리는 것은
    의미가 없다(무엇을 고친 것인지 알 수 없게 된다).
    """
    return (backup_dir(doc_path, part_id, page_number) / "l2.json").exists()


def save_backup(doc_path: str | Path, part_id: str, page_number: int) -> bool:
    """지금 결과를 백업해 둔다. 덮어쓰기 **직전에** 부른다.

    입력: doc_path, part_id, page_number — 1-based.
    출력: 백업했으면 True. OCR 결과가 없거나 비어 있으면 False.

    왜 빈 결과는 백업하지 않는가:
        «돌았는데 아무것도 못 읽은» 쪽으로 되돌릴 이유가 없다.
        그런 쪽까지 남기면 되돌리기 버튼이 쓸모없는 곳에도 뜬다.
    """
    from ocr.layout_staleness import ocr_path, read_page_json

    doc_path = Path(doc_path)
    data = read_page_json(ocr_path(doc_path, part_id, page_number))
    if not data or not data.get("ocr_results"):
        return False

    dest_dir = backup_dir(doc_path, part_id, page_number)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        for src, name in _members(doc_path, part_id, page_number):
            dest = dest_dir / name
            if src.exists():
                shutil.copy2(src, dest)
            elif dest.exists():
                # 이번에는 없는 파일이 지난 백업에 남아 있으면 지운다.
                # 안 지우면 되돌릴 때 «그때 없던 파일»이 되살아난다.
                dest.unlink()
    except OSError as e:
        # 백업 실패로 OCR을 막지는 않는다. 다만 되돌릴 수 없게 되므로 남긴다.
        logger.warning(f"쪽 백업 실패({page_number}쪽): {e}")
        return False
    return True


def restore_backup(doc_path: str | Path, part_id: str, page_number: int) -> bool:
    """백업을 되돌린다.

    입력: doc_path, part_id, page_number.
    출력: 되돌렸으면 True. 백업이 없으면 False.

    **방금 저장한 것 하나만 취소한다.** 두 번은 안 된다 (모듈 설명 참조).

    되돌린 뒤 백업은 **지우지 않는다.** 되돌리기를 한 번 더 눌러 원래대로
    가고 싶어질 수 있는데, 지워 버리면 그 길이 막힌다. 대신 되돌리는
    순간의 현재 결과를 새 백업으로 바꿔 두어 **두 상태를 오갈 수 있게** 한다.
    """
    doc_path = Path(doc_path)
    if not has_backup(doc_path, part_id, page_number):
        return False

    dest_dir = backup_dir(doc_path, part_id, page_number)
    try:
        for live, name in _members(doc_path, part_id, page_number):
            saved = dest_dir / name
            # 지금 것을 들고, 백업을 제자리에 놓고, 들고 있던 것을 백업으로.
            holding = live.read_bytes() if live.exists() else None
            if saved.exists():
                live.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(saved, live)
            elif live.exists():
                # 백업 시점에 없던 파일이다. 그 상태로 되돌리려면 지워야 한다.
                live.unlink()

            if holding is not None:
                saved.parent.mkdir(parents=True, exist_ok=True)
                saved.write_bytes(holding)
            elif saved.exists():
                saved.unlink()
    except OSError as e:
        logger.warning(f"쪽 되돌리기 실패({page_number}쪽): {e}")
        return False
    return True
