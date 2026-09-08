"""서지정보 파서 테스트.

Phase 5: NDL Search, 국립공문서관 파서 동작 확인.
네트워크 접근이 필요한 테스트는 실제 API를 호출한다.
"""

import sys
from pathlib import Path

import pytest

# src/ 디렉토리를 경로에 추가
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)


class TestParserRegistry:
    """파서 레지스트리 테스트."""

    def test_list_parsers(self):
        """등록된 파서 목록이 반환된다."""
        import parsers  # noqa: F401 — 자동 등록 트리거
        from parsers.base import list_parsers

        result = list_parsers()
        assert len(result) >= 2

        ids = [p["id"] for p in result]
        assert "ndl" in ids
        assert "japan_national_archives" in ids

    def test_get_parser(self):
        """parser_id로 fetcher/mapper를 가져올 수 있다."""
        import parsers  # noqa: F401
        from parsers.base import get_parser

        fetcher, mapper = get_parser("ndl")
        assert fetcher.parser_id == "ndl"
        assert mapper.parser_id == "ndl"

    def test_get_parser_not_found(self):
        """존재하지 않는 parser_id는 KeyError."""
        from parsers.base import get_parser

        with pytest.raises(KeyError):
            get_parser("nonexistent")

    def test_registry_json(self):
        """registry.json을 읽을 수 있다."""
        from parsers.base import get_registry_json

        data = get_registry_json()
        assert "parsers" in data
        assert len(data["parsers"]) >= 2


class TestNdlParser:
    """NDL Search 파서 테스트 (네트워크 필요)."""

    @pytest.mark.asyncio
    async def test_search_monggu(self):
        """'蒙求'로 NDL 검색 시 결과가 반환된다."""
        import parsers  # noqa: F401
        from parsers.base import get_parser

        fetcher, _mapper = get_parser("ndl")
        results = await fetcher.search("蒙求", cnt=5)

        assert len(results) > 0
        # 첫 번째 결과에 제목이 있어야 한다
        assert results[0]["title"] is not None
        # raw 데이터가 포함되어야 한다
        assert "raw" in results[0]
        assert results[0]["raw"].get("dc:title") is not None

    @pytest.mark.asyncio
    async def test_map_to_bibliography(self):
        """NDL 검색 결과를 bibliography.json 형식으로 매핑할 수 있다."""
        import parsers  # noqa: F401
        from parsers.base import get_parser

        fetcher, mapper = get_parser("ndl")
        results = await fetcher.search("蒙求", cnt=3)
        assert len(results) > 0

        # 첫 번째 결과를 매핑
        bib = mapper.map_to_bibliography(results[0]["raw"])

        # 필수 필드 확인
        assert "title" in bib
        assert bib["title"] is not None
        assert "raw_metadata" in bib
        assert bib["raw_metadata"]["source_system"] == "ndl"
        assert "_mapping_info" in bib
        assert bib["_mapping_info"]["parser_id"] == "ndl"
        assert bib["_mapping_info"]["api_variant"] == "opensearch"

    @pytest.mark.asyncio
    async def test_mapping_fields(self):
        """매핑된 필드가 bibliography.schema.json 구조를 따른다."""
        import parsers  # noqa: F401
        from parsers.base import get_parser

        fetcher, mapper = get_parser("ndl")
        results = await fetcher.search("蒙求", cnt=1)
        assert len(results) > 0

        bib = mapper.map_to_bibliography(results[0]["raw"])

        # 스키마 필드 존재 확인
        expected_fields = [
            "title",
            "title_reading",
            "alternative_titles",
            "creator",
            "contributors",
            "date_created",
            "edition_type",
            "physical_description",
            "subject",
            "classification",
            "series_title",
            "material_type",
            "repository",
            "digital_source",
            "raw_metadata",
            "_mapping_info",
            "notes",
        ]
        for field in expected_fields:
            assert field in bib, f"필드 누락: {field}"

        # edition_type은 NDL에 없으므로 None
        assert bib["edition_type"] is None

        # digital_source 구조 확인
        if bib["digital_source"]:
            assert bib["digital_source"]["platform"] == "NDL Search (国立国会図書館サーチ)"


class TestNdlMapperUnit:
    """NDL Mapper 단위 테스트 (네트워크 불필요)."""

    def test_map_minimal_data(self):
        """최소 데이터로도 매핑이 성공한다."""
        from parsers.ndl import NdlMapper

        mapper = NdlMapper()
        raw = {"dc:title": "テスト"}

        bib = mapper.map_to_bibliography(raw)
        assert bib["title"] == "テスト"
        assert bib["creator"] is None
        assert bib["edition_type"] is None

    def test_map_full_data(self):
        """전체 필드가 있는 데이터를 매핑한다."""
        from parsers.ndl import NdlMapper

        mapper = NdlMapper()
        raw = {
            "dc:title": "蒙求",
            "dcndl:titleTranscription": "モウギュウ",
            "dc:creator": "李瀚",
            "dcndl:creatorTranscription": "リ カン",
            "dcterms:issued": "2024.2",
            "dc:extent": "174 p",
            "dcndl:materialType": "図書",
            "dcndl:NDLC": "Y84",
            "dcndl:NDC10": "726.1",
            "dcndl:NDLBibID": "033286846",
            "dcndl:seriesTitle": "FUZ comics",
            "rdfs:seeAlso": "https://ndlsearch.ndl.go.jp/books/R100000002-I033286846",
        }

        bib = mapper.map_to_bibliography(raw)
        assert bib["title"] == "蒙求"
        assert bib["title_reading"] == "モウギュウ"
        assert bib["creator"]["name"] == "李瀚"
        assert bib["creator"]["name_reading"] == "リ カン"
        assert bib["date_created"] == "2024.2"
        assert bib["physical_description"] == "174 p"
        assert bib["material_type"] == "図書"
        assert bib["classification"]["NDLC"] == "Y84"
        assert bib["classification"]["NDC10"] == "726.1"
        assert bib["series_title"] == "FUZ comics"
        assert bib["digital_source"]["system_ids"]["NDLBibID"] == "033286846"


@pytest.fixture
def bibliography_client(tmp_path, monkeypatch):
    """입력: 임시 폴더. 출력: 서지 전용 클라이언트. 목적: 실제 서고 격리."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers import documents

    monkeypatch.setattr(documents, "get_library_path", lambda: tmp_path)
    monkeypatch.setattr(documents, "require_repo_path", lambda *args: tmp_path)
    (tmp_path / "bibliography.json").write_text('{"title": "original"}', encoding="utf-8")
    app = FastAPI()
    app.add_api_route("/bib", documents.api_save_bibliography, methods=["PUT"])
    app.add_api_route("/bib", documents.api_bibliography, methods=["GET"])
    with TestClient(app) as client:
        yield client, tmp_path / "bibliography.json"


@pytest.mark.parametrize("failure", ["json", "permission", "list"])
def test_bibliography_read_failure_never_overwrites(bibliography_client, monkeypatch, failure):
    """입력: 읽기 실패. 출력: 오류·파일 보존. 목적: 복구 전 덮어쓰기 방지."""
    from app.routers import documents

    client, path = bibliography_client
    if failure == "permission":

        def unreadable(_path):
            """입력: 경로. 출력: 권한 오류. 목적: 읽기 실패 재현."""
            raise PermissionError("blocked")

        monkeypatch.setattr(documents, "get_bibliography", unreadable)
    else:
        path.write_text("{" if failure == "json" else "[]", encoding="utf-8")
    before = path.read_bytes()
    response = client.put("/bib?doc_id=d1", json={"title": "changed"})
    assert response.status_code == 500
    assert path.read_bytes() == before
    assert client.get("/bib?doc_id=d1").status_code == 500


@pytest.mark.parametrize("human_value", [None, "", "수동 판정"])
def test_bibliography_preserves_explicit_pansik_fields(bibliography_client, human_value):
    """입력: 개별 칸 편집·비우기. 출력: 그대로 저장. 목적: 자동값 우선 방지."""
    client, _ = bibliography_client
    payload = {"printing_info": {"summary": "10行20字", "haengja": human_value}}
    assert client.put("/bib?doc_id=d1", json=payload).status_code == 200
    assert client.get("/bib?doc_id=d1").json()["printing_info"] == payload["printing_info"]
    assert client.put("/bib?doc_id=d1", json={"title": "edited"}).status_code == 200
    assert client.get("/bib?doc_id=d1").json()["printing_info"] == payload["printing_info"]


def test_a_new_catalog_line_replaces_what_it_states_and_keeps_the_rest(bibliography_client):
    """입력: 손으로 적어 둔 판식 위에 새 목록 원문. 출력: 원문이 말한 칸만 바뀐다.

    목적: 목록의 형태사항을 붙여 넣는 까닭은 손으로 적어 둔 값을 바로잡기 위해서다. 그래서
    원문이 말하는 칸은 갈라 담은 값이 이긴다(출처는 summary에 남는다). 원문이 말하지 않는 칸은
    언급되지 않았을 뿐이므로 그대로 둔다(2026-09-09 — Codex는 손으로 적은 값이 언제나 이겨야
    한다고 보았으나, 그러면 목록을 붙여 넣어도 낡은 값이 영영 남는다).
    """
    client, _ = bibliography_client
    before = {"haengja": "수동 판정", "eomi": "무어미"}
    assert client.put("/bib?doc_id=d1", json={"printing_info": before}).status_code == 200
    assert (
        client.put("/bib?doc_id=d1", json={"printing_info": {"summary": "10行20字"}}).status_code
        == 200
    )
    info = client.get("/bib?doc_id=d1").json()["printing_info"]
    assert info["haengja"] == "반엽 10행 20자"  # 원문이 말한 칸 — 새 값이 이긴다
    assert info["eomi"] == "무어미"  # 원문이 말하지 않은 칸 — 그대로
    assert info["summary"] == "10行20字"


def test_bibliography_invalid_existing_pansik_is_rejected(bibliography_client):
    """입력: 스키마 위반 판식. 출력: 오류·원본 보존. 목적: 비정상 종료 방지."""
    client, path = bibliography_client
    path.write_text('{"printing_info": "invalid"}', encoding="utf-8")
    before = path.read_bytes()
    response = client.put("/bib?doc_id=d1", json={"title": "edited"})
    assert response.status_code == 400
    assert path.read_bytes() == before


def test_bibliography_null_and_mapping_round_trip(bibliography_client):
    """입력: 비우기·매핑 출처. 출력: 같은 값. 목적: 실제 저장 계약 확인."""
    client, _ = bibliography_client
    payload = {
        "title": None,
        "printing_info": {"summary": "10行20字"},
        "publishing": {"place": "서울"},
        "extent": {"books": "1冊"},
        "_mapping_info": {"parser_id": "korcis"},
    }
    assert client.put("/bib?doc_id=d1", json=payload).status_code == 200
    payload["printing_info"] = None
    assert client.put("/bib?doc_id=d1", json={"printing_info": None}).status_code == 200
    assert client.get("/bib?doc_id=d1").json() == payload


@pytest.mark.parametrize("printing_info", [{"summary": 10}, {"haengja": []}, {"unknown": "value"}])
def test_bibliography_schema_rejects_invalid_merge(bibliography_client, printing_info):
    """입력: 잘못된 하위 칸. 출력: 400·파일 보존. 목적: 저장 전 스키마 검증."""
    client, path = bibliography_client
    before = path.read_bytes()
    response = client.put("/bib?doc_id=d1", json={"printing_info": printing_info})
    assert response.status_code == 400
    assert path.read_bytes() == before


def test_bibliography_same_loop_saves_keep_disjoint_fields(bibliography_client):
    """입력: 동시 부분 저장. 출력: 두 칸 보존. 목적: 단일 이벤트 루프 계약 확인."""
    import asyncio

    from app.routers.documents import BibliographySaveRequest, api_save_bibliography

    async def save_both():
        """입력: 두 편집값. 출력: 저장 응답. 목적: 같은 루프에 함께 예약."""
        return await asyncio.gather(
            api_save_bibliography("d1", BibliographySaveRequest(title="changed")),
            api_save_bibliography("d1", BibliographySaveRequest(notes="retained")),
        )

    assert all(result["status"] == "saved" for result in asyncio.run(save_both()))
    client, _ = bibliography_client
    assert client.get("/bib?doc_id=d1").json() == {"title": "changed", "notes": "retained"}


def test_bibliography_request_accepts_every_schema_field():
    """입력: 스키마의 모든 칸. 출력: 같은 요청. 목적: 조용한 누락 방지."""
    import json
    from pathlib import Path

    from app.routers.documents import BibliographySaveRequest

    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/source_repo/bibliography.schema.json").read_text(
            encoding="utf-8"
        )
    )
    payload = dict.fromkeys(schema["properties"])
    payload["_mapping_info"] = {"parser_id": "korcis"}
    request = BibliographySaveRequest.model_validate(payload)
    assert request.model_dump(exclude_unset=True, by_alias=True) == payload


def test_saving_bibliography_keeps_and_parses_pansik(tmp_path, monkeypatch):
    """입력: 판식이 있는 문헌에 제목만 고쳐 저장. 출력: 판식 보존·구조화.

    목적: 화면이 모르는 칸을 지우지 않는다. 전에는 저장 요청 모델에 printing_info·publishing·
    extent가 없어, 제목만 고쳐도 그 셋이 사라졌다(2026-09-08 확인).
    """
    from fastapi.testclient import TestClient

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    from app.server import app

    with TestClient(app) as client:
        assert client.post("/api/library/quick-start").status_code == 200
        import fitz

        pdf = tmp_path / "t.pdf"
        doc = fitz.open()
        doc.new_page(width=400, height=600)
        doc.save(str(pdf))
        with open(pdf, "rb") as f:
            r = client.post(
                "/api/documents/create-from-files",
                data={"doc_id": "d1", "title": "책"},
                files=[("files", ("t.pdf", f.read(), "application/pdf"))],
            )
        assert r.status_code == 200, r.text

        # ① 판식 원문을 붙여 넣어 저장 — 서버가 갈라 담는다
        r = client.put(
            "/api/documents/d1/bibliography",
            json={
                "title": "책",
                "printing_info": {"summary": "四周雙邊 半郭 19.1 x 14.6 cm, 10行20字 註雙行"},
            },
        )
        assert r.status_code == 200, r.text
        info = client.get("/api/documents/d1/bibliography").json()["printing_info"]
        assert info["haengja"] == "반엽 10행 20자"
        assert info["ju_haengja"] == "주쌍행"

        # ② 화면이 판식을 모르는 채 제목만 고쳐 보내도 지워지지 않는다
        r = client.put("/api/documents/d1/bibliography", json={"title": "고친 제목"})
        assert r.status_code == 200, r.text
        again = client.get("/api/documents/d1/bibliography").json()
        assert again["title"] == "고친 제목"
        assert again["printing_info"]["haengja"] == "반엽 10행 20자"


def test_correcting_the_pansik_line_replaces_the_split_fields(tmp_path, monkeypatch):
    """입력: 판식 원문을 고쳐 다시 저장. 출력: 갈라 담은 칸도 새 값.

    목적: 화면은 기존 printing_info를 그대로 안고 새 summary만 얹어 보낸다. 병합 순서가
    거꾸로면 원문만 바뀌고 광곽·행자수는 옛 값으로 남는다(2026-09-09 확인).
    원문이 그대로일 때 사람이 개별 칸을 손본 것은 반대로 그 손질이 이겨야 한다.
    """
    from fastapi.testclient import TestClient

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    from app.server import app

    with TestClient(app) as client:
        assert client.post("/api/library/quick-start").status_code == 200
        import fitz

        pdf = tmp_path / "t.pdf"
        doc = fitz.open()
        doc.new_page(width=400, height=600)
        doc.save(str(pdf))
        with open(pdf, "rb") as f:
            r = client.post(
                "/api/documents/create-from-files",
                data={"doc_id": "d1", "title": "책"},
                files=[("files", ("t.pdf", f.read(), "application/pdf"))],
            )
        assert r.status_code == 200, r.text

        def put(info):
            res = client.put("/api/documents/d1/bibliography", json={"printing_info": info})
            assert res.status_code == 200, res.text
            return client.get("/api/documents/d1/bibliography").json()["printing_info"]

        first = put({"summary": "四周雙邊 10行20字"})
        assert first["gwangwak"] == "사주쌍변" and first["haengja"] == "반엽 10행 20자"

        # ① 원문을 고쳐 다시 — 화면처럼 옛 값을 안고 새 원문만 얹어 보낸다
        corrected = put({**first, "summary": "四周單邊 12行24字"})
        assert corrected["gwangwak"] == "사주단변"
        assert corrected["haengja"] == "반엽 12행 24자"

        # ② 원문은 그대로 두고 사람이 한 칸만 손봤다 — 그 손질이 이긴다
        touched = put({**corrected, "gwangwak": "좌우쌍변"})
        assert touched["gwangwak"] == "좌우쌍변"
        assert touched["haengja"] == "반엽 12행 24자"
