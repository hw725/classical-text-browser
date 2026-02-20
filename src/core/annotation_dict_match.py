"""참조 사전 매칭 엔진.

다른 문헌에서 내보낸 사전(reference dictionary)을 현재 문헌의 원문에
자동 매칭하여 번역 시 참고 정보로 제공한다.

핵심 워크플로우:
  문헌A (완성) → 사전 내보내기 → 문헌B에 참조 사전으로 등록
  → 문헌B 번역 시 자동 매칭 → 사용자 확인 → 번역 컨텍스트에 포함

매칭 알고리즘:
  한자 표제어(headword)의 단순 부분 문자열 검색.
  한자는 형태소 변화가 없어 정규식 불필요. 표제어가 원문에 나타나면 매칭.
"""

import json
from pathlib import Path


# ──────────────────────────────────────
# 참조 사전 저장소 관리
# ──────────────────────────────────────


def _ref_dict_dir(interp_path: Path) -> Path:
    """참조 사전 저장 디렉토리 경로.

    위치: {interp_path}/L7_annotation/reference_dicts/
    왜 이렇게 하는가:
      L7_annotation 아래에 두어 주석 시스템의 일부임을 명확히 한다.
      main_text/와 나란히 놓여 기존 annotation 파일과 구분된다.
    """
    return interp_path / "L7_annotation" / "reference_dicts"


def list_reference_dicts(interp_path: str | Path) -> list[dict]:
    """등록된 참조 사전 목록을 반환한다.

    목적: 프론트엔드에서 어떤 참조 사전이 로드되어 있는지 표시.
    출력: [{"filename": ..., "source_document": ..., "total_entries": N, ...}, ...]
    """
    interp_path = Path(interp_path).resolve()
    ref_dir = _ref_dict_dir(interp_path)
    if not ref_dir.exists():
        return []

    results = []
    for f in sorted(ref_dir.glob("*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            results.append({
                "filename": f.name,
                "source_document_id": data.get("source", {}).get("document_id", ""),
                "source_document_title": data.get("source", {}).get("document_title", ""),
                "source_interpretation_id": data.get("source", {}).get("interpretation_id", ""),
                "total_entries": data.get("statistics", {}).get("total_entries", len(data.get("entries", []))),
                "export_timestamp": data.get("export_timestamp"),
            })
        except (json.JSONDecodeError, OSError):
            # 손상된 파일은 건너뜀
            continue

    return results


def register_reference_dict(
    interp_path: str | Path,
    dictionary_data: dict,
    filename: str | None = None,
) -> Path:
    """참조 사전을 해석 저장소에 등록한다.

    목적: 내보내기된 사전 파일을 참조 사전 디렉토리에 저장.
    입력:
        interp_path — 대상 해석 저장소 경로.
        dictionary_data — 내보내기된 사전 JSON dict.
        filename — 저장할 파일명. None이면 자동 생성.
    출력: 저장된 파일 경로.
    """
    interp_path = Path(interp_path).resolve()
    ref_dir = _ref_dict_dir(interp_path)
    ref_dir.mkdir(parents=True, exist_ok=True)

    if filename is None:
        # source 정보에서 파일명 자동 생성
        source = dictionary_data.get("source", {})
        doc_id = source.get("document_id", "unknown")
        timestamp = dictionary_data.get("export_timestamp", "")[:10].replace("-", "")
        filename = f"{doc_id}_dict_{timestamp}.json"

    file_path = ref_dir / filename

    text = json.dumps(dictionary_data, ensure_ascii=False, indent=2) + "\n"
    file_path.write_text(text, encoding="utf-8")

    return file_path


def load_reference_dict(interp_path: str | Path, filename: str) -> dict:
    """참조 사전 파일을 읽어 반환한다.

    출력: 사전 JSON dict.
    Raises: FileNotFoundError — 파일이 없을 때.
    """
    interp_path = Path(interp_path).resolve()
    file_path = _ref_dict_dir(interp_path) / filename

    if not file_path.exists():
        raise FileNotFoundError(f"참조 사전 파일을 찾을 수 없습니다: {file_path}")

    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


def remove_reference_dict(interp_path: str | Path, filename: str) -> bool:
    """참조 사전을 등록 해제(삭제)한다.

    출력: 삭제 성공 여부.

    왜 이렇게 하는가:
      참조 사전은 다른 문헌의 복사본이므로, 삭제해도 원본은 보존된다.
      실제 파일 삭제가 아닌 경우 별도 _removed 마킹도 가능하나,
      참조 사전은 원본 문헌에 항상 있으므로 직접 삭제해도 안전하다.
    """
    interp_path = Path(interp_path).resolve()
    file_path = _ref_dict_dir(interp_path) / filename

    if not file_path.exists():
        return False

    file_path.unlink()
    return True


# ──────────────────────────────────────
# 매칭 엔진
# ──────────────────────────────────────


def _build_headword_index(ref_dicts: list[dict]) -> list[dict]:
    """참조 사전 목록에서 headword 인덱스를 구축한다.

    목적: 매칭 시 반복 순회를 피하기 위해 미리 표제어를 정리.
    입력: 참조 사전 dict 리스트.
    출력: [{headword, headword_reading, type, dictionary_meaning,
            contextual_meaning, source_dict_filename, source_document_title,
            source_references, related_terms}, ...]

    왜 이렇게 하는가:
        여러 참조 사전에서 같은 headword가 존재할 수 있다.
        모두 수집하여 사용자에게 출처별로 보여준다.
    """
    index = []
    for ref_dict in ref_dicts:
        source = ref_dict.get("source", {})
        source_title = source.get("document_title", "")
        source_filename = ref_dict.get("_filename", "")  # 호출 시 주입

        for entry in ref_dict.get("entries", []):
            hw = entry.get("headword", "")
            if not hw:
                continue
            index.append({
                "headword": hw,
                "headword_reading": entry.get("headword_reading"),
                "type": entry.get("type", "term"),
                "dictionary_meaning": entry.get("dictionary_meaning", ""),
                "contextual_meaning": entry.get("contextual_meaning"),
                "source_references": entry.get("source_references", []),
                "related_terms": entry.get("related_terms", []),
                "source_dict_filename": source_filename,
                "source_document_title": source_title,
            })

    # 표제어 길이 내림차순 정렬 (긴 표제어 우선 매칭 — 부분 겹침 방지)
    index.sort(key=lambda x: len(x["headword"]), reverse=True)

    return index


def match_text(
    original_text: str,
    ref_dicts: list[dict],
    block_id: str | None = None,
) -> list[dict]:
    """원문 텍스트에서 참조 사전의 headword를 매칭한다.

    목적: 번역 시 참고할 수 있는 사전 항목을 자동으로 찾아낸다.
    입력:
        original_text — 매칭 대상 원문 (블록 단위 또는 페이지 전체).
        ref_dicts — 참조 사전 dict 리스트 (각각 _filename 필드 주입 필요).
        block_id — 매칭 결과에 표시할 블록 ID (선택).
    출력: [{headword, headword_reading, type, dictionary_meaning,
            contextual_meaning, source_dict, source_document,
            match_positions: [{start, end, block_id}]}, ...]

    왜 이렇게 하는가:
        한자 표제어는 형태소 변화가 없으므로 단순 부분 문자열 검색으로 충분하다.
        정규식이나 형태소 분석기가 필요 없다.
        긴 표제어부터 매칭하여 부분 겹침을 최소화한다.
    """
    if not original_text or not ref_dicts:
        return []

    index = _build_headword_index(ref_dicts)
    matches = []
    # (headword, source_dict_filename, start) 중복 방지
    # 같은 headword라도 다른 사전에서 오면 별개의 매칭으로 취급
    seen_positions: set[tuple[str, str, int]] = set()

    for item in index:
        hw = item["headword"]
        src_file = item["source_dict_filename"]
        positions = []

        # 원문에서 표제어의 모든 출현 위치 검색
        start_idx = 0
        while True:
            pos = original_text.find(hw, start_idx)
            if pos == -1:
                break

            # end는 inclusive이므로 pos + len(hw) - 1
            end_pos = pos + len(hw) - 1

            # 중복 방지: 같은 headword + 같은 사전 + 같은 위치면 건너뜀
            dedup_key = (hw, src_file, pos)
            if dedup_key not in seen_positions:
                seen_positions.add(dedup_key)
                match_pos = {"start": pos, "end": end_pos}
                if block_id:
                    match_pos["block_id"] = block_id
                positions.append(match_pos)

            start_idx = pos + 1  # 겹치는 매칭도 허용

        if positions:
            matches.append({
                "headword": hw,
                "headword_reading": item["headword_reading"],
                "type": item["type"],
                "dictionary_meaning": item["dictionary_meaning"],
                "contextual_meaning": item["contextual_meaning"],
                "source_references": item["source_references"],
                "related_terms": item["related_terms"],
                "source_dict": item["source_dict_filename"],
                "source_document": item["source_document_title"],
                "match_positions": positions,
            })

    return matches


def match_page_blocks(
    interp_path: str | Path,
    blocks_text: list[dict],
    ref_filenames: list[str] | None = None,
) -> list[dict]:
    """페이지의 블록들에 대해 참조 사전 매칭을 수행한다.

    목적: 블록별로 원문을 매칭하여 블록 ID 정보를 포함한 결과 반환.
    입력:
        interp_path — 해석 저장소 경로.
        blocks_text — [{"block_id": "p01_b01", "text": "王戎簡要..."}, ...]
        ref_filenames — 사용할 참조 사전 파일명 리스트. None이면 전체.
    출력: match_text()와 동일한 형식. match_positions에 block_id 포함.

    왜 이렇게 하는가:
        프론트엔드에서 블록별로 매칭 결과를 표시해야 한다.
        모든 블록에 대해 한번에 매칭하되, 블록 ID를 추적한다.
    """
    interp_path = Path(interp_path).resolve()

    # 참조 사전 로드
    ref_dir = _ref_dict_dir(interp_path)
    if not ref_dir.exists():
        return []

    ref_dicts = []
    if ref_filenames:
        filenames = ref_filenames
    else:
        filenames = [f.name for f in sorted(ref_dir.glob("*.json"))]

    for fname in filenames:
        try:
            data = load_reference_dict(interp_path, fname)
            data["_filename"] = fname  # 매칭 결과에 출처 추적용
            ref_dicts.append(data)
        except (FileNotFoundError, json.JSONDecodeError):
            continue

    if not ref_dicts:
        return []

    # 블록별 매칭 수행 후 결과 통합
    all_matches: dict[str, dict] = {}  # headword → match 항목

    for block_info in blocks_text:
        block_id = block_info.get("block_id", "")
        text = block_info.get("text", "")
        if not text:
            continue

        block_matches = match_text(text, ref_dicts, block_id=block_id)

        for m in block_matches:
            hw = m["headword"]
            if hw in all_matches:
                # 같은 headword의 match_positions 합치기
                all_matches[hw]["match_positions"].extend(m["match_positions"])
            else:
                all_matches[hw] = m

    return list(all_matches.values())


def format_for_translation_context(matches: list[dict]) -> str:
    """매칭 결과를 번역 LLM 프롬프트에 포함할 수 있는 텍스트로 변환한다.

    목적: 사용자가 선택한 매칭 항목을 번역 프롬프트에 "사전 참고" 섹션으로 포함.
    입력: match_text() 또는 match_page_blocks()의 결과 (사용자가 선택한 것만).
    출력: 프롬프트에 포함할 참고 사전 텍스트.

    왜 이렇게 하는가:
        LLM이 번역할 때 사전 정보를 참고하면 일관성이 높아진다.
        특히 고유명사(인물, 지명)의 번역 일관성에 효과적이다.
    """
    if not matches:
        return ""

    lines = ["[참고 사전]"]
    for m in matches:
        hw = m["headword"]
        reading = m.get("headword_reading") or ""
        meaning = m.get("dictionary_meaning", "")
        ctx_meaning = m.get("contextual_meaning") or ""
        ann_type = m.get("type", "")

        line = f"- {hw}"
        if reading:
            line += f"({reading})"
        if ann_type:
            line += f" [{ann_type}]"
        line += f": {meaning}"
        if ctx_meaning:
            line += f" / 문맥: {ctx_meaning}"

        refs = m.get("source_references", [])
        if refs:
            ref_titles = [r.get("title", "") for r in refs if r.get("title")]
            if ref_titles:
                line += f" (출전: {', '.join(ref_titles)})"

        lines.append(line)

    return "\n".join(lines)
