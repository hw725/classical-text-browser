"""사전형 주석 내보내기/가져오기.

해석 저장소의 L7 사전형 주석을 독립적인 사전 파일로 내보내고,
다른 해석에서 참조용으로 가져올 수 있다.

내보내기 형식: 독립 JSON — 표제어 + 사전적 의미 + 출현 위치 + 메타데이터.
가져오기 전략: headword 기반 매칭 → 병합(source_references/related_terms 합집합).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from core.annotation import load_annotations, save_annotations, _gen_annotation_id

# ──────────────────────────────────────
# 내보내기 (Export)
# ──────────────────────────────────────


def export_dictionary(
    interp_path: str | Path,
    doc_id: str,
    doc_title: str,
    interp_id: str,
    part_id: str = "main",
    page_range: tuple[int, int] | None = None,
) -> dict:
    """해석 저장소의 L7 사전형 주석을 독립 사전 JSON으로 내보낸다.

    목적: 사전 데이터를 다른 해석/문헌에서 참조할 수 있도록 추출.
    입력:
        interp_path — 해석 저장소 경로.
        doc_id — 문서 식별자.
        doc_title — 문서 제목 (사람이 읽기 위한 용도).
        interp_id — 해석 식별자.
        part_id — 권 식별자 (기본: "main").
        page_range — 페이지 범위 (start, end). None이면 전체.
    출력: 독립 사전 JSON dict.
    """
    interp_path = Path(interp_path).resolve()

    # 페이지 범위 결정
    # 왜 이렇게 하는가:
    #   L7 annotation 파일은 페이지별로 존재한다.
    #   page_range가 없으면 디렉토리를 스캔하여 모든 페이지를 수집.
    ann_dir = interp_path / "L7_annotation" / "main_text"
    if page_range:
        pages = list(range(page_range[0], page_range[1] + 1))
    elif ann_dir.exists():
        pages = sorted(
            _extract_page_num(f.name)
            for f in ann_dir.glob(f"{part_id}_page_*_annotation.json")
            if _extract_page_num(f.name) is not None
        )
    else:
        pages = []

    # 모든 페이지에서 사전 항목 수집
    entries = []
    by_type: dict[str, int] = {}

    for page_num in pages:
        data = load_annotations(interp_path, part_id, page_num)
        for block in data.get("blocks", []):
            for ann in block.get("annotations", []):
                # dictionary가 있는 주석만 내보내기
                if not ann.get("dictionary"):
                    continue

                dictionary = ann["dictionary"]
                entry = {
                    "headword": dictionary.get("headword", ""),
                    "headword_reading": dictionary.get("headword_reading"),
                    "type": ann.get("type", "note"),
                    "dictionary_meaning": dictionary.get("dictionary_meaning", ""),
                    "contextual_meaning": dictionary.get("contextual_meaning"),
                    "source_references": dictionary.get("source_references", []),
                    "related_terms": dictionary.get("related_terms", []),
                    "notes": dictionary.get("notes"),
                    "occurrences": [
                        {
                            "part_id": part_id,
                            "page_number": page_num,
                            "block_id": block["block_id"],
                            "start": ann["target"]["start"],
                            "end": ann["target"]["end"],
                            "source_text_context": ann.get("source_text_snapshot", ""),
                        }
                    ],
                    "generation_stage": ann.get("current_stage", "none"),
                }
                entries.append(entry)

                # 통계
                t = ann.get("type", "unknown")
                by_type[t] = by_type.get(t, 0) + 1

    # 동일 headword 항목 통합 (같은 표제어가 여러 페이지에 나올 수 있음)
    entries = _deduplicate_entries(entries)

    return {
        "schema_version": "1.0",
        "export_type": "dictionary",
        "export_timestamp": datetime.now(timezone.utc).isoformat(),
        "source": {
            "document_id": doc_id,
            "document_title": doc_title,
            "interpretation_id": interp_id,
        },
        "entries": entries,
        "statistics": {
            "total_entries": len(entries),
            "by_type": by_type,
        },
    }


def save_export(
    interp_path: str | Path,
    dictionary_data: dict,
) -> Path:
    """내보내기 파일을 해석 저장소의 exports/ 디렉토리에 저장한다.

    출력: 저장된 파일 경로.
    """
    interp_path = Path(interp_path).resolve()
    exports_dir = interp_path / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = exports_dir / f"dictionary_{timestamp}.json"

    text = json.dumps(dictionary_data, ensure_ascii=False, indent=2) + "\n"
    file_path.write_text(text, encoding="utf-8")

    return file_path


# ──────────────────────────────────────
# 가져오기 (Import)
# ──────────────────────────────────────


def import_dictionary(
    interp_path: str | Path,
    dictionary_data: dict,
    part_id: str = "main",
    target_page: int = 1,
    merge_strategy: str = "merge",
) -> dict:
    """독립 사전 파일을 해석 저장소에 가져온다.

    목적: 다른 문헌에서 내보낸 사전을 현재 해석에 참조 가능하도록 병합.
    입력:
        interp_path — 대상 해석 저장소 경로.
        dictionary_data — 내보내기된 사전 JSON dict.
        part_id — 대상 권 식별자.
        target_page — 가져오기 대상 페이지 (위치 없는 항목의 기본 페이지).
        merge_strategy — "merge" (기존 항목과 병합) | "skip_existing" | "overwrite".
    출력: { imported: N, merged: N, skipped: N }.

    왜 이렇게 하는가:
        가져온 사전 항목은 target 위치가 없다 (다른 문서의 위치이므로).
        target_page의 별도 블록("_imported")에 위치 없이 저장한다.
        나중에 사용자가 원문에서 해당 어휘를 발견하면 위치를 지정할 수 있다.
    """
    interp_path = Path(interp_path).resolve()

    # 기존 주석 로드
    existing_data = load_annotations(interp_path, part_id, target_page)

    # 기존 headword 인덱스 구축
    existing_headwords: dict[str, dict] = {}
    for block in existing_data.get("blocks", []):
        for ann in block.get("annotations", []):
            if ann.get("dictionary") and ann["dictionary"].get("headword"):
                existing_headwords[ann["dictionary"]["headword"]] = ann

    imported = 0
    merged = 0
    skipped = 0
    source_doc = dictionary_data.get("source", {}).get("document_title", "알 수 없음")

    for entry in dictionary_data.get("entries", []):
        headword = entry.get("headword", "")
        if not headword:
            continue

        if headword in existing_headwords:
            if merge_strategy == "skip_existing":
                skipped += 1
                continue
            elif merge_strategy == "merge":
                # 기존 항목에 source_references, related_terms 합집합 병합
                existing_ann = existing_headwords[headword]
                existing_dict = existing_ann.get("dictionary", {})

                # source_references 합집합
                existing_refs = {
                    r.get("title", ""): r
                    for r in existing_dict.get("source_references", [])
                }
                for ref in entry.get("source_references", []):
                    if ref.get("title") and ref["title"] not in existing_refs:
                        existing_dict.setdefault("source_references", []).append(ref)

                # related_terms 합집합
                existing_terms = set(existing_dict.get("related_terms", []))
                for term in entry.get("related_terms", []):
                    if term not in existing_terms:
                        existing_dict.setdefault("related_terms", []).append(term)
                        existing_terms.add(term)

                # notes에 import 기록
                import_note = f"[{source_doc}에서 가져옴]"
                existing_notes = existing_dict.get("notes") or ""
                if import_note not in existing_notes:
                    existing_dict["notes"] = (
                        f"{existing_notes} {import_note}".strip() if existing_notes
                        else import_note
                    )

                merged += 1
                continue
            # overwrite: 아래에서 새 항목으로 추가 (기존 항목 제거하지 않음)

        # 새 항목 생성 (위치 없음)
        new_ann = {
            "id": _gen_annotation_id(),
            "target": {"start": 0, "end": 0},  # 위치 미지정
            "type": entry.get("type", "note"),
            "content": {
                "label": f"{entry.get('headword_reading', '')}({headword})",
                "description": entry.get("dictionary_meaning", ""),
                "references": [
                    r.get("title", "") for r in entry.get("source_references", [])
                ],
            },
            "dictionary": {
                "headword": headword,
                "headword_reading": entry.get("headword_reading"),
                "dictionary_meaning": entry.get("dictionary_meaning", ""),
                "contextual_meaning": None,  # 문맥적 의미는 문서별 고유
                "source_references": entry.get("source_references", []),
                "related_terms": entry.get("related_terms", []),
                "notes": f"[{source_doc}에서 가져옴]",
            },
            "current_stage": "none",
            "generation_history": [],
            "source_text_snapshot": None,
            "translation_snapshot": None,
            "annotator": {"type": "human", "model": None, "draft_id": None},
            "status": "draft",
            "reviewed_by": None,
            "reviewed_at": None,
        }

        # "_imported" 블록에 추가
        _imported_block = None
        for block in existing_data.get("blocks", []):
            if block["block_id"] == "_imported":
                _imported_block = block
                break
        if _imported_block is None:
            _imported_block = {"block_id": "_imported", "annotations": []}
            existing_data["blocks"].append(_imported_block)

        _imported_block["annotations"].append(new_ann)
        imported += 1

    # 저장
    if imported > 0 or merged > 0:
        save_annotations(interp_path, part_id, target_page, existing_data)

    return {"imported": imported, "merged": merged, "skipped": skipped}


# ──────────────────────────────────────
# 유틸리티
# ──────────────────────────────────────


def _extract_page_num(filename: str) -> int | None:
    """파일명에서 페이지 번호를 추출한다. 예: main_page_001_annotation.json → 1"""
    parts = filename.split("_page_")
    if len(parts) < 2:
        return None
    try:
        return int(parts[1].split("_")[0])
    except (ValueError, IndexError):
        return None


def _deduplicate_entries(entries: list[dict]) -> list[dict]:
    """동일 headword 항목을 통합한다.

    왜 이렇게 하는가:
        같은 표제어가 여러 페이지에 나타날 수 있다.
        내보내기 시 occurrences를 합치고, 나머지 필드는 첫 등장을 기준으로 한다.
    """
    by_headword: dict[str, dict] = {}

    for entry in entries:
        hw = entry.get("headword", "")
        if hw in by_headword:
            # occurrences 합치기
            by_headword[hw]["occurrences"].extend(entry.get("occurrences", []))
            # related_terms 합집합
            existing_terms = set(by_headword[hw].get("related_terms", []))
            for term in entry.get("related_terms", []):
                if term not in existing_terms:
                    by_headword[hw]["related_terms"].append(term)
                    existing_terms.add(term)
        else:
            by_headword[hw] = entry

    return list(by_headword.values())
