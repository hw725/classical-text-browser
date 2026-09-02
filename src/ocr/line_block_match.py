"""탐지된 행(LINE)을 L3 LayoutBlock에 배정한다 — 쪽 단위 OCR 엔진 공용 (D-086).

왜 따로 있는가:
    NDL 계열 엔진 셋(古典籍-Lite·TrOCR·NDLOCR-Lite)은 쪽 전체에서 행을 찾은 뒤
    그 행을 사용자가 그린 LayoutBlock에 나눠 담는다. 이 배정 규칙이 세 엔진에
    복사되어 있었고, 「어느 블록에도 안 들어가는 행은 가장 가까운 블록에 준다」는
    폴백 때문에 선택하지 않은 영역의 글자가 결과에 섞였다. 파이프라인은 그 부작용을
    막으려고 「블록이 쪽의 70% 이상을 덮을 때만 쪽 단위」라는 조건을 두었고, 그 결과
    대부분의 실제 작업(블록 몇 개만 그리거나 한 블록만 다시 돌리기)이 **블록 크롭**
    경로로 흘러 행 탐지기(RTMDet, 1280px 쪽 전체로 학습)가 좁은 크롭 위에서 돌았다.
    합성 세로쓰기 쪽 실측: 쪽 전체 CER 0.09 vs 열 크롭 0.45.

규칙:
    1. 행의 중심점이 들어가는 블록이 있으면 그중 겹침이 가장 큰 블록.
    2. 없으면 행 넓이의 min_overlap 이상이 들어가는 블록 중 가장 많이 겹치는 블록.
    3. 그래도 없으면 **버린다.** 가장 가까운 블록에 주지 않는다 — 사용자가 고르지 않은
       영역이기 때문이다. 이 규칙 덕에 파이프라인은 커버리지 조건 없이 언제나 쪽
       전체에 탐지를 돌릴 수 있다.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def intersection_area(a: list, b: list) -> float:
    """두 bbox([x1,y1,x2,y2])의 교집합 넓이. 겹치지 않으면 0."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    return float((ix2 - ix1) * (iy2 - iy1))


def match_lines_to_blocks(
    lines: list[dict],
    blocks: list[dict],
    min_overlap: float = 0.5,
) -> dict[str, list[dict]]:
    """행 목록을 블록 id별로 묶는다.

    입력:
      lines: [{"text": str, "bbox": [x1,y1,x2,y2], ...}, ...] — 쪽 픽셀 좌표
      blocks: L3 블록 목록 [{"block_id": str, "bbox": [x1,y1,x2,y2], "skip": bool}, ...]
      min_overlap: 중심점이 어느 블록에도 없을 때, 행 넓이 중 블록에 들어가는 비율의 하한
    출력:
      {block_id: [line, ...]} — 어느 블록에도 배정되지 않은 행은 빠진다.
      블록이 하나도 없으면 {"unmatched": lines} (예전 동작 유지 — 호출자가 전면 블록을 만든다).
    """
    valid = [
        b for b in blocks if not b.get("skip", False) and b.get("bbox") and len(b["bbox"]) == 4
    ]
    if not valid:
        return {"unmatched": list(lines)} if lines else {}

    result: dict[str, list[dict]] = {}
    dropped = 0
    for line in lines:
        lb = line.get("bbox")
        if not lb or len(lb) != 4:
            dropped += 1
            continue
        cx, cy = (lb[0] + lb[2]) / 2, (lb[1] + lb[3]) / 2
        line_area = max(1.0, float((lb[2] - lb[0]) * (lb[3] - lb[1])))

        best_id, best_score = None, -1.0
        # 1. 중심점을 품는 블록
        for b in valid:
            x1, y1, x2, y2 = b["bbox"]
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                score = intersection_area(lb, b["bbox"])
                if score > best_score:
                    best_id, best_score = b.get("block_id"), score
        # 2. 중심점은 밖이지만 행의 절반 이상이 들어가는 블록
        if best_id is None:
            for b in valid:
                ratio = intersection_area(lb, b["bbox"]) / line_area
                if ratio >= min_overlap and ratio > best_score:
                    best_id, best_score = b.get("block_id"), ratio
        if best_id is None:
            dropped += 1
            continue
        result.setdefault(best_id, []).append(line)

    if dropped:
        logger.debug(f"블록 밖 행 {dropped}개 제외 (선택하지 않은 영역)")
    return result
