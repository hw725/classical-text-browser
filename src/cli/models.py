"""CLI에서 LLM 모델 고르기 — 이름을 외워 치지 않는다.

왜: `--model openai_oauth:gpt-6-astra`를 매번 정확히 치라는 것은 무리다(2026-09-05 지적).
`ctb models`가 지금 쓸 수 있는 비전 모델을 번호와 함께 보여 주고, `--model`은
**번호·이름 일부·정확한 이름** 어느 것이든 받는다. 하나로 좁혀지지 않으면 후보를 보여 준다.
"""

from __future__ import annotations


def list_vision_models() -> list[dict]:
    """지금 쓸 수 있는 비전 모델. [{provider, model, display, cost}] — 폴백 순서대로."""
    import asyncio

    from llm.router import LlmRouter

    models = asyncio.run(LlmRouter().get_available_models())
    return [
        {
            "provider": m["provider"],
            "model": m["model"],
            "display": m.get("display") or f"{m['provider']} — {m['model']}",
            "cost": m.get("cost", "paid"),
        }
        for m in models
        if m.get("available") and m.get("vision") and "image" not in str(m.get("model", ""))
    ]


def format_list(models: list[dict]) -> str:
    if not models:
        return "쓸 수 있는 비전 모델이 없습니다 — 키·프록시·Ollama를 확인하세요."
    width = len(str(len(models)))
    lines = ["쓸 수 있는 모델 (번호나 이름 일부로 고릅니다):"]
    for i, m in enumerate(models, 1):
        # «free»만 보고 공짜로 오해하면 안 된다(D-056). 구독으로 도는 것은 한도를 소모한다.
        if m["provider"] == "openai_oauth" or (m["provider"] == "ollama" and "cloud" in m["model"]):
            cost = "구독 한도"
        elif m["cost"] == "free":
            cost = "로컬 무료"
        else:
            cost = "종량 과금"
        lines.append(f"  {i:>{width}}. {m['provider']}:{m['model']}    {cost}")
    return "\n".join(lines)


def resolve(spec: str, models: list[dict] | None = None) -> tuple[str, str | None]:
    """«3»·«astra»·«openai_oauth:gpt-6-astra»·«gemini» → (provider, model).

    - 번호: 목록의 그 줄.
    - «프로바이더:모델» 정확히: 그대로(목록에 없어도 허용 — 새 모델일 수 있다).
    - 프로바이더 이름만: 그 프로바이더의 기본 모델 (model=None).
    - 그 밖의 문자열: 목록에서 대소문자 무시 부분 일치. 하나면 그것, 여럿이면 ValueError로
      후보를 알린다.
    """
    spec = spec.strip()
    if not spec:
        raise ValueError("모델을 비워 둘 수 없습니다.")
    if spec.isdigit():
        models = list_vision_models() if models is None else models
        i = int(spec)
        if not 1 <= i <= len(models):
            raise ValueError(f"{i}번은 없습니다.\n" + format_list(models))
        return models[i - 1]["provider"], models[i - 1]["model"]
    if ":" in spec:
        provider, _, model = spec.partition(":")
        return provider.strip(), (model.strip() or None)
    known_providers = ("ollama", "openai_oauth", "gemini", "openai", "anthropic")
    if spec in known_providers:
        return spec, None
    models = list_vision_models() if models is None else models
    hits = [m for m in models if spec.lower() in m["model"].lower()]
    if len(hits) == 1:
        return hits[0]["provider"], hits[0]["model"]
    if not hits:
        raise ValueError(f"'{spec}'에 맞는 모델이 없습니다.\n" + format_list(models))
    cands = "\n".join(f"  {m['provider']}:{m['model']}" for m in hits)
    raise ValueError(f"'{spec}'에 맞는 모델이 여럿입니다 — 더 길게 적으세요:\n{cands}")


def pick_interactive() -> str:
    """목록을 보여 주고 번호를 묻는다. 돌려주는 값은 «프로바이더:모델»."""
    models = list_vision_models()
    print(format_list(models))
    if not models:
        raise ValueError("고를 모델이 없습니다.")
    raw = input("번호: ").strip()
    provider, model = resolve(raw, models)
    return f"{provider}:{model}" if model else provider
