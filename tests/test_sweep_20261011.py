# ruff: noqa: E501 — 한글 docstring·JS 스텁 줄은 쪼개면 읽기 어렵다
"""2026-10-11 전수 검토가 찾은 결함의 회귀 시험 (backlog B-012~B-077 — 1차 B-012~B-035, 2차·보충 B-037~B-077).

왜 한 파일인가:
    전수 검토(442파일)에서 나온 결함을 《고치기 전에 빨간불》로 먼저 세우고, 고친 뒤 초록이 되는
    것을 한 자리에서 확인하려고 모았다. 시험마다 머리에 backlog 번호를 붙인다 — 그 항목을 닫을
    때 근거가 이 시험이다.

무엇을 재는가(요약):
    - 저장 형식: 스냅샷 왕복이 편성 경계·작업 계획·문헌별 승인·사용자 사전·주석 유형을 잃지 않고
      (B-013), 들인 manifest와 honkoku L2가 스키마를 지키고(B-014·B-015), 줄끝이 LF인가(B-021)
    - 읽는 자리: 원문 내보내기가 교정을 싣는가(B-017), LLM 교정이 서고 사전을 읽는가(B-020),
      주석 사전 내보내기가 문헌 id를 바로 적는가(B-022)
    - 파서: 장서각·KOSTMA·규장각 서지가 스키마를 지키는가(B-033), KORCIS 판식·소장처(B-031),
      이미지 묶음 순서(B-034), 외부 텍스트 쪽 대조(B-032)
    - 화면 JS: 인용 좌표·권(B-016), 번역 일괄 집계·참조 사전(B-018), 권 전체 OCR 모델(B-019),
      시작 행 옮기기(B-025), 사전 활성화(B-026)
    - 2차·보충(B-037~B-077): 스냅샷 경로 안전·엔티티 id, 백업·.env·휴지통 데이터 손실(B-049~B-051),
      zip 업데이트 보호(B-052), 이스케이프 종류 전체(B-041), 편집기 코드포인트(B-042), 늦은 응답이
      다른 쪽에 그려지는 경쟁, 설명이 주인 함수에서 떨어진 자리
    - 릴리스 리뷰(B-078): reset --hard 전 추적 밖 파일 남기기, 옛 zip 백업의 staged·한글 경로,
      늦은 비고 응답, 같은 책 다른 대목 출전
    - 시험 정리(B-079): KORCIS 서지의 목차·해제 칸이 스키마에 있어 저장된다, 서지 매퍼 출력 키 ⊂ 스키마
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import jsonschema
import pytest

from tests.js_harness import STATIC_JS, extract_js, run_js

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "schemas"


def _schema(rel: str) -> dict:
    return json.loads((SCHEMAS / rel).read_text(encoding="utf-8"))


# ── 공용 픽스처: 서고 + 문헌(PDF 3쪽) + L4 + 해석 저장소 ─────────────────────────────


@pytest.fixture()
def client(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    from fastapi.testclient import TestClient

    from app.server import app

    with TestClient(app) as c:
        yield c


def _setup(client, tmp_path) -> tuple[Path, str]:
    """서고 + 문헌 d1(PDF 3쪽) + L4 세 쪽 + 해석 저장소 i1. 출력: (서고 경로, 권 id)."""
    import fitz

    r = client.post("/api/library/quick-start")
    assert r.status_code == 200, r.text
    lib = Path(r.json()["library_path"])
    pdf = tmp_path / "t.pdf"
    d = fitz.open()
    for _ in range(3):
        d.new_page(width=400, height=600)
    d.save(str(pdf))
    d.close()
    with open(pdf, "rb") as f:
        r = client.post(
            "/api/documents/create-from-files",
            data={"doc_id": "d1", "title": "담초"},
            files=[("files", ("t.pdf", f.read(), "application/pdf"))],
        )
    assert r.status_code == 200, r.text
    part_id = r.json()["parts"][0]["part_id"]
    pages = lib / "documents" / "d1" / "L4_text" / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    for n, text in (
        (1, "天地玄黃\n宇宙洪荒"),
        (2, "日月盈昃\n辰宿列張"),
        (3, "寒來暑往\n秋收冬藏"),
    ):
        (pages / f"{part_id}_page_{n:03d}.txt").write_text(text, encoding="utf-8")
    r = client.post(
        "/api/interpretations",
        json={
            "interp_id": "i1",
            "source_document_id": "d1",
            "interpreter_type": "human",
            "interpreter_name": "t",
            "title": "t",
        },
    )
    assert r.status_code == 200, r.text
    return lib, part_id


# ── B-012 엔티티 패널 《현재 페이지만》 ────────────────────────────────────────────────


def test_b012_page_entities_return_units_under_the_key_the_screen_reads(tmp_path, monkeypatch):
    """B-012: 쪽 엔티티 응답은 단위를 《units》에 담는다 — 화면(entity-manager.js)이 그 키를 읽는다."""
    from core import entity as E

    unit = {"id": "u1", "source_ref": {"document_id": "d1", "page": 1}}
    monkeypatch.setattr(
        E, "list_entities", lambda path, kind, *a, **k: [unit] if kind == "unit" else []
    )
    out = E.list_entities_for_page(tmp_path, "d1", 1)
    assert out.get("units") == [unit], out
    # 화면이 쓰는 키 목록과 같아야 한다
    src = (STATIC_JS / "entity-manager.js").read_text(encoding="utf-8")
    assert 'unit: "units"' in src


# ── B-013·B-014·B-021·B-023 스냅샷 왕복 ───────────────────────────────────────────


def _snapshot_with_everything(client, tmp_path):
    """경계 둘·작업 계획·문헌별 승인·사용자 사전·주석 유형을 갖춘 서고에서 스냅샷을 만든다."""
    from core.alignment import VariantCharDict, save_document_approvals
    from core.snapshot import build_snapshot
    from ocr.read_book import plan_path

    lib, part_id = _setup(client, tmp_path)
    doc = lib / "documents" / "d1"
    ids = []
    for page in (1, 2):
        r = client.post(
            "/api/documents/d1/boundaries",
            json={
                "part_id": part_id,
                "start": {"page": page, "line": 0, "offset": 0},
                "title": f"t{page}",
            },
        )
        assert r.status_code == 200, r.text
        ids.append(r.json()["boundary"]["id"])
    plan = {"title": "계획", "guidance": "", "ranges": [], "chapters": []}
    p = plan_path(doc, part_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    appr = VariantCharDict.empty()
    appr.add_pair("爲", "為")
    save_document_approvals(doc, appr)
    # 사용자 사전(서고 resources/, D-104)과 서고 주석 유형(core/annotation_types.py의 자리)
    res = lib / "resources"
    res.mkdir(exist_ok=True)
    user = VariantCharDict.empty()
    user.add_pair("峯", "峰")
    user.save(str(res / "variant_chars.json"))
    (lib / "annotation_types.json").write_text(
        json.dumps(
            {"custom": [{"id": "my_type", "label": "내 유형", "color": "#123456"}], "hidden": []},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return lib, part_id, ids, build_snapshot(lib, "d1", "i1")


def test_b013_snapshot_round_trip_keeps_boundaries_plan_and_approvals(client, tmp_path):
    """B-013: 내보냈다 들이면 편성 경계·작업 계획·문헌별 승인이 그대로 있다."""
    from core.snapshot import create_work_from_snapshot
    from core.snapshot_validator import validate_snapshot

    lib, part_id, ids, snap = _snapshot_with_everything(client, tmp_path)
    errors, _warnings = validate_snapshot(snap)
    assert errors == [], errors
    out = create_work_from_snapshot(lib, json.loads(json.dumps(snap)))
    new_doc = lib / "documents" / out["doc_id"]
    bfile = new_doc / "boundaries" / f"{part_id}.json"
    assert bfile.exists(), "경계 목록이 들여지지 않았다"
    data = json.loads(bfile.read_text(encoding="utf-8"))
    assert [b["id"] for b in data["boundaries"]] == ids
    assert data["document_id"] == out["doc_id"]  # 새 문헌 id로 고쳐 적는다
    assert (new_doc / "read_plan" / f"{part_id}.json").exists()
    assert (new_doc / "variant_approvals.json").exists()


def test_b013_snapshot_carries_user_dictionary_and_custom_types(client, tmp_path):
    """B-013: 사용자 이체자 사전(서고 resources/)·서고 주석 유형이 스냅샷에 실리고, 들이면 합쳐진다."""
    from core.alignment import VariantCharDict
    from core.snapshot import create_work_from_snapshot

    lib, _part, _ids, snap = _snapshot_with_everything(client, tmp_path)
    vc = json.dumps(snap.get("variant_characters"), ensure_ascii=False)
    assert "峯" in vc and "峰" in vc, vc[:300]
    assert any(t.get("id") == "my_type" for t in snap.get("annotation_types") or [])

    # 다른 쌍을 이미 가진 서고로 들이면 덮어쓰지 않고 합친다
    other = tmp_path / "other_lib"
    (other / "resources").mkdir(parents=True)
    (other / "documents").mkdir()
    (other / "interpretations").mkdir()
    mine = VariantCharDict.empty()
    mine.add_pair("回", "囘")
    mine.save(str(other / "resources" / "variant_chars.json"))
    create_work_from_snapshot(other, json.loads(json.dumps(snap)))
    merged = VariantCharDict(dict_path=str(other / "resources" / "variant_chars.json"))
    assert merged.is_variant("回", "囘") and merged.is_variant("峯", "峰")
    types = json.loads((other / "annotation_types.json").read_text(encoding="utf-8"))
    assert any(t.get("id") == "my_type" for t in types.get("custom", []))


def test_b014_imported_manifest_is_schema_valid(client, tmp_path):
    """B-014: 들인 문헌의 manifest가 manifest.schema.json을 지킨다(회전 저장 등이 막히지 않게)."""
    from core.snapshot import create_work_from_snapshot

    lib, _part, _ids, snap = _snapshot_with_everything(client, tmp_path)
    out = create_work_from_snapshot(lib, json.loads(json.dumps(snap)))
    manifest = json.loads(
        (lib / "documents" / out["doc_id"] / "manifest.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(manifest, _schema("source_repo/manifest.schema.json"))


def test_b021_imported_l4_is_lf(client, tmp_path):
    """B-021: 스냅샷으로 들인 L4 쪽 글이 LF로 저장된다(Windows에서 CRLF가 되지 않는다)."""
    from core.snapshot import create_work_from_snapshot

    lib, part_id, _ids, snap = _snapshot_with_everything(client, tmp_path)
    out = create_work_from_snapshot(lib, json.loads(json.dumps(snap)))
    raw = (
        lib / "documents" / out["doc_id"] / "L4_text" / "pages" / f"{part_id}_page_001.txt"
    ).read_bytes()
    assert b"\n" in raw and b"\r\n" not in raw


def test_b021_l6_text_layer_is_lf(tmp_path):
    """B-021: 해석 층 텍스트(L6 .txt)가 LF로 저장된다."""
    from core.interpretation import save_layer_content

    interp = tmp_path / "interp"
    interp.mkdir()
    out = save_layer_content(interp, "L6_translation", "main_text", "v1", 1, "가\r\n나\n다")
    raw = (interp / out["file_path"]).read_bytes()
    assert raw == "가\n나\n다".encode("utf-8")


def test_b023_validator_does_not_flag_unit_ids_as_missing(client, tmp_path):
    """B-023: L5~L7의 block_id가 단위(경계) id면 《L3에 없음》 경고를 내지 않는다."""
    from core.snapshot_validator import validate_snapshot

    _lib, _part, ids, snap = _snapshot_with_everything(client, tmp_path)
    snap["interpretation"]["layers"]["L5_punctuation"] = [
        {"block_id": ids[0], "marks": [], "_source_path": "L5_reading/main_text/x_punctuation.json"}
    ]
    _errors, warnings = validate_snapshot(snap)
    assert not [w for w in warnings if ids[0] in w], warnings


# ── B-015 みんなで翻刻 L2의 koji 칸 ─────────────────────────────────────────────────


def test_b015_ocr_line_schema_accepts_koji():
    """B-015: honkoku 엔진이 행에 남기는 koji(태그 포함 표기)를 L2 스키마가 받는다(D-124 의도)."""
    schema = _schema("source_repo/ocr_page.schema.json")
    line_schema = {"$ref": "#/$defs/OcrLine", "$defs": schema["$defs"]}
    line = {"text": "學而", "bbox": [0, 0, 10, 20], "koji": "學[レ]而"}
    jsonschema.validate(line, line_schema)


# ── B-017 원문 내보내기와 교정 ───────────────────────────────────────────────────


def test_b017_text_export_uses_corrected_text(tmp_path):
    """B-017: 교정 탭의 자유 편집(corrections의 corrected_text)이 원문 내보내기에 들어간다."""
    from export.text_export import export_document

    doc = tmp_path / "documents" / "d1"
    (doc / "L4_text" / "pages").mkdir(parents=True)
    (doc / "L4_text" / "corrections").mkdir(parents=True)
    (doc / "manifest.json").write_text(
        json.dumps({"document_id": "d1", "title": "t", "parts": [{"part_id": "v1"}]}),
        encoding="utf-8",
    )
    (doc / "L4_text" / "pages" / "v1_page_001.txt").write_text("天地玄皇", encoding="utf-8")
    (doc / "L4_text" / "corrections" / "v1_page_001_corrections.json").write_text(
        json.dumps({"corrected_text": "天地玄黃", "corrections": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    files, _stats = export_document(doc, "v1", "md")
    body = "".join(files.values())
    assert "天地玄黃" in body and "玄皇" not in body


# ── B-020 LLM 교정의 이체자 사전 ─────────────────────────────────────────────────


def test_b020_correction_dicts_read_the_library_dictionary(tmp_path, monkeypatch):
    """B-020: LLM 교정의 strict 사전은 서고 resources/의 활성 사전이다(앱 폴더 파일이 아니다)."""
    from app.routers import llm_ocr
    from core.alignment import VariantCharDict

    lib = tmp_path / "lib"
    (lib / "resources").mkdir(parents=True)
    vd = VariantCharDict.empty()
    vd.add_pair("峯", "峰")
    vd.save(str(lib / "resources" / "variant_chars.json"))
    doc = lib / "documents" / "d1"
    doc.mkdir(parents=True)
    monkeypatch.setattr(llm_ocr, "get_library_path", lambda: lib)
    bundle, _pairs = llm_ocr._correction_dicts(doc)
    assert bundle.classify("峯", "峰") == "strict"


# ── B-022 주석 라우터의 낡은 경로 ───────────────────────────────────────────────


def test_b022_dictionary_export_names_the_source_document(client, tmp_path):
    """B-022: 사전 내보내기의 문헌 id·제목은 해석 저장소 manifest의 원본 문헌에서 온다."""
    _setup(client, tmp_path)
    r = client.get("/api/interpretations/i1/export/dictionary")
    assert r.status_code == 200, r.text
    meta = r.json().get("source") or r.json()
    text = json.dumps(meta, ensure_ascii=False)
    assert '"document_id": "d1"' in text, text[:400]
    assert '"document_title": "담초"' in text, text[:400]


def test_b022_pages_with_text_come_from_the_source_document(client, tmp_path):
    """B-022: 일괄 사전 생성의 대상 쪽은 원본 문헌의 L4(documents/{doc}/L4_text/pages)에서 센다."""
    from app.routers import annotation

    lib, part_id = _setup(client, tmp_path)
    pages = annotation._pages_with_source_text(lib / "interpretations" / "i1", part_id)
    assert pages == [1, 2, 3]


def test_b022_deleting_an_annotation_is_committed(client, tmp_path):
    """B-022: 주석 삭제도 추가·수정처럼 해석 저장소 git 이력에 남는다."""
    import git

    lib, part_id = _setup(client, tmp_path)
    q = f"?part_id={part_id}"
    r = client.post(
        f"/api/interpretations/i1/pages/1/annotations/__add/b1{q}",
        json={
            "target": {"start": 0, "end": 1},
            "type": "person",
            "content": {"label": "x", "description": "y"},
        },
    )
    assert r.status_code == 201, r.text
    ann_id = r.json()["id"]
    repo = git.Repo(lib / "interpretations" / "i1")
    before = len(list(repo.iter_commits()))
    r = client.delete(f"/api/interpretations/i1/pages/1/annotations/b1/{ann_id}{q}")
    assert r.status_code == 204, r.text
    assert len(list(repo.iter_commits())) == before + 1


# ── B-024 저장소 id 규칙 ──────────────────────────────────────────────────────────


def test_b024_reading_ingest_uses_the_single_repo_id_rule():
    """B-024: 강독 들이기의 해석 저장소 id 검사는 core.repo_id의 규칙 하나를 쓴다."""
    from core import reading_ingest, repo_id

    src = (ROOT / "src" / "core" / "reading_ingest.py").read_text(encoding="utf-8")
    assert "a-z0-9_" not in src, "정규식을 따로 적지 않는다"
    assert reading_ingest.REPO_ID_PATTERN is repo_id.REPO_ID_PATTERN


# ── B-031 KORCIS 판식·소장처 ───────────────────────────────────────────────────


def test_b031_korcis_fetch_by_url_brings_pansik_and_holdings(monkeypatch):
    """B-031: KORCIS URL로 가져오면 OpenAPI 상세(판식·소장처)가 실리고, 매퍼가 note_info의 판식까지 읽는다.

    2026-10-11 실측: rec_key=vdkvgwkey(302554414)로 상세를 받으면 판식(「左右雙邊…半葉10行22字」)은
    form_info가 아니라 note_info에 있다.
    """
    from parsers import korcis

    async def fake_marc(self, item_id):
        return {"vdkvgwkey": item_id, "245": {"a": "蒙求"}}

    async def fake_enrich(self, data):
        return None

    async def fake_openapi(rec_key, api_key=None):
        assert rec_key == "302554414"
        return {
            "form_info": "[3卷2冊 ;  , 18.8 x 13.0 cm]",
            "note_info": "[紙質: 洋紙<br>, 左右雙邊, 上下單邊. 半郭 13.4 x 9.6cm. 有界. 半葉10行22字. 小黑口. 線裝<br>]",
            "hold_libs": ["충남대학교 도서관"],
        }

    monkeypatch.setattr(korcis.KorcisFetcher, "_fetch_marc", fake_marc)
    monkeypatch.setattr(korcis.KorcisFetcher, "_enrich_with_contents", fake_enrich)
    monkeypatch.setattr(korcis, "openapi_detail", fake_openapi)
    raw = asyncio.run(
        korcis.KorcisFetcher().fetch_by_url(
            "https://www.nl.go.kr/korcis/search/searchResultDetail.do?vdkvgwkey=302554414"
        )
    )
    assert raw.get("_openapi_detail"), "수집 경로가 OpenAPI 상세를 싣지 않았다"
    bib = korcis.KorcisMapper().map_to_bibliography(raw)
    assert bib["printing_info"] and "10행" in json.dumps(bib["printing_info"], ensure_ascii=False)
    assert bib["repository"]["name"] == "충남대학교 도서관"


def test_b031_fetch_and_map_path_also_gets_pansik(monkeypatch):
    """B-031: 검색에서 고른 항목(fetch-and-map → fetch_detail)도 OpenAPI 판식·소장처를 받는다."""
    from parsers import korcis

    async def fake_marc(self, item_id):
        return {"vdkvgwkey": item_id}

    async def fake_enrich(self, data):
        return None

    async def fake_openapi(rec_key, api_key=None):
        return {"note_info": "四周單邊 半郭 20.0 x 14.0 cm 有界 10行20字", "hold_libs": ["규장각"]}

    monkeypatch.setattr(korcis.KorcisFetcher, "_fetch_marc", fake_marc)
    monkeypatch.setattr(korcis.KorcisFetcher, "_enrich_with_contents", fake_enrich)
    monkeypatch.setattr(korcis, "openapi_detail", fake_openapi)
    raw = asyncio.run(korcis.KorcisFetcher().fetch_detail("77"))
    bib = korcis.KorcisMapper().map_to_bibliography(raw)
    assert bib["printing_info"] and bib["repository"]["name"] == "규장각"


def test_b031_openapi_failure_does_not_break_fetch(monkeypatch):
    """B-031: OpenAPI가 실패해도 MARC 서지는 그대로 돌아온다(판식만 빈다)."""
    from parsers import korcis

    async def fake_marc(self, item_id):
        return {"vdkvgwkey": item_id}

    async def fake_enrich(self, data):
        return None

    async def boom(rec_key, api_key=None):
        raise ConnectionError("down")

    monkeypatch.setattr(korcis.KorcisFetcher, "_fetch_marc", fake_marc)
    monkeypatch.setattr(korcis.KorcisFetcher, "_enrich_with_contents", fake_enrich)
    monkeypatch.setattr(korcis, "openapi_detail", boom)
    raw = asyncio.run(
        korcis.KorcisFetcher().fetch_by_url(
            "https://www.nl.go.kr/korcis/search/searchResultDetail.do?vdkvgwkey=1"
        )
    )
    assert raw["vdkvgwkey"] == "1" and not raw.get("_openapi_detail")


# ── B-032 외부 텍스트 쪽 대조 ──────────────────────────────────────────────────


def test_b032_identical_text_maps_each_page_exactly():
    """B-032: OCR과 외부 텍스트가 같으면 쪽마다 matched_text가 그 쪽 원문과 같다."""
    from text_import.common import align_text_to_pages

    src = (
        "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏閏餘成歲律呂調陽雲騰致雨露結爲霜"
        "金生麗水玉出崑岡劍號巨闕珠稱夜光果珍李柰菜重芥薑海鹹河淡鱗潛羽翔龍師火帝鳥官人皇"
        "始制文字乃服衣裳推位讓國有虞陶唐弔民伐罪周發殷湯坐朝問道垂拱平章愛育黎首臣伏戎羌"
    )
    pages = [src[i : i + 40] for i in range(0, 120, 40)]
    result = align_text_to_pages(
        [{"page_num": n + 1, "text": t} for n, t in enumerate(pages)], "".join(pages)
    )
    got = {r["page_num"]: r["matched_text"] for r in result}
    assert [got[n + 1] for n in range(3)] == pages


# ── B-033 장서각·KOSTMA·규장각 서지 ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "module,cls,raw",
    [
        (
            "parsers.jsg",
            "JsgMapper",
            {"title": "國朝寶鑑", "사부분류": "史部", "유형분류": "고서/기타"},
        ),
        ("parsers.kostma", "KostmaMapper", {"title": "家禮", "분류": "經部"}),
        ("parsers.kyujanggak", "KyujanggakMapper", {"title": "雲養集", "사부분류": "集部"}),
    ],
)
def test_b033_korean_archive_mappers_produce_schema_valid_bibliography(module, cls, raw):
    """B-033: 세 기관 매퍼의 출력이 bibliography.schema.json을 지킨다(저장 검증에서 막히지 않게)."""
    import importlib

    mapper = getattr(importlib.import_module(module), cls)()
    bib = mapper.map_to_bibliography(raw)
    jsonschema.validate(bib, _schema("source_repo/bibliography.schema.json"))
    assert bib["subject"] and isinstance(bib["subject"], list)


# ── B-034 이미지 묶음 순서 ─────────────────────────────────────────────────────


def test_b034_image_bundle_uses_natural_order():
    """B-034: p1~p12 이미지가 p1, p2, … p10, p11, p12 순서로 묶인다(사전순이 아니라)."""
    from parsers.asset_detector import _group_images_into_bundles

    links = [("", f"https://x.org/book/p{i}.jpg") for i in (10, 2, 1, 12, 11, 3)]
    bundles = _group_images_into_bundles(links)
    urls = bundles[0]["download_urls"]
    assert [u.rsplit("/p", 1)[1] for u in urls] == [
        "1.jpg",
        "2.jpg",
        "3.jpg",
        "10.jpg",
        "11.jpg",
        "12.jpg",
    ]


# ── B-030(server.py 머리말) 라우터별 수 — 줄을 넘긴 표기도 검사기가 본다 ─────────────


def test_b030_drift_checker_sees_router_count_on_a_wrapped_line():
    """server.py 머리말처럼 《(N 라우트)》가 다음 줄로 넘어간 표기도 라우터별 수로 대조한다."""
    from tests.test_doc_drift import _load_checker  # 검사기를 한 벌로 불러오는 길(sys.modules 등록)

    cdd = _load_checker()
    facts = cdd.measure_facts(ROOT)
    text = "    routers/composition.py   — 편성: 내용 트리\n                               (1 라우트)\n"
    found = cdd.scan_text(text, "x.py", facts)
    assert any("composition.py" in m.desc for m in found), found


# ── 화면 JS ─────────────────────────────────────────────────────────────────────


def test_b016_citation_offsets_count_code_points(tmp_path):
    """B-016: 확장 한자(UTF-16 두 단위) 뒤의 글자도 코드포인트 위치로 돌려준다."""
    out = run_js(
        tmp_path,
        "citation-editor.js",
        ["_citeDisplayOffsetToOriginal"],
        "",
        # 《𠀀甲》: 화면(Range)의 표시 오프셋 2는 甲 — 코드포인트로는 1
        'console.log(JSON.stringify({i: _citeDisplayOffsetToOriginal(2, "\\u{20000}甲", [])}));',
    )
    assert out["i"] == 1


def test_b016_citation_requests_carry_part_id():
    """B-016: 인용 마크 API 호출은 모두 ?part_id=를 붙인다(다권본에서 《main》으로 새지 않게)."""
    src = (STATIC_JS / "citation-editor.js").read_text(encoding="utf-8")
    urls = re.findall(r"`[^`]*citation-marks[^`]*`", src)
    assert urls
    missing = [u for u in urls if "interpPartQuery" not in u and "part_id" not in u]
    assert missing == [], missing
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith(("*", "//")))
    assert "CITE_PRESETS." not in code, "없어진 상수를 참조한다"


_TRANS_STUBS = """
const calls = {toasts: [], bodies: []};
const transState = {sentences: [{text: "甲"}, {text: "乙"}], blockId: "u1", _refDictContext: "[참고 사전]\\n- 甲: 갑"};
const interpState = {interpId: "i1"};
const viewerState = {partId: "v1", pageNum: 1};
function _findTranslation() { return null; }
function confirm() { return true; }
function showToast(msg, kind) { calls.toasts.push(msg); }
function getLlmModelSelection() { return {force_provider: null, force_model: null}; }
function _transApiBlockId() { return "u1"; }
function _renderTransCards() {}
function _renderTransStatusSummary() {}
async function _addManualTranslation() { return true; } // 저장 성공(2026-10-11부터 참·거짓을 돌려준다)
const document = {querySelectorAll: () => [], getElementById: () => null};
let FAIL = true;
async function fetchWithSSE(url, body) {
  calls.bodies.push(body);
  if (FAIL) throw new Error("키 없음");
  return {translation: "번역"};
}
"""


def test_b018_single_translation_reports_failure_and_sends_reference_dict(tmp_path):
    """B-018: AI 번역 하나가 실패하면 false를 돌려주고, 적용한 참조 사전 문맥이 요청에 실린다."""
    out = run_js(
        tmp_path,
        "translation-editor.js",
        ["_aiTranslateSingle"],
        _TRANS_STUBS,
        "const bad = await _aiTranslateSingle(0); FAIL = false; const ok = await _aiTranslateSingle(0);"
        "console.log(JSON.stringify({bad, ok, body: calls.bodies[0]}));",
    )
    assert out["bad"] is False and out["ok"] is True
    assert out["body"].get("reference_context", "").startswith("[참고 사전]")


def test_b018_bulk_translation_counts_failures(tmp_path):
    """B-018: 일괄 AI 번역이 실패를 실패로 센다."""
    out = run_js(
        tmp_path,
        "translation-editor.js",
        ["_aiTranslateAll"],
        _TRANS_STUBS + "async function _aiTranslateSingle() { return false; }",
        "await _aiTranslateAll(); console.log(JSON.stringify({t: calls.toasts}));",
    )
    assert any("실패 2건" in t for t in out["t"]), out


def test_b018_translation_input_includes_reference_dict():
    """B-018: 서버가 화면이 보낸 참조 사전 문맥을 번역 프롬프트에 싣는다."""
    from app.routers.reading import AiTranslationRequest, _translation_input

    body = AiTranslationRequest(text="甲乙", reference_context="[참고 사전]\n- 甲: 갑")
    out = _translation_input(body)
    assert "- 甲: 갑" in out and out.rstrip().endswith("甲乙")


def test_b019_part_ocr_uses_the_selected_llm_model():
    """B-019: 권 전체 OCR도 쪽 OCR처럼 《ocr-llm-model-select》에서 고른 모델을 보낸다."""
    src = (STATIC_JS / "ocr-panel.js").read_text(encoding="utf-8")
    body = extract_js(src, ["_runPartOcr"])
    assert 'getLlmModelSelection("ocr-llm-model-select")' in body


def test_b025_shift_boundary_works_without_an_interpretation(tmp_path):
    """B-025: 시작 행 ▲▼는 해석 저장소 없이도 경계를 옮긴다(편성은 문헌의 것, D-097)."""
    setup = """
const calls = [];
const contentsState = {interpId: null, docId: "d1", partId: "v1"};
async function _shiftPreview() { return ""; }
function confirm() { return true; }
function _boundaryUrl(id) { return "/api/documents/d1/boundaries/" + id; }
async function fetch(url, opts) { calls.push([url, opts && opts.method]); return {ok: true, json: async () => ({})}; }
function showToast() {}
async function refreshContentsTree() {}
function _notifyBoundaryChanged() {}
const document = {dispatchEvent() {}};
class CustomEvent { constructor(n, o) { this.n = n; this.o = o; } }
"""
    out = run_js(
        tmp_path,
        "contents-tree.js",
        ["_shiftBoundary"],
        setup,
        'await _shiftBoundary({id: "b1", anchor: {page: 1, line: 0}}, 1);'
        "console.log(JSON.stringify({calls}));",
    )
    assert out["calls"] and out["calls"][0][1] == "PUT", out


def test_b026_variant_dictionary_can_be_activated_from_the_screen(tmp_path):
    """B-026: 이체자 탭에서 고른 사전을 《활성》으로 바꾸는 단추가 있고, 활성화 API를 부른다."""
    html = (ROOT / "src" / "app" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="vm-btn-activate"' in html
    src = (STATIC_JS / "variant-manager.js").read_text(encoding="utf-8")
    assert '_bindClick("vm-btn-activate", _activateDict)' in src
    setup = """
const calls = [];
const document = {getElementById: () => ({value: "my_dict"})};
async function fetch(url, opts) { calls.push([url, opts && opts.method]); return {ok: true, json: async () => ({})}; }
function showToast() {}
async function _loadDictList() {}
"""
    out = run_js(
        tmp_path,
        "variant-manager.js",
        ["_activateDict"],
        setup,
        "await _activateDict(); console.log(JSON.stringify({calls}));",
    )
    assert out["calls"][0] == ["/api/variant-dicts/my_dict/activate", "PUT"]


# ── B-035 시험이 외부에 닿지 않는다 ─────────────────────────────────────────────


def test_b035_tests_cannot_reach_external_hosts():
    """B-035: `network` 표지가 없는 시험은 바깥 연결이 막힌다(가짜 라우터를 빠뜨리면 빨간불)."""
    import socket

    with pytest.raises(ConnectionRefusedError, match="외부 네트워크 차단"):
        socket.create_connection(("203.0.113.7", 443), timeout=1)


@pytest.mark.parametrize("port", [11434, 10531, 10540])
def test_local_daemons_that_relay_outside_are_blocked_too(port):
    """루프백이어도 Ollama(11434)·OAuth 프록시(10531~10540)는 막는다 — 그 데몬이 바깥(ollama.com·OpenAI)으로
    넘겨 부른다. 예전에는 루프백을 통째로 열어 두어, PC에 Ollama가 떠 있으면 시험이 클라우드 모델까지 닿았다."""
    import socket

    with pytest.raises(ConnectionRefusedError, match="외부 네트워크 차단"):
        socket.create_connection(("127.0.0.1", port), timeout=1)


# ── 파서·가져오기의 남은 어긋남 ─────────────────────────────────────────────────


class _RecordingRouter:
    """LlmRouter.call만 흉내 낸다 — providers를 직접 돌면 AttributeError로 드러난다."""

    def __init__(self, text):
        self.text = text
        self.kwargs = []

    async def call(self, prompt, **kwargs):
        self.kwargs.append(kwargs)

        class R:
            pass

        r = R()
        r.text, r.provider, r.model = self.text, "fake", "fake-1"
        return r


def test_generic_llm_extraction_goes_through_the_router(monkeypatch):
    """범용 서지 추출은 LlmRouter.call 하나로 부르고 JSON을 강제한다(D-010 《라우터가 유일한 진입점》)."""
    from parsers.generic_llm import GenericLlmFetcher

    router = _RecordingRouter('{"title": "蒙求"}')
    f = GenericLlmFetcher()
    monkeypatch.setattr(f, "_get_router", lambda: router)
    out = asyncio.run(f._extract_with_llm("# 蒙求", "https://example.org/x"))
    assert out["title"] == "蒙求"
    assert router.kwargs[0].get("response_format") == "json"


def test_text_separator_asks_for_json():
    """원문/번역 분리 호출은 JSON을 강제한다(D-083)."""
    from text_import.text_separator import TextSeparator

    router = _RecordingRouter('{"original_text": "甲", "translation": "", "notes": ""}')
    sep = TextSeparator(router)
    asyncio.run(sep.analyze_structure([{"page_num": 1, "text": "甲 갑"}]))
    assert router.kwargs and all(k.get("response_format") == "json" for k in router.kwargs)


def test_ndl_fetch_detail_returns_the_record_with_that_bib_id(monkeypatch):
    """NDLBibID 키워드 검색의 첫 건이 다른 자료면 고르지 않는다 — ID가 같은 레코드를 돌려준다."""
    import httpx

    from parsers.ndl import NdlFetcher

    # NDL 응답의 ID 표기: <dc:identifier xsi:type="dcndl:NDLBibID">…</dc:identifier>
    def item(title, bib):
        return (
            f"<item><title>{title}</title><dc:title>{title}</dc:title>"
            f'<dc:identifier xsi:type="dcndl:NDLBibID">{bib}</dc:identifier></item>'
        )

    xml = (
        '<rss xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcndl="http://ndl.go.jp/dcndl/terms/"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<channel>" + item("엉뚱한 자료", "999") + item("蒙求", "123") + "</channel></rss>"
    ).encode("utf-8")

    class FakeResp:
        content = xml

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    out = asyncio.run(NdlFetcher().fetch_detail("123"))
    assert out.get("dcndl:NDLBibID") == "123"


def test_kostma_assets_survive_a_non_numeric_book_number():
    """KOSTMA 책 번호가 숫자가 아니어도 자산 목록 전체가 죽지 않는다."""
    from parsers.kostma import KostmaFetcher

    raw = {
        "title": "家禮",
        "book_infos": [{"imgInfos": [{"bookNum": "上", "bookPath": "B1", "fname": "a.jpg"}]}],
    }
    assets = asyncio.run(KostmaFetcher().list_assets(raw))
    assert assets and "上" in assets[0]["label"]


def test_pdf_text_extractor_is_always_closed():
    """PdfTextExtractor는 언제나 with로 연다(AGENTS 《fitz.open()은 with로》 — Windows가 PDF를 잠근다)."""
    import ast

    bad = []
    for path in (ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        in_with = {
            id(item.context_expr)
            for node in ast.walk(tree)
            if isinstance(node, (ast.With, ast.AsyncWith))
            for item in node.items
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "PdfTextExtractor"
                and id(node) not in in_with
            ):
                bad.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    assert bad == [], bad


def test_archives_jp_parse_failure_is_logged(monkeypatch, caplog):
    """국립공문서관 검색 결과 해석이 깨지면 빈 목록과 함께 경고를 남긴다(조용히 0건이 되지 않게)."""
    import logging

    from parsers import archives_jp

    def boom(_text):
        raise ValueError("구조가 바뀌었다")

    monkeypatch.setattr(archives_jp.lxml_html, "fromstring", boom)
    with caplog.at_level(logging.WARNING, logger=archives_jp.logger.name):
        assert archives_jp._parse_search_results("<html/>") == []
        archives_jp._parse_detail_page("<html/>", "https://www.digital.archives.go.jp/x")
    assert sum("구조가 바뀌었다" in r.getMessage() for r in caplog.records) == 2


# ── B-028 OCR 라우트의 문헌 id 검증 ─────────────────────────────────────────────


def test_b028_ocr_routes_validate_document_id():
    """B-028: OCR 라우트가 문헌 경로를 require_repo_path로만 만든다(id 형식 검증 — 경로 탈출 차단)."""
    src = (ROOT / "src" / "app" / "routers" / "llm_ocr.py").read_text(encoding="utf-8")
    assert '/ "documents" / doc_id' not in src


def test_b028_bad_document_id_is_rejected_not_looked_up(client, tmp_path):
    """B-028: 규칙에 안 맞는 문헌 id(대문자)는 400 — 파일을 찾아보기 전에 막힌다."""
    _setup(client, tmp_path)
    r = client.get("/api/documents/BAD_ID/parts/vol1/pages/1/ocr")
    assert r.status_code == 400, r.text


# ── 작은 파서 결함 ───────────────────────────────────────────────────────────


def test_asset_extension_comes_from_the_last_path_segment():
    """폴더 이름의 점을 확장자로 오인하지 않는다."""
    from parsers.asset_detector import _get_file_extension

    assert _get_file_extension("/a.b/c") == ""
    assert _get_file_extension("/docs/file.PDF?v=1") == ".pdf"


def test_ndl_mapper_carries_publisher_and_place():
    """NDL 서지에 발행자·발행지가 실리고 스키마를 지킨다."""
    from parsers.ndl import NdlMapper

    bib = NdlMapper().map_to_bibliography(
        {"dc:title": "蒙求", "dc:publisher": "藝文印書館", "dcndl:publicationPlace": "臺北"}
    )
    assert bib["publishing"] == {"place": "臺北", "publisher": "藝文印書館"}
    jsonschema.validate(bib, _schema("source_repo/bibliography.schema.json"))


# ── 화면에 넣는 문자열·CSS 변수 ─────────────────────────────────────────────


def test_b029_known_unescaped_sites_are_escaped():
    """B-029: 전수에서 짚은 자리들이 이스케이프를 거친다(같은 자리가 되돌아오지 않게)."""
    raw = {
        "translation-editor.js": ['rows="2">${tr.translation}</textarea>', "${punctuatedText}</span>"],
        "hyeonto-editor.js": ["${annBefore[i]}</span>", '"hyeonto-char">${ch}</span>', ": ${ann.text}</span>"],
        "interpretation.js": ['"interp-list-source">${item.source_document_id}</span>', "${tf.path}</span>"],
        "workspace.js": ["<strong>${repo.id}</strong>", 'value="${repo.remote_url || ""}"'],
        "citation-editor.js": ["[${t.status}]", 'data-cite-id="${m.id}"'],
        "composition-editor.js": ["못했습니다: ${e.message}</div>"],
        "contents-tree.js": ['[data-block-id="${blockId}"]'],
    }
    left = []
    for name, pats in raw.items():
        src = (STATIC_JS / name).read_text(encoding="utf-8")
        left += [f"{name}: {p}" for p in pats if p in src]
    assert left == [], left


def test_css_variables_used_are_defined():
    """화면이 쓰는 CSS 변수(폴백 없는 var(--x))는 어딘가에 정의돼 있다 — 없으면 그 선언은 조용히 무시된다."""
    static = ROOT / "src" / "app" / "static"
    # 함께 실은 제3자 라이브러리(static/vendor, D-140)는 우리 화면 코드가 아니라 뺀다
    files = [f for f in [*static.rglob("*.css"), *static.rglob("*.js"), *static.rglob("*.html")] if "vendor" not in f.parts]
    defined, used = set(), {}
    for f in files:
        s = f.read_text(encoding="utf-8", errors="replace")
        defined |= set(re.findall(r"(--[a-zA-Z0-9-]+)\s*:", s))
        defined |= set(re.findall(r"setProperty\(\s*[\"'](--[a-zA-Z0-9-]+)", s))
        for m in re.finditer(r"var\((--[a-zA-Z0-9-]+)\s*(,)?", s):
            if not m.group(2):
                used.setdefault(m.group(1), set()).add(f.name)
    missing = {k: sorted(v) for k, v in used.items() if k not in defined}
    assert missing == {}, missing


# ── 2차 전수(S-20261011-185238): 화면 JS ──────────────────────────────────────────────────────
_DOM_STUB = """
// textContent → innerHTML: 브라우저처럼 &, <, > 만 바꾸고 따옴표는 그대로 둔다
globalThis.document = { createElement() {
  let t = ""; return { set textContent(v) { t = String(v); },
    get innerHTML() { return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); } }; } };
"""


def _escape_helpers() -> list[tuple[str, str]]:
    """화면 JS의 최상위 이스케이프 함수 전부 — (파일, 이름). 손으로 적은 목록이면 새 함수가 빠진다."""
    out = []
    for f in sorted(STATIC_JS.glob("*.js")):
        for m in re.finditer(r"^function\s+(_?[A-Za-z]*[Ee]sc[A-Za-z]*)\s*\(", f.read_text(encoding="utf-8"), re.M):
            if "scalat" not in m.group(1):  # 애매한 후보(escalate) 함수는 이스케이프가 아니다
                out.append((f.name, m.group(1)))
    return out


@pytest.mark.parametrize(("js_file", "fn"), _escape_helpers())
def test_every_escape_helper_blocks_both_quotes(tmp_path, js_file, fn):
    """이스케이프 함수는 어느 것이든 큰·작은따옴표까지 막는다 — 속성 자리(title="${…}")에 쓰여도 안전하게.
    전에는 textContent 방식 아홉 개가 따옴표를 그대로 두었고, 그중 다섯이 문헌·권 제목(끌어다 놓은 파일 이름)·
    에셋 id·외부 서지의 source_url을 속성에 넣었다(create-document 450·693, contents-tree 112·141, bibliography 690)."""
    out = run_js(tmp_path, js_file, [fn], _DOM_STUB, f'console.log(JSON.stringify({{v: {fn}(`a"b\'c<d>&`)}}));')
    v = out["v"]
    assert '"' not in v and "'" not in v, f"{js_file}::{fn} → {v!r}"
    assert "<" not in v and ">" not in v


# 확장 한자(CJK 확장 B, U+20000)는 UTF-16에서 두 단위다 — 그 뒤의 좌표가 코드포인트로 맞는지 본다.
# 서버(파이썬 str)는 코드포인트로 센다: "𠀀天地"에서 天은 1번.
_ASTRAL = "\U00020000天地"
_EL_STUB = """
const _els = {}; globalThis.document = { getElementById(id) { return (_els[id] = _els[id] || { textContent: "", innerHTML: "", style: {} }); } };
"""


def test_hyeonto_preview_counts_code_points(tmp_path):
    """현토 미리보기 — 1번 글자(天) 뒤 현토가 天 뒤에 붙는다. 전에는 UTF-16으로 세어 𠀀의 뒤쪽 반에 붙었다."""
    out = run_js(tmp_path, "hyeonto-editor.js", ["_htChars", "_renderHyeontoPreview"], _EL_STUB + f"""
globalThis.hyeontoState = {{ originalText: {json.dumps(_ASTRAL)}, punctMarks: [],
  annotations: [{{ target: {{ start: 1, end: 1 }}, position: "after", text: "은" }}] }};""",
        '_renderHyeontoPreview(); console.log(JSON.stringify({v: _els["hyeonto-preview"].textContent}));')
    assert out["v"] == "\U00020000天은地"


def test_translation_sentence_split_counts_code_points(tmp_path):
    """번역 문장 나누기 — 표점 。이 天(1번) 뒤면 첫 문장은 《𠀀天》, 범위 0~1. 서버 split_sentences와 같은 자."""
    out = run_js(tmp_path, "translation-editor.js", ["_trChars", "_splitSentencesClient"], "",
        f'console.log(JSON.stringify(_splitSentencesClient({json.dumps(_ASTRAL)}, [{{target: {{start: 1, end: 1}}, after: "。"}}])));')
    assert out == [{"start": 0, "end": 1, "text": "\U00020000天"}, {"start": 2, "end": 2, "text": "地"}]


def test_correction_local_apply_counts_code_points(tmp_path):
    """교정 미리 적용 — char_index 1(天)을 人으로. 서버 _apply_corrections_to_text와 같은 결과여야 한다."""
    from core.document import _apply_corrections_to_text

    corr = [{"char_index": 1, "original_ocr": "天", "corrected": "人", "block_id": None, "line": None}]
    out = run_js(tmp_path, "correction-editor.js", ["_corrChars", "_applyCorrectionsLocally"], "",
        f"console.log(JSON.stringify({{v: _applyCorrectionsLocally({json.dumps(_ASTRAL)}, {json.dumps(corr)})}}));")
    assert out["v"] == "\U00020000人地"
    assert _apply_corrections_to_text(_ASTRAL, corr) == out["v"]


def test_punctuation_preview_counts_code_points(tmp_path):
    """표점 미리보기 — 天(1번) 뒤 。가 天 뒤에 붙는다."""
    out = run_js(tmp_path, "punctuation-editor.js", ["_puChars", "_renderPreview"], _EL_STUB + f"""
globalThis.punctState = {{ originalText: {json.dumps(_ASTRAL)}, marks: [{{ target: {{ start: 1, end: 1 }}, after: "。" }}] }};""",
        '_renderPreview(); console.log(JSON.stringify({v: _els["punct-preview"].textContent}));')
    assert out["v"] == "\U00020000天。地"


@pytest.mark.parametrize(("etype", "fields"), [
    ("tag", {"ef-surface": "王戎", "ef-block-id": "u1", "ef-core-category": "person", "ef-status": "draft"}),
    ("agent", {"ef-name": "王戎", "ef-status": "draft"}),
])
def test_entity_edit_keeps_metadata(tmp_path, etype, fields):
    """Tag·Agent를 고쳐 저장해도 기존 metadata가 남는다 — 서버는 얕은 병합이라 null을 보내면 지워졌다."""
    setup = (
        "globalThis.__fields = " + json.dumps(fields, ensure_ascii=False) + ";\n"
        "globalThis.document = { getElementById: (id) => (id in globalThis.__fields ? { value: globalThis.__fields[id] } : null) };\n"
        "globalThis.entityState = { editingEntity: { id: 'e1', metadata: { promoted_to: 'c9' } } };\n"
    )
    out = run_js(tmp_path, "entity-manager.js", ["_collectFormData"], setup,
                 f"console.log(JSON.stringify({{b: _collectFormData({etype!r})}}));")
    assert out["b"]["metadata"] == {"promoted_to": "c9"}


def test_notes_pending_save_goes_to_the_page_it_was_written_on(tmp_path):
    """비고를 3쪽에 쓰고 2초 안에 4쪽으로 옮기면 그 비고는 3쪽에 저장되고, 4쪽 파일은 덮이지 않는다."""
    setup = """
const calls = [];
globalThis.fetch = async (url, opt) => { calls.push({ url, method: (opt && opt.method) || "GET", body: opt && opt.body });
  return { ok: true, json: async () => ({ entries: [] }) }; };
const _el = () => ({ innerHTML: "", textContent: "" });
globalThis.document = { getElementById: () => _el() };
globalThis.interpState = { interpId: "i1" };
globalThis.viewerState = { partId: "vol1", pageNum: 3 };
globalThis.notesState = { entries: [], loaded: true, saveTimer: null, pendingTarget: null, saving: false };
globalThis._renderNotes = () => {};
"""
    body = """
notesState.entries = [{ text: "3쪽 비고" }];
_scheduleSave();
viewerState.pageNum = 4;             // 2초가 지나기 전에 쪽을 옮긴다
await loadPageNotes();
await new Promise((r) => setTimeout(r, 2200)); // 옛 타이머가 남아 있었다면 여기서 터진다
console.log(JSON.stringify(calls.map((c) => [c.method, c.url, c.body || null])));
"""
    out = run_js(tmp_path, "notes-panel.js", ["_notesInterpId", "_notesTarget", "_notesStillOn", "_flushNotesSave", "_saveNotes", "_scheduleSave", "loadPageNotes"], setup, body)
    puts = [c for c in out if c[0] == "PUT"]
    assert len(puts) == 1 and "/pages/3/" in puts[0][1] and "3쪽 비고" in puts[0][2], out
    assert not any(c[0] == "PUT" and "/pages/4/" in c[1] for c in out), out


def test_new_layout_block_id_never_repeats_a_remaining_one(tmp_path):
    """b01·b02·b03에서 b01을 지우고 새로 그리면 b04 — 전에는 《개수 + 1》 = b03이라 남은 것과 겹쳤다."""
    out = run_js(tmp_path, "layout-editor.js", ["_nextLayoutBlockId"], "",
                 'console.log(JSON.stringify({v: _nextLayoutBlockId(7, [{block_id: "p07_b02"}, {block_id: "p07_b03"}]), e: _nextLayoutBlockId(7, [])}));')
    assert out == {"v": "p07_b04", "e": "p07_b01"}
    src = (STATIC_JS / "layout-editor.js").read_text(encoding="utf-8")
    assert "layoutState.blocks.length + 1" not in src


def test_dictionary_save_keeps_source_section_and_url(tmp_path):
    """사전 필드를 저장해도 출전의 section·url과 폼에 없는 사전 칸이 남는다 — 전에는 {title}만 다시 만들어 보냈다."""
    prev = {"headword": "王戎", "dictionary_meaning": "옛 뜻", "generated_by": "llm",
            "source_references": [{"title": "世說新語", "section": "德行", "url": "https://x/1"}]}
    fields = {"ann-dict-headword": "王戎", "ann-dict-meaning": "새 뜻", "ann-dict-src-refs": "世說新語, 晉書"}
    setup = (
        "let sent = null;\n"
        "globalThis.fetch = async (url, opt) => { sent = JSON.parse(opt.body); return { ok: true, json: async () => ({}) }; };\n"
        "const F = " + json.dumps(fields, ensure_ascii=False) + ";\n"
        "globalThis.document = { getElementById: (id) => (id in F ? { value: F[id] } : null) };\n"
        "globalThis.viewerState = { pageNum: 1 }; globalThis.interpState = { interpId: 'i1' };\n"
        "globalThis.annState = { selectedAnnId: 'a1', annotations: [{ id: 'a1', dictionary: " + json.dumps(prev, ensure_ascii=False) + " }] };\n"
        "globalThis._annApiBlockId = () => 'u1'; globalThis._annPartQuery = () => '';\n"
        "globalThis._showSaveStatus = () => {}; globalThis._loadBlockAnnotations = async () => {}; globalThis._renderAnnList = () => {};\n"
    )
    out = run_js(tmp_path, "annotation-editor.js", ["_saveDictFields"], setup, "await _saveDictFields(); console.log(JSON.stringify(sent));")
    d = out["dictionary"]
    assert d["dictionary_meaning"] == "새 뜻" and d["generated_by"] == "llm"
    assert d["source_references"] == [{"title": "世說新語", "section": "德行", "url": "https://x/1"}, {"title": "晉書"}]


_STATIC = ROOT / "src" / "app" / "static"


def test_every_used_animation_has_keyframes():
    """CSS·화면이 쓰는 animation 이름에는 @keyframes가 있다 — progress-pulse가 없어 진행 막대가 멈춰 있었다."""
    text = "\n".join(p.read_text(encoding="utf-8") for p in [*_STATIC.rglob("*.css"), *_STATIC.rglob("*.js"), _STATIC / "index.html"] if "vendor" not in p.parts)
    defined = set(re.findall(r"@keyframes\s+([\w-]+)", text))
    keywords = {"none", "infinite", "linear", "ease", "ease-in", "ease-out", "ease-in-out", "alternate", "forwards",
                "backwards", "both", "normal", "reverse", "running", "paused", "step-end", "step-start",
                "alternate-reverse", "var", "cubic-bezier", "steps"}
    used = set()
    for m in re.finditer(r"animation(?:-name)?\s*:\s*([^;\"'}]+)", text):
        used |= {t for t in re.split(r"[\s,]+", m.group(1)) if re.fullmatch(r"[a-zA-Z][\w-]*", t) and t not in keywords}
    assert used - defined == set()


def test_elements_shown_with_empty_display_are_not_hidden_by_the_stylesheet():
    """JS가 style.display=""로 켜는 요소를 스타일시트가 display:none으로 숨기면 영영 안 보인다
    (인용 《원문이 마크 이후 변경되었습니다》 경고). index.html의 id 요소 + getElementById 경로를 전부 본다."""
    css = re.sub(r"/\*.*?\*/", "", "\n".join(p.read_text(encoding="utf-8") for p in _STATIC.rglob("*.css") if "vendor" not in p.parts), flags=re.S)
    hidden_cls, hidden_id = set(), set()
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        if re.search(r"display\s*:\s*none", m.group(2)):
            for sel in (s.strip() for s in m.group(1).split(",")):
                if re.fullmatch(r"\.[\w-]+", sel):
                    hidden_cls.add(sel[1:])
                elif re.fullmatch(r"#[\w-]+", sel):
                    hidden_id.add(sel[1:])
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    classes = {}
    for m in re.finditer(r"<[a-zA-Z][^>]*\bid=\"([\w-]+)\"[^>]*>", html):
        c = re.search(r"\bclass=\"([^\"]*)\"", m.group(0))
        classes[m.group(1)] = c.group(1).split() if c else []
    bad = []
    for f in STATIC_JS.glob("*.js"):
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"(?:const|let|var)\s+(\w+)\s*=\s*document\.getElementById\(\s*[\"']([\w-]+)[\"']\s*\)", src):
            var, eid = m.groups()
            if re.search(rf"\b{re.escape(var)}\.style\.display\s*=\s*[^;\n]*[\"'][\"']", src[m.end(): m.end() + 4000]):
                if eid in hidden_id or any(c in hidden_cls for c in classes.get(eid, [])):
                    bad.append(f"{f.name}: #{eid}")
    assert bad == [], bad


def test_ctrl_s_saves_text_only_when_this_editor_is_shown_and_dirty(tmp_path):
    """Ctrl+S가 숨은 텍스트 편집기의 옛 글로 확정본을 덮지 않는다 — 보이고 수정된 때만 저장."""
    setup = """
let saves = 0, keydown = null;
const ta = { value: "", offsetParent: null, addEventListener() {}, dispatchEvent() {} };
globalThis.document = {
  getElementById: (id) => (id === "text-content" ? ta : { addEventListener() {} }),
  addEventListener: (ev, fn) => { if (ev === "keydown") keydown = fn; },
};
globalThis.viewerState = { docId: "d1" };
globalThis.editorState = { isDirty: false, originalText: "" };
globalThis._saveCurrentText = () => { saves++; };
globalThis._updateSaveStatus = () => {}; globalThis._insertAtCursor = () => {};
"""
    body = """
initTextEditor();
const press = () => keydown({ ctrlKey: true, key: "s", preventDefault() {} });
press();                                   // 숨음·수정 없음
editorState.isDirty = true; press();       // 숨음·수정 있음 (다른 탭에서 Ctrl+S)
ta.offsetParent = {}; editorState.isDirty = false; press(); // 보임·수정 없음
editorState.isDirty = true; press();       // 보임·수정 있음 → 저장
console.log(JSON.stringify({ saves }));
"""
    out = run_js(tmp_path, "text-editor.js", ["initTextEditor"], setup, body)
    assert out["saves"] == 1


# ── 1차 전수에서 넘어온 데이터 손실 셋 ─────────────────────────────────────────────────────────
def _tiny_library(root: Path) -> Path:
    lib = root / "lib"
    (lib / "documents").mkdir(parents=True)
    (lib / "library_manifest.json").write_text("{}", encoding="utf-8")
    return lib


def test_backup_never_moves_or_deletes_a_folder_it_did_not_make(tmp_path):
    """다른 파일이 든 폴더(구글 드라이브 등)를 백업 자리로 골라도 그 파일은 옮겨지거나 지워지지 않는다.
    전에는 첫 백업이 폴더를 통째로 《_prev》로 옮기고 두 번째 백업이 rmtree로 지웠다."""
    from core.backup import backup_library

    lib = _tiny_library(tmp_path)
    drive = tmp_path / "drive"
    drive.mkdir()
    (drive / "논문.hwp").write_text("소중한 파일", encoding="utf-8")
    r1 = backup_library(lib, drive)
    r2 = backup_library(lib, drive)
    assert r1["success"] and r2["success"], (r1, r2)
    assert (drive / "논문.hwp").read_text(encoding="utf-8") == "소중한 파일"
    assert not (tmp_path / "drive_prev").exists()
    assert Path(r2["backup_path"]).parent == drive
    assert (Path(r2["backup_path"]) / "library_manifest.json").exists()


def test_backup_rotates_its_own_previous_backup(tmp_path):
    """빈 폴더나 이 앱이 만든 백업 자리는 예전처럼 그 자리에 쓰고, 옛 백업은 _prev로 돌린다."""
    from core.backup import backup_library

    lib = _tiny_library(tmp_path)
    target = tmp_path / "bk"
    target.mkdir()
    assert backup_library(lib, target)["backup_path"] == str(target.resolve())
    assert backup_library(lib, target)["success"]
    assert (tmp_path / "bk_prev" / "_backup_meta.json").exists()


def test_env_write_keeps_other_lines_of_a_cp949_file(tmp_path):
    """메모장이 cp949로 저장한 .env에 키 하나를 넣어도 다른 줄(예산·모델 고정·한글 주석)이 남는다."""
    from core.env_settings import MANAGED_KEYS, env_path, write_values

    p = env_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes("# 한글 주석\nMONTHLY_BUDGET_USD=5\nCTB_PIN_MODEL=x\n".encode("cp949"))
    provider = next(iter(MANAGED_KEYS))
    write_values(tmp_path, {provider: "sk-test-1234"})
    text = p.read_text(encoding="utf-8")
    assert "MONTHLY_BUDGET_USD=5" in text and "CTB_PIN_MODEL=x" in text and "# 한글 주석" in text
    assert f"{MANAGED_KEYS[provider]}=sk-test-1234" in text


def test_env_write_refuses_an_unreadable_file(tmp_path):
    """UTF-8도 cp949도 아닌 .env는 고치지 않는다 — 원래 바이트가 그대로 남는다."""
    from core.env_settings import MANAGED_KEYS, env_path, write_values

    p = env_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    junk = b"BUDGET=5\n\xff\xfe\xfa\n"
    p.write_bytes(junk)
    with pytest.raises(ValueError):
        write_values(tmp_path, {next(iter(MANAGED_KEYS)): "sk-x"})
    assert p.read_bytes() == junk


def test_trash_move_never_falls_back_to_copy_and_delete(tmp_path, monkeypatch):
    """잠긴 폴더를 휴지통으로 못 옮기면 원본을 그대로 두고 실패를 알린다 — 전에는 shutil.move가
    《복사 → 원본 지우기》로 넘어가, 원본 지우기가 도중에 멈추면 완전한 사본을 지우고 원본 조각만 옮겼다."""
    import core.library as libmod

    lib = _tiny_library(tmp_path)
    doc = lib / "documents" / "doc1"
    (doc / "L4_text").mkdir(parents=True)
    (doc / "L4_text" / "p1.txt").write_text("본문", encoding="utf-8")

    def locked(src, dst):
        raise PermissionError("잠김")

    monkeypatch.setattr(libmod.os, "rename", locked)
    monkeypatch.setattr(libmod.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        libmod._move_to_trash(lib, "documents", "doc1")
    assert (doc / "L4_text" / "p1.txt").read_text(encoding="utf-8") == "본문"
    trash = lib / ".trash" / "documents"
    assert not trash.exists() or not any(trash.iterdir())


def test_zip_copy_does_not_overwrite_files_edited_after_conversion(tmp_path):
    """zip 사본을 git 사본으로 바꾼 뒤 사용자가 고친 파일이 있으면 《받기》가 reset --hard로 덮지 않는다.
    바꾼 그대로면(zip 시점 파일) 예전처럼 원격에 맞춘다."""
    import shutil as _sh
    import subprocess as _sp

    from core import updater

    if _sh.which("git") is None:
        pytest.skip("git이 없다")

    def g(args, cwd):
        _sp.run(["git", *args], cwd=str(cwd), capture_output=True, check=True)

    origin = tmp_path / "origin"
    origin.mkdir()
    for a in (["init", "-q"], ["symbolic-ref", "HEAD", "refs/heads/main"],
              ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        g(a, origin)
    (origin / "app.py").write_text("v1\n", encoding="utf-8")
    g(["add", "."], origin)
    g(["commit", "-q", "-m", "first"], origin)
    z = tmp_path / "zip"
    z.mkdir()
    (z / "app.py").write_text("v1\n", encoding="utf-8")
    (origin / "app.py").write_text("v2\n", encoding="utf-8")
    g(["commit", "-q", "-am", "second"], origin)

    assert updater.ensure_git_checkout(z, remote=str(origin))["ok"]
    assert updater.zip_user_changes(z) == []          # 바꾼 그대로 — 원격에 맞춰도 된다
    (z / "app.py").write_text("사용자가 고친 줄\n", encoding="utf-8")
    assert updater.zip_user_changes(z) == ["app.py"]  # 그 뒤 고쳤다 — 덮으면 안 된다


def test_hwp_taidu_pos_points_at_the_raised_character():
    """대두 공백 뒤 글자의 clean_text 자리가 pos다 — 예전에는 늘 0이라 대두가 모두 첫 글자에 붙어 저장됐다."""
    from hwp.text_cleaner import clean_hwp_text

    r = clean_hwp_text("天地之道\n  王命以下\n事", strip_punct=True, strip_hyeonto=True)
    assert r.clean_text == "天地之道王命以下事"
    assert [t["pos"] for t in r.taidu_marks] == [4]
    assert r.clean_text[r.taidu_marks[0]["pos"]] == "王"


@pytest.mark.parametrize("server_ok", [True, False])
def test_reset_corrections_in_free_edit_really_empties_and_reports_failure(tmp_path, server_ok):
    """자유 편집 모드의 《모두 삭제》는 원문을 보낸다(지금 글을 보내면 서버가 같은 교정을 다시 만든다).
    저장이 실패하면 실패를 알린다 — 예전 _saveCorrections는 실패를 삼켜 리셋의 알림이 닿지 않았다."""
    setup = f"""
const sent = []; const toasts = [];
const SERVER_OK = {str(server_ok).lower()};
globalThis.fetch = async (url, opt) => {{ if (opt && opt.method === "PUT") sent.push(JSON.parse(opt.body));
  return {{ ok: SERVER_OK, json: async () => ({{ corrections: [], git: null }}) }}; }};
globalThis.AbortController = class {{ constructor() {{ this.signal = null; }} abort() {{}} }};
globalThis.confirm = () => true;
globalThis.showToast = (m, k) => toasts.push(k || "info");
const ta = {{ value: "고친 글" }};
globalThis.document = {{ getElementById: (id) => (id === "corr-freetext-editor" ? ta : null) }};
globalThis.viewerState = {{ docId: "d", partId: "vol1", pageNum: 1 }};
globalThis.correctionState = {{ editMode: "freetext", pageText: "원문", correctedText: "고친 글",
  corrections: [{{ char_index: 0, original_ocr: "원", corrected: "고친" }}], editSeq: 0, saving: false }};
for (const f of ["_updateCorrSaveStatus", "_renderCorrectionView", "_renderCorrList", "_updateCorrCount", "_loadGitLog"]) globalThis[f] = () => {{}};
"""
    out = run_js(tmp_path, "correction-editor.js", ["_corrChars", "_applyCorrectionsLocally", "_saveCorrections", "_resetAllCorrections"],
                 setup, "await _resetAllCorrections(); console.log(JSON.stringify({ sent, toasts }));")
    assert out["sent"] and out["sent"][0]["corrected_text"] == "원문"
    assert ("error" in out["toasts"]) is (not server_ok)


def test_manifest_has_one_entry_per_id_after_trash_and_recreate(tmp_path):
    """휴지통으로 보내면 매니페스트 목록에서 빠지고, 같은 id를 다시 등록해도 항목은 하나다."""
    from core.document import _update_library_manifest
    from core.library import trash_document

    lib = _tiny_library(tmp_path)
    (lib / "documents" / "doc1").mkdir()
    _update_library_manifest(lib, "doc1", "첫판")
    trash_document(lib, "doc1")
    m = json.loads((lib / "library_manifest.json").read_text(encoding="utf-8"))
    assert [d["document_id"] for d in m["documents"]] == []
    _update_library_manifest(lib, "doc1", "다시 만든 판")
    _update_library_manifest(lib, "doc1", "또 다시")
    m = json.loads((lib / "library_manifest.json").read_text(encoding="utf-8"))
    assert [(d["document_id"], d["title"]) for d in m["documents"]] == [("doc1", "또 다시")]


def test_bibliography_manual_edit_can_clear_a_field(tmp_path):
    """서지 수동 편집에서 칸을 비우면 지워진다(null) — 예전에는 《값 || 옛 값》이라 지울 수 없었다."""
    setup = """
const F = { "bib-edit-notes": { value: "  " }, "bib-edit-series": { value: "새 총서" } };
globalThis.document = { getElementById: (id) => F[id] || null };
"""
    out = run_js(tmp_path, "bibliography.js", ["_bibEditOr"], setup,
                 'console.log(JSON.stringify({n: _bibEditOr("bib-edit-notes", "옛 메모"), s: _bibEditOr("bib-edit-series", "옛"), m: _bibEditOr("bib-edit-missing", "옛 값")}));')
    assert out == {"n": None, "s": "새 총서", "m": "옛 값"}
    src = (STATIC_JS / "bibliography.js").read_text(encoding="utf-8")
    assert '_getEditField("bib-edit-notes") || bib.notes' not in src


def test_hwp_leading_punctuation_is_marked_before_the_first_char():
    """첫 원문 글자 앞에 온 표점은 《0번 앞》으로 적힌다 — 《0번 뒤》와 구별된다."""
    from hwp.text_cleaner import clean_hwp_text

    marks = clean_hwp_text("「天地」").punctuation_marks
    assert marks[0] == {"pos": 0, "mark": "「", "original_mark": "「", "position": "before"}
    assert "position" not in marks[1] and marks[1]["pos"] == 1


def test_index_html_has_no_literal_unicode_escapes():
    """HTML은 \\u201c 같은 JS 탈출을 해석하지 않는다 — 라벨에 백슬래시가 그대로 찍혔다(인용 《원문을 “”로 감싸기》)."""
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    outside_scripts = re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I)
    assert re.findall(r"\\u[0-9a-fA-F]{4}", outside_scripts) == []


def test_screen_libraries_are_served_locally_with_browser_mime_types(client):
    """PDF.js·d3·onnxruntime-web을 CDN이 아니라 static/vendor에서 내보낸다 — 인터넷 없는 첫 실행에서
    PDF가 뜨지 않았다. 모듈(.mjs)·wasm은 브라우저가 MIME을 따지므로 형식까지 본다(Windows는 .mjs가 text/plain이었다)."""
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    remote = re.findall(r"<script[^>]*\bsrc=\"(https?://[^\"]+)\"", html) + re.findall(r"<link[^>]*\bhref=\"(https?://[^\"]+)\"", html)
    assert remote == [], remote
    for js in ("pdf-renderer.js", "koten-layout-detector.js"):
        assert not re.search(r"https?://(cdn|cdnjs|unpkg|d3js)", (STATIC_JS / js).read_text(encoding="utf-8")), js
    want = {
        "vendor/pdfjs/pdf.min.js": "javascript", "vendor/pdfjs/pdf.worker.min.js": "javascript",
        "vendor/d3/d3.min.js": "javascript", "vendor/onnxruntime-web/ort.min.js": "javascript",
        "vendor/onnxruntime-web/ort-wasm-simd-threaded.mjs": "javascript",
        "vendor/onnxruntime-web/ort-wasm-simd-threaded.wasm": "application/wasm",
    }
    for path, kind in want.items():
        r = client.get("/static/" + path)
        assert r.status_code == 200, path
        assert kind in r.headers["content-type"], (path, r.headers["content-type"])
    for lic in ("pdfjs", "d3", "onnxruntime-web"):
        assert (_STATIC / "vendor" / lic / "LICENSE").is_file(), lic


@pytest.mark.parametrize("case", ["error_event", "no_complete", "not_sse"])
def test_fetch_with_sse_falls_back_only_before_the_stream_opens(tmp_path, case):
    """스트림이 열린 뒤 실패하면 폴백 URL로 같은 LLM 호출을 다시 보내지 않고 서버 오류 문구를 그대로 올린다.
    스트림이 열리기 전(SSE가 아닌 응답)에만 폴백한다. 예전에는 둘 다 폴백해 유료 모델이면 비용이 두 번 나갔다."""
    setup = f"""
const CASE = {json.dumps(case)};
const calls = [];
const enc = new TextEncoder();
function sse(events) {{
  const chunks = events.map((e) => enc.encode("data: " + JSON.stringify(e) + "\\n\\n"));
  let i = 0;
  return {{ getReader: () => ({{ read: async () => (i < chunks.length ? {{ done: false, value: chunks[i++] }} : {{ done: true }}) }}) }};
}}
globalThis.fetch = async (url) => {{
  calls.push(url);
  if (url === "/fallback") return {{ ok: true, json: async () => ({{ via: "fallback" }}) }};
  if (CASE === "not_sse") return {{ ok: false, status: 404, headers: {{ get: () => "application/json" }} }};
  const events = CASE === "error_event" ? [{{ type: "progress" }}, {{ type: "error", error: "모델 한도 초과" }}] : [{{ type: "progress" }}];
  return {{ ok: true, headers: {{ get: () => "text/event-stream" }}, body: sse(events) }};
}};
"""
    body = """
let out, err = null;
try { out = await fetchWithSSE("/stream", {}, null, "/fallback"); } catch (e) { err = e.message; }
console.log(JSON.stringify({ calls, out: out || null, err }));
"""
    r = run_js(tmp_path, "workspace.js", ["fetchWithSSE"], setup, body)
    if case == "not_sse":
        assert r["calls"] == ["/stream", "/fallback"] and r["out"] == {"via": "fallback"}
    else:
        assert r["calls"] == ["/stream"], r
        assert r["err"] and ("모델 한도 초과" in r["err"] if case == "error_event" else "결과 없이" in r["err"])


def test_page_ocr_result_is_not_drawn_on_another_page(tmp_path):
    """쪽 OCR 도중 다른 쪽으로 옮기면 끝난 결과를 지금 쪽 패널에 그리지 않는다(저장은 옛 쪽에 됐다)."""
    setup = """
const drawn = [];
globalThis.viewerState = { docId: "d", partId: "vol1", pageNum: 3 };
globalThis.ocrState = { running: false };
globalThis.layoutState = { blocks: [] };
globalThis.document = { getElementById: () => null };
globalThis.showToast = () => {};
globalThis._showProgress = () => {}; globalThis._disableButtons = () => {};
globalThis.getLlmModelSelection = () => ({});
globalThis._runOcrWithStreaming = async () => { viewerState.pageNum = 4; return { page: 3 }; };
globalThis.fetch = async () => ({ ok: true, json: async () => ({ page: 3 }) });
globalThis._displayResults = (r) => drawn.push(r);
"""
    out = run_js(tmp_path, "ocr-panel.js", ["_runOcr"], setup, "await _runOcr(null); console.log(JSON.stringify({ drawn }));")
    assert out["drawn"] == []


def test_part_ocr_direction_follows_the_profile():
    """권 전체 OCR의 전면 블록 방향이 세로 고정이 아니라 프로필을 따른다(레이아웃 편집기와 같은 규칙)."""
    src = (STATIC_JS / "ocr-panel.js").read_text(encoding="utf-8")
    assert 'writing_direction: "vertical_rtl",' not in src
    assert 'workspaceProfile === "extract" ? "horizontal_ltr" : "vertical_rtl"' in src


@pytest.mark.parametrize(("js_file", "fn", "quiet"), [
    ("citation-editor.js", "_loadCiteMarks", True),
    ("citation-editor.js", "_deleteCiteMark", False),
    ("annotation-editor.js", "_loadBlockAnnotations", True),
    ("annotation-editor.js", "_deleteAnnotation", False),
])
def test_no_request_to_a_default_interpretation_when_none_is_chosen(tmp_path, js_file, fn, quiet):
    """해석 저장소를 고르지 않았으면 《default》라는 없는 저장소로 요청하지 않는다. 동작(삭제 등)은 그 까닭을 알린다."""
    setup = """
const calls = []; const toasts = [];
globalThis.fetch = async (url) => { calls.push(url); return { ok: false, status: 404, json: async () => ({}) }; };
globalThis.showToast = (m) => toasts.push(m);
globalThis.confirm = () => true;
globalThis.viewerState = { docId: "d", partId: "vol1", pageNum: 1 };
globalThis.interpState = { interpId: null };
globalThis.annState = { selectedAnnId: "a1", annotations: [] }; globalThis.citeState = { marks: [], selectedMarkId: "c1" };
globalThis.document = { getElementById: () => null, querySelectorAll: () => [] };
globalThis.interpPartQuery = () => ""; globalThis._annPartQuery = () => ""; globalThis._annApiBlockId = () => "u1";
"""
    out = run_js(tmp_path, js_file, [fn], setup,
                 f'try {{ await {fn}("c1"); }} catch (e) {{}} console.log(JSON.stringify({{ calls, toasts }}));')
    assert not any("/interpretations/default/" in c for c in out["calls"]), out["calls"]
    assert (out["toasts"] == []) is quiet, out["toasts"]


def test_snapshot_entities_without_id_do_not_overwrite_each_other(tmp_path):
    """id 없는 엔티티 둘을 들이면 파일 둘이 생긴다 — 예전에는 둘 다 unknown.json에 써져 하나만 남았다."""
    from core.snapshot import create_work_from_snapshot

    lib = tmp_path / "lib"
    lib.mkdir()
    data = {
        "schema_version": "1.0",
        "source_info": {"title": "t", "document_id": "doc", "interpretation_id": "interp"},
        "original": {"layers": {}},
        "interpretation": {"layers": {}, "core_entities": {"concept": [{"label": "甲"}, {"label": "乙"}]}},
    }
    out = create_work_from_snapshot(lib, data)
    files = list((lib / "interpretations" / out["interp_id"] / "core_entities" / "concept").glob("*.json"))
    labels = sorted(json.loads(f.read_text(encoding="utf-8"))["label"] for f in files)
    assert labels == ["乙", "甲"] and not any(f.stem == "unknown" for f in files)
    assert sum("새 id" in w for w in out["warnings"]) == 2


def test_layout_reset_reports_a_failed_save(tmp_path):
    """레이아웃 《모두 삭제》의 저장이 실패하면 알린다 — 예전 _saveLayout은 실패를 삼켜 알림이 닿지 않았다."""
    setup = """
const toasts = [];
globalThis.viewerState = { docId: "d", partId: "vol1", pageNum: 1 };
globalThis.layoutState = { blocks: [{ block_id: "p01_b01" }], imageWidth: 100, imageHeight: 100 };
globalThis.pdfState = {};
globalThis.confirm = () => true;
globalThis.showToast = (m, k) => toasts.push(k);
globalThis.fetch = async () => ({ ok: false, json: async () => ({ error: "디스크 가득" }) });
for (const f of ["_updateLayoutSaveStatus", "_redrawOverlay", "_updatePropsForm", "_updateBlockList"]) globalThis[f] = () => {};
"""
    out = run_js(tmp_path, "layout-editor.js", ["_saveLayout", "_resetAllBlocks"], setup,
                 "await _resetAllBlocks(); console.log(JSON.stringify({ toasts }));")
    assert "error" in out["toasts"]


def test_no_docstring_is_separated_from_its_function():
    """설명이 주인 함수에서 떨어지지 않았는가 — 떨어지면 읽는 사람이 엉뚱한 함수의 설명으로 읽는다.
    잡는 꼴 둘: JS 《함수 설명 뒤에 또 설명》, Python 《첫 문장 뒤의 설명 문자열》. 설명과 함수 사이에 변수가
    끼인 꼴은 그 설명이 변수의 것인지 함수의 것인지 기계로 가르지 못해(변수 설명이 정상인 자리가 있다)
    읽어서 고쳤다(work-order). 다른 함수 설명이 걸린 꼴도 같다(composition-editor).
    2026-10-11 전수·보충에서 원래 일곱, 새로 넣은 도우미가 만든 다섯을 고쳤다."""
    bad = []
    for f in STATIC_JS.glob("*.js"):
        lines = f.read_text(encoding="utf-8").splitlines()
        nb = [i for i, ln in enumerate(lines) if ln.strip()]  # 빈 줄을 뺀 줄 번호
        for k, i in enumerate(nb[:-1]):
            if lines[i].strip() != "*/" or not lines[nb[k + 1]].startswith("/**"):
                continue
            # 앞 블록이 어디서 열렸나 — 절 머리말(/* ─)이나 파일 머리말(첫 줄)이면 정상이다
            opener = next(j for j in range(i, -1, -1) if lines[j].lstrip().startswith("/*"))
            if lines[opener].startswith("/**") and opener > 0:
                bad.append(f"{f.name}:{nb[k + 1] + 1} 설명 뒤에 또 설명")
    # Python: 함수·클래스 본문의 첫 문장이 설명이 아닌데 바로 뒤(다음 def 전 세 줄 안)에 설명 꼴 문자열이
    # 있으면 그 문자열은 __doc__가 아니라 버려지는 식이다(composition.py·rule_induction.py, 2026-10-11 보충)
    for f in (Path("src")).rglob("*.py"):
        lines = f.read_text(encoding="utf-8").splitlines()
        for i, ln in enumerate(lines):
            if not (re.match(r"\s*(async def|def|class) ", ln) and ln.rstrip().endswith(":")):
                continue
            body = [j for j in range(i + 1, min(i + 6, len(lines))) if lines[j].strip()]
            if not body or lines[body[0]].strip().startswith(('"""', 'r"""')):
                continue
            ind = len(lines[body[0]]) - len(lines[body[0]].lstrip())
            for j in body[1:4]:
                if re.match(r"\s*(async def|def|class|@)", lines[j]):
                    break
                if lines[j].strip().startswith('"""') and len(lines[j]) - len(lines[j].lstrip()) == ind:
                    bad.append(f"{f.as_posix()}:{j + 1} 첫 문장 뒤의 설명 문자열")
                    break
    assert bad == [], bad


def test_toast_escape_blocks_quotes():
    """toast.js의 escapeHtml은 즉시 실행 함수 안에 있어 위 시험이 잡지 못한다 — 같은 규칙을 소스로 본다."""
    src = (STATIC_JS / "toast.js").read_text(encoding="utf-8")
    m = re.search(r"function escapeHtml\(text\)\s*\{(.*?)\n  \}", src, re.S)
    assert m and '"/g' in m.group(1) and "'/g" in m.group(1), "toast.js escapeHtml이 따옴표를 막지 않는다"


# ── 2차 전수(S-20261011-185238)가 찾은 셋 — 스냅샷 경로·폴더 배치 이어 하기·Paddle 워커 시간 제한 ──
def _evil_snapshot(field: str) -> dict:
    """한 자리에만 `../`를 넣은 스냅샷. field가 어느 자리인지 고른다."""
    esc = "../../escaped"
    data = {
        "schema_version": "1.0",
        "source_info": {"title": "t", "document_id": "doc", "interpretation_id": "interp"},
        "original": {"layers": {}},
        "interpretation": {"layers": {}},
    }
    o, i = data["original"]["layers"], data["interpretation"]["layers"]
    if field == "document_id":
        data["source_info"]["document_id"] = esc
    elif field == "l3_part":
        o["L3_layout"] = {"type": "inline", "pages": [{"part_id": esc, "page_number": 1, "blocks": []}]}
    elif field == "l4_file":
        o["L4_text"] = {"type": "inline", "pages": [{"file_name": "../../escaped.txt", "text": "x"}]}
    elif field == "boundary_part":
        o["boundaries"] = {"type": "inline", "parts": [{"part_id": esc, "boundaries": []}]}
    elif field == "read_plan":
        o["read_plan"] = {"type": "inline", "parts": {esc: {}}}
    elif field == "source_path":
        i["L5_punctuation"] = [{"_source_path": "../../escaped.json", "block_id": "b"}]
    elif field == "entity_type":
        data["interpretation"]["core_entities"] = {esc: [{"id": "e1"}]}
    elif field == "entity_id":
        data["interpretation"]["core_entities"] = {"concept": [{"id": esc}]}
    return data


_EVIL_FIELDS = ["document_id", "l3_part", "l4_file", "boundary_part", "read_plan", "source_path", "entity_type", "entity_id"]


@pytest.mark.parametrize("field", _EVIL_FIELDS)
def test_snapshot_paths_that_escape_the_library_are_refused(tmp_path, field):
    """스냅샷의 이름에 `../`가 있으면 검증이 막고(라우트는 422), 들이기 함수도 아무것도 쓰지 않는다.
    전에는 `_source_path`·file_name·part·엔티티 id·document_id를 검사 없이 경로로 썼다 — 폴더 가져오기에만 검사가 있었다."""
    from core.snapshot import create_work_from_snapshot
    from core.snapshot_validator import validate_snapshot

    lib = tmp_path / "a" / "b" / "lib"
    lib.mkdir(parents=True)
    data = _evil_snapshot(field)
    errors, _ = validate_snapshot(data)
    assert errors, f"{field}: 검증이 막지 않았다"
    with pytest.raises(ValueError):
        create_work_from_snapshot(lib, data)
    escaped = [p for p in tmp_path.rglob("*escaped*")]
    assert escaped == [], escaped
    assert not (lib / "documents").exists() or not any((lib / "documents").iterdir())


def test_snapshot_with_ordinary_names_still_imports(tmp_path):
    """검사가 정상 스냅샷까지 막지 않는다 — 평범한 이름(vol1·page 파일·엔티티 id)은 그대로 들어간다."""
    from core.snapshot import create_work_from_snapshot
    from core.snapshot_validator import validate_snapshot

    data = {
        "schema_version": "1.0",
        "source_info": {"title": "t", "document_id": "doc" + "x" * 60, "interpretation_id": "interp"},
        "original": {"layers": {"L4_text": {"type": "inline", "pages": [{"file_name": "vol1_page_001.txt", "text": "x"}]}}},
        "interpretation": {"layers": {}, "core_entities": {"concept": [{"id": "c_1"}]}},
    }
    errors, _ = validate_snapshot(data)
    assert errors == [], errors
    lib = tmp_path / "lib"
    lib.mkdir()
    out = create_work_from_snapshot(lib, data)
    from core.repo_id import is_valid_repo_id

    # 원래 id가 길어도 새 id(+ 시각 15자)가 저장소 id 규칙(64자)을 넘지 않는다
    assert is_valid_repo_id(out["doc_id"]), out["doc_id"]
    assert (lib / "documents" / out["doc_id"] / "L4_text" / "pages" / "vol1_page_001.txt").exists()


def test_embed_folder_doc_id_is_stable_per_file(tmp_path):
    """폴더 배치 OCR의 문헌 id는 원본 파일로 정해진다 — 중단 뒤 다시 돌리면 같은 편이 같은 id라 이어 한다.
    전에는 《시각 + 순번》이라 다시 돌릴 때마다 처음부터 했다(이어 하기 코드가 한 번도 맞지 않았다)."""
    import inspect

    from cli import embed_folder as ef
    from core.repo_id import is_valid_repo_id

    a, b = tmp_path / "가.pdf", tmp_path / "나.pdf"
    ida, ida2, idb = ef._safe_doc_id(a), ef._safe_doc_id(a), ef._safe_doc_id(b)
    assert ida == ida2 and ida != idb
    assert is_valid_repo_id(ida) and is_valid_repo_id(idb)
    loop = inspect.getsource(ef.embed_folder)
    assert "_safe_doc_id(task.path)" in loop and "time.time() * 10" not in loop

    # 같은 자리에 다른 스캔을 덮어 두면 다른 id — 옛 OCR을 이어 쓰지 않는다
    real = tmp_path / "논문.pdf"
    real.write_bytes(b"%PDF-1 first scan")
    first = ef._safe_doc_id(real)
    assert ef._safe_doc_id(real) == first
    real.write_bytes(b"%PDF-1 a different, longer scan")
    assert ef._safe_doc_id(real) != first


def test_paddle_worker_call_honours_its_timeout():
    """워커가 답하지 않으면 timeout초 뒤 실패로 돌아온다 — 전에는 timeout을 받기만 하고 끝없이 기다렸다."""
    import subprocess
    import sys
    import threading

    from ocr.base import OcrEngineError
    from ocr.paddleocr_engine import PaddleOcrEngine

    stuck = subprocess.Popen(
        [sys.executable, "-c", "import sys, time; sys.stdin.readline(); time.sleep(60)"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8",
    )
    eng = PaddleOcrEngine.__new__(PaddleOcrEngine)
    eng._worker_lock = threading.Lock()
    eng._worker = stuck
    eng._worker_python = sys.executable
    box: dict = {}

    def call():
        try:
            box["out"] = eng._worker_call({"op": "ping"}, timeout=1)
        except Exception as e:  # noqa: BLE001
            box["err"] = e

    t = threading.Thread(target=call, daemon=True)
    try:
        t.start()
        t.join(15)
        assert not t.is_alive(), "timeout=1인데 15초가 지나도 돌아오지 않았다"
        assert isinstance(box.get("err"), OcrEngineError), box
        try:  # kill() 직후의 poll()은 아직 None일 수 있다 — 끝나기를 잠깐 기다린다
            stuck.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pytest.fail("멈춘 워커를 끄지 않았다(60초 sleep 중인 채로 남았다)")
    finally:
        if stuck.poll() is None:
            stuck.kill()
        w = getattr(eng, "_worker", None)
        if w is not None and w is not stuck and w.poll() is None:
            w.kill()


# ── 보충 재확인(바뀐 80파일, 2026-10-11 밤) — B-067~ ─────────────────────────────────────


def test_pick_from_correction_char_without_corrected_text(tmp_path):
    """B-067: 교정본이 빈 문자열일 때 《찍기》 미리보기가 원문으로 보인다. 전에는 정의되지 않은 `raw`로 ReferenceError."""
    setup = """
const form = { querySelector: (s) => (globalThis._f[s] = globalThis._f[s] || { value: "", textContent: "" }) };
globalThis._f = {};
globalThis.contentsState = { picking: true, pickForm: form };
globalThis.correctionState = { pageText: "甲乙\\n丙丁", correctedText: "", corrections: [] };
globalThis.viewerState = { pageNum: 1 };
globalThis._drawAnchorCanvas = () => {}; globalThis._markPicked = () => {};
"""
    out = run_js(tmp_path, "contents-tree.js", ["pickBoundaryFromCorrectionChar"], setup,
                 'const ok = pickBoundaryFromCorrectionChar(3); console.log(JSON.stringify({ ok, hint: _f[".contents-pick-hint"].textContent }));')
    assert out["ok"] is True
    assert "丙" in out["hint"], out


def test_backup_info_finds_the_subfolder_backup(tmp_path):
    """B-067: 고른 폴더에 다른 파일이 있어 하위 폴더에 백업하면 설정 화면의 《마지막 백업》도 그것을 읽는다."""
    from core.backup import backup_library, get_backup_info

    lib = _tiny_library(tmp_path)
    drive = tmp_path / "drive"
    drive.mkdir()
    (drive / "other.txt").write_text("x", encoding="utf-8")
    assert backup_library(lib, drive)["success"]
    assert get_backup_info(drive) is None  # 고른 폴더 자체에는 메타가 없다
    info = get_backup_info(drive, lib.name)
    assert info is not None and info.get("timestamp")


def test_interpretation_with_entities_or_citations_is_not_empty(tmp_path):
    """B-067: 엔티티·인용 표시·쪽 비고만 있는 해석 저장소도 《비었다》가 아니다 — 추출 모드 정리가 휴지통에 보내지 않는다."""
    from app.routers.interpretations import _interpretation_content_files

    for sub in ("core_entities/tags/t1.json", "citation_marks/vol1_page_001_citation_marks.json", "_notes/vol1/page_001.json"):
        root = tmp_path / sub.split("/")[0]
        f = root / sub
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{}", encoding="utf-8")
        assert _interpretation_content_files(root), sub


def test_trash_restore_retries_and_puts_the_item_back_in_the_manifest(tmp_path, monkeypatch):
    """B-068: 휴지통에서 되돌리면 library_manifest.json에 다시 적고, 잠겨 있으면 몇 번 다시 해 본 뒤 휴지통에 그대로 둔 채 알린다."""
    import json as _json

    import core.library as libmod

    lib = _tiny_library(tmp_path)
    doc = lib / "documents" / "doc1"
    doc.mkdir()
    (doc / "manifest.json").write_text(_json.dumps({"document_id": "doc1", "title": "제목"}), encoding="utf-8")
    (lib / "library_manifest.json").write_text(_json.dumps({"documents": [{"document_id": "doc1", "title": "제목"}]}), encoding="utf-8")
    name = libmod.trash_document(lib, "doc1")["trash_name"]
    assert _json.loads((lib / "library_manifest.json").read_text(encoding="utf-8"))["documents"] == []

    tries = []
    real_rename = libmod.os.rename

    def locked(src, dst):
        tries.append(1)
        raise PermissionError("잠김")

    monkeypatch.setattr(libmod.time, "sleep", lambda s: None)
    monkeypatch.setattr(libmod.os, "rename", locked)
    with pytest.raises(PermissionError):
        libmod.restore_from_trash(lib, "documents", name)
    assert len(tries) > 1, "한 번만 해 보고 포기했다"
    assert (lib / ".trash" / "documents" / name).exists()

    monkeypatch.setattr(libmod.os, "rename", real_rename)
    assert libmod.restore_from_trash(lib, "documents", name) == "doc1"
    docs = _json.loads((lib / "library_manifest.json").read_text(encoding="utf-8"))["documents"]
    assert [d["document_id"] for d in docs] == ["doc1"] and docs[0]["title"] == "제목"


def test_trash_routes_report_a_locked_folder_as_409_once(client, monkeypatch, tmp_path):
    """B-068: 잠긴 폴더의 휴지통 보내기·되돌리기는 500이 아니라 409, 안내는 한 번만 실린다."""
    import app.routers.documents as docs_r
    import app.routers.interpretations as interp_r
    import app.routers.library as lib_r

    for mod in (docs_r, interp_r, lib_r):  # 《서고 없음》 409로 먼저 빠지지 않게
        monkeypatch.setattr(mod, "get_library_path", lambda: tmp_path)

    msg = "'x'을(를) 휴지통으로 옮기지 못했습니다 — …\n→ 해결: 닫고 다시"

    def boom(*a, **k):
        raise PermissionError(msg)

    monkeypatch.setattr(interp_r, "trash_interpretation", boom)
    monkeypatch.setattr(docs_r, "trash_document", boom)
    monkeypatch.setattr(lib_r, "restore_from_trash", boom)
    r1 = client.delete("/api/interpretations/x")
    r2 = client.delete("/api/documents/x")
    r3 = client.post("/api/trash/documents/20260101T000000_x/restore")
    for r in (r1, r2, r3):
        assert r.status_code == 409, (r.status_code, r.text)
        assert r.json()["error"].count("해결") == 1


def test_correction_reset_rolls_back_when_the_save_fails(tmp_path):
    """B-069: 리셋 저장이 실패하면 상태·편집 칸을 리셋 전으로 되돌린다 — 화면은 옛 교정인데 상태는 비어 다음 저장이 지우던 것."""
    setup = """
const ta = { value: "고친 글" };
globalThis.document = { getElementById: (id) => (id === "corr-freetext-editor" ? ta : null) };
globalThis.viewerState = { docId: "d", partId: "v", pageNum: 1 };
globalThis.correctionState = { corrections: [{ id: 1 }], correctedText: "고친 글", pageText: "원문", isDirty: false };
globalThis.confirm = () => true; const toasts = []; globalThis.showToast = (m) => toasts.push(m);
globalThis._saveCorrections = async () => false;
globalThis._renderCorrectionView = () => {}; globalThis._renderCorrList = () => {}; globalThis._updateCorrCount = () => {};
"""
    out = run_js(tmp_path, "correction-editor.js", ["_resetAllCorrections"], setup,
                 "await _resetAllCorrections(); console.log(JSON.stringify({ n: correctionState.corrections.length, t: correctionState.correctedText, ta: ta.value, toasts }));")
    assert out["n"] == 1 and out["t"] == "고친 글" and out["ta"] == "고친 글", out
    assert out["toasts"], "실패를 알리지 않았다"


def test_split_and_delete_report_partial_failure(tmp_path):
    """B-069: 서버가 207(일부 실패)을 주면 쪼개기·단위 삭제가 《완료》라 하지 않고 오류를 알린다."""
    setup = """
const toasts = []; const status = [];
globalThis.showToast = (m, kind) => toasts.push(kind + ":" + m);
globalThis._updateCompStatus = (m) => status.push(m);
globalThis.viewerState = { docId: "d", partId: "v" };
globalThis.compState = { selectedTb: { id: "u1" }, selectedTbId: "u1", units: [] };
globalThis.document = { getElementById: () => ({ value: "가\\n===\\n나\\n===\\n다" }) };
globalThis._parseSplitPieces = (v) => v.split("===");
globalThis._cancelSplit = () => {}; globalThis._loadCompositionData = async () => {};
globalThis.refreshContentsTree = async () => {}; globalThis.confirm = () => true;
globalThis.fetch = async () => ({ ok: true, status: 207, json: async () => ({ created_count: 1, errors: ["조각 2: 못 찾음"] }) });
"""
    out = run_js(tmp_path, "composition-editor.js", ["_executeSplit", "_deleteUnit"], setup,
                 "await _executeSplit(); await _deleteUnit({ id: 'u1', sequence_index: 1, original_text: '가' }); console.log(JSON.stringify({ toasts, status }));")
    assert any("일부 실패" in t and "조각 2" in t for t in out["toasts"]), out
    assert not any("쪼개기 완료" in s for s in out["status"])
    assert any(t.startswith("error:삭제 실패") for t in out["toasts"]), out
    assert not any("삭제 완료" in s for s in out["status"]), out


def test_annotation_card_type_is_escaped():
    """B-069: 주석 카드의 유형 아이콘·이름·색(사용자 정의 유형 포함)이 이스케이프된다."""
    src = (STATIC_JS / "annotation-editor.js").read_text(encoding="utf-8")
    assert "${typeInfo.icon} ${typeInfo.label}" not in src
    assert 'style="color:${_escAttr(typeInfo.color)}">${_escHtml(typeInfo.icon)} ${_escHtml(typeInfo.label)}' in src


def test_pdf_load_failure_keeps_the_canvas(tmp_path):
    """B-070: PDF를 못 열면 안내만 얹고 캔버스는 숨긴다 — 전에는 컨테이너를 통째로 바꿔 다른 문헌의 PDF도 그려지지 않았다."""
    src = (STATIC_JS / "pdf-renderer.js").read_text(encoding="utf-8")
    assert "container.innerHTML =" not in src.split("async function loadPdfPage(")[1].split("\n}\n")[0]
    setup = """
const kids = []; const wrapper = { hidden: false };
const container = { appendChild: (n) => kids.push(n) };
globalThis.document = {
  getElementById: (id) => id === "pdf-canvas-container" ? container : id === "pdf-canvas-wrapper" ? wrapper
    : (id === "pdf-load-failed" ? kids.find((k) => k.id === id) || null : null),
  createElement: () => ({ style: {}, hidden: false }),
};
"""
    out = run_js(tmp_path, "pdf-renderer.js", ["_showPdfLoadFailed"], setup,
                 "_showPdfLoadFailed(true); const a = [wrapper.hidden, kids.length]; _showPdfLoadFailed(false); console.log(JSON.stringify({ a, b: [wrapper.hidden, kids[0].hidden, kids.length] }));")
    assert out["a"] == [True, 1] and out["b"] == [False, True, 1], out


def test_notes_save_waits_for_the_running_save(tmp_path):
    """B-070: 비고 저장이 도는 중에 다음 저장이 오면 기다렸다가 저장한다 — 전에는 그냥 돌아가 편집이 사라졌다."""
    setup = """
const puts = []; let release;
globalThis.fetch = (url, opt) => { puts.push(JSON.parse(opt.body).entries.map((e) => e.text).join());
  return puts.length === 1 ? new Promise((r) => { release = () => r({ ok: true }); }) : Promise.resolve({ ok: true }); };
globalThis.document = { getElementById: () => null };
globalThis.notesState = { saving: false, savingPromise: null, entries: [] };
"""
    out = run_js(tmp_path, "notes-panel.js", ["_saveNotes"], setup, """
const first = _saveNotes({ interpId: "i", partId: "v", pageNum: 1, entries: [{ text: "가" }] });
const second = _saveNotes({ interpId: "i", partId: "v", pageNum: 2, entries: [{ text: "나" }] });
await new Promise((r) => setTimeout(r, 10)); release(); await first; await second;
console.log(JSON.stringify({ puts }));""")
    assert out["puts"] == ["가", "나"], out


def test_screen_text_matches_behaviour():
    """B-071: 화면 문구·입력칸이 실제 동작과 맞는다 — URL 모드 ID 자동, 확장 한자 한 글자, 위 바 쪽 번호, 해시 복원 프로필, 내보내기 단추 글자."""
    html = (STATIC_JS.parent / "index.html").read_text(encoding="utf-8")
    assert 'id="batch-original-char" maxlength' not in html and 'id="batch-corrected-char" maxlength' not in html
    assert "Array.from(originalChar).length !== 1" in (STATIC_JS / "batch-correction.js").read_text(encoding="utf-8")
    assert "_previewData.suggested_doc_id" in (STATIC_JS / "create-document.js").read_text(encoding="utf-8")
    ws = (STATIC_JS / "workspace.js").read_text(encoding="utf-8")
    on_page = ws.split("function onPageChanged(")[1].split("\n}\n")[0]
    assert "updateModeBarContext()" in on_page
    restore = ws.split("async function _restoreFromHash(")[1].split("\n}\n")[0]
    assert "applyProfileForDocument(target.docId)" in restore
    assert 'exportBtn.textContent = "JSON 내보내기"' in ws


def test_zip_copy_with_an_old_mark_keeps_differing_files(tmp_path, monkeypatch):
    """B-072: 지문 없는 옛 zip 표시면 덮기 전에 원격과 다른 파일을 설정 폴더에 남긴다 — 전에는 《고친 것 없음》으로 읽고 덮었다."""
    import subprocess as _sp

    import core.app_config as cfg
    import core.updater as up

    root = tmp_path / "app"
    root.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    import os as _os

    e = {**_os.environ, **env}
    _sp.run(["git", "init", "-q"], cwd=root, check=True, env=e)
    (root / "a.txt").write_text("원래", encoding="utf-8")
    _sp.run(["git", "add", "a.txt"], cwd=root, check=True, env=e)
    _sp.run(["git", "commit", "-qm", "x"], cwd=root, check=True, env=e)
    (root / "a.txt").write_text("손으로 고침", encoding="utf-8")
    (root / up.ZIP_MARK).write_text("converted from zip\n", encoding="utf-8")
    assert up.zip_user_changes(root) is None
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path / "cfg")
    kept = up._keep_zip_files(root)
    assert kept is not None and (kept / "a.txt").read_text(encoding="utf-8") == "손으로 고침"
    src = Path(up.__file__).read_text(encoding="utf-8")
    assert "elif changed is None:" in src and "_keep_zip_files()" in src


def test_llm_cost_and_ollama_retry_window():
    """B-072: 쓸 수 없는 ChatGPT 계정도 《구독》(무료 아님, D-056), Ollama가 사고를 켜 다시 부를 때 문맥 창도 다시 잰다."""
    router = (Path("src") / "llm" / "router.py").read_text(encoding="utf-8")
    assert '"free" if provider.provider_id in ("ollama", "openai_oauth")' not in router
    oll = (Path("src") / "llm" / "providers" / "ollama.py").read_text(encoding="utf-8")
    assert "_gen_options(max_tokens + budget" in oll


def test_bibliography_source_link_is_http_only(tmp_path):
    """B-073: 서지의 원본 주소는 http(s)만 링크가 된다. 판식 값은 이스케이프한다."""
    out = run_js(tmp_path, "bibliography.js", ["_formatDigitalSource", "_escapeHtmlBibliography"], _DOM_STUB,
                 'console.log(JSON.stringify({ bad: _formatDigitalSource({ platform: "p", source_url: "javascript:alert(1)" }), good: _formatDigitalSource({ platform: "p", source_url: "https://x.org/a" }) }));')
    assert "<a " not in out["bad"] and "javascript:alert(1)" in out["bad"]
    assert 'href="https://x.org/a"' in out["good"]
    src = (STATIC_JS / "bibliography.js").read_text(encoding="utf-8")
    pansik = src.split("function _formatPansik(")[1].split("\n}\n")[0]
    assert "_escapeHtmlBibliography(String(v))" in pansik and "<br>원문:" in pansik


def test_server_autodetect_asks_and_ignores_a_moved_page(tmp_path):
    """B-074: 서버 엔진 자동 감지도 기존 블록을 덮기 전에 묻고, 감지 중 쪽을 옮기면 결과를 버린다. 0건이면 기존 블록을 그대로 둔다."""
    base = """
globalThis.viewerState = { docId: "d", partId: "v", pageNum: 1 };
globalThis.layoutState = { blocks: [{ block_id: "p01_b01" }], isDirty: false };
globalThis.document = { getElementById: () => null };
globalThis.showToast = () => {}; const st = []; globalThis._setAutodetectStatus = (m) => st.push(m);
globalThis.pdfState = { pdfDoc: { getPage: async () => ({}) } }; globalThis.pdfViewport = () => ({ width: 100, height: 100 });
globalThis._redrawOverlay = () => {}; globalThis._updateBlockList = () => {}; globalThis._saveLayout = async () => true;
globalThis.performance = { now: () => 0 };
"""
    moved = base + """globalThis.confirm = () => true;
globalThis.fetch = async () => { viewerState.pageNum = 2; return { ok: true, json: async () => ({ blocks: [{ bbox: [0,0,1,1] }], image_width: 100, image_height: 100, block_count: 1 }) }; };"""
    out = run_js(tmp_path, "layout-editor.js", ["_runAutoDetectServer", "_layoutStillOn", "_confirmReplaceBlocks"], moved,
                 "await _runAutoDetectServer('ndlocr'); console.log(JSON.stringify({ ids: layoutState.blocks.map((b) => b.block_id), st }));")
    assert out["ids"] == ["p01_b01"], out
    declined = base + """let asked = 0; globalThis.confirm = () => { asked++; return false; };
globalThis.fetch = async () => ({ ok: true, json: async () => ({ blocks: [{ bbox: [0,0,1,1] }], image_width: 100, image_height: 100, block_count: 1 }) });"""
    (tmp_path / "b").mkdir()
    out = run_js(tmp_path / "b", "layout-editor.js", ["_runAutoDetectServer", "_layoutStillOn", "_confirmReplaceBlocks"], declined,
                 "await _runAutoDetectServer('ndlocr'); console.log(JSON.stringify({ ids: layoutState.blocks.map((b) => b.block_id), asked }));")
    assert out == {"ids": ["p01_b01"], "asked": 1}, out
    empty = base + """globalThis.confirm = () => true;
globalThis.fetch = async () => ({ ok: true, json: async () => ({ blocks: [], image_width: 100, image_height: 100, block_count: 0 }) });"""
    (tmp_path / "c").mkdir()
    out = run_js(tmp_path / "c", "layout-editor.js", ["_runAutoDetectServer", "_layoutStillOn", "_confirmReplaceBlocks"], empty,
                 "await _runAutoDetectServer('ndlocr'); console.log(JSON.stringify({ ids: layoutState.blocks.map((b) => b.block_id), dirty: layoutState.isDirty }));")
    assert out == {"ids": ["p01_b01"], "dirty": False}, out


def test_llm_correction_draft_is_not_drawn_on_another_page(tmp_path):
    """B-074: LLM 교정 도중 쪽을 옮기면 옛 쪽 초안을 지금 쪽에 그리지 않는다(「적용」이 지금 쪽으로 가던 것)."""
    setup = """
const drawn = [];
globalThis.viewerState = { docId: "d", partId: "v", pageNum: 3 };
globalThis.document = { getElementById: () => null, querySelectorAll: () => [] };
globalThis.showToast = () => {}; globalThis.getLlmModelSelection = () => ({});
globalThis.fetch = async () => { viewerState.pageNum = 4; return { ok: true, json: async () => ({ blocks: [] }) }; };
globalThis._renderCorrectionDraft = (d) => drawn.push(d);
globalThis._showProgress = () => {}; globalThis._disableButtons = () => {}; globalThis.ocrState = {};
"""
    out = run_js(tmp_path, "ocr-panel.js", ["_runCorrection"], setup, "await _runCorrection('low', null); console.log(JSON.stringify({ drawn }));")
    assert out["drawn"] == []


def test_ai_translation_reports_a_failed_save(tmp_path):
    """B-075: AI 번역을 받고 저장(PUT·추가)이 실패하면 false — 일괄 번역이 《실패 0건》으로 보고하던 것."""
    setup = """
globalThis.transState = { sentences: [{ start: 0, end: 1, text: "甲" }], translations: [], blockId: "u1" };
globalThis.interpState = { interpId: "i" }; globalThis.viewerState = { docId: "d", partId: "v", pageNum: 1 };
globalThis.document = { querySelectorAll: () => [] }; globalThis.confirm = () => true;
const toasts = []; globalThis.showToast = (m) => toasts.push(m);
globalThis.fetchWithSSE = async () => ({ translation: "번역" });
globalThis._findTranslation = () => null; globalThis.interpPartQuery = () => ""; globalThis._transApiBlockId = () => "u1";
globalThis._renderTransCards = () => {}; globalThis._renderTransStatusSummary = () => {};
globalThis.fetch = async () => ({ ok: false, status: 500, json: async () => ({ error: "디스크" }) });
"""
    out = run_js(tmp_path, "translation-editor.js", ["_aiTranslateSingle", "_addManualTranslation"], setup,
                 "const r = await _aiTranslateSingle(0); console.log(JSON.stringify({ r, toasts }));")
    assert out["r"] is False and any("디스크" in t for t in out["toasts"]), out


def test_dict_layer_json_save_returns_its_size(tmp_path):
    """B-075: 해석 층에 dict JSON을 저장하면 크기를 돌려준다 — 전에는 UnboundLocalError로 라우트가 400, git 커밋을 건너뛰었다."""
    from core.interpretation import save_layer_content

    out = save_layer_content(tmp_path, "L7_annotation", "", "vol1", 1, {"blocks": []})
    assert out["status"] == "saved" and out["size"] > 0


def test_snapshot_entity_with_empty_id_gets_a_new_id_instead_of_422():
    """B-075: id가 빈 엔티티는 경로 검사에 걸리지 않는다 — 들일 때 새 UUID를 붙인다(B-063과 같은 길)."""
    from core.snapshot import unsafe_snapshot_paths

    data = {"original": {"layers": {}}, "interpretation": {"core_entities": {"tags": [{"id": ""}, {"label": "x"}]}}}
    assert not [p for p in unsafe_snapshot_paths(data) if "엔티티 id" in p]


def test_env_reader_refuses_non_korean_8bit_and_llm_config_reads_cp949(tmp_path):
    """B-076: .env를 cp949로 읽는 것은 한글일 때만 — 라틴 문자 8비트 파일을 cp949로 오해해 다시 쓰면 글자가 바뀐다.
    LLM 설정도 설정 화면과 같은 판독으로 한글 cp949 .env를 읽는다."""
    from core.env_settings import _read_lines_for_write
    from llm.config import LlmConfig

    latin = tmp_path / "latin.env"
    latin.write_bytes("# café\nX=1\n".encode("latin-1"))
    with pytest.raises(ValueError):
        _read_lines_for_write(latin)
    ko = tmp_path / "ko.env"
    ko.write_bytes("# 주석\nMY_NAME=홍길동\n".encode("cp949"))
    assert _read_lines_for_write(ko)[1] == "MY_NAME=홍길동"
    assert LlmConfig._load_dotenv(LlmConfig.__new__(LlmConfig), ko).get("MY_NAME") == "홍길동"


def test_small_ui_fixes_are_in_place():
    """B-076: 지역 이스케이프도 작은따옴표까지, 쪽 수만 세는 PDF 열기는 통째로 받지 않음, 레이아웃 교정 배지 배경, 토스트 줄바꿈."""
    assert """"'": "&#39;" """.strip() in (STATIC_JS / "ocr-panel.js").read_text(encoding="utf-8")
    assert "getDocument({ url, disableAutoFetch: true, disableStream: true })" in (STATIC_JS / "sidebar-tree.js").read_text(encoding="utf-8")
    css = (STATIC_JS.parent / "css" / "workspace.css").read_text(encoding="utf-8")
    assert ".corr-list-type.type-layout-correction {" in css
    assert "white-space: pre-line;" in css.split(".toast-message {")[1].split("}")[0]


_UTF16_SLICE = re.compile(r"\b(text|raw|meaning|snippet|original\w*|content|label|title|preview\w*|selectedText|source_text_snapshot)\w*\)?\.(slice|substring|substr)\(\s*0\s*,")


def test_display_previews_cut_by_code_points():
    """B-076: 화면에 보이려고 자르는 미리보기도 코드포인트로 자른다 — UTF-16으로 자르면 확장 한자 반쪽이 남는다."""
    bad = []
    for f in STATIC_JS.glob("*.js"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            # 《…Chars(text.substring(0, i))》는 정규식 위치(UTF-16)로 자른 뒤 코드포인트로 세는 올바른 꼴이다
            if _UTF16_SLICE.search(line) and "Array.from" not in line and "Chars(" not in line:
                bad.append(f"{f.name}:{n}: {line.strip()[:80]}")
    assert bad == [], bad


# ── B-078: 릴리스 리뷰(Codex, 2026-10-11)가 찾은 것 ─────────────────────────────


def _git_repo(path: Path, files: dict[str, str]) -> None:
    import os as _os
    import subprocess as _sp

    e = {**_os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    path.mkdir(parents=True, exist_ok=True)
    for args in (["init", "-q"], ["symbolic-ref", "HEAD", "refs/heads/main"]):
        _sp.run(["git", *args], cwd=path, check=True, env=e, capture_output=True)
    for rel, text in files.items():
        (path / rel).write_text(text, encoding="utf-8")
    _sp.run(["git", "add", "."], cwd=path, check=True, env=e, capture_output=True)
    _sp.run(["git", "commit", "-qm", "x"], cwd=path, check=True, env=e, capture_output=True)


def test_reset_hard_keeps_user_files_the_new_version_starts_tracking(tmp_path, monkeypatch):
    """B-078: zip에서 바꾼 뒤 사용자가 만든 파일을 새 판이 같은 경로로 추적하면, reset --hard 전에
    update-backup/에 남는다 — 전에는 지문에도 dirty 검사에도 안 걸려 묻지 않고 덮였다."""
    import shutil as _sh
    import subprocess as _sp

    import core.app_config as cfg
    import core.updater as up

    if _sh.which("git") is None:
        pytest.skip("git이 없다")
    origin = tmp_path / "origin"
    _git_repo(origin, {"app.py": "v1\n"})
    z = tmp_path / "zip"
    z.mkdir()
    (z / "app.py").write_text("v1\n", encoding="utf-8")
    assert up.ensure_git_checkout(z, remote=str(origin))["ok"]
    (z / "내메모.txt").write_text("사용자가 만든 파일", encoding="utf-8")   # 추적 밖, 한글 경로
    (origin / "내메모.txt").write_text("새 판의 파일", encoding="utf-8")
    _sp.run(["git", "add", "."], cwd=origin, check=True, capture_output=True)
    _sp.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "y"], cwd=origin, check=True, capture_output=True)
    _sp.run(["git", "fetch", "-q", "origin", "main"], cwd=z, check=True, capture_output=True)
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path / "cfg")
    steps: list[dict] = []
    up._note_kept_collisions(z, steps)
    assert steps and "update-backup" in steps[0]["output"], steps
    kept = list((tmp_path / "cfg" / "update-backup").rglob("내메모.txt"))
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == "사용자가 만든 파일"


def test_collision_backup_covers_folder_and_ancestor_shapes(tmp_path, monkeypatch):
    """B-078 재검토: 새 판의 파일 자리가 지금은 추적 밖 폴더이거나(그 안 파일이 지워진다),
    새 판 경로의 조상이 지금은 추적 밖 파일이어도(그 파일이 지워진다) 남긴다."""
    import shutil as _sh
    import subprocess as _sp

    import core.app_config as cfg
    import core.updater as up

    if _sh.which("git") is None:
        pytest.skip("git이 없다")
    origin = tmp_path / "origin"
    _git_repo(origin, {"app.py": "v1\n"})
    z = tmp_path / "zip"
    z.mkdir()
    (z / "app.py").write_text("v1\n", encoding="utf-8")
    assert up.ensure_git_checkout(z, remote=str(origin))["ok"]
    (z / "notes").mkdir()
    (z / "notes" / "user.md").write_text("폴더 안 사용자 파일", encoding="utf-8")
    (z / "docs").write_text("조상 자리의 사용자 파일", encoding="utf-8")
    (origin / "notes").write_text("새 판의 파일", encoding="utf-8")
    (origin / "docs").mkdir()
    (origin / "docs" / "new.md").write_text("새 판", encoding="utf-8")
    _sp.run(["git", "add", "."], cwd=origin, check=True, capture_output=True)
    _sp.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "y"], cwd=origin, check=True, capture_output=True)
    _sp.run(["git", "fetch", "-q", "origin", "main"], cwd=z, check=True, capture_output=True)
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path / "cfg")
    ok, kept = up._keep_untracked_collisions(z)
    assert ok and kept is not None
    assert (kept / "notes" / "user.md").read_text(encoding="utf-8") == "폴더 안 사용자 파일"
    assert (kept / "docs").read_text(encoding="utf-8") == "조상 자리의 사용자 파일"


def _fake_update_run(monkeypatch, up, *, lookup_ok=True, pull_fails=False):
    """_apply_update_locked가 부르는 git을 기록만 하는 가짜로 바꾼다. 출력: 부른 순서 목록."""
    calls: list[str] = []

    def fake_run(args, cwd, timeout):
        a = list(args)
        if a[:2] == ["git", "ls-tree"] or a[:2] == ["git", "ls-files"]:
            calls.append("lookup")
            return (0, "") if lookup_ok else (128, "fatal: 조회 실패")
        if a[:3] == ["git", "reset", "--hard"]:
            calls.append("reset")
            return 0, ""
        if a[:2] == ["git", "pull"]:
            calls.append("pull")
            return (1, "not possible to fast-forward") if pull_fails else (0, "")
        if a[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return 0, "main"
        if a[:2] == ["git", "rev-list"]:
            return 0, "0"
        calls.append(" ".join(a[:2]))
        return 0, ""

    monkeypatch.setattr(up, "_run", fake_run)
    return calls


@pytest.mark.parametrize("zip_mark", [True, False])
def test_collision_lookup_runs_before_each_reset_and_failure_stops_it(tmp_path, monkeypatch, zip_mark):
    """B-078 재검토: 두 reset --hard 자리(zip 사본 맞추기·pull 실패 뒤 맞추기) 모두 《덮일 파일 확인》이
    reset보다 먼저 돌고, 그 조회가 실패하면 reset 없이 멈춘다 — 전에는 실패를 《충돌 없음》으로 읽었다."""
    import core.updater as up

    root = tmp_path / "app"
    root.mkdir()
    if zip_mark:
        (root / up.ZIP_MARK).write_text("{}", encoding="utf-8")
    calls = _fake_update_run(monkeypatch, up, pull_fails=not zip_mark)
    r = up._apply_update_locked(root, [], lambda: ["uv", "sync"])
    assert r["ok"], r
    assert "reset" in calls and calls.index("lookup") < calls.index("reset"), calls

    if zip_mark:
        (root / up.ZIP_MARK).write_text("{}", encoding="utf-8")
    calls = _fake_update_run(monkeypatch, up, lookup_ok=False, pull_fails=not zip_mark)
    r = up._apply_update_locked(root, [], lambda: ["uv", "sync"])
    assert not r["ok"] and "reset" not in calls, (r, calls)
    assert any(s["name"] == "새 판이 덮을 파일 확인" and not s["ok"] for s in r["steps"])


def test_update_backups_in_the_same_second_do_not_overwrite_each_other(tmp_path, monkeypatch):
    """B-078 재검토: 같은 초에 두 번 남겨도 앞 백업이 덮이지 않는다 — 전에는 폴더 이름이 초 단위라 같은 폴더였다."""
    import datetime as _real_dt
    import sys as _sys
    import types as _types

    import core.app_config as cfg
    import core.updater as up

    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path / "cfg")
    # 시각을 고정한다 — 두 호출이 초 경계를 넘으면 옛 구현(초 단위 이름)도 통과해 버린다
    fixed = _real_dt.datetime(2026, 10, 11, 23, 59, 59)
    fake = _types.ModuleType("datetime")
    fake.datetime = type("FixedDT", (), {"now": staticmethod(lambda: fixed)})
    monkeypatch.setitem(_sys.modules, "datetime", fake)
    root = tmp_path / "app"
    root.mkdir()
    (root / "a.txt").write_text("A", encoding="utf-8")
    first = up._copy_to_update_backup(root, ["a.txt"])
    (root / "a.txt").write_text("B", encoding="utf-8")
    second = up._copy_to_update_backup(root, ["a.txt"])
    assert first != second
    assert (first / "a.txt").read_text(encoding="utf-8") == "A"
    assert (second / "a.txt").read_text(encoding="utf-8") == "B"


def test_old_zip_mark_backup_includes_staged_and_korean_paths(tmp_path, monkeypatch):
    """B-078: 지문 없는 옛 zip 표시의 백업이 `git add`한 수정과 한글 경로를 빠뜨리지 않는다 —
    전에는 `git diff --name-only`(index와 비교, 경로 따옴표)라 둘 다 빠졌다."""
    import os as _os
    import shutil as _sh
    import subprocess as _sp

    import core.app_config as cfg
    import core.updater as up

    if _sh.which("git") is None:
        pytest.skip("git이 없다")
    root = tmp_path / "app"
    _git_repo(root, {"a.txt": "원래", "해제.md": "원래"})
    (root / "a.txt").write_text("고쳐서 add함", encoding="utf-8")
    _sp.run(["git", "add", "a.txt"], cwd=root, check=True, env=_os.environ, capture_output=True)
    (root / "해제.md").write_text("손으로 고침", encoding="utf-8")
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path / "cfg")
    kept = up._keep_zip_files(root)
    assert kept is not None
    assert (kept / "a.txt").read_text(encoding="utf-8") == "고쳐서 add함"
    assert (kept / "해제.md").read_text(encoding="utf-8") == "손으로 고침"


def test_late_notes_response_is_not_drawn_on_another_page(tmp_path):
    """B-078: 3쪽 비고 응답이 4쪽으로 옮긴 뒤 늦게 오면 버린다 — 전에는 4쪽에 3쪽 비고를 그렸고,
    고치면 4쪽 파일에 3쪽 내용이 저장됐다."""
    setup = """
const gates = {};
globalThis.fetch = (url) => new Promise((res) => {
  const page = /pages\\/(\\d+)\\//.exec(url)[1];
  const reply = { ok: true, json: async () => ({ entries: [{ text: page + "쪽 비고" }] }) };
  if (page === "3") gates.p3 = () => res(reply); else res(reply);
});
const _el = () => ({ innerHTML: "", textContent: "" });
globalThis.document = { getElementById: () => _el() };
globalThis.interpState = { interpId: "i1" };
globalThis.viewerState = { partId: "vol1", pageNum: 3 };
globalThis.notesState = { entries: [], loaded: false, saveTimer: null, pendingTarget: null, saving: false };
globalThis._renderNotes = () => {};
"""
    body = """
const slow = loadPageNotes();                     // 3쪽 — 응답이 늦는다
await new Promise((r) => setTimeout(r, 10));
viewerState.pageNum = 4;
await loadPageNotes();                            // 4쪽 — 바로 온다
gates.p3(); await slow;                           // 이제야 3쪽 응답
console.log(JSON.stringify(notesState.entries));
"""
    out = run_js(tmp_path, "notes-panel.js", ["_notesInterpId", "_notesTarget", "_notesStillOn", "_flushNotesSave", "_saveNotes", "_scheduleSave", "loadPageNotes"], setup, body)
    assert out == [{"text": "4쪽 비고"}], out


def test_dictionary_save_keeps_every_section_of_the_same_book(tmp_path):
    """B-078: 같은 책의 다른 대목 둘(section·url만 다름)이 저장 뒤에도 둘 다 남는다 — 전에는 제목 하나에
    항목 하나라 마지막 대목이 둘로 복제되고 첫 대목이 사라졌다."""
    prev = {"headword": "王戎", "source_references": [
        {"title": "世說新語", "section": "德行", "url": "https://x/1"},
        {"title": "世說新語", "section": "雅量", "url": "https://x/2"}]}
    fields = {"ann-dict-headword": "王戎", "ann-dict-meaning": "뜻", "ann-dict-src-refs": "世說新語, 世說新語"}
    setup = (
        "let sent = null;\n"
        "globalThis.fetch = async (url, opt) => { sent = JSON.parse(opt.body); return { ok: true, json: async () => ({}) }; };\n"
        "const F = " + json.dumps(fields, ensure_ascii=False) + ";\n"
        "globalThis.document = { getElementById: (id) => (id in F ? { value: F[id] } : null) };\n"
        "globalThis.viewerState = { pageNum: 1 }; globalThis.interpState = { interpId: 'i1' };\n"
        "globalThis.annState = { selectedAnnId: 'a1', annotations: [{ id: 'a1', dictionary: " + json.dumps(prev, ensure_ascii=False) + " }] };\n"
        "globalThis._annApiBlockId = () => 'u1'; globalThis._annPartQuery = () => '';\n"
        "globalThis._showSaveStatus = () => {}; globalThis._loadBlockAnnotations = async () => {}; globalThis._renderAnnList = () => {};\n"
    )
    out = run_js(tmp_path, "annotation-editor.js", ["_saveDictFields"], setup, "await _saveDictFields(); console.log(JSON.stringify(sent));")
    assert out["dictionary"]["source_references"] == prev["source_references"]


# ── B-079: 시험 중복 정리(2026-10-12)에서 강화한 시험이 찾은 것 ─────────────────


@pytest.mark.parametrize("with_popups", [True, False])
def test_korcis_bibliography_saves_with_contents_and_abstracts(tmp_path, with_popups):
    """B-079: KORCIS 서지가 저장된다 — 매퍼는 목차(contents)·해제(abstracts)를 늘 싣는데 스키마에 그 칸이
    없어(additionalProperties: false) URL 가져오기가 매번 《서지정보 저장 실패》였다(2026-04-15부터)."""
    from core.document import save_bibliography
    from parsers.korcis import KorcisMapper
    from tests.test_korcis import sample_marc_data, sample_marc_with_openapi

    raw = sample_marc_with_openapi.__wrapped__(sample_marc_data.__wrapped__())
    if with_popups:
        raw["_contents_info"] = [{"title": "表紙", "page": "0"}, {"title": "海東諸國紀", "page": "1"}]
        raw["_abstracts_info"] = "『해동제국기』는 …"
    bib = KorcisMapper().map_to_bibliography(raw)
    save_bibliography(tmp_path, bib)
    saved = json.loads((tmp_path / "bibliography.json").read_text(encoding="utf-8"))
    if with_popups:
        assert saved["contents"] == [{"title": "表紙", "page": "0"}, {"title": "海東諸國紀", "page": "1"}]
        assert saved["abstracts"] == "『해동제국기』는 …"
    else:
        assert saved["contents"] is None and saved["abstracts"] is None


def test_every_mapper_output_key_is_in_the_bibliography_schema():
    """B-079 같은 종류: 서지 매퍼가 돌려주는 맨 위 키는 모두 스키마에 있다 — 없는 키 하나면 저장이 통째로 막힌다.
    매퍼 원문에서 map_to_bibliography가 만드는 dict의 키를 읽어 스키마 properties와 견준다.

    못 보는 것(Codex 리뷰 2026-10-12): `bib["x"] = …`·`update()`·`**other`·계산된 키·`dict(...)`, 다른 이름의 도우미가
    만드는 dict, 하위 폴더 매퍼. 실제 출력은 매퍼별 시험(B-033 셋·B-079 KORCIS)이 스키마로 검증한다."""
    import ast

    props = set(_schema("source_repo/bibliography.schema.json")["properties"])
    bad = []
    for f in sorted((ROOT / "src" / "parsers").glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef) and fn.name.startswith(("map_to_bibliography", "_map_")):
                for node in ast.walk(fn):
                    keys = [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)] if isinstance(node, ast.Dict) else []
                    # 출처 기록(field_sources)의 《creator.name》처럼 점 든 키는 서지 본문 키가 아니라 건너뛴다 —
                    # dict 통째로가 아니라 그 키만(통째로 빼면 같은 dict의 진짜 잘못된 키까지 놓친다)
                    if "title" in keys:
                        for k in keys:
                            if "." not in k and k not in props:
                                bad.append(f"{f.name}:{fn.name}:{k}")
    assert bad == [], bad
