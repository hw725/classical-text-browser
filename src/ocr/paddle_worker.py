"""PaddleOCR 워커 — 다른 가상환경의 파이썬에서 PaddleOCR을 돌리는 자식 프로세스 (D-091).

왜 필요한가:
    Windows에서 torch(cu124)와 paddlepaddle-gpu는 서로 다른 판의 cuDNN 9 DLL을 들고 온다.
    한 프로세스에 둘을 올리면 먼저 뜬 쪽이 이기고 뒤쪽이 WinError 127로 죽는다(CLAUDE.md
    결합 지점 표). 그래서 GPU 환경(.venv-gpu)에서 NDL古典籍 TrOCR(torch)을 쓰면 PaddleOCR이
    사용 불가가 됐다. 프로세스를 나누면 둘 다 산다 — 서버는 .venv-gpu에서, PaddleOCR은
    .venv(CPU)의 파이썬을 자식으로 띄워 거기서 돈다.

프로토콜 (stdin/stdout, 한 줄에 JSON 하나):
    → {"op": "ping"}
    ← {"ok": true, "available": bool, "reason": str|null, "python": str, "paddle": str|null}
    → {"op": "recognize", "image_b64": str, "writing_direction": str, "language": str, "kwargs": {}}
    ← {"ok": true, "result": {"lines": [...]}}  |  {"ok": false, "error": str}
    → {"op": "quit"}

이 파일은 자식 파이썬(.venv)에서 `python -m ocr.paddle_worker`로 실행된다. 부모는
`ocr.paddleocr_engine.PaddleOcrEngine`의 워커 모드가 담당한다.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import traceback


def _engine():
    # 워커 안에서는 반드시 in-process 모드로 — 아니면 자식이 또 자식을 띄운다.
    os.environ.pop("CTB_PADDLE_PYTHON", None)
    os.environ.pop("CTB_PADDLE_FORCE_WORKER", None)
    from ocr.paddleocr_engine import PaddleOcrEngine

    return PaddleOcrEngine()


def handle_request(engine, req: dict) -> dict:
    """요청 하나를 처리해 응답 dict를 만든다. 예외는 전부 {"ok": false}로 바꾼다."""
    op = req.get("op")
    try:
        if op == "ping":
            available = bool(engine.is_available())
            paddle_ver = None
            if available:
                try:
                    import paddle

                    paddle_ver = getattr(paddle, "__version__", None)
                except Exception:  # noqa: BLE001
                    paddle_ver = None
            return {
                "ok": True,
                "available": available,
                "reason": None if available else getattr(engine, "_unavailable_reason", None),
                "python": sys.version.split()[0],
                "executable": sys.executable,
                "paddle": paddle_ver,
            }
        if op == "recognize":
            image = base64.b64decode(req["image_b64"])
            result = engine.recognize(
                image,
                writing_direction=req.get("writing_direction", "vertical_rtl"),
                language=req.get("language", "classical_chinese"),
                **(req.get("kwargs") or {}),
            )
            return {"ok": True, "result": result.to_dict()}
        if op == "quit":
            return {"ok": True, "bye": True}
        return {"ok": False, "error": f"알 수 없는 op: {op}"}
    except Exception as e:  # noqa: BLE001 — 부모가 OcrEngineError로 바꿔 던진다
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc()[-1500:],
        }


def main() -> int:
    # 로그가 stdout으로 새면 프로토콜이 깨진다 — 전부 stderr로
    import logging

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    engine = _engine()
    out = sys.stdout
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except ValueError:
            out.write(
                json.dumps({"ok": False, "error": "JSON 해석 실패"}, ensure_ascii=False) + "\n"
            )
            out.flush()
            continue
        resp = handle_request(engine, req)
        out.write(json.dumps(resp, ensure_ascii=False) + "\n")
        out.flush()
        if resp.get("bye"):
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
