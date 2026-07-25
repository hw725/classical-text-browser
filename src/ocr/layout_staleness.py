"""레이아웃을 다시 잡은 쪽을 골라낸다 (부분 재-OCR 판정).

무엇을 푸는가:
    논문 수십 쪽을 한 번에 OCR 했는데 그 중 몇 쪽만 결과가 나쁠 수 있다.
    2단 조판, 한시 원문과 번역이 나란한 쪽, 표가 있는 쪽이 그렇다.
    이런 쪽은 레이아웃 탭에서 영역을 손으로 나눈 뒤 **그 쪽만** 다시
    돌려야 한다. 그런데 배치 OCR은 "L2 결과가 있으면 건너뛴다"가 기본이라
    (중단 후 이어 돌리기 위해) 손으로 고친 쪽도 그대로 건너뛴다.

    사용자가 매번 "몇 쪽을 고쳤는지" 기억해 쪽 번호를 입력하게 만드는 대신,
    **레이아웃이 OCR 이후에 바뀐 쪽을 기계가 찾아낸다.**

어떻게 판정하는가:
    L2 OCR 결과의 각 OcrResult에는 어느 LayoutBlock을 읽은 것인지가
    `layout_block_id`로 남아 있다(ocr_page.schema.json). 이 집합과 현재
    L3 레이아웃의 `block_id` 집합을 비교하면 된다.

        전면 블록 1개로 돌렸다        → L2: {p03_b01}
        레이아웃 탭에서 3개로 나눴다  → L3: {p03_b01, p03_b02, p03_b03}
        → 집합이 다르다 → 이 쪽은 다시 돌려야 한다

    블록 개수는 그대로인데 bbox만 조정한 경우는 집합 비교로 잡히지 않으므로
    파일 수정 시각을 보조로 쓴다(L3가 L2보다 나중에 저장됐는가).

왜 스키마에 타임스탬프를 넣지 않는가:
    layout_page / ocr_page 스키마는 둘 다 `additionalProperties: false`다.
    시각 필드를 넣으려면 스키마를 고쳐야 하고, 그러면 기존 저장소의 데이터와
    교환 형식(D-018)에 영향이 간다. 판정에 필요한 정보가 **이미 저장된
    데이터 안에 있으므로** 스키마를 건드리지 않는다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 파일 수정 시각 비교에 두는 여유(초).
#
# 왜 여유가 필요한가: OCR 파이프라인은 L3를 읽은 직후 L2를 쓰므로 두 파일의
# 시각이 1초 안쪽으로 붙는다. 파일시스템 시각 해상도와 저장 순서 때문에
# L3가 근소하게 나중으로 찍히는 일이 생기는데, 여유가 없으면 "레이아웃이
# 바뀌었다"고 오판해 멀쩡한 쪽을 다시 돌린다(LLM 호출 = 비용).
MTIME_TOLERANCE_SEC = 5.0


def layout_path(doc_path: Path, part_id: str, page_number: int) -> Path:
    """이 쪽의 L3 레이아웃 파일 경로."""
    return Path(doc_path) / "L3_layout" / f"{part_id}_page_{page_number:03d}.json"


def ocr_path(doc_path: Path, part_id: str, page_number: int) -> Path:
    """이 쪽의 L2 OCR 결과 파일 경로."""
    return Path(doc_path) / "L2_ocr" / f"{part_id}_page_{page_number:03d}.json"


def _read_json(path: Path) -> dict | None:
    """JSON 파일을 읽는다. 없거나 깨졌으면 None."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def has_ocr_result(doc_path: Path, part_id: str, page_number: int) -> bool:
    """이 쪽에 쓸 만한 OCR 결과가 있는지 확인한다 (재개 판단).

    입력: doc_path — 문헌 디렉토리. part_id. page_number — 1-based.
    출력: L2 파일이 있고 ocr_results가 비어 있지 않으면 True.

    파일만 있고 내용이 비어 있으면 False다 — 실패한 쪽을 영원히
    건너뛰게 되면 사용자는 왜 그 쪽만 비었는지 알 수 없다.
    """
    data = _read_json(ocr_path(doc_path, part_id, page_number))
    return bool(data and data.get("ocr_results"))


def _ocr_block_ids(ocr_data: dict) -> set[str]:
    """L2 결과가 읽었던 LayoutBlock의 id 집합.

    layout_block_id가 null인 항목(경로 B — 레이아웃 전에 페이지 전체를
    OCR 한 경우)은 비교 대상이 아니므로 뺀다.
    """
    ids = set()
    for result in ocr_data.get("ocr_results") or []:
        block_id = result.get("layout_block_id")
        if block_id:
            ids.add(block_id)
    return ids


def _layout_block_ids(layout_data: dict) -> set[str]:
    """현재 L3 레이아웃의 block_id 집합. skip=True인 블록은 뺀다.

    skip 블록은 OCR이 건너뛰므로 L2에 결과가 남지 않는다. 포함시키면
    집합이 항상 어긋나 매번 다시 돌게 된다.
    """
    ids = set()
    for block in layout_data.get("blocks") or []:
        if block.get("skip"):
            continue
        block_id = block.get("block_id")
        if block_id:
            ids.add(block_id)
    return ids


def layout_changed_since_ocr(
    doc_path: str | Path,
    part_id: str,
    page_number: int,
    *,
    use_mtime: bool = True,
) -> tuple[bool, str]:
    """이 쪽의 레이아웃이 OCR 이후에 바뀌었는지 판정한다.

    입력:
        doc_path — 문헌 디렉토리. part_id — 권 식별자. page_number — 1-based.
        use_mtime — 파일 수정 시각 비교를 함께 쓸지. git으로 저장소를 다시
            받아 온 직후처럼 시각을 믿을 수 없는 상황에서는 끈다.
    출력: (바뀌었는가, 사람이 읽을 사유)
        바뀌지 않았으면 (False, "").

    판정하지 못하는 경우는 False로 둔다. "바뀌었다"고 잘못 말하면 멀쩡한
    쪽에 LLM 호출이 다시 나가므로, 확실할 때만 True를 돌려준다.
    """
    doc_path = Path(doc_path)
    l3 = layout_path(doc_path, part_id, page_number)
    l2 = ocr_path(doc_path, part_id, page_number)

    layout_data = _read_json(l3)
    ocr_data = _read_json(l2)
    if layout_data is None or ocr_data is None:
        # 레이아웃이 없으면 전면 블록이 새로 생길 것이고,
        # OCR 결과가 없으면 애초에 건너뛸 쪽이 아니다.
        return False, ""

    current = _layout_block_ids(layout_data)
    used = _ocr_block_ids(ocr_data)

    if current and used and current != used:
        return True, (
            f"레이아웃이 바뀌었습니다 "
            f"(OCR 당시 블록 {len(used)}개 → 현재 {len(current)}개)."
        )

    if not use_mtime:
        return False, ""

    # 블록 구성은 같지만 영역(bbox)만 조정했을 수 있다. 이것은 저장된
    # 데이터로는 알 수 없으므로 파일 시각으로 본다.
    try:
        if l3.stat().st_mtime > l2.stat().st_mtime + MTIME_TOLERANCE_SEC:
            return True, "레이아웃을 OCR 이후에 수정했습니다."
    except OSError:
        pass

    return False, ""


def find_stale_pages(
    doc_path: str | Path,
    part_id: str,
    pages: list[int],
    *,
    use_mtime: bool = True,
) -> list[int]:
    """주어진 쪽들 중 레이아웃이 OCR 이후에 바뀐 쪽만 골라낸다.

    입력: doc_path, part_id, pages — 검사할 쪽 번호 목록.
    출력: 다시 돌려야 하는 쪽 번호 목록 (오름차순).

    배치를 돌리기 전에 «몇 쪽이 다시 도는지»를 사용자에게 미리 보여 주는
    용도다. 비용이 걸린 일은 실행 전에 규모를 알 수 있어야 한다.
    """
    stale = []
    for page_number in pages:
        changed, _ = layout_changed_since_ocr(
            doc_path, part_id, page_number, use_mtime=use_mtime
        )
        if changed:
            stale.append(page_number)
    return sorted(stale)
