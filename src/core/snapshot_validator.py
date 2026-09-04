"""JSON 스냅샷 Import 검증 모듈.

Phase 12-3: 스냅샷 데이터의 구조적 무결성을 검증한다.

왜 이렇게 하는가:
    잘못된 스냅샷을 import하면 데이터가 깨질 수 있다.
    검증을 먼저 수행하여 errors(import 차단)와 warnings(경고만)를
    분리하여 사용자에게 알려준다.

검증 항목:
    1. 구조 — `schemas/exchange.schema.json`(교환 형식의 **정본**)으로 검증한다 (B-005)
    2. 버전 호환성
    3. block_id 참조 무결성 (L5~L7 → L3 block_id) — 스키마로 적을 수 없는 것
    4. annotation_types 참조 무결성 — 같은 이유

왜 스키마와 손 규칙을 나누는가: 「어떤 칸이 있어야 하는가」는 스키마 하나가 정하고
(구현·문서·검증이 갈라지지 않게), 「이 id가 저기 있는가」처럼 스키마가 말할 수 없는 것만
여기서 본다.
"""

SUPPORTED_VERSIONS = ["1.0"]

# 스키마의 기계 문구를 사람 말로. 없으면 원문을 그대로 보여 준다.
_MESSAGE_HINTS = {
    "source_info": "이 스냅샷이 어느 문헌·해석의 것인지(source_info)가 없거나 모양이 다릅니다",
    "original": "원본 층(original) 절이 없거나 모양이 다릅니다",
}


def validate_snapshot(data: dict) -> tuple[list[str], list[str]]:
    """스냅샷 데이터를 검증한다.

    입력: JSON 스냅샷 딕셔너리(옛 이름으로 적힌 것도 받는다).
    출력: (errors, warnings) 튜플.
        errors — import를 차단하는 심각한 문제 목록.
        warnings — import는 가능하지만 주의가 필요한 사항 목록.
    """
    from core.snapshot import exchange_validator, normalize_snapshot

    errors: list[str] = []
    warnings: list[str] = []

    if "schema_version" not in data:
        errors.append("schema_version 필드 누락")
        return errors, warnings  # 더 이상 검증 불가

    version = data["schema_version"]
    if version not in SUPPORTED_VERSIONS:
        errors.append(f"지원하지 않는 스키마 버전: {version}")
        return errors, warnings

    # 옛 이름을 먼저 지금 이름으로 옮긴다 — 스키마에 옛 이름을 넣으면 정본이 둘이 된다
    data = normalize_snapshot(data)

    for err in sorted(exchange_validator().iter_errors(data), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(최상위)"
        hint = _MESSAGE_HINTS.get(where)  # 절 자체가 통째로 어긋난 때만 사람 말로 바꾼다
        errors.append(f"{where}: {hint or err.message}")

    if "interpretation" not in data:
        warnings.append("interpretation 섹션 없음: 해석 데이터 미포함")
    else:
        _validate_interpretation(data, warnings)

    if "original" in data:
        _validate_original(data["original"], warnings)

    return errors, warnings


def _validate_original(original: dict, warnings: list) -> None:
    """original 섹션 내부 검증."""
    layers = original.get("layers", {})

    # L1 이미지 참조 확인
    l1 = layers.get("L1_source", {})
    if l1.get("type") == "reference" and l1.get("files"):
        warnings.append(
            f"L1 이미지 {len(l1['files'])}개는 경로 참조만 포함 — 실제 파일은 별도 복사 필요"
        )

    # L4 텍스트 존재 확인
    l4 = layers.get("L4_text", {})
    if not l4.get("pages"):
        warnings.append("L4 텍스트 페이지가 없음")


def _validate_interpretation(data: dict, warnings: list) -> None:
    """interpretation 섹션 + 참조 무결성 검증."""
    interp = data.get("interpretation", {})
    layers = interp.get("layers", {})

    # block_id 수집: L3 레이아웃에서 추출
    l3_block_ids = _extract_l3_block_ids(data)

    # L5 표점의 block_id 참조 확인
    for item in layers.get("L5_punctuation", []):
        bid = item.get("block_id")
        if bid and l3_block_ids and bid not in l3_block_ids:
            warnings.append(f"L5 표점의 block_id '{bid}'가 L3에 없음")

    # L5 현토의 block_id 참조 확인
    for item in layers.get("L5_hyeonto", []):
        bid = item.get("block_id")
        if bid and l3_block_ids and bid not in l3_block_ids:
            warnings.append(f"L5 현토의 block_id '{bid}'가 L3에 없음")

    # L6 번역의 block_id 참조 확인
    for item in layers.get("L6_translation", []):
        translations = item.get("translations", [])
        for tr in translations:
            bid = tr.get("source", {}).get("block_id")
            if bid and l3_block_ids and bid not in l3_block_ids:
                warnings.append(f"L6 번역의 block_id '{bid}'가 L3에 없음")

    # L7 주석의 block_id + type 참조 확인
    defined_types = {t.get("id") for t in data.get("annotation_types", []) if t.get("id")}
    for item in layers.get("L7_annotation", []):
        for block in item.get("blocks", []):
            bid = block.get("block_id")
            if bid and l3_block_ids and bid not in l3_block_ids:
                warnings.append(f"L7 주석의 block_id '{bid}'가 L3에 없음")
            for ann in block.get("annotations", []):
                ann_type = ann.get("type")
                if ann_type and defined_types and ann_type not in defined_types:
                    warnings.append(f"L7 주석 type '{ann_type}'이 annotation_types에 미정의")


def _extract_l3_block_ids(data: dict) -> set[str]:
    """L3 레이아웃에서 모든 block_id를 추출한다."""
    ids = set()
    l3_pages = data.get("original", {}).get("layers", {}).get("L3_layout", {}).get("pages", [])
    for page in l3_pages:
        for block in page.get("blocks", []):
            bid = block.get("block_id")
            if bid:
                ids.add(bid)
    return ids
