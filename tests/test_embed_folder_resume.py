"""폴더 배치의 재개 동작 테스트 — 중단해도 돌린 쪽을 버리지 않는가.

왜 이 테스트가 있는가:
    수십 편 수천 쪽을 도는 배치는 몇 시간에서 며칠이 걸린다. 그동안 한 번도
    안 멈춘다는 보장이 없다(네트워크, 한도 초과, 재부팅). 멈춘 지점이
    한 편의 중간이면 그 편에 이미 들어간 LLM 호출이 통째로 버려지거나,
    문헌 ID가 이미 있어 그 편이 영영 실패로 남는다.

    기록 파일(_load_done)은 **편 단위** 재개만 해 준다. 편 안쪽에서 멈춘
    경우를 여기서 잡는다.

무엇을 LLM 없이 확인하는가:
    파이프라인을 가짜로 바꿔 «몇 쪽에 실제로 호출이 나갔는가»를 센다.
    호출 횟수가 곧 비용이므로, 재개가 동작하면 그 수가 줄어야 한다.
"""

import json

import fitz
import pytest

from cli.embed_folder import PaperTask, _process_one


class FakePipeline:
    """run_page()가 불린 쪽을 기록하고 최소한의 L2를 쓴다.

    실제 OcrPipeline은 엔진을 부르므로 테스트에서 쓸 수 없다. 재개 판정이
    보는 것은 L2 파일의 존재와 내용뿐이므로 그 형태만 만든다.
    """

    def __init__(self, library_path):
        self.library_path = library_path
        self.called_pages = []
        self.fail_after = None  # 이 횟수를 넘기면 예외를 던진다 (중단 재현)

    def run_page(self, *, doc_id, part_id, page_number, engine_id=None, **kw):
        if self.fail_after is not None and len(self.called_pages) >= self.fail_after:
            raise RuntimeError("연결이 끊겼습니다 (중단 재현)")
        self.called_pages.append(page_number)

        doc_path = self.library_path / "documents" / doc_id
        (doc_path / "L2_ocr").mkdir(exist_ok=True)
        (doc_path / "L2_ocr" / f"{part_id}_page_{page_number:03d}.json").write_text(
            json.dumps(
                {
                    "part_id": part_id,
                    "page_number": page_number,
                    "ocr_engine": "fake",
                    "ocr_results": [
                        {
                            "layout_block_id": f"p{page_number:02d}_b01",
                            "lines": [{"text": f"{page_number}쪽 본문입니다."}],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        class _R:
            ocr_results = [{"lines": [{"text": "본문"}]}]

        return _R()


@pytest.fixture()
def library(tmp_path):
    """빈 작업 서고."""
    from core.library import init_library

    lib = tmp_path / "lib"
    init_library(lib)
    return lib


@pytest.fixture()
def scan_pdf(tmp_path):
    """텍스트 레이어가 없는 3쪽짜리 PDF."""
    path = tmp_path / "논문.pdf"
    out = fitz.open()
    for _ in range(3):
        tmp = fitz.open()
        tp = tmp.new_page(width=595, height=842)
        tp.insert_text((70, 100), "본문 텍스트", fontname="korea", fontsize=11)
        jpg = tp.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("jpeg", jpg_quality=50)
        tmp.close()
        p = out.new_page(width=595, height=842)
        p.insert_image(p.rect, stream=jpg)
    out.save(str(path))
    out.close()
    return path


def _task(pdf):
    return PaperTask(path=pdf, topic="기타", pages=3, verdict="scanned")


def test_interrupted_paper_resumes_from_where_it_stopped(library, scan_pdf):
    """2쪽까지 돌고 멈췄으면, 다시 실행할 때 3쪽만 돌아야 한다.

    이것이 안 되면 재시작마다 그 편이 1쪽부터 다시 돌아 비용이 이중으로 든다.
    """
    archive = library.parent / "archive"

    # 1차 실행 — 2쪽까지 돌고 3쪽에서 끊긴다.
    pipe = FakePipeline(library)
    pipe.fail_after = 2
    rec = _process_one(
        _task(scan_pdf), library, "embed_0001", None, archive, False, pipe
    )
    assert rec["status"] == "failed"
    assert pipe.called_pages == [1, 2]

    # 2차 실행 — 같은 doc_id로 다시 온다.
    pipe2 = FakePipeline(library)
    rec2 = _process_one(
        _task(scan_pdf), library, "embed_0001", None, archive, False, pipe2
    )

    # 1·2쪽은 결과가 있으니 건너뛰고 3쪽만 새로 돈다.
    assert pipe2.called_pages == [3], "이미 돌린 쪽에 LLM 호출이 다시 나갔다"
    assert rec2["resumed_pages"] == 2
    assert rec2["status"] == "ok"
    assert rec2["ocr_pages"] == 3


def test_fresh_paper_runs_every_page(library, scan_pdf):
    """처음 도는 편은 모든 쪽을 돈다 (재개 로직이 새 작업을 막지 않는다)."""
    pipe = FakePipeline(library)
    rec = _process_one(
        _task(scan_pdf), library, "embed_0002", None, library.parent / "arc", False, pipe
    )
    assert pipe.called_pages == [1, 2, 3]
    assert rec["status"] == "ok"
    assert "resumed_pages" not in rec


def test_resume_does_not_duplicate_document(library, scan_pdf):
    """재개해도 문헌이 두 개로 늘지 않는다.

    add_document를 다시 부르면 같은 논문의 사본이 서고에 쌓인다.
    """
    archive = library.parent / "archive"
    pipe = FakePipeline(library)
    pipe.fail_after = 1
    _process_one(_task(scan_pdf), library, "embed_0003", None, archive, False, pipe)

    before = sorted(p.name for p in (library / "documents").iterdir())
    pipe2 = FakePipeline(library)
    _process_one(_task(scan_pdf), library, "embed_0003", None, archive, False, pipe2)
    after = sorted(p.name for p in (library / "documents").iterdir())

    assert before == after == ["embed_0003"]
