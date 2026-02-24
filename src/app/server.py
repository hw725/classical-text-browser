"""웹 앱 서버 — 라우터 조립 및 정적 파일 서빙.

FastAPI 기반. 서고 데이터를 API로 제공하고 정적 파일(HTML/CSS/JS)을 서빙한다.
D-001: 이 플랫폼의 주 인터페이스는 GUI이며, CLI는 보조 도구다.

아키텍처:
    이 파일은 FastAPI 앱 생성과 라우터 마운트만 담당한다.
    실제 API 엔드포인트는 app/routers/ 패키지의 8개 라우터 모듈에 분산:

    routers/library.py       — 서고/설정/백업/휴지통 (16 라우트)
    routers/documents.py     — 문헌 CRUD/페이지/교정/서지/파서 (32 라우트)
    routers/interpretations.py — 해석 CRUD/레이어/의존/엔티티 (22 라우트)
    routers/llm_ocr.py       — LLM 상태·분석·초안 + OCR 엔진·실행 (13 라우트)
    routers/alignment.py     — 이체자 사전/정렬/일괄교정 (17 라우트)
    routers/reading.py       — L5 표점·현토 + L6 번역 + 비고 + AI보조 (22 라우트)
    routers/annotation.py    — L7 주석·사전형·인용마크 + AI보조 (30 라우트)
    routers/version.py       — Git 그래프/되돌리기/스냅샷/가져오기 (7 라우트)

    공유 상태 및 헬퍼는 app/_state.py에 집약.
"""

import sys
from pathlib import Path

# src/ 디렉토리를 Python 경로에 추가
_src_dir = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app._state import configure_library, set_library_path  # noqa: F401
from app.routers import (  # noqa: F401
    library,
    documents,
    interpretations,
    llm_ocr,
    alignment,
    reading,
    annotation,
    version,
)

app = FastAPI(
    title="고전서지 통합 브라우저",
    description="사람과 LLM이 함께 고전 텍스트를 읽고 번역하고 연구하는 통합 작업 환경",
    version="0.2.0",
)

# ── 라우터 마운트 ─────────────────────────────────
app.include_router(library.router)
app.include_router(documents.router)
app.include_router(interpretations.router)
app.include_router(llm_ocr.router)
app.include_router(alignment.router)
app.include_router(reading.router)
app.include_router(annotation.router)
app.include_router(version.router)

# ── 정적 파일 서빙 ───────────────────────────────
# 서고 유무와 관계없이 항상 마운트한다.
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


def configure(library_path: str | Path) -> FastAPI:
    """서고 경로를 설정하고 정적 파일 마운트를 수행한다.

    목적: 서버 시작 전(또는 런타임에 서고 전환 시) 서고 경로를 지정한다.
    입력: library_path — 서고 디렉토리 경로.
    출력: 설정된 FastAPI 앱 인스턴스.

    서고 전환 시 주의:
        - LLM 라우터 캐시를 초기화한다 (서고별 .env가 다를 수 있음).
        - 최근 서고 목록에 추가한다.
    """
    configure_library(library_path)
    return app


# ── 하위 호환: parsers/generic_llm.py 등에서 사용 ──
# 기존에 `from app.server import _get_llm_router` 형태로 접근하는 코드 지원
from app._state import _get_llm_router  # noqa: F401
