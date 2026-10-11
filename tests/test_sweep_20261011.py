# ruff: noqa: E501 — 한글 docstring·JS 스텁 줄은 쪼개면 읽기 어렵다
"""2026-10-11 전수 검토가 찾은 결함의 회귀 시험 (backlog B-012~B-035).

왜 한 파일인가:
    전수 검토(442파일)에서 나온 결함을 «고치기 전에 빨간불»로 먼저 세우고, 고친 뒤 초록이 되는
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


# ── B-012 엔티티 패널 «현재 페이지만» ────────────────────────────────────────────────


def test_b012_page_entities_return_units_under_the_key_the_screen_reads(tmp_path, monkeypatch):
    """B-012: 쪽 엔티티 응답은 단위를 «units»에 담는다 — 화면(entity-manager.js)이 그 키를 읽는다."""
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
    """B-023: L5~L7의 block_id가 단위(경계) id면 «L3에 없음» 경고를 내지 않는다."""
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
    """server.py 머리말처럼 «(N 라우트)»가 다음 줄로 넘어간 표기도 라우터별 수로 대조한다."""
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
        # «𠀀甲»: 화면(Range)의 표시 오프셋 2는 甲 — 코드포인트로는 1
        'console.log(JSON.stringify({i: _citeDisplayOffsetToOriginal(2, "\\u{20000}甲", [])}));',
    )
    assert out["i"] == 1


def test_b016_citation_requests_carry_part_id():
    """B-016: 인용 마크 API 호출은 모두 ?part_id=를 붙인다(다권본에서 «main»으로 새지 않게)."""
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
async function _addManualTranslation() {}
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
    """B-019: 권 전체 OCR도 쪽 OCR처럼 «ocr-llm-model-select»에서 고른 모델을 보낸다."""
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
    """B-026: 이체자 탭에서 고른 사전을 «활성»으로 바꾸는 단추가 있고, 활성화 API를 부른다."""
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
    """범용 서지 추출은 LlmRouter.call 하나로 부르고 JSON을 강제한다(D-010 «라우터가 유일한 진입점»)."""
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
    """PdfTextExtractor는 언제나 with로 연다(AGENTS «fitz.open()은 with로» — Windows가 PDF를 잠근다)."""
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
    files = [*static.rglob("*.css"), *static.rglob("*.js"), *static.rglob("*.html")]
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
    전에는 «시각 + 순번»이라 다시 돌릴 때마다 처음부터 했다(이어 하기 코드가 한 번도 맞지 않았다)."""
    import inspect

    from cli import embed_folder as ef
    from core.repo_id import is_valid_repo_id

    a, b = tmp_path / "가.pdf", tmp_path / "나.pdf"
    ida, ida2, idb = ef._safe_doc_id(a), ef._safe_doc_id(a), ef._safe_doc_id(b)
    assert ida == ida2 and ida != idb
    assert is_valid_repo_id(ida) and is_valid_repo_id(idb)
    loop = inspect.getsource(ef.embed_folder)
    assert "_safe_doc_id(task.path)" in loop and "time.time() * 10" not in loop


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
