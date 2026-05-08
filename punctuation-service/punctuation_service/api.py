"""외부 표점 서비스 — FastAPI 진입점.

본체(classical-text-browser)에서 httpx 등으로 호출하는 마이크로서비스.
SikuRoBERTa 기반 추론을 별도 프로세스에 격리하여, 본체 의존성을 가볍게 유지한다.

엔드포인트:
- GET  /health     서비스/엔진 상태
- POST /punctuate  표점 추론 본체

응답 스키마는 본체의 _normalize_punct_marks() (src/app/routers/reading.py)
규약과 호환되게 맞췄다. 즉 marks: [{start, end, before, after}, ...] 형태.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .engine import PunctuationEngine, get_engine


class PunctuateRequest(BaseModel):
    text: str = Field(..., description="표점을 붙일 원문 (한문)")


class PunctuationMarkModel(BaseModel):
    """본체의 marks 스키마와 호환. 필드명 변경 금지."""

    start: int
    end: int
    before: str = ""
    after: str


class PunctuateResponse(BaseModel):
    engine: str = Field(..., description="사용된 엔진 이름")
    punctuated: str = Field(..., description="표점이 적용된 결과 문자열")
    marks: list[PunctuationMarkModel] = Field(default_factory=list)


# 엔진은 lifespan에서 한 번만 만들어 모듈 전역에 둔다.
# 모델 로드가 무겁기 때문에 요청마다 만들면 안 된다.
_engine: Optional[PunctuationEngine] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 환경변수 PUNCT_ENGINE을 보고 엔진을 초기화."""
    global _engine
    engine_name = os.getenv("PUNCT_ENGINE", "mock")
    _engine = get_engine(engine_name)
    yield
    # 종료 시 정리할 자원이 생기면 여기에 추가 (현재는 없음).


app = FastAPI(
    title="고전한문 표점 서비스",
    version="0.1.0",
    description="SikuRoBERTa 기반 자동 표점 (yachagye/korean-classical-chinese-punctuation 모델 활용)",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict:
    """간단한 상태 점검. 본체에서 서비스 가용성 판단에 사용."""
    if _engine is None:
        return {"ok": False, "engine": None, "ready": False}
    return {"ok": True, "engine": _engine.name, "ready": _engine.ready()}


@app.post("/punctuate", response_model=PunctuateResponse)
def punctuate(req: PunctuateRequest) -> PunctuateResponse:
    """원문 텍스트를 받아 표점을 붙여 반환.

    - 빈 문자열은 즉시 빈 결과를 돌려준다 (네트워크 왕복 비용은 그대로).
    - 엔진 미준비(ready=False) 상태에서 호출되면 503 — 본체가 LLM 표점 등 다른 경로로 폴백 가능.
    - 추론 실패는 500. 본체에서 예외 메시지를 사용자에게 노출하기 적합한 형태로 가공할 것.
    """
    if _engine is None:
        raise HTTPException(status_code=503, detail="엔진이 초기화되지 않았습니다")
    if not _engine.ready():
        raise HTTPException(
            status_code=503,
            detail=f"엔진({_engine.name})이 아직 준비되지 않았습니다 (모델 미로드 등)",
        )
    if not req.text:
        return PunctuateResponse(engine=_engine.name, punctuated="", marks=[])
    try:
        result = _engine.punctuate(req.text)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        # 너무 자세한 내부 오류를 외부에 흘리지 않되, 디버그를 위해 메시지는 포함.
        raise HTTPException(status_code=500, detail=f"표점 추론 실패: {exc}") from exc
    return PunctuateResponse(engine=_engine.name, **result)
