"""TypeSafe Jev(System One) 전송 계층 — 글을 만들지 않고 «판정»만 돌려주는 모델.

왜 여기 있는가:
    이 저장소의 `llm/providers/*`는 전부 **생성 모델**이다 — 프롬프트를 주면 글을 돌려주고,
    코드가 그 글에서 JSON을 건져 쓴다. Jev는 그 계열이 아니다. state(관찰한 것)와 **형이 정해진
    질문**을 주면 답은 확률이 붙은 판정 하나씩이고, 자유로운 글은 아예 나오지 않는다. 그래서
    «모델이 위치를 만들지 않고 고르기만 한다»(D-117·D-125)를 프롬프트로 부탁하는 대신
    **형식으로 강제**할 수 있다 — 없는 행 번호를 지어낼 자리가 없다.

    LlmRouter에 넣지 않은 까닭도 같다. 라우터의 계약은 «프롬프트 → 글»이고 Jev에는 글이 없다.
    화면의 「모델」 목록(생성 모델을 고르는 자리)에도 넣지 않는다.

무엇을 아는가:
    - 엔드포인트 `POST https://api.typesafe.ai/v1/systemone` — {state, model, questions}
      → {model, answers, usage}. 질문 형은 noul(예/아니오 확률)·choice(고르기)·score(등급).
    - 한 번에 여러 질문을 보낼 수 있고 **서로의 답을 보지 못한 채 병렬로** 평가된다.
      한 요청의 예산은 64k 토큰(state + 모든 질문), state + 가장 긴 질문 하나는 32k.
    - 입력만 청구된다($0.042/M, 2026-09-21 콘솔 확인). 응답에 cost가 없어 토큰으로 환산한다.
    - **텍스트 전용이다** — 이미지·오디오·비디오를 받지 않는다(공식 문서). 쪽 이미지를 봐야 하는
      일(판독 계획의 «무슨 글인가»)에는 쓸 수 없다.
    - **영어가 1차 훈련 언어이고 CJK는 정확도가 낮다고 문서가 스스로 밝힌다.** 한문 코퍼스에
      들이기 전에 반드시 재야 한다.

키:
    TYPESAFE_API_KEY → JEV_API_KEY → OPENROUTER_API_KEY 순으로 환경변수를 보고, 없으면 공용 키
    파일(`~/.claude/data/triage/.env`)을 **전부 읽은 뒤 같은 이름 순서로** 고른다. 파일에 적힌
    줄 순서가 우선순위를 뒤집으면 안 된다(llm_pipeline 2026-09-21 실측 사고: OpenRouter 키가
    위에 있어 직결 호출이 401이었다). 값은 어디에도 출력하지 않는다.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"
TYPESAFE_MODEL = "jev-latest"
INPUT_USD_PER_M = 0.042  # 입력만 청구된다 — 출력분은 청구서에 없다(2026-09-21)

KEY_ENV_FILE = pathlib.Path.home() / ".claude" / "data" / "triage" / ".env"
KEY_NAMES = ("TYPESAFE_API_KEY", "JEV_API_KEY", "OPENROUTER_API_KEY")


class JevGateExceeded(RuntimeError):
    """호출 상한을 넘었다 — 한 건도 쏘지 않고 거부한다(전역 규칙 11: 게이트는 도구 층에)."""


class JevCallFailed(RuntimeError):
    """호출이 실패했다. status는 HTTP 상태(없으면 None), detail은 본문 앞부분."""

    def __init__(self, message: str, *, status: Optional[int] = None, detail: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


def resolve_key(
    env_file: Optional[pathlib.Path] = None, names: Sequence[str] = KEY_NAMES
) -> Optional[str]:
    """API 키를 찾는다. 입력: 키 파일 경로(없으면 기본), 볼 이름들. 출력: 키 또는 None.

    환경변수를 이름 순서로 보고, 없으면 파일을 **전부 읽은 뒤** 같은 이름 순서로 고른다.
    줄 끝 주석(` # …`)과 따옴표를 떼고, 공백뿐인 값은 «없음»으로 본다 — 그대로 두면
    `Bearer  ` 같은 헤더가 나간다.
    """
    for name in names:
        v = os.environ.get(name)
        if v and v.strip():
            return v.strip()
    path = env_file or KEY_ENV_FILE
    if not path.exists():
        return None
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip().lstrip("﻿")
        if line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        k, _, v = line.partition("=")
        v = v.split(" #", 1)[0].strip().strip('"').strip("'").strip()
        if v:
            found.setdefault(k.strip(), v)
    for name in names:
        if name in found:
            return found[name]
    return None


def noul(answer: Any) -> Optional[float]:
    """noul 답에서 «예일 확률» 하나. 입력: answers의 값. 출력: 0~1 또는 None(형이 아니면)."""
    if not isinstance(answer, Mapping):
        return None
    v = answer.get("noul")
    if isinstance(v, bool):  # 파이썬에서 True는 int다 — 확률로 세면 안 된다
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def choice(answer: Any, allowed: Sequence[str]) -> tuple[Optional[str], Optional[float]]:
    """choice 답에서 (고른 것, 그 확률). 정해 둔 선택지가 아니면 (None, None) — 코드가 되돌린다."""
    if not isinstance(answer, Mapping):
        return None, None
    pick = answer.get("choice")
    probs = answer.get("probabilities")
    p = None
    if isinstance(probs, Mapping) and isinstance(pick, str):
        v = probs.get(pick)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            p = float(v)
    return (pick if isinstance(pick, str) and pick in allowed else None), p


def _int(v: Any) -> int:
    """토큰 수. 문자열로 와도 센다 — 조용히 0이 되면 «공짜로 돌았다»로 보고된다."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v.strip())
        except ValueError:
            return 0
    return 0


class JevClient:
    """state + questions → answers. 호출 수·토큰·비용을 스스로 센다.

    입력(생성자): api_key(없으면 resolve_key), url(JEV_BASE_URL로도 덮는다), model,
    max_calls(상한 — 넘으면 네트워크 전에 거부), timeout, retries(429·529에만).
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        url: Optional[str] = None,
        model: Optional[str] = None,
        max_calls: int = 60,
        timeout: float = 120.0,
        retries: int = 3,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self._key = (api_key if api_key is not None else resolve_key() or "").strip()
        self._url = url or os.environ.get("JEV_BASE_URL") or TYPESAFE_URL
        self.model = model or TYPESAFE_MODEL
        self._max_calls = max_calls
        self._timeout = timeout
        self._retries = max(0, int(retries))
        self._opener = opener
        self.calls_made = 0
        self.questions_asked = 0
        self.input_tokens_total = 0
        self.output_tokens_total = 0
        self.cost_total = 0.0
        self.uncosted_calls = 0  # 비용을 셀 근거(usage)가 없던 호출 — 0이 «공짜»인지 구분한다

    @property
    def has_key(self) -> bool:
        return bool(self._key)

    def gate(self, planned: int) -> None:
        """보내기 전에 부른다. 상한을 넘으면 한 건도 쏘지 않는다."""
        if planned > self._max_calls:
            raise JevGateExceeded(
                f"호출 {planned}회가 상한 {self._max_calls}회를 넘습니다 — 실행을 거부합니다. "
                f"max_calls를 올리거나 보낼 양을 줄이세요."
            )

    def ask(self, state: str, questions: Mapping[str, Any]) -> Mapping[str, Any]:
        """한 번 부른다. 입력: state(관찰한 것), questions({id: {type, instructions, …}}).
        출력: answers({id: 답}). 실패는 JevCallFailed, 상한 초과는 JevGateExceeded.

        429(한도)·529(과부하)만 지수 백오프로 다시 시도한다 — 400(질문이 잘못됨)은
        다시 보내도 같은 답이라 바로 올린다.
        """
        if not self._key:
            raise JevCallFailed("jev_no_key")
        if self.calls_made >= self._max_calls:
            raise JevGateExceeded(f"상한 {self._max_calls}회에 이미 도달했습니다.")
        body = {"state": state, "model": self.model, "questions": dict(questions)}
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        delay = 1.0
        for attempt in range(self._retries + 1):
            req = urllib.request.Request(
                self._url,
                data=data,
                method="POST",
                headers={
                    "authorization": f"Bearer {self._key}",
                    "content-type": "application/json",
                },
            )
            self.calls_made += 1
            self.questions_asked += len(body["questions"])
            try:
                with self._opener(req, timeout=self._timeout) as resp:
                    payload = json.load(resp)
                break
            except urllib.error.HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8", "replace")[:300]
                except Exception:  # noqa: BLE001
                    detail = ""
                if exc.code in (429, 529) and attempt < self._retries:
                    logger.warning("Jev %s — %.1f초 뒤 다시 시도합니다", exc.code, delay)
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise JevCallFailed("jev_http_error", status=exc.code, detail=detail) from exc
            except (OSError, ValueError) as exc:
                if attempt < self._retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise JevCallFailed("jev_transport_error") from exc

        usage = payload.get("usage") if isinstance(payload, Mapping) else None
        if isinstance(usage, Mapping):
            seen_in = _int(usage.get("input_tokens")) or _int(usage.get("prompt_tokens"))
            self.input_tokens_total += seen_in
            self.output_tokens_total += _int(usage.get("output_tokens"))
            reported = usage.get("cost")
            if isinstance(reported, (int, float)) and not isinstance(reported, bool):
                self.cost_total += float(reported)  # 게이트웨이가 준 값이 정본이다
            else:
                self.cost_total += seen_in * INPUT_USD_PER_M / 1_000_000
                if not seen_in:
                    self.uncosted_calls += 1
        else:
            self.uncosted_calls += 1

        answers = payload.get("answers") if isinstance(payload, Mapping) else None
        if not isinstance(answers, Mapping):
            raise JevCallFailed("jev_invalid_response")
        return answers

    def usage(self) -> dict:
        """지금까지 쓴 것. 출력: calls·questions·input_tokens·output_tokens·cost_usd·uncosted."""
        return {
            "calls": self.calls_made,
            "questions": self.questions_asked,
            "input_tokens": self.input_tokens_total,
            "output_tokens": self.output_tokens_total,
            "cost_usd": round(self.cost_total, 6),
            "uncosted_calls": self.uncosted_calls,
        }
