"""`python -m punctuation_service` 실행 진입점.

환경변수:
- PUNCT_HOST       (기본 127.0.0.1)
- PUNCT_PORT       (기본 8765)
- PUNCT_ENGINE     (mock | sikurroberta, 기본 mock)
- PUNCT_MODEL_PATH (sikurroberta 엔진일 때 .ckpt 가중치 경로)
- PUNCT_DEVICE     (sikurroberta 엔진일 때: auto | cuda | cpu, 기본 auto)

사용 예 (Mock):
    uv sync
    uv run python -m punctuation_service

사용 예 (실제 모델):
    uv sync --extra real
    PUNCT_ENGINE=sikurroberta PUNCT_MODEL_PATH=/path/to/model.ckpt \\
        uv run python -m punctuation_service
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("PUNCT_HOST", "127.0.0.1")
    port = int(os.getenv("PUNCT_PORT", "8765"))
    # reload=False: 본 서비스는 모델 로드가 무거우므로 운영 시 항상 단일 워커.
    # 개발 중 코드 변경 반영이 필요하면 `uvicorn ... --reload`로 직접 실행할 것.
    uvicorn.run(
        "punctuation_service.api:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
