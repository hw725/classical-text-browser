"""이체자 사전 원자료 파서 (D-080).

외부 자료를 이 저장소의 사전 형식(`{"variants": {A: [B, ...]}}`)으로 옮기는 순수
함수들이다. 네트워크·파일 입출력은 `scripts/build_variant_dicts.py`가 맡고, 여기는
문자열을 받아 쌍 목록을 돌려주기만 한다 — 그래야 서버 없이 시험할 수 있다.

어디서 무엇을 가져오는가 (라이선스는 D-080 표 참조):

| 파서 | 원자료 | 층 |
|---|---|---|
| parse_opencc | BYVoid/OpenCC data/dictionary/*.txt (Apache-2.0) | script |
| parse_unihan_variants | Unicode Unihan_Variants.txt (Unicode License) | 필드별 |
| parse_cjkvi_csv | cjkvi-variants twedu·hydzd·cjkvi·ucs-scs (라이선스 미확인) | loose/script |
| parse_jp_old_style | cjkvi-variants jp-old-style.txt (라이선스 미확인) | script |

층(tier)의 뜻 — D-080 결정 2:
  strict  확정 동자. 정렬 엔진이 «이체자»로 분류한다.
  loose   넓은 이체 관계(통가·차자 포함). 힌트만 — 동치로 쓰면 오독이 숨는다.
  script  문자 체계 차이(간체·신자체·지역 변형). 힌트만. 본문은 절대 고치지 않는다.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Iterable

TIERS = ("strict", "loose", "script")

# Unihan 변형 필드 → 층. kSpoofingVariant는 «닮아 보이는 글자»라 이체자가 아니다 — 제외.
UNIHAN_FIELD_TIERS = {
    "kZVariant": "strict",
    "kSemanticVariant": "loose",
    "kSpecializedSemanticVariant": "loose",
    "kSimplifiedVariant": "script",
    "kTraditionalVariant": "script",
}

# 변체 선택자(IVS) U+E0100–U+E01EF. jp-old-style.txt가 글자마다 붙여 둔다.
# 사전 키는 기본 글자여야 하므로 벗겨 낸다.
_IVS_RE = re.compile("[\U000e0100-\U000e01ef︀-️]")

Pair = tuple[str, str]


def _is_single_cjk(s: str) -> bool:
    """한 글자(코드포인트 하나)인가. 결합 문자·IVS가 남은 것은 거른다."""
    return len(s) == 1 and not s.isspace()


def _clean(s: str) -> str:
    return _IVS_RE.sub("", s.strip())


def parse_opencc(text: str) -> list[Pair]:
    """OpenCC 사전 텍스트를 (원자, 대상자) 쌍으로.

    입력: `key<TAB>value [value ...]` 줄들. `#` 주석 허용.
    출력: 한 글자 ↔ 한 글자 쌍만. 여러 글자 항목(어구 사전)은 건너뛴다.
    """
    pairs: list[Pair] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" not in line:
            continue
        key, values = line.split("\t", 1)
        key = _clean(key)
        if not _is_single_cjk(key):
            continue
        for v in values.split():
            v = _clean(v)
            if _is_single_cjk(v) and v != key:
                pairs.append((key, v))
    return pairs


def parse_unihan_variants(text: str, fields: Iterable[str]) -> list[Pair]:
    """Unihan_Variants.txt에서 지정 필드의 쌍을 뽑는다.

    입력: 파일 본문. 줄 형식 `U+4E00<TAB>kSemanticVariant<TAB>U+58F9<kFenn U+5F0C`.
          값에는 `<출처>` 꼬리가 붙을 수 있다 — `<` 앞까지가 코드포인트다.
          fields — 뽑을 필드 이름들 (UNIHAN_FIELD_TIERS의 키).
    출력: (글자, 글자) 쌍.
    """
    wanted = set(fields)
    pairs: list[Pair] = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) < 3 or cols[1] not in wanted:
            continue
        src = _cp_to_char(cols[0])
        if src is None:
            continue
        for token in cols[2].split():
            token = token.split("<", 1)[0]
            dst = _cp_to_char(token)
            if dst is not None and dst != src:
                pairs.append((src, dst))
    return pairs


def _cp_to_char(token: str):
    token = token.strip()
    if not token.startswith("U+"):
        return None
    try:
        return chr(int(token[2:], 16))
    except ValueError:
        return None


def parse_cjkvi_csv(text: str) -> list[Pair]:
    """cjkvi-variants의 3열 CSV(`글자,관계,글자`)를 쌍으로.

    머리의 관계 선언 줄(`twedu/variant,<rev>,twedu/regular` 등)과 주석은 건너뛴다.
    구성 정보(`[⿱亠厶]`)가 붙은 줄은 기본 글자 부분만 취한다.
    """
    pairs: list[Pair] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cols = line.split(",")
        if len(cols) < 3:
            continue
        a, rel, b = cols[0], cols[1], cols[2]
        if rel.startswith("<") or "/" in a or "/" in b:
            continue  # 관계 선언 줄
        a = _clean(a.split("[", 1)[0])
        b = _clean(b.split("[", 1)[0])
        if _is_single_cjk(a) and _is_single_cjk(b) and a != b:
            pairs.append((a, b))
    return pairs


def parse_jp_old_style(text: str) -> list[Pair]:
    """jp-old-style.txt(신자체<TAB>구자체[<TAB>호환자][<TAB>주석])를 쌍으로. IVS를 벗긴다."""
    pairs: list[Pair] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) < 2:
            continue
        new, old = _clean(cols[0]), _clean(cols[1])
        if _is_single_cjk(new) and _is_single_cjk(old) and new != old:
            pairs.append((new, old))
    return pairs


def pairs_to_variants(pairs: Iterable[Pair]) -> dict[str, list[str]]:
    """쌍 목록을 양방향 `{A: [B, ...]}`로. 이 저장소 사전 형식의 `variants` 값."""
    table: dict[str, set[str]] = {}
    for a, b in pairs:
        if a == b:
            continue
        table.setdefault(a, set()).add(b)
        table.setdefault(b, set()).add(a)
    return {k: sorted(v) for k, v in sorted(table.items())}


def build_dict_payload(
    pairs: Iterable[Pair],
    *,
    tier: str,
    source_name: str,
    source_url: str,
    source_files: list[str],
    license_note: str,
    retrieved: str | None = None,
) -> dict:
    """사전 파일 한 벌을 만든다. `_tier`·`_source`가 D-080 결정 4의 출처 기록이다.

    입력: pairs — 쌍 목록. tier — strict|loose|script. 나머지는 출처 메타.
    출력: JSON으로 그대로 저장할 dict.
    """
    if tier not in TIERS:
        raise ValueError(f"알 수 없는 층: {tier} (strict|loose|script)")
    variants = pairs_to_variants(pairs)
    pair_count = sum(len(v) for v in variants.values()) // 2
    return {
        "_format_guide": {
            "설명": "이체자(異體字) 사전. 같은 글자의 다른 형태를 등록한다.",
            "양방향 규칙": "A→B를 등록하면 B→A도 자동 등록된다.",
            "용도": "정렬 엔진이 OCR↔참조 텍스트 대조 시 이체자를 분류한다. "
            "본문은 고치지 않는다(D-080).",
            "층": {
                "strict": "확정 동자 — 정렬에서 «이체자»로 분류",
                "loose": "넓은 이체 관계 — 힌트만, 동치 아님",
                "script": "문자 체계 차이(간체·신자체) — 힌트만, 동치 아님",
            },
        },
        "_version": "0.2.0",
        "_tier": tier,
        "_source": {
            "name": source_name,
            "url": source_url,
            "files": list(source_files),
            "license": license_note,
            "retrieved": retrieved or date.today().isoformat(),
            "pair_count": pair_count,
        },
        "variants": variants,
    }
