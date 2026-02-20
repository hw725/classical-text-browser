"""범용 에셋 감지 유틸리티 테스트.

테스트 대상: src/parsers/asset_detector.py
- detect_assets_from_markdown(): 마크다운에서 PDF/이미지 링크 추출
- _group_images_into_bundles(): 이미지 번들 그룹핑
- _resolve_url(): 상대→절대 URL 변환
- _label_from_url(): URL에서 라벨 추출
- _get_file_extension(): 확장자 추출
"""

import pytest
import asyncio

# 테스트 대상 모듈
from parsers.asset_detector import (
    detect_assets_from_markdown,
    detect_assets,
    _resolve_url,
    _label_from_url,
    _get_file_extension,
    _group_images_into_bundles,
    _url_to_asset_id,
)


# ── _get_file_extension 테스트 ──────────────────

class TestGetFileExtension:
    def test_pdf(self):
        assert _get_file_extension("/docs/file.pdf") == ".pdf"

    def test_pdf_with_query(self):
        assert _get_file_extension("/docs/file.pdf?v=1") == ".pdf"

    def test_jpg(self):
        assert _get_file_extension("/images/page.jpg") == ".jpg"

    def test_tiff(self):
        assert _get_file_extension("/images/scan.tiff") == ".tiff"

    def test_no_extension(self):
        assert _get_file_extension("/api/download") == ""

    def test_fragment(self):
        assert _get_file_extension("/docs/file.pdf#page=1") == ".pdf"

    def test_long_extension_ignored(self):
        """8자 이상의 확장자는 확장자로 인식하지 않는다."""
        assert _get_file_extension("/path/something.verylongext") == ""


# ── _resolve_url 테스트 ──────────────────────────

class TestResolveUrl:
    def test_absolute_url(self):
        result = _resolve_url(
            "https://example.com/file.pdf",
            "https://base.com/page",
        )
        assert result == "https://example.com/file.pdf"

    def test_relative_url(self):
        result = _resolve_url(
            "docs/file.pdf",
            "https://example.com/catalog/item.html",
        )
        assert result == "https://example.com/catalog/docs/file.pdf"

    def test_root_relative_url(self):
        result = _resolve_url(
            "/downloads/file.pdf",
            "https://example.com/catalog/item.html",
        )
        assert result == "https://example.com/downloads/file.pdf"

    def test_data_url_excluded(self):
        assert _resolve_url("data:image/png;base64,xxx", "https://x.com") is None

    def test_javascript_excluded(self):
        assert _resolve_url("javascript:void(0)", "https://x.com") is None

    def test_empty_url(self):
        assert _resolve_url("", "https://x.com") is None


# ── _label_from_url 테스트 ──────────────────────

class TestLabelFromUrl:
    def test_simple_filename(self):
        assert _label_from_url("https://example.com/docs/論語_全.pdf") == "論語_全.pdf"

    def test_encoded_filename(self):
        label = _label_from_url("https://example.com/docs/%E8%AB%96%E8%AA%9E.pdf")
        assert "論語" in label

    def test_no_filename(self):
        assert _label_from_url("https://example.com/") == "download"


# ── detect_assets_from_markdown 테스트 ──────────

class TestDetectAssetsFromMarkdown:
    @pytest.fixture
    def base_url(self):
        return "https://library.example.ac.jp/catalog/item123"

    @pytest.mark.asyncio
    async def test_pdf_links(self, base_url):
        """마크다운에서 PDF 링크를 감지한다."""
        markdown = """
# 문헌 상세

- [원문 PDF 다운로드](https://library.example.ac.jp/files/monggu.pdf)
- [해제 PDF](https://library.example.ac.jp/files/monggu_intro.pdf)
"""
        assets = await detect_assets_from_markdown(markdown, base_url)
        pdfs = [a for a in assets if a["download_type"] == "pdf"]
        assert len(pdfs) == 2
        assert pdfs[0]["download_url"].endswith("monggu.pdf")
        assert pdfs[1]["download_url"].endswith("monggu_intro.pdf")
        # 라벨은 마크다운 링크 텍스트
        assert pdfs[0]["label"] == "원문 PDF 다운로드"

    @pytest.mark.asyncio
    async def test_image_bundle(self, base_url):
        """같은 디렉토리의 이미지 2개 이상은 번들로 그룹핑한다."""
        markdown = """
![page1](https://img.example.com/scans/page_001.jpg)
![page2](https://img.example.com/scans/page_002.jpg)
![page3](https://img.example.com/scans/page_003.jpg)
"""
        assets = await detect_assets_from_markdown(markdown, base_url)
        bundles = [a for a in assets if a["download_type"] == "image_bundle"]
        assert len(bundles) == 1
        assert bundles[0]["page_count"] == 3
        assert len(bundles[0]["download_urls"]) == 3

    @pytest.mark.asyncio
    async def test_single_image_not_bundled(self, base_url):
        """이미지가 1개뿐이면 번들로 만들지 않는다."""
        markdown = "[표지](https://img.example.com/cover/front.jpg)"
        assets = await detect_assets_from_markdown(markdown, base_url)
        images = [a for a in assets if a["download_type"] == "image"]
        assert len(images) == 1
        assert images[0]["download_url"].endswith("front.jpg")

    @pytest.mark.asyncio
    async def test_decorative_images_excluded(self, base_url):
        """로고, 아이콘 등 장식 이미지는 제외한다."""
        markdown = """
![logo](https://example.com/images/logo.png)
![icon](https://example.com/images/nav_icon.jpg)
![page](https://example.com/scans/page_001.jpg)
"""
        assets = await detect_assets_from_markdown(markdown, base_url)
        # logo, icon은 제외되고 page만 남아야 함
        urls = [a.get("download_url", "") for a in assets]
        assert any("page_001" in u for u in urls)
        assert not any("logo" in u for u in urls)
        assert not any("icon" in u for u in urls)

    @pytest.mark.asyncio
    async def test_duplicate_urls_removed(self, base_url):
        """같은 URL이 여러 번 나와도 1번만 포함한다."""
        markdown = """
[PDF 1](https://example.com/file.pdf)
[같은 PDF](https://example.com/file.pdf)
"""
        assets = await detect_assets_from_markdown(markdown, base_url)
        assert len(assets) == 1

    @pytest.mark.asyncio
    async def test_relative_urls_resolved(self, base_url):
        """상대 URL이 절대 URL로 변환된다."""
        markdown = "[PDF](/downloads/monggu.pdf)"
        assets = await detect_assets_from_markdown(markdown, base_url)
        assert len(assets) == 1
        assert assets[0]["download_url"].startswith("https://library.example.ac.jp/")

    @pytest.mark.asyncio
    async def test_bare_urls(self, base_url):
        """마크다운 링크가 아닌 bare URL도 감지한다."""
        markdown = """
다운로드: https://example.com/documents/text.pdf
"""
        assets = await detect_assets_from_markdown(markdown, base_url)
        pdfs = [a for a in assets if a["download_type"] == "pdf"]
        assert len(pdfs) == 1

    @pytest.mark.asyncio
    async def test_mixed_pdfs_and_images(self, base_url):
        """PDF와 이미지가 섞여 있을 때 각각 감지한다."""
        markdown = """
[원문](https://example.com/docs/text.pdf)
![page1](https://example.com/scans/p1.jpg)
![page2](https://example.com/scans/p2.jpg)
"""
        assets = await detect_assets_from_markdown(markdown, base_url)
        pdfs = [a for a in assets if a["download_type"] == "pdf"]
        bundles = [a for a in assets if a["download_type"] == "image_bundle"]
        assert len(pdfs) == 1
        assert len(bundles) == 1

    @pytest.mark.asyncio
    async def test_empty_markdown(self, base_url):
        """빈 마크다운은 빈 리스트를 반환한다."""
        assets = await detect_assets_from_markdown("", base_url)
        assert assets == []


# ── _group_images_into_bundles 테스트 ───────────

class TestGroupImagesIntoBundles:
    def test_same_directory_grouped(self):
        """같은 디렉토리의 이미지가 번들로 묶인다."""
        links = [
            ("p1", "https://a.com/scans/p1.jpg"),
            ("p2", "https://a.com/scans/p2.jpg"),
            ("p3", "https://a.com/scans/p3.jpg"),
        ]
        result = _group_images_into_bundles(links)
        assert len(result) == 1
        assert result[0]["download_type"] == "image_bundle"
        assert result[0]["page_count"] == 3

    def test_different_directories_separate(self):
        """다른 디렉토리의 이미지는 별도로 처리된다."""
        links = [
            ("a", "https://a.com/dir1/a.jpg"),
            ("b", "https://a.com/dir2/b.jpg"),
        ]
        result = _group_images_into_bundles(links)
        # 각 디렉토리에 1개씩 → 번들 아닌 개별 이미지
        assert len(result) == 2
        assert all(r["download_type"] == "image" for r in result)

    def test_bundle_urls_sorted(self):
        """번들 내 URL은 파일명 순으로 정렬된다."""
        links = [
            ("p3", "https://a.com/s/p3.jpg"),
            ("p1", "https://a.com/s/p1.jpg"),
            ("p2", "https://a.com/s/p2.jpg"),
        ]
        result = _group_images_into_bundles(links)
        assert len(result) == 1
        urls = result[0]["download_urls"]
        assert "p1" in urls[0]
        assert "p2" in urls[1]
        assert "p3" in urls[2]

    def test_empty_list(self):
        """빈 리스트는 빈 결과를 반환한다."""
        assert _group_images_into_bundles([]) == []


# ── _url_to_asset_id 테스트 ─────────────────────

class TestUrlToAssetId:
    def test_deterministic(self):
        """같은 URL은 항상 같은 ID를 생성한다."""
        url = "https://example.com/file.pdf"
        assert _url_to_asset_id(url) == _url_to_asset_id(url)

    def test_different_urls_different_ids(self):
        """다른 URL은 다른 ID를 생성한다."""
        id1 = _url_to_asset_id("https://example.com/a.pdf")
        id2 = _url_to_asset_id("https://example.com/b.pdf")
        assert id1 != id2

    def test_length(self):
        """ID는 12자이다."""
        assert len(_url_to_asset_id("https://example.com/file.pdf")) == 12
