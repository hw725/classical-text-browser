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
            try:
                shutil.copy2(file_path, dest)
            except PermissionError as e:
                raise ValueError(
                    f"파일 복사 권한이 없습니다: {file_path} → {dest}\n"
                    f"→ 원인: {e}\n"
                    "→ 해결: 파일 및 대상 폴더의 읽기/쓰기 권한을 확인하세요."
                ) from e
            except OSError as e:
                raise ValueError(
                    f"파일 복사 중 오류가 발생했습니다: {file_path} → {dest}\n"
                    f"→ 원인: {e}\n"
                    "→ 해결: 디스크 공간, 파일 경로 길이, 네트워크 드라이브 연결 상태를 확인하세요."
                ) from e
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
    gitignore_content = (
        "# 안전 규칙: 저장소 내부 Git 메타데이터는 절대 추적하지 않는다.\n"
        ".git\n"
        ".git/\n"
        "**/.git\n"
        "**/.git/**\n"
        "\n"
        "# 임시/캐시 파일\n"
        "__pycache__/\n"
        "*.py[cod]\n"
        "*.tmp\n"
        "*.temp\n"
        "\n"
        "# 에디터/OS 잡파일\n"
        ".DS_Store\n"
        "Thumbs.db\n"
        ".vscode/\n"
        ".idea/\n"
    )
    (doc_path / ".gitignore").write_text(gitignore_content, encoding="utf-8")

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


def get_bibliography(doc_path: str | Path) -> dict:
    """문헌의 서지정보(bibliography.json)를 읽어 반환한다.

    목적: 문헌의 서지정보를 조회한다.
    입력: doc_path — 문헌 디렉토리 경로.
    출력: bibliography.json의 내용 (dict). 파일이 없으면 기본 구조 반환.
    왜 이렇게 하는가: 서지정보는 처음에는 거의 비어 있을 수 있고,
                      나중에 파서나 수동 입력으로 채워진다.
    """
    doc_path = Path(doc_path).resolve()
    bib_path = doc_path / "bibliography.json"

    if bib_path.exists():
        return json.loads(bib_path.read_text(encoding="utf-8"))

    # 파일이 없으면 manifest에서 제목만 가져와 기본 구조 반환
    manifest = get_document_info(doc_path)
    return {"title": manifest.get("title")}


def save_bibliography(doc_path: str | Path, bibliography: dict) -> dict:
    """문헌의 서지정보를 저장한다.

    목적: bibliography.json을 갱신한다.
    입력:
        doc_path — 문헌 디렉토리 경로.
        bibliography — bibliography.schema.json 형식의 dict.
    출력: {status: "saved", file_path}.
    왜 이렇게 하는가: 파서가 외부 소스에서 가져온 서지정보를 저장하거나,
                      사용자가 수동으로 편집한 내용을 저장할 때 사용한다.
                      저장 전에 jsonschema로 검증하여 잘못된 데이터를 방지한다.
    """
    import jsonschema

    doc_path = Path(doc_path).resolve()
    bib_path = doc_path / "bibliography.json"

    # 스키마 검증
    schema_path = (
        Path(__file__).resolve().parent.parent.parent
        / "schemas" / "source_repo" / "bibliography.schema.json"
    )
    if schema_path.exists():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        # _mapping_info, raw_metadata는 스키마에 포함되어 있으므로 그대로 검증
        # 단, 검증 전에 빈 값 정리 (null 필드는 스키마가 허용)
        jsonschema.validate(instance=bibliography, schema=schema)

    _write_json(bib_path, bibliography)

    relative_path = bib_path.relative_to(doc_path).as_posix()
    return {
        "status": "saved",
        "file_path": relative_path,
    }


def _corrections_file_path(doc_path: Path, part_id: str, page_num: int) -> Path:
    """교정 파일 경로를 조립한다. (내부 유틸리티)

    컨벤션: L4_text/corrections/{part_id}_page_{NNN}_corrections.json
    왜 이렇게 하는가: 교정 데이터를 텍스트 파일과 분리하여 저장하면,
                      텍스트 원본과 교정 기록을 독립적으로 관리할 수 있다.
                      네이밍 규칙은 L4_text/pages, L3_layout과 동일하게 유지한다.
    """
    filename = f"{part_id}_page_{page_num:03d}_corrections.json"
    return doc_path / "L4_text" / "corrections" / filename


def get_page_corrections(doc_path: str | Path, part_id: str, page_num: int) -> dict:
    """특정 페이지의 교정 기록을 읽어 반환한다.

    목적: L4_text/corrections/ 에서 해당 페이지의 교정 JSON 파일을 읽는다.
    입력:
        doc_path — 문헌 디렉토리 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호 (1부터 시작).
    출력: corrections.schema.json 형식의 dict + _meta.
          파일이 없으면 빈 corrections 배열과 exists=false를 반환한다.
    왜 이렇게 하는가: 교정이 아직 진행되지 않은 페이지도 있으므로,
                      파일이 없으면 기본 구조를 반환한다.
    """
    doc_path = Path(doc_path).resolve()
    manifest = get_document_info(doc_path)
    corr_path = _corrections_file_path(doc_path, part_id, page_num)

    relative_path = corr_path.relative_to(doc_path).as_posix()

    if corr_path.exists():
        data = json.loads(corr_path.read_text(encoding="utf-8"))
        data["_meta"] = {
            "document_id": manifest["document_id"],
            "file_path": relative_path,
            "exists": True,
        }
        return data

    # 파일이 없으면 빈 교정 반환
    return {
        "part_id": part_id,
        "corrections": [],
        "_meta": {
            "document_id": manifest["document_id"],
            "file_path": relative_path,
            "exists": False,
        },
    }


def get_corrected_text(
    doc_path: str | Path, part_id: str, page_num: int
) -> dict:
    """교정이 적용된 텍스트를 반환한다.

    목적: L4_text/pages/의 원본 텍스트에 L4_text/corrections/의 교정 기록을
          적용하여, "교정된 텍스트"를 생성한다. 편성(composition) 단계에서
          TextBlock을 만들 때 이 텍스트를 사용한다.
    입력:
        doc_path — 문헌 디렉토리 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호 (1부터 시작).
    출력:
        {
            "document_id": str,
            "part_id": str,
            "page": int,
            "original_text": str,      — 교정 전 원본
            "corrected_text": str,     — 교정 적용 후 텍스트
            "correction_count": int,   — 적용된 교정 건수
            "blocks": [                — 블록별 교정 텍스트 (L3 있을 때)
                {
                    "block_id": str,
                    "original_text": str,
                    "corrected_text": str,
                    "corrections_applied": int,
                },
                ...
            ]
        }

    왜 이렇게 하는가:
        교정 에디터는 원본을 건드리지 않고 교정 기록만 저장한다.
        표점·현토 등 후속 작업에서는 "교정된 텍스트"가 필요하므로,
        이 함수가 원본 + 교정 기록을 합쳐 교정된 텍스트를 생성한다.
    """
    doc_path = Path(doc_path).resolve()
    manifest = get_document_info(doc_path)

    # 원본 텍스트 로드
    text_result = get_page_text(doc_path, part_id, page_num)
    original_text = text_result["text"]

    # 교정 기록 로드
    corr_result = get_page_corrections(doc_path, part_id, page_num)
    corrections = corr_result.get("corrections", [])

    # L3 레이아웃 로드 (블록별 분리를 위해)
    layout_result = get_page_layout(doc_path, part_id, page_num)
    blocks_meta = layout_result.get("blocks", [])

    # 전체 텍스트에 교정 적용
    corrected_text = _apply_corrections_to_text(original_text, corrections)

    # 블록별 교정 텍스트 (블록 마커가 있는 경우)
    block_texts = _split_text_by_blocks(original_text, blocks_meta)
    result_blocks = []
    for bt in block_texts:
        block_corrs = [
            c for c in corrections if c.get("block_id") == bt["block_id"]
        ]
        bt_corrected = _apply_corrections_to_text(
            bt["text"], block_corrs, block_local=True
        )
        result_blocks.append({
            "block_id": bt["block_id"],
            "block_type": bt.get("block_type", "main_text"),
            "original_text": bt["text"],
            "corrected_text": bt_corrected,
            "corrections_applied": len(block_corrs),
        })

    return {
        "document_id": manifest["document_id"],
        "part_id": part_id,
        "page": page_num,
        "original_text": original_text,
        "corrected_text": corrected_text,
        "correction_count": len(corrections),
        "blocks": result_blocks,
    }


def _apply_corrections_to_text(
    text: str, corrections: list[dict], block_local: bool = False
) -> str:
    """텍스트에 교정 기록을 적용한다. (내부 유틸리티)

    왜 이렇게 하는가:
        교정 기록의 line/char_index를 사용하여 원본 텍스트의 해당 위치를
        찾아 교정문으로 치환한다. 교정 기록이 없으면 원본 그대로 반환.

    block_local이 True이면 line/char_index가 블록 내부 기준이라고 간주한다.
    """
    if not corrections:
        return text

    lines = text.split("\n")

    # 교정을 역순으로 적용 (뒤에서부터 치환해야 인덱스가 밀리지 않음)
    # line + char_index 기준으로 정렬 후 역순
    sorted_corrs = sorted(
        corrections,
        key=lambda c: (c.get("line") or 0, c.get("char_index") or 0),
        reverse=True,
    )

    for corr in sorted_corrs:
        line_num = corr.get("line")
        char_idx = corr.get("char_index")
        original_ocr = corr.get("original_ocr", "")
        corrected = corr.get("corrected", "")

        if char_idx is None:
            continue

        if line_num is not None:
            # 줄+글자 좌표 방식
            if line_num < 0 or line_num >= len(lines):
                continue
            line = lines[line_num]
            end_idx = char_idx + len(original_ocr)
            if end_idx <= len(line) and line[char_idx:end_idx] == original_ocr:
                lines[line_num] = line[:char_idx] + corrected + line[end_idx:]
        else:
            # line=null → char_index가 페이지 전체 기준 평면 인덱스
            # 줄바꿈 포함 전체 텍스트에서 직접 치환
            full = "\n".join(lines)
            end_idx = char_idx + len(original_ocr)
            if end_idx <= len(full) and full[char_idx:end_idx] == original_ocr:
                full = full[:char_idx] + corrected + full[end_idx:]
                lines = full.split("\n")

    return "\n".join(lines)


def _split_text_by_blocks(
    text: str, blocks_meta: list[dict]
) -> list[dict]:
    """텍스트를 L3 블록 기준으로 분리한다. (내부 유틸리티)

    왜 이렇게 하는가:
        L4 텍스트는 페이지 단위로 저장되지만, 편성 에디터에서는
        블록 단위로 표시해야 한다. 텍스트에 [本文], [注釈] 마커가 있으면
        이를 기준으로 분리하고, 없으면 전체를 하나의 블록으로 취급한다.

    현재 L4 텍스트의 구조:
        - 마커가 없으면: 전체 텍스트가 첫 번째 블록
        - [本文] / [注釈] 마커가 있으면: 마커 기준으로 분리
    """
    import re

    # 블록이 없으면 전체를 하나의 기본 블록으로
    if not blocks_meta:
        default_block_id = f"p{1:02d}_b01"
        return [{
            "block_id": default_block_id,
            "block_type": "main_text",
            "text": text,
        }]

    # [本文] / [注釈] 마커로 분리 시도
    marker_pattern = re.compile(r"\[(本文|注釈)\]")
    markers = list(marker_pattern.finditer(text))

    if not markers:
        # 마커가 없으면: 블록 메타 순서대로 전체 텍스트를 첫 블록에 배정
        result = []
        for i, bm in enumerate(blocks_meta):
            result.append({
                "block_id": bm.get("block_id", f"b{i+1:02d}"),
                "block_type": bm.get("block_type", "main_text"),
                "text": text if i == 0 else "",
            })
        return result

    # 마커 기반 분리
    result = []
    segments = []
    last_idx = 0
    last_type = "main_text"

    for m in markers:
        if m.start() > last_idx:
            seg_text = text[last_idx:m.start()].strip()
            if seg_text:
                segments.append({"type": last_type, "text": seg_text})
        last_type = "main_text" if m.group(1) == "本文" else "annotation"
        last_idx = m.end()

    # 마지막 세그먼트
    if last_idx < len(text):
        seg_text = text[last_idx:].strip()
        if seg_text:
            segments.append({"type": last_type, "text": seg_text})

    # 세그먼트와 블록 메타를 매칭
    for i, seg in enumerate(segments):
        if i < len(blocks_meta):
            block_id = blocks_meta[i].get("block_id", f"b{i+1:02d}")
            block_type = blocks_meta[i].get("block_type", seg["type"])
        else:
            block_id = f"extra_b{i+1:02d}"
            block_type = seg["type"]

        result.append({
            "block_id": block_id,
            "block_type": block_type,
            "text": seg["text"],
        })

    return result


def save_page_corrections(
    doc_path: str | Path,
    part_id: str,
    page_num: int,
    corrections_data: dict,
) -> dict:
    """특정 페이지의 교정 기록을 저장한다.

    목적: L4_text/corrections/ 에 교정 JSON 파일을 기록한다.
    입력:
        doc_path — 문헌 디렉토리 경로.
        part_id — 권 식별자.
        page_num — 페이지 번호.
        corrections_data — corrections.schema.json 형식의 dict.
    출력: dict with status, file_path, correction_count.
    왜 이렇게 하는가: 교정 편집기에서 사용자가 글자 교정을 완료하면,
                      이 함수가 호출되어 교정 기록이 JSON으로 저장된다.
                      저장 전에 jsonschema로 검증하여, 잘못된 데이터가 저장되지 않도록 한다.

    Raises:
        jsonschema.ValidationError: 스키마 검증 실패 시.
    """
    import jsonschema

    doc_path = Path(doc_path).resolve()
    corr_path = _corrections_file_path(doc_path, part_id, page_num)

    # L4_text/corrections/ 디렉토리가 없으면 생성
    corr_path.parent.mkdir(parents=True, exist_ok=True)

    # 스키마 검증
    schema_path = (
        Path(__file__).resolve().parent.parent.parent
        / "schemas" / "source_repo" / "corrections.schema.json"
    )
    if schema_path.exists():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        # _meta 필드는 내부용이므로 검증 전에 제거
        validate_data = {k: v for k, v in corrections_data.items() if not k.startswith("_")}
        jsonschema.validate(instance=validate_data, schema=schema)

    # _meta 필드 제거 후 저장
    save_data = {k: v for k, v in corrections_data.items() if not k.startswith("_")}
    _write_json(corr_path, save_data)

    relative_path = corr_path.relative_to(doc_path).as_posix()
    return {
        "status": "saved",
        "file_path": relative_path,
        "correction_count": len(save_data.get("corrections", [])),
    }


def git_commit_document(
    doc_path: str | Path,
    message: str,
    add_paths: list[str] | None = None,
) -> dict:
    """문헌 저장소에 git commit을 생성한다.

    목적: 교정 저장 시 자동으로 커밋하여 버전 이력을 남긴다.
    입력:
        doc_path — 문헌 디렉토리 경로 (git 저장소).
        message — 커밋 메시지.
    출력: {committed: True/False, hash, message}.
    왜 이렇게 하는가: 매 교정 저장마다 커밋하면, 모든 변경 이력이
                      git log에 남아 언제든 이전 상태로 돌아갈 수 있다.
                      변경사항이 없으면 빈 커밋을 만들지 않는다.
    """
    doc_path = Path(doc_path).resolve()

    try:
        repo = git.Repo(doc_path)
    except git.InvalidGitRepositoryError:
        # git 저장소가 아직 없으면 자동 초기화한다.
        # 왜: add_document()로 정식 등록하지 않은 문헌(더미 등)도
        #      교정 저장 시 자연스럽게 git 이력을 시작할 수 있게 한다.
        repo = git.Repo.init(doc_path)

    # 변경사항이 없으면 커밋 스킵
    if not repo.is_dirty(untracked_files=True):
        return {"committed": False, "message": "변경사항 없음"}

    if add_paths:
        staged_paths = []
        for rel_path in add_paths:
            if not rel_path:
                continue
            abs_path = (doc_path / rel_path).resolve()
            if abs_path.exists():
                staged_paths.append(rel_path)

        if staged_paths:
            repo.index.add(staged_paths)
        else:
            repo.index.add(["."])
    else:
        repo.index.add(["."])

    try:
        commit = repo.index.commit(message)
    except git.HookExecutionError:
        # Git LFS 등의 post-commit hook이 실패할 수 있다.
        # 커밋 자체는 이미 완료되었으므로, hook 에러는 무시하고
        # 마지막 커밋 정보를 가져온다.
        commit = repo.head.commit

    return {
        "committed": True,
        "hash": commit.hexsha,
        "short_hash": commit.hexsha[:7],
        "message": message,
    }


def get_git_log(doc_path: str | Path, max_count: int = 50) -> list[dict]:
    """문헌 저장소의 git 커밋 이력을 반환한다.

    목적: 하단 패널의 Git 이력 탭에 표시할 커밋 목록을 가져온다.
    입력:
        doc_path — 문헌 디렉토리 경로.
        max_count — 최대 커밋 수 (기본 50).
    출력: [{hash, short_hash, message, author, date}, ...].
    왜 이렇게 하는가: 연구자가 자신의 교정 이력을 확인하고,
                      특정 시점의 상태를 찾아볼 수 있게 한다.
    """
    doc_path = Path(doc_path).resolve()

    try:
        repo = git.Repo(doc_path)
    except git.InvalidGitRepositoryError:
        return []

    commits = []
    for c in repo.iter_commits(max_count=max_count):
        commits.append({
            "hash": c.hexsha,
            "short_hash": c.hexsha[:7],
            "message": c.message.strip(),
            "author": str(c.author),
            "date": c.committed_datetime.isoformat(),
        })

    return commits


def get_git_diff(doc_path: str | Path, commit_hash: str) -> dict:
    """특정 커밋과 그 부모 커밋 사이의 diff를 반환한다.

    목적: 특정 교정 커밋에서 무엇이 변경되었는지 확인한다.
    입력:
        doc_path — 문헌 디렉토리 경로.
        commit_hash — 대상 커밋 해시 (full 또는 short).
    출력: {commit_hash, message, diffs: [{file, change_type, diff_text}, ...]}.
    왜 이렇게 하는가: 연구자가 교정 전후를 비교하여,
                      어떤 글자가 어떻게 변경되었는지 확인할 수 있다.
    """
    doc_path = Path(doc_path).resolve()

    try:
        repo = git.Repo(doc_path)
        commit = repo.commit(commit_hash)
    except (git.InvalidGitRepositoryError, git.BadName, ValueError):
        return {"error": f"커밋을 찾을 수 없습니다: {commit_hash}"}

    result = {
        "commit_hash": commit.hexsha,
        "short_hash": commit.hexsha[:7],
        "message": commit.message.strip(),
        "author": str(commit.author),
        "date": commit.committed_datetime.isoformat(),
        "diffs": [],
    }

    # 부모가 없으면 (최초 커밋) 빈 트리와 비교
    if commit.parents:
        parent = commit.parents[0]
        diffs = parent.diff(commit, create_patch=True)
    else:
        diffs = commit.diff(git.NULL_TREE, create_patch=True)

    for d in diffs:
        diff_entry = {
            "file": d.b_path or d.a_path,
            "change_type": d.change_type,
        }
        # diff 텍스트 (패치 내용)
        try:
            diff_entry["diff_text"] = d.diff.decode("utf-8", errors="replace")
        except Exception:
            diff_entry["diff_text"] = "(바이너리 파일)"

        result["diffs"].append(diff_entry)

    return result


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


def _formatting_file_path(doc_path: Path, part_id: str, page_num: int) -> Path:
    """서식 메타데이터(대두 등) 파일 경로를 조립한다. (내부 유틸리티)

    컨벤션: L4_text/pages/{part_id}_page_{NNN}_formatting.json
    왜 이렇게 하는가: 대두 등 서식 정보를 L4 txt 파일과 분리하여 저장하면,
                      기존 파이프라인에 전혀 영향 없이 서식 메타데이터를 관리할 수 있다.
    """
    filename = f"{part_id}_page_{page_num:03d}_formatting.json"
    return doc_path / "L4_text" / "pages" / filename


def _hwp_clean_file_path(doc_path: Path, part_id: str, page_num: int) -> Path:
    """HWP 정리 데이터(표점·현토) 사이드카 파일 경로를 조립한다. (내부 유틸리티)

    컨벤션: L4_text/pages/{part_id}_page_{NNN}_hwp_clean.json
    왜 이렇게 하는가: HWP에서 분리한 표점·현토 데이터를 L4 옆에 보관해 두면,
                      나중에 L5(해석 저장소)로 가져갈 때 원본 데이터로 사용할 수 있다.
    """
    filename = f"{part_id}_page_{page_num:03d}_hwp_clean.json"
    return doc_path / "L4_text" / "pages" / filename


def _ocr_file_path(doc_path: Path, part_id: str, page_num: int) -> Path:
    """L2 OCR 결과 파일 경로를 조립한다. (내부 유틸리티)

    컨벤션: L2_ocr/{part_id}_page_{NNN}.json
    """
    filename = f"{part_id}_page_{page_num:03d}.json"
    return doc_path / "L2_ocr" / filename


# --- HWP 가져오기 ---


def import_hwp_text_to_document(
    library_path: str | Path,
    doc_id: str,
    hwp_file: str | Path,
    page_mapping: list[dict] | None = None,
    strip_punctuation: bool = True,
    strip_hyeonto: bool = True,
) -> dict:
    """시나리오 1: 기존 문서에 HWP 텍스트를 페이지별로 L4에 가져온다.

    목적: PDF 스캔이 이미 있는 문서에 HWP 타이핑본의 텍스트를 투입한다.
          표점·현토를 분리하여 순수 원문만 L4에 저장하고,
          분리된 데이터는 사이드카 JSON으로 보관한다.
    입력:
        library_path — 서고 경로.
        doc_id — 기존 문헌 ID.
        hwp_file — HWP/HWPX 파일 경로.
        page_mapping — HWP 섹션 ↔ PDF 페이지 매핑.
            None이면 순서대로 1:1 자동 매핑.
            형식: [{"section_index": 0, "page_num": 1, "part_id": "vol1"}, ...]
        strip_punctuation — True이면 표점을 제거하고 별도 저장.
        strip_hyeonto — True이면 현토를 제거하고 별도 저장.
    출력:
        {
            "document_id": str,
            "mode": "import_to_existing",
            "pages_saved": int,
            "text_pages": [{page_num, part_id, text_length, has_punct, has_hyeonto}],
            "cleaned_stats": {had_punctuation, had_hyeonto, punct_count, hyeonto_count},
        }

    처리 흐름:
        1. HWP 텍스트 추출 → 섹션/단락별 분할
        2. page_mapping으로 HWP 섹션 ↔ PDF 페이지 매핑 (1단계)
        3. 표점·현토 분리 (strip_punctuation, strip_hyeonto)
        4. L4_text/pages/{part_id}_page_{NNN}.txt에 저장
        5. 서식 메타데이터(대두)는 _formatting.json에 저장
        6. 표점·현토 데이터는 _hwp_clean.json에 저장
        7. completeness_status 업데이트
        8. git commit

    Raises:
        FileNotFoundError: 문헌이 존재하지 않을 때.
        FileNotFoundError: HWP 파일이 없을 때.
        ValueError: HWP 파일 형식이 지원되지 않을 때.
    """
    from hwp.reader import get_reader
    from hwp.text_cleaner import clean_hwp_text

    library_path = Path(library_path).resolve()
    hwp_file = Path(hwp_file)
    doc_path = library_path / "documents" / doc_id

    # 문서 존재 확인
    if not doc_path.exists():
        raise FileNotFoundError(
            f"문헌이 존재하지 않습니다: {doc_id}\n"
            "→ 해결: 먼저 문헌을 생성하세요. 또는 HWP만으로 새 문헌을 만들려면 "
            "create_document_from_hwp()를 사용하세요."
        )

    # HWP 텍스트 추출
    reader = get_reader(hwp_file)

    # HWPX이면 섹션별 추출, HWP이면 전체 텍스트를 줄바꿈 기준으로 분할
    if hasattr(reader, "extract_sections"):
        sections = reader.extract_sections()
        section_texts = [s["text"] for s in sections]
    else:
        full_text = reader.extract_text()
        # 빈 줄 2개 이상을 페이지 구분자로 사용
        section_texts = [t.strip() for t in re.split(r"\n{2,}", full_text) if t.strip()]

    # 매니페스트에서 parts 정보 확인
    manifest = get_document_info(doc_path)
    parts = manifest.get("parts", [])
    if not parts:
        raise ValueError(
            "문헌에 parts(파일)가 정의되어 있지 않습니다.\n"
            "→ 해결: manifest.json의 parts 배열을 확인하세요."
        )

    # 기본 part_id
    default_part_id = parts[0]["part_id"]

    # page_mapping 생성 (없으면 1:1 자동 매핑)
    if page_mapping is None:
        page_mapping = []
        for i, text in enumerate(section_texts):
            page_mapping.append({
                "section_index": i,
                "page_num": i + 1,
                "part_id": default_part_id,
            })

    # 각 페이지에 텍스트 저장
    text_pages = []
    total_punct_count = 0
    total_hyeonto_count = 0
    had_punctuation = False
    had_hyeonto = False

    for mapping in page_mapping:
        section_idx = mapping["section_index"]
        page_num = mapping["page_num"]
        part_id = mapping.get("part_id", default_part_id)

        if section_idx >= len(section_texts):
            continue  # 매핑이 섹션 수보다 많으면 건너뜀

        raw_text = section_texts[section_idx]

        # 표점·현토 분리
        result = clean_hwp_text(
            raw_text,
            strip_punct=strip_punctuation,
            strip_hyeonto=strip_hyeonto,
        )

        # L4 텍스트 저장
        save_page_text(doc_path, part_id, page_num, result.clean_text)

        # 서식 메타데이터(대두) 저장
        if result.taidu_marks:
            fmt_path = _formatting_file_path(doc_path, part_id, page_num)
            fmt_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json(fmt_path, {
                "taidu": [
                    {"pos": t["pos"], "raise_chars": t["raise_chars"], "note": t["note"]}
                    for t in result.taidu_marks
                ],
            })

        # 표점·현토 데이터 사이드카 저장 (나중에 L5로 이전 가능)
        if result.punctuation_marks or result.hyeonto_annotations:
            clean_path = _hwp_clean_file_path(doc_path, part_id, page_num)
            clean_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json(clean_path, {
                "source": "hwp_import",
                "raw_text_length": len(raw_text),
                "clean_text_length": len(result.clean_text),
                "punctuation_marks": result.punctuation_marks,
                "hyeonto_annotations": result.hyeonto_annotations,
            })

        # 통계 수집
        if result.had_punctuation:
            had_punctuation = True
        if result.had_hyeonto:
            had_hyeonto = True
        total_punct_count += len(result.punctuation_marks)
        total_hyeonto_count += len(result.hyeonto_annotations)

        text_pages.append({
            "page_num": page_num,
            "part_id": part_id,
            "text_length": len(result.clean_text),
            "has_punct": result.had_punctuation,
            "has_hyeonto": result.had_hyeonto,
        })

    # completeness_status 업데이트
    manifest["completeness_status"] = "text_imported"
    _write_json(doc_path / "manifest.json", manifest)

    # git commit
    git_commit_document(doc_path, f"feat: HWP 텍스트 가져오기 — {len(text_pages)}페이지")

    return {
        "document_id": doc_id,
        "mode": "import_to_existing",
        "pages_saved": len(text_pages),
        "text_pages": text_pages,
        "cleaned_stats": {
            "had_punctuation": had_punctuation,
            "had_hyeonto": had_hyeonto,
            "punct_count": total_punct_count,
            "hyeonto_count": total_hyeonto_count,
        },
    }


def match_hwp_text_to_layout_blocks(
    library_path: str | Path,
    doc_id: str,
    part_id: str,
    page_num: int,
    block_text_mapping: list[dict],
) -> dict:
    """2단계: 페이지 내 텍스트를 LayoutBlock 단위로 매칭한다.

    목적: 1단계(페이지 매핑) 완료 후, 레이아웃 분석(L3)이 있으면
          HWP 텍스트를 LayoutBlock 단위로 분할·매칭한다.
    입력:
        library_path — 서고 경로.
        doc_id — 문헌 ID.
        part_id — 권 식별자.
        page_num — 페이지 번호.
        block_text_mapping — [{layout_block_id, text}].
            각 항목은 해당 LayoutBlock에 대응하는 텍스트.
    출력:
        {
            "matched_blocks": int,
            "ocr_result_saved": str (L2 파일 경로),
        }

    전제: 해당 페이지의 레이아웃 분석(L3)이 완료되어 있어야 함.

    처리 흐름:
        1. block_text_mapping 검증 (LayoutBlock 존재 여부)
        2. L2 OcrResult 형태로 저장 (ocr_engine="hwp_import")
        3. git commit

    Raises:
        FileNotFoundError: 문헌이 존재하지 않을 때.
    """
    library_path = Path(library_path).resolve()
    doc_path = library_path / "documents" / doc_id

    if not doc_path.exists():
        raise FileNotFoundError(f"문헌이 존재하지 않습니다: {doc_id}")

    # L3 레이아웃 확인
    layout = get_page_layout(doc_path, part_id, page_num)
    existing_block_ids = {
        b["block_id"] for b in layout.get("blocks", [])
    }

    # OcrResult 목록 생성 (ocr_page.schema.json 형식)
    ocr_results = []
    matched = 0

    for mapping in block_text_mapping:
        block_id = mapping.get("layout_block_id")
        text = mapping.get("text", "")

        if not text:
            continue

        # LayoutBlock 존재 여부 확인 (경고만, 에러는 아님)
        if block_id and block_id not in existing_block_ids:
            import logging
            logging.getLogger(__name__).warning(
                "LayoutBlock이 L3에 존재하지 않습니다: %s (page %d)",
                block_id, page_num,
            )

        # 텍스트를 줄 단위로 분할하여 OcrLine 형태로 변환
        lines = []
        for line_text in text.split("\n"):
            if line_text.strip():
                lines.append({
                    "text": line_text,
                    "bbox": None,
                    "characters": None,
                })

        ocr_results.append({
            "layout_block_id": block_id,
            "lines": lines,
        })
        matched += 1

    # L2 OcrResult 저장
    ocr_page_data = {
        "part_id": part_id,
        "page_number": page_num,
        "ocr_engine": "hwp_import",
        "ocr_config": {
            "engine": "hwp_import",
            "language": None,
            "direction": None,
        },
        "ocr_results": ocr_results,
    }

    ocr_path = _ocr_file_path(doc_path, part_id, page_num)
    ocr_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(ocr_path, ocr_page_data)

    relative_path = ocr_path.relative_to(doc_path).as_posix()

    # git commit
    git_commit_document(
        doc_path,
        f"feat: HWP 텍스트 LayoutBlock 매칭 — page {page_num}, {matched}블록",
    )

    return {
        "matched_blocks": matched,
        "ocr_result_saved": relative_path,
    }


def create_document_from_hwp(
    library_path: str | Path,
    hwp_file: str | Path,
    doc_id: str,
    title: str | None = None,
    strip_punctuation: bool = True,
    strip_hyeonto: bool = True,
) -> dict:
    """시나리오 2: HWP 파일로 새 문헌을 생성한다.

    목적: PDF 없이 HWP 파일만 있을 때, HWP 자체를 원본으로 새 문헌을 만든다.
          텍스트를 추출하여 페이지별로 L4에 저장하고,
          표점·현토를 분리한 데이터는 사이드카 JSON으로 보관한다.
    입력:
        library_path — 서고 경로.
        hwp_file — HWP/HWPX 파일 경로.
        doc_id — 새 문헌 ID (영문 소문자+숫자+밑줄).
        title — 문헌 제목 (None이면 HWP 메타데이터에서 추출).
        strip_punctuation — True이면 표점을 제거하고 별도 저장.
        strip_hyeonto — True이면 현토를 제거하고 별도 저장.
    출력:
        {
            "doc_path": str,
            "document_id": str,
            "title": str,
            "mode": "create_from_hwp",
            "pages_saved": int,
            "text_pages": [{page_num, text_length, has_punct, has_hyeonto}],
            "cleaned_stats": {...},
            "images_extracted": int,
        }

    처리 흐름:
        1. HWP 파일 → L1_source에 복사 (원본 보존)
        2. 메타데이터 추출 → 제목, 서지정보
        3. 텍스트 추출 → 표점·현토 분리 → L4_text/pages/에 페이지별 저장
        4. 서식 메타데이터(대두) → _formatting.json
        5. 표점·현토 데이터 → _hwp_clean.json 사이드카
        6. 이미지 추출 (있으면) → L1_source에 저장
        7. bibliography.json에 메타데이터
        8. completeness_status = "text_imported"
        9. git commit

    Raises:
        FileExistsError: 같은 doc_id의 문헌이 이미 존재할 때.
        FileNotFoundError: HWP 파일이 없을 때.
        ValueError: HWP 파일 형식이 지원되지 않을 때.
    """
    from hwp.reader import get_reader
    from hwp.text_cleaner import clean_hwp_text

    library_path = Path(library_path).resolve()
    hwp_file = Path(hwp_file)

    if not hwp_file.exists():
        raise FileNotFoundError(
            f"HWP 파일을 찾을 수 없습니다: {hwp_file}\n"
            "→ 해결: 파일 경로를 확인하세요."
        )

    # 리더로 메타데이터 추출 (파일 형식도 검증됨)
    reader = get_reader(hwp_file)
    metadata = reader.extract_metadata()
    effective_title = title or metadata.get("title") or hwp_file.stem

    # 1. 문헌 생성 (HWP 파일을 L1_source에 복사)
    doc_path = add_document(
        library_path,
        effective_title,
        doc_id,
        files=[hwp_file],
    )

    # 2. 텍스트 추출
    # 새 리더 — add_document가 파일을 L1에 복사했으므로,
    # 원본 hwp_file은 여전히 유효하다 (복사지가 아닌 원본 사용)
    if hasattr(reader, "extract_sections"):
        sections = reader.extract_sections()
        section_texts = [s["text"] for s in sections]
    else:
        full_text = reader.extract_text()
        section_texts = [t.strip() for t in re.split(r"\n{2,}", full_text) if t.strip()]

    # part_id — HWP 문서는 단권본이므로 vol1
    part_id = "vol1"

    # manifest의 parts에 page_count 업데이트
    manifest = get_document_info(doc_path)

    # 3. 각 페이지에 텍스트 저장
    text_pages = []
    total_punct_count = 0
    total_hyeonto_count = 0
    had_punctuation = False
    had_hyeonto = False

    for i, raw_text in enumerate(section_texts):
        page_num = i + 1

        # 표점·현토 분리
        result = clean_hwp_text(
            raw_text,
            strip_punct=strip_punctuation,
            strip_hyeonto=strip_hyeonto,
        )

        # L4 텍스트 저장
        save_page_text(doc_path, part_id, page_num, result.clean_text)

        # 서식 메타데이터(대두) 저장
        if result.taidu_marks:
            fmt_path = _formatting_file_path(doc_path, part_id, page_num)
            fmt_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json(fmt_path, {
                "taidu": [
                    {"pos": t["pos"], "raise_chars": t["raise_chars"], "note": t["note"]}
                    for t in result.taidu_marks
                ],
            })

        # 표점·현토 데이터 사이드카 저장
        if result.punctuation_marks or result.hyeonto_annotations:
            clean_path = _hwp_clean_file_path(doc_path, part_id, page_num)
            clean_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json(clean_path, {
                "source": "hwp_import",
                "raw_text_length": len(raw_text),
                "clean_text_length": len(result.clean_text),
                "punctuation_marks": result.punctuation_marks,
                "hyeonto_annotations": result.hyeonto_annotations,
            })

        # 통계
        if result.had_punctuation:
            had_punctuation = True
        if result.had_hyeonto:
            had_hyeonto = True
        total_punct_count += len(result.punctuation_marks)
        total_hyeonto_count += len(result.hyeonto_annotations)

        text_pages.append({
            "page_num": page_num,
            "text_length": len(result.clean_text),
            "has_punct": result.had_punctuation,
            "has_hyeonto": result.had_hyeonto,
        })

    # 4. 이미지 추출 (HWPX만 지원)
    images_extracted = 0
    if hasattr(reader, "extract_images"):
        images_dest = doc_path / "L1_source"
        images = reader.extract_images(images_dest)
        images_extracted = len(images)

    # 5. manifest 업데이트
    for part in manifest.get("parts", []):
        if part["part_id"] == part_id:
            part["page_count"] = len(section_texts)
    manifest["completeness_status"] = "text_imported"
    _write_json(doc_path / "manifest.json", manifest)

    # 6. 서지정보 저장
    bib = {"title": effective_title}
    if metadata.get("author"):
        bib["creator"] = {"name": metadata["author"]}
    save_bibliography(doc_path, bib)

    # 7. git commit
    repo = git.Repo(doc_path)
    repo.index.add(["."])
    try:
        repo.index.commit(f"feat: HWP에서 문헌 생성 — {effective_title}")
    except git.HookExecutionError:
        pass  # hook 에러는 무시 (커밋 자체는 완료)

    return {
        "doc_path": str(doc_path),
        "document_id": doc_id,
        "title": effective_title,
        "mode": "create_from_hwp",
        "pages_saved": len(text_pages),
        "text_pages": text_pages,
        "cleaned_stats": {
            "had_punctuation": had_punctuation,
            "had_hyeonto": had_hyeonto,
            "punct_count": total_punct_count,
            "hyeonto_count": total_hyeonto_count,
        },
        "images_extracted": images_extracted,
    }


# --- URL에서 문헌 자동 생성 ---


async def create_document_from_url(
    library_path: str | Path,
    url: str,
    doc_id: str,
    title: str | None = None,
    selected_assets: list[str] | None = None,
    progress_callback=None,
) -> dict:
    """URL에서 서지정보와 이미지를 자동으로 가져와 문헌을 생성한다.

    목적: URL 하나로 서지정보 추출 + 이미지 다운로드 + 문서 폴더 생성을 한번에 수행.
    입력:
        library_path — 서고 경로.
        url — 외부 아카이브 URL.
        doc_id — 문헌 ID (영문 소문자+숫자+밑줄).
        title — 문헌 제목 (None이면 서지정보에서 추출).
        selected_assets — 다운로드할 에셋 ID 목록 (None이면 전체).
        progress_callback — (status_msg, current, total)를 받는 콜백. (선택)
    출력:
        {
            "doc_path": str,
            "document_id": str,
            "title": str,
            "bibliography": dict,
            "parts": list,
            "parser_id": str,
            "asset_count": int,
        }

    처리 흐름:
        1. URL에서 파서 자동 판별
        2. fetch_by_url()로 메타데이터 추출
        3. map_to_bibliography()로 서지정보 변환
        4. list_assets()로 다운로드 가능 에셋 조회
        5. download_asset()로 각 에셋 다운로드 (임시 디렉토리)
        6. add_document(files=[...])로 문헌 생성
        7. save_bibliography()로 서지정보 저장
        8. git commit

    왜 이렇게 하는가:
        기존 워크플로우는 '이미지 먼저 준비 → 문서 생성 → 서지 추가'인데,
        국립공문서관처럼 URL에서 이미지와 서지를 모두 제공하는 경우
        한 번에 처리하는 것이 연구자에게 훨씬 편리하다.
    """
    import tempfile

    from parsers.base import detect_parser_from_url, get_parser

    library_path = Path(library_path).resolve()

    # 1. 파서 판별
    parser_id = detect_parser_from_url(url)
    if parser_id is None:
        raise ValueError(f"이 URL은 자동 인식할 수 없습니다: {url}")

    import parsers as _parsers_mod  # noqa: F401 — 파서 모듈 자동 등록
    fetcher, mapper = get_parser(parser_id)

    # 2. 메타데이터 추출
    if progress_callback:
        progress_callback("서지정보 가져오는 중...", 0, 0)
    raw_data = await fetcher.fetch_by_url(url)

    # 3. 서지정보 매핑
    bibliography = mapper.map_to_bibliography(raw_data)
    effective_title = title or bibliography.get("title") or "제목없음"

    # 4. 에셋 다운로드
    # - 전용 에셋 다운로더가 있는 파서 → list_assets() + download_asset()
    # - 없는 파서지만 selected_assets가 있음 → 폴백 감지 + 범용 다운로더
    downloaded_files: list[Path] = []
    asset_parts_info: list[dict] = []

    if fetcher.supports_asset_download:
        if progress_callback:
            progress_callback("에셋 목록 조회 중...", 0, 0)
        assets = await fetcher.list_assets(raw_data)

        # 선택된 에셋만 필터 (None이면 전체)
        if selected_assets is not None:
            assets = [a for a in assets if a["asset_id"] in selected_assets]

        if assets:
            with tempfile.TemporaryDirectory(prefix="ctp_download_") as tmp_dir:
                tmp_path = Path(tmp_dir)
                for i, asset in enumerate(assets):
                    if progress_callback:
                        progress_callback(
                            f"다운로드 중: {asset['label']} ({i + 1}/{len(assets)})",
                            i + 1,
                            len(assets),
                        )

                    pdf_path = await fetcher.download_asset(
                        asset,
                        tmp_path,
                        progress_callback=(
                            lambda cur, total, _label=asset["label"]: (
                                progress_callback(
                                    f"다운로드 중: {_label} p.{cur}/{total}",
                                    cur,
                                    total,
                                )
                            )
                            if progress_callback
                            else None
                        ),
                    )
                    downloaded_files.append(pdf_path)
                    asset_parts_info.append({
                        "label": asset["label"],
                        "page_count": asset.get("page_count"),
                    })

                # 5. add_document() 호출
                if progress_callback:
                    progress_callback("문헌 폴더 생성 중...", 0, 0)
                doc_path = add_document(
                    library_path,
                    effective_title,
                    doc_id,
                    files=downloaded_files,
                )
            # TemporaryDirectory가 여기서 자동 정리됨
        else:
            doc_path = add_document(library_path, effective_title, doc_id)
    elif selected_assets:
        # 폴백: 전용 다운로더가 없지만 preview에서 에셋이 감지된 경우
        # (NDL/KORCIS 등에서 URL 자체가 PDF일 때)
        from parsers.asset_detector import detect_direct_download, download_generic_asset

        if progress_callback:
            progress_callback("에셋 감지 중...", 0, 0)
        direct = await detect_direct_download(url)

        if direct and direct["asset_id"] in selected_assets:
            with tempfile.TemporaryDirectory(prefix="ctp_download_") as tmp_dir:
                tmp_path = Path(tmp_dir)
                if progress_callback:
                    progress_callback(
                        f"다운로드 중: {direct['label']}", 1, 1,
                    )
                pdf_path = await download_generic_asset(
                    direct, tmp_path,
                    progress_callback=(
                        lambda cur, total: progress_callback(
                            f"다운로드 중: {direct['label']}", cur, total,
                        )
                    ) if progress_callback else None,
                )
                downloaded_files.append(pdf_path)
                asset_parts_info.append({
                    "label": direct["label"],
                    "page_count": direct.get("page_count"),
                })

                if progress_callback:
                    progress_callback("문헌 폴더 생성 중...", 0, 0)
                doc_path = add_document(
                    library_path,
                    effective_title,
                    doc_id,
                    files=downloaded_files,
                )
        else:
            doc_path = add_document(library_path, effective_title, doc_id)
    else:
        doc_path = add_document(library_path, effective_title, doc_id)

    # 6. manifest.json의 parts에 페이지 수와 라벨 업데이트
    manifest = get_document_info(doc_path)
    for i, part in enumerate(manifest.get("parts", [])):
        if i < len(asset_parts_info):
            part["page_count"] = asset_parts_info[i].get("page_count")
            part["label"] = asset_parts_info[i]["label"]
    if bibliography:
        manifest["completeness_status"] = "bibliography_added"
    _write_json(doc_path / "manifest.json", manifest)

    # 7. 서지정보 저장
    save_bibliography(doc_path, bibliography)

    # 8. git commit
    repo = git.Repo(doc_path)
    repo.index.add(["."])
    repo.index.commit(f"feat: URL에서 문헌 생성 ({parser_id})")

    return {
        "doc_path": str(doc_path),
        "document_id": doc_id,
        "title": effective_title,
        "bibliography": bibliography,
        "parts": manifest.get("parts", []),
        "parser_id": parser_id,
        "asset_count": len(downloaded_files),
    }


# ──────────────────────────────────────────────────────────
# 일괄 교정 (Batch Correction)
# ──────────────────────────────────────────────────────────


def search_char_in_pages(
    doc_path: str | Path,
    part_id: str,
    page_start: int,
    page_end: int,
    target_char: str,
) -> list[dict]:
    """여러 페이지에서 특정 글자를 검색한다.

    목적: 일괄 교정의 미리보기 단계. 교정 대상 글자가 어느 페이지의
          어느 위치에 있는지 찾아서, 이미 교정된 위치는 제외한다.
    입력:
        doc_path — 문헌 디렉토리 경로.
        part_id — 권 식별자.
        page_start — 검색 시작 페이지 (1부터).
        page_end — 검색 끝 페이지 (포함).
        target_char — 찾을 글자 (1글자).
    출력:
        페이지별 검색 결과 리스트:
        [
            {
                "page": int,
                "count": int,
                "positions": [
                    {"char_index": int, "context": str},
                    ...
                ]
            },
            ...
        ]
    왜 이렇게 하는가:
        일괄 교정 전 사용자가 매칭 결과를 미리 확인할 수 있도록 한다.
        이미 교정된 위치를 제외해야 같은 글자를 중복 교정하지 않는다.
    """
    doc_path = Path(doc_path).resolve()
    results = []

    for page_num in range(page_start, page_end + 1):
        # 원본 텍스트 로드
        text_result = get_page_text(doc_path, part_id, page_num)
        text = text_result.get("text", "")
        if not text:
            continue

        # 기존 교정 로드 — 이미 교정된 위치를 제외하기 위해
        corr_result = get_page_corrections(doc_path, part_id, page_num)
        corrections = corr_result.get("corrections", [])

        # 이미 교정된 char_index 집합 (line=null인 평면 인덱스)
        corrected_indices = set()
        for c in corrections:
            ci = c.get("char_index")
            if ci is not None and c.get("line") is None:
                corrected_indices.add(ci)

        # 텍스트에서 target_char 검색
        positions = []
        for i, ch in enumerate(text):
            if ch == target_char and i not in corrected_indices:
                # 컨텍스트: 앞뒤 5글자
                ctx_start = max(0, i - 5)
                ctx_end = min(len(text), i + 6)
                context = text[ctx_start:ctx_end]
                positions.append({
                    "char_index": i,
                    "context": context,
                })

        if positions:
            results.append({
                "page": page_num,
                "count": len(positions),
                "positions": positions,
            })

    return results


def apply_batch_corrections(
    doc_path: str | Path,
    part_id: str,
    page_start: int,
    page_end: int,
    original_char: str,
    corrected_char: str,
    correction_type: str = "ocr_error",
    note: str | None = None,
) -> dict:
    """여러 페이지에 걸쳐 같은 글자를 일괄 교정한다.

    목적: 같은 OCR 오류가 여러 페이지에서 반복될 때, 한 번에 모두 교정한다.
    입력:
        doc_path — 문헌 디렉토리 경로.
        part_id — 권 식별자.
        page_start — 교정 시작 페이지.
        page_end — 교정 끝 페이지 (포함).
        original_char — 교정 전 글자.
        corrected_char — 교정 후 글자.
        correction_type — 교정 유형 (기본: 'ocr_error').
        note — 교정 비고.
    출력:
        {
            "total_corrected": int,
            "pages_affected": int,
            "details": [
                {"page": int, "corrected": int},
                ...
            ]
        }
    왜 이렇게 하는가:
        페이지마다 corrections.json에 교정 항목을 추가한다.
        corrected_by를 'human_batch'로 표시하여 일괄 교정임을 구분한다.
    """
    doc_path = Path(doc_path).resolve()
    total = 0
    details = []

    for page_num in range(page_start, page_end + 1):
        # 원본 텍스트 로드
        text_result = get_page_text(doc_path, part_id, page_num)
        text = text_result.get("text", "")
        if not text:
            continue

        # 기존 교정 로드
        corr_result = get_page_corrections(doc_path, part_id, page_num)
        corrections = corr_result.get("corrections", [])

        # 이미 교정된 위치 집합
        corrected_indices = set()
        for c in corrections:
            ci = c.get("char_index")
            if ci is not None and c.get("line") is None:
                corrected_indices.add(ci)

        # 텍스트에서 original_char 검색 → 새 교정 항목 생성
        new_corrs = []
        for i, ch in enumerate(text):
            if ch == original_char and i not in corrected_indices:
                entry = {
                    "page": page_num,
                    "block_id": None,
                    "line": None,
                    "char_index": i,
                    "type": correction_type,
                    "original_ocr": original_char,
                    "corrected": corrected_char,
                    "corrected_by": "human_batch",
                    "confidence": None,
                    "note": note,
                }
                new_corrs.append(entry)

        if not new_corrs:
            continue

        # 기존 교정에 추가하여 저장
        corrections.extend(new_corrs)
        save_data = {
            "part_id": part_id,
            "corrections": corrections,
        }
        save_page_corrections(doc_path, part_id, page_num, save_data)

        total += len(new_corrs)
        details.append({"page": page_num, "corrected": len(new_corrs)})

    return {
        "total_corrected": total,
        "pages_affected": len(details),
        "details": details,
    }
