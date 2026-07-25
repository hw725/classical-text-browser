"""페이지 이미지에서 **글자가 있는 줄의 위치**만 찾아낸다 (인식 없이).

왜 이 모듈이 필요한가:
    LLM Vision은 이 저장소에서 국한문 혼용을 가장 잘 읽지만 좌표를 주지 않는다.
    그래서 텍스트 레이어를 입힐 때 글자를 원본 자리에 놓지 못하고 왼쪽 여백에
    순서대로 늘어놓게 된다. 검색하면 형광이 엉뚱한 자리에 뜬다.

    PaddleOCR의 **검출(detection)** 은 «글자가 어디 있는지»만 보므로 언어와
    무관하다. 인식은 LLM Vision에 맡기고 위치만 여기서 가져오면 둘 다 얻는다.

    실측(2026-07-25, 국한문 혼용 논문 1쪽)이 이 분업의 근거다:
        PaddleOCR lang=korean      → 한글 479자, 한자   0자
        PaddleOCR lang=chinese_cht → 한글   0자, 한자 202자
        LLM Vision                 → 한글 490자, 한자 163자
    두 인식 모델은 상보적이라 어느 하나로도 국한문 혼용을 읽을 수 없다.
    반면 검출은 두 경우 모두 같은 위치를 정확히 짚었다.

읽기 순서를 어떻게 맞추는가:
    검출은 한 줄을 여러 조각으로 나눈다(«Ⅰ.», «『灌庭叢書』와», «李安中»).
    그래서 세로로 겹치는 조각을 «행»으로 묶는데, 2단 조판에서는 이때
    좌단과 우단이 한 줄로 합쳐지는 사고가 난다. 실제로 그렇게 해 봤더니
    목차에서 2줄이 1줄이 되어 그 뒤가 전부 밀렸다.

    그래서 행 안에서 **가로 간격이 크게 벌어지면 별개 칸으로 쪼갠다.**
    나열 순서는 «행 위→아래, 행 안에서 좌→우»다. 이 순서를 고른 근거는
    LLM Vision이 같은 쪽의 2단 목차를 Ⅰ → Ⅲ → Ⅱ → Ⅳ 로 읽었다는 것이다.
    즉 단별로 훑지 않고 행 단위로 좌우를 오갔다.

이 모듈이 하지 않는 일:
    영역의 **의미**는 판별하지 않는다. 본문인지 각주인지 판심제인지 모른다.
    그것은 레이아웃 분석(L3)의 일이고, 여기서는 «글자가 있는 자리»만 본다.
"""

from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 저장소가 페이지를 렌더할 때 쓰는 기본 배율(=144 DPI). 좌표계를 맞추기 위해
# 검출도 같은 배율로 렌더한 이미지를 받는다.
DEFAULT_RENDER_SCALE = 2.0

# 세로 중심이 이 픽셀 안이면 같은 행으로 본다.
DEFAULT_ROW_TOLERANCE = 8.0

# 행 안에서 가로 간격이 이미지 폭의 이 비율을 넘으면 칸(단)을 가른다.
# 4%는 실측으로 고른 값이다 — 2단 목차의 좌우 간격(약 15%)은 가르고,
# 낱말 사이 공백(1% 안팎)은 가르지 않는다.
DEFAULT_COLUMN_GAP_RATIO = 0.04


@dataclass
class DetectedLine:
    """검출된 줄 하나의 위치. 좌표는 렌더 이미지의 픽셀."""

    x0: float
    y0: float
    x1: float
    y1: float

    def as_bbox(self) -> list[float]:
        """[x0, y0, x1, y1] 형태로 돌려준다 (L2/L3 bbox와 같은 형식)."""
        return [self.x0, self.y0, self.x1, self.y1]


def is_available() -> bool:
    """검출을 쓸 수 있는지 확인한다 (PaddleOCR 설치 여부).

    출력: True면 detect_lines()를 쓸 수 있다.

    왜 확인이 필요한가: PaddleOCR는 선택 설치(extra)다. 없으면 텍스트 레이어를
    입힐 때 지금까지처럼 순서 배치로 물러나야 하고, 그것이 오류가 되어서는 안 된다.
    """
    try:
        import paddleocr  # noqa: F401
    except Exception:  # noqa: BLE001 — import 실패 원인은 여기서 중요하지 않다
        return False
    return True


def _configure_windows_cpu() -> None:
    """Windows CPU 환경에서 OneDNN을 끈다.

    paddlepaddle 3.x는 Windows에서 OneDNN 경로가 PIR 속성 변환을 지원하지 않아
    `ConvertPirAttribute2RuntimeAttribute not support` 로 추론이 실패한다
    (실측 2026-07-25, paddlepaddle 3.3.1). 생성자 인자만으로는 늦는 경우가 있어
    환경 변수로도 못 박는다.
    """
    if platform.system() == "Windows":
        os.environ.setdefault("FLAGS_use_mkldnn", "0")
        os.environ.setdefault("FLAGS_enable_pir_api", "0")


_detector = None


def _get_detector():
    """검출기를 만들어 재사용한다 (모델 로드가 느리므로).

    PaddleOCR 3.x의 TextDetection을 쓴다. 인식 모델을 올리지 않으므로
    전체 파이프라인보다 훨씬 가볍고 언어 설정도 필요 없다.
    """
    global _detector
    if _detector is not None:
        return _detector

    _configure_windows_cpu()
    from paddleocr import TextDetection

    kwargs = {}
    if platform.system() == "Windows":
        kwargs["enable_mkldnn"] = False
    try:
        _detector = TextDetection(**kwargs)
    except TypeError:
        # 인자 이름이 다른 버전이면 기본값으로 만든다.
        _detector = TextDetection()
    logger.info("텍스트 줄 검출기 로드 완료 (PaddleOCR TextDetection)")
    return _detector


def _raw_boxes(image_bytes: bytes) -> list[list[float]]:
    """검출 결과에서 [x0, y0, x1, y1] 목록을 뽑는다."""
    import tempfile
    from pathlib import Path

    detector = _get_detector()

    # PaddleOCR는 파일 경로나 배열을 받는다. 바이트를 직접 넘길 수 없어
    # 임시 파일을 거친다.
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = Path(tmp.name)
    try:
        result = detector.predict(str(tmp_path))
    finally:
        tmp_path.unlink(missing_ok=True)

    first = result[0] if isinstance(result, list) and result else result
    data = getattr(first, "json", None) or first
    if isinstance(data, dict) and "res" in data:
        data = data["res"]
    polys = (data or {}).get("dt_polys") or []

    boxes = []
    for poly in polys:
        xs = [float(p[0]) for p in poly]
        ys = [float(p[1]) for p in poly]
        boxes.append([min(xs), min(ys), max(xs), max(ys)])
    return boxes


# 목표 줄 수를 아는 경우에 훑을 후보값.
#
# 왜 후보를 훑는가 (실측 2026-07-25, 논문 15쪽):
#   쪽마다 필요한 임계값이 **모순된다.**
#     1쪽(2단 목차)  — 2~6%여야 맞는다. 8% 이상이면 좌우가 합쳐진다.
#     4쪽(한시 대역) — 4% 이상이어야 한다. 2%면 낱말마다 쪼개진다.
#     12쪽           — 12% 이상이어야 한다.
#   1쪽은 6% 이하를, 12쪽은 12% 이상을 요구하므로 고정값으로는 둘 다 만족할 수 없다.
#
#   그러나 우리는 **정답 줄 수를 이미 안다** — LLM Vision이 읽은 줄 수다.
#   그것을 목표로 후보를 훑어 맞는 조합을 고르면 쪽마다 알맞게 갈린다.
_GAP_CANDIDATES = (0.04, 0.02, 0.03, 0.06, 0.08, 0.12, 0.20, 1.0)
_ROW_TOLERANCE_CANDIDATES = (8.0, 6.0, 10.0, 12.0, 5.0, 16.0)


def group_into_lines(
    boxes: list[list[float]],
    image_width: float,
    *,
    row_tolerance: float = DEFAULT_ROW_TOLERANCE,
    column_gap_ratio: float = DEFAULT_COLUMN_GAP_RATIO,
    target_count: int | None = None,
) -> list[DetectedLine]:
    """검출 조각들을 읽기 순서의 줄 목록으로 묶는다.

    입력:
        boxes — [x0, y0, x1, y1] 목록 (렌더 이미지 픽셀).
        image_width — 렌더 이미지 폭(px). 단을 가르는 기준에 쓴다.
        target_count — 맞춰야 할 줄 수(보통 LLM이 읽은 줄 수). 주면 이 개수가
            나오는 임계값 조합을 찾아 쓴다. 못 찾으면 기본값 결과를 돌려준다.
    출력: 읽기 순서(행 위→아래, 행 안에서 좌→우)로 정렬된 DetectedLine 목록.

    이 함수는 PaddleOCR에 의존하지 않는다 — 순수 계산이라 따로 시험할 수 있다.
    """
    if target_count is not None:
        # 기본 조합을 먼저 보고, 어긋나면 후보를 넓혀 간다.
        for tol in _ROW_TOLERANCE_CANDIDATES:
            for ratio in _GAP_CANDIDATES:
                lines = _group_once(boxes, image_width, tol, ratio)
                if len(lines) == target_count:
                    return lines
        # 못 맞췄다. 기본값 결과를 주고 판단은 호출부에 맡긴다
        # (호출부는 개수가 다르면 위치를 채우지 않는다).
        return _group_once(boxes, image_width, row_tolerance, column_gap_ratio)

    return _group_once(boxes, image_width, row_tolerance, column_gap_ratio)


def _group_once(
    boxes: list[list[float]],
    image_width: float,
    row_tolerance: float,
    column_gap_ratio: float,
) -> list[DetectedLine]:
    """한 가지 임계값 조합으로 묶는다. (group_into_lines의 내부 구현)"""
    if not boxes:
        return []

    # 1) 세로로 겹치는 조각을 행으로 묶는다.
    rows: list[list[list[float]]] = []
    for box in sorted(boxes, key=lambda b: b[1]):
        center_y = (box[1] + box[3]) / 2
        for row in rows:
            row_center = sum((m[1] + m[3]) / 2 for m in row) / len(row)
            if abs(center_y - row_center) < row_tolerance:
                row.append(box)
                break
        else:
            rows.append([box])

    # 2) 행 안에서 가로로 크게 벌어지면 칸을 가른다 (2단 조판 분리).
    gap_min = image_width * column_gap_ratio
    lines: list[DetectedLine] = []
    for row in sorted(rows, key=lambda r: min(m[1] for m in r)):
        ordered = sorted(row, key=lambda m: m[0])
        cell = [ordered[0]]
        cells = []
        for box in ordered[1:]:
            if box[0] - max(c[2] for c in cell) > gap_min:
                cells.append(cell)
                cell = [box]
            else:
                cell.append(box)
        cells.append(cell)

        # 3) 한 칸을 한 줄로 합친다. 행 안에서는 좌 → 우 순서.
        for c in cells:
            lines.append(
                DetectedLine(
                    x0=min(m[0] for m in c),
                    y0=min(m[1] for m in c),
                    x1=max(m[2] for m in c),
                    y1=max(m[3] for m in c),
                )
            )
    return lines


def detect_lines(
    image_bytes: bytes,
    image_width: float,
    *,
    row_tolerance: float = DEFAULT_ROW_TOLERANCE,
    column_gap_ratio: float = DEFAULT_COLUMN_GAP_RATIO,
    target_count: int | None = None,
) -> list[DetectedLine]:
    """페이지 이미지에서 글자 줄의 위치를 읽기 순서로 찾아낸다.

    입력:
        image_bytes — 페이지 이미지(PNG 등). 저장소 기본 배율(144 DPI)로 렌더한 것.
        image_width — 그 이미지의 폭(px).
        target_count — 맞춰야 할 줄 수(보통 인식이 읽은 줄 수).
            쪽마다 알맞은 임계값이 다르므로 이 값을 목표로 후보를 훑는다.
    출력: 읽기 순서의 DetectedLine 목록. 검출할 수 없으면 빈 목록.

    예외를 던지지 않는다: 검출은 **위치를 개선하는 보조 수단**이지 필수가 아니다.
    실패하면 호출부가 지금까지처럼 순서 배치로 물러날 수 있어야 한다.
    """
    if not is_available():
        return []
    try:
        boxes = _raw_boxes(image_bytes)
    except Exception as e:  # noqa: BLE001 — 실패는 폴백으로 흡수한다
        logger.warning(f"줄 위치 검출 실패 (순서 배치로 물러납니다): {e}")
        return []
    return group_into_lines(
        boxes,
        image_width,
        row_tolerance=row_tolerance,
        column_gap_ratio=column_gap_ratio,
        target_count=target_count,
    )
