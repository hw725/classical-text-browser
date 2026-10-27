"""B-085-1: GPU 환경(.venv-gpu)에서 줄 위치 검출이 늘 실패하던 결함의 재현 시험.

무엇이 있었나 (2026-10-28 릴리스 E2E, 운양집 3쪽):
    `.venv-gpu`(paddlepaddle-gpu 3.3.1 · paddleocr 3.7.0 · paddlex 3.7.2)에서 글자층을 구우면 줄
    위치 검출이 《partially initialized module 'paddle' has no attribute 'tensor'》로 쪽마다 실패해,
    좌표 없는 줄(교정본 L4)이 전부 왼쪽 위부터 순서 배치로 놓였다(positioned 0 / approximated 90).

원인:
    `paddleocr`(paddlex)가 torch를 끌어오면 torch의 cuDNN 9 DLL이 먼저 올라가, 같은 프로세스에서
    paddle GPU판의 `cudnn_cnn64_9.dll`이 WinError 127로 실패한다. 서버 프로세스는 NDL古典籍
    Full(torch)을 이미 올려 두므로 이 충돌은 피할 수 없다 — 그래서 PaddleOCR 인식은 D-091부터 자식
    워커에서 돈다. 줄 검출만 서버 프로세스 안에서 `TextDetection`을 만들어 같은 벽에 부딪혔다(첫
    실패 뒤 반쯤 올라간 paddle 모듈이 남아 다음부터는 순환 import로 보인다).

이 시험이 지키는 것:
    1) 서버가 PaddleOCR 워커를 쓰는 환경이면 줄 검출도 그 워커(`op: detect`)로 간다 — 서버
       프로세스의 paddle import가 죽어도 검출은 산다.
    2) 실제 `.venv-gpu`에서, 서버처럼 torch를 먼저 올린 프로세스에서도 줄이 검출된다(이 PC에
    `.venv-gpu`가 있을 때만).
    3) 세로쓰기 쪽의 검출 조각을 열(오른쪽 → 왼쪽, 열 안에서 위 → 아래)로 묶는다 — 가로 행으로
       묶으면 세로쓰기 쪽에서 줄 수가 맞지 않아 위치를 채울 수 없다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GPU_PY = ROOT / ".venv-gpu" / "Scripts" / "python.exe"
CPU_PY = ROOT / ".venv" / "Scripts" / "python.exe"


def _png(width: int = 400, height: int = 300) -> bytes:
    import fitz

    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), False)
    pix.clear_with(255)
    return pix.tobytes("png")


def test_detection_uses_paddle_worker_when_in_process_paddle_breaks(monkeypatch):
    """서버가 워커 모드(CTB_PADDLE_PYTHON)면 검출도 워커로 간다.

    서버 안 paddle이 죽어도 검출은 산다.
    """
    from ocr import line_detector, paddleocr_engine

    # 서버 프로세스 안의 paddle은 B-085에서처럼 죽는다고 둔다
    class _Broken:
        def __getattr__(self, name):
            raise AttributeError(
                "partially initialized module 'paddle' has no attribute 'tensor' "
                "(most likely due to a circular import)"
            )

    monkeypatch.setitem(sys.modules, "paddleocr", _Broken())
    monkeypatch.setattr(line_detector, "_detector", None)
    # 워커 모드 조건(start_server.bat이 .venv-gpu 서버에 주는 값과 같은 꼴)
    monkeypatch.setenv("CTB_PADDLE_PYTHON", "C:/other/.venv/Scripts/python.exe")
    monkeypatch.setenv("CTB_PADDLE_GPU_WORKER", "0")

    calls: list[dict] = []

    def fake_call(self, req, timeout=600.0):
        calls.append(req)
        if req["op"] == "ping":
            return {"ok": True, "available": True}
        if req["op"] == "detect":
            return {"ok": True, "boxes": [[10, 10, 200, 40], [10, 60, 200, 90]]}
        return {"ok": False, "error": "unexpected"}

    monkeypatch.setattr(paddleocr_engine.PaddleOcrEngine, "_worker_call", fake_call)
    if hasattr(line_detector, "_reset_worker"):
        line_detector._reset_worker()

    lines = line_detector.detect_lines(_png(), 400.0)

    assert [r["op"] for r in calls if r["op"] == "detect"], "검출 요청이 워커로 가지 않았다"
    assert len(lines) == 2, f"워커가 준 두 줄을 받지 못했다: {lines}"


def test_vertical_grouping_orders_columns_right_to_left():
    """세로쓰기: 조각을 열로 묶어 오른쪽 열부터, 열 안에서는 위 → 아래로 늘어놓는다."""
    from ocr.line_detector import group_into_lines

    # 오른쪽부터 세 열. 가운데 열은 두 조각으로 끊겨 검출됐다(사이 간격은 작다).
    # 왼쪽 열은 위아래로 크게 떨어진 두 칸(위 본문, 아래 쪽 번호)이다.
    boxes = [
        [300, 20, 340, 580],  # 1열(오른쪽)
        [230, 20, 270, 280],  # 2열 위 조각
        [232, 290, 268, 560],  # 2열 아래 조각(간격 10px — 같은 줄)
        [160, 20, 200, 300],  # 3열 본문
        [162, 520, 198, 580],  # 3열 아래 쪽 번호(간격 220px — 다른 줄)
    ]
    lines = group_into_lines(boxes, 400.0, image_height=600.0, vertical=True)

    got = [[round(v) for v in ln.as_bbox()] for ln in lines]
    assert got == [
        [300, 20, 340, 580],
        [230, 20, 270, 560],
        [160, 20, 200, 300],
        [162, 520, 198, 580],
    ], got


def test_vertical_grouping_matches_target_count():
    """세로쓰기에서도 목표 줄 수를 주면 그 수가 나오는 임계값을 찾는다."""
    from ocr.line_detector import group_into_lines

    boxes = [[300, 20, 340, 580], [230, 20, 270, 280], [232, 290, 268, 560], [160, 20, 200, 300]]
    # 2열의 두 조각을 따로 셀 수도(4줄), 합칠 수도(3줄) 있다
    for n in (3, 4):
        got = group_into_lines(boxes, 400.0, image_height=600.0, vertical=True, target_count=n)
        assert len(got) == n


_GPU_SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import torch  # 서버처럼 torch(NDL古典籍 Full)를 먼저 올린다
import fitz
doc = fitz.open()
page = doc.new_page(width=420, height=300)
y = 60
for t in ("一二三四五六七八九十天地玄黃", "宇宙洪荒日月盈昃辰宿列張寒來",
"暑往秋收冬藏閏餘成歲律呂調陽"):
    page.insert_text((30, y), t, fontname="china-t", fontsize=24)
    y += 70
pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
from ocr.line_detector import detect_lines
lines = detect_lines(pix.tobytes("png"), float(pix.width))
print("RESULT " + json.dumps({"lines": len(lines)}))
'''


@pytest.mark.slow
@pytest.mark.skipif(not GPU_PY.exists(), reason="이 PC에 .venv-gpu가 없다")
def test_real_gpu_env_detects_lines_with_torch_loaded(tmp_path):
    """실제 .venv-gpu, torch를 먼저 올린 프로세스(서버와 같은 순서)에서 줄이 검출된다."""
    script = tmp_path / "gpu_detect.py"
    script.write_text(_GPU_SCRIPT, encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("CTB_PADDLE_DEVICE", None)
    if CPU_PY.exists():
        env["CTB_PADDLE_PYTHON"] = str(CPU_PY)  # start_server.bat과 같은 값
    proc = subprocess.run(
        [str(GPU_PY), str(script), str(ROOT / "src")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=600,
    )
    out = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert out, f"결과 줄이 없다 (rc={proc.returncode})\n{proc.stderr[-2000:]}"
    n = json.loads(out[-1][len("RESULT "):])["lines"]
    assert n == 3, f".venv-gpu에서 검출 {n}줄(3줄이어야 한다)\n{proc.stderr[-2000:]}"
