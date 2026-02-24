"""라우터 공통 상태 및 헬퍼.

모든 라우터가 이 모듈에서 get_library_path(), _get_llm_router() 등을 import한다.
순환 import 방지를 위해 이 모듈은 core/llm/ocr 모듈만 lazy-import한다.
"""

import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 전역 상태 ─────────────────────────────────

_library_path: Path | None = None
_llm_router = None
_llm_drafts: dict = {}
_ocr_registry = None
_ocr_pipeline = None

# 저장소 ID 패턴: 영문 소문자로 시작, 소문자·숫자·밑줄만 허용 (최대 64자)
# document.py의 _DOC_ID_PATTERN, interpretation.py의 _INTERP_ID_PATTERN과 동일한 규칙.
# 경로 탈출(../ 등)을 원천 차단하기 위해 API 계층에서도 검증한다.
_REPO_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


# ── 상태 접근 함수 ───────────────────────────

def get_library_path() -> Path | None:
    """현재 서고 경로를 반환한다."""
    return _library_path


def set_library_path(path: Path | None):
    """서고 경로를 설정한다. LLM 라우터 캐시도 리셋된다."""
    global _library_path, _llm_router
    _library_path = path
    _llm_router = None  # 서고 전환 시 LLM 라우터 리셋


def get_llm_drafts() -> dict:
    """LLM 초안 저장소를 반환한다 (메모리 — 서버 재시작 시 소멸)."""
    return _llm_drafts


def configure_library(library_path: str | Path):
    """서고 경로를 설정하고 건강 검사를 수행한다.

    목적: 서버 시작 전(또는 런타임에 서고 전환 시) 서고 경로를 지정한다.

    서고 전환 시 주의:
        - LLM 라우터 캐시를 초기화한다 (서고별 .env가 다를 수 있음).
        - 최근 서고 목록에 추가한다.
        - Git 건강 검사를 수행한다.
    """
    resolved = Path(library_path).resolve()
    set_library_path(resolved)

    # 최근 서고 목록에 추가
    try:
        from core.app_config import add_recent_library
        lib_name = resolved.name
        # library_manifest.json에서 이름 읽기 (있으면)
        manifest_path = resolved / "library_manifest.json"
        if manifest_path.exists():
            import json
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            lib_name = manifest.get("name", lib_name)
        add_recent_library(str(resolved), lib_name)
    except Exception as e:
        logger.debug(f"최근 서고 기록 실패 (무시): {e}")

    # Git 건강 검사 — .git 내부 파일 오염 자동 탐지 및 수리
    try:
        from core.library import check_git_health, repair_git_contamination
        contaminated = check_git_health(resolved)
        if contaminated:
            logger.warning(
                "Git 오염 발견: %d개 저장소에서 .git/ 파일이 추적 중",
                len(contaminated),
            )
            for item in contaminated:
                logger.warning(
                    "  - %s/%s: %d개 파일 오염",
                    item["repo_type"], item["repo_id"],
                    len(item["contaminated_files"]),
                )
                repair_result = repair_git_contamination(item["repo_path"])
                if repair_result["repaired"]:
                    logger.info(
                        "  → 자동 수리 완료 (%s): %d개 파일 제거",
                        repair_result["method"],
                        repair_result["files_removed"],
                    )
                else:
                    logger.error(
                        "  → 자동 수리 실패: %s",
                        repair_result.get("error", "알 수 없는 오류"),
                    )
    except Exception as e:
        logger.debug(f"Git 건강 검사 실패 (무시): {e}")


# ── LLM 라우터 ────────────────────────────────

def _get_llm_router():
    """LLM Router를 lazy-init한다.

    왜 lazy-init인가:
        _library_path는 serve 명령에서 설정된다.
        LlmConfig가 서고의 .env를 읽으려면 경로가 필요하다.
    """
    global _llm_router
    if _llm_router is None:
        from llm.config import LlmConfig
        from llm.router import LlmRouter
        config = LlmConfig(library_root=_library_path)
        _llm_router = LlmRouter(config)
    return _llm_router


# ── OCR 파이프라인 ────────────────────────────

def _get_ocr_pipeline():
    """OCR Pipeline과 Registry를 lazy-init한다.

    왜 lazy-init인가:
        _library_path는 serve 명령에서 설정된다.
        OcrPipeline은 library_root가 필요하므로 앱 초기화 후에 생성해야 한다.
    """
    global _ocr_registry, _ocr_pipeline
    if _ocr_registry is None:
        from ocr.registry import OcrEngineRegistry
        from ocr.pipeline import OcrPipeline

        _ocr_registry = OcrEngineRegistry()
        _ocr_registry.auto_register()

        # LLM Vision OCR 엔진에 라우터 주입
        # auto_register()에서 LlmOcrEngine이 등록되었으면, 라우터를 연결한다.
        # register() 시점에는 라우터가 없어 is_available()=False였으므로
        # 기본 엔진도 여기서 설정한다.
        llm_engine = _ocr_registry._engines.get("llm_vision")
        if llm_engine is not None:
            router = _get_llm_router()
            llm_engine.set_router(router)
            if _ocr_registry._default_engine_id is None and llm_engine.is_available():
                _ocr_registry._default_engine_id = "llm_vision"

        _ocr_pipeline = OcrPipeline(_ocr_registry, library_root=str(_library_path))

    return _ocr_pipeline, _ocr_registry


# ── 경로 해석 ────────────────────────────────

def _resolve_repo_path(repo_type: str, repo_id: str) -> Path | None:
    """repo_type("documents"/"interpretations")과 repo_id로 저장소 경로를 결정한다.

    왜 이렇게 하는가:
        원본 저장소와 해석 저장소를 단일 엔드포인트로 처리하기 위해
        repo_type 문자열을 검증하고 경로를 반환한다.
        repo_id도 정규식으로 검증하여 경로 탈출(path traversal)을 방지한다.
    """
    if _library_path is None:
        return None
    if repo_type not in ("documents", "interpretations"):
        return None
    if not _REPO_ID_PATTERN.match(repo_id):
        return None
    return _library_path / repo_type / repo_id


# ===========================================================================
#  LLM 공통 프롬프트 + 호출 헬퍼
# ===========================================================================
#
# 왜 여기에 모아두는가:
#   reading, annotation 라우터가 공유하는 LLM 호출 로직이다.
#   _get_llm_router()가 프로바이더 폴백(base44_bridge → ollama → openai → anthropic)을
#   관리하므로, 각 기능은 프롬프트만 다르고 호출 방식은 동일하다.
#
# 커스텀 방법:
#   1. 프롬프트 수정: _LLM_PROMPTS 딕셔너리를 수정
#   2. 프로바이더 변경: force_provider 파라미터로 특정 프로바이더 지정
#   3. 모델 변경: force_model 파라미터로 특정 모델 지정
#   4. 새 기능 추가: _get_llm_router().call() 또는 .call_with_image() 호출
# ===========================================================================

# ─── LLM 프롬프트 템플릿 (수정 용이하도록 분리) ──────────────

_LLM_PROMPTS = {
    "punctuation": {
        "system": (
            "당신은 고전 한문 표점(句讀) 전문가입니다.\n"
            "주어진 원문에 현대 학술 표점부호를 삽입하세요.\n\n"
            "사용 가능한 부호: 。，、；：？！《》〈〉「」『』\n\n"
            "규칙:\n"
            "- 문장이 끝나면(句) 。\n"
            "- 절이 이어지면(讀) ，\n"
            "- 단순 나열·병렬(竝列)은 、\n"
            "- 대구·열거가 길면 ；\n"
            "- 서명은 《》, 편명은 〈〉\n"
            "- 인용은 「」\n"
            "- 의문문은 ？, 감탄문은 ！\n\n"
            "중요:\n"
            "- start/end는 0-based 글자 인덱스 (inclusive)\n"
            "- 단일 글자 뒤에 부호를 넣으면 start == end\n"
            "- 부호를 글자 뒤에 넣으려면 after에, 앞에 넣으려면 before에 넣으세요\n"
            "- 원문 글자를 절대 변경하지 마세요\n"
            "- JSON만 반환하세요. 설명 텍스트를 넣지 마세요.\n\n"
            "출력 형식:\n"
            '{"marks": [{"start": 1, "end": 1, "before": null, "after": "，"}, '
            '{"start": 3, "end": 3, "before": null, "after": "。"}]}'
        ),
        "user": "다음 고전 한문에 표점을 삽입하세요:\n\n원문({char_count}자): {text}",
    },
    "translation": {
        "system": (
            "당신은 고전 한문 번역 전문가입니다.\n"
            "주어진 문장을 한국어로 번역하세요.\n"
            "규칙:\n"
            "1. 원문의 뜻을 정확하게 전달하되, 자연스러운 한국어로 번역합니다.\n"
            "2. 고유명사(인명, 지명)는 한자를 병기합니다. 예: 왕융(王戎)\n"
            "3. 반드시 순수 JSON만 출력하세요.\n"
            "출력 형식:\n"
            '{"translation": "번역문", "notes": "번역 참고사항(선택)"}'
        ),
        "user": "다음 고전 한문을 한국어로 번역하세요:\n\n{text}",
    },
    "annotation": {
        "system": (
            "당신은 고전 한문 주석 전문가입니다.\n"
            "주어진 텍스트에서 주석이 필요한 항목을 태깅하세요.\n"
            "규칙:\n"
            "1. 인명(person), 지명(place), 관직(official_title), 서명(book_title), "
            "전고(allusion), 용어(term)를 식별합니다.\n"
            "2. 각 항목에 간단한 설명을 덧붙이세요.\n"
            "3. 원문의 시작 인덱스(start)와 끝 인덱스(end)를 포함하세요.\n"
            "4. 반드시 순수 JSON만 출력하세요.\n"
            "출력 형식:\n"
            '{"annotations": [{"text": "王戎", "type": "person", '
            '"start": 0, "end": 2, '
            '"label": "왕융(王戎)", "description": "竹林七賢의 한 사람"}]}'
        ),
        "user": "다음 고전 한문에서 주석 대상을 태깅하세요:\n\n{text}",
    },
}


async def _call_llm_text(purpose: str, text: str,
                          force_provider=None, force_model=None) -> dict:
    """공통 LLM 텍스트 호출. 프롬프트 템플릿 + JSON 파싱.

    왜 이렇게 하는가:
        표점, 번역, 주석 모두 동일한 패턴이다:
        1. 시스템 프롬프트 + 사용자 프롬프트 구성
        2. LLM 라우터로 호출
        3. JSON 응답 파싱
        4. 결과 반환

    커스텀:
        _LLM_PROMPTS 딕셔너리를 수정하면 프롬프트를 바꿀 수 있다.

    폴백 전략:
        자동 모드(force_provider 없음)에서 프로바이더가 JSON이 아닌
        거절 응답을 반환하면 다음 프로바이더로 자동 재시도한다.
        Base44 agent-chat은 MCP 도구 기반이라 자유 형식 텍스트 요청을
        "도구가 없습니다"로 거절할 수 있다.
    """
    import json as _json
    import asyncio as _asyncio

    prompts = _LLM_PROMPTS.get(purpose)
    if not prompts:
        raise ValueError(f"알 수 없는 LLM purpose: {purpose}")

    router = _get_llm_router()
    system_prompt = prompts["system"]
    user_prompt = prompts["user"].format(text=text, char_count=len(text))

    # thinking 모델(kimi-k2.5 등)은 사고 토큰 + 출력 토큰이 합산되므로
    # 4096으로는 사고에 다 쓰고 출력이 빈 응답이 될 수 있다.
    _MAX_TOKENS = 16384

    # 표점·번역·주석 모두 JSON 출력을 기대한다.
    # response_format="json"을 전달하면 각 프로바이더가 네이티브 JSON 모드를 활성화:
    #   Gemini: response_mime_type="application/json" (thinking 유출 방지)
    #   OpenAI: response_format={"type":"json_object"}
    #   Ollama: format="json"
    _RESPONSE_FORMAT = "json"

    # ── force_provider가 지정된 경우: 해당 프로바이더만 시도 (빈 응답·에러 시 1회 재시도) ──
    if force_provider:
        response = None
        last_error = None
        for _attempt in range(2):
            try:
                response = await router.call(
                    user_prompt,
                    system=system_prompt,
                    response_format=_RESPONSE_FORMAT,
                    force_provider=force_provider,
                    force_model=force_model,
                    purpose=purpose,
                    max_tokens=_MAX_TOKENS,
                )
                last_error = None
                if response.text.strip():
                    break
                logger.warning(
                    f"LLM {purpose} — {force_provider}/{force_model or 'auto'} "
                    f"빈 응답 (시도 {_attempt+1}/2), "
                    f"tokens_out={getattr(response, 'tokens_out', '?')}"
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    f"LLM {purpose} — {force_provider} 에러 (시도 {_attempt+1}/2): {e}"
                )
        # 재시도 후에도 에러가 남아 있으면 전파
        if last_error:
            raise last_error
        return _parse_llm_json(response, _json)

    # ── 자동 모드: 프로바이더 순서대로 시도, JSON 파싱 실패 시 다음으로 ──
    # 가용성을 병렬로 사전 체크 (캐시 활용).
    # Base44(subprocess 5s) + Ollama(HTTP 3s) 순차 체크 → 최대 8초 낭비 방지.
    avail_results = await _asyncio.gather(
        *[router.is_available_cached(p) for p in router.providers],
        return_exceptions=True,
    )

    errors = []
    tried = []
    for provider, avail in zip(router.providers, avail_results):
        if avail is not True:
            logger.debug(f"LLM {purpose} — {provider.provider_id}: 사용 불가, 건너뜀")
            continue

        try:
            tried.append(provider.provider_id)
            logger.info(f"LLM {purpose} — {provider.provider_id} 시도 중...")

            response = await provider.call(
                user_prompt,
                system=system_prompt,
                response_format=_RESPONSE_FORMAT,
                max_tokens=_MAX_TOKENS,
                purpose=purpose,
            )
            router.usage_tracker.log(response, purpose=purpose)

            logger.info(
                f"LLM {purpose} — {provider.provider_id}/{response.model} 응답 수신 "
                f"(길이={len(response.text)}, tokens_out={response.tokens_out})"
            )

            # JSON 파싱 시도 — 실패하면 다음 프로바이더로
            return _parse_llm_json(response, _json)

        except Exception as e:
            logger.warning(
                f"LLM {purpose} — {provider.provider_id} 실패: {e}"
            )
            errors.append(f"{provider.provider_id}: {e}")
            continue

    raise ValueError(
        f"모든 LLM 프로바이더가 {purpose} 요청에 실패했습니다 "
        f"(시도: {', '.join(tried) if tried else '없음'}):\n"
        + "\n".join(f"  - {e}" for e in errors)
    )


async def _call_llm_text_stream(purpose: str, text: str,
                                 queue,
                                 force_provider=None, force_model=None):
    """스트리밍 LLM 호출. asyncio.Queue에 SSE 이벤트를 넣는다.

    왜 별도 함수인가:
        기존 _call_llm_text()를 수정하지 않고, SSE 엔드포인트 전용으로 추가.
        queue에 {"type":"progress",...}, {"type":"complete",...}, {"type":"error",...}를 넣는다.
        엔드포인트는 queue에서 꺼내 StreamingResponse로 전달한다.

    이벤트 형식:
        progress: {"type":"progress","elapsed_sec":N,"tokens":N,"provider":"..."}
        complete: {"type":"complete","result":{...파싱된 JSON...}}
        error:    {"type":"error","error":"에러 메시지"}
    """
    import json as _json
    import asyncio as _asyncio

    prompts = _LLM_PROMPTS.get(purpose)
    if not prompts:
        await queue.put({"type": "error", "error": f"알 수 없는 LLM purpose: {purpose}"})
        return

    router = _get_llm_router()
    system_prompt = prompts["system"]
    user_prompt = prompts["user"].format(text=text, char_count=len(text))
    _MAX_TOKENS = 16384
    _RESPONSE_FORMAT = "json"

    def _progress_cb(event):
        """provider의 progress_callback → queue에 넣기.

        왜 call_soon_threadsafe가 아닌가:
            progress_callback은 같은 이벤트 루프의 async for 내에서 호출되므로
            put_nowait()으로 충분하다.
        """
        try:
            queue.put_nowait(event)
        except Exception:
            pass  # queue full — 무시 (progress는 best-effort)

    try:
        if force_provider:
            response = await router.call_stream(
                user_prompt,
                system=system_prompt,
                response_format=_RESPONSE_FORMAT,
                force_provider=force_provider,
                force_model=force_model,
                purpose=purpose,
                max_tokens=_MAX_TOKENS,
                progress_callback=_progress_cb,
            )
        else:
            # 자동 모드에서도 call_stream 사용
            response = await router.call_stream(
                user_prompt,
                system=system_prompt,
                response_format=_RESPONSE_FORMAT,
                purpose=purpose,
                max_tokens=_MAX_TOKENS,
                progress_callback=_progress_cb,
            )

        # JSON 파싱 (_parse_llm_json 재사용)
        result = _parse_llm_json(response, _json)
        await queue.put({"type": "complete", "result": result})

    except Exception as e:
        logger.error(f"LLM stream {purpose} 실패: {e}")
        await queue.put({"type": "error", "error": str(e)})


def _parse_llm_json(response, _json) -> dict:
    """LLM 응답에서 JSON을 추출한다.

    왜 별도 함수인가:
        _call_llm_text의 자동 폴백에서 반복 사용.
        파싱 실패 시 ValueError를 발생시켜 다음 프로바이더로 넘긴다.

    처리 순서:
        1. 빈 응답 감지
        2. <think>...</think> thinking 태그 제거
        3. markdown 코드 블록 제거
        4. JSON 파싱 (전체 → 부분 추출)
    """
    raw = response.text.strip()

    # 빈 응답 조기 감지 (OpenAI content_filter / refusal 등)
    if not raw:
        logger.warning(
            f"LLM 빈 응답 ({response.provider}/{response.model}) "
            f"— tokens_out={getattr(response, 'tokens_out', '?')}, "
            f"raw={getattr(response, 'raw', '?')}"
        )
        raise ValueError(
            f"{response.provider}({response.model})이(가) 빈 응답을 반환했습니다. "
            f"콘텐츠 필터링 또는 모델 오류일 수 있습니다."
        )

    # thinking 모델의 사고 과정 제거:
    #   1. <think>...</think> 태그 (Ollama kimi-k2.5, qwq 등)
    #   2. Gemini thinking 유출: JSON 없이 추론 텍스트만 반환되는 경우
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()

    # thinking 태그 제거 후 빈 응답이 되는 경우 (사고만 하고 출력 없음)
    if not raw:
        logger.warning(
            f"LLM thinking-only 응답 ({response.provider}/{response.model}) "
            f"— 사고 태그 제거 후 빈 응답"
        )
        raise ValueError(
            f"{response.provider}({response.model})이(가) 사고(thinking)만 반환하고 "
            f"실제 출력은 비어 있습니다."
        )

    # JSON이 아예 없고 reasoning 텍스트만 있는 경우 조기 감지
    # (Gemini thinking 유출: "Check...", "Correct.", "Wait," 같은 패턴)
    if '{' not in raw:
        logger.warning(
            f"LLM 응답에 JSON 없음 ({response.provider}/{response.model}): "
            f"{raw[:100]}..."
        )
        raise ValueError(
            f"{response.provider}({response.model}) 응답에 JSON이 없습니다. "
            f"모델이 구조화 출력 대신 자유 텍스트를 반환했습니다."
        )

    # markdown 코드 블록 제거
    if "```" in raw:
        parts = raw.split("```")
        if len(parts) >= 3:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError:
        # JSON 부분만 추출 시도 — 마지막 유효 JSON 객체를 찾는다.
        # rfind로 찾으면 thinking 잔여물이 아닌 실제 JSON을 잡을 가능성이 높다.
        start = raw.rfind('{"')
        if start < 0:
            start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = _json.loads(raw[start:end])
            except _json.JSONDecodeError:
                raise ValueError(
                    f"LLM 응답 JSON 파싱 실패 ({response.provider}): {raw[:200]}"
                )
        else:
            raise ValueError(
                f"LLM 응답에 JSON이 없음 ({response.provider}): {raw[:200]}"
            )

    data["_provider"] = response.provider
    data["_model"] = response.model
    return data
