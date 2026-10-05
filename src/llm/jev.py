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
    TYPESAFE_API_KEY → JEV_API_KEY 순으로, 이름마다 환경변수 → **서고 `.env`**(설정 화면
    «판정 모델»에서 넣은 키, D-134) → 프로젝트 `.env` → 공용 키 파일(`~/.claude/data/triage/.env`,
    **전부 읽은 뒤 같은 이름 순서로**)을 본다. 파일에 적힌 줄 순서가 우선순위를 뒤집으면 안 된다
    (llm_pipeline 2026-09-21 실측 사고: OpenRouter 키가 위에 있어 직결 호출이 401이었다).
    값은 어디에도 출력하지 않는다.

    **OPENROUTER_API_KEY는 여기서 보지 않는다**(D-136 후속, 2026-10-05). 전에는 이름 목록 끝에
    있어 OpenRouter 키만 있는 사람의 Jev가 그 키를 TypeSafe 주소로 보내 401을 받았다. 이제
    «어떤 키도 남의 주소로 나가지 않는다» — OpenRouter 키만 있으면 `make_jev_client`가
    같은 Jev를 OpenRouter 경유(`openrouter_decider.OpenRouterJevClient`)로 부른다.

판정 모델 공통 계약 (D-134):
    같은 «state + 형이 정해진 질문 → 확률 붙은 답» 계약을 쓰는 다른 업체(Perplexity Decisions —
    이미지를 받는다)는 `llm/decider.py`가 이 클래스를 물려받아 주소·모델·이미지 싣는 법만 바꾼다.
    호출 상한·백오프·토큰/비용 세기·사용 기록은 여기 한 곳에 있다.
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
# TypeSafe 직결 주소로 보내도 되는 키만. OPENROUTER_API_KEY를 넣지 않는다(위 «키» 참고).
KEY_NAMES = ("TYPESAFE_API_KEY", "JEV_API_KEY")

# 이 저장소가 아는 판정 업체의 호스트(PROVIDER → 그 업체 호스트). 주소 재정의(URL_ENV)가
# **다른 업체**의 호스트를 가리키면 키를 싣지 않고 거부한다 — TypeSafe 키가 OpenRouter로,
# OpenRouter 키가 Perplexity로 나가는 길을 막는다(Codex 리뷰 2026-10-06). 같은 업체 주소와
# 모르는 호스트(자체 게이트웨이·Cloudflare AI Gateway 등)는 지금처럼 허용한다.
# llm_pipeline 정본 `jev_decisions.py`의 «JEV_BASE_URL 은 직결 공급자에만 듣는다»와 같은 방침.
# 앞에 점이 없는 값은 그 호스트와 그 하위 도메인을 뜻한다. Cloudflare는 API 호스트만 —
# `gateway.ai.cloudflare.com`(AI Gateway)은 자체 게이트웨이로 본다.
VENDOR_HOSTS: dict[str, tuple[str, ...]] = {
    "typesafe": ("typesafe.ai",),
    "openrouter": ("openrouter.ai",),
    "perplexity": ("perplexity.ai",),
    "cloudflare": ("api.cloudflare.com",),
}


def vendor_of_url(url: str) -> Optional[str]:
    """주소의 호스트가 아는 판정 업체면 그 PROVIDER, 아니면 None(자체 게이트웨이 등)."""
    from urllib.parse import urlsplit

    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    for provider, hosts in VENDOR_HOSTS.items():
        if any(host == h or host.endswith("." + h) for h in hosts):
            return provider
    return None


class JevGateExceeded(RuntimeError):
    """호출 상한을 넘었다 — 한 건도 쏘지 않고 거부한다(전역 규칙 11: 게이트는 도구 층에)."""


class JevCallFailed(RuntimeError):
    """호출이 실패했다. status는 HTTP 상태(없으면 None), detail은 본문 앞부분."""

    def __init__(self, message: str, *, status: Optional[int] = None, detail: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


def _key_from_app_env(names: Sequence[str], library_root: Optional[pathlib.Path]) -> Optional[str]:
    """서고 `.env`·프로젝트 `.env`(LlmConfig와 같은 규칙 — 서고가 이긴다)에서 이름 순서로 찾는다.

    설정 화면에서 넣은 키가 여기 있다(D-134). 전에는 Jev가 이 파일을 보지 않아,
    화면에서 키를 넣을 길이 생겨도 Jev는 «키 없음»이었을 것이다.
    """
    try:
        from llm.config import LlmConfig
    except ImportError:  # 패키지 밖에서 단독으로 쓸 때
        return None
    cache = LlmConfig(library_root=library_root)._env_cache
    for name in names:
        v = (cache.get(name) or "").split(" #", 1)[0].strip()
        if v:
            return v
    return None


def resolve_key(
    env_file: Optional[pathlib.Path] = None,
    names: Sequence[str] = KEY_NAMES,
    library_root: Optional[pathlib.Path] = None,
    fallback_file: bool = True,
) -> Optional[str]:
    """API 키를 찾는다. 입력: 키 파일 경로(없으면 기본), 볼 이름들, 서고 루트,
    fallback_file(False면 공용 키 파일을 보지 않는다 — Jev 전용 개인 파일이라
    다른 업체에는 안 쓴다).
    출력: 키 또는 None.

    순서: 환경변수 → 서고·프로젝트 `.env` → 공용 키 파일. 파일은 **전부 읽은 뒤** 같은 이름
    순서로 고른다. 줄 끝 주석(` # …`)과 따옴표를 떼고, 공백뿐인 값은 «없음»으로 본다 —
    그대로 두면 `Bearer  ` 같은 헤더가 나간다.
    """
    # **이름이 먼저다** — 이름마다 환경변수 → 서고·프로젝트 .env → 공용 키 파일 순으로
    # 본 뒤 다음 이름으로 간다. 출처를 먼저 돌면 .env의 OPENROUTER_API_KEY가 키 파일의
    # TYPESAFE_API_KEY를 이겨 직결 주소로 남의 키가 나간다(2026-09-21 401 사고의 재현 —
    # 2026-10-02 검토 지적).
    file_found = _read_key_file(env_file, fallback_file)
    for name in names:
        v = os.environ.get(name)
        if v and v.strip():
            return v.strip()
        if env_file is None:
            v = _key_from_app_env((name,), library_root)
            if v:
                return v
        if name in file_found:
            return file_found[name]
    return None


def _read_key_file(env_file: Optional[pathlib.Path], fallback_file: bool) -> dict[str, str]:
    """키 파일을 **전부 읽어** {이름: 값}. 줄 순서는 우선순위가 아니다(이름 순서가 정한다)."""
    if env_file is None and not fallback_file:
        return {}
    path = env_file or KEY_ENV_FILE
    if not path.exists():
        return {}
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
    return found


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
    max_calls(상한 — 넘으면 네트워크 전에 거부), timeout, retries(429·529에만),
    library_root(키를 찾을 서고 — 설정 화면이 넣은 키, 그리고 사용 기록을 남길 자리).

    다른 업체로 물려받을 때 바꾸는 것(클래스 속성): PROVIDER·DEFAULT_URL·DEFAULT_MODEL·
    URL_ENV·KEY_NAMES·KEY_FALLBACK_FILE·INPUT_USD_PER_M·ACCEPTS_IMAGES, 그리고 `_body`
    (필요하면 `_resolve_key`·`_unwrap`도 — Cloudflare clef, D-135).
    """

    PROVIDER = "typesafe"
    DEFAULT_URL = TYPESAFE_URL
    DEFAULT_MODEL = TYPESAFE_MODEL
    URL_ENV = "JEV_BASE_URL"
    KEY_NAMES: tuple[str, ...] = KEY_NAMES
    KEY_FALLBACK_FILE = True
    INPUT_USD_PER_M = INPUT_USD_PER_M
    ACCEPTS_IMAGES = False  # Jev는 텍스트만 받는다(공식 문서) — 이미지를 주면 보내기 전에 거부

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
        library_root: Optional[pathlib.Path] = None,
    ) -> None:
        self._library_root = pathlib.Path(library_root) if library_root else None
        if api_key is None:
            api_key = self._resolve_key()
        self._key = (api_key or "").strip()
        env_url = None if url else (os.environ.get(self.URL_ENV) or "").strip() or None
        self._url = url or env_url or self.DEFAULT_URL
        # 주소가 **다른 판정 업체**를 가리키면 이 클래스의 키를 거기 보내지 않는다(VENDOR_HOSTS).
        # 생성은 막지 않는다(설정 화면의 키 유무 조회가 깨지지 않게) — ask가 보내기 전에 거부한다.
        self._url_refusal: Optional[str] = None
        other = vendor_of_url(self._url) if self._url else None
        if other is not None and other != self.PROVIDER:
            source = f"환경변수 {self.URL_ENV}" if env_url else "주소 인자(url)"
            self._url_refusal = (
                f"{source}가 다른 판정 업체({other})의 주소를 가리킵니다 — {self.PROVIDER} 키를 "
                f"그 주소로 보내지 않습니다. {self.URL_ENV}를 지우거나 {self.PROVIDER} 주소·"
                f"자체 게이트웨이로 바꾸세요."
            )
            logger.warning("%s", self._url_refusal)
        self.model = model or self.DEFAULT_MODEL
        self._max_calls = max_calls
        self._timeout = timeout
        self._retries = max(0, int(retries))
        self._opener = opener
        # 두 숫자를 따로 센다(2026-10-05 리뷰 143):
        #   asks_made  — 논리 호출(ask 한 번 = 질문 묶음 하나).
        #                **상한(max_calls)은 이것을 센다.**
        #   calls_made — 실제로 나간 HTTP 요청(429·529 백오프, clef 413 축소 재전송 포함).
        #                사용 보고용.
        # 왜 나누는가: 호출자는 상한을 «보낼 묶음 수 + 여유»로 잡는다(gate(planned)도 묶음
        # 수와 견준다). 그런데 ask가 HTTP 요청을 세어 상한과 견주면, 거부된 요청(429·413 —
        # 청구되지 않는다)이 상한을 갉는다. 자동 스캔에서 Cloudflare 413 재전송이 쌓이면 쪽
        # 수의 절반쯤에서 상한이 차고, 남은 쪽이 유료 OpenRouter로 밀려났다. 재전송은 묻기
        # 하나 안에서 retries(+413 1회)로 이미 묶여 있으므로 HTTP 요청의 최대는
        # max_calls × (retries+1) × 2로 여전히 유한하다.
        self.asks_made = 0
        # 이번 묻기를 asks_made에 이미 셌는가 — _send가 **실제로 보내기 직전에** 센다.
        # 본문 크기 초과처럼 보내기 전에 거절된 묻기는 상한을 쓰지 않는다(Codex 리뷰 2026-10-06).
        self._ask_counted = False
        self.calls_made = 0
        self.questions_asked = 0
        self.input_tokens_total = 0
        self.output_tokens_total = 0
        self.cost_total = 0.0
        self.uncosted_calls = 0  # 비용을 셀 근거(usage)가 없던 호출 — 0이 «공짜»인지 구분한다

    def _resolve_key(self) -> Optional[str]:
        """키를 찾는다 — 물려받는 업체가 출처를 더할 수 있게 메서드로 둔다.

        Cloudflare(clef_cf.py)는 여기에 «Windows 사용자 환경변수»를 더한다: 키를 거기 넣은 뒤
        이미 떠 있던 서버 프로세스는 os.environ에 그 값이 없기 때문이다.
        """
        return resolve_key(
            names=self.KEY_NAMES,
            library_root=self._library_root,
            fallback_file=self.KEY_FALLBACK_FILE,
        )

    def _unwrap(self, payload: Any) -> Any:
        """응답 본문 → {answers, usage} 모양. Jev·Decider는 그대로다.

        Cloudflare는 {"result": {...}, "success": true}로 한 겹 싸서 준다 — 물려받아 벗긴다.
        """
        return payload

    @property
    def has_key(self) -> bool:
        return bool(self._key)

    def gate(self, planned: int) -> None:
        """보내기 전에 부른다. **남은** 예산(상한 − 이미 쓴 묻기)을 넘으면 한 건도 쏘지 않는다.

        전에는 상한 전체와 견주어, 이미 몇 번 물은 클라이언트도 게이트를 통과한 뒤 중간에
        JevGateExceeded로 멈췄다(Codex 리뷰 2026-10-06). 지금 호출부는 모두 새 클라이언트에서
        부르므로(asks_made 0) 그쪽 동작은 같다.
        """
        remaining = self._max_calls - self.asks_made
        if planned > remaining:
            raise JevGateExceeded(
                f"호출 {planned}회가 남은 예산 {max(remaining, 0)}회(상한 {self._max_calls}회 중 "
                f"{self.asks_made}회 사용)를 넘습니다 — 실행을 거부합니다. "
                f"max_calls를 올리거나 보낼 양을 줄이세요."
            )

    def _body(
        self, state: Any, questions: Mapping[str, Any], images: Sequence[tuple[bytes, str]]
    ) -> dict:
        """요청 본문. Jev: {state, model, questions}.

        이미지를 싣는 법은 업체마다 달라 물려받아 바꾼다.
        """
        return {"state": state, "model": self.model, "questions": dict(questions)}

    def ask(
        self,
        state: Any,
        questions: Mapping[str, Any],
        *,
        images: Sequence[tuple[bytes, str]] = (),
        purpose: str = "decision",
    ) -> Mapping[str, Any]:
        """한 번 부른다. 입력: state(관찰한 것), questions({id: {type, instructions, …}}),
        images([(바이트, mime)] — 이미지를 받는 업체만), purpose(사용 기록에 남길 용도).
        출력: answers({id: 답}). 실패는 JevCallFailed, 상한 초과는 JevGateExceeded.

        429(한도)·529(과부하)만 지수 백오프로 다시 시도한다 — 400(질문이 잘못됨)은
        다시 보내도 같은 답이라 바로 올린다. 429에 Retry-After가 있으면 그만큼 기다린다.

        상한은 **묻기 횟수**(asks_made)로 센다 — 다시 보내기는 같은 묻기다(__init__ 주석).
        세는 때는 실제로 보내기 직전이다(_send) — 보내기 전 로컬 검증에서 거절되면 세지 않는다.
        """
        if not self._key:
            raise JevCallFailed("jev_no_key")
        if self._url_refusal:
            raise JevCallFailed("url_points_to_other_vendor", detail=self._url_refusal)
        if images and not self.ACCEPTS_IMAGES:
            # Jev에 base64를 넣으면 오류 없이 «글자로» 읽어 엉뚱한 답이 온다(2026-10-02 실측) —
            # 보내기 전에 막는다
            raise JevCallFailed("images_not_supported")
        if self.asks_made >= self._max_calls:
            raise JevGateExceeded(f"상한 {self._max_calls}회에 이미 도달했습니다.")
        self._ask_counted = False
        return self._send(state, questions, images, purpose)

    def _send(
        self,
        state: Any,
        questions: Mapping[str, Any],
        images: Sequence[tuple[bytes, str]],
        purpose: str,
    ) -> Mapping[str, Any]:
        """묻기 하나를 HTTP로 보낸다(백오프 포함). 상한 검사는 ask가 이미 했다.

        물려받는 업체가 «같은 묻기를 고쳐 다시 보내기»(clef 413 축소)를 여기에 얹는다 —
        ask를 두 번 부르면 묻기 두 번으로 세어진다.
        """
        body = self._body(state, questions, images)
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        # 본문을 다 만들었다 — 여기서부터는 실제로 보낸다. 묻기 하나에 한 번만 센다
        # (clef 413 축소 재전송은 같은 묻기라 _ask_counted가 이미 True다).
        if not self._ask_counted:
            self.asks_made += 1
            self._ask_counted = True
        delay = 1.0
        started = time.monotonic()
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
                    wait = delay
                    retry_after = (exc.headers or {}).get("Retry-After") if exc.headers else None
                    try:
                        if retry_after is not None:
                            wait = min(60.0, max(wait, float(retry_after)))
                    except (TypeError, ValueError):
                        pass
                    logger.warning(
                        "%s %s — %.1f초 뒤 다시 시도합니다", self.PROVIDER, exc.code, wait
                    )
                    time.sleep(wait)
                    delay *= 2
                    continue
                raise JevCallFailed("jev_http_error", status=exc.code, detail=detail) from exc
            except (OSError, ValueError) as exc:
                if attempt < self._retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise JevCallFailed("jev_transport_error") from exc

        payload = self._unwrap(payload)
        usage = payload.get("usage") if isinstance(payload, Mapping) else None
        seen_in = seen_out = 0
        call_cost = 0.0
        if isinstance(usage, Mapping):
            seen_in = _int(usage.get("input_tokens")) or _int(usage.get("prompt_tokens"))
            seen_out = _int(usage.get("output_tokens"))
            self.input_tokens_total += seen_in
            self.output_tokens_total += seen_out
            reported = usage.get("cost")
            if isinstance(reported, (int, float)) and not isinstance(reported, bool):
                call_cost = float(reported)  # 게이트웨이가 준 값이 정본이다
            else:
                call_cost = seen_in * self.INPUT_USD_PER_M / 1_000_000
                if not seen_in:
                    self.uncosted_calls += 1
            self.cost_total += call_cost
        else:
            self.uncosted_calls += 1
        self._log_usage(seen_in, seen_out, call_cost, time.monotonic() - started, purpose)

        answers = payload.get("answers") if isinstance(payload, Mapping) else None
        if not isinstance(answers, Mapping):
            raise JevCallFailed("jev_invalid_response")
        return answers

    def _log_usage(
        self, tokens_in: int, tokens_out: int, cost: float, elapsed: float, purpose: str
    ) -> None:
        """서고의 LLM 사용 기록(llm_usage_log.jsonl)에 한 줄 — 생성 모델과 같은 파일·같은 모양.

        전에는 판정 모델 호출이 어디에도 남지 않아 «이번 달 얼마 썼나»에서 빠졌다(D-134).
        기록 실패는 호출을 실패시키지 않는다.
        """
        try:
            from llm.config import LlmConfig
            from llm.providers.base import LlmResponse
            from llm.usage_tracker import UsageTracker

            UsageTracker(LlmConfig(library_root=self._library_root)).log(
                LlmResponse(
                    text="",
                    provider=self.PROVIDER,
                    model=self.model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost,
                    elapsed_sec=round(elapsed, 3),
                ),
                purpose=purpose,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("판정 모델 사용 기록 실패: %s", e)

    def usage(self) -> dict:
        """지금까지 쓴 것. 출력: calls(HTTP 요청, 재전송 포함)·asks(묻기 — 상한이 세는 것)·
        questions·input_tokens·output_tokens·cost_usd·uncosted_calls."""
        return {
            "calls": self.calls_made,
            "asks": self.asks_made,
            "questions": self.questions_asked,
            "input_tokens": self.input_tokens_total,
            "output_tokens": self.output_tokens_total,
            "cost_usd": round(self.cost_total, 6),
            "uncosted_calls": self.uncosted_calls,
        }


def make_jev_client(
    *, library_root: Optional[pathlib.Path] = None, max_calls: int = 60, **kwargs: Any
) -> JevClient:
    """Jev를 부를 클라이언트를 고른다 — **키마다 제 주소로만** (D-136 후속, 2026-10-05).

    입력: library_root(키를 찾을 서고), max_calls(호출 상한), 나머지는 클라이언트 생성자에 그대로
          (timeout·retries·opener 등).
    출력: 셋 중 하나.
      - TypeSafe 키(TYPESAFE_API_KEY·JEV_API_KEY)가 있으면 → `JevClient`(TypeSafe 직결)
      - 없고 OpenRouter 키가 있으면 → `OpenRouterJevClient`(같은 Jev를 OpenRouter 경유로,
        `~typesafe/jev-latest`)
      - 둘 다 없으면 → 키 없는 `JevClient`(has_key False — 호출하면 jev_no_key)

    왜 이렇게 고르는가: 사용자 결정(2026-10-05) «OpenRouter 키만 있으면 Jev를 OpenRouter 경유로
    부른다». 둘 다 있으면 직결이 먼저인 까닭은 그것이 측정한 기본 길이고(D-129), OpenRouter 크레딧을
    본문 decider 몫으로 남기기 위해서다.

    클래스는 **부를 때** 모듈에서 찾는다 — 시험이 `llm.jev.JevClient`·
    `llm.openrouter_decider.OpenRouterJevClient`를 가짜로 바꿔 끼울 수 있게.
    """
    direct = JevClient(library_root=library_root, max_calls=max_calls, **kwargs)
    if direct.has_key:
        return direct
    from llm import openrouter_decider  # 순환 import 피함(그 모듈이 이 모듈을 물려받는다)

    via = openrouter_decider.OpenRouterJevClient(
        library_root=library_root, max_calls=max_calls, **kwargs
    )
    return via if via.has_key else direct
