"""범용 에셋(PDF/이미지) 감지 및 다운로드 유틸리티.

서지 웹페이지에서 다운로드 가능한 PDF 링크나 이미지 파일 묶음을
자동으로 감지하고 다운로드한다.

왜 이렇게 하는가:
    국립공문서관(archives_jp)만 전용 에셋 다운로더가 있었는데,
    다른 기관의 서지 페이지에서도 PDF/이미지를 자동 감지하여
    수동 다운로드 없이 문헌을 생성할 수 있게 한다.

사용법:
    # 에셋 감지
    assets = await detect_assets(url, page_markdown)

    # 에셋 다운로드
    for asset in assets:
        path = await download_generic_asset(asset, dest_dir)
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlparse, unquote

import httpx

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────

# 감지할 파일 확장자
PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

# 장식 이미지(아이콘/로고)를 제외하기 위한 파일명 패턴
# 이런 파일명은 보통 콘텐츠 이미지가 아니라 UI 요소다.
_DECORATIVE_PATTERNS = re.compile(
    r"(logo|icon|favicon|banner|button|arrow|bg|background|"
    r"header|footer|nav|menu|thumb_small|pixel|spacer|"
    r"sprite|badge|avatar)",
    re.IGNORECASE,
)

# 마크다운에서 링크를 추출하는 정규식
# [text](url) 형식 — 이미지 ![alt](url) 포함
_MD_LINK_RE = re.compile(
    r"!?\[([^\]]*)\]\(([^)\s]+(?:\s+\"[^\"]*\")?)\)"
)

# bare URL (http/https로 시작하는 URL)
_BARE_URL_RE = re.compile(
    r"(?<!\()"  # 괄호 안이 아닌 것
    r"(https?://[^\s<>)\]\"']+)"
)

# HTTP 클라이언트 공통 설정
_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ClassicalTextPlatform/1.0)"
}


# ── 에셋 감지 함수 ──────────────────────────────────

async def detect_direct_download(url: str) -> dict[str, Any] | None:
    """URL 자체가 다운로드 가능한 파일(PDF/이미지)인지 확인한다.

    입력:
        url — 확인할 URL.
    출력:
        에셋 정보 dict 또는 None (다운로드 가능한 파일이 아니면).

    처리 흐름:
        1. URL 확장자로 1차 판별
        2. HEAD 요청으로 Content-Type 확인
        3. 파일 크기(Content-Length) 가져오기
    """
    parsed = urlparse(url)
    path_lower = parsed.path.lower()

    # 1. 확장자로 1차 판별
    ext = _get_file_extension(path_lower)
    is_pdf_ext = ext in PDF_EXTENSIONS
    is_image_ext = ext in IMAGE_EXTENSIONS

    if not is_pdf_ext and not is_image_ext:
        # 확장자가 없으면 HEAD 요청으로 Content-Type 확인
        try:
            async with httpx.AsyncClient(
                timeout=_HTTP_TIMEOUT,
                headers=_HTTP_HEADERS,
                follow_redirects=True,
            ) as client:
                resp = await client.head(url)
                content_type = resp.headers.get("content-type", "").lower()
                if "application/pdf" in content_type:
                    is_pdf_ext = True
                elif any(t in content_type for t in ("image/jpeg", "image/png", "image/tiff")):
                    is_image_ext = True
                else:
                    return None
        except Exception as e:
            logger.debug(f"HEAD 요청 실패 (에셋 감지 건너뜀): {url} — {e}")
            return None

    # 2. 파일 크기 가져오기 (가능하면)
    file_size = None
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            headers=_HTTP_HEADERS,
            follow_redirects=True,
        ) as client:
            resp = await client.head(url)
            cl = resp.headers.get("content-length")
            if cl:
                file_size = int(cl)
    except Exception:
        pass

    # 3. 에셋 정보 반환
    label = _label_from_url(url)
    download_type = "pdf" if is_pdf_ext else "image"

    return {
        "asset_id": _url_to_asset_id(url),
        "id": _url_to_asset_id(url),
        "label": label,
        "page_count": None,
        "file_size": file_size,
        "download_type": download_type,
        "download_url": url,
    }


async def detect_assets_from_markdown(
    markdown: str, base_url: str
) -> list[dict[str, Any]]:
    """마크다운 텍스트에서 PDF/이미지 링크를 추출한다.

    입력:
        markdown — 웹페이지를 변환한 마크다운 텍스트.
        base_url — 상대 URL을 절대 URL로 변환하기 위한 기준 URL.
    출력:
        에셋 정보 dict 리스트.

    처리 흐름:
        1. 마크다운 링크 [text](url) 추출
        2. bare URL 추출
        3. 확장자로 PDF/이미지 필터링
        4. 장식 이미지(로고/아이콘) 제외
        5. 이미지 번들 그룹핑 (같은 디렉토리의 이미지 2개 이상 → 1개 번들)
        6. 중복 URL 제거
    """
    if not markdown:
        return []

    # 1+2. 모든 URL 수집
    found_links: list[tuple[str, str]] = []  # (label, absolute_url)

    # 마크다운 링크 [text](url "title") — title 부분 제거
    for match in _MD_LINK_RE.finditer(markdown):
        label = match.group(1).strip()
        raw_url = match.group(2).strip()
        # "title" 부분 제거
        if raw_url.endswith('"'):
            raw_url = raw_url.rsplit('"', 2)[0].strip()
        abs_url = _resolve_url(raw_url, base_url)
        if abs_url:
            found_links.append((label, abs_url))

    # bare URL
    for match in _BARE_URL_RE.finditer(markdown):
        raw_url = match.group(1).strip()
        # 마크다운 링크 안의 URL은 이미 수집했으므로 건너뜀
        abs_url = _resolve_url(raw_url, base_url)
        if abs_url:
            found_links.append(("", abs_url))

    # 3. 확장자로 필터링 + 분류
    seen_urls: set[str] = set()
    pdf_assets: list[dict[str, Any]] = []
    image_links: list[tuple[str, str]] = []  # (label, url)

    for label, abs_url in found_links:
        # URL 정규화 (쿼리 파라미터 포함하여 중복 체크)
        norm_url = abs_url.split("#")[0]  # fragment 제거
        if norm_url in seen_urls:
            continue

        ext = _get_file_extension(urlparse(abs_url).path.lower())

        if ext in PDF_EXTENSIONS:
            seen_urls.add(norm_url)
            pdf_label = label or _label_from_url(abs_url)
            pdf_assets.append({
                "asset_id": _url_to_asset_id(abs_url),
                "id": _url_to_asset_id(abs_url),
                "label": pdf_label,
                "page_count": None,
                "file_size": None,
                "download_type": "pdf",
                "download_url": abs_url,
            })

        elif ext in IMAGE_EXTENSIONS:
            # 장식 이미지 제외
            filename = urlparse(abs_url).path.split("/")[-1]
            if _DECORATIVE_PATTERNS.search(filename):
                continue
            seen_urls.add(norm_url)
            image_links.append((label, abs_url))

    # 5. 이미지 번들 그룹핑
    image_assets = _group_images_into_bundles(image_links)

    # PDF 먼저, 이미지 번들 나중에
    return pdf_assets + image_assets


async def detect_assets(
    url: str, page_markdown: str | None = None
) -> list[dict[str, Any]]:
    """메인 진입점: URL 직접 감지 + 페이지 내 링크 감지.

    입력:
        url — 대상 URL.
        page_markdown — 페이지의 마크다운 텍스트 (이미 변환된 것이 있으면).
    출력:
        에셋 정보 dict 리스트.

    처리 흐름:
        1. URL 자체가 파일인지 확인 (detect_direct_download)
        2. 페이지 마크다운에서 링크 감지 (detect_assets_from_markdown)
        3. 결과 병합
    """
    assets: list[dict[str, Any]] = []

    # 1. URL 자체가 다운로드 가능한 파일인지
    direct = await detect_direct_download(url)
    if direct:
        # URL 자체가 파일이면 페이지 스캔 불필요
        return [direct]

    # 2. 페이지 마크다운에서 링크 감지
    if page_markdown:
        page_assets = await detect_assets_from_markdown(page_markdown, url)
        assets.extend(page_assets)

    return assets


# ── 에셋 다운로드 함수 ──────────────────────────────

async def download_generic_asset(
    asset_info: dict[str, Any],
    dest_dir: Path,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Path:
    """범용 에셋을 다운로드한다.

    입력:
        asset_info — detect_assets()가 반환한 에셋 항목.
            필수 키: download_url, download_type, label
        dest_dir — 파일을 저장할 디렉토리.
        progress_callback — (current, total)를 받는 진행 콜백.
    출력:
        다운로드된 파일의 Path.

    처리 흐름:
        download_type에 따라:
        - "pdf": HTTP GET → 저장
        - "image": HTTP GET → 저장
        - "image_bundle": 이미지들 다운로드 → fpdf2로 PDF 병합
    """
    download_type = asset_info.get("download_type", "pdf")
    label = asset_info.get("label", "download")

    if download_type == "image_bundle":
        return await _download_image_bundle(asset_info, dest_dir, progress_callback)
    else:
        return await _download_single_file(asset_info, dest_dir, progress_callback)


async def _download_single_file(
    asset_info: dict[str, Any],
    dest_dir: Path,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Path:
    """단일 파일(PDF 또는 이미지)을 다운로드한다.

    입력:
        asset_info — download_url, label, download_type 포함.
        dest_dir — 저장 디렉토리.
    출력:
        다운로드된 파일의 Path.
    """
    url = asset_info["download_url"]
    label = asset_info.get("label", "download")
    download_type = asset_info.get("download_type", "pdf")

    # 확장자 결정
    ext = _get_file_extension(urlparse(url).path.lower())
    if not ext:
        ext = ".pdf" if download_type == "pdf" else ".jpg"

    safe_name = _sanitize_filename(label)
    file_path = dest_dir / f"{safe_name}{ext}"

    logger.info(f"다운로드 시작: {url} → {file_path.name}")

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(120.0, connect=15.0),
        headers=_HTTP_HEADERS,
        follow_redirects=True,
    ) as client:
        # 스트리밍 다운로드 (대용량 PDF 대응)
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            total_size = int(resp.headers.get("content-length", 0))
            downloaded = 0

            with open(file_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        progress_callback(downloaded, total_size)

    logger.info(
        "다운로드 완료: %s (%.1fMB)",
        file_path.name,
        file_path.stat().st_size / 1024 / 1024,
    )
    return file_path


async def _download_image_bundle(
    asset_info: dict[str, Any],
    dest_dir: Path,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Path:
    """이미지 묶음을 다운로드하고 PDF로 병합한다.

    입력:
        asset_info — download_urls(리스트), label 포함.
        dest_dir — 저장 디렉토리.
    출력:
        병합된 PDF 파일의 Path.

    처리 흐름:
        1. 각 이미지 URL을 순서대로 다운로드
        2. fpdf2 + PIL로 이미지 → PDF 페이지 변환
        3. 단일 PDF로 출력
        (archives_jp.py의 JPEG→PDF 변환 패턴과 동일)
    """
    from fpdf import FPDF
    from PIL import Image

    urls: list[str] = asset_info.get("download_urls", [])
    label = asset_info.get("label", "images")
    total = len(urls)

    if not urls:
        raise ValueError("이미지 번들에 URL이 없습니다.")

    # 1. 이미지 다운로드
    image_paths: list[Path] = []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=15.0),
        headers=_HTTP_HEADERS,
        follow_redirects=True,
    ) as client:
        for i, img_url in enumerate(urls):
            ext = _get_file_extension(urlparse(img_url).path.lower()) or ".jpg"
            img_path = dest_dir / f"_bundle_{i:04d}{ext}"

            resp = await client.get(img_url)
            resp.raise_for_status()
            img_path.write_bytes(resp.content)
            image_paths.append(img_path)

            if progress_callback:
                progress_callback(i + 1, total)

    # 2. 이미지 → PDF 변환 (archives_jp.py 패턴 재사용)
    pdf = FPDF(unit="pt")
    for img_path in image_paths:
        with Image.open(img_path) as img:
            # RGBA/L/P → RGB 변환 (fpdf2 호환)
            if img.mode != "RGB":
                img = img.convert("RGB")
                rgb_path = img_path.with_suffix(".conv.jpg")
                img.save(str(rgb_path), "JPEG", quality=95)
                img_path = rgb_path
            w_px, h_px = img.size

        # 150dpi 기준으로 변환 (고서 스캔 해상도)
        w_pt = w_px * 72 / 150
        h_pt = h_px * 72 / 150
        pdf.add_page(format=(w_pt, h_pt))
        pdf.image(str(img_path), x=0, y=0, w=w_pt, h=h_pt)

    safe_name = _sanitize_filename(label)
    pdf_path = dest_dir / f"{safe_name}.pdf"
    pdf.output(str(pdf_path))

    logger.info(
        "이미지 번들 PDF 생성 완료: %s (%d페이지, %.1fMB)",
        pdf_path.name,
        total,
        pdf_path.stat().st_size / 1024 / 1024,
    )
    return pdf_path


# ── 내부 유틸리티 ──────────────────────────────────

def _get_file_extension(path: str) -> str:
    """URL 경로에서 파일 확장자를 추출한다.

    쿼리 파라미터를 제거하고 확장자만 반환한다.
    예: "/docs/file.pdf?v=1" → ".pdf"
    """
    # 쿼리 파라미터 제거
    clean = path.split("?")[0].split("#")[0]
    if "." in clean:
        ext = "." + clean.rsplit(".", 1)[-1].lower()
        # 확장자가 너무 길면(8자 이상) 확장자가 아님
        if len(ext) <= 8:
            return ext
    return ""


def _resolve_url(raw_url: str, base_url: str) -> str | None:
    """상대 URL을 절대 URL로 변환한다.

    입력:
        raw_url — 마크다운에서 추출한 URL (상대 또는 절대).
        base_url — 기준 URL.
    출력:
        절대 URL. 변환 불가능하면 None.
    """
    if not raw_url:
        return None

    # data: URL, javascript: URL 제외
    if raw_url.startswith(("data:", "javascript:", "mailto:", "#")):
        return None

    try:
        resolved = urljoin(base_url, raw_url)
        parsed = urlparse(resolved)
        if parsed.scheme in ("http", "https"):
            return resolved
    except Exception:
        pass

    return None


def _label_from_url(url: str) -> str:
    """URL에서 사람이 읽을 수 있는 라벨을 추출한다.

    예: "https://example.com/docs/論語_全.pdf" → "論語_全.pdf"
    """
    parsed = urlparse(url)
    path = unquote(parsed.path)
    filename = path.split("/")[-1] if "/" in path else path
    return filename or "download"


def _url_to_asset_id(url: str) -> str:
    """URL에서 짧은 에셋 ID를 생성한다.

    URL의 MD5 해시 앞 12자를 사용한다.
    왜: asset_id는 select/filter 키로 사용되므로 짧고 고유해야 한다.
    """
    return hashlib.md5(url.encode()).hexdigest()[:12]


def _sanitize_filename(name: str) -> str:
    """파일명에 사용할 수 없는 문자를 제거한다.

    archives_jp.py의 _sanitize_filename과 동일한 패턴.
    """
    # 파일 시스템 금지 문자 제거
    safe = re.sub(r'[<>:"/\\|?*]', "_", name)
    # 연속 밑줄 정리
    safe = re.sub(r"_+", "_", safe).strip("_")
    # 빈 문자열이면 기본값
    return safe or "download"


def _group_images_into_bundles(
    image_links: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """이미지 링크들을 디렉토리 기준으로 번들 그룹핑한다.

    입력:
        image_links — (label, url) 튜플 리스트.
    출력:
        에셋 정보 dict 리스트.

    그룹핑 규칙:
        - 같은 디렉토리 경로의 이미지 2개 이상 → 1개 image_bundle
        - 1개만 있는 이미지 → 개별 image 에셋
        - 번들 라벨: 디렉토리 이름 사용

    왜 이렇게 하는가:
        학술 기관 사이트에서 한 문헌의 페이지 이미지들은 보통
        같은 디렉토리에 순번 파일명(page_001.jpg, page_002.jpg)으로 저장된다.
        이를 자동으로 묶어서 PDF로 변환하면 연구자가 편리하다.
    """
    if not image_links:
        return []

    # 디렉토리별 그룹핑
    dir_groups: dict[str, list[tuple[str, str]]] = {}
    for label, url in image_links:
        parsed = urlparse(url)
        dir_path = "/".join(parsed.path.split("/")[:-1])
        dir_key = f"{parsed.netloc}{dir_path}"
        dir_groups.setdefault(dir_key, []).append((label, url))

    assets: list[dict[str, Any]] = []

    for dir_key, links in dir_groups.items():
        if len(links) >= 2:
            # 번들로 그룹핑
            urls = [url for _, url in links]
            # URL 순서 정렬 (파일명 기준 자연 정렬)
            urls.sort(key=lambda u: urlparse(u).path)

            # 라벨: 디렉토리 이름
            dir_name = dir_key.split("/")[-1] if "/" in dir_key else dir_key
            bundle_label = unquote(dir_name) or "이미지 묶음"
            bundle_label = f"{bundle_label} ({len(urls)}장)"

            # 번들 ID: 첫 URL의 해시
            bundle_id = _url_to_asset_id(urls[0]) + "_bundle"

            assets.append({
                "asset_id": bundle_id,
                "id": bundle_id,
                "label": bundle_label,
                "page_count": len(urls),
                "file_size": None,
                "download_type": "image_bundle",
                "download_urls": urls,
            })
        else:
            # 개별 이미지
            label, url = links[0]
            img_label = label or _label_from_url(url)
            assets.append({
                "asset_id": _url_to_asset_id(url),
                "id": _url_to_asset_id(url),
                "label": img_label,
                "page_count": 1,
                "file_size": None,
                "download_type": "image",
                "download_url": url,
            })

    return assets
