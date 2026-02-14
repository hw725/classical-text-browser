"""문헌(Document) 관리 모듈.

각 문헌은 원본 저장소(1~4층)에 해당하는 독립 git 저장소다.
platform-v7.md 섹션 10.1의 구조를 따른다:

    {doc_id}/
    ├── manifest.json          # 문헌 메타데이터 + parts + completeness
    ├── bibliography.json      # 서지정보 (처음엔 거의 비어 있음)
    ├── L1_source/             # 1층: 원본 이미지/PDF (불변)
    ├── L2_ocr/                # 2층: OCR 결과
    ├── L3_layout/             # 3층: 레이아웃 분석
    └── L4_text/               # 4층: 교정 텍스트
        ├── pages/
        ├── corrections/
        └── alignment/
"""

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import git


# 문헌 ID 패턴: manifest.schema.json의 document_id 규칙과 동일
_DOC_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def add_document(
    library_path: str | Path,
    title: str,
    doc_id: str,
    files: list[str | Path] | None = None,
) -> Path:
    """문헌을 서고에 등록한다.

    목적: 원본 저장소 디렉토리 구조를 생성하고, 파일을 복사하고, git init 한다.
    입력:
        library_path — 서고 경로.
        title — 문헌 제목 (예: "蒙求").
        doc_id — 문헌 ID. 영문 소문자+숫자+밑줄 (예: "monggu").
        files — L1_source에 복사할 파일 경로 목록. None이면 빈 문헌.
    출력: 생성된 문헌 디렉토리의 Path.

    Raises:
        FileExistsError: 같은 doc_id의 문헌이 이미 존재할 때.
        ValueError: doc_id 형식이 올바르지 않을 때.
        FileNotFoundError: 지정된 파일이 없을 때.
    """
    library_path = Path(library_path).resolve()
    doc_path = library_path / "documents" / doc_id

    # doc_id 형식 검증
    if not _DOC_ID_PATTERN.match(doc_id):
        raise ValueError(
            f"문헌 ID 형식이 올바르지 않습니다: '{doc_id}'\n"
            "→ 해결: 영문 소문자로 시작하고, 소문자·숫자·밑줄만 사용하세요. (예: monggu, test_01)"
        )

    if doc_path.exists():
        raise FileExistsError(
            f"문헌이 이미 존재합니다: {doc_path}\n"
            "→ 해결: 다른 doc_id를 사용하세요."
        )

    # --- 디렉토리 구조 생성 (v7 §10.1) ---
    doc_path.mkdir(parents=True)
    (doc_path / "L1_source").mkdir()
    (doc_path / "L2_ocr").mkdir()
    (doc_path / "L3_layout").mkdir()
    l4 = doc_path / "L4_text"
    (l4 / "pages").mkdir(parents=True)
    (l4 / "corrections").mkdir()
    (l4 / "alignment").mkdir()

    # --- 파일 복사 → parts 구성 ---
    parts = []
    if files:
        for file_path in files:
            file_path = Path(file_path)
            if not file_path.exists():
                raise FileNotFoundError(
                    f"파일을 찾을 수 없습니다: {file_path}\n"
                    "→ 해결: 파일 경로를 확인하세요."
                )
            dest = doc_path / "L1_source" / file_path.name
            shutil.copy2(file_path, dest)
            part_id = f"vol{len(parts) + 1}"
            parts.append({
                "part_id": part_id,
                "label": file_path.stem,
                "file": f"L1_source/{file_path.name}",
                "page_count": None,
            })

    # --- manifest.json (manifest.schema.json 준수) ---
    manifest = {
        "document_id": doc_id,
        "title": title,
        "title_ko": None,
        "parts": parts,
        "completeness_status": "file_only",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": None,
    }
    _write_json(doc_path / "manifest.json", manifest)

    # --- bibliography.json (초기: 제목만 채움, 나머지 null) ---
    bibliography = {"title": title}
    _write_json(doc_path / "bibliography.json", bibliography)

    # --- git init + .gitattributes (LFS 설정) ---
    # v7 §5.1: git-lfs 필수. 이미지/PDF는 LFS로 관리.
    gitattributes_content = (
        "# git-lfs: 이미지/PDF 대용량 파일 관리 (v7 §5.1)\n"
        "*.pdf filter=lfs diff=lfs merge=lfs -text\n"
        "*.jpg filter=lfs diff=lfs merge=lfs -text\n"
        "*.jpeg filter=lfs diff=lfs merge=lfs -text\n"
        "*.png filter=lfs diff=lfs merge=lfs -text\n"
        "*.tif filter=lfs diff=lfs merge=lfs -text\n"
        "*.tiff filter=lfs diff=lfs merge=lfs -text\n"
    )
    (doc_path / ".gitattributes").write_text(gitattributes_content, encoding="utf-8")

    repo = git.Repo.init(doc_path)
    repo.index.add(["."])
    repo.index.commit(f"feat: 문헌 등록 — {title}")

    # --- 서고 매니페스트 업데이트 ---
    _update_library_manifest(library_path, doc_id, title)

    return doc_path


def get_document_info(doc_path: str | Path) -> dict:
    """manifest.json을 읽어 반환한다.

    목적: 문헌의 메타데이터를 조회한다.
    입력: doc_path — 문헌 디렉토리 경로.
    출력: manifest.json의 내용 (dict).
    """
    doc_path = Path(doc_path).resolve()
    manifest_path = doc_path / "manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"문헌을 찾을 수 없습니다: {manifest_path}\n"
            "→ 해결: 올바른 문헌 경로를 지정하세요."
        )

    return json.loads(manifest_path.read_text(encoding="utf-8"))


def list_pages(doc_path: str | Path) -> list[dict]:
    """L1_source/ 내의 파일(페이지) 목록을 반환한다.

    목적: 문헌의 원본 파일 목록을 조회한다.
    입력: doc_path — 문헌 디렉토리 경로.
    출력: 파일 정보 dict의 리스트 (filename, size, suffix).
    """
    doc_path = Path(doc_path).resolve()
    source_dir = doc_path / "L1_source"

    if not source_dir.exists():
        return []

    pages = []
    for f in sorted(source_dir.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            pages.append({
                "filename": f.name,
                "size": f.stat().st_size,
                "suffix": f.suffix,
            })

    return pages


def get_pdf_path(doc_path: str | Path, part_id: str) -> Path:
    """manifest의 parts에서 part_id에 해당하는 PDF 파일 경로를 반환한다.

    목적: PDF 뷰어에 파일을 서빙하기 위해 실제 파일 경로를 조립한다.
    입력:
        doc_path — 문헌 디렉토리 경로.
        part_id — 권 식별자 (예: "vol1").
    출력: PDF 파일의 절대 Path.
    왜 이렇게 하는가: manifest.json의 parts[].file은 상대 경로이므로,
                      doc_path와 합쳐서 절대 경로를 만들어야 한다.

    Raises:
        FileNotFoundError: 문헌 또는 해당 part_id를 찾을 수 없을 때.
    """
    doc_path = Path(doc_path).resolve()
    manifest = get_document_info(doc_path)

    for part in manifest.get("parts", []):
        if part["part_id"] == part_id:
            pdf_path = doc_path / part["file"]
            if not pdf_path.exists():
                raise FileNotFoundError(
                    f"PDF 파일을 찾을 수 없습니다: {pdf_path}\n"
                    "→ 해결: L1_source/ 디렉토리에 파일이 있는지 확인하세요."
                )
            return pdf_path

    available = [p["part_id"] for p in manifest.get("parts", [])]
    raise FileNotFoundError(
        f"권을 찾을 수 없습니다: part_id='{part_id}'\n"
        f"→ 사용 가능한 part_id: {available}"
    )


def _text_file_path(doc_path: Path, part_id: str, page_num: int) -> Path:
    """텍스트 파일 경로를 조립한다. (내부 유틸리티)

    컨벤션: L4_text/pages/{part_id}_page_{NNN}.txt (NNN = 3자리 zero-padded)
    왜 이렇게 하는가: 다권본에서 각 권의 각 페이지를 고유하게 식별하기 위해
                      part_id + 페이지 번호를 결합한다.
    """
    filename = f"{part_id}_page_{page_num:03d}.txt"
    return doc_path / "L4_text" / "pages" / filename


def get_page_text(doc_path: str | Path, part_id: str, page_num: int) -> dict:
    """특정 페이지의 텍스트를 읽어 반환한다.

    목적: L4_text/pages/ 에서 해당 페이지의 텍스트 파일을 읽는다.
    입력:
        doc_path — 문헌 디렉토리 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호 (1부터 시작).
    출력: dict with document_id, part_id, page, text, file_path, exists.
    왜 이렇게 하는가: 텍스트가 아직 입력되지 않은 페이지도 있을 수 있으므로,
                      파일이 없으면 빈 문자열과 exists=false를 반환한다.
    """
    doc_path = Path(doc_path).resolve()
    manifest = get_document_info(doc_path)
    text_path = _text_file_path(doc_path, part_id, page_num)

    # doc_path 기준 상대 경로 (Windows/Unix 호환 슬래시)
    relative_path = text_path.relative_to(doc_path).as_posix()

    if text_path.exists():
        text = text_path.read_text(encoding="utf-8")
        return {
            "document_id": manifest["document_id"],
            "part_id": part_id,
            "page": page_num,
            "text": text,
            "file_path": relative_path,
            "exists": True,
        }

    return {
        "document_id": manifest["document_id"],
        "part_id": part_id,
        "page": page_num,
        "text": "",
        "file_path": relative_path,
        "exists": False,
    }


def save_page_text(
    doc_path: str | Path,
    part_id: str,
    page_num: int,
    text: str,
) -> dict:
    """특정 페이지의 텍스트를 저장한다.

    목적: L4_text/pages/ 에 텍스트 파일을 기록한다.
    입력:
        doc_path — 문헌 디렉토리 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호.
        text — 저장할 텍스트 내용.
    출력: dict with status, file_path, size.
    왜 이렇게 하는가: 사용자가 우측 에디터에서 텍스트를 입력하면,
                      이 함수가 호출되어 L4_text/pages/에 파일로 저장된다.
                      UTF-8 인코딩, LF 줄바꿈으로 통일한다.
    """
    doc_path = Path(doc_path).resolve()
    text_path = _text_file_path(doc_path, part_id, page_num)

    # L4_text/pages/ 디렉토리가 없으면 생성
    text_path.parent.mkdir(parents=True, exist_ok=True)

    # LF 줄바꿈으로 통일 (Windows CRLF → LF)
    normalized_text = text.replace("\r\n", "\n")
    text_path.write_text(normalized_text, encoding="utf-8")

    relative_path = text_path.relative_to(doc_path).as_posix()
    return {
        "status": "saved",
        "file_path": relative_path,
        "size": len(normalized_text.encode("utf-8")),
    }


def _layout_file_path(doc_path: Path, part_id: str, page_num: int) -> Path:
    """L3 레이아웃 파일 경로를 조립한다. (내부 유틸리티)

    컨벤션: L3_layout/{part_id}_page_{NNN}.json (NNN = 3자리 zero-padded)
    왜 이렇게 하는가: L4_text와 동일한 네이밍 규칙을 사용하여 일관성을 유지한다.
    """
    filename = f"{part_id}_page_{page_num:03d}.json"
    return doc_path / "L3_layout" / filename


def get_page_layout(doc_path: str | Path, part_id: str, page_num: int) -> dict:
    """특정 페이지의 레이아웃(LayoutBlock 목록)을 읽어 반환한다.

    목적: L3_layout/ 에서 해당 페이지의 레이아웃 JSON 파일을 읽는다.
    입력:
        doc_path — 문헌 디렉토리 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호 (1부터 시작).
    출력: layout_page.schema.json 형식의 dict.
          파일이 없으면 빈 blocks 배열과 exists=false를 반환한다.
    왜 이렇게 하는가: 레이아웃이 아직 작성되지 않은 페이지도 있으므로,
                      파일이 없으면 기본 구조를 반환한다.
    """
    doc_path = Path(doc_path).resolve()
    manifest = get_document_info(doc_path)
    layout_path = _layout_file_path(doc_path, part_id, page_num)

    relative_path = layout_path.relative_to(doc_path).as_posix()

    if layout_path.exists():
        data = json.loads(layout_path.read_text(encoding="utf-8"))
        data["_meta"] = {
            "document_id": manifest["document_id"],
            "file_path": relative_path,
            "exists": True,
        }
        return data

    # 파일이 없으면 빈 레이아웃 반환
    return {
        "part_id": part_id,
        "page_number": page_num,
        "image_width": None,
        "image_height": None,
        "analysis_method": None,
        "blocks": [],
        "_meta": {
            "document_id": manifest["document_id"],
            "file_path": relative_path,
            "exists": False,
        },
    }


def save_page_layout(
    doc_path: str | Path,
    part_id: str,
    page_num: int,
    layout_data: dict,
) -> dict:
    """특정 페이지의 레이아웃을 저장한다.

    목적: L3_layout/ 에 레이아웃 JSON 파일을 기록한다.
    입력:
        doc_path — 문헌 디렉토리 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호.
        layout_data — layout_page.schema.json 형식의 dict.
    출력: dict with status, file_path, block_count.
    왜 이렇게 하는가: 레이아웃 편집기에서 사용자가 LayoutBlock을 그리고 저장하면,
                      이 함수가 호출되어 L3_layout/에 JSON으로 기록된다.
                      저장 전에 jsonschema로 검증하여, 잘못된 데이터가 저장되지 않도록 한다.

    Raises:
        jsonschema.ValidationError: 스키마 검증 실패 시.
    """
    import jsonschema

    doc_path = Path(doc_path).resolve()
    layout_path = _layout_file_path(doc_path, part_id, page_num)

    # L3_layout/ 디렉토리가 없으면 생성
    layout_path.parent.mkdir(parents=True, exist_ok=True)

    # 스키마 검증
    schema_path = (
        Path(__file__).resolve().parent.parent.parent
        / "schemas" / "source_repo" / "layout_page.schema.json"
    )
    if schema_path.exists():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        # _meta 필드는 내부용이므로 검증 전에 제거
        validate_data = {k: v for k, v in layout_data.items() if not k.startswith("_")}
        jsonschema.validate(instance=validate_data, schema=schema)

    # _meta 필드 제거 후 저장
    save_data = {k: v for k, v in layout_data.items() if not k.startswith("_")}
    _write_json(layout_path, save_data)

    relative_path = layout_path.relative_to(doc_path).as_posix()
    return {
        "status": "saved",
        "file_path": relative_path,
        "block_count": len(save_data.get("blocks", [])),
    }


def _update_library_manifest(library_path: Path, doc_id: str, title: str) -> None:
    """서고 매니페스트에 새 문헌을 추가한다. (내부 유틸리티)"""
    manifest_path = library_path / "library_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"documents": []}

    manifest["documents"].append({
        "document_id": doc_id,
        "title": title,
        "path": f"documents/{doc_id}",
    })

    _write_json(manifest_path, manifest)


def _write_json(path: Path, data: dict) -> None:
    """JSON 파일을 UTF-8로 저장한다. (내부 유틸리티)"""
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
