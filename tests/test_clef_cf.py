"""판정 모델 — Cloudflare Workers AI clef(이미지) (D-135). 네트워크 없이 가짜 opener로만 잰다.

무엇을 고정하는가:
  - 주소는 계정 id로 만든다(…/accounts/{id}/ai/run/@cf/cloudflare/clef), Bearer 토큰
  - 본문은 {model:"clef", state, questions, images:[data URL]} — 이미지는 state 안이 아니라 최상위
  - 응답 {"result": {...}, "success": true}를 벗겨 answers·usage를 읽는다. success=false는 실패
  - 이미지 상한: 4장 초과는 보내기 전에 거부, 16MP·4MiB를 넘는 장은 줄인다, 합계 8MiB, 본문 13MiB
  - 키: 환경변수 → 서고 .env → Windows 사용자 환경변수. 토큰과 계정 id가 둘 다 있어야 «키 있음»
  - 자동 스캔이 force_provider="clef"면 clef의 확률로 종류를 정하고, 키가 없으면 400(needs_key)
  - 설정 상태가 키 있을 때 default_image_provider="clef"를 준다(화면이 미리 고른다)
"""

from __future__ import annotations

import base64
import io
import json

import pytest

import llm.clef_cf as clef
from llm.clef_cf import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    ClefClient,
    fit_image_clef,
)
from llm.jev import JevCallFailed


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _cf_opener(capture: list, answers: dict, usage=None, success=True):
    """Cloudflare 모양으로 싸서 돌려주는 가짜 opener."""

    def op(req, timeout=None):
        capture.append(req)
        payload = {
            "result": {"answers": answers, "usage": usage or {"input_tokens": 2000}},
            "success": success,
            "errors": [] if success else [{"code": 5006, "message": "bad input"}],
            "messages": [],
        }
        return _Resp(json.dumps(payload).encode())

    return op


def _img(w: int, h: int, fmt: str = "PNG", noise: bool = False) -> bytes:
    from PIL import Image

    if noise:
        import os

        im = Image.frombytes("RGB", (w, h), os.urandom(w * h * 3))
    else:
        im = Image.new("RGB", (w, h), "white")
    buf = io.BytesIO()
    im.save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _no_ambient_cloudflare(monkeypatch, tmp_path):
    """이 PC의 Cloudflare 키(환경변수·Windows 사용자 환경변수·프로젝트 .env)를 섞지 않는다."""
    import llm.jev as jev

    # OPENROUTER_API_KEY도 — clef 사슬의 2단계라 그 키만 있어도 «clef 키 있음»이 된다(D-135 후속)
    for k in (
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_CLEF_URL",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(clef, "_win_user_env", lambda name: None)
    monkeypatch.setattr(jev, "KEY_ENV_FILE", tmp_path / "no-personal-key-file.env")

    def library_only(names, library_root):
        if not library_root:
            return None
        p = library_root / ".env"
        if not p.exists():
            return None
        vals = dict(
            ln.split("=", 1) for ln in p.read_text(encoding="utf-8").splitlines() if "=" in ln
        )
        return next((vals[n].strip() for n in names if vals.get(n, "").strip()), None)

    monkeypatch.setattr(jev, "_key_from_app_env", library_only)


def test_body_shape_url_and_unwrap(tmp_path):
    cap: list = []
    c = ClefClient(
        api_key="cf-tok",
        account_id="acc123",
        opener=_cf_opener(cap, {"q": {"type": "noul", "noul": 0.8}}),
        library_root=tmp_path,
    )
    ans = c.ask(
        "한 쪽", {"q": {"type": "noul", "instructions": "?"}}, images=[(_img(40, 30), "image/png")]
    )
    assert ans == {"q": {"type": "noul", "noul": 0.8}}  # result를 벗겼다
    req = cap[0]
    assert (
        req.full_url
        == "https://api.cloudflare.com/client/v4/accounts/acc123/ai/run/@cf/cloudflare/clef"
    )
    assert req.get_header("Authorization") == "Bearer cf-tok"
    body = json.loads(req.data)
    assert set(body) == {"model", "state", "questions", "images"}
    assert (
        body["model"] == "clef" and body["state"] == "한 쪽"
    )  # state는 글 그대로 — 이미지 안 섞임
    assert len(body["images"]) == 1 and body["images"][0].startswith("data:image/png;base64,")
    assert base64.b64decode(body["images"][0].split(",", 1)[1]) == _img(40, 30)
    # usage는 result 안에 있다 — 벗기지 않으면 0토큰(«공짜»)으로 잘못 센다
    assert c.usage()["input_tokens"] == 2000
    assert c.usage()["cost_usd"] == pytest.approx(2000 * 0.24 / 1e6)


def _decoded_pixels(data_url: str) -> int:
    from PIL import Image

    im = Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1])))
    return im.width * im.height


def test_default_image_cap_is_two_megapixels(tmp_path):
    # 서버 한도(16MP)가 아니라 문맥 토큰을 지키는 2MP로 줄여 보낸다
    # (2026-10-04 평가: 큰 쪽 12장이 413)
    cap: list = []
    c = ClefClient(
        api_key="t",
        account_id="a",
        library_root=tmp_path,
        opener=_cf_opener(cap, {"q": {"type": "noul", "noul": 0.5}}),
    )
    c.ask(
        "s", {"q": {"type": "noul", "instructions": "?"}}, images=[(_img(3000, 3000), "image/png")]
    )
    px = _decoded_pixels(json.loads(cap[0].data)["images"][0])
    assert px <= clef.DEFAULT_IMAGE_PIXELS


def test_default_image_bytes_cap_300kb(tmp_path):
    # 2MP여도 JPEG가 크면(빽빽한 글·종이 질감) 서버가 바이트로 어림해 413을 낸다(2026-10-05) —
    # 성공한 범위(≤304KB) 안인 300KB로 맞춰 보낸다
    cap: list = []
    c = ClefClient(
        api_key="t",
        account_id="a",
        library_root=tmp_path,
        opener=_cf_opener(cap, {"q": {"type": "noul", "noul": 0.5}}),
    )
    c.ask(
        "s",
        {"q": {"type": "noul", "instructions": "?"}},
        images=[(_img(1400, 1400, fmt="PNG", noise=True), "image/png")],
    )
    url = json.loads(cap[0].data)["images"][0]
    assert len(base64.b64decode(url.split(",", 1)[1])) <= clef.DEFAULT_IMAGE_BYTES


def test_context_overflow_413_shrinks_and_retries_once(tmp_path):
    import urllib.error

    sent: list = []
    msg = (
        '{"errors":[{"message":"AiError: Ai: The estimated number of input and '
        "maximum output tokens (208453) exceeded this model context window limit "
        '(65536). (x)","code":5021}],"success":false}'
    )
    ok = _cf_opener(sent, {"q": {"type": "noul", "noul": 0.7}})
    state = {"n": 0}

    def op(req, timeout=None):
        state["n"] += 1
        if state["n"] == 1:
            sent.append(req)
            raise urllib.error.HTTPError(
                req.full_url, 413, "too large", {}, io.BytesIO(msg.encode())
            )
        return ok(req, timeout)

    c = ClefClient(api_key="t", account_id="a", library_root=tmp_path, opener=op)
    ans = c.ask(
        "s", {"q": {"type": "noul", "instructions": "?"}}, images=[(_img(3000, 3000), "image/png")]
    )
    assert ans["q"]["noul"] == 0.7
    first, second = (_decoded_pixels(json.loads(r.data)["images"][0]) for r in sent)
    assert second < first  # 오류문의 예상 토큰 수에 비례해 줄였다
    assert c.image_pixels < clef.DEFAULT_IMAGE_PIXELS


def test_413_without_images_is_not_retried(tmp_path):
    import urllib.error

    calls = {"n": 0}

    def op(req, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(
            req.full_url,
            413,
            "too large",
            {},
            io.BytesIO(
                b'{"errors":[{"message":"(70000) exceeded this model '
                b'context window limit (65536)"}]}'
            ),
        )

    c = ClefClient(api_key="t", account_id="a", library_root=tmp_path, opener=op)
    with pytest.raises(JevCallFailed):
        c.ask("긴 글", {"q": {"type": "noul", "instructions": "?"}})
    assert calls["n"] == 1


def test_no_images_field_without_images():
    cap: list = []
    ClefClient(api_key="t", account_id="a", opener=_cf_opener(cap, {})).ask(
        "s", {"q": {"type": "noul", "instructions": "?"}}
    )
    assert "images" not in json.loads(cap[0].data)


def test_success_false_is_failure():
    cap: list = []
    c = ClefClient(api_key="t", account_id="a", opener=_cf_opener(cap, {}, success=False))
    with pytest.raises(JevCallFailed, match="clef_error"):
        c.ask("s", {"q": {"type": "noul", "instructions": "?"}})


def test_more_than_four_images_refused_before_sending():
    cap: list = []
    c = ClefClient(api_key="t", account_id="a", opener=_cf_opener(cap, {}))
    imgs = [(_img(10, 10), "image/png")] * 5
    with pytest.raises(JevCallFailed, match="clef_too_many_images"):
        c.ask("s", {}, images=imgs)
    assert cap == [] and c.calls_made == 0


def test_fit_image_limits():
    from PIL import Image

    # 16MP를 넘는 장은 줄인다(희게 칠한 큰 PNG — 바이트는 작아도 화소가 넘는다)
    big = _img(5000, 4000)
    data, mime = fit_image_clef(big, "image/png")
    w, h = Image.open(io.BytesIO(data)).size
    assert w * h <= MAX_IMAGE_PIXELS and mime == "image/jpeg"
    # 4MiB를 넘는 장은 바이트 상한 안으로(잡음 PNG는 압축이 안 된다)
    noisy = _img(1400, 1400, noise=True)
    assert len(noisy) > MAX_IMAGE_BYTES
    data, mime = fit_image_clef(noisy, "image/png")
    assert len(data) <= MAX_IMAGE_BYTES and mime == "image/jpeg"
    # 상한 안이면 그대로(다시 압축하지 않는다)
    small = _img(400, 300)
    assert fit_image_clef(small, "image/png") == (small, "image/png")
    # 받지 않는 형식(GIF)은 JPEG로
    gif = _img(50, 50, fmt="GIF")
    assert fit_image_clef(gif, "image/gif")[1] == "image/jpeg"


def test_total_image_bytes_shared_across_images():
    """장마다 4MiB 안이어도 합계 8MiB를 넘으면 장마다 몫(8MiB÷장수)으로 줄인다."""
    cap: list = []
    noisy = _img(1100, 1100, noise=True)  # PNG ≈ 3.5MiB — 한 장 상한 안
    assert 2 * 1024 * 1024 < len(noisy) <= MAX_IMAGE_BYTES
    ClefClient(api_key="t", account_id="a", opener=_cf_opener(cap, {})).ask(
        "s", {}, images=[(noisy, "image/png")] * 4
    )
    imgs = json.loads(cap[0].data)["images"]
    total = sum(len(base64.b64decode(u.split(",", 1)[1])) for u in imgs)
    assert total <= 8 * 1024 * 1024
    assert len(cap[0].data) <= 13 * 1024 * 1024


def test_key_resolution_order(tmp_path, monkeypatch):
    """환경변수 → 서고 .env → Windows 사용자 환경변수. 토큰·계정 id가 둘 다 있어야 has_key."""
    lib = tmp_path / "lib"
    lib.mkdir()
    # 아무것도 없으면 키 없음
    assert not ClefClient(library_root=lib).has_key
    # 레지스트리(Windows 사용자 환경변수)만 있어도 찾는다 — 키를 넣기 전에 뜬 서버를 위해
    reg = {"CLOUDFLARE_API_TOKEN": "tok-reg", "CLOUDFLARE_ACCOUNT_ID": "acc-reg"}
    monkeypatch.setattr(clef, "_win_user_env", lambda name: reg.get(name))
    c = ClefClient(library_root=lib)
    assert c.has_key and c._key == "tok-reg" and "/accounts/acc-reg/" in c._url
    # 서고 .env가 레지스트리를 이긴다
    (lib / ".env").write_text(
        "CLOUDFLARE_API_TOKEN=tok-lib\nCLOUDFLARE_ACCOUNT_ID=acc-lib\n", encoding="utf-8"
    )
    c = ClefClient(library_root=lib)
    assert c._key == "tok-lib" and "/accounts/acc-lib/" in c._url
    # 환경변수가 모두를 이긴다
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok-env")
    assert ClefClient(library_root=lib)._key == "tok-env"


def test_token_without_account_is_not_a_key(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / ".env").write_text("CLOUDFLARE_API_TOKEN=tok-only\n", encoding="utf-8")
    c = ClefClient(library_root=lib, opener=_cf_opener([], {}))
    assert not c.has_key
    with pytest.raises(JevCallFailed, match="clef_no_account"):
        c.ask("s", {})


def test_clef_is_logged_as_cloudflare(tmp_path):
    ClefClient(api_key="t", account_id="a", opener=_cf_opener([], {}), library_root=tmp_path).ask(
        "s", {"q": {"type": "noul", "instructions": "?"}}, purpose="page_survey"
    )
    log = (tmp_path / "llm_usage_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
    entry = json.loads(log[-1])
    assert entry["provider"] == "cloudflare" and entry["model"] == "clef"
    assert entry["tokens_in"] == 2000


# ── 라우트 ──

from tests.test_segmentation import _setup, client  # noqa: E402,F401 — fixture 재사용


def test_settings_default_image_provider_is_clef_with_keys(client, tmp_path):  # noqa: F811
    _setup(client, tmp_path)
    r = client.post(
        "/api/settings/llm-keys",
        json={"cloudflare": "cf-tokenABCD", "cloudflare_account": "acc-1234"},
    )
    assert r.status_code == 200, r.text
    assert "cf-tokenABCD" not in r.text  # 값은 돌려주지 않는다
    d = client.get("/api/settings/decision-models").json()
    cf = next(m for m in d["models"] if m["id"] == "cloudflare")
    assert cf["has_key"] is True and cf["extra_keys"] == ["cloudflare_account"]
    assert d["default_image_provider"] == "clef"


def test_survey_with_clef_uses_probabilities(client, tmp_path, monkeypatch):  # noqa: F811
    from core import env_doctor

    monkeypatch.setattr(env_doctor, "_GPU_RUNTIME", True)
    import app.routers.llm_ocr as llm_ocr

    async def _no_probe(force_provider):  # 미리 세기가 진짜 Ollama에 닿지 않게
        return {"checked": False, "ready": []}

    monkeypatch.setattr(llm_ocr, "_vision_readiness", _no_probe)
    _lib, part_id = _setup(client, tmp_path)
    url = f"/api/documents/d1/parts/{part_id}/rotation/suggest"

    r = client.post(url, json={"force_provider": "clef", "force_model": "clef"})
    assert r.status_code == 400 and r.json()["needs_key"] == "cloudflare"

    r = client.post(url, json={"dry_run": True, "force_provider": "clef"})
    assert r.json()["engine"] == "clef" and r.json()["cost_usd_est"] > 0

    sent: list = []

    def fake_ask(self, state, questions, *, images=(), purpose=""):
        sent.append((len(images), purpose))
        return {
            "orientation": {"choice": "upright", "probabilities": {"upright": 0.9}},
            "has_classical_print": {"noul": 0.88},
        }

    monkeypatch.setattr(clef.ClefClient, "has_key", property(lambda self: True))
    monkeypatch.setattr(clef.ClefClient, "ask", fake_ask)
    r = client.post(url, json={"force_provider": "clef", "force_model": "clef"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["provider"] == "cloudflare" and d["model"] == "clef"
    assert sent and all(n == 1 and p == "page_survey" for n, p in sent)
    assert d["per_page"][0]["contents"] == ["classical_print"]
    assert d["per_page"][0]["decider"]["contents"]["classical_print"] == 0.88


def test_openrouter_clef_body_puts_image_in_state_array():
    # OpenRouter는 이미지를 state 배열의 image_url로만 받는다
    # (최상위 images는 무시 — 2026-10-05 색 시험).
    # 키는 OPENROUTER_API_KEY만 — TypeSafe 키를 OpenRouter로 보내지 않는다
    from llm.openrouter_decider import OpenRouterClefClient

    assert OpenRouterClefClient.KEY_NAMES == ("OPENROUTER_API_KEY",)
    c = OpenRouterClefClient(api_key="or-test", max_calls=0)
    body = c._body(
        "한 쪽",
        {"q": {"type": "noul", "instructions": "?"}},
        [(_img(1400, 1400, fmt="PNG", noise=True), "image/png")],
    )
    assert body["model"] == "cloudflare/clef" and "images" not in body
    text, part = body["state"]
    assert text == "한 쪽" and part["type"] == "image_url"
    raw = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
    assert len(raw) <= clef.DEFAULT_IMAGE_BYTES  # 다시 인코딩해 커지지 않는다


def _survey_chain_setup(client, tmp_path, monkeypatch, or_ask):  # noqa: F811 — fixture를 받아 넘긴다
    """Cloudflare clef는 실패, OpenRouter clef는 or_ask로 답하는 자동 스캔 준비."""
    import app._state as app_state
    import app.routers.llm_ocr as llm_ocr
    from core import env_doctor
    from llm.openrouter_decider import OpenRouterClefClient

    monkeypatch.setattr(env_doctor, "_GPU_RUNTIME", True)
    _lib, part_id = _setup(client, tmp_path)

    def quota(self, *a, **k):
        raise JevCallFailed("jev_http_error", status=429, detail="daily free allocation")

    monkeypatch.setattr(clef.ClefClient, "has_key", property(lambda self: True))
    monkeypatch.setattr(clef.ClefClient, "ask", quota)
    monkeypatch.setattr(OpenRouterClefClient, "ask", or_ask)
    fake = OpenRouterClefClient(api_key="or-test", max_calls=10)
    monkeypatch.setattr(llm_ocr, "_openrouter_clef", lambda *a, **k: fake)
    seen: dict = {}

    class FakeRouter:
        async def call_with_image(self, prompt, image, **kw):
            seen["router"] = kw
            from types import SimpleNamespace

            return SimpleNamespace(
                text='{"orientation": "upright", "contents": []}',
                provider="ollama",
                model="kimi-k3:cloud",
            )

    monkeypatch.setattr(app_state, "_get_llm_router", lambda: FakeRouter())
    url = f"/api/documents/d1/parts/{part_id}/rotation/suggest"
    return url, seen


def test_survey_chain_cloudflare_to_openrouter(client, tmp_path, monkeypatch):  # noqa: F811
    # Cloudflare 무료량이 바닥나면 같은 쪽을 OpenRouter clef로 다시 묻고 뒤 쪽도 그쪽을 쓴다
    def or_ok(self, state, questions, *, images=(), purpose=""):
        return {
            "orientation": {"choice": "upright", "probabilities": {"upright": 0.9}},
            "has_classical_print": {"noul": 0.8},
        }

    url, seen = _survey_chain_setup(client, tmp_path, monkeypatch, or_ok)
    d = client.post(url, json={"force_provider": "clef", "force_model": "clef"}).json()
    assert d["fallback"] == "cloudflare→openrouter"
    assert d["provider"] == "openrouter" and d["model"] == "cloudflare/clef"
    assert "router" not in seen  # 비전 모델까지 가지 않았다
    assert "OpenRouter clef로" in (d["error"] or "")


def test_survey_chain_falls_through_to_vision(client, tmp_path, monkeypatch):  # noqa: F811
    # OpenRouter도 실패하면(크레딧 소진 등) 기본 비전 모델로
    def or_fail(self, *a, **k):
        raise JevCallFailed("jev_http_error", status=402, detail="insufficient credits")

    url, seen = _survey_chain_setup(client, tmp_path, monkeypatch, or_fail)
    d = client.post(url, json={"force_provider": "clef", "force_model": "clef"}).json()
    assert d["fallback"] == "cloudflare→openrouter→vision"
    assert d["provider"] == "ollama" and "router" in seen


def test_survey_falls_back_to_vision_llm_when_clef_fails(client, tmp_path, monkeypatch):  # noqa: F811
    # 무료량 소진 등으로 clef가 실패하면 그 쪽부터 기본 비전 모델로 넘긴다(2026-10-05 사용자 지시).
    # Jev는 이미지를 못 읽으므로 폴백은 비전 LLM이다
    from types import SimpleNamespace

    import app.routers.llm_ocr as llm_ocr
    from core import env_doctor

    monkeypatch.setattr(env_doctor, "_GPU_RUNTIME", True)
    _lib, part_id = _setup(client, tmp_path)
    url = f"/api/documents/d1/parts/{part_id}/rotation/suggest"

    def quota(self, *a, **k):
        raise JevCallFailed("jev_http_error", status=429, detail="daily free allocation")

    seen: dict = {}

    class FakeRouter:
        async def call_with_image(self, prompt, image, **kw):
            seen.update(kw)
            return SimpleNamespace(
                text='{"orientation": "upright", "contents": ["handwriting"]}',
                provider="ollama",
                model="kimi-k3:cloud",
            )

    monkeypatch.setattr(clef.ClefClient, "has_key", property(lambda self: True))
    monkeypatch.setattr(clef.ClefClient, "ask", quota)
    # 이 PC의 개인 키 파일에는 진짜 OpenRouter 키가 있다 — 사슬 2단계를 끄고 이 시험은 3단계만 본다
    monkeypatch.setattr(llm_ocr, "_openrouter_clef", lambda *a, **k: None)
    # 자동 스캔 라우트는 함수 안에서 `from app._state import _get_llm_router`로 가져온다 —
    # llm_ocr의 이름만 바꾸면 진짜 라우터가 진짜 Ollama를 부른다
    # (2026-10-05 이 시험이 그렇게 새고 있었다)
    import app._state as app_state

    monkeypatch.setattr(app_state, "_get_llm_router", lambda: FakeRouter())
    monkeypatch.setattr(llm_ocr, "_get_llm_router", lambda: FakeRouter())
    r = client.post(url, json={"force_provider": "clef", "force_model": "clef"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["fallback"] == "clef→vision"
    # 비전 모델이 답했다(시험 쪽은 흰 바탕이라 내용은 코드의 백지 판정이 덮을 수 있다)
    assert d["provider"] == "ollama" and d["model"] == "kimi-k3:cloud"  # 가짜 라우터의 답
    assert "decider" not in d["per_page"][0]
    # "clef"를 라우터에 넘기지 않고 화면의 종류 판정 기본 모델로 바꿔 보낸다
    from core.page_survey import SURVEY_FALLBACK_MODEL

    assert (seen["force_provider"], seen["force_model"]) == SURVEY_FALLBACK_MODEL
    assert "이 쪽부터 기본 비전 모델로" in (d["error"] or "")
