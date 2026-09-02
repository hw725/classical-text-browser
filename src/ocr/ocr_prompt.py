"""LLM OCR 프롬프트 조립기 (D-081).

왜 조립하는가:
    예전 프롬프트는 「고전 텍스트 OCR 전문가」 한 줄 페르소나·규칙 5개·서사
    방향·언어가 전부였다. 그런데 이 시스템은 모델에게 말해 주지 않은 것을 이미
    갖고 있었다 — 서지(연대·문자 체계·판종), L3 블록 종류, 이체자 사전, 다른
    엔진의 결과. 비교 대상 저장소(korean-modern-document-ocr)는 이것들을
    시스템 프롬프트에 **손으로** 적어 품질을 올렸는데, 그러면 자료가 바뀔 때마다
    코드를 고쳐야 한다. 여기서는 저장소 안의 데이터에서 호출 시점에 조립한다.

다섯 조각:
    1. 고정 정책   — 보이는 대로 옮긴다 / 정규화 금지 / [?] / □ / 잡음 무시 / JSON만
    2. 문헌 지침   — bibliography.json + manifest.ocr_guidance 에서 자동 생성
    3. 블록 지침   — block_type 에 따른 한 줄 (resources/block_types.json)
    4. 자형 주의   — 문헌별 승인 이체자 쌍 (D-080). 정규화 지시가 아니라 주의 목록
    5. 앵커        — 같은 블록의 엔진 결과. «참고만 하라»

규칙은 짧게 둔다. 1순위 프로바이더가 소형 로컬 모델이라 긴 규칙 목록에서
지시 준수가 떨어진다. 효과가 더 확실한 앵커와 블록 종류에 투자한다.

불확실 표기:
    모델은 확신 없는 글자 뒤에 `[?]`를, 판독 불가 자리에 `□`를 쓴다.
    `parse_uncertainty()`가 마커를 걷어 내고 글자별 신뢰도를 돌려준다.
    예전에는 모든 글자에 0.9를 박았다 — 하류가 신뢰도로 오해할 가짜 값이었다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─── 신뢰도 상수 ─────────────────────────────────────────────────
# LLM은 글자별 확률을 내지 않는다. 마커로 세 단계만 구분한다.
CERTAIN_CONFIDENCE = 0.9  # 마커 없음
UNCERTAIN_CONFIDENCE = 0.5  # 글자 뒤 [?]
ILLEGIBLE_CONFIDENCE = 0.1  # □ (판독 불가 자리)

UNCERTAIN_MARK = "[?]"
ILLEGIBLE_CHAR = "□"

# ─── 1. 고정 정책 ────────────────────────────────────────────────
# 짧게. 한 줄에 규칙 하나. 번호는 모델이 참조할 수 있게 둔다.
POLICY_RULES = (
    "이미지에 보이는 글자를 **보이는 대로** 옮깁니다. 간체·신자체·정자 사이에서 "
    "바꾸지 않습니다(정규화 금지). 이체자·약자도 원문 자형 그대로 옮깁니다.",
    "한 글자라도 확신할 수 없으면 그 글자 **바로 뒤에** [?] 를 붙입니다. 예: 王戎[?]簡要",
    "판독이 불가능한 자리는 글자 수만큼 □ 를 씁니다. 원본에 없는 내용을 채워 넣지 않습니다.",
    "장서인·인장·광곽(테두리)·어미·여백의 낙서와 얼룩은 글자가 아닙니다. 옮기지 않습니다.",
    "한 줄(행)이 JSON의 한 항목입니다. 줄을 합치거나 나누지 않습니다.",
    "반드시 순수 JSON만 출력합니다. 설명·markdown·사고 과정을 포함하지 않습니다.",
)

OUTPUT_FORMAT_DESC = '출력 형식 (JSON):\n{"lines": [{"text": "첫째 줄"}, {"text": "둘째 줄"}, ...]}'

_DIRECTION_DESC = {
    "vertical_rtl": "세로쓰기 — 오른쪽 열부터 왼쪽으로, 각 열은 위에서 아래로",
    "vertical_ltr": "세로쓰기 — 왼쪽 열부터 오른쪽으로, 각 열은 위에서 아래로",
    "horizontal_ltr": "가로쓰기 — 위 행부터 아래로, 각 행은 왼쪽에서 오른쪽으로",
    "horizontal_rtl": "가로쓰기 — 위 행부터 아래로, 각 행은 오른쪽에서 왼쪽으로",
}

_LANGUAGE_DESC = {
    "classical_chinese": "고전 한문(漢文)",
    "korean": "한국어(한글·한자 혼용 가능)",
    "japanese": "일본어(한자·가나 혼용)",
    "mixed": "한자·한글 혼용",
}


def build_system_prompt() -> str:
    """시스템 프롬프트(고정 정책 + 출력 형식)를 만든다.

    출력: 문자열. 호출마다 같다 — 프로바이더의 프롬프트 캐시가 먹도록 문헌·블록
          정보는 사용자 프롬프트 쪽에 넣는다.
    """
    rules = "\n".join(f"{i}. {r}" for i, r in enumerate(POLICY_RULES, 1))
    return (
        "당신은 동아시아 고전·근대 문헌 OCR 전문가입니다. "
        "이미지의 글자를 정확하게 옮겨 JSON으로 반환합니다.\n\n"
        f"규칙:\n{rules}\n\n{OUTPUT_FORMAT_DESC}\n"
    )


# ─── 2. 문헌 지침 ────────────────────────────────────────────────


def build_document_guidance(manifest: Optional[dict], bibliography: Optional[dict]) -> str:
    """서지와 매니페스트에서 문헌 지침 문장을 만든다.

    입력: manifest — manifest.json 내용(ocr_guidance 를 볼 수 있다). None 허용.
          bibliography — bibliography.json 내용. None 허용.
    출력: 2~4문장. 아무 정보도 없으면 빈 문자열.

    왜 이 필드들인가: 연대·판종·문자 체계는 모델이 기대해야 할 글자 집합과 문체의
    사전 확률을 바꾼다. 15세기 목판본 한문과 1930년대 일본어 공문서는 헷갈리는
    글자도, 잡음의 모양도 다르다. 인명·지명 같은 도메인 어휘는 사용자가
    ocr_guidance 에 적는다 — 자료마다 다르므로 코드에 두지 않는다.
    """
    bib = bibliography or {}
    man = manifest or {}
    parts: list[str] = []

    title = bib.get("title") or man.get("title")
    if title:
        parts.append(f"문헌: {title}.")

    facts: list[str] = []
    if bib.get("date_created"):
        facts.append(f"성립·간행 {bib['date_created']}")
    if bib.get("edition_type"):
        facts.append(f"판종 {bib['edition_type']}")
    if bib.get("script"):
        facts.append(f"문자 체계 {bib['script']}")
    if bib.get("language"):
        lang = _LANGUAGE_DESC.get(bib["language"], bib["language"])
        facts.append(f"언어 {lang}")
    if bib.get("material_type"):
        facts.append(f"자료 유형 {bib['material_type']}")
    if facts:
        parts.append("; ".join(facts) + ".")

    guidance = (man.get("ocr_guidance") or "").strip()
    if guidance:
        parts.append(guidance)

    return " ".join(parts)


def load_document_guidance(doc_path: Path | str) -> str:
    """문헌 디렉터리에서 manifest.json·bibliography.json 을 읽어 지침을 만든다.

    입력: doc_path — documents/{doc_id} 경로.
    출력: 지침 문자열. 파일이 없거나 깨져 있으면 빈 문자열 — 지침이 없어도 OCR은
          돌아가야 한다. 읽기 실패는 로그로만 남긴다.
    """
    doc_path = Path(doc_path)
    manifest = _read_json_or_none(doc_path / "manifest.json")
    bibliography = _read_json_or_none(doc_path / "bibliography.json")
    return build_document_guidance(manifest, bibliography)


def _read_json_or_none(path: Path) -> Optional[dict]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
    except (OSError, ValueError) as e:
        logger.warning(f"문헌 지침용 파일을 읽지 못했습니다: {path} — {e}")
    return None


# ─── 3. 블록 지침 ────────────────────────────────────────────────

# block_types.json 의 설명은 «무엇인가»를 말한다. 여기서는 «어떻게 읽는가»를
# 덧붙인다. 읽는 법이 특별한 종류만 적고, 나머지는 설명만 쓴다.
_BLOCK_READING_HINTS = {
    "annotation": "작은 글자가 쌍행(두 줄)으로 배열되어 있으면 오른쪽 줄을 먼저, "
    "왼쪽 줄을 다음에 읽습니다. 본문 대자와 섞지 않습니다.",
    "marginal_note": "여백의 짧은 메모입니다. 본문과 이어 붙이지 않습니다.",
    "page_title": "판심의 제목·권차·장차 정보입니다. 보이는 글자만 옮깁니다.",
    "page_number": "장차(쪽 번호)입니다. 숫자·한자 숫자를 그대로 옮깁니다.",
    "seal": "인장 영역입니다. 인장의 글자는 옮기지 않고 빈 결과를 돌려줍니다.",
    "illustration": "그림 영역입니다. 그림 안의 글자가 아니면 빈 결과를 돌려줍니다.",
    "colophon": "간기입니다. 연호·간행처·간행자 표기를 정확히 옮깁니다.",
}

_BLOCK_TYPES_CACHE: Optional[dict] = None


def _load_block_types() -> dict:
    """resources/block_types.json 을 읽어 {id: {label, description}} 로 돌려준다. 캐시."""
    global _BLOCK_TYPES_CACHE
    if _BLOCK_TYPES_CACHE is not None:
        return _BLOCK_TYPES_CACHE
    path = Path(__file__).resolve().parent.parent.parent / "resources" / "block_types.json"
    table: dict = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for bt in data.get("block_types", []):
            table[bt["id"]] = {
                "label": bt.get("label", bt["id"]),
                "description": bt.get("description", ""),
            }
    except (OSError, ValueError, KeyError) as e:
        logger.warning(f"block_types.json 을 읽지 못했습니다: {e}")
    _BLOCK_TYPES_CACHE = table
    return table


def build_block_guidance(block_type: Optional[str]) -> str:
    """블록 종류에 따른 한 줄 지침. 모르는 종류나 None 이면 빈 문자열."""
    if not block_type or block_type == "unknown":
        return ""
    info = _load_block_types().get(block_type)
    label = info["label"] if info else block_type
    desc = (info["description"] if info else "").strip()
    hint = _BLOCK_READING_HINTS.get(block_type, "")
    text = f"이 영역은 «{label}»입니다."
    if desc:
        text += f" {desc}"
    if hint:
        text += f" {hint}"
    return text


# ─── 4. 자형 주의 목록 ───────────────────────────────────────────

MAX_VARIANT_HINTS = 30


def build_variant_hints(pairs: Optional[list]) -> str:
    """이체자 쌍 목록을 «주의 목록» 문장으로 만든다.

    입력: pairs — [["說","説"], ...] 또는 ["說/説", ...]. None·빈 목록이면 빈 문자열.
    출력: 한 문단. 상위 MAX_VARIANT_HINTS 개까지만.

    정규화 지시가 **아니다.** «이 둘은 헷갈리기 쉬우니 자형을 다시 보라»는 주의다.
    「臺가 맞다」고 배운 모델이 원본의 台를 臺로 바꾸는 과교정이 D-080이 막으려는
    것이다. 문장이 그 뜻을 명시한다.
    """
    if not pairs:
        return ""
    shown: list[str] = []
    for p in pairs[:MAX_VARIANT_HINTS]:
        if isinstance(p, str):
            shown.append(p)
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            shown.append(f"{p[0]}/{p[1]}")
    if not shown:
        return ""
    return (
        "이 문헌에서 헷갈리기 쉬운 자형 쌍(참고): "
        + "、".join(shown)
        + ". 어느 쪽이 맞다는 뜻이 아닙니다 — 이미지의 자형을 다시 보고 보이는 대로 옮깁니다."
    )


# ─── 5. 앵커 + 사용자 프롬프트 조립 ─────────────────────────────


def build_user_prompt(
    writing_direction: str,
    language: str,
    *,
    block_type: Optional[str] = None,
    doc_guidance: Optional[str] = None,
    variant_hints: Optional[list] = None,
    anchor_text: Optional[str] = None,
    context_before: Optional[str] = None,
    context_after: Optional[str] = None,
) -> str:
    """사용자 프롬프트를 조립한다.

    입력:
      writing_direction — vertical_rtl 등. language — classical_chinese 등.
      block_type        — L3 블록 종류. 없으면 블록 지침 생략.
      doc_guidance      — build_document_guidance() 결과. 없으면 생략.
      variant_hints     — 이체자 쌍 목록. 없으면 생략.
      anchor_text       — 같은 블록의 엔진 OCR 결과. 있으면 «참고만» 으로 첨부.
      context_before/after — 앞뒤 블록·쪽의 텍스트. 정밀 판독(D-082 2단계)에서 쓴다.
    출력: 문자열. 비어 있는 조각은 자리 자체가 빠진다.
    """
    direction = _DIRECTION_DESC.get(writing_direction, writing_direction)
    lang = _LANGUAGE_DESC.get(language, language)

    sections: list[str] = ["이 이미지의 텍스트를 읽어 JSON으로 반환하세요."]
    sections.append(f"서사 방향: {direction}\n언어: {lang}")

    if doc_guidance:
        sections.append(f"[문헌 정보]\n{doc_guidance}")
    block_line = build_block_guidance(block_type)
    if block_line:
        sections.append(f"[영역 정보]\n{block_line}")
    hints = build_variant_hints(variant_hints)
    if hints:
        sections.append(f"[자형 주의]\n{hints}")
    if context_before or context_after:
        ctx = []
        if context_before:
            ctx.append(f"앞 문맥: {context_before}")
        if context_after:
            ctx.append(f"뒤 문맥: {context_after}")
        sections.append(
            "[주변 문맥 — 이 영역 바깥의 글입니다. 옮기지 말고 판독에만 참고하세요]\n"
            + "\n".join(ctx)
        )
    if anchor_text:
        sections.append(
            "[1차 인식 결과 — 다른 OCR 엔진이 이 영역을 읽은 것입니다. 오독과 순서 오류가 "
            "있을 수 있으니 참고만 하고, 최종 판단은 이미지로 합니다]\n" + anchor_text
        )
    sections.append("JSON으로만 응답하세요.")
    return "\n\n".join(sections)


# ─── 불확실 표기 파싱 ────────────────────────────────────────────


def parse_uncertainty(text: str) -> tuple[str, list[float]]:
    """`[?]` 마커와 `□` 를 글자별 신뢰도로 바꾼다.

    입력: 모델이 돌려준 한 줄. 예: "王戎[?]簡要□"
    출력: (마커를 걷어 낸 텍스트, 공백 아닌 글자별 신뢰도 목록). 위 예 →
          ("王戎簡要□", [0.9, 0.5, 0.9, 0.9, 0.1])

    텍스트의 공백은 **보존**한다 — 가로쓰기 한글 문헌의 어절 경계가 여기서 사라지면
    L4와 PDF 텍스트 레이어에서 단어가 붙어 버린다. 신뢰도 목록은 공백을 건너뛴 글자
    순서다(엔진의 글자 목록이 공백을 세지 않기 때문). 마커가 문장 맨 앞에
    오면(붙일 글자가 없으면) 버린다. 마커 문자열 자체는 어떤 경우에도 텍스트에
    남지 않는다 — 남으면 PDF 텍스트 레이어에 «[?]»가 구워진다.
    """
    chars: list[str] = []
    confs: list[float] = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith(UNCERTAIN_MARK, i):
            if confs:
                confs[-1] = min(confs[-1], UNCERTAIN_CONFIDENCE)
            i += len(UNCERTAIN_MARK)
            continue
        ch = text[i]
        i += 1
        chars.append(ch)
        if ch.isspace():
            continue
        confs.append(ILLEGIBLE_CONFIDENCE if ch == ILLEGIBLE_CHAR else CERTAIN_CONFIDENCE)
    return "".join(chars).strip(), confs
