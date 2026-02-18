"""JSON 스냅샷 Import 검증 모듈.

Phase 12-3: 스냅샷 데이터의 구조적 무결성을 검증한다.

왜 이렇게 하는가:
    잘못된 스냅샷을 import하면 데이터가 깨질 수 있다.
    검증을 먼저 수행하여 errors(import 차단)와 warnings(경고만)를
    분리하여 사용자에게 알려준다.

검증 항목:
    1. 필수 필드 존재 (schema_version, work.title)
    2. 버전 호환성
    3. original 섹션 구조
    4. block_id 참조 무결성 (L5~L7 → L3 block_id)
    5. annotation_types 참조 무결성
"""


SUPPORTED_VERSIONS = ["1.0"]


def validate_snapshot(data: dict) -> tuple[list[str], list[str]]:
    """스냅샷 데이터를 검증한다.

    입력: JSON 스냅샷 딕셔너리.
    출력: (errors, warnings) 튜플.
        errors — import를 차단하는 심각한 문제 목록.
        warnings — import는 가능하지만 주의가 필요한 사항 목록.
    """
    errors = []
    warnings = []

    # 1. 필수 필드
    if "schema_version" not in data:
        errors.append("schema_version 필드 누락")
        return errors, warnings  # 더 이상 검증 불가

    # 2. 버전 호환성
    version = data["schema_version"]
    if version not in SUPPORTED_VERSIONS:
        errors.append(f"지원하지 않는 스키마 버전: {version}")
        return errors, warnings

    # 3. work 섹션
    work = data.get("work", {})
    if not work.get("title"):
        errors.append("work.title 누락")

    # 4. original 섹션
    if "original" not in data:
        errors.append("original 섹션 누락")
    else:
        _validate_original(data["original"], warnings)

    # 5. interpretation 섹션 (선택적 — 없으면 경고만)
    if "interpretation" not in data:
        warnings.append("interpretation 섹션 없음: 해석 데이터 미포함")
    else:
        _validate_interpretation(data, warnings)

    return errors, warnings


def _validate_original(original: dict, warnings: list) -> None:
    """original 섹션 내부 검증."""
    layers = original.get("layers", {})

    # L1 이미지 참조 확인
    l1 = layers.get("L1_source", {})
    if l1.get("type") == "reference" and l1.get("files"):
        warnings.append(
            f"L1 이미지 {len(l1['files'])}개는 경로 참조만 포함 — "
            "실제 파일은 별도 복사 필요"
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
                    warnings.append(
                        f"L7 주석 type '{ann_type}'이 annotation_types에 미정의"
                    )


def _extract_l3_block_ids(data: dict) -> set[str]:
    """L3 레이아웃에서 모든 block_id를 추출한다."""
    ids = set()
    l3_pages = (
        data.get("original", {})
        .get("layers", {})
        .get("L3_layout", {})
        .get("pages", [])
    )
    for page in l3_pages:
        for block in page.get("blocks", []):
            bid = block.get("block_id")
            if bid:
                ids.add(bid)
    return ids
