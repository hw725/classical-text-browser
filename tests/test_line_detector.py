"""검출 조각을 읽기 순서의 줄로 묶는 로직 테스트.

왜 이 테스트가 있는가:
    검출은 한 줄을 여러 조각으로 나눈다(「Ⅰ.」 「『灌庭叢書』와」 「李安中」).
    세로로만 묶으면 2단 조판에서 좌단과 우단이 한 줄로 합쳐져 2줄이 1줄이 되고,
    그 지점부터 텍스트가 전부 밀린다. 실제로 그 사고가 있었다.

    여기서는 PaddleOCR 없이 순수 계산만 검증한다 — 묶는 규칙이 핵심이고
    모델 설치 여부와 무관하게 회귀를 잡을 수 있어야 하기 때문이다.
"""

from ocr.line_detector import DEFAULT_RENDER_SCALE, group_into_lines, is_available

IMG_W = 990.0  # 495pt × 2.0 (실제 논문 페이지 폭)


def test_single_column_rows_stay_separate():
    """1단 본문은 줄마다 따로 잡혀야 한다."""
    boxes = [
        [110, 640, 880, 668],
        [114, 678, 878, 706],
        [108, 716, 876, 744],
    ]
    lines = group_into_lines(boxes, IMG_W)
    assert len(lines) == 3
    # 위에서 아래 순서
    assert [round(line.y0) for line in lines] == [640, 678, 716]


def test_fragments_in_same_row_merge():
    """한 줄이 조각나 검출돼도 하나로 합쳐져야 한다.

    「Ⅰ.」 「『灌庭叢書』와」 「李安中」처럼 낱말 단위로 잘리는 것이 정상이다.
    """
    boxes = [
        [181, 483, 205, 505],  # Ⅰ.
        [211, 483, 330, 505],  # 『灌庭叢書』와
        [336, 483, 367, 505],  # 李安中
    ]
    lines = group_into_lines(boxes, IMG_W)
    assert len(lines) == 1
    assert lines[0].x0 == 181
    assert lines[0].x1 == 367


def test_two_column_row_splits_into_cells():
    """2단 조판에서 좌단과 우단은 갈라져야 한다 — 이게 핵심이다.

    세로로만 묶으면 x=181~667이 한 줄이 되어 2줄이 1줄로 뭉개진다.
    """
    boxes = [
        [181, 483, 367, 505],  # 좌단: Ⅰ. 『灌庭叢書』와 李安中
        [512, 480, 667, 505],  # 우단: Ⅲ. 李安中의 시세계
    ]
    lines = group_into_lines(boxes, IMG_W)
    assert len(lines) == 2, "좌단과 우단이 한 줄로 합쳐졌다"
    # 같은 행 안에서는 좌 → 우 순서
    assert lines[0].x0 < lines[1].x0


def test_reading_order_is_row_then_left_to_right():
    """읽기 순서는 «행 위→아래, 행 안에서 좌→우»여야 한다.

    근거: LLM Vision이 같은 쪽의 2단 목차를 Ⅰ → Ⅲ → Ⅱ → Ⅳ 로 읽었다.
    단별로 훑은 것이 아니라 행 단위로 좌우를 오갔다. 매칭도 그래야 맞는다.
    """
    boxes = [
        [181, 483, 367, 505],  # Ⅰ (1행 좌)
        [512, 480, 667, 505],  # Ⅲ (1행 우)
        [180, 509, 431, 531],  # Ⅱ (2행 좌)
        [510, 505, 597, 531],  # Ⅳ (2행 우)
    ]
    lines = group_into_lines(boxes, IMG_W)
    assert len(lines) == 4
    got = [(round(line.x0), round(line.y0)) for line in lines]
    assert got == [(181, 483), (512, 480), (180, 509), (510, 505)], got


def test_word_spacing_does_not_split_columns():
    """낱말 사이 공백은 단으로 갈라서는 안 된다.

    임계값이 너무 낮으면 본문 한 줄이 여러 줄로 쪼개져 텍스트가 밀린다.
    """
    boxes = [
        [110, 640, 300, 668],
        [316, 640, 500, 668],  # 16px 간격 — 낱말 사이
        [516, 640, 880, 668],
    ]
    lines = group_into_lines(boxes, IMG_W)
    assert len(lines) == 1, f"낱말 간격에서 갈라졌다: {len(lines)}줄"


def test_slightly_offset_boxes_share_a_row():
    """세로로 조금 어긋난 조각도 같은 행으로 봐야 한다 (인쇄·검출 오차)."""
    boxes = [
        [110, 640, 300, 668],
        [316, 644, 500, 672],  # 4px 아래로 밀림
    ]
    lines = group_into_lines(boxes, IMG_W)
    assert len(lines) == 1


def test_empty_input():
    """검출된 것이 없으면 빈 목록이다 (예외가 아니라)."""
    assert group_into_lines([], IMG_W) == []


def test_bbox_format_matches_ocr_schema():
    """as_bbox()는 L2/L3와 같은 [x0, y0, x1, y1] 형식이어야 한다."""
    lines = group_into_lines([[10, 20, 30, 40]], IMG_W)
    assert lines[0].as_bbox() == [10, 20, 30, 40]


def test_render_scale_matches_repository_default():
    """검출 좌표계는 저장소 기본 렌더 배율과 같아야 한다.

    이 값이 어긋나면 PDF 포인트로 되돌릴 때 위치가 통째로 틀어진다.
    """
    from export.text_layer_pdf import DEFAULT_RENDER_SCALE as export_scale
    from ocr.full_page_block import DEFAULT_RENDER_SCALE as block_scale
    from ocr.image_utils import DEFAULT_RENDER_SCALE as render_default

    assert DEFAULT_RENDER_SCALE == export_scale == block_scale == render_default == 2.0


def test_is_available_returns_bool():
    """설치 여부 확인은 예외 없이 참·거짓을 돌려줘야 한다.

    PaddleOCR가 없는 환경에서도 이 함수는 조용히 False여야 하고,
    그래야 호출부가 순서 배치로 물러날 수 있다.
    """
    assert isinstance(is_available(), bool)


def test_target_count_resolves_conflicting_thresholds():
    """쪽마다 필요한 임계값이 모순될 때 목표 줄 수로 풀어야 한다.

    실측(논문 15쪽)에서 확인된 모순:
      2단 목차는 6% 이하여야 좌우가 갈리고,
      한시 대역이 있는 쪽은 12% 이상이어야 낱말이 안 쪼개진다.
    고정값으로는 둘 다 만족할 수 없다.
    """
    # 좌우 간격이 8%인 2단 — 갈라야 2줄이 된다
    two_column = [
        [100, 100, 300, 130],
        [380, 100, 600, 130],  # 간격 80px = 8.1%
    ]
    # 기본값(4%)이면 이미 2줄이다
    assert len(group_into_lines(two_column, IMG_W)) == 2
    # 목표를 1줄로 주면 가르지 않는 조합을 찾아낸다
    assert len(group_into_lines(two_column, IMG_W, target_count=1)) == 1
    # 목표를 2줄로 주면 가르는 조합을 찾아낸다
    assert len(group_into_lines(two_column, IMG_W, target_count=2)) == 2


def test_target_count_uses_row_tolerance_too():
    """가로 간격만으로 안 되면 세로 묶는 기준도 넓혀 봐야 한다."""
    # 세로로 10px 어긋난 두 조각 — 기본 tolerance(8)로는 다른 행이다
    boxes = [
        [100, 100, 300, 128],
        [320, 111, 500, 139],
    ]
    assert len(group_into_lines(boxes, IMG_W)) == 2
    # 한 줄이 목표면 tolerance를 넓힌 조합을 찾는다
    assert len(group_into_lines(boxes, IMG_W, target_count=1)) == 1


def test_target_count_unreachable_falls_back_to_default():
    """어느 조합으로도 목표에 못 맞추면 기본값 결과를 준다.

    호출부는 개수가 다르면 위치를 채우지 않으므로, 여기서 억지로
    맞추려 들면 오히려 줄이 밀린다.
    """
    boxes = [[100, 100, 300, 130], [100, 200, 300, 230]]
    # 2줄짜리인데 5줄을 요구 — 불가능
    lines = group_into_lines(boxes, IMG_W, target_count=5)
    assert len(lines) == 2, "도달 불가능한 목표에 억지로 맞췄다"


def test_target_count_preserves_reading_order():
    """목표를 맞추는 조합을 골라도 읽기 순서는 유지돼야 한다."""
    boxes = [
        [181, 483, 367, 505],  # 1행 좌
        [512, 480, 667, 505],  # 1행 우
        [180, 509, 431, 531],  # 2행 좌
        [510, 505, 597, 531],  # 2행 우
    ]
    lines = group_into_lines(boxes, IMG_W, target_count=4)
    got = [(round(line.x0), round(line.y0)) for line in lines]
    assert got == [(181, 483), (512, 480), (180, 509), (510, 505)], got
