""".hwp(HWP 5.0)를 읽을 때 확장 B 한자와 사용자 정의 영역(PUA) 글자를 지우지 않는다.

2026-10-22, 연구 작업대 rhwp 검토에서 발견.

무엇이 잘못됐었나:
    hwp-hwpx-parser 1.0.0의 HWP5 판독기는 글자를 UTF-16 한 단위(16비트)씩 읽고
    `_is_valid_char`의 허용 목록에 든 것만 남긴다. 그 목록에
      - PUA(U+E000~F8FF, 구결자·한양 PUA 한자)와
      - 대리쌍(U+D800~DFFF, 확장 B 이후 한자와 SPUA-A가 이 두 단위로 저장된다)
    이 없어서, 《옛 비석에 '𥛠'으로》가 《''으로》가 되고
    《性善이라(구결)시니》의 구결자가 오류 없이 사라졌다.
    .hwpx는 XML을 읽으므로 이 문제가 없다.

픽스처 `tests/fixtures/hwp/extb_pua.hwp`:
    rhwp 0.8.7(`HwpDocument.createEmpty` → `insertText`·`insertFootnote` → `exportHwp`)로
    만든 3.5KB 문서. 본문에 U+256E0(확장 B)·U+F537(PUA)·U+F0853(SPUA-A),
    각주에 U+2604D(확장 B)·U+E004(PUA)가 있다.
    합성 파일만으로 끝내지 않았다 — 실물 .hwp(예기집설대전·현토 표점 논문 사본)에서
    확장 B·PUA 수와 종류가 다른 판독기(rhwp)와 그대로 같아짐을 확인했다(2·605자).
"""

from __future__ import annotations

from pathlib import Path

from hwp.reader import get_reader

FIXTURE = Path(__file__).parent / "fixtures" / "hwp" / "extb_pua.hwp"

BODY_CHARS = ["\U000256E0", "", "\U000F0853"]
NOTE_CHARS = ["\U0002604D", ""]


def _read():
    with get_reader(FIXTURE) as r:
        return r.extract_text(), r.extract_text_with_notes()


def test_본문의_확장B_PUA_SPUA가_남는다():
    text, notes = _read()
    for ch in BODY_CHARS:
        assert ch in text, f"extract_text에서 U+{ord(ch):04X}가 사라졌다"
        assert ch in notes["text"], f"with_notes 본문에서 U+{ord(ch):04X}가 사라졌다"
    # 자리까지 맞는가 — 앞뒤 글자 사이에 정확히 그 글자가 온다
    assert "비석에 \U000256E0으로" in text
    assert "性善이라시니" in text


def test_각주의_확장B_PUA가_남는다():
    _, notes = _read()
    fn = "".join(n["text"] for n in notes["footnotes"])
    assert len(notes["footnotes"]) == 1
    for ch in NOTE_CHARS:
        assert ch in fn, f"각주에서 U+{ord(ch):04X}가 사라졌다"


def test_짝_잃은_대리_단위가_남지_않는다():
    """대리쌍을 허용하면서 짝이 맞지 않는 반쪽이 그대로 나가면 UTF-8로 저장할 때 죽는다.

    짝을 잃은 반쪽은 U+FFFD(대체 문자)로 바꿔 《여기 글자가 있었다》를 남긴다
    — 조용히 지우지 않는다.
    """
    text, notes = _read()
    for s in [text, notes["text"], *[n["text"] for n in notes["footnotes"]]]:
        assert not any(0xD800 <= ord(c) <= 0xDFFF for c in s)
        s.encode("utf-8")  # 반쪽이 남아 있으면 UnicodeEncodeError


def test_섹션_나누기도_같은_글을_쓴다():
    with get_reader(FIXTURE) as r:
        sections = r.extract_sections()
    joined = "".join(s["text"] for s in sections)
    for ch in BODY_CHARS:
        assert ch in joined
