"""LLM 답에서 «항목 목록»을 꺼내는 공통 파서 — 주석(L7)과 사전형 주석이 같은 것을 쓴다.

왜 하나로 모았는가(Codex 교차검증 2026-09-16 ⑥·⑦·⑪):
    사전형 주석 파서와 일반 주석 파서가 따로 있어 잘린 답에 한쪽은 1건·다른 쪽은 0건이었다.
    한쪽에 복구·검증을 고쳐도 다른 쪽엔 적용되지 않는다. 꺼내기·복구·진단은 여기서 한 번만 하고,
    기능마다 다른 «항목 하나의 검증»(좌표·범주)만 각 모듈에 남긴다.

무엇을 돌려주는가:
    - items — dict인 항목만. null·숫자·문자열 같은 기형 항목은 세어서 버린다(rejected).
      전에는 `parsed["annotations"]`를 타입 검사 없이 돌려줘 `None`이나 `[None]` 하나가
      정상 항목까지 끌고 500으로 끝났다.
    - status — "ok"(닫힌 JSON을 읽음) · "recovered"(답이 잘려 완성된 항목만 건짐) ·
      "no_json"(JSON이 없음). 화면이 «완료»와 «부분 완료»·«답을 읽지 못함»을 가르는 근거다.
      복구한 0건과 정상적인 0건은 다르다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class ParsedItems:
    """파싱 결과. items는 dict만 담는다."""

    items: list[dict] = field(default_factory=list)
    status: str = "ok"  # ok | recovered | no_json
    rejected: int = 0  # dict가 아니어서 버린 항목 수

    def diagnostics(self) -> dict:
        """API 응답·화면에 실을 요약."""
        return {
            "parse_status": self.status,
            "parsed_items": len(self.items),
            "rejected_items": self.rejected,
        }


def _strip_fence(text: str) -> str:
    """```json … ``` 울타리를 벗긴다. 닫는 울타리가 없으면(잘린 답) 여는 줄만 뗀다."""
    if "```" not in text:
        return text
    start = text.find("```")
    content_start = text.find("\n", start)
    if content_start == -1:
        return text
    end = text.find("```", content_start)
    if end == -1:
        return text[content_start:].strip()
    return text[content_start:end].strip()


def _only_dicts(seq) -> tuple[list[dict], int]:
    """목록에서 dict만 남기고 버린 개수를 함께 돌려준다. 목록이 아니면 전부 거부 1건."""
    if seq is None:
        return [], 0
    if not isinstance(seq, list):
        return [], 1
    items = [x for x in seq if isinstance(x, dict)]
    return items, len(seq) - len(items)


def _from_parsed(parsed, key: str) -> tuple[list[dict], int] | None:
    """json.loads 결과에서 항목 목록을 고른다. 모양이 아니면 None."""
    if isinstance(parsed, dict) and key in parsed:
        return _only_dicts(parsed[key])
    if isinstance(parsed, list):
        return _only_dicts(parsed)
    return None


def recover_truncated_items(text: str, key: str = "annotations") -> list[dict] | None:
    """`"<key>": [` 뒤의 객체를 하나씩 읽어 완성된 것만 돌려준다. 배열 시작이 없으면 None.

    입력: 잘렸을 수 있는 응답. 출력: 항목 목록(완성된 dict만) 또는 None.
    잘린 마지막 항목은 버린다(2026-09-12 실측: v2 프롬프트로 답이 길어지자 5,300자에서 잘려 0건).
    """
    i = text.find(f'"{key}"')
    j = text.find("[", i) if i >= 0 else -1
    if j < 0:
        return None
    dec = json.JSONDecoder()
    out: list[dict] = []
    pos = j + 1
    n = len(text)
    while True:
        while pos < n and text[pos] in " ,\t\r\n":
            pos += 1
        if pos >= n or text[pos] != "{":
            break
        try:
            obj, end = dec.raw_decode(text, pos)
        except json.JSONDecodeError:
            break  # 여기서부터 잘렸다
        if isinstance(obj, dict):
            out.append(obj)
        pos = end
    return out


def parse_llm_items(response_text: str, key: str = "annotations") -> ParsedItems:
    """LLM 응답에서 항목 목록을 꺼낸다.

    입력: response_text — 모델 답 전체(설명 문장·울타리가 섞여 있어도 된다). key — 목록 키.
    출력: ParsedItems(items·status·rejected).

    순서: ① 울타리 벗기고 통째로 json.loads → ② `{`부터 마지막 `}`까지 → ③ 잘린 답 복구.
    ①②에서 읽히면 "ok", ③으로 건지면 "recovered", 어느 것도 아니면 "no_json".
    """
    text = _strip_fence((response_text or "").strip())

    try:
        got = _from_parsed(json.loads(text), key)
        if got is not None:
            return ParsedItems(items=got[0], status="ok", rejected=got[1])
    except json.JSONDecodeError:
        pass

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            got = _from_parsed(json.loads(text[first_brace : last_brace + 1]), key)
            if got is not None:
                return ParsedItems(items=got[0], status="ok", rejected=got[1])
        except json.JSONDecodeError:
            pass

    recovered = recover_truncated_items(text, key)
    if recovered is None:
        return ParsedItems(items=[], status="no_json", rejected=0)
    return ParsedItems(items=recovered, status="recovered", rejected=0)
