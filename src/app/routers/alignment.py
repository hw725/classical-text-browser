"""정렬 엔진 라우터 (Phase 10-3).

OCR 결과(L2)와 확정 텍스트(L4) 대조, 이체자 사전 관리(다중 사전),
일괄 교정(Batch Correction) API를 모아둔다.

왜 분리하는가:
    server.py가 너무 길어져 유지보수가 어렵다.
    정렬/이체자/일괄교정 기능은 독립적이므로 별도 라우터로 분리한다.
"""

import os
import re
import shutil
import subprocess

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.responses import Response

from app._state import get_library_path, require_repo_path

router = APIRouter(tags=["alignment"])


# ===========================================================================
#  이체자 사전 관리 (다중 사전 지원)
# ===========================================================================
# resources/ 폴더에 여러 사전 파일이 공존할 수 있다.
# 활성 사전 이름은 resources/.active_variant_dict 에 기록.
_variant_dict = None
_variant_dict_name: str | None = None  # 현재 로드된 사전 파일명


def _app_resources_dir() -> str:
    """앱이 들고 다니는 기본 자료 폴더 (읽기 전용으로 쓴다).

    이 파일은 src/app/routers/alignment.py이므로 routers/ → app/ → src/ → 프로젝트루트.
    """
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "resources"))


def _get_resources_dir() -> str:
    """이체자 사전이 사는 자리 — **서고의 resources/** (D-104).

    왜 앱 폴더가 아닌가:
        사전은 사람이 작업하며 늘려 가는 **작업물**이다. 앱 폴더에 쓰면 두 가지가 깨진다 —
        ① 앱을 새 판으로 갈 때(`git pull`) 그 수정이 충돌하거나 사라진다. 실제로 새로 넣은
           앱 업데이트(D-103)가 「작업 트리가 더러워 받지 않습니다」로 막힌다. 이체자를 하나만
           넣어도 그렇게 된다(실측 2026-09-05).
        ② 서고마다 다른 사전을 쓸 수 없다.

    처음 쓰는 서고에는 앱 기본 사전을 **한 번 복사해 넣는다.** 그 뒤로는 서고의 것만 고친다.
    서고가 아직 없으면(설정 전) 앱 폴더를 그대로 쓴다 — 읽기만 하는 상황이다.
    """
    import shutil

    lib = get_library_path()
    if lib is None:
        return _app_resources_dir()
    target = os.path.join(str(lib), "resources")
    os.makedirs(target, exist_ok=True)
    seed = os.path.join(target, "variant_chars.json")
    if not os.path.exists(seed):
        src = os.path.join(_app_resources_dir(), "variant_chars.json")
        if os.path.exists(src):
            shutil.copy2(src, seed)
    return target


def _get_active_dict_name() -> str:
    """활성 이체자 사전 파일명을 반환한다.

    resources/.active_variant_dict 파일에 기록된 이름을 읽는다.
    파일이 없으면 기본값 'variant_chars'를 반환한다.
    """
    marker = os.path.join(_get_resources_dir(), ".active_variant_dict")
    if os.path.exists(marker):
        with open(marker, "r", encoding="utf-8") as f:
            name = f.read().strip()
            if name:
                return name
    return "variant_chars"


def _set_active_dict_name(name: str) -> None:
    """활성 이체자 사전 이름을 저장한다."""
    marker = os.path.join(_get_resources_dir(), ".active_variant_dict")
    with open(marker, "w", encoding="utf-8") as f:
        f.write(name)


def _dict_name_to_path(name: str) -> str:
    """사전 이름을 파일 경로로 변환한다. 예: 'variant_chars' → '.../resources/variant_chars.json'"""
    return os.path.join(_get_resources_dir(), f"{name}.json")


def _get_variant_dict(name: str | None = None):
    """이체자 사전을 로드한다.

    name이 None이면 활성 사전을 로드한다.
    이미 같은 이름이 로드되어 있으면 캐시를 반환한다.
    """
    global _variant_dict, _variant_dict_name
    from core.alignment import VariantCharDict

    if name is None:
        name = _get_active_dict_name()

    # 캐시 열쇠는 **경로**다. 이름만으로 잡으면 서고를 바꿔도 앞 서고의 사전이 돌아온다
    # (사전이 서고 안에 살게 된 뒤로는 이름이 같아도 다른 파일이다 — D-104).
    path = _dict_name_to_path(name)
    if _variant_dict is not None and _variant_dict_name == path:
        return _variant_dict

    _variant_dict = VariantCharDict(dict_path=path)
    _variant_dict_name = path
    return _variant_dict


def _save_variant_dict(vd, name: str | None = None) -> str:
    """이체자 사전을 파일로 저장하고 경로를 반환한다."""
    if name is None:
        name = _get_active_dict_name()
    path = _dict_name_to_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    vd.save(path)
    global _variant_dict, _variant_dict_name
    _variant_dict, _variant_dict_name = vd, path
    return path


def _list_variant_dicts() -> list[dict]:
    """resources/ 폴더의 이체자 사전 파일 목록을 반환한다.

    variant_chars*.json 패턴에 맞는 파일만 포함한다.
    반환: [{"name": "variant_chars", "path": "...", "active": True}, ...]
    """
    import glob as glob_mod

    resources = _get_resources_dir()
    active = _get_active_dict_name()
    result = []
    # variant_ 로 시작하는 JSON 파일 탐색
    for path in sorted(glob_mod.glob(os.path.join(resources, "variant_*.json"))):
        basename = os.path.basename(path)
        name = basename.rsplit(".json", 1)[0]
        result.append(
            {
                "name": name,
                "file": basename,
                "active": name == active,
                # 층(D-080). 파일 머리의 _tier. 없으면 strict — 예전 파일 그대로.
                "tier": _read_dict_tier(path),
            }
        )
    return result


# 비활성 사전 캐시: {이름: (mtime, VariantCharDict)}. 정렬 요청마다 OpenCC 4천 쌍
# 사전을 다시 읽지 않기 위해서다. 파일이 바뀌면(mtime) 다시 읽는다.
_dict_cache: dict[str, tuple[float, object]] = {}


def _load_dict_cached(name: str):
    """이름의 사전을 (mtime 기준) 캐시해서 돌려준다. 파일이 없으면 None."""
    from core.alignment import VariantCharDict

    path = _dict_name_to_path(name)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    hit = _dict_cache.get(name)
    if hit and hit[0] == mtime:
        return hit[1]
    vd = VariantCharDict(dict_path=path)
    _dict_cache[name] = (mtime, vd)
    return vd


def _read_dict_tier(path: str) -> str:
    """사전 파일의 `_tier`. 캐시된 사전 객체에서 읽는다 — 파일을 두 번 파싱하지 않는다."""
    name = os.path.basename(path).rsplit(".json", 1)[0]
    vd = _load_dict_cached(name)
    return vd.tier if vd is not None else "strict"


def _get_tiered_dicts(doc_path=None):
    """정렬에 쓸 사전 묶음을 만든다 (D-080).

    구성:
      1. 활성 사전 — 파일의 _tier 그대로(예전 파일은 strict)
      2. 문헌별 승인 사전 — strict (doc_path가 있을 때)
      3. resources/의 나머지 사전 중 _tier가 loose·script인 것 — 힌트만

    strict 층은 1·2에서만 나온다. 넓은 사전이 우연히 활성이 아니어도 힌트는
    보이고, 활성이어도 그 파일의 층이 loose면 동치가 되지 않는다.
    """
    from core.alignment import TieredVariantDicts, load_document_approvals

    bundle = TieredVariantDicts()
    active_name = _get_active_dict_name()
    bundle.add(_get_variant_dict(active_name))
    if doc_path is not None:
        bundle.add(load_document_approvals(doc_path))
    for entry in _list_variant_dicts():
        if entry["name"] == active_name or entry["tier"] == "strict":
            continue
        bundle.add(_load_dict_cached(entry["name"]))
    return bundle


# ── Pydantic 모델 ─────────────────────────────────


class VariantPairRequest(BaseModel):
    """이체자 쌍 추가/삭제 요청."""

    char_a: str
    char_b: str


class VariantImportRequest(BaseModel):
    """이체자 대량 가져오기 요청."""

    text: str
    format: str = "auto"


class CreateDictRequest(BaseModel):
    """새 사전 생성 요청."""

    name: str


class CopyDictRequest(BaseModel):
    """사전 복제 요청."""

    new_name: str


class BatchCorrectionRequest(BaseModel):
    """일괄 교정 요청."""

    part_id: str
    page_start: int
    page_end: int
    original_char: str
    corrected_char: str
    correction_type: str = "ocr_error"
    note: str | None = None


# ===========================================================================
#  Phase 10-3: 정렬 엔진 — OCR ↔ 텍스트 대조 API
# ===========================================================================


@router.post("/api/documents/{doc_id}/parts/{part_id}/pages/{page_number}/alignment")
async def api_run_alignment(
    doc_id: str,
    part_id: str,
    page_number: int,
):
    """페이지의 OCR 결과(L2)와 확정 텍스트(L4)를 글자 단위로 대조한다.

    목적: 교정 모드에서 OCR 인식 결과와 사람이 확정한 텍스트의 차이를 시각적으로 보여준다.
    입력:
        doc_id — 문헌 ID.
        part_id — 권 식별자.
        page_number — 페이지 번호 (1-indexed).
    전제 조건:
        L2(OCR 결과)와 L4(확정 텍스트)가 모두 있어야 한다.
    출력: {
        "blocks": [BlockAlignment.to_dict(), ...],  # 블록별 대조 결과
        "page_stats": AlignmentStats.to_dict()       # 페이지 전체 통계 (* 블록)
    }
    """
    _library_path = get_library_path()
    if _library_path is None:
        return JSONResponse({"error": "서고가 설정되지 않았습니다."}, status_code=500)

    doc_path = require_repo_path("documents", doc_id)
    if not doc_path.exists():
        return JSONResponse(
            {"error": f"문헌을 찾을 수 없습니다: {doc_id}"},
            status_code=404,
        )

    from core.alignment import align_page

    # 활성 사전 + 이 문헌의 승인 쌍 + 힌트용 넓은 사전 (D-080)
    variant_dict = _get_tiered_dicts(doc_path)

    try:
        block_results = align_page(
            library_root=str(_library_path),
            doc_id=doc_id,
            part_id=part_id,
            page_number=page_number,
            variant_dict=variant_dict,
        )
    except Exception as e:
        return JSONResponse(
            {"error": f"대조 실행 실패: {e}"},
            status_code=500,
        )

    # 에러만 있는 경우
    if len(block_results) == 1 and block_results[0].error:
        return JSONResponse(
            {"error": block_results[0].error},
            status_code=404,
        )

    # 페이지 전체 통계 (* 블록)
    page_stats = None
    blocks_output = []
    for br in block_results:
        blocks_output.append(br.to_dict())
        if br.layout_block_id == "*" and br.stats:
            page_stats = br.stats.to_dict()

    return {
        "blocks": blocks_output,
        "page_stats": page_stats,
    }


# ── 기존 호환 API (활성 사전에 프록시) ──


@router.get("/api/alignment/variant-dict")
async def api_get_variant_dict():
    """활성 이체자 사전 내용을 반환한다. (기존 API 호환)"""
    variant_dict = _get_variant_dict()
    return {
        "variants": variant_dict.to_dict(),
        "size": variant_dict.size,
        "pair_count": variant_dict.pair_count,
        "active_name": _get_active_dict_name(),
    }


@router.post("/api/alignment/variant-dict")
async def api_add_variant_pair(body: VariantPairRequest):
    """활성 사전에 이체자 쌍을 추가한다. (기존 API 호환)"""
    variant_dict = _get_variant_dict()

    if not body.char_a or not body.char_b:
        return JSONResponse({"error": "두 글자 모두 입력해야 합니다."}, status_code=400)
    if body.char_a == body.char_b:
        return JSONResponse({"error": "같은 글자는 이체자로 등록할 수 없습니다."}, status_code=400)

    variant_dict.add_pair(body.char_a, body.char_b)
    _save_variant_dict(variant_dict)
    return {"status": "ok", "size": variant_dict.size}


@router.delete("/api/alignment/variant-dict")
async def api_delete_variant_pair(body: VariantPairRequest):
    """활성 사전에서 이체자 쌍을 삭제한다."""
    variant_dict = _get_variant_dict()

    if not body.char_a or not body.char_b:
        return JSONResponse({"error": "두 글자 모두 입력해야 합니다."}, status_code=400)

    removed = variant_dict.remove_pair(body.char_a, body.char_b)
    if not removed:
        return JSONResponse({"error": "해당 이체자 쌍이 존재하지 않습니다."}, status_code=404)

    _save_variant_dict(variant_dict)
    return {"status": "ok", "removed": True, "size": variant_dict.size}


@router.post("/api/alignment/variant-dict/import")
async def api_import_variant_dict(body: VariantImportRequest):
    """활성 사전에 이체자 데이터를 대량 가져온다. (기존 API 호환)"""
    if not body.text or not body.text.strip():
        return JSONResponse({"error": "가져올 데이터가 비어 있습니다."}, status_code=400)

    variant_dict = _get_variant_dict()
    result = variant_dict.import_bulk(body.text, body.format)

    if result["added"] > 0:
        _save_variant_dict(variant_dict)

    return {
        "status": "ok",
        "added": result["added"],
        "skipped": result["skipped"],
        "errors": result["errors"],
        "size": variant_dict.size,
    }


# ── 다중 사전 관리 API ──


@router.get("/api/variant-dicts")
async def api_list_variant_dicts():
    """resources/ 폴더의 이체자 사전 목록을 반환한다.

    출력: { "dicts": [{"name": "variant_chars", "file": "variant_chars.json", "active": true}] }
    """
    return {"dicts": _list_variant_dicts()}


@router.get("/api/variant-dicts/{name}")
async def api_get_variant_dict_by_name(name: str):
    """특정 이름의 이체자 사전 내용을 반환한다."""
    path = _dict_name_to_path(name)
    if not os.path.exists(path):
        return JSONResponse({"error": f"사전을 찾을 수 없습니다: {name}"}, status_code=404)

    vd = _get_variant_dict(name)
    return {
        "name": name,
        "variants": vd.to_dict(),
        "size": vd.size,
        "pair_count": vd.pair_count,
        "active": name == _get_active_dict_name(),
    }


@router.post("/api/variant-dicts")
async def api_create_variant_dict(body: CreateDictRequest):
    """빈 이체자 사전을 새로 생성한다.

    이름은 자동으로 'variant_' 접두사가 붙는다.
    예: 'kangxi' → 'variant_kangxi'
    """
    # variant_ 접두사 자동 추가
    raw_name = body.name.strip()
    if not raw_name.startswith("variant_"):
        raw_name = f"variant_{raw_name}"

    if not re.match(r"^variant_[a-zA-Z0-9_\-]+$", raw_name):
        return JSONResponse(
            {"error": "사전 이름은 영문, 숫자, 밑줄, 하이픈만 사용할 수 있습니다."},
            status_code=400,
        )

    path = _dict_name_to_path(raw_name)
    if os.path.exists(path):
        return JSONResponse({"error": f"이미 존재하는 사전입니다: {raw_name}"}, status_code=409)

    from core.alignment import VariantCharDict

    vd = VariantCharDict(dict_path=None)  # 빈 사전
    vd.save(path)
    return {"status": "ok", "name": raw_name}


@router.post("/api/variant-dicts/{name}/copy")
async def api_copy_variant_dict(name: str, body: CopyDictRequest):
    """기존 사전을 새 이름으로 복제한다."""
    new_name = body.new_name.strip()
    if not new_name.startswith("variant_"):
        new_name = f"variant_{new_name}"

    if not re.match(r"^variant_[a-zA-Z0-9_\-]+$", new_name):
        return JSONResponse(
            {"error": "사전 이름은 영문, 숫자, 밑줄, 하이픈만 사용할 수 있습니다."},
            status_code=400,
        )

    src_path = _dict_name_to_path(name)
    if not os.path.exists(src_path):
        return JSONResponse({"error": f"원본 사전을 찾을 수 없습니다: {name}"}, status_code=404)

    dst_path = _dict_name_to_path(new_name)
    if os.path.exists(dst_path):
        return JSONResponse({"error": f"이미 존재하는 사전입니다: {new_name}"}, status_code=409)

    shutil.copy2(src_path, dst_path)
    return {"status": "ok", "name": new_name}


@router.delete("/api/variant-dicts/{name}")
async def api_delete_variant_dict(name: str):
    """사전 파일을 삭제한다 (휴지통으로 이동).

    활성 사전은 삭제할 수 없다.
    """
    active = _get_active_dict_name()
    if name == active:
        return JSONResponse(
            {"error": "활성 사전은 삭제할 수 없습니다. 먼저 다른 사전을 활성화하세요."},
            status_code=400,
        )

    path = _dict_name_to_path(name)
    if not os.path.exists(path):
        return JSONResponse({"error": f"사전을 찾을 수 없습니다: {name}"}, status_code=404)

    # 휴지통으로 이동 (CLAUDE.md: 영구 삭제 금지)
    try:
        subprocess.run(
            [
                "powershell",
                "-Command",
                f"Add-Type -AssemblyName Microsoft.VisualBasic; "
                f"[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
                f"'{path}', 'OnlyErrorDialogs', 'SendToRecycleBin')",
            ],
            check=True,
            capture_output=True,
        )
    except Exception:
        # PowerShell 실패 시 (Linux 등) — 이름 변경으로 "삭제"
        trash_path = path + ".deleted"
        os.rename(path, trash_path)

    return {"status": "ok", "deleted": name}


@router.put("/api/variant-dicts/{name}/activate")
async def api_activate_variant_dict(name: str):
    """지정한 사전을 활성 사전으로 설정한다."""
    path = _dict_name_to_path(name)
    if not os.path.exists(path):
        return JSONResponse({"error": f"사전을 찾을 수 없습니다: {name}"}, status_code=404)

    _set_active_dict_name(name)

    # 캐시 무효화 → 다음 _get_variant_dict() 호출 시 새 사전 로드
    global _variant_dict, _variant_dict_name
    _variant_dict = None
    _variant_dict_name = None

    return {"status": "ok", "active": name}


@router.post("/api/variant-dicts/{name}/pair")
async def api_add_pair_to_dict(name: str, body: VariantPairRequest):
    """지정한 사전에 이체자 쌍을 추가한다."""
    path = _dict_name_to_path(name)
    if not os.path.exists(path):
        return JSONResponse({"error": f"사전을 찾을 수 없습니다: {name}"}, status_code=404)
    if not body.char_a or not body.char_b:
        return JSONResponse({"error": "두 글자 모두 입력해야 합니다."}, status_code=400)
    if body.char_a == body.char_b:
        return JSONResponse({"error": "같은 글자는 이체자로 등록할 수 없습니다."}, status_code=400)

    vd = _get_variant_dict(name)
    vd.add_pair(body.char_a, body.char_b)
    _save_variant_dict(vd, name)
    return {"status": "ok", "size": vd.size}


@router.delete("/api/variant-dicts/{name}/pair")
async def api_delete_pair_from_dict(name: str, body: VariantPairRequest):
    """지정한 사전에서 이체자 쌍을 삭제한다."""
    path = _dict_name_to_path(name)
    if not os.path.exists(path):
        return JSONResponse({"error": f"사전을 찾을 수 없습니다: {name}"}, status_code=404)

    vd = _get_variant_dict(name)
    removed = vd.remove_pair(body.char_a, body.char_b)
    if not removed:
        return JSONResponse({"error": "해당 이체자 쌍이 존재하지 않습니다."}, status_code=404)

    _save_variant_dict(vd, name)
    return {"status": "ok", "removed": True, "size": vd.size}


# ── 문헌별 이체자 승인 (D-080 결정 3) ──
#
# 넓은 사전(loose)·문자 체계 사전(script)에만 있는 쌍을 사람이 «이 문헌에서는 같은
# 글자»로 승인하면 그 문헌 안에서만 strict로 승격된다. 전역 사전으로 올라가지 않는다.
# A 문헌의 승인이 B 문헌의 판정을 바꾸면 안 되기 때문이다.


@router.get("/api/documents/{doc_id}/variant-approvals")
async def api_list_variant_approvals(doc_id: str):
    """이 문헌에서 승인된 이체자 쌍 목록."""
    from core.alignment import load_document_approvals

    doc_path = require_repo_path("documents", doc_id)
    if not doc_path.exists():
        return JSONResponse({"error": f"문헌을 찾을 수 없습니다: {doc_id}"}, status_code=404)
    vd = load_document_approvals(doc_path)
    return {"doc_id": doc_id, "pair_count": vd.pair_count, "variants": vd.to_dict()}


@router.post("/api/documents/{doc_id}/variant-approvals")
async def api_approve_variant_pair(doc_id: str, body: VariantPairRequest):
    """이 문헌에서 두 글자를 같은 글자로 승인한다 (문헌 안에서만 strict)."""
    from core.alignment import load_document_approvals, save_document_approvals

    doc_path = require_repo_path("documents", doc_id)
    if not doc_path.exists():
        return JSONResponse({"error": f"문헌을 찾을 수 없습니다: {doc_id}"}, status_code=404)
    if not body.char_a or not body.char_b:
        return JSONResponse({"error": "두 글자 모두 입력해야 합니다."}, status_code=400)
    if body.char_a == body.char_b:
        return JSONResponse({"error": "같은 글자는 승인할 필요가 없습니다."}, status_code=400)

    vd = load_document_approvals(doc_path)
    vd.add_pair(body.char_a, body.char_b)
    save_document_approvals(doc_path, vd)
    return {"status": "ok", "doc_id": doc_id, "pair_count": vd.pair_count}


@router.delete("/api/documents/{doc_id}/variant-approvals")
async def api_revoke_variant_pair(doc_id: str, body: VariantPairRequest):
    """이 문헌의 승인 쌍 하나를 철회한다."""
    from core.alignment import load_document_approvals, save_document_approvals

    doc_path = require_repo_path("documents", doc_id)
    if not doc_path.exists():
        return JSONResponse({"error": f"문헌을 찾을 수 없습니다: {doc_id}"}, status_code=404)

    vd = load_document_approvals(doc_path)
    if not vd.remove_pair(body.char_a, body.char_b):
        return JSONResponse({"error": "승인된 쌍이 아닙니다."}, status_code=404)
    save_document_approvals(doc_path, vd)
    return {"status": "ok", "removed": True, "pair_count": vd.pair_count}


@router.post("/api/variant-dicts/{name}/import")
async def api_import_to_dict(name: str, body: VariantImportRequest):
    """지정한 사전에 이체자 데이터를 대량 가져온다."""
    path = _dict_name_to_path(name)
    if not os.path.exists(path):
        return JSONResponse({"error": f"사전을 찾을 수 없습니다: {name}"}, status_code=404)
    if not body.text or not body.text.strip():
        return JSONResponse({"error": "가져올 데이터가 비어 있습니다."}, status_code=400)

    vd = _get_variant_dict(name)
    result = vd.import_bulk(body.text, body.format)

    if result["added"] > 0:
        _save_variant_dict(vd, name)

    return {
        "status": "ok",
        "added": result["added"],
        "skipped": result["skipped"],
        "errors": result["errors"],
        "size": vd.size,
    }


@router.get("/api/variant-dicts/{name}/export")
async def api_export_variant_dict(name: str, format: str = "json"):
    """이체자 사전을 파일로 내보낸다.

    format: "json" (기본) 또는 "csv"
    """
    path = _dict_name_to_path(name)
    if not os.path.exists(path):
        return JSONResponse({"error": f"사전을 찾을 수 없습니다: {name}"}, status_code=404)

    vd = _get_variant_dict(name)

    if format == "csv":
        csv_text = vd.export_csv()
        return Response(
            content=csv_text,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
        )
    else:
        # JSON: 원본 파일을 그대로 반환
        return FileResponse(
            path=path,
            media_type="application/json; charset=utf-8",
            filename=f"{name}.json",
        )


# ───────────────────────────────────────────────────
# 일괄 교정 (Batch Correction)
# ───────────────────────────────────────────────────


@router.post("/api/documents/{doc_id}/batch-corrections/preview")
async def api_batch_correction_preview(doc_id: str, body: BatchCorrectionRequest):
    """일괄 교정 미리보기 — 대상 글자가 어느 페이지에서 몇 건 매칭되는지 반환한다."""
    _library_path = get_library_path()
    doc_path = require_repo_path("documents", doc_id)

    from core.document import search_char_in_pages

    results = search_char_in_pages(
        doc_path, body.part_id, body.page_start, body.page_end, body.original_char
    )
    total = sum(r["count"] for r in results)
    return {
        "original_char": body.original_char,
        "corrected_char": body.corrected_char,
        "total_matches": total,
        "pages": results,
    }


@router.post("/api/documents/{doc_id}/batch-corrections/execute")
async def api_batch_correction_execute(
    doc_id: str,
    body: BatchCorrectionRequest,
    background_tasks: BackgroundTasks,
):
    """일괄 교정 실행 — 매칭되는 모든 위치에 교정을 적용한다."""
    _library_path = get_library_path()
    doc_path = require_repo_path("documents", doc_id)

    from core.document import apply_batch_corrections, git_commit_document

    result = apply_batch_corrections(
        doc_path,
        body.part_id,
        body.page_start,
        body.page_end,
        body.original_char,
        body.corrected_char,
        body.correction_type,
        body.note,
    )

    # git commit은 백그라운드로 (성능)
    if result["total_corrected"] > 0:
        msg = (
            f"fix: 일괄 교정 '{body.original_char}'→'{body.corrected_char}' "
            f"({result['total_corrected']}건, {result['pages_affected']}페이지)"
        )
        background_tasks.add_task(git_commit_document, doc_path, msg)

    return result
