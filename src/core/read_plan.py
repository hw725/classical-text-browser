"""작업 계획 — 책 한 권을 «어느 쪽을 어떻게 읽을지» 적은 데이터 (D-131).

왜 필요한가:
    세부가 복잡한 스캔본(돌아간 2쪽 펼침·세로쓰기·필사본·한글 번역이 섞인 사진본·표)은
    쪽마다 회전·엔진·쓰기 방향이 다르다. 그것을 화면의 단추로 하나씩 고르게 하는 대신,
    연구자가 **말로** 적게 하고(「5~69쪽은 누운 펼침이고 활자, 133~154쪽은 한글 번역이 붙은
    편지」) 그 말을 이 계획으로 옮긴 뒤 코드가 확인해서 돌린다. 계획은 JSON 파일로 남으므로
    사람이 고치거나, 다른 에이전트(Claude Code 등)가 직접 써도 된다.

무엇을 하지 않는가:
    OCR을 돌리지 않는다(cli/read_book.py가 돈다). 계획을 저장소에 쓰지도 않는다.

가장 중요한 계약 — 옮기지 못한 말은 돌려준다(rule_talk와 같은 규약):
    모델은 정해진 칸만 쓴다. 모르는 엔진·범위를 벗어난 쪽·알 수 없는 회전은 코드가 되돌려
    `unsupported`에 적는다. 비슷한 것으로 바꿔치기하면 사람은 말했다고 여기는데 기계는 다른 일을
    한다.

계획의 모양 (schemas/source_repo/read_plan.schema.json이 못박는다):
    {
      "title": "책 이름",
      "guidance": "LLM 엔진에게 줄 판독 지침(자연어) — manifest.ocr_guidance로 들어간다",
      "ranges": [
        {"pages": "5-69", "rotation": 90, "engine": "ndlocr",
         "writing": "vertical_rtl", "note": "누운 2쪽 펼침"},
        {"pages": "2,4", "skip": true, "note": "백지"}
      ],
      "chapters": [{"page": 5, "title": "壹. 民事慣習回答彙集", "level": 1}]
    }
    쪽 번호는 **PDF 쪽**(1부터)이다. 책에 인쇄된 쪽수와 다르다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

ROTATIONS = (0, 90, 180, 270)
WRITINGS = ("vertical_rtl", "horizontal_ltr")
# 계획에 적을 수 있는 엔진. 설치되지 않은 엔진은 실행 직전에 따로 거른다.
KNOWN_ENGINES = (
    "ndlocr",  # 근대 활자(일본어·한문, 가타카나 문어문). 한글 불가
    "ndlkotenocr",  # 古典籍 Lite — 판본·목활자
    "ndlkotenocr-full",  # 古典籍 Full — 필사·초서
    "honkoku",  # みんなで翻刻 — 훈점
    "paddleocr",  # 가로쓰기 현대 활자(한글 포함)
    "llm_vision",  # LLM 비전 — 한글 세로쓰기·섞인 쪽. 외부 모델을 부른다
)

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "schemas" / "source_repo" / "read_plan.schema.json"
)


_PIECE_RE = re.compile(r"^(\d*)-(\d*)$|^(\d+)$")


def parse_pages(spec: str | int, page_count: Optional[int] = None) -> list[int]:
    """「1-4,7,10-12」 꼴을 쪽 번호 목록으로. 입력: 문자열(또는 정수), 전체 쪽 수(범위 검사용).

    출력: 오름차순·중복 없는 목록. 형식이 틀리거나 범위를 벗어나면 ValueError(한국어 사유).
    열린 범위(「5-」)는 쪽 수가 있어야 닫힌다 — 없으면 ValueError(끝을 0으로 두지 않는다).
    """
    if isinstance(spec, bool) or not isinstance(spec, (str, int)):
        raise ValueError(f"쪽은 «1-4,7» 꼴의 글이어야 합니다: {spec!r}")
    out: set[int] = set()
    for piece in str(spec).replace(" ", "").split(","):
        if not piece:
            continue
        m = _PIECE_RE.match(piece)
        if not m:
            raise ValueError(f"쪽 범위를 읽을 수 없습니다: «{piece}» (예: 5-69, 2,4)")
        if m.group(3):
            a = b = int(m.group(3))
        else:
            a = int(m.group(1)) if m.group(1) else 1
            if m.group(2):
                b = int(m.group(2))
            elif page_count:
                b = page_count
            else:
                raise ValueError(f"끝이 열린 범위는 책의 쪽 수를 알아야 합니다: «{piece}»")
        if a < 1 or b < a:
            raise ValueError(f"쪽 범위가 잘못되었습니다: «{piece}» (1부터, 끝은 시작 이상)")
        if page_count and b > page_count:
            raise ValueError(f"쪽 범위가 책을 벗어납니다: «{piece}» (이 책은 {page_count}쪽)")
        out.update(range(a, b + 1))
    return sorted(out)


def pages_spec(pages: list[int]) -> str:
    """쪽 목록을 닫힌 범위 글로. 예: [1,2,3,7] → «1-3,7».

    「5-」 같은 열린 범위를 저장하지 않으려고 쓴다.
    """
    runs: list[list[int]] = []
    for p in sorted(set(pages)):
        if runs and runs[-1][1] == p - 1:
            runs[-1][1] = p
        else:
            runs.append([p, p])
    return ",".join(f"{a}" if a == b else f"{a}-{b}" for a, b in runs)


def _strict_int(v) -> Optional[int]:
    """정수로 적힌 값만 정수로 — 90.9·"90도"·True는 받지 않는다(비슷한 값으로 바꾸지 않는다)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()):
        return int(v.strip())
    return None


def title_anchor(title: str) -> str:
    """제목에서 번호 머리(「壹.」「1장」)를 떼고 대조에 쓸 앞 6자(공백·구두점 뺌).

    장 경계를 쪽 안에서 찾을 때 원문 내보내기(export/text_export)와
    강독 들이기(core/reading_ingest)가 같은 규칙을 쓴다 — 따로 두면 한쪽만 고쳐진다.
    """
    t = re.sub(
        r"^[\s壹貳參肆伍陸柒捌玖拾一二三四五六七八九十0-9第章編部.、．:：\-]+", "", title or ""
    )
    return re.sub(r"[\s・.·、。,()（）]", "", t)[:6]


def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _list_of_dicts(plan: dict, key: str, problems: list[dict]) -> list:
    v = plan.get(key)
    if v is None:
        return []
    if not isinstance(v, list):
        problems.append({"where": key, "why": "목록([…])이어야 합니다"})
        return []
    return v


def validate_plan(plan: dict, page_count: int) -> tuple[dict, list[dict]]:
    """계획을 확인하고 정리한다. 형식이 맞지 않는 항목은 버리고 이유를 돌려준다.

    입력: 계획 dict(사람·LLM·에이전트가 쓴 것), 책 전체 쪽 수.
    출력: (정리된 계획, problems[{"where", "why"}]).
    왜 예외 대신 목록인가: LLM이 옮긴 계획은 일부만 틀리는 일이 흔하다. 한 칸이 틀렸다고 전부를
    버리면 사람이 말한 나머지가 사라진다. 버린 것은 반드시 보여 준다. 모르는 값을 비슷한 값으로
    바꾸지 않는다(skip "false"를 건너뜀으로, 회전 90.9를 90으로, 층위 0을 1로 — 모두 문제로 알린다).
    쪽 범위는 **닫힌 범위로 정리해** 저장한다 — 열린 범위는 나중에 쪽 수 없이 읽으면 깨진다.
    """
    import jsonschema

    problems: list[dict] = []
    if not isinstance(plan, dict):
        raise ValueError("계획은 {…} 모양이어야 합니다")
    clean: dict = {
        "title": str(plan.get("title") or "").strip(),
        "guidance": str(plan.get("guidance") or "").strip(),
        "ranges": [],
        "chapters": [],
    }
    for i, r in enumerate(_list_of_dicts(plan, "ranges", problems)):
        where = f"ranges[{i}]"
        if not isinstance(r, dict):
            problems.append({"where": where, "why": "구간은 {…} 모양이어야 합니다"})
            continue
        try:
            pages = parse_pages(r.get("pages", ""), page_count)
        except ValueError as e:
            problems.append({"where": where, "why": str(e)})
            continue
        if not pages:
            problems.append({"where": where, "why": "쪽이 비어 있습니다"})
            continue
        item: dict = {"pages": pages_spec(pages)}
        skip = r.get("skip", False)
        if skip not in (True, False):
            problems.append({"where": where, "why": f"skip은 true/false여야 합니다: {skip!r}"})
            continue
        if skip:
            item["skip"] = True
        else:
            rot = _strict_int(r.get("rotation", 0))
            if rot is None or rot % 360 not in ROTATIONS:
                problems.append(
                    {"where": where, "why": f"회전은 0·90·180·270 중 하나: {r.get('rotation')!r}"}
                )
                continue
            engine = str(r.get("engine") or "ndlocr")
            if engine not in KNOWN_ENGINES:
                problems.append(
                    {
                        "where": where,
                        "why": f"모르는 엔진 «{engine}» "
                        f"(쓸 수 있는 것: {', '.join(KNOWN_ENGINES)})",
                    }
                )
                continue
            writing = str(r.get("writing") or "vertical_rtl")
            if writing not in WRITINGS:
                problems.append(
                    {"where": where, "why": f"쓰기 방향은 {' 또는 '.join(WRITINGS)}: {writing}"}
                )
                continue
            item.update({"rotation": rot % 360, "engine": engine, "writing": writing})
        if r.get("note"):
            item["note"] = str(r["note"])[:200]
        clean["ranges"].append(item)
    for i, c in enumerate(_list_of_dicts(plan, "chapters", problems)):
        where = f"chapters[{i}]"
        if not isinstance(c, dict):
            problems.append({"where": where, "why": "장은 {…} 모양이어야 합니다"})
            continue
        page = _strict_int(c.get("page"))
        level = _strict_int(c.get("level", 1))
        title = str(c.get("title") or "").strip()
        if page is None or level is None or not title:
            problems.append(
                {"where": where, "why": "장에는 page·level(정수)과 title이 있어야 합니다"}
            )
            continue
        if not 1 <= page <= page_count or not 1 <= level <= 6:
            problems.append(
                {"where": where, "why": f"쪽({page})·층위({level})가 범위 밖입니다 (층위 1~6)"}
            )
            continue
        clean["chapters"].append({"page": page, "title": title[:200], "level": level})
    clean["chapters"].sort(key=lambda c: (c["page"], c["level"]))
    # 쪽 이름표 — PDF 쪽과 다른 쪽 번호 체계(교재에 손글씨로 적은 면, 인쇄된 쪽수 등).
    # 규칙이 있으면 offset(«교재 면 = PDF 쪽 − 4»), 낱쪽이면 label을 적는다. 뒤의 것이 이긴다.
    labels: list[dict] = []
    for i, lb in enumerate(_list_of_dicts(plan, "page_labels", problems)):
        where = f"page_labels[{i}]"
        if not isinstance(lb, dict) or "pages" not in lb:
            problems.append({"where": where, "why": "이름표에는 pages가 있어야 합니다"})
            continue
        try:
            pages = parse_pages(lb["pages"], page_count)
        except ValueError as e:
            problems.append({"where": where, "why": str(e)})
            continue
        name = str(lb.get("name") or "").strip()
        if not pages or not name or ("offset" in lb) == ("label" in lb):
            problems.append(
                {"where": where, "why": "이름표에는 쪽·name과 offset·label 중 하나가 있어야 합니다"}
            )
            continue
        item = {"pages": pages_spec(pages), "name": name[:20]}
        if "offset" in lb:
            off = _strict_int(lb["offset"])
            if off is None:
                problems.append(
                    {"where": where, "why": f"offset은 정수여야 합니다: {lb['offset']!r}"}
                )
                continue
            item["offset"] = off
        else:
            item["label"] = str(lb["label"])[:20]
        labels.append(item)
    if labels:
        clean["page_labels"] = labels
    # 한 쪽이 두 구간에 들면 뒤의 것이 이긴다 — 조용히 넘어가지 않고 알린다.
    seen: dict[int, int] = {}
    for i, r in enumerate(clean["ranges"]):
        for p in parse_pages(r["pages"], page_count):
            if p in seen:
                problems.append(
                    {
                        "where": f"ranges[{i}]",
                        "why": f"{p}쪽이 ranges[{seen[p]}]와 겹칩니다 — 뒤의 구간을 씁니다",
                    }
                )
            seen[p] = i
    jsonschema.validate(clean, _schema())
    return clean, problems


def page_settings(plan: dict, page_count: int) -> dict[int, dict]:
    """쪽마다 적용할 설정. {쪽: {"rotation", "engine", "writing"} 또는 {"skip": True}}.

    계획에 없는 쪽은 결과에 없다 — 돌리지 않는다(무엇을 할지 모르는 쪽을 추측하지 않는다).
    """
    out: dict[int, dict] = {}
    for r in plan.get("ranges") or []:
        for p in parse_pages(r["pages"], page_count):
            out[p] = (
                {"skip": True}
                if r.get("skip")
                else {
                    "rotation": r["rotation"],
                    "engine": r["engine"],
                    "writing": r["writing"],
                }
            )
    return out


def page_label_map(
    plan: dict, page_count: Optional[int] = None
) -> dict[int, list[tuple[str, str]]]:
    """쪽마다 붙일 이름표. 출력: {PDF 쪽: [(이름, 값), …]} — 예 {46: [("교재", "42")]}.

    뒤의 이름표가 이긴다. offset 규칙이 0 이하로 떨어지는 쪽(표지·목차 등)에서는 그 이름표를
    **지운다** — 앞 이름표의 값이 남으면 뒤 규칙이 «없음»이라고 한 것을 어긴다.
    저장된 계획의 범위는 닫혀 있다(validate_plan) — 쪽 수 없이 읽어도 된다.
    """
    out: dict[int, dict[str, str]] = {}
    for lb in plan.get("page_labels") or []:
        for p in parse_pages(lb["pages"], page_count):
            slot = out.setdefault(p, {})
            if "offset" in lb:
                v = p + int(lb["offset"])
                if v < 1:
                    slot.pop(lb["name"], None)
                    continue
                slot[lb["name"]] = str(v)
            else:
                slot[lb["name"]] = lb["label"]
    return {p: list(d.items()) for p, d in out.items() if d}


def rotation_runs(settings: dict[int, dict]) -> list[tuple[int, int, int]]:
    """쪽별 회전을 이어진 구간 (from, to, rotation)으로 묶는다.

    manifest.rotation_ranges(D-126)에 적으려고 쓴다.
    """
    runs: list[tuple[int, int, int]] = []
    for p in sorted(settings):
        s = settings[p]
        if s.get("skip"):
            continue
        rot = s["rotation"]
        if runs and runs[-1][2] == rot and runs[-1][1] == p - 1:
            runs[-1] = (runs[-1][0], p, rot)
        else:
            runs.append((p, p, rot))
    return runs


SYSTEM_PROMPT = (
    "당신은 스캔본 OCR 도구의 «말 옮김이»입니다. 연구자가 책에 대해 말한 것을 이 프로그램의 "
    "작업 계획 칸으로 옮깁니다. 규칙: (1) 주어진 칸 이름과 값만 씁니다. (2) 어떤 칸으로도 옮길 수 "
    "없는 말은 지어내지 말고 unsupported에 그대로 적습니다 — 비슷한 칸으로 바꿔치기하는 것이 가장 "
    "나쁜 답입니다. (3) 연구자가 말하지 않은 쪽 범위·장 제목을 더하지 않습니다. "
    "(4) JSON만 출력합니다."
)


def _field_guide(page_count: int, available: list[str]) -> str:
    """모델에게 보일 칸 설명. 책에서 나온 값은 예로 들지 않는다(rule_talk와 같은 이유)."""
    return (
        f"이 책은 PDF로 {page_count}쪽입니다. 쪽 번호는 PDF 쪽(1부터)입니다.\n"
        "칸:\n"
        "  title: 책 이름\n"
        "  guidance: LLM 엔진에게 줄 판독 지침(자연어, 연구자의 말을 요약)\n"
        '  ranges: [{"pages": "a-b,c", "rotation": 0|90|180|270, "engine": 엔진, '
        '"writing": "vertical_rtl"|"horizontal_ltr", "skip": true|false, "note": "…"}]\n'
        "    rotation은 «바로 세우려면 시계 방향으로 몇 도». 누운 쪽이 어느 쪽으로 누웠는지 "
        "연구자가 말하지 않았으면 unsupported에 적습니다.\n"
        f"    engine은 다음 중 하나: {', '.join(KNOWN_ENGINES)}\n"
        f"    (지금 설치된 것: {', '.join(available) or '알 수 없음'})\n"
        "    고르는 법: 근대 활자 일본어·한문 → ndlocr, 판본 → ndlkotenocr, 필사·초서 → "
        "ndlkotenocr-full, 훈점 → honkoku, 가로쓰기 한글 → paddleocr, "
        "한글 세로쓰기·섞인 쪽 → llm_vision\n"
        '  chapters: [{"page": PDF 쪽, "title": "…", "level": 1~6}]\n'
    )


async def plan_from_words(
    said: str,
    page_count: int,
    available: list[str],
    router,
    base_plan: Optional[dict] = None,
    force_provider: Optional[str] = None,
    force_model: Optional[str] = None,
) -> tuple[Optional[dict], dict]:
    """연구자가 말한 것을 작업 계획으로 옮긴다. 저장하지 않는다.

    입력: 연구자의 말, 책의 쪽 수, 설치된 엔진 목록, LLM 라우터, 이어서 고칠 기존 계획(선택).
    출력: (정리된 계획 또는 None,
          {"unsupported", "problems", "note", "provider", "model", "error"}).
    목적: 「말 → 계획 → 코드가 확인 → 사람이 보고 실행」. 옮긴 계획은 파일로 남아 고쳐 쓸 수 있다.
    """
    from core.toc import lenient_json

    meta: dict = {
        "unsupported": [],
        "problems": [],
        "note": "",
        "provider": None,
        "model": None,
        "error": None,
    }
    said = (said or "").strip()
    if not said:
        meta["error"] = "책에 대해 아는 것을 한 줄 이상 적어 주세요."
        return None, meta
    prompt = _field_guide(page_count, available)
    if base_plan:
        prompt += "\n지금 계획(이것을 고칩니다 — 말하지 않은 부분은 그대로 둡니다):\n"
        prompt += json.dumps(base_plan, ensure_ascii=False)
    prompt += (
        "\n\n연구자가 한 말:\n"
        + said
        + '\n\n형식: {"plan": {"title": …, "guidance": …, "ranges": […], "chapters": […]}, '
        + '"unsupported": [{"said": "…", "why": "…"}], "note": "…"}'
    )
    kwargs = {
        "system": SYSTEM_PROMPT,
        "response_format": "json",
        "max_tokens": 4096,
        "purpose": "read_plan",
        "think": False,  # 칸으로 옮기는 일이다(D-083)
    }
    if force_provider:
        kwargs["force_provider"] = force_provider
    if force_model:
        kwargs["force_model"] = force_model
    try:
        response = await router.call(prompt, **kwargs)
    except Exception as e:  # noqa: BLE001 — 모델이 없어도 계획 파일을 손으로 쓰는 길은 남는다
        meta["error"] = f"{type(e).__name__}: {e}"
        return None, meta
    meta["provider"] = getattr(response, "provider", None)
    meta["model"] = getattr(response, "model", None)
    data = lenient_json(getattr(response, "text", "") or "")
    if not isinstance(data, dict) or not isinstance(data.get("plan"), dict):
        meta["error"] = "JSON 응답을 해석할 수 없습니다."
        return None, meta
    try:
        plan, problems = validate_plan(data["plan"], page_count)
    except (ValueError, TypeError) as e:  # 모양부터 틀린 답 — 예외로 끝내지 않고 알린다
        meta["error"] = f"모델의 계획을 읽을 수 없습니다: {e}"
        return None, meta
    meta["problems"] = problems
    meta["unsupported"] = [
        {"said": str(u.get("said") or "")[:200], "why": str(u.get("why") or "")[:200]}
        for u in (data.get("unsupported") or [])
        if isinstance(u, dict)
    ] + [{"said": p["where"], "why": p["why"]} for p in problems]
    meta["note"] = str(data.get("note") or "")[:500]
    return plan, meta
