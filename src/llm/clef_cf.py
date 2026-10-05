"""Cloudflare Workers AI `@cf/cloudflare/clef` — 이미지를 받는 판정 모델 (D-135).

왜 있는가:
    자동 스캔의 «무슨 글인가»(활자·판본·손글씨·훈점·한글·백지)를 판정 모델로 묻는 자리는
    D-134에서 Perplexity `decider-27b`가 처음 맡았다. clef는 같은 계약(«state + 형이 정해진 질문 →
    확률 붙은 답», 글을 만들지 않는다 — System One 판정 모델, 27B)을 Cloudflare 위에서 주고 이미지를
    받는다. 무료 몫(하루 10,000 neurons)이 있어 이 PC에서는 이것을 이미지 판정의 기본으로 둔다
    (사용자 결정 2026-10-04). Decider는 선택지로 남는다.

무엇을 아는가 (사용자가 전한 Cloudflare 문서 요약, 2026-10-04 — 실측 아님):
    - `POST https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/@cf/cloudflare/clef`,
      `Authorization: Bearer <CLOUDFLARE_API_TOKEN>`.
    - 본문 `{model: "clef", state, questions, images: [data URL…]}` — 이미지는 Decider와 달리
      **state 안이 아니라 최상위 `images` 배열**이다. 최대 4장, PNG·JPEG·WebP, 한 장 디코드 4MiB·
      16MP 이하, 합계 디코드 8MiB 이하, 본문 13MiB 이하. 원격 주소(http)는 받지 않는다.
    - 응답은 한 겹 싸여 온다: `{"result": {"answers": …, "usage": …}, "success": true}` — 벗긴다.
    - 입력 토큰만 청구, 100만 토큰당 $0.24. 무료 몫 하루 10,000 neurons ≈ clef 입력 약 458K 토큰.
      비용 칸(cost_usd)은 단가로 환산한 **명목값**이다 — 무료 몫 안에서 돌았는지는 계정 화면이 안다.
    - 이미지 한 장이 몇 토큰인지는 문서에 없다. **한문·고서 이미지 정확도도 문서에 없다** —
      `scripts/eval_clef_survey.py`로 우리 자료에서 잰다. 재기 전 답은 «제안»이다.

키: CLOUDFLARE_API_TOKEN·CLOUDFLARE_ACCOUNT_ID — 환경변수 → 서고 `.env`(설정 화면 «판정 모델») →
    프로젝트 `.env` → **Windows 사용자 환경변수**(HKCU\\Environment).
    마지막 것은 키를 넣기 전에 떠 있던
    서버가 os.environ에 그 값을 갖지 못하기 때문이다. 값은 어디에도 출력하지 않는다.
"""

from __future__ import annotations

import base64
import os
import re
import sys
from collections.abc import Mapping, Sequence
from io import BytesIO
from typing import Any, Optional

from llm.jev import JevCallFailed, JevClient, resolve_key

CLEF_MODEL = "clef"
CLEF_URL_TEMPLATE = (
    "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/cloudflare/clef"
)
CLEF_INPUT_USD_PER_M = 0.24
CLEF_KEY_NAMES = ("CLOUDFLARE_API_TOKEN",)
CLEF_ACCOUNT_NAMES = ("CLOUDFLARE_ACCOUNT_ID",)

# 문서의 상한(사용자 전달 2026-10-04). 이름에 «MAX»가 붙은 것은 넘으면 서버가 거부하는 값이다
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 4 * 1024 * 1024  # 한 장, 디코드(=base64를 풀었을 때) 크기
MAX_IMAGE_PIXELS = 16_000_000  # 한 장 16MP
MAX_TOTAL_IMAGE_BYTES = 8 * 1024 * 1024  # 모든 장 합계
MAX_BODY_BYTES = 13 * 1024 * 1024  # JSON 본문 전체
# 위 값들은 «서버가 받는» 한도이고 모델의 문맥(65,536토큰)과는 별개다. 2026-10-04 평가에서 16MP 근처
# 쪽 이미지가 «예상 입력+출력 208,453토큰 > 65,536»으로 413(code 5021)을 받아 24장 중 12장을 잃었다.
# 종류·방향 판정에는 고해상도가 필요 없으므로 기본은 2MP로 줄여 보내고, 그래도 문맥 초과 413이 오면
# 오류문의 예상 토큰 수에 비례해 한 번 더 줄여 1회 다시 보낸다(ClefClient.ask).
DEFAULT_IMAGE_PIXELS = 2_000_000
CLEF_CONTEXT_TOKENS = 65_536
_CTX_RE = re.compile(r"\((\d+)\) exceeded this model context window limit \((\d+)\)")
_MIME_OK = {"image/png", "image/jpeg", "image/webp"}


def _win_user_env(name: str) -> Optional[str]:
    """Windows 사용자 환경변수(HKCU\\Environment)에서 값을 읽는다. Windows가 아니거나 없으면 None.

    왜 레지스트리를 직접 읽는가: 사용자 환경변수는 «그 뒤에 뜬» 프로세스만 물려받는다. 앱 서버를
    먼저 띄우고 키를 넣으면 os.environ에는 없고 여기에만 있다.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            v, _typ = winreg.QueryValueEx(k, name)
    except OSError:
        return None
    v = str(v or "").strip()
    return v or None


def resolve_cloudflare(names: Sequence[str], library_root=None) -> Optional[str]:
    """Cloudflare 값 하나를 찾는다. 순서: 환경변수 → 서고·프로젝트 .env → Windows 사용자 환경변수.

    Jev의 공용 키 파일은 보지 않는다(Jev 전용 개인 파일이다).
    """
    v = resolve_key(names=names, library_root=library_root, fallback_file=False)
    if v:
        return v
    for n in names:
        v = _win_user_env(n)
        if v:
            return v
    return None


def fit_image_clef(
    data: bytes,
    mime: str = "image/jpeg",
    max_bytes: int = MAX_IMAGE_BYTES,
    max_pixels: int = MAX_IMAGE_PIXELS,
) -> tuple[bytes, str]:
    """이미지 한 장을 clef 상한(max_pixels·max_bytes·PNG/JPEG/WebP) 안으로. 출력: (바이트, mime).

    max_pixels는 서버 한도(16MP)를 넘지 못한다.
    호출자(ClefClient)는 문맥 토큰을 지키려고 더 작게 준다.

    왜: 상한을 넘으면 서버가 거부한다 — 한 쪽을 통째로 잃지 않게 보내기 전에 줄인다.
    이미 상한 안이고 형식도 맞으면 그대로 둔다(다시 압축하면 화질만 잃는다).
    PIL이 없거나 못 읽는 바이트면 그대로 돌려준다 — 서버가 판단하게 한다.
    """
    try:
        from PIL import Image

        cap = min(int(max_pixels), MAX_IMAGE_PIXELS)
        img = Image.open(BytesIO(data))
        w, h = img.size
        if w * h <= cap and len(data) <= max_bytes and mime in _MIME_OK:
            return data, mime
        img = img.convert("RGB")
        if w * h > cap:
            scale = (cap / (w * h)) ** 0.5 * 0.99
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        # 바이트 상한 — JPEG 품질을 내리고, 그래도 넘으면 크기를 줄인다
        quality = 88
        while True:
            out = BytesIO()
            img.save(out, format="JPEG", quality=quality)
            blob = out.getvalue()
            if len(blob) <= max_bytes:
                return blob, "image/jpeg"
            if quality > 60:
                quality -= 10
            else:
                img = img.resize((max(1, int(img.width * 0.8)), max(1, int(img.height * 0.8))))
    except Exception:  # noqa: BLE001
        return data, mime


class ClefClient(JevClient):
    """Cloudflare clef — JevClient와 같은 ask·gate·백오프·사용 기록, 주소·키·본문·응답만 다르다."""

    PROVIDER = "cloudflare"
    DEFAULT_URL = ""  # 계정 id로 만든다(__init__)
    DEFAULT_MODEL = CLEF_MODEL
    URL_ENV = "CLOUDFLARE_CLEF_URL"
    KEY_NAMES = CLEF_KEY_NAMES
    KEY_FALLBACK_FILE = False
    INPUT_USD_PER_M = CLEF_INPUT_USD_PER_M
    ACCEPTS_IMAGES = True

    def __init__(self, *, account_id: Optional[str] = None, url: Optional[str] = None, **kw):
        """입력: JevClient와 같고 account_id(없으면 CLOUDFLARE_ACCOUNT_ID를 찾는다)가 더해진다."""
        lib = kw.get("library_root")
        if account_id is None:
            account_id = resolve_cloudflare(CLEF_ACCOUNT_NAMES, lib)
        self._account = (account_id or "").strip()
        if url is None and not os.environ.get(self.URL_ENV) and self._account:
            url = CLEF_URL_TEMPLATE.format(account=self._account)
        self.image_pixels = DEFAULT_IMAGE_PIXELS  # 문맥 초과 413을 받으면 ask가 줄인다
        super().__init__(url=url, **kw)

    def _resolve_key(self) -> Optional[str]:
        return resolve_cloudflare(self.KEY_NAMES, self._library_root)

    @property
    def has_key(self) -> bool:
        """토큰과 계정 id가 **둘 다** 있어야 부를 수 있다 — 하나만 있으면 «키 없음»으로 본다."""
        return bool(self._key) and bool(self._url)

    def ask(self, state, questions, *, images=(), purpose: str = "decision"):
        """JevClient.ask와 같다. 계정 id가 없거나 이미지가 5장 이상이면 보내기 전에 거부한다."""
        if self._key and not self._url:
            raise JevCallFailed("clef_no_account")
        if len(images) > MAX_IMAGES:
            raise JevCallFailed("clef_too_many_images", detail=f"{len(images)} > {MAX_IMAGES}")
        try:
            return super().ask(state, questions, images=images, purpose=purpose)
        except JevCallFailed as e:
            # 문맥 초과(413, 오류문에 «(예상) exceeded … (한도)»)이고 이미지가 있으면
            # 한 번만 줄여 다시 보낸다.
            # 이미지 토큰은 픽셀 수에 비례한다고 보고, 한도의 85%에 맞게 픽셀 상한을 줄인다.
            m = _CTX_RE.search(str(getattr(e, "detail", "") or ""))
            if not (images and getattr(e, "status", None) == 413 and m):
                raise
            est, limit = int(m.group(1)), int(m.group(2))
            self.image_pixels = max(200_000, int(self.image_pixels * (limit * 0.85) / est))
            return super().ask(state, questions, images=images, purpose=purpose)

    def _body(
        self, state: Any, questions: Mapping[str, Any], images: Sequence[tuple[bytes, str]]
    ) -> dict:
        """{model, state, questions, images?}. 이미지는 최상위 `images`에 data URL로.

        합계 8MiB를 넘을 장수면 장마다 몫(8MiB ÷ 장수)으로 더 줄인다. 그래도 본문이 13MiB를
        넘으면 보내기 전에 거부한다(서버가 거부할 것을 미리 — 호출 수를 쓰지 않는다).
        """
        body: dict = {"model": self.model, "state": state, "questions": dict(questions)}
        if images:
            share = min(MAX_IMAGE_BYTES, MAX_TOTAL_IMAGE_BYTES // len(images))
            urls = []
            for raw, mime in images:
                data, m = fit_image_clef(
                    raw, mime or "image/jpeg", max_bytes=share, max_pixels=self.image_pixels
                )
                urls.append(f"data:{m};base64,{base64.b64encode(data).decode('ascii')}")
            body["images"] = urls
        check_body_size(body)
        return body

    def _unwrap(self, payload: Any) -> Any:
        """{"result": {...}, "success": true} → result. success가 false면 실패로 올린다."""
        if not isinstance(payload, Mapping):
            return payload
        if payload.get("success") is False:
            errs = payload.get("errors") or []
            raise JevCallFailed("clef_error", detail=str(errs)[:300])
        inner = payload.get("result")
        return inner if isinstance(inner, Mapping) else payload


def check_body_size(body: dict) -> int:
    """본문 바이트 수. 상한(13MiB)을 넘으면 JevCallFailed — 시험과 평가 스크립트가 쓴다."""
    import json

    n = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
    if n > MAX_BODY_BYTES:
        raise JevCallFailed("clef_body_too_large", detail=f"{n} > {MAX_BODY_BYTES}")
    return n


def clef_status(library_root=None) -> dict:
    """키가 있는가만 — 네트워크를 쓰지 않는다. 출력: {provider, has_key, model}."""
    c = ClefClient(library_root=library_root, max_calls=0)
    return {"provider": c.PROVIDER, "has_key": c.has_key, "model": c.model}
