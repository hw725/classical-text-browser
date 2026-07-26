"""JSON 저장이 원자적인지 확인한다 (D-069).

왜 이 시험이 필요한가:
    `Path.write_text()`는 **먼저 파일을 0바이트로 자르고** 쓴다. 그 사이에
    정전·강제종료·디스크 부족이 나면 `manifest.json`이 빈 파일로 남고,
    그 문헌은 통째로 열리지 않는다. git 커밋 이전 상태였다면 되돌릴 길도 없다.

    저장이 «성공하는» 경우만 보는 시험으로는 이것을 잡을 수 없다.
    쓰기 도중에 일부러 실패시켜, 예전 내용이 남아 있는지를 본다.
"""

import json

import pytest

from core.document import write_json_atomic


def test_writes_and_reads_back(tmp_path):
    """평범한 저장이 그대로 읽혀야 한다 (한자·한글 보존 포함)."""
    target = tmp_path / "manifest.json"
    data = {"document_id": "doc_1", "title": "薄庭叢書 연구", "parts": []}

    write_json_atomic(target, data)

    assert json.loads(target.read_text(encoding="utf-8")) == data
    # ensure_ascii=False — 한자가 \uXXXX로 깨지지 않아야 한다
    assert "薄庭叢書" in target.read_text(encoding="utf-8")


def test_creates_parent_directories(tmp_path):
    """중간 디렉터리가 없어도 만들어 준다."""
    target = tmp_path / "a" / "b" / "c.json"
    write_json_atomic(target, {"ok": True})
    assert target.exists()


def test_failure_keeps_previous_content(tmp_path, monkeypatch):
    """쓰기 도중 죽어도 **예전 내용이 그대로 남아야** 한다.

    이것이 이 함수의 존재 이유다. write_text()였다면 여기서 빈 파일이 된다.
    """
    target = tmp_path / "manifest.json"
    original = {"document_id": "doc_1", "parts": [{"part_id": "vol1"}]}
    write_json_atomic(target, original)

    # 임시 파일에는 다 썼는데 갈아 끼우는 순간 죽는 상황
    def boom(src, dst):
        raise OSError("디스크가 가득 찼습니다")

    monkeypatch.setattr("os.replace", boom)

    with pytest.raises(OSError):
        write_json_atomic(target, {"document_id": "doc_1", "parts": []})

    # 예전 내용이 온전해야 한다
    assert json.loads(target.read_text(encoding="utf-8")) == original


def test_failure_leaves_no_temp_file(tmp_path, monkeypatch):
    """실패해도 서고에 정체불명 임시 파일을 남기지 않는다."""
    target = tmp_path / "manifest.json"
    write_json_atomic(target, {"a": 1})

    monkeypatch.setattr("os.replace", lambda s, d: (_ for _ in ()).throw(OSError("실패")))
    with pytest.raises(OSError):
        write_json_atomic(target, {"a": 2})

    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "manifest.json"]
    assert leftovers == [], f"임시 파일이 남았다: {leftovers}"


def test_all_core_writers_delegate():
    """다섯 모듈의 _write_json이 모두 같은 정본을 쓴다.

    한 곳만 고치고 나머지를 잊으면 그 층의 데이터만 위험한 채 남는다.
    """
    import inspect

    from core import document, entity, interpretation, library, snapshot

    for mod in (entity, interpretation, library, snapshot):
        src = inspect.getsource(mod._write_json)
        assert "write_json_atomic" in src, f"{mod.__name__}이 위임하지 않는다"
    assert inspect.getsource(document._write_json).count("write_json_atomic") == 1
