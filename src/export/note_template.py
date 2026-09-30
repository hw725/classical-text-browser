"""강독 노트의 «틀» — 사용자가 준 모양대로 층의 원문·번역·주석을 다시 짠다 (D-131 보완).

왜 틀인가: 노트 모양은 수업·스터디마다 달라진다(사용자 지시 2026-09-30). 모양을 코드에 박으면
바뀔 때마다 코드를 고쳐야 하고, 모양별 저장 형식을 두면 데이터를 옮겨야 한다. 그래서 저장은
기존 층(L4·경계·L6·L7) 그대로 두고, **모양은 내보낼 때 주는 틀**로만 정한다.

틀은 Jinja2 문법이다. 연구자가 직접 쓰지 않아도 된다 — 원하는 노트의 예시 한 편을 붙여 넣으면
`template_from_example`이 LLM에게 «이 예시를 틀로 바꿔라»라고 묻는다. 모델은 **글을 만들지 않고
자리만 표시한다**: 예시의 원문·번역·풀이 자리를 변수로 바꾸고, 제목 줄 같은 고정 글만 남긴다.
그 틀을 코드가 채우므로, 노트에 들어가는 원문·번역·주석은 언제나 층에 있는 것뿐이다.

틀은 저장하지 않는다. 화면에서 파일로 받아 두었다가 다시 올려 쓴다.
"""

from __future__ import annotations

import re
from typing import Optional

# 틀에서 쓸 수 있는 이름 — LLM 프롬프트와 화면 도움말이 같은 표를 쓴다.
# assemble_notes(export/reading_note.py)가 만드는 보기와 같아야 한다(시험이 지킨다).
FIELDS = """\
note — 장 하나(파일 하나)
  note.title         노트 제목(예: 「壹. 民事慣習回答彙集 강독 노트」)
  note.chapter       장 제목
  note.bibliography  서지 줄 목록
  note.intro         해제 문단 목록
  note.notes         해제 덧붙임 줄 목록
  note.points        독해 요점 목록
  note.sections      문서 항목 목록 — 각 항목 s:
    s.heading        항목 제목(원제 (국역 제목))
    s.level          층위 수(3이면 === 제목 ===)
    s.page           시작 PDF 쪽
    s.meta           문서 정보 줄 목록(발신·수신·날짜·교재 면, 강의 메모 등)
    s.segments       구획 목록 — 각 구획 g:
      g.label        구획 표지(○① 등)
      g.text         원문(지금 확정본)
      g.ko           국역
      g.terms        어휘·문법 목록 — 각 t: t.term, t.reading(읽기), t.gloss(풀이)
      g.check        검토 메모(없으면 빈 글)
      g.changed      번역 뒤 원문이 고쳐졌으면 참
loop.index — 반복 안에서 1부터 세는 번호
"""

SYSTEM_PROMPT = (
    "너는 문서 틀 변환기다. 연구자가 붙여 넣은 «노트 예시»를 Jinja2 틀로 바꾼다. "
    "예시에 든 원문·번역·풀이·제목 같은 **내용**은 틀에 남기지 말고 아래 변수로 바꾼다. "
    "고정된 글(절 제목 「== 해제 ==」, 「국역 (펼치기)」, 표 문법, 구분 기호)만 그대로 남긴다. "
    "예시가 되풀이하는 단위(항목·구획·어휘)는 {% for %}로 돌린다. "
    "예시에 없는 칸은 넣지 않는다. 틀만 답하고 설명·코드 울타리(```)는 쓰지 않는다."
)

# 시험 채우기용 보기 — 틀이 실제로 돌아가는지(오류 없이 글이 나오는지) 확인한다
SAMPLE_NOTE = {
    "title": "貳. 臨時財産整理局事務要綱 강독 노트",
    "chapter": "貳. 臨時財産整理局事務要綱",
    "bibliography": ["교재 PDF 34~52쪽"],
    "intro": ["해제 문단."],
    "notes": [],
    "points": ["候 뒤 한 글자를 본다."],
    "sections": [
        {
            "heading": "一、證明方ノ件 (증명 방식의 건)",
            "level": 3,
            "page": 46,
            "meta": [
                "각 관찰사 앞 탁지부 차관 통첩 · 隆熙 2년(1908) 7월 9일",
                "교재 42면 · PDF p.46",
            ],
            "segments": [
                {
                    "label": "○①",
                    "text": "本年六月勅令第三十九號ヲ以テ",
                    "ko": "올해 6월 칙령 제39호로써",
                    "terms": [{"term": "以テ", "reading": "もって", "gloss": "~로써"}],
                    "check": "",
                    "changed": False,
                }
            ],
        }
    ],
}


def _env():
    """사용자가 준 틀을 돌리는 환경 — 샌드박스(파일·속성 접근 막힘), 자동 이스케이프 없음.

    자동 이스케이프를 끄는 이유: 결과는 위키·마크다운 글이지 HTML이 아니다. 원문의 「<」 같은 글자가
    &lt;로 바뀌면 노트가 망가진다. 틀은 화면에 그려지지 않고 파일로만 나간다.
    """
    from jinja2.sandbox import SandboxedEnvironment

    return SandboxedEnvironment(
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def render_with_template(note: dict, template: str) -> str:
    """노트 보기 하나를 틀로 그린다.

    입력: note — assemble_notes의 원소, template — Jinja2 틀 글.
    출력: 완성된 글. 틀이 문법상 틀렸거나 돌다가 막히면 ValueError(한국어, 해결책 포함).
    """
    from jinja2 import TemplateError

    try:
        return _env().from_string(template).render(note=note)
    except TemplateError as e:
        raise ValueError(
            f"틀을 채우지 못했습니다: {e}\n→ 해결: 예시로 틀을 다시 만들거나, 틀 파일의 "
            "{% for %}·{% endfor %} 짝과 변수 이름을 확인하세요."
        ) from e


def check_template(template: str) -> list[str]:
    """틀이 쓸 만한지 본보기 노트로 돌려 본다. 출력: 문제 목록(비었으면 통과)."""
    problems: list[str] = []
    if not (template or "").strip():
        return ["틀이 비었습니다."]
    try:
        out = render_with_template(SAMPLE_NOTE, template)
    except ValueError as e:
        return [str(e)]
    # 층의 내용이 하나도 안 들어가는 틀은 노트가 아니다(예시 글을 그대로 베낀 경우)
    seg = SAMPLE_NOTE["sections"][0]["segments"][0]
    if seg["text"] not in out and seg["ko"] not in out:
        problems.append("틀이 원문·국역 자리를 쓰지 않습니다 — 예시 글을 그대로 베낀 것 같습니다.")
    return problems


def _strip_fence(text: str) -> str:
    """모델이 지시를 어기고 ``` 울타리를 쳤으면 벗긴다."""
    m = re.search(r"```[a-zA-Z0-9]*\n(.*?)```", text or "", re.S)
    return (m.group(1) if m else (text or "")).strip("\n") + "\n"


async def template_from_example(
    example: str,
    router,
    force_provider: Optional[str] = None,
    force_model: Optional[str] = None,
) -> dict:
    """노트 예시 → 틀. **저장하지 않는다.**

    출력: {"template", "problems", "preview", "provider", "model"} 또는 {"error"}.
    preview는 본보기 노트를 그 틀로 채운 글 — 연구자는 틀 문법 대신 이것을 보고 판단한다.
    """
    example = (example or "").strip()
    if not example:
        return {
            "error": "노트 예시가 비었습니다. 원하는 노트 한 편(한 항목이면 충분)을 붙여 넣으세요."
        }
    if len(example) > 20000:
        # 틀에 필요한 것은 되풀이 모양이다 — 앞부분이면 충분하고, 길면 비용만 는다
        example = example[:20000]
    prompt = (
        "쓸 수 있는 변수(이것 말고는 쓰지 않는다):\n"
        + FIELDS
        + "\n노트 예시:\n"
        + example
        + "\n\n위 예시와 같은 모양을 만드는 Jinja2 틀만 답하라."
    )
    kwargs = {
        "system": SYSTEM_PROMPT,
        "max_tokens": 4096,
        "purpose": "note_template",
        "think": False,  # 모양을 옮기는 일이다(D-083)
    }
    if force_provider:
        kwargs["force_provider"] = force_provider
    if force_model:
        kwargs["force_model"] = force_model
    try:
        response = await router.call(prompt, **kwargs)
    except Exception as e:  # noqa: BLE001 — 모델이 없으면 틀 파일을 직접 올리는 길이 남는다
        return {"error": f"{type(e).__name__}: {e}"}
    template = _strip_fence(getattr(response, "text", "") or "")
    problems = check_template(template)
    preview = ""
    if not any(p.startswith("틀을 채우지") for p in problems):
        preview = render_with_template(SAMPLE_NOTE, template)
    return {
        "template": template,
        "problems": problems,
        "preview": preview,
        "provider": getattr(response, "provider", None),
        "model": getattr(response, "model", None),
    }
