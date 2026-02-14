"""더미 PDF 생성 스크립트.

목적: Phase 3 테스트용 2페이지 A4 PDF를 생성한다.
      고전 텍스트(세로쓰기 한문)를 시뮬레이션한다.
      한 글자씩 세로로 배치하고, 우측에서 좌측으로 열을 진행한다.

사용법:
    uv run python examples/generate_dummy_pdf.py

출력: examples/dummy_shishuo.pdf
"""

from pathlib import Path

from fpdf import FPDF


def find_cjk_font() -> Path:
    """CJK 지원 TTF 폰트를 찾는다.

    목적: PDF에 한자를 렌더링하기 위해 시스템에서 TTF 폰트를 탐색한다.
    출력: 폰트 파일의 Path.
    왜 이렇게 하는가: fpdf2는 내장 폰트에 CJK를 포함하지 않으므로,
                      시스템 폰트를 사용해야 한다.
    """
    candidates = [
        # Windows 시스템 폰트 (CJK 커버리지가 넓은 순서)
        Path("C:/Windows/Fonts/ARIALUNI.TTF"),  # Arial Unicode MS — 가장 넓은 커버리지
        Path("C:/Windows/Fonts/simsunb.ttf"),   # SimSun-ExtB — 중국어 전용
        Path("C:/Windows/Fonts/malgun.ttf"),    # 맑은 고딕
        # macOS
        Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
        # Linux
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "CJK 폰트를 찾을 수 없습니다.\n"
        "→ 해결: Windows의 경우 C:/Windows/Fonts/malgun.ttf 가 필요합니다.\n"
        "   Linux/macOS의 경우 Noto CJK 폰트를 설치하세요."
    )


def _draw_vertical_text(
    pdf: FPDF,
    text: str,
    x_start: float,
    y_start: float,
    font_size: float,
    col_gap: float,
) -> None:
    """한 글자씩 세로로 배치한다 (세로쓰기 시뮬레이션).

    목적: 고전 텍스트의 세로쓰기를 시뮬레이션한다.
    입력:
        pdf — FPDF 인스턴스.
        text — 배치할 텍스트.
        x_start — 첫 열의 x 좌표 (우측에서 시작).
        y_start — 첫 글자의 y 좌표.
        font_size — 글자 크기 (pt).
        col_gap — 열 간격 (mm).
    왜 이렇게 하는가: fpdf2에는 네이티브 세로쓰기 기능이 없으므로,
                      글자를 한 개씩 배치하여 세로쓰기를 시뮬레이션한다.
    """
    pdf.set_font("CJK", size=font_size)
    # 글자 간격: 폰트 크기를 mm로 변환 (1pt ≈ 0.353mm) × 간격 배율
    char_height = font_size * 0.353 * 1.5
    x = x_start
    y = y_start

    for char in text:
        pdf.text(x, y, char)
        y += char_height
        # 페이지 하단에 도달하면 다음 열(좌측)로 이동
        if y > 270:
            y = y_start
            x -= col_gap


def _draw_double_line_annotation(
    pdf: FPDF,
    text: str,
    x_start: float,
    y_start: float,
    font_size: float,
) -> None:
    """소자 쌍행(두 열) 주석을 시뮬레이션한다.

    목적: 고전 텍스트의 소자쌍행(小字雙行) 주석을 시뮬레이션한다.
          원래 주석은 본문의 절반 크기 글자가 두 줄로 배치된다.
    입력:
        pdf — FPDF 인스턴스.
        text — 주석 텍스트.
        x_start — 주석 영역의 x 좌표.
        y_start — 첫 글자의 y 좌표.
        font_size — 글자 크기 (pt).
    """
    pdf.set_font("CJK", size=font_size)
    char_height = font_size * 0.353 * 1.4
    col_offset = font_size * 0.353 * 1.2  # 쌍행 열 간격

    # 텍스트를 두 열로 분배
    mid = (len(text) + 1) // 2
    col1 = text[:mid]   # 우측 열
    col2 = text[mid:]   # 좌측 열

    # 우측 열
    y = y_start
    for char in col1:
        pdf.text(x_start, y, char)
        y += char_height

    # 좌측 열
    y = y_start
    for char in col2:
        pdf.text(x_start - col_offset, y, char)
        y += char_height


def generate_dummy_pdf(output_path: Path) -> None:
    """2페이지 더미 PDF를 생성한다.

    목적: Phase 3 병렬 뷰어 테스트용 PDF를 생성한다.
    입력: output_path — 출력 파일 경로.
    출력: A4 세로 2페이지 PDF 파일.

    페이지 구성:
        1페이지: 대자 "王戎簡要裴楷清通" + 소자 쌍행 "王戎字濬沖瑯邪臨沂人"
        2페이지: 대자 "孔明臥龍呂望非熊" + 소자 쌍행 "孔明字亮琅邪陽都人"
    """
    font_path = find_cjk_font()

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_font("CJK", "", str(font_path))

    # --- 페이지 1 ---
    pdf.add_page()

    # 페이지 제목 (상단)
    pdf.set_font("CJK", size=10)
    pdf.text(90, 15, "世說新語 — 德行第一")

    # 본문: 대자 세로쓰기 (우측에서 좌측)
    _draw_vertical_text(
        pdf, "王戎簡要裴楷清通",
        x_start=180, y_start=30, font_size=24, col_gap=28,
    )

    # 주석: 소자 쌍행
    _draw_double_line_annotation(
        pdf, "王戎字濬沖瑯邪臨沂人",
        x_start=90, y_start=30, font_size=12,
    )

    # --- 페이지 2 ---
    pdf.add_page()

    pdf.set_font("CJK", size=10)
    pdf.text(90, 15, "世說新語 — 德行第一")

    _draw_vertical_text(
        pdf, "孔明臥龍呂望非熊",
        x_start=180, y_start=30, font_size=24, col_gap=28,
    )

    _draw_double_line_annotation(
        pdf, "孔明字亮琅邪陽都人",
        x_start=90, y_start=30, font_size=12,
    )

    # PDF 저장
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))
    print(f"더미 PDF 생성 완료: {output_path}")
    print(f"  페이지 수: 2")
    print(f"  파일 크기: {output_path.stat().st_size:,} bytes")


if __name__ == "__main__":
    output = Path(__file__).parent / "dummy_shishuo.pdf"
    generate_dummy_pdf(output)
